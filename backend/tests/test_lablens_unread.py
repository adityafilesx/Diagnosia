"""WI-230: lines the parser could not read are counted and shown, and results written in words
(positive, negative, trace) are read on our server and sent to a person."""
import pytest

from backend import llm
from backend.config import WEB_DIR
from backend.lablens import extract, parser
from backend.lablens.extract import ReadReport
from backend.tests.conftest import FakeAI, grant
from backend.tests.test_lablens import REPORT_LINES, extraction, lab_pdf, upload

HEADER = REPORT_LINES[:4]
GOOD = ["Haemoglobin (Photometry) 11.2 L g/dL 13.0 - 17.0", "Creatinine 1.02 mg/dl < 1.3"]


def read(lines):
    return parser.parse_report("\n".join(lines))


# --- lines not read ---------------------------------------------------------------------------


def test_a_clean_report_has_no_unread_lines():
    results, unread = read(REPORT_LINES)
    assert len(results) == 8 and unread == []


def test_a_known_test_whose_value_cannot_be_read_is_counted():
    results, unread = read(HEADER + [GOOD[0], "Glucose, Fasting ## mg/dL 70 - 100", GOOD[1]])
    assert [row["standard_name"] for row in results] == ["Hemoglobin", "Creatinine"]
    assert unread == ["Glucose, Fasting ## mg/dL 70 - 100"]


def test_an_unreadable_line_between_the_results_is_counted():
    garbled = "S0d1um (ISE) 1 4 1 mm0l/L 1 3 5 - 1 4 5 ????"
    results, unread = read(HEADER + [GOOD[0], garbled, GOOD[1]])
    assert len(results) == 2 and unread == [garbled]


def test_headings_and_the_page_furniture_are_not_counted():
    lines = HEADER + [GOOD[0], "LIPID PROFILE", "Page 1 of 2", "", GOOD[1], "Report generated on 12/03/2026 at 10:42", "Dr. A. Pathologist, MD  Reg. No. 12345"]
    results, unread = read(lines)
    assert len(results) == 2 and unread == []


def test_a_known_test_is_counted_even_outside_the_table():
    _, unread = read(HEADER + GOOD + ["", "HbA1c pending, sample haemolysed"])
    assert unread == ["HbA1c pending, sample haemolysed"]


def test_parse_results_is_unchanged_for_its_callers():
    assert parser.parse_results("\n".join(REPORT_LINES)) == read(REPORT_LINES)[0]


def test_the_count_is_stored_and_shown_with_the_lines(doctor, patient):
    lines = HEADER + [GOOD[0], "Glucose, Fasting ## mg/dL 70 - 100", "S0d1um (ISE) 1 4 1 mm0l/L 1 3 5 - 1 4 5 ????", GOOD[1]]
    report = upload(doctor, patient["id"], lab_pdf(lines)).json()
    saved = extraction(doctor, report["id"])
    assert saved["lines_not_read"] == 2
    assert saved["unread_lines"] == ["Glucose, Fasting ## mg/dL 70 - 100", "S0d1um (ISE) 1 4 1 mm0l/L 1 3 5 - 1 4 5 ????"]
    assert len(saved["results"]) == 2


def test_a_clean_upload_says_zero(doctor, patient):
    report = upload(doctor, patient["id"]).json()
    saved = extraction(doctor, report["id"])
    assert saved["lines_not_read"] == 0 and saved["unread_lines"] == []


def test_the_ai_reading_reports_what_it_left_out(doctor, patient, monkeypatch):
    grant(doctor, patient["id"], "ai_processing")
    answer = ReadReport.model_validate(
        {
            "is_lab_report": True, "name_on_report": "", "laboratory": "", "collection_date": "",
            "results": [{"test_name": "Hemoglobin", "value": "12.9", "unit": "g/dL", "reference_range": "13.0 - 17.0", "printed_flag": "L", "legibility": "clear"}],
            "lines_left_out": 3,
        }
    )
    monkeypatch.setattr(llm, "ask", FakeAI(answer))
    from backend.tests.test_lablens import blank_pdf

    report = upload(doctor, patient["id"], blank_pdf()).json()
    saved = extraction(doctor, report["id"])
    assert saved["extraction_method"] == "ai-vision"
    assert saved["lines_not_read"] == 3 and saved["unread_lines"] == []  # a count only: the AI gives no text for them


