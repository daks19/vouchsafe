# Changelog

All notable changes to this project. Newest first. Dates are when the work landed.

## [Unreleased]

### Added
- CA dashboard: `python -m gstagent.dashboard` (FastAPI) serves a React page (`frontend/`) over the live agent.
  Client list, readiness meter (resolved cases only; declined and handed-over cases are not ready), exception
  queue, case detail with the draft in the recipient's language beside the English, owner approval, the CA's
  decision, replies (tagged when from a voice note), W3 proof and the audit trail. Clicks carry the hash of the
  text shown: a stale page or a double click gets "changed" (409) and sends nothing. With `--channel telegram`
  only the shop's messages go out, to the demo chat; supplier messages stay simulated. A failed AI step can be
  retried from the page; a failed voice note or network error never stops the Telegram listener, and the page keeps refreshing while a voice note is transcribed. A refused IMS save tells the CA; a typed reply or "a day passes" from a tab left open across Reset is refused. Demo controls: a day passes, type a reply, reset. 25 offline tests.
- CA decision step in the agent: after every hand-off the case waits for the CA (`Agent.decide`). Options come
  from the actual IMS record: Accept / Keep Pending / Reject (as the `ims.treatment` card allows) when the record
  exists, otherwise Wait for the supplier / Follow up again; Close always needs a reason; W3 offers Collect the
  missing proof, and missing documents can be marked not applicable. IMS actions are saved on the mock portal
  only, on the CA's click. 13 offline tests.

### Changed
- W3 evidence no longer says "at purchase GSTR-2B showed…": each bill now reads "GSTR-2B for 10-2026, observed
  <date> (SIMULATED)" and "Status on the purchase date: not available", since the snapshot is taken now.
- A hand-off no longer ends the case: the outcome is the CA's decision.
- Telegram bot channel (`channels/telegram.py`), now the default for the live demo because Meta locks a new
  WhatsApp account until the business is verified (error 131031). Sends text and voice notes, reads typed or
  voice replies by long polling (no public address needed), only to and from `TELEGRAM_DEMO_CHAT`; the bot token
  never appears in errors. `python -m gstagent.channels.live` takes `--channel telegram|whatsapp` (default
  telegram). `python -m gstagent.channels.telegram` prints your chat id. 6 offline tests. Live check (27 Nov,
  Tamil): W1 ran end to end; the Tamil voice reply was transcribed word for word and read as never ordered.
- Live check (27 Nov, Sarvam): text-to-speech returns Ogg/Opus (plays as a voice note); speech-to-text read the
  Hindi clip back word for word.
- WhatsApp and voice channels (`src/gstagent/channels/`), not run live yet:
  - `whatsapp.py`: WhatsApp Cloud API test number; sends text and voice notes, receives replies on a webhook
    that checks Meta's signature, downloads voice notes. Prototype sends only to `WHATSAPP_DEMO_TO`.
  - `voice.py`: Sarvam text-to-speech (`bulbul:v3`, Ogg/Opus) and speech-to-text (`saaras:v4`; the spec named
    v3, which Sarvam now calls legacy). 11 languages.
  - `Agent(deliver=...)` sends each approved message on a real channel; W1 questions also go as a voice note.
  - `python -m gstagent.channels.live`: W1 end to end on WhatsApp, the owner approving in the terminal.
  - Settings in `.env.example`. 10 offline tests.
