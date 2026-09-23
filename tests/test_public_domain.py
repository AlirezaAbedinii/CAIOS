"""One variable decides the public domain, and nothing spells one out behind it.

C0, for docs/certificate-plan.md. `CAIOS_PUBLIC_DOMAIN` in
configs/env/caios.env is the only place the platform's public domain is
written down. Everything else derives from it: the four control-plane
hostnames, PAPI's advertised endpoint and CORS list, the deployment domain
Traefik routes on, both certificates' SANs, Keycloak's redirect URIs, the
federated-learning bundles and OSCAR's issuer.

Worth a test for the same reason the scheme is: a missed spot does not fail
loudly. A stale hostname in the issuer chain is 401 on everything with nothing
in the log naming the cause. A stale one in the deployment domain is a
wildcard certificate that does not cover what PAPI hands out, which surfaces
as 502 behind a certificate a browser calls perfectly valid.

The exceptions are named below with their reasons, so a sixth one is a
decision rather than an oversight.
"""

import re
import subprocess

import pytest

# --- what may still say "sslip" -------------------------------------------

# (path, substring that must appear on the line). A line matches an exemption
# only if BOTH agree, so an exemption cannot quietly widen to the whole file.
SSLIP_ALLOWED = [
    # The one definition site. This IS the variable.
    ("configs/env/caios.env.template", "CAIOS_PUBLIC_DOMAIN="),

    # OSCAR and MinIO are PRIVATE. They are reached over 192.168.104.0/24 at
    # the OSCAR node's own address, with certificates from the CAIOS CA, and
    # nothing outside the cluster talks to them. Let's Encrypt cannot issue
    # for a private IP, so these must NOT follow the public domain.
    ("scripts/install-oscar.sh", "OSCAR_HOST="),
    ("scripts/install-oscar.sh", "MINIO_HOST="),
    ("scripts/oscar-submit.sh", "minio-console."),

    # Classifiers, not hostnames. Each decides whether ACME is possible at
    # all, because Let's Encrypt issues wildcards over DNS-01 alone and nobody
    # controls the sslip.io zone — so this is not a setting to get wrong, it
    # is a fact to detect and refuse on.
    ("scripts/render-configs.sh", "CAIOS_PUBLIC_DOMAIN\" == *.sslip.io"),
    ("scripts/render-configs.sh", "CAIOS_DOMAIN_KIND="),
    ("scripts/render-nginx-config.sh", "tls_for()"),

    # A synthetic domain in a test fixture, not a hostname. Exempted on the
    # word "fixture" rather than on the file, so a real hostname typed into
    # this same file is still caught.
    ("tests/test_jumpserver_config.py", "fixture"),
]

# .template covers the env file, the Caddyfile, the Keycloak realm and the
# nginx config for the proxy VM — all of which name public hostnames and all
# of which are rendered rather than read directly, so a stale one is invisible
# until something downstream fails for an unrelated-looking reason.
SCANNED_SUFFIXES = (".sh", ".yml", ".yaml", ".ini", ".hcl", ".py", ".json",
                    ".cfg", ".patch", ".template")
SCANNED_NAMES = ()
SKIP_PREFIXES = ("docs/", "vendor/", "build/", "tests/test_public_domain.py")


def _tracked(root):
    # --others as well as --cached: a file that is not committed yet is
    # exactly the one most likely to have a hostname typed into it, and
    # scanning only what is tracked means the test passes right up until the
    # moment the mistake is permanent. --exclude-standard keeps build/ and
    # the gitignored env file out.
    out = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
        cwd=root, capture_output=True, text=True, check=True).stdout.split()
    return [p for p in out
            if not p.startswith(SKIP_PREFIXES)
            and (p.endswith(SCANNED_SUFFIXES) or p.endswith(SCANNED_NAMES))]


def _code_lines(root, rel):
    """Lines with commentary removed, as (number, text).

    The CAIOS configs explain at length what upstream got wrong, and those
    explanations quote the very strings asserted absent here — so a check that
    cannot tell code from commentary fails on its own documentation. Patch
    files carry a diff prefix that has to come off before a `#` is visible.
    """
    text = (root / rel).read_text(encoding="utf-8", errors="replace")
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)   # hcl block
    out = []
    for n, line in enumerate(text.splitlines(), 1):
        body = re.sub(r"^[+\- ]", "", line) if rel.endswith(".patch") else line
        if re.match(r"^\s*[#;]", body):
            continue
        out.append((n, body))
    return out


def test_nothing_spells_a_public_hostname_out(root):
    offenders = []
    for rel in _tracked(root):
        for n, line in _code_lines(root, rel):
            if "sslip" not in line:
                continue
            if any(rel == p and s in line for p, s in SSLIP_ALLOWED):
                continue
            offenders.append(f"{rel}:{n}: {line.strip()}")
    assert not offenders, (
        "These spell a hostname out instead of deriving it from "
        "CAIOS_PUBLIC_DOMAIN. Moving to a real domain would leave them "
        "pointing at the old one, and every symptom of that is silent:\n  "
        + "\n  ".join(offenders)
    )


