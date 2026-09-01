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


def test_the_figures_set_svg_presentation_in_css_only(root):
    """A CSS property beats an SVG presentation attribute, always.

    Twice in one afternoon: `transform` on the hero tiles stacked twelve of
    them at the origin, and `text-anchor` on a chart caption centred it on the
    left edge of the plot and ran it off the drawing. Both looked like a
    rendering failure and neither logged anything.

    The rule that avoids the whole family: if a property is styled in the
    stylesheet, do not also set it as an attribute in the template.
    """
    html = (
        root / HOME / "components/slide-figure/slide-figure.component.html"
    ).read_text(encoding="utf-8")
    css = (
        root / HOME / "components/slide-figure/slide-figure.component.scss"
    ).read_text(encoding="utf-8")

    styled = {
        prop
        for prop in ("text-anchor", "transform", "fill", "stroke", "opacity")
        if re.search(rf"^\s+{prop}:", css, flags=re.MULTILINE)
    }
    clashes = [p for p in styled if re.search(rf'\s{p}="', html)]
    assert not clashes, (
        f"these are set both in the stylesheet and as attributes, and the "
        f"stylesheet wins: {sorted(clashes)}"
    )


# --- the hero illustration --------------------------------------------------


def test_the_hero_image_is_staged_by_the_build(root):
    """The page references the file directly, and every missing path under this
    dashboard answers HTTP 200 with index.html. An unstaged image is therefore
    a broken picture at the top of the first page anybody sees, with nothing
    anywhere reporting it."""
    html = (root / HOME / "components/home/home.component.html").read_text(
        encoding="utf-8"
    )
    src = re.search(r'src="/assets/images/([^"]+)"', html)
    assert src, "the hero image is not referenced from the page"
    name = src.group(1)

    assert (root / "configs/dashboard/images" / name).is_file(), (
        f"{name} is referenced by the page and is not in configs/dashboard/images/"
    )

    script = (root / BUILD_SCRIPT).read_text(encoding="utf-8")
    required = re.search(r"REQUIRED_IMAGES=\(([^)]+)\)", script).group(1)
    assert name in required, (
        f"{name} is not in REQUIRED_IMAGES, so a missing copy would be a broken "
        f"image rather than a loud build warning"
    )


def test_the_hero_image_cannot_shift_the_page_as_it_loads(root):
    """Without intrinsic dimensions the browser lays the page out at zero
    height for the image and reflows when it arrives, moving the headline and
    the buttons beside it under the reader's cursor."""
    html = (root / HOME / "components/home/home.component.html").read_text(
        encoding="utf-8"
    )
    img = re.search(r"<img[^>]*motif__image.*?/>", html, flags=re.DOTALL)
    assert img, "no hero image element found"
    assert re.search(r'width="\d+"', img.group(0)), "the hero image has no width"
    assert re.search(r'height="\d+"', img.group(0)), "the hero image has no height"
    assert "loading=\"lazy\"" not in img.group(0), (
        "the hero image is the first thing on the page and must not be deferred"
    )


