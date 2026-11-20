"""Number guard: no figure reaches the owner, supplier or CA unless the case computed it.

Every LLM-drafted message passes through `check()` with the facts the rule engine
produced (amounts, dates, invoice numbers, citations). Any number in the text that
is not among those facts blocks the message.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Iterable

_NUM = re.compile(r"(?<![\w.])\d[\d,]*(?:\.\d+)?")


def _numbers(text: str) -> set[Decimal]:
    out = set()
    for tok in _NUM.findall(text):
        try:
            out.add(Decimal(tok.replace(",", "")).normalize())
        except InvalidOperation:
            continue
    return out


@dataclass(frozen=True)
class GuardResult:
    ok: bool
    unknown: tuple[str, ...]


def check(text: str, facts: Iterable[object]) -> GuardResult:
    allowed: set[Decimal] = set()
    for f in facts:
        allowed |= _numbers(str(f))
        if isinstance(f, Decimal):
            allowed.add(f.normalize())
    unknown = sorted(f"{n:f}" for n in _numbers(text) - allowed)
    return GuardResult(ok=not unknown, unknown=tuple(unknown))
