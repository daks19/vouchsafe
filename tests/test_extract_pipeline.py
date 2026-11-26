"""Bill photo -> Claude fields -> validators -> matcher -> CA queue, offline (Claude replies replayed from fixtures)."""

import json
import re
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from gstagent import ca_queue, data, extract
from gstagent.ca_queue import process
from gstagent.extract import BillRead, ExtractionError, read_bill
from gstagent.rules import RuleBook
from gstagent.validate import image_hash, validate

BILLS = Path(__file__).parent / "fixtures" / "bills"
RULES = RuleBook.load()
PROFILE = data.load_profile()


def png(name: str) -> bytes:
    return (BILLS / f"{name}.png").read_bytes()


def reply(name: str, **changes) -> dict:
    r = json.loads((BILLS / f"{name}.reply.json").read_text())
    for k, v in changes.items():
        r[k] = v if isinstance(v, dict) else {"value": v, "confidence": 0.95}
    return r


def replay(r: dict):
    return lambda *_: json.dumps(r)


def check(r: dict):
    read = read_bill(b"img", "image/png", replay(r))
    return validate(read, image_hash(b"img"), "IMG-test", PROFILE, RULES)


# --- extraction ------------------------------------------------------------------------------------

def test_schema_model_and_fields_agree():
    assert set(BillRead.model_fields) == set(extract.FIELDS) == set(extract.SCHEMA["required"])
    assert extract.SCHEMA["additionalProperties"] is False


def test_prompt_carries_no_gstin_or_pan():
    assert not re.search(r"\d{2}[A-Z]{5}\d{4}[A-Z]|[A-Z]{5}\d{4}[A-Z]", extract.PROMPT)


def test_read_bill_replays_recorded_reply():
    read = read_bill(png("nandi_missing_in_2b"), "image/png", replay(reply("nandi_missing_in_2b")))
    assert read.invoice_no.value == "NH/2291" and read.supplier_gstin.value == "29SMBPN4622B1ZW"
    assert all(0 <= r.confidence <= 1 for r in read.__dict__.values())


def test_reply_outside_schema_is_refused():
    with pytest.raises(ExtractionError):
        read_bill(b"img", "image/png", lambda *_: '{"invoice_no": "X"}')
    with pytest.raises(ExtractionError):
        read_bill(b"img", "image/png", lambda *_: "not json")


# --- validators ------------------------------------------------------------------------------------

def test_clean_bill_passes_every_check():
    c = check(reply("nandi_missing_in_2b"))
    assert c.resnap == [] and c.bill.taxable_value == Decimal("14500.00") and c.bill.image_hash


def test_null_field_blocks_and_asks_for_resnap():
    c = check(reply("nandi_missing_in_2b", taxable_value={"value": None, "confidence": 0.2}))
    assert c.bill is None and c.resnap[0].kind == "resnap" and "taxable_value" in c.resnap[0].detail["reason"]


def test_low_confidence_field_blocks():
    c = check(reply("nandi_missing_in_2b", invoice_no={"value": "NH/2291", "confidence": 0.4}))
    assert c.bill is None and "invoice_no" in c.resnap[0].detail["reason"]


def test_tax_not_matching_rate_blocks():
    c = check(reply("nandi_missing_in_2b", cgst="1350.00", sgst="1350.00", total="17200.00"))
    assert c.bill is None and [t.detail["check"] for t in c.resnap] == ["arithmetic"]
    assert "18% of ₹14,500 is ₹2,610" in c.resnap[0].detail["reason"]


def test_total_not_matching_blocks():
    c = check(reply("nandi_missing_in_2b", total="17010.00"))
    assert c.bill is None and "Total" in c.resnap[0].detail["reason"]


def test_wrong_split_cites_rule_card():
    c = check(reply("kaveri_wrong_split"))
    t = c.resnap[0]
    assert c.bill is None and t.detail["rule"] == "gst.tax_split@1"
    assert any("IGST Act 2017 s.8(1)" in x for x in t.detail["citations"])


