"""The marketplace is served from this repository, not from GitHub.

T1. PAPI builds the catalogue from `raw.githubusercontent.com` at request time —
one fetch for the catalogue's `.gitmodules`, then one per entry for its
`ai4-metadata.yml`, about fifteen for a full page — and `requests.Session()`
carries no timeout, so an unreachable source hangs the page instead of failing
it. That host was unreachable from every CAIOS node for about three hours on
2026-09-01 while `api.github.com`, `github.com` and Docker Hub kept working.

`scripts/mirror-catalogue.sh` mirrors it into `catalog/mirror/`, Caddy serves it
at `/mirror/`, and patch `0014` makes the base URL configuration.

Two things these tests exist to catch, neither of which a status code can see:

  * the mirror going stale or partial — a missing entry is a module that
    silently vanishes from the marketplace;
  * the licence regression, which is why `repo-info.json` exists at all. Every
    module reported `MIT` because `IS_PROD` must be false (gotcha 1), which
    makes `IS_DEV` true, which makes `get_github_info()` return a mock that PAPI
    wrote over the real metadata. `ai4os-yolo-torch` is AGPL-3.0.

All offline: these read the repository, never a running PAPI. The live half is
`scripts/check-catalogue.sh`.
"""

import configparser
import json

import pytest
import yaml

MIRROR = "catalog/mirror"
PATCH = "patches/ai4-papi/0014-catalogue-source-and-metadata.patch"
MIRROR_SCRIPT = "scripts/mirror-catalogue.sh"
KEEP = "catalog/keep.txt"
AI4LIFE_LIST = "catalog/ai4life-models.txt"

# PAPI hardcodes `master` for the catalogue repo and falls back to `master` for
# an entry with no branch, so these paths are literal whatever the real default
# branch is called.
MODULES_GITMODULES = "AlirezaAbedinii/caios-modules-catalog/master/.gitmodules"
TOOLS_GITMODULES = "ai4os/tools-catalog/master/.gitmodules"
AI4LIFE_JSON = (
    "ai4os/ai4os-ai4life-loader/refs/heads/main/models/filtered_models.json"
)


def _submodules(path):
    cfg = configparser.ConfigParser()
    cfg.read_string(path.read_text(encoding="utf-8"))
    out = {}
    for s in cfg.sections():
        d = dict(cfg.items(s))
        out[d["path"]] = {
            "url": d["url"].replace(".git", ""),
            "branch": d.get("branch", "master"),
        }
    return out


@pytest.fixture(scope="module")
def modules(root):
    return _submodules(root / MIRROR / MODULES_GITMODULES)


@pytest.fixture(scope="module")
def tools(root):
    return _submodules(root / MIRROR / TOOLS_GITMODULES)


@pytest.fixture(scope="module")
def repo_info(root):
    return json.loads((root / MIRROR / "repo-info.json").read_text(encoding="utf-8"))


# --- the mirror is complete ------------------------------------------------


def test_both_catalogues_are_mirrored(root):
    for p in (MODULES_GITMODULES, TOOLS_GITMODULES):
        f = root / MIRROR / p
        assert f.is_file(), f"{p} missing — PAPI would 503 on the whole catalogue"
        assert "[submodule" in f.read_text(encoding="utf-8")


def test_modules_mirror_matches_keep_list(root, modules):
    """The curated list and the mirror are the same set.

    `catalog/keep.txt` is what a medical researcher is meant to see. If the fork
    is re-curated and the mirror is not refreshed, the marketplace shows the old
    set — and nothing else notices.
    """
    kept = {
        line.split("#")[0].strip()
        for line in (root / KEEP).read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    }
    kept.discard("")
    assert set(modules) == kept, (
        "mirror and keep.txt disagree — re-run scripts/mirror-catalogue.sh\n"
        f"  only in mirror:   {sorted(set(modules) - kept)}\n"
        f"  only in keep.txt: {sorted(kept - set(modules))}"
    )


@pytest.mark.parametrize("which", ["modules", "tools"])
def test_every_entry_has_mirrored_metadata(root, request, which):
    """Every entry PAPI will ask about has a file waiting at the path it uses.

    The path is `<owner>/<repo>/<branch>/ai4-metadata.yml`, reproducing
    raw.githubusercontent.com's own layout — which is what keeps patch 0014 a
    base-URL swap rather than a rewrite.
    """
    entries = request.getfixturevalue(which)
    for name, e in entries.items():
        owner_repo = e["url"].removeprefix("https://github.com/")
        f = root / MIRROR / owner_repo / e["branch"] / "ai4-metadata.yml"
        assert f.is_file(), f"{name}: no mirrored metadata at {f.relative_to(root)}"


@pytest.mark.parametrize("which", ["modules", "tools"])
def test_mirrored_metadata_parses_and_is_usable(root, request, which):
    entries = request.getfixturevalue(which)
    for name, e in entries.items():
        owner_repo = e["url"].removeprefix("https://github.com/")
        f = root / MIRROR / owner_repo / e["branch"] / "ai4-metadata.yml"
        d = yaml.safe_load(f.read_text(encoding="utf-8"))
        assert isinstance(d, dict), f"{name}: metadata is not a mapping"
        for field in ("title", "summary"):
            assert d.get(field), f"{name}: no {field}, the card would render blank"


