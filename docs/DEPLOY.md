# Deploying Diagnosia

One container runs everything: the API, the pages in `web/`, and the background sweeps. Any host that
runs a Docker image and gives it HTTPS and a persistent disk works (Render, Railway, Fly.io, a VPS
behind Caddy or nginx). Netlify and other static hosts can't run it.

This is a deployment for **made-up patients only**. Before any real patient data, work through
`PRODUCTION_DEPLOYMENT_CHECKLIST.md`.

## What the host must give the container

| Need | Why |
|---|---|
| **HTTPS** at the public address | Browsers open the microphone only on `https` (or `localhost`). On plain `http`, DiagnoFast and ClinScribe have no voice input at all. Session cookies are also HTTPS-only (`DIAGNOSIA_HTTPS=1`, set in the image) |
| A **persistent disk at `/data`** | The SQLite database (`/data/diagnosia.db`) and stored documents. Without it every deploy starts empty |
| A **secret file** for the document key ring, outside `/data` | The app refuses to start in production without `DIAGNOSIA_DOCUMENT_KEY_FILE` |
| **One instance**, one worker | SQLite has one writer, and the sweeps run in the process. Don't scale out |
| The `PORT` variable, if the host sets one | The image listens on `$PORT`, or 8000 |

## Environment

| Variable | Value |
|---|---|
| `GROQ_API_KEY`, `GEMINI_API_KEY` | At least one. Store as host secrets, never in the repo |
| `SARVAM_API_KEY` | For Sarvam Hindi voice and speech to text |
| `DIAGNOSIA_ENV` | `production` (or `staging`) |
| `DIAGNOSIA_DOCUMENT_KEY_FILE` | Path of the mounted key ring, for example `/secrets/document-keys.json` |
| `DIAGNOSIA_DEMO_MODE` and `DIAGNOSIA_DEMO_OUTSIDE_DEVELOPMENT` | Both `1` for a demo with made-up patients. Demo mode opens the kiosk, shows one-time codes on screen and allows the Edge voices |
| `DIAGNOFAST_KIOSK_DOCTOR_ID` | A verified doctor's ID, so self-service kiosk visits go to them |
| `FORWARDED_ALLOW_IPS` | `*` in the image. Set it to the proxy's address when the host publishes one, so visitors can't fake their address to dodge rate limits |

Leave `ALLOW_REAL_PATIENT_DATA` and `ENABLE_EXTERNAL_MESSAGING` unset.

## Steps

1. **Build:** `docker build -t diagnosia .` (or point the host at the repository; it finds the `Dockerfile`).
2. **Key ring:** create it once, then store it as a secret file on the host:
   `python -m backend.operator_cli generate-key --path ./document-keys.json`. Keep two offline copies.
   Losing it makes stored documents unreadable.
3. **Start** the service with the disk at `/data`, the key ring mounted, and the variables above.
   `GET /healthz` should say `ok`, and `GET /readyz` should say `ready: true` (`medicine_list_missing`
   is only a warning: the medicine dataset is never in git, so names go unchecked until it is mounted and
   `DIAGNOSIA_MEDICINE_LIST` points at it).
4. **First administrator.** Sign up at `/login.html`, then in the host's shell:

   ```bash
   python -m backend.operator_cli bootstrap-organization --admin-email <you> --organization "<name>" \
       --type clinic --evidence-type "<what you checked>" --evidence-reference "<reference>" --operator "<your name>"
   ```

5. **Sarvam for Hindi.** First set the Sarvam workspace to zero retention and opt out of model training
   (its default is to train on API data). Then record that decision and switch it on:

   ```bash
   python -m backend.operator_cli signoff --item sarvam_terms --signed-by "<name>" --role "<role>" \
       --document-reference "<where the Sarvam setting is recorded>" --operator "<your name>"
   ```

   Then **Settings → Sarvam AI → on**. Hindi questions are then read by Bulbul (`aparna_hi_customer`,
   slightly slower and steadier than Bulbul's defaults) and answers are written by Saaras v4. The voices
   are settings; `docs/integrations/SARVAM.md` lists others to try. If Sarvam fails, the app falls back to
   the earlier voices and Groq Whisper.

## Checked on 22 November 2026

- The image built and started with `DIAGNOSIA_ENV=production`, a key ring and a `/data` volume. `/readyz`
  was ready, HSTS and the content-security policy were sent.
- Every one of the 179 API routes and every page was called signed out and as a doctor, a lab reviewer
  and a patient, through a simulated HTTPS proxy: no server errors.
- Over HTTPS, a DiagnoFast interview in Hindi in Chrome recorded from the microphone (a made-up Hindi
  answer played as the microphone) and Sarvam wrote it back word for word.
