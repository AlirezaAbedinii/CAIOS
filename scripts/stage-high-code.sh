#!/usr/bin/env bash
# Put the high-code notebook into a running YOLO JupyterLab deployment, and
# run it once so everything it touches is warm.
#
#   bash scripts/stage-high-code.sh <workspace-uuid> <llm-uuid>
#   bash scripts/stage-high-code.sh <workspace-uuid> <llm-uuid> --llm-owner platform-admin
#   bash scripts/stage-high-code.sh <workspace-uuid> <llm-uuid> --service ai4papi-…
#
# The workspace is the YOLO module deployed from the marketplace in Jupyter
# mode, by the demo account (researcher). The notebook lands in
# /srv/caios-demo/, next to the module's own code.
#
# WHY THIS EXISTS
#
# The notebook calls two other parts of the platform — the serverless YOLO
# service and the private LLM — and each needs an endpoint and a secret. Typing
# those on camera puts a token in the recording; pasting them into the notebook
# puts it in every copy of the notebook. So they are fetched here, from PAPI
# with the owners' own tokens, and written into the workspace as a mode-600
# config file that the notebook reads and never shows.
#
# The run at the end is the test and the warm-up at once: YOLO's weights come
# from GitHub at first use, the serverless service scales from zero, and the
# model has to answer once. None of that should happen for the first time on
# camera.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

ENV_FILE="configs/env/caios.env"
[[ -f "$ENV_FILE" ]] || { echo "Missing $ENV_FILE"; exit 1; }
set -a; source "$ENV_FILE"; set +a

SCHEME="${CAIOS_SCHEME:-https}"
export CAIOS_API="${SCHEME}://${CAIOS_API_HOST}/v1"
export CAIOS_ISSUER="${SCHEME}://${CAIOS_AUTH_HOST}/realms/${KEYCLOAK_REALM}"

exec python3 scripts/lib/stage_high_code.py "$@"
