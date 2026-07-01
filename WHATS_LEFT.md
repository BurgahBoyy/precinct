# Precinct — What's left to be "real-user ready" (honest gap map)
*2026-07-01. The question: if we handed this to a real campaign/consultant today, what's missing? No sugar-coating.*

## What's already real (the foundation — genuinely solid)
- **Voter Data Layer** — FL adapter pinned to the official extract spec; canonical multi-state schema; protected-voter redaction.
- **AI Targeting** — plain-English → voter segment; honest derived turnout score; every value labelled.
- **Lists / turf** and **voter profiles** with voting history.
- **Finance & Compliance** + **AI document intake** — cited FL limits, compliance flags, human-gated drafts.
- **26 value-pinned tests**; passed an independent adversarial audit ("real, competent code, not smoke").

**But today it:** runs on your laptop only, on **400 labelled *sample* voters**, keeps everything **in memory** (restart = data gone), has **no login**, and its AI is a fast **rule-based** stand-in with a Claude seam (not yet real Claude).

---

## Tier 1 — blockers before ANY real user (must-have)
1. **Real voter data loaded.** Swap the 400 sample voters for the actual Florida extract. The load path already exists (`VoterStore.from_fl_zip`) — it just needs the disk. → *Gate: your FL voter-file request.*
2. **Persistence (a database).** Right now lists, tags, and contributions live in RAM and vanish on restart. A real user needs their work saved. → *I build it; needs a managed database.*
3. **Auth + hosting.** Accounts/login, a live URL, locked-down CORS, and PII/protected-voter rules enforced for real. → *I build it; needs your GitHub + cloud logins.*

## Tier 2 — the core features a campaign expects day-to-day
4. **Field operations / canvassing** (Module 3) — turf-cut on a map, walk lists, the mobile door-knocking app with offline capture that writes back. This is WebElect's daily heart; it's the biggest *feature* gap.
5. **Supporter CRM** (Module 4) — support/oppose/undecided tagging flows, contact records, dedupe/merge.
6. **Multi-campaign console** (Module 9) — the consultant cockpit to run many campaigns with per-campaign data walls. We're single-campaign today; this is the whole point for the buyer we picked.

## Tier 3 — completeness & polish
7. **Petitions & ballot access** (Module 7) and **Fundraising intelligence** (Module 8).
8. **Wire real Claude** into the two AI seams — messy phrasing + real scanned checks. → *Gate: an Anthropic API key.*
9. **Actual state e-filing** — we *generate* the finance report; *submitting* it to the FL Division of Elections is a further integration. Plus the **per-state legal/data-license review** before monetizing.
10. **Production hardening** — rate limiting, monitoring, backups, file-encoding confirmation.
11. **Amazing UX (dedicated finale)** — a full polish pass so it's genuinely delightful, not just functional: interaction design, speed/perceived-speed, empty & error states, mobile/responsive, keyboard flow, onboarding, and the small details that make a real user *want* to use it. Done last, once the features are in.

---

## Honest bottom line
- **Built:** a strong, audited skeleton + 3 of ~10 modules. Better foundation than most MVPs — but not yet a daily-use product.
- **To hand a real consultant something they'd use:** Tier 1 is mandatory (data + persistence + auth/deploy); Tier 2 makes it genuinely useful; Tier 3 makes it complete.
- **All buildable** — most by me. Only **3 gates need you:** the FL data disk, cloud logins (deploy), and an API key (real Claude).
- **Rough order if we push to a usable v1:** persistence → auth → deploy → real FL data → field/canvassing → multi-campaign console → real Claude → petitions/fundraising → e-filing/hardening → **an amazing-UX polish pass to finish.**
