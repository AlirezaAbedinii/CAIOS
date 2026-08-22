"""A deployment is not `running` until a user can open it.

Stage L4b. On 2026-08-21 the dashboard showed a green `running` badge and an
enabled *Quick access* button for **184 seconds** in front of a Traefik
`Bad Gateway`, and reported a deployment Nomad had merely queued as a red
`error` with an empty message. R-23, R-24, D-38, D-39.

Both faults are in `nomad_utils.py` and both are fixed by patch
`0011-deployment-readiness.patch`. The fixtures under `fixtures/nomad/` are
recorded from that incident, trimmed to the fields the code reads — the raw
Nomad JSON carries live credentials (R-09) and must never be committed.

Offline: the functions under test are pure, so they are lifted out of the
patched source with `ast` rather than imported. Importing `ai4papi.nomad_utils`
would pull in nomad, fastapi, requests and a config file, none of which belong
in a test that has to run in seconds.
"""

import ast
import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

HELPERS = ("unstarted_user_tasks", "deployment_is_ready", "placement_status")
PATCH = "0011-deployment-readiness.patch"


# --- loading the code under test -----------------------------------------


@pytest.fixture(scope="session")
def helpers(root):
    """The helpers, lifted from `vendor/` with the CAIOS patches applied.

    Patched into a temporary directory rather than read from `build/`, so the
    test always reflects the patch in the repository and never a stale build.
    """
    src = root / "vendor" / "ai4-papi"
    if not src.is_dir():
        pytest.skip("vendor/ai4-papi not cloned")
    patches = sorted((root / "patches" / "ai4-papi").glob("*.patch"))
    if not any(p.name == PATCH for p in patches):
        pytest.skip(f"{PATCH} not present")

    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp) / "ai4-papi"
        shutil.copytree(src, work, symlinks=True)
        for p in patches:
            subprocess.run(
                ["git", "-C", str(work), "apply", str(p)],
                check=True,
                capture_output=True,
            )
        source = (work / "ai4papi" / "nomad_utils.py").read_text(encoding="utf-8")

    tree = ast.parse(source)
    namespace = {}
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in HELPERS:
            module = ast.Module(body=[node], type_ignores=[])
            exec(compile(module, "<nomad_utils>", "exec"), namespace)

    missing = [name for name in HELPERS if name not in namespace]
    assert not missing, (
        f"{PATCH} no longer defines {missing}. If the helpers were renamed, "
        "rename them here too — do not delete the tests."
    )
    return namespace


@pytest.fixture(scope="session")
def fixtures(root):
    def load(name):
        return json.loads(
            (root / "tests" / "fixtures" / "nomad" / name).read_text(encoding="utf-8")
        )

    return load


# --- R-23: `running` must mean "you can open it" --------------------------


def test_llm_is_starting_while_open_webui_has_not_started(helpers, fixtures):
    """The 184-second window, as recorded.

    `open-webui` is the only task in the LLM job without a lifecycle block, and
    Nomad had not started it. `main` — which is what upstream reads — is vLLM,
    a prestart sidecar that was up and loading the model.
    """
    tasks = fixtures("tasks-llm.json")["Tasks"]
    alloc = fixtures("alloc-llm-loading.json")

    assert helpers["unstarted_user_tasks"](tasks, alloc) == ["open-webui"]


def test_llm_is_running_once_open_webui_has_started(helpers, fixtures):
    """The same deployment after 22:46:24, when the chat interface answered."""
    tasks = fixtures("tasks-llm.json")["Tasks"]
    alloc = fixtures("alloc-llm-ready.json")

    assert helpers["unstarted_user_tasks"](tasks, alloc) == []


def test_single_task_deployment_is_untouched(helpers, fixtures):
    """The no-op case, and the reason this change is safe to ship.

    Every module, the dev environment and the federated server have one task,
    named `main`, with no lifecycle block. It is a user task, it has started,
    and nothing about their status changes.
    """
    tasks = fixtures("tasks-single-task.json")["Tasks"]
    alloc = fixtures("alloc-single-task.json")

    assert helpers["unstarted_user_tasks"](tasks, alloc) == []


