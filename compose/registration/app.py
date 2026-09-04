"""CAIOS registration approvals.

T6. A researcher signs up through Keycloak's own registration form and can
then log in — and reach nothing at all, because PAPI authorises on a realm
role they do not have. This service is how somebody grants it.

WHY THERE IS NO DATABASE
------------------------
"Pending" is not a state we store. A pending user is a realm user holding no
`access:<vo>:<level>` role. That single fact removes every hard part of a
registration system: nothing to keep in step with Keycloak, no row that
disagrees with reality, nothing to migrate, and no way for an approval to be
recorded here but not there. Approve is one role assignment, deny is one
disable, and Keycloak remains the only place any of it lives.

WHY IT IS NOT PART OF PAPI
--------------------------
PAPI is what the entire platform runs through. A fault in an admin console
used by one person a week must not be able to stop a demo. This is ~200 lines
in its own container: if it is broken or down, everything else is unaffected
and the demo accounts still work.

It is reached at `/registration/*` on the API hostname rather than a hostname
of its own, so it adds no DNS name, no certificate SAN and no new origin for
the browser to be told about.

WHAT IT IS TRUSTED WITH
-----------------------
A Keycloak service account holding `view-users` and `manage-users` — the
narrowest pair that can list users and assign one role. Deliberately not
`realm-admin`: an approval console must not be able to rewrite the realm that
login itself depends on.

Every request is authorised twice over. The caller's token is verified for
signature, issuer and audience exactly as PAPI verifies it, and then it must
carry `access:<vo>:ap-d`. The service account's own rights are never exposed
to a caller who does not have that.
"""

import os
import re

import httpx
import jwt
from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

# --- configuration, all from the environment -------------------------------

SCHEME = os.environ.get("CAIOS_SCHEME", "https")
AUTH_HOST = os.environ["CAIOS_AUTH_HOST"]
REALM = os.environ.get("KEYCLOAK_REALM", "caios")
VO = os.environ.get("CAIOS_VO", "vo.caios.ca")
CLIENT_ID = os.environ.get("KEYCLOAK_REGISTRATION_CLIENT", "caios-registration")
CLIENT_SECRET = os.environ["KEYCLOAK_REGISTRATION_SECRET"]

ISSUER = f"{SCHEME}://{AUTH_HOST}/realms/{REALM}"
ADMIN_API = f"{SCHEME}://{AUTH_HOST}/admin/realms/{REALM}"

# The role granted on approval, and the one required to grant it.
ROLE_USER = f"access:{VO}:ap-u"
ROLE_ADMIN = f"access:{VO}:ap-d"

# Same shape as PAPI's CORS list: an origin is scheme-exact, and a missing one
# is a wall the browser reports as a generic failure with nothing in our log.
CORS_ORIGINS = [
    o for o in os.environ.get("CAIOS_CORS_ORIGINS", "").split(",") if o.strip()
]

app = FastAPI(
    title="CAIOS registration approvals",
    description=__doc__,
    docs_url="/registration/docs",
    openapi_url="/registration/openapi.json",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)

security = HTTPBearer()

# Keycloak's signing keys. PyJWKClient caches them and refetches on rotation,
# so this is one HTTP call at first use rather than one per request.
_jwks = jwt.PyJWKClient(f"{ISSUER}/protocol/openid-connect/certs")


# --- who is calling --------------------------------------------------------


def require_admin(
    creds: HTTPAuthorizationCredentials = Depends(security),
) -> dict:
    """Verify the caller's token and require the administrator role.

    Verified the same way PAPI verifies it — signature, issuer and audience —
    because a token this service accepted but PAPI would not is a way for the
    two to disagree about who somebody is.
    """
    try:
        key = _jwks.get_signing_key_from_jwt(creds.credentials).key
        claims = jwt.decode(
            creds.credentials,
            key,
            algorithms=["RS256"],
            audience="account",
            issuer=ISSUER,
            options={"verify_exp": True, "verify_iss": True, "verify_aud": True},
        )
    except Exception as e:
        raise HTTPException(status_code=401, detail=str(e))

    roles = (claims.get("realm_access") or {}).get("roles") or []
    if ROLE_ADMIN not in roles:
        raise HTTPException(
            status_code=403,
            detail=(
                f"Approving registrations requires the {ROLE_ADMIN} role. "
                "Ask a platform administrator."
            ),
        )
    return claims


# --- talking to Keycloak ---------------------------------------------------


def _service_token() -> str:
    """A fresh client-credentials token for the service account.

    Not cached. These are cheap, this endpoint is used by one person at a time,
    and a cache is one more thing that can hold a token past a rotated secret.
    """
    r = httpx.post(
        f"{ISSUER}/protocol/openid-connect/token",
        data={
            "grant_type": "client_credentials",
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
        },
        timeout=20,
    )
    if r.status_code != 200:
        raise HTTPException(
            status_code=502,
            detail=(
                "The registration service could not authenticate to Keycloak. "
                "Check KEYCLOAK_REGISTRATION_SECRET against the "
                f"{CLIENT_ID} client. Keycloak said: {r.text[:200]}"
            ),
        )
    return r.json()["access_token"]


def _kc(method: str, path: str, **kw) -> httpx.Response:
    token = _service_token()
    r = httpx.request(
        method,
        f"{ADMIN_API}{path}",
        headers={"Authorization": f"Bearer {token}"},
        timeout=30,
        **kw,
    )
    if r.status_code >= 400:
        raise HTTPException(
            status_code=502,
            detail=f"Keycloak refused {method} {path}: {r.status_code} {r.text[:200]}",
        )
    return r


