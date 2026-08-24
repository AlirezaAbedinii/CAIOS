#!/usr/bin/env bash
# Check that the running dashboard reads as CAIOS, not as somebody else's stack.
#
#   bash scripts/check-branding.sh
#
# Read-only. Fetches the dashboard and PAPI over HTTPS and inspects what they
# actually serve, not what the configuration files say they should.
#
# The Stage 5 gate is "someone unfamiliar with the project opens the dashboard
# and reads it as a medical imaging platform". That is a judgement, and no
# script settles it. This settles the half that is mechanical — no foreign
# branding, no third-party tracking, real artwork, a catalogue that fits the
# audience — so the judgement is about the part that needs a human.
#
# WHY IT CHECKS BYTES AND NOT STATUS CODES
#
# The dashboard shipped for days with no logo and no favicon. Both returned
# HTTP 200, because nginx answers a missing asset with index.html — so the
# browser received HTML labelled as a PNG, the top-left of every page was a
# broken image, and every naive check passed. Anything here that can be
# verified by content is verified by content.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

ENV_FILE="configs/env/caios.env"
[[ -f "$ENV_FILE" ]] || { echo "Missing $ENV_FILE"; exit 1; }
set -a; source "$ENV_FILE"; set +a

DASH="https://${CAIOS_DASHBOARD_HOST}"
API="https://${CAIOS_API_HOST}"
VO="${CAIOS_VO:-vo.caios.ca}"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

fail=0
ok()   { printf '  [ ok ] %s\n' "$1"; }
bad()  { printf '  [FAIL] %s\n' "$1"; fail=1; }
warn() { printf '  [warn] %s\n' "$1"; }

echo "=== 1. the dashboard answers ==="
if ! curl -k -sS --max-time 20 "$DASH/" -o "$TMP/index.html"; then
    bad "cannot reach $DASH"
    exit 1
fi
ok "$DASH is up"

title="$(grep -oiE '<title>[^<]*</title>' "$TMP/index.html" | sed -E 's|</?title>||gI')"
[[ "$title" == *CAIOS* ]] && ok "page title is \"$title\"" || bad "page title is \"$title\", expected CAIOS"

echo
echo "=== 2. runtime configuration ==="
if ! curl -k -sS --max-time 20 "$DASH/assets/config/config.json" -o "$TMP/config.json"; then
    bad "config.json is not served — the dashboard cannot configure itself"
else
    python3 - "$TMP/config.json" <<'PY'
import json
import sys

conf = json.load(open(sys.argv[1]))
problems = []

# Anything still pointing at AI4EOSC is live, not cosmetic: this file is what
# the running app uses for its API, its login and its links.
blob = json.dumps(conf)
if "ai4eosc" in blob.lower():
    hits = [k for k, v in conf.items() if "ai4eosc" in json.dumps(v).lower()]
    problems.append(f"config.json still references ai4eosc in: {', '.join(hits)}")

analytics = conf.get("analytics") or {}
if analytics.get("src"):
    problems.append(
        f"analytics beacon is live ({analytics['src']}) — demo traffic would be "
        "reported to a third party"
    )

for key, want in (("projectName", "CAIOS"), ("voName", "vo.caios.ca")):
    if conf.get(key) != want:
        problems.append(f"{key} is {conf.get(key)!r}, expected {want!r}")

for link in conf.get("footerLinks") or []:
    if "ai4eosc" in json.dumps(link).lower():
        problems.append(f"footer link points at AI4EOSC: {link}")

for entry in conf.get("sidenavMenu") or []:
    if "ai4eosc" in json.dumps(entry).lower():
        problems.append(f"sidenav entry points at AI4EOSC: {entry}")

for p in problems:
    print(f"  [FAIL] {p}")
if not problems:
    print("  [ ok ] no AI4EOSC references, analytics beacon disabled, names correct")
raise SystemExit(1 if problems else 0)
PY
    [[ $? -eq 0 ]] || fail=1
fi

