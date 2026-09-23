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


# --- the public proxy (C1) -------------------------------------------------

JUMP_HOST = "caios_jump"

# Groups that would do something to a machine. Membership of any of these
# means a Consul agent, a Nomad agent, Docker, or a reformatted disk.
CLUSTER_GROUPS = (
    "consul_master", "consul_clients", "nomad_master",
    "nomad_cpu_clients", "nomad_gpu_clients", "nomad_volume",
    "traefik_master", "monitoring",
)


def test_the_jumpserver_exists_and_is_addressable(inv, root):
    hosts = _hosts(inv, "jumpserver")
    assert hosts == [JUMP_HOST], f"[jumpserver] should hold only {JUMP_HOST}: {hosts}"
    # Read the raw line: the fixture's parser splits on "=", so the address
    # ends up as a value rather than staying on the host line.
    import re
    raw = (root / INVENTORY).read_text()
    assert re.search(rf"^{JUMP_HOST}\s+ansible_host=\d+\.\d+\.\d+\.\d+", raw, re.M), (
        f"{JUMP_HOST} has no ansible_host address. Ansible cannot reach it by "
        f"name — nothing resolves 'caios_jump'."
    )


def test_the_jumpserver_is_in_no_cluster_group(inv):
    """It is not a cluster node and nothing may treat it as one.

    playbook-nomad.yml would install Docker and a Nomad agent on it;
    playbook-prepare-volumes.yml would repartition and reformat /dev/vdb,
    which this machine does not have. It is also the way humans reach the
    cluster, so breaking it costs more than the website.
    """
    for group in CLUSTER_GROUPS:
        assert JUMP_HOST not in _hosts(inv, group), (
            f"{JUMP_HOST} is in [{group}]. That group is acted on by a "
            f"playbook that assumes a cluster node."
        )


def test_only_its_own_playbook_targets_it(root):
    """A `hosts:` line that reaches the jumpserver by accident is the whole
    risk here, and it would not be obvious from the playbook itself."""
    import re
    for pb in sorted((root / "ansible").glob("playbook-*.yml")):
        targets = re.findall(r"^\s*hosts:\s*(\S+)", pb.read_text(), re.M)
        for t in targets:
            if pb.name == "playbook-jumpserver.yml":
                assert t == "jumpserver", f"{pb.name} targets {t}"
            else:
                assert t != "all" and "jumpserver" not in t, (
                    f"{pb.name} targets '{t}', which can reach the jumpserver"
                )
