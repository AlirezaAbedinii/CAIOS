"""The dashboard's LLM model cards come from CAIOS, and agree with PAPI's form.

R-07. Upstream's dashboard fetches AI4OS's own `vllm.yaml` from
raw.githubusercontent.com, so the model CARDS came from their list of thirteen
while the deploy form's DROPDOWN came from our PAPI's curated nine. The two
disagreed about what exists, what it is called, and whether it needs a Hugging
Face token.

These tests are offline: they read the repository, not the running dashboard.
scripts/check-branding.sh does the live half, and has to, because every missing
asset under the dashboard answers 200 with index.html.
"""

import re

import pytest
import yaml

CATALOGUE = "configs/papi/vllm.yaml"
PATCH = "patches/ai4-dashboard/0002-vllm-catalogue-url.patch"
BUILD_SCRIPT = "scripts/build-dashboard.sh"
STAGED = "build/ai4-dashboard/src/assets/config/vllm.yaml"
SERVICE = "src/app/modules/catalog/services/tools-service/tools.service.ts"


@pytest.fixture(scope="module")
def catalogue(root):
    return yaml.safe_load((root / CATALOGUE).read_text(encoding="utf-8"))["models"]


def test_the_catalogue_url_is_no_longer_a_third_party_fetch(root):
    """The whole of patch 0002, stated as an assertion."""
    patch = root / PATCH
    if not patch.is_file():
        pytest.skip("0002 not present")
    text = patch.read_text(encoding="utf-8")
    assert "-            'https://raw.githubusercontent.com/ai4os/ai4-papi" in text, (
        "the GitHub URL should be removed, not merely added around"
    )
    assert "+        const url = '/assets/config/vllm.yaml';" in text, (
        "the replacement must be an asset this deployment serves"
    )


def test_the_build_stages_the_catalogue_the_patch_points_at(root):
    """A patch pointing at an asset nobody stages is a 404 — and under this
    dashboard a 404 is an HTTP 200 carrying index.html, which js-yaml then
    parses into something shapeless rather than throwing."""
    script = (root / BUILD_SCRIPT).read_text(encoding="utf-8")
    assert re.search(
        r'cp\s+configs/papi/vllm\.yaml\s+"\$DST/src/assets/config/vllm\.yaml"', script
    ), f"{BUILD_SCRIPT} does not stage the file patch 0002 asks for"


def test_the_staged_catalogue_is_the_one_papi_reads(root, catalogue):
    """One file, two consumers. If build/ has been produced, the copy in it must
    still be the same list — not a stale one from an earlier curation."""
    staged = root / STAGED
    if not staged.is_file():
        pytest.skip("build/ai4-dashboard not built yet")
    served = yaml.safe_load(staged.read_text(encoding="utf-8"))["models"]
    assert list(served) == list(catalogue), (
        "the staged catalogue and configs/papi/vllm.yaml have drifted apart"
    )


def test_every_model_has_what_a_card_renders(catalogue):
    """VllmModelConfig in the dashboard declares these non-optional, and a
    missing one renders as the literal word "undefined" on the card rather than
    as an error anyone would notice."""
    for model_id, model in catalogue.items():
        for field in ("name", "description", "family", "license", "context"):
            assert model.get(field), f"{model_id} has no {field}"
        assert isinstance(model.get("needs_HF_token"), bool), (
            f"{model_id}: needs_HF_token must be a boolean — the form reads it "
            f"to decide whether the Hugging Face field is required"
        )


def test_no_model_in_our_catalogue_needs_a_hugging_face_token(catalogue):
    """D-32 and the L5 gate: the gated Llama models are dropped from our list,
    so the token field should never become required. If this fails, the demo
    has a form field that must be filled in and nobody has a token."""
    gated = [k for k, m in catalogue.items() if m.get("needs_HF_token")]
    assert not gated, f"these need a Hugging Face token: {gated}"
