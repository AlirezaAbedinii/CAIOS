# Infrastructure

How the five Compute Canada nodes are used, and why. Read this with
`docs/mvp-plan.md`, which says *when* each piece gets built.

---

## The short version

Five nodes, all with GPUs. Three of them do the actual AI work and become the
three "hospital sites" in the federated learning demo. One runs the cluster
brain plus every web service. One is the front door.

Only **two floating (public) IPs** are needed. Everything else is private and
reached by SSH through node 1.

```
                    INTERNET
                        |
        +---------------+----------------+
        |                                |
   FIP #1                            FIP #2
        |                                |
+-------v---------+            +---------v---------+
| 1. caios_server |            |  2. caios_edge    |
|-----------------|            |-------------------|
| Consul server   |            | Traefik           |
| Nomad server    |            |  (as a Nomad job) |
| SSH bastion     |            | Nomad CPU client  |
|                 |            |                   |
| Docker Compose: |            | Serves:           |
|  - Keycloak     |            |  *.pacs-          |
|  - Vault        |            |  deployments.<..> |
|  - PAPI         |            |                   |
|  - Dashboard    |            | Ports 80/443      |
|  - Caddy (TLS)  |            |  + 8002/8003      |
+--------+--------+            +---------+---------+
         |                               |
         |     private cluster network   |
         +----+-------------+------------+----+
              |             |                 |
     +--------v----+ +------v------+ +--------v----+
     | 3. site_a   | | 4. site_b   | | 5. site_c   |
     |-------------|  |------------| |-------------|
     | Nomad GPU   | | Nomad GPU   | | Nomad GPU   |
     | client      | | client      | | client      |
     |             | |             | |             |
     | "Hospital A"| |"Hospital B" | |"Hospital C" |
     +-------------+ +-------------+ +-------------+
```

---

## Node by node

### 1. `caios_server` — the brain and the front door for services

