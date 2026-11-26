"""Understand the receiver's reply to "did this arrive?" (W1). Claude classifies; it never decides the outcome.

The reply can be in any Indian language or English, in any script (or typed in Latin letters), and code-mixed.
Only the question and reply text are sent, with any GSTIN or PAN masked first.
"""

from __future__ import annotations

import json

from gstagent.language import mask_ids
from gstagent.llm import LLMError, ask_json

ANSWERS = ("arrived", "still_coming", "never_ordered", "unclear")
MIN_CONFIDENCE = 0.6

SCHEMA = {
    "type": "object",
    "properties": {"answer": {"type": "string", "enum": list(ANSWERS)}, "confidence": {"type": "number"}},
    "required": ["answer", "confidence"],
    "additionalProperties": False,
}


def classify(question: str, reply: str) -> str:
    """Return one of ANSWERS. Low confidence counts as unclear, so the agent asks again."""
    question, reply = mask_ids(question)[0], mask_ids(reply)[0]
    text = ask_json([{"type": "text", "text": (
        "A small shop in India asked the person who receives goods this question:\n"
        f"{question}\n\nTheir reply. It may be in any Indian language or English, in any script or typed in "
        f"Latin letters, and may mix languages:\n{reply}\n\n"
        "Classify the reply. arrived = the goods came. still_coming = ordered but not here yet. "
        "never_ordered = the shop never ordered this. unclear = anything else, or you are not sure. "
        "confidence is from 0 to 1.")}], SCHEMA, effort="low")
    try:
        r = json.loads(text)
    except json.JSONDecodeError as e:
        raise LLMError(f"reply classification was not JSON: {e}") from e
    return r["answer"] if r.get("answer") in ANSWERS and r.get("confidence", 0) >= MIN_CONFIDENCE else "unclear"
