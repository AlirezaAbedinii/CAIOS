#!/usr/bin/env bash
# Prune our fork of the module catalogue down to catalog/keep.txt.
#
#   bash scripts/curate-catalogue.sh            # show what would change
#   bash scripts/curate-catalogue.sh --apply    # rewrite and push the fork
#
# Prints by default and changes nothing. Only --apply pushes.
#
# WHAT THE CATALOGUE ACTUALLY IS
#
# A repository whose only meaningful content is `.gitmodules` — one submodule
# per marketplace entry. PAPI reads exactly that file, from
# raw.githubusercontent.com, and never clones anything:
#
#     ai4papi/routers/v1/catalog/common.py, Catalog.get_items()
#
# So curating the marketplace means removing submodule entries, not writing
# code. Everything else in the repo is incidental.
#
# WHY A FORK RATHER THAN A FILTER IN PAPI
#
# A filter would mean carrying another patch against upstream forever, and the
# curated list would live in our configuration where nobody outside the team
# could see it. The fork is the path upstream documents for a new flavour, it is
# one line of patch (the repo name), and the result is publicly inspectable —
# which matters when the question "what did you actually change?" comes up.
#
# AFTER RUNNING THIS
#
# PAPI caches the catalogue for six hours. Either POST /v1/catalog/modules/refresh
# or restart PAPI, or the marketplace will show the old list and look broken.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

FORK="${CAIOS_CATALOGUE_FORK:-AlirezaAbedinii/caios-modules-catalog}"
KEEP_FILE="catalog/keep.txt"
WORK="${CAIOS_CATALOGUE_WORK:-/mnt/tmp/caios-catalogue}"
APPLY=0
[[ "${1:-}" == "--apply" ]] && APPLY=1

[[ -f "$KEEP_FILE" ]] || { echo "Missing $KEEP_FILE"; exit 1; }
command -v gh >/dev/null || { echo "gh not found — needed to push the fork."; exit 1; }

# Strip inline comments and blanks.
mapfile -t KEEP < <(sed 's/#.*//' "$KEEP_FILE" | tr -d ' \t' | grep -v '^$' | sort -u)
echo "==> keep list: ${#KEEP[@]} modules"

echo "==> fetching $FORK"
rm -rf "$WORK"
mkdir -p "$(dirname "$WORK")"
git clone -q "https://github.com/$FORK.git" "$WORK" 2>&1 | tail -2
[[ -f "$WORK/.gitmodules" ]] || { echo "No .gitmodules in the fork — did the fork finish?"; exit 1; }

present="$(python3 -c "
import configparser
c = configparser.ConfigParser()
c.read('$WORK/.gitmodules')
for s in c.sections():
    print(dict(c.items(s))['path'])
" | sort -u)"

missing=()
for k in "${KEEP[@]}"; do
    grep -qx "$k" <<<"$present" || missing+=("$k")
done
if (( ${#missing[@]} )); then
    echo "  These keep-list entries are not in the catalogue at all:"
    printf '    %s\n' "${missing[@]}"
    echo "  Fix $KEEP_FILE — a typo here silently shrinks the marketplace."
    exit 1
fi

remove="$(comm -23 <(echo "$present") <(printf '%s\n' "${KEEP[@]}"))"
remove_count="$(grep -c . <<<"$remove" || true)"

echo
echo "==> keeping ${#KEEP[@]}:"
printf '    %s\n' "${KEEP[@]}"
echo
echo "==> removing $remove_count:"
sed 's/^/    /' <<<"$remove"

if (( ! APPLY )); then
    echo
    echo "Nothing changed. Re-run with --apply to rewrite and push the fork."
    exit 0
fi

echo
echo "==> rewriting .gitmodules"
cd "$WORK"

# A fresh clone inherits no identity — this machine has none set globally, only
# per-repository on the CAIOS checkout. Without this, `git commit` fails and, if
# nobody is checking exit codes, the script cheerfully reports a push that never
# happened.
git config user.name "$(git -C "$ROOT" config user.name)"
git config user.email "$(git -C "$ROOT" config user.email)"
while read -r path; do
    [[ -n "$path" ]] || continue
    # Submodules here are gitlinks with no working tree, so `git rm` is enough;
    # deinit would fail on something never initialised.
    git rm -q --cached "$path" 2>/dev/null || true
    rm -rf "$path"
    git config -f .gitmodules --remove-section "submodule.$path" 2>/dev/null || true
done <<<"$remove"

# Blank lines left behind by --remove-section make the file untidy but parse
# fine; tidy anyway so a reviewer sees a clean diff.
python3 - <<'PY'
import re
from pathlib import Path

p = Path(".gitmodules")
text = re.sub(r"\n{3,}", "\n\n", p.read_text().strip()) + "\n"
p.write_text(text)
PY

git add -A
if git diff --cached --quiet; then
    echo "  nothing to commit — fork already curated."
    exit 0
fi

git commit -q -m "Curate for CAIOS: keep ${#KEEP[@]} medical and general-purpose modules

The CAIOS deployment serves medical and neuroscience researchers. Of the 46
modules upstream, roughly two thirds are marine, agricultural or remote
sensing — good modules, wrong audience.

Kept: the two medical modules, the retrainable general-purpose backbones
someone would run on their own images, body pose for movement analysis, and
the demo app.

Removed entries are untouched upstream and can be restored by syncing this
fork." || { echo "  commit FAILED"; exit 1; }

git push origin HEAD 2>&1 | tail -2 || { echo "  push FAILED"; exit 1; }
echo "  pushed to $FORK"

echo
echo "==> PAPI caches the catalogue for six hours. Refresh it:"
echo "     curl -k -X PUT -H \"Authorization: Bearer \$TOKEN\" \\"
echo "       https://<api-host>/v1/catalog/modules/refresh"
