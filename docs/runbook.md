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

**Required, not optional.** An earlier version of this section called it
cosmetic. It is not: without our CA installed, the dashboard loads and then
fails with *"Error calling the API, please try again later"*.

Here is why. Clicking "proceed anyway" grants an exception for **that hostname
only**. The dashboard is served from `dashboard.<...>` but calls the API at
`api.<...>` — a different host — from JavaScript. A background request cannot
show you a warning to click through, so the browser simply blocks it and the
page reports an API error. Login is affected the same way, via `auth.<...>`.

Two ways out. Installing the CA is the real fix; the second is a stopgap.

**What you are copying:** `~/caios-ca.pem` on `caios_server`. This is the
*public* half of our local certificate authority. It is meant to be distributed
and is safe to email, paste or commit anywhere. The private half is
`~/caios-ca.key`, which never leaves that node.

### Easiest: download it from the dashboard

Open this in the browser that has the problem and save the file:

```
https://dashboard.<CTRL_IP>.sslip.io/caios-ca.pem
```

You will have to click past the certificate warning once to reach it, which is
fine — that exception is enough to fetch this one file. Then install it (below)
and the warnings disappear everywhere.

### Stopgap, if you cannot install a CA right now

Visit each hostname once and click through its warning, so the browser holds a
separate exception for each:

```
https://api.<CTRL_IP>.sslip.io/docs
https://auth.<CTRL_IP>.sslip.io/realms/caios
```

Then reload the dashboard. This works, but the exceptions are per-browser and
per-profile and do not survive a fresh machine — so it is not what you want for
a recording, or for a demo on someone else's laptop.

### Other ways to get the file

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

## Running the federated demo

The headline. Roughly ten minutes end to end, of which thirty seconds is actual
training. All of it is clicking except the two commands typed into workspace
terminals.

### Once, before the first run

```bash
# on caios_server — downloads ~900 MB, then never again
demo/.venv/bin/python demo/fl/prepare_data.py
demo/.venv/bin/python demo/fl/partition.py
bash scripts/build-fl-bundles.sh
```

`build-fl-bundles.sh` must be re-run after any change to `client.py`,
`model.py`, or the data — the workspaces fetch the bundle, not the repository.

The Nomad scheduler must be in `spread` mode or two hospitals land on one
machine (D-19). Idempotent, so just run it:

```bash
cd ansible && ansible-playbook playbook-scheduler-config.yml
```

### Bring the demo up

```bash
bash scripts/deploy-fl-demo.sh            # server + three sites, ~3 minutes
bash scripts/deploy-fl-demo.sh --status   # where everything landed
```

On the day this is done by clicking through the dashboard — Tools → federated
server (service **jupyter**, min clients **3**), then three dev environments,
**GPU 0**. The script is for rehearsal and for rebuilding without re-deriving
nine form fields from memory.

**Check `--status` shows the three sites on three different nodes.** That is the
whole claim. If two share a node, the scheduler is still on `binpack`.

### Start the server

Open the federated server's **ide** endpoint, and in a terminal:

```bash
cd /srv/ai4os-federated-server/fedserver && python3 server.py
```

Wait for `Flower ECE: gRPC server running`. It then blocks until all three
clients connect — that is `min_fit_clients: 3` doing its job, not a hang.

### Start the three hospitals

In each site workspace's terminal, with that site's name and the server's
hostname (the `fedserver-...` address from `--status`):

```bash
curl -k -sSL https://dashboard.192.168.104.181.sslip.io/fl/bootstrap.sh | bash -s site_a fedserver-<uuid>.pacs-deployments.192.168.104.105.sslip.io
cd ~/caios-fl && ./run.sh
```

Add `--quiet` to `run.sh`'s command for a clean projector terminal; leave it off
if anything is going wrong, because Flower's per-message logging is the first
useful thing to read.

Training starts the moment the third client connects. Each site prints its own
accuracy on the shared test set as the rounds land.

### Afterwards

```bash
# collect the curve and redraw the chart
demo/.venv/bin/python demo/fl/plot_results.py
bash scripts/deploy-fl-demo.sh --delete    # asks for confirmation
```

### When it goes wrong

**Clients connect but nothing happens.** The server needs all three. Check
`--status` says `running` for every site, and that each client printed
`connecting to ...`. Two connected clients wait forever by design.

