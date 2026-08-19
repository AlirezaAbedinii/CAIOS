# LLM deployment — infrastructure

What the hardware actually is, what fits on it, and what has to change. The
staged work is in `docs/llm-plan.md`; the things that can go wrong are in
`docs/llm-risks.md`.

Everything below was **measured on the live cluster on 2026-08-19**, not read
off a spec sheet. Where a number differs from what an earlier document assumed,
the measured one wins and the earlier document is corrected.

---

## The answer to "do we need more instances?"

**No. One idle instance is enough, and it is the one we already have.**

`192.168.104.188` — the sixth instance, deliberately left out of the cluster
since day one because nobody had told us what it was — becomes `caios_llm`, a
fourth Nomad GPU compute client dedicated to language-model serving.

That assumes it is a GPU node like the other five. **This has not been
verified**, because it has never been logged into. Verifying it is Stage L0 of
the plan and takes about ten minutes. There are three outcomes:

| If node 6 is… | Then |
|---|---|
| A GPU node like the others | It becomes `caios_llm`. Plan proceeds unchanged. **Expected case.** |
| A CPU-only node | It hosts Open WebUI only; vLLM has to share a hospital node, and the LLM and FL demos can no longer run at the same time. |
| The jumpserver | It stays out. Same fallback as above, and a seventh instance becomes worth requesting. |

A **seventh** instance is not needed for this feature. It would only buy two
things, neither of them on the critical path: a hot spare if a node fails, and
— at ≥72 GB RAM — the CVAT annotation tool that has been deferred since D-16.

---

## The GPU, measured

Every node reports one device named `NVIDIA H100L-1-12C`. That name is an
NVIDIA vGPU profile, and it is worth decoding because almost every sizing
decision follows from it.

```
$ nvidia-smi -L
GPU 0: NVIDIA H100L-1-12C (UUID: GPU-db300f68-...)
  MIG 1g.12gb  Device 0: (UUID: MIG-f90f1469-...)
```

| Property | Value | Why it matters |
|---|---|---|
| Virtualization mode | **VGPU**, NVIDIA Virtual Compute Server | The guest sees a whole device; the host does the slicing. |
| MIG mode | **Enabled**, one `1g.12gb` instance | We hold 1/7 of an H100 NVL, not a whole one. |
| **Multiprocessor count** | **16** | Out of 132 on a full H100 NVL. This is the compute budget. |
| Framebuffer, nominal | 12288 MiB | What the profile name promises. |
| **Framebuffer, usable** | **10565 MiB** | 1724 MiB goes to ECC and vGPU overhead. **This is the number that matters.** |
| Compute capability | **9.0** (Hopper) | bfloat16, FP8 and FlashAttention-3 all supported. |
| Driver | 580.105.08, CUDA 13.0 | Recent. No CUDA-version blocker for any current vLLM image. |
| ECC | Enabled | Not optional on vGPU, and it is where most of the 1724 MiB goes. |

### Two consequences that shape everything

**1. We have less VRAM than upstream assumes, not more.** The whole AI4OS LLM
tool is written for a Tesla T4 with **16 GB**. We have **10.3 GB usable**. Every
piece of upstream's model tuning — context lengths, which models are offered at
all — is calibrated for a card with 55% more memory than ours. Upstream's
guidance is not a floor we clear comfortably; it is a ceiling we are under.

**2. Compute capability 9.0 is a genuine upgrade over a T4's 7.5.** Upstream
passes `--dtype float16` to every model for one reason, stated in a comment at
the top of `etc/vllm.yaml`: *"bfloat16 is only supported in GPUs with compute
capability +8.0 (NVIDIA T4 has 7.5)"*. That constraint does not apply to us. We
can run models in their native bfloat16, which is what they were trained in and
what avoids the overflow behaviour fp16 can show on models trained in bf16.

So the trade against the reference platform is: **less memory, better maths.**
Roughly T4-class throughput from 16 SMs of Hopper, on faster memory, with a
smaller framebuffer.

---

## What fits on 10.3 GB

vLLM's memory has three consumers: model weights, a fixed overhead (CUDA
context, compiled graphs, activation peaks — budget ~1.2 GB), and whatever is
left becomes KV cache, which is what determines how long a conversation can get
and how many people can chat at once.

With `--gpu-memory-utilization 0.80` the allowance is **9830 MiB ≈ 10.3 GB**.
Weight sizes below are the real `.safetensors` totals from the Hugging Face API,
measured 2026-08-19.

