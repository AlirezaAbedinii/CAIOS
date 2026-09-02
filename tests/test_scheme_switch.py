"""One variable decides the scheme, and nothing hardcodes it behind its back.

T5. `CAIOS_SCHEME` in configs/env/caios.env is the only place the platform's
scheme is written down. Everything else derives from it: Caddy's site blocks,
Keycloak's issuer, PAPI's advertised endpoints, the dashboard's apiURL, the
Traefik router tags, the federated-learning bundles, every check script.

That property is worth a test because a single missed spot does not fail
loudly. A stale `https://` in the issuer chain is a 401 on everything with no
message that names the cause; a stale one in a Traefik router tag is a
deployment that comes up healthy with no route to it.

The exceptions are deliberate and named here, so adding another one is a
decision rather than an oversight.
"""

import json
import re
import subprocess

import pytest

# --- what the scheme must reach -------------------------------------------

# The federated-learning router keeps TLS under both schemes. It is gRPC on
# :443 spoken by Flower clients inside cluster workspaces, which already carry
# the CA in their bundle (D-43) — so it is a barrier to nobody, and h2c from
# client to Traefik is not a thing to discover on demo day. D-67.
FEDSERVER_EXEMPT = "${JOB_UUID}-fedserver.tls=true"

# Job templates for tools this cluster cannot host, so their scheme is moot:
# CVAT needs ~71 GB on one node (gotcha 9) and NVFLARE needs TCP 8002-8003
# open (gotcha 8). Both are listed in the dashboard's demoUnavailable.
UNHOSTABLE = {"ai4os-cvat", "ai4os-nvflare"}

SCHEME_AWARE_JOB_TEMPLATES = [
    "etc/modules/nomad.hcl",
    "etc/tools/ai4os-dev-env/nomad.hcl",
    "etc/tools/ai4os-federated-server/nomad.hcl",
    "etc/tools/ai4os-ai4life-loader/nomad.hcl",
    "etc/tools/ai4os-llm/nomad.hcl",
    "etc/try_me/nomad.hcl",
]


def _env(root):
    """configs/env/caios.env as a dict, or skip if it is not there."""
    f = root / "configs" / "env" / "caios.env"
    if not f.is_file():
        pytest.skip("configs/env/caios.env absent (it is gitignored)")
    out = {}
    for line in f.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip()
    return out


def test_scheme_is_set_and_is_one_of_two(root):
    assert _env(root).get("CAIOS_SCHEME") in ("http", "https")


def test_template_carries_the_variable_too(root):
    """A fresh install must get the switch, not a hardcoded scheme."""
    t = (root / "configs" / "env" / "caios.env.template").read_text()
    assert re.search(r"^CAIOS_SCHEME=(http|https)$", t, re.M), (
        "caios.env.template has no CAIOS_SCHEME. A fresh install would render "
        "configs with an empty scheme and every URL would be '://host'."
    )


def test_render_configs_rejects_a_nonsense_scheme(root):
    """Caught at render time, not three services later."""
    s = (root / "scripts" / "render-configs.sh").read_text()
    assert "expected http or https" in s


# --- the rendered control plane -------------------------------------------


def test_caddyfile_is_rendered_not_mounted(root):
    """compose must mount the rendered Caddyfile, or the scheme cannot change.

    The scheme decides the file's structure — which site block carries the
    certificate and which carries the bounce — so Caddy's own {$ENV}
    substitution cannot express it.
    """
    compose = (root / "compose" / "docker-compose.yml").read_text()
    assert "./generated/caddy/Caddyfile:/etc/caddy/Caddyfile:ro" in compose
    assert "./caddy/Caddyfile:/etc/caddy/Caddyfile:ro" not in compose
    assert (root / "compose" / "caddy" / "Caddyfile.template").is_file()


def test_caddy_template_serves_both_schemes(root):
    """Both schemes answer: the active one serves, the other bounces to it.

    Not tidiness. Chrome upgrades http:// navigations to https:// on its own
    and only falls back if the upgrade FAILS — and ours would succeed. Without
    the bounce a visitor lands on a valid TLS page whose calls to the http://
    API are then blocked as mixed content.
    """
    t = (root / "compose" / "caddy" / "Caddyfile.template").read_text()
    for host in ("DASHBOARD", "API", "AUTH", "VAULT"):
        assert "${CAIOS_SCHEME}://${CAIOS_%s_HOST}" % host in t
        assert "${CAIOS_ALT_SCHEME}://${CAIOS_%s_HOST}" % host in t
    assert "redir ${CAIOS_SCHEME}://{host}{uri} 302" in t


