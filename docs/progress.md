# Progress

Running log of what has actually been done. Updated at every step.

Newest entries at the top. Each entry says what changed, what was verified, and
what it unblocks — so that "done" always means something checkable.

**Where we are: MVP Stage 0 complete. Nothing installed on the nodes yet.**
Next action is Stage 1, which needs SSH keys distributed and volumes confirmed.

---

## Status at a glance

| Stage | What it delivers | State |
|---|---|---|
| 0 — Local scaffold | Every config, script and patch, written and self-tested | **Done** |
| 1 — Cluster | Consul, Nomad, Traefik running; a job reachable over HTTPS | Not started |
| 2 — Identity | Keycloak and Vault; a token PAPI accepts | Not started |
| 3 — Control plane | PAPI and the dashboard; deploy a model from the browser | Not started |
| 4 — Federated learning | Training across three sites | Not started |
| 5 — Content and branding | Curated catalogue, CAIOS look | Not started |

**Blocking Stage 1 — one thing, ten minutes:**

Install the cluster public key on the other four nodes. It needs a credential
only on your laptop, so it cannot be done from here. Step by step in
`docs/ssh-setup.md`; verify with `bash scripts/check-ssh.sh`.

That same check also reports each site node's disk layout, which answers the
second prerequisite: confirming their `/mnt` holds nothing worth keeping before
the Nomad playbook reformats it.

---

## 2026-08-12 — Stage 0: SSH, disks, and a correction

**Correction: the second volume was already there.** An earlier note said
`caios_server` had no data volume. That was wrong — it came from truncated
command output. Every instance has a **125 GB volume at `/dev/vdb`, formatted
ext4, mounted at `/mnt`**. That is why this repository lives at `/mnt/CAIOS`.

This changes the disk plan and surfaces a hazard:

- **`caios_server` keeps `/mnt` as ext4, untouched.** Nothing on the control
  plane needs per-container disk quotas. `playbook-control-plane.yml` simply
  points Docker's storage at `/mnt/docker`, which matters because the root disk
  has only ~12 GB free and the control-plane images will not fit there.
- **The three site nodes get `/mnt` repartitioned and reformatted as XFS**, at
  `/mnt/data`. This is required — Docker's `storage-opt` disk limits only work
  on XFS, and the cluster test asserts the device path `/dev/vdb1` literally.
- **That step erases `/mnt` on those nodes.** `caios_server` is deliberately
  absent from the `nomad_volume` inventory group, with a warning at the group
  saying why. One typo there would delete this repository.

**SSH.** `caios_server` had no private key at all — only `authorized_keys` — so
it could accept connections but never make one. Generated a dedicated cluster
keypair here (`~/.ssh/caios_cluster`) rather than copying a personal key onto a
shared node: it is scoped to this cluster and revocable by deleting four lines.

Installing its public half is the one step that cannot be automated from here,
because it needs a credential only on your laptop. `docs/ssh-setup.md` covers
both routes; `scripts/check-ssh.sh` verifies the result using the cluster key
alone, with agent forwarding and passwords disabled, so a pass means Ansible
will work unattended.

Ran it: all four nodes answer at the network level and reject the key, which is
exactly the expected state. Network connectivity is confirmed; only
authorisation is missing.

**Repository made private-safe.** Rewrote git history to purge the four internal
documents from all thirteen commits, and force-pushed. Verified zero occurrences
across every remaining ref; the files are still on disk. Full backup taken first
at `/home/ubuntu/caios-backup-20260812-0416.bundle`. Hardened `.gitignore` with
catch-all rules for credentials, OpenStack RC files, private keys, Terraform
state and internal notes, so the next sensitive file is ignored by default
rather than by memory.

---

## 2026-08-12 — Stage 0: adapted to the real network, and the last of the scaffold

**Network reality corrected.** The earlier design assumed two public floating
IPs. There are none — every node is private on `192.168.104.0/24`, reached
through OpenVPN and a jumpserver. Reworked accordingly:

- Renamed `CAIOS_FIP1`/`FIP2` to `CAIOS_CTRL_IP`/`CAIOS_EDGE_IP`, since
  "floating IP" now describes something that does not exist.
- Ansible runs *from* `caios_server`, reaching the others directly across the
  subnet. No bastion hop in the automation.
- **Verified `sslip.io` resolves private addresses** from the node:
  `dashboard.192.168.104.181.sslip.io → 192.168.104.181`. The hostname scheme
  therefore needs no change and still requires no DNS setup.

**Node roles assigned** to the real addresses:

| Node | Address | Role |
|---|---|---|
| `caios_server` | 192.168.104.181 | Cluster servers + web services. We work here. |
| `caios_edge` | 192.168.104.105 | Traefik. Every deployment address points here. |
| `caios_site_a` | 192.168.104.20 | GPU compute — "Hospital A" |
| `caios_site_b` | 192.168.104.145 | GPU compute — "Hospital B" |
| `caios_site_c` | 192.168.104.7 | GPU compute — "Hospital C" |
| *unassigned* | 192.168.104.188 | Sixth instance, deliberately left out until identified |

**Measured on `caios_server`:** 3 vCPU, 34 GB RAM, 20 GB disk, one
`NVIDIA H100L-1-12C` (12 GB slice), Ubuntu 22.04.5. Two things follow: no node
can host CVAT (~72 GB in one place), and no second volume is attached here.

**`configs/env/caios.env` created** with the real addresses and freshly generated
secrets, mode `600`, confirmed gitignored. Rendering verified end to end.

