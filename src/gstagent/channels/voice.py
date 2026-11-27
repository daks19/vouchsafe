"""Voice through Sarvam: text -> voice note (TTS), voice note -> text (STT). Key: SARVAM_API_KEY in .env.

API shapes from docs.sarvam.ai (api-reference-docs, checked 2026-11-27). ₹100 free credit on signup; STT is
about ₹0.49 a minute and TTS ₹3 per 1,000 characters (bulbul:v3).
"""

from __future__ import annotations

import base64
import os

import httpx

from gstagent.llm import load_dotenv

API = "https://api.sarvam.ai"
STT_MODEL, TTS_MODEL = "saaras:v4", "bulbul:v3"
TTS_LANGS = {"bn-IN", "en-IN", "gu-IN", "hi-IN", "kn-IN", "ml-IN", "mr-IN", "od-IN", "pa-IN", "ta-IN", "te-IN"}
MAX_CHARS = 2500  # per TTS request
TIMEOUT = 60


class VoiceError(Exception):
    pass


def _key() -> str:
    load_dotenv()
    k = os.environ.get("SARVAM_API_KEY")
    if not k:
        raise VoiceError("no Sarvam key: put SARVAM_API_KEY=... in .env (dashboard.sarvam.ai)")
    return k


def _check(r: httpx.Response) -> dict:
    if r.status_code == 402:
        raise VoiceError("Sarvam credit used up (HTTP 402)")
    if r.status_code != 200:
        raise VoiceError(f"Sarvam HTTP {r.status_code}: {r.text[:200]}")
    return r.json()


def speak(text: str, lang: str) -> bytes:
    """Ogg/Opus audio, the format WhatsApp plays as a voice note."""
    if lang not in TTS_LANGS:
        raise VoiceError(f"no Sarvam voice for {lang}")
    if len(text) > MAX_CHARS:
        raise VoiceError(f"message too long to speak ({len(text)} > {MAX_CHARS} characters)")
    r = httpx.post(f"{API}/text-to-speech", headers={"api-subscription-key": _key()}, timeout=TIMEOUT,
                   json={"text": text, "language_code": lang, "model": TTS_MODEL,
                         "output_audio_codec": "opus", "speech_sample_rate": 16000})  # opus needs 8/16/24/48 kHz
    return base64.b64decode(_check(r)["audios"][0])


def transcribe(audio: bytes, mime: str = "audio/ogg") -> tuple[str, str | None]:
    """A voice reply in any Indian language -> (transcript, detected language code)."""
    r = httpx.post(f"{API}/speech-to-text", headers={"api-subscription-key": _key()}, timeout=TIMEOUT,
                   files={"file": ("reply.ogg", audio, mime.split(";")[0])},
                   data={"model": STT_MODEL, "mode": "transcribe", "language_code": "unknown"})
    out = _check(r)
    return out["transcript"], out.get("language_code")
