"""Telegram, WhatsApp and Sarvam adapters, the webhook, and the agent sending through a channel. Offline: httpx is faked."""

import base64
import hashlib
import hmac
import json

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from gstagent import data
from gstagent.agent import cases, demo
from gstagent.agent.graph import Agent
from gstagent.channels import live, telegram, voice, whatsapp
from gstagent.matcher import reconcile
from gstagent.mock_gstn.app import app as mock_app

ENV = {"SARVAM_API_KEY": "s-key", "WHATSAPP_TOKEN": "w-tok", "WHATSAPP_PHONE_ID": "111",
       "WHATSAPP_DEMO_TO": "919800000001", "WHATSAPP_VERIFY_TOKEN": "vt", "WHATSAPP_APP_SECRET": "secret",
       "TELEGRAM_BOT_TOKEN": "123:tg-secret", "TELEGRAM_DEMO_CHAT": "4242"}


@pytest.fixture
def env(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)  # no real .env leaks in
    for k, v in ENV.items():
        monkeypatch.setenv(k, v)
    return monkeypatch


def fake(monkeypatch, replies):
    """Fake httpx.post/get: each call takes the next (status, json or bytes) reply and is recorded."""
    sent = []

    def call(method):
        def f(url, **kw):
            sent.append({"method": method, "url": url, **kw})
            status, body = replies.pop(0)
            req = httpx.Request(method, url)
            return (httpx.Response(status, content=body, request=req) if isinstance(body, bytes)
                    else httpx.Response(status, json=body, request=req))
        return f
    monkeypatch.setattr(httpx, "post", call("POST"))
    monkeypatch.setattr(httpx, "get", call("GET"))
    return sent


def test_speak_asks_sarvam_for_an_opus_voice_note(env):
    sent = fake(env, [(200, {"request_id": "r", "audios": [base64.b64encode(b"OGG").decode()]})])
    assert voice.speak("नमस्ते", "hi-IN") == b"OGG"
    s = sent[0]
    assert s["url"] == "https://api.sarvam.ai/text-to-speech" and s["headers"] == {"api-subscription-key": "s-key"}
    assert s["json"]["language_code"] == "hi-IN" and s["json"]["output_audio_codec"] == "opus"


def test_speak_refuses_without_credit_language_or_key(env):
    fake(env, [(402, {"error": {"code": "insufficient_quota_error"}})])
    with pytest.raises(voice.VoiceError, match="credit"):
        voice.speak("hi", "en-IN")
    with pytest.raises(voice.VoiceError, match="no Sarvam voice"):
        voice.speak("hi", "fr-FR")
    env.delenv("SARVAM_API_KEY")
    with pytest.raises(voice.VoiceError, match="SARVAM_API_KEY"):
        voice.speak("hi", "en-IN")


def test_transcribe_sends_the_voice_note_and_returns_text_and_language(env):
    sent = fake(env, [(200, {"request_id": "r", "transcript": "இல்லை சார்", "language_code": "ta-IN"})])
    assert voice.transcribe(b"OGG", "audio/ogg; codecs=opus") == ("இல்லை சார்", "ta-IN")
    s = sent[0]
    assert s["files"]["file"] == ("reply.ogg", b"OGG", "audio/ogg")
    assert s["data"]["model"] == voice.STT_MODEL and s["data"]["language_code"] == "unknown"


def test_messages_go_only_to_the_demo_phone(env):
    sent = fake(env, [(200, {"messages": [{"id": "wamid.1"}]}), (200, {"id": "media9"}),
                      (200, {"messages": [{"id": "wamid.2"}]})])
    assert whatsapp.send_text("hello") == "wamid.1"
    assert whatsapp.send_voice(b"OGG") == "wamid.2"
    text, upload, audio = sent
    assert text["url"] == "https://graph.facebook.com/v27.0/111/messages"
    assert text["headers"] == {"Authorization": "Bearer w-tok"}
    assert text["json"]["to"] == "919800000001" and text["json"]["text"] == {"body": "hello"}
    assert upload["url"].endswith("/111/media") and upload["files"]["file"][2] == "audio/ogg"
    assert audio["json"]["audio"] == {"id": "media9", "voice": True} and audio["json"]["to"] == "919800000001"


