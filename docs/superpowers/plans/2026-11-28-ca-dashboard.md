# CA dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One browser page where the owner approves the agent's messages, a Telegram voice reply lands on its case,
and the CA records the tax decision, driving the real `Agent`.

**Architecture:** The agent graph gains a CA decision step after every hand-off, with options worked out from the
actual IMS record. A FastAPI app (`dashboard.py`) wraps one `Agent` and the in-process mock portal, exposes a small
JSON API, optionally listens on Telegram, and serves a built React page that polls every 2 s.

**Tech Stack:** Python 3.12, LangGraph, FastAPI, pytest (offline); React 19 + Vite + Tailwind 4 + lucide-react.

**Spec:** [docs/superpowers/specs/2026-11-27-ca-dashboard-design.md](../specs/2026-11-27-ca-dashboard-design.md)

## Global Constraints

- Branch `dakshan/ca-dashboard` from up-to-date `main`. Commit on the branch as the steps say; **no push or PR
  until Dakshan asks**. No `Co-Authored-By` or any AI attribution in commits or PR text.
- Tests stay offline: no LLM, Sarvam or Telegram call in `pytest`. `uv run pytest -q` green after every task.
- AGENTS.md rules hold: the LLM never computes; no ID in prompt text; prepare, never file; **no automatic Reject**
  (a Reject only on the CA's click); every simulation labelled; `Decimal` money; every language, not one.
- Every API response carries `X-Simulated: true`; the page shows a SIMULATED banner at all times.
- No SEBI, DRHP, ICDR, banker or prospectus wording from IPO SHERPA. Credit reused parts in the README pattern ledger.
- Real messages only to `TELEGRAM_DEMO_CHAT`; only W1 (shop) messages go to Telegram, W2 supplier messages stay
  simulated.
- Desktop/projector layout only. Plain, short words on the page.

## Review Focus

1. Double-click on Approve or a decision: the second request must get 409 and nothing is sent twice (Task 3 test).
2. A Telegram message when no case waits for a reply: logged and ignored, the poll thread keeps running (Task 3).
3. A voice note that fails to transcribe (Sarvam or LLM error): the case keeps waiting, the page shows the error,
   the poll thread survives (Task 3).
4. The mock portal refuses the CA's IMS save: the case goes back to waiting for the CA with `ims.save_failed` in the
   trail, never silently "done" (Task 1).
5. A page left open across Reset, or a stale case id: 404 with a plain message, never a 500 (Task 3).

---

### Task 1: CA decision step in the agent

**Files:**
- Modify: `src/gstagent/agent/graph.py` (`handoff`, new nodes `ca_decide`, `ca_ims`, `ca_close`, edges; `Agent.approve`,
  new `Agent.decide`)
- Modify: `src/gstagent/agent/demo.py` (`drive` answers the CA step; split out `cases_for` and `day_passes`)
- Test: `tests/test_agent.py`

**Interfaces:**
- Produces:
  - Interrupt `{"type": "ca_decision", "text": <hand-off text>, "options": list[str], "record": {"key", "doc_type",
    "action"} | None, "missing": list[str], "sha256": <_sha of the hand-off draft>}`.
    `missing` = evidence-pack document keys not present (W3 only, else `[]`).
  - Choice ids: `accept`, `pending`, `reject`, `wait_supplier`, `follow_up`, `collect_proof`, `closed`.
  - Resume value `{"choice": str, "note": str, "reason": str, "not_applicable": list[str], "sha256": str}`.
  - `Agent.approve(case_id: str, yes: bool = True, sha256: str | None = None) -> dict`: raises
    `ValueError("text changed since shown")` when `sha256` is given and differs from the waiting one.
  - `Agent.decide(case_id: str, choice: str, note: str = "", reason: str = "", not_applicable: list[str] = (),
    sha256: str | None = None) -> dict`: raises `ValueError` when not waiting for `ca_decision`, the hash differs,
    `choice` is not in `options`, `closed` has a blank reason, or `not_applicable` is not a subset of `missing`.
  - `demo.cases_for(portal, shop_lang: str | None = None) -> list[dict]`: resets the portal, reconciles, fires the
    W3 cancellation event, returns the cases sorted by `case_id` (the first half of today's `run`).
  - `demo.day_passes(agent, portal, case_id: str) -> dict`: the existing W2 branch of `drive` (GSTR-1A filed on the
    first day for `W2:B029`/`W2:B030`), then `agent.answer(case_id, {"type": "day_passed"})`.
  - `demo.DEMO_CHOICE = ("pending", "collect_proof", "closed")`, `demo.DEMO_REASON = "Demo: closed by the CA."`.

Options rule (in `ca_decide`): W3 → `["collect_proof", "closed"]`. Otherwise look up
`f"{ctin}|{invoice_no}"` in `GET /mock-gstn/ims?gstin=<PROFILE.gstin>&rtnprd=<period>`: found → each of
`ACCEPTED→accept, PENDING→pending, REJECTED→reject` whose `RULES.evaluate("ims.treatment", period_start(period),
doc_type=<record doc_type>, action=...)` is allowed, then `closed`; not found → `["wait_supplier", "follow_up",
"closed"]`.

Routing: `handoff` → `ca_decide` (and `handoff` no longer sets `outcome`). Invalid resume (hash, choice, blank
`closed` reason) → event `ca.decision_refused`, back to `ca_decide`. Valid → event `ca.decided` with
`"<choice>: <note>"` (plus `not applicable: …` when given), then `accept|pending|reject` → `ca_ims`;
`wait_supplier` → `w2_wait` with `checks` reset to 0; `follow_up` → `w2_ask` with `checks` reset to 0;
`collect_proof|closed` → `ca_close`. `ca_ims` posts the action to `/mock-gstn/ims/save`; non-200 → event
`ims.save_failed`, back to `ca_decide`; 200 → event `ims.ca_saved`, then `case.closed`. Outcome copy, exactly:

| choice | outcome |
|---|---|
| accept | `The CA accepted it in IMS (SIMULATED).` |
| pending | `The CA kept it Pending in IMS (SIMULATED).` |
| reject | `The CA rejected it in IMS (SIMULATED).` |
| collect_proof | `The CA asked for the missing proof.` |
| closed | `Closed by the CA: <reason>` |

- [ ] **Step 1: Write the failing tests** in `tests/test_agent.py`

```python
def to_ca(portal, a=None):  # W1 CP/7781 driven to the CA step
    a = a or agent(portal)
    c = w1_case(); a.open(c)
    a.approve(c["case_id"]); a.answer(c["case_id"], "No, we never ordered this."); v = a.approve(c["case_id"])
    return a, c["case_id"], v

def test_handoff_waits_for_the_ca_with_ims_options(portal):
    _, _, v = to_ca(portal)
    assert v["waiting"]["type"] == "ca_decision" and v["outcome"] is None
    assert v["waiting"]["options"] == ["accept", "pending", "reject", "closed"]
    assert v["waiting"]["record"]["key"] == "29CHCFC7955B1Z0|CP/7781"

def test_ca_pending_is_saved_on_the_mock_ims(portal):
    a, cid, _ = to_ca(portal)
    v = a.decide(cid, "pending", note="ask Manju's manager")
    assert v["outcome"] == "The CA kept it Pending in IMS (SIMULATED)." and v["waiting"] is None
    ims = portal.get("/mock-gstn/ims", params={"gstin": demo.data.load_profile().gstin, "rtnprd": "102026"}).json()
    assert next(r for r in ims["records"] if r["key"] == "29CHCFC7955B1Z0|CP/7781")["action"] == "PENDING"
    assert [e["kind"] for e in v["timeline"]][-3:] == ["ca.decided", "ims.ca_saved", "case.closed"]

def test_ca_closed_needs_a_reason_and_wrong_hash_is_refused(portal):
    a, cid, _ = to_ca(portal)
    with pytest.raises(ValueError): a.decide(cid, "closed")
    with pytest.raises(ValueError): a.decide(cid, "pending", sha256="0" * 64)
    with pytest.raises(ValueError): a.decide(cid, "wait_supplier")      # not offered: the record exists
    assert a.decide(cid, "closed", reason="Duplicate of CP/7780")["outcome"] == "Closed by the CA: Duplicate of CP/7780"

def test_w2_bill_missing_from_2b_gets_no_ims_buttons(portal):
    # the W2 case with facts.problem == "missing_in_2b" that the demo supplier never fixes
    ...  # open it, approve, day_passes x3, approve hand-off
    assert v["waiting"]["options"] == ["wait_supplier", "follow_up", "closed"] and v["waiting"]["record"] is None

def test_ca_wait_for_supplier_goes_back_to_portal_checks(portal):
    ...  # same case: decide("wait_supplier") -> waiting type "event", checks_done 0

def test_w3_ca_options_and_missing_documents(portal):
    ...  # W3 case: approve hand-off -> options ["collect_proof", "closed"], "toll_receipt" in waiting["missing"]
    # decide("collect_proof", not_applicable=["weighbridge_slip"]) -> outcome "The CA asked for the missing proof."

def test_refused_ims_save_goes_back_to_the_ca(portal, monkeypatch):
    a, cid, _ = to_ca(portal)
    real = portal.post
    monkeypatch.setattr(portal, "post", lambda url, **kw: httpx.Response(503, text="portal down")
                        if url.endswith("/ims/save") else real(url, **kw))
    v = a.decide(cid, "reject")
    assert v["waiting"]["type"] == "ca_decision" and v["outcome"] is None
    assert v["timeline"][-1]["kind"] == "ims.save_failed"
```

Update the existing tests for the new ends: in `test_all_three_workflows_run_end_to_end_twice_in_a_row`, W1 ends
`"The CA kept it Pending in IMS (SIMULATED)."`, W3 ends `"The CA asked for the missing proof."`, W2:B031/B032 end
with the `DEMO_CHOICE` outcome their options allow. In `test_every_outward_action_comes_right_after_an_owner_approval`,
also assert every `ims.ca_saved` comes right after a `ca.decided`. `test_w1_unclear_twice_goes_to_the_ca` now
expects `waiting["type"] == "ca_decision"`.

- [ ] **Step 2: Run** `uv run pytest tests/test_agent.py -q` — Expected: the new tests FAIL (`AttributeError: decide`).
- [ ] **Step 3: Implement** the nodes, routing and `Agent.decide`/`approve(sha256=)` in `graph.py` as above; in
  `demo.py` add `cases_for`, `day_passes`, and a `ca_decision` branch in `drive` that picks the first of
  `DEMO_CHOICE` in `options` (reason `DEMO_REASON` for `closed`). `drive` never picks `reject`.
- [ ] **Step 4: Run** `uv run pytest -q` — Expected: all PASS.
- [ ] **Step 5: Commit** `git add src/gstagent/agent tests/test_agent.py && git commit -m "Agent: CA decision step after hand-off, options from the IMS record"`

### Task 2: W3 evidence says what was seen and when

**Files:**
- Modify: `src/gstagent/agent/graph.py` (`w3_assess` text lines only)
- Test: `tests/test_agent.py` (`test_w3_lists_exposed_bills_with_snapshots_and_evidence`)

**Interfaces:**
- Consumes: `snapshots.take()` → `gstr2b_period`, `taken_at`, `source`, `in_gstr2b`, `sha256` (unchanged).
- Produces: per-bill line, exactly:
  `- {inv} dated {dd-mm-yyyy}, GST {₹}. GSTR-2B for {MM-YYYY}, observed {dd-mm-yyyy} (SIMULATED): {reported|not reported}
  (snapshot {12 hex}). Status on the purchase date: not available. Available: {document names, "; "}.`
  Document names come from the `itc.evidence_pack` card's `documents` params. The card's explanation (missing list)
  stays once at the end, as now.

- [ ] **Step 1: Update the test**: assert the hand-off text contains `"observed "`, `"(SIMULATED)"`,
  `"Status on the purchase date: not available."`, and does **not** contain `"At purchase"`.
- [ ] **Step 2: Run** `uv run pytest tests/test_agent.py -q -k w3` — Expected: FAIL.
- [ ] **Step 3: Implement** the new line in `w3_assess`; add the new figure strings (period, observed date) to
  `extra` so the number guard allows them.
- [ ] **Step 4: Run** `uv run pytest -q` — Expected: all PASS.
- [ ] **Step 5: Commit** `git commit -am "W3: evidence shows when the portal was observed, not 'at purchase'"`

### Task 3: Dashboard API

**Files:**
- Create: `src/gstagent/dashboard.py`
- Test: `tests/test_dashboard.py`

**Interfaces:**
- Consumes: `Agent` (Task 1), `demo.cases_for`, `demo.day_passes`, `demo.SCRIPTED`, `demo.offline_translate`,
  `demo.TODAY`, `live.deliver`, `live.heard`, `telegram.poll`, `RULES.get(rule_id, on).title/.citations`.
- Produces:
  - `make_app(lang: str = "ta-IN", channel: str = "none", live: bool = False) -> FastAPI`. `channel="telegram"`
    implies live LLM calls and starts `telegram.poll(app.state.on_message)` in a daemon thread on startup (not in
    tests). `channel="none"` uses `demo.SCRIPTED` classify and `demo.offline_translate` unless `live`.
  - `app.state.on_message(m: dict) -> None`: Telegram message → `live.heard(m)` → `agent.answer` on the one case
    waiting for a reply; none waiting → log and ignore; any `live.ERRORS` → store in `app.state.last_error`, case
    keeps waiting. A reply that came from a voice note is remembered per case, so the detail can tag it.
  - Deliver wrapper: `live.deliver(item)` only when `item["voice"]` (W1 shop message); otherwise return
    `"simulated channel (one phone on stage)"`.
  - One `threading.Lock` around every agent call. Agent db `":memory:"`; reset builds a fresh `Agent`.
  - Routes (`{case_id:path}` because ids contain `|` and `/`):
    - `GET /api/clients` → `[{"name": PROFILE.trade_name, "active": true}, {"name": "Kaveri Textiles (sample)", "active": false}, {"name": "Nandini Medicals (sample)", "active": false}]`
    - `GET /api/cases` → `{"cases": [{"case_id", "workflow", "title": "<supplier> <invoice_no>", "status", "outcome"}],
      "readiness": {"resolved": int, "total": int}, "channel": str, "lang": str, "last_error": str | None}`.
      `status` from `waiting.type`: `approval→waiting_approval`, `reply→waiting_reply`, `event→waiting_supplier`,
      `ca_decision→waiting_ca`, none → `resolved`, except an outcome starting `Owner declined` → `declined`
      (the mismatch is still there, so it is not ready). `resolved` counts only `resolved`.
    - `GET /api/cases/{case_id}` → `Agent.view()` + `"facts"` + `"voice_replies": list[str]` (reply texts heard
      from voice notes) + `"rules": [{"id", "title", "citations"}]` from
      `{"W1": ["ims.treatment"], "W2": ["itc.time_limit_16_4", "itc.gstr1a_flow"], "W3": ["itc.evidence_pack"]}`.
    - `POST /api/cases/{case_id}/approve` `{"approve": bool, "sha256": str}`
    - `POST /api/cases/{case_id}/decide` `{"choice", "note", "reason", "not_applicable", "sha256"}`
    - `POST /api/cases/{case_id}/reply` `{"text": str}` (only when waiting for a reply)
    - `POST /api/cases/{case_id}/day` (only when waiting for the supplier) → `demo.day_passes`
    - `POST /api/reset`
    - Unknown case → 404; wrong state or stale hash → 409; invalid decision → 422 (`ValueError` text as `detail`).
    - Middleware adds `X-Simulated: true`. If `frontend/dist` exists, mount it at `/` with `StaticFiles(html=True)`
      after the API routes.
  - `main(argv)` with `--lang` (choices `language.LANGUAGES`, default `ta-IN`), `--channel {none,telegram}`
    (default `none`), `--live`, `--port 8000`; checks Telegram settings first like `live.main`; runs uvicorn.

- [ ] **Step 1: Write the failing tests** in `tests/test_dashboard.py` (fixture: `TestClient(make_app())`,
  reset the mock portal before and after, as in `test_agent.py`)

```python
W1 = "W1:29CHCFC7955B1Z0|CP/7781"
TAMIL = demo.REPLIES["ta-IN"]

def waiting(c, cid): return c.get(f"/api/cases/{cid}").json()["waiting"]

def test_lists_every_case_with_status_and_readiness(client):
    r = client.get("/api/cases"); body = r.json()
    assert r.headers["X-Simulated"] == "true" and len(body["cases"]) == 6
    assert body["readiness"] == {"resolved": 0, "total": 6}
    assert all(c["status"] == "waiting_approval" for c in body["cases"])

def test_stage_path_from_question_to_ca_decision(client):
    sha = waiting(client, W1)["sha256"]
    assert client.post(f"/api/cases/{W1}/approve", json={"approve": True, "sha256": sha}).status_code == 200
    assert client.post(f"/api/cases/{W1}/reply", json={"text": TAMIL}).status_code == 200
    w = waiting(client, W1); client.post(f"/api/cases/{W1}/approve", json={"approve": True, "sha256": w["sha256"]})
    w = waiting(client, W1)
    assert w["type"] == "ca_decision" and "pending" in w["options"]
    r = client.post(f"/api/cases/{W1}/decide", json={"choice": "pending", "note": "", "reason": "",
                                                     "not_applicable": [], "sha256": w["sha256"]})
    assert r.json()["outcome"] == "The CA kept it Pending in IMS (SIMULATED)."
    assert client.get("/api/cases").json()["readiness"]["resolved"] == 1

def test_double_click_and_stale_hash_get_409_and_send_nothing(client): ...
    # approve twice with the same sha: first 200, second 409; outbox has one item
def test_closed_without_reason_is_422(client): ...
def test_reply_when_not_waiting_for_one_is_409(client): ...
def test_unknown_case_is_404(client): ...           # also after POST /api/reset
def test_case_detail_has_facts_and_cited_rules(client): ...   # W1: facts.invoice_no == "CP/7781", rules[0].id == "ims.treatment"
def test_day_passes_lets_a_supplier_fix_it(client): ...       # W2:B029: approve, day -> status resolved, outcome "Supplier fixed it..."
def test_telegram_reply_goes_to_the_waiting_case(client): ... # app.state.on_message({"type": "text", "text": TAMIL, ...})
def test_telegram_voice_reply_is_tagged(client, monkeypatch): ...  # live.heard patched to return TAMIL for an audio message -> voice_replies == [TAMIL]
def test_declined_case_is_not_ready(client): ...  # approve False on W1 -> status "declined", readiness resolved 0
def test_telegram_message_with_no_case_waiting_is_ignored(client): ...
def test_failed_voice_note_keeps_the_case_waiting(client, monkeypatch): ...  # live.heard raises voice.VoiceError -> last_error set
def test_only_shop_messages_go_to_telegram(monkeypatch): ...  # make_app(channel="telegram") with live.deliver patched: W2 send not delivered
```

- [ ] **Step 2: Run** `uv run pytest tests/test_dashboard.py -q` — Expected: FAIL (`ModuleNotFoundError`).
- [ ] **Step 3: Implement** `src/gstagent/dashboard.py` per the Interfaces block. Module docstring gives the run
  commands and says what is real and what is simulated, like `live.py`.
- [ ] **Step 4: Run** `uv run pytest -q` — Expected: all PASS.
- [ ] **Step 5: Commit** `git add src/gstagent/dashboard.py tests/test_dashboard.py && git commit -m "Dashboard API over the live agent"`

### Task 4: Page: layout, queue and readiness

**Files:**
- Create: `frontend/package.json` (deps as IPO SHERPA's: `react`/`react-dom` ^19.2.7, `lucide-react` ^1.23.0; dev:
  `vite` ^8.1.1, `@vitejs/plugin-react` ^6.0.3, `tailwindcss` + `@tailwindcss/vite` ^4.3.2), `frontend/vite.config.js`
  (react + tailwind plugins; dev proxy `/api` → `http://localhost:8000`), `frontend/index.html` (title "Vouchsafe: CA
  workspace"), `frontend/src/main.jsx`, `frontend/src/index.css` (`@import "tailwindcss";`), `frontend/src/api.js`,
  `frontend/src/App.jsx`, `frontend/src/components/{ClientList,Readiness,CaseQueue}.jsx`
- Copy and adapt from `/home/dakshan/Projects/Automated-IPO-Drafter/frontend/src/components/`: `ui/Card.jsx`,
  `ui/Badge.jsx`, `ui/StatTile.jsx` → `frontend/src/components/ui/`; `ComplianceScoreMeter.jsx` → `Readiness.jsx`.
  Remove any SEBI/DRHP/banker wording.
- Modify: `.gitignore` (add `node_modules/`)

**Interfaces:**
- Consumes: Task 3 routes.
- Produces: `api.js` exports `getCases()`, `getCase(id)`, `getClients()`, `post(path, body)`; every case id is
  `encodeURIComponent`-ed. `App.jsx` holds `selectedId`, polls `getCases()` and the open case every 2000 ms.

Layout: SIMULATED banner across the top (text: `SIMULATED: mock GST portal and fictional data.` plus
`Telegram messages are real and go only to the demo chat.` when `channel == "telegram"`, else
`Messages are simulated.`); left client list (dummies greyed, not clickable); top readiness meter
(`resolved of total ready`) and stat tiles (Open, Waiting on you = `waiting_approval` + `waiting_ca`, Waiting on others
= `waiting_reply` + `waiting_supplier`, Resolved); middle queue table: workflow badge, title, issue, status badge.
Status labels: `Waiting for approval`, `Waiting for reply`, `Waiting for supplier`, `Waiting for the CA`, `Resolved`,
`Declined`.

- [ ] **Step 1:** `cd frontend && npm install` — Expected: no errors.
- [ ] **Step 2:** Write the files above.
- [ ] **Step 3:** `npm run build` — Expected: `frontend/dist/index.html` exists, no errors.
- [ ] **Step 4:** Start `uv run python -m gstagent.dashboard` (via the Browser preview with a `.claude/launch.json`
  entry), open `/`: six cases, readiness `0 of 6`, banner visible; clicking a row selects it.
- [ ] **Step 5: Commit** `git add frontend .gitignore && git commit -m "Dashboard page: queue, readiness, clients"`
  (`frontend/dist` and `node_modules` stay untracked).

### Task 5: Page: case detail, approvals and CA decisions

**Files:**
- Create: `frontend/src/components/{CaseDetail,DecisionPanel,DemoControls}.jsx`
- Copy and adapt: `AuditTrail.jsx` (timeline items are `{at, kind, summary}`)

**Interfaces:**
- Consumes: `getCase`, `post` (Task 4); detail shape from Task 3.

Detail panel, top to bottom: reason and cited rules (`rules[].title` and citations); the waiting approval: text in
the recipient's language, English beside it (`text_en`) when different, `note` if any, buttons
`Approve as owner (demo)` / `Approve as CA` (from `approver`) and `Decline`, each posting the shown `sha256`;
for `ca_decision`: the hand-off text, one button per option with labels
`accept: Accept in IMS`, `pending: Keep Pending in IMS`, `reject: Reject in IMS`, `wait_supplier: Wait for the supplier`,
`follow_up: Follow up again`, `collect_proof: Collect the missing proof`, `closed: Close`, a note box, a reason box
required for Close, and for W3 a checklist of `missing` documents marked "not applicable" → `not_applicable`;
replies from the timeline (`shop.replied`), tagged `voice note` when the text is in `voice_replies`; proof: W3 snapshots (period, observed time, reported or not, hash) and
`missing`; the audit trail. Buttons disable while a request runs. A 409/422/404 shows its `detail` as a toast.
Demo controls (labelled "Demo"): `A day passes` when `waiting.type == "event"`, `Type a reply` when `reply`,
`Reset scenario`. `last_error` shows as a toast.

- [ ] **Step 1:** Write the components.
- [ ] **Step 2:** `npm run build` — Expected: no errors.
- [ ] **Step 3:** In the preview, run the stage path offline: approve W1 → type the Tamil demo reply → approve the
  hand-off → Keep Pending → case shows Resolved, readiness `1 of 6`, trail ends `ca.decided`, `ims.ca_saved`,
  `case.closed`. Then W2 missing-from-2B: three `A day passes` → only Wait / Follow up / Close offered. Then Close
  with no reason shows the 422 toast. Screenshot the page.
- [ ] **Step 4: Commit** `git add frontend && git commit -m "Dashboard page: case detail, approvals, CA decisions"`

### Task 6: Docs, then the live rehearsal

**Files:**
- Modify: `README.md` (run command, layout, pattern-ledger credit for the reused IPO SHERPA parts), `PLAN.md`
  (10 Dec row status, Progress log entry), `CHANGELOG.md` (`[Unreleased]`), `AGENTS.md` (test count, dashboard
  command), `docs/SPEC.md` (W3 row: "observed on" wording and "status on the purchase date: not available";
  CA decision step), `docs/PROGRESS-LOG.md` (section 5 → built).

- [ ] **Step 1:** Update the docs. Run `uv run pytest -q` and put the real count in AGENTS.md.
- [ ] **Step 2:** Live rehearsal with Dakshan's phone:
  `uv run python -m gstagent.dashboard --lang ta-IN --channel telegram` → approve W1 on the page → Telegram voice
  note arrives → reply by voice in Tamil → the reply shows on the case → hand-off → Keep Pending. Repeat 3 times; log
  each run's time, which LLM answered, and any manual step in the PLAN.md Progress log.
- [ ] **Step 3: Commit** `git add -A README.md PLAN.md CHANGELOG.md AGENTS.md docs && git commit -m "Docs: CA dashboard"`.
  Push and PR only when Dakshan asks.

## Not in this plan (follow-ups)

- `itc.evidence_pack` card v2: check the document list against the judgment (para 103(vi)) and drop "X of 7"
  framing. Law-facing, needs its own version and citations.
- Date ambiguity guard (1 Oct read as 10 Jan): ask before chasing a supplier.
- The 40-bill labelled accuracy test; Hindi/Kannada live runs; the phone-sized shop screen.
