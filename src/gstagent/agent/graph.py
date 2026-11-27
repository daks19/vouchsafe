"""The agent loop: one LangGraph thread per case.

Each case runs plan -> act -> wait -> re-check -> close or hand off to the CA. The graph pauses with
interrupt() before every outbound message, IMS action and CA hand-off, and while it waits for a reply
or a portal event. The SQLite checkpointer keeps every case across days and restarts.

Rules and Python decide every step. Claude only reads the receiver's reply (reply.py). Every drafted
text passes the number guard, and an approval counts only if it carries the hash of the exact text shown.
"""

from __future__ import annotations

import hashlib
import json
import operator
import sqlite3
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Annotated, Callable, TypedDict

import httpx
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from gstagent import data, guard, gstin, language, snapshots
from gstagent.agent import reply as reply_mod
from gstagent.agent.cases import period_start
from gstagent.llm import LLMError
from gstagent.matcher import AMOUNT_TOLERANCE, norm_inv, reconcile
from gstagent.models import BookEntry, MatchStatus
from gstagent.rules import RuleBook
from gstagent.rules.logic import rupees

RULES = RuleBook.load()
PROFILE = data.load_profile()
FORMS = ("GSTR-2B", "GSTR-1A", "GSTR-1", "GSTR-3B", "IFF")  # form names whose digits the guard may see
MAX_ASKS = 2     # W1: ask the receiver at most twice, then hand to the CA
MAX_CHECKS = 3   # W2: re-check the portal three times, then hand to the CA


class CaseState(TypedDict, total=False):
    case_id: str
    workflow: str                 # W1 | W2 | W3
    facts: dict                   # plain strings only; also the number guard's allow-list
    bill: dict                    # W2: the bill being chased (BookEntry as JSON)
    draft: dict                   # the action waiting for approval
    approved: bool
    reply: str
    answer: str
    asks: int
    checks: int
    snapshots: list[dict]
    outcome: str
    timeline: Annotated[list[dict], operator.add]   # append-only audit log
    outbox: Annotated[list[dict], operator.add]     # messages sent (channel is simulated until 7 Dec)


