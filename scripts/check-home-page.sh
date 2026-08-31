#!/usr/bin/env bash
# Check that the home page a browser actually receives is the one we built.
#
#   bash scripts/check-home-page.sh
#   CHECK_DASHBOARD_URL=http://127.0.0.1:18080 bash scripts/check-home-page.sh
#
# Read-only. The unit tests in tests/test_home_page.py read the repository and
# cannot see a build; this reads what nginx serves and cannot see the source.
# Both halves are needed, and the gap between them is where the last three
# visual stages each lost a day.
#
# WHY IT CHECKS BYTES AND NOT STATUS CODES
#
# Every missing path under this dashboard answers HTTP 200 with index.html. A
# font that 404s is a 200 carrying HTML; a stylesheet that was never staged is
# a 200 carrying HTML. Status codes prove nothing here, so everything below
# looks at the content it got back.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

ENV_FILE="configs/env/caios.env"
[[ -f "$ENV_FILE" ]] || { echo "Missing $ENV_FILE"; exit 1; }
set -a; source "$ENV_FILE"; set +a

# NOT named DASHBOARD_URL: caios.env exports that and is sourced above with
# `set -a`, so an override by that name is silently overwritten and the check
# quietly tests the deployed dashboard while reporting on a candidate.
DASH="${CHECK_DASHBOARD_URL:-https://${CAIOS_DASHBOARD_HOST}}"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

fail=0
ok()   { printf '  [ ok ] %s\n' "$1"; }
bad()  { printf '  [FAIL] %s\n' "$1"; fail=1; }

echo "=== 1. the page is served ==="
if ! curl -k -sS --max-time 20 "$DASH/" -o "$TMP/index.html"; then
    bad "cannot reach $DASH"
    exit 1
fi
ok "$DASH answers"

# The route is patched, not redirected, so `/` is the app shell like any other
# path. What proves the home page exists is its lazy chunk, below.
if grep -qi '<app-root' "$TMP/index.html"; then
    ok "/ serves the application"
else
    bad "/ did not serve the application shell"
fi

echo
echo "=== 2. the copy reached the browser ==="
# ngx-translate renders a missing key as the key itself, in display type, with
# no error anywhere. So the strings are checked where the browser reads them.
curl -k -sS --max-time 20 "$DASH/assets/i18n/en.json" -o "$TMP/en.json" 2>/dev/null
if head -c 20 "$TMP/en.json" | grep -qi "<!doctype\|<html"; then
    bad "/assets/i18n/en.json served index.html — the merge did not happen"
else
    python3 - "$TMP/en.json" configs/dashboard/i18n/en.caios.json <<'PY'
import json
import sys


def strip(o):
    if isinstance(o, dict):
        return {k: strip(v) for k, v in o.items() if not k.startswith("_comment")}
    return o


served = json.load(open(sys.argv[1], encoding="utf-8"))
ours = strip(json.load(open(sys.argv[2], encoding="utf-8")))["HOME"]

if "HOME" not in served:
    print("  [FAIL] the served en.json has no HOME block; the merge did not run")
    raise SystemExit(1)


def leaves(node, prefix=""):
    for k, v in node.items():
        if isinstance(v, dict):
            yield from leaves(v, f"{prefix}{k}.")
        else:
            yield prefix + k, v


mismatched = []
for key, value in leaves(ours):
    node = served["HOME"]
    for part in key.split("."):
        node = node.get(part) if isinstance(node, dict) else None
        if node is None:
            break
    if node != value:
        mismatched.append(key)

if mismatched:
    print(f"  [FAIL] {len(mismatched)} string(s) differ from the source: {mismatched[:4]}")
    raise SystemExit(1)

count = len(list(leaves(ours)))
print(f"  [ ok ] all {count} home page strings served, and they are ours")

# Upstream's own keys must survive the merge. A shallow update would take a
# whole block with it and every other page would render its keys as text.
for key in ("SIDENAV", "DEPLOYMENTS", "CATALOG", "ERRORS"):
    if key not in served:
        print(f"  [FAIL] the merge dropped upstream's {key} block")
        raise SystemExit(1)
