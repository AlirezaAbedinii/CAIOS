# Demo script

The walkthrough, beat by beat, with what to say, what to click, and what to do
when something misbehaves.

**Total: ~22 minutes**, leaving time for questions in a 35-minute slot. Timings
are measured, not estimated — the sources are noted where they matter.

Setup and rehearsal live in `docs/runbook.md`. This file is the performance.

---

## Before you start

Run these in order. The last one is not optional — a cold image pull mid-demo
is the most reliable way to make a working platform look broken.

```bash
bash scripts/check-branding.sh                 # 30s — is it still CAIOS?
bash scripts/verify-cluster.sh                 # 10s — are all nodes schedulable?
bash scripts/deploy-fl-demo.sh --status        # is the federation already up?
cd ansible && ansible-playbook playbook-prepull-images.yml
```

**Have these open in tabs, in this order:**

1. The dashboard, logged out
2. `demo/fl/results/federated-vs-baselines.png` — the closing chart
3. A terminal per hospital site, already bootstrapped (see beat 5)

**Have this ready but hidden:** the recording of a completed federated run. If
a round hangs, you cut to it rather than debugging in front of people.

> **Say once, at the top, and then stop apologising for it:** "You'll see a
> certificate warning — this is on a private research network with a
> self-signed certificate. A real deployment uses a real domain." Then click
> through and never mention it again.

**Two things about the LLM, until Stage L6 gives it a beat of its own.**

*Only one fits while the federation is up.* An LLM deployment wants two
exclusive CPU cores, 16.3 GB and a GPU. The LLM node holds any that is already
running, and the three hospital nodes have a free GPU each but only three cores
— one of which a workspace is using. A second deployment therefore sits at an
orange `queued` badge until something is deleted. That is correct behaviour and
the badge now says so, but do not discover it on camera.

*A deployment takes one to three minutes before you can open it.* The badge goes
yellow `starting` and *Quick access* stays greyed out for the whole of it, which
is the honest thing to show — but it is dead air. Deploy it at the start of a
beat and come back to it, exactly as beat 5 does with the federated rounds.

---

## Beat 1 — Log in, and see a catalogue that speaks your language (2 min)

**Click:** Log in as `researcher`. Land on the Marketplace.

**Say:** "This is CAIOS — the same platform stack the EU runs for AI4EOSC,
deployed on Compute Canada hardware and pointed at medical imaging."

**The point of this beat is the catalogue, so let them read it.** Nine modules:
retinopathy, image and object classification you retrain on your own data,
body pose. Scroll slowly.

**Say:** "Upstream ships forty-six modules. About two thirds are marine biology
and remote sensing — good models, wrong audience. We curated it down to what a
clinical or neuroscience group would actually deploy."

> **If asked "is that all?"** — that is the right question and the answer is
> the strongest thing here: "Deliberately. A researcher scanning nine modules
> that could all apply to their work forms a better impression than one
> scrolling past thirty they never will. And the number is not the ceiling —
> next beat."

---

## Beat 2 — Real neuroscience, deployed by ID (3 min)

**Click:** Tools → AI4Life loader. Open the model dropdown.

**Say:** "This is a loader for bioimage.io, the community model zoo. Any model
in it deploys here by ID, with no code."

The dropdown opens on **`zealous-snail`** — "Circuit reconstruction for electron
microscopy". Let that sit for a second.

**Say:** "That's connectomics — tracing neurons through electron microscopy
volumes. Below it, two more architectures on the same task, so you can compare
them; mitochondria segmentation; CellPose; nucleus segmentation with seventy
thousand downloads."

**Click:** Deploy it. While it starts, move on — do not watch a progress bar.

> **Honest framing, and use it if the audience is technical:** "We didn't build
> these. That's the point — the platform makes a published model deployable in
> a click, so the lab's effort goes into their own models rather than
> infrastructure."

---

## Beat 3 — A real GPU workspace (3 min)

**Click:** Tools → Development environment. JupyterLab, 1 GPU. Deploy.

**Say, while it starts:** "Every deployment gets its own address and its own
resources, scheduled onto whichever node has room."

**Click:** open the workspace when it is running (~90 seconds, measured), open a
terminal, run:

```bash
nvidia-smi
```

**Say:** "An H100 slice, inside a container the researcher got from a web page.
No ticket, no sysadmin."

> **If it is slow to start:** talk over it — the nodes are 3-core machines and
> this is the honest cost of a small cluster. Do not sit in silence.

---

## Beat 4 — The problem federated learning solves (2 min)

No clicking. This is the setup for the headline, and it is worth doing properly.

**Say:** "Three hospitals. Each has brain MRI with tumour labels. None of them
can send it anywhere — not to us, not to each other. Ethics, privacy,
provincial law."

