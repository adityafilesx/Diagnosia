# Audit and refinement plan

This is the working plan for fixing what the November 2026 product, architecture and UX review found. It
turns that review into numbered issues, numbered work items, an order to do them in, and a test that says
when each one is done. Follow it top to bottom. Update the status column as work lands.

- **Source:** the review "Diagnosia six tools review" (12 November 2026, written before the rename to Curai).
  It lives outside the repo; this plan is self-contained.
- **Re-checked against the code on 13 November 2026.** Issues marked ✔ were confirmed by reading the code
  again. Issues marked ◐ come from the review and must be re-confirmed by the person who picks them up (the
  **Check** command shows how). Line numbers drift; the Check command is the authority, not a line number.
- **Not clinically or legally reviewed.** Where the plan touches regulation or data protection it lists
  questions for a regulatory consultant and a data-protection lawyer. It does not answer them.

## 1. Ground rules

Every work item follows these. They come from `agent_context.md` and are not optional.

1. **Hard rules stay.** The AI never diagnoses, changes a dose, suggests a substitute medicine, or tells a
   patient something is or isn't serious. A person approves every AI draft. Unconfirmed or unreadable
   medicines are never explained. Made-up patients only, until the sign-offs in `backend/safety.py` are done
   and `ALLOW_REAL_PATIENT_DATA` is on for a reason.
2. **Test first.** Write the failing test that shows the issue, then fix it. No test needs keys or network.
3. **One work item per branch**, named `fix/<id>-<short-name>` or `feature/<id>-<short-name>`, and one pull
   request into `main`. Run `pytest backend/tests --ignore=backend/tests/browser` before opening it.
4. **UI changes** are checked in a real browser at 390, 820 and 1280 px, and by keyboard.
5. **Never weaken a safety test to get green.** Never edit the frozen evaluation files
   (`backend/tests/ai_eval/diagnofast/v1/`). New data is a new version.
6. **Schema changes** are a `schema.sql` table (new) or a numbered step in `backend/migrations.py` (existing).
7. **Update the docs the change touches** in the same pull request, including `agent_context.md`.
8. **Measure.** Each item names what to measure. Record the number in the pull request.

**Definition of done for any item:** failing test written first, now passing; full suite green; docs updated;
browser check done if there is a screen; the "Done when" line below is true; the status column is updated.

**Effort scale** (judgement, not measured): **S** about a day, **M** two to four days, **L** one to two weeks,
**XL** longer or needs outside people.

## 2. Decisions only the owner can make

Several items wait on these. Each has a recommended default so work is not blocked, and the items that can
start without any decision are listed in the next section.

| # | Decision | Recommended default | Gates |
|---|---|---|---|
| D1 | What may the public demo be? Is there a hosted demo, do demo mode and default consent stay on, what does a visitor see? | A hosted demo is allowed, but it must show the consent screen (WI-101) and demo mode is switched on by an explicit setting, never by default. | WI-101, WI-110, WI-111, WI-260 |
| D2 | What leads, and what is frozen? | DiagnoFast and Prescription Analyzer lead. ClinScribe, LabLens, ReferralLoop and DischargeCare are pilots that get only the fixes in this plan. | Phase 2 scope |
| D3 | What is the intended use of the triage and suggestion features? Keep urgent-symptom routing, "investigations to consider", LabLens range status, the patient-pack brief and AI diet or lifestyle text, or hold them until a regulatory view arrives? | Hold "investigations to consider" and AI diet/lifestyle text behind a switch (off) until the written view arrives. Keep urgent routing, since it only says "tell reception". | WI-112, WI-113, WI-232, WI-251, WI-266 |
| D4 | Which AI vendors and which host? Do Groq and Gemini stay, on which paid or regional terms? Does Edge TTS go? Which Indian region? When does the PostgreSQL move happen? | Edge TTS off outside the demo. Name the allowed providers for patient text. One Indian-region host. PostgreSQL decided by the load-test threshold (WI-261). | WI-106, WI-212, WI-260, WI-280, WI-282 |
| D5 | Is ABDM in scope? | ABHA stays simulated, the product makes no ABDM claim, and the sandbox starts only when someone owns it. | Phase 3 |

## 3. What can start now, with no decision

These need nobody's approval: WI-001, WI-002, WI-003, WI-102, WI-103, WI-104, WI-105, WI-107, WI-108, WI-109,
WI-114 and WI-115, plus the Phase 2 items whose Depends-on column says "none". Start with Phase 0, then run
Phase 1 items in the order shown.

## 4. The audit register

Severity: **S1** privacy or safety, fix before anyone outside the team uses the product. **S2** fix before a
hosted pilot. **S3** improvement.
Verified: ✔ re-read in the code on 13 November 2026. ◐ from the review; re-confirm with the Check command.

### 4.1 Privacy, consent and data flows

| ID | Sev | Finding | Verified | Check (run from the repo root) | Fixed by |
|---|---|---|---|---|---|
| I-01 | S1 | The patient interview page sends `consent` and `abha_consent` as constant `true` and shows no consent text. | ✔ | `grep -n "consent: true" web/js/intake.js; grep -ci consent web/intake.html` (second is 0) | WI-101 |
| I-02 | S1 | Neither the DiagnoFast consent nor the prescription consent is stored. They are request booleans only. | ◐ | `grep -n "consent" backend/diagnofast/routes.py backend/prescription/routes.py` | WI-101 |
| I-03 | S1 | Interview links never expire. The `intakes` table has no expiry, and a link works while the status is `waiting` or `in_progress`. Abandoned links stay valid. | ✔ | `grep -n "OPEN_STATUSES" backend/diagnofast/routes.py`; `sed -n 25,45p backend/db.py` (no `expires_at`; the one in `db.py` belongs to `sessions`) | WI-102 |
| I-04 | S1 | Microsoft Edge text-to-speech receives every DiagnoFast question (AI-written, may paraphrase patient answers). It is on by default, is an unofficial endpoint with no agreement, is missing from the "what leaves our servers" table and has no sign-off item. | ✔ | `grep -n "edge_tts" backend/speech.py`; `grep -n -i "microsoft\|edge" docs/DATA_PROTECTION_AND_RETENTION.md` (no match); `grep -n "REQUIRED_SIGNOFFS" -A12 backend/safety.py` | WI-106 |
| I-05 | S2 | Five tools are pinned to Gemini first, including the DiagnoFast interview turn, so patient answers go to Gemini first by default. The setup doc says fewer. | ✔ for the code, ◐ for the doc | `sed -n 33,42p backend/settings_store.py`; `grep -n -i "prefer" docs/PLATFORM_SETUP.md` | WI-106 |
| I-06 | S1 | The prescription tick-to-confirm rule is enforced by the browser. The server trusts the `legibility` flags it receives and keeps no record of which items were ticked. | ◐ | `grep -n "legibility" backend/prescription/analyzer.py`; read `/explain` in `backend/prescription/routes.py` | WI-211 (record) and WI-106 (honest wording) |
| I-07 | S2 | Demo mode and default consent are on by default, and the kiosk falls back to the first verified doctor. A hosted copy inherits all of it. | ✔ | `grep -n "demo_mode" backend/config.py backend/diagnofast/routes.py`; `grep -n "demo_mode" backend/safety.py` (no check) | WI-110 |
| I-08 | S2 | FHIR export routes are live (`GET /api/patients/{id}/fhir`, ClinScribe note export) although the product treats export as switched off and the output is not validated against ABDM profiles. | ✔ | `grep -n "fhir" backend/records/routes.py backend/clinscribe/routes.py` | WI-111 |
| I-09 | S2 | The doctor view labels simulated ABHA history only as "ABHA record" while the report prompt still says "DEMO DATA". A doctor could read invented history as real. The owner removed the label for the demo on purpose. | ✔ | `grep -n "ABHA record" web/js/care/diagnofast.js`; `grep -n "DEMO DATA" backend/diagnofast/agent.py` | WI-111 (restore decision with D1) |
| I-10 | S2 | The patient-side discharge API returns the raw episode row, including `flagged` and `close_exception` (internal fields). | ◐ | `grep -n "flagged\|close_exception" backend/dischargecare/routes.py` | WI-115 |
| I-11 | S2 | The audit log is append-only against the application only (database triggers). There is no hash chain, so someone with file access could alter it. | ◐ | `grep -n "audit" backend/records/schema.sql` | WI-286 (Phase 3) |
| I-12 | S2 | Answers, transcripts and reports are plain text in SQLite with no retention limit. Recordings are encrypted. | ◐ | `sed -n 25,45p backend/db.py`; `grep -n -i "retention" docs/DATA_PROTECTION_AND_RETENTION.md` | WI-267 |

