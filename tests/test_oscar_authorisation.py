"""OSCAR authorises on a group, and errors from it must be readable.

Found 2026-09-08: a newly-registered account opened the Inference page and got
a red "Error calling the API" banner every five seconds. Two independent faults
were stacked, and the first one hid the second for weeks.

  1. **Every OSCAR failure arrived as the same blank 500.** PAPI put the
     exception object in `HTTPException(detail=...)`; FastAPI could not
     serialise it, raised `TypeError` inside its own exception handler, and
     returned a bare 500 with the original error destroyed. The only surviving
     copy was PAPI's traceback.

  2. **Underneath it, OSCAR was answering 401.** It picks the claim it
     authorises on by the NAME OF THE REALM — anything not `egi` or `ai4eosc`
     means `group_membership` — so the `access:<vo>:<level>` role every CAIOS
     token carries is invisible to it. A `oscar-users` group and a claim mapper
     were created by hand during Stage O2 and never written down as code, so
     every account created afterwards was refused.

The Inference page polls every 5 seconds, which is why one unauthorised account
produced an unending banner rather than a single error.
"""

import json
import re

import pytest

PATCH = "patches/ai4-papi/0019-oscar-errors-are-readable.patch"
BOOTSTRAP = "scripts/keycloak-bootstrap.sh"
SERVICE = "compose/registration/app.py"
GROUP = "oscar-users"


# --- the error must survive being reported ---------------------------------


def test_an_oscar_error_is_a_string_not_an_object(root):
    """`detail=e` is the whole fault: an exception is not JSON."""
    t = (root / PATCH).read_text()
    assert "-                detail=e," in t
    assert "+                detail=str(e)," in t


def test_no_exception_object_is_left_in_any_detail(root):
    """The same mistake twice in the same function; both branches fixed."""
    src = root / "build" / "ai4-papi" / "ai4papi" / "routers" / "v1" / "inference" / "oscar.py"
    if not src.is_file():
        pytest.skip("build/ai4-papi absent — run scripts/apply-patches.sh")
    body = src.read_text()
    assert re.search(r"detail=e\s*,", body) is None, (
        "an exception object is still being handed to HTTPException(detail=...)"
    )


def test_the_message_names_the_upstream_status_and_url(root):
    """What turns 'something went wrong' into a diagnosis."""
    t = (root / PATCH).read_text()
    assert "OSCAR) answered" in t
    assert 'getattr(getattr(e, "response", None), "status_code", None)' in t


def test_an_upstream_failure_does_not_eject_the_user(root):
    """502, not 401/403.

    The dashboard's error interceptor sends any 401 or 403 to /forbidden. On a
    page that polls every five seconds that is not an error message, it is
    being thrown off the page repeatedly.
    """
    t = (root / PATCH).read_text()
    assert "+                status_code=502," in t
    assert "+                status_code=500," not in t


# --- the group OSCAR actually reads ----------------------------------------


def test_the_group_and_its_mapper_are_created_by_script(root):
    """They existed only in the live realm.

    Rebuilding from the template would have silently lost serverless inference
    for everybody, with nothing to notice it.
    """
    t = (root / BOOTSTRAP).read_text()
    assert f'OSCAR_GROUP="{GROUP}"' in t
    assert "oidc-group-membership-mapper" in t
    assert 'config.\\"claim.name\\"=group_membership' in t


def test_the_claim_carries_no_leading_slash(root):
    """full.path=false, or the claim reads ["/oscar-users"] and OSCAR — which
    compares the strings exactly — refuses everybody."""
    t = (root / BOOTSTRAP).read_text()
    assert 'config.\\"full.path\\"=false' in t


def test_every_scripted_account_joins_the_group(root):
    """Including platform-admin, which T6 created and which was refused by
    OSCAR until this was scripted."""
    t = (root / BOOTSTRAP).read_text()
    assert "groups/${GROUP_ID}" in t


def test_approval_grants_the_group_as_well_as_the_role(root):
    """The role is access to the platform; the group is access to serverless
    inference. One without the other is an account that works everywhere except
    the Inference page, where it fails every five seconds."""
    t = (root / SERVICE).read_text()
    approve = t[t.index("def approve("):t.index("def deny(")]
    assert "_oscar_group()" in approve
    assert 'f"/users/{user_id}/groups/' in approve


def test_denial_takes_the_group_back(root):
    t = (root / SERVICE).read_text()
    deny = t[t.index("def deny("):]
    assert "_oscar_group()" in deny


def test_a_missing_group_is_an_actionable_refusal(root):
    """Approving into a half-working state silently is worse than refusing."""
    t = (root / SERVICE).read_text()
    assert "status_code=409" in t
    assert "keycloak-bootstrap.sh" in t


def test_the_reason_the_realm_name_matters_is_written_down(root):
    """OSCAR chooses the claim by a substring match on the issuer. Had the
    realm been named ai4eosc, realm roles would have worked untouched — the
    realm's NAME is load-bearing and nothing upstream documents it."""
    t = (root / BOOTSTRAP).read_text()
    assert "/realms/egi" in t and "/realms/ai4eosc" in t
    assert "group_membership" in t


# --- the pipefail trap that bit twice in one day ---------------------------


def test_no_grep_q_on_a_pipe_under_pipefail(root):
    """`cmd | grep -q` reports FAILURE ON SUCCESS when pipefail is set.

    grep -q exits the moment it matches, the writer dies of SIGPIPE, and
    pipefail returns the writer's status. It cost two debugging rounds in one
    day — once in check-registration.sh, once in keycloak-bootstrap.sh — so it
    is now a test rather than a lesson.
    """
    for name in ("keycloak-bootstrap.sh", "check-registration.sh"):
        path = root / "scripts" / name
        for n, line in enumerate(path.read_text().splitlines(), 1):
            if line.lstrip().startswith("#"):
                continue
            # A here-string is fine; only a real pipe closes early.
            if re.search(r"\|\s*grep\s+-[a-zA-Z]*q", line):
                pytest.fail(
                    f"{name}:{n} pipes into `grep -q` under `set -o pipefail`, "
                    f"which fails when the pattern IS found:\n    {line.strip()}"
                )
