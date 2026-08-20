# Progress

Running log of what has actually been done. Updated at every step.

Newest entries at the top. Each entry says what changed, what was verified, and
what it unblocks — so that "done" always means something checkable.

**Where we are: MVP complete. Stages 0–5 are done.** A federated training runs
across three hospital sites on three separate machines and beats what any one
site can do alone; the platform around it now reads as a medical imaging
platform rather than somebody else's stack. `docs/demo-script.md` is written
and timed at 22 minutes.

**Stage 6 — LLM deployment — is the current focus**, planned on 2026-08-19 and
not yet built. `docs/llm-plan.md` is the plan; the entry below says what the
analysis found. Alongside it, what is left is rehearsal and the V1 list.

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
| 6 — LLM deployment | vLLM + Open WebUI on the lab's own GPUs | **L0, L1, L2 done; L3 next** — `docs/llm-plan.md` |

**Nothing is blocking.** The GPU-scheduling defect found on 2026-08-19 was fixed
the same day (R-18). Next actions, in order:

1. **Stage L3** — the first real vLLM deployment. Everything it needs is in
   place: the node, the config, the images, and a job that `nomad job plan` says
   will allocate.
2. **Rehearse the demo end to end in a browser**, following
   `docs/demo-script.md`. Nothing in the walkthrough has been driven by a human
   clicking yet — every piece is verified individually, which is not the same
   thing.
3. **A real domain and certificate** (V1 item 1). Half a day, and it removes the
   browser warning that currently opens the demo.
4. Record it.

Two things a person still has to judge, which no script settles:

- Does the dashboard read as a medical imaging platform to someone who does not
  know the project? That is the Stage 5 gate's real half.
- Is brain MRI the right disease area? (Q-08 — answered by default, not by
  decision.)

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
