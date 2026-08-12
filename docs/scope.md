# Scope

What we are building, what we are not, and which of it lands in MVP versus V1.
This is the document to check against expectations — if something here is wrong,
it is much cheaper to find out now.

`docs/mvp-plan.md` says in what *order*. This says *what*.

---

## In one paragraph

CAIOS is a branded instance of the open-source **AI4OS** platform, running on five
GPU nodes on Compute Canada's Arbutus cloud, aimed at medical and neuroscience
researchers. A researcher logs in through a web browser, picks a model from a
catalogue, and gets a GPU workspace or a running model without touching a
terminal. The headline capability is **federated learning**: training a model
across three simulated hospital sites where the data never leaves each site.

We deploy and brand the platform. We do not fork it. Every change to upstream
behaviour is either configuration we own or a small, reviewable patch.

---

## The definitions

**MVP** — the end-to-end story works. A researcher logs in, deploys a model,
opens a GPU workspace, and runs a federated training across three sites. Rough
edges are acceptable; gaps in the story are not. **Target: 8 working days.**

**V1** — the same thing, polished, recorded, and with the pieces that make it
look finished rather than assembled.

---

## Feature scope

### MVP

| Capability | What it means in the demo |
|---|---|
| Cluster | Five nodes running Nomad, Consul and Traefik |
| Login | Own login system, demo accounts, no institutional SSO |
| Web dashboard | Branded CAIOS, the only interface the demo uses |
| Model catalogue | Curated to medical and neuroscience, not marine biology |
| Deploy a model | From the catalogue, in the browser, running in under a minute |
| GPU workspace | JupyterLab or VS Code on a real GPU |
| **Federated learning** | **Three sites, non-IID data, rounds visible as they run** |
| Statistics page | Live cluster usage — nodes, GPUs, running jobs |
| Secrets | Per-deployment, so each site can hold its own credential |

### V1, in priority order

| Capability | Why it waits | Cost |
|---|---|---|
| Real domain + trusted certificate | Needs a domain purchase; MVP works without it | 0.5 day |
| Rehearse twice, record once | Only meaningful once MVP works end to end | 1.5 days |
| Sites enforced by login | MVP *chooses* the site; V1 makes it structural | 1 day |
| Nextcloud storage | Platform-native storage; MVP copies data in directly | 1 day |
| CVAT annotation | Needs a node with ~72 GB RAM, which we do not have | 0.5 day |
| NVFLARE | Second federated framework; Flower alone tells the story | 0.5 day |
| bioimage.io model loader | Adds real neuroscience models to the catalogue | 0.5 day |

### Stretch, only if V1 lands clean

MLflow experiment tracking · one custom neuroscience module built from scratch ·
an LLM chat service

> On the LLM: our GPUs are 12 GB slices of an H100. A 7B model at full precision
> needs about 14 GB. This beat requires a quantised or smaller model, and should
> be treated as genuinely optional.

### Not in scope, and why

These are all real features of the upstream platform. They are out because they
cost days and add nothing to the story we are telling. Each is a roadmap-slide
item.

| Excluded | Reason |
|---|---|
| OSCAR serverless inference | A whole second platform to operate |
| Harbor container registry | We pull public images |
| Jenkins publishing pipeline | Nobody publishes a module in the demo |
| Drift monitoring | Needs a production model and history |
| Provenance tracking | Needs external infrastructure |
| Low-code pipeline builders | Adds a second UI to learn and debug |
| Carbon-footprint accounting | Depends on an external API |
| **Real PACS / DICOM integration** | **A separate project — see the caveat below** |

> **The one to confirm.** The brief mentioned a "PACS lab flavour installation".
> We have read that as *branding* — logo, colours, naming. If it means connecting
> to a real hospital imaging archive over DICOM, that is a different project with
> a different timeline. Worth confirming explicitly.

---

## What "federated learning" means here, concretely

The centrepiece, so it is worth being precise about what is and is not claimed.

