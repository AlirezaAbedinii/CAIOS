#!/usr/bin/env bash
# Configure Vault so PAPI can store per-deployment secrets against our Keycloak.
#
#   bash scripts/vault-bootstrap.sh
#
# Run once, after `docker compose up vault keycloak`. Idempotent.
#
# Why this exists: deploying the federated learning server makes PAPI call
# create_secret() and create_vault_token() before it ever contacts Nomad. If
# Vault is missing, unmounted, or does not trust our realm, the headline demo
# fails at PAPI with an error that mentions neither Vault nor Keycloak.
#
# Every value below is dictated by upstream's hardcoded expectations in
# ai4papi/routers/v1/secrets.py:
#   VAULT_AUTH_PATH  = "jwt-keycloak"   -> auth mount path
#   VAULT_MOUNT_POINT= "/secrets/"      -> KV mount name
#   VAULT_ROLE       = ""               -> so the JWT backend needs a default_role
#   client.secrets.kv.v1                -> KV version 1, NOT v2
#   path users/<sub>/<vo>/...           -> policy templating keys off `sub`
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

ENV_FILE="configs/env/caios.env"
[[ -f "$ENV_FILE" ]] || { echo "Missing $ENV_FILE — see configs/env/caios.env.template"; exit 1; }
set -a; source "$ENV_FILE"; set +a

export VAULT_ADDR="${VAULT_ADDR:-http://127.0.0.1:8200}"
export VAULT_TOKEN="${VAULT_ROOT_TOKEN:?VAULT_ROOT_TOKEN is empty in $ENV_FILE}"

# T5. The scheme the platform serves on, from configs/env/caios.env.
# Defaults to https so this script behaves as it always did against an
# env file written before the switch existed.
SCHEME="${CAIOS_SCHEME:-https}"
ISSUER="${SCHEME}://${CAIOS_AUTH_HOST}/realms/${KEYCLOAK_REALM}"

vault() { docker exec -e VAULT_ADDR -e VAULT_TOKEN caios_vault vault "$@"; }

echo "==> KV store at secrets/ (version 1)"
# PAPI calls client.secrets.kv.v1 explicitly. A v2 mount answers on a different
# API path and every secret operation 404s.
vault secrets list -format=json | grep -q '"secrets/"' \
    || vault secrets enable -path=secrets -version=1 kv

echo "==> JWT auth at jwt-keycloak/"
vault auth list -format=json | grep -q '"jwt-keycloak/"' \
    || vault auth enable -path=jwt-keycloak jwt

echo "==> trusting $ISSUER"
# Vault fetches the realm's OIDC discovery document over HTTPS, and that
# certificate is signed by our own CA — which the Vault container has no reason
# to trust. Without oidc_discovery_ca_pem it fails with a TLS verification error
# that reads like a network problem. The PEM is passed inline, so nothing has to
# be mounted into the container.
#
# Over HTTP there is no certificate to verify, and passing the CA anyway is not
# merely redundant: Vault validates the two together and rejects a CA supplied
# for a non-TLS discovery URL. Same conditional as compose/vault/bootstrap.sh,
# which is what runs unattended.
if [[ "$SCHEME" == "https" ]]; then
    CA_PEM="$(cat "${CAIOS_CA_CRT:-$HOME/caios-ca.pem}")"
    docker exec -i -e VAULT_ADDR -e VAULT_TOKEN caios_vault \
        vault write auth/jwt-keycloak/config \
            oidc_discovery_url="$ISSUER" \
            oidc_discovery_ca_pem="$CA_PEM" \
            default_role="caios"
else
    docker exec -i -e VAULT_ADDR -e VAULT_TOKEN caios_vault \
        vault write auth/jwt-keycloak/config \
            oidc_discovery_url="$ISSUER" \
            default_role="caios"
fi

echo "==> policy caios-user"
# Templated so each user can only reach their own subtree. The alias name is
# the JWT's `sub` claim (user_claim below), which is exactly what PAPI uses to
# build the path: users/<auth_info['id']>/<vo>/...
ACCESSOR="$(vault auth list -format=json \
    | python3 -c 'import json,sys; print(json.load(sys.stdin)["jwt-keycloak/"]["accessor"])')"

docker exec -i -e VAULT_ADDR -e VAULT_TOKEN caios_vault \
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
# audience="account" (ai4papi/auth.py:42), so that is what Keycloak issues.
# token_ttl is generous because the federated server holds its token for the
# life of the deployment.
vault write auth/jwt-keycloak/role/caios \
    role_type="jwt" \
    user_claim="sub" \
    bound_audiences="account" \
    token_policies="caios-user" \
    token_ttl="1h" \
    token_max_ttl="8760h"

cat <<EOF

Vault configured.
  issuer   $ISSUER
  kv       secrets/ (v1)
  auth     jwt-keycloak/
  role     caios (default)

Verify with a real user token:
  TOKEN=\$(bash scripts/get-token.sh <username> <password>)
  curl -s --request POST --data "{\"jwt\":\"\$TOKEN\",\"role\":\"caios\"}" \\
      \$VAULT_ADDR/v1/auth/jwt-keycloak/login | head -c 400

A 400 mentioning audience or issuer means Keycloak and Vault disagree about
the realm URL — they must match character for character, https included.
EOF
