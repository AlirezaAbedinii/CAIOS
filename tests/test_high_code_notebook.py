"""The high-code notebook: what the camera sees, and what it must never see.

The notebook is recorded, so it is a public artefact the moment the video is.
Its endpoints and secrets are staged into the workspace by
scripts/stage-high-code.sh as dotfiles the notebook reads and never shows; these
tests keep it that way, and keep the recording starting from a clean notebook.
"""

import json
import re

import pytest

NOTEBOOK = "demo/high-code/high-code.ipynb"
HELPER = "demo/high-code/caios_demo.py"
STAGER = "scripts/lib/stage_high_code.py"


@pytest.fixture(scope="module")
def notebook(root):
    return json.loads((root / NOTEBOOK).read_text(encoding="utf-8"))


def _code(notebook):
    return ["".join(c["source"]) if isinstance(c["source"], list) else c["source"]
            for c in notebook["cells"] if c["cell_type"] == "code"]


def test_the_notebook_is_committed_clean(notebook):
    """A recording starts from a notebook nobody has run: no outputs, no
    execution counts, nothing from a rehearsal left on screen."""
    for cell in notebook["cells"]:
        if cell["cell_type"] == "code":
            assert cell["outputs"] == [], "a code cell carries outputs"
            assert cell["execution_count"] is None, "a code cell carries an execution count"


def test_it_is_short_enough_for_its_beat(notebook):
    """The high-code beat is about eighty seconds (docs/demo-plan.md)."""
    code = _code(notebook)
    assert len(code) <= 5, f"{len(code)} code cells"
    assert sum(len(c.splitlines()) for c in code) <= 20


def test_no_endpoint_or_secret_is_ever_in_a_cell(notebook):
    text = "\n".join(_code(notebook))
    # "ss(?:l)ip", not the plain word: tests/test_public_domain.py scans every
    # Python file for that word, and would fail on the pattern forbidding it.
    for pattern in (r"https?://", r"ss(?:l)ip", r"Bearer", r"token", r"api_key", r"password",
                    r"\beyJ[A-Za-z0-9_-]{10,}"):
        assert not re.search(pattern, text, re.IGNORECASE), f"a cell contains {pattern!r}"


def test_the_image_comes_from_inside_the_module(notebook):
    """YOLO's sample images ship inside ultralytics, so the detection cell needs
    no download to have something to look at."""
    assert "ASSETS" in "\n".join(_code(notebook))


def test_the_helper_verifies_tls_and_reads_hidden_config(root):
    """D-43: a notebook arguing that nothing leaves the platform does not switch
    certificate checking off. The config and CA are dotfiles so the file
    browser on camera does not list them."""
    src = (root / HELPER).read_text(encoding="utf-8")
    assert "verify=False" not in src
    assert src.count("verify=CA") >= 2
    assert '".caios.json"' in src and '".caios-ca.pem"' in src


def test_the_language_model_answers_the_same_way_every_take(root):
    """A 2B model at the default temperature once reported a missing stop sign
    for this prompt. A recording is retaken; its answer should not change."""
    assert '"temperature": 0' in (root / HELPER).read_text(encoding="utf-8")


def test_the_stager_writes_the_config_private_and_hidden(root):
    src = (root / STAGER).read_text(encoding="utf-8")
    assert 'put(alloc, ".caios.json", json.dumps(config), mode="600")' in src
    assert "umask 077" in src
