# ClinScribe

**Status:** pilot. Audio capture tested in Chrome with a fake device. Live Groq untested, and no vendor agreement exists. Last audio chunk now kept on pause or stop.

Turns a consultation into a draft note that a clinician checks and signs.
Code: `backend/clinscribe/`, `web/js/care/clinscribe.js`. Tests: `test_clinscribe.py`.

## Workflow

1. A clinician opens a session on an in-progress visit. `ai_scribe` consent is required.
2. The session starts paused. Recording begins only on a click, with a visible state.
3. The browser sends 25-second audio chunks to Groq's Whisper, or lines can be typed if audio fails.
   A typed line needs the same consent as recording. A chunk the speech service could not turn into
   text is counted on the session (`chunks_lost`) and shown as an "N chunks lost" badge on the session,
   in the session list and on the draft.
4. After "Stop and finish" the record controls are replaced by "Draft the note" and "Add a missed
   line". A line posted to a stopped session is refused (409) unless it is marked as a missed line
   (`missed_line: true`), and nothing is added once the note is signed.
5. After stopping, the model chosen in Settings drafts statements in a SOAP or history-and-physical template.
6. The verifier checks each statement against the transcript and flags problems.
7. The clinician edits and signs. Open flags must be acknowledged. A signed note is final.
8. The transcript is deleted on signing unless `transcript_retention` was agreed.

States: session `paused`, `recording`, `stopped`. Note `draft`, `approved`, `discarded`.

## Data

`scribe_sessions`, `transcript_segments`, `clinical_notes`, and
`clinical_note_versions`, which keeps every version, AI and clinician. Each note
records the model, prompt version and verifier version.

## API

Under `/api/addons/clinscribe`: `POST encounters/{id}/sessions`,
`POST sessions/{id}/state`, `POST sessions/{id}/transcribe`, `POST sessions/{id}/segments`,
`PATCH segments/{id}`, `POST sessions/{id}/draft-note`, `GET`/`PATCH notes/{id}`,
`POST notes/{id}/approve`, `POST notes/{id}/discard`, `GET notes/{id}/fhir`,
`DELETE sessions/{id}/transcript`.

## Safety

- Only the clinician who held the consultation can sign. Patients never see a draft.
- The verifier (version 2.0) flags missing numbers, changed units, lost negation, swapped side,
  and unsupported text. AI summaries always need confirming.
- Numbers and units are checked against the lines a statement cites (and the line that matches it
  best), not the whole transcript. A number said only in another line is flagged with that line's
  number, so a dose that belongs to a different medicine no longer passes.
- Medicines: a name is the word before a dose ("metformin 850 mg") or after a form ("Tab ..."). The
  name must be in the cited lines (a misheard spelling counts as the same name), its dose must be said
  with it in one of those lines, and how often must match, using the prescription tool's frequency
  rules. A wrong medicine, a dose said with another medicine, or a different frequency is
  "does not match", never "please check".
- A line the clinician types or changes is checked again on save. It is flagged only where it
  conflicts with the transcript: a different dose or frequency for a medicine that was discussed.
  What the clinician adds from their own examination, or a medicine nobody mentioned, is not
  questioned. Signing stops to show a flag the clinician has not seen yet.
- Limits of these rules: they know a medicine only by its place beside a dose or a form, they compare
  doses by number and unit, and they have been tested on made-up lines only.
- Hindi transcripts can't be word-matched. Those statements are marked `not_checked` ("Not checked:
  compare with the source line"), never supported, and a note with any of them has the status
  `not_checked`, not `verified`. Numbers are still checked, counting ones spoken as words in English
  or Hindi.
- The review screen shows the cited transcript line beside each statement, in its own language. The
  lines are read from the transcript when the note is opened and are never saved into the note.
- Each flagged statement has an id and needs its own acknowledgement: `POST notes/{id}/approve` takes
  `acknowledged` (a list of statement ids) and refuses with `flags_open` and the ids still missing. One
  tick for the whole note is no longer accepted. The signed version records which flags were acknowledged.
- When the transcript is deleted (at signing without retention consent, or by hand), the line numbers
  that pointed into it are dropped from the note, which is then marked `sources_deleted`.
- A session has one unsigned draft at a time (migration 17 adds the index). Drafting again returns
  409 `draft_exists` with the draft's id; discard it to draft again.

## Limits

Speakers are labelled by hand, there are no per-segment timestamps or confidence
scores, and there is no PDF export. Long silences still send chunks. The verifier was
tested on synthetic sentences only.
