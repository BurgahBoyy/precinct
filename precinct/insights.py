"""Precinct — Ask Precinct + phrasing help (applied AI, Module 2/9).

ask(): answers a plain-English question about THIS campaign from a compact,
pre-computed snapshot (aggregates only — no raw voter PII leaves the app).
rephrase_query(): rewrites free-form phrasing into the targeting grammar.
Claude when a key exists; deterministic rule-based fallback offline.
Advisory analysis only — never actions, never auto-commits anything.
"""
from __future__ import annotations

import json
import re


def campaign_snapshot(summary: dict, tag_counts: dict, lists: list, fin_report: dict, donors: list) -> dict:
    """Aggregates only. Compact on purpose (token budget + privacy)."""
    return {
        "voter_universe": {
            "total": summary.get("total"), "active": summary.get("active"),
            "with_email": summary.get("with_email"),
            "by_party": summary.get("by_party"), "by_county": summary.get("by_county"),
        },
        "canvass_tags": tag_counts,
        "saved_lists": [{"name": l.get("name"), "voters": l.get("count")} for l in lists],
        "finance": {
            "raised": str(fin_report.get("totals", {}).get("raised")),
            "spent": str(fin_report.get("totals", {}).get("spent")),
            "cash_on_hand": str(fin_report.get("totals", {}).get("cash_on_hand")),
            "contributions": fin_report.get("contribution_count"),
            "limit_applied": str(fin_report.get("limit_applied")),
            "compliance_flags": [f.get("message") for f in fin_report.get("compliance_flags", [])],
        },
        "donor_room": [
            {"donor": d.get("donor"), "given_total": str(d.get("given_total")),
             "room_general": str(d.get("room_general")), "maxed": d.get("maxed")}
            for d in donors
        ],
        "data_note": "voter records are an illustrative sample, finance figures are seed+entered demo data",
    }


def rule_answer(question: str, snap: dict) -> str:
    """Deterministic fallback: pick relevant stats by keyword; honest and compact."""
    q = question.lower()
    u, f, t = snap["voter_universe"], snap["finance"], snap["canvass_tags"]
    parts: list[str] = []
    if re.search(r"support|tag|canvass|door|knock|volunteer|lean|undecided|oppose", q):
        parts.append("Canvass tags: " + (", ".join(f"{k} {v}" for k, v in sorted(t.items())) or "none yet") + ".")
    if re.search(r"rais|money|cash|spent|finance|contribut|donat", q):
        parts.append(f"Finance: ${f['raised']} raised, ${f['spent']} spent, ${f['cash_on_hand']} on hand across {f['contributions']} contributions.")
    if re.search(r"max|room|give|ask|donor", q):
        maxed = [d["donor"] for d in snap["donor_room"] if d.get("maxed")]
        openroom = [f"{d['donor']} (${d['room_general']})" for d in snap["donor_room"] if not d.get("maxed")]
        parts.append("Maxed out: " + (", ".join(maxed) or "nobody") + ". Room to give: " + (", ".join(openroom) or "nobody") + ".")
    if re.search(r"list|turf|walk", q):
        parts.append("Saved lists: " + (", ".join(f"{l['name']} ({l['voters']})" for l in snap["saved_lists"]) or "none yet") + ".")
    if re.search(r"voter|universe|party|county|how many|total", q) or not parts:
        parts.append(f"Universe: {u['total']} voters ({u['active']} active, {u['with_email']} with email); parties " +
                     ", ".join(f"{k} {v}" for k, v in (u.get("by_party") or {}).items()) + ".")
    if len(snap["finance"].get("compliance_flags") or []) and re.search(r"complian|flag|legal|limit", q):
        parts.append("Compliance flags: " + " | ".join(snap["finance"]["compliance_flags"]))
    parts.append("(Rule-based summary — sample/demo data.)")
    return " ".join(parts)


def llm_answer(question: str, snap: dict) -> str:
    import anthropic
    from . import config
    client = anthropic.Anthropic(api_key=config.get_api_key())
    msg = client.messages.create(
        model=config.CLAUDE_MODEL, max_tokens=300,
        system=("You are Precinct's campaign data analyst. Answer the manager's question using ONLY the JSON "
                "snapshot provided — cite the actual numbers, be direct, 1-3 sentences, plain language. "
                "If the snapshot can't answer it, say so and name what data would be needed. "
                "Remember the data is an illustrative sample/demo — note that only when scale matters. No advice on breaking election law."),
        messages=[{"role": "user", "content": "SNAPSHOT:\n" + json.dumps(snap) + "\n\nQUESTION: " + question}],
    )
    return msg.content[0].text.strip()


def ask(question: str, snap: dict, prefer_ai: bool = True):
    """Return (answer, method)."""
    from . import config
    if prefer_ai and config.has_api_key():
        try:
            return llm_answer(question, snap), "claude"
        except Exception:
            pass
    return rule_answer(question, snap), "rule-based"


def rephrase_query(query: str) -> str | None:
    """Rewrite free-form phrasing into the targeting grammar. Raises nothing; None on failure."""
    try:
        import anthropic
        from . import config
        if not config.has_api_key():
            return None
        client = anthropic.Anthropic(api_key=config.get_api_key())
        msg = client.messages.create(
            model=config.CLAUDE_MODEL, max_tokens=80,
            system=("Rewrite the user's voter-targeting request as ONE plain line in the style of these examples: "
                    "'Republican men under 40 in Duval county' | 'low-propensity Democratic women over 50 in Orange county who voted by mail' | "
                    "'NPA voters 30-45 who voted by mail' | 'active Democrats in Miami-Dade who skipped 2022' | 'Republicans in HD 35' | 'women in senate district 14'. "
                    "Include ONLY constraints the user actually stated — never add low-propensity, active, or anything they didn't say. "
                    "Party words: Democratic, Republican, NPA, Green, Libertarian ('red'=Republican, 'blue'=Democratic). "
                    "No brackets, no quotes, no prose — just the query line. If it is not a voter-targeting request, return exactly: NO"),
            messages=[{"role": "user", "content": query[:300]}],
        )
        out = msg.content[0].text.strip().strip('"')
        if not out or out.upper() == "NO" or len(out) > 200:
            return None
        return out
    except Exception:
        return None
