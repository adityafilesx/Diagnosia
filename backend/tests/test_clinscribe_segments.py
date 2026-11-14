"""WI-222: typed lines are guarded by the session's state and by consent, and lost audio is counted."""
from backend import llm, speech
from backend.tests.conftest import FakeAI
from backend.tests.test_clinscribe import draft, encounter, fake_draft, ready_session, session  # noqa: F401 (fixtures)

BASE = "/api/addons/clinscribe"


def type_line(doctor, session_id, text="I have had a cough for three days", **fields):
    return doctor.post(f"{BASE}/sessions/{session_id}/segments", json={"text": text, **fields})


def lines(doctor, session_id):
    return doctor.get(f"{BASE}/sessions/{session_id}").json()["segments"]


def test_a_line_posted_to_a_stopped_session_is_refused(doctor, patient, encounter):
    started = ready_session(doctor, patient, encounter)
    response = type_line(doctor, started["id"], "A stray line from an old tab")
    assert response.status_code == 409
    assert len(lines(doctor, started["id"])) == 1


def test_a_missed_line_can_be_added_after_stop_when_it_says_so(doctor, patient, encounter):
    started = ready_session(doctor, patient, encounter)
    response = type_line(doctor, started["id"], "Also a fever since yesterday", missed_line=True)
    assert response.status_code == 201
    assert response.json()["source"] == "typed"
    assert [line["sequence"] for line in lines(doctor, started["id"])] == [1, 2]


def test_a_missed_line_flag_is_harmless_before_stop(doctor, patient, encounter):
    started = session(doctor, patient, encounter).json()
    assert type_line(doctor, started["id"], missed_line=True).status_code == 201


def test_typing_is_allowed_while_recording_or_paused(doctor, patient, encounter):
    started = session(doctor, patient, encounter).json()
    assert type_line(doctor, started["id"]).status_code == 201  # paused
    doctor.post(f"{BASE}/sessions/{started['id']}/state", json={"state": "recording"})
    assert type_line(doctor, started["id"]).status_code == 201


def test_no_line_is_kept_once_consent_is_revoked(doctor, patient, encounter):
    started = session(doctor, patient, encounter).json()
    consent = doctor.get(f"/api/patients/{patient['id']}/consents").json()["consents"][0]
    doctor.post(f"/api/patients/{patient['id']}/consents/{consent['id']}/revoke")
    response = type_line(doctor, started["id"])
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "consent_required"
    assert lines(doctor, started["id"]) == []
    doctor.post(f"{BASE}/sessions/{started['id']}/state", json={"state": "stopped"})
    assert type_line(doctor, started["id"], missed_line=True).status_code == 409


def test_nothing_is_added_once_the_note_is_signed(doctor, patient, encounter, monkeypatch):
    monkeypatch.setattr(llm, "ask", FakeAI(fake_draft()))
    started = ready_session(doctor, patient, encounter)
    note = draft(doctor, started["id"]).json()
    doctor.post(f"{BASE}/notes/{note['id']}/approve", json={"acknowledge_flags": True})
    response = type_line(doctor, started["id"], "Too late", missed_line=True)
    assert response.status_code == 409
    assert lines(doctor, started["id"]) == []  # the transcript was deleted on signing and stays empty


def recording(doctor, patient, encounter):
    started = session(doctor, patient, encounter).json()
    doctor.post(f"{BASE}/sessions/{started['id']}/state", json={"state": "recording"})
    return started


def send_audio(doctor, session_id):
    return doctor.post(f"{BASE}/sessions/{session_id}/transcribe", files={"audio": ("a.webm", b"audio", "audio/webm")})


def test_chunks_that_could_not_be_transcribed_are_counted(doctor, patient, encounter, monkeypatch):
    started = recording(doctor, patient, encounter)
    assert doctor.get(f"{BASE}/sessions/{started['id']}").json()["chunks_lost"] == 0

    def down(*args):
        raise speech.SpeechUnavailable("down")

    def rejected(*args):
        raise speech.SpeechRejected("bad audio")

    monkeypatch.setattr(speech, "transcribe", down)
    assert send_audio(doctor, started["id"]).status_code == 503
    monkeypatch.setattr(speech, "transcribe", rejected)
    assert send_audio(doctor, started["id"]).status_code == 422
    monkeypatch.setattr(speech, "transcribe", lambda *args: "I have a cough")
    assert send_audio(doctor, started["id"]).status_code == 201

    view = doctor.get(f"{BASE}/sessions/{started['id']}").json()
    assert view["chunks_lost"] == 2 and len(view["segments"]) == 1
    listed = doctor.get(f"{BASE}/patients/{patient['id']}/sessions").json()[0]
    assert listed["chunks_lost"] == 2


def test_silence_is_not_a_lost_chunk(doctor, patient, encounter, monkeypatch):
    started = recording(doctor, patient, encounter)
    monkeypatch.setattr(speech, "transcribe", lambda *args: "   ")
    assert send_audio(doctor, started["id"]).json() == {"segment": None}
    assert doctor.get(f"{BASE}/sessions/{started['id']}").json()["chunks_lost"] == 0


def test_the_draft_says_how_many_chunks_were_lost(doctor, patient, encounter, monkeypatch):
    started = recording(doctor, patient, encounter)

    def down(*args):
        raise speech.SpeechUnavailable("down")

    monkeypatch.setattr(speech, "transcribe", down)
    send_audio(doctor, started["id"])
    type_line(doctor, started["id"])
    doctor.post(f"{BASE}/sessions/{started['id']}/state", json={"state": "stopped"})
    monkeypatch.setattr(llm, "ask", FakeAI(fake_draft()))
    note = draft(doctor, started["id"]).json()
    assert note["chunks_lost"] == 1
