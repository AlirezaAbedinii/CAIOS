# Demo script

The walkthrough, beat by beat, with what to say, what to click, and what to do
when something misbehaves.

**Total: ~25 minutes**, leaving time for questions in a 35-minute slot. Timings
are measured, not estimated — the sources are noted where they matter.

Setup and rehearsal live in `docs/runbook.md`. This file is the performance.

---

## Before you start

Run these in order. The last one is not optional — a cold image pull mid-demo
is the most reliable way to make a working platform look broken.

```bash
bash scripts/check-branding.sh                 # 30s — is it still CAIOS?
bash scripts/verify-cluster.sh                 # 10s — are all nodes schedulable?
bash scripts/check-llm-config.sh               # 20s — is the LLM tool deployable?
bash scripts/deploy-fl-demo.sh --status        # is the federation already up?
cd ansible && ansible-playbook playbook-prepull-images.yml
```

**Deploy the language model FIRST, before the federated workspaces.** Two
reasons, and both of them cost you if you get the order wrong:

- It takes **one to three minutes** to load, and the badge stays yellow the
  whole time. Started first, that disappears behind beats 1 to 6.
- With four compute nodes and spread scheduling, a workspace deployed first can
  land on the LLM node — and then the LLM has nowhere to go (R-14). Deploying
  the LLM first puts it on its own node and pushes the three workspaces onto the
  three hospital machines, which is what makes it a three-site demo.

Use the dashboard, exactly as beat 7 describes, and **write down the endpoint
and the API key** — you want both pasted into the notebook before anyone is
watching.

Then bring up the federation, and check the bootstrap URL actually serves, since
that is what each hospital pastes:

```bash
curl -k -sS -o /dev/null -w '%{http_code}\n' https://<dashboard>/fl/bootstrap.sh
```

**Have these open in tabs, in this order:**

1. The dashboard, logged out
2. `demo/fl/results/federated-vs-baselines.png` — the closing chart
3. A terminal per hospital site, already bootstrapped (see beat 5)
4. The chat interface of the running LLM, **already logged in** — the login
   screen is thirty seconds of typing that shows nothing
5. A notebook in the site_a workspace with beat 7's four lines pasted in,
   endpoint and key filled, unrun

**Have this ready but hidden:** the recording of a completed federated run. If
a round hangs, you cut to it rather than debugging in front of people.

> **Say once, at the top, and then stop apologising for it:** "You'll see a
> certificate warning — this is on a private research network with a
> self-signed certificate. A real deployment uses a real domain." Then click
> through and never mention it again.

**Two things about the LLM that will bite if you forget them.**

*Only one fits while the federation is up.* An LLM deployment wants two
exclusive CPU cores, 16.3 GB and a GPU. The LLM node holds whichever one is
already running, and the three hospital nodes have a free GPU each but only
three cores — one of which a workspace is using. A second deployment therefore
sits at an orange `queued` badge until something is deleted. That is correct
behaviour and the badge names the resource that ran out, but do not discover it
on camera. Beat 7 shows the deploy *form* and then switches to the running one.

*A deployment takes one to three minutes before you can open it,* and the
default model is the slowest of the nine. The badge goes yellow `starting` and
*Quick access* stays greyed out for the whole of it. That is honest and it is
dead air — which is why it goes first, before beat 1.

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

## Beat 7 — A private language model, on your own GPU (3 min)

The same argument as beat 5, escalated: *the platform that trains across
hospitals without moving data also answers questions without sending them to a
vendor.*

**Say first, because it is the whole point:** "Everything you've seen so far is
about training. This is about inference — and it's the question every hospital
IT department is actually being asked right now, which is 'can we use an LLM
without sending patient notes to a company in California?'"

**Click:** Marketplace → LLMs.

**Say:** "Nine models, and this page is served by this cluster — the cards, the
descriptions, the badges. Nothing here calls out to anybody."

Pick one and click it. The deploy form opens with that model selected.

> **You deployed one before you started** (see *Before you start*), so do not
> deploy a second here — it will queue for a GPU and say so. Show the form,
> then switch to the one that is already running.

**Click:** the running LLM deployment → *Quick access* → the chat interface.

Log in with the credentials you set. Ask it something that sounds like the room:

> *Summarise this radiology note in one sentence: T2 hyperintense lesion, left
> periventricular white matter, 8mm, stable versus prior study.*

**Say, while it streams:** "That's running on a GPU in this cluster. The prompt
didn't leave the building, and there's no API bill."

