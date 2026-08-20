"""Every model we offer fits in the GPU we have, and is described well enough
for the dashboard to render a card for it.

The failure this prevents: a user picks a model from the dropdown, waits four
minutes for 7 GB of weights to download, and vLLM dies with a CUDA
out-of-memory error that reads as if the model is broken.
"""

import pytest
import yaml

from conftest import GPU_FREE_MIB, GPU_TOTAL_MIB, VLLM_OVERHEAD_MIB

CATALOGUE = "configs/papi/vllm.yaml"

# Real `.safetensors` totals from the Hugging Face API, measured 2026-08-19,
# excluding duplicate `consolidated.*` files. In MiB.
WEIGHTS_MIB = {
    "Qwen/Qwen3.5-2B": 4339,
    "Qwen/Qwen3.5-0.8B": 1669,
    "mistralai/Ministral-3-3B-Instruct-2512": 4454,
    "LiquidAI/LFM2.5-1.2B-Instruct": 2232,
    "LiquidAI/LFM2.5-1.2B-Thinking": 2232,
    "LiquidAI/LFM2.5-VL-450M": 858,
    "LiquidAI/LFM2.5-VL-1.6B": 3042,
    "ibm-granite/granite-4.1-3b": 6495,
    "deepseek-ai/DeepSeek-R1-Distill-Qwen-1.5B": 3386,
}

# Models measured too large for this GPU. Offering one is worse than not
# offering it: the failure happens minutes in, after a long download.
KNOWN_TOO_BIG = {
    "mistralai/Ministral-3-3B-Reasoning-2512",
    "ibm-granite/granite-vision-4.1-4b",
}

# Gated models need a Hugging Face token, which the deploy form stores in clear
# text in the Nomad job (docs/llm-risks.md R-09).
KNOWN_GATED = {
    "meta-llama/Llama-3.2-3B",
    "meta-llama/Llama-3.2-3B-Instruct",
}

REQUIRED_KEYS = {"name", "description", "family", "license", "context", "needs_HF_token", "args"}


@pytest.fixture(scope="module")
def models(root):
    with open(root / CATALOGUE, encoding="utf-8") as f:
        return yaml.safe_load(f)["models"]


def _arg(args, flag):
    return args[args.index(flag) + 1] if flag in args else None


def test_catalogue_is_not_empty(models):
    assert len(models) >= 3


def test_every_model_has_what_the_dashboard_renders(models):
    """The LLM catalogue page builds a card per model from exactly these keys."""
    for model_id, cfg in models.items():
        missing = REQUIRED_KEYS - set(cfg)
        assert not missing, f"{model_id} is missing {missing}"


def test_no_model_forces_float16(models):
    """Upstream sets --dtype float16 for one reason it states itself: a Tesla T4
    is compute capability 7.5 and cannot do bfloat16. Ours is 9.0."""
    for model_id, cfg in models.items():
        assert "--dtype" not in cfg["args"], (
            f"{model_id} pins a dtype; on capability 9.0 let the model use its own"
        )


def test_every_model_caps_gpu_memory(models):
    """vLLM's default 0.90 is a fraction of TOTAL but it can only use FREE, and
    on this vGPU those differ by ~1.6 GB. Left alone it asks for more memory
    than exists and dies at startup."""
    ceiling = GPU_FREE_MIB / GPU_TOTAL_MIB
    for model_id, cfg in models.items():
        raw = _arg(cfg["args"], "--gpu-memory-utilization")
        assert raw is not None, f"{model_id} does not set --gpu-memory-utilization"
        util = float(raw)
        assert util * GPU_TOTAL_MIB < GPU_FREE_MIB, (
            f"{model_id} wants {util * GPU_TOTAL_MIB:.0f} MiB of {GPU_FREE_MIB} free"
        )
        assert util <= 0.85, (
            f"{model_id} at {util} leaves under "
            f"{GPU_FREE_MIB - util * GPU_TOTAL_MIB:.0f} MiB spare — too tight"
        )


def test_every_model_leaves_room_for_a_kv_cache(models):
    """Weights that fit are not enough — a model with no KV cache serves nobody."""
    for model_id, cfg in models.items():
        weights = WEIGHTS_MIB.get(model_id)
        if weights is None:
            pytest.fail(
                f"{model_id} has no measured weight size. Add it to WEIGHTS_MIB "
                "from the Hugging Face API before offering it."
            )
        budget = float(_arg(cfg["args"], "--gpu-memory-utilization")) * GPU_TOTAL_MIB
        kv = budget - weights - VLLM_OVERHEAD_MIB
        assert kv > 1024, (
            f"{model_id}: {weights} MiB of weights leaves only {kv:.0f} MiB for KV cache"
        )


def test_oversized_and_gated_models_are_not_offered(models):
    for model_id in KNOWN_TOO_BIG:
        assert model_id not in models, f"{model_id} does not fit this GPU"
    for model_id in KNOWN_GATED:
        assert model_id not in models, (
            f"{model_id} is gated; it would require a token stored in clear text"
        )


def test_no_offered_model_needs_a_token(models):
    """Follows from the above, and is what the dashboard's token field keys off."""
    for model_id, cfg in models.items():
        assert cfg["needs_HF_token"] is False, f"{model_id} is marked as gated"


def test_default_model_returns_plain_content(models):
    """The model the form pre-selects must answer a plain OpenAI request.

    Measured on 2026-08-19 (docs/llm-risks.md R-20): with
    `--reasoning-parser qwen3`, Qwen3.5 put its entire answer in a `reasoning`
    field and returned `content: null`. Every ordinary client — the OpenAI SDK,
    LangChain, an editor plugin, the notebook beat of the demo — reads `content`
    and would have got None while the deployment looked perfectly healthy.

    A reasoning parser is right for a model whose selling point is showing its
    working. It is wrong for the default.
    """
    default = next(iter(models))
    assert "--reasoning-parser" not in models[default]["args"], (
        f"{default} is the deploy form's default and sets a reasoning parser; "
        "it will return content: null to a plain OpenAI request"
    )


def test_reasoning_parsers_only_on_thinking_models(models):
    """Kept deliberately on the models where separated reasoning is the point,
    so that dropping it everywhere is not mistaken for the rule."""
    expected = {
        "LiquidAI/LFM2.5-1.2B-Thinking",
        "deepseek-ai/DeepSeek-R1-Distill-Qwen-1.5B",
    }
    actual = {k for k, v in models.items() if "--reasoning-parser" in v["args"]}
    assert actual <= expected, (
        f"unexpected reasoning parser on {actual - expected} — see R-20"
    )


def test_default_model_is_deliberate(root, models):
    """PAPI sets the form's default to models[0], so file order is user-visible."""
    first = next(iter(models))
    assert first == "Qwen/Qwen3.5-2B", (
        f"the deploy form would default to {first}; if that is intended, update "
        "this test and the note in the catalogue header"
    )
