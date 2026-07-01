from datetime import date
from fastapi.testclient import TestClient
from precinct.api import app, voter_detail
from precinct.schema import Address, Party, Voter, VoterStatus

client = TestClient(app)


def test_health_ok():
    r = client.get("/health")
    assert r.status_code == 200
    d = r.json()
    assert d["data_provenance"] == "illustrative"
    assert "turnout_basis" in d


def test_target_values():
    r = client.post("/target", json={"query": "Democratic women in Orange county"})
    assert r.status_code == 200
    d = r.json()
    assert "party = DEM" in d["understood"]["filters"]
    assert d["data_provenance"] == "illustrative"
    assert all(row["provenance"] == "illustrative" for row in d["results"])


def test_low_prop_no_duplicate_filter():
    d = client.post("/target", json={"query": "low-propensity Democrats"}).json()
    assert d["understood"]["filters"].count("turnout <= 0.34") == 1   # structured, not fragile string dup


def test_bad_input_422():
    assert client.post("/target", json={"query": ""}).status_code == 422


def test_voter_404():
    assert client.get("/voter/NOPE").status_code == 404


def _protected() -> Voter:
    return Voter(voter_id="P1", source_state="FL", protected=True, name_first="Jane", name_last="Doe",
                 residence=Address(line1="123 Secret St", city="Orlando", state="FL", zipcode="32801"),
                 phone="(407) 5550000", email="jane@x.com", party=Party.DEM, county="Orange",
                 status=VoterStatus.ACTIVE, birth_date=date(1980, 1, 1))


def test_protected_voter_is_redacted():
    d = voter_detail(_protected())
    assert d["name"] == "[protected]"
    assert d["residence"] == "[protected]"
    assert d["phone"] == "" and d["email"] == ""
    assert d["contactable"] is False and d["protected"] is True
