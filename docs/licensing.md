# Licensing

What CAIOS is licensed under, what it inherits, and the one licensing problem
the platform actually has.

Written for checklist item 6 — *"make sure there are no licensing problems
regarding Europe and AI4OS"*. Verified against the upstream repositories at the
commits pinned in `scripts/clone-vendor.sh`.

---

## The short answer

**There is no licensing problem with AI4OS, and being a European project creates
no obligation and no restriction of any kind.**

Every upstream component CAIOS deploys is **Apache License 2.0**:

| Repository | Licence |
|---|---|
| `ai4os/ai4-papi` | Apache-2.0 (ships a `NOTICE`) |
| `ai4os/ai4-dashboard` | Apache-2.0 |
| `ai4os/ai4-ansible` | Apache-2.0 |
| `ai4os/ai4-nomad_tests` | Apache-2.0 |

Apache-2.0 grants a **worldwide, royalty-free, irrevocable** licence to use,
reproduce, modify, distribute and sublicense, **including commercially**, with
no territorial limit and no field-of-use restriction. It also carries an express
patent grant from every contributor, which runs in our favour rather than
against us.

Nothing about the licensor being European, EU-funded, or an EU project changes
any of that. There is no clause conditioning the grant on geography, on
membership, or on funding source.

## What Apache-2.0 does require

Three obligations, all satisfied as of 2026-09-02:

1. **Retain notices.** Copyright, patent, trademark and attribution notices must
   survive redistribution. Our patches modify Apache-2.0 files and the container
   images redistribute them, so this applies. `vendor/` is never edited and the
   upstream `LICENSE` files travel with the source.
2. **State changes.** Modified files must carry prominent notices saying they
   were changed. `patches/` holds every modification as a separate patch pinned
   to its upstream commit, and `patches/README.md` says what each one changes and
   why. `NOTICE` names that directory as this project's statement of changes.
3. **Propagate `NOTICE`.** `ai4-papi` ships one. Its content is reproduced in
   this repository's `NOTICE`, alongside our own.

There is **no copyleft obligation.** Apache-2.0 does not require CAIOS to be
open source, and does not extend to work that merely runs on the platform.

## Our own licence

CAIOS is released under Apache-2.0 — the same licence as the stack it deploys.
`LICENSE` is the standard text with our copyright in the appendix; it differs
from upstream's by exactly one line.

Choosing the same licence is deliberate. It removes any question of
compatibility, and it keeps open the option of contributing a patch back
upstream without a relicensing conversation.

## The real problem, and it is ours

**Every module in the marketplace displays `MIT` as its licence, whatever its
actual licence is.** Found in a browser on 2026-09-02.

The cause is a chain, and the first link is not optional:

- `IS_PROD` must be `false` — gotcha 1. PAPI's official image sets
  `ENV IS_PROD=True`, and left alone PAPI refuses to start over missing Harbor,
  Jenkins, provenance and LiteLLM tokens.
- `conf.py` derives `IS_DEV = not IS_PROD`, so `IS_DEV` is true.
- `utils.get_github_info()` short-circuits on `IS_DEV` and returns mock data:
  `{"created": "1970-01-01", "updated": "1970-01-01", "license": "MIT"}`.
- `catalog/common.py` then writes that over the module's real metadata:

  ```python
  metadata["dates"]["created"] = gh_info.get("created", "")
  metadata["dates"]["updated"] = gh_info.get("updated", "")
  metadata["license"]          = gh_info.get("license", "")
  ```

Verified against `/v1/catalog/modules/detail`: all nine modules report `MIT` and
`1970-01-01`.

**Why it matters.** `ai4os-yolo-torch` wraps Ultralytics YOLO, which is
**AGPL-3.0** — a strong copyleft licence with obligations that MIT does not
have. Presenting it as MIT on our own marketplace misstates a third party's
terms to our users, and could lead someone to use it in a way its licence does
not allow.

This is not inherited from AI4OS. Upstream runs with `IS_PROD=True` and a GitHub
token, so the path never fires for them. It is a consequence of how *we* have to
run PAPI, and it is ours to fix.

**Fix:** stop the mock value winning over real metadata. A module's own
`ai4-metadata.yml` states its licence, and that should be preferred whenever
GitHub information is unavailable. Tracked as part of T3 in
`docs/finalization-plan.md`.

## What this notice does not cover

The catalogue lists containerised models that CAIOS neither authored nor
licensed. Each carries its own terms:

- **Marketplace modules** — per-repository licences, several not Apache-2.0.
- **AI4Life loader models** — from bioimage.io, per-model licences. The
  underlying dataset used in the federated demo is public and CC BY 4.0 (D-07).
- **LLM tool models** — from Hugging Face, with their own licences and
  acceptable-use terms.

Deploying a model through CAIOS does not relicense it.

Two smaller items, noted for completeness rather than as problems: our
modules-catalog fork carries no licence file, because it holds only submodule
pointers and no code; and the CAIOS brand and artwork are not covered by the
software licence.

## Attribution on the platform

Two AI4OS mentions in the interface are deliberate and are staying — the sidenav
acknowledgement and the home page's closing line. Apache-2.0 asks for
attribution, and these are it.

Every *other* AI4OS or AI4EOSC string a visitor can read is unintentional
upstream residue. Those are tracked in `docs/finalization-plan.md` and
enforced against an allowlist by `scripts/check-branding.sh`.
