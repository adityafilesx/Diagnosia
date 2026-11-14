# Agent context: Curai

Read this first. It tells you what this project is, how it's built, what you must never
break, and what's still unfinished. Where it disagrees with the code, trust the code and fix
this file.

## What it is

**The project was renamed from Diagnosia to Curai** in November 2026. The domain is curai.in and the
public contact is support@curai.in. Settings are `CURAI_*` (the old `DIAGNOSIA_*` names are no longer
read), the default database is `backend/storage/curai.db`, and the session cookie is `curai_session`.
The GitHub repository may still carry the old name. Use "Curai" in everything new.

Curai is an AI-powered healthcare platform for India that brings patient records, medical
history and clinical tools together in one place. It helps doctors make better-informed decisions
and manage their workflows more efficiently, so care is more connected, organised and intelligent.
It started as a school project in 2023 and is being launched as a startup. India has too few
doctors, so consultations last about two minutes; every tool saves the doctor time or gives them
a fuller picture.

Six tools share one patient record, in the order of a visit:

| When | Tool | Who uses it | What it does | Status |
|---|---|---|---|---|
| Before | **DiagnoFast** | Doctors; patients answer | Interviews the patient by voice in their own language while they wait, fills the doctor's specialty form, adds past records from ABHA, and writes a one-page report | Built and tested live. ABHA is **simulated** |
| During | **ClinScribe** | Clinicians | Turns a consultation into a draft note the clinician checks and signs | Pilot |
| During | **LabLens** | Patients and clinicians | Reads lab reports into results a person confirms | Pilot, synthetic layouts only |
| After | **Prescription Analyzer** | Patients | Reads a photo of a prescription, decodes shorthand, and explains it in plain Hindi or English with audio, diet, yoga and schedule | Built and tested live |
| After | **ReferralLoop** | Doctors and specialists | Follows a referral from request to returned outcome | Pilot |
| After | **DischargeCare** | Hospital teams and families | Turns a discharge plan into a family checklist and team tasks | Pilot |

**Skin Cancer Detection and OptiKinesis were removed** as a product decision: they didn't fit one
shared patient record. Old CareFlow events from the skin tool stay readable through
`contract.RETIRED_MODULES`, but no new ones can be recorded. Don't bring either back without a
product decision. OptiKinesis lives on in its own repo, <https://github.com/HimalGarg/OptiKinesis>.

Removed tools (Talkie, Curl Counter, BMI Calculator, DocFinder, the old Symptom Checker and
Prescription Generator) and the sidelined VisionTrack were deleted along with the `archive/`
folder. They remain in git history if anyone needs to look at them.

More background: `PROJECT_DESCRIPTION.md` (the product, in plain language), `README.md` (setup),
`pitch/` (pitch statistics with sources, video script, slides).

## Repo layout

```
web/        The public site. The ONLY folder served to visitors.
            Webflow-style HTML + css/ js/ images/ icons/. No build step.
backend/    One FastAPI app: accounts and one folder per tool.
  app.py            Wires everything together and serves web/
  auth.py           Sign-up, login, sessions (Argon2, HttpOnly cookie)
  db.py             SQLite schema (users, sessions, intakes)
  migrations.py     Numbered schema changes for existing databases
  safety.py         Pilot readiness checks and signoffs
  private_files.py  Owner-only files and folders, on Linux, macOS and Windows
  settings_store.py Models, tool switches and defaults, set in the app
  operator_cli.py   Command-line setup, keys, backups, first administrator
  llm.py            Groq and Gemini calls, with fallback. ask(system, content, schema, tool)
  speech.py         Groq transcription/WAV speech; Edge neural question playback
  images.py         Upload checks (JPG/PNG, size)
  ratelimit.py      Limits on the public and costly routes, counted in SQLite
  synthetic/        Made-up test data: seed_accounts.py (logins), diagnofast_data.py and diagnofast_eval.py (labelled
                    interviews and a scorer), diagnofast_links.py (waiting interview links for manual testing)
  config.py         Settings from environment / .env
  prescription/     analyzer.py, shorthand.py, medicines.py, routes.py
  diagnofast/       agent.py, red_flags.py, abha.py, recordings.py, routes.py, forms/*.json
  records/          The shared patient record, access gate, audit, encrypted documents
  clinscribe/ lablens/ referralloop/ dischargecare/ reminders/   One folder per tool, each with its schema.sql
  careflow/         Activity timeline: event contract, outbox, delivery, routes
  integrations/     Optional Meko and YugabyteDB adapters, and AI run records
  patient_pack/     One searchable view of a patient's records, on Meko: render, sync, access, brief, routes
  tests/            pytest suite (no API keys needed)
pitch/      Pitch material.
datasets/, backend/storage/   Not in git (see below).
```