def _event(kind: str, summary: str) -> dict:
    return {"at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "kind": kind, "summary": summary}


def _dd(iso: str) -> str:
    return "-".join(reversed(iso.split("-")))


def _sha(d: dict) -> str:
    shown = {k: d.get(k) for k in ("kind", "to", "text", "text_en", "lang")}
    return hashlib.sha256(json.dumps(shown, sort_keys=True).encode()).hexdigest()


def _allowed(s: CaseState, extra: tuple = ()) -> list:
    return [*s["facts"].values(), *FORMS, PROFILE.gstin, *extra]


def _draft(s: CaseState, kind: str, to: str, text: str, then: str, after: str | None = None,
           outcome: str | None = None, extra: tuple = ()) -> dict:
    g = guard.check(text, _allowed(s, extra))
    if not g.ok:
        raise ValueError(f"number guard blocked a {kind}: {g.unknown}")
    return {"kind": kind, "to": to, "text": text, "lang": "en-IN", "approver": "owner", "then": then,
            "after": after, "outcome": outcome}


def build(portal: httpx.Client, classify: Callable[[str, str], str], today: date, checkpointer,
          translate: Callable[[str, str], str] = language.translate,
          deliver: Callable[[dict], str] | None = None):
    def message(s: CaseState, text: str, after: str, outcome: str | None = None) -> dict:
        """A message to a person, in their language. The English stays beside it for the owner to check."""
        f = s["facts"]
        d = _draft(s, "message", f["to"], text, then="send", after=after, outcome=outcome)
        lang = f.get("lang", "en-IN")
        name = language.LANGUAGES.get(lang, lang)
        if lang == "en-IN":
            return d
        try:
            t = translate(text, lang)
        except LLMError as e:
            return {**d, "note": f"Shown in English: no {name} version yet ({e})."}
        if not guard.check(t, _allowed(s)).ok:  # the translation must not add or change a figure
            return {**d, "note": f"Shown in English: the {name} version changed a number."}
        return {**d, "text": t, "text_en": text, "lang": lang}

    def gstr2b(period: str) -> dict:
        r = portal.get("/mock-gstn/gstr2b", params={"gstin": PROFILE.gstin, "rtnprd": period})
        r.raise_for_status()
        return r.json()

    # --- shared ----------------------------------------------------------------------------------
    def open_case(s: CaseState):
        f = s["facts"]
        what = f"{f.get('supplier', f['ctin'])} {f.get('invoice_no', '')}".strip()
        return {"asks": 0, "checks": 0, "timeline": [_event("case.open", f"{s['workflow']} case opened: {what}")]}

    def approve(s: CaseState):
        d, h = s["draft"], _sha(s["draft"])
        ans = interrupt({"type": "approval", "approver": d["approver"], "action": d["kind"], "to": d["to"],
                         "text": d["text"], "text_en": d.get("text_en"), "lang": d["lang"], "note": d.get("note"),
                         "sha256": h})
        ok = bool(ans.get("approve")) and ans.get("sha256") == h
        why = "approved" if ok else ("declined" if not ans.get("approve") else "declined (text changed since shown)")
        return {"approved": ok, "timeline": [_event(f"{d['approver']}.{why.split()[0]}", f"{d['kind']} {why}")]}

    def declined(s: CaseState):
        return {"outcome": "Owner declined; nothing was sent.", "timeline": [_event("case.closed", "declined")]}

    def send(s: CaseState):
        d = s["draft"]
        kind = "shop.asked" if s["workflow"] == "W1" else "supplier.messaged"
        lang = language.LANGUAGES.get(d["lang"], d["lang"])
        item = {"to": d["to"], "lang": d["lang"], "text": d["text"], "text_en": d.get("text_en"),
                "note": d.get("note"), "sha256": _sha(d), "voice": s["workflow"] == "W1"}  # the shop gets a voice note
        how = deliver(item) if deliver else "simulated channel"
        return {"outbox": [item], "timeline": [_event(kind, f"Sent to {d['to']} in {lang} ({how})")]}

    def done(s: CaseState):
        return {"outcome": s["draft"]["outcome"], "timeline": [_event("case.closed", s["draft"]["outcome"])]}

    def handoff_draft(s: CaseState):
        f = s["facts"]
        if s["workflow"] == "W1":
            text = (f"{f['supplier']} invoice {f['invoice_no']} dated {_dd(f['invoice_date'])} for "
                    f"{rupees(Decimal(f['value']))} is in GSTR-2B with no bill. {f['to']} replied: \"{s.get('reply', '')}\" "
                    f"(read as: {s.get('answer', 'no answer')}). One staff answer is not proof. "
                    "The CA decides whether to reject it in IMS.")
            return {"draft": _draft(s, "ca_handoff", "CA", text, then="handoff", extra=(s.get("reply", ""),))}
        tl = RULES.evaluate("itc.time_limit_16_4", today, invoice_date=f["invoice_date"], check_date=today,
                            filing_scheme=PROFILE.scheme.value, state_code=PROFILE.state_code)
        problem = {"missing_in_2b": "not in GSTR-2B", "amount_mismatch": "filed amount differs from the bill"}
        text = (f"{f['supplier']} has not fixed invoice {f['invoice_no']} ({problem[f['problem']]}) after "
                f"{s['checks']} portal checks. ITC at risk: {rupees(Decimal(f['at_risk']))}. {tl.explanation}")
        return {"draft": _draft(s, "ca_handoff", "CA", text, then="handoff", extra=(str(s["checks"]), tl.explanation))}

    def handoff(s: CaseState):
        return {"outcome": "Handed to the CA with the full case.", "timeline": [_event("ca.handoff", s["draft"]["text"])]}

    # --- W1: confirm the delivery ----------------------------------------------------------------
    def w1_ask(s: CaseState):
        f = s["facts"]
        text = (f"{f['supplier']} invoice {f['invoice_no']} dated {_dd(f['invoice_date'])} for "
                f"{rupees(Decimal(f['value']))} is on the GST portal, but we have no bill for it. "
                "Did this order arrive? Reply: arrived, still coming, or never ordered.")
        return {"draft": message(s, text, after="w1_wait"), "asks": s["asks"] + 1}

    def w1_wait(s: CaseState):
        text = interrupt({"type": "reply", "from": s["facts"]["to"], "question": s["draft"]["text"]})
        return {"reply": text, "timeline": [_event("shop.replied", text)]}

    def w1_understand(s: CaseState):
        answer = classify(s["draft"]["text"], s["reply"])
        return {"answer": answer, "timeline": [_event("reply.understood", answer)]}

    def w1_route(s: CaseState) -> str:
        a = s["answer"]
        if a == "unclear":
            return "w1_ask" if s["asks"] < MAX_ASKS else "handoff_draft"
        return {"arrived": "w1_bill", "still_coming": "w1_ims", "never_ordered": "handoff_draft"}[a]

    def w1_bill(s: CaseState):
        f = s["facts"]
        text = f"Thank you. Please send a photo of the bill for {f['supplier']} invoice {f['invoice_no']}."
        return {"draft": message(s, text, after="done",
                                 outcome="Goods arrived; bill photo requested. It will be matched when it comes in.")}

    def w1_ims(s: CaseState):
        f = s["facts"]
        rule = RULES.evaluate("ims.treatment", period_start(f["period"]), doc_type="INV", action="PENDING")
        text = (f"Mark {f['supplier']} invoice {f['invoice_no']} ({rupees(Decimal(f['value']))}) as Pending in IMS: "
                f"the goods are still on the way. {rule.explanation}")
        return {"draft": _draft(s, "ims_pending", "IMS (simulated portal)", text, then="ims_save",
                                extra=(rule.explanation,))}

    def ims_save(s: CaseState):
        f = s["facts"]
        r = portal.post("/mock-gstn/ims/save", json={"gstin": PROFILE.gstin, "rtnprd": f["period"], "actions": [
            {"ctin": f["ctin"], "inum": f["invoice_no"], "action": "PENDING"}]})
        if r.status_code != 200:  # recover: the portal refused, so a person looks at it
            return {"timeline": [_event("ims.save_failed", r.text)]}
        return {"outcome": "Marked Pending in IMS until the goods arrive.",
                "timeline": [_event("ims.pending_saved", f"{f['invoice_no']} Pending"), _event("case.closed", "pending")]}

    # --- W2: supplier correction -----------------------------------------------------------------
    def w2_ask(s: CaseState):
        f = s["facts"]
        head = (f"Hello. This is {PROFILE.trade_name} (GSTIN {PROFILE.gstin}). Your invoice {f['invoice_no']} "
                f"dated {_dd(f['invoice_date'])}")
        if f["problem"] == MatchStatus.AMOUNT_MISMATCH.value:
            diffs = []  # name only what differs
            if abs(Decimal(f["filed_taxable"]) - Decimal(f["taxable"])) > AMOUNT_TOLERANCE:
                diffs.append(f"taxable value {rupees(Decimal(f['filed_taxable']))}, but the bill says "
                             f"{rupees(Decimal(f['taxable']))}")
            if f.get("filed_date", f["invoice_date"]) != f["invoice_date"]:
                diffs.append(f"the date as {_dd(f['filed_date'])}, but the bill says {_dd(f['invoice_date'])}")
            text = f"{head}: you filed {' and '.join(diffs)}. Please correct it through GSTR-1A."
        else:
            text = (f"{head} (taxable {rupees(Decimal(f['taxable']))}, GST {rupees(Decimal(f['tax']))}) is not in our "
                    "GSTR-2B. Please report it in your GSTR-1/IFF, or in GSTR-1A if that return is already filed.")
        return {"draft": message(s, text, after="w2_wait")}

    def w2_wait(s: CaseState):
        ev = interrupt({"type": "event", "waiting_for": "supplier to file GSTR-1A", "checks_done": s["checks"]})
        return {"timeline": [_event("event.received", (ev or {}).get("type", "tick"))]}

    def w2_recheck(s: CaseState):
        f = s["facts"]
        bill = BookEntry.model_validate(s["bill"])
        records = data.portal_records_from_2b(gstr2b(f["period"]))
        m = next(m for m in reconcile([bill], records, RULES, period_start(f["period"])) if m.book_id == bill.id)
        checks = s["checks"] + 1
        if m.status != MatchStatus.MATCHED:
            return {"checks": checks, "timeline": [_event("portal.checked", f"check {checks}: {m.status.value}")]}
        rec = next(p for p in records if f"{p.ctin}|{p.inum}" == m.portal_key)
        flow = RULES.evaluate("itc.gstr1a_flow", rec.supfildt or today, original_period=f["period"],
                              gstr1a_filed_on=rec.supfildt or today)
        outcome = f"Supplier fixed it; the bill now matches ({m.tier}). {flow.explanation}"
        return {"checks": checks, "outcome": outcome,
                "timeline": [_event("portal.checked", f"check {checks}: matched"), _event("case.closed", outcome)]}

    def w2_route(s: CaseState) -> str:
        if s.get("outcome"):
            return END
        return "w2_wait" if s["checks"] < MAX_CHECKS else "handoff_draft"

    # --- W3: keep purchase evidence --------------------------------------------------------------
    def w3_assess(s: CaseState):
        f = s["facts"]
        st = portal.get(f"/mock-gstn/suppliers/{f['ctin']}").json()
        if st["status"] != "Cancelled":
            return {"outcome": "Supplier is active; no purchases exposed.",
                    "timeline": [_event("portal.checked", "supplier active"), _event("case.closed", "nothing exposed")]}
        eff = date.fromisoformat(st["effective_from"])
        # shortcut: bills come from the synthetic books; read them from the case store once it exists.
        exposed = {norm_inv(b.invoice_no): b for b in data.load_books()
                   if gstin.check(b.supplier_gstin_raw).gstin == f["ctin"] and b.invoice_date >= eff}
        bills = sorted(exposed.values(), key=lambda b: b.invoice_date)
        g2b = gstr2b(f["period"])
        snaps = [snapshots.take(b, g2b) for b in bills]
        packs = [RULES.evaluate("itc.evidence_pack", today, state_code=PROFILE.state_code,
                                present=["invoice"] + (["bank_payment"] if b.paid_on else [])) for b in bills]
        total = sum((b.tax for b in bills), Decimal("0"))
        name = bills[0].supplier_name if bills else f["ctin"]
        lines = [f"{name} ({f['ctin']}): registration cancelled with effect from {_dd(eff.isoformat())}, a past date. "
                 f"{len(bills)} bills dated on or after that are exposed; GST on them {rupees(total)}."]
        for b, sn, p in zip(bills, snaps, packs):
            lines.append(f"- {b.invoice_no} dated {_dd(b.invoice_date.isoformat())}, GST {rupees(b.tax)}. "
                         f"At purchase GSTR-2B showed it {'reported' if sn['in_gstr2b'] else 'not reported'} "
                         f"(snapshot {sn['sha256'][:12]}). Evidence: {p.value['present_count']} of {p.value['total']} documents.")
        lines += list(dict.fromkeys(p.explanation for p in packs))  # same explanation for many bills: say it once
        extra = (st["effective_from"], str(len(bills)), rupees(total), *(rupees(b.tax) for b in bills),
                 *(b.invoice_no for b in bills), *(b.invoice_date.isoformat() for b in bills),
                 *(sn["sha256"][:12] for sn in snaps), *(p.explanation for p in packs),
                 *(f"{p.value['present_count']} {p.value['total']}" for p in packs))
        return {"snapshots": snaps, "facts": {**f, "supplier": name},
                "draft": _draft(s, "ca_handoff", "CA", "\n".join(lines), then="handoff", extra=extra),
                "timeline": [_event("portal.checked", f"cancelled from {st['effective_from']}; {len(bills)} bills exposed")]}

    g = StateGraph(CaseState)
    for name, fn in [("open_case", open_case), ("approve", approve), ("declined", declined), ("send", send),
                     ("done", done), ("handoff_draft", handoff_draft), ("handoff", handoff),
                     ("w1_ask", w1_ask), ("w1_wait", w1_wait), ("w1_understand", w1_understand), ("w1_bill", w1_bill),
                     ("w1_ims", w1_ims), ("ims_save", ims_save),
                     ("w2_ask", w2_ask), ("w2_wait", w2_wait), ("w2_recheck", w2_recheck), ("w3_assess", w3_assess)]:
        g.add_node(name, fn)
    g.add_edge(START, "open_case")
    g.add_conditional_edges("open_case", lambda s: {"W1": "w1_ask", "W2": "w2_ask", "W3": "w3_assess"}[s["workflow"]])
    for n in ("w1_ask", "w1_bill", "w1_ims", "w2_ask", "handoff_draft"):
        g.add_edge(n, "approve")
    g.add_conditional_edges("approve", lambda s: s["draft"]["then"] if s["approved"] else "declined")
    g.add_conditional_edges("send", lambda s: s["draft"]["after"])
    g.add_edge("w1_wait", "w1_understand")
    g.add_conditional_edges("w1_understand", w1_route)
    g.add_conditional_edges("ims_save", lambda s: END if s.get("outcome") else "handoff_draft")
    g.add_edge("w2_wait", "w2_recheck")
    g.add_conditional_edges("w2_recheck", w2_route)
    g.add_conditional_edges("w3_assess", lambda s: END if s.get("outcome") else "approve")
    for n in ("declined", "done", "handoff"):
        g.add_edge(n, END)
    return g.compile(checkpointer=checkpointer)


class Agent:
    """Open cases, see what each one waits for, and answer it. `db` is a SQLite path (":memory:" for tests)."""

    def __init__(self, portal: httpx.Client, db: str = ":memory:",
                 classify: Callable[[str, str], str] = reply_mod.classify, today: date | None = None,
                 translate: Callable[[str, str], str] = language.translate,
                 deliver: Callable[[dict], str] | None = None):
        """`deliver` sends an approved message on a real channel and says how; None keeps it simulated."""
        self.conn = sqlite3.connect(db, check_same_thread=False)
        self.graph = build(portal, classify, today or date.today(), SqliteSaver(self.conn), translate, deliver)

    @staticmethod
    def _cfg(case_id: str) -> dict:
        return {"configurable": {"thread_id": case_id}}

    def open(self, case: dict) -> dict:
        if not self.graph.get_state(self._cfg(case["case_id"])).values:  # never open the same case twice
            self.graph.invoke(case, self._cfg(case["case_id"]))
        return self.view(case["case_id"])

    def answer(self, case_id: str, value) -> dict:
        self.graph.invoke(Command(resume=value), self._cfg(case_id))
        return self.view(case_id)

    def approve(self, case_id: str, yes: bool = True) -> dict:
        w = self.view(case_id)["waiting"]
        if not w or w["type"] != "approval":
            raise ValueError(f"{case_id} is not waiting for an approval")
        return self.answer(case_id, {"approve": yes, "sha256": w["sha256"]})

    def view(self, case_id: str) -> dict:
        st = self.graph.get_state(self._cfg(case_id))
        v = st.values
        return {"case_id": case_id, "workflow": v.get("workflow"),
                "waiting": st.interrupts[0].value if st.interrupts else None,
                "outcome": v.get("outcome"), "timeline": v.get("timeline", []), "outbox": v.get("outbox", []),
                "snapshots": v.get("snapshots", [])}

    def close(self) -> None:
        self.conn.close()
