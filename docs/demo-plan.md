# Demo plan — three tiers, then record

**The working plan from 2026-09-24.** Priorities changed that day: finish the
code and record the demo *before* the real certificate. Stages C2 and C3 of
`docs/certificate-plan.md` wait, which costs little because they were blocked
on the supervisor's domain anyway. This supersedes T8 of
`docs/finalization-plan.md` as the plan for the recording.

The recording happens under the CAIOS CA, so the browser that records it must
have `caios-ca.pem` imported. No certificate dialog on camera.

---

## The demo: three tiers of control

| Tier | What the viewer sees | Built on | State on 2026-09-24 |
|---|---|---|---|
| **No code** | Deploy a private language model from the marketplace and chat with it | the `ai4os-llm` tool: vLLM + Open WebUI | works |
| **Low code** | A catalogue model deployed as a serverless service: an image in, detections out | OSCAR on `192.168.104.69` | worked 2026-08-26; step 4 re-walks it |
| **High code** | JupyterLab: the researcher writes the code | a module in Jupyter mode (A) or the dev-env tool (B) | **the problem tier**; step 3 |

All three start from the marketplace, which is the point: one catalogue, three
depths.

---

## What the investigation found

Measured 2026-09-24, read-only, before anything was changed.

### 1. Module deployments fail on a download from Europe

The object-detection deployment titled "high code" (`cc63b18d`, platform-admin)
died on `caios-wn-gpu-0`, and the module was never the problem:

```
17:45:58  main  Downloading image   ai4oshub/obj-detection-torch:latest   (78 s)
17:47:16  main  Started             deep-start --deepaas
17:47:49  ui    Driver Failure      Failed to pull
                registry.cloud.ai4eosc.eu/ai4os/deepaas_ui:latest:
                net/http: timeout awaiting response headers
17:47:49  main  Sibling Task Failed -> killed, exit 137
17:47:59        Alloc Unhealthy     job dead
```

`ui` is DEEPaaS's Gradio page, a `poststart` sidecar pulled from **AI4EOSC's
registry in Europe**, with `restart { attempts = 0, mode = "fail" }` — so one
slow pull takes the whole allocation down with it. An hour later the
registry's `/v2/` endpoint answered in 0.86 s, which first read as a transient
fault. It was not: step 1 found its manifest endpoint — the exact call in the
error — hanging for every image tried, for the rest of the afternoon. A
registry that answers its health check and stalls on the one request that
matters is the same shape as the GitHub outage of 2026-09-01.

**Every module deployment carries this risk, not only this module.**
`playbook-prepull-images.yml` already pre-pulls `deepaas_ui` and quotes this
exact error in its header, but it never protected a module deployment, for two
reasons that stack:

1. Upstream's module template sets `force_pull = true` on `ui` (and on `main`).
2. **Nomad pulls a `:latest` tag every time regardless of `force_pull`.**
   Verified in the v1.11.3 source, `drivers/docker/driver.go`
   `createImage()`: the local-image check runs only
   `if !ForcePull && tag != "latest"`. So turning `force_pull` off is not
   enough on its own — the image must be referenced by a pinned tag or digest.
   For a digest, `parseDockerImage()` sets the tag to `""`, the local check
   runs, and a cached image is used with no network call at all.

The LLM template never had this problem because it pins every tag
(`v0.27.1`, `v0.11.0`, `3.12-slim-bullseye`) *and* sets `force_pull = false`.

### 2. `obj-detection-torch` cannot use this cluster's GPU

Its image is built on `pytorch/pytorch:1.4-cuda10.1-cudnn7-runtime`. MIG needs
CUDA 11 or later, so on these MIG-backed slices it is CPU-only whatever the form
says. `ai4os-yolo-torch` (PyTorch 1.13, CUDA 11.6, image rebuilt 2026-01-19) is
the better high-code vehicle, and it is the model the OSCAR tier already runs.
Whether PyTorch 1.13 actually computes on an H100 MIG slice is untested
(gotcha 13) — step 3 measures it.

