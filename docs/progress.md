# Progress

Running log of what has actually been done. Updated at every step.

Newest entries at the top. Each entry says what changed, what was verified, and
what it unblocks — so that "done" always means something checkable.

**Where we are: MVP complete. Stages 0–5 are done.** A federated training runs
across three hospital sites on three separate machines and beats what any one
site can do alone; the platform around it now reads as a medical imaging
platform rather than somebody else's stack. `docs/demo-script.md` is written
and timed at 22 minutes.

**Stage 6 — LLM deployment — is the current focus.** As of 2026-08-20 a
**Stage 6 is complete.** A researcher deploys a private language model onto the
lab's GPU, talks to it in a browser at their own subdomain, and calls it from a
notebook with the stock OpenAI client — and the demo has a beat for it.
`docs/llm-plan.md` carries what each of the seven stages actually found, most of
which was not in the plan.

---

## Status at a glance

| Stage | What it delivers | State |
|---|---|---|
| 0 — Local scaffold | Every config, script and patch, written and self-tested | **Done** |
| 1 — Cluster | Consul, Nomad, Traefik running; a job reachable over HTTPS | **Done** — gate passed |
| 2 — Identity | Keycloak and Vault; a token PAPI accepts | **Done** — gate passed |
| 3 — Control plane | PAPI and the dashboard; deploy a model from the browser | **Done** — gate passed |
| 4 — Federated learning | Training across three sites | **Done** — gate passed |
| 5 — Content and branding | Curated catalogue, CAIOS look | **Done** — gate passed |
| 6 — LLM deployment | vLLM + Open WebUI on the lab's own GPUs | **Done** — gate passed, `docs/llm-plan.md` |

**Nothing is blocking.** The GPU-scheduling defect found on 2026-08-19 was fixed
the same day (R-18). Next actions, in order:

1. **Rehearse the demo end to end in a browser**, following
   `docs/demo-script.md`. The LLM half has now been driven by a human clicking,
   and it found two faults; the federated half has not.
3. **A real domain and certificate** (V1 item 1). Half a day, and it removes the
   browser warning that currently opens the demo.
4. Record it.

Two things a person still has to judge, which no script settles:

- Does the dashboard read as a medical imaging platform to someone who does not
  know the project? That is the Stage 5 gate's real half.
- Is brain MRI the right disease area? (Q-08 — answered by default, not by
  decision.)

---

## 2026-09-02 — The vanishing deployment, reproduced and fixed

A report that a deployment "goes starting, then running, then disappears". It
reproduced, and it was two separate faults wearing one symptom.

### Why they died

Three abandoned jobs were sitting in Nomad — all `posenet-tf`, titled "Test
deployment", "module test" and "1", all `Stop: False`, so nobody stopped them.
The allocation says it plainly: container exits **code 1** two seconds after
start, three times, then `Not Restarting — Exceeded allowed attempts`.

Reproduced directly:

```
docker run ai4oshub/posenet-tf:latest deep-start --jupyter
[C ServerApp] Running as root is not recommended. Use --allow-root to bypass.
```

Every module image ships a `deep-start` that launches JupyterLab as root
**without `--allow-root`**. Checked across the catalogue: five of nine confirmed
so far, none with it. So the `jupyter` service has never worked on any module,
and the option was offered on every one of them.

`configs/papi/modules-user.yaml` now offers `deepaas` only, with the measurement
written next to the line so nobody adds it back. A module *is* an inference API;
the interactive workspace is the dev-env tool.

### Why they disappeared

`nomad_utils.get_deployments()` filters `Status != "dead"`, which hides a
deployment the user deleted and a deployment that died by itself equally — and
the second is the entire reason someone opens that page.

Patch `0015`. `Stop` separates the cases exactly, so the filter becomes
`(Status != "dead" or Stop == false)`. Two more changes, because "failed" with
no reason is barely better than gone: the task event stream already carries
`Exit Code: 1, Exit Message: "…"` and nothing was reading it; and a dead job
whose allocations have been garbage collected reported **`queued`**, which says
it is about to start when it is over.

All three abandoned deployments now render as red `failed` rows with a reason.
D-39 and D-50 at the other end of a deployment's life: *deleted*, *crashed* and
*queued* are three different words.

### What works, tested rather than assumed

- **A module deploys and runs.** `ai4os-demo-app` with DEEPaaS: `running` for
  six minutes, endpoint answering.
- **The high-code path works.** A dev-env deployed *through the dashboard* with
  the Jupyter service: JupyterLab loads at its own subdomain, accepts the
  password, opens a workspace and runs commands in a terminal.
- **The GPU is real.** `check-gpu-scheduling.sh` passes — `torch.cuda = True` on
  the MIG device, with and without Nomad selecting it.

### Three things found on the way that are not fixed yet

- **The dev-env's default tag is `u24.04`, a bare Ubuntu with no numpy.** A test
  user taking the default gets an empty environment. Upstream overwrites the
  configured default in code (`docker_tag.value = tags[0]`, natsorted Z-A), so
  changing it needs a patch. The FL demo uses `tf2.14.0`.
- **The workspace's own landing file is AI4EOSC-branded** — a large AI4/eosc
  logo and "Welcome to AI4OS Development Environment", inside the window the
  high-code beat spends its time in. It is baked into the module image.
- **Statistics reporting 4 GPUs is correct**, not a bug: four compute nodes with
  one MIG slice each, and `caios-traefik` is the ingress node with none by
  design.

### On the federated results

They were measured 2026-08-15, before the MIG fix on 08-19 — but the FL clients
run with `gpu_num: 0` by design (gotcha 10, the two-GPU cap), so the MIG defect
never touched them. The recorded 0.853 stands.

---

## 2026-09-02 — T1: the marketplace is served by this cluster

The catalogue no longer reads GitHub at request time. `scripts/mirror-catalogue.sh`
mirrors it into `catalog/mirror/`, Caddy serves it at `/mirror/`, and patch
`0014` makes the source configuration. Measured after: **9 modules in 0.016 s,
6 tools in 0.019 s, and no GitHub host in PAPI's log for the whole run.**

Committed, not gitignored — 19 files, 356 KB — so a fresh clone can serve the
marketplace with no internet at all.

### It fixed a licensing bug on the way past

`ai4-metadata.yml` schema 2.0.0 has no `license` key, so a module's licence is
only ever known from its repository. Upstream reads it from `api.github.com` in
`utils.get_github_info()`, which short-circuits on `IS_DEV` and returns
`{"created": "1970-01-01", "updated": "1970-01-01", "license": "MIT"}`. `IS_PROD`
must be false here (gotcha 1), so that branch is always taken — and
`common.py` assigned it unconditionally over the real metadata.

Every module in the marketplace reported **MIT** and **1970-01-01**. Verified in
a browser: `ai4os-yolo-torch` now reads **AGPL_3_0**, which is what Ultralytics
YOLO actually is, and `posenet-tf` reads Apache-2.0. Three distinct licences
across nine modules where there had been one.

`repo-info.json` carries them, built once at mirror time from `api.github.com`
rather than per request — correct *and* offline, and fifteen calls per refresh
sits comfortably inside GitHub's 60-per-hour unauthenticated limit where fifteen
per page load would not. That asymmetry is the whole argument for the mirror.

### And a timeout, which is the half that matters most

`requests.Session()` passed none anywhere, so an unreachable source held the
worker thread until TCP gave up. That is why the outage presented as a spinner
that never resolved rather than as an error. Now `(5, 15)` and a **503 naming
the source**, because the address is configuration now and a misconfigured one
looks identical to an outage.

Measured, by pointing a throwaway container at an unroutable address:
**90 s+ hang becomes 503 in 2 s.**

### D-44, met for the second time, and it cost half an hour

`mirror-catalogue.sh` did `rm -rf "$OUT"` then `mkdir`, which is the exact
mistake `build-fl-bundles.sh` was fixed for on 2026-08-22 — and the warning was
already written in this script's own header. compose bind-mounts
`catalog/mirror` into Caddy, a bind mount follows the **inode**, so Caddy went
on serving the deleted directory: every `/mirror/` URL 404ing while the freshly
built files sat on the host looking perfect. PAPI answered 503 naming the
source, which is at least how it was found in seconds rather than minutes.

Emptying in place now, with a test that fails if `rm -rf` comes back.

### T2 as well

The four stale federated-learning deployments from 2026-08-15 are stopped —
three workspaces and the FL server, all registered under the old private
hostname `pacs-deployments.192.168.104.105.sslip.io` and unreachable publicly,
so a test user clicking them got nothing. The `ai4os-llm` "test meeting" is
still running, pending a decision.

### Verified

`pytest tests/` is **139 green** including 18 new ones;
`scripts/check-catalogue.sh` passes all four sections;
`scripts/check-branding.sh` passes again — its marketplace section had been
failing since the outage.

---

## 2026-09-02 — The finalization browser pass, and three faults no API probe could see

`docs/finalization-plan.md` is the plan for the last stage, against the
supervisor's eleven-item checklist. This entry records what the browser pass
that opens it actually found.

### It corrected the headline of the plan's first draft

The draft said `raw.githubusercontent.com` was permanently unreachable from the
cluster. It is not — it was unreachable for about three hours on 2026-09-01, and
the draft was written inside that window. PAPI's own log dates it: every
`Network is unreachable` falls in `19:47-19:59` and `22:36-22:54` UTC, with
successful catalogue loads before, between and after, and a 60-sample probe the
next morning came back 60/60.

That makes the fix easier to justify, not harder. The dependency is consulted at
request time, on the demo's critical path, about ten times per cold catalogue
load — and `requests.Session()` carries **no timeout anywhere**, so when it does
fail the page spins rather than errors. An intermittent hang is worse to plan
around than an outage.

### Three faults that only a browser could report

**Profile -> API Keys ejects the user out of the application.** Not an error
toast: `/v1/llm/api_keys` proxies to AI4EOSC's LiteLLM at
`vllm.cloud.ai4eosc.eu`, hardcoded in `routers/v1/llm/keys.py`, which answers
401 — and the error interceptor lands the browser on
`/forbidden;errorMessage=...` carrying another platform's internal error in our
URL bar. One click from the profile menu.

**Every module in the marketplace reports the wrong licence.** `IS_PROD` must be
`false` (gotcha 1, not optional), so `IS_DEV` is true, so
`utils.get_github_info()` returns mock data — and `catalog/common.py` writes it
straight over the module's real metadata:

```
metadata["license"] = gh_info.get("license", "")   # -> "MIT", always
metadata["dates"]["created"] = ...                  # -> "1970-01-01", always
```

All nine modules report `MIT` and `1970-01-01`. `ai4os-yolo-torch` wraps
Ultralytics YOLO, which is **AGPL-3.0**. Stating someone else's AGPL work as MIT
on our own marketplace is the one real licensing problem this project has, and
it is ours rather than anything inherited from AI4OS.

**The Deploy menu offers four targets and two do not exist here** — "Inference
API (cloud)" via an Infrastructure Manager we do not run, and "Inference API
(EU Node)", which offers European infrastructure on a platform whose argument is
that data stays in Canada. Not missing features to be annotated; wrong offers to
be removed.

### Three more third-party leaks, after the six already closed

All on module detail pages: a **`build aborted`** badge served from
`jenkins.cloud.ai4eosc.eu`, every image in a module description fetched from
`raw.githubusercontent.com` by the visitor's browser, and `api.github.com` for
dates and licence — currently short-circuited by `IS_DEV`, so it fires only if
that is ever fixed naively.

And four AI4 strings the earlier grep could not see, because they come from
module metadata rather than from `en.json`: the dev-env's own title "AI4OS
Development Environment", the "AI4 pre trained / trainable / inference" category
chips, the tag **`vo.imagine-ai.eu`** rendered on our modules, and the Modules
page tab strip reading "AI4EOSC".

### Two earlier findings withdrawn

Both came from probing the API without a browser:

- **User statistics are not zeros.** `Your Usage` renders live figures — 5 jobs,
  6 CPUs, 33 GiB, 1 GPU. Only the historical timeseries is empty. No annotation
  needed.
- **The catalogue outage is intermittent, not permanent.** As above.

### Checked and working

Home page, login, Modules (9), Tools (6), LLMs, Deployments, Inference (3 OSCAR
services), Batch training, Try me, Statistics and Profile -> Overview / Storage /
Services all render with no console error. OSCAR is healthy throughout — what
the outage broke was the *route* to it, since "Deploy -> Inference API
(serverless)" lives on a module detail page.

### Also recorded

Five stale deployments, not four: three `tool-devenv-*` workspaces, the
`CAIOS federated server` (all four from 2026-08-15, registered under the old
private hostname and unreachable publicly), and a `tool-llm-*` titled "test
meeting". The four federated ones are approved for deletion.

Registration is deferred by decision — demo accounts with passwords are
acceptable for the walkthrough, so T6 is built only if time allows.

---

## 2026-09-01 — Deployed. The dashboard people see is now the one we have been building

`caios/dashboard:latest` was still `pre-f1`. Neither the typography pass nor the
home page had ever served a request, so deploying F3 shipped F2 with it and the
change was larger than "the home page":

- the home page at `/`, where the modules catalogue used to be
- F2's tokens on **every** page: one typeface, machine values in a monospace
  with figures that line up, hairlines in place of Material's drop shadows
- the platform-status feed off, so nothing asks GitHub about another project
- no-cache on `config.json`, `vllm.yaml` and `en.json`

Deployed by retagging rather than rebuilding, so the bytes that were verified
are the bytes that are serving:

```bash
docker tag caios/dashboard:f3-home caios/dashboard:latest
sudo docker compose -f compose/docker-compose.yml \
     --env-file configs/env/caios.env up -d --force-recreate dashboard
```

Git tag `f3-home` records what the image was built from.

### The page pass R-35 asked for, finally done

F2 was verified on Modules and Deployments only, and R-35 has been carrying the
other six pages ever since. Deploying made the check possible against live data,
and it found nothing: **Statistics, Modules, Tools, LLMs, Deployments,
Inference, Try me, Batch training and Profile** all render correctly. Status
pills unchanged in hue, no page with a horizontal scrollbar, no error toast.

