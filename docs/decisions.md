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


## Settled on 2026-08-22 — Stage L6

**D-43 — A workspace verifies CAIOS certificates; it does not skip them.**
The demo's last beat calls a CAIOS-hosted model from a hospital workspace, and
the workspace does not trust our CA — so the obvious fix is `verify=False`. It
is also a bad thing to put on screen while arguing that this platform is the
private option. A reviewer who sees TLS verification switched off has learned
something about our care, not about our architecture.

The bundle each workspace already downloads contains `caios-ca.pem`, so
`SSL_CERT_FILE` pointing at it verifies properly and costs one line. **The
`curl -k` in `bootstrap.sh` stays the single unverified request in the whole
demo, and it is the request that fetches that CA** — which is a defensible
answer to the question, rather than an awkward one.

The general rule: when a private CA makes something inconvenient, distribute the
CA. Turning verification off is a decision about what you are willing to show.

**D-44 — Scripts empty the directories they own; they do not replace them.**
`build-fl-bundles.sh` did `rm -rf` then `mkdir`, which changes the **inode**.
Caddy has that directory bind-mounted, and a bind mount follows the inode, so
Caddy served a deleted directory: `/fl/*` 404ing everywhere while the rebuilt
bundles sat on the host looking perfect.

Nothing about that is specific to Caddy or to this script. Any build step whose
output directory is bind-mounted anywhere has it, and the symptom is always the
same shape — the producer is correct, the consumer is stale, and no error is
raised by either. `find "$DIST" -mindepth 1 -delete` keeps the inode.

The cost of getting it wrong here would have been beat 5, the headline feature,
failing at the first hospital's bootstrap — caused by the script the runbook
tells you to re-run before the demo.


---

**D-45 — The dashboard serves its own fonts.**
`index.html` fetched four typefaces from Google on every page load. Patch
`0004` removes them; `scripts/fetch-fonts.sh` downloads them into
`configs/dashboard/fonts/` and generates the `@font-face` rules.

The privacy argument is the familiar one — a fifth third-party request from a
page meant to be self-contained, after the three in gotcha 6 and the model
catalogue in `0002`. It is not the argument that mattered.

**Material icons are a font.** Each icon is a ligature: the markup says
`<mat-icon>menu</mat-icon>` and the typeface draws a hamburger. If the font
does not arrive the browser renders the ligature source, so every icon in the
dashboard becomes the word it is named after. An air-gapped demo machine or a
conference network that fails closed would have shown an interface that looked
catastrophically broken for a reason unrelated to CAIOS. Nobody would have
found that before demo day, because the machine we develop on has internet.

Two faults were already present and are fixed with it. Material's typography
config asked for `'Raleway'`, which nothing ever fetched, so components
rendered in **Arial** while body copy rendered in **Roboto** — two unrelated
faces on every page, by accident (R-27). And the payload fell from
**5,447 KB to 221 KB**: the icon font shipped all ~3,000 Material Symbols, and
the dashboard uses 65 of them.

**D-46 — Anything visual that can win from a stylesheet does not become a patch.**
Our theme had always loaded *before* upstream's `src/styles.scss`, so it could
never override anything upstream set. Adding `overrides.scss` *after* it, in
the `styles` array we already own in `angular-configurations.json`, gives us a
sheet that wins without touching an upstream file.

The whole typography and token pass therefore carries **no patch and no drift**.
Only two patches exist for the visual work: a pure deletion in `index.html`,
and later the home page. Position is load-bearing — moving `overrides.scss`
above `src/styles.scss` silently reverts the typography, which is why the
config file says so where someone editing it will read it.

**D-47 — The icon subset is derived from source, and a stale one fails a test.**
Subsetting the icon font is not optional: 5,222 KB against 91 KB. But a glyph
the subset lacks does not error — it renders as the ligature source text, so a
delete button shows the word "delete" and nothing reports it. Same shape as
R-26, where six of nine model cards rendered a broken image behind an HTTP 200.