print("  [ ok ] upstream's own strings survived the merge")

em = [k for k, v in leaves(ours) if "—" in v]
if em:
    print(f"  [FAIL] em dashes reached the browser in: {em}")
    raise SystemExit(1)
print("  [ ok ] no em dashes")
PY
    [[ $? -eq 0 ]] || fail=1
fi

echo
echo "=== 3. the typefaces are typefaces ==="
# The page sets IBM Plex in its own stylesheet. A missing file here is a 200
# carrying HTML, and the page silently falls back to the system sans, which is
# a change nobody would notice until a screenshot was compared.
for font in ibm-plex-sans-1 ibm-plex-sans-2 ibm-plex-mono-2 ibm-plex-mono-4; do
    curl -k -sS --max-time 20 -o "$TMP/$font.woff2" \
        "$DASH/assets/fonts/$font.woff2" 2>/dev/null
    kind="$(file -b "$TMP/$font.woff2" 2>/dev/null)"
    case "$kind" in
        *Web\ Open\ Font*|*WOFF*) ok "$font.woff2 is $kind" ;;
        HTML*) bad "$font.woff2 served index.html — the page falls back to the system sans" ;;
        *)     bad "$font.woff2 is not a font: $kind" ;;
    esac
done

echo
echo "=== 4. the page is self-contained ==="
# D-46. The home page issues no request of its own and fetches nothing from
# anybody else. Its lazy chunk is where a later change would put either.
#
# The chunk name is content-hashed and index.html never names it: the entry
# bundle does, at the point where the route is loaded. So find the entry, read
# the chunk names out of it, and identify ours by something only it contains.
entry="$(grep -oE 'main-[A-Za-z0-9]+\.js' "$TMP/index.html" | head -1)"
chunk=""
if [[ -n "$entry" ]] && curl -k -sS --max-time 30 "$DASH/$entry" -o "$TMP/main.js"; then
    for candidate in $(grep -oE 'chunk-[A-Za-z0-9_-]+\.js' "$TMP/main.js" | sort -u); do
        curl -k -sS --max-time 20 "$DASH/$candidate" -o "$TMP/chunk.js" 2>/dev/null || continue
        if grep -q 'slide__figure' "$TMP/chunk.js" 2>/dev/null; then
            chunk="$candidate"
            break
        fi
    done
fi

if [[ -z "$chunk" ]]; then
    bad "could not find the home page chunk; it may not have been built"
else
    ok "home page chunk is $chunk"

    # Any absolute URL the browser would follow. Comments do not survive the
    # build, so anything left here is a reference, not a note.
    offenders="$(grep -oE 'https?://[a-zA-Z0-9.-]+' "$TMP/chunk.js" | sort -u | grep -v '^https\?://localhost' || true)"
    if [[ -n "$offenders" ]]; then
        bad "the home page chunk references outside hosts: $(echo "$offenders" | tr '\n' ' ')"
    else
        ok "the home page fetches nothing from anybody else"
    fi

    # The vocabulary ban, checked where it matters. The unit tests read the
    # source; this reads what shipped, so a string added straight into a
    # template rather than into en.caios.json is still caught.
    shipped=""
    for word in Nomad Kubernetes vLLM Traefik Keycloak H100 NVIDIA; do
        grep -qi "$word" "$TMP/chunk.js" && shipped="$shipped $word"
    done
    if [[ -n "$shipped" ]]; then
        bad "infrastructure vocabulary shipped in the home page:$shipped"
    else
        ok "no infrastructure vocabulary in what shipped"
    fi
fi

echo
if (( fail )); then
    echo "Home page check FAILED."
    exit 1
fi
cat <<'MSG'
Home page check passed.

What it cannot tell you: whether the page reads well, whether the drawings say
what they are meant to say, and whether the motion feels considered. Open it and
look. That is the half of this stage no script has ever settled.
MSG