def test_no_control_plane_hostname_is_hardcoded_https(root):
    """The four places a stale scheme becomes a silent 401 on everything."""
    compose = (root / "compose" / "docker-compose.yml").read_text()
    for key in ("KC_HOSTNAME", "KEYCLOAK_URL", "API_SERVER", "ISSUER"):
        line = next(
            (l for l in compose.splitlines() if l.strip().startswith(key + ":")), None
        )
        assert line, f"{key} is gone from compose"
        assert "${CAIOS_SCHEME}" in line, (
            f"{key} hardcodes a scheme. PAPI compares the issuer character by "
            f"character; a mismatch is 401 on every request with nothing in the "
            f"log that names the cause.\n  {line.strip()}"
        )


def test_papi_conf_advertises_the_configured_scheme(root):
    """Every endpoint the dashboard shows is built in one place."""
    src = (root / "build" / "ai4-papi" / "ai4papi" / "nomad_utils.py")
    if not src.is_file():
        pytest.skip("build/ai4-papi absent — run scripts/apply-patches.sh")
    t = src.read_text()
    assert 'f"https://{url}"' not in t
    assert 'f"{papiconf.CAIOS_SCHEME}://{url}"' in t


def test_papi_cors_lists_both_schemes(root):
    """An origin is scheme-exact, and a missing one is a CORS wall.

    A CORS failure reaches the user as "Error calling the API" on every page,
    with nothing in PAPI's log to explain it. Listing both costs nothing.
    """
    t = (root / "configs" / "papi" / "main.yaml").read_text()
    assert "- https://dashboard.${CAIOS_PUBLIC_IP}.sslip.io" in t
    assert "- http://dashboard.${CAIOS_PUBLIC_IP}.sslip.io" in t


def test_keycloak_client_accepts_both_schemes(root):
    """The dashboard sends window.location.origin as its redirect URI."""
    t = (root / "configs" / "keycloak" / "caios-realm.json.template").read_text()
    assert '"https://${CAIOS_DASHBOARD_HOST}/*"' in t
    assert '"http://${CAIOS_DASHBOARD_HOST}/*"' in t
    assert '"sslRequired": "${KEYCLOAK_SSL_REQUIRED}"' in t


def test_realm_settings_are_applied_to_the_live_realm(root):
    """Keycloak imports a realm only on first start.

    Editing the template and re-rendering changes nothing on a running system:
    the importer skips silently and everything keeps working with the old
    values. sslRequired and the redirect URIs have to go through the admin API.
    """
    t = (root / "scripts" / "keycloak-bootstrap.sh").read_text()
    assert 'kc update "realms/${REALM}" -s "sslRequired=${SSL_REQUIRED}"' in t
    assert "redirectUris=" in t and "webOrigins=" in t


def test_vault_issuer_follows_the_scheme_and_drops_the_ca_on_http(root):
    """Vault rejects a CA supplied for a non-TLS discovery URL."""
    t = (root / "compose" / "vault" / "bootstrap.sh").read_text()
    assert 'ISSUER="${SCHEME}://${CAIOS_AUTH_HOST}/realms/${KEYCLOAK_REALM}"' in t
    assert 'if [ "$SCHEME" = "https" ]; then' in t


# --- the deployment tier ---------------------------------------------------


@pytest.mark.parametrize("rel", SCHEME_AWARE_JOB_TEMPLATES)
def test_job_templates_use_the_router_placeholder(root, rel):
    f = root / "build" / "ai4-papi" / rel
    if not f.is_file():
        pytest.skip("build/ai4-papi absent — run scripts/apply-patches.sh")
    t = f.read_text()
    assert "${CAIOS_ROUTER_TLS}" in t, f"{rel} has no scheme-driven router tag"
    leftover = [
        l.strip()
        for l in t.splitlines()
        if "tls=true" in l and FEDSERVER_EXEMPT not in l
    ]
    assert not leftover, (
        f"{rel} still hardcodes TLS on a router:\n  " + "\n  ".join(leftover)
    )


def test_the_federated_server_keeps_tls(root):
    """The one exemption, and it is deliberate — see D-67."""
    f = root / "build" / "ai4-papi" / "etc" / "tools" / "ai4os-federated-server" / "nomad.hcl"
    if not f.is_file():
        pytest.skip("build/ai4-papi absent — run scripts/apply-patches.sh")
    t = f.read_text()
    assert FEDSERVER_EXEMPT in t, (
        "The fedserver router lost its TLS tag. Its clients speak gRPC on :443 "
        "with the CA from their bundle; plain h2c through Traefik is untested "
        "here and this is the headline demo."
    )
    assert "D-67" in t, "the exemption must say why, or someone will 'fix' it"


def test_the_mounted_llm_template_matches(root):
    """configs/ overrides build/ for the LLM tool, so both have to change."""
    t = (root / "configs" / "papi" / "tools" / "ai4os-llm" / "nomad.hcl").read_text()
    assert "${CAIOS_ROUTER_TLS}" in t
    assert "tls=true" not in t


