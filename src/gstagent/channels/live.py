"""W1 on a real messaging app: the owner approves in this terminal, the question goes to the demo chat as text
plus a voice note, and the spoken or typed reply comes back.

    uv run python -m gstagent.channels.live --lang ta-IN                      # Telegram (default)
    uv run python -m gstagent.channels.live --lang ta-IN --channel whatsapp

Needs SARVAM_API_KEY and an LLM key in .env, plus the channel's settings:
- Telegram: TELEGRAM_* (see telegram.py). No public address needed.
- WhatsApp: WHATSAPP_* (see whatsapp.py) and a public HTTPS address for the webhook, e.g.
  `cloudflared tunnel --url http://localhost:8000`; put <that address>/whatsapp/webhook in the Meta dashboard.
  Send "hi" from the demo phone first (WhatsApp's 24-hour rule).
Portal and data are SIMULATED.
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
from gstagent.channels import telegram, voice, whatsapp
from gstagent.llm import LLMError
from gstagent.matcher import reconcile
from gstagent.mock_gstn.app import app as mock_app


CHANNELS = {"telegram": telegram, "whatsapp": whatsapp}
SETTINGS = {"telegram": ("TELEGRAM_BOT_TOKEN", "TELEGRAM_DEMO_CHAT"),
            "whatsapp": ("WHATSAPP_TOKEN", "WHATSAPP_PHONE_ID", "WHATSAPP_DEMO_TO", "WHATSAPP_VERIFY_TOKEN",
                         "WHATSAPP_APP_SECRET")}
ERRORS = (telegram.TelegramError, whatsapp.WhatsAppError, voice.VoiceError, LLMError)


def deliver(item: dict, ch=telegram) -> str:
    """Text always; a voice note too when asked for. A failed voice note still leaves the text sent."""
    name = "WhatsApp" if ch is whatsapp else "Telegram"
    ch.send_text(item["text"])
    if not item.get("voice"):
        return f"{name} text to the demo chat"
    try:
        ch.send_voice(voice.speak(item["text"], item["lang"]))
    except ERRORS as e:
        return f"{name} text to the demo chat; voice note failed: {e}"
    return f"{name} text and voice note to the demo chat"


def heard(m: dict, ch=telegram) -> str:
    """The reply as text: typed, or a voice note turned into text."""
    if m["type"] == "text":
        return m["text"]
    audio, mime = ch.download(m["media_id"])
    return voice.transcribe(audio, mime)[0]


def inbox(channel: str, port: int) -> queue.Queue:
    """Start listening in the background; incoming messages land on the queue (each once)."""
    q: queue.Queue = queue.Queue()
    seen: set[str] = set()

    def on_message(m: dict) -> None:
        if m["id"] not in seen:  # Meta retries a webhook it thinks failed
            seen.add(m["id"])
            q.put(m)
    if channel == "telegram":
        run = lambda: telegram.poll(on_message)  # noqa: E731
    else:
        app = FastAPI()
        app.include_router(whatsapp.router(on_message))
        run = uvicorn.Server(uvicorn.Config(app, port=port, log_level="warning")).run
    threading.Thread(target=run, daemon=True).start()
    return q


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--lang", choices=sorted(language.LANGUAGES), default="hi-IN", help="the shop's language")
    ap.add_argument("--channel", choices=sorted(CHANNELS), default="telegram")
    ap.add_argument("--port", type=int, default=8000, help="WhatsApp webhook port")
    a = ap.parse_args(argv)
    ch = CHANNELS[a.channel]
    for name in SETTINGS[a.channel]:
        ch.setting(name)  # fail now, not halfway through
    q = inbox(a.channel, a.port)
    portal = TestClient(mock_app)
    portal.post("/mock-gstn/reset")
    books, records = data.load_books(), data.portal_records_from_2b(data.load_json("gstr2b_102026.json"))
    todo = cases.from_matches(reconcile(books, records, RULES, cases.period_start(PERIOD)), books, records, PERIOD,
                              a.lang)
    case = next(c for c in todo if c["workflow"] == "W1")
    agent = Agent(portal, today=TODAY, deliver=lambda item: deliver(item, ch))
    where = f"webhook on :{a.port}/whatsapp/webhook" if a.channel == "whatsapp" else "polling Telegram"
    print(f"[SIMULATED portal and data; REAL {a.channel} messages to the demo chat]  {where}")
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
            print(f"\nWaiting for the reply on {a.channel} (Ctrl-C to stop)...")
            text = heard(q.get(), ch)
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
    except ERRORS as e:
        print(f"error: {e}", file=sys.stderr)
        sys.exit(2)
