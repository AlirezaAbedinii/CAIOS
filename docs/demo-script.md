# Demo script — the five-minute recording

What is recorded, beat by beat: what is on screen, what to say, and what to do
when a take goes wrong. **About five minutes**, recorded as one clip per beat
and cut together. Nothing waits on camera: everything slow is deployed and
warmed before recording starts, and every load is a cut.

The three tiers use the home page's own words, under *How you work with it*:
**No code**, **Low code**, **High code**. The recording shows each in turn,
then federated learning, then where it all runs.

Setup that is not specific to the recording lives in `docs/runbook.md`. The
25-minute live walkthrough this replaces is in git history:
`git show 2370f10:docs/demo-script.md`. Its questions section is carried over
at the end, corrected.

---

## The cut

| Time | Beat | On screen | Words |
|---|---|---|---|
| 0:00–0:20 | 1. What CAIOS is | the home page, its three tiers | 38 |
| 0:20–0:50 | 2. A new researcher gets in | sign-up, the waiting room, `/admin` approves, the platform opens | 35 |
| 0:50–1:50 | 3. **No code**: a private language model | LLMs, a card, the deploy form, the running model summarising a radiology note | 50 |
| 1:50–2:40 | 4. **Low code**: serverless inference | YOLO, *Deploy* ▾ serverless, the Inference list, one request, detections | 59 |
| 2:40–4:00 | 5. **High code**: the notebook | YOLO as JupyterLab, four cells: detect, count, the serverless call, the LLM | 62 |
| 4:00–4:40 | 6. Federated learning *(to confirm)* | three hospitals training, then the chart | 53 |
| 4:40–5:00 | 7. Close | Statistics | 32 |
| | | | **329** |

329 words is about 2 min 12 s of speech at 150 words a minute, which leaves
the other 2 min 48 s for the screens to be read. The timing sheet at the end
does this beat by beat. Step 7 of `docs/demo-plan.md` replaces these estimates
with two timed read-throughs.

---

## Before you start

### The day before, or the morning of

**1. The platform checks.**

```bash
bash scripts/check-branding.sh        # is it still CAIOS, as served?
bash scripts/verify-cluster.sh        # are the four compute nodes schedulable?
bash scripts/check-llm-config.sh      # is the LLM tool deployable?
```

**2. Clear the stage.** Only the recording's own deployments should be
running:

```bash
nomad job status -namespace=caios < /dev/null
```

On 2026-09-29 two things were in the way, and both are yours to remove:

- **Platform Administrator's "demo no code" LLM**, on `caios-wn-gpu-2`, which
  is `caios_site_c`, a hospital. While the federated demo is up the cluster
  fits exactly one LLM (gotcha 19), and it has to be researcher's.
- **researcher's three serverless services from 2026-08-26.** They answer with
  their job's log, because they predate patch `0022`, and one is titled
  "Testing Classification". Beat 4 shows the Inference list.

**3. Pre-pull, by node role, and pin.**

```bash
cd ansible
ansible-playbook playbook-prepull-images.yml --tags plan -c local   # what each node gets; connects to nothing
ansible-playbook playbook-prepull-images.yml
```

Every node must end reporting **4 of 4 images cached and pinned**. A node that
does not fails the play and says so. Do it on the day: two of the images are
`latest` tags, which a deployment re-checks with Docker Hub (gotcha 28), and a
tag that moved overnight is a download on camera.

### Deploy, in this order, as researcher

The order matters twice. The LLM goes first, so it lands on its own node. The
serverless service comes before the workspace, because staging the notebook
needs both.

**1. The language model.** Marketplace → LLMs → **Qwen3.5-2B**, the default →
deploy. Set the Open WebUI email and password; you log in with them before
recording. It takes one to three minutes. Then check where it landed:

```bash
nomad job allocs -namespace=caios -json <llm-uuid> < /dev/null \
  | python3 -c 'import json,sys; print([a["NodeName"] for a in json.load(sys.stdin)])'
```

It must say `caios-wn-gpu-3`. If it names a hospital (`gpu-0`, `-1` or `-2`),
delete it and deploy again before anything else is running. Its preference
for `caios_llm` is soft, and the one deployed on 2026-09-24 landed on
`caios_site_c`.

**2. The serverless service.** YOLO models → **Deploy** ▾ → **Inference API
(serverless)** → the form's defaults, title `Object detection` → submit. Then
warm it, which also shows you the answer beat 4 will get:

```bash
bash scripts/oscar-submit.sh --list
bash scripts/oscar-submit.sh <service-name> tests/fixtures/modules/grace_hopper.jpg
```

If the model image is not on the OSCAR node yet, the first call downloads it,
which takes about three minutes. With the image there, a new service answers
its first call in 6.8 s and the next in 6.3 s, in JSON: a person and a tie
(measured 2026-09-29).

