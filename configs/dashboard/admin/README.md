# The registration console

CAIOS-owned Angular, staged into `src/app/modules/admin/` by
`scripts/build-dashboard.sh`. **Editing the copy under `build/` does nothing
that survives the next build.**

Same arrangement as `configs/dashboard/home/` and for the same reason: this
creates only new files, so there is nothing upstream can move underneath it,
and a patch of this size would not be reviewable (D-46). The only upstream
edits it needs are two small ones:

| Patch | What it does |
|---|---|
| `ai4-dashboard/0011-admin-route.patch` | routes `/admin` here |
| `ai4-dashboard/0013-admin-sidenav.patch` | a sidenav entry, for `ap-d` only |

Its strings live in `configs/dashboard/i18n/en.caios.json` under `ADMIN`, and
the sidenav labels under `SIDENAV`.

---

## What it is a view of

Nothing here holds state. The page reads the approval service
(`compose/registration/app.py`), which reads Keycloak, and **an account's state
is the access it holds**:

| The account holds | State |
|---|---|
| no `access:<vo>:<level>` role | `pending` |
| any such role | `approved` |
| disabled | `denied` |

Approving grants `access:<vo>:ap-u`. Denying removes what is held and disables
the account — not deletes it, because an account that can be re-registered with
the same address the next minute has not been denied.

## Three decisions worth not re-litigating

**No route guard.** Every call the page makes requires `access:<vo>:ap-d` at
the service. A guard here would be a second place where "who may approve" is
decided, and two places can disagree. A non-administrator who types `/admin`
gets a page that cannot load anything, which is the correct outcome reached the
correct way.

**Hidden in the sidenav, not disabled.** The opposite of the choice made for
`try-me` and `batch`, deliberately. Those are platform capabilities this
deployment cannot run, and saying so is honest. This is a capability the
*viewer* does not have, and advertising it to every researcher only invites a
click that goes nowhere.

**Two lists, not a filter.** "Who is waiting" is the question the page exists to
answer, and it should be answered before anybody touches a control.

## Changing it

The live check is `bash scripts/check-registration.sh`, which registers a
throwaway account through Keycloak's real form, walks it through approval and
denial, and deletes it. The offline checks are in `tests/test_registration.py`.
