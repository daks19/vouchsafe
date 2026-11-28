# Vouchsafe (gst-agent)

Team Neo Frontier.

Tech4Bharat 2026, Problem Statement 3.1: *Micro enterprises lose time and profit to compliance paperwork.*

An agent that runs a micro business's GST close, from the bills in its WhatsApp chat to a CA-ready pack.
It chases the suppliers whose filings put the owner's input credit at risk, explains to the owner in
his own language what is about to be filed in his name, and **stops at the line where a professional files**.

> **Status: P0 pipeline done; agent loop and CA dashboard built.** A bill photo goes through an LLM's vision (Gemini by default)
> (`extract.py`), Python validators (`validate.py`) and the matcher + rule cards into a CA exception queue
> (`ca_queue.py`). A LangGraph agent (`agent/`) runs the three workflows on each mismatch, pausing for the
> owner's approval before every outward action; every hand-off waits for the CA's decision on a dashboard
> (`dashboard.py` + `frontend/`). Synthetic data, simulated GST portal and message channel.
> Sarvam voice is tested live; the live demo channel is a Telegram bot (WhatsApp needs a verified business). See [PLAN.md](PLAN.md).

Build plan: [PLAN.md](PLAN.md) · Rules for contributors and AI agents: [AGENTS.md](AGENTS.md) · Changes: [CHANGELOG.md](CHANGELOG.md)

## Quick start

```bash
uv sync
uv run pytest -q                                    # 286 tests: rule cards, matcher, guard, mock portal, bill pipeline, agent, languages, channels, dashboard
uv run python -m gstagent.demo                      # reconciliation + rule checks on the synthetic trader
uv run python -m gstagent.synth.generate            # regenerate data/synthetic (deterministic, --seed 7)
uv run uvicorn gstagent.mock_gstn.app:app --port 8100   # simulated GST portal; docs at /docs

# Bill photo -> CA-queue exception. --replay uses a saved Claude reply (offline, no key needed).
uv run python -m gstagent.ca_queue tests/fixtures/bills/nandi_missing_in_2b.png \
    --replay tests/fixtures/bills/nandi_missing_in_2b.reply.json
# Live: cp .env.example .env, add a key (Gemini's is free), drop --replay (--save-reply out.json keeps the reply)
uv run uvicorn gstagent.ca_queue:app --port 8200        # POST raw image bytes to /ca-queue/bills; GET /ca-queue
uv run python -m gstagent.synth.bill_images             # re-render the fixture bill photos (dev group: Pillow)

# Agent loop: W1, W2, W3 end to end on the in-process mock portal, approving every pause; prints each audit log.
uv run python -m gstagent.agent.demo --lang hi-IN       # shop speaks Hindi; any of the 11 codes in language.py
# add --live so the LLM translates each message into the recipient's language and reads the reply

# W1 on a real Telegram bot + Sarvam voice (keys in .env; see src/gstagent/channels/telegram.py and live.py)
uv run python -m gstagent.channels.live --lang ta-IN          # --channel whatsapp once Meta verifies the business

# CA dashboard: one page over the live agent. Build the page once (Node 20+), then open http://localhost:8000
(cd frontend && npm install && npm run build)
uv run python -m gstagent.dashboard                             # rehearsal: offline, no keys, simulated channel
uv run python -m gstagent.dashboard --lang ta-IN --channel telegram   # W1 to the Telegram demo chat (live LLM + voice)
```

