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
    # Must be "https://<api host>/v1" — the suffix is not optional, see below.
    ("apiURL points at our API",
     c.get("apiURL") == "https://%s/v1" % api_host, c.get("apiURL")),
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
c=$(curl -sS --max-time 20 -o /dev/null -w '%{http_code}' "$DASH/assets/images/favicon.ico")
[[ "$c" == "200" ]] && ok "favicon served ($c)" || bad "favicon returned $c"

# apiURL must end in /v1. app.config.ts replaces the API base with this value
# wholesale, and the built-in default carries the suffix — omit it and every
# call lands one level too high, which the UI reports as
# "Error calling the API, please retry later Error: Not Found".
API_BASE=$(python3 -c "import json;print(json.load(open('/tmp/caios-cfg.json'))['apiURL'])" 2>/dev/null)
[[ "$API_BASE" == */v1 ]] && ok "apiURL includes the /v1 suffix" \
                          || bad "apiURL is '$API_BASE' — must end in /v1"

# Call the endpoints the dashboard actually loads, with the Accept header a
# browser actually sends. Angular sends a list, not the bare "application/json"
# that upstream's metadata endpoint compares against — so testing with curl's
# default header hides a 400 that every real page load would hit.
BROWSER_ACCEPT='Accept: application/json, text/plain, */*'
TOKEN=$(bash scripts/get-token.sh researcher "${CAIOS_PW_RESEARCHER:-}" 2>/dev/null)

for ep in \
    "catalog/modules/detail|module catalogue" \
    "catalog/tools/detail|tool catalogue" \
    "catalog/modules/ai4os-demo-app/metadata|module metadata"
do
    path="${ep%%|*}"; label="${ep##*|}"
    c=$(curl -sS --max-time 40 -H "$BROWSER_ACCEPT" -o /dev/null -w '%{http_code}' "$API_BASE/$path")
    [[ "$c" == "200" ]] && ok "$label ($c)" || bad "$label returned $c"
done

if [[ -n "$TOKEN" ]]; then
    for ep in \
        "deployments/stats/cluster?vo=vo.caios.ca|cluster statistics" \
        "deployments/stats/user?vo=vo.caios.ca|user statistics" \
        "deployments/modules?vo=vo.caios.ca|deployments list"
    do
        path="${ep%%|*}"; label="${ep##*|}"
        c=$(curl -sS --max-time 40 -H "$BROWSER_ACCEPT" -H "Authorization: Bearer $TOKEN" \
            -o /dev/null -w '%{http_code}' "$API_BASE/$path")
        [[ "$c" == "200" ]] && ok "$label ($c)" || bad "$label returned $c"
    done
    # The Statistics page dereferences these without a guard:
    #   statsResponse['datacenters'][dc]['footprints']['carbon']
    # A null footprints throws inside the subscribe callback, and the page then
    # spins forever showing no error at all — so assert the shape, not just 200.
    curl -sS --max-time 60 -H "$BROWSER_ACCEPT" -H "Authorization: Bearer $TOKEN" \
        -o /tmp/caios-cluster.json "$API_BASE/deployments/stats/cluster?vo=vo.caios.ca" 2>/dev/null
    python3 <<'PYSTATS'
import json, sys
try:
    d = json.load(open("/tmp/caios-cluster.json"))
except Exception as e:
    print("  [FAIL] cluster stats are not valid JSON: %s" % e); sys.exit(1)

dcs = d.get("datacenters") or {}
if not dcs:
    print("  [FAIL] no datacenters reported"); sys.exit(1)

bad = 0
for name, dc in dcs.items():
    fp = dc.get("footprints")
    if not isinstance(fp, dict) or not all(k in fp for k in ("carbon", "water", "green-score")):
        print("  [FAIL] datacenter %s has footprints=%r — the Statistics page "
              "will throw and hang on this" % (name, fp)); bad = 1
    if dc.get("affinity") is None:
        print("  [FAIL] datacenter %s has affinity=None" % name); bad = 1
    if not dc.get("nodes"):
        print("  [FAIL] datacenter %s reports no nodes" % name); bad = 1

if not bad:
    n = sum(len(dc.get("nodes") or {}) for dc in dcs.values())
    c = d.get("cluster") or {}
    print("  [ ok ] statistics shape is renderable (%d node(s), %s GPU(s))"
          % (n, c.get("gpu_total")))
sys.exit(bad)
PYSTATS
    [[ $? -eq 0 ]] || fail=1
else
    printf '  [skip] authenticated endpoints — no password in caios.env\n'
fi

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

FIRST, in that browser, install our CA:

    $DASH/caios-ca.pem

Not cosmetic. The page is served from ${CAIOS_DASHBOARD_HOST} but calls the API
on ${CAIOS_API_HOST}. Clicking past the warning covers only the first host; the
background calls to the second are blocked silently, and the page reports
"Error calling the API, please try again later".

docs/runbook.md has per-platform install steps and a stopgap.
EOF
