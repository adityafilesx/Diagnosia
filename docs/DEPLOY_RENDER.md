# Deploying the judge demo on Render (free)

For the IIITD hackathon judges. Judges open the public link, click any of the six tools on the home
page, and land in that tool already signed in. **Made-up patients only.** Judge mode signs in anyone
who opens the link, so it must never run with real data, and the app refuses to start if asked to.

The files: `render.yaml` (the Blueprint), `scripts/render_start.sh` (the start command),
`backend/deploy_boot.py` (what runs in the build and on every boot) and `backend/judge.py` (the demo door).

## How it behaves on the free tier

| Free-tier fact | What the deployment does about it |
|---|---|
| The disk is wiped on every restart, redeploy and spin-down | The made-up hospital is seeded **in the build**, so every boot starts from it. Anything judges add is gone after a restart, which is fine for a demo |
| 0.1 CPU | Seeding 30 patients took about 4 minutes at 0.1 CPU (in the build, once). A boot from the seeded build took 78 seconds, measured locally at 0.1 CPU and 512 MB |
| Sleeps after 15 minutes idle, about a minute to wake | Keep it awake during judging with a ping (below). A wake costs Render's minute plus the 78-second boot |
| 512 MB RAM | The app used about 70 MB without the medicine list (measured) |
| Secret Files: 1 MB in total | Enough for the key ring. **Not** for the medicine list (31.8 MB; even names only, gzipped, is 1.5 MB). See "Medicine list" |
| 750 free hours a month | One service awake all month is about 744 hours. Turn the ping off after judging |

## Accounts a judge is signed in as

| Tool | Account | Why |
|---|---|---|
| DiagnoFast, ClinScribe, LabLens, ReferralLoop, DischargeCare | `doctor07@example.com`, a verified General Medicine doctor | Staff tools need a verified doctor. This one is **not** an organization administrator, so judges can't change Settings, keys or staff verification |
| Prescription Analyzer | `patient007@example.com` | It is the patient's own tool |

They are the same person on both sides: doctor07 is the clinician on patient007's chart, and the
workspace opens that chart first, so every staff tool works straight away. Kiosk visits
(`intake.html` with no link) go to doctor07 too, so they appear in the queue a judge is looking at.
Every judge shares these two accounts and sees the others' made-up entries. AI limits are counted
per account and address in judge mode, so one busy judge doesn't use up the others' allowance.

## Before you start (once, on your computer)

1. **Key ring.** Make one, outside the repository:

   ```bash
   python -m backend.operator_cli generate-key --path ~/diagnosia-render-keys/document-keys.json
   ```

   Keep a copy. You upload its contents in step 3. Never commit it.
2. **Sarvam.** Confirm your Sarvam workspace is set to zero data retention and opted out of model
   training. Only then set `DIAGNOSIA_SARVAM_SIGNED_OFF_BY` (step 3): its value is recorded as your
   sign-off. Without it, Sarvam stays off and Hindi uses the Edge voices.

## In the Render dashboard

1. **New → Blueprint**, pick the repository and the branch with this work. Render reads `render.yaml`
   and creates one free web service called `diagnosia`.
2. When it asks for the values marked `sync: false`, fill in:

   | Environment variable | What |
   |---|---|
   | `GROQ_API_KEY` | Your Groq key |
   | `GEMINI_API_KEY` | Your Gemini key |
   | `SARVAM_API_KEY` | Your Sarvam key |
   | `DIAGNOSIA_SARVAM_SIGNED_OFF_BY` | Your name, only after step 2 above |

   `render.yaml` already sets the rest: `PYTHON_VERSION`, `DIAGNOSIA_ENV`, `DIAGNOSIA_HTTPS`,
   `DIAGNOSIA_DEMO_MODE`, `DIAGNOSIA_DEMO_OUTSIDE_DEVELOPMENT`, `DIAGNOSIA_JUDGE_MODE`,
   `DIAGNOSIA_DEMO_PATIENTS`, `DIAGNOSIA_AI_DAILY_TOKENS` and `DIAGNOSIA_DOCUMENT_KEY_SOURCE`.
3. **Environment → Secret Files → Add Secret File.** Filename `document-keys.json`; contents: paste the
   key ring file. Save (this redeploys).
4. Wait for the deploy. In the logs, the build ends with `Demo settings restored.`, and the boot says
   `The synthetic hospital already exists` (proof the build's data reached the running service).
5. Check `https://<your-service>.onrender.com/readyz` says `"ready":true`. The only warning should be
   `medicine_list_missing`.
6. Open the home page, click a tool, and check it opens signed in with the yellow line
   "Demo: made-up patients only".

`DIAGNOSIA_AI_DAILY_TOKENS` is 15,000,000: about 40 judges each running every tool, with retries. Groq's
and Gemini's own free limits usually run out first; the app then falls back between them.

## Keep it awake during judging

Pick one (both free). Ping `https://<your-service>.onrender.com/healthz` every 10 minutes.

- **UptimeRobot:** Add New Monitor → type HTTP(s) → the URL above → interval 10 minutes (5 is the free
  minimum, 10 is enough) → Create.
- **cron-job.org:** Create cronjob → the URL above → every 10 minutes → Save.

Start it an hour before judging. The first ping may wait about two minutes while the service wakes.

## After judging: turn judge mode off

1. Pause or delete the monitor, so the free hours aren't used up.
2. In Render, **Environment**: set `DIAGNOSIA_JUDGE_MODE` to `0` and save. The service rebuilds and
   redeploys with an empty database: no demo accounts, the demo door answers "Not Found", and the home
   page links go back to the sign-in page. (The off deploy is built to succeed on purpose: a failed
   deploy on Render leaves the previous one, with judge mode on, running.) Check that
   `/api/demo/status` says `{"judge_mode":false}`, then **Suspend** the service, or delete it.
3. The seeded accounts share a published password (`backend/synthetic/seed_accounts.py`). That is fine
   for made-up data that disappears on restart, and another reason to suspend the service afterwards.

## Medicine list

The checker's list (`datasets/`, never committed) is 31.8 MB and Render allows 1 MB of Secret Files in
total, so it can't go up that way. Without it the Prescription Analyzer still reads, confirms and
explains, and every medicine card says "We could not check this name against a list". Options:

1. **Leave it off** for the judges (what this deployment does).
2. **Download it at boot** from a private link (for example a private release asset), with a token in
   an environment variable. Measure memory first: the full list may not fit beside the app in 512 MB.
3. A paid instance with a persistent disk.

The dataset's upstream permission is unconfirmed (see `agent_context.md`, Licences), so don't put it
anywhere public.

## What doesn't work on the free tier

- Data judges add is lost on every restart and wake. Render may restart a free service at any time.
- No email or SMS: the OPD outbox stays a demo outbox that sends nothing.
- Neo4j, MongoDB, YugabyteDB and Meko are off (none is set). The views fall back to SQLite.
- The first request after a sleep takes about two minutes.
