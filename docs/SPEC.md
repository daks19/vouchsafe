# Vouchsafe: product spec (prototype round)

Tech4Bharat 2026 · Theme 3 (MSME Finance and Compliance) · PS 3.1 · Agentic AI track
Team Neo Frontier: Dakshan Kumar S (lead), Adithyan Benoy, Sachin Saravanan, Shaisanjai P
Status: shortlisted for prototyping on 24 Nov 2026. **Prototype deadline 13 Dec 2026.** Finale 27 Dec, Bangalore Palace.
Repo: https://github.com/daks19/vouchsafe · Deck: `Vouchsafe - Neo Frontier final v4.pdf` (13 slides) and form text `HackCulture idea submission.md` are in the team's shared folder, not in this repo
Last updated 26 Nov 2026 to match the submitted deck and form.

## 1. The product in one line

**Vouchsafe is an agentic AI assistant that helps small GST-registered traders and their accountants sort out purchase invoices that don't match, in the trader's own language.** Shops send bill photos and voice notes on WhatsApp. Claude reads the bills, tested rules match them against GSTR-2B and IMS, and for every mismatch the agent asks the person who received the goods, by voice, before the invoice is deemed accepted. It follows up with suppliers and keeps proof of every purchase. It prepares; the owner or the CA approves and files. It never touches money.

## 2. Who it is for

| Role | Who | What they get | Pays? |
|---|---|---|---|
| Primary user | Micro trader or small manufacturer, ₹40 lakh–₹3 crore turnover, B2B purchases from many suppliers, often QRMP | Voice questions in their own language, a read-back before filing, proof kept for years | No, free |
| Confirmer | Shop staff who receive goods (e.g. "Manju") | One voice note or tap: "did this arrive?" | No |
| Paying customer | Part-time accountant or CA with 30–80 clients | Sorted bills, an exception-only queue, evidence packs, Tally export | Yes, flat workspace: ₹499 a month for up to 25 clients, ₹999 for up to 75 (a guess to test) |
| Assisted channel | Local helper at a digital service centre such as JanAI Café | Scans the bag of bills for shops that want help | Earns per verified intake (mocked: no public API) |

Demo persona: Ramesh, hardware trader in Mysuru, ₹80 lakh turnover, 25 suppliers, quarterly filer. Illustrative only, not an interviewee.

## 3. What it does

### Three core workflows (60% or more of the demo)

| # | Workflow | Trigger | What the agent does | Ends with |
|---|---|---|---|---|
| W1 | **Confirm the delivery** | A GSTR-2B / IMS line with no matching bill | Sends a voice note to whoever received the goods: "₹73,160 from Chamundi Packaging, invoice CP/7781: did this order arrive?" Three answers: arrived / still coming / never ordered | Arrived, no bill: ask for the bill photo. Still coming: recommend IMS Pending before GSTR-2B is generated. Never ordered: CA exception, the CA decides on Reject. One staff "no" is never proof. Never an automatic Reject, never called fraud |
| W2 | **Supplier correction** | Amount mismatch, or an invoice missing from 2B | With the owner's OK, messages the supplier naming the exact invoice and fix, checks IMS daily for the GSTR-1A, re-matches. The GSTR-1A shows in IMS once saved, but its credit lands in the next GSTR-2B (`itc.gstr1a_flow`) | Case closes itself, or goes to the CA with the IMS status and the Section 16(4) date. For a QRMP buyer the practical cutoff is the Jul–Sep GSTR-3B, not 30 Nov (`itc.time_limit_16_4`) |
| W3 | **Keep purchase evidence** | A supplier's registration is cancelled with a past effective date | Lists invoices dated on or after that date, works out the exposure, and records what GSTR-2B showed and when it was observed | An evidence pack with the kinds of proof the *Shaurya Alloys* judgment points to (invoices, e-way bills, transport receipts, weighbridge slips, bank payment proof), marking what's present and missing (`itc.evidence_pack`); the CA can mark a missing item not applicable and judges whether it is enough. Persuasive outside Punjab and Haryana; guarantees nothing. "Status on the purchase date: not available" unless a snapshot was taken then |

### Supporting features (shown briefly)