def test_a_pending_task_counts_as_unstarted(helpers, fixtures):
    """The live state at 22:43:20, which no snapshot survives.

    The recorded loading fixture was taken after the deployment was deleted, so
    its tasks read `dead`. While it was actually loading, `main` was `running`
    and `open-webui` was `pending`. The helper keys off StartedAt precisely so
    that the State string cannot mislead it.
    """
    tasks = fixtures("tasks-llm.json")["Tasks"]
    alloc = {
        "TaskStates": {
            "main": {"State": "running", "StartedAt": "2026-08-21T22:43:20.518Z"},
            "check_vllm_startup": {
                "State": "running",
                "StartedAt": "2026-08-21T22:43:20.020Z",
            },
            "open-webui": {"State": "pending", "StartedAt": None},
        }
    }

    assert helpers["unstarted_user_tasks"](tasks, alloc) == ["open-webui"]


def test_nomad_zero_time_is_not_a_start_time(helpers, fixtures):
    """Nomad serialises "never started" as null or as the Go zero time."""
    tasks = fixtures("tasks-llm.json")["Tasks"]
    alloc = {"TaskStates": {"open-webui": {"State": "pending", "StartedAt": "0001-01-01T00:00:00Z"}}}

    assert helpers["unstarted_user_tasks"](tasks, alloc) == ["open-webui"]


def test_a_missing_task_state_is_not_a_start_time(helpers, fixtures):
    """Nomad omits TaskStates entirely between placement and the first task."""
    tasks = fixtures("tasks-llm.json")["Tasks"]

    assert helpers["unstarted_user_tasks"](tasks, {}) == ["open-webui"]


# --- R-23, second half: a container starting is not a socket listening ----


def test_a_started_container_is_not_yet_ready(helpers, fixtures):
    """The 22 seconds the first fix did not close.

    Measured 2026-08-22: Nomad started the `open-webui` container at T+178 s
    and the first HTTP response came at T+200 s. Uvicorn opens its socket only
    after the FastAPI lifespan has created the administrator and closed signup
    (D-37), so "the container started" is still the wrong question.
    """
    tasks = fixtures("tasks-llm.json")["Tasks"]
    services = fixtures("services-llm.json")["Services"]
    alloc = {
        "TaskStates": {
            "main": {"State": "running", "StartedAt": "2026-08-22T02:10:00Z"},
            "check_vllm_startup": {"State": "dead", "StartedAt": "2026-08-22T02:07:00Z"},
            "open-webui": {"State": "running", "StartedAt": "2026-08-22T02:10:00Z"},
        },
        "DeploymentStatus": None,
    }

    assert helpers["deployment_is_ready"](tasks, services, alloc) is False


def test_ready_once_nomad_says_the_checks_pass(helpers, fixtures):
    tasks = fixtures("tasks-llm.json")["Tasks"]
    services = fixtures("services-llm.json")["Services"]
    alloc = dict(
        fixtures("alloc-llm-ready.json"),
        DeploymentStatus={"Healthy": True, "Canary": False},
    )

    assert helpers["deployment_is_ready"](tasks, services, alloc) is True


def test_a_group_without_checks_does_not_wait_for_a_health_signal(helpers, fixtures):
    """The wedge this must never cause.

    Nothing but the LLM tool defines checks. If the gate demanded
    DeploymentStatus.Healthy unconditionally, every module and workspace would
    sit at `starting` for as long as Nomad left that field absent — and the
    instrumented run on 2026-08-22 showed it absent, not False, for the whole
    of a deployment.
    """
    tasks = fixtures("tasks-single-task.json")["Tasks"]
    services = fixtures("services-single-task.json")["Services"]
    alloc = dict(fixtures("alloc-single-task.json"), DeploymentStatus=None)

    assert helpers["deployment_is_ready"](tasks, services, alloc) is True


def test_absent_deployment_status_is_not_healthy(helpers, fixtures):
    """`Healthy` is absent during the window, never False. Anything testing
    `is False` would have passed the tests and failed on the cluster."""
    tasks = fixtures("tasks-llm.json")["Tasks"]
    services = fixtures("services-llm.json")["Services"]
    ready = fixtures("alloc-llm-ready.json")

    for status in (None, {}, {"Healthy": None}, {"Healthy": False}):
        alloc = dict(ready, DeploymentStatus=status)
        assert helpers["deployment_is_ready"](tasks, services, alloc) is False, status


