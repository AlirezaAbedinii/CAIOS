# Dashboard visual design — the plan

**Stage 7 of the CAIOS build, and the first one that is not load-bearing.** The
MVP works, federated learning works, the private language model works. This
makes the dashboard look like it was built by people who knew what they were
doing, without changing what any of it does.

**Status: F1 SHELVED after a bad deploy. F2 built and verified 2026-08-24, not
deployed. F3 built and verified 2026-08-29, not deployed. F0 outstanding.**

F4's work landed inside F3 rather than after it: motion that has no
reduced-motion path is not shippable (D-48), so the entrance sequence and the
scroll reveal were written with theirs in the same commit. What remains of F4
is animating the schematic further, and it is optional.

The governing constraint, stated once so every decision below can be checked
against it: **the platform is the deliverable and this is not.** Nothing in this
plan is worth a bug in the marketplace, the deployment table, or the LLM
catalogue. Where a choice is between "better looking" and "cannot break the
demo", it goes to "cannot break the demo" every time.

---

## Scope, as decided

| | Decision |
|---|---|
| **Reach** | Theme tokens + a new home page. Feature pages are not touched. |
| **Direction** | Instrument panel — precision-scientific — with an animated node graph confined to the home page hero. |
| **Media** | Inline animated SVG/CSS. No video. |
| **Budget** | Four engineer-days, hard stop. |

UX does not change. Every route, every click path, every label stays where it
is. This is a *UI* pass: the same product, better presented.

### What "instrument panel" means in practice

Restrained palette, hairline rules instead of heavy borders, monospace for every
number the reader might compare, and typography carrying the hierarchy rather
than boxes and colour. The reference is an imaging workstation or a lab
instrument console, not a SaaS marketing site. Dense and calm.

This is deliberately *not* "more complicated". For an audience of medical
researchers assessing a grant, visual busyness reads as effort spent on the
surface instead of the substance. The target is **considered**.

### The Canadian and medical signals

Not a maple leaf. The honest version of both signals is the same sentence, and
it happens to describe the headline feature:

> Train on hospital data that never leaves the hospital — or the country.

Data sovereignty is Canadian, medical, and technically true of what this
platform actually does. It carries the hero. Supporting signals are a Digital
Research Alliance credit in the footer and the platform's own vocabulary —
connectomics, DICOM, bioimage.io, three hospital sites — in place of stock
medical imagery.

---

## Two faults that already exist

Both were found while reading the build for this plan. Both are worth fixing
whatever happens to the rest of it.

### R-27 · The theme asks for a font that is never loaded

`configs/dashboard/theme/caios/_material.scss:93` sets Material's font stack to
`'Raleway', Arial, Helvetica, sans-serif`. Nothing in the dashboard ever fetches
Raleway — `src/index.html` loads Roboto and the two Material Symbols sets, and
that is all. So the stack falls through to **Arial**.

`src/styles.scss:5` separately sets body text to `Roboto`, which *is* fetched.

The result on screen today: Material components — buttons, cards, tables, form
fields — render in Arial, while body copy renders in Roboto. Two unrelated
typefaces on every page. It is not a design choice, it is a fallback, and it is
a large part of why the dashboard reads as unfinished.

### R-28 · Every font and every icon is fetched from Google

`src/index.html` pulls all four typefaces from `fonts.googleapis.com`, with
preconnects to `fonts.gstatic.com`.

Material icons are a **font**: the glyphs arrive as a typeface, and each icon is
a ligature — the markup says `<mat-icon>menu</mat-icon>` and the font draws a
hamburger. If that font does not load, the browser renders the ligature source
text instead. The sidenav toggle becomes the literal word `menu`. The section
heading becomes `dashboard`. Every icon in the application degrades to a word.

So on a private subnet, an air-gapped demo machine, or a conference network that
fails closed, the dashboard breaks in a way that looks catastrophic and has
nothing to do with the platform.

