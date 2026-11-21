"""Stretch A: the ReferralLoop network view (Neo4j), staff only, behind referrals.network_view (off).

Neo4j gets IDs and coded terms only. SQLite decides which referrals a person may see, and every word
shown is read again from SQLite. With Neo4j off or down, the same view is built from SQLite.
"""
import json
from datetime import date, timedelta

import pytest

from backend.config import settings
from backend.db import connect
from backend.diagnofast import graph_sync
from backend.integrations import graph
from backend.tests.conftest import grant
from backend.tests.fake_graph import FakeGraph
from backend.tests.test_opd_bookings import switch
from backend.tests.test_referralloop import BASE, clinic, send  # noqa: F401

NETWORK = f"{BASE}/network"


@pytest.fixture
def network_on(client):
    switch("referrals.network_view")


@pytest.fixture
def fake_graph(client, monkeypatch):
    fake = FakeGraph()
    graph.use(fake)
    monkeypatch.setattr(settings, "neo4j_uri", "neo4j://127.0.0.1:7687")
    switch("neo4j.enabled")
    yield fake
    graph.use(None)


def referrals(doctor, patient, clinic, count=2, **fields):
    grant(doctor, patient["id"], "referral_sharing")
    made = []
    for index in range(count):
        extra = {"confirm_duplicate_reason": "A second, separate question"} if index else {}
        response = send(doctor, patient, clinic, **fields, **extra)
        assert response.status_code == 201, response.text
        made.append(response.json())
    return made


def overdue(referral_id):
    db = connect()
    db.execute("UPDATE referrals SET respond_by = ? WHERE id = ?", ((date.today() - timedelta(days=3)).isoformat(), referral_id))
    db.commit()
    db.close()


def test_off_until_switched_on(doctor):
    assert doctor.get(NETWORK).status_code == 403


def test_without_neo4j_the_view_comes_from_sqlite(doctor, patient, clinic, network_on):
    made = referrals(doctor, patient, clinic)
    overdue(made[0]["id"])
    view = doctor.get(NETWORK).json()
    assert view["source"] == "sqlite"
    [edge] = view["paths"]
    assert edge["from"]["name"] == "Meera Iyer"
    assert edge["to"]["name"] == "Lakeview Cardiology"
    assert edge["specialty"] == "Cardiology"
    assert (edge["referrals"], edge["open"], edge["overdue"]) == (2, 2, 1)
    assert view["load"] == [{"destination": edge["to"], "open": 2, "overdue": 1}]
    assert view["overdue"][0]["referral_id"] == made[0]["id"]


def test_status_changes_are_queued_with_the_change_and_copied_as_codes(doctor, patient, clinic, network_on, fake_graph):
    made = referrals(doctor, patient, clinic, count=1)
    db = connect()
    state = db.execute("SELECT state FROM graph_items WHERE source_type = 'referral' AND source_id = ?", (made[0]["id"],)).fetchone()
    db.close()
    assert state["state"] == "queued"
    assert graph_sync.run_once() == 1
    copied = fake_graph.referrals[f"referral:{made[0]['id']}"]
    assert copied["from_ref"] == f"doctor:{doctor.id}"
    assert copied["to_ref"].startswith("org:")
    assert copied["specialty"] == "cardiology"
    text = json.dumps(copied)
    for free_text in ("palpitations", "Intermittent", "Ravi", "Lakeview"):
        assert free_text not in text


def test_with_neo4j_the_same_view_comes_from_the_graph(doctor, patient, clinic, network_on, fake_graph):
    made = referrals(doctor, patient, clinic)
    overdue(made[1]["id"])
    graph_sync.run_once()
    db = connect()
    graph_sync.enqueue(db, "referral", made[1]["id"])  # the overdue date changed, so it is copied again
    db.commit()
    db.close()
    db = connect()
    db.execute("UPDATE graph_items SET next_attempt_at = '2000-01-01T00:00:00+00:00'")
    db.commit()
    db.close()
    graph_sync.run_once()
    from_graph = doctor.get(NETWORK).json()
    assert from_graph["source"] == "neo4j"
    graph.use(None)
    switch("neo4j.enabled", False)
    from_sqlite = doctor.get(NETWORK).json()
    for key in ("paths", "load", "overdue"):
        assert from_graph[key] == from_sqlite[key]


def test_neo4j_down_falls_back_to_sqlite(doctor, patient, clinic, network_on, fake_graph):
    referrals(doctor, patient, clinic)
    graph_sync.run_once()
    fake_graph.down = True
    assert doctor.get(NETWORK).json()["source"] == "sqlite"


def test_the_receiving_service_sees_its_load_and_strangers_see_nothing(doctor, person, patient, clinic, network_on):
    referrals(doctor, patient, clinic)
    assert clinic.get(NETWORK).json()["load"][0]["open"] == 2
    stranger = person("doctor", "Zed", "Stranger")
    assert stranger.get(NETWORK).json() == {"source": "sqlite", "paths": [], "load": [], "overdue": []}


def test_a_graph_entry_outside_my_referrals_is_never_shown(doctor, person, patient, clinic, network_on, fake_graph):
    referrals(doctor, patient, clinic)
    graph_sync.run_once()
    fake_graph.referrals["referral:someone-else"] = {
        "ref": "referral:someone-else", "from_ref": "doctor:999", "to_ref": "doctor:998", "specialty": "neurology",
        "priority": "urgent", "status": "sent", "open": True, "respond_by": "2000-01-01", "day": "2026-11-01",
    }
    view = doctor.get(NETWORK).json()
    assert all(edge["specialty"] != "neurology" for edge in view["paths"])


def test_patients_cannot_open_the_network(person, network_on):
    patient_account = person("patient", "Asha", "Verma")
    assert patient_account.get(NETWORK).status_code == 403
