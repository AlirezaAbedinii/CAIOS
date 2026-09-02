# Finalization plan

What is left between here and a recorded demo, against the supervisor's
checklist of eleven items. Written 2026-09-01, corrected and extended by a
browser pass on 2026-09-02.

`docs/mvp-plan.md`, `docs/llm-plan.md`, `docs/oscar-plan.md` and
`docs/frontend-plan.md` are the plans for what was built. This is the plan for
finishing.

---

## The supervisor's checklist

| # | Requirement | State | Task |
|---|---|---|---|
| 1 | Portal with services underneath: OSCAR and serverless | Built and working | — |
| 2 | Two use cases, one low code and one high code | Both work; both sit behind the catalogue | T1 |
| 3 | "Not included in the Demo Version" for other services | **Unbuilt.** The phrase is nowhere in the repository | T4 |
| 4 | Registration service: form and admin console | **Unbuilt.** Deferred by decision — demo accounts instead | T6 (optional) |
| 5 | HTTP instead of HTTPS | **Platform ready; switch held on the proxy VM** | T5 |
| 6 | No licensing problem re: Europe and AI4OS | Upstream is clean. **Two problems are ours** | T3 |
| 7 | Identify potential improvements | Written up; no implementation | — |
| 8 | Demo video performable by test users | Script exists and has drifted | T8 |
| 9 | Acceptable availability | Two concrete gaps | T7 |
| 10 | Agentic workflow / compute graph | Out of scope | — |
| 11 | `pacslab.ca` / `caios-demo` subdomain | Out of scope, but designed for | T5 |

---

## What the investigation found

### 1. The catalogue depends on a host that intermittently disappears

`raw.githubusercontent.com` — `185.199.108–111.x`, GitHub's Fastly-fronted CDN
— was unreachable from **every** node for about three hours on 2026-09-01.
Measured from `caios_server`, `caios_edge`, `caios_site_a` and `caios_oscar`;
`api.github.com` (`140.82.x`), `github.com`, Docker Hub and Hugging Face all
kept working throughout, and there is no local firewall rule. It recovered on
its own and a 60-sample probe on 2026-09-02 came back 60/60.

PAPI's log dates the window precisely — every `Network is unreachable` falls in
`19:47–19:59` and `22:36–22:54` UTC, with successful catalogue loads before,
between and after. It flaps rather than switching cleanly off.

**Why it matters more than an outage normally would.** The dependency is on the
demo's critical path and it is consulted at request time:

- `Catalog.get_items()` fetches `.gitmodules` from that host.
- `_get_metadata()` then fetches **each module's** `ai4-metadata.yml` from it —
  about ten requests per cold catalogue load.
- `utils.ai4life_catalog()` uses it for the AI4Life model list.
- The **dashboard** uses it directly from the visitor's browser, twice: the
  AI4Life summary (`endpoints.ai4lifeModulesSummary`) and every image inside a
  module's description.

And `session = requests.Session()` carries **no timeout anywhere**, so a failure
hangs the request instead of ending it. Measured: `/v1/catalog/modules` and
`/v1/catalog/tools` returned nothing after 90 seconds. The user-visible result
is a page that spins forever.

Everything that broke during the window broke because of this one fact: Modules
dead, Tools dead, and with them the only route to a JupyterLab workspace (the
high-code use case) and the only route to "Deploy → Inference API (serverless)"
(the low-code one), because that menu item lives on a module detail page.

> **Corrected 2026-09-02.** The first version of this document called it a
> permanent block. It is not. That framing came from measuring only inside the
> outage window. The fix is unchanged and better justified: an intermittent
> dependency that hangs is harder to plan around than one that is simply down.

### 2. Profile → API Keys ejects the user from the application

The worst user-visible fault on the platform, and one click from the profile
menu. `/v1/llm/api_keys` proxies to **AI4EOSC's LiteLLM** at
`vllm.cloud.ai4eosc.eu`, hardcoded in `routers/v1/llm/keys.py`. It answers 401,
the dashboard's error interceptor treats that as forbidden, and the browser
lands on:

```
/forbidden;errorMessage=Error: {"error":{"message":"Authentication Error,
LiteLLM Virtual Key expected. Received=****, expected to start with 'sk-'.",
"type":"auth_error","param":"None","code":"401"}}
```

Another platform's internal error, in our URL bar, on a page that says
Forbidden. Verified in a browser 2026-09-02.

### 3. Every module displays the wrong licence

`IS_PROD` must be `false` — gotcha 1, and not optional: the official image sets
`IS_PROD=True` and PAPI then refuses to start over missing Harbor, Jenkins,
provenance and LiteLLM tokens. But `conf.py` derives `IS_DEV = not IS_PROD`, and
`utils.get_github_info()` short-circuits on `IS_DEV` and returns mock data:

```python
return {"created": "1970-01-01", "updated": "1970-01-01", "license": "MIT"}
```

`catalog/common.py` then writes that straight over the module's real metadata:

```python
metadata["dates"]["created"] = gh_info.get("created", "")
metadata["dates"]["updated"] = gh_info.get("updated", "")
metadata["license"]          = gh_info.get("license", "")
```

So **all nine modules report `MIT` and `1970-01-01`**, verified against
`/v1/catalog/modules/detail`. `ai4os-yolo-torch` wraps Ultralytics YOLO, which
is **AGPL-3.0**. Stating someone else's AGPL work as MIT on our own marketplace
is the one real licensing problem this project has, and it is ours rather than
anything inherited from AI4OS.

The dates are the same bug wearing a different hat: every module page shows
"1970-01-01" as its creation and update date.

### 4. Third-party leaks the earlier sweeps missed

Six were known and closed. The browser pass found three more, all on module
detail pages:

| Leak | What a visitor sees |
|---|---|
| `jenkins.cloud.ai4eosc.eu/buildStatus/icon` | A **`build aborted`** badge on module pages — AI4EOSC's Jenkins, reporting on a job that is not ours |
| `raw.githubusercontent.com/...` | Every image inside a module's description, fetched by the visitor's browser |
| `api.github.com/repos/...` | Reached for dates and licence — currently short-circuited by `IS_DEV`, so it fires only if that is ever fixed naively |

### 5. AI4OS and AI4EOSC strings a visitor actually reads

Nine i18n strings plus four things the earlier grep could not see, because they
come from module metadata or upstream vocabulary rather than from `en.json`:

- `DASHBOARD.USAGE` — "**AI4EOSC** Usage Over Time", the Statistics usage tab
- `CATALOG.MODULE` / `.TOOL` / `.AI4LIFE` — "AI4 Module", "AI4 Tool",
  "AI4Life Module", the type label on every catalogue card
- `CATALOG.MODULE-DETAIL.DEPLOY.EU-NODE` — a deploy option, see below
- `PROFILE.STORAGE-TAB.AI4EOSC-NEXTCLOUD` — "AI4EOSC Nextcloud", rendered
- three `docs.ai4os.eu` links, plus the `footerLinks` documentation link
- **"AI4OS Development Environment"** — the dev-env's own title, in the Tools list
- **"AI4 pre trained" / "AI4 trainable" / "AI4 inference"** — platform category
  chips on every module page
- **`vo.imagine-ai.eu`** — another project's VO, rendered as a tag on our modules
- The Modules page's own tab strip reads **"AI4EOSC"** and "AI4Life"

Not visible, verified: `SIDENAV.AI4OS` and the "powered by" block are gated to
the `imagine`/`ai4life` VOs; `status.ai4eosc.eu` is gated on `deployedInNomad`
(false); the AI4EOSC chatbot component is referenced by no template;
`login.cloud.ai4eosc.eu` and `api.cloud.ai4eosc.eu` are compiled-in fallbacks
overridden at runtime.

Keeping deliberately: the sidenav acknowledgement and `HOME.CLOSING.STACK`.
Apache-2.0 asks for attribution and these are it.