It is also a fifth third-party leak, in the same family as the four in gotcha 6
and the same objection patch `0002` raised about `raw.githubusercontent.com`:
the user's browser announcing our demo traffic to someone else's server on every
page load.

`scripts/check-branding.sh` checks for the analytics beacon and the model-list
fetch. It does not check for this one. Stage F1 adds that check.

---

## The mechanical finding that shapes the plan

`configs/dashboard/angular-configurations.json` is ours, and it owns the
`styles` array that `scripts/build-dashboard.sh` merges into `angular.json`:

```json
"styles": [
    "src/theme/caios/variables.scss",
    "src/styles.scss",
    ...
]
```

Stylesheets later in that array win over earlier ones at equal specificity. Our
theme currently loads **first**, which is why it cannot override anything
`src/styles.scss` sets — including the body font.

Adding `src/theme/caios/overrides.scss` **after** `src/styles.scss` gives us a
sheet that wins, in a file we own, listed in a config we own.

**The consequence: the entire typography and token pass needs zero patches.**
No upstream file is edited, so there is nothing to drift when
`scripts/clone-vendor.sh` moves a SHA. Stages F1 and F2 add no maintenance
liability at all.

The `assets` array already globs all of `src/assets/`, so self-hosted font files
dropped in `src/assets/fonts/` are published with no config change either.

---

## Reversibility

Asked for explicitly, and the existing build already provides most of it.

| Change | Lives in | To undo |
|---|---|---|
| Fonts, tokens, type scale | `configs/dashboard/theme/caios/` | `git checkout` that directory |
| Style load order | `configs/dashboard/angular-configurations.json` | `git checkout` one file |
| Home page | `configs/dashboard/home/` + `configs/dashboard/i18n/` | `git checkout` those directories |
| Route change | `patches/ai4-dashboard/0004-home-route.patch` | `rm` the patch — `/` redirects to the catalogue again |

`vendor/` and `build/` are gitignored and rebuilt from source every run, so
there is no state to clean up. **The unit of reverting is one file**, and the
home page can be removed without touching the theme or vice versa.

Each stage is one commit. Each stage is independently revertable. A stage that
does not look better than what it replaced gets reverted rather than defended.

---

## Definition of done

1. The dashboard renders identically with the network unplugged.
2. One typeface family, deliberately chosen, everywhere.
3. `/` is a home page that states what CAIOS is, who it is for, and that data
   stays in Canada — and it makes **no** call to PAPI.
4. Every animation has a `prefers-reduced-motion` path that renders the final
   state immediately.
5. `check-dashboard.sh`, `check-branding.sh` and `pytest tests/` all pass.
6. Screenshots of every page, before and after, at 1440 and 768 px.
7. No change to any route path, click target, or label outside the new page.

---

## How this is tested

Frontend work has a weaker test story than the infrastructure stages did, and
pretending otherwise would be dishonest. There is no assertion for "looks
right". What can be checked mechanically:

| Check | Catches |
|---|---|
| `scripts/check-branding.sh` (extended in F1) | Third-party font fetch reintroduced |
| `pytest tests/test_patches.py` | The home page patch stopped applying |
| `ng build --configuration caios-production` | SCSS errors, missing assets, bundle failure |
| Screenshot diff against the F0 baseline | Any feature page changed when it should not have |
| Manual: DevTools offline mode | R-28 has actually been fixed |
| Manual: OS reduce-motion setting | Animations degrade correctly |

The screenshot baseline is the real regression test here. It is the only thing
that will catch a token change quietly wrecking a page nobody thought to look
at.

---

## Stage F0 — Look at it, and photograph it · half a day · changes nothing

**This stage is not optional and it goes first.**

`CLAUDE.md` already lists a browser look at the LLM catalogue page as
outstanding. If the redesign lands before that look happens, no fault found
afterwards can be attributed: it will be impossible to tell whether a broken
page was broken already or broken by this work.

