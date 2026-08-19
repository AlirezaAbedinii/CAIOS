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

### `ai4-papi/0003-tryme-vo.patch` — pinned to `e80a2b7`

`routers/v1/try_me/nomad.py` looks up `"vo.ai4eosc.eu"` in the VO map **at import
time**. On any deployment whose `main.yaml` does not list that VO it raises
`KeyError` and PAPI refuses to start at all — not just the try-me feature, the
whole API. Falls back to the first VO configured.

### `ai4-papi/0004-stats-without-wattnet.patch` — pinned to `e80a2b7`

`routers/v1/deployments/common.py` multiplies a carbon-footprint `affinity`
value that is `None` whenever the WattNet lookup was skipped — which it always
is here, because we do not run it. Every deployment then fails with
`unsupported operand type(s) for *: 'NoneType' and 'float'`: a 500 caused
entirely by an optional feature. Guarded.

### `ai4-papi/0005-skip-mail-sidecar.patch` — pinned to `e80a2b7`

The `email-notification` task is a **prestart** task, so when it cannot start
neither does the deployment — and it pulls from an external registry. With no
mail configured it is pure failure surface. Skipped when unconfigured.

### `ai4-papi/0006-browser-accept-header.patch` — pinned to `e80a2b7`

`routers/v1/catalog/common.py` compares the `Accept` header with `==`. Browsers
never send exactly `application/json`; Angular's `HttpClient` sends
`application/json, text/plain, */*`. So every request from our own dashboard was
treated as a request for HTML. Parses the header as the list with q-values that
it is.

### `ai4-papi/0007-catalogue-repo.patch` — pinned to `e80a2b7`

Covered above under the marketplace: the GitHub repository the catalogue is read
from is hardcoded, and it is the only thing deciding what a user sees. Read from
`MODULES_CATALOGUE_REPO`, defaulting to upstream.

### `ai4-papi/0008-ai4life-model-list.patch` — pinned to `e80a2b7`

`routers/v1/catalog/tools.py` offers all 68 entries of the AI4Life loader's
`filtered_models.json`, in file order, about two dozen of them near-duplicates,
with whatever happens to be first as the default. Read from `AI4LIFE_MODELS` so
the list can be curated and ordered; unset behaves as upstream.

### `ai4-papi/0009-llm-gpu-models.patch` — pinned to `e80a2b7`

Two fixes in the LLM deployment path, `routers/v1/deployments/tools.py`.

**The GPU allowlist.** Line 604 is a single hardcoded string comparison:

```python
if "Tesla T4" not in models:
    raise HTTPException(status_code=405, ...)
```

That is the only thing between a perfectly capable GPU and a 405, and it is not
configuration anywhere — so a deployment with different hardware cannot run this
tool at all. Ours reports `NVIDIA H100L-1-12C MIG 1g.12gb`, which is strictly
more capable than a T4 in everything except memory. Now read from
`LLM_GPU_MODELS` as a comma-separated list, **defaulting to `Tesla T4`** so an
unset variable behaves exactly as upstream does.

Still present at upstream `master` as of 2026-08-19, so there is no fix to pull.

**The `open-webui` typo.** Line 575 reads:

```python
if user_conf["llm"]["type"] in ["openwebui", "both"]:   # username/password checks
```

but the value that field can hold, per `etc/tools/ai4os-llm/user.yaml`, is
`open-webui` **with a hyphen**. So a standalone UI deployment skipped both
credential checks, `create-admin` then POSTed an empty email and password, and
the UI came up **with signup open** — the first visitor becomes the
administrator. Worth reporting upstream.

Neither can be configuration: both are literals inside a function body.

### `ai4-nomad_tests/0001-namespaces.patch` — pinned to `HEAD` (unversioned repo)

`ai4_nomad_tests/conf.py` and `tests/node/cpu.py:83` hardcode the namespace list
`["ai4eosc", "imagine", "tutorials"]` and a matching domain map. With our
namespace, the intersection is empty, the Traefik reachability half of the test
quietly tests nothing, and the node is still marked ready.

That matters because this test suite is not optional: it is the only thing that
sets `meta.status=ready` on each node, and every PAPI job template requires it.
Without the patch we get a cluster that passes its own tests and then fails
every real deployment.

### `ai4-dashboard/0001-pacslab-logo.patch`

The sidenav footer renders two images side by side: upstream's `eu-flag.jpg` and
the tenant logo. The EU flag is a European funding acknowledgement — correct for
AI4EOSC, and a false claim for us. CAIOS is a Canadian project running on
Compute Canada under a Canadian allocation, and the flag rendered
unconditionally, on every page.

The patch replaces it with `pacslab-logo.png`, crediting PACS Lab — the
organisation behind CAIOS — beside the CAIOS mark. It cannot be configuration:
the tenant config offers text and links, not images, and the image list in that
block is hardcoded in the template.

This is the first dashboard patch, so the note below is no longer strictly true.
It still describes the *principle* correctly, and the rest of it still holds:
everything else visible in a walkthrough is tenant configuration.
`scripts/build-dashboard.sh` applies dashboard patches itself, because it stages
`vendor/` into `build/` and would otherwise overwrite whatever
`apply-patches.sh` had put there.

### `ai4-dashboard` — otherwise deliberately **not** patched for MVP

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
