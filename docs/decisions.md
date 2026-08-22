# Decisions

Append-only log. Newest at the bottom of each section. Claude Code should add an entry
whenever it makes a choice future-us would want explained.

Format: **D-nn** for settled, **Q-nn** for open.

---

## Settled

**D-01 — We deploy AI4OS, not a fork.**
iMagine, AI4Life and KMD4EOSC are existing branded instances of the same stack, and
`ai4-docs` has an onboarding checklist for a new project. We follow it.

**D-02 — Flavour name is `pacslab`.** *Superseded by D-10.*

**D-03 — Control-plane services run as Docker Compose, not as Nomad jobs.**
Easier to debug in a three-week window. *Amended 2026-08-12:* they run on `caios_server`
rather than a dedicated node (D-11), and the set is Keycloak, Vault, PAPI, dashboard and
Caddy — not MinIO (D-15).

**D-04 — Three Nomad datacenters named `site_a`, `site_b`, `site_c`.**
*Superseded by D-13 — upstream Ansible cannot do this.*

**D-05 — GPU nodes are built from the `gpu-enabled-instance` volume snapshot.**
Skips NVIDIA driver installation and GPU activation. Do not follow the manual dkms
instructions.

**D-06 — `IS_PROD` is set to `false` on PAPI.** *Revised 2026-08-12.*
Originally "stays unset". That is wrong when running the official image: `conf.py`
defaults to `false`, but `docker/Dockerfile` then sets `ENV IS_PROD=True`, so leaving it
unset inherits `True` and PAPI refuses to start. It must be set explicitly. Dev mode
downgrades missing-token errors to warnings, and we are not running Harbor, Jenkins, the
provenance API or LiteLLM.

**D-07 — Public datasets only.**
No real patient imaging. Removes ethics and privacy questions entirely and means no
audience question is unanswerable.

**D-08 — Branding happens early, not late.**
Original brief deferred it. Since this supports a grant application, a walkthrough
covered in someone else's logos undercuts the point. Half a day, high payoff.

**D-09 — Out of scope for v1.**
OSCAR serverless, Harbor, Jenkins publishing pipeline, drift monitoring, provenance,
low-code pipelines, carbon accounting, real PACS/DICOM archive integration. These go on
a roadmap slide.

---

## Settled on 2026-08-12

Decisions taken after verifying every upstream repository at HEAD, and after the
supervisor prioritised speed to a working demo over completeness.

**D-10 — The name is CAIOS, and `caios` is the flavour slug.** *Supersedes D-02.*
Canadian Artificial Intelligence Operating System. Used for the Nomad namespace, the
dashboard tenant, the theme directory and the `angular.json` build configuration.
Every user-visible string that upstream renders as AI4OS/AI4EOSC/AI4Dashboard becomes
CAIOS. PACS Lab branding, if wanted, is added later as a second theme — the stack
supports several, so nothing is lost by not doing it now. Nothing was built under
`pacslab`, so there is no migration cost.

**D-11 — Five nodes: one brain plus web services, one ingress, three sites.**
`caios_server` runs the Consul/Nomad servers *and* the Compose control plane, because
PAPI then reaches Nomad over loopback with the mTLS certificates Ansible already put on
that node. That removes cert-copying and cross-node 4646 exposure, and it frees a node
to be a third hospital site — three sites on five nodes rather than two. Full layout in
`docs/infrastructure.md`.

**D-12 — MVP uses sslip.io plus a self-signed wildcard; a real domain is V1.**
*Resolves Q-01, which was blocking.* The platform genuinely requires per-deployment
hostnames — Traefik routes on the Host header, so "just expose a port" cannot work.
But sslip.io resolves any name ending in an IP back to that IP, which gives us working
wildcards with no DNS account and no waiting on anyone. The only thing it cannot give us
is a trusted certificate, because Let's Encrypt issues wildcards only over DNS-01.
Accepted cost: a browser warning on first visit. Swapping in a real domain later changes
two values.

