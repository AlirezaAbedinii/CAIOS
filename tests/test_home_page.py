"""The home page keeps the promises that make it safe to put at `/`.

Stage F3. Three of these are the constraints the page was designed around and
one is a content rule that would otherwise be checked by nobody:

  * it makes no HTTP request of any kind (D-46);
  * every translation key its templates use actually exists;
  * it does not redeclare the icon font (the fault that took F1 down);
  * AI4OS is named once, and the counts it prints match the files they count.

All offline: these read the repository, never a running dashboard.
"""

import json
import re

import pytest
import yaml

HOME = "configs/dashboard/home"
STRINGS = "configs/dashboard/i18n/en.caios.json"
ROUTE_PATCH = "patches/ai4-dashboard/0004-home-route.patch"
BUILD_SCRIPT = "scripts/build-dashboard.sh"


def _sources(root, *suffixes):
    d = root / HOME
    return [p for p in d.rglob("*") if p.suffix in suffixes]


def _strings(root):
    """The CAIOS block, with the _comment annotations stripped as the build
    strips them."""

    def strip(o):
        if isinstance(o, dict):
            return {k: strip(v) for k, v in o.items() if not k.startswith("_comment")}
        return o

    return strip(json.loads((root / STRINGS).read_text(encoding="utf-8")))


@pytest.fixture(scope="module", autouse=True)
def _require_home(root):
    if not (root / HOME).is_dir():
        pytest.skip("home page not present")


# --- D-46: the page has no backend -----------------------------------------

FORBIDDEN = [
    (r"\bHttpClient\b", "HttpClient"),
    (r"\bfetch\s*\(", "fetch()"),
    (r"\bXMLHttpRequest\b", "XMLHttpRequest"),
    (r"\bnavigator\.sendBeacon\b", "sendBeacon"),
    # Any service that would reach PAPI. Named individually rather than by a
    # blanket "@app/core" ban, because importing a type from core is harmless.
    (r"\bAppConfigService\b", "AppConfigService"),
    (r"\bDeploymentsService\b", "DeploymentsService"),
    (r"\bCatalogService\b", "CatalogService"),
]


def test_the_home_page_makes_no_http_request(root):
    """The reason `/` is safe to hand a visitor while the cluster is mid-deploy.

    Gotchas 18, 19 and 20 were all the dashboard reporting backend state
    wrongly. A first page with no backend cannot do that, and this is the
    assertion that keeps it that way when somebody later wants to put a live
    deployment count in the hero.
    """
    for path in _sources(root, ".ts", ".html"):
        text = path.read_text(encoding="utf-8")
        for pattern, name in FORBIDDEN:
            assert not re.search(pattern, text), (
                f"{path.relative_to(root)} uses {name}. The home page makes no "
                f"HTTP request (D-46) — see the README beside it."
            )


def test_the_home_page_loads_nothing_from_a_third_party(root):
    """Same objection as the analytics beacon and the GitHub model list: a page
    on a private subnet should not make the visitor's browser call anyone."""
    for path in _sources(root, ".ts", ".html", ".scss"):
        text = path.read_text(encoding="utf-8")
        # Absolute http(s) URLs in a src/href/url(). Prose mentioning a domain
        # inside a comment is fine; a reference the browser would follow is not.
        for match in re.finditer(r"""(?:src|href|url)\s*[=(]\s*['"]?(https?://[^'")\s]+)""", text):
            pytest.fail(
                f"{path.relative_to(root)} fetches {match.group(1)}. "
                f"Everything the home page needs is served by this cluster."
            )


# --- the fault that took F1 down --------------------------------------------


def test_the_home_page_does_not_redeclare_the_icon_font(root):
    """F1's failure mode, as an assertion.

    index.html still loads Google's complete Material Symbols Rounded. A second
    @font-face for that family, pointing at our 65-glyph subset, would leave
    every icon outside the subset rendering as the word it is named after —
    across the whole application, from a stylesheet on one page.
    """
    for path in _sources(root, ".scss"):
        text = path.read_text(encoding="utf-8")
        faces = re.findall(r"font-family:\s*'([^']+)'", text)
        assert "Material Symbols Rounded" not in faces, (
            f"{path.relative_to(root)} declares the icon font. That is how "
            f"Stage F1 turned every icon in the dashboard into a word."
        )


def test_the_fonts_the_home_page_declares_are_actually_staged(root):
    """A @font-face pointing at a missing file is silent: nginx answers every
    unknown path with index.html and HTTP 200, so the browser gets an HTML
    document where it asked for a typeface and simply falls back."""
    staged = {p.name for p in (root / "configs/dashboard/fonts").glob("*.woff2")}
    for path in _sources(root, ".scss"):
        for ref in re.findall(r"url\('/assets/fonts/([^']+)'\)", path.read_text(encoding="utf-8")):
            assert ref in staged, (
                f"{path.relative_to(root)} asks for {ref}, which is not in "
                f"configs/dashboard/fonts/. Run scripts/fetch-fonts.sh."
            )


# --- the reveal cannot leave the page blank ---------------------------------


