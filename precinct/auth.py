"""Precinct — auth (Module 10). Dark-launched: everything no-ops until PRECINCT_AUTH=1.

AUTHN: email+password (stdlib scrypt, per-user salt), opaque session tokens stored
HASHED, HttpOnly cookie. AUTHZ v1: authenticated required for everything except the
public shell; per-campaign membership (owner/manager/volunteer) enforced on writes.
First registered user becomes site admin; signups after that need PRECINCT_ALLOW_SIGNUP=1.
"""
from __future__ import annotations

import hashlib
import os
import secrets
from datetime import datetime, timedelta, timezone

from . import db as DB

COOKIE = "precinct_session"
SESSION_DAYS = 14
_PUBLIC_PATHS = {"/", "/health", "/auth/login", "/auth/register", "/auth/me"}


def enabled() -> bool:
    return os.environ.get("PRECINCT_AUTH", "").strip() in ("1", "true", "yes")


def signup_open() -> bool:
    return DB.count_users() == 0 or os.environ.get("PRECINCT_ALLOW_SIGNUP", "").strip() in ("1", "true", "yes")


def hash_pw(password: str, salt: bytes | None = None) -> tuple[str, str]:
    salt = salt or secrets.token_bytes(16)
    h = hashlib.scrypt(password.encode(), salt=salt, n=16384, r=8, p=1, dklen=32)
    return h.hex(), salt.hex()


def verify_pw(password: str, pw_hash: str, salt_hex: str) -> bool:
    try:
        h = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt_hex), n=16384, r=8, p=1, dklen=32)
        return secrets.compare_digest(h.hex(), pw_hash)
    except Exception:
        return False


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def register(email: str, name: str, password: str) -> dict:
    email = email.strip().lower()
    if DB.get_user_by_email(email):
        raise ValueError("email already registered")
    role = "admin" if DB.count_users() == 0 else "member"
    pw, salt = hash_pw(password)
    uid = DB.create_user(email, name.strip(), pw, salt, role)
    return {"id": uid, "email": email, "name": name.strip(), "role": role}


def login(email: str, password: str) -> str | None:
    u = DB.get_user_by_email(email.strip().lower())
    if not u or not verify_pw(password, u["pw_hash"], u["salt"]):
        return None
    token = secrets.token_urlsafe(32)
    exp = (datetime.now(timezone.utc) + timedelta(days=SESSION_DAYS)).isoformat(timespec="seconds")
    DB.create_session(_token_hash(token), u["id"], exp)
    return token


def logout(token: str | None):
    if token:
        DB.delete_session(_token_hash(token))


def user_from_token(token: str | None) -> dict | None:
    if not token:
        return None
    u = DB.get_session_user(_token_hash(token))
    if not u:
        return None
    if u["expires"] < datetime.now(timezone.utc).isoformat(timespec="seconds"):
        DB.delete_session(_token_hash(token))
        return None
    return {"id": u["id"], "email": u["email"], "name": u["name"], "role": u["role"]}


def is_public(path: str) -> bool:
    return path in _PUBLIC_PATHS or path.startswith("/docs") or path.startswith("/openapi")


def can_write(user: dict | None, campaign_id: int) -> bool:
    """Membership gate for campaign writes. Admin everywhere; volunteers can write (canvass is a write)."""
    if not enabled():
        return True
    if not user:
        return False
    if user.get("role") == "admin":
        return True
    return DB.get_membership(user["id"], campaign_id) is not None
