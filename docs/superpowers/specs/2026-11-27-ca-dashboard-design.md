# CA dashboard: design

Date: 2026-11-27 · Milestone: 10 Dec "CA dashboard + accuracy" (PLAN.md) · Owner: Dakshan

## Why

Judges watch a screen. Today the agent runs only in a terminal: approvals are typed `y`, replies show as printed
lines. The dashboard is the CA's workspace, where the paying customer sees each client's open cases and approves
the next step. It is also the stage for the demo's "agent at work" moment: a click on Approve really sends the
Telegram question, Manju's voice reply appears on the page, and the CA hand-off follows.

## Goals

- One page that shows every open case of the demo client with: issue, plain reason, cited rule, what the agent is
  waiting for, the draft waiting for approval (in the recipient's language with English beside it), the reply, the
  proof, and the case's audit trail.
- Approve / Decline on the page drives the **live** agent (same `Agent` as `channels/live.py`), including sending on
  Telegram with a Sarvam voice note.
- Telegram replies (typed or voice) land in the right case without a page refresh.
- A readiness meter for the period: cases closed or handed to the CA out of all cases. *(Builder's call)* A declined
  case is not ready: the mismatch is still there.
- One command starts everything; one browser tab shows it.

## Non-goals (for 10 Dec)

- Login, accounts, multi-user, real client data. One synthetic client; the client list shows 2–3 dummy clients
  beside it, clearly not clickable.
- Tally export, Q&A copilot, notice check, rule-change alert (cut order in PLAN.md).
- Filing a return or any real IMS action: the CA decision is saved on the mock portal only.
- The phone-sized `Shop.jsx` screen and the owner's filing read-back: a separate change after this one.
- Bill-photo upload on the dashboard (the CA-queue API already takes photos; wiring it in comes later).
- Mobile layout. Desktop/projector only.

## Anti-goals (failure even if it works)

- Anything that looks like a GSTN/CBIC screen or a filed return. Every simulated thing labelled SIMULATED.
- Any number on the page that the rules or Python did not compute (the agent's drafts already pass the number
  guard; the page adds no computed figures except the readiness count).
- SEBI, DRHP, ICDR, banker or prospectus wording carried over from IPO SHERPA.
- Hard-coding one language: drafts show in the recipient's language plus English.
- A click that sends a message without the exact text the user saw (approvals stay hash-bound).

## Constraints

- Stack per SPEC §6: React 19 + Vite + Tailwind 4, lucide icons; backend Python 3.12 + FastAPI.
- Reuse from IPO SHERPA (`/home/dakshan/Projects/Automated-IPO-Drafter/frontend/src/components`) only the small
  parts: `ui/Card.jsx`, `ui/Badge.jsx`, `ui/StatTile.jsx`, `AuditTrail.jsx`, `ComplianceScoreMeter.jsx` (→ readiness
  meter), and the table layout of `BankerDashboard.jsx` (→ exception queue). Not `App.jsx` (SEBI wording, Supabase),
  not `Wizard.jsx`. Credit in the README pattern ledger.
- Tests stay offline (AGENTS.md). Prototype rule: real messages only to `TELEGRAM_DEMO_CHAT`.
- Fictional data only.

## Approaches considered

1. **React page + FastAPI over the agent, served as one app** (picked). Page reuses the IPO SHERPA kit; built
   files served by the same FastAPI app; page polls every ~2 s. Costs a Node build step.
2. Plain server-rendered HTML from FastAPI, no React. Quicker, no Node, but cannot reuse the UI kit and looks
   plainer; judges judge the screen. Dropped.
3. Streamlit. Generic look, awkward step-by-step approvals. Dropped.

Live vs replay: **live** picked (the dashboard drives the real agent); a replay viewer was quicker but inert.

## Design (decided)

**Who approves what (decided 27 Nov):** the **owner** approves what goes out in the shop's name (messages to staff
and suppliers, an IMS Pending the agent recommends); on stage the button reads "Approve as owner (demo)". The
**CA** makes the tax decision on every case handed to them. This adds one step to the agent:

- After `handoff`, the case waits for a **CA decision** (`interrupt({"type": "ca_decision", "options": [...],
  "sha256": ...})`, bound to the hand-off text the CA saw) instead of ending.
- **Options come from the actual record, not the workflow** (revised 27 Nov after the Gemini / Claude / ChatGPT
  cross-check). IMS buttons show only when the supplier's record is in IMS; a bill that is only in the shop's
  books has no IMS action. The note is optional; **Closed** needs a reason.
  - IMS record exists (W1 "never ordered"; W2 after the supplier files GSTR-1A): **Accept** / **Keep Pending** /
    **Reject**, plus **Closed** with a reason.
  - No IMS record (W2 supplier still has not reported the bill): **Wait for the supplier** (back to the W2 wait
    loop) / **Follow up again** / **Closed** with a reason. No IMS buttons.
  - W3 exposed purchases: **Collect the missing proof** / **Closed, proof is enough** (with a reason).
  - Not in this round: the limited-period Pending rule for specific records (credit notes etc.), RCM bills.
- Pending, Accept and Reject are saved on the mock portal's IMS (`/mock-gstn/ims/save`, already validated by the
  `ims.treatment` card), labelled SIMULATED. A Reject only ever happens on this CA click, never automatically
  (AGENTS.md rule 4 still holds: the agent never rejects; the CA does).
