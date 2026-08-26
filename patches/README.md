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

### `ai4-papi/0010-llm-webui-endpoint.patch` — pinned to `e80a2b7`

`routers/v1/deployments/tools.py` again, and the reason Stage L4 exists.

For a `both` deployment, vLLM and Open WebUI are two tasks in **the same Nomad
allocation** — same node, same network namespace, ports a hop apart. Upstream
nevertheless hands the UI the public HTTPS endpoint of the vLLM beside it:

```python
api_endpoint = f"https://vllm-{job_uuid}" + ".${meta.domain}" + f"-{base_domain}/v1"
```

So the chat interface leaves the node, resolves a public hostname, crosses
Traefik, and comes back to a port it could have reached directly. On any
deployment whose TLS is signed by its own CA — ours, D-12 — aiohttp raises
`CERTIFICATE_VERIFY_FAILED`.

**What makes this worth a patch rather than a shrug is the failure mode.** Open
WebUI catches the exception and carries on, so:

```
ERROR open_webui.routers.openai:send_get_request - Connection error: ...
      [SSL: CERTIFICATE_VERIFY_FAILED] self-signed certificate in certificate chain
INFO  "GET /api/models HTTP/1.1" 200
```

`GET /api/models` returns **200 with an empty list**. Nomad reports the
allocation healthy, the login page works, the admin account is correct, and the
model dropdown is empty. Nothing outside the container's stderr says why.

The fix is D-36 applied to the application instead of to the helper tasks:
`http://${NOMAD_ADDR_vllm}/v1`, interpolated by the Nomad client at launch.
Confirmed by hand before it was written — from inside the `open-webui`
container, that address answered `401` (the key was missing), which is a
connection that worked.

Only `both` is redirected. A standalone `open-webui` keeps whatever endpoint the
user supplied, which is the one case where leaving the cluster is the point.
Unset in every other path, so the patch changes nothing for anyone else.

### `ai4-papi/0011-deployment-readiness.patch` — pinned to `e80a2b7`

`ai4papi/nomad_utils.py`, and the reason Stage L4b exists. Two changes, both
pure functions over data `get_deployment` has already fetched — no extra Nomad
calls, no new dependency, and **no dashboard change needed**, because `starting`
and `queued` are already badges upstream and *Quick access* is already gated on
`status === 'running'`.

**1. `running` becomes `starting` until a user can actually open it.**

```python
status = a["TaskStates"]["main"]["State"] if a.get("TaskStates") else "queued"
```

`main` is whichever task PAPI renamed at submission (`tools.py:678`). For the
LLM tool that is **vLLM, a prestart sidecar** — so it reads `running` while the
model is still loading and while Nomad has not started Open WebUI at all.
Measured on 2026-08-21: green badge at T+1 s, chat interface answering at
T+185 s, and Traefik serving `Bad Gateway` for the 184 seconds in between,
because the Consul service carries no check but the node's own liveness.

The patch adds `unstarted_user_tasks()`: tasks with a `lifecycle` block are
plumbing, tasks without one are what a user opens, and Nomad has not started one
until it has a `StartedAt`.

**That alone was not enough, and the smoke test caught it.** Moving the signal
from the wrong container to the right container still leaves it a signal about a
*container*: measured on 2026-08-22, Nomad started `open-webui` at T+182 s and
the first HTTP response came at T+220 s. Uvicorn opens its socket only after the
FastAPI lifespan has created the administrator and closed signup (D-37), so 38
seconds of green badge survived the first fix.

So `deployment_is_ready()` adds a second condition: where the group defines
health checks, Nomad must also have marked the allocation healthy. Nomad's
`update.health_check` already defaults to `checks`, so with checks present that
means "the port answers". The checks were added to
`configs/papi/tools/ai4os-llm/nomad.hcl` in the same change, and the two are
useless apart — the check without the gate leaves the badge wrong, the gate
without the check has nothing to read.

One layer remained after that, and it is not in Nomad: Traefik's consul-catalog
provider polls Consul at 15 s intervals, so the public URL goes live up to that
long after the check passes. `min_healthy_time = "25s"` in the job template
covers it. No patch can — the check runs on the node, against the allocation,
and the late component is the reverse proxy in front of it.

