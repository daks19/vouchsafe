"""Every rule card's own examples must pass. Adding a card version adds its tests."""

from datetime import date, datetime
from decimal import Decimal

import pytest

from gstagent.rules import RuleBook, RuleError

BOOK = RuleBook.load()
CASES = [
    pytest.param(card, ex, id=f"{card.id}@{card.version}:{ex.name}")
    for versions in BOOK.cards.values()
    for card in versions
    for ex in card.examples
]


def same(actual, expected) -> bool:
    if expected is None or actual is None:
        return actual is expected
    if isinstance(actual, Decimal):
        return actual == Decimal(str(expected))
    if isinstance(actual, datetime):
        return actual.isoformat() == (expected.isoformat() if isinstance(expected, datetime) else str(expected))
    if isinstance(actual, date):
        return actual.isoformat() == (expected.isoformat() if isinstance(expected, date) else str(expected))
    if isinstance(actual, list):
        return len(actual) == len(expected) and all(same(a, e) for a, e in zip(actual, expected))
    return actual == expected


@pytest.mark.parametrize("card,example", CASES)
def test_card_examples(card, example):
    # The example's date must select this exact card version.
    assert BOOK.get(card.id, example.as_of).version == card.version, "example date outside card window"
    result = BOOK.evaluate(card.id, example.as_of, **example.inputs)
    for key, want in example.expect.items():
        assert key in result.value, f"missing output {key}"
        assert same(result.value[key], want), f"{key}: got {result.value[key]!r}, want {want!r}"
    assert result.explanation
    assert result.citations


def test_every_card_has_examples():
    missing = [f"{c.id}@{c.version}" for v in BOOK.cards.values() for c in v if not c.examples]
    assert not missing, f"cards without examples: {missing}"


def test_effective_dating_picks_version_by_date():
    assert BOOK.get("ewb.number_format", date(2026, 12, 31)).params["digits"] == 12
    assert BOOK.get("ewb.number_format", date(2027, 1, 1)).params["digits"] == 14


def test_old_rate_invoice_is_judged_by_its_own_date():
    # A 12% invoice dated Aug 2025 that shows up in the Oct 2026 period is still valid.
    assert BOOK.evaluate("gst.rate_check", date(2025, 8, 10), rate="12").value["category"] == "standard"


def test_no_rule_before_its_start():
    with pytest.raises(RuleError):
        BOOK.get("tds.contractor", date(2026, 3, 31))


def test_74a_only_for_fy_2024_25_onwards():
    on = date(2026, 11, 18)
    assert BOOK.evaluate("demand.section", on, fy_start_year=2023).value["section"] == "73/74"
    assert BOOK.evaluate("demand.section", on, fy_start_year=2024).value["section"] == "74A"


def test_filed_3b_is_never_called_proof_of_payment():
    r = BOOK.evaluate("itc.rule_37a", date(2026, 11, 18), invoice_date="2025-08-12",
                      supplier_3b_filed_by_cutoff=True, check_date="2026-11-18")
    assert "not proof that the tax on this invoice was paid" in r.explanation
    ok = BOOK.evaluate("itc.supplier_reported", date(2026, 10, 1), in_2b=True, tax="100")
    assert "not that he paid the tax" in ok.explanation