### 3. The recorded reason JupyterLab is off for modules does not hold up

`configs/papi/modules-user.yaml` says every module's `deep-start` launches
JupyterLab as root without `--allow-root`. But `deep-start`'s own
`jupyter_notebook_config.py` (and its `jupyter_server_config.py` symlink) has set
`allow_root = True` since 2023-06, and `deep-start` points `JUPYTER_CONFIG_DIR`
at it. Jupyter only prints "Use --allow-root to bypass" when that file **fails
to load** — for example on its `from pkg_resources import ...` line. Only
`posenet-tf` was ever actually run. The fix is plausibly a mounted config, not
impossible.

It matters twice over, because in Jupyter mode PAPI removes the `ui` task
(`modules.py`: `if service != "deepaas": exclude_tasks.append("ui")`): no
download from Europe and no AI4EOSC-branded Gradio page.

### 4. The cluster layout had drifted

Three LLMs held three of the four compute nodes. The federated demo could not
have run:

| Deployment | Owner | Node | |
|---|---|---|---|
| test meeting | researcher | gpu-3, the dedicated LLM node | 28 days old |
| test8000 | researcher | gpu-1, hospital B | 18 days old |
| demo no code | platform-admin | gpu-2, hospital C | landed on a hospital because gpu-3 was taken |

Only gpu-0 had a free core, which is where the module went. **Fixed in step 0.**

### 5. OSCAR is healthy, and private

`/health` answers 200; three services exist from 2026-08-26, all owned by
`researcher`. Its hostnames — `oscar.`, `minio.`, `minio-console.` on
`192.168.104.69.sslip.io` — are not routed through the public proxy, so the
machine that records the low-code tier must be on the VPN.
`docs/oscar-gui-guide.md` contradicts itself: step 5 says to ignore the
synchronous endpoint, Route A recommends it.

### 6. Upstream names and logos a viewer can still read

All from module or tool metadata, served by PAPI from `catalog/mirror/`:

- `vo.imagine-ai.eu` as a tag on five modules — another project's VO
- "AI4 trainable", "AI4 pre trained", "AI4 inference" on all eight modules
- tool titles "AI4OS Development Environment" and "AI4life model loader"
- the Gradio page's footer: an AI4EOSC logo, fetched from
  `raw.githubusercontent.com` by the viewer's browser and linking to
  `ai4eosc.eu` (`ui_utils.py` falls back to AI4EOSC for any namespace but
  `imagine`)
- the dev-env's welcome page (R3), and its defaults — VS Code on a bare
  `u24.04` image — so a viewer taking the defaults gets neither JupyterLab nor
  PyTorch

---

## The five-minute cut

**The recording is about five minutes.** That is the constraint everything
below now answers to. At a speaking pace that is 600 to 700 words, so nothing
waits on camera: each beat is recorded as its own clip, everything slow is
deployed and warmed beforehand, and every load is a cut.

Proposed 2026-09-24, **to be confirmed**:

| Time | Beat | On screen | How the waiting disappears |
|---|---|---|---|
| 0:00–0:20 | What CAIOS is | the home page: Canadian, private, for medical and neuroscience research; three depths of control | — |
| 0:20–0:50 | A new researcher gets in | Keycloak's sign-up form → the waiting room → an administrator approves at `/admin` → the marketplace | two browser windows, cut between them |
| 0:50–1:50 | **No code**: a private language model | LLMs → a model's card → the deploy form → the running deployment → a clinical note summarised in the chat window | deployed before recording; the 1–3 min load is a cut |
| 1:50–2:40 | **Low code**: serverless inference | YOLO → *Deploy* ▾ → *Inference API (serverless)* → the Inference list → one request → detections | service created and warmed beforehand |
| 2:40–4:00 | **High code**: the notebook | YOLO → *Deploy* ▾ dedicated, JupyterLab → a notebook of four or five short cells: detections drawn on an image, then the same model's serverless endpoint and the private LLM called from the same notebook. **CPU** — see step 3's spike; the GPU is the LLM beat's to show | workspace deployed and notebook staged beforehand |
| 4:00–4:40 | Federated learning *(decided later)* | three hospital workspaces training, rounds at 2×, then the chart: 0.853 against 0.806 and 0.865 | pre-bootstrapped |
| 4:40–5:00 | Close | Statistics: live usage on Compute Canada; one roadmap line | — |