So the list is never hand-maintained. `fetch-fonts.sh` derives it from the
Angular source, and `--check` re-derives it and diffs without touching the
network; `tests/test_icon_subset.py` runs exactly that, so there is one copy of
the extraction patterns rather than a second one in the test that could drift
into agreeing with a bug.


---

## Settled on 2026-08-25 — Stage O0

> **Numbering note.** D-48 and D-49 were settled on the `f1-self-hosted-fonts`
> branch (Stage F2) and have since merged. This entry took D-50 deliberately so
> the numbers would not collide, which is why there is no gap to explain.

**D-50 — A feature we do not run must fail as unconfigured, not as broken.**
PAPI's OSCAR router is mounted unconditionally and the dashboard hardcodes a
sidenav link to `/tasks/inference`, so both are reachable on a cluster that
runs no OSCAR. `main.yaml` has no `oscar` block (D-09), the code indexes it
directly, and a logged-in researcher got HTTP 500 from a menu item.

Patch `0012` splits the two cases the way D-39 requires. The listing returns
`[]`, because that is the call the page makes when it opens and an empty table
is the truthful rendering of "this cluster offers no serverless inference". The
write paths return 501 with a sentence naming the feature and the VO, because
silently accepting a create would be worse than refusing one.

Third application of the same principle: `ACCOUNTING_PTH` unset (patch `0004`),
a queued deployment reported as `error` (patch `0011`), and now this. The
general form: **an absent optional feature is a state, not a failure, and the
message has to say which.**

The implementation lesson is separate and worth as much. The first version
guarded `get_client_from_auth` — the obvious place, the only place the config
is read on the client path — and passed every unit test while leaving
`POST /services` raising `KeyError` exactly as before, because
`create_service` builds the service definition *first*. What caught it was a
test asserting the upstream indexing expression was **gone**, rather than one
asserting the new guard was **present**. Asserting an absence catches the paths
you did not think of; asserting a presence only confirms the one you did.

---

## Settled on 2026-08-26 — Stage O2

**D-54 — Identity for a third-party component is granted by a group claim, not
by reusing our role names.**
OSCAR chooses which JWT claim to read from a substring of the issuer URL, and
for any realm not called `egi` or `ai4eosc` it reads `group_membership`. So a
`oscar-users` group and a Group Membership mapper were added, rather than
bending PAPI's `access:<vo>:<level>` roles into a shape a second consumer also
understands.

The two systems now read different claims from the same token and neither
constrains the other. That is the point: PAPI's role grammar is load-bearing
for deployments and must not acquire a second meaning. The change is additive —
existing claims are untouched — and a full realm export was taken first.

Recorded also because it is surprising: **the realm's *name* is load-bearing.**
Had ours been `ai4eosc`, OSCAR would have accepted our realm roles unmodified.

**D-55 — On a single-node OSCAR, storage is ReadWriteOnce.**
The chart asks for `ReadWriteMany` because OSCAR assumes several nodes. K3s'
`local-path` provisioner supports only RWO, and on one node the two are
equivalent. The PVC is created RWO deliberately.

The constraint this creates is real and should be checked before anyone adds a
second OSCAR node: RWX would then be required, and `local-path` cannot provide
it. See R-38.

---

## Settled on 2026-08-26 — Knative

**D-56 — OSCAR runs a serverless backend after all.** *Supersedes D-51.*
D-51 said asynchronous-only "until synchronous is asked for". It was asked for,
on the correct grounds: the bucket round-trip is a poor experience. Upload a
file to one web app, wait, come back, download from a folder — for a single
image that is absurd, and it is not an integration point anything can build on.

With Knative Serving plus Kourier on the OSCAR node, the `/run/<service>`
endpoint the dashboard **already advertises** starts working: POST an image,
get the detections back in the same response, measured at 5.3-5.9 seconds. No
dashboard change was needed — the *Synchronous calls* panel had been showing a
correct endpoint and token for a feature that was not installed.

