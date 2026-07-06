# Precinct — the AI-native campaign operating system

A campaign OS built from scratch for the way races are actually run: target voters in
plain English, cut turf onto walk sheets and maps, run phone banks, chase outstanding
mail ballots daily, keep the finance ledger compliance-checked — with Claude reading
the messy paperwork and answering questions about your own campaign's numbers.

**Live demo:** the app ships with 400 labeled illustrative voters and a sample ballot
season — every derived number is marked, sample data is never passed off as real.
Press ▶ "60-sec tour" in the header and it demos itself.

## What's inside
- **Voter data layer** — canonical multi-state schema; Florida adapter pinned to the
  official Voter Extract layout; drag-drop loader; Postgres-backed store that scales
  to the full statewide file (SQL-compiled targeting, no 13M-row RAM tricks)
- **Targeting** — natural language ("low-propensity Republican men under 40 in HD 35")
  with the parse echoed back as filters; Claude rephrases free-form phrasing
- **Field ops** — street-ordered walk sheets, balanced turf splitting, turf maps,
  phone-bank call sheets, canvass tagging, **vote-by-mail ballot chase**
- **Finance & compliance** — real cited FL contribution limits (s.106.08), compliance
  flags, AI document intake (Claude drafts, a human approves — always)
- **Ask Precinct** — plain-English Q&A over campaign aggregates (no voter PII ever
  goes to the model)
- **Multi-campaign** with per-campaign data walls, memberships, audit trail on every
  write, auth (scrypt + hashed session tokens), security headers, per-IP rate limits

## Stack
Python / FastAPI · Postgres (Cloud SQL) or SQLite · vanilla single-file frontend ·
Anthropic Claude for the AI seams · Cloud Run. 60 automated tests (SQLite default; the full suite also runs against live Postgres) run against BOTH
database engines.

## Run it
```
pip install -r requirements.txt
python -m pytest -q
python -m uvicorn precinct.api:app     # http://localhost:8000
```
Optional env: `ANTHROPIC_API_KEY` (AI seams; rule-based fallbacks otherwise),
`PRECINCT_PG_*` (Postgres), `PRECINCT_STORE=pg` (SQL voter store),
`PRECINCT_AUTH=1` (accounts).

## Data & honesty posture
Voter data comes from official state public-records extracts under their permitted
political/scholarly use. Sample data is labeled illustrative everywhere. Derived
values are marked ◈. AI-read documents carry a provenance pill and require human
approval before anything is committed or filed.
