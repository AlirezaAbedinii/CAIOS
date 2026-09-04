#!/usr/bin/env bash
# Create the CAIOS demo users and give them the role PAPI actually looks for.
#
#   bash scripts/keycloak-bootstrap.sh
#
# Run once, after `docker compose up keycloak`. Idempotent — re-running updates
# passwords rather than failing.
#
# The realm, its roles and the dashboard client come from the realm import
# (configs/keycloak/caios-realm.json.template). Only users are created here,
# because their passwords must not be committed.
#
# Passwords are read from configs/env/caios.env, or generated and printed if
# absent. Write them down: Keycloak will not show them again.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

ENV_FILE="configs/env/caios.env"
[[ -f "$ENV_FILE" ]] || { echo "Missing $ENV_FILE — see configs/env/caios.env.template"; exit 1; }
set -a; source "$ENV_FILE"; set +a

REALM="${KEYCLOAK_REALM:-caios}"
VO="vo.caios.ca"
ROLE="access:${VO}:ap-u"

kc() { docker exec -i caios_keycloak /opt/keycloak/bin/kcadm.sh "$@"; }

echo "==> authenticating to Keycloak"
kc config credentials \
    --server http://localhost:8080 \
    --realm master \
    --user "${KEYCLOAK_ADMIN}" \
    --password "${KEYCLOAK_ADMIN_PASSWORD}"

# ---------------------------------------------------------------------------
# Realm and client settings that the import cannot deliver.
#
# Keycloak imports a realm ONLY on first start. Once caios exists, editing
# configs/keycloak/caios-realm.json.template and re-rendering changes nothing on
# the running system — the importer skips it silently and everything keeps
# working with the old values. That is fine for most fields and fatal for these
# two, so they are applied here through the admin API, idempotently.
#
#   sslRequired    Keycloak treats a request from a public address as external.
#                  Left at "external" on an http platform it refuses the login
#                  page with "HTTPS required", which reaches the user as a
#                  broken login on a dashboard that otherwise renders perfectly.
#
#   redirectUris   The dashboard sends window.location.origin as its redirect
#   webOrigins     URI, so the scheme the visitor arrived on is the one Keycloak
#                  is asked to return to. Both are registered, so neither can
#                  fail with "Invalid parameter: redirect_uri".
#
# Derived from CAIOS_SCHEME. Re-run this script after flipping it.
# ---------------------------------------------------------------------------
if [[ "${CAIOS_SCHEME:-https}" == "https" ]]; then
    SSL_REQUIRED=external
else
    SSL_REQUIRED=none
fi

echo "==> realm ${REALM}: sslRequired=${SSL_REQUIRED} (CAIOS_SCHEME=${CAIOS_SCHEME:-https})"
kc update "realms/${REALM}" -s "sslRequired=${SSL_REQUIRED}"

CLIENT_UUID="$(kc get clients -r "$REALM" -q "clientId=caios-dashboard" \
    --fields id --format csv --noquotes 2>/dev/null | tail -n1 || true)"
if [[ -z "$CLIENT_UUID" ]]; then
    echo "  caios-dashboard client not found in realm ${REALM}. Import it first."
    exit 1
fi

DASH_HTTPS="https://${CAIOS_DASHBOARD_HOST}"
DASH_HTTP="http://${CAIOS_DASHBOARD_HOST}"
echo "==> client caios-dashboard: redirect URIs and web origins for both schemes"
kc update "clients/${CLIENT_UUID}" -r "$REALM" \
    -s "redirectUris=[\"${DASH_HTTPS}/*\",\"${DASH_HTTP}/*\",\"http://localhost:8080/*\"]" \
    -s "webOrigins=[\"${DASH_HTTPS}\",\"${DASH_HTTP}\",\"http://localhost:8080\"]" \
    -s "attributes.\"post.logout.redirect.uris\"=${DASH_HTTPS}/*##${DASH_HTTP}/*##http://localhost:8080/*"

echo

# ---------------------------------------------------------------------------
# T6 — self-registration, and the service account that approves it.
#
# "Pending" is not a state we store anywhere. It is simply a realm user who
# holds no access:<vo>:<level> role: Keycloak lets them log in, PAPI refuses
# every request, and the dashboard shows them a waiting message. Approval is
# one role assignment and denial is one disable. No database, nothing to keep
# in step with Keycloak, and nothing to migrate.
# ---------------------------------------------------------------------------

echo "==> realm ${REALM}: self-registration on"
# What this opens: anyone who can reach Keycloak can CREATE an account. What it
# does not open: any access at all. A new account has no role, so PAPI answers
# 401 on everything until somebody with ap-d approves it. The exposure is
# unwanted rows in the user list, not unwanted use of the cluster.
kc update "realms/${REALM}" \
    -s "registrationAllowed=true" \
    -s "registrationEmailAsUsername=false" \
    -s "loginWithEmailAllowed=true" \
    -s "verifyEmail=false"
