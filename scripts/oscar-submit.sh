#!/usr/bin/env bash
# Send an image to an OSCAR inference service and print its answer.
#
#   bash scripts/oscar-submit.sh <service-name> <image-file>
#   bash scripts/oscar-submit.sh --list
#
# Run from caios_server. Needs configs/env/caios.env and a researcher password.
#
# WHY THIS EXISTS
#
# OSCAR's input is not the image. The FDL script PAPI ships does
#
#     with open(FILE_PATH, "r") as f:
#         params = json.loads(f.read())
#
# so the object dropped into <service>/inputs/ must be a JSON document, with
# the image base64-encoded inside an `oscar-files` array:
#
#     {"oscar-files": [{"key": "files", "file_format": "jpg", "data": "..."}]}
#
# Nothing in the dashboard says this. Upload a JPEG directly and the job runs,
# fails inside the container, and leaves a UnicodeDecodeError in outputs/ —
# `byte 0x89` for a PNG, because the script opened a binary file as text. This
# script does the wrapping so a demo never hits that.
#
# NAME THE INPUT `.json`. The script keys off the extension: a non-.json name
# makes it skip saving the model's structured output, and you get only a log.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

ENV_FILE="configs/env/caios.env"
[[ -f "$ENV_FILE" ]] || { echo "Missing $ENV_FILE"; exit 1; }
set -a; source "$ENV_FILE"; set +a

VO="${CAIOS_VO:-vo.caios.ca}"
# T5. The scheme the platform serves on, from configs/env/caios.env.
# Defaults to https so this script behaves as it always did against an
# env file written before the switch existed.
SCHEME="${CAIOS_SCHEME:-https}"
API="${SCHEME}://${CAIOS_API_HOST}"
USER_NAME="${CAIOS_FL_USER:-researcher}"
PW_VAR="CAIOS_PW_$(echo "$USER_NAME" | tr 'a-z-' 'A-Z_')"
PASSWORD="${!PW_VAR:-}"
[[ -n "$PASSWORD" ]] || { echo "No password for $USER_NAME ($PW_VAR unset)"; exit 1; }

TOKEN="$(bash scripts/get-token.sh "$USER_NAME" "$PASSWORD" 2>/dev/null)"
[[ -n "$TOKEN" ]] || { echo "Could not get a token — is Keycloak up?"; exit 1; }

api() { curl -sk -m 60 -H "Authorization: Bearer $TOKEN" "$@"; }

if [[ "${1:-}" == "--list" ]]; then
    api "$API/v1/inference/oscar/services?vo=$VO" | python3 -c "
import json, sys
svcs = json.load(sys.stdin)
if not svcs:
    print('  no inference services. Create one from the Marketplace:')
    print('  a module -> Deploy -> Inference API (serverless)')
    raise SystemExit
for s in svcs:
    print('  %s' % s['name'])
    print('     image  %s' % s.get('image'))
    print('     cpu %s  memory %s' % (s.get('cpu'), s.get('memory')))
"
    exit 0
fi

SERVICE="${1:?usage: oscar-submit.sh <service-name> <image-file>  |  --list}"
IMAGE="${2:?usage: oscar-submit.sh <service-name> <image-file>}"
[[ -f "$IMAGE" ]] || { echo "No such file: $IMAGE"; exit 1; }

EXT="${IMAGE##*.}"
STAMP="$(date +%H%M%S)"
NAME="submit-$STAMP"

echo "=== wrapping $(basename "$IMAGE") as an OSCAR input ==="
python3 - "$IMAGE" "$EXT" "/tmp/$NAME.json" <<'PY'
import base64, json, sys
src, ext, dst = sys.argv[1:4]
doc = {"oscar-files": [{"key": "files", "file_format": ext, "data":
                        base64.b64encode(open(src, "rb").read()).decode()}]}
open(dst, "w").write(json.dumps(doc))
print(f"  {dst}  ({len(json.dumps(doc))} bytes)")
PY

# The synchronous endpoint, as the service's owner. Since patch 0022 a service
# answers with its result as plain JSON; one created before 2026-09-27 answers
# with its job's log, and the result is the line starting "return:".
SVC_JSON="$(api "$API/v1/inference/oscar/services/$SERVICE?vo=$VO")"
ENDPOINT="$(python3 -c 'import json,sys; print(json.load(sys.stdin).get("endpoint", ""))' <<<"$SVC_JSON" 2>/dev/null)"
SVC_TOKEN="$(python3 -c 'import json,sys; print(json.load(sys.stdin).get("token", ""))' <<<"$SVC_JSON" 2>/dev/null)"
[[ -n "$ENDPOINT" && -n "$SVC_TOKEN" ]] || { echo "PAPI gave no endpoint for $SERVICE — check the name with --list"; exit 1; }

echo "=== calling $ENDPOINT ==="
T0=$(date +%s.%N)
ANSWER="$(curl -sS -m 420 --cacert compose/certs/caios-ca.pem \
    -H "Authorization: Bearer $SVC_TOKEN" -H "Content-Type: application/json" \
    --data @"/tmp/$NAME.json" "$ENDPOINT")"
T1=$(date +%s.%N)
python3 - "$ANSWER" <<'PY2'
import ast, json, re, sys
text = sys.argv[1]
try:
    result = json.loads(text)
except ValueError:
    line = next((l for l in text.splitlines() if "return:" in l), "")
    if not line:
        print(text[-2000:]); raise SystemExit(1)
    print("  (a service created before patch 0022: this was its log)")
    result = ast.literal_eval(re.sub(r"\x1b\[[0-9;]*m", "", line).split("return:", 1)[1].strip())
print(json.dumps(result, indent=2)[:3000])
PY2
echo "  answered in $(python3 -c "print(round($T1 - $T0, 1))") s"
echo
echo "Many files, or results you want kept: upload them instead, into"
echo "  $SERVICE/inputs/   at   https://minio-console.${CAIOS_OSCAR_NODE_IP:-192.168.104.69}.sslip.io"
echo "and collect  $SERVICE/outputs/<name>.json  (docs/oscar-gui-guide.md, Route B)."