def test_every_exemption_is_still_real(root):
    """An allowlist nobody prunes stops being an allowlist."""
    for rel, needle in SSLIP_ALLOWED:
        lines = [l for _, l in _code_lines(root, rel)
                 if "sslip" in l and needle in l]
        assert lines, (
            f"{rel} no longer has an sslip line containing {needle!r}. "
            f"Remove the exemption rather than leaving it to cover something "
            f"it was never written for."
        )


# --- the definition site ---------------------------------------------------


def _template(root):
    return (root / "configs" / "env" / "caios.env.template").read_text()


def test_template_defines_the_domain_with_an_sslip_default(root):
    """A fresh install has to work with no DNS account and no zone access."""
    assert re.search(r"^CAIOS_PUBLIC_DOMAIN=\$\{CAIOS_PUBLIC_IP\}\.sslip\.io$",
                     _template(root), re.M)


@pytest.mark.parametrize("var", ["CAIOS_DASHBOARD_HOST", "CAIOS_API_HOST",
                                 "CAIOS_AUTH_HOST", "CAIOS_VAULT_HOST",
                                 "CAIOS_DEPLOYMENTS_DOMAIN"])
def test_every_public_name_derives_from_it(root, var):
    line = next((l for l in _template(root).splitlines()
                 if l.startswith(var + "=")), None)
    assert line, f"{var} is gone from the template"
    assert "${CAIOS_PUBLIC_DOMAIN}" in line, (
        f"{var} does not derive from CAIOS_PUBLIC_DOMAIN:\n  {line}"
    )


def test_acme_placeholders_exist(root):
    """Empty is correct while the domain is sslip.io. Absent is not — C2 needs
    somewhere to put them that is gitignored, and that is caios.env."""
    t = _template(root)
    for var in ("CAIOS_ACME_EMAIL", "CAIOS_CF_API_TOKEN"):
        assert re.search(rf"^{var}=$", t, re.M), f"{var} missing or pre-filled"


# --- the things that break silently ---------------------------------------


def test_render_refuses_to_run_without_the_domain(root):
    """Empty would render '://host' into every URL and start cleanly."""
    t = (root / "scripts" / "render-configs.sh").read_text()
    required = re.search(r"for required in (.*?); do", t, re.S)
    assert required
    for var in ("CAIOS_PUBLIC_IP", "CAIOS_PUBLIC_DOMAIN",
                "CAIOS_DEPLOYMENTS_DOMAIN"):
        assert var in required.group(1), f"render-configs.sh does not require {var}"


def test_compose_passes_everything_papi_interpolates(root):
    """main.yaml is expanded by the PAPI image's own envsubst at start.

    A variable it names that compose does not pass survives into the running
    config as a literal ${...} — an endpoint the dashboard renders verbatim
    and a CORS origin that matches no browser. Nothing errors.
    """
    main = (root / "configs" / "papi" / "main.yaml").read_text()
    compose = (root / "compose" / "docker-compose.yml").read_text()
    papi = compose.split("  papi:", 1)[1].split("\n  registration:", 1)[0]
    for var in sorted(set(re.findall(r"\$\{([A-Z_][A-Z0-9_]*)\}", main))):
        assert re.search(rf"^\s+{var}:", papi, re.M), (
            f"configs/papi/main.yaml interpolates ${{{var}}} but compose's papi "
            f"environment does not pass it. It will survive as a literal."
        )


def test_the_wildcard_prefix_matches_the_inventory(root):
    """PAPI joins meta.domain to lb.domain with a hyphen, so the certificate
    covers *.<meta.domain>-<lb.domain>. Two files have to agree and nothing
    else checks them; disagreement is a deployment with no valid certificate.
    """
    certs = (root / "scripts" / "make-traefik-certs.sh").read_text()
    prefix = re.search(r'^DEPLOY_PREFIX="([^"]+)"', certs, re.M)
    assert prefix, "make-traefik-certs.sh no longer names the prefix"
    inventory = (root / "ansible" / "inventory" / "hosts.ini").read_text()
    found = set(re.findall(r"^\S+.*\bdomain=(\w+)", inventory, re.M))
    assert found == {prefix.group(1)}, (
        f"make-traefik-certs.sh issues for *.{prefix.group(1)}-<domain> but the "
        f"inventory sets meta.domain to {sorted(found)}"
    )


def test_the_deployment_domain_has_one_spelling(root):
    """It used to have four, and one of them was wrong."""
    for rel in ("configs/papi/main.yaml", "scripts/make-traefik-certs.sh",
                "scripts/run-cluster-tests.sh"):
        body = "\n".join(l for _, l in _code_lines(root, rel))
        assert "CAIOS_DEPLOYMENTS_DOMAIN" in body, (
            f"{rel} builds the deployment domain some other way"
        )
