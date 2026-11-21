# Curai: hackathon build plan

**Curai** is an AI healthcare platform for Indian hospitals. Six tools share one patient record. For
this hackathon we build on **DiagnoFast**, the tool that takes the patient's history before they see
the doctor. We add two partner technologies: **Sarvam AI** for Indian-language speech and **Neo4j**
for graphs.

**The core idea, which stays fixed after Mentor Round 1:** the patient tells their story by voice, in
their own language, on their own phone, before the consultation. The doctor then reads it in English
in under a minute.

This plan describes the code on `main` as of 21 Nov 2026 (commit `10f05ca`). We will revise it once at
Mentor Round 1, with sign-off, and then it is locked.

---

## Why this matters (the startup case)

**The problem.** The average Indian patient gets about two minutes with their doctor (BMJ Open, 2017).
One government doctor serves about 11,000 people (National Health Profile 2018). Yet the patient's
history alone leads to the diagnosis in 76% of cases (Peterson et al., West J Med, 1992), and history
is the part that gets rushed. Patients wait in long queues, and many struggle to describe their
symptoms, especially when the form is in a language they don't speak. About 1 in 5 rural Indians aged
7 and over cannot read (PLFS 2023-24), so the interview has to be spoken, not written.

**Who pays.** Hospitals and clinics pay, not patients. About 75% of outpatient care in India is private
(Brookings India, from NSS 2014 data), so private hospitals and clinics are our first customers. We
haven't set a price yet, either per intake or per doctor per month. The AI calls cost us about Rs 2 to
2.50 per intake, measured on an earlier Gemini setup. During this build we will measure it again on
today's Groq and Gemini setup, with Sarvam added.

**Why we win.**
1. **One shared patient record across six tools.** The interview isn't a PDF that gets filed and
   forgotten: it feeds the patient's chart, referrals and discharge.
2. **Safety comes first by design.** The AI never diagnoses. Plain rules stop urgent patients even when
   the AI is down, and nothing is explained to a patient until they have confirmed it.
3. **Indian languages, on the patient's side.** AI scribes such as Abridge (US), Eka Care and Augnito
   (India) help the doctor write up the consultation. DiagnoFast makes sure the consultation starts
   with the history already taken. 98% of Indian internet users use content in Indian languages
   (IAMAI–Kantar, 2024).

**The market.** India has about 4 billion doctor consultations a year (Praxis Global Alliance, 2021).
93.95 crore Indians already have an ABHA health ID (Health Ministry, July 2026), so the digital
infrastructure already exists.

