# Infrastructure

How the Compute Canada nodes are used, and why. Read this with
`docs/mvp-plan.md`, which says *when* each piece gets built, and
`docs/concepts.md` if Nomad, Consul and Traefik are unfamiliar.

---

## The short version

Seven nodes on Arbutus, all on the private subnet
`192.168.104.0/24`. Three of them do the actual AI work and become the three
"hospital sites" in the federated learning demo. One runs the cluster brain plus
every web service. One is the front door.

**Nothing here has a public IP.** Access is OpenVPN → jumpserver → SSH.

```
        You  --OpenVPN-->  jumpserver  --SSH-->  the cluster
                                                      |
        +---------------------------------------------+
        |                                             |
+-------v-------------------+          +--------------v------------+
| caios_server              |          | caios_edge                |
| 192.168.104.181           |          | 192.168.104.105           |
|---------------------------|          |---------------------------|
| Consul server             |          | Traefik (as a Nomad job)  |
| Nomad server              |          | Nomad CPU client          |
| Ansible control node      |          |                           |
|                           |          | Serves every deployment:  |
| Docker Compose:           |          |   *.pacs-deployments      |
|   Keycloak   (login)      |          |   .192.168.104.105        |
|   Vault      (secrets)    |          |   .sslip.io               |
|   PAPI       (the API)    |          |                           |
|   Dashboard  (the UI)     |          | Ports 80/443, 8002/8003   |
|   Caddy      (TLS)        |          |                           |
+-------------+-------------+          +-------------+-------------+
              |                                      |
              |        private cluster network       |
              +------+--------------+----------------+
                     |              |                |
          +----------v--+  +--------v----+  +--------v----+
          | caios_site_a|  | caios_site_b|  | caios_site_c|
          | .104.20     |  | .104.145    |  | .104.7      |
          |-------------|  |-------------|  |-------------|
          | Nomad GPU   |  | Nomad GPU   |  | Nomad GPU   |
          | client      |  | client      |  | client      |
          |             |  |             |  |             |
          | "Hospital A"|  | "Hospital B"|  | "Hospital C"|
          +-------------+  +-------------+  +-------------+

          192.168.104.188 — caios_llm, the LLM host (joined). See below.
          192.168.104.69  — caios_oscar, serverless inference. Not in Nomad.
```

---

## Node by node

### `caios_server` — 192.168.104.181 — the brain and the web services

This is the node we work from. Ansible runs here; it reaches the others directly
across the private subnet, so there is no bastion hop in the automation.

Two separate things live here:

**The cluster control plane** — Consul server and Nomad server. This decides
where jobs run. It is deliberately **not** a Nomad client, so no user workload
ever lands on it and it stays responsive.

**The web services**, as plain Docker Compose (D-03 — far easier to debug in
three weeks than running them as Nomad jobs):

| Service | What it does |
|---|---|
| Keycloak | Login. Issues the tokens PAPI checks. |
| Vault | Stores per-deployment secrets. Required by the FL server. |
| PAPI | The control-plane API. The only thing holding Nomad credentials. |
| Dashboard | The Angular web UI. Talks only to PAPI. |
| Caddy | TLS termination for the four hostnames. |

**Why the services live here rather than on their own node:** PAPI needs mTLS
certificates to talk to Nomad. On this node those certificates already exist at
`/etc/nomad.d/certs/`, put there by Ansible, and Nomad answers on
`127.0.0.1:4646`. Anywhere else means copying certificates around and opening
port 4646 across the network. That removes a whole class of debugging, and it
frees a node to be a third hospital site.

**Measured specs:** 3 vCPU, 34 GB RAM, 20 GB root disk plus a 125 GB volume at
`/mnt`, one `NVIDIA H100L-1-12C` (a 12 GB slice of an H100), Ubuntu 22.04.5.

Two consequences:

- The root disk has only ~12 GB free, which will not hold the control-plane
  images. `playbook-control-plane.yml` points Docker's storage at `/mnt` before
  installing it — moving it afterwards means copying or losing data.
- **`/mnt` on this node must never be reformatted.** This repository lives at
  `/mnt/CAIOS`. `caios_server` is deliberately absent from the `nomad_volume`
  inventory group for that reason.

> 3 vCPU is on the small side for five containers plus two cluster servers.
> Workable, but if the control plane feels sluggish this is the first thing to
> look at. It does not need its GPU.

### `caios_edge` — 192.168.104.105 — the front door for deployments

Runs **Traefik**, which is what gives every deployment its own web address.
Traefik runs *as a Nomad job*, not as Compose — Ansible deploys it and pins it
to this node, because every deployment hostname resolves to this node's IP.

It is also the cluster's **CPU client**. Not optional: `ai4-ansible` requires at
least one, and this is it.

Its GPU sits idle. That is the price of a dedicated ingress node, and it is
worth paying — if Traefik goes down, nothing is reachable.

