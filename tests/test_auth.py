import os
from fastapi.testclient import TestClient
from precinct.api import app

client = TestClient(app)


def test_auth_disabled_by_default():
    assert client.get("/auth/me").json() == {"auth": "disabled"}
    assert client.get("/summary").status_code == 200   # open access


def test_full_auth_flow_when_enabled(monkeypatch):
    monkeypatch.setenv("PRECINCT_AUTH", "1")
    c = TestClient(app)
    # gate closed without a session
    assert c.get("/summary").status_code == 401
    # public shell still reachable
    assert c.get("/health").status_code == 200
    # first signup allowed -> becomes admin
    r = c.post("/auth/register", json={"email": "rob@example.com", "name": "Rob", "password": "hunter2hunter2"})
    assert r.status_code == 200 and r.json()["role"] == "admin"
    # signups now closed (no PRECINCT_ALLOW_SIGNUP)
    assert c.post("/auth/register", json={"email": "x@example.com", "name": "X", "password": "hunter2hunter2"}).status_code == 403
    # wrong password rejected
    assert c.post("/auth/login", json={"email": "rob@example.com", "password": "wrong"}).status_code == 401
    # login sets the session cookie; gate opens
    r = c.post("/auth/login", json={"email": "rob@example.com", "password": "hunter2hunter2"})
    assert r.status_code == 200
    assert c.get("/summary").status_code == 200
    me = c.get("/auth/me").json()
    assert me["user"]["email"] == "rob@example.com" and me["user"]["role"] == "admin"
    # admin can write anywhere (campaign 1 exists from seeds)
    assert c.post("/voter/100000003/tag", json={"tag": "lean", "campaign_id": 1}).status_code == 200
    # creating a campaign grants owner membership
    cid = c.post("/campaigns", json={"name": "Authed Race", "office_type": "other"}).json()["id"]
    assert {"campaign_id": cid, "role": "owner"} in c.get("/auth/me").json()["memberships"]
    # logout closes the gate
    c.post("/auth/logout")
    assert c.get("/summary").status_code == 401


def test_membership_required_for_writes(monkeypatch):
    monkeypatch.setenv("PRECINCT_AUTH", "1")
    monkeypatch.setenv("PRECINCT_ALLOW_SIGNUP", "1")
    c = TestClient(app)
    c.post("/auth/register", json={"email": "vol@example.com", "name": "Vol", "password": "hunter2hunter2"})
    c.post("/auth/login", json={"email": "vol@example.com", "password": "hunter2hunter2"})
    # not a member of campaign 1 -> writes forbidden, reads fine
    assert c.get("/summary").status_code == 200
    assert c.post("/voter/100000004/tag", json={"tag": "lean", "campaign_id": 1}).status_code == 403
