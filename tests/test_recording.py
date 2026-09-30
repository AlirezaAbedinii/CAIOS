"""The narrated recording's source files agree with each other.

demo/recording/ makes the video from three things that must stay in step:
the narration (narration.yaml), the takes that wait on its lines (record.py)
and the edit that places them (assemble.py). Offline: nothing here records,
speaks or encodes anything.
"""

import importlib.util
import re

import pytest
import yaml

REC = "demo/recording"
DASHES = re.compile("[—–]")   # em and en dash: the narration uses neither


@pytest.fixture(scope="module")
def narration(root):
    return yaml.safe_load((root / REC / "narration.yaml").read_text())


@pytest.fixture(scope="module")
def lines(narration):
    return {l["id"]: l for b in narration["beats"] for l in b["lines"]}


@pytest.fixture(scope="module")
def record_src(root):
    return (root / REC / "record.py").read_text()


@pytest.fixture(scope="module")
def assemble(root):
    spec = importlib.util.spec_from_file_location("assemble", root / REC / "assemble.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_no_dashes_in_anything_spoken_or_shown(root, lines):
    for lid, l in lines.items():
        for field in ("text", "speak"):
            assert not DASHES.search(l.get(field, "")), f"{lid}.{field} has a dash"
    for page in (root / REC / "cards").glob("*.html"):
        assert not DASHES.search(page.read_text()), f"{page.name} has a dash"
    transcript = root / REC / "transcript.md"
    if transcript.exists():
        assert not DASHES.search(transcript.read_text())


def test_line_ids_are_unique(narration):
    ids = [l["id"] for b in narration["beats"] for l in b["lines"]]
    assert len(ids) == len(set(ids))


def test_every_cue_names_a_line_and_every_line_is_cued(record_src, lines):
    said = set(re.findall(r'\.say\("(\w+)"', record_src))
    words = set(re.findall(r'\.word\("(\w+)"', record_src))
    assert said - set(lines) == set(), "record.py says a line narration.yaml does not have"
    assert words <= said, "a word cue waits on a line that is never said"
    assert set(lines) - said == set(), "a narration line is never said, so never heard"


def spoken(line, lexicon):
    """What the voice reads, as tts.py builds it, with the phoneme markup removed."""
    text = " ".join(line.get("speak", line["text"]).split())
    for word, repl in lexicon.items():
        text = re.sub(rf"\b{re.escape(word)}\b", repl, text)
    return re.sub(r"\[([^\]]+)\]\(/[^)]*/\)", r"\1", text)


def test_word_cues_name_words_the_voice_says(record_src, lines, narration):
    for lid, word in re.findall(r'\.word\("(\w+)", "([^"]+)"', record_src):
        said = spoken(lines[lid], narration.get("lexicon") or {}).lower()
        assert re.search(rf"\b{re.escape(word.lower())}\b", said), f"{word!r} is not said in {lid}"


def test_record_and_assemble_agree_on_the_running_order(record_src, assemble):
    order = re.search(r"^ORDER = (\[.*?\])", record_src, re.S | re.M).group(1)
    assert eval(order) == assemble.ORDER


def test_every_caption_fits_two_rows(assemble, lines):
    for lid, l in lines.items():
        for block in assemble.chunks(l["text"]):
            rows = block.split("\n")
            assert len(rows) <= 2 and all(len(r) <= 42 for r in rows), (lid, block)


def test_the_recording_outputs_are_not_committed(root):
    ignore = (root / REC / ".gitignore").read_text()
    assert re.search(r"^out/$", ignore, re.M), "out/ holds session tokens and the video"
