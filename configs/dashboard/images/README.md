# CAIOS dashboard artwork

Drop four files here. `scripts/build-dashboard.sh` copies them into the build as
`src/assets/images/caios/`, which the tenant configuration maps onto
`/assets/images/`.

| File | Where it appears | Notes |
|---|---|---|
| `dashboard-logo.png` | Top-left of every page | The single most visible branding element. Transparent PNG, roughly 200x50. |
| `favicon.ico` | Browser tab | Referenced directly by `index.html`. |
| `forbidden.png` | 403 page | Rarely seen; placeholder is fine. |
| `not-found.png` | 404 page | Rarely seen; placeholder is fine. |

Until these exist the build falls back to upstream artwork, so nothing is
blocked — but a walkthrough showing another project's logo defeats the point of
branding at all. `dashboard-logo.png` and `favicon.ico` are the two that matter.

Colours are not here; they live in `../theme/caios/variables.scss`.
