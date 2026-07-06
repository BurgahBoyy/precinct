# Precinct — Internal Adversarial Review (S7)
> NOTE (2026-07-06): this is an INTERNAL adversarial pass by a fresh-context agent of the same build system — rigorous, but NOT a third-party audit. A external review is a future item.
*Fresh-context adversarial review by a skeptical senior-engineer agent. Date: 2026-07-01. The builder can't grade itself — this is required by the build kit.*

## Verdict
**Real, competent code — not smoke.** It runs end-to-end, the tests pin values (not just directions), the Florida adapter is mapped field-for-field to the real published layout, and provenance labelling (real/derived/illustrative) is a maturity most devs skip. Skeleton is senior-grade (pure engine, quarantined I/O, adapter pattern). A few domain-logic and safety gaps keep it just below a senior's bar — and they're exactly the ones that matter once real voters load.

## Grades
| Area | Grade |
|------|-------|
| Architecture | A− |
| Code quality | B+ |
| Testing | B |
| Security | C as-is · B for a labelled localhost demo |
| Production-readiness | C |

## The 3 findings that matter most (fix before real voter data)
1. **Protected voters leak PII.** The adapter reads Florida's public-records-exemption flag, but the API never honors it — `voter_detail`/`voter_row` return address/phone/email/DOB for anyone, including the law-enforcement/judge/abuse-survivor records the exemption exists to protect. Highest severity.
2. **"Skipped / did-not-vote" conflates abstained with not-eligible.** `did_not_vote_in` / the year-skipped predicate return True for voters who registered after the election, moved in, or turned 18 later — so a "skipped 2022" turf list knocks doors of people who couldn't legally vote then. Wrong turf = the core product.
3. **Turnout score is dataset-relative and unstable.** Presented as a hard %, but the denominator is derived from whichever voters are loaded, so the same voter can score differently across loads. Make the election calendar explicit, or caveat the number on every surface.

## Other real fixes (ranked)
4. Fragile float-as-string dedup for the low-propensity filter (`api.py`) → use a structured flag.
5. No API-layer tests (TestClient is free; `httpx` already a dep) → add them, incl. a protected-voter redaction test.
6. `date.today()` inside the "pure" engine contradicts the determinism claim → require `as_of` or soften the docstring.
7. Blanket `latin-1` decode silently mojibakes accented (e.g. Hispanic) surnames → confirm/​document FL encoding, surface errors.
8. Duplicated low-propensity trigger word list (two copies) → share one.
9. `datetime.utcnow()` deprecated → `datetime.now(timezone.utc)`; lock down CORS + add auth before deploy (S6-gated).
10. Name magic numbers (max age 130, LOW_PROP, sample n); set `mailing=None` when blank per the schema default.

## Typical dev vs senior
Above the typical-dev median (canonical schema + adapter, value-pinned tests, provenance labelling, defined turnout denominator). Below senior in specific domain judgment: the protected-voter leak, eligibility-gating, and treating a dataset-relative score as intrinsic — a senior blocks the first before a single real Floridian loads.

## Status → next
Audit deposited. **S8 fix loop** addresses findings #1–#4 first, each with the test that would have caught it. Nothing on screen is currently a lie (all data is labelled illustrative), so this is fix-before-real-data, not fix-a-live-leak.