Pages: `index.html` (the public site, one catalogue of all 6 tools), `care.html` (the workspace,
where every tool runs), `*_hiw.html` info pages, the patient-facing `intake.html` (no account),
`login.html`. `diagnofast.html`, `prescription_analyzer.html` and `dashboard.html` only redirect
into the workspace.

The tool list has one source: `web/js/care/catalogue.js`, in the order of a visit. The rail and Home
read it. `index.html` repeats it by hand, and `test_site.py` checks that both agree.

## Run it

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
copy .env.example .env        # add the keys, see below
.\.venv\Scripts\python.exe -m uvicorn backend.app:app --reload
.\.venv\Scripts\python.exe -m pytest backend\tests
```

Open <http://127.0.0.1:8000>. `python -m backend.operator_cli setup-local` creates demo accounts, and
`./start_local.sh` (macOS/Linux; makes the venv, installs, then runs the next command) or
`python -m backend.synthetic.serve` seeds 14 staff and 60 patient records (30 with logins) if they
aren't there yet, then starts the server (`seed_accounts` alone only seeds).
Data sources and the plan for a labelled test set: `docs/DATA_SOURCES_AND_EVAL_PLAN.md`.
The audit register and the ordered fix plan (issues I-xx, work items WI-xxx): `docs/AUDIT_AND_REFINEMENT_PLAN.md`.
Pick work from it, write the failing test first, and update its status table.
Staff accounts are **not** self-declared: a doctor stays pending until an organization administrator
verifies them, and the first administrator is only created from the command line.

Without keys the site still runs and the tools show a friendly error. The tests use fakes, so
they never need keys or network access.

**Keys:** a free `GROQ_API_KEY` and `GEMINI_API_KEY`, each in Settings or in `.env` (git-ignored). One is enough. Ask the project owner
for it. Never put a key in code, a test, a doc, a commit or a chat message.

## How the tools work, and why

### Prescription Analyzer (`backend/prescription/`)
Handwriting reading is the risky part, so **nothing is explained until the patient confirms it**.
1. `/api/prescription/read` takes up to 4 photos of one prescription (front and back). Groq's
   vision model
   returns a fixed structure, marking each field `clear`, `unsure` or `unreadable`. It's told never
   to guess.
2. `shorthand.py` decodes OD, BD, TDS, HS, SOS, BBF, `1-0-1`, `x x 1` and so on with plain rules,
   not AI. It returns nothing rather than guessing. A fixed schedule is withheld when the marks
   disagree with the written frequency, and SOS/PRN medicines never get a fixed time.
3. `medicines.py` checks each name against a list of about 250,000 Indian medicines (rapidfuzz).
   Found, close ("Did you mean ...?") or not found. It only flags names. It **never changes** what
   was read. A "clear" name that isn't in the list is downgraded to "unsure".
4. The patient ticks each medicine that matches their prescription. Unticked or unreadable ones go
   to "ask your pharmacist" and **never reach the explanation step**.
5. `/api/prescription/explain` explains only the confirmed medicines, in the patient's language.
   It never changes a dose or suggests a substitute.

The photo isn't stored. A consent box says it goes to outside AI services, and each agreement is stored in
`consent_records` with the version of the words (`backend/records/consent.py`).

### DiagnoFast (`backend/diagnofast/`)
- Six specialty forms live in `forms/*.json`: general medicine, dermatology, cardiology, orthopedics, ENT and pediatrics (no form builder).
- Reception creates a **one-interview link** for each patient. The patient needs no account. The
  link stops working when the interview ends, after 24 hours unopened, or 2 hours after it starts
  (`CURAI_DIAGNOFAST_LINK_HOURS`, `CURAI_DIAGNOFAST_INTERVIEW_HOURS`). Only a hash of each link is stored.
  A reload carries on at the current question. An answer is saved only if its question is still
  open, and the page's `answer_key` makes a retry return the stored reply instead of saving twice.
- `intake.html` without a token opens the self-service specialty grid when
  `DIAGNOFAST_KIOSK_DOCTOR_ID` names a verified doctor. New visits go only to that doctor;
  public callers cannot attach a chart, choose a doctor or fetch ABHA records. The kiosk is
  unavailable when unconfigured or when that doctor loses verification, except in demo mode,
  where it falls back to the first verified doctor. The kiosk and the patient routes are
  rate-limited (`ratelimit.py`).
- The patient chooses a language first, then reads three consent lines and taps "I agree". ABHA records
  are a separate yes or no. `/start` needs the current wording's version and stores the consent. The
  words live in `backend/records/consent.py`: change the words, change the version.
- The interview is a **controlled loop**, not a free-running agent. `agent.advance` runs each
  answer. The AI picks the next question and extracts fields. `agent.apply_turn` keeps the rules in
  code: only fields on the form are kept, required fields must be filled, and there's a maximum of
  12 questions. The AI never diagnoses.
- **Medicines and allergies are always asked.** The code keeps the last questions for them
  (`agent.HIGH_RISK_FIELDS`) and stores the patient's own words if the AI records nothing.
- **With the AI down the form finishes the interview**: `agent.advance` falls back to the form's own
  required questions in order and keeps each answer as said. The report then fails and the doctor reads
  the answers. A failure the patient can't fix shows a plain message and a "Tell reception" button,
  which marks the visit "Asked for help" in the queue (`POST /patient/{token}/help`).
- Urgent symptoms (chest pain, trouble breathing and similar) end the interview at once and send
  the patient to reception. Two layers check for them. First `red_flags.screen` runs plain rules on
  the answer in English, Hindi and romanised Hindi, skipping clearly negated symptoms; a match stops
  the interview without calling the AI, so it works even when the AI is down. If the rules find
  nothing, the AI's `urgent_symptoms` still can. The rules deliberately skip words that usually
  describe history (stroke, heart attack, epilepsy, food poisoning) and leave those to the AI.
  They score 100% on the frozen v1 set (`docs/BASELINES.md`), which only proves v1's own phrasings
  are handled. Tune on the dev split only, and never edit v1.
- An urgent stop tells the patient to go to the reception desk now (no word about seriousness), holds
  that screen for a minute, and alerts staff: a notification for the interview's doctor and the patient's
  clinicians, which every staff screen polls every 5 seconds (`GET /api/diagnofast/alerts`) and shows as
  a banner until someone marks it seen. "Tell reception" raises the same kind of banner.
- Voice: Edge neural voices read questions in Indian English (Neerja) and Hindi (Swara).
  `CURAI_NEURAL_TTS=0` disables this service. After an 8-second neural timeout, English
  can use Groq WAV and Hindi uses the browser. Browser voice and typing remain fallbacks.
- The two-column interview shows live browser recognition and optional answer chips. Recordings
  stop at 28 seconds. Where live recognition is unavailable or incomplete, Groq prepares a
  transcript preview. Patients edit and confirm before sending. Confirmed text wins over audio
  recognition; original audio is retained only when encryption is configured. Gemini is preferred
  for the next-turn field normalization, with the normal configurable provider fallback.
- A link can belong to a patient record. Its report then appears in that patient's chart for the
  care team, through the normal access gate and audit log. Recordings are encrypted with the
  document key ring (`recordings.py`). Without a key ring, no recording is kept.
- `abha.py` has one interface with a simulated version. The records stay flagged `is_demo_data`, but the screens no longer say so (see Rules).
  Real ABHA access needs ABDM sandbox approval, an exit review and a security audit.
- Doctors see a queue (urgent patients first) and a printable requisition: local intake barcode,
  demographics, reported ROS, provenance-labeled history, investigation suggestions for physician
  review, and a blank physician workspace. H*/L* require supplied measured values and ranges;
  unasked symptoms are never normal. Original answers and recordings remain expandable. Reports print on one A4 page; if entries do not fit, the printout explicitly says it is incomplete
  and directs the doctor to the full report, original answers and transcript on screen. AI output remains unreviewed
  until a doctor presses "Mark as reviewed" (`POST /intakes/{id}/review`, stored as `reviewed_by` and
  `reviewed_at`); the queue and the chart show which reports are reviewed. `diagnofast/validate.py` checks
  each report on view and flags, never changes: a NORMAL row must cite an answer with a negative
  (`evidence_turns`), an H*/L* row needs a number and a printed range, and no investigation may name a
  medicine or dose.

