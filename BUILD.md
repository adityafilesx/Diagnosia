# Diagnosia: hackathon build plan

**Diagnosia** is an AI healthcare platform for Indian hospitals. Six tools share one patient record. For
this hackathon we build on **DiagnoFast**, the tool that takes the patient's history before they see
the doctor. We add two partner technologies: **Sarvam AI** for better Hindi and English speech, and
**Neo4j** for graphs.

**The core idea, which stays fixed after Mentor Round 1:** the patient tells their story by voice, in
Hindi, English or a mix of the two (Hinglish), on their own phone, before the consultation. The doctor
then reads it in English in under a minute.

**Languages.** Hindi and English stay the only languages and the defaults, and Hinglish is handled within
them. Nothing about either may get worse. We are not adding other languages in this build.

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
3. **The patient's own language, on the patient's side.** AI scribes such as Abridge (US), Eka Care and
   Augnito (India) help the doctor write up the consultation. DiagnoFast makes sure the consultation
   starts with the history already taken, in Hindi, English or Hinglish. 98% of Indian internet users
   use content in Indian languages (IAMAI–Kantar, 2024).

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
| **Languages and voice** | English and Hindi. Questions are read aloud by Edge neural voices (Neerja, Swara) in demo mode, Groq's English voice, or the browser's own voice, and the patient can always type. Live browser recognition plus a Groq Whisper preview turn speech to text, and the patient edits and confirms it. Recordings stop at 28 s. | Outside demo mode, Hindi is read only by the browser's voice, because Groq has no Hindi voice. Hinglish gets no special handling. Consent lines and the urgent message aren't read aloud to patients who can't read well. Answers aren't translated: the doctor sees the patient's Hindi words and English form fields, but no English line beside each answer. |
| **The interview** | The interview runs as a controlled loop. The AI chooses the next question and fills in the form, and the code enforces the rules: only fields on the form are kept, there's a 12-question limit, and medicines and allergies are always asked. If the AI is down, the form asks its own questions. There are six specialty forms. | The AI chooses follow-up questions using only the form. There's no complaint-specific approach (such as SOCRATES for pain) and no rule for probing vague answers. During the interview the AI doesn't see the patient's age, sex, past visits or ABHA records, so it can re-ask things we already know. |
| **Safety** | Plain rules for urgent symptoms (English, Hindi, romanised Hindi; they skip "no chest pain") run before the AI, and the AI keeps its own urgent list. An urgent stop sends the patient to reception and raises a staff banner within 5 s. There's a "Tell reception" button. Consent words are shown, versioned and stored. ABHA records have their own yes or no. | The rules score 100% on our frozen test set, but that only proves they handle the phrasings in that set. A Hindi speaker still has to approve the Hindi consent words. |
| **The doctor's side** | A queue with urgent patients first, and a one-page A4 report. The patient's own answers and encrypted recordings sit beside the report. "Mark as reviewed" stamps who reviewed it and when. `validate.py` flags report rows the answers don't support, because each row cites the answers it came from. | Patients get no queue number or department. Doctors can't give feedback on the questions asked. The links between report rows and answers exist in the data but are never drawn. |
| **Platform** | The shared patient record, access checks, audit log, CareFlow event outbox (no free text), rate limits, a daily AI budget and FHIR export. | **ABHA is simulated:** every patient gets the same made-up records. The app isn't hosted. There's no Neo4j. **Sarvam was removed from the code on 31 Oct 2026**, and a test (`test_platform.py`) fails if the name comes back. No tool is clinically validated, and the "demo data" labels were taken off the screens for the demo. |
| **Other tools** | Prescription Analyzer is built and tested live. ClinScribe, LabLens, ReferralLoop and DischargeCare are at pilot stage. | They aren't part of the finale build (see the appendix). |

---

## 2. Where we will be at 12 PM on 22 Nov

### The core flow (all six steps working end to end, on made-up patients)

1. **Booking and link.** Reception books a made-up patient into a doctor's slot on a reception screen.
   Each booking gets a queue number for that doctor that day, and the department comes from the booking.
   Diagnosia shows the interview link as an SMS or WhatsApp message in a **demo outbox**, to arrive at
   booking time or the evening before. No real message is sent, because no SMS provider is connected
   (`reminders/adapters.py` has none). The message is neutral and holds only the link. The kiosk and
   reception tablet stay as the fallback for patients without smartphones, elderly patients and walk-ins.
