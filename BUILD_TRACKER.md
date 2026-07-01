# Precinct — Build Tracker  (at-a-glance progress)
*Updated 2026-07-01. ✅ done · 🟡 in progress · ⛔ waiting on human · ⬜ not started.*

## Kit stages
| Stage | What | State |
|-------|------|-------|
| S0 | Lock purpose & ground truth | ✅ (confirmed by Rob) |
| S0.5 | Inventory & harvest | ✅ |
| S1 | Map → spine (roadmap) | ✅ (confirmed) |
| S1.5 | Map to instance (FL schema) | ✅ (pinned to official layout) |
| S2 | Scaffold pure core | ✅ (engine + adapter + NL seam; 8 tests green) |
| S3 | Calibrate on REAL data | ⛔ needs the official FL disk (Rob's standing request) |
| S4 | Build outward (API + console) | ✅ local end-to-end on labelled sample data |
| S5 | Connectors | ⬜ (harvest kit templates: gcp/gh/deploy) |
| S6 | Deploy | ⛔ needs cloud login · billing · WIF (Rob's gate) |
| S7 | Independent adversarial audit | ✅ verdict "real, competent — not smoke"; report in AUDIT.md |
| S8 | Fix loop | ✅ top-4 findings closed + guarded; 18 tests green |
| S9 | Ship / harden call | ⬜ (Rob) |

## Module spine (Phase 1 core)
| # | Module | State |
|---|--------|-------|
| 1 | Voter Data Layer | ✅ schema + FL adapter + store (real-disk seam ready) |
| 2 | AI Targeting Engine | ✅ NL → segment, derived turnout score, API + console |
| 3 | Field Operations | ⬜ (walk lists + mobile capture) |
| 4 | Supporter & Contact CRM | ⬜ Phase 2 |
| 5 | AI Document Reading | ✅ finance intake (text→draft, human-gated); LLM seam for scans |
| 6 | Finance & Compliance | ✅ contributions/expenses, cited FL limits, report + compliance flags |
| 7–10 | Petitions · Fundraising · Multi-Campaign Console · Platform | ⬜ Phase 2/3 |

## Next actions
- **Hands (me), no gate:** Module 3 (field ops) or S5 connectors + S7 audit — can proceed now.
- **Eyes (Rob), parallel:** place the FL standing voter-extract request (see `../Flori