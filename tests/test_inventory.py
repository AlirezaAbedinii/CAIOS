"""The Ansible inventory says what Stage L1 assumes it says.

Two of these guard against silent, expensive mistakes: a node that looks healthy
and never receives work, and a rename that breaks every other node.
"""

import configparser

import pytest

INVENTORY = "ansible/inventory/hosts.ini"
LLM_HOST = "caios_llm"


@pytest.fixture(scope="module")
def inv(root):
    cfg = configparser.ConfigParser(allow_no_value=True, delimiters=("=",))
    cfg.optionxform = str  # host lines are not keys to be lower-cased
    cfg.read(root / INVENTORY)
    return cfg


def _hosts(inv, group):
    """Host names in a group, ignoring the `key=value` host vars after them."""
    if group not in inv:
        return []
    return [line.split()[0] for line in inv[group] if line.split()]


def test_llm_host_exists(inv):
    assert LLM_HOST in _hosts(inv, "consul_clients")
    assert LLM_HOST in _hosts(inv, "nomad_gpu_clients")


def test_ansible_names_have_no_hyphens(inv):
    """Gotcha 4. Ansible's own names must use underscores; the Nomad agent names
    it generates (caios-wn-gpu-3) are hyphenated and that is expected."""
    for group in ("consul_master", "consul_clients", "nomad_gpu_clients", "nomad_cpu_clients"):
        for host in _hosts(inv, group):
            assert "-" not in host, f"{host} in [{group}] contains a hyphen"


def test_llm_host_is_last_in_the_gpu_group(inv):
    """roles/nomad/tasks/set_hostname.yml names each agent
    caios-wn-gpu-<index in this list>. Inserting a host anywhere but the end
    renames every node after it, which breaks Consul registration and the node
    names the federated-learning demo prints."""
    gpus = _hosts(inv, "nomad_gpu_clients")
    assert gpus[-1] == LLM_HOST, (
        f"{LLM_HOST} must stay last in nomad_gpu_clients; order is {gpus}"
    )
    assert gpus[:3] == ["caios_site_a", "caios_site_b", "caios_site_c"], (
        "the three hospital nodes must keep indices 0, 1 and 2"
    )


def test_control_plane_is_never_in_the_volume_group(inv):
    """playbook-prepare-volumes.yml reformats /dev/vdb for every host here, and
    this repository lives on caios_server's volume at /mnt/CAIOS."""
    assert "caios_server" not in _hosts(inv, "nomad_volume")


def test_llm_host_is_in_the_volume_group(inv):
    """Not cosmetic. ai4-ansible points Nomad's data_dir at /mnt/data only for
    hosts in this group; everything else gets /opt/nomad on the 20 GB root disk.
    ai4-nomad_tests then asserts unique.storage.volume is /dev/vdb1, fails the
    node, and meta.status never becomes ready — so the node looks perfectly
    healthy and silently receives no work at all."""
    assert LLM_HOST in _hosts(inv, "nomad_volume")


def test_llm_host_vars(root):
    import yaml

    path = root / "ansible/inventory/host_vars" / f"{LLM_HOST}.yml"
    assert path.is_file(), f"{path} is missing"
    meta = yaml.safe_load(path.read_text(encoding="utf-8"))["nomad_client_meta"]

    assert meta.get("role") == "llm", "the LLM job template's affinity reads meta.role"
    # ai4-nomad_tests is the only thing that flips this to "ready", and every
    # PAPI job template constrains on it. Shipping "ready" skips certification;
    # omitting it entirely means nothing is ever scheduled here.
    assert meta.get("status") == "test", (
        "nomad_client_meta must start as status: test, not ready"
    )