- Statuses keep **Waiting for the CA** and **Resolved** apart, so the readiness count never treats a hand-off as
  done.
- **W3 evidence shows what was seen and when**, not a verdict. Each document is **available / missing / not
  applicable**; the CA judges if it is enough (Shaurya Alloys gives examples, not a fixed checklist). Portal facts
  read "In GSTR-2B for 2026-10, observed 27 Nov 2026 (SIMULATED)" from the snapshot's `gstr2b_period`, `taken_at`
  and `source`, and "Status on the purchase date: not available" when no snapshot was taken then. No claim about
  the supplier's registration status: a GSTR-2B entry is not a registration check.
- Audit trail gets `ca.decided` with the choice and note; the case outcome says what the CA decided.
- Changes `agent/graph.py`, `agent/demo.py` (`drive` answers the CA step), `tests/test_agent.py`, and the
  number-guard allow-list if the note is shown in a later message (it is not sent to anyone).

**Backend: `src/gstagent/dashboard.py`** (FastAPI app, run with
`uv run python -m gstagent.dashboard --lang ta-IN [--channel telegram|none] [--live]`):

- On start: reset the in-process mock portal, build the cases exactly as `agent/demo.py` `run()` does (5 match cases +
  the W3 cancellation), open each in one `Agent` (SQLite file under `data/`, or `:memory:`). `--channel telegram`
  passes `live.deliver` and starts `telegram.poll`; `none` keeps the channel simulated (for rehearsal and tests).
- *(Builder's call)* Modes: `--channel telegram` always uses the real LLM (translate + read replies).
  `--channel none` (default, rehearsal and tests) uses the offline stand-ins from `agent/demo.py` unless `--live`
  is given, so rehearsal needs no keys and starts instantly.
- *(Builder's call)* Only messages to the shop (W1) go out on Telegram; supplier messages (W2) stay simulated and
  are labelled so, because the demo has one phone and a supplier message there would confuse the W1 reply routing.
- One lock around every agent call (LangGraph + SQLite, background reply thread).
- Endpoints (JSON):
  - `GET /api/clients` → demo client + dummy clients.
  - `GET /api/cases` → per case: id, workflow, title, status (waiting approval / waiting reply / waiting supplier /
    closed / handed to CA), outcome, and the readiness count.
  - `GET /api/cases/{id}` → `Agent.view()` plus the case's facts needed for display (supplier, invoice, reason,
    cited rule ids).
  - `POST /api/cases/{id}/approve` `{approve: bool, sha256}` → `Agent.answer` with the hash the page showed;
    mismatched hash is refused.
  - `POST /api/cases/{id}/reply` `{text}` → typed reply for rehearsal without a phone.
  - `POST /api/cases/{id}/day` → demo control for W2: "a day passes"; on the first day for the cases `demo.py` uses,
    the mock supplier files GSTR-1A (same as `demo.drive`).
  - `POST /api/reset` → start the scenario again.
- A Telegram reply goes to the one case currently waiting for a reply (W1). If none waits, it is logged and ignored.
- Every response carries `X-Simulated: true`; the page shows a SIMULATED banner for portal and data.
- Serves the built page from `frontend/dist` at `/`.

**Frontend: `frontend/`** (Vite project in this repo; `npm run build` → `frontend/dist`, git-ignored):

- Left: client list (demo client active, dummies greyed). Top: readiness meter + stat tiles (open, waiting on you,
  waiting on others, closed).
- Middle: exception queue table, one row per case: workflow badge, supplier + invoice, issue, status badge.
- Right / detail panel for the selected case: reason and cited rule; the waiting draft in the recipient's language
  with English beside it and "Approve as owner (demo)" / "Approve as CA" (from the draft's `approver`) + Decline;
  for a case handed to the CA, the decision buttons and a note box; replies (with "voice note" tag when it
  came from speech); proof (W3 evidence: present / missing documents and
  snapshot hashes; bill details for W1/W2); audit trail (reused `AuditTrail.jsx`).
- Polls `/api/cases` and the open case every 2 s; buttons disable while a request runs (sending + voice takes
  a few seconds).
- Demo controls (small, labelled "Demo"): "A day passes" on W2 cases, "Type a reply" on W1, "Reset scenario".

## Stage path (the one that must work every time)

CP/7781 (W1, Chamundi Packaging, in 2B but not in the books): approve the Telegram question as owner → Tamil (or any language) voice reply lands
on the case → hand-off → the CA picks Keep Pending or Reject → audit trail shows it. Everything else on the page
is supporting. Rehearse it repeatedly and note each run's time, which LLM answered, and any manual step; keep a
labelled replay as backup.

## Left to the builder

- Exact component split, styling, colours (keep it calm and readable on a projector), polling details.
- How dummy clients look; empty states; error toasts.
- Test shape: FastAPI `TestClient` tests of every endpoint with the simulated channel and offline translate/classify;
  no frontend test framework unless cheap.
- Where the SQLite file lives and whether reset deletes it.
