# OSCAR serverless inference — the plan

**Stage 7 of the CAIOS build.** The MVP works, federated learning works, and a
private language model works. This adds the one remaining dashboard section
that is wired but dead: **Inference**.

Read alongside:

| Document | Answers |
|---|---|
| `docs/feature-coverage.md` §11 | Why this was cut in the first place, and at what price |
| `docs/infrastructure.md` | What hardware exists and what each node is for |
| `docs/decisions.md` | D-09 (cut), D-15 (storage is Nextcloud, not MinIO) |

**Status: O0 to O4 complete — the O4 gate passed 2026-08-26.** A file dropped
in MinIO triggers a Kubernetes Job that runs a catalogue model and writes a
prediction, with the pod scaled to zero either side. O5 (the browser check) is
next.

The governing constraint: **OSCAR is additive and must stay additive.** Nothing
in this plan may put the marketplace, the deployment table, the federated
learning demo or the LLM tool at risk. Where a choice is between "more OSCAR"
and "cannot break what works", it goes to the latter every time.

---

## What is already here, and what is broken

Established by reading the source and probing the live cluster on 2026-08-25.

### 1. PAPI's OSCAR API is live, and returns 500

The inference router is mounted **unconditionally** in
`ai4papi/routers/v1/__init__.py` — there is no configuration gate. Four
endpoints are advertised in the running OpenAPI schema:

```
/v1/inference/oscar/cluster            HTTP 500
/v1/inference/oscar/services           HTTP 500
/v1/inference/oscar/conf
/v1/inference/oscar/services/{name}
```

They fail because `MAIN_CONF["oscar"]` was removed from `main.yaml` under D-09,
and the code indexes it directly.

### 2. The dashboard's Inference page ships in the running build

`src/app/modules/inference/` is complete upstream — routing, list component,
detail component, service. And the menu entry is **hardcoded in the sidenav
component**, not gated by tenant configuration:

```js
{name:"SIDENAV.INFERENCE",url:"/tasks/inference",isRestricted:true,...}
```

Found in `main-5MX6OJOI.js`, the bundle this cluster serves today. So a
logged-in researcher can click through to a page whose only backend call is a
500. Nobody had noticed because nobody had clicked it — which is precisely what
Stage F0 exists to catch.

### 3. The integration is thinner than the original estimate assumed

```python
client_options = {
    "cluster_id": ...["cluster_id"],
    "endpoint":   ...["endpoint"],
    "oidc_token": token,      # the user's own Keycloak token, passed through
    "ssl": "true",
}
```

Pure configuration, read from `main.yaml`. **No PAPI patch is required to
connect a cluster** — unlike the Keycloak URL (`0001`) and the Vault address
(`0002`), upstream already made this configurable. And authentication is a
token pass-through, so "connect authentication to our login system" — costed at
one day in `feature-coverage.md` — reduces to pointing OSCAR's OIDC issuer at
our realm.

---

## Two corrections to our own cost analysis

`docs/feature-coverage.md` §11 states OSCAR "requires Kubernetes plus Knative,
MinIO, CLUES and the OSCAR manager", and costs it at 5–8 days. Checked against
OSCAR's own Helm chart:

| What we wrote | What the chart says |
|---|---|
| Knative required | `serverlessBackend: ""` — **Knative serves *synchronous* invocations only.** Asynchronous, MinIO-triggered execution runs on plain Kubernetes Jobs |
| EGI Check-in authentication | `oidc.enable`, `oidc.issuer`, `oidc.subject`, `oidc.groups` — the issuer is a plain string, so a self-hosted Keycloak works |
| A heavy manager | `resources.requests`: **512Mi memory, 500m CPU** |
| A Kubernetes cluster | K3s is a documented, supported deployment target |

MinIO stays mandatory: the FDL template PAPI renders hardcodes
`storage_provider: minio.default` for both input and output.

**Revised: 3–4 days asynchronous-only, plus 1–2 if synchronous invocation is
wanted.** The original 5–8 was not wrong for a full Knative build on dedicated
hardware; it was answering a bigger question than we need to ask.

