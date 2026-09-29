"""The workspace bundle carries what the demo needs, and pins what it installs.

The three hospital workspaces fetch a BUNDLE, not this repository — editing
demo/fl/client.py has no effect until scripts/build-fl-bundles.sh is re-run.
That indirection is the point (each site gets only its own slices) and it is
also the thing that goes stale silently, so what the bundle must contain is
asserted here rather than remembered.
"""

import re

import pytest

BOOTSTRAP = "demo/fl/bootstrap.sh"
BUILD = "scripts/build-fl-bundles.sh"


@pytest.fixture(scope="module")
def bootstrap(root):
    return (root / BOOTSTRAP).read_text(encoding="utf-8")


def test_every_pip_install_is_pinned(bootstrap):
    """The federated server runs a fork of Flower based on 1.16.0. A client on
    a different major connects, sits there, and times out without saying why —
    which on camera is indistinguishable from a broken cluster."""
    installs = re.findall(r'pip install[^\n]*?"([^"]+)"', bootstrap)
    assert installs, "no pip installs found — has bootstrap.sh moved?"
    for spec in installs:
        assert "==" in spec, f"{spec} is unpinned"


def test_the_openai_client_is_installed_at_bootstrap(bootstrap):
    """The last demo beat calls a CAIOS-hosted model from a hospital workspace,
    and `pip install` in front of an audience is dead air. Five seconds here."""
    assert re.search(r'OPENAI_VERSION="[\d.]+"', bootstrap), (
        "no pinned openai version in bootstrap.sh"
    )
    assert 'pip install --quiet --disable-pip-version-check "openai==$OPENAI_VERSION"' in bootstrap


def test_both_libraries_are_checked_before_the_demo_starts(bootstrap):
    """A version conflict between flwr and openai would otherwise surface as a
    traceback in the final beat, which is the worst possible place for it."""
    assert 'python3 -c "import flwr, openai"' in bootstrap


def test_the_bundle_ships_the_ca(root):
    """R-05, from the other side. A workspace does not trust the CAIOS CA, so
    without this file in the bundle nothing in the workspace can reach a CAIOS
    deployment over HTTPS — not the federated server, and not the LLM endpoint
    the last beat calls. `curl -k` in bootstrap.sh is the single exception, and
    it is the request that fetches this file."""
    build = (root / BUILD).read_text(encoding="utf-8")
    assert re.search(r'cp "\$CA_SRC" "\$work/caios-ca\.pem"', build), (
        f"{BUILD} no longer copies the CA into the bundle"
    )
    bootstrap = (root / BOOTSTRAP).read_text(encoding="utf-8")
    assert "caios-ca.pem" in bootstrap, (
        "bootstrap.sh no longer checks the CA arrived"
    )


def test_the_bootstrap_verifies_what_it_unpacked(bootstrap):
    """A truncated download leaves a workspace that looks bootstrapped and
    fails later, mid-round."""
    for required in ("client.py", "model.py", "caios-ca.pem"):
        assert required in bootstrap, f"bootstrap.sh does not check for {required}"


def test_the_build_does_not_replace_the_directory_caddy_serves(root):
    """The one that broke beat 5, found on 2026-08-22.

    `rm -rf "$DIST"` followed by mkdir produces a NEW INODE. compose/caddy has
    that directory bind-mounted at /srv/fl, and a bind mount follows the inode
    rather than the path — so Caddy goes on serving the deleted one. /srv/fl is
    empty inside the container, every /fl/* URL 404s, and the freshly built
    bundles sit on the host looking perfect.

    That is the bootstrap one-liner each hospital pastes, broken by the very
    script docs/runbook.md tells you to re-run after editing client.py.
    """
    # Comments stripped first: the script explains this failure at length, and
    # the explanation quotes the very line the test asserts is absent. Same
    # reason strip_hcl_comments exists for the job templates — a test that
    # cannot tell code from commentary fails on its own documentation.
    build = re.sub(
        r"^\s*#.*$", "", (root / BUILD).read_text(encoding="utf-8"), flags=re.MULTILINE
    )
    assert 'rm -rf "$DIST"' not in build, (
        "build-fl-bundles.sh replaces the directory Caddy has bind-mounted. "
        "Empty it in place instead, or /fl/ 404s until Caddy is recreated."
    )
    assert 'find "$DIST" -mindepth 1 -delete' in build, (
        "the directory must be emptied in place, keeping its inode"
    )


