# CAIOS

**Canadian Artificial Intelligence Operating System** — a private AI platform for medical
and neuroscience research, running on a seven-node cluster on Compute Canada's Arbutus
cloud. Researchers deploy a private language model with no code, run a model as a
serverless service with little code, and write their own in JupyterLab notebooks — and
the data stays in Canada.

Built on the open-source [AI4OS](https://docs.ai4os.eu/) stack. We deploy it and brand
it; we do not fork it. Every change to upstream behaviour is either configuration in
`configs/` or a reviewable patch in `patches/`.

The headline capability is **federated learning**: training a model across three
simulated hospital sites where the data never leaves each site.

---

## The cluster

Seven nodes on Arbutus, measured 2026-09-27. Six carry one slice of an NVIDIA H100
(`H100L-1-12C`, 12 GB); four of those run user work.

| Node | vCPU | RAM | GPU | Role |
|---|---|---|---|---|
| `caios_server` | 3 | 34 GB | 1 slice | Control plane: Nomad and Consul servers, Keycloak, Vault, PAPI, dashboard |
| `caios_edge` | 3 | 34 GB | 1 slice | Ingress: Traefik, one subdomain per deployment |
| `caios_site_a`, `_b`, `_c` | 3 each | 34 GB each | 1 slice each | GPU compute — the three "hospital sites" |
| `caios_llm` | 3 | 34 GB | 1 slice | GPU compute — private language models |
| `caios_oscar` | 16 | 58 GB | — | Serverless inference: Kubernetes (K3s), OSCAR, MinIO |

A separate proxy VM holds the public address. How it all fits together, and why:
[docs/infrastructure.md](docs/infrastructure.md).

---

## Start here

| If you want to | Read |
|---|---|
| Understand the seven nodes and how they fit together | [docs/infrastructure.md](docs/infrastructure.md) |
| Know what we are working on now | [docs/demo-plan.md](docs/demo-plan.md) |
| Know why something is the way it is | [docs/decisions.md](docs/decisions.md) |
| Know exactly what is in MVP and what is V1 | [docs/scope.md](docs/scope.md) |
| See what has actually been done so far | [docs/progress.md](docs/progress.md) |
| Understand Nomad, Consul and Traefik | [docs/concepts.md](docs/concepts.md) |
| Operate or debug a running cluster | [docs/runbook.md](docs/runbook.md) |
| Give the cluster SSH access to itself | [docs/ssh-setup.md](docs/ssh-setup.md) |

---

## Getting from here to a running cluster

The sequence that built this cluster, and rebuilds it from scratch.

```bash
# 0. One-time: give caios_server SSH access to the others (docs/ssh-setup.md)
bash scripts/check-ssh.sh

# 1. Pin and fetch upstream (read-only, into vendor/)
bash scripts/clone-vendor.sh

# 2. Apply our patches into build/ — vendor/ is never modified
bash scripts/apply-patches.sh

# 3. Render config templates that need the real hostnames
bash scripts/render-configs.sh

# 4. Wildcard certificate for deployments
bash scripts/make-traefik-certs.sh

# 5. Cluster.  WARNING: playbook-nomad.yml reformats /dev/vdb on the three
#    site nodes, erasing their /mnt. See ansible/inventory/hosts.ini.
cd ansible
ansible-galaxy install grycap.docker
ansible-playbook playbook-control-plane.yml   # Docker on caios_server
ansible-playbook playbook-consul.yml
ansible-playbook playbook-nomad.yml
cd ..

# 6. Confirm the cluster can actually schedule anything
bash scripts/verify-cluster.sh

# 7. Control plane
bash scripts/build-dashboard.sh
cd compose && docker compose --env-file ../configs/env/caios.env up -d
```

---

## Layout

```
ansible/       Inventory, group_vars and playbook entrypoints for the cluster
compose/       Docker Compose control plane: Keycloak, Vault, PAPI, dashboard, Caddy
configs/       Config we own, copied out of upstream and edited: PAPI, dashboard, Keycloak
patches/       Upstream source edits that cannot be configuration, each one explained
nomad-jobs/    Hand-written jobs, starting with the Stage 1 smoke test
catalog/       Curated medical module list
demo/          The federated learning demo, the high-code notebook, module test results
docs/          Infrastructure, plan, decisions, runbook
scripts/       Re-runnable helpers — pinning, patching, rendering, certs, verification
vendor/        Upstream clones. Read-only, gitignored. Never edit anything here.
build/         Patched copies of upstream. Disposable, gitignored.
```

---

## Two things worth knowing before you debug anything

**PAPI is the only component holding Nomad credentials.** If it is misconfigured, the
dashboard still renders perfectly and every button fails quietly. Check PAPI first.

**A Nomad node reporting `ready` tells you almost nothing.** Every deployment is
constrained on `meta.status=ready`, `meta.type=compute`, a matching `meta.namespace` and
`region = "global"`. A node failing any of them looks healthy and silently never receives
work. `scripts/verify-cluster.sh` checks all four in one go, and is the right first move
whenever a job is stuck pending.

---

## Licence

CAIOS is licensed under the **Apache License 2.0** — see [`LICENSE`](LICENSE).

It deploys the [AI4OS](https://github.com/ai4os) stack, which is Apache-2.0 as
well; [`NOTICE`](NOTICE) carries the required attribution and names `patches/` as
this project's statement of changes. `docs/licensing.md` explains what is
inherited, what is required, and what the catalogue's models are licensed under
— which is **not** this licence, and varies per model.
