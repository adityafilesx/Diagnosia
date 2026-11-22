"""WI-221: the cited source line beside each statement, one acknowledgement per flag, an honest
label for a transcript the rules can't check, no dangling pointers, and one draft per session."""
import pytest

from backend import llm
from backend.clinscribe import verifier
from backend.config import WEB_DIR
from backend.db import connect
from backend.tests.conftest import FakeAI, grant
from backend.tests.test_clinscribe import draft, encounter, fake_draft, session, statement  # noqa: F401 (fixtures)

BASE = "/api/addons/clinscribe"
HINDI_LINES = ["तीन दिन से बुखार है", "खांसी रात में ज़्यादा होती है", "सीने में दर्द नहीं है"]


def ready(doctor, patient, encounter, lines, language="en-IN"):
    grant(doctor, patient["id"], "ai_scribe")
    started = doctor.post(f"{BASE}/encounters/{encounter['id']}/sessions", json={"language": language}).json()
    for line in lines:
        doctor.post(f"{BASE}/sessions/{started['id']}/segments", json={"text": line, "speaker": "patient"})
    doctor.post(f"{BASE}/sessions/{started['id']}/state", json={"state": "stopped"})
    return started


def drafted(doctor, patient, encounter, monkeypatch, lines, statements, language="en-IN"):
    started = ready(doctor, patient, encounter, lines, language)
    content = {"sections": [{"heading": "Subjective", "statements": statements}], "missing_information": []}
    monkeypatch.setattr(llm, "ask", FakeAI(type(fake_draft()).model_validate(content)))
    return started, draft(doctor, started["id"]).json()


def lines_of(note):
    return [line for part in note["content"]["sections"] for line in part["statements"]]


def flagged_ids(note):
    return [line["id"] for line in lines_of(note) if line["check"]["verdict"] in verifier.FLAGGED]


def sign(doctor, note, acknowledged=None):
    ids = flagged_ids(note) if acknowledged is None else acknowledged
    return doctor.post(f"{BASE}/notes/{note['id']}/approve", json={"acknowledged": ids})


# --- the source line beside each statement -----------------------------------------------------


def test_each_statement_carries_the_lines_it_cites(doctor, patient, encounter, monkeypatch):
    _, note = drafted(
        doctor, patient, encounter, monkeypatch, HINDI_LINES,
        [statement("Fever for 3 days", cited=(1,)), statement("No chest pain", cited=(3,)), statement("Cough worse at night", cited=(2, 9))],
        language="hi-IN",
    )
    first, second, third = lines_of(doctor.get(f"{BASE}/notes/{note['id']}").json())
    assert first["sources"] == [{"line": 1, "speaker": "patient", "text": HINDI_LINES[0], "language": "hi-IN"}]
    assert second["sources"][0]["text"] == HINDI_LINES[2]
    assert [source["line"] for source in third["sources"]] == [2]  # a line that doesn't exist is not shown


def test_the_source_lines_are_never_saved_into_the_note(doctor, patient, encounter, monkeypatch):
    _, note = drafted(doctor, patient, encounter, monkeypatch, HINDI_LINES, [statement("Fever for 3 days", cited=(1,))], language="hi-IN")
    db = connect()
    stored = " ".join(row[0] for row in db.execute("SELECT content FROM clinical_note_versions"))
    db.close()
    assert HINDI_LINES[0] not in stored and '"sources"' not in stored


def test_a_patient_never_gets_source_lines(doctor, person, monkeypatch):
    from backend.tests.conftest import linked_patient

    account, record = linked_patient(doctor, person)
    visit = doctor.post(f"/api/patients/{record['id']}/encounters", json={"reason": "Follow-up"}).json()
    grant(doctor, record["id"], "transcript_retention")
    _, note = drafted(doctor, record, visit, monkeypatch, ["I have had a cough for three days"], [statement("Cough for three days")])
    assert sign(doctor, note).status_code == 200
    seen = account.get(f"{BASE}/notes/{note['id']}").json()
    assert all("sources" not in line for line in lines_of(seen))


# --- a transcript the rules can't check is not called verified ---------------------------------


def test_a_hindi_statement_is_not_checked_rather_than_verified(doctor, patient, encounter, monkeypatch):
    _, note = drafted(doctor, patient, encounter, monkeypatch, HINDI_LINES, [statement("Fever for 3 days", cited=(1,))], language="hi-IN")
    [line] = lines_of(note)
    assert line["check"]["verdict"] == "not_checked"
    summary = note["content"]["verification"]
    assert summary["status"] == "not_checked" and summary["not_checked"] == 1 and summary["supported"] == 0
    assert note["open_flags"] == 1


def test_the_page_does_not_call_the_hindi_flag_a_check():
    script = (WEB_DIR / "js" / "care" / "clinscribe.js").read_text(encoding="utf-8")
    assert "not_checked:" in script
    assert "Not checked" in script and "compare" in script.lower()


# --- one acknowledgement per flag --------------------------------------------------------------


def test_every_flagged_line_must_be_acknowledged_by_itself(doctor, patient, encounter, monkeypatch):
    _, note = drafted(
        doctor, patient, encounter, monkeypatch, ["I have had a cough for three days"],
        [statement("Cough for three days"), statement("Start insulin glargine tonight"), statement("Crackles at both lung bases")],
    )
    flagged = flagged_ids(note)
    assert len(flagged) == 2
    assert sign(doctor, note, []).json()["detail"]["code"] == "flags_open"
    partly = sign(doctor, note, flagged[:1])
    assert partly.status_code == 409
    assert partly.json()["detail"]["unacknowledged"] == flagged[1:]
    assert sign(doctor, note, flagged).status_code == 200


