"""Doctor report additions (step 9): Hindi beside a labelled machine translation, the reviewing doctor's
feedback question, feedback scored in diagnofast_eval, and Hinglish phrasings in a dev-only set."""
import json
from pathlib import Path

import pytest

from backend import llm, speech
from backend.db import connect
from backend.diagnofast import guidance
from backend.operator_cli import main as operator
from backend.records import consent
from backend.synthetic import diagnofast_eval
from backend.tests.test_diagnofast import ALL_REQUIRED, ScriptedAI, turn
from backend.tests.test_opd_bookings import switch

HINDI = "मुझे दो दिन से बुखार है"


def interview(doctor, client, monkeypatch, answers=(HINDI, "No cough")):
    turns = [turn(question="?") for _ in answers[:-1]] + [turn(ALL_REQUIRED, finished=True)]
    monkeypatch.setattr(llm, "ask", ScriptedAI(turns))
    made = doctor.post("/api/diagnofast/intakes", json={"form_id": "general_physician", "patient_name": "Ravi Kumar"}).json()
    token = made["link"].split("token=")[1]
    client.cookies.clear()
    client.post(f"/api/diagnofast/patient/{token}/start", json={"language": "hi-IN", "consent": True, "consent_version": consent.VERSION})
    for text in answers:
        client.post(f"/api/diagnofast/patient/{token}/answer", data={"text": text})
    return made["id"]


# Translation


def test_hindi_answers_get_a_labelled_machine_translation_beside_them(doctor, client, monkeypatch):
    seen = []
    monkeypatch.setattr(speech, "translate_to_english", lambda text: seen.append(text) or ("I have had a fever for two days" if "बुखार" in text else None))
    intake_id = interview(doctor, client, monkeypatch)
    detail = doctor.get(f"/api/diagnofast/intakes/{intake_id}").json()
    first, second = detail["transcript"]
    assert first["answer"] == HINDI  # the patient's own words never change
    assert first["english"] == "I have had a fever for two days"
    assert first["english_label"] == "machine translation"
    assert "english" not in second
    assert seen == [HINDI, "No cough"]  # speech.py itself skips text with no Devanagari


def test_a_failed_translation_leaves_the_report_unharmed(doctor, client, monkeypatch):
    monkeypatch.setattr(speech, "translate_to_english", lambda text: None)
    intake_id = interview(doctor, client, monkeypatch)
    detail = doctor.get(f"/api/diagnofast/intakes/{intake_id}").json()
    assert detail["status"] == "done"
    assert "english" not in detail["transcript"][0]


def test_the_report_ai_still_reads_the_patients_own_words(doctor, client, monkeypatch):
    monkeypatch.setattr(speech, "translate_to_english", lambda text: "TRANSLATED")
    ai = ScriptedAI([turn(question="?"), turn(ALL_REQUIRED, finished=True)])
    monkeypatch.setattr(llm, "ask", ai)
    made = doctor.post("/api/diagnofast/intakes", json={"form_id": "general_physician", "patient_name": "Ravi Kumar"}).json()
    token = made["link"].split("token=")[1]
    client.cookies.clear()
    client.post(f"/api/diagnofast/patient/{token}/start", json={"language": "hi-IN", "consent": True, "consent_version": consent.VERSION})
    client.post(f"/api/diagnofast/patient/{token}/answer", data={"text": HINDI})
    client.post(f"/api/diagnofast/patient/{token}/answer", data={"text": "नहीं"})
    report_request = next(call for call in ai.calls if call.get("tool") == "diagnofast_report")
    assert HINDI in report_request["content"] and "TRANSLATED" not in report_request["content"]


# Feedback at review


def test_the_feedback_question_is_off_until_switched_on(doctor, client, monkeypatch):
    intake_id = interview(doctor, client, monkeypatch)
    assert doctor.get(f"/api/diagnofast/intakes/{intake_id}").json()["feedback"] is None
    assert doctor.post(f"/api/diagnofast/intakes/{intake_id}/feedback", json={"wished_asked": "travel"}).status_code == 403


