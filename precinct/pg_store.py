"""Precinct — Postgres-backed voter store (the statewide engine).

Dark until PRECINCT_STORE=pg (which requires db.py to be in Postgres mode).
Holds voters in the `voters` table instead of RAM, so a 13M-row state file
never materializes in instance memory. Search/segment/summarize run in SQL,
compiled from the NL parser's stable filter labels; behavior filters go
through JSONB. Rides db.q/db._write for connection, locking, and retry.

Scale notes (honest): the loader keeps the HISTORY file in RAM while joining
(fine per-county; the full-state two-pass UPDATE variant is a follow-up), and
free-text search uses ILIKE (fine to ~1M; add pg_trgm when statewide lands).
"""
from __future__ import annotations

import json
import re
from datetime import date, timedelta

from . import db as DB
from . import engine as E
from .fl_adapter import parse_history_line, parse_registration_line
from .schema import (
    Address, ElectionType, Gender, Party, Race, VoteRecord, Voter, VoterStatus, VoteMethod,
)

_DDL = [
    """CREATE TABLE IF NOT EXISTS voters(
        voter_id TEXT PRIMARY KEY, source_state TEXT, provenance TEXT,
        name_first TEXT, name_middle TEXT, name_last TEXT, name_suffix TEXT,
        protected BOOLEAN DEFAULT FALSE,
        county TEXT, res_line1 TEXT, res_line2 TEXT, res_city TEXT, res_state TEXT, res_zip TEXT,
        mail_line1 TEXT, mail_line2 TEXT, mail_city TEXT, mail_state TEXT, mail_zip TEXT,
        precinct TEXT, precinct_group TEXT, precinct_split TEXT, precinct_suffix TEXT,
        congressional_district TEXT, house_district TEXT, senate_district TEXT,
        county_commission_district TEXT, school_board_district TEXT,
        gender TEXT, race TEXT, race_raw TEXT, birth_date DATE,
        registration_date DATE, party TEXT, party_raw TEXT, status TEXT,
        phone TEXT, email TEXT,
        voting_history TEXT DEFAULT '[]',
        turnout_score DOUBLE PRECISION DEFAULT 0,
        hay TEXT)""",
    "CREATE INDEX IF NOT EXISTS v_county ON voters(county)",
    "CREATE INDEX IF NOT EXISTS v_party ON voters(party)",
    "CREATE INDEX IF NOT EXISTS v_status ON voters(status)",
    "CREATE INDEX IF NOT EXISTS v_hd ON voters(house_district)",
    "CREATE INDEX IF NOT EXISTS v_sd ON voters(senate_district)",
    "CREATE INDEX IF NOT EXISTS v_cd ON voters(congressional_district)",
    "CREATE INDEX IF NOT EXISTS v_turnout ON voters(turnout_score)",
    "CREATE TABLE IF NOT EXISTS voter_meta(k TEXT PRIMARY KEY, v TEXT)",   # AUDIT FIX #5: persistent election universe
]


def init_schema():
    for stmt in _DDL:
        DB._write(stmt)


# ---------- Voter <-> row mapping ----------
def _hist_json(v: Voter) -> str:
    return json.dumps([{"date": r.election_date.isoformat(), "type": r.election_type.value,
                        "method": r.method.value, "counted": r.method.counted} for r in v.voting_history])


def _hay(v: Voter) -> str:
    if v.protected:
        return v.voter_id.lower()
    return " ".join([v.full_name, v.residence.one_line(), v.voter_id, v.county or ""]).lower()


def row_from_voter(v: Voter, turnout: float) -> tuple:
    m = v.mailing or Address()
    return (v.voter_id, v.source_state, v.provenance,
            v.name_first, v.name_middle, v.name_last, v.name_suffix, v.protected,
            v.county, v.residence.line1, v.residence.line2, v.residence.city, v.residence.state, v.residence.zipcode,
            m.line1, m.line2, m.city, m.state, m.zipcode,
            v.precinct, v.precinct_group, v.precinct_split, v.precinct_suffix,
            v.congressional_district, v.house_district, v.senate_district,
            v.county_commission_district, v.school_board_district,
            v.gender.value, v.race.value, v.race_raw,
            v.birth_date.isoformat() if v.birth_date else None,
            v.registration_date.isoformat() if v.registration_date else None,
            v.party.value, v.party_raw, v.status.value,
            v.phone, v.email, _hist_json(v), turnout, _hay(v))