### 6. The Deploy menu offers four targets and two of them do not exist

Read from the live dropdown on a module page:

| Option | Subtitle | State |
|---|---|---|
| Inference API (serverless) | on the project's OSCAR cluster | **Works** — this is the low-code use case |
| Inference API + UI (dedicated) | on the project's Nomad cluster | **Works** |
| Inference API (cloud) | Deploy on your own cloud resources via IM | Infrastructure Manager is not deployed |
| Inference API (EU Node) | Deploy in the EOSC EU Node cloud resources | European infrastructure, on a platform whose argument is that data stays in Canada |

The last two are not missing features to be annotated. They are wrong offers,
and they should be removed.

### 7. Upstream licensing is clean

`ai4-papi`, `ai4-dashboard`, `ai4-ansible` and `ai4-nomad_tests` are all
**Apache License 2.0**; `ai4-papi` ships a `NOTICE`. Apache-2.0 grants
worldwide, royalty-free rights to use, modify, redistribute, sublicense and
commercialise, with **no territorial and no field-of-use restriction**. That the
project is European creates no obligation of any kind. There is also an express
patent grant, which runs in our favour.

Three obligations follow, and we satisfy none of them yet because this
repository carries no licence file at all:

1. Retain copyright, licence and attribution notices in redistributed source.
   Our patches modify Apache-2.0 files and the containers redistribute them.
2. State that files were changed. `patches/README.md` already does this well —
   it needs to be *named* as the change statement.
3. Propagate `NOTICE` content.

Worth writing down but not licence problems: the modules-catalog fork carries no
licence file (it holds submodule pointers only), and models pulled from
bioimage.io and Hugging Face carry their own per-model terms.

### 8. Availability

Healthy: five Nomad clients ready, all containers `unless-stopped` and up 6 days
to 2 weeks, Docker, Nomad and Consul all `enabled` at boot, RAM barely touched
anywhere. Four practical gaps:

1. **Vault does not survive a reboot.** It runs in dev mode
   (`storage_type: inmem`). Compose re-runs `vault_init` on every `up` —
   deliberately — but that container is `restart: on-failure` and **exited 0**,
   so Docker will not restart it after a host reboot. Vault comes back empty and
   healthy-looking, and deploying the FL server then fails with a bare 500.
2. **No HTTP timeout anywhere in PAPI**, which is why finding 1 presents as a
   spinner rather than an error.
3. **Disk.** `caios_server` root is at 77 % (4.5 GB free); `caios_llm`'s
   `/mnt/data` at 78 % against docuum's 80 GB threshold.
4. **No cold-start run has ever been done.** Outstanding since Stage L6.

### 9. Five stale deployments

Four from 2026-08-15 — three `tool-devenv-*` workspaces and the
`CAIOS federated server` — plus a `tool-llm-*` titled "test meeting" from
2026-08-26. The four older ones registered under the **old private hostname**
`pacs-deployments.192.168.104.105.sslip.io`; PAPI still prints those URLs and
the public variant 404s, so a test user clicking them gets nothing.

Approved for deletion: the four federated-learning ones. The LLM is still to be
confirmed.

---

## Corrections to earlier findings

Both came from measuring the API without a browser, and the browser pass
overturned them:

- **User statistics are not zeros.** `Your Usage` renders live figures — 5 jobs,
  6 CPUs, 33 GiB, 1 GPU. Only the historical timeseries is empty, because
  accounting was never deployed. The panel does not need annotating.
- **The catalogue outage is intermittent, not permanent.** See finding 1.

---

## Tasks

Dependency ordered. Dashboard changes are grouped, because each one costs a
build, a deploy and a browser re-verification.

### T1 — Self-hosted catalogue mirror

**Objective.** The marketplace works with no third-party fetch at request time,
from PAPI and from the visitor's browser.

