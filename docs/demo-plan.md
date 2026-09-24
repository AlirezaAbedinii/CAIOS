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
slow pull takes the whole allocation down with it. The registry answered
normally an hour later (`401` in 0.86 s, which is its unauthenticated reply):
transient, the same shape as the GitHub outage of 2026-09-01.

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

## Steps

| # | Step | Gate | State |
|---|---|---|---|
| 0 | Clean slate | the stale deployments gone, gpu-1 and gpu-3 free | **done 2026-09-24** |
| 1 | Module deploys stop depending on Europe | `obj-detection-torch` deploys with no pull of `ui`, predicts, UI loads | next |
| 2 | Every marketplace module tested | `scripts/check-modules.sh` green for all eight, or the failures removed | |
| 3 | High code | a notebook that runs on the GPU from a marketplace deployment | |
| 4 | Low code re-walked | the GUI guide followed literally, timings re-measured, guide fixed | |
| 5 | Names and logos | `check-branding.sh` asserts the list in finding 6 on the served API | |
| 6 | The script | `docs/demo-script.md` rewritten around the three tiers, timed | |
| 7 | Rehearse, then record | two timed read-throughs, the second with no correction | |

Order: 0, 1, then 2 with the step-3 spike and step 4 in parallel, then 3, 5, 6, 7.
About four to five working days. Commit and push after each step.

### Step 1 — Module deploys stop depending on Europe

- PAPI patch `0020`: the `ui` image referenced **by digest** with
  `force_pull = false`, so a cached copy is used with no network call. `main`
  gets `force_pull = false` too, which helps any pinned tag; for the default
  `latest` Nomad still checks Docker Hub, which is fast when the layers are
  cached and has been reliable throughout.
- `playbook-prepull-images.yml` pulls the same digest, so the two cannot drift;
  a unit test asserts they agree. Adds `ai4os-yolo-torch` after measuring each
  node's disk against docuum's 80 GB threshold (gotcha 14).
- Gate: deploy `obj-detection-torch`; the `ui` task shows no *Downloading
  image* event; `predict` returns detections; the UI page loads. Then delete.

### Step 2 — Every marketplace module tested

`scripts/check-modules.sh`, shaped like `check-llm-catalogue.sh`. For each module
in `catalog/keep.txt`: deploy (DEEPaaS, CPU), wait for `running`, `GET
/v2/models/`, one `predict` with a fixture of the right data type, the UI
answers, delete. A module that fails is fixed or removed from `keep.txt` (one
line, a mirror refresh, and the home-page counts test). GPU tested only for the
module the demo uses, with a matrix multiplication (gotcha 13).

### Step 3 — High code

A spike first: a one-off Nomad job, outside PAPI so nothing user-visible
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

### Step 5 — Names and logos

Clean the metadata when the mirror is built (`scripts/mirror-catalogue.sh`):
no `vo.*` tags, "Trainable / Pre-trained / Inference", "Development
Environment". No dashboard rebuild; PAPI serves it. `check-branding.sh` asserts
it. Optionally a locally built `caios/deepaas_ui` with a CAIOS footer, loaded
onto the nodes and never pulled from anywhere — worth it only if the Gradio page
appears on camera or test users will click it.

### Step 6 — The script

Rewrite `docs/demo-script.md` around the three tiers, opening on the home page.
A before-you-start list: pre-pull, the LLM deployed first so it lands on gpu-3,
one warm-up request to OSCAR, the high-code workspace deployed and its notebook
staged. A fallback clip for each tier.

### Step 7 — Rehearse, then record

Two timed read-throughs, then one take per tier. Clean browser profile with the
CA imported. Never on camera: the MinIO secret key, the vLLM API key, Vault
tokens, passwords.

---

## Open decisions

1. **Is federated learning in the recording?** `CLAUDE.md` still calls it the
   headline; the three tiers do not mention it. Recommended: keep it as the end
   of the high-code tier, since it runs in the same JupyterLab workspaces.
2. **High-code vehicle:** YOLO in Jupyter mode with B as the fallback, or
   `obj-detection-torch` specifically?
3. **The three OSCAR services from 2026-08-26** — clear them so the Inference
   list is clean on camera?
4. **Which account records, and from which machine?** Recommended: `researcher`,
   on a laptop on the VPN. And any names or logos noticed that finding 6 misses.

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