# --- R-24: "waiting" and "failed" are different words ---------------------


def test_blocked_evaluation_is_queued_not_error(helpers, fixtures):
    """Nomad had not refused this deployment. It placed it 47 seconds later."""
    evals = fixtures("evals-blocked.json")["Evaluations"]

    status, _ = helpers["placement_status"](evals)

    assert status == "queued"


def test_queued_message_says_what_ran_out(helpers, fixtures):
    """The detail is on the evaluation that has FailedTGAllocs, which is not
    evals[0] — that is the whole bug."""
    evals = fixtures("evals-blocked.json")["Evaluations"]

    _, msg = helpers["placement_status"](evals)

    assert "cpu" in msg
    assert "devices" in msg
    assert "free up" in msg, "a queued deployment must say it will start by itself"


def test_queued_message_is_never_empty(helpers, fixtures):
    """The regression, stated plainly.

    Upstream read `evals[0].get('FailedTGAllocs', '')`. This endpoint returns
    evaluations unordered and evals[0] was the *blocked* evaluation, which
    carries no FailedTGAllocs — so the badge was red and there was nothing
    beside it. A deployment 47 seconds from starting was deleted because of it.
    """
    evals = fixtures("evals-blocked.json")["Evaluations"]
    assert not evals[0].get("FailedTGAllocs"), (
        "fixture no longer reproduces the ordering that caused the bug"
    )

    _, msg = helpers["placement_status"](evals)

    assert msg.strip()
    assert msg.strip() not in {"None", "{}", "''"}


def test_unplaceable_evaluation_is_still_an_error(helpers, fixtures):
    """Without a BlockedEval, Nomad is not going to retry, and `error` is right."""
    evals = fixtures("evals-unplaceable.json")["Evaluations"]

    status, msg = helpers["placement_status"](evals)

    assert status == "error"
    assert msg.strip()


def test_an_evaluation_with_no_failure_yet_is_queued_not_error(helpers):
    """T+0, seen on the instrumented run of 2026-08-22.

    Between accepting a deployment and running the first scheduling pass, Nomad
    has an evaluation and no allocation and nothing has failed. Upstream called
    that `error`, so every deployment flashed red for its first second.
    """
    status, msg = helpers["placement_status"]([{"ID": "x", "Status": "pending"}])

    assert status == "queued"
    assert msg.strip()


def test_a_real_failure_with_no_detail_is_still_an_error(helpers):
    """Belt and braces: never hand the dashboard an empty string again."""
    status, msg = helpers["placement_status"](
        [{"ID": "x", "Status": "complete", "FailedTGAllocs": {"usergroup": {}}}]
    )

    assert status == "error"
    assert msg.strip()


# --- the patch has to stay wired in --------------------------------------


def test_patch_calls_both_helpers(root):
    """A helper nothing calls is a helper that silently stops mattering."""
    patch = (root / "patches" / "ai4-papi" / PATCH).read_text(encoding="utf-8")

    assert "+        if info[\"status\"] == \"running\" and not deployment_is_ready(" in patch
    assert '+        info["status"], info["error_msg"] = placement_status(evals)' in patch
    assert "-        info[\"status\"] = \"error\"" in patch, (
        "the unconditional error must be removed, not merely added around"
    )


# --- the fixtures must stay safe to commit -------------------------------


def test_fixtures_carry_no_credentials(root):
    """R-09: raw Nomad job and allocation JSON contains VLLM_API_KEY,
    WEBUI_ADMIN_PASSWORD, jupyterPASSWORD and Nomad token IDs in clear text.
    The fixtures are trimmed to the fields the code reads; this keeps them that
    way if anyone re-records them.
    """
    pattern = re.compile(r"(token|password|secret|api_key|_pass|_key)", re.I)
    offenders = []
    for path in sorted((root / "tests" / "fixtures" / "nomad").glob("*.json")):
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if pattern.search(line):
                offenders.append(f"{path.name}:{n}: {line.strip()}")

    assert not offenders, "re-record with only the fields under test:\n" + "\n".join(
        offenders
    )
