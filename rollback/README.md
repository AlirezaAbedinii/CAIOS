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
cd compose && sudo docker compose up -d dashboard
```

Roughly ten seconds. No build, no network.

## What is here

| File | Image id | Git tag | What it is |
|---|---|---|---|
| `dashboard-pre-f1.tar` | `1c6dd451b6a4` | `pre-f1` | The dashboard as it served on 2026-08-23, before self-hosted fonts. Loads Roboto and the Material Symbols sets from Google, so it needs internet to render its icons. |

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
