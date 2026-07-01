"""
Precinct — read-only voter store.

Holds loaded voters in memory and exposes the seam where the REAL Florida disk
plugs in (`from_fl_files`). Until then, `from_sample` loads labelled illustrative
data so the app runs end-to-end. This is the only stateful piece; the engine
stays pure.
"""
from __future__ import annotations

import io
import zipfile
from pathlib import Path

from .fl_adapter import load_extract
from .sample_data import load_sample_voters
from .schema import Voter


class VoterStore:
    def __init__(self, voters: list[Voter], provenance: str = "illustrative"):
        self._voters = voters
        self.provenance = provenance          # "illustrative" until real data is loaded

    @classmethod
    def from_sample(cls, n: int = 200, seed: int = 42) -> "VoterStore":
        return cls(load_sample_voters(n, seed), provenance="illustrative")

    @classmethod
    def from_fl_files(cls, registration_path: str, history_path: str = "") -> "VoterStore":
        """
        REAL-DATA SEAM (S3). Point at an unzipped county registration .txt (and
        optional history .txt) from the official monthly extract. Records come
        back provenance="real".
        """
        reg = Path(registration_path).read_text(encoding="latin-1").splitlines()
        hist = Path(history_path).read_text(encoding="latin-1").splitlines() if history_path else []
        return cls(load_extract(reg, hist), provenance="real")

    @classmethod
    def from_fl_zip(cls, registration_zip: str, history_zip: str = "") -> "VoterStore":
        """Load directly from the official zipped extract folders (all 67 counties)."""
        reg = _read_all_txt_from_zip(registration_zip)
        hist = _read_all_txt_from_zip(history_zip) if history_zip else []
        return cls(load_extract(reg, hist), provenance="real")

    def all(self) -> list[Voter]:
        return self._voters

    def __len__(self) -> int:
        return len(self._voters)


def _read_all_txt_from_zip(zip_path: str) -> list[str]:
    lines: list[str] = []
    with zipfile.ZipFile(zip_path) as z:
        for name in z.namelist():
            if name.lower().endswith(".txt"):
                with z.open(name) as fh:
                    lines.extend(io.TextIOWrapper(fh, encoding="latin-1").read().splitlines())
    return lines
