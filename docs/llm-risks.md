# LLM deployment — risks and restrictions

Companion to `docs/llm-plan.md`. Every entry is something that will cost time
or credibility if hit blind. Ordered by how much it costs, not by how likely it
is.

**Severity key.** *Blocking* — the feature does not work at all until it is
fixed. *Silent* — it works in a way that looks fine and is not, which is worse.
*Costly* — it works but wastes demo time. *Accepted* — we are choosing to live
with it, and here is why.

Every "verified" claim below was checked against upstream source at the pinned
commit `e80a2b7`, or against the live cluster, on 2026-08-19.

---

## Blocking — the feature is dead until these are fixed

### R-01 · The tool refuses to deploy on anything that is not a Tesla T4

**Verified.** `ai4papi/routers/v1/deployments/tools.py:604-612`:

```python
models = nomad_utils.get_gpu_models(vo)
if "Tesla T4" not in models:
    raise HTTPException(status_code=405, detail=...)
```

This is the error already seen in the dashboard. It is a hard string comparison
against one GPU model name, in Python, with no configuration behind it —
checked against upstream `master` as well as our pin, so there is no upstream
fix to pull.

**Fix:** patch `0009`, reading the allowed models from an environment variable
and defaulting to upstream's value. Same shape as patches `0001`, `0002` and
`0007`. → Stage L2.

**The value to set is now `NVIDIA H100L-1-12C MIG 1g.12gb`**, not
`NVIDIA H100L-1-12C` — the device plugin upgrade in R-18 changed what
`get_gpu_models()` returns. Confirmed against the live API on 2026-08-19.

### R-02 · The Nomad job also constrains the GPU device to a Tesla T4

**Verified.** `etc/tools/ai4os-llm/nomad.hcl:167-172`. Even with R-01 patched,
the job would be submitted and then never placed, because no device in this
cluster matches. Nomad reports this as a pending allocation with no obvious
error, which is the worst kind of failure.

**Fix:** our own `nomad.hcl` in `configs/papi/tools/ai4os-llm/`, bind-mounted
over upstream's — the same override mechanism already used for two `user.yaml`
files. The constraint is dropped rather than retargeted: there is exactly one
GPU model in this cluster, so it constrains nothing. → Stage L2.

### R-03 · The job asks for 8 CPU cores and 32 GB on nodes with 3 and 30

**Verified.** `nomad.hcl` lines 161-162 and 259-260. This is a bigger blocker
than either GPU check and would have bitten immediately after fixing them.

There is a second trap inside the fix, which is why it gets its own stage: in
Nomad, `cores` reserves whole CPUs *and* removes their MHz from the shared pool.
Reserving all three cores on a 6000 MHz node leaves nothing for the two helper
tasks and the job still will not place. The arithmetic is worked through in
`docs/llm-infrastructure.md`. → Stage L2.

### R-18 · Nomad allocated a GPU that CUDA could not use — **FIXED 2026-08-19**

**Found and fixed the same day. Recorded in full because the failure mode is the
lesson, not the fix.**

Our GPUs are MIG-backed vGPUs: the card exposes one `MIG 1g.12gb` instance, and
CUDA can address the instance but not the parent card. `nomad-device-nvidia`
**1.0.0** fingerprinted and allocated the **parent**. So any job with the
`device "gpu"` stanza — which is every PAPI job template — landed in a container
where:

```
nvidia-smi -L            ->  GPU 0: NVIDIA H100L-1-12C (UUID: GPU-...)   [no MIG line]
torch.cuda.is_available  ->  False
```

**Nothing GPU-backed had ever actually computed on this cluster.** It went
unnoticed for a week because the only check anyone ran was `nvidia-smi`, which
passes. `docs/progress.md` recorded "the GPU is visible inside a workspace" on
2026-08-12; it was visible and it was useless. The federated-learning demo was
unaffected only because D-18 made its clients CPU-only.

