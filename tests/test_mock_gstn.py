from fastapi.testclient import TestClient

from gstagent import data
from gstagent.mock_gstn.app import app

client = TestClient(app)
PROFILE = data.load_json("profile.json")
Q = {"gstin": PROFILE["gstin"], "rtnprd": "102026"}


def setup_function():
    client.post("/mock-gstn/reset")


def test_every_response_is_labelled_simulated():
    r = client.get("/mock-gstn/gstr2b", params=Q)
    assert r.status_code == 200 and r.headers["X-Simulated"] == "true"
    assert "SIMULATED" in r.json()["_simulated"]


def test_supplier_files_gstr1a_adds_records_once():
    ctin = data.load_json("gstr1a_event.json")["ctin"]
    first = client.post("/mock-gstn/events/supplier-files-gstr1a", json={"ctin": ctin})
    assert first.status_code == 200 and first.json()["added"] == 2
    assert client.post("/mock-gstn/events/supplier-files-gstr1a", json={"ctin": ctin}).status_code == 404
    inv = [i for s in client.get("/mock-gstn/gstr2b", params=Q).json()["data"]["docdata"]["b2b"]
           if s["ctin"] == ctin for i in s["inv"]]
    assert len(inv) == 2


def test_ims_save_validates_with_rule_card():
    recs = client.get("/mock-gstn/ims", params=Q).json()["records"]
    crn = next(r for r in recs if r["doc_type"] == "CRN")
    ok = client.post("/mock-gstn/ims/save", json={**Q, "actions": [
        {"ctin": crn["ctin"], "inum": crn["inum"], "action": "PENDING"}]})
    assert ok.status_code == 200  # credit notes may be Pending from the Oct-2025 period
    assert client.get("/mock-gstn/ims", params=Q).json()["records"][recs.index(crn)]["action"] == "PENDING"


def test_reverse_charge_records_are_not_in_ims():
    from gstagent.mock_gstn.app import STATE
    first = STATE.gstr2b["data"]["docdata"]["b2b"][0]
    first["inv"][0]["rev"] = "Y"
    rcm_key = f"{first['ctin']}|{first['inv'][0]['inum']}"
    keys = {r["key"] for r in client.get("/mock-gstn/ims", params=Q).json()["records"]}
    assert rcm_key not in keys
    r = client.post("/mock-gstn/ims/save", json={**Q, "actions": [
        {"ctin": first["ctin"], "inum": first["inv"][0]["inum"], "action": "PENDING"}]})
    assert r.status_code == 422 and "not in IMS" in r.json()["detail"]["reason"]


def test_backdated_cancellation_shows_in_supplier_status():
    ctin = PROFILE["gstin"]  # any GSTIN works; the simulation does not check it exists
    assert client.get(f"/mock-gstn/suppliers/{ctin}").json()["status"] == "Active"
    client.post("/mock-gstn/events/supplier-cancelled", json={"ctin": ctin, "effective_from": "2026-07-01"})
    s = client.get(f"/mock-gstn/suppliers/{ctin}").json()
    assert s["status"] == "Cancelled" and s["effective_from"] == "2026-07-01"
    client.post("/mock-gstn/reset")
    assert client.get(f"/mock-gstn/suppliers/{ctin}").json()["status"] == "Active"
