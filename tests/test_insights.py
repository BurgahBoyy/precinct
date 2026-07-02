from fastapi.testclient import TestClient
from precinct.api import app

client = TestClient(app)


def test_ask_answers_offline_rule_based():
    r = client.post("/ask", json={"question": "how much have we raised and who is maxed out?", "campaign_id": 1})
    assert r.status_code == 200
    d = r.json()
    assert d["method"] == "rule-based"          # PRECINCT_DISABLE_AI=1 in conftest
    assert "raised" in d["answer"].lower()
    assert "Bob Lee" in d["answer"]             # seeded maxed donor


def test_ask_validates_input():
    assert client.post("/ask", json={"question": "", "campaign_id": 1}).status_code == 422


def test_target_gibberish_stays_honest_offline():
    r = client.post("/target", json={"query": "qqq zzz vvv www", "limit": 5})
    assert r.status_code == 200
    d = r.json()
    assert d["ai_note"] is None                  # no AI offline; no fake filters invented
    assert d["understood"]["filters"] == []
