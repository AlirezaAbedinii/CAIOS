# Patches

Minimal source edits to upstream, applied at container build time. Every patch
here exists because a value that *should* be configuration is hardcoded in
Python or TypeScript.

**These are the entire delta between AI4OS and CAIOS at the code level.** Keep
it that way — it is what makes "we deploy AI4OS, we do not fork it" true, and
it is what lets us pull upstream fixes without a merge nightmare.

Each patch is pinned to the upstream commit it was written against. If
`scripts/clone-vendor.sh` moves to a newer SHA and a patch fails to apply, read
the patch, not the error.

## Applying

```bash
bash scripts/apply-patches.sh
```

Copies `vendor/<repo>` to `build/<repo>` and applies patches there. `vendor/`
is never modified.

## What each patch does and why it cannot be configuration

### `ai4-papi/0001-keycloak-url.patch` — pinned to `e80a2b7`

`ai4papi/auth.py:30` hardcodes:

```python
KEYCLOAK_URL = "https://login.cloud.ai4eosc.eu/realms/ai4eosc"
```

Not in `main.yaml`, not an environment variable. PAPI validates every incoming
token's signature and issuer against this URL, so without the patch our
Keycloak's tokens are rejected and nothing authenticates. The patch reads it
from `KEYCLOAK_URL` with the upstream value as fallback.

### `ai4-papi/0002-vault-addr.patch` — pinned to `e80a2b7`

`ai4papi/routers/v1/secrets.py:21` hardcodes:

```python
VAULT_ADDR = "https://secrets.services.ai4os.eu:8200/"
```

This matters more than it looks. Deploying the **federated learning server**
calls `create_secret()` and `create_vault_token()` before it ever contacts
Nomad (`routers/v1/deployments/tools.py:377-392`). Against AI4EOSC's Vault, our
Keycloak's token is rejected — so the headline feature fails at PAPI, with an
error that looks nothing like "wrong Vault". Same treatment: read from
`VAULT_ADDR`, keep the upstream default.

### `ai4-nomad_tests/0001-namespaces.patch` — pinned to `HEAD` (unversioned repo)

`ai4_nomad_tests/conf.py` and `tests/node/cpu.py:83` hardcode the namespace list
`["ai4eosc", "imagine", "tutorials"]` and a matching domain map. With our
namespace, the intersection is empty, the Traefik reachability half of the test
quietly tests nothing, and the node is still marked ready.

That matters because this test suite is not optional: it is the only thing that
sets `meta.status=ready` on each node, and every PAPI job template requires it.
Without the patch we get a cluster that passes its own tests and then fails
every real deployment.

### `ai4-dashboard` — deliberately **not** patched for MVP

The dashboard has hardcoded `cloud.ai4eosc.eu` endpoints, but on inspection
none of them need a source patch to get the MVP demo right.

**The OIDC issuer looks like it needs one and does not.**
`core/services/auth/auth.config.ts:5` hardcodes AI4EOSC's realm, but
`core/services/auth/auth.service.ts:99-104` overwrites it at runtime from the
app config, which `docker/Dockerfile.prod` fills from the `ISSUER` environment
variable at container start. Setting `ISSUER` is enough.

**Everything visible in a walkthrough is tenant configuration, not code.**
The sidenav menu, the footer links and the analytics beacon live in
`src/assets/config/_base.json` and are overridden by `configs/dashboard/caios.json`.
The analytics one is the one that actually matters: left alone, the dashboard
loads a third-party tracking script and reports our demo traffic to it.

**What stays leaking, and why we are accepting it:**

| File | Leaks | Why it is fine for MVP |
|---|---|---|
| `modules/profile/store/storage-providers.store.ts:5` | Storage endpoint | Storage is deferred to V1 |
| `.../services-tab.component.ts:47-48` | MLflow signup links | MLflow is not deployed |
| `.../ai4eosc-module-detail.component.ts:206,613` | Provenance API links | Provenance is out of scope (D-09) |
| `layout/sidenav/sidenav.component.html:188,222` | Project and status page links | Two links in a collapsed menu |

Revisit before recording the walkthrough — if any of these end up on screen,
patch them then. Patching code we do not need to patch is how a deployment
becomes a fork.