**3. The high-code workspace.** YOLO models → **Deploy** ▾ → **Dedicated
deployment** → *Service* **Jupyter**, one CPU, and a password you will type on
camera. Then, on `caios_server`:

```bash
bash scripts/stage-high-code.sh <workspace-uuid> <llm-uuid>
```

It puts the notebook and its hidden config into the workspace and runs it once.
That run is the warm-up: YOLO's weights come from GitHub at first use.

**4. Federated learning, if beat 6 stays.**
`bash scripts/deploy-fl-demo.sh`, then `--status`: the three sites must be on
three different hospital nodes. Bootstrap the three sites, and start nothing
yet (`docs/runbook.md`, *Running the federated demo*). Record one complete run
before the take, as beat 6's fallback.

### The windows

Record in a **clean browser profile with the CAIOS CA imported**. That way no
certificate warning appears, and no bookmark, extension or autofill of anybody's
shows.

| Window | Signed in as | For |
|---|---|---|
| A | nobody | beat 1, the home page; then beat 2's sign-up |
| B | Platform Administrator | beat 2's approval, at `/admin` |
| C | researcher (Dana Okafor) | beats 3 to 7, one tab per beat, in order |

Window C's tabs, in order:

1. the LLMs page
2. the LLM's chat, logged in, with a new chat open
3. the YOLO module page
4. Deployments → Inference
5. JupyterLab, with `caios-demo/high-code.ipynb` open and cleared (*Kernel →
   Restart Kernel and Clear Outputs*)
6. Statistics

Outside the browser:

- a terminal on `caios_server`, for beat 4
- four terminals tiled, for beat 6
- `demo/fl/results/federated-vs-baselines.png`

The header shows who is signed in. Window A shows beat 2's new account and
window C shows Dana Okafor. The cut between beats 2 and 3 hides that, and
beats 3 to 7 need a history an account created on camera cannot have (D-85).

### Never on camera

- the Inference detail page's token and MinIO secret key: leave both eye icons
  alone
- the LLM's API key
- any password, except typed into a masked field
- a terminal's `export` lines, or `configs/env/caios.env`: set everything before
  the take, then `clear`

---

## Beat 1 — What CAIOS is · 0:00–0:20

**Window A**, the home page, signed out.

**On screen.** Hold on the headline for a moment, then scroll to *How you work
with it*. Click **No code**, **Low code** and **High code** as you name them.

**Say:**

> This is CAIOS: AI infrastructure for medical and neuroscience research,
> operated in Canada. Nothing you do here is handed to a commercial service.
> You can work with it at three depths: no code, low code and high code.

---

## Beat 2 — A new researcher gets in · 0:20–0:50

**Window A, then B, then A.** Three clips, two cuts.

**On screen:**

1. **Sign in** → **Register**. Fill in the form for a fictional colleague: a
   name, an `example.org` address, a username and a password → **Register**.
2. The waiting room: *Your account is waiting for approval*.
3. **Cut** to window B, `/admin`. The new name is under *Waiting for a
   decision* → **Approve**.
4. **Cut** to window A. Sign out and sign in again, as the waiting room says.
   The platform opens.

**Say:**

> A new colleague signs up with nothing more than an email address. Until
> someone approves them, they can sign in and see nothing. An administrator
> approves the request in one click, and the platform opens.

Typing is dead air. Speed the form up in the edit, or cut from the empty form
to the filled one.

---

## Beat 3 — No code: a private language model · 0:50–1:50

**Window C.**

**On screen:**

1. Marketplace → **LLMs** → the **Qwen3.5-2B** card → **Deploy**. The form
   opens with that model chosen. Show it, and **do not submit**: a second LLM
   would queue for capacity, and say so (gotcha 19).
2. **Cut** to Deployments: researcher's language model, green → *Quick access*
   → the chat.
3. Paste the note and send:

> Summarise this radiology note in one sentence: T2 hyperintense lesion, left
> periventricular white matter, 8mm, stable versus prior study.

Measured 2026-09-29 on Qwen3.5-2B, through its API: one sentence in 0.3–0.4 s,
with no thinking block:

> An eight-millimeter T2 hyperintense lesion in the left periventricular white
> matter that is stable compared to a prior study.

The chat window samples, so expect the wording to change between takes.

**Say:**

> No code. Choose an open language model from the catalogue and fill in a short
> form. A few minutes later it is running on the lab's own GPU, at its own
> private address.
>
> *[the chat]* Here it summarises a radiology note. The note never left this
> cluster, and nobody bills per question.

---

## Beat 4 — Low code: serverless inference · 1:50–2:40

**Window C, then the `caios_server` terminal.**

**On screen:**

1. The YOLO module page → **Deploy** ▾ → **Inference API (serverless)** → the
   form. Show it, and **do not submit**.