def test_unreadable_gstin_asks_for_resnap_but_still_matches():
    c = check(reply("nandi_missing_in_2b", supplier_gstin="29SMBPN4622B1Z9"))
    assert c.bill is not None and [t.detail["check"] for t in c.resnap] == ["gstin"]


def test_ocr_z_slip_in_gstin_is_repaired_silently():
    c = check(reply("nandi_missing_in_2b", supplier_gstin="29SMBPN4622B12W"))
    assert c.bill is not None and c.resnap == []


# --- pipeline and CA queue -------------------------------------------------------------------------

def run(name: str, **changes):
    return process(png(name), "image/png", replay(reply(name, **changes)))


def test_bill_missing_in_2b_reaches_ca_queue_with_cited_rule():
    r = run("nandi_missing_in_2b")
    [q] = r.queue
    assert q.issue == "Supplier has not reported this bill" and q.rule == "itc.supplier_reported@2"
    assert q.itc_at_risk == Decimal("2610.00") and q.citations and "supplier" in q.recommended_action


def test_bill_matching_2b_leaves_queue_empty():
    r = run("chamundi_matches_2b")
    assert r.bill.invoice_no == "CP/7781" and r.queue == []


def test_wrong_split_never_reaches_matcher():
    r = run("kaveri_wrong_split")
    assert r.bill is None and [q.issue for q in r.queue] == ["Photo needs a re-snap"]


def test_post_reform_12_percent_flags_rate_review():
    r = run("nandi_missing_in_2b", rate="12", cgst="870.00", sgst="870.00", total="16240.00")
    assert {q.rule for q in r.queue} == {"itc.supplier_reported@2", "gst.rate_check@2"}


def test_bill_already_in_books_is_a_duplicate():
    b = data.load_books()[0]
    r = run("nandi_missing_in_2b", supplier_name=b.supplier_name, supplier_gstin=b.supplier_gstin_raw,
            invoice_no=b.invoice_no, invoice_date=b.invoice_date.isoformat(), taxable_value=str(b.taxable_value),
            cgst=str(b.cgst), sgst=str(b.sgst), total=str(b.taxable_value + b.tax))
    assert [q.issue for q in r.queue] == ["Same bill sent twice"]


def test_cli_prints_the_exception(capsys):
    rc = ca_queue.main([str(BILLS / "nandi_missing_in_2b.png"), "--replay", str(BILLS / "nandi_missing_in_2b.reply.json")])
    out = capsys.readouterr().out
    assert rc == 0 and "itc.supplier_reported@2" in out and "ITC at risk: ₹2,610" in out


# --- API -------------------------------------------------------------------------------------------

@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(ca_queue, "CALL", replay(reply("nandi_missing_in_2b")))
    c = TestClient(ca_queue.app)
    c.post("/ca-queue/reset")
    return c


def test_api_returns_queue_and_is_labelled_simulated(client):
    r = client.post("/ca-queue/bills", content=png("nandi_missing_in_2b"), headers={"content-type": "image/png"})
    assert r.status_code == 200 and r.headers["X-Simulated"] == "true" and "SIMULATED" in r.json()["_simulated"]
    [q] = r.json()["queue"]
    assert q["rule"] == "itc.supplier_reported@2" and q["recommended_action"]
    assert len(client.get("/ca-queue").json()["items"]) == 1


def test_api_same_photo_twice_is_counted_once(client):
    img = png("nandi_missing_in_2b")
    client.post("/ca-queue/bills", content=img, headers={"content-type": "image/png"})
    second = client.post("/ca-queue/bills", content=img, headers={"content-type": "image/png"}).json()
    assert [q["issue"] for q in second["queue"]] == ["Same bill sent twice"]


def test_api_refuses_non_images(client):
    assert client.post("/ca-queue/bills", content=b"hi", headers={"content-type": "text/plain"}).status_code == 415
