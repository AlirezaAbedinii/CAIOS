#!/usr/bin/env bash
# Render the proxy VM's CAIOS nginx config from configs/env/caios.env.
#
#   bash scripts/render-nginx-config.sh
#   bash scripts/render-nginx-config.sh --diff    # against the saved live copy
#
# Output: build/jumpserver/caios.conf   (gitignored; the templates are committed)
#
# Stage C1 of docs/certificate-plan.md. The proxy VM was the only machine in
# the architecture configured by hand. This does not change that on its own —
# it makes the config a generated artifact of the same variable everything
# else derives from, so that moving to a real domain cannot leave this file
# behind. Copying it up is a documented manual step; see docs/nginx-proxy.md.
#
# ADDITIVE, NOT A CUTOVER
# -----------------------
# CAIOS_LEGACY_DOMAIN, when set, gets its own pair of server blocks alongside
# the primary one. Both domains then answer at the same time, on their own
# certificates, and rolling back is swapping the two variables rather than
# reissuing anything. Nothing is deleted at any point, which is the whole
# reason this is safe to do a week before a recording.
#
# WHY envsubst IS GIVEN AN EXPLICIT LIST
# --------------------------------------
# Bare `envsubst` replaces every $NAME it sees. An nginx config is full of
# them — $host, $remote_addr, $proxy_add_x_forwarded_for, $connection_upgrade
# — and they are nginx's, not the shell's. Unlisted, they would all render as
# empty strings and the result would be a config that fails to parse if you
# are lucky and silently proxies to nothing if you are not.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

ENV_FILE="configs/env/caios.env"
[[ -f "$ENV_FILE" ]] || { echo "Missing $ENV_FILE"; exit 1; }
set -a; . "$ENV_FILE"; set +a
: "${CAIOS_PUBLIC_IP:?CAIOS_PUBLIC_IP is empty}"
: "${CAIOS_CTRL_IP:?CAIOS_CTRL_IP is empty}"
: "${CAIOS_EDGE_IP:?CAIOS_EDGE_IP is empty}"
: "${CAIOS_PUBLIC_DOMAIN:?CAIOS_PUBLIC_DOMAIN is empty}"

OUT="build/jumpserver"
mkdir -p "$OUT"
TARGET="$OUT/caios.conf"

HEAD_VARS='${CAIOS_PUBLIC_IP} ${CAIOS_CTRL_IP} ${CAIOS_EDGE_IP}'
SITE_VARS='${CAIOS_NGINX_DOMAIN} ${CAIOS_NGINX_DEPLOY_RE} ${CAIOS_NGINX_DEFAULT} ${CAIOS_NGINX_CERT} ${CAIOS_NGINX_KEY} ${CAIOS_NGINX_DEPLOY_CERT} ${CAIOS_NGINX_DEPLOY_KEY}'

# A server_name regex is matched against the whole Host, so every dot has to
# be escaped or "." matches any character and a lookalike domain would route
# into this cluster.
escape_re() { printf '%s' "$1" | sed 's/\./\\./g'; }

emit_site() {   # domain  tls_mode  default_flag
    local domain="$1" mode="$2" default="$3"
    local deploy_domain="deployments.${domain}"

    case "$mode" in
        caios-ca)
            # Issued by scripts/make-control-plane-cert.sh and
            # make-traefik-certs.sh, then copied to the proxy by hand.
            CAIOS_NGINX_CERT=/etc/nginx/certs/caios-public.pem
            CAIOS_NGINX_KEY=/etc/nginx/certs/caios-public.key
            CAIOS_NGINX_DEPLOY_CERT=/etc/nginx/certs/caios-deployments.pem
            CAIOS_NGINX_DEPLOY_KEY=/etc/nginx/certs/caios-deployments.key
            ;;
        acme)
            # One certificate covers both tiers: certbot is asked for
            # <domain>, *.<domain> and *.pacs-deployments.<domain> together.
            CAIOS_NGINX_CERT="/etc/letsencrypt/live/${domain}/fullchain.pem"
            CAIOS_NGINX_KEY="/etc/letsencrypt/live/${domain}/privkey.pem"
            CAIOS_NGINX_DEPLOY_CERT="$CAIOS_NGINX_CERT"
            CAIOS_NGINX_DEPLOY_KEY="$CAIOS_NGINX_KEY"
            ;;
        *) echo "unknown tls mode '$mode' for $domain"; exit 1 ;;
    esac

    CAIOS_NGINX_DOMAIN="$domain"
    CAIOS_NGINX_DEPLOY_RE="$(escape_re "$deploy_domain")"
    CAIOS_NGINX_DEFAULT="$default"
    export CAIOS_NGINX_DOMAIN CAIOS_NGINX_DEPLOY_RE CAIOS_NGINX_DEFAULT \
           CAIOS_NGINX_CERT CAIOS_NGINX_KEY \
           CAIOS_NGINX_DEPLOY_CERT CAIOS_NGINX_DEPLOY_KEY

    envsubst "$SITE_VARS" < configs/nginx/caios.conf.site.template
}

# An sslip.io name can only ever carry a CAIOS CA certificate: Let's Encrypt
# issues wildcards over DNS-01 alone, and nobody controls that zone.
tls_for() { [[ "$1" == *.sslip.io ]] && echo caios-ca || echo "${CAIOS_TLS_MODE:-acme}"; }

{
    envsubst "$HEAD_VARS" < configs/nginx/caios.conf.head.template
    # The primary domain owns default_server: it decides what answers a
    # request whose Host matches nothing, and that should be whatever the
    # platform currently calls itself.
    emit_site "$CAIOS_PUBLIC_DOMAIN" "$(tls_for "$CAIOS_PUBLIC_DOMAIN")" " default_server"
    if [[ -n "${CAIOS_LEGACY_DOMAIN:-}" ]]; then
        emit_site "$CAIOS_LEGACY_DOMAIN" "$(tls_for "$CAIOS_LEGACY_DOMAIN")" ""
    fi
} > "$TARGET"

echo "Wrote $TARGET"
echo "  primary  ${CAIOS_PUBLIC_DOMAIN}  ($(tls_for "$CAIOS_PUBLIC_DOMAIN"))"
[[ -n "${CAIOS_LEGACY_DOMAIN:-}" ]] &&
    echo "  legacy   ${CAIOS_LEGACY_DOMAIN}  ($(tls_for "$CAIOS_LEGACY_DOMAIN"))"

if [[ "${1:-}" == "--diff" ]]; then
    LIVE="$(ls -1 ops/jumpserver/caios.conf.live-* 2>/dev/null | tail -1)"
    [[ -n "$LIVE" ]] || { echo "No saved live copy under ops/jumpserver/"; exit 1; }
    echo
    echo "=== vs $LIVE (directives only; comments differ by design) ==="
    strip() { grep -vE '^\s*#|^\s*$' "$1"; }
    if diff -u <(strip "$LIVE") <(strip "$TARGET"); then
        echo "identical — the template reproduces what is running"
    else
        echo
        echo "DIFFERENT. Every line above is a change this render would make."
        exit 1
    fi
fi
