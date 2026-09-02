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

### `ai4-papi/0013-oscar-warm-and-cluster-status.patch` — pinned to `e80a2b7`

**Stage O3.** Two additions on top of `0012`, both about a serverless service
having a state the user can feel and no way to see.

**Warm or cold.** A service that scales to zero pays a start-up cost on the
first request after an idle window. The authoritative signal is a Knative
Revision's `status.actualReplicas`: present and non-zero means a container is
up. `_knative_replicas()` reads the Kubernetes API on the OSCAR node directly —
OSCAR itself does not expose this — and annotates every row of
`GET /services` and the detail response with `warm` and `replicas`.

Deliberately *not* inferred from "was it called recently" or "is the image
cached". The failure mode of a proxy signal here is a badge reading **WARM**
while the user waits three minutes, which is worse than no badge at all.

One call per page load, not one per row: `TTLCache(ttl=10)` over the whole
revision list. Ten seconds is well inside Knative's ~30 s idle window, so the
badge cannot be more than one window stale.

**`OSCAR_K8S_API` and `OSCAR_K8S_TOKEN_PATH` unset disables it**, and every
service then reports `warm: null` — which is *unknown*, not *cold*. D-39 again:
an absent signal is not a negative one. The lookup is also wrapped so that no
failure of a status badge can break the listing it decorates.

**`GET /cluster/status`.** Upstream's `/cluster` returns version strings. The
dashboard also wants to show what the cluster *is* — nodes, cores, memory —
and the Statistics page cannot answer that, because it reads Nomad and the
OSCAR node sits deliberately outside the Nomad cluster so the two schedulers
cannot destabilise each other. OSCAR already reports all of it at
`/system/status`, so this proxies that rather than inventing a second source
of truth.

D-57. Full plan: `docs/oscar-plan.md`.

### `ai4-papi/0014-catalogue-source-and-metadata.patch` — pinned to `e80a2b7`

**T1.** Three changes to the same code path, all about where the marketplace
comes from and whether it can be trusted.

**Where the catalogue is read from.** `catalog/common.py` hardcodes
`raw.githubusercontent.com` and builds the marketplace from it *at request
time*: one fetch for the catalogue's `.gitmodules`, then one per entry for its
`ai4-metadata.yml` — about fifteen for a full page. That host is Fastly-fronted
and was unreachable from **every** CAIOS node for roughly three hours on
2026-09-01, while `api.github.com`, `github.com`, Docker Hub and Hugging Face
all kept working.

`CATALOGUE_BASE_URL` points at a local mirror with the same path layout
(`<owner>/<repo>/<branch>/<file>`), built by `scripts/mirror-catalogue.sh` and
served by Caddy at `/mirror/`. Unset **or empty** behaves exactly as upstream —
`or` rather than a `get()` default, because a blank line in an env file must not
silently point the marketplace at nothing. Same treatment in
`utils.ai4life_catalog()`, which feeds the AI4Life dropdown from the same host.

**A timeout.** `session = requests.Session()` passes none anywhere, so an
unreachable source does not fail — it holds the worker thread until TCP gives
up. That is why the outage presented as a dashboard spinner that never resolved
rather than as an error. `(5, 15)` connect/read, and an unreachable catalogue
now raises **503 naming the source**, because the address is configuration now
and a misconfigured one looks identical to an outage. D-50 again: an absent
source is a state, not a hang. Measured: 90 s+ hang becomes 503 in 2 s.

**The licence.** This one is not a performance problem.

`ai4-metadata.yml` schema 2.0.0 has **no `license` key**, so a module's licence
is only ever known from its repository. Upstream reads it from `api.github.com`
in `utils.get_github_info()` — which short-circuits on `IS_DEV` and returns a
mock, `{"created": "1970-01-01", "updated": "1970-01-01", "license": "MIT"}`.
`IS_PROD` **must** be false for CAIOS (gotcha 1), so `IS_DEV` is always true.
And `common.py` assigned it unconditionally:

```python
metadata["license"] = gh_info.get("license", "")
```

So **every module in the marketplace reported MIT and 1970-01-01.**
`ai4os-yolo-torch` wraps Ultralytics YOLO and is **AGPL-3.0**; `posenet-tf` is
Apache-2.0. Stating either as MIT misrepresents a third party's terms to our own
users — the one real licensing problem this project has, and ours rather than
inherited. See `docs/licensing.md`.

The fix has two halves. `mirrored_repo_info()` reads `repo-info.json` from the
same mirror, built once from `api.github.com` at mirror time rather than per
request — correct *and* offline, and comfortably inside GitHub's 60-per-hour
unauthenticated limit. And the assignments become conditional, so a real value
is never overwritten by a mock one.

Verified live: nine modules, three distinct licences, no 1970 date, and no
GitHub host in PAPI's log for the whole run. `scripts/check-catalogue.sh`
section 4 asserts the 503 by pointing a throwaway container at an unroutable
address.

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

### `ai4-dashboard/0006-no-cache-runtime-assets.patch` — pinned to `c360f20`

Everything the Angular build emits carries a content hash, so a new build is a
new filename and a browser cannot serve a stale one. Three files are not built
and do not change name:

