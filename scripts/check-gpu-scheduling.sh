#!/usr/bin/env bash
# Does a Nomad job that ASKS for a GPU actually get a usable one?
#
#   bash scripts/check-gpu-scheduling.sh        # run on caios_server
#
# Deploys two tiny batch jobs and purges them. Nothing else is touched.
#
# WHY THIS EXISTS
# ---------------
# Found on 2026-08-19. Our GPUs are MIG-backed vGPUs: the physical device holds
# one `MIG 1g.12gb` instance, and CUDA can only use the MIG instance, not the
# parent. nomad-device-nvidia 1.0.0 fingerprints and allocates the PARENT
# device, so a job with a `device "gpu"` stanza gets a container where:
#
#     nvidia-smi          works, and shows the GPU
#     torch.cuda          is False
#
# That is the worst possible failure mode — it looks like success. docs/progress.md
# recorded "the GPU is visible inside a workspace" on 2026-08-12 and it was true
# and useless. Nothing GPU-backed has ever actually computed on this cluster.
#
# MIG support landed in nomad-device-nvidia 1.1.0 (issues #3, #27, #53, all
# closed 2024-08-22). `nomad_nvidia_plugin_version` in ansible/group_vars/all.yml
# is what selects it. This script is how you tell whether the bump worked.
#
# EXPECTED RESULT AFTER THE FIX: both probes report torch.cuda = True.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

export NOMAD_ADDR="${NOMAD_ADDR:-https://127.0.0.1:4646}"
export NOMAD_CACERT="${NOMAD_CACERT:-/etc/nomad.d/certs/nomad-ca.pem}"
export NOMAD_CLIENT_CERT="${NOMAD_CLIENT_CERT:-/etc/nomad.d/certs/cli.pem}"
export NOMAD_CLIENT_KEY="${NOMAD_CLIENT_KEY:-/etc/nomad.d/certs/cli-key.pem}"
export NOMAD_NAMESPACE="${NOMAD_NAMESPACE:-caios}"

JOB="caios-gpuprobe"
IMAGE="${CAIOS_PROBE_IMAGE:-ai4oshub/ai4os-dev-env:pytorch2.1}"
TMP="$(mktemp -d)"
trap 'nomad job stop -purge -detach "$JOB" >/dev/null 2>&1; rm -rf "$TMP"' EXIT

command -v nomad >/dev/null || { echo "nomad CLI not found — run this on caios_server."; exit 1; }

PROBE='import torch as t; c=t.cuda.is_available(); print(chr(84)+chr(79)+chr(82)+chr(67)+chr(72)+chr(95)+chr(67)+chr(85)+chr(68)+chr(65)+chr(61)+str(c)); print(chr(68)+chr(69)+chr(86)+chr(61)+(t.cuda.get_device_name(0) if c else chr(45)))'

render() {  # $1 = "with" | "without"
    local dev_stanza=""
    [[ "$1" == "with" ]] && dev_stanza='
        device "gpu" {
          count = 1
        }'
    cat > "$TMP/job.hcl" <<HCL
job "$JOB" {
  namespace = "$NOMAD_NAMESPACE"
  type      = "batch"
  region    = "global"

  constraint {
    attribute = "\${meta.status}"
    operator  = "regexp"
    value     = "ready"
  }
  constraint {
    attribute = "\${meta.type}"
    operator  = "="
    value     = "compute"
  }
  constraint {
    attribute = "\${meta.tags}"
    operator  = "regexp"
    value     = "gpu"
  }

  group "g" {
    task "probe" {
      driver = "docker"
      config {
        image   = "$IMAGE"
        command = "bash"
        args    = ["-c", "nvidia-smi -L | sed 's/^/SMI /'; python3 -c '$PROBE'"]
        # NOTE: $PROBE must contain no double quotes — it is embedded in an HCL
        # string, and one would terminate it and make the job unparseable.
      }
      resources {
        cores  = 1
        memory = 2000
$dev_stanza
      }
    }
  }
}
HCL
}

run_probe() {  # $1 = "with" | "without"
    render "$1"
    nomad job stop -purge -detach "$JOB" >/dev/null 2>&1
    sleep 2
    if ! nomad job run -detach "$TMP/job.hcl" >/dev/null 2>&1; then
        echo "  could not submit the probe job"
        return 1
    fi
    local alloc="" i
    for i in $(seq 1 24); do
        alloc="$(nomad job status "$JOB" 2>/dev/null | grep -A3 '^Allocations' | tail -1 | awk '{print $1}')"
        [[ -n "$alloc" && "$alloc" != "No" ]] && \
            nomad alloc status "$alloc" 2>/dev/null | grep -qE '^Client Status\s+= (complete|failed)' && break
        sleep 5
    done
    [[ -n "$alloc" ]] || { echo "  probe never scheduled"; return 1; }
    nomad alloc logs "$alloc" probe 2>/dev/null | grep -E '^(SMI|TORCH_CUDA|DEV)' | sed 's/^/  /'
    nomad job stop -purge -detach "$JOB" >/dev/null 2>&1
}

fail=0

echo "=== A. job WITH \`device \"gpu\" { count = 1 }\`  (what every PAPI template uses) ==="
a="$(run_probe with)"; echo "$a"
if grep -q 'TORCH_CUDA=True' <<<"$a"; then
    echo "  [ ok ] a GPU-requesting job gets a usable CUDA device"
else
    echo "  [FAIL] a GPU-requesting job gets NO usable CUDA device"
    grep -q 'MIG' <<<"$a" || echo "         (note: no MIG line above — the parent device was exposed, not the instance)"
    echo "         fix: bump nomad_nvidia_plugin_version to 1.1.0 and re-run the nomad playbook"
    fail=1
fi

echo
echo "=== B. same job WITHOUT the device stanza  (control) ==="
b="$(run_probe without)"; echo "$b"
if grep -q 'TORCH_CUDA=True' <<<"$b"; then
    echo "  [ ok ] CUDA works when Nomad is not selecting the device"
else
    echo "  [FAIL] CUDA does not work even without device selection — this is not a Nomad problem"
    fail=1
fi

echo
if [[ $fail -eq 0 ]]; then
    echo "GPU scheduling is healthy."
else
    echo "GPU scheduling is BROKEN — see above. Details: docs/llm-risks.md R-18."
fi
exit $fail