2. **Cut** to Deployments → **Inference**: the service you created before
   recording → open it. The *Endpoint* is under *Synchronous calls*; leave the
   token hidden.
3. **Cut** to the terminal:

```bash
curl -s -H "Authorization: Bearer $TOKEN" --data @portrait.json "$ENDPOINT" | python3 -m json.tool
```

JSON comes back in about 6 s: a person at 0.909 and a tie at 0.611, each with
a box. That is this exact command, measured 2026-09-29 against a service made
the way step 2 above makes one.

Set up before the take, off camera. The endpoint and token come from the
detail page: reveal and copy them before recording, never during it.

```bash
export ENDPOINT='<Endpoint>' TOKEN='<Token>'
export CURL_CA_BUNDLE=/mnt/CAIOS/compose/certs/caios-ca.pem
python3 -c 'import base64, json, sys; print(json.dumps({"oscar-files": [{"key": "files", "file_format": "jpg", "data": base64.b64encode(open(sys.argv[1], "rb").read()).decode()}]}))' \
    /mnt/CAIOS/tests/fixtures/modules/grace_hopper.jpg > portrait.json
clear
```

The service reads JSON with the image inside, not the image itself
(`docs/oscar-gui-guide.md`, step 6). That is why `portrait.json` exists, and
why it is made off camera.

**Say:**

> Low code. The same catalogue, but this time the model is published as a
> service that costs nothing while nobody is using it. It gets an address and a
> key.
>
> *[the terminal]* One request from a script: an image in, and back come the
> objects in it, where they are and how sure the model is. Between requests,
> nothing is running.

---

## Beat 5 — High code: the notebook · 2:40–4:00

**Window C.**

**On screen:**

1. The YOLO module page → **Deploy** ▾ → **Dedicated deployment** →
   *Service*: **Jupyter**. Show the choice, and **do not submit**.
2. **Cut** to Deployments: the workspace → *Quick access* → JupyterLab. Type
   the password into the masked field.
3. Open `caios-demo/high-code.ipynb` → *Run → Run All Cells*.

| Cell | On screen | Measured 2026-09-27 |
|---|---|---|
| 1 | the bus photograph, its detections drawn | 1.4 s |
| 2 | the count: four people, a bus, a stop sign | instant |
| 3 | the same count, from the serverless service | 5.2–8.2 s. Cut or speed up |
| 4 | *"A street photo captures a bus and a stop sign alongside four pedestrians walking along the sidewalk."* | 0.3 s |

Cell 3 takes 5 to 8 seconds whether or not the service is warm. Once the image
is on the OSCAR node, a cold start measured about the same as a warm call
(`docs/oscar-gui-guide.md`, *Warm and cold*). Cut it or speed it up rather than
wait.

**Say:**

> High code. The same model again, opened as a full JupyterLab workspace, with
> its own code and environment.
>
> *[cell 1]* It finds the bus and the people, and draws them.
>
> *[cell 3]* From the same notebook I can call the serverless service from a
> moment ago,
>
> *[cell 4]* and ask our private language model to describe what was found.
> Three ways in, one platform, and nothing leaves it.

---

## Beat 6 — Federated learning · 4:00–4:40 · *to confirm*

Still undecided. It is scripted here because the headline feature is federated
learning. If it is cut, its 40 seconds go to beat 5.

**On screen:**

1. Four terminals, tiled: the server and the three sites, already
   bootstrapped. Start the server, then the three sites; training starts when
   the third connects.
2. The rounds, at 2× in the edit. Ten rounds took 34.6 s measured, so about
   17 s on screen.
3. **Cut** to the chart, `demo/fl/results/federated-vs-baselines.png`.

**Say:**

> And this is what makes it matter for hospitals. Three sites, each training on
> scans that never leave its own machine. They share only what they learned.
>
> *[the chart]* The shared model reaches 0.853 accuracy. The best hospital on
> its own reaches 0.806, and pooling everything, which none of them is allowed
> to do, 0.865.

---

## Beat 7 — Close · 4:40–5:00

**Window C**, Statistics.

**Say:**

> All of this runs on a seven-node cluster on Compute Canada's Arbutus cloud,
> under the lab's own allocation. Next come a public certificate, and models in
> the catalogue that use its GPUs.

---

## When a take goes wrong

Record one clean take of every beat during the rehearsal. That is the fallback
clip. If a live take goes wrong, record the other beats and splice the fallback
in.

