#!/usr/bin/env bash
# Print (or, with --apply, run) the OpenStack commands that create the four
# CAIOS security groups.
#
#   bash scripts/openstack-security-groups.sh            # print only, default
#   bash scripts/openstack-security-groups.sh --apply    # actually create them
#
# Prints by default on purpose. This is shared academic infrastructure under a
# PI's allocation — read the commands before anything touches it.
#
# Creating groups is additive and reversible. Nothing here deletes anything.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

APPLY=false
[[ "${1:-}" == "--apply" ]] && APPLY=true

# The private subnet all five nodes share, e.g. 192.168.1.0/24.
# Consul and Nomad ports are restricted to this; exposing them publicly would
# hand over cluster control.
SUBNET="${CAIOS_SUBNET:-<PRIVATE_SUBNET_CIDR>}"
# Where you and the other engineer SSH from. Narrow this if you can.
ADMIN_CIDR="${CAIOS_ADMIN_CIDR:-0.0.0.0/0}"

if [[ "$SUBNET" == "<PRIVATE_SUBNET_CIDR>" ]]; then
    echo "# NOTE: set CAIOS_SUBNET to the cluster's private CIDR before applying."
    echo "#       e.g. CAIOS_SUBNET=192.168.1.0/24 bash $0 --apply"
    echo
fi

emit() {
    if $APPLY; then
        echo "+ $*"
        "$@"
    else
        printf '%q ' "$@"; echo
    fi
}

rule() { emit openstack security group rule create "$@"; }

cat <<'EOF'
# ---------------------------------------------------------------------------
# CAIOS security groups
#
# Apply to nodes as follows (docs/infrastructure.md):
#   caios_server   default, caios_consul, caios_nomad, caios_traefik
#                  (traefik group is what opens 80/443 for the dashboard/API)
#   caios_edge     default, caios_consul, caios_nomad, caios_traefik
#   caios_site_*   default, caios_consul, caios_nomad
#
# Upstream also documents a fifth "Federation" group for multi-site clusters.
# We are a single site; it is deliberately skipped.
# ---------------------------------------------------------------------------
EOF
echo

echo "# --- groups ---"
for g in caios_consul caios_nomad caios_traefik; do
    emit openstack security group create "$g" --description "CAIOS $g"
done
echo

echo "# --- caios_consul: cluster gossip and service discovery, subnet only ---"
rule --protocol tcp --dst-port 8300 --remote-ip "$SUBNET" --description "Consul server RPC" caios_consul
for p in 8301 8302; do
    rule --protocol tcp --dst-port $p --remote-ip "$SUBNET" --description "Consul Serf" caios_consul
    rule --protocol udp --dst-port $p --remote-ip "$SUBNET" --description "Consul Serf" caios_consul
done
rule --protocol tcp --dst-port 8500:8503 --remote-ip "$SUBNET" --description "Consul HTTP/HTTPS/gRPC" caios_consul
rule --protocol tcp --dst-port 8600 --remote-ip "$SUBNET" --description "Consul DNS" caios_consul
rule --protocol udp --dst-port 8600 --remote-ip "$SUBNET" --description "Consul DNS" caios_consul
rule --protocol tcp --dst-port 21000:21255 --remote-ip "$SUBNET" --description "Consul sidecar proxies" caios_consul
echo

echo "# --- caios_nomad: scheduling, subnet only ---"
# Upstream opens 4646 to 0.0.0.0/0. We do not need to: PAPI runs on the Nomad
# server and reaches it over loopback.
rule --protocol tcp --dst-port 4646 --remote-ip "$SUBNET" --description "Nomad HTTP API" caios_nomad
rule --protocol tcp --dst-port 4647 --remote-ip "$SUBNET" --description "Nomad RPC" caios_nomad
rule --protocol tcp --dst-port 4648 --remote-ip "$SUBNET" --description "Nomad Serf" caios_nomad
rule --protocol udp --dst-port 4648 --remote-ip "$SUBNET" --description "Nomad Serf" caios_nomad
echo

echo "# --- caios_traefik: public ingress ---"
rule --protocol tcp --dst-port 80 --remote-ip 0.0.0.0/0 --description "HTTP (also ACME challenge)" caios_traefik
rule --protocol tcp --dst-port 443 --remote-ip 0.0.0.0/0 --description "HTTPS" caios_traefik
# NVFLARE talks over raw TCP through Traefik's nvflare_fl / nvflare_admin
# entrypoints. Easy to miss, and it breaks that demo silently.
rule --protocol tcp --dst-port 8002:8003 --remote-ip 0.0.0.0/0 --description "NVFLARE FL and admin" caios_traefik
rule --protocol tcp --dst-port 8081 --remote-ip "$SUBNET" --description "Traefik dashboard" caios_traefik
echo

echo "# --- default group: SSH ---"
rule --protocol tcp --dst-port 22 --remote-ip "$ADMIN_CIDR" --description "SSH" default
echo

if ! $APPLY; then
    cat <<'EOF'
# ---------------------------------------------------------------------------
# Printed only. Re-run with --apply to execute, after setting CAIOS_SUBNET
# and ideally CAIOS_ADMIN_CIDR.
# ---------------------------------------------------------------------------
EOF
fi
