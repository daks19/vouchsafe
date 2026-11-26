# PLAN.md

Build plan for the Tech4Bharat prototype. Prototype due **13 Dec 2026**; finale **27 Dec** (Bangalore Palace).
Full detail lives in [docs/SPEC.md](docs/SPEC.md) §8. Update this file when a milestone moves.
Taking a task? Put your name in its Owner cell first, so two people (or two agents) never build the same thing.

## Milestones

| Due | Milestone | Done when | Status | Owner |
|---|---|---|---|---|
| 29 Nov | **P0 pipeline** | Bill photo → Claude fields → validators → matcher → CA-queue exception with reason and cited rule (synthetic data) | Built; live check passed on Gemini free tier (26 Nov) | Dakshan |
| 3 Dec | **Agent + three workflows** | LangGraph loop runs W1, W2, W3 end to end on the mock portal, twice in a row, with approval pauses | Built, merged (PR #1); live run passed in Hindi, Tamil, Telugu (26 Nov) | Dakshan |
| 7 Dec | **Real channels** | WhatsApp question and Sarvam voice reply in Hindi, Tamil, Telugu, Kannada, English and the other supported languages on a low-cost Android | Not started |  |
| 10 Dec | **CA dashboard + accuracy** | Dashboard shows each case with replies and proof; extraction accuracy measured on 20–40 real bills | Not started |  |
| 12 Dec | **Hardening** | Demo script rehearsed, video recorded, README says what is simulated and what was reused | Not started |  |
| 13 Dec | **Prototype submitted** | | |  |

**Cut order if time runs short:** Q&A copilot → rule-change alert → notice check → Tally export. **Never cut W1.**

## P0: left to finish (by 29 Nov)

- [x] Run the live LLM call once with a key (`cp .env.example .env`, Gemini's key is free):
      `uv run python -m gstagent.ca_queue <png> --save-reply out.json`.
      Compare it with the hand-made fixture, then replace the three `.reply.json` files with real recordings.
- [ ] Decide whether the README "Status" line can say P0 is done (only after the live check passes).

## Next: agent + three workflows (by 3 Dec)

New code in `src/gstagent/agent/` (LangGraph, SQLite checkpointer, `interrupt()` before every outward action).

- [x] Cases: one per mismatch (`agent/cases.py`), each a LangGraph thread saved in SQLite. Not yet `models.Case`.
- [x] **W1 Confirm the delivery:** a 2B line with no bill → ask the receiver (text first; voice comes on 7 Dec).
      Three answers: arrived (ask for the bill) / still coming (recommend IMS Pending) / never ordered (CA exception).
- [x] **W2 Supplier correction:** owner approves → message the supplier → wait for the GSTR-1A event in
      `mock_gstn` → re-match → close, or escalate to the CA with the 16(4) date.
- [x] **W3 Keep purchase evidence:** add a "cancellation backdated" event to `mock_gstn`, plus supplier snapshots
      (`snapshots.py`) → list exposed invoices → evidence pack (`itc.evidence_pack`), with proof present and missing.
- [x] Append-only audit log per case (`case.open`, `owner.approved`, `shop.asked`, `supplier.messaged`,
      `ims.pending_saved`, `ca.handoff`, `case.closed`). `ca.approved` comes with the CA dashboard (10 Dec).
- [x] Agent-loop tests on the mock portal: each workflow twice in a row, with approvals replayed (`tests/test_agent.py`).
- [x] Review and merge `dakshan/agent-loop` into `main` by pull request (PR #1).
- [x] Multilingual: messages go out in each recipient's language (shop: profile; supplier: own record), with the
      English beside it for the owner; replies understood in any Indian language. 11 languages in `language.py`.
- [ ] Run the demo with `--live` in several languages (e.g. `--lang hi-IN`, `ta-IN`, `te-IN`) so the LLM really
      translates and reads replies; have native speakers check the messages and the demo replies (needs a key).
- [ ] Group a supplier's open W2 cases into one message (today: one message per bill).

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
- If Gemini's free model reads bills badly, try `LLM_PROVIDER=groq` or `claude` (paid) on the same 3 fixtures.
- Lyzr AI credits: terms unknown. Keep LangGraph unless the hackathon requires Lyzr.
- Cards marked `verify_before_finale: true` need checking against primary text (CBIC/GSTN) before 27 Dec.

## Progress log

Newest first. One entry per work session, by whoever did the work (person or agent): what changed, where it was
left, and what the next person should do first. Keep each entry to a few lines; details go in CHANGELOG.md.

### 2026-11-26 (night) · Dakshan (with Claude)
- Branch `dakshan/groq-fallback`: a busy or rate-limited Gemini now falls back to Groq when `GROQ_API_KEY` is
  set. 209 tests pass. **Not verified:** a live Groq call (no Groq key yet).
- **Next:** add a free Groq key to `.env` and read the 3 fixture bills with `LLM_PROVIDER=groq` once.

### 2026-11-26 (evening) · Dakshan (with Claude)
- Merged the agent loop into `main` (PR #1).
- Branch `dakshan/llm-switch`: `llm.py` now picks the LLM from `LLM_PROVIDER` (gemini default, groq, claude),
  keys from a git-ignored `.env` (`.env.example`). 204 tests pass.
- Live check on Gemini free tier: 3 fixture bills read right; `--live` demo in Hindi, Tamil, Telugu ran end to end.
  Found and fixed: translations in the wrong script (Tamil came back in Kannada script). Busy models fall back.
- **Not verified:** Groq and Claude live; native-speaker check of the translations; the free tier is often busy
  (503), so rehearse the demo early and keep `--replay` fixtures as backup.
- **Next:** replace the 3 hand-made `.reply.json` fixtures with the live recordings; start the 7 Dec channels.

### 2026-11-26 (later) · Dakshan (with Claude)
- Built the agent loop on branch `dakshan/agent-loop`: `agent/` (LangGraph + SQLite), W1/W2/W3, hash-bound owner
  approvals, audit log, `llm.py`, `snapshots.py`, mock-portal cancellation event.
- Made it multilingual (was Kannada-only): `language.py` (11 languages, GSTIN/PAN masking, translation),
  per-recipient message language, replies in any language, suppliers in the data now use 7 languages. 195 tests pass.
- `uv run python -m gstagent.agent.demo` runs all three workflows end to end offline.
- **Not verified:** Claude translating and reading replies live (stubbed in tests and the offline demo).
- **Next:** open a pull request for the branch; then the 7 Dec channels milestone (WhatsApp + Sarvam) plugs into
  the `send` node and the `reply` pause in `agent/graph.py`.

### 2026-11-26 · Dakshan (with Claude)
- Built the P0 pipeline: `extract.py`, `validate.py`, `ca_queue.py`, rule card `gst.tax_split@1`, three fixture bills
  in `tests/fixtures/bills/`. 163 tests pass.
- Moved the spec into `docs/SPEC.md`; added `AGENTS.md`, `PLAN.md`, `CHANGELOG.md` and a `CLAUDE.md` that loads AGENTS.md.
- **Not verified:** the live Claude call (no API key on this machine). The fixture replies are hand-made, not recorded.
- **Next:** run the live check in *P0: left to finish*, then claim a milestone above and start the agent loop.