### 4.2 Safety of the clinical flow

| ID | Sev | Finding | Verified | Check | Fixed by |
|---|---|---|---|---|---|
| I-20 | S1 | The urgent-symptom rules miss real phrasings. Recall on the project's own dev split: poisoning 53.8%, seizure 64.3%, stroke 69.0%, overall single answers 77.8%; Hindi negation after a longer phrase causes false alarms. Not clinician reviewed. | ✔ (reproduced) | `python -m backend.synthetic.diagnofast_eval` | WI-201 |
| I-21 | S1 | An urgent stop tells the patient to go to reception, but nothing alerts staff. The doctor's queue polls only while the page is open. | ◐ | `grep -n "urgent" web/js/care/diagnofast.js \| head`; `grep -n "poll\|setInterval" web/js/care/diagnofast.js` | WI-203 |
| I-22 | S1 | LabLens marks "high confidence" pending rows as accepted and reviewed at confirm. The screen says unremoved results are "saved as read". A person may never have looked at them. | ✔ (the block only waits on `review`-confidence rows) | `sed -n 245,270p backend/lablens/routes.py`; `grep -n "saved as read" web/js/care/lablens.js` | WI-104 |
| I-23 | S2 | A DiagnoFast report says "clinician review required", but there is no review state. The only statuses are waiting, in progress, preparing report, done and report failed. | ◐ | `grep -n "status" backend/diagnofast/routes.py \| head -20` | WI-204 |
| I-24 | S2 | The DiagnoFast report's safety rules (no invented `NORMAL`, `H*/L*` only with a measured value and range, no drug names in investigations) live only in the prompt. No code checks them. The AI's `urgent_symptoms` are free text shown unvalidated. | ◐ | `grep -n "NORMAL" backend/diagnofast/agent.py` (prompt only) | WI-204 |
| I-25 | S2 | The highest-risk form fields (current medicines, allergies) can be skipped. The interview ends at 12 questions, and orthopedics and pediatrics have 10 required fields. | ◐ | `grep -n "MAX_QUESTIONS" backend/diagnofast/agent.py`; count required fields in `forms/*.json` | WI-202 |
| I-26 | S2 | If the AI is down mid-interview, the answer is not saved and the patient sees an error. The form's own fallback question is used only for a blank AI question, not for an outage. | ◐ | `sed -n 380,395p backend/diagnofast/routes.py` | WI-202 |
| I-27 | S2 | ClinScribe's verifier checks numbers and units against the whole transcript, not the cited lines; has no drug-name or frequency check; marks every Hindi statement "uncertain"; and clinician edits clear flags without re-checking. | ◐ | `sed -n 85,110p backend/clinscribe/verifier.py` | WI-220, WI-221 |
| I-28 | S3 | The prescription "how to take" sentence shown and read aloud is the AI's; the rule-decoded directions appear only on the confirm step. A missing course length becomes a 7-day reminder. | ✔ for the 7-day default | `grep -n "UNKNOWN_DURATION_DAYS" backend/prescription/analyzer.py` | WI-213 |
| I-29 | S2 | If the medicine list file is missing, the name check returns `unchecked` and a "clear" name stays "clear". The screen shows nothing. CI always stubs the check, so the real checker is never tested. | ◐ | `grep -n "unchecked" backend/prescription/medicines.py web/js/care/prescription.js`; `grep -n "check_name" backend/tests/conftest.py` | WI-212 |

### 4.3 Data integrity and reliability

| ID | Sev | Finding | Verified | Check | Fixed by |
|---|---|---|---|---|---|
| I-30 | S1 | Two simultaneous answers to one interview can overwrite each other. The route reads the row, calls the AI (seconds), then updates by `id` only, without checking status or `questions_asked`. Audio files are named by turn index and can overwrite each other. | ✔ (the UPDATE is `WHERE id = ?` only) | `sed -n 400,420p backend/diagnofast/routes.py`; `grep -n "def save" -A6 backend/diagnofast/recordings.py` | WI-103 |
| I-31 | S2 | There is no resume. A reload mid-interview leaves the patient stuck, because `GET /patient/{token}` returns only the name and `/start` returns 409 once started. | ◐ | `sed -n 262,285p backend/diagnofast/routes.py` | WI-102 |
| I-32 | S2 | A report task that fails with anything other than an AI error leaves the row in `preparing_report` for ever. No startup recovery. | ◐ | `sed -n 320,356p backend/diagnofast/routes.py` | WI-107 |
| I-33 | S2 | The periodic sweep catches only `sqlite3.Error`, so any other exception ends it silently. | ✔ | `grep -n "except sqlite3.Error" backend/app.py` | WI-107 |
| I-34 | S2 | The access gate writes an audit row on every read, and takes the database write lock before slow AI calls (ClinScribe drafting, patient-pack brief and ask). Several users will hit "database is locked" first. | ◐ | `sed -n 49,80p backend/records/access.py`; `grep -n "open_patient" backend/clinscribe/routes.py` | WI-261 |
| I-35 | S3 | No `/healthz` or `/readyz`; the only status route needs a signed-in user. | ✔ | `grep -n "healthz\|readyz" backend/app.py` (no match) | WI-107 |
| I-36 | S2 | Reminders: reads have side effects (`process_due` on every list), "no answer" attempts have no cap, and no tool creates a reminder automatically. | ✔ for `process_due` | `grep -n "process_due" backend/reminders/routes.py` | WI-254 |
| I-37 | S2 | Referral "needs chasing" is computed only when someone loads the list; no scheduler touches referrals. The auto-created tasks have no `due_at`, so escalation ignores them. | ◐ | `grep -n "respond_by" backend/referralloop/routes.py`; `grep -n "def escalate_overdue" -A15 backend/records/care.py` | WI-240 |
| I-38 | S3 | A referral appointment time is unvalidated free text, and `booked` can be set with no appointment row. | ◐ | `grep -n "scheduled_at" backend/referralloop/routes.py` | WI-242 |
| I-39 | S2 | Any care-team clinician, not only the responsible one, can close a discharge, and unresolved barriers never block closing. | ◐ | `sed -n 380,412p backend/dischargecare/routes.py` | WI-253 |