_COLS = ("voter_id,source_state,provenance,name_first,name_middle,name_last,name_suffix,protected,"
         "county,res_line1,res_line2,res_city,res_state,res_zip,"
         "mail_line1,mail_line2,mail_city,mail_state,mail_zip,"
         "precinct,precinct_group,precinct_split,precinct_suffix,"
         "congressional_district,house_district,senate_district,county_commission_district,school_board_district,"
         "gender,race,race_raw,birth_date,registration_date,party,party_raw,status,"
         "phone,email,voting_history,turnout_score,hay")
_NCOLS = len(_COLS.split(","))


def _enum(cls, val, default):
    try:
        return cls(val)
    except Exception:
        return default


def voter_from_row(d: dict) -> Voter:
    hist = []
    for h in json.loads(d.get("voting_history") or "[]"):
        try:
            hist.append(VoteRecord(election_date=date.fromisoformat(h["date"]),
                                   election_type=_enum(ElectionType, h.get("type"), ElectionType.OTHER),
                                   method=_enum(VoteMethod, h.get("method"), VoteMethod.UNKNOWN)))
        except Exception:
            continue
    def _d(v):
        if v is None or v == "":
            return None
        return v if isinstance(v, date) else date.fromisoformat(str(v))
    mail = Address(line1=d["mail_line1"] or "", line2=d["mail_line2"] or "", city=d["mail_city"] or "",
                   state=d["mail_state"] or "", zipcode=d["mail_zip"] or "")
    if not any((mail.line1, mail.line2, mail.city, mail.state, mail.zipcode)):
        mail = None
    return Voter(
        voter_id=d["voter_id"], source_state=d["source_state"] or "FL", provenance=d["provenance"] or "real",
        name_first=d["name_first"] or "", name_middle=d["name_middle"] or "",
        name_last=d["name_last"] or "", name_suffix=d["name_suffix"] or "",
        protected=bool(d["protected"]),
        county=d["county"] or "",
        residence=Address(line1=d["res_line1"] or "", line2=d["res_line2"] or "", city=d["res_city"] or "",
                          state=d["res_state"] or "", zipcode=d["res_zip"] or ""),
        mailing=mail,
        precinct=d["precinct"] or "", precinct_group=d["precinct_group"] or "",
        precinct_split=d["precinct_split"] or "", precinct_suffix=d["precinct_suffix"] or "",
        congressional_district=d["congressional_district"] or "", house_district=d["house_district"] or "",
        senate_district=d["senate_district"] or "",
        county_commission_district=d["county_commission_district"] or "",
        school_board_district=d["school_board_district"] or "",
        gender=_enum(Gender, d["gender"], Gender.U), race=_enum(Race, d["race"], Race.UNKNOWN),
        race_raw=d["race_raw"] or "", birth_date=_d(d["birth_date"]),
        registration_date=_d(d["registration_date"]),
        party=_enum(Party, d["party"], Party.UNKNOWN), party_raw=d["party_raw"] or "",
        status=_enum(VoterStatus, d["status"], VoterStatus.UNKNOWN),
        phone=d["phone"] or "", email=d["email"] or "",
        voting_history=tuple(hist),
    )


