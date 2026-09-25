"""A module deployment must not wait on Europe for an image the node already has.

2026-09-24: an obj-detection-torch deployment died because its "ui" sidecar,
the DEEPaaS Gradio page, could not be pulled from AI4EOSC's registry — with the
image already on the node. Two things stacked: upstream's template sets
force_pull = true, and Nomad re-pulls any `latest` tag whatever force_pull says
(createImage() in its docker driver checks locally only for a pinned tag or a
digest). The sidecar has no restarts, so its failure took the module with it.

Patch 0020 pins that image by digest; the pre-pull playbook pulls the same
reference. These tests keep the two equal, because a template that names one
digest while the nodes hold another is the original failure again, silently.
"""

import re
import shutil
import subprocess

import pytest
import yaml

from conftest import strip_hcl_comments

PLAYBOOK = "ansible/playbook-prepull-images.yml"

DIGEST_REF = re.compile(
    r"^registry\.cloud\.ai4eosc\.eu/ai4os/deepaas_ui@sha256:[0-9a-f]{64}$"
)

# Tasks upstream's template declares that PAPI removes from every deployment on
# this platform: the two storage tasks whenever no storage is configured
# (there is no Nextcloud, D-15), and the mail sidecar by patch 0005. Only these
# may still name a moving tag in AI4EOSC's registry.
REMOVED_HERE = {"storage_mount", "dataset_download", "email-notification"}


@pytest.fixture(scope="module")
def template(root, tmp_path_factory):
    """etc/modules/nomad.hcl with every CAIOS patch applied, comments removed."""
    src = root / "vendor" / "ai4-papi"
    if not src.is_dir():
        pytest.skip("vendor/ai4-papi not cloned")
    work = tmp_path_factory.mktemp("papi") / "ai4-papi"
    shutil.copytree(src, work, symlinks=True)
    for patch in sorted((root / "patches" / "ai4-papi").glob("*.patch")):
        subprocess.run(
            ["git", "-C", str(work), "apply", str(patch)],
            check=True,
            capture_output=True,
        )
    return strip_hcl_comments(
        (work / "etc" / "modules" / "nomad.hcl").read_text(encoding="utf-8")
    )


@pytest.fixture(scope="module")
def playbook_vars(root):
    plays = yaml.safe_load((root / PLAYBOOK).read_text(encoding="utf-8"))
    return plays[0]["vars"]


def _tasks(template):
    """{task name: its block}, split on the task headers."""
    parts = re.split(r'^\s*task\s+"([^"]+)"\s*\{', template, flags=re.MULTILINE)
    return dict(zip(parts[1::2], parts[2::2]))


def _image(block):
    m = re.search(r'^\s*image\s*=\s*"([^"]+)"', block, re.MULTILINE)
    assert m, "task has no image line — has the template moved?"
    return m.group(1)


def test_the_ui_sidecar_is_pinned_by_digest(template):
    """A digest is the one reference form Nomad looks up locally before pulling."""
    image = _image(_tasks(template)["ui"])
    assert DIGEST_REF.match(image), (
        f"the ui task pulls {image!r}; a tag means every deployment asks "
        "AI4EOSC's registry again, and a stalled answer kills the module"
    )


@pytest.mark.parametrize("task", ["ui", "main"])
def test_the_tasks_a_module_keeps_are_not_force_pulled(template, task):
    block = _tasks(template)[task]
    assert re.search(r"^\s*force_pull\s*=\s*false\s*$", block, re.MULTILINE), (
        f"task {task!r} must set force_pull = false"
    )
    assert not re.search(r"^\s*force_pull\s*=\s*true", block, re.MULTILINE)


def test_only_removed_tasks_still_name_a_moving_tag_in_europe(template):
    """Any other task with a `latest` from registry.cloud.ai4eosc.eu would be
    this bug again, one task over."""
    offenders = {
        name
        for name, block in _tasks(template).items()
        if re.search(r'image\s*=\s*"registry\.cloud\.ai4eosc\.eu/[^"@]+"', block)
    }
    assert offenders <= REMOVED_HERE, (
        f"tasks pulling a tag from AI4EOSC's registry: {sorted(offenders - REMOVED_HERE)}"
    )


def test_the_playbook_prepulls_exactly_what_the_template_runs(template, playbook_vars):
    image = _image(_tasks(template)["ui"])
    images = playbook_vars["caios_images"]
    assert image in images, (
        "the pre-pull playbook does not pull the digest patch 0020 pins, so a "
        "fresh node will pull it at deployment time — from Europe"
    )
    stale = [i for i in images if "deepaas_ui" in i and i != image]
    assert not stale, f"the playbook also pulls a different deepaas_ui: {stale}"



def test_jupyter_may_run_as_root_in_every_module(template):
    """deep-start appends $jupyterOPTS to `jupyter lab` verbatim. posenet-tf's
    image ships an old Jupyter config without allow_root, so without this flag
    Jupyter refuses to start as root and the container exits 1 — the failure
    that took JupyterLab away from every module on 2026-09-02. Patch 0021."""
    block = _tasks(template)["main"]
    assert re.search(r'^\s*jupyterOPTS\s*=\s*"--allow-root"\s*$', block, re.MULTILINE), (
        "the module template must pass --allow-root to JupyterLab"
    )