### Work

1. Bring the dashboard up and open every page in a real browser: catalogue
   (modules, tools, LLMs), a module detail, the deploy form, deployments,
   statistics, profile, and both error pages.
2. Screenshot each at 1440 px and 768 px into `docs/screenshots/before/`.
3. Write down everything that looks wrong. Separately from this plan — these are
   pre-existing faults and some may be worth fixing on their own merits.
4. Specifically confirm or refute R-27 and R-28 by eye and in DevTools:
   - Network tab, filter `fonts.g` — are there four external requests?
   - Offline mode, hard reload — do icons become words?
   - Inspect a button, check computed `font-family` — is it Arial?

### Gate

Every page photographed. R-27 and R-28 confirmed or corrected in this document.
No code changed.

---

## Stage F1 — Serve our own fonts · half a day · fixes R-27 and R-28

The smallest change with the largest effect, and it stands on its own even if
every later stage is abandoned.

### Work

1. Choose the pairing. The direction calls for a technical sans for the
   interface and a monospace for numerics. Candidates are recorded in F1's
   "What it found" section once seen on screen — the choice is made in a
   browser, not from a specimen sheet.
2. Download the WOFF2 files, self-hosted under `src/assets/fonts/`. WOFF2 is the
   compressed web font format every current browser reads; a full family is
   typically 30–80 KB per weight, so we subset to the weights actually used.
3. Self-host the Material Symbols font the same way. This is the half that fixes
   the icons, and it is the half that matters on demo day.
4. `@font-face` declarations with `font-display: swap` in the new
   `overrides.scss`.
5. Patch `src/index.html` to drop the four Google `<link>` tags and the two
   preconnects. **This is the one patch F1 needs** — `index.html` is upstream.
   It is a pure deletion, which is the least drift-prone kind of patch there is.
6. Extend `scripts/check-branding.sh` with a section asserting the built bundle
   contains no `fonts.googleapis.com` or `fonts.gstatic.com` reference.

### Tests

- `check-branding.sh` fails before the change, passes after.
- DevTools offline, hard reload: every icon still an icon.
- Computed `font-family` on a Material button is the chosen face, not Arial.

### Gate

The dashboard renders completely with the network unplugged. One typeface
family across Material components and body copy.

### What it found — run on 2026-08-23

**Passed.** IBM Plex Sans + IBM Plex Mono, chosen from a specimen rather than a
name. Image `caios/dashboard:f1-fonts` builds clean; `caios/dashboard:latest`
deliberately untouched, so nothing deployed changed.

Three things the plan had not accounted for.

**The icon font is 5,222 KB, so subsetting was mandatory rather than tidy.**
The plan assumed self-hosting was a copy operation. The full Material Symbols
Rounded variable face is over five megabytes — which is also what every visitor
downloads from Google today. Subset to the 65 icons in use, with all four axes
intact because the dashboard varies all four, it is 91 KB.

That forced a second decision. Icon names are *heavily* dynamic — ten
components take the name as an input, 16 of 150 `<mat-icon>` tags are
interpolated — so a hand-written subset list would eventually miss one, and a
missing glyph renders as a word. The list is derived from source instead, and
`fetch-fonts.sh --check` is what the test runs, so there is one copy of the
extraction rather than two that can disagree (D-47).

**A fourth font was being loaded and never used.** `index.html` pulled Material
Symbols *Outlined* as well as *Rounded*. Nothing references Outlined —
`styles.scss:78` and `app.config.ts:131` both name Rounded. One of the four
requests on every page load was pure waste.

**Two bugs in this stage's own tooling, both silent.** The generator wrote
`font-weight: 300700` where a variable font needs `300 700` — not a valid
weight, so the rule is dropped and the face never applies while the file still
downloads and the CSS still parses. And the mono was fetched as four static
cuts at 299 KB because the request asked for a weight *list* rather than a
variable *range*. Both are now asserted in `tests/test_icon_subset.py`.

