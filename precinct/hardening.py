"""Precinct — production hardening: security headers + per-IP rate limiting.

Headers ride on every response. Rate limits are in-memory sliding windows per
(client-ip, bucket) — per-instance on Cloud Run, which is the honest v1;
a shared store (Redis/Cloud SQL) is the multi-instance follow-up.
Disable in tests/local via PRECINCT_RATELIMIT=0.
"""
from __future__ import annotations

import os
import threading
import time

CSP = ("default-src 'self'; script-src 'self' 'unsafe-inline' https://cdnjs.cloudflare.com; "
       "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com https://cdnjs.cloudflare.com; "
       "font-src https://fonts.gstatic.com; "
       "img-src 'self' data: https://tile.openstreetmap.org https://*.tile.openstreetmap.org; "
       "connect-src 'self'")

HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Content-Security-Policy": CSP,
    "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
    "Permissions-Policy": "geolocation=(), microphone=(), camera=()",
}

LIMITS = {          # bucket: (max requests, window seconds)
    "auth": (10, 60),      # login/register — brute-force guard
    "ai": (20, 60),        # /ask, /finance/intake, /target — Claude cost guard
    "write": (120, 60),    # tags/lists/contributions — abuse guard
}

_LOCK = threading.Lock()
_HITS: dict[tuple, list] = {}


def bucket_for(path: str, method: str) -> str | None:
    if path.startswith("/auth/") and method == "POST":
        return "auth"
    if method == "POST" and path in ("/ask", "/finance/intake", "/target"):
        return "ai"
    if method in ("POST", "DELETE"):
        return "write"
    return None


def allowed(ip: str, bucket: str) -> bool:
    if os.environ.get("PRECINCT_RATELIMIT", "1") == "0":
        return True
    maxn, per = LIMITS[bucket]
    now = time.time()
    key = (ip, bucket)
    with _LOCK:
        if len(_HITS) > 10000:      # bound memory under address churn
            _HITS.clear()
        q = [t for t in _HITS.get(key, []) if now - t < per]
        if len(q) >= maxn:
            _HITS[key] = q
            return False
        q.append(now)
        _HITS[key] = q
    return True


def reset():
    with _LOCK:
        _HITS.clear()
