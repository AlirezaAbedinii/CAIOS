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

## `header_image.webp` — the home page illustration

**Derived, not edited by hand.** The supplied artwork lives in `source/` and
the asset the dashboard serves is produced from it:

```bash
demo/.venv/bin/python scripts/make-header-image.py configs/dashboard/images/source/<file>
```

That script does three things, and the first is the one you would otherwise
forget. It **keys out the background**, because the illustrations arrive on
their own cream, which is close to the page's paper but not the same, so
dropped in as supplied they read as a rectangle pasted onto the page. It
**sizes the image for the slot**, which the browser gives about 320 CSS pixels,
so 640 is exactly 2x and anything beyond it is bytes nobody sees. And it
**writes WebP**, which for dense line work is several times smaller than a PNG
of the same drawing.

The page references the file directly, so a missing copy is a broken picture at
the top of the first page anybody sees, behind nginx's HTTP 200. It is in
`REQUIRED_IMAGES` for that reason, and `scripts/check-home-page.sh` reads the
file type of what the running dashboard serves rather than its status code.

`tests/test_home_page.py` asserts three things about it: that it carries an
alpha channel, so nobody ships a version whose background was never removed;
that it stays under 400 KB; and that a source file exists to rebuild it from.

### Replacing it

Put the new artwork in `source/`, delete the one it supersedes in the same
commit, and run the script. Then re-read two things: the `width` and `height`
on the `<img>` in `home.component.html` if the aspect ratio changed, and
`HOME.FIGURE.HERO-ALT` in `configs/dashboard/i18n/en.caios.json`, which
describes what the picture shows.

Superseded sources are deleted rather than kept. They are a few megabytes each
and git history keeps them recoverable.