### 4.4 Cost, abuse and operations

| ID | Sev | Finding | Verified | Check | Fixed by |
|---|---|---|---|---|---|
| I-40 | S1 | The signed-in AI routes have no rate limit: prescription read and explain, ClinScribe transcribe and draft, LabLens upload and retry, patient-pack brief and ask. Registration is open with no per-address limit, so anyone can sign up and run up AI cost. | ✔ (only `/speak` is limited in these modules) | `grep -n "ratelimit" backend/prescription/routes.py backend/clinscribe/routes.py backend/lablens/routes.py backend/patient_pack/routes.py backend/auth.py` | WI-105 |
| I-41 | S2 | No token or cost accounting. AI run records hold provider, model and timings only. No caching, no per-user spend cap. | ◐ | `grep -n "agent_runs" -r backend/integrations/execution.py \| head` | WI-105 |
| I-42 | S2 | No CI, no dependency lockfile, no dependency audit. | ✔ | `ls .github` (missing); `ls backend/requirements*.txt` | WI-001 |
| I-43 | S2 | Observability is a request-id header only: no logging configuration, no metrics, no error reporter. Production is blind. | ◐ | `grep -rn "logging.basicConfig\|dictConfig" backend` | WI-262 |
| I-44 | S3 | No HSTS; a content-security-policy only on `/care.html`; no MFA, password reset or idle timeout for sessions. | ◐ | `grep -n "Content-Security-Policy\|Strict-Transport" backend/app.py` | WI-263, WI-281 |
| I-45 | S3 | Concurrency is untested: no test covers two writers, a kill mid-job, or load. | ✔ (no such tests) | `grep -rn "Thread\|concurrent" backend/tests --include=*.py -l` | WI-103, WI-261 |

### 4.5 Product and documentation honesty

| ID | Sev | Finding | Verified | Check | Fixed by |
|---|---|---|---|---|---|
| I-50 | S3 | The README says "58 proposed LOINC mappings". The data file has 49 analytes, and the mapping table is never read by the parser. | ✔ | `python3 -c "import json;print(len(json.load(open('backend/lablens/analytes.json'))['analytes']))"` | WI-108 |
| I-51 | S3 | The docs and the product copy say interview links are "single use". They are not (I-03). | ✔ | `grep -rn -i "single-use\|single use" docs README.md agent_context.md web/*.html` | WI-102, WI-108 |
| I-52 | S2 | The product story is "six tools, one record, in the order of a visit", but no tool hands anything to the next. `HANDOFF_PURPOSE` is empty. | ◐ | `grep -n "HANDOFF_PURPOSE" backend/careflow/delivery.py` | WI-270 |
| I-53 | S2 | The DiagnoFast report and a patient's saved prescription list live beside the shared record, not in it. Kiosk visits have no patient record at all and are orphaned. | ◐ | `grep -n "patient_id" backend/diagnofast/routes.py \| head` | WI-271 |

### 4.6 User experience and accessibility (WCAG 2.2 AA)

| ID | Sev | Finding | Verified | Check | Fixed by |
|---|---|---|---|---|---|
| I-60 | S2 | 2.4.11 Focus Not Obscured: at phone width the sticky patient bar (111–159 px) hides focused fields; no `scroll-padding-top`. | ◐ | open `care.html` at 390 px, tab through a patient page; `grep -n "scroll-padding" web/css/care.css` | WI-109 |
| I-61 | S2 | Focus is dropped to `BODY` after every route change in the workspace, and error toasts are polite and vanish in 4 seconds. | ◐ | `grep -n "focus" web/js/care/app.js \| head`; `grep -n "role" web/js/care/ui.js \| head` | WI-109 |
| I-62 | S2 | Non-text contrast: input borders 1.74:1 (light) and 1.37:1 (dark); focus ring on the black bar 2.7:1. Text contrast fails on `.good.status` (4.35:1) and on one public-site colour (4.09:1). | ◐ | recompute from the tokens in `web/css/care.css`; axe on the pages | WI-109 |
| I-63 | S2 | No `lang` on `index.html` or `login.html`; Hindi text in the workspace has no `lang="hi"`. | ◐ | `grep -L 'lang=' web/*.html`; `grep -rn 'lang="hi' web/js` | WI-109 |
| I-64 | S2 | The public page fails axe: no landmarks or skip link, unnamed logo links, a tab list containing plain buttons, an iframe without a title. The login page has duplicate ids and dead Google, Facebook and "Forgot password" controls. | ◐ | run axe-core on `index.html` and `login.html` | WI-109 |
| I-65 | S3 | At phone width the public navigation overlaps the logo, and the fixed Login button covers "about us". Confirmed in the running app, causes in `index.css` and `flow-button.css`. | ◐ | open `index.html` at 390 px | WI-109 |
| I-66 | S3 | The hero animation has no `prefers-reduced-motion` check and no pause. | ◐ | `grep -rn "prefers-reduced-motion" web` | WI-109 |
| I-67 | S2 | The patient's workspace is the clinician's with parts hidden: staff wording ("Patient pack", "encounters"), Reminders and Tasks reachable only by typing the address, no Hindi interface outside the interview. | ◐ | sign in as `patient001@example.com` at 390 px | WI-264 |
| I-68 | S1 | The interview shows no consent words (I-01), defaults the language to Hindi for English-labelled patients, shows a staff-worded AI-error message with no next step, and the urgent stop says nothing about what happens next. | ◐ | open an interview link at 820 px with no AI key | WI-101, WI-202, WI-203 |
| I-69 | S3 | A DiagnoFast report with no linked chart is a dead end: no "add to chart" and no "start ClinScribe". | ◐ | open a kiosk report as `doctor01@example.com` | WI-205 |

## 5. Work items

Phase 0 is week one. Phase 1 is the next 30 days. Phase 2 is the following 60 days. Phase 3 is the rest of
the year. Within a phase, work in the order listed unless the dependency column says otherwise.

### Phase 0: foundations (week 1)

