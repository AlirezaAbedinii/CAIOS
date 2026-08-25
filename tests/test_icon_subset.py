"""The shelved self-hosted fonts stay internally consistent.

Stage F1 is SHELVED (see the top of scripts/fetch-fonts.sh): the dashboard
still loads its typefaces from Google, and nothing in the build imports these
files. They are kept, and kept correct, so finishing F1 is a matter of fixing
the two faults that rolled it back rather than starting again.

These tests guard the tooling, not the running dashboard. They would all have
passed while F1 was broken — the derivation was checked against itself, which
is exactly the flaw that let it ship. Read that as a limit on what a test can
do here, not as reassurance.

A glyph a subset font lacks does not error. Material icons are ligatures — the
markup says `<mat-icon>delete</mat-icon>` and the typeface draws a bin — so a
missing glyph renders the ligature source instead, and the button shows the
word "delete". Add an icon to a template, forget to re-run
`scripts/fetch-fonts.sh`, and that ships. Nothing in the build complains,
because nothing is wrong: the page is valid, the font loaded, the glyph simply
is not in it.

Same shape as R-26, where six of nine model cards rendered a broken image
behind an HTTP 200, and the same remedy: make it a failing test instead of
something you notice in a browser, or do not.
"""

import re
import subprocess

import pytest

FONT_DIR = "configs/dashboard/fonts"
SCSS = "configs/dashboard/theme/caios/_fonts.scss"

def test_icon_subset_covers_the_source(root):
    """Every icon the dashboard uses is in the font the dashboard ships.

    Delegates to `fetch-fonts.sh --check` rather than re-deriving the list
    here. The extraction patterns are fiddly and there must be exactly one
    copy of them — a second copy in this file would drift out of step with the
    script and then agree with whichever bug it was written beside.
    """
    if not (root / "vendor" / "ai4-dashboard").is_dir():
        pytest.skip("vendor/ai4-dashboard not cloned")

    result = subprocess.run(
        ["bash", "scripts/fetch-fonts.sh", "--check"],
        cwd=root,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        "the committed icon subset no longer matches the source:\n\n"
        + result.stdout
        + result.stderr
    )


def test_every_font_face_rule_points_at_a_file_that_exists(root):
    """A 404 here is invisible: nginx answers a missing asset with index.html
    and HTTP 200, so the browser gets a page where it asked for a font, fails
    to parse it, and silently uses the fallback. Gotcha 20."""
    scss = (root / SCSS).read_text()
    urls = re.findall(r"url\('([^']+)'\)", scss)
    assert urls, f"{SCSS} declares no @font-face src — did fetch-fonts.sh run?"

    for url in urls:
        assert url.startswith("/assets/fonts/"), (
            f"{url} is not served from /assets/fonts/, which is the only path "
            "the angular.json assets glob publishes"
        )
        f = root / FONT_DIR / url.rsplit("/", 1)[-1]
        assert f.is_file(), f"{SCSS} references {url}, but {f} is missing"
        assert f.stat().st_size > 0, f"{f} is empty"


def test_variable_font_weight_ranges_survived_generation(root):
    """`font-weight: 300 700` declares a variable range. Written as `300700`
    it is not a valid font-weight at all, the rule is dropped, and the face
    never applies — while the file still downloads and the CSS still parses.
    The generator got this wrong once."""
    for line in (root / SCSS).read_text().splitlines():
        if "font-weight:" not in line:
            continue
        value = line.split(":", 1)[1].strip().rstrip(";")
        parts = value.split()
        assert all(p.isdigit() and 1 <= int(p) <= 1000 for p in parts), (
            f"implausible font-weight {value!r} in {SCSS} — a variable range "
            "collapsed into one number is the usual cause"
        )


def test_the_scss_is_generated_not_hand_edited(root):
    """It is regenerated wholesale by fetch-fonts.sh. An edit here is lost the
    next time anyone changes a typeface, so say so in the file itself."""
    head = (root / SCSS).read_text()[:400]
    assert "GENERATED" in head and "fetch-fonts.sh" in head
