# Vouchsafe (gst-agent)

Team Neo Frontier.

Tech4Bharat 2026, Problem Statement 3.1: *Micro enterprises lose time and profit to compliance paperwork.*

An agent that runs a micro business's GST close, from the bills in its WhatsApp chat to a CA-ready pack.
It chases the suppliers whose filings put the owner's input credit at risk, explains to the owner in
his own language what is about to be filed in his name, and **stops at the line where a professional files**.

> **Status: scaffold.** Deterministic core, rule cards, synthetic data and a simulated GST portal.
> No agent loop, LLM, WhatsApp or voice yet. See *Next steps*.

## Quick start

```bash
uv sync
uv run pytest -q                                    # 137 tests: rule-card examples, matcher scenarios, guard, mock portal
uv run python -m gstagent.demo                      # reconciliation + rule checks on the synthetic trader
uv run python -m gstagent.synth.generate            # regenerate data/synthetic (deterministic, --seed 7)
uv run uvicorn gstagent.mock_gstn.app:app --port 8100   # simulated GST portal; docs at /docs
```

## Layout

| Path | What it is |
|---|---|
| `src/gstagent/models.py` | Case schema: the single source of truth (profile, bills, portal records, matches, tasks, approvals, timeline). Money is `Decimal`. |
| `src/gstagent/gstin.py` | GSTIN structure + Luhn mod-36 checksum. OCR 'Z' repair only when the checksum then passes; never rewrites valid `D`/`C` (TDS/TCS) GSTINs. |
| `src/gstagent/rules/` | Effective-dated **rule cards** (`cards/<id>@<version>.yaml`) plus their logic (`logic.py`). |
| `src/gstagent/matcher.py` | Bills vs GSTR-2B in 4 tiers (exact, normalised, fuzzy, anchored), with a plain reason on every row. |
| `src/gstagent/guard.py` | Number guard: blocks any message containing a figure the case did not compute. |
| `src/gstagent/mock_gstn/` | **Simulated** GST portal: GSTR-2B (GSP-documented JSON shape), IMS view/save, "supplier files GSTR-1A" trigger. |
| `src/gstagent/synth/` | Synthetic data generator with seeded scenarios. |
| `data/synthetic/` | Generated data for a fictional QRMP trader in Mysuru, period 10/2026. |

## Design rules

1. **The LLM never computes.** Every figure comes from a rule card; `guard.check()` blocks anything else.
2. **Profile gate first.** Monthly, QRMP or composition; individual or firm; prior-year turnover. A rule that
   does not apply stays silent (e.g. no contractor TDS for a proprietor below ₹1 crore).
3. **Rules are effective-dated and tested.** A card version carries its window, citations and worked examples.
   `pytest` runs every example.
4. **Prepare, never file.** The ceiling is "ready for CA filing (simulated)". Every outward action waits for human approval.
5. **Label every simulation.** Mock endpoints return `X-Simulated: true` and a `_simulated` banner.

## Rule cards

