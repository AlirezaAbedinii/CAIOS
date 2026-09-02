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
