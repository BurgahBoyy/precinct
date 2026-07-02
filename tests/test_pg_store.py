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
