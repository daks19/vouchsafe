"""Read a bill photo into fixed fields with Claude vision.

Every field comes back as {"value": str | null, "confidence": 0..1}. Unclear fields are null,
never guessed. Money stays a string here and becomes Decimal in the validators.

Privacy: only the image goes to the model. The prompt carries no GSTIN, PAN or name.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Callable

import anthropic
from pydantic import BaseModel

MODEL = "claude-opus-5-5"

FIELDS = {
    "supplier_name": "seller's trade name as printed",
    "supplier_gstin": "seller's 15-character GSTIN",
    "buyer_gstin": "buyer's 15-character GSTIN, if printed",
    "doc_type": "INV for a tax invoice, CRN for a credit note, DBN for a debit note",
    "invoice_no": "invoice or note number exactly as printed, punctuation included",
    "invoice_date": "invoice date as YYYY-MM-DD",
    "place_of_supply": "two-digit state code of the place of supply, e.g. 29",
    "hsn": "HSN/SAC codes, comma-separated",
    "taxable_value": "total taxable value before tax, digits and a decimal point only",
    "rate": "GST rate in percent, e.g. 18 (the total rate, not the CGST half)",
    "igst": "total IGST amount, digits only; 0 if the bill shows none",
    "cgst": "total CGST amount, digits only; 0 if the bill shows none",
    "sgst": "total SGST/UTGST amount, digits only; 0 if the bill shows none",
    "total": "grand total payable, digits only",
}

PROMPT = (
    "This is a photo of an Indian GST purchase bill. Copy each field exactly as printed.\n"
    "If a field is missing, cut off, blurred or you are not sure, set value to null. Never guess or compute "
    "a value that is not printed; never fix a GSTIN that looks wrong.\n"
    "confidence is how sure you are that value matches the print, from 0 to 1.\n\nFields:\n"
    + "\n".join(f"- {k}: {v}" for k, v in FIELDS.items())
)

_FIELD_SCHEMA = {
    "type": "object",
    "properties": {"value": {"type": ["string", "null"]}, "confidence": {"type": "number"}},
    "required": ["value", "confidence"],
    "additionalProperties": False,
}
SCHEMA = {
    "type": "object",
    "properties": {k: _FIELD_SCHEMA for k in FIELDS},
    "required": list(FIELDS),
    "additionalProperties": False,
}


class Read(BaseModel):
    value: str | None
    confidence: float


class BillRead(BaseModel):
    supplier_name: Read
    supplier_gstin: Read
    buyer_gstin: Read
    doc_type: Read
    invoice_no: Read
    invoice_date: Read
    place_of_supply: Read
    hsn: Read
    taxable_value: Read
    rate: Read
    igst: Read
    cgst: Read
    sgst: Read
    total: Read


class ExtractionError(Exception):
    pass


class NoCredentials(ExtractionError):
    pass


def call_claude(image: bytes, media_type: str) -> str:
    """One Claude vision call; returns the JSON text. Key from ANTHROPIC_API_KEY (or an `ant` profile)."""
    client = anthropic.Anthropic()
    try:
        msg = _create(client, image, media_type)
    except TypeError as e:  # the SDK raises TypeError when it finds no key
        if "authentication" not in str(e):
            raise
        raise NoCredentials("no Claude credentials: export ANTHROPIC_API_KEY, or use --replay") from e
    if msg.stop_reason != "end_turn":
        raise ExtractionError(f"Claude stopped with {msg.stop_reason}; ask for the bill again")
    return next(b.text for b in msg.content if b.type == "text")


def _create(client: anthropic.Anthropic, image: bytes, media_type: str):
    return client.beta.messages.create(
        model=MODEL,
        max_tokens=16000,  # adaptive thinking is always on and counts against this
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        output_config={"effort": "medium", "format": {"type": "json_schema", "schema": SCHEMA}},
        messages=[{"role": "user", "content": [
            {"type": "image", "source": {"type": "base64", "media_type": media_type,
                                         "data": base64.standard_b64encode(image).decode()}},
            {"type": "text", "text": PROMPT},
        ]}],
    )


MEDIA_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}


def read_bill(image: bytes, media_type: str, call: Callable[[bytes, str], str] = call_claude) -> BillRead:
    """Bill image -> fields with confidence. Pass `call` to replay a recorded response (tests, offline demo)."""
    try:
        read = BillRead.model_validate(json.loads(call(image, media_type)))
    except (json.JSONDecodeError, ValueError) as e:
        raise ExtractionError(f"model reply did not fit the bill schema: {e}") from e
    for r in read.__dict__.values():
        r.confidence = min(max(r.confidence, 0.0), 1.0)
        if r.value is not None and not r.value.strip():
            r.value = None
    return read


def media_type_of(path: Path) -> str:
    try:
        return MEDIA_TYPES[path.suffix.lower()]
    except KeyError:
        raise ExtractionError(f"{path.name}: send a PNG, JPEG or WebP photo") from None
