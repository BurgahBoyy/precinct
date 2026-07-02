# Precinct — codebase (v0.1)

AI-native campaign operating system. This is the working engine + API + console for
**Module 1 (Voter Data Layer)** and **Module 2 (AI Targeting)** of the roadmap —
built to displace WebElect. See the docs in the parent folder (`Product_Brief.md`,
`Ground_Truth.md`, `Roadmap.md`, `Florida_Voter_Data_Access.md`).

## What works right now
- **Canonical multi-state voter schema** (`precinct/schema.py`) — states map *into* it.
- **Florida adapter** (`precinct/fl_adapter.py`) — parses the official FL "Voter Extract"
  tab-delimited files, pinned field-for-field to the May 2026 layout (38 registration
  fields + voting history + code tables).
- **Pure targeting engine** (`precinct/engine.py`) — predicates, segmentation, and an
  honest, dataset-relative **turnout score** (not a black box).
- **Natural-language targeting** (`precinct/nl_targeting.py`) — type the target in plain
  English; it always **reports back what it understood**. Rule-based today; a clear seam
  (`llm_parse`) is where Claude plugs in later.
- **Typed API** (`precinct/api.py`) — FastAPI; bad input → 422; every value labelled.
- **Console** (`console/index.html`) — search box → live results, with a prominent
  SAMPLE-DATA banner and derived-value tags.
- **Labelled sample data** (`precinct/sample_data.py`) — synthetic FL-format voters so the
  whole thing runs *before the real disk arrives*. Everything is stamped
  `provenance="illustrative"`.

## Run it
```bash
cd precinct
pip install -r requirements.txt        # (use --break-system-packages on some systems)
python -m pytest -q                     # 26 tests, value-pinned
python -m uvicorn precinct.api:app --reload
# then open http://localhost:8000/
```

## Plugging in REAL Florida voters (the only thing between this and real data)
1. Rob places the standing request → the official monthly extract arrives (see
   `../Florida_Voter_Data_Access.md`).
2. Point the store at it — one line:
   ```python
   from precinct.store import VoterStore
   STORE = VoterStore.from_fl_zip("Voter_Registration_YYYYMMDD.zip",
                                   "Voter_History_YYYYMMDD.zip")
   ```
   Records now come back `provenance="real"` and the console banner flips to green.

## Provenance labels (build-kit non-negotiable)
- **real** — straight from the official extract.
- **derived** — computed by Precinct (age, turnout score, reach).
- **illustrative** — sample data, not real voters.

## Where this sits in the build (kit stages)
S0–S1.5 ✅ (docs + schema map) · **S2 ✅ pure core + tests green** · **S4 🟡 API + console local** ·
S3 (calibrate on the real disk), S5 (connectors), S6 (deploy), S7 (independent audit) — next.
