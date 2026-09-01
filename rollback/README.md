# Rollback

Saved container images, so a deployment that misbehaves can be undone in
seconds rather than rebuilt under pressure.

`*.tar` files are **gitignored** — they are 150–200 MB each. What *is* tracked
is this file and the git tag each image was built from, which is what makes
them reproducible.

## Restore an image

```bash
sudo docker load -i rollback/dashboard-pre-f1.tar
sudo docker tag caios/dashboard:pre-f1 caios/dashboard:latest
cd compose && sudo docker compose --env-file ../configs/env/caios.env up -d --force-recreate dashboard
```

Roughly ten seconds. No build, no network.

## What is here

| File | Image id | Git tag | What it is |
|---|---|---|---|
| `dashboard-f3-home.tar` | `417647e928b6` | `f3-home` | **Deployed 2026-09-01, and what is serving now.** The home page, F2's theme on every page, the platform-status feed off, and no-cache on the unhashed runtime assets. |
| `dashboard-pre-f1.tar` | `1c6dd451b6a4` | `pre-f1` | What served from 2026-08-23 until 2026-09-01, and **the one to roll back to**. Loads Roboto and the Material Symbols sets from Google, so it needs internet to render its icons. |

`f3-home` is here for the deploy after this one, not for undoing this one: the
convention is to keep the image you are replacing, and by the time anything
replaces `f3-home` this is the file that will undo it.

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
