"""A deployment that crashes must say so, not disappear.

Found 2026-09-02 by reproducing a report that a deployment "goes starting, then
running, then vanishes". Both halves of that were real and separate:

  * **Why it died.** Every module image ships a `deep-start` that launches
    JupyterLab as root *without* `--allow-root`. Jupyter refuses, the container
    exits 1, Nomad retries twice and gives up. Reproduced directly:
    `docker run ai4oshub/posenet-tf:latest deep-start --jupyter` prints
    "Running as root is not recommended. Use --allow-root to bypass."

  * **Why it vanished.** `nomad_utils.get_deployments()` filters
    `Status != "dead"`, which hides a deployment the user deleted and a
    deployment that died by itself equally. Three abandoned `posenet-tf` jobs
    had accumulated in Nomad, invisible in the dashboard, with nothing anywhere
    saying anything had gone wrong.

Patch `0015` fixes the second; `configs/papi/modules-user.yaml` removes the
option that triggers the first. These tests hold both.

Offline: they read the repository and the patch, never a running PAPI. The live
half is `scripts/check-deployments.sh`.
"""

from pathlib import Path
import re

import pytest
import yaml

PATCH = "patches/ai4-papi/0015-failed-deployments-visible.patch"
MODULES_CONF = "configs/papi/modules-user.yaml"
DEVENV_CONF = "configs/papi/tools/ai4os-dev-env/user.yaml"


@pytest.fixture(scope="module")
def patch(root):
    return (root / PATCH).read_text(encoding="utf-8")


# --- the deployment stops disappearing --------------------------------------


def test_the_dead_filter_no_longer_hides_crashes(patch):
    """`Stop` is what separates "deleted" from "died"."""
    assert "-        'Status != \"dead\" and '" in patch, (
        "the upstream filter line is not being replaced"
    )
    assert "+        '(Status != \"dead\" or Stop == false) and '" in patch


def test_a_failure_carries_a_reason(patch):
    """`failed` with an empty message is only marginally better than nothing.

    Nomad's task event stream already holds "Exit Code: 1, Exit Message: ...";
    upstream set `error_msg` only for placement failures, so a container that
    started and then died reached the dashboard as a bare "failed".
    """
    assert "_task_failure_reason" in patch
    assert "TaskStates" in patch
    assert "Terminated" in patch, "the event carrying the exit code is not read"


def test_a_dead_job_is_never_reported_as_queued(patch):
    """The garbage-collected case.

    Once Nomad GCs the allocations there is nothing left to read a reason from,
    and upstream fell through to `queued` — which tells the user the deployment
    is about to start when in fact it is over. Two of the three abandoned jobs
    were in exactly this state.
    """
    assert 'j.get("Status") == "dead" and not j.get("Stop")' in patch
    assert '+        info["status"] = "failed"' in patch


def test_reason_helper_is_honest_about_knowing_nothing(patch):
    """It returns "" rather than inventing a cause, and the caller leaves the
    field alone. Same rule as D-50: an absent value is a state."""
    assert 'return " | ".join(reasons)' in patch
    assert 'if info["status"] == "failed" and not info.get("error_msg")' in patch


# --- the option that always crashed is not offered --------------------------


def _conf(root, path):
    # These files are two YAML documents: the full form, then the values.
    return list(yaml.safe_load_all((root / path).read_text(encoding="utf-8")))[0]


def test_modules_do_not_offer_jupyter(root):
    """Measured: it crashes on every module image in the catalogue.

    Offering an option that cannot work is worse than not offering it — the
    user gets a deployment that dies two minutes later for a reason the
    interface never mentions.
    """
    svc = _conf(root, MODULES_CONF)["general"]["service"]
    assert svc["options"] == ["deepaas"], (
        f"modules still offer {svc['options']} — jupyter does not work on any "
        "module image (no --allow-root in their deep-start)"
    )
    assert svc["value"] == "deepaas"


def test_the_module_service_description_points_somewhere_that_works(root):
    """Removing an option without saying where to go instead is a dead end."""
    desc = _conf(root, MODULES_CONF)["general"]["service"]["description"].lower()
    assert "development environment" in desc or "dev-env" in desc, (
        "the description should send a user wanting a notebook to the tool that "
        "actually provides one"
    )


