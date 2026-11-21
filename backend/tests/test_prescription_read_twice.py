"""Two readings of one prescription: any field that differs is shown as unsure, never clear (WI-210)."""
import pytest

from backend import llm, settings_store
from backend.config import WEB_DIR, settings
from backend.prescription import analyzer, compare
from backend.prescription.analyzer import ReadPrescription
from backend.tests.test_prescription import photo_bytes
from backend.images import read_image


def field(value="", legibility="clear"):
    return {"value": value, "legibility": legibility}


def medicine(name="Amoxicillin", dose="500 mg", frequency="BD", pattern="1-0-1", duration="5 days"):
    return {
        "name": field(name), "dose": field(dose), "frequency": field(frequency),
        "day_pattern": field(pattern), "duration": field(duration), "notes": field(),
    }


def reading(*medicines, notes=""):
    return {"is_prescription": True, "medicines": list(medicines), "follow_up_date": field(), "doctor_notes": field(notes)}


def test_two_identical_readings_change_nothing():
    merged = compare.compare(reading(medicine()), reading(medicine()))
    assert merged["medicines"][0]["name"] == field("Amoxicillin")
    assert merged["medicines"][0]["differs"] == {}
    assert merged["differing_fields"] == 0


def test_small_differences_in_spacing_and_case_are_not_differences():
    merged = compare.compare(reading(medicine(dose="500 mg")), reading(medicine(dose="500MG")))
    assert merged["medicines"][0]["dose"]["legibility"] == "clear"


def test_a_field_that_differs_becomes_unsure_and_no_winner_is_picked():
    merged = compare.compare(reading(medicine(name="Azee 500", dose="500 mg")), reading(medicine(name="Azu 500", dose="250 mg")))
    first = merged["medicines"][0]
    assert first["name"] == field("Azee 500", "unsure")  # the first reading's words, marked unsure
    assert first["dose"]["legibility"] == "unsure"
    assert first["differs"] == {"name": "Azu 500", "dose": "250 mg"}  # the other reading is shown beside it
    assert first["frequency"]["legibility"] == "clear"
    assert merged["differing_fields"] == 2


def with_name_legibility(legibility):
    item = medicine()
    item["name"]["legibility"] = legibility
    return item


def test_the_stricter_legibility_wins_even_when_the_words_agree():
    merged = compare.compare(reading(medicine()), reading(with_name_legibility("unsure")))
    assert merged["medicines"][0]["name"] == field("Amoxicillin", "unsure")
    assert merged["medicines"][0]["differs"] == {}
    merged = compare.compare(reading(with_name_legibility("unreadable")), reading(medicine()))
    assert merged["medicines"][0]["name"]["legibility"] == "unreadable"


def test_a_medicine_only_one_reading_found_is_kept_and_unsure():
    merged = compare.compare(reading(medicine()), reading(medicine(), medicine(name="Pantoprazole", dose="40 mg")))
    assert [item["name"]["value"] for item in merged["medicines"]] == ["Amoxicillin", "Pantoprazole"]
    extra = merged["medicines"][1]
    assert extra["only_in_one_reading"] is True
    assert all(extra[key]["legibility"] == "unsure" for key in ("name", "dose", "frequency", "day_pattern", "duration"))


def test_medicines_are_paired_by_name_not_by_position():
    first = reading(medicine(name="Amoxicillin"), medicine(name="Pantoprazole", dose="40 mg"))
    second = reading(medicine(name="Pantoprazole", dose="40 mg"), medicine(name="Amoxicillin"))
    assert compare.compare(first, second)["differing_fields"] == 0


def test_flag_quality_counts_caught_and_missed_errors():
    truth = [("Azee 500", "1-0-0", "3"), ("Pantoprazole", "1-0-0", "5")]
    first = reading(medicine(name="Azee 500", pattern="1-0-1", duration="3 days"), medicine(name="Pantoprazole", pattern="1-0-0", duration="7 days"))
    second = reading(medicine(name="Azee 500", pattern="1-0-0", duration="3 days"), medicine(name="Pantoprazole", pattern="1-0-0", duration="7 days"))
    quality = compare.flag_quality(truth, first, second)
    # Azee's pattern is wrong and the readings differ (caught). Pantoprazole's duration is wrong in both (missed).
    assert quality["fields"] == 6 and quality["errors"] == 2 and quality["flagged"] == 1
    assert quality["caught"] == 1 and quality["missed"] == 1 and quality["false_flags"] == 0
    assert quality["precision"] == 1.0 and quality["recall"] == 0.5


class TwoReadings:
    def __init__(self, first, second):
        self.replies, self.calls = [first, second], []

    def __call__(self, system, content, schema, **options):
        self.calls.append(options)
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return ReadPrescription.model_validate(reply)


@pytest.fixture
def photo():
    return [read_image(photo_bytes())]


def test_reading_twice_is_an_experiment_that_starts_switched_off(client, photo, monkeypatch):
    ai = TwoReadings(reading(medicine()), reading(medicine()))
    monkeypatch.setattr(llm, "ask", ai)
    assert settings_store.SETTINGS["prescription.read_twice"]["default"] is False
    result = analyzer.read_prescription(photo)
    assert len(ai.calls) == 1 and "differing_fields" not in result


def test_when_switched_on_a_differing_field_is_never_clear(client, photo, monkeypatch):
    monkeypatch.setitem(settings_store.SETTINGS["prescription.read_twice"], "default", True)
    ai = TwoReadings(reading(medicine(dose="500 mg")), reading(medicine(dose="250 mg")))
    monkeypatch.setattr(llm, "ask", ai)
    result = analyzer.read_prescription(photo)
    assert len(ai.calls) == 2
    assert ai.calls[1].get("prefer_other") is True  # a different model when there is one
    assert result["medicines"][0]["dose"]["legibility"] == "unsure"
    assert result["medicines"][0]["differs"] == {"dose": "250 mg"}


def test_if_the_second_reading_fails_the_first_is_used_and_says_so(client, photo, monkeypatch):
    monkeypatch.setitem(settings_store.SETTINGS["prescription.read_twice"], "default", True)
    monkeypatch.setattr(llm, "ask", TwoReadings(reading(medicine()), llm.AIUnavailable("down")))
    result = analyzer.read_prescription(photo)
    assert result["medicines"][0]["name"]["value"] == "Amoxicillin"
    assert result["read_twice"] is False


def test_the_second_provider_goes_first_when_asked(monkeypatch):
    monkeypatch.setattr(settings, "groq_api_key", "groq-test-key")
    monkeypatch.setattr(settings, "gemini_api_key", "gemini-test-key")
    usual = [provider for provider, _ in llm._attempts("prescription_read")]
    other = [provider for provider, _ in llm._attempts("prescription_read", prefer_other=True)]
    assert other[0] != usual[0] and sorted(other) == sorted(usual)


def test_the_page_shows_the_other_reading_and_never_sends_it_on():
    page = (WEB_DIR / "js" / "care" / "prescription.js").read_text(encoding="utf-8")
    assert "differs" in page and "only_in_one_reading" in page
    # The page sends back only which cards were ticked (WI-211), so the other reading can't travel on.
    assert "medicines:" not in page and "reading_id: reading.reading_id, confirmed: confirmed" in page
