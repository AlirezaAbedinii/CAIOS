"""The pre-pull playbook sends each node what the demo will run there, and pins it.

docs/demo-plan.md step 6. The playbook used to send every image to every GPU
node; measured on 2026-09-29, caios_llm held 52 GB of module images and no
vLLM, because docuum had evicted it. So the lists are split by node role, and
each list is checked here against the file the demo actually deploys from —
the same idea as test_module_template.py's digest check, one step wider.

The pins are containers created and never started, which docuum never evicts
the image of (D-86). `ansible/files/caios-pin.sh` is run here against a fake
docker, because the real one is on the nodes.
"""

import configparser
import json
import os
import re
import stat
import subprocess
import textwrap

import pytest
import yaml

from conftest import strip_hcl_comments

PLAYBOOK = "ansible/playbook-prepull-images.yml"
PIN = "ansible/files/caios-pin.sh"


@pytest.fixture(scope="module")
def play(root):
    return yaml.safe_load((root / PLAYBOOK).read_text(encoding="utf-8"))[0]


@pytest.fixture(scope="module")
def by_role(play):
    return play["vars"]["caios_images_by_role"]


def _user_default(root, tool, field):
    conf = yaml.safe_load(
        (root / "configs/papi/tools" / tool / "user.yaml").read_text(encoding="utf-8")
    )
    return conf["general"][field]["value"]


# --- the lists match what the demo deploys --------------------------------


def test_the_llm_node_gets_every_image_the_llm_job_runs(root, by_role):
    hcl = strip_hcl_comments(
        (root / "configs/papi/tools/ai4os-llm/nomad.hcl").read_text(encoding="utf-8")
    )
    images = set(re.findall(r'^\s*image\s*=\s*"([^"$]+)"', hcl, re.MULTILINE))
    assert images, "no literal image lines in the LLM template — has it moved?"
    missing = images - set(by_role["llm"])
    assert not missing, (
        f"the LLM job runs {sorted(missing)} but caios_llm does not pre-pull "
        "it: the first deployment would pull it on camera"
    )


def test_the_sites_get_the_federated_workspace_image(root, by_role):
    script = (root / "scripts/deploy-fl-demo.sh").read_text(encoding="utf-8")
    tags = set(re.findall(r"'docker_tag':\s*'([^']+)'", script))
    assert len(tags) == 1, f"expected one workspace tag in deploy-fl-demo.sh, found {tags}"
    image = f"{_user_default(root, 'ai4os-dev-env', 'docker_image')}:{tags.pop()}"
    assert image in by_role["site"], (
        f"the three hospital workspaces deploy {image}; the sites do not pre-pull it"
    )


def test_the_sites_get_the_federated_server_at_its_default_tag(root, by_role):
    image = (
        f"{_user_default(root, 'ai4os-federated-server', 'docker_image')}:"
        f"{_user_default(root, 'ai4os-federated-server', 'docker_tag')}"
    )
    assert image in by_role["site"]


def test_the_sites_get_the_high_code_module_at_its_default_tag(root, by_role):
    meta = yaml.safe_load(
        (root / "catalog/mirror/ai4os-hub/ai4os-yolo-torch/main/ai4-metadata.yml")
        .read_text(encoding="utf-8")
    )
    modules = yaml.safe_load(
        (root / "configs/papi/modules-user.yaml").read_text(encoding="utf-8")
    )
    tag = modules["general"]["docker_tag"]["value"]
    image = f"{meta['links']['docker_image']}:{tag}"
    assert image in by_role["site"], (
        f"the high-code workspace deploys {image}; the sites do not pre-pull it"
    )


def test_no_llm_image_goes_to_a_hospital(by_role):
    """The reason for the split: 38 GB the sites never run, against 80 GB."""
    assert not set(by_role["llm"]) & set(by_role["site"])


# --- every node resolves to a role ----------------------------------------


def test_every_gpu_node_has_a_list(root, play, by_role):
    ini = configparser.ConfigParser(allow_no_value=True, delimiters=(" ",))
    ini.optionxform = str
    ini.read(root / "ansible/inventory/hosts.ini")
    hosts = list(ini["nomad_gpu_clients"])
    assert "caios_llm" in hosts and len(hosts) == 4

    # One line, not the whole file: all.yml carries tags only Ansible reads.
    (line,) = [
        ln for ln in (root / "ansible/group_vars/all.yml").read_text(encoding="utf-8").splitlines()
        if ln.startswith("nomad_client_meta:")
    ]
    default = yaml.safe_load(line)["nomad_client_meta"]
    roles = {}
    for host in hosts:
        meta = default
        hv = root / "ansible/inventory/host_vars" / f"{host}.yml"
        if hv.exists():
            meta = (yaml.safe_load(hv.read_text(encoding="utf-8")) or {}).get(
                "nomad_client_meta", default
            )
        roles[host] = meta.get("role", "site")

    assert "default('site')" in play["vars"]["caios_node_role"]
    assert roles["caios_llm"] == "llm"
    assert sorted(set(roles.values())) == sorted(by_role), roles


# --- pins go on before anything can be evicted ----------------------------


def test_pins_are_placed_before_the_pull_and_again_after(play):
    names = [t["name"] for t in play["tasks"]]

    def at(prefix):
        return next(i for i, n in enumerate(names) if n.startswith(prefix))

    assert at("Release pins") < at("Pin what is already here") < at("Pull images")
    assert at("Pull images") < at("Pin what was pulled") < at("Count") < at("Report")