| Model | Weights | KV budget left | Verdict |
|---|---|---|---|
| `LFM2.5-VL-450M` | 0.90 GB | ~8.2 GB | Comfortable |
| `Qwen3.5-0.8B` | 1.75 GB | ~7.4 GB | Comfortable |
| `LFM2.5-1.2B-Instruct` / `-Thinking` | 2.34 GB | ~6.8 GB | Comfortable |
| `LFM2.5-VL-1.6B` | 3.19 GB | ~5.9 GB | Comfortable |
| `DeepSeek-R1-Distill-Qwen-1.5B` | 3.55 GB | ~5.6 GB | Comfortable |
| **`Qwen3.5-2B`** | **4.55 GB** | **~4.6 GB** | **Comfortable — the demo default** |
| `Ministral-3-3B-Instruct-2512` | 4.67 GB | ~4.4 GB | Comfortable |
| `Llama-3.2-3B` / `-Instruct` | 6.43 GB | ~2.7 GB | Tight; also **gated** (needs an HF token) |
| `granite-4.1-3b` | 6.81 GB | ~2.3 GB | Tight — cap context at 8K |
| `Ministral-3-3B-Reasoning-2512` | 7.70 GB | ~1.4 GB | Very tight — expect failures |
| `granite-vision-4.1-4b` | 7.99 GB | ~1.1 GB | Very tight — expect failures |

**Recommended curated list: nine models, down from upstream's thirteen.**
Everything from `LFM2.5-VL-450M` down to `Ministral-3-3B-Instruct` (eight), plus
`granite-4.1-3b` at a reduced context length. Four are dropped:

- `Ministral-3-3B-Reasoning-2512` and `granite-vision-4.1-4b`, because 7.7 and
  8.0 GB of weights leave no usable KV cache in a 10.3 GB budget;
- both `Llama-3.2-3B` variants, because they are **gated** — a demo that needs a
  Hugging Face token typed into a form which stores it in clear text in the
  Nomad job (R-09) is a worse demo than one that does not.

The arithmetic is a *prediction*, not a measurement. Stage L3 replaces it with
the number vLLM prints at startup ("GPU KV cache size: N tokens"), and the model
list gets trimmed to what actually loaded.

---

## The node, measured

All six instances appear identical. Measured on `caios-wn-gpu-0`:

| | |
|---|---|
| CPU | **3 cores** (Nomad: `ReservableCpuCores [0,1,2]`, 6000 MHz total) |
| RAM | 35068 MB, of which Nomad reserves 4096 → **~30 GB schedulable** |
| Disk | 125 GB volume, containerd root moved onto it |
| GPU | 1 × `NVIDIA H100L-1-12C` |

### Why the tool cannot possibly schedule today

Upstream's `etc/tools/ai4os-llm/nomad.hcl` asks for:

```hcl
task "vllm"        { resources { cores = 4  memory = 16000 } }
task "open-webui"  { resources { cores = 4  memory = 16000 } }
```

**Eight dedicated CPU cores and 32 GB of RAM, on nodes with three cores and
30 GB schedulable.** The reference deployment has 64–86 vCPU per node; we have
three. This job cannot be placed on any node in this cluster and never could
have been — it would sit in `pending` with `Dimension "cores" exhausted`
forever. The GPU-model error the tool currently returns is simply the check
that fires first.

### What it has to become

There is a trap in the fix. Nomad's `cores` reserves whole CPUs *and removes
their share of the MHz pool*. Reserve all three cores on a 6000 MHz node and
there is **0 MHz left** for the two small helper tasks, so the job still will
not place. The tasks have to mix `cores` (for the workload) with `cpu` shares
(for the helpers).

| Task | Upstream | CAIOS | Reasoning |
|---|---|---|---|
| `vllm` | `cores = 4`, 16000 MB | `cores = 2`, 12000 MB | Two dedicated cores for the API server and tokenizer. 12 GB of host RAM comfortably holds a ≤7 GB safetensors load. |
| `open-webui` | `cores = 4`, 16000 MB | `cpu = 1200`, 4000 MB | Shares, not dedicated cores. It is a web app with SQLite; 16 GB was for RAG at a scale we will not see. |
| `check_vllm_startup` | (default) | `cpu = 100`, 300 MB | Explicit, so the arithmetic below is checkable. |
| `create-admin` | (default) | `cpu = 100`, 300 MB | Same. |

The budget then closes:

```
cores:   2 dedicated            = 4000 MHz reserved   (of 6000)
shares:  1200 + 100 + 100       = 1400 MHz            (of 2000 remaining)   ✓
memory:  12000 + 4000 + 300 + 300 = 16600 MB          (of ~30000)           ✓
gpu:     1                                            (of 1)                ✓
```

It fits on **an empty node, with room to spare**. It does not fit on a node
already running a federated-learning workspace, which is why the node has to be
dedicated rather than borrowed.

---

## The cluster after the change

```
        You  --OpenVPN-->  jumpserver  --SSH-->  the cluster
                                                      |
        +---------------------------------------------+
        |                                             |
+-------v-------------------+          +--------------v------------+
| caios_server  .181        |          | caios_edge  .105          |
| Consul + Nomad servers    |          | Traefik, CPU client       |
| Compose control plane     |          | *.pacs-deployments...     |
+-------------+-------------+          +-------------+-------------+
              |                                      |
              +------+--------------+----------------+--------+
                     |              |                |        |
          +----------v--+  +--------v----+  +--------v----+  +v--------------+
          | caios_site_a|  | caios_site_b|  | caios_site_c|  | caios_llm     |
          | .104.20     |  | .104.145    |  | .104.7      |  | .104.188      |
          | "Hospital A"|  | "Hospital B"|  | "Hospital C"|  | NEW           |
          | FL client   |  | FL client   |  | FL client   |  | vLLM +        |
          |             |  |             |  |             |  | Open WebUI    |
          +-------------+  +-------------+  +-------------+  +---------------+
                     the three sites — unchanged            meta.role = llm
```

**What changes:** one inventory entry, one `host_vars` file, three Ansible
playbook runs limited to that host, one run of `ai4-nomad_tests`. No existing
node is touched. No security group changes — the LLM tool is plain HTTPS
through Traefik on 443, unlike NVFLARE with its 8002-8003.

**What is destructive and needs your approval:** `playbook-nomad.yml` will
**repartition and reformat `/dev/vdb` on the new node as XFS**, erasing whatever
is on it. That is gotcha 5 — Docker's disk quotas and `ai4-nomad_tests` both
require it. Stage L0 checks the volume's contents before Stage L1 touches it.

---

## The one thing this breaks, and how it is fixed

`scripts/deploy-fl-demo.sh` says, in its own header:

> *Nothing here pins a workspace to a node. The cluster scheduler is in "spread"
> mode, so each deployment goes to the least-allocated node and the three land
> one per site.*

That is true for three workspaces on three nodes. **With four compute nodes it
stops being true.** The three "hospital" workspaces could land on any three of
the four, so a recorded demo could show Hospital B running on `caios_llm`, or
`caios_site_c` sitting empty while the machine labelled as the LLM host trains
brain-tumour models. The federated learning is still genuinely distributed —
spread still puts them on distinct machines — but the story on screen is
wrong, and someone will notice.

Two fixes, and the plan does both:

1. **Durable (Stage L1):** tag the new node `meta.role = llm`, and add a soft
   anti-affinity for it to the dev-environment job template, the way upstream
   already uses anti-affinity to keep CPU jobs off GPU nodes. Soft, so if a
   hospital node dies the workspace still lands somewhere rather than failing.
2. **Operational (Stage L6):** the demo script deploys the LLM **before** the FL
   workspaces. `caios_llm` is then the most-allocated node, and spread avoids it
   on its own.

Both are cheap. Neither alone is quite enough: (1) can be defeated by a full
cluster, (2) by running the demo out of order.

---

## Capacity, honestly

One GPU per node, five GPU-capable nodes, one GPU held for as long as a vLLM
deployment exists.

- **One LLM deployment** on `caios_llm`: the intended state. Costs nothing else.
- **A second concurrent LLM deployment** has to take a hospital node's GPU. The
  FL demo is CPU-only (D-18) so it would still run, but the cluster is then out
  of GPUs for anything else.
- **Nothing stops a user doing this.** PAPI's two-GPU-per-user quota
  (`quotas.check_userwise`) reads `conf["hardware"]["gpu_num"]`, and the LLM
  tool has no `hardware` section at all — so its GPU is invisible to the quota.
  Any user can start any number of LLM deployments until the cluster is full.
  Contained on a private demo cluster with five accounts; a real problem if this
  is ever kept. Recorded in `docs/llm-risks.md`.

**Idle cost is the thing to watch on demo day.** A vLLM left running from
yesterday's rehearsal is a GPU that is gone. `scripts/verify-cluster.sh` shows
allocations per node; check it before recording.
