#!/usr/bin/env bash
# Configure the public nginx proxy from this repository.
#
#   bash scripts/deploy-jumpserver.sh --check      # diff only, change nothing
#   bash scripts/deploy-jumpserver.sh              # apply, CAIOS CA certificate
#   bash scripts/deploy-jumpserver.sh --tls-mode acme
#
# Stage C1 of docs/certificate-plan.md. Until 2026-09-23 the proxy VM was the
# only machine in the architecture configured by hand, and it is the one about
# to hold the platform's real certificate.
#
# WHY A WRAPPER RATHER THAN group_vars
# ------------------------------------
# The domain lives in configs/env/caios.env and nowhere else (stage C0). A
# copy in ansible/group_vars/ would be a second source of truth for exactly
# the value the whole certificate plan exists to keep in one place — and the
# two would disagree silently, because Ansible never reads that file and the
# platform never reads group_vars. So the variables are passed at run time,
# from the same file everything else derives from.
#
# THE ORDER THAT MATTERS
# ----------------------
# Take the public-path baseline BEFORE applying, and compare after. The gate
# for C1 is that the table does not change: the playbook is supposed to
# reproduce what is already there, and "it still works" is not something to
# establish by looking at one page in a browser.
#
#   bash scripts/check-public-path.sh > /tmp/before
#   bash scripts/deploy-jumpserver.sh
#   bash scripts/check-public-path.sh > /tmp/after
#   diff /tmp/before /tmp/after      # must be empty
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

ENV_FILE="configs/env/caios.env"
[[ -f "$ENV_FILE" ]] || { echo "Missing $ENV_FILE"; exit 1; }
set -a; . "$ENV_FILE"; set +a
: "${CAIOS_PUBLIC_DOMAIN:?CAIOS_PUBLIC_DOMAIN is empty}"
: "${CAIOS_DEPLOYMENTS_DOMAIN:?CAIOS_DEPLOYMENTS_DOMAIN is empty}"

TLS_MODE="${CAIOS_TLS_MODE:-caios-ca}"
EXTRA=()
while [[ $# -gt 0 ]]; do
    case "$1" in
        --check)     EXTRA+=(--check --diff) ;;
        --tls-mode)  TLS_MODE="$2"; shift ;;
        *)           EXTRA+=("$1") ;;
    esac
    shift
done

case "$TLS_MODE" in
    caios-ca) ;;
    acme)
        # Let's Encrypt issues wildcards only over DNS-01, which proves
        # control of the zone. Nobody controls sslip.io, so this is not a
        # configuration problem to debug on the proxy — it cannot work.
        if [[ "$CAIOS_PUBLIC_DOMAIN" == *.sslip.io ]]; then
            echo "CAIOS_PUBLIC_DOMAIN is '${CAIOS_PUBLIC_DOMAIN}', an sslip.io name."
            echo "Let's Encrypt cannot issue for it: DNS-01 needs control of the"
            echo "zone. Set a real domain in $ENV_FILE first (stage C2)."
            exit 1
        fi
        : "${CAIOS_ACME_EMAIL:?is empty. ACME registration needs an address that is read}"
        : "${CAIOS_CF_API_TOKEN:?CAIOS_CF_API_TOKEN is empty — see caios.env}"
        ;;
    *)
        echo "--tls-mode is '${TLS_MODE}'; expected caios-ca or acme."
        exit 1
        ;;
esac

PLAYBOOK="ansible/playbook-jumpserver.yml"
if [[ ! -f "$PLAYBOOK" ]]; then
    echo "$PLAYBOOK does not exist yet."
    echo
    echo "It cannot be written until the proxy's current configuration has been"
    echo "read, because reproducing it faithfully is the gate for this stage:"
    echo
    echo "  ssh -t ubuntu@${CAIOS_PUBLIC_IP} 'sudo nginx -T' > /tmp/nginx-T.txt 2>&1"
    echo
    echo "-t is not optional: sudo needs a terminal, and without one the command"
    echo "fails at the password prompt with a single line of output."
    exit 1
fi

# The Cloudflare token is a real secret: it can rewrite every record in the
# zone. Passed in a file rather than with -e, because -e puts it in the
# process table where any user on this host can read it with ps.
VARS="$(mktemp)"; chmod 600 "$VARS"
trap 'rm -f "$VARS"' EXIT
cat > "$VARS" <<EOF
caios_public_domain: "${CAIOS_PUBLIC_DOMAIN}"
caios_deployments_domain: "${CAIOS_DEPLOYMENTS_DOMAIN}"
caios_ctrl_ip: "${CAIOS_CTRL_IP}"
caios_edge_ip: "${CAIOS_EDGE_IP}"
caios_tls_mode: "${TLS_MODE}"
caios_acme_email: "${CAIOS_ACME_EMAIL:-}"
caios_cf_api_token: "${CAIOS_CF_API_TOKEN:-}"
EOF

echo "=== jumpserver ${CAIOS_PUBLIC_IP} ==="
echo "  domain      ${CAIOS_PUBLIC_DOMAIN}"
echo "  deployments *.pacs-${CAIOS_DEPLOYMENTS_DOMAIN}"
echo "  tls mode    ${TLS_MODE}"
[[ " ${EXTRA[*]-} " == *" --check "* ]] && echo "  MODE        check only, nothing is changed"
echo

cd ansible
exec ansible-playbook playbook-jumpserver.yml -e "@$VARS" ${EXTRA[@]+"${EXTRA[@]}"}
