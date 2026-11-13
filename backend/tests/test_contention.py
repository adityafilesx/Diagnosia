"""A slow AI call never holds the database's write lock, and a lock that can't be had is a 503 (WI-261)."""
import sqlite3
import threading
import time

import pytest

from backend import db as db_module
from backend import llm
from backend.config import settings
from backend.tests.test_clinscribe import draft, encounter, fake_draft, ready_session  # noqa: F401  (encounter is a fixture)

SLOW_AI_SECONDS = 1.5
SHORT_BUSY_SECONDS = 0.3


@pytest.fixture
def short_busy_wait(monkeypatch):
    # A writer gives up after a short wait, so a lock held through a slow AI call shows up quickly.
    monkeypatch.setattr(settings, "db_busy_seconds", SHORT_BUSY_SECONDS)


def test_the_busy_wait_comes_from_settings(client, monkeypatch):
    monkeypatch.setattr(settings, "db_busy_seconds", 7)
    connection = db_module.connect()
    try:
        assert connection.execute("PRAGMA busy_timeout").fetchone()[0] == 7000
    finally:
        connection.close()


def test_other_writes_go_through_while_a_note_is_being_drafted(doctor, patient, encounter, person, short_busy_wait, monkeypatch):
    started = threading.Event()

    def slow_ai(*args, **options):
        started.set()
        time.sleep(SLOW_AI_SECONDS)
        return fake_draft()

    monkeypatch.setattr(llm, "ask", slow_ai)
    ready = ready_session(doctor, patient, encounter)
    result = {}
    drafting = threading.Thread(target=lambda: result.update(draft=draft(doctor, ready["id"]).status_code))
    drafting.start()
    assert started.wait(5)
    other = person("doctor")
    writes = [other.post("/api/patients", json={"first_name": f"Synthetic{n}", "last_name": "Writer"}).status_code for n in range(3)]
    drafting.join()
    assert writes == [201, 201, 201]
    assert result["draft"] == 201


def test_a_lock_that_cannot_be_had_is_a_plain_503(client, doctor, short_busy_wait):
    holder = sqlite3.connect(settings.db_path)
    holder.execute("BEGIN IMMEDIATE")  # someone else is writing and doesn't let go
    try:
        response = doctor.post("/api/patients", json={"first_name": "Synthetic", "last_name": "Blocked"})
    finally:
        holder.rollback()
        holder.close()
    assert response.status_code == 503
    assert response.json()["detail"] == "The system is busy. Please try again in a moment."


def test_the_load_test_runs_and_reports_against_the_threshold(monkeypatch):
    from backend import llm as llm_module
    from backend.synthetic import load_test

    monkeypatch.setattr(llm_module, "ask", llm_module.ask)  # the script swaps it; put it back afterwards
    for name in ("db_path", "documents_dir", "document_key_file"):
        monkeypatch.setattr(settings, name, getattr(settings, name))
    result = load_test.run(staff=3, drafters=1, seconds=1.5, ai_seconds=0.5)
    assert result["writes"] > 0 and result["error"] == 0
    assert result["drafts"] >= 1 and result["draft_errors"] == 0
    assert result["busy"] == 0
    assert set(result) >= {"p50_ms", "p95_ms", "move_to_postgresql"}
