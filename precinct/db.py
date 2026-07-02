"""Precinct — persistence (SQLite, stdlib). User-generated data survives restart.
DB path from env PRECINCT_DB, else <project>/precinct.db. One connection, thread-safe writes."""
from __future__ import annotations

import json
import os
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

_DB_PATH = os.environ.get("PRECINCT_DB", str(Path(__file__).resolve().parent.parent / "precinct.db"))
_lock = threading.Lock()
_conn: sqlite3.Connection | None = None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def conn() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        _conn = sqlite3.connect(_DB_PATH, check_same_thread=False)
        _conn.row_factory = sqlite3.Row
        _conn.executescript("""
        CREATE TABLE IF NOT EXISTS campaigns(id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, office_type TEXT, created TEXT);
        CREATE TABLE IF NOT EXISTS voter_tags(campaign_id INT, voter_id TEXT, tag TEXT, created TEXT, UNIQUE(campaign_id,voter_id,tag));
        CREATE TABLE IF NOT EXISTS lists(id INTEGER PRIMARY KEY AUTOINCREMENT, campaign_id INT, name TEXT, query TEXT, voter_ids TEXT, count INT, created TEXT);
        CREATE TABLE IF NOT EXISTS contributions(id INTEGER PRIMARY KEY AUTOINCREMENT, campaign_id INT, donor_name TEXT, amount TEXT, date TEXT, phase TEXT, method TEXT, address TEXT, check_number TEXT, provenance TEXT, created TEXT);
        CREATE TABLE IF NOT EXISTS expenses(id INTEGER PRIMARY KEY AUTOINCREMENT, campaign_id INT, payee TEXT, amount TEXT, date TEXT, purpose TEXT, provenance TEXT, created TEXT);
        CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY AUTOINCREMENT, campaign_id INT, action TEXT, detail TEXT, created TEXT);
        CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY AUTOINCREMENT, email TEXT UNIQUE, name TEXT, pw_hash TEXT, salt TEXT, role TEXT, created TEXT);
        CREATE TABLE IF NOT EXISTS sessions(token_hash TEXT UNIQUE, user_id INT, expires TEXT, created TEXT);
        CREATE TABLE IF NOT EXISTS memberships(user_id INT, campaign_id INT, role TEXT, created TEXT, UNIQUE(user_id,campaign_id));
        """)
        _conn.commit()
    return _conn


def _write(sql: str, args=()):
    with _lock:
        cur = conn().execute(sql, args)
        conn().commit()
        return cur.lastrowid


# --- campaigns ---
def create_campaign(name: str, office_type: str = "other") -> int:
    return _write("INSERT INTO campaigns(name,office_type,created) VALUES(?,?,?)", (name, office_type, _now()))

def list_campaigns() -> list[dict]:
    return [dict(r) for r in conn().execute("SELECT * FROM campaigns ORDER BY id")]

def get_campaign(cid: int) -> dict | None:
    r = conn().execute("SELECT * FROM campaigns WHERE id=?", (cid,)).fetchone()
    return dict(r) if r else None


# --- voter tags (CRM + canvass capture) ---
def add_tag(cid: int, voter_id: str, tag: str):
    _write("INSERT OR IGNORE INTO voter_tags(campaign_id,voter_id,tag,created) VALUES(?,?,?,?)", (cid, voter_id, tag, _now()))

def remove_tag(cid: int, voter_id: str, tag: str):
    _write("DELETE FROM voter_tags WHERE campaign_id=? AND voter_id=? AND tag=?", (cid, voter_id, tag))

def tags_for_voter(cid: int, voter_id: str) -> list[str]:
    return [r["tag"] for r in conn().execute("SELECT tag FROM voter_tags WHERE campaign_id=? AND voter_id=?", (cid, voter_id))]

def tagged_voters(cid: int, tag: str | None = None) -> list[dict]:
    if tag:
        rows = conn().execute("SELECT voter_id,tag FROM voter_tags WHERE campaign_id=? AND tag=?", (cid, tag))
    else:
        rows = conn().execute("SELECT voter_id,tag FROM voter_tags WHERE campaign_id=?", (cid,))
    return [dict(r) for r in rows]

def tag_counts(cid: int) -> dict:
    return {r["tag"]: r["n"] for r in conn().execute("SELECT tag,COUNT(*) n FROM voter_tags WHERE campaign_id=? GROUP BY tag", (cid,))}