def test_docker_images_are_namespaced(root, modules):
    """The `image-classification-tf-dicom` trap.

    PAPI does `repo, image = registry.split("/")[-2:]` on the docker image, so a
    bare name with no namespace raises ValueError and `/config` returns HTTP 500
    the moment the module is clicked. That is why that module is not in
    keep.txt; this keeps a future re-curation from reintroducing one.
    """
    for name, e in modules.items():
        owner_repo = e["url"].removeprefix("https://github.com/")
        f = root / MIRROR / owner_repo / e["branch"] / "ai4-metadata.yml"
        image = (yaml.safe_load(f.read_text(encoding="utf-8")).get("links") or {}).get(
            "docker_image", ""
        )
        assert "/" in image, (
            f"{name}: docker_image {image!r} has no namespace — /config would 500"
        )


def test_ai4life_list_is_mirrored_and_covers_the_curated_models(root):
    f = root / MIRROR / AI4LIFE_JSON
    assert f.is_file(), "the AI4Life dropdown would be empty (demo beat 2)"
    available = {m["id"] for m in json.loads(f.read_text(encoding="utf-8")).values()}

    curated = [
        line.split("#")[0].strip()
        for line in (root / AI4LIFE_LIST).read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    curated = [c for c in curated if c]
    missing = [c for c in curated if c not in available]
    assert not missing, f"curated AI4Life models absent from the mirror: {missing}"


# --- the licence regression ------------------------------------------------


def test_repo_info_covers_every_entry(root, modules, tools, repo_info):
    for entries in (modules, tools):
        for name, e in entries.items():
            owner_repo = e["url"].removeprefix("https://github.com/")
            assert owner_repo in repo_info, (
                f"{name}: no licence recorded, the module page would show none"
            )


def test_licences_are_not_all_mit(repo_info):
    """The regression itself, stated as the thing that was wrong.

    Before the fix every module reported MIT, because `get_github_info()`
    short-circuits on IS_DEV to `{"license": "MIT", ...}` and PAPI wrote it over
    the real metadata. A mirror that somehow produced MIT for everything would
    be indistinguishable from the bug.
    """
    licences = {v["license"] for v in repo_info.values()}
    assert licences != {"MIT"}, "every licence is MIT again — the mock is winning"
    assert len(licences) > 1, f"suspiciously uniform licences: {licences}"


def test_the_agpl_module_is_recorded_as_agpl(repo_info):
    """`ai4os-yolo-torch` wraps Ultralytics YOLO and is AGPL-3.0.

    Named explicitly because it is the case that makes this a licensing problem
    rather than a cosmetic one: AGPL and MIT impose materially different
    obligations on whoever deploys it. See docs/licensing.md.
    """
    lic = repo_info["ai4os-hub/ai4os-yolo-torch"]["license"]
    assert "AGPL" in lic, f"YOLO recorded as {lic!r}, expected AGPL-3.0"


def test_no_repo_is_dated_to_the_epoch(repo_info):
    """1970-01-01 is the mock's fingerprint, not a real date."""
    for repo, info in repo_info.items():
        for field in ("created", "updated"):
            assert not info[field].startswith("1970"), (
                f"{repo}: {field} is the epoch — the IS_DEV mock is winning"
            )


# --- the patch keeps its promises ------------------------------------------


def test_patch_makes_the_source_configurable_with_upstream_as_default(root):
    p = (root / PATCH).read_text(encoding="utf-8")
    assert "CATALOGUE_BASE_URL" in p
    # `or` rather than a get() default: unset and empty must behave the same,
    # or a blank line in an env file silently points the marketplace at nothing.
    assert 'os.environ.get("CATALOGUE_BASE_URL") or "https://raw.githubusercontent.com"' in p


def test_patch_adds_a_timeout(root):
    """The reason the outage presented as a spinner rather than an error."""
    p = (root / PATCH).read_text(encoding="utf-8")
    assert "CATALOGUE_TIMEOUT" in p
    assert "timeout=CATALOGUE_TIMEOUT" in p
    assert "timeout=(5, 15)" in p, "utils.ai4life_catalog() still has no timeout"


def test_patch_turns_an_unreachable_source_into_503_not_a_hang(root):
    p = (root / PATCH).read_text(encoding="utf-8")
    assert "status_code=503" in p
    assert "requests.RequestException" in p


def test_patch_stops_the_mock_overwriting_real_metadata(root):
    """The licence fix, in the patch rather than in the mirror.

    Upstream assigns unconditionally:
        metadata["license"] = gh_info.get("license", "")
    which is what let the IS_DEV mock win.
    """
    p = (root / PATCH).read_text(encoding="utf-8")
    assert '-                metadata["license"] = gh_info.get("license", "")' in p
    assert "mirrored_repo_info" in p


def test_mirror_script_empties_in_place(root):
    """D-44, met twice now.

    compose bind-mounts `catalog/mirror` into Caddy. A bind mount follows the
    inode, so `rm -rf` + `mkdir` leaves Caddy serving the deleted directory —
    every /mirror/ URL 404s while the files sit on the host looking perfect.
    """
    s = (root / MIRROR_SCRIPT).read_text(encoding="utf-8")
    assert 'rm -rf "$OUT"' not in s, "recreating the directory breaks Caddy's mount"
    assert 'find "$OUT" -mindepth 1 -delete' in s


def test_mirror_script_does_not_fetch_from_the_flaky_host(root):
    """It fetches over github.com and api.github.com, both of which stayed up.

    Fetching the mirror from the host the mirror exists to avoid would make the
    refresh fail in exactly the situation the mirror is for.
    """
    s = (root / MIRROR_SCRIPT).read_text(encoding="utf-8")
    code = "\n".join(
        line for line in s.splitlines() if not line.lstrip().startswith("#")
    )
    assert "raw.githubusercontent.com" not in code