The LLM catalogue page, outstanding in `CLAUDE.md` since Stage L5, has now been
looked at: nine models, every badge a real image, every card with a
description. **R-35 closed.**

### Verified after the deploy

`scripts/check-branding.sh` passes, including the section added on 2026-08-30
that had been failing on purpose until this deploy. `scripts/check-home-page.sh`
passes against the live host. `pytest tests/` is 122 green.

### Rollback

`rollback/dashboard-pre-f1.tar` is the exact image that was serving until today,
so the undo is a load, a retag and a recreate, in about ten seconds. The image
just deployed is saved as `rollback/dashboard-f3-home.tar` for whatever replaces
it next.

---

## 2026-08-31 — The home page, rewritten for the people who will read it

The first version was written for the wrong person. It described the platform
the way its builders describe it to each other: cluster size, GPU model,
scheduler, control plane, container, bearer token. All true, none of it any use
to a clinician-scientist, which is who opens this page.

**Now three blocks**: what this is, one stage carrying six slides, and a way in.
It was seven sections and about five thousand pixels.

The six slides are the three capabilities and the three depths of control, in
two labelled groups, because they answer two different questions. In Use is
gone: it and Depth of Control were the same argument told twice.

**The architecture diagram is gone too.** It was accurate and useless. Each
slide now carries a drawing of what the capability means, and the federated
slide carries the real accuracy curve from `demo/fl/results/`, projected from
the recorded numbers rather than drawn by hand, with the best single site and
the pooled ceiling as reference levels. It is the most credible thing the
project has, and a research audience reads a figure more fluently than a
paragraph.

### Three faults it found, none of which any existing test could see

**A CSS property beats an SVG presentation attribute.** The hero motif
positions twelve tiles with `transform` attributes; reusing the entrance
keyframe, which ends on `transform: none`, moved all twelve to the origin and
stacked them. Twelve elements in the DOM, twelve correct attributes, one tile on
screen. The chart caption did the same with `text-anchor` and ran off the
drawing. Found by measuring bounding boxes in a browser. **D-65**, with a test.

**Unhashed assets are cacheable, and one of them is every string in the
interface.** After the rewrite a browser that had opened the previous build kept
rendering the previous build's words and showed raw translation keys for
anything new. Nothing was wrong with the deployment. Patch `0006`, **D-66**.
Upstream had tried to prevent this and written `location = /config.json`, which
matches nothing, because the application fetches `/assets/config/config.json`.

**The same hole covers the runtime configuration**, which is worse than stale
copy: change the API address and a returning visitor keeps talking to the old
one.

### Tests

`tests/test_home_page.py` is twenty assertions now, and the new ones encode what
the feedback asked for rather than what the code happens to do: no
infrastructure vocabulary, no count of machines, no em dashes, a word budget on
the visible copy, six slides in two groups, the chart equal to the recorded
curve, and no presentation attribute that the stylesheet also sets.

`scripts/check-home-page.sh` is the other half, and it has to exist for the same
reason the branding check does: the unit tests read the repository and cannot
see a build. It checks a running dashboard, and it takes
`CHECK_DASHBOARD_URL` so a candidate image can be checked before it is
deployed.

---

## 2026-08-30 — R-38 closed: the dashboard stops reading somebody else's status feed

Found while checking that the new home page issues no request of its own. It
does not; the shell around it made three, and two of them went to
`api.github.com/repos/**AI4EOSC**/status/issues` on every full page load.

That feed drives the startup popup, the notifications bell and the red
maintenance banner on the deployments list. Three consequences, and the
likeliest is the dullest:

- **The rate limit.** GitHub allows 60 unauthenticated requests an hour per IP
  address — measured against that endpoint. Two per page load is about thirty
  loads an hour from one address, and an audience in one building shares one.
  Past that, every visitor gets a red *"Error retrieving the platform
  notifications"*. Upstream evidently meets this: their error interceptor has a
  special case so a 403 **from that exact URL** does not throw the user onto the
  Forbidden page. Symptom handled, cause not.
- **Their notice on our screen.** All three paths pass a notice whose VO is
  `null`, which is what a platform-wide announcement looks like. An AI4EOSC
  maintenance window, announced correctly by them, would render as our popup and
  as a red banner over our deployments table.
- **The leak itself.** The sixth, after the analytics beacon, the model
  catalogue, the fonts and the icon set.

**Turned off** — patch `0005`, D-62. The source is `platformStatusUrl` in the
tenant config now, read like every other setting, and empty means no request is
made at all rather than a request to a default. The bell renders its existing
"No notifications" and the deployments list renders no banner: unconfigured, not
broken (D-50). Pointing it at a CAIOS status repository stays available as a
one-line config change if the feature is ever wanted.

Verified in a browser on the built image: zero requests to any GitHub host, no
error toast, and the bell's empty state intact. The bundle carries no
`api.github.com` reference at all.

`scripts/check-branding.sh` gained section 3d, which asserts both halves — the
served config carries the key blank, **and** the bundle no longer names the
repository, because either alone can be true while the feature still fires.

> **That check now fails against the running dashboard**, which is still
> `caios/dashboard:latest`. That is the correct answer to the question it asks:
> what is deployed still leaks. It goes green when the new image is deployed.

---

## 2026-08-29 — Stage F3: `/` is a home page

The dashboard's front door used to be `/catalog/modules`, so the first thing
anyone saw was a grid of model cards — no statement of what CAIOS is, who it is
for, or that it runs in Canada. It is now a page that says all three in the
first screen.

Seven sections, in the order the argument runs: identity and sovereignty, who
it is for, the three capabilities, the depth of control, the platform in use,
provenance, and the catalogue. Built and verified against the built image in a
browser (D-49); `caios/dashboard:latest` is untouched, so nothing deployed has
changed.

### The decision that shaped the page

The plan called for three pillars. Three cards for serverless inference,
federated learning and private language models would have said — silently, and
to everyone — that these are three products. They are three paths through one
cluster.

So there is **one schematic of the cluster**, drawn from
`docs/infrastructure.md`, and choosing a capability re-lights the path through
it. Nothing is removed between states, only dimmed, because it is the same
cluster either way. The data marks inside the three site nodes are drawn in
every state and never move, which is the federated argument made in a picture
instead of a paragraph.

### What it found

- **The schematic was illegible and only a browser could say so.** Drawn at a
  nominal size and left to scale into its column, every label rendered at about
  six pixels. Re-laid out for the width it actually gets, then confirmed by
  measuring each label's bounding box against its own rectangle in the live
  page.
- **The scroll reveal was one browser away from a blank page.**
  `IntersectionObserver` was constructed, given an element filling the viewport,
  and never called back. Every armed section stayed invisible and every test
  passed. Now the hidden state is applied by the directive rather than the
  stylesheet, `prefers-reduced-motion` skips arming entirely, and a 1.5 s
  timeout abandons the effect if nothing reports anywhere. **D-59.**
- **F1 had a second way back in.** The page wanted IBM Plex — the family F1
  staged and never used — and importing the generated `_fonts.scss` to get it
  would also have redeclared `Material Symbols Rounded` against our 65-glyph
  subset. That is F1's failure, reintroduced application-wide from a
  page-level stylesheet. The two text faces are declared directly instead and
  the icon family is not named at all. **D-61.**

### How it is built, and what it costs to keep

| | Where | Drift |
|---|---|---|
| The page | `configs/dashboard/home/`, staged verbatim | none |
| The strings | `configs/dashboard/i18n/en.caios.json`, merged into `en.json` | none |
| The route | `patches/ai4-dashboard/0004-home-route.patch` | nine lines, one file |

**D-58.** Removing the patch restores the old redirect exactly, and the staged
module is simply never routed to.

The page issues **no HTTP request of any kind** — no PAPI call, no font, no
image, no analytics — so it cannot show an error, a spinner or an empty state
whatever the cluster is doing. Given that gotchas 18, 19 and 20 were all the
dashboard reporting backend state wrongly, that is worth more than it sounds.
`tests/test_home_page.py` keeps it true, along with the counts it prints, the
translation keys it uses, and the icon font it must not declare.

### One thing it found that is not its own

Checking that the home page issues no request of its own — it does not — showed
what the shell around it fetches. Three of the calls on every page load go to
`api.github.com/repos/**AI4EOSC**/status/issues`, which is another project's
issue tracker, read from the visitor's browser, and which can render *their*
maintenance notices as *our* popups and banners. A sixth third-party leak, and
the only one that can put somebody else's words on the screen during the demo.

Recorded as **R-38** in `docs/frontend-plan.md` and deliberately not fixed here:
it is outside F3, it touches the notifications button and the deployments list,
and it needs a decision — point it at a CAIOS status repository, or disable it
so the feature reads as unconfigured rather than broken (D-50).

### Still outstanding

A screenshot pass into `docs/screenshots/after/`, the narrow layout seen at a
real 768 px rather than simulated, and someone actually *watching* the motion —
the browser that would not report intersections is not the place to judge
whether an animation feels right.

---

## 2026-08-22 — STAGE 6 COMPLETE: the demo has a beat for the private model

Stage L6, and with it the whole LLM feature. The walkthrough is **25 minutes**,
with beat 7 giving the private language model three of them.

### The gate item, measured rather than asserted

"LLM and federated learning demonstrated in the same session on the same
cluster, neither degrading the other" is easy to claim and worth checking. With
the LLM serving on `caios-wn-gpu-3`, all three hospitals were bootstrapped
through the **real one-liner** and joined:

```
10 rounds in 34.6 s          final accuracy 0.845
LLM answered every 20 s throughout, at 71–81 ms
```

Neither moved. The federated numbers are a rehearsal run, not a re-measurement —
the recorded headline stays 0.853 against 0.806 and 0.865.

### What writing the beat found that planning it had not

**The four-line notebook did not work.** A dev-env workspace calling the
deployment's endpoint gets `CERTIFICATE_VERIFY_FAILED`: it is served by Traefik
under our own CA, which the workspace has never heard of. That is R-05 for the
fourth time — helper tasks, then Open WebUI, then Open WebUI's model list, and
now the path a *user* takes.

The fix needed nothing new. Every hospital bundle already ships `caios-ca.pem`,
so `SSL_CERT_FILE` pointing at it verifies properly. That matters more than it
sounds: the obvious alternative is `verify=False`, and putting TLS verification
switched off on screen while arguing that this is the private option teaches a
reviewer something about our care rather than about our architecture (D-43). The
`curl -k` in `bootstrap.sh` remains the only unverified request in the demo, and
it is the one that fetches the CA — a defensible answer rather than an awkward
one.

`bootstrap.sh` also installs a pinned `openai` client, so the beat has no
`pip install` in it. Checked against the federated path before committing to it:
flwr 1.16.0, TensorFlow 2.14.0 and numpy 1.26.0 unchanged, `pip check` clean.

### And a fault that would have broken beat 5 on the day

`build-fl-bundles.sh` did `rm -rf "$DIST"` then `mkdir`. That produces a new
**inode**, and Caddy has that directory bind-mounted at `/srv/fl`. A bind mount
follows the inode, not the path — so Caddy went on serving the deleted one.
`/srv/fl` empty inside the container, every `/fl/*` URL a 404, and the freshly
built bundles sitting on the host looking perfect.

That is the bootstrap one-liner each hospital pastes in beat 5, broken by the
very script `docs/runbook.md` tells you to re-run before the demo. The running
federation never noticed — those three sites bootstrapped in August and had
their bundles already. **Only a new bootstrap would have hit it, which is to say
only demo day.** Emptying in place keeps the inode; verified by rebuilding
without touching Caddy. D-44.

### The beat is cheaper than expected

Both timed parts are effectively instant — the chat reply streams in under two
seconds, the notebook cell returns in one. So its three minutes are talking, not
waiting, which makes it the only beat in the script where somebody in the room
can pick the prompt. Worth using.

The measured answer, from inside the site_a workspace:

> The patient has a stable, 8mm left periventricular white matter
> hyperintensity on T2 imaging, consistent with prior findings.

### What is left, and it is not engineering

Three things, all needing a person rather than a script:

- **A timed read-through of beat 7, twice.** Its mechanics are measured; nobody
  has read it aloud with a stopwatch.
- **The LLM catalogue page in a browser** — L5's open item.
- **The cold-start smoke run.** Deliberately skipped: the cluster is holding a
  deployed LLM and a live federation, which is exactly the state the gate needed.
  Do it after the next teardown.

---

## 2026-08-22 — STAGE L5 GATE PASSED: the marketplace stops phoning GitHub

The dashboard's LLM catalogue page is now served entirely by this cluster. The
planned change was one hardcoded URL. Reading the page it serves found two more
faults, both of which the audience would have seen, and neither of which any
status-code check could report.

### The planned part: one file, two consumers

`tools.service.ts` fetched the model list from
`raw.githubusercontent.com/ai4os/ai4-papi/.../etc/vllm.yaml` — the file *AI4OS's*
PAPI serves. Ours serves a curated nine. So the model **cards** described
upstream's thirteen while the deploy **dropdown** came from our PAPI: cards for
models we do not offer, no card for four that we do, and a Hugging Face token
field keyed off the wrong list. It was also a third-party fetch made by the
user's browser from a page meant to be self-contained on a private subnet.

Now `/assets/config/vllm.yaml`, staged from `configs/papi/vllm.yaml`. Verified
live: PAPI's nine options and the dashboard's nine cards are the same ids in the
same order, and the default is in the card list. R-07 closed, D-40.

### Fault 1: the model id was two labels glued together

`vllm.yaml` keys each entry on the Hugging Face id. The dashboard read it and
threw the key away — `{ name, ...config }`, where the entry's own `name`
overwrites the key — then rebuilt it as `family + '/' + name` in three places.

That is right only when the organisation equals the family label. It is not for
`mistralai/Ministral-3-3B-Instruct-2512` (family `Mistral`) or
`ibm-granite/granite-4.1-3b` (family `IBM`): **two of our nine, and four of
upstream's own thirteen**, so this is inherited, not caused by curating.

| where | what a user saw |
|---|---|
| clicking the card | the deploy dropdown opened blank — the preselected value was not one of its options |
| the "Card" chip | `huggingface.co/Mistral/…` → 404 |
| `needs_HF_token` | `find()` missed, `?? false` decided no token was needed |

