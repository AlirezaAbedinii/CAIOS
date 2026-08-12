#!/usr/bin/env bash
# Verify the identity layer end to end: Keycloak issues a token PAPI will
# accept, and Vault accepts that same token and isolates secrets per user.
#
#   bash scripts/check-identity.sh                 # default user: researcher
#   bash scripts/check-identity.sh site-a          # any demo user
#
# Read-only apart from writing and deleting one throwaway secret under the
# user's own path.
#
# This is the Stage 2 gate. Run it after any change to the realm, the Vault
# configuration, or the addresses in caios.env — all three have to agree on the
# issuer string character for character.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

ENV_FILE="configs/env/caios.env"
[[ -f "$ENV_FILE" ]] || { echo "Missing $ENV_FILE"; exit 1; }
set -a; source "$ENV_FILE"; set +a

USER_NAME="${1:-researcher}"
PW_VAR="CAIOS_PW_$(echo "$USER_NAME" | tr 'a-z-' 'A-Z_')"
PASSWORD="${!PW_VAR:-}"
[[ -n "$PASSWORD" ]] || { echo "No password for $USER_NAME ($PW_VAR unset in $ENV_FILE)"; exit 1; }

VAULT="${VAULT_ADDR:-http://127.0.0.1:8200}"
fail=0
ok()   { printf '  [ ok ] %s\n' "$1"; }
bad()  { printf '  [FAIL] %s\n' "$1"; fail=1; }

decode() { cut -d. -f2 | python3 -c '
import base64, json, sys
r = sys.stdin.read().strip()
json.dump(json.loads(base64.urlsafe_b64decode(r + "=" * (-len(r) % 4))), sys.stdout)
'; }

echo "=== 1. Keycloak issues a token ==="
TOKEN="$(bash scripts/get-token.sh "$USER_NAME" "$PASSWORD" 2>/dev/null)"
if [[ -z "$TOKEN" ]]; then
    bad "no token returned — is Keycloak up, and is the password right?"
    exit 1
fi
ok "token issued for $USER_NAME"

CLAIMS="$(printf '%s' "$TOKEN" | decode)"

# PAPI decodes with require=[sub, iss, name, email] and audience="account",
# then parses realm roles matching access:<vo>:<level>. A token missing any of
# these is rejected with a 401 that does not say which.
python3 - "$CLAIMS" <<'PY'
import json, sys
c = json.loads(sys.argv[1])
missing = [k for k in ("sub", "iss", "name", "email") if not c.get(k)]
aud = c.get("aud")
aud_ok = "account" in (aud if isinstance(aud, list) else [aud])
roles = [r for r in c.get("realm_access", {}).get("roles", []) if r.startswith("access:")]
for label, good, detail in [
    ("required claims (sub, iss, name, email)", not missing, "missing: %s" % missing),
    ("audience includes 'account'", aud_ok, "aud=%r" % (aud,)),
    ("carries an access:<vo>:<level> role", bool(roles), "roles=%r" % (roles,)),
]:
    print("  [ ok ] " + label if good else "  [FAIL] %s — %s" % (label, detail))
print("         issuer: %s" % c.get("iss"))
sys.exit(0 if (not missing and aud_ok and roles) else 1)
PY
[[ $? -eq 0 ]] || fail=1

SUB="$(python3 -c "import json,sys;print(json.loads(sys.argv[1])['sub'])" "$CLAIMS" 2>/dev/null)"

echo
echo "=== 2. Vault accepts the same token ==="
LOGIN="$(curl -sS --max-time 20 -X POST \
    --data "{\"jwt\":\"$TOKEN\",\"role\":\"caios\"}" \
    "$VAULT/v1/auth/jwt-keycloak/login" 2>/dev/null)"

VT="$(python3 -c "
import json,sys
d=json.loads(sys.argv[1])
print(d.get('auth',{}).get('client_token',''))" "$LOGIN" 2>/dev/null)"

if [[ -z "$VT" ]]; then
    bad "Vault rejected the token"
    echo "$LOGIN" | head -c 300 | sed 's/^/         /'
    echo
    echo "         A mention of issuer or audience means Keycloak and Vault"
    echo "         disagree about the realm URL. They must match exactly."
    exit 1
fi
ok "Vault issued a token"

echo
echo "=== 3. Secrets work at the paths PAPI actually uses ==="
# PAPI builds: users/<sub>/<vo>/deployments/<uuid>/federated/default
P="secrets/users/${SUB}/vo.caios.ca/deployments/_healthcheck/federated/default"

W=$(curl -sS --max-time 20 -o /dev/null -w '%{http_code}' -X POST \
    -H "X-Vault-Token: $VT" --data '{"token":"healthcheck"}' "$VAULT/v1/$P")
[[ "$W" =~ ^2 ]] && ok "wrote a secret (HTTP $W)" || bad "write failed (HTTP $W)"

R=$(curl -sS --max-time 20 -H "X-Vault-Token: $VT" "$VAULT/v1/$P" \
    | python3 -c "import json,sys;print(json.load(sys.stdin).get('data',{}).get('token',''))" 2>/dev/null)
[[ "$R" == "healthcheck" ]] && ok "read it back" || bad "read back '$R', expected 'healthcheck'"

# The policy is templated on the sub claim, so one user must not see another's.
OTHER="site-a"; [[ "$USER_NAME" == "site-a" ]] && OTHER="site-b"
OPW_VAR="CAIOS_PW_$(echo "$OTHER" | tr 'a-z-' 'A-Z_')"
if [[ -n "${!OPW_VAR:-}" ]]; then
    OT="$(bash scripts/get-token.sh "$OTHER" "${!OPW_VAR}" 2>/dev/null)"
    OVT="$(curl -sS --max-time 20 -X POST --data "{\"jwt\":\"$OT\",\"role\":\"caios\"}" \
        "$VAULT/v1/auth/jwt-keycloak/login" \
        | python3 -c "import json,sys;print(json.load(sys.stdin).get('auth',{}).get('client_token',''))" 2>/dev/null)"
    D=$(curl -sS --max-time 20 -o /dev/null -w '%{http_code}' \
        -H "X-Vault-Token: $OVT" "$VAULT/v1/$P")
    [[ "$D" == "403" ]] && ok "another user is denied (HTTP 403)" \
                        || bad "$OTHER got HTTP $D reading ${USER_NAME}'s secret — expected 403"
fi

curl -sS --max-time 20 -o /dev/null -X DELETE -H "X-Vault-Token: $VT" "$VAULT/v1/$P"

echo
if (( fail )); then
    echo "IDENTITY CHECK FAILED"
    exit 1
fi
echo "Identity layer OK — Keycloak and Vault agree, and PAPI's requirements are met."