The asynchronous path stays and is still the right tool for batches. What
changed is which one a user meets first.

Two things this cost, both worth recording:

**Knative rejects OSCAR's pods until PVC support is switched on.** OSCAR mounts
its FaaS-supervisor volume into every service pod, and Knative disables
persistent volumes by default. The webhook refuses the Service with
`Persistent volume claim support is disabled`. Two feature flags in
`config-features` fix it — `kubernetes.podspec-persistent-volume-claim` and
`...-persistent-volume-write`.

**PAPI cannot report OSCAR's errors.** When OSCAR refused, PAPI answered a bare
`Internal Server Error` because its own `raise_for_status` decorator does
`json.dumps` on a `requests.HTTPError`, which is not serialisable. The real
reason never reaches the user, and would not reach a dashboard either. Upstream
bug; worth a patch and a report.

**D-57 — Warm and cold are read from Knative, not inferred.**
A serverless service that scales to zero has a state a user can feel — the
first request after an idle period pays a start-up cost — and nothing in the
dashboard says which state it is in.

The authoritative signal is the Knative Revision's `status.actualReplicas`:
present and non-zero means a container is up (**warm**), absent means scaled to
zero (**cold**). Measured on this cluster: Knative holds the container about
**30 seconds** after the last request.

Deliberately not inferred from anything else. "Has it been called recently" and
"is its image cached on the node" are both proxies that are right most of the
time, and the failure mode of a proxy here is a badge that says warm while the
user waits. The platform knows the answer; ask it.

Carrying this to the dashboard needs a path that does not exist yet — OSCAR's
service JSON has no live status field, so PAPI would have to read the Knative
API directly, which means giving PAPI a read-only credential on the OSCAR
cluster. That is the cost of the badge, and it is worth stating before anyone
starts.

---

## Settled on 2026-08-29 — Stage F3

> **Numbering note.** D-51, D-52 and D-53 were taken on the OSCAR branch and
> either superseded (D-51, by D-56) or folded into their neighbours before that
> branch merged. There is no gap to explain; F3 continues at D-58.

**D-58 — Application code CAIOS owns is staged, not patched.**
D-46 said this for stylesheets. F3 is the first stage where it applies to
Angular source, and the reasoning is the same one step further: a patch that
creates a whole module is a patch nobody can review, and every line of it has
to be re-read whenever anything near it moves.

So `configs/dashboard/home/` is staged verbatim into `src/app/modules/home/`
and `configs/dashboard/i18n/en.caios.json` is deep-merged into upstream's
`en.json`, exactly as `caios.json` is merged over `_base.json`. The only
upstream edit is nine lines of `app.routes.ts`.

The merge rather than a patch matters most for `en.json`: it is 900 lines that
change whenever any page upstream gains a label, so a patch against it would
break for reasons that have nothing to do with us.

**D-59 — An animation must not be able to hide content.**
The scroll reveal hides an element and then shows it again. Both halves have to
be done by the same script, in that order, or the failure modes are blank
sections:

- the hidden state is added by the directive, never by the stylesheet, so an
  element whose script did not run is simply visible;
- `prefers-reduced-motion` skips arming entirely rather than shortening a
  transition;
- and if `IntersectionObserver` reports nothing anywhere on the page within a
  second and a half, the effect is abandoned and everything is shown.

The third is not defensive programming for its own sake. It was found by
looking: in one browser context the observer was constructed, given an element
filling the viewport, and never called back — not even with the initial report
a working implementation always sends. Without the timeout that browser gets a
page with five empty sections, and every test still passes.

