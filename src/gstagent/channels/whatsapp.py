"""WhatsApp Cloud API: send text and voice notes, receive replies on a webhook. Settings in .env:

    WHATSAPP_TOKEN=...          # Meta app dashboard -> WhatsApp -> API Setup (temporary or system-user token)
    WHATSAPP_PHONE_ID=...       # the test number's "Phone number ID"
    WHATSAPP_DEMO_TO=91...      # the one phone every message goes to in the prototype (a verified test recipient)
    WHATSAPP_VERIFY_TOKEN=...   # any string; type the same one in the dashboard's webhook setup
    WHATSAPP_APP_SECRET=...     # App settings -> Basic; checks that webhook calls really come from Meta

Prototype rule: every message goes to WHATSAPP_DEMO_TO, never to a real supplier or shop; the intended
recipient is only logged. WhatsApp allows free-form messages only within 24 hours of that phone's last
message, so send "hi" from the demo phone first. API shapes from developers.facebook.com (v27.0, 2026-11-27).
"""

from __future__ import annotations

import hashlib
import hmac
import os
from typing import Callable

import httpx
from fastapi import APIRouter, HTTPException, Request, Response

from gstagent.llm import load_dotenv

GRAPH = "https://graph.facebook.com/v27.0"
TIMEOUT = 30


class WhatsAppError(Exception):
    pass


def setting(name: str) -> str:
    load_dotenv()
    v = os.environ.get(name)
    if not v:
        raise WhatsAppError(f"put {name}=... in .env (see gstagent/channels/whatsapp.py)")
    return v


def _auth() -> dict:
    return {"Authorization": f"Bearer {setting('WHATSAPP_TOKEN')}"}


def _ok(r: httpx.Response) -> dict:
    if r.status_code != 200:
        raise WhatsAppError(f"WhatsApp HTTP {r.status_code}: {r.text[:300]}")
    return r.json()


def _send(body: dict) -> str:
    r = httpx.post(f"{GRAPH}/{setting('WHATSAPP_PHONE_ID')}/messages", headers=_auth(), timeout=TIMEOUT,
                   json={"messaging_product": "whatsapp", "recipient_type": "individual",
                         "to": setting("WHATSAPP_DEMO_TO"), **body})
    return _ok(r)["messages"][0]["id"]


def send_text(text: str) -> str:
    return _send({"type": "text", "text": {"body": text}})


def send_voice(ogg_opus: bytes) -> str:
    r = httpx.post(f"{GRAPH}/{setting('WHATSAPP_PHONE_ID')}/media", headers=_auth(), timeout=TIMEOUT,
                   data={"messaging_product": "whatsapp", "type": "audio/ogg"},
                   files={"file": ("message.ogg", ogg_opus, "audio/ogg")})
    return _send({"type": "audio", "audio": {"id": _ok(r)["id"], "voice": True}})


def download(media_id: str) -> tuple[bytes, str]:
    meta = _ok(httpx.get(f"{GRAPH}/{media_id}", headers=_auth(), timeout=TIMEOUT))
    r = httpx.get(meta["url"], headers=_auth(), timeout=TIMEOUT)  # the url lasts 5 minutes
    if r.status_code != 200:
        raise WhatsAppError(f"media download HTTP {r.status_code}")
    return r.content, meta.get("mime_type", "audio/ogg")


def messages(payload: dict) -> list[dict]:
    """Incoming text and voice messages from a webhook call: {from, id, type, text | media_id, mime}."""
    out = []
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            for m in change.get("value", {}).get("messages", []):
                item = {"from": m.get("from"), "id": m.get("id"), "type": m.get("type")}
                if m.get("type") == "text":
                    item["text"] = m["text"]["body"]
                elif m.get("type") == "audio":
                    item.update(media_id=m["audio"]["id"], mime=m["audio"].get("mime_type", "audio/ogg"))
                else:
                    continue  # photos, buttons etc. are not handled yet
                out.append(item)
    return out


def signed(body: bytes, header: str | None) -> bool:
    want = "sha256=" + hmac.new(setting("WHATSAPP_APP_SECRET").encode(), body, hashlib.sha256).hexdigest()
    return bool(header) and hmac.compare_digest(want, header)


def router(on_message: Callable[[dict], None]) -> APIRouter:
    """GET: Meta's one-time webhook check. POST: each incoming message from the demo phone, to on_message."""
    r = APIRouter()

    @r.get("/whatsapp/webhook")
    def verify(request: Request) -> Response:
        q = request.query_params
        if q.get("hub.mode") == "subscribe" and q.get("hub.verify_token") == setting("WHATSAPP_VERIFY_TOKEN"):
            return Response(q.get("hub.challenge", ""), media_type="text/plain")
        raise HTTPException(403, "verify token does not match")

    @r.post("/whatsapp/webhook")
    async def receive(request: Request) -> dict:
        body = await request.body()
        if not signed(body, request.headers.get("X-Hub-Signature-256")):
            raise HTTPException(403, "bad signature")
        demo = setting("WHATSAPP_DEMO_TO").lstrip("+")
        for m in messages(await request.json()):
            if m["from"] == demo:  # anyone else is ignored in the prototype
                on_message(m)
        return {"ok": True}

    return r
