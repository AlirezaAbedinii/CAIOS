# A real certificate, on a domain we control

The last item on the finalization checklist, and the one that decides how every
visitor and every viewer of the recording meets the platform.

Written 2026-09-22. **Nothing has been built yet.** This is the handoff from the
session that investigated it: the facts, the plan, and the traps. Start by
reading it, then plan, then build.

`docs/finalization-plan.md` rows 5 and 11 are what this closes.
`docs/nginx-proxy.md` describes the machine that has to change.
`docs/public-access.md` describes the public path as it stands today.

---

## Where it stands

**Waiting on one answer.** A message went to the supervisor on 2026-09-22 asking
him to register `caios.ca` (about $12/year, at Namecheap or any CIRA-certified
registrar) and then point its nameservers at Cloudflare. Everything in stages C2
and C3 below is blocked on that. **C0 and C1 are not blocked and can start
immediately.**

If the answer is no, the fallback is `caios.pacslab.ca` as an A record in his
existing zone. That works, but his DNS moved to GoDaddy, whose API is gated
behind a paid tier, so the certificate would need him to paste TXT records by
hand every 60 days. Same plan either way; only stage C2 changes.

---

## The decision, in one paragraph

Today the platform serves HTTPS with a certificate from our own CA, so every
visitor meets a full-page browser warning and has to install `caios-ca.pem`
before the dashboard works at all. T5 (checklist item 5) proposed to fix that by
dropping to HTTP. **We are not doing that.** A real domain with a publicly
trusted wildcard certificate removes the warning the other way: the certificate
becomes legitimate rather than absent, nothing travels in clear text, and it
also answers checklist item 11. `CAIOS_SCHEME` stays `https` permanently and T5
is retired with a recorded reason.

---

## Facts established, and how

Everything here was measured on 2026-09-14 and 2026-09-22. Where a claim came
from somebody's screen rather than a command, it says so.

### The domain

| Fact | Evidence |
|---|---|
| `caios.ca` is **available** | CIRA's own RDAP returns 404 for it, and 200 for `pacslab.ca`, `cira.ca`, `uvic.ca` |
| `caios.com`, `.org`, `.dev`, `.app` are taken | NS records exist for all four |
| `pacslab.ca` **moved off Cloudflare** to GoDaddy, recently | NS is now `ns43/ns44.domaincontrol.com`; it was `ingrid/langston.ns.cloudflare.com` on 2026-09-14 |
| `pacslab.ca` now forwards to GitHub Pages | A records are GoDaddy's forwarding service |
| **Cloudflare cannot register `.ca`** | Not a CIRA-certified registrar. It hosts DNS for `.ca` but will neither register nor accept a transfer |
| **A work permit does not satisfy CIRA's presence requirement** | Eligible: citizens, permanent residents ordinarily resident, and Canadian institutions. Temporary residents are not a category |

Check availability again before assuming it is still free:

```bash
curl -s -o /dev/null -w '%{http_code}\n' https://rdap.ca.fury.ca/rdap/domain/caios.ca
# 404 = available, 200 = registered
```

### Why a redirect cannot work

Asked and answered three times, so it is written down. The supervisor offered to
redirect an endpoint to CAIOS. That does not help, for three independent
reasons:

1. **A redirect moves the visitor.** Their browser leaves `pacslab.ca` and
   connects to us, so from that moment the certificate must match *our*
   hostname. The warning returns exactly there.
2. **A proxy is not available.** `pacslab.ca` is GitHub Pages now, which serves
   static files and cannot proxy.
3. **A path cannot carry this platform anyway.** Every deployment gets its own
   hostname and Traefik routes on the Host header alone. `ide-<uuid>...` and
   `ui-<uuid>...` cannot live under a single `/caios` path.

What *would* work in his zone is a subdomain, `caios.pacslab.ca`, as an A
record. The distinction that matters is **DNS record, not redirect**.

### The proxy VM

