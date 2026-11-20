"""Behaviour for each rule card. Parameters come from the card, never hardcoded here.

Each function takes (card, inputs) and returns (value_dict, explanation).
Explanations are plain language and only contain numbers computed here.
"""

from __future__ import annotations

import math
from datetime import date, datetime, time, timedelta
from decimal import ROUND_HALF_UP, Decimal
from functools import lru_cache
from typing import Any

from gstagent.rules.engine import RuleCard, rule


def D(x: Any) -> Decimal:
    return x if isinstance(x, Decimal) else Decimal(str(x))


def as_date(x: Any) -> date:
    if isinstance(x, datetime):
        return x.date()
    if isinstance(x, date):
        return x
    return date.fromisoformat(str(x))


def as_dt(x: Any) -> datetime:
    if isinstance(x, datetime):
        return x
    return datetime.fromisoformat(str(x))


def rupees(x: Decimal) -> str:
    """Indian digit grouping: 1234567.5 -> ₹12,34,567.50"""
    q = x.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    sign = "-" if q < 0 else ""
    whole, frac = f"{abs(q):.2f}".split(".")
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        whole = ",".join(groups + [tail])
    return f"{sign}₹{whole}" + ("" if frac == "00" else f".{frac}")


@lru_cache(maxsize=1)
def _rulebook():
    """The loaded cards, for rules that read another card (e.g. 16(4) uses the filing calendar)."""
    from gstagent.rules.engine import RuleBook

    return RuleBook.load()


def _next_month(d: date, day: int) -> date:
    y, m = (d.year + 1, 1) if d.month == 12 else (d.year, d.month + 1)
    return date(y, m, day)


# --------------------------------------------------------------------------- GST

@rule("gst.filing_calendar")
def filing_calendar(card: RuleCard, i: dict) -> tuple[dict, str]:
    p = card.params
    scheme, state = i["scheme"], str(i["state_code"]).zfill(2)
    mm, yyyy = int(str(i["period"])[:2]), int(str(i["period"])[2:])
    period_start = date(yyyy, mm, 1)
    out = {"gstr1_or_iff": None, "gstr1_optional": False, "gstr3b": None, "pmt06": None, "cmp08": None}
    quarter_end = mm in (3, 6, 9, 12)

    if scheme == "regular_monthly":
        out["gstr1_or_iff"] = _next_month(period_start, p["monthly"]["gstr1_day"])
        out["gstr3b"] = _next_month(period_start, p["monthly"]["gstr3b_day"])
        msg = f"Monthly filer: GSTR-1 by {out['gstr1_or_iff']}, GSTR-3B by {out['gstr3b']}."
    elif scheme == "regular_qrmp":
        q = p["qrmp"]
        out["gstr1_or_iff"] = _next_month(period_start, q["iff_or_gstr1_day"])
        if quarter_end:
            day = q["gstr3b_day_group_a"] if state in q["group_a_states"] else q["gstr3b_day_group_b"]
            out["gstr3b"] = _next_month(period_start, day)
            msg = f"QRMP quarter-end month: GSTR-1 by {out['gstr1_or_iff']}, GSTR-3B by {out['gstr3b']}."
        else:
            out["gstr1_optional"] = True
            out["pmt06"] = _next_month(period_start, q["pmt06_day"])
            msg = (f"QRMP first/second month: IFF is optional (by {out['gstr1_or_iff']}); "
                   f"pay tax via PMT-06 by {out['pmt06']}.")
    elif scheme == "composition":
        if quarter_end:
            out["cmp08"] = _next_month(period_start, p["composition"]["cmp08_day"])
            msg = f"Composition: CMP-08 for the quarter by {out['cmp08']}. No ITC, no IMS actions."
        else:
            msg = "Composition: nothing due for this month; CMP-08 is quarterly. No ITC, no IMS actions."
    else:
        raise ValueError(f"unknown scheme {scheme}")
    return out, msg