**Build on.** Patch `0007` already made the catalogue *repository* configuration;
patches `0002` and `0003` established self-hosting for `vllm.yaml`; Caddy already
serves static trees at `/fl/*` and `/caios-ca.pem`; `catalog/keep.txt` and
`catalog/ai4life-models.txt` already define the curated set.

**Changes.**

- `scripts/mirror-catalogue.sh` — clone the catalogue fork and each kept
  module/tool repo over `github.com`, writing `catalog/mirror/.gitmodules`,
  `catalog/mirror/<module>/ai4-metadata.yml` and
  `catalog/mirror/ai4life/filtered_models.json`. Idempotent; records the source
  commit per file. Verified feasible — `git clone --depth 1 --filter=blob:none`
  of `ai4os-hub/ai4os-yolo-torch` works.
- Caddy: a `handle_path /catalog/*` file server. **Empty in place on refresh** —
  D-44's bind-mount inode trap applies exactly.
- PAPI patch `0014` — make the base URL configuration (`CATALOGUE_BASE_URL`,
  upstream as the default) in `catalog/common.py` for `get_items()` and
  `_get_metadata()`, and in `utils.ai4life_catalog()`. Add connect and read
  timeouts, and turn an unreachable source into a 503 with a sentence.
- Dashboard patch — `endpoints.ai4lifeModulesSummary` to a staged local file.

**Tests.** Unit: the mirror holds exactly `keep.txt`; every `ai4-metadata.yml`
parses and carries a *namespaced* `docker_image` (the
`image-classification-tf-dicom` trap that returns HTTP 500); the AI4Life file
holds all twelve curated ids; the base URL is read from the environment with the
upstream default intact. Smoke: `scripts/check-catalogue.sh` — both endpoints
under 2 s, every module has a deployable `/config`, and a **negative case** with
`CATALOGUE_BASE_URL` pointed at a blackhole returning 503 within 10 s rather
than hanging.

**Browser.** Modules and Tools render; a module detail page opens; the network
panel shows no request to any `githubusercontent` host.

**Difficulty.** Medium-high. The per-module metadata mirror is the fiddly part.

### T2 — Clear the stale deployments

Delete the four federated-learning deployments (approved). Confirm the LLM
separately. Smoke: every endpoint printed by `/v1/deployments/tools` answers 200
at the current base domain. Difficulty: trivial.

### T3 — Licensing, and the AI4OS reference sweep

**Objective.** The platform states licences correctly, and the only AI4OS
mentions a visitor reads are the two deliberate attributions.

**Changes.**

- **The licence bug is the priority.** Stop `IS_DEV` overwriting real metadata:
  a module's own `ai4-metadata.yml` carries its licence, and the mock value
  should never win. Flipping `IS_PROD` is not available (gotcha 1), so this is a
  PAPI patch — and it lands naturally beside T1, which is already touching
  `_get_metadata`. The dates fix comes with it.
- `LICENSE` (Apache-2.0), `NOTICE`, and `docs/licensing.md` recording the above.
- Override the user-facing i18n strings in `configs/dashboard/i18n/en.caios.json`.
- Remove the EU Node and IM deploy options; remove the Jenkins badge; drop the
  unreferenced `eu-flag.jpg`.
- Decide the `docs.ai4os.eu` footer link.

**Tests.** Unit: no module reports `MIT` unless its metadata says so; no module
reports 1970. Smoke: extend `check-branding.sh` to fetch the served `en.json`,
match every string against `/ai4|eosc/i` and assert the result **equals an
explicit allowlist**, so a future upstream bump surfaces new strings rather than
shipping them.

**Difficulty.** Low-medium.

### T4 — "Not included in the Demo Version"

**Objective.** Every exposed surface either works or says one consistent
sentence. Nothing spins, nothing 500s, nothing ejects the user.

**Build on.** D-50 already sets the rule — an absent optional feature is a state,
not a failure — and PAPI applies it three times, in patches `0004`, `0011` and
`0012`. This extends it to the interface.

**Mechanism.** One shared notice plus a `demoUnavailable` list in the tenant
config, so the surfaces are data rather than a scatter of edits.