**D-60 — Every number the home page prints can be pointed at a file.**
Four counts, three accuracies, three timings, and each one is either read from
a file in this repository or recorded in `docs/`. `tests/test_home_page.py`
asserts the counts against `catalog/keep.txt`, `catalog/ai4life-models.txt` and
`configs/papi/vllm.yaml`, so curating the marketplace and forgetting the home
page is a failing test rather than a wrong number on the first page anybody
sees.

There are no users, customers, testimonials or adoption figures on the page,
for the simple reason that there are none to report. A first page that inflates
is the cheapest thing in the world for a reviewer to check.

**D-61 — The home page declares its own text faces and never the icon font.**
It sets IBM Plex Sans and Mono from the WOFF2 files staged since F1, in its own
lazy-loaded stylesheet, and deliberately does not import
`theme/caios/_fonts.scss` — which also declares `Material Symbols Rounded`.

A second declaration of the icon family, pointing at our 65-glyph subset while
`index.html` is still loading Google's complete one, is exactly how F1 turned
every icon in the dashboard into the word it is named after. The blast radius
of a missing Plex file is one page falling back to the system sans; the blast
radius of a redeclared icon font is the whole application. A test asserts the
icon family is not named anywhere in this directory.

---

## Settled on 2026-08-30

**D-62 — The platform-status feed is off, not pointed somewhere.**
Upstream reads AI4EOSC's GitHub issue tracker for the startup popup, the
notifications bell and the maintenance banner on the deployments list, from the
visitor's browser, on every page load. Patch `0005` makes the source
configuration; `configs/dashboard/caios.json` leaves it blank.

Two options were real. **Point it at a CAIOS status repository** — more useful,
and a one-line change whenever it is wanted, but it needs a repository that does
not exist and the habit of maintaining it, neither of which is worth acquiring
before a demo. **Turn it off** — the feature then reads as unconfigured rather
than broken, which is the rule D-50 already set.

Off, and the key is present-and-empty rather than absent, so the served config
states the decision instead of leaving it to a default. The same reasoning as
the analytics keys, which are blanked rather than deleted.

The number that settled it: GitHub allows **60 unauthenticated requests an hour
per IP address**, the dashboard spends two per full page load, and an audience
in one building shares one address. Past thirty loads, every visitor gets a red
error toast — which is a likelier failure than the one that prompted the look,
and a worse one to meet on a projector.

---

## Settled on 2026-08-31

**D-63 — The home page is written for the people who use the platform, not the
people who run it.**
Its readers are medical and neuroscience academics. Not one of them needs to
know what schedules a job, what serves a model, or what the GPU is called, and
a count of machines tells them only how small the platform is this month.

So the page carries none of that vocabulary and no size of the installation,
and `tests/test_home_page.py` enforces both against a word list rather than
against anyone's memory. The words are easy to reintroduce by accident, in a
sentence that reads perfectly well to whoever wrote it.

The corollary is what the page shows instead: a measured result, drawn as a
chart, and five drawings of what each capability means rather than of how it is
built. A research audience reads a figure more fluently than a paragraph.

**D-64 — Everything the page has to say is on one stage.**
Seven stacked sections and five thousand pixels became three blocks, with six
slides in the middle in two labelled groups. The material is the same; the
reader now chooses what to look at instead of scrolling past it, and the length
of the page stops being a measure of how much was written.

A word budget on the visible copy keeps it that way. Alt text is excluded from
it deliberately, because counting it would put a limit in competition with
accessibility, and that is a trade nobody should be asked to make.

**D-65 — SVG presentation attributes are never set in a template when the
stylesheet styles them.**
A CSS property beats a presentation attribute, always. Twice in one afternoon:
`transform` on the hero tiles stacked twelve of them at the origin, and
`text-anchor` on a chart caption centred it on the left edge of the plot and ran
it off the drawing. Both look exactly like a rendering failure, and neither logs
anything anywhere.

The rule avoids the whole family, and a test enforces it for the properties the
figures actually style.