def test_download_follows_the_media_url(env):
    sent = fake(env, [(200, {"url": "https://lookaside.example/x", "mime_type": "audio/ogg; codecs=opus"}),
                      (200, b"OGG")])
    assert whatsapp.download("media9") == (b"OGG", "audio/ogg; codecs=opus")
    assert sent[1]["url"] == "https://lookaside.example/x" and sent[1]["headers"]["Authorization"] == "Bearer w-tok"


def payload(sender, *msgs):
    return {"object": "whatsapp_business_account", "entry": [{"changes": [{"value": {
        "contacts": [{"wa_id": sender}], "messages": [{"from": sender, "timestamp": "1795000000", **m}
                                                      for m in msgs]}}]}]}


def test_webhook_payload_gives_text_and_voice_and_skips_the_rest():
    p = payload("919800000001",
                {"id": "a", "type": "text", "text": {"body": "never ordered"}},
                {"id": "b", "type": "audio", "audio": {"id": "m1", "mime_type": "audio/ogg; codecs=opus", "voice": True}},
                {"id": "c", "type": "image", "image": {"id": "m2"}})
    assert whatsapp.messages(p) == [
        {"from": "919800000001", "id": "a", "type": "text", "text": "never ordered"},
        {"from": "919800000001", "id": "b", "type": "audio", "media_id": "m1", "mime": "audio/ogg; codecs=opus"}]


def test_webhook_checks_the_token_the_signature_and_the_sender(env):
    got = []
    app = FastAPI()
    app.include_router(whatsapp.router(got.append))
    c = TestClient(app)
    ok = c.get("/whatsapp/webhook", params={"hub.mode": "subscribe", "hub.verify_token": "vt", "hub.challenge": "42"})
    assert ok.status_code == 200 and ok.text == "42"
    assert c.get("/whatsapp/webhook", params={"hub.mode": "subscribe", "hub.verify_token": "no"}).status_code == 403

    def post(p, secret="secret"):
        body = json.dumps(p).encode()
        sig = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        return c.post("/whatsapp/webhook", content=body, headers={"X-Hub-Signature-256": sig,
                                                                  "Content-Type": "application/json"})
    msg = {"id": "a", "type": "text", "text": {"body": "hi"}}
    assert post(payload("919800000001", msg), secret="forged").status_code == 403 and not got
    assert post(payload("919999999999", msg)).status_code == 200 and not got  # not the demo phone
    assert post(payload("919800000001", msg)).status_code == 200 and got[0]["text"] == "hi"


def test_approved_w1_question_goes_out_on_the_channel_with_a_voice_note():
    portal = TestClient(mock_app)
    portal.post("/mock-gstn/reset")
    books, recs = data.load_books(), data.portal_records_from_2b(data.load_json("gstr2b_102026.json"))
    c = next(c for c in cases.from_matches(reconcile(books, recs, demo.RULES, cases.period_start("102026")),
                                           books, recs, "102026") if c["workflow"] == "W1")
    sent = []
    a = Agent(portal, classify=lambda q, r: "never_ordered", today=demo.TODAY, translate=demo.offline_translate,
              deliver=lambda item: sent.append(item) or "WhatsApp test")
    a.open(c)
    assert not sent  # nothing goes out before the owner approves
    v = a.approve(c["case_id"])
    assert len(sent) == 1 and sent[0]["voice"] is True and sent[0]["text"] == v["outbox"][0]["text"]
    assert v["timeline"][-1]["summary"].endswith("(WhatsApp test)")


def test_live_voice_failure_still_sends_the_text(env):
    calls = []
    env.setattr(whatsapp, "send_text", lambda t: calls.append(("text", t)))
    env.setattr(voice, "speak", lambda t, lang: (_ for _ in ()).throw(voice.VoiceError("credit used up")))
    how = live.deliver({"text": "Did it arrive?", "lang": "hi-IN", "voice": True}, whatsapp)
    assert calls == [("text", "Did it arrive?")] and how.startswith("WhatsApp") and "voice note failed" in how


