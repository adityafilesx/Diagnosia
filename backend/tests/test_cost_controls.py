"""Limits on the signed-in AI routes, sign-up and login, and the daily AI breaker (audit plan WI-105)."""
import httpx
import pytest
from pydantic import BaseModel

from backend import llm, operator_cli, ratelimit
from backend.config import settings
from backend.integrations import execution
from backend.tests.test_prescription import RecordingAI, post_photo, read_result, signed_in


class Answer(BaseModel):
    text: str


def reply(prompt_tokens=1200, completion_tokens=300):
    return httpx.Response(
        200,
        json={
            "choices": [{"message": {"content": '{"text": "hello"}'}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens},
        },
    )


@pytest.fixture
def small(monkeypatch):
    def make(name, limit):
        monkeypatch.setitem(ratelimit.RULES, name, ratelimit.Rule(name, limit, 3600, "Slow down."))

    return make


@pytest.fixture
def one_provider(monkeypatch):
    monkeypatch.setattr(settings, "groq_api_key", "groq-test-key")
    monkeypatch.setattr(settings, "gemini_api_key", "")
    monkeypatch.setattr(httpx, "post", lambda *args, **options: reply())


def test_a_script_making_accounts_is_stopped_at_the_cap(client, small):
    small(ratelimit.REGISTER_PER_ADDRESS, 3)
    statuses = [
        client.post(
            "/api/auth/register",
            json={"first_name": "Bot", "last_name": str(n), "email": f"bot{n}@example.com", "password": "a-long-password", "role": "patient"},
        ).status_code
        for n in range(5)
    ]
    assert statuses == [201, 201, 201, 429, 429]


def test_login_attempts_from_one_address_are_capped(client, small):
    small(ratelimit.LOGIN_PER_ADDRESS, 2)
    attempt = {"email": "nobody@example.com", "password": "wrong-password"}
    assert [client.post("/api/auth/login", json=attempt).status_code for _ in range(3)] == [401, 401, 429]


def test_prescription_photos_are_capped_per_account(client, details, small, monkeypatch):
    small(ratelimit.PRESCRIPTION_READS, 2)
    ai = RecordingAI(read_result())
    monkeypatch.setattr(llm, "ask", ai)
    signed_in(client, details)
    assert [post_photo(client).status_code for _ in range(3)] == [200, 200, 429]
    assert len(ai.calls) == 2  # the refused photo never reached the AI


def test_every_ai_route_shares_one_daily_quota(client, details, small, monkeypatch):
    small(ratelimit.AI_DAILY_PER_USER, 1)
    monkeypatch.setattr(llm, "ask", RecordingAI(read_result()))
    signed_in(client, details)
    assert post_photo(client).status_code == 200
    explained = client.post("/api/prescription/explain", json={"medicines": [], "language": "en-IN", "doctor_notes": ""})
    assert explained.status_code == 429



def test_tokens_are_recorded_with_each_run(client, one_provider):
    llm.ask("Be careful.", "SYNTHETIC", Answer, tool="clinscribe_note")
    [row] = execution.usage_since("2000-01-01")
    assert (row["tool"], row["prompt_tokens"], row["completion_tokens"], row["calls"]) == ("clinscribe_note", 1200, 300, 1)


def test_the_breaker_trips_on_tokens_and_answers_in_plain_words(client, details, one_provider, monkeypatch):
    monkeypatch.setattr(settings, "ai_daily_tokens", 2000)
    llm.ask("Be careful.", "SYNTHETIC", Answer, tool="clinscribe_note")  # 1500 tokens: still under
    llm.ask("Be careful.", "SYNTHETIC", Answer, tool="clinscribe_note")  # 3000: now over
    with pytest.raises(llm.AIBudgetReached):
        llm.ask("Be careful.", "SYNTHETIC", Answer, tool="clinscribe_note")

    signed_in(client, details)
    refused = post_photo(client)
    assert refused.status_code == 503
    assert "limit for today" in refused.json()["detail"]


def test_the_breaker_can_trip_on_spend(client, one_provider, monkeypatch):
    model = llm._attempts("clinscribe_note")[0][1]
    monkeypatch.setattr(settings, "ai_daily_tokens", 0)
    monkeypatch.setattr(settings, "ai_daily_spend_usd", 0.001)
    monkeypatch.setattr(settings, "ai_prices", {model: (1.0, 1.0)})  # 1500 tokens cost 0.0015 USD
    llm.ask("Be careful.", "SYNTHETIC", Answer, tool="clinscribe_note")
    with pytest.raises(llm.AIBudgetReached):
        llm.ask("Be careful.", "SYNTHETIC", Answer, tool="clinscribe_note")


def test_a_weekly_cost_per_tool_can_be_printed(client, one_provider, monkeypatch, capsys):
    model = llm._attempts("clinscribe_note")[0][1]
    monkeypatch.setattr(settings, "ai_prices", {model: (0.5, 1.5)})
    llm.ask("Be careful.", "SYNTHETIC", Answer, tool="clinscribe_note")
    assert operator_cli.main(["ai-usage", "--days", "7"]) == 0
    printed = capsys.readouterr().out
    assert "clinscribe_note" in printed and "1200 in" in printed and "0.0010 USD" in printed


def test_seeding_can_lift_the_limits_for_itself(client, small):
    small(ratelimit.REGISTER_PER_ADDRESS, 1)
    with ratelimit.suspended():
        for n in range(3):
            ratelimit.hit(ratelimit.REGISTER_PER_ADDRESS, "testclient")
    ratelimit.hit(ratelimit.REGISTER_PER_ADDRESS, "testclient")
    with pytest.raises(Exception):
        ratelimit.hit(ratelimit.REGISTER_PER_ADDRESS, "testclient")
