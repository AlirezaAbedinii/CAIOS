#!/usr/bin/env bash
# Turn catalog/ai4life-models.txt into the AI4LIFE_MODELS environment variable,
# validating every ID against the live AI4Life catalogue first.
#
#   bash scripts/render-ai4life-models.sh           # check and print
#   bash scripts/render-ai4life-models.sh --write   # also write it into caios.env
#
# WHY THE VALIDATION IS THE POINT
#
# The IDs are mostly bioimage.io nicknames, and it is natural to copy one off
# the website. That does not always work: the most downloaded model in the
# catalogue is shown everywhere as "affable-shark", but the loader's `id` field
# for it is the concept DOI 10.5281/zenodo.5764892, and the deploy form only
# accepts the id.
#
# A wrong ID here fails silently — PAPI drops unknown entries, so the dropdown
# just quietly has one fewer option and nobody notices until the model someone
# asked to see is not there. So every line is checked against
# filtered_models.json, and a typo stops this script.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

LIST="catalog/ai4life-models.txt"
ENV_FILE="configs/env/caios.env"
CATALOGUE_URL="https://raw.githubusercontent.com/ai4os/ai4os-ai4life-loader/refs/heads/main/models/filtered_models.json"
WRITE=0
[[ "${1:-}" == "--write" ]] && WRITE=1

[[ -f "$LIST" ]] || { echo "Missing $LIST"; exit 1; }

mapfile -t WANT < <(sed 's/#.*//' "$LIST" | sed 's/[[:space:]]*$//;s/^[[:space:]]*//' | grep -v '^$')
echo "==> $LIST lists ${#WANT[@]} model(s)"

echo "==> fetching the live AI4Life catalogue"
tmp="$(mktemp)"
trap 'rm -f "$tmp"' EXIT
curl -sS --max-time 60 "$CATALOGUE_URL" -o "$tmp" || { echo "  could not fetch $CATALOGUE_URL"; exit 1; }

# The wanted list goes via a file, not a pipe: `python3 - <<PY` already takes
# stdin for the program itself, so a piped list never arrives and every ID looks
# missing. Cost an eye-blink here and a wrong turn in Stage 4.
wanted_file="$(mktemp)"
trap 'rm -f "$tmp" "$wanted_file"' EXIT
printf '%s\n' "${WANT[@]}" > "$wanted_file"

python3 - "$tmp" "$wanted_file" <<'PY'
import json
import sys

catalogue = json.load(open(sys.argv[1]))
available = {}
for entry in catalogue.values():
    available[entry["id"]] = entry

wanted = [line.strip() for line in open(sys.argv[2]) if line.strip()]

missing = [i for i in wanted if i not in available]
if missing:
    print(f"  {len(available)} models in the live catalogue")
    print("  These IDs are not in it:")
    for i in missing:
        print(f"    {i}")
    print()
    print("  Note the `id` field is not always the bioimage.io nickname.")
    print("  Nicknames that exist, for reference:")
    for entry in catalogue.values():
        nick = entry.get("nickname")
        if nick and nick != entry["id"]:
            print(f"    {nick:26s} -> {entry['id']}")
    raise SystemExit(1)

print(f"  all {len(wanted)} present in a catalogue of {len(available)}")
print()
print("  the dropdown a user will see, in order:")
for index, i in enumerate(wanted):
    entry = available[i]
    mark = "default ->" if index == 0 else "          "
    desc = (entry.get("description") or "").replace("\n", " ")[:58]
    print(f"  {mark} {i:26s} {desc}")

with open("/tmp/ai4life_models.env", "w") as handle:
    handle.write("AI4LIFE_MODELS=" + ",".join(wanted) + "\n")
PY
status=$?
[[ $status -eq 0 ]] || exit $status

VALUE="$(cut -d= -f2- < /tmp/ai4life_models.env)"

if (( ! WRITE )); then
    echo
    echo "AI4LIFE_MODELS=$VALUE"
    echo
    echo "Re-run with --write to put this into $ENV_FILE."
    exit 0
fi

[[ -f "$ENV_FILE" ]] || { echo "Missing $ENV_FILE"; exit 1; }
if grep -q '^AI4LIFE_MODELS=' "$ENV_FILE"; then
    python3 - "$ENV_FILE" "$VALUE" <<'PY'
import sys
path, value = sys.argv[1], sys.argv[2]
lines = open(path).read().splitlines(keepends=True)
out = []
for line in lines:
    out.append(f"AI4LIFE_MODELS={value}\n" if line.startswith("AI4LIFE_MODELS=") else line)
open(path, "w").writelines(out)
PY
else
    {
        printf '\n# Bioimage.io models the AI4Life loader offers, in dropdown order\n'
        printf '# (patches/ai4-papi/0008). Generated from catalog/ai4life-models.txt by\n'
        printf '# scripts/render-ai4life-models.sh — edit that file, not this line.\n'
        printf 'AI4LIFE_MODELS=%s\n' "$VALUE"
    } >> "$ENV_FILE"
fi
echo
echo "  wrote AI4LIFE_MODELS into $ENV_FILE"
echo "  restart PAPI for it to take effect."
