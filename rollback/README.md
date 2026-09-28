# Rollback

Saved container images, so a deployment that misbehaves can be undone in
seconds rather than rebuilt under pressure.

`*.tar` files are **gitignored** — they are 150–200 MB each. What *is* tracked
is this file and the git tag each image was built from, which is what makes
them reproducible.

## Restore an image

```bash
sudo docker load -i rollback/dashboard-pre-step5.tar
sudo docker tag caios/dashboard:pre-step5 caios/dashboard:latest
sudo docker compose -f compose/docker-compose.yml \
     --env-file configs/env/caios.env up -d --no-deps --force-recreate dashboard
```

Roughly ten seconds. No build, no network.

**Keep `--no-deps`**, here and in every section below. The dashboard depends
on PAPI and PAPI on Keycloak and Vault, and without it compose may recreate
those too — a recreated Vault is an empty one until `vault_init` has run
(D-76). The sections written before 2026-09-28 left it out and were
corrected that day.

## What is here

The convention is to keep the image you are replacing, so each file is the
undo for the deploy that came after it. As of 2026-09-28 the dashboard serving
is the step-5 build of `docs/demo-plan.md` and PAPI has patches `0001` to
`0023`; the two **bold** rows undo them.

| File | Image id | Git tag | What it is |
|---|---|---|---|
| `dashboard-pre-step5.tar` | `f9383c8bb8b7` | `dashboard-pre-step5` | **Served 2026-09-07 to 2026-09-28; the undo for the dashboard serving now.** See its section below. |
| `dashboard-t5a-scheme.tar` | `49b2ce97c89a` | — | T5, the scheme switch. The undo for T6. |
| `dashboard-t4-complete.tar` | `ae8e96ce0cc9` | `t4-complete` | T4 as finished, 2026-09-02. |
| `dashboard-t4-demo-unavailable.tar` | `8b9a6e0ede73` | `t4-demo-unavailable` | T3/T4's first deploy, 2026-09-02. |
| `dashboard-f3-home.tar` | `417647e928b6` | `f3-home` | Deployed 2026-09-01: the home page, F2's theme on every page, the platform-status feed off, and no-cache on the unhashed runtime assets. |
| `dashboard-pre-f1.tar` | `1c6dd451b6a4` | `pre-f1` | Served 2026-08-23 to 2026-09-01. Loads Roboto and the Material Symbols sets from Google, so it needs internet to render its icons. |
| `papi-pre-0023.tar` | `40cd48c206cc` | `papi-pre-0023` | **Patches `0001` to `0022`; the undo for the PAPI serving now.** |
| `papi-pre-0022.tar` | `2d8869680c74` | `papi-pre-0022` | Patches `0001` to `0021`: OSCAR services still answer with their job's log. |
| `papi-pre-0021.tar` | `20440189706a` | `papi-pre-0021` | Patches `0001` to `0020`: `posenet-tf` cannot start JupyterLab as root. |
| `papi-pre-0020.tar` | `9e386c49d511` | `papi-pre-0020` | Patches `0001` to `0019`. See its section below. |

## Why both a tarball and a git tag

They fail differently, which is the point.

The **git tag** is the durable record: `git checkout pre-f1 && bash
scripts/build-dashboard.sh` reconstructs the image from source, and that works
on any machine, forever. But it is a *rebuild* — it depends on `vendor/` being
at the pinned SHA and on npm resolving the same tree, so it reproduces the
image faithfully rather than bit-for-bit, and it takes minutes.

The **tarball** is the exact bytes that were serving. It cannot drift, needs no
network, and restores in seconds — but it lives only on this host and a
`docker image prune -a` would take the tag with it, which is why it is written
to a file rather than left as a tag alone.

On demo day you want the tarball. Six months from now you want the tag.

## `dashboard-t4-demo-unavailable.tar` — saved 2026-09-02

The image deployed for T3/T4: the demo-unavailable notice on the three profile
tabs, the EU Node and Infrastructure Manager deploy targets removed, and the
AI4EOSC strings a visitor reads replaced.

The image it replaced is `dashboard-f3-home.tar`, so that is the undo for this
deploy. Git tag `t4-demo-unavailable` records what it was built from.

