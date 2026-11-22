# Diagnosia

> **An AI-powered healthcare platform that brings patient records, medical history and clinical tools together in one place.**

Diagnosia helps doctors make better-informed decisions and manage their
workflows more efficiently. The goal is to make healthcare more connected,
organised and intelligent.

It has six tools, all working on **one shared patient record**, in the order of
a visit:

| When | Tool | Who uses it | What it does in one line |
|---|---|---|---|
| Before the visit | **DiagnoFast** | Doctors; patients answer | Takes the patient's history by voice in the waiting room and hands the doctor a one-page report. |
| During the visit | **ClinScribe** | Clinicians | Turns a consultation into a draft note that the clinician checks and signs. |
| During the visit | **LabLens** | Patients and clinicians | Reads a lab report into results a person confirms, and shows trends over time. |
| After the visit | **Prescription Analyzer** | Patients | Reads a prescription photo and explains the confirmed medicines in plain Hindi or English. |
| After the visit | **ReferralLoop** | Doctors and specialists | Follows a referral from request until the outcome is back and reviewed. |
| After the visit | **DischargeCare** | Hospital teams and families | Turns a discharge plan into a family checklist and tracked team tasks. |

---

## 1. The problem

### Doctors decide with half the picture

India has too few doctors for the number of people who need them. A
consultation can last two minutes, and much of that goes on the same basic
questions: *what is the problem, since when, any fever, which medicines?* The
doctor then decides with whatever the patient remembers in that moment.

### Records are scattered

A patient's history lives in many places: a paper prescription from last
month, a lab report on a phone, a discharge summary in a hospital file, a
referral letter that never came back. Nobody sees all of it at once, so tests
are repeated and important details are missed.

### Paperwork takes the doctor's time

Writing notes, copying lab values and chasing referrals take time away from
patients. The more patients a doctor sees, the less time there is for each one.

### Care breaks between visits

After the consultation, patients struggle with prescriptions written in
handwriting and shorthand (*1-0-1*, *BD*, *SOS*). Referrals go unanswered.
Families leave hospital without a clear plan. Follow-up depends on someone
remembering.

---

## 2. One shared patient record

Every tool reads from and writes to the same patient record. Access is decided
once, by the care team and the patient's consent, and every opening of a record
is written to an audit log.

```
   BEFORE THE VISIT          DURING THE VISIT              AFTER THE VISIT
┌──────────────────┐   ┌────────────────────────┐   ┌──────────────────────────┐
│   DiagnoFast     │   │  ClinScribe            │   │  Prescription Analyzer   │
│  voice history,  │──▶│  draft note to sign    │──▶│  ReferralLoop            │
│  one-page report │   │  LabLens               │   │  DischargeCare           │
│                  │   │  confirmed lab results │   │                          │
└────────┬─────────┘   └───────────┬────────────┘   └────────────┬─────────────┘
         │                         │                             │
         └─────────────────────────┼─────────────────────────────┘
                                   ▼
                  ┌────────────────────────────────────┐
                  │     One shared patient record      │
                  │  history · notes · results ·       │
                  │  medicines · referrals · tasks     │
                  │  consent and access log            │
                  └────────────────────────────────────┘
```

AI only ever prepares a **draft**. Nothing becomes part of the record until a
person reviews and approves it. CareFlow, a timeline on each record, shows where
the patient is in their care and what is waiting for someone.

---

## 3. DiagnoFast: before the visit

### The history is ready before the patient walks in

DiagnoFast interviews the patient by voice while they wait, in Hindi or Indian
English, and fills in the doctor's specialty form. When the patient enters the
cabin, the doctor already has a short, organised report.

1. **Reception creates a link for one interview**, which expires after a day, or the patient picks a specialty at
   a self-service kiosk. No patient account is needed.
2. **It asks out loud.** Each question is read in the patient's language: by
   neural voices in the demo, by Groq or the browser's voice otherwise.
3. **The patient answers out loud or types.** Live speech recognition shows the
   words as they speak. The patient checks and edits the text before sending.
4. **The AI fills in the form.** It picks out the complaint, duration,
   severity, medicines and allergies, and asks a follow-up when something is
   unclear. It never diagnoses.
5. **Past records are added**, with consent, from ABHA (simulated for now).
6. **The doctor receives a one-page report**: chief complaint, history of the
   present illness, the specialty form's answers, past history with its source
   labelled, a review of systems, and investigations to consider. The original
   answers and recordings stay one click away.

Six specialty forms are included: general medicine, dermatology, cardiology,
orthopaedics, ENT and paediatrics.

### Urgent symptoms reach a person at once, by two checks

A patient who mentions chest pain, trouble breathing, signs of a stroke, heavy
bleeding, fainting, a seizure, a severe allergic reaction, poisoning or thoughts
of self-harm must reach a person straight away. DiagnoFast checks every answer
twice:

1. **Plain rules first.** Before any AI is called, rules written in code look
   for these symptoms in English, Hindi and romanised Hindi. They skip clearly
   negated mentions ("no chest pain", "सीने में दर्द नहीं है"). A match ends the
   interview and tells the patient to go to reception. This works even when the
   AI service is down.
