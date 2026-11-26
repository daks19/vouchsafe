"""CA exception queue: bill photo -> Claude reads -> validators -> matcher + rule cards -> queue rows.

    uv run python -m gstagent.ca_queue tests/fixtures/bills/nandi_missing_in_2b.png \\
        --replay tests/fixtures/bills/nandi_missing_in_2b.reply.json   # offline; drop --replay to call Claude
    uv run uvicorn gstagent.ca_queue:app --port 8200                   # POST an image to /ca-queue/bills

Runs against the synthetic trader's books and the mock GSTR-2B (SIMULATED data).
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Callable

import anthropic
from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel

from gstagent import data, extract
from gstagent.extract import BillRead
from gstagent.llm import LLMError, NoCredentials
from gstagent.matcher import reconcile
from gstagent.models import BookEntry, Match, MatchStatus
from gstagent.rules import RuleBook
from gstagent.rules.logic import rupees
from gstagent.validate import image_hash, validate

BANNER = "SIMULATED: synthetic trader, mock GSTR-2B, fictional data"
RULES = RuleBook.load()


class QueueItem(BaseModel):
    bill_id: str
    issue: str
    reason: str
    rule: str
    citations: list[str]
    recommended_action: str
    itc_at_risk: Decimal = Decimal("0")


@dataclass
class Result:
    read: BillRead
    bill: BookEntry | None
    queue: list[QueueItem] = field(default_factory=list)


# status (or matched tier) -> (issue, rule id, recommended action). Never "reject": that is the CA's call.
_ROWS = {
    MatchStatus.MISSING_IN_2B: ("Supplier has not reported this bill", "itc.supplier_reported",
                                "Ask the supplier to report it in GSTR-1/IFF (or GSTR-1A), then check GSTR-2B again."),
    MatchStatus.AMOUNT_MISMATCH: ("Bill and supplier's filing differ", "itc.supplier_reported",
                                  "Ask the supplier to correct it through GSTR-1A; keep it Pending in IMS until it matches."),
    MatchStatus.DUPLICATE_IN_BOOKS: ("Same bill sent twice", "matcher.duplicate", "None; the bill is counted once."),
    "normalised": ("Matched with small differences", "matcher.normalised", "None; note the difference on file."),
    "fuzzy": ("Matched; invoice number differs slightly", "matcher.fuzzy", "Confirm the invoice number on the bill."),
    "anchored": ("Matched without a readable GSTIN", "matcher.anchored", "Confirm the supplier GSTIN on the bill."),
    "repaired": ("Matched after a GSTIN repair", "gstin.checksum", "Confirm the repaired GSTIN with the supplier."),
}


def _period_start(gstr2b: dict) -> date:
    p = gstr2b["data"]["rtnprd"]
    return date(int(p[2:]), int(p[:2]), 1)


def _row(m: Match, period_start: date) -> QueueItem | None:
    if m.status == MatchStatus.MATCHED:
        key = "repaired" if m.tier == "exact" and "repaired" in m.reason else m.tier
        if key == "exact":
            return None  # clean: nothing for the CA
    else:
        key = m.status
    issue, rule_id, action = _ROWS[key]
    if rule_id in RULES.cards:
        rule_id = f"{rule_id}@{RULES.get(rule_id, period_start).version}"
    return QueueItem(bill_id=m.book_id, issue=issue, reason=m.reason, rule=rule_id, citations=m.citations,
                     recommended_action=action, itc_at_risk=m.itc_at_risk)


def process(image: bytes, media_type: str, call: Callable[[bytes, str], str] = extract.call_claude,
            seen: list[BookEntry] = ()) -> Result:
    """One bill photo -> its rows in the CA queue (empty when the bill matches cleanly).

    `seen` holds bills already sent this period, so a photo sent twice shows up as a duplicate.
    """
    profile = data.load_profile()
    gstr2b = data.load_json("gstr2b_102026.json")
    period_start = _period_start(gstr2b)
    h = image_hash(image)
    bill_id = f"IMG{len(seen) + 1:03d}"  # the image hash itself goes on the bill for duplicate checks

    read = extract.read_bill(image, media_type, call)
    checked = validate(read, h, bill_id, profile, RULES)
    result = Result(read, checked.bill)
    for t in checked.resnap:
        result.queue.append(QueueItem(bill_id=bill_id, issue="Photo needs a re-snap", reason=t.detail["reason"],
                                      rule=t.detail["rule"], citations=t.detail["citations"],
                                      recommended_action=t.detail["action"]))
    if checked.bill is None:
        return result

    matches = reconcile(data.load_books() + list(seen) + [checked.bill], data.portal_records_from_2b(gstr2b), RULES, period_start)
    result.queue += [r for m in matches if m.book_id == bill_id and (r := _row(m, period_start))]

    rate = RULES.evaluate("gst.rate_check", checked.bill.invoice_date, rate=checked.bill.rate)
    if rate.value["category"] != "standard":
        result.queue.append(QueueItem(bill_id=bill_id, issue="Rate needs review", reason=rate.explanation,
                                      rule=f"{rate.rule_id}@{rate.version}", citations=rate.citations,
                                      recommended_action="Check the HSN and rate with the supplier; do not reject."))
    return result


# --- API -------------------------------------------------------------------------------------------

app = FastAPI(title="Vouchsafe CA queue (prototype)", description=BANNER)
QUEUE: list[QueueItem] = []
SEEN: list[BookEntry] = []  # bills received through the API (in memory; resets on restart)
CALL: Callable[[bytes, str], str] = extract.call_claude  # tests swap in a recorded reply


@app.middleware("http")
async def simulated_header(request, call_next):
    response = await call_next(request)
    response.headers["X-Simulated"] = "true"
    return response


@app.post("/ca-queue/bills")
async def add_bill(request: Request):
    """Body: the raw image bytes, with Content-Type image/png, image/jpeg or image/webp."""
    media_type = request.headers.get("content-type", "").split(";")[0].strip()
    if media_type not in extract.MEDIA_TYPES.values():
        raise HTTPException(415, "send the bill as image/png, image/jpeg or image/webp")
    image = await request.body()
    if not image:
        raise HTTPException(400, "empty body")
    try:
        r = process(image, media_type, CALL, SEEN)
    except NoCredentials as e:
        raise HTTPException(503, str(e)) from e
    except LLMError as e:
        raise HTTPException(422, str(e)) from e
    except anthropic.AnthropicError as e:
        raise HTTPException(502, f"could not reach the LLM: {e}") from e
    QUEUE.extend(r.queue)
    if r.bill:
        SEEN.append(r.bill)
    return {"_simulated": BANNER, "bill": r.bill, "read": r.read, "queue": r.queue}


@app.get("/ca-queue")
def queue():
    return {"_simulated": BANNER, "items": QUEUE}


@app.post("/ca-queue/reset")
def reset():
    QUEUE.clear()
    SEEN.clear()
    return {"ok": True}


# --- CLI -------------------------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Bill photo -> CA-queue exceptions (synthetic data).")
    ap.add_argument("image", type=Path)
    ap.add_argument("--replay", type=Path, help="use a saved Claude reply (JSON) instead of calling the API")
    ap.add_argument("--save-reply", type=Path, help="save the live Claude reply here, to replay later")
    a = ap.parse_args(argv)

    call = extract.call_claude
    if a.replay:
        call = lambda *_: a.replay.read_text()  # noqa: E731
    elif a.save_reply:
        def call(img: bytes, mt: str) -> str:
            text = extract.call_claude(img, mt)
            a.save_reply.write_text(text)
            return text
    try:
        r = process(a.image.read_bytes(), extract.media_type_of(a.image), call)
    except (LLMError, anthropic.AnthropicError, OSError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    print(f"[{BANNER}]")
    b = r.bill
    print(f"Bill: {b.supplier_name} {b.invoice_no} dated {b.invoice_date}, taxable {rupees(b.taxable_value)}, "
          f"tax {rupees(b.tax)} (confidence {b.extraction_confidence:.2f})" if b else "Bill: not matched yet")
    if not r.queue:
        print("CA queue: nothing to review; the bill matches the supplier's filing.")
    for i, q in enumerate(r.queue, 1):
        print(f"\n{i}. {q.issue}  [{q.rule}]")
        print(f"   Reason: {q.reason}")
        if q.itc_at_risk:
            print(f"   ITC at risk: {rupees(q.itc_at_risk)}")
        for c in q.citations:
            print(f"   Cites: {c}")
        print(f"   Action: {q.recommended_action}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
