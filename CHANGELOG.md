# Changelog

All notable changes to this project. Newest first. Dates are when the work landed.

## [Unreleased]

### Added
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
- No more Kannada-only defaults: model defaults are `en-IN`; synthetic suppliers now use Hindi, Tamil, Telugu,
  Marathi, Malayalam, English and Kannada; supplier messages no longer open with a Kannada greeting.
- README "Next steps" now points to PLAN.md instead of keeping its own list.

### Known limits
- The live Claude call has not been run yet (no key on the dev machine). The fixture replies are hand-made in the
  reply schema, not recordings.

## 2026-11-20: prototype core

### Added
- Deterministic core: case schema (`models.py`), GSTIN checksum with OCR 'Z' repair, 4-tier matcher,
  number guard, 24 effective-dated rule-card versions with citations and worked examples.
- Simulated GST portal (`mock_gstn`): GSTR-2B, IMS view/save, "supplier files GSTR-1A" event.
- Synthetic data for a fictional QRMP trader in Mysuru, period 10/2026, with seeded scenarios.
- 137 tests.