The third is the one that outlives the demo. Everything we offer is ungated, so
the answer is right **by accident**; a gated model would have rendered no token
field and then failed at PAPI with a 400 — three components away from the cause.
Patch `0003`, R-25, D-41.

**How it survived upstream is the interesting part.** Their mock YAML keyed on
the *display name* and carried no `name` field at all, so `{ name, ...config }`
filled `name` in from the key and every test passed — against a shape the real
file never has. A test that agrees with a bug is worse than no test. The patch
repairs the fixtures and gives one of them a family that differs from its
organisation, so the regression is covered rather than assumed.

### Fault 2: six of the nine cards rendered a broken image

Each card renders `assets/images/llm-companies/{family}_logo.png`. Our nine
models span five families; upstream ships a badge for two of them, plus
`meta-llama`, which we dropped. Missing: Mistral, LiquidAI and IBM — and
LiquidAI alone is four of the nine.

**Nothing reported it, and nothing could.** nginx answers every missing path
under this dashboard with `index.html` and HTTP 200. `file` on the response says
"HTML document"; the browser draws a broken image. Third time this exact pattern
has cost something here: it is how the dashboard once shipped with no logo and
no favicon, and it is why `check-branding.sh` has tested artwork by content
rather than by status since Stage 5.

Fixed with generated lettermarks in the CAIOS palette rather than downloaded
trademarks — no licensing question in a grant demo, and a page of six real logos
and three approximations looks worse than one that is visibly consistent.
Guarded twice, because the moments differ: a unit test fails if any family in
`vllm.yaml` has no badge, so adding a model with a new family fails at test time;
`check-branding.sh` checks what is actually served, per family. R-26, D-42.

### What this stage is really about

Both faults were found by reading the component that consumes the file the stage
was about, not by running anything. Every check in this repository was green
before and after fault 2 existed, because every one of them would have had to
look at a response body to see it — which is the rule this project already had,
applied one level further out than anyone had applied it.

### Also fixed while here

- The runbook's dashboard rebuild recipe was missing `sudo` (Docker needs it on
  this host) and `--force-recreate` (without it, `up -d` leaves the old
  container serving the old image — the failure where you rebuild three times
  and the page never changes).
- D-38 and D-39 were written into `docs/llm-plan.md` when L4b shipped and cited
  in `CLAUDE.md`, but never appended to `docs/decisions.md`. Recorded now.

### What is left

The catalogue page has not been looked at in a browser. Everything above is
measured from the served bytes. L4's browser check found two faults no script
had; this page has not had its equivalent.

---

## 2026-08-22 — Stage L4b: the fix is smaller than the bug

**Patch `0011` shipped and PAPI is running it.** Two conditions over data
`get_deployment` had already fetched — no extra Nomad calls, no new dependency,
and **no dashboard change**, which was checked rather than assumed: `starting`
and `queued` are already badges in `deployment-badge.ts`, and `status ===
'running'` appears in exactly one place in the whole Angular application, the
*Quick access* gate. Fix PAPI and the button disables itself.

**Verified live against the scenario that produced the bug.** A second LLM
submitted while the first held the only free GPU:

```
status   : queued
error_msg: Waiting for cluster capacity. This deployment will start on its own
           when resources free up... 'cores' exhausted on 1 node(s); 'cpu'
           exhausted on 2 node(s); 'devices: no devices match request'
           exhausted on 1 node(s)...
```

Yesterday, the same request produced a red `error` and an empty string. And
nothing already running changed: the LLM and all four federated jobs still read
`running` through the patched PAPI, which is the single-task no-op holding in
production rather than only in a test.

**The fixtures could not be committed as recorded.** Raw Nomad allocation and
job JSON carries `VLLM_API_KEY`, `WEBUI_ADMIN_PASSWORD`, `jupyterPASSWORD`,
`RCLONE_CONFIG_RSHARE_PASS` and Nomad token IDs in clear text. That is R-09,
which we had written down as a risk about job *specifications* without noticing
it applies to anything recorded from one. Fixtures are trimmed to the fields the
code reads, and a test keeps them that way.

**Then the smoke test failed the fix.** Patch `0011` v1 passed all thirteen unit
tests and the assertion written for this very stage caught it on the cluster:

```
PAPI status trail: queued -> starting -> running
[FAIL] PAPI said 'running' at T+178s; the UI only answered at T+200s (R-23)
       22s of green badge and an enabled Quick access button
```

184 seconds down to 22, and to 38 on the next run — the remainder is the same
mistake one layer down. v1 moved the signal from the wrong container to the
right container, but a container starting is not a socket listening. Open WebUI
opens its port only after the FastAPI lifespan has created the administrator and
closed signup, so Nomad's "task started" is 22-38 seconds early.

**An instrumented deployment settled it**, sampling PAPI, HTTP, Nomad and Consul
every five seconds from T+0. Three findings, none of them guessable:

| | |
|---|---|
| `DeploymentStatus` is **absent** through the window, never `False` | the obvious `Healthy is False` test would have passed every unit test and done nothing on the cluster |
| `Healthy=True` and the first HTTP 200 land in the **same sample** | with a health check present it is an accurate readiness signal, not an approximation |
| T+0 reports `error` | between acceptance and the first scheduling pass there is an evaluation, no allocation and no failure — so **every** deployment on this platform has always flashed red for its first second |

**And the Consul check, which had just been dropped, turned out to be half the
fix.** It was dropped on the argument that turning a 502 into a 404 helps
nobody. That was about the wrong thing: without a check, Nomad falls back to
task-state health, so `DeploymentStatus.Healthy` means "every container started"
— exactly what R-23 is about. The gate has nothing to read without it. Kept, with
an explicit `healthy_deadline` of 10 minutes because Nomad measures it from
allocation start and a cold `vllm/vllm-openai` pull is 30.8 GB.

Two changes, useless apart: a `tcp` check on each service, and
`deployment_is_ready()` requiring both the user tasks started and — where checks
exist — Nomad's own healthy verdict.

**Then it failed again, at three seconds, on a hop Nomad cannot see.**

| | |
|---|---|
| T+206 s | Open WebUI's port opens; the Consul check goes passing |
| T+216 s | Nomad marks the allocation healthy — `min_healthy_time`, 10 s default |
| T+219 s | Traefik finishes polling Consul and the public URL serves |

Traefik's consul-catalog provider **polls**, at 15 s by default. No health check
can cover that: the check runs on the node against the allocation, and the thing
that is late is the reverse proxy in front of it. `min_healthy_time = "25s"`
clears the poll with margin, leaving the badge conservative by ten to twenty
seconds instead of optimistic by three — the harmless direction.

**184 s → 22 s → 3 s → 0.** Each of the first two fixes passed the complete unit
suite. Every layer was found by a test, none by reasoning about it.

### Gate passed 2026-08-22

```
PAPI status trail: queued -> starting
  [ ok ] PAPI never reported 'running' before the UI answered
  [ ok ] page title is "Open WebUI"        [ ok ] signup is closed
  [ ok ] the account is an administrator   [ ok ] dropdown offers Qwen/Qwen3.5-2B
  [ ok ] 229 SSE chunks at 10.0 ms         75.1 tok/s
```

Stage L4b is done. Three deployments were spent finding a bug two conditions
wide, which is the correct ratio when the failure mode is a green badge.

---

## 2026-08-21 — the browser check: the chat window is fine, the dashboard is not

**Stage L4's last open item was "somebody has to open it in a browser".**
Somebody did. The chat interface itself passed on every count — certificate
warning, login, model dropdown, word-by-word streaming, session survives a
logout. What failed was everything *around* it, and neither fault is in the LLM
tool. Both are in how PAPI describes any deployment.

This is the fifth time in this project that a fault appeared only when a human
clicked something, and the fifth time no programmatic check was failing.

### The reconstruction

Every line below is from `caios_papi` and Nomad, not from memory.

| Time (UTC) | |
|---|---|
| 22:41:58 | second LLM submitted. PAPI 200. Eval `e1ae7636` → **placement failure**, blocked eval created |
| 22:42:41 | first LLM deleted — frees the GPU, 2 cores, 16 GB on `caios-wn-gpu-3` |
| 22:42:45 | the blocked eval unblocks and **places the second LLM** |
| 22:42:48 | the second LLM is deleted, 3 seconds after it finally started |
| 22:43:19 | third LLM submitted, placed straight away |
| 22:43:20 | vLLM container starts → **PAPI reports `running`**, *Quick access* enabled |
| 22:46:14 | vLLM finishes loading (174 s); `open-webui` starts |
| 22:46:24 | Nomad marks the allocation healthy — the UI answers |

### 1. A green badge in front of a 502, for 184 seconds

`nomad_utils.py` reads `TaskStates["main"]["State"]`, and PAPI renames the first
task in a template to `main`. In our job `main` is vLLM, which is a `prestart`
**sidecar** — so it is `running` while the model is still loading and while
Nomad has not started Open WebUI at all.

Consul then does the other half. The service registers with one check on it:

```
service b4d12680-...-ui   192.168.104.188:31960
  checks: [('Serf Health Status', 'passing')]
```

The node is alive. That is the whole assertion. Traefik publishes the route
against it and proxies to a port nothing is listening on, which is a
`Bad Gateway`. R-23.

### 2. "Queued for a GPU" and "this will never run" are the same red badge

The second deployment was never rejected. Nomad said:

```
Evaluation "2fde368b" waiting for additional capacity to place remainder
```

and placed it 47 seconds later. But PAPI has no `queued`-for-capacity state —
any job with an evaluation and no allocation is `error`. **And the message was
empty**, because `/v1/job/:id/evaluations` returns evaluations unordered,
upstream reads `evals[0]`, and the one that came back first was the blocked
evaluation, which carries no `FailedTGAllocs`. Red badge, nothing beside it, and
a deployment that was 47 seconds from working got deleted. R-24.

### The capacity limit underneath, which is not a bug

| Node | Running | CPU free | RAM free | GPU free |
|---|---|---|---|---|
| `caios-wn-gpu-0` | docuum + 1 FL workspace | 3900 MHz | 24.9 GB | yes |
| `caios-wn-gpu-1` | docuum + 1 FL workspace | 3900 MHz | 24.9 GB | yes |
| `caios-wn-gpu-2` | docuum + FL workspace + FL server | 1900 MHz | 20.9 GB | yes |
| `caios-wn-gpu-3` | docuum + the running LLM | 600 MHz | 14.1 GB | **no** |

An LLM needs 5300 MHz — 2 exclusive cores plus 1300 — 16.3 GB, and a GPU. The
three hospital nodes have a free GPU each and still cannot take it: two
exclusive cores do not fit in what is left of a 3-core machine once a workspace
holds one. **While the federated demo is up, this cluster hosts exactly one
LLM.** That belongs in the demo script, because the failure is one click away.

### What it costs to fix: half a day, and no dashboard change

Checked before writing the stage: `starting` (yellow) and `queued` (orange) are
already in the dashboard's `deployment-badge.ts`, and *Quick access* is already
gated on `status === 'running'`. Fix PAPI and the button disables itself. So
Stage L4b is one patch — `0011` — of two conditions over data
`nomad_utils.py` has already fetched, plus a unit test built from the recorded
JSON of this incident. Written up in `docs/llm-plan.md`; proposes D-38 and D-39.

`docs/llm-risks.md` gains R-23 and R-24, `docs/runbook.md` gains both symptoms,
and its "what to expect" table now warns that a green badge means the model has
started *loading*.

---

## 2026-08-20 — STAGE L4 GATE: the chat interface works, and two 200s were lying

**A researcher can now deploy a private language model and talk to it.** Not
through `curl` — through a chat window at their own subdomain, over HTTPS, with
replies arriving word by word.

Both faults this stage found returned **HTTP 200**. That is the whole character
of it: every check the previous stages run was green throughout, because every
check the previous stages run is about the engine.

### 1. The chat interface could not reach the model beside it

Open WebUI and vLLM are two tasks in the same Nomad allocation — same node,
ports a hop apart. Upstream hands the UI the *public* HTTPS endpoint of the vLLM
next to it, so the chat interface left the node, resolved a public hostname,
crossed Traefik and came back into our own CA.

```
ERROR open_webui.routers.openai - [SSL: CERTIFICATE_VERIFY_FAILED]
      self-signed certificate in certificate chain
INFO  "GET /api/models HTTP/1.1" 200
```

Open WebUI catches the error and carries on. So: allocation healthy, login page
working, admin account correct, **model dropdown empty**, and nothing outside the
container's stderr saying why.

This is R-05, which we had already found, fixed, and written up — as a problem
with two helper tasks. It was missed here because this endpoint is not in our
job template: it arrives from PAPI as `${API_ENDPOINT}`, so there was nothing
wrong to see in the file we had audited. Patch `0010` sends it to
`${NOMAD_ADDR_vllm}` instead, and D-36 is broadened from "health checks" to
"nothing in a deployment reaches its own services by public hostname".

### 2. The smoke test made itself the administrator

Open WebUI grants admin to whoever registers first. Upstream claims the account
from outside, with a `poststart` task polling `/api/v1/auths/signup` until it
lands. Between the port opening and that POST succeeding, the deployment belongs
to whoever asks.

I measured the window, decided it was small enough to leave alone, and then lost
the race to it on the very next run:

| run | UI answered | `create-admin` | outcome |
|---|---|---|---|
| 1 | T+108 s | won at T+106 s | fine |
| 2 | T+101 s | still polling | **the test registered itself as admin** |

The script's only crime was checking whether a stranger could sign up — which
you can only test by trying. It got a 200, and the deployment's real credentials
were refused afterwards with *"The email or password provided is incorrect"*: an
error describing the symptom and not the cause. The demo-day equivalent is
somebody clicking *Quick access* a moment early, which R-21 already establishes
people will do, because the link appears before it works.

Fixed with `WEBUI_ADMIN_EMAIL` / `_PASSWORD` / `_NAME`, which Open WebUI handles
inside its FastAPI lifespan — the account is created and signup closed **before
uvicorn creates the listening socket**. Zero window instead of a small one. The
`create-admin` task is gone; it could not have stayed, because signup answers
403 once an admin exists and upstream's script retries that for fifteen minutes
and then fails the allocation. That also frees a container, a `pip install` at
startup, and 300 MB.