def _held_access_roles(user_id: str) -> list[dict]:
    """The full representations of the access roles this user holds.

    Representations rather than names, because removing a role mapping needs
    the whole object and re-fetching each one by name is a request this service
    account is not permitted to make (see _assignable_role below).

    Read from Keycloak every time rather than from anything we store, so the
    answer cannot be stale.
    """
    roles = _kc("GET", f"/users/{user_id}/role-mappings/realm").json()
    return [
        r for r in roles
        if re.match(rf"access:{re.escape(VO)}:.+$", r.get("name", ""))
    ]


def _access_levels(user_id: str) -> list[str]:
    """The access levels this user holds, e.g. ['ap-u']."""
    return [r["name"].rsplit(":", 1)[1] for r in _held_access_roles(user_id)]


def _assignable_role(user_id: str, name: str) -> dict:
    """The representation of a realm role this user does not have yet.

    Via the user's *available* role mappings rather than GET /roles/{name}.
    Reading a role definition directly requires `view-realm`, which this
    service account deliberately does not have — it holds only view-users and
    manage-users, the narrowest pair that can list accounts and change one
    role. This endpoint answers "what may I give this user", which is exactly
    the question being asked, and needs nothing beyond those two.
    """
    available = _kc("GET", f"/users/{user_id}/role-mappings/realm/available").json()
    for r in available:
        if r.get("name") == name:
            return r
    raise HTTPException(
        status_code=409,
        detail=(
            f"The role {name} is not available to assign to this account. "
            "It either already holds it, or the role is missing from the realm."
        ),
    )


# --- what a caller sees ----------------------------------------------------


class Account(BaseModel):
    id: str
    username: str
    email: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    created: int | None = None
    enabled: bool
    levels: list[str]
    state: str


def _describe(u: dict) -> Account:
    levels = _access_levels(u["id"])
    if not u.get("enabled", True):
        state = "denied"
    elif levels:
        state = "approved"
    else:
        state = "pending"
    return Account(
        id=u["id"],
        username=u.get("username", ""),
        email=u.get("email"),
        first_name=u.get("firstName"),
        last_name=u.get("lastName"),
        created=u.get("createdTimestamp"),
        enabled=u.get("enabled", True),
        levels=levels,
        state=state,
    )


@app.get("/registration/health")
def health():
    """Deliberately unauthenticated and deliberately shallow.

    It answers "is this container serving", which is what a health check is
    for. It does not call Keycloak: a health check that fails when a
    *dependency* is down turns one outage into two.
    """
    return {"status": "ok", "issuer": ISSUER, "vo": VO}


@app.get("/registration/accounts", response_model=list[Account])
def accounts(_: dict = Depends(require_admin)) -> list[Account]:
    """Every account, newest first, with the state its roles imply."""
    users = _kc("GET", "/users", params={"max": 500, "briefRepresentation": True}).json()
    out = [_describe(u) for u in users]
    out.sort(key=lambda a: (a.created or 0), reverse=True)
    return out


@app.get("/registration/pending", response_model=list[Account])
def pending(_: dict = Depends(require_admin)) -> list[Account]:
    """Accounts waiting on somebody. The console's whole job."""
    return [a for a in accounts(_) if a.state == "pending"]


@app.post("/registration/approve/{user_id}", response_model=Account)
def approve(user_id: str, _: dict = Depends(require_admin)) -> Account:
    """Grant ap-u. Never anything higher.

    An approval console that can mint administrators is a privilege-escalation
    path wearing a friendly name — the level is fixed here rather than taken
    from the request for exactly that reason.
    """
    user = _kc("GET", f"/users/{user_id}").json()
    if not user.get("enabled", True):
        _kc("PUT", f"/users/{user_id}", json={"enabled": True})

    # Idempotent: approving an already-approved account changes nothing rather
    # than failing, so a double click is harmless.
    if ROLE_USER not in [r["name"] for r in _held_access_roles(user_id)]:
        _kc(
            "POST",
            f"/users/{user_id}/role-mappings/realm",
            json=[_assignable_role(user_id, ROLE_USER)],
        )
    return _describe(_kc("GET", f"/users/{user_id}").json())


@app.post("/registration/deny/{user_id}", response_model=Account)
def deny(user_id: str, caller: dict = Depends(require_admin)) -> Account:
    """Disable the account and remove any access it holds.

    Disable rather than delete: a deleted account can be re-registered with
    the same address, and a denial that can be undone by signing up again is
    not a denial. It also leaves a record of the decision.

    Two things it refuses, because both are ways to lock everybody out of the
    platform with one click:
    """
    if user_id == caller.get("sub"):
        raise HTTPException(status_code=400, detail="You cannot deny your own account.")

    levels = _access_levels(user_id)
    if "ap-d" in levels:
        raise HTTPException(
            status_code=400,
            detail=(
                "That account is a platform administrator. Remove the "
                f"{ROLE_ADMIN} role in Keycloak first, deliberately."
            ),
        )

    held = _held_access_roles(user_id)
    if held:
        _kc("DELETE", f"/users/{user_id}/role-mappings/realm", json=held)
    _kc("PUT", f"/users/{user_id}", json={"enabled": False})
    return _describe(_kc("GET", f"/users/{user_id}").json())