Fixture bills (`tests/fixtures/bills/`): `nandi_missing_in_2b` (supplier hasn't reported it → ITC at risk),
`chamundi_matches_2b` (matches the 2B-only record → nothing to review), `kaveri_wrong_split` (IGST inside one
state → re-snap). Their `.reply.json` files are live Gemini recordings (27 Nov), replayed offline in tests.

## Layout

| Path | What it is |
|---|---|
| `src/gstagent/models.py` | Case schema: the single source of truth (profile, bills, portal records, matches, tasks, approvals, timeline). Money is `Decimal`. |
| `src/gstagent/gstin.py` | GSTIN structure + Luhn mod-36 checksum. OCR 'Z' repair only when the checksum then passes; never rewrites valid `D`/`C` (TDS/TCS) GSTINs. |
| `src/gstagent/rules/` | Effective-dated **rule cards** (`cards/<id>@<version>.yaml`) plus their logic (`logic.py`). |
| `src/gstagent/extract.py` | Claude vision reads a bill photo into fixed fields, each with a confidence; unclear = null. Only the image is sent; the prompt has no GSTIN/PAN. |
| `src/gstagent/validate.py` | Checks on what Claude read: required fields + confidence, GSTIN check digit, CGST/SGST vs IGST split (`gst.tax_split`), arithmetic. A failure is a "resnap" task. |
| `src/gstagent/ca_queue.py` | Photo → extract → validate → matcher + rule cards → CA queue rows. CLI and FastAPI app. |
| `src/gstagent/agent/` | LangGraph agent: one thread per case (`cases.py`), W1/W2/W3 graph with hash-bound approval pauses and an append-only audit log (`graph.py`), Claude reading the shop's reply (`reply.py`), scripted demo (`demo.py`). SQLite checkpointer keeps cases across restarts. |
| `src/gstagent/dashboard.py` | CA workspace API: lists cases with status and readiness, owner approvals and CA decisions (hash-bound), typed or Telegram replies, demo controls; serves `frontend/dist`. |
| `frontend/` | React 19 + Vite + Tailwind 4 page: client list, readiness meter, exception queue, case detail with approvals, CA decision, replies, proof and audit trail. Polls every 2 s. |
| `src/gstagent/channels/` | Telegram bot (`telegram.py`: the live demo channel), WhatsApp Cloud API (`whatsapp.py`: signed webhook; needs Meta business verification) and Sarvam voice (`voice.py`: text-to-speech, speech-to-text). Prototype sends only to one demo chat. `live.py` runs W1 on them. |
| `src/gstagent/language.py` | Supported languages (Hindi, Bengali, Telugu, Marathi, Tamil, Gujarati, Kannada, Malayalam, Odia, Punjabi, English), GSTIN/PAN masking, translation. Each message goes out in the recipient's language. |
| `src/gstagent/llm.py` | The one place that calls an LLM, always for schema-checked JSON. `LLM_PROVIDER` picks Gemini (default, free), Groq (free) or Claude (paid); a busy Gemini falls back to Groq. |
| `src/gstagent/snapshots.py` | What GSTR-2B showed about a bill's supplier, timestamped and hashed (W3 evidence). |
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
| `gst.tax_split` | 1 | Same state → CGST + SGST in equal halves; different states → IGST only (IGST Act s.5, 7, 8; CGST Act s.9). SEZ/imports not detected, so a mismatch is a review |
| `gst.rate_check` | 1 (to 21 Sep 2025), 2 (from 22 Sep 2025) | Judged on the invoice's own date; never auto-reject |
| `itc.time_limit_16_4` | 1 | 30 November after the financial year, or the annual return date if earlier (pass `annual_return_filed_on`). With `filing_scheme`, also the last GSTR-3B that can carry the claim: October's for monthly filers (due 20 Nov), the Jul–Sep quarter's for QRMP filers (due 22/24 Oct) |
| `itc.gstr1a_flow` | 1 (*verify*) | A GSTR-1A record shows in IMS once saved; its ITC lands in the next GSTR-2B generated after filing (usually the next period's), Rule 60(7)(iia) |
| `itc.evidence_pack` | 1, 2 (*verify*) | *Shaurya Alloys* para 103(vi): proof such as invoices, e-way bills, transport receipts, weighbridge slips, stock and consumption records (examples, not a checklist; no score). v2 lists bank payment and toll receipts as other useful proof. Binding only in Punjab, Haryana and Chandigarh; never a guarantee |
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

The hackathon requires original work. Ideas we borrowed are listed here. All code in this repo is our own; the
dashboard's small UI parts are adapted from IPO SHERPA, built by members of this team (credited in each file).

| Idea | Seen in | How we implemented it |
|---|---|---|
| Schema as single source of truth; deterministic checks with citation and fix steps; seeded demo data; "professional signs off" gate | IPO SHERPA (cjagadheesh/Automated-IPO-Drafter, SEBI TechSprint 2026) | `models.py`, rule cards with citations, `synth/`, approval model |
| Dashboard UI kit (card, badge, stat tile, theme), readiness arc, audit-trail layout | IPO SHERPA (same team) | `frontend/src/components/ui/`, `Readiness.jsx`, `Timeline.jsx`, `index.css`; SEBI/ICDR wording removed |
| Tiered reconciliation with a reason per row | KedarDamale/Automated-Reconcillation | `matcher.py` (4 tiers, stdlib only) |
| Degrade gracefully when services fail | DoAideAi/GSTBot | Planned for the agent loop |
| GSTIN position-14 OCR repair | TrustBill AI (IJERT, May 2026) | `gstin.py`, but only when the checksum passes and never for D/C GSTINs |
| "No model ever produces a figure" | Pucca (as described in a Gemini report; not found) | `guard.py` |

## Simulated or not yet built

- **GST portal**: simulated (`mock_gstn`). Real GSTN/GSP access is not available to student teams.
- **E-way bill portal, e-invoice IRP**: not yet; mock with NIC field names next.
- **Messages to the shop and suppliers**: simulated; the agent records them in each case's outbox. On the
  dashboard with `--channel telegram`, only the shop's (W1) messages go out for real, to the demo chat.
- **IMS actions** (Accept / Pending / Reject): saved on the mock portal only, on the CA's click.
- **WhatsApp**: adapter built (`channels/whatsapp.py`), but Meta locks a new account until the business is verified,
  so the prototype uses a Telegram bot.
- **Voice**: Sarvam STT/TTS (`channels/voice.py`), tested live.
- **JanAI Café / Asha**: no public API; any integration must be shown as a labelled mock.
- **Filing**: never. Simulated hand-off only.

## Next steps

The build plan, who owns what, and the latest progress are in [PLAN.md](PLAN.md). Kept there only, so it can't drift.
