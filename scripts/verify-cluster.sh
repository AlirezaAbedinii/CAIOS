#!/usr/bin/env bash
# Print the cluster state that decides whether anything can ever be scheduled.
#
#   bash scripts/verify-cluster.sh        # run on caios_server
#
# Read-only. Touches nothing.
#
# This is the first thing to run whenever a deployment is "stuck in pending".
# Every PAPI deployment is constrained on three pieces of node metadata plus the
# region. A node failing any of them looks completely healthy in
# `nomad node status` and silently never receives work.
set -uo pipefail

export NOMAD_ADDR="${NOMAD_ADDR:-https://127.0.0.1:4646}"
export NOMAD_CACERT="${NOMAD_CACERT:-/etc/nomad.d/certs/nomad-ca.pem}"
export NOMAD_CLIENT_CERT="${NOMAD_CLIENT_CERT:-/etc/nomad.d/certs/cli.pem}"
export NOMAD_CLIENT_KEY="${NOMAD_CLIENT_KEY:-/etc/nomad.d/certs/cli-key.pem}"

command -v nomad >/dev/null || { echo "nomad CLI not found — run this on caios_server."; exit 1; }

# The Consul CLI needs a token for anything useful. The bootstrap token is
# fetched to the controller by the Consul playbook.
CONSUL_BOOTSTRAP="${CONSUL_BOOTSTRAP:-$HOME/caios/consul_fetched/consul_bootstrap}"
if [[ -z "${CONSUL_HTTP_TOKEN:-}" && -r "$CONSUL_BOOTSTRAP" ]]; then
    CONSUL_HTTP_TOKEN="$(grep -oP 'SecretID:\s*\K\S+' "$CONSUL_BOOTSTRAP" 2>/dev/null)"
    export CONSUL_HTTP_TOKEN
fi

echo "=== Consul members ==="
if command -v consul >/dev/null; then
    consul members 2>&1 | sed 's/^/  /'
else
    echo "  consul CLI not found"
fi

echo
echo "=== Nomad servers ==="
nomad server members 2>&1 | grep -v "^$" | grep -v "Web UI" | sed 's/^/  /'

echo
echo "=== Nodes ==="
# `nomad node status -json` (list form) returns only a summary — it has no Meta
# field at all. The metadata that decides scheduling is only in the per-node
# form, so collect the IDs first and query each one.
NODE_IDS="$(nomad node status -json 2>/dev/null \
    | python3 -c 'import json,sys; [print(n["ID"]) for n in json.load(sys.stdin)]' 2>/dev/null)"

if [[ -z "$NODE_IDS" ]]; then
    echo "  could not read node list — is Nomad up, and are the certs readable?"
    exit 1
fi

NODE_DETAIL="$(for id in $NODE_IDS; do nomad node status -json "$id" 2>/dev/null; done \
    | python3 -c '
import json, sys
raw = sys.stdin.read()
dec = json.JSONDecoder()
out, i = [], 0
while i < len(raw):
    while i < len(raw) and raw[i].isspace():
        i += 1
    if i >= len(raw):
        break
    obj, i = dec.raw_decode(raw, i)
    out.append(obj)
json.dump(out, sys.stdout)
')"

printf '%s' "$NODE_DETAIL" | python3 -c '
import json, sys

nodes = json.load(sys.stdin)
hdr = ("%-18s %-7s %-9s %-12s %-9s %-6s %-16s %s" % (
    "NAME", "STATUS", "ELIGIBLE", "meta.status",
    "meta.type", "meta.tags", "meta.namespace", "meta.domain"))
print("  " + hdr)
print("  " + "-" * len(hdr))

problems = []
compute = 0
for n in sorted(nodes, key=lambda x: x.get("Name", "")):
    m = n.get("Meta") or {}
    name = n.get("Name", "?")
    print("  " + ("%-18s %-7s %-9s %-12s %-9s %-6s %-16s %s" % (
        name, n.get("Status", ""), n.get("SchedulingEligibility", ""),
        m.get("status", "-"), m.get("type", "-"), m.get("tags", "-"),
        m.get("namespace", "-"), m.get("domain", "-"))))

    if m.get("type") == "compute":
        compute += 1
        if m.get("status") != "ready":
            problems.append(
                "%s: meta.status is \"%s\", not \"ready\". PAPI constrains every "
                "deployment on this, so nothing will be placed. Run ai4-nomad_tests."
                % (name, m.get("status", "unset")))
        if not m.get("namespace"):
            problems.append("%s: no meta.namespace - will never receive work." % name)
        if not m.get("domain"):
            problems.append("%s: no meta.domain - deployments get no hostname." % name)
    if n.get("SchedulingEligibility") == "ineligible":
        problems.append("%s: marked ineligible; nothing will be placed here." % name)

print()
if not compute:
    problems.append("No node has meta.type=compute. Every PAPI deployment requires one.")

if problems:
    print("  PROBLEMS")
    for p in problems:
        print("   -", p)
    sys.exit(1)

print("  %d compute node(s) schedulable." % compute)
' || VERIFY_FAILED=1

echo
echo "=== Region (must be \"global\" to match PAPI job templates) ==="
nomad agent-info -json 2>/dev/null \
    | python3 -c 'import json,sys; print("  region:", json.load(sys.stdin)["config"]["Region"])' \
    2>/dev/null || echo "  could not read agent info"

echo
echo "=== Namespaces ==="
nomad namespace list 2>&1 | sed 's/^/  /'

echo
echo "=== Jobs ==="
nomad job status 2>&1 | grep -v "Web UI" | grep -v "^$" | sed 's/^/  /'

# docuum deletes least-recently-used Docker images above a threshold. Upstream's
# nomad role hardcodes 50 GB, which is smaller than the pre-pull set once the
# 30.8 GB vLLM image is included — so it silently deletes images that
# playbook-prepull-images.yml just fetched, and can evict vLLM itself between a
# rehearsal and a demo. Re-running playbook-nomad.yml puts 50 GB back.
echo
echo "=== docuum image-GC threshold (must be big enough for the vLLM image) ==="
DOCUUM_ARGS="$(NOMAD_NAMESPACE=default nomad job inspect docuum 2>/dev/null \
    | python3 -c '
import json, sys
try:
    job = json.load(sys.stdin)["Job"]
except Exception:
    raise SystemExit
for group in job.get("TaskGroups") or []:
    for task in group.get("Tasks") or []:
        args = (task.get("Config") or {}).get("args") or []
        if args:
            print(" ".join(str(a) for a in args))
' 2>/dev/null)"

if [[ -z "$DOCUUM_ARGS" ]]; then
    echo "  docuum is not running — images will accumulate until the disk fills"
else
    echo "  threshold: $DOCUUM_ARGS"
    if grep -q "50 GB" <<<"$DOCUUM_ARGS"; then
        echo "  PROBLEM: this is upstream's 50 GB, and the full image set is ~68 GB."
        echo "           Something re-ran the nomad role. Fix:"
        echo "             cd ansible && ansible-playbook playbook-docuum.yml"
        VERIFY_FAILED=1
    fi
fi

exit "${VERIFY_FAILED:-0}"
