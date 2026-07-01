from datetime import date
from decimal import Decimal
from fastapi.testclient import TestClient
from precinct import finance as FIN
from precinct.doc_intake import parse_contribution_text
from precinct.api import app

client = TestClient(app)


def C(name, amt, phase=FIN.Phase.GENERAL, method=FIN.Method.CHECK, addr="1 St"):
    return FIN.Contribution(name, Decimal(str(amt)), date(2026, 5, 1), phase, method, addr)


def test_over_limit_flagged():
    flags = FIN.check_compliance([C("Bob", 1000), C("Bob", 300)], "other")  # $1300 general
    assert any(f.severity == "error" and "over the $1000" in f.message for f in flags)


def test_phase_separation_no_error():
    cs = [C("Ann", 600, FIN.Phase.PRIMARY), C("Ann", 600, FIN.Phase.GENERAL)]
    assert [f for f in FIN.check_compliance(cs, "other") if f.severity == "error"] == []


def test_statewide_limit_higher():
    cs = [C("Rich", 2500)]
    assert any(f.severity == "error" for f in FIN.check_compliance(cs, "other"))       # >$1000
    assert [f for f in FIN.check_compliance(cs, "statewide") if f.severity == "error"] == []  # <$3000


def test_cash_limit():
    assert any("cash limit" in f.message for f in FIN.check_compliance([C("Cashy", 200, method=FIN.Method.CASH)], "other"))


def test_totals_pinned():
    t = FIN.totals([C("A", 500), C("B", 250)], [FIN.Expense("X", Decimal("100"), date(2026, 5, 1))])
    assert t["raised"] == Decimal("750") and t["cash_on_hand"] == Decimal("650")


def test_doc_intake_parses():
    d = parse_contribution_text("From John Smith, 123 Main St, $500.00 check #1023 06/15/2026")
    assert d.amount == "500.00" and d.check_number == "1023" and d.date == "06/15/2026"
    assert "John Smith" in d.donor_name
    assert any("human must review" in w for w in d.warnings)   # never auto-commits


def test_api_report_flags_seed_over_limit():
    d = client.get("/finance/report?office=other").json()
    assert d["limit_applied"] == "1000"
    assert any(f["severity"] == "error" for f in d["compliance_flags"])   # Bob Lee seed $1300


def test_api_intake_endpoint():
    r = client.post("/finance/intake", json={"text": "Jane Doe $250 check #77 05/01/2026"})
    assert r.status_code == 200 and r.json()["draft"]["amount"] == "250"