One thing that came out better than planned: a `@font-face` rule costs nothing
until something uses the family, so shipping IBM Plex Mono now is free. F2 puts
numerals on it without touching this pipeline.

Measured, serving from the built image:

| | before | after |
|---|---|---|
| Font payload | 5,447 KB | **221 KB** |
| Requests to Google | 4 | **0** |
| Typefaces on screen | Arial + Roboto, unintended | IBM Plex Sans |
| Renders offline | no — icons become words | **yes** |

And the trap that justifies how `check-branding.sh` tests this: a request for
`/assets/fonts/missing.woff2` returns **HTTP 200 with an HTML document**. A
status code proves nothing here, so the check reads the file type.

---

## Stage F2 — The token pass · one day · no patches

A **design token** is a named value used everywhere instead of a literal —
`--font-md: 16px` rather than `16px` scattered through forty files. The theme
already has some; they are thin, and the sizes are a flat list rather than a
scale.

### Work

1. **Type scale.** Replace the six flat sizes with a ratio-based scale, and give
   each step a line-height and weight. Line-height is the largest single lever
   on whether dense data reads as calm or cramped.
2. **Spacing scale.** One base unit, multiples of it, nothing off-grid.
3. **Depth.** Replace Material's default drop shadows with hairline borders plus
   a single very soft shadow. Instrument panels use rules, not floating cards.
4. **Radii.** One value, applied consistently. Mixed corner radii is the single
   most common tell of an unconsidered interface.
5. **Transitions.** 150–200 ms on hover and focus states. Instant state changes
   feel cheap; anything over ~300 ms feels sluggish.
6. **Focus rings.** Visible, high contrast, never removed. Keyboard navigation
   is an accessibility requirement and researchers do use it.
7. **Palette**, treated as two separate sets — see R-29 below.

All of it in `configs/dashboard/theme/caios/`, plus the new `overrides.scss`
appended to the `styles` array. No upstream file touched.

### Tests

- `ng build --configuration caios-production` succeeds.
- Screenshot every page again; diff against the F0 baseline. Differences are
  expected everywhere — the check is that they are *only* stylistic, and that no
  page lost content, gained a scrollbar, or reflowed into a broken layout.
- Contrast-check every text/background pair against WCAG AA (4.5:1 for body).

### Gate

Every page still renders correctly at 1440 and 768 px. Status colours verified
unchanged in meaning. Nothing in the deployment table reads differently.

### What it found — run on 2026-08-24

**Built and verified in a browser against live data. Not deployed.** Image
`caios/dashboard:f2-tokens`; the running dashboard is untouched.

The method changed, and that is the main thing to record. F1 was designed
blind and shipped a fault no test could see. F2 was done with a browser
attached: read the real DOM for selectors, measure the real columns, then
**inject the candidate CSS into the live page and photograph it** — real data,
real widths, zero deployment risk. Every claim below was measured in that
browser rather than reasoned about.

What the browser showed that reading could not:

**R-27 confirmed live.** Table cells computed to `font-family: Raleway` — a
face nothing loads — while `body` computed to Roboto. The mismatch was not
theoretical. Fixed by naming Roboto in `_material.scss`, which needs no new
bytes because `index.html` already fetches it.

**The column widths decided the type size.** `containerName` is a flexible
column with room to spare; `creationTime` is **fixed at 200 px**. A monospace
sets wider than a proportional face at the same size, so mono at 14 px risked
`05:14:31 23-08-2026` overflowing. Set at 13 px it measures clear, confirmed
with `scrollWidth > clientWidth` on the real cell. Guessing would have got this
wrong in one direction or the other.

**Real selectors, not invented ones.** Angular Material emits
`mat-column-containerName`, `mat-column-creationTime`, `mat-column-gpus`. Those
are what the monospace targets. A first guess at `td:nth-child(3)` would have
been brittle and wrong — the tables use `MAT-CELL` elements, not `td`.

