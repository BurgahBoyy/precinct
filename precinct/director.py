"""Precinct — the Director (agentic layer, v1).

The verdict said it plainly: incumbents SHOW campaigns their data; nobody RUNS the
work. The Director closes the loop for the VBM chase: every morning it ranks who
to contact first, assigns the channel, and writes the outreach — so a campaign
opens Precinct to a finished plan, not a report.

Privacy posture (hard rule, same as Ask Precinct): the AI sees AGGREGATES ONLY —
segment counts, day-ranges, turnout buckets. It writes the strategy narrative and
one message TEMPLATE per segment with a {first_name} placeholder; THIS module
mail-merges real names locally. No voter PII ever reaches the model.

Deterministic core (works with AI off):
  priority = ballot-age urgency + low-turnout need + tag strength.
  Segments: OVERDUE (sent >14d) · AGING (7-14d) · FRESH (<7d).
"""
from __future__ import annotations

import json
import re
from datetime import date

from . import ballots as BAL
from . import db as DB

SEGMENTS = ("OVERDUE", "AGING", "FRESH")
_SEG_DEF = {"OVERDUE": "ballot out more than 14 days — highest risk of never returning",
            "AGING": "ballot out 7-14 days — nudge now before it goes stale",
            "FRESH": "ballot out under 7 days — light touch, confirm it's coming back"}


def _days_since(iso: str, today: date) -> int | None:
    try:
        return max(0, (today - date.fromisoformat(iso)).days)   # future-dated (illustrative) -> 0, never negative
    except Exception:
        return None


def _segment(days_out) -> str:
    if days_out is None:
        return "AGING"
    if days_out > 14:
        return "OVERDUE"
    if days_out >= 7:
        return "AGING"
    return "FRESH"


def build_plan(campaign_id: int, voters_by_id, today: date | None = None,
               tags: tuple = ("support", "lean")) -> dict:
    """Deterministic plan: prioritized, segmented, channel-assigned chase actions.
    `voters_by_id(ids) -> list[Voter]` is injected so both stores work."""
    today = today or date.today()
    raw = BAL.chase_rows(campaign_id, tags)
    status = {r["voter_id"]: r for r in raw}
    actions = []
    for v in voters_by_id(list(status.keys())):
        s = status[v.voter_id]
        ref = s.get("sent") or s.get("requested") or ""
        days_out = _days_since(ref, today)
        turnout = 0.0
        try:
            from . import engine as E
            from .api import UNIVERSE
            turnout = E.turnout_score(v, UNIVERSE)
        except Exception:
            pass
        vtags = DB.tags_for_voter(campaign_id, v.voter_id)
        tag_w = 2 if "support" in vtags else 1
        priority = (min(days_out or 7, 30) * 2) + int((1 - turnout) * 20) + tag_w * 5
        actions.append({
            "voter_id": v.voter_id,
            "first_name": (v.name_first or "there").title(),
            "name": "[protected]" if v.protected else v.full_name,
            "phone": "" if v.protected else v.phone,
            "address": "" if v.protected else v.residence.one_line(),
            "party": v.party.value, "county": v.county,
            "days_out": days_out, "turnout_pct": round(turnout * 100),
            "tags": vtags,
            "segment": _segment(days_out),
            "channel": "call" if (v.phone and not v.protected) else "knock",
            "priority": priority,
        })
    actions.sort(key=lambda a: -a["priority"])
    seg_counts = {s: sum(1 for a in actions if a["segment"] == s) for s in SEGMENTS}
    roll = BAL.rollup(campaign_id, tags)
    election = roll.get("election")
    days_to_election = None
    if election:
        m = re.match(r"(\d{4}-\d{2}-\d{2})", election)
        if m:
            days_to_election = (date.fromisoformat(m.group(1)) - today).days
    return {"campaign_id": campaign_id, "as_of": today.isoformat(), "election": election,
            "days_to_election": days_to_election,
            "segments": [{"key": s, "count": seg_counts[s], "meaning": _SEG_DEF[s]} for s in SEGMENTS],
            "actions": actions,
            "banked": roll.get("supporters", {}).get("banked", 0),
            "outstanding": roll.get("supporters", {}).get("outstanding", 0),
            "season_provenance": roll.get("provenance", "none")}