## Rules that must not be broken

**Patient safety**
- The AI never diagnoses, never changes a dose, never suggests a substitute medicine, and never
  tells a patient something is or isn't serious.
- Unreadable or unconfirmed medicines are never explained.
- Doctors stay in charge. Every clinical tool assists and never decides.
- The owner removed the "DEMO DATA" and pilot labels from the screens for the demo. ABHA is still simulated and no tool is clinically validated, so bring them back before any real use, and say so when presenting.

**Privacy**
- Use **made-up patients** only. No real patient data until privacy and security are reviewed.
- Never commit prescription photos, audio or databases. `.gitignore` covers `Prescriptions*.jpg`,
  `backend/storage/` and `*.db`. Check before you `git add`.
- Groq receives this data in the United States, with no signed agreement yet. Keep personal details
  out of test photos. See `docs/CLINICAL_GOVERNANCE.md`.
- Meko has no signed agreement either, and states nothing about compliance. Patient packs stop when
  `ALLOW_REAL_PATIENT_DATA` is on. Don't remove that.

**Licences**
- **Never commit** the medicine dataset. It lives in git-ignored `datasets/`.
- The medicine dataset repo is MIT, but the data looks scraped from pharmacy sites, so its
  upstream permission is unconfirmed. Fine for a demo. Replace it before selling.

