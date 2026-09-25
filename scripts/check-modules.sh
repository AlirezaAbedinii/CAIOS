#!/usr/bin/env bash
# Deploy every marketplace module, in both modes, and report which ones work.
#
#   bash scripts/check-modules.sh                    # every module, DEEPaaS and Jupyter
#   bash scripts/check-modules.sh --only yolo        # a subset, by substring
#   bash scripts/check-modules.sh --modes deepaas    # one mode
#
# Results are appended to demo/modules/check-results.tsv. Every deployment it
# creates is deleted before it exits, pass or fail.
#
# WHY THIS EXISTS
#
# The marketplace offers eight modules and two ways to deploy each, and until
# 2026-09-24 nobody had deployed most of them here. The one conclusion that had
# been drawn about all of them — "JupyterLab does not work on any module" — came
# from a single image, and was wrong for the next one tried. A researcher
# clicking Deploy gets whichever combination they pick; this is how we find out
# which ones work before they do.
#
# It runs through PAPI with the dashboard's own defaults (one CPU, no GPU), so a
# pass means the button works — not merely that the image does.
#
# It pulls every module image onto whichever node Nomad picks, which is tens of
# gigabytes across the cluster, and docuum will evict older images to make
# room. Re-run the pre-pull for the demo's images afterwards.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

ENV_FILE="configs/env/caios.env"
[[ -f "$ENV_FILE" ]] || { echo "Missing $ENV_FILE"; exit 1; }
set -a; source "$ENV_FILE"; set +a

USER_NAME="${CAIOS_CHECK_USER:-researcher}"
PW_VAR="CAIOS_PW_$(echo "$USER_NAME" | tr 'a-z-' 'A-Z_')"
[[ -n "${!PW_VAR:-}" ]] || { echo "No password for $USER_NAME ($PW_VAR unset)"; exit 1; }

SCHEME="${CAIOS_SCHEME:-https}"
export CAIOS_API="${SCHEME}://${CAIOS_API_HOST}/v1"
export CAIOS_ISSUER="${SCHEME}://${CAIOS_AUTH_HOST}/realms/${KEYCLOAK_REALM}"
export CAIOS_CHECK_USER="$USER_NAME"
export CAIOS_CHECK_PASSWORD="${!PW_VAR}"

exec python3 scripts/lib/check_modules.py "$@"
