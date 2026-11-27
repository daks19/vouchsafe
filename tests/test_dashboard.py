"""CA dashboard API over the live agent. Offline: simulated channel, scripted reply reading, no translation."""

import pytest
from fastapi.testclient import TestClient

from gstagent import dashboard
from gstagent.agent import demo
from gstagent.channels import live, voice
from gstagent.mock_gstn.app import app as mock_app

W1 = "W1:29CHCFC7955B1Z0|CP/7781"
TAMIL = demo.REPLIES["ta-IN"]


@pytest.fixture
def client():
    TestClient(mock_app).post("/mock-gstn/reset")
    yield TestClient(dashboard.make_app(lang="ta-IN"))
    TestClient(mock_app).post("/mock-gstn/reset")


def case(c, cid):
    return c.get(f"/api/cases/{cid}").json()


def approve(c, cid, yes=True):
    return c.post(f"/api/cases/{cid}/approve", json={"approve": yes, "sha256": case(c, cid)["waiting"]["sha256"]})


def decide(c, cid, choice, reason=""):
    w = case(c, cid)["waiting"]
    return c.post(f"/api/cases/{cid}/decide", json={"choice": choice, "note": "", "reason": reason,
                                                     "not_applicable": [], "sha256": w["sha256"]})


def to_ca(c):
    approve(c, W1)
    c.post(f"/api/cases/{W1}/reply", json={"text": TAMIL})
    approve(c, W1)
    return case(c, W1)["waiting"]


def statuses(c):
    return {x["case_id"]: x["status"] for x in c.get("/api/cases").json()["cases"]}


def test_lists_every_case_with_status_and_readiness(client):
    r = client.get("/api/cases")
    body = r.json()
    assert r.headers["X-Simulated"] == "true" and len(body["cases"]) == 6
    assert body["readiness"] == {"resolved": 0, "total": 6}
    assert set(statuses(client).values()) == {"waiting_approval"}
    assert body["channel"] == "none" and body["lang"] == "ta-IN" and body["last_error"] is None
    assert next(x for x in body["cases"] if x["case_id"] == W1)["title"] == "Chamundi Packaging CP/7781"


def test_stage_path_from_question_to_ca_decision(client):
    assert approve(client, W1).status_code == 200
    assert statuses(client)[W1] == "waiting_reply"
    assert client.post(f"/api/cases/{W1}/reply", json={"text": TAMIL}).status_code == 200
    assert approve(client, W1).status_code == 200
    w = case(client, W1)["waiting"]
    assert w["type"] == "ca_decision" and statuses(client)[W1] == "waiting_ca"
    r = decide(client, W1, "pending")
    assert r.status_code == 200 and r.json()["outcome"] == "The CA kept it Pending in IMS (SIMULATED)."
    assert statuses(client)[W1] == "resolved"
    assert client.get("/api/cases").json()["readiness"] == {"resolved": 1, "total": 6}


def test_double_click_and_stale_hash_get_409_and_send_nothing(client):
    sha = case(client, W1)["waiting"]["sha256"]
    assert client.post(f"/api/cases/{W1}/approve", json={"approve": True, "sha256": sha}).status_code == 200
    r = client.post(f"/api/cases/{W1}/approve", json={"approve": True, "sha256": sha})
    assert r.status_code == 409 and len(case(client, W1)["outbox"]) == 1
    w = to_ca_from_reply(client)
    stale = {"choice": "pending", "note": "", "reason": "", "not_applicable": [], "sha256": "0" * 64}
    assert client.post(f"/api/cases/{W1}/decide", json=stale).status_code == 409
    assert case(client, W1)["waiting"] == w


def to_ca_from_reply(c):
    c.post(f"/api/cases/{W1}/reply", json={"text": TAMIL})
    approve(c, W1)
    return case(c, W1)["waiting"]


def test_closed_without_reason_is_422(client):
    to_ca(client)
    r = decide(client, W1, "closed")
    assert r.status_code == 422 and "reason" in r.json()["detail"]
    assert decide(client, W1, "closed", reason="Duplicate").json()["outcome"] == "Closed by the CA: Duplicate"


def test_reply_and_day_in_the_wrong_state_are_409(client):
    assert client.post(f"/api/cases/{W1}/reply", json={"text": TAMIL}).status_code == 409
    assert client.post(f"/api/cases/{W1}/day").status_code == 409
    assert decide(client, W1, "pending").status_code == 409


def test_unknown_case_is_404_also_after_reset(client):
    assert client.get("/api/cases/W9:nope").status_code == 404
    assert client.post("/api/cases/W9:nope/approve", json={"approve": True, "sha256": "x"}).status_code == 404
    approve(client, W1)
    assert client.post("/api/reset").status_code == 200
    assert statuses(client)[W1] == "waiting_approval" and case(client, W1)["outbox"] == []


def test_case_detail_has_facts_and_cited_rules(client):
    d = case(client, W1)
    assert d["facts"]["invoice_no"] == "CP/7781" and d["rules"][0]["id"] == "ims.treatment"
    assert d["rules"][0]["title"] and d["rules"][0]["citations"] and d["voice_replies"] == []


def test_day_passes_lets_a_supplier_fix_it(client):
    approve(client, "W2:B029")
    assert statuses(client)["W2:B029"] == "waiting_supplier"
    r = client.post("/api/cases/W2:B029/day")
    assert r.status_code == 200 and r.json()["outcome"].startswith("Supplier fixed it")
    assert statuses(client)["W2:B029"] == "resolved"