**D-13 — Sites are node-level, not datacenter-level.** *Supersedes D-04.*
`roles/nomad/templates/nomad.j2` writes `datacenter = "{{ consul_dc_name }}"` into every
agent, so all nodes share one datacenter and the per-host `nomad_dc` variable only names
files. Three datacenters would mean editing a vendored role. MVP therefore runs one
namespace and picks the site at deploy time; V1 maps three VOs to three namespaces, one
per node, which makes site membership enforced by login rather than chosen — a stronger
claim than three datacenters would have given us anyway.

**D-14 — We run our own Vault.** *Resolves the Vault question.*
Not optional: deploying the federated server makes PAPI call Vault before it contacts
Nomad, so without one the headline demo fails. Dev mode for MVP — in-memory, auto-unseal
— because losing secrets on restart is a feature for a demo. The alternative (patching
Vault out of the FL path, ~2 hours) stays in the fallback ladder; it would cost us the
per-client revocable-token beat.

**D-15 — Storage follows the platform: Nextcloud over WebDAV, and it is V1.**
The platform offers `rclone_vendor: [nextcloud]` only, and `storage.py` hardcodes the
Nextcloud DAV path; MinIO appears upstream only under OSCAR, which we are not running.
So substituting MinIO would mean patching five templates and breaking the dashboard's
credential flow. For MVP, datasets are copied into the dev environment directly. What we
lose until V1: the Storage tab, and "data already mounted".

**D-16 — CVAT is deferred until a large-RAM node exists.**
It is a single Nomad group of 22 containers totalling ~71 GB RAM, all of which must land
on one machine. It is demo beat 4 of 7, roughly three minutes. Not worth reshaping the
cluster for.

**D-17 — Upstream is pinned, and changes to it are patches, not edits.**
`scripts/clone-vendor.sh` pins each repository to a specific commit; `patches/` holds the
four source edits that cannot be configuration. This is what keeps "we deploy AI4OS, we
do not fork it" (D-01) honest, and what lets us take upstream fixes later.

**D-18 — FL clients run CPU-only.**
PAPI caps one user at 2 GPUs across all running deployments, so three GPU-backed clients
would be rejected on the third. The demo downsamples hard anyway — a federated round has
to complete in seconds — so CPU is sufficient and avoids a confusing quota error in front
of an audience.

---

## Settled on 2026-08-15

Decisions taken while building the federated learning demo (Stage 4).

**D-19 — The Nomad scheduler runs in `spread` mode, cluster-wide.**
Nomad defaults to `binpack`: fill one node before starting the next. At 3 cores
a node that packs two hospital workspaces onto one machine and leaves the third
idle. The training would be identical and the accuracy numbers unchanged — but
the demo claims three hospitals on three machines with data that never moves,
and two of the three would have been the same computer. `spread` sends each
deployment to the least-allocated node, so the three land one per site without
anyone choosing where. One idempotent playbook
(`ansible/playbook-scheduler-config.yml`), no patches.

Rejected alternative: a "which hospital?" dropdown in the deploy form, mapped to
a Nomad constraint on node metadata. That needs a PAPI patch *and* an Angular
patch — the dashboard builds its configuration form from hardcoded fields, not
from PAPI's schema, so a new key in `user.yaml` would simply not appear — plus a
dashboard rebuild. Days of work and two more patches to carry, for placement one
cluster setting already gives. Enforcing site membership by login remains V1
item 3, which is the stronger version of the claim anyway.

**D-20 — The demo dataset is Cheng et al.'s brain-tumour MRI set.**
*Resolves Q-08's default rather than the question itself.* 3064 T1-weighted
contrast-enhanced slices from 233 patients, three tumour types, on figshare
under CC BY 4.0, no registration. Public data only, per D-07.

Three classes is what makes the federated story legible: one site can be given
mostly meningioma, another mostly glioma, the third a spread, and the resulting
models are visibly different. Two classes would be thin and ten would be noise.

