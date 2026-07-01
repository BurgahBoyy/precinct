"""
Precinct — canonical, multi-state voter schema.

This is the S1.5 "map to instance" output expressed as code: a canonical model
that any state's voter file maps INTO, so the engine binds to canonical handles
(not one state's quirks). The Florida field layout (the first real source) is
mapped in fl_adapter.py.

Pure data + enums only. No I/O, no network, no globals. Import-safe.

Provenance rule (build-kit non-negotiable #2): every Voter carries a
`provenance` tag so nothing shown to a human is an unlabelled guess.
  - "real"         -> parsed from an official state extract
  - "illustrative" -> synthetic sample data (NOT a real person)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from typing import Optional


class Party(str, Enum):
    """Canonical party, normalized across states. `party_raw` keeps the original."""
    DEM = "DEM"
    REP = "REP"
    NPA = "NPA"          # No Party Affiliation / unaffiliated / independent-of-party
    LIB = "LIB"
    GRN = "GRN"
    IND = "IND"          # a registered "Independent" party (distinct from NPA)
    OTHER = "OTHER"
    UNKNOWN = "UNKNOWN"


class Gender(str, Enum):
    F = "F"
    M = "M"
    U = "U"


class Race(str, Enum):
    AMERICAN_INDIAN = "american_indian_or_alaskan_native"
    ASIAN_PI = "asian_or_pacific_islander"
    BLACK = "black_not_hispanic"
    HISPANIC = "hispanic"
    WHITE = "white_not_hispanic"
    OTHER = "other"
    MULTI = "multi_racial"
    UNKNOWN = "unknown"


class VoterStatus(str, Enum):
    ACTIVE = "ACT"
    INACTIVE = "INA"
    UNKNOWN = "UNK"


class ElectionType(str, Enum):
    PRESIDENTIAL_PRIMARY = "PPP"
    PRIMARY = "PRI"
    RUNOFF = "RUN"
    GENERAL = "GEN"
    OTHER = "OTH"


class VoteMethod(str, Enum):
    """How a ballot was cast, canonicalized from state history codes."""
    BY_MAIL = "by_mail"
    EARLY = "early"
    AT_POLLS = "at_polls"
    PROVISIONAL_NOT_COUNTED = "provisional_not_counted"
    MAIL_NOT_COUNTED = "mail_not_counted"
    DID_NOT_VOTE = "did_not_vote"
    UNKNOWN = "unknown"

    @property
    def counted(self) -> bool:
        """True if this record represents a ballot that actually counted."""
        return self in (VoteMethod.BY_MAIL, VoteMethod.EARLY, VoteMethod.AT_POLLS)


@dataclass(frozen=True)
class VoteRecord:
    """One row of a voter's participation history."""
    election_date: date
    election_type: ElectionType
    method: VoteMethod


@dataclass(frozen=True)
class Address:
    line1: str = ""
    line2: str = ""
    city: str = ""
    state: str = ""
    zipcode: str = ""

    def one_line(self) -> str:
        parts = [p for p in (self.line1, self.line2, self.city, self.state, self.zipcode) if p]
        return ", ".join(parts)


@dataclass(frozen=True)
class Voter:
    """
    A canonical voter record. One state's extract maps into this shape.
    All fields optional-friendly so partial/protected records don't crash the engine.
    """
    voter_id: str
    source_state: str                       # e.g. "FL"
    provenance: str = "illustrative"        # "real" | "illustrative"

    # identity
    name_first: str = ""
    name_middle: str = ""
    name_last: str = ""
    name_suffix: str = ""
    protected: bool = False                 # requested public-records exemption

    # geography
    county: str = ""                        # raw county code/name from source
    residence: Address = field(default_factory=Address)
    mailing: Optional[Address] = None
    precinct: str = ""
    precinct_group: str = ""
    precinct_split: str = ""
    precinct_suffix: str = ""

    # districts
    congressional_district: str = ""
    house_district: str = ""
    senate_district: str = ""
    county_commission_district: str = ""
    school_board_district: str = ""

    # demographics
    gender: Gender = Gender.U
    race: Race = Race.UNKNOWN
    race_raw: str = ""
    birth_date: Optional[date] = None

    # registration
    registration_date: Optional[date] = None
    party: Party = Party.UNKNOWN
    party_raw: str = ""
    status: VoterStatus = VoterStatus.UNKNOWN

    # contact
    phone: str = ""
    email: str = ""

    # participation
    voting_history: tuple[VoteRecord, ...] = ()

    @property
    def full_name(self) -> str:
        parts = [self.name_first, self.name_middle, self.name_last, self.name_suffix]
        return " ".join(p for p in parts if p).strip()
