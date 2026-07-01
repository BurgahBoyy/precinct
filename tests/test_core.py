"""
Precinct core tests — value-pinned (not just direction).
Run from the project root:  python -m pytest -q
"""
from datetime import date

from precinct import engine as E
from precinct import nl_targeting as NL
from precinct.fl_adapter import parse_registration_line, parse_history_line, load_extract
from precinct.schema import (
    Address, ElectionType, Gender, Party, Race, Voter, VoterStatus, VoteMethod, VoteRecord,
)
from precinct.sample_data import load_sample_voters
from precinct.store import VoterStore

AS_OF = date(2026, 7, 1)

# One known FL registration row (38 tab-delimited fields, official order)
_REG_LINE = "\t".join([
    "ORA", "100", "Doe", "", "Jane", "", "N",
    "123 Oak St", "", "Orlando", "FL", "32801",
    "", "", "", "", "", "", "",
    "F", "5", "06/15/1980", "01/10/2010", "DEM",
    "001", "", "", "", "ACT",
    "010", "045", "011", "003", "02",
    "407", "5551234", "", "jane.doe@example.com",
])


def test_adapter_pins_fields():
    v = parse_registration_line(_REG_LINE)
    assert v is not None
    assert v.voter_id == "100"
    assert v.full_name == "Jane Doe"
    assert v.county == "Orange"            # ORA -> Orange via code table
    assert v.party is Party.DEM
    assert v.party_raw == "DEM"
    assert v.gender is Gender.F
    assert v.race is Race.WHITE            # code "5"
    assert v.status is VoterStatus.ACTIVE
    assert v.residence.city == "Orlando"
    assert v.phone == "(407) 5551234"
    assert v.email == "jane.doe@example.com"
    assert v.birth_date == date(1980, 6, 15)
    assert v.provenance == "real"


def test_age_pinned():
    v = parse_registration_line(_REG_LINE)
    assert E.age(v, AS_OF) == 46           # born 1980-06-15, as of 2026-07-01


def test_history_parse_and_join():
    reg = [_REG_LINE]
    hist = [
        "\t".join(["ORA", "100", "11/03/2020", "GEN", "Y"]),   # at polls
        "\t".join(["ORA", "100", "11/08/2022", "GEN", "A"]),   # by mail
        "\t".join(["ORA", "100", "08/23/2022", "PRI", "E"]),   # early
    ]
    (vid, rec) = parse_history_line(hist[1])
    assert vid == "100"
    assert rec.election_type is ElectionType.GENERAL
    assert rec.method is VoteMethod.BY_MAIL

    voters = load_extract(reg, hist)
    assert len(voters) == 1
    assert len(voters[0].voting_history) == 3


def _voter(**kw) -> Voter:
    base = dict(voter_id="X", source_state="FL", county="Orange",
                party=Party.DEM, gender=Gender.F, status=VoterStatus.ACTIVE,
                birth_date=date(1970, 1, 1))
    base.update(kw)
    return Voter(**base)


def test_turnout_score_pinned():
    hist = (
        VoteRecord(date(2020, 11, 3), ElectionType.GENERAL, VoteMethod.AT_POLLS),
        VoteRecord(date(2022, 11, 8), ElectionType.GENERAL, VoteMethod.BY_MAIL),
        # 2024 general skipped
    )
    v = _voter(voting_history=hist)
    universe = {date(2020, 11, 3), date(2022, 11, 8), date(2024, 11, 5)}
    assert E.turnout_score(v, universe) == 0.6667      # 2 of 3


def test_predicates():
    hist = (VoteRecord(date(2022, 11, 8), ElectionType.GENERAL, VoteMethod.BY_MAIL),)
    v = _voter(voting_history=hist)
    assert E.by_party(Party.DEM)(v) is True
    assert E.by_party(Party.REP)(v) is False
    assert E.age_between(50, 60, AS_OF)(v) is True      # born 1970 -> 56
    assert E.voted_by_mail()(v) is True
    assert E.did_not_vote_in(date(2024, 11, 5))(v) is True
    assert E.all_of(E.by_party(Party.DEM), E.voted_by_mail())(v) is True
    assert E.negate(E.by_party(Party.DEM))(v) is False


def test_nl_parse_reads_back_and_matches():
    q = NL.parse("Democratic women over 50 in Orange county who voted by mail", as_of=AS_OF)
    assert "party = DEM" in q.filters
    assert "gender = F" in q.filters
    assert "age > 50" in q.filters
    assert "county = Orange" in q.filters
    assert "has voted by mail" in q.filters

    match = _voter(voting_history=(VoteRecord(date(2022, 11, 8), ElectionType.GENERAL, VoteMethod.BY_MAIL),))
    assert q.predicate(match) is True

    rep_man = _voter(party=Party.REP, gender=Gender.M)
    assert q.predicate(rep_man) is False


def test_bad_input_tolerated():
    assert parse_registration_line("") is None
    assert parse_history_line("junk") is None
    short = parse_registration_line("ORA\t200\tSmith")   # far fewer than 38 fields
    assert short is not None and short.voter_id == "200"


def test_sample_data_is_labelled_and_loads():
    voters = load_sample_voters(n=50, seed=42)
    assert len(voters) == 50
    assert all(v.provenance == "illustrative" for v in voters)   # never mislabelled as real
    store = VoterStore.from_sample(n=50)
    assert len(store) == 50 and store.provenance == "illustrative"


def test_skip_is_eligibility_gated():
    from precinct.nl_targeting import _year_predicate_skipped
    late = _voter(registration_date=date(2023, 1, 1), voting_history=())
    early = _voter(registration_date=date(2018, 1, 1), voting_history=())
    assert _year_predicate_skipped(2022)(late) is False   # registered after -> not a skip
    assert _year_predicate_skipped(2022)(early) is True    # eligible, no ballot -> skip


def test_did_not_vote_is_eligibility_gated():
    late = _voter(registration_date=date(2025, 1, 1))
    assert E.was_eligible(late, date(2022, 11, 8)) is False
    assert E.did_not_vote_in(date(2022, 11, 8))(late) is False   # ineligible != skipped


def test_mailing_none_when_blank():
    v = parse_registration_line(_REG_LINE)   # _REG_LINE has all-blank mailing fields
    assert v.mailing is None


def test_nl_low_propensity_flag():
    assert NL.parse("low turnout Democrats").low_propensity is True
    assert NL.parse("Democrats").low_propensity is False
