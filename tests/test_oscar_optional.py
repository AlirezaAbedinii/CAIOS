"""An unconfigured feature is not a server error.

Stage O0. PAPI's OSCAR router is mounted unconditionally
(`routers/v1/__init__.py`) and the dashboard hardcodes a sidenav link to
`/tasks/inference` (`sidenav.component.ts`, confirmed present in the served
bundle). We run no OSCAR cluster (D-09), so `main.yaml` has no `oscar` block
and `MAIN_CONF["oscar"]["clusters"][vo]` raises `KeyError` — which reaches a
logged-in researcher as a bare **HTTP 500** on a page they can reach from the
menu today.

Measured on the live cluster on 2026-08-25, before the fix:

    /v1/inference/oscar/cluster    HTTP 500
    /v1/inference/oscar/services   HTTP 500

`0012-oscar-optional.patch` makes the listing return `[]` and the rest return
501 with a sentence. Same shape as `0004-stats-without-wattnet.patch`, which
did this for `ACCOUNTING_PTH`, and the same principle as D-39: "waiting" and
"failed" are different words.

Offline: the two helpers are pure, so they are lifted out of the patched source
with `ast` rather than imported. Importing the router would pull in fastapi,
oscar_python, requests and a config file.
"""

import ast
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

HELPERS = ("oscar_cluster_conf", "require_oscar")
PATCH = "0012-oscar-optional.patch"
SOURCE = ("ai4papi", "routers", "v1", "inference", "oscar.py")

VO = "vo.caios.ca"


class FakeHTTPException(Exception):
    """Stand-in for fastapi.HTTPException, which we do not import here."""

    def __init__(self, status_code, detail):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


class FakePapiconf:
    """`papiconf` as the helpers use it: one attribute, MAIN_CONF."""

    def __init__(self, main_conf):
        self.MAIN_CONF = main_conf


# --- loading the code under test -----------------------------------------


@pytest.fixture(scope="session")
def patched_source(root):
    """`oscar.py` with every CAIOS patch applied, as text.

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
        return (work.joinpath(*SOURCE)).read_text(encoding="utf-8")


@pytest.fixture
def helpers(patched_source):
    """The two helpers, with `papiconf` and `HTTPException` injected.

    Function-scoped: each test sets its own MAIN_CONF through
    `helpers["_set_conf"]`, so they must not share a namespace.
    """
    tree = ast.parse(patched_source)
    namespace = {"HTTPException": FakeHTTPException}

    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in HELPERS:
            module = ast.Module(body=[node], type_ignores=[])
            exec(compile(module, "<oscar>", "exec"), namespace)

    missing = [name for name in HELPERS if name not in namespace]
    assert not missing, (
        f"{PATCH} no longer defines {missing}. If the helpers were renamed, "
        "rename them here too — do not delete the tests."
    )

    def set_conf(main_conf):
        namespace["papiconf"] = FakePapiconf(main_conf)

    namespace["_set_conf"] = set_conf
    set_conf({})
    return namespace


# --- the state CAIOS is actually in --------------------------------------


def test_no_oscar_block_at_all_is_none_not_keyerror(helpers):
    """Our `main.yaml` has no `oscar:` key. This is the live case."""
    helpers["_set_conf"]({"nomad": {}, "lb": {}})
    assert helpers["oscar_cluster_conf"](VO) is None


def test_oscar_block_without_our_vo_is_none(helpers):
    """Upstream's file has clusters for four VOs, none of them ours."""
    helpers["_set_conf"](
        {"oscar": {"clusters": {"vo.ai4eosc.eu": {"endpoint": "https://x", "cluster_id": "y"}}}}
    )
    assert helpers["oscar_cluster_conf"](VO) is None


def test_empty_cluster_entry_is_treated_as_unconfigured(helpers):
    """A half-written config is not a working one.

    `.get(vo)` returns `{}` here rather than None, so the property that matters
    is falsiness — which is what `require_oscar` actually branches on.
    """
    helpers["_set_conf"]({"oscar": {"clusters": {VO: {}}}})
    assert not helpers["oscar_cluster_conf"](VO)
    with pytest.raises(FakeHTTPException) as exc:
        helpers["require_oscar"](VO)
    assert exc.value.status_code == 501


# --- what a user gets -----------------------------------------------------


def test_unconfigured_raises_501_not_500(helpers):
    """501 Not Implemented. A 500 reads as "we broke"; this cluster simply
    does not offer the feature."""
    helpers["_set_conf"]({})
    with pytest.raises(FakeHTTPException) as exc:
        helpers["require_oscar"](VO)
    assert exc.value.status_code == 501, (
        "500 is what upstream produces by accident, and it is the thing this "
        "patch exists to stop."
    )


def test_the_message_says_which_feature_and_which_vo(helpers):
    """R-24's lesson: an empty or generic message costs a deployment. The
    message has to be actionable on its own."""
    helpers["_set_conf"]({})
    with pytest.raises(FakeHTTPException) as exc:
        helpers["require_oscar"](VO)
    detail = exc.value.detail
    assert "OSCAR" in detail
    assert VO in detail
    assert detail.strip(), "an empty detail is what made R-24 expensive"


# --- and it must stay a no-op once OSCAR is real --------------------------


def test_configured_cluster_is_returned_unchanged(helpers):
    """Stage O3 adds this block. The guard must then get out of the way."""
    cluster = {"endpoint": "https://oscar.example", "cluster_id": "oscar-caios-cluster"}
    helpers["_set_conf"]({"oscar": {"clusters": {VO: cluster}}})
    assert helpers["oscar_cluster_conf"](VO) == cluster
    assert helpers["require_oscar"](VO) == cluster


# --- source-level guarantees ----------------------------------------------


def test_services_listing_returns_empty_rather_than_raising(patched_source):
    """The dashboard calls `/services` when the Inference page opens, so this
    one endpoint must degrade to an empty list, not to a status code."""
    assert "if not oscar_cluster_conf(vo):\n        return []" in patched_source, (
        "get_services_list must early-return [] when OSCAR is unconfigured, or "
        "the Inference page shows an error bar instead of an empty table."
    )


def test_client_still_receives_cluster_id_and_endpoint(patched_source):
    """The refactor must not drop what oscar_python needs."""
    assert '"cluster_id": cluster["cluster_id"]' in patched_source
    assert '"endpoint": cluster["endpoint"]' in patched_source
    assert '"oidc_token": token' in patched_source, (
        "PAPI passes the user's own Keycloak token straight through; that is "
        "the whole auth integration."
    )


def test_upstream_direct_indexing_is_gone(patched_source):
    """The KeyError path must be removed, not merely guarded elsewhere."""
    assert 'papiconf.MAIN_CONF["oscar"]["clusters"][vo]["cluster_id"]' not in patched_source


def test_service_definition_is_guarded_too(patched_source):
    """The gap this suite found on 2026-08-25.

    `create_service` calls `make_service_definition(user_conf, vo)` BEFORE
    `get_client_from_auth`, and that function reads the cluster id directly.
    Guarding only the client path left `POST /services` raising KeyError -> 500
    exactly as before, with every unit test green.
    """
    assert '"CLUSTER_ID": require_oscar(vo)["cluster_id"]' in patched_source, (
        "make_service_definition must go through require_oscar, or create_service "
        "500s before the guard on the client path is ever reached."
    )
