#!/usr/bin/env bash
# The registration lifecycle, end to end, against the running platform.
#
#   bash scripts/check-registration.sh
#
# Registers a throwaway account through Keycloak's REAL registration form,
# proves PAPI refuses it, approves it, proves PAPI accepts it, denies it, and
# deletes it. Nothing is left behind.
#
# WHY THE REAL FORM
#
# Creating the user through the admin API would test the approval service and
# nothing else. The form is the half a stranger actually touches, and it is the
# half that breaks silently: a realm setting that did not reach the live realm
# (the import runs only once), a required attribute nobody can satisfy, a
# missing PKCE parameter. This registers the way a person would.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

ENV_FILE="configs/env/caios.env"
[[ -f "$ENV_FILE" ]] || { echo "Missing $ENV_FILE — see configs/env/caios.env.template"; exit 1; }
set -a; source "$ENV_FILE"; set +a

SCHEME="${CAIOS_SCHEME:-https}"
API="${SCHEME}://${CAIOS_API_HOST}"
AUTH="${SCHEME}://${CAIOS_AUTH_HOST}"
REALM="${KEYCLOAK_REALM:-caios}"
VO="vo.caios.ca"

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

FAILED=0
ok()   { printf '  [ ok ] %s\n' "$1"; }
bad()  { printf '  [FAIL] %s\n' "$1"; FAILED=1; }
note() { printf '         %s\n' "$1"; }

# curl -k throughout: under CAIOS_SCHEME=https the platform serves its own CA,
# which this script has no reason to assume is installed. It is checking
# behaviour, not trust; scripts/check-dashboard.sh is what verifies the chain.
c() { curl -sk --max-time 60 "$@"; }

USERNAME="t6check$RANDOM$RANDOM"
PASSWORD="Check-Pass-$RANDOM$RANDOM"
EMAIL="${USERNAME}@example.invalid"

echo "=== 0. Prerequisites ==="

ADMIN_TOKEN="$(bash scripts/get-token.sh platform-admin "${CAIOS_PW_PLATFORM_ADMIN:-}" 2>/dev/null || true)"
if [[ -z "$ADMIN_TOKEN" ]]; then
    bad "no token for platform-admin — set CAIOS_PW_PLATFORM_ADMIN and run scripts/keycloak-bootstrap.sh"
    exit 1
fi
ok "platform-admin can sign in"

HEALTH="$(c "$API/registration/health" || true)"
if grep -q '"status": *"ok"' <<<"$HEALTH"; then
    ok "the approval service is serving"
else
    bad "the approval service did not answer at $API/registration/health"
    note "docker compose logs registration"
    exit 1
fi

# The issuer it validates against must be the one Keycloak mints, or every
# admin call 401s for a reason that reads like a permissions problem.
SVC_ISSUER="$(python3 -c "import json,sys; print(json.load(sys.stdin).get('issuer',''))" <<<"$HEALTH")"
if [[ "$SVC_ISSUER" == "${AUTH}/realms/${REALM}" ]]; then
    ok "it validates against ${SVC_ISSUER}"
else
    bad "issuer mismatch: service says '$SVC_ISSUER', platform is '${AUTH}/realms/${REALM}'"
fi

echo
echo "=== 1. Only an administrator may approve ==="

code() { c -o /dev/null -w '%{http_code}' "$@"; }

[[ "$(code "$API/registration/accounts")" == "403" ]] \
    && ok "no token is refused" || bad "an unauthenticated caller was not refused"

[[ "$(code "$API/registration/accounts" -H 'Authorization: Bearer not.a.real.token')" == "401" ]] \
    && ok "a forged token is refused" || bad "a forged token was not refused"

USER_TOKEN="$(bash scripts/get-token.sh researcher "${CAIOS_PW_RESEARCHER:-}" 2>/dev/null || true)"
if [[ -n "$USER_TOKEN" ]]; then
    [[ "$(code "$API/registration/accounts" -H "Authorization: Bearer $USER_TOKEN")" == "403" ]] \
        && ok "an ordinary user (ap-u) is refused" \
        || bad "an ordinary user could read the account list"