**A client fails the TLS handshake.** It is using the wrong CA or none. The
bundle ships `caios-ca.pem` and `client.py` refuses to start without `--ca`.
Upstream's example passes `certifi` here, which only works for a
publicly-trusted certificate; ours is signed by the CAIOS local CA.

**A client connects, then times out saying nothing useful.** Flower version. The
server runs a fork based on 1.16.0 and the bundle pins `flwr==1.16.0`. If
someone has re-run `pip install flwr` in that workspace, it is now on a
different major.

**Accuracy starts high and gets worse, or sits flat near 0.33.** Not the
plumbing. Check that all three sites got *different* bundles — three copies of
the same shard federates perfectly and learns nothing extra.

**A workspace will not start, "Dimension cpu exhausted".** Four FL workloads
need four cores across three 3-core nodes. Delete any leftover deployments:
`bash scripts/deploy-fl-demo.sh --status` lists everything running.

**The bundle download 404s.** `scripts/build-fl-bundles.sh` has not been run, or
Caddy predates the `/fl/` route. Re-run the build, then
`docker compose -f compose/docker-compose.yml --env-file configs/env/caios.env up -d caddy`.

### Rehearsing without the cluster

`bash scripts/fl-rehearse.sh` runs a server and three clients on caios_server
over loopback and checks the result. One minute. It exercises everything except
the network path, so it is the right place to test any change to `client.py` or
`model.py` before rebuilding bundles.

---

## Catalogue and branding

### Is it still CAIOS?

```bash
bash scripts/check-branding.sh
```

Checks what the running dashboard actually serves. Run it after any dashboard
rebuild, any catalogue change, and once immediately before the demo.

It verifies artwork by magic bytes, not status code, and that is deliberate:
nginx answers a missing asset with `index.html` and HTTP 200, so a missing logo
looks fine to anything that only reads status codes. That is exactly how the
dashboard shipped with no logo at all.

### Changing which modules appear in the marketplace

Edit `catalog/keep.txt`, then:

```bash
bash scripts/curate-catalogue.sh            # show what would change
bash scripts/curate-catalogue.sh --apply    # rewrite and push the fork
```

**Then wait up to five minutes.** `raw.githubusercontent.com` serves
`.gitmodules` with `max-age=300`, so the marketplace keeps showing the old list
after the push no matter how many times you restart PAPI. This looks exactly
like a broken cache and is not one. After that, restart PAPI to clear its own
six-hour cache:

```bash
sudo docker restart caios_papi
```

### Changing which bioimage.io models the AI4Life loader offers

Edit `catalog/ai4life-models.txt`, then:

```bash
bash scripts/render-ai4life-models.sh           # validate the IDs
bash scripts/render-ai4life-models.sh --write   # write into caios.env
sudo docker compose -f compose/docker-compose.yml --env-file configs/env/caios.env up -d papi
```

The validation matters. IDs are usually bioimage.io nicknames but not always —
the most downloaded model is shown everywhere as `affable-shark` while the
loader's `id` is the DOI `10.5281/zenodo.5764892`. A wrong ID fails silently,
because PAPI drops ones it does not recognise, so the dropdown just quietly has
one fewer entry.

### Regenerating the logo and favicon

```bash
demo/.venv/bin/python scripts/make-brand-assets.py
bash scripts/build-dashboard.sh
sudo docker compose -f compose/docker-compose.yml --env-file configs/env/caios.env up -d dashboard
```

Colours live in `configs/dashboard/theme/caios/variables.scss` and are repeated
at the top of the script; change both.

---

## Deploying an LLM

**Tools → Deploy your LLM.** Pick a model, fill in an email and a password for
the chat interface, click Deploy. About **two to four minutes** later there is a
chat window at its own subdomain and an OpenAI-compatible API endpoint beside it.

```bash
bash scripts/check-llm-config.sh                       # is it deployable at all
bash scripts/check-llm-deploy.sh                       # the engine, end to end
bash scripts/check-llm-ui.sh                           # the chat interface too
bash scripts/check-llm-ui.sh --keep                    # ...and leave it running
bash scripts/check-llm-catalogue.sh                    # all nine models, ~1 hour
```

All of them deploy and then delete. `--keep` prints the URL and the generated
password and leaves a GPU held until you delete it.

### What to expect, so you can tell slow from broken

