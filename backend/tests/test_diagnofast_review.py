"""A doctor's reviewed stamp, and code checks on the AI's report that flag but never change it (WI-204)."""
import pytest

from backend import llm
from backend.auth import SESSION_COOKIE
from backend.diagnofast import validate
from backend.diagnofast.agent import Report, ReviewOfSystem, Turn
from backend.tests.test_diagnofast import ALL_REQUIRED, create_intake, doctor_session, say, services, start, turn  # noqa: F401

CONVERSATION = [
    {"question": "Any chest pain?", "answer": "No, no chest pain at all"},
    {"question": "Any cough?", "answer": "Yes, a dry cough for a week"},
    {"question": "What was your sugar reading?", "answer": "It was 180 this morning"},
]


def row(flag, finding="Chest pain", norm="Not applicable (symptom)", turns=(), system="Cardiovascular"):
    return {"system": system, "parameter": finding, "finding": finding, "flag": flag, "norm": norm, "evidence_turns": list(turns)}


def problems(rows=(), investigations=()):
    report = {"review_of_systems": list(rows), "suggested_investigations": list(investigations)}
    return validate.check_report(report, CONVERSATION)


def test_a_normal_row_must_cite_an_answer_with_a_negative():
    assert problems([row("NORMAL", "No chest pain", turns=[1])]) == []
    [problem] = problems([row("NORMAL", "No cough", turns=[2])])  # turn 2 says yes
    assert problem["field"] == "review_of_systems" and problem["index"] == 0 and "negative" in problem["problem"]
    [problem] = problems([row("NORMAL", "No chest pain")])  # cites nothing
    assert "negative" in problem["problem"]
    assert problems([row("NORMAL", "No chest pain", turns=[9])])  # cites a turn that doesn't exist


def test_hindi_negatives_count():
    conversation = [{"question": "सीने में दर्द?", "answer": "नहीं, कोई दर्द नहीं"}]
    report = {"review_of_systems": [row("NORMAL", "No chest pain", turns=[1])], "suggested_investigations": []}
    assert validate.check_report(report, conversation) == []


def test_a_high_or_low_flag_needs_a_number_and_a_range():
    assert problems([row("H*", "Fasting glucose 180 mg/dL", "70-100 mg/dL", turns=[3], system="Metabolic")]) == []
    [problem] = problems([row("H*", "Glucose high", "70-100 mg/dL", system="Metabolic")])
    assert "number" in problem["problem"]
    [problem] = problems([row("L*", "Haemoglobin 9 g/dL", "Not applicable (symptom)", system="Blood")])
    assert "range" in problem["problem"]
    assert problems([row("H*", "Glucose 180 mg/dL", "< 100 mg/dL", system="Metabolic")]) == []


def test_an_investigation_that_names_a_medicine_is_flagged():
    assert problems(investigations=["Complete blood count", "Chest X-ray"]) == []
    flagged = problems(investigations=["Complete blood count", "Start paracetamol 500 mg", "Azithromycin course"])
    assert [item["index"] for item in flagged] == [1, 2]
    assert all(item["field"] == "suggested_investigations" for item in flagged)


def test_the_validator_never_changes_the_report():
    report = {"review_of_systems": [row("NORMAL", "No cough", turns=[2])], "suggested_investigations": ["Paracetamol"]}
    before = repr(report)
    validate.check_report(report, CONVERSATION)
    assert repr(report) == before


class ReportAI:
    def __init__(self, report):
        self.turns, self.report = [turn(ALL_REQUIRED, finished=True)], report

    def __call__(self, system, content, schema, **options):
        return self.turns.pop(0) if schema is Turn else self.report


def _finished(client, details, monkeypatch, report):
    monkeypatch.setattr(llm, "ask", ReportAI(report))
    doctor_session(client, details)
    intake_id, token = create_intake(client)
    cookie = client.cookies[SESSION_COOKIE]
    client.cookies.clear()
    start(client, token)
    say(client, token, "No chest pain")
    client.cookies.set(SESSION_COOKIE, cookie)
    return intake_id


def make_report(rows=()):
    return Report(chief_complaint="Fever", present_illness="Three days of fever.", highlights=[], current_medicines=[],
                  allergies=[], past_history="", gaps=[], review_of_systems=[ReviewOfSystem(**item) for item in rows])


def test_a_flagged_report_shows_its_problems_and_keeps_its_content(client, details, services, monkeypatch):
    intake_id = _finished(client, details, monkeypatch, make_report([row("NORMAL", "No cough", turns=[])]))
    detail = client.get(f"/api/diagnofast/intakes/{intake_id}").json()
    assert detail["report"]["review_of_systems"][0]["flag"] == "NORMAL"  # unchanged
    assert detail["report_problems"] and detail["report_problems"][0]["field"] == "review_of_systems"


def test_a_report_is_unreviewed_until_a_doctor_stamps_it(client, details, services, monkeypatch, person):
    intake_id = _finished(client, details, monkeypatch, make_report())
    detail = client.get(f"/api/diagnofast/intakes/{intake_id}").json()
    assert detail["reviewed"] is None
    assert client.get("/api/diagnofast/intakes").json()[0]["reviewed"] is False

    assert person("doctor").post(f"/api/diagnofast/intakes/{intake_id}/review").status_code == 404  # not theirs
    stamped = client.post(f"/api/diagnofast/intakes/{intake_id}/review")
    assert stamped.status_code == 200
    detail = client.get(f"/api/diagnofast/intakes/{intake_id}").json()
    assert detail["reviewed"]["by"] == "Asha Rao" and detail["reviewed"]["at"]
    assert client.get("/api/diagnofast/intakes").json()[0]["reviewed"] is True
    assert client.post(f"/api/diagnofast/intakes/{intake_id}/review").status_code == 409  # stamped once


def test_an_interview_still_running_cannot_be_stamped(client, details, services):
    doctor_session(client, details)
    intake_id, _ = create_intake(client)
    assert client.post(f"/api/diagnofast/intakes/{intake_id}/review").status_code == 409
