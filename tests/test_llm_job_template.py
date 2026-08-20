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

    Upstream's helper tasks call their own PUBLIC HTTPS URL, which is served
    with our own CA's certificate. A stock python image does not trust it,
    `requests` raises, the script does not catch it, and because it is a
    prestart hook the whole allocation dies — with a traceback that never
    mentions certificates.

    Upstream's second helper, create-admin, had the same problem and is gone
    for a different reason; see the two tests below.
    """
    m = re.search(r'VLLM_ENDPOINT\s*=\s*"([^"]+)"', job)
    assert m, "VLLM_ENDPOINT not found in the template"
    assert m.group(1).startswith("http://"), (
        f"VLLM_ENDPOINT is {m.group(1)!r} — it must not go out through Traefik"
    )
    assert "NOMAD_ADDR_" in m.group(1), (
        "VLLM_ENDPOINT should address the allocation directly"
    )


def test_helper_scripts_survive_a_connection_error(job):
    """Waiting for a model to load means the endpoint refuses connections for
    minutes. That is the normal state, not an error, and it must not escape."""
    assert job.count("requests.exceptions.RequestException") >= 1


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


def test_the_chat_interface_does_not_leave_the_allocation_either(job):
    """R-05 applied to Open WebUI itself, which the original reading missed.

    The helper tasks above were fixed in Stage L2. Open WebUI was not, because
    its endpoint arrives from PAPI as ${API_ENDPOINT} rather than being written
    here — so nothing in this file looked wrong. What it produced was a
    deployment Nomad called healthy, a login that worked, and an empty model
    dropdown, with CERTIFICATE_VERIFY_FAILED visible only in stderr behind an
    HTTP 200. Patch 0010; render.py carries what PAPI now substitutes.
    """
    m = re.search(r'OPENAI_API_BASE_URL\s*=\s*"([^"]+)"', job)
    assert m, "OPENAI_API_BASE_URL not found in the template"
    url = m.group(1)
    assert url.startswith("http://"), (
        f"OPENAI_API_BASE_URL renders as {url!r} — a "
        "https:// hostname here means the UI is going back out through Traefik"
    )
    assert "NOMAD_ADDR_" in url, "the UI should address the allocation directly"


def test_a_standalone_ui_still_points_where_the_user_said(root):
    """The other half of 0010: only "both" is redirected.

    Deploying Open WebUI on its own, against an endpoint somewhere else, is a
    supported option on the form. Redirecting that into the allocation would
    point it at a vLLM task the deployment does not even contain.
    """
    from render import STANDALONE_UI_SUBS

    job = strip_hcl_comments(render(root / TEMPLATE, STANDALONE_UI_SUBS))
    m = re.search(r'OPENAI_API_BASE_URL\s*=\s*"([^"]+)"', job)
    assert m and m.group(1) == "https://someone-elses-llm.example.org/v1"


def test_ollama_is_switched_off(job):
    """Open WebUI probes host.docker.internal:11434 on every model listing.

    Nothing here serves Ollama, so that is a DNS lookup that cannot succeed on
    the first page a demo audience sees, plus a red ERROR line in the logs with
    no bearing on anything.
    """
    assert re.search(r"ENABLE_OLLAMA_API\s*=\s*false", job), (
        "ENABLE_OLLAMA_API is not disabled in the open-webui task"
    )


def test_the_admin_is_created_before_the_port_opens(job):
    """R-22, and the reason the create-admin task is gone.

    Open WebUI gives administrator to whoever registers first. Upstream claims
    that account with a poststart task POSTing to /api/v1/auths/signup once the
    UI is listening — so between the port opening and that POST landing, the
    account belongs to whoever asks. Stage L4 measured that window at 0-3
    seconds and then lost the race to it by accident: check-llm-ui.sh, polling
    the UI, registered itself as the administrator and the deployment's own
    credentials were refused afterwards.

    WEBUI_ADMIN_* is handled inside Open WebUI's FastAPI lifespan, which
    completes before uvicorn creates the listening socket. Zero window, rather
    than a small one.
    """
    for var, want in (
        ("WEBUI_ADMIN_EMAIL", "researcher@example.org"),
        ("WEBUI_ADMIN_PASSWORD", "hunter2"),
        ("WEBUI_ADMIN_NAME", "Test Researcher"),
    ):
        m = re.search(rf'{var}\s*=\s*"([^"]*)"', job)
        assert m, f"{var} is not set on the open-webui task"
        assert m.group(1) == want, (
            f"{var} renders as {m.group(1)!r} — it must carry what PAPI "
            f"substitutes, not a literal"
        )


def test_nothing_claims_the_admin_account_over_http(job):
    """The other half of R-22: create-admin could not have stayed.

    With an admin already present, Open WebUI answers 403 to signup. Upstream's
    script neither expects that nor gives up on it — it retries for fifteen
    minutes and then raises, and as a poststart hook that fails the allocation.
    So this is not a tidy-up: the two mechanisms are mutually exclusive.
    """
    assert "create-admin" not in job, "the create-admin task is still in the job"
    assert "auths/signup" not in job, (
        "something in this job still claims the admin account over HTTP"
    )