def test_a_doctor_can_say_what_they_wished_had_been_asked(doctor, client, monkeypatch):
    switch("diagnofast.review_feedback")
    intake_id = interview(doctor, client, monkeypatch)
    assert doctor.get(f"/api/diagnofast/intakes/{intake_id}").json()["feedback"] == {"question": "Anything you wish had been asked?", "answers": []}
    response = doctor.post(f"/api/diagnofast/intakes/{intake_id}/feedback", json={"wished_asked": "Whether they had travelled recently", "good_question": "Have you travelled anywhere in the last two weeks?"})
    assert response.status_code == 201
    answers = doctor.get(f"/api/diagnofast/intakes/{intake_id}").json()["feedback"]["answers"]
    assert answers[0]["wished_asked"] == "Whether they had travelled recently"


def test_feedback_needs_words_and_a_finished_interview(doctor, client, monkeypatch):
    switch("diagnofast.review_feedback")
    made = doctor.post("/api/diagnofast/intakes", json={"form_id": "general_physician", "patient_name": "Ravi Kumar"}).json()
    assert doctor.post(f"/api/diagnofast/intakes/{made['id']}/feedback", json={"wished_asked": "travel"}).status_code == 409
    intake_id = interview(doctor, client, monkeypatch)
    assert doctor.post(f"/api/diagnofast/intakes/{intake_id}/feedback", json={"wished_asked": "  "}).status_code == 422
    assert doctor.post(f"/api/diagnofast/intakes/{intake_id}/feedback", json={"wished_asked": "x" * 1001}).status_code == 422


def test_a_stranger_cannot_give_or_read_feedback(doctor, person, client, monkeypatch):
    switch("diagnofast.review_feedback")
    intake_id = interview(doctor, client, monkeypatch)
    stranger = person("doctor", "Zed", "Stranger")
    assert stranger.post(f"/api/diagnofast/intakes/{intake_id}/feedback", json={"wished_asked": "travel"}).status_code in (403, 404)


def test_feedback_becomes_a_prompt_example_only_after_a_person_promotes_it(doctor, client, monkeypatch):
    switch("diagnofast.review_feedback")
    intake_id = interview(doctor, client, monkeypatch)
    doctor.post(f"/api/diagnofast/intakes/{intake_id}/feedback", json={"wished_asked": "travel", "good_question": "Have you travelled in the last two weeks?"})
    db = connect()
    assert not any(example.get("source") == "doctor_feedback" for example in guidance.examples(db))
    feedback_id = db.execute("SELECT id FROM diagnofast_feedback").fetchone()[0]
    db.close()
    assert operator(["feedback-promote", "--id", str(feedback_id), "--operator", "tester"]) == 0
    db = connect()
    promoted = [example for example in guidance.examples(db) if example.get("source") == "doctor_feedback"]
    db.close()
    assert promoted == [{"source": "doctor_feedback", "patient_said": "", "good_question": "Have you travelled in the last two weeks?"}]


# The evaluation


def test_feedback_is_scored_against_what_the_question_graph_would_ask():
    rows = [
        {"complaints": ["fever"], "wished_asked": "Whether they travelled anywhere"},
        {"complaints": ["fever"], "wished_asked": "Sleep and appetite"},
        {"complaints": [], "wished_asked": "Family history of diabetes"},
    ]
    score = diagnofast_eval.score_feedback(rows, guidance.seed())
    assert score["total"] == 3
    assert score["covered_by_graph"] == 1
    assert score["themes"]["travel"] == 1


def test_hinglish_phrasings_live_in_a_dev_only_set_outside_v1():
    folder = Path(diagnofast_eval.__file__).resolve().parents[1] / "tests" / "ai_eval" / "diagnofast" / "hinglish_dev"
    rows = [json.loads(line) for line in (folder / "screening_dev.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(rows) >= 30
    assert {row["split"] for row in rows} == {"dev"}
    assert {row["script"] for row in rows} <= {"hinglish_rom", "hinglish_mixed"}
    v1 = Path(folder).parent / "v1"
    assert not any("hinglish" in path.name for path in v1.iterdir())


def test_the_hinglish_score_is_reported(capsys):
    assert diagnofast_eval.main(["--hinglish"]) == 0
    out = capsys.readouterr().out
    assert "Hinglish" in out and "dev only" in out