| | |
|---|---|
| deploy → chat interface answering | 80–200 s, depending on the model |
| of which model loading | most of it — `torch.compile` and 86 CUDA graphs |
| the default model is the **slowest** | Qwen3.5-2B, ~180 s. LFM2.5-1.2B-Instruct is ~80 s |
| generation | 18–129 tok/s across the catalogue |
| GPU used | ~9 GB of 10.3 GB |

Redeploying the same model saves only about 20 seconds. The weights are cached;
the compilation is not, and the compilation is the expensive part. **So
pre-deploy before the demo** — see `docs/demo-script.md`.

Open WebUI starts only after the model has finished loading, because
`check_vllm_startup` is a non-sidecar `prestart` task. That gives you a useful
shortcut: **if the chat interface answers at all, the model is ready.**

It also gives you a trap. **The dashboard turns the badge green and enables
*Quick access* as soon as vLLM's container starts, roughly three minutes before
the chat interface exists** — so the button lights up, and the link 502s (R-23).
Until Stage L4b lands, treat a green badge as "the model started loading", and
give it the 80–200 s above before clicking. On camera, click it once and let it
work rather than clicking early and recovering.

### Checking it by hand, in a browser

Scripts cannot settle this one. Three faults in this project appeared only when
a human clicked something, and none of them had a failing programmatic check.
`scripts/check-llm-ui.sh` measures the streaming *mechanism* — 6 ms between
chunks — but "does this read like a chat window" is a judgement.

Get one running and leave it there:

```bash
bash scripts/check-llm-ui.sh --keep
```

It prints the URL, the login and a generated password. Then, in a browser on the
VPN:

1. **The certificate warning.** Expected until we have a real domain (V1 item 1).
   Proceed through it, or install the CA — see *Trusting the CAIOS certificate*
   above. Worth knowing which one you will do on camera.
2. **Log in** with the printed credentials. You should land in a chat window,
   not on a "create an account" page. An account-creation page means the
   deployment thinks it has no administrator (R-22).
3. **Check the model dropdown** names the model that was deployed, and nothing
   else. Empty means the UI cannot reach vLLM; see the next section.
4. **Ask it something and watch the reply.** It must appear word by word. All at
   once, after a pause, is a buffered event stream — the symptom below.
5. **Log out and back in.** Sessions survive because `WEBUI_SECRET_KEY` is fixed;
   if you are logged out unexpectedly mid-walkthrough, that is what changed.

If the model is `LFM2.5-1.2B-Thinking` or `DeepSeek-R1-Distill-Qwen-1.5B`, the
reply opens with a collapsible **Thinking** block that fills first — about three
seconds of it before the answer starts. That is correct behaviour, not a fault,
and it is why neither should be the model deployed live in the demo.

### The badge says `running` but *Quick access* gives "Bad Gateway"

**Wait. It is loading, and the dashboard is wrong, not the deployment.**

Until Stage L4b lands, `running` means "the vLLM container started" — not "the
chat interface answers". vLLM then spends one to three minutes loading the model,
and Nomad does not start Open WebUI until it has finished. Traefik publishes the
route immediately, so the URL exists, resolves, and proxies to a port nothing is
listening on. That is a 502 (R-23).

Measured on a real deployment: badge green at **T+1 s**, UI actually answering at
**T+185 s**.

To see where it really is:

```bash
nomad alloc status -namespace caios <alloc> | grep -A4 'Task "open-webui"'
```

`Started At = N/A` means the model is still loading. Once that task has a start
time, give it ten more seconds and reload.

Faster, from the browser: the deployment **detail** page computes
`active_endpoints` and the table does not, so open the deployment rather than
staring at the row.

### "Deploy your LLM" comes back with a red `error` and no message

**Almost certainly the cluster is full, and the deployment is queued rather than
dead.** Do not delete it — it will start by itself when something frees up
(R-24).

Confirm:

```bash
nomad eval list -namespace caios -job <job-id> -verbose   # look for Placement Failures = true
nomad eval status -namespace caios -verbose <eval-id>     # says which dimension ran out
```

`Evaluation "..." waiting for additional capacity to place remainder` means Nomad
is holding it, not refusing it.

**While the federated demo is running, only one LLM fits.** One LLM deployment
needs 2 exclusive CPU cores plus 1300 MHz, 16.3 GB and a GPU. The LLM node holds
the one that is already running; the three hospital nodes have a free GPU each
but only 3 cores, and a workspace is using one. Free a GPU by deleting the other
LLM, or tear down the federated demo first.