# ---------- the AI half: brief + message templates from AGGREGATES ONLY ----------
def _aggregates(plan: dict) -> dict:
    return {"election": plan["election"], "days_to_election": plan["days_to_election"],
            "banked": plan["banked"], "outstanding": plan["outstanding"],
            "segments": plan["segments"],
            "channel_mix": {"call": sum(1 for a in plan["actions"] if a["channel"] == "call"),
                            "knock": sum(1 for a in plan["actions"] if a["channel"] == "knock")},
            "low_turnout_share_pct": round(100 * sum(1 for a in plan["actions"] if a["turnout_pct"] <= 34)
                                           / max(1, len(plan["actions"])))}


def rule_brief(plan: dict) -> tuple[str, dict]:
    segs = {s["key"]: s["count"] for s in plan["segments"]}
    dte = plan["days_to_election"]
    brief = (f"{plan['outstanding']} of your supporters still have ballots out"
             + (f" with {dte} days to election" if dte is not None else "") + ". "
             f"Start with the {segs.get('OVERDUE', 0)} OVERDUE (out >14 days — highest risk), "
             f"then the {segs.get('AGING', 0)} AGING. Calls first where we have phones; knock the rest. "
             f"{plan['banked']} are already banked. (Rule-based plan — AI narrative offline.)")
    templates = {
        "OVERDUE": "Hi {first_name}, it's the campaign — your mail ballot went out a while back and we want to make sure your voice counts. Can you drop it in the mail today, or would a ballot drop box be easier?",
        "AGING": "Hi {first_name}! Quick reminder from the campaign — your mail ballot is sitting at home. Five minutes today locks in your vote. Need anything?",
        "FRESH": "Hi {first_name}, your mail ballot should have just arrived. When it does, we'd love for you to send it right back — every early return helps us focus on the doors that need it.",
    }
    return brief, templates


def ai_brief(plan: dict) -> tuple[str, dict, str]:
    """Claude writes the narrative + one template per segment. Aggregates only. Falls back to rules."""
    from . import config
    if not config.has_api_key():
        b, t = rule_brief(plan)
        return b, t, "rule-based"
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=config.get_api_key())
        msg = client.messages.create(
            model=config.CLAUDE_MODEL, max_tokens=700,
            system=("You are Precinct's field director. From the aggregate ballot-chase snapshot, write "
                    "(1) 'brief': a punchy 2-4 sentence morning plan for the campaign manager — what to do TODAY and why, cite the numbers; "
                    "(2) 'templates': one short friendly SMS-length outreach message per segment key (OVERDUE, AGING, FRESH), each MUST contain the literal placeholder {first_name}, "
                    "encouraging returning the mail ballot. Never invent voter names or data. Tone: warm, urgent where deserved, zero pressure tactics. "
                    "Return ONLY minified JSON: {\"brief\": str, \"templates\": {\"OVERDUE\": str, \"AGING\": str, \"FRESH\": str}}"),
            messages=[{"role": "user", "content": json.dumps(_aggregates(plan))}],
        )
        raw = msg.content[0].text.strip()
        mo = re.search(r"\{.*\}", raw, re.DOTALL)
        data = json.loads(mo.group(0) if mo else raw)
        templates = data.get("templates", {})
        if not all(k in templates and "{first_name}" in templates[k] for k in SEGMENTS):
            raise ValueError("bad templates")
        return data["brief"], templates, "claude"
    except Exception:
        b, t = rule_brief(plan)
        return b, t, "rule-based"


def merged_actions(plan: dict, templates: dict) -> list[dict]:
    """LOCAL mail-merge — names never left this process."""
    out = []
    for a in plan["actions"]:
        t = templates.get(a["segment"], "")
        out.append({**a, "message": t.replace("{first_name}", a["first_name"])})
    return out