- **Correct supplier reading:** a composition supplier means "no credit on this bill", not "risky". A QRMP supplier files quarterly. Reverse-charge records are outside IMS.
- **Hygiene:** WhatsApp bill intake with read-back, CA dashboard, Tally export, number guard, hash-bound approvals.
- **Optional, cut first:** guided notice check (RFN/DIN), "rule changed" alert, "explain this exception" Q&A.

### What it never does

Files a return, holds or moves money, auto-rejects an invoice, stores the GST password or OTP, calls a supplier a fraud, advises holding back GST, states a number the rules did not compute, or sends unmasked GSTIN/PAN in text to the LLM.

## 4. Architecture (as shown on deck slides 9–10)

```
WhatsApp photo / voice / PDF ─┐
GSTR-2B + IMS (GSP; mock now) ┼─► 1 Collect ─► 2 Claude vision reads bill ─► 3 Python validators ─► 4 Matcher + rule cards
                              │                                                                         │
                              │        ┌────────────────────────────────────────────────────────────────┘
                              │        ▼
                              │   5 Plan (LangGraph) ─► 6 Ask by voice (Sarvam TTS + STT) ─► 7 Claude reads reply, agent acts
                              │        ▲                                                         │
                              │        └──── waits for events: supplier saves GSTR-1A, cancellation backdated (mock) ◄┘
                              │
                              └──► 8 Follow up and hand off: CA dashboard · evidence pack · Tally export · audit log
```

Step by step:

1. **Collect** (WhatsApp Cloud API in production; a Telegram bot in the prototype, because Meta needs a verified business first): bill photos, PDFs and voice notes to the business number. GSTR-2B and IMS come through a GSP in production, the mock portal in the prototype.
2. **Read the bill** (Claude vision): photo → fixed JSON fields (supplier, GSTIN, invoice no., date, taxable value, tax, total, HSN) with a confidence per field. Unclear fields stay blank, never guessed.
3. **Check the fields** (Python validators): GSTIN check digit (built), state-code vs CGST/SGST or IGST split, arithmetic, duplicate photo (image hash, built). A failed check asks for a clearer photo. Tesseract is the offline backup for GSTIN and totals only.
4. **Match and apply rules** (built): 4-tier matcher against GSTR-2B and IMS; rule cards work out credit at risk and each deadline.
5. **Plan** (LangGraph): one case per mismatch; who must answer what, by when, working back from the GSTR-2B date.
6. **Ask by voice** (Sarvam): text-to-speech voice note in the person's language, tap buttons as fallback; speech-to-text (`saaras:v3`) on the reply, 22 Indian languages plus English, code-mixed speech included.
7. **Understand and act** (Claude + LangGraph): Claude classifies the reply and pulls out any amount or date; amounts are read back. The agent asks for the bill, recommends Pending, or messages the supplier after the owner's OK.
8. **Follow up and hand off** (LangGraph + CA dashboard): waits days if needed, re-checks, escalates a silent supplier, hands each case to the CA with replies, photos and proof. The case then waits for the CA's decision: Accept / Keep Pending / Reject in IMS only when the supplier's record is in IMS (and the rule card allows it), otherwise Wait for the supplier / Follow up again; Close needs a reason. A Reject only ever happens on the CA's click.

**Memory and approvals:** LangGraph checkpointer (SQLite) saves every case, so the agent can wait days and resume; `interrupt()` before every outbound message, IMS action or hand-off.
**Guardrails:** Claude reads, listens and writes but never calculates; the number guard (`guard.py`, built) blocks any figure the rules didn't compute; GSTIN/PAN masked in text sent to the LLM; bill photos read only with the owner's consent; every portal action labelled SIMULATED.

## 5. Where each piece comes from

