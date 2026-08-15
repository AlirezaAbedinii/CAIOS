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

Each of these has a default recorded above or in `docs/scope.md`, so none of them
blocks work. They are tracked because deciding some of them late is expensive.

---

## Log

*Append new decisions below with date and one line of reasoning.*

**2026-08-12** — Verified all six upstream repositories at HEAD. Recorded D-10 through
D-18, revised D-02, D-04 and D-06, and closed Q-01. Corrections to `CLAUDE.md` and
the project notes made in the same change. Scaffold for MVP Stage 0 committed.

**2026-08-15** — Stage 4 gate passed: a federated training across three hospital
nodes, 0.853 against 0.806 for the best single site and 0.865 for pooling
everything. Recorded D-19 through D-23 and answered Q-08 by default.