`134.87.8.230`, Ubuntu 22.04.5, nginx 1.18.0. Not configured from this
repository. Measured through `--resolve` so that `/etc/hosts` on `caios_server`
could not mask it (gotcha 22).

| Observation | Value |
|---|---|
| `:80`, control-plane names | `301` to `https://`, `Server: nginx/1.18.0 (Ubuntu)` |
| `:443`, dashboard | `HTTP/2 200`, `Server: nginx/1.18.0 (Ubuntu)` |
| Certificate for control-plane SNI | CAIOS Local CA, 4 SANs + `localhost` + two IPs, expires 2028-11-27 |
| Certificate for a deployment SNI | `*.pacs-deployments.134.87.8.230.sslip.io`, also CAIOS CA |
| No `Strict-Transport-Security` anywhere | confirmed on both schemes |

**It terminates TLS for both tiers.** A request for a deployment hostname comes
back `404` with `Server: nginx/1.18.0`, carrying Traefik's wildcard certificate.
So the Let's Encrypt certificate goes **on this machine**, not on Caddy and not
on Traefik. Those two keep their CAIOS CA certificates for the internal leg.

From a partial `sudo nginx -T` pasted by the user (the full config has not been
read yet):

- upstreams named `caios_control_plane` and `caios_deployments`
- `proxy_pass https://...` to both, so the internal leg is HTTPS
- **`proxy_ssl_verify on`**, `proxy_ssl_verify_depth 2`, `proxy_ssl_name $host`,
  `proxy_ssl_trusted_certificate /etc/nginx/certs/caios-ca.pem`
- certificates at `/etc/nginx/certs/caios-public.{pem,key}` and
  `caios-deployments.{pem,key}`
- `listen 443 ssl http2` (the 1.18 form, as expected)
- deployment vhost matched by regex: `~^[^.]+\.pacs-deployments\....$`
- **no `grpc_pass` anywhere**
- no `/etc/letsencrypt`, no certbot, no acme.sh, no lego
- only `:80`, `:443` and a loopback `:53` listening

### What the repository hardcodes

Every public hostname is spelled `<svc>.${CAIOS_PUBLIC_IP}.sslip.io` rather than
derived from a domain. Files outside `vendor/`, `docs/` and `build/` that
mention `sslip`:

```
ansible/inventory/hosts.ini          configs/env/caios.env.template
configs/papi/main.yaml               demo/fl/client.py
nomad-jobs/smoke-test.hcl            patches/ai4-nomad_tests/0001-namespaces.patch
scripts/check-llm-deploy.sh          scripts/install-oscar.sh
scripts/make-traefik-certs.sh        scripts/oscar-submit.sh
scripts/render-configs.sh            scripts/run-cluster-tests.sh
tests/render.py                      tests/test_scheme_switch.py
```

Also relevant and not in that list, because they derive from the variables:
`compose/docker-compose.yml` (`KC_HOSTNAME`, `KEYCLOAK_URL`, `API_SERVER`,
`ISSUER`, `CAIOS_CORS_ORIGINS`), `scripts/keycloak-bootstrap.sh`
(`redirectUris`, `webOrigins`), `scripts/make-control-plane-cert.sh` (SANs), and
`/etc/hosts` on `caios_server`.

`scripts/install-oscar.sh:45` carries a **literal** `https://auth.134.87.8.230.sslip.io/realms/caios`
as the OIDC issuer default. OSCAR must be re-run, or it will reject every token
after the cutover.

---

## The plan

Five stages. C0 and C1 need no domain.

### C0 — Make the domain one variable

Introduce `CAIOS_PUBLIC_DOMAIN`, defaulting to `${CAIOS_PUBLIC_IP}.sslip.io`, and
derive every hostname from it. Touches the file list above plus
`configs/papi/main.yaml` (`api.domain`, `CORS_origins`, `lb.domain`).

Add `CAIOS_ACME_EMAIL` and `CAIOS_CF_API_TOKEN` placeholders to the env template.
Add `tests/test_public_domain.py`: nothing outside the template may hardcode
`sslip`.

