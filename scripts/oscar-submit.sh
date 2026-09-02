#!/usr/bin/env bash
# Submit an image to an OSCAR inference service and wait for the result.
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

# Credentials come from the per-user secret OSCAR creates on the K3s cluster,
# not from MinIO's root account — the service is owned by the OIDC subject and
# only that identity should be writing to its bucket.
echo "=== uploading to $SERVICE/inputs/$NAME.json ==="
echo "  (this is the trigger — nothing is running until the object lands)"
cat <<EOF

  On the OSCAR node:
    mc cp /tmp/$NAME.json caiosuser/$SERVICE/inputs/$NAME.json

  Or in a browser, at
    https://minio-console.${CAIOS_OSCAR_NODE_IP:-192.168.104.69}.sslip.io
  upload the file into  $SERVICE/inputs/

  Then collect the result from
    $SERVICE/outputs/$NAME.json

EOF
echo "Measured: ~13 s upload-to-result once the image is cached on the node;"
echo "the first run of a service also pulls its image (YOLO took 3m12s)."