| ID | Work | Done when | Effort | Depends on |
|---|---|---|---|---|
| WI-001 | Add CI on Linux and Windows: run `pytest backend/tests --ignore=backend/tests/browser`, then `pip-audit` on `backend/requirements.txt`. Pin dependencies with a lockfile. | Every pull request runs green on both systems; `ls .github/workflows` shows the workflow; a deliberately failing test turns it red | S–M | none |
| WI-002 | Record baselines before changing anything and keep them in `docs/BASELINES.md`: test count (1379 passed, 1 skipped on 13 Nov), the red-flag scores (`diagnofast_eval`, dev and frozen test), `lab_validation.score` result, and the model-comparison table from `backend/tests/ai_eval/README.md`. | Numbers are in the file with the date and commit | S | none |
| WI-003 | Add a pull request template with the definition of done, "what I tested by hand", and the metric recorded. | A new pull request shows the template | S | none |

### Phase 1: close the trust gaps (30 days)

| ID | Work | Files | Done when | Effort | Depends on |
|---|---|---|---|---|---|
| WI-101 | **Visible, stored, bilingual consent.** Interview: language as two large buttons first (no default), then a consent screen (three plain lines: this is recorded; it goes to outside AI services; a doctor will check it) with an explicit "I agree / मैं सहमत हूँ" button that sets the flag. ABHA is a separate yes or no, shown only when an ABHA id exists. Prescription: a full-row consent control of at least 44 px. Store a consent record (kind, text version, language, time, intake or user) in a new table. | `web/intake.html`, `web/js/intake.js`, `web/js/care/prescription.js`, `backend/diagnofast/routes.py`, `backend/prescription/routes.py`, new table in a `schema.sql` | `grep "consent: true" web/js/intake.js` finds nothing; a test shows `/start` and `/prescription/read` are refused without a stored consent; every new intake has a consent row; a Hindi speaker has approved the wording | M | D1; a Hindi reviewer |
| WI-102 | **Link expiry and resume.** Add `expires_at` to intakes (24 hours for `waiting`, configurable) as a migration. A sweep closes stale rows. Add `GET /patient/{token}/state` returning the current question and language, and make the page resume from it. Update "single use" wording to what is true. | `backend/migrations.py`, `backend/diagnofast/routes.py`, `web/js/intake.js`, `backend/app.py` sweep | A link older than the limit is refused with the "ask reception" message; reloading mid-interview returns to the same question; abandoned kiosk rows are closed | M | none |
| WI-103 | **Safe answer writes.** Make the update conditional (`WHERE id=? AND status='in_progress' AND questions_asked=?`), return 409 on a lost race, add an idempotency key so a retry returns the stored result, and name audio files uniquely. Keep the saved answer if the AI fails after the transcript is stored, so a retry doesn't lose it. | `backend/diagnofast/routes.py`, `backend/diagnofast/recordings.py` | A two-thread test posting the same answer twice, with a slow fake AI, leaves exactly one stored answer and one 409; no orphan audio file; report built once | M | none |
| WI-104 | **LabLens confirm gate.** Remove silent acceptance. Every row needs a person's action, or one explicit "I compared these with the original" tick per report, and rows nobody touched stay unreviewed. Reword "saved as read". After a "Fix", re-run the unit and plausibility checks. | `backend/lablens/routes.py`, `web/js/care/lablens.js` | No observation has `reviewed_by` unless a person acted or ticked; a test fails if a pending high-confidence row is accepted silently; a typed 112 for 11.2 raises a plausibility issue | S–M | none |
| WI-105 | **Cost and abuse controls.** Per-user limits on every AI route listed in I-40; per-address limits on register and login; a daily per-user quota and a global daily spend breaker counted in SQLite; token usage and a price table recorded in the AI run records. | `backend/ratelimit.py`, the route modules, `backend/auth.py`, `backend/integrations/execution.py`, `backend/llm.py` | A script creating accounts and submitting photos is stopped at a stated cap; the breaker trips in a test and returns a patient-worded message; a weekly cost per tool is printable | M | none |
| WI-106 | **Close the data-egress gaps.** Edge TTS off unless the demo setting is on (D4). Correct `DATA_PROTECTION_AND_RETENTION.md`, `CLINICAL_GOVERNANCE.md`, `LICENCE_AND_DEPENDENCY_AUDIT.md` and `PLATFORM_SETUP.md` so the "what leaves our servers" table matches the code. Add sign-off items for Edge TTS terms and the Meko agreement. State plainly that the prescription tick is browser-enforced until WI-211. Name the allowed providers for patient text (decision D4); refuse others. | `backend/speech.py`, `backend/config.py`, `backend/safety.py`, `backend/settings_store.py`, the four docs | The egress table matches a grep of outbound calls (a test lists the hosts the code can reach); `REQUIRED_SIGNOFFS` has the new items; with Edge TTS off a question is read by the browser voice | M | D4 |
| WI-107 | **Reliability.** The sweep logs every exception and keeps running; a startup sweep fails or retries rows stuck in `preparing_report`; `report_failed` gets a retry; add `/healthz` (process up) and `/readyz` (database and key ring OK) without patient data. | `backend/app.py`, `backend/diagnofast/routes.py`, `backend/safety.py` | A restart test leaves no report in `preparing_report` for more than 5 minutes; killing the sweep's database mid-run is logged and the next pass runs | M | none |
| WI-108 | **Honest labels in the docs and copy.** Fix the "single use" wording (after WI-102 makes expiry true), the README's "58 LOINC mappings" (it is 49), the FHIR "switched off" wording, and add this plan to the docs table. | docs, `web/*.html` | `grep` for each old phrase finds nothing | S | none |
| WI-109 | **Workspace and public-page accessibility.** `scroll-padding-top` equal to the patient bar height; focus the `main` heading on route change and announce it; errors as `role=alert` and persistent; `lang` on every page and `lang="hi"` on Hindi spans; borders and focus rings at 3:1 or better; darken the two failing text tokens; public page landmarks, skip link, names on logo links, iframe title, tab-list roles; login page duplicate ids and the dead social and "Forgot password" controls removed or labelled; `prefers-reduced-motion` plus a pause control; fix the phone navigation overlap. | `web/css/care.css`, `web/js/care/app.js`, `web/js/care/ui.js`, `web/index.html`, `web/login.html`, `web/css/index.css`, `web/css/flow-button.css`, `web/js/hero-gradient.js` | axe-core is clean on the pages the review tested; 2.4.11 passes at 320 px; keyboard route change lands on the new heading; no overlap at 390 px; a browser check at 390, 820 and 1280 px | L | none |
| WI-110 | **Demo mode must be a choice.** In `safety.assert_safe_to_start`, refuse to start with `CURAI_ENV` outside development and demo mode on, unless an explicit "I know" setting is present. Print a loud banner when demo mode or default consent is on. | `backend/safety.py`, `backend/config.py` | A test shows a non-development start with demo mode on refuses; the banner shows in the log | S | D1 |
| WI-111 | **Gate or document the FHIR export routes.** Put them behind the same switch as the UI, or document them as live. Restore the ABHA "simulated" label and the report prompt's provenance wording before anyone outside the team sees the screen (owner chose to remove it for the demo, so this is D1). | `backend/records/routes.py`, `backend/clinscribe/routes.py`, `web/js/care/diagnofast.js` | Route behaviour matches the docs; the label is back or the removal is recorded as a decision | S | D1 |
| WI-112 | **Commission the regulatory and data-protection reviews.** Give a regulatory consultant the per-tool table (section 7) and ask for a written classification view. Give a data-protection lawyer the data-flow table from WI-106 and ask for a fiduciary or processor view, a children's-data view (pediatrics), and a retention view. | `docs/` | Both engagements exist with dates; questions in section 7 are sent | XL (outside people) | D3 |
| WI-113 | **Hold unreviewed suggestion features.** Put "investigations to consider", AI diet and lifestyle text, and the patient-pack brief and ask behind switches that default off until WI-112 returns. | `backend/settings_store.py`, `web/js/care/diagnofast.js`, `web/js/care/prescription.js`, `web/js/care/pack.js` | With the switch off the feature is absent from the screen and the API refuses it | M | D3 |
| WI-114 | **Rename follow-ups.** Rename the GitHub repository to `curai`, update the remote, and edit the two pitch decks. | repo settings, `pitch/` | `git remote -v` shows the new name; the decks say Curai | S | none |
| WI-115 | **Hide internal discharge fields from the patient API.** Return an explicit patient view for episodes (no `flagged`, no `close_exception`). | `backend/dischargecare/routes.py` | A patient-role call returns neither field (test); the staff view is unchanged | S | none |

