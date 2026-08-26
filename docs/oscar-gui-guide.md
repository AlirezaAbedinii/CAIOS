# Running an inference from the GUI — click by click

Every screen name and button label below is the real text in the running
dashboard, checked against `src/assets/i18n/en.json` on 2026-08-26.

---

## First, why this is confusing

Three things about this flow are genuinely surprising, and knowing them up
front removes most of the difficulty:

1. **You do not create an inference from the Inference page.** You start in the
   Marketplace, from a model. The Inference page only *lists* what exists.
2. **There are two ways to send an image, and the good one is not obvious.**
   Since 2026-08-26 this cluster runs Knative, so the **Endpoint** shown under
   *Synchronous calls* works: you POST an image and the answer comes back in
   the same HTTP response. Use that. The MinIO route below it still exists and
   is the right tool for batches, but it is a much longer walk.
3. **Either way, what you send is not the raw image.** It is a small JSON
   document with the image encoded inside it.

None of that is your misreading. It is how the platform works.

---

## The map

```
  CAIOS dashboard                                    MinIO console
  ─────────────────────────────────                  ─────────────────────
  1  Marketplace
        │  click a model
  2  Module detail
        │  Deploy ▾  ->  Inference API (serverless)
  3  Configure training  (the form)
        │  submit
  4  Inference           (the list)
        │  click your service
  5  Inference detail    ── credentials ──────────>  6  upload input.json
                                                          │
                                                     7  download the result
```

Steps 1-5 are in CAIOS. Steps 6-7 are in MinIO. That hand-off is the part
that makes it feel broken; it is not.

---

## Step 1 — Marketplace

Left sidebar → **Marketplace**. You see nine model cards.

For object detection pick **`ai4os-yolo-torch`**. Click the card.

---

## Step 2 — The model's page: find the Deploy menu

Top right of the model page there is a button labelled **`Deploy`** with a
small **▾** arrow. Click it.

A dropdown opens with several options. The one you want is:

> **Inference API (serverless)**
> *Serverless inference API on the project's OSCAR cluster*

**This is the least obvious step in the whole platform.** The word "OSCAR"
appears only in the grey subtitle. The other entries deploy the model as a
normal, always-running deployment — that is *not* what you want here.

> If the item is greyed out: you are not logged in, or your account is not a
> project member.

---

## Step 3 — The form, confusingly titled "Configure training"

The page header says **`Configure training`**. Ignore that — it is upstream's
wording and the same form is reused for everything. You are configuring an
inference service.

Two steps:

**`General configuration`** → a panel headed *Deployment options*

| Field | What to put |
|---|---|
| **Deployment title** | anything, e.g. `object detection` |
| **Deployment description** | optional |

**`Hardware configuration`**

| Field | Suggested |
|---|---|
| **CPUs** | `4` |
| **Memory** | `8000` |

Then submit. A green message appears reading *"OSCAR service created with uuid
ai4papi-…"* and you land on the Inference page automatically.

---

## Step 4 — The Inference page

Left sidebar → **Deployments** → **Inference**. Header **`Inference`**,
subtitle **`Serverless (OSCAR)`**.

A table with four columns: **Title**, **Image**, **Creation time (UTC)**,
**Actions**.

Your service is the row you just made. If it says **`Nothing deployed yet`**,
the creation did not work — go back to step 2.

> **There is no "create" button on this page.** That is why it feels like a
> dead end if you come here first. Creating always starts from the Marketplace.

Click the row.

---

## Step 5 — Inference detail: collect four values

Header **`Inference detail`**. It shows Deployment ID, Docker image, Creation
time, CPUs and Memory, then two sections.

**Ignore `Synchronous calls`.** It shows an *Endpoint* and a *Token*. On this
cluster that path does not work — synchronous invocation needs a component we
deliberately did not install. It is displayed unconditionally by the API.

**Use `Asynchronous calls`.** Write down all four:

| Field on screen | What it is |
|---|---|
| **MINIO bucket** | your service's bucket, `ai4papi-…` |
| **MINIO URL** | the MinIO address |
| **MINIO access key** | username for the next step |
| **MINIO secret key** | password for the next step (click the eye to reveal) |

---

## Step 6 — Prepare the input

