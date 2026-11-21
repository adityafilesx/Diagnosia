"""Graph-guided, doctor-like follow-up questions (step 7). The graph advises; the code's rules decide."""
import json

import pytest

from backend import llm
from backend.config import settings
from backend.db import connect
from backend.diagnofast import agent, guidance
from backend.integrations import graph
from backend.records import consent
from backend.tests.fake_graph import FakeGraph
from backend.tests.test_diagnofast import ScriptedAI, create_intake, doctor_session, form, services, turn  # noqa: F401
from backend.tests.test_opd_bookings import switch


@pytest.fixture
def fake_graph(client, monkeypatch):
    fake = FakeGraph()
    graph.use(fake)
    monkeypatch.setattr(settings, "neo4j_uri", "neo4j://127.0.0.1:7687")
    switch("neo4j.enabled")
    yield fake
    graph.use(None)


def started(client, details, language="hi-IN", **extra):
    doctor_session(client, details)
    intake_id, token = create_intake(client, **extra)
    client.cookies.clear()
    assert client.post(f"/api/diagnofast/patient/{token}/start", json={"language": language, "consent": True, "consent_version": consent.VERSION}).status_code == 200
    return intake_id, token


def request_body(ai):
    return json.loads(ai.calls[-1]["content"])


# The seed file


def test_the_seed_is_versioned_and_marked_not_clinically_reviewed():
    seed = guidance.seed()
    assert seed["version"] == "questions_v2"
    assert seed["clinically_reviewed"] is False and "NOT CLINICALLY REVIEWED" in seed["status"]
    for complaint in seed["complaints"]:
        for key in ("follow_ups", "associated", "red_flags"):
            for item in complaint[key]:
                assert item["en"].strip() and item["hi"].strip(), item["id"]


def test_pain_follows_socrates_and_fever_asks_pattern_chills_rash_and_travel():
    seed = {c["id"]: c for c in guidance.seed()["complaints"]}
    assert {"pain_site", "pain_onset", "pain_character", "pain_time", "pain_triggers", "pain_severity"} <= {q["id"] for q in seed["headache"]["follow_ups"]}
    assert {"fever_duration", "fever_pattern", "fever_chills", "fever_rash", "fever_travel"} <= {q["id"] for q in seed["fever"]["follow_ups"]}


@pytest.mark.parametrize("said, expected", [
    ("मुझे तीन दिन से बुखार है", ["fever"]),
    ("sar dard aur bukhar", ["fever", "headache"]),
    ("My stomach pain is bad", ["abdominal_pain"]),
    ("pet mein dard hai", ["abdominal_pain"]),
    ("I moved here last year", []),  # "ear" inside "year" is not an ear problem
    ("हमारा मकान दूर है", []),  # "कान" inside "मकान" is not an ear either
])
def test_complaints_are_matched_in_english_hindi_and_hinglish(said, expected):
    assert sorted(guidance.match_complaints([said])) == sorted(expected)


# Vague answers


@pytest.mark.parametrize("said, ask", [
    ("kabhi kabhi", "times a week"), ("Sometimes", "times a week"), ("कभी-कभी होता है", "times a week"),
    ("bahut dard hai", "1 to 10"), ("a lot", "1 to 10"), ("kaafi din se", "how many days"),
])
def test_vague_answers_get_a_probe(said, ask):
    assert ask in guidance.vague_probe(said)["ask_about"]


@pytest.mark.parametrize("said", ["3 times a week", "दिन में 2 बार", "It started on Monday evening after dinner and has not stopped since then at all", ""])
def test_precise_or_long_answers_are_not_probed(said):
    assert guidance.vague_probe(said) is None


# The graph's order


def test_the_graph_asks_follow_ups_then_red_flag_screens_then_associated_symptoms():
    fake = FakeGraph()
    fake.load_questions(guidance.seed())
    order, asked = [], []
    while (found := fake.next_question(["fever"], asked)) is not None:
        order.append(found["kind"])
        asked.append(found["id"])
    assert order == ["follow_up"] * 6 + ["red_flag"] * 2 + ["associated"] * 3


# The interview, with the switches


def test_with_both_switches_off_the_request_is_exactly_as_before(client, details, services, fake_graph, monkeypatch):
    ai = ScriptedAI([turn(question="Next?")])
    monkeypatch.setattr(llm, "ask", ai)
    _, token = started(client, details)
    client.post(f"/api/diagnofast/patient/{token}/answer", data={"text": "मुझे बुखार है"})
    assert ai.calls[-1]["system"] == agent.TURN_SYSTEM
    assert set(request_body(ai)) == {"patient_language", "form_fields", "answers_so_far", "conversation"}
    assert fake_graph.calls == []


