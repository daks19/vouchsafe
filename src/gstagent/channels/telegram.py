"""Telegram bot: send text and voice notes, read replies by long polling (no public address needed). In .env:

    TELEGRAM_BOT_TOKEN=...     # from @BotFather (/newbot)
    TELEGRAM_DEMO_CHAT=...     # the one chat every message goes to; send /start to the bot, then run
                               #   uv run python -m gstagent.channels.telegram   to print your chat id

The prototype's live channel while WhatsApp waits for Meta business verification. Same message shapes as
whatsapp.py, so live.py drives either. Prototype rule: every message goes to TELEGRAM_DEMO_CHAT only, and only
messages from that chat are read. API shapes from core.telegram.org/bots/api (2026-11-27).
"""

from __future__ import annotations

import os
import time
from typing import Callable

import httpx

from gstagent.llm import load_dotenv

API = "https://api.telegram.org"
POLL_SECONDS = 30
TIMEOUT = POLL_SECONDS + 10


class TelegramError(Exception):
    pass


def setting(name: str) -> str:
    load_dotenv()
    v = os.environ.get(name)
    if not v:
        raise TelegramError(f"put {name}=... in .env (see gstagent/channels/telegram.py)")
    return v


def _call(method: str, files: dict | None = None, **params) -> dict | list:
    try:  # the token is in the URL: never let an httpx error print it
        r = httpx.post(f"{API}/bot{setting('TELEGRAM_BOT_TOKEN')}/{method}", timeout=TIMEOUT,
                       **({"data": params, "files": files} if files else {"json": params}))
    except httpx.HTTPError as e:
        raise TelegramError(f"Telegram {method}: {type(e).__name__}") from None
    out = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
    if r.status_code != 200 or not out.get("ok"):
        raise TelegramError(f"Telegram {method} HTTP {r.status_code}: {out.get('description', r.text[:200])}")
    return out["result"]


def send_text(text: str) -> int:
    return _call("sendMessage", chat_id=setting("TELEGRAM_DEMO_CHAT"), text=text)["message_id"]


def send_voice(ogg_opus: bytes) -> int:
    """Ogg/Opus shows as a voice note."""
    return _call("sendVoice", files={"voice": ("message.ogg", ogg_opus, "audio/ogg")},
                 chat_id=setting("TELEGRAM_DEMO_CHAT"))["message_id"]


def download(file_id: str) -> tuple[bytes, str]:
    path = _call("getFile", file_id=file_id)["file_path"]
    try:
        r = httpx.get(f"{API}/file/bot{setting('TELEGRAM_BOT_TOKEN')}/{path}", timeout=TIMEOUT)
    except httpx.HTTPError as e:
        raise TelegramError(f"Telegram file download: {type(e).__name__}") from None
    if r.status_code != 200:
        raise TelegramError(f"Telegram file download HTTP {r.status_code}")
    return r.content, "audio/ogg"


def messages(updates: list[dict]) -> list[dict]:
    """Text and voice messages from getUpdates: {from, id, type, text | media_id, mime}, like whatsapp.messages."""
    out = []
    for u in updates:
        m = u.get("message") or {}
        item = {"from": str(m.get("chat", {}).get("id")), "id": str(u["update_id"])}
        if "text" in m:
            item.update(type="text", text=m["text"])
        elif "voice" in m:
            item.update(type="audio", media_id=m["voice"]["file_id"], mime=m["voice"].get("mime_type", "audio/ogg"))
        else:
            continue  # photos, stickers etc. are not handled yet
        out.append(item)
    return out


def poll(on_message: Callable[[dict], None]) -> None:
    """Forever: each new message from the demo chat goes to on_message. Messages sent before start are skipped."""
    demo = setting("TELEGRAM_DEMO_CHAT")
    old = _call("getUpdates", timeout=0)
    offset = old[-1]["update_id"] + 1 if old else 0
    while True:
        try:
            updates = _call("getUpdates", offset=offset, timeout=POLL_SECONDS, allowed_updates=["message"])
        except TelegramError:
            time.sleep(3)  # network blip: try again
            continue
        if updates:
            offset = updates[-1]["update_id"] + 1
        for m in messages(updates):
            if m["from"] == demo:  # anyone else is ignored in the prototype
                on_message(m)


if __name__ == "__main__":  # setup helper: print who has messaged the bot
    for u in _call("getUpdates", timeout=0):
        c = (u.get("message") or {}).get("chat", {})
        if c:
            print(f"chat id {c['id']}  ({c.get('first_name') or c.get('title', '')})")
