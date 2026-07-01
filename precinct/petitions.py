"""Precinct — petitions & ballot access. Pre-filled petition rows + signature validation vs the roll."""
from __future__ import annotations

import re


def _norm(s: str) -> str:
    return re.sub(r"[^a-z ]", "", (s or "").lower()).strip()


def prefilled_rows(voters) -> list[dict]:
    """One pre-filled petition line per voter (protected voters excluded from printed sheets)."""
    return [{"voter_id": v.voter_id, "name": v.full_name, "address": v.residence.one_line(),
             "precinct": v.precinct} for v in voters if not v.protected]


def validate_signature(name: str, voters) -> dict:
    """Match a signed name against the voter roll: exact, partial (last name), or none."""
    n = _norm(name)
    if not n:
        return {"match": "none"}
    exact = [v for v in voters if _norm(v.full_name) == n]
    if exact:
        return {"match": "exact", "voter_id": exact[0].voter_id, "name": exact[0].full_name}
    last = n.split()[-1]
    cands = [v for v in voters if _norm(v.name_last) == last]
    if cands:
        return {"match": "partial", "candidates": [{"voter_id": c.voter_id, "name": c.full_name} for c in cands[:5]]}
    return {"match": "none"}
