"""Supplier snapshots: what GSTR-2B showed about a bill's supplier, stamped and hashed.

In production a snapshot is taken when each purchase is recorded (and from a GSP taxpayer search);
then a later backdated cancellation can be compared with what was visible at purchase time. The
prototype takes them from the mock GSTR-2B when a case needs them, and says so (`source`).
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

from gstagent import gstin
from gstagent.matcher import norm_inv
from gstagent.models import BookEntry


def take(bill: BookEntry, gstr2b: dict, taken_at: datetime | None = None) -> dict:
    ctin = gstin.check(bill.supplier_gstin_raw).gstin
    sup = next((s for s in gstr2b["data"]["docdata"].get("b2b", []) if s["ctin"] == ctin), None)
    rec = next((i for i in (sup or {}).get("inv", []) if norm_inv(i["inum"]) == norm_inv(bill.invoice_no)), None)
    snap = {
        "bill_id": bill.id, "ctin": ctin, "invoice_no": bill.invoice_no,
        "in_gstr2b": rec is not None,
        "supplier_filed_on": sup.get("supfildt") if sup else None,
        "supplier_return_period": sup.get("supprd") if sup else None,
        "gstr2b_period": gstr2b["data"]["rtnprd"],
        "taken_at": (taken_at or datetime.now(timezone.utc)).isoformat(timespec="seconds"),
        "source": "mock GSTR-2B (SIMULATED)",
    }
    snap["sha256"] = hashlib.sha256(json.dumps(snap, sort_keys=True).encode()).hexdigest()
    return snap
