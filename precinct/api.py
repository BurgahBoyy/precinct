"""Precinct — typed API edge. Bad input -> 422. Values labelled; protected voters redacted.
Persistence via SQLite (db.py); campaigns own tags/lists/finance. Finance intake uses Claude when a key exists."""
from __future__ import annotations

import itertools
import re
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
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

STORE: VoterStore = VoterStore.from_sample(n=400)
UNIVERSE = E.election_universe(STORE.all(), types=(ElectionType.GENERAL,))
TODAY = date.today()
BY_ID = {v.voter_id: v for v in STORE.all()}
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
        _, matched = _run_query(lst_q)
        DB.save_list(cid, "Persuasion turf — mail-first NPAs", lst_q, [v.voter_id for v in matched])
        for vid, tg in zip([v.voter_id for v in matched][:3], ["support", "lean", "undecided"]):
            DB.add_tag(cid, vid, tg)


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
    return {"status": "ok", "voters_loaded": len(STORE), "data_provenance": STORE.provenance,
            "general_elections_in_data": len(UNIVERSE), "turnout_basis": TURNOUT_BASIS,
            "ai_ready": config.has_api_key(), "campaigns": len(DB.list_campaigns())}


@app.get("/summary")
def summary() -> dict:
    return {"provenance_of_records": STORE.provenance, "values_are": "derived", **E.summarize(STORE.all())}


@app.get("/counties")
def counties() -> dict:
    counts: dict[str, int] = {}
    for v in STORE.all():
        if v.county:
            counts[v.county] = counts.get(v.county, 0) + 1
    return {"counties": dict(sorted(counts.items()))}


@app.get("/voters")
def voters(limit: int = 25) -> dict:
    limit = max(1, min(limit, 1000))
    return {"count": min(limit, len(STORE)), "data_provenance": STORE.provenance,
            "results": [voter_row(v) for v in STORE.all()[:limit]]}


@app.get("/voter/{voter_id}")
def voter(voter_id: str, campaign_id: int = DEFAULT_CID) -> dict:
    v = BY_ID.get(voter_id)
    if v is None:
        raise HTTPException(status_code=404, detail="voter not found")
    d = voter_detail(v)
    d["tags"] = DB.tags_for_voter(campaign_id, voter_id)
    return d


@app.post("/target")
def target(req: TargetRequest) -> dict:
    parsed, matched = _run_query(req.query, req.limit)
    filters = list(parsed.filters)
    if parsed.low_propensity:
        filters.append(f"turnout <= {LOW_PROP}")
    return {"understood": {"description": parsed.description, "filters": filters, "warnings": parsed.warnings},
            "total_matched": len(matched), "returned": len(matched), "data_provenance": STORE.provenance,
            "derived_fields": ["age", "turnout_score", "contactable"], "turnout_basis": TURNOUT_BASIS,
            "results": [voter_row(v) for v in matched]}


# ---------- campaigns (multi-campaign) ----------
@app.get("/campaigns")
def campaigns_list() -> dict:
    return {"campaigns": DB.list_campaigns()}


@app.post("/campaigns")
def campaigns_create(req: CampaignRequest) -> dict:
    cid = DB.create_campaign(req.name, req.office_type)
    return DB.get_campaign(cid)


# ---------- supporter CRM / canvass tags ----------
@app.post("/voter/{voter_id}/tag")
def tag_voter(voter_id: str, req: TagRequest) -> dict:
    if voter_id not in BY_ID:
        raise HTTPException(status_code=404, detail="voter not found")
    DB.add_tag(req.campaign_id, voter_id, req.tag)
    return {"voter_id": voter_id, "tags": DB.tags_for_voter(req.campaign_id, voter_id)}


@app.delete("/voter/{voter_id}/tag")
def untag_voter(voter_id: str, tag: str, campaign_id: int = DEFAULT_CID) -> dict:
    DB.remove_tag(campaign_id, voter_id, tag)
    return {"voter_id": voter_id, "tags": DB.tags_for_voter(campaign_id, voter_id)}


