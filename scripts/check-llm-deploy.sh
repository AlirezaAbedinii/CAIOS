#!/usr/bin/env bash
# Stage L3 gate: deploy a model, get a real completion out of it, delete it.
#
#   bash scripts/check-llm-deploy.sh                       # the default model
#   bash scripts/check-llm-deploy.sh Qwen/Qwen3.5-0.8B     # a specific one
#   bash scripts/check-llm-deploy.sh --keep                # leave it running
#
# DEPLOYS AND THEN DELETES a vLLM instance. Self-cleaning, so it can run in a
# loop — but it holds a GPU while it runs, and `--keep` holds one indefinitely.
#
# It goes through PAPI and Traefik exactly as a user does, including fetching
# the API token from Vault, because the point is to test the path a researcher
# takes and not a shortcut through Nomad.
#
# WHAT IT MEASURES, AND WHY THOSE NUMBERS
#
#   time to first token   decides whether the demo can deploy live or has to
#                         pre-warm. Two to five minutes was the estimate; this
#                         replaces the estimate.
#   tokens/second         decides whether a live chat looks fluent or painful.
#   KV cache size         vLLM's own report of what fits, which replaces the
#                         arithmetic in docs/llm-infrastructure.md.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

ENV_FILE="configs/env/caios.env"
[[ -f "$ENV_FILE" ]] || { echo "Missing $ENV_FILE"; exit 1; }
set -a; source "$ENV_FILE"; set +a

KEEP=false
MODEL=""
for arg in "$@"; do
    case "$arg" in
        --keep) KEEP=true ;;
        *) MODEL="$arg" ;;
    esac
done

API="https://${CAIOS_API_HOST}"
VO="${CAIOS_VO:-vo.caios.ca}"
USER_NAME="${CAIOS_LLM_USER:-researcher}"
PW_VAR="CAIOS_PW_$(echo "$USER_NAME" | tr 'a-z-' 'A-Z_')"
PASSWORD="${!PW_VAR:-}"
DEPLOY_TIMEOUT="${CAIOS_LLM_TIMEOUT:-900}"

fail=0
ok()   { printf '  [ ok ] %s\n' "$1"; }
bad()  { printf '  [FAIL] %s\n' "$1"; fail=1; }
info() { printf '         %s\n' "$1"; }