Downsampled to 64×64 — a federated round has to finish in seconds on a CPU-only
client (D-18), and nothing about the mechanism changes with resolution. Swapping
the dataset is still cheap: `prepare_data.py` produces one array file and
everything downstream reads that.

**D-21 — Splits are by patient, and there is one shared test set.**
A patient contributes several near-identical slices. Splitting at slice level
puts the same patient in training and test, lifts the score several points, and
makes every number in the chart meaningless — and it is the first thing a
careful reviewer checks. So assignment is by patient everywhere, which costs
nothing because a patient has one tumour type.

The test set is held out before any site is formed and shared by all of them.
Site-alone, centralised and federated have to be scored on identical data or the
three lines cannot be compared. Clients therefore evaluate the *global* model on
that shared set rather than on local data, which also means any client's curve
is the federated curve.

**D-22 — Each site gets a bundle containing only its own data.**
MVP has no Nextcloud (D-15), so datasets are copied into the workspace.
`scripts/build-fl-bundles.sh` builds one tarball per site, served by Caddy at
`/fl/` on the dashboard host, and fetched by a one-line bootstrap in the
workspace terminal.

Published on the dashboard host rather than a `data.<...>` hostname because the
control-plane certificate carries exactly four SANs and regenerating it to add a
fifth would risk a working login for a file download — the CA is already served
from a path on that host for the same reason.

The per-site packaging is the part worth keeping: Site A's bundle physically
does not contain Site B's slices, so the isolation the demo claims is a property
of what was delivered rather than a promise about how we behaved.

**D-23 — FL clients pin `flwr==1.16.0`, and the model has no batch
normalisation.** The deployed server runs a fork of Flower based on 1.16.0, so
`pip install flwr` would fetch whatever is current and a client on a different
major connects, sits there, and times out without explaining why.

No BatchNorm because it keeps running mean and variance as non-trainable state,
and FedAvg averages those across sites holding very different class mixes —
exactly our setup. The failure mode is a model that scores well on each client
and badly on the shared test set: it looks like federated learning not working
when it is a normalisation artefact. Dropout regularises instead.

---

## Settled on 2026-08-16

Decisions taken while curating content and branding (Stage 5).

**D-24 — The marketplace is a curated fork, and the repo name is configuration.**
`caios-modules-catalog`, pruned from 46 modules to 9 by
`scripts/curate-catalogue.sh` against `catalog/keep.txt`. A fork rather than a
filter inside PAPI: a filter is another patch to carry forever and hides the
curation in our private configuration, where nobody can inspect what we changed.
`patches/ai4-papi/0007` makes the repository name an environment variable, so
unset, PAPI behaves exactly as upstream.

The keep test is "would a medical or neuroscience researcher plausibly deploy
this on their own data?", judged from each module's summary rather than its
name. Emptier and relevant beats fuller and irrelevant: nine modules that could
all apply reads better than 46 where you scroll past coral reef segmentation.

**D-25 — `image-classification-tf-dicom` is dropped, and "two medical modules"
is really one.** The DICOM module was the anchor of the PACS framing. It is
undeployable in two independent ways: its metadata gives `docker_image` without
a namespace, which makes PAPI's `registry.split("/")[-2:]` raise and return
HTTP 500 the moment it is clicked; and the image is published nowhere findable,
so even a fixed parse would fail at pull.

We could patch PAPI to default the namespace. That converts an immediate error
into a deployment that spins and dies in front of an audience, which is worse.
Consequence recorded rather than hidden: the stock catalogue's medical content
is one module, and the neuroscience content is zero.

**D-26 — Neuroscience comes from the AI4Life loader, not from stock modules.**
*Follows from D-25.* Twelve curated bioimage.io models
(`catalog/ai4life-models.txt`), ordered so the deploy form opens on connectomics
— tracing neurons through electron microscopy. Real published models, deployable
by ID, no code written by us. `patches/ai4-papi/0008` makes the list
configuration; unset, upstream behaviour.

