# Runbook

Operational notes. Kept current as we go — this is what saves us on demo day.

**Status: Stage 0 complete (local scaffold). Nothing installed on the nodes yet.**
Sections below marked *(not yet exercised)* are written from the source but have
not been run against real hardware. Correct them the moment reality disagrees.

---

## Addresses

Everything derives from the two IPs in `configs/env/caios.env`.

| What | Where |
|---|---|
| Dashboard | `https://dashboard.192.168.104.181.sslip.io` |
| API (PAPI) | `https://api.192.168.104.181.sslip.io` — Swagger at `/docs` |
| Login (Keycloak) | `https://auth.192.168.104.181.sslip.io` |
| Vault | `https://vault.192.168.104.181.sslip.io` |
| Deployments | `https://<service>-<uuid>.pacs-deployments.192.168.104.105.sslip.io` |
| Nomad UI | `https://192.168.104.181:4646` (subnet only) |

---

## Everyday commands

```bash
# We work from caios_server (192.168.104.181). Others: ssh 192.168.104.105 etc.
bash scripts/verify-cluster.sh      # first move when anything is stuck
cd compose && docker compose --env-file ../configs/env/caios.env ps
docker compose logs -f papi         # PAPI is the usual culprit
```

Redeploy after a config change:

```bash
bash scripts/render-configs.sh
cd compose && docker compose --env-file ../configs/env/caios.env up -d --force-recreate papi
```

---

## Triage

### A deployment is stuck in "pending"

Almost always node metadata. Run `scripts/verify-cluster.sh` first — it checks
all four conditions and names the failing one.

Every PAPI deployment requires **all** of:

| Condition | Set by | Common failure |
|---|---|---|
| `meta.status = ready` | `ai4-nomad_tests` | Ansible ships `test`. If the test suite has not run, nothing deploys. |
| `meta.type = compute` | Ansible, from inventory group | The Traefik node is `traefik` and can never run user work. That is intended. |
| `meta.namespace` matches | Inventory `nomad_namespaces=` | Typo here and the node looks perfectly healthy forever. |
| `region = "global"` | `group_vars/all.yml` | Upstream default `ai4os` makes every PAPI job unschedulable. |

Then check placement directly:

```bash
nomad job status -namespace caios <job>
nomad eval status <eval-id>     # ConstraintFiltered names the constraint that failed
```

### The dashboard renders but every button fails

PAPI. It holds the only Nomad credentials, so a misconfigured PAPI produces a
perfect-looking UI in which nothing works.

```bash
docker compose logs --tail=100 papi
curl -sk https://api.192.168.104.181.sslip.io/v1/catalog/modules | head -c 300
```

If PAPI is not running at all, check `IS_PROD` first. Its Dockerfile sets
`IS_PROD=True`; our compose overrides it to `false`. If that override is lost,
PAPI exits complaining about tokens for services we do not run.

### Every request returns 401

Keycloak and PAPI disagree about the realm URL. The issuer is compared literally
— scheme, host and trailing slash all count.

```bash
bash scripts/get-token.sh researcher '<password>'   # decodes and reports claims
```

PAPI requires `sub`, `iss`, `name`, `email`, an `aud` of `account`, and a realm
role matching `access:<vo>:<level>` at `ap-u` or above. `get-token.sh` names
whichever is missing.

### Deploying the federated server fails, and the error mentions nothing useful

Vault. PAPI creates a secret and a Vault token *before* it contacts Nomad, so
this fails with no Nomad involvement at all.

```bash
docker compose logs --tail=50 papi | grep -i vault
docker exec caios_vault vault status
bash scripts/vault-bootstrap.sh       # idempotent; safe to re-run
```

### A deployment is running but unreachable

Consul or Traefik, not Nomad.

```bash
nomad job status -namespace caios <job>      # confirm it really is running
consul catalog services                       # is the service registered?
nomad alloc logs -job traefik-caios           # is Traefik healthy?
```

Also check the certificate actually reached the node:

```bash
ssh caios_edge 'ls -l /etc/nomad.d/traefik-certs/'
```

Both `domain.key` and `domain.pem` must be there. The Ansible role *warns*
rather than fails if the bundle is missing, so Traefik starts happily and serves
no certificate.

### Browser warns the certificate is not trusted

Expected on MVP — self-signed wildcard (D-12). Click through once. Fixed in V1
by a real domain.

---

## Before the demo *(not yet exercised)*

- [ ] Pre-pull every image onto every node. A cold multi-GB pull mid-demo is the
      most reliable way to make a working platform look broken.
- [ ] Pre-create accounts, datasets, and one **completed** federated run to cut
      to if a live round hangs.
- [ ] Run the whole demo twice, the second time from a clean state. That is
      where the things that only worked because of something you did on day
      three show up.
- [ ] Record it. If the network fails on the day, there is still a demo.
- [ ] Snapshot all VMs.

---

## Things that will bite, in the order they usually do

1. `meta.status` still `test` — nothing schedules, and the cluster looks fine.
2. `nomad_region` left at `ai4os` — same symptom, different cause.
3. Certificate bundle misnamed — Traefik serves no certificate, silently.
4. `IS_PROD` inherited as `True` — PAPI will not start.
5. Keycloak issuer mismatch — universal 401.
6. Three GPU deployments under one account — rejected on the third, by design
   (2-GPU cap). Run FL clients CPU-only.
