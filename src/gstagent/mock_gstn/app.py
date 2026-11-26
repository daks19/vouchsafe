"""SIMULATED GST portal for the demo. Not connected to GSTN.

Serves GSTR-2B in the GSP-documented JSON shape, IMS actions validated by the
`ims.treatment` rule card, and demo triggers for "the supplier files GSTR-1A" and
"a supplier's registration is cancelled with a backdated effective date".

    uv run uvicorn gstagent.mock_gstn.app:app --reload --port 8100
"""

from __future__ import annotations

import copy
from datetime import date
from typing import Literal

from fastapi import FastAPI, HTTPException, Response
from pydantic import BaseModel

from gstagent.data import load_json, portal_records_from_2b
from gstagent.rules import RuleBook

BANNER = "SIMULATED: mock GST portal (GSP-documented schema), fictional data"

app = FastAPI(title="Mock GSTN (simulated)", description=BANNER)
RULES = RuleBook.load()


class _State:
    def reset(self) -> None:
        self.gstr2b = load_json("gstr2b_102026.json")
        self.pending_event = load_json("gstr1a_event.json")
        self.ims: dict[str, str] = {}
        self.cancelled: dict[str, date] = {}  # ctin -> effective date of cancellation

    def period_start(self) -> date:
        p = self.gstr2b["data"]["rtnprd"]
        return date(int(p[2:]), int(p[:2]), 1)


STATE = _State()
STATE.reset()


@app.middleware("http")
async def simulated_header(request, call_next):
    response = await call_next(request)
    response.headers["X-Simulated"] = "true"
    return response


@app.get("/health")
def health():
    return {"ok": True, "banner": BANNER}


@app.post("/mock-gstn/reset")
def reset():
    STATE.reset()
    return {"ok": True}


def _check_period(gstin: str, rtnprd: str) -> None:
    d = STATE.gstr2b["data"]
    if gstin != d["gstin"] or rtnprd != d["rtnprd"]:
        raise HTTPException(404, f"no data for {gstin} / {rtnprd} in the simulation")


@app.get("/mock-gstn/gstr2b")
def gstr2b(gstin: str, rtnprd: str):
    _check_period(gstin, rtnprd)
    return STATE.gstr2b


class SupplierFiles(BaseModel):
    ctin: str


@app.post("/mock-gstn/events/supplier-files-gstr1a")
def supplier_files_gstr1a(ev: SupplierFiles):
    """Demo trigger: the chased supplier reports the missing invoices; GSTR-2B is recomputed."""
    pending = STATE.pending_event
    if not pending or pending["ctin"] != ev.ctin or not pending["records"]:
        raise HTTPException(404, "no pending filing for this supplier in the simulation")
    b2b = STATE.gstr2b["data"]["docdata"]["b2b"]
    sup = next((s for s in b2b if s["ctin"] == ev.ctin), None)
    if sup is None:
        sup = {"ctin": ev.ctin, "trdnm": pending["trdnm"], "supfildt": None, "supprd": None, "inv": []}
        b2b.append(sup)
    for r in pending["records"]:
        dd = lambda iso: "-".join(reversed(iso.split("-")))  # noqa: E731  ISO -> dd-mm-yyyy
        sup["supfildt"], sup["supprd"] = dd(r["supfildt"]), r["supprd"]
        sup["inv"].append({
            "inum": r["inum"], "typ": "R", "dt": dd(r["dt"]), "val": r["val"], "pos": r["pos"],
            "rev": r["rev"], "itcavl": r["itcavl"], "rsn": r["rsn"], "txval": r["txval"],
            "igst": r["igst"], "cgst": r["cgst"], "sgst": r["sgst"], "cess": "0",
        })
    added = len(pending["records"])
    STATE.pending_event = {**pending, "records": []}
    return {"added": added, "ctin": ev.ctin, "note": "GSTR-2B recomputed (simulated)"}


class SupplierCancelled(BaseModel):
    ctin: str
    effective_from: date


@app.post("/mock-gstn/events/supplier-cancelled")
def supplier_cancelled(ev: SupplierCancelled):
    """Demo trigger: the officer cancels a supplier's registration from a past date."""
    STATE.cancelled[ev.ctin] = ev.effective_from
    return {"ctin": ev.ctin, "effective_from": ev.effective_from, "note": "Cancellation recorded (simulated)"}


@app.get("/mock-gstn/suppliers/{ctin}")
def supplier_status(ctin: str):
    """Registration status, as a GSP taxpayer search would show it."""
    eff = STATE.cancelled.get(ctin)
    return {"_simulated": BANNER, "ctin": ctin, "status": "Cancelled" if eff else "Active", "effective_from": eff}


@app.get("/mock-gstn/ims")
def ims(gstin: str, rtnprd: str):
    _check_period(gstin, rtnprd)
    rows = []
    for p in portal_records_from_2b(STATE.gstr2b):
        if p.rev == "Y":
            continue  # reverse-charge records are not part of IMS; they flow into GSTR-2B directly
        k = f"{p.ctin}|{p.inum}"
        rows.append({"key": k, "ctin": p.ctin, "trdnm": p.trdnm, "doc_type": p.doc_type.value,
                     "inum": p.inum, "val": str(p.val), "action": STATE.ims.get(k, "NO_ACTION")})
    return {"_simulated": BANNER, "records": rows}


class ImsAction(BaseModel):
    ctin: str
    inum: str
    action: Literal["ACCEPTED", "REJECTED", "PENDING"]


class ImsSave(BaseModel):
    gstin: str
    rtnprd: str
    actions: list[ImsAction]


@app.post("/mock-gstn/ims/save")
def ims_save(req: ImsSave, response: Response):
    _check_period(req.gstin, req.rtnprd)
    records = {f"{p.ctin}|{p.inum}": p for p in portal_records_from_2b(STATE.gstr2b)}
    staged = copy.copy(STATE.ims)
    for a in req.actions:
        k = f"{a.ctin}|{a.inum}"
        if k not in records:
            raise HTTPException(404, f"{k} is not in IMS for this period")
        r = RULES.evaluate("ims.treatment", STATE.period_start(),
                           doc_type=records[k].doc_type.value, action=a.action,
                           reverse_charge=records[k].rev == "Y")
        if not r.value["allowed"]:
            raise HTTPException(422, {"key": k, "reason": r.explanation, "citations": r.citations})
        staged[k] = a.action
    STATE.ims = staged
    return {"saved": len(req.actions), "note": "Saved in the simulation. Recompute GSTR-2B before filing."}