R-22, and D-37: **a window that is small is not a window that is closed.**

### What was measured

| | |
|---|---|
| deploy → chat interface answering | **101 s** (LFM2.5-1.2B-Instruct) |
| SSE chunk spacing through Traefik | **6.0 ms** — a buffered burst is ~0.02 ms |
| thinking model, one sentence of answer | 2388 chars of `reasoning`, 199 of `content`, 2.8 s before the first answer token |

The streaming test originally used a wall-clock floor and passed on 0.7 s of
spread, because the model counted to twenty too quickly to judge. A wall-clock
threshold is really a test of how fast the model is, and this catalogue spans 18
to 129 tok/s. It measures the **gap between chunks** now, which separates
streamed from buffered by three orders of magnitude instead of by luck.

### Smaller things, and the L3 question answered

Open WebUI probed `host.docker.internal:11434` for Ollama on every model
listing — a DNS lookup that cannot succeed, on the first page an audience sees.
It also shipped an `arena-model` placeholder that shared the dropdown with the
real model; with one model deployed, it compares that model with itself. Both
off.

**The two thinking models render properly**, which Stage L3 left open with
"confirm, or drop both". The stream separates `reasoning` from `content`, so
Open WebUI has what it needs for its collapsible section. They stay — but they
are not what to deploy live, because three seconds of visible thinking before a
one-sentence answer is three seconds of dead air on camera.

### What is left

One thing: **nobody has opened it in a browser.** The mechanism is measured, but
`docs/progress.md` records three faults in this project that appeared only when
a human clicked something, and none of them had a failing programmatic check.

---

## 2026-08-20 — the catalogue is real: 9 of 9 models load and answer

Stage L3's last open gate item closed. Every model the dashboard offers was
deployed, asked a question, and deleted — `scripts/check-llm-catalogue.sh`, about
an hour, unattended. Full table in `demo/llm/README.md`.

```
Qwen3.5-2B (default)            ok    182 s    76.6 tok/s
Qwen3.5-0.8B                    ok    172 s   128.7
Ministral-3-3B-Instruct-2512    ok    101 s    18.2
LFM2.5-1.2B-Instruct            ok     81 s    59.7
LFM2.5-1.2B-Thinking            ok*    81 s      -
LFM2.5-VL-450M                  ok     91 s    68.9
LFM2.5-VL-1.6B                  ok     91 s    63.4
granite-4.1-3b                  ok    111 s    51.4
DeepSeek-R1-Distill-Qwen-1.5B   ok*    91 s      -
```

**Nothing ran out of GPU memory.** Including `granite-4.1-3b`, which this
repository's own config comments had flagged as "the tightest model we offer; if
Stage L3 finds it will not load, drop it". It loads in 111 s. The memory
arithmetic was sound and the warning was wrong in the safe direction — which
only testing could establish.

