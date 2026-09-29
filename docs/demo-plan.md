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
| 4:00–4:40 | Federated learning *(kept, 2026-09-29)* | three hospital workspaces training, rounds at 2×, then the chart: 0.853 against 0.806 and 0.865 | pre-bootstrapped |
| 4:40–5:00 | Close | Statistics: live usage on Compute Canada; one roadmap line | — |

If federated learning is cut, its 40 seconds go to the notebook.

What it changes about the steps:

- **Step 3 is now the critical path**, and it is YOLO. It goes next.
- **Step 4's result has to be clean on camera.** See its first measurement
  below: today the synchronous answer is the job's log with the detections
  buried in it.
- **Step 5 narrows to the screens above.** The Gradio page is not among them.
  The Keycloak sign-up form and the YOLO module page are, and the second
  carried `vo.imagine-ai.eu` and "AI4 …" chips until step 5 removed them.
- **Step 2 still runs**, because test users can click any module, but after
  step 3: its Jupyter column only exists if step 3 finds JupyterLab works on
  modules.
- The sign-up beat is a new account, and the rest is recorded as `researcher`
  (Dana Okafor). The name in the dashboard header changes between beat two and
  beat three; a cut hides it, or the new account records everything and every
  deployment is created during the session. **Decided at step 6: the cut hides
  it (D-85).**

## Steps

| # | Step | Gate | State |
|---|---|---|---|
| 0 | Clean slate | the stale deployments gone, gpu-1 and gpu-3 free | **done 2026-09-24** |
| 1 | Module deploys stop depending on Europe | `obj-detection-torch` deploys with no pull of `ui`, predicts, UI loads | **done 2026-09-24** |
| 2 | Every marketplace module tested | `scripts/check-modules.sh` green for all eight, or the failures removed — DEEPaaS **and** Jupyter mode | **done 2026-09-25**; 14 of 16 pass, two catalogue decisions open |
| 3 | High code | a notebook that runs from a marketplace deployment | **done 2026-09-27** — four cells, 10 s, three runs identical |
| 4 | Low code re-walked | the GUI guide followed literally, timings re-measured, guide fixed | **done 2026-09-27** — answers are JSON now; the browser walk is the rehearsal's |
| 5 | Names and logos | `check-branding.sh` asserts the list in finding 6 on the served API; two modules dimmed | **done 2026-09-28** — what the demo's screens say is ours, checked in a browser |
| 6 | The script | `docs/demo-script.md` rewritten around the three tiers, timed | **done 2026-09-29** — 329 words, 2:12 of speech; the pre-pull split by node role, and pinned |
| 7 | Rehearse, then record | two timed read-throughs, the second with no correction | **in progress** — the platform rehearsed end to end and staged for recording, 2026-09-29; the read-throughs and the takes are a person's |

Order, revised for the five-minute cut and then by step 3's spike: 0, 1, the
step-3 spike, 2, the rest of 3, 4, 5, 6, **7**. Step 2 moved up because the
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

### Step 2 — Every marketplace module tested · done

**Done 2026-09-25 — see the step log.** JupyterLab is offered on modules again,
patch `0021` fixed the one image that could not run it as root, and 14 of 16
module/mode pairs pass. The two that do not are catalogue questions, not bugs
(Decisions, below). No module can use this cluster's GPU.

The plan, as it was:

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

### Step 4 — Low code re-walked · done

**Done 2026-09-27 — see the step log.** Patch `0022`: a synchronous call now
answers with the result as plain JSON, and the classifier's uploads keep their
result. Every call the dashboard's serverless form and Inference pages make was
exercised through PAPI as `researcher`, with fresh services; the pages
themselves did not change, so the browser half of this step — which is also
how whoever records re-learns the workflow — is the first thing the rehearsal
does, from `docs/oscar-gui-guide.md`.

The plan, as it was:

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

Also now, decided 2026-09-27: **dim `obj-detection-torch` and
`tf-cnn-benchmarks-api`** in the marketplace with "Not included in the Demo
Version" — their ids into `configs/dashboard/caios.json`'s `demoUnavailable`,
the mechanism CVAT and NVFLARE already use — and switch
`tests/test_failed_deployments.py` to read its exemptions from that list, so
there is one source of truth. It rides on this step's dashboard rebuild.

