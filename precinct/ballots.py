"""Precinct — vote-by-mail / early-vote tracking: THE CHASE (Florida's daily heartbeat).

During election season the FL Division of Elections publishes daily absentee-request
and early-voting files. This module ingests them into `ballot_status`, derives each
voter's banked/outstanding state, and produces chase lists: YOUR supporters whose
ballots are still sitting on kitchen counters.

FORMAT NOTE [OPEN — verify against the first real daily file]: `parse_ballot_line`
is pinned to the commonly published shape (delimited: county, voter_id, election,
request/sent/returned dates + early-vote records). The column map below is ONE
constant to adjust on day one of real files; everything downstream is format-agnostic.

Provenance rule holds: illustrative season data is labeled illustrative, everywhere.
"""
from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone

from . import db as DB

# --- pinned column map for the daily absentee file [OPEN: verify vs first real file] ---
BALLOT_COLS = {"county": 0, "voter_id": 1, "election": 2, "requested": 3, "sent": 4, "returned": 5}
BALLOT_DELIMS = ("\t", "|", ",")

_DDL = """CREATE TABLE IF NOT EXISTS ballot_status(
    voter_id TEXT, election TEXT,
    requested TEXT, sent TEXT, returned TEXT, early_voted TEXT,
    provenance TEXT, updated TEXT,
    UNIQUE(voter_id, election))"""


def init_schema():
    DB._write(_DDL)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _norm_date(v: str) -> str:
    v = (v or "").strip()
    if not v:
        return ""
    m = re.match(r"(\d{1,2})/(\d{1,2})/(\d{2,4})", v)
    if m:
        mo, d, y = m.groups()
        y = ("20" + y) if len(y) == 2 else y
        return f"{y}-{int(mo):02d}-{int(d):02d}"
    return v[:10]


def parse_ballot_line(line: str) -> dict | None:
    line = line.rstrip("\n")
    if not line.strip():
        return None
    fields = None
    for d in BALLOT_DELIMS:
        if d in line:
            fields = line.split(d)
            break
    if not fields or len(fields) <= BALLOT_COLS["returned"]:
        return None
    g = lambda k: fields[BALLOT_COLS[k]].strip() if BALLOT_COLS[k] < len(fields) else ""
    vid = g("voter_id")
    if not vid or not vid.isdigit():
        return None
    return {"voter_id": vid, "election": g("election") or "unknown",
            "requested": _norm_date(g("requested")), "sent": _norm_date(g("sent")),
            "returned": _norm_date(g("returned"))}


def upsert_status(rows: list[dict], provenance: str = "real", batch_size: int = 200) -> int:
    """Idempotent daily refresh: newest file wins per (voter, election)."""
    init_schema()
    total = 0
    if DB._is_pg:
        sql_one = ("INSERT INTO ballot_status(voter_id,election,requested,sent,returned,early_voted,provenance,updated) "
                   "VALUES(?,?,?,?,?,?,?,?) ON CONFLICT (voter_id,election) DO UPDATE SET "
                   "requested=EXCLUDED.requested, sent=EXCLUDED.sent, returned=EXCLUDED.returned, "
                   "early_voted=EXCLUDED.early_voted, provenance=EXCLUDED.provenance, updated=EXCLUDED.updated")
    else:
        sql_one = ("INSERT OR REPLACE INTO ballot_status(voter_id,election,requested,sent,returned,early_voted,provenance,updated) "
                   "VALUES(?,?,?,?,?,?,?,?)")
    for r in rows:
        DB._write(sql_one, (r["voter_id"], r["election"], r.get("requested", ""), r.get("sent", ""),
                            r.get("returned", ""), r.get("early_voted", ""), provenance, _now()))
        total += 1
    return total


def load_ballot_lines(lines, provenance: str = "real") -> int:
    rows = [p for p in (parse_ballot_line(l) for l in lines) if p]
    return upsert_status(rows, provenance)


