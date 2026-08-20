# LLM deployment — the plan

**Stage 6 of the CAIOS build.** The MVP is complete and federated learning
works; this adds the second headline feature — a researcher deploying a private
language model onto the lab's own GPUs.

Read alongside:

| Document | Answers |
|---|---|
| `docs/llm-concepts.md` | What vLLM and Open WebUI are, and how they differ |
| `docs/llm-infrastructure.md` | What the hardware is, what fits, what changes |
| `docs/llm-risks.md` | What will go wrong, and what it costs |

**Nothing in this document has been implemented.** It is a plan, and the first
stage is a ten-minute check that decides whether the rest of it is possible.

---

## The headline

The tool is not "nearly working with a GPU-model mismatch". It has **four
independent blockers**, and the GPU-model error is only the one that fires
first. Fixing it alone would replace an error message with a deployment that
queues forever.

| # | Blocker | Where | Fix | Risk |
|---|---|---|---|---|
| 1 | Hard-coded `"Tesla T4"` gate | `tools.py:604` (Python) | Patch `0009` | R-01 |
| 2 | Nomad device constraint `= "Tesla T4"` | `nomad.hcl:171` | Config override | R-02 |
| 3 | **Asks for 8 CPU cores and 32 GB** on 3-core, 30 GB nodes | `nomad.hcl:161,259` | Config override | R-03 |
| 4 | Both helper tasks call their own public HTTPS URL and die on our self-signed CA | `nomad.hcl:196,284` | Config override | R-05 |
| 5 | ~~A Nomad job that asks for a GPU gets one CUDA cannot use~~ | `nomad-device-nvidia` 1.0.0 | **FIXED — plugin 1.1.0** | R-18 |

Blocker 3 is the real one for scheduling. Blocker 4 is the one that would have
eaten a day, because it fails with a traceback that never mentions certificates.

**Blocker 5 was found by running Stage L0, and it was not an LLM problem — it
was cluster-wide.** Our GPUs are MIG-backed vGPUs; the device plugin allocated
the *parent* device, which CUDA cannot use, so every PAPI job template landed in
a container where `nvidia-smi` worked and `torch.cuda` was `False`. Nothing
GPU-backed had ever actually computed on this cluster.

**Fixed on 2026-08-19** by `nomad-device-nvidia` 1.1.0, applied with
`ansible/playbook-nvidia-plugin.yml`, verified end to end, FL deployments intact.
It changed the GPU's name and reported memory, which patch `0009` and
`gpu_models.csv` both depend on. See R-18.

**None of them need a fork.** One patch — in the same shape as the three we
already carry — plus configuration files bind-mounted over upstream's, which is
the mechanism already used for two other tools, plus one Ansible version bump.

**Estimated cost: 4 engineer-days**, roughly 2.5 calendar days with two people.
`docs/feature-coverage.md` previously estimated one day; that estimate saw the
memory numbers and none of the four blockers above. It is corrected in the same
change as this document.

---

## Definition of done

> A researcher logs into CAIOS, opens **Tools → Deploy your LLM**, picks a model,
> clicks Deploy, and within five minutes has a chat interface at their own
> subdomain and an OpenAI-compatible API endpoint. A notebook in a CAIOS dev
> environment calls that endpoint with four lines of Python. Nothing leaves the
> cluster. The federated learning demo still runs, unchanged, at the same time.

That last sentence is a requirement, not a bonus. A feature that breaks the
existing headline is not done.

---

## How this is tested

Two layers, matching how this repository already works.

**Unit tests** — new. `tests/`, pytest, **completely offline**: no cluster, no
network, no Nomad. They read the files in this repository and assert things
about them. They are what makes "the arithmetic closes" a checked fact rather
than a comment. They run in seconds, so they run on every change.

```bash
bash scripts/run-tests.sh          # creates .venv-tests/, runs pytest
```

**Smoke tests** — the existing house style. `scripts/check-*.sh`, read-only,
run against the live thing, **checking content and not status codes**. That rule
is not decoration: the dashboard once served HTML labelled as a PNG with a 200,
and every naive check passed (see the header of `scripts/check-branding.sh`).

New files this plan adds:

```
tests/
  requirements.txt            pytest, pyyaml, python-hcl2
  conftest.py                 repo-root fixture, the measured cluster constants
  test_patches.py             every patch still applies to vendor/
  test_llm_job_template.py    the job template's resource budget closes
  test_vllm_catalogue.py      every offered model fits in 10.3 GB
  test_papi_mounts.py         every compose bind-mount source exists
  test_inventory.py           caios_llm is wired the way L1 says it is
scripts/
  run-tests.sh                unit tests
  check-llm-node.sh           L0/L1 — is the node real, does CUDA work
  check-llm-config.sh         L2  — does PAPI offer the tool, and our models
  check-llm-deploy.sh         L3  — deploy vllm, get a completion, delete
  check-llm-ui.sh             L4  — deploy both, log in, chat, delete
```

