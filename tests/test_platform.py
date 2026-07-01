from fastapi.testclient import TestClient
from precinct.api import app

client = TestClient(app)


def test_campaign_crud():
    r = client.post("/campaigns", json={"name": "Test Race", "office_type": "statewide"})
    assert r.status_code == 200 and r.json()["name"] == "Test Race"
    assert "Test Race" in [c["name"] for c in client.get("/campaigns").json()["campaigns"]]


def test_tag_flow_persists():
    vid = "100000000"
    assert "support" in client.post(f"/voter/{vid}/tag", json={"tag": "support", "campaign_id": 1}).json()["tags"]
    assert client.get("/tags?campaign_id=1").json()["counts"].get("support", 0) >= 1
    assert "support" in client.get(f"/voter/{vid}?campaign_id=1").json()["tags"]   # survives via DB
    client.delete(f"/voter/{vid}/tag?tag=support&campaign_id=1")
    assert "support" not in client.get(f"/voter/{vid}?campaign_id=1").json()["tags"]


def test_list_persist_and_walklist_sorted():
    r = client.post("/lists", json={"name": "Turf A", "query": "Democratic women in Orange county", "campaign_id": 1})
    lid = r.json()["id"]
    assert r.json()["count"] > 0
    assert any(l["id"] == lid for l in client.get("/lists?campaign_id=1").json()["lists"])   # persisted
    wl = client.get(f"/walklist/{lid}?campaign_id=1").json()
    assert wl["stop_count"] > 0 and len(wl["streets"]) > 0
    streets = [s["street"] for s in wl["streets"]]
    assert streets == sorted(streets)


def test_intake_fallback_offline():
    d = client.post("/finance/intake", json={"text": "Jane Doe $250 check #77 05/01/2026"}).json()
    assert d["method"] == "rule-based"                     # AI disabled in tests
    assert d["draft"]["amount"] == "250" and d["draft"]["date"] == "2026-05-01"


def test_add_contribution_persists():
    before = len(client.get("/finance/contributions?campaign_id=1").json()["contributions"])
    client.post("/finance/contributions", json={"donor_name": "New Donor", "amount": 123.45, "date": "2026-05-01", "campaign_id": 1})
    after = len(client.get("/finance/contributions?campaign_id=1").json()["contributions"])
    assert after == before + 1


def test_fundraising_room_to_give():
    d = client.get("/fundraising/report?office=other&campaign_id=1").json()
    assert d["limit"] == "1000"
    bob = [x for x in d["donors"] if x["donor"] == "Bob Lee"][0]
    assert bob["maxed"] is True and bob["room_general"] == "0"        # Bob gave $1300 general -> maxed
    alice = [x for x in d["donors"] if x["donor"] == "Alice Kim"][0]
    assert alice["room_general"] == "500"                            # gave $500 -> $500 room


def test_petition_prefill_and_validate():
    lid = client.post("/lists", json={"name": "Petition turf", "query": "Democratic women in Orange county", "campaign_id": 1}).json()["id"]
    pet = client.get(f"/petition/{lid}").json()
    assert pet["count"] > 0 and "name" in pet["rows"][0]
    some_name = pet["rows"][0]["name"]
    assert client.post("/petition/validate", json={"name": some_name}).json()["match"] == "exact"
    assert client.post("/petition/validate", json={"name": "Zzyzx Nobody"}).json()["match"] == "none"