**New documents:** `docs/concepts.md` (Nomad, Consul and Traefik explained from
zero), `docs/scope.md` (what is MVP, what is V1, what is excluded and why), and
this file.

**Internal documents removed from the public repository** — the working notes,
supervisor questions and original phase plan. They remain on disk.

**Consequence worth flagging:** with no public IP, nothing is reachable outside
the VPN. That rules out a live demo to external reviewers unless a floating IP is
requested, or reviewers get VPN access. Recording was already the plan, so this
costs nothing — but a floating IP has a lead time and is worth requesting now.

---

## 2026-08-12 — Stage 0: catalogue and operations

**Catalogue counted properly, and the neuroscience gap closed.** Against both the
repository and the live API: 46 models, **2 medical**, **0 neuroscience** — not
the 4 medical previously recorded.

The fix turned out to be better than expected. The platform's bioimage.io loader
supports three **connectomics** models — neuron segmentation in electron
microscopy — plus mitochondria segmentation. Real neuroscience, no code. That
downgrades "build a custom neuroscience module" from necessary (1.5-2 days) to an
optional stretch item.

Curation plan is mostly subtraction: remove ~31 marine, agricultural and remote
sensing models, leaving ~15 that are all plausibly relevant.

**Runbook written**, organised by symptom rather than by component — the failures
in this stack are mostly silent, so "a dashboard that renders with every button
dead" is a more useful heading than "PAPI".

---

## 2026-08-12 — Stage 0: control plane, patches and tooling

**Compose stack** for `caios_server`: Caddy, Keycloak, Vault, PAPI, dashboard.

Three problems found by reading PAPI's own Dockerfile, each of which would have
cost time on the node:

1. **It sets `IS_PROD=True`.** The received wisdom — "leave `IS_PROD` unset" — is
   therefore wrong for the official image: unset inherits `True` and PAPI refuses
   to start over missing tokens for services we do not run. Now set to `false`
   explicitly.
2. **It binds `0.0.0.0:80`**, which collides with Caddy and would expose PAPI
   directly. Rebound to loopback.
3. **It regenerates its own config file at every start**, so a config mounted at
   the obvious path is silently overwritten a second later. Mounted at the file
   it actually reads instead.

**Four upstream patches**, all verified to apply and parse:

| Patch | Why it cannot be configuration |
|---|---|
| PAPI Keycloak URL | Hardcoded in Python. Without it, every login is rejected. |
| PAPI Vault address | Hardcoded. Deploying the FL server calls Vault *before* Nomad, so the headline demo fails with an error mentioning neither. |
| Cluster test namespaces | Hardcoded to AI4EOSC's. Also fixed two assertions that were no-ops, so a misconfigured node now fails instead of being marked ready. |
| Dashboard | **Not patched** — the value that looked hardcoded turns out to be overridable at runtime. |

**Scripts**, all syntax-checked, several tested against synthetic data:
vendor pinning, patch application, config rendering, certificate generation,
cluster verification, security groups (prints by default, creates only with
`--apply`), Keycloak users, token inspection.

`verify-cluster.sh` earns its place: it checks the four conditions that decide
whether anything can be scheduled, and was tested to correctly catch the exact
silent failure that would otherwise cost a day.

---

## 2026-08-12 — Stage 0: branding and configuration

**CAIOS dashboard tenant** added alongside upstream's five. Theme recoloured to a
clinical teal, deliberately distinct from AI4EOSC's cyan-on-navy so it does not
read as a reskin. Verified the build target resolves and the tenant config
produces no `cloud.ai4eosc.eu` URLs.

Two leaks closed that the original notes had not caught: the footer links, and an
**analytics beacon** that would have reported our demo traffic to a third-party
tracker.

**PAPI configured** for a single VO, deployment addresses derived from the
Traefik node, OSCAR removed, MLflow blanked rather than left pointing at
AI4EOSC's. Added our datacenter to the map file — without it the Statistics page
places the cluster at latitude 0, longitude 0.

**Federated server defaults changed** to fit the demo: expose the image that
issues per-client credentials (upstream hides it), default to the mode where
training rounds are *visible* rather than hidden, and require three clients.

---

## 2026-08-12 — Stage 0: verification and planning

Read all six upstream repositories at HEAD rather than trusting notes, and found
several things that would each have cost a day or more:

- **The federated learning server needs Vault**, at an address hardcoded in
  Python. This is on the critical path of the headline feature and was in nobody's
  plan.
- **The cluster test suite is not optional.** It is the only thing that marks
  nodes as ready for work, and without it every deployment queues forever on a
  cluster that reports itself perfectly healthy.
- **Three Nomad datacenters are not achievable** with the upstream automation —
  it writes one datacenter name into every node. Sites become node-level instead,
  which turns out to be the better design anyway.
- **Platform storage is Nextcloud over WebDAV, not S3.** The plan to run MinIO
  would not have worked.
- **CVAT needs ~71 GB of RAM on a single machine.**
- **One user may hold at most 2 GPUs**, so three GPU-backed federated clients
  would be rejected on the third.

Recorded as decisions D-10 to D-18; three earlier decisions superseded or revised.

**Node layout redesigned** to put the web services on the same node as the
cluster servers. PAPI then reaches Nomad over loopback using certificates that
are already there — removing a class of debugging, and freeing a node so we get
**three** hospital sites out of five machines instead of two.

**Delivery split into MVP and V1** so there is something demonstrable in about
eight days rather than three weeks.