Clean the metadata when the mirror is built (`scripts/mirror-catalogue.sh`):
no `vo.*` tags, "Trainable / Pre-trained / Inference", "Development
Environment". No dashboard rebuild; PAPI serves it. `check-branding.sh` asserts
it. Optionally a locally built `caios/deepaas_ui` with a CAIOS footer, loaded
onto the nodes and never pulled from anywhere — worth it only if the Gradio page
appears on camera or test users will click it.

*As done: the categories could not be renamed in the data. The schema owns
them, and trying broke the live marketplace for five minutes — see the step
log and D-84. They are relabelled at display instead.*

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

*As done: the split alone was not enough, because docuum evicts what was pulled
weeks ago first. The images are pinned too (D-86). See the step log.*

### Step 7 — Rehearse, then record

Two timed read-throughs, then one take per tier. Clean browser profile with the
CA imported. Never on camera: the MinIO secret key, the vLLM API key, Vault
tokens, passwords.

---

## Decisions

Answered 2026-09-24:

1. **Federated learning: decided later.** In if it fits as high code, and it
   probably does. It keeps a provisional 40 seconds in the cut.
   **Decided 2026-09-29: kept**, at step 7.
2. **High code is YOLO.** `ai4os-yolo-torch`, in Jupyter mode if step 3's spike
   finds that works, else the dev-env fallback (B).
3. **The OSCAR services stay**, and were tested with real requests instead —
   see step 4.
4. **`researcher` records.** A new account is created on camera, to show
   sign-up and approval.

The storyboard was confirmed on 2026-09-25.

Opened by step 2, 2026-09-25, and **decided 2026-09-27**:

5. **`obj-detection-torch`** runs as an API (predict 6 s) but cannot run
   JupyterLab: it is not in the image, and pip cannot install it over a
   distutils-installed PyYAML. It is also the oldest image in the marketplace
   (PyTorch 1.4, 2019), and `ai4os-fasterrcnn-torch` does the same job — Faster
   R-CNN detection — and passes both modes. **Recommended: remove it.**
   **Decided: kept in the marketplace, dimmed, "Not included in the Demo
   Version". Step 5.**
6. **`tf-cnn-benchmarks-api`** exists to answer "is this GPU working", and on
   this cluster the answer is always no: TensorFlow 2.2 finds the H100 slice and
   never finishes a matrix multiplication on it. On CPU its "predict" is a full
   benchmark that runs past five minutes. **Recommended: remove it.**
   **Decided: the same — dimmed. Step 5.**
*Asked 2026-09-27, before deciding 5 to 7: can the modules be fixed to run on
the GPU instead?* Answered in the step log, "Can the modules run on the GPU?".
Short version: yes, but only by rebuilding their images on a newer base — no
setting does it — and it is cheap only for the PyTorch ones.

7. **Should modules be offered a GPU at all?** None of the eight can use one
   (step log). Offering it holds a GPU nobody else can then use, counts against
   the researcher's two-GPU limit, and runs on CPU anyway. **Recommended:
   CPU-only for modules** — `gpu_num` fixed at 0 in `modules-user.yaml`, with a
   sentence saying why; GPUs stay offered where they work: the LLM, the
   development environment, federated learning.
   **Decided: CPU-only now (done in step 4, D-83); rebuild YOLO and Faster
   R-CNN on a GPU-capable base after the demo** — see "After the demo".

---

## After the demo

Work that is decided and deliberately not before the recording:

- **GPU modules.** Rebuild `ai4os-yolo-torch` and `ai4os-fasterrcnn-torch` on a
  PyTorch 2 / CUDA 12 base, host them where PAPI reads tags from (a CAIOS
  organisation on Docker Hub), pin their tags (gotcha 28), point the catalogue
  mirror at them, and raise `gpu_num` for those two. Proven feasible
  2026-09-27 (step log, "Can the modules run on the GPU?").
- **The Gradio page's footer.** `deepaas_ui` renders an AI4EOSC logo, fetched
  from `raw.githubusercontent.com` by the viewer's browser, for any namespace
  but `imagine` (finding 6). A locally built `caios/deepaas_ui`, pinned by
  digest like the image it replaces (gotcha 28). Off camera in the five-minute
  cut; test users clicking a module's UI will see it.
- **The certificate**, `docs/certificate-plan.md` C2 and C3.

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

### Step 2 — every module, both modes · 2026-09-25

