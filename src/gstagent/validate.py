"""Python checks on what Claude read from a bill. The model reads; these decide.

A failed check becomes a "resnap" Task (ask the shop for a clearer photo). Missing fields, a wrong
CGST/SGST-vs-IGST split or bad arithmetic block matching, since the numbers can't be trusted. An
unreadable GSTIN does not block: the matcher's anchored tier can still place the bill. Duplicate
photos are caught by the matcher through `image_hash`.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation

from gstagent import gstin
from gstagent.extract import BillRead
from gstagent.models import BookEntry, DocType, Task, TaxpayerProfile
from gstagent.rules import RuleBook
from gstagent.rules.logic import rupees

REQUIRED = ("supplier_name", "doc_type", "invoice_no", "invoice_date", "taxable_value", "rate", "igst", "cgst", "sgst")
MONEY = ("taxable_value", "rate", "igst", "cgst", "sgst", "total")
MIN_CONFIDENCE = 0.6
ARITH_TOLERANCE = Decimal("1.00")
RESNAP_ACTION = "Ask the shop for a clearer photo of the whole bill."
MONTHS = {m: i for i, m in enumerate(("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov",
                                      "dec"), 1)}


def printed_date(text: str) -> date | None:
    """A date as printed on an Indian bill: day first (01/10/2026 is 1 October). None if it isn't a full date."""
    t = text.strip()
    if m := re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})", t):  # ISO, year first
        y, mo, d = m.groups()
    elif m := re.fullmatch(r"([A-Za-z]{3,9})\.? (\d{1,2}),? (\d{4})", t):  # Oct 1, 2026
        mo, d, y = m.groups()
    elif m := re.fullmatch(r"(\d{1,2})[/.\- ]+(\d{1,2}|[A-Za-z]{3,9})[/.,\- ]+(\d{4}|\d{2})", t):
        d, mo, y = m.groups()
    else:
        return None
    mo = int(mo) if mo.isdigit() else MONTHS.get(mo[:3].lower())
    try:
        return date(int(y) + (2000 if len(y) == 2 else 0), mo, int(d))
    except (TypeError, ValueError):
        return None


def image_hash(image: bytes) -> str:
    # shortcut: exact-bytes hash catches the same file sent twice, not a second photo of the same bill;
    # switch to a perceptual hash (e.g. imagehash.phash) once real photos come in.
    return hashlib.sha256(image).hexdigest()[:16]


@dataclass
class Checked:
    bill: BookEntry | None                 # None when the numbers can't be matched yet
    resnap: list[Task] = field(default_factory=list)


def _money(v: str | None) -> Decimal | None:
    try:
        return Decimal(re.sub(r"[₹,\s]|Rs\.?", "", v)) if v else None
    except InvalidOperation:
        return None


def validate(read: BillRead, img_hash: str, bill_id: str, profile: TaxpayerProfile, rules: RuleBook) -> Checked:
    tasks: list[Task] = []

    def resnap(check: str, reason: str, blocks: bool, rule: str | None = None, citations: list[str] = (),
               action: str = RESNAP_ACTION) -> None:
        tasks.append(Task(id=f"{bill_id}-resnap-{len(tasks) + 1}", kind="resnap", detail={
            "check": check, "reason": reason, "blocks_matching": blocks, "rule": rule or f"validator.{check}",
            "citations": list(citations), "action": action}))

    # 1. Every field the matcher needs is present, readable and confident.
    f = {k: getattr(read, k) for k in BillRead.model_fields}
    nums = {k: _money(f[k].value) for k in MONEY}
    try:
        inv_date = date.fromisoformat(f["invoice_date"].value or "")
    except ValueError:
        inv_date = None
    doc_ok = f["doc_type"].value in {d.value for d in DocType}
    unclear = [k for k in REQUIRED if f[k].value is None or f[k].confidence < MIN_CONFIDENCE
               or (k in nums and nums[k] is None) or (k == "invoice_date" and inv_date is None)
               or (k == "doc_type" and not doc_ok)]
    if unclear:
        resnap("fields", f"Could not read clearly: {', '.join(unclear)}.", blocks=True)
        return Checked(None, tasks)

    # 1b. The date as printed, read day first, must agree with the model's date (a model once read 01/10 as 10 Jan).
    p = f.get("invoice_date_printed")
    shown = printed_date(p.value) if p and p.value else None
    if shown and shown != inv_date:
        resnap("date", f"The bill shows the date as '{p.value}'. Read day first, as on Indian bills, that is "
                       f"{shown:%d-%m-%Y}, but it was read as {inv_date:%d-%m-%Y}.", blocks=True,
               action="Ask the shop to confirm the invoice date before anyone is asked about this bill.")
        return Checked(None, tasks)

    taxable, rate, igst, cgst, sgst, total = (nums[k] for k in MONEY)
    tax = igst + cgst + sgst

    # 2. GSTIN check digit, with the position-14 'Z' repair (gstin.py).
    g = gstin.check(f["supplier_gstin"].value or "")
    if not g.valid:
        resnap("gstin", f"Supplier GSTIN on the photo failed the check: {g.reason}.", blocks=False,
               action="Ask the shop for a clearer photo of the supplier GSTIN.")

    # 3. State codes decide CGST+SGST or IGST (rule card gst.tax_split).
    pos = f["place_of_supply"].value
    if not (pos and re.fullmatch(r"\d{2}", pos) and f["place_of_supply"].confidence >= MIN_CONFIDENCE):
        pos = profile.state_code  # goods delivered to the shop: place of supply is the shop's state
    if g.valid:
        r = rules.evaluate("gst.tax_split", inv_date, supplier_state=g.state_code, place_of_supply=pos,
                           igst=igst, cgst=cgst, sgst=sgst)
        if not r.value["ok"]:
            resnap("tax_split", r.explanation, blocks=True, rule=f"{r.rule_id}@{r.version}", citations=r.citations,
                   action=RESNAP_ACTION + " If the print really shows this, ask the supplier for a corrected invoice.")

    # 4. Arithmetic: tax is rate% of taxable value; total is taxable value plus tax.
    expected_tax = taxable * rate / 100
    if abs(tax - expected_tax) > ARITH_TOLERANCE:
        resnap("arithmetic", f"Tax on the bill is {rupees(tax)}, but {rate}% of {rupees(taxable)} is "
                             f"{rupees(expected_tax)}.", blocks=True)
    if total is not None and f["total"].confidence >= MIN_CONFIDENCE and abs(total - (taxable + tax)) > ARITH_TOLERANCE:
        resnap("arithmetic", f"Total on the bill is {rupees(total)}, but taxable value plus tax is "
                             f"{rupees(taxable + tax)}.", blocks=True)

    if any(t.detail["blocks_matching"] for t in tasks):
        return Checked(None, tasks)
    bill = BookEntry(
        id=bill_id, supplier_gstin_raw=f["supplier_gstin"].value or "", supplier_name=f["supplier_name"].value,
        doc_type=DocType(f["doc_type"].value), invoice_no=f["invoice_no"].value, invoice_date=inv_date,
        taxable_value=taxable, rate=rate, igst=igst, cgst=cgst, sgst=sgst, source="whatsapp_photo",
        extraction_confidence=min(f[k].confidence for k in REQUIRED), image_hash=img_hash)
    return Checked(bill, tasks)
