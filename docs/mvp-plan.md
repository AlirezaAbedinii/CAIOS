# MVP and V1 plan

This replaces `docs/phase-plan.md` as the working plan. The phase plan stays as
the reference for the full 21-day shape; this document is what we actually
execute against, split so that there is something demonstrable early.

**Guiding rule:** anything that adds real complexity without visibly improving
the demo gets deferred to V1 or cut. Where something is deferred, there is a
one-line note saying what we lose.

---

## What MVP means here

**MVP = a researcher logs in through a browser, deploys a model from a medical
catalogue, opens a GPU workspace, and runs a federated training across three
simulated hospital sites.**

That is the whole grant story end to end. It is deliberately missing polish,
annotation, and a trusted TLS certificate. Everything missing is either
cosmetic or additive — none of it requires redoing what MVP builds.

**Target: 8 working days.** Then V1 hardens and beautifies it.

---

## MVP scope

### In

Consul + Nomad + Traefik cluster on 5 nodes · self-signed wildcard TLS over
`sslip.io` · Keycloak with local demo accounts · Vault · PAPI · CAIOS-branded
dashboard · dev environment (Jupyter/VS Code) · **Flower federated learning
across three sites** · curated medical catalogue · Statistics page rendering
live cluster data

### Deferred to V1 (with what we lose)

| Deferred | What we lose until V1 |
|---|---|
| Real domain + Let's Encrypt | A browser TLS warning on first visit. Cosmetic, but bad on a recording. |
| Nextcloud storage | The Storage tab, and "data already mounted". Datasets get copied into the dev-env directly instead. |
| CVAT annotation | Demo beat 4 (~3 min). Needs the 72 GB node, which does not exist yet. |
| Namespace-per-site VOs | Sites are *chosen* at deploy time rather than *enforced* by login. Same demo, weaker claim. |
| NVFLARE | A second FL framework. Flower alone tells the story. |
| AI4Life / bioimage.io loader | Two extra catalogue entries. Cheap to add later. |
| `ai4-accounting` history | Statistics shows live usage, not accumulated history. |
| MLflow, LLM service, custom module | Stretch goals, unchanged. |

### Cut entirely

OSCAR · Harbor · Jenkins · drift monitoring · provenance · low-code pipelines ·
carbon accounting · real PACS/DICOM integration. Unchanged from
`docs/context.md` §2 — these go on a roadmap slide.

---

## MVP — Stage 0: local scaffold (no nodes touched)

**Status: done in this session.** Everything below is committed and reviewable
before a single command runs against a node.

- [x] Repo scaffold and `.gitignore`
- [x] `docs/infrastructure.md` — the five-node design
- [x] `docs/questions-for-supervisor.md` — for tomorrow's meeting
- [x] `ansible/inventory/hosts.ini` + `group_vars/all.yml` with our overrides
- [x] `configs/papi/` — `main.yaml`, `datacenters.csv`, `.env.template`
- [x] `configs/dashboard/` — CAIOS tenant config and theme
- [x] `compose/` — Keycloak, Vault, PAPI, dashboard, Caddy
- [x] `patches/` — the four unavoidable upstream source edits
- [x] `scripts/` — vendor pinning, certificate generation, cluster verification

**What is needed to move to Stage 1:** the five node IPs, and the two floating
IPs. Fill them into `ansible/inventory/hosts.ini` and
`configs/env/caios.env`, and everything else is already written.

---

## MVP — Stage 1: cluster (2 days)

Goal: a job deployed by hand is reachable over HTTPS at its own subdomain.

- [ ] Confirm both floating IPs; note them — every hostname derives from them
- [ ] Create the four security groups (`scripts/openstack-security-groups.sh`
      prints the exact commands; nothing runs without approval)
- [ ] Attach one volume per site node; confirm each appears as `/dev/vdb`
- [ ] `~/.ssh/config` with `ProxyJump` through node 1; both engineers verify
- [ ] `ansible-galaxy install grycap.docker`
- [ ] `bash scripts/make-traefik-certs.sh` — self-signed wildcard, packaged the
      way the Traefik role expects
- [ ] `ansible-playbook -i ansible/inventory/hosts.ini vendor/ai4-ansible/playbook-consul.yaml`
- [ ] `ansible-playbook -i ansible/inventory/hosts.ini vendor/ai4-ansible/playbook-nomad.yaml`
- [ ] `bash scripts/verify-cluster.sh` — prints every node's metadata and region
- [ ] Run the patched `ai4-nomad_tests`; **confirm every client flips to
      `meta.status=ready`**
- [ ] Deploy `nomad-jobs/smoke-test.hcl` by hand; open it over HTTPS

> **Gate — hard.** Both must be true:
> 1. A hand-deployed job answers over HTTPS at its own subdomain.
> 2. Every compute node reports `meta.status=ready`.
>
> Condition 2 is not a formality. Until it holds, PAPI's job templates constrain
> every deployment to nodes that do not exist, and Stage 3 will fail in a way
> that looks like a PAPI bug. Do not skip it because the cluster "looks fine".

---

## MVP — Stage 2: identity and secrets (1 day)

Goal: a token issued by our Keycloak is accepted by PAPI.

- [ ] `docker compose up keycloak vault caddy` on node 1
- [ ] Import `configs/keycloak/caios-realm.json` — creates the realm, the `papi`
      and `dashboard` clients, and the role structure
