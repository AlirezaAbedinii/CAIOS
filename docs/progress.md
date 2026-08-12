# Progress

Running log of what has actually been done. Updated at every step.

Newest entries at the top. Each entry says what changed, what was verified, and
what it unblocks — so that "done" always means something checkable.

**Where we are: Stage 2 complete.** The cluster is live and proven, and the
identity layer on top of it works — Keycloak issues tokens PAPI will accept, and
Vault accepts those same tokens and isolates secrets per user. Next is Stage 3:
PAPI and the dashboard, which is the first stage that produces something a
viewer would recognise as the product.

---

## Status at a glance

| Stage | What it delivers | State |
|---|---|---|
| 0 — Local scaffold | Every config, script and patch, written and self-tested | **Done** |
| 1 — Cluster | Consul, Nomad, Traefik running; a job reachable over HTTPS | **Done** — gate passed |
| 2 — Identity | Keycloak and Vault; a token PAPI accepts | **Done** — gate passed |
| 3 — Control plane | PAPI and the dashboard; deploy a model from the browser | Not started |
| 4 — Federated learning | Training across three sites | Not started |
| 5 — Content and branding | Curated catalogue, CAIOS look | Not started |

**Nothing is blocking.** Next actions, in order:

1. Stage 3 — build and start PAPI, point it at Nomad, Keycloak and Vault, then
   build the CAIOS dashboard and click through it in a browser.
2. Stage 4 — federated learning across the three sites.

---

## 2026-08-12 — STAGE 2 GATE PASSED: identity and secrets

Keycloak and Vault are running, and a real user token passes every check PAPI
will make:

```
=== 1. Keycloak issues a token ===
  [ ok ] required claims (sub, iss, name, email)
  [ ok ] audience includes 'account'
  [ ok ] carries an access:<vo>:<level> role
         issuer: https://auth.192.168.104.181.sslip.io/realms/caios
=== 2. Vault accepts the same token ===
  [ ok ] Vault issued a token
=== 3. Secrets work at the paths PAPI actually uses ===
  [ ok ] wrote a secret        [ ok ] read it back
  [ ok ] another user is denied (HTTP 403)
```

Four demo users exist — one researcher and one per hospital site — each holding
`access:vo.caios.ca:ap-u`, the role name PAPI actually parses.

### The bug that would have cost a day

The realm listed the client's scopes explicitly and **omitted `basic`**. In
Keycloak 26 that scope carries the `sub` protocol mapper, and PAPI requires
`sub` on every token and uses it as the user identity for Vault secret paths.

The resulting tokens looked completely healthy — right issuer, right audience,
name, email, roles all present — and PAPI would have rejected every one of them
with a 401 saying nothing about which claim was missing. It only surfaced
because the check decodes and inspects each required claim by name rather than
asserting "a token came back".

Fixed in the template with a comment explaining why the scope is not optional.

### Three other things worth recording

**Keycloak refuses to import an annotated realm file.** It rejects any field it
does not recognise, so our `_comment` keys failed the whole import with
"Unrecognized field". Rather than strip the documentation, `render-configs.sh`
now removes `_comment*` keys on the way out — the template stays annotated, the
artefact stays valid.

**Keycloak now runs on Postgres, not its built-in file database.** The first
failed import corrupted the H2 store badly enough that Keycloak would not start
at all ("Database is already closed") and its volume had to be deleted.
Identity is the one service whose failure takes the whole demo with it, and a
real database costs one container.

**Vault could not fetch the realm's discovery document.** Its container has no
reason to trust our CA, so the HTTPS fetch failed with a TLS error that reads
like a network problem. Fixed by passing the CA inline through
`oidc_discovery_ca_pem` — nothing has to be mounted.

### Certificates: one authority for everything

Caddy's automatic HTTPS cannot work here — it uses Let's Encrypt, which must
reach the host from the public internet, and every node is behind the VPN. Its
fallback is an internal CA, which would have meant a *second* authority to
distribute.

Instead the control plane now serves a certificate issued from the same CA as
the deployment wildcard. Import `caios-ca.pem` once and the dashboard, the API,
Keycloak, Vault and every deployment are all trusted.

`scripts/check-identity.sh` re-runs the whole verification, and belongs after
any change to the realm, to Vault, or to the addresses — all three have to agree
on the issuer string exactly.

---

## 2026-08-12 — STAGE 1 GATE PASSED