**Gate.** Set the variable to its sslip default in the live `caios.env`,
re-render, and diff the generated tree against what is there now. **Zero
differences.** Then the full suite still passes.

*Estimate: 1 hour.*

### C1 — The jumpserver becomes an Ansible-managed host

It is the only machine in the architecture configured by hand, and it is about
to hold the certificate.

- `[jumpserver]` in `ansible/inventory/hosts.ini`
- `ansible/playbook-jumpserver.yml`
- `ansible/templates/nginx-caios.conf.j2`, reproducing the current config
  faithfully, with `server_name` values from `CAIOS_PUBLIC_DOMAIN` and a
  `caios_tls_mode: caios-ca | acme` switch choosing between
  `/etc/nginx/certs/caios-*.pem` and `/etc/letsencrypt/live/.../fullchain.pem`
- installs `certbot python3-certbot-dns-cloudflare`, writes
  `/etc/letsencrypt/cloudflare.ini` mode 600, `--deploy-hook 'systemctl reload nginx'`
- backs up the existing config first; `nginx -t` before every reload

Keep the `:80` to `:443` redirect. Under HTTPS it is correct.

**Gate.** Run it in `caios-ca` mode against the *current* sslip hostnames. The
rendered config must be equivalent to what is already there and the public site
must be unchanged. That proves the template before it ever carries a new name.

*Estimate: 2 hours. Needs SSH to the jumpserver, see Open questions.*

### C2 — DNS and the certificate

Blocked on the domain.

1. Cloudflare free account, `caios.ca` added as a zone, **2FA on**, scoped API
   token (Edit zone DNS, that zone only) into `caios.env` (gitignored, 600).
2. `scripts/make-dns-records.sh`, idempotent: A records for `caios.ca`,
   `*.caios.ca` and `*.pacs-deployments.caios.ca`, all to `134.87.8.230`, all
   DNS-only. Plus a CAA record pinning issuance to `letsencrypt.org`. Verify
   with `dig @1.1.1.1`.
3. Playbook in `acme` mode. **Let's Encrypt staging first**, inspect the chain,
   then production. Staging is not optional: production rate limits are
   unforgiving and a burned week would be fatal this close to recording.

*Estimate: 30 minutes.*

### C3 — Cutover

`CAIOS_PUBLIC_DOMAIN=caios.ca`, then in this order:

1. `render-configs.sh`
2. `make-traefik-certs.sh` and `make-control-plane-cert.sh`, then ship Traefik's
   to `caios_edge` (`playbook-nomad.yml --limit caios_edge`, and remove the
   unpacked directory first or the role will not re-extract)
3. `keycloak-bootstrap.sh`, because `redirectUris` and `webOrigins` are **live
   realm settings** and the realm import runs only once
4. `apply-patches.sh`, `build-dashboard.sh`
5. `docker compose up -d --build`
6. `/etc/hosts` on `caios_server`
7. `install-oscar.sh` with the new issuer
8. `build-fl-bundles.sh`
9. Redeploy every running deployment. A Nomad job bakes its Traefik router tags
   at submit time.
10. `verify-cluster.sh`, every `check-*.sh`, `fl-rehearse.sh`

**Gate.** From a laptop, **off the VPN**, in a clean browser profile: padlock on
the dashboard, login, a workspace terminal (WebSockets), an LLM reply streaming
(SSE), an approval at `/admin`. No certificate dialog anywhere.

*Estimate: 4 hours.*

### C4 — Write it down

D-77 (a trusted certificate on a domain we own; item 5's intent met by HTTPS
done properly; T5 retired), D-78 (the jumpserver is Ansible-managed), D-79 (the
FL bundle trusts the system store). Then `docs/nginx-proxy.md` rewritten,
`public-access.md`, `runbook.md`, `finalization-plan.md` rows 5 and 11,
`CLAUDE.md` gotchas 22 and 23 plus status, the demo script's opening URL,
`rollback/README.md`.