### The half that makes it infrastructure

The chat window is the demo; the endpoint is the product. Switch to the
**site_a workspace terminal** — the same one that was a hospital in beat 5.

```python
import os
from openai import OpenAI

os.environ["SSL_CERT_FILE"] = os.path.expanduser("~/caios-fl/caios-ca.pem")
llm = OpenAI(base_url="https://vllm-<uuid>.<domain>/v1", api_key="<from Vault>")

print(llm.chat.completions.create(
    model="LiquidAI/LFM2.5-1.2B-Instruct",
    messages=[{"role": "user", "content":
               "Summarise this radiology note in one sentence: T2 hyperintense "
               "lesion, left periventricular white matter, 8mm, stable versus prior."}],
).choices[0].message.content)
```

Measured, on 2026-08-22, from inside the site_a workspace, against the running
deployment:

> The patient has a stable, 8mm left periventricular white matter
> hyperintensity on T2 imaging, consistent with prior findings.

**The cell returns in about a second.** Both timed parts of this beat are
effectively instant — the chat reply streams in under two seconds and the
notebook cell in one — so the three minutes is talking, not waiting. That is
unusual in this script and worth using: it is the one beat where you can afford
to let somebody in the room choose the prompt.

**Say:** "That's the standard OpenAI client library, unmodified, pointed at this
cluster instead of at OpenAI. Any tool that speaks that API — an editor plugin,
a pipeline, an existing product — works against a model running on the hospital's
own hardware by changing one URL."

**Then, and this is the line to land:** "This is the same workspace that was a
hospital site ten minutes ago. One platform: it trains across sites without
moving data, and it serves models without the prompts leaving either."

> **Where the two values come from.** The endpoint is on the deployment's page
> in the dashboard. The API key is in Vault — the deployment's own secret, under
> `/deployments/<uuid>/llm/vllm`. Have both pasted into the notebook **before**
> the demo; fetching them on camera is a minute of typing that proves nothing.

> **`SSL_CERT_FILE` is not boilerplate to apologise for.** It is the platform's
> own CA, which the workspace got in its bundle, and it means this request is
> verified rather than waved through. With a real domain (V1) the line goes
> away. If somebody asks: the only unverified request in the whole demo is the
> `curl -k` that fetches that CA in the first place.

### If it goes wrong

> **The model dropdown in the chat window is empty.** The UI cannot reach the
> engine. Nothing else will work; switch to the API half above, which does not
> go through the UI. `docs/runbook.md` has the diagnosis.

> **The reply arrives all at once instead of word by word.** Cosmetic. Keep
> going and do not mention it.

> **The notebook raises `CERTIFICATE_VERIFY_FAILED`.** The workspace was
> deployed fresh rather than bootstrapped for beat 5, so it has no
> `caios-fl/caios-ca.pem`. Run the bootstrap one-liner and try again.

---

## Beat 8 — What it costs and where it runs (2 min)

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

**"Does the language model know medicine?"**
No, and do not let this one slide: "These are general-purpose open models —
Qwen, Mistral, IBM Granite, LiquidAI. The claim is privacy, not clinical
competence. What the platform gives you is somewhere to run a model where the
prompts never leave; if you had a medically fine-tuned model, it would be one
line of configuration to offer it instead."

**"Is the language model actually private, or is it calling out?"**
"It is a container on a GPU in this cluster with no outbound path in the request
line at all. The weights were downloaded once, at deployment, from Hugging Face
— you can see that in the logs — and after that nothing leaves. The chat
interface talks to the engine over the node's own network, not through the
public address."

**"How big a model can you run?"**
Be exact: "About 3 billion parameters on one of these GPU slices — 10.3 GB
usable. That is a real constraint of the hardware we were given, not of the
platform: the same deployment on a full H100 or across several would run a much
larger model. All nine on the list were deployed and answered before this
demo."

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
| 7 | **Private language model** | **3** |
| 8 | Cluster and roadmap | 2 |
| | **Total** | **25** |

If you are running long, cut beat 6 first — beat 7 makes the same "it is an
endpoint, not a notebook" point with a better example — then beat 2's
deployment (talk over the dropdown instead of deploying). Inside beat 7, the
cuttable half is the chat window, not the notebook: the chat window is the part
they can imagine, and the notebook is the part they cannot get anywhere else.

**Never cut beat 4** — without the problem stated, beat 5 is just numbers going
up.
