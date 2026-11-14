"""Medicines and allergies are always asked, and the form finishes the interview when the AI is down (WI-202)."""
import pytest

from backend import llm
from backend.auth import SESSION_COOKIE
from backend.diagnofast import agent
from backend.diagnofast.agent import Turn, load_form
from backend.tests.test_diagnofast import create_intake, doctor_session, say, services, start, turn  # noqa: F401

FORMS = ["general_physician", "dermatologist", "cardiology", "orthopedics", "ent", "pediatrics"]


def play(form, ai, language="en-IN", answer="Since Monday"):
    """Runs a whole interview through the real loop. Returns the questions asked and the final answers."""
    question = agent.first_question(form, language)
    asked, answers, conversation = [question], {}, []
    for count in range(1, agent.MAX_QUESTIONS + 2):
        conversation.append({"question": question, "answer": answer})
        step = agent.advance(form, answers, conversation, count, language)
        answers = step.answers
        if step.question is None:
            return asked, answers
        question = step.question
        asked.append(question)
    raise AssertionError("the interview never ended")


def question_for(form, key, language="en-IN"):
    return next(item["question"][language] for item in form["fields"] if item["key"] == key)


@pytest.mark.parametrize("form_id", FORMS)
def test_medicines_and_allergies_are_asked_even_if_the_ai_never_does(form_id, monkeypatch):
    # An AI that wanders: its own question every time, and it never fills the two fields.
    monkeypatch.setattr(llm, "ask", lambda *args, **options: turn({"chief_complaint": "Fever"}, question="Anything else?"))
    form = load_form(form_id)
    asked, answers = play(form, None)
    assert question_for(form, "current_medicines") in asked
    assert question_for(form, "allergies") in asked
    assert len(asked) <= agent.MAX_QUESTIONS
    # The patient's own words are kept for the doctor when the AI extracted nothing.
    assert answers["current_medicines"] == "Since Monday" and answers["allergies"] == "Since Monday"


def test_the_ai_can_still_fill_them_in_its_own_words(monkeypatch):
    form = load_form("general_physician")
    filled = {"current_medicines": "Metformin 500 mg", "allergies": "None known"}
    monkeypatch.setattr(llm, "ask", lambda *args, **options: turn(filled, question="Anything else?"))
    _, answers = play(form, None)
    assert answers["current_medicines"] == "Metformin 500 mg" and answers["allergies"] == "None known"


@pytest.mark.parametrize("failure", [llm.AIUnavailable("down"), llm.AIDeclined("no"), llm.AINotConfigured("no key"), llm.AIBudgetReached("cap")])
@pytest.mark.parametrize("form_id", FORMS)
def test_with_the_ai_down_the_form_finishes_the_interview(form_id, failure, monkeypatch):
    def down(*args, **options):
        raise failure

    monkeypatch.setattr(llm, "ask", down)
    form = load_form(form_id)
    asked, answers = play(form, None, language="hi-IN", answer="तीन दिन से")
    required = [item for item in form["fields"] if item["required"]]
    assert asked == [item["question"]["hi-IN"] for item in required]  # the form's own questions, in order
    assert all(answers[item["key"]] == "तीन दिन से" for item in required)


def test_an_urgent_answer_still_stops_the_fallback(monkeypatch):
    def down(*args, **options):
        raise llm.AIUnavailable("down")

    monkeypatch.setattr(llm, "ask", down)
    form = load_form("general_physician")
    step = agent.advance(form, {}, [{"question": agent.first_question(form, "en-IN"), "answer": "I have chest pain"}], 1, "en-IN")
    assert step.urgent == ["Chest pain"] and step.question is None


def test_a_patient_finishes_through_the_routes_with_no_ai_at_all(client, details, services, monkeypatch):
    def down(*args, **options):
        raise llm.AINotConfigured("no key")

    monkeypatch.setattr(llm, "ask", down)
    doctor_session(client, details)
    intake_id, token = create_intake(client)
    cookie = client.cookies[SESSION_COOKIE]
    client.cookies.clear()
    start(client, token)
    for _ in range(agent.MAX_QUESTIONS):
        reply = say(client, token, "Do din se")
        assert reply.status_code == 200
        if reply.json()["finished"]:
            break
    assert reply.json()["finished"] is True and reply.json()["urgent"] is False
    client.cookies.set(SESSION_COOKIE, cookie)
    detail = client.get(f"/api/diagnofast/intakes/{intake_id}").json()
    assert detail["status"] == "report_failed"  # no AI to write the summary: the doctor reads the answers
    filled = {item["label"]: item["value"] for item in detail["answers"]}
    form = load_form("general_physician")
    for item in form["fields"]:
        if item["required"]:
            assert filled[item["label"]] == "Do din se"


def test_a_patient_can_ask_for_a_person(client, details, services):
    doctor_session(client, details)
    intake_id, token = create_intake(client)
    cookie = client.cookies[SESSION_COOKIE]
    client.cookies.clear()
    assert client.post("/api/diagnofast/patient/not-a-link/help").status_code == 404
    assert client.post(f"/api/diagnofast/patient/{token}/help").status_code == 200
    client.cookies.set(SESSION_COOKIE, cookie)
    row = next(item for item in client.get("/api/diagnofast/intakes").json() if item["id"] == intake_id)
    assert row["needs_help"] is True