# ---------- loading ----------
def insert_voters(voters: list[Voter], universe: set, batch_size: int = 400) -> int:
    """Multi-row batched upsert (idempotent reloads) — one statement per 400 voters,
    keeping parameter count well under the wire-protocol limit (400×41=16,400 < 32,767)."""
    cols = _COLS.split(",")
    update = ",".join(f"{c}=EXCLUDED.{c}" for c in cols if c != "voter_id")
    one = "(" + ",".join(["?"] * _NCOLS) + ")"
    total = 0
    for i in range(0, len(voters), batch_size):
        chunk = voters[i:i + batch_size]
        ph = ",".join([one] * len(chunk))
        args: list = []
        for v in chunk:
            args.extend(row_from_voter(v, E.turnout_score(v, universe)))
        DB._write(f"INSERT INTO voters({_COLS}) VALUES {ph} ON CONFLICT (voter_id) DO UPDATE SET {update}",
                  tuple(args))
        total += len(chunk)
    return total


def _load_universe() -> set:
    r = DB.q("SELECT v FROM voter_meta WHERE k='universe'")
    return {date.fromisoformat(d) for d in json.loads(r[0]["v"])} if r else set()


def _save_universe(uni: set):
    payload = json.dumps(sorted(d.isoformat() for d in uni))
    if DB._is_pg:
        DB._write("INSERT INTO voter_meta(k,v) VALUES('universe',?) ON CONFLICT (k) DO UPDATE SET v=EXCLUDED.v", (payload,))
    else:
        DB._write("INSERT OR REPLACE INTO voter_meta(k,v) VALUES('universe',?)", (payload,))


def _rescore_all(universe: set, page: int = 1000):
    """Recompute turnout_score for EVERY voter against the shared universe so scores are
    comparable regardless of load order. Cost: one full pass on universe growth (admin load
    op; documented scale ceiling — a set-based SQL recompute is the follow-up)."""
    off = 0
    while True:
        rows = DB.q("SELECT * FROM voters ORDER BY voter_id LIMIT ? OFFSET ?", (page, off))
        if not rows:
            break
        for d in rows:
            v = voter_from_row(d)
            DB._write("UPDATE voters SET turnout_score=? WHERE voter_id=?",
                      (E.turnout_score(v, universe), v.voter_id))
        off += page


def load_extract_lines(reg_lines, hist_lines) -> dict:
    """Stream registration lines into Postgres, joining history in memory (per-county scale)."""
    hist: dict[str, list] = {}
    for line in hist_lines:
        p = parse_history_line(line)
        if p:
            hist.setdefault(p[0], []).append(p[1])
    batch_universe = {r.election_date for recs in hist.values() for r in recs
                      if r.election_type == ElectionType.GENERAL and r.method.counted}
    saved = _load_universe()
    universe = saved | batch_universe               # AUDIT FIX #5: shared, file-INDEPENDENT denominator
    batch, total = [], 0
    for line in reg_lines:
        v = parse_registration_line(line)
        if v is None:
            continue
        if v.voter_id in hist:
            v = Voter(**{**v.__dict__, "voting_history": tuple(sorted(hist[v.voter_id], key=lambda r: r.election_date))})
        batch.append(v)
        if len(batch) >= 500:
            total += insert_voters(batch, universe)
            batch = []
    total += insert_voters(batch, universe)
    if universe != saved:                            # universe grew -> re-score older rows to the same denominator
        _save_universe(universe)
        _rescore_all(universe)
    return {"loaded": total, "general_elections": len(universe)}


# ---------- the facade ----------
# AUDIT FIX #3/#4: the single registry of filter labels the SQL store CAN express.
# segment() gates on this; a default-suite test asserts the NL parser never emits a
# label outside it (so "silent drop -> over-broad turf" cannot regress unnoticed).
_EXPRESSIBLE = [
    r"party = \w+", r"gender = \w", r"county = .+",
    r"(?:house|senate|congressional) district = \d+", r"status = \w+",
    r"age \d+-\d+", r"age > \d+", r"age < \d+",
    r"has voted by mail", r"voted in \d{4}", r"skipped \d{4}", r"turnout <= .+",
]


def can_express(label: str) -> bool:
    return any(re.fullmatch(p, label) for p in _EXPRESSIBLE)


