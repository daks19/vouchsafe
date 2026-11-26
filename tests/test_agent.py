"""Agent loop (LangGraph): W1, W2, W3 on the mock portal, approvals, restarts. Offline: replies are classified by stubs."""

import json
import re

import pytest
from fastapi.testclient import TestClient

from gstagent import data, language
from gstagent.agent import cases, demo, reply
from gstagent.agent.graph import Agent, _draft
from gstagent.matcher import reconcile
from gstagent.mock_gstn.app import app as mock_app

OUTWARD = {"shop.asked", "supplier.messaged", "ca.handoff", "ims.pending_saved"}


@pytest.fixture
def portal():
    p = TestClient(mock_app)
    p.post("/mock-gstn/reset")
    yield p
    p.post("/mock-gstn/reset")


def agent(portal, answer="never_ordered", db=":memory:", translate=demo.offline_translate):
    return Agent(portal, db=db, classify=lambda q, r: answer, today=demo.TODAY, translate=translate)


def w1_case():
    books = data.load_books()
    recs = data.portal_records_from_2b(data.load_json("gstr2b_102026.json"))
    todo = cases.from_matches(reconcile(books, recs, demo.RULES, cases.period_start("102026")), books, recs, "102026")
    return next(c for c in todo if c["workflow"] == "W1")


def strip(view):  # outcome and audit trail without times; snapshot hashes include the time taken, so mask them
    return view["outcome"], [(e["kind"], re.sub(r"snapshot [0-9a-f]{12}", "snapshot <hash>", e["summary"]))
                             for e in view["timeline"]]


# --- the milestone: three workflows, end to end, twice in a row ------------------------------------

def test_all_three_workflows_run_end_to_end_twice_in_a_row(portal):
    first = demo.run(agent(portal), portal)
    second = demo.run(agent(portal), portal)
    assert {k: strip(v) for k, v in first.items()} == {k: strip(v) for k, v in second.items()}
    out = {k: v["outcome"] for k, v in first.items()}
    assert out["W1:29CHCFC7955B1Z0|CP/7781"].startswith("Handed to the CA")
    assert out["W2:B029"].startswith("Supplier fixed it") and out["W2:B030"].startswith("Supplier fixed it")
    assert out["W2:B031"].startswith("Handed to the CA") and out["W2:B032"].startswith("Handed to the CA")
    assert out["W3:29CHCFC7955B1Z0"].startswith("Handed to the CA")
    assert all(v["waiting"] is None for v in first.values())


def test_every_outward_action_comes_right_after_an_owner_approval(portal):
    for v in demo.run(agent(portal), portal).values():
        kinds = [e["kind"] for e in v["timeline"]]
        for i, k in enumerate(kinds):
            if k in OUTWARD:
                assert kinds[i - 1] == "owner.approved", (v["case_id"], kinds)


def test_w2_gstr1a_case_explains_credit_lands_next_period(portal):
    v = demo.run(agent(portal), portal)["W2:B029"]
    assert "GSTR-2B for Nov 2026" in v["outcome"]
    assert "GSTR-1A" in v["outbox"][0]["text"] and "29KEMPR1791C1ZW" in v["outbox"][0]["text"]


def test_w3_lists_exposed_bills_with_snapshots_and_evidence(portal):
    v = demo.run(agent(portal), portal)["W3:29CHCFC7955B1Z0"]
    pack = next(e["summary"] for e in v["timeline"] if e["kind"] == "ca.handoff")
    assert "3 bills" in pack and "₹16,047" in pack and "1 of 7 documents" in pack and "not binding" in pack
    assert len(v["snapshots"]) == 3 and all(len(s["sha256"]) == 64 for s in v["snapshots"])


def test_w3_active_supplier_closes_without_a_pack(portal):
    v = agent(portal).open(cases.cancellation("29CHCFC7955B1Z0", "102026"))
    assert v["waiting"] is None and "active" in v["outcome"]


# --- W1 branches ---------------------------------------------------------------------------------

def to_reply(a, c):
    a.open(c)
    return a.approve(c["case_id"])


def test_w1_still_coming_marks_pending_in_ims(portal):
    a, c = agent(portal, "still_coming"), w1_case()
    to_reply(a, c)
    v = a.answer(c["case_id"], "innu barbeku")
    assert v["waiting"]["action"] == "ims_pending"
    v = a.approve(c["case_id"])
    assert v["outcome"].startswith("Marked Pending")
    ims = portal.get("/mock-gstn/ims", params={"gstin": data.load_profile().gstin, "rtnprd": "102026"}).json()
    assert next(r for r in ims["records"] if r["inum"] == "CP/7781")["action"] == "PENDING"


def test_w1_arrived_asks_for_the_bill(portal):
    a, c = agent(portal, "arrived"), w1_case()
    to_reply(a, c)
    a.answer(c["case_id"], "bantu")
    v = a.approve(c["case_id"])
    assert "bill photo requested" in v["outcome"] and "photo of the bill" in v["outbox"][-1]["text"]


def test_w1_unclear_twice_goes_to_the_ca(portal):
    a, c = agent(portal, "unclear"), w1_case()
    to_reply(a, c)
    v = a.answer(c["case_id"], "hmm")
    assert v["waiting"]["action"] == "message"   # asks again
    a.approve(c["case_id"])
    v = a.answer(c["case_id"], "hmm")
    assert v["waiting"]["action"] == "ca_handoff"


# --- approvals and memory ------------------------------------------------------------------------