`test_papi_mounts.py` deserves a note. It exists because of D-29: Docker's
response to a missing bind-mount source is to **silently create an empty
directory**, which is how PAPI came to run healthily while trusting no CAIOS
certificate. This plan adds four new bind mounts. That failure mode is now a
test.

---

## Stage L0 — Verify node 6, and prove CUDA works  ·  half a day  ·  changes nothing

**Do this first and alone.** It is read-only, and it is what makes the next
stage's erase safe to approve.

**D-31 settles what the node is:** ours, unused, identical to the other five.
So L0 is no longer discovery — it is the verification that a claim about
hardware nobody has logged into yet is actually true, plus the one genuinely
open technical question (CUDA on a MIG-backed vGPU).

### Work

One SSH session, no writes. **The first login this node has ever had:**

```bash
ssh -i ~/.ssh/caios_cluster ubuntu@192.168.104.188 \
  'nvidia-smi --query-gpu=name,memory.total,memory.free,compute_cap,driver_version --format=csv; \
   nproc; free -g | head -2; lsblk; df -h /mnt; ls -A /mnt'
```

Confirming, against the other five: one `NVIDIA H100L-1-12C` with ~10565 MiB
free, 3 cores, ~34 GB RAM, a 125 GB `/dev/vdb` — and, the one that gates Stage
L1, **that `/mnt` holds nothing but `lost+found`.**

If the SSH key is not yet installed on this node — likely, since it has never
been used — `docs/ssh-setup.md` is the ten-minute fix, the same one the other
four needed.

Then the question that is not about the node at all, run on any GPU node,
because it is the one assumption that would sink the feature late:

```bash
docker run --rm --runtime=nvidia -e NVIDIA_VISIBLE_DEVICES=all \
  nvidia/cuda:12.4.0-base-ubuntu22.04 nvidia-smi -L
```

then the same with a real CUDA allocation rather than just `nvidia-smi`. A
MIG-backed vGPU can show up in `nvidia-smi` inside a container and still fail at
CUDA init — see R-18. `docs/progress.md` records `nvidia-smi` working inside a
workspace; it does not record a tensor being multiplied.

### Tests

**Unit** — none. Nothing has been written yet.

**Smoke** — `scripts/check-llm-node.sh`, read-only, run against `.188` and one
known-good node so the output can be compared side by side. It prints, and
asserts where it can: GPU name and usable framebuffer, core count, free RAM,
`/dev/vdb` presence and contents, egress to `huggingface.co` and `ghcr.io`, and
a CUDA tensor operation inside a container.

### What it found — run on 2026-08-19

**Complete.** It cleared the technical unknown it was written for, found a
cluster-wide defect that was fixed the same day, and confirmed node 6 is what
D-31 said it is.

**Done, on `caios_site_a`:**

- **CUDA computes on the MIG-backed vGPU.** `torch.cuda.is_available() → True`,
  device `NVIDIA H100L-1-12C MIG 1g.12gb`, capability **9.0**, a 1024×1024
  matmul agreeing with the CPU to 4.4e-4, and **bfloat16 works**. So the vGPU is
  not an obstacle, and upstream's `--dtype float16` is confirmed unnecessary.
- **The memory numbers CUDA reports are not the ones `nvidia-smi` reports.**
  `torch.cuda.mem_get_info()` gives **total 12100 MiB, free 10475 MiB** against
  `nvidia-smi`'s 12288 / 10565. vLLM sizes from the CUDA numbers, so those win:
  0.90 overshoots by 415 MiB, 0.85 leaves 190 MiB, **0.80 leaves 795 MiB**.
  R-06 confirmed, and the recommendation is now measured rather than predicted.
- **Blocker 5 found — see R-18.** A Nomad job with `device "gpu" { count = 1 }`
  gets a container where `nvidia-smi` shows the GPU and `torch.cuda` is `False`;
  the identical job without the stanza works. The device plugin allocates the
  parent device, and CUDA can only use the MIG instance. Confirmed four ways at
  the container level and twice through the real Nomad path. **This affects every
  GPU workload on the cluster, not just the LLM tool.**
- Egress to `huggingface.co` and `ghcr.io` works; 85 GB free on the data volume.

**Done, on node 6** (`192.168.104.188`, hostname `ai4eosc-6`) — first login it
has ever had. D-31 is confirmed by measurement:

| | node 6 | the three site nodes |
|---|---|---|
| cores | 3 | 3 |
| RAM | 34 GB | 34 GB |
| GPU | `NVIDIA H100L-1-12C`, 10565 MiB free, cc 9.0 | identical |
| driver | 580.105.08 | identical |
| MIG instances | 1 | 1 |
| egress to Hugging Face | yes | yes |

**And the gate for Stage L1: `/mnt` holds `lost+found` and nothing else.** Its
`/dev/vdb` is 125 GB of ext4 on the raw device with no partition table — the
shipped layout, exactly as `docs/llm-infrastructure.md` describes, and exactly
what has to be relaid.

**It is a bare node.** The NVIDIA driver is present (from the
`gpu-enabled-instance` snapshot), but there is no Docker, Nomad or Consul —
nothing has ever been provisioned on it. So the CUDA-in-container test cannot run
there yet; Stage L1 installs the container runtime, and the check is re-run
afterwards. CUDA compute is already proven on hardware identical in every
measured respect, so this is a formality rather than an open question.

Both checks are now scripts, so they are repeatable rather than a transcript:
`scripts/check-llm-node.sh` and `scripts/check-gpu-scheduling.sh`.

### Gate — passed 2026-08-19

- [x] A CUDA workload provably runs inside a container on a MIG-backed vGPU
- [x] The vLLM memory budget measured, not predicted
- [x] Cluster key installed on node 6
- [x] The node's specs match the other three, measured not assumed
- [x] **Its `/mnt` contents seen: `lost+found` only** — Stage L1 is safe to run
- [x] Bonus, not in the original gate: a cluster-wide GPU defect found and fixed

Deferred to after L1, because the node has no container runtime yet:
re-run `scripts/check-llm-node.sh 192.168.104.188` and confirm CUDA computes
there too.

**Commit:** `llm: measure node 6 and prove CUDA works on the vGPU`

---

## Stage L1 — Bring node 6 in as `caios_llm`  ·  half a day  ·  **destructive**

Settled by D-31. **This stage reformats `/dev/vdb` on node 6, erasing it.**
What that means, exactly what is and is not destroyed, and why the node cannot
be certified without it, is in `docs/llm-infrastructure.md` under *"What the
reformat actually does"*. Read that before approving this stage.

### Work

- `ansible/inventory/hosts.ini` — add `caios_llm ansible_host=192.168.104.188`
  to `consul_clients`, `nomad_gpu_clients` and `nomad_volume`, with
  `domain=pacs nomad_namespaces=caios batch=false` like the site nodes. The
  Ansible alias has no hyphen (gotcha 4).
- `ansible/inventory/host_vars/caios_llm.yml` — `nomad_client_meta:
  {status: test, role: llm}`. `status: test` is not optional: it is what
  `ai4-nomad_tests` flips to `ready`, and every job template requires it.
- `configs/papi/tools/ai4os-dev-env/nomad.hcl` — a new override adding a soft
  anti-affinity on `meta.role = llm`, so federated-learning workspaces prefer
  the three hospital nodes. Soft, so a dead hospital node does not block a
  workspace. This is R-14.
- ~~Bump `nomad_nvidia_plugin_version`~~ — **done on 2026-08-19**, ahead of this
  stage, because it was blocking every GPU workload on the cluster and not just
  node 6. `caios_llm` picks it up automatically when it joins, since it reads the
  same group var.
- Run, each limited to the one host, and **each shown to you before it runs**:
  `playbook-prepare-volumes.yml`, `playbook-nomad.yml`,
  `playbook-container-storage.yml`, `playbook-prepull-images.yml`.
- `scripts/run-cluster-tests.sh` to flip `meta.status=ready`.
- Confirm the new node reports the same device name as the other three,
  `NVIDIA H100L-1-12C MIG 1g.12gb` — the name changed with the plugin upgrade and
  patch `0009`'s allowlist depends on it.

> **The approval gate.** `playbook-prepare-volumes.yml` repartitions and
> reformats `/dev/vdb` as XFS, erasing it. Only that volume — the OS disk
> `/dev/vda` is untouched. The playbook **refuses to run** if `/mnt` holds
> anything other than `lost+found`, so the L0 gate above is a check and not the
> only line of defence. This is the same step the three site nodes went through
> on 2026-08-12.

### Tests

**Unit** — `tests/test_inventory.py`. Parses `hosts.ini` and the host vars and
asserts: `caios_llm` exists; its Ansible name has no hyphen; it is in
`nomad_gpu_clients` **and** `nomad_volume` (so that reformatting is a deliberate,
reviewable line in the inventory rather than an accident); `nomad_namespaces` is
`caios` and `domain` is `pacs`, because a mismatch in either produces jobs that
queue forever with no error anywhere; and `nomad_client_meta` still carries
`status: test`.

