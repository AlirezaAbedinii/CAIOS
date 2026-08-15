#!/usr/bin/env bash
# Deploy the federated learning demo: one Flower server and three hospital
# workspaces, through PAPI, exactly as the dashboard would.
#
#   bash scripts/deploy-fl-demo.sh            # server + three sites
#   bash scripts/deploy-fl-demo.sh --status   # what is running, and where
#   bash scripts/deploy-fl-demo.sh --delete   # tear the whole demo down
#
# On demo day this is done by clicking through the dashboard — that is the
# story, and it is what the Stage 4 gate asks for. This script exists for
# rehearsal (V1 item 2) and for rebuilding the demo after a teardown without
# re-deriving nine form fields from memory. It calls the same PAPI endpoints the
# dashboard calls, with the same user's token.
#
# WHAT IT DEPLOYS, AND WHY EACH SETTING
#
#   ai4os-federated-server, service=jupyter
#       Not service=fedserver. That mode starts the server itself and gives no
#       window into it; with JupyterLab we run server.py in front of the
#       audience and the rounds print as they happen. A silent black box is a
#       bad demo.
#
#   min_fit_clients = min_available_clients = 3
#       Nothing aggregates until all three hospitals have reported. Keep the two
#       equal: upstream's server.py passes them to FedAvg the wrong way round,
#       which is invisible while they match and confusing the moment they do not.
#
#   three ai4os-dev-env, gpu_num=0
#       CPU-only, per D-18: PAPI caps one user at 2 GPUs across all running
#       deployments, so a third GPU-backed client is rejected outright. The
#       clients are downsampled hard anyway and a round takes seconds on CPU.
#
# PLACEMENT
#
# Nothing here pins a workspace to a node. The cluster scheduler is in "spread"
# mode (ansible/playbook-scheduler-config.yml), so each deployment goes to the
# least-allocated node and the three land one per site. --status prints where
# they actually went, because "three hospitals on three machines" is a claim the
# demo makes out loud and it is worth checking rather than assuming.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

ENV_FILE="configs/env/caios.env"
[[ -f "$ENV_FILE" ]] || { echo "Missing $ENV_FILE"; exit 1; }
set -a; source "$ENV_FILE"; set +a

VO="${CAIOS_VO:-vo.caios.ca}"
API="https://${CAIOS_API_HOST}"
USER_NAME="${CAIOS_FL_USER:-researcher}"
PW_VAR="CAIOS_PW_$(echo "$USER_NAME" | tr 'a-z-' 'A-Z_')"
PASSWORD="${!PW_VAR:-}"
ROUNDS="${CAIOS_FL_ROUNDS:-10}"
# The password for the deployed JupyterLab/VS Code workspaces. No default here
# on purpose: a working credential in a committed file is a committed secret,
# even a throwaway one on a VPN-only subnet. Real value lives in caios.env.
IDE_PASSWORD="${CAIOS_FL_IDE_PASSWORD:-}"
STATE="demo/fl/results/deployment.json"

[[ -n "$PASSWORD" ]] || { echo "No password for $USER_NAME ($PW_VAR unset in $ENV_FILE)"; exit 1; }
if [[ -z "$IDE_PASSWORD" ]]; then
    echo "CAIOS_FL_IDE_PASSWORD is unset. Add it to $ENV_FILE:"
    echo
    echo "    CAIOS_FL_IDE_PASSWORD=$(head -c 12 /dev/urandom | base64 | tr -d '/+=' | head -c 14)"
    echo
    echo "PAPI requires at least 9 characters."
    exit 1
fi

TOKEN="$(bash scripts/get-token.sh "$USER_NAME" "$PASSWORD" 2>/dev/null)"
[[ -n "$TOKEN" ]] || { echo "Could not get a token for $USER_NAME — is Keycloak up?"; exit 1; }

api() {  # api <method> <path> [body]
    local method="$1" path="$2" body="${3:-}"
    if [[ -n "$body" ]]; then
        curl -k -sS -X "$method" -H "Authorization: Bearer $TOKEN" \
            -H "Content-Type: application/json" "$API$path" -d "$body"
    else
        curl -k -sS -X "$method" -H "Authorization: Bearer $TOKEN" "$API$path"
    fi
}

list_tools() { api GET "/v1/deployments/tools?vos=$VO"; }

# ---------------------------------------------------------------------------
# --status
# ---------------------------------------------------------------------------
if [[ "${1:-}" == "--status" ]]; then
    # Note the quoting: the JSON arrives on stdin, so the program cannot come
    # from a heredoc — that would take stdin for itself and leave python
    # parsing its own source. Hence -c, in double quotes, with single quotes
    # inside and no $ or backticks.
    list_tools | python3 -c "
import json, sys
deps = json.load(sys.stdin)
if not deps:
    print('  nothing deployed.')
    raise SystemExit
print('  %d deployment(s):' % len(deps))
print()
for d in sorted(deps, key=lambda x: x.get('title') or ''):
    title = d.get('title') or '(untitled)'
    alloc = (d.get('alloc_ID') or '?')[:8]
    print('  %s' % title)
    print('    %s' % d['job_ID'])
    print('    status %s   alloc %s' % (d['status'], alloc))
    for name, url in (d.get('endpoints') or {}).items():
        if name in ('ide', 'fedserver', 'monitor'):
            print('    %-9s %s' % (name, url))
    print()
"
    exit 0
fi

