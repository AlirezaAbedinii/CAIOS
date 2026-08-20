#!/usr/bin/env bash
# Deploy every model the form offers, one at a time, and report which ones work.
#
#   bash scripts/check-llm-catalogue.sh              # all of them
#   bash scripts/check-llm-catalogue.sh --from 4     # resume at the 4th
#
# Takes roughly an hour, mostly weight downloads. Unattended, and it deletes each
# deployment before starting the next — only one GPU exists on the LLM host, so
# they cannot overlap.
#
# WHY THIS EXISTS
#
# The catalogue in configs/papi/vllm.yaml is nine models chosen by arithmetic:
# weights plus overhead against a measured 9680 MiB budget. Arithmetic has been
# wrong twice already on this project — the vLLM image was quoted at 10.5 GB and
# is 30.8 GB on disk, and the weight cache was predicted to save minutes and
# saves 22 seconds.
#
# A researcher picking a model from the dropdown and waiting four minutes for a
# CUDA out-of-memory error is a bad demo. This is how we find those first.
#
# It reuses scripts/check-llm-deploy.sh per model rather than reimplementing the
# deploy-and-test cycle, so there is one copy of that logic and it is the copy
# that Stage L3 verified.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

FROM=1
[[ "${1:-}" == "--from" ]] && FROM="${2:-1}"

# A model that cannot load costs a full timeout here, because check-llm-deploy.sh
# waits for an endpoint rather than watching the allocation. An early-bail was
# tried and regressed the readiness loop, so it was reverted in favour of the
# version Stage L3 verified — correctness over speed. Ten minutes is enough for
# the largest weights on this list and bounds the cost of a failure.
export CAIOS_LLM_TIMEOUT="${CAIOS_LLM_TIMEOUT:-600}"

mapfile -t MODELS < <(python3 -c '
import yaml
for k in yaml.safe_load(open("configs/papi/vllm.yaml"))["models"]:
    print(k)
')
[[ ${#MODELS[@]} -gt 0 ]] || { echo "No models found in configs/papi/vllm.yaml"; exit 1; }

RESULTS="${CAIOS_LLM_RESULTS:-demo/llm/catalogue-results.tsv}"
mkdir -p "$(dirname "$RESULTS")"
[[ -f "$RESULTS" ]] || printf 'model\tverdict\tready_s\ttok_s\tnote\n' > "$RESULTS"

echo "Sweeping ${#MODELS[@]} models from #$FROM. Results append to $RESULTS"
echo

i=0
for model in "${MODELS[@]}"; do
    i=$((i + 1))
    [[ $i -lt $FROM ]] && continue

    echo "======================================================================"
    echo "[$i/${#MODELS[@]}] $model"
    echo "======================================================================"

    out="$(bash scripts/check-llm-deploy.sh "$model" 2>&1)"
    rc=$?

    ready="$(grep -oP 'first answer: \K[0-9]+' <<<"$out" | head -1)"
    toks="$(grep -oP '= \K[0-9.]+(?= tok/s)' <<<"$out" | head -1)"

    if [[ $rc -eq 0 ]]; then
        verdict="ok"; note=""
    elif grep -q "returned an empty completion" <<<"$out"; then
        # Loaded and generated, but put its answer somewhere a plain OpenAI
        # client will not look. See docs/llm-risks.md R-20.
        verdict="EMPTY-CONTENT"; note="answers into a non-content field"
    elif grep -qE "main-dead|alloc-failed|alloc-lost" <<<"$out"; then
        verdict="WONT-LOAD"; note="allocation died — usually CUDA OOM"
    elif grep -q "never answered within" <<<"$out"; then
        verdict="TIMEOUT"; note="no endpoint inside ${CAIOS_LLM_TIMEOUT}s"
    else
        verdict="FAILED"; note="see the log above"
    fi

    printf '%s\t%s\t%s\t%s\t%s\n' \
        "$model" "$verdict" "${ready:--}" "${toks:--}" "$note" >> "$RESULTS"

    if [[ $rc -eq 0 ]]; then
        sed -n '/=== 3\./,$p' <<<"$out" | head -8
    else
        # On failure the interesting part is the readiness section and whatever
        # the script said about why. Showing nothing here cost an hour once.
        tail -12 <<<"$out" | sed 's/^/    /'
    fi
    echo "  --> $verdict"
    echo

    # Let Nomad reap the allocation and release the GPU before the next one.
    sleep 20
done

echo "======================================================================"
echo "SUMMARY"
echo "======================================================================"
column -t -s $'\t' "$RESULTS"
echo
bad=$(awk -F'\t' 'NR>1 && $2!="ok"' "$RESULTS" | wc -l)
tot=$(awk 'NR>1' "$RESULTS" | wc -l)
echo "$((tot - bad))/$tot models usable."
if [[ $bad -gt 0 ]]; then
    echo
    echo "Remove anything not 'ok' from configs/papi/vllm.yaml — a dropdown entry"
    echo "that fails after a four-minute wait is worse than one that is absent."
fi