Every ID is validated against the live catalogue by
`scripts/render-ai4life-models.sh`, because a wrong one fails silently — PAPI
drops IDs it does not recognise, so the dropdown quietly has one fewer entry.
This is not hypothetical: `catalog/medical-shortlist.md` recommends
`affable-shark`, which is a bioimage.io nickname and not the `id` the deploy
form accepts.

**D-27 — Brand artwork is generated by a script, and committed.**
`scripts/make-brand-assets.py` produces the logo, favicon and error pages; the
PNGs are committed too, because the build needs them and nobody should have to
run a script to get a working dashboard. A binary in a repository with no way to
regenerate it is a dead end the first time someone wants it wider or recoloured.

**D-28 — Branding is verified by content, never by status code.**
`scripts/check-branding.sh`. The dashboard shipped with no logo and no favicon
for days while every asset returned HTTP 200, because nginx answers a missing
asset with `index.html`. Status codes cannot detect that class of failure; magic
bytes can.

The script also draws the line the Stage 5 gate needs: the runtime `config.json`
is what the app actually uses, so anything AI4EOSC there is a failure, while
upstream addresses compiled into the JS bundle as overridden fallbacks are
warnings. It explicitly does not claim to test whether the platform *reads* as
medical — that is a judgement, and it says so.

**D-29 — Bind-mount paths in compose are repo-relative, never `${HOME}`.**
Docker requires `sudo` on this host and `sudo` resets `HOME` to `/root`, so
`${HOME}/caios-ca.pem` resolved to a file that does not exist — and Docker
silently creates an empty *directory* for a missing bind-mount source rather
than failing. PAPI then started healthily while trusting no CAIOS certificate,
and every outbound HTTPS call to our own domains failed with an error
mentioning nothing about mounts.

**D-30 — PACS Lab is credited in the sidenav, and the EU flag is removed.**
CAIOS is the project; PACS Lab (`https://pacs.eecs.yorku.ca/`) is the
organisation behind it. Its logo sits beside the CAIOS mark at the bottom of the
sidenav, linked, and the acknowledgement line names it.

It *replaces* upstream's `eu-flag.jpg` rather than joining it. That flag is a
European funding acknowledgement — correct for AI4EOSC, and a claim CAIOS cannot
make: this is a Canadian project on Compute Canada under a Canadian allocation.
It rendered unconditionally, on every page, and had gone unnoticed because
branding review had been looking for missing CAIOS branding rather than for
inherited branding that was present and wrong.

This is the first dashboard patch (`patches/ai4-dashboard/0001`), so the
"dashboard is unpatched" property no longer holds literally. It cannot be
configuration: the tenant config offers text and links, and the image pair is
hardcoded in the template. `scripts/check-branding.sh` now fails if `eu-flag`
returns or `pacslab-logo` disappears.

The logo file is supplied by PACS Lab, not generated.
`scripts/make-brand-assets.py` deliberately does not draw it — an approximation
of another organisation's real mark is worse than none.

---

## Settled on 2026-08-19

**D-31 — The sixth instance becomes `caios_llm`, a dedicated LLM host.**
`192.168.104.188` is ours, unused, and identical to the other five: 3 vCPU,
~34 GB RAM, one `NVIDIA H100L-1-12C`, a 125 GB volume at `/dev/vdb`. Confirmed
by the supervisor on 2026-08-19; it has still never been logged into, so Stage
L0 verifies the specs rather than discovering them.

It joins as a fourth Nomad GPU compute client and runs the LLM tool only. The
alternative — borrowing a hospital node — was rejected because the tool needs a
nearly empty 3-core node, which would make the LLM and federated-learning demos
mutually exclusive. **No new instances are needed for this feature.**
*Closes Q-11.*

**D-32 — The LLM catalogue is upstream's models, used as they are.**
No fine-tuning, no custom weights, no medically adapted model. The nine models
we offer are AI4OS's own list, filtered only for what fits in 10.3 GB of usable
VRAM and for what does not require a Hugging Face token.

