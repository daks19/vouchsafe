from decimal import Decimal

from gstagent.guard import check


def test_allows_only_computed_numbers():
    facts = [Decimal("4320.00"), "2026-11-30", "SGT/1023"]
    assert check("₹4,320 of ITC is at risk on SGT/1023; claim by 2026-11-30.", facts).ok


def test_blocks_invented_number():
    r = check("You will save ₹18,000 this month.", [Decimal("4320")])
    assert not r.ok and r.unknown == ("18000",)


def test_indian_grouping_is_understood():
    assert check("Penalty ₹1,00,000", [Decimal("100000")]).ok