def test_the_dev_env_still_offers_an_interactive_workspace(root):
    """The high-code path. Verified in a browser on 2026-09-02: JupyterLab
    loads, accepts the password and runs a terminal."""
    svc = _conf(root, DEVENV_CONF)["general"]["service"]
    assert "jupyter" in svc["options"]
    assert "vscode" in svc["options"]


def test_the_reason_jupyter_was_removed_is_written_down(root):
    """A bare `options: ['deepaas']` invites someone to add jupyter back.

    The measurement that justifies it has to live next to the line it explains,
    or this is a one-line regression waiting to happen.
    """
    text = (root / MODULES_CONF).read_text(encoding="utf-8")
    block = text[: text.index("service:")]
    tail = text[text.index("service:") - 1200 : text.index("service:")]
    assert "allow-root" in tail, "no explanation of why jupyter is absent"
    assert block is not None


# --- loading quotas.py without PAPI's dependency tree ----------------------
#
# These tests run offline, like the rest of this file. quotas.py imports
# fastapi and ai4papi.conf, neither of which the test venv has and neither of
# which the function under test uses for anything but raising. Stubbing them is
# what keeps this a test of the real code rather than of a copy of it.


def _load_quotas():
    import importlib.util
    import sys
    import types

    src = Path(__file__).resolve().parent.parent / "build" / "ai4-papi" / "ai4papi" / "quotas.py"
    if not src.is_file():
        return None

    saved = {k: sys.modules.get(k) for k in ("fastapi", "ai4papi", "ai4papi.conf")}

    fastapi = types.ModuleType("fastapi")

    class HTTPException(Exception):
        def __init__(self, status_code=400, detail=""):
            super().__init__(detail)
            self.status_code = status_code
            self.detail = detail

    fastapi.HTTPException = HTTPException
    sys.modules["fastapi"] = fastapi

    pkg = types.ModuleType("ai4papi")
    pkg.__path__ = []
    conf = types.ModuleType("ai4papi.conf")
    pkg.conf = conf
    sys.modules["ai4papi"] = pkg
    sys.modules["ai4papi.conf"] = conf

    try:
        spec = importlib.util.spec_from_file_location("caios_quotas", src)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    finally:
        for k, v in saved.items():
            if v is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = v

# --- the other half of patch 0015 -----------------------------------------
#
# Making a failed deployment visible put it in front of code that assumed every
# deployment has an allocation. A failed one does not, so its `resources` is
# empty — and the GPU quota check indexed straight into it. Any user with one
# failed deployment in their history could then create no new deployment at
# all: HTTP 500 on every POST, with a KeyError in the log and nothing in the
# dashboard beyond "Error".
#
# Found on 2026-09-02 by trying to deploy a workspace on a cluster with three
# old failed jobs in it. Patch 0017.


def test_quota_tolerates_a_deployment_with_no_resources():
    """A deployment that is not running holds no GPU. Zero, not a crash."""
    quotas = _load_quotas()
    if quotas is None:
        import pytest

        pytest.skip("build/ai4-papi absent — run scripts/apply-patches.sh")

    deployments = [
        {"job_ID": "failed-one", "status": "error", "resources": {}},
        {"job_ID": "no-key-at-all", "status": "error"},
        {"job_ID": "running-cpu", "status": "running", "resources": {"gpu_num": 0}},
        {"job_ID": "running-gpu", "status": "running", "resources": {"gpu_num": 1}},
    ]
    # One GPU in use, one requested, threshold of two: this must be allowed.
    quotas.check_userwise(
        conf={"hardware": {"gpu_num": 1}},
        deployments=deployments,
    )


def test_quota_still_refuses_a_third_gpu():
    """The guard the crash was hiding must still work."""
    import pytest

    quotas = _load_quotas()
    if quotas is None:
        pytest.skip("build/ai4-papi absent — run scripts/apply-patches.sh")

    deployments = [
        {"job_ID": "a", "status": "running", "resources": {"gpu_num": 1}},
        {"job_ID": "b", "status": "running", "resources": {"gpu_num": 1}},
        {"job_ID": "dead", "status": "error", "resources": {}},
    ]
    with pytest.raises(Exception) as excinfo:
        quotas.check_userwise(
            conf={"hardware": {"gpu_num": 1}},
            deployments=deployments,
        )
    assert "2 GPUs" in str(excinfo.value)
