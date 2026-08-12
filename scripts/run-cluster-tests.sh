#!/usr/bin/env bash
# Run ai4-nomad_tests against the cluster.
#
#   bash scripts/run-cluster-tests.sh              # test and mark nodes ready
#   bash scripts/run-cluster-tests.sh --dry-run    # report only, change nothing
#
# This is not just validation. It is the ONLY thing that sets meta.status=ready
# on a node, and every PAPI job template constrains on that — so until this
# passes, the cluster schedules nothing while looking perfectly healthy.
#
# It deploys a small job to each node in turn and fetches it back through
# Traefik over HTTPS, so a pass also proves routing and certificates work.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

ENV_FILE="configs/env/caios.env"
[[ -f "$ENV_FILE" ]] || { echo "Missing $ENV_FILE"; exit 1; }
set -a; source "$ENV_FILE"; set +a

export PATH="$HOME/.local/bin:$PATH"
export NOMAD_ADDR="${NOMAD_ADDR:-https://127.0.0.1:4646}"
export NOMAD_CACERT="${NOMAD_CACERT:-/etc/nomad.d/certs/nomad-ca.pem}"
export NOMAD_CLIENT_CERT="${NOMAD_CLIENT_CERT:-/etc/nomad.d/certs/cli.pem}"
export NOMAD_CLIENT_KEY="${NOMAD_CLIENT_KEY:-/etc/nomad.d/certs/cli-key.pem}"

# Consumed by our patch to the suite's conf.py, which upstream hardcodes to the
# AI4EOSC namespaces. Note the base domain has NO "pacs-" prefix: the test
# builds "<meta.domain>-<base>" itself, and meta.domain is already "pacs".
export AI4_NAMESPACES="caios"
export AI4_BASE_DOMAIN="deployments.${CAIOS_EDGE_IP}.sslip.io"

# requests uses certifi, not the system trust store, so pointing at our CA here
# is what stops the HTTPS check failing with "Invalid SSL certificates".
export REQUESTS_CA_BUNDLE="${REQUESTS_CA_BUNDLE:-$HOME/caios-ca.pem}"

command -v ai4-nomad-tests >/dev/null || {
    echo "ai4-nomad-tests not installed. Run:"
    echo "  bash scripts/apply-patches.sh"
    echo "  python3 -m pip install --user -e build/ai4-nomad_tests"
    exit 1
}

echo "namespaces : $AI4_NAMESPACES"
echo "base domain: $AI4_BASE_DOMAIN"
echo "CA bundle  : $REQUESTS_CA_BUNDLE"
echo

exec ai4-nomad-tests --cluster "$@"
