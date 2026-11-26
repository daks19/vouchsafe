"""Synthetic data for one QRMP trader in Mysuru, tax period October 2026.

Everything here is fictional: names, GSTINs (checksum-valid but made up), phone
numbers (+91 90000 000xx placeholders) and amounts. Each scenario the demo needs
is seeded deliberately and recorded in expected_matches.json, so tests can check
the matcher finds it.

    uv run python -m gstagent.synth.generate --out data/synthetic --seed 7
"""

from __future__ import annotations

import argparse
import json
import random
import string
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

from gstagent import gstin
from gstagent.language import STATE_LANGUAGE

PERIOD = "102026"
BUYER_STATE = "29"
TWO = Decimal("0.01")

# name, state, PAN holder type letter, rate%
SUPPLIERS = [
    ("Sri Ganesh Traders", "29", "P", 18),
    ("Mysore Agro Supplies", "29", "F", 5),
    ("Chamundi Packaging", "29", "F", 18),
    ("Kaveri Plastics", "29", "C", 18),
    ("Nandi Hardware", "29", "P", 18),
    ("Sahyadri Seeds", "29", "F", 5),
    ("Malnad Spices", "29", "P", 5),
    ("Tumkur Steel Works", "29", "C", 18),
    ("Hassan Fertilisers", "29", "F", 5),
    ("Bharath Electricals", "29", "P", 18),
    ("Coimbatore Pumps", "33", "C", 18),
    ("Pune Agro Chem", "27", "C", 18),
    ("Kochi Coir Products", "32", "F", 5),
    ("Mandya Jaggery Traders", "29", "P", 5),
    ("Udupi Logistics", "29", "F", 18),
]


def _pan(rng: random.Random, holder: str, name: str) -> str:
    letters = "".join(rng.choice(string.ascii_uppercase) for _ in range(3))
    return f"{letters}{holder}{name[0].upper()}{rng.randint(1000, 9999)}{rng.choice(string.ascii_uppercase)}"


def _taxes(txval: Decimal, rate: Decimal, supplier_state: str) -> dict:
    if supplier_state == BUYER_STATE:
        half = (txval * rate / 200).quantize(TWO, ROUND_HALF_UP)
        return {"igst": Decimal("0"), "cgst": half, "sgst": half}
    return {"igst": (txval * rate / 100).quantize(TWO, ROUND_HALF_UP), "cgst": Decimal("0"), "sgst": Decimal("0")}


def _ddmmyyyy(d: date) -> str:
    return d.strftime("%d-%m-%Y")


def _j(x):
    if isinstance(x, Decimal):
        return str(x)
    if isinstance(x, (date, datetime)):
        return x.isoformat()
    raise TypeError(type(x))


# Suppliers choose their own language; many traders don't use their state's main one.
LANGUAGE_CHOICE = {"Bharath Electricals": "hi-IN", "Tumkur Steel Works": "te-IN", "Udupi Logistics": "en-IN",
                   "Sri Ganesh Traders": "ta-IN", "Mysore Agro Supplies": "hi-IN"}