| Surface | Today | Action |
|---|---|---|
| Profile → API Keys | **Ejects to Forbidden** with AI4EOSC's error | Notice. Highest priority |
| Profile → Storage | Offers "AI4EOSC Nextcloud"; none deployed | Notice |
| Profile → Services | MLflow and Hugging Face, both Unlinked | Notice |
| Batch training | Lists honestly; nothing can create one | Notice, keep the nav item |
| Snapshots | Lists `[]`; creating needs Harbor | Notice on the action |
| Zenodo dataset picker | 404s; needs public internet | Hide |
| CVAT tool card | Needs ~71 GB on one node (gotcha 9) | Notice on the card |
| NVFLARE tool card | Needs TCP 8002-8003 (gotcha 8) | Verify, then notice or keep |
| Try me | Works | **Keep** |

**Tests.** Unit: every id in `demoUnavailable` matches a known surface, and every
surface in this table appears in it. Smoke: the dashboard never calls
`/v1/llm/api_keys`. Browser: click every sidenav item and every profile tab —
zero error toasts, zero unresolved spinners, zero ejections.

**Difficulty.** Medium.

### T5 — HTTP instead of HTTPS

**Status 2026-09-02: the platform is ready and the switch is HELD.** Every
scheme now derives from `CAIOS_SCHEME` in `configs/env/caios.env`, still set to
`https`, so the platform is unchanged and working. It is not flipped because of
something the assessment below did not know about — see
[the proxy VM](#the-blocker-the-assessment-missed).

Landed: the rendered Caddyfile serving both schemes, Keycloak's issuer and
realm settings, PAPI patch `0016` (advertised endpoints, the vLLM base URL, and
sixteen Traefik router tags across six job templates), dashboard patch `0010`
(`requireHttps`), the Traefik job without its `web → websecure` redirect, Vault,
the FL bundles, twelve scripts and `tests/test_scheme_switch.py`.

Verified end to end at both settings: a real dev-env deployment submitted
`tls=true` under `https`, and the same template renders `entrypoints=web` under
`http` with the federated-learning router keeping TLS (D-67).

Found on the way, and **fixed**: patch `0015` had made deployment creation
impossible for any user with a failed deployment in their history — HTTP 500 on
every POST. Patch `0017`. See [T4's aftermath](#t4s-aftermath).

#### The blocker the assessment missed

`134.87.8.230` is **a separate VM running nginx 1.18.0**, and it is the public
front door for both tiers. `docs/public-access.md` said there was no such
machine; that is corrected there and in D-69.

It redirects `:80` to `:443` unconditionally. Against a platform serving HTTP —
where Caddy answers `:443` with a 302 back to HTTP — that is a **redirect
loop**, not a degradation, on the hostname the demo opens on. And its
certificate is the CAIOS CA's, so a visitor would still have to install
`caios-ca.pem`, which is the entire point of the requirement.

`docs/nginx-proxy.md` holds the exact nginx change and the flip procedure that
follows it. **Do not set `CAIOS_SCHEME=http` before it is applied.**

The reason this went unnoticed for a week is worth more than the fact:
`/etc/hosts` on `caios_server` maps the four control-plane hostnames straight to
`192.168.104.181`, so every curl run from that node bypasses the proxy. Use
`--resolve` and read the `Server:` header.

#### T4's aftermath

Making a crashed deployment visible (`0015`) put it in front of
`quotas.check_userwise`, which indexed `d["resources"]["gpu_num"]`. A failed
deployment has no allocation and therefore no resources, so three abandoned
`posenet-tf` jobs were enough to make the platform unable to create anything at
all. Patch `0017`, plus two tests that fail without it.

Found by deploying a workspace during the T5 smoke test, for an unrelated
reason. That is the argument for smoke-testing by using the platform rather
than by reading it.

#### The original assessment, for reference

**Assessment: feasible, one real blocker, roughly a day.**

| Layer | Dependency |
|---|---|
| Caddy | Four `https://` blocks, `auto_https off`, a `tls` directive each |
| Traefik | `web` → `websecure` redirect; default cert store |
| Job templates | `traefik.http.routers.*.tls=true` in upstream `modules/nomad.hcl`, `tools/*/nomad.hcl`, and our three |
| PAPI | `nomad_utils.py:148` hardcodes `f"https://{url}"` for every endpoint shown; `tools.py:601` for the vLLM base URL |
| Keycloak | `KC_HOSTNAME`; Caddy's `X-Forwarded-Proto https`; realm `sslRequired: "external"`; client `redirectUris` and `webOrigins` |
| Dashboard | **Blocker:** `angular-oauth2-oidc` defaults `requireHttps: "remoteOnly"` and throws on an `http://` non-localhost issuer |
| Config | `apiURL`, `issuer`, `self.domain`, `CORS_origins`, `API_SERVER`, `ISSUER`, `DASHBOARD_URL` |
| FL bundles | `SSL_CERT_FILE` (D-43), `curl -k` in `bootstrap.sh` |
| Scripts | `get-token.sh`, `verify-cluster.sh`, `oscar-submit.sh`, every `check-*.sh` |

**Login will still work.** Two things needed checking and only one bites. The
Keycloak client requires PKCE `S256`, and `crypto.subtle` is unavailable in
insecure contexts — but the deployed bundle carries `angular-oauth2-oidc`'s
`DefaultHashHandler`, a pure-JavaScript SHA-256, and calls `subtle.digest`
nowhere. `crypto.getRandomValues`, which it does use, works in insecure
contexts. `requireHttps` is the one that bites, and it is one line in a patch.

**Also checked.** No `Strict-Transport-Security` header is emitted anywhere and
`sslip.io` is not preloaded, so browsers will not force HTTPS back on us.
Cookies lose `Secure` once `sslRequired` is `none`; test in a clean profile.
Websockets move `wss:` to `ws:` — JupyterLab and Open WebUI streaming must be
exercised. OSCAR's own Kubernetes ingress is reached server-side by PAPI and can
stay HTTPS.

**Approach.** Introduce `CAIOS_SCHEME` in `caios.env` and thread it through the
rendered configs, so HTTPS stays one variable away and the eventual move to a
real certificate on the PACS Lab domain is a config change rather than a second
migration. Keep every certificate and cert script in the tree.

**Order within the task.** Keycloak realm, then Caddy, then dashboard config and
the `requireHttps` patch, then PAPI, then Traefik, then rebuild both images,
then rebuild the FL bundles, then re-run every check. One atomic commit.

**Main risks.** A partial switch produces mixed content or a CORS wall, and both
look like "the dashboard is broken". The issuer string must be byte-identical in
four places; PAPI compares it character by character and a mismatch is a silent
401 on everything.

**Difficulty.** Medium-high, and the riskiest change here.

### T6 — Registration and admin console *(optional)*

Deferred by decision on 2026-09-02: demo accounts with passwords are acceptable,
and this is only built if time allows. `researcher`, `site_a`, `site_b` and
`site_c` already exist.

If built: access is a single realm role (`access:vo.caios.ca:ap-u`), so approval
is one role assignment. Keycloak gets `registrationAllowed: true` and an
organisation/reason attribute; a small service holds a Keycloak service account
and exposes pending/approve/deny; the dashboard gets an `/admin` page using the
`configs/dashboard/home/` + patch `0004` pattern, and the existing unauthorized
state becomes "pending approval". Smoke test registers a throwaway user,
asserts PAPI refuses it, approves, asserts PAPI accepts it, deletes it.

**Difficulty.** High. 1.5–2 days.

### T7 — Availability hardening

`caios-compose.service` so `docker compose up -d` runs at boot, which is what
makes `vault_init` re-run and closes the Vault hole. `scripts/preflight.sh`
running every check in order and printing one verdict. Prune images on both
constrained nodes. Smoke: **the cold-start run** — reboot `caios_server`, run
preflight with no manual step, deploy one of each. Difficulty: low-medium.

### T8 — Demo script and recording

Open on the home page rather than the marketplace. Name the low-code and
high-code use cases explicitly. Fold in the OSCAR beat from `docs/oscar-demo.md`
with its discoverability warning. Re-measure every timing. Two timed
read-throughs by a person, as the test user rather than as an administrator.
Then record. Difficulty: low, gated on everything else.

---

## Phase R — worth doing, not required

Added 2026-09-02 at the supervisor's request. Everything here would improve the
demo and none of it blocks it. **The rule for this phase: work it only when the
required stages are done or blocked on someone else**, and take items in the
order below, because that order is reward against risk rather than reward alone.

Two of these are cheap enough that they will probably happen; the last two
almost certainly will not, and are written down so the decision is deliberate
rather than forgotten.

| # | Item | Reward | Risk / complexity | Verdict |
|---|---|---|---|---|
| **R1** | **Deploy `ai4-accounting`** | **High.** Turns the Statistics history from an empty chart into a real usage story, and answers Q-04 — the open question with the shortest fuse. It is the one page that currently shows nothing where a reviewer expects something. | **Low.** Already an upstream repo in our list; `ACCOUNTING_PTH` is the only wiring, and patch `0004` already made its absence graceful. Nothing else depends on it, so a failed attempt costs an afternoon and changes nothing. | **Do it first** |
| **R2** | **A CAIOS status repository** | **Low-medium.** Turns the notifications bell from "unconfigured" into a working feature, and gives the demo somewhere to announce a maintenance window. | **Very low.** One line of tenant config — D-62 deliberately left the hook in place. The cost is not the change, it is acquiring the habit of maintaining the repository. | **Do if idle** |
| **R3** | **Replace the workspace landing page** | **Medium-high.** `INFO.md` inside every dev-env renders a large AI4/eosc logo and "Welcome to AI4OS Development Environment" — *inside the window the high-code beat spends three minutes in*. It is the most prominent AI4EOSC branding left anywhere, and the one place a viewer reads closely. | **Medium.** The file is baked into the module image, so the options are a `template` stanza in the dev-env job that overwrites `/srv/INFO.md` at start, or a forked image. The first is ~10 lines of HCL and reversible; the risk is that it runs before the volume mount and gets clobbered, which needs a deploy to find out. | **Do if time** |
| **R4** | **Default the dev-env to a scientific image** | **Medium.** `u24.04` is bare Ubuntu with no numpy, so a test user taking the default gets an empty workspace. Deferred by decision on 2026-09-02: the demo script will say to pick `tf2.14.0` instead. | **Low-medium**, but awkward. Upstream overwrites the configured default in code (`docker_tag.value = tags[0]`, natsorted Z-A), so it needs a patch to a line that exists specifically to pick the newest tag. Small, but it fights upstream's intent rather than filling a gap. | **Documented, deferred** |
| **R5** | **Registration and admin console** | **Medium.** Checklist item 4, and it would let a stranger reach the platform without us minting an account. Downgraded on 2026-09-02: demo accounts with passwords are acceptable for the walkthrough. | **High.** The only genuinely new software in the plan — a Keycloak service account, an approval API, a new dashboard page. 1.5-2 days, and it touches the realm that login depends on. | **Only if everything else lands** |
| **R6** | **A Nextcloud, a Harbor, or a `tryme` node** | **Low for the demo.** Each switches one disabled control back on — storage and Batch, Snapshots, Try me respectively. None of them appears in the walkthrough. | **High**, and misdirected: these are three separate services for three controls the demo never touches. The honest version of this reward is "the interface has fewer greyed-out things in it". | **No** |

**Why R1 before R3** even though R3's reward is higher: R1 cannot break anything
that currently works, and R3 edits the job template that the entire high-code
beat runs on. When two items are close on reward, the one that cannot damage a
working demo goes first.

**Why R6 is a no rather than a maybe.** Three services to un-grey three controls
nobody clicks during the walkthrough is the definition of effort spent on the
appearance of completeness. The controls now say why they are off, which is the
part that mattered.

---

## Execution order

1. Browser pass — **done 2026-09-02**
2. T1 — catalogue mirror, with the timeout — **done**
3. T2 — clear the stale deployments — **done**
4. T3 — licensing, LICENSE/NOTICE, AI4OS references — **done**
5. T4 — every control tested; unavailable ones disabled or removed — **done**
6. T5 — HTTP switch — **plumbing done; flip held on `docs/nginx-proxy.md`**
7. **T7 — availability and preflight** ← next
8. T8 — demo script, read-throughs, record

Phase R runs alongside, whenever the above is blocked on someone else.

T1 goes first because two of the five demo paths run through the catalogue. T5
sits after the fixes so nothing is written twice against a scheme that then
changes. T6 moved after T7 once it became optional.

---

## Demo readiness

- `pytest tests/` green
- `scripts/preflight.sh` green from a **cold boot**, no manual step
- Zero third-party requests during a full walkthrough, measured in the browser
  and in `docker logs caios_papi`. The platform should demo with the internet
  unplugged
- Every sidenav item and profile tab clicked in a clean profile: no error toast,
  no unresolved spinner, no ejection, no AI4EOSC string on screen
- No module misstates its licence
- Low-code path end to end: pick a model, deploy it serverless, file in, result out
- High-code path end to end: JupyterLab workspace, federated client, then the
  private LLM from the same notebook with the stock OpenAI client
- Every URL the Deployments page prints answers 200
- No certificate dialog anywhere in the walkthrough
- Every number in the script re-measured on the day
- Two timed read-throughs, the second with no correction

Then record. The video is the last action taken on this project.

---

## Future improvements

For checklist item 7. Assessed against this architecture rather than in the
abstract. None of it is in scope.

**ServerlessLLM.** Today a vLLM deployment pins a whole GPU for as long as it
exists — gotcha 19 records the consequence, that the cluster fits exactly one
LLM while the federated demo is up. Loading-optimised checkpoints and live
migration would let several models share a GPU with cold starts in seconds.
It targets Kubernetes/Ray, so it lands on the **OSCAR cluster, not Nomad**, and
that node has no GPU. Effort high; risks are ours specifically — the GPUs are
MIG-backed vGPU slices with 10.3 GB usable against a nominal 12 (gotchas 11 and
15), and a multi-model server is exactly the workload that overshoots that;
gotcha 13's lesson would have to be re-established on Kubernetes. Not before the
grant; a credible 3–4 week piece afterwards.

**Pure Kubernetes.** One scheduler instead of two, a much larger ecosystem, and
what most reviewers expect. But PAPI renders Nomad HCL, the deployment model is
Nomad-native throughout, and the position that makes this project defensible —
"we deploy AI4OS, we do not fork it", currently true at fourteen small patches —
depends on staying on Nomad. It is not a migration, it is a different platform,
and the cost is permanent ownership of a fork. **Not realistic as a
replacement.** The realistic version is the one already half-built: keep Nomad
for long-running and stateful work, grow the existing OSCAR/Kubernetes side for
serverless and inference. That needs one thing — a GPU node on the Kubernetes
cluster — which also unblocks ServerlessLLM, making it the highest-leverage item
here.

**Three cheaper wins.** A real certificate on the PACS Lab domain retires the
whole reason item 5 exists. Deploying `ai4-accounting` turns the Statistics
history from empty into a real usage story and answers Q-04. A CAIOS status
repository is one line of tenant config (D-62 left the hook in place) and turns
the notifications bell from unconfigured into a working feature.

**Agentic workflow**, noted only because it was flagged as a thesis topic: OSCAR
already chains services through event-driven storage triggers, one service's
output directory being the next one's input event. A graph editor over OSCAR
services is a UI over machinery that runs today, not a new runtime. That is the
cheapest credible starting point.