def test_a_blanket_tick_no_longer_signs_a_flagged_note(doctor, patient, encounter, monkeypatch):
    _, note = drafted(doctor, patient, encounter, monkeypatch, ["I have had a cough for three days"], [statement("Start insulin glargine tonight")])
    response = doctor.post(f"{BASE}/notes/{note['id']}/approve", json={"acknowledge_flags": True})
    assert response.status_code == 409 and response.json()["detail"]["code"] == "flags_open"


def test_an_acknowledgement_for_a_line_that_is_not_in_the_note_is_refused(doctor, patient, encounter, monkeypatch):
    _, note = drafted(doctor, patient, encounter, monkeypatch, ["I have had a cough for three days"], [statement("Start insulin glargine tonight")])
    assert sign(doctor, note, flagged_ids(note) + ["made-up-id"]).status_code == 422


def test_the_signed_note_records_which_flags_were_acknowledged(doctor, patient, encounter, monkeypatch):
    _, note = drafted(doctor, patient, encounter, monkeypatch, ["I have had a cough for three days"], [statement("Start insulin glargine tonight")])
    flagged = flagged_ids(note)
    signed = sign(doctor, note).json()
    assert signed["content"]["acknowledged_flags"] == flagged and signed["content"]["signed_with_open_flags"] == 1


def test_an_edited_line_gets_its_own_id_and_an_untouched_one_keeps_its_id(doctor, patient, encounter, monkeypatch):
    _, note = drafted(doctor, patient, encounter, monkeypatch, ["I have had a cough for three days"], [statement("Cough for three days")])
    [original] = lines_of(note)
    body = {"sections": [{"heading": "Subjective", "statements": [{"text": "Cough for three days"}, {"text": "Chest clear"}]}]}
    kept, added = lines_of(doctor.patch(f"{BASE}/notes/{note['id']}", json=body).json())
    assert kept["id"] == original["id"] and added["id"] and added["id"] != original["id"]


# --- no dangling pointers ---------------------------------------------------------------------


def test_signing_without_retention_drops_the_pointers_to_deleted_lines(doctor, patient, encounter, monkeypatch):
    _, note = drafted(doctor, patient, encounter, monkeypatch, ["I have had a cough for three days"], [statement("Cough for three days")])
    assert lines_of(note)[0]["evidence_segments"] == [1]
    signed = sign(doctor, note).json()
    assert signed["transcript_retained"] is False
    [line] = lines_of(signed)
    assert line["evidence_segments"] == [] and line["check"]["evidence"] == [] and "sources" not in line
    assert signed["content"]["sources_deleted"] is True
    again = lines_of(doctor.get(f"{BASE}/notes/{note['id']}").json())[0]
    assert again["evidence_segments"] == []


def test_signing_with_retention_keeps_the_pointers_and_the_lines(doctor, patient, encounter, monkeypatch):
    grant(doctor, patient["id"], "transcript_retention")
    _, note = drafted(doctor, patient, encounter, monkeypatch, ["I have had a cough for three days"], [statement("Cough for three days")])
    signed = sign(doctor, note).json()
    [line] = lines_of(signed)
    assert line["evidence_segments"] == [1] and line["sources"][0]["text"] == "I have had a cough for three days"


def test_deleting_the_transcript_of_a_draft_stops_showing_pointers(doctor, patient, encounter, monkeypatch):
    started, note = drafted(doctor, patient, encounter, monkeypatch, ["I have had a cough for three days"], [statement("Cough for three days")])
    assert doctor.delete(f"{BASE}/sessions/{started['id']}/transcript").status_code == 204
    [line] = lines_of(doctor.get(f"{BASE}/notes/{note['id']}").json())
    assert line["evidence_segments"] == [] and line["check"]["evidence"] == [] and "sources" not in line


# --- one active draft per session -------------------------------------------------------------


def test_a_session_has_one_active_draft(doctor, patient, encounter, monkeypatch):
    started, note = drafted(doctor, patient, encounter, monkeypatch, ["I have had a cough for three days"], [statement("Cough for three days")])
    second = draft(doctor, started["id"])
    assert second.status_code == 409
    assert second.json()["detail"] == {"code": "draft_exists", "note_id": note["id"], "message": "This session already has a draft. Open it, or discard it to draft again."}


def test_discarding_the_draft_allows_a_new_one(doctor, patient, encounter, monkeypatch):
    started, note = drafted(doctor, patient, encounter, monkeypatch, ["I have had a cough for three days"], [statement("Cough for three days")])
    doctor.post(f"{BASE}/notes/{note['id']}/discard")
    assert draft(doctor, started["id"]).status_code == 201


def test_a_refused_second_draft_costs_no_ai_call(doctor, patient, encounter, monkeypatch):
    started, _ = drafted(doctor, patient, encounter, monkeypatch, ["I have had a cough for three days"], [statement("Cough for three days")])
    monkeypatch.setattr(llm, "ask", lambda *args, **options: pytest.fail("the AI must not be called"))
    assert draft(doctor, started["id"]).status_code == 409
