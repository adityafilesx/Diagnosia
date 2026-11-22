"""Stretch B: possible medicine and allergy conflicts across doctors, for staff only (conflicts.medicine_checks, off).

Only finished, confirmed records count: doctor-reviewed DiagnoFast reports, prescriptions the patient
ticked and saved, and active allergy records. Never drafts, unreviewed reports or transcripts. Flags say
"Possible conflict: check" and never advise. Salt-level matching needs a licensed drug database, so it
is reported as unavailable rather than guessed.
"""
import json
import uuid

import pytest

from backend.config import settings
from backend.db import connect
from backend.diagnofast import graph_sync
from backend.integrations import graph
from backend.tests.fake_graph import FakeGraph
from backend.tests.test_opd_bookings import switch

ADVICE_WORDS = ("generic", "substitute", "instead", "switch to", "stop taking", "replace", "alternative", "cheaper")


@pytest.fixture
def checks_on(client):
    switch("conflicts.medicine_checks")


def url(patient):
    return f"/api/conflicts/patients/{patient['id']}"


def visit(doctor_id, patient_id, medicines=(), allergies=(), reviewed=True, status="done"):
    db = connect()
    db.execute(
        """INSERT INTO intakes (token_hash, doctor_id, form_id, patient_name, patient_id, status, report, reviewed_at, reviewed_by, created_at)
           VALUES (?, ?, 'general_physician', 'Made Up', ?, ?, ?, ?, ?, '2026-11-20 09:00:00')""",
        (uuid.uuid4().hex, doctor_id, patient_id, status,
         json.dumps({"chief_complaint": "Check-up", "current_medicines": list(medicines), "allergies": list(allergies)}),
         "2026-11-20 10:00:00" if reviewed else None, doctor_id if reviewed else None),
    )
    db.commit()
    intake_id = db.execute("SELECT max(id) FROM intakes").fetchone()[0]
    db.close()
    return intake_id


def saved_prescription(patient_id, user_id, *names):
    db = connect()
    medicines = [{"name": {"value": name, "legibility": "clear"}, "dose": {"value": "", "legibility": "clear"},
                  "frequency": {"value": "", "legibility": "clear"}, "duration": {"value": "", "legibility": "clear"},
                  "notes": {"value": "", "legibility": "clear"}, "contains": "Metformin (500mg)"} for name in names]
    db.execute("INSERT INTO saved_prescriptions (id, patient_id, medicines, saved_by, created_at) VALUES (?, ?, ?, ?, '2026-11-21T08:00:00+00:00')",
               (uuid.uuid4().hex, patient_id, json.dumps(medicines), user_id))
    db.commit()
    db.close()


def allergy(patient_id, user_id, substance, status="active"):
    db = connect()
    db.execute("INSERT INTO allergies (id, patient_id, substance, status, source_type, recorded_by, created_at) VALUES (?, ?, ?, ?, 'clinician', ?, '2026-11-01')",
               (uuid.uuid4().hex, patient_id, substance, status, user_id))
    db.commit()
    db.close()


def test_off_until_switched_on(doctor, patient):
    assert doctor.get(url(patient)).status_code == 403


def test_the_same_medicine_from_two_doctors_is_a_possible_duplicate(doctor, person, patient, checks_on):
    other = person("doctor", "Kiran", "Rao")
    visit(doctor.id, patient["id"], medicines=["Metformin 500 mg twice a day"])
    visit(other.id, patient["id"], medicines=["metformin 1 g at night"])
    found = doctor.get(url(patient)).json()
    [flag] = [item for item in found["flags"] if item["kind"] == "possible_duplicate"]
    assert flag["message"].startswith("Possible conflict: check.")
    assert {entry["text"] for entry in flag["records"]} == {"Metformin 500 mg twice a day", "metformin 1 g at night"}
    assert {entry["doctor"] for entry in flag["records"]} == {"Meera Iyer", "Kiran Rao"}


def test_a_recorded_allergy_matching_a_medicine_is_flagged(doctor, patient, checks_on):
    allergy(patient["id"], doctor.id, "Penicillin")
    visit(doctor.id, patient["id"], medicines=["Penicillin V 250 mg"])
    found = doctor.get(url(patient)).json()
    [flag] = [item for item in found["flags"] if item["kind"] == "allergy_conflict"]
    assert "Penicillin" in flag["message"] and flag["message"].startswith("Possible conflict: check.")


def test_unreviewed_reports_drafts_and_refuted_allergies_do_not_count(doctor, person, patient, checks_on):
    other = person("doctor", "Kiran", "Rao")
    visit(doctor.id, patient["id"], medicines=["Metformin 500 mg"])
    visit(other.id, patient["id"], medicines=["Metformin 500 mg"], reviewed=False)
    visit(other.id, patient["id"], medicines=["Metformin 500 mg"], status="preparing_report", reviewed=False)
    allergy(patient["id"], doctor.id, "Metformin", status="refuted")
    assert doctor.get(url(patient)).json()["flags"] == []


def test_a_patients_saved_prescription_counts_but_its_ingredient_list_is_never_used(doctor, patient, checks_on):
    saved_prescription(patient["id"], doctor.id, "Glycomet 500")
    visit(doctor.id, patient["id"], medicines=["Metformin 500 mg"])
    found = doctor.get(url(patient)).json()
    # Glycomet contains metformin, but that is salt-level matching, which needs a licensed drug database.
    assert found["flags"] == []
    assert found["salt_check"]["available"] is False
    assert "licensed drug database" in found["salt_check"]["reason"]


def test_never_advice_and_never_a_substitute(doctor, person, patient, checks_on):
    other = person("doctor", "Kiran", "Rao")
    allergy(patient["id"], doctor.id, "Penicillin")
    visit(doctor.id, patient["id"], medicines=["Penicillin V 250 mg", "Metformin 500 mg"])
    visit(other.id, patient["id"], medicines=["Metformin 1 g"])
    text = json.dumps(doctor.get(url(patient)).json()).lower()
    for word in ADVICE_WORDS:
        assert word not in text.replace("not available without a licensed", ""), word


def test_patients_and_strangers_see_nothing(doctor, person, patient, checks_on):
    stranger = person("doctor", "Zed", "Stranger")
    assert stranger.get(url(patient)).status_code in (403, 404)
    patient_account = person("patient", "Ravi", "Kumar")
    assert patient_account.get(url(patient)).status_code == 403


def test_with_neo4j_the_visits_come_from_the_graph_and_words_from_sqlite(doctor, person, patient, checks_on, monkeypatch):
    fake = FakeGraph()
    graph.use(fake)
    try:
        monkeypatch.setattr(settings, "neo4j_uri", "neo4j://127.0.0.1:7687")
        switch("neo4j.enabled")
        other = person("doctor", "Kiran", "Rao")
        first = visit(doctor.id, patient["id"], medicines=["Metformin 500 mg"])
        second = visit(other.id, patient["id"], medicines=["Metformin 1 g"])
        db = connect()
        for intake_id in (first, second):
            graph_sync.enqueue(db, "intake", intake_id)
        db.commit()
        db.close()
        graph_sync.run_once()
        found = doctor.get(url(patient)).json()
        assert found["source"] == "neo4j"
        assert [flag["kind"] for flag in found["flags"]] == ["possible_duplicate"]
        fake.down = True
        assert doctor.get(url(patient)).json()["source"] == "sqlite"
    finally:
        graph.use(None)
