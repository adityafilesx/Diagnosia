"""Sarvam in speech.py: Saaras v4 speech to text, Bulbul voice and Mayura translation, Hindi and English only.

No test reaches Sarvam. httpx.post is replaced, and each fake checks the request it was given.
"""
import base64
import logging

import httpx
import pytest

from backend import speech
from backend.config import settings

KEY = "sk_test_sarvam_key"


class FakeResponse:
    def __init__(self, status_code=200, body=None, content=b""):
        self.status_code = status_code
        self._body = body or {}
        self.content = content

    def json(self):
        return self._body


@pytest.fixture
def sarvam_on(monkeypatch):
    monkeypatch.setattr(settings, "sarvam_api_key", KEY)
    monkeypatch.setattr(speech, "sarvam_active", lambda: True)


@pytest.fixture
def calls(monkeypatch):
    seen = []

    def install(handler):
        def post(url, **options):
            seen.append((url, options))
            return handler(url, options)

        monkeypatch.setattr(speech.httpx, "post", post)
        return seen

    return install


def test_transcription_tries_saaras_first_with_the_mixed_language_mode(sarvam_on, calls):
    seen = calls(lambda url, options: FakeResponse(body={"request_id": "r1", "transcript": "मुझे fever है", "language_code": "hi-IN"}))
    assert speech.transcribe(b"audio", "audio/webm", "hi-IN") == "मुझे fever है"
    url, options = seen[0]
    assert url == "https://api.sarvam.ai/speech-to-text"
    assert options["headers"] == {"api-subscription-key": KEY}
    assert options["data"] == {"model": "saaras:v4", "mode": "codemix", "language_code": "hi-IN"}
    assert options["files"]["file"][0] == "audio.webm"


def test_saaras_is_never_asked_to_translate(sarvam_on, calls):
    seen = calls(lambda url, options: FakeResponse(body={"transcript": "I have a cough"}))
    for language in ("en-IN", "hi-IN"):
        speech.transcribe(b"audio", "audio/mp4", language)
    assert all(options["data"]["mode"] != "translate" for _url, options in seen)


def test_a_failed_saaras_call_falls_back_to_groq_whisper_with_its_no_speech_filter(sarvam_on, calls, monkeypatch):
    monkeypatch.setattr(settings, "groq_api_key", "gsk_test")

    def handler(url, options):
        if "sarvam" in url:
            return FakeResponse(503)
        return FakeResponse(body={"text": "x", "segments": [
            {"text": "I have a headache", "no_speech_prob": 0.1},
            {"text": "Thank you for watching", "no_speech_prob": 0.9},
        ]})

    seen = calls(handler)
    assert speech.transcribe(b"audio", "audio/webm", "en-IN") == "I have a headache"
    assert [url for url, _ in seen if "sarvam" in url]
    assert "groq.com" in seen[-1][0]


def test_with_sarvam_off_nothing_goes_to_sarvam(calls, monkeypatch):
    monkeypatch.setattr(settings, "groq_api_key", "gsk_test")
    monkeypatch.setattr(speech, "sarvam_active", lambda: False)
    seen = calls(lambda url, options: FakeResponse(body={"text": "hello"}))
    speech.transcribe(b"audio", "audio/webm", "en-IN")
    assert not [url for url, _ in seen if "sarvam" in url]


def test_sarvam_is_inactive_with_real_patient_data_allowed(client, monkeypatch):
    monkeypatch.setattr(settings, "sarvam_api_key", KEY)
    monkeypatch.setattr(settings, "allow_real_patient_data", True)
    assert speech.sarvam_active() is False


def test_sarvam_is_inactive_by_default(client):
    assert speech.sarvam_active() is False


def test_bulbul_reads_hindi_in_the_chosen_gentle_voice(sarvam_on, calls):
    mp3 = b"ID3-hindi"
    seen = calls(lambda url, options: FakeResponse(body={"request_id": "r", "audios": [base64.b64encode(mp3).decode()]}))
    assert speech.speak_sarvam("आपको कब से बुखार है?", "hi-IN") == mp3
    url, options = seen[0]
    assert url == "https://api.sarvam.ai/text-to-speech"
    assert options["json"] == {
        "text": "आपको कब से बुखार है?", "language_code": "hi-IN", "speaker": "aparna_hi_customer",
        "model": "bulbul:v4-flash", "output_audio_codec": "mp3", "pace": 0.9, "temperature": 0.4,
    }


def test_bulbul_uses_the_english_voice_for_english(sarvam_on, calls):
    seen = calls(lambda url, options: FakeResponse(body={"audios": [base64.b64encode(b"a").decode()]}))
    speech.speak_sarvam("How long have you had the fever?", "en-IN")
    assert seen[0][1]["json"]["speaker"] == "neha_en_customer"