`scripts/check-modules.sh` (new): each module deployed through PAPI as
`researcher`, with the form's defaults — one CPU, no GPU — in DEEPaaS mode
(model listed, a prediction on a real input, the Gradio page) and in Jupyter
mode (login with the deployment password). Results in
`demo/modules/check-results.tsv`.

| Module | DEEPaaS | Jupyter |
|---|---|---|
| ai4os-yolo-torch | pass — predict 2.5 s, person 0.909 | pass |
| ai4os-fasterrcnn-torch | pass — predict 8.9 s | pass |
| obj-detection-torch | pass — predict 6.0 s, person 0.999 | **fail** — cannot install JupyterLab |
| retinopathy-test | pass — predict 3.7 s | pass |
| ai4os-image-classification-tf | pass — predict 1.7 s, military uniform 0.34 | pass |
| ai4os-audio-classification-tf | pass — a 440 Hz tone is "Busy signal", 0.97 | pass |
| posenet-tf | pass — body keypoints, nose 0.998 | pass, **after patch `0021`** |
| tf-cnn-benchmarks-api | **fail** — predict runs past 300 s | pass |

What the sweep itself taught, in the order it happened:

- **About six module deployments fit at once**, beside the running LLM. Each
  reserves a whole core plus 500 MHz for its UI. The first version submitted
  eight and waited for all of them; two queued for capacity and would have been
  recorded as failures. It now keeps a rolling window of six and tests each
  deployment the moment it runs, deleting it straight after.
- **The Gradio page answers a few seconds after the API.** Checked once, straight
  after predicting, two modules showed 502 and were wrongly failed; re-tested
  with a three-minute wait they were up 0–5 s later. Worth knowing on demo day:
  a 502 on a fresh module's UI means "wait a moment".
- **`posenet-tf` was the 2026-09-02 failure, and it was real** — its image
  ships an older Jupyter config in `/srv/.jupyter` without `allow_root`. Patch
  `0021` passes `--allow-root`, which `deep-start` hands to `jupyter lab`; it
  now starts in 10 s.
- **`obj-detection-torch` cannot run JupyterLab** for a different reason: it
  is not in the image, and `pip install jupyterlab` stops at *Cannot uninstall
  'PyYAML'. It is a distutils installed project*. The only template-level fix
  is a global pip setting that would change every researcher's own
  `pip install` in every module, so it was not taken. Decision 5.

**GPUs.** Read from every module's Dockerfile and base image, and measured for
the two with a CUDA recent enough to see the slice:

| Module | Built on | With a GPU |
|---|---|---|
| retinopathy-test | TensorFlow 1.12, CUDA 9 in its `gpu` tag | cannot see a MIG slice |
| image-classification-tf, audio-classification-tf, posenet-tf | TensorFlow 1.14, CUDA 10 in `gpu` tags; `latest` is the CPU build | cannot see it |
| obj-detection-torch | PyTorch 1.4, CUDA 10.1 | cannot see it |
| ai4os-yolo-torch, ai4os-fasterrcnn-torch | PyTorch 1.13, CUDA 11.6 | sees it; first CUDA call still compiling after 25 min (measured, YOLO) |
| tf-cnn-benchmarks-api | TensorFlow 2.2, CUDA 11.0 | sees *"H100L-1-12C MIG 1g.12gb, Compute Capability 9.0"*; a 2048² matmul unfinished after 240 s (measured) |

MIG needs CUDA 11 or later to see a slice at all, and Hopper kernels need CUDA
11.8 or later. None of the eight has both. The cluster's GPUs are fine — vLLM
and the development environment's PyTorch 2.x images use them natively — the
modules simply predate the hardware. Decision 7.

Side effects, as expected: every module image was pulled onto whichever node
Nomad chose, so docuum has evicted some older images. Step 6 re-pulls the
demo's.

### Step 3 — the notebook · done 2026-09-27

`demo/high-code/high-code.ipynb`, four code cells, run inside the YOLO module
deployed in Jupyter mode as `researcher`, staged by `scripts/stage-high-code.sh`
and run by it once, headless:

```
[1.4s] YOLO on bus.jpg, boxes drawn             -> an image
[0.0s] what it found                            -> bus 1, person 4, stop sign 1
[5.2s] the same model, as the serverless service -> person 4, bus 1, stop sign 1
[0.3s] the private LLM describes it             -> "A street photo captures a bus and a stop
                                                    sign alongside four pedestrians walking
                                                    along the sidewalk."
```

