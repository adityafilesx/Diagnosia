"""WI-220: numbers and units are checked against the lines a statement cites, medicine names and how
often are checked too, and a clinician's edit is checked again."""
import pytest

from backend import llm
from backend.clinscribe import verifier
from backend.tests.conftest import FakeAI
from backend.tests.test_clinscribe import draft, encounter, fake_draft, session, statement  # noqa: F401 (fixtures)

BASE = "/api/addons/clinscribe"
TWO_MEDICINES = ["Start metformin 850 mg twice daily", "Continue amlodipine 5 mg once daily"]


def check(text, transcript, cited=(1,)):
    return verifier.check_statement(text, list(cited), dict(enumerate(transcript, start=1)))


def flagged(result):
    return result["verdict"] in ("uncertain", "unsupported")


def reasons(result):
    return " | ".join(result["reasons"]).lower()


# --- numbers and units against the cited lines ------------------------------------------------


def test_a_statement_matching_its_cited_line_is_still_supported():
    assert check("Continue amlodipine 5 mg once daily", TWO_MEDICINES, cited=(2,))["verdict"] == "supported"
    assert check("Start metformin 850 mg twice daily", TWO_MEDICINES, cited=(1,))["verdict"] == "supported"


def test_a_dose_from_another_line_is_flagged_as_the_wrong_item():
    # 850 is in the transcript, but it is metformin's dose. Checked against the whole transcript
    # (the old way) this passed.
    result = check("Continue amlodipine 850 mg once daily", TWO_MEDICINES, cited=(2,))
    assert flagged(result)
    assert "850" in reasons(result)


def test_citing_both_lines_does_not_hide_a_dose_on_the_wrong_medicine():
    result = check("Continue amlodipine 850 mg once daily", TWO_MEDICINES, cited=(1, 2))
    assert result["verdict"] == "unsupported"
    assert "amlodipine" in reasons(result) and "850" in reasons(result)


def test_a_number_said_only_elsewhere_names_the_line_it_is_in():
    transcript = ["Fever for 3 days", "Weight is 70 kg", "Cough is worse at night"]
    result = check("Fever for 70 days", transcript, cited=(1,))
    assert flagged(result)
    assert "line 2" in reasons(result)


def test_a_unit_from_another_line_does_not_pass():
    transcript = ["Levothyroxine 50 mcg in the morning", "Vitamin D 50 mg weekly"]
    result = check("Levothyroxine 50 mg in the morning", transcript, cited=(1,))
    assert flagged(result)
    assert "unit" in reasons(result) or "levothyroxine" in reasons(result)


# --- medicine names ---------------------------------------------------------------------------


def test_a_swapped_medicine_is_flagged():
    result = check("Amlodipine 5 mg daily", ["Atenolol 5 mg daily"])
    assert result["verdict"] == "unsupported"
    assert "amlodipine" in reasons(result) and "medicine" in reasons(result)


def test_a_medicine_named_only_in_another_line_is_flagged():
    transcript = ["Atenolol 5 mg daily", "She also takes amlodipine for blood pressure"]
    result = check("Amlodipine 5 mg daily", transcript, cited=(1,))
    assert result["verdict"] == "unsupported"


def test_a_misheard_spelling_of_the_same_medicine_is_not_a_swap():
    assert check("Amlodipine 5 mg daily", ["amlodipin 5 mg daily"])["verdict"] == "supported"
    assert check("Metformin 500 mg twice daily", ["Met formin 500 mg twice daily"])["verdict"] != "unsupported"


@pytest.mark.parametrize(
    "text",
    ["Blood pressure 140 over 90", "Weight 70 kg", "Fasting sugar was 118 this week", "Pain for 3 days in the left knee"],
)
def test_ordinary_measurements_are_not_mistaken_for_medicines(text):
    assert verifier.medicine_names(text) == set()


def test_medicine_names_are_found_beside_a_dose_or_a_form():
    assert verifier.medicine_names("Continue metformin 850 mg twice daily") == {"metformin"}
    assert verifier.medicine_names("Tab Pantop-D once daily before food") == {"pantop"}
    assert verifier.medicine_names("Increase the dose to 10 mg") == set()


# --- how often --------------------------------------------------------------------------------


def test_a_changed_frequency_is_flagged():
    result = check("Metformin 850 mg three times a day", ["Start metformin 850 mg twice daily"])
    assert result["verdict"] == "unsupported"
    assert "how often" in reasons(result)


