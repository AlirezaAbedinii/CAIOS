"""Signing out signs you out, and what a new account is first told.

Two faults reported on 2026-09-05, after the first real person registered:

  * **Logging out did not log you out.** Log out, log in, and the dashboard
    silently returned the same user without ever showing the login form.
  * The access-level popup — the first sentence a new account reads — linked to
    AI4EOSC's documentation.

Offline: these read the repository. The live half of the first one is a browser,
and the Keycloak half was verified with a full authorization-code flow.
"""

import json
import re

import pytest

PATCH = "patches/ai4-dashboard/0014-logout-ends-the-session.patch"
I18N = "configs/dashboard/i18n/en.caios.json"


def _patch(root):
    return (root / PATCH).read_text()


def _strings(root):
    return json.loads((root / I18N).read_text())


# --- signing out -----------------------------------------------------------


def test_logout_ends_the_session_at_keycloak(root):
    """logOut(true) is `noRedirectToLogoutUrl`.

    It forgets the tokens in the current tab and leaves Keycloak's session
    cookie untouched, so the next sign-in finds a live SSO session and returns
    immediately with a fresh code. Verified against the running Keycloak with a
    full authorization-code flow: with the cookie alive the authorization
    endpoint answers 302-with-code; after end_session it serves the login form.
    """
    t = _patch(root)
    assert "-            this.oauthService.logOut(true);" in t
    assert "+            this.oauthService.logOut();" in t


def test_the_id_token_survives_long_enough_to_be_sent(root):
    """OAuthStorage is localStorage, so clearing it first destroys the
    id_token that end_session needs as id_token_hint."""
    src = (root / "build" / "ai4-dashboard" / "src" / "app" / "core"
           / "services" / "auth" / "auth.service.ts")
    if not src.is_file():
        pytest.skip("build/ai4-dashboard absent — run scripts/apply-patches.sh")
    body = src.read_text()
    body = body[body.index("    logout() {"):]
    body = body[: body.index("\n    isAuthenticated()")]

    # Statements only. The comment explaining this ordering names both calls,
    # so matching raw text would find the prose rather than the code.
    code = "\n".join(
        line for line in body.splitlines() if not line.lstrip().startswith("//")
    )

    def at(needle):
        assert needle in code, f"{needle} is gone from logout()"
        return code.index(needle)

    assert at("this.oauthService.logOut();") < at("localStorage.clear();"), (
        "localStorage.clear() runs before logOut(), which takes the id token "
        "with it and leaves Keycloak a logout it cannot attribute to anybody"
    )
    # And the keys worth keeping are read before anything is cleared.
    assert at("variables[key] = localStorage.getItem(key)") < at(
        "this.oauthService.logOut();"
    )


def test_the_storage_assumption_is_still_true(root):
    """The ordering above is only necessary because tokens live in
    localStorage. If that ever changes, the comment is wrong and this test
    should be the thing that says so."""
    src = (root / "build" / "ai4-dashboard" / "src" / "app" / "app.providers.ts")
    if not src.is_file():
        pytest.skip("build/ai4-dashboard absent — run scripts/apply-patches.sh")
    t = src.read_text()
    assert re.search(r"function storageFactory\(\)[^}]*return localStorage;", t, re.S)


def test_the_return_address_is_stated_not_inferred(root):
    """Without postLogoutRedirectUri, Keycloak does not come back at all — it
    shows its own 'you are logged out' page, which is somebody else's branding
    in the middle of a demo. The library's fallback flag has changed default
    between releases, so it is stated."""
    t = _patch(root)
    assert "postLogoutRedirectUri: window.location.origin," in t


def test_navigation_does_not_race_the_redirect(root):
    """logOut() navigates away, so the router call belongs in the branch where
    there is no redirect."""
    t = _patch(root)
    assert "+        } else {" in t
    assert "+            this.router.navigateByUrl('/catalog/modules');" in t



# --- what a new account is told --------------------------------------------
#
# Both strings are deep-merged over upstream's en.json, so neither needs a
# patch. Both are asserted by content rather than by banning a domain: the
# footer's SIDENAV.DOCUMENTATION link to docs.ai4os.eu is deliberate and
# recorded, because AI4OS is the stack this platform is built on.


def test_the_access_popup_sends_nobody_off_the_platform(root):
    """The first sentence a newly-registered account reads.

    It fires whenever the access level changes, which since T6 includes the
    moment somebody signs up — so its link to AI4EOSC's documentation was
    reaching the people least able to make sense of it.
    """
    body = _strings(root)["PROFILE"]["ACCESS-MODAL-BODY"]
    assert "<a " not in body and "href" not in body, "the popup still links out"
    assert "ai4os" not in body.lower() and "ai4eosc" not in body.lower()
    assert "approve" in body.lower(), (
        "a new account's popup should say what happens next, which is that "
        "somebody has to approve it"
    )


def test_the_popup_keeps_the_interpolation_it_is_given(root):
    """app.component.ts passes currentHighestRole into the translation. Drop
    the placeholder and the sentence silently loses its subject."""
    body = _strings(root)["PROFILE"]["ACCESS-MODAL-BODY"]
    assert "{{currentHighestRole}}" in body
