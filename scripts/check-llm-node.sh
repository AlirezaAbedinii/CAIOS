#!/usr/bin/env bash
# Stage L0: measure a candidate LLM node, and prove CUDA actually computes on it.
#
#   bash scripts/check-llm-node.sh                    # node 6, plus site_a as a reference
#   bash scripts/check-llm-node.sh 192.168.104.188    # just one
#
# Read-only on the node: no writes, no formatting, no configuration changes.
# It does run ONE short-lived container (--rm) to test CUDA. That container is
# removed when it exits and touches nothing outside itself.
#
# WHY THE CUDA TEST IS THE POINT OF THIS SCRIPT
# ---------------------------------------------
# These GPUs are MIG-backed vGPUs. On a MIG-enabled device, `nvidia-smi` inside
# a container can show the GPU perfectly while CUDA cannot use it at all —
# because the parent device is exposed and the MIG instance is not. The output
# looks like success.
#
# docs/progress.md recorded exactly that on 2026-08-12: "the GPU is visible
# inside a workspace". It was, and CUDA still did not work. So this script does
# not ask whether the GPU is *visible*; it multiplies two matrices and checks
# the answer.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

KEY="${CAIOS_SSH_KEY:-$HOME/.ssh/caios_cluster}"
# Already on every compute node (playbook-prepull-images.yml), so no download.
PROBE_IMAGE="${CAIOS_PROBE_IMAGE:-ai4oshub/ai4os-dev-env:pytorch2.1}"

