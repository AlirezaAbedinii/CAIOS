# Security

## Reporting a vulnerability

Please do not open a public issue. Report it privately through GitHub:
**Security → Report a vulnerability**
([direct link](https://github.com/AlirezaAbedinii/CAIOS/security/advisories/new)).
Include what you found, where, and how to reproduce it.

That includes a credential you find anywhere in this repository or its history.

## How secrets are kept out

- Real values live only in `configs/env/caios.env` and other gitignored files.
  Committed files carry placeholders; `configs/env/caios.env.template` lists
  every variable.
- `scripts/check-secrets.sh` scans every commit with
  [gitleaks](https://github.com/gitleaks/gitleaks), refuses tracked key, certificate
  and env files, and looks for each real secret from `caios.env` by value in the
  tracked files and the whole history.
- It runs before every push once the hook is enabled
  (`git config core.hooksPath .githooks`), and in CI on every push and pull request.

A secret found in history is already public: rotate it first, then decide whether
to rewrite history.

## Scope

CAIOS is a research platform. Its public endpoints serve a demonstration and are
not intended for clinical or identifiable patient data.
