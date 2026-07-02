import os, tempfile
os.environ["PRECINCT_DB"] = os.path.join(tempfile.mkdtemp(), "test.db")
os.environ["PRECINCT_DISABLE_AI"] = "1"   # deterministic, offline: intake uses the rule-based path
os.environ["PRECINCT_COOKIE_SECURE"] = "0"  # TestClient runs over http