fi

[[ "$(code "$API/registration/accounts" -H "Authorization: Bearer $ADMIN_TOKEN")" == "200" ]] \
    && ok "the administrator (ap-d) is admitted" || bad "the administrator was refused"

echo
echo "=== 2. A stranger registers, through the form a stranger would use ==="

VERIFIER="$(openssl rand -hex 32)"
CHALLENGE="$(printf '%s' "$VERIFIER" | openssl dgst -sha256 -binary | openssl base64 | tr '+/' '-_' | tr -d '=')"
REG_URL="${AUTH}/realms/${REALM}/protocol/openid-connect/registrations"
REG_URL+="?client_id=caios-dashboard&response_type=code&scope=openid"
REG_URL+="&code_challenge=${CHALLENGE}&code_challenge_method=S256"
REG_URL+="&redirect_uri=${SCHEME}%3A%2F%2F${CAIOS_DASHBOARD_HOST}%2F"

c -c "$WORK/cookies" -o "$WORK/form.html" "$REG_URL"
if grep -q 'id="kc-register-form"' "$WORK/form.html"; then
    ok "the registration form is served"
else
    bad "no registration form at the registration endpoint"
    note "registrationAllowed may be false on the LIVE realm — the import runs"
    note "only once. Fix: bash scripts/keycloak-bootstrap.sh"
    exit 1
fi

ACTION="$(grep -oE 'action="[^"]+"' "$WORK/form.html" | head -1 \
    | sed 's/^action="//; s/"$//' \
    | python3 -c 'import sys,html; print(html.unescape(sys.stdin.read().strip()))')"

c -b "$WORK/cookies" -c "$WORK/cookies" -D "$WORK/reg.hdr" -o "$WORK/reg.html" \
    -d "username=$USERNAME" -d "email=$EMAIL" \
    -d "firstName=Check" -d "lastName=Account" \
    -d "password=$PASSWORD" -d "password-confirm=$PASSWORD" \
    "$ACTION" >/dev/null

if head -1 "$WORK/reg.hdr" | grep -q "302"; then
    ok "registered as $USERNAME"
else
    bad "registration was rejected"
    grep -oE '<span[^>]*kc-feedback-text[^>]*>[^<]+' "$WORK/reg.html" | head -2 | sed 's/^/         /'
    exit 1
fi

# From here on the account exists, so clean it up whatever happens.
USER_ID="$(c "$API/registration/accounts" -H "Authorization: Bearer $ADMIN_TOKEN" \
    | python3 -c "import json,sys; print(next((a['id'] for a in json.load(sys.stdin) if a['username']=='$USERNAME'), ''))")"
[[ -n "$USER_ID" ]] || { bad "the new account is not visible to the console"; exit 1; }

cleanup() {
    docker exec -i caios_keycloak /opt/keycloak/bin/kcadm.sh delete "users/$USER_ID" \
        -r "$REALM" >/dev/null 2>&1 || true
    rm -rf "$WORK"
}
trap cleanup EXIT

echo
echo "=== 3. Registered is not approved ==="

STATE="$(c "$API/registration/pending" -H "Authorization: Bearer $ADMIN_TOKEN" \
    | python3 -c "import json,sys; print(next((a['state'] for a in json.load(sys.stdin) if a['username']=='$USERNAME'), 'absent'))")"
[[ "$STATE" == "pending" ]] && ok "the console lists it as pending" \
    || bad "the console reports '$STATE', expected 'pending'"

NEW_TOKEN="$(bash scripts/get-token.sh "$USERNAME" "$PASSWORD" 2>/dev/null || true)"
[[ -n "$NEW_TOKEN" ]] && ok "Keycloak lets them sign in" \
    || bad "the new account cannot sign in at all"

