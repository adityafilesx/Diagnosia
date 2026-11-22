"""The consent words name Sarvam AI, carry a new version, and can be read aloud (BUILD.md step 3)."""
import base64
import re

from backend import ratelimit, speech
from backend.config import WEB_DIR
from backend.records import consent
from backend.tests.test_consent import _patient_link
from backend.tests.test_diagnofast import create_intake, doctor_session, services  # noqa: F401
from backend.tests.test_diagnofast_kiosk import configure_kiosk


def test_the_interview_words_name_sarvam_in_both_languages_without_claiming_india():
    english = " ".join(consent.WORDS[consent.INTERVIEW]["en-IN"])
    hindi = " ".join(consent.WORDS[consent.INTERVIEW]["hi-IN"])
    assert "Sarvam AI" in english and "Sarvam AI" in hindi
    assert "India" not in english and "भारत" not in hindi  # where Sarvam keeps data is unconfirmed


def test_the_version_changed_with_the_words():
    assert consent.VERSION == "2026-11-21"
    prescription_page = (WEB_DIR / "js" / "care" / "prescription.js").read_text(encoding="utf-8")
    assert re.search(rf"CONSENT_VERSION = '{consent.VERSION}'", prescription_page)


def test_the_new_hindi_line_is_marked_for_a_hindi_speaker():
    pending = consent.NEEDS_HINDI_APPROVAL
    assert (consent.INTERVIEW, 1) in pending
    assert "WI-101" in pending[(consent.INTERVIEW, 1)]


def test_a_patient_can_hear_the_consent_words(client, details, services, monkeypatch):
    spoken = []
    monkeypatch.setattr(speech, "question_audio", lambda text, language: spoken.append((text, language)) or (b"mp3", "audio/mpeg"))
    _, token = _patient_link(client, details)
    response = client.post(f"/api/diagnofast/patient/{token}/consent-audio", json={"language": "hi-IN", "kind": "interview"})
    assert response.status_code == 200
    assert response.json()["audio"] == "data:audio/mpeg;base64," + base64.b64encode(b"mp3").decode()
    text, language = spoken[0]
    assert language == "hi-IN"
    assert all(line in text for line in consent.WORDS[consent.INTERVIEW]["hi-IN"])


def test_with_no_voice_the_page_falls_back_to_the_browser(client, details, services, monkeypatch):
    monkeypatch.setattr(speech, "question_audio", lambda text, language: None)
    _, token = _patient_link(client, details)
    response = client.post(f"/api/diagnofast/patient/{token}/consent-audio", json={"language": "en-IN", "kind": "interview"})
    assert response.status_code == 200 and response.json() == {"audio": None}


def test_the_abha_question_is_read_only_when_the_link_has_an_abha_number(client, details, services, monkeypatch):
    monkeypatch.setattr(speech, "question_audio", lambda text, language: (b"a", "audio/mpeg"))
    doctor_session(client, details)
    _, plain = create_intake(client)
    _, with_abha = create_intake(client, abha_id="91-1234-5678-9012")
    client.cookies.clear()
    token = plain
    assert client.post(f"/api/diagnofast/patient/{token}/consent-audio", json={"language": "en-IN", "kind": "abha"}).status_code == 404
    token = with_abha
    assert client.post(f"/api/diagnofast/patient/{token}/consent-audio", json={"language": "en-IN", "kind": "abha"}).status_code == 200


def test_a_made_up_link_hears_nothing(client, monkeypatch):
    monkeypatch.setattr(speech, "question_audio", lambda text, language: (b"a", "audio/mpeg"))
    assert client.post("/api/diagnofast/patient/not-a-real-token/consent-audio", json={"language": "en-IN", "kind": "interview"}).status_code == 404


def test_the_kiosk_can_read_the_consent_words(client, doctor, monkeypatch):
    configure_kiosk(doctor, monkeypatch)
    client.cookies.clear()
    monkeypatch.setattr(speech, "question_audio", lambda text, language: (b"a", "audio/mpeg"))
    response = client.post("/api/diagnofast/kiosk/consent-audio", json={"language": "en-IN"})
    assert response.status_code == 200 and response.json()["audio"]


def test_reading_aloud_is_rate_limited_per_link(client, details, services, monkeypatch):
    monkeypatch.setattr(speech, "question_audio", lambda text, language: None)
    monkeypatch.setitem(ratelimit.RULES, ratelimit.CONSENT_AUDIO, ratelimit.Rule(ratelimit.CONSENT_AUDIO, 2, 3600, "busy"))
    _, token = _patient_link(client, details)
    codes = [client.post(f"/api/diagnofast/patient/{token}/consent-audio", json={"language": "en-IN", "kind": "interview"}).status_code for _ in range(3)]
    assert codes == [200, 200, 429]


def test_the_intake_page_has_a_read_aloud_button_and_no_inline_handlers():
    page = (WEB_DIR / "intake.html").read_text(encoding="utf-8")
    assert 'id="intake-consent-listen"' in page
    assert "onclick=" not in page
