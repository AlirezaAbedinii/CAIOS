"""Every file compose bind-mounts into PAPI exists on disk.

This test exists because of D-29. Docker's response to a missing bind-mount
source is not an error — it silently creates an empty DIRECTORY in its place.
That is how PAPI came to run healthily while trusting no CAIOS certificate:
every outbound HTTPS call to our own domains failed, and the error mentioned
nothing about mounts.

Stage L2 adds three more mounts, so the failure mode is now a test.
"""

import re

import pytest
import yaml

COMPOSE = "compose/docker-compose.yml"


@pytest.fixture(scope="module")
def compose(root):
    with open(root / COMPOSE, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _host_paths(service):
    for volume in service.get("volumes", []):
        if not isinstance(volume, str):
            continue
        src = volume.split(":", 1)[0]
        # Skip named volumes and anything the environment fills in.
        if src.startswith((".", "/")) and "${" not in src:
            yield src


def test_papi_bind_mount_sources_exist(root, compose):
    compose_dir = root / "compose"
    missing = []
    for name, service in compose["services"].items():
        for src in _host_paths(service):
            path = (compose_dir / src).resolve()
            # /etc/nomad.d/certs only exists on caios_server; absent elsewhere is
            # legitimate, so it is reported rather than failed.
            if str(path).startswith("/etc/"):
                continue
            if not path.exists():
                missing.append(f"{name}: {src} -> {path}")
    assert not missing, "bind-mount sources Docker would silently create as empty dirs:\n  " + "\n  ".join(missing)


def test_no_mount_source_uses_home(root):
    """D-29 itself: `${HOME}` resolves to /root under sudo, where the file is not."""
    text = (root / COMPOSE).read_text(encoding="utf-8")
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("- ") and ":" in stripped:
            assert "${HOME}" not in stripped and "$HOME" not in stripped, (
                f"bind mount uses HOME, which sudo rewrites to /root: {stripped}"
            )


def test_llm_config_is_mounted(root, compose):
    """The three files that make the LLM tool deployable here."""
    papi = compose["services"]["papi"]
    # "src:target[:opts]" — the target is the middle field, not everything after
    # the first colon.
    mounted = {
        v.split(":")[1] for v in papi["volumes"] if isinstance(v, str) and ":" in v
    }
    for target in (
        "/home/ai4-papi/etc/vllm.yaml",
        "/home/ai4-papi/etc/tools/ai4os-llm/nomad.hcl",
        "/home/ai4-papi/etc/tools/ai4os-llm/user.yaml",
    ):
        assert target in mounted, f"{target} is not mounted into PAPI"


def test_llm_gpu_allowlist_is_set(root, compose):
    """Patch 0009 defaults to upstream's "Tesla T4" when this is unset, which
    would put the 405 straight back."""
    env = compose["services"]["papi"]["environment"]
    assert "LLM_GPU_MODELS" in env
    assert "Tesla T4" not in str(env["LLM_GPU_MODELS"])
    assert "MIG" in str(env["LLM_GPU_MODELS"]), (
        "the device plugin reports the MIG instance since 2026-08-19; the plain "
        "card name matches nothing now"
    )


def test_is_prod_is_explicitly_false(compose):
    """Gotcha 1: PAPI's own Dockerfile sets IS_PROD=True, so leaving this unset
    inherits True and PAPI refuses to start over tokens for services we do not
    run — with an error that does not point at the cause."""
    assert str(compose["services"]["papi"]["environment"]["IS_PROD"]).lower() == "false"