The consequence is a wording constraint, not an engineering one: the claim this
feature supports is **privacy** — your model, your hardware, your prompts never
leave the cluster — and not medical competence. Nothing in the demo script may
imply the model knows medicine, because a reviewer will ask and it does not.
That is the same argument federated learning makes, applied to inference, and
it is true. *Closes Q-09.*

Fine-tuning stays available later at a cost that is now known: any model on the
list can be swapped for a fine-tuned variant by changing one line in
`configs/papi/vllm.yaml`, provided the variant fits the same memory budget.

---

## Open

**Q-02 — Does "PACS lab flavour" mean branding or integration?**
Assumed branding only. Building as CAIOS now; PACS Lab can be a second theme later. If
it means connecting to a real PACS or DICOM archive, that is a separate project.

**Q-03 — Demo format.** Assumption: produce a recording regardless, since it doubles as
insurance. Affects only the last two days.

**Q-04 — Does the Statistics page need real accumulated usage history?**
Assumption: live cluster data is enough. If not, `ai4-accounting` has to start collecting
almost immediately — this is the open question with the shortest fuse.

**Q-05 — Does federated learning carry the research contribution?**
Assumption: yes, it is the headline. Everything is built around it.

**Q-06 — Institutional SSO, or is a demo login sufficient?**
Assumption: our own Keycloak with local demo accounts. Built that way.

**Q-07 — Throwaway demo, or something the lab keeps running?**
Assumption: treat as a demo, but keep everything in automation anyway. If it is to be
kept, Vault and Keycloak both move off dev-mode storage.

**Q-08 — Audience and disease area.** *Answered by default, see D-20.*
The FL demo is built on public brain MRI (three tumour types). Swapping is still
cheaper than it looks — `prepare_data.py` produces one array file and everything
downstream reads that — but the story, the chart and the site case-mix narrative
are now written around this dataset. Worth confirming before the demo script is
recorded.

**Q-10 — Should an LLM deployment stay running between demos?**
A running vLLM holds a whole GPU indefinitely. Assumption: tear it down between
rehearsals; deploy live at the start of the real demo and come back to it, which
also hides the model-load time.

Each of these has a default recorded above or in `docs/scope.md`, so none of them
blocks work. They are tracked because deciding some of them late is expensive.

## Settled on 2026-08-20

D-33 to D-36 were written in `docs/llm-plan.md` on 2026-08-19 as proposals, "to
be appended here once the implementation confirms them". Stages L2 to L4 have
now done that, so they move here. D-36 arrives broader than it was proposed,
because Stage L4 found the narrow version had missed the case that mattered.

**D-33 — GPU model allowlists are configuration, not source.**
Patch `0009` reads `LLM_GPU_MODELS` and defaults to upstream's `Tesla T4`, so an
unset variable behaves exactly as upstream does. The Nomad-side device
constraint is dropped entirely rather than retargeted: with one GPU model in the
cluster it distinguishes nothing and can only go stale — which it did, once,
when the device plugin upgrade renamed the card under us.

**D-34 — Job resource budgets are asserted by a test, not by a comment.**
Upstream's LLM job asks for 8 cores on 3-core nodes, and the failure mode is a
job that pends forever with no error anywhere. `tests/test_llm_job_template.py`
makes the budget a checked fact, including the `cores`-versus-shares trap, and
checks the header comment still matches the resources below it.

**D-35 — Container images in job templates are pinned, and never force-pulled.**
`vllm/vllm-openai:latest` is 30.8 GB on disk and it moves. Pinned tags plus
pre-pulling turn a fifteen-minute silence into two minutes, and stop an
overnight upstream release from breaking a rehearsed demo.

**D-36 — Nothing in a deployment reaches its own services by public hostname.**
*Broadened on 2026-08-20.* Proposed as "in-allocation health checks talk to the
allocation, not to Traefik", which was true and too narrow: it described the two
helper tasks, and Stage L4 found **Open WebUI itself** doing the same thing —
handed the public HTTPS endpoint of the vLLM task beside it in the same
allocation.

