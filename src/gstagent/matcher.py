"""Match the owner's purchase bills against GSTR-2B, with a plain reason for every row.

Tiers, tried in order on still-unmatched rows:
    exact       same GSTIN, same invoice number, same date, same taxable value
    normalised  same GSTIN, invoice number equal after removing punctuation, date within N days
    fuzzy       same GSTIN, invoice numbers nearly equal (OCR slips), date within N days
    anchored    bill GSTIN unreadable: unique invoice number + date + amount match
Then: same supplier and invoice but different value -> amount mismatch; leftovers are
missing on one side. Arithmetic is Decimal; ITC at risk comes from a rule card.
"""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal
from difflib import SequenceMatcher

from gstagent import gstin
from gstagent.models import BookEntry, DocType, Match, MatchStatus, PortalRecord
from gstagent.rules import RuleBook
from gstagent.rules.logic import rupees

AMOUNT_TOLERANCE = Decimal("1.00")
DATE_WINDOW_DAYS = 10
FUZZY_MIN_RATIO = 0.8


def norm_inv(x: str) -> str:
    return re.sub(r"[^0-9A-Z]", "", x.upper())


def key(p: PortalRecord) -> str:
    return f"{p.ctin}|{p.inum}"


def _close(a: Decimal, b: Decimal) -> bool:
    return abs(a - b) <= AMOUNT_TOLERANCE


def _days(a: date, b: date) -> int:
    return abs((a - b).days)


def _differences(b: BookEntry, p: PortalRecord) -> str:
    diffs = []
    if b.invoice_no.strip().upper() != p.inum.strip().upper():
        diffs.append(f"number written '{b.invoice_no}' on the bill vs '{p.inum}' filed")
    if b.invoice_date != p.dt:
        diffs.append(f"bill dated {b.invoice_date} vs {p.dt} filed ({_days(b.invoice_date, p.dt)} days apart)")
    return "; ".join(diffs) or "no differences"


def _mismatch(b: BookEntry, p: PortalRecord) -> str:
    """Only the fields that actually differ, so the reason never reads '₹62,000 vs ₹62,000'."""
    filed, bill = [], []
    if not _close(b.taxable_value, p.txval):
        filed.append(f"taxable value {rupees(p.txval)}")
        bill.append(rupees(b.taxable_value))
    if b.invoice_date != p.dt:
        filed.append(f"date {p.dt}")
        bill.append(str(b.invoice_date))
    return f"Supplier filed {' and '.join(filed)} but the bill says {' and '.join(bill)}"


