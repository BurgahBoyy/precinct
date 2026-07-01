"""Precinct — Finance & Compliance (pure engine). Money as Decimal. FL limits cited."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import Enum
from typing import Optional

# FL contribution limits PER ELECTION (primary and general are separate elections).
# Source: FL Division of Elections / s.106.08, Fla. Stat. — statewide (& Supreme Court
# retention) $3,000; all other offices $1,000.  [REAL — cited]
FL_LIMITS = {"statewide": Decimal("3000"), "other": Decimal("1000")}
FL_CASH_LIMIT = Decimal("50")  # s.106.09 cash contribution cap [REAL]


class Phase(str, Enum):
    PRIMARY = "primary"
    GENERAL = "general"


class Method(str, Enum):
    CHECK = "check"
    CARD = "card"
    CASH = "cash"
    IN_KIND = "in_kind"
    OTHER = "other"


@dataclass
class Contribution:
    donor_name: str
    amount: Decimal
    date: date
    phase: Phase = Phase.GENERAL
    method: Method = Method.CHECK
    address: str = ""
    check_number: str = ""
    occupation: str = ""
    memo: str = ""
    id: str = ""
    provenance: str = "illustrative"


@dataclass
class Expense:
    payee: str
    amount: Decimal
    date: date
    purpose: str = ""
    method: Method = Method.CHECK
    id: str = ""
    provenance: str = "illustrative"


@dataclass
class Flag:
    severity: str   # "error" | "warning"
    message: str
    ref: str = ""


def totals(contribs, expenses) -> dict:
    raised = sum((c.amount for c in contribs), Decimal("0"))
    spent = sum((e.amount for e in expenses), Decimal("0"))
    return {"raised": raised, "spent": spent, "cash_on_hand": raised - spent}


def aggregate_by_donor(contribs, phase: Optional[Phase] = None) -> dict:
    agg: dict[str, Decimal] = {}
    for c in contribs:
        if phase and c.phase != phase:
            continue
        agg[c.donor_name] = agg.get(c.donor_name, Decimal("0")) + c.amount
    return agg


def check_compliance(contribs, office: str = "other") -> list[Flag]:
    limit = FL_LIMITS.get(office, FL_LIMITS["other"])
    flags: list[Flag] = []
    for phase in Phase:  # limits apply per election (primary/general separate)
        for donor, total in aggregate_by_donor(contribs, phase).items():
            if total > limit:
                flags.append(Flag("error",
                    f"{donor} gave ${total} in the {phase.value} election — over the "
                    f"${limit} FL limit for {office} office (per election).", donor))
    for c in contribs:
        if not c.donor_name or not c.address:
            flags.append(Flag("warning",
                f"Contribution from '{c.donor_name or '(unknown)'}' is missing required donor name/address.", c.id))
        if c.method == Method.CASH and c.amount > FL_CASH_LIMIT:
            flags.append(Flag("error",
                f"Cash contribution ${c.amount} from {c.donor_name} exceeds the FL ${FL_CASH_LIMIT} cash limit.", c.id))
    return flags


def generate_report(contribs, expenses, office: str = "other") -> dict:
    t = totals(contribs, expenses)
    return {
        "totals": {k: str(v) for k, v in t.items()},
        "contribution_count": len(contribs),
        "expense_count": len(expenses),
        "by_donor": {k: str(v) for k, v in sorted(aggregate_by_donor(contribs).items(), key=lambda kv: -kv[1])},
        "compliance_flags": [{"severity": f.severity, "message": f.message, "ref": f.ref}
                             for f in check_compliance(contribs, office)],
        "office_type": office,
        "limit_applied": str(FL_LIMITS.get(office, FL_LIMITS["other"])),
    }


def donor_intelligence(contribs, office: str = "other") -> dict:
    """Per-donor giving + how much more they can LEGALLY give this election (limit - given in general)."""
    limit = FL_LIMITS.get(office, FL_LIMITS["other"])
    donors: dict[str, dict] = {}
    for c in contribs:
        d = donors.setdefault(c.donor_name, {"total": Decimal("0"), "general": Decimal("0")})
        d["total"] += c.amount
        if c.phase == Phase.GENERAL:
            d["general"] += c.amount
    out = []
    for name, d in donors.items():
        room = limit - d["general"]
        out.append({"donor": name, "given_total": str(d["total"]), "given_general": str(d["general"]),
                    "room_general": str(room if room > 0 else Decimal("0")), "maxed": d["general"] >= limit})
    out.sort(key=lambda x: -Decimal(x["given_total"]))
    return {"office": office, "limit": str(limit), "donors": out}
