"""Languages: every message a person reads goes out in that person's language.

Codes follow Sarvam's (`hi-IN`, `od-IN`, ...) so the voice channel can use them as they are. Claude can
translate other languages too; this list is the set we support, test and demo.
"""

from __future__ import annotations

import json
import re

from gstagent.llm import LLMError, ask_json

LANGUAGES = {
    "en-IN": "English", "hi-IN": "Hindi", "bn-IN": "Bengali", "te-IN": "Telugu", "mr-IN": "Marathi",
    "ta-IN": "Tamil", "gu-IN": "Gujarati", "kn-IN": "Kannada", "ml-IN": "Malayalam", "od-IN": "Odia",
    "pa-IN": "Punjabi",
}

# Usual language by GSTIN state code; a person's own choice (profile, supplier record) always wins.
STATE_LANGUAGE = {
    "02": "hi-IN", "03": "pa-IN", "04": "hi-IN", "05": "hi-IN", "06": "hi-IN", "07": "hi-IN", "08": "hi-IN",
    "09": "hi-IN", "10": "hi-IN", "19": "bn-IN", "20": "hi-IN", "21": "od-IN", "22": "hi-IN", "23": "hi-IN",
    "24": "gu-IN", "27": "mr-IN", "29": "kn-IN", "32": "ml-IN", "33": "ta-IN", "36": "te-IN", "37": "te-IN",
}

_IDS = re.compile(r"\b\d{2}[A-Z]{5}\d{4}[A-Z][1-9A-Z][A-Z0-9][0-9A-Z]\b|\b[A-Z]{5}\d{4}[A-Z]\b")  # GSTIN, PAN

SCHEMA = {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"],
          "additionalProperties": False}


def mask_ids(text: str) -> tuple[str, dict[str, str]]:
    """Replace each GSTIN/PAN with a token, so no ID reaches the LLM (spec §4)."""
    ids: dict[str, str] = {}

    def sub(m: re.Match) -> str:
        token = next((t for t, v in ids.items() if v == m.group()), f"[[ID{len(ids) + 1}]]")
        ids[token] = m.group()
        return token
    return _IDS.sub(sub, text), ids


def unmask(text: str, ids: dict[str, str]) -> str:
    for token, value in ids.items():
        text = text.replace(token, value)
    return text


def translate(text: str, lang: str) -> str:
    """English draft -> the recipient's language. The caller re-checks numbers with the guard."""
    if lang == "en-IN":
        return text
    masked, ids = mask_ids(text)
    out = ask_json([{"type": "text", "text": (
        f"Translate this message into {LANGUAGES.get(lang, lang)} for a small business in India. Use plain, polite, "
        "everyday words a shopkeeper would use; keep English trade words people say anyway (bill, invoice, GST). "
        "Keep every number, ₹ amount, date, invoice number, form name (GSTR-2B, GSTR-1A, GSTR-1, IFF, IMS) and every "
        "[[ID..]] token exactly as written, in Western digits.\n\n" + masked)}], SCHEMA, effort="low")
    try:
        result = json.loads(out)["text"]
    except (json.JSONDecodeError, KeyError) as e:
        raise LLMError(f"translation was not in the expected shape: {e}") from e
    if any(t not in result for t in ids):
        raise LLMError("translation dropped a GSTIN/PAN placeholder")
    return unmask(result, ids)