- [ ] Create demo users: one researcher, one admin
- [ ] Assign the realm role `access:vo.caios.ca:ap-u`
      — **the name matters**; PAPI parses roles with the regex
      `access:<vo>:<level>` and rejects anything else
- [ ] Configure Vault's JWT auth backend against our realm
      (`scripts/vault-bootstrap.sh`)
- [ ] Verify: fetch a token from Keycloak, decode it, confirm it carries `sub`,
      `iss`, `name`, `email`, an `account` audience, and the role

**Gate:** `scripts/check-token.sh` prints a decoded token containing the
correctly-named role.

---

## MVP — Stage 3: control plane and dashboard (2 days)

Goal: log in through the browser, deploy a module, open it. No terminal.

- [ ] Apply `patches/ai4-papi/` — Keycloak URL and Vault address
- [ ] Copy `configs/papi/main.yaml` and `var/datacenters.csv` into place
- [ ] `docker compose up papi` with `IS_PROD` unset
- [ ] Verify `https://api.<CTRL_IP>.sslip.io/docs` renders
- [ ] Make one authenticated call with a real token
- [ ] Build the dashboard: `docker build -f docker/Dockerfile.prod
      --build-arg TENANT=caios`
- [ ] `docker compose up dashboard`
- [ ] Click through: log in → Marketplace → deploy a module → Deployments →
      open its endpoint

**Gate:** the click-through above completes without touching a terminal.

---

## MVP — Stage 4: federated learning (2 days)

The headline. Everything above exists to make this work.

- [ ] Deploy one dev environment; confirm Jupyter opens and the GPU is visible
- [ ] Prepare and partition the dataset non-IID across three sites
      (`demo/fl/partition.py`) — Site A mostly class 1, Site B mostly class 2,
      Site C mixed
- [ ] Deploy the Flower FL server: `service: jupyter`, `min_fit_clients: 3`
- [ ] Deploy three dev environments, one per site node
- [ ] **CPU-only for the FL clients.** PAPI caps one user at 2 GPUs across all
      running deployments; three GPU clients would be rejected on the third.
      They are also downsampled hard, so CPU is plenty.
- [ ] Run a full federated training; confirm accuracy improves across rounds
- [ ] Produce the three-line chart: site-alone vs centralised vs federated

**Gate:** a federated training completes across three sites, driven from the
dashboard.

---

## MVP — Stage 5: content and branding (1 day, runs in parallel)

- [ ] Curated medical catalogue live (`catalog/`)
- [ ] CAIOS logo, palette, favicon, title strings
- [ ] Every `cloud.ai4eosc.eu` link repointed or removed — including the
      analytics beacon, which otherwise reports our demo traffic to a third party
- [ ] `docs/demo-script.md` written and timed

**Gate:** someone unfamiliar with the project opens the dashboard and reads it
as a medical imaging platform.

---

## V1 — after MVP demonstrates end to end

Ordered by value per day, highest first.

1. **Real domain + Let's Encrypt wildcard** (0.5 day) — removes the browser
   warning. Do this before recording anything.
2. **Rehearse twice, record once** (1.5 days) — run the demo end to end, then
   again from a clean state. Pre-pull every Docker image onto every node. This
   is where the things that only worked because of something you did on day
   three show up.
3. **Namespace-per-site** (1 day) — three VOs mapped to three namespaces, one
   per node. Turns "we chose Site B" into "Site B's account physically cannot
   deploy anywhere else". Materially strengthens the FL claim.
4. **Nextcloud storage** (1 day) — the Storage tab, and datasets mounted rather
   than copied.
5. **CVAT** (0.5 day, needs the 72 GB node) — demo beat 4.
6. **NVFLARE** (0.5 day) — second FL framework. Remember TCP 8002-8003.
7. **AI4Life / bioimage.io loader** (0.5 day) — cheapest catalogue credibility.
8. **Stretch:** MLflow · custom neuroscience module · LLM service (quantised —
   12 GB VRAM will not hold a 7B model at fp16).

---

## Fallback ladder

Decide these now, not at 2am.

- **Cluster not up after Stage 1:** collapse to single-node Nomad on one large
  VM. Loses multi-site FL, keeps the entire dashboard and tools story. One day
  to recover, still a good demo.
- **Dashboard not working after Stage 3:** demo through PAPI's Swagger UI and
  the Nomad UI. Weaker, but it proves the platform works, and it is honest.
- **FL not converging in Stage 4:** demo the server and clients connecting and
  exchanging rounds on a trivial dataset. The point is the federated mechanism,
  not the model's accuracy. Do not let a model-quality problem look like an
  infrastructure failure in front of the audience.
- **Anything catastrophic:** play the recording and walk the architecture. This
  is why V1 item 2 exists.

---

## Known risks carried into MVP

These are accepted, not solved. Each has a note so nobody rediscovers them.

| Risk | Why we are accepting it | Trigger to act |
|---|---|---|
| Self-signed TLS | Free, works today, zero lead time | Before recording |
| Vault is on the FL critical path | We run our own; patched address | If Stage 2 slips past a day, patch Vault out of the FL path instead (~2 h, loses the per-client token beat) |
| Sites chosen, not enforced | Namespace-per-site costs a day and changes Keycloak | V1 item 3 |
| No CVAT | The 72 GB node does not exist yet | When it does |
| Statistics has no history | Live cluster data renders correctly | Only if the supervisor asks for accumulated usage |
| One Nomad datacenter | Upstream Ansible cannot do three; sites are node-level, not DC-level | Never — this is the correct design, just not the one originally assumed |
