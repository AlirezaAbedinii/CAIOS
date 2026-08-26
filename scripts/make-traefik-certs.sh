#!/usr/bin/env bash
# Produce the wildcard certificate bundle the Traefik Ansible role expects,
# signed by a small local CA that we also emit so things can actually trust it.
#
#   bash scripts/make-traefik-certs.sh
#
# Outputs, on the Ansible master:
#   ~/caios-ca.pem              the CA certificate — distribute this
#   ~/caios-ca.key              the CA private key — keep, never distribute
#   ~/caios-deployments.zip     what Ansible ships to the Traefik node
#   ~/caios-deployments/        the same, unpacked
#
# The zip must contain exactly two files named domain.key and domain.pem. The
# names are not negotiable: roles/nomad/tasks/traefik_service.yml copies them by
# name, and only *warns* if they are missing — so a wrong name produces a Traefik
# that starts cleanly and serves no certificate at all.
#
# WHY A CA AND NOT JUST A SELF-SIGNED CERT
# ----------------------------------------
# A bare self-signed certificate is CA:FALSE, which means nothing can be
# configured to trust it — not curl, not Python's requests, not a browser's
# "always trust" option. That is fine until something automated checks HTTPS.
# ai4-nomad_tests does exactly that: it deploys a job per node and fetches it
# through Traefik, and raises "SSL Error: Invalid SSL certificates" on failure.
# Since that suite is also the only thing that marks nodes ready for work, an
# untrustable certificate blocks the whole cluster.
#
# So: issue a CA once, sign the wildcard with it, and hand out the CA. One file
# to trust, in one place, and browsers can import it too.
#
# Let's Encrypt is not an option here. It issues wildcards only over DNS-01,
# which needs control of the zone, and we do not control sslip.io. V1 swaps in a
# real domain; only the two IPs in caios.env change.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

ENV_FILE="configs/env/caios.env"
[[ -f "$ENV_FILE" ]] || { echo "Missing $ENV_FILE — see configs/env/caios.env.template"; exit 1; }
set -a; source "$ENV_FILE"; set +a
: "${CAIOS_EDGE_IP:?CAIOS_EDGE_IP (address of the Traefik node) is empty}"

# Must match `domain=` in ansible/inventory/hosts.ini and lb.domain in
# configs/papi/main.yaml. A deployment resolves as:
#   <service>-<uuid>.<meta.domain>-<lb.domain>
# so the wildcard covers one label, not a nested subdomain.
# Prefer the floating/public IP when set so deployment links and the
# Traefik wildcard match what nginx exposes (docs/public-access.md Step 3/4).
DEPLOY_IP="${CAIOS_PUBLIC_IP:-$CAIOS_EDGE_IP}"
BASE="pacs-deployments.${DEPLOY_IP}.sslip.io"
OUT="${TRAEFIK_CERT_OUT:-$HOME}"
NAME="caios-deployments"
CA_KEY="$OUT/caios-ca.key"
CA_CRT="$OUT/caios-ca.pem"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

# ---------------------------------------------------------------------------
# The CA. Created once and reused: regenerating it would invalidate every
# certificate already trusted anywhere.
# ---------------------------------------------------------------------------
if [[ -f "$CA_KEY" && -f "$CA_CRT" ]]; then
    echo "==> reusing existing CA at $CA_CRT"
else
    echo "==> creating CAIOS local CA (10 years)"
    openssl req -x509 -nodes -newkey rsa:4096 -sha256 -days 3650 \
        -keyout "$CA_KEY" -out "$CA_CRT" \
        -subj "/C=CA/ST=British Columbia/O=CAIOS/CN=CAIOS Local CA" \
        -addext "basicConstraints=critical,CA:TRUE,pathlen:0" \
        -addext "keyUsage=critical,keyCertSign,cRLSign" \
        2>/dev/null
    chmod 600 "$CA_KEY"
fi