**What the demo actually shows:**

- Three separate physical machines, each holding a different slice of a public
  dataset. Data is deliberately split **non-IID** — Site A mostly one class, Site
  B mostly another, Site C mixed — because that is what real hospitals look like.
- A coordinating server the researcher starts from the dashboard.
- Each site trains on its own data. Only model weights leave the machine.
- Accuracy improving round by round, visible as it happens.
- A closing chart: one site alone (poor), all data pooled centrally (best, but
  legally impossible), federated (close to central, and permitted).

**What it does not show:** a novel algorithm, a clinically meaningful model, or
real patient data. It uses public data only (D-07), deliberately — it means no
question about ethics or privacy is unanswerable.

The claim is *"this platform can run federated training across institutions"*,
not *"this model is clinically useful"*.

---

## The catalogue problem

Worth stating plainly because it is the first thing an audience sees.

The stock catalogue is 46 models. Verified counts: **2 medical**, **0
neuroscience**. About 20 are marine and environmental. Deployed as-is, a
neuroscientist opens the catalogue and sees coral reef segmentation.

The fix is mostly subtraction: remove roughly 31 irrelevant models, keep the two
medical ones and the general-purpose models a researcher could apply to their own
data. That leaves about 15, all plausibly useful.

Then add real ones. The platform includes a loader that can deploy any model from
**bioimage.io**, a public repository of life-science imaging models — and it
supports three **connectomics** models (tracing neurons through electron
microscopy), plus mitochondria segmentation. That is genuine neuroscience for no
code at all, and it is why building a custom model has moved from *necessary* to
*optional*.

Detail in `catalog/medical-shortlist.md`.

---

## Software we deploy

All open source. Nothing here is written by us from scratch.

| Component | Role |
|---|---|
| `ai4-ansible` | Installs the cluster: Consul, Nomad, Traefik |
| `ai4-papi` | The platform API. The dashboard's only backend |
| `ai4-dashboard` | The web interface. We add a CAIOS theme |
| `ai4-nomad_tests` | Validates the cluster; also marks nodes ready for work |
| `modules-catalog` | The model catalogue. We fork and curate |
| `ai4os-dev-env` | JupyterLab / VS Code workspaces. Also the FL client |
| `ai4os-federated-server` | The federated learning coordinator |
| Keycloak, Vault, Traefik, Consul, Nomad | Third-party infrastructure |

Deferred to V1: `ai4os-cvat` (annotation), `ai4os-nvflare` (second FL framework),
`ai4os-ai4life-loader` (bioimage.io models).

---

## Constraints we are working within

Facts, not preferences. Each shapes something above.

| Constraint | Consequence |
|---|---|
| No public IP on any node | Nothing is reachable outside the VPN. A live demo to external reviewers needs a floating IP, or it has to be recorded. |
| No DNS zone we control | No trusted certificate for MVP. Browser shows a warning until we buy a domain. |
| GPUs are 12 GB slices | Fine for the FL demo and imaging models. Tight for large language models. |
| No node above 34 GB RAM | CVAT cannot run at all — it needs ~72 GB on one machine. |
| Two engineers, three weeks | Everything above is a choice about where those days go. |

---

## Open questions

None of these block work — each has a default already in effect. They are listed
because deciding some of them late is expensive.

| Question | Our default | Cost of deciding late |
|---|---|---|
| Buy a domain (~$15/yr)? | Self-signed certificate, browser warning | **Low, but has lead time — worth starting now** |
| "PACS flavour" = branding or DICOM integration? | Branding | **Very high if it means integration** |
| Live demo, or recorded? | Record it regardless, as insurance | Medium |
| Does Statistics need historical usage? | Live data only | **High — history has to be collected for days** |
| Which imaging modality should we feature? | Public brain MRI | Medium — the FL demo gets built around it |
| Throwaway demo, or kept running? | Demo, but fully automated anyway | Low |
