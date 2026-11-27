"""The one place that calls an LLM. Every call asks for JSON that fits a schema.

Pick the provider in `.env` (git-ignored) or the shell:

    LLM_PROVIDER=gemini   GEMINI_API_KEY=...      # default; free tier (Google may use free-tier data for training)
    LLM_PROVIDER=groq     GROQ_API_KEY=...        # free tier, rate-limited
    LLM_PROVIDER=claude   ANTHROPIC_API_KEY=...   # paid
    LLM_MODEL=...                                  # optional: override the provider's default model

When Gemini is busy or out of free quota, Groq is tried (and the other way round) if its key is set too.

Callers pass Claude-style content blocks (text, base64 image); each provider's adapter converts them.
Callers never put GSTIN or PAN into the text they send (spec §4 guardrails).
"""

from __future__ import annotations

import os
from pathlib import Path

import anthropic
import httpx

PROVIDERS = ("gemini", "groq", "claude")
MODEL = "claude-opus-5-5"
GEMINI_MODELS = ("gemini-3.8-flash", "gemini-3.6-flash", "gemini-3.5-flash-lite")  # free tier; the next one is tried when one is busy
GROQ_TEXT_MODEL, GROQ_VISION_MODEL = "openai/gpt-oss-120b", "qwen/qwen3.8-27b"
FALLBACK = {"gemini": "groq", "groq": "gemini"}  # used when the main one is busy and its key is set
KEYS = {"gemini": "GEMINI_API_KEY", "groq": "GROQ_API_KEY", "claude": "ANTHROPIC_API_KEY"}
TIMEOUT = 120


class LLMError(Exception):
    pass


class NoCredentials(LLMError):
    pass


class Busy(LLMError):
    """Rate limit, overload or timeout: worth trying another model or again later."""


def _load_dotenv(path: Path = Path(".env")) -> None:
    """KEY=VALUE lines from a git-ignored .env; the shell environment wins."""
    if path.is_file():
        for line in path.read_text().splitlines():
            k, sep, v = line.partition("=")
            v = v.split(" #")[0].strip().strip("\"'")  # drop an inline comment
            if sep and v and not k.strip().startswith("#"):
                os.environ.setdefault(k.strip(), v)


def provider() -> str:
    _load_dotenv()
    p = os.environ.get("LLM_PROVIDER", "gemini").strip().lower()
    if p not in PROVIDERS:
        raise LLMError(f"LLM_PROVIDER={p!r}; use one of {', '.join(PROVIDERS)}")
    return p


def ask_json(content: list[dict], schema: dict, effort: str = "medium") -> str:
    """Send content blocks; return the model's JSON text."""
    p = provider()
    if p == "claude":
        return _claude(content, schema, effort)
    key = os.environ.get(KEYS[p])
    if not key:
        raise NoCredentials(f"no {p} key: put {KEYS[p]}=... in .env (or set LLM_PROVIDER), or use --replay")
    model = os.environ.get("LLM_MODEL") or None
    backup = FALLBACK.get(p)
    try:
        return _call(p, content, schema, key, model)
    except Busy:
        if not (backup and os.environ.get(KEYS[backup])):
            raise
    return _call(backup, content, schema, os.environ[KEYS[backup]], None)  # LLM_MODEL names the main provider's model


def _call(p: str, content: list[dict], schema: dict, key: str, model: str | None) -> str:
    try:
        return (_gemini if p == "gemini" else _groq)(content, schema, key, model)
    except httpx.HTTPError as e:
        raise LLMError(f"could not reach {p}: {e}") from e


def _post(url: str, headers: dict, body: dict) -> dict:
    try:
        r = httpx.post(url, headers=headers, json=body, timeout=TIMEOUT)
    except httpx.TimeoutException as e:
        raise Busy(f"timed out: {e}") from e
    if r.status_code in (401, 403):
        raise NoCredentials(f"key refused ({r.status_code}): check it in .env")
    if r.status_code in (429, 500, 503):
        raise Busy(f"the AI service is busy or rate-limited (HTTP {r.status_code}); try again later")
    if r.status_code != 200:
        raise LLMError(f"HTTP {r.status_code}: {r.text[:300]}")
    return r.json()


def _gemini(content: list[dict], schema: dict, key: str, model: str | None = None) -> str:
    """Interactions API (aistudio.google.com/api-reference, checked 2026-11-26)."""
    parts = [{"type": "text", "text": b["text"]} if b["type"] == "text"
             else {"type": "image", "data": b["source"]["data"], "mime_type": b["source"]["media_type"]}
             for b in content]
    models = [model] if model else list(GEMINI_MODELS)
    for i, model in enumerate(models):
        try:
            out = _post("https://generativelanguage.googleapis.com/v1beta/interactions",
                        {"x-goog-api-key": key},
                        {"model": model, "input": parts, "store": False,
                         "response_format": {"type": "text", "mime_type": "application/json", "schema": schema}})
            break
        except Busy:
            if i == len(models) - 1:
                raise
    if out.get("status") != "completed":
        raise LLMError(f"Gemini stopped with status {out.get('status')!r}; try again")
    texts = [c["text"] for s in out.get("steps", []) if s.get("type") == "model_output"
             for c in s.get("content", []) if c.get("type") == "text"]
    if not texts:
        raise LLMError("Gemini returned no text")
    return texts[-1]


def _groq(content: list[dict], schema: dict, key: str, model: str | None = None) -> str:
    """OpenAI-style chat completions with strict JSON schema (console.groq.com/docs, checked 2026-11-26)."""
    images = any(b["type"] == "image" for b in content)
    blocks = [{"type": "text", "text": b["text"]} if b["type"] == "text"
              else {"type": "image_url", "image_url": {"url": f"data:{b['source']['media_type']};base64,"
                                                              f"{b['source']['data']}"}}
              for b in content]
    model = model or (GROQ_VISION_MODEL if images else GROQ_TEXT_MODEL)
    out = _post("https://api.groq.com/openai/v1/chat/completions", {"Authorization": f"Bearer {key}"},
                {"model": model, "messages": [{"role": "user", "content": blocks}],
                 "response_format": {"type": "json_schema",
                                     "json_schema": {"name": "reply", "strict": True, "schema": schema}}})
    choice = out["choices"][0]
    if choice.get("finish_reason") != "stop":
        raise LLMError(f"Groq stopped with {choice.get('finish_reason')}; try again")
    return choice["message"]["content"]


def _claude(content: list[dict], schema: dict, effort: str) -> str:
    client = anthropic.Anthropic()
    try:
        msg = client.beta.messages.create(
            model=os.environ.get("LLM_MODEL", MODEL),
            max_tokens=16000,  # adaptive thinking is always on and counts against this
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            output_config={"effort": effort, "format": {"type": "json_schema", "schema": schema}},
            messages=[{"role": "user", "content": content}],
        )
    except TypeError as e:  # the SDK raises TypeError when it finds no key
        if "authentication" not in str(e):
            raise
        raise NoCredentials("no Claude credentials: put ANTHROPIC_API_KEY=... in .env, or use --replay") from e
    if msg.stop_reason != "end_turn":
        raise LLMError(f"Claude stopped with {msg.stop_reason}; try again")
    return next(b.text for b in msg.content if b.type == "text")