Groups with no checks fall back to the task condition alone, so nothing that
cannot express readiness can wedge at `starting`. That matters more than it
looks: the instrumented run showed `DeploymentStatus` **absent** for the whole
window, never `False`, so a naive `Healthy is False` test would have passed
every unit test and done nothing on the cluster. R-23, D-38.

**For every single-task deployment this is a no-op** — modules, the dev
environment and the federated server have one task named `main` with no
lifecycle block, so it is a user task and it has already started. That is
asserted by `tests/test_deployment_status.py` against a recorded workspace
allocation, because "safe for everything else" is the claim that matters.

**2. A blocked evaluation becomes `queued`, with a message.**

```python
info["status"] = "error"
info["error_msg"] = f"{evals[0].get('FailedTGAllocs', '')}"
```

Nomad distinguishes "I cannot place this" from "I will place this when there is
room". Upstream flattens both into `error`. Worse, `/v1/job/:id/evaluations`
returns evaluations **unordered**, and the one that comes back first is
frequently the *blocked* evaluation — which carries no `FailedTGAllocs`. So the
message is the empty string.

That is not hypothetical: on 2026-08-21 a second LLM deployment was submitted
while the first held the only free GPU, shown as a red error with no text, and
deleted by the user three seconds after Nomad finally placed it. It had been
47 seconds from working.

`placement_status()` splits the one case into three. No `FailedTGAllocs` on any
evaluation means Nomad has not run a scheduling pass yet — `queued`, and the
instrumented run showed this is a real state every deployment passes through, so
upstream flashed red for the first second of its life. A non-empty `BlockedEval`
means Nomad will retry when capacity changes — also `queued`. Only the remainder
is an `error`. In every case the message is built from whichever evaluation
actually has `FailedTGAllocs`, turning `DimensionExhausted` and
`ConstraintFiltered` into a sentence rather than a Python dict. R-24, D-39.

Worth reporting upstream. Neither fault is CAIOS-specific: the first affects any
tool using lifecycle hooks, and the second affects any deployment on any cluster
that is ever briefly full.


Still present at upstream `master` as of 2026-08-20. Worth reporting: it affects
any AI4OS deployment not using a publicly trusted certificate.

### `ai4-papi/0012-oscar-optional.patch` — pinned to `e80a2b7`

**Stage O0.** Makes serverless inference (OSCAR) an optional feature instead of
an assumed one.

`ai4papi/routers/v1/inference/oscar.py` reads its cluster configuration by
direct index, in four places:

```python
papiconf.MAIN_CONF["oscar"]["clusters"][vo]["cluster_id"]
```

That is correct for AI4EOSC, which runs an OSCAR cluster for every VO it
serves. We run none — `oscar:` is absent from `configs/papi/main.yaml`
entirely (D-09) — so every one of those lookups raises `KeyError`, and FastAPI
turns it into a bare **HTTP 500**.

**This is reachable today.** The inference router is mounted unconditionally in
`routers/v1/__init__.py`, and the dashboard hardcodes a sidenav entry — not a
tenant-configurable one — at `/tasks/inference`:

```js
{name:"SIDENAV.INFERENCE",url:"/tasks/inference",isRestricted:true,...}
```

Confirmed present in the bundle the cluster serves. Measured against the live
API on 2026-08-25, before this patch:

```
/v1/inference/oscar/cluster    HTTP 500
/v1/inference/oscar/services   HTTP 500
```

So a logged-in researcher can reach a page from the menu whose only backend
call is a server error, for a feature we deliberately do not offer.

**What the patch does.** Two helpers, `oscar_cluster_conf()` and
`require_oscar()`, and every direct index routed through the latter:

| Endpoint | Before | After |
|---|---|---|
| `GET /services` | 500 | `[]` — the page renders its empty state |
| `GET /cluster`, `GET /services/{name}` | 500 | 501 with a sentence |
| `POST` / `PUT` / `DELETE /services` | 500 | 501 with a sentence |

`GET /conf` never touched the cluster config and is unchanged.