def test_the_plan_can_be_printed_without_touching_a_node(play):
    plan = next(t for t in play["tasks"] if t["name"] == "Plan")
    assert "ansible.builtin.debug" in plan and "plan" in plan["tags"]


# --- caios-pin.sh, against a fake docker ----------------------------------

FAKE_DOCKER = textwrap.dedent(
    '''\
    #!/usr/bin/env python3
    """Just enough of docker for caios-pin.sh, with state in $FAKE_DOCKER_STATE."""
    import json, os, sys

    path = os.environ["FAKE_DOCKER_STATE"]
    st = json.load(open(path))
    a = sys.argv[1:]
    st["calls"].append(a)

    def done(code=0, out=None):
        json.dump(st, open(path, "w"))
        if out is not None:
            print(out)
        sys.exit(code)

    if a[:2] == ["image", "inspect"]:
        ref = a[-1]
        done(0, st["images"][ref]) if ref in st["images"] else done(1)
    if a[:2] == ["container", "inspect"]:
        c = st["containers"].get(a[-1])
        done(0, c["image"]) if c else done(1)
    if a[0] == "rm":
        done(0 if st["containers"].pop(a[1], None) else 1)
    if a[0] == "create":
        name, label, ref = a[a.index("--name") + 1], a[a.index("--label") + 1], a[-1]
        if name in st["containers"] or ref not in st["images"]:
            done(1)
        st["containers"][name] = {"image": st["images"][ref], "label": label.split("=", 1)[1]}
        done(0, "0123abcd")
    if a[:2] == ["ps", "-a"]:
        lines = [f"{n} {c['label']}" for n, c in st["containers"].items() if c.get("label")]
        done(0, "\\n".join(lines)) if lines else done(0)
    done(99)
    '''
)


@pytest.fixture
def docker(tmp_path, root):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake = bin_dir / "docker"
    fake.write_text(FAKE_DOCKER, encoding="utf-8")
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    state = tmp_path / "state.json"

    class Docker:
        def set(self, images, containers=None):
            state.write_text(json.dumps(
                {"images": images, "containers": containers or {}, "calls": []}
            ))

        @property
        def state(self):
            return json.loads(state.read_text())

        def run(self, *args):
            env = {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}",
                   "FAKE_DOCKER_STATE": str(state)}
            return subprocess.run(["bash", str(root / PIN), *args], env=env,
                                  capture_output=True, text=True, check=True).stdout

    return Docker()


def _creates(state):
    return [c for c in state["calls"] if c[0] == "create"]


def test_an_absent_image_is_reported_and_not_pinned(docker):
    docker.set({})
    assert docker.run("pin", "vllm/vllm-openai:v0.27.1").strip() == "absent vllm/vllm-openai:v0.27.1"
    assert not _creates(docker.state)


def test_a_present_image_is_pinned_once(docker):
    docker.set({"python:3.12-slim-bullseye": "sha256:aaa"})
    assert docker.run("pin", "python:3.12-slim-bullseye").startswith("pinned")
    (pin,) = docker.state["containers"].values()
    assert pin == {"image": "sha256:aaa", "label": "python:3.12-slim-bullseye"}

    assert docker.run("pin", "python:3.12-slim-bullseye").startswith("held")
    assert len(_creates(docker.state)) == 1, "a second run must not create another pin"


def test_a_pin_follows_its_tag_when_the_tag_moves(docker):
    ref = "ai4oshub/ai4os-yolo-torch:latest"
    docker.set({ref: "sha256:old"})
    docker.run("pin", ref)
    state = docker.state
    state["images"][ref] = "sha256:new"
    docker.set(state["images"], state["containers"])

    assert docker.run("pin", ref).startswith("pinned")
    (pin,) = docker.state["containers"].values()
    assert pin["image"] == "sha256:new", "the old image would be held forever"


def test_release_removes_only_pins_that_are_not_listed(docker):
    keep, drop = "ai4oshub/ai4os-dev-env:tf2.14.0", "ai4oshub/ai4os-dev-env:pytorch2.1"
    docker.set({keep: "sha256:k", drop: "sha256:d"})
    docker.run("pin", keep)
    docker.run("pin", drop)
    out = docker.run("release", keep, "vllm/vllm-openai:v0.27.1")
    assert out.strip() == f"released {drop}"
    assert [c["label"] for c in docker.state["containers"].values()] == [keep]


def test_count_is_images_present_and_pinned_to_their_current_id(docker):
    a, b, c = "a:1", "b:1", "c:1"
    docker.set({a: "sha256:a", b: "sha256:b"})
    docker.run("pin", a)
    assert docker.run("count", a, b, c).strip() == "1"


def test_every_pin_name_is_a_valid_distinct_container_name(root, play, docker):
    refs = play["vars"]["caios_images_every_node"] + [
        i for role in play["vars"]["caios_images_by_role"].values() for i in role
    ]
    docker.set({r: f"sha256:{n}" for n, r in enumerate(refs)})
    for r in refs:
        docker.run("pin", r)
    names = list(docker.state["containers"])
    assert len(names) == len(refs), "two references share a pin name"
    for n in names:
        assert re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]+", n), n
