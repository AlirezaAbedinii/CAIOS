# The moving parts, explained

Written for someone who has not used Nomad, Consul or Traefik before. No prior
knowledge assumed. If you know Kubernetes, there is a translation table at the
end — but read the rest first, because the analogy misleads in a few places.

---

## The problem all of this solves

A researcher clicks "deploy" on a model in a web page. Thirty seconds later they
have a JupyterLab running on a GPU somewhere in the cluster, reachable at its own
web address, with a password only they know.

Between the click and the notebook, four questions have to be answered:

1. **Which machine should run this?** → Nomad
2. **Where did it end up, and is it alive?** → Consul
3. **How does a browser request reach it?** → Traefik
4. **Is this person allowed, and what are they allowed to do?** → Keycloak + PAPI

Each tool answers exactly one. That is the whole architecture.

---

## Nomad — decides which machine runs what

**The one-line version:** you describe a job you want running; Nomad finds a
machine with room for it and starts it there.

You never say "run this on node 3". You say "this needs 4 CPUs, 8 GB of RAM and
a GPU", and Nomad picks. If the machine dies, Nomad notices and starts the job
somewhere else.

### Vocabulary you will actually meet

| Term | What it means |
|---|---|
| **Job** | What you want running, described in a `.hcl` file. "One JupyterLab with a GPU." |
| **Task** | One container inside a job. Most jobs have one; CVAT has 22. |
| **Group** | A bundle of tasks that must run **on the same machine**. |
| **Allocation** | One actual running copy of a group, on a specific node. The thing you look at when debugging. |
| **Client / node** | A machine that runs work. |
| **Server** | A machine that *decides*. Runs no user work. `caios_server` is ours. |
| **Namespace** | A partition for organising and isolating jobs. Ours is `caios`. |
| **Datacenter** | A grouping of nodes. We have exactly one, called `caios`. |
| **Evaluation** | Nomad's record of *thinking about* placing a job. Where to look when a job will not start. |

### Constraints — the thing that will confuse you first

A job can demand properties of the machine it runs on:

```hcl
constraint {
  attribute = "${meta.type}"
  value     = "compute"
}
```

"Only run me on a node tagged `type=compute`."

Every node carries **metadata** — arbitrary key/value labels set when we
configure it. Our nodes carry `status`, `type`, `tags`, `namespace` and `domain`.

**This is the single biggest source of confusion in this platform.** Every job
the platform creates carries four requirements: `meta.status=ready`,
`meta.type=compute`, a matching `meta.namespace`, and the right region. If a node
fails *any* of them, Nomad will not place the job there — and says nothing
useful. `nomad node status` shows every node as healthy and `ready`, because that
is Nomad's own health, which is a different thing from our `meta.status` label.

The symptom is a job that sits in "pending" forever. `scripts/verify-cluster.sh`
checks all four in one command, which is why it exists.

### Commands worth knowing

```bash
nomad node status                          # every machine
nomad node status -verbose <node>          # including its metadata
nomad job status -namespace caios <job>    # is it running?
nomad eval status <eval-id>                # WHY it is not running
nomad alloc logs <alloc-id>                # the container's own output
```

`nomad eval status` is the one people forget. It reports `ConstraintFiltered`,
which names the exact requirement that excluded every node.

---

## Consul — the address book and the health checker

**The one-line version:** Consul keeps a live list of what is running where, and
whether it is healthy.

Nomad places a job and tells Consul: "there is now a service called
`abc123-ide` at 192.168.104.20 port 29471." Consul records that, then keeps
checking it is still alive. When the job stops, the entry disappears.

That matters because **the port is unpredictable**. Nomad assigns a random high
port to avoid collisions between deployments. Nothing can hardcode it, so
something has to keep track. That is Consul.

Consul also does two other jobs here:

- **Cluster membership.** It is how the five machines find each other.
- **Access control.** It issues the tokens Nomad and Traefik use to talk to it.

You will rarely touch it directly. When you do:

```bash
consul members            # are all five machines talking to each other?
consul catalog services   # what is registered right now?
```

If a deployment is *running* but *unreachable*, Consul is the first thing to
check — the job may never have registered.

