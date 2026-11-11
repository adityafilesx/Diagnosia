"""The synthetic account seeder makes working logins and stays out of real deployments."""
import csv

import pytest

from backend.config import settings
from backend.synthetic import seed_accounts


@pytest.fixture
def seeded(client, tmp_path, monkeypatch):
    monkeypatch.setattr(seed_accounts, "OUTPUT_DIR", tmp_path / "synthetic")
    assert seed_accounts.run(patients=12, with_login=6, seed=7) == 0
    with open(tmp_path / "synthetic" / "accounts.csv", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def test_it_makes_doctors_and_patients_that_can_sign_in(client, seeded):
    roles = [row["role"] for row in seeded]
    assert roles.count("doctor") == 14 and roles.count("patient") == 6
    for email in ("doctor01@example.com", "patient001@example.com"):
        response = client.post("/api/auth/login", json={"email": email, "password": seed_accounts.PASSWORD})
        assert response.status_code == 200
    assert client.get("/api/patients").status_code == 200


def test_one_doctor_stays_pending_and_the_rest_are_verified(client, seeded):
    client.post("/api/auth/login", json={"email": "pending.doctor@example.com", "password": seed_accounts.PASSWORD})
    assert client.get("/api/me").json()["account_status"] == "pending_verification"
    client.post("/api/auth/logout")
    client.post("/api/auth/login", json={"email": "doctor03@example.com", "password": seed_accounts.PASSWORD})
    assert client.get("/api/me").json()["account_status"] == "verified"


def test_a_patient_sees_the_chart_a_doctor_made(client, seeded):
    client.post("/api/auth/login", json={"email": "patient001@example.com", "password": seed_accounts.PASSWORD})
    charts = client.get("/api/patients").json()
    assert len(charts) == 1


def test_the_same_seed_makes_the_same_people(client, tmp_path, monkeypatch):
    first = seed_accounts._patient_rows(__import__("random").Random(5), 10, 5)
    second = seed_accounts._patient_rows(__import__("random").Random(5), 10, 5)
    assert first == second


def test_it_refuses_to_run_with_real_patient_data(client, monkeypatch):
    monkeypatch.setattr(settings, "allow_real_patient_data", True)
    assert seed_accounts.run(patients=1, with_login=1, seed=1) == 1
