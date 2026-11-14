"""WI-211: the server keeps its own reading, decides what may be confirmed, and records what was."""
import json

import pytest

from backend import llm
from backend.config import WEB_DIR
from backend.db import connect
from backend.prescription import analyzer, routes
from backend.prescription.analyzer import Guidance, ReadPrescription
from backend.tests.conftest import linked_patient
from backend.tests.test_prescription import RecordingAI, post_photo, signed_in
from backend.version import APP_VERSION


def read_field(value="", legibility="clear"):
    return {"value": value, "legibility": legibility}


def med(name="Amoxicillin", frequency=read_field("BD"), day_pattern=read_field("1-0-1"), name_legibility="clear"):
    return {
        "name": read_field(name, name_legibility),
        "dose": read_field("500 mg"),
        "frequency": frequency,
        "day_pattern": day_pattern,
        "duration": read_field("5 days"),
        "notes": read_field(),
    }


def reading(*medicines):
    return ReadPrescription.model_validate(
        {"is_prescription": True, "medicines": list(medicines), "follow_up_date": read_field(), "doctor_notes": read_field()}
    )


class TwoStepAI:
    """Answers the read with a reading and everything after it with empty guidance."""

    def __init__(self, result):
        self.result = result
        self.calls = []

    def __call__(self, system, content, schema, **options):
        self.calls.append({"content": content, "schema": schema, **options})
        return self.result if schema is ReadPrescription else schema.model_validate({"medicines": []})


def read(client, monkeypatch, *medicines):
    ai = TwoStepAI(reading(*medicines))
    monkeypatch.setattr(llm, "ask", ai)
    response = post_photo(client)
    assert response.status_code == 200
    return response.json(), ai


def explain(client, reading_id, confirmed, **fields):
    return client.post("/api/prescription/explain", json={"reading_id": reading_id, "confirmed": confirmed, "language": "en-IN", **fields})


def confirmations():
    db = connect()
    try:
        return [dict(row) for row in db.execute("SELECT * FROM prescription_confirmations ORDER BY created_at, rowid")]
    finally:
        db.close()


# --- one readability rule ---------------------------------------------------------------------

LEGIBLE_MARK_UNREADABLE_TEXT = med(frequency=read_field("squiggle", "unreadable"), day_pattern=read_field("1-0-1"))
NOTHING_TO_GO_ON = med(frequency=read_field("", "unreadable"), day_pattern=read_field())
UNREADABLE_NAME = med(name="Amox?", name_legibility="unreadable")


@pytest.mark.parametrize(
    "medicine, expected",
    [(med(), True), (LEGIBLE_MARK_UNREADABLE_TEXT, True), (NOTHING_TO_GO_ON, False), (UNREADABLE_NAME, False), (med(name="  "), False)],
)
def test_the_server_says_which_medicines_can_be_confirmed(client, details, monkeypatch, medicine, expected):
    signed_in(client, details)
    result, _ = read(client, monkeypatch, medicine)
    assert result["medicines"][0]["confirmable"] is expected
    assert result["reading_id"]


def test_a_legible_mark_with_unreadable_text_is_handled_the_same_on_both_sides(client, details, monkeypatch):
    # The page offers a tick exactly where the server says so, and the server explains exactly those.
    signed_in(client, details)
    result, ai = read(client, monkeypatch, LEGIBLE_MARK_UNREADABLE_TEXT)
    assert result["medicines"][0]["confirmable"] is True
    explained = explain(client, result["reading_id"], [0]).json()
    assert explained["ask_pharmacist"] == []
    assert explained["schedule"]["morning"][0]["name"] == "Amoxicillin"


def test_the_page_has_no_readability_rule_of_its_own():
    script = (WEB_DIR / "js" / "care" / "prescription.js").read_text(encoding="utf-8")
    assert "medicine.confirmable" in script
    assert "function isReadable" not in script
    # It sends which cards were ticked, never the medicines or how legible they were.
    assert "confirmed:" in script and "legibility: 'unreadable'" not in script


# --- the server uses its own reading, not what the browser sends -----------------------------


def test_explaining_uses_the_stored_reading_not_fields_sent_by_the_browser(client, details, monkeypatch):
    signed_in(client, details)
    result, ai = read(client, monkeypatch, med(), UNREADABLE_NAME)
    forged = json.loads(json.dumps(result["medicines"]))
    forged[1]["name"] = read_field("Warfarin", "clear")  # the browser claims the unreadable one was clear
    response = explain(client, result["reading_id"], [0], medicines=forged)
    assert response.status_code == 200
    sent = json.dumps([call["content"] for call in ai.calls[1:]])
    assert "Warfarin" not in sent and "Amoxicillin" in sent


def test_ticking_a_medicine_that_cannot_be_confirmed_is_refused(client, details, monkeypatch):
    signed_in(client, details)
    result, ai = read(client, monkeypatch, med(), UNREADABLE_NAME)
    response = explain(client, result["reading_id"], [0, 1])
    assert response.status_code == 422
    assert len(ai.calls) == 1  # only the read: nothing was explained
    assert confirmations() == []


def test_an_unticked_medicine_goes_to_the_pharmacist_list_and_is_never_explained(client, details, monkeypatch):
    signed_in(client, details)
    result, ai = read(client, monkeypatch, med(), med(name="Pantoprazole"))
    explained = explain(client, result["reading_id"], [0]).json()
    assert explained["ask_pharmacist"] == ["Pantoprazole"]
    assert "Pantoprazole" not in json.dumps([call["content"] for call in ai.calls[1:]])