**Upstream puts `mat-elevation-z8` on its tables** — a three-layer drop shadow
intended for a floating dialog, on data that is not floating. Replacing it with
a hairline is the single largest visual change in this stage.

Verified after the change: **no horizontal overflow** on either page, no cell
overflowing its column, status pills and action icons untouched.

### Risks carried out of F2

**R-35 · The theme is global; verification was not.** `overrides.scss` applies
to every page. Deployments and Modules were checked in a browser. Statistics,
LLMs, Inference, Try-me, Batch training and Profile were **not**. Nothing in
the stage is structural, so the expected worst case is cosmetic — but "expected"
is doing work in that sentence, and F1 is why it should not be trusted. Check
the remaining pages before deploying.

**R-36 · The monospace columns are bound to Material's class names.** If
upstream renames a column, the rule stops matching and those cells quietly
revert to proportional text. Cosmetic, silent, and worth knowing rather than
rediscovering.

**R-37 · Two `!important` declarations.** The header colour and the elevation
override both need it to beat Material's own specificity. They are scoped to
one class each, but every `!important` makes the next override harder.

**R-29 stands, untouched.** The status palette was deliberately not changed —
see the closing comment in `overrides.scss` for why that is the highest-
consequence change available in a theme pass and the only one producing no
error.

---

## Stage F3 — The home page · one day · one nine-line patch

### Work

**Revised on 2026-08-27, before any of it was written.** The plan said "one
additive patch" and meant a patch that creates the whole module. F2's finding
made that unnecessary: `configs/dashboard/` is ours, `scripts/build-dashboard.sh`
stages it, and a patch is only needed where an *upstream* line has to change.

So the split is:

| | Where it lives | Drift |
|---|---|---|
| The page — components, styles, copy | `configs/dashboard/home/`, staged verbatim | none |
| The English strings | `configs/dashboard/i18n/en.caios.json`, deep-merged into upstream's `en.json` | none |
| The route that reaches it | `patches/ai4-dashboard/0004-home-route.patch` | nine lines in one file |

Two things this buys. A 1,500-line patch is not reviewable and would have to be
re-rolled by hand every time anything near it moved; staged files are read as
ordinary source. And `en.json` is a 900-line upstream file that changes whenever
any page gains a label, so a patch against it would break for reasons that have
nothing to do with the home page — the merge cannot.

D-46 already says this; F3 is the first stage where it applies to application
code rather than to a stylesheet.


1. New lazy-loaded module at `src/app/modules/home/`. **Lazy-loaded** means its
   code is only downloaded when someone visits `/` — Angular splits it into a
   separate bundle, so it cannot slow down any other page.
2. Change the `''` redirect in `app.routes.ts` from `/catalog/modules` to
   `home`. One line.
3. Point the sidenav logo's `routerLink=""` at the same place — it already
   resolves through the redirect, so this needs no change, but confirm it.
4. Content, in order:
   - **Hero** — the data-sovereignty thesis, the CAIOS wordmark, the node graph
     (F4 animates it; F3 ships it static).
   - **What this is** — two short paragraphs. An AI platform for medical and
     neuroscience research, running on Canadian infrastructure.
   - **Three pillars** — curated marketplace, federated learning, private
     language models. Each linking to the page that does it.
   - **Who it is for** — the researcher's path, in their vocabulary.
   - **Footer credits** — PACS Lab, Digital Research Alliance, AI4OS upstream.
5. All strings through `@ngx-translate`, matching how every other page does it
   — but authored in `configs/dashboard/i18n/en.caios.json` and merged into
   `src/assets/i18n/en.json` at stage time, rather than patched into it.

### The constraint that makes this safe

**The home page makes no HTTP request.** No PAPI call, no catalogue fetch, no
statistics query. It is static content and inline SVG.

