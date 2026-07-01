"""Precinct — natural-language targeting (the AI seam). Rule-based default; llm_parse() is the Claude seam."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from typing import Optional

from . import engine as E
from .schema import ElectionType, Party, VoterStatus, VoteMethod, Voter

MAX_AGE = 130
LOW_PROP_WORDS = ("low propensity", "low-propensity", "low turnout", "unlikely", "sporadic")


@dataclass
class ParsedQuery:
    predicate: E.Predicate
    description: str
    filters: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    low_propensity: bool = False


_PARTY_WORDS = {
    Party.DEM: ("democrat", "democratic", "dem ", "dems", "blue"),
    Party.REP: ("republican", "republicans", "gop", "rep ", "reps", "red"),
    Party.NPA: ("npa", "no party", "unaffiliated", "independent voters", "independents"),
    Party.LIB: ("libertarian",),
    Party.GRN: ("green party",),
}


def _year_predicate_voted(year: int) -> E.Predicate:
    return lambda v: any(r.election_date.year == year and r.method.counted for r in v.voting_history)


def _year_predicate_skipped(year: int) -> E.Predicate:
    def _p(v: Voter) -> bool:
        if v.registration_date is not None and v.registration_date.year > year:
            return False  # not yet registered that year -> not a real skip
        return not any(r.election_date.year == year and r.method.counted for r in v.voting_history)
    return _p


def parse(text: str, as_of: Optional[date] = None, low_propensity_threshold: float = 0.34) -> ParsedQuery:
    t = f" {text.lower().strip()} "
    preds: list[E.Predicate] = []
    filters: list[str] = []
    warnings: list[str] = []

    for party, words in _PARTY_WORDS.items():
        if any(w in t for w in words):
            preds.append(E.by_party(party)); filters.append(f"party = {party.value}"); break

    if any(w in t for w in (" women", " woman", " female", " females")):
        preds.append(E.gender_is("F")); filters.append("gender = F")
    elif any(w in t for w in (" men ", " man ", " male", " males")):
        preds.append(E.gender_is("M")); filters.append("gender = M")

    m = (re.search(r"between\s+(\d{1,3})\s+and\s+(\d{1,3})", t)
         or re.search(r"\b(\d{1,3})\s*(?:-|–|to)\s*(\d{1,3})\b", t))
    if m:
        lo, hi = sorted((int(m.group(1)), int(m.group(2))))
        preds.append(E.age_between(lo, hi, as_of)); filters.append(f"age {lo}-{hi}")
    else:
        mo = re.search(r"(?:over|older than|above)\s+(\d{1,3})", t) or re.search(r"\b(\d{1,3})\s*\+", t)
        mu = re.search(r"(?:under|younger than|below)\s+(\d{1,3})", t)
        if mo:
            preds.append(E.age_between(int(mo.group(1)) + 1, MAX_AGE, as_of)); filters.append(f"age > {mo.group(1)}")
        if mu:
            preds.append(E.age_between(0, int(mu.group(1)) - 1, as_of)); filters.append(f"age < {mu.group(1)}")

    mc = re.search(r"in\s+([a-z][a-z .'-]+?)\s+county", t) or re.search(r"\bcounty\s+([a-z][a-z .'-]+)", t)
    if mc:
        county = mc.group(1).strip().title()
        preds.append(E.by_county(county)); filters.append(f"county = {county}")

    if " inactive" in t:
        preds.append(E.by_status(VoterStatus.INACTIVE)); filters.append("status = inactive")
    elif " active" in t:
        preds.append(E.by_status(VoterStatus.ACTIVE)); filters.append("status = active")

    if any(w in t for w in ("voted by mail", "vote by mail", "vote-by-mail", "vbm", "absentee")):
        preds.append(E.voted_by_mail()); filters.append("has voted by mail")

    for mm in re.finditer(r"(skipped|did ?n[o']?t vote in|didnt vote in)\s+(\d{4})", t):
        yr = int(mm.group(2)); preds.append(_year_predicate_skipped(yr)); filters.append(f"skipped {yr}")
    for mm in re.finditer(r"voted in\s+(\d{4})", t):
        yr = int(mm.group(1)); preds.append(_year_predicate_voted(yr)); filters.append(f"voted in {yr}")

    low_prop = any(w in t for w in LOW_PROP_WORDS)
    if low_prop:
        warnings.append("low-propensity is a DERIVED filter applied after segmentation "
                        "(relative to the general elections in the loaded dataset).")

    if not preds and not low_prop:
        warnings.append("No filters recognized — returning everyone. Try naming a party, age, county, or behavior.")
        predicate: E.Predicate = lambda v: True
    else:
        predicate = E.all_of(*preds) if preds else (lambda v: True)

    desc = " AND ".join(filters) if filters else ("low turnout only" if low_prop else "all voters")
    return ParsedQuery(predicate=predicate, description=desc, filters=filters, warnings=warnings, low_propensity=low_prop)


def wants_low_propensity(text: str) -> bool:
    t = text.lower()
    return any(w in t for w in LOW_PROP_WORDS)


def llm_parse(text: str) -> ParsedQuery:  # pragma: no cover - seam
    raise NotImplementedError("LLM parser not wired yet - rule-based parse() is the default.")
