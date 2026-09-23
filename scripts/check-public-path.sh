#!/usr/bin/env bash
# What a visitor actually gets, measured from outside the box.
#
#   bash scripts/check-public-path.sh                 # print the table
#   bash scripts/check-public-path.sh > /tmp/before   # baseline, then diff
#
# This is the gate for stage C1 (docs/certificate-plan.md): capture the table
# before touching the nginx proxy VM, capture it after, and require them
# identical. It is also the before/after for C3, where exactly the hostnames
# and the certificate issuer should change and nothing else.
#
# WHY THIS IS NOT JUST curl
# -------------------------
# /etc/hosts on caios_server maps the four control-plane names straight to
# 192.168.104.181, so a plain curl from this node talks to CADDY and never
# reaches the public proxy at all (gotcha 22). Both answer, and they are not
# the same path — so a measurement taken the obvious way reports on the wrong
# machine and looks entirely reasonable.
#
# --resolve defeats that, but ONLY if the name matches the URL exactly. curl
# accepts `--resolve dashboard.1.2.3.4:443:1.2.3.4` for a URL whose host is
# `dashboard.1.2.3.4.sslip.io`, prints "Added ... to DNS cache", never matches
# it, and falls through to /etc/hosts. It fails OPEN and says nothing. That is
# why the host string is built once here rather than typed at a prompt.
#
# The proof that we arrived is the Server header: the proxy is nginx/1.18.0
# (Ubuntu). `Caddy` or any other nginx means we never left this machine, and
# the run fails rather than reporting numbers from the wrong host.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

ENV_FILE="configs/env/caios.env"
[[ -f "$ENV_FILE" ]] || { echo "Missing $ENV_FILE"; exit 1; }
set -a; . "$ENV_FILE"; set +a
: "${CAIOS_PUBLIC_IP:?CAIOS_PUBLIC_IP is empty}"
: "${CAIOS_PUBLIC_DOMAIN:?CAIOS_PUBLIC_DOMAIN is empty}"
: "${CAIOS_DEPLOYMENTS_DOMAIN:?CAIOS_DEPLOYMENTS_DOMAIN is empty}"

IP="$CAIOS_PUBLIC_IP"
PROXY_SERVER="nginx/1.18.0 (Ubuntu)"
rc=0

# A deployment name that is well-formed but belongs to nothing, so the result
# does not depend on what happens to be deployed today. Traefik answers 404,
# which still proves the whole path: DNS, proxy, SNI, upstream, routing.
PROBE_DEPLOY="probe.pacs-${CAIOS_DEPLOYMENTS_DOMAIN}"
# A name the proxy has no server block for. Its own 502 is the one response it
# generates rather than relays, so it is the clearest evidence of arrival.
PROBE_UNKNOWN="no-such-service.${CAIOS_PUBLIC_DOMAIN}"

HOSTS=(
    "dashboard.${CAIOS_PUBLIC_DOMAIN}"
    "api.${CAIOS_PUBLIC_DOMAIN}"
    "auth.${CAIOS_PUBLIC_DOMAIN}"
    "vault.${CAIOS_PUBLIC_DOMAIN}"
    "$PROBE_DEPLOY"
    "$PROBE_UNKNOWN"
)

probe() {   # host port -> "code|server|hsts"
    local host="$1" port="$2" scheme=https
    [[ "$port" == 80 ]] && scheme=http
    local hdr
    hdr="$(curl -sk -o /dev/null -D- --max-time 15 \
           --resolve "${host}:${port}:${IP}" "${scheme}://${host}/" 2>/dev/null)" || true
    [[ -z "$hdr" ]] && { echo "UNREACHABLE||"; return; }
    printf '%s|%s|%s\n' \
        "$(sed -n '1s#^HTTP/[0-9.]* \([0-9]*\).*#\1#p' <<<"${hdr//$'\r'/}" | head -1)" \
        "$(grep -i '^server:' <<<"${hdr//$'\r'/}" | head -1 | cut -d' ' -f2- )" \
        "$(grep -qi '^strict-transport-security:' <<<"${hdr//$'\r'/}" && echo HSTS || echo -)"
}

echo "Public path as a visitor sees it"
echo "  proxy      ${IP}"
echo "  domain     ${CAIOS_PUBLIC_DOMAIN}"
echo "  scheme     ${CAIOS_SCHEME:-https}"
echo
printf '%-52s %5s %6s %-26s %s\n' HOST PORT CODE SERVER HSTS
for h in "${HOSTS[@]}"; do
    for port in 80 443; do
        IFS='|' read -r code server hsts <<<"$(probe "$h" "$port")"
        printf '%-52s %5s %6s %-26s %s\n' "$h" "$port" "${code:-?}" "${server:-?}" "$hsts"
        if [[ "$code" == "UNREACHABLE" || -z "$code" ]]; then
            echo "    !! no response — the proxy did not answer" >&2
            rc=1
        elif [[ "$server" != "$PROXY_SERVER" ]]; then
            echo "    !! answered by '${server}', not the proxy. This measurement is" >&2
            echo "       of the wrong machine — see the header of this script." >&2
            rc=1
        fi
    done
done

echo
echo "Certificate presented per hostname"
printf '%-52s %s\n' HOST 'SUBJECT / ISSUER'
for h in "${HOSTS[@]}"; do
    # -connect by literal address, so name resolution cannot intervene at all.
    cert="$(echo | openssl s_client -connect "${IP}:443" -servername "$h" 2>/dev/null \
            | openssl x509 -noout -subject -issuer 2>/dev/null)" || true
    if [[ -z "$cert" ]]; then
        printf '%-52s %s\n' "$h" "(no certificate)"
        continue
    fi
    printf '%-52s %s\n' "$h" "$(sed -n 's/^subject=.*CN *= *//p' <<<"$cert")"
    printf '%-52s   issued by %s\n' "" "$(sed -n 's/^issuer=.*CN *= *//p' <<<"$cert")"
done

echo
if [[ $rc -eq 0 ]]; then
    echo "Every response came from the proxy. Codes above are the baseline."
else
    echo "FAILED — at least one response did not come from the proxy." >&2
fi
exit $rc