**D-66 — A file that changes without changing its name is served with no-store.**
Everything the Angular build emits is content-hashed, so a new build is a new
filename. Three files are not: the runtime configuration, the model catalogue
and every string in the interface. Without a cache header a browser reuses its
copy for as long as its own heuristic allows, and a returning visitor gets the
previous release's words, or the previous release's API address, against
today's bundle.

Found by deploying and watching it happen. Patch `0006`. Upstream had tried to
prevent exactly this and written a location block that matches nothing, which
is the more useful half of the lesson: a rule that never fires looks identical
to a rule that works.

Fonts and images stay cacheable. They are large, they change rarely, and the
trade goes the other way.

---

## Log

*Append new decisions below with date and one line of reasoning.*

**2026-08-31** — The home page rewritten for its actual audience. Recorded
D-63 to D-66. It had been written in the vocabulary of the people who built the
platform; it is now three blocks and six slides, with a measured chart in place
of an architecture diagram. Two SVG faults and one caching fault found by
looking at it in a browser, all three of which passed every test that existed
at the time.

**2026-08-30** — R-38 closed: the dashboard no longer reads another project's
status feed. Patch `0005`, D-62, `tests/test_platform_status.py`, and section 3d
of `scripts/check-branding.sh` — which fails until the new image is deployed,
because it tests what is running rather than what is committed.

**2026-08-29** — Stage F3: `/` is a home page. Recorded D-58 to D-61. The page
states what CAIOS is, who it is for and where it runs, shows the three
capabilities over one schematic of the actual cluster, walks the no-code /
low-code / high-code path with a form, a request and a method, and ends on the
catalogue. It makes no HTTP request of any kind, and a test keeps it that way.

Two things it found that no plan had. The schematic was drawn at a nominal size
and every label in it was illegible once the SVG scaled into its column — the
geometry is now laid out for the width the console actually gives it, measured
in a browser. And the scroll reveal was one browser away from a blank page:
`IntersectionObserver` never reported, so the armed sections never unarmed.
D-59 is that, generalised.

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

**2026-08-22, later** — Stage L6, and Stage 6 with it. The demo has a beat for
the private language model: a chat window, and the stock OpenAI client pointed
at the cluster from the same workspace that was a hospital site ten minutes
earlier. Recorded D-43 and D-44, both found by trying to write the beat rather
than by planning it — the notebook did not work against our own CA, and
rebuilding the FL bundles turned out to break the URL every hospital pastes.
The gate item was measured rather than asserted: 10 federated rounds in 34.6 s
while the LLM answered at 71–81 ms throughout.

**2026-08-23** — Stage F1: the dashboard serves its own fonts. Recorded D-45
through D-47. The stage was scoped as a privacy fix and turned out to be a
demo-day one: Material icons are a font, so with no route to Google every icon
in the interface renders as the word it is named after, and the machine we
develop on has internet so nobody would have seen it. Two faults were already
there — Material asked for a typeface nothing loaded, and the icon font shipped
all ~3,000 symbols for the 65 in use. 5,447 KB to 221 KB.

The reusable part is D-46: our theme had been loading *before* upstream's
stylesheet all along, which is why it had never been able to override anything.
One line of ordering in a config we already own turns the rest of the visual
work into zero patches.

**D-48 — Machine values are set in a system monospace, not a downloaded one.**
Container tags, timestamps, GPU counts and sizes are compared character by
character, and proportional digits do not line up between rows. They get
`ui-monospace, SFMono-Regular, Menlo, Consolas, …` — a stack every platform
already ships.

Not a downloaded face, and the reason is F1: a typeface that fails to arrive
takes the interface with it. A system stack costs no bytes, cannot 404, and
cannot be removed by a patch that turns out to be wrong. The instrument-panel
treatment is worth having; it is not worth a second network dependency.

Sized at 13 px against the cell's 14 px, because a monospace sets wider and
`creationTime` is a fixed 200 px column. That number came from measuring the
column in a browser, not from taste.

