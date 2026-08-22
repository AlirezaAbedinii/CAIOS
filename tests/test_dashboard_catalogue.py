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


def test_the_model_id_is_not_rebuilt_from_display_fields(root):
    """Patch 0003.

    Upstream carried only `family` and `name` and reconstructed the model id as
    `family + '/' + name` in three places: the card click that preselects the
    deploy dropdown, the "Card" chip that opens Hugging Face, and the
    `needs_HF_token` lookup. That is only correct when the Hugging Face
    organisation happens to equal the family label.
    """
    patch = root / "patches" / "ai4-dashboard" / "0003-vllm-model-id.patch"
    if not patch.is_file():
        pytest.skip("0003 not present")
    text = patch.read_text(encoding="utf-8")

    # The reconstruction is removed, not merely added around.
    for removed in (
        "-            state: { llmId: this.llm.family + '/' + this.llm.name },",
        "-                (m) => m.family + '/' + m.name === model",
    ):
        assert removed in text, f"still present: {removed.lstrip('-').strip()}"

    # The key stops being discarded: it is destructured as `id` and spread last.
    assert "-                        name, // model name" in text, (
        "the line that let config.name overwrite the key is still there"
    )
    assert "+                    ([id, config]) => ({" in text
    assert "+                        id," in text, (
        "the service must keep the YAML key as the model id"
    )


def test_no_model_id_can_be_rebuilt_from_family_and_name(catalogue):
    """The data half of the same bug, and the reason it is not theoretical.

    This asserts the catalogue CONTAINS entries where the reconstruction fails,
    which reads backwards until you see why: if every model here happened to
    agree, patch 0003 would look like a refactor and someone would drop it. Two
    of our nine disagree, and both are models the demo can offer.
    """
    mismatched = [
        model_id
        for model_id, m in catalogue.items()
        if f"{m['family']}/{m['name']}" != model_id
    ]
    assert mismatched, (
        "no model in the catalogue distinguishes id from family/name any more. "
        "If that is deliberate, patch 0003 is still correct — the id is the id "
        "— but this test no longer proves anything and should say so."
    )
    for model_id in mismatched:
        assert "/" in model_id, f"{model_id} is not a Hugging Face model id"



def test_every_card_asks_for_a_logo_that_exists(root, catalogue):
    """`family` is also an image filename: assets/images/llm-companies/
    {family}_logo.png. A family with no logo renders a broken image on the card,
    and because every missing path under this dashboard answers 200 with
    index.html, nothing anywhere reports it."""
    families = sorted({m["family"] for m in catalogue.values()})
    logos = root / "configs" / "dashboard" / "images" / "llm-companies"
    upstream = root / "vendor" / "ai4-dashboard" / "src" / "assets" / "images" / "llm-companies"
    missing = [
        f
        for f in families
        if not (logos / f"{f}_logo.png").is_file()
        and not (upstream / f"{f}_logo.png").is_file()
    ]
    assert not missing, (
        f"no card logo for {missing}. Generate them with "
        f"scripts/make-brand-assets.py, or the cards render a broken image."
    )