**Phase 1 exit criteria.** These S1 issues are fixed, or have a written owner decision: I-01, I-02, I-03, I-04,
I-22, I-30 and I-40. I-06 has honest wording (the full fix is WI-211 in Phase 2). I-20, I-21 and I-68 stay open
until Phase 2: Phase 1 only records the baseline and gets the clinician and alert design agreed. CI is green. A
consent record exists for every new intake and prescription read. **Measure:** share of intakes and reads with a
stored consent (target 100%); the two-thread race test passes; no observation reviewed without a human action;
the scripted abuse loop is stopped; the egress table matches the code.

### Phase 2: pilot-ready for made-up patients, hosted (days 30 to 90)

**DiagnoFast** (leads, D2)

| ID | Work | Done when | Effort | Depends on |
|---|---|---|---|---|
| WI-201 | **Red-flag v2.** Write a new labelled set (v2; never edit v1) containing the missed phrasings and Hindi negation cases from the v1 README, written with a native Hindi speaker; extend the rules (negation reach after a longer symptom phrase, suffixes, the missed phrasings); settle the 12 "needs a clinician" answers with a clinician. | Re-scoring v1 and v2 shows recall for poisoning, seizure and stroke above targets a clinician signed; no drop on v1 frozen test; calm interviews wrongly stopped does not rise | L | a clinician and a Hindi reviewer |
| WI-202 | **Code-enforced high-risk fields and a form fallback.** If medicines or allergies are still missing near the question cap, the code asks them. When the AI is down, a form-driven fallback (static questions) finishes the interview. A "tell reception" button on every failure. Language asked first. | With the fake AI set to fail, a form still completes; no interview ends without medicines and allergies unless the patient declined | M | WI-103 |
| WI-203 | **Staff alert on an urgent stop**, using the existing urgent event. The patient's urgent screen says "go to reception now", reads it aloud, and does not auto-reset for 60 seconds, with no statement about seriousness. | Alert latency from stop to staff screen is measured on the kiosk and recorded; the patient screen tests pass | M | none |
| WI-204 | **Doctor "reviewed" stamp and report validator.** A reviewed-by and reviewed-at stamp that is the only thing letting a report enter the chart as reviewed. A validator after `write_report`: every `NORMAL` row cites a turn with a negative, every `H*/L*` row has a number and a range, no investigation text contains a drug name; failures are shown as flagged. | A test per rule; no report stays unreviewed in the chart view | M | WI-107 |
| WI-205 | **Report hand-off buttons and queue.** "Add to chart", "Choose existing chart", "Start ClinScribe for this patient"; a compact top strip (urgent, allergies, medicines); queue rows with name, age, department and state chip; copy link and QR. | A kiosk report can be attached in two clicks; browser check at 390, 820, 1280 px | M | WI-271 |

**Prescription Analyzer**

| ID | Work | Done when | Effort | Depends on |
|---|---|---|---|---|
| WI-210 | **Read twice and compare, as an experiment first.** Two independent reads (preferably two different models). Any field that differs becomes `unsure`; never pick a winner or merge. Measure on the synthetic set before shipping. | Disagreement rate against error rate is reported by `ai_eval/run_eval.py`; flag precision and recall are published; a differing field is never shown as `clear` | L | WI-001 |
| WI-211 | **Record what the patient confirmed.** Show the patient's own photo next to each card (a local object URL, never uploaded). Store the confirmed set, app version and model on every explain and save. One shared readability rule on client and server. | The log shows the confirmed set per explain; a legible mark with unreadable text is handled the same on both sides (test) | M | none |
| WI-212 | **Visible `unchecked` and a real checker in CI.** Show "We could not check this name against a list". Add a health banner when the list is missing. Add a tiny fixture CSV so CI exercises the real checker. Plan the licensed replacement list (the current one looks scraped). | A deployment without the list shows the banner; CI proves a near-miss name is `close` | S–M | D4 for the licensed list |
| WI-213 | **Directions cross-check.** Show the rule-decoded directions beside the AI sentence and reject an AI sentence whose numbers differ. Replace the 7-day default with "no end date written, ask your doctor". | A seeded mismatch is rejected; no reminder has an invented course length | M | none |

**ClinScribe, LabLens, ReferralLoop, DischargeCare**

