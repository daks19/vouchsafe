# AGENTS.md

Instructions for AI coding agents (and new teammates) working in this repo.

## What this is

Vouchsafe: an agentic GST assistant for small traders and their CAs (Tech4Bharat 2026, PS 3.1, Agentic AI track).
Shops send bill photos; Claude reads them; tested rule cards match them against GSTR-2B/IMS; the agent asks
the right person about each mismatch and keeps evidence. It prepares. A human approves and files.

- **Source of truth:** [docs/SPEC.md](docs/SPEC.md).
  Sections 4 (architecture), 5 (where each piece comes from), 6 (stack), 8 (build plan).
- **What to build next:** [PLAN.md](PLAN.md). **What changed:** [CHANGELOG.md](CHANGELOG.md).

## Commands

```bash
uv sync
uv run pytest -q                       # must stay green; currently 211 tests
uv run python -m gstagent.demo         # reconciliation on the synthetic trader
uv run python -m gstagent.ca_queue tests/fixtures/bills/nandi_missing_in_2b.png \
    --replay tests/fixtures/bills/nandi_missing_in_2b.reply.json   # bill photo -> CA queue, offline
```

Python 3.12, managed with `uv`. Add packages with `uv add` (runtime) or `uv add --dev` (tests and tooling only).

## Rules that never bend

1. **The LLM never computes.** Every figure comes from a rule card or Python code. `guard.check()` blocks any
   message containing a number the case did not compute.
2. **Never send unmasked PAN or GSTIN to the LLM in text.** Images go with the owner's consent; prompts carry no IDs.
3. **Unclear means null.** Extraction never guesses a field. A failed validator asks for a re-snap.
4. **Prepare, never file.** No filing, no money movement, no automatic Reject in IMS, never call a supplier a fraud.
   Every outward action (message, IMS action, hand-off) waits for human approval.
5. **Label every simulation.** Mock endpoints send `X-Simulated: true` and a `_simulated` banner.
6. **Money is `Decimal`**, never float. Dates are `date`, never strings, inside models.
7. **Every language, not one.** Vouchsafe serves traders across India. Anything a person reads or hears goes
   out in that person's language (`language.py`); never hard-code or default to one regional language. Demos and
   tests show several. The Mysuru shop is only demo data.

## How the code is laid out

- `models.py` is the single schema. Read and write through it; don't invent parallel shapes.
- Law-facing facts live in rule cards: `rules/cards/<id>@<version>.yaml` plus a function in `rules/logic.py`.
  To change a rule, add a new version with its own window, citations and examples. Never edit an old card's
  facts. `pytest` runs every card's examples.
- Pipeline: `extract.py` (Claude vision) → `validate.py` → `matcher.py` + rule cards → `ca_queue.py`.
- Agent: `agent/graph.py` (LangGraph). One thread per case. Every outward action is drafted, passes the number
  guard, then waits at the `approve` node; an approval counts only with the hash of the exact text shown.
  All LLM calls go through `llm.py`.
- Tests must run offline. Mock every LLM, Sarvam or WhatsApp call with a recorded reply in `tests/fixtures/`.
- LLM: `LLM_PROVIDER` in `.env` picks `gemini` (default, free tier), `groq` (free tier) or `claude` (paid).
  If Gemini is busy, Groq is tried when its key is set too (and the other way round). Default models are in `llm.py`; `LLM_MODEL` overrides one. See `.env.example`. Don't change the defaults
  without the team's say. Google may use free-tier data for training: fictional data only on the free tier.

## Working rules

- Keep changes small and finish them: update callers, tests, fixtures, README and CHANGELOG in the same change.
- Plain, short language in user-facing text and docs. The owner and CA are not engineers.
- **Teamwork:** two people (and their agents) work here. `git pull` before starting. One branch per task
  (`<name>/<task>`), merged into `main` by pull request; never push straight to `main`. Before you start a task,
  put your name in its PLAN.md row so nobody doubles up. Every PR updates PLAN.md status and CHANGELOG.md.
- **Every session, start and end:** read PLAN.md (Owner column and the latest *Progress log* entry) before
  you start. Before you stop, add a Progress log entry (what changed, where you left it, what's unverified, what
  to do next) and update CHANGELOG.md `[Unreleased]`. Anything only in your chat, local notes or agent memory is
  invisible to the rest of the team: if it matters, write it in the repo.
- **Secrets:** API keys go in your shell environment or a local `.env` (git-ignored). Never in code, fixtures or docs.
- **Git:** commit or push only when asked. **No `Co-Authored-By` trailer or any AI attribution in commits.**
- **Reuse from IPO SHERPA** (github.com/cjagadheesh/Automated-IPO-Drafter) only when PLAN.md says so. Credit it in the README
  pattern ledger, and strip any SEBI, DRHP, ICDR, banker or prospectus wording.
- All data is fictional. Never add a real person's GSTIN, PAN, phone number or bill without written consent.