**Smoke** — `scripts/verify-cluster.sh` must now show **four** compute nodes
with `meta.status=ready`, `meta.type=compute`, `meta.namespace=caios` and
region `global`. `scripts/check-llm-node.sh` re-run against the joined node.

**`scripts/check-gpu-scheduling.sh` must still pass** once the fourth node
joins — it is the regression test for the plugin, and a node that joined with a
stale one would fail it.

**Regression, and this one matters more than the rest:** tear down and re-run
`scripts/deploy-fl-demo.sh`, then `--status`, and confirm the three workspaces
still land on `caios_site_a/b/c` and not on `caios_llm`. This is the check that
proves the new node did not quietly damage the existing headline feature.

### What it found — run on 2026-08-19

**Complete.** Node 6 is `caios-wn-gpu-3`, certified, and the LLM job places.

```
NAME             STATUS  ELIGIBLE  meta.status  meta.type  meta.tags  meta.role
caios-wn-gpu-0   ready   eligible  ready        compute    gpu        -
caios-wn-gpu-1   ready   eligible  ready        compute    gpu        -
caios-wn-gpu-2   ready   eligible  ready        compute    gpu        -
caios-wn-gpu-3   ready   eligible  ready        compute    gpu        llm

4 compute node(s) schedulable.
```

- `/dev/vdb1`, XFS with `prjquota`, mounted at `/mnt/data`. The "box" now has a
  drawer 1.
- The GPU fingerprints as `NVIDIA H100L-1-12C MIG 1g.12gb` at 10564 MiB — **the
  plugin fix propagated by itself**, straight from the group var, with no extra
  step. That is the payoff for fixing it in Ansible rather than by hand.
- CUDA computes there: capability 9.0, bfloat16, same 12100/10475 MiB as the
  other three.
- **`nomad job plan` on the LLM job: "All tasks successfully allocated."** It
  reported "Dimension cpu exhausted on 2 nodes" before this stage.
- The four federated-learning deployments came through untouched.

**Two findings, both of which changed the plan.**

**1. A garbage collector was deleting the pre-pulled images.** `docuum` runs as a
Nomad system job on every compute node with upstream's threshold of 50 GB. The
full pre-pull set is 67.9 GB — because `vllm/vllm-openai` is **30.8 GB on disk**,
not the 10.5 GB compressed figure this plan originally quoted. So the pre-pull
playbook fetched eleven images, reported success for all eleven, and six were
deleted before it finished. Fixed by `nomad-jobs/docuum.hcl` at 80 GB, with
`ansible/playbook-docuum.yml` to reapply it and a check in
`scripts/verify-cluster.sh` because re-running the Nomad role reverts it. See
R-10.

**2. The anti-affinity this plan proposed does not work.** Measured rather than
assumed: three dev-env-shaped jobs land on `gpu-0, gpu-1, gpu-3` — including the
LLM host — and adding a soft anti-affinity on `meta.role = llm` changed nothing.
Nomad's spread score for an idle node outweighs a `-100` affinity. **Deploying
the LLM first does work**, measured the same way, and costs nothing. The
332-line dev-env template copy is therefore not being carried. See R-14.

### Gate — passed 2026-08-19

- [x] Four compute nodes ready; `caios_llm` carries `meta.role=llm`
- [x] CUDA computes on the new node
- [x] `scripts/check-gpu-scheduling.sh` still healthy with four nodes
- [x] The LLM job places (`nomad job plan`)
- [x] The four FL deployments survived, on their original nodes
- [x] Placement behaviour measured, and the ordering fix documented in
      `scripts/deploy-fl-demo.sh`

**Commit:** `cluster: node 6 joins as caios_llm, the LLM host`

---

## Stage L2 — Make PAPI able to deploy it  ·  one day  ·  the substantial stage

All four blockers, no deployment yet. Everything here is testable offline, which
is why it is one stage and not four.

### Work

**One patch.** `patches/ai4-papi/0009-llm-gpu-models.patch`, pinned to `e80a2b7`,
doing two things:

- Replace the `"Tesla T4" not in models` gate with a list read from
  `LLM_GPU_MODELS`, **defaulting to `Tesla T4`** so that unset behaves exactly
  as upstream. Same shape as `0001` (Keycloak URL), `0002` (Vault address) and
  `0007` (catalogue repo) — a value that should have been configuration and is
  not.
- Fix `"openwebui"` → `"open-webui"` in the type check at line 575, which is
  why a standalone UI deploys with no administrator (R-08). Report upstream.

**Four configuration files**, bind-mounted over upstream's the way
`ai4os-dev-env/user.yaml` and `ai4os-federated-server/user.yaml` already are:

`configs/papi/tools/ai4os-llm/nomad.hcl`
: The job template. Device constraint removed — one GPU model in the cluster
  constrains nothing. Resources rebalanced so the budget closes on a 3-core
  node (the arithmetic is in `docs/llm-infrastructure.md`). Images pinned to
  `vllm/vllm-openai:v0.27.1` and `ghcr.io/open-webui/open-webui:v0.11.0`, with
  `force_pull = false` (R-10). Both helper tasks switched from the public HTTPS URL to
  `${NOMAD_ADDR_vllm}` / `${NOMAD_ADDR_ui}` over plain HTTP inside the
  allocation — R-05, the day-eater. A host bind mount for the Hugging Face cache
  so a redeploy does not re-download 4.5 GB (R-11). `shm_size` set explicitly.

`configs/papi/tools/ai4os-llm/user.yaml`
: CAIOS defaults and descriptions. The `type` field keeps all three options.

`configs/papi/vllm.yaml`
: The curated model list — nine models that fit in 10.3 GB, down from
  upstream's thirteen: two whose weights leave no room for a KV cache, and both
  gated Llama variants, which would need a Hugging Face token typed into a form
  that stores it in clear text (R-09). `--dtype float16`
  dropped throughout: it exists because a T4 is compute capability 7.5, and ours
  is 9.0, so the models run in their native bfloat16. Every entry gains
  `--gpu-memory-utilization 0.80` (R-06).

`compose/docker-compose.yml`
: Four bind mounts and `LLM_GPU_MODELS`, each with the comment explaining why —
  the file's existing convention.

Plus `ansible/playbook-prepull-images.yml`: add the two pinned images and
`python:slim-bullseye`, which the helper tasks use and which is missing today.

### Tests

**Unit** — the bulk of the new test suite, all offline.

`test_patches.py`
: Every patch in `patches/`, not only the new one, still applies to `vendor/`
  (`git apply --check`). Turns upstream drift into a failing test instead of a
  demo-day surprise. Then assert on the patched output in `build/ai4-papi/`:
  `LLM_GPU_MODELS` is read, `Tesla T4` survives only as a default, and
  `open-webui` appears in the type check.

`test_llm_job_template.py`
: Substitute the template with a representative mapping, parse the result, and
  assert the things that would otherwise be discovered by a job pending
  forever:
  - no `Tesla T4` anywhere;
  - dedicated `cores` ≤ 3, **and** `cores × 2000 + Σ cpu shares ≤ 6000` — the
    subtle one, because reserving a core removes its MHz from the shared pool;
  - Σ task memory ≤ 30000 MB;
  - exactly one GPU device requested;
  - every image is pinned — no `:latest`, no `:main`;
  - no `https://` URL in either helper task, so R-05 cannot come back.

`test_vllm_catalogue.py`
: Every model has the seven keys the dashboard cards expect. Every model's args
  set `--gpu-memory-utilization` and it is ≤ 0.85. No model sets
  `--dtype float16`. And a fit check: `weights + 1.2 GB overhead < 10.3 GB`,
  against weight sizes recorded in the test fixture, so adding an oversized
  model to the list fails the suite rather than the deployment.

`test_papi_mounts.py`
: Every host-side path in every `compose/docker-compose.yml` bind mount exists
  on disk. This is D-29 as a test.

**Smoke** — `scripts/check-llm-config.sh`, after `docker compose build papi &&
up -d`:

- `GET /v1/catalog/tools` includes `ai4os-llm`;
- `GET /v1/catalog/tools/ai4os-llm/config?vo=vo.caios.ca` returns **our** nine
  models and not upstream's thirteen — a content check, so a stale mount is
  caught rather than a 200 being accepted as success;
- the rendered job passes `nomad job validate`, which is the cheapest possible
  proof that Nomad will accept it, and costs nothing to run;
- PAPI's logs contain no startup warnings about the new mounts.

### What it found — run on 2026-08-19

**Complete.** All four blockers addressed, 31 unit tests and the smoke test
green.

**The unit tests were checked against upstream, not just against ourselves.**
Pointing the same nine assertions at `vendor/ai4-papi/etc/tools/ai4os-llm/nomad.hcl`
fails all nine — 8 cores on a 3-core node, 32 GB on a 30 GB node, the Tesla T4
constraint, the moving image tags, `force_pull`, the HTTPS helper URLs, the
missing `shm_size`. A suite that passes on both the fixed and the broken version
tests nothing, so this is the check that the checks are real.

**The live API now serves our configuration**, verified field by field rather
than by status code:

```
ai4os-llm is in the tools catalogue
serving our 9 models, not upstream's thirteen
form defaults to Qwen/Qwen3.5-2B
deployment types: ['both', 'vllm', 'open-webui']
PAPI allows: NVIDIA H100L-1-12C MIG 1g.12gb
   cluster has: NVIDIA H100L-1-12C MIG 1g.12gb
nomad job validate: Job validation successful
```

