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

**Q-08 — Audience and disease area.** *New.*
Which imaging modality would land best? Currently planning around public brain MRI.
Swapping is cheap now and expensive once the FL demo is built around it.

Each of these has a default recorded above or in `docs/scope.md`, so none of them
blocks work. They are tracked because deciding some of them late is expensive.

---

## Log

*Append new decisions below with date and one line of reasoning.*

**2026-08-12** — Verified all six upstream repositories at HEAD. Recorded D-10 through
D-18, revised D-02, D-04 and D-06, and closed Q-01. Corrections to `CLAUDE.md` and
the project notes made in the same change. Scaffold for MVP Stage 0 committed.
