import os
from datetime import date

import pytest

pytestmark = pytest.mark.skipif(os.environ.get("PRECINCT_TEST_PG") != "1",
                                reason="needs a real Postgres (PRECINCT_TEST_PG=1)")

if os.environ.get("PRECINCT_TEST_PG") == "1":
    from precinct import db as DB
    from precinct import engine as E
    from precinct import nl_targeting as NL
    from precinct import pg_store as PS
    from precinct.sample_data import load_sample_voters
    from precinct.schema import ElectionType


def _fresh_store():
    PS.init_schema()
    DB._write("DELETE FROM voters")
    voters = load_sample_voters(200, 7)
    uni = E.election_universe(voters, types=(ElectionType.GENERAL,))
    PS.insert_voters(voters, uni)
    return voters, uni, PS.VoterStorePG()


@pytest.fixture(scope="module", autouse=True)
def _restore_suite_store_after_module():
    """This module wipes/replaces the shared voters table — restore the suite's
    400-voter seed afterward so later test modules see the standard universe."""
    yield
    if os.environ.get("PRECINCT_TEST_PG_STORE") == "1":
        from precinct import engine as E2
        from precinct.sample_data import load_sample_voters
        from precinct.schema import ElectionType
        DB._write("DELETE FROM voters")
        vs = load_sample_voters(400, 42)
        PS.insert_voters(vs, E2.election_universe(vs, types=(ElectionType.GENERAL,)))


QUERIES = [
    "Republicans in HD 4",
    "NPA voters 30-45 who voted by mail",
    "low-propensity Democratic women over 50 in Orange county",
    "active democrats in Miami-Dade who skipped 2022",
    "women under 30 who voted in 2020",
]


def test_sql_segment_matches_python_engine_exactly():
    voters, uni, store = _fresh_store()
    assert store.count() == 200
    today = date.today()
    for q in QUERIES:
        parsed = NL.parse(q, as_of=today)
        py = E.segment(voters, parsed.predicate)
        if parsed.low_propensity:
            py = [v for v in py if E.turnout_score(v, uni) <= 0.34]
        total, rows = store.segment(parsed.filters, parsed.low_propensity, 0.34, limit=500, as_of=today)
        assert total == len(py), f"{q}: sql={total} python={len(py)}"
        assert {v.voter_id for v in rows} == {v.voter_id for v in py}, q


def test_summarize_search_and_lookups_match():
    voters, uni, store = _fresh_store()
    ref = E.summarize(voters)
    s = store.summarize()
    assert s["total"] == ref["total"] and s["active"] == ref["active"]
    assert s["by_party"] == ref["by_party"] and s["with_email"] == ref["with_email"]
    target = next(v for v in voters if not v.protected)
    assert any(h.voter_id == target.voter_id for h in store.search(target.name_last.lower(), 200))
    v = store.by_id(voters[5].voter_id)
    assert v and v.party == voters[5].party and v.voting_history == voters[5].voting_history
    got = store.by_ids([voters[3].voter_id, voters[9].voter_id])
    assert [g.voter_id for g in got] == [voters[3].voter_id, voters[9].voter_id]


def test_loader_ingests_official_layout_lines():
    _fresh_store()
    from tests.test_hardening import _fl_zip
    import zipfile
    with zipfile.ZipFile(_fl_zip(5)) as z:
        lines = z.read(z.namelist()[0]).decode().splitlines()
    DB._write("DELETE FROM voters")
    out = PS.load_extract_lines(lines, [])
    store = PS.VoterStorePG()
    assert out["loaded"] == 5 and store.count() == 5
    assert store.provenance == "real"
    assert store.by_id("900000001").name_first == "Real1"



def test_universe_is_shared_across_multicounty_loads_AUDIT5():
    """AUDIT FIX #5: loading a second county whose history adds a new general election
    must re-score the FIRST county's voters against the shared universe — so turnout is
    comparable regardless of load order (was: per-file denominator)."""
    from precinct import pg_store as PS
    from precinct import db as DB
    DB._write("DELETE FROM voters"); DB._write("DELETE FROM voter_meta")
    # county A: one voter, voted GEN 2020 only; batch history has GENs 2020
    a_reg = ["DAD\t900000100\tSmith\t\tAda\t\tN\t1 A St\t\tMiami\tFL\t33101\t\t\t\t\t\t\t\tF\t5\t01/01/1980\t01/01/2010\tDEM\t001\t\t\t\tACT\t\t\t\t\t\t\t\t\t"]
    a_hist = ["DAD\t900000100\t11/03/2020\tGEN\tE"]
    PS.load_extract_lines(a_reg, a_hist)
    score_before = DB.q("SELECT turnout_score FROM voters WHERE voter_id='900000100'")[0]["turnout_score"]
    uni_before = len(PS._load_universe())
    # county B: adds a GEN 2022 to the universe
    b_reg = ["DAD\t900000200\tJones\t\tBob\t\tN\t2 B St\t\tMiami\tFL\t33101\t\t\t\t\t\t\t\tM\t5\t01/01/1980\t01/01/2010\tREP\t002\t\t\t\tACT\t\t\t\t\t\t\t\t\t"]
    b_hist = ["DAD\t900000200\t11/08/2022\tGEN\tE"]
    PS.load_extract_lines(b_reg, b_hist)
    uni_after = len(PS._load_universe())
    score_after = DB.q("SELECT turnout_score FROM voters WHERE voter_id='900000100'")[0]["turnout_score"]
    assert uni_after == uni_before + 1                      # universe grew (2020 -> {2020,2022})
    # Ada voted 1 of 2 generals now, not 1 of 1 -> her comparable score dropped
    assert abs(score_after - 0.5) < 1e-6 and score_before > score_after
    # restore the standard 400-voter seed for later modules
    from precinct import engine as E
    from precinct.sample_data import load_sample_voters
    from precinct.schema import ElectionType
    DB._write("DELETE FROM voters"); DB._write("DELETE FROM voter_meta")
    vs = load_sample_voters(400, 42)
    PS.insert_voters(vs, E.election_universe(vs, types=(ElectionType.GENERAL,)))
