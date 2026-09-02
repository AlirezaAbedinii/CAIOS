#!/bin/sh
# Configure Vault so PAPI can store per-deployment secrets against our Keycloak.
#
# Runs as the `vault_init` compose service on every `up`, and again whenever
# Vault restarts. Idempotent by construction: every step is either conditional
# or a write that produces the same result twice.
#
# WHY THIS IS A SERVICE AND NOT A ONE-OFF SCRIPT
# ---------------------------------------------
# Vault runs in dev mode, which keeps everything in memory. Any restart — a
# compose recreate, a host reboot, an OOM kill — silently discards the auth
# backend, the policy and the role. Vault comes back up looking perfectly
# healthy and answers every login with "permission denied", which surfaces from
# PAPI as a bare HTTP 500 on any deployment, pointing nowhere near Vault.
#
# That already happened once mid-Stage-3 and cost a debugging cycle. Rather than
# rely on someone remembering to re-run a script, the configuration is reapplied
# automatically whenever the stack starts.
#
# Losing stored *secrets* on restart is still expected and fine for a demo — it
# just means redeploying anything that held one. Losing the *configuration* is
# what breaks the platform, and that is what this prevents.
set -eu

: "${VAULT_ADDR:?}"
: "${VAULT_TOKEN:?}"
: "${CAIOS_AUTH_HOST:?}"
: "${KEYCLOAK_REALM:?}"

# T5. The issuer Vault trusts must be the SAME STRING Keycloak mints, which is
# KC_HOSTNAME in compose/docker-compose.yml. Both derive from CAIOS_SCHEME; if
# they ever disagree, Vault answers every login "permission denied" and PAPI
# surfaces that as a bare HTTP 500 on any deployment that stores a secret —
# which is every federated-learning and LLM deployment.
SCHEME="${CAIOS_SCHEME:-https}"
ISSUER="${SCHEME}://${CAIOS_AUTH_HOST}/realms/${KEYCLOAK_REALM}"
CA_FILE="${CAIOS_CA_FILE:-/caios-ca.pem}"

echo "waiting for Vault at $VAULT_ADDR"
until vault status >/dev/null 2>&1; do sleep 2; done
echo "Vault is up"

# Also wait for Keycloak. Vault validates the OIDC discovery URL at the moment
# the config is written, so writing it before Keycloak (or the proxy in front of
# it) is serving produces "error checking oidc discovery URL" and this container
# restarts in a loop. Waiting here turns a flapping service into a short pause.
echo "waiting for $ISSUER"
i=0
# busybox wget (this image) has no --ca-certificate, so this probe skips
# verification. That is fine: it only answers "is Keycloak serving yet".
# The real TLS check happens below, where Vault validates the discovery
# URL against oidc_discovery_ca_pem.
until wget -q -O /dev/null --no-check-certificate \
        "$ISSUER/.well-known/openid-configuration" 2>/dev/null; do
    i=$((i + 1))
    if [ "$i" -gt 150 ]; then
        echo "Keycloak did not become reachable at $ISSUER after 5 minutes."
        echo "Check: docker compose logs keycloak caddy"
        exit 1
    fi
    sleep 2
done
echo "Keycloak is serving the realm"

# Every value below is dictated by upstream's hardcoded expectations in
# ai4papi/routers/v1/secrets.py:
#   VAULT_AUTH_PATH   "jwt-keycloak"   -> auth mount path
#   VAULT_MOUNT_POINT "/secrets/"      -> KV mount name
#   client.secrets.kv.v1               -> KV version 1, NOT v2
#   path users/<sub>/<vo>/...          -> policy templates off the `sub` claim

echo "==> KV store at secrets/ (version 1)"
# PAPI calls the v1 API explicitly; a v2 mount answers on a different path and
# every secret operation 404s.
vault secrets list -format=json | grep -q '"secrets/"' \
    || vault secrets enable -path=secrets -version=1 kv

echo "==> JWT auth at jwt-keycloak/"
vault auth list -format=json | grep -q '"jwt-keycloak/"' \
    || vault auth enable -path=jwt-keycloak jwt

echo "==> trusting $ISSUER"
# Vault fetches the realm's discovery document from that URL. Over HTTPS the
# certificate is signed by our own CA, which this image has no reason to trust,
# so the CA is handed over explicitly — without it the fetch fails with a TLS
# error that reads like a network problem.
#
# Over HTTP there is no certificate to verify, and passing oidc_discovery_ca_pem
# anyway is not merely redundant: Vault validates the two together and rejects
# a CA supplied for a non-TLS discovery URL, so vault_init would restart in a
# loop and every deployment needing a secret would 500.
if [ "$SCHEME" = "https" ]; then
    vault write auth/jwt-keycloak/config \
        oidc_discovery_url="$ISSUER" \
        oidc_discovery_ca_pem=@"$CA_FILE" \
        default_role="caios"
else
    vault write auth/jwt-keycloak/config \
        oidc_discovery_url="$ISSUER" \
        default_role="caios"
fi

echo "==> policy caios-user"
# Templated so each user reaches only their own subtree. The alias name is the
# JWT's `sub` claim (user_claim below), which is exactly what PAPI uses to build
# the path: users/<auth_info['id']>/<vo>/...
ACCESSOR="$(vault auth list -format=json \
    | sed -n 's/.*"jwt-keycloak\/": *{[^}]*"accessor": *"\([^"]*\)".*/\1/p')"
if [ -z "$ACCESSOR" ]; then
    # Fall back to a line-oriented read if the single-line sed above misses.
    ACCESSOR="$(vault auth list | awk '$1=="jwt-keycloak/"{print $3}')"
fi
[ -n "$ACCESSOR" ] || { echo "could not determine the jwt-keycloak accessor"; exit 1; }

vault policy write caios-user - <<EOF
path "secrets/users/{{identity.entity.aliases.${ACCESSOR}.name}}/*" {
  capabilities = ["create", "read", "update", "delete", "list"]
}
path "secrets/metadata/users/{{identity.entity.aliases.${ACCESSOR}.name}}/*" {
  capabilities = ["list", "read"]
}
EOF

echo "==> role caios"
# bound_audiences must include "account": PAPI decodes tokens with
# audience="account", so that is what Keycloak issues.
#
# The role name matters. Upstream passes an empty role, which Vault reads as a
# request for a role literally named "" rather than as "use default_role", and
# answers 403. Our patch makes the name configurable and compose sets it to
# "caios" — so this name and VAULT_ROLE in docker-compose.yml must agree.
vault write auth/jwt-keycloak/role/caios \
    role_type="jwt" \
    user_claim="sub" \
    bound_audiences="account" \
    token_policies="caios-user" \
    token_ttl="1h" \
    token_max_ttl="768h"

echo
echo "Vault configured:"
echo "  issuer $ISSUER"
echo "  kv     secrets/ (v1)"
echo "  auth   jwt-keycloak/  role caios"
