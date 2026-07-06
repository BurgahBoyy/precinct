import json

from fastapi.testclient import TestClient
from precinct.api import app

client = TestClient(app)


def _plan():
    r = client.post("/director/brief?campaign_id=1")
    assert r.status_code == 200
    return r.json()


def test_director_plan_offline_rule_based():
    d = _plan()
    assert d["method"] == "rule-based"              # PRECINCT_DISABLE_AI=1 in tests
    assert d["outstanding"] == len(d["actions"])
    assert "{first_name}" not in json.dumps(d)      # merge happened — no raw placeholders leak
    for a in d["actions"]:
        assert a["segment"] in ("OVERDUE", "AGING", "FRESH")
        assert a["channel"] in ("call", "knock")
        assert a["first_name"] and a["first_name"] in a["message"]


def test_director_priority_is_sorted_and_deterministic():
    a1 = _plan()["actions"]
    a2 = _plan()["actions"]
    assert [x["voter_id"] for x in a1] == [x["voter_id"] for x in a2]
    pris = [x["priority"] for x in a1]
    assert pris == sorted(pris, reverse=True)


def test_director_audit_logged():
    _plan()
    ev = client.get("/audit?campaign_id=1").json()["events"]
    assert any(e["action"] == "director.brief" for e in ev)


def test_empty_campaign_gets_empty_plan():
    d = client.post("/director/brief?campaign_id=777").json()
    assert d["actions"] == [] and d["outstanding"] == 0