```bash
sudo docker load -i rollback/dashboard-f3-home.tar
sudo docker tag caios/dashboard:f3-home caios/dashboard:latest
sudo docker compose -f compose/docker-compose.yml \
     --env-file configs/env/caios.env up -d --no-deps --force-recreate dashboard
```

## `dashboard-t5a-scheme.tar` — saved 2026-09-04

The image deployed through T5 and up to T6: the scheme switch (`requireHttps`
derived from the issuer, patch `0010`) and everything before it. **This is the
undo for the T6 deploy** — it has no registration console, no `/admin` route
and no waiting-room page.

Note it is also the image that makes `CAIOS_SCHEME` work in both directions, so
rolling back to it does not undo T5.

```bash
sudo docker load -i rollback/dashboard-t5a-scheme.tar
sudo docker tag caios/dashboard:t5a-scheme caios/dashboard:latest
sudo docker compose -f compose/docker-compose.yml \
     --env-file configs/env/caios.env up -d --no-deps --force-recreate dashboard
```

Rolling the dashboard back does **not** turn registration off. That is Keycloak
and the approval service, and it is a separate decision:

```bash
# stop accepting new signups (the live realm, not the template)
docker exec -i caios_keycloak /opt/keycloak/bin/kcadm.sh update realms/caios \
    -s registrationAllowed=false

# and/or stop the approval service
sudo docker compose -f compose/docker-compose.yml \
     --env-file configs/env/caios.env stop registration
```

Accounts already approved keep working either way: their access is a realm
role, and nothing in T6 is required to honour it.

## `papi-pre-0020.tar` — saved 2026-09-24

The first PAPI image kept here; until now only the dashboard had rollbacks.
It is the PAPI built on 2026-09-08, serving until patch `0020` was deployed:
patches `0001` to `0019`, with the module template's `ui` sidecar still pulling
`deepaas_ui:latest` from AI4EOSC's registry at every deployment. Git tag
`papi-pre-0020` records what it was built from.

**This is the undo for patch `0020`**, and rolling back reintroduces the fault
it fixed: a module deployment dies whenever that registry stalls.

```bash
sudo docker load -i rollback/papi-pre-0020.tar
sudo docker tag caios/papi:pre-0020 caios/papi:latest
sudo docker compose -f compose/docker-compose.yml \
     --env-file configs/env/caios.env up -d --no-deps --force-recreate papi
```

`--no-deps`, so the recreate touches PAPI alone. Without it compose may also
recreate Keycloak or Vault, and a recreated Vault is an empty one until
`vault_init` has run (D-76).

## `papi-pre-0023.tar` and `dashboard-pre-step5.tar` — saved 2026-09-28

Step 5 of `docs/demo-plan.md` changed both. **`papi-pre-0023.tar`** is PAPI with
patches `0001` to `0022` (tag `papi-pre-0023`): the Inference detail page still
shows the in-cluster MinIO address. **`dashboard-pre-step5.tar`** is the
dashboard built on 2026-09-07 from `166a638` (tag `dashboard-pre-step5`):
creation times in Europe/Paris under a "UTC" label, "Configure training" on
every deploy form, "AI4 …" category chips, and the two modules step 2 found
failing still clickable.

```bash
sudo docker load -i rollback/dashboard-pre-step5.tar
sudo docker tag caios/dashboard:pre-step5 caios/dashboard:latest
sudo docker compose -f compose/docker-compose.yml \
     --env-file configs/env/caios.env up -d --no-deps --force-recreate dashboard

sudo docker load -i rollback/papi-pre-0023.tar
sudo docker tag caios/papi:pre-0023 caios/papi:latest
sudo docker compose -f compose/docker-compose.yml \
     --env-file configs/env/caios.env up -d --no-deps --force-recreate papi
```

Either can go back without the other. The old PAPI ignores
`CAIOS_OSCAR_MINIO_URL`, and the old dashboard reads the same API.

The catalogue text is not in either image: `catalog/mirror/` is served live, so
undoing that half is a `git checkout` of the mirror and a PAPI restart. Do not
undo it by hand-editing categories back in: see D-84.
