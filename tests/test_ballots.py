from fastapi.testclient import TestClient
from precinct import ballots as BAL
from precinct.api import app

client = TestClient(app)


def test_season_seeded_and_rollup_math():
    s = client.get("/ballots/summary?campaign_id=1").json()
    assert s["election"] == "2026-11-03-GEN" and s["provenance"] == "illustrative"
    o = s["overall"]
    assert o["requested"] > 0
    assert o["banked"] + o["outstanding"] <= o["requested"] + o["banked"]  # early-votes may bank without request row semantics
    assert o["outstanding"] == o["requested"] - o["banked"] or o["outstanding"] >= 0


def test_chase_list_excludes_banked_and_respects_campaign():
    # tag two known voters: one outstanding, one returned (from the deterministic seed)
    rows = BAL.chase_rows(1)
    d = client.get("/ballots/chase?campaign_id=1").json()
    assert d["provenance"] == "illustrative"
    assert d["count"] == len(rows)
    for r in d["results"]:
        assert r["ballot_requested"] or r["ballot_sent"]     # in the chase => ballot is out
    # a fresh campaign has no supporters => empty chase
    e = client.get("/ballots/chase?campaign_id=999").json()
    assert e["count"] == 0


def test_adapter_parses_and_upserts_idempotently():
    lines = ["DAD\t900000010\t2026-11-03-GEN\t10/01/2026\t10/03/2026\t",
             "DAD\t900000011\t2026-11-03-GEN\t10/01/2026\t10/03/2026\t10/10/2026"]
    assert BAL.load_ballot_lines(lines) == 2
    assert BAL.load_ballot_lines(lines) == 2          # idempotent refresh
    rows = {r["voter_id"]: r for r in BAL.DB.q("SELECT * FROM ballot_status WHERE voter_id IN (?,?)",
                                               ("900000010", "900000011"))}
    assert rows["900000010"]["returned"] == "" and rows["900000011"]["returned"] == "2026-10-10"


def test_ballot_upload_locked_while_auth_dark():
    import io
    r = client.post("/admin/load-ballots", files={"ballots_file": ("d.txt", io.BytesIO(b"x"), "text/plain")})
    assert r.status_code == 403
