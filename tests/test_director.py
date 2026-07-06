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


# --- Director v2: autonomous runs, persistence, scheduling ---
def test_v2_run_persists_a_snapshot():
    d = client.post("/director/run?campaign_id=1").json()
    assert "run_id" in d and d["outstanding"] == len(d["actions"])
    latest = client.get("/director/latest?campaign_id=1").json()["run"]
    assert latest and latest["id"] == d["run_id"] and latest["plan"]["as_of"] == d["as_of"]
    runs = client.get("/director/runs?campaign_id=1").json()["runs"]
    assert any(r["id"] == d["run_id"] for r in runs)


def test_v2_schedule_roundtrip_and_audit():
    r = client.post("/director/schedule?campaign_id=1", json={"enabled": True, "hour": 6, "email": "boss@example.com"}).json()
    assert r["schedule"]["enabled"] == 1 and r["schedule"]["hour"] == 6
    got = client.get("/director/schedule?campaign_id=1").json()["schedule"]
    assert got["email"] == "boss@example.com"
    assert any(e["action"] == "director.schedule" for e in client.get("/audit?campaign_id=1").json()["events"])


def test_v2_heartbeat_runs_enabled_campaigns_and_marks_last_run():
    client.post("/director/schedule?campaign_id=1", json={"enabled": True, "hour": 7, "email": ""})
    out = client.post("/director/run-scheduled").json()
    assert out["count"] >= 1 and any(x.get("campaign_id") == 1 and "run_id" in x for x in out["ran"])
    sc = client.get("/director/schedule?campaign_id=1").json()["schedule"]
    assert sc["last_run"] is not None


def test_v2_heartbeat_token_guard(monkeypatch):
    monkeypatch.setenv("PRECINCT_HEARTBEAT_TOKEN", "s3cret")
    from fastapi.testclient import TestClient
    from precinct.api import app as app2
    c = TestClient(app2)
    assert c.post("/director/run-scheduled").status_code == 403
    assert c.post("/director/run-scheduled?token=s3cret").status_code == 200
