#!/usr/bin/env bash
# Issue the TLS certificate Caddy serves for the four control-plane hostnames,
# signed by the same CA as the deployment wildcard.
#
#   bash scripts/make-control-plane-cert.sh
#
# Outputs:
#   compose/certs/control-plane.pem   leaf + CA chain
#   compose/certs/control-plane.key   private key
#
# WHY NOT LET CADDY HANDLE IT
# ---------------------------
# Caddy's automatic HTTPS is excellent and we would normally use it. It cannot
# work here: it obtains certificates from Let's Encrypt, which has to reach the
# host from the public internet to verify the challenge, and every node in this
# cluster is on a private subnet behind a VPN. Left enabled, Caddy retries the
# challenge forever and serves nothing usable in the meantime.
#
# Caddy's other fallback is its own internal CA — which works, but would mean a
# SECOND certificate authority to distribute and trust, on top of the one the
# deployments already use. One CA for the whole platform is simpler to explain
# and simpler to install.
#
# So we issue the certificate ourselves from the CA created by
# scripts/make-traefik-certs.sh, and point Caddy at the files.
#
# Re-runnable. Run it again after changing an address in caios.env.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

ENV_FILE="configs/env/caios.env"
[[ -f "$ENV_FILE" ]] || { echo "Missing $ENV_FILE — see configs/env/caios.env.template"; exit 1; }
set -a; source "$ENV_FILE"; set +a
: "${CAIOS_CTRL_IP:?CAIOS_CTRL_IP is empty}"

CA_KEY="${CAIOS_CA_KEY:-$HOME/caios-ca.key}"
CA_CRT="${CAIOS_CA_CRT:-$HOME/caios-ca.pem}"

if [[ ! -f "$CA_KEY" || ! -f "$CA_CRT" ]]; then
    echo "No CA at $CA_CRT."
    echo "Run scripts/make-traefik-certs.sh first — it creates the CA."
    exit 1
fi

OUT="compose/certs"
mkdir -p "$OUT"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

# Also covers the bare IP and localhost, so the same certificate works whether
# you reach the box by hostname, by address, or through an SSH tunnel.
SANS="DNS:${CAIOS_DASHBOARD_HOST},DNS:${CAIOS_API_HOST},DNS:${CAIOS_AUTH_HOST},DNS:${CAIOS_VAULT_HOST},DNS:localhost,IP:${CAIOS_CTRL_IP},IP:127.0.0.1"

echo "==> issuing control-plane certificate"
echo "    $SANS" | tr ',' '\n' | sed 's/^/      /'

openssl req -nodes -newkey rsa:2048 -sha256 \
    -keyout "$WORK/tls.key" -out "$WORK/tls.csr" \
    -subj "/C=CA/ST=British Columbia/O=CAIOS/CN=${CAIOS_DASHBOARD_HOST}" \
    2>/dev/null

cat > "$WORK/ext.cnf" <<EOF
basicConstraints = CA:FALSE
keyUsage = critical,digitalSignature,keyEncipherment
extendedKeyUsage = serverAuth
subjectAltName = ${SANS}
EOF

openssl x509 -req -in "$WORK/tls.csr" \
    -CA "$CA_CRT" -CAkey "$CA_KEY" -CAcreateserial \
    -out "$WORK/tls.crt" -days 825 -sha256 \
    -extfile "$WORK/ext.cnf" \
    2>/dev/null

# Leaf first, then the CA, so a client holding only the CA can build the chain.
cat "$WORK/tls.crt" "$CA_CRT" > "$OUT/control-plane.pem"
cp "$WORK/tls.key" "$OUT/control-plane.key"
chmod 644 "$OUT/control-plane.pem"
chmod 600 "$OUT/control-plane.key"

echo "==> verifying"
openssl verify -CAfile "$CA_CRT" "$WORK/tls.crt" | sed 's/^/    /'
openssl x509 -in "$WORK/tls.crt" -noout -dates | sed 's/^/    /'

cat <<EOF

Wrote:
  $OUT/control-plane.pem
  $OUT/control-plane.key

compose/caddy/Caddyfile points at these. Restart Caddy to pick up a new one:
  cd compose && docker compose --env-file ../configs/env/caios.env restart caddy
EOF
