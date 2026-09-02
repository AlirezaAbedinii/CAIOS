# The proxy VM — the one change T5 still needs, and how to make it

`134.87.8.230` is a **separate machine** running Ubuntu's nginx 1.18.0. It is
the public front door for the whole platform and it is **not configured from
this repository**. Nothing in `ansible/`, `compose/` or `scripts/` touches it.

Found on 2026-09-02, during T5. `docs/public-access.md` had claimed there was
no such machine; that claim is corrected there, along with the `/etc/hosts`
entry on `caios_server` that hid it from every test.

---

## What it does today

| Request | Result |
|---|---|
| `:80`, any hostname | `301` to the same URL on `https://` |
| `:443`, `dashboard\|api\|auth\|vault.134.87.8.230.sslip.io` | terminates TLS, proxies to Caddy on `192.168.104.181` |
| `:443`, `*.pacs-deployments.134.87.8.230.sslip.io` | terminates TLS, proxies to Traefik on `192.168.104.105` |
| `:443`, anything else | `502` |

It presents the **CAIOS CA's** certificate, not a publicly trusted one.

Two facts established by measurement rather than assumption:

- It is a different machine from both cluster nodes. Its SSH host key matches
  neither `192.168.104.181` nor `192.168.104.105`.
- It does **not** proxy to Caddy on port 80. Caddy's `:80` answers `404` for
  every control-plane hostname while the public HTTPS path answers `200`, so
  the upstream leg is HTTPS.

That last one is why the current state is safe: adding HTTP site blocks to
Caddy changed nothing for a public visitor.

---

## Why T5 is blocked on it

**The redirect makes the HTTP switch worse than a no-op — it makes the platform
unreachable.**

With `CAIOS_SCHEME=http`:

1. Visitor opens `http://dashboard.134.87.8.230.sslip.io/`
2. The proxy answers `301 → https://dashboard...`
3. The proxy terminates TLS and proxies to Caddy on `:443`
4. Caddy, now serving HTTP, answers `:443` with `302 → http://dashboard...`
5. Back to step 1.

A redirect loop, on the hostname the demo opens on.

And even without the loop, the switch would buy nothing: the proxy's own
certificate is issued by the CAIOS CA, so a visitor still has to install
`caios-ca.pem` — which is the entire point of the requirement.

**So `CAIOS_SCHEME` must stay `https` until this file has been applied.**
`scripts/preflight.sh` (T7) should assert it.

---

## The change

One server block replaced. On the proxy VM:

```bash
sudo cp /etc/nginx/sites-available/caios /etc/nginx/sites-available/caios.bak-$(date +%Y%m%d)
```

Replace the `listen 80` block — the one that does nothing but redirect — with a
block that proxies, using the same `Host`-based routing the `:443` blocks
already use:

```nginx
# CAIOS T5. Plain HTTP is a first-class entrance, not a doormat.
#
# The platform serves HTTP (CAIOS_SCHEME=http in configs/env/caios.env) so that
# a visitor needs no certificate authority installed. Redirecting to HTTPS here
# would send them to a TLS page whose API calls are then blocked as mixed
# content — and, because Caddy answers HTTPS with a redirect back to HTTP, into
# a redirect loop.
#
# The :443 blocks below are unchanged. Both schemes answer; the platform
# decides which one it advertises.

server {
    listen 80;
    listen [::]:80;
    server_name dashboard.134.87.8.230.sslip.io
                api.134.87.8.230.sslip.io
                auth.134.87.8.230.sslip.io
                vault.134.87.8.230.sslip.io;

    # Caddy on caios_server. Plain HTTP upstream: Caddy serves both schemes and
    # the HTTP site block is the real one while CAIOS_SCHEME=http.
    location / {
        proxy_pass http://192.168.104.181;
        proxy_set_header Host              $host;
        proxy_set_header X-Real-IP         $remote_addr;
        proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;

        # Keycloak mints the issuer from this. It MUST say http, or every token
        # carries an https:// issuer into an http:// platform and PAPI answers
        # 401 on everything while the login page itself looks perfect.
        proxy_set_header X-Forwarded-Proto http;
        proxy_set_header X-Forwarded-Port  80;

        # JupyterLab and Open WebUI. ws:// rather than wss:// now, same upgrade.
        proxy_http_version 1.1;
        proxy_set_header Upgrade    $http_upgrade;
        proxy_set_header Connection "upgrade";

        # Open WebUI and vLLM stream token by token. Buffering turns that into
        # one long pause followed by the whole answer at once, which on camera
        # reads as a model that does not work.
        proxy_buffering off;
        proxy_read_timeout 3600s;
        proxy_send_timeout 3600s;
    }
}

server {
    listen 80;
    listen [::]:80;
    server_name *.pacs-deployments.134.87.8.230.sslip.io;

    # Traefik on caios_edge. It routes on Host alone, so the header must survive
    # exactly — every deployment is distinguished by hostname and nothing else.
    location / {
        proxy_pass http://192.168.104.105;
        proxy_set_header Host              $host;
        proxy_set_header X-Real-IP         $remote_addr;
        proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto http;

        proxy_http_version 1.1;
        proxy_set_header Upgrade    $http_upgrade;
        proxy_set_header Connection "upgrade";

        proxy_buffering off;
        proxy_read_timeout 3600s;
        proxy_send_timeout 3600s;
    }
}
```

Then:

```bash
sudo nginx -t && sudo systemctl reload nginx
```

`nginx -t` before reload is not ceremony: Ubuntu 22.04 ships nginx **1.18**,
which rejects `http2 on;` (that is 1.25.1+) and wants `listen 443 ssl http2;`.
If the existing `:443` blocks use the newer form, this nginx is not 1.18 and
the version assumptions here need rechecking.

**Leave every `:443` block exactly as it is.** They are what makes the rollback
work: flip `CAIOS_SCHEME` back to `https`, re-render, restart, and the platform
is served over TLS again with no change needed here.

---

## Then, and only then

```bash
sed -i 's/^CAIOS_SCHEME=.*/CAIOS_SCHEME=http/' configs/env/caios.env
bash scripts/render-configs.sh
bash scripts/keycloak-bootstrap.sh          # sslRequired=none on the LIVE realm
bash scripts/apply-patches.sh
bash scripts/build-dashboard.sh
cd compose && docker compose --env-file ../configs/env/caios.env up -d --build
cd .. && bash scripts/build-fl-bundles.sh
bash scripts/verify-cluster.sh
bash scripts/check-dashboard.sh
bash scripts/check-identity.sh
```

Redeploy anything that was running: a Nomad job bakes its Traefik router tags
at submit time, so a deployment created before the flip keeps its HTTPS-only
router until it is recreated.

## Verifying it, from a machine that is not `caios_server`

Or from `caios_server` with `--resolve`, which is what defeats the `/etc/hosts`
entry that hid this proxy in the first place:

```bash
for h in dashboard api auth; do
  curl -sD- --resolve $h.134.87.8.230.sslip.io:80:134.87.8.230 \
       http://$h.134.87.8.230.sslip.io/ -o /dev/null | head -1
done
```

Every line must be `200`, `302` or `404` — **never `301`**. A `301` means the
redirect is still there and the loop is live.