This means it is structurally incapable of showing an error, a spinner, or an
empty state. Whatever the cluster is doing, the first page of the demo renders
correctly. Given that gotchas 18, 19 and 20 were all cases of the dashboard
lying about backend state, a landing page with no backend is worth more than it
sounds.

### Tests

`tests/test_home_page.py` carries the mechanical half, and it exists because
this page has more that can be checked than "looks right" suggests:

| Assertion | What it catches |
|---|---|
| No `HttpClient`, `fetch`, `XMLHttpRequest` or PAPI service in the module | D-46 quietly abandoned by a later change that wants a live figure in the hero |
| No absolute `http(s)://` in any `src`, `href` or `url()` | a sixth third-party leak, in the family of gotcha 6 |
| No `@font-face` for `Material Symbols Rounded` | **F1's exact failure**, reintroduced from a page-level stylesheet |
| Every `HOME.*` key used exists, and every key defined is used | ngx-translate renders a missing key as the key itself, in display type, with no error |
| `AI4OS` appears once | credit drifting into co-branding |
| The printed counts equal the files they count | the easiest thing on the platform to check, and the worst to be wrong |
| The route patch touches exactly one upstream file | the architecture above, as an assertion |

And, still needing a person:

- `pytest tests/test_patches.py` — the new patch applies to pinned upstream.
- Every other route still resolves; `/catalog/modules` unchanged.
- Screenshot diff: no feature page differs from its F2 state.
- Confirm in DevTools Network that loading `/` issues zero XHR requests.

### Gate

`/` is the home page. Nothing else changed. Removing the patch restores the old
redirect exactly.

### What it found — run on 2026-08-29

**Built and verified in a browser against the built image (D-49). Not
deployed.** Image `caios/dashboard:f3-home`; `caios/dashboard:latest` is
untouched, so nothing running changed.

The page came out as seven sections in the order the argument runs — identity,
who it is for, the three capabilities, the depth of control, the platform in
use, provenance, and the catalogue. Five things the plan had not anticipated.

**The three pillars became one console, and that was the largest decision on
the page.** Three cards for serverless inference, federated learning and
private language models would have said, silently and to everyone, that these
are three products. So there is one schematic of the cluster — the machines in
`docs/infrastructure.md`, drawn to scale — and choosing a capability re-lights
the path through it. Nothing is removed between states, only dimmed, because it
is the same cluster either way. The data marks inside the site nodes are drawn
in every state and never move; that restraint *is* the federated argument, and
it needs no caption.

**The schematic was illegible, and only a browser could have said so.** Drawn
at a nominal 980x440 and left to scale into its column, every label in it
rendered at about six pixels. The geometry is now laid out for the width the
console actually gives it — roughly 640 CSS pixels — with the edge and the
control plane merged into one box, because saying they are separate machines
cost a third of the width for a distinction that matters to whoever operates
the cluster and not at all to whoever is reading the page. Confirmed by
measuring every label's bounding box against its own rectangle in the live
page, not by eye.

**The scroll reveal was one browser away from a blank page.** In the browser
this was verified in, `IntersectionObserver` was constructed, given an element
filling the viewport, and never called back — not even the initial report a
working implementation always sends. Every armed section therefore stayed at
opacity 0, and every test passed. Now: the hidden state is applied by the
directive rather than the stylesheet, `reduce` skips arming entirely, and a
1.5 s timeout abandons the effect if nothing has reported anywhere. **D-59**,
and `tests/test_home_page.py` asserts all three.

**F1's fault had a second way in.** The page needed IBM Plex, which is exactly
the family F1 staged and never used. Importing `theme/caios/_fonts.scss` to get
it would also have declared `Material Symbols Rounded` against our 65-glyph
subset while `index.html` still loads Google's complete one — the F1 failure,
reintroduced from a page-level stylesheet, affecting the whole application. The
two text faces are declared here instead and the icon family is not named at
all. **D-61**, with a test.

