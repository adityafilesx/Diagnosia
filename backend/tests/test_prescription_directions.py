"""WI-213: the AI's "how to take" sentence is checked against the prescription's own numbers, and a
missing course length is never filled in."""
import pytest

from backend import llm
from backend.config import WEB_DIR
from backend.prescription import analyzer, crosscheck
from backend.prescription.analyzer import Guidance
from backend.tests.test_prescription import RecordingAI, timed


def by_schema(guidance):
    """The explanation for the explanation call, and "can't place it" for the planning call."""
    def answer(system, content, schema, **options):
        return guidance if schema is Guidance else schema.model_validate({"medicines": []})

    return answer


def explained(monkeypatch, medicine, sentence, language="en-IN", name=None):
    answer = Guidance.model_validate(
        {"medicines": [{"name": name or medicine.name.value, "purpose": "For infection.", "how_to_take": sentence}]}
    )
    monkeypatch.setattr(llm, "ask", by_schema(answer))
    return analyzer.explain_prescription([medicine], language)["guidance"]["medicines"][0]


AMOX = timed("Amoxicillin", frequency="BD", day_pattern="1-0-1", duration="x 5 days", dose="500 mg")


# --- the cross-check ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "sentence",
    [
        "Take one in the morning and one at night, for 5 days.",
        "Take 1 tablet twice a day for 5 days.",
        "Take it two times a day. Each dose is 500 mg.",
        "Take it in the morning and at night after food.",  # no numbers at all
        "सुबह 1 और रात को 1 गोली, 5 दिन तक लें।",
        "सुबह एक और रात को एक गोली, पाँच दिन तक लें।",
        "दिन में दो बार लें, ५ दिन तक।",
    ],
)
def test_a_sentence_that_agrees_with_the_prescription_is_kept(monkeypatch, sentence):
    result = explained(monkeypatch, AMOX, sentence)
    assert result["how_to_take"] == sentence
    assert result["directions_rejected"] is False


@pytest.mark.parametrize(
    "sentence",
    [
        "Take 2 tablets three times a day for 5 days.",  # three times: written twice
        "Take one in the morning and one at night, for 7 days.",  # 7 days: written 5
        "Take 250 mg twice a day.",  # a different dose
        "Take it at 8 am and 9 pm.",  # clock times nobody wrote
        "दिन में तीन बार लें।",  # three times, in Hindi words
        "१० दिन तक लें।",  # ten days, in Devanagari digits
        "Take four tablets daily.",
    ],
)
def test_a_seeded_mismatch_is_rejected(monkeypatch, sentence):
    result = explained(monkeypatch, AMOX, sentence)
    assert result["directions_rejected"] is True
    assert sentence not in result["how_to_take"]
    # What the patient gets instead is the prescription's own words, never the AI's numbers.
    assert "500 mg, BD, 1-0-1, x 5 days" in result["how_to_take"]


def test_the_rejected_sentence_falls_back_in_the_patients_language(monkeypatch):
    result = explained(monkeypatch, AMOX, "दिन में चार बार लें।", language="hi-IN")
    assert result["directions_rejected"] is True
    assert "पर्चे" in result["how_to_take"] and "1-0-1" in result["how_to_take"]


def test_the_rule_decoded_directions_travel_with_every_explanation(monkeypatch):
    result = explained(monkeypatch, AMOX, "Take it in the morning and at night.")
    assert result["decoded"] == "One in the morning, none in the afternoon, one at night. Twice a day. Take it for 5 days"
    assert result["as_written"] == "500 mg, BD, 1-0-1, x 5 days"


def test_directions_the_rules_cannot_decode_are_not_invented(monkeypatch):
    odd = timed("Amoxicillin", frequency="as directed")
    result = explained(monkeypatch, odd, "Take it as your doctor told you.")
    assert result["decoded"] is None and result["directions_rejected"] is False


def test_a_total_for_the_day_and_a_course_in_days_are_allowed():
    medicine = timed("T. Cefix 200", day_pattern="1-1-1", duration="for 2 weeks")
    assert crosscheck.agrees("Take 3 tablets a day for 14 days.", medicine)
    assert crosscheck.agrees("Take one tablet three times a day for 2 weeks.", medicine)
    assert not crosscheck.agrees("Take it for 5 weeks.", medicine)
    # The check compares numbers, not what each one counts: 3 is on this prescription (three a day),
    # so "for 3 weeks" passes. It catches a number nobody wrote, not a number in the wrong place.
    assert crosscheck.agrees("Take it for 3 weeks.", medicine)


