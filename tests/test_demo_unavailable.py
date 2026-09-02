"""Features this deployment does not run say so, rather than failing.

T4, and the supervisor's checklist item 3. The dashboard is built for a platform
with Nextcloud, MLflow, a LiteLLM gateway and a Harbor registry. CAIOS runs none
of them, and upstream renders their pages anyway.

The urgent one was **Profile -> API Keys**. `/v1/llm/api_keys` proxies to
AI4EOSC's LiteLLM (hardcoded in `routers/v1/llm/keys.py`), which answers 401,
and the error interceptor navigated the browser to

    /forbidden;errorMessage=Error: {"error":{"message":"Authentication Error,
    LiteLLM Virtual Key expected. Received=****, expected to start with 'sk-'."}}

— another platform's internal error, in our URL bar, on a page that says
Forbidden. One click from the profile menu.

Patch `0007` replaces such a surface's body with one sentence. Which surfaces
is a list in the tenant config, so the day a service exists it is one line to
turn back on. D-50 again: an absent optional feature is a state, not a failure.

The patch also removes two deploy targets outright, because they are not
features this platform lacks — they are offers it should never make.

All offline: these read the repository. The live half is a browser pass.
"""

import json
import re

import pytest

PATCH = "patches/ai4-dashboard/0007-demo-unavailable.patch"
TENANT = "configs/dashboard/caios.json"
STRINGS = "configs/dashboard/i18n/en.caios.json"

# The three whose backing service is genuinely not deployed.
EXPECTED_UNAVAILABLE = {"apikeys", "storage", "services"}


def _strip_comments(o):
    if isinstance(o, dict):
        return {
            k: _strip_comments(v) for k, v in o.items() if not k.startswith("_comment")
        }
    return o


@pytest.fixture(scope="module")
def patch(root):
    return (root / PATCH).read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def tenant(root):
    return _strip_comments(json.loads((root / TENANT).read_text(encoding="utf-8")))


@pytest.fixture(scope="module")
def strings(root):
    return _strip_comments(json.loads((root / STRINGS).read_text(encoding="utf-8")))


# --- the notice exists and is configured ------------------------------------


def test_the_sentence_exists_and_says_what_the_supervisor_asked_for(strings):
    msg = strings["DEMO"]["UNAVAILABLE"]
    assert "Not included in the Demo Version" in msg, (
        "the checklist asks for this exact phrase"
    )
    # It must also say WHY, or it reads as a feature that is coming rather than
    # one that is deliberately absent.
    assert "not running" in msg.lower()


def test_the_unavailable_surfaces_are_the_ones_with_no_backing_service(tenant):
    assert set(tenant["demoUnavailable"]) == EXPECTED_UNAVAILABLE


def test_overview_is_not_disabled(tenant):
    """The one profile tab that works entirely from the token."""
    assert "overview" not in tenant["demoUnavailable"]


def test_the_list_is_present_even_when_it_would_be_empty(root):
    """Present-and-explicit rather than absent, the same rule the analytics and
    platform-status keys follow: the served config should state the decision
    rather than leave it to a default."""
    raw = json.loads((root / TENANT).read_text(encoding="utf-8"))
    assert "demoUnavailable" in raw
    assert any(k.startswith("_comment") and "demo" in k.lower() for k in raw)


# --- the patch does what the config implies ---------------------------------


def test_config_service_defaults_to_showing_everything(patch):
    """An unset list must behave exactly as upstream, so the patch is safe for
    a flavour that runs all of these services."""
    assert "get demoUnavailable(): string[]" in patch
    assert "return this.appConfig.demoUnavailable ?? [];" in patch


def test_the_notice_is_rendered_before_the_tab_body(patch):
    """Rendering it *instead of* the body is what prevents the request that
    caused the ejection — a disabled control would still have mounted the
    component and called the API."""
    assert "isDemoUnavailable(activeTab)" in patch
    assert "'DEMO.UNAVAILABLE' | translate" in patch


def test_the_ejection_is_recorded_where_someone_will_read_it(patch):
    """The comment has to survive, or the next person removes the guard."""
    assert "forbidden" in patch.lower()
    assert "litellm" in patch.lower()


# --- two deploy targets removed, not annotated ------------------------------


def test_the_eu_node_deploy_target_is_gone(patch):
    """European infrastructure offered on a platform whose argument is that the
    data stays in Canada. Not a missing feature — a wrong offer."""
    assert "-" in patch
    removed = "\n".join(l[1:] for l in patch.splitlines() if l.startswith("-"))
    assert "eosc-node.html" in removed
    assert "CATALOG.MODULE-DETAIL.DEPLOY.EU-NODE" in removed


def test_the_infrastructure_manager_deploy_target_is_gone(patch):
    removed = "\n".join(l[1:] for l in patch.splitlines() if l.startswith("-"))
    assert "im.egi.eu" in removed


def test_the_two_working_deploy_targets_are_untouched(patch):
    """OSCAR serverless is the low-code use case and Nomad is the high-code
    one. A patch that removed either would break the demo."""
    removed = "\n".join(l[1:] for l in patch.splitlines() if l.startswith("-"))
    assert "trainModulePlatform('oscar')" not in removed
    assert "trainModulePlatform('nomad')" not in removed


# --- the strings a visitor reads --------------------------------------------


def test_the_statistics_heading_does_not_name_another_project(strings):
    assert "AI4EOSC" not in strings["DASHBOARD"]["USAGE"]


def test_the_catalogue_card_labels_do_not_say_ai4(strings):
    for key in ("MODULE", "TOOL"):
        assert not re.search(r"\bAI4\b", strings["CATALOG"][key]), (
            f"CATALOG.{key} still says AI4 — it is the type label on every card"
        )


def test_the_marketplace_tab_is_named_after_this_platform(patch, strings):
    """`<mat-tab label="AI4EOSC">` was a hardcoded literal, not a translation
    key, so it could not be overridden in en.caios.json like the others."""
    removed = "\n".join(l[1:] for l in patch.splitlines() if l.startswith("-"))
    assert 'label="AI4EOSC"' in removed
    assert strings["CATALOG"]["TABS"]["PLATFORM"] == "CAIOS"


def test_ai4life_is_deliberately_not_renamed(strings):
    """AI4Life is the real name of the bioimage.io model zoo project, so naming
    it is accurate attribution rather than upstream residue. This test exists so
    a future sweep does not "fix" it."""
    catalog = strings.get("CATALOG", {})
    assert "AI4LIFE" not in catalog, (
        "AI4Life should keep its own name — it is a real external project"
    )