The listing degrades to an empty list rather than a status code because that is
the call the Inference page makes when it opens; a 501 there would still paint
an error bar over a feature that is simply absent. The write paths get 501,
because silently accepting a create would be worse. D-39 — *"waiting" and
"failed" are different words* — applied to a third case.

**Why all four call sites and not just the client path.** `create_service`
calls `make_service_definition(user_conf, vo)` **before** it builds a client,
and that function reads the cluster id directly. Guarding only
`get_client_from_auth` left `POST /services` raising `KeyError` exactly as
before — with every unit test green. `tests/test_oscar_optional.py` found it,
and now covers it.

**Unset behaves as upstream.** Once `oscar.clusters.<vo>` exists in
`main.yaml` (Stage O3), `require_oscar` returns it and every endpoint behaves
exactly as upstream does. The patch adds a guard; it changes no behaviour on a
configured cluster.

Full plan: `docs/oscar-plan.md`.

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

### `ai4-dashboard/0002-vllm-catalogue-url.patch`

`tools.service.ts` fetches the LLM model catalogue from **AI4OS's GitHub**:

```ts
const url =
    'https://raw.githubusercontent.com/ai4os/ai4-papi/refs/heads/master/etc/vllm.yaml';
```

That is the file *their* PAPI serves. Ours serves a curated subset — the models
that fit in 10.3 GB of usable VRAM, with the gated Llama entries dropped — so
the page had two disagreeing sources: the model **cards** and the
`needs_HF_token` logic came from upstream's thirteen, while the deploy form's
**dropdown** came from our PAPI's nine. Cards for models we do not offer, no
card for the ones we do, and a Hugging Face field that appears for the wrong
models.

It is also a third-party fetch made by the user's browser, from a page that is
supposed to be self-contained on a private subnet — the same objection as the
analytics beacon removed in Stage 0, and it fails outright if GitHub is
unreachable.

Now `/assets/config/vllm.yaml`, staged by `scripts/build-dashboard.sh` from
`configs/papi/vllm.yaml`, so PAPI and this page read one file. Leading slash and
`HttpClient` match `app-config.service.ts`, which already loads
`/assets/config/config.json` that way.

It cannot be configuration: the URL is a string literal in a service method.

The patch also updates `tools.service.spec.ts`, which asserts the URL the
catalogue is fetched from. Left alone it would assert the behaviour we just
removed; updated, it is the thing that stops the third-party fetch coming back.

### `ai4-dashboard/0003-vllm-model-id.patch`

The dashboard never kept the model id. `getVllmModelConfiguration()` reads
`vllm.yaml`, whose keys **are** the ids, and then throws the key away:

```ts
Object.entries(parsedYaml.models).map(([name, config]) => ({
    name,        // the key...
    ...config,   // ...immediately overwritten by the entry's own `name`
}));
```

So three places rebuilt it as `family + '/' + name`, which is right only when
the Hugging Face organisation equals the family label. It does not for
`mistralai/Ministral-3-3B-Instruct-2512` (family `Mistral`) or
`ibm-granite/granite-4.1-3b` (family `IBM`) — **two of our nine, and four of
upstream's own thirteen**, so this is inherited rather than caused by curating.

| where | what went wrong |
|---|---|
| `llm-card.loadLLM()` | preselects the deploy dropdown with a value not in it, so it opens blank |
| `llm-card.openLink()` | the "Card" chip opens `huggingface.co/Mistral/...` — a 404 |
| `general-conf-form.modelChanged()` | `find()` misses, `?? false` decides no Hugging Face token is needed |

The third is the dangerous one. Every model in the CAIOS catalogue is ungated,
so the answer is right — by accident. A gated model would show no token field
and fail at PAPI with a 400 the form had all the information to prevent.

The fix is to keep the key as `id` and use it in all three places.

It also repairs the fixtures, which is how the bug survived: the mock YAML keyed
on the **display name** and carried no `name` field, so upstream's
`{ name, ...config }` filled `name` in from the key and every test passed
against a shape the real file never has. The fixtures now key on the model id
and include a family that differs from its organisation.

Worth reporting upstream, with the two mismatching entries as the reproduction.

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
