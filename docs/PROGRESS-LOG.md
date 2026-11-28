# Vouchsafe: progress and decisions log

Written 27 Nov 2026 to brief other AI agents and reviewers before the next build step. It covers what exists,
what has been tested live, every important decision and why, the mistakes we made, and what comes next.
Repo: github.com/daks19/vouchsafe. Source of truth for the product: [SPEC.md](SPEC.md). Build plan:
[../PLAN.md](../PLAN.md). Change history: [../CHANGELOG.md](../CHANGELOG.md).

## 1. What Vouchsafe is

An agentic GST assistant for small Indian traders and their accountants (Tech4Bharat 2026, PS 3.1, Agentic AI
track). A shop sends bill photos. An LLM reads them; tested rule cards match them against GSTR-2B and IMS. For
every mismatch, the agent asks the right person in their own language (by voice), follows up, and keeps proof.
**It prepares; a human approves and files.** It never files, never moves money, never auto-rejects an invoice.

- Prototype due **13 Dec 2026**; finale **27 Dec** (Bangalore Palace).
- Team Neo Frontier: four registered students (Dakshan Kumar S, Adithyan Benoy, Sachin Saravanan, Shaisanjai P);
  two write code, each with AI agents. One branch per task, merged by PR.
- All data is fictional. The GST portal is simulated (student teams can't get GSTN/GSP access).

## 2. Where it stands today (27 Nov)

Milestones in PLAN.md: P0 pipeline (due 29 Nov) **done**; agent + three workflows (due 3 Dec) **done**; real
channels (due 7 Dec) **mostly done**; CA dashboard (due 10 Dec) **designed, not built**; hardening (12 Dec) not started.

228 offline tests pass. 8 PRs merged, all on 26–27 Nov.

### Working and tested live

| What | Live result |
|---|---|
| Bill photo → fields (Gemini free tier) | 3 of 3 fixture bills read right (~5.5 s each). Recordings saved as test fixtures. |
| Agent demo `--live` | W1, W2, W3 end to end in Hindi, Tamil and Telugu; replies read right. |
| Groq as backup LLM | Works, but reads bills worse: 1 of 3 fully right. Nothing unsafe got through (validators caught the bad bill). |
| Sarvam voice | Text-to-speech returns Ogg/Opus (plays as a voice note). Speech-to-text read a Hindi clip back word for word. |
| **Telegram live W1** | Owner approved in the terminal → Tamil question sent as text + voice note → user replied by Tamil voice note → transcribed word for word → read as "never ordered" → case handed to the CA with full audit trail. |
| Faster drafting | With Gemini busy, a translation now takes ~7.5 s instead of 18–60 s. |

### Built, tested offline only

- WhatsApp Cloud API adapter (`channels/whatsapp.py`): send text and voice notes, signed webhook, media download.
  Blocked live by Meta (see §4).
- Claude as LLM provider (paid; never run live).
- Groq on text (translation, reading replies): never run live.
- Telegram in languages other than Tamil.

### Simulated (by design)

GST portal (GSTR-2B, IMS, supplier status, "supplier files GSTR-1A", "registration cancelled" events), supplier
snapshots' data, messages to suppliers. Every simulated response is labelled `X-Simulated: true`.

## 3. What has been built (by layer)

| Layer | Files | Notes |
|---|---|---|
| Schema | `models.py` | Single source of truth. Money is `Decimal`, dates are `date`. |
| GSTIN | `gstin.py` | Structure + check digit; OCR 'Z' repair only when the checksum then passes. |
| Rule cards | `rules/cards/*.yaml`, `rules/logic.py` | Effective-dated, cited, each with examples run by pytest. Never edit an old card; add a version. |
| Bill reading | `extract.py` | LLM vision → fixed fields with confidence; unclear = null, never guessed. No GSTIN/PAN in prompts. |
| Validators | `validate.py` | Required fields, GSTIN check digit, CGST/SGST vs IGST split, arithmetic. Failure → "re-snap". |
| Matcher | `matcher.py` | 4 tiers: exact, normalised, fuzzy (OCR slips), anchored (GSTIN unreadable); then amount mismatch, missing on either side. Plain reason per row. |
| CA queue | `ca_queue.py` | Photo → extract → validate → match → queue rows. CLI + FastAPI. State in memory. |
| Number guard | `guard.py` | Blocks any outgoing message containing a number the rules did not compute. |
| Agent | `agent/` | LangGraph + SQLite checkpointer. One thread per case. W1 confirm delivery, W2 supplier correction, W3 evidence after a backdated cancellation. Every outward action is drafted, guarded, then waits for approval bound to the hash of the exact text shown. Append-only audit log. |
| Languages | `language.py` | 11 languages; each message in the recipient's language with English beside it for the owner. Prompts carry no GSTIN/PAN in text; bill photos (which show them) go to the LLM only with the owner's consent. |
| LLM | `llm.py` | One place for all LLM calls. `LLM_PROVIDER` = gemini (default, free) / groq (free) / claude (paid). Busy model → next free Gemini model → Groq. Text calls give each model 6 s; photos 120 s. |
| Channels | `channels/telegram.py`, `whatsapp.py`, `voice.py`, `live.py` | Telegram is the live demo channel; WhatsApp kept for production; Sarvam for voice. `live.py --channel telegram|whatsapp` runs W1 live. Prototype sends only to one demo chat. |
| Mock portal | `mock_gstn/` | GSP-shaped GSTR-2B, IMS save validated by the `ims.treatment` card, demo events. |

## 4. Timeline and decisions

### 26 Nov
1. **P0 pipeline built** (photo → fields → validators → matcher → CA queue). 163 tests.
2. **Agent loop built** with LangGraph (W1/W2/W3, hash-bound approvals, audit log). PR #1.
3. **Made multilingual.** The first version was Kannada-only (the demo shop is in Mysuru). Rule since then: every
   message goes out in the recipient's language; never default to one regional language. 11 languages.
4. **LLM provider switch.** Decision: Gemini free tier as default (no budget), Groq as free backup, Claude as paid
   option. Reason: student team, no paid API budget. Constraint: Google may train on free-tier data, so fictional
   data only. PR #2.
5. **Live Gemini check found a real bug:** a Tamil translation came back in Kannada script. Fixed with a script check
   on translations. Busy Gemini models now fall back to the next free model.
6. **Groq fallback** when Gemini is busy or out of quota. PR #3.

### 27 Nov, morning
7. **Live Groq check.** Groq misread a date (1 Oct → 10 Jan) and returned junk amounts for one bill. Validators
   caught it. Decision: Gemini stays first, Groq only as backup.
8. **Fixed a confusing message.** A date-only mismatch read "₹62,000 but the bill says ₹62,000". The CA-queue reason
   and supplier message now name only the field that differs. PR #4.
9. **Live fixtures.** The three hand-made bill fixtures were replaced with real Gemini recordings. P0 marked done. PR #5.

### 27 Nov, afternoon: channels
10. **Cost check.** WhatsApp ~₹0 for a demo; Sarvam ₹100 free credit (STT ₹0.49/min, TTS ₹3 per 1k characters).
    Demo total ~₹0–150.
11. **Built WhatsApp Cloud API + Sarvam voice adapters** against Meta's documented API, offline tests only. PR #6.

### 27 Nov, evening: the WhatsApp detour (a mistake)
12. **Meta locked the WhatsApp account.** The user created a Meta developer app and business portfolio. Incoming
    messages worked, but every outgoing message failed with error **131031 "Business Account locked"**. The webhook
    log showed the cause: Meta sent `BUSINESS_VERIFICATION_NEEDED` minutes after the account was created. Account
    Quality showed no policy issue. Unlocking needs business verification with a *registered business's* documents
    (GST certificate, incorporation certificate, business bank statement) and 2–10 business days. A student team
    has none.
13. **What went wrong:** the agent (Claude) chose Meta's direct Cloud API because it is the official route, and led
    the user through account setup **without first checking or warning that new accounts can be locked until the
    business is verified**. That cost the user several hours of setup (Meta app, business portfolio, test number,
    2FA, Account Quality checks) for a channel that cannot send. Lesson: check the onboarding gates of any external
    platform (verification, approval, country limits) *before* asking the user to create accounts.
14. **Options compared:**
    - Meta business verification: not feasible (no registered business; 2–10 days).
    - Meta support ticket: unknown wait, no promise.
    - **Twilio WhatsApp sandbox:** real WhatsApp, no verification; 100 free messages, rejoin every 3 days,
      24-hour window, Twilio's number and logo as sender, no custom templates, India sign-up unconfirmed.
    - **Telegram bot:** free, instant, real voice-note bubbles, answer buttons possible, its own name, no public
      address (long polling), no expiry. But Indian shop owners mostly use WhatsApp, not Telegram.
    - Unofficial WhatsApp libraries: rejected (break WhatsApp's terms, can ban the user's number).
15. **Decision: Telegram for the live demo.** Reason: reliable on stage, free, no expiry. The pitch line becomes
    "the channel is a plug-in; production runs on a verified WhatsApp number". The WhatsApp code stays.
    PLAN, SPEC and README were updated before any code. PR #7.
16. **Live Telegram run.** First attempt in Hindi: the user doesn't speak Hindi and no reply reached the bot. Rerun in
    **Tamil worked end to end** (see §2).

### 27 Nov, night
17. **Slow drafting fixed.** Cause: when `gemini-3.8-flash` was busy, the backup `gemini-3.6-flash` took 18–32 s on a
    short translation; `flash-lite` answers in ~1 s. Fix: text-only calls give each model 6 s before moving on.
    Trade-off: under load, the lightest model writes the translation more often (quality looked fine; no native
    speaker check yet). PR #8.
18. **CA dashboard designed** (not built). See §5.

## 5. The CA dashboard (built 28 Nov; live Telegram rehearsal pending)

Full design: [superpowers/specs/2026-11-27-ca-dashboard-design.md](superpowers/specs/2026-11-27-ca-dashboard-design.md).

- **Why:** judges watch a screen; today everything runs in a terminal. The CA is the paying customer.
- **Live, not a replay:** clicking Approve on the page really sends the Telegram question; the voice reply appears on
  the page; the hand-off follows.
- **Stack:** React 19 + Vite + Tailwind 4 page, reusing small parts of the team's earlier IPO SHERPA project (cards,
  badges, stat tiles, audit trail, score meter → readiness meter); FastAPI API over the agent; served as one app,
  one command. Page polls every 2 s.
