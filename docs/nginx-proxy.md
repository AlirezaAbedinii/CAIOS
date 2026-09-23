# The proxy VM — the public front door, and how to change it

`134.87.8.230` is a **separate machine** running Ubuntu's nginx 1.18.0. It is
the public front door for the whole platform, and it is also the jumpserver:
humans reach every instance through it over OpenVPN.

Its full configuration was read on 2026-09-23 and the CAIOS half is saved at
`ops/jumpserver/caios.conf.live-20260923`. That file is the baseline the
generated config is checked against.

---

## Two things to know before touching it

### 1. It serves a project that is not CAIOS

`/etc/nginx/conf.d/seventask.conf` proxies an unrelated application on
**:8888** to `192.168.104.198`. Nothing in this repository knew about it until
2026-09-23.

**Only ever replace `/etc/nginx/conf.d/caios.conf`.** Never `nginx.conf`,
never `seventask.conf`, never anything in `sites-enabled` (which is empty).

And one coupling that is easy to destroy by tidying up. `caios.conf` defines

```nginx
map $http_upgrade $connection_upgrade { default upgrade; '' close; }
```

in the **http context**, and `seventask.conf` *uses it without defining its
own* — deliberately, with a comment saying so, because a duplicate `map` is a
global nginx syntax error. So:

- remove it, and WebSockets break for the other project;
- emit it twice, and **nginx refuses to start, for everybody**.

`tests/test_jumpserver_config.py` asserts it appears exactly once.

### 2. It is the way people reach the cluster

Breaking nginx costs the website. Breaking `sshd` costs access to every
instance. **Nothing in this procedure touches sshd**, and nothing should.

For the same reason `caios_server`'s SSH key is deliberately **not** installed
here: that would let anything that compromises the public web tier reach the
bastion, and from there everything behind it. The proxy is configured by a
human from a workstation that already has access. See D-77.

---

## What it does today

Measured through `scripts/check-public-path.sh`, which is immune to the
`/etc/hosts` entry on `caios_server` that otherwise hides this machine.

| Request | Result |
|---|---|
| `:80`, **any** hostname | `301` to `https://` — one `default_server` block |
| `:443` `dashboard\|api\|auth\|vault.<domain>` | `200/200/302/307`, proxied to Caddy on `192.168.104.181` |
| `:443` `*.pacs-deployments.<domain>` | proxied to Traefik on `192.168.104.105` |
| `:443` anything else | falls to the default server, then Caddy, then `502` |

It presents the **CAIOS CA's** certificate: `/etc/nginx/certs/caios-public.pem`
is a byte-identical copy of this repository's `compose/certs/control-plane.pem`
(same serial), and `caios-deployments.pem` is the Traefik wildcard. Both were
copied here by hand.

`auth` and `vault` send `Strict-Transport-Security: max-age=31536000;
includeSubDomains` — Keycloak and Vault set it themselves. Those two hostnames
therefore cannot be served over plain HTTP again in any browser that has seen
them, for a year. `docs/certificate-plan.md` says there is no HSTS anywhere;
that is wrong and this is the correction.

### The internal leg is verified

```nginx
proxy_ssl_verify      on;
proxy_ssl_name        $host;
proxy_ssl_trusted_certificate /etc/nginx/certs/caios-ca.pem;
```

nginx checks that Caddy and Traefik present a certificate valid for **the
hostname the visitor asked for**. Moving the platform to a new domain without
reissuing *both* internal certificates with the new SANs turns every request
into a `502`, behind a public certificate a browser calls perfectly valid.
This is trap 1 of the certificate plan, and it is the one that will actually
happen.

---

## Changing it

The config is generated from `configs/env/caios.env` — the same
`CAIOS_PUBLIC_DOMAIN` everything else derives from (stage C0).

```bash
bash scripts/render-nginx-config.sh --diff
```

renders to `build/jumpserver/caios.conf` and diffs it against the saved live
copy. **With no domain change, that diff is empty**; that is what proves the
template is faithful before it is asked to carry a new name.

### Applying it

From a workstation that already has jumpserver access:

```bash
scp build/jumpserver/caios.conf ubuntu@134.87.8.230:/tmp/caios.conf
```

Then, on the proxy — back up, install, **test, and only then reload**:

```bash
sudo cp /etc/nginx/conf.d/caios.conf ~/caios.conf.bak-$(date +%Y%m%d-%H%M%S) && \
sudo cp /tmp/caios.conf /etc/nginx/conf.d/caios.conf && \
sudo nginx -t && sudo systemctl reload nginx
```

`&&` throughout is the safety: a failed `nginx -t` stops before the reload, and
the running nginx keeps its current configuration until one succeeds. A bad
file sitting in `conf.d` changes nothing by itself.

If `nginx -t` fails:

```bash
sudo cp ~/caios.conf.bak-<stamp> /etc/nginx/conf.d/caios.conf && sudo nginx -t
```

### Verifying it

From `caios_server`, before and after:

```bash
bash scripts/check-public-path.sh > /tmp/before
# ... apply ...
bash scripts/check-public-path.sh > /tmp/after
diff /tmp/before /tmp/after
```

Empty is the pass. The script fails outright if any response came from
somewhere other than the proxy, which is the mistake this whole page exists to
prevent.

---

## Adding a real domain (C2/C3)

**Additive, not a cutover.** Set the new domain as the primary and move the
current one to `CAIOS_LEGACY_DOMAIN`:

```bash
CAIOS_PUBLIC_DOMAIN=caios.ca
CAIOS_LEGACY_DOMAIN=${CAIOS_PUBLIC_IP}.sslip.io
```

Both then get their own `server` blocks on their own certificates, and both
keep answering. **Rolling back is swapping those two lines** and re-applying —
no certificate is reissued and nothing is deleted at any point.

The Let's Encrypt certificate lives **only here**. Caddy and Traefik keep
their CAIOS CA certificates for the internal leg, which is what
`proxy_ssl_verify` validates against — so they must be reissued with the new
SANs in the same change.

Certbot, on the proxy, once:

```bash
sudo apt-get install -y certbot python3-certbot-dns-cloudflare
sudo install -m 600 /dev/null /etc/letsencrypt/cloudflare.ini
# dns_cloudflare_api_token = <CAIOS_CF_API_TOKEN from caios.env>

sudo certbot certonly --dns-cloudflare \
  --dns-cloudflare-credentials /etc/letsencrypt/cloudflare.ini \
  --dns-cloudflare-propagation-seconds 30 \
  -d caios.ca -d '*.caios.ca' -d '*.pacs-deployments.caios.ca' \
  --email "$CAIOS_ACME_EMAIL" --agree-tos --non-interactive \
  --deploy-hook 'systemctl reload nginx' \
  --dry-run          # REMOVE only after the dry run passes
```

**Do the `--dry-run` first.** Production rate limits are unforgiving and a
burned week would be fatal this close to recording. Certbot installs its own
renewal timer; the deploy hook is what makes a renewal take effect.

One certificate covers both tiers, which is why the rendered config points
both server blocks at the same `fullchain.pem`.

### gRPC is not proxied here

There is no `grpc_pass` anywhere in this config, and `proxy_pass` cannot carry
gRPC. The federated demo works because its three clients run inside the
cluster and reach Traefik directly across the private subnet — they never come
through this machine.

**Test the federated round trip on a public hostname before changing
anything**, so a pre-existing limitation is not mistaken for damage done by the
cutover. nginx 1.18 supports `grpc_pass grpcs://...` if it turns out to matter.

---

## What this page used to say

Until 2026-09-23 it described a plan to make `:80` proxy to Caddy instead of
redirecting, so the platform could be served over plain HTTP (T5, checklist
item 5). **That is retired.** A real domain with a publicly trusted
certificate removes the browser warning the other way — the certificate
becomes legitimate rather than absent — and nothing travels in clear text.
See `docs/certificate-plan.md` and D-77.

It also said the config lived in `/etc/nginx/sites-available/caios`. It does
not; it is `/etc/nginx/conf.d/caios.conf`, and `sites-enabled` is empty.
