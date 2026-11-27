"""The CA workspace: one page over the live agent. The owner approves what goes out; the CA decides each hand-off.

    uv run python -m gstagent.dashboard                                   # rehearsal: offline, no keys, simulated channel
    uv run python -m gstagent.dashboard --live                            # the LLM translates and reads replies
    uv run python -m gstagent.dashboard --lang ta-IN --channel telegram   # W1 goes to the Telegram demo chat (live)

Then open http://localhost:8000 (build the page first: cd frontend && npm install && npm run build).
Portal, supplier events and data are SIMULATED. With --channel telegram, messages to the shop are real and go only
to TELEGRAM_DEMO_CHAT; messages to suppliers stay simulated (one phone on stage).
"""

from __future__ import annotations

import argparse
import logging
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Callable

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.testclient import TestClient
from pydantic import BaseModel

from gstagent import data, language
from gstagent.agent import demo, reply
from gstagent.agent.graph import RULES, Agent
from gstagent.channels import live, telegram
from gstagent.llm import LLMError
from gstagent.mock_gstn.app import app as mock_app

log = logging.getLogger("gstagent.dashboard")
DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"
RULE_IDS = {"W1": ["ims.treatment"], "W2": ["itc.time_limit_16_4", "itc.gstr1a_flow"], "W3": ["itc.evidence_pack"]}
STATUS = {"approval": "waiting_approval", "reply": "waiting_reply", "event": "waiting_supplier",
          "ca_decision": "waiting_ca"}
SAMPLES = ["Kaveri Textiles (sample)", "Nandini Medicals (sample)"]  # not clickable: the demo has one client


def shop_only(send: Callable[[dict], str]) -> Callable[[dict], str]:
    """Only the shop's messages (W1, sent with a voice note) go out for real; supplier messages stay simulated."""
    return lambda item: send(item) if item.get("voice") else "simulated channel (one phone on stage)"


class Approval(BaseModel):
    approve: bool
    sha256: str


class Decision(BaseModel):
    choice: str
    note: str = ""
    reason: str = ""
    not_applicable: list[str] = []
    sha256: str


class Reply(BaseModel):
    text: str