---

## Traefik — the front door

**The one-line version:** Traefik is the single entry point for web traffic, and
it works out which container each request belongs to by reading the address the
browser asked for.

This is the part people find surprising, so it is worth being concrete.

There is one Traefik, on `caios_edge`, holding ports 80 and 443. Every
deployment's web address points at that one machine. When a request arrives:

```
Browser asks for:  https://ide-abc123.pacs-deployments.192.168.104.105.sslip.io
                                    |
                          Traefik reads the Host: header
                                    |
                          asks Consul: what is "abc123-ide"?
                                    |
                          Consul: 192.168.104.20 port 29471
                                    |
                          Traefik forwards the request there
```

**Traefik routes on hostname, not port.** That is why the platform needs a
wildcard DNS entry and cannot simply "expose a port". With one port and no
hostnames, there is nothing to distinguish twenty running deployments from each
other.

Traefik learns about services automatically, by watching Consul. Nobody edits a
Traefik config when a deployment starts — the job carries tags like:

```
traefik.enable=true
traefik.http.routers.abc123.rule=Host(`ide-abc123.pacs-deployments...`)
```

Consul stores those tags, Traefik reads them, and routing appears. This is why
a broken Consul looks like a broken Traefik.

Traefik also terminates TLS: it holds the certificate and speaks plain HTTP to
the containers behind it. So there is exactly one certificate to manage, and it
has to be a **wildcard**, because deployment hostnames are unpredictable.

---

## How they work together

Deploying a Jupyter notebook, start to finish:

```
1. Browser  ---------->  Dashboard        "deploy the dev environment"
2. Dashboard ---------->  PAPI            with the user's login token
3. PAPI                                   checks the token against Keycloak
4. PAPI                                   fills in a Nomad job template
5. PAPI     ---------->  Nomad            "please run this"
6. Nomad                                  finds a node satisfying the constraints
7. Nomad    ---------->  caios_site_a     starts the container
8. Nomad    ---------->  Consul           "abc123-ide is at .20:29471"
9. Traefik  <----------  Consul           notices the new service
10. Browser ---------->  Traefik          https://ide-abc123.pacs-...
11. Traefik ---------->  caios_site_a     forwards it
```

Reading that list backwards is how you debug. A failure at step 6 is a
constraint problem. At step 8, Consul. At step 9 or 11, Traefik.

---

## The other pieces, briefly

**PAPI** (Platform API) — the platform's own API, written in Python. The
dashboard talks *only* to this; it never touches Nomad. PAPI holds the
credentials for Nomad, checks permissions, and turns "deploy this model" into a
Nomad job. **It is the only component with Nomad credentials**, which is why a
misconfigured PAPI produces a dashboard that renders perfectly and in which every
button fails silently.

**Keycloak** — the login system. Issues a signed token proving who you are and
what you may do. PAPI verifies the signature on every request.

**Vault** — an encrypted store for secrets. Each deployment gets its own. The
federated learning server needs it, which is why it is not optional here.

**Ansible** — how we install Consul, Nomad and Traefik on five machines
repeatably. Run it twice and the second run changes nothing.

**Docker Compose** — how we run the five web services on `caios_server`. Simpler
than Nomad for things that never need to move.

---

## If you know Kubernetes

| Kubernetes | Here | Caveat |
|---|---|---|
| Pod | Allocation | |
| Deployment | Job | |
| Node | Client / node | |
| Namespace | Namespace | Close enough |
| Ingress + controller | Traefik | Traefik is also the load balancer |
| Service + kube-dns | Consul | Consul is a separate product, not built in |
| nodeSelector / affinity | Constraint / affinity | Same idea, different syntax |
| etcd | Raft inside Nomad and Consul | Not separately operated |
| Helm chart | `.hcl` job file | Much simpler, no templating engine |

**Where the analogy breaks:** Nomad does far less than Kubernetes. There is no
built-in service mesh, no operators, no CRDs, no controller pattern. A job file
is usually under 100 lines and does what it says. That is the appeal — and it is
why "just use a Helm chart" is not an option here.
