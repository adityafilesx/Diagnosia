"""The synthetic seed runs where judge mode runs: outside development, behind HTTPS-only cookies."""
import pytest

from backend import judge
from backend.config import settings
from backend.db import connect
from backend.synthetic import seed_accounts


@pytest.fixture
def deployed(client, monkeypatch):
    monkeypatch.setattr(settings, "environment", "production")
    monkeypatch.setattr(settings, "cookie_secure", True)  # DIAGNOSIA_HTTPS=1
    monkeypatch.setattr(settings, "demo_mode", True)
    monkeypatch.setattr(settings, "demo_outside_development", True)
    monkeypatch.setattr(settings, "allow_real_patient_data", False)
    return client


def test_outside_development_without_judge_mode_seeding_refuses(deployed):
    assert seed_accounts.run(patients=8, with_login=8, seed=2026) == 1


def test_with_real_patient_data_seeding_refuses_even_in_judge_mode(deployed, monkeypatch):
    monkeypatch.setattr(settings, "judge_mode", True)
    monkeypatch.setattr(settings, "allow_real_patient_data", True)
    assert seed_accounts.run(patients=8, with_login=8, seed=2026) == 1


def test_judge_mode_seeds_behind_https_only_cookies_with_the_demo_accounts(deployed, monkeypatch):
    monkeypatch.setattr(settings, "judge_mode", True)
    assert seed_accounts.run(patients=8, with_login=8, seed=2026) == 0
    db = connect()
    doctor = db.execute("SELECT * FROM users WHERE email = ?", (judge.DOCTOR_EMAIL,)).fetchone()
    assert doctor["account_status"] == "verified"
    assert judge.demo_account(db, judge.PATIENT_EMAIL) is not None
    chart = db.execute(
        "SELECT patients.id FROM patients JOIN users ON users.id = patients.user_id WHERE users.email = ?", (judge.PATIENT_EMAIL,)
    ).fetchone()
    on_team = db.execute(
        "SELECT 1 FROM care_team WHERE patient_id = ? AND user_id = ? AND role = 'clinician' AND revoked_at IS NULL",
        (chart["id"], doctor["id"]),
    ).fetchone()
    admin = db.execute(
        "SELECT 1 FROM organization_members WHERE user_id = ? AND role = 'admin'", (doctor["id"],)
    ).fetchone()
    db.close()
    assert on_team is not None  # the demo doctor can open the demo patient's chart
    assert admin is None  # and is not the administrator


def test_seeding_twice_adds_nothing(deployed, monkeypatch):
    monkeypatch.setattr(settings, "judge_mode", True)
    assert seed_accounts.run(patients=8, with_login=8, seed=2026) == 0
    db = connect()
    before = db.execute("SELECT COUNT(*) FROM patients").fetchone()[0]
    db.close()
    assert seed_accounts.run(patients=8, with_login=8, seed=2026) == 0
    db = connect()
    after = db.execute("SELECT COUNT(*) FROM patients").fetchone()[0]
    db.close()
    assert before == after == 8