- **Who approves what (decided):** the owner approves what goes out in the shop's name (messages, recommended IMS
  Pending). The **CA makes the tax decision** on every case handed over. Options come from the actual record:
  Accept / Keep Pending / Reject when the supplier's record is in IMS; Wait for the supplier / Follow up again when
  it is not (W2 bill missing from 2B); Collect the missing proof (W3); Close always needs a reason. Saved on the
  mock portal only. A Reject happens only on the CA's click, never automatically.
- **Run it:** `(cd frontend && npm install && npm run build)`, then `uv run python -m gstagent.dashboard` (offline) or
  `--lang ta-IN --channel telegram` (live), and open http://localhost:8000.
- **Builder's calls:** offline rehearsal mode with no API keys; only W1 shop messages go to Telegram (supplier
  messages stay simulated, one phone on stage); declined cases don't count as ready.
- **Not in this round:** login, Tally export, phone-sized shop screen, bill-photo upload on the page, mobile layout.

## 5b. Cross-check of the plan (27 Nov, Gemini + Claude + ChatGPT)

Three AI reviews of this log disagreed in places. What we kept:

- **Roster is fine.** The rules want 4 students; SPEC names 4. Only confirm the names match the HackCulture
  registration. (Claude's audit called this an emergency; it was wrong.)
- **Keep Telegram.** Tell judges exactly what is live (Telegram + Sarvam voice) and what is simulated (portal,
  supplier). Twilio is optional, after the core path works. Don't put unverified Meta error codes in the pitch.
- **Privacy: billing alone is not the fix.** Paid Gemini stops Google training on the data, but it does not give
  consent, does not cover the Groq fallback, and the Gemini API needs users 18+. Before any real bill: a paid
  key on an adult team member's account, the owner's written consent, and only providers whose terms allow it.
- **No model migration needed now.** Our Gemini and Groq defaults are not the ones being retired. The Claude
  default (Opus) is only used with `LLM_PROVIDER=claude`; switching it to Haiku is the team's call.
- **CA buttons come from the record** (IMS buttons only when an IMS record exists; Accept added; Closed needs a
  reason). **W3 evidence shows what was seen and when**, marked available / missing / not applicable; the CA
  judges sufficiency. Both are now in the dashboard design.
- **The bill test measures fields, not time saved.** Label 40 bills by hand first; report correct / wrong / blank
  per field (invoice no., date, GSTIN, amounts), and count wrong dates that passed validation separately (Groq read
  1 Oct as 10 Jan: both valid dates). Time saved needs a CA timed with and without Vouchsafe.
- **Narrow pitch claim:** Vouchsafe asks the person who handled the delivery, attaches the answer to the exact
  invoice, and gives the CA an approval-controlled next step. No "India's first", no unsourced competitor prices.
- **Deferred until the stage path is repeatable:** Twilio, e-invoice QR, GSTR-2B import, extra stage demos.

## 6. Future plan (to 13 Dec)

1. CA dashboard (10 Dec), as above.
2. Accuracy on 40 hand-labelled bill photos shared with written consent (10 Dec), in parallel with 1, on a
   setup whose terms allow it (see 5b). Only the team can collect these.
3. Field evidence: at least one practising CA uses the queue; note which calls or searches it removes.
4. Finish channels: live Telegram run in Hindi, Telugu, Kannada, English; native-speaker check of translations.
5. Hardening (12 Dec): pick one demo persona ("Ramesh, hardware trader" vs "Sri Lakshmi Agro Traders" don't match),
   rehearse the 7-step demo script, record the video, remove any leftover SEBI/DRHP wording from IPO SHERPA reuse.
6. Optional: Telegram answer buttons (arrived / still coming / never ordered); bill photos sent to the bot; the
   owner's "what is being filed in your name" read-back; phone-sized shop screen.
7. After the prototype: WhatsApp once a registered business is verified (or via a WhatsApp provider).

## 7. Rules every agent must keep (from AGENTS.md)

1. The LLM never computes; every figure comes from a rule card or Python. The number guard blocks the rest.
2. Never send unmasked PAN or GSTIN to the LLM in text.
3. Unclear means null; never guess a field.
4. Prepare, never file. No money movement, no automatic Reject, never call a supplier a fraud. Every outward action
   waits for human approval.
5. Label every simulation.
6. Money is `Decimal`; dates are `date`.
7. Every language, not one.
8. Secrets only in the shell or git-ignored `.env`. Commit only when asked; no AI attribution in commits.

## 8. Open questions worth a second opinion

1. **Telegram vs WhatsApp for the pitch.** Will judges mark down a Telegram demo for an India-first product whose
   users live on WhatsApp? Is "channel is a plug-in; production on verified WhatsApp" convincing, or should we also
   try the Twilio WhatsApp sandbox?
2. **Is the CA dashboard the right next piece**, ahead of collecting real bills for the accuracy number?
3. **CA decision step:** are the options (Keep Pending / Reject / Wait / Collect proof / Closed) right for how a
   CA actually works with IMS?
4. **Free-tier LLM risk on stage:** Gemini is often busy (503). Is the fallback chain (3 Gemini models → Groq) plus
   offline replay enough, or should the demo budget for a paid key?
5. **Translation quality** from the lightest Gemini model, pending a native-speaker check.