**And the argument for Stage L1 stopped being an argument.** `nomad job plan`
against the live cluster:

```
- WARNING: Failed to place all allocations.
    * Dimension "cpu" exhausted on 2 nodes
    * Dimension "cores" exhausted on 1 nodes
```

The job is correct and the cluster has no room for it while the three
federated-learning workspaces hold cores on all three compute nodes. **Node 6 is
not a preference, it is a requirement** — this is what `docs/llm-infrastructure.md`
predicted from arithmetic, now measured.

**A latent bug found on the way.** `scripts/apply-patches.sh` does `rm -rf build/<repo>`,
and `build/ai4-dashboard` holds root-owned files from the Docker build in
`scripts/build-dashboard.sh`. The `rm` failed with "Permission denied", and
because the script runs under `set -e` everything after it was skipped — so the
dashboard was being left unpatched while `ai4-papi` looked fine. Fixed, and it is
the same shape of fault as D-29: a failure that presents as silence.

### Gate — passed 2026-08-19

- [x] `bash scripts/run-tests.sh` green — 31 tests
- [x] The suite demonstrably fails against upstream's template
- [x] `bash scripts/check-llm-config.sh` green
- [x] `nomad job validate` accepts the rendered job
- [ ] The dashboard's deploy form opens in a browser and lists nine models
      — needs a human with a browser, like every other UI check in this project

**Commit:** `llm: unblock the tool on CAIOS hardware`

---

## Stage L3 — First real deployment, vLLM only  ·  half a day

The engine alone. No UI to log into, so a failure is unambiguous.

### Work

Deploy with `type: vllm` through PAPI, watch the allocation, and read the two
numbers vLLM prints that settle the sizing predictions: the KV cache size, and
the time to first ready. Then call it.

```bash
curl -sk -H "Authorization: Bearer $TOKEN" \
  https://vllm-$UUID.pacs-deployments.$EDGE.sslip.io/v1/chat/completions \
  -d '{"model":"Qwen/Qwen3.5-2B","messages":[{"role":"user","content":"Hello"}]}'
```

Then delete it and deploy the same model again, to prove the Hugging Face cache
mount works and to measure the difference.

### Tests

**Unit** — none new; the suite from L2 still has to pass.

**Smoke** — `scripts/check-llm-deploy.sh`, the first end-to-end script:
deploy → poll until `running` with a timeout → assert `/v1/models` names the
model we asked for → assert a chat completion comes back with non-empty content
→ **report tokens per second and total startup time** → delete, and assert it is
gone. Idempotent and self-cleaning, so it can run in a loop.

The throughput number is not vanity. It decides whether the demo can afford a
live chat or has to show a pre-warmed one.

### What it found — run on 2026-08-19

**Complete. A model deployed through the dashboard's own API answered a question
on CAIOS hardware.** The 405 that started this work is gone:
`POST /v1/deployments/tools?tool_name=ai4os-llm` returns `{"status":"success"}`.

| measurement | value |
|---|---|
| deploy → `/v1/models` answering | **175–204 s** |
| of which weight download (cold cache) | ~22 s |
| sustained generation | **97.8 tok/s** over 300 tokens |
| GPU memory used | **8963 MiB**, 1603 MiB still free |
| placed on | `caios-wn-gpu-3` — the affinity worked |

Everything L2 configured is confirmed live, from PAPI's own view of the
deployment: `vllm/vllm-openai:v0.27.1` (pinned), `--gpu-memory-utilization 0.80`,
`cpu_num 2`, `gpu_num 1`, `memory_MB 12000`.

**R-05 is proven, not just reasoned about.** `check_vllm_startup` terminated with
**exit code 0** at +175 s. Upstream's version would have died on our self-signed
CA and taken the allocation with it.

**R-06 is confirmed by a running model.** 8963 MiB used against a 9680 MiB
budget. vLLM's own default of 0.90 would have asked for 10890 MiB, which is more
than the card had free.

**Two corrections to this plan's own claims.**

**1. The weight cache does not make redeployment quick.** R-11 said "seconds". It
saves **22 s of ~190 s** — cold 197 s, warm 175 s, alloc creation to health check
passing. The dominant cost is `torch.compile` and capturing 86 CUDA graphs on a
16-SM slice, which happens every time. The cache is still worth having for
bandwidth and for not depending on Hugging Face, but the demo must pre-deploy
regardless.

**2. The default model returned an empty `content` field.** See R-20 — the
biggest find of the stage, and the reason the smoke test asserts a non-empty
completion rather than a 200. Upstream's `--reasoning-parser qwen3` put the whole
answer in a `reasoning` field, so every ordinary OpenAI client would have read
`content` and got `None`. Fixed by dropping the parser from the two
general-purpose Qwen entries, verified by experiment rather than by guessing
between two candidate causes.

