#!/usr/bin/env bash
# Verify the dashboard is serving, correctly branded, and wired to the right
# API and login server.
#
#   bash scripts/check-dashboard.sh
#
# Read-only.
#
# What this cannot check is whether the page *looks* right — that needs a
# browser. It checks everything a browser would depend on, so that when
# something is wrong you know whether to look at the build, the runtime
# configuration, or the browser itself.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

ENV_FILE="configs/env/caios.env"
[[ -f "$ENV_FILE" ]] || { echo "Missing $ENV_FILE"; exit 1; }
set -a; source "$ENV_FILE"; set +a

DASH="https://${CAIOS_DASHBOARD_HOST}"
fail=0
ok()  { printf '  [ ok ] %s\n' "$1"; }
bad() { printf '  [FAIL] %s\n' "$1"; fail=1; }

echo "=== 1. The page is served ==="
CODE=$(curl -sS --max-time 30 -o /tmp/caios-dash.html -w '%{http_code}' "$DASH/" 2>/dev/null)
[[ "$CODE" == "200" ]] && ok "GET / returns 200" || { bad "GET / returns $CODE"; exit 1; }

TLS=$(curl -sS --max-time 30 -o /dev/null -w '%{ssl_verify_result}' "$DASH/" 2>/dev/null)
[[ "$TLS" == "0" ]] && ok "certificate verifies against our CA" \
                    || bad "certificate did not verify (code $TLS)"

grep -qi "<title>CAIOS</title>" /tmp/caios-dash.html \
    && ok "page title is CAIOS" \
    || bad "page title is $(grep -oi '<title>[^<]*</title>' /tmp/caios-dash.html || echo 'missing')"

echo
echo "=== 2. Runtime configuration ==="
# config.json is written at container start from the environment, not baked in,
# so this is where a wrong API address or realm shows up.
curl -sS --max-time 30 -o /tmp/caios-cfg.json "$DASH/assets/config/config.json" 2>/dev/null
python3 - "$CAIOS_API_HOST" "$CAIOS_AUTH_HOST" "$KEYCLOAK_REALM" <<'PY'
import json, sys
api_host, auth_host, realm = sys.argv[1], sys.argv[2], sys.argv[3]
try:
    c = json.load(open("/tmp/caios-cfg.json"))
except Exception as e:
    print("  [FAIL] config.json is not valid JSON: %s" % e); sys.exit(1)

checks = [
    ("apiURL points at our API",  c.get("apiURL") == "https://" + api_host, c.get("apiURL")),
    ("issuer points at our realm",
     c.get("issuer") == "https://%s/realms/%s" % (auth_host, realm), c.get("issuer")),
    ("clientId is caios-dashboard", c.get("clientId") == "caios-dashboard", c.get("clientId")),
    ("branded as CAIOS", c.get("projectName") == "CAIOS", c.get("projectName")),
]
bad = 0
for label, good, got in checks:
    if good:
        print("  [ ok ] %s" % label)
    else:
        print("  [FAIL] %s — got %r" % (label, got)); bad = 1

# The analytics beacon in upstream's base config reports traffic to a
# third-party tracker. Our tenant blanks it; verify it stayed blank.
src = (c.get("analytics") or {}).get("src") or ""
if src:
    print("  [FAIL] analytics beacon is active: %s" % src); bad = 1
else:
    print("  [ ok ] no third-party analytics beacon")

# Nothing user-visible should still point at the upstream project.
leaks = [k for k, v in c.items() if "ai4eosc.eu" in json.dumps(v)]
if leaks:
    print("  [warn] still references cloud.ai4eosc.eu in: %s" % ", ".join(leaks))
else:
    print("  [ ok ] no cloud.ai4eosc.eu references")
sys.exit(bad)
PY
[[ $? -eq 0 ]] || fail=1

echo
echo "=== 3. The things the page will call ==="
for probe in "$DASH/assets/images/favicon.ico|favicon" ; do
    url="${probe%%|*}"; label="${probe##*|}"
    c=$(curl -sS --max-time 20 -o /dev/null -w '%{http_code}' "$url")
    [[ "$c" == "200" ]] && ok "$label served ($c)" || bad "$label returned $c"
done

c=$(curl -sS --max-time 30 -o /dev/null -w '%{http_code}' "https://${CAIOS_API_HOST}/v1/catalog/modules")
[[ "$c" == "200" ]] && ok "API catalogue reachable ($c)" || bad "API catalogue returned $c"

c=$(curl -sS --max-time 30 -o /dev/null -w '%{http_code}' \
    "https://${CAIOS_AUTH_HOST}/realms/${KEYCLOAK_REALM}/.well-known/openid-configuration")
[[ "$c" == "200" ]] && ok "login server discovery reachable ($c)" || bad "discovery returned $c"

echo
if (( fail )); then
    echo "DASHBOARD CHECK FAILED"
    exit 1
fi
cat <<EOF
Dashboard OK.

Open it at:  $DASH
Log in as:   researcher   (password in configs/env/caios.env)

If the browser warns about the certificate, import ~/caios-ca.pem once —
see docs/runbook.md.
EOF