| Rule | Versions | Notes |
|---|---|---|
| `gst.filing_calendar` | 1 | Monthly 11th/20th; QRMP IFF 13th, PMT-06 25th, 3B 22nd/24th; composition CMP-08 18th |
| `ims.treatment` | 1 (Oct 2024), 2 (Oct 2025) | No action = deemed accepted at GSTR-2B generation; Pending is never deemed accepted later (stays until acted on or 16(4)); credit notes may be Pending from Oct-2025 period; BoE accept/pending only; reverse-charge records are outside IMS |
| `gst.rate_check` | 1 (to 21 Sep 2025), 2 (from 22 Sep 2025) | Judged on the invoice's own date; never auto-reject |
| `itc.time_limit_16_4` | 1 | 30 November after the financial year, or the annual return date if earlier (pass `annual_return_filed_on`). With `filing_scheme`, also the last GSTR-3B that can carry the claim: October's for monthly filers (due 20 Nov), the Jul–Sep quarter's for QRMP filers (due 22/24 Oct) |
| `itc.gstr1a_flow` | 1 (*verify*) | A GSTR-1A record shows in IMS once saved; its ITC lands in the next GSTR-2B generated after filing (usually the next period's), Rule 60(7)(iia) |
| `itc.evidence_pack` | 1 (*verify*) | *Shaurya Alloys* Guideline 6: seven documents (invoices, e-way bills, transport receipts, weighbridge slips, toll receipts, stock records, bank payment proof); binding only in Punjab, Haryana and Chandigarh; never a guarantee |
| `itc.supplier_reported` | 1 (to Sep 2022), 2 (adds 16(2)(ba) from Oct 2022) | ITC at risk if the supplier has not reported, or if the ITC is restricted under Section 38; reporting is never treated as proof of payment |
| `itc.rule_37a` | 1 (*verify*) | Supplier's GSTR-3B missing on 30 Sep after the FY → reverse by 30 Nov, re-avail when filed; a year-end check, not a payment detector |
| `demand.section` | 1 (to Oct 2024), 2 (from Nov 2024, *verify*) | Demands for FY 2024-25 onwards under Section 74A; earlier years under 73/74 |
| `gst.drc01c_trigger` | 1 | More than ₹25 lakh **and** more than 20% (Council minutes, not rule text) |
| `ewb.number_format` | 1 (12 digits), 2 (14 digits, from 1 Jan 2027, *announced*) | The live "rules keep changing" demo |
| `ewb.validity` | 1 (100 km/day), 2 (200 km/day from 2021) | Midnight-of-next-day counting |
| `ewb.extension` | 1, 2 (adds 360-day cap from 2025) | 8 hours after expiry (rule); 8 hours before (portal) |
| `ewb.doc_age` | 1 | No EWB for documents older than 180 days (from 2025) |
| `ewb.circular_64` | 1 | Minor errors (para 5(a)-(f)); output is a draft for a professional |
| `tds.deductor_gate` | 1 | Individual/HUF deducts only above ₹1 crore (business) / ₹50 lakh (profession) last year |
| `tds.contractor` | 1 | ₹30,000 / ₹1,00,000; 1% / 2% / 20% no PAN; base excludes GST |

**Adding a rule change** (the stage demo): copy the current card to `<id>@<n+1>.yaml`, set the new
`effective_from`, close the old card with `effective_to`, update `params`, `citations` and `examples`,
then run `uv run pytest -q`. The engine refuses overlapping windows and cards without logic.

Cards marked `verify_before_finale: true` rest on secondary sources. Check each against the primary
text (CBIC/GSTN/Income-tax Department) before the finale.

## Synthetic scenarios (`data/synthetic/expected_matches.json`)

All names, GSTINs (checksum-valid), phone numbers and amounts are fictional.

| Scenario | What the agent should do |
|---|---|
| clean (25 bills) | Match exactly; nothing for the CA to look at |
| invoice number punctuation differs | Match (normalised) and say how |
| bill dated on receipt, 3 days late | Match (normalised) and say how |
| OCR read 0 as O in invoice number | Match (fuzzy), ask to confirm |
| supplier not filed, will file when chased (2 bills) | Missing in 2B → chase → `POST /mock-gstn/events/supplier-files-gstr1a` → re-match |
| supplier not filed, stays silent | Missing in 2B → escalate, recommend IMS Pending with reason |
| supplier keyed ₹45,000 instead of ₹54,000 | Amount mismatch, ITC at risk, ask supplier to amend via GSTR-1A |
| GSTIN 'Z' misread as '2' | Repair (checksum passes) and match |
| GSTIN unreadable | Anchored match on invoice + date + amount; ask for a clearer photo |
| same bill photographed twice | Duplicate, counted once |
| Aug 2025 bill at 12% filed late | Valid old rate; Section 16(4) deadline 30 Nov 2026 |
| post-reform bill at 12% | Rate needs review; don't reject |
| supplier credit note | Matched; IMS credit-note rules apply |
| invoice in 2B with no bill | Ask the owner; Pending; Reject only after CA review |
| e-way bills | One normal, one near expiry (extension window), one detained over a one-character vehicle typo (Circular 64 para 5(f)) |

## Pattern ledger (provenance)

The hackathon requires original work. Ideas we borrowed are listed here; all code in this repo is our own.

| Idea | Seen in | How we implemented it |
|---|---|---|
| Schema as single source of truth; deterministic checks with citation and fix steps; seeded demo data; "professional signs off" gate | IPO SHERPA (cjagadheesh/Automated-IPO-Drafter, SEBI TechSprint 2026) | `models.py`, rule cards with citations, `synth/`, approval model |
| Tiered reconciliation with a reason per row | KedarDamale/Automated-Reconcillation | `matcher.py` (4 tiers, stdlib only) |
| Degrade gracefully when services fail | DoAideAi/GSTBot | Planned for the agent loop |
| GSTIN position-14 OCR repair | TrustBill AI (IJERT, May 2026) | `gstin.py`, but only when the checksum passes and never for D/C GSTINs |
| "No model ever produces a figure" | Pucca (as described in a Gemini report; not found) | `guard.py` |

## Simulated or not yet built

- **GST portal**: simulated (`mock_gstn`). Real GSTN/GSP access is not available to student teams.
- **E-way bill portal, e-invoice IRP**: not yet; mock with NIC field names next.
- **WhatsApp**: not yet; Meta Cloud API test number (5 recipients, templates needed for supplier chasers).
- **Voice**: not yet; Sarvam STT/TTS behind an adapter.
- **JanAI Café / Asha**: no public API; any integration must be shown as a labelled mock.
- **Filing**: never. Simulated hand-off only.

## Next steps (from the build plan)

1. Agent loop with case store and approval interrupts: plan → act → wait for event → recover → approve.
2. Supplier chase journey end to end (draft → owner approves → send → wait for GSTR-1A → re-match → close or escalate).
3. Vision-LLM bill extraction with schema + validators; real bill photos (with consent) for evaluation.
4. Owner's vernacular "what is being filed in your name" summary, through `guard.check()`.
5. CA cockpit: triage, Tally XML export (educational mode: vouchers dated 1st, 2nd or 31st only), hash-bound approval.
