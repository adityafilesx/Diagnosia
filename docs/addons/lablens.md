# LabLens

**Status:** pilot. Documents are encrypted, and uploads fail closed without keys. LOINC codes are proposals. Measured on synthetic layouts only.

Reads lab reports into reviewed results and trends. It doesn't diagnose.
Code: `backend/lablens/`, `web/js/care/lablens.js`. Tests: `test_lablens.py`.

## Workflow

1. A patient or clinician uploads a PDF, JPG or PNG. File type is checked from its
   bytes, and the original is stored unchanged.
2. A background job reads PDF text on our server and parses it line by line.
3. If that finds nothing, and `ai_processing` consent exists, the vision model chosen in Settings reads page images, three at a time.
   Without consent, the report waits for manual entry.
4. Each value is checked. Anything doubtful is highlighted, and all AI readings are.
5. A person compares it with the original, then accepts, fixes or removes each result.
6. Confirming writes `observations` with provenance. The report is then fixed.

States: `processing`, `needs_review`, `needs_manual_entry`, `confirmed`, `failed`.
Failures are stored and can be retried. A restart marks interrupted jobs as failed.

## Checks

Implausible value, missing or unexpected unit, unclear decimal or thousands separator,
missing range, printed flag that disagrees with the range, unrecognised test, and a
name that differs from the patient, which must be acknowledged.

## Data

`clinical_documents`, `lab_reports`, `lab_results`, `observations`. The catalogue in
`analytes.json` holds about 50 tests with LOINC codes, units and limits.

## API

Under `/api/addons/lablens`: `POST reports`, `GET patients/{id}/reports`,
`GET reports/{id}/extraction`, `POST reports/{id}/retry`, `PATCH results/{id}`,
`POST reports/{id}/results`, `POST reports/{id}/confirm`, `GET patients/{id}/trends`,
`GET reports/{id}/fhir`.

## Safety

- The lab's own name, unit and range are always kept, and corrections keep the original.
- Values are described only as below, within or above the lab's printed range.
- Trends never join different units.

## Limits

Tested on synthetic PDFs, not real reports from Indian labs. The local parser reads numeric
results, and results written in words (positive, negative, reactive, non reactive, trace, nil,
present, absent, detected, not detected, 1+ to 4+). A word result gets no number, unit or range
status and always goes to a person. Lines holding two tests are split and always flagged for review.

The review screen says "N lines not read" and lists them: a test the parser knows with no value it
could read, or a line holding a number between the results. It is a prompt to look at the original,
not a measure of everything missed: a line outside the table that names no known test isn't counted.
For a report read by AI, the count is the AI's own count of lines it left out, with no text. There is no virus scanning of uploads.
