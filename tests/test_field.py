from fastapi.testclient import TestClient
from precinct.api import app

client = TestClient(app)


def test_voter_search_finds_by_name():
    r = client.get("/voters/search?q=patricia")
    assert r.status_code == 200
    d = r.json()
    assert d["count"] >= 1 and all("Patricia" in x["name"] for x in d["results"] if x["name"] != "[protected]")


def test_voter_search_rejects_short():
    assert client.get("/voters/search?q=a").status_code == 422


def test_turf_split_covers_all_doors():
    r = client.get("/walklist/1?campaign_id=1&turfs=3")
    assert r.status_code == 200
    d = r.json()
    assert d["turf_count"] == 3 and len(d["turfs"]) == 3
    assert sum(t["doors"] for t in d["turfs"]) == d["stop_count"]
    biggest_street = max(len(s["stops"]) for s in d["streets"])
    doors = [t["doors"] for t in d["turfs"]]
    assert max(doors) - min(doors) <= biggest_street  # greedy balance bound


def test_calllist_only_phone_holders():
    r = client.get("/calllist/1?campaign_id=1")
    assert r.status_code == 200
    d = r.json()
    assert d["count"] >= 1 and all(x.get("phone") for x in d["results"])


def test_audit_records_tag_write():
    client.post("/voter/100000002/tag", json={"tag": "lean", "campaign_id": 1})
    ev = client.get("/audit?campaign_id=1").json()["events"]
    assert any(e["action"] == "voter.tagged" and "100000002" in e["detail"] for e in ev)
