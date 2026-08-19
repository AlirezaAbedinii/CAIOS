"""Every patch still applies to the pinned upstream, and says what it claims.

D-17: changes to upstream are patches, not edits. The standing cost of that is
drift — scripts/clone-vendor.sh moves a SHA and a patch stops applying. This
turns that into a failing test run instead of a failed container build on demo
day.
"""

import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

REPOS = ["ai4-papi", "ai4-nomad_tests", "ai4-dashboard"]


def _patches(root, repo):
    d = root / "patches" / repo
    return sorted(d.glob("*.patch")) if d.is_dir() else []


@pytest.mark.parametrize("repo", REPOS)
def test_patches_apply_to_pinned_upstream(root, repo):
    src = root / "vendor" / repo
    if not src.is_dir():
        pytest.skip(f"vendor/{repo} not cloned")
    patches = _patches(root, repo)
    if not patches:
        pytest.skip(f"no patches for {repo}")

    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp) / repo
        shutil.copytree(src, work, symlinks=True)
        for patch in patches:
            result = subprocess.run(
                ["git", "-C", str(work), "apply", str(patch)],
                capture_output=True,
                text=True,
            )
            assert result.returncode == 0, (
                f"{patch.name} no longer applies to vendor/{repo}.\n"
                f"Read the patch, not the error — patches/README.md says what it is for.\n"
                f"{result.stderr}"
            )


def test_llm_gpu_patch_makes_the_allowlist_configurable(root):
    """0009's whole purpose: the GPU gate becomes configuration, and unset still
    behaves exactly as upstream."""
    patch = root / "patches" / "ai4-papi" / "0009-llm-gpu-models.patch"
    if not patch.is_file():
        pytest.skip("0009 not present")
    text = patch.read_text(encoding="utf-8")
    assert 'os.getenv("LLM_GPU_MODELS", "Tesla T4")' in text, (
        "the upstream default must be preserved for an unset variable"
    )
    assert '-            if "Tesla T4" not in models:' in text, (
        "the hardcoded comparison should be removed, not merely added around"
    )


def test_llm_gpu_patch_fixes_the_open_webui_typo(root):
    """Upstream tests for "openwebui"; the value is "open-webui". A standalone UI
    therefore skipped its credential checks and came up with signup open."""
    patch = root / "patches" / "ai4-papi" / "0009-llm-gpu-models.patch"
    if not patch.is_file():
        pytest.skip("0009 not present")
    text = patch.read_text(encoding="utf-8")
    assert '-        if user_conf["llm"]["type"] in ["openwebui", "both"]:' in text
    assert '+        if user_conf["llm"]["type"] in ["open-webui", "both"]:' in text


def test_every_patch_is_referenced_in_the_readme(root):
    """A patch nobody documented is a patch nobody can evaluate later."""
    readme = (root / "patches" / "README.md").read_text(encoding="utf-8")
    for repo in REPOS:
        for patch in _patches(root, repo):
            assert patch.stem in readme, (
                f"{repo}/{patch.name} is not explained in patches/README.md"
            )