If federated learning is cut, its 40 seconds go to the notebook.

What it changes about the steps:

- **Step 3 is now the critical path**, and it is YOLO. It goes next.
- **Step 4's result has to be clean on camera.** See its first measurement
  below: today the synchronous answer is the job's log with the detections
  buried in it.
- **Step 5 narrows to the screens above.** The Gradio page is not among them.
  The Keycloak sign-up form and the YOLO module page are, and the second
  carries `vo.imagine-ai.eu` and "AI4 …" chips today.
- **Step 2 still runs**, because test users can click any module, but after
  step 3: its Jupyter column only exists if step 3 finds JupyterLab works on
  modules.
- The sign-up beat is a new account, and the rest is recorded as `researcher`
  (Dana Okafor). The name in the dashboard header changes between beat two and
  beat three; a cut hides it, or the new account records everything and every
  deployment is created during the session. Decide at step 6.

## Steps

| # | Step | Gate | State |
|---|---|---|---|
| 0 | Clean slate | the stale deployments gone, gpu-1 and gpu-3 free | **done 2026-09-24** |
| 1 | Module deploys stop depending on Europe | `obj-detection-torch` deploys with no pull of `ui`, predicts, UI loads | **done 2026-09-24** |
| 2 | Every marketplace module tested | `scripts/check-modules.sh` green for all eight, or the failures removed — DEEPaaS **and** Jupyter mode | **next** |
| 3 | High code | a notebook that runs from a marketplace deployment | spike done 2026-09-24; notebook after 2 |
| 4 | Low code re-walked | the GUI guide followed literally, timings re-measured, guide fixed | services tested 2026-09-24 |
| 5 | Names and logos | `check-branding.sh` asserts the list in finding 6 on the served API | |
| 6 | The script | `docs/demo-script.md` rewritten around the three tiers, timed | |
| 7 | Rehearse, then record | two timed read-throughs, the second with no correction | |

Order, revised for the five-minute cut and then by step 3's spike: 0, 1, the
step-3 spike, **2**, the rest of 3, 4, 5, 6, 7. Step 2 moved up because the
high-code beat needs JupyterLab offered on modules again, and that should not
be switched back on for all eight without testing all eight. About four
working days. Commit and push after each step.

### Step 1 — Module deploys stop depending on Europe · done

- PAPI patch `0020`: the `ui` image referenced **by digest** with
  `force_pull = false`, so a cached copy is used with no network call. `main`
  gets `force_pull = false` too, which helps any pinned tag; for the default
  `latest` Nomad still checks Docker Hub, which is fast when the layers are
  cached and has been reliable throughout.
- `playbook-prepull-images.yml` pulls the same digest and skips it when
  present; `tests/test_module_template.py` keeps the two equal. It now targets
  the compute nodes only, and no longer pulls three images nothing here runs.
- **YOLO was not added.** The measurement said the list itself is the problem
  — see step 6.
- Gate: passed. See the step log.

### Step 2 — Every marketplace module tested

