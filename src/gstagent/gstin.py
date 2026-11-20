"""GSTIN structure and checksum validation.

GSTIN layout (15 chars):
    [0:2]   state code (01-38, 97 other territory, 99 centre jurisdiction)
    [2:12]  PAN of the holder (5 letters, 4 digits, 1 letter); PAN[3] is the
            holder type (P individual, C company, H HUF, F firm, E LLP, ...).
            TDS-deductor registrations use a TAN here (4 letters, 5 digits, 1 letter).
    [12]    entity number for the same PAN in the state (1-9, then A-Z)
    [13]    'Z' for normal taxpayers; 'D' for TDS deductors and 'C' for TCS
            collectors in that position, so a validator must NOT force 'Z'
    [14]    checksum: Luhn mod-36 over the first 14 characters

The OCR "Z-fix" below only proposes a repair. It accepts the repair when the
checksum then passes, and never silently rewrites a valid GSTIN.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
_VALUE = {c: i for i, c in enumerate(ALPHABET)}

_ID = r"(?:[A-Z]{5}\d{4}[A-Z]|[A-Z]{4}\d{5}[A-Z])"  # PAN or TAN
_SHAPE = re.compile(rf"^\d{{2}}{_ID}[1-9A-Z][A-Z0-9][0-9A-Z]$")
_FIRST14 = re.compile(rf"^\d{{2}}{_ID}[1-9A-Z][A-Z0-9]$")

PAN_HOLDER_TYPES = {
    "P": "individual",
    "C": "company",
    "H": "huf",
    "F": "firm",
    "E": "llp",
    "A": "aop",
    "B": "boi",
    "T": "trust",
    "G": "government",
    "L": "local_authority",
    "J": "artificial_juridical_person",
}

# Characters OCR commonly produces where a 'Z' was printed.
_Z_CONFUSIONS = set("2I17S")


def checksum_char(first14: str) -> str:
    """Return the checksum character for the first 14 characters of a GSTIN."""
    if len(first14) != 14:
        raise ValueError("need exactly 14 characters")
    total = 0
    for i, ch in enumerate(first14.upper()):
        product = _VALUE[ch] * (1 if i % 2 == 0 else 2)
        total += product // 36 + product % 36
    return ALPHABET[(36 - total % 36) % 36]


def normalise(raw: str) -> str:
    return re.sub(r"[^0-9A-Za-z]", "", raw or "").upper()


@dataclass(frozen=True)
class GstinCheck:
    raw: str
    gstin: str          # normalised (and repaired, if a repair was accepted)
    valid: bool
    repaired: bool
    reason: str
    state_code: str | None = None
    pan: str | None = None
    holder_type: str | None = None
    registration_kind: str | None = None  # normal | tds_deductor | tcs_collector


def _describe(g: str) -> dict:
    kind = {"Z": "normal", "D": "tds_deductor", "C": "tcs_collector"}.get(g[13], "other")
    is_pan = bool(re.match(r"^[A-Z]{5}\d{4}[A-Z]$", g[2:12]))
    return {
        "state_code": g[:2],
        "pan": g[2:12] if is_pan else None,
        "holder_type": PAN_HOLDER_TYPES.get(g[5], "unknown") if is_pan else "tan_based",
        "registration_kind": kind,
    }


def is_valid(raw: str) -> bool:
    g = normalise(raw)
    return bool(_SHAPE.match(g)) and checksum_char(g[:14]) == g[14]


def check(raw: str) -> GstinCheck:
    """Validate a GSTIN, proposing a position-13 'Z' repair for OCR errors."""
    g = normalise(raw)
    if len(g) != 15:
        return GstinCheck(raw, g, False, False, f"expected 15 characters, got {len(g)}")

    if _SHAPE.match(g) and checksum_char(g[:14]) == g[14]:
        return GstinCheck(raw, g, True, False, "checksum ok", **_describe(g))

    if g[13] in _Z_CONFUSIONS:
        candidate = g[:13] + "Z" + g[14]
        if _SHAPE.match(candidate) and checksum_char(candidate[:14]) == candidate[14]:
            return GstinCheck(
                raw, candidate, True, True,
                f"OCR repair: position 14 read as '{g[13]}', checksum passes with 'Z'",
                **_describe(candidate),
            )

    if not _SHAPE.match(g):
        return GstinCheck(raw, g, False, False, "does not match GSTIN structure")
    return GstinCheck(raw, g, False, False, "checksum failed; ask for a clearer photo")


def build(state_code: str, pan: str, entity: str = "1", position13: str = "Z") -> str:
    """Build a checksum-valid GSTIN (used by the synthetic data generator)."""
    first14 = f"{state_code}{pan}{entity}{position13}".upper()
    if not _FIRST14.match(first14):
        raise ValueError(f"bad GSTIN parts: {first14}")
    return first14 + checksum_char(first14)