**Security**
- All SQL uses parameters. Passwords are Argon2. Session tokens are stored hashed.
- Every answer carries a content-security-policy (`backend/app.py`): strict for `care.html` and
  `intake.html`, and for the public pages each inline script is allowed by the hash of its text, worked
  out at start-up. Don't add inline event handlers, `<object>` tags or scripts from other sites. HSTS is
  sent when `CURAI_HTTPS=1`.
- A session ends after 30 idle minutes (`CURAI_SESSION_IDLE_MINUTES`, sliding, migration 14). The
  workspace marks requests made with no recent input as background (`X-Curai-Background`), so timed
  refreshes don't keep a session alive; a new timed request that is real use passes `active: true` to `api()`.
- Page text from patients and from the AI goes in with `textContent`, never `innerHTML`.
- Only `web/` is served. Don't add routes that serve other folders.
- Never log keys, patient text or full AI answers.

## Conventions

- Python 3.11. Match the style of the surrounding code, which is plain, with short comments that
  say **why**.
- New AI behavior goes behind a small function with a Pydantic schema, called through `llm.ask`.
  New speech behavior goes through `speech.py`.
- **Tests must not need keys or network.** Fake `llm.ask` and `speech` as the existing tests do. Put
  new tests in `backend/tests/` and run the whole suite before opening a pull request.
