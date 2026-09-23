"""The proxy VM's nginx config is generated, and it reproduces what is running.

C1 of docs/certificate-plan.md. 134.87.8.230 is the public front door for the
whole platform and was the only machine in the architecture configured by
hand. These tests cover the two things that make generating it safe:

  * it renders byte-for-byte what is live today, so the template is proved
    before it ever carries a new domain, and
  * it cannot damage the OTHER project on that machine.

That second one is not hypothetical. /etc/nginx/conf.d/seventask.conf serves
an unrelated application on :8888 and deliberately does not define its own
`map $http_upgrade $connection_upgrade` — it uses the one in caios.conf,
because a duplicate map in the http context is a global nginx syntax error.
So this file both owns that block and must never emit it twice.
"""

import re
import subprocess

import pytest

RENDERED = "build/jumpserver/caios.conf"
RENDERER = "scripts/render-nginx-config.sh"


def _render(root, extra_env=None):
    import os
    env = {**os.environ, **(extra_env or {})}
    r = subprocess.run(["bash", RENDERER], cwd=root, env=env,
                       capture_output=True, text=True)
    if r.returncode != 0:
        if "Missing configs/env/caios.env" in r.stdout + r.stderr:
            pytest.skip("configs/env/caios.env absent (it is gitignored)")
        raise AssertionError(r.stdout + r.stderr)
    return (root / RENDERED).read_text()


def _directives(text):
    return [l for l in text.splitlines()
            if l.strip() and not l.lstrip().startswith("#")]


# --- the gate --------------------------------------------------------------


def test_it_reproduces_the_running_config(root):
    """The whole point of C1. Render with today's domain and compare against
    the copy taken off the proxy, so the template is known to be faithful
    BEFORE it is asked to carry a new name."""
    live = sorted((root / "ops" / "jumpserver").glob("caios.conf.live-*"))
    assert live, "no saved copy of the live config under ops/jumpserver/"
    rendered = _render(root)
    assert _directives(rendered) == _directives(live[-1].read_text()), (
        "the rendered config no longer matches what is running on the proxy. "
        "Run: bash scripts/render-nginx-config.sh --diff"
    )


# --- the other project on that machine ------------------------------------


def test_the_upgrade_map_is_emitted_exactly_once(root):
    """seventask.conf uses this map and defines no other. Two of them is not
    a CAIOS problem — nginx refuses to start at all, for everybody."""
    assert len(re.findall(r"^map \$http_upgrade \$connection_upgrade",
                          _render(root), re.M)) == 1


def test_the_templates_say_why_that_machine_is_shared(root):
    head = (root / "configs" / "nginx" / "caios.conf.head.template").read_text()
    assert "seventask" in head.lower(), (
        "the head template must say that this machine serves another project. "
        "Somebody will otherwise tidy up the map block, or replace nginx.conf."
    )


# --- nginx's own variables must survive ------------------------------------


def test_envsubst_is_given_an_explicit_variable_list(root):
    """Bare envsubst replaces every $NAME it sees, and an nginx config is made
    of them. Unlisted, $host and friends render empty: a config that fails to
    parse if you are lucky, and proxies to nothing if you are not."""
    # Code lines only: the script's own header explains this at length and
    # the word "envsubst" appears in that prose too.
    code = "\n".join(l for l in (root / RENDERER).read_text().splitlines()
                     if not l.lstrip().startswith("#"))
    calls = re.findall(r"envsubst\s+(\S+)", code)
    assert calls, "no envsubst call found"
    for c in calls:
        assert c.startswith('"$') or c.startswith("'$"), (
            f"envsubst called without a variable list: envsubst {c}"
        )


@pytest.mark.parametrize("var", ["$host", "$remote_addr",
                                 "$proxy_add_x_forwarded_for",
                                 "$http_upgrade", "$connection_upgrade",
                                 "$request_uri"])
def test_nginx_variables_survive_rendering(root, var):
    assert var in _render(root), f"{var} was eaten by envsubst"


# --- routing and TLS -------------------------------------------------------


def test_every_dot_in_the_deployment_regex_is_escaped(root):
    """server_name regexes match the whole Host header. An unescaped dot makes
    '.' match any character, so a lookalike hostname would route into this
    cluster and be served a certificate for it."""
    for line in _render(root).splitlines():
        m = re.search(r"server_name\s+~\^(.*)\$;", line)
        if not m:
            continue
        body = m.group(1).replace(r"\.", "")          # drop escaped dots
        body = re.sub(r"\[\^\.\]\+", "", body)        # and the label class
        assert "." not in body, f"unescaped dot in: {line.strip()}"


def test_the_internal_leg_stays_verified(root):
    """proxy_ssl_verify is what forces both internal certificates to be
    reissued in the same change that moves the domain. Turning it off would
    make the cutover 'work' while the proxy trusted anything at all."""
    t = _render(root)
    assert "proxy_ssl_verify              on;" in t
    assert "proxy_ssl_name                $host;" in t


def test_http_is_redirected_not_served(root):
    """gotcha 23: the platform is https and stays https while this redirect
    exists, or the two bounces form a loop."""
    assert re.search(r"return 301 https://\$host\$request_uri;", _render(root))


# --- the additive model ----------------------------------------------------


def test_a_legacy_domain_gets_its_own_blocks_on_its_own_certificate(root):
    """Rollback is swapping two variables, not reissuing anything.

    Both domains answer at once: the new one on Let's Encrypt, the old one on
    the CAIOS CA it already has. Nothing is deleted at any point, which is
    what makes this safe to do days before a recording.
    """
    # An .sslip.io name so the CAIOS CA branch of tls_for() is the one taken,
    # and "fixture" in every line so test_public_domain can tell a synthetic
    # domain from a hostname somebody typed in for real.
    t = _render(root, {"CAIOS_LEGACY_DOMAIN": "fixture.sslip.io"})
    assert "dashboard.fixture.sslip.io" in t
    assert r"~^[^.]+\.pacs-deployments\.fixture\.sslip\.io$" in t
    assert "/etc/nginx/certs/caios-public.pem" in t
    assert t.count("default_server") == 4, (
        "exactly one https block and the one :80 block may be default_server"
    )
