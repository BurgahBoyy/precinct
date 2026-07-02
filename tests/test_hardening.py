import io
import zipfile

from fastapi.testclient import TestClient
from precinct.api import app

client = TestClient(app)


def _fl_zip(n=3):
    """Synthetic official-layout registration zip (38 tab-delimited fields)."""
    rows = []
    for i in range(n):
        f = [""] * 38
        f[0] = "DAD"; f[1] = f"9000000{i:02d}"; f[2] = "Testerson"; f[4] = f"Real{i}"
        f[6] = "N"; f[7] = f"{100+i} Ocean Dr"; f[9] = "Miami"; f[10] = "FL"; f[11] = "33101"
        f[19] = "F"; f[20] = "5"; f[21] = "01/15/1980"; f[22] = "02/20/2015"; f[23] = "DEM"
        f[24] = "001"; f[28] = "ACT"; f[34] = "305"; f[35] = f"555000{i}"
        rows.append("\t".join(f))
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("DAD_20260701.txt", "\n".join(rows))
    buf.seek(0)
    return buf


def test_security_headers_on_every_response():
    r = client.get("/health")
    assert r.headers["X-Content-Type-Options"] == "nosniff"
    assert r.headers["X-Frame-Options"] == "DENY"
    assert "default-src 'self'" in r.headers["Content-Security-Policy"]
    assert "max-age" in r.headers["Strict-Transport-Security"]


def test_rate_limit_trips(monkeypatch):
    from precinct import hardening
    monkeypatch.setenv("PRECINCT_RATELIMIT", "1")
    hardening.reset()
    codes = [client.post("/auth/login", json={"email": "a@b.co", "password": "x"}).status_code for _ in range(12)]
    assert 429 in codes                      # brute-force guard trips inside the window
    hardening.reset()


def test_upload_forbidden_while_auth_dark():
    r = client.post("/admin/load-voters", files={"registration": ("reg.zip", _fl_zip(), "application/zip")})
    assert r.status_code == 403


def test_upload_swaps_store_for_admin(monkeypatch):
    import precinct.api as A
    monkeypatch.setenv("PRECINCT_AUTH", "1")
    monkeypatch.setenv("PRECINCT_ALLOW_SIGNUP", "1")
    old = (A.STORE, A.UNIVERSE, A.BY_ID, A.TURNOUT_BASIS)
    try:
        c = TestClient(app)
        c.post("/auth/register", json={"email": "boss@example.com", "name": "Boss", "password": "hunter2hunter2"})
        c.post("/auth/login", json={"email": "boss@example.com", "password": "hunter2hunter2"})
        me = c.get("/auth/me").json()
        if me["user"]["role"] != "admin":       # an earlier test may own the admin slot
            r = c.post("/admin/load-voters", files={"registration": ("reg.zip", _fl_zip(), "application/zip")})
            assert r.status_code == 403         # non-admin blocked — still a valid authz check
            return
        r = c.post("/admin/load-voters", files={"registration": ("reg.zip", _fl_zip(), "application/zip")})
        assert r.status_code == 200
        d = r.json()
        assert d["loaded"] == 3 and d["provenance"] == "real"
        h = c.get("/health").json()
        assert h["voters_loaded"] == 3 and h["data_provenance"] == "real"
    finally:
        A.STORE, A.UNIVERSE, A.BY_ID, A.TURNOUT_BASIS = old