```
/assets/config/config.json   the API address, the issuer, the client id
/assets/config/vllm.yaml     the model catalogue the cards are drawn from
/assets/i18n/en.json         every string in the interface
```

`docker/nginx.conf` sends no cache header for any of them, so nginx answers
with `ETag` and `Last-Modified` only and a browser is then free to reuse its
copy for as long as its own heuristic allows.

**Found by deploying.** After rewriting every string on the home page, a
browser that had opened the previous build kept rendering the previous build's
words against the new bundle, and the page showed raw translation keys for the
strings that were new. Nothing was wrong with the deployment.

The same hole covers the runtime configuration, which is worse: change
`API_SERVER` and a returning visitor talks to the old address.

**Upstream tried to prevent exactly this and missed.** `nginx.conf` already
carries a no-cache block for `config.json` — as `location = /config.json`,
which matches nothing, because the application fetches
`/assets/config/config.json`. The patch leaves that block alone, notes that it
is dead, and adds a regular-expression location covering both directories. A
regex location takes precedence over the prefix match above it, so it wins for
these two directories and nothing else.

Fonts and images are deliberately **not** covered. They are large, they change
rarely, and caching them is worth having.

### `ai4-dashboard/0005-platform-status-source.patch` — pinned to `c360f20`

**R-38.** Makes the platform-status feed configuration instead of a hardcoded
reference to another project, and off when unset.

`shared/services/platform-status/platform-status.service.ts` hardcodes
AI4EOSC's own GitHub issue tracker in three methods:

```ts
'https://api.github.com/repos/AI4EOSC/status/issues?state=open&…'
```

Those three feed the startup popup, the notifications bell, and the red
maintenance banner on the deployments list. Every one of them is fetched **from
the visitor's browser**, twice on a normal page load and three times on the
deployments page.

**Two failure modes, and the boring one is likelier.**

*The rate limit.* GitHub allows **60 unauthenticated requests an hour per IP
address** — measured, not assumed. At two per full page load that is about
thirty loads an hour from one address, and a demo audience in one building
shares one. Past that, GitHub answers 403 and the component pops a red
*"Error retrieving the platform notifications"*. Upstream evidently meets this:
`core/interceptors/http-error.interceptor.ts` carries a special case so a 403
**from that exact URL** does not throw the user onto the Forbidden page. That
is the symptom handled, not the cause.

*Somebody else's words on our screen.* All three paths filter by VO, and the
filter passes a notice whose `vo` is `null` — which is what a platform-wide
notice looks like. So an AI4EOSC maintenance window, announced correctly by
them, renders as our popup and as a red banner over our deployments table. No
mistake is required by anyone.

**What the patch does.** The URL comes from `platformStatusUrl` in the tenant
config, read through `AppConfigService` like every other setting, and **an
empty or absent value means no request is made at all** — each method returns
an empty list. The bell then renders its existing "No notifications" state and
the deployments list renders no banner: a feature we do not run looks
unconfigured, not broken (D-50). `configs/dashboard/caios.json` sets it blank
deliberately, and `scripts/check-branding.sh` asserts both that the served
config carries the key blank and that the bundle no longer names the
repository.

The interceptor guard is kept but generalised to match `/status/issues` rather
than one project's URL — a status feed answering 403 still must not throw the
user to the Forbidden page, whatever feed it is.

**This changes the default for an unconfigured tenant**, from "read AI4EOSC" to
"off". That is the point: a flavour that forgets to set the key should end up
quiet rather than showing another project's notices.

Upstream's three service tests still exercise the fetch path — the patch adds
`platformStatusUrl` to `app-config.mock.ts` so they do — and one test is added
for the CAIOS behaviour, which `httpMock.verify()` makes meaningful: a method
that quietly made a request after all fails on the unmatched call.

### `ai4-dashboard/0004-home-route.patch` — pinned to `c360f20`

**Stage F3.** Nine lines in `src/app/app.routes.ts`, and the only upstream file
the home page touches.

Upstream sends `/` straight to `/catalog/modules`, so the first thing anyone
sees is a grid of model cards with no statement of what the platform is, who it
is for, or where it runs. This replaces that redirect with a lazy-loaded route
onto the CAIOS home page.

The page itself is **not** in this patch. It is CAIOS-owned Angular source in
`configs/dashboard/home/`, staged into `src/app/modules/home/` by
`scripts/build-dashboard.sh`, and its English strings are deep-merged into
`src/assets/i18n/en.json` from `configs/dashboard/i18n/en.caios.json`. Neither
is an upstream edit, so neither can drift (D-46).

Why that split rather than one patch creating the whole module: a 1,500-line
patch is not reviewable, and `en.json` is a 900-line upstream file that changes
whenever any page gains a label — a patch against it would break for reasons
that have nothing to do with the home page.

`loadChildren`, not `component`: the bundle is downloaded only by someone who
opens `/`, so a user who signs in and goes to their deployments pays nothing
for it.

**Removing this patch restores upstream exactly** — the old `redirectTo` line
comes back and the staged module is simply never routed to.
`tests/test_home_page.py` asserts that the patch touches one file and that the
old redirect is the line being replaced.

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