Three consecutive runs, identical. The notebook opens from the workspace's own
file browser beside the module's code, reached through the public proxy with
the deployment password.

**No secret is in the notebook.** Endpoints, the service token and the LLM key
come from PAPI with the owners' own tokens and are staged as `.caios.json`
(mode 600) and `.caios-ca.pem` — dotfiles, which JupyterLab's file browser does
not list, so nothing sensitive is one click away on camera. Both calls verify
TLS against the CAIOS CA (D-43). `tests/test_high_code_notebook.py`.

What building it found:

- **The prompt matters more than the model.** The first wording made the model
  call the image "created by an AI"; another sampling "found" a missing stop
  sign. The call now pins `temperature: 0`, and the wording that won was
  checked against the model before it went into the notebook.
- **`nomad alloc exec` loses output when its stdin closes.** 1.28 MB of a
  1.73 MB file arrived with stdin at `/dev/null`, and one warm-up's entire
  summary vanished — which the first version of the script reported as a pass.
  It now holds stdin open for the length of the command, summarises the
  executed notebook inside the workspace rather than copying 1.7 MB out, and
  fails on an empty result.
- **The workspace reaches the LLM through the public proxy** — the node
  resolves the deployment hostname to the floating IP and the hairpin works —
  and OSCAR on its private address. No special routing needed.

The serverless cell is the only slow one, and only after the service has
scaled to zero (Knative holds it about 30 s). On camera: run it once just
before the take, or cut.

### Can the modules run on the GPU? · 2026-09-27

Asked before deciding what to do with the modules. **Yes, but not by any
setting: the fix is rebuilding each module's image on a newer base.** The GPU
and its driver are fine; what is old is the software inside the images.

Measured on `caios-wn-gpu-1`, one MIG slice, in the development environment's
`pytorch2.6` image — the software a rebuilt module image would carry:

```
torch 2.6.0+cu126, compiled for sm_80, sm_86, sm_90
first 4096x4096 matmul, cold    1.2 s      (the module's PyTorch 1.13: unfinished after 25 min)
the YOLO module's own package   installs, and deepaas-cli predict returns its detections
one YOLO training epoch, coco8  4.7 s on "CUDA:0 (NVIDIA H100L-1-12C MIG 1g.12gb)"
```

The only extra it needed was OpenCV's system libraries (`libgl1`,
`libglib2.0-0`), which the module's own Dockerfile already installs.

| Module | Route | Effort |
|---|---|---|
| ai4os-yolo-torch | same Dockerfile, `--build-arg tag=` a PyTorch 2.x / CUDA 12 base | **low** — hours; proven above |
| ai4os-fasterrcnn-torch | same, same base as YOLO | **low–medium** — its training pipeline is untested on PyTorch 2 |
| obj-detection-torch | same, but its requirements pin 2019-era packages (Pillow 7, OpenCV 4.2, pandas 1.0) | **medium** — porting, for a module Faster R-CNN already covers |
| four TensorFlow 1.x modules | NVIDIA's last TensorFlow 1 build, `nvcr.io/nvidia/tensorflow:23.03-tf1-py3` (TF 1.15.5, CUDA 12.1, Python 3.8) | **medium–high each** — Python 3.6 to 3.8, and an 8.1 GB compressed base, about 20 GB on disk per module against docuum's 80 GB per node |
| tf-cnn-benchmarks-api | NVIDIA TensorFlow 2 `25.02-tf2-py3` (TF 2.17, CUDA 12.8) | **uncertain** — the benchmark code is archived and was written for TF 2.2 |

Plumbing every route shares: the rebuilt images need a home PAPI can read tags
from — PAPI lists a module's tags from Docker Hub, so a CAIOS organisation there
is the path of least resistance — a pinned tag rather than `latest` (gotcha 28),
the catalogue mirror's `docker_image` pointed at it, and for YOLO, whose licence
is AGPL-3.0, the Dockerfile published with the image.

**Recommendation.** Not for the five-minute demo: the notebook answers in 1.4 s
on CPU, and the GPU story is the LLM's. After the demo, if GPU modules matter,
rebuild YOLO and Faster R-CNN first — cheap and proven — and leave the
TensorFlow 1 family on CPU: 20 GB images buy little on 12 GB GPU slices.
Until something is rebuilt, the honest form offers modules no GPU.