# --- saved lists / turf ---
def save_list(cid: int, name: str, query: str, voter_ids: list[str]) -> int:
    return _write("INSERT INTO lists(campaign_id,name,query,voter_ids,count,created) VALUES(?,?,?,?,?,?)",
                  (cid, name, query, json.dumps(voter_ids), len(voter_ids), _now()))

def get_lists(cid: int) -> list[dict]:
    return [{**dict(r), "voter_ids": json.loads(r["voter_ids"])}
            for r in conn().execute("SELECT * FROM lists WHERE campaign_id=? ORDER BY id DESC", (cid,))]

def get_list(lid: int) -> dict | None:
    r = conn().execute("SELECT * FROM lists WHERE id=?", (lid,)).fetchone()
    if not r:
        return None
    d = dict(r); d["voter_ids"] = json.loads(d["voter_ids"]); return d


# --- finance ---
def add_contribution(cid: int, **f) -> int:
    return _write("INSERT INTO contributions(campaign_id,donor_name,amount,date,phase,method,address,check_number,provenance,created) VALUES(?,?,?,?,?,?,?,?,?,?)",
                  (cid, f["donor_name"], f["amount"], f["date"], f["phase"], f["method"], f.get("address", ""), f.get("check_number", ""), f.get("provenance", "entered"), _now()))

def get_contributions(cid: int) -> list[dict]:
    return [dict(r) for r in conn().execute("SELECT * FROM contributions WHERE campaign_id=? ORDER BY id", (cid,))]

def add_expense(cid: int, payee: str, amount: str, date: str, purpose: str, provenance: str = "entered") -> int:
    return _write("INSERT INTO expenses(campaign_id,payee,amount,date,purpose,provenance,created) VALUES(?,?,?,?,?,?,?)",
                  (cid, payee, amount, date, purpose, provenance, _now()))

def get_expenses(cid: int) -> list[dict]:
    return [dict(r) for r in conn().execute("SELECT * FROM expenses WHERE campaign_id=? ORDER BY id", (cid,))]


# --- users / sessions / memberships (auth; dark until PRECINCT_AUTH=1) ---
def count_users() -> int:
    return conn().execute("SELECT COUNT(*) n FROM users").fetchone()["n"]

def create_user(email: str, name: str, pw_hash: str, salt: str, role: str) -> int:
    return _write("INSERT INTO users(email,name,pw_hash,salt,role,created) VALUES(?,?,?,?,?,?)",
                  (email, name, pw_hash, salt, role, _now()))

def get_user_by_email(email: str) -> dict | None:
    r = conn().execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
    return dict(r) if r else None

def create_session(token_hash: str, user_id: int, expires: str):
    _write("INSERT OR REPLACE INTO sessions(token_hash,user_id,expires,created) VALUES(?,?,?,?)",
           (token_hash, user_id, expires, _now()))

def get_session_user(token_hash: str) -> dict | None:
    r = conn().execute("SELECT u.id,u.email,u.name,u.role,s.expires FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.token_hash=?",
                       (token_hash,)).fetchone()
    return dict(r) if r else None

def delete_session(token_hash: str):
    _write("DELETE FROM sessions WHERE token_hash=?", (token_hash,))

def add_membership(user_id: int, campaign_id: int, role: str = "manager"):
    _write("INSERT OR IGNORE INTO memberships(user_id,campaign_id,role,created) VALUES(?,?,?,?)",
           (user_id, campaign_id, role, _now()))

def get_membership(user_id: int, campaign_id: int) -> dict | None:
    r = conn().execute("SELECT * FROM memberships WHERE user_id=? AND campaign_id=?", (user_id, campaign_id)).fetchone()
    return dict(r) if r else None

def memberships_for_user(user_id: int) -> list[dict]:
    return [dict(r) for r in conn().execute("SELECT campaign_id,role FROM memberships WHERE user_id=?", (user_id,))]


# --- audit trail (every write, compliance posture) ---
def log_action(cid: int, action: str, detail: str = ""):
    _write("INSERT INTO audit(campaign_id,action,detail,created) VALUES(?,?,?,?)", (cid, action, (detail or "")[:300], _now()))

def get_audit(cid: int, limit: int = 20) -> list[dict]:
    limit = max(1, min(int(limit), 100))
    return [dict(r) for r in conn().execute("SELECT action,detail,created FROM audit WHERE campaign_id=? ORDER BY id DESC LIMIT ?", (cid, limit))]