def test_declined_case_is_not_ready(client):
    approve(client, W1, yes=False)
    assert statuses(client)[W1] == "declined"
    assert client.get("/api/cases").json()["readiness"]["resolved"] == 0


def test_telegram_reply_goes_to_the_waiting_case(client):
    approve(client, W1)
    client.app.state.on_message({"from": "4242", "id": "1", "type": "text", "text": TAMIL})
    assert case(client, W1)["waiting"]["action"] == "ca_handoff"
    assert case(client, W1)["voice_replies"] == []


def test_telegram_voice_reply_is_tagged(client, monkeypatch):
    monkeypatch.setattr(live, "heard", lambda m, ch=None: TAMIL)
    approve(client, W1)
    client.app.state.on_message({"from": "4242", "id": "2", "type": "audio", "media_id": "f1", "mime": "audio/ogg"})
    assert case(client, W1)["voice_replies"] == [TAMIL]


def test_telegram_message_with_no_case_waiting_is_ignored(client):
    client.app.state.on_message({"from": "4242", "id": "3", "type": "text", "text": "hello"})
    assert set(statuses(client).values()) == {"waiting_approval"}


def test_failed_voice_note_keeps_the_case_waiting(client, monkeypatch):
    def broken(m, ch=None):
        raise voice.VoiceError("Sarvam HTTP 503")
    monkeypatch.setattr(live, "heard", broken)
    approve(client, W1)
    client.app.state.on_message({"from": "4242", "id": "4", "type": "audio", "media_id": "f2", "mime": "audio/ogg"})
    assert statuses(client)[W1] == "waiting_reply"
    assert "Sarvam HTTP 503" in client.get("/api/cases").json()["last_error"]


def test_only_shop_messages_go_to_telegram():
    sent = []
    send = dashboard.shop_only(lambda item: sent.append(item) or "Telegram text to the demo chat")
    assert send({"voice": False, "text": "to a supplier"}) == "simulated channel (one phone on stage)"
    assert send({"voice": True, "text": "to the shop"}) == "Telegram text to the demo chat"
    assert [i["text"] for i in sent] == ["to the shop"]


def test_clients_show_the_demo_shop_and_greyed_samples(client):
    rows = client.get("/api/clients").json()
    assert rows[0]["active"] is True and all(not r["active"] for r in rows[1:]) and len(rows) == 3


def test_llm_busy_while_reading_a_reply_can_be_retried():
    from gstagent.llm import LLMError
    busy = {"on": True}

    def classify(q, r):
        if busy["on"]:
            raise LLMError("gemini busy (503)")
        return "never_ordered"
    TestClient(mock_app).post("/mock-gstn/reset")
    c = TestClient(dashboard.make_app(classify=classify))
    approve(c, W1)
    r = c.post(f"/api/cases/{W1}/reply", json={"text": TAMIL})
    assert r.status_code == 502 and "busy" in r.json()["detail"] and statuses(c)[W1] == "needs_retry"
    busy["on"] = False
    assert c.post(f"/api/cases/{W1}/retry").json()["waiting"]["action"] == "ca_handoff"
    assert c.post(f"/api/cases/{W1}/retry").status_code == 409  # nothing failed now


def test_any_failure_reading_a_telegram_reply_keeps_the_listener_alive(client, monkeypatch):
    def boom(m, ch=None):
        raise RuntimeError("unexpected")
    monkeypatch.setattr(live, "heard", boom)
    approve(client, W1)
    client.app.state.on_message({"from": "4242", "id": "5", "type": "audio", "media_id": "f3", "mime": "audio/ogg"})
    assert statuses(client)[W1] == "waiting_reply"
    assert "unexpected" in client.get("/api/cases").json()["last_error"]


def test_the_page_stays_responsive_while_a_voice_note_is_transcribed(client, monkeypatch):
    import threading

    def slow_heard(m, ch=None):  # the page polls while Sarvam is working; it must not wait for the lock
        assert client.get("/api/cases").status_code == 200
        return TAMIL
    monkeypatch.setattr(live, "heard", slow_heard)
    approve(client, W1)
    t = threading.Thread(target=client.app.state.on_message,
                         args=({"from": "4242", "id": "6", "type": "audio", "media_id": "f4", "mime": "audio/ogg"},))
    t.start()
    t.join(timeout=10)
    assert not t.is_alive() and case(client, W1)["voice_replies"] == [TAMIL]


def test_an_old_error_clears_once_a_reply_gets_through(client, monkeypatch):
    def broken(m, ch=None):  # the voice note fails; the typed reply after it gets through
        if m["type"] == "audio":
            raise voice.VoiceError("Sarvam HTTP 503")
        return m["text"]
    monkeypatch.setattr(live, "heard", broken)
    approve(client, W1)
    client.app.state.on_message({"from": "4242", "id": "7", "type": "audio", "media_id": "f5", "mime": "audio/ogg"})
    client.app.state.on_message({"from": "4242", "id": "8", "type": "text", "text": TAMIL})
    assert client.get("/api/cases").json()["last_error"] is None


def test_a_channel_failure_is_a_plain_502_not_a_crash():
    from gstagent.channels import telegram

    def classify(q, r):
        raise telegram.TelegramError("Telegram sendMessage: ConnectError")
    TestClient(mock_app).post("/mock-gstn/reset")
    c = TestClient(dashboard.make_app(classify=classify), raise_server_exceptions=False)
    approve(c, W1)
    r = c.post(f"/api/cases/{W1}/reply", json={"text": TAMIL})
    assert r.status_code == 502 and "Telegram" in r.json()["detail"] and statuses(c)[W1] == "needs_retry"
