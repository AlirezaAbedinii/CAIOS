# Feature coverage — what the dashboard offers vs what we are building

Every section of the reference dashboard (`dashboard.cloud.ai4eosc.eu`), whether
it is in our scope, and what it would cost to add.

All figures verified against the upstream source at the commits we pin, not
estimated from memory. Effort is engineer-days for one person.

---

## Summary

| Dashboard section | In scope | Effort to add |
|---|---|---|
| **Catalog → Modules** | ✅ MVP | — |
| **Catalog → Tools** | ⚠️ 2 of 6 in MVP | 0.5–1 day each |
| **Catalog → LLMs** | ❌ V1 stretch | 1 day |
| **Deployments** | ✅ MVP | — |
| **Deployments → Inference** | ❌ Out | **5–8 days** (needs Kubernetes) |
| **Try me** | ❌ Out | 1 day + a dedicated node |
| **Batch training** | ❌ Out | 1–1.5 days |
| **Tasks** | ✅ MVP (comes free) | — |
| **Statistics** | ✅ MVP (live data) | +2 days for history |
| **Services → Storage** | ❌ V1 | 1 day |
| **Services → Experiment tracking** | ❌ V1 stretch | 1–1.5 days |
| **Services → AI Inference workflows** | ❌ Out | same as Inference — **5–8 days** |
| **Services → LLM Chat** | ❌ Out | 2–3 days |

**Roughly 60% of the dashboard's surface is in the MVP.** The excluded 40% is
concentrated in two areas: serverless inference (which needs a second cluster)
and the LLM features (which need more GPU memory than we have).

---

## 1. Catalog → Modules ✅ **In scope**

The marketplace of AI models. This is the demo's front door.

Working already at the platform level; what remains is curation. The stock
catalogue is 46 models of which **2 are medical and 0 neuroscience** — mostly
marine biology. We remove ~31 irrelevant entries and keep ~15.

No extra cost: it is a list of references, not software.

---

## 2. Catalog → Tools ⚠️ **2 of 6 in MVP**

Six tools exist upstream. These are deployable *services* rather than models.

| Tool | What it does | Scope | Cost to add | Blocker |
|---|---|---|---|---|
| **Dev environment** | JupyterLab / VS Code on a GPU | ✅ MVP | — | — |
| **Federated server** | Coordinates federated learning | ✅ MVP | — | — |
| **AI4Life loader** | Deploys any bioimage.io model by ID | 🔶 V1 | **0.5 day** | none |
| **NVFLARE** | Second federated learning framework | 🔶 V1 | **0.5 day** | needs 2 firewall ports |
| **CVAT** | Image annotation | 🔶 V1 | **0.5 day** | **needs ~71 GB RAM on one machine** |
| **LLM (vLLM + chat UI)** | Deploy your own language model | ❌ | **1 day** | **needs ~32 GB RAM + a bigger GPU** |

### Why adding a tool is cheap

Each tool is already packaged and already configured in the platform's API. The
work per tool is: enable it, deploy it once, confirm it works, and write the demo
steps. That is **half a day** for the ones with no external dependency.

The cost is not engineering — it is *demo time and risk*. Every tool is another
thing that can fail in front of an audience and another few minutes of narrative.
That is the real reason we start with two.

### The three that have a real blocker

**CVAT** is one unit of 22 containers that must all run on the same machine and
together need about 71 GB of memory. Our largest node has 34 GB. The software
cost is half a day; the hardware is the constraint. If the larger machine
appears, this comes back easily.

**NVFLARE** needs two extra ports opened. Trivial, but it duplicates a story
Flower already tells, so it earns its place only if a reviewer specifically cares
about NVIDIA's stack.

**The LLM tool** is covered in the next section.

---

## 3. Catalog → LLMs ❌ **V1 stretch — and the honest picture is better than expected**

The platform ships **13 ready-to-deploy language models**:

| Family | Models | Size |
|---|---|---|
| Qwen 3.5 | 2 | 0.8B, 2B |
| Mistral (Ministral 3) | 2 | 3B, incl. a reasoning variant |
| LiquidAI LFM 2.5 | 4 | 0.45B–1.6B, incl. 2 vision models |
| IBM Granite 4.1 | 2 | 3B, incl. a vision model |
| Meta Llama 3.2 | 2 | 3B — requires a Hugging Face token |
| DeepSeek R1 (distilled) | 1 | 1.5B |