def reconcile(books: list[BookEntry], portal: list[PortalRecord], rules: RuleBook,
              period_start: date) -> list[Match]:
    results: list[Match] = []
    canon: dict[str, str | None] = {}
    notes: dict[str, str] = {}
    for b in books:
        c = gstin.check(b.supplier_gstin_raw)
        canon[b.id] = c.gstin if c.valid else None
        if c.repaired:
            notes[b.id] = f" (GSTIN on the photo was repaired: {c.reason})"
        elif not c.valid:
            notes[b.id] = f" (GSTIN on the photo could not be read: {c.reason})"

    # Duplicates in books: same photo, or same supplier + invoice number.
    seen: dict[tuple, str] = {}
    live: list[BookEntry] = []
    for b in books:
        sig_img = ("img", b.image_hash) if b.image_hash else None
        sig_inv = ("inv", canon[b.id], norm_inv(b.invoice_no), b.doc_type)
        dup_of = (seen.get(sig_img) if sig_img else None) or (seen.get(sig_inv) if canon[b.id] else None)
        if dup_of:
            results.append(Match(book_id=b.id, portal_key=None, status=MatchStatus.DUPLICATE_IN_BOOKS,
                                 reason=f"Same bill as {dup_of}; counted once."))
            continue
        if sig_img:
            seen[sig_img] = b.id
        if canon[b.id]:
            seen[sig_inv] = b.id
        live.append(b)

    unmatched_portal = list(portal)

    def take(b: BookEntry, p: PortalRecord, tier: str, reason: str) -> None:
        unmatched_portal.remove(p)
        results.append(Match(book_id=b.id, portal_key=key(p), status=MatchStatus.MATCHED,
                             tier=tier, reason=reason + notes.get(b.id, "")))

    tiers = [
        ("exact", lambda b, p: canon[b.id] == p.ctin and b.invoice_no.strip().upper() == p.inum.strip().upper()
         and b.invoice_date == p.dt and _close(b.taxable_value, p.txval),
         lambda b, p: "Matches the supplier's filing exactly."),
        ("normalised", lambda b, p: canon[b.id] == p.ctin and norm_inv(b.invoice_no) == norm_inv(p.inum)
         and _days(b.invoice_date, p.dt) <= DATE_WINDOW_DAYS and _close(b.taxable_value, p.txval),
         lambda b, p: "Same invoice; " + _differences(b, p) + "."),
        ("fuzzy", lambda b, p: canon[b.id] == p.ctin
         and SequenceMatcher(None, norm_inv(b.invoice_no), norm_inv(p.inum)).ratio() >= FUZZY_MIN_RATIO
         and _days(b.invoice_date, p.dt) <= DATE_WINDOW_DAYS and _close(b.taxable_value, p.txval),
         lambda b, p: f"Likely the same invoice: '{b.invoice_no}' on the photo vs '{p.inum}' filed "
                      f"(same supplier and amount). Confirm the number."),
    ]
    for tier, test, why in tiers:
        for b in list(live):
            cands = [p for p in unmatched_portal if p.doc_type == b.doc_type and test(b, p)]
            if len(cands) == 1:
                take(b, cands[0], tier, why(b, cands[0]))
                live.remove(b)

    # Anchored: bill GSTIN unreadable, so rely on a unique invoice + date + amount match.
    for b in list(live):
        if canon[b.id] is not None:
            continue
        cands = [p for p in unmatched_portal if p.doc_type == b.doc_type
                 and norm_inv(p.inum) == norm_inv(b.invoice_no)
                 and _days(b.invoice_date, p.dt) <= DATE_WINDOW_DAYS and _close(b.taxable_value, p.txval)]
        if len(cands) == 1:
            p = cands[0]
            take(b, p, "anchored", f"Matched on invoice number, date and amount to {p.trdnm} ({p.ctin}). "
                                   f"Confirm the supplier GSTIN from the bill.")
            live.remove(b)

    # Same supplier + invoice, different value.
    for b in list(live):
        cands = [p for p in unmatched_portal if p.doc_type == b.doc_type and p.ctin == canon[b.id]
                 and norm_inv(p.inum) == norm_inv(b.invoice_no)]
        if len(cands) == 1:
            p = cands[0]
            unmatched_portal.remove(p)
            live.remove(b)
            risk = max(b.tax - p.tax, Decimal("0")) if b.doc_type == DocType.INVOICE else Decimal("0")
            results.append(Match(
                book_id=b.id, portal_key=key(p), status=MatchStatus.AMOUNT_MISMATCH, itc_at_risk=risk,
                reason=(f"{_mismatch(b, p)}; "
                        f"{rupees(risk)} of ITC at risk until the supplier amends via GSTR-1A."),
                citations=rules.get("itc.supplier_reported", period_start).citations))

    for b in live:
        r = rules.evaluate("itc.supplier_reported", period_start, in_2b=False,
                           tax=b.tax if b.doc_type == DocType.INVOICE else 0)
        results.append(Match(book_id=b.id, portal_key=None, status=MatchStatus.MISSING_IN_2B,
                             itc_at_risk=r.value["itc_at_risk"], reason=r.explanation + notes.get(b.id, ""),
                             citations=r.citations))

    for p in unmatched_portal:
        seen_as = (f"Unrecognised purchase: {p.trdnm} reported invoice {p.inum} ({rupees(p.val)}) against this "
                   f"GSTIN, but there is no bill for it. Ask whoever receives goods whether it arrived. ")
        if p.rev == "Y":
            r = rules.evaluate("ims.treatment", period_start, doc_type=p.doc_type.value, action="PENDING",
                               reverse_charge=True)
            reason = seen_as + r.explanation
            cites = r.citations
        else:
            reason = seen_as + ("If it did not, recommend IMS Pending before GSTR-2B is generated. This alone is not "
                                "a sign that anyone used the GST login. Reject only after the CA reviews.")
            cites = []
        results.append(Match(book_id=None, portal_key=key(p), status=MatchStatus.MISSING_IN_BOOKS,
                             reason=reason, citations=cites))
    return results