*Estimate: 1 hour.*

---

## Traps

Four, and the first is the one that will actually happen.

1. **nginx verifies its upstreams by hostname.** `proxy_ssl_verify on` with
   `proxy_ssl_name $host` means the proxy checks that Caddy and Traefik present
   a certificate valid for the *new* names. Reissue both internal certificates
   with the new SANs in the same change, or the whole platform answers `502`
   with a certificate that looks perfectly fine in a browser.

2. **The FL bundle trusts our CA and nothing else.** D-43 pins
   `SSL_CERT_FILE=caios-ca.pem` and passes `--ca caios-ca.pem` to gRPC. After
   the cutover the public endpoints present a Let's Encrypt chain, so the bundle
   must fall back to the system trust store. This is an improvement worth saying
   out loud in the recording: the workspaces stop needing our CA at all. The
   federated server itself keeps TLS under our CA (D-67), so `client.py`'s
   `--ca` flag stays meaningful for that one hop.

3. **gRPC through the proxy is probably already broken on the public names.**
   There is no `grpc_pass` in the nginx config and `proxy_pass` cannot carry
   gRPC. The demo works because the three clients run inside the cluster and
   reach Traefik directly across the private subnet. **Test the federated round
   trip on a public hostname before changing anything**, so that a pre-existing
   fault is not mistaken for damage done by the cutover. If it needs fixing,
   nginx 1.18 supports `grpc_pass grpcs://...`.

4. **`/etc/hosts` on `caios_server` hides the proxy.** Four hostnames are mapped
   straight to `192.168.104.181`, so every curl from that node bypasses the
   public path entirely. Always `--resolve` and read `Server:`. `nginx/1.18.0
   (Ubuntu)` means the proxy; `Caddy` means you never left the box. Update the
   file during C3 or the cutover will appear to work from the one machine where
   it is least meaningful.

---

## Open questions

1. **Did the supervisor register the domain?** Everything from C2 waits on this.
2. **SSH to the jumpserver.** `caios_server`'s public key
   (`~/.ssh/caios_cluster.pub`, `ssh-ed25519 AAAA...RU9J caios-cluster-20260812`)
   was to be appended to `~/.ssh/authorized_keys` on `134.87.8.230`. **The
   username on that machine is still unknown.** Without it, C1 can be written
   but not applied.
3. **The full `sudo nginx -T`** has not been read, only a grep of it. Fetch it
   before writing the Jinja template.

---

## Rollback

`CAIOS_PUBLIC_DOMAIN` back to `${CAIOS_PUBLIC_IP}.sslip.io`, playbook in
`caios-ca` mode, re-render, restart. Both machines keep their existing
certificates throughout, and the sslip.io names keep resolving because sslip.io
is a public service that never stops answering. Nothing is deleted at any stage.

---

## What was rejected, and why

| Option | Why not |
|---|---|
| HTTP instead of HTTPS (T5) | Removes the warning by removing the certificate. Passwords and tokens in clear text on a public IP, "Not secure" for the whole recording, and it still needs the proxy VM changed |
| Let's Encrypt on the sslip.io names | `sslip.io` is not on the Public Suffix List, so its 50-certificates-per-week limit is shared with every user of the service worldwide. Wildcards impossible. D-12 |
| A redirect or a path under `pacslab.ca` | See "Why a redirect cannot work" |
| `pacslab.github.io` | GitHub controls that zone. We can add no records and it cannot proxy |
| Cloudflare proxy ("orange cloud") free Universal SSL | Covers one label only, so `dashboard.caios.ca` would be covered but nothing deeper. Also routes all traffic through a third party, which sits badly with a platform whose argument is that data stays in Canada |
| Cloudflare Registrar | Cannot register or hold `.ca` |
| A paid commercial certificate | Still needs a domain, and buys nothing over Let's Encrypt except manual renewal |