def test_owner_decline_sends_nothing(portal):
    a, c = agent(portal), w1_case()
    a.open(c)
    v = a.approve(c["case_id"], yes=False)
    assert v["outbox"] == [] and v["outcome"].startswith("Owner declined")


def test_approval_must_carry_the_hash_of_the_text_shown(portal):
    a, c = agent(portal), w1_case()
    a.open(c)
    v = a.answer(c["case_id"], {"approve": True, "sha256": "0" * 64})
    assert v["outbox"] == [] and v["outcome"].startswith("Owner declined")


def test_case_survives_a_restart(portal, tmp_path):
    db = str(tmp_path / "cases.sqlite")
    a, c = agent(portal, db=db), w1_case()
    to_reply(a, c)
    a.close()
    b = agent(portal, db=db)                      # a new process, days later
    assert b.view(c["case_id"])["waiting"]["type"] == "reply"
    assert b.answer(c["case_id"], "illa")["waiting"]["action"] == "ca_handoff"


def test_opening_the_same_case_twice_does_nothing(portal):
    a, c = agent(portal), w1_case()
    a.open(c)
    assert len(a.open(c)["timeline"]) == 1


def test_number_guard_blocks_a_figure_the_case_did_not_compute():
    s = {"facts": {"supplier": "X", "value": "100"}}
    _draft(s, "message", "Manju", "X for ₹100", then="send")
    with pytest.raises(ValueError, match="number guard"):
        _draft(s, "message", "Manju", "X for ₹150", then="send")


# --- reply understanding -------------------------------------------------------------------------

def test_reply_low_confidence_is_unclear_and_prompt_has_no_ids(monkeypatch):
    sent = []

    def fake(content, schema, effort="medium"):
        sent.append(content[0]["text"])
        return json.dumps({"answer": "never_ordered", "confidence": confidence})

    monkeypatch.setattr(reply, "ask_json", fake)
    confidence = 0.9
    assert reply.classify("Did CP/7781 arrive?", "illa") == "never_ordered"
    confidence = 0.3
    assert reply.classify("Did CP/7781 arrive?", "illa") == "unclear"
    assert not any(re.search(r"\d{2}[A-Z]{5}\d{4}[A-Z]", t) for t in sent)


# --- languages -----------------------------------------------------------------------------------

def fake_hindi(text, lang):  # keeps every figure, as the real translation must
    return "हिंदी: " + text


def test_messages_go_out_in_the_recipients_language(portal):
    first = demo.run(agent(portal, translate=fake_hindi), portal, shop_lang="ta-IN")
    langs = {v["case_id"]: v["outbox"][0]["lang"] for v in first.values() if v["outbox"]}
    assert langs["W1:29CHCFC7955B1Z0|CP/7781"] == "ta-IN"                   # the shop's language
    assert langs["W2:B029"] == "hi-IN" and langs["W2:B032"] == "te-IN"      # each supplier's own
    assert langs["W2:B031"] == "en-IN"
    m = first["W2:B029"]["outbox"][0]
    assert m["text"].startswith("हिंदी") and m["text_en"].startswith("Hello") and m["note"] is None


def test_owner_sees_both_texts_and_approval_binds_both(portal):
    a, c = agent(portal, translate=fake_hindi), w1_case()
    c["facts"]["lang"] = "hi-IN"
    w = a.open(c)["waiting"]
    assert w["lang"] == "hi-IN" and w["text"].startswith("हिंदी") and w["text_en"] and w["sha256"]


def test_a_translation_that_changes_a_number_is_not_sent(portal):
    a, c = agent(portal, translate=lambda t, lang: t.replace("73,160", "37,160")), w1_case()
    c["facts"]["lang"] = "hi-IN"
    w = a.open(c)["waiting"]
    assert w["lang"] == "en-IN" and "changed a number" in w["note"] and "73,160" in w["text"]


@pytest.mark.parametrize("lang", sorted(language.LANGUAGES))
def test_w1_runs_in_every_supported_language(portal, lang):
    a, c = Agent(portal, classify=lambda q, r: demo.SCRIPTED.get(r, "unclear"), today=demo.TODAY,
                 translate=fake_hindi), w1_case()
    c["facts"]["lang"] = lang
    v = demo.drive(a, portal, a.open(c)["case_id"], lang)
    assert v["outcome"].startswith("Handed to the CA") and demo.REPLIES[lang] in v["timeline"][3]["summary"]


def test_demo_has_a_reply_for_every_supported_language():
    assert set(demo.REPLIES) == set(language.LANGUAGES)


def test_translation_never_sees_a_gstin_or_pan(monkeypatch):
    sent = []

    def fake(content, schema, effort="medium"):
        sent.append(content[0]["text"])
        return json.dumps({"text": "अनुवाद " + content[0]["text"].split("\n\n", 1)[1]})

    monkeypatch.setattr(language, "ask_json", fake)
    out = language.translate("GSTIN 29KEMPR1791C1ZW, PAN KEMPR1791C, invoice BE/6074", "hi-IN")
    assert "29KEMPR1791C1ZW" in out and "KEMPR1791C" in out
    assert not any("KEMPR1791C" in t for t in sent)
    assert language.translate("same", "en-IN") == "same"


def test_translation_that_drops_an_id_is_refused(monkeypatch):
    monkeypatch.setattr(language, "ask_json", lambda c, s, effort="medium": json.dumps({"text": "no id here"}))
    with pytest.raises(language.LLMError):
        language.translate("GSTIN 29KEMPR1791C1ZW", "ta-IN")