The helpers fail loudly, by killing the allocation. The application catches the
TLS error and serves an empty model list behind an HTTP 200, which is worse. So
the rule is now about the deployment and not about health checks: if a task
needs a service in its own allocation, it addresses it with `${NOMAD_ADDR_*}`
over plain HTTP. That removes DNS, Traefik and TLS from a path where none of
them are doing anything useful, and it is enforced by unit tests for both the
job template and patch `0010`.

Applies beyond this tool. Any AI4OS deployment behind a private CA has this
fault, and we should report it.

**D-37 — Service accounts a deployment needs are created at boot, not claimed
over HTTP afterwards.**
Open WebUI grants administrator to whoever registers first, and upstream claims
that account with a `poststart` task polling `/api/v1/auths/signup`. Between the
port opening and that POST landing, the deployment belongs to whoever asks.

Measured at 0–3 seconds, and then hit by accident: a smoke test checking whether
signup was closed registered *itself* as the administrator, after which the
deployment's real credentials were refused with an error describing the symptom
and not the cause. `WEBUI_ADMIN_EMAIL` / `_PASSWORD` / `_NAME` do the same job
inside Open WebUI's FastAPI lifespan, which completes before uvicorn creates the
listening socket, so the window is zero rather than small.

The generalisation is the decision: **a window that is small is not a window
that is closed.** Where a service can be configured to create its own
credentials at startup, that is preferred over any amount of polling from
outside, however tight the loop. See R-22.


## Settled on 2026-08-22 — carried over from Stage L4b

Written in `docs/llm-plan.md` when L4b shipped and cited in `CLAUDE.md`, but
never appended here. Recorded now so the numbering means something.

**D-38 — `running` means "a user can open it", not "a container started".**
Every readiness signal in this stack is about the first container, and this
project has been bitten by that three times: an endpoint that does not resolve
(R-21), a model dropdown that is empty behind a 200 (R-05, D-36), and a green
badge in front of a 502 (R-23). A status a user acts on has to describe the
thing the user acts on.

**D-39 — "waiting" and "failed" are different words.**
Nomad distinguishes a blocked evaluation from an unplaceable one, and PAPI must
not flatten them. The cost of flattening is measured: a deployment that was 47
seconds from starting was deleted because the dashboard called it an error and
said nothing else.


## Settled on 2026-08-22

**D-40 — Anything the dashboard needs at runtime is served by this cluster.**
Stage L5 removed the last third-party fetch: the LLM model catalogue, which
upstream pulled from `raw.githubusercontent.com` in the user's browser. It now
comes from `/assets/config/vllm.yaml`, staged from `configs/papi/vllm.yaml`, so
PAPI and the dashboard read one file.

Two reasons, and the second is the one that generalises. The narrow one is
correctness: our catalogue is nine models and theirs is thirteen, so the cards
and the deploy dropdown described different platforms. The broad one is that
this is a **private subnet** — a page that needs the public internet to render
correctly is a page that breaks in the room where we demo it. The analytics
beacon (D-27) was the same argument about a different resource.

The rule going forward: if the dashboard fetches it, we serve it. Gotcha 6 in
`CLAUDE.md` lists the places upstream reaches out; `check-branding.sh` is where
a new one gets caught.

**D-41 — An identifier is carried, never reconstructed.**
The dashboard read a YAML file keyed on Hugging Face model ids, discarded the
keys, and rebuilt them where needed as `family + '/' + name`. That works for
most models and silently fails for the ones where an organisation is not a tidy
family label — two of our nine, four of upstream's thirteen.

The failures were a dropdown that opened blank, a "Card" link that 404s, and a
`needs_HF_token` lookup that missed and defaulted to `false`. The last is the
instructive one: **it was right for us by accident**, because everything in our
catalogue is ungated, and it would have become wrong the day somebody added a
gated model — with the symptom appearing at PAPI as a 400, three components away
from the cause.

Patch `0003` keeps the key. The general form is worth stating because it is
cheap to get right and expensive to find: a derived identifier is a guess about
a naming convention, and naming conventions have exceptions.