def test_the_graph_picks_the_next_question_and_the_ai_only_words_it(client, details, services, fake_graph, monkeypatch):
    switch("diagnofast.graph_followups")
    ai = ScriptedAI([turn(question="पहला"), turn(question="दूसरा")])
    monkeypatch.setattr(llm, "ask", ai)
    intake_id, token = started(client, details)
    client.post(f"/api/diagnofast/patient/{token}/answer", data={"text": "मुझे बुखार है"})
    first = request_body(ai)["graph_suggestion"]
    assert first == {"id": "fever_duration", "kind": "follow_up", "question": "आपको कितने दिनों से बुखार है?", "english": "How many days have you had the fever?"}
    assert "Graph guidance" in ai.calls[-1]["system"]
    client.post(f"/api/diagnofast/patient/{token}/answer", data={"text": "दो दिन से"})
    assert request_body(ai)["graph_suggestion"]["id"] == "fever_pattern"  # the same question is never offered twice
    db = connect()
    state = json.loads(db.execute("SELECT graph_state FROM intakes WHERE id = ?", (intake_id,)).fetchone()[0])
    db.close()
    assert state == {"complaints": ["fever"], "asked": ["fever_duration", "fever_pattern"]}


def test_a_red_flag_screen_question_is_labelled_as_screening(client, details, services, fake_graph, monkeypatch):
    switch("diagnofast.graph_followups")
    ai = ScriptedAI([turn(question="?")])
    monkeypatch.setattr(llm, "ask", ai)
    intake_id, token = started(client, details)
    db = connect()
    asked = [q["id"] for q in guidance.seed()["complaints"][0]["follow_ups"]]
    db.execute("UPDATE intakes SET graph_state = ? WHERE id = ?", (json.dumps({"complaints": ["fever"], "asked": asked}), intake_id))
    db.commit()
    db.close()
    client.post(f"/api/diagnofast/patient/{token}/answer", data={"text": "मुझे बुखार है"})
    assert request_body(ai)["graph_suggestion"]["kind"] == "red_flag_screen"


def test_an_urgent_answer_stops_before_the_graph_or_the_ai_is_asked(client, details, services, fake_graph, monkeypatch):
    switch("diagnofast.graph_followups")
    switch("diagnofast.doctor_like_interview")
    def no_turn(system, content, schema, **options):
        assert schema is not agent.Turn, "the rules stop this before any interview question"
        return ScriptedAI([]).__call__(system, content, schema, **options)

    monkeypatch.setattr(llm, "ask", no_turn)
    _, token = started(client, details)
    reply = client.post(f"/api/diagnofast/patient/{token}/answer", data={"text": "मेरे सीने में दर्द है"}).json()
    assert reply["urgent"] is True
    assert fake_graph.calls == []


def test_neo4j_down_means_the_ai_chooses_alone(client, details, services, fake_graph, monkeypatch):
    switch("diagnofast.graph_followups")
    fake_graph.down = True
    ai = ScriptedAI([turn(question="Next?")])
    monkeypatch.setattr(llm, "ask", ai)
    _, token = started(client, details)
    response = client.post(f"/api/diagnofast/patient/{token}/answer", data={"text": "मुझे बुखार है"})
    assert response.status_code == 200 and response.json()["question"] == "Next?"
    assert "graph_suggestion" not in request_body(ai)


def test_real_patient_data_stops_the_graph(client, details, services, fake_graph, monkeypatch):
    switch("diagnofast.graph_followups")
    monkeypatch.setattr(settings, "allow_real_patient_data", True)
    ai = ScriptedAI([turn(question="Next?")])
    monkeypatch.setattr(llm, "ask", ai)
    _, token = started(client, details)
    client.post(f"/api/diagnofast/patient/{token}/answer", data={"text": "मुझे बुखार है"})
    assert fake_graph.calls == [] and "graph_suggestion" not in request_body(ai)


def test_the_graph_leaves_room_for_medicines_and_allergies(form):
    from backend.tests.test_diagnofast import ALL_REQUIRED

    answers = {key: value for key, value in ALL_REQUIRED.items() if key not in agent.HIGH_RISK_FIELDS}
    # The AI followed the graph and asked about travel, but the cap still saves the last questions.
    step = agent.apply_turn(form, answers, turn(answers, question="Have you travelled?"), agent.MAX_QUESTIONS - 2, "en-IN")
    assert step.question == form["fields"][[f["key"] for f in form["fields"]].index("current_medicines")]["question"]["en-IN"]


def test_no_graph_question_is_offered_when_only_required_questions_fit(client, details, services, fake_graph, monkeypatch):
    switch("diagnofast.graph_followups")
    ai = ScriptedAI([turn(question="?")])
    monkeypatch.setattr(llm, "ask", ai)
    intake_id, token = started(client, details)
    db = connect()
    db.execute("UPDATE intakes SET questions_asked = ? WHERE id = ?", (agent.MAX_QUESTIONS - 3, intake_id))
    db.commit()
    db.close()
    client.post(f"/api/diagnofast/patient/{token}/answer", data={"text": "मुझे बुखार है"})
    assert "graph_suggestion" not in request_body(ai)