> This node can never run user deployments. Ansible tags it
> `meta.type = traefik`, and every deployment requires `meta.type = compute`.
> By design.

### `caios_site_a/b/c` — .20, .145, .7 — the three hospitals

Nomad GPU clients. These run everything a user deploys: dev environments, model
inference, the federated learning clients.

**These three nodes are the demo.** The federated learning story is that each
stands for a hospital, holds its own slice of the data, and trains locally —
the model weights travel, the data does not. Three separate machines make that
structurally true rather than a claim on a slide.

**Each has a second volume, and Ansible will reformat it.** These instances ship
with a 125 GB volume at `/dev/vdb`, already formatted ext4 and already mounted at
`/mnt`. For the three site nodes, `playbook-nomad.yml` repartitions it, formats
it **XFS**, and mounts it at `/mnt/data`.

That step **erases whatever is on `/mnt`** on those nodes. Confirm they hold
nothing of value first — the check is in `ansible/inventory/hosts.ini`.

Why XFS rather than leaving it alone: Docker limits how much disk each container
can use via `storage-opt`, and that only works on XFS with project quotas. Without
it a single runaway deployment fills the node. The cluster test suite also asserts
the device path `/dev/vdb1` literally, so a node left as-is is marked failed and
receives no work.

**This applies only to Nomad client nodes.** `caios_server` keeps its `/mnt` as
ext4, untouched — nothing on the control plane needs per-container quotas, and
this repository lives there.

### 192.168.104.188 — `caios_llm`, the LLM host  *(joined 2026-08-19)*

Six addresses were provided; the node count was given as five. This one was left
out of the cluster until we knew what it was.

**Answered on 2026-08-19 (D-31): it is ours, unused, and identical to the other
five** — 3 vCPU, ~34 GB RAM, one `NVIDIA H100L-1-12C`, a 125 GB volume. It
becomes **`caios_llm`**, a fourth Nomad GPU compute client dedicated to the LLM
tool, so that vLLM and Open WebUI never compete with the three hospital nodes
for CPU or GPU.

**Joined on 2026-08-19** as the cluster's fourth GPU compute client, Nomad agent
`caios-wn-gpu-3`. Its `/dev/vdb` was reformatted XFS and mounted at `/mnt/data`
(it held only `lost+found`), and it carries `meta.role = llm` so the LLM job
prefers it. `docs/llm-infrastructure.md` explains the reformat in full.

**Confirmed in production on 2026-08-22:** with an LLM serving on this node,
the three hospitals ran 10 federated rounds in 34.6 s while the LLM answered at
71-81 ms throughout. The separation works — neither workload degraded the other.

**One operational rule came out of it:** deploy the LLM *before* the federated
learning workspaces. With four compute nodes, spread scheduling will otherwise
put one "hospital" on this machine — measured, and a soft anti-affinity does not
prevent it. See `scripts/deploy-fl-demo.sh`.

It is **not** the CVAT host: CVAT needs ~72 GB of RAM in one place and this node
has 34, so D-16 stands unchanged.


### `192.168.104.69` — `caios_oscar`, serverless inference  *(added 2026-08-25)*

Hostname `ai4eosc-7`. Provided to host OSCAR, and **deliberately outside the
Nomad cluster**. Measured, not assumed:

| | ai4eosc-7 | every other CAIOS node |
|---|---|---|
| vCPU | **16** | 3 |
| RAM | **58 GB** | 34 GB |
| `/mnt` | **560 GB** ext4, empty | 125 GB |
| root | 20 GB | 20 GB |
| GPU | **none** | 1× `NVIDIA H100L-1-12C` |

By a wide margin the largest machine in the project. Every sizing constraint
recorded in this repository — the 2-CPU cap on modules, the mail sidecar
patched out to reclaim a core, CPU-only FL clients — comes from 3-vCPU nodes
and does not apply here.

**It runs K3s, not Nomad, and must never run both.** Both manage containerd
and cgroups; a node running each half-works in ways that are miserable to
diagnose. It is therefore absent from `ansible/inventory/hosts.ini` entirely,
and `verify-cluster.sh` will never see it.

**Its `/mnt` needs no reformat.** Unlike the three site nodes, nothing here
wants XFS project quotas and `ai4-nomad_tests` never runs against it, so the
volume stays ext4 exactly as provisioned. Nothing about adding this node
touches the running platform.

**The 20 GB root disk is the operational constraint.** K3s defaults every path
to `/var/lib/rancher/k3s`; left alone it fills `/`. Everything goes to `/mnt`
via `--data-dir`, verified by measurement — the same trap Stage 3 hit when
Docker's `data-root` was set and containerd's image store went to the system
disk anyway.

**No GPU.** OSCAR services run DEEPaaS module images, which infer on CPU. Not
a limitation for inference; it does mean GPU-backed serverless would need a
different node.