[[ -n "$PASSWORD" ]] || { echo "No password for $USER_NAME ($PW_VAR unset)"; exit 1; }
TOKEN="$(bash scripts/get-token.sh "$USER_NAME" "$PASSWORD" 2>/dev/null)"
[[ ${#TOKEN} -gt 40 ]] || { echo "Could not get an access token — is Keycloak up?"; exit 1; }

api() {  # api <method> <path> [body]
    local method="$1" path="$2" body="${3:-}"
    if [[ -n "$body" ]]; then
        curl -k -sS -X "$method" -H "Authorization: Bearer $TOKEN" \
            -H "Content-Type: application/json" "$API$path" -d "$body"
    else
        curl -k -sS -X "$method" -H "Authorization: Bearer $TOKEN" "$API$path"
    fi
}

JOB_ID=""
cleanup() {
    if [[ -n "$JOB_ID" && "$KEEP" != true ]]; then
        echo
        echo "=== cleaning up ==="
        api DELETE "/v1/deployments/tools/$JOB_ID?vo=$VO" >/dev/null 2>&1
        echo "  deleted $JOB_ID"
    elif [[ -n "$JOB_ID" ]]; then
        echo
        echo "  --keep: $JOB_ID is still running and still holding a GPU."
        echo "  Delete it with: bash scripts/check-llm-deploy.sh --delete-id $JOB_ID"
    fi
}
trap cleanup EXIT

# If no model was named, use whatever the deploy form defaults to — the point is
# to test what a user actually gets.
if [[ -z "$MODEL" ]]; then
    MODEL="$(api GET "/v1/catalog/tools/ai4os-llm/config?vo=$VO" \
        | python3 -c 'import json,sys;print(json.load(sys.stdin)["llm"]["vllm_model_id"]["value"])' 2>/dev/null)"
fi
[[ -n "$MODEL" ]] || { echo "Could not determine which model to deploy."; exit 1; }

echo "=== 1. deploy $MODEL (type: vllm) ==="
CONF="$(MODEL="$MODEL" python3 -c '
import json, os
print(json.dumps({
    "general": {"title": "CAIOS LLM check", "desc": "scripts/check-llm-deploy.sh"},
    "llm": {"type": "vllm", "vllm_model_id": os.environ["MODEL"]},
}))')"

T0=$(date +%s)
RESP="$(api POST "/v1/deployments/tools?vo=$VO&tool_name=ai4os-llm" "$CONF")"
JOB_ID="$(python3 -c 'import json,sys;print(json.load(sys.stdin).get("job_ID",""))' <<<"$RESP" 2>/dev/null)"
if [[ -z "$JOB_ID" ]]; then
    bad "deployment refused"
    info "$(head -c 500 <<<"$RESP")"
    exit 1
fi
ok "accepted: $JOB_ID"

echo
echo "=== 2. wait for the endpoint to answer ==="
# The deployment reports "running" as soon as the container starts, which is
# long before the model is loaded. The only meaningful readiness signal is
# /v1/models answering, so that is what this waits for.
# Readiness is judged from the HTTP status ALONE, not from being able to
# authenticate. vLLM answers 401 to a bad key and Traefik answers 502 when there
# is nothing behind it, so the two are distinguishable — and the check no longer
# depends on the Vault secret having appeared yet. An earlier version required
# both, and a slow secret meant this loop span for fifteen minutes against a
# deployment that had been serving for twelve of them.
ENDPOINT=""; APIKEY=""; READY_CODE=""
for _ in $(seq 1 "$((DEPLOY_TIMEOUT / 10))"); do
    if [[ -z "$ENDPOINT" ]]; then
        ENDPOINT="$(api GET "/v1/deployments/tools/$JOB_ID?vo=$VO" \
            | python3 -c 'import json,sys;print((json.load(sys.stdin).get("endpoints") or {}).get("vllm",""))' 2>/dev/null)"
    fi
    if [[ -n "$ENDPOINT" ]]; then
        READY_CODE=$(curl -k -sS --max-time 10 -o /dev/null -w '%{http_code}' \
            "$ENDPOINT/v1/models" 2>/dev/null)
        # 200 or 401 both mean vLLM is listening and has loaded the model.
        [[ "$READY_CODE" == "200" || "$READY_CODE" == "401" ]] && break
    fi
    sleep 10
done
READY=$(( $(date +%s) - T0 ))

if [[ "$READY_CODE" != "200" && "$READY_CODE" != "401" ]]; then
    bad "vLLM never answered within ${DEPLOY_TIMEOUT}s (last status: ${READY_CODE:-no response})"
    info "endpoint: ${ENDPOINT:-none published}"
    info "check the allocation: NOMAD_NAMESPACE=caios nomad job status $JOB_ID"
    exit 1
fi

# Now fetch the key, with its own retries, so a slow Vault is reported as a
# Vault problem rather than as a model that would not start.
for _ in $(seq 1 12); do
    APIKEY="$(api GET "/v1/secrets?vo=$VO&subpath=/deployments/$JOB_ID" \
        | python3 -c '
import json, sys
for path, data in (json.load(sys.stdin) or {}).items():
    if path.endswith("/llm/vllm"):
        print(data.get("token", "")); break
' 2>/dev/null)"
    [[ -n "$APIKEY" ]] && break
    sleep 5
done

[[ -n "$ENDPOINT" ]] && ok "endpoint: $ENDPOINT" || { bad "no endpoint published"; exit 1; }
[[ -n "$APIKEY" ]]   && ok "API key retrieved from Vault" || bad "no API key in Vault"

code=$(curl -k -sS --max-time 15 -o /tmp/caios-llm-models.json -w '%{http_code}' \
    -H "Authorization: Bearer $APIKEY" "$ENDPOINT/v1/models" 2>/dev/null)
if [[ "$code" != "200" ]]; then
    bad "/v1/models returned $code after ${READY}s"
    exit 1
fi
served="$(python3 -c 'import json;print(json.load(open("/tmp/caios-llm-models.json"))["data"][0]["id"])' 2>/dev/null)"
[[ "$served" == "$MODEL" ]] && ok "serving $served" || bad "serving $served, expected $MODEL"
info "time from deploy to first answer: ${READY}s"

echo
echo "=== 3. a real completion ==="
# Content, not a status code: a 200 with an empty string is not a working model.
REQ="$(MODEL="$MODEL" python3 -c '
import json, os
print(json.dumps({
    "model": os.environ["MODEL"],
    "messages": [{"role": "user", "content": "In one sentence, what is federated learning?"}],
    "max_tokens": 120,
    "temperature": 0,
}))')"
C0=$(date +%s.%N)
curl -k -sS --max-time 120 -o /tmp/caios-llm-chat.json \
    -H "Authorization: Bearer $APIKEY" -H "Content-Type: application/json" \
    "$ENDPOINT/v1/chat/completions" -d "$REQ" >/dev/null 2>&1
C1=$(date +%s.%N)

python3 - "$C0" "$C1" <<'PY'
import json, sys

t0, t1 = float(sys.argv[1]), float(sys.argv[2])
try:
    r = json.load(open("/tmp/caios-llm-chat.json"))
except Exception:
    print("  [FAIL] no JSON came back"); raise SystemExit(1)
if "error" in r:
    print("  [FAIL] %s" % str(r["error"])[:300]); raise SystemExit(1)

text = (r["choices"][0]["message"].get("content") or "").strip()
if not text:
    print("  [FAIL] the model returned an empty completion"); raise SystemExit(1)

out = r.get("usage", {}).get("completion_tokens", 0)
elapsed = t1 - t0
print("  [ ok ] completion: %s" % (text[:150] + ("..." if len(text) > 150 else "")))
print("         %d tokens in %.1fs = %.1f tok/s" % (out, elapsed, out / elapsed if elapsed else 0))
PY
[[ $? -eq 0 ]] || fail=1

echo
echo "=== 4. how much of the GPU it actually took ==="
# vLLM 0.27 does not log the KV cache size anywhere greppable, so ask the card.
# This is the real answer to "did 0.80 fit", and it replaces the arithmetic in
# docs/llm-infrastructure.md with a measurement.
if command -v nomad >/dev/null; then
    export NOMAD_ADDR="${NOMAD_ADDR:-https://127.0.0.1:4646}"
    export NOMAD_CACERT="${NOMAD_CACERT:-/etc/nomad.d/certs/nomad-ca.pem}"
    export NOMAD_CLIENT_CERT="${NOMAD_CLIENT_CERT:-/etc/nomad.d/certs/cli.pem}"
    export NOMAD_CLIENT_KEY="${NOMAD_CLIENT_KEY:-/etc/nomad.d/certs/cli-key.pem}"
    export NOMAD_NAMESPACE="${NOMAD_NAMESPACE:-caios}"
    alloc="$(nomad job allocs -json "$JOB_ID" 2>/dev/null \
        | python3 -c 'import json,sys;a=json.load(sys.stdin);print(a[0]["ID"] if a else "")' 2>/dev/null)"
    node="$(nomad job allocs -json "$JOB_ID" 2>/dev/null \
        | python3 -c 'import json,sys;a=json.load(sys.stdin);print(a[0]["NodeName"] if a else "")' 2>/dev/null)"
    [[ -n "$node" ]] && info "running on $node"

    # Map the Nomad agent name back to an address so we can read its GPU.
    node_ip="$(nomad node status -json 2>/dev/null \
        | python3 -c '
import json, sys
name = sys.argv[1]
for n in json.load(sys.stdin):
    if n["Name"] == name:
        print(n.get("Address", "")); break
' "$node" 2>/dev/null)"

    if [[ -n "$node_ip" && -f "${CAIOS_SSH_KEY:-$HOME/.ssh/caios_cluster}" ]]; then
        used="$(timeout 30 ssh -i "${CAIOS_SSH_KEY:-$HOME/.ssh/caios_cluster}" \
            -o IdentitiesOnly=yes -o BatchMode=yes -o ConnectTimeout=10 \
            "ubuntu@$node_ip" \
            'nvidia-smi --query-gpu=memory.used,memory.free --format=csv,noheader' 2>/dev/null)"
        if [[ -n "$used" ]]; then
            info "GPU on $node: $used"
            info "the deployment asked for 0.80 of what CUDA reports as total"
        else
            info "could not read the GPU on $node"
        fi
    else
        info "no route to $node — skipping the GPU reading"
    fi
else
    info "nomad CLI not found — skipping (run this on caios_server)"
fi

echo
if [[ $fail -eq 0 ]]; then
    echo "Stage L3: a model deployed through PAPI answered a question. "
else
    echo "Stage L3 has FAILURES — see above."
fi
exit $fail