def test_the_ai_is_asked_to_count_what_it_leaves_out():
    assert "lines_left_out" in extract.READ_SYSTEM
    assert "lines_left_out" in ReadReport.model_fields


def test_the_page_shows_the_count():
    script = (WEB_DIR / "js" / "care" / "lablens.js").read_text(encoding="utf-8")
    assert "lines_not_read" in script and "not read" in script and "unread_lines" in script


# --- results written in words -----------------------------------------------------------------


@pytest.mark.parametrize(
    "line, name, value",
    [
        ("HBsAg (Rapid Card) Non Reactive", "HBsAg", "Non Reactive"),
        ("Dengue NS1 Antigen : Positive", "Dengue NS1 Antigen", "Positive"),
        ("Urine Protein Trace", "Urine Protein", "Trace"),
        ("Urine Glucose - Nil", "Urine Glucose", "Nil"),
        ("Malarial Parasite Not Detected", "Malarial Parasite", "Not Detected"),
        ("Urine Ketones NEGATIVE Negative", "Urine Ketones", "NEGATIVE"),
        ("Urine Albumin 2+", "Urine Albumin", "2+"),
        ("HIV I & II Antibodies Non-Reactive", "HIV I & II Antibodies", "Non-Reactive"),
    ],
)
def test_a_result_in_words_is_read_and_sent_to_review(line, name, value):
    results, unread = read(HEADER + [GOOD[0], line, GOOD[1]])
    assert unread == []
    result = next(row for row in results if row["original_name"] == name)
    assert result["value_text"] == value and result["value_number"] is None
    assert result["confidence"] == "review"
    assert any("in words" in issue for issue in result["issues"])
    assert not any(issue in ("No unit found", "No reference range found") for issue in result["issues"])


def test_the_reference_written_beside_a_word_result_is_kept():
    result = next(row for row in read(HEADER + [GOOD[0], "Urine Ketones Positive Negative", GOOD[1]])[0] if row["original_name"] == "Urine Ketones")
    assert result["value_text"] == "Positive" and result["reference_text"] == "Negative"


@pytest.mark.parametrize("line", ["Remarks: sample received in good condition", "Method: Immunoturbidimetry", "Interpretation of results is the treating doctor's", "Negative"])
def test_ordinary_words_are_not_turned_into_results(line):
    results, _ = read(HEADER + [GOOD[0], line, GOOD[1]])
    assert len(results) == 2


def test_a_word_result_is_never_given_a_number_or_a_range_status(doctor, patient):
    lines = HEADER + [GOOD[0], "HBsAg (Rapid Card) Non Reactive", GOOD[1]]
    report = upload(doctor, patient["id"], lab_pdf(lines)).json()
    saved = extraction(doctor, report["id"])
    word = next(row for row in saved["results"] if row["original_name"] == "HBsAg")
    assert word["value_number"] is None and word["review_status"] == "pending" and word["confidence"] == "review"
    assert saved["to_review"] >= 1


def test_a_person_can_accept_a_word_result_and_it_reaches_the_record_as_written(doctor, patient):
    lines = HEADER + [GOOD[0], "HBsAg (Rapid Card) Non Reactive", GOOD[1]]
    report = upload(doctor, patient["id"], lab_pdf(lines)).json()
    base = "/api/addons/lablens"
    for row in extraction(doctor, report["id"])["results"]:
        assert doctor.patch(f"{base}/results/{row['id']}", json={"action": "accept"}).status_code == 200
    confirmed = doctor.post(f"{base}/reports/{report['id']}/confirm", json={})
    assert confirmed.status_code == 200
    observations = doctor.get(f"/api/patients/{patient['id']}/observations").json()
    found = next(item for item in observations if item["label"] == "HBsAg")
    assert found["value_text"] == "Non Reactive" and found["value_number"] is None