def generate(seed: int = 7) -> dict:
    rng = random.Random(seed)

    buyer_pan = _pan(rng, "P", "Ramesh")
    profile = {
        "gstin": gstin.build(BUYER_STATE, buyer_pan),
        "legal_name": "Ramesh K (proprietor)",
        "trade_name": "Sri Lakshmi Agro Traders",
        "state_code": BUYER_STATE,
        "city": "Mysuru",
        "scheme": "regular_qrmp",
        "holder_type": "individual",
        "prior_year_turnover": "8000000",
        "income_kind": "business",
        "preferred_language": "kn-IN",
        "accountant_name": "CA Suresh (part-time accountant)",
        "phone": "+91 90000 00000",
    }

    suppliers = []
    for n, (name, state, holder, rate) in enumerate(SUPPLIERS, 1):
        suppliers.append({
            "gstin": gstin.build(state, _pan(rng, holder, name)),
            "name": name,
            "state_code": state,
            "default_rate": rate,
            "phone": f"+91 90000 000{n:02d}",
            "language": LANGUAGE_CHOICE.get(name) or STATE_LANGUAGE.get(state, "en-IN"),
        })
    by_name = {s["name"]: s for s in suppliers}

    books, portal, expected = [], [], {}
    event_records: list[dict] = []   # records that appear only after the supplier files GSTR-1A
    seq = iter(range(1, 1000))

    def bill(sup: dict, *, inv_no: str | None = None, d: date | None = None, txval: Decimal | None = None,
             rate: int | None = None, doc_type: str = "INV") -> dict:
        i = next(seq)
        d = d or date(2026, 10, rng.randint(1, 28))
        txval = txval or Decimal(rng.randrange(2000, 80000, 50))
        rate_d = Decimal(rate if rate is not None else sup["default_rate"])
        prefix = "".join(w[0] for w in sup["name"].split()[:3]).upper()
        return {
            "id": f"B{i:03d}",
            "supplier_gstin_raw": sup["gstin"],
            "supplier_name": sup["name"],
            "doc_type": doc_type,
            "invoice_no": inv_no or f"{prefix}/{rng.randint(100, 9999)}",
            "invoice_date": d,
            "taxable_value": txval,
            "rate": rate_d,
            **_taxes(txval, rate_d, sup["state_code"]),
            "source": "whatsapp_photo",
            "extraction_confidence": round(rng.uniform(0.86, 0.99), 2),
            "image_hash": f"{rng.getrandbits(64):016x}",
        }

    def to_portal(b: dict, sup: dict, **overrides) -> dict:
        rec = {
            "ctin": sup["gstin"], "trdnm": sup["name"], "doc_type": b["doc_type"],
            "inum": b["invoice_no"], "dt": b["invoice_date"],
            "txval": b["taxable_value"], "igst": b["igst"], "cgst": b["cgst"], "sgst": b["sgst"],
            "pos": BUYER_STATE, "rev": "N", "itcavl": "Y", "rsn": "",
            "supfildt": date(2026, 11, rng.choice([11, 12, 13])), "supprd": PERIOD,
        }
        rec.update(overrides)
        if "txval" in overrides:
            rec.update(_taxes(rec["txval"], b["rate"], sup["state_code"]))
        rec["val"] = rec["txval"] + rec["igst"] + rec["cgst"] + rec["sgst"]
        return rec

    def add(b: dict, sup: dict, scenario: str, status: str, tier: str | None = None, **portal_overrides):
        books.append(b)
        if status not in ("missing_in_2b",):
            portal.append(to_portal(b, sup, **portal_overrides))
        expected[b["id"]] = {"scenario": scenario, "status": status, "tier": tier}

    # Clean matches: most suppliers, 1-3 bills each.
    clean_suppliers = [s for s in suppliers if s["name"] not in (
        "Bharath Electricals", "Udupi Logistics", "Pune Agro Chem")]
    for sup in clean_suppliers:
        for _ in range(rng.randint(1, 3)):
            add(bill(sup), sup, "clean", "matched", "exact")

    g, m, k, t, c = (by_name[n] for n in (
        "Sri Ganesh Traders", "Malnad Spices", "Kaveri Plastics", "Tumkur Steel Works", "Coimbatore Pumps"))

    # A. Invoice number punctuation differs between bill and portal.
    b = bill(g, inv_no="SGT/1023")
    add(b, g, "inv_no_format", "matched", "normalised", inum="SGT-1023")
    # B. Bill dated on receipt, 3 days after the supplier's invoice date.
    b = bill(m, d=date(2026, 10, 18))
    add(b, m, "date_shift", "matched", "normalised", dt=date(2026, 10, 15))
    # C. OCR read a zero as the letter O in the invoice number.
    b = bill(k, inv_no="KP/1O45")
    add(b, k, "inv_no_ocr", "matched", "fuzzy", inum="KP/1045")
    # D. Supplier has not filed yet; will file via GSTR-1A when chased.
    be = by_name["Bharath Electricals"]
    for amount in (Decimal("24000"), Decimal("12000")):
        b = bill(be, txval=amount)
        add(b, be, "supplier_not_filed_will_file", "missing_in_2b")
        event_records.append(to_portal(b, be, supfildt=date(2026, 11, 18)))
    # E. Supplier has not filed and stays silent.
    ul = by_name["Udupi Logistics"]
    b = bill(ul, txval=Decimal("18500"))
    add(b, ul, "supplier_not_filed_silent", "missing_in_2b")
    # F. Supplier reported a different taxable value (keyed 45,000 instead of 54,000).
    b = bill(t, txval=Decimal("54000"))
    add(b, t, "amount_mismatch", "amount_mismatch", txval=Decimal("45000"))
    # G1. OCR misread the 'Z' in the supplier GSTIN as '2' (repairable).
    b = bill(c)
    b["supplier_gstin_raw"] = c["gstin"][:13] + "2" + c["gstin"][14]
    add(b, c, "gstin_ocr_z_repairable", "matched", "exact")
    # G2. GSTIN on the bill photo is unreadable/wrong (not repairable): match by invoice + date + amount.
    pa = by_name["Pune Agro Chem"]
    b = bill(pa)
    raw = pa["gstin"]
    b["supplier_gstin_raw"] = raw[:7] + raw[8] + raw[7] + raw[9:]  # two PAN digits swapped
    add(b, pa, "gstin_unreadable_anchored", "matched", "anchored")
    # H. The same bill photographed twice.
    first = bill(g, inv_no="SGT/1088")
    add(first, g, "duplicate_original", "matched", "exact")
    dup = dict(first, id=f"B{next(seq):03d}")
    books.append(dup)
    expected[dup["id"]] = {"scenario": "duplicate_photo", "status": "duplicate_in_books", "tier": None}
    # I. Old bill: Aug 2025 at 12% (valid pre-reform rate), supplier filed late; Sec 16(4) deadline 30 Nov 2026.
    n = by_name["Nandi Hardware"]
    b = bill(n, inv_no="NH/0457", d=date(2025, 8, 12), txval=Decimal("36000"), rate=12)
    add(b, n, "old_rate_late_filed", "matched", "exact")
    # L. Post-reform invoice charged at 12% by mistake: rate needs review.
    b = bill(k, inv_no="KP/1102", rate=12)
    add(b, k, "post_reform_12pct", "matched", "exact")
    # K. Credit note from a supplier, in both books and portal.
    hf = by_name["Hassan Fertilisers"]
    b = bill(hf, inv_no="HF/CN/07", txval=Decimal("3000"), doc_type="CRN")
    add(b, hf, "credit_note", "matched", "exact")
    # J. Supplier reported an invoice the owner has no bill for.
    j_sup = by_name["Chamundi Packaging"]
    ghost = bill(j_sup, inv_no="CP/7781", txval=Decimal("62000"))
    portal.append(to_portal(ghost, j_sup))
    expected_portal_only = [f"{j_sup['gstin']}|CP/7781"]

    gstr2b = _gstr2b_json(profile["gstin"], portal)
    gstr1a_event = {"ctin": be["gstin"], "trdnm": be["name"], "records": event_records}

    ewbs = [
        {"ewb_no": "291014526377", "doc_no": "SLAT/0912", "doc_date": date(2026, 11, 14),
         "generated_at": datetime(2026, 11, 14, 10, 0), "from": "Mysuru", "to": "Bengaluru",
         "distance_km": 145, "vehicle_no": "KA09AB1234", "scenario": "normal"},
        {"ewb_no": "291014526401", "doc_no": "SLAT/0910", "doc_date": date(2026, 11, 13),
         "generated_at": datetime(2026, 11, 13, 18, 30), "from": "Mysuru", "to": "Shivamogga",
         "distance_km": 160, "vehicle_no": "KA09C7731", "scenario": "delayed_needs_extension"},
        {"ewb_no": "291014526455", "doc_no": "SLAT/0915", "doc_date": date(2026, 11, 14),
         "generated_at": datetime(2026, 11, 14, 7, 15), "from": "Mysuru", "to": "Mandya",
         "distance_km": 48, "vehicle_no": "KA09M4589", "vehicle_no_actual": "KA09M4588",
         "invoice_present": True, "scenario": "detained_vehicle_typo"},
    ]

    return {
        "profile.json": profile,
        "suppliers.json": suppliers,
        "books.json": books,
        f"gstr2b_{PERIOD}.json": gstr2b,
        "gstr1a_event.json": gstr1a_event,
        "ewb.json": ewbs,
        "expected_matches.json": {"books": expected, "portal_only": expected_portal_only},
    }