@app.get("/tags")
def tags(campaign_id: int = DEFAULT_CID) -> dict:
    return {"counts": DB.tag_counts(campaign_id)}


@app.get("/supporters")
def supporters(campaign_id: int = DEFAULT_CID, tag: str = "support") -> dict:
    ids = [t["voter_id"] for t in DB.tagged_voters(campaign_id, tag)]
    rows = [{**voter_row(BY_ID[i]), "tags": DB.tags_for_voter(campaign_id, i)} for i in ids if i in BY_ID]
    return {"tag": tag, "count": len(rows), "results": rows, "data_provenance": STORE.provenance}


# ---------- field ops: walk list from a saved list ----------
@app.get("/walklist/{list_id}")
def walklist(list_id: int, campaign_id: int = DEFAULT_CID) -> dict:
    lst = DB.get_list(list_id)
    if not lst:
        raise HTTPException(status_code=404, detail="list not found")
    groups: dict[str, list[Voter]] = {}
    for vid in lst["voter_ids"]:
        v = BY_ID.get(vid)
        if v:
            groups.setdefault(_street(v), []).append(v)
    streets = []
    for st in sorted(groups):
        stops = sorted(groups[st], key=_num)
        streets.append({"street": st, "stops": [
            {**voter_row(x), "address": x.residence.one_line(), "tags": DB.tags_for_voter(campaign_id, x.voter_id)}
            for x in stops]})
    return {"list_id": list_id, "name": lst["name"], "streets": streets,
            "stop_count": sum(len(s["stops"]) for s in streets), "data_provenance": STORE.provenance}


# ---------- saved lists / turf (persisted) ----------
@app.post("/lists")
def save_list(req: SaveListRequest) -> dict:
    _, matched = _run_query(req.query)
    lid = DB.save_list(req.campaign_id, req.name, req.query, [v.voter_id for v in matched])
    return {"id": lid, "name": req.name, "count": len(matched)}


@app.get("/lists")
def lists(campaign_id: int = DEFAULT_CID) -> dict:
    return {"lists": [{k: l[k] for k in ("id", "name", "query", "count", "created")} for l in DB.get_lists(campaign_id)]}


@app.get("/lists/{list_id}")
def get_list(list_id: int) -> dict:
    l = DB.get_list(list_id)
    if not l:
        raise HTTPException(status_code=404, detail="list not found")
    rows = [voter_row(BY_ID[vid]) for vid in l["voter_ids"] if vid in BY_ID]
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
def add_contrib(req: ContributionRequest) -> dict:
    try:
        d = date.fromisoformat(req.date)
    except ValueError:
        raise HTTPException(status_code=422, detail="date must be YYYY-MM-DD")
    phase = req.phase if req.phase in FIN.Phase._value2member_map_ else "general"
    method = req.method if req.method in FIN.Method._value2member_map_ else "other"
    lid = DB.add_contribution(req.campaign_id, donor_name=req.donor_name, amount=str(req.amount), date=d.isoformat(),
                              phase=phase, method=method, address=req.address, check_number=req.check_number, provenance="entered")
    return {"id": lid, "donor_name": req.donor_name, "amount": str(req.amount)}


@app.get("/finance/report")
def finance_report(office: str = "other", campaign_id: int = DEFAULT_CID) -> dict:
    rep = FIN.generate_report(_contribs_for(campaign_id), _expenses_for(campaign_id), office)
    rep["data_provenance"] = "illustrative seed + entered"
    return rep


_FRONTEND = Path(__file__).resolve().parent.parent / "console" / "index.html"


@app.get("/")
def frontend() -> FileResponse:
    return FileResponse(str(_FRONTEND))


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
    voters = [BY_ID[vid] for vid in l["voter_ids"] if vid in BY_ID]
    rows = PET.prefilled_rows(voters)
    return {"list_id": list_id, "name": l["name"], "rows": rows, "count": len(rows), "data_provenance": STORE.provenance}


@app.post("/petition/validate")
def petition_validate(req: SigRequest) -> dict:
    return PET.validate_signature(req.name, STORE.all())