Three sources: **gst-agent** (built: this repo), **IPO SHERPA** (the team's earlier project, adapt with credit), and **new** work.

| Component | Source | File(s) | What changes |
|---|---|---|---|
| Rule engine: effective-dated, cited, tested cards | gst-agent | `src/gstagent/rules/` (24 card versions, 137 tests) | Keep |
| Bill ↔ GSTR-2B matcher, 4 tiers | gst-agent | `src/gstagent/matcher.py` | Keep |
| Mock GST portal (2B, IMS, GSTR-1A event) | gst-agent | `src/gstagent/mock_gstn/app.py` | Add a "cancellation backdated" event |
| GSTIN checksum and repair | gst-agent | `src/gstagent/gstin.py` | Keep |
| Number guard | gst-agent | `src/gstagent/guard.py` | Keep; optionally port lakh/crore normalisation from IPO SHERPA's `hallucination_guard.py` |
| Bill extraction | **New** | `extract.py` | Claude vision with a strict JSON schema, then the validators. Replaces the PaddleOCR chain |
| LLM client | IPO SHERPA | `backend/llm_client.py` | Optional: provider wrapper, Anthropic as default |
| Supplier name matching, legal vs trade name | IPO SHERPA | `backend/nlp_analyzer.py` → `nlp_semantic_match` | Match "Laxmi Steels" to "Sri Laxmi Steel Traders" |
| Evidence-pack completeness | IPO SHERPA | `backend/coverage.py` | Requirements become the Shaurya Alloys proof list |
| Approvals with states | IPO SHERPA | `backend/certification.py` | Becomes CA case approval (draft → reviewed → approved), hash-bound |
| Audit log, append-only | IPO SHERPA | `backend/audit_log.py` | Actions: `case.open`, `shop.asked`, `supplier.messaged`, `ims.recommended`, `ca.approved` |
| Evidence pack / hand-off documents | IPO SHERPA | `backend/generator.py`, `exporter.py` | Short PDF evidence pack; zip becomes the CA hand-off |
| Frontend shell and UI kit | IPO SHERPA | `App.jsx`, `Dashboard.jsx`, `AuditTrail.jsx`, `ui/*` | Dashboard → CA client list; score meter → period readiness |
| CA exception queue | IPO SHERPA, adapted | `BankerDashboard.jsx` | Rows: issue, reason, cited rule, recommended action, Approve / Ask again |
| **Agent loop** | **New** | `agent/` (LangGraph) | The heart of "Agentic AI" |
| **Messaging channel + voice** | **New** | `channels/telegram.py`, `channels/whatsapp.py`, `channels/voice.py` | Telegram bot for the prototype; WhatsApp Cloud API once the business is verified; Sarvam STT/TTS behind one adapter |
| **Supplier snapshots** | **New** | `snapshots.py` | Status and filing data per bill, with timestamp and hash, from what GSTR-2B shows (GSP search in production, mocked) |
| **Shop screens** | **New** | `Shop.jsx` (phone-sized) | Fallback for WhatsApp: "Did this arrive?" and the read-back |

**Drop from IPO SHERPA:** PaddleOCR/pytesseract chain (replaced by Claude vision), `blockchain.py` and `contracts/`, `peer_comparison.py`, `financial_ratio_checker.py`, `due_diligence.py`, `sebi_icdr_corpus.py`, DRHP chapters, `Wizard.jsx`, camelot/tabula/chromadb/torch.

**Clean-up before any screenshot:** no "SEBI", "DRHP", "ICDR", "banker" or "prospectus" in UI text, logger names or routes. Never style output as a GSTN/CBIC document. Don't send unmasked PAN/GSTIN to the LLM (IPO SHERPA does).

## 6. Tech stack

| Layer | Choice |
|---|---|
| Backend | Python 3.12, FastAPI, Pydantic (gst-agent) |
| Rules | YAML rule cards + pytest examples |
| LLM and vision | Claude (Anthropic API) |
| Agent loop | LangGraph, SQLite checkpointer, `interrupt()` approvals |
| Voice | Sarvam speech-to-text (`saaras:v3`) and text-to-speech |
| Channel | Prototype: Telegram bot. Production: WhatsApp Cloud API (needs Meta business verification) |
| Offline backup | Tesseract (GSTIN and totals only) |
| Frontend | React 19 + Vite + Tailwind 4 (from IPO SHERPA) |
| Government systems | Mock GST portal, every response labelled SIMULATED |
| Data | Synthetic bills and 2B; 20–40 real bill photos shared with consent for the accuracy figure |
| Credits | Lyzr AI credits announced; check terms when they arrive. If Lyzr is required, use it for the model calls or agent layer; otherwise keep LangGraph |

## 7. Team split

| Area | Owner (assign) |
|---|---|
| Extraction (Claude vision + validators), matcher integration, rule engine, mock portal events, snapshots | |
| Agent loop (LangGraph), W1/W2/W3, evidence-pack generator | |
| WhatsApp + Sarvam voice channel, shop screens | |
| CA dashboard and exception queue, readiness meter, audit trail, demo screenshots, video | |

## 8. Build plan (to 13 Dec)

| By | Milestone | Done when |
|---|---|---|
| 29 Nov | P0 pipeline | A bill photo → Claude fields → validators → matcher → an exception in the CA queue with reason and cited rule (synthetic data) |
| 3 Dec | Agent + three workflows | LangGraph loop runs W1, W2 and W3 end to end on the mock portal, twice in a row, with approval pauses |
| 7 Dec | Real channels | WhatsApp question and Sarvam voice reply in Hindi, Tamil, Telugu, Kannada, English and the other supported languages (list in `src/gstagent/language.py`) on a low-cost Android |
| 10 Dec | CA dashboard + accuracy | Dashboard shows each case with replies and proof; extraction accuracy measured on 20–40 real bills |
| 12 Dec | Hardening | Demo script rehearsed; video recorded; README states what is simulated and what was reused |
| 13 Dec | Prototype submitted | |
| 27 Dec | Finale | Live demo at Bangalore Palace |

Cut order if time runs short: Q&A copilot, then rule-change alert, then notice check, then Tally export. Never cut W1.

## 9. Demo (5 minutes)

1. The problem in one line, with the cost numbers (20 s).
2. A normal bill matches with no effort; a composition supplier shows "no credit on this bill" (20 s).
3. **W1:** bill photo in → Claude reads it → ₹73,160 line unmatched → voice note to Manju → she answers "never ordered" by voice → CA exception; "still coming" would mean IMS Pending (60 s).
4. **W2:** correction request → press "supplier saves GSTR-1A" → agent re-matches and closes; a silent supplier goes to the CA (50 s).
5. **W3:** cancellation backdated to July → three invoices light up → evidence pack with present and missing proof (50 s).
6. Read-back before filing and CA approval (30 s).
7. Business model and the ask (30 s).

## 10. Proof we will show

| Metric | How measured |
|---|---|
| Bill-reading accuracy | Fields correct on 20–40 consented real bills |
| Auto-match rate | Share of bills matched with no human step (synthetic set plus real sample) |
| Agent reliability | W1/W2/W3 complete end to end without help, repeated runs |
| Voice understanding | Replies classified correctly on recorded test answers, per language tried |

Pilot metrics (after the prototype, not claimed now): confirmation response rate, false alarms on unrecognised invoices, CA minutes saved per client, willingness to pay.

## 11. Business model

Accountant pays a flat workspace fee (₹499 a month for up to 25 clients, ₹999 for up to 75), about ₹13–20 per client a month, roughly 2% of the ~₹11,601 a year these clients already pay their accountant (MSE WP 229). The owner uses it free. If sorting takes a third to half of the accountant's time and Vouchsafe does half of it, the same hours cover about 18–33% more clients (estimate, to be tested). Jobs: local helpers paid per verified intake.

## 12. Risks and how we handle them

| Risk | Handling |
|---|---|
| Scope too big by 13 Dec | P0 first; cut order above; W1 never cut |
| A juror recognises IPO SHERPA code | Disclose reuse in the README; rename every domain term |
| LLM invents a number | Number guard on every outgoing message |
| Claude misreads a bill | Validators + confidence; low confidence asks for a re-snap or read-back |
| API costs and quotas | Claude and Sarvam keys with low limits; Sarvam free credit is only ₹100; check Lyzr credits |
| WhatsApp locked until business verification | Telegram bot for the prototype; in-app phone screen as the last fallback |
| Rule mistakes in front of a CA juror | Rule cards cited and tested; cards marked `verify_before_finale` checked against primary text |

## 13. Credits line for the README

> Number guard pattern, approval workflow, audit log, evidence-pack generator and UI components adapted from IPO SHERPA (2nd place, GFF SEBI TechSprint 2026), built by members of this team. The GST rule engine, matcher, mock GST portal, Claude extraction, LangGraph agent loop and WhatsApp/voice channel are new for Tech4Bharat.

When IPO SHERPA modules are copied in, replace the README's "all code in this repo is our own" line with this credit.
