"""
Precinct — synthetic sample data (LABELLED ILLUSTRATIVE).

These are NOT real voters. They are generated in the exact Florida extract
format and parsed through the real fl_adapter, so (a) the parser is exercised
end-to-end and (b) the whole app runs before the real disk arrives. Every
record returned here is stamped provenance="illustrative".

Deterministic (seeded) so the demo numbers are stable.
"""
from __future__ import annotations

import random
from datetime import date

from .fl_adapter import load_extract
from .schema import Voter

# Fixed election calendar present in the sample history (for turnout scoring / year filters)
_GENERALS = ["11/03/2020", "11/08/2022", "11/05/2024"]
_PRIMARIES = ["08/18/2020", "08/23/2022", "08/20/2024"]

_COUNTIES = ["ORA", "DAD", "DUV", "HIL", "PIN"]           # Orange, Miami-Dade, Duval, Hillsborough, Pinellas
_PARTIES = ["DEM", "REP", "NPA", "NPA", "LPF", "GRE"]      # NPA weighted up (realistic)
_FIRST_F = ["Maria", "Jennifer", "Ashley", "Linda", "Patricia", "Sofia", "Grace", "Denise"]
_FIRST_M = ["James", "Robert", "Michael", "Carlos", "David", "Andre", "Hassan", "Peter"]
_LAST = ["Smith", "Johnson", "Garcia", "Nguyen", "Williams", "Brown", "Davis", "Martinez", "Lee", "Clark"]
_STREETS = ["Oak St", "Palm Ave", "Main St", "Bayshore Blvd", "Pine Dr", "Lake Rd", "Sunset Way"]


def generate_fl_lines(n: int = 200, seed: int = 42) -> tuple[list[str], list[str]]:
    """Return (registration_lines, history_lines) in official FL tab-delimited format."""
    rng = random.Random(seed)
    reg_lines: list[str] = []
    hist_lines: list[str] = []

    for i in range(n):
        vid = f"{100000000 + i}"
        county = rng.choice(_COUNTIES)
        gender = rng.choice(["F", "M"])
        first = rng.choice(_FIRST_F if gender == "F" else _FIRST_M)
        last = rng.choice(_LAST)
        party = rng.choice(_PARTIES)
        race = rng.choice(["1", "2", "3", "4", "5", "6"])
        birth_year = rng.randint(1945, 2006)
        birth = f"{rng.randint(1,12):02d}/{rng.randint(1,28):02d}/{birth_year}"
        reg = f"{rng.randint(1,12):02d}/{rng.randint(1,28):02d}/{rng.randint(2004,2024)}"
        precinct = f"{rng.randint(1,60):03d}"
        cong = f"{rng.randint(1,28):03d}"
        house = f"{rng.randint(1,120):03d}"
        senate = f"{rng.randint(1,40):03d}"
        status = "ACT" if rng.random() > 0.12 else "INA"
        email = f"{first.lower()}.{last.lower()}{i}@example.com" if rng.random() > 0.4 else ""
        area = rng.choice(["407", "305", "904", "813", "727"])
        phone = f"{rng.randint(2000000, 9999999)}" if rng.random() > 0.5 else ""

        # 38 tab-delimited fields, exact order per the official layout
        fields = [
            county, vid, last, "", first, "", "N",
            f"{rng.randint(100,9999)} {rng.choice(_STREETS)}", "",
            county.title(), "FL", f"3{rng.randint(1000,4999)}",
            "", "", "", "", "", "", "",          # mailing (blank)
            gender, race, birth, reg, party,
            precinct, "", "", "", status,
            cong, house, senate, f"{rng.randint(1,7):03d}", f"{rng.randint(1,9):02d}",
            area, phone, "", email,
        ]
        reg_lines.append("\t".join(fields))

        # voting history: propensity tier drives how many elections they show up in
        tier = rng.random()
        for d in _GENERALS:
            if rng.random() < (0.9 if tier > 0.66 else 0.5 if tier > 0.33 else 0.2):
                method = "A" if rng.random() < 0.45 else ("E" if rng.random() < 0.4 else "Y")
                hist_lines.append("\t".join([county, vid, d, "GEN", method]))
        for d in _PRIMARIES:
            if rng.random() < (0.7 if tier > 0.66 else 0.3 if tier > 0.33 else 0.1):
                method = "A" if rng.random() < 0.5 else "Y"
                hist_lines.append("\t".join([county, vid, d, "PRI", method]))

    return reg_lines, hist_lines


def load_sample_voters(n: int = 200, seed: int = 42) -> list[Voter]:
    """Parse synthetic FL lines through the real adapter; stamp provenance='illustrative'."""
    reg, hist = generate_fl_lines(n, seed)
    voters = load_extract(reg, hist)
    return [Voter(**{**v.__dict__, "provenance": "illustrative"}) for v in voters]