def test_numbers_in_the_medicines_own_name_are_not_a_mismatch():
    medicine = timed("Dolo 650", frequency="OD")
    assert crosscheck.agrees("Take Dolo 650 once a day.", medicine)
    assert not crosscheck.agrees("Take Dolo 650 twice a day.", medicine)


def test_half_is_understood():
    medicine = timed("T. Thyronorm", day_pattern="½-0-0")
    assert crosscheck.agrees("Take half a tablet in the morning.", medicine)
    assert crosscheck.agrees("सुबह आधी गोली लें।", medicine)
    assert not crosscheck.agrees("Take one tablet in the morning.", medicine)


def test_an_explanation_for_a_medicine_nobody_confirmed_is_dropped(monkeypatch):
    answer = Guidance.model_validate(
        {
            "medicines": [
                {"name": "Amoxicillin", "purpose": "", "how_to_take": "Take it in the morning and at night."},
                {"name": "Warfarin", "purpose": "", "how_to_take": "Take it at night."},
            ]
        }
    )
    monkeypatch.setattr(llm, "ask", RecordingAI(answer))
    names = [item["name"] for item in analyzer.explain_prescription([AMOX], "en-IN")["guidance"]["medicines"]]
    assert names == ["Amoxicillin"]


# --- no invented course length -----------------------------------------------------------------


def test_there_is_no_default_course_length_any_more():
    assert not hasattr(analyzer, "UNKNOWN_DURATION_DAYS")


def test_a_medicine_with_no_written_duration_gets_no_course_length():
    reminders = analyzer.build_schedule([timed("T. Open", day_pattern="1-0-0")], "en-IN", start_date="2026-11-01")
    item = reminders["slots"]["morning"]["medicines"][0]
    assert item["duration_days"] is None and item["no_end_date"] is True
    assert "duration_assumed" not in item
    segment = reminders["slots"]["morning"]["segments"][0]
    assert segment["duration_days"] is None and segment["last_day"] is None and segment["no_end_date"] is True
    assert "no end date written, ask your doctor" in segment["description"].lower()
    assert "COUNT" not in reminders["ics"] and "RRULE:FREQ=DAILY\r\n" in reminders["ics"]


def test_a_written_duration_is_kept_exactly():
    reminders = analyzer.build_schedule([timed("T. Five", day_pattern="1-0-0", duration="x 5 days")], "en-IN")
    item = reminders["slots"]["morning"]["medicines"][0]
    assert item["duration_days"] == 5 and item["no_end_date"] is False
    assert "COUNT=5" in reminders["ics"]


def test_a_dated_course_ends_and_an_undated_one_carries_on_without_a_length():
    five = timed("T. Five", day_pattern="1-0-0", duration="x 5 days")
    open_ended = timed("T. Open", day_pattern="1-0-0")
    reminders = analyzer.build_schedule([five, open_ended], "en-IN", start_date="2026-11-01")
    first, second = reminders["slots"]["morning"]["segments"]
    assert [m["name"] for m in first["medicines"]] == ["T. Five", "T. Open"]
    assert (first["first_day"], first["last_day"], first["duration_days"]) == (1, 5, 5)
    assert [m["name"] for m in second["medicines"]] == ["T. Open"]
    assert (second["first_day"], second["last_day"], second["duration_days"]) == (6, None, None)
    assert second["dtstart"].startswith("20261106")
    assert reminders["ics"].count("COUNT=") == 1 and "COUNT=5" in reminders["ics"]


@pytest.mark.parametrize("duration", ["", "till review", "continue", "as advised"])
def test_no_reminder_ever_has_an_invented_course_length(duration):
    reminders = analyzer.build_schedule([timed("T. Any", "BD", duration=duration)], "hi-IN")
    for slot in reminders["slots"].values():
        assert slot["duration_days"] is None
        for segment in slot["segments"]:
            assert segment["duration_days"] is None and segment["no_end_date"] is True
    assert "COUNT" not in reminders["ics"]


def test_the_page_shows_the_decoded_directions_and_the_missing_end_date():
    script = (WEB_DIR / "js" / "care" / "prescription.js").read_text(encoding="utf-8")
    assert "medicine.decoded" in script and "directions_rejected" in script
    assert "No end date written. Ask your doctor" in script
    assert "duration_assumed" not in script and "set to" not in script