### Gate — passed 2026-08-20

- [x] A completion returns, from a model running on `caios_llm`'s GPU
- [x] Startup time and tokens/sec recorded
- [x] Cache benefit measured — and the plan's claim about it corrected
- [x] `scripts/check-llm-deploy.sh` runs the whole cycle unattended and cleans up
- [x] *(added during the stage)* The default model returns usable `content` to a
      plain OpenAI request — see R-20
- [x] **The model list checked against what actually loads.** All nine deployed
      and answered — `demo/llm/README.md` has the table. Nothing was trimmed
      because nothing failed.

**What the sweep settled.** No model ran out of GPU memory, including
`granite-4.1-3b`, which this repository's own config comments had flagged as
"the tightest model we offer; if Stage L3 finds it will not load, drop it". It
loads in 111 s. The memory arithmetic was sound, and the warning was wrong in
the safe direction — which only testing could show.

Two smaller findings worth carrying into the demo script: the **default is the
slowest model on the list** (Qwen3.5-2B at 182 s against LFM2.5-1.2B-Instruct at
81 s), and throughput varies more than size predicts (18 to 129 tok/s).

The two thinking models keep their reasoning parser and so answer into
`reasoning` rather than `content`. Both alternatives were measured; without the
parser they return raw thinking with a literal `<think>` tag, which reads worse
to a person than an empty field reads to a script. Kept, with the trade-off
written into their catalogue descriptions — and flagged for Stage L4 to confirm
Open WebUI renders them properly. If it does not, drop them: seven uniform
models beat nine with two that need explaining.

**Commit:** `llm: first vLLM deployment serving on CAIOS`

---

## Stage L4 — The full thing, with Open WebUI  ·  half a day

### Work

Deploy `type: both`. This is where R-05 gets its real test: `check_vllm_startup`
must block Open WebUI until the model is loaded, and `create-admin` must claim
the admin account. Then open it in a browser, log in, and have a conversation.

A browser is not optional here. `docs/progress.md` records three faults that
only appeared when the dashboard was opened in a real browser and that no
programmatic check had caught — streamed responses through Traefik are exactly
the kind of thing that behaves differently under `curl`.

### Tests

**Unit** — none new.

**Smoke** — `scripts/check-llm-ui.sh`: deploy `both` → assert the UI hostname
serves **Open WebUI's HTML and not the dashboard's** (content, per the house
rule) → assert `/api/config` reports authentication enabled and signup closed →
log in as the admin the job created and assert a token comes back → send a chat
turn through the UI's own API and assert the reply is non-empty → delete.

**Manual, and written into the runbook:** open it in a browser, confirm replies
stream token by token rather than arriving in one block. Server-sent events
through Traefik is the failure this catches.

### Gate

- [ ] Chat works in a browser, streaming, over HTTPS
- [ ] The admin account is the one the deployment created, and signup is closed
- [ ] `docs/runbook.md` gains an LLM section, organised by symptom

**Commit:** `llm: Open WebUI end to end, admin and streaming verified`

---

## Stage L5 — Model cards from our catalogue, not GitHub  ·  half a day

### Work

`patches/ai4-dashboard/0002-vllm-catalogue-url.patch` — replace the hardcoded
`raw.githubusercontent.com/ai4os/ai4-papi/.../etc/vllm.yaml` with a relative
asset path. `scripts/build-dashboard.sh` stages `configs/papi/vllm.yaml` into
the image as that asset, so PAPI and the dashboard read one file.

This is R-07, and it is the second dashboard patch. Like the first (`0001`, the
PACS Lab logo) it cannot be configuration: the URL is a string literal in a
service class.

### Tests

**Unit** — assert the built bundle in `build/ai4-dashboard/` contains no
`raw.githubusercontent.com`, and that the staged asset parses as YAML with the
same model keys as `configs/papi/vllm.yaml`. One file, two consumers, one test
that they agree.

**Smoke** — extend `scripts/check-branding.sh`, which already exists to catch
exactly this class of leak: the served dashboard must reference no third-party
host for its model list, and `/assets/config/vllm.yaml` must return YAML naming
our models — content, not a status code.

**Manual:** the LLM catalogue page in the marketplace shows nine cards with
descriptions, and the Hugging Face token field behaves correctly — with the
gated Llama models dropped from our list, it should never become required.

### Gate

- [ ] No third-party fetch from the dashboard for model metadata
- [ ] Cards and dropdown agree, because they read the same file

**Commit:** `dashboard: read the LLM catalogue from CAIOS, not from GitHub`

---

## Stage L6 — Make it a demo  ·  half a day

