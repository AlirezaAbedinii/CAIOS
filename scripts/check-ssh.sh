#!/usr/bin/env bash
# Verify caios_server can reach every other node with the cluster key alone,
# and report the disk layout Stage 1 depends on.
#
#   bash scripts/check-ssh.sh
#
# Read-only. Runs `lsblk` and `ls` on each node and nothing else.
#
# Deliberately disables agent forwarding and password authentication, so a pass
# means Ansible will work unattended rather than only while you are logged in.
set -uo pipefail

KEY="${CAIOS_SSH_KEY:-$HOME/.ssh/caios_cluster}"
NODES=(
    "caios_edge   192.168.104.105"
    "caios_site_a 192.168.104.20"
    "caios_site_b 192.168.104.145"
    "caios_site_c 192.168.104.7"
)

if [[ ! -f "$KEY" ]]; then
    echo "No cluster key at $KEY."
    echo "Generate one:  ssh-keygen -t ed25519 -N '' -f $KEY"
    exit 1
fi

SSH_OPTS=(
    -i "$KEY"
    -o IdentitiesOnly=yes          # ignore any agent; prove THIS key works
    -o PasswordAuthentication=no
    -o BatchMode=yes               # never prompt
    -o ConnectTimeout=8
    -o StrictHostKeyChecking=accept-new
)

echo "Using key: $KEY"
echo "           $(ssh-keygen -lf "${KEY}.pub" 2>/dev/null || echo '(no public half)')"
echo

fail=0
for entry in "${NODES[@]}"; do
    read -r name ip <<<"$entry"
    printf '%-14s %-16s ' "$name" "$ip"

    out="$(ssh "${SSH_OPTS[@]}" "ubuntu@$ip" \
        'echo REACHABLE; lsblk -ndo NAME,SIZE,FSTYPE,MOUNTPOINT | grep -v loop; echo "---"; ls -A /mnt 2>/dev/null | head -5' 2>&1)"

    if [[ "$out" == REACHABLE* ]]; then
        echo "OK"
        # Disk layout: the site nodes need /dev/vdb, which Ansible will reformat.
        echo "$out" | sed -n '2,/---/p' | grep -v '^---$' | sed 's/^/                                 disk: /'
        contents="$(echo "$out" | sed -n '/^---$/,$p' | tail -n +2)"
        if [[ -n "$contents" ]]; then
            echo "                                 /mnt contains: $(echo "$contents" | tr '\n' ' ')"
            echo "                                 ^ playbook-nomad.yml ERASES /mnt on site nodes"
        else
            echo "                                 /mnt is empty — safe to reformat"
        fi
    else
        echo "FAILED"
        echo "$out" | head -3 | sed 's/^/                                 /'
        fail=1
    fi
    echo
done

if (( fail )); then
    cat <<EOF
Not all nodes are reachable with the cluster key.

The public key that must be in ~/.ssh/authorized_keys on each node:

  $(cat "${KEY}.pub" 2>/dev/null)

See docs/ssh-setup.md for how to install it.
EOF
    exit 1
fi

cat <<'EOF'
All four nodes reachable with the cluster key alone.

Next:
  cd ansible && ansible all -m ping

Then check the disk report above. Any site node whose /mnt holds something you
care about must be dealt with before playbook-nomad.yml runs — it repartitions
and reformats that volume.
EOF