| ID | Work | Done when | Effort | Depends on |
|---|---|---|---|---|
| WI-220 | **Verifier upgrade.** Check numbers and units against the cited lines; add drug-name and frequency checks using the prescription modules; re-run on clinician edits. | New synthetic cases (swapped drug, wrong item, edited-in wrong dose) are flagged; the existing tests still pass | M | none |
| WI-221 | **Hindi source-line view.** Show the cited source line beside each statement; per-flag acknowledgement; stop calling the Hindi flag a verification; drop dangling evidence pointers when the transcript is deleted on sign; one active draft per session. | A clinician finds a seeded wrong line in a Hindi note in a small observed session | M | WI-220 |
| WI-222 | **Guard typed segments** on session state and consent; show "N chunks lost"; replace record controls with "Draft the note" and "Add a missed line" after stop. | A segment posted to a stopped session gets 409 (test); the badge shows | S–M | none |
| WI-230 | **Unparsed lines and qualitative results.** Count and show "N lines not read"; parse qualitative results locally and send them to review. | A report with a deliberately unparsable line shows a non-zero count | M | none |
| WI-231 | **Scored scan test set.** Synthetic scans with ground truth for the AI path; publish per-field scan error rates beside the 37/37 text figure. | Rates are in `docs/BASELINES.md` | L | WI-002 |
| WI-232 | **Wording of range comparison.** Show the lab's own printed flag and range, and label any computed `range_status` as "compared with the printed range". Do not present trends as interpretation until the consultant says so. | No screen says "high" or "low" without naming its source | S | D3, WI-112 |
| WI-240 | **Referral overdue as pushed work.** The five-minute sweep creates a due-dated high-priority task for referrals past `respond_by`; auto-created tasks get a `due_at` so escalation covers them. | A seeded referral past `respond_by` produces a task with nobody opening a page | M | none |
| WI-241 | **Structured referral outcome.** Outcome type, follow-up date and proposed medicine changes as a flagged note for the clinician; the review step creates the follow-up task; emit a CareFlow event on review. | After review a dated follow-up task exists; the timeline shows "outcome reviewed" | M | WI-270 |
| WI-242 | Validate appointment datetimes; require an appointment row for `booked`. | A malformed date is refused (test) | S | none |
| WI-243 | Redirect creates the replacement referral; block cancel from `outcome_returned` unless reviewed. | Redirected referrals link to their replacement | S–M | none |
| WI-244 | Referral form UX: "New referral" first, destination as a required radio group with field-level errors, priority as a select, no-patient guard. | A referral is sent in fewer clicks; no route fails with no patient open | S–M | none |
| WI-250 | **Family checklist in plain words.** Approved summary, "who to call" first, large "Done"; notify on tasks added after approval. | A family member can say what to do and whom to call after one read | M | WI-115 |
| WI-251 | **Hindi discharge instructions as a reviewed workflow.** Side-by-side entry; any AI translation is a labelled draft the clinician approves. Needs a policy decision because the docs say no AI writes instructions. | No instruction reaches a family without clinician approval | M | D3; a Hindi reviewer |
| WI-252 | Link pending results to LabLens reports and create a task when `expected_by` passes. | Finalising attaches a confirmed observation; an overdue result creates a task | M | WI-270 |
| WI-253 | Restrict close to the responsible clinician (or a second to reopen); unresolved barriers become a close warning with a target date. | A non-responsible clinician cannot close (test) | S | none |
| WI-254 | **Automatic reminders.** Create reminders on discharge approval, referral booked, and pending result due, through the existing module. `process_due` moves off read routes into the sweep, and "no answer" attempts get a cap. Do not build SMS or voice channels until a vendor agreement exists. | Every approved episode has reminders; reads no longer write | M | none |

**Platform, hand-offs and patient experience**

| ID | Work | Done when | Effort | Depends on |
|---|---|---|---|---|
| WI-260 | **Hosted single-host demo** in an Indian region: one worker, persistent encrypted volume, HTTPS, proxy headers, encrypted daily backups and a restore drill. | A restore into a scratch path matches row counts; HTTPS and proxy-header flags documented | L | D4, WI-110, WI-107 |
| WI-261 | **Contention fixes and a load test.** Take the audit write off the AI call's critical path (audit after the AI call, or in its own short transaction); set a busy timeout and return 503 on lock; write a load test and set the threshold that triggers the PostgreSQL decision. | No "database is locked" in a multi-thread test with a slow fake AI; `SQLITE_BUSY` count and p95 write latency recorded against the threshold | M | WI-103 |
| WI-262 | **Observability.** Logging configuration with request ids and no patient text; error tracking; an uptime check; log retention that meets CERT-In's 180 days (confirm with the lawyer). | A test asserts logs hold no patient text; an induced error shows in the tracker | M | WI-107 |
| WI-263 | **Security headers.** HSTS and a content-security-policy on every page; session idle timeout. | Headers present in a test for every route family | S–M | none |
| WI-264 | **Patient experience.** Patient Home in visit order (Your medicines, Your lab results, Going home, Reminders), a one-time language choice that sets `lang` and the chrome, patient-voice rewrites, hide CareFlow and Patient pack from patients. | A small observed session with intended users on made-up cases (an expert walkthrough, not a study) finds no staff-word confusion | L | WI-109 |
| WI-265 | **Clinic counts page** (counts only, no patient text): interviews started and completed, share ending in an urgent stop, time from interview end to report ready, share of reports reviewed, doctor edit rate on notes, lab rows corrected. | The counts match a manual tally on made-up data | M | WI-204 |
| WI-266 | **Pilot protocol** for consultation minutes and form completeness with consenting clinicians on made-up or non-identifying flows; ethics review if any real patient is involved. | The protocol is approved before any collection | M | D3, WI-112 |
| WI-267 | **Retention.** Retention periods for answers, transcripts and reports, with a purge job; written down with the lawyer. | A purge test removes rows past the period | M | WI-112 |
| WI-270 | **Three small hand-offs that keep a person in the loop.** Show the DiagnoFast report and latest confirmed labs beside the ClinScribe draft as read-only context (never model input); DischargeCare pending results point at a LabLens report; referral outcome review creates a dated follow-up task. Emit CareFlow events for note signed, referral outcome reviewed, and discharge approved or closed. | Each hand-off has a test; the timeline shows the three events | L | WI-204, WI-241, WI-252 |
| WI-271 | **DiagnoFast report as a record item** with draft, reviewed and superseded states; kiosk visits get a one-click "attach to a chart"; a doctor-only reconciliation view lists medicines and allergies as reported, as saved from a prescription, and as recorded in the chart side by side, and decides nothing. | A kiosk report can be attached; the view shows differences without choosing | L | WI-204 |
| WI-272 | **Prescription tidy.** Collapse the duplicate schedule output (`build_schedule` and `build_calendar_reminders`) and trim the calendar code for the pilot to a schedule table plus a plain `.ics`. Freeze diet and yoga text (WI-113). | The explain response has one schedule; tests pass | M | WI-113 |

**Cut or freeze (no new work in these until named)**

- New DiagnoFast specialties until a clinician reviews the six forms.
- The Code 39 barcode and A4 fit-measuring print code for DiagnoFast reports, unless a clinic asks for paper.
- LOINC mapping workflow expansion, until a laboratory professional exists to approve mappings.
- SMS and voice reminder channels, until a vendor agreement exists.
- Per-tool FHIR exports, if the record-level one covers it.
- Any AI that ranks referral urgency, or any coded diagnosis, assessment or plan generator in ClinScribe.
- A prescription pill or strip photo cross-check.

**Phase 2 exit criteria.** All S2 issues are fixed or accepted in writing. A hosted single-host copy runs with
made-up patients and a restore drill passed. **Measure:** red-flag recall per category against the signed
targets; alert latency; read-twice precision and recall; scan error rates published; a past-due referral creates
a task unaided; the load-test numbers recorded and the PostgreSQL decision taken against the threshold.

