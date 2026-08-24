#!/usr/bin/env bash
# Download the web fonts CAIOS serves itself, and generate the @font-face rules.
#
#   bash scripts/fetch-fonts.sh
#
# Re-runnable, and the only thing that should ever write these files by hand is
# this script. Writes three things, all committed:
#
#   configs/dashboard/fonts/*.woff2             the font files
#   configs/dashboard/fonts/icons.txt           the icon subset, DERIVED from source
#   configs/dashboard/theme/caios/_fonts.scss   generated @font-face rules
#
# Why self-hosted at all (D-45):
#
#   Upstream's index.html pulls four families from fonts.googleapis.com. Two
#   consequences, and the second is the one that matters.
#
#   1. It is a third-party request made by the user's browser on every page
#      load — the same objection raised against the analytics beacon and
#      against fetching the model catalogue from raw.githubusercontent.com.
#
#   2. Material icons are a FONT. Each icon is a ligature: the markup says
#      <mat-icon>menu</mat-icon> and the typeface draws a hamburger. If that
#      font does not load, the browser renders the ligature source instead, so
#      every icon in the dashboard degrades to a word. On a private subnet or
#      a conference network that fails closed, the whole interface breaks in a
#      way that looks catastrophic and has nothing to do with the platform.
#
# Why the icon font is subset:
#
#   The full Material Symbols Rounded variable font is 5,222 KB. The dashboard
#   uses 65 of its ~3,000 icons. Subset to those, with all four axes intact, it
#   is 91 KB. That is not an optimisation, it is the difference between shipping
#   the font at all and not.
#
#   The subset list is DERIVED from the source below, never hand-maintained,
#   and tests/test_icon_subset.py fails if the source starts using an icon the
#   committed list does not carry. A missed icon renders as a word — the exact
#   fault this script exists to fix — so it must not be possible to introduce
#   one quietly.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

SRC="vendor/ai4-dashboard/src"
OUT="configs/dashboard/fonts"
SCSS="configs/dashboard/theme/caios/_fonts.scss"

[[ -d "$SRC" ]] || { echo "vendor/ai4-dashboard missing. Run scripts/clone-vendor.sh."; exit 1; }

# Google serves woff2 only to a browser-shaped user agent. With curl's default
# UA it answers with truetype, which is roughly twice the size.
UA="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"

# The text faces. Changing the design means changing these two lines and
# re-running; nothing else in the repository names a typeface.
#
# IBM Plex Sans + IBM Plex Mono (D-45). The mono is a true sibling of the sans
# rather than an unrelated face, so a deployment id or a GPU figure set in mono
# sits on the same skeleton as the interface text beside it. That matters more
# here than it would elsewhere: this dashboard is mostly numbers.
#
# Prefer a variable range (300..700) to a list of static weights. Asking for
# "300;400;500;600" returns four separate cuts per unicode-range — eight files
# and 299 KB for the sans alone. One variable file covers the whole range in
# 75 KB and lets the theme use any weight in it, including ones we have not
# chosen yet.
FAMILIES=(
    "IBM+Plex+Sans:wght@300..700"
    "IBM+Plex+Mono:wght@400;500"   # no variable cut exists — see the guard below
)

mkdir -p "$OUT"

MODE="${1:-}"

# --check derives the list and compares it to the committed one without
# touching the network or writing anything. tests/test_icon_subset.py runs it,
# so the patterns below are the single source of truth: there is no second copy
# in the test that could drift out of step with this one.
if [[ "$MODE" == "--check" ]]; then
    DERIVED="$(mktemp)"
    trap 'rm -f "$DERIVED"' EXIT
else
    DERIVED="$OUT/icons.txt"
fi

