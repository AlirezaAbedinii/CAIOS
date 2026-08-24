# Screenshots

Not tracked for their own sake. Two directories, two different jobs.

## `before/`

The **F0 baseline** from `docs/frontend-plan.md` — every page as it looked
before any visual change, at 1440 px and 768 px.

This is the regression test for the theme pass. Frontend work has no assertion
for "looks right", so the only thing that will catch a token change quietly
wrecking a page nobody thought to open is a diff against these.

Name them `<page>-<width>.png`:

    catalog-modules-1440.png   catalog-modules-768.png
    module-detail-1440.png     deploy-form-1440.png
    deployments-1440.png       statistics-1440.png
    catalog-llms-1440.png      profile-1440.png
    not-found-1440.png         forbidden-1440.png

## `issues/`

Evidence of faults found by looking, kept separately because these are
**pre-existing bugs, not baseline**. A fault photographed here is one that
cannot later be blamed on the redesign.

Name them for the symptom, not the page: `module-deploy-<what-went-wrong>.png`.

Anything in here should also be written up — as a risk in the relevant plan
document, or as an issue for the session that will fix it. A screenshot with no
prose beside it stops being legible within a week.