@rule("ims.treatment")
def ims_treatment(card: RuleCard, i: dict) -> tuple[dict, str]:
    p = card.params
    doc, action = i["doc_type"], i["action"]
    boe = bool(i.get("is_bill_of_entry", False))

    if i.get("reverse_charge"):
        return ({"allowed": False, "in_ims": False, "flows_to_2b": True},
                "Reverse-charge records are not in IMS; they flow into GSTR-2B directly, so no IMS action "
                "(Accept, Reject or Pending) is possible. Ask the CA how to treat it.")
    if boe and not p["boe_in_ims"]:
        return {"allowed": False, "flows_to_2b": None}, "Bills of Entry are not in IMS for this period."
    if boe and action == "REJECTED":
        return {"allowed": False, "flows_to_2b": None}, "Bills of Entry can only be Accepted or kept Pending."
    if doc == "CRN" and action == "PENDING" and not p["credit_note_pending_allowed"]:
        return {"allowed": False, "flows_to_2b": None}, "Credit notes cannot be kept Pending in this period."

    if action in ("NO_ACTION", "ACCEPTED"):
        note = ("No action: the record is deemed accepted when GSTR-2B is generated and flows into it."
                if action == "NO_ACTION" else "Accepted: the record flows into GSTR-2B.")
        if doc == "CRN" and p["credit_note_reduction_choice"]:
            note += " On accepting a credit note the buyer declares how much ITC to reduce (remark needed if less than full)."
        return {"allowed": True, "flows_to_2b": True}, note
    if action == "REJECTED":
        return {"allowed": True, "flows_to_2b": False}, "Rejected: kept out of GSTR-2B ITC. Recommend Reject only after CA review."
    if action == "PENDING":
        if doc == "CRN":
            return ({"allowed": True, "flows_to_2b": False},
                    "Pending: the credit note is kept out of this GSTR-2B for one tax period.")
        return ({"allowed": True, "flows_to_2b": False},
                "Pending: kept out of GSTR-2B and GSTR-3B. It is not deemed accepted later; it stays Pending "
                "until someone accepts or rejects it, or the Section 16(4) time limit is reached.")
    raise ValueError(f"unknown action {action}")


@rule("gst.rate_check")
def rate_check(card: RuleCard, i: dict) -> tuple[dict, str]:
    rate = D(i["rate"])
    standard = {D(r) for r in card.params["standard"]}
    special = {D(r) for r in card.params.get("special", [])}
    window = f"for supplies on or after {card.effective_from}" + (
        f" and up to {card.effective_to}" if card.effective_to else "")
    if rate in standard:
        return {"category": "standard"}, f"{rate}% is a standard rate {window}."
    if rate in special:
        return {"category": "special_review"}, f"{rate}% is a special rate {window}; check the HSN qualifies."
    return {"category": "non_standard_review"}, (
        f"{rate}% is not a standard rate {window}. Flag for review; do not reject automatically.")