2. **The AI second.** When the rules find nothing, the AI still lists anything
   that may need attention, including what rules can't judge, such as whether
   "stroke" means today or a parent's history.

Urgent patients go to the top of the doctor's queue.

---

## 4. ClinScribe and LabLens: during the visit

### ClinScribe: the note writes itself, the doctor signs it

ClinScribe records the consultation, with consent, and drafts a structured note
in SOAP or history-and-physical form. A verifier checks each statement against
the transcript and flags anything it can't support. The clinician edits and
signs; a signed note is final, and every version is kept. The transcript is
deleted on signing unless the patient agreed to keep it.

### LabLens: lab reports become results a person confirms

A patient or clinician uploads a lab report as a PDF or photo. LabLens reads
text PDFs on Diagnosia's own server and uses an AI vision model only for scans,
with consent. Each value is checked for an unclear unit, a missing range or a
flag that disagrees with the range. A person compares every result with the
original before it reaches the record. Confirmed results build trends over
time.

---

## 5. After the visit

### Prescription Analyzer

The patient photographs the prescription. The AI reads it and marks each field
as clear, unsure or unreadable, and is told never to guess. Plain rules, not
AI, decode shorthand such as `1-0-1`, `OD`, `BD`, `TDS`, `HS` and `SOS`. Each
name is checked against about 250,000 Indian medicine listings. The patient
confirms each medicine; anything unconfirmed or unreadable goes on a list for
the pharmacist and is never explained. The confirmed medicines are explained in
plain Hindi or English, with audio, a daily schedule, and diet and lifestyle
guidance. It never changes a dose or suggests a substitute.

### ReferralLoop

A referral is followed from request through acknowledgement, booking and
attendance until the specialist's outcome comes back and the referring doctor
reviews it. Nothing silently falls through: a stalled referral shows up as work
for someone.

### DischargeCare

A discharge plan becomes a checklist for the family and tracked tasks for the
team. Tasks open only when the responsible clinician approves. An episode can
close only when the required tasks are done and pending results are final, or a
written exception is recorded. Reminders that aren't confirmed become follow-up
calls for staff.

---

## 6. Trust, privacy and safety

- **Doctors stay in charge.** Every tool assists. None diagnoses, changes a
  dose, suggests a substitute medicine or tells a patient that something is or
  isn't serious.
- **Drafts until reviewed.** AI output is marked unreviewed and kept out of the
  approved record and exports until a person approves it.
- **Consent first.** Each purpose, such as AI drafting or sharing a referral,
  has its own consent, and revoking it takes effect straight away.
- **Security.** Passwords use Argon2, sessions are stored hashed, documents and
  recordings are encrypted, and every SQL query is parameterised. Public routes
  are rate-limited.
- **Not approved for real patient data.** Diagnosia is a pilot and uses made-up
  patients only. The AI vendors (Groq in the United States, Google Gemini) have
  no signed data agreement with Diagnosia yet, and privacy, security and
  regulatory reviews are still to come.

---

## 7. Who Diagnosia is for

| Customer | What they get |
|---|---|
| **Individual doctors and small clinics** | DiagnoFast with their specialty form, ClinScribe and LabLens: a full picture before and during each visit, and less paperwork |
| **Hospitals and healthcare organisations** | All six tools across departments, with ReferralLoop and DischargeCare to keep care joined up between teams and after discharge |
| **Patients and families** | DiagnoFast intake in their own language by voice, the Prescription Analyzer, their lab results, and a clear discharge checklist |

---

## 8. Current status

Diagnosia began as a school project in 2023 and is being rebuilt as a startup.

| Tool | Status |
|---|---|
| **DiagnoFast** | Built and tested live with synthetic patients. ABHA records are simulated. Real Hindi speech is lightly tested. |
| **ClinScribe** | Pilot. Audio capture tested in Chrome with a simulated microphone. |
| **LabLens** | Pilot. Measured on synthetic report layouts only; proposed LOINC codes are unreviewed. |
| **Prescription Analyzer** | Built and tested live on synthetic prescriptions. Reading of real handwriting is untested. |
| **ReferralLoop** | Pilot. Works within verified organisations. |
| **DischargeCare** | Pilot. Reminders are in-app or by staff call; SMS is not connected. |
| **Platform** | Not hosted yet. Not approved for real patient data. Clinical, privacy, security and regulatory reviews are outstanding. |

---

## 9. Technology

| Area | Technology |
|---|---|
| Web platform | Plain HTML, CSS and JavaScript front end; FastAPI and SQLite back end |
| Language models | Google Gemini and Groq, with automatic fallback, always through a fixed schema |
| Speech | Edge neural voices for questions, Groq Whisper for transcription, browser speech as a fallback |
| Urgent-symptom rules | Plain regular-expression rules in English, Hindi and romanised Hindi |
| Prescription reading | Vision models, plain rules for shorthand, and fuzzy matching against Indian medicine listings |
| Lab reports | Local PDF text parsing, with AI vision for scans only |
| Security | Argon2 passwords, hashed sessions, AES-256-GCM document encryption, rate limits counted in SQLite |
| Optional integrations | MongoDB Atlas (CareFlow timeline), YugabyteDB (AI run records), Meko (search index) |

---

<div align="center">

**Diagnosia: connected, organised and intelligent care.**

</div>