- The frontend is plain HTML, CSS and JavaScript. No framework and no build step. A new tool is a
  module in `web/js/care/`, one entry in `catalogue.js`, and the renderer in `app.js`. Its text goes
  through `h()`, and its colours come from the tokens in `care.css`. Only `intake.html` still uses
  `tools.css`. The public pages use the Webflow template in `index.css`.
- Only the microphone browser check is in the repo (`backend/tests/browser/`). After a UI change,
  test it in a real browser at desktop, tablet and phone widths.
- Don't add dependencies without a reason. `backend/requirements.txt` is the app. `backend/requirements.lock`
  pins every package for Linux and Windows and is what CI installs; after changing requirements, regenerate it with
  `uv pip compile backend/requirements.txt --universal --python-version 3.11 -o backend/requirements.lock` and run
  `pip-audit -r backend/requirements.lock`. CI (`.github/workflows/ci.yml`) runs the suite on both systems and the audit.
- A new tool's routes join the sweep in `test_security.py`. Add a real gate, not a list entry.
- Code and tests must work on both Windows and Linux. Protect sensitive files with
  `private_files.py`, because `chmod` does nothing on Windows. Pass `encoding="utf-8"` when reading
  text, because Windows otherwise uses cp1252.

## Features held for regulatory review

"Investigations to consider" in DiagnoFast and the patient-pack AI brief and questions are behind
Settings switches (`features.*` in `settings_store.HELD_FEATURES`) that start off, until a written
regulatory view arrives. Off means the API refuses them and nothing is stored or shown. Don't switch
them on by default.

## CareFlow

Events go through `backend/careflow/events.py`, never straight to a store. The outbox write shares the
transaction with the change, usually through the audit hook. Events hold no free text, so don't add
any: a new metadata key needs a reason. SQLite stays the record, and nothing flows back from MongoDB,
YugabyteDB or Meko. See `docs/integrations/`.

## Patient packs

One Meko datapack per patient, used as a search index. See `docs/integrations/PATIENT_PACKS.md`.

- A finished record is queued with `sync.enqueue`, in the same transaction. Only finished records go in:
  never a draft, a pending result, a transcript or an unconfirmed medicine.
- SQLite decides access, in `patient_pack/access.py`. Anything shown or given to the AI is read again
  from SQLite. Meko's text never reaches a prompt or a screen.
- Off by default, and stopped by `ALLOW_REAL_PATIENT_DATA`. There's no agreement with Meko, so made-up
  patients only.
- In demo mode every consent is recorded by default, marked `demo_default`, and the workspace has no
  consent panel. `care.consent_by_default` must stay false with real patient data. Before real use, the
  consent panel, the record of who opened a chart and the pilot warnings need bringing back.
- **FHIR export routes are live** (`GET /api/patients/{id}/fhir`, ClinScribe and LabLens exports), behind
  the normal access gate and audit log. Only ClinScribe shows an export button. The output is generic
  FHIR R4, not validated against ABDM profiles. See `docs/FHIR_MAPPING.md`.
- Clinical text never goes in Meko memory or conversations.
- Meko never returns a datapack slot, so live tests must not create them freely.

## Team workflow

- `main` is the shared, working version. **Don't commit to `main` directly.**
- Branch from `main` for each piece of work, one tool or feature per branch, named like
  `feature/lablens-trends` or `fix/intake-timeout`. Open a pull request into `main`.
- Run `pytest backend/tests` before opening it, and say what you tested by hand.
- Pull `main` into your branch often. Likely collision points are `backend/app.py` (router
  registration), `backend/requirements.txt`, `web/css/index.css` and `backend/db.py`.
- **Schema changes are migrations.** New tables go in a tool's `schema.sql`. A change to an existing
  table is a numbered step in `backend/migrations.py`, which runs once at start-up. Never ask anyone
  to delete a database.

## Known gaps and open work

- **SQLite contention.** One writer at a time. A request that has written anything (an audit row
  counts) holds the lock until it commits, so routes call `db.release(db)` before a slow outside call
  (AI, speech, Meko). A lock not had within `CURAI_DB_BUSY_SECONDS` is a plain 503.
  `python -m backend.synthetic.load_test` measures it; the PostgreSQL threshold and numbers are in
  `docs/BASELINES.md`. Do the same in any new route that calls the AI after writing.