# --- derivation ---
def _banked(r: dict) -> bool:
    return bool(r.get("returned") or r.get("early_voted"))


def _outstanding(r: dict) -> bool:
    return bool((r.get("requested") or r.get("sent")) and not _banked(r))


def current_election() -> str | None:
    r = DB.q("SELECT election, COUNT(*) AS n FROM ballot_status GROUP BY election ORDER BY n DESC LIMIT 1")
    return r[0]["election"] if r else None


def season_provenance() -> str:
    r = DB.q("SELECT provenance FROM ballot_status LIMIT 1")
    return r[0]["provenance"] if r else "none"


def rollup(campaign_id: int, tags: tuple = ("support", "lean")) -> dict:
    """Banked vs outstanding — overall and among THIS campaign's supporters/leaners."""
    init_schema()
    el = current_election()
    if not el:
        return {"election": None, "season": "no ballot data loaded yet",
                "overall": {}, "supporters": {}, "provenance": "none"}
    rows = DB.q("SELECT requested, sent, returned, early_voted FROM ballot_status WHERE election=?", (el,))
    overall = {"requested": sum(1 for r in rows if r.get("requested") or r.get("sent")),
               "banked": sum(1 for r in rows if _banked(r)),
               "outstanding": sum(1 for r in rows if _outstanding(r))}
    ph = ",".join(["?"] * len(tags))
    srows = DB.q(f"""SELECT DISTINCT b.voter_id, b.requested, b.sent, b.returned, b.early_voted
                     FROM ballot_status b JOIN voter_tags t ON t.voter_id = b.voter_id
                     WHERE b.election=? AND t.campaign_id=? AND t.tag IN ({ph})""",
                 (el, campaign_id) + tuple(tags))
    sup = {"requested": sum(1 for r in srows if r.get("requested") or r.get("sent")),
           "banked": sum(1 for r in srows if _banked(r)),
           "outstanding": sum(1 for r in srows if _outstanding(r))}
    return {"election": el, "overall": overall, "supporters": sup, "provenance": season_provenance()}


def chase_rows(campaign_id: int, tags: tuple = ("support", "lean")) -> list[dict]:
    """THE CHASE LIST: this campaign's supporters/leaners with an outstanding ballot."""
    init_schema()
    el = current_election()
    if not el:
        return []
    ph = ",".join(["?"] * len(tags))
    rows = DB.q(f"""SELECT DISTINCT b.voter_id, b.requested, b.sent, b.returned, b.early_voted
                    FROM ballot_status b JOIN voter_tags t ON t.voter_id = b.voter_id
                    WHERE b.election=? AND t.campaign_id=? AND t.tag IN ({ph})""",
                (el, campaign_id) + tuple(tags))
    return [{"voter_id": r["voter_id"], "requested": r["requested"], "sent": r["sent"]}
            for r in rows if _outstanding(r)]


# --- illustrative season (sample mode only; labeled everywhere) ---
def seed_illustrative_season(voter_ids: list[str], election: str = "2026-11-03-GEN") -> int:
    """Deterministic fake season: ~45%% requested, of those ~55%% returned, ~12%% early."""
    rows = []
    for vid in voter_ids:
        h = int(hashlib.md5(vid.encode()).hexdigest()[:8], 16)
        if h % 100 >= 45:
            continue
        r = {"voter_id": vid, "election": election,
             "requested": f"2026-09-{(h % 28) + 1:02d}", "sent": f"2026-10-{(h % 20) + 1:02d}",
             "returned": "", "early_voted": ""}
        roll = (h // 100) % 100
        if roll < 55:
            r["returned"] = f"2026-10-{(roll % 27) + 2:02d}"
        elif roll < 67:
            r["early_voted"] = f"2026-10-{(roll % 12) + 18:02d}"
        rows.append(r)
    return upsert_status(rows, provenance="illustrative")