**Show:** the chart, but **cover the teal line** — physically, or have a second
image ready.

**Say:** "Each hospital can train alone. The grey lines are what they get: high
seventies. Pool everything and you get 0.865 — the dashed line. That is the
thing they're not allowed to do."

**Then:** "So the question is how close you can get to the dashed line without
anybody's data moving."

---

## Beat 5 — Federated learning across three hospitals (8 min)

The headline. Everything so far exists to make this land.

**Show first, so nobody thinks it is a simulation:**

```bash
bash scripts/deploy-fl-demo.sh --status
```

**Say:** "Three workspaces, on three separate physical machines — gpu-0, gpu-1,
gpu-2. Each holds one hospital's slices and nothing else."

**Click:** Open the federated server's IDE. In its terminal:

```bash
cd /srv/ai4os-federated-server/fedserver && python3 server.py
```

**Say:** "It's waiting. It will not start until all three hospitals have
joined — that's the minimum-clients setting."

**Then, in each of the three site terminals** (already bootstrapped — see the
runbook; do the bootstrap *before* the demo, it is a dull 60 seconds of pip):

```bash
cd ~/caios-fl && ./run.sh --quiet
```

Start them one at a time and narrate:

- After the first: "One hospital connected. Nothing is happening yet."
- After the second: "Two. Still waiting."
- After the third: **it starts immediately.**

**Say, while rounds print:** "Each site is training on its own patients, sending
only model weights, and getting back an average. Watch the accuracy — that
number is the shared global model, scored on held-out scans none of the three
has ever seen."

**Runs in about 30 seconds** for 10 rounds (measured). Let the numbers scroll.

**Then reveal the teal line on the chart.**

**Say:** "0.853. The best single hospital got 0.806, pooling everything got
0.865. Federated closed eighty-one percent of that gap — and no image left the
machine it started on."

> **Fallback, in order:**
> 1. A client fails to connect → restart just that one; the server waits.
> 2. Two connect and the third will not → say "this is the minimum-clients
>    behaviour, and it's the right behaviour", then cut to the recording.
> 3. Rounds run but accuracy is poor → **this is not an infrastructure
>    failure and must not be allowed to look like one.** Say: "the mechanism is
>    what matters here; the model is a demo model on downsampled images." Then
>    show the chart from the completed run.

---

## Beat 6 — Serve it as an API (2 min)

**Click:** back to the deployed module from beat 2 or 3, open its API endpoint.

**Say:** "Every deployment exposes the same REST API. So the output of all this
is not a notebook — it's an endpoint a hospital's own software can call."

Run one prediction through the Swagger UI.

---

## Beat 7 — What it costs and where it runs (2 min)

**Click:** Statistics.

**Say:** "Live cluster usage — five nodes on Compute Canada's Arbutus cloud,
with a GPU each. This is running on the allocation, not on a laptop."

**Close with the roadmap slide**, not with the platform. Name the deferred
items honestly: annotation with CVAT, shared storage, a second FL framework,
and a real certificate.

---

## Questions you will be asked

**"Is the data really not moving?"**
Open `demo/fl/client.py` and point at `fit()`. What is returned is weights, a
slice count and an accuracy number. Then: "and each site's bundle physically
contains only its own slices — that's built, not promised."

**"Could a hospital reconstruct another's data from the weights?"**
Be straight: "Gradient inversion is a real attack and this demo does not defend
against it. The platform ships differential privacy and secure aggregation as
options we haven't turned on. For a production deployment you would."

**"Why is the accuracy not higher?"**
"Downsampled to 64×64 so a round finishes while you watch, three thousand
images, and a deliberately small model. The comparison between the three lines
is the result — not the absolute number."

**"How much of this did you build?"**
"Almost none of the platform, deliberately — it's AI4OS, which the EU funds and
maintains. What we built is the Canadian deployment, the medical curation, and
the federated demo. The delta is eight small patches."

**"Can we run our own models on it?"**
Yes — that is what beat 3's workspace is, and the marketplace is a git
repository of module definitions.

---

## Timing sheet

| Beat | What | Minutes |
|---|---|---|
| 1 | Log in, curated catalogue | 2 |
| 2 | Neuroscience by model ID | 3 |
| 3 | GPU workspace | 3 |
| 4 | The problem | 2 |
| 5 | **Federated learning** | **8** |
| 6 | Model as an API | 2 |
| 7 | Cluster and roadmap | 2 |
| | **Total** | **22** |

If you are running long, cut beat 6 first, then beat 2's deployment (talk over
the dropdown instead of deploying). **Never cut beat 4** — without the problem
stated, beat 5 is just numbers going up.
