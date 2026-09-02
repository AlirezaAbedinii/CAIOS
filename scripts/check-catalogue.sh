#!/usr/bin/env bash
# Check that the marketplace is served by this cluster and nothing else.
#
#   bash scripts/check-catalogue.sh
#
# Read-only apart from the last section, which starts a throwaway container and
# removes it. The unit tests in tests/test_catalogue_mirror.py read the
# repository and cannot see a running PAPI; this reads the running platform and
# cannot see the source. Both halves are needed.
#
# WHAT IT IS ACTUALLY ASKING
#
# Not "does the catalogue work" — it worked before the mirror too, whenever
# GitHub happened to be reachable. It asks three harder questions:
#
#   * is the catalogue served without touching a third-party host at all;
#   * does an unreachable source FAIL rather than HANG, which is the difference
#     between a page that errors and a page that spins forever;
#   * is every licence real, rather than the "MIT" the IS_DEV mock returns.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

ENV_FILE="configs/env/caios.env"
[[ -f "$ENV_FILE" ]] || { echo "Missing $ENV_FILE"; exit 1; }
set -a; source "$ENV_FILE"; set +a

API="${CHECK_API_URL:-https://${CAIOS_API_HOST}}"
DASH="${CHECK_DASHBOARD_URL:-https://${CAIOS_DASHBOARD_HOST}}"
USER_NAME="${CHECK_USER:-researcher}"
PASS_VAR="CAIOS_PW_$(echo "$USER_NAME" | tr '[:lower:]-' '[:upper:]_')"
PASSWORD="${!PASS_VAR:-}"

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

fail=0
ok()   { printf '  [ ok ] %s\n' "$1"; }
bad()  { printf '  [FAIL] %s\n' "$1"; fail=1; }
info() { printf '         %s\n' "$1"; }

# --------------------------------------------------------------------------
echo "=== 1. the mirror is being served ==="
# Every unknown path under the dashboard answers 200 with index.html, so a
# status code proves nothing here. Look at the bytes.
for path in \
    "mirror/${MODULES_CATALOGUE_REPO}/master/.gitmodules" \
    "mirror/ai4os/tools-catalog/master/.gitmodules" \
    "mirror/repo-info.json"
do
    body="$(curl -k -sS --max-time 15 "$DASH/$path" 2>/dev/null)"
    if [[ -z "$body" ]]; then
        bad "$path — empty response"
    elif grep -q "<!doctype html" <<<"${body,,}"; then
        bad "$path — served index.html, so the file is not there (nginx/Caddy 200s everything)"
    else
        ok "$path ($(wc -c <<<"$body") bytes)"
    fi
done

# --------------------------------------------------------------------------
echo
echo "=== 2. PAPI reads the mirror, not GitHub ==="
if [[ -z "$PASSWORD" ]]; then
    bad "no password in $PASS_VAR — cannot get a token"
else
    TOKEN="$(bash scripts/get-token.sh "$USER_NAME" "$PASSWORD" 2>/dev/null)"
    [[ -n "$TOKEN" ]] || bad "could not get a token for $USER_NAME"
fi

fetch() {  # path -> writes $TMP/body, prints "code time"
    curl -k -sS --max-time 60 -o "$TMP/body" \
        -w '%{http_code} %{time_total}' \
        -H "Authorization: Bearer ${TOKEN:-}" "$API/v1$1" 2>/dev/null
}

if [[ -n "${TOKEN:-}" ]]; then
    for ep in /catalog/modules/detail /catalog/tools/detail; do
        read -r code secs <<<"$(fetch "$ep")"
        if [[ "$code" != "200" ]]; then
            bad "$ep returned $code"
            info "$(head -c 200 "$TMP/body")"
        else
            n="$(python3 -c "import json;print(len(json.load(open('$TMP/body'))))" 2>/dev/null || echo '?')"
            # Two seconds is generous for a local read and far below the ~90s a
            # blocked GitHub used to take before it gave up.
            if (( $(echo "$secs > 2" | bc -l) )); then
                bad "$ep took ${secs}s for $n items — is it still reaching GitHub?"
            else
                ok "$ep — $n items in ${secs}s"
            fi
        fi
    done
fi

# The strongest single assertion here: PAPI's own log names every host it
# failed to reach, and should name none of them.
hits="$(sudo docker logs caios_papi 2>&1 | grep -ciE 'githubusercontent|api\.github' || true)"
if [[ "$hits" == "0" ]]; then
    ok "no GitHub host appears in PAPI's log for this run"
