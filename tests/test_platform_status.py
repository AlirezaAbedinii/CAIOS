"""The dashboard does not read another project's status feed.

R-38. Upstream hardcodes AI4EOSC's GitHub issue tracker as the source of the
startup popup, the notifications bell and the red maintenance banner on the
deployments list, and reads it from the visitor's browser on every page load.
Two consequences, and the less exotic one is the rate limit: GitHub allows 60
unauthenticated requests an hour per IP address, the dashboard spends two of
them per full page load, and past that the user gets a red error toast instead
of a dashboard.

Patch 0005 makes the source configuration and off when unset. These tests read
the repository; scripts/check-branding.sh does the live half, and has to — the
only way to know what a running dashboard fetches is to look at what it serves.
"""

import json

import pytest

PATCH = "patches/ai4-dashboard/0005-platform-status-source.patch"
TENANT = "configs/dashboard/caios.json"
CHECK = "scripts/check-branding.sh"
UPSTREAM_URL = "https://api.github.com/repos/AI4EOSC/status/issues"


@pytest.fixture(scope="module")
def patch(root):
    p = root / PATCH
    if not p.is_file():
        pytest.skip("0005 not present")
    return p.read_text(encoding="utf-8")


def test_the_hardcoded_tracker_is_removed_not_merely_guarded(patch):
    """All three call sites, not one. The bell and the popup share a method;
    the deployments banner does not, and it is the one that paints red."""
    removed = [
        line
        for line in patch.splitlines()
        if line.startswith("-") and UPSTREAM_URL in line
    ]
    assert len(removed) >= 3, (
        f"expected the URL to be removed from all three service methods, "
        f"found {len(removed)} removals"
    )


def test_unset_means_no_request_rather_than_a_default(patch):
    """The distinction the whole change turns on. A default of "" that still
    calls the URL, or a getter that falls back to upstream's tracker, would
    leave every symptom in place while looking fixed."""
    assert "if (!this.statusIssuesUrl) {" in patch
    assert "return of([]);" in patch, (
        "an unconfigured feed must return an empty list, not make a request"
    )
    assert "this.appConfig.platformStatusUrl ?? ''" in patch, (
        "the config getter must fall back to empty, never to a URL"
    )


def test_the_interceptor_no_longer_names_another_project(patch):
    """The guard is still wanted — a status feed answering 403 must not throw
    the user onto the Forbidden page — but it should not be spelled with
    somebody else's repository in it."""
    assert f"-                            '{UPSTREAM_URL}'" in patch
    assert "+                        !error.url?.includes('/status/issues')" in patch


def test_upstream_tests_still_exercise_the_fetch_path(patch):
    """A change that switches a feature off and lets its tests pass by never
    running is not a tested change. The mock keeps the configured path covered,
    and a new test covers the unconfigured one."""
    assert "platformStatusUrl: 'https://api.github.com/repos/AI4EOSC/status/issues'" in patch, (
        "app-config.mock.ts must supply a URL or upstream's three tests stop "
        "testing anything"
    )
    assert "makes no request at all when no status URL is configured" in patch


def test_the_tenant_sets_the_key_blank_rather_than_omitting_it(root):
    """Present-and-empty, not absent. `scripts/check-branding.sh` reads the
    served config and can tell "off" from "nobody thought about it" only if the
    key is there — the same reason the analytics keys are blanked rather than
    deleted."""
    conf = json.loads((root / TENANT).read_text(encoding="utf-8"))
    assert "platformStatusUrl" in conf, (
        "the key must be present so the served config states the decision"
    )
    assert conf["platformStatusUrl"] == "", (
        "blank means off; a URL here means the feature is on and pointed "
        "somewhere, which is a decision to make deliberately"
    )


def test_the_branding_check_covers_both_halves(root):
    """Either half can be true while the feature still fires: a blank config
    key with an unpatched bundle still fetches, and a patched bundle with a URL
    configured still fetches. Both are checked."""
    script = (root / CHECK).read_text(encoding="utf-8")
    assert "platformStatusUrl" in script, (
        "check-branding.sh does not read the served platformStatusUrl"
    )
    assert "api.github.com/repos/AI4EOSC/status" in script, (
        "check-branding.sh does not assert the bundle stopped naming the tracker"
    )
