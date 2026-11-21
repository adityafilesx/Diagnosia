"""The Neo4j projection worker and the history and evidence graphs on the doctor's report (step 8).

SQLite stays the record: a reference is queued with the change, the worker re-reads SQLite, Neo4j gets
IDs and coded terms only, and anything shown is read again from SQLite after the access gate.
"""
import json

import pytest

from backend import llm
from backend.config import settings
from backend.db import connect
from backend.diagnofast import agent, graph_sync
from backend.diagnofast.agent import Report, ReviewOfSystem
from backend.integrations import graph
from backend.records import consent
from backend.tests.fake_graph import FakeGraph
from backend.tests.test_diagnofast import ALL_REQUIRED, ScriptedAI, turn
from backend.tests.test_opd_bookings import switch


def full_report():
    return Report(
        chief_complaint="Fever for three days",
        present_illness="Fever with chills, no cough.",
        highlights=[], current_medicines=["Metformin 500 mg twice a day"], allergies=["Penicillin"],
        past_history="", gaps=[],
        review_of_systems=[
            ReviewOfSystem(system="General", parameter="Fever", finding="Patient-reported fever", flag="NOT_ASSESSED", norm="Not applicable (symptom)", evidence_turns=[1]),
            ReviewOfSystem(system="Respiratory", parameter="Cough", finding="No cough", flag="NORMAL", norm="Not applicable (symptom)", evidence_turns=[2]),
        ],
    )


class ReportAI(ScriptedAI):
    def __call__(self, system, content, schema, **options):
        self.calls.append({"system": system, "content": content, "schema": schema, **options})
        return self.turns.pop(0) if schema is agent.Turn else full_report()


@pytest.fixture
def fake_graph(client, monkeypatch):
    fake = FakeGraph()
    graph.use(fake)
    monkeypatch.setattr(settings, "neo4j_uri", "neo4j://127.0.0.1:7687")
    switch("neo4j.enabled")
    yield fake
    graph.use(None)


def finished_interview(doctor, client, monkeypatch, patient_id=None):
    monkeypatch.setattr(llm, "ask", ReportAI([turn(question="Any cough?"), turn(ALL_REQUIRED, finished=True)]))
    body = {"form_id": "general_physician", "patient_name": "Ravi Kumar"}
    if patient_id:
        body["patient_id"] = patient_id
    made = doctor.post("/api/diagnofast/intakes", json=body).json()
    token = made["link"].split("token=")[1]
    client.cookies.clear()
    client.post(f"/api/diagnofast/patient/{token}/start", json={"language": "en-IN", "consent": True, "consent_version": consent.VERSION})
    client.post(f"/api/diagnofast/patient/{token}/answer", data={"text": "I have had a fever for three days"})
    client.post(f"/api/diagnofast/patient/{token}/answer", data={"text": "No cough"})
    return made["id"]


def queued(source_id):
    db = connect()
    try:
        return db.execute("SELECT state FROM graph_items WHERE source_type = 'intake' AND source_id = ?", (str(source_id),)).fetchone()
    finally:
        db.close()


def test_a_finished_report_is_queued_in_the_same_transaction(doctor, client, patient, fake_graph, monkeypatch):
    intake_id = finished_interview(doctor, client, monkeypatch, patient["id"])
    assert queued(intake_id)["state"] == "queued"


def test_nothing_is_queued_with_neo4j_off(doctor, client, patient, monkeypatch):
    intake_id = finished_interview(doctor, client, monkeypatch, patient["id"])
    assert queued(intake_id) is None


def test_the_worker_sends_ids_and_coded_terms_only(doctor, client, patient, fake_graph, monkeypatch):
    intake_id = finished_interview(doctor, client, monkeypatch, patient["id"])
    assert graph_sync.run_once() == 1
    visit = fake_graph.visits[f"intake:{intake_id}"]
    assert visit["patient_ref"] == f"patient:{patient['id']}"
    assert visit["doctor_ref"] == f"doctor:{doctor.id}"
    assert visit["department"] == "general_physician"
    kinds = {(term["kind"], term["code"]) for term in visit["terms"]}
    assert ("complaint", "fever") in kinds and ("medicine", "metformin") in kinds and ("allergy", "penicillin") in kinds
    text = json.dumps(visit)
    for free_text in ("Ravi", "three days", "No cough", "twice a day", "I have had"):
        assert free_text not in text
    assert [row["turns"] for row in visit["rows"]] == [[1], [2]]
    assert queued(intake_id)["state"] == "sent"


