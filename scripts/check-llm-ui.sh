#!/usr/bin/env bash
# Stage L4 gate: deploy the chat interface AND the engine, log in as the
# administrator the deployment created, and have a conversation through it.
#
#   bash scripts/check-llm-ui.sh                          # the default model
#   bash scripts/check-llm-ui.sh LiquidAI/LFM2.5-1.2B-Instruct   # a faster one
#   bash scripts/check-llm-ui.sh --keep                   # leave it running
#
# DEPLOYS AND THEN DELETES a `both` deployment. Self-cleaning, so it can run in
# a loop — but it holds a GPU while it runs, and `--keep` holds one until you
# delete it by hand.
#
# WHY THIS EXISTS SEPARATELY FROM check-llm-deploy.sh
#
# check-llm-deploy.sh proves the engine answers. Everything it tests can be
# green while the thing a researcher actually opens is useless, and in Stage L4
# it was: Open WebUI reached vLLM through Traefik, hit our own CA, caught the
# TLS error, and served
#
#     GET /api/models -> 200 {"data": []}
#
# A deployment Nomad called healthy, a login page that worked, an admin account
# that was correct, and an empty model dropdown. Nothing outside the container's
# stderr said why. So this script asserts on CONTENT at every step — the model
# list names the model we asked for, the reply has words in it — and never on a
# status code alone. Patch 0010 is the fix; this is what would have caught it.
#
# The last check is the one no `curl` normally makes: that the reply arrives in
# pieces rather than in one block. Server-sent events through a reverse proxy
# is exactly the kind of thing that works until a proxy buffers it, and a
# buffered stream looks like a hung browser for thirty seconds.
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

# The Open WebUI administrator this deployment will create for itself. The
# password is generated per run and thrown away with the deployment, so there is
# nothing here to commit and nothing to rotate. It is printed under --keep,
# because then you have to log in by hand.
UI_EMAIL="${CAIOS_LLM_UI_EMAIL:-llm-check@caios.ca}"
UI_PASSWORD="${CAIOS_LLM_UI_PASSWORD:-$(head -c 18 /dev/urandom | base64 | tr -d '/+=')}"

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

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
        echo "=== 8. delete it, and check it is gone ==="
        api DELETE "/v1/deployments/tools/$JOB_ID?vo=$VO" >/dev/null 2>&1
        sleep 3
        if api GET "/v1/deployments/tools?vo=$VO" | grep -q "$JOB_ID"; then
            printf '  [FAIL] %s\n' "$JOB_ID is still listed after DELETE"
        else
            printf '  [ ok ] %s\n' "deleted, and no longer listed"
        fi
    elif [[ -n "$JOB_ID" ]]; then
        echo
        echo "  --keep: $JOB_ID is still running and still holding a GPU."
        echo "     UI:       ${UI:-not published}"
        echo "     login:    $UI_EMAIL"
        echo "     password: $UI_PASSWORD"
    fi
}
trap 'cleanup; rm -rf "$TMP"' EXIT

if [[ -z "$MODEL" ]]; then
    MODEL="$(api GET "/v1/catalog/tools/ai4os-llm/config?vo=$VO" \
        | python3 -c 'import json,sys;print(json.load(sys.stdin)["llm"]["vllm_model_id"]["value"])' 2>/dev/null)"
fi
[[ -n "$MODEL" ]] || { echo "Could not determine which model to deploy."; exit 1; }

