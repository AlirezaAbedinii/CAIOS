#!/usr/bin/env bash
# Fetch an access token for a CAIOS demo user, for testing PAPI by hand.
#
#   TOKEN=$(bash scripts/get-token.sh researcher 'password')
#   curl -H "Authorization: Bearer $TOKEN" https://$CAIOS_API_HOST/v1/deployments/modules
#
# Uses the direct grant flow, which the dashboard client has enabled for exactly
# this reason. Browser logins use the authorization code flow instead.
#
# Prints the raw token on stdout so it composes; everything else goes to stderr.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

ENV_FILE="configs/env/caios.env"
[[ -f "$ENV_FILE" ]] || { echo "Missing $ENV_FILE" >&2; exit 1; }
set -a; source "$ENV_FILE"; set +a

USERNAME="${1:?usage: get-token.sh <username> <password>}"
PASSWORD="${2:?usage: get-token.sh <username> <password>}"
ISSUER="https://${CAIOS_AUTH_HOST}/realms/${KEYCLOAK_REALM}"

# --insecure while we are on self-signed certificates (D-12). Drop it once a
# real domain is in place.
RESPONSE="$(curl -sS --insecure \
    -X POST "${ISSUER}/protocol/openid-connect/token" \
    -d "client_id=caios-dashboard" \
    -d "username=${USERNAME}" \
    -d "password=${PASSWORD}" \
    -d "grant_type=password" \
    -d "scope=openid profile email")"

TOKEN="$(printf '%s' "$RESPONSE" | python3 -c '
import json, sys
d = json.load(sys.stdin)
if "access_token" not in d:
    sys.stderr.write("Keycloak returned no token:\n" + json.dumps(d, indent=2) + "\n")
    sys.exit(1)
print(d["access_token"])
')"

# Decode the payload to stderr so a caller capturing stdout still sees it.
printf '%s' "$TOKEN" | cut -d. -f2 | python3 -c '
import base64, json, sys
raw = sys.stdin.read()
payload = json.loads(base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)))
roles = payload.get("realm_access", {}).get("roles", [])
access = [r for r in roles if r.startswith("access:")]
out = sys.stderr
print("  sub  :", payload.get("sub"), file=out)
print("  iss  :", payload.get("iss"), file=out)
print("  name :", payload.get("name"), file=out)
print("  email:", payload.get("email"), file=out)
print("  aud  :", payload.get("aud"), file=out)
print("  roles:", access or "NONE - PAPI will reject this user", file=out)
missing = [k for k in ("sub", "iss", "name", "email") if not payload.get(k)]
if missing:
    print("  MISSING REQUIRED CLAIMS:", missing, file=out)
    print("  PAPI requires all four. Set the user first name, last name and email.", file=out)
' || true

printf '%s\n' "$TOKEN"