### Work

- `docs/demo-script.md` — a new beat. The natural place is after Beat 6 ("Serve
  it as an API"), because the argument is the same one escalated: *the platform
  that trains across hospitals without moving data also answers questions
  without sending them to a vendor.* Target 3 minutes.
- **Deploy the LLM first**, before the FL workspaces, and say so in the script's
  "Before you start". It hides the two-to-five-minute model load behind the rest
  of the demo, and it makes spread-mode scheduling place the workspaces on the
  hospital nodes without relying on the anti-affinity alone (R-14).
- The beat that ties both features together: a notebook in a CAIOS dev
  environment calling the deployment's OpenAI endpoint in four lines. It shows
  this is infrastructure, not a chat toy.
- `docs/decisions.md`, `docs/feature-coverage.md`, `docs/infrastructure.md`,
  `docs/progress.md`, `CLAUDE.md` — updated together.

### Tests

**Unit** — the full suite green from a clean checkout.

**Smoke** — all four `check-llm-*.sh` green from a **cold start**: no
deployments running, images pre-pulled, nothing warm. That is demo-day
conditions, and it is the only run that means anything.

**Rehearsal** — the new beat timed. `docs/demo-script.md` is currently 22
minutes; this should not push it past 26.

### Gate

- [ ] The beat rehearses inside its time budget, twice
- [ ] LLM and federated learning demonstrated in the same session on the same
      cluster, neither degrading the other

**Commit:** `docs: the LLM beat, and what Stage 6 changed`

---

## Timeline

| Stage | Work | Days | Can start |
|---|---|---|---|
| L0 | Verify node 6, prove CUDA works | 0.5 | **done 2026-08-19** |
| L1 | Join it as `caios_llm` | 0.5 | **done 2026-08-19** |
| L2 | Patch and configure PAPI | 1.0 | **done 2026-08-19** |
| L3 | First vLLM deployment | 0.5 | **done — 9/9 models verified** |
| L4 | Open WebUI end to end | 0.5 | **next** |
| L5 | Dashboard catalogue | 0.5 | After L2 |
| L6 | Demo, docs, rehearsal | 0.5 | After L4 + L5 |
| | | **4.0** | |

L2 is the long pole and depends on nothing, so with two engineers one starts L0
while the other starts L2, and the calendar cost is about **2.5 days**.

---

## Decisions

**Settled on 2026-08-19, in `docs/decisions.md`:**

- **D-31** — the sixth instance becomes `caios_llm`, a dedicated LLM host. It is
  ours and identical to the other five. No new instances are needed.
- **D-32** — the LLM catalogue is upstream's models, used as they are. No
  fine-tuning. The claim this feature supports is privacy, not medical
  competence, and the demo wording is bound by that.

**Proposed, to be appended as D-33…D-36 once the implementation confirms them.**
They are listed here rather than there because none is settled until the code
that depends on them exists.

**D-33 — GPU model allowlists are configuration, not source.**
Patch `0009` reads `LLM_GPU_MODELS` and defaults to upstream's `Tesla T4`. The
Nomad-side device constraint is dropped entirely: with one GPU model in the
cluster it constrains nothing and can only go stale.

**D-34 — Job resource budgets are asserted by a test, not by a comment.**
Upstream's LLM job asks for 8 cores on 3-core nodes. The failure mode is a job
that pends forever with no error. `test_llm_job_template.py` makes the budget a
checked fact, including the `cores`-versus-shares trap.

**D-35 — Container images in job templates are pinned, and never force-pulled.**
`vllm/vllm-openai:latest` is 10.5 GB and moves. Pinned tags plus pre-pulling
turn a fifteen-minute silence into two minutes, and stop an overnight upstream
release from breaking a rehearsed demo.

**D-36 — In-allocation health checks talk to the allocation, not to Traefik.**
Upstream's helper tasks call their own public HTTPS URL, which cannot work
against a private CA. Using `${NOMAD_ADDR_*}` removes DNS, TLS and Traefik from
the startup path and tests the thing actually being waited for.

---

## Open questions

**Q-09 — Answered on 2026-08-19. See D-32.** Upstream's models, used as they
are. No fine-tuning, and the demo makes the privacy claim only.

**Q-11 — Answered on 2026-08-19. See D-31.** The node is ours and identical to
the other five. Stage L0 verifies rather than discovers.

**Q-10 — Should the LLM stay running between demos?** *Still open.*
A running vLLM holds a GPU indefinitely. Leaving it up makes the demo instant;
tearing it down frees a GPU and proves the deploy flow live. **Assumption:**
tear down between rehearsals, deploy live at the start of the real demo and come
back to it — which is what the script's ordering already does. Nothing depends
on this before Stage L6.