**D-42 — Placeholder artwork for third-party marks, generated not downloaded.**
Six of the nine LLM cards rendered a broken image, because the card asks for
`{family}_logo.png` and upstream ships badges for two of our five families.

The three missing ones are generated lettermarks in the CAIOS palette
(`scripts/make-brand-assets.py`), not the vendors' real logos. Downloading
trademarks into the repository for a grant demo raises a licensing question
nobody needs to answer, and a page mixing three real logos with three
approximations looks worse than one that is visibly consistent. Replacing the
files is the whole job if the real marks are ever wanted — the filename is the
only contract.

The guard matters more than the artwork: **a missing asset under this dashboard
answers 200 with `index.html`**, so nothing anywhere reports it. There is now a
unit test that fails when a family in `vllm.yaml` has no badge, and a live check
that reads the served bytes with `file`. Third time this pattern has cost
something here — see D-28.


---

## Log

*Append new decisions below with date and one line of reasoning.*

**2026-08-12** — Verified all six upstream repositories at HEAD. Recorded D-10 through
D-18, revised D-02, D-04 and D-06, and closed Q-01. Corrections to `CLAUDE.md` and
the project notes made in the same change. Scaffold for MVP Stage 0 committed.

**2026-08-15** — Stage 4 gate passed: a federated training across three hospital
nodes, 0.853 against 0.806 for the best single site and 0.865 for pooling
everything. Recorded D-19 through D-23 and answered Q-08 by default.

**2026-08-16** — Stage 5 gate passed and the MVP is complete: catalogue curated
from 46 modules to 9, twelve bioimage.io models with connectomics as the
default, CAIOS artwork where there had been none, and a branding audit that
checks content rather than status codes. Recorded D-24 through D-29. The
headline finding is D-25: upstream's "two medical modules" is really one.

**2026-08-16, later** — PACS Lab credited in the sidenav footer, replacing an EU
funding flag that had been rendering on every page. Recorded as D-30, and the
first dashboard patch.

**2026-08-19** — Stage 6 (LLM deployment) planned, not built. Four documents
written: `docs/llm-plan.md`, `docs/llm-concepts.md`, `docs/llm-infrastructure.md`
and `docs/llm-risks.md`. Opened Q-09 through Q-11. **No decisions recorded yet** —
the plan proposes engineering decisions and they are listed there, awaiting
approval, rather than here. Corrected `docs/feature-coverage.md`, which had this
feature at one engineer-day against four blockers it had not found.

**2026-08-19, later** — Q-09 and Q-11 answered by the supervisor and recorded as
D-31 and D-32: the sixth instance is ours and becomes the LLM host, and the LLM
catalogue ships upstream's models unmodified. The plan's remaining engineering
proposals renumbered to D-33 through D-36. `docs/llm-infrastructure.md` gained a
section explaining exactly what the `/dev/vdb` reformat does and why the node is
never certified without it — the original text asserted it was necessary without
showing the mechanism.

**2026-08-20** — Stage L4: Open WebUI end to end. Two faults found, both of
which returned HTTP 200 while being completely broken — the chat interface could
not reach the model beside it (patch `0010`, R-05 extended), and the first
visitor to a deployment became its administrator (R-22). Recorded D-33 through
D-37; D-36 arrives broader than proposed because the narrow version had missed
the case that mattered. `scripts/check-llm-ui.sh` is the gate, and the runbook
gained an LLM section organised by symptom.

**2026-08-22** — Stage L5: the dashboard's LLM catalogue now comes from CAIOS.
The planned change was one URL; reading the page it serves found two more
faults, both demo-visible and neither detectable by a status code — the model id
was rebuilt from two display fields (R-25) and six of nine cards rendered a
broken image (R-26). Recorded D-40 through D-42. Dashboard patches `0002` and
`0003`; `0002` also repairs the spec it invalidated, and `0003` the fixtures
that had been agreeing with the bug.
