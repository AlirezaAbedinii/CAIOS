# CAIOS

**Canadian Artificial Intelligence Operating System** — a research platform for medical
and neuroscience AI, running on five GPU nodes on Compute Canada's Arbutus cloud.

Built on the open-source [AI4OS](https://docs.ai4os.eu/) stack. We deploy it and brand
it; we do not fork it. Every change to upstream behaviour is either configuration in
`configs/` or a reviewable patch in `patches/`.

The headline capability is **federated learning**: training a model across three
simulated hospital sites where the data never leaves each site.

---

## Start here

| If you want to | Read |
|---|---|
| Understand the five nodes and how they fit together | [docs/infrastructure.md](docs/infrastructure.md) |
| Know what we are building and in what order | [docs/mvp-plan.md](docs/mvp-plan.md) |
| Know why something is the way it is | [docs/decisions.md](docs/decisions.md) |
| Brief the supervisor, or answer their questions | [docs/questions-for-supervisor.md](docs/questions-for-supervisor.md) |
| Work on this as an agent or a new engineer | [CLAUDE.md](CLAUDE.md) |

---

## Getting from here to a running cluster

Everything below the first step is written and committed. The first step is the only
thing blocking.

```bash
# 0. Fill in the five node IPs and the two floating IPs
cp configs/env/caios.env.template configs/env/caios.env
$EDITOR configs/env/caios.env ansible/inventory/hosts.ini

# 1. Pin and fetch upstream (read-only, into vendor/)
bash scripts/clone-vendor.sh

# 2. Apply our patches into build/ — vendor/ is never modified
bash scripts/apply-patches.sh

# 3. Render config templates that need the real hostnames
bash scripts/render-configs.sh

# 4. Wildcard certificate for deployments
bash scripts/make-traefik-certs.sh

# 5. Cluster
cd ansible
ansible-galaxy install grycap.docker
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
patches/       The four upstream source edits that cannot be configuration
nomad-jobs/    Hand-written jobs, starting with the Stage 1 smoke test
catalog/       Curated medical module list
demo/          Federated learning scripts, dataset partitioning, comparison chart
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
