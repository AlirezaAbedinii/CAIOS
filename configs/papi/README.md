# PAPI configuration

Files here are mounted into the PAPI container. Upstream lives in
`vendor/ai4-papi/`; never edit it there.

| File | Mounted at | Why it must change |
|---|---|---|
| `main.yaml` | `/srv/ai4-papi/etc/main.yaml` | Domain, CORS, VO, namespace and load-balancer mappings. Upstream ships AI4EOSC's. |
| `var/datacenters.csv` | `/srv/ai4-papi/var/datacenters.csv` | The Statistics page reads this to place datacenters on a map. Our datacenter name (`caios`) must appear, or PAPI adds it dynamically at latitude 0, longitude 0 — the Gulf of Guinea. Coordinates are Victoria, BC (Arbutus). |
| `.env` | container environment | Nomad mTLS paths and tokens. Generated from `../env/caios.env.template`; never committed. |

## Environment variables

Only four are genuinely mandatory:

```
NOMAD_ADDR  NOMAD_CACERT  NOMAD_CLIENT_CERT  NOMAD_CLIENT_KEY
```

Everything else (`ZENODO_TOKEN`, `GITHUB_TOKEN`, `HARBOR_ROBOT_PASSWORD`,
`JENKINS_TOKEN`, `PROVENANCE_TOKEN`, `MAILING_TOKEN`, `WATTNET_PASSWORD`,
`ACCOUNTING_PTH`, `LLM_API_KEY`) belongs to services we are not running.

**Leave `IS_PROD` unset.** PAPI defaults it to `false`, and in that mode missing
tokens produce warnings. Set it to `true` without those services and PAPI
refuses to start with an error that does not point at the cause.

## Things upstream hardcodes that we patch

Two values live in Python, not in config, and both must be patched — see
`../../patches/ai4-papi/`:

- `ai4papi/auth.py` — Keycloak realm URL
- `ai4papi/routers/v1/secrets.py` — Vault address

## Tool configuration we override

`ai4os-federated-server/user.yaml` restricts `docker_tag` to `['latest']`
upstream, which hides the `tokens` image. That image is what gives each
federated client its own revocable credential — a beat worth having in the
demo. `tools/` here adds it back.
