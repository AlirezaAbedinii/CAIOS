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

Expected until you install our CA — see "Trusting the CAIOS certificate on your
own machine" below. Clicking through works fine in the meantime. A real domain
in V1 removes the step entirely.

---

## Rebuilding the dashboard

The dashboard is the one service built from source rather than pulled, so it is
the one with a real build step.

```bash
bash scripts/build-dashboard.sh
cd compose && docker compose --env-file ../configs/env/caios.env up -d dashboard
bash ../scripts/check-dashboard.sh
```

The build takes several minutes — it is a full Angular compile — and needs
network access for `npm ci`.

### What is baked in versus injected at start

This distinction decides whether you need a rebuild or just a restart.

| Changes | Needs |
|---|---|
| Theme colours, logo, tenant JSON, page title | **Rebuild** |
| API address, login server, client ID | **Restart only** |

The four runtime values are written into `config.json` by the image's own
entrypoint on every start. So moving the API to a new address is a restart, not
a rebuild.

### If the page loads but nothing works

Check `config.json` first — it is served at
`/assets/config/config.json` and shows exactly what the running page believes:

```bash
curl -s https://dashboard.<CTRL_IP>.sslip.io/assets/config/config.json | python3 -m json.tool
```

`apiURL` and `issuer` are the two that matter. A wrong `issuer` produces a login
loop; a wrong `apiURL` produces a page that renders perfectly with every action
failing.

### If login redirects and then fails

The redirect URI must be registered in Keycloak. Ours are scoped to the real
dashboard origin deliberately — a wildcard on a public client is how tokens get
stolen. If the dashboard address changes, the realm has to change with it:

```bash
bash scripts/render-configs.sh    # regenerates from caios.env
```

Keycloak only imports a realm on first start, so an existing deployment needs
the change applying through the admin console, or the `keycloak_db` volume
removed to re-import from scratch.

---

## Trusting the CAIOS certificate on your own machine

Optional. Without it everything works, you just click past a browser warning on
every CAIOS page. With it, no warnings anywhere — worth doing before recording
anything.

**What you are copying:** `~/caios-ca.pem` on `caios_server`. This is the
*public* half of our local certificate authority. It is meant to be distributed
and is safe to email, paste or commit anywhere. The private half is
`~/caios-ca.key`, which never leaves that node.

### Where to run the copy

The file already exists on `caios_server`. There is nothing to copy *there* —
run these **on your own laptop**, after connecting to the VPN.

If you reach the cluster directly once on the VPN:

```bash
scp ubuntu@192.168.104.181:~/caios-ca.pem .
```

If you go through a jumpserver, hop through it:

```bash
scp -J <user>@<jumpserver> ubuntu@192.168.104.181:~/caios-ca.pem .
```

### If scp is awkward, just copy the text

A CA certificate is a small block of base64. This is often the fastest route,
and it avoids working out the jump path entirely. On `caios_server`:

```bash
cat ~/caios-ca.pem
```

Select the output, including both `-----BEGIN CERTIFICATE-----` and
`-----END CERTIFICATE-----` lines, and save it on your laptop as
`caios-ca.pem`.

### Then install it

| Where | How |
|---|---|
| **macOS** | Double-click the file → Keychain Access → find "CAIOS Local CA" → Get Info → Trust → "When using this certificate: Always Trust" |
| **Firefox** | Settings → Privacy & Security → Certificates → View Certificates → Authorities → Import → tick "Trust this CA to identify websites" |
| **Chrome / Edge (macOS)** | Uses the system keychain — do the macOS step above |
| **Chrome / Edge (Windows)** | Double-click → Install Certificate → Local Machine → "Trusted Root Certification Authorities" |
| **Linux (system-wide)** | `sudo cp caios-ca.pem /usr/local/share/ca-certificates/caios-ca.crt && sudo update-ca-certificates` |

Firefox is worth calling out: it keeps its **own** trust store and ignores the
operating system's, so installing system-wide is not enough for it.

### Check it worked

```bash
curl -sS -o /dev/null -w "HTTP %{http_code}  TLS verify %{ssl_verify_result}\n" https://smoke.pacs-deployments.192.168.104.105.sslip.io
```

`TLS verify 0` means the chain validated. (That URL only exists while a test
deployment is running — any CAIOS deployment hostname works.)

### Already done for you

`caios_server` itself trusts the CA — `scripts/make-traefik-certs.sh` installed
it into the system store. Python tooling gets it through `REQUESTS_CA_BUNDLE`,
which `scripts/run-cluster-tests.sh` sets. Nothing on the cluster needs this
step; it is purely for browsers on your own machine.

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