Two Microsoft Phi models are disabled upstream because the chat interface renders
their output incorrectly.

**Correcting an earlier assumption.** We previously assumed language models were
out of reach because a 7B model needs about 14 GB of GPU memory and ours have 12
GB. That was pessimistic: **every model in this catalogue is 4B or smaller**, and
the smaller ones would fit our GPUs comfortably. They are tuned for a 16 GB card;
we have 12 GB, so the 3–4B models are tight but the 0.5–2B models are not.

**The actual blocker is system memory, not GPU memory.** The tool asks for
16 GB of RAM for the model server and another 16 GB for the chat interface —
32 GB total, on nodes with 34 GB. It would run with almost nothing to spare, and
would compete with the federated learning demo for the same machines.

**Cost: 1 day**, mostly tuning memory limits and picking one or two small models
that behave well. Genuinely feasible as a V1 stretch, and it demos well — a
researcher chatting with a private model on the lab's own hardware is a good
image. It should not displace federated learning.

---

## 4. Deployments ✅ **In scope**

The list of what a user currently has running, with links to open each one. Core
to the demo; nothing extra needed.

### Deployments → Inference ❌ **Out — see the OSCAR section**

---

## 5. Try me ❌ **Out of scope**

Lets an anonymous or low-privilege visitor try a model instantly with no setup —
a genuinely nice feature for a public platform.

**Why it is out.** It requires a **dedicated node** tagged `tryme`, with model
images pre-pulled so the trial starts instantly. We have five nodes and all five
have jobs. It is also hardcoded upstream to the AI4EOSC organisation, so it needs
a small patch.

**Cost: 1 day plus a machine.** Low value for our audience — our demo has a
logged-in researcher, not an anonymous browser.

---

## 6. Batch training ❌ **Out of scope**

Submits long-running training that queues and runs unattended, emailing you when
finished.

**Why it is out.** Needs nodes tagged as batch workers and a mail service for the
notifications. More importantly, a batch job that runs for hours is the opposite
of a demo — you cannot show it working in a walkthrough.

**Cost: 1–1.5 days.** Worth it only if this becomes a platform the lab actually
runs, not for the demo.

---

## 7. Tasks ✅ **In scope, free**

The progress view for actions in flight. Part of the dashboard; no separate
service.

---

## 8. Statistics ✅ **In scope, live data only**

Shows the cluster: machines, GPUs, memory, running jobs, and a map. This is a
strong visual and it works with what we have.

**One caveat.** *Historical* usage graphs — usage over the past weeks — come from
a separate accounting service that must run continuously to have anything to
show. Adding it later shows an empty chart.

**Cost: 2 days, and it has to start almost immediately.** This is the open
question with the shortest fuse, which is why it is in the questions list.

---

## 9. Platform Services → Storage ❌ **V1**

The platform's own file storage, so datasets are already mounted inside a
workspace rather than copied in.

**What it actually is.** Not S3 or a generic cloud bucket — the platform is built
around **Nextcloud over WebDAV**, hardcoded in several places. Substituting
something else means patching five templates and breaking the dashboard's own
credential flow.

**Cost: 1 day** — deploy Nextcloud, configure it to accept requests from the
dashboard, connect the credential storage.

**What we lose in MVP:** the Storage tab, and the "your data is already here"
moment. Datasets are copied into the workspace directly instead. The federated
learning demo is unaffected — each site's data is placed on its own machine,
which is the point.

---

## 10. Platform Services → Experiment tracking (MLflow) ❌ **V1 stretch**

Records every training run and its results so "which configuration was best" has
an answer.

**Cost: 1–1.5 days** — deploy MLflow with a database and object storage behind
it, connect user accounts.

Nice for credibility with an ML audience, invisible to everyone else. It earns
its place only if the audience is technical.

---

## 11. Platform Services → AI Inference workflows (OSCAR) ❌ **Out — this is the expensive one**

You flagged this as something we need, so it deserves a direct answer.

