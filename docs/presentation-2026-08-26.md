# CAIOS — Project Status

**Canadian Artificial Intelligence Operating System**
A research platform for medical and neuroscience AI, running on our own GPU nodes
on Compute Canada.

*Week of 19–26 August 2026. Previous update: 19 August.*

---

## The headline

> **The platform left the VPN, and grew two capabilities it did not have last
> week.** It is now reachable from the open internet at a real address. On it, a
> researcher can run a private language model on our own GPU — no data leaving
> the country, no OpenAI account — and can serve any model in the catalogue as an
> API that **consumes nothing at all between requests.**

Last week the report was "the platform is finished; what remains is rehearsal, a
web address and a recording." Two of those three turned out to be bigger than
they looked, and in solving them we added two features that materially change
what the grant application can claim.

Nothing is blocking. One half-day of configuration stands between the current
state and a demo that runs entirely over the public internet.

---

## What is new since 19 August

| | Status |
|---|---|
| **Public internet access** — no VPN required for the control plane | **Working** |
| **Private language model on our own GPU** — nine models, chat interface, API | **Working** |
| **Serverless inference** — call an endpoint, or drop a file in a bucket | **Working** |
| **Deployments reachable publicly** (workspaces, chat windows) | One config block short — half a day |
| Dashboard visual pass | Built and verified, not yet deployed |
| Rehearsed and recorded walkthrough | Still outstanding |
| Trusted certificate on a real domain | Still outstanding — **and now the sharpest item** |

The cluster grew from five nodes to **seven**. Neither addition cost anything:
both machines already existed and were idle.

---

## 1. The platform is on the public internet

Anyone with the address can now open CAIOS in a browser. No VPN, no jumpserver,
no SSH. Login, the marketplace, deployments, the API and its documentation are
all served publicly.

This was expected to need a new machine running a proxy. It did not. A Compute
Canada floating IP is an address translation rather than a network card, so it
mapped straight onto the machine already terminating our traffic — **zero new
infrastructure, and the change was four hostnames and two certificates.**

### What is public, and what is deliberately not

| Public | Not public, and should stay that way |
|---|---|
| Dashboard, login, the API and its docs | The cluster scheduler and its UI |
| The federated-learning demo materials | The service registry |
| Our certificate authority, for visitors to install | SSH, on every machine |

### The one gap

Running *deployments* — a researcher's workspace, a chat window — still answer
only on their private addresses. The public address reaches the front door
correctly; the front door has no rule yet for passing those particular requests
through to the machine that serves them. **One block of configuration, about
half a day**, and it is written and reviewed already.

We are treating it as a deliberate step rather than a leftover, because closing
it makes every running GPU workspace publicly reachable, and those currently sit
behind a single shared password. That is a decision to make on purpose.

### The consequence for the recording

A visitor's browser does not trust our certificate authority, so the first thing
anyone sees is a security warning, and they must install a certificate before the
dashboard will work at all. **We investigated using a free public certificate and
it is not viable on the free address service we are on** — the certificate
authority treats every `sslip.io` name in the world as one domain with a shared
weekly quota, so issuance would fail unpredictably, at the worst possible moment.

With a real domain the whole problem disappears in one step, for the control
plane and every deployment at once. See the questions at the end.

---

## 2. A private language model, on our own GPU

A researcher picks a model from the catalogue, fills in a short form, and about
three minutes later has a **chat window at their own web address** — the same
experience as ChatGPT, running on a GPU in this cluster, with nothing sent
anywhere.

For a medical audience the argument is short: this is the way to use a language
model on patient notes at all. The alternative is a commercial API, which for
identifiable data is not an option.

**Nine models are offered**, from Qwen, Mistral, IBM Granite, LiquidAI and
DeepSeek, sized to fit our GPU. Every one of them was deployed and tested.

It is also an **API, not only a chat window.** The demo shows the stock OpenAI
Python client — unmodified, the library any researcher already has — pointed at
our cluster instead of at OpenAI, from the same workspace that was a hospital
site ten minutes earlier. Existing code moves over by changing one address.

### Measured, not asserted

The two headline features were run at the same time on purpose:

| | |
|---|---|
| Ten federated training rounds, across three sites | **34.6 s** |
| The language model answering, throughout that window | **71–81 ms** per token |
| Either one degrading the other | **No** |

