#!/usr/bin/env bash
# Print the node metadata that decides whether anything can ever be scheduled.
#
#   bash scripts/verify-cluster.sh        # run on caios_server
#
# Read-only. Touches nothing.
#
# This is the first thing to run whenever a deployment is "stuck in pending".
# PAPI's job templates constrain every deployment on three pieces of node
# metadata and a region. A node failing any of them looks completely healthy in
# `nomad node status` and silently never receives work.
set -euo pipefail

export NOMAD_ADDR="${NOMAD_ADDR:-https://127.0.0.1:4646}"
export NOMAD_CACERT="${NOMAD_CACERT:-/etc/nomad.d/certs/nomad-ca.pem}"
export NOMAD_CLIENT_CERT="${NOMAD_CLIENT_CERT:-/etc/nomad.d/certs/cli.pem}"
export NOMAD_CLIENT_KEY="${NOMAD_CLIENT_KEY:-/etc/nomad.d/certs/cli-key.pem}"

command -v nomad >/dev/null || { echo "nomad CLI not found — run this on caios_server."; exit 1; }

echo "=== Consul ==="
consul members 2>/dev/null || echo "  (consul CLI unavailable or ACL token not exported)"

echo
echo "=== Nomad region ==="
# Must be "global": every PAPI job template hardcodes region = "global", and a
# job submitted to a region that does not exist is rejected outright.
nomad agent-info -json 2>/dev/null \
    | python3 -c 'import json,sys; print("  region:", json.load(sys.stdin)["config"]["Region"])' \
    2>/dev/null || echo "  could not read agent info"

echo
echo "=== Nodes ==="
nomad node status -json | python3 - <<'PY'
import json, sys

nodes = json.load(sys.stdin)
hdr = f"{'NAME':<26} {'STATUS':<8} {'ELIGIBLE':<10} {'meta.status':<12} {'meta.type':<9} {'meta.tags':<6} {'meta.namespace':<18} {'meta.domain'}"
print("  " + hdr)
print("  " + "-" * len(hdr))

problems = []
for n in nodes:
    m = n.get("Meta") or {}
    name = n.get("Name", "?")
    row = (f"{name:<26} {n.get('Status',''):<8} {n.get('SchedulingEligibility',''):<10} "
           f"{m.get('status','-'):<12} {m.get('type','-'):<9} {m.get('tags','-'):<6} "
           f"{m.get('namespace','-'):<18} {m.get('domain','-')}")
    print("  " + row)

    # Only compute nodes are expected to run user workloads.
    if m.get("type") == "compute":
        if m.get("status") != "ready":
            problems.append(
                f"{name}: meta.status is '{m.get('status','unset')}', not 'ready'. "
                "PAPI constrains every deployment on this. Run ai4-nomad_tests."
            )
        if not m.get("namespace"):
            problems.append(f"{name}: no meta.namespace — will never receive work.")
        if not m.get("domain"):
            problems.append(f"{name}: no meta.domain — deployments get no hostname.")
    if n.get("SchedulingEligibility") == "ineligible":
        problems.append(f"{name}: marked ineligible; nothing will be placed here.")

print()
if problems:
    print("  PROBLEMS")
    for p in problems:
        print("   -", p)
    sys.exit(1)

if not any((n.get("Meta") or {}).get("type") == "compute" for n in nodes):
    print("  PROBLEM: no node has meta.type=compute. Every PAPI deployment "
          "requires one.")
    sys.exit(1)

print("  All compute nodes look schedulable.")
PY

echo
echo "=== Namespaces ==="
nomad namespace list

echo
echo "=== Running jobs ==="
nomad job status