**There is more that can be checked mechanically than a landing page suggests.**
Eleven assertions, listed above. The two that will earn their keep are the
translation-key check in both directions — ngx-translate renders a missing key
as the key itself, in display type, with no error — and the inventory counts,
which turn "we curated the catalogue and forgot the home page" into a failing
test rather than a wrong number on the first page anybody sees.

### What is still outstanding

- A **screenshot pass** at 1440 and 768 px into `docs/screenshots/after/`, and
  a diff against the F0 baseline to confirm no feature page moved. The theme is
  untouched by this stage, so the expectation is zero difference.
- The **narrow layout** was verified by injecting the breakpoint's rules into
  the live page and shrinking the content column, because the browser available
  here would not resize its viewport. The reflow is correct; it has not been
  seen at a real 768 px.
- The **entrance and reveal animations** were verified as CSS and by their
  final state. They have not been *watched* — the same browser that would not
  report intersections is not the place to judge whether motion feels right.
- R-28 is still live and was seen again here: on a cold load the icon font
  arrives from Google as a **3.96 MB** download, and every icon renders as its
  own name until it does. That is F1's business, not F3's, but it is the first
  thing a visitor sees and it is worth restating.

---

## Stage F4 — Motion · half a day

Added last, deliberately. Motion on top of a design that is not yet right hides
the problem rather than fixing it.

### Work

1. **The node graph.** Three site nodes and a server node. Weights travel from
   sites to centre and back; the data glyphs at each site never move. That
   restraint *is* the point being made — it is the federated argument drawn
   rather than stated.
2. **Entrance.** A short staggered reveal on load. One orchestrated sequence,
   not scattered effects.
3. **Scroll reveal** on the pillars, subtle, using `IntersectionObserver` — the
   browser API that reports when an element enters the viewport, and the cheap
   way to do this without listening to every scroll event.
4. `@angular/animations` is already a dependency. **No new libraries.** No GSAP,
   no Lottie — each would add bundle weight and a supply-chain surface for
   effects that CSS handles.

### Reduced motion is written at the same time, not after

Browsers expose `prefers-reduced-motion` for users with vestibular disorders and
motion sensitivity. Ignoring it is a real accessibility defect, and with a
medical audience it is the kind of thing that gets noticed.

Every animation gets its `@media (prefers-reduced-motion: reduce)` branch in the
same commit that introduces it, rendering the final state immediately. Not a
follow-up task — retrofitting this reliably misses cases.

### Tests

- OS reduce-motion enabled: page renders complete and still, no movement.
- Animation pauses when offscreen.
- No layout shift as animations run.

### Gate

Motion serves the federated argument. Reduced-motion path verified by setting
the OS preference, not by reading the CSS.

---

## Stage F5 — Rebuild, regress, rehearse · half a day

### Work

1. `scripts/build-dashboard.sh` clean, from scratch.
2. Full screenshot pass into `docs/screenshots/after/`, diffed against F0.
3. `check-dashboard.sh`, `check-branding.sh`, `pytest tests/`.
4. Offline check one more time on the built image, not the dev server.
5. Walk `docs/demo-script.md` beat by beat in the browser. Beat 1 now opens on a
   home page it does not mention — update the script.
6. Record D-45 onward in `docs/decisions.md`; update `docs/progress.md` and
   `CLAUDE.md`.

### Gate

Every check green. Demo script matches what the browser does.

---

## Risks

### R-29 · The status palette carries meaning, and recolouring it breaks the meaning

`--good-value`, `--neutral-value`, `--bad-value`, `--success-green`,
`--warning-orange` and `--neon-red` are not decoration. They are how a user
tells a running deployment from a failed one.

A palette pass that treats all colour variables as one set will change them, the
pages will still render, every check will pass, and a failed deployment will
stop looking failed. This is the highest-consequence risk in the plan precisely
because it produces no error.