> **Note for the roadmap slide.** Asynchronous-only still tells the whole
> serverless story — scale to zero, event-driven execution, a bucket drop that
> starts a job. What it does not give is a low-latency HTTP endpoint, and we
> already have that: every deployed module exposes a DEEPaaS REST API. Beat 6
> of the demo is exactly that.

---

## The hardware question

Measured 2026-08-25:

```
RAM free    gpu-0/1/2  32G of 34G     gpu-3  29G of 34G     edge  33G of 34G
Disk        gpu-0/1/2  41G of 125G    gpu-3  97G of 125G    edge  6G of 20G
CPU         3 vCPU everywhere — and Nomad reserves whole cores
```

RAM is plentiful. **CPU is the binding constraint**, as it has been since
Stage 3. `caios_edge` runs only the Traefik job and is otherwise idle.

Neither the OpenStack CLI nor any credentials exist on `caios_server`, so the
project's VM quota could not be checked from here. That is Stage O1's first
task.

---

## Stage O0 — Stop the Inference page 500ing · half a day · **done**

**This stage is worth doing whether or not OSCAR is ever deployed**, which is
why it goes first and why it carries no hardware dependency.

### Work

Patch `0012-oscar-optional.patch`. Two helpers, `oscar_cluster_conf()` and
`require_oscar()`, with every direct index routed through the latter.

| Endpoint | Before | After |
|---|---|---|
| `GET /services` | 500 | `[]` — the page renders its empty state |
| `GET /cluster`, `GET /services/{name}` | 500 | 501 with a sentence |
| `POST` / `PUT` / `DELETE /services` | 500 | 501 with a sentence |

The listing degrades to an empty list because that is the call the page makes
when it opens. The write paths get 501, because silently accepting a create
would be worse than refusing one. This is D-39 applied a third time.

### Tests

`tests/test_oscar_optional.py` — 10 cases, offline, the helpers lifted from the
patched source with `ast` in the manner of `test_deployment_status.py`.

### Gate

Passed 2026-08-25. All 12 `ai4-papi` patches apply in sequence to the pinned
upstream; the new suite is green.

### What it found

**Guarding the client path alone was not enough.** `create_service` calls
`make_service_definition(user_conf, vo)` **before** it builds a client, and
that function reads the cluster id directly. The first version of this patch
guarded `get_client_from_auth`, passed every unit test, and left
`POST /services` raising `KeyError` exactly as before.

The suite caught it because one test asserted the *absence* of the upstream
indexing expression rather than the presence of the new guard. Asserting what
must be gone is worth more than asserting what was added — the same lesson the
F1 rollback produced from the other direction, where a derivation checked
against itself proved only self-consistency.

Four call sites, not one. Recorded as D-50.

---

## Stage O1 — The node · **measured 2026-08-25**

`192.168.104.69`, hostname `ai4eosc-7`, provided for this purpose. Measured
rather than assumed, per Stage L0's precedent:

| | ai4eosc-7 | every other CAIOS node |
|---|---|---|
| vCPU | **16** | 3 |
| RAM | **58 GB** | 34 GB |
| `/mnt` | **560 GB** ext4, `lost+found` only | 125 GB |
| root | 20 GB, 18 GB free | 20 GB |
| GPU | **none** | 1× `NVIDIA H100L-1-12C` |
| OS | Ubuntu 22.04.5 | Ubuntu 22.04.5 |

Nothing is installed: no Docker, no containerd, no k3s, no Nomad, no Consul.

### What this changes

**CPU stops being the binding constraint.** Every sizing decision in this
project so far has been shaped by 3-vCPU nodes — the dev-env capped at 2 CPUs,
the mail sidecar patched out to reclaim a core, FL clients forced CPU-only. R-33
is therefore closed before it opened: K3s, MinIO and the OSCAR manager together
want roughly 1.5 cores out of 16.

**No GPU, and that is fine.** OSCAR services run DEEPaaS module images, which
infer on CPU. R-34 stands only if GPU-backed serverless is later wanted, and it
would then need a device plugin on this node — remembering R-18, where the
plugin was silently broken cluster-wide and `nvidia-smi` did not reveal it.

