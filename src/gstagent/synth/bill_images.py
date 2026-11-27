"""Render fictional bill photos and the Claude reply each should produce (test fixtures).

    uv run python -m gstagent.synth.bill_images      # needs the dev group (Pillow)

Writes tests/fixtures/bills/<name>.png and <name>.reply.json. The replies it writes are hand-made in
the reply schema (gstagent.extract.SCHEMA). The committed ones are live Gemini recordings (27 Nov): rerunning
this overwrites them, so re-record after with `python -m gstagent.ca_queue <png> --save-reply <name>.reply.json`.
All names, GSTINs and amounts are fictional.
"""

from __future__ import annotations

import json
import random
from decimal import Decimal
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

OUT = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "bills"
BUYER = ("Sri Lakshmi Agro Traders", "Sayyaji Rao Road, Mysuru 570001", "29KEMPR1791C1ZW")

BILLS = [
    # Not in GSTR-2B: the supplier has not reported it -> ITC at risk.
    dict(name="nandi_missing_in_2b", supplier="Nandi Hardware", addr="14, Ashoka Road, Mysuru 570001",
         gstin="29SMBPN4622B1ZW", inv="NH/2291", date="2026-10-27", rate=18, split="intra",
         items=[("Door hinges, steel 4 in", "8302", 120, "62.50"), ("Wood screws, box of 100", "7318", 40, "175.00")]),
    # The 2B record with no bill (portal_only): this photo matches it exactly -> nothing for the CA.
    dict(name="chamundi_matches_2b", supplier="Chamundi Packaging", addr="Plot 22, Hebbal Industrial Area, Mysuru",
         gstin="29CHCFC7955B1Z0", inv="CP/7781", date="2026-10-01", rate=18, split="intra",
         items=[("Corrugated boxes, 5-ply", "4819", 2000, "25.00"), ("BOPP tape, 2 in", "3919", 400, "30.00")]),
    # IGST charged although supplier and shop are both in Karnataka -> tax-split check fails -> re-snap.
    dict(name="kaveri_wrong_split", supplier="Kaveri Plastics", addr="5th Cross, Bannimantap, Mysuru",
         gstin="29SDHCK2013S1ZF", inv="KP/1102", date="2026-10-20", rate=18, split="inter",
         items=[("HDPE bags, 50 kg", "3923", 500, "16.00")]),
]


def totals(b: dict) -> dict:
    taxable = sum(Decimal(q) * Decimal(p) for _, _, q, p in b["items"])
    tax = taxable * b["rate"] / 100
    half = (tax / 2).quantize(Decimal("0.01"))
    igst, cgst, sgst = (tax, Decimal(0), Decimal(0)) if b["split"] == "inter" else (Decimal(0), half, half)
    return {"taxable": taxable, "igst": igst, "cgst": cgst, "sgst": sgst, "total": taxable + igst + cgst + sgst}


def _s(x: Decimal) -> str:
    return f"{x:.2f}"


def reply(b: dict) -> dict:
    t = totals(b)
    v = {"supplier_name": b["supplier"], "supplier_gstin": b["gstin"], "buyer_gstin": BUYER[2], "doc_type": "INV",
         "invoice_no": b["inv"], "invoice_date": b["date"], "place_of_supply": "29",
         "hsn": ", ".join(i[1] for i in b["items"]), "taxable_value": _s(t["taxable"]), "rate": str(b["rate"]),
         "igst": _s(t["igst"]), "cgst": _s(t["cgst"]), "sgst": _s(t["sgst"]), "total": _s(t["total"])}
    rnd = random.Random(b["name"])
    return {k: {"value": val, "confidence": round(rnd.uniform(0.88, 0.99), 2)} for k, val in v.items()}