@pytest.mark.parametrize("note", ["Metformin 850 mg BD", "Metformin 850 mg twice a day", "Metformin 850 mg 2 times a day"])
def test_the_same_frequency_in_other_words_is_supported(note):
    assert check(note, ["Start metformin 850 mg twice daily"])["verdict"] == "supported"


def test_a_frequency_nobody_said_is_flagged():
    result = check("Metformin 850 mg twice daily", ["Start metformin 850 mg"])
    assert flagged(result) and "how often" in reasons(result)


# --- clinician edits are checked again -------------------------------------------------------


def note_for(doctor, patient, encounter, monkeypatch, lines, text, cited=(1,)):
    started = session(doctor, patient, encounter).json()
    for line in lines:
        doctor.post(f"{BASE}/sessions/{started['id']}/segments", json={"text": line, "speaker": "clinician"})
    doctor.post(f"{BASE}/sessions/{started['id']}/state", json={"state": "stopped"})
    monkeypatch.setattr(llm, "ask", FakeAI(fake_draft(text, evidence_segments=list(cited))))
    return draft(doctor, started["id"]).json()


def edit(doctor, note, *texts):
    body = {"sections": [{"heading": "Subjective", "statements": [{"text": text} for text in texts]}]}
    return doctor.patch(f"{BASE}/notes/{note['id']}", json=body).json()


def test_an_edited_in_wrong_dose_is_flagged(doctor, patient, encounter, monkeypatch):
    note = note_for(doctor, patient, encounter, monkeypatch, ["Continue amlodipine 5 mg once daily"], "Continue amlodipine 5 mg once daily")
    assert note["open_flags"] == 0
    edited = edit(doctor, note, "Continue amlodipine 50 mg once daily")
    line = edited["content"]["sections"][0]["statements"][0]
    assert line["origin"] == "clinician_statement"
    assert line["check"]["verdict"] == "uncertain"
    assert "50 mg" in " ".join(line["check"]["reasons"]) and "line 1" in " ".join(line["check"]["reasons"])
    assert edited["open_flags"] == 1
    url = f"{BASE}/notes/{note['id']}/approve"
    assert doctor.post(url, json={}).json()["detail"]["code"] == "flags_open"
    assert doctor.post(url, json={"acknowledge_flags": True}).status_code == 200  # the clinician stays in charge


def test_an_edited_in_wrong_frequency_or_medicine_swap_is_flagged(doctor, patient, encounter, monkeypatch):
    note = note_for(doctor, patient, encounter, monkeypatch, TWO_MEDICINES, "Start metformin 850 mg twice daily")
    edited = edit(doctor, note, "Start metformin 850 mg three times a day", "Continue amlodipine 850 mg once daily")
    first, second = edited["content"]["sections"][0]["statements"]
    assert first["check"]["verdict"] == "uncertain" and "how often" in " ".join(first["check"]["reasons"]).lower()
    assert second["check"]["verdict"] == "uncertain" and "850 mg" in " ".join(second["check"]["reasons"])
    assert edited["open_flags"] == 2


def test_what_a_clinician_adds_from_their_own_examination_is_not_flagged(doctor, patient, encounter, monkeypatch):
    note = note_for(doctor, patient, encounter, monkeypatch, ["Continue amlodipine 5 mg once daily"], "Continue amlodipine 5 mg once daily")
    edited = edit(
        doctor, note,
        "Continue amlodipine 5 mg once daily",  # untouched: keeps its check
        "Chest clear on auscultation",
        "Blood pressure 130/80 mmHg, weight 72 kg",
        "Start atorvastatin 10 mg at night",  # a new medicine the transcript never mentions
    )
    verdicts = [line["check"]["verdict"] for line in edited["content"]["sections"][0]["statements"]]
    assert verdicts == ["supported", "clinician_entered", "clinician_entered", "clinician_entered"]
    assert edited["open_flags"] == 0


def test_correcting_a_flagged_line_to_what_was_said_clears_the_flag(doctor, patient, encounter, monkeypatch):
    note = note_for(doctor, patient, encounter, monkeypatch, ["Continue amlodipine 5 mg once daily"], "Continue amlodipine 50 mg once daily")
    assert note["open_flags"] == 1
    edited = edit(doctor, note, "Continue amlodipine 5 mg once daily")
    assert edited["open_flags"] == 0


def test_the_verifier_version_moved_on():
    assert verifier.VERSION == "2.0"
