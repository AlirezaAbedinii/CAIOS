#!/usr/bin/env bash
# Run one federation through the cluster, headless, and check what beat 6 says.
#
#   bash scripts/check-fl-cluster.sh               # the demo as deployed
#   bash scripts/check-fl-cluster.sh --bootstrap   # bootstrap the hospitals first
#
# Needs the federated demo up (scripts/deploy-fl-demo.sh). Checks the three
# hospitals are on three machines, that each reaches the server on the private
# path, and that ten rounds finish, then kills anything it started. About a
# minute; add a minute for --bootstrap. scripts/fl-rehearse.sh runs the same
# federation on this machine alone, and so cannot see the network path; this
# is the one that goes through the cluster (docs/demo-plan.md, step 7).
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

ENV_FILE="configs/env/caios.env"
[[ -f "$ENV_FILE" ]] || { echo "Missing $ENV_FILE"; exit 1; }
set -a; source "$ENV_FILE"; set +a

SCHEME="${CAIOS_SCHEME:-https}"
export CAIOS_API="${SCHEME}://${CAIOS_API_HOST}/v1"
export CAIOS_ISSUER="${SCHEME}://${CAIOS_AUTH_HOST}/realms/${KEYCLOAK_REALM}"
export CAIOS_FL_BOOTSTRAP_URL="${SCHEME}://${CAIOS_DASHBOARD_HOST}/fl/bootstrap.sh"

exec python3 scripts/lib/check_fl_cluster.py "$@"
