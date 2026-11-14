# Baselines

Numbers recorded before the audit-plan fixes (`docs/AUDIT_AND_REFINEMENT_PLAN.md`, WI-002), so every later
change can be compared with them. Add a dated row whenever a number is re-measured. All data is made up.

## 13 November 2026, before Phase 1

Measured on commit `b8acd2e` (plus the dependency upgrade in WI-001), Python 3.11, Linux.

### Test suite

`pytest backend/tests --ignore=backend/tests/browser`: **1379 passed, 1 skipped** (the skip is a Windows-only
file-permission test). The same count before and after the FastAPI 0.135 / Starlette 1.10 / pytest 9 upgrade.

### Dependency audit

`pip-audit -r backend/requirements.lock`: before the upgrade, Starlette 0.46.2 had 14 advisories and pytest
8.4.2 had 2. After it, **no known vulnerabilities**.

### Urgent-symptom rules (`python -m backend.synthetic.diagnofast_eval`)

| Check | Dev split | Frozen test split |
|---|---|---|
| Single answers with an urgent symptom, exact flags | 140/180 (77.8%) | 36/42 (85.7%) |
| Negation then symptom, exact flags | 52/65 (80.0%) | 7/11 (63.6%) |
| Negated mention, no flag | 85/93 (91.4%) | 14/15 (93.3%) |
| History mention, no flag | 17/17 | 6/6 |
| Ordinary complaint, no flag | 39/39 | 6/6 |
| Urgent interviews stopped at the right turn | 205/244 (84.0%) | 59/68 (86.8%) |
| Calm interviews wrongly stopped | 5 of 713 | 2 of 175 |

Recall by category on dev: fainting 100%, self-harm 100%, trouble breathing 93.8%, chest pain 81.1%, heavy
bleeding 80.8%, severe allergy 77.8%, stroke signs 69.0%, seizure 64.3%, poisoning 53.8%. By script on dev:
English 90.6%, Devanagari 85.8%, romanised Hindi 74.6%.

### Lab report reading (`python -m backend.tests.lab_validation.score`)

Synthetic text-PDF layouts only (the scanned layouts are not scored yet, see WI-231):

| Field | Right |
|---|---|
| Test found | 37/37 |
| Value | 37/37 |
| Unit | 35/36 |
| Reference low | 30/30 |
| Reference high | 34/34 |
| Patient name in header | 9/9 |
| Collection date in header | 9/9 |

No wrong values and no silent misses.

### Prescription and lab photo reading with real models

Not re-measured (needs keys). The last recorded comparison is in `backend/tests/ai_eval/README.md`
(31 October 2026: five synthetic prescriptions, three lab photos).

### Not yet measured

- AI cost per tool and per completed intake (no token accounting yet, WI-105).
- Alert latency for an urgent stop (no alert yet, WI-203).

## 13 November 2026, after the urgent-symptom rule changes (WI-201, rules part)

`python -m backend.synthetic.diagnofast_eval`, same frozen v1 files. The rules were tuned on the dev split only;
the test split was run once, after the change.

| Check | Dev before | Dev after | Test before | Test after |
|---|---|---|---|---|
| Single answers with an urgent symptom, exact flags | 140/180 (77.8%) | 180/180 | 36/42 (85.7%) | 42/42 |
| Negation then symptom, exact flags | 52/65 (80.0%) | 65/65 | 7/11 (63.6%) | 11/11 |
| Negated mention, no flag | 85/93 (91.4%) | 93/93 | 14/15 (93.3%) | 15/15 |
| History mention, no flag | 17/17 | 17/17 | 6/6 | 6/6 |
| Ordinary complaint, no flag | 39/39 | 39/39 | 6/6 | 6/6 |
| Urgent interviews stopped at the right turn | 205/244 (84.0%) | 244/244 | 59/68 (86.8%) | 68/68 |
| Calm interviews wrongly stopped | 5 of 713 | 0 of 713 | 2 of 175 | 0 of 175 |

Recall by category, dev before to after: chest pain 81.1% to 100%, trouble breathing 93.8% to 100%, heavy
bleeding 80.8% to 100%, severe allergy 77.8% to 100%, stroke signs 69.0% to 100%, seizure 64.3% to 100%,
poisoning 53.8% to 100%; fainting and self-harm stayed at 100%. On the test split before: stroke signs 7/11,
seizure 2/5, severe allergy 5/7, the rest complete. After: every category complete.

**Read this with care.** v1's test split is built from the same pool of phrasings as its dev split, so 100% means
"every phrasing v1 knows is now handled", not "every way a patient might say it". Real recall on unseen wording
is unknown until the v2 set exists, written with a native Hindi speaker and a clinician (WI-201, still open).
The ten "needs a clinician" answers are unchanged: the rules flag the same four as before.

## 13 November 2026, urgent-stop alert latency (WI-203)

Time from the patient page receiving the urgent stop to the alert banner showing on a signed-in doctor's
screen that was open on another tool. Chromium, same machine as the server, three runs at 390, 820 and 1280 px:
**2.3 s, 2.8 s, 2.3 s.** Staff screens ask for alerts every 5 seconds, so the expected worst case is about 5 s
plus the network. Not yet measured on a real kiosk tablet and clinic network.

No longer open from the first table: token accounting exists (WI-105), and this alert latency.

## 13 November 2026, SQLite write contention (WI-261)

`python -m backend.synthetic.load_test`: a throwaway database, 20 staff each saving every second (new patients
and tasks), 5 ClinScribe drafts in flight through a fake AI that takes 3 seconds, 30 seconds, one process,
4 CPUs. Busy wait 5 s (`CURAI_DB_BUSY_SECONDS`).

| | Writes | Refused as busy | p50 | p95 | Max | Notes drafted |
|---|---|---|---|---|---|---|
| Before (the lock held through each AI call) | 123 | 73 (59%) | 5015 ms | 5033 ms | 5170 ms | 9 |
| After (transaction ended before the AI call) | 547 | 0 | 12 ms | 125 ms | 465 ms | 45 |
| After, stress: every writer saving non-stop | 2936 | 0 | 35 ms | 965 ms | 5067 ms | 36 |

**Threshold for moving to PostgreSQL:** at the pilot load above, a p95 write above 250 ms or any write refused as
busy. The pilot load now passes (125 ms, none refused), so SQLite stays for a single-host demo. The stress row
fails the threshold and shows where the limit is: one writer at a time, with Python's own lock between threads.
Re-run before adding a second worker process or a second clinic, and on the real host.

