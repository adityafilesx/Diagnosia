"""Every host the server can call is named in the data-protection document (audit plan WI-106)."""
import re

import pytest

from backend import llm, speech
from backend.config import ROOT_DIR, neural_tts_allowed, settings

BROWSER_ONLY = {"calendar.google.com", "assets.website-files.com"}  # opened by the visitor's browser


def hosts_in_code():
    found = set()
    for path in (ROOT_DIR / "backend").rglob("*.py"):
        if "tests" in path.parts:
            continue
        # Only https: the http addresses in the code are code-system names (LOINC, HL7), never called.
        found |= set(re.findall(r"https://([a-z0-9.-]+)", path.read_text(encoding="utf-8")))
    return found


def test_every_host_the_code_names_is_in_the_egress_table():
    document = (ROOT_DIR / "docs" / "DATA_PROTECTION_AND_RETENTION.md").read_text(encoding="utf-8")
    for host in hosts_in_code() - BROWSER_ONLY:
        assert f"`{host}`" in document, host
    for host in BROWSER_ONLY:
        assert host in document
    assert "`speech.platform.bing.com`" in document  # inside the edge-tts library, so not found above


def test_edge_voices_run_only_in_demo_mode(monkeypatch):
    monkeypatch.setattr(settings, "neural_tts_enabled", True)
    monkeypatch.setattr(settings, "demo_mode", True)
    assert neural_tts_allowed()
    monkeypatch.setattr(settings, "demo_mode", False)
    assert not neural_tts_allowed()
    with pytest.raises(speech.SpeechUnavailable):
        speech.speak_neural("How long have you had the fever?", "en-IN")
    monkeypatch.setattr(settings, "demo_mode", True)
    monkeypatch.setattr(settings, "allow_real_patient_data", True)
    assert not neural_tts_allowed()


def test_without_edge_a_hindi_question_is_left_to_the_browser_voice(client, details, monkeypatch):
    from backend.tests.test_diagnofast import create_intake, doctor_session, start

    monkeypatch.setattr(settings, "demo_mode", False)
    monkeypatch.setattr(speech, "speak_neural", lambda *args: pytest.fail("Edge must not be called"))
    doctor_session(client, details)
    _, token = create_intake(client)
    client.cookies.clear()
    assert start(client, token).json()["audio"] is None  # Hindi: the page reads it in the browser's voice


def test_patient_text_goes_to_no_unnamed_ai_host(monkeypatch):
    monkeypatch.setattr(settings, "ai_base_url", "https://ai.example.net/v1")
    with pytest.raises(llm.AINotConfigured):
        llm._post({}, "key", 5)
    with pytest.raises(speech.SpeechUnavailable):
        speech._post("/audio/speech", json={})
