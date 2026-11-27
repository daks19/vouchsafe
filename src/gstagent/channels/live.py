"""W1 on real WhatsApp: the owner approves in this terminal, the question goes to the demo phone as text plus a
voice note, and the spoken or typed reply comes back through the webhook.

    uv run python -m gstagent.channels.live --lang ta-IN

Needs WHATSAPP_* (see whatsapp.py), SARVAM_API_KEY and an LLM key in .env, and a public HTTPS address for the
webhook, e.g. `cloudflared tunnel --url http://localhost:8000`; put <that address>/whatsapp/webhook in the Meta
dashboard. Send "hi" from the demo phone first (WhatsApp's 24-hour rule). Portal and data are SIMULATED.
"""

from __future__ import annotations

import argparse
import queue
import sys
import threading

import uvicorn
from fastapi import FastAPI
from fastapi.testclient import TestClient

from gstagent import data, language
from gstagent.agent import cases
from gstagent.agent.demo import PERIOD, TODAY
from gstagent.agent.graph import RULES, Agent
from gstagent.channels import voice, whatsapp
from gstagent.llm import LLMError
from gstagent.matcher import reconcile
from gstagent.mock_gstn.app import app as mock_app


def deliver(item: dict) -> str:
    """Text always; a voice note too when asked for. A failed voice note still leaves the text sent."""
    whatsapp.send_text(item["text"])
    if not item.get("voice"):
        return "WhatsApp text to the demo phone"
    try:
        whatsapp.send_voice(voice.speak(item["text"], item["lang"]))
    except (voice.VoiceError, whatsapp.WhatsAppError) as e:
        return f"WhatsApp text to the demo phone; voice note failed: {e}"
    return "WhatsApp text and voice note to the demo phone"


def heard(m: dict) -> str:
    """The reply as text: typed, or a voice note turned into text."""
    if m["type"] == "text":
        return m["text"]
    audio, mime = whatsapp.download(m["media_id"])
    return voice.transcribe(audio, mime)[0]


def inbox(port: int) -> queue.Queue:
    """Start the webhook server in the background; incoming messages land on the queue (each once)."""
    q: queue.Queue = queue.Queue()
    seen: set[str] = set()

    def on_message(m: dict) -> None:
        if m["id"] not in seen:  # Meta retries a webhook it thinks failed
            seen.add(m["id"])
            q.put(m)
    app = FastAPI()
    app.include_router(whatsapp.router(on_message))
    server = uvicorn.Server(uvicorn.Config(app, port=port, log_level="warning"))
    threading.Thread(target=server.run, daemon=True).start()
    return q


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--lang", choices=sorted(language.LANGUAGES), default="hi-IN", help="the shop's language")
    ap.add_argument("--port", type=int, default=8000)
    a = ap.parse_args(argv)
    for name in ("WHATSAPP_TOKEN", "WHATSAPP_PHONE_ID", "WHATSAPP_DEMO_TO", "WHATSAPP_VERIFY_TOKEN",
                 "WHATSAPP_APP_SECRET"):
        whatsapp.setting(name)  # fail now, not halfway through
    q = inbox(a.port)
    portal = TestClient(mock_app)
    portal.post("/mock-gstn/reset")
    books, records = data.load_books(), data.portal_records_from_2b(data.load_json("gstr2b_102026.json"))
    todo = cases.from_matches(reconcile(books, records, RULES, cases.period_start(PERIOD)), books, records, PERIOD,
                              a.lang)
    case = next(c for c in todo if c["workflow"] == "W1")
    agent = Agent(portal, today=TODAY, deliver=deliver)
    print(f"[SIMULATED portal and data; REAL WhatsApp to the demo phone]  webhook on :{a.port}/whatsapp/webhook")
    v = agent.open(case)
    while v["waiting"]:
        w = v["waiting"]
        if w["type"] == "approval":
            print(f"\nTo {w['to']} [{language.LANGUAGES[w['lang']]}]:\n  {w['text']}")
            if w.get("text_en") and w["text_en"] != w["text"]:
                print(f"  (English: {w['text_en']})")
            if w.get("note"):
                print(f"  ({w['note']})")
            v = agent.approve(case["case_id"], input("Approve? [y/N] ").strip().lower() == "y")
        elif w["type"] == "reply":
            print("\nWaiting for the reply on WhatsApp (Ctrl-C to stop)...")
            text = heard(q.get())
            print(f"  heard: {text}")
            v = agent.answer(case["case_id"], text)
        else:
            break
    print(f"\n=== {case['case_id']} -> {v['outcome']}")
    for e in v["timeline"]:
        print(f"  {e['kind']:<18} {e['summary'].splitlines()[0][:110]}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (whatsapp.WhatsAppError, voice.VoiceError, LLMError) as e:
        print(f"error: {e}", file=sys.stderr)
        sys.exit(2)