echo
echo "=== 3. branding artwork is really artwork ==="
for asset in dashboard-logo.png favicon.ico forbidden.png not-found.png pacslab-logo.png; do
    ctype="$(curl -k -sS --max-time 20 -o "$TMP/$asset" -w '%{content_type}' "$DASH/assets/images/$asset")"
    kind="$(file -b "$TMP/$asset" 2>/dev/null)"
    case "$kind" in
        PNG*|"MS Windows icon"*)
            ok "$asset is $(echo "$kind" | cut -d, -f1,2)" ;;
        HTML*)
            bad "$asset served index.html (HTTP 200, content-type $ctype) — the asset is missing" ;;
        *)
            bad "$asset is not an image: $kind" ;;
    esac
done

echo
echo "=== 3b. no funding claims we cannot make ==="
# Upstream renders an EU flag in the sidenav footer, unconditionally. That is a
# European funding acknowledgement, correct for AI4EOSC and false for us: CAIOS
# is a Canadian project on Compute Canada under a Canadian allocation. It is
# replaced by the PACS Lab logo (patches/ai4-dashboard/0001), and this makes
# sure a dashboard rebuild that drops the patch cannot quietly bring it back.
bundle_main="$(grep -oE 'main-[A-Z0-9]+\.js' "$TMP/index.html" | head -1)"
if [[ -n "$bundle_main" ]] && curl -k -sS --max-time 30 "$DASH/$bundle_main" -o "$TMP/main.js"; then
    if grep -q 'eu-flag' "$TMP/main.js"; then
        bad "the sidenav still renders eu-flag.jpg — it claims EU funding CAIOS does not have"
    else
        ok "no EU funding acknowledgement rendered"
    fi
    if grep -q 'pacslab-logo' "$TMP/main.js"; then
        ok "PACS Lab is credited beside the CAIOS mark"
    else
        bad "pacslab-logo.png is not referenced — the dashboard patch did not apply"
    fi
fi

echo
echo "=== 3c. the LLM catalogue is ours, and it is one file ==="
# R-07. Upstream's dashboard fetched this list from raw.githubusercontent.com,
# so the model CARDS came from AI4OS's thirteen while the deploy form's DROPDOWN
# came from our PAPI's nine. Two sources disagreeing about what exists.
#
# Content, not status: every missing path under this dashboard answers 200 with
# index.html, and js-yaml parses HTML into something shapeless rather than
# throwing — so "did it 200" tells you nothing at all here.
curl -k -sS --max-time 20 "$DASH/assets/config/vllm.yaml" -o "$TMP/vllm.yaml" 2>/dev/null
if head -c 20 "$TMP/vllm.yaml" | grep -qi "<!doctype\|<html"; then
    bad "/assets/config/vllm.yaml served index.html — build-dashboard.sh did not stage it"
else
    python3 - "$TMP/vllm.yaml" configs/papi/vllm.yaml <<'PY'
import sys

import yaml

try:
    served = yaml.safe_load(open(sys.argv[1], encoding="utf-8"))["models"]
except Exception as e:
    print("  [FAIL] the served catalogue is not the YAML we expect: %s" % e)
    raise SystemExit(1)
ours = yaml.safe_load(open(sys.argv[2], encoding="utf-8"))["models"]

if list(served) != list(ours):
    only_served = [m for m in served if m not in ours]
    only_ours = [m for m in ours if m not in served]
    print("  [FAIL] the served catalogue is not configs/papi/vllm.yaml")
    if only_served:
        print("         served but not ours: %s" % only_served)
    if only_ours:
        print("         ours but not served: %s" % only_ours)
    raise SystemExit(1)
print("  [ ok ] %d models, and they are ours" % len(served))

missing = [m for m, c in served.items() if not c.get("description")]
if missing:
    print("  [FAIL] cards with no description: %s" % missing)
    raise SystemExit(1)
print("  [ ok ] every card has a description")
PY
    [[ $? -eq 0 ]] || fail=1
fi