If instead the message names a **constraint** rather than a dimension, that is a
different problem — see "A deployment is stuck in pending" above and run
`scripts/verify-cluster.sh`.

### The chat interface loads, but the model dropdown is empty

The one to know. Everything returns HTTP 200 — the login page, the API, the
model list — and the list is empty.

Open WebUI could not reach vLLM. Read the container's stderr, which is the only
place that says so:

```bash
nomad alloc logs -namespace caios <alloc> open-webui | grep -i "ssl\|connect"
```

`CERTIFICATE_VERIFY_FAILED` means PAPI handed the UI the **public** vLLM
hostname instead of the allocation's own address — patch `0010` is missing from
the running image. Rebuild it:

```bash
bash scripts/apply-patches.sh
cd compose && docker compose --env-file ../configs/env/caios.env up -d --build papi
```

### "The email or password provided is incorrect", with the right password

Somebody else got there first. Open WebUI gives the administrator account to
whoever registers first, and if signup was open when a stranger loaded the page,
the deployment is theirs (R-22).

Check whether the door is still open:

```bash
curl -sk https://ui-<uuid>.<domain>/api/config | python3 -m json.tool | grep -i signup
```

`"enable_signup": true` on a running deployment means `WEBUI_ADMIN_EMAIL` and
`WEBUI_ADMIN_PASSWORD` did not reach the container — check the `open-webui`
task's env, and that PAPI was restarted after the last change to
`configs/papi/tools/ai4os-llm/nomad.hcl`, which is bind-mounted and read at
startup.

There is no recovery for an already-claimed deployment. Delete it and deploy
again; it costs two minutes.

### The reply appears all at once instead of word by word

Server-sent events are being buffered somewhere between the browser and the
container — almost always a proxy. `scripts/check-llm-ui.sh` measures the gap
between chunks and will say so; healthy is around 6 ms, a buffered stream is
tens of microseconds. Check Traefik has no `buffering` middleware on that router.

### The deployment's link is dead the moment it appears

Wait ten seconds and reload. PAPI publishes the endpoint before Nomad has placed
the allocation, and until then the hostname still contains `${meta.domain}` and
cannot resolve (R-21). Self-healing, and worth a beat of patience on camera
rather than a fix.

### The answer arrives in a "Thinking" block and the reply looks empty

Two models in the catalogue are reasoning models — `LFM2.5-1.2B-Thinking` and
`DeepSeek-R1-Distill-Qwen-1.5B`. They answer into `reasoning`, not `content`.
Open WebUI renders that as a collapsible section, which is the intended
experience; a script reading `content` gets `None` (R-20).

Measured for one sentence of answer: **2388 characters of thinking, 199 of
answer, 2.8 seconds before the first answer token.** Fine to show, but do not
make one of them the model you deploy live.

### The dropdown offers "arena-model" as well

`ENABLE_EVALUATION_ARENA_MODELS` is not reaching the container. It is Open
WebUI's blind A/B comparison placeholder, and with one model deployed it
compares that model with itself. Harmless, confusing, and off in our template.

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
7. Nomad scheduler left on `binpack` — two hospitals share a node and the
   federated demo quietly stops being a three-site demo.
8. Bundles not rebuilt after editing `client.py` or `model.py` — the workspaces
   fetch the bundle, not the repository, so the change simply is not there.
9. A compose bind mount pointing at `${HOME}` — Docker needs `sudo` here, `sudo`
   makes `HOME=/root`, and a missing mount source becomes an empty *directory*
   rather than an error. PAPI then runs healthily while trusting no CAIOS
   certificate, and every call to our own domains fails with
   `CERTIFICATE_VERIFY_FAILED`.
10. Catalogue edited but the marketplace unchanged — GitHub's raw CDN caches
    `.gitmodules` for five minutes. Not PAPI's fault; wait, then restart PAPI.
11. A chat interface with an empty model dropdown — Open WebUI could not reach
    the vLLM beside it, and reports that as an HTTP 200 with no models. Patch
    `0010` missing from the running PAPI image.
12. Somebody opened a fresh LLM deployment before its owner did, and is now its
    administrator. Should be impossible now (R-22), but the symptom is the
    owner's own password being refused.