NODES=("$@")
if [[ ${#NODES[@]} -eq 0 ]]; then
    NODES=(192.168.104.188 192.168.104.20)
fi

SSH_OPTS=(-i "$KEY" -o IdentitiesOnly=yes -o PasswordAuthentication=no
          -o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new)

fail=0
ok()   { printf '  [ ok ] %s\n' "$1"; }
bad()  { printf '  [FAIL] %s\n' "$1"; fail=1; }
warn() { printf '  [warn] %s\n' "$1"; }

[[ -f "$KEY" ]] || { echo "No cluster key at $KEY. See docs/ssh-setup.md."; exit 1; }

for ip in "${NODES[@]}"; do
    echo
    echo "==================== $ip ===================="

    if ! timeout 20 ssh "${SSH_OPTS[@]}" "ubuntu@$ip" true 2>/dev/null; then
        bad "cannot log in with the cluster key — see docs/ssh-setup.md"
        continue
    fi
    ok "reachable with the cluster key alone"

    echo
    echo "--- specs ---"
    timeout 60 ssh "${SSH_OPTS[@]}" "ubuntu@$ip" '
        echo "hostname : $(hostname)"
        echo "cores    : $(nproc)"
        echo "ram      : $(free -g | awk "/^Mem:/{print \$2\" GB\"}")"
        nvidia-smi --query-gpu=name,memory.total,memory.free,compute_cap,driver_version \
                   --format=csv,noheader 2>/dev/null \
            | awk -F", " "{print \"gpu      : \"\$1\"  total=\"\$2\"  free=\"\$3\"  cc=\"\$4\"  driver=\"\$5}" \
            || echo "gpu      : NONE DETECTED"
        echo "mig      : $(nvidia-smi -L 2>/dev/null | grep -c MIG) instance(s)"
    ' 2>/dev/null | sed "s/^/  /"

    echo
    echo "--- the volume Stage L1 would reformat ---"
    # This is the output a human has to read before approving L1. It is printed
    # in full deliberately: the approval is for erasing THIS, not for a summary.
    timeout 60 ssh "${SSH_OPTS[@]}" "ubuntu@$ip" '
        lsblk -o NAME,SIZE,FSTYPE,MOUNTPOINT,LABEL | grep -vE "loop[0-9]"
        echo
        echo "contents of /mnt:"
        ls -A /mnt 2>/dev/null | sed "s/^/    /" || echo "    (not mounted)"
    ' 2>/dev/null | sed "s/^/  /"

    # A node already through playbook-prepare-volumes.yml has /dev/vdb1 mounted
    # at /mnt/data and needs nothing. Only the shipped layout — ext4 written
    # straight onto /dev/vdb with no partition table — is what L1 has to change.
    prepared="$(timeout 30 ssh "${SSH_OPTS[@]}" "ubuntu@$ip" \
        'findmnt -no SOURCE /mnt/data 2>/dev/null' 2>/dev/null)"
    if [[ "$prepared" == /dev/vd*1 ]]; then
        ok "already prepared: $prepared mounted at /mnt/data — Stage L1 has nothing to do here"
    else
        contents="$(timeout 30 ssh "${SSH_OPTS[@]}" "ubuntu@$ip" \
            'ls -A /mnt 2>/dev/null | grep -v "^lost+found$" | wc -l' 2>/dev/null)"
        if [[ "${contents:-1}" == "0" ]]; then
            ok "/mnt holds nothing but lost+found — safe for Stage L1 to reformat"
        else
            warn "/mnt has $contents entries besides lost+found — Stage L1 would ERASE them"
            warn "playbook-prepare-volumes.yml refuses to run until that is resolved"
        fi
    fi

    echo
    echo "--- container runtime and egress ---"
    timeout 60 ssh "${SSH_OPTS[@]}" "ubuntu@$ip" '
        sudo docker info 2>/dev/null | grep -i "runtimes" | sed "s/^ */  /"
        printf "  huggingface.co : "; curl -s -o /dev/null -w "%{http_code}\n" --max-time 15 https://huggingface.co/api/models/Qwen/Qwen3.5-2B
        printf "  ghcr.io        : "; curl -s -o /dev/null -w "%{http_code}\n" --max-time 15 https://ghcr.io/v2/
        printf "  free on data   : "; df -h /mnt/data 2>/dev/null | awk "NR==2{print \$4}" || df -h /mnt | awk "NR==2{print \$4}"
    ' 2>/dev/null

    echo
    echo "--- CUDA COMPUTE (not just visibility) ---"
    out="$(timeout 300 ssh "${SSH_OPTS[@]}" "ubuntu@$ip" "
        sudo docker run --rm --runtime=nvidia -e NVIDIA_VISIBLE_DEVICES=all \
          $PROBE_IMAGE python3 -c '
import torch
if not torch.cuda.is_available():
    print(\"NO-CUDA\"); raise SystemExit(1)
free, total = torch.cuda.mem_get_info()
a = torch.randn(1024, 1024, device=\"cuda\")
err = float((a @ a - (a.cpu() @ a.cpu()).cuda()).abs().max())
print(\"DEV\", torch.cuda.get_device_name(0))
print(\"CAP\", \"%d.%d\" % torch.cuda.get_device_capability(0))
print(\"MEM\", int(total/2**20), int(free/2**20))
print(\"BF16\", torch.cuda.is_bf16_supported())
print(\"ERR\", err)
'" 2>/dev/null)"

    if grep -q "^DEV" <<<"$out"; then
        dev=$(awk '/^DEV/{$1="";print substr($0,2)}' <<<"$out")
        cap=$(awk '/^CAP/{print $2}' <<<"$out")
        tot=$(awk '/^MEM/{print $2}' <<<"$out")
        fre=$(awk '/^MEM/{print $3}' <<<"$out")
        bf=$(awk  '/^BF16/{print $2}' <<<"$out")
        ok "CUDA computes: $dev"
        ok "compute capability $cap  (>=8.0 means bfloat16, so no --dtype float16)"
        ok "CUDA sees total=${tot} MiB, free=${fre} MiB"
        [[ "$bf" == "True" ]] && ok "bfloat16 supported" || bad "bfloat16 NOT supported"

        # Sizing report, not a pass/fail gate. vLLM takes gpu-memory-utilization
        # as a fraction of TOTAL, but can only ever use FREE — and on this vGPU
        # those differ by ~1.6 GB because of ECC and virtualisation overhead.
        # vLLM's own default is 0.90, and it is expected to be over the line.
        echo "        vLLM --gpu-memory-utilization, against ${fre} MiB actually free:"
        for u in 90 85 80; do
            want=$(( tot * u / 100 ))
            head=$(( fre - want ))
            if   [[ $head -lt 0   ]]; then verdict="OVER by $(( -head )) MiB — will not start"
            elif [[ $head -lt 500 ]]; then verdict="fits, only ${head} MiB spare — too tight"
            else                            verdict="fits, ${head} MiB spare"
            fi
            printf '          0.%s -> %5s MiB : %s\n' "$u" "$want" "$verdict"
        done
    else
        bad "CUDA does NOT work in a container on this node"
        [[ -n "$out" ]] && sed 's/^/        /' <<<"$out" | head -5
    fi
done

echo
if [[ $fail -eq 0 ]]; then
    echo "All checks passed."
else
    echo "Some checks FAILED — see above."
fi
exit $fail
