"""Effective-dated rule cards.

A rule card is a YAML file (one per version) in rules/cards/, named
`<rule_id>@<version>.yaml`. It holds the law-facing facts: effective window,
parameters, citations, status, and worked examples. The behaviour lives in a
small Python function registered under the same rule id (rules/logic.py).

Changing a rule means adding a new card version with a new effective window
and its own examples. `pytest` then runs every card's examples, so a rule
change is only "live" once its examples pass. The LLM never computes a figure:
every number the agent states comes from `RuleBook.evaluate`.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any, Callable, Literal

import yaml
from pydantic import BaseModel, Field

CARDS_DIR = Path(__file__).parent / "cards"


class Example(BaseModel):
    name: str
    as_of: date
    inputs: dict[str, Any] = Field(default_factory=dict)
    expect: dict[str, Any]


class RuleCard(BaseModel):
    id: str
    version: int
    title: str
    status: Literal["in_force", "announced", "superseded"] = "in_force"
    effective_from: date
    effective_to: date | None = None
    selects_on: str = "the date passed as `on`"
    params: dict[str, Any] = Field(default_factory=dict)
    citations: list[str]
    verify_before_finale: bool = False
    notes: str = ""
    examples: list[Example] = Field(default_factory=list)

    def covers(self, on: date) -> bool:
        return self.effective_from <= on and (self.effective_to is None or on <= self.effective_to)


@dataclass
class RuleResult:
    rule_id: str
    version: int
    value: dict[str, Any]
    explanation: str
    citations: list[str]
    status: str
    verify_before_finale: bool


LogicFn = Callable[[RuleCard, dict[str, Any]], tuple[dict[str, Any], str]]
_LOGIC: dict[str, LogicFn] = {}


def rule(rule_id: str) -> Callable[[LogicFn], LogicFn]:
    def register(fn: LogicFn) -> LogicFn:
        _LOGIC[rule_id] = fn
        return fn
    return register


class RuleError(Exception):
    pass


@dataclass
class RuleBook:
    cards: dict[str, list[RuleCard]] = field(default_factory=dict)

    @classmethod
    def load(cls, directory: Path = CARDS_DIR) -> "RuleBook":
        from gstagent.rules import logic  # noqa: F401  (registers logic functions)

        grouped: dict[str, list[RuleCard]] = defaultdict(list)
        for path in sorted(directory.glob("*.yaml")):
            card = RuleCard.model_validate(yaml.safe_load(path.read_text()))
            expected_name = f"{card.id}@{card.version}.yaml"
            if path.name != expected_name:
                raise RuleError(f"{path.name}: file must be named {expected_name}")
            grouped[card.id].append(card)

        book = cls({k: sorted(v, key=lambda c: c.effective_from) for k, v in grouped.items()})
        book.check_integrity()
        return book

    def check_integrity(self) -> None:
        for rule_id, versions in self.cards.items():
            if rule_id not in _LOGIC:
                raise RuleError(f"no logic registered for rule {rule_id}")
            for a, b in zip(versions, versions[1:]):
                if a.effective_to is None or a.effective_to >= b.effective_from:
                    raise RuleError(
                        f"{rule_id}: v{a.version} and v{b.version} effective windows overlap"
                    )

    def get(self, rule_id: str, on: date) -> RuleCard:
        if isinstance(on, datetime):
            on = on.date()
        for card in self.cards.get(rule_id, []):
            if card.covers(on):
                return card
        raise RuleError(f"no version of {rule_id} in effect on {on.isoformat()}")

    def evaluate(self, rule_id: str, on: date, **inputs: Any) -> RuleResult:
        card = self.get(rule_id, on)
        value, explanation = _LOGIC[rule_id](card, inputs)
        return RuleResult(
            rule_id=card.id,
            version=card.version,
            value=value,
            explanation=explanation,
            citations=card.citations,
            status=card.status,
            verify_before_finale=card.verify_before_finale,
        )
