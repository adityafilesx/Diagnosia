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
- Write contention under load (WI-261).
- Alert latency for an urgent stop (no alert yet, WI-203).