def test_sending_twice_changes_nothing(doctor, client, patient, fake_graph, monkeypatch):
    intake_id = finished_interview(doctor, client, monkeypatch, patient["id"])
    graph_sync.run_once()
    first = json.dumps(fake_graph.visits, sort_keys=True)
    db = connect()
    graph_sync.enqueue(db, "intake", intake_id)
    db.commit()
    db.close()
    graph_sync.run_once()
    assert json.dumps(fake_graph.visits, sort_keys=True) == first


def test_an_outage_is_retried_later_and_nothing_is_lost(doctor, client, patient, fake_graph, monkeypatch):
    intake_id = finished_interview(doctor, client, monkeypatch, patient["id"])
    fake_graph.down = True
    assert graph_sync.run_once() == 0
    assert queued(intake_id)["state"] == "queued"
    fake_graph.down = False
    db = connect()
    db.execute("UPDATE graph_items SET next_attempt_at = '2000-01-01T00:00:00+00:00'")
    db.commit()
    db.close()
    assert graph_sync.run_once() == 1


def test_real_patient_data_stops_the_worker(doctor, client, patient, fake_graph, monkeypatch):
    finished_interview(doctor, client, monkeypatch, patient["id"])
    monkeypatch.setattr(settings, "allow_real_patient_data", True)
    assert graph_sync.run_once() == 0
    assert fake_graph.visits == {}


def test_the_evidence_view_ties_each_row_to_its_answer_and_recording(doctor, client, patient, fake_graph, monkeypatch):
    intake_id = finished_interview(doctor, client, monkeypatch, patient["id"])
    graph_sync.run_once()
    view = doctor.get(f"/api/diagnofast/intakes/{intake_id}/graph").json()
    assert view["source"] == "neo4j"
    [fever, cough] = view["evidence"]
    assert fever["row"]["parameter"] == "Fever" and fever["answers"][0]["turn"] == 1
    assert fever["answers"][0]["answer"] == "I have had a fever for three days"  # words re-read from SQLite
    assert cough["answers"][0]["answer"] == "No cough"


def test_with_neo4j_down_the_evidence_comes_from_sqlite(doctor, client, patient, fake_graph, monkeypatch):
    intake_id = finished_interview(doctor, client, monkeypatch, patient["id"])
    fake_graph.down = True
    view = doctor.get(f"/api/diagnofast/intakes/{intake_id}/graph").json()
    assert view["source"] == "sqlite"
    assert view["evidence"][1]["answers"][0]["answer"] == "No cough"


def test_with_neo4j_off_the_evidence_still_comes_from_sqlite(doctor, client, patient, monkeypatch):
    intake_id = finished_interview(doctor, client, monkeypatch, patient["id"])
    view = doctor.get(f"/api/diagnofast/intakes/{intake_id}/graph").json()
    assert view["source"] == "sqlite" and len(view["evidence"]) == 2


def test_the_history_graph_lists_the_patients_visits_with_words_from_sqlite(doctor, client, patient, fake_graph, monkeypatch):
    first = finished_interview(doctor, client, monkeypatch, patient["id"])
    second = finished_interview(doctor, client, monkeypatch, patient["id"])
    graph_sync.run_once()
    view = doctor.get(f"/api/diagnofast/intakes/{second}/graph").json()
    visits = {item["intake_id"]: item for item in view["history"]}
    assert set(visits) == {first, second}
    assert visits[first]["chief_complaint"] == "Fever for three days"
    assert visits[first]["medicines"] == ["Metformin 500 mg twice a day"]
    assert visits[first]["allergies"] == ["Penicillin"]


def test_a_stranger_cannot_open_the_graph(doctor, person, client, patient, fake_graph, monkeypatch):
    intake_id = finished_interview(doctor, client, monkeypatch, patient["id"])
    stranger = person("doctor", "Zed", "Stranger")
    assert stranger.get(f"/api/diagnofast/intakes/{intake_id}/graph").status_code in (403, 404)


def test_a_graph_entry_for_another_patient_is_never_shown(doctor, client, patient, fake_graph, monkeypatch):
    intake_id = finished_interview(doctor, client, monkeypatch, patient["id"])
    graph_sync.run_once()
    # A corrupted or stale projection claims a visit that SQLite says belongs to nobody here.
    fake_graph.visits["intake:999999"] = {**fake_graph.visits[f"intake:{intake_id}"], "visit_ref": "intake:999999"}
    view = doctor.get(f"/api/diagnofast/intakes/{intake_id}/graph").json()
    assert 999999 not in {item["intake_id"] for item in view["history"]}


def test_the_rebuild_command_clears_and_requeues(doctor, client, patient, fake_graph, monkeypatch):
    from backend.operator_cli import main as operator

    intake_id = finished_interview(doctor, client, monkeypatch, patient["id"])
    graph_sync.run_once()
    assert operator(["graph-rebuild"]) == 0
    assert "clear" in fake_graph.calls
    assert queued(intake_id)["state"] == "queued"