def test_the_scroll_reveal_has_a_way_out(root):
    """The hidden state is applied by script and must be removable by script
    even when the browser never reports an intersection.

    This is not hypothetical. Verified in a browser during F3: the observer was
    constructed, given an element filling the viewport, and never called back —
    not even with the initial report a working implementation always sends. Under
    the obvious arrangement that leaves a whole section at opacity 0 for good,
    which is a blank page caused by a decoration.
    """
    src = (root / HOME / "reveal.directive.ts").read_text(encoding="utf-8")
    assert "setTimeout" in src, (
        "the reveal has no fallback: if IntersectionObserver never reports, "
        "every armed section stays invisible"
    )
    assert "prefers-reduced-motion" in src, (
        "reduced motion must skip arming entirely, not merely shorten the "
        "transition (D-48)"
    )
    assert "classList.add('reveal-armed')" in src, (
        "the hidden state must be added by the directive, so an element whose "
        "script did not run is simply visible"
    )

    css = (root / HOME / "components/home/home.component.scss").read_text(
        encoding="utf-8"
    )
    assert ".reveal-armed {" in css and "opacity: 0" in css
    assert "prefers-reduced-motion" in css, (
        "the stylesheet needs its own reduced-motion branch as well"
    )


# --- strings ----------------------------------------------------------------


def test_every_translation_key_the_templates_use_exists(root):
    """ngx-translate renders a missing key as the key itself, so the page would
    read `HOME.POSITION.P1` in 17px type and nothing would report an error."""
    strings = _strings(root)
    missing = []
    for path in _sources(root, ".html", ".ts"):
        text = path.read_text(encoding="utf-8")
        for key in re.findall(r"['\"](HOME\.[A-Z0-9.\-]+)['\"]", text):
            node = strings
            for part in key.split("."):
                node = node.get(part) if isinstance(node, dict) else None
                if node is None:
                    missing.append(f"{key}  ({path.relative_to(root)})")
                    break
    assert not missing, "translation keys used but not defined:\n  " + "\n  ".join(missing)


def test_no_string_is_defined_and_never_used(root):
    """The other direction. Dead copy is how a page ends up saying two
    different things in two places, one of them invisible."""
    used = set()
    for path in _sources(root, ".html", ".ts"):
        used |= set(re.findall(r"['\"](HOME\.[A-Z0-9.\-]+)['\"]", path.read_text(encoding="utf-8")))

    def leaves(node, prefix):
        for k, v in node.items():
            if isinstance(v, dict):
                yield from leaves(v, f"{prefix}.{k}")
            else:
                yield f"{prefix}.{k}"

    defined = set(leaves(_strings(root)["HOME"], "HOME"))
    assert not (defined - used), f"defined but never rendered: {sorted(defined - used)}"


def test_the_upstream_foundation_is_named_once(root):
    """Credit, not branding. Once is attribution; repeated it reads as though
    the platform were somebody else's product with a badge on it."""
    text = json.dumps(_strings(root)["HOME"])
    assert text.count("AI4OS") == 1, (
        f"AI4OS appears {text.count('AI4OS')} times in the home page copy; it "
        f"should be named exactly once, in the colophon."
    )


# --- the counts the page prints ---------------------------------------------


def test_the_inventory_counts_match_the_files_they_count(root):
    """Every figure on this page is a count of something in the repository. The
    page is the easiest place on the platform to check and the worst place to
    be wrong, so the counts are asserted rather than trusted."""

    def keep(path):
        return len(
            [
                line
                for line in (root / path).read_text(encoding="utf-8").splitlines()
                if line.strip() and not line.lstrip().startswith("#")
            ]
        )

    expected = {
        "9": keep("catalog/keep.txt"),
        "12": keep("catalog/ai4life-models.txt"),
    }
    for printed, actual in expected.items():
        assert int(printed) == actual, (
            f"the home page prints {printed} where the repository now has {actual}"
        )

    models = yaml.safe_load((root / "configs/papi/vllm.yaml").read_text(encoding="utf-8"))
    assert len(models["models"]) == 9, (
        "the home page prints 9 language models; configs/papi/vllm.yaml has "
        f"{len(models['models'])}"
    )

    ts = (root / HOME / "components/home/home.component.ts").read_text(encoding="utf-8")
    for count in re.findall(r"count:\s*'(\d+)'", ts):
        assert count in {"9", "12", "3"}, f"unexplained count {count} in the inventory"


# --- how it reaches the browser ---------------------------------------------


def test_the_route_patch_is_the_only_upstream_edit(root):
    """The whole architecture of F3, as an assertion: one patch, one file."""
    patch = (root / ROUTE_PATCH).read_text(encoding="utf-8")
    files = re.findall(r"^\+\+\+ b/(.+)$", patch, flags=re.MULTILINE)
    assert files == ["src/app/app.routes.ts"], (
        f"the home page should touch one upstream file; this patch touches {files}"
    )
    assert "loadChildren" in patch and "home.module" in patch, (
        "the route must lazy-load the module, not eagerly import it"
    )
    assert "redirectTo: '/catalog/modules'" in patch, (
        "the patch should replace the old redirect, so removing it restores it exactly"
    )


def test_the_build_stages_what_the_route_imports(root):
    """A route importing a directory nobody stages fails a hundred lines into
    an ng build, a long way from its cause."""
    script = (root / BUILD_SCRIPT).read_text(encoding="utf-8")
    assert 'cp -r "$CFG"/home/. "$DST/src/app/modules/home/"' in script, (
        f"{BUILD_SCRIPT} does not stage configs/dashboard/home/"
    )
    assert "en.caios.json" in script, (
        f"{BUILD_SCRIPT} does not merge the CAIOS strings into en.json"
    )