**What incubation would unlock:** approval for the ABDM sandbox (so ABHA records are real), a regulatory
review (CDSCO's July 2026 guidance on medical device software may apply), a security audit, signed data
agreements with our AI and SMS vendors, and a first hospital pilot.

---

## 1. Where we are

On `main` the test suite runs with no keys and no network. 1,536 tests pass and 1 fails: a timing
check in the load test, which a commit on an open branch already fixes.

| Area | Works today | Mocked, hardcoded or missing |
|---|---|---|
| **Getting to the interview** | Reception creates a one-interview link. Only a hash of the link is stored. It expires 24 h after it's made if nobody opens it, or 2 h after the interview starts, and a reload carries on at the same question. A self-service kiosk on a tablet handles walk-ins. | Reception copies the link by hand. There's no SMS or WhatsApp, because no provider is connected. There are no OPD appointments, slots, phone logins or QR codes. The link stops working when the interview ends, so the patient sees only "Thank you". |
| **Languages and voice** | English and Hindi only. Questions are read aloud by Edge neural voices (Neerja, Swara) in demo mode, Groq's English voice, or the browser's own voice, and the patient can always type. Live browser recognition plus a Groq Whisper preview turn speech to text, and the patient edits and confirms it. Recordings stop at 28 s. | No other language. The language list is fixed in the code, the forms, the consent words and the screens. Outside demo mode, Hindi is read only by the browser's voice. Mixed Hindi and English (Hinglish) gets no special handling. Answers aren't translated: the doctor sees the patient's Hindi words and English form fields, but no English line beside each answer. |
| **The interview** | The interview runs as a controlled loop. The AI chooses the next question and fills in the form, and the code enforces the rules: only fields on the form are kept, there's a 12-question limit, and medicines and allergies are always asked. If the AI is down, the form asks its own questions. There are six specialty forms. | The AI chooses follow-up questions using only the form. There's no complaint-specific approach (such as SOCRATES for pain) and no rule for probing vague answers. During the interview the AI doesn't see the patient's age, sex, past visits or ABHA records, so it can re-ask things we already know. |
| **Safety** | Plain rules for urgent symptoms (English, Hindi, romanised Hindi; they skip "no chest pain") run before the AI, and the AI keeps its own urgent list. An urgent stop sends the patient to reception and raises a staff banner within 5 s. There's a "Tell reception" button. Consent words are shown, versioned and stored. | The rules score 100% on our frozen test set, but that only proves they handle the phrasings in that set. A Hindi speaker still has to approve the Hindi consent words. No other language has urgent-symptom rules. |
| **The doctor's side** | A queue with urgent patients first, and a one-page A4 report. The patient's own answers and encrypted recordings sit beside the report. "Mark as reviewed" stamps who reviewed it and when. `validate.py` flags report rows the answers don't support, because each row cites the answers it came from. | Patients get no queue number or department. Doctors can't give feedback on the questions asked. The links between report rows and answers exist in the data but are never drawn. |
| **Platform** | The shared patient record, access checks, audit log, CareFlow event outbox (no free text), rate limits, a daily AI budget and FHIR export. | **ABHA is simulated:** every patient gets the same made-up records. The app isn't hosted. There's no Neo4j. **Sarvam was removed from the code on 31 Oct 2026**, and a test (`test_platform.py`) fails if the name comes back. No tool is clinically validated, and the "demo data" labels were taken off the screens for the demo. |
| **Other tools** | Prescription Analyzer is built and tested live. ClinScribe, LabLens, ReferralLoop and DischargeCare are at pilot stage. | They aren't part of the finale build (see the appendix). |

---

## 2. Where we will be at 12 PM on 22 Nov

### The core flow (all six steps working end to end, on made-up patients)

1. **Booking and link.** Reception books a patient into a doctor's slot, and the department comes from
   the booking. Curai shows the interview link as an SMS or WhatsApp message in a **demo outbox**, to
   arrive at booking time or the evening before. No real message is sent, because no SMS provider is
   connected. The message holds only the link and nothing clinical. The kiosk and reception tablet
   stay as the fallback for patients without smartphones, elderly patients and walk-ins.
2. **Slot QR login.** Each slot shows a QR code in the hospital. The patient scans it, enters their phone
   number and types a one-time code (OTP). In the demo the OTP appears on screen, because there's no SMS
   provider. The server stores only a hash of the code, which expires after 5 minutes and allows 3
   tries. The patient then picks their own name, shown masked (for example "R\*\*\* K\*\*\*, 34"), from
   that slot's bookings that carry the verified phone number, because families often share one phone.
   The server then issues a normal one-interview link, so the existing hash and expiry rules apply.
   Attempts are rate-limited per slot and per phone. **A name and phone number alone never log anyone
   in, because neither is secret.**
3. **Language and consent.** Hindi and English stay the defaults and work exactly as they do today. Tamil
   is a new option on the language screen. The Tamil consent words are translated in advance, reviewed by
   a Tamil speaker and versioned in `consent.py`. They name Sarvam AI as a service that receives the
   answers. Consent words are never translated live.
4. **A voice interview on the patient's own phone, with follow-up questions guided by a graph.** Sarvam
   Saarika turns speech into text (Hindi, English, Hinglish and Tamil), and Sarvam Bulbul reads each
   question aloud. A Neo4j graph links each complaint to its follow-up questions, associated symptoms and
   red-flag questions, and the interview walks the graph to pick the next question. The AI only words
   the question and pulls out the answers. The questions sound more like a doctor's:
   - follow-ups that fit the complaint (SOCRATES for pain; duration, pattern, chills, rash and travel
     for fever)
   - things we already know are confirmed, not asked again ("Last visit you said you take metformin. Are
     you still taking it?")
   - vague answers are probed ("sometimes" becomes "how many times a week?"; "a lot" becomes "from 1 to
     10?")
   - one short question at a time, with a brief acknowledgement, in simple words or Hinglish

   The code's rules don't change: the 12-question limit, medicines and allergies always asked, and
   urgent-symptom rules checked first. Tamil gets urgent-symptom rules written natively in Tamil.
5. **The patient sees their queue number and department.** Sarvam Bulbul reads them aloud in the
   patient's language. The patient sees "What you told us" (their own words) straight away, and the AI
   summary only after the doctor presses "Mark as reviewed". An urgent stop works as it does today: "Go
   to reception now". After the interview the link becomes a read-only status page until the end of the
   day.
6. **The doctor reads an English report.** For each answer that wasn't in English, the report shows the
   patient's original words beside a machine translation from Sarvam Mayura, labelled as a translation.
   A Neo4j **evidence graph** traces each report row to the answer it came from and that answer's
   recording. A **history graph** links the patient to their past visits, symptoms, medicines, allergies
   and doctors. At review time the doctor is asked one question, "Anything you wish had been asked?",
   and the answers are scored with `diagnofast_eval.py`.

**Walk-ins.** A walk-in who doesn't know which department to visit gets a department suggestion from the
graph, and **only staff see it**. Staff confirm it before the patient sees anything, because sending
patients to a department by AI is close to triage, where CDSCO rules may apply.

### Stretch (only if the core flow passes all its tests by 6 AM)

- Bengali as a second new language, with the same checklist as Tamil.
- Sarvam as an optional third AI provider in `llm.py`.
- Prescription Analyzer explanations and audio in Tamil. `crosscheck.py`, which is on the open branch and
  not yet in `main`, must first learn Tamil number words and Tamil digits.
- ReferralLoop network view, and medicine, allergy and duplicate-salt conflicts across doctors, flagged
  to the doctor or pharmacist only.

---

## 3. User segments

- **Primary: OPD outpatients in Indian hospitals.** Especially patients who speak Hindi, Hinglish or
  Tamil more easily than English, who have a smartphone and who wait in long queues.
- **OPD doctors.** They read the history in under a minute, review it and say what was missing.
- **Reception and triage staff.** They book patients, display the slot QR codes, confirm departments for
  walk-ins, respond to urgent alerts, and run the kiosk for patients without smartphones.
- **Families and caregivers.** They share the phone, answer for an elderly parent or a child (there's a
  pediatrics form), and hear the queue number.

The buyer is the hospital or clinic.

---

## 4. Partner technology: Sarvam AI and Neo4j

We are not using Arduino. Curai is software that runs on the phones and tablets hospitals and patients
already have.

| Tech | The product need it solves | Where it goes |
|---|---|---|
| **Sarvam Saarika** (speech to text) | Better recognition of Hindi and Hinglish, the default languages, and Tamil as a new one | A new provider in `speech.py`. Groq Whisper and live browser recognition stay as the fallback, and the patient still confirms the text |
| **Sarvam Bulbul** (text to speech) | Natural voices for questions, the queue number and the department, including Tamil | `speech.py`. Edge (Neerja, Swara), Groq, the browser's voice and on-screen text stay as fallbacks |
| **Sarvam Mayura** (translation) | The doctor reads English beside the patient's own words | Runs on the text the patient confirmed. We don't use Saaras, which translates straight from audio, for the record, because the patient's confirmed text takes priority over audio |
| **Neo4j: question graph** | Follow-up questions that fit the complaint, with the urgent-symptom questions to ask | Loaded from a reviewed, versioned file in git and read by `agent.advance` inside the existing controlled loop |
| **Neo4j: history graph** | Personal context, so the interview confirms what we know instead of re-asking | A read-only copy of finished records, used for the interview and the doctor's report |
| **Neo4j: evidence graph** | Lets the doctor trust or challenge each report row | Report row → cited answer → recording. Works alongside `validate.py` |
| **Neo4j: department suggestion** | Routing walk-ins without AI deciding for the patient | Shown to staff only, and staff confirm it |

## Guardrails

- **SQLite stays the record.** Neo4j is a read-only copy. A reference is queued in the same database
  transaction as the change, as patient packs already do, and the worker reads the finished record
  from SQLite. CareFlow events carry no free text, so they can trigger an update but can't supply the
  words. Nothing flows back from Neo4j to SQLite.
- **SQLite decides access.** Neo4j holds IDs and coded terms. Any words shown on screen or sent to the
  AI are read again from SQLite, after the normal access check and audit log.
- **The graph makes suggestions to staff and never diagnoses.** A red-flag node only adds a screening
  question. It never decides anything, and it never replaces the plain urgent-symptom rules. The AI
  never diagnoses and never says that anything is or isn't serious.
- **Made-up patients only, in Neo4j and in Sarvam.** Both stop when `ALLOW_REAL_PATIENT_DATA` is on,
  just as patient packs do. Neo4j runs locally in Docker, so nothing leaves the laptop.
- **Both sit behind Settings switches** and fall back to today's behaviour when switched off or
  unreachable: Hindi and English, today's voices, and follow-ups chosen by the AI alone.
- **Bringing Sarvam back is a deliberate product decision.** It was removed on 31 Oct 2026. Bringing it
  back means adding its host to the allowed AI hosts, naming it in the consent words (with a new
  version), adding a vendor entry in `docs/CLINICAL_GOVERNANCE.md`, and changing the test that blocks
  the name so that it still blocks Anthropic. Sarvam is an Indian provider and may keep data in India,
  unlike Groq (US, no agreement), but this is **to be confirmed in writing**.
- **Fixed text is reviewed, never translated live.** This covers the consent words, the form's own
  questions (used when the AI is down), the urgent and thank-you messages, and the screen text.
- **Tests fake both services** and need no keys or network. The `neo4j` driver goes into
  `backend/requirements-integrations.txt`, next to the other optional database drivers. The QR library
  (`segno`) goes into `requirements.txt`, and then we regenerate `requirements.lock`. We run
  `pip-audit` on both.
- **Honesty:** ABHA is simulated, and no tool is clinically validated. The question graph hasn't been
  reviewed by a clinician. The demo labels must come back before any real use, and we say so when we
  present.

## 5. Definition of done

A patient scans their slot QR, completes a voice interview on their own phone in Hindi, English or Tamil
with graph-guided follow-up questions, and sees their queue number and department in their language,
while the doctor opens an English report with the patient's original words, a labelled translation and
a Neo4j history and evidence graph — on made-up patients, with the full test suite passing without keys.

## Timeline (21 Nov 4 PM → 22 Nov 12 PM)

| When | Work |
|---|---|
| Fri 4–5 PM | Bring `iiitd` up to date with the open feature branch (19 commits not yet in `main`). Add keys to `.env`, start Neo4j in Docker, seed made-up bookings, and write the failing tests first. |
| 5–8 PM | Three parallel tracks. **A:** bookings, slot QR, OTP, link issue and rate limits. **B:** Sarvam in `speech.py` (speech to text, voice, translation) with fallbacks and fakes. **C:** question graph file, Neo4j loader and the read-only copy of records. |
| Mentor Round 1 | Present this plan, agree the one revision, then lock it. |
| 8 PM–12 AM | Tamil pack: consent words, form questions, screen text, fixed messages and urgent-symptom rules, reviewed by a Tamil speaker. The graph starts choosing the next question inside `agent.advance`. |
| 12–4 AM | Patient status page: queue number, department, "What you told us", read aloud. Doctor's report: original words and translation, evidence graph, history graph, feedback question. Department suggestion for walk-ins, shown to staff. |
| 4–6 AM | Full test suite and `pip-audit`. **Checkpoint:** stretch work starts only if the core flow passes. |
| 6–9 AM | Real-browser tests on a phone, a tablet and a desktop. A live run on Sarvam and Neo4j with made-up patients. Record a backup demo video. |
| 9–11 AM | Fix bugs, do stretch work if there's time, and update `agent_context.md` and `CLINICAL_GOVERNANCE.md`. |
| **11 AM–12 PM** | **Freeze: no new code. Rehearse the demo twice.** |

## Risks and fallbacks

| Risk | Fallback |
|---|---|
| Sarvam is down, out of quota or slow | Hindi and English carry on with today's voices and Groq Whisper. Tamil is typed and read by the browser's voice. Keep the backup video ready. |
| The Tamil urgent-symptom rules miss a phrasing | The AI's own urgent list still checks every answer, and the English rules also run on the translation. We say plainly that the Tamil rules are a small reviewed list, not validated. |
| No Tamil speaker can review the text in time | Leave Tamil switched off. Demo Hindi, English and Hinglish on Sarvam, and say why. |
| Neo4j is down | The AI chooses follow-ups alone, as it does today. The evidence view is drawn straight from SQLite. |
| The phone microphone needs HTTPS | Serve the demo over HTTPS through a tunnel. Typing and the tablet still work. |
| Venue Wi-Fi fails | Use a phone hotspot. Neo4j and SQLite are local. |
| AI rate limits during the demo | Groq and Gemini fall back to each other. Set the daily AI budget so a runaway test can't use it up. |
| The scope slips | Hold the 6 AM checkpoint. Stretch goes first, then Bengali, then the walk-in suggestion. |
| The branch base differs from the latest work | Merge the open feature branch before 5 PM so new migrations don't clash with migration 14. |

---

## Appendix A: Sarvam AI and Neo4j across the platform (beyond the finale)

None of this is promised for 22 Nov.

| Tool | Sarvam AI | Neo4j |
|---|---|---|
| **DiagnoFast** | More Indian languages, each with reviewed consent words, forms and urgent-symptom rules | Questions refined with doctors' feedback. Fine-tuning comes later, and only on reviewed real data |
| **ClinScribe** | Transcribing consultations that mix languages | Links between signed notes, visits and problems |
| **LabLens** | Results read aloud, with no words about seriousness | Trends for each test across reports |
| **Prescription Analyzer** | Explanations and audio in Tamil and more, once `crosscheck.py` knows each language's numbers | Medicine, allergy and duplicate-salt conflicts across doctors, flagged to the doctor or pharmacist only. A patient is never shown a cheaper or different brand to switch to |
| **ReferralLoop** | Referral status by SMS or voice in the patient's language | Network view: referral paths, overdue loops, specialist load |
| **DischargeCare** | The family's checklist in their language | Which tasks depend on which |
| **Platform** | Booking SMS. Sarvam as an optional AI provider | A CareFlow journey graph and analytics on how patients move through the hospital |

## Appendix B: build notes (where the code changes)

- **Bookings and slots:** a new table in a tool `schema.sql` (slot, doctor, department or form, patient,
  phone, queue number). Changes to `intakes` are numbered migrations.
- **OTP:** hashed, 5-minute expiry, 3 tries, rate-limited per slot and per phone (`ratelimit.py`). Shown
  on screen only in demo mode.
- **Status page:** a finished link can read its own status (queue number, department, the patient's own
  answers, and the summary once reviewed) until the end of the day. It can never answer questions again.
- **Languages:** `speech.Language`, the six forms (questions and answer chips), `intake.js` screen text,
  the urgent and thank-you messages in `agent.py`, and `consent.py` all gain `ta-IN`, each reviewed. The
  negative words in `validate.py` gain Tamil, or the check runs on the English translation.
- **Interview context:** `agent.next_turn` also receives age, sex, past visits and simulated ABHA records,
  each labelled with its source. ABHA items are confirmed with the patient, never copied in as fact.
- **Slow calls:** routes call `db.release(db)` before any Sarvam or Neo4j call, as they do before AI
  calls today.
- **Tests:** fakes for Sarvam and Neo4j, new routes added to the sweep in `test_security.py`, and the
  Tamil urgent-symptom rules scored on a labelled set split into dev and test.
