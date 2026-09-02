#!/usr/bin/env bash
# Expand ${...} placeholders in config templates into compose/generated/.
#
#   bash scripts/render-configs.sh
#
# Templates are committed; rendered output is gitignored and disposable.
# Run this after editing configs/env/caios.env, then restart the affected
# service.
#
# PAPI's main.yaml is deliberately NOT rendered here — its container runs
# envsubst itself at start (upstream behaviour we keep), so it gets the raw
# template mounted and expands it in place.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

ENV_FILE="configs/env/caios.env"
if [[ ! -f "$ENV_FILE" ]]; then
    echo "Missing $ENV_FILE."
    echo "  cp configs/env/caios.env.template $ENV_FILE   and fill in the two floating IPs."
    exit 1
fi

set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

for required in CAIOS_CTRL_IP CAIOS_EDGE_IP; do
    if [[ -z "${!required:-}" ]]; then
        echo "$required is empty in $ENV_FILE. Every hostname derives from it."
        exit 1
    fi
done

# T5. One variable decides the scheme of every user-facing URL on the platform.
# Anything but http or https would render a Caddyfile that fails to parse and a
# Keycloak issuer that matches nothing, so it is rejected here rather than three
# services later.
case "${CAIOS_SCHEME:-}" in
    http)  CAIOS_ALT_SCHEME=https; CAIOS_PORT=80  ;;
    https) CAIOS_ALT_SCHEME=http;  CAIOS_PORT=443 ;;
    *)
        echo "CAIOS_SCHEME is '${CAIOS_SCHEME:-}' in $ENV_FILE; expected http or https."
        exit 1
        ;;
esac

# A Caddy site block on http:// rejects a tls directive outright, so the
# certificate goes to whichever of the two blocks is the https one. Under
# CAIOS_SCHEME=http that is the bounce block, which still has to complete a TLS
# handshake before it can answer with a redirect.
if [[ "$CAIOS_SCHEME" == "https" ]]; then
    CAIOS_TLS="import caios_tls"; CAIOS_ALT_TLS=""
else
    CAIOS_TLS=""; CAIOS_ALT_TLS="import caios_tls"
fi
# Keycloak refuses to serve a realm over plain HTTP to anything it considers
# external, and a public floating IP is external. "none" is therefore required
# on an http platform, and "external" is kept on an https one so nothing is
# relaxed that does not have to be.
if [[ "$CAIOS_SCHEME" == "https" ]]; then
    KEYCLOAK_SSL_REQUIRED=external
else
    KEYCLOAK_SSL_REQUIRED=none
fi
export CAIOS_ALT_SCHEME CAIOS_PORT CAIOS_TLS CAIOS_ALT_TLS KEYCLOAK_SSL_REQUIRED

mkdir -p compose/generated/keycloak compose/generated/caddy

# Caddy. Rendered rather than mounted directly because the scheme decides the
# STRUCTURE of the file — which site block carries the certificate and which
# carries the bounce — and Caddy's own {$ENV} substitution cannot choose between
# two shapes.
envsubst < compose/caddy/Caddyfile.template > compose/generated/caddy/Caddyfile
echo "  compose/generated/caddy/Caddyfile (${CAIOS_SCHEME}, bouncing ${CAIOS_ALT_SCHEME})"


# Keycloak's realm importer rejects any field it does not recognise, and fails
# the whole import with "Unrecognized field". That makes an annotated template
# impossible to import directly. So the comments live in the template, where
# they are useful, and are stripped here on the way out.
envsubst < configs/keycloak/caios-realm.json.template \
    | python3 -c '
import json, sys

def strip(o):
    if isinstance(o, dict):
        return {k: strip(v) for k, v in o.items() if not k.startswith("_comment")}
    if isinstance(o, list):
        return [strip(v) for v in o]
    return o

json.dump(strip(json.load(sys.stdin)), sys.stdout, indent=2)
' > compose/generated/keycloak/caios-realm.json

python3 -c "import json,sys; json.load(open(sys.argv[1]))" \
    compose/generated/keycloak/caios-realm.json
echo "  compose/generated/keycloak/caios-realm.json (comments stripped for Keycloak)"

cat <<EOF

Rendered for:
  dashboard  ${CAIOS_SCHEME}://${CAIOS_DASHBOARD_HOST}
  api        ${CAIOS_SCHEME}://${CAIOS_API_HOST}
  auth       ${CAIOS_SCHEME}://${CAIOS_AUTH_HOST}
  vault      ${CAIOS_SCHEME}://${CAIOS_VAULT_HOST}
  deployments  *.pacs-deployments.${CAIOS_EDGE_IP}.sslip.io

${CAIOS_ALT_SCHEME}:// answers on all four hostnames with a 302 to
${CAIOS_SCHEME}://, so a browser that upgrades the scheme on its own comes back.

Keycloak imports the realm only on first start. If it has run before, the
import is skipped — delete the keycloak_data volume or apply changes through
the admin console.
EOF