def test_the_doctor_like_interview_adds_known_context_with_sources(client, details, services, monkeypatch):
    switch("diagnofast.doctor_like_interview")
    ai = ScriptedAI([turn(question="?")])
    monkeypatch.setattr(llm, "ask", ai)
    doctor_session(client, details)
    _, token = create_intake(client, patient_age=61, patient_sex="female", abha_id="91-1111-2222-3333")
    client.cookies.clear()
    client.post(f"/api/diagnofast/patient/{token}/start", json={"language": "en-IN", "consent": True, "consent_version": consent.VERSION, "abha_consent": True})
    client.post(f"/api/diagnofast/patient/{token}/answer", data={"text": "Sometimes I get headaches"})
    body = request_body(ai)
    assert {"source": "booking", "fact": "Age 61"} in body["known_context"]
    abha = [fact for fact in body["known_context"] if fact["source"] == "abha_simulated"]
    assert abha and all("Metformin" in fact["fact"] or "diabetes" in fact["fact"].lower() or ":" in fact["fact"] for fact in abha)
    assert body["vague_answer"]["ask_about"].startswith("how many times")
    assert body["examples"] and all(example["source"] for example in body["examples"])
    system = ai.calls[-1]["system"]
    assert "Hinglish" in system and "abha_simulated" in system and "Never copy a known_context fact" in system


def test_past_visits_are_labelled_reviewed_or_not(client, details, services, patient, doctor, monkeypatch):
    switch("diagnofast.doctor_like_interview")
    db = connect()
    db.execute(
        """INSERT INTO intakes (token_hash, doctor_id, form_id, patient_name, patient_id, status, report, reviewed_at)
           VALUES ('old', ?, 'general_physician', 'Ravi Kumar', ?, 'done', ?, datetime('now'))""",
        (doctor.id, patient["id"], json.dumps({"chief_complaint": "Cough", "current_medicines": ["Metformin 500 mg"], "allergies": []})),
    )
    db.commit()
    row_id = db.execute("SELECT id FROM intakes WHERE token_hash = 'old'").fetchone()[0]
    current = dict(db.execute("SELECT * FROM intakes WHERE id = ?", (row_id,)).fetchone())
    current.update(id=row_id + 1, records=None, patient_age=None, patient_sex=None)
    facts = guidance.known_context(db, current)
    db.close()
    assert {"source": "past_visit_reviewed", "fact": f"{facts[0]['fact'][:10]}: came with Cough"} in facts
    assert any("Metformin" in fact["fact"] for fact in facts)


def test_the_neo4j_client_loads_questions_with_constraints_and_merge():
    class Driver:
        def __init__(self):
            self.queries = []

        def execute_query(self, query, params, database_):
            self.queries.append((query, params, database_))
            return [], None, []

    driver = Driver()
    client = graph.Neo4jGraph(driver, "neo4j")
    client.load_questions(guidance.seed())
    statements = [query for query, _, _ in driver.queries]
    assert all("IF NOT EXISTS" in s for s in statements[:-1])
    assert "MERGE (c:Complaint" in statements[-1] and "CREATE (" not in statements[-1]
    assert all(database == "neo4j" for _, _, database in driver.queries)


def test_a_driver_failure_is_reported_without_its_message():
    class Driver:
        def execute_query(self, query, params, database_):
            raise RuntimeError("secret patient words in the message")

    with pytest.raises(graph.GraphUnavailable) as caught:
        graph.Neo4jGraph(Driver(), "neo4j").next_question(["fever"], [])
    assert "patient" not in str(caught.value)


def test_a_question_id_has_one_wording_because_neo4j_merges_on_it():
    # MERGE (q:Question {id}) keeps one node per ID, so two wordings under one ID would silently become one.
    wordings = {}
    for complaint in guidance.seed()["complaints"]:
        for key in ("follow_ups", "associated", "red_flags"):
            for item in complaint[key]:
                wordings.setdefault(item["id"], set()).add((item["en"], item["hi"]))
    assert {qid: texts for qid, texts in wordings.items() if len(texts) > 1} == {}


def test_the_fake_keeps_one_question_per_id_as_merge_does():
    seed = {"version": "t", "complaints": [
        {"id": "a", "department": "ent", "follow_ups": [{"id": "q", "en": "first", "hi": "पहला"}], "associated": [], "red_flags": []},
        {"id": "b", "department": "ent", "follow_ups": [{"id": "q", "en": "second", "hi": "दूसरा"}], "associated": [], "red_flags": []},
    ]}
    fake = FakeGraph()
    fake.load_questions(seed)
    assert fake.next_question(["a"], [])["en"] == fake.next_question(["b"], [])["en"] == "second"