# ---------------------------------------------------------------------------
# The wildcard, signed by that CA.
# ---------------------------------------------------------------------------
echo "==> issuing wildcard for *.${BASE}"

openssl req -nodes -newkey rsa:2048 -sha256 \
    -keyout "$WORK/domain.key" -out "$WORK/domain.csr" \
    -subj "/C=CA/ST=British Columbia/O=CAIOS/CN=*.${BASE}" \
    2>/dev/null

cat > "$WORK/ext.cnf" <<EOF
basicConstraints = CA:FALSE
keyUsage = critical,digitalSignature,keyEncipherment
extendedKeyUsage = serverAuth
subjectAltName = DNS:*.${BASE},DNS:${BASE}
EOF

openssl x509 -req -in "$WORK/domain.csr" \
    -CA "$CA_CRT" -CAkey "$CA_KEY" -CAcreateserial \
    -out "$WORK/domain.crt" -days 825 -sha256 \
    -extfile "$WORK/ext.cnf" \
    2>/dev/null

# Traefik's default certificate wants the leaf followed by its chain, so that
# clients holding only the CA can still build a path.
cat "$WORK/domain.crt" "$CA_CRT" > "$WORK/domain.pem"

mkdir -p "$OUT/$NAME"
cp "$WORK/domain.key" "$WORK/domain.pem" "$OUT/$NAME/"
chmod 600 "$OUT/$NAME/domain.key"

# Python's zipfile rather than zip(1), which is not on a stock Ubuntu cloud
# image. Entries are written as "<name>/domain.*" so the archive unpacks into
# the directory the Ansible role expects.
python3 - "$OUT" "$NAME" <<'PY'
import sys, zipfile, pathlib
out, name = pathlib.Path(sys.argv[1]), sys.argv[2]
with zipfile.ZipFile(out / f"{name}.zip", "w", zipfile.ZIP_DEFLATED) as z:
    for fn in ("domain.key", "domain.pem"):
        z.write(out / name / fn, arcname=f"{name}/{fn}")
PY

echo "==> wrote $OUT/${NAME}.zip"
openssl x509 -in "$WORK/domain.crt" -noout -subject -dates -ext subjectAltName \
    | sed 's/^/    /'

echo "==> verifying the chain"
openssl verify -CAfile "$CA_CRT" "$WORK/domain.crt" | sed 's/^/    /'

# Make it trusted for curl and anything else using the system store. Python's
# requests does NOT use this store — it uses certifi — so tooling needs
# REQUESTS_CA_BUNDLE instead. Both are covered below.
if command -v update-ca-certificates >/dev/null && [[ -w /usr/local/share/ca-certificates ]] 2>/dev/null; then
    cp "$CA_CRT" /usr/local/share/ca-certificates/caios-ca.crt && update-ca-certificates >/dev/null 2>&1 || true
elif command -v sudo >/dev/null && sudo -n true 2>/dev/null; then
    sudo cp "$CA_CRT" /usr/local/share/ca-certificates/caios-ca.crt
    sudo update-ca-certificates >/dev/null 2>&1 || true
    echo "==> CA installed into the system trust store"
fi

cat <<EOF

Next:
  1. group_vars/all.yml already sets  traefik_certs: ${NAME}
     and  path: /home/ubuntu/  — the role looks for \${path}\${traefik_certs}.zip
  2. Ship it:  rm -rf ${OUT}/${NAME} && cd ansible && ansible-playbook playbook-nomad.yml --limit caios_edge
     (removing the directory is what makes the role re-extract the new zip)
  3. Restart Traefik so it picks the certificate up.

To trust it:
  * Python tooling (ai4-nomad_tests):  export REQUESTS_CA_BUNDLE=${CA_CRT}
  * curl:                              already works, CA is in the system store
  * A browser:                         import ${CA_CRT} once, as a trusted
                                       authority. Then no warnings anywhere.
EOF