2. **Slot QR login.** Each slot shows a QR code in the hospital, drawn on the server as SVG. The patient
   scans it, enters their phone number and types a one-time code (OTP). In the demo the OTP appears on
   screen, because there's no SMS provider. The server stores only a hash of the code, which expires
   after 5 minutes and allows 3 tries. The patient then picks their own name, shown masked (for example
   "R\*\*\* K\*\*\*, 34"), from **only** that slot's bookings that carry the verified phone number, because
   families often share one phone. The server then issues a normal one-interview link, so the existing
   hash and expiry rules apply. Attempts are rate-limited per slot and per phone. **A name and phone
   number alone never log anyone in, because neither is secret.**
3. **Language and consent.** The patient chooses Hindi or English, which work exactly as they do today.
   The consent words name Sarvam AI as a service that receives the answers, and get a new version. Each
   consent line can be read aloud by Sarvam Bulbul for patients who can't read well. ABHA records stay
   behind their own separate yes or no, which the new login doesn't touch.
4. **A voice interview on the patient's own phone, with follow-up questions guided by a graph.** Sarvam
   Saarika turns speech into text, with better recognition of Hindi, English and Hinglish. Sarvam Bulbul
   reads each question aloud in a natural Hindi or English voice, including outside demo mode. A Neo4j
   graph links each complaint to its follow-up questions, associated symptoms and red-flag screening
   questions, and the interview walks the graph to pick the next question. The AI only words the
   question and pulls out the answers. The questions sound more like a doctor's:
    - follow-ups that fit the complaint (SOCRATES for pain; duration, pattern, chills, rash and travel
      for fever)
    - things we already know (age, sex, past visits, simulated ABHA records, each labelled with its
      source) are confirmed, not asked again ("Last visit you said you take metformin. Are you still
      taking it?"). ABHA items are confirmed with the patient, never copied in as fact.
    - vague answers are probed ("sometimes" becomes "how many times a week?"; "a lot" becomes "from 1
      to 10?")
    - one short question at a time, with a brief acknowledgement, in simple words, and in Hinglish when
      the patient uses it

    The code's rules don't change: the 12-question limit, medicines and allergies always asked, and the
    urgent-symptom rules checked first. Red-flag nodes in the graph only add screening questions.

5. **The patient sees their queue number and department.** After the interview the link becomes a
   read-only status page until the end of the day. Sarvam Bulbul reads the queue number and department
   aloud. The patient sees "What you told us" (their own words) straight away, and the AI summary only
   after the doctor presses "Mark as reviewed". An urgent stop works as it does today ("Go to reception
   now"), and the message is also spoken aloud.
6. **The doctor reads an English report.** For each Hindi answer, the report shows the patient's original
   words beside an English translation of the text the patient confirmed, made by Sarvam Mayura and
   labelled "machine translation". A Neo4j **evidence graph** traces each report row to the answer it came
   from and that answer's recording. A **history graph** links the patient to their past visits,
   symptoms, medicines, allergies and doctors. At review time the doctor is asked one question, "Anything
   you wish had been asked?". The answers are stored and scored with `diagnofast_eval.py`, and good ones
   become examples in the interview prompt. Fine-tuning comes later, and only on reviewed real data.

**Walk-ins.** A walk-in who doesn't know which department to visit gets a department suggestion from the
graph, and **only staff see it**. Staff confirm it before the patient sees anything, because sending
patients to a department by AI is close to triage, where CDSCO rules may apply.

### Stretch (only if the core flow passes all its tests by 6 AM)

- Sarvam as an optional third AI provider in `llm.py`, inside the existing fallback.
- ReferralLoop network view: referral paths, overdue loops, specialist load.
- Medicine, allergy and duplicate-salt conflicts across doctors, flagged to the doctor or pharmacist only.
  A patient is never shown a brand-to-generic substitute.

---

## 3. User segments

- **Primary: OPD outpatients in Indian hospitals.** Especially patients who speak Hindi or Hinglish more
  easily than English, or who read with difficulty, who have a smartphone and who wait in long queues.
- **OPD doctors.** They read the history in under a minute, review it and say what was missing.
- **Reception and triage staff.** They book patients, display the slot QR codes, confirm departments for
  walk-ins, respond to urgent alerts, and run the kiosk for patients without smartphones.
- **Families and caregivers.** They share the phone, answer for an elderly parent or a child (there's a
  pediatrics form), and hear the queue number.

The buyer is the hospital or clinic.

---

## 4. Partner technology: Sarvam AI and Neo4j

We are not using Arduino. Diagnosia is software that runs on the phones and tablets hospitals and
patients already have.

| Tech | The product need it solves | Where it goes |
|---|---|---|
| **Sarvam Saarika** (speech to text) | Better recognition of Hindi, English and Hinglish speech | A new provider in `speech.py`, tried first. Groq Whisper stays as the fallback, with its no-speech filtering, and the patient still confirms the text |
| **Sarvam Bulbul** (text to speech) | A natural Hindi voice that also works outside demo mode (today Edge runs only in demo mode, and Groq has no Hindi voice). Reads questions, consent lines, the queue number, the department and the urgent message | `speech.py`, tried first. Edge (Neerja, Swara, demo mode only), Groq English, the browser's voice and typing stay as fallbacks, in today's order |
| **Sarvam Mayura** (translation) | The doctor reads English beside the patient's own Hindi words | Runs on the text the patient confirmed. We don't use Saaras, which translates straight from audio, for the record, because the patient's confirmed text takes priority over audio |
| **Sarvam as a vendor** | An Indian provider that may keep data in India, unlike Groq (US, no agreement). **To be confirmed in writing** | `docs/CLINICAL_GOVERNANCE.md` vendor section, and the consent words |
| **Neo4j: question graph** | Follow-up questions that fit the complaint, with the red-flag screening questions to ask | Loaded from a versioned seed file in git, marked "not clinically reviewed", and read by `agent.advance` inside the existing controlled loop |
| **Neo4j: history graph** | Personal context, so the interview confirms what we know instead of re-asking | A read-only copy of finished records, used for the interview and the doctor's report |
| **Neo4j: evidence graph** | Lets the doctor trust or challenge each report row | Report row → cited answer → recording, drawn in plain JavaScript and SVG. Works alongside `validate.py`. With Neo4j down, it's built from SQLite |
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
- **Hindi and English must not get worse.** The urgent-symptom rules for English, Hindi and romanised
  Hindi stay as they are and must still score 100% on the frozen v1 set, which is never edited. New
  Hinglish phrasings go into the dev split only.
- **Made-up patients only, in Neo4j and in Sarvam.** Both stop completely when `ALLOW_REAL_PATIENT_DATA`
  is on, just as patient packs do. Neo4j runs locally in Docker, so nothing leaves the laptop.
- **Every new feature sits behind a Settings switch that starts off**, and falls back to today's
  behaviour when switched off or unreachable: today's voices and speech, and follow-ups chosen by the
  AI alone.
- **Bringing Sarvam back is a deliberate product decision.** It was removed on 31 Oct 2026. Bringing it
  back means adding its host to the allowed AI hosts, naming it in the consent words (with a new
  version), adding a vendor entry in `docs/CLINICAL_GOVERNANCE.md`, and changing the test that blocks
  the name so that it still blocks Anthropic.
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

A patient scans their slot QR, completes a voice interview on their own phone in Hindi, English or
Hinglish with graph-guided follow-up questions, and sees their queue number and department read aloud in
their language, while the doctor opens an English report with the patient's original words, a labelled
translation and a Neo4j history and evidence graph — on made-up patients, with the full test suite
passing without keys.

## Timeline (21 Nov 4 PM → 22 Nov 12 PM)

| When | Work |
|---|---|
| Fri 4–5 PM | Bring `iiitd` up to date with the open feature branch (19 commits not yet in `main`). Add keys to `.env`, start Neo4j in Docker, seed made-up bookings, and write the failing tests first. |
| 5–8 PM | Three parallel tracks. **A:** bookings, reception screen, demo outbox, slot QR, OTP, link issue and rate limits. **B:** Sarvam in `speech.py` (speech to text, voice, translation) with fallbacks and fakes; consent words naming Sarvam, read aloud. **C:** question graph seed file, Neo4j loader and the read-only copy of records. |
| Mentor Round 1 | Present this plan, agree the one revision, then lock it. |
| 8 PM–12 AM | The graph starts choosing the next question inside `agent.advance`. Known context, probing vague answers, a more human tone, and Hinglish phrasings for the dev split. |
| 12–4 AM | Patient status page: queue number, department, "What you told us", read aloud, urgent message spoken. Doctor's report: original words and translation, evidence graph, history graph, feedback question. Department suggestion for walk-ins, shown to staff. |
| 4–6 AM | Full test suite and `pip-audit`. **Checkpoint:** stretch work starts only if the core flow passes. |
| 6–9 AM | Real-browser tests on a phone, a tablet and a desktop. A live run on Sarvam and Neo4j with made-up patients. Record a backup demo video. |
| 9–11 AM | Fix bugs, do stretch work if there's time, and update `agent_context.md` and `CLINICAL_GOVERNANCE.md`. |
| **11 AM–12 PM** | **Freeze: no new code. Rehearse the demo twice.** |

## Risks and fallbacks

| Risk | Fallback |
|---|---|
| Sarvam is down, out of quota or slow | Hindi and English carry on with today's voices (Edge in demo mode, Groq English, the browser) and Groq Whisper. No translation line, and the doctor reads the patient's own words. Keep the backup video ready. |
| Sarvam's recognition of Hinglish is worse than expected | The patient still edits and confirms every answer, and the Settings switch puts Groq Whisper back first. |
| Neo4j is down | The AI chooses follow-ups alone, as it does today. The evidence view is drawn straight from SQLite. |
| The phone microphone needs HTTPS | Serve the demo over HTTPS through a tunnel. Typing and the tablet still work. |
| Venue Wi-Fi fails | Use a phone hotspot. Neo4j and SQLite are local. |
| AI rate limits during the demo | Groq and Gemini fall back to each other. Set the daily AI budget so a runaway test can't use it up. |
| The scope slips | Hold the 6 AM checkpoint. Stretch goes first, then the walk-in suggestion. |
| The branch base differs from the latest work | Merge the open feature branch before 5 PM so new migrations don't clash with migration 14. |

---

## Appendix A: Sarvam AI and Neo4j across the platform (beyond the finale)

None of this is promised for 22 Nov.

| Tool | Sarvam AI | Neo4j |
|---|---|---|
| **DiagnoFast** | Better voices and recognition as Sarvam's models improve | Questions refined with doctors' feedback, which first become prompt examples. Fine-tuning comes later, and only on reviewed real data |
| **ClinScribe** | Transcribing Hindi, English and Hinglish consultations | Links between signed notes, visits and problems |
| **LabLens** | Results read aloud, with no words about seriousness | Trends for each test across reports |
| **Prescription Analyzer** | Voice reminders to take each confirmed medicine, read in Hindi or English | Medicine, allergy and duplicate-salt conflicts across doctors, flagged to the doctor or pharmacist only. A patient is never shown a cheaper or different brand to switch to |
| **ReferralLoop** | Referral status by SMS or voice in Hindi or English | Network view: referral paths, overdue loops, specialist load |
| **DischargeCare** | The family's checklist read aloud | Which tasks depend on which |
| **Patient packs** | None | A structured index beside Meko. Access is still decided in SQLite, and the content is re-read from SQLite |
| **Platform** | Booking SMS. Sarvam as an optional AI provider | A CareFlow journey graph and analytics on how patients move through the hospital |

## Appendix B: build notes (where the code changes)

- **Bookings and slots:** a new table in a tool `schema.sql` (slot, doctor, department or form, patient,
  phone, queue number per doctor per day). Changes to `intakes` are numbered migrations.
- **OTP:** hashed, 5-minute expiry, 3 tries, rate-limited per slot and per phone (`ratelimit.py`). Shown
  on screen only in demo mode.
- **Status page:** a finished link can read its own status (queue number, department, the patient's own
  answers, and the summary once reviewed) until the end of the day. It can never answer questions again.
- **Languages:** `speech.Language` stays `en-IN` and `hi-IN`. Hinglish is recognised and answered within
  them. The negative words in `validate.py` already cover English and Hindi.
- **Interview context:** `agent.next_turn` also receives age, sex, past visits and simulated ABHA records,
  each labelled with its source. ABHA items are confirmed with the patient, never copied in as fact.
- **Doctor feedback:** stored with the review, scored in `diagnofast_eval.py`, and good examples are added
  to the interview prompt as few-shot examples.
- **Slow calls:** routes call `db.release(db)` before any Sarvam or Neo4j call, as they do before AI
  calls today.
- **Tests:** fakes for Sarvam and Neo4j, new routes added to the sweep in `test_security.py`, and Hinglish
  phrasings added to the dev split only, with the score reported.
