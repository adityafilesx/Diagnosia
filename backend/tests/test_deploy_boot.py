"""What a judge-mode host does on every boot: its disk starts empty each time (Render's free tier)."""
import json

import pytest
from fastapi.testclient import TestClient

from backend import deploy_boot, judge, safety, settings_store
from backend.app import app
from backend.config import settings
from backend.db import connect
from backend.private_files import is_private
from backend.records import vault


@pytest.fixture
def host(client, monkeypatch):
    monkeypatch.setattr(settings, "environment", "production")
    monkeypatch.setattr(settings, "cookie_secure", True)
    monkeypatch.setattr(settings, "demo_mode", True)
    monkeypatch.setattr(settings, "demo_outside_development", True)
    monkeypatch.setattr(settings, "allow_real_patient_data", False)
    monkeypatch.setattr(settings, "judge_mode", True)
    monkeypatch.delenv(deploy_boot.SIGNED_OFF_BY, raising=False)
    monkeypatch.delenv(deploy_boot.KEY_SOURCE, raising=False)
    return client


def _boot():
    return deploy_boot.main(patients=8, with_login=8)


def _signoffs():
    db = connect()
    rows = db.execute("SELECT * FROM governance_signoffs WHERE item = 'sarvam_terms' AND revoked_at IS NULL").fetchall()
    db.close()
    return rows


@pytest.mark.parametrize("build", [False, True])
def test_with_judge_mode_off_the_deploy_succeeds_with_no_demo_data(host, monkeypatch, build):
    # A failed deploy would leave the previous one, with judge mode on, running. So turning judge mode
    # off must deploy cleanly: an empty database, nobody to sign in as, the demo door closed.
    monkeypatch.setattr(settings, "judge_mode", False)
    monkeypatch.setenv(deploy_boot.SIGNED_OFF_BY, "Someone")
    assert deploy_boot.main(patients=8, with_login=8, build=build) == 0
    db = connect()
    assert db.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0
    assert db.execute("SELECT COUNT(*) FROM governance_signoffs").fetchone()[0] == 0
    db.close()
    assert TestClient(app).get("/demo/open?tool=diagnofast", follow_redirects=False).status_code == 404


def test_first_boot_seeds_and_turns_the_demo_settings_on(host):
    assert _boot() == 0
    db = connect()
    assert judge.demo_account(db, judge.DOCTOR_EMAIL) is not None
    assert settings_store.enabled_tools(db) == list(settings_store.TOOLS)
    assert settings_store.get("sarvam.enabled", db) is True
    db.close()


def test_without_the_named_person_sarvam_is_switched_on_but_not_signed_off(host):
    assert _boot() == 0
    assert _signoffs() == []
    from backend import addons

    db = connect()
    assert addons.sarvam_ready(db) is False  # the sign-off is a person's decision, never assumed
    db.close()


def test_the_named_person_signs_sarvam_off_once(host, monkeypatch):
    monkeypatch.setenv(deploy_boot.SIGNED_OFF_BY, "Aditya (project owner)")
    assert _boot() == 0
    assert _boot() == 0  # every boot, but one record
    rows = _signoffs()
    assert len(rows) == 1
    assert rows[0]["signed_by"] == "Aditya (project owner)"
    assert "zero data retention" in rows[0]["document_reference"]


def test_a_blank_name_signs_nothing(host, monkeypatch):
    monkeypatch.setenv(deploy_boot.SIGNED_OFF_BY, "   ")
    assert _boot() == 0
    assert _signoffs() == []


def test_boot_is_safe_to_repeat(host):
    assert _boot() == 0
    assert _boot() == 0
    db = connect()
    assert db.execute("SELECT COUNT(*) FROM patients").fetchone()[0] == 8
    db.close()
    safety.assert_safe_to_start(connect())


def test_the_key_ring_is_copied_somewhere_only_its_owner_can_read(host, monkeypatch, tmp_path_factory, key_file, expose):
    # Each in its own folder: a key ring may never sit beside the database or the documents.
    source = tmp_path_factory.mktemp("secrets") / "document-keys.json"
    source.write_text(key_file.read_text(encoding="utf-8"), encoding="utf-8")
    expose(source)  # a host's secret file may be readable by others
    target = tmp_path_factory.mktemp("home") / ".diagnosia" / "document-keys.json"
    monkeypatch.setenv(deploy_boot.KEY_SOURCE, str(source))
    monkeypatch.setattr(settings, "document_key_file", str(target))
    assert _boot() == 0
    assert is_private(target)
    assert json.loads(target.read_text(encoding="utf-8")) == json.loads(source.read_text(encoding="utf-8"))
    assert vault.status()[0]


def test_a_missing_key_source_stops_the_boot(host, monkeypatch, tmp_path):
    monkeypatch.setenv(deploy_boot.KEY_SOURCE, str(tmp_path / "nowhere.json"))
    assert _boot() == 1


def test_the_kiosk_sends_visits_to_the_demo_doctor_in_judge_mode(host):
    assert _boot() == 0
    db = connect()
    doctor_id = db.execute("SELECT id FROM users WHERE email = ?", (judge.DOCTOR_EMAIL,)).fetchone()["id"]
    db.close()
    with TestClient(app, base_url="https://testserver") as kiosk:
        assert kiosk.get("/api/diagnofast/kiosk").status_code == 200
        made = kiosk.post("/api/diagnofast/kiosk/intakes", json={
            "form_id": "general_physician", "patient_name": "Kiosk Visitor", "patient_age": 30, "patient_sex": "female",
            "consent": True,
        })
    assert made.status_code == 201, made.text
    db = connect()
    owner = db.execute("SELECT doctor_id FROM intakes ORDER BY id DESC LIMIT 1").fetchone()["doctor_id"]
    db.close()
    assert owner == doctor_id


def test_the_build_seeds_without_the_key_ring_and_the_boot_then_only_checks(host, monkeypatch, tmp_path):
    monkeypatch.setenv(deploy_boot.KEY_SOURCE, str(tmp_path / "not-in-the-build.json"))  # secret files: runtime only
    assert deploy_boot.main(patients=8, with_login=8, build=True) == 0
    db = connect()
    assert judge.demo_account(db, judge.DOCTOR_EMAIL) is not None
    db.close()
    assert _boot() == 1  # at boot the key ring must be there
