# Public access — one floating IP, and what actually routes through it

How CAIOS is reached from outside the VPN, with exactly **one** floating IP.

**Status: built 2026-08-25.** The control plane is public and working. Deployments
are one Caddy site block short — see [The remaining gap](#the-remaining-gap-deployments).

Read with `docs/infrastructure.md` (what each node is) and `docs/runbook.md`
(operational triage).

---

## What was actually built

The original plan for this document assumed a separate VM running nginx. That
turned out to be unnecessary, and the reason is worth stating because it is the
single most useful fact here:

> **An OpenStack floating IP is DNAT, not an interface address.** `134.87.8.230`
> is mapped to `192.168.104.181` by the network layer. `ip addr` on
> `caios_server` shows only its private address — the public one never appears
> there — and Caddy, already listening on `*:443`, serves the public hostnames
> without knowing anything changed.

So there is **no nginx and no proxy VM**. The floating IP lands on
`caios_server`, and Caddy is the reverse proxy that was already there.

```
                    Internet
                       │
                134.87.8.230            ← OpenStack floating IP (DNAT)
                       │
                       ▼
        ┌──────────────────────────────┐
        │ caios_server  192.168.104.181│
        │ Caddy  :80 :443              │
        │   dashboard.134.87.8.230…    │
        │   api.134.87.8.230…          │
        │   auth.134.87.8.230…         │
        │   vault.134.87.8.230…        │
        └──────────────┬───────────────┘
                       │  private subnet
                       ▼
        ┌──────────────────────────────┐
        │ caios_edge  192.168.104.105  │
        │ Traefik :443                 │
        │  *.pacs-deployments.…        │   ← nothing routes here yet
        └──────────────────────────────┘
```

### The change that made it work

One new variable in `configs/env/caios.env`, with every public hostname derived
from it:

```bash
CAIOS_CTRL_IP=192.168.104.181     # unchanged — PAPI still reaches Nomad here
CAIOS_EDGE_IP=192.168.104.105     # unchanged
CAIOS_PUBLIC_IP=134.87.8.230      # new

CAIOS_DASHBOARD_HOST=dashboard.${CAIOS_PUBLIC_IP}.sslip.io
CAIOS_API_HOST=api.${CAIOS_PUBLIC_IP}.sslip.io
CAIOS_AUTH_HOST=auth.${CAIOS_PUBLIC_IP}.sslip.io
CAIOS_VAULT_HOST=vault.${CAIOS_PUBLIC_IP}.sslip.io
```

The internal IPs stay exactly as they were. Only the *public-facing* names
moved, which is what keeps PAPI's loopback path to Nomad untouched.

`configs/papi/main.yaml` followed:

```yaml
lb:
  domain:
    vo.caios.ca: deployments.${CAIOS_PUBLIC_IP}.sslip.io
```

And both certificates were reissued from the CAIOS CA — verified on the running
system:

| Certificate | SANs |
|---|---|
| Control plane (Caddy, `.181`) | `dashboard/api/auth/vault.134.87.8.230.sslip.io`, `localhost`, IP `192.168.104.181`, IP `127.0.0.1` |
| Deployment wildcard (Traefik, `.105`) | `*.pacs-deployments.134.87.8.230.sslip.io`, `pacs-deployments.134.87.8.230.sslip.io` |

---

## What is exposed

Verified by reading listening sockets and Traefik's live routing table.

### Tier 1 — Control plane · Caddy on `caios_server`, public via the floating IP

| Public hostname | → upstream | Service | Notes |
|---|---|---|---|
| `dashboard.134.87.8.230.sslip.io` | `127.0.0.1:8081` | Angular dashboard | Also serves `/caios-ca.pem` and `/fl/*` directly from Caddy |
| `api.134.87.8.230.sslip.io` | `127.0.0.1:8000` | PAPI | Swagger at `/docs`. **PAPI emits its own CORS headers** — never add them in a proxy, duplicates are rejected by browsers |
| `auth.134.87.8.230.sslip.io` | `127.0.0.1:8180` | Keycloak | Needs `X-Forwarded-Proto: https` or it mints `http://` issuers and everything 401s |
| `vault.134.87.8.230.sslip.io` | `127.0.0.1:8200` | Vault | Admin only. **Consider whether this should be public at all** |

### Tier 2 — Deployments · Traefik on `caios_edge`

Dynamic: Traefik learns routes from Consul tags as Nomad jobs start and stop.

```
*.pacs-deployments.134.87.8.230.sslip.io      ← what PAPI now issues
*.pacs-deployments.192.168.104.105.sslip.io   ← what older deployments still carry
```

| Prefix | What it is | Protocol requirement |
|---|---|---|
| `ide-` | JupyterLab / VS Code workspace | **WebSocket upgrade** |
| `api-` | DEEPaaS REST API of a deployed module | plain HTTP |
| `monitor-` | Monitoring endpoint | plain HTTP |
| `custom-` | Module-specific extra port | varies |
| `ui-` | Open WebUI (LLM chat) | **SSE streaming** — buffering must be off |
| `vllm-` | vLLM OpenAI-compatible API | **SSE streaming** |
| `fedserver-` | Flower federated-learning server | **gRPC over HTTP/2** — see below |

> **`fedserver-` does not need to be public.** The three federated clients run
> inside cluster workspaces and reach Traefik across the private subnet. Leave
> it internal — gRPC through a second proxy layer is work with no payoff.

### Tier 3 — Never expose these

| Node | Port | Service |
|---|---|---|
| `.181` | 4646 | Nomad HTTP/UI (mTLS) |
| `.181` | 4647, 4648 | Nomad RPC / Serf |
| `.181` | 8500 | **Consul HTTP API** — ACLs on, but reachable subnet-wide |
| `.181` | 8300/8301/8302, 8600 | Consul RPC, Serf, DNS |
| `.181` | 2019 | Caddy admin API (loopback only) |
| `.105` | 8081, 8002, 8003 | Traefik entrypoints, currently unrouted |
| `.69` | 6443 | Kubernetes API (OSCAR node) |
| all | 22 | SSH |

**Only 80 and 443 should be reachable on the floating IP.** Check it:

```bash
nmap -Pn -p 22,80,443,4646,8500,8200 134.87.8.230
```

---

## The remaining gap: deployments

**The control plane is public and working. Deployments are not, and the reason
is one missing site block.**

PAPI now issues deployment URLs under `deployments.134.87.8.230.sslip.io`. That
name resolves to the floating IP, which DNATs to `caios_server` — where **Caddy
has only the four fixed vhosts and nothing matching the wildcard**. Traefik,
which does have the right routes and the right certificate, is on `caios_edge`
and receives nothing.

Confirmed on the running system: the Caddyfile contains exactly four
`https://…` site blocks plus a `:80` catch-all.

### Two consequences worth separating

**New deployments** get a public hostname that reaches Caddy and finds no site.

**Existing deployments** are unaffected and still work — but only on their *old*
private hostnames, because a Nomad job bakes its Traefik router rule at submit
time. The four federated jobs and the LLM deployment all still carry
`…pacs-deployments.192.168.104.105.sslip.io`. Nothing re-writes them; they keep
working on the VPN and are invisible publicly until redeployed.

### The fix

Add one wildcard site block to `compose/caddy/Caddyfile`:

```caddy
# Deployments. Traefik on caios_edge owns the routing and holds the wildcard
# certificate; Caddy's only job here is to carry the request across from the
# floating IP, which lands on caios_server.
#
# The Host header must survive: Traefik routes on it exclusively, and every
# deployment is distinguished by hostname alone.
*.pacs-deployments.{$CAIOS_PUBLIC_IP}.sslip.io {
	import caios_tls

	reverse_proxy https://192.168.104.105 {
		header_up Host {host}
		header_up X-Forwarded-Proto https

		transport http {
			# Traefik serves the CAIOS wildcard cert for the *deployment*
			# names, not for the edge node's address, so verification must
			# be told which name to expect.
			tls
			tls_server_name {host}
			tls_trusted_ca_certs /etc/caddy/certs/caios-ca.pem
		}
	}
}
```

Then the control-plane certificate needs the wildcard added to its SANs, since
Caddy now terminates TLS for those names too:

```bash
# add *.pacs-deployments.${CAIOS_PUBLIC_IP}.sslip.io to the SAN list
bash scripts/make-control-plane-cert.sh
cd compose && sudo docker compose --env-file ../configs/env/caios.env up -d --force-recreate caddy
```

**Why proxy rather than move the floating IP to `caios_edge`:** the control
plane would then be unreachable instead. With one floating IP something has to
carry both, and Caddy is already the thing terminating TLS on the node that has
it.

### Verify

```bash
# deploy something new, then:
bash scripts/deploy-fl-demo.sh --status     # endpoints should now read 134.87.8.230
curl -sS -o /dev/null -w 'HTTP %{http_code}\n' --cacert caios-ca.pem \
  https://ide-<uuid>.pacs-deployments.134.87.8.230.sslip.io/
```

WebSocket and SSE behaviour is worth checking explicitly, because both fail
quietly: open a workspace terminal (proves WebSockets survive the extra hop),
and send an LLM prompt (proves the reply still streams rather than arriving in
one block).

---

## Certificates

### Do not try to use Let's Encrypt with sslip.io

Verified against the Public Suffix List and Let's Encrypt's published limits:

- `sslip.io` is **not** on the Public Suffix List.
- Let's Encrypt derives "registered domain" from that list, so every
  `*.sslip.io` name in the world belongs to the single registered domain
  `sslip.io`.
- The limit is **50 certificates per registered domain per 7 days**, shared
  with every other user of the service worldwide.

Issuance would fail unpredictably, and it would fail at the worst time.
Wildcards are worse: `*.pacs-deployments.<IP>.sslip.io` needs DNS-01, which
needs control of the `sslip.io` zone.

**With a real domain none of this applies** — one DNS-01 wildcard against your
own zone covers the control plane *and* every deployment, publicly trusted,
with no CA for visitors to install. That is V1 item 1, and now that the
platform is genuinely public it is the highest-value half-day left.

### Until then, visitors install the CA

`https://dashboard.134.87.8.230.sslip.io/caios-ca.pem`, served by Caddy.

This is functional, not cosmetic: the dashboard is served from `dashboard.…`
but calls `api.…` from JavaScript, and a background fetch cannot prompt for an
exception, so the browser silently blocks it and the page reports an API error.
Firefox keeps its own trust store and needs a separate import.

---

## Security, now that this is genuinely public

The threat model changed the moment the floating IP was attached. Previously
everything was behind a VPN and the honest description was "nothing is exposed".

- [ ] **Vault** — `vault.134.87.8.230.sslip.io` is publicly resolvable. It runs
      in **dev mode**: in-memory, auto-unsealed, with a fixed root token
      (D-14). That was a reasonable choice for a VPN-only demo and is a
      different proposition on a public address. Either restrict it or move it
      off dev-mode storage.
- [ ] **Keycloak redirect URIs** — must list the public dashboard origin, and
      must never be widened to `*`. A wildcard redirect on a public client is
      how tokens get stolen, and the client is now genuinely public.
- [ ] **`nomad_ui_passwd`** is still `CHANGEME` in `ansible/group_vars/all.yml`.
      Nomad is not exposed on 80/443, but this is now worth fixing rather than
      noting.
- [ ] **Rate limiting** — there is none in front of Keycloak's token endpoint.
- [ ] **Deployment workspaces** carry a single shared IDE password
      (`CAIOS_FL_IDE_PASSWORD`). Once deployments are publicly routable, that
      password is the only thing in front of a GPU workspace with a shell.

That last one is the sharpest: the fix in the previous section makes every
running workspace publicly reachable. **Do it deliberately, not incidentally.**

---

## Troubleshooting

Organised by symptom, because these failures are mostly silent.

**Every hostname fails TLS with `internal error`, from everywhere.**
Caddy has no certificate matching the SNI. This exact failure happened on
2026-08-25: the control-plane certificate was reissued for the public names and
the old `*.192.168.104.181.sslip.io` names stopped working the same second —
which looked like a total outage and was a rename. Check the SANs:

```bash
sudo openssl x509 -in compose/certs/control-plane.pem -noout -ext subjectAltName
```

**The dashboard loads, then says "Error calling the API".**
Either the visitor has not installed `caios-ca.pem`, or `API_SERVER` still
points somewhere else. Check what the running page believes:

```bash
curl -s https://dashboard.134.87.8.230.sslip.io/assets/config/config.json
```

`apiURL` must be public **and end in `/v1`**.

**Login redirects to a private address.**
`KC_HOSTNAME` was not updated, or Keycloak never re-imported the realm.
Keycloak imports a realm **only on first start** — fix it in the admin console.

**`invalid_redirect_uri` after entering a password.**
The public dashboard origin is not in the client's valid redirect URIs.

**Every request returns 401 with nothing useful logged.**
Issuer mismatch. The token records which Keycloak issued it and PAPI compares
character by character; `http` vs `https` or a trailing slash is enough.

**A deployment URL 404s.**
If it is a *new* deployment on a `134.87.8.230` hostname, that is the gap above.
If it is an *old* one, it still lives on its `192.168.104.105` hostname and is
VPN-only until redeployed.

**A workspace opens but has no kernel.**
WebSocket upgrade is not surviving a proxy hop.

**An LLM reply arrives all at once after a long pause.**
Response buffering somewhere in the chain. Caddy does not buffer by default;
anything added in front might.

---

## Appendix — when you *would* need a separate proxy VM

None of this is needed today. It becomes relevant if:

- **The floating IP moves to a VM that is not `caios_server`.** Then that VM
  needs to proxy both tiers, and nginx is a reasonable choice. Keep
  `proxy_set_header Host $host` (Caddy and Traefik route on it exclusively),
  `X-Forwarded-Proto https` (Keycloak mints `http://` issuers without it),
  `Upgrade`/`Connection` for workspaces, and `proxy_buffering off` for
  streaming. Note that Ubuntu 22.04 ships **nginx 1.18**, which wants
  `listen 443 ssl http2;` — `http2 on;` is 1.25.1+ and fails `nginx -t`.
- **A second floating IP becomes available.** Then attach it to `caios_edge`,
  point `lb.domain` at it, and delete the wildcard block entirely — Traefik
  serves deployments directly and there is no extra hop at all. **This is the
  better architecture**, and it is one quota request away.