**D-49 — Visual changes are verified by injecting them into the live page,
not by deploying them.**
F1 was designed without ever looking at the dashboard, and shipped a fault that
no test could have caught. F2 was done with a browser attached: read the DOM
for real selectors, measure the real columns, then inject the candidate CSS
into the running page and photograph it.

Real data, real widths, real fonts, and the deployed image never changes. It
takes a minute and it is the only check in this whole plan that looks at what a
user would actually see. A theme change that has not been through it is not
ready, whatever the test suite says.

**2026-08-24** — Stage F1 rolled back and shelved; Stage F2 built and verified.
Recorded D-48 and D-49. F1's lesson is not "fonts are hard" but that a
derivation checked against itself proves only self-consistency: the test ran
the same extraction as the script and so agreed with its bug. F2's method
answers that directly — the check is a browser, not another assertion.

**2026-08-25** — Stage O0: serverless inference degrades instead of erroring.
Patch `0012` and `tests/test_oscar_optional.py`. Recorded D-50. Found on the
way: the Inference menu entry is hardcoded in the dashboard sidenav, so the
500 was reachable from the menu by any logged-in user and had been since
Stage 3. Full plan in `docs/oscar-plan.md`.

**2026-08-26** — Stage O2 gate passed: OSCAR accepts a CAIOS Keycloak token.
Recorded D-54 and D-55. The headline finding is that three of the four
failures were one fault — a helm release left in `failed` state, whose missing
PVC surfaced only on the OIDC path, never on basic auth.

**2026-08-26, later** — Knative Serving and Kourier installed on the OSCAR
node; `/run/<service>` works and returns detections in 5.3-5.9 s. Recorded
D-56 (supersedes D-51) and D-57. Two findings worth more than the feature: the
dashboard had been advertising a working-looking endpoint for an uninstalled
backend, and PAPI cannot serialise an OSCAR error so every OSCAR failure
reaches the user as a bare 500.

**D-67 — The federated-learning router keeps TLS when everything else drops it.**
T5 moves the platform to HTTP so a visitor needs no certificate authority
installed. The `fedserver-` router is the one exception, and it is marked in
the job template so nobody tidies it away.

Three reasons, in order of weight. It is **gRPC on :443**, and Traefik
accepting h2c from a client is not a property to be discovering on demo day —
this is the headline feature. Its clients are Flower processes inside cluster
workspaces that **already carry the CA** in their bundle (D-43), so TLS costs
them nothing. And **no browser ever reaches that hostname**, so it is not a
barrier to any visitor — which is the entire purpose of the switch.

The general rule this is an instance of: drop TLS where it stands between a
person and the platform, keep it where it stands between two machines that
already trust each other.

**D-68 — The scheme is one variable, and both schemes always answer.**
`CAIOS_SCHEME` in `configs/env/caios.env` is the only place the platform's
scheme is written down. Caddy's site blocks, Keycloak's issuer, PAPI's
advertised endpoints, the dashboard's `apiURL`, the Traefik router tags, the
federated bundles and every check script derive from it. Rollback is the
variable, a render and a restart — no rebuild, because the dashboard image
derives `requireHttps` from the issuer at runtime rather than being compiled
for one scheme.

Both schemes answer on every control-plane hostname. The active one serves; the
inactive one returns a 302 to the active one. That is not symmetry for its own
sake: **Chrome upgrades `http://` navigations to `https://` on its own** and
only falls back if the upgrade fails — and ours would succeed. Without the
bounce, a visitor typing the dashboard hostname lands on a valid TLS page whose
calls to the `http://` API are blocked as mixed content: a dead dashboard that
reads as our bug rather than the browser's helpfulness.

The certificates and every certificate script stay in the tree for the same
reason.

