"""
Precinct — pure targeting engine (the build-kit "pure core").

Primitives in, plain values out. No DB, no network, no globals, no creds.
Deterministic when callers pass an explicit as_of (the API always does); value-pinned by tests.

Derived metrics are labelled "derived" wherever they surface. The turnout score
is an honest, dataset-relative propensity — NOT a black-box model:
    turnout_score(voter) = (counted ballots the voter cast in the window)
                           / (elections that actually occurred in the window,
                              as observed across the loaded dataset)
So a voter who voted in 3 of the 4 general elections present in the data scores 0.75.
"""
from __future__ import annotations

from datetime import date
from typing import Callable, Iterable, Optional

from .schema import ElectionType, Party, Voter, VoterStatus, VoteMethod

Predicate = Callable[[Voter], bool]


# --- derived metrics -------------------------------------------------------

def age(voter: Voter, as_of: Optional[date] = None) -> Optional[int]:
    """Age in whole years, or None if birth date is unknown/protected."""
    if voter.birth_date is None:
        return None
    ref = as_of or date.today()
    yrs = ref.year - voter.birth_date.year
    if (ref.month, ref.day) < (voter.birth_date.month, voter.birth_date.day):
        yrs -= 1
    return yrs


def counted_votes(voter: Voter,
                  types: tuple[ElectionType, ...] = (ElectionType.GENERAL,),
                  since: Optional[date] = None) -> int:
    """Number of ballots the voter actually cast (that counted) matching the filter."""
    n = 0
    for r in voter.voting_history:
        if r.election_type not in types:
            continue
        if since and r.election_date < since:
            continue
        if r.method.counted:
            n += 1
    return n


def election_universe(voters: Iterable[Voter],
                      types: tuple[ElectionType, ...] = (ElectionType.GENERAL,),
                      since: Optional[date] = None) -> set[date]:
    """The set of election dates that actually appear in the data for the given types/window."""
    u: set[date] = set()
    for v in voters:
        for r in v.voting_history:
            if r.election_type in types and (not since or r.election_date >= since):
                u.add(r.election_date)
    return u


def turnout_score(voter: Voter, universe: set[date],
                  types: tuple[ElectionType, ...] = (ElectionType.GENERAL,)) -> float:
    """Dataset-relative propensity in [0.0, 1.0]. Empty universe -> 0.0 (undefined)."""
    if not universe:
        return 0.0
    voted = {
        r.election_date for r in voter.voting_history
        if r.election_type in types and r.method.counted and r.election_date in universe
    }
    return round(len(voted) / len(universe), 4)


# --- predicate builders ----------------------------------------------------

def by_party(*parties: Party) -> Predicate:
    s = set(parties)
    return lambda v: v.party in s


def by_status(*statuses: VoterStatus) -> Predicate:
    s = set(statuses)
    return lambda v: v.status in s


def by_county(*counties: str) -> Predicate:
    s = {c.lower() for c in counties}
    return lambda v: v.county.lower() in s


def in_precinct(*precincts: str) -> Predicate:
    s = set(precincts)
    return lambda v: v.precinct in s


def by_district(kind: str, *values: str) -> Predicate:
    """kind in {'congressional','house','senate','county_commission','school_board'}."""
    attr = f"{kind}_district"
    s = set(values)
    return lambda v: getattr(v, attr, "") in s


def age_between(low: int, high: int, as_of: Optional[date] = None) -> Predicate:
    def _p(v: Voter) -> bool:
        a = age(v, as_of)
        return a is not None and low <= a <= high
    return _p


def gender_is(code: str) -> Predicate:
    return lambda v: v.gender.value == code.upper()


def voted_by_mail(types: tuple[ElectionType, ...] = (ElectionType.GENERAL, ElectionType.PRIMARY),
                  since: Optional[date] = None) -> Predicate:
    def _p(v: Voter) -> bool:
        for r in v.voting_history:
            if r.method == VoteMethod.BY_MAIL and r.election_type in types:
                if not since or r.election_date >= since:
                    return True
        return False
    return _p


def voted_in(election_date: date) -> Predicate:
    return lambda v: any(
        r.election_date == election_date and r.method.counted for r in v.voting_history
    )


def was_eligible(voter: Voter, election_date: date) -> bool:
    """Registered on/before the election (unknown reg date -> assume eligible)."""
    return voter.registration_date is None or voter.registration_date <= election_date


def did_not_vote_in(election_date: date) -> Predicate:
    """True only if the voter WAS eligible but cast no counted ballot (a real skip)."""
    return lambda v: was_eligible(v, election_date) and not any(
        r.election_date == election_date and r.method.counted for r in v.voting_history
    )


# --- combinators -----------------------------------------------------------

def all_of(*preds: Predicate) -> Predicate:
    return lambda v: all(p(v) for p in preds)


def any_of(*preds: Predicate) -> Predicate:
    return lambda v: any(p(v) for p in preds)


def negate(pred: Predicate) -> Predicate:
    return lambda v: not pred(v)


# --- segmentation & summary ------------------------------------------------

def segment(voters: Iterable[Voter], predicate: Predicate) -> list[Voter]:
    """Pure filter: the voters matching the predicate."""
    return [v for v in voters if predicate(v)]


def summarize(voters: list[Voter]) -> dict:
    """Derived roll-up for a dashboard. Every value here is provenance='derived'."""
    by_party: dict[str, int] = {}
    by_county: dict[str, int] = {}
    active = 0
    with_email = 0
    for v in voters:
        by_party[v.party.value] = by_party.get(v.party.value, 0) + 1
        if v.county:
            by_county[v.county] = by_county.get(v.county, 0) + 1
        if v.status == VoterStatus.ACTIVE:
            active += 1
        if v.email:
            with_email += 1
    return {
        "total": len(voters),
        "active": active,
        "with_email": with_email,
        "by_party": dict(sorted(by_party.items(), key=lambda kv: -kv[1])),
        "by_county": dict(sorted(by_county.items(), key=lambda kv: -kv[1])),
    }