**Not the CVAT host either.** 58 GB against the ~71 GB CVAT wants on one
machine. Closer than anything before it, but still short, so D-16 stands.

Full plan: `docs/oscar-plan.md`.

---

## Addresses

Every hostname derives from `configs/env/caios.env`.

**Changed 2026-08-25.** A floating IP (`134.87.8.230`) was attached to
`caios_server`, so the four control-plane hostnames now derive from
`CAIOS_PUBLIC_IP` rather than from the private `CAIOS_CTRL_IP`. The private
addresses are unchanged and still wire PAPI to Nomad over loopback.
See `docs/public-access.md`.

| Hostname | Resolves to | Serves |
|---|---|---|
| `dashboard.134.87.8.230.sslip.io` | caios_server | The web UI |
| `api.134.87.8.230.sslip.io` | caios_server | PAPI |
| `auth.134.87.8.230.sslip.io` | caios_server | Keycloak |
| `vault.134.87.8.230.sslip.io` | caios_server | Vault (admin only) |
| `*.pacs-deployments.192.168.104.105.sslip.io` | caios_edge | **Every deployment** |

### Why hostnames at all, when everything is private

Because the platform gives **every deployment its own web address**, and Traefik
decides which container a request belongs to by reading the `Host:` header — not
by port number. Start a Jupyter workspace and it appears at
`ide-a1b2c3.pacs-deployments...`; its API at `api-a1b2c3.pacs-deployments...`.
With one port and no hostnames there is nowhere to route.

**We do not need to buy a domain or configure any DNS.** `sslip.io` is a free
public DNS service that resolves any name ending in an IP address back to that
IP — including private ones. Verified from the node:

```
dashboard.192.168.104.181.sslip.io  ->  192.168.104.181
```

Arbitrary prefixes work, so the wildcard works. No account, no zone, nothing to
request.

**Two caveats.**

1. Each engineer's machine must be on the VPN *and* must not have a resolver
   that discards private-IP DNS answers. Some routers and corporate resolvers do
   this as "DNS rebinding protection". If a hostname fails to resolve on your
   laptop but works on the node, that is the cause — the fallback is a handful
   of `/etc/hosts` entries.
2. No trusted TLS certificate. Let's Encrypt issues wildcards only via DNS-01,
   which needs control of the zone, and we do not control `sslip.io`. So MVP
   uses a self-signed wildcard and the browser shows a warning you click past
   once. V1 swaps in a real domain; two values change and nothing else.

### The thing worth raising with the supervisor

**Nobody outside the VPN can see any of this.** That is fine for building, and
fine for a recorded walkthrough. It rules out a live demo to external reviewers
unless one of these happens:

- a **floating IP** is assigned to `caios_edge` and `caios_server` (Arbutus has
  them; they are quota-limited and have to be requested), or
- reviewers are given VPN access, which is unlikely to be acceptable, or
- the demo is **recorded**, which we planned to do anyway as insurance.

The cheapest safe answer is: record it, and request a floating IP in parallel in
case a live demo is wanted. Requesting one costs an email and has a lead time;
discovering the need in week three does not end well.

---

## Security groups

All nodes are in one OpenStack project on one subnet, so the rules are simpler
than the upstream guide assumes — there is no public exposure to defend.

| Group | Applied to | Rules |
|---|---|---|
| `default` | all | Egress all; ICMP; TCP 22; intra-project traffic |
| `caios_consul` | all | TCP 8300, 8301, 8302, 8500-8503, 8600; UDP 8301, 8302, 8600; TCP 21000-21255 |
| `caios_nomad` | all | TCP 4646, 4647, 4648; UDP 4648 |
| `caios_traefik` | caios_edge, caios_server | TCP 80, 443; **TCP 8002-8003 (NVFLARE)**; TCP 8081 |

Scope every rule to the subnet `192.168.104.0/24`. `scripts/openstack-security-groups.sh`
prints the commands; it only creates them with `--apply`.

If intra-project traffic is already unrestricted on Arbutus, most of this is a
no-op — but it is worth applying anyway so the cluster does not depend on a
default that could change.

---

## How the pieces talk

Worth internalising, because it explains most failures:

1. The **browser** only ever talks to the dashboard and, through it, to PAPI.
2. **PAPI** is the only component holding Nomad credentials. Misconfigure it and
   the dashboard still renders perfectly while every button fails quietly. When
   something looks broken in the UI, check PAPI first.
3. **Nomad** decides which node runs a job, using constraints on node metadata.
   A node missing a tag looks completely healthy and silently never receives
   work. The top cause of "why is my job stuck pending".
4. **Traefik** learns about running jobs through Consul and routes to them by
   hostname. If a deployment is running but unreachable, the problem is Consul
   or Traefik, not Nomad.