### Step 4 — serverless answers with its result · done 2026-09-27

Patch `0022` changes the script every OSCAR service runs. Verified with fresh
services created through PAPI exactly as the serverless form sends them, with
its defaults (2 CPUs, 3000 MB), then deleted:

| | Synchronous | Upload to the bucket |
|---|---|---|
| YOLO | **262 bytes of JSON**, 5.8 s after creation, 5.5 s after that | JSON result in 9.1 s |
| image classification | **plain JSON**, 9.6–10.3 s | JSON result in 12.2 s — **used to be lost** |

It took three rounds on the cluster, and the two that failed each taught
something no document said:

1. The synchronous result was written where uploads write theirs, and came back
   **base64-encoded** (`W1t7Im5hbWUiOi…`): OSCAR answers a synchronous call
   with any file it finds in the output folder, encoded. It is now written to
   `/tmp`, and the answer is the script's stdout.
2. The version lines were moved to stderr, and still opened every answer:
   **OSCAR's synchronous answer includes stderr.** They are now printed for
   uploads only.

`tests/test_oscar_service_script.py` runs the script's closing block with bash,
in both modes, against a log coloured exactly as DEEPaaS 2.6 colours it.

Also in this step:

- **Modules are offered CPU only** (decision 7, D-83): `gpu_num` is `[0, 0]`
  with the reason as the form's hint, and PAPI itself answers a module asking
  for a GPU with `400: The parameter gpu_num should smaller or equal to 0`.
- **`scripts/oscar-submit.sh` sends the image now** and prints the answer; until
  today it wrapped the image and printed instructions. It reads either kind of
  answer, so it also works against a service created before `0022`.
- **The staging script picks the newest YOLO service**, so the notebook talks to
  one that answers in JSON when one exists.
- The three services from 2026-08-26 are untouched, as asked, and still answer
  the old way.

The GUI half is the rehearsal's first job, and it is short: marketplace → YOLO
→ *Deploy* ▾ → *Inference API (serverless)* → the form's defaults → *Inference*
→ the service → its endpoint.

### Step 5 — names and labels · done 2026-09-28

Every screen in the five-minute cut was walked in a browser against the live
platform. The walk found three faults no script had looked for, and each is now
behind a check.

| Where | Was | Now | By |
|---|---|---|---|
| module tags | `vo.imagine-ai.eu` on five modules | gone | mirror sanitiser |
| Tools list | "AI4OS Development Environment" | "Development Environment" | mirror sanitiser |
| category chips and filter | "AI4 trainable", "AI4 pre trained", "AI4 inference" | "trainable", "pre trained", "inference" | dashboard `0017`, display only |
| deploy form heading | "Configure training", on every form | "Configure deployment" | string |
| Deploy menu | "Inference API + UI (dedicated)" | "Dedicated deployment", described as an API or a notebook | string |
| creation times | Paris time, from a timestamp read as the viewer's local time | UTC, as every label says | dashboard `0016` |
| Inference detail | "MINIO URL": `http://minio.minio.svc.cluster.local:9000` | "MinIO console": the console users sign in to | PAPI `0023` and a string |
| `obj-detection-torch`, `tf-cnn-benchmarks-api` | clickable, failing | dimmed, labelled "Not included in the Demo Version" | tenant config, dashboard `0018` |

**What went wrong on the way.** The first attempt renamed the category values
in the catalogue mirror. PAPI validates every entry against the AI4OS metadata
schema, and that schema *enumerates* the categories, so all eight modules
served as "invalid metadata" with their ids for titles for about five minutes
before the mirror was reverted and PAPI restarted. Nothing had noticed.
`check-branding.sh` now fails on any entry marked invalid,
`tests/test_catalogue_mirror.py` keeps the mirror's categories to the schema's,
and the chips are relabelled in the dashboard instead (D-84).

**What the browser walk found:**

- **Creation times were wrong under a "UTC" label.** Upstream parses PAPI's
  zone-less timestamp as the browser's local time and formats it in
  Europe/Paris. That is right only for a viewer in Central Europe. A service
  created at 00:36 UTC read 06:36 in the list and 00:36 in its own detail
  dialog.