# ---------------------------------------------------------------- icon subset
#
# Every icon name that can reach a <mat-icon>. Four shapes, because the
# dashboard uses all four: a literal between the tags, an attribute on a
# wrapper component, a bound literal, and a string in a component class.
# 150 <mat-icon> tags, 16 of which are interpolated from component inputs.
#
# Nothing here comes from PAPI — there is no icon field on any API interface
# and no icon name in any config file, which is what makes a derived list
# trustworthy rather than a guess.
echo "==> deriving the icon subset from $SRC"
{
    grep -rhoP '<mat-icon[^>]*>\s*\K[a-z0-9_]+(?=\s*</mat-icon)'                        "$SRC" --include="*.html" || true
    grep -rhoP '(?<![a-zA-Z])(?:icon|fontIcon|iconName|prefixIcon|cardIcon|suffixIcon)="\K[a-z0-9_]+(?=")' "$SRC" --include="*.html" || true
    grep -rhoP "\[(?:icon|fontIcon|iconName|prefixIcon|cardIcon|suffixIcon)\]=\"'\K[a-z0-9_]+(?=')"        "$SRC" --include="*.html" || true
    grep -rhoP "(?:icon|iconName|fontIcon|prefixIcon|cardIcon)\s*[:=]\s*'\K[a-z0-9_]+(?=')"                "$SRC" --include="*.ts" || true
    grep -rhoP '(?:icon|iconName|fontIcon|prefixIcon|cardIcon)\s*[:=]\s*"\K[a-z0-9_]+(?=")'                "$SRC" --include="*.ts" || true
    grep -rhoP 'class="[^"]*material-symbols-rounded[^"]*"[^>]*>\s*\K[a-z0-9_]+'         "$SRC" --include="*.html" || true
} | sort -u > "$DERIVED"

icon_count=$(wc -l < "$DERIVED")
(( icon_count > 0 )) || { echo "derived zero icons — the greps above have gone stale"; exit 1; }
echo "    $icon_count icons"

if [[ "$MODE" == "--check" ]]; then
    # The committed font was built for the committed list. If the source has
    # started using an icon that list does not carry, that icon is not in the
    # subset — and a glyph the font lacks renders as the ligature source text,
    # so the button shows the word "delete" instead of a bin. Nothing errors.
    if diff -q "$OUT/icons.txt" "$DERIVED" >/dev/null 2>&1; then
        echo "    [ ok ] committed subset matches the source"
        exit 0
    fi
    echo
    echo "    [FAIL] the icon subset is out of date."
    comm -13 "$OUT/icons.txt" "$DERIVED" | sed 's/^/           + used in source, MISSING from the font: /'
    comm -23 "$OUT/icons.txt" "$DERIVED" | sed 's/^/           - in the font, no longer used:          /'
    echo
    echo "           Re-run: bash scripts/fetch-fonts.sh"
    exit 1
fi

# ------------------------------------------------------------------ downloads
#
# One @font-face block per unicode-range subset Google returns. We keep only
# the Latin ranges: the dashboard ships English and Spanish i18n and nothing
# that needs Cyrillic, Greek or Vietnamese, and those are more than half the
# bytes.
: > "$SCSS"
cat >> "$SCSS" <<'HEADER'
// GENERATED by scripts/fetch-fonts.sh — do not edit by hand.
//
// Self-hosted so the dashboard renders with no network beyond this cluster.
// See that script for why, and for how the icon subset is derived.

HEADER

total=0

