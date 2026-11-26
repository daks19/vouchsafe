"""The one place that calls Claude. Every call asks for JSON that fits a schema.

Callers never put GSTIN or PAN into the text they send (spec §4 guardrails).
"""

from __future__ import annotations

import anthropic

MODEL = "claude-opus-5-5"


class LLMError(Exception):
    pass


class NoCredentials(LLMError):
    pass


def ask_json(content: list[dict], schema: dict, effort: str = "medium") -> str:
    """Send content blocks; return Claude's JSON text. Key from ANTHROPIC_API_KEY (or an `ant` profile)."""
    client = anthropic.Anthropic()
    try:
        msg = client.beta.messages.create(
            model=MODEL,
            max_tokens=16000,  # adaptive thinking is always on and counts against this
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            output_config={"effort": effort, "format": {"type": "json_schema", "schema": schema}},
            messages=[{"role": "user", "content": content}],
        )
    except TypeError as e:  # the SDK raises TypeError when it finds no key
        if "authentication" not in str(e):
            raise
        raise NoCredentials("no Claude credentials: export ANTHROPIC_API_KEY, or use --replay") from e
    if msg.stop_reason != "end_turn":
        raise LLMError(f"Claude stopped with {msg.stop_reason}; try again")
    return next(b.text for b in msg.content if b.type == "text")