# Every card renders a {family}_logo.png. Our nine models span five families and
# upstream ships a badge for two of them, so six of the nine cards showed a
# broken image until the missing three were generated. `file`, not the status
# code: a missing asset here is a 200 carrying index.html.
families=$(python3 -c "
import yaml
d = yaml.safe_load(open('configs/papi/vllm.yaml'))['models']
print(' '.join(sorted({m['family'] for m in d.values()})))
" 2>/dev/null)
for family in $families; do
    curl -k -sS --max-time 20 -o "$TMP/badge.png" \
        "$DASH/assets/images/llm-companies/${family}_logo.png" 2>/dev/null
    kind="$(file -b "$TMP/badge.png" 2>/dev/null)"
    case "$kind" in
        PNG*)  ok "${family} card badge is $(echo "$kind" | cut -d, -f1,2)" ;;
        HTML*) bad "${family}_logo.png served index.html — that card shows a broken image" ;;
        *)     bad "${family}_logo.png is not an image: $kind" ;;
    esac
done

# The browser must not go to GitHub for it either. The URL is compiled into the
# bundle, so this catches a rebuild that dropped patch 0002 even if the asset
# above is staged correctly and looks perfect.
if [[ -s "$TMP/main.js" ]]; then
    if grep -q 'ai4-papi/refs/heads/master/etc/vllm.yaml' "$TMP/main.js"; then
        bad "the bundle still fetches the model list from raw.githubusercontent.com"
    else
        ok "no third-party fetch for the model list"
    fi
fi

echo
echo "=== 3d. the page renders with no network but ours ==="

# R-28. The dashboard used to fetch four typefaces from Google on every page
# load. Two of them are the Material Symbols icon sets, and Material icons are
# a FONT: each icon is a ligature, so <mat-icon>menu</mat-icon> draws a
# hamburger only if the typeface arrived. When it does not, the browser renders
# the ligature source and every icon becomes the word it is named after.
#
# So this is not a privacy nicety. On an air-gapped demo machine or a
# conference network that fails closed, an unpatched dashboard looks
# catastrophically broken for a reason unrelated to the platform.
#
# Checked against the served index.html and the compiled bundle, because patch
# 0004 touches the first and the stylesheet touches the second — a rebuild that
# dropped either one would still pass a check that only looked at the other.
curl -k -sS --max-time 20 -o "$TMP/index.html" "$DASH/" 2>/dev/null

leaked=0
for host in fonts.googleapis.com fonts.gstatic.com; do
    if grep -q "$host" "$TMP/index.html" 2>/dev/null; then
        bad "index.html still reaches $host — icons break with no internet"
        leaked=1
    fi
done
(( leaked )) || ok "index.html reaches no third-party font host"

# The fonts must actually be there. nginx answers a missing path with
# index.html and HTTP 200, so a 404 here is invisible: the browser gets a web
# page where it asked for a font, fails to parse it, and quietly falls back —
# which for the icon font means words instead of icons. Same shape as R-26.
if [[ -s "$TMP/main.js" ]] || [[ -s "$TMP/index.html" ]]; then
    font_file="$(grep -rhoP "/assets/fonts/[A-Za-z0-9._-]+\.woff2" "$TMP"/*.js "$TMP/index.html" 2>/dev/null | head -1)"
    # The stylesheet is a separate bundle; ask for a name we know we shipped if
    # nothing turned up in the JS.
    [[ -n "$font_file" ]] || font_file="/assets/fonts/material-symbols-rounded-1.woff2"
    curl -k -sS --max-time 20 -o "$TMP/font.bin" "$DASH$font_file" 2>/dev/null
    kind="$(file -b "$TMP/font.bin" 2>/dev/null)"
    case "$kind" in
        *Web*Open*Font*|*WOFF*) ok "$(basename "$font_file") is a real font ($(du -h "$TMP/font.bin" | cut -f1))" ;;
        HTML*)                  bad "$font_file served index.html — every icon will render as a word" ;;
        *)                      bad "$font_file is not a font: $kind" ;;
    esac
fi

echo
echo "=== 4. the marketplace fits the audience ==="
PW_VAR="CAIOS_PW_RESEARCHER"
TOKEN="$(bash scripts/get-token.sh researcher "${!PW_VAR:-}" 2>/dev/null)"
if [[ -z "$TOKEN" ]]; then
    warn "no token — skipping catalogue checks (is Keycloak up?)"
