"""Precinct — config & secrets. Loads the Anthropic key; never logs it."""
from __future__ import annotations

import os
from pathlib import Path

_KEY_FILES = ["claude api key.txt", "anthropic_key.txt"]
CLAUDE_MODEL = os.environ.get("PRECINCT_CLAUDE_MODEL", "claude-haiku-4-5-20251001")


def get_api_key() -> str | None:
    if os.environ.get("PRECINCT_DISABLE_AI"):
        return None
    k = os.environ.get("ANTHROPIC_API_KEY")
    if k and k.strip():
        return k.strip()
    cands = []
    ef = os.environ.get("PRECINCT_KEY_FILE")
    if ef:
        cands.append(Path(ef))
    root = Path(__file__).resolve().parent.parent          # precinct/
    for base in (root, root.parent):                        # precinct/ and its parent (Arian Biz)
        for name in _KEY_FILES:
            cands.append(base / name)
    for p in cands:
        try:
            if p.exists():
                v = p.read_text(encoding="utf-8").strip()
                if v:
                    return v
        except Exception:
            pass
    return None


def has_api_key() -> bool:
    return bool(get_api_key())