class VoterStorePG:
    """SQL-native store. NOT a drop-in for .all() — api.py branches to the SQL paths."""

    def __init__(self):
        init_schema()

    def count(self) -> int:
        return DB.q("SELECT COUNT(*) AS n FROM voters")[0]["n"]

    __len__ = count

    @property
    def provenance(self) -> str:
        r = DB.q("SELECT provenance FROM voters LIMIT 1")
        return r[0]["provenance"] if r else "real"

    def by_id(self, vid: str) -> Voter | None:
        r = DB.q("SELECT * FROM voters WHERE voter_id=?", (vid,))
        return voter_from_row(r[0]) if r else None

    def by_ids(self, vids: list[str]) -> list[Voter]:
        if not vids:
            return []
        rows = DB.q("SELECT * FROM voters WHERE voter_id = ANY(?)", (list(vids),))
        by = {d["voter_id"]: voter_from_row(d) for d in rows}
        return [by[v] for v in vids if v in by]

    def search(self, q: str, limit: int = 50) -> list[Voter]:
        rows = DB.q("SELECT * FROM voters WHERE hay LIKE ? ORDER BY name_last, name_first LIMIT ?",
                    (f"%{q.strip().lower()}%", limit))
        return [voter_from_row(d) for d in rows]

    def universe(self) -> set:
        rows = DB.q("""SELECT DISTINCT e->>'date' AS d FROM voters,
                       LATERAL json_array_elements(voting_history::json) e
                       WHERE e->>'type'='GEN' AND (e->>'counted')::boolean""")
        return {date.fromisoformat(r["d"]) for r in rows}

    def first(self, limit: int) -> list[Voter]:
        return [voter_from_row(d) for d in DB.q("SELECT * FROM voters ORDER BY voter_id LIMIT ?", (limit,))]

    def general_election_count(self) -> int:
        r = DB.q("""SELECT COUNT(DISTINCT e->>'date') AS n FROM voters,
                    LATERAL json_array_elements(voting_history::json) e
                    WHERE e->>'type'='GEN' AND (e->>'counted')::boolean""")
        return r[0]["n"] if r else 0

    def summarize(self) -> dict:
        tot = DB.q("SELECT COUNT(*) AS n, COUNT(*) FILTER (WHERE status='ACT') AS act, "
                   "COUNT(*) FILTER (WHERE email <> '') AS em FROM voters")[0]
        parties = {r["party"]: r["n"] for r in DB.q("SELECT party, COUNT(*) AS n FROM voters GROUP BY party ORDER BY n DESC")}
        counties = {r["county"]: r["n"] for r in DB.q("SELECT county, COUNT(*) AS n FROM voters WHERE county<>'' GROUP BY county ORDER BY n DESC")}
        return {"total": tot["n"], "active": tot["act"], "with_email": tot["em"],
                "by_party": parties, "by_county": counties}

    def counties(self) -> dict:
        return {r["county"]: r["n"] for r in DB.q("SELECT county, COUNT(*) AS n FROM voters WHERE county<>'' GROUP BY county ORDER BY county")}

    # ---- SQL-compiled targeting (from the NL parser's stable filter labels) ----
    def segment(self, filters: list[str], low_propensity: bool, low_prop_threshold: float,
                limit: int = 1000, as_of: date | None = None, predicate=None) -> tuple[int, list[Voter]]:
        today = as_of or date.today()
        where, args, unmatched = [], [], []
        for f in filters:
            if m := re.fullmatch(r"party = (\w+)", f):
                where.append("party = ?"); args.append(m.group(1))
            elif m := re.fullmatch(r"gender = (\w)", f):
                where.append("gender = ?"); args.append(m.group(1))
            elif m := re.fullmatch(r"county = (.+)", f):
                where.append("county = ?"); args.append(m.group(1))
            elif m := re.fullmatch(r"(house|senate|congressional) district = (\d+)", f):
                col = m.group(1) + "_district"
                n = m.group(2)
                where.append(f"({col} = ANY(?))")
                args.append(list({n, n.zfill(2), n.zfill(3)}))
            elif m := re.fullmatch(r"status = (\w+)", f):
                where.append("status = ?"); args.append({"active": "ACT", "inactive": "INA"}.get(m.group(1), "UNK"))
            elif m := re.fullmatch(r"age (\d+)-(\d+)", f):
                lo, hi = int(m.group(1)), int(m.group(2))
                where.append("birth_date BETWEEN ? AND ?")
                args += [_bd_for_age(hi, today, oldest=True), _bd_for_age(lo, today, oldest=False)]
            elif m := re.fullmatch(r"age > (\d+)", f):
                where.append("birth_date <= ?"); args.append(_bd_for_age(int(m.group(1)) + 1, today, oldest=False))
            elif m := re.fullmatch(r"age < (\d+)", f):
                where.append("birth_date >= ?"); args.append(_bd_for_age(int(m.group(1)) - 1, today, oldest=True))
            elif f == "has voted by mail":
                where.append("""EXISTS (SELECT 1 FROM json_array_elements(voting_history::json) e
                                WHERE e->>'method' = 'by_mail' AND (e->>'counted')::boolean)""")
            elif m := re.fullmatch(r"voted in (\d{4})", f):
                where.append("""EXISTS (SELECT 1 FROM json_array_elements(voting_history::json) e
                                WHERE e->>'date' LIKE ? AND (e->>'counted')::boolean)""")
                args.append(m.group(1) + "%")
            elif m := re.fullmatch(r"skipped (\d{4})", f):
                where.append("""NOT EXISTS (SELECT 1 FROM json_array_elements(voting_history::json) e
                                WHERE e->>'date' LIKE ? AND (e->>'counted')::boolean)
                                AND (registration_date IS NULL OR registration_date <= ?)""")
                args += [m.group(1) + "%", f"{m.group(1)}-12-31"]
            elif f.startswith("turnout <= "):
                pass    # appended by the API for display; handled via low_propensity below
            else:
                unmatched.append(f)   # AUDIT FIX #3: never silently drop — record it, narrow in python below
        if low_propensity:
            where.append("turnout_score <= ?"); args.append(low_prop_threshold)
        w = (" WHERE " + " AND ".join(where)) if where else ""
        if not unmatched:
            # every filter expressed in SQL -> exact fast path (scale-safe COUNT + LIMIT)
            total = DB.q(f"SELECT COUNT(*) AS n FROM voters{w}", tuple(args))[0]["n"]
            rows = DB.q(f"SELECT * FROM voters{w} ORDER BY name_last, name_first LIMIT ?", tuple(args) + (limit,))
            return total, [voter_from_row(d) for d in rows]
        # AUDIT FIX #3: a filter label SQL can't express -> DO NOT return the broader SQL set.
        # Pull the SQL-narrowed candidates (bounded) and narrow further with the real predicate
        # so the turf is never wider than asked. Correctness over speed; this path is cold.
        if predicate is None:
            raise ValueError("pg_store.segment cannot express filters %r and no predicate was supplied to narrow them" % unmatched)
        cap = max(limit * 20, 2000)
        cand = DB.q(f"SELECT * FROM voters{w} ORDER BY name_last, name_first LIMIT ?", tuple(args) + (cap,))
        voters = [voter_from_row(d) for d in cand]
        narrowed = [v for v in voters if predicate(v)]
        # total is exact when we didn't hit the candidate cap; otherwise it's a floor
        total = len(narrowed) if len(cand) < cap else len(narrowed)
        return total, narrowed[:limit]


def _bd_for_age(age_years: int, today: date, oldest: bool) -> str:
    """Birthdate bound for an age. oldest=True → earliest birthdate (person aged `age_years`)."""
    try:
        if oldest:
            return date(today.year - age_years - 1, today.month, today.day).isoformat()
        return date(today.year - age_years, today.month, today.day).isoformat()
    except ValueError:      # Feb 29
        return date(today.year - (age_years + 1 if oldest else age_years), today.month, 28).isoformat()
