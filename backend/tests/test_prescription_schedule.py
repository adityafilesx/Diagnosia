"""WI-272: one schedule in the explanation, and a plain .ics file. No second copy, no calendar links."""
import json

from backend import llm
from backend.config import WEB_DIR
from backend.prescription import analyzer
from backend.prescription.analyzer import Guidance
from backend.tests.test_prescription import field, medicine, read_as, signed_in, timed


def quiet_ai(system, content, schema, **options):
    return schema.model_validate({"medicines": []})


def explain(client, monkeypatch, *medicines, confirmed=None):
    reading_id = read_as(client, monkeypatch, *medicines)
    monkeypatch.setattr(llm, "ask", quiet_ai)
    ticks = list(range(len(medicines))) if confirmed is None else confirmed
    response = client.post("/api/prescription/explain", json={"reading_id": reading_id, "confirmed": ticks, "language": "en-IN"})
    assert response.status_code == 200
    return response.json()


def test_the_explanation_has_one_schedule(client, details, monkeypatch):
    signed_in(client, details)
    amox = medicine("Amoxicillin", frequency="1-0-1").model_copy(update={"duration": field("5 days")})
    sos = medicine("Paracetamol", frequency="SOS")
    body = explain(client, monkeypatch, amox, sos)
    assert set(body) == {"guidance", "plan", "schedule", "ask_pharmacist"}
    schedule = body["schedule"]
    assert set(schedule) == {"start_date", "times", "slots", "as_needed", "unscheduled", "ics"}
    assert list(schedule["slots"]) == ["morning", "night"]
    assert [item["name"] for item in schedule["slots"]["morning"]["medicines"]] == ["Amoxicillin"]
    assert [item["name"] for item in schedule["as_needed"]] == ["Paracetamol"]
    # Each medicine is named once per time of day it is taken, nowhere twice over.
    assert json.dumps(body).count('"name": "Paracetamol"') == 1


def test_the_schedule_carries_a_plain_ics_and_no_calendar_links(client, details, monkeypatch):
    signed_in(client, details)
    amox = medicine("Amoxicillin", frequency="1-0-1").model_copy(update={"duration": field("5 days")})
    body = explain(client, monkeypatch, amox)
    ics = body["schedule"]["ics"]
    assert ics.startswith("BEGIN:VCALENDAR") and ics.rstrip().endswith("END:VCALENDAR")
    assert "RRULE:FREQ=DAILY;COUNT=5" in ics and ics.count("BEGIN:VEVENT") == 2
    assert "google" not in json.dumps(body).lower() and "http" not in ics.lower()


def test_one_function_builds_the_schedule():
    assert not hasattr(analyzer, "build_calendar_reminders") and not hasattr(analyzer, "generate_ics_calendar")
    schedule = analyzer.build_schedule([timed("T. Cefix 200", day_pattern="1-0-1", duration="x 5 days")], "en-IN", start_date="2026-11-01")
    slot = schedule["slots"]["morning"]
    assert set(slot) == {"slot", "title", "time", "duration_days", "medicines", "segments"}
    assert set(slot["segments"][0]) == {"title", "first_day", "last_day", "duration_days", "no_end_date", "medicines", "description", "dtstart"}
    assert slot["segments"][0]["dtstart"] == "20261101T080000"


def test_the_calendar_route_returns_the_same_schedule_for_new_times(client, details, monkeypatch):
    signed_in(client, details)
    amox = medicine("Amoxicillin", frequency="1-0-1").model_copy(update={"duration": field("5 days")})
    first = explain(client, monkeypatch, amox)["schedule"]
    reading_id = read_as(client, monkeypatch, amox)
    again = client.post(
        "/api/prescription/calendar",
        json={"reading_id": reading_id, "confirmed": [0], "language": "en-IN", "start_date": first["start_date"], "times": {"night": "22:00"}},
    ).json()
    assert set(again) == set(first)
    assert again["times"]["night"] == "22:00" and again["times"]["morning"] == first["times"]["morning"]
    assert "T220000" in again["ics"]


def test_no_diet_or_lifestyle_text_is_produced():
    # Frozen (WI-113): the explanation gives a purpose and how to take, nothing else.
    assert set(Guidance.model_json_schema()["$defs"]["MedicineGuidance"]["properties"]) == {"name", "purpose", "how_to_take"}
    source = (WEB_DIR / "js" / "care" / "prescription.js").read_text(encoding="utf-8").lower()
    assert "diet" not in source and "yoga" not in source


def test_the_page_draws_one_schedule_and_links_to_no_calendar_site():
    source = (WEB_DIR / "js" / "care" / "prescription.js").read_text(encoding="utf-8")
    assert "data.reminders" not in source and "google" not in source.lower()
    assert source.count("'Daily schedule'") == 1
    assert "schedule.ics" in source