@rule("itc.time_limit_16_4")
def itc_time_limit(card: RuleCard, i: dict) -> tuple[dict, str]:
    inv, today = as_date(i["invoice_date"]), as_date(i["check_date"])
    fy_end_year = inv.year + 1 if inv.month >= 4 else inv.year
    dl = card.params["deadline"]
    deadline = date(fy_end_year, dl["month"], dl["day"])
    annual = i.get("annual_return_filed_on")
    cut = annual is not None and as_date(annual) < deadline
    if cut:
        deadline = as_date(annual)
    days_left = (deadline - today).days
    expired = days_left < 0
    if cut:
        why = f"ITC on this invoice had to be claimed by {deadline}, when the annual return was filed (earlier than 30 November). "
    elif annual is None:
        why = (f"ITC on this invoice must be claimed by {deadline}, or by the date the annual return is filed if that "
               f"comes first. ")
    else:
        why = f"ITC on this invoice must be claimed by {deadline}. "
    msg = why + ("The deadline has passed." if expired else f"{days_left} days left.")
    out = {"deadline": deadline, "days_left": days_left, "expired": expired, "cut_by_annual_return": cut,
           "last_return_period": None, "claim_by": None, "claim_by_passed": None}

    scheme = i.get("filing_scheme")
    if scheme is None:
        return out, msg
    if scheme == "composition":
        return out, msg + " A composition taxpayer cannot claim ITC at all."

    # ITC is claimed in a GSTR-3B, and a period's GSTR-3B can only be filed after the period ends.
    # So the last return that can carry the claim is for the period ending before the deadline's month.
    last_month = date(deadline.year, deadline.month, 1) - timedelta(days=1)
    if scheme == "regular_qrmp":
        qe = (last_month.month // 3) * 3                     # last quarter-end month at or before it
        last_period = date(last_month.year, qe, 1) if qe else date(last_month.year - 1, 12, 1)
        label = f"GSTR-3B for the quarter ending {last_period:%b %Y}"
    elif scheme == "regular_monthly":
        last_period = last_month.replace(day=1)
        label = f"GSTR-3B for {last_period:%b %Y}"
    else:
        raise ValueError(f"unknown filing_scheme {scheme}")

    period = f"{last_period:%m%Y}"
    cal_card = _rulebook().get("gst.filing_calendar", last_period)
    cal, _ = filing_calendar(cal_card, {"scheme": scheme, "state_code": i.get("state_code", "29"), "period": period})
    claim_by = min(cal["gstr3b"], deadline)
    passed = today > claim_by
    out.update(last_return_period=period, claim_by=claim_by, claim_by_passed=passed)

    msg += (f" In practice the last return that can carry this claim is the {label}, due {claim_by}"
            + (" (cut short by the deadline)." if claim_by < cal["gstr3b"] else "."))
    if scheme == "regular_qrmp":
        msg += " The next quarter's return is due after the deadline, so it is too late."
    if passed and not expired:
        msg += (f" That due date has passed: if the {label} is not filed yet, file it with this claim before "
                f"{deadline} (late fee and interest apply). If it was filed without the claim, no later return "
                "can carry it; ask the CA.")
    return out, msg


@rule("itc.supplier_reported")
def itc_supplier_reported(card: RuleCard, i: dict) -> tuple[dict, str]:
    tax = D(i["tax"])
    in_2b, itcavl = bool(i["in_2b"]), i.get("itcavl", "Y")
    restricted = card.params.get("check_s38_restriction", False) and bool(i.get("restricted_s38", False))
    if in_2b and itcavl == "Y" and not restricted:
        return ({"itc_claimable_now": True, "itc_at_risk": Decimal("0")},
                "Supplier has reported this invoice; ITC shows in GSTR-2B. This shows the supplier reported it, "
                "not that he paid the tax.")
    if not in_2b:
        why = "supplier has not reported it in GSTR-1/IFF"
    elif restricted:
        why = "the ITC communicated in GSTR-2B is restricted under Section 38 (Section 16(2)(ba))"
    else:
        why = "GSTR-2B marks ITC as not available"
    return ({"itc_claimable_now": False, "itc_at_risk": tax},
            f"{rupees(tax)} of ITC is at risk: {why}.")


@rule("itc.gstr1a_flow")
def itc_gstr1a_flow(card: RuleCard, i: dict) -> tuple[dict, str]:
    filed = as_date(i["gstr1a_filed_on"])
    orig = str(i["original_period"])
    orig_start = date(int(orig[2:]), int(orig[:2]), 1)
    gen_day = card.params["gstr2b_generation_day"]
    # GSTR-2B for period P is generated on gen_day of the month after P. A GSTR-1A record goes
    # into the next GSTR-2B generated after it is filed.
    gen = date(filed.year, filed.month, gen_day)
    if filed >= gen:
        gen = _next_month(gen, gen_day)
    p_end = gen.replace(day=1) - timedelta(days=1)
    period = f"{p_end:%m%Y}"
    later = p_end.replace(day=1) > orig_start
    msg = ("The supplier's corrected record shows in IMS as soon as it is saved in GSTR-1A, so it can be "
           f"matched now. Its ITC flows into the GSTR-2B for {p_end:%b %Y}, generated on {gen}"
           + (f", not the {orig_start:%b %Y} GSTR-2B. Claim it in that later period's return." if later else "."))
    return ({"in_ims_now": True, "itc_2b_period": period, "itc_2b_available_on": gen,
             "later_than_original_period": later}, msg)


@rule("itc.evidence_pack")
def itc_evidence_pack(card: RuleCard, i: dict) -> tuple[dict, str]:
    p = card.params
    docs: dict[str, str] = p["documents"]
    present = set(i.get("present", []))
    unknown = present - docs.keys()
    if unknown:
        raise ValueError(f"unknown document keys {sorted(unknown)}")
    missing = [k for k in docs if k not in present]
    binding = str(i.get("state_code", "")).zfill(2) in p["binding_state_codes"]
    msg = f"{len(docs) - len(missing)} of {len(docs)} documents in the pack."
    if missing:
        msg += " Missing: " + "; ".join(docs[k] for k in missing) + "."
    msg += (" Shaurya Alloys binds in Punjab, Haryana and Chandigarh." if binding else
            " Shaurya Alloys is a Punjab and Haryana High Court ruling: persuasive here, not binding.")
    msg += " The pack helps the CA show the purchase was genuine; it does not guarantee the credit."
    return ({"present_count": len(docs) - len(missing), "total": len(docs), "missing": missing,
             "complete": not missing, "binding": binding, "guarantees_outcome": False}, msg)


def _fy_end_year(d: date) -> int:
    return d.year + 1 if d.month >= 4 else d.year


@rule("itc.rule_37a")
def itc_rule_37a(card: RuleCard, i: dict) -> tuple[dict, str]:
    p = card.params
    inv, today = as_date(i["invoice_date"]), as_date(i["check_date"])
    fy_end = _fy_end_year(inv)
    cutoff = date(fy_end, p["supplier_cutoff"]["month"], p["supplier_cutoff"]["day"])
    reverse_by = date(fy_end, p["reverse_by"]["month"], p["reverse_by"]["day"])
    filed = bool(i["supplier_3b_filed_by_cutoff"])
    days_left = (reverse_by - today).days
    out = {"reversal_required": False, "supplier_cutoff": cutoff, "reverse_by": reverse_by, "days_left": days_left}
    note = " A filed GSTR-3B is filing status, not proof that the tax on this invoice was paid."
    if filed:
        return out, f"The supplier filed GSTR-3B for that period by {cutoff}: no Rule 37A reversal." + note
    if today <= cutoff:
        return out, (f"The supplier has not yet filed GSTR-3B for that period. If it is still missing on {cutoff}, "
                     f"the ITC must be reversed by {reverse_by}.") + note
    out["reversal_required"] = True
    when = "The date has passed." if days_left < 0 else f"{days_left} days left."
    return out, (f"The supplier had not filed GSTR-3B for that period by {cutoff}, so the ITC must be reversed by "
                 f"{reverse_by}; it can be re-availed once the supplier files. {when} Confirm with the CA.") + note


@rule("demand.section")
def demand_section(card: RuleCard, i: dict) -> tuple[dict, str]:
    fy = int(i["fy_start_year"])
    first_74a = card.params.get("s74a_from_fy")
    label = f"FY {fy}-{str(fy + 1)[-2:]}"
    if first_74a is not None and fy >= int(first_74a):
        return {"section": "74A"}, f"A demand for {label} falls under Section 74A. Time limits and penalties are for the CA."
    return {"section": "73/74"}, (f"A demand for {label} falls under Section 73 (or 74 if fraud is alleged). "
                                  f"Time limits and penalties are for the CA.")


@rule("gst.drc01c_trigger")
def drc01c_trigger(card: RuleCard, i: dict) -> tuple[dict, str]:
    itc_3b, itc_2b = D(i["itc_3b"]), D(i["itc_2b"])
    excess = itc_3b - itc_2b
    amt, pct = D(card.params["amount_threshold"]), D(card.params["percent_threshold"])
    excess_pct = (excess * 100 / itc_2b).quantize(Decimal("0.01")) if itc_2b > 0 else None
    trigger = excess > amt and (excess_pct is None or excess_pct > pct)
    msg = (f"ITC claimed exceeds GSTR-2B by {rupees(max(excess, Decimal('0')))}"
           + (f" ({excess_pct}%)" if excess_pct is not None and excess > 0 else "")
           + (". This would cross the DRC-01C trigger; prepare the explanation now."
              if trigger else f". Below the DRC-01C trigger (more than {rupees(amt)} and more than {pct}%)."))
    return {"would_trigger": trigger, "excess": excess, "excess_pct": excess_pct}, msg


# ------------------------------------------------------------------- E-way bill

@rule("ewb.number_format")
def ewb_number_format(card: RuleCard, i: dict) -> tuple[dict, str]:
    digits = card.params["digits"]
    no = str(i["ewb_no"]).strip()
    ok = no.isdigit() and len(no) == digits
    return ({"valid_format": ok, "expected_digits": digits},
            f"E-way bills generated in this period have {digits}-digit numbers; "
            + ("format ok." if ok else f"'{no}' does not match."))


@rule("ewb.validity")
def ewb_validity(card: RuleCard, i: dict) -> tuple[dict, str]:
    start = as_dt(i["validity_start_at"])
    km = D(i["distance_km"])
    per_day = D(card.params["odc_km_per_day"] if i.get("odc") else card.params["km_per_day"])
    days = max(1, math.ceil(km / per_day))
    # Each day expires at midnight of the day following the start date.
    valid_through = start.date() + timedelta(days=days)
    expires_at = datetime.combine(valid_through + timedelta(days=1), time(0, 0))
    return ({"days": days, "valid_through_date": valid_through, "expires_at": expires_at},
            f"{km} km at {per_day} km per day gives {days} day(s); valid until midnight ending {valid_through}.")


@rule("ewb.extension")
def ewb_extension(card: RuleCard, i: dict) -> tuple[dict, str]:
    p = card.params
    expires, now = as_dt(i["expires_at"]), as_dt(i["now"])
    opens = expires - timedelta(hours=p["hours_before_expiry"])
    closes = expires + timedelta(hours=p["hours_after_expiry"])
    in_window = opens <= now <= closes
    reasons = []
    if not in_window:
        reasons.append("outside the extension window")
    cap = p.get("max_total_days")
    if cap and i.get("original_generated_at"):
        if (now - as_dt(i["original_generated_at"])).days > cap:
            reasons.append(f"total validity would exceed the {cap}-day cap")
    ok = not reasons
    msg = (f"Extension window: {opens:%d-%m-%Y %H:%M} to {closes:%d-%m-%Y %H:%M}. "
           + ("Extension possible now." if ok else "Cannot extend: " + "; ".join(reasons) + "."))
    return {"can_extend": ok, "window_opens": opens, "window_closes": closes}, msg


@rule("ewb.doc_age")
def ewb_doc_age(card: RuleCard, i: dict) -> tuple[dict, str]:
    age = (as_date(i["generate_on"]) - as_date(i["doc_date"])).days
    limit = card.params["max_doc_age_days"]
    ok = age <= limit
    return ({"allowed": ok, "age_days": age},
            f"Document is {age} days old; " + ("e-way bill can be generated." if ok
             else f"e-way bills cannot be generated for documents older than {limit} days."))


def _char_diff(a: str, b: str) -> int:
    a, b = a.replace(" ", "").replace("-", "").upper(), b.replace(" ", "").replace("-", "").upper()
    if len(a) == len(b):
        return sum(x != y for x, y in zip(a, b))
    prev = list(range(len(b) + 1))  # Levenshtein
    for ca in a:
        cur = [prev[0] + 1]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


@rule("ewb.circular_64")
def ewb_circular_64(card: RuleCard, i: dict) -> tuple[dict, str]:
    if not (i.get("invoice_present") and i.get("ewb_present")):
        return ({"covered": False, "paras": []},
                "Circular 64 only helps when the goods carry both an invoice and an e-way bill.")
    paras, uncovered = [], []
    for field, para in (("vehicle_no", "5(f)"), ("doc_no", "5(d)")):
        ewb_v, real_v = i.get(f"{field}_ewb"), i.get(f"{field}_actual")
        if ewb_v and real_v:
            n = _char_diff(str(ewb_v), str(real_v))
            if 0 < n <= card.params["max_char_errors"]:
                paras.append(para)
            elif n > card.params["max_char_errors"]:
                uncovered.append(f"{field} differs by {n} characters")
    for flag, para in (("name_spelling_error_gstin_correct", "5(a)"),
                       ("pin_error_address_correct", "5(b)"),
                       ("address_error_locality_correct", "5(c)"),
                       ("hsn_error_first2_and_rate_correct", "5(e)")):
        if i.get(flag):
            paras.append(para)
    covered = bool(paras) and not uncovered
    if covered:
        pen = card.params["penalty_s125"]
        msg = (f"Minor error(s) under Circular 64/38/2018-GST para {', '.join(paras)}: Section 129 "
               f"proceedings may not be initiated; penalty under Section 125 of {rupees(D(pen['cgst']))} CGST + "
               f"{rupees(D(pen['sgst']))} SGST (or {rupees(D(pen['igst']))} IGST). Draft for professional review.")
    else:
        msg = "Not covered by Circular 64" + (f": {'; '.join(uncovered)}" if uncovered else "") + ". Escalate to a professional."
    return {"covered": covered, "paras": paras}, msg


# -------------------------------------------------------------------------- TDS

@rule("tds.deductor_gate")
def tds_deductor_gate(card: RuleCard, i: dict) -> tuple[dict, str]:
    p = card.params
    holder = i["holder_type"]
    if holder not in ("individual", "huf"):
        return ({"must_deduct": True, "cliff_warning": False},
                f"A {holder} must deduct TDS on contractor and professional payments.")
    kind = i.get("income_kind", "business")
    limit = D(p["turnover_limit_business"] if kind == "business" else p["receipts_limit_profession"])
    prior = D(i["prior_year_turnover"])
    must = prior > limit
    projected = D(i.get("current_year_projection", 0))
    warn = (not must) and projected > limit * D(p["cliff_warning_fraction"])
    if must:
        msg = f"Last year's {kind} turnover of {rupees(prior)} is above {rupees(limit)}: TDS deduction applies this year."
    else:
        msg = f"Last year's {kind} turnover of {rupees(prior)} is within {rupees(limit)}: no contractor or professional TDS to deduct this year."
        if warn:
            msg += f" This year is projected at {rupees(projected)}; crossing {rupees(limit)} makes you a deductor next year."
    return {"must_deduct": must, "cliff_warning": warn}, msg


@rule("tds.contractor")
def tds_contractor(card: RuleCard, i: dict) -> tuple[dict, str]:
    p = card.params
    if i.get("transporter_exempt"):
        return ({"tds": Decimal("0"), "base": Decimal("0"), "rate": Decimal("0"), "payment_code": None},
                "Transporter owning ten or fewer goods carriages has given a declaration with PAN: no TDS.")
    bill = D(i["bill_base"])
    agg_before, done_before = D(i.get("aggregate_before", 0)), D(i.get("tds_base_already", 0))
    agg_after = agg_before + bill
    single, aggregate = D(p["single_bill_threshold"]), D(p["aggregate_threshold"])
    if agg_after > aggregate:
        base, why = agg_after - done_before, f"year's total {rupees(agg_after)} crosses {rupees(aggregate)}"
    elif bill > single:
        base, why = bill, f"this bill {rupees(bill)} exceeds {rupees(single)}"
    else:
        return ({"tds": Decimal("0"), "base": Decimal("0"), "rate": Decimal("0"), "payment_code": None},
                f"No TDS yet: bill within {rupees(single)} and year's total {rupees(agg_after)} within {rupees(aggregate)}.")
    ind = i["payee_holder_type"] in ("individual", "huf")
    rate = D(p["rate_no_pan"] if not i.get("payee_has_pan", True)
             else p["rate_individual_huf"] if ind else p["rate_others"])
    code = p["payment_code_individual_huf"] if ind else p["payment_code_others"]
    tds = (base * rate / 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return ({"tds": tds, "base": base, "rate": rate, "payment_code": code},
            f"Deduct {rupees(tds)} ({rate}% of {rupees(base)}, GST excluded) because the {why}.")
