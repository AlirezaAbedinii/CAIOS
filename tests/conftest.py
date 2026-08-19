"""Shared fixtures, and the cluster constants the tests assert against.

The numbers here are MEASURED, not specified. Re-derive them with
`bash scripts/check-llm-node.sh` and `bash scripts/verify-cluster.sh` rather
than editing them to make a test pass — if the hardware really changed, the
plan changed with it.
"""

from pathlib import Path
import re

import pytest

ROOT = Path(__file__).resolve().parent.parent


# --- the cluster, as measured on 2026-08-19 -------------------------------

# Nomad reports 3 reservable cores per node at 6000 MHz total, so one core is
# worth 2000 MHz of the shared pool. This is the relationship that makes
# "reserve all 3 cores and the job still will not place" true.
NODE_CORES = 3
NODE_CPU_MHZ = 6000
MHZ_PER_CORE = NODE_CPU_MHZ // NODE_CORES

# 35068 MB present, 4096 reserved for the OS by nomad_reserved_memory_mb.
NODE_MEMORY_MB = 35068 - 4096

# torch.cuda.mem_get_info() inside a container, which is what vLLM sizes
# against. nvidia-smi says 12288/10565; those are NOT the numbers that matter.
GPU_TOTAL_MIB = 12100
GPU_FREE_MIB = 10475

# vLLM's fixed overhead: CUDA context, compiled graphs, activation peaks.
# A working estimate, replaced by measurement in Stage L3.
VLLM_OVERHEAD_MIB = 1200


@pytest.fixture(scope="session")
def root():
    return ROOT


def strip_hcl_comments(text):
    """Remove /* */ blocks and # line comments.

    Needed because the CAIOS templates explain at length what upstream got
    wrong, and those explanations quote the very strings the tests assert are
    absent. A test that cannot tell code from commentary would fail on its own
    documentation.
    """
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    return re.sub(r"^\s*#.*$", "", text, flags=re.MULTILINE)