def _gstr2b_json(buyer_gstin: str, records: list[dict]) -> dict:
    """GSTR-2B in the GSP-documented shape (docdata.b2b[].inv[], cdnr[].nt[])."""
    b2b: dict[str, dict] = {}
    cdnr: dict[str, dict] = {}
    for r in records:
        bucket = cdnr if r["doc_type"] == "CRN" else b2b
        sup = bucket.setdefault(r["ctin"], {
            "ctin": r["ctin"], "trdnm": r["trdnm"],
            "supfildt": _ddmmyyyy(r["supfildt"]), "supprd": r["supprd"],
            ("nt" if bucket is cdnr else "inv"): [],
        })
        doc = {
            ("ntnum" if bucket is cdnr else "inum"): r["inum"],
            "typ": "C" if bucket is cdnr else "R",
            "dt": _ddmmyyyy(r["dt"]), "val": r["val"], "pos": r["pos"], "rev": r["rev"],
            "itcavl": r["itcavl"], "rsn": r["rsn"],
            "txval": r["txval"], "igst": r["igst"], "cgst": r["cgst"], "sgst": r["sgst"], "cess": Decimal("0"),
        }
        sup["nt" if bucket is cdnr else "inv"].append(doc)
    return {
        "_simulated": "SIMULATED GSTR-2B for a fictional taxpayer. Not from the GST portal.",
        "data": {
            "gstin": buyer_gstin, "rtnprd": PERIOD, "version": "1.0", "gendt": "14-11-2026",
            "docdata": {"b2b": list(b2b.values()), "cdnr": list(cdnr.values())},
        },
    }


def write(out: Path, seed: int = 7) -> list[Path]:
    out.mkdir(parents=True, exist_ok=True)
    paths = []
    for name, content in generate(seed).items():
        p = out / name
        p.write_text(json.dumps(content, indent=2, default=_j, ensure_ascii=False) + "\n")
        paths.append(p)
    return paths


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", type=Path, default=Path("data/synthetic"))
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()
    for p in write(args.out, args.seed):
        print(p)


if __name__ == "__main__":
    main()