### Phase 3: the gate to real data, if the owner chooses to go (months 4 to 12)

| ID | Work | Done when | Depends on |
|---|---|---|---|
| WI-280 | **PostgreSQL with versioned migrations**, a queue (Procrastinate or equivalent) with leases, shared object storage and a managed key service. | Kill-mid-job resumes once; migrations run on both engines until cutover | load-test threshold trips or a second server is planned |
| WI-281 | **MFA, password reset with an email channel, idle timeout**, and an independent penetration test. | Pen-test findings closed | email provider choice |
| WI-282 | **Signed agreements with every processor** (or an India-region route, subject to per-model availability) and a data-protection assessment signed off in `governance_signoffs`. | All sign-offs complete | D4, lawyer |
| WI-283 | **Apply the regulatory outcome**: intended-use statements, quality system and risk file if any function is a device, an algorithm change process for model swaps. | A documented classification per tool | consultant memo |
| WI-284 | **ABDM sandbox, if chosen**: ABHA create and verify first, then the provider or user role; security audit. No claim before sandbox exit. | Sandbox exit | D5 |
| WI-285 | **Tenant column** on patients and care team before a second clinic shares a deployment. | A cross-tenant access test fails closed | WI-280 |
| WI-286 | **Audit hash chain** on `audit_events` (I-11). | A tamper test detects a changed row | WI-280 |
| WI-287 | **A third language** through a per-language gate: its own red-flag rules and labelled data, not only a translated question set. | Word-error and red-flag recall per language published | geography decision |
| WI-288 | **A real-user study** with low-literacy participants and a clinician-reviewed Hindi discharge set. | Task success and comprehension measured | pilot approval |
| WI-289 | **Restore for real use**: the demo labels and pilot warnings, the consent panel, the who-opened-a-chart record, and FHIR export in the UI; `care.consent_by_default` false with real data. | `ALLOW_REAL_PATIENT_DATA` is on only with all of these | real-data decision |

## 6. Verification and audit cadence

- **After every pull request:** the suite, the new test, the browser check for screens, and the metric in the
  pull request text.
- **Weekly:** re-run `python -m backend.synthetic.diagnofast_eval`, the LabLens scorer, and the egress test.
  Add the numbers to `docs/BASELINES.md`. A drop in a safety number blocks the next merge until explained.
- **End of each phase:** re-run every **Check** command in section 4 and update the Verified column. Any issue
  whose check now passes becomes ✔ fixed and moves out of the register. Re-run the axe checks and the three
  walkthroughs (patient on a phone, doctor between patients, reception on a tablet). Write a short note on what
  changed and what was found new.
- **Before any real patient:** every S1 and S2 issue is closed, all `REQUIRED_SIGNOFFS` are signed, the
  regulatory and data-protection views are in writing, and the owner has made D1 to D5 in writing.

## 7. Questions for outside reviewers

For a **medical-device regulatory consultant** (CDSCO's Medical Device Software guidance of July 2026 is the
starting point; the research could not read the primary document or reproduce its class table):

1. DiagnoFast: does urgent-symptom routing that tells a patient to go to reception, and a list of "investigations
   to consider" for the physician, make it medical-device software, and in which class?
2. LabLens: does showing a result against the lab's printed range, a computed high or low flag, and a trend
   chart change its status?
3. Prescription Analyzer: does explaining a confirmed prescription in plain language, with diet and lifestyle
   text, change its status?
4. ClinScribe: where is the line between documentation and a drafted assessment or plan?
5. Patient-pack brief and ask: does an AI summary of a patient's record count as clinical decision support?
6. What change-control record is needed when a model is swapped?

For a **data-protection lawyer** (the DPDP Rules were reported as notified in November 2025 with the main duties
from about May 2027; the research could not read the Rules text):

1. Is Curai a data fiduciary or a processor for a clinic's patients, and what does that change?
2. What notice and consent text is needed for the patient interview, the prescription reader and a minor's
   (pediatrics) data? Whose consent is it?
3. Is sending patient text to Groq (United States) and Google, or question text to Microsoft, allowed, and what
   agreements and data-residency terms are needed?
4. What retention and deletion periods apply to answers, transcripts, recordings and reports?
5. What breach-notification process and timeline must be in place, and who owns it?

## 8. Known limits of this plan

- The review behind it read search summaries for most outside claims, because official sites (CDSCO, ABDM,
  Google, Groq, SQLite, PubMed and others) could not be opened. Prices, limits and legal readings need a second
  look on the official page before anyone relies on them.
- The walkthrough could not run any AI step (no keys), and used no real microphone, Hindi speech or handwriting.
  It was an expert walkthrough, not user research.
- Effort sizes are judgement, not measurement. Revise them after the first three items land.
- Nothing here has been reviewed by a clinician, a regulator or a lawyer.

## 9. Status tracker

Copy a row into the pull request when work starts. States: Open, In progress, Done (with the pull request).

