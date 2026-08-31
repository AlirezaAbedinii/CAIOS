# The CAIOS home page

CAIOS-owned Angular source, staged into `src/app/modules/home/` by
`scripts/build-dashboard.sh`. Nothing here is a copy of anything upstream, so
none of it drifts when `scripts/clone-vendor.sh` moves a SHA.

Stage F3 of `docs/frontend-plan.md`.

---

## Why it lives in `configs/` and not in a patch

F2 established the rule (D-46, D-49): anything CAIOS can own outright is a file
we stage, not a hunk we apply. A patch that *creates* files is drift-free in
theory, but it still has to be read, re-rolled and re-tested whenever anything
near it moves, and a 1,500-line patch is not reviewable.

So the split is:

| | Where |
|---|---|
| The page — components, styles, copy | here, staged verbatim |
| The English strings | `configs/dashboard/i18n/en.caios.json`, merged into upstream's `en.json` |
| The route that reaches it | `patches/ai4-dashboard/0004-home-route.patch` — nine lines in one file |

The patch is the only upstream edit, and it is small enough to re-roll by hand
in a minute if `app.routes.ts` ever moves.

---

## The one constraint that shapes everything else

**The page makes no HTTP request.** No PAPI call, no catalogue fetch, no
statistics query, no external font, no external image. It is markup, inline SVG
and CSS.

That is D-46, and it is not an aesthetic preference. Gotchas 18, 19 and 20 were
all cases of the dashboard reporting backend state incorrectly; a first page
with no backend has no such failure mode. Whatever the cluster is doing, the
first thing a visitor sees renders correctly.

`tests/test_home_page.py` asserts it — no `HttpClient`, no `fetch`, no absolute
URL, in any file in this directory.

---

## Who it is written for

**Medical and neuroscience academics, not engineers.** They have not heard of
the scheduler, they do not know what a control plane is, and a count of machines
tells them only how small the platform is this month.

So the page carries no infrastructure vocabulary and no size of the
installation, and `tests/test_home_page.py` enforces both against a word list
rather than against anyone's memory. Those words are easy to reintroduce by
accident, in a sentence that reads perfectly well to whoever wrote it. D-63.

There is also a word budget on the visible copy, and no em dashes.

## Layout

```
home.module.ts                    NgModule wrapper, matching every other module
home-routing.module.ts            one route, path ''
reveal.directive.ts               scroll reveal, and its way out
components/
  home/                           the page: three blocks, tokens, @font-face
  stage/                          six slides in two groups, and the timer
  slide-figure/                   the six drawings, one user space
```

Three blocks and nothing else: what this is, the stage, and a way in. The stage
is what used to be five stacked sections. D-64.

## One trap, twice

**A CSS property beats an SVG presentation attribute.** Do not set `transform`,
`text-anchor`, `fill`, `stroke` or `opacity` in a template when the stylesheet
styles them.

It cost an afternoon twice. `transform` on the hero tiles moved all twelve to
the origin and stacked them, and `text-anchor` on the chart caption centred it
on the left edge of the plot and ran it off the drawing. Both look exactly like
a rendering failure; neither logs anything. D-65, and there is a test.

Components are standalone and declared in the module's `imports`, which is how
upstream does it (see `src/app/modules/not-found/`).

## Typography

The page sets its own two faces — IBM Plex Sans and IBM Plex Mono — from
`configs/dashboard/fonts/`, files that have been staged and served since F1 and
until now used by nothing.

The `@font-face` rules are declared **here**, in a lazy-loaded component
stylesheet, and deliberately **not** by importing `theme/caios/_fonts.scss`.
That file also declares `Material Symbols Rounded`, and redeclaring the icon
face against our 65-glyph subset while `index.html` is still loading Google's
full one is precisely how F1 turned every icon into a word. The icon font is
not touched by anything in this directory.

The failure mode if a Plex file does not arrive is therefore bounded: this one
page falls back to the system sans, and the rest of the dashboard is unaffected.