def render(b: dict) -> Image.Image:
    t = totals(b)
    W, H = 1000, 1300
    page = Image.new("RGB", (W, H), (250, 247, 238))
    d = ImageDraw.Draw(page)
    f = lambda n: ImageFont.load_default(size=n)  # noqa: E731
    ink, grey = (25, 25, 40), (90, 90, 100)
    d.text((W // 2, 50), b["supplier"].upper(), font=f(44), fill=ink, anchor="mm")
    d.text((W // 2, 100), b["addr"], font=f(22), fill=grey, anchor="mm")
    d.text((W // 2, 132), f"GSTIN: {b['gstin']}    State: Karnataka (29)", font=f(22), fill=ink, anchor="mm")
    d.text((W // 2, 185), "TAX INVOICE", font=f(32), fill=ink, anchor="mm")
    d.line((50, 210, W - 50, 210), fill=ink, width=2)
    dd = "-".join(reversed(b["date"].split("-")))
    d.text((60, 230), f"Invoice No: {b['inv']}", font=f(24), fill=ink)
    d.text((W - 60, 230), f"Date: {dd}", font=f(24), fill=ink, anchor="ra")
    d.text((60, 275), f"Bill to: {BUYER[0]}", font=f(22), fill=ink)
    d.text((60, 305), BUYER[1], font=f(20), fill=grey)
    d.text((60, 335), f"GSTIN: {BUYER[2]}    Place of supply: 29-Karnataka", font=f(20), fill=ink)

    cols = [60, 110, 520, 640, 740, 840]
    y = 390
    d.rectangle((50, y - 10, W - 50, y + 30), outline=ink, width=2)
    for x, h in zip(cols, ["#", "Description", "HSN", "Qty", "Rate", "Amount"]):
        d.text((x, y), h, font=f(22), fill=ink)
    for n, (desc, hsn, qty, price) in enumerate(b["items"], 1):
        y += 45
        amt = Decimal(qty) * Decimal(price)
        for x, s in zip(cols, [str(n), desc, hsn, str(qty), price, _s(amt)]):
            d.text((x, y), s, font=f(21), fill=ink)
    y += 60
    d.line((50, y, W - 50, y), fill=ink, width=1)
    lines = [("Taxable value", t["taxable"])]
    if b["split"] == "inter":
        lines.append((f"IGST @ {b['rate']}%", t["igst"]))
    else:
        lines += [(f"CGST @ {b['rate'] / 2:g}%", t["cgst"]), (f"SGST @ {b['rate'] / 2:g}%", t["sgst"])]
    lines.append(("TOTAL (Rs.)", t["total"]))
    for label, val in lines:
        y += 40
        d.text((560, y), label, font=f(24), fill=ink)
        d.text((W - 60, y), _s(val), font=f(24), fill=ink, anchor="ra")
    d.text((W - 60, H - 120), f"For {b['supplier']}", font=f(22), fill=ink, anchor="ra")
    d.text((W - 60, H - 60), "Authorised signatory", font=f(20), fill=grey, anchor="ra")
    d.text((60, H - 60), "Goods once sold will not be taken back. E.&O.E.", font=f(18), fill=grey)

    # Make it look photographed: slight tilt on a table, soft focus, uneven light.
    rnd = random.Random(b["name"])
    photo = Image.new("RGB", (W + 160, H + 160), (118, 96, 72))
    photo.paste(page.rotate(rnd.uniform(-2.5, 2.5), expand=False, fillcolor=(118, 96, 72)), (80, 80))
    shade = Image.linear_gradient("L").resize(photo.size).point(lambda p: 205 + p // 5)
    photo = Image.composite(photo, Image.new("RGB", photo.size, (0, 0, 0)), shade)
    return photo.filter(ImageFilter.GaussianBlur(0.7))


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for b in BILLS:
        render(b).save(OUT / f"{b['name']}.png", optimize=True)
        (OUT / f"{b['name']}.reply.json").write_text(json.dumps(reply(b), indent=2) + "\n")
        print(f"wrote {b['name']}.png and .reply.json")


if __name__ == "__main__":
    main()