**The fix was one Ansible variable**, `nomad_nvidia_plugin_version: 1.0.0 → 1.1.0`
(MIG support: issues #3, #27 and #53, all closed 2024-08-22 with that release),
applied by `ansible/playbook-nvidia-plugin.yml` — a surgical playbook rather than
re-running the whole Nomad role, `serial: 1`, keeping the old binary alongside
for rollback.

**Verified after:**

```
job WITH device "gpu" { count = 1 }:
  SMI GPU 0: NVIDIA H100L-1-12C (UUID: GPU-...)
  SMI   MIG 1g.12gb  Device 0: (UUID: MIG-...)
  TORCH_CUDA=True
  DEV=NVIDIA H100L-1-12C MIG 1g.12gb
```

`scripts/check-gpu-scheduling.sh` reports "GPU scheduling is healthy" and is the
regression test. All four federated-learning deployments **survived** the rolling
restart — Nomad reattached to the running containers rather than killing them,
which was better than expected and is not something to rely on.

**Two consequences that outlive the fix.**

1. **The device name changed** from `NVIDIA H100L-1-12C` to
   `NVIDIA H100L-1-12C MIG 1g.12gb`, and the reported memory from 12288 to
   **10564 MiB** — the real usable figure. `configs/papi/var/gpu_models.csv`
   gained a row for it and PAPI now serves
   `gpu_type options: ['', 'NVIDIA H100L-1-12C MIG 1g.12gb']`. **Patch `0009`'s
   `LLM_GPU_MODELS` allowlist must use the new string** (R-01).
2. **`nvidia-smi` is not evidence.** Any future GPU check in this project
   multiplies two matrices. Both `scripts/check-llm-node.sh` and
   `scripts/check-gpu-scheduling.sh` do.

### R-04 · Node 6's specs are claimed, not yet measured

**Downgraded on 2026-08-19 by D-31.** The instance is confirmed ours, unused,
and identical to the other five. What remains is that nobody has logged into it,
so every number about it is inherited from the other nodes rather than read off
this one — including the `/dev/vdb` contents that Stage L1 erases.

**Fix:** Stage L0, ten minutes, read-only, before anything else is built.
Expected to be uneventful; it exists because "expected" is not "measured".

---

## Silent — works, looks fine, is not

### R-05 · The two helper tasks will die on our own TLS certificate

**Verified by reading, not yet by running — and it is the finding most likely to
cost a day.**

`check_vllm_startup` and `create-admin` are ordinary `python:slim-bullseye`
containers that `pip install requests` and then call **their own deployment's
public HTTPS URL**:

```
https://vllm-<uuid>.pacs-deployments.192.168.104.105.sslip.io/v1/models
https://ui-<uuid>.pacs-deployments.192.168.104.105.sslip.io/api/v1/auths/signup
```

Those are served by Traefik with our **self-signed CA's** wildcard certificate
(D-12). The stock Python image has never heard of that CA, so `requests` raises
`SSLError`. Neither script catches exceptions — both only test `response.ok` —
so the traceback escapes, the task exits non-zero, and because both are
`prestart`/`poststart` hooks **the whole allocation dies**.

`ansible/playbook-prepull-images.yml` already records this failure mode from a
different cause: *"the failing tasks are prestart and poststart sidecars, so
their failure kills the whole allocation — a deployment that looks like a
platform fault when it is really a slow download."*

Symptom if unfixed: the deployment goes `pending → running → failed` with no
message anywhere mentioning certificates.

**Fix:** stop going out through the front door. Both tasks are in the same
allocation as the service they are polling, so they can use Nomad's own
`${NOMAD_ADDR_vllm}` / `${NOMAD_ADDR_ui}` over plain HTTP on the node. That
removes DNS, Traefik and TLS from the startup path, and tests the right thing —
"is vLLM up" rather than "is the entire ingress chain up". → Stage L2, verified
in L3 and L4.

Fallback if the interpolation misbehaves: mount our CA into the tasks and set
`REQUESTS_CA_BUNDLE`, which is what the PAPI container already does.

### R-06 · vLLM's default memory fraction overshoots the usable framebuffer

**Verified by measurement, twice — and the numbers CUDA reports are not the ones
`nvidia-smi` reports.** From inside a container on `caios_site_a`,
`torch.cuda.mem_get_info()` returns **total 12100 MiB, free 10475 MiB**, where
`nvidia-smi` says 12288 and 10565. vLLM sizes itself from the CUDA numbers, so
those are the ones that matter:

| `--gpu-memory-utilization` | wants | against 10475 MiB free |
|---|---|---|
| 0.90 (vLLM's default) | 10890 MiB | **over by 415 MiB — will not start** |
| 0.85 | 10285 MiB | fits, 190 MiB spare — too tight |
| **0.80** | **9680 MiB** | **fits, 795 MiB spare** |

Left alone, vLLM fails at startup with a CUDA out-of-memory error that reads as
if the model is too big when the model is fine.

**Fix:** `--gpu-memory-utilization 0.80` on every entry in our curated
`configs/papi/vllm.yaml`, plus a unit test that fails the build if any model
omits it or sets it above 0.85. `scripts/check-llm-node.sh` prints this table
for any node, so it can be re-derived rather than trusted.

**Confirmed by a running deployment on 2026-08-19.** With Qwen3.5-2B loaded,
`nvidia-smi` on the node reported **8963 MiB used, 1603 MiB free** against a
budget of 9680 MiB. So 0.80 fits with room to spare, and 0.90's 10890 MiB target
would indeed have exceeded what the card had. → Stage L2.

### R-07 · The dashboard reads its model catalogue from AI4OS's GitHub, not from us

**Verified.** `ai4-dashboard/src/app/modules/catalog/services/tools-service/tools.service.ts:107-109`
hardcodes:

```ts
const url = 'https://raw.githubusercontent.com/ai4os/ai4-papi/refs/heads/master/etc/vllm.yaml';
```

Two consequences, one cosmetic and one functional.

*Functional:* the deploy form's model **dropdown** comes from our PAPI, but the
model **cards**, and the `needs_HF_token` logic that decides whether the
Hugging Face token field is required, come from upstream's file. Curate our
list and the two disagree — models with no description, and a token field that
appears or does not appear for the wrong models.

*Cosmetic, but it is the gotcha-6 pattern again:* it is a third-party fetch made
by the user's browser, from a page that is supposed to be self-contained on a
private subnet.

**Fix:** dashboard patch `0002` pointing at a relative asset, and
`scripts/build-dashboard.sh` staging our curated file into the image. → Stage L5.

### R-08 · A standalone Open WebUI deploys with no administrator

**Verified — upstream bug, and it has a security consequence.**
`tools.py:575` reads:

```python
if user_conf["llm"]["type"] in ["openwebui", "both"]:   # checks username/password
```

The option value defined in `user.yaml` is **`open-webui`**, with a hyphen.
`"openwebui"` is not a value the field can ever hold, so for a standalone UI
deployment the username and password checks are skipped entirely. The
`create-admin` task then POSTs an empty email and password, Open WebUI rejects
it, and the task retries forever while **the UI is already serving with signup
open** — so the first person to open the URL becomes the administrator.

Contained on a private subnet. Still wrong, and cheap to fix in the same patch
as R-01. Worth reporting upstream. → Stage L2.

### R-20 · The model returns an empty `content` field — **FOUND AND FIXED 2026-08-19**

**The first real deployment answered correctly and looked broken.**

```json
"content":   null,
"reasoning": "Federated learning is a machine learning approach where a global
              model is trained across multiple decentralized devices..."
```

Qwen3.5 has thinking enabled by default, and upstream's `--reasoning-parser qwen3`
routes everything before `</think>` into a separate `reasoning` field. The model
answered *inside* the think block and never emitted the closing tag, so the
parser classified the entire response as reasoning and left `content` null.

**Why this is a silent failure and not a cosmetic one.** Every OpenAI-compatible
client reads `content`: the Python SDK, LangChain, editor plugins, and the
"call it from a notebook in four lines" beat of the demo. All of them get `None`
and conclude the platform is broken. The only reason it was caught is that
`scripts/check-llm-deploy.sh` asserts a **non-empty completion** rather than a
200 — a 200 is exactly what this returns.

Upstream has the same class of problem recorded in its own catalogue: two Phi
models are commented out with *"openwebui does not render it's response
correctly."*

**Fix, and it was verified rather than guessed.** Two candidate causes: either
the parser was mis-classifying output that has no think tags, or the model really
wraps everything in tags. Those imply opposite fixes, so they were distinguished
by experiment — `enable_thinking: false` produced clean `content`, and removing
`--reasoning-parser` produced clean `content` **with no `<think>` markup leaking
through**. The tags come from the prompt template, not the generation.

So `--reasoning-parser` is dropped from the two general-purpose Qwen entries in
`configs/papi/vllm.yaml`, and **kept** on `LFM2.5-1.2B-Thinking` and
`DeepSeek-R1-Distill-Qwen-1.5B`, where separated reasoning is the point of the
model and Open WebUI renders it as a collapsible section.

**The general rule for this catalogue:** a model offered as a default must return
`content` to a plain OpenAI request. Anything that only works with extra
request-level arguments is a demo that breaks the moment someone writes ordinary
code against it.

**The two thinking models are a deliberate exception, and both options were
measured (2026-08-20).** Removing their parser does not produce a clean answer —
it produces the model's unedited thinking in `content`, opening with a literal
`<think>` tag on LFM2.5. So:

| | `content` | how it reads |
|---|---|---|
| parser kept | `null` | good in Open WebUI, `None` from a script |
| parser removed | raw thinking | looks broken to a person |

Kept, because the demo audience is people looking at a chat window. Their
catalogue descriptions now tell API callers to read `reasoning`. **Stage L4 must
confirm Open WebUI actually renders them well** — if it does not, drop both.
Seven uniform models beat nine with two that need explaining.

### R-21 · The deployment endpoint is a dead link until the allocation is placed

**Found on 2026-08-20 by a test harness that trusted it.** `GET /v1/deployments/tools/<id>`
publishes the endpoint before Nomad has placed the allocation, and at that point
it still contains Nomad's own placeholder:

```
https://vllm-<uuid>.${meta.domain}-deployments.192.168.104.105.sslip.io
                    ^^^^^^^^^^^^^ literal, unsubstituted
```

`meta.domain` is interpolated by the Nomad *client*, so before placement there is
nothing to interpolate it with. The hostname cannot resolve — `curl` reports
status `000`.

It cost an hour here: `scripts/check-llm-deploy.sh` fetched the endpoint once and
cached it, so any deployment whose first poll landed in that window spent its
whole timeout curling an unresolvable name, and three perfectly healthy models
were reported as failures. Fixed by treating anything containing `${` as "not an
endpoint yet" and re-fetching.

**The same window exists in the dashboard.** A user who clicks *Quick access* on
a deployment that has been accepted but not yet placed gets a dead link. It is a
few seconds wide and self-healing, so it is a papercut rather than a fault — but
it is exactly the sort of thing that happens on camera. Worth knowing about
before the demo, and worth a beat of patience in the script rather than a fix.

### R-09 · Secrets are written in clear text into the Nomad job specification

**Verified.** `nomad.hcl` puts `HUGGING_FACE_HUB_TOKEN`, `VLLM_API_KEY` and the
Open WebUI admin `PASSWORD` into `env` blocks as literal values. Anyone who can
read the job in that Nomad namespace can read them — this is upstream's design,
not something we introduce, and the federated-server tool has the same shape.

**Accepted for the demo**, with two consequences written into the demo script:
use a throwaway Hugging Face token if one is needed at all (the recommended
models are all ungated, so it should not be), and never type a real password
into the UI credential fields. Not a candidate for fixing in this window —
doing it properly means routing these through Vault, which is a PAPI change.

---

## Costly — works, but eats the clock

### R-10 · Thirty gigabytes of container image, and a garbage collector that deletes it

**Corrected and expanded on 2026-08-19 after measuring it on a real node.** The
original entry said 10.5 GB. That is the *compressed* size in the registry; on
disk `vllm/vllm-openai:v0.27.1` is **30.8 GB**. The whole pre-pull set is
**67.9 GB**, measured.

Two separate problems follow.

**The pull itself.** 30.8 GB is a very long silence in front of an audience, and
upstream sets `force_pull = true` on every deployment. Both `:latest` and Open
WebUI's `:main` are moving tags, so a demo that worked yesterday can break
overnight. *Fixed:* pinned tags, `force_pull = false`, and both images added to
`ansible/playbook-prepull-images.yml` — along with `python:3.12-slim-bullseye`
for the helper tasks, which upstream references as a bare, moving
`python:slim-bullseye`.

**And then something deletes it.** `docuum` runs as a Nomad **system job on every
compute node**, evicting least-recently-used images above a threshold that
upstream hardcodes at **50 GB** in `roles/nomad/templates/nomad-docuum-job.j2`.
Running the pre-pull against `caios_llm` pulled all eleven images, reported
success for all eleven, and docuum deleted six of them **before the playbook
finished**:

```
[INFO] Docker images are now using `40.37 GB`, which is within the limit of `50 GB`.
```

`docker images` showed five. The playbook exists precisely to keep a large pull
off the demo's critical path, and a garbage collector was undoing its work as it
ran — reporting success throughout.

The demo-day version of this is worse: vLLM is the largest image on the node, so
it is the prime eviction candidate. Deploy a dev environment (12.9 GB) after it,
cross the threshold, lose vLLM, and the next LLM deployment re-downloads 30.8 GB
live.

*Fixed:* `nomad-jobs/docuum.hcl` raises the threshold to **80 GB** — the full set
plus ~12 GB, still leaving ~45 GB of the 125 GB volume for allocation
directories, logs and the model cache. Node 6 now holds 11 of 11 images at
67.91 GB with nothing being evicted.

**The catch, and why there are two more guards.** Re-running
`ansible/playbook-nomad.yml` against `nomad_master` re-submits upstream's
template and puts 50 GB back. So `ansible/playbook-docuum.yml` reapplies ours,
and `scripts/verify-cluster.sh` prints the live threshold and **fails** if it has
reverted. A silent regression here costs 30 GB at the worst possible moment.

### R-11 · Model weights are re-downloaded on every deployment

Weights land in the container's writable layer, which is discarded when the
allocation stops. Delete and redeploy and the 4.5 GB comes down from Hugging
Face again.

*Fixed:* a host bind mount for the Hugging Face cache
(`/mnt/data/hf-cache:/root/.cache/huggingface`) with `HF_HOME` pointed at it.
Verified working — 4.3 GB of Qwen3.5-2B persisted to the host volume, and the
directory is created by `playbook-prepull-images.yml` rather than left for Docker
to invent (the D-29 failure mode).

**Correcting what this entry used to claim.** It said a second deployment would
"start in seconds". It does not. Measured on 2026-08-19, alloc creation to the
health check passing:

| | cold cache | warm cache |
|---|---|---|
| Qwen3.5-2B (4.5 GB) | **197s** | **175s** |

**The cache saves about 22 seconds of a ~190 second startup.** The dominant cost
is not the download — it is `torch.compile` plus capturing 86 CUDA graphs on a
16-SM MIG slice, and that happens on every start regardless.

So the cache is still worth having (it saves bandwidth, and it makes startup
independent of Hugging Face being reachable and fast) but it is **not** a way to
make deployment quick. The demo has to deploy the LLM ahead of time either way —
which is what the ordering rule in R-14 already requires for a different reason.

### R-12 · vLLM startup is slow even when everything is right

Weight load, `torch.compile`, and CUDA graph capture happen before the first
token. On 16 SMs expect **two to five minutes** from allocation to a working
`/v1/models`, with the deployment showing as starting the whole time.

**Measured on 2026-08-19, and the estimate was right:** **175-204 seconds** from
`POST /v1/deployments/tools` to `/v1/models` answering, for Qwen3.5-2B. Roughly
30s of that is weight download on a cold cache; the rest is `torch.compile` and
capturing 86 CUDA graphs.

Once up, it is **fast**: **97.8 tokens/second** sustained over a 300-token
generation, which is comfortably fluent for a live chat and better than a 16-SM
slice suggests.

**Fix:** none needed, but the demo must not wait for it live. The demo script
deploys the LLM first and comes back to it, exactly as it already does for the
federated-learning bundles — which R-14 requires anyway for placement reasons.
If it ever needs to be faster, `--enforce-eager` removes graph capture at some
cost to throughput.

### R-13 · Open WebUI downloads an embedding model on first boot

Open WebUI fetches a sentence-transformers model for its RAG feature the first
time it starts. Roughly 90 MB, needs egress to Hugging Face, and it happens
while the login page is already being served — so the UI looks up and is slow.

**Fix:** pre-pull is not possible (it is inside the app, not the image), so it
is a documented wait, plus `WEBUI_SECRET_KEY` set explicitly so sessions survive
a restart. → Stage L4.

### R-14 · Four compute nodes breaks the "three hospitals" picture

**Confirmed by measurement on 2026-08-19, and the fix this document originally
proposed turned out not to work.**

`scripts/deploy-fl-demo.sh` relies on spread-mode scheduling to land three
workspaces on three nodes. With `caios_llm` in the cluster there are four, and
three dev-env-shaped jobs land like this:

```
   caios-wn-gpu-0: 1
   caios-wn-gpu-1: 1
   caios-wn-gpu-3: 1     <- caios_llm, the LLM host
```

The training is still genuinely federated across three separate machines; the
node names on screen stop matching the story, which a viewer will notice.

**What did not work: a soft anti-affinity on `meta.role = llm`.** This document
proposed it, and it was tested before being written into anything. Placement was
unchanged — still `gpu-0, gpu-1, gpu-3`. Nomad combines affinity with the
spread score, and an empty node scores high enough on spread that a `-100`
affinity does not overcome it. Worth recording as a general lesson: **soft
affinities do not override spread on an idle node.**

**What does work: deploy the LLM first.** With an LLM-shaped allocation already
holding `caios_llm`, the same three workspaces land on the hospital nodes and
none goes near it — measured, not argued. That is now the documented ordering in
`scripts/deploy-fl-demo.sh` and it becomes a line in the demo script at Stage L6.

**If a guarantee is wanted rather than an ordering convention**, the option is a
*hard* constraint (`meta.role != llm`) in a `configs/papi/tools/ai4os-dev-env/nomad.hcl`
override. Not taken, for two reasons: it means carrying a copy of a 332-line
upstream file whose correctness the primary demo depends on, and a hard
constraint means a workspace fails to deploy outright when the three hospital
nodes are full, rather than landing somewhere and looking untidy. Worth revisiting
only if the ordering convention proves fragile in rehearsal.

## Accepted — chosen, with reasons

### R-15 · An LLM deployment is invisible to the GPU quota

`quotas.check_userwise` caps a user at two GPUs by reading
`conf["hardware"]["gpu_num"]`. The LLM tool's `user.yaml` has **no `hardware`
section at all**, so the field is absent, the check short-circuits, and the GPU
is never counted. One user can start LLM deployments until the cluster has no
GPUs left.

Accepted: five accounts, one private cluster, and adding a `hardware` section
would change the deploy form for no demo benefit. Written into the runbook as
"if a GPU deployment will not place, look for a forgotten vLLM first".

### R-16 · Reformatting `/dev/vdb` on node 6 destroys whatever is on it

The instances ship with a 125 GB ext4 filesystem written **directly to the raw
device**, with no partition table. `ai4-nomad_tests` asserts that a GPU compute
node's Nomad `data_dir` sits on `/dev/vdb1`, and that suite is the only thing
that sets `meta.status = ready` — so without a partition the node certifies as
failed, never turns ready, and silently receives no work at all. Creating a
partition table means writing over the start of the disk, which is where the
existing filesystem lives. **There is no non-destructive path.**

Only `/dev/vdb` is affected. The OS disk `/dev/vda` — the operating system,
`/home/ubuntu`, SSH keys, packages — is untouched, as is every other node.

**Not accepted silently, and three checks deep:** Stage L0 lists the volume's
contents for a human to read; the playbook independently refuses to run if
`/mnt` holds anything other than `lost+found`; and it carries a hard assert that
it can never run against `caios_server`, whose volume holds this repository. The
full explanation, with the evidence, is in `docs/llm-infrastructure.md` under
*"What the reformat actually does"*.

### R-17 · No model in the catalogue knows any medicine

Every model on offer is a general-purpose instruction-tuned model. The
defensible claim is *"your own model, on your own hardware, where the prompts
never leave"* — which is the same privacy argument as the federated learning
demo and is true. *"A medical AI assistant"* is not, and a reviewer will ask.

**Decided on 2026-08-19 (D-32):** upstream's models, used as they are, no
fine-tuning. So this is now a **wording constraint on the demo**, and it is
binding: nothing in the script may imply the model knows medicine.

The cost of changing course later is known and small — any model on the list can
be swapped for a fine-tuned variant by changing one line in
`configs/papi/vllm.yaml`, provided the variant fits the same 10.3 GB budget.

### R-19 · Upstream drift

Patch `0009` and both config overrides are pinned to `e80a2b7`. If
`scripts/clone-vendor.sh` moves, they may not apply. This is the standing cost
of D-17 and is unchanged by this work; the unit tests in Stage L2 include a
`git apply --check`, so drift fails the test run rather than demo day.