**It is not the CVAT host either.** 58 GB against the ~71 GB CVAT wants in one
place. Closer than anything before it, but still short, so D-16 stands. Worth
re-measuring CVAT's real requirement rather than its sum-of-requests if
annotation ever comes back.

### The 20 GB root disk is the constraint that shapes O2

18 GB free on `/`, against a 560 GB volume already mounted at `/mnt`.
**Everything K3s writes must go to `/mnt`.**

This is the same trap Stage 3 hit and documented: Docker's `data-root` was set,
images went to containerd's root anyway, and the system disk filled to 84% while
the data volume sat at 1%. K3s embeds containerd, so the equivalent mistake is
available here.

| What | Default location | Must become |
|---|---|---|
| K3s state, images, embedded DB | `/var/lib/rancher/k3s` | `/mnt/k3s` via `--data-dir` |
| Local-path PVCs (MinIO's data) | `<data-dir>/storage` | follows `--data-dir`, **verify** |
| Kubelet root | under `<data-dir>` | follows `--data-dir`, **verify** |

`--data-dir` is believed to move all three. **Verify with `du` after install
rather than trusting it** — that is exactly the assumption that cost a day in
Stage 3, and the check is one command.

### No reformat, unlike the site nodes

`/mnt` is already ext4, already mounted, and holds only `lost+found`. It needs
**no repartitioning and no XFS**: this node is not a Nomad client, so there are
no `storage-opt` quotas to enforce, and `ai4-nomad_tests` — which asserts the
literal path `/dev/vdb1` — never runs against it. Leave the disk alone.

That also means Stage O1 carries none of the destructive warnings that
`playbook-nomad.yml` and `playbook-prepare-volumes.yml` do. Nothing here erases
anything.

### This node must never join Nomad

R-32. K3s and Nomad both manage containerd and cgroups, and a node running both
half-works in ways that are miserable to diagnose. `ai4eosc-7` stays out of
`ansible/inventory/hosts.ini` entirely.

### Outstanding for O1

- [ ] **Install the cluster public key.** `~/.ssh/caios_cluster.pub` from
      `caios_server` is not in this node's `authorized_keys`, so automation
      cannot reach it unattended — only personal keys can. Same procedure as
      `docs/ssh-setup.md`.
- [ ] **Confirm the security groups** permit `caios_server` → this node on the
      port OSCAR will serve. TCP 22 already connects between them, so the
      subnet is not blanket-filtered.

## Stage O2 — K3s, MinIO and OSCAR · 1–1.5 days · the substantial stage

### Work

```
k3s (single node, --disable traefik)
  └─ MinIO           object store, input/output buckets
  └─ OSCAR manager   oidc.enable=true
  │                  oidc.issuer=https://auth.<CTRL_IP>.sslip.io/realms/caios
  └─ serverlessBackend: ""      Kubernetes Jobs — no Knative in this stage
```

**`--disable traefik` is not optional.** K3s ships Traefik and binds 80/443 by
default. On any node in this cluster that is a collision; on `caios_edge` it
would take the platform's ingress down.

### The one that will bite

**OSCAR must trust the CAIOS CA.** It fetches Keycloak's JWKS over HTTPS to
validate tokens, and it has no reason to trust a private authority.

This is the **fifth** occurrence of this exact pattern in this project:

| | |
|---|---|
| Stage 2 | Vault could not fetch the realm's discovery document |
| Stage 4 | The FL client's gRPC handshake against Traefik |
| Stage L4 | Open WebUI's model list, silently empty behind an HTTP 200 |
| Stage L6 | The notebook beat — `CERTIFICATE_VERIFY_FAILED` (D-43) |
| **O2** | **OSCAR's OIDC discovery** |

Budget for it up front rather than discovering it: mount `caios-ca.pem` into
the OSCAR manager pod. D-43 applies — distribute the CA, do not switch
verification off.

### Tests

Extend `tests/test_oscar_optional.py` with the configured-cluster path, and add
a `scripts/check-oscar.sh` smoke test in the manner of `check-llm-deploy.sh`.

### Gate

`curl` OSCAR's `/system/info` with a real CAIOS researcher token → HTTP 200.
Not a basic-auth token; the OIDC path is the whole integration.

---

### What the dashboard does with MinIO — settled by reading it

`inference-detail.component.html` renders the bucket, URL, access key and
secret as a **credentials panel the user copies from**. It does not upload.

Two consequences:

- **The page renders without MinIO being reachable from the browser.** But the
  user cannot actually do anything until MinIO is reachable from wherever they
  push files — their laptop on the VPN, or a dev-env workspace. MinIO needs its
  own hostname and a certificate from the CAIOS CA, on the subnet.
- **The secret key is displayed in the page.** That is R-09's shape — a
  credential in the clear in a place nobody thought of as a secret store.
  Worth a look before this is on a projector.

Proposed names, both served from the K3s ingress on `.69` and signed by the
CAIOS CA, so PAPI (which already trusts that CA) reaches them directly with no
hairpin through Caddy on `.181`:

```
oscar.192.168.104.69.sslip.io
minio.192.168.104.69.sslip.io
```

### What O2 found — run 2026-08-26

Installed and verified:

```
k3s v1.36.3+k3s1   --data-dir /mnt/k3s --disable traefik
ingress-nginx      LoadBalancer, EXTERNAL-IP 192.168.104.69
MinIO              https://minio.192.168.104.69.sslip.io   HTTP 200  TLSverify 0
OSCAR 4.1.2        https://oscar.192.168.104.69.sslip.io   HTTP 200  TLSverify 0
                   serverless_backend: none (async only)
                   minio verify: True
/system/services   200  []
```

**`--data-dir` works, but not for everything, and only measurement shows it.**
Images land in `/mnt/k3s/agent/containerd`; about **250 MB of self-extracted
static binaries stay on `/var/lib/rancher/k3s/data` regardless**. That is
fixed-size and does not grow, so it is fine on an 18 GB root — but it is not
what the flag appears to promise, and the install log says
`Preparing data dir /var/lib/rancher/k3s/data/...` which reads alarming.
Root sat at 10% afterwards. D-53 holds, with that caveat recorded.

**R-30 arrived exactly as predicted, and worse than predicted.** The OSCAR pod
exited with code **2** immediately after printing `OIDC authentication
enabled: true` — and printed nothing else. No stack trace, no TLS error, no
mention of a certificate. Eleven lines of log, then gone, in a CrashLoopBackOff
that looked like a configuration error rather than a trust problem.

The cause was the CAIOS CA: OSCAR verifies MinIO over HTTPS at startup and its
container has no reason to trust our authority. Fixed by mounting the CA and
setting `SSL_CERT_DIR=/etc/ssl/certs:/caios-ca` — Go reads every file in every
listed directory, so public CAs keep working and ours is added. **Verification
stays on** (D-43): `/system/config` reports `minio verify: True`.

Two false leads cost time and are worth recording, because both looked
authoritative:

- **Three `nodes is forbidden` RBAC errors on every start.** Real, and worth
  fixing — the chart does not grant its service account node-list at cluster
  scope — but not the cause. The manager logs `INFO: InterLink Unavailable`
  and carries on.
- **A `--set minIO.TLSVerify=false` test that never ran.** The helm upgrade
  failed behind `|| true` and `>/dev/null`, the pod hash did not change, and
  the result read as "TLS is not the problem". It was. Checking the pod's
  actual env — `MINIO_TLS_VERIFY=true` — is what turned it around.
  **A test whose failure is invisible is worse than no test**, which is the
  same lesson F1 produced from the other direction.

### STAGE O2 GATE PASSED — 2026-08-26

```
GET /system/info      200   with a CAIOS researcher token
GET /system/config    200
GET /system/services  200   []
no token              401
garbage token         400
```

`check-identity.sh` and `check-dashboard.sh` both still pass afterwards, which
matters because this stage edited the realm the whole platform authenticates
against.

**Four failures stood between "installed" and "gate passed", and only the first
was predicted.**

**1. The claim OSCAR reads is chosen by the issuer's *name*.** Not by config —
by a substring match on the issuer URL:

| Issuer contains | Claim read |
|---|---|
| `/realms/egi` | `entitlements` |
| `/realms/ai4eosc` | realm roles |
| anything else | **`group_membership`** |

Ours is `/realms/caios`, so OSCAR reads `group_membership`. Setting
`OIDC_GROUPS` to the realm role our tokens already carry was tried first and
refused — which ruled the theory out in two minutes rather than by argument.

A near-miss worth recording: had the realm been named `ai4eosc`, realm roles
would have worked untouched. The realm's *name* is load-bearing in a way
nothing documents.

The fix is additive — a `oscar-users` group, a Group Membership mapper emitting
`group_membership` with `full.path` off, and the four demo users added. No
existing claim changed; the token still carries the same roles, issuer and
audience it did before. A full realm export was taken first, to
`~/keycloak-backups/`.

**2, 3 and 4 were one fault wearing three faces.** With authorisation fixed the
401 became a 500, then a different 500, then a third:

```
401  ->  500 namespaces "oscar-svc" not found
     ->  500 error retrieving base pvc oscar-svc/oscar-pvc
     ->  500 ProvisioningFailed: NodePath only supports ReadWriteOnce
```

All three trace back to the helm install reporting `5 errors occurred` and a
release left in `failed` state — while the pod ran and answered `/health`, so
it read as noise. It was not. The chart's `PersistentVolumeClaim` and
`populate-volume-job` had failed to create because `oscar-svc` did not exist,
and nothing surfaced that until a *user* token asked OSCAR to provision
per-user storage. Basic auth never touches that path, which is exactly why
`/system/info` answered 200 for the admin throughout.

**The last one is a real single-node constraint, not a mistake.** The chart
asks for `ReadWriteMany`; K3s' `local-path` provisioner supports only
`ReadWriteOnce`. OSCAR assumes a multi-node cluster with shared storage. On one
node RWO is equivalent and correct — but **a second OSCAR node would need real
RWX storage** (NFS, Longhorn) before it could join. Recorded as R-38.

**What this stage is really about.** Every one of the four failures was
diagnosed by reading what the system actually reported — the pod's real env
(`MINIO_TLS_VERIFY=true` when a test claimed otherwise), the PVC's events, the
difference between the basic-auth and OIDC paths. None of it was guessable, and
the helm `failed` status was pointing at it the whole time.


## Stage O3 — Wire PAPI · half a day · **configuration only**

### Work

```yaml
# configs/papi/main.yaml
oscar:
  clusters:
    vo.caios.ca:
      endpoint: https://oscar.${CAIOS_CTRL_IP}.sslip.io
      cluster_id: oscar-caios-cluster
```

Plus a Caddy vhost for the OSCAR endpoint, and that hostname added to the
control-plane certificate's SANs.

**No patch.** PAPI already trusts the CAIOS CA — `compose/docker-compose.yml`
mounts it and runs `update-ca-certificates`, and `REQUESTS_CA_BUNDLE` is set —
so `oscar_python`'s `ssl: "true"` should validate without further work. If it
does not, that is R-30 and the fix is in the container, not in the source.

### Gate

`/v1/inference/oscar/cluster?vo=vo.caios.ca` returns 200 — the endpoint that
returns 500 today and 501 after O0.

---

### STAGE O3 GATE PASSED — 2026-08-26

```
GET /v1/inference/oscar/cluster?vo=vo.caios.ca    200
GET /v1/inference/oscar/services?vo=vo.caios.ca   200  []
GET /v1/inference/oscar/conf?item_name=...        200  {general, hardware}
no token                                          401
```

**Those endpoints had returned HTTP 500 for the entire life of this platform.**

The change was three additive edits and a rebuild:

| File | Change |
|---|---|
| `configs/papi/main.yaml` | the `oscar.clusters.vo.caios.ca` block, replacing the `# oscar: removed` comment |
| `compose/docker-compose.yml` | `CAIOS_OSCAR_ENDPOINT` passed to the papi service |
| `configs/env/caios.env` | the endpoint value |

Plus patch `0012` shipped in the same rebuild, so the *absence* of that block
now degrades rather than erroring — the two halves of the work meeting.

**No PAPI patch was needed to connect the cluster**, exactly as O0's reading
predicted: unlike the Keycloak URL (`0001`) and the Vault address (`0002`),
upstream already made the OSCAR endpoint configuration. And no network or trust
work was needed either — PAPI's container already reached OSCAR at
`TLSverify 0`, because compose mounts the CAIOS CA for Keycloak's sake and the
same trust covers this.

Regression after the rebuild: 19 dashboard checks passing, no failures, all
five running deployments still listed.

### Stage O3 is where the dashboard becomes usable

Nothing was done to the dashboard, and nothing needed to be. Its `inference`
module has shipped in every build since Stage 3; only its backend was missing.

## Stage O4 — One service, end to end · half a day

### Work

Create an OSCAR service from a curated catalogue module —
`ai4os-image-classification-tf` is the safe pick, since it is already in
`catalog/keep.txt` and known to deploy — push a file to its MinIO input bucket,
and confirm a Kubernetes Job runs and output appears.

### Gate

An inference result produced from a file drop, with the pod scaled to zero
before and after. **Scale-to-zero is the entire value proposition**; a service
that idles at one replica has not demonstrated it.

---

### STAGE O4 GATE PASSED — 2026-08-26

```
upload inputs/input.json  ->  Job created automatically
                          ->  Complete in ~14s
                          ->  outputs/tmp-file-qlaoi.json

{"status":"OK",
 "labels":["dishwasher","cleaver","milk_can","matchstick","spotlight"],
 "probabilities":[0.714, 0.020, 0.019, 0.019, 0.016]}
```

Nothing runs before or after. Scale-to-zero, demonstrated rather than claimed.

The labels are nonsense because the test input was a synthetic gradient PNG fed
to an ImageNet classifier. The pipeline is what this gate is about.

**Also live:** the MinIO browser console, so uploads do not require a CLI.

```
oscar.192.168.104.69.sslip.io           TLSverify 0
minio.192.168.104.69.sslip.io           TLSverify 0   S3 API
minio-console.192.168.104.69.sslip.io   TLSverify 0   browser UI
```

### Four faults, and how each was found

**1. The 500 was in the response body all along.** The source returns
`c.String(http.StatusInternalServerError, err.Error())` — the reason travels in
the body, and nothing logs it. Every attempt to read it had failed because the
OSCAR pod has no `curl` and MinIO logs only the status code. Replaying the
webhook by hand produced it in one line:

```
error ensuring credentials for user minio: secrets "minio" not found
```

Replaying required MinIO's own bearer token, which `mc admin config get`
redacts and `mc admin config export` prints.

**2. It was the same install failure a third time.** The chart's `Secret: minio`
targets `oscar-svc` and had died with the PVC and the populate Job when that
namespace did not exist. Three separate symptoms, one cause, and the helm
release had been sitting in `failed` state pointing at it the whole time.

**3. Jobs were being created in a namespace nobody was watching.** OSCAR
creates them per-user, in `oscar-svc-<first 8 of the OIDC sub>` — not in
`oscar-svc`. Two failed Jobs had been sitting there through several rounds of
"no job was created".

**4. R-30, for the sixth time.** With the Job finally running, the container
died on:

```
botocore.exceptions.SSLError: SSL validation failed for
https://minio.192.168.104.69.sslip.io/... certificate verify failed
```

The FaaS supervisor inside the job container does not trust the CAIOS CA, and
there is no supported way to mount it there. **D-36 already decided this case** —
a task reaching a service in its own cluster addresses it directly over plain
HTTP, removing TLS from a path where it is doing nothing. `MINIO_ENDPOINT` is
now `http://minio.minio.svc.cluster.local:9000`. Users still reach MinIO over
HTTPS at its own hostname; only the in-cluster job traffic is plain.

### And one fault that was mine

The first successful Job still failed, on `UnicodeDecodeError: byte 0x89` — the
PNG magic number. The FDL script does not take a raw file:

```python
with open(FILE_PATH, "r") as f:
    params = json.loads(f.read())
```

**The input is a JSON document**, with files base64-encoded inside an
`oscar-files` array. Worth stating loudly because nothing in the dashboard says
so, and a user dropping a JPEG into `inputs/` gets a stack trace:

```json
{"oscar-files": [{"key": "files", "file_format": "png", "data": "<base64>"}]}
```

## Stage O5 — The browser check · half a day · **non-negotiable**

The Inference list and detail components have never rendered against real data
in this deployment. Every prior UI stage in this project found something no
script could:

- Stage 3 found three faults a browser saw and curl did not.
- Stage L4 found two that no status code could report.
- Stage L5 found a blank dropdown and six broken images behind HTTP 200s.

D-49 is the rule: **a change that has not been through a browser is not ready,
whatever the test suite says.**

### Gate

Create, list, inspect and delete an OSCAR service entirely from the dashboard,
with screenshots into `docs/screenshots/` per the F0 convention.

---

## Stage O6 — Decide whether it earns a demo beat · half a day

The walkthrough is 25 minutes over 8 beats and already runs long.

**Recommendation: replace beat 6 rather than adding a ninth.** Beat 6 is
"serve it as an API"; OSCAR tells a strictly stronger version of the same
story — the same model, the same REST call, but consuming nothing while idle.

`docs/feature-coverage.md` argues scale-to-zero is "close to invisible in a
25-minute walkthrough", and that remains true of the *demo*. The grant and
roadmap value is real and separate, and is served by the platform having it at
all rather than by three minutes of stage time.

### Gate

Either a rewritten beat 6, timed; or a written decision not to demo it, with
the roadmap slide updated to say it is built rather than planned.

---

## Risks

| | |
|---|---|
| **R-30** | OSCAR's OIDC discovery fails against our private CA. Fifth occurrence of this pattern — see the table in O2 |
| **R-31** | **MinIO is not Nextcloud.** OSCAR brings a second object store, unrelated to the platform's Storage tab. D-15 is unchanged, and the Storage tab still will not work |
| **R-32** | K3s must never run on a Nomad client — both manage containerd and cgroups, and the failure mode is a node that half-works |
| **R-33** | ~~3 vCPU~~ **Closed 2026-08-25.** The node has 16 vCPU and 58 GB; K3s, MinIO and the manager want ~1.5 cores |
| **R-34** | OSCAR services are **CPU-only**: `ai4eosc-7` has no GPU. Fine for DEEPaaS inference. GPU-backed serverless would need a different node and a device plugin — remembering R-18, where that plugin was silently broken and `nvidia-smi` did not reveal it |
| **R-35** | `allowed_users` and `vo` in the FDL must match `vo.caios.ca` exactly, or services are created and then filtered out of the listing — created but invisible |
| **R-36** | Adding a Kubernetes cluster adds a second orchestrator to operate, monitor and explain. That cost is permanent and is not in the day estimate |
| **R-37** | **The 20 GB root disk.** K3s defaults every path to `/var/lib/rancher/k3s`. Left unset it fills `/` and the node dies quietly, exactly as Stage 3's containerd image store did. `--data-dir /mnt/k3s`, verified with `du`, not assumed |

---

## Decisions this plan proposes

To be appended to `docs/decisions.md` once implementation confirms them.

**D-50 — A feature we do not run must fail as unconfigured, not as broken.**
*Settled — Stage O0.* Recorded already.

**D-51 — OSCAR runs asynchronous-only until synchronous is asked for.**
Knative serves synchronous invocation and roughly doubles the moving parts.
Asynchronous execution tells the whole serverless story and the platform
already has a low-latency path in DEEPaaS. Proposed.

**D-52 — The OSCAR cluster is a separate node, and never a hospital node.**
*Settled by provision — `ai4eosc-7` (192.168.104.69), 16 vCPU, 58 GB, no GPU,
560 GB at `/mnt`. It stays out of the Nomad inventory (R-32) and needs no
reformat, so nothing about it touches the running platform.*

**D-53 — Everything K3s writes lives on `/mnt`.**
The root disk is 20 GB. `--data-dir /mnt/k3s`, verified by measurement after
install rather than by reading the flag's documentation. Proposed; O2 settles
it.