# verifyEmail stays false deliberately: there is no SMTP server on this
# platform, so requiring verification would leave every registration stuck at a
# mail that can never arrive — a registration form that silently never works.
# The approval step is the human check that verification would otherwise be.

echo "==> client caios-registration (service account for approvals)"
: "${KEYCLOAK_REGISTRATION_SECRET:?set it in configs/env/caios.env — see the template}"
REG_UUID="$(kc get clients -r "$REALM" -q "clientId=caios-registration" \
    --fields id --format csv --noquotes 2>/dev/null | tail -n1 || true)"
if [[ -z "$REG_UUID" ]]; then
    kc create clients -r "$REALM" \
        -s "clientId=caios-registration" \
        -s "enabled=true" \
        -s "publicClient=false" \
        -s "standardFlowEnabled=false" \
        -s "directAccessGrantsEnabled=false" \
        -s "serviceAccountsEnabled=true" \
        -s "secret=${KEYCLOAK_REGISTRATION_SECRET}" >/dev/null
    REG_UUID="$(kc get clients -r "$REALM" -q "clientId=caios-registration" \
        --fields id --format csv --noquotes | tail -n1)"
    echo "     created"
else
    # Re-runnable: the secret in caios.env is the source of truth, so push it
    # again rather than reading Keycloak's. A rotated secret is then one edit
    # and one re-run.
    kc update "clients/${REG_UUID}" -r "$REALM" \
        -s "serviceAccountsEnabled=true" \
        -s "secret=${KEYCLOAK_REGISTRATION_SECRET}" >/dev/null
    echo "     exists (secret re-applied)"
fi

# The service account needs to read the user list and assign one realm role.
# view-users and manage-users are the narrowest pair that allows both; NOT
# realm-admin, which would let this service rewrite the realm login depends on.
echo "==> granting the service account view-users and manage-users"
SA_USER="service-account-caios-registration"
for r in view-users manage-users; do
    kc add-roles -r "$REALM" --uusername "$SA_USER" \
        --cclientid realm-management --rolename "$r" >/dev/null 2>&1 || true
done

echo

# username : first : last : email : access level
#
# The level is the last field of the realm role PAPI parses. ap-u is the
# minimum that can deploy; ap-d outranks it and is what the approval service
# requires, so platform-admin can both approve and deploy.
USERS=(
  "researcher:Dana:Okafor:researcher@caios.local:ap-u"
  "site-a:Site:A:site-a@caios.local:ap-u"
  "site-b:Site:B:site-b@caios.local:ap-u"
  "site-c:Site:C:site-c@caios.local:ap-u"
  "platform-admin:Platform:Administrator:admin@caios.local:ap-d"
)

echo
for entry in "${USERS[@]}"; do
    IFS=: read -r username first last email level <<<"$entry"

    # Passwords may be pinned per user in caios.env, e.g. CAIOS_PW_RESEARCHER.
    var="CAIOS_PW_$(echo "$username" | tr 'a-z-' 'A-Z_')"
    password="${!var:-}"
    if [[ -z "$password" ]]; then
        password="$(openssl rand -base64 15)"
        generated=" (generated)"
    else
        generated=""
    fi

    uid="$(kc get users -r "$REALM" -q "username=$username" --fields id --format csv --noquotes 2>/dev/null | tail -n1 || true)"

    if [[ -z "$uid" ]]; then
        # emailVerified matters: PAPI requires an `email` claim on every token,
        # and an unverified address can be withheld depending on realm settings.
        kc create users -r "$REALM" \
            -s "username=$username" \
            -s "firstName=$first" \
            -s "lastName=$last" \
            -s "email=$email" \
            -s "emailVerified=true" \
            -s "enabled=true" >/dev/null
        uid="$(kc get users -r "$REALM" -q "username=$username" --fields id --format csv --noquotes | tail -n1)"
        action="created"
    else
        action="exists "
    fi

    kc set-password -r "$REALM" --userid "$uid" --new-password "$password" >/dev/null

    # The role name IS the interface. PAPI parses realm roles with the regex
    # access:<vo>:<level> and ignores everything else, so a role called
    # "user" or a Keycloak group conveys nothing to it. ap-u is the minimum
    # level that can deploy.
    kc add-roles -r "$REALM" --uusername "$username" \
        --rolename "access:${VO}:${level}" >/dev/null 2>&1 || true

    printf '  %s  %-15s  %-6s  %s%s\n' "$action" "$username" "$level" "$password" "$generated"
done

cat <<EOF

Every account holds access:${VO}:<level> as listed above.

Verify a token carries it:
  bash scripts/get-token.sh researcher '<password>' | cut -d. -f2 | base64 -d 2>/dev/null | python3 -m json.tool

Look for realm_access.roles containing "${ROLE}", plus sub, iss, name, email
and an aud of "account". PAPI rejects a token missing any of those.
EOF