DEPLOY='{"general":{"title":"registration-check","docker_tag":"u24.04","service":"jupyter","jupyter_password":"check-pass-1"},"hardware":{"cpu_num":1,"ram":4000,"disk":1000,"gpu_num":0}}'
CODE="$(code -X POST "$API/v1/deployments/tools?vo=${VO}&tool_name=ai4os-dev-env" \
    -H "Authorization: Bearer $NEW_TOKEN" -H 'Content-Type: application/json' -d "$DEPLOY")"
if [[ "$CODE" == "401" ]]; then
    ok "PAPI refuses them (401)"
elif [[ "$CODE" == "500" ]]; then
    bad "PAPI answered 500 — patch 0018 is not applied to the running image"
    note "A user with no access role must get an honest refusal, not a crash."
else
    bad "PAPI answered $CODE for an unapproved account, expected 401"
fi

echo
echo "=== 4. Approval is one role assignment ==="

RESULT="$(c -X POST "$API/registration/approve/$USER_ID" -H "Authorization: Bearer $ADMIN_TOKEN")"
LEVELS="$(python3 -c "import json,sys; print(','.join(json.load(sys.stdin).get('levels',[])))" <<<"$RESULT" 2>/dev/null || echo "?")"
[[ "$LEVELS" == "ap-u" ]] && ok "approved, holds ap-u" || bad "after approval the account holds '$LEVELS'"

[[ "$(code -X POST "$API/registration/approve/$USER_ID" -H "Authorization: Bearer $ADMIN_TOKEN")" == "200" ]] \
    && ok "approving twice is harmless" || bad "a second approval failed"

NEW_TOKEN="$(bash scripts/get-token.sh "$USERNAME" "$PASSWORD" 2>/dev/null || true)"
CREATED="$(c -X POST "$API/v1/deployments/tools?vo=${VO}&tool_name=ai4os-dev-env" \
    -H "Authorization: Bearer $NEW_TOKEN" -H 'Content-Type: application/json' -d "$DEPLOY")"
JOB="$(python3 -c "import json,sys; print(json.load(sys.stdin).get('job_ID',''))" <<<"$CREATED" 2>/dev/null || true)"
if [[ -n "$JOB" ]]; then
    ok "PAPI now accepts them — deployment $JOB"
    c -X DELETE "$API/v1/deployments/tools/${JOB}?vo=${VO}" -H "Authorization: Bearer $NEW_TOKEN" >/dev/null
    note "deleted again"
else
    bad "an approved account still could not deploy: $(head -c 160 <<<"$CREATED")"
fi

echo
echo "=== 5. Denial, and what it refuses to do ==="

ADMIN_ID="$(c "$API/registration/accounts" -H "Authorization: Bearer $ADMIN_TOKEN" \
    | python3 -c "import json,sys; print(next((a['id'] for a in json.load(sys.stdin) if a['username']=='platform-admin'), ''))")"
[[ "$(code -X POST "$API/registration/deny/$ADMIN_ID" -H "Authorization: Bearer $ADMIN_TOKEN")" == "400" ]] \
    && ok "you cannot deny your own account" || bad "self-denial was allowed"

RESULT="$(c -X POST "$API/registration/deny/$USER_ID" -H "Authorization: Bearer $ADMIN_TOKEN")"
DSTATE="$(python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('state'), d.get('enabled'), ','.join(d.get('levels',[])))" <<<"$RESULT" 2>/dev/null || echo "?")"
[[ "$DSTATE" == "denied False " ]] && ok "denied: disabled, and its access removed" \
    || bad "after denial the account reads '$DSTATE'"

[[ -z "$(bash scripts/get-token.sh "$USERNAME" "$PASSWORD" 2>/dev/null || true)" ]] \
    && ok "a denied account can no longer sign in" \
    || bad "a denied account can still sign in"

echo
if [[ "$FAILED" == "0" ]]; then
    echo "Registration lifecycle OK — the throwaway account has been deleted."
else
    echo "REGISTRATION CHECK FAILED"
fi
exit "$FAILED"
