# The moving parts, explained

Written for someone who has not used Nomad, Consul or Traefik before. No prior
knowledge assumed. If you know Kubernetes, there is a translation table at the
end — but read the rest first, because the analogy misleads in a few places.

---

## Contents

**The cluster:** [Nomad](#nomad--decides-which-machine-runs-what) ·
[Consul](#consul--the-address-book-and-the-health-checker) ·
[Traefik](#traefik--the-front-door)

**Getting it installed:** [Ansible](#ansible--installs-everything-repeatably) ·
[Docker and containers](#docker-and-containers--the-unit-everything-ships-in) ·
[Docker Compose](#docker-compose--a-few-containers-on-one-machine)

**The platform:** [PAPI](#papi--the-platforms-own-api) ·
[The dashboard](#the-dashboard--the-only-screen-anyone-sees) ·
[DEEPaaS](#deepaas--the-common-shape-of-every-model) ·
[Modules and tools](#modules-and-tools--two-kinds-of-thing-you-can-deploy)

**Identity and secrets:** [Keycloak](#keycloak--who-you-are) ·
[Vault](#vault--secrets-that-are-not-in-files) ·
[VO](#vo--which-group-you-belong-to)

**The AI parts:** [Federated learning](#federated-learning--the-headline) ·
[Flower and NVFLARE](#flower-and-nvflare--two-ways-to-do-it) ·
[CVAT](#cvat--labelling-images) ·
[MLflow](#mlflow--keeping-track-of-experiments) ·
[bioimage.io](#bioimageio--a-public-library-of-life-science-models)

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

---

# Getting it installed

## Ansible — installs everything, repeatably

**The one-line version:** you write down what a machine should look like, and
Ansible makes it look like that — on five machines at once, over SSH.

Without it, setting up five nodes means SSH-ing into each one and typing the same
forty commands, getting one slightly wrong on node 3, and spending a day finding
out which. Ansible is how you avoid that, and how you rebuild the cluster from
scratch in an hour if something goes badly wrong.

### The one idea that makes it click: describe the end state, not the steps

A shell script says *"run `apt install docker`"*. If Docker is already installed
you get an error, or worse, something half-changes.

Ansible says *"Docker should be present"*. If it already is, Ansible does
nothing and reports `ok`. If it is not, it installs it and reports `changed`.

This property is called **idempotence**, and it is the whole point. You can run
the same playbook ten times safely. The tenth run makes zero changes and takes
thirty seconds. That means when something breaks halfway through, you fix the
cause and just run it again — you never have to work out which steps already
happened.

### Vocabulary

| Term | What it means | Ours |
|---|---|---|
| **Inventory** | The list of machines, and which group each belongs to | `ansible/inventory/hosts.ini` |
| **Group** | A named set of machines, so you can say "all GPU clients" | `nomad_gpu_clients`, `traefik_master`, … |
| **Playbook** | An ordered list of things to make true, aimed at some groups | `ansible/playbook-nomad.yml` |
| **Task** | One thing to make true. "This package is installed." | |
| **Role** | A reusable bundle of tasks. Upstream ships these; we do not write them | `vendor/ai4-ansible/roles/nomad` |
| **Variables** | Values the tasks use, so the same role works for different sites | `ansible/group_vars/all.yml` |
| **Control node** | The machine running Ansible. Needs SSH access to the rest | `caios_server` |

### How our files fit together

```
ansible/inventory/hosts.ini    which machines exist, and what each one is for
ansible/group_vars/all.yml     the settings — versions, names, ports
ansible/playbook-*.yml         the entry points we actually run
vendor/ai4-ansible/roles/      the upstream tasks. Read-only, never edited.
```

The split matters. **The roles are upstream's and we do not touch them**; every
difference between their cluster and ours lives in `group_vars/all.yml`. That is
what lets us take their bug fixes later without untangling a fork.

### Running it

```bash
cd ansible
ansible all -m ping              # can we reach every machine?
ansible-playbook playbook-consul.yml
ansible-playbook playbook-nomad.yml
```

Output is per machine, per task, colour-coded:

- **ok** (green) — already correct, nothing done
- **changed** (yellow) — it did something
- **failed** (red) — stop and read

A second run should be almost entirely green. If it is not, something is
rewriting a file every time, which is worth understanding rather than ignoring.

Useful flags:

```bash
ansible-playbook playbook-nomad.yml --check      # dry run: report, change nothing
ansible-playbook playbook-nomad.yml --limit caios_site_a   # one machine only
ansible-playbook playbook-nomad.yml -v           # more detail (-vvv for lots)
```

`--check` is worth the habit before anything that touches disks.

### The one sharp edge

Ansible does exactly what the role says, on every machine in the group, without
asking. The volume task in the Nomad role reformats a disk — which is correct
for a fresh compute node and catastrophic for a machine holding your work. There
is no confirmation prompt.

That is why `caios_server` is deliberately excluded from the `nomad_volume`
group, and why that group carries a warning. Read what a playbook touches before
running it on something you care about.

---

## Docker and containers — the unit everything ships in

**The one-line version:** a container is an application packaged with everything
it needs to run, so it behaves the same everywhere.

A model needs a specific Python version, specific libraries, specific CUDA
drivers. Installing that on a shared machine, for twenty different models, ends
in a dependency war nobody wins. Instead each model ships as an **image** — a
frozen filesystem containing the app and its dependencies. Running an image gives
you a **container**: an isolated process with its own filesystem view.

Two consequences that show up constantly here:

- **Images are big.** Several GB each, and a GPU model image can exceed 10 GB.
  This is why nodes need a big disk, and why "pre-pull every image before the
  demo" is on the checklist — a cold download mid-demo looks like a broken
  platform.
- **Containers are disposable.** Anything written inside one is gone when it
  stops, unless it was written to a mounted volume. That is a feature (clean
  restarts) and a trap (unsaved notebook work).

Docker is the thing that builds and runs them. Nomad tells Docker what to run.

## Docker Compose — a few containers on one machine

**The one-line version:** one file describing several containers that run
together, started with one command.

Nomad decides *where* things run across a cluster. Compose does not decide
anything — you say "these five containers, on this machine". That is exactly what
we want for the control plane, where Keycloak, Vault, PAPI, the dashboard and
Caddy always run on `caios_server` and never move.

```bash
cd compose
docker compose --env-file ../configs/env/caios.env up -d   # start everything
docker compose logs -f papi                                 # follow one service
docker compose ps                                           # what is running
```

We could have run these as Nomad jobs. We chose not to, because `docker compose
logs papi` is a much shorter path to an answer than chasing an allocation through
the Nomad UI, and none of the five benefit from being scheduled.

---

# The platform

## PAPI — the platform's own API

**The one-line version:** the brain of the platform. It turns "deploy this model"
into a Nomad job, after checking you are allowed.

Written in Python. The dashboard talks *only* to PAPI and never touches Nomad
directly. PAPI holds the Nomad credentials, verifies your login token, applies
quotas, fills in a job template, and submits it.

**Two things worth remembering.** First, it is the only component with Nomad
credentials — which is why a misconfigured PAPI produces a dashboard that renders
perfectly and in which every button fails silently. When the UI looks broken,
check PAPI first. Second, `/docs` on the API gives you a full interactive
interface to every endpoint, which is the fallback if the dashboard ever fails.

## The dashboard — the only screen anyone sees

An Angular web application. Browse a catalogue, configure a deployment, watch it
start, open it. Everything the demo shows happens here.

It supports **tenants** — the same code with different branding, so AI4EOSC,
iMagine, AI4Life and KMD4EOSC are all the same application wearing different
clothes. CAIOS is a fifth. That is why branding is cheap for us: it is a
supported feature, not a hack.

## DEEPaaS — the common shape of every model

**The one-line version:** the agreement that makes every model in the catalogue
work the same way.

Every model in the marketplace exposes the same web API: the same endpoint to
train, the same endpoint to predict, the same way of describing its inputs. That
uniformity is what lets the dashboard show a working "try it" form for a model it
has never seen — it just asks the model to describe itself.

Practically: when you deploy a model and get a URL ending in `/ui`, that is
DEEPaaS rendering a form from the model's own metadata.

## Modules and tools — two kinds of thing you can deploy

The catalogue holds both, and the distinction matters when reading the docs:

- **Module** — a packaged AI model. Image classification, segmentation, and so
  on. What a researcher deploys to *use* a model.
- **Tool** — a service rather than a model: a JupyterLab workspace, the federated
  learning server, CVAT. What a researcher deploys to *do work*.

Six tools exist upstream. We use two for MVP: the development environment and the
federated learning server.

---

# Identity and secrets

## Keycloak — who you are

**The one-line version:** the login system. It proves who you are to everything
else, so nothing else needs to store passwords.

You log in once against Keycloak. It hands back a **token** — a signed piece of
data saying "this is Dana, here is their email, here is what they may do". Your
browser sends that token with every request. PAPI checks the signature and
trusts the contents. PAPI never sees your password.

The token expires (30 minutes here) and is silently renewed. This is standard
OpenID Connect — the same mechanism behind "sign in with Google".

**The detail that bites:** the token records *which* Keycloak issued it, and PAPI
compares that against its own configuration character by character. An `http`
where an `https` was expected, or a trailing slash, and every request returns
401 with no useful explanation.

## Vault — secrets that are not in files

**The one-line version:** an encrypted store for passwords and tokens, where
access is granted per-user rather than per-file.

Config files are the wrong place for secrets: they get committed, copied and
shared. Vault holds them instead, encrypted, and hands them out only to callers
who prove their identity — using the same Keycloak token you already have.

Here it stores per-deployment secrets. The federated learning server uses it to
issue each participating site its own credential, which is what makes "each
hospital has its own revocable key" true rather than decorative.

It is not optional: deploying the FL server makes PAPI call Vault *before* it
contacts Nomad, so a missing Vault fails the headline demo.

## VO — which group you belong to

**Virtual Organisation.** A research project or community. Membership decides
which resources you may use.

In this platform, one VO maps to one Nomad namespace and a set of nodes. Ours is
`vo.caios.ca` → the `caios` namespace. It is the mechanism that would let three
"hospital sites" have genuinely separate access later, in V1.

---

# The AI parts

## Federated learning — the headline

**The one-line version:** train one shared model across several hospitals without
any hospital's data ever leaving its building.

The problem it solves is real and specific. Hospital A cannot legally send
patient scans to Hospital B. But a model trained on one hospital's data alone is
worse than one trained on all of it. Federated learning gets most of the benefit
without moving the data.

How a round works:

```
1. Server sends the current model to every site
2. Each site trains it on its OWN data, locally
3. Each site sends back only the updated weights — never the data
4. Server averages the updates into a new shared model
5. Repeat
```

What travels is the model. What stays is the data. Repeat 5-10 times and the
shared model approaches the quality of one trained centrally.

Two terms that will come up:

- **Non-IID** — the sites' data is not statistically alike. Hospital A sees
  mostly one condition, Hospital B another. Real, and harder to train on, which
  is why we deliberately split our demo data this way.
- **FedAvg / FedProx** — the recipe for combining updates. FedAvg is a plain
  weighted average. FedProx handles non-IID data better by penalising sites that
  drift too far from the shared model.

## Flower and NVFLARE — two ways to do it

Both are frameworks implementing the loop above. **Flower** is lighter and easier
to demonstrate, and is what MVP uses. **NVFLARE** is NVIDIA's, heavier, more
production-oriented, and V1 at the earliest. The story only needs one.

## CVAT — labelling images

Computer Vision Annotation Tool. A web application for drawing boxes and outlines
on images to create training data — the manual work that precedes supervised
learning.

Deferred here for a very concrete reason: it is a single unit of 22 containers
that must all run on one machine and together want about 71 GB of RAM. No node we
have can hold it.

## MLflow — keeping track of experiments

When you train a model fifty times with different settings, MLflow records what
each run used and what it scored, so "which one was best" has an answer. A
stretch goal, not MVP.

## bioimage.io — a public library of life-science models

A public repository of pre-trained models for biological imaging — cell
segmentation, electron microscopy, and so on. The platform includes a loader that
can deploy any of them by ID.

This matters more than it sounds: it is where our neuroscience credibility comes
from. The library includes **connectomics** models — tracing neurons through
electron microscopy volumes — which is genuine neuroscience, available with no
code at all.

---

# If you know Kubernetes

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