| Item | Owner | State | Pull request | Date done |
|---|---|---|---|---|
| WI-001 to WI-003 (Phase 0) | Claude | Done (13 Nov): CI, lockfile, audit (Starlette and pytest upgraded to clear 16 advisories), baselines, PR template | branch `claude/eager-tesla-g24rmm` | 13 Nov 2026 |
| WI-102, WI-103 | Claude | Done (13 Nov): links expire (24 h unopened, 2 h once started, migration 9, sweep marks them `expired`); `GET /patient/{token}` returns the current question so a reload resumes (no separate `/state` route); answers saved only if the question is still open (409 otherwise), retried with an answer key that returns the stored reply; unique recording names, the losing recording removed. On an AI failure nothing is stored and the page keeps the typed answer for a retry. | branch `claude/eager-tesla-g24rmm` | 13 Nov 2026 |
| WI-101 | Claude | Done in code (13 Nov): the interview asks the language first (two buttons, no default), then shows three consent lines from `records/consent.py` with an "I agree" button; ABHA is a separate yes or no, shown only with an ABHA number. The prescription consent is a full-row control (44 px). `/start` and `/prescription/read` need the current wording's version and store a row in `consent_records` (kind, version, language, agreed, intake or user). **Still open:** a Hindi speaker must approve the Hindi wording. | branch `claude/eager-tesla-g24rmm` | 13 Nov 2026 |
| WI-104, WI-115 | Claude | Done (13 Nov): LabLens no longer accepts untouched results silently. Confirming needs each result accepted, fixed or removed, or one "I compared every result with the original" tick (409 `comparison_needed` otherwise). A typed fix gets the unit and plausibility checks again, and one with an issue goes back to pending. The patient's discharge list returns only id, dates, destination, status and emergency contact. | branch `claude/eager-tesla-g24rmm` | 13 Nov 2026 |
| WI-105 | Claude | Done (13 Nov): per-account hourly limits on prescription read and explain, ClinScribe transcribe and draft, LabLens upload and retry, patient-pack brief and ask, plus a shared daily quota (2,000 per account); per-address limits on register (20 an hour) and login (100 an hour); a daily breaker in `llm.ask` on tokens (default 5 million) or priced spend; token counts on every AI attempt and `operator_cli ai-usage`. Not yet: speech transcription in the budget, and the token columns are not copied to YugabyteDB. | branch `claude/eager-tesla-g24rmm` | 13 Nov 2026 |
| WI-106 | Claude | Done in code (13 Nov), using the D4 default: Edge voices only in demo mode (never with real data allowed); AI and speech calls refuse hosts outside `CURAI_ALLOWED_AI_HOSTS` (Groq, Gemini, this machine); signoffs `edge_tts_terms` and `meko_agreement` added; the four docs now list every host, and `test_egress.py` fails if the code names one that isn't listed. The prescription tick is stated as client-attested until WI-211. **Open:** D4 itself (which vendors on which terms). | branch `claude/eager-tesla-g24rmm` | 13 Nov 2026 |
| WI-107 | Claude | Done (13 Nov): each sweep step commits on its own and a failure is logged without stopping the rest; the sweep also runs at start-up; a report left `preparing_report` for 5 minutes becomes `report_failed` (migration 10 adds `report_requested_at`); any error in the report job leaves it failed; doctors get "Try writing the summary again" (`POST /intakes/{id}/report/retry`); `/healthz` and `/readyz` added. | branch `claude/eager-tesla-g24rmm` | 13 Nov 2026 |
| WI-108 | Claude | Done (13 Nov): "single use" now says a link serves one interview and expires; README says 49 LOINC mappings; FHIR wording corrected (see WI-111). The review notes and report under `research_notes/` and `reports/` keep their original wording as a record. | branch `claude/eager-tesla-g24rmm` | 13 Nov 2026 |
| WI-110 | Claude | Done (13 Nov), using the D1 default: demo mode is on by default only when `CURAI_ENV=development`; elsewhere it needs `CURAI_DEMO_MODE=1` plus `CURAI_DEMO_OUTSIDE_DEVELOPMENT=1`, or start-up is refused. A banner is logged whenever demo mode or default consent is on. | branch `claude/eager-tesla-g24rmm` | 13 Nov 2026 |
| WI-111 | Claude | Partly done (13 Nov): the FHIR routes are documented as live, behind the access gate and audit (`FHIR_MAPPING.md`, `agent_context.md`). **Waiting on D1:** whether to put them behind a setting, and whether to restore the ABHA "simulated" label, which the owner removed for the demo. Not restored. | branch `claude/eager-tesla-g24rmm` | 13 Nov 2026 |
| WI-113 | Claude | Done (13 Nov), using the D3 default: "investigations to consider" and the patient-pack AI brief and questions are behind Settings switches that start off (section "Held for regulatory review"). Off means not stored, not shown, and refused by the API. The AI diet and lifestyle text named in the plan no longer exists in the code (explanations give only purpose and how to take). | branch `claude/eager-tesla-g24rmm` | 13 Nov 2026 |
| WI-109 | Claude | Mostly done (13 Nov): `lang` and one main landmark on every page; skip link, named logo links, map title, tab roles and landmarks on the public page; login page ids unique and the dead Google, Facebook and "Forgot password" controls removed; reduced motion respected with a pause button; the Login button no longer covers the menu at 390 px; workspace focus moves to the new heading on a route change, errors are persistent alerts with a dismiss button, scroll padding follows the sticky bar, control borders and the bar's focus ring meet 3:1, `.good` status text meets 4.5:1, Hindi content carries `lang="hi"`. axe-core is clean on login, intake and the workspace pages tested. **Left:** one colour in the owner's team section (4.09:1) and a moderate heading-order note on the public page. | branch `claude/eager-tesla-g24rmm` | 13 Nov 2026 |
| WI-201 | Claude | Rules part done (13 Nov), branch `fix/WI-201-red-flag-rules`: the missed phrasings and the longer Hindi negation reach from v1's dev split are handled; v1 dev and test are now complete with no calm interview stopped (numbers in `BASELINES.md`). **Waiting on a clinician and a Hindi reviewer:** the v2 labelled set, the signed recall targets, and the ten "needs a clinician" answers. v1's test split shares its phrasings with dev, so it cannot show recall on unseen wording. | `fix/WI-201-red-flag-rules` | 13 Nov 2026 |
| WI-202 | Claude | Done (13 Nov): the code keeps the last questions for medicines and allergies and stores the patient's own words when the AI records nothing; with the AI unavailable, declined, unconfigured or over budget, the form's required questions finish the interview; failures the patient can't fix show a plain bilingual message and a "Tell reception" button that marks the visit in the queue (migration 11). Language first was done in WI-101. Fallback answers are kept in the patient's language, not English. | `feature/WI-202-required-questions-and-fallback` | 13 Nov 2026 |
| WI-203 | Claude | Done (13 Nov): an urgent stop writes an alert in the same transaction for the interview's doctor and the patient's clinicians; staff screens poll every 5 seconds and show a banner on any page until it is marked seen; the patient screen says to go to the reception desk now, reads it aloud, and holds for 60 seconds. Latency measured locally at 2.3 to 2.8 s (`BASELINES.md`); **not yet measured on a real kiosk and clinic network.** There is no reception role, so the alert goes to doctors' screens only. | `feature/WI-203-urgent-staff-alert` | 13 Nov 2026 |
| WI-210 | Claude | Built as an experiment, off by default (13 Nov): a second independent reading (the other provider first) is compared field by field; any difference becomes `unsure` with the other reading shown beside it, a medicine only one reading found is kept and marked, and no winner is picked or merged. A test proves a differing field is never `clear`. `ai_eval/run_eval.py --twice` reports disagreement rate, error rate and flag precision and recall. **Not yet measured:** this machine has no API keys, so the numbers must be run by someone with keys before the setting is switched on. | `feature/WI-210-read-twice` | 13 Nov 2026 |
| WI-261 | Claude | Done (13 Nov): ClinScribe drafting and transcription, the patient-pack brief and ask, and the LabLens job end their transaction before the AI, speech or Meko call (`db.release`), so a slow AI call holds no write lock; busy wait is a setting and a lock timeout is a plain 503; `backend/synthetic/load_test.py` with a threshold (pilot load: p95 write above 250 ms or any busy write means PostgreSQL). Before: 59% of writes refused at 5 s; after: none, p95 125 ms (`BASELINES.md`). Decision against the threshold: stay on SQLite for the single-host demo. Measured in this container, not yet on the real host. | `fix/WI-261-sqlite-contention` | 13 Nov 2026 |
| Phase 1 still open | | WI-112 (outside reviewers), WI-114 (repository rename, pitch deck) need people outside the code; D1 to D5 need the owner | | |
| WI-201 to WI-272 (Phase 2) | | Open | | |
| WI-280 to WI-289 (Phase 3) | | Open | | |
| D1 to D5 (owner decisions) | | Open | | |