def make_app(lang: str = "ta-IN", channel: str = "none", live_llm: bool = False,
             classify: Callable[[str, str], str] | None = None) -> FastAPI:
    real = live_llm or channel == "telegram"
    classify = classify or (reply.classify if real else (lambda q, r: demo.SCRIPTED.get(r, "unclear")))
    translate = language.translate if real else demo.offline_translate
    deliver = shop_only(live.deliver) if channel == "telegram" else None
    portal = TestClient(mock_app)
    lock = threading.Lock()  # one agent call at a time: page clicks and the Telegram thread share it
    s: dict = {}

    def reset() -> None:
        s["cases"] = {c["case_id"]: c for c in demo.cases_for(portal, lang)}
        s["agent"] = Agent(portal, classify=classify, today=demo.TODAY, translate=translate, deliver=deliver)
        s["voice"], s["last_error"] = {}, None
        for c in s["cases"].values():
            s["agent"].open(c)

    def known(cid: str) -> None:
        if cid not in s["cases"]:
            raise HTTPException(404, f"No case {cid}. The scenario may have been reset: reload the page.")

    def status(cid: str, v: dict) -> str:
        if v["waiting"]:
            return STATUS[v["waiting"]["type"]]
        if s["agent"].stuck(cid):
            return "needs_retry"
        return "declined" if (v["outcome"] or "").startswith("Owner declined") else "resolved"

    def waiting_for(cid: str, kind: str) -> dict:
        known(cid)
        w = s["agent"].view(cid)["waiting"]
        if not w or w["type"] != kind:
            raise HTTPException(409, f"This case is not waiting for {kind.replace('_', ' ')} now.")
        return w

    def run(fn: Callable[[], dict]) -> dict:
        try:
            return fn()
        except LLMError as e:  # the step can be run again with /retry
            s["last_error"] = str(e)
            raise HTTPException(502, f"The AI service failed: {e}. Press 'Try again'.") from None

    def on_message(m: dict) -> None:
        """A Telegram message: the reply to the one case waiting for one. Anything else is logged and ignored."""
        with lock:
            cid = next((c for c in s["cases"] if (s["agent"].view(c)["waiting"] or {}).get("type") == "reply"), None)
            if cid is None:
                log.info("Telegram message with no case waiting for a reply: ignored")
                return
            try:
                text = live.heard(m)
                if m["type"] == "audio":
                    s["voice"].setdefault(cid, []).append(text)
                s["agent"].answer(cid, text)
            except live.ERRORS as e:
                s["last_error"] = f"Reply to {cid} not read: {e}"

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if channel == "telegram":
            threading.Thread(target=telegram.poll, args=(on_message,), daemon=True).start()
        yield

    app = FastAPI(title="Vouchsafe CA workspace (SIMULATED)", lifespan=lifespan)
    app.state.on_message = on_message
    reset()

    @app.middleware("http")
    async def simulated(request, call_next):
        r = await call_next(request)
        r.headers["X-Simulated"] = "true"
        return r

    @app.get("/api/clients")
    def clients():
        return [{"name": data.load_profile().trade_name, "active": True}, *({"name": n, "active": False} for n in SAMPLES)]

    @app.get("/api/cases")
    def cases():
        with lock:
            rows = []
            for cid, c in s["cases"].items():
                v = s["agent"].view(cid)
                f = v["facts"] or c["facts"]
                rows.append({"case_id": cid, "workflow": c["workflow"], "status": status(cid, v), "outcome": v["outcome"],
                             "title": f"{f.get('supplier', f['ctin'])} {f.get('invoice_no', '')}".strip()})
            return {"cases": rows, "readiness": {"resolved": sum(r["status"] == "resolved" for r in rows),
                                                 "total": len(rows)},
                    "channel": channel, "lang": lang, "last_error": s["last_error"]}

    @app.post("/api/cases/{cid:path}/approve")
    def approve(cid: str, body: Approval):
        with lock:
            w = waiting_for(cid, "approval")
            if body.sha256 != w["sha256"]:
                raise HTTPException(409, "The text changed since you saw it. Look again before approving.")
            return run(lambda: s["agent"].approve(cid, body.approve, sha256=body.sha256))

    @app.post("/api/cases/{cid:path}/decide")
    def decide(cid: str, body: Decision):
        with lock:
            w = waiting_for(cid, "ca_decision")
            if body.sha256 != w["sha256"]:
                raise HTTPException(409, "The case changed since you saw it. Look again before deciding.")
            try:
                return s["agent"].decide(cid, body.choice, body.note, body.reason, body.not_applicable, body.sha256)
            except ValueError as e:
                raise HTTPException(422, str(e)) from None

    @app.post("/api/cases/{cid:path}/reply")
    def typed_reply(cid: str, body: Reply):
        with lock:
            waiting_for(cid, "reply")
            return run(lambda: s["agent"].answer(cid, body.text))

    @app.post("/api/cases/{cid:path}/day")
    def day(cid: str):
        with lock:
            waiting_for(cid, "event")
            return run(lambda: demo.day_passes(s["agent"], portal, cid))

    @app.post("/api/cases/{cid:path}/retry")
    def retry(cid: str):
        with lock:
            known(cid)
            if not s["agent"].stuck(cid):
                raise HTTPException(409, "Nothing failed on this case.")
            s["last_error"] = None
            return run(lambda: s["agent"].retry(cid))

    @app.get("/api/cases/{cid:path}")
    def one(cid: str):
        with lock:
            known(cid)
            v = s["agent"].view(cid)
            rules = [{"id": r, "title": (card := RULES.get(r, demo.TODAY)).title, "citations": card.citations}
                     for r in RULE_IDS[s["cases"][cid]["workflow"]]]
            return {**v, "facts": v["facts"] or s["cases"][cid]["facts"], "status": status(cid, v),
                    "voice_replies": s["voice"].get(cid, []), "rules": rules}

    @app.post("/api/reset")
    def reset_route():
        with lock:
            reset()
            return {"cases": len(s["cases"])}

    if DIST.is_dir():
        app.mount("/", StaticFiles(directory=DIST, html=True), name="page")
    return app


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--lang", choices=sorted(language.LANGUAGES), default="ta-IN", help="the shop's language")
    ap.add_argument("--channel", choices=["none", "telegram"], default="none")
    ap.add_argument("--live", action="store_true", help="the LLM translates and reads replies (key in .env)")
    ap.add_argument("--port", type=int, default=8000)
    a = ap.parse_args(argv)
    if a.channel == "telegram":
        for name in live.SETTINGS["telegram"]:
            telegram.setting(name)  # fail now, not on the first click
    uvicorn.run(make_app(a.lang, a.channel, a.live), port=a.port, log_level="warning")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