else
    bad "PAPI's log mentions a GitHub host $hits time(s) — the mirror is being bypassed"
fi

# --------------------------------------------------------------------------
echo
echo "=== 3. every licence is real ==="
if [[ -n "${TOKEN:-}" ]]; then
    read -r code _ <<<"$(fetch /catalog/modules/detail)"
    if [[ "$code" == "200" ]]; then
        python3 - "$TMP/body" <<'PY'
import json, sys
mods = json.load(open(sys.argv[1]))
lic = {m["name"]: (m.get("license") or "") for m in mods}
dates = {m["name"]: m["dates"]["created"] for m in mods}

bad = False
if set(lic.values()) == {"MIT"}:
    print("  [FAIL] every module reports MIT — the IS_DEV mock is winning again")
    bad = True
else:
    print(f"  [ ok ] {len(set(lic.values()))} distinct licences across {len(lic)} modules")

for name, v in sorted(lic.items()):
    if not v:
        print(f"  [FAIL] {name} has no licence")
        bad = True

epoch = [n for n, d in dates.items() if str(d).startswith("1970")]
if epoch:
    print(f"  [FAIL] dated to the epoch: {epoch}")
    bad = True
else:
    print("  [ ok ] no module is dated 1970-01-01")

# Named because it is the case that makes this a licensing problem rather than
# a cosmetic one. AGPL and MIT impose materially different obligations.
yolo = lic.get("ai4os-yolo-torch", "")
if "AGPL" in yolo.upper():
    print(f"  [ ok ] ai4os-yolo-torch reports {yolo} (Ultralytics YOLO is AGPL-3.0)")
else:
    print(f"  [FAIL] ai4os-yolo-torch reports {yolo!r}, expected AGPL")
    bad = True

sys.exit(1 if bad else 0)
PY
        [[ $? -eq 0 ]] || fail=1
    fi
fi

# --------------------------------------------------------------------------
echo
echo "=== 4. an unreachable source fails instead of hanging ==="
# The whole point of the timeout. Upstream passes none, so a blocked host holds
# the worker thread until TCP gives up and the dashboard shows a spinner that
# never resolves — which is how the 2026-09-01 outage presented.
#
# Run against a throwaway PAPI pointed at a blackhole address, so the live one
# is never touched.
BLACKHOLE="http://192.0.2.1/mirror"   # TEST-NET-1, guaranteed unroutable
CID=""
cleanup_probe() { [[ -n "$CID" ]] && sudo docker rm -f "$CID" >/dev/null 2>&1; }
trap 'cleanup_probe; rm -rf "$TMP"' EXIT

CID="$(sudo docker run -d --rm \
    -e IS_PROD=false \
    -e CATALOGUE_BASE_URL="$BLACKHOLE" \
    -e MODULES_CATALOGUE_REPO="${MODULES_CATALOGUE_REPO}" \
    --entrypoint sh caios/papi:latest -c 'sleep 300' 2>/dev/null)"

if [[ -z "$CID" ]]; then
    bad "could not start a probe container from caios/papi:latest"
else
    start=$(date +%s)
    # PAPI is installed with pipx, so its dependencies live in that venv rather
    # than in the system interpreter. `python3 -c` finds no fastapi at all.
    PY_BIN=/root/.local/share/pipx/venvs/ai4papi/bin/python
    out="$(sudo docker exec "$CID" "$PY_BIN" -c "
import os, sys
sys.path.insert(0, '/home/ai4-papi')
from ai4papi.routers.v1.catalog.modules import Modules
from fastapi import HTTPException
try:
    Modules.get_items()
    print('NO_ERROR')
except HTTPException as e:
    print('HTTP', e.status_code)
except Exception as e:
    print('OTHER', e.__class__.__name__)
" 2>&1 | tail -1)"
    elapsed=$(( $(date +%s) - start ))

    case "$out" in
        "HTTP 503")
            if (( elapsed <= 40 )); then
                ok "unreachable source -> HTTP 503 in ${elapsed}s (not a hang)"
            else
                bad "returned 503 but took ${elapsed}s — the timeout is too generous"
            fi
            ;;
        NO_ERROR) bad "a blackhole source returned a catalogue — is the URL being ignored?" ;;
        *)        bad "expected HTTP 503, got: $out (after ${elapsed}s)" ;;
    esac
fi

# --------------------------------------------------------------------------
echo
if [[ $fail -ne 0 ]]; then
    echo "CATALOGUE CHECK FAILED — see [FAIL] lines above."
    exit 1
fi
echo "CATALOGUE CHECK PASSED"