Two columns per module, not one: DEEPaaS mode as below, and **Jupyter mode**
(JupyterLab answers `/login`, the deployment password logs in), because the
high-code beat needs `jupyter` offered on modules again and the one image that
failed on 2026-09-02 was `posenet-tf`. Plus one policy question the spike
raised: every module image predates the H100 (finding 2, step 3's spike), so
should the deploy form still offer modules a GPU at all?

`scripts/check-modules.sh`, shaped like `check-llm-catalogue.sh`. For each module
in `catalog/keep.txt`: deploy (DEEPaaS, CPU), wait for `running`, `GET
/v2/models/`, one `predict` with a fixture of the right data type, the UI
answers, delete. A module that fails is fixed or removed from `keep.txt` (one
line, a mirror refresh, and the home-page counts test). GPU tested only for the
module the demo uses, with a matrix multiplication (gotcha 13).

### Step 3 — High code

**Spike done 2026-09-24 — see the step log.** JupyterLab works in the YOLO
module as it stands; the GPU does not, in any useful sense; YOLO on CPU is
fast. So the tier is **A on CPU**: Marketplace → YOLO → *Deploy* → JupyterLab,
no GPU. What remains: offer `jupyter` for modules again once step 2 has tested
Jupyter mode on all eight; write the notebook; rename the *"Inference API + UI
(dedicated)"* menu item, which is wrong for a notebook (step 5).

The spike, as planned: a one-off Nomad job, outside PAPI so nothing user-visible
changes, running `ai4os-yolo-torch` with `deep-start --jupyter` and a GPU. It
answers three questions: does JupyterLab come up, how long does it take (it
installs JupyterLab from PyPI at every start), and does the GPU compute.

- **A — it works:** JupyterLab comes back as a deploy option for the modules
  that pass step 2. The tier is Marketplace → YOLO → Deploy → JupyterLab.
- **B — it does not:** the dev-env tool on `pytorch2.6` with JupyterLab,
  proven on 2026-09-02, defaulted to JupyterLab.

Either way, one prepared notebook, delivered the way the FL bundles are: detect
objects on the GPU, draw the boxes, call the same model's serverless endpoint,
and ask the private LLM to summarise the detections. All three tiers in one
place.

### Step 4 — Low code re-walked

As the recording account, in a clean browser, follow `docs/oscar-gui-guide.md`
literally: create the YOLO service from the marketplace, find it on the
Inference page, send an image to the synchronous endpoint with `curl`, upload
one through the MinIO console, delete the service. Re-measure cold and warm,
fix the guide. The MinIO secret key is rendered in the page: never on camera.

**First measurement, 2026-09-24: all three services answer, and two things
would look wrong on camera.** One real photograph to each of the three
`researcher` services from 2026-08-26, both routes, TLS verified against the
CAIOS CA:

| Service | Synchronous (`/run/…`) | Through the bucket |
|---|---|---|
| YOLO, "CAIOS object detection" | 200 in 13.0 s cold, 5.2 s warm | result in 9.1 s: clean JSON, person 0.909, tie 0.611 |
| image classification, 8 GB | 200 in 15.4 s | ran, **result lost** — only a log |
| image classification, 4 GB | 200 in 16.7 s, 12.4 s again | ran, **result lost** — only a log |

1. **The synchronous answer is the job's log, not the result.** PAPI's service
   script (`etc/oscar/service.yaml`) returns `cat service.log` for a
   synchronous call. The detections are in it, as one Python-repr line
   (`return: [[{'name': 'person', …}]]`) — line 14 of 16 for YOLO, line 221 of
   about 230 for the classifier, under forty kilobytes of TensorFlow warnings.
   Correct, and unusable on screen.
2. **The classifier's bucket result is thrown away.** DEEPaaS 2.6.0 colours its
   log, so the line naming the result file ends in an ANSI escape
   (`…tmp-file-mwkea.json^[[00m`). The script `cut`s that filename, escape
   included, and the `mv` that saves it finds no such file. YOLO ships DEEPaaS
   2.5.2, which does not colour its log, which is the only reason it works.

Both are one PAPI patch to `etc/oscar/service.yaml`: strip escapes before
parsing, and answer a synchronous call with the result rather than the log.
It reaches **new** services only; the three existing ones keep the script they
were created with.

Not a CAIOS fault but worth knowing: `curl --aws-sigv4` (7.81 here) cannot
upload to this MinIO — it predates the `x-amz-content-sha256` header MinIO
requires and gets 403 `SignatureDoesNotMatch`. The browser console and any S3
SDK are fine.

### Step 5 — Names and logos

Clean the metadata when the mirror is built (`scripts/mirror-catalogue.sh`):
no `vo.*` tags, "Trainable / Pre-trained / Inference", "Development
Environment". No dashboard rebuild; PAPI serves it. `check-branding.sh` asserts
it. Optionally a locally built `caios/deepaas_ui` with a CAIOS footer, loaded
onto the nodes and never pulled from anywhere — worth it only if the Gradio page
appears on camera or test users will click it.

### Step 6 — The script

**First, the pre-pull list, split by node role.** Measured 2026-09-24 in step 1:
the list sends every image to every GPU node, including 38 GB of LLM images
(`vllm` 30.8, `open-webui` 7.1) that only `caios_llm` runs in the demo, and
docuum has already evicted different parts of it on different nodes. Images on
disk: `caios_site_a` 53 GB, `caios_llm` 71, `caios_site_b` and `caios_site_c`
77, against docuum's 80. Running the playbook across every node today would
pull the LLM images back onto site_a and push three nodes past the threshold,
and docuum would evict whatever was least recently used — possibly `tf2.14.0`,
which the federated workspaces deploy and which **is not on the list at all**
(the list has `pytorch2.1`, which nothing in the demo deploys). The split:
the `ui` digest everywhere; the LLM images on `caios_llm`; on the hospitals
the federated images plus whatever step 3 chose (YOLO is about 15 GB on disk,
and fits only on site_a today). `docs/demo-script.md` currently tells you to
run the playbook before the demo — fix that line in the same change.

Then rewrite `docs/demo-script.md` around the three tiers, opening on the home page.
A before-you-start list: pre-pull, the LLM deployed first so it lands on gpu-3,
one warm-up request to OSCAR, the high-code workspace deployed and its notebook
staged. A fallback clip for each tier.

### Step 7 — Rehearse, then record

Two timed read-throughs, then one take per tier. Clean browser profile with the
CA imported. Never on camera: the MinIO secret key, the vLLM API key, Vault
tokens, passwords.

---

## Decisions

Answered 2026-09-24:

1. **Federated learning: decided later.** In if it fits as high code, and it
   probably does. It keeps a provisional 40 seconds in the cut.
2. **High code is YOLO.** `ai4os-yolo-torch`, in Jupyter mode if step 3's spike
   finds that works, else the dev-env fallback (B).
3. **The OSCAR services stay**, and were tested with real requests instead —
   see step 4.
4. **`researcher` records.** A new account is created on camera, to show
   sign-up and approval.

Still open: the storyboard above.

---

## Step log

### Step 0 — clean slate · done 2026-09-24

Deleted through PAPI as each owner, so the LLMs' Vault secrets went with them —
which `nomad job stop` would not have done:

```
DELETE /v1/deployments/tools/dd502c71-a17c-11f1-93e4-fdb0b70ec6e8    test meeting  researcher      200
DELETE /v1/deployments/tools/6f4f340e-a99f-11f1-a265-6506f4f80430    test8000      researcher      200
DELETE /v1/deployments/modules/cc63b18d-b83f-11f1-8656-079b7921fda4  high code     platform-admin  200
```

The two running LLMs were stopped (PAPI purges only jobs that are not running,
so they read `dead (stopped)` until Nomad's garbage collection); the failed
module was purged. After:

| Node | Running |
|---|---|
| gpu-0 (hospital A) | docuum |
| gpu-1 (hospital B) | docuum |
| gpu-2 (hospital C) | docuum, **demo no code** |
| gpu-3 (LLM node) | docuum |

`demo no code` stays until recording day and is then redeployed **first**, so it
lands on gpu-3 and the three hospital nodes stay free for the federation. The
OSCAR services are untouched (decision 3).

### Step 1 — module deploys stop depending on Europe · done 2026-09-24

**AI4EOSC's registry was stalling throughout**, which made the gate a real
test rather than a formality. Its `/v2/` and token endpoints answered in under
a second; the manifest request — the exact call in the failed deployment's
error — hung for the full 45 s on every image tried, HEAD and GET alike. So the
digest could not be read from Europe. It was read from the nodes instead: all
four GPU nodes held the same `sha256:31f35b28…`, built 2025-05-06, which is
also the date of the Gradio UI repository's last commit. `latest` has not moved
in over a year, so pinning it changes nothing about what runs.

Patch `0020` built into PAPI and deployed; the old image is
`rollback/papi-pre-0020.tar`, git tag `papi-pre-0020`. Then the gate, as
platform-admin, with the dashboard's own defaults:

```
T+1s   queued
T+6s   running                      caios-wn-gpu-0, the node that failed at 17:47

task ui    Received -> Task Setup -> Started     no "Downloading image": taken from the node
task main  Received -> Task Setup -> Downloading image -> Started   (latest, 1 s: Docker Hub)

GET  /v2/models/                     200   obj_detect_pytorch
POST /v2/models/obj_detect_pytorch/predict/   grace_hopper.jpg, CPU, 1 core
     200 in 5.5 s   person 0.999, tie 0.953, with boxes
GET  ui-<uuid>                       200   the Gradio page
```

TLS verified against the CAIOS CA the whole way, through the public proxy.
Deleted afterwards. The same module, on the same node, on the same afternoon:
two minutes and dead before, running in six seconds after.

The playbook was run on `caios_llm` only, which already held every listed
image: 8 of 8, nothing changed, and the pinned image skipped without a request
to the stalled registry. It was deliberately **not** run across the cluster —
see step 6.

**Observed, not touched:** on `caios_edge`, `docker system df` fails with
*rw layer snapshot not found for container 17aa0177f60d…*. Traefik is serving
normally. Worth a look before the cold-start run (T7), not before.

### Step 3 spike — YOLO in Jupyter mode · 2026-09-24

A one-off Nomad job outside PAPI, mirroring the module template's `main` task in
Jupyter mode — `ai4oshub/ai4os-yolo-torch:latest`, `deep-start --jupyter`, one
core, 8 GB, one GPU — pinned to `caios-wn-gpu-0`, the only node with disk room
for the image. Purged afterwards.

**JupyterLab works, first time, with no change.** `deep-start` installed
JupyterLab from PyPI in about 9 s, loaded its own config from
`/srv/.deep-start`, and served `/srv` on `0.0.0.0:8888`:

```
GET  /login                          200   Jupyter Server
POST /login  (the deployment password)  302 -> /lab
GET  /api/contents/  logged in       200   ai4os-yolo-torch, ai4os-yolov8-torch
GET  /api/contents/  not logged in   403
```

So the reason recorded on 2026-09-02 for switching Jupyter off on every module
("runs as root without `--allow-root`") does not hold for this image — its
config sets `allow_root = True` and loads. Whether it holds for any of the
other seven is step 2's Jupyter column.

**The GPU is not usable.** PyTorch 1.13.1 is built for CUDA 11.6, which
predates Hopper, so it carries no kernels for compute capability 9.0 and the
driver JIT-compiles them from PTX at the first CUDA call. That call was still
compiling after **25 minutes** at 99% of the job's one core, with the JIT
cache at exactly **1024 MB** — the driver's default ceiling, beyond which it
evicts and recompiles. Stopped there. A test user who ticks *one GPU* for this
module would see a notebook that hangs on its first GPU line for half an hour.

**On CPU, YOLO is fast**, on that same single core:

```
ultralytics 8.4.3                       import 1.0 s, yolov8n.pt 0.4 s (from GitHub)
bus.jpg     bus, 4 people, stop sign    0.27 s, then 0.12 s
zidane.jpg  2 people, tie               0.11 s, then 0.10 s
```

Two runtime dependencies this surfaced, both to keep in mind for demo day
rather than to fix: Jupyter mode installs JupyterLab **from PyPI at every
start**, and YOLO's weights come **from GitHub** at first use — in the
notebook, and in every cold OSCAR job too. Deploy and warm before recording.

The notebook the module ships, `notebooks/1.0-yolov8_api_start.ipynb`, is a
four-cell stub (it prints the hostname). The demo needs its own.
