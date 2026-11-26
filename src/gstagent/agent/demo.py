"""Run W1, W2 and W3 end to end on the mock portal, approving each pause the way the owner would.

    uv run python -m gstagent.agent.demo                 # offline: in-process mock portal, scripted reply reading
    uv run python -m gstagent.agent.demo --lang ta-IN    # the shop speaks Tamil (any code in gstagent.language)
    uv run python -m gstagent.agent.demo --live          # the LLM translates and reads replies (key in .env, see llm.py)

Offline, messages are shown in English with a note; --live sends each one in the recipient's language.

Every portal call, message and reply here is SIMULATED; the data is fictional.
"""

from __future__ import annotations

import argparse
import sys
from datetime import date

import httpx
from fastapi.testclient import TestClient

from gstagent import data, language
from gstagent.agent import cases, reply
from gstagent.agent.graph import RULES, Agent
from gstagent.language import LANGUAGES
from gstagent.llm import LLMError
from gstagent.matcher import reconcile
from gstagent.mock_gstn.app import app as mock_app

TODAY = date(2026, 11, 26)
PERIOD = "102026"
FILES_GSTR1A = "29BTGPB9133V1ZT"               # Bharath Electricals files GSTR-1A when chased
CANCELLED = ("29CHCFC7955B1Z0", "2026-07-01")  # Chamundi Packaging cancelled from July, backdated
# "No, we never placed this order", as the person at the shop might reply. Demo text: have a native speaker check.
REPLIES = {
    "en-IN": "No, we never ordered this.",
    "hi-IN": "नहीं भैया, यह ऑर्डर हमने दिया ही नहीं था।",
    "bn-IN": "না দাদা, এই অর্ডারটা আমরা দিইনি।",
    "te-IN": "లేదు సార్, ఆ ఆర్డర్ మేము ఇవ్వనే లేదు.",
    "mr-IN": "नाही साहेब, ही ऑर्डर आम्ही दिलीच नव्हती.",
    "ta-IN": "இல்லை சார், அந்த ஆர்டரை நாங்கள் கொடுக்கவே இல்லை.",
    "gu-IN": "ના ભાઈ, આ ઓર્ડર અમે આપ્યો જ નથી.",
    "kn-IN": "ಇಲ್ಲ ಸಾರ್, ಆ ಆರ್ಡರ್ ನಾವು ಕೊಟ್ಟೇ ಇಲ್ಲ",
    "ml-IN": "ഇല്ല സാർ, ആ ഓർഡർ ഞങ്ങൾ കൊടുത്തിട്ടില്ല.",
    "od-IN": "ନା ଭାଇ, ଏହି ଅର୍ଡର ଆମେ ଦେଇନାହୁଁ।",
    "pa-IN": "ਨਹੀਂ ਜੀ, ਇਹ ਆਰਡਰ ਅਸੀਂ ਦਿੱਤਾ ਹੀ ਨਹੀਂ ਸੀ।",
}
SCRIPTED = {r: "never_ordered" for r in REPLIES.values()}  # offline stand-in for Claude reading the reply


def offline_translate(text: str, lang: str) -> str:
    raise LLMError("offline run; --live sends it translated")


def drive(agent: Agent, portal: httpx.Client, case_id: str, shop_lang: str) -> dict:
    """Answer every pause until the case ends: approve each draft, send the reply, let days pass."""
    v = agent.view(case_id)
    while v["waiting"]:
        w = v["waiting"]
        if w["type"] == "approval":
            v = agent.approve(case_id)
        elif w["type"] == "reply":
            v = agent.answer(case_id, REPLIES[shop_lang])
        else:  # waiting for the supplier: one day passes; the chased supplier files on the first day
            if case_id in ("W2:B029", "W2:B030") and w["checks_done"] == 0:
                portal.post("/mock-gstn/events/supplier-files-gstr1a", json={"ctin": FILES_GSTR1A})
            v = agent.answer(case_id, {"type": "day_passed"})
    return v


def run(agent: Agent, portal: httpx.Client, shop_lang: str | None = None) -> dict[str, dict]:
    """The whole scenario, from a fresh portal. Returns each case's final view."""
    shop_lang = shop_lang or data.load_profile().preferred_language
    portal.post("/mock-gstn/reset")
    books = data.load_books()
    records = data.portal_records_from_2b(data.load_json("gstr2b_102026.json"))
    todo = cases.from_matches(reconcile(books, records, RULES, cases.period_start(PERIOD)), books, records, PERIOD,
                                shop_lang)
    portal.post("/mock-gstn/events/supplier-cancelled", json={"ctin": CANCELLED[0], "effective_from": CANCELLED[1]})
    todo.append(cases.cancellation(CANCELLED[0], PERIOD))
    out = {}
    for c in sorted(todo, key=lambda c: c["case_id"]):
        agent.open(c)
        out[c["case_id"]] = drive(agent, portal, c["case_id"], shop_lang)
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--lang", choices=sorted(LANGUAGES), help="the shop's language (default: the profile's)")
    ap.add_argument("--live", action="store_true", help="the LLM translates messages and reads the reply")
    a = ap.parse_args(argv)
    classify = reply.classify if a.live else (lambda q, r: SCRIPTED.get(r, "unclear"))
    portal = TestClient(mock_app)
    agent = Agent(portal, classify=classify, today=TODAY, translate=language.translate if a.live else offline_translate)
    try:
        results = run(agent, portal, a.lang)
    except LLMError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    print("[SIMULATED: mock GST portal, simulated WhatsApp channel, fictional data]")
    for cid, v in results.items():
        print(f"\n=== {cid}  ->  {v['outcome']}")
        for e in v["timeline"]:
            print(f"  {e['kind']:<18} {e['summary'].splitlines()[0][:110]}")
        for m in v["outbox"]:
            note = f"  ({m['note']})" if m.get("note") else ""
            print(f"  -> to {m['to']} [{LANGUAGES[m['lang']]}]{note}\n     {m['text'][:110]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