def test_question_audio_order_is_sarvam_then_edge_then_groq_then_the_browser(sarvam_on, monkeypatch):
    order = []

    def fail(name):
        def call(text, language):
            order.append(name)
            raise speech.SpeechUnavailable(name)
        return call

    monkeypatch.setattr(speech, "speak_sarvam", fail("sarvam"))
    monkeypatch.setattr(speech, "speak_neural", fail("edge"))
    monkeypatch.setattr(speech, "speak", fail("groq"))
    monkeypatch.setattr(speech, "neural_tts_allowed", lambda: True)
    assert speech.question_audio("How are you?", "en-IN") is None
    assert order == ["sarvam", "edge", "groq"]
    order.clear()
    assert speech.question_audio("आप कैसे हैं?", "hi-IN") is None
    assert order == ["sarvam", "edge"]  # Groq has no Hindi voice, so the browser reads it


def test_question_audio_returns_sarvam_mp3_first(sarvam_on, monkeypatch):
    monkeypatch.setattr(speech, "speak_sarvam", lambda text, language: b"mp3")
    monkeypatch.setattr(speech, "speak_neural", lambda text, language: pytest.fail("Sarvam answered"))
    assert speech.question_audio("आप कैसे हैं?", "hi-IN") == (b"mp3", "audio/mpeg")


def test_question_audio_is_today_s_behaviour_with_sarvam_off(monkeypatch):
    monkeypatch.setattr(speech, "sarvam_active", lambda: False)
    monkeypatch.setattr(speech, "speak_sarvam", lambda text, language: pytest.fail("Sarvam is off"))
    monkeypatch.setattr(speech, "neural_tts_allowed", lambda: False)
    monkeypatch.setattr(speech, "speak", lambda text, language: b"wav")
    assert speech.question_audio("Hello", "en-IN") == (b"wav", "audio/wav")


def test_mayura_translates_confirmed_hindi_to_english(sarvam_on, calls):
    seen = calls(lambda url, options: FakeResponse(body={"translated_text": "I have had a fever for two days", "source_language_code": "hi-IN"}))
    assert speech.translate_to_english("मुझे दो दिन से बुखार है") == "I have had a fever for two days"
    url, options = seen[0]
    assert url == "https://api.sarvam.ai/translate"
    assert options["json"] == {
        "input": "मुझे दो दिन से बुखार है", "source_language_code": "auto", "target_language_code": "en-IN",
        "mode": "formal", "model": "mayura:v1",
    }


def test_long_answers_are_translated_in_pieces_under_mayuras_limit(sarvam_on, calls):
    seen = calls(lambda url, options: FakeResponse(body={"translated_text": f"part{len(options['json']['input'])}"}))
    sentence = "मुझे बुखार है और सिर में दर्द है। "
    text = sentence * 60  # about 2,000 characters
    result = speech.translate_to_english(text)
    assert len(seen) >= 2
    assert all(len(options["json"]["input"]) <= speech.MAYURA_MAX_CHARS for _url, options in seen)
    assert "".join(options["json"]["input"] for _url, options in seen).replace(" ", "") == text.replace(" ", "")
    assert result.startswith("part")


def test_translation_is_skipped_for_english_and_when_sarvam_is_off(calls, monkeypatch):
    seen = calls(lambda url, options: FakeResponse(body={"translated_text": "x"}))
    monkeypatch.setattr(speech, "sarvam_active", lambda: True)
    monkeypatch.setattr(settings, "sarvam_api_key", KEY)
    assert speech.translate_to_english("I have a cough since Monday") is None
    monkeypatch.setattr(speech, "sarvam_active", lambda: False)
    assert speech.translate_to_english("मुझे खांसी है") is None
    assert seen == []


def test_a_failed_translation_is_simply_missing(sarvam_on, calls):
    calls(lambda url, options: FakeResponse(500))
    assert speech.translate_to_english("मुझे खांसी है") is None


def test_sarvam_refuses_a_host_outside_the_allowed_list(sarvam_on, calls, monkeypatch):
    monkeypatch.setattr(settings, "sarvam_base_url", "https://evil.example.com")
    seen = calls(lambda url, options: FakeResponse(body={"transcript": "x"}))
    with pytest.raises(speech.SpeechUnavailable):
        speech.speak_sarvam("hello", "en-IN")
    assert seen == []


def test_nothing_about_the_patient_or_the_key_is_logged(sarvam_on, calls, caplog, monkeypatch):
    monkeypatch.setattr(settings, "groq_api_key", "")
    calls(lambda url, options: (_ for _ in ()).throw(httpx.ConnectError("boom मुझे सीने में दर्द")))
    caplog.set_level(logging.DEBUG)
    with pytest.raises(speech.SpeechUnavailable):
        speech.transcribe(b"audio", "audio/webm", "hi-IN")
    speech.translate_to_english("मुझे सीने में दर्द है")
    assert KEY not in caplog.text
    assert "सीने" not in caplog.text


def test_the_language_list_is_still_english_and_hindi_only():
    assert set(speech.LANGUAGE_CODES) == {"en-IN", "hi-IN"}
