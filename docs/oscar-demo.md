# Serverless object detection — the scenario

A demo beat for OSCAR, built and measured end to end on 2026-08-26. Everything
below is a recorded run, not a plan.

Read with `docs/oscar-plan.md` (how it was built) and `docs/demo-script.md`
(the walkthrough this could join).

---

## The scenario

> A researcher has a folder of images and wants objects found in them. They
> want an endpoint they can keep, not a GPU they have to babysit — and they do
> not want to pay for a machine that sits idle between batches.

They pick a detection model from the marketplace, deploy it as a **serverless
inference service**, and from then on: **drop a file in, get a result out.**
Between requests nothing runs and nothing is consumed.

That last sentence is the whole point of the beat. Everything else in CAIOS —
the dev environment, the federated demo, the LLM — holds hardware for as long
as it exists. This does not.

---

## What was actually run

**Model:** `ai4oshub/ai4os-yolo-torch` — YOLO, detection *and* classification,
already in `catalog/keep.txt`.

**Input:** the canonical YOLO demo photograph — a bus with people, 810x1080.

**Result**, from `outputs/detect.json`:

```
person     conf 0.862   box (  48, 393)-( 244, 903)
person     conf 0.849   box ( 669, 392)-( 810, 876)
bus        conf 0.847   box (  17, 227)-( 809, 766)
person     conf 0.843   box ( 221, 405)-( 344, 858)
person     conf 0.369   box (   0, 550)-(  61, 871)
stop sign  conf 0.251   box (   0, 251)-(  33, 325)
```

Six objects, with bounding boxes and confidences.

**Timings, measured:**

| | |
|---|---|
| First run (pulls the model image) | **3 min 12 s** |
| Every run after (image cached) | **13 s**, upload to result |
| Pods running between requests | **0** |

---

## Doing it in the browser

### 1. Deploy the service

**Marketplace → any module → `Deploy` ▾ → `Inference API (serverless)`**

> **This is the least discoverable thing in the whole platform.** The OSCAR
> option is a menu item inside the *Deploy* dropdown on a module's detail page,
> and it is labelled *"Inference API (serverless)"* — the word OSCAR appears
> only in the subtitle. The Inference page itself has no create button at all,
> so a user who goes looking there finds a dead end. Say the path out loud when
> demoing; do not let anyone hunt for it.

Fill in the form (4 CPU and 8 GB suits YOLO), submit. It lands on
**Deployments → Inference**.

### 2. Get the bucket and credentials

Open the service from that list. Its detail page shows the bucket name, the
MinIO endpoint, and an access key and secret.

> The secret is rendered in the page. Worth knowing before it is on a
> projector.

### 3. Prepare the input — the step nothing tells you about

**The object you upload is not the image.** It is a JSON document with the
image base64-encoded inside it:

```json
{"oscar-files": [{"key": "files", "file_format": "jpg", "data": "<base64>"}]}
```

because the FDL script PAPI ships does `params = json.loads(f.read())`.

Upload a JPEG directly and the job runs, fails inside the container, and leaves
a `UnicodeDecodeError` in `outputs/` — `byte 0x89` for a PNG, which is its
magic number, because the script opened a binary file as text. Nothing in the
dashboard warns about this.

`scripts/oscar-submit.sh` does the wrapping:

```bash
bash scripts/oscar-submit.sh --list
bash scripts/oscar-submit.sh <service-name> photo.jpg
```

**Name the file `.json`.** The script keys off the extension: any other name
and it skips saving the model's structured output, leaving only a log.

### 4. Upload it

Browser: **`https://minio-console.192.168.104.69.sslip.io`**, sign in with the
key and secret from the detail page, and upload into `<service>/inputs/`.

The upload *is* the trigger. Nothing is running until the object lands.

### 5. Collect the result

`<service>/outputs/` gains two objects:

| File | What |
|---|---|
| `<name>.json` | the model's structured output — the detections |
| `<name>.log` | stdout from the container, for when it goes wrong |

Download the JSON from the same console. Done.

---

## Demoing it, in about three minutes

**Deploy the service before the audience arrives, and run one image through
it.** That pulls the image onto the node, which turns the live run from three
minutes into thirteen seconds. This is the same reasoning as pre-pulling images
before the federated beat.

**Say, while showing Deployments → Inference:**
> "This service exists, and it is consuming nothing. No CPU, no memory, no GPU.
> There is no container running."

**Show it:** `kubectl get pods` in the service namespace — empty.

**Upload the image.** Then, within a few seconds, a pod appears, runs, and
completes. Download the JSON and read out the detections.

**Say:**
> "Four people, a bus and a stop sign, with boxes and confidences. The
> container existed for about eight seconds and is already gone. Fifty models
> can be *available* on hardware that would only hold five running."

### The honest framing, if asked

> "This is the same model you could deploy as a dedicated service on the
> previous tab. The difference is not the model, it is the economics: that one
> holds a machine, this one holds a bucket."

---

## What will go wrong, and what to say

**The first run takes three minutes.** It is pulling the model image. Warm it
before the demo; if it happens live, say so plainly — it is a cold start, and
cold starts are the honest cost of scale-to-zero.

**The result is a stack trace instead of detections.** The input was not
wrapped as JSON. See step 3.

**`outputs/` has a `.log` but no `.json`.** The input file was not named
`.json`, so the script did not save structured output.

**The detail page shows a `/run/<service>` endpoint that does not work.** That
is *synchronous* invocation, which needs Knative, and this cluster is
asynchronous-only by choice (D-51). It is displayed unconditionally by PAPI.
Do not click it in front of anyone; the async path above is the one that works.

**Nothing appears at all.** Check the per-user namespace —
`oscar-svc-<first 8 characters of the OIDC subject>`, not `oscar-svc`. That is
where OSCAR puts the Jobs, and it is the single most confusing thing about
watching this work.

---

## Why this beat is worth having

The demo already shows a model served as a REST API (beat 6). This shows the
same thing with the resource cost removed, and it is the only part of the
platform that can claim it.

Against that: it is a third infrastructure story in a 25-minute walkthrough,
and `docs/feature-coverage.md` argued — correctly — that scale-to-zero is
close to invisible when one presenter sends one request. **The recommendation
in `docs/oscar-plan.md` stands: replace beat 6 rather than adding a ninth
beat.** The same model, the same REST call, and a sentence about what it costs
while nobody is asking.
