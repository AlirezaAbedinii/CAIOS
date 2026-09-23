#!/usr/bin/env bash
# Capture every configuration artifact that can be derived offline, so a
# refactor can be PROVED inert rather than believed to be.
#
#   bash scripts/snapshot-config.sh <dir>
#
# Written for Stage C0, where the domain became one variable. The gate for
# that stage is "snapshot, refactor, snapshot, diff, empty" — and that gate is
# only worth having if the snapshot covers more than the two files
# render-configs.sh happens to write.
#
# It is reused at C3, where the diff must show the domain change and NOTHING
# else. That is the only cheap way to catch a missed hostname before it
# becomes a 401 on everything with no log line naming the cause.
#
# Everything here is read-only and offline: no Docker daemon, no sudo, no
# network, no certificate issued. `docker compose config` is client-side
# parsing only.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

OUT="${1:?usage: snapshot-config.sh <output-dir>}"
mkdir -p "$OUT"

ENV_FILE="configs/env/caios.env"
[[ -f "$ENV_FILE" ]] || { echo "Missing $ENV_FILE"; exit 1; }
set -a; . "$ENV_FILE"; set +a

# 1. What render-configs.sh writes. Rendered into the repo as usual, then
#    copied, so the snapshot reflects the real path the platform reads.
bash scripts/render-configs.sh >/dev/null
cp compose/generated/caddy/Caddyfile            "$OUT/Caddyfile"
cp compose/generated/keycloak/caios-realm.json  "$OUT/caios-realm.json"

# 2. Every environment variable the control plane actually receives, fully
#    resolved. This is the big one: the four hostnames reach PAPI, Keycloak,
#    Vault, the dashboard and the registration service through here, and a
#    missed substitution shows up as a literal ${...} rather than as an error.
( cd compose && docker compose --env-file ../configs/env/caios.env config ) \
    > "$OUT/compose-resolved.yml"

# 3. PAPI's main.yaml. Not rendered by render-configs.sh — the image runs
#    envsubst on it at start (upstream behaviour we keep), so this reproduces
#    what the container will build.
envsubst < configs/papi/main.yaml > "$OUT/papi-main.yaml"

# 4. Values that exist only as expressions inside scripts. Recomputed here
#    rather than executed, because the scripts that own them issue
#    certificates or talk to Keycloak as a side effect.
{
    echo "# Derived hostnames and the values built from them."
    echo "# Recomputed from $ENV_FILE; see the script that owns each one."
    echo
    echo "dashboard_host           = ${CAIOS_DASHBOARD_HOST}"
    echo "api_host                 = ${CAIOS_API_HOST}"
    echo "auth_host                = ${CAIOS_AUTH_HOST}"
    echo "vault_host               = ${CAIOS_VAULT_HOST}"
    echo "public_domain            = ${CAIOS_PUBLIC_DOMAIN}"
    echo "deployments_domain       = ${CAIOS_DEPLOYMENTS_DOMAIN}"
    echo
    echo "# make-control-plane-cert.sh — the SAN list Caddy's certificate carries."
    echo "control_plane_sans       = DNS:${CAIOS_DASHBOARD_HOST},DNS:${CAIOS_API_HOST},DNS:${CAIOS_AUTH_HOST},DNS:${CAIOS_VAULT_HOST},DNS:localhost,IP:${CAIOS_CTRL_IP},IP:127.0.0.1"
    echo
    echo "# make-traefik-certs.sh — the deployment wildcard."
    echo "traefik_wildcard         = *.pacs-${CAIOS_DEPLOYMENTS_DOMAIN}"
    echo
    echo "# run-cluster-tests.sh — what ai4-nomad_tests verifies over HTTPS."
    echo "ai4_base_domain          = ${CAIOS_DEPLOYMENTS_DOMAIN}"
    echo
    echo "# build-fl-bundles.sh — where a site workspace fetches its bundle."
    echo "fl_base_url              = ${CAIOS_SCHEME}://${CAIOS_DASHBOARD_HOST}/fl"
    echo "fl_server_hint           = fedserver-<uuid>.${CAIOS_DEPLOYMENTS_DOMAIN:-<domain>}:443"
    echo
    echo "# keycloak-bootstrap.sh — LIVE realm settings, applied after import."
    echo "redirect_uris            = https://${CAIOS_DASHBOARD_HOST}/*, http://${CAIOS_DASHBOARD_HOST}/*, http://localhost:8080/*"
    echo "web_origins              = https://${CAIOS_DASHBOARD_HOST}, http://${CAIOS_DASHBOARD_HOST}, http://localhost:8080"
    echo
    echo "# install-oscar.sh — the issuer OSCAR validates every token against."
    echo "oscar_oidc_issuer        = ${CAIOS_OIDC_ISSUER:-${CAIOS_SCHEME:-https}://auth.${CAIOS_PUBLIC_DOMAIN}/realms/${KEYCLOAK_REALM:-caios}}"
    echo "oscar_endpoint           = ${CAIOS_OSCAR_ENDPOINT:-}"
} > "$OUT/derived.txt"

echo "Snapshot written to $OUT"
ls -1 "$OUT" | sed 's/^/  /'