@pytest.mark.parametrize("confirmed", [[5], [-1], [0, 0]])
def test_a_tick_must_name_a_medicine_in_the_reading_once(client, details, monkeypatch, confirmed):
    signed_in(client, details)
    result, _ = read(client, monkeypatch, med())
    assert explain(client, result["reading_id"], confirmed).status_code == 422


def test_a_reading_belongs_to_the_person_who_made_it(client, details, monkeypatch, person):
    signed_in(client, details)
    result, _ = read(client, monkeypatch, med())
    other = person("patient", "Nisha", "Rao")
    assert explain(other, result["reading_id"], [0]).status_code == 404
    assert explain(other, "no-such-reading", [0]).status_code == 404


def test_explain_needs_a_reading(client, details, monkeypatch):
    signed_in(client, details)
    monkeypatch.setattr(llm, "ask", RecordingAI(Guidance(medicines=[])))
    response = client.post("/api/prescription/explain", json={"medicines": [med()], "language": "en-IN"})
    assert response.status_code == 422


def test_an_old_reading_must_be_read_again(client, details, monkeypatch):
    signed_in(client, details)
    result, _ = read(client, monkeypatch, med())
    db = connect()
    db.execute("UPDATE prescription_readings SET created_at = '2020-01-01T00:00:00+00:00'")
    db.commit()
    db.close()
    assert explain(client, result["reading_id"], [0]).status_code == 409
    db = connect()
    routes.forget_old_readings(db)  # what the sweep runs
    db.commit()
    assert db.execute("SELECT COUNT(*) FROM prescription_readings").fetchone()[0] == 0
    db.close()


# --- the record of what was confirmed ---------------------------------------------------------


def test_every_explain_records_the_confirmed_set(client, details, monkeypatch):
    signed_in(client, details)
    result, _ = read(client, monkeypatch, med(), med(name="Pantoprazole"), UNREADABLE_NAME)
    assert explain(client, result["reading_id"], [1], doctor_notes="SECRET-NOTE review in a week").status_code == 200
    [row] = confirmations()
    assert row["action"] == "explain" and row["reading_id"] == result["reading_id"]
    assert row["app_version"] == APP_VERSION and row["language"] == "en-IN"
    assert row["offered"] == 2 and row["read_count"] == 3  # two could be ticked, of three read
    confirmed = json.loads(row["confirmed"])
    assert [item["index"] for item in confirmed] == [1]
    assert confirmed[0]["name"] == {"value": "Pantoprazole", "legibility": "clear"}
    assert set(confirmed[0]) == {"index", "name", "dose", "frequency", "day_pattern", "duration", "notes"}
    assert "SECRET-NOTE" not in json.dumps(row)  # no free text beyond the confirmed medicine fields
    assert "Amoxicillin" not in row["confirmed"]  # the unticked one is not in the confirmed set


def test_the_record_names_the_models(client, details, monkeypatch):
    signed_in(client, details)
    result, _ = read(client, monkeypatch, med())
    monkeypatch.setattr(llm, "last_model", lambda: "gemini/gemini-test")
    explain(client, result["reading_id"], [0])
    [row] = confirmations()
    assert row["explain_model"] == "gemini/gemini-test"
    assert row["read_model"] == "unknown"  # the fake AI in this test names no model


def test_a_save_records_the_confirmed_set_and_keeps_only_ticked_medicines(doctor, person, monkeypatch):
    account, record = linked_patient(doctor, person)
    result, _ = read(account, monkeypatch, med(), med(name="Pantoprazole"))
    saved = account.post("/api/prescription/save", json={"reading_id": result["reading_id"], "confirmed": [0]})
    assert saved.status_code == 201 and saved.json()["medicines"] == 1
    rows = [row for row in confirmations() if row["action"] == "save"]
    assert [json.loads(row["confirmed"])[0]["name"]["value"] for row in rows] == ["Amoxicillin"]
    db = connect()
    stored = json.loads(db.execute("SELECT medicines FROM saved_prescriptions").fetchone()[0])
    db.close()
    assert [item["name"]["value"] for item in stored] == ["Amoxicillin"]


def test_nothing_ticked_cannot_be_saved(doctor, person, monkeypatch):
    account, _ = linked_patient(doctor, person)
    result, _ = read(account, monkeypatch, med())
    assert account.post("/api/prescription/save", json={"reading_id": result["reading_id"], "confirmed": []}).status_code == 422


def test_no_photo_is_kept_with_a_reading(client, details, monkeypatch):
    signed_in(client, details)
    read(client, monkeypatch, med())
    db = connect()
    columns = {row[1] for row in db.execute("PRAGMA table_info(prescription_readings)")}
    db.close()
    assert not columns & {"photo", "image", "images", "doctor_notes"}


def test_the_photo_beside_each_card_never_leaves_the_browser():
    script = (WEB_DIR / "js" / "care" / "prescription.js").read_text(encoding="utf-8")
    assert "URL.createObjectURL(photo)" in script and "URL.revokeObjectURL(address)" in script
    assert "photoStrip()" in script
    # The only upload of the photo is the read itself.
    assert script.count("body.append('images'") == 1
