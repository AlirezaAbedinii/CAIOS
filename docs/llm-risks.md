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

### R-18 · Nomad allocates a GPU that CUDA cannot use — **CONFIRMED, cluster-wide**

**No longer a risk. Measured on 2026-08-19, and it is a defect in the running
cluster that has nothing to do with the LLM tool.**

Our GPUs are MIG-backed vGPUs: the device holds one `MIG 1g.12gb` instance, and
CUDA can address the instance but not the parent. `nomad-device-nvidia` **1.0.0**
— the version we run — fingerprints and allocates the **parent**. So a Nomad job
with the `device "gpu"` stanza that every PAPI template uses gets a container in
which:

```
nvidia-smi -L            ->  GPU 0: NVIDIA H100L-1-12C (UUID: GPU-...)
                             (and no MIG line)
torch.cuda.is_available  ->  False
```

Verified four ways on `caios_site_a`:

| `NVIDIA_VISIBLE_DEVICES` | MIG device exposed | `torch.cuda` |
|---|---|---|
| `GPU-<parent uuid>` — what the plugin selects | no | **False** |
| `MIG-<instance uuid>` | yes | True |
| `0:0` | yes | True |
| `all` | yes | True |

and then through the real Nomad path: a batch job **with** `device "gpu" { count = 1 }`
reports `False`; the identical job **without** it reports `True` and
`NVIDIA H100L-1-12C MIG 1g.12gb`. Setting `NVIDIA_VISIBLE_DEVICES` in the task's
own `env` block does **not** help — the device plugin overrides it.

**This is the worst failure mode there is, because it looks like success.**
`docs/progress.md` recorded on 2026-08-12 that "the GPU is visible inside a
workspace". That was true, and the GPU was unusable. Nothing GPU-backed has ever
actually computed on this cluster; nobody checked, because `nvidia-smi` said yes.
The federated-learning demo is unaffected — D-18 made its clients CPU-only.

**Fix — one Ansible variable.** MIG support landed in `nomad-device-nvidia`
**1.1.0** (issues #3, #27 and #53, all closed 2024-08-22 alongside that release).
`ansible/group_vars/all.yml:91` pins `nomad_nvidia_plugin_version: 1.0.0`, and
the role downloads it straight from `releases.hashicorp.com` — the 1.1.0 artifact
is present and fetchable, verified.

**Not yet proven on our hardware**, and that distinction matters: the fix is
strongly indicated, not measured. Stage L1 bumps the version, restarts the Nomad
clients, and `scripts/check-gpu-scheduling.sh` says whether it worked.

Two things to re-check after the bump, because the plugin will report the MIG
instance rather than the parent:

- the **device name** may change from `NVIDIA H100L-1-12C` to a name including
  the MIG profile. That is what `get_gpu_models(vo)` returns, so it feeds
  `configs/papi/var/gpu_models.csv`, the dev-env `gpu_type` dropdown, and the
  allowlist in patch `0009` (R-01). All three may need the new string.
- restarting a Nomad client **disturbs running allocations**, including the four
  federated-learning deployments. Schedule it, do not surprise it.

**Fallback if 1.1.0 does not fix it:** drop the `device "gpu"` stanza and select
the node by `meta.role = llm` instead — proven to work above. The cost is that
Nomad stops accounting for the GPU, so nothing prevents two GPU jobs landing on
one node. Tolerable only because the LLM node is dedicated and `cores = 2` on a
3-core node already means one such job at a time.

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
for any node, so it can be re-derived rather than trusted. → Stage L2.

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

### R-10 · Ten and a half gigabytes of container image, pulled on every deployment

**Verified.** `vllm/vllm-openai:latest` is **10.53 GB**, and the job sets
`force_pull = true` on all three images. On a first deployment that is a very
long silence in front of an audience; `playbook-prepull-images.yml` exists
precisely because a slow pull already killed allocations here once.

Also, both `:latest` and Open WebUI's `:main` are **moving tags**. A demo that
worked yesterday can break overnight because someone else released something.

**Fix:** pin `vllm/vllm-openai:v0.27.1` and
`ghcr.io/open-webui/open-webui:v0.11.0`, set `force_pull = false`, and add both
— plus `python:slim-bullseye`, which the helper tasks use and which is not in
the list either — to the pre-pull playbook. → Stage L2.

### R-11 · Model weights are re-downloaded on every deployment

Weights land in the container's writable layer, which is discarded when the
allocation stops. Delete and redeploy and the 4.5 GB comes down from Hugging
Face again. Fine once; painful during a rehearsal loop.

**Fix:** a host bind mount for the Hugging Face cache
(`/mnt/data/hf-cache:/root/.cache/huggingface`) with `HF_HOME` pointed at it.
Nomad's Docker driver already reports `volumes.enabled = true`, and the
containerd root is on the 125 GB volume. Second deployment of the same model
then starts in seconds. → Stage L2, measured in L3.

### R-12 · vLLM startup is slow even when everything is right

Weight load, `torch.compile`, and CUDA graph capture happen before the first
token. On 16 SMs expect **two to five minutes** from allocation to a working
`/v1/models`, with the deployment showing as starting the whole time.

**Fix:** none needed, but the demo must not wait for it live. The demo script
deploys the LLM first and comes back to it, exactly as it already does for the
federated-learning bundles. If it is still too slow, `--enforce-eager` removes
graph capture at some cost to throughput. Measured and recorded in Stage L3.

### R-13 · Open WebUI downloads an embedding model on first boot

Open WebUI fetches a sentence-transformers model for its RAG feature the first
time it starts. Roughly 90 MB, needs egress to Hugging Face, and it happens
while the login page is already being served — so the UI looks up and is slow.

**Fix:** pre-pull is not possible (it is inside the app, not the image), so it
is a documented wait, plus `WEBUI_SECRET_KEY` set explicitly so sessions survive
a restart. → Stage L4.

### R-14 · Four compute nodes breaks the "three hospitals" picture

Covered in full in `docs/llm-infrastructure.md`. In short: `deploy-fl-demo.sh`
relies on spread-mode scheduling to land three workspaces on three nodes, and
with a fourth node in the cluster it can land them anywhere. The training is
still genuinely federated; the node names on screen stop matching the story.

**Fix:** a soft anti-affinity on `meta.role = llm` in the dev-env job template,
plus deploying the LLM before the FL workspaces on demo day. → Stages L1 and L6.

---

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