- **Not hosted.** Netlify can't run this backend. It needs a Python host. Set `CURAI_HTTPS=1`
  in production.
- **Rate limits and the AI budget.** The kiosk, the patient interview routes, sign-up and login (per
  address), and every signed-in AI route (per account, plus a shared daily quota) are limited
  (`ratelimit.py`, counted in SQLite). `llm.ask` refuses once the deployment's daily tokens
  (`CURAI_AI_DAILY_TOKENS`) or spend (`CURAI_AI_DAILY_SPEND_USD`, priced from `CURAI_AI_PRICES`) are
  used up. Each AI attempt records its token counts; `operator_cli ai-usage --days 7` prints use and
  cost per tool. Speech transcription isn't counted in the token budget yet. Seeding scripts lift the
  limits for themselves with `ratelimit.suspended()`. Behind a reverse proxy,
  run uvicorn with `--proxy-headers --forwarded-allow-ips=<proxy>`, or every visitor shares the
  proxy's limit. Patient links can be guessed at only by luck (they're long random tokens).
- **Demo mode opens the kiosk.** With `DIAGNOFAST_KIOSK_DOCTOR_ID` unset, demo mode sends kiosk
  visits to the first verified doctor. Set it, or turn demo mode off, before real use.
- **Prescription reading varies between runs.** The same photo can read `Azu` one time and `Azee`
  the next, and a confident "clear" can still be wrong. The patient confirmation step is the safety
  net. **Read twice** is built as an experiment, off by default (Settings, `prescription.read_twice`):
  a second reading from the other provider, and `prescription/compare.py` marks every field the two
  disagree on as unsure, shows the other reading beside it, and never picks a winner. It doubles the
  reading cost. Measure it with `ai_eval/run_eval.py --twice` before switching it on.
- **Live on both, lightly.** A Hindi interview and a synthetic prescription work on Groq and Gemini.
  Reading quality on real handwriting and real Hindi speech is untested. Run `backend/tests/live/`
  with `CURAI_LIVE_TESTS=1` after changing a model.
- **Five tools use Gemini first** (`settings_store.READING_TOOLS`): prescription reading, explaining and planning the daily times, lab report reading, and the DiagnoFast interview turn, so patient interview answers go to Gemini first by default. Each has its own setting. The photo-reading choice came from a comparison on synthetic photos in `backend/tests/ai_eval/`. Re-run it when models change. `test_docs_match_code.py` fails if `docs/PLATFORM_SETUP.md` states a different count.
- **Model choice.** Each tool's Groq model is a setting, and Gemini has one model for the other tools. A
  failed call goes to the other provider, or providers take turns (`ai.strategy`). With one provider,
  a failed call is retried once. A DiagnoFast question times out at 45 seconds per provider.
- **Languages.** Hindi and English only.
- **ABHA** is simulated. **Regulation:** CDSCO's medical device software guidance (July 2026)
  may apply to clinical decision support. Get a regulatory review before any real use.
- **Cost** (rough, from measured tokens): about Rs 2 per prescription and Rs 2 to 2.50 per
  DiagnoFast intake, measured on the earlier Gemini setup. Re-measure on Groq before quoting prices.
- **Site text.** `terms_of_service.html` hasn't been reviewed for the new tools. The team section
  is owned by the project owner. Leave it.
- The earlier symptom-checker, prescription and BMI features are gone. Don't rebuild them.

## Things that look wrong but aren't

- Many tests patch `llm.ask`, `speech.speak` and the medicine list on purpose.

## Related

- **OptiKinesis** has its own repo: <https://github.com/HimalGarg/OptiKinesis>.
- Pitch: Mesa Venture League 2027 qualifier (video and optional deck). Material is in `pitch/`.
  Every statistic there has a source, and `pitch/MVL27_PITCH_STATS.md` lists numbers to avoid.
