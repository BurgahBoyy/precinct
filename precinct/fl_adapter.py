"""
Precinct — Florida adapter.

Maps the official Florida "Voter Extract" tab-delimited files INTO the canonical
schema (schema.py). Field order and codes are pinned to the official
"Voter Extract File Layout (Updated May 2026)" published by the FL Division of
Elections. See Florida_Voter_Data_Access.md for the source link.

Two files per county:
  - Registration:  CountyCode_YYYYMMDD.txt        (38 tab-delimited fields)
  - Voting history: CountyCode_H_YYYYMMDD.txt      (5 tab-delimited fields)

Pure parsing. No I/O beyond being handed lines. Records parsed here are tagged
provenance="real".
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Iterable, Optional

from .schema import (
    Address, ElectionType, Gender, Party, Race, VoteMethod, VoteRecord,
    Voter, VoterStatus,
)

# --- Code tables (pinned to the official layout) ---------------------------

RACE_CODES = {
    "1": Race.AMERICAN_INDIAN, "2": Race.ASIAN_PI, "3": Race.BLACK,
    "4": Race.HISPANIC, "5": Race.WHITE, "6": Race.OTHER,
    "7": Race.MULTI, "9": Race.UNKNOWN,
}

# FL party code -> canonical Party. Raw code is always preserved on the Voter.
PARTY_CODES = {
    "DEM": Party.DEM, "REP": Party.REP, "NPA": Party.NPA,
    "LPF": Party.LIB, "GRE": Party.GRN, "IND": Party.IND,
}

HISTORY_CODES = {
    "A": VoteMethod.BY_MAIL,
    "B": VoteMethod.MAIL_NOT_COUNTED,
    "E": VoteMethod.EARLY,
    "L": VoteMethod.MAIL_NOT_COUNTED,
    "N": VoteMethod.DID_NOT_VOTE,
    "P": VoteMethod.PROVISIONAL_NOT_COUNTED,
    "Y": VoteMethod.AT_POLLS,
}

GENDER_CODES = {"F": Gender.F, "M": Gender.M, "U": Gender.U}
STATUS_CODES = {"ACT": VoterStatus.ACTIVE, "INA": VoterStatus.INACTIVE}

FL_COUNTY_NAMES = {
    "ALA": "Alachua", "BAK": "Baker", "BAY": "Bay", "BRA": "Bradford",
    "BRE": "Brevard", "BRO": "Broward", "CAL": "Calhoun", "CHA": "Charlotte",
    "CIT": "Citrus", "CLA": "Clay", "CLL": "Collier", "CLM": "Columbia",
    "DAD": "Miami-Dade", "DES": "Desoto", "DIX": "Dixie", "DUV": "Duval",
    "ESC": "Escambia", "FLA": "Flagler", "FRA": "Franklin", "GAD": "Gadsden",
    "GIL": "Gilchrist", "GLA": "Glades", "GUL": "Gulf", "HAM": "Hamilton",
    "HAR": "Hardee", "HEN": "Hendry", "HER": "Hernando", "HIG": "Highlands",
    "HIL": "Hillsborough", "HOL": "Holmes", "IND": "Indian River", "JAC": "Jackson",
    "JEF": "Jefferson", "LAF": "Lafayette", "LAK": "Lake", "LEE": "Lee",
    "LEO": "Leon", "LEV": "Levy", "LIB": "Liberty", "MAD": "Madison",
    "MAN": "Manatee", "MRN": "Marion", "MRT": "Martin", "MON": "Monroe",
    "NAS": "Nassau", "OKA": "Okaloosa", "OKE": "Okeechobee", "ORA": "Orange",
    "OSC": "Osceola", "PAL": "Palm Beach", "PAS": "Pasco", "PIN": "Pinellas",
    "POL": "Polk", "PUT": "Putnam", "SAN": "Santa Rosa", "SAR": "Sarasota",
    "SEM": "Seminole", "STJ": "St. Johns", "STL": "St. Lucie", "SUM": "Sumter",
    "SUW": "Suwannee", "TAY": "Taylor", "UNI": "Union", "VOL": "Volusia",
    "WAK": "Wakulla", "WAL": "Walton", "WAS": "Washington",
}

# Registration field indices (0-based) per the official 38-field layout.
R_COUNTY, R_VOTER_ID, R_LAST, R_SUFFIX, R_FIRST, R_MIDDLE, R_EXEMPT = 0, 1, 2, 3, 4, 5, 6
R_RES_L1, R_RES_L2, R_RES_CITY, R_RES_STATE, R_RES_ZIP = 7, 8, 9, 10, 11
R_MAIL_L1, R_MAIL_L2, R_MAIL_L3, R_MAIL_CITY, R_MAIL_STATE, R_MAIL_ZIP, R_MAIL_COUNTRY = 12, 13, 14, 15, 16, 17, 18
R_GENDER, R_RACE, R_BIRTH, R_REGDATE, R_PARTY = 19, 20, 21, 22, 23
R_PRECINCT, R_PREC_GROUP, R_PREC_SPLIT, R_PREC_SUFFIX, R_STATUS = 24, 25, 26, 27, 28
R_CONG, R_HOUSE, R_SENATE, R_COMMISH, R_SCHOOL = 29, 30, 31, 32, 33
R_AREACODE, R_PHONE, R_PHONE_EXT, R_EMAIL = 34, 35, 36, 37
R_FIELD_COUNT = 38


def _parse_date(s: str) -> Optional[date]:
    s = (s or "").strip()
    if not s:
        return None
    try:
        return datetime.strptime(s, "%m/%d/%Y").date()
    except ValueError:
        return None


def _g(fields: list[str], idx: int) -> str:
    return fields[idx].strip() if idx < len(fields) else ""


def parse_registration_line(line: str) -> Optional[Voter]:
    """Parse one tab-delimited FL registration row into a canonical Voter."""
    if not line.strip():
        return None
    f = line.rstrip("\n").split("\t")
    if len(f) < R_FIELD_COUNT:
        f = f + [""] * (R_FIELD_COUNT - len(f))  # tolerate short/protected rows

    area, num = _g(f, R_AREACODE), _g(f, R_PHONE)
    ext = _g(f, R_PHONE_EXT)
    phone = ""
    if num:
        phone = f"({area}) {num}" if area else num
        if ext:
            phone += f" x{ext}"

    county_code = _g(f, R_COUNTY)
    _mail = Address(line1=_g(f, R_MAIL_L1), line2=_g(f, R_MAIL_L2), city=_g(f, R_MAIL_CITY),
                    state=_g(f, R_MAIL_STATE), zipcode=_g(f, R_MAIL_ZIP))
    if not any((_mail.line1, _mail.line2, _mail.city, _mail.state, _mail.zipcode)):
        _mail = None
    return Voter(
        voter_id=_g(f, R_VOTER_ID),
        source_state="FL",
        provenance="real",
        name_first=_g(f, R_FIRST),
        name_middle=_g(f, R_MIDDLE),
        name_last=_g(f, R_LAST),
        name_suffix=_g(f, R_SUFFIX),
        protected=_g(f, R_EXEMPT).upper() == "Y",
        county=FL_COUNTY_NAMES.get(county_code, county_code),
        residence=Address(
            line1=_g(f, R_RES_L1), line2=_g(f, R_RES_L2),
            city=_g(f, R_RES_CITY), state=_g(f, R_RES_STATE), zipcode=_g(f, R_RES_ZIP),
        ),
        mailing=_mail,
        precinct=_g(f, R_PRECINCT),
        precinct_group=_g(f, R_PREC_GROUP),
        precinct_split=_g(f, R_PREC_SPLIT),
        precinct_suffix=_g(f, R_PREC_SUFFIX),
        congressional_district=_g(f, R_CONG),
        house_district=_g(f, R_HOUSE),
        senate_district=_g(f, R_SENATE),
        county_commission_district=_g(f, R_COMMISH),
        school_board_district=_g(f, R_SCHOOL),
        gender=GENDER_CODES.get(_g(f, R_GENDER).upper(), Gender.U),
        race=RACE_CODES.get(_g(f, R_RACE), Race.UNKNOWN),
        race_raw=_g(f, R_RACE),
        birth_date=_parse_date(_g(f, R_BIRTH)),
        registration_date=_parse_date(_g(f, R_REGDATE)),
        party=PARTY_CODES.get(_g(f, R_PARTY).upper(), Party.OTHER if _g(f, R_PARTY) else Party.UNKNOWN),
        party_raw=_g(f, R_PARTY),
        status=STATUS_CODES.get(_g(f, R_STATUS).upper(), VoterStatus.UNKNOWN),
        phone=phone,
        email=_g(f, R_EMAIL),
    )


def parse_history_line(line: str) -> Optional[tuple[str, VoteRecord]]:
    """Parse one tab-delimited FL voting-history row -> (voter_id, VoteRecord)."""
    if not line.strip():
        return None
    f = line.rstrip("\n").split("\t")
    if len(f) < 5:
        return None
    voter_id = f[1].strip()
    edate = _parse_date(f[2])
    if not voter_id or edate is None:
        return None
    etype = ElectionType(f[3].strip()) if f[3].strip() in ElectionType._value2member_map_ else ElectionType.OTHER
    method = HISTORY_CODES.get(f[4].strip().upper(), VoteMethod.UNKNOWN)
    return voter_id, VoteRecord(election_date=edate, election_type=etype, method=method)


def load_extract(registration_lines: Iterable[str],
                 history_lines: Iterable[str] = ()) -> list[Voter]:
    """
    Join registration + history into canonical Voters.
    Registration is authoritative for the voter set; history is attached by voter_id.
    """
    history: dict[str, list[VoteRecord]] = {}
    for line in history_lines:
        parsed = parse_history_line(line)
        if parsed:
            vid, rec = parsed
            history.setdefault(vid, []).append(rec)

    voters: list[Voter] = []
    for line in registration_lines:
        v = parse_registration_line(line)
        if v is None:
            continue
        recs = tuple(sorted(history.get(v.voter_id, ()), key=lambda r: r.election_date))
        if recs:
            v = Voter(**{**v.__dict__, "voting_history": recs})
        voters.append(v)
    return voters