- **The Inference detail page offered an address nobody can open**, the one
  OSCAR's jobs use inside the cluster. PAPI now returns
  `CAIOS_OSCAR_MINIO_URL` in its place, and the services keep the in-cluster
  address.
- **A dimmed card's tooltip could never appear.** It sat on the element whose
  `pointer-events: none` makes the card unclickable, so no mouse reached it.
  This had been true of CVAT and NVFLARE since T4. It was found on the first
  step-5 build, and fixed in a second: a label on the card, and the full
  sentence as a tooltip on an undimmed wrapper.

**Checked in the browser, on the build that is serving:**

- the YOLO page's chips and tags
- the Deploy menu, and the form heading "Configure deployment: YOLO models"
- Deepaas and Jupyter offered, and the GPU field capped at 0 with the reason
  as its hint
- "Development Environment" in Tools, and the category filter's options
- the LLM's creation time
- a serverless service created from the form: its list time matched its
  detail's (00:55:36), with the "MinIO console" field. The service was
  deleted afterwards.
- all four dimmed cards (two modules, CVAT, NVFLARE) showing the label, with
  the tooltip opening

**Tests:** 336 unit. The smoke checks all pass against the live platform:

| Check | Result |
|---|---|
| `check-branding` | 26 ok |
| `check-dashboard` | 19 ok |
| `check-catalogue` | 10 ok |
| `check-home-page` | 13 ok |
| `check-public-path` | passed |

`check-branding` gained two sections: 2b covers what the demo's screens say,
and 4b covers the marketplace's own words.

**Deliberately left:**

- **"AI4life model loader"** names where its models come from, as the Modules
  page's AI4Life tab does.
- **The Gradio page's AI4EOSC footer** is not in the five-minute cut. It stays
  on the after-the-demo list.
- **The Keycloak sign-up and login pages** are the stock Keycloak theme with a
  "CAIOS" wordmark. The sign-up beat puts them on camera. They are legible and
  say nothing wrong, so theming them is polish, for step 7 to judge on the
  recording.

Rollback: `rollback/papi-pre-0023.tar` and `rollback/dashboard-pre-step5.tar`.
The catalogue half is a `git checkout` of the mirror and a PAPI restart.

### Step 6 — the script · done 2026-09-29

**`docs/demo-script.md` is rewritten for the five-minute recording.** It has
seven beats, opens on the home page and uses its three tiers as the spine. Each
beat has what is on screen, what to say and what to cut. It adds a
before-you-start list, the three browser windows, what never goes on camera, a
table of what goes wrong in each beat, and the live demo's questions, corrected.

The narration is 329 words, counted from the script: about 2 min 12 s at
150 words a minute, which leaves 2 min 48 s for the screens. Two of the
waits were measured for it today:

- **the LLM beat's note:** 0.3–0.4 s on Qwen3.5-2B, one sentence, no thinking
  block
- **the low-code command:** exactly as the script has it, 6.8 s for a new
  service's first call and 6.3 s after. The service was created as the form
  does it, then deleted.

**The pre-pull, split by node role, found the nodes in worse shape than step 1
had:**

| Node | Images | What was wrong |
|---|---|---|
| `caios_llm` | 52 GB | module images from step 2's sweeps, and **no vLLM**: docuum had evicted it |
| `caios_site_c` | 76.5 GB | vLLM and Open WebUI, for the LLM Platform Administrator deployed on 2026-09-24. It landed here, on a hospital, despite its preference for `caios_llm` |
| `caios_site_b` | 62.7 GB | neither the federated workspace image nor the FL server |
| `caios_site_a` | 77.7 GB | near the threshold, mostly module images |

So the playbook now sends each node its role's list:

- every node gets the `ui` digest
- `caios_llm` gets vLLM, Open WebUI and the LLM helper, about 38 GB
- the three sites get the FL workspace (`tf2.14.0`), the FL server and YOLO,
  about 34 GB

`--tags plan -c local` prints the split and connects to nothing. Three images
that nothing in the demo deploys left the list:

- `dev-env:u22.04`
- `dev-env:pytorch2.1`, which the list had said the FL workspaces use; they
  use `tf2.14.0`
- `federated-server:tokens`