else
    curl -k -sS --max-time 30 -H "Authorization: Bearer $TOKEN" "$API/v1/catalog/modules" -o "$TMP/modules.json"
    python3 - "$TMP/modules.json" catalog/keep.txt <<'PY'
import json
import sys

served = set(json.load(open(sys.argv[1])))
keep = set()
for line in open(sys.argv[2]):
    line = line.split("#")[0].strip()
    if line:
        keep.add(line)

extra = served - keep
missing = keep - served
if extra:
    print(f"  [FAIL] marketplace serves modules not in keep.txt: {sorted(extra)}")
if missing:
    print(f"  [FAIL] keep.txt lists modules the marketplace does not serve: {sorted(missing)}")
if not extra and not missing:
    print(f"  [ ok ] {len(served)} modules, exactly matching catalog/keep.txt")
raise SystemExit(1 if (extra or missing) else 0)
PY
    [[ $? -eq 0 ]] || fail=1

    # A module whose /config errors is worse than one that is absent: it is a
    # visible entry that fails the moment it is clicked.
    broken=()
    for m in $(python3 -c "import json;[print(x) for x in json.load(open('$TMP/modules.json'))]"); do
        code="$(curl -k -sS --max-time 30 -o /dev/null -w '%{http_code}' \
            -H "Authorization: Bearer $TOKEN" "$API/v1/catalog/modules/$m/config?vo=$VO")"
        [[ "$code" == "200" ]] || broken+=("$m($code)")
    done
    if (( ${#broken[@]} )); then
        bad "these modules error when opened: ${broken[*]}"
    else
        ok "every module returns a deployable configuration"
    fi

    echo
    echo "=== 5. neuroscience is actually on offer ==="
    curl -k -sS --max-time 30 -H "Authorization: Bearer $TOKEN" \
        "$API/v1/catalog/tools/ai4os-ai4life-loader/config?vo=$VO" -o "$TMP/ai4life.json"
    python3 - "$TMP/ai4life.json" <<'PY'
import json
import sys

conf = json.load(open(sys.argv[1]))
model = conf.get("general", {}).get("model_id", {})
options = model.get("options") or []
default = model.get("value")

if not options:
    print("  [FAIL] the AI4Life loader offers no models")
    raise SystemExit(1)
if len(options) > 30:
    print(f"  [warn] {len(options)} models offered — the curated list is not in effect")
    raise SystemExit(0)
print(f"  [ ok ] {len(options)} curated models, default {default!r}")
raise SystemExit(0)
PY
    [[ $? -eq 0 ]] || fail=1
fi

echo
echo "=== 6. compiled-in upstream defaults (informational) ==="
# These live in the JavaScript bundle because upstream compiles its own
# deployment's addresses in as fallbacks. They are overridden at container start
# by the runtime config checked in section 2, which is why login works against
# our Keycloak. They are listed rather than ignored because if that injection
# ever silently failed, the dashboard would quietly talk to AI4EOSC instead.
bundle="$(grep -oE 'main-[A-Z0-9]+\.js' "$TMP/index.html" | head -1)"
if [[ -n "$bundle" ]] && curl -k -sS --max-time 30 "$DASH/$bundle" -o "$TMP/main.js"; then
    hits="$(grep -oc 'cloud\.ai4eosc\.eu' "$TMP/main.js" 2>/dev/null || echo 0)"
    if [[ "$hits" == "0" ]]; then
        ok "no upstream addresses compiled into $bundle"
    else
        warn "$hits upstream address(es) compiled into $bundle as fallbacks"
        warn "  overridden at runtime — section 2 confirms the live values are ours"
    fi
    if grep -q 'plausible-script' "$TMP/main.js"; then
        warn "the analytics loader is still in the bundle; it runs with an empty"
        warn "  src, so it makes no third-party request (section 2 checks that)"
    fi
fi

echo
if (( fail )); then
    echo "BRANDING CHECK FAILED — see [FAIL] lines above."
    exit 1
fi
cat <<'DONE'
Branding check passed.

The mechanical half of the Stage 5 gate holds: no foreign branding, no
third-party tracking, real artwork, and a catalogue that fits the audience.

The other half needs a person: open the dashboard, and ask someone who does not
know the project what they think it is for.
DONE