### What it gives you

Serverless inference: a model that consumes **no resources when idle**,
auto-scales when queries arrive, and can process large batches asynchronously.
The pitch is real — you can host fifty models on hardware that would only fit
five running continuously.

### Why it is expensive here

**OSCAR is a separate platform that runs on Kubernetes.** Verified against its
own documentation: an OSCAR cluster requires Kubernetes plus Knative (the
serverless engine), MinIO (object storage), CLUES (the elasticity manager) and
the OSCAR manager itself.

Our platform runs on **Nomad**, a different orchestrator. The dashboard talks to
OSCAR as an *external service* — our API is only a client of it. So adding
serverless inference does not mean enabling a feature. It means **standing up and
operating a second cluster on a different technology stack**, then connecting the
two.

### What that costs

| Work | Days |
|---|---|
| Kubernetes cluster on dedicated nodes | 2–3 |
| Knative, MinIO, CLUES, OSCAR manager | 1–2 |
| Connect authentication to our login system | 1 |
| Connect our API, test, debug | 1–2 |
| **Total** | **5–8 days** |

Plus **nodes we do not have** — all five are allocated, and Kubernetes needs its
own.

Against a 20-day budget with two engineers, that is roughly a quarter of the
remaining capacity, spent on infrastructure rather than anything visible.

### What you can have instead, for free

The demo already includes **"serve the trained model as a REST endpoint"** as its
closing beat. A deployed model exposes a standard web API that anyone can call —
this works today, needs nothing extra, and is what most viewers understand by
"deploy a model for inference".

What OSCAR adds on top is *scale-to-zero* and *auto-scaling*. Those are
operational efficiencies. They matter enormously for a production service with
unpredictable traffic; they are close to invisible in a 25-minute walkthrough,
where one deployment serves one request from one presenter.

### My recommendation

**Leave it out for the demo, and put it on the roadmap slide.** It is a genuinely
strong story for a grant — "the architecture supports serverless, auto-scaling
inference" — and it costs one sentence there instead of a quarter of the
remaining budget.

If a reviewer specifically asks about production inference economics, that is
exactly when a roadmap item does its job.

**Reconsider it if** the grant's claim is specifically about efficient
large-scale serving rather than federated learning. In that case it moves from
"nice" to "necessary" and we should rebalance deliberately — but that is a
scope decision, not a technical one, and worth making explicitly.

---

## 12. Platform Services → LLM Chat ❌ **Out of scope**

A ChatGPT-style interface against models the platform hosts. Distinct from the
LLM *tool* above: that deploys a model for you, this is a shared always-on
service for everyone.

**What it needs.** Three pieces: the chat interface, a gateway that manages API
keys and routes requests, and at least one always-running model server. Upstream,
these live at fixed addresses hardcoded in the platform's source, so we would
also patch those.

**Cost: 2–3 days**, plus a GPU permanently occupied by the model.

That last part is the real objection. We have three GPU machines and the
federated learning demo needs all three. A permanently-loaded chat model would
compete with the headline feature for the same hardware.

---

## What this means overall

**The two big exclusions are both hardware, not software.** Serverless inference
needs a second cluster; the LLM features need GPU and memory headroom we do not
have. Neither is a limitation of our approach, and both are honest roadmap items.

**Adding tools is cheap; adding platforms is not.** Any of the four remaining
tools is roughly half a day. OSCAR is 5–8 days and a new cluster. That asymmetry
should drive the decisions.

**The demo does not have a hole where inference should be.** "Deploy a model and
call it over an API" is already in the walkthrough. What is missing is the
serverless *economics*, which is a slide rather than a screen.

### If you want to add exactly one thing

**The AI4Life loader — half a day.** It puts real neuroscience models in the
catalogue, including connectomics models that trace neurons through electron
microscopy. That directly addresses the weakest part of the current story, which
is that the catalogue does not yet look like it was built for this audience.

### If you want to add a second

**The LLM tool — one day.** A researcher chatting with a private model running on
the lab's own hardware is a memorable image, and the models available are small
enough to actually work. Schedule it after federated learning is finished and
recorded, so it can never compete with the headline for time or GPUs.
