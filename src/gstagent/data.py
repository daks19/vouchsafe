"""Load the synthetic dataset (or any data in the same shape) into case models."""

from __future__ import annotations

import json
import os
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from gstagent.models import BookEntry, DocType, PortalRecord, TaxpayerProfile

DEFAULT_DIR = Path(os.environ.get("GSTAGENT_DATA", Path(__file__).resolve().parents[2] / "data" / "synthetic"))


def _d(s: str):
    return datetime.strptime(s, "%d-%m-%Y").date()


def load_json(name: str, directory: Path = DEFAULT_DIR):
    return json.loads((directory / name).read_text())


def load_profile(directory: Path = DEFAULT_DIR) -> TaxpayerProfile:
    return TaxpayerProfile.model_validate(load_json("profile.json", directory))


def load_books(directory: Path = DEFAULT_DIR) -> list[BookEntry]:
    return [BookEntry.model_validate(b) for b in load_json("books.json", directory)]


def portal_records_from_2b(gstr2b: dict) -> list[PortalRecord]:
    """Flatten GSP-shaped GSTR-2B JSON into PortalRecord rows."""
    out = []
    docdata = gstr2b["data"]["docdata"]
    for section, items_key, num_key, doc_type in (("b2b", "inv", "inum", DocType.INVOICE),
                                                  ("cdnr", "nt", "ntnum", DocType.CREDIT_NOTE)):
        for sup in docdata.get(section, []):
            for d in sup[items_key]:
                out.append(PortalRecord(
                    ctin=sup["ctin"], trdnm=sup["trdnm"], doc_type=doc_type, inum=d[num_key],
                    dt=_d(d["dt"]), val=Decimal(d["val"]), txval=Decimal(d["txval"]),
                    igst=Decimal(d["igst"]), cgst=Decimal(d["cgst"]), sgst=Decimal(d["sgst"]),
                    pos=d["pos"], rev=d["rev"], itcavl=d["itcavl"], rsn=d.get("rsn", ""),
                    supfildt=_d(sup["supfildt"]) if sup.get("supfildt") else None, supprd=sup.get("supprd"),
                ))
    return out
