# PLAN.md

Build plan for the Tech4Bharat prototype. Prototype due **13 Dec 2026**; finale **27 Dec** (Bangalore Palace).
Full detail lives in [docs/SPEC.md](docs/SPEC.md) §8. Update this file when a milestone moves.
Taking a task? Put your name in its Owner cell first, so two people (or two agents) never build the same thing.

## Milestones

| Due | Milestone | Done when | Status | Owner |
|---|---|---|---|---|
| 29 Nov | **P0 pipeline** | Bill photo → Claude fields → validators → matcher → CA-queue exception with reason and cited rule (synthetic data) | Built, live Claude call not yet tested | Dakshan |
| 3 Dec | **Agent + three workflows** | LangGraph loop runs W1, W2, W3 end to end on the mock portal, twice in a row, with approval pauses | Not started |  |
| 7 Dec | **Real channels** | WhatsApp question and Sarvam voice reply (Kannada first) on a low-cost Android | Not started |  |
| 10 Dec | **CA dashboard + accuracy** | Dashboard shows each case with replies and proof; extraction accuracy measured on 20–40 real bills | Not started |  |
| 12 Dec | **Hardening** | Demo script rehearsed, video recorded, README says what is simulated and what was reused | Not started |  |
| 13 Dec | **Prototype submitted** | | |  |

**Cut order if time runs short:** Q&A copilot → rule-change alert → notice check → Tally export. **Never cut W1.**

## P0: left to finish (by 29 Nov)

- [ ] Run the live Claude call once with a key: `uv run python -m gstagent.ca_queue <png> --save-reply out.json`.
      Compare it with the hand-made fixture, then replace the three `.reply.json` files with real recordings.
- [ ] Decide whether the README "Status" line can say P0 is done (only after the live check passes).

## Next: agent + three workflows (by 3 Dec)

New code in `src/gstagent/agent/` (LangGraph, SQLite checkpointer, `interrupt()` before every outward action).

- [ ] Case store: one case per mismatch, built from the CA-queue rows and `models.Case`.
- [ ] **W1 Confirm the delivery:** a 2B line with no bill → ask the receiver (text first; voice comes on 7 Dec).
      Three answers: arrived (ask for the bill) / still coming (recommend IMS Pending) / never ordered (CA exception).
- [ ] **W2 Supplier correction:** owner approves → message the supplier → wait for the GSTR-1A event in
      `mock_gstn` → re-match → close, or escalate to the CA with the 16(4) date.
- [ ] **W3 Keep purchase evidence:** add a "cancellation backdated" event to `mock_gstn`, plus supplier snapshots
      (`snapshots.py`) → list exposed invoices → evidence pack (`itc.evidence_pack`), with proof present and missing.
- [ ] Append-only audit log (`case.open`, `shop.asked`, `supplier.messaged`, `ims.recommended`, `ca.approved`).
- [ ] Agent-loop tests on the mock portal: each workflow twice in a row, with approvals replayed.

## Later milestones, in short

- **7 Dec:** `channels/whatsapp.py` (Cloud API test number, 5 recipients, templates for supplier messages) and
  `channels/voice.py` (Sarvam `saaras:v3` speech-to-text, plus text-to-speech, behind one adapter).
- **10 Dec:** CA dashboard from the IPO SHERPA UI kit (client list, exception queue, readiness meter, audit trail,
  hash-bound approval); phone-sized `Shop.jsx` fallback; owner's "what is being filed in your name" read-back in
  their language, through `guard.check()`; accuracy run on consented real bills. Tally XML export if time allows
  (educational mode: vouchers dated 1st, 2nd or 31st only).
- **12 Dec:** clean-up pass (no SEBI/DRHP/ICDR/banker wording), README credits line from spec §13, demo video.

## Known gaps and open questions

- Image duplicate check is an exact-bytes hash; switch to a perceptual hash once real photos come in.
- Arithmetic check assumes one GST rate per bill.
- CA-queue API keeps its state in memory.
- Demo persona is "Ramesh, hardware trader", but the synthetic trade name is "Sri Lakshmi Agro Traders". Pick one before the video.
- Lyzr AI credits: terms unknown. Keep LangGraph unless the hackathon requires Lyzr.
- Cards marked `verify_before_finale: true` need checking against primary text (CBIC/GSTN) before 27 Dec.

## Progress log

Newest first. One entry per work session, by whoever did the work (person or agent): what changed, where it was
left, and what the next person should do first. Keep each entry to a few lines; details go in CHANGELOG.md.

### 2026-11-26 · Dakshan (with Claude)
- Built the P0 pipeline: `extract.py`, `validate.py`, `ca_queue.py`, rule card `gst.tax_split@1`, three fixture bills
  in `tests/fixtures/bills/`. 163 tests pass.
- Moved the spec into `docs/SPEC.md`; added `AGENTS.md`, `PLAN.md`, `CHANGELOG.md` and a `CLAUDE.md` that loads AGENTS.md.
- **Not verified:** the live Claude call (no API key on this machine). The fixture replies are hand-made, not recorded.
- **Next:** run the live check in *P0: left to finish*, then claim a milestone above and start the agent loop.