def test_the_placeholder_is_substituted_at_load_time(root):
    """safe_substitute leaves an unknown ${...} in place, and Traefik ignores
    a tag it cannot parse — so a missed substitution is a healthy deployment
    with no route at all. It is done once, where every template is read."""
    f = root / "build" / "ai4-papi" / "ai4papi" / "conf.py"
    if not f.is_file():
        pytest.skip("build/ai4-papi absent — run scripts/apply-patches.sh")
    t = f.read_text()
    assert 'raw.replace("${CAIOS_ROUTER_TLS}", CAIOS_ROUTER_TLS)' in t
    assert 'CAIOS_ROUTER_TLS = "tls=true" if CAIOS_SCHEME == "https" else "entrypoints=web"' in t


def test_unhostable_tools_are_left_alone_on_purpose(root):
    """CVAT and NVFLARE cannot run on this cluster, so their scheme is moot.

    Asserted so the omission is a recorded decision rather than something
    half-done that looks like an oversight.
    """
    for tool in sorted(UNHOSTABLE):
        f = root / "build" / "ai4-papi" / "etc" / "tools" / tool / "nomad.hcl"
        if not f.is_file():
            pytest.skip("build/ai4-papi absent — run scripts/apply-patches.sh")
        assert "${CAIOS_ROUTER_TLS}" not in f.read_text()
        conf = json.loads((root / "configs" / "dashboard" / "caios.json").read_text())
        assert tool in conf["demoUnavailable"]


# --- Traefik ---------------------------------------------------------------


def test_traefik_template_has_no_redirect(root):
    """Entrypoint-level, so it fires before routing and no router can opt out."""
    t = (root / "ansible" / "templates" / "traefik.j2").read_text()
    assert "redirections" not in t.split("{#", 1)[-1].split("#}", 1)[-1], (
        "ansible/templates/traefik.j2 still redirects web to websecure"
    )
    assert "[entryPoints.web]" in t


def test_verify_cluster_guards_the_redirect(root):
    """Re-running playbook-nomad.yml puts the redirect back — same shape of
    regression as the docuum threshold (gotcha 14), same shape of guard."""
    t = (root / "scripts" / "verify-cluster.sh").read_text()
    assert "playbook-traefik.yml" in t
    assert 'grep -q "redirections"' in t


# --- the dashboard ---------------------------------------------------------


def test_oidc_accepts_an_http_issuer(root):
    """angular-oauth2-oidc rejects an http:// issuer before sending a request.

    requireHttps defaults to 'remoteOnly', loadDiscoveryDocument() rejects, and
    the dashboard renders a login page that can never complete.
    """
    f = (root / "build" / "ai4-dashboard" / "src" / "app" / "core" / "services"
         / "auth" / "auth.service.ts")
    if not f.is_file():
        pytest.skip("build/ai4-dashboard absent — run scripts/apply-patches.sh")
    t = f.read_text()
    assert "authCodeFlowConfig.requireHttps" in t
    assert "this.appConfigService.issuer.startsWith('https://')" in t, (
        "requireHttps must be DERIVED from the issuer, not switched off — that "
        "is what lets one image serve both schemes, which is what makes the "
        "rollback a variable rather than a rebuild."
    )


# --- the scripts -----------------------------------------------------------


SCHEME_AWARE_SCRIPTS = [
    "check-branding.sh",
    "check-home-page.sh",
    "check-catalogue.sh",
    "check-dashboard.sh",
    "check-llm-config.sh",
    "check-llm-deploy.sh",
    "check-llm-ui.sh",
    "get-token.sh",
    "build-fl-bundles.sh",
    "deploy-fl-demo.sh",
    "vault-bootstrap.sh",
    "oscar-submit.sh",
]


@pytest.mark.parametrize("name", SCHEME_AWARE_SCRIPTS)
def test_scripts_derive_the_scheme(root, name):
    t = (root / "scripts" / name).read_text()
    assert 'SCHEME="${CAIOS_SCHEME:-https}"' in t, (
        f"{name} does not read CAIOS_SCHEME. A check that probes the wrong "
        f"scheme reports a broken platform that is fine, or the reverse."
    )
    hardcoded = [
        l.strip()
        for l in t.splitlines()
        if re.search(r'https://\$\{CAIOS_(API|AUTH|DASHBOARD|VAULT)_HOST', l)
        # keycloak-bootstrap registers both schemes on purpose; nothing else may.
    ]
    assert not hardcoded, f"{name} still hardcodes https:\n  " + "\n  ".join(hardcoded)


@pytest.mark.parametrize("name", SCHEME_AWARE_SCRIPTS + ["render-configs.sh",
                                                        "keycloak-bootstrap.sh",
                                                        "verify-cluster.sh"])
def test_scripts_parse(root, name):
    r = subprocess.run(["bash", "-n", str(root / "scripts" / name)],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