A container scheduled by Nomad, routed by Traefik, reached over HTTPS at its own
subdomain with a **verified** certificate:

```
$ curl https://smoke.pacs-deployments.192.168.104.105.sslip.io
HTTP 200   TLS verify: 0 (0 = certificate verified)

Server address: 172.17.0.3:80
Server name: 9eb2dfd5d032
```

All four nodes report `meta.status=ready`. The cluster can now schedule work.

**The certificate needed rework.** The original wildcard was a bare self-signed
leaf — `CA:FALSE` — which nothing can be configured to trust: not curl, not
Python's `requests`, not a browser's "always trust". That is survivable until
something automated checks HTTPS, and `ai4-nomad_tests` does exactly that,
raising "Invalid SSL certificates". Since that suite is also the only thing that
marks nodes ready, an untrustable certificate blocked the entire cluster.

Replaced with a proper two-tier setup: a local CA (`~/caios-ca.pem`, 10 years)
signing the wildcard. One file to trust, in one place. The CA is installed in the
system trust store for curl, passed to Python tooling via `REQUESTS_CA_BUNDLE`,
and can be imported into a browser once to remove warnings entirely — a
noticeably better demo experience than clicking through a warning screen.

**The gate proved more than it looks.** For that request to return 200, all of
this had to be working: Nomad placed the job against four constraints; Docker
pulled and ran it; Consul registered the service and its Traefik tags; Traefik
read those tags and built a route; sslip.io resolved the wildcard hostname; and
the TLS chain validated. A single 200 covers the whole path.

**One mistake worth recording**, because it will recur: the first attempt
returned 404. The job template builds its hostname as
`<name>.${meta.domain}-<BASE_DOMAIN>`, and `meta.domain` is already `pacs` — so
passing `pacs-deployments...` as the base produced
`smoke.pacs-pacs-deployments...`. The base domain must be
`deployments.<ip>.sslip.io`, matching `lb.domain` in `configs/papi/main.yaml`
exactly. Noted in the job file itself now.

`scripts/run-cluster-tests.sh` captures the full invocation — namespaces, base
domain and CA bundle — so nobody has to reconstruct it.

---

## 2026-08-12 — Stage 1: Consul, Nomad and Traefik are live

**The cluster is up.** Five Consul members, Nomad server leading with region
`global` and datacenter `caios`, four Nomad clients ready, and the Traefik job
already running.

```
Consul   5 members alive          datacenter caios
Nomad    1 server (leader)        region global
         4 clients ready          3 GPU compute + 1 traefik
Jobs     traefik-caios running    docuum running
Namespace  caios                  created
```

GPU nodes check out completely: `NVIDIA H100L-1-12C` detected as a Nomad device,
the `nvidia` Docker runtime present, `/dev/vdb1` mounted, 44.7 GB per core
(the test needs >5), 4096 MB reserved.

**One step left before the Stage 1 gate:** every compute node still reports
`meta.status=test`. That is the value Ansible ships, and only `ai4-nomad_tests`
changes it to `ready` — which every PAPI deployment requires. Next action.

### Four real problems, and what each cost

**1. `import_playbook` silently loaded the wrong variables.** Ansible resolves
`group_vars/` relative to the playbook's own directory. Importing
`vendor/ai4-ansible/playbook-consul.yaml` therefore made *upstream's* IFCA
settings win, and every one of ours was ignored — the first run happily built an
`ifca-imagine` cluster and reported success. Replaced both wrappers with plays
that call the vendored roles directly, and added asserts on `consul_dc_name` and
`nomad_region` so it cannot recur quietly.

**2. `group_vars` still held `<CTRL_IP>` placeholders** from the earlier variable
rename. Consul clients tried to resolve that literal string as a hostname,
joined nothing, and left a one-node cluster that looked perfectly healthy from
the server. Added a placeholder guard to both playbooks.

**3. Re-running after a reset failed nowhere near its cause.** The role guards
ACL bootstrap with a `creates:` file check, so a leftover file made it skip
bootstrapping and reuse a token that no longer existed in the wiped raft store.
Every later ACL call failed, and the visible symptom was a timeout waiting for an
agent token file. `playbook-reset-cluster.yml` now clears those artifacts.

**4. The data volumes were the wrong shape, twice over.** These are OpenStack
*ephemeral* disks: 125 GB at `/dev/vdb`, ext4 written straight to the device with
no partition table, mounted at `/mnt` by cloud-init.