Either route needs the same JSON document — the image base64-encoded inside an
`oscar-files` array:

```json
{"oscar-files": [{"key": "files", "file_format": "jpg", "data": "<base64>"}]}
```

If you send a raw JPEG the model runs, fails inside the container, and you get
an error instead of a result.

On `caios_server`:

```bash
bash scripts/oscar-submit.sh --list                       # find your service
bash scripts/oscar-submit.sh <service-name> photo.jpg     # writes the JSON
```

---

## Route A — the endpoint  *(recommended)*

**One request. The result comes back in the response.** This is what the
*Synchronous calls* section of the detail page is for.

Take the **Endpoint** and **Token** from step 5, then:

```bash
curl -H "Authorization: Bearer <TOKEN>" \
     -H "Content-Type: application/json" \
     --data @input.json \
     <ENDPOINT>
```

The detections come back in the response body. **Measured: 5.3-5.9 seconds**,
warm or cold — Knative starts a container if none is running, and the pull is
already cached.

No MinIO, no buckets, no second web app. If you are building anything on top of
CAIOS, this is the integration point: it is an ordinary HTTP API with a bearer
token.

---

## Route B — the bucket  *(for batches)*

Better when you have many files, or want the results kept: drop N images in and
collect N results later.

Open **`https://minio-console.192.168.104.69.sslip.io`**.

1. Sign in with the **MINIO access key** and **MINIO secret key** from step 5.
2. Left menu → **Object Browser**.
3. Open the bucket matching **MINIO bucket** from step 5.
4. Open **`inputs`**, click **Upload**, choose your `.json` file.

**Name it `.json`.** Any other extension and the structured output is not
saved — you get only a log.

The upload is the trigger. Nothing runs until the object lands.

### Collecting the result

Go up one level, open **`outputs`**. After a few seconds:

| File | What |
|---|---|
| `<yourname>.json` | **the result** |
| `<yourname>.log` | the container's output, for when it went wrong |

A real result:

```json
[{"name": "person", "confidence": 0.862, "box": {"x1": 48, "y1": 393, "x2": 244, "y2": 903}},
 {"name": "bus",    "confidence": 0.847, "box": {"x1": 17, "y1": 227, "x2": 809, "y2": 766}}]
```

---

## Warm and cold

The service scales to zero when idle, so its speed depends on whether a
container is already running.

| State | What it means | Response time |
|---|---|---|
| **Warm** | a container is up | ~5 s |
| **Cold** | nothing running | ~5 s + start-up |
| **First ever call** | the model image is still being downloaded | **~3 minutes** |

Measured: Knative keeps the container alive for about **30 seconds** after the
last request, then removes it. That is the whole economic argument — between
requests this service consumes nothing at all.

**Before any demo, send one request** so the image is on the node. Otherwise
the first call looks like a hang.

## How long it takes

| | |
|---|---|
| **The very first request to a new service** | **~3 minutes** — downloading the model image |
| Endpoint (Route A), after that | **~5 seconds** |
| Bucket (Route B), after that | **~13 seconds** |

If your first run seems hung, it is not. It is pulling several gigabytes.
**Run one image through the service before any demo** so the audience sees the
thirteen-second version.

---

## When it does not work

| What you see | Why |
|---|---|
| `outputs/` has a `.log` but no `.json` | Your input file was not named `.json` |
| The log ends in `UnicodeDecodeError: byte 0x89` | You uploaded a raw image instead of the JSON wrapper. `0x89` is the first byte of a PNG |
| Nothing appears in `outputs/` at all | The upload went to the wrong folder. It must be `inputs/`, inside the bucket named on the detail page |
| The Deploy menu item is greyed out | Not logged in, or not a project member |
| The `Endpoint` under *Synchronous calls* returns 404 | The Knative backend is not running. It was installed on 2026-08-26; check `kubectl -n knative-serving get pods` on the OSCAR node |
| The Inference page says `Nothing deployed yet` | Service creation failed, or you are looking at a different account's services |

---

## The short version

> Marketplace → model → **Deploy ▾ → Inference API (serverless)** → fill the
> form → **Deployments → Inference** → click your service → copy the
> **Endpoint** and **Token** → `curl` your JSON at it → the detections come
> back in the response.
>
> The MinIO route is still there for batches, but you do not need it.
