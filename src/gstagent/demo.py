"""Print this period's reconciliation and checks for the synthetic trader.

    uv run python -m gstagent.demo
"""

from __future__ import annotations

from collections import Counter
from datetime import date, datetime

from gstagent import data
from gstagent.matcher import reconcile
from gstagent.models import MatchStatus
from gstagent.rules import RuleBook
from gstagent.rules.logic import rupees

TODAY = date(2026, 11, 14)


def main() -> None:
    rules = RuleBook.load()
    profile = data.load_profile()
    books = {b.id: b for b in data.load_books()}
    portal = data.portal_records_from_2b(data.load_json("gstr2b_102026.json"))
    period_start = date(2026, 10, 1)

    print(f"{profile.trade_name} ({profile.gstin}), {profile.scheme.value}, period 10/2026  [SIMULATED DATA]\n")

    gate = rules.evaluate("tds.deductor_gate", date(2026, 4, 1), holder_type=profile.holder_type,
                          prior_year_turnover=profile.prior_year_turnover)
    cal = rules.evaluate("gst.filing_calendar", period_start, scheme=profile.scheme.value,
                         state_code=profile.state_code, period="102026")
    print("Profile gate")
    print(f"  {cal.explanation}")
    print(f"  {gate.explanation}\n")

    results = reconcile(list(books.values()), portal, rules, period_start)
    counts = Counter(m.status for m in results)
    risk = sum((m.itc_at_risk for m in results), start=type(results[0].itc_at_risk)("0"))
    clean = sum(1 for m in results
                if m.status == MatchStatus.MATCHED and m.tier == "exact" and "repaired" not in m.reason)
    print(f"Reconciliation: {len(books)} bills vs {len(portal)} portal records")
    print(f"  {clean} clean, {len(results) - clean} need a look; ITC at risk {rupees(risk)}\n")

    print("Needs judgement")
    for m in results:
        if m.status == MatchStatus.MATCHED and m.tier == "exact" and "repaired" not in m.reason:
            continue
        b = books.get(m.book_id) if m.book_id else None
        label = f"{b.id} {b.supplier_name} {b.invoice_no}" if b else m.portal_key
        tier = f"/{m.tier}" if m.tier else ""
        print(f"  [{m.status.value}{tier}] {label}\n      {m.reason}")

    print("\nRule checks on individual bills")
    for b in books.values():
        rate = rules.evaluate("gst.rate_check", b.invoice_date, rate=b.rate)
        if rate.value["category"] != "standard":
            print(f"  {b.id} {b.supplier_name} {b.invoice_no}: {rate.explanation}")
        if b.invoice_date < date(2026, 4, 1):
            tl = rules.evaluate("itc.time_limit_16_4", TODAY, invoice_date=b.invoice_date, check_date=TODAY,
                                filing_scheme=profile.scheme.value, state_code=profile.state_code)
            print(f"  {b.id} {b.supplier_name} {b.invoice_no}: {tl.explanation}")

    print("\nE-way bills")
    for e in data.load_json("ewb.json"):
        start = datetime.fromisoformat(e["generated_at"])
        v = rules.evaluate("ewb.validity", start, validity_start_at=start, distance_km=e["distance_km"])
        print(f"  {e['ewb_no']} {e['from']}->{e['to']}: {v.explanation}")
        if e["scenario"] == "detained_vehicle_typo":
            c = rules.evaluate("ewb.circular_64", TODAY, invoice_present=True, ewb_present=True,
                               vehicle_no_ewb=e["vehicle_no"], vehicle_no_actual=e["vehicle_no_actual"])
            print(f"      Detained: {c.explanation}")

    print(f"\nMatch counts: {dict((k.value, v) for k, v in counts.items())}")


if __name__ == "__main__":
    main()
