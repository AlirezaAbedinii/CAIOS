# Contributing

CAIOS deploys and brands the AI4OS stack; it does not fork it. Most changes are
configuration, a patch to upstream, or a script.

## Ground rules

- **Never edit `vendor/`.** It holds pinned upstream clones
  (`scripts/clone-vendor.sh`). Change behaviour with configuration in `configs/`
  or a numbered patch in `patches/`, which `scripts/apply-patches.sh` applies into
  `build/`. Each patch says why it cannot be configuration.
- **Never commit a secret.** Real values go in `configs/env/caios.env`, which is
  gitignored. See [SECURITY.md](SECURITY.md).
- **Automate, do not hand-fix.** A fix made over SSH is lost at the next rebuild;
  write the Ansible task or the script instead.
- **Record decisions.** Anything future readers would ask "why?" about goes in
  [docs/decisions.md](docs/decisions.md).

## Before you push

```bash
git config core.hooksPath .githooks   # once: the pre-push secrets check
bash scripts/run-tests.sh             # unit tests, offline, a few seconds
bash scripts/check-secrets.sh         # also run by the hook and by CI
```

Checks that need the live cluster are the `scripts/check-*.sh` smoke tests; the
[runbook](docs/runbook.md) says when to run which.

## Commits

One logical change per commit, with a subject that says what changed for the
platform (`area: what is now true`), and a body that says why.
