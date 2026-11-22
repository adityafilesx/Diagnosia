# Testing the integrations

Results must say what they ran against. A mock, a local stand-in and a real service prove different things.

| Level | Command | Against | Proves |
|---|---|---|---|
| Unit and mock | `.venv/bin/python -m pytest` | Fakes only | Logic. Never a connection |
| Local stand-ins | `LOCAL_MONGODB_URI=... LOCAL_POSTGRES_DSN=... .venv/bin/python -m pytest -m local_stack backend/tests/local_stack` | A local MongoDB and PostgreSQL | The real drivers and queries work. **Never a live result** |
| Live | `DIAGNOSIA_LIVE_INTEGRATIONS=1 .venv/bin/python -m pytest -m live backend/tests/live/test_live_integrations.py` | Real Atlas, YugabyteDB, Meko | The real service works |
| End to end | `python -m backend.tests.local_stack.end_to_end` | Whatever is configured | The journey, outages and recovery |
| Browser | `node backend/tests/browser/run_careflow.mjs <puppeteer-core> <port>` | A running server | The screen |

## Live tests can't be fooled

Each one checks what it's connected to first. The Atlas tests fail on any server outside `mongodb.net`, and the YugabyteDB tests fail unless the server identifies itself as YugabyteDB.

- No credentials: the test skips, with `BLOCKED_MISSING_CREDENTIALS` and the variable's name.
- Service switched on but credentials missing: the test fails, because they were expected.

## End-to-end run

```bash
DIAGNOSIA_DB=/tmp/e2e/e2e.db DIAGNOSIA_DOCUMENTS=/tmp/e2e/docs .venv/bin/python -m backend.tests.local_stack.end_to_end \
    --real-ai --mongo-container NAME --yugabyte-container NAME
```

It refuses a database without `e2e` in its path. With container names it stops those servers for real. Without them, the outage is simulated, which is the only safe way to do it against a cloud service.

## Browser

Run the demo, start a server, and pass `--expect-stream` when change streams are on, and `--mongo-container NAME` to test an outage. It checks signing in, events, filters, handoffs, labels, status, live updates, fallback and error states.

## Microphone

Speech is faked by the server. The run covers permission refusal, missing and busy devices, empty
recordings, network and transcription failures, long recordings and revoked consent, in Chrome with
a fake audio device. It is not a test of a real microphone.

```bash
DIAGNOSIA_DB=/tmp/test-run/mic.db DIAGNOSIA_DOCUMENTS=/tmp/test-run/docs \
DIAGNOSIA_DOCUMENT_KEY_FILE=/path/outside/keys.json python -m backend.tests.browser.serve 8124
node backend/tests/browser/run_microphone.mjs <puppeteer node_modules> 8124 /tmp/test-run/mic.db .venv/bin/python
```

## Lab report layouts

`backend/tests/lab_validation/` generates synthetic Indian lab report layouts, and
`backend/tests/test_lab_validation.py` checks them in the normal run. To score LabLens on them:

```bash
python -m backend.tests.lab_validation.score
```

### Scanned reports (the AI reading path)

A text PDF is read on our own server. A scan or a photo goes to the AI, and that path has its own
scored set: 8 synthetic layouts, each as a clean scan and four spoiled ones (blurred, tilted, shaded
and grainy, small and compressed), 40 scans and 150 results, with the right answers in `truth.json`.
The set comes out identical every time it is made.

```bash
python -m backend.tests.lab_validation.scan_set /tmp/lab-scans
python -m backend.tests.lab_validation.scan_score /tmp/lab-scans --out /tmp/lab-scans/score.json
```

The second command needs a real `GROQ_API_KEY` or `GEMINI_API_KEY` in `.env`. It sends the 40
synthetic scans to the model set for "LabLens: reading scanned reports", in 40 requests, and prints
the error rate for each field (test found, value, unit, range low and high, the printed high or low
mark), by condition, with every wrong value listed. A value that is right for a different row of
the same report is listed separately as a wrong row, the dangerous kind. Without a key, or if the
provider's limit is reached part-way, it stops and prints no score, so a setup problem can't be
recorded as a reading error. Paste the table it prints into `docs/BASELINES.md` with the date, the
model names it reports and the commit.

`backend/tests/test_lab_scan_scoring.py` checks the set and the scoring in the normal run with a
stand-in reader. That proves the counting is right. It says nothing about any model.

## AI providers

Marked `live`, excluded from the normal run, synthetic data only. They skip themselves without real
keys in `GROQ_API_KEY` and `GEMINI_API_KEY`, and are the only proof that the chosen models accept
our requests. Re-run them after changing a model.

```bash
DIAGNOSIA_LIVE_TESTS=1 .venv/bin/python -m pytest -m live backend/tests/live
```
