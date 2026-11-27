"""The matcher must find every scenario the synthetic generator seeded."""

from datetime import date
from decimal import Decimal

import pytest

from gstagent import data
from gstagent.matcher import reconcile
from gstagent.models import MatchStatus
from gstagent.rules import RuleBook

RULES = RuleBook.load()
EXPECTED = data.load_json("expected_matches.json")


@pytest.fixture(scope="module")
def results():
    books = data.load_books()
    portal = data.portal_records_from_2b(data.load_json("gstr2b_102026.json"))
    return reconcile(books, portal, RULES, date(2026, 10, 1))


def test_every_book_entry_gets_exactly_one_result(results):
    ids = [m.book_id for m in results if m.book_id]
    assert sorted(ids) == sorted(EXPECTED["books"])


@pytest.mark.parametrize("book_id,want", sorted(EXPECTED["books"].items()))
def test_seeded_scenario(results, book_id, want):
    m = next(m for m in results if m.book_id == book_id)
    assert m.status.value == want["status"], f"{want['scenario']}: {m.reason}"
    if want["tier"]:
        assert m.tier == want["tier"], f"{want['scenario']}: matched via {m.tier}"
    assert m.reason


def test_portal_only_record_is_flagged(results):
    flagged = {m.portal_key for m in results if m.status == MatchStatus.MISSING_IN_BOOKS}
    assert flagged == set(EXPECTED["portal_only"])


def test_itc_at_risk_is_tax_of_missing_bills(results):
    books = {b.id: b for b in data.load_books()}
    for m in results:
        if m.status == MatchStatus.MISSING_IN_2B:
            assert m.itc_at_risk == books[m.book_id].tax > Decimal("0")
            assert m.citations


def test_supplier_filing_gstr1a_resolves_missing_invoices():
    books = data.load_books()
    twob = data.load_json("gstr2b_102026.json")
    event = data.load_json("gstr1a_event.json")
    portal = data.portal_records_from_2b(twob)
    before = reconcile(books, portal, RULES, date(2026, 10, 1))
    from gstagent.models import PortalRecord
    portal += [PortalRecord.model_validate({**r, "trdnm": event["trdnm"]}) for r in event["records"]]
    after = reconcile(books, portal, RULES, date(2026, 10, 1))
    count = lambda rs: sum(m.status == MatchStatus.MISSING_IN_2B for m in rs)  # noqa: E731
    assert count(before) - count(after) == len(event["records"])


def _portal(rev: str):
    from gstagent.models import PortalRecord
    return PortalRecord(ctin="29AABCL1234M1Z5", trdnm="Laxmi Steels", inum="LS/2026/118", dt=date(2026, 10, 3),
                        val=Decimal("18400"), txval=Decimal("15593.22"), igst=Decimal("2806.78"), pos="29", rev=rev)


def test_unrecognised_purchase_is_not_called_misuse():
    [m] = reconcile([], [_portal("N")], RULES, date(2026, 10, 1))
    assert m.status == MatchStatus.MISSING_IN_BOOKS
    assert "Unrecognised purchase" in m.reason and "Pending" in m.reason
    assert "not a sign that anyone used the GST login" in m.reason


def test_reverse_charge_line_never_suggests_ims_pending():
    [m] = reconcile([], [_portal("Y")], RULES, date(2026, 10, 1))
    assert m.status == MatchStatus.MISSING_IN_BOOKS
    assert "not in IMS" in m.reason and "recommend IMS Pending" not in m.reason
    assert m.citations


def test_mismatch_reason_names_only_the_field_that_differs(results):
    """Live Groq read 1 Oct as 10 Jan; the reason must say 'date', not '₹62,000 vs ₹62,000'."""
    m = next(m for m in results if m.tier == "exact")
    b = next(b for b in data.load_books() if b.id == m.book_id)
    p = next(p for p in data.portal_records_from_2b(data.load_json("gstr2b_102026.json"))
             if p.inum == b.invoice_no)
    late = b.model_copy(update={"invoice_date": date(2026, 1, 10)})
    [r] = [r for r in reconcile([late], [p], RULES, date(2026, 10, 1)) if r.book_id]
    assert r.status == MatchStatus.AMOUNT_MISMATCH
    assert "date" in r.reason and "taxable value" not in r.reason
