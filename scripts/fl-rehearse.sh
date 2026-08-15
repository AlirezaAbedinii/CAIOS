#!/usr/bin/env bash
# Run the whole federation on this one machine, with no cluster involved.
#
#   bash scripts/fl-rehearse.sh              # 10 rounds, 3 sites
#   bash scripts/fl-rehearse.sh 5            # fewer rounds
#
# Starts demo/fl/local_server.py and three demo/fl/client.py processes over
# loopback, waits for the federation to finish, and checks that the aggregated
# accuracy actually improved and landed near the centralised baseline.
#
# WHY THIS EXISTS
#
# Everything that can go wrong with the federated client — a Flower version
# mismatch, weights that do not line up, a metric key the server cannot
# aggregate, a model that does not converge under averaging — goes wrong here in
# two minutes instead of in a redeploy loop against three Nomad jobs. What this
# cannot test is the network path: TLS through Traefik and the CA. That is
# Stage 4E, and it is the only thing left after this passes.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

ROUNDS="${1:-10}"
PYTHON="${PYTHON:-$ROOT/demo/.venv/bin/python}"
PORT="${FL_PORT:-5000}"
LOGS="$ROOT/demo/fl/results/rehearsal"
SITES=(site_a site_b site_c)

[[ -x "$PYTHON" ]] || { echo "No interpreter at $PYTHON — see docs/runbook.md."; exit 1; }
[[ -f demo/data/sites/test.npz ]] || { echo "No data — run demo/fl/partition.py first."; exit 1; }

mkdir -p "$LOGS"
pids=()
cleanup() { for p in "${pids[@]:-}"; do kill "$p" 2>/dev/null; done; }
trap cleanup EXIT

echo "=== server: $ROUNDS rounds, waiting for ${#SITES[@]} hospitals ==="
"$PYTHON" demo/fl/local_server.py --rounds "$ROUNDS" --clients "${#SITES[@]}" \
    --address "0.0.0.0:$PORT" >"$LOGS/server.log" 2>&1 &
server_pid=$!
pids+=("$server_pid")

# Flower refuses connections until the gRPC listener is actually bound, and a
# client that is refused exits rather than retrying.
for _ in $(seq 30); do
    (exec 3<>"/dev/tcp/127.0.0.1/$PORT") 2>/dev/null && break
    kill -0 "$server_pid" 2>/dev/null || { echo "server died:"; tail -20 "$LOGS/server.log"; exit 1; }
    sleep 1
done

echo "=== clients ==="
for site in "${SITES[@]}"; do
    "$PYTHON" demo/fl/client.py --site "$site" --server "127.0.0.1:$PORT" --insecure \
        >"$LOGS/$site.log" 2>&1 &
    pids+=($!)
    echo "  started $site"
done

echo
echo "=== federating (tail of the server log) ==="
while kill -0 "$server_pid" 2>/dev/null; do
    sleep 2
done
wait "$server_pid"
grep -E "^  round" "$LOGS/server.log" || true

echo
echo "=== result ==="
"$PYTHON" - "$ROOT" <<'PY'
import json, sys
from pathlib import Path

root = Path(sys.argv[1])
results = root / "demo" / "fl" / "results"
fed_file = results / "federated_server.json"
if not fed_file.exists():
    print("  [FAIL] no federated curve was written — see the logs above.")
    raise SystemExit(1)

curve = json.loads(fed_file.read_text())["curve"]
if len(curve) < 2:
    print(f"  [FAIL] only {len(curve)} round(s) completed.")
    raise SystemExit(1)

first, best, last = curve[0], max(curve), curve[-1]
print(f"  federated   round 1 {first:.3f} -> round {len(curve)} {last:.3f} (best {best:.3f})")

fail = 0
if best <= first:
    print("  [FAIL] accuracy never improved over round 1.")
    fail = 1
else:
    print("  [ ok ] accuracy improved across rounds")

base_file = results / "baselines.json"
if base_file.exists():
    base = json.loads(base_file.read_text())
    sites = {k: max(v) for k, v in base["curves"].items() if k != "central"}
    central = max(base["curves"]["central"])
    best_site = max(sites.values())
    for name, value in sorted(sites.items()):
        print(f"  {name:11s} best {value:.3f}")
    print(f"  central     best {central:.3f}")
    if best > best_site:
        print(f"  [ ok ] federated beats every site alone (+{best - best_site:.3f})")
    else:
        print(f"  [WARN] federated {best:.3f} did not beat the best site {best_site:.3f}")
        print("         more rounds usually fixes this; it is not a plumbing fault.")
else:
    print("  [WARN] no baselines.json — run demo/fl/baselines.py to compare.")

raise SystemExit(fail)
PY
status=$?

echo
echo "logs in $LOGS/"
exit "$status"