def test_caddy_still_serves_the_directory_the_build_writes(root):
    """The two halves of the above, kept in agreement. If either path moves,
    the mount points somewhere the build never writes — and, as ever here, the
    symptom is a 404 rather than an error at startup."""
    compose = (root / "compose" / "docker-compose.yml").read_text(encoding="utf-8")
    assert "../demo/fl/dist:/srv/fl:ro" in compose, (
        "compose no longer mounts demo/fl/dist at /srv/fl"
    )
    build = (root / BUILD).read_text(encoding="utf-8")
    assert 'DIST="demo/fl/dist"' in build, (
        "the build writes somewhere other than the directory compose mounts"
    )


# --- the federated server is reached on the private path -------------------
#
# Measured 2026-09-29: the server's public name resolves to the proxy VM, which
# cannot carry gRPC, and every client's stream was reset (RST_STREAM, error
# code 1). Pinned to Traefik's private address, the same run finished ten rounds
# in 32 s at 0.852. The bootstrap does the pinning; these hold it there.

import subprocess


def _pin_block(bootstrap, hosts):
    start = bootstrap.index('EDGE_IP="${CAIOS_FL_EDGE_IP:-@@FL_EDGE_IP@@}"')
    end = bootstrap.index("\nfi\n", start) + len("\nfi\n")
    return bootstrap[start:end].replace("/etc/hosts", str(hosts))


def _run_pin(bootstrap, tmp_path, server, edge_ip="192.0.2.5", hosts_text="127.0.0.1 localhost\n"):
    hosts = tmp_path / "hosts"
    hosts.write_text(hosts_text)
    script = f'SERVER="{server}"\nCAIOS_FL_EDGE_IP="{edge_ip}"\n' + _pin_block(bootstrap, hosts)
    out = subprocess.run(["bash", "-euo", "pipefail", "-c", script], capture_output=True, text=True, check=True).stdout
    return out, hosts.read_text()


def test_the_build_bakes_in_the_private_router(root):
    build = (root / "scripts/build-fl-bundles.sh").read_text(encoding="utf-8")
    assert '"s|@@FL_EDGE_IP@@|$CAIOS_EDGE_IP|g"' in build


def test_the_server_is_pinned_to_the_private_router(bootstrap, tmp_path):
    out, hosts = _run_pin(bootstrap, tmp_path, "fedserver-abc.pacs-deployments.example")
    assert "192.0.2.5 fedserver-abc.pacs-deployments.example" in hosts.splitlines()
    assert "pinned" in out


def test_pinning_twice_adds_one_line(bootstrap, tmp_path):
    line = "192.0.2.5 fedserver-abc.pacs-deployments.example\n"
    out, hosts = _run_pin(bootstrap, tmp_path, "fedserver-abc.pacs-deployments.example",
                          hosts_text="127.0.0.1 localhost\n" + line)
    assert hosts.count("fedserver-abc") == 1 and "already pinned" in out


def test_nothing_is_pinned_without_a_server_or_a_built_address(bootstrap, tmp_path):
    _, hosts = _run_pin(bootstrap, tmp_path, "")
    assert "fedserver" not in hosts
    _, hosts = _run_pin(bootstrap, tmp_path, "fedserver-abc.example", edge_ip="@@FL_EDGE_IP@@")
    assert "fedserver" not in hosts, "an unbuilt bootstrap must not write its placeholder"
