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

**Confirmed on 2026-08-19 (D-31):** the instance is ours, has never been used,
and is identical to the other five — 3 vCPU, ~34 GB RAM, one
`NVIDIA H100L-1-12C`, a 125 GB volume. It has still never been logged into, so
Stage L0 measures it rather than taking that on trust; the numbers are expected
to match, and the stage exists because "expected to" is not "does".

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
| Framebuffer, free per `nvidia-smi` | 10565 MiB | 1724 MiB goes to ECC and vGPU overhead. |
| **What CUDA reports** | **total 12100, free 10475 MiB** | Measured from inside a container. **These are the numbers vLLM sizes against**, and they are not the ones `nvidia-smi` prints. |
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

### And a third, found by actually testing it

**Nomad cannot currently hand a job a GPU that CUDA can use.** The device plugin
we run (`nomad-device-nvidia` 1.0.0) allocates the **parent** device; CUDA can
only address the **MIG instance**. A job with the `device "gpu"` stanza that
every PAPI template uses gets a container where `nvidia-smi` shows the GPU and
`torch.cuda.is_available()` is `False`.

This is not an LLM problem — it applies to every GPU workload on the cluster,
and it has been true since the cluster was built. It went unnoticed because
`nvidia-smi` reports success. The fix is a one-variable Ansible bump to plugin
1.1.0, which added MIG support. Full detail and the evidence: `docs/llm-risks.md`
R-18. Verify with `scripts/check-gpu-scheduling.sh`.

---

## What fits on 10.3 GB

vLLM's memory has three consumers: model weights, a fixed overhead (CUDA
context, compiled graphs, activation peaks — budget ~1.2 GB), and whatever is
left becomes KV cache, which is what determines how long a conversation can get
and how many people can chat at once.

vLLM takes `--gpu-memory-utilization` as a fraction of **total**, but can only
ever use **free**. Measured on `caios_site_a` on 2026-08-19:

| setting | wants | against 10475 MiB free |
|---|---|---|
| 0.90 — vLLM's own default | 10890 MiB | **over by 415 MiB, will not start** |
| 0.85 | 10285 MiB | fits, 190 MiB spare — too tight |
| **0.80** | **9680 MiB ≈ 10.15 GB** | **fits, 795 MiB spare** |

So the budget is **0.80, giving ~10.1 GB**. Weight sizes below are the real
`.safetensors` totals from the Hugging Face API, measured 2026-08-19.

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

**What is destructive and needs your approval:** the new node's second disk,
`/dev/vdb`, is repartitioned and reformatted. The next section says exactly what
that means.

---

## What the reformat actually does

This is the one irreversible step in the whole plan, so it is worth being
precise rather than waving at "gotcha 5".

### What these instances ship with

Every instance in this project has **two disks**. Measured on `caios_server`,
and the other five are the same image:

```
NAME      SIZE FSTYPE   MOUNTPOINT   LABEL
vda        20G                                  <-- the OS disk
├─vda1   19.9G ext4     /                cloudimg-rootfs
├─vda14     4M
└─vda15   106M vfat     /boot/efi        UEFI
vdb       125G ext4     /mnt             ephemeral0    <-- the data disk
```

Look closely at `vdb`. It has **no partitions at all** — no `vdb1` under it.
OpenStack wrote an ext4 filesystem directly onto the raw device and cloud-init
mounted it at `/mnt`. That single detail is the whole problem.

### Why that layout stops the node from ever receiving work

`ai4-nomad_tests` is not optional. It is the **only** thing that sets
`meta.status = ready` on a node, and every PAPI job template constrains on that
(gotcha 2). A node that fails it looks completely healthy in `nomad node status`
and silently never receives a single deployment.

For a GPU compute node, the test that runs is
`ai4_nomad_tests/tests/node/gpu.py`, and its first assertion is:

```python
assert n["Attributes"]["unique.storage.volume"] in ["/dev/vdb1", "/dev/sdb1"], \
    "No volume mounted"
```

`unique.storage.volume` is Nomad's own fingerprint of the device backing its
`data_dir`. On the live cluster, right now:

| Node | In `nomad_volume`? | `unique.storage.volume` | Disk seen |
|---|---|---|---|
| `caios-wn-gpu-0` | yes | **`/dev/vdb1`** | 134 GB |
| `caios-traefik` | no | `/dev/vda1` | 20 GB |

That difference is produced by one line in `ai4-ansible`'s `nomad.j2`: a host in
the `nomad_volume` group gets `data_dir = /mnt/data`; every other host gets
`data_dir = /opt/nomad`, which sits on the 20 GB root disk. (The Traefik node
passes certification anyway because `meta.type = traefik` routes it to a
different test that does not check storage.)

So leaving node 6 out of `nomad_volume` gives us a node that reports
`/dev/vda1`, **fails the GPU node test, never turns `ready`, and never runs
anything** — while looking perfectly fine. It would also put Nomad's working
directory, where a 10.5 GB container image and 5 GB of model weights land, on a
root disk with about 12 GB free.

### Why it cannot be done without erasing

To make Nomad report `/dev/vdb1`, a partition called `vdb1` has to exist. To
create a partition table on a disk, you write to the start of the disk — which
is exactly where the existing whole-device filesystem's metadata lives. **There
is no non-destructive path from "ext4 on the raw device" to "ext4 on a
partition".** The data has to be somewhere else while the disk is relaid.

That is the entire reason this step is destructive. It is not that XFS is
required and ext4 must go; it is that a *partition* is required and there is not
one.

### What is destroyed, and what is not

**Destroyed:** everything on `/dev/vdb`, the 125 GB data volume currently
mounted at `/mnt`. On the three site nodes that was `lost+found` and nothing
else, verified on 2026-08-12. Node 6 has never been used, so it should be the
same — and Stage L0 confirms it by eye before Stage L1 runs.

**Not touched:**

- `/dev/vda` — the OS disk. The operating system, `/home/ubuntu`, SSH keys,
  installed packages, everything under `/` survives untouched.
- Every other node in the cluster. The playbook runs `--limit caios_llm`.
- `caios_server`'s volume, ever. The playbook carries a hard `assert` refusing to
  run against it, because **this repository lives on it** at `/mnt/CAIOS`.

There is a reboot in the middle. The LXD snap holds a stale reference to `/dev/vdb`
in its own mount namespace, created while the disk was mounted, and that makes
`mkfs` fail with "Device or resource busy" even after unmounting. Rebooting is
the deterministic way to clear it, and the node is empty, so it costs a minute.

### The safety gate is already in the playbook

`playbook-prepare-volumes.yml` does not take your word for it. Before it touches
anything it lists the contents of `/mnt`, and:

```
- name: "Refuse to erase a volume with data on it"
  ansible.builtin.fail:
    msg: |
      {{ caios_device }} on {{ inventory_hostname }} is not empty:
      ...
      Move anything you need off it, or pass -e caios_force_wipe=true if you
      are certain it is disposable.
```

So the sequence is: L0 shows you what is on the disk, you approve, and the
playbook independently refuses if anything other than `lost+found` is there.
Two checks, and neither is "trust the plan".

### What we considered instead

| Alternative | Why not |
|---|---|
| Leave the disk alone, keep Nomad on `/opt/nomad` | Node never certifies, never runs anything, and has ~12 GB free where a 10.5 GB image must land. |
| Patch `ai4-nomad_tests` to accept `/dev/vdb` | We already carry one patch to that suite, so it is possible. But it would make node 6 the only node in the cluster laid out differently from the rest, and it means editing the thing whose job is to certify nodes so that it certifies a node it was written to reject. |
| Keep ext4, just add the partition | Adding the partition is the destructive act. The filesystem type is incidental — XFS is chosen only because we are reformatting anyway and it is what the other three nodes have. |
| Manually set `meta.status = ready` | Defeats the point of the check, and it would be undone by the next Ansible run. |

**Recommendation: do it as designed.** It is the same step the three hospital
nodes went through, on a disk that has never held anything, behind two
independent confirmations.

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