# ---------------------------------------------------------------------------
# --delete
# ---------------------------------------------------------------------------
if [[ "${1:-}" == "--delete" ]]; then
    ids="$(list_tools | python3 -c 'import json,sys;[print(d["job_ID"]) for d in json.load(sys.stdin)]')"
    [[ -n "$ids" ]] || { echo "  nothing to delete."; exit 0; }
    echo "This will delete these tool deployments in $VO:"
    echo "$ids" | sed 's/^/  /'
    read -r -p "Type 'yes' to continue: " confirm
    [[ "$confirm" == "yes" ]] || { echo "aborted."; exit 1; }
    for id in $ids; do
        echo -n "  deleting $id ... "
        api DELETE "/v1/deployments/tools/$id?vo=$VO"; echo
    done
    rm -f "$STATE"
    exit 0
fi

# ---------------------------------------------------------------------------
# deploy
# ---------------------------------------------------------------------------
deploy() {  # deploy <tool> <json-conf> -> job id on stdout
    local tool="$1" conf="$2"
    api POST "/v1/deployments/tools?vo=$VO&tool_name=$tool" "$conf" | python3 -c "
import json, sys
r = json.load(sys.stdin)
if r.get('status') != 'success':
    print('DEPLOY FAILED:', json.dumps(r)[:400], file=sys.stderr)
    raise SystemExit(1)
print(r['job_ID'])
"
}

wait_running() {  # wait_running <tool-uuid> <label>
    local id="$1" label="$2"
    for _ in $(seq 60); do
        local status
        status="$(api GET "/v1/deployments/tools/$id?vo=$VO" |
            python3 -c "import json,sys;print(json.load(sys.stdin).get('status','?'))" 2>/dev/null)"
        case "$status" in
            running) echo "  $label is running"; return 0 ;;
            error|failed|dead) echo "  $label FAILED ($status)"; return 1 ;;
        esac
        sleep 10
    done
    echo "  $label did not start in 10 minutes — check the Nomad UI."
    return 1
}

echo "=== 1. federated server ($ROUNDS rounds, waiting for 3 hospitals) ==="
server_conf="$(ROUNDS="$ROUNDS" IDE_PASSWORD="$IDE_PASSWORD" python3 - <<'PY'
import json, os

print(json.dumps({
    "general": {
        "title": "CAIOS federated server",
        "desc": "Flower FL server for the three-hospital brain MRI demo",
        "service": "jupyter",
        "jupyter_password": os.environ["IDE_PASSWORD"],
    },
    "hardware": {"cpu_num": 1, "ram": 4000, "disk": 2000},
    "flower": {
        "rounds": int(os.environ["ROUNDS"]),
        "metric": "accuracy",
        "min_fit_clients": 3,
        "min_available_clients": 3,
    },
}))
PY
)"
server_id="$(deploy ai4os-federated-server "$server_conf")" || exit 1
echo "  $server_id"
wait_running "$server_id" "federated server" || exit 1

echo
echo "=== 2. three hospital workspaces (CPU-only, one per site) ==="
declare -A site_ids
for site in site_a site_b site_c; do
    # -c rather than a heredoc: a heredoc inside a command substitution inside
    # this loop is read once and then gone, so the second site would be
    # deployed with an empty body and PAPI would silently fill in defaults.
    conf="$(SITE="$site" IDE_PASSWORD="$IDE_PASSWORD" python3 -c "
import json, os
site = os.environ['SITE']
print(json.dumps({
    'general': {
        'title': 'CAIOS ' + site,
        'desc': 'Federated learning client for ' + site + ' — holds only its own slices',
        'service': 'jupyter',
        'jupyter_password': os.environ['IDE_PASSWORD'],
        'docker_tag': 'tf2.14.0',
    },
    'hardware': {'cpu_num': 1, 'gpu_num': 0, 'ram': 6000, 'disk': 8000},
}))
")"
    [[ -n "$conf" ]] || { echo "  could not build the config for $site"; exit 1; }
    id="$(deploy ai4os-dev-env "$conf")" || exit 1
    site_ids[$site]="$id"
    echo "  $site -> $id"
done

echo
for site in site_a site_b site_c; do
    wait_running "${site_ids[$site]}" "$site" || exit 1
done

# ---------------------------------------------------------------------------
# Record what was deployed, so the next steps do not need it typed back in.
# ---------------------------------------------------------------------------
mkdir -p "$(dirname "$STATE")"
python3 - "$STATE" "$server_id" "${site_ids[site_a]}" "${site_ids[site_b]}" "${site_ids[site_c]}" <<'PY'
import json, sys
state, server, *sites = sys.argv[1:]
json_data = {
    "server": server,
    "sites": dict(zip(["site_a", "site_b", "site_c"], sites)),
}
open(state, "w").write(json.dumps(json_data, indent=2) + "\n")
PY

echo
echo "=== 3. where everything landed ==="
bash "$0" --status

echo "=== next ==="
echo
echo "  1. Open the federated server's IDE, then in a terminal:"
echo "       cd federated-server/fedserver && python3 server.py"
echo
echo "  2. In each hospital workspace's terminal:"
echo "       curl -k -sSL https://${CAIOS_DASHBOARD_HOST}/fl/bootstrap.sh | bash -s <site> <fedserver-host>"
echo "       ./run.sh"
echo
echo "  Full walkthrough: docs/runbook.md, 'Running the federated demo'."
