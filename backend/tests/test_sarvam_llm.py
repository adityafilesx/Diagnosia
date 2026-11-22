"""Stretch: Sarvam as an optional third AI provider in llm.py, last in the existing fallback (step 12)."""
import json

import pytest
from pydantic import BaseModel

from backend import llm
from backend.config import settings
from backend.db import connect
from backend.operator_cli import main as operator
from backend.tests.test_opd_bookings import switch


class Answer(BaseModel):
    text: str


class Reply:
    def __init__(self, status_code, body=None):
        self.status_code = status_code
        self._body = body or {}
        self.headers = {}

    def json(self):
        return self._body


def ok(text="hi"):
    return Reply(200, {"choices": [{"message": {"content": json.dumps({"text": text})}, "finish_reason": "stop"}],
                       "usage": {"prompt_tokens": 3, "completion_tokens": 2}})


@pytest.fixture
def sarvam_llm(client, monkeypatch):
    monkeypatch.setattr(settings, "sarvam_api_key", "sk_test")
    switch("sarvam.enabled")
    switch("sarvam.llm")
    assert operator(["signoff", "--item", "sarvam_terms", "--signed-by", "x", "--role", "y", "--document-reference", "z", "--operator", "t"]) == 0


def test_the_switch_starts_off(client):
    from backend import settings_store

    assert settings_store.get("sarvam.llm") is False


def test_sarvam_is_tried_last_after_groq_fails(sarvam_llm, monkeypatch):
    monkeypatch.setattr(settings, "groq_api_key", "gsk_test")
    calls = []

    def post(url, headers, json, timeout):
        calls.append((url, json))
        return Reply(503) if "groq" in url else ok("from sarvam")

    monkeypatch.setattr(llm.httpx, "post", post)
    monkeypatch.setattr(llm.time, "sleep", lambda seconds: None)
    assert llm.ask("system", "hello", Answer, tool="clinscribe_note").text == "from sarvam"
    assert "groq.com" in calls[0][0]
    url, body = calls[-1]
    assert url == "https://api.sarvam.ai/v1/chat/completions"
    assert body["model"] == "sarvam-105b"
    assert "max_tokens" in body and "max_completion_tokens" not in body


def test_sarvam_alone_can_answer(sarvam_llm, monkeypatch):
    monkeypatch.setattr(llm.httpx, "post", lambda url, headers, json, timeout: ok())
    assert llm.ask("system", "hello", Answer, tool="clinscribe_note").text == "hi"


def test_not_used_without_its_own_switch_or_sign_off(client, monkeypatch):
    monkeypatch.setattr(settings, "sarvam_api_key", "sk_test")
    switch("sarvam.enabled")
    assert ("sarvam", "sarvam-105b") not in llm._attempts("clinscribe_note")
    switch("sarvam.llm")
    assert ("sarvam", "sarvam-105b") not in llm._attempts("clinscribe_note")  # no sign-off yet


def test_not_used_with_real_patient_data(sarvam_llm, monkeypatch):
    monkeypatch.setattr(settings, "allow_real_patient_data", True)
    assert ("sarvam", "sarvam-105b") not in llm._attempts("clinscribe_note")


def test_photos_never_go_to_sarvam(sarvam_llm):
    image = [{"type": "image", "source": {"media_type": "image/jpeg", "data": "eA=="}}]
    assert llm._attempts("prescription_read", content=image) == []
