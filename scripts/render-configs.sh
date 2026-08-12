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

mkdir -p compose/generated/keycloak

envsubst < configs/keycloak/caios-realm.json.template \
    > compose/generated/keycloak/caios-realm.json
python3 -c "import json,sys; json.load(open(sys.argv[1]))" \
    compose/generated/keycloak/caios-realm.json
echo "  compose/generated/keycloak/caios-realm.json"

cat <<EOF

Rendered for:
  dashboard  https://${CAIOS_DASHBOARD_HOST}
  api        https://${CAIOS_API_HOST}
  auth       https://${CAIOS_AUTH_HOST}
  vault      https://${CAIOS_VAULT_HOST}
  deployments  *.pacs-deployments.${CAIOS_EDGE_IP}.sslip.io

Keycloak imports the realm only on first start. If it has run before, the
import is skipped — delete the keycloak_data volume or apply changes through
the admin console.
EOF