**D-69 — There is a proxy VM, and `/etc/hosts` on `caios_server` hid it.**
Found on 2026-09-02. `134.87.8.230` is a separate machine running nginx 1.18.0
and is the public front door for both tiers. `docs/public-access.md` had said
for a week that no such machine existed and that the floating IP DNATs straight
to `caios_server`.

The reason it survived that long is worth more than the fact. `/etc/hosts` on
`caios_server` maps the four control-plane hostnames to `192.168.104.181`, so
**every curl run from that node bypasses the proxy and talks to Caddy
directly**. Both answer, both look right, and they are not the same path. The
deployment hostnames have no override, which is the only reason it surfaced at
all — a `301` from `nginx/1.18.0 (Ubuntu)` where Caddy was expected.

Two consequences. Verifying anything public from `caios_server` requires
`--resolve`, and the `Server:` header is the tell. And T5 cannot be completed
from this repository alone: the proxy redirects `:80` to `:443`
unconditionally, which against a platform serving HTTP is a **redirect loop**,
not a degradation. `docs/nginx-proxy.md` holds the exact change and
`CAIOS_SCHEME` stays `https` until it is applied.

**2026-09-02** — T5 plumbing landed; the switch itself is held. Recorded D-67
to D-69. Every scheme on the platform now derives from `CAIOS_SCHEME`, still
set to `https`, so the platform is unchanged and working. The finding that
matters is D-69: the public path was never the path anyone had been measuring.

**D-70 — A pending account is the absence of a role, not a row.**
T6. Registration could have been a service with a database of applications,
each with a status, kept in step with Keycloak. Instead a pending user *is* a
realm user holding no `access:<vo>:<level>` role, and approval *is* the role
assignment.

Everything hard about the first design disappears with the second. There is no
record that can disagree with reality, nothing to migrate, no way for an
approval to be written in one place and not the other, and no question about
what happens if somebody is changed directly in Keycloak. The console is a view
over an API that is a view over Keycloak, and Keycloak remains the only thing
that knows anything.

The cost is that "when did they apply" is Keycloak's `createdTimestamp` and
"why" is not recorded at all. Both are acceptable for a platform whose approver
is one person who also reads the email.

**D-71 — The approval service is its own container, not a PAPI router.**
PAPI is what the entire platform runs through; every page of the dashboard and
every deployment passes through it. An admin console used by one person a week
must not be able to stop a demo, and a ~300-line FastAPI app in its own
container cannot.

It is reached at `/registration/*` on the **API hostname** rather than one of
its own, which is what keeps the cost to nearly nothing: no DNS name, no fifth
SAN on the control-plane certificate, and no second origin for the browser to
be told about.

The trade accepted knowingly: one more container to start, and one more thing
that can be down. Down, it takes nothing with it — accounts can still be
approved in Keycloak directly, which is what the console's own error state
says.

**D-72 — An approval console may never grant more than it is approving.**
`approve` assigns `ap-u` and the level is fixed in the code, never taken from
the request. An approval console that can mint administrators is a
privilege-escalation path wearing a friendly name.

Three more refusals for the same reason. You cannot deny your own account. You
cannot deny an account holding `ap-d` without first removing that role
deliberately in Keycloak. And denial disables rather than deletes, because an
account that can be re-registered with the same address the next minute has not
been denied.

The service account behind all of it holds `view-users` and `manage-users` —
the narrowest pair that can list accounts and change one role. Not
`realm-admin`: a registration console must not be able to rewrite the realm
that login itself depends on. That constraint was tested by the first real
approval failing, because reading a role definition by name needs `view-realm`;
the fix was to ask a different question, not to widen the grant.

**2026-09-04** — T6 built: self-registration, an approval service, and a
console. Recorded D-70 to D-72. Found on the way: a user holding no access role
made PAPI answer HTTP 500 (`ValueError: None is not in list`), which had never
fired because every account until now was created with a role already attached.
Self-registration produces exactly that user, so the most likely person to meet
that code path was getting the least useful answer the platform can give. Patch
`0018`.
