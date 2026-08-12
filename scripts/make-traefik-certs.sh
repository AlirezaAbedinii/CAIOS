#!/usr/bin/env bash
# Produce the wildcard certificate bundle the Traefik Ansible role expects.
#
#   bash scripts/make-traefik-certs.sh
#
# Output: /home/ubuntu/caios-deployments.zip on the Ansible master, containing
# exactly two files named domain.key and domain.pem. The names are not
# negotiable — roles/nomad/tasks/traefik_service.yml copies them by name, and
# warns rather than fails if they are missing, so a wrong name produces a
# Traefik that starts fine and serves no certificate.
#
# MVP uses a self-signed certificate. Let's Encrypt issues wildcards only over
# DNS-01, which needs API control of the zone, and we do not control sslip.io.
# The cost is a browser warning on first visit. V1 swaps in a real domain and a
# real wildcard; nothing else about the setup changes.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

ENV_FILE="configs/env/caios.env"
[[ -f "$ENV_FILE" ]] || { echo "Missing $ENV_FILE — see configs/env/caios.env.template"; exit 1; }
set -a; source "$ENV_FILE"; set +a
: "${CAIOS_EDGE_IP:?CAIOS_EDGE_IP (Traefik node floating IP) is empty}"

# Must match `domain=` in ansible/inventory/hosts.ini and lb.domain in
# configs/papi/main.yaml. A deployment resolves as:
#   <service>-<uuid>.<meta.domain>-<lb.domain>
# so the wildcard covers one label, not a nested subdomain.
BASE="pacs-deployments.${CAIOS_EDGE_IP}.sslip.io"
OUT="${TRAEFIK_CERT_OUT:-$HOME}"
NAME="caios-deployments"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

echo "==> generating self-signed wildcard for *.${BASE}"

openssl req -x509 -nodes -newkey rsa:2048 -sha256 -days 825 \
    -keyout "$WORK/domain.key" \
    -out "$WORK/domain.pem" \
    -subj "/C=CA/ST=British Columbia/L=Victoria/O=CAIOS/CN=*.${BASE}" \
    -addext "subjectAltName=DNS:*.${BASE},DNS:${BASE}" \
    -addext "basicConstraints=CA:FALSE" \
    -addext "keyUsage=digitalSignature,keyEncipherment" \
    -addext "extendedKeyUsage=serverAuth" \
    2>/dev/null

mkdir -p "$OUT/$NAME"
cp "$WORK/domain.key" "$WORK/domain.pem" "$OUT/$NAME/"

# Python's zipfile rather than the zip(1) binary, which is not installed on a
# stock Ubuntu 22.04 cloud image. Entries are written as "<name>/domain.*" so
# the archive unpacks into the directory the Ansible role expects.
python3 - "$OUT" "$NAME" <<'PY'
import sys, zipfile, pathlib
out, name = pathlib.Path(sys.argv[1]), sys.argv[2]
with zipfile.ZipFile(out / f"{name}.zip", "w", zipfile.ZIP_DEFLATED) as z:
    for fn in ("domain.key", "domain.pem"):
        z.write(out / name / fn, arcname=f"{name}/{fn}")
PY

echo "==> wrote $OUT/${NAME}.zip"
openssl x509 -in "$WORK/domain.pem" -noout -subject -dates \
    -ext subjectAltName | sed 's/^/    /'

cat <<EOF

Next:
  1. group_vars/all.yml already sets  traefik_certs: ${NAME}
     and  path: /home/ubuntu/  — the role looks for \${path}\${traefik_certs}.zip
  2. Re-run  ansible-playbook playbook-nomad.yml  to deploy Traefik with it.

The zip must unpack to a directory named ${NAME}/ containing domain.key and
domain.pem. That is what the role's "creates:" check looks for.
EOF
