# Platform setup

How to get Curai working end to end on one machine, and what can be configured.

## First run

```bash
uv pip install -r backend/requirements.txt
.venv/bin/python -m backend.operator_cli setup-local
.venv/bin/uvicorn backend.app:app --host 127.0.0.1 --port 8001 --reload
```

`setup-local` runs in development only, and only once. It:

- creates the document encryption key at `~/.curai/document-keys.json`, outside the project
- adds the settings it needs to `.env`
- creates a verified demo clinic, a demo specialist centre, and demo accounts
- runs a synthetic patient journey through the record-based tools and leaves a DiagnoFast link waiting, using the real API
- saves the logins to `~/.curai/local-accounts.txt`

**Back up the key file.** Losing it makes stored documents unreadable.

It approves no clinical content and records no governance signoff. LOINC mappings
stay unreviewed, so you can try the review workflow with the demo laboratory account.

## Turning on AI

Create a free key at [console.groq.com](https://console.groq.com). Sign in as the demo doctor,
open **Settings**, and paste it under AI key. The key is stored encrypted and never shown again.
You can use `GROQ_API_KEY` in `.env` instead, which takes priority.

### A second provider

Add a free Gemini key from [aistudio.google.com/apikey](https://aistudio.google.com/apikey) in the same
place, or as `GEMINI_API_KEY`. With both keys:

| Setting | Meaning |
|---|---|
| Provider tried first | Groq or Gemini. Default Groq |
| When both providers have a key | **fallback**: the other one answers only when the first fails. **round_robin**: they take turns, and a failure still falls back to the other |
| Gemini model | One model for every tool. Default `gemini-3.5-flash-lite` |

Five tools prefer Gemini whichever general setting is chosen (`READING_TOOLS` in
`backend/settings_store.py`): reading prescription photos, explaining a prescription, planning a
prescription's daily times, reading scanned lab reports, and understanding a patient's confirmed
answer in a DiagnoFast interview. The photo-reading ones were chosen because Gemini read photos
better in our comparison (`backend/tests/ai_eval/README.md`). Each has its own provider and Gemini
model setting. The reading ones default to `gemini-3.5-flash`, which is often busy or over its free
limit, so they back up to `gemini-3.5-flash-lite` and then to Groq. Round robin never moves these
five.

**Patient interview answers go to Gemini first by default**, and to Groq only when Gemini fails.
Change "DiagnoFast: understanding confirmed answers" in Settings to send them to Groq first.

Gemini carries text and images. Speech to text and the English voice stay on Groq. In demo mode,
DiagnoFast questions use Microsoft Edge voices (question text only, never answers); outside demo mode
that service is never called. The browser's own voice covers the rest, so Gemini alone can't transcribe a consultation. A failed call is logged
by provider name only, never with its content. **Both providers receive patient content**, so each
needs its own agreement before real use.

Without a key, everything except drafting, speech and reading scans still works, and each screen
says what is missing.

## What the demo accounts do

| Account | Try this |
|---|---|
| Doctor and clinic administrator | Every tool, Settings, staff verification |
| Specialist | Received referrals: accept, book, return an outcome |
| Laboratory reviewer | Approve or correct LOINC mappings |
| Patient | Their own record, readings, checklist, on a phone-sized screen too |

## What Settings controls

| Area | What you can change |
|---|---|
| AI key | Add, replace or remove |
| AI models | The model for each job. Any model name the provider supports is accepted |
| Tools | Switch any tool on or off, including DiagnoFast and Prescription Analyzer. Off applies to the API too, not only the screen |
| ClinScribe | Default language, your clinic's own note headings |
| LabLens | Whether AI reads reports we can't read locally |
| ReferralLoop | Suggested reply times |
| Reminders | Hours a patient has to confirm |
| Sarvam AI | On or off, the speech-to-text and voice models, the Hindi and English voices, the translation model. Needs a key and the `sarvam_terms` sign-off |
| Neo4j | On or off. Needs `NEO4J_URI` and a password |
| DiagnoFast add-ons | Graph follow-ups, the doctor-like interview, OPD bookings (with the status page and demo outbox), slot QR login, walk-in suggestions, review feedback. Each starts off |

Only an administrator of a verified organization can change these, and each change is audited.
Safety switches, such as allowing real patient data, are deliberately not settings.

## Models

Chosen from Groq's documentation, checked 31 October 2026. Availability changes, so check
[Groq's model list](https://console.groq.com/docs/models).

| Job | Default | Why |
|---|---|---|
| Clinical notes | `openai/gpt-oss-120b` | Production model with guaranteed schema output |
| Prescription explanations | `openai/gpt-oss-20b` | Faster, same guarantee |
| Prescription and lab images | `qwen/qwen3.8-27b` | The vision model open to all accounts. **Groq lists it as preview** |
| Speech to text | `whisper-large-v3` | Groq's choice for error-sensitive multilingual use |
| Reading aloud, English | `canopylabs/orpheus-v1-english` | Preview. May need its terms accepted in Groq's console |
| Reading aloud, Hindi | Browser voice | Groq has no Hindi voice |

Groq's documents don't name Hindi for Whisper, so test Hindi transcription with your own key.

## Free plan limits

Groq's page didn't make clear whether the figures it showed were the free plan's, so check
[your limits](https://console.groq.com/settings/limits). They appeared to be about 30 requests a
minute and 1,000 a day for the chat models, with 8,000 tokens a minute. A long consultation could
exceed that, and the app then reports the limit rather than failing silently. Speech appeared to be
20 requests a minute. These limits suit a demo and a small pilot, not a busy clinic.

## Other free providers

Any OpenAI-compatible service can replace Groq by setting `AI_BASE_URL`, such as a local model
server. Choose models in Settings. This route hasn't been tested with a real alternative.

## The hackathon add-ons (Sarvam AI, Neo4j, bookings)

Everything below is for made-up patients only, starts switched off, and stops completely when
`ALLOW_REAL_PATIENT_DATA` is on. With each one off, the app behaves exactly as before. The plan is in
`BUILD.md`; the sources are in `integrations/SARVAM.md` and `integrations/NEO4J.md`.

**Sarvam AI** (Hindi and English speech to text, voice and translation):

1. In the Sarvam dashboard, set the workspace's data retention to "No retention (0 days)" and opt out of
   model training. Sarvam's own terms train on API data unless you opt out.
2. Record that you did it: `python -m backend.operator_cli signoff --item sarvam_terms --signed-by "<name>" --role "Account owner" --document-reference "<where it's written down>" --operator "<you>"`.
3. Put `SARVAM_API_KEY` in `.env`, or save it in Settings, AI keys.
4. Turn on Settings, Sarvam AI. Speech to text then tries Saaras v4 first (its mixed-language mode),
   questions are read by Bulbul, and confirmed Hindi answers get an English machine translation for
   the doctor. Any Sarvam failure falls back to Groq, Edge and the browser.

**Neo4j** (the question graph, history and evidence graphs, walk-in suggestions):

1. `pip install -r backend/requirements-integrations.txt` (the `neo4j` driver).
2. Set `NEO4J_PASSWORD` (8 characters or more) and `NEO4J_URI=neo4j://127.0.0.1:7687` in `.env`.
3. `docker compose -f docker-compose.integrations.yml up neo4j`. It listens on this machine only.
4. Turn on Settings, Neo4j, then the DiagnoFast add-ons you want. The question graph loads itself from
   `backend/diagnofast/graph/questions_v1.json` (not clinically reviewed). Finished visits are copied by
   the app's sweep; `python -m backend.operator_cli graph-rebuild` empties the copy and sends them again.

**OPD bookings and the slot QR login**: turn on DiagnoFast add-ons, OPD bookings (and slot QR login),
then open DiagnoFast, "OPD bookings and queue". Nothing is sent to a phone: the demo outbox shows the
message. One-time codes are shown on the screen, and only in demo mode.

**A phone's microphone needs HTTPS.** Browsers only allow the microphone on HTTPS or `localhost`, and a
LAN address such as `http://192.168.1.20:8000` doesn't count. Two ways:

- A tunnel, for example `cloudflared tunnel --url http://localhost:8000`. Easiest, but every request,
  made-up data included, passes through Cloudflare, and the address changes each run. Run uvicorn with
  `--proxy-headers` so rate limits see real visitors.
- A local certificate with `mkcert` for your LAN address. Nothing goes to a third party, but each phone
  must install and trust mkcert's `rootCA.pem` by hand. Never share `rootCA-key.pem`.

Typing always works without a microphone.

## Moving beyond a local demo

`setup-local` is for synthetic data on your own machine. For anything else, follow
`PRODUCTION_DEPLOYMENT_CHECKLIST.md`.
