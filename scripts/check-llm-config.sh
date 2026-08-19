#!/usr/bin/env bash
# Stage L2 gate: is the LLM tool actually deployable on this cluster?
#
#   bash scripts/check-llm-config.sh
#
# Read-only. Asks PAPI what it would do, and asks Nomad whether it would accept
# the result. Deploys nothing — scripts/check-llm-deploy.sh does that in L3.
#
# WHY IT CHECKS CONTENT AND NOT STATUS CODES
#
# Every failure this stage guards against returns HTTP 200. A stale bind mount
# serves upstream's thirteen models with a 200. An allowlist naming a GPU that
# no longer exists returns a 200 from the catalogue and a 405 only at deploy
# time, minutes later, in front of an audience. So this compares what is served
# against what is in the repository, field by field.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

ENV_FILE="configs/env/caios.env"
[[ -f "$ENV_FILE" ]] || { echo "Missing $ENV_FILE"; exit 1; }
set -a; source "$ENV_FILE"; set +a

API="https://${CAIOS_API_HOST}"
VO="${CAIOS_VO:-vo.caios.ca}"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

fail=0
ok()   { printf '  [ ok ] %s\n' "$1"; }
bad()  { printf '  [FAIL] %s\n' "$1"; fail=1; }
warn() { printf '  [warn] %s\n' "$1"; }

echo "=== 1. PAPI is up and offers the tool ==="
code=$(curl -sk --max-time 20 -o "$TMP/tools.json" -w '%{http_code}' "$API/v1/catalog/tools")
[[ "$code" == "200" ]] && ok "GET /v1/catalog/tools -> 200" || { bad "GET /v1/catalog/tools -> $code"; exit 1; }
grep -q "ai4os-llm" "$TMP/tools.json" \
    && ok "ai4os-llm is in the tools catalogue" \
    || bad "ai4os-llm is missing from the tools catalogue"

echo
echo "=== 2. The deploy form matches configs/papi/vllm.yaml ==="
TOKEN=$(bash scripts/get-token.sh researcher "${CAIOS_PW_RESEARCHER:-}" 2>/dev/null | tail -1)
if [[ ${#TOKEN} -lt 40 ]]; then
    bad "could not get an access token — cannot check the form"
else
    code=$(curl -sk --max-time 30 -H "Authorization: Bearer $TOKEN" \
        -o "$TMP/conf.json" -w '%{http_code}' \
        "$API/v1/catalog/tools/ai4os-llm/config?vo=$VO")
    if [[ "$code" != "200" ]]; then
        bad "GET the LLM tool config -> $code"
        head -c 400 "$TMP/conf.json"
    else
        ok "GET the LLM tool config -> 200"
        python3 - "$TMP/conf.json" <<'PY'
import json, sys, pathlib
import yaml

served = json.load(open(sys.argv[1]))
ours = yaml.safe_load(open("configs/papi/vllm.yaml"))["models"]

served_models = served["llm"]["vllm_model_id"]["options"]
if set(served_models) == set(ours):
    print(f"  [ ok ] serving our {len(ours)} models, not upstream's thirteen")
else:
    print("  [FAIL] served model list does not match configs/papi/vllm.yaml")
    print(f"         only served: {sorted(set(served_models) - set(ours))}")
    print(f"         only ours  : {sorted(set(ours) - set(served_models))}")
    raise SystemExit(1)

want = next(iter(ours))
got = served["llm"]["vllm_model_id"]["value"]
print(("  [ ok ] " if got == want else "  [FAIL] ") + f"form defaults to {got}")

opts = served["llm"]["type"]["options"]
print(("  [ ok ] " if set(opts) == {"both", "vllm", "open-webui"} else "  [FAIL] ")
      + f"deployment types: {opts}")
PY
        [[ $? -eq 0 ]] || fail=1
    fi
fi

echo
echo "=== 3. The GPU allowlist matches what the cluster actually reports ==="
# The whole point of patch 0009. A mismatch here is the 405 the user first saw,
# and it only shows up at deploy time.
allow=$(sudo docker inspect caios_papi --format '{{range .Config.Env}}{{println .}}{{end}}' 2>/dev/null \
        | grep '^LLM_GPU_MODELS=' | cut -d= -f2-)
if [[ -z "$allow" ]]; then
    bad "LLM_GPU_MODELS is not set in the PAPI container — patch 0009 would fall back to 'Tesla T4'"
else
    ok "PAPI allows: $allow"
    export NOMAD_ADDR="${NOMAD_ADDR:-https://127.0.0.1:4646}"
    export NOMAD_CACERT="${NOMAD_CACERT:-/etc/nomad.d/certs/nomad-ca.pem}"
    export NOMAD_CLIENT_CERT="${NOMAD_CLIENT_CERT:-/etc/nomad.d/certs/cli.pem}"
    export NOMAD_CLIENT_KEY="${NOMAD_CLIENT_KEY:-/etc/nomad.d/certs/cli-key.pem}"
    present=$(for id in $(nomad node status -json 2>/dev/null | python3 -c 'import json,sys;[print(n["ID"]) for n in json.load(sys.stdin)]' 2>/dev/null); do
        nomad node status -json "$id" 2>/dev/null | python3 -c '
import json,sys
n=json.load(sys.stdin)
for d in (n["NodeResources"].get("Devices") or []):
    if d["Type"]=="gpu": print(d["Name"])
' 2>/dev/null
    done | sort -u)
    if [[ -z "$present" ]]; then
        warn "could not read GPU models from Nomad — skipping the comparison"
    else
        echo "$present" | sed 's/^/         cluster has: /'
        matched=0
        while IFS= read -r model; do
            grep -Fqx "$model" <<<"$present" && matched=1
        done < <(tr ',' '\n' <<<"$allow" | sed 's/^ *//;s/ *$//')
        [[ $matched -eq 1 ]] \
            && ok "the allowlist matches a GPU that exists" \
            || bad "the allowlist matches NOTHING in this cluster — deployments will 405"
    fi
fi

echo
echo "=== 4. Nomad would accept the job template ==="
if ! command -v nomad >/dev/null; then
    warn "nomad CLI not found — skipping (run this on caios_server)"
else
    python3 tests/render.py configs/papi/tools/ai4os-llm/nomad.hcl > "$TMP/job.hcl" 2>/dev/null
    export NOMAD_NAMESPACE="${NOMAD_NAMESPACE:-caios}"
    if out=$(nomad job validate "$TMP/job.hcl" 2>&1); then
        ok "nomad job validate: $(tail -1 <<<"$out")"
    else
        bad "nomad job validate failed"
        sed 's/^/         /' <<<"$out" | head -8
    fi
fi

echo
if [[ $fail -eq 0 ]]; then
    echo "Stage L2 configuration is good."
else
    echo "Stage L2 configuration has FAILURES — see above."
fi
exit $fail