**Public IP: yes (floating IP #1). This is also the SSH bastion.**

Runs two separate things that happen to live on the same box:

*The cluster control plane* — Consul server and Nomad server. This is what
decides where jobs run. It is **not** a Nomad client, so no user workload ever
lands here; it stays responsive.

*The web services*, as plain Docker Compose (decision D-03 — far easier to debug
in three weeks than running them as Nomad jobs):

| Service | What it does |
|---|---|
| Keycloak | Login. Issues the tokens PAPI checks. |
| Vault | Stores per-deployment secrets. **Required by the FL server** — see below. |
| PAPI | The control plane API. The only thing holding Nomad credentials. |
| Dashboard | The Angular web UI. Talks only to PAPI. |
| Caddy | TLS termination and routing for the four hostnames above. |

**Why services live here and not on their own node:** PAPI needs mTLS
certificates to talk to Nomad. On this node those certificates already exist at
`/etc/nomad.d/certs/` because Ansible put them there, and PAPI can reach Nomad
at `127.0.0.1:4646`. Putting PAPI anywhere else means copying certificates
around and opening port 4646 across the network. This removes a whole class of
Phase-3 debugging, and it frees a node to be a third hospital site.

### 2. `caios_edge` — the front door for deployments

**Public IP: yes (floating IP #2).**

Runs Traefik, which is what gives every deployment its own subdomain. Traefik
runs *as a Nomad job*, not as Compose — the Ansible role deploys it and pins it
to this node, because DNS points here.

It is also registered as the cluster's **CPU client**. This is not optional:
`ai4-ansible` requires at least one CPU client and the Traefik node is it.

Its GPU sits idle. That is the price of having a dedicated ingress node, and
it is worth paying — Traefik going down takes the whole demo with it.

> Note: this node can never run user deployments. Ansible tags it
> `meta.type = traefik`, and every PAPI job template requires
> `meta.type = compute`. That is by design.

### 3-5. `caios_site_a`, `caios_site_b`, `caios_site_c` — the three hospitals

**Public IP: no.** Reached by SSH through node 1.

Nomad GPU clients. These run everything a user deploys: dev environments,
model inference, the federated learning clients.

**These three nodes are the demo.** The whole federated learning story is that
each one stands for a hospital, holds its own slice of the data, and trains
locally — the model weights travel, the data does not. Three separate nodes make
that structurally true rather than a claim on a slide.

Each needs an **attached volume, formatted XFS**. This is not optional either:
Docker's disk limits require XFS, and without it nodes fill with images and jobs
fail in confusing ways. Ansible formats and mounts it, but the volume must be
attached in OpenStack first, and it must show up as `/dev/vdb` — the cluster
test suite asserts exactly that.

---

## Two public IPs, four hostnames

Everything the outside world touches resolves to one of two addresses.

| Hostname | Points at | Serves |
|---|---|---|
| `dashboard.<FIP1>.sslip.io` | node 1 | The web UI |
| `api.<FIP1>.sslip.io` | node 1 | PAPI |
| `auth.<FIP1>.sslip.io` | node 1 | Keycloak |
| `vault.<FIP1>.sslip.io` | node 1 | Vault (admin only) |
| `*.pacs-deployments.<FIP2>.sslip.io` | node 2 | **Every user deployment** |

### About that wildcard, and your question on ports

You asked whether we can just expose a port on one instance instead of dealing
with a domain. Short answer: not really, and here is the honest reason.

The platform gives **every deployment its own hostname**. Start a Jupyter
workspace and it comes up at `ide-a1b2c3.pacs-deployments.<...>`; its API is at
`api-a1b2c3.pacs-deployments.<...>`. This is not a preference we can configure
away — it is how Traefik decides which of the many running containers your
request belongs to. Traefik routes on the `Host:` header, not on port numbers.
With one port and no hostnames, there is nowhere to route to.

**But we do not need to buy a domain to get started.** For the MVP we use
`sslip.io`, a free public DNS service that resolves any hostname ending in an IP
address back to that IP. `api-a1b2c3.pacs-deployments.206.12.1.2.sslip.io`
resolves to `206.12.1.2`, with no DNS account, no zone access, and nothing to
request from anyone. Wildcards work because arbitrary prefixes are allowed.

The one thing it cannot give us is a trusted TLS certificate. Let's Encrypt
issues wildcard certificates only via DNS-01, which needs API control of the
zone — and we do not control `sslip.io`. So:

- **MVP:** self-signed wildcard certificate. Everything works; the browser shows
  a warning on first visit that you click past once per session.
- **V1:** a real domain (about $15/year) plus a Let's Encrypt wildcard. Same
  configuration, two values changed, no rework.

The browser warning is the *only* thing the domain buys us — but it is the one
thing a recorded walkthrough cannot have. That is why "buy a domain" is the
first item in `docs/questions-for-supervisor.md`. It is cheap, it has a lead
time, and it should be started tomorrow rather than in week three.

---

## Security groups

Four groups. Upstream documents a fifth (`Federation`) for multi-site clusters;
we are a single site, so we skip it deliberately.

| Group | Applied to | Rules |
|---|---|---|
| `default` | all nodes | Egress all; ICMP; TCP 22 from admin IPs; intra-group TCP/UDP |
| `caios_consul` | all nodes | TCP 8300, 8301, 8302, 8500-8503, 8600; UDP 8301, 8302, 8600; TCP 21000-21255 — **cluster subnet only** |
| `caios_nomad` | all nodes | TCP 4646, 4647, 4648; UDP 4648 — cluster subnet only. Upstream opens 4646 to the world; we do not need to, because PAPI reaches Nomad over loopback. |
| `caios_traefik` | node 2 | TCP 80, 443 from anywhere; **TCP 8002-8003 from anywhere (NVFLARE)**; TCP 8081 subnet only |

Node 1 additionally needs TCP 80 and 443 from anywhere, for the dashboard and
API. Add it to `caios_traefik` or give it its own rule — either is fine.

---

## What happens when the sixth node arrives

You mentioned you can add a node with 72 GB of RAM. That node is for **CVAT**,
the annotation tool, which is a single Nomad job containing 22 containers that
must all land on the same machine and together ask for about 71 GB of RAM. No
node in the current layout can host it.

It joins as a fourth compute client, tagged the same way as nodes 3-5. Nothing
about the existing setup changes. Until it exists, CVAT stays out of the demo —
it is beat 4 of 7 and roughly three minutes, so its absence costs us little.

---

## How the pieces actually talk

Worth internalising, because it explains most failures:

1. The **browser** only ever talks to the dashboard and, through it, to PAPI.
2. **PAPI** is the only component that holds Nomad credentials. If PAPI is
   misconfigured the dashboard still renders perfectly and every button fails
   quietly. When something looks broken in the UI, check PAPI first.
3. **Nomad** decides which node runs a job, using constraints on node metadata.
   A node missing a tag looks completely healthy and silently never receives
   work. This is the single most common cause of "why is my job stuck pending".
4. **Traefik** learns about running jobs through Consul, and routes to them by
   hostname. If a deployment is running but unreachable, the problem is Consul
   or Traefik, not Nomad.