echo "=== 1. deploy $MODEL (type: both) ==="
CONF="$(MODEL="$MODEL" EMAIL="$UI_EMAIL" PW="$UI_PASSWORD" python3 -c '
import json, os
print(json.dumps({
    "general": {"title": "CAIOS LLM UI check", "desc": "scripts/check-llm-ui.sh"},
    "llm": {
        "type": "both",
        "vllm_model_id": os.environ["MODEL"],
        "ui_username": os.environ["EMAIL"],
        "ui_password": os.environ["PW"],
    },
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
echo "=== 2. wait for the chat interface ==="
# Open WebUI is gated behind check_vllm_startup, which is a non-sidecar prestart
# task — so the UI answering at all means the model is already loaded. That is
# the single most useful thing this deployment shape gives us, and it is worth
# stating: if the UI is up, vLLM is up.
#
# As in check-llm-deploy.sh, PAPI publishes the endpoint with Nomad's own
# ${meta.domain} still in it until the allocation is placed, so anything
# carrying a ${...} is not an endpoint yet (R-21).
#
# The poll is deliberately tight, and the FIRST successful body is kept: section
# 4 asserts against that rather than against a later fetch. Whether signup was
# already closed the very first time the UI answered is the whole of R-22, and a
# leisurely poll cannot tell the difference between "closed at boot" and "closed
# a few seconds later by something else".
#
# The loop asks the UI FIRST and PAPI second, and breaks the moment the UI
# answers. That ordering matters: the PAPI detail endpoint probes both
# deployment endpoints itself with a 2 s timeout each, so asking it first would
# add up to four seconds between the port opening and us noticing — which is
# exactly the tightness R-22 depends on.
UI=""; READY_CODE=""; EARLY_RUNNING=""; STATUS=""; STATUS_TRAIL=""
for _ in $(seq 1 "$((DEPLOY_TIMEOUT / 3))"); do
    if [[ -n "$UI" && "$UI" != *'${'* ]]; then
        READY_CODE=$(curl -k -sS --max-time 10 -o "$TMP/config.json" -w '%{http_code}' \
            "$UI/api/config" 2>/dev/null)
        [[ "$READY_CODE" == "200" ]] && break
    fi

    # One GET serves both purposes: the endpoint, and the status PAPI is telling
    # the dashboard right now. Reached only while the UI is not answering.
    DEP="$(api GET "/v1/deployments/tools/$JOB_ID?vo=$VO" 2>/dev/null)"
    STATUS="$(python3 -c 'import json,sys;print(json.load(sys.stdin).get("status",""))' <<<"$DEP" 2>/dev/null)"
    if [[ -z "$UI" || "$UI" == *'${'* ]]; then
        UI="$(python3 -c 'import json,sys;print((json.load(sys.stdin).get("endpoints") or {}).get("ui",""))' <<<"$DEP" 2>/dev/null)"
    fi
    [[ -n "$STATUS" && "$STATUS_TRAIL" != *"$STATUS"* ]] &&
        STATUS_TRAIL="${STATUS_TRAIL:+$STATUS_TRAIL -> }$STATUS"

    # R-23, and the reason Stage L4b exists. Anything reached here has already
    # failed to answer on this pass, so `running` here means PAPI is telling the
    # dashboard to show a green badge and enable Quick access in front of a
    # Bad Gateway. Measured at 184 seconds wide before patch 0011.
    [[ "$STATUS" == "running" ]] && EARLY_RUNNING="${EARLY_RUNNING:-$(( $(date +%s) - T0 ))}"

    sleep 3
done
READY=$(( $(date +%s) - T0 ))

if [[ "$READY_CODE" != "200" ]]; then
    bad "the UI never answered within ${DEPLOY_TIMEOUT}s (last status: ${READY_CODE:-no response})"
    info "endpoint: ${UI:-none published}"
    info "check the allocation: NOMAD_NAMESPACE=caios nomad job status $JOB_ID"
    exit 1
fi
ok "UI answering after ${READY}s: $UI"
info "which also means vLLM loaded the model — check_vllm_startup gates it"
info "PAPI status trail: ${STATUS_TRAIL:-none observed}"

# The assertion Stage L4b exists to make.
if [[ -n "$EARLY_RUNNING" ]]; then
    bad "PAPI said 'running' at T+${EARLY_RUNNING}s; the UI only answered at T+${READY}s (R-23)"
    info "$(( READY - EARLY_RUNNING ))s of green badge and an enabled Quick access"
    info "button in front of a Bad Gateway. Patch 0011 is the fix — check it is"
    info "applied:  grep -c unstarted_user_tasks build/ai4-papi/ai4papi/nomad_utils.py"
else
    ok "PAPI never reported 'running' before the UI answered"
fi

echo
echo "=== 3. it is Open WebUI, not the dashboard ==="
# Both are served by the same Traefik under the same wildcard certificate, so a
# routing mistake gives a 200 for the wrong application. Content, not status.
curl -k -sS --max-time 20 "$UI/" -o "$TMP/ui.html" -w '' 2>/dev/null
title="$(grep -oiE '<title>[^<]*</title>' "$TMP/ui.html" | sed -E 's|</?title>||gI' | head -1)"
[[ "$title" == *"Open WebUI"* ]] \
    && ok "page title is \"$title\"" \
    || bad "page title is \"${title:-none}\", expected Open WebUI"
if grep -qi "CAIOS" "$TMP/ui.html"; then
    bad "the UI hostname is serving the CAIOS dashboard, not Open WebUI"
else
    ok "no dashboard markup at this hostname"
fi

echo
echo "=== 4. authentication is on and signup is closed ==="
# $TMP/config.json is the first 200 the UI ever served, captured by the loop
# above. Nothing in this deployment closes signup after boot any more — the
# create-admin task that used to do it is gone (R-22) — so "closed here" can
# only mean "closed before the port opened".
python3 - "$TMP/config.json" <<'PY'
import json, sys

c = json.load(open(sys.argv[1]))
f = c.get("features", {})
print("  [ ok ] Open WebUI %s" % c.get("version", "?"))
bad = 0
if f.get("auth") is True:
    print("  [ ok ] authentication is enabled")
else:
    print("  [FAIL] features.auth is %r — the UI is open to anyone" % f.get("auth")); bad = 1
if f.get("enable_signup") is False:
    print("  [ ok ] signup is closed")
else:
    print("  [FAIL] features.enable_signup is %r — the next visitor can register"
          % f.get("enable_signup")); bad = 1
if c.get("onboarding"):
    print("  [FAIL] the UI is in onboarding mode — no admin account was created"); bad = 1
raise SystemExit(bad)
PY
[[ $? -eq 0 ]] || fail=1

# Reported and enforced are different claims, and the only way to test the
# second one is to try. This probe has a side effect on purpose: if it succeeds,
# THIS SCRIPT is now the administrator of the deployment it was testing. That is
# not a flaw in the test, it is the finding — it is precisely what a person
# opening the Quick Access link a moment early would have done. The deployment
# is deleted at the end either way.
code=$(curl -k -sS --max-time 20 -o "$TMP/signup.json" -w '%{http_code}' \
    -X POST -H "Content-Type: application/json" "$UI/api/v1/auths/signup" \
    -d '{"email":"passer-by@example.org","password":"not-my-cluster","name":"Passer By"}' 2>/dev/null)
if [[ "$code" == "403" ]]; then
    ok "a second signup is refused (403), not merely discouraged"
else
    bad "signup returned $code — a stranger can create an account"
    if [[ "$code" == "200" ]]; then
        info "This run has just registered passer-by@example.org, and Open WebUI"
        info "gives administrator to whoever registers first. The deployment now"
        info "belongs to the test, so the signin below will fail too — that is a"
        info "consequence of this line, not a second fault. R-22."
    fi
fi

echo
echo "=== 5. the admin account is the one the deployment created ==="
code=$(curl -k -sS --max-time 20 -o "$TMP/signin.json" -w '%{http_code}' \
    -X POST -H "Content-Type: application/json" "$UI/api/v1/auths/signin" \
    -d "$(EMAIL="$UI_EMAIL" PW="$UI_PASSWORD" python3 -c '
import json, os
print(json.dumps({"email": os.environ["EMAIL"], "password": os.environ["PW"]}))')" 2>/dev/null)
if [[ "$code" != "200" ]]; then
    bad "signin as $UI_EMAIL returned $code"
    info "$(head -c 300 "$TMP/signin.json")"
    exit 1
fi
UITOK="$(python3 -c 'import json;print(json.load(open("'"$TMP"'/signin.json")).get("token",""))')"
[[ -n "$UITOK" ]] && ok "signed in as $UI_EMAIL" || bad "signin returned no token"
role="$(python3 -c 'import json;print(json.load(open("'"$TMP"'/signin.json")).get("role",""))')"
[[ "$role" == "admin" ]] \
    && ok "the account is an administrator" \
    || bad "the account has role \"$role\", not admin"

echo
echo "=== 6. the UI can see the model ==="
# The check that catches patch 0010's absence. An empty list here comes back as
# an HTTP 200, and every naive check passes while the dropdown is empty.
curl -k -sS --max-time 30 -H "Authorization: Bearer $UITOK" "$UI/api/models" \
    -o "$TMP/models.json" 2>/dev/null
python3 - "$TMP/models.json" "$MODEL" <<'PY'
import json, sys

data = json.load(open(sys.argv[1])).get("data") or []
ids = [m.get("id") for m in data]
if not ids:
    print("  [FAIL] the model list is empty — the UI cannot reach vLLM.")
    print("         This is a 200. Read the open-webui task's stderr:")
    print("         nomad alloc logs <alloc> open-webui | grep -i ssl")
    raise SystemExit(1)
if sys.argv[2] not in ids:
    print("  [FAIL] the UI offers %s, expected %s" % (ids, sys.argv[2])); raise SystemExit(1)
print("  [ ok ] the model dropdown offers %s" % ids)
PY
[[ $? -eq 0 ]] || fail=1

echo
echo "=== 7. a conversation, through the interface's own API ==="
REQ="$(MODEL="$MODEL" python3 -c '
import json, os
print(json.dumps({
    "model": os.environ["MODEL"],
    "messages": [{"role": "user", "content": "In one sentence, what is federated learning?"}],
    "max_tokens": 160,
    "temperature": 0,
}))')"
C0=$(date +%s.%N)
curl -k -sS --max-time 180 -o "$TMP/chat.json" \
    -H "Authorization: Bearer $UITOK" -H "Content-Type: application/json" \
    "$UI/api/chat/completions" -d "$REQ" >/dev/null 2>&1
C1=$(date +%s.%N)

python3 - "$C0" "$C1" "$TMP/chat.json" <<'PY'
import json, sys

t0, t1 = float(sys.argv[1]), float(sys.argv[2])
try:
    r = json.load(open(sys.argv[3]))
except Exception:
    print("  [FAIL] no JSON came back from the UI"); raise SystemExit(1)
if "error" in r or "detail" in r:
    print("  [FAIL] %s" % str(r.get("error") or r.get("detail"))[:300]); raise SystemExit(1)

msg = r["choices"][0]["message"]
text = (msg.get("content") or "").strip()
if not text:
    # A thinking model answers into `reasoning`; Open WebUI renders that as a
    # collapsible section, so it is a pass here, unlike for a plain API caller.
    text = (msg.get("reasoning") or "").strip()
    if text:
        print("  [ ok ] answered into `reasoning` — a thinking model (R-20)")
    else:
        print("  [FAIL] the reply is empty in both content and reasoning")
        raise SystemExit(1)

out = r.get("usage", {}).get("completion_tokens", 0)
elapsed = t1 - t0
print("  [ ok ] reply: %s" % (text[:150] + ("..." if len(text) > 150 else "")))
print("         %d tokens in %.1fs = %.1f tok/s" % (out, elapsed, out / elapsed if elapsed else 0))
PY
[[ $? -eq 0 ]] || fail=1

echo
echo "=== 7b. the reply streams rather than arriving in one block ==="
# The failure this catches is a proxy that buffers server-sent events. The page
# then shows nothing at all for the whole generation and then everything at
# once, which reads as a hang. curl -N leaves the stream unbuffered; what
# matters is whether the chunks are spread out in time.
#
# The prompt asks for a long answer on purpose. An earlier version asked the
# model to count to twenty, which it did in 0.7 seconds — 121 chunks, genuinely
# streamed, and far too short to distinguish from a buffered burst. A test whose
# verdict depends on how quickly the model finishes is not measuring the proxy.
SREQ="$(MODEL="$MODEL" python3 -c '
import json, os
print(json.dumps({
    "model": os.environ["MODEL"],
    "messages": [{"role": "user", "content":
        "Explain federated learning to a hospital IT administrator. "
        "Write about 200 words, in full sentences."}],
    "max_tokens": 400,
    "temperature": 0,
    "stream": True,
}))')"
curl -k -sSN --max-time 180 \
    -H "Authorization: Bearer $UITOK" -H "Content-Type: application/json" \
    "$UI/api/chat/completions" -d "$SREQ" 2>/dev/null \
| python3 -c '
import sys, time

first = last = None
chunks = 0
for line in iter(sys.stdin.readline, ""):
    if not line.startswith("data:"):
        continue
    now = time.time()
    if first is None:
        first = now
    last = now
    chunks += 1

if chunks == 0:
    print("  [FAIL] nothing arrived as server-sent events")
    raise SystemExit(1)
spread = (last - first) if first else 0.0
gap = (spread / (chunks - 1) * 1000) if chunks > 1 else 0.0
print("         %d SSE chunks over %.1fs, %.1f ms between them" % (chunks, spread, gap))

# Under 30 chunks the model answered too briefly for the timing to mean
# anything, so say that rather than returning a verdict the numbers do not
# support.
if chunks < 30:
    print("  [FAIL] only %d chunks — too short to judge. Either the model" % chunks)
    print("         stopped early or the stream was collapsed into a burst.")
    raise SystemExit(1)

# The test is the GAP between chunks, not how long the whole answer took. A
# wall-clock floor is really a test of how fast the model is: our catalogue
# spans 18 to 129 tok/s, so the same threshold is generous for one model and
# marginal for another. The gap separates the two cases by three orders of
# magnitude instead — a buffered response arrives from a single read, tens of
# microseconds apart, while a streamed one is paced by generation at several
# milliseconds a token.
if gap < 1.0:
    print("  [FAIL] %d chunks arrived %.3f ms apart — that is one read, not a" % (chunks, gap))
    print("         stream. The browser shows nothing and then everything.")
    print("         Check Traefik is not buffering this router.")
    raise SystemExit(1)
print("  [ ok ] the reply arrives token by token, not in one block")
'
[[ ${PIPESTATUS[1]:-0} -eq 0 ]] || fail=1

echo
if [[ $fail -eq 0 ]]; then
    echo "Stage L4: the chat interface works end to end, and it streams."
else
    echo "Stage L4 has FAILURES — see above."
fi
exit $fail
