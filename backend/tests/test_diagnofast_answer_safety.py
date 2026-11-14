"""An answer is saved once, links expire, and a reloaded page carries on (audit plan WI-102, WI-103)."""
import json
import threading

from fastapi.testclient import TestClient

from backend import llm
from backend.app import _sweep_once, app
from backend.auth import SESSION_COOKIE
from backend.config import settings
from backend.db import connect
from backend.tests.test_diagnofast import (
    ALL_REQUIRED,
    ScriptedAI,
    create_intake,
    doctor_session,
    say,
    services,  # noqa: F401  (a fixture)
    start,
    turn,
)


def _row(intake_id):
    db = connect()
    try:
        return db.execute("SELECT * FROM intakes WHERE id = ?", (intake_id,)).fetchone()
    finally:
        db.close()


def _set(intake_id, sql):
    db = connect()
    try:
        db.execute(f"UPDATE intakes SET {sql} WHERE id = ?", (intake_id,))
        db.commit()
    finally:
        db.close()


def _patient(client, details):
    doctor_session(client, details)
    intake_id, token = create_intake(client)
    cookie = client.cookies[SESSION_COOKIE]
    client.cookies.clear()  # the patient has no account
    return intake_id, token, cookie


def _recordings(intake_id):
    folder = settings.documents_dir / "intake-audio" / str(intake_id)
    return sorted(path.name for path in folder.glob("*.enc")) if folder.exists() else []


def test_two_answers_to_the_same_question_are_saved_once(client, details, services, monkeypatch):
    both_waiting = threading.Barrier(2, timeout=10)

    def slow_ai(system, content, schema, **options):
        both_waiting.wait()  # both requests have read the row before either writes
        return turn({"chief_complaint": "Fever"})

    monkeypatch.setattr(llm, "ask", slow_ai)
    intake_id, token, _ = _patient(client, details)
    start(client, token)

    results = []

    def send(text):
        with TestClient(app) as tab:  # a second tab or a retrying phone
            response = tab.post(
                f"/api/diagnofast/patient/{token}/answer",
                data={"text": text},
                files={"audio": ("answer", b"voice", "audio/webm")},
            )
            results.append(response.status_code)

    threads = [threading.Thread(target=send, args=(text,)) for text in ("Bukhar hai", "Sir dard hai")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert sorted(results) == [200, 409]
    row = _row(intake_id)
    transcript = json.loads(row["transcript"])
    assert len(transcript) == 1
    assert row["questions_asked"] == 2
    # The losing answer's recording is not left behind.
    assert _recordings(intake_id) == [transcript[0]["audio"] + ".enc"]


def test_a_retried_answer_gets_the_same_reply_and_is_saved_once(client, details, services, monkeypatch):
    ai = ScriptedAI([turn({"chief_complaint": "Fever"}, question="Since when?")])
    monkeypatch.setattr(llm, "ask", ai)
    intake_id, token, _ = _patient(client, details)
    start(client, token)

    answer = {"text": "Bukhar hai", "answer_key": "key-1"}
    first = client.post(f"/api/diagnofast/patient/{token}/answer", data=answer)
    again = client.post(f"/api/diagnofast/patient/{token}/answer", data=answer)

    assert first.status_code == again.status_code == 200
    assert again.json()["question"] == first.json()["question"] == "Since when?"
    assert len(ai.calls) == 1  # the retry did not ask the AI again
    assert _row(intake_id)["questions_asked"] == 2


def test_a_retry_after_the_last_answer_still_gets_its_thank_you(client, details, services, monkeypatch):
    monkeypatch.setattr(llm, "ask", ScriptedAI([turn(ALL_REQUIRED, finished=True)]))
    intake_id, token, _ = _patient(client, details)
    start(client, token)

    answer = {"text": "Bukhar hai", "answer_key": "last"}
    first = client.post(f"/api/diagnofast/patient/{token}/answer", data=answer).json()
    again = client.post(f"/api/diagnofast/patient/{token}/answer", data=answer)

    assert first["finished"] is True
    assert again.status_code == 200
    assert again.json()["message"] == first["message"]
    # Without the key, the finished link is still closed.
    assert say(client, token).status_code == 404


def test_an_unused_link_expires(client, details, services):
    intake_id, token, cookie = _patient(client, details)
    assert _row(intake_id)["expires_at"]
    _set(intake_id, "expires_at = datetime('now', '-1 minute')")

    refused = client.get(f"/api/diagnofast/patient/{token}")
    assert refused.status_code == 404
    assert "expired" in refused.json()["detail"]
    assert start(client, token).status_code == 404

    _sweep_once()
    assert _row(intake_id)["status"] == "expired"
    client.cookies.set(SESSION_COOKIE, cookie)
    assert client.get("/api/diagnofast/intakes").json()[0]["status"] == "expired"


def test_a_started_interview_gets_its_own_window(client, details, services, monkeypatch):
    monkeypatch.setattr(settings, "diagnofast_interview_hours", 3)
    intake_id, token, _ = _patient(client, details)
    start(client, token)
    db = connect()
    try:
        hours = db.execute(
            "SELECT round((julianday(expires_at) - julianday('now')) * 24) FROM intakes WHERE id = ?", (intake_id,)
        ).fetchone()[0]
    finally:
        db.close()
    assert hours == 3

    _set(intake_id, "expires_at = datetime('now', '-1 minute')")
    assert say(client, token).status_code == 404


def test_a_reloaded_page_carries_on_at_the_same_question(client, details, services, monkeypatch):
    monkeypatch.setattr(llm, "ask", ScriptedAI([turn({"chief_complaint": "Fever"}, question="Since when?")]))
    intake_id, token, _ = _patient(client, details)

    waiting = client.get(f"/api/diagnofast/patient/{token}").json()
    assert waiting["status"] == "waiting"
    assert "question" not in waiting

    start(client, token)
    say(client, token)
    page = client.get(f"/api/diagnofast/patient/{token}").json()
    assert page["status"] == "in_progress"
    assert page["language"] == "hi-IN"
    assert page["question"] == "Since when?"
    assert page["questions_asked"] == 2


def test_a_second_start_is_refused(client, details, services):
    _, token, _ = _patient(client, details)
    assert start(client, token).status_code == 200
    assert start(client, token).status_code == 409