- `parted` reports that as partition table type `loop` with one pseudo-partition,
  so upstream's `when: partitions | length == 0` never fires, no real partition
  is created, and it then runs `mkfs.xfs` on a `/dev/vdb1` that does not exist.
- There is a second bug behind it that bites even on a blank disk: `vol_info` is
  registered *before* partitioning, so the filesystem step is skipped on the same
  run that creates the partition. Upstream presumably works around it by running
  the playbook twice.
- Then `mkfs` failed with "Device or resource busy" while `fuser`, `lsof` and
  `dmsetup` all showed nothing holding the device — and a raw `dd` to it
  succeeded. The cause: **the LXD snap's mount namespace**, created while
  `/dev/vdb` was mounted at `/mnt`, still held a reference. `mkfs` opens with
  `O_EXCL` and fails; `dd` does not and works.

`playbook-prepare-volumes.yml` now lays the disks out correctly in one pass —
drop the cloud-init fstab entry, reboot to clear stale namespace references,
wipe, partition, format XFS, mount at `/mnt/data` with `prjquota`. All three
site nodes are done and the role's own volume tasks are now no-ops.

### GPU drivers: the hazard was real

`grycap.docker` declares `NVIDIA.nvidia_driver` as a **hard role dependency**,
and role dependencies cannot be skipped with tags or variables. The real role
apt-installs a public NVIDIA driver and reboots, with no check for an existing
one.

These nodes run driver **580.105.08 installed via NVIDIA's `.run` installer**, so
`dpkg` knows nothing about it — `dpkg -l | grep -c nvidia` returns 0. apt would
have installed the older public 550 driver over a working vGPU stack and
rebooted all three GPU nodes.

Our stub at `ansible/roles/NVIDIA.nvidia_driver/` verifies instead of installing,
and `ansible.cfg` puts our roles first so it shadows the Galaxy one. The
container toolkit still installs normally — confirmed by the `nvidia` runtime
being present and the GPU showing up as a Nomad device.

### Also fixed

`scripts/verify-cluster.sh` had two bugs of its own. It piped JSON into
`python3 -` while also feeding the program in via heredoc, so the program read an
empty stdin; and `nomad node status -json` in list form returns no `Meta` field
at all, so metadata needs a per-node query. Both fixed — it now correctly reports
all four constraint fields and flags the `meta.status=test` issue by name.

---

## 2026-08-12 — Stage 1 unblocked: SSH working, all volumes confirmed empty

**SSH access is done.** The cluster key now reaches all four nodes.
`scripts/check-ssh.sh` passes using that key alone, with agent forwarding and
password authentication disabled — so Ansible will work unattended, not only
while someone is logged in.

**The disk question is settled, and the answer is the easy one.** Every node has
the same layout: a 20 GB root disk plus a 125 GB volume at `/dev/vdb`, ext4,
mounted at `/mnt`. On all four, `/mnt` contains only `lost+found` — the directory
`mkfs` creates on every ext4 filesystem, meaning nothing has ever been written
there.

So the reformat that `playbook-nomad.yml` performs on the three site nodes
destroys nothing. **No action needed, and nothing to preserve.**

Improved `check-ssh.sh` to recognise `lost+found` as empty. It was previously
reporting a bare volume as "contains files", which is a warning that trains you
to ignore warnings.

**Nothing has been installed yet, and nothing has been damaged.** The hazard
noted in the previous entry is a property of a playbook we have not run — it
matters when we run it, not before.

**Ansible is not yet installed** on `caios_server`. That is the next step, along
with the cluster playbooks themselves.

**`docs/concepts.md` substantially expanded** — from three tools to sixteen,
grouped into cluster / installation / platform / identity / AI, with a contents
list. Ansible gets the fullest treatment, including the idea that makes it click
(describe the end state, not the steps), what our four file types each do, how to
read its output, and the one sharp edge: it reformats disks without asking.

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

**Measured on `caios_server`:** 3 vCPU, 34 GB RAM, 20 GB root disk, one
`NVIDIA H100L-1-12C` (12 GB slice), Ubuntu 22.04.5. No node can host CVAT, which
needs ~72 GB of RAM in one place.

> *Corrected the same day:* this entry originally said no second volume was
> attached. There is one — 125 GB at `/dev/vdb`, mounted at `/mnt`. See the
> entry above.

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