fetch() {
    local label="$1" url="$2" slug="$3"
    echo "==> $label"
    local css
    css=$(curl -sS -m 40 -A "$UA" "$url")
    [[ -n "$css" ]] || { echo "    empty response from Google Fonts"; exit 1; }
    # Ask for an axis a family does not have — a variable range on a family that
    # ships only static cuts, say — and Google answers 200 with an HTML error
    # page rather than a 4xx. Without this the failure surfaces further down as
    # "no Latin subset found", which points at the wrong thing entirely.
    if [[ "$css" != *"@font-face"* ]]; then
        echo "    Google returned no @font-face rules for this request."
        echo "    Usually means the family has no such axis — IBM Plex Mono, for"
        echo "    one, has no variable cut, so wght@400..600 fails and wght@400;500"
        echo "    succeeds. Check the family on fonts.google.com."
        exit 1
    fi

    local n=0
    # Split on @font-face so each block keeps its own weight and unicode-range.
    while IFS= read -r block; do
        [[ -z "$block" ]] && continue
        local src_url range family weight style file bytes
        src_url=$(grep -oP 'url\(\K[^)]+' <<<"$block" | head -1)
        [[ -n "$src_url" ]] || continue
        range=$(grep -oP 'unicode-range:\s*\K[^;]+' <<<"$block" || true)
        # Latin only. A block with no range at all (the icon font) is kept.
        if [[ -n "$range" && "$range" != *"U+0000-00FF"* && "$range" != *"U+0100"* ]]; then
            continue
        fi
        family=$(grep -oP "font-family:\s*'\K[^']+" <<<"$block" | head -1)
        # xargs, not `tr -d ' '`: a variable font's weight is a RANGE ("300 700")
        # and deleting the space yields "300700", which is not a valid
        # font-weight. The rule is then dropped and the face never applies.
        weight=$(grep -oP 'font-weight:\s*\K[^;]+' <<<"$block" | head -1 | xargs)
        style=$(grep -oP 'font-style:\s*\K[^;]+' <<<"$block" | head -1 | tr -d ' ')
        n=$((n + 1))
        file="${slug}-${n}.woff2"
        curl -sSL -m 40 -A "$UA" -o "$OUT/$file" "$src_url"
        bytes=$(stat -c%s "$OUT/$file")
        total=$((total + bytes))

        {
            printf '@font-face {\n'
            printf "    font-family: '%s';\n" "$family"
            printf '    font-style: %s;\n' "${style:-normal}"
            printf '    font-weight: %s;\n' "${weight:-400}"
            # swap: show the fallback immediately and repaint when the real face
            # arrives, rather than leaving invisible text. These files are on the
            # same host as the page, so the swap window is milliseconds.
            printf '    font-display: swap;\n'
            printf "    src: url('/assets/fonts/%s') format('woff2');\n" "$file"
            [[ -n "$range" ]] && printf '    unicode-range: %s;\n' "$range"
            printf '}\n\n'
        } >> "$SCSS"

        printf '    %-34s %6.1f KB\n' "$file" "$(echo "$bytes/1024" | bc -l)"
    # Each @font-face block flattened onto one line, because the loop below
    # reads line by line and a block spans five.
    done < <(awk 'BEGIN{RS="@font-face"} NR>1{gsub(/\n/," "); print "@font-face" $0}' <<<"$css")

    (( n > 0 )) || { echo "    CSS had @font-face rules but no Latin subset — response shape changed"; exit 1; }
}

for fam in "${FAMILIES[@]}"; do
    slug=$(tr '[:upper:]' '[:lower:]' <<<"${fam%%:*}" | tr '+' '-')
    fetch "${fam%%:*}" "https://fonts.googleapis.com/css2?family=${fam}&display=swap" "$slug"
done

# The icon font last, so it is the obvious thing at the bottom of the file.
names=$(paste -sd, "$OUT/icons.txt")
fetch "Material Symbols Rounded (subset)" \
    "https://fonts.googleapis.com/css2?family=Material+Symbols+Rounded:opsz,wght,FILL,GRAD@20..48,100..700,0..1,-50..200&icon_names=${names}" \
    "material-symbols-rounded"

printf '\n==> %d files, %.1f KB total\n' "$(ls "$OUT"/*.woff2 | wc -l)" "$(echo "$total/1024" | bc -l)"
echo "    fonts   $OUT"
echo "    rules   $SCSS"
echo
echo "Next: scripts/build-dashboard.sh stages both into the image."