| Beat | What you see | What it is, and what to do |
|---|---|---|
| 3 | the chat's model dropdown is empty | the interface cannot reach the engine (`docs/runbook.md`); use the fallback |
| 3 | the reply arrives all at once, not word by word | cosmetic; keep going |
| 3 | the deployment is orange, `queued` | a second LLM is running somewhere; delete it (gotcha 19) |
| 4 | the request takes minutes | the model image is not on the OSCAR node: the warm-up was skipped. Cut, send one request, retake |
| 4 | the answer is a log, not JSON | a service created before 2026-09-27; use the new one |
| 5 | cell 3 takes much more than 8 s | the model image is not on the OSCAR node, or it is busy; send one request from the terminal, then retake |
| 5 | cell 1 prints a download | the staging run was skipped; run `stage-high-code.sh` |
| 6 | a site does not connect | restart that site; the server waits for all three. Otherwise, the recorded run |
| any | a deployment pulls an image | the pre-pull did not report 4 of 4 on that node; see *Before you start* |

---

## After the recording

- **Beat 2's account.** Deny it at `/admin`, which disables it, then delete it
  in Keycloak's admin console under *Users*.
- **The federated demo:** `bash scripts/deploy-fl-demo.sh --delete`.
- **The rest**, meaning the LLM, the workspace and the serverless service,
  either delete it or leave it up for the questions.

---

## Timing sheet

Words are counted from the *Say* blocks above, stage directions excluded.
Speech is estimated at 150 words a minute. Waits are measured, and cut or sped
up where marked.

| Beat | Slot | Words | Speech | What fills the rest |
|---|---|---|---|---|
| 1 | 20 s | 38 | 15 s | the headline, three tab clicks |
| 2 | 30 s | 35 | 14 s | the form, sped up; two cuts |
| 3 | 60 s | 50 | 20 s | the card and the form; the reply, 0.3–0.4 s |
| 4 | 50 s | 59 | 24 s | the menu, the list, the detail; the request, ~6 s |
| 5 | 80 s | 62 | 25 s | the Service choice, JupyterLab, four cells: 1.4 s, instant, 5–8 s (cut), 0.3 s |
| 6 | 40 s | 53 | 21 s | ~17 s of rounds at 2×, the chart |
| 7 | 20 s | 32 | 13 s | Statistics |
| | **5:00** | **329** | **2:12** | |

If it runs long, cut from the top of this list:

1. beat 2's second cut, the sign-out and sign-in, since the approval itself is
   the point
2. beat 4's form, going straight from the menu to the Inference list
3. beat 6, which gives its 40 seconds to beat 5

---

## Questions you will be asked

The recording will be followed by questions. These were the live demo's, and
the facts in them are updated to 2026-09-29.

**"Is the data really not moving?"**
Open `demo/fl/client.py` and point at `fit()`. It returns weights, a slice
count and an accuracy number. Then: "and each site's bundle physically contains
only its own slices. That's built, not promised."

**"Could a hospital reconstruct another's data from the weights?"**
Be straight: "Gradient inversion is a real attack, and this demo does not
defend against it. The platform ships differential privacy and secure
aggregation as options we haven't turned on. For a production deployment you
would."

**"Why is the accuracy not higher?"**
"The images are downsampled to 64×64 so a round finishes while you watch.
There are three thousand of them, and the model is deliberately small. The
result is the comparison between the three lines, not the absolute number."

**"How much of this did you build?"**
"Almost none of the platform, deliberately. It's AI4OS, which the EU funds and
maintains. What we built is the Canadian deployment, the medical curation, the
federated demo, and a set of small, documented patches, each with the reason
it exists."

**"Can we run our own models on it?"**
Yes. Beat 5's workspace is exactly that, and the marketplace is a git
repository of module definitions.

**"Why do the catalogue's models run on CPU?"**
"Their published images were built before this cluster's GPUs existed, and
cannot use them. We measured what a rebuild on a current base would do: YOLO's
own code trained an epoch in under five seconds on one of these GPU slices. The
rebuild comes after this recording." The language models and the development
environment use the GPUs now. The federated demo runs on CPU by choice: PAPI
allows one account two GPUs, and there are three hospitals (gotcha 10).

**"Does the language model know medicine?"**
No, and do not let this one slide: "These are general-purpose open models:
Qwen, Mistral, IBM Granite, LiquidAI. The claim is privacy, not clinical
competence. What the platform gives you is somewhere to run a model where the
prompts never leave. A medically fine-tuned model would be one line of
configuration to offer."

**"Is the language model actually private, or is it calling out?"**
"It is a container on a GPU in this cluster. The weights were downloaded once,
at deployment, from Hugging Face, and after that nothing leaves. The chat
interface talks to the engine over the node's own network, not through the
public address."

**"How big a model can you run?"**
Be exact: "About 3 billion parameters on one of these GPU slices, which have
10.3 GB usable. That is a limit of the hardware we were given, not of the
platform. The same deployment on a full H100, or across several, would run a
much larger model."

**"What does the serverless service cost when nobody is using it?"**
"Nothing. Between requests no container runs; the first request after an idle
spell starts one in about the time the request itself takes."