Two findings for the demo script: **the default is the slowest model on the
list** (182 s against LFM2.5-1.2B-Instruct's 81 s), and throughput varies more
than parameter count predicts, from 18 to 129 tok/s.

### The two thinking models, and a decision made by measurement

`LFM2.5-1.2B-Thinking` and `DeepSeek-R1-Distill` answer into `reasoning` rather
than `content` — R-20 again. Both alternatives were tried:

| | `content` | how it reads |
|---|---|---|
| reasoning parser kept | `null` | Open WebUI renders it as a collapsible section; a script gets `None` |
| parser removed | the model's raw thinking | opens with a literal `<think>` tag on LFM2.5 |

Removing the parser does not produce a clean answer, it produces unedited
thinking. So the parser stays: the demo audience is people looking at a chat
window, and a visible `<think>` tag is the worse failure. Their catalogue
descriptions now tell API callers to read `reasoning`, and **Stage L4 has to
confirm Open WebUI really does render them well** — if not, drop both, because
seven uniform models beat nine with two that need explaining.

### An hour lost to my own test harness, and what it exposed

The first sweep reported three healthy models as timeouts, including
`Qwen3.5-2B`, which had already been deployed successfully four times that day.
That mismatch is what prompted reading the failure output instead of believing
the table.

The cause was mine: PAPI publishes a deployment's endpoint **before** Nomad has
placed the allocation, and at that point it still reads

```
https://vllm-<uuid>.${meta.domain}-deployments.192.168.104.105.sslip.io
```

`meta.domain` is interpolated by the Nomad client, so before placement there is
nothing to interpolate it with and the hostname cannot resolve. The harness
fetched the endpoint once and kept it, so any deployment whose first poll landed
in that window curled an unresolvable name for its whole timeout. Fixed by
treating anything containing `${` as not-an-endpoint-yet.

**The same window exists in the dashboard** — a user clicking *Quick access* too
early gets a dead link. Seconds wide and self-healing, so a papercut rather than
a fault, but exactly the sort of thing that happens on camera. Recorded as R-21.

Two process notes, since both cost real time. An "early bail" added to
`check-llm-deploy.sh` after the stage was verified regressed the readiness loop,
and was reverted rather than debugged — changing a verified script and
immediately using it for a long unattended run was the mistake. And the sweep
printed nothing when a model failed, only the sections that exist on success, so
the first failure arrived as a bare `TIMEOUT` with the diagnostic swallowed. Both
fixed; the broken first pass is kept as
`demo/llm/catalogue-results-BROKEN-HARNESS.tsv` rather than deleted, because a
red result is a claim about the test as much as about the thing tested.

---

## 2026-08-20 — STAGE L3 GATE PASSED: a private model answered a question

**The second headline feature works.** A researcher's account deployed a language
model through the dashboard's own API onto the lab's GPU, and it answered:

> Federated learning is a machine learning approach where a global model is
> trained across multiple decentralized devices or servers, which share only
> their local data and model updates rather than the raw data itself.

The error that started this work — *"requires NVIDIA T4 GPUs"* — is gone.
`POST /v1/deployments/tools?tool_name=ai4os-llm` returns `{"status":"success"}`.

| measurement | value |
|---|---|
| deploy → `/v1/models` answering | **175–204 s** |
| sustained generation | **97.8 tok/s** over 300 tokens |
| GPU memory used | **8963 MiB**, 1603 MiB still free |
| placed on | `caios-wn-gpu-3` — the affinity worked |

PAPI's own view of the deployment confirms every L2 decision reached the running
container: `vllm/vllm-openai:v0.27.1` (pinned, not `:latest`),
`--gpu-memory-utilization 0.80`, `cpu_num 2`, `gpu_num 1`, `memory_MB 12000`.
The API key came back through the documented Vault path,
`GET /v1/secrets?subpath=/deployments/<id>`.

**R-05 proven rather than reasoned about.** `check_vllm_startup` terminated with
**exit code 0** at +175 s. Upstream's version calls its own public HTTPS URL and
would have died on our self-signed CA, taking the allocation with it.

**R-06 confirmed by a running model.** 8963 MiB used against a 9680 MiB budget.
vLLM's own default of 0.90 would have wanted 10890 MiB — more than the card had
free. The prediction and the measurement agree.

### The find of the stage: the model answered, and looked broken

The first completion came back like this:

```json
"content":   null,
"reasoning": "Federated learning is a machine learning approach where..."
```

Qwen3.5 thinks by default, and upstream's `--reasoning-parser qwen3` routes
everything before `</think>` into a separate field. The model answered *inside*
the think block and never emitted the closing tag, so the parser took the whole
response and left `content` null.

**Every ordinary OpenAI client reads `content`** — the Python SDK, LangChain,
editor plugins, and the "call it from a notebook in four lines" beat of the demo.
All of them would have got `None` from a deployment that reported itself
perfectly healthy. It was caught only because `check-llm-deploy.sh` asserts a
**non-empty completion** rather than a 200, which is exactly what this returns.

Upstream has the same class of bug recorded in its own catalogue: two Phi models
are commented out with *"openwebui does not render it's response correctly."*

There were two candidate causes implying opposite fixes — a parser mis-classifying
untagged output, or a model that really wraps everything in tags — so they were
separated by experiment rather than picked. `enable_thinking: false` gave clean
`content`; removing `--reasoning-parser` also gave clean `content` **with no
`<think>` markup leaking**. The tags come from the prompt template, not the
generation. Parser dropped from the two general-purpose Qwen entries, kept on
`LFM2.5-1.2B-Thinking` and `DeepSeek-R1-Distill`, where separated reasoning is
the point.

Two new unit tests encode the rule, and both were checked against this morning's
configuration to confirm they catch it.

### A correction to this plan's own claim

R-11 said a cached redeploy would "start in seconds". It does not. Alloc creation
to health check passing:

| | cold cache | warm cache |
|---|---|---|
| Qwen3.5-2B | **197 s** | **175 s** |

**The cache saves ~22 s of a ~190 s startup.** The dominant cost is
`torch.compile` and capturing 86 CUDA graphs on a 16-SM slice, which happens
every start. The cache still earns its place — bandwidth, and independence from
Hugging Face being up — but the demo must pre-deploy either way, which R-14's
ordering rule already required.

**`scripts/check-llm-deploy.sh`** runs the whole cycle unattended: deploy, wait,
assert a real completion, report throughput and GPU use, delete. Self-cleaning,
so it can run in a loop.

---

## 2026-08-19 — STAGE L1 GATE PASSED: caios_llm is in the cluster

Node 6 joined as `caios-wn-gpu-3`, the dedicated LLM host. The destructive step
was approved after L0 showed its `/mnt` held only `lost+found`.

```
NAME             STATUS  ELIGIBLE  meta.status  meta.type  meta.tags  meta.role
caios-wn-gpu-0   ready   eligible  ready        compute    gpu        -
caios-wn-gpu-1   ready   eligible  ready        compute    gpu        -
caios-wn-gpu-2   ready   eligible  ready        compute    gpu        -
caios-wn-gpu-3   ready   eligible  ready        compute    gpu        llm

4 compute node(s) schedulable.
```

- `/dev/vdb` relaid as `/dev/vdb1`, XFS with `prjquota`, at `/mnt/data`.
- Consul and Nomad joined; the other five nodes untouched throughout.
- **The GPU plugin fix propagated by itself.** The node fingerprinted
  `NVIDIA H100L-1-12C MIG 1g.12gb` at 10564 MiB on first boot, straight from the
  group var — no separate step. That is what fixing it in Ansible bought.
- CUDA computes there: capability 9.0, bfloat16, 12100/10475 MiB.
- `ai4-nomad_tests` certified all four nodes; 54 seconds.
- **`nomad job plan` on the LLM job: "All tasks successfully allocated."** It
  said "Dimension cpu exhausted on 2 nodes" this morning.
- All four federated-learning deployments came through on their original nodes.

### A garbage collector was deleting the images as they arrived

`playbook-prepull-images.yml` pulled eleven images onto the new node, reported
**changed** for all eleven, and finished with five present.

`docuum` runs as a Nomad **system job on every compute node**, evicting
least-recently-used images above a threshold upstream hardcodes at **50 GB**:

```
[INFO] Docker images are now using `40.37 GB`, which is within the limit of `50 GB`.
```

The full set is **67.9 GB**, because `vllm/vllm-openai:v0.27.1` is **30.8 GB on
disk** — 10.5 GB is the *compressed* registry size, and every disk figure written
here before today used the smaller number. Corrected throughout.

The demo-day version is worse than wasted bandwidth: vLLM is the biggest image on
the node and therefore first to be evicted. Deploy a dev environment after it,
cross the threshold, and the next LLM deployment re-downloads 30 GB live.

Fixed with `nomad-jobs/docuum.hcl` at 80 GB — the full set plus ~12 GB, still
leaving ~45 GB of the volume for allocation dirs, logs and the model cache. Node
6 now holds **11 of 11 images at 67.91 GB** with nothing evicted. Because
re-running `playbook-nomad.yml` restores upstream's 50 GB, there is now
`ansible/playbook-docuum.yml` to reapply ours and a check in
`scripts/verify-cluster.sh` that **fails** if it has reverted.

### The fix this plan proposed for placement does not work

With four compute nodes, three dev-env-shaped jobs land on:

```
   caios-wn-gpu-0: 1
   caios-wn-gpu-1: 1
   caios-wn-gpu-3: 1     <- the LLM host
```

So a fresh FL deployment would show "Hospital C" running on the LLM machine.
The plan's answer was a soft anti-affinity on `meta.role = llm`. **Tested before
being written into anything, and it changed nothing** — same three nodes. Nomad
combines affinity with the spread score, and an idle node's spread score
outweighs a `-100` affinity.

**Deploying the LLM first does work**, measured the same way: with an LLM-shaped
allocation holding `caios_llm`, the workspaces go to the hospital nodes and none
goes near it. That ordering is now documented in `scripts/deploy-fl-demo.sh`,
`docs/infrastructure.md` and CLAUDE.md, and becomes a line in the demo script.

The 332-line dev-env template copy is therefore **not** being carried. A hard
constraint would guarantee placement, but it means owning a copy of a file the
primary demo depends on, and it makes a workspace fail outright when the three
hospital nodes are full. Recorded as an option in R-14 rather than taken.

---

## 2026-08-19 — STAGE L2 GATE PASSED: the LLM tool is deployable here

All four blockers addressed. One patch, four configuration files, 31 unit tests,
one smoke test. No fork.

**`patches/ai4-papi/0009-llm-gpu-models.patch`** does two things. It replaces the
hardcoded `if "Tesla T4" not in models` with a list read from `LLM_GPU_MODELS`,
**defaulting to `Tesla T4`** so unset behaves exactly as upstream — the same
shape as patches 0001, 0002 and 0007. And it fixes `"openwebui"` to
`"open-webui"`, the typo that let a standalone UI deployment skip its credential
checks and come up with signup open.

**Four config files, bind-mounted over upstream's**, the mechanism already used
for two other tools:

- `configs/papi/tools/ai4os-llm/nomad.hcl` — device constraint dropped, resources
  that fit a 3-core node, images pinned and not force-pulled, both helper tasks
  moved off the public HTTPS URL onto `${NOMAD_ADDR_*}`, a host-mounted Hugging
  Face cache, `shm_size` set.
- `configs/papi/tools/ai4os-llm/user.yaml` — the form, with CAIOS wording.
- `configs/papi/vllm.yaml` — nine models instead of thirteen, every one with
  `--gpu-memory-utilization 0.80` and none with `--dtype float16`.
- `compose/docker-compose.yml` — the mounts, and `LLM_GPU_MODELS`.

### The tests were checked against upstream, not only against ourselves

A suite that passes on both the fixed and the broken version tests nothing. So
the same nine assertions were pointed at `vendor/ai4-papi`'s template:

```
caught  no Tesla T4 constraint
caught  dedicated cores fit: template reserves 8 dedicated cores; nodes have 3
caught  shared cpu survives: 8 cores leave -10000 MHz in the shared pool
caught  memory fits: tasks ask for 32000 MB; 30972 MB is schedulable
caught  images pinned: vllm/vllm-openai:latest uses a moving tag
caught  not force-pulled
caught  helpers stay in-allocation: VLLM_ENDPOINT is 'https://vllm-...'
caught  helpers survive conn errors
caught  shm_size set

9/9 upstream defects caught by the suite
```

### The live API serves our configuration

Checked field by field rather than by status code, because every failure this
guards against returns 200:

```
ai4os-llm is in the tools catalogue
serving our 9 models, not upstream's thirteen
form defaults to Qwen/Qwen3.5-2B
deployment types: ['both', 'vllm', 'open-webui']
PAPI allows:  NVIDIA H100L-1-12C MIG 1g.12gb
cluster has:  NVIDIA H100L-1-12C MIG 1g.12gb
nomad job validate: Job validation successful
```

### Stage L1 stopped being an argument and became a measurement

`nomad job plan` against the live cluster:

```
- WARNING: Failed to place all allocations.
    * Dimension "cpu" exhausted on 2 nodes
    * Dimension "cores" exhausted on 1 nodes
```

The job is correct; the cluster has no room for it while the three FL workspaces
hold cores on all three compute nodes. Node 6 is a requirement, not a preference.
The arithmetic in `docs/llm-infrastructure.md` predicted exactly this.

### Two things found on the way

**`scripts/apply-patches.sh` was silently skipping the dashboard.** It does
`rm -rf build/<repo>`, and `build/ai4-dashboard` holds root-owned files from the
Docker build in `scripts/build-dashboard.sh`. The `rm` failed with "Permission
denied", and under `set -e` everything after it was skipped — so `ai4-papi` was
patched, printed success, and `ai4-dashboard` was not. Same shape as D-29: a
failure that presents as silence. Fixed.

**Six patches were undocumented.** `test_every_patch_is_referenced_in_the_readme`
found that `patches/README.md` explained 0001, 0002 and the two non-PAPI patches
but not 0003 through 0008. All now documented, along with 0009.

**New test infrastructure**, the first in this repository: `tests/` with pytest,
run by `bash scripts/run-tests.sh` in a gitignored venv. Offline — no cluster, no
Nomad, no network — so it can run on every change. 31 tests in 0.03 seconds.

---

## 2026-08-19 — STAGE L0 GATE PASSED: node 6 measured, and it is what D-31 said

First login node 6 has ever had. **D-31 confirmed by measurement**, not inherited
from the other nodes:

| | node 6 (`ai4eosc-6`) | the three site nodes |
|---|---|---|
| cores | 3 | 3 |
| RAM | 34 GB | 34 GB |
| GPU | `NVIDIA H100L-1-12C`, 10565 MiB free, cc 9.0 | identical |
| driver | 580.105.08 | identical |
| MIG instances | 1 | 1 |
| egress to Hugging Face | yes | yes |

**The gate for Stage L1, and the reason L0 exists: `/mnt` holds `lost+found` and
nothing else.** Its disk is the shipped layout —

```
vdb   125G ext4  /mnt  ephemeral0        <- no partition table, no vdb1
```

— which is exactly the thing that has to be relaid, and it is safe to relay.

**It is a bare node.** NVIDIA driver 580.105.08 present, from the
`gpu-enabled-instance` snapshot. No Docker, no Nomad, no Consul: nothing has ever
been provisioned on it, and it has been up 2 weeks doing nothing. So the
CUDA-in-container test cannot run there yet — Stage L1 installs the container
runtime and the check is re-run then. CUDA compute is already proven on hardware
identical in every measured respect, so this is a formality.

**A flaw in the check script, found by running it somewhere new.** It reported
"CUDA does NOT work on this node" for what was really "this node has no Docker".
That is the same class of mistake as trusting `nvidia-smi`: a check that cannot
tell "broken" from "not applicable" will eventually send someone hunting a
hardware fault that does not exist. It now distinguishes the two, and says which
stage installs the missing piece.

Access, for the record: the pasted `SHA256:2NamFbFqAlAKIchz…` turned out to be
node 6's **host** key — the server proving its identity to us, the opposite
direction from the client key that grants access, and a one-way hash either way.
The key itself was installed separately and works.

---

## 2026-08-19 — GPU scheduling FIXED cluster-wide

The defect found an hour earlier is fixed, verified, and turned into a
regression test. **Approved by the supervisor to disturb the federated-learning
deployments; in the end it did not have to.**

**One Ansible variable.** `nomad_nvidia_plugin_version: 1.0.0 -> 1.1.0`, applied
by a new `ansible/playbook-nvidia-plugin.yml` rather than by re-running the whole
Nomad role — that role also prepares volumes, writes certificates and rewrites
agent configuration, none of which needed to change and all of which was a chance
to break something that worked. The playbook runs `serial: 1`, keeps the old
binary as `nomad-device-nvidia.1.0.0.bak` so a rollback does not need the network,
and waits for the GPU to reappear before moving to the next node.

Rolled out one node first, verified, then the other two.

**What changed on each node**, 22,779,848 bytes (built Oct 2021) -> 28,292,408:

| | before (1.0.0) | after (1.1.0) |
|---|---|---|
| device name | `NVIDIA H100L-1-12C` | `NVIDIA H100L-1-12C MIG 1g.12gb` |
| instance id | `GPU-db6f8125-...` | `MIG-f18b0103-...` |
| memory reported | 12288 MiB (nominal) | **10564 MiB** (real) |

**End to end, through the stanza every PAPI template uses:**

```
job WITH device "gpu" { count = 1 }
  SMI GPU 0: NVIDIA H100L-1-12C (UUID: GPU-...)
  SMI   MIG 1g.12gb  Device 0: (UUID: MIG-...)
  TORCH_CUDA=True
  DEV=NVIDIA H100L-1-12C MIG 1g.12gb
```

`scripts/check-gpu-scheduling.sh` now reports **"GPU scheduling is healthy"**,
having reported "BROKEN" an hour before. That script is the regression test.

**The FL deployments survived.** All four still running, on the same three nodes,
tasks healthy. `leave_on_terminate = true` in the client config had me expecting
them to be lost — Nomad reattached to the running Docker containers instead. Worth
recording, and not worth relying on: the next restart may behave differently.

**Downstream, as predicted.** The device name change propagates:
`configs/papi/var/gpu_models.csv` gained a row for the MIG name at its real
10564 MiB, PAPI was restarted, and the API now serves

```
gpu_type options: ['', 'NVIDIA H100L-1-12C MIG 1g.12gb']
```

so the dashboard's GPU dropdown is correct. **Patch `0009`'s allowlist, when it
is written in Stage L2, must use the new string** — the old one no longer matches
anything.

**The lesson, now gotcha 13 in CLAUDE.md:** `nvidia-smi` is not evidence that a
GPU works. Every GPU check in this project multiplies two matrices.

---

## 2026-08-19 — STAGE L0: CUDA works, and GPU scheduling does not

Stage L0 run. It cleared the technical unknown it was written for and found a
cluster-wide defect that has been there since the cluster was built.

**The good news, measured on `caios_site_a` in a container:**

```
torch.cuda.is_available : True
device                  : NVIDIA H100L-1-12C MIG 1g.12gb
capability              : (9, 0)          -> bfloat16 supported
1024x1024 matmul        : agrees with CPU to 4.4e-4
bfloat16 matmul         : works
```

So the MIG-backed vGPU is not an obstacle, and upstream's `--dtype float16` —
which exists only because a Tesla T4 is compute capability 7.5 — is confirmed
unnecessary for us.

**A correction to our own numbers.** `torch.cuda.mem_get_info()` reports
**total 12100 MiB, free 10475 MiB**, where `nvidia-smi` says 12288 / 10565.
vLLM sizes itself from the CUDA figures, so those are the ones that count:

| `--gpu-memory-utilization` | wants | against 10475 MiB free |
|---|---|---|
| 0.90 (vLLM default) | 10890 MiB | over by 415 MiB — will not start |
| 0.85 | 10285 MiB | fits, 190 MiB spare — too tight |
| **0.80** | **9680 MiB** | **fits, 795 MiB spare** |

R-06 confirmed. The 0.80 recommendation is now measured, not predicted.

### Blocker 5, and it is not about the LLM

**A Nomad job that asks for a GPU gets one CUDA cannot use.** These are
MIG-backed vGPUs: the card holds one `MIG 1g.12gb` instance, and CUDA can address
the instance but not the parent. `nomad-device-nvidia` **1.0.0** — the version in
`ansible/group_vars/all.yml` — allocates the **parent**.

At the container level, four ways:

| `NVIDIA_VISIBLE_DEVICES` | MIG exposed | `torch.cuda` |
|---|---|---|
| `GPU-<parent uuid>` — what the plugin selects | no | **False** |
| `MIG-<instance uuid>` | yes | True |
| `0:0` | yes | True |
| `all` | yes | True |

And through the real Nomad path, twice: a batch job **with**
`device "gpu" { count = 1 }` reports `TORCH_CUDA=False` and no MIG line; the
identical job **without** the stanza reports `True` and
`NVIDIA H100L-1-12C MIG 1g.12gb`. Setting `NVIDIA_VISIBLE_DEVICES` in the task's
own `env` block does not help — the plugin overrides it.

**Every PAPI job template uses that stanza. So nothing GPU-backed has ever
actually computed on this cluster.** It stayed invisible for a week because the
only check anyone ran was `nvidia-smi`, which passes — the entry above on
2026-08-12, *"the GPU is visible inside a workspace"*, was true and useless. This
is the exact failure mode that entry was later flagged for in R-18, written as a
theoretical risk before it turned out to be a live one.

The federated-learning demo is unaffected: D-18 made its clients CPU-only, which
is now a considerably better decision than it looked at the time.

**Fix: one Ansible variable.** MIG support landed in `nomad-device-nvidia`
**1.1.0** — issues #3, #27 and #53, all closed 2024-08-22 with that release. The
role fetches it straight from `releases.hashicorp.com`, and the 1.1.0 artifact is
present and downloadable, verified. **Not yet proven on our hardware**; the bump
restarts Nomad agents, which disturbs the four running FL allocations, so it
needs its own window and its own approval.

### Two scripts, so none of this is a transcript

- `scripts/check-llm-node.sh` — measures a candidate node and, crucially,
  **multiplies two matrices** rather than asking whether the GPU is visible. It
  also prints the `--gpu-memory-utilization` table for that node, and
  distinguishes a node already through `playbook-prepare-volumes.yml` from one
  still in the shipped layout.
- `scripts/check-gpu-scheduling.sh` — deploys the two probes above and reports.
  This is the acceptance test for the plugin bump: it must go from FAIL to pass.

Both were run; both reproduce the findings. All probe jobs purged afterwards, the
four FL deployments untouched, all four nodes still `ready`.

### Still blocked, and it needs you

The cluster SSH key is not installed on `192.168.104.188`, so it cannot be logged
into from `caios_server`. `docs/ssh-setup.md` is the same ten-minute procedure the
other four nodes went through and it needs a key only you hold. Until then, node
6's specs are inherited rather than measured — and nobody has seen what is on the
volume Stage L1 would erase.

---

## 2026-08-19, later — two questions answered, and the reformat explained

**Q-11 answered → D-31.** The sixth instance is ours, unused, and identical to
the other five. It becomes `caios_llm`, a dedicated LLM host. No new instances
are needed for Stage 6. It has still never been logged into, so Stage L0 changes
from *discovery* to *verification* — the numbers are inherited from the other
nodes rather than read off this one, and one of them (what is on `/dev/vdb`) is
the thing Stage L1 erases.

**Q-09 answered → D-32.** Upstream's LLM catalogue, used as it is. No
fine-tuning, no custom weights. The consequence is a wording constraint rather
than an engineering one: the claim this feature supports is **privacy** — your
model, your hardware, your prompts never leave — and not medical competence.
Nothing in the demo script may imply otherwise. Swapping in a fine-tuned variant
later costs one line in `configs/papi/vllm.yaml`, provided it fits the same
10.3 GB budget.

**The destructive step, explained properly.** The plan asserted that joining
node 6 requires reformatting `/dev/vdb` and did not show why, which is not good
enough for an irreversible operation on shared infrastructure.
`docs/llm-infrastructure.md` now has a section that does, with the evidence:

- These instances ship `/dev/vdb` as **125 GB of ext4 written directly to the
  raw device, with no partition table.** There is no `vdb1`.
- `ai4-nomad_tests` (`tests/node/gpu.py`) asserts
  `unique.storage.volume in ["/dev/vdb1", "/dev/sdb1"]`, and that suite is the
  **only** thing that sets `meta.status=ready`, which every PAPI job template
  requires. A node failing it looks healthy and silently never receives work.
- The fingerprint follows one line in `ai4-ansible`'s `nomad.j2`: hosts in the
  `nomad_volume` group get `data_dir = /mnt/data`, everything else gets
  `/opt/nomad` on the 20 GB root disk. Verified live — `caios-wn-gpu-0` reports
  `/dev/vdb1` and 134 GB, `caios-traefik` reports `/dev/vda1` and 20 GB.
- Creating a partition means writing over the start of the disk, where the
  existing filesystem's metadata lives. **There is no non-destructive path from
  whole-device ext4 to a partition.** XFS is incidental — the partition is the
  requirement.
- Only `/dev/vdb` is affected. `/dev/vda` — OS, `/home/ubuntu`, SSH keys,
  packages — is untouched, as is every other node. `playbook-prepare-volumes.yml`
  independently refuses to run if `/mnt` holds anything but `lost+found`, and
  carries a hard assert that it can never run against `caios_server`, whose
  volume holds this repository.

Four alternatives were considered and are written down with why each is worse,
so the choice is reviewable rather than assumed.

**Renumbering:** the plan's proposed engineering decisions moved from D-31…D-35
to D-33…D-36, since D-31 and D-32 are now settled.

---

## 2026-08-19 — Stage 6 planned: LLM deployment

**New focus, and it is the second headline feature.** A researcher deploys a
private language model onto the lab's own GPUs — vLLM as the engine, Open WebUI
as the chat interface. The argument is the same one as federated learning,
escalated: the platform that trains across hospitals without moving data also
answers questions without sending them to a vendor.

**Nothing built. Four documents written**, and everything in them measured
against the live cluster rather than assumed:
`docs/llm-plan.md` (staged plan with tests), `docs/llm-concepts.md` (what the
pieces are), `docs/llm-infrastructure.md` (what the hardware is), and
`docs/llm-risks.md` (what goes wrong).

**The tool has four blockers, not the one it reports.** The dashboard's
"requires NVIDIA T4 GPUs" error is the check that happens to fire first:

1. A hard-coded `"Tesla T4"` string comparison in PAPI's Python
   (`tools.py:604`) — still present at upstream `master`, so there is no fix to
   pull.
2. A second `Tesla T4` device constraint in the Nomad job (`nomad.hcl:171`),
   which would leave the job pending forever with no error.
3. **The job asks for 8 dedicated CPU cores and 32 GB on nodes with 3 and 30.**
   This is the real blocker, it is larger than the memory gap, and no node in
   this cluster could ever have placed it. There is a trap inside the fix:
   Nomad's `cores` removes those CPUs' MHz from the shared pool, so reserving
   all three leaves nothing for the helper tasks and the job still will not
   place.
4. Both helper tasks call **their own public HTTPS URL** and so hit our
   self-signed CA from a stock Python image. Neither catches exceptions, and
   both are `prestart`/`poststart` hooks — so the allocation dies with a
   traceback that never mentions certificates. This is the one that would have
   cost a day.

**What the GPU actually is.** `NVIDIA H100L-1-12C` decoded: a MIG-backed vGPU,
one `1g.12gb` slice, **16 SMs** of an H100 NVL, driver 580.105.08, CUDA 13.0.

- **Usable framebuffer is 10565 MiB, not 12288** — ECC and vGPU overhead take
  1724 MiB. vLLM's default `--gpu-memory-utilization 0.9` is a fraction of the
  nominal total, so left alone it asks for more memory than exists.
- **Compute capability 9.0, not the T4's 7.5.** Upstream forces `--dtype
  float16` on every model for exactly one reason, stated in its own comment: a
  T4 cannot do bfloat16. We can. Less memory than the reference platform, better
  arithmetic.

Weight sizes were measured from the Hugging Face API rather than estimated:
eight of the thirteen catalogue models fit comfortably in the 10.3 GB budget,
three are tight, and two probably will not start.

**Infrastructure answer: no new instances.** The idle sixth instance
(`192.168.104.188`) becomes `caios_llm`, a fourth Nomad GPU compute client
dedicated to this. The three hospital nodes are not touched. The one caveat is
that it has never been logged into — Stage L0 is ten minutes of finding out
whether it is a GPU node, and the plan is sequenced so nothing depends on the
answer until after that.

**One regression risk found, in the existing feature.**
`scripts/deploy-fl-demo.sh` relies on spread-mode scheduling to land three
workspaces on three nodes. With a fourth compute node that stops being true, so
a recording could show Hospital B running on the machine labelled as the LLM
host. Fixed two ways in the plan: a soft anti-affinity on `meta.role = llm`, and
deploying the LLM before the FL workspaces on demo day.

**Also found, and worth reporting upstream:** `tools.py:575` tests
`type in ["openwebui", "both"]`, but the option value is `open-webui`. So a
standalone UI deployment skips its credential checks entirely, `create-admin`
posts an empty email and password, and the UI serves with signup open — the
first person to find the URL becomes the administrator.

**Corrected in the same change:** `docs/feature-coverage.md` had this at one
engineer-day, based on memory tuning being the whole job. It is four, and the
section now says why.

**Estimated cost: 4 engineer-days**, about 2.5 calendar with two people. The
long pole (Stage L2, the patch and configuration) depends on nothing and can
start immediately, in parallel with identifying node 6.

---

## 2026-08-16 — STAGE 5 GATE PASSED: it reads as a medical platform

The MVP is complete. `scripts/check-branding.sh` passes every mechanical check,
and `docs/demo-script.md` is written and timed at 22 minutes over seven beats.

**The catalogue went from 46 modules to 9.** Upstream's is roughly two thirds
marine biology, agriculture and remote sensing — good modules, wrong audience,
and it is the first thing a visitor looks at. Curated in a fork
(`caios-modules-catalog`), driven by `catalog/keep.txt`, which records the test
applied to every line: would a medical or neuroscience researcher plausibly
deploy this on their own data?

Judged from each module's own summary rather than its name, which mattered more
than expected. `DEEP-OC-mods` reads generic and is network security monitoring.
`ai4os-speech-to-text-tf` sounds like clinical dictation and is keyword
spotting. Two U-Net segmentation models were dropped despite segmentation being
*the* medical imaging task, because one is trained on Cercospora leaf spot and
the other on aerial imagery — a clinician who reads "leaf spot" concludes the
platform is not theirs.

**The finding that matters more than the curation.**
`image-classification-tf-dicom` — chest X-ray, speaks DICOM, on paper the single
most relevant module upstream ships and the anchor for the whole PACS framing —
is undeployable:

- its metadata gives `docker_image` as a bare `image-classification-tf-dicom`
  with no namespace, where every other module gives `ai4oshub/<name>`. PAPI does
  `repo, image = registry.split("/")[-2:]`, which raises `ValueError`, so
  `/config` returns HTTP 500 and the dashboard errors the instant the module is
  clicked;
- and the image is published nowhere findable, so even with the parse fixed it
  would fail at pull.

Patching PAPI would have turned an immediate error into a deployment that spins
and dies in front of an audience. So it is dropped, and **the documented "two
medical modules" is really one.**

**Which makes the AI4Life loader load-bearing, not a bonus.** It deploys any
bioimage.io model by ID. Upstream offers all 68 it supports, in file order, two
dozen of which are near-identical nucleus and E. coli segmentation entries. Ours
is a curated twelve, ordered so the form opens on *"Circuit reconstruction for
electron microscopy"* — connectomics, which is core neuroscience. That is where
the platform's neuroscience credibility now comes from.

A second documentation error found here: `catalog/medical-shortlist.md`
recommends `affable-shark` (70,000 downloads) and claims the IDs were verified
against the loader's own `filtered_models.json`. They were not — that is the
bioimage.io *nickname*; the `id` the deploy form accepts is the concept DOI
`10.5281/zenodo.5764892`. Wrong IDs fail silently, because PAPI just drops ones
it does not recognise, so `scripts/render-ai4life-models.sh` now validates every
line against the live catalogue and refuses to render if any is unknown.

**The dashboard had no logo and no favicon.** Not the wrong ones — none. Every
page carried a broken image in the top-left, and nothing looked like an error,
because nginx answers a missing asset with `index.html` and HTTP 200: the
browser was receiving HTML labelled as a PNG.

The cause was one line in `build-dashboard.sh`, which tested whether the artwork
directory was non-empty with `compgen -G`. It matched the `README.md` sitting in
that directory explaining what to put there, so the placeholder fallback never
ran. It now checks for the four files by name. Artwork is generated by
`scripts/make-brand-assets.py`; the mark is three nodes joined in a triangle,
which is the federated story in one glyph.

**`scripts/check-branding.sh` exists so this cannot recur quietly.** It verifies
assets by content type and magic bytes rather than status code — precisely the
mistake that hid the missing logo — and separates what is live from what is
inert: the runtime `config.json` is clean and the analytics beacon is disabled
(a FAIL if not), while two `cloud.ai4eosc.eu` addresses compiled into the JS
bundle as overridden fallbacks are reported as warnings rather than pretended
away.

**One bug found by accident, worth more than the feature that found it.**
Rebuilding PAPI broke all of its outbound HTTPS to our own domains
(`CERTIFICATE_VERIFY_FAILED`, surfacing as "Fail to fetch data from the url" on
the deployments page). The CA was mounted from `${HOME}/caios-ca.pem`; Docker
needs `sudo` on this host, `sudo` resets `HOME` to `/root`, the file is not
there — and **Docker's response to a missing bind-mount source is to silently
create an empty directory**. So `update-ca-certificates` found a directory,
did nothing, and PAPI started perfectly while trusting no CAIOS certificate at
all. Both mounts are now repo-relative. Every silent "configuration had no
effect" of this shape has the same cause.

---

## 2026-08-15 — STAGE 4 GATE PASSED: federated learning across three sites

Ten rounds, three hospitals, thirty seconds of training, zero failed rounds.

```
  federated across three sites   0.710 -> 0.842, best 0.853
  best single hospital alone     0.806
  all data pooled centrally      0.865
```

Federated closes **81% of the gap** between the best a single hospital can do
and what pooling everything would give — with no slice of data leaving the node
it started on. The chart is `demo/fl/results/federated-vs-baselines.png`.

Where the work actually ran:

| Node | Holds | Slices |
|---|---|---|
| `caios-wn-gpu-0` | Hospital A workspace | 700 |
| `caios-wn-gpu-1` | Hospital B workspace | 958 |
| `caios-wn-gpu-2` | Hospital C workspace + the Flower server | 799 |

**The work was split into six pieces**, each committed and testable on its own,
so that only the last one needed the cluster. That ordering paid for itself: by
the time anything was deployed, the only untested thing left was the network
path.

**The data.** Cheng et al.'s public brain-tumour MRI set from figshare — 3064
T1-weighted slices, 233 patients, three tumour types, CC BY 4.0. Public data
only (D-07), reduced to 64×64 because a federated round has to finish while an
audience watches.

Split deliberately unevenly, because an even split would have made the demo
prove nothing: each site could train a decent model alone and federating would
gain nothing visible. Hospital A gets mostly meningioma, B mostly glioma, C a
spread — the case mix of a referral centre versus a general hospital.

Splits are **by patient, never by slice**. One patient contributes several
near-identical slices, so a random slice-level split would put the same patient
in both training and test and quietly inflate every number above. This is the
first thing a reviewer would check.

**The comparison is honest in two ways worth stating.** Every line is scored on
one test set, held out before the sites were formed and patient-disjoint from
all of them. And every line is trained in *rounds*, not epochs — a site-alone
model at round 5 has made exactly as many passes over its own data as a
federated client has, so the chart compares methods rather than training
budgets.

**Three hospitals had to be three machines.** Nomad defaults to `binpack`, and
at 3 cores a node it would have packed two workspaces onto one machine and left
the third idle. The training and the accuracy would have been identical; the
claim would not. `ansible/playbook-scheduler-config.yml` switches the cluster to
`spread`, so each deployment lands on the least-allocated node. One idempotent
setting, no patches.

The alternative — a "which hospital?" dropdown in the deploy form — needs a PAPI
patch *and* an Angular patch, because the dashboard builds its configuration
form from hardcoded fields rather than from PAPI's schema, plus a dashboard
rebuild. Days of work for placement one cluster setting already gives us.
Enforcing site membership properly stays V1 item 3.

**Each site's bundle contains only that site's data.** With no Nextcloud in MVP
(D-15), datasets are copied into the workspace. `scripts/build-fl-bundles.sh`
builds one tarball per site and the isolation is verified, not asserted — Site
A's bundle physically does not contain Site B's slices. That turns a promise
about how we behave into a property of what was delivered.

**What the local rehearsal caught, before any deployment.**
`scripts/fl-rehearse.sh` runs the whole federation over loopback in one minute.
It found the model choices that matter — no batch normalisation, because FedAvg
would average running statistics across sites with very different class mixes
and produce something that looks like federated learning failing when it is a
normalisation artefact — and it settled the Flower version. The deployed server
runs a fork based on 1.16.0, so clients pin `flwr==1.16.0`; a client on a
different major connects, waits, and times out saying nothing useful.

**What only the cluster could prove**, and did: a client inside a workspace can
reach the bundle host, install the pinned Flower, and complete a gRPC TLS
handshake against Traefik using the CAIOS CA. Upstream's own example client
passes `certifi` there, which works only for a publicly-trusted certificate; for
us it fails with a handshake error that never mentions certificates.

Also verified on the way through: the GPU is visible inside a workspace
(`NVIDIA H100L-1-12C`, driver 580.105.08) and JupyterLab serves at its own
subdomain.

**Two bash traps that cost time**, recorded so nobody pays twice. A heredoc
inside a command substitution inside a loop is consumed after the first
iteration — the second site deployed with an empty body and PAPI silently
filled in defaults. And piping JSON into `python3 - <<PY` makes Python read the
heredoc as its own stdin, so the pipe is never seen. Both now use `python3 -c`.

**Cleaned up:** the Stage 3 gate deployment and a GPU test workspace were
deleted to free cores for the four FL workloads, and one orphaned federated
server left behind by the first failed script run. All recreatable in minutes.

---

## 2026-08-12 — Stage 3 follow-up: three browser-only faults

The dashboard opened in a real browser for the first time and failed three
different ways, none of which the programmatic checks had caught. All three are
fixed and the checks now cover them.

**1. Certificate trust is functional, not cosmetic.** Clicking past the warning
grants an exception for that hostname only. The page is served from
`dashboard.<...>` but calls `api.<...>`, and a background fetch cannot prompt —
so the browser blocked it and the page reported an API error. Caddy now serves
the CA at `/caios-ca.pem` on the dashboard host, reachable from the machine that
has the problem. Docs corrected; they had called it optional.

**2. `API_SERVER` must include `/v1`.** `app.config.ts` replaces the API base
with this value wholesale, and the built-in default is
`https://api.cloud.ai4eosc.eu/v1`. Without the suffix every call landed one
level too high and returned 404 — surfacing as *"Error calling the API, please
retry later Error: Not Found"* on every page. A runtime value, so it was a
restart rather than a rebuild.

**4. The Statistics page hung on a null it never checked.** Every request
returned 200, so the fault was entirely client-side: the page does

```js
statsResponse['datacenters'][dc]['footprints']['carbon']
```

with no guard, and our `footprints` was null because the carbon-footprint
lookup is patched out. The exception killed the subscribe callback, so the
spinner ran forever and **nothing was reported** — no error bar, no console
message the user would look for.

Fixed server-side rather than by patching the dashboard: PAPI now always
returns a footprints structure with empty lists, and a zero affinity instead of
null. Empty lists render as em dashes, which is the right display for "we do
not collect this". No dashboard patch, no rebuild.

The check now asserts the *shape* of the statistics payload, not just its
status code — a 200 carrying a null in the wrong place was exactly the failure.

**3. PAPI compares the `Accept` header with strict equality.** It checks
`accept != "application/json"`, but Angular sends
`application/json, text/plain, */*`. So every module and tool metadata request
from the dashboard was answered with 400 "Please specify the profile". Accept is
a list with q-values, not a token; patched to treat anything that will accept
plain JSON as a request for plain JSON.

This one is worth remembering as a class: **testing an API with curl's default
headers hides faults that only appear in a browser.** The check script now sends
the header Angular actually sends.

### Also fixed: the Statistics page no longer errors

`/deployments/stats/user` returned 500 because `ACCOUNTING_PTH` is unset — we
deliberately do not run the accounting service. Upstream raises rather than
degrades, so a feature we chose not to have produced an alarming red bar.

It now returns the same shape `ai4-accounting` itself writes for a namespace
with no recorded usage — a zeroed aggregate and empty series — so the page shows
empty charts instead of an error. That is also the honest answer: there is no
history yet.

### The check script now exercises real page loads

It calls the endpoints the dashboard actually loads, with the browser's Accept
header and a real token, and asserts `apiURL` ends in `/v1`. Every one of these
three faults would now be caught before opening a browser.

---

## 2026-08-12 — STAGE 3 GATE PASSED: the dashboard is live

The full browser login path, proven end to end rather than assumed:

```
  login page renders          <title>Sign in to CAIOS</title>
  credentials submitted       authorization code issued (110 chars)
  code exchanged (PKCE)       access token returned
  token used against PAPI     HTTP 200
  wrong redirect URI          HTTP 400 — correctly rejected
```

That is the real sequence a browser performs: the login form was fetched,
submitted with a real password, the returned code exchanged for a token, and
that token accepted by the API. Everything the dashboard needs is working.

`scripts/check-dashboard.sh` covers the rest: the page serves over a certificate
that validates, the title is ours, and the runtime configuration points at our
API, our realm and our client. It also asserts the third-party analytics beacon
stayed blanked.

### The same lesson, a third time

The Angular build failed with:

```
Schema validation failed: Data path "" must NOT have additional
properties(_comment_styles).
```

Annotated JSON is good for humans and invalid for schema-validating consumers.
This has now come up three times — the Keycloak realm import, `angular.json`,
and the tenant config served to the browser — each time with a different
symptom. The rule that emerged: **keep the notes in the source, strip them at
the boundary.** All three staging paths now do.

The tenant one was the subtlest: those comments explained which upstream URLs we
replaced, so they *mentioned* `cloud.ai4eosc.eu` — and were being published in
the running page's config, where they read like leftover AI4EOSC references.

### Where Stage 3 stands

| | |
|---|---|
| PAPI | Deploys modules with a real token; statistics report the live cluster |
| Dashboard | Serves, branded CAIOS, wired to our API and login server |
| Login | Full authorization-code flow with PKCE, verified end to end |
| A running module | Reachable at its own address over verified HTTPS |

Open it at `https://dashboard.192.168.104.181.sslip.io` and log in as
`researcher`. Import `~/caios-ca.pem` first to avoid the certificate warning.

Next is Stage 4: federated learning across the three sites. The sizing note from
part A matters there — the dev environment's upstream default of 4 CPUs will not
place on a 3-vCPU node, and three GPU-backed clients under one account would hit
the 2-GPU cap. Clients run CPU-only.

---

## 2026-08-12 — Stage 3, part A: PAPI is live and deploying

A module deployed **through the API**, with a real Keycloak token, running on
the cluster and reachable at its own address:

```
POST /v1/deployments/modules            HTTP 200
  api  https://api-<uuid>.pacs-deployments...   HTTP 200  TLS verified
  ui   https://ui-<uuid>.pacs-deployments...    HTTP 200  TLS verified
```

Unauthenticated requests get 401; authenticated ones get 200. The Statistics
endpoint reports all four nodes, 3 GPUs and the `NVIDIA H100L-1-12C` model name
against our own `caios` datacenter.

Part B is the dashboard: the same actions from a browser instead of curl.

### Two node-level problems that were not PAPI's fault

**Image storage was never on the data volume.** Docker 29 uses the containerd
image store, so image layers live under *containerd's* root, not Docker's
`data-root`. Both ai4-ansible and our own control-plane playbook set
`data-root` — which moves almost nothing. Images filled the 20 GB system disk
to 84% while the 125 GB volume sat at 1%, and the next pull failed with "No
space left on device" mid-deployment.

`playbook-container-storage.yml` points containerd's root at the volume on
every node. System disks went from 84% to 31%.

> Also learned: with the containerd snapshotter, Docker's `storage-opt` disk
> limits are **not enforced** — that is an overlay2-on-XFS feature. The XFS
> formatting still matters because `ai4-nomad_tests` asserts it, but
> per-container disk quotas are not actually in effect. Recorded rather than
> fixed; enforcing them means moving the whole daemon back to overlay2.

**I broke the control plane doing it.** That playbook restarts Docker and wipes
the image store on every host it touches, and I ran it against `caios_server`
while the control plane was live. Every container and image there went,
including the locally built PAPI. Recovery was ~15 minutes: prune the stale
build cache, rebuild, `up -d`.

Named volumes survived — they live under Docker's data-root, not containerd's —
so the Keycloak database, realm and users were untouched. Vault lost its
contents, and `vault_init` reapplied its configuration by itself, which is
exactly what it was added for.

The playbook now says all of this at the top, and suggests `--limit
nomad_clients` to leave the control plane alone.

**The registry in Europe is slow enough to fail pulls.** Sidecar images come
from AI4EOSC's registry, and from Canada Docker's HTTP client times out
mid-pull. Because those sidecars are `prestart`/`poststart` tasks, their
failure kills the whole allocation — a deployment that looks like a platform
fault when it is really a slow download. `playbook-prepull-images.yml` warms
all eight images on every node; deployments now start in seconds.

### Five more upstream patches, each blocking something

| Patch | Without it |
|---|---|
| `0003-tryme-vo` | PAPI will not start at all. A hardcoded `vo.ai4eosc.eu` is looked up at import time and raises `KeyError` on any other VO. |
| `0004-stats-without-wattnet` | The Statistics page dies. An unguarded call to an external carbon-footprint API we do not use kills the stats refresh, and `/stats/cluster` starts returning 500 after an hour. |
| `0004` (second half) | Every deployment fails. With footprints skipped, affinity is `None` and the deploy path multiplies it by 0.3. |
| `0002-vault-addr` (extended) | Every deployment fails with a bare 500. Upstream sends an empty Vault role name, which Vault reads as a role literally named `""` rather than "use the default", and answers 403. |
| `0005-skip-mail-sidecar` | Deployments die when an unused mail sidecar cannot pull, and it reserves a whole CPU core — a third of one of our nodes. |

### Sizing: our nodes are small, and it shows

The reference deployment has 64-86 vCPU per node. Ours have 3. Nomad reserves
whole cores, so a 2-CPU request plus the mail sidecar's core plus the UI task's
shared time exceeded a 3-core node, and the job queued forever with "Dimension
cpu exhausted" — refused, not slowed.

With the mail sidecar patched out, 2 CPUs fits. `configs/papi/modules-user.yaml`
and the dev-env config now cap `cpu_num` at 2 with the reasoning inline. The
upstream dev-env default of 4 would never have placed.

---

## 2026-08-12 — STAGE 2 GATE PASSED: identity and secrets

Keycloak and Vault are running, and a real user token passes every check PAPI
will make:

```
=== 1. Keycloak issues a token ===
  [ ok ] required claims (sub, iss, name, email)
  [ ok ] audience includes 'account'
  [ ok ] carries an access:<vo>:<level> role
         issuer: https://auth.192.168.104.181.sslip.io/realms/caios
=== 2. Vault accepts the same token ===
  [ ok ] Vault issued a token
=== 3. Secrets work at the paths PAPI actually uses ===
  [ ok ] wrote a secret        [ ok ] read it back
  [ ok ] another user is denied (HTTP 403)
```

Four demo users exist — one researcher and one per hospital site — each holding
`access:vo.caios.ca:ap-u`, the role name PAPI actually parses.

### The bug that would have cost a day

The realm listed the client's scopes explicitly and **omitted `basic`**. In
Keycloak 26 that scope carries the `sub` protocol mapper, and PAPI requires
`sub` on every token and uses it as the user identity for Vault secret paths.

The resulting tokens looked completely healthy — right issuer, right audience,
name, email, roles all present — and PAPI would have rejected every one of them
with a 401 saying nothing about which claim was missing. It only surfaced
because the check decodes and inspects each required claim by name rather than
asserting "a token came back".

Fixed in the template with a comment explaining why the scope is not optional.

### Three other things worth recording

**Keycloak refuses to import an annotated realm file.** It rejects any field it
does not recognise, so our `_comment` keys failed the whole import with
"Unrecognized field". Rather than strip the documentation, `render-configs.sh`
now removes `_comment*` keys on the way out — the template stays annotated, the
artefact stays valid.

**Keycloak now runs on Postgres, not its built-in file database.** The first
failed import corrupted the H2 store badly enough that Keycloak would not start
at all ("Database is already closed") and its volume had to be deleted.
Identity is the one service whose failure takes the whole demo with it, and a
real database costs one container.

**Vault could not fetch the realm's discovery document.** Its container has no
reason to trust our CA, so the HTTPS fetch failed with a TLS error that reads
like a network problem. Fixed by passing the CA inline through
`oidc_discovery_ca_pem` — nothing has to be mounted.

### Certificates: one authority for everything

Caddy's automatic HTTPS cannot work here — it uses Let's Encrypt, which must
reach the host from the public internet, and every node is behind the VPN. Its
fallback is an internal CA, which would have meant a *second* authority to
distribute.

Instead the control plane now serves a certificate issued from the same CA as
the deployment wildcard. Import `caios-ca.pem` once and the dashboard, the API,
Keycloak, Vault and every deployment are all trusted.

`scripts/check-identity.sh` re-runs the whole verification, and belongs after
any change to the realm, to Vault, or to the addresses — all three have to agree
on the issuer string exactly.

---

## 2026-08-12 — STAGE 1 GATE PASSED

A container scheduled by Nomad, routed by Traefik, reached over HTTPS at its own
subdomain with a **verified** certificate:

```
$ curl https://smoke.pacs-deployments.192.168.104.105.sslip.io
HTTP 200   TLS verify: 0 (0 = certificate verified)

Server address: 172.17.0.3:80
Server name: 9eb2dfd5d032
```

All four nodes report `meta.status=ready`. The cluster can now schedule work.

**The certificate needed rework.** The original wildcard was a bare self-signed
leaf — `CA:FALSE` — which nothing can be configured to trust: not curl, not
Python's `requests`, not a browser's "always trust". That is survivable until
something automated checks HTTPS, and `ai4-nomad_tests` does exactly that,
raising "Invalid SSL certificates". Since that suite is also the only thing that
marks nodes ready, an untrustable certificate blocked the entire cluster.

Replaced with a proper two-tier setup: a local CA (`~/caios-ca.pem`, 10 years)
signing the wildcard. One file to trust, in one place. The CA is installed in the
system trust store for curl, passed to Python tooling via `REQUESTS_CA_BUNDLE`,
and can be imported into a browser once to remove warnings entirely — a
noticeably better demo experience than clicking through a warning screen.

**The gate proved more than it looks.** For that request to return 200, all of
this had to be working: Nomad placed the job against four constraints; Docker
pulled and ran it; Consul registered the service and its Traefik tags; Traefik
read those tags and built a route; sslip.io resolved the wildcard hostname; and
the TLS chain validated. A single 200 covers the whole path.

**One mistake worth recording**, because it will recur: the first attempt
returned 404. The job template builds its hostname as
`<name>.${meta.domain}-<BASE_DOMAIN>`, and `meta.domain` is already `pacs` — so
passing `pacs-deployments...` as the base produced
`smoke.pacs-pacs-deployments...`. The base domain must be
`deployments.<ip>.sslip.io`, matching `lb.domain` in `configs/papi/main.yaml`
exactly. Noted in the job file itself now.

`scripts/run-cluster-tests.sh` captures the full invocation — namespaces, base
domain and CA bundle — so nobody has to reconstruct it.

---

## 2026-08-12 — Stage 1: Consul, Nomad and Traefik are live

**The cluster is up.** Five Consul members, Nomad server leading with region
`global` and datacenter `caios`, four Nomad clients ready, and the Traefik job
already running.

```
Consul   5 members alive          datacenter caios
Nomad    1 server (leader)        region global
         4 clients ready          3 GPU compute + 1 traefik
Jobs     traefik-caios running    docuum running
Namespace  caios                  created
```

GPU nodes check out completely: `NVIDIA H100L-1-12C` detected as a Nomad device,
the `nvidia` Docker runtime present, `/dev/vdb1` mounted, 44.7 GB per core
(the test needs >5), 4096 MB reserved.

**One step left before the Stage 1 gate:** every compute node still reports
`meta.status=test`. That is the value Ansible ships, and only `ai4-nomad_tests`
changes it to `ready` — which every PAPI deployment requires. Next action.

### Four real problems, and what each cost

**1. `import_playbook` silently loaded the wrong variables.** Ansible resolves
`group_vars/` relative to the playbook's own directory. Importing
`vendor/ai4-ansible/playbook-consul.yaml` therefore made *upstream's* IFCA
settings win, and every one of ours was ignored — the first run happily built an
`ifca-imagine` cluster and reported success. Replaced both wrappers with plays
that call the vendored roles directly, and added asserts on `consul_dc_name` and
`nomad_region` so it cannot recur quietly.

**2. `group_vars` still held `<CTRL_IP>` placeholders** from the earlier variable
rename. Consul clients tried to resolve that literal string as a hostname,
joined nothing, and left a one-node cluster that looked perfectly healthy from
the server. Added a placeholder guard to both playbooks.

**3. Re-running after a reset failed nowhere near its cause.** The role guards
ACL bootstrap with a `creates:` file check, so a leftover file made it skip
bootstrapping and reuse a token that no longer existed in the wiped raft store.
Every later ACL call failed, and the visible symptom was a timeout waiting for an
agent token file. `playbook-reset-cluster.yml` now clears those artifacts.

**4. The data volumes were the wrong shape, twice over.** These are OpenStack
*ephemeral* disks: 125 GB at `/dev/vdb`, ext4 written straight to the device with
no partition table, mounted at `/mnt` by cloud-init.

- `parted` reports that as partition table type `loop` with one pseudo-partition,
  so upstream's `when: partitions | length == 0` never fires, no real partition
  is created, and it then runs `mkfs.xfs` on a `/dev/vdb1` that does not exist.
- There is a second bug behind it that bites even on a blank disk: `vol_info` is
  registered *before* partitioning, so the filesystem step is skipped on the same
  run that creates the partition. Upstream presumably works around it by running
  the playbook twice.
- Then `mkfs` failed with "Device or resource busy" while `fuser`, `lsof` and
  `dmsetup` all showed nothing holding the device — and a raw `dd` to it
  succeeded. The cause: **the LXD snap's mount namespace**, created while
  `/dev/vdb` was mounted at `/mnt`, still held a reference. `mkfs` opens with
  `O_EXCL` and fails; `dd` does not and works.

`playbook-prepare-volumes.yml` now lays the disks out correctly in one pass —
drop the cloud-init fstab entry, reboot to clear stale namespace references,
wipe, partition, format XFS, mount at `/mnt/data` with `prjquota`. All three
site nodes are done and the role's own volume tasks are now no-ops.

### GPU drivers: the hazard was real

`grycap.docker` declares `NVIDIA.nvidia_driver` as a **hard role dependency**,
and role dependencies cannot be skipped with tags or variables. The real role
apt-installs a public NVIDIA driver and reboots, with no check for an existing
one.

These nodes run driver **580.105.08 installed via NVIDIA's `.run` installer**, so
`dpkg` knows nothing about it — `dpkg -l | grep -c nvidia` returns 0. apt would
have installed the older public 550 driver over a working vGPU stack and
rebooted all three GPU nodes.

Our stub at `ansible/roles/NVIDIA.nvidia_driver/` verifies instead of installing,
and `ansible.cfg` puts our roles first so it shadows the Galaxy one. The
container toolkit still installs normally — confirmed by the `nvidia` runtime
being present and the GPU showing up as a Nomad device.

### Also fixed

`scripts/verify-cluster.sh` had two bugs of its own. It piped JSON into
`python3 -` while also feeding the program in via heredoc, so the program read an
empty stdin; and `nomad node status -json` in list form returns no `Meta` field
at all, so metadata needs a per-node query. Both fixed — it now correctly reports
all four constraint fields and flags the `meta.status=test` issue by name.

---

## 2026-08-12 — Stage 1 unblocked: SSH working, all volumes confirmed empty

**SSH access is done.** The cluster key now reaches all four nodes.
`scripts/check-ssh.sh` passes using that key alone, with agent forwarding and
password authentication disabled — so Ansible will work unattended, not only
while someone is logged in.

**The disk question is settled, and the answer is the easy one.** Every node has
the same layout: a 20 GB root disk plus a 125 GB volume at `/dev/vdb`, ext4,
mounted at `/mnt`. On all four, `/mnt` contains only `lost+found` — the directory
`mkfs` creates on every ext4 filesystem, meaning nothing has ever been written
there.

So the reformat that `playbook-nomad.yml` performs on the three site nodes
destroys nothing. **No action needed, and nothing to preserve.**

Improved `check-ssh.sh` to recognise `lost+found` as empty. It was previously
reporting a bare volume as "contains files", which is a warning that trains you
to ignore warnings.

**Nothing has been installed yet, and nothing has been damaged.** The hazard
noted in the previous entry is a property of a playbook we have not run — it
matters when we run it, not before.

**Ansible is not yet installed** on `caios_server`. That is the next step, along
with the cluster playbooks themselves.

**`docs/concepts.md` substantially expanded** — from three tools to sixteen,
grouped into cluster / installation / platform / identity / AI, with a contents
list. Ansible gets the fullest treatment, including the idea that makes it click
(describe the end state, not the steps), what our four file types each do, how to
read its output, and the one sharp edge: it reformats disks without asking.

---

## 2026-08-12 — Stage 0: SSH, disks, and a correction

**Correction: the second volume was already there.** An earlier note said
`caios_server` had no data volume. That was wrong — it came from truncated
command output. Every instance has a **125 GB volume at `/dev/vdb`, formatted
ext4, mounted at `/mnt`**. That is why this repository lives at `/mnt/CAIOS`.

This changes the disk plan and surfaces a hazard:

- **`caios_server` keeps `/mnt` as ext4, untouched.** Nothing on the control
  plane needs per-container disk quotas. `playbook-control-plane.yml` simply
  points Docker's storage at `/mnt/docker`, which matters because the root disk
  has only ~12 GB free and the control-plane images will not fit there.
- **The three site nodes get `/mnt` repartitioned and reformatted as XFS**, at
  `/mnt/data`. This is required — Docker's `storage-opt` disk limits only work
  on XFS, and the cluster test asserts the device path `/dev/vdb1` literally.
- **That step erases `/mnt` on those nodes.** `caios_server` is deliberately
  absent from the `nomad_volume` inventory group, with a warning at the group
  saying why. One typo there would delete this repository.

**SSH.** `caios_server` had no private key at all — only `authorized_keys` — so
it could accept connections but never make one. Generated a dedicated cluster
keypair here (`~/.ssh/caios_cluster`) rather than copying a personal key onto a
shared node: it is scoped to this cluster and revocable by deleting four lines.

Installing its public half is the one step that cannot be automated from here,
because it needs a credential only on your laptop. `docs/ssh-setup.md` covers
both routes; `scripts/check-ssh.sh` verifies the result using the cluster key
alone, with agent forwarding and passwords disabled, so a pass means Ansible
will work unattended.

Ran it: all four nodes answer at the network level and reject the key, which is
exactly the expected state. Network connectivity is confirmed; only
authorisation is missing.

**Repository made private-safe.** Rewrote git history to purge the four internal
documents from all thirteen commits, and force-pushed. Verified zero occurrences
across every remaining ref; the files are still on disk. Full backup taken first
at `/home/ubuntu/caios-backup-20260812-0416.bundle`. Hardened `.gitignore` with
catch-all rules for credentials, OpenStack RC files, private keys, Terraform
state and internal notes, so the next sensitive file is ignored by default
rather than by memory.

---

## 2026-08-12 — Stage 0: adapted to the real network, and the last of the scaffold

**Network reality corrected.** The earlier design assumed two public floating
IPs. There are none — every node is private on `192.168.104.0/24`, reached
through OpenVPN and a jumpserver. Reworked accordingly:

- Renamed `CAIOS_FIP1`/`FIP2` to `CAIOS_CTRL_IP`/`CAIOS_EDGE_IP`, since
  "floating IP" now describes something that does not exist.
- Ansible runs *from* `caios_server`, reaching the others directly across the
  subnet. No bastion hop in the automation.
- **Verified `sslip.io` resolves private addresses** from the node:
  `dashboard.192.168.104.181.sslip.io → 192.168.104.181`. The hostname scheme
  therefore needs no change and still requires no DNS setup.

**Node roles assigned** to the real addresses:

| Node | Address | Role |
|---|---|---|
| `caios_server` | 192.168.104.181 | Cluster servers + web services. We work here. |
| `caios_edge` | 192.168.104.105 | Traefik. Every deployment address points here. |
| `caios_site_a` | 192.168.104.20 | GPU compute — "Hospital A" |
| `caios_site_b` | 192.168.104.145 | GPU compute — "Hospital B" |
| `caios_site_c` | 192.168.104.7 | GPU compute — "Hospital C" |
| *unassigned* | 192.168.104.188 | Sixth instance, deliberately left out until identified |

**Measured on `caios_server`:** 3 vCPU, 34 GB RAM, 20 GB root disk, one
`NVIDIA H100L-1-12C` (12 GB slice), Ubuntu 22.04.5. No node can host CVAT, which
needs ~72 GB of RAM in one place.

> *Corrected the same day:* this entry originally said no second volume was
> attached. There is one — 125 GB at `/dev/vdb`, mounted at `/mnt`. See the
> entry above.

**`configs/env/caios.env` created** with the real addresses and freshly generated
secrets, mode `600`, confirmed gitignored. Rendering verified end to end.

**New documents:** `docs/concepts.md` (Nomad, Consul and Traefik explained from
zero), `docs/scope.md` (what is MVP, what is V1, what is excluded and why), and
this file.

**Internal documents removed from the public repository** — the working notes,
supervisor questions and original phase plan. They remain on disk.

**Consequence worth flagging:** with no public IP, nothing is reachable outside
the VPN. That rules out a live demo to external reviewers unless a floating IP is
requested, or reviewers get VPN access. Recording was already the plan, so this
costs nothing — but a floating IP has a lead time and is worth requesting now.

---

## 2026-08-12 — Stage 0: catalogue and operations

**Catalogue counted properly, and the neuroscience gap closed.** Against both the
repository and the live API: 46 models, **2 medical**, **0 neuroscience** — not
the 4 medical previously recorded.

The fix turned out to be better than expected. The platform's bioimage.io loader
supports three **connectomics** models — neuron segmentation in electron
microscopy — plus mitochondria segmentation. Real neuroscience, no code. That
downgrades "build a custom neuroscience module" from necessary (1.5-2 days) to an
optional stretch item.

Curation plan is mostly subtraction: remove ~31 marine, agricultural and remote
sensing models, leaving ~15 that are all plausibly relevant.

**Runbook written**, organised by symptom rather than by component — the failures
in this stack are mostly silent, so "a dashboard that renders with every button
dead" is a more useful heading than "PAPI".

---

## 2026-08-12 — Stage 0: control plane, patches and tooling

**Compose stack** for `caios_server`: Caddy, Keycloak, Vault, PAPI, dashboard.

Three problems found by reading PAPI's own Dockerfile, each of which would have
cost time on the node:

1. **It sets `IS_PROD=True`.** The received wisdom — "leave `IS_PROD` unset" — is
   therefore wrong for the official image: unset inherits `True` and PAPI refuses
   to start over missing tokens for services we do not run. Now set to `false`
   explicitly.
2. **It binds `0.0.0.0:80`**, which collides with Caddy and would expose PAPI
   directly. Rebound to loopback.
3. **It regenerates its own config file at every start**, so a config mounted at
   the obvious path is silently overwritten a second later. Mounted at the file
   it actually reads instead.

**Four upstream patches**, all verified to apply and parse:

| Patch | Why it cannot be configuration |
|---|---|
| PAPI Keycloak URL | Hardcoded in Python. Without it, every login is rejected. |
| PAPI Vault address | Hardcoded. Deploying the FL server calls Vault *before* Nomad, so the headline demo fails with an error mentioning neither. |
| Cluster test namespaces | Hardcoded to AI4EOSC's. Also fixed two assertions that were no-ops, so a misconfigured node now fails instead of being marked ready. |
| Dashboard | **Not patched** — the value that looked hardcoded turns out to be overridable at runtime. |

**Scripts**, all syntax-checked, several tested against synthetic data:
vendor pinning, patch application, config rendering, certificate generation,
cluster verification, security groups (prints by default, creates only with
`--apply`), Keycloak users, token inspection.

`verify-cluster.sh` earns its place: it checks the four conditions that decide
whether anything can be scheduled, and was tested to correctly catch the exact
silent failure that would otherwise cost a day.

---

## 2026-08-12 — Stage 0: branding and configuration

**CAIOS dashboard tenant** added alongside upstream's five. Theme recoloured to a
clinical teal, deliberately distinct from AI4EOSC's cyan-on-navy so it does not
read as a reskin. Verified the build target resolves and the tenant config
produces no `cloud.ai4eosc.eu` URLs.

Two leaks closed that the original notes had not caught: the footer links, and an
**analytics beacon** that would have reported our demo traffic to a third-party
tracker.

**PAPI configured** for a single VO, deployment addresses derived from the
Traefik node, OSCAR removed, MLflow blanked rather than left pointing at
AI4EOSC's. Added our datacenter to the map file — without it the Statistics page
places the cluster at latitude 0, longitude 0.

**Federated server defaults changed** to fit the demo: expose the image that
issues per-client credentials (upstream hides it), default to the mode where
training rounds are *visible* rather than hidden, and require three clients.

---

## 2026-08-12 — Stage 0: verification and planning

Read all six upstream repositories at HEAD rather than trusting notes, and found
several things that would each have cost a day or more:

- **The federated learning server needs Vault**, at an address hardcoded in
  Python. This is on the critical path of the headline feature and was in nobody's
  plan.
- **The cluster test suite is not optional.** It is the only thing that marks
  nodes as ready for work, and without it every deployment queues forever on a
  cluster that reports itself perfectly healthy.
- **Three Nomad datacenters are not achievable** with the upstream automation —
  it writes one datacenter name into every node. Sites become node-level instead,
  which turns out to be the better design anyway.
- **Platform storage is Nextcloud over WebDAV, not S3.** The plan to run MinIO
  would not have worked.
- **CVAT needs ~71 GB of RAM on a single machine.**
- **One user may hold at most 2 GPUs**, so three GPU-backed federated clients
  would be rejected on the third.

Recorded as decisions D-10 to D-18; three earlier decisions superseded or revised.

**Node layout redesigned** to put the web services on the same node as the
cluster servers. PAPI then reaches Nomad over loopback using certificates that
are already there — removing a class of debugging, and freeing a node so we get
**three** hospital sites out of five machines instead of two.

**Delivery split into MVP and V1** so there is something demonstrable in about
eight days rather than three weeks.
