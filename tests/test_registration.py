"""Self-registration, and the approval that turns an account into access.

T6. Checklist item 4 — a registration form and an admin console.

The design decision worth holding onto is that **"pending" is not stored
anywhere**. A pending user is simply a realm user who holds no
`access:<vo>:<level>` role: Keycloak lets them log in, PAPI answers 401 on
everything, and the dashboard shows them a waiting message. Approval is one
role assignment; denial is one disable.

No database, nothing to keep in step with Keycloak, and nothing to migrate.
Every test below exists to stop that becoming something more complicated.

Offline: these read the repository. The live half is
`scripts/check-registration.sh`.
"""

import json
import re
from pathlib import Path

import pytest

VO = "vo.caios.ca"
REALM_TEMPLATE = "configs/keycloak/caios-realm.json.template"
BOOTSTRAP = "scripts/keycloak-bootstrap.sh"


def _realm(root):
    """The realm template with its ${...} placeholders neutralised."""
    t = (root / REALM_TEMPLATE).read_text()
    return json.loads(re.sub(r"\$\{[^}]+\}", "PLACEHOLDER", t))


# --- the realm -------------------------------------------------------------


def test_self_registration_is_on(root):
    assert _realm(root)["registrationAllowed"] is True


def test_email_verification_is_off_and_says_why(root):
    """There is no SMTP server on this platform.

    Requiring verification would leave every registration waiting on a mail
    that can never arrive — a form that silently never works. The human
    approval step is the check that verification would otherwise be.
    """
    r = _realm(root)
    assert r["verifyEmail"] is False
    assert "SMTP" in r["_comment_registration"]


def test_registration_grants_no_access(root):
    """The realm defines no default role that would let a new account in.

    This is the whole safety property of turning registration on: account
    CREATION is open, access is not. If a default role ever appears here that
    matches access:<vo>:<level>, every stranger who signs up can deploy.
    """
    r = _realm(root)
    default_role = r.get("defaultRole") or {}
    composites = default_role.get("composites") or {}
    for name in composites.get("realm") or []:
        assert not re.match(r"access:[^:]+:", name), (
            f"the realm's default role grants {name!r} to every new account"
        )
    for name in r.get("defaultRoles") or []:
        assert not re.match(r"access:[^:]+:", name)


def test_the_admin_level_exists(root):
    """ap-d is what the approval service requires. It is not invented here —
    it is upstream's top access level and the realm already defined it."""
    names = [x["name"] for x in _realm(root)["roles"]["realm"]]
    assert f"access:{VO}:ap-d" in names
    assert f"access:{VO}:ap-u" in names


# --- the bootstrap script --------------------------------------------------


def _bootstrap(root):
    return (root / BOOTSTRAP).read_text()


def test_realm_settings_reach_the_live_realm(root):
    """Keycloak imports a realm only on first start.

    Editing the template and re-rendering changes nothing on a running system.
    Same trap as sslRequired in T5, same answer: apply through the admin API.
    """
    t = _bootstrap(root)
    assert 'kc update "realms/${REALM}"' in t
    assert "registrationAllowed=true" in t


def test_there_is_an_administrator_account(root):
    t = _bootstrap(root)
    assert re.search(r'"platform-admin:[^"]*:ap-d"', t), (
        "no account holds ap-d, so nobody can approve anybody"
    )


def test_every_demo_account_declares_its_level(root):
    """The level is the last field of the role PAPI parses; a missing one
    would silently assign nothing."""
    t = _bootstrap(root)
    users = re.findall(r'^\s+"([a-z-]+:[^"]*)"\s*$', t, re.M)
    assert users, "the USERS table is gone"
    for entry in users:
        parts = entry.split(":")
        assert len(parts) == 5, f"{entry!r} has no access level"
        assert parts[4] in ("ap-u", "ap-d"), parts[4]


def test_the_service_account_is_not_a_realm_admin(root):
    """view-users and manage-users are the narrowest pair that allows listing
    users and assigning one role.

    realm-admin would let the approval service rewrite the realm that login
    itself depends on — a registration console should not be able to change
    how anybody signs in.
    """
    t = _bootstrap(root)
    assert "--cclientid realm-management" in t
    # The roles actually granted, not every mention of one — the comment above
    # the loop names realm-admin in order to say it is NOT used.
    granted = re.search(r"^for r in ([a-z-]+(?: [a-z-]+)*); do$", t, re.M)
    assert granted, "the role-granting loop is gone"
    roles = set(granted.group(1).split())
    assert roles == {"view-users", "manage-users"}, (
        f"the service account is granted {sorted(roles)}. Anything wider — "
        f"realm-admin above all — would let a registration console rewrite the "
        f"realm that login itself depends on."
    )


def test_the_service_client_cannot_be_used_as_a_login(root):
    """It is a machine credential. Standard flow and direct grants stay off, so
    the secret cannot be turned into a user session."""
    t = _bootstrap(root)
    block = t[t.index("clientId=caios-registration"):]
    block = block[: block.index("REG_UUID=", 10)] if "REG_UUID=" in block[10:] else block
    assert '-s "standardFlowEnabled=false"' in block
    assert '-s "directAccessGrantsEnabled=false"' in block
    assert '-s "publicClient=false"' in block


def test_the_secret_is_required_not_defaulted(root):
    """A service account with realm-management rights must never come up with
    a value somebody could guess from the repository."""
    t = _bootstrap(root)
    assert ': "${KEYCLOAK_REGISTRATION_SECRET:?' in t


def test_the_secret_is_documented_and_empty_in_the_template(root):
    t = (root / "configs" / "env" / "caios.env.template").read_text()
    assert re.search(r"^KEYCLOAK_REGISTRATION_SECRET=$", t, re.M), (
        "the template must carry the key with no value — a committed secret "
        "is a committed secret even if it is only a placeholder people reuse"
    )
    assert re.search(r"^CAIOS_PW_PLATFORM_ADMIN=$", t, re.M)


def test_no_secret_is_committed(root):
    """The real values live only in the gitignored env file."""
    t = (root / "configs" / "env" / "caios.env.template").read_text()
    for line in t.splitlines():
        if line.startswith(("KEYCLOAK_", "CAIOS_PW_")) and "=" in line:
            key, _, value = line.partition("=")
            assert value in ("", "admin", "caios"), (
                f"{key} carries a value in the committed template: {value!r}"
            )