- Cross-provider fallback: when Gemini is busy or out of free quota, `llm.py` tries Groq (and the other way
  round), if that provider's key is in `.env` too. 2 offline tests. Live check (27 Nov, Groq): 1 of 3 bills
  read fully right (one date read backwards, one bill's amounts unreadable and sent for a re-snap), so Groq stays
  the backup.
- LLM provider switch in `llm.py`: `LLM_PROVIDER=gemini` (default, free tier; `gemini-3.8-flash`, falling back to `gemini-3.6-flash` when busy), `groq`
  (free tier; `qwen/qwen3.8-27b` for bill photos, `openai/gpt-oss-120b` for text) or `claude` (paid). Keys and
  `LLM_MODEL` come from the shell or a git-ignored `.env` (`.env.example` shows them). 10 offline tests.
- Live check (26 Nov, Gemini free tier): all 3 fixture bills read correctly (only case and `0` vs `0.00` differ;
  the wrong-split bill was caught). Agent demo `--live` in Hindi, Tamil and Telugu ran end to end; replies read right.
- Free-tier fallback: when a Gemini model is busy (429/500/503 or timeout) the next free model is tried
  (`gemini-3.8-flash` → `gemini-3.6-flash` → `gemini-3.5-flash-lite`).

### Fixed
- Drafting a message could take a minute when Gemini was busy: the backup model answered slowly while the
  lightest one answers in about a second. Short text requests (translating a message, reading a reply) now give
  each model 6 seconds before moving to the next; bill photos still get 120. Live (27 Nov, busy Gemini): a
  Hindi or Tamil translation took 18–32 s on the backup model, now about 7.5 s. 1 test.
- A bill whose date differs from the supplier's filing (same amount) no longer reads "₹62,000 but the bill
  says ₹62,000": the CA-queue reason and the supplier message name only what differs. 2 tests.
- A translation in the wrong script is refused (live, a Tamil message came back in Kannada script; Hindi came
  back in Latin letters). The prompt asks for the native script; `language.in_script()` checks it; a refused
  translation goes out in English with a note, as before.
- Agent loop (`src/gstagent/agent/`, LangGraph + SQLite checkpointer): one case per mismatch, three workflows.
  - W1 confirm the delivery: ask the receiver, read the reply (Claude, `reply.py`), then ask for the bill,
    mark Pending in IMS, or hand to the CA. Asks at most twice.
  - W2 supplier correction: message the supplier, wait for GSTR-1A, re-check the portal; close when it matches
    (with the `itc.gstr1a_flow` note on which GSTR-2B gets the credit) or hand to the CA after three checks with
    the Section 16(4) dates.
  - W3 keep purchase evidence: on a backdated cancellation, list exposed bills with supplier snapshots and the
    `itc.evidence_pack` status, and hand the pack to the CA.
  - Every outward action waits for the owner's approval, bound to a hash of the exact text; every draft passes
    the number guard; an append-only audit log per case.
  - `python -m gstagent.agent.demo` runs all three end to end; 14 agent tests (each workflow twice in a row).
- Multilingual (`language.py`): 11 languages. Messages go out in each recipient's language (shop's from the
  profile, each supplier's own), with the English beside it for the owner; the approval hash covers both; a
  translation that changes a figure is not used. Replies are understood in any Indian language or script.
  GSTINs and PANs are masked before any text reaches Claude. Demo: `--lang`, a reply in every language.
- `llm.py`: the single Claude call (JSON schema, server-side fallback), used by bill extraction and reply reading.
- `snapshots.py`: timestamped, hashed record of what GSTR-2B showed about a bill's supplier.
- Mock portal: `POST /mock-gstn/events/supplier-cancelled` and `GET /mock-gstn/suppliers/{ctin}`.
- Dependencies: `langgraph`, `langgraph-checkpoint-sqlite`, `httpx` (runtime).
- P0 bill pipeline: a bill photo turns into a CA-queue exception with issue, reason, cited rule and recommended action.
  - `extract.py`: Claude vision (`claude-opus-5-5`) reads a bill into fixed fields, each with a confidence score.
    Unclear fields come back null. Only the image is sent; the prompt has no GSTIN or PAN.
  - `validate.py`: checks required fields and confidence, the GSTIN check digit (with repair), the CGST/SGST-vs-IGST
    split and the arithmetic. A failed check creates a "resnap" task.
  - `ca_queue.py`: runs the matcher and rate check and builds the queue rows. Usable as a CLI
    (`python -m gstagent.ca_queue <image> [--replay | --save-reply]`) and as a FastAPI app (`/ca-queue/bills`, `/ca-queue`).
  - Rule card `gst.tax_split@1` (IGST Act s.5, 7, 8; CGST Act s.9) with 5 tested examples.
  - Three synthetic bill photos with matching Claude replies in `tests/fixtures/bills/`, rendered by
    `synth/bill_images.py`.
  - 26 new tests (163 in total).
- Dependency: `anthropic` (runtime), `pillow` (dev only).
- `AGENTS.md` (rules for contributors and AI agents), `CLAUDE.md` (loads AGENTS.md), `PLAN.md` (milestones,
  owners, progress log) and this changelog.
- `docs/SPEC.md`: the product spec, moved into the repo so the whole team works from one copy.

### Changed
- The 3 bill fixtures (`tests/fixtures/bills/*.reply.json`) are now live Gemini recordings instead of hand-made
  replies; same values, only capitals, `0` vs `0.00` and confidence scores differ.
- No more Kannada-only defaults: model defaults are `en-IN`; synthetic suppliers now use Hindi, Tamil, Telugu,
  Marathi, Malayalam, English and Kannada; supplier messages no longer open with a Kannada greeting.
- README "Next steps" now points to PLAN.md instead of keeping its own list.

### Known limits
- The paid Claude provider has not been run live (Gemini and Groq have).

## 2026-11-20: prototype core

### Added
- Deterministic core: case schema (`models.py`), GSTIN checksum with OCR 'Z' repair, 4-tier matcher,
  number guard, 24 effective-dated rule-card versions with citations and worked examples.
- Simulated GST portal (`mock_gstn`): GSTR-2B, IMS view/save, "supplier files GSTR-1A" event.
- Synthetic data for a fictional QRMP trader in Mysuru, period 10/2026, with seeded scenarios.
- 137 tests.