Splitting was not enough. docuum evicts the least recently used image first,
and on `caios_llm` pulling vLLM back crosses 80 GB with Open WebUI, last used
in August, as the likeliest casualty. So each image is **pinned**: a container
created from it and never started, which docuum never evicts the image of
(D-86). The pins go on before the pulls. `ansible/files/caios-pin.sh` does it,
and `tests/test_prepull_split.py` runs it against a fake docker and checks each
list against the file the demo deploys from.

**The playbook has not been run.** Against today's nodes it writes about 70 GB
to shared machines: vLLM to `caios_llm`, the FL images to `caios_site_a` and
`caios_site_b`, and YOLO to `caios_site_c`. docuum then evicts unpinned module
images to make room, so it waits for a go-ahead. It is the first line of
step 7.

**Also in this step:**

- **The home page's tiers read No code, Low code, High code**, the recording's
  own words. They were *No code, Some code, Full control*. The dashboard was
  rebuilt and deployed, and `rollback/dashboard-pre-step6.tar` is the undo.
- **The module deploy form's GPU hint** said federated learning uses the GPUs.
  The demo's federated workspaces are CPU-only (gotcha 10), so the hint now
  names the language models and the development environment only. PAPI was
  restarted to read it.
- **Decided:** the recording has two accounts, and the cut between beats 2 and
  3 hides the change of name (D-85).
- **Left to the person recording:**
  - Platform Administrator's LLM on `caios_site_c`
  - researcher's three serverless services from 2026-08-26, one titled
    "Testing Classification", which beat 4 would show

  The script's checklist says what each is in the way of.

**Tests:** 350 unit (14 new). `check-branding`, `check-dashboard`,
`check-catalogue`, `check-home-page` and `check-public-path` all pass against
the live platform.

### Step 7 — the rehearsal, the platform half · 2026-09-29

Everything in the script's *Before you start* was done for real, as
`researcher`, and every beat's machinery was exercised.

**The pre-pull ran.** Every node reported *4 of 4 images cached and pinned*.
vLLM is back on `caios_llm`.

**Removed, as decided:**

- Platform Administrator's LLM on `caios_site_c`
- researcher's three serverless services from 2026-08-26

**Deployed and staged, where they will be recorded:**

| What | Where | Measured |
|---|---|---|
| Private language model, Qwen3.5-2B | `caios-wn-gpu-3`, the LLM node | running within 4 min 20 s |
| Object detection, serverless | the OSCAR node | first answer 7.0 s: a person and a tie |
| Federated server and three hospitals | server on `gpu-1`; `site_a` on `gpu-2`, `site_b` on `gpu-0`, `site_c` on `gpu-1` | deployed in 28 s; ten rounds in 32 s |
| YOLO notebook | `caios-wn-gpu-0` | staged; cells 1.9 s, instant, 8.1 s, 0.2 s |

**Two things the rehearsal found that no earlier step could have:**

1. **The deploy order in step 6's checklist was wrong.** With the notebook
   deployed before the federation, spread put `site_a` and `site_c` on the same
   machine. The scheduler was on `spread`, as it should be; the notebook's 8 GB
   made its node look busiest. The checklist now deploys the LLM, then the
   federation, then the rest, and `deploy-fl-demo.sh` says so.
2. **The federation could not run through the cluster at all.** Every client
   died with `RST_STREAM`, because the server's public name leads to the proxy
   VM and that proxy cannot carry gRPC. `docs/nginx-proxy.md` had said the
   clients never come through it. The hospital bootstrap now pins the name to
   Traefik's private address (D-87). Three runs after the fix: ten rounds in
   31.6–32.2 s, final accuracy 0.842–0.852, against 0.853 on the chart.
   `scripts/check-fl-cluster.sh` is new, and checks this path in a minute. Its
   first run passed.

**Also:**

- `deploy-fl-demo.sh` printed a wrong path for `server.py`.
- The home page's tiers were checked in a browser; they switch correctly.
- The chat login for the recording's LLM is `CAIOS_DEMO_UI_EMAIL` and
  `CAIOS_DEMO_UI_PASSWORD` in `configs/env/caios.env`.
- The workspaces' password is `CAIOS_FL_IDE_PASSWORD`.

**What is left is a person's:**

- a clean browser profile with the CAIOS CA imported
- logging in to the chat and to JupyterLab
- two timed read-throughs
- the takes
- deleting beat 2's account afterwards

The script is `docs/demo-script.md`, with its checklist already done except for
those.
