# Decisions

Append-only log. Newest at the bottom of each section. Claude Code should add an entry
whenever it makes a choice future-us would want explained.

Format: **D-nn** for settled, **Q-nn** for open.

---

## Settled

**D-01 — We deploy AI4OS, not a fork.**
iMagine, AI4Life and KMD4EOSC are existing branded instances of the same stack, and
`ai4-docs` has an onboarding checklist for a new project. We follow it.

**D-02 — Flavour name is `pacslab`.**
Used consistently for the Nomad namespace, the dashboard tenant config, the theme
directory and the `angular.json` build configuration.

**D-03 — Control-plane services run as Docker Compose on `ai4_services`, not as Nomad jobs.**
Keycloak, MinIO, PAPI and the dashboard. Easier to debug in a three-week window.
Revisit only if the demo needs it.

**D-04 — Three Nomad datacenters named `site_a`, `site_b`, `site_c`.**
Makes the federated story structural: the Statistics page genuinely shows three sites
and we can honestly say data stays on each node.

**D-05 — GPU nodes are built from the `gpu-enabled-instance` volume snapshot.**
Skips NVIDIA driver installation and GPU activation. Do not follow the manual dkms
instructions.

**D-06 — `IS_PROD` stays unset on PAPI.**
Dev mode downgrades missing-token errors to warnings. We are not running Harbor,
Jenkins, the provenance API or LiteLLM.

**D-07 — Public datasets only.**
No real patient imaging. Removes ethics and privacy questions entirely and means no
audience question is unanswerable.

**D-08 — Branding happens early, not late.**
Original brief deferred it. Since this supports a grant application, a walkthrough
covered in someone else's logos undercuts the point. Half a day, high payoff.

**D-09 — Out of scope for v1.**
OSCAR serverless, Harbor, Jenkins publishing pipeline, drift monitoring, provenance,
low-code pipelines, carbon accounting, real PACS/DICOM archive integration. These go on
a roadmap slide.

---

## Open

**Q-01 — Domain and DNS zone access.** *Blocking.*
Every deployment gets its own subdomain, so we need a domain we control, a wildcard
record, and a wildcard certificate via DNS-01, which needs API access to the zone.
Waiting on the supervisor. Fallback: buy a cheap domain ourselves.

**Q-02 — Does "PACS lab flavour" mean branding or integration?**
Assumed branding only (logo, palette, icons). If it means connecting to a real PACS or
DICOM archive (Orthanc, DICOMweb, C-STORE), that is a separate project and the plan
changes materially.

**Q-03 — Demo format.**
Live session, recorded walkthrough, or stills in the application. Changes what Phase 6
optimises for. Current assumption: produce a recording regardless, since it doubles as
insurance.

**Q-04 — Does the Statistics page need real accumulated usage history?**
If yes, `ai4-accounting` and `monitoring-nomad` need to run for several days, which
moves them much earlier in the plan. Current assumption: rendering correctly with live
cluster data is enough.

**Q-05 — Does federated learning carry the research contribution in the grant?**
If yes, restructure the demo around the three-site story and cut time from CVAT and
annotation to make room.

**Q-06 — Institutional SSO, or is a demo login sufficient?**
Current assumption: our own Keycloak with local demo accounts.

**Q-07 — Throwaway demo, or the start of something the lab keeps running?**
Changes how much time goes into reproducibility. Current assumption: treat it as
throwaway but keep everything in Ansible anyway, since that costs little.

---

## Log

*Append new decisions below with date and one line of reasoning.*