def test_the_hero_image_is_small_enough_to_be_the_first_thing_that_loads(root):
    """This page loads two font files and nothing else. An illustration that
    weighs more than everything around it put together is not a decision
    anybody made; it is a file nobody looked at."""
    images = list((root / "configs/dashboard/images").glob("header_image.*"))
    assert images, "no hero image in configs/dashboard/images/"
    size = images[0].stat().st_size
    assert size < 400 * 1024, (
        f"{images[0].name} is {size / 1024:.0f} KB. Resize it, and prefer WebP: "
        f"the same picture at the width the page gives it is a quarter of a "
        f"comparable PNG."
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
    read `HOME.STAGE.LLM.BODY` in display type and nothing would report an
    error."""
    strings = _strings(root)
    missing = []
    for path in _sources(root, ".html", ".ts"):
        text = path.read_text(encoding="utf-8")
        for key in re.findall(r"['\"](HOME\.[A-Z0-9.\-]+)['\"]", text):
            # `'HOME.STAGE.' + figureKey + '.FIGURE-ALT'` leaves a bare prefix
            # in the source. It is a fragment, not a key.
            if key.endswith("."):
                continue
            node = strings
            for part in key.split("."):
                node = node.get(part) if isinstance(node, dict) else None
                if node is None:
                    missing.append(f"{key}  ({path.relative_to(root)})")
                    break
    assert not missing, "translation keys used but not defined:\n  " + "\n  ".join(missing)


def test_no_string_is_defined_and_never_used(root):
    """The other direction. Dead copy is how a page ends up saying two
    different things in two places, one of them invisible.

    The figure keys are built at runtime from the slide id (`no-code` becomes
    `NO-CODE`), so they are matched by prefix rather than by literal.
    """
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
    # `'HOME.STAGE.' + figureKey + '.FIGURE-ALT'` covers every slide's alt text.
    dynamic = {k for k in defined if k.endswith(".FIGURE-ALT")}
    orphans = defined - used - dynamic
    assert not orphans, f"defined but never rendered: {sorted(orphans)}"


def test_the_upstream_foundation_is_named_once(root):
    """Credit, not branding. Once is attribution; repeated it reads as though
    the platform were somebody else's product with a badge on it."""
    text = json.dumps(_strings(root)["HOME"])
    assert text.count("AI4OS") == 1, (
        f"AI4OS appears {text.count('AI4OS')} times in the home page copy; it "
        f"should be named exactly once, in the closing block."
    )


# --- who the page is written for --------------------------------------------
#
# The audience is medical and neuroscience academics. Not one of them needs to
# know what schedules a job, and a count of machines tells them only how small
# the platform is this month. Both of these are easy to reintroduce by
# accident, in a sentence that reads perfectly well to whoever wrote it.

INFRASTRUCTURE_WORDS = [
    "nomad",
    "kubernetes",
    "docker",
    "container",
    "vllm",
    "traefik",
    "keycloak",
    "vault",
    "consul",
    "h100",
    "nvidia",
    "gpu",
    "cpu",
    "vcpu",
    "tls",
    "oidc",
    "single sign-on",
    "control plane",
    "cluster",
    "node",
    "scheduler",
    "bearer",
    "curl",
    "json",
    "yaml",
    "http",
]


def _home_prose(root):
    """Every rendered string, with the annotations stripped as the build strips
    them. The _comment keys explain the rules and therefore quote the very
    words the rules ban."""

    def leaves(node):
        for k, v in node.items():
            if isinstance(v, dict):
                yield from leaves(v)
            else:
                yield k, v

    return list(leaves(_strings(root)["HOME"]))


def test_the_page_does_not_talk_about_infrastructure(root):
    """A clinician-scientist reading this page should not meet a word whose
    only purpose is to describe how the platform is built."""
    found = []
    for key, value in _home_prose(root):
        lowered = value.lower()
        for word in INFRASTRUCTURE_WORDS:
            if re.search(rf"\b{re.escape(word)}\b", lowered):
                found.append(f"{key}: {word!r} in {value!r}")
    assert not found, (
        "the home page uses vocabulary its audience has no use for:\n  "
        + "\n  ".join(found)
    )


def test_the_page_states_no_size_of_the_installation(root):
    """This is a demonstration and it will grow. A number of machines printed
    on the first page is a promise that dates badly, and it is not a number
    anybody reading it wanted."""
    pattern = re.compile(
        r"\b(one|two|three|four|five|six|seven|eight|nine|ten|\d+)[\s-]"
        r"(node|machine|server|gpu)",
        re.IGNORECASE,
    )
    hits = [f"{k}: {v!r}" for k, v in _home_prose(root) if pattern.search(v)]
    assert not hits, "the home page counts the installation:\n  " + "\n  ".join(hits)


def test_the_copy_uses_no_em_dashes(root):
    """A house rule, and a legible one: an em dash is the punctuation mark that
    most makes written English read as though nobody chose the sentence."""
    hits = [f"{k}: {v!r}" for k, v in _home_prose(root) if "\u2014" in v]
    assert not hits, "em dashes in the home page copy:\n  " + "\n  ".join(hits)


def test_the_platform_does_not_claim_the_catalogue_as_its_own(root):
    """The catalogue and the ways of serving a model come from the upstream
    stack. Saying CAIOS adds them overstates what this project did."""
    text = json.dumps(_strings(root)["HOME"]).lower()
    for claim in ("its own catalogue", "this interface on top"):
        assert claim not in text, f"the page claims {claim!r} as CAIOS's own"


# --- how much there is to read ----------------------------------------------


def test_the_page_stays_short(root):
    """The page was seven stacked sections and five thousand pixels. It is now
    a heading, one stage and a way out. This is a blunt guard against it
    growing back a section at a time."""
    html = (root / HOME / "components/home/home.component.html").read_text(
        encoding="utf-8"
    )
    blocks = len(re.findall(r"<(section|header)\b", html))
    assert blocks <= 3, (
        f"the home page has {blocks} top-level blocks; it is meant to be three"
    )

    # Visible prose only. Alt text is for readers who cannot see the drawing
    # and counting it here would put a word budget in competition with
    # accessibility, which is a trade nobody should be asked to make.
    words = sum(
        len(v.split()) for k, v in _home_prose(root) if not k.endswith("FIGURE-ALT")
    )
    assert words < 450, (
        f"the home page has {words} words of visible copy. It is a first "
        f"impression, not a document; the detail belongs on the pages it "
        f"links to."
    )


def test_the_stage_carries_the_slides_rather_than_the_page(root):
    """The point of the rewrite: what used to be sections is now one stage, in
    two labelled groups."""
    ts = (root / HOME / "components/stage/stage.component.ts").read_text(
        encoding="utf-8"
    )
    assert ts.count("group: 'what',") == 3, "three slides for what the platform does"
    assert ts.count("group: 'how',") == 3, "three slides for how you work with it"


# --- the figures ------------------------------------------------------------


def test_the_measured_chart_is_drawn_from_the_measurements(root):
    """The federated figure is the one drawing that reports a result, so it is
    projected from the recorded numbers rather than from a hand-written path.
    A drawing and the result it reports cannot then drift apart."""
    ts = (root / HOME / "components/slide-figure/slide-figure.component.ts").read_text(
        encoding="utf-8"
    )
    literal = re.search(r"curve = \[([^\]]+)\]", ts).group(1)
    curve = [float(n) for n in re.findall(r"[\d.]+", literal)]
    recorded = json.loads(
        (root / "demo/fl/results/cluster/federated_site_a.json").read_text(
            encoding="utf-8"
        )
    )["curve"]
    assert curve == recorded, (
        "the chart on the home page is not the curve in "
        "demo/fl/results/cluster/federated_site_a.json"
    )

    baselines = json.loads(
        (root / "demo/fl/results/baselines.json").read_text(encoding="utf-8")
    )["curves"]
    best_single = max(max(baselines[s]) for s in ("site_a", "site_b", "site_c"))
    pooled = max(baselines["central"])
    assert f"bestSingleSite = {round(best_single, 3)}" in ts
    assert f"pooled = {round(pooled, 3)}" in ts


def test_every_slide_has_a_drawing(root):
    """Six slides, six figures. A slide that falls through to the default case
    would silently show the wrong picture."""
    ts = (root / HOME / "components/slide-figure/slide-figure.component.ts").read_text(
        encoding="utf-8"
    )
    ids = re.search(r"export type FigureId =([^;]+);", ts).group(1)
    declared = set(re.findall(r"'([a-z-]+)'", ids))

    html = (
        root / HOME / "components/slide-figure/slide-figure.component.html"
    ).read_text(encoding="utf-8")
    drawn = set(re.findall(r"@case \('([a-z-]+)'\)", html))
    assert "@default" in html, "the last figure should be the default branch"
    assert declared - drawn == {"high-code"}, (
        f"figures declared but not drawn: {sorted(declared - drawn - {'high-code'})}"
    )


# --- the reveal cannot leave the page blank ---------------------------------


def test_the_scroll_reveal_has_a_way_out(root):
    """The hidden state is applied by script and must be removable by script
    even when the browser never reports an intersection.

    This is not hypothetical. Verified in a browser during F3: the observer was
    constructed, given an element filling the viewport, and never called back,
    not even with the initial report a working implementation always sends.
    Under the obvious arrangement that leaves a whole section at opacity 0 for
    good, which is a blank page caused by a decoration.
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
