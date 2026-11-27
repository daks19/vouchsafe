"""Turn reconciliation results and portal events into agent cases: one case per mismatch."""

from __future__ import annotations

from datetime import date

from gstagent import data, gstin
from gstagent.language import STATE_LANGUAGE
from gstagent.matcher import key
from gstagent.models import BookEntry, Match, MatchStatus, PortalRecord

RECEIVER = "Manju (receives goods at the shop)"  # fictional demo persona (spec §2)


def from_matches(matches: list[Match], books: list[BookEntry], portal: list[PortalRecord], period: str,
                 shop_lang: str | None = None) -> list[dict]:
    """W1 for a portal line with no bill; W2 for a bill the supplier has not reported or reported wrongly.

    Each case carries the recipient's language: the shop's for W1, the supplier's own for W2.
    """
    shop_lang = shop_lang or data.load_profile().preferred_language
    by_id = {b.id: b for b in books}
    by_key = {key(p): p for p in portal}
    suppliers = {s["gstin"]: s for s in data.load_json("suppliers.json")}
    cases = []
    for m in matches:
        if m.status == MatchStatus.MISSING_IN_BOOKS:
            p = by_key[m.portal_key]
            cases.append({"case_id": f"W1:{m.portal_key}", "workflow": "W1", "facts": {
                "period": period, "ctin": p.ctin, "supplier": p.trdnm, "invoice_no": p.inum,
                "invoice_date": p.dt.isoformat(), "value": str(p.val), "to": RECEIVER, "lang": shop_lang}})
        elif m.status in (MatchStatus.MISSING_IN_2B, MatchStatus.AMOUNT_MISMATCH):
            b = by_id[m.book_id]
            g = gstin.check(b.supplier_gstin_raw)
            if not g.valid:
                continue  # can't message a supplier we can't identify; the CA queue already shows it
            sup = suppliers.get(g.gstin, {})
            facts = {"period": period, "ctin": g.gstin, "supplier": b.supplier_name, "invoice_no": b.invoice_no,
                     "invoice_date": b.invoice_date.isoformat(), "taxable": str(b.taxable_value), "tax": str(b.tax),
                     "at_risk": str(m.itc_at_risk),
                     "problem": m.status.value, "to": f"{b.supplier_name} ({sup.get('phone', 'no phone on file')})",
                     "lang": sup.get("language") or STATE_LANGUAGE.get(g.gstin[:2], "en-IN")}
            if m.status == MatchStatus.AMOUNT_MISMATCH:
                facts["filed_taxable"] = str(by_key[m.portal_key].txval)
                facts["filed_date"] = by_key[m.portal_key].dt.isoformat()
            cases.append({"case_id": f"W2:{b.id}", "workflow": "W2", "facts": facts,
                          "bill": b.model_dump(mode="json")})
    return cases


def cancellation(ctin: str, period: str) -> dict:
    """W3: a supplier's registration may have been cancelled from a past date. The agent checks the portal itself."""
    return {"case_id": f"W3:{ctin}", "workflow": "W3", "facts": {"period": period, "ctin": ctin}}


def period_start(period: str) -> date:
    return date(int(period[2:]), int(period[:2]), 1)
