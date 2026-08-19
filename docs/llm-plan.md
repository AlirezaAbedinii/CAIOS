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

Blocker 3 is the real one. The reference deployment has 64–86 vCPU per node; we
have three. Blocker 4 is the one that would have eaten a day, because it fails
with a traceback that never mentions certificates.

**None of them need a fork.** One patch — in the same shape as the three we
already carry — plus configuration files bind-mounted over upstream's, which is
the mechanism already used for two other tools.

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

## Stage L0 — Find out what node 6 is  ·  half a day  ·  changes nothing

**Everything downstream branches here, and nothing else does.** Do this first
and alone.

`192.168.104.188` has been in `docs/infrastructure.md` since day one as "the
sixth instance, deliberately left out until we know what it is". We now have a
use for it, so we find out.

### Work

Four questions, one SSH session, no writes:

```bash
ssh -i ~/.ssh/caios_cluster ubuntu@192.168.104.188 \
  'nvidia-smi --query-gpu=name,memory.total,memory.free,compute_cap,driver_version --format=csv; \
   nproc; free -g | head -2; lsblk; df -h /mnt; ls -la /mnt'
```

- **Does it have a GPU**, and is it the same `H100L-1-12C` as the others?
- **How many cores and how much RAM?** Three and 34 GB is expected.
- **Is there a `/dev/vdb`**, and — the destructive question — **does it hold
  anything?** Stage L1 reformats it.
- **Is it the jumpserver?** If OpenVPN or a bastion service is running on it,
  it stays out of the cluster and the plan takes its fallback path.

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

### Gate

- [ ] Node 6 identified, and its `/mnt` contents seen by a human
- [ ] A CUDA workload provably runs inside a container on a MIG-backed vGPU
- [ ] Which of the three infrastructure paths we are on is written down

**Commit:** `llm: measure node 6 and prove CUDA works on the vGPU`

---

## Stage L1 — Bring node 6 in as `caios_llm`  ·  half a day  ·  **destructive**

Only if L0 says it is a GPU node. Otherwise skip to L2 and accept that the LLM
and FL demos cannot run at the same time.

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
- Run, each limited to the one host, and **each shown to you before it runs**:
  `playbook-prepare-volumes.yml`, `playbook-nomad.yml`,
  `playbook-container-storage.yml`, `playbook-prepull-images.yml`.
- `scripts/run-cluster-tests.sh` to flip `meta.status=ready`.

> **The approval gate.** `playbook-nomad.yml` repartitions and reformats
> `/dev/vdb` as XFS, erasing it. The exact commands are printed and nothing runs
> until you say go. This is the same step the three site nodes went through.

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

**Regression, and this one matters more than the rest:** tear down and re-run
`scripts/deploy-fl-demo.sh`, then `--status`, and confirm the three workspaces
still land on `caios_site_a/b/c` and not on `caios_llm`. This is the check that
proves the new node did not quietly damage the existing headline feature.

### Gate

- [ ] Four compute nodes ready; `caios_llm` carries `meta.role=llm`
- [ ] The FL demo still places one workspace per hospital node
- [ ] `docs/infrastructure.md` updated — it currently says "five nodes"

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

### Gate

- [ ] `bash scripts/run-tests.sh` green
- [ ] `bash scripts/check-llm-config.sh` green
- [ ] The dashboard's deploy form opens and lists our nine models

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

### Gate

- [ ] A completion returns, from a model running on `caios_llm`'s GPU
- [ ] Startup time and tokens/sec recorded in `docs/progress.md`
- [ ] Second deployment of the same model is measurably faster (cache works)
- [ ] The model list trimmed to what actually loaded

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
| L0 | Identify node 6, prove CUDA works | 0.5 | Now |
| L1 | Join it as `caios_llm` | 0.5 | After L0 |
| L2 | Patch and configure PAPI | 1.0 | **Now — independent of L0/L1** |
| L3 | First vLLM deployment | 0.5 | After L1 + L2 |
| L4 | Open WebUI end to end | 0.5 | After L3 |
| L5 | Dashboard catalogue | 0.5 | After L2 |
| L6 | Demo, docs, rehearsal | 0.5 | After L4 + L5 |
| | | **4.0** | |

L2 is the long pole and depends on nothing, so with two engineers one starts L0
while the other starts L2, and the calendar cost is about **2.5 days**.

---

## Decisions this plan proposes

To be appended to `docs/decisions.md` as D-31…D-35 once you approve them. They
are listed here rather than there because none of them is settled yet.

**D-31 — Node 6 becomes `caios_llm`, a dedicated LLM host.**
The tool needs a nearly empty 3-core node; borrowing a hospital node would make
the LLM and FL demos mutually exclusive. No new instances are required.

**D-32 — GPU model allowlists are configuration, not source.**
Patch `0009` reads `LLM_GPU_MODELS` and defaults to upstream's `Tesla T4`. The
Nomad-side device constraint is dropped entirely: with one GPU model in the
cluster it constrains nothing and can only go stale.

**D-33 — Job resource budgets are asserted by a test, not by a comment.**
Upstream's LLM job asks for 8 cores on 3-core nodes. The failure mode is a job
that pends forever with no error. `test_llm_job_template.py` makes the budget a
checked fact, including the `cores`-versus-shares trap.

**D-34 — Container images in job templates are pinned, and never force-pulled.**
`vllm/vllm-openai:latest` is 10.5 GB and moves. Pinned tags plus pre-pulling
turn a fifteen-minute silence into two minutes, and stop an overnight upstream
release from breaking a rehearsed demo.

**D-35 — In-allocation health checks talk to the allocation, not to Traefik.**
Upstream's helper tasks call their own public HTTPS URL, which cannot work
against a private CA. Using `${NOMAD_ADDR_*}` removes DNS, TLS and Traefik from
the startup path and tests the thing actually being waited for.

---

## Open questions

**Q-09 — Is a medically fine-tuned model wanted, and if so which one?**
Every model in the catalogue is general-purpose. The defensible claim is
privacy — *your model, your hardware, your prompts never leave* — not medical
competence. Adding a clinical model is one line in `configs/papi/vllm.yaml` plus
a fit check against 10.3 GB, but somebody has to name a model they are willing
to stand behind in front of reviewers. **Assumption if unanswered:** ship the
general-purpose catalogue and make the privacy claim only.

**Q-10 — Should the LLM stay running between demos?**
A running vLLM holds a GPU indefinitely. Leaving it up makes the demo instant;
tearing it down frees a GPU and proves the deploy flow live. **Assumption:**
tear down between rehearsals, deploy live at the start of the real demo and come
back to it — which is what the script's ordering already does.

**Q-11 — Does node 6 have a role nobody has told us about?**
It has been idle since day one. If it is the jumpserver or belongs to another
group, L0 finds out before anything is touched. **Assumption:** it is a spare
identical to the other five.
