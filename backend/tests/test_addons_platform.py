"""The switches, keys and gates for the hackathon add-ons: Sarvam, Neo4j and the new DiagnoFast parts.

Every add-on starts off, and Sarvam and Neo4j stop completely when real patient data is allowed.
"""
from pathlib import Path

import pytest

from backend import addons, safety, settings_store
from backend.config import settings
from backend.db import connect
from backend.operator_cli import main as operator
from backend.tests.conftest import verified_organization

ROOT = Path(__file__).parents[2]
NEW_SWITCHES = (
    "sarvam.enabled",
    "neo4j.enabled",
    "diagnofast.graph_followups",
    "diagnofast.doctor_like_interview",
    "diagnofast.bookings",
    "diagnofast.slot_login",
    "diagnofast.walkin_suggestion",
    "diagnofast.review_feedback",
)


@pytest.fixture
def db(client):
    connection = connect()
    yield connection
    connection.close()


def switch_on(db, *keys):
    for key in keys:
        db.execute("INSERT OR REPLACE INTO platform_settings (key, value, updated_by, updated_at) VALUES (?, 'true', 1, '')", (key,))
    db.commit()


def sign(item="sarvam_terms"):
    return operator(["signoff", "--item", item, "--signed-by", "Synthetic", "--role", "Account owner",
                     "--document-reference", "DOC-1", "--operator", "tester"])


@pytest.mark.parametrize("key", NEW_SWITCHES)
def test_every_new_switch_exists_and_starts_off(db, key):
    assert settings_store.SETTINGS[key]["type"] == "bool"
    assert settings_store.get(key, db) is False


def test_sarvam_host_is_allowed_and_nothing_else_new():
    assert "api.sarvam.ai" in settings.allowed_ai_hosts


def test_sarvam_needs_switch_key_and_signoff(db, monkeypatch):
    monkeypatch.setattr(settings, "sarvam_api_key", "sk_test_key_123")
    assert addons.sarvam_ready(db) is False  # switch off
    switch_on(db, "sarvam.enabled")
    assert addons.sarvam_ready(db) is False  # no sign-off yet
    assert sign() == 0
    assert addons.sarvam_ready(db) is True
    monkeypatch.setattr(settings, "sarvam_api_key", "")
    assert addons.sarvam_ready(db) is False  # no key


def test_sarvam_and_neo4j_stop_when_real_data_is_allowed(db, monkeypatch):
    monkeypatch.setattr(settings, "sarvam_api_key", "sk_test_key_123")
    monkeypatch.setattr(settings, "neo4j_uri", "neo4j://127.0.0.1:7687")
    switch_on(db, "sarvam.enabled", "neo4j.enabled")
    sign()
    assert addons.sarvam_ready(db) and addons.neo4j_ready(db)
    monkeypatch.setattr(settings, "allow_real_patient_data", True)
    assert addons.sarvam_ready(db) is False
    assert addons.neo4j_ready(db) is False


def test_neo4j_needs_switch_and_address(db, monkeypatch):
    monkeypatch.setattr(settings, "neo4j_uri", "")
    switch_on(db, "neo4j.enabled")
    assert addons.neo4j_ready(db) is False
    monkeypatch.setattr(settings, "neo4j_uri", "neo4j://127.0.0.1:7687")
    assert addons.neo4j_ready(db) is True


def test_the_sarvam_signoff_is_a_feature_gate_not_a_real_data_requirement(db):
    assert "sarvam_terms" in safety.FEATURE_SIGNOFFS
    assert "sarvam_terms" not in safety.REQUIRED_SIGNOFFS
    assert sign() == 0
    assert safety.signed_off(db, "sarvam_terms")
    assert operator(["revoke-signoff", "--item", "sarvam_terms", "--operator", "tester"]) == 0
    assert not safety.signed_off(db, "sarvam_terms")


def test_sarvam_key_and_neo4j_password_can_be_saved_in_settings(person, db):
    staff = person("doctor", "Anil", "Shah")
    verified_organization(staff)
    for provider in ("sarvam", "neo4j"):
        response = staff.put(f"/api/platform/ai-key?provider={provider}", json={"key": "secret-value-1234"})
        assert response.status_code == 200, response.text
        assert settings_store.api_key(db, provider) == "secret-value-1234"
    listed = staff.get("/api/platform/settings").json()["ai_keys"]
    assert listed["sarvam"]["configured"] and listed["neo4j"]["configured"]
    assert "secret-value" not in str(listed)


def test_dependencies_are_declared_where_the_plan_says():
    assert "segno" in (ROOT / "backend/requirements.txt").read_text(encoding="utf-8")
    assert "segno==" in (ROOT / "backend/requirements.lock").read_text(encoding="utf-8")
    assert "neo4j" in (ROOT / "backend/requirements-integrations.txt").read_text(encoding="utf-8")
    assert "neo4j" not in (ROOT / "backend/requirements.txt").read_text(encoding="utf-8")


def test_docker_compose_runs_neo4j_on_this_machine_only():
    compose = (ROOT / "docker-compose.integrations.yml").read_text(encoding="utf-8")
    assert "neo4j:5.26-community" in compose
    assert "127.0.0.1:7687:7687" in compose