**Mitigation:** the palette is two sets. *Brand* colours are free to change.
*Semantic* colours change only deliberately, only for contrast, and never in
hue. F2's gate requires looking at a deployment table with a real error in it.

### R-30 · Motion without a reduced-motion path

**Mitigation:** written in the same commit, gated by testing with the OS
preference actually set.

### R-31 · The home page becomes a second thing that can fail

**Mitigation:** static only, zero HTTP requests, verified in DevTools at F3's
gate. A page with no data source has no failure mode beyond a build error, and a
build error is loud.

### R-32 · Layout shift as fonts and images load

Content jumping while a page settles looks cheap and makes clicks land on the
wrong target. **Mitigation:** self-hosted fonts (F1) remove the network race;
inline SVG has no load delay; any raster image gets explicit dimensions.

### R-33 · Patch drift

Every patch breaks when upstream moves the lines it targets.

**Mitigation:** the architecture above reduces this to two patches — a pure
deletion in `index.html`, and one additive patch that creates new files and
changes a single route line. `tests/test_patches.py` turns drift into a failing
test rather than a failed build on demo day.

### R-38 · A sixth third-party leak, and this one can put another project's words on our screen

**Found on 2026-08-29 while checking that the home page issues no request of its
own.** It does not. The application shell around it makes three, and one of them
is new to this list:

```
GET https://api.github.com/repos/AI4EOSC/status/issues?state=open&…
```

`src/app/shared/services/platform-status/platform-status.service.ts` fetches
**AI4EOSC's** GitHub issue tracker from the visitor's browser on every page
load, three times over — once for a popup, once for the notifications bell, once
for a Nomad-maintenance banner on the deployments list.

Two problems, and the second is worse than the leak.

1. It is the same objection as the analytics beacon, the model catalogue and the
   Google fonts: our demo traffic announced to somebody else's server, from a
   page that is meant to be self-contained.
2. **It renders another project's operational notices as ours.** An issue
   labelled `dashboard-popup` in the AI4EOSC status repository becomes a popup
   in CAIOS, and one labelled `nomad-maintenance` becomes a red banner over our
   deployments table. Nobody has to do anything wrong for this to happen; it
   only requires AI4EOSC to have a maintenance window during our demo.

**Not fixed here.** It is outside F3 — the home page does not use it, and the
fix touches the notifications button and the deployments list. It also needs a
decision rather than a patch: either point it at a CAIOS status repository, or
disable it and let the feature read as unconfigured rather than broken, which is
the rule D-50 already set for exactly this shape of problem.

`scripts/check-branding.sh` should grow an assertion for it in the same change,
alongside the ones for the analytics beacon and the model list.

### R-34 · Scope creep

Frontend work expands to fill available time, and unlike the infrastructure
stages there is no point at which it is objectively finished.

**Mitigation:** four days, hard stop. Feature pages are out of scope and stay
out. If F3 overruns, F4 is cut — a static node graph is a perfectly good node
graph.

---

## Decisions this plan proposes

Recorded in `docs/decisions.md` as each stage closes.

**D-45 — The dashboard serves its own fonts.** Removes a third-party leak,
removes the demo's dependence on reaching Google, and fixes an existing
mismatch where Material components rendered in a fallback face.

**D-46 — The home page makes no backend call.** It is static content and inline
SVG. The first page of the demo cannot show an error, whatever the cluster is
doing.

**D-47 — Brand colour and status colour are separate sets.** Status colours
encode deployment state and change only deliberately, never in hue.

**D-48 — A reduced-motion path ships in the same commit as the animation it
covers.** Retrofitting misses cases, and this is an accessibility requirement
rather than a nicety.

**D-49 — Visual changes go in CAIOS-owned config, not patches, wherever the
cascade allows it.** Ordering our stylesheet after upstream's in the `styles`
array we already control means the whole token pass carries no drift risk.
