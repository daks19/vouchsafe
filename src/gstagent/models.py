"""Case schema: the single source of truth every module reads and writes.

Money is always Decimal (never float). The LLM fills extraction fields only;
every computed figure comes from a rule card (see gstagent.rules).
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field


class Scheme(StrEnum):
    REGULAR_MONTHLY = "regular_monthly"
    REGULAR_QRMP = "regular_qrmp"
    COMPOSITION = "composition"


class TaxpayerProfile(BaseModel):
    """Profile gate: decides which modules apply at all."""

    gstin: str
    legal_name: str
    trade_name: str | None = None
    state_code: str
    scheme: Scheme
    holder_type: str  # from PAN 4th char: individual, huf, firm, llp, company, ...
    prior_year_turnover: Decimal
    income_kind: Literal["business", "profession"] = "business"
    preferred_language: str = "en-IN"   # language code, see gstagent.language
    accountant_name: str | None = None


class Supplier(BaseModel):
    gstin: str
    name: str
    state_code: str
    phone: str | None = None
    language: str = "en-IN"


class DocType(StrEnum):
    INVOICE = "INV"
    CREDIT_NOTE = "CRN"
    DEBIT_NOTE = "DBN"


class BookEntry(BaseModel):
    """A purchase bill as captured from the owner (photo, voice or manual)."""

    id: str
    supplier_gstin_raw: str           # exactly as captured; may contain OCR errors
    supplier_name: str
    doc_type: DocType = DocType.INVOICE
    invoice_no: str
    invoice_date: date
    taxable_value: Decimal
    rate: Decimal                     # GST rate %, e.g. Decimal("18")
    igst: Decimal = Decimal("0")
    cgst: Decimal = Decimal("0")
    sgst: Decimal = Decimal("0")
    source: Literal["whatsapp_photo", "voice_note", "manual", "tally_import"] = "whatsapp_photo"
    extraction_confidence: float = 1.0
    image_hash: str | None = None     # perceptual hash, for duplicate detection
    paid_on: date | None = None

    @property
    def tax(self) -> Decimal:
        return self.igst + self.cgst + self.sgst


class PortalRecord(BaseModel):
    """One inward document as GSTR-2B / IMS shows it (GSP-documented field names)."""

    ctin: str                          # supplier GSTIN
    trdnm: str                         # supplier trade name
    typ: str = "R"                     # R regular, etc.
    doc_type: DocType = DocType.INVOICE
    inum: str
    dt: date
    val: Decimal                       # invoice value
    txval: Decimal
    igst: Decimal = Decimal("0")
    cgst: Decimal = Decimal("0")
    sgst: Decimal = Decimal("0")
    pos: str                           # place of supply state code
    rev: Literal["Y", "N"] = "N"       # reverse charge
    itcavl: Literal["Y", "N"] = "Y"
    rsn: str = ""                      # reason if ITC not available
    supfildt: date | None = None       # supplier filing date
    supprd: str | None = None          # supplier return period MMYYYY
    ims_action: Literal["NO_ACTION", "ACCEPTED", "REJECTED", "PENDING"] = "NO_ACTION"

    @property
    def tax(self) -> Decimal:
        return self.igst + self.cgst + self.sgst


class MatchStatus(StrEnum):
    MATCHED = "matched"
    AMOUNT_MISMATCH = "amount_mismatch"
    MISSING_IN_2B = "missing_in_2b"        # in books, supplier has not reported it
    MISSING_IN_BOOKS = "missing_in_books"  # supplier reported it, owner has no bill
    DUPLICATE_IN_BOOKS = "duplicate_in_books"


class Match(BaseModel):
    book_id: str | None
    portal_key: str | None              # f"{ctin}|{inum}"
    status: MatchStatus
    tier: str | None = None             # exact | normalised | fuzzy | anchored
    itc_at_risk: Decimal = Decimal("0")
    reason: str                         # plain-language explanation shown to CA/owner
    citations: list[str] = Field(default_factory=list)


class TaskState(StrEnum):
    PLANNED = "planned"
    WAITING_APPROVAL = "waiting_approval"
    WAITING_EXTERNAL = "waiting_external"   # e.g. supplier to file GSTR-1A
    DONE = "done"
    ESCALATED = "escalated"


class Task(BaseModel):
    id: str
    kind: str                          # chase_supplier, ims_recommendation, ...
    due: date | None = None
    state: TaskState = TaskState.PLANNED
    detail: dict = Field(default_factory=dict)


class Approval(BaseModel):
    """Human approval, bound to a hash of exactly what was approved."""

    task_id: str
    approver: Literal["owner", "accountant"]
    content_sha256: str
    approved_at: datetime


class CaseEvent(BaseModel):
    at: datetime
    kind: str
    summary: str
    data: dict = Field(default_factory=dict)


class Case(BaseModel):
    """Memory of one business for one tax period."""

    profile: TaxpayerProfile
    period: str                        # MMYYYY
    books: list[BookEntry] = Field(default_factory=list)
    portal: list[PortalRecord] = Field(default_factory=list)
    matches: list[Match] = Field(default_factory=list)
    tasks: list[Task] = Field(default_factory=list)
    approvals: list[Approval] = Field(default_factory=list)
    timeline: list[CaseEvent] = Field(default_factory=list)