def test_live_turns_a_voice_reply_into_text(env):
    env.setattr(whatsapp, "download", lambda mid: (b"OGG", "audio/ogg"))
    env.setattr(voice, "transcribe", lambda audio, mime: ("नहीं, ऑर्डर नहीं दिया", "hi-IN"))
    assert live.heard({"type": "audio", "media_id": "m1", "mime": "audio/ogg"}, whatsapp) == "नहीं, ऑर्डर नहीं दिया"
    assert live.heard({"type": "text", "text": "never ordered"}) == "never ordered"


TG = "https://api.telegram.org/bot123:tg-secret"


def test_telegram_sends_only_to_the_demo_chat_and_hides_the_token(env):
    sent = fake(env, [(200, {"ok": True, "result": {"message_id": 1}}),
                      (200, {"ok": True, "result": {"message_id": 2}}),
                      (401, {"ok": False, "description": "Unauthorized"})])
    assert telegram.send_text("hello") == 1 and telegram.send_voice(b"OGG") == 2
    text, voice_note = sent[:2]
    assert text["url"] == f"{TG}/sendMessage" and text["json"] == {"chat_id": "4242", "text": "hello"}
    assert voice_note["url"] == f"{TG}/sendVoice" and voice_note["data"] == {"chat_id": "4242"}
    assert voice_note["files"]["voice"] == ("message.ogg", b"OGG", "audio/ogg")
    with pytest.raises(telegram.TelegramError, match="Unauthorized") as e:
        telegram.send_text("x")
    assert "tg-secret" not in str(e.value)


def test_telegram_network_error_does_not_leak_the_token(env):
    def boom(url, **kw):
        raise httpx.ConnectError(f"cannot reach {url}")
    env.setattr(httpx, "post", boom)
    with pytest.raises(telegram.TelegramError) as e:
        telegram.send_text("x")
    assert "tg-secret" not in str(e.value)


def update(uid, chat, **msg):
    return {"update_id": uid, "message": {"message_id": uid, "chat": {"id": chat}, **msg}}


def test_telegram_updates_give_text_and_voice_and_skip_the_rest():
    ups = [update(1, 4242, text="never ordered"),
           update(2, 4242, voice={"file_id": "f1", "mime_type": "audio/ogg", "duration": 2}),
           update(3, 4242, photo=[{"file_id": "p"}]), {"update_id": 4, "edited_message": {}}]
    assert telegram.messages(ups) == [
        {"from": "4242", "id": "1", "type": "text", "text": "never ordered"},
        {"from": "4242", "id": "2", "type": "audio", "media_id": "f1", "mime": "audio/ogg"}]


def test_telegram_download_follows_the_file_path(env):
    sent = fake(env, [(200, {"ok": True, "result": {"file_path": "voice/file_9.oga"}}), (200, b"OGG")])
    assert telegram.download("f1") == (b"OGG", "audio/ogg")
    assert sent[1]["url"] == "https://api.telegram.org/file/bot123:tg-secret/voice/file_9.oga"


def test_telegram_poll_skips_old_messages_and_other_chats(env):
    class Done(Exception):
        pass
    sent = fake(env, [(200, {"ok": True, "result": [update(5, 4242, text="old hi")]}),
                      (200, {"ok": True, "result": [update(6, 999, text="stranger"), update(7, 4242, text="arrived")]})])
    got = []

    def on_message(m):
        got.append(m)
        raise Done
    with pytest.raises(Done):
        telegram.poll(on_message)
    assert sent[1]["json"]["offset"] == 6 and [m["text"] for m in got] == ["arrived"]


def test_live_deliver_on_telegram_sends_text_then_voice(env):
    calls = []
    env.setattr(telegram, "send_text", lambda t: calls.append("text"))
    env.setattr(telegram, "send_voice", lambda a: calls.append(("voice", a)))
    env.setattr(voice, "speak", lambda t, lang: b"OGG")
    assert live.deliver({"text": "Aaya?", "lang": "hi-IN", "voice": True}) == "Telegram text and voice note to the demo chat"
    assert calls == ["text", ("voice", b"OGG")]
