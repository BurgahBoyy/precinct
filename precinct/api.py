"""Precinct — typed API edge. Bad input -> 422. Values labelled; protected voters redacted.
Persistence via SQLite (db.py); campaigns own tags/lists/finance. Finance intake uses Claude when a key exists."""
from __future__ import annotations

import itertools
import re
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, Request, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

from . import db as DB
from . import engine as E
from . import finance as FIN
from . import nl_targeting as NL
from .doc_intake import read_contribution
from .schema import ElectionType, Voter
from .store import VoterStore

app = FastAPI(title="Precinct API", version="0.2.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

from . import auth as AUTH  # noqa: E402
from . import hardening as HARD  # noqa: E402


@app.middleware("http")
async def _auth_gate(request: Request, call_next):
    ip = (request.headers.get("x-forwarded-for") or (request.client.host if request.client else "?")).split(",")[0].strip()
    b = HARD.bucket_for(request.url.path, request.method)
    if b and not HARD.allowed(ip, b):
        return JSONResponse({"detail": "rate limit exceeded — slow down"}, status_code=429)
    if AUTH.enabled() and not AUTH.is_public(request.url.path):
        user = AUTH.user_from_token(request.cookies.get(AUTH.COOKIE))
        if not user:
            return JSONResponse({"detail": "authentication required"}, status_code=401)
        request.state.user = user
    response = await call_next(request)
    for k, v in HARD.HEADERS.items():
        response.headers.setdefault(k, v)
    return response


def _user(request: Request) -> dict | None:
    return getattr(request.state, "user", None)


def _require_member(request: Request, campaign_id: int):
    if AUTH.enabled() and not AUTH.can_write(_user(request), campaign_id):
        raise HTTPException(status_code=403, detail="not a member of this campaign")

import os as _os

_USE_PG_STORE = _os.environ.get("PRECINCT_STORE", "").lower() == "pg"
if _USE_PG_STORE:
    from . import pg_store as _PS
    PGS = _PS.VoterStorePG()
    STORE: VoterStore = VoterStore([], provenance=(PGS.provenance if len(PGS) else "real"))
    UNIVERSE = PGS.universe()
else:
    PGS = None
    STORE = VoterStore.from_sample(n=400)
    UNIVERSE = E.election_universe(STORE.all(), types=(ElectionType.GENERAL,))
TODAY = date.today()
BY_ID = {v.voter_id: v for v in STORE.all()}


def _get_voter(vid: str):
    return PGS.by_id(vid) if PGS else BY_ID.get(vid)


def _get_voters(vids: list[str]):
    if PGS:
        return PGS.by_ids(vids)
    return [BY_ID[v] for v in vids if v in BY_ID]


def _voter_count() -> int:
    return len(PGS) if PGS else len(STORE)


def _segment(query: str, limit: int = 1000):
    """(parsed, matched, total) — SQL-compiled on the PG store, python engine otherwise."""
    parsed = NL.parse(query, as_of=TODAY, low_propensity_threshold=LOW_PROP)
    if PGS:
        total, matched = PGS.segment(parsed.filters, parsed.low_propensity, LOW_PROP, limit=limit, as_of=TODAY)
        return parsed, matched, total
    _, matched = _run_query(query, limit)
    return parsed, matched, len(matched)
LOW_PROP = 0.34
TURNOUT_BASIS = f"share of the {len(UNIVERSE)} general elections present in the loaded dataset"
REDACTED = "[protected]"
DEFAULT_CID = 1


def _bootstrap():
    DB.conn()
    if not DB.list_campaigns():
        cid = DB.create_campaign("Demo Campaign", "other")
        seeds = [
            ("Alice Kim", "500", "2026-05-10", "general", "check", "12 Palm Ave, Orlando FL", "1180"),
            ("Bob Lee", "1000", "2026-05-12", "general", "check", "5 Oak St, Tampa FL", "2201"),
            ("Bob Lee", "300", "2026-06-01", "general", "card", "5 Oak St, Tampa FL", ""),
            ("Carlos Diaz", "250", "2026-04-02", "primary", "check", "9 Bay Rd, Miami FL", ""),
            ("Dana White", "50", "2026-05-20", "general", "cash", "", ""),
        ]
        for s in seeds:
            DB.add_contribution(cid, donor_name=s[0], amount=s[1], date=s[2], phase=s[3],
                                method=s[4], address=s[5], check_number=s[6], provenance="illustrative")
        DB.add_expense(cid, "Print Shop", "400", "2026-05-15", "mailers", "illustrative")
        DB.add_expense(cid, "Digital Ads Co", "300", "2026-06-02", "online ads", "illustrative")
        lst_q = "NPA voters 30-45 who voted by mail"
        _, matched, _t = _segment(lst_q)
        DB.save_list(cid, "Persuasion turf — mail-first NPAs", lst_q, [v.voter_id for v in matched])
        for vid, tg in zip([v.voter_id for v in matched][:3], ["support", "lean", "undecided"]):
            DB.add_tag(cid, vid, tg)
    from . import ballots as BAL
    BAL.init_schema()
    if STORE.provenance == "illustrative" and BAL.current_election() is None:
        ids = [v.voter_id for v in (PGS.first(1000) if PGS else STORE.all())]
        BAL.seed_illustrative_season(ids)


# ---------- voter serialization ----------
def voter_row(v: Voter) -> dict:
    p = v.protected
    return {"voter_id": v.voter_id, "name": REDACTED if p else v.full_name, "party": v.party.value,
            "county": v.county, "precinct": v.precinct, "status": v.status.value,
            "age": E.age(v, TODAY), "turnout_score": E.turnout_score(v, UNIVERSE),
            "contactable": False if p else bool(v.email or v.phone), "protected": p, "provenance": v.provenance}


def voter_detail(v: Voter) -> dict:
    p = v.protected
    return {**voter_row(v),
            "residence": REDACTED if p else v.residence.one_line(),
            "gender": v.gender.value, "race": v.race.value, "party_raw": v.party_raw,
            "birth_date": v.birth_date.isoformat() if v.birth_date else None,
            "registration_date": v.registration_date.isoformat() if v.registration_date else None,
            "districts": {"congressional": v.congressional_district, "house": v.house_district,
                          "senate": v.senate_district, "county_commission": v.county_commission_district,
                          "school_board": v.school_board_district},
            "phone": "" if p else v.phone, "email": "" if p else v.email,
            "voting_history": [{"date": r.election_date.isoformat(), "type": r.election_type.value,
                                "method": r.method.value} for r in v.voting_history],
            "turnout_basis": TURNOUT_BASIS}


def _run_query(query: str, limit: int = 1000):
    parsed = NL.parse(query, as_of=TODAY, low_propensity_threshold=LOW_PROP)
    matched = E.segment(STORE.all(), parsed.predicate)
    if parsed.low_propensity:
        matched = [v for v in matched if E.turnout_score(v, UNIVERSE) <= LOW_PROP]
    return parsed, matched[:limit]


def _street(v: Voter) -> str:
    ln = v.residence.line1 or ""
    m = re.match(r"\s*\d+\s+(.*)", ln)
    return (m.group(1).strip() if m else ln.strip()) or "(unknown street)"


def _num(v: Voter) -> int:
    m = re.match(r"\s*(\d+)", v.residence.line1 or "")
    return int(m.group(1)) if m else 0


_COUNTY_ANCHORS = {"Miami-Dade": (25.774, -80.194), "Orange": (28.538, -81.379), "Duval": (30.332, -81.656),
                   "Hillsborough": (27.951, -82.457), "Pinellas": (27.876, -82.638)}


def _pseudo_coords(v: Voter):
    """Illustrative map positions for SAMPLE data only (county anchor + stable street hash).
    Real data gets None until the geocoding pipeline runs — the UI says so."""
    if v.provenance != "illustrative":
        return None, None
    import hashlib as _h
    a = _COUNTY_ANCHORS.get(v.county, (27.8, -81.7))
    hs = int(_h.md5((v.county + "|" + _street(v)).encode()).hexdigest()[:8], 16)
    dlat = ((hs % 1000) / 1000 - 0.5) * 0.08
    dlng = (((hs // 1000) % 1000) / 1000 - 0.5) * 0.08
    n = _num(v)
    return (round(a[0] + dlat + (n % 100) * 0.00006, 6), round(a[1] + dlng + ((n // 100) % 10) * 0.00006, 6))


_bootstrap()


# ---------- finance helpers (DB -> engine objects) ----------
def _contribs_for(cid: int):
    out = []
    for r in DB.get_contributions(cid):
        out.append(FIN.Contribution(r["donor_name"], Decimal(r["amount"]), date.fromisoformat(r["date"]),
                                     FIN.Phase(r["phase"]), FIN.Method(r["method"]), r["address"] or "",
                                     r["check_number"] or "", id=str(r["id"]), provenance=r["provenance"]))
    return out


def _expenses_for(cid: int):
    return [FIN.Expense(r["payee"], Decimal(r["amount"]), date.fromisoformat(r["date"]), r["purpose"] or "",
                        id=str(r["id"]), provenance=r["provenance"]) for r in DB.get_expenses(cid)]


def _contrib_dict(c) -> dict:
    return {"id": c.id, "donor_name": c.donor_name, "amount": str(c.amount), "date": c.date.isoformat(),
            "phase": c.phase.value, "method": c.method.value, "address": c.address,
            "check_number": c.check_number, "provenance": c.provenance}


# ---------- request models ----------
class TargetRequest(BaseModel):
    query: str = Field(min_length=1, max_length=500)
    limit: int = Field(default=100, ge=1, le=1000)


class SaveListRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    query: str = Field(min_length=1, max_length=500)
    campaign_id: int = DEFAULT_CID


class CampaignRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    office_type: str = "other"


class TagRequest(BaseModel):
    tag: str = Field(min_length=1, max_length=40)
    campaign_id: int = DEFAULT_CID


class IntakeRequest(BaseModel):
    text: str = Field(min_length=1, max_length=2000)


class ContributionRequest(BaseModel):
    donor_name: str = Field(min_length=1, max_length=200)
    amount: float = Field(gt=0)
    date: str
    phase: str = "general"
    method: str = "check"
    address: str = ""
    check_number: str = ""
    campaign_id: int = DEFAULT_CID


# ---------- core / voters / targeting ----------
@app.get("/health")
def health() -> dict:
    from . import config
    return {"status": "ok", "voters_loaded": _voter_count(), "data_provenance": STORE.provenance,
            "general_elections_in_data": len(UNIVERSE), "turnout_basis": TURNOUT_BASIS,
            "ai_ready": config.has_api_key(), "campaigns": len(DB.list_campaigns())}


@app.get("/summary")
def summary() -> dict:
    summ = PGS.summarize() if PGS else E.summarize(STORE.all())
    return {"provenance_of_records": STORE.provenance, "values_are": "derived", **summ}


@app.get("/counties")
def counties() -> dict:
    if PGS:
        return {"counties": PGS.counties()}
    counts: dict[str, int] = {}
    for v in STORE.all():
        if v.county:
            counts[v.county] = counts.get(v.county, 0) + 1
    return {"counties": dict(sorted(counts.items()))}


@app.get("/voters")
def voters(limit: int = 25) -> dict:
    limit = max(1, min(limit, 1000))
    rows = PGS.first(limit) if PGS else STORE.all()[:limit]
    return {"count": len(rows), "data_provenance": STORE.provenance,
            "results": [voter_row(v) for v in rows]}


@app.get("/voters/search")
def voters_search(q: str, limit: int = 50) -> dict:
    qs = q.strip().lower()
    if len(qs) < 2:
        raise HTTPException(status_code=422, detail="query too short (2+ characters)")
    limit = max(1, min(limit, 200))
    if PGS:
        vs = PGS.search(qs, limit)
        return {"query": q, "count": len(vs), "results": [voter_row(v) for v in vs],
                "data_provenance": STORE.provenance}
    out = []
    for v in STORE.all():
        hay = v.voter_id.lower() if v.protected else " ".join(
            [v.full_name or "", v.residence.one_line() or "", v.voter_id, v.county or ""]).lower()
        if qs in hay:
            out.append(voter_row(v))
            if len(out) >= limit:
                break
    return {"query": q, "count": len(out), "results": out, "data_provenance": STORE.provenance}


@app.get("/voter/{voter_id}")
def voter(voter_id: str, campaign_id: int = DEFAULT_CID) -> dict:
    v = _get_voter(voter_id)
    if v is None:
        raise HTTPException(status_code=404, detail="voter not found")
    d = voter_detail(v)
    d["tags"] = DB.tags_for_voter(campaign_id, voter_id)
    return d


@app.post("/target")
def target(req: TargetRequest) -> dict:
    parsed, matched, total = _segment(req.query, req.limit)
    ai_note = None
    thin = (not parsed.filters and not parsed.low_propensity) or (
        len(parsed.filters) < 2 and not parsed.low_propensity and len(req.query.split()) >= 5)
    if thin:
        from .insights import rephrase_query
        rq = rephrase_query(req.query)
        if rq:
            p2, m2, t2 = _segment(rq, req.limit)
            gain = len(p2.filters) + (1 if p2.low_propensity else 0) > len(parsed.filters) + (1 if parsed.low_propensity else 0)
            if gain:
                parsed, matched, total, ai_note = p2, m2, t2, f'Claude interpreted your phrasing as: "{rq}"'
    filters = list(parsed.filters)
    if parsed.low_propensity:
        filters.append(f"turnout <= {LOW_PROP}")
    return {"understood": {"description": parsed.description, "filters": filters, "warnings": parsed.warnings},
            "ai_note": ai_note,
            "total_matched": total, "returned": len(matched), "data_provenance": STORE.provenance,
            "derived_fields": ["age", "turnout_score", "contactable"], "turnout_basis": TURNOUT_BASIS,
            "results": [voter_row(v) for v in matched]}


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=300)
    campaign_id: int = DEFAULT_CID


@app.post("/ask")
def ask_precinct(req: AskRequest) -> dict:
    from .insights import ask, campaign_snapshot
    rep = FIN.generate_report(_contribs_for(req.campaign_id), _expenses_for(req.campaign_id), "other")
    donors = FIN.donor_intelligence(_contribs_for(req.campaign_id), "other").get("donors", [])
    snap = campaign_snapshot(PGS.summarize() if PGS else E.summarize(STORE.all()), DB.tag_counts(req.campaign_id),
                             [{k: l[k] for k in ("name", "count")} for l in DB.get_lists(req.campaign_id)], rep, donors)
    answer, method = ask(req.question, snap)
    return {"answer": answer, "method": method, "data_provenance": STORE.provenance,
            "note": "advisory analysis over aggregates; no raw voter records are sent to the model"}


# ---------- campaigns (multi-campaign) ----------
@app.get("/campaigns")
def campaigns_list() -> dict:
    return {"campaigns": DB.list_campaigns()}


@app.post("/campaigns")
def campaigns_create(req: CampaignRequest, request: Request) -> dict:
    cid = DB.create_campaign(req.name, req.office_type)
    u = _user(request)
    if u:
        DB.add_membership(u["id"], cid, "owner")
    DB.log_action(cid, "campaign.created", req.name + (f" by {u['email']}" if u else ""))
    return DB.get_campaign(cid)


# ---------- supporter CRM / canvass tags ----------
@app.post("/voter/{voter_id}/tag")
def tag_voter(voter_id: str, req: TagRequest, request: Request) -> dict:
    if _get_voter(voter_id) is None:
        raise HTTPException(status_code=404, detail="voter not found")
    _require_member(request, req.campaign_id)
    DB.add_tag(req.campaign_id, voter_id, req.tag)
    DB.log_action(req.campaign_id, "voter.tagged", f"{voter_id} +{req.tag}")
    return {"voter_id": voter_id, "tags": DB.tags_for_voter(req.campaign_id, voter_id)}


@app.delete("/voter/{voter_id}/tag")
def untag_voter(voter_id: str, tag: str, request: Request = None, campaign_id: int = DEFAULT_CID) -> dict:
    if request is not None:
        _require_member(request, campaign_id)
    DB.remove_tag(campaign_id, voter_id, tag)
    DB.log_action(campaign_id, "voter.untagged", f"{voter_id} -{tag}")
    return {"voter_id": voter_id, "tags": DB.tags_for_voter(campaign_id, voter_id)}


@app.get("/tags")
def tags(campaign_id: int = DEFAULT_CID) -> dict:
    return {"counts": DB.tag_counts(campaign_id)}


@app.get("/supporters")
def supporters(campaign_id: int = DEFAULT_CID, tag: str = "support") -> dict:
    ids = [t["voter_id"] for t in DB.tagged_voters(campaign_id, tag)]
    rows = [{**voter_row(v), "tags": DB.tags_for_voter(campaign_id, v.voter_id)} for v in _get_voters(ids)]
    return {"tag": tag, "count": len(rows), "results": rows, "data_provenance": STORE.provenance}


# ---------- field ops: walk list from a saved list ----------
@app.get("/walklist/{list_id}")
def walklist(list_id: int, campaign_id: int = DEFAULT_CID, turfs: int = 1) -> dict:
    lst = DB.get_list(list_id)
    if not lst:
        raise HTTPException(status_code=404, detail="list not found")
    groups: dict[str, list[Voter]] = {}
    for v in _get_voters(lst["voter_ids"]):
        groups.setdefault(_street(v), []).append(v)
    streets = []
    for st in sorted(groups):
        stops = sorted(groups[st], key=_num)
        streets.append({"street": st, "stops": [
            {**voter_row(x), "address": x.residence.one_line(), "tags": DB.tags_for_voter(campaign_id, x.voter_id),
             "lat": _pseudo_coords(x)[0], "lng": _pseudo_coords(x)[1]}
            for x in stops]})
    turfs = max(1, min(int(turfs), 10))
    bins = [{"turf": i + 1, "streets": [], "doors": 0} for i in range(turfs)]
    for s in sorted(streets, key=lambda x: -len(x["stops"])):
        b = min(bins, key=lambda b: b["doors"])
        b["streets"].append(s)
        b["doors"] += len(s["stops"])
    for b in bins:
        b["streets"].sort(key=lambda s: s["street"])
    return {"list_id": list_id, "name": lst["name"], "streets": streets,
            "turfs": bins, "turf_count": turfs,
            "positions": "illustrative (county anchor + street hash)" if STORE.provenance == "illustrative" else "pending geocoding of the real file",
            "stop_count": sum(len(s["stops"]) for s in streets), "data_provenance": STORE.provenance}


@app.get("/calllist/{list_id}")
def calllist(list_id: int, campaign_id: int = DEFAULT_CID) -> dict:
    lst = DB.get_list(list_id)
    if not lst:
        raise HTTPException(status_code=404, detail="list not found")
    rows = []
    for v in _get_voters(lst["voter_ids"]):
        if v.phone and not v.protected:
            rows.append({**voter_row(v), "phone": v.phone, "tags": DB.tags_for_voter(campaign_id, v.voter_id)})
    return {"list_id": list_id, "name": lst["name"], "count": len(rows), "results": rows,
            "data_provenance": STORE.provenance}


@app.get("/ballots/summary")
def ballots_summary(campaign_id: int = DEFAULT_CID) -> dict:
    from . import ballots as BAL
    return BAL.rollup(campaign_id)


@app.get("/ballots/chase")
def ballots_chase(campaign_id: int = DEFAULT_CID) -> dict:
    """The chase list: supporters/leaners with outstanding mail ballots, full voter rows."""
    from . import ballots as BAL
    raw = BAL.chase_rows(campaign_id)
    status = {r["voter_id"]: r for r in raw}
    out = []
    for v in _get_voters(list(status.keys())):
        s = status[v.voter_id]
        out.append({**voter_row(v), "phone": "" if v.protected else v.phone,
                    "address": "" if v.protected else v.residence.one_line(),
                    "ballot_requested": s["requested"], "ballot_sent": s["sent"],
                    "tags": DB.tags_for_voter(campaign_id, v.voter_id)})
    return {"election": BAL.current_election(), "count": len(out), "results": out,
            "provenance": BAL.season_provenance(),
            "note": "supporters + leaners whose ballots are out but not returned — go get them"}


@app.post("/admin/load-ballots")
async def admin_load_ballots(request: Request, ballots_file: UploadFile = File(...)) -> dict:
    """Ingest a daily absentee/early-vote file. Admin-only, like the voter loader."""
    if not AUTH.enabled():
        raise HTTPException(status_code=403, detail="ballot-file loading requires auth to be enabled (admin-only)")
    u = _user(request)
    if not u or u.get("role") != "admin":
        raise HTTPException(status_code=403, detail="site admin only")
    from . import ballots as BAL
    data = await ballots_file.read()
    if len(data) > 100 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="file too large")
    n = BAL.load_ballot_lines(data.decode("latin-1").splitlines())
    if n == 0:
        raise HTTPException(status_code=422, detail="no ballot rows parsed — check the file format (see ballots.py column map)")
    DB.log_action(0, "admin.ballots_loaded", f"{n} ballot-status rows by {u['email']}")
    return {"loaded": n, "election": BAL.current_election()}


@app.get("/audit")
def audit(campaign_id: int = DEFAULT_CID, limit: int = 20) -> dict:
    return {"events": DB.get_audit(campaign_id, limit)}


# ---------- saved lists / turf (persisted) ----------
@app.post("/lists")
def save_list(req: SaveListRequest, request: Request) -> dict:
    _require_member(request, req.campaign_id)
    _, matched, _total = _segment(req.query)
    lid = DB.save_list(req.campaign_id, req.name, req.query, [v.voter_id for v in matched])
    DB.log_action(req.campaign_id, "list.saved", f"{req.name} ({len(matched)} voters)")
    return {"id": lid, "name": req.name, "count": len(matched)}


@app.get("/lists")
def lists(campaign_id: int = DEFAULT_CID) -> dict:
    return {"lists": [{k: l[k] for k in ("id", "name", "query", "count", "created")} for l in DB.get_lists(campaign_id)]}


@app.get("/lists/{list_id}")
def get_list(list_id: int) -> dict:
    l = DB.get_list(list_id)
    if not l:
        raise HTTPException(status_code=404, detail="list not found")
    rows = [voter_row(v) for v in _get_voters(l["voter_ids"])]
    return {"id": l["id"], "name": l["name"], "query": l["query"], "count": l["count"],
            "created": l["created"], "data_provenance": STORE.provenance, "results": rows}


# ---------- finance & compliance (persisted) + Claude intake ----------
@app.post("/finance/intake")
def finance_intake(req: IntakeRequest) -> dict:
    d, method = read_contribution(req.text, prefer_ai=True)
    return {"draft": {"donor_name": d.donor_name, "amount": d.amount, "date": d.date,
                      "check_number": d.check_number, "address": d.address},
            "read": d.read, "warnings": d.warnings, "method": method}


@app.get("/finance/contributions")
def finance_contribs(campaign_id: int = DEFAULT_CID) -> dict:
    return {"contributions": [_contrib_dict(c) for c in _contribs_for(campaign_id)],
            "expenses": [{"id": e.id, "payee": e.payee, "amount": str(e.amount), "date": e.date.isoformat(),
                          "purpose": e.purpose, "provenance": e.provenance} for e in _expenses_for(campaign_id)],
            "data_provenance": "illustrative"}


@app.post("/finance/contributions")
def add_contrib(req: ContributionRequest, request: Request) -> dict:
    _require_member(request, req.campaign_id)
    try:
        d = date.fromisoformat(req.date)
    except ValueError:
        raise HTTPException(status_code=422, detail="date must be YYYY-MM-DD")
    phase = req.phase if req.phase in FIN.Phase._value2member_map_ else "general"
    method = req.method if req.method in FIN.Method._value2member_map_ else "other"
    lid = DB.add_contribution(req.campaign_id, donor_name=req.donor_name, amount=str(req.amount), date=d.isoformat(),
                              phase=phase, method=method, address=req.address, check_number=req.check_number, provenance="entered")
    DB.log_action(req.campaign_id, "finance.contribution", f"{req.donor_name} ${req.amount}")
    return {"id": lid, "donor_name": req.donor_name, "amount": str(req.amount)}


@app.get("/finance/report")
def finance_report(office: str = "other", campaign_id: int = DEFAULT_CID) -> dict:
    rep = FIN.generate_report(_contribs_for(campaign_id), _expenses_for(campaign_id), office)
    rep["data_provenance"] = "illustrative seed + entered"
    return rep


@app.post("/admin/load-voters")
async def admin_load_voters(request: Request, registration: UploadFile = File(...),
                            history: UploadFile = File(None)) -> dict:
    """Swap the in-memory voter store for a REAL Florida extract zip. Admin-only, auth required."""
    if not AUTH.enabled():
        raise HTTPException(status_code=403, detail="voter-file loading requires auth to be enabled (admin-only)")
    u = _user(request)
    if not u or u.get("role") != "admin":
        raise HTTPException(status_code=403, detail="site admin only")
    import os as _os
    import tempfile
    global STORE, UNIVERSE, BY_ID, TURNOUT_BASIS
    data = await registration.read()
    if len(data) > 100 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="file too large for this instance — load county-by-county")
    with tempfile.TemporaryDirectory() as td:
        rp = _os.path.join(td, "reg.zip")
        open(rp, "wb").write(data)
        hp = ""
        if history is not None and history.filename:
            hp = _os.path.join(td, "hist.zip")
            open(hp, "wb").write(await history.read())
        try:
            if PGS:
                from .store import _read_all_txt_from_zip
                out = _PS.load_extract_lines(_read_all_txt_from_zip(rp),
                                             _read_all_txt_from_zip(hp) if hp else [])
                if out["loaded"] == 0:
                    raise HTTPException(status_code=422, detail="no voters parsed — is this the official registration extract?")
                UNIVERSE = PGS.universe()
                TURNOUT_BASIS = f"share of the {len(UNIVERSE)} general elections present in the loaded dataset"
                DB.log_action(0, "admin.voters_loaded", f"{out['loaded']} voters into Postgres by {u['email']}")
                return {"loaded": out["loaded"], "provenance": "real", "general_elections": len(UNIVERSE)}
            new_store = VoterStore.from_fl_zip(rp, hp)
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=422, detail=f"could not parse the extract: {e}")
    if len(new_store) == 0:
        raise HTTPException(status_code=422, detail="no voters parsed — is this the official registration extract?")
    STORE = new_store
    UNIVERSE = E.election_universe(STORE.all(), types=(ElectionType.GENERAL,))
    BY_ID = {v.voter_id: v for v in STORE.all()}
    TURNOUT_BASIS = f"share of the {len(UNIVERSE)} general elections present in the loaded dataset"
    DB.log_action(0, "admin.voters_loaded", f"{len(STORE)} voters loaded ({STORE.provenance}) by {u['email']}")
    return {"loaded": len(STORE), "provenance": STORE.provenance, "general_elections": len(UNIVERSE)}


class RegisterRequest(BaseModel):
    email: str = Field(min_length=5, max_length=200)
    name: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=8, max_length=200)


class LoginRequest(BaseModel):
    email: str = Field(min_length=5, max_length=200)
    password: str = Field(min_length=1, max_length=200)


@app.post("/auth/register")
def auth_register(req: RegisterRequest) -> dict:
    if not AUTH.enabled():
        raise HTTPException(status_code=400, detail="auth is not enabled on this deployment")
    if not AUTH.signup_open():
        raise HTTPException(status_code=403, detail="signups are closed — ask the site admin for an account")
    try:
        u = AUTH.register(req.email, req.name, req.password)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    DB.log_action(0, "user.registered", f"{u['email']} ({u['role']})")
    return {"registered": True, "email": u["email"], "role": u["role"]}


@app.post("/auth/login")
def auth_login(req: LoginRequest, response: Response) -> dict:
    if not AUTH.enabled():
        raise HTTPException(status_code=400, detail="auth is not enabled on this deployment")
    token = AUTH.login(req.email, req.password)
    if not token:
        raise HTTPException(status_code=401, detail="wrong email or password")
    import os as _os
    response.set_cookie(AUTH.COOKIE, token, max_age=AUTH.SESSION_DAYS * 86400, httponly=True, samesite="lax",
                        secure=_os.environ.get("PRECINCT_COOKIE_SECURE", "1") != "0")
    u = DB.get_user_by_email(req.email.strip().lower())
    DB.log_action(0, "user.login", u["email"])
    return {"ok": True, "name": u["name"], "role": u["role"]}


@app.post("/auth/logout")
def auth_logout(request: Request, response: Response) -> dict:
    AUTH.logout(request.cookies.get(AUTH.COOKIE))
    response.delete_cookie(AUTH.COOKIE)
    return {"ok": True}


@app.get("/auth/me")
def auth_me(request: Request) -> dict:
    if not AUTH.enabled():
        return {"auth": "disabled"}
    u = AUTH.user_from_token(request.cookies.get(AUTH.COOKIE))
    if not u:
        raise HTTPException(status_code=401, detail="not signed in")
    return {"auth": "enabled", "user": u, "memberships": DB.memberships_for_user(u["id"])}


_FRONTEND = Path(__file__).resolve().parent.parent / "console" / "index.html"


@app.get("/")
def frontend() -> FileResponse:
    return FileResponse(str(_FRONTEND))


_OG = Path(__file__).resolve().parent.parent / "console" / "og.png"


@app.get("/og.png")
def og_image() -> FileResponse:
    return FileResponse(str(_OG), media_type="image/png")


# ---------- Module 7 Petitions + Module 8 Fundraising ----------
from . import petitions as PET  # noqa: E402


class SigRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)


@app.get("/fundraising/report")
def fundraising(office: str = "other", campaign_id: int = DEFAULT_CID) -> dict:
    return FIN.donor_intelligence(_contribs_for(campaign_id), office)


@app.get("/petition/{list_id}")
def petition(list_id: int) -> dict:
    l = DB.get_list(list_id)
    if not l:
        raise HTTPException(status_code=404, detail="list not found")
    voters = _get_voters(l["voter_ids"])
    rows = PET.prefilled_rows(voters)
    return {"list_id": list_id, "name": l["name"], "rows": rows, "count": len(rows), "data_provenance": STORE.provenance}


@app.post("/petition/validate")
def petition_validate(req: SigRequest) -> dict:
    pool = PGS.search(req.name.strip().lower(), 500) if PGS else STORE.all()
    return PET.validate_signature(req.name, pool)
