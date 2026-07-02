import os, tempfile
os.environ["PRECINCT_DB"] = os.path.join(tempfile.mkdtemp(), "test.db")
os.environ["PRECINCT_DISABLE_AI"] = "1"   # deterministic, offline: intake uses the rule-based path
os.environ["PRECINCT_COOKIE_SECURE"] = "0"  # TestClient runs over http
os.environ["PRECINCT_RATELIMIT"] = "0"  # deterministic tests; the rate-limit test re-enables it

# --- optional: run the WHOLE suite against a real Postgres (test db) ---------
# PRECINCT_TEST_PG=1 [PRECINCT_TEST_PG_VIA_CONNECTOR=1 PRECINCT_TEST_PG_INSTANCE=proj:region:inst]
if os.environ.get("PRECINCT_TEST_PG") == "1":
    os.environ.setdefault("PRECINCT_PG_DB", "precinct_test")
    if os.environ.get("PRECINCT_TEST_PG_VIA_CONNECTOR") == "1":
        from google.cloud.sql.connector import Connector
        from precinct import db as _db
        _connector = Connector()
        _inst = os.environ["PRECINCT_TEST_PG_INSTANCE"]
        def _factory():
            return _connector.connect(_inst, "pg8000",
                                      user=os.environ.get("PRECINCT_PG_USER", "precinct_app"),
                                      password=os.environ.get("PRECINCT_PG_PASSWORD", ""),
                                      db=os.environ.get("PRECINCT_PG_DB", "precinct_test"))
        _db._connect_pg_factory = _factory
        os.environ.setdefault("PRECINCT_PG_HOST", "via-connector")   # any non-empty value => PG mode
    from precinct import db as _dbr
    _c = _dbr.conn()
    _cur = _c.cursor()
    for _t in ("audit", "memberships", "sessions", "users", "expenses", "contributions", "lists", "voter_tags", "campaigns"):
        _cur.execute(f"DROP TABLE IF EXISTS {_t} CASCADE")
    _cur.close()
    _dbr._reset_connection()   # next conn() rebuilds a fresh schema; api import then seeds it
