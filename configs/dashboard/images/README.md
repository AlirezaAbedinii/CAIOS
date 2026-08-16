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
| `pacslab-logo.png` | Sidenav footer, beside the CAIOS mark | **Supplied, not generated.** PACS Lab's own logo — see below. |

## pacslab-logo.png

CAIOS is the project; **PACS Lab is the organisation behind it**, and its logo
sits beside the CAIOS mark at the bottom of the sidenav
(`patches/ai4-dashboard/0001-pacslab-logo.patch`).

It replaces upstream's `eu-flag.jpg`, which rendered there unconditionally. That
flag is a European funding acknowledgement — correct for AI4EOSC, and a claim
CAIOS cannot make: this is a Canadian project on Compute Canada under a Canadian
allocation.

**This file is not generated.** `scripts/make-brand-assets.py` draws the four
CAIOS images; it deliberately does not draw this one, because it is another
organisation's mark and an approximation of somebody's real logo is worse than
none. Save the official file here, ideally a square transparent PNG of at least
256x256 — it renders at 46px wide next to the 100px CAIOS logo.

Until these exist the build falls back to upstream artwork, so nothing is
blocked — but a walkthrough showing another project's logo defeats the point of
branding at all. `dashboard-logo.png` and `favicon.ico` are the two that matter.

Colours are not here; they live in `../theme/caios/variables.scss`.