### One finding we would rather have found later

While preparing this work we discovered that **no GPU workload on this cluster
had ever actually used its GPU.** The scheduler was handing containers a device
the graphics library could not address. Every diagnostic said the GPU was
present; anything that tried to compute on it silently fell back to the
processor. This had been true since the cluster was built, and looked entirely
healthy for a week.

- **Found and fixed the same day**, 19 August, by a single version change, rolled
  out one machine at a time with no interruption to running work.
- **The federated learning result reported last week is unaffected.** Those
  clients run processor-only by design — a platform limit caps one account at two
  GPUs, so we never asked for one. The numbers stand exactly as reported.
- Every GPU check in this project now multiplies two matrices and compares the
  answer. Being shown the hardware is not evidence that it works.

We are reporting this rather than quietly filing it, because it is the kind of
thing a reviewer would be right to ask how we would catch.

---

## 3. Serverless inference — the model costs nothing while nobody is asking

The last dashboard section that was wired but dead now works.

> A researcher deploys a model as an **inference service**. Between requests
> there is no container, no reserved processor, no reserved memory — **nothing
> running at all.** A request arrives, the model starts, answers, and goes away
> again.

Everything else on this platform holds hardware for as long as it exists. This
does not. The practical consequence is the sentence worth saying to a grant
panel: **fifty models can be available on hardware that would only hold five
running.**

There are two ways to use it, and both work:

| | How it feels | Measured |
|---|---|---|
| **An endpoint** | Send an image, get the answer back in the same reply. An ordinary web API with a token — the integration point for anything built on top of CAIOS | **5.3–5.9 s** |
| **A folder** | Drop files in, collect results later. The right tool for a batch of a thousand scans | **13 s** per file |

**A real run**, on the object-detection model from our catalogue:

```
person      confidence 0.86      person      confidence 0.84
person      confidence 0.85      person      confidence 0.37
bus         confidence 0.85      stop sign   confidence 0.25
```

Six objects, with boxes and confidences, from a photograph. Before the request
and thirty seconds after it, nothing was running.

The honest cost, which we will state rather than hide: **the very first request
to a brand-new service takes about three minutes** while the model is downloaded
onto the machine. Afterwards it is the numbers above. For the demo we send one
request beforehand, exactly as we pre-load images before the federated beat.

This runs on a **seventh machine** that was sitting idle — 16 processors and
58 GB, five times the processing capacity of any other node in the cluster. It
is deliberately kept separate from the rest, so nothing about it can affect the
federated demo or the language model.

### It also fixed something embarrassing

The dashboard's Inference page has shipped in every build since the platform went
up, with a permanent link in the sidebar — and it returned an error to any
logged-in user who clicked it, because we had switched the feature off. Nobody
had clicked it. It now either works or says plainly that it is not configured.

The general rule this produced, now applied in four places: **a feature we do not
run must look unconfigured, not broken.**

---

## 4. The dashboard's appearance

Two things worth reporting, one of them a failure.

**We shipped a bad change and rolled it back the same day.** An attempt to serve
the dashboard's fonts from our own machines — so the interface does not depend on
an internet connection — removed an icon set it wrongly believed was unused. Six
icons in the top bar and filters turned into their own names in oversized text.
The test suite passed, because the test repeated the same faulty reasoning as the
script it was testing. **Reverted within hours; nothing else was affected.**

The lesson has changed how we work: a change to anything visual is now verified
by injecting it into the live page in a browser and photographing the result,
before anything is deployed. A check that agrees with itself proves nothing.

**Done that way, the typography pass is built and verified** — and it found that
the dashboard has been rendering **two unrelated typefaces on every page** since
day one, not by choice but because the theme asks for a font nothing ever loads.
Tables now use aligned figures in the columns a reader compares, and upstream's
heavy drop-shadows are replaced with hairlines. It is built and photographed and
**not yet deployed**, which is the right order given the week's other lesson.

Separately, and worth a line for the sovereignty story: the dashboard used to
report our traffic to a third-party analytics service and fetch its model list
from GitHub, in the visitor's browser. **Both are now served by this cluster.**

---

## State of the work

