"""Precinct — document-reading intake (Module 5, applied to finance).

Turns a messy human string (a pasted check memo, a receipt line) into a DRAFT
contribution a human then approves. Deterministic parser today; llm_extract() is
the Claude-with-tools seam for real scanned documents. Never auto-commits.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class DraftContribution:
    donor_name: str = ""
    amount: Optional[str] = None
    date: Optional[str] = None
    check_number: str = ""
    address: str = ""
    read: list = field(default_factory=list)
    warnings: list = field(default_factory=list)


def parse_contribution_text(text: str) -> DraftContribution:
    d = DraftContribution()
    read: list[str] = []

    m = re.search(r"\$\s*([0-9][0-9,]*(?:\.\d{2})?)", text)
    if m:
        d.amount = m.group(1).replace(",", ""); read.append(f"amount ${d.amount}")

    m = re.search(r"(?:check|chk|ck)\s*#?\s*(\d{2,6})|#\s*(\d{2,6})", text, re.I)
    if m:
        d.check_number = m.group(1) or m.group(2); read.append(f"check #{d.check_number}")

    m = re.search(r"(\d{1,2}/\d{1,2}/\d{2,4})", text)
    if m:
        d.date = m.group(1); read.append(f"date {d.date}")

    mn = re.search(r"[Ff]rom\s+([A-Z][a-zA-Z.'-]+(?:\s+[A-Z][a-zA-Z.'-]+)+)", text)
    if mn:
        d.donor_name = mn.group(1).strip()
    else:
        first = text.split(",")[0].strip()
        first = re.sub(r"^\s*from\s+", "", first, flags=re.I)
        if first and not first.startswith("$") and re.match(r"[A-Za-z]", first):
            d.donor_name = re.sub(r"\s*\$.*$", "", first).strip()
    if d.donor_name:
        read.append(f"donor {d.donor_name}")

    ma = re.search(r"\d+\s+[A-Za-z0-9 .'-]+?\b(?:st|street|ave|avenue|rd|road|blvd|dr|drive|way|ln|lane|ct)\b\.?", text, re.I)
    if ma:
        d.address = ma.group(0).strip(); read.append("address")

    if not d.amount:
        d.warnings.append("No dollar amount found.")
    if not d.donor_name:
        d.warnings.append("No donor name found.")
    d.warnings.append("AI-drafted — a human must review before this is committed or filed.")
    d.read = read
    return d


def _norm_date(v):
    if not v:
        return None
    v = str(v).strip()
    m = re.match(r"(\d{1,2})/(\d{1,2})/(\d{2,4})", v)
    if m:
        mo, d, y = m.groups()
        y = ("20" + y) if len(y) == 2 else y
        return f"{y}-{int(mo):02d}-{int(d):02d}"
    return v  # assume already ISO


def llm_extract(text: str) -> DraftContribution:
    """Real Claude extraction for messy documents. Raises on any error (caller falls back)."""
    import json
    import anthropic
    from . import config
    client = anthropic.Anthropic(api_key=config.get_api_key())
    msg = client.messages.create(
        model=config.CLAUDE_MODEL, max_tokens=400,
        system=("Extract campaign-contribution fields from messy text. Return ONLY minified JSON with keys "
                "donor_name, amount (number in dollars or null), date (YYYY-MM-DD or null), "
                "check_number (string or null), address (string or null). Unknown -> null. No prose."),
        messages=[{"role": "user", "content": text}],
    )
    raw = msg.content[0].text.strip()
    mo = re.search(r"\{.*\}", raw, re.DOTALL)
    data = json.loads(mo.group(0) if mo else raw)
    d = DraftContribution()
    d.donor_name = (data.get("donor_name") or "")
    amt = data.get("amount")
    d.amount = str(amt) if amt not in (None, "") else None
    d.date = _norm_date(data.get("date"))
    d.check_number = str(data.get("check_number") or "")
    d.address = data.get("address") or ""
    d.read = [lbl for lbl, v in [("donor " + d.donor_name, d.donor_name), ("amount $" + (d.amount or ""), d.amount),
                                 ("date " + (d.date or ""), d.date), ("check #" + d.check_number, d.check_number),
                                 ("address", d.address)] if v]
    d.warnings = ["Read by Claude (AI). A human must review before this is committed or filed."]
    return d


def read_contribution(text: str, prefer_ai: bool = True):
    """Return (DraftContribution, method). Tries Claude when a key exists; always falls back to rules."""
    from . import config
    if prefer_ai and config.has_api_key():
        try:
            return llm_extract(text), "claude"
        except Exception:
            pass
    d = parse_contribution_text(text)
    d.date = _norm_date(d.date)
    return d, "rule-based"
