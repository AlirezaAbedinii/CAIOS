"""The LLM job template asks for resources that exist, and for a GPU that does.

Every assertion here corresponds to a way the deployment fails silently — a job
that PAPI accepts and Nomad then never places, with no error anywhere. That is
the failure mode this file exists to make loud.
"""

import re

import pytest

from conftest import (
    GPU_TOTAL_MIB,
    MHZ_PER_CORE,
    NODE_CORES,
    NODE_CPU_MHZ,
    NODE_MEMORY_MB,
    strip_hcl_comments,
)
from render import render

TEMPLATE = "configs/papi/tools/ai4os-llm/nomad.hcl"


@pytest.fixture(scope="module")
def job(root):
    """The template as PAPI would submit it: substituted, comments removed."""
    return strip_hcl_comments(render(root / TEMPLATE))


def _ints(job, key):
    return [int(m) for m in re.findall(rf"^\s*{key}\s*=\s*(\d+)\s*$", job, re.MULTILINE)]


def test_no_tesla_t4_constraint(job):
    """Upstream pins device.model to "Tesla T4".

    No device here matches, so the job would be accepted and then pend forever.
    """
    assert "Tesla T4" not in job


def test_exactly_one_gpu_requested(job):
    """One GPU per node, and vLLM cannot use more than one MIG instance anyway."""
    devices = re.findall(r'device\s+"gpu"\s*\{([^}]*)\}', job, re.DOTALL)
    assert len(devices) == 1, f"expected one gpu device block, found {len(devices)}"
    assert re.search(r"count\s*=\s*1", devices[0])


def test_dedicated_cores_fit_the_node(job):
    cores = sum(_ints(job, "cores"))
    assert cores <= NODE_CORES, (
        f"template reserves {cores} dedicated cores; nodes have {NODE_CORES}. "
        "Upstream asks for 8 — this is the check that catches that."
    )


def test_shared_cpu_survives_the_core_reservation(job):
    """The subtle one, and the reason a naive fix still does not place.

    Nomad's `cores` reserves whole CPUs *and* removes their share of the MHz
    pool. Reserve all three on a 6000 MHz node and the tasks using plain `cpu`
    shares — here, Open WebUI and the two helpers — have nothing left to draw
    on, so the group as a whole is unschedulable even though `cores` alone fit.
    """
    cores = sum(_ints(job, "cores"))
    shares = sum(_ints(job, "cpu"))
    remaining = NODE_CPU_MHZ - cores * MHZ_PER_CORE
    assert shares <= remaining, (
        f"{cores} dedicated cores leave {remaining} MHz in the shared pool, "
        f"but share-based tasks ask for {shares} MHz"
    )


def test_memory_fits_the_node(job):
    total = sum(_ints(job, "memory"))
    assert total <= NODE_MEMORY_MB, (
        f"tasks ask for {total} MB; {NODE_MEMORY_MB} MB is schedulable"
    )


def test_every_image_is_pinned(job):
    """A floating tag turns "it worked yesterday" into a demo-day surprise."""
    images = re.findall(r'image\s*=\s*"([^"]+)"', job)
    assert images, "no images found — has the template moved?"
    for image in images:
        assert ":" in image, f"{image} has no tag at all"
        tag = image.rsplit(":", 1)[1]
        assert tag not in ("latest", "main", "master", "dev", "nightly"), (
            f"{image} uses a moving tag"
        )


def test_images_are_not_force_pulled(job):
    """vLLM's image is 10.5 GB. Pulling it per deployment is minutes of silence."""
    assert "force_pull = true" not in job.replace("  ", " ")


def test_helper_tasks_do_not_leave_the_allocation(job):
    """R-05, the one that would have cost a day.

    Upstream's two helper tasks call their own PUBLIC HTTPS URL, which is served
    with our own CA's certificate. A stock python image does not trust it,
    `requests` raises, neither script catches, and because both are
    prestart/poststart hooks the whole allocation dies — with a traceback that
    never mentions certificates.
    """
    for var in ("VLLM_ENDPOINT", "OPEN_WEBUI_URL"):
        m = re.search(rf'{var}\s*=\s*"([^"]+)"', job)
        assert m, f"{var} not found in the template"
        assert m.group(1).startswith("http://"), (
            f"{var} is {m.group(1)!r} — it must not go out through Traefik"
        )
        assert "NOMAD_ADDR_" in m.group(1), (
            f"{var} should address the allocation directly"
        )


def test_helper_scripts_survive_a_connection_error(job):
    """Waiting for a model to load means the endpoint refuses connections for
    minutes. That is the normal state, not an error, and it must not escape."""
    assert job.count("requests.exceptions.RequestException") >= 2


def test_gpu_memory_utilisation_is_sane_in_the_rendered_args(job):
    """The rendered VLLM_ARGS carry whatever vllm.yaml supplied."""
    m = re.search(r"args\s*=\s*(\[[^\]]*\])", job)
    assert m, "vLLM args not rendered"
    assert "--gpu-memory-utilization" in m.group(1)


def test_shm_size_is_set(job):
    """Docker's 64 MB default shows up as a "Bus error" that reads like a model
    problem rather than a container one."""
    m = re.search(r"shm_size\s*=\s*(\d+)", job)
    assert m, "shm_size not set for the vLLM task"
    assert int(m.group(1)) >= 512_000_000


def test_budget_is_documented_honestly(root):
    """The header claims an arithmetic; this checks the claim is still true."""
    raw = (root / TEMPLATE).read_text(encoding="utf-8")
    job = strip_hcl_comments(render(root / TEMPLATE))
    cores = sum(_ints(job, "cores"))
    memory = sum(_ints(job, "memory"))
    assert f"cores : {cores} dedicated" in raw, (
        "the comment block no longer matches the resources below it"
    )
    assert str(memory) in raw