```
Foundation & infrastructure   ██████████████████████  100%
User accounts & security      ██████████████████████  100%
Web dashboard & control       ██████████████████████  100%
Federated learning demo       ██████████████████████  100%
Medical content & branding    ██████████████████████  100%
Private language model        ██████████████████████  100%
Serverless inference          ███████████████████░░░   ~85%
Public internet access        ██████████████████░░░░   ~80%
Dashboard visual pass         ████████████████░░░░░░   ~70%

Toward a working demo         ██████████████████████  100%
Including final polish        ███████████████████░░░   ~85%
```

The last line moved from 80% to 85% while the scope underneath it grew by two
features. Read it as: the demo has been runnable throughout, and the work since
has been widening what it can show.

### The cluster, now seven machines

| | |
|---|---|
| Control plane and web services | 1 |
| Front door | 1 |
| **Hospital sites** (GPU) | **3** |
| Language-model host (GPU) | 1 |
| Serverless inference host | 1 |

The last two were both idle machines already in the project. No new quota was
requested, and the three hospital nodes were not touched.

---

## What is left

Roughly two and a half days, none of it risky.

1. **Close the public-deployment gap** *(half a day)* — one configuration block,
   already written. Do it deliberately: it makes every workspace publicly
   reachable, and they share one password today.
2. **Click through the inference pages in a browser** *(half a day)* — the list
   and detail screens have never been seen against real data. Every previous time
   we have done this it has found something no script could: three faults at one
   stage, two at another, six broken images behind a page that reported success.
3. **Decide whether serverless earns a slot in the walkthrough** *(half a day)* —
   the demo is 25 minutes over 8 beats and already runs long. Our recommendation
   is to *replace* the existing "serve it as an API" beat rather than add a ninth:
   same model, same request, and a sentence about what it costs while idle.
4. **Rehearse end to end, twice, the second time from a cold start** *(1 day)*.
5. **Record it.**

**Security items now that this is genuinely public**, in order of sharpness:

- The shared workspace password, before deployments become publicly reachable.
- Our secrets service runs in a development mode appropriate to a VPN-only demo
  and not to a public address. Either restrict it or move it.
- No rate limiting in front of the login endpoint.

None of these are hard. They were correct decisions for a private demo and are
the wrong ones for a public one, which is a distinction worth making explicitly
rather than discovering.

---

## Questions

### 1. Can we buy a domain name? (~$15/year) — *now the highest-value half-day left*

Asked last week; it has gone from cosmetic to structural. The platform is public
now, and the free address service we are using **cannot be given a trusted
certificate** — that is verified, not assumed. So today every visitor, and every
viewer of the recording, meets a security warning and has to install a
certificate before the dashboard works.

A real domain solves it in one step for the control plane and every deployment at
once, with nothing for a visitor to install. Domains take a day or two to become
usable, so this needs a yes or no.

### 2. Is CAIOS a demo, or something the lab keeps running?

Not urgent, but it now decides more than it did last week. Going public changed
the threat model, and how we handle credentials and the secrets service should
follow from this answer rather than be revisited twice.

### 3. Does the Statistics page need historical usage?

Unchanged and still short-fused. The page correctly shows live activity. Showing
*historical* graphs needs a service collecting data continuously for days, so if
it is wanted, collection has to start almost immediately.

**Default in effect:** live data only.

### 4. Live demonstration, or recorded?

We recommend recording regardless. The public address now exists, so a live
external demonstration is genuinely possible — which makes this a real choice
rather than a theoretical one.

### 5. One more machine with a lot of memory?

Still the only way to get the annotation tool back. New information: the
serverless machine has 58 GB, against the ~71 GB that tool wants in one place.
Closer than anything we have had, and still short. Not on the critical path.

---

## Summary

The platform does three things now, and each is a separate argument in the grant:

- **Federated learning** — a model trained across three hospital sites, reaching
  within 1.2 percentage points of pooling all the data, with no data moving.
- **A private language model** — on our own GPU, in our own country, with the
  standard API so existing code moves over by changing one address.
- **Serverless inference** — any model in the catalogue served as an endpoint
  that consumes nothing while nobody is asking.

All three are on the public internet, and all three were measured rather than
asserted. What remains is half a day of configuration, a browser pass, and
rehearsal.

**The one decision worth making this week is still the domain name.** It was
fifteen dollars and half a day last week. It is the same fifteen dollars now, and
it is the difference between a public platform and a public platform that greets
every visitor with a security warning.
