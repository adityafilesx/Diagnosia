"""WI-231: the scan test set and its scorer. A stand-in reader is used here, so these tests prove the
set is made right and the scoring counts right. They say nothing about how any model reads a scan."""
import hashlib
import io
import json

import pytest
from PIL import Image

from backend import llm
from backend.config import settings
from backend.lablens import extract
from backend.lablens.extract import ReadReport
from backend.tests.lab_validation import scan_score, scan_set


@pytest.fixture(scope="module")
def folder(tmp_path_factory):
    path = tmp_path_factory.mktemp("scans")
    scan_set.write(path)
    return path


def perfect(scan):
    """What a faultless reading of this scan would return."""
    return ReadReport.model_validate(
        {
            "is_lab_report": True, "name_on_report": scan["patient"] or "", "laboratory": "", "collection_date": "",
            "results": [
                {"test_name": row["name"], "value": row["value"], "unit": row["unit"], "reference_range": row["reference"], "printed_flag": row["flag"], "legibility": "clear"}
                for row in scan["results"]
            ],
        }
    )


def reader_from(folder, change=lambda scan, report: report):
    truth = json.loads((folder / "truth.json").read_text(encoding="utf-8"))
    by_digest = {hashlib.sha256((folder / scan["file"]).read_bytes()).hexdigest(): scan for scan in truth["scans"]}

    def read(data, content_type):
        scan = by_digest[hashlib.sha256(data).hexdigest()]
        return change(scan, perfect(scan))

    return read


# --- the set ----------------------------------------------------------------------------------


def test_the_set_has_every_layout_in_every_condition(folder):
    truth = json.loads((folder / "truth.json").read_text(encoding="utf-8"))
    assert truth["version"] == scan_set.VERSION
    assert len(truth["scans"]) == len(scan_set.layouts()) * len(scan_set.CONDITIONS) == 40
    assert {scan["condition"] for scan in truth["scans"]} == set(scan_set.CONDITIONS)
    assert all((folder / scan["file"]).exists() for scan in truth["scans"])


def test_each_scan_is_an_image_with_no_text_layer(folder):
    for path in folder.glob("*.jpg"):
        data = path.read_bytes()
        image = Image.open(io.BytesIO(data))
        assert image.format == "JPEG" and min(image.size) > 500
        assert b"Hemoglobin" not in data and b"Creatinine" not in data  # pixels only: nothing to copy as text


def test_the_set_is_the_same_every_time_it_is_made(tmp_path, folder):
    scan_set.write(tmp_path)
    for path in folder.glob("*.jpg"):
        assert (tmp_path / path.name).read_bytes() == path.read_bytes(), path.name
    assert (tmp_path / "truth.json").read_text(encoding="utf-8") == (folder / "truth.json").read_text(encoding="utf-8")


def test_the_conditions_really_change_the_picture(folder):
    clean = (folder / "single_lines__clean.jpg").read_bytes()
    for condition in scan_set.CONDITIONS[1:]:
        assert (folder / f"single_lines__{condition}.jpg").read_bytes() != clean


def test_the_answers_are_what_lablens_itself_makes_of_the_printed_text():
    # The ground truth must agree with the app's own parsing of a perfectly read row, or the scorer
    # would count a correct reading as wrong.
    for layout in scan_set.layouts():
        report = perfect(scan_set.truth_for(layout))
        for row, result in zip(layout.rows, extract.ai_results(report)):
            assert result["value_number"] == pytest.approx(row.number), (layout.name, row.name)
            assert result["reference_low"] == row.low and result["reference_high"] == row.high, (layout.name, row.name)
            assert result["loinc_code"] == row.code, (layout.name, row.name)


def test_every_person_and_laboratory_in_the_set_is_made_up(folder):
    assert "invented" in json.loads((folder / "truth.json").read_text(encoding="utf-8"))["note"]


# --- the scorer -------------------------------------------------------------------------------


def test_a_perfect_reading_scores_no_errors(folder):
    result = scan_score.run(folder, reader_from(folder))
    assert all(field["errors"] == 0 for field in result["fields"].values())
    assert result["fields"]["found"]["total"] == 150  # 30 results in the 8 layouts, in 5 conditions
    assert result["missed"] == result["wrong_values"] == result["wrong_rows"] == result["extra"] == []


def test_seeded_errors_are_counted_exactly(folder):
    def spoil(scan, report):
        if scan["layout"] != "close_values" or scan["condition"] != "blurred":
            return report
        rows = report.results
        rows[0].value = "183"  # a misread digit
        rows[1].value, rows[2].value = rows[2].value, rows[1].value  # two values on each other's rows
        rows[3].unit = "mg/L"  # a changed unit
        rows[3].reference_range = "0.7 - 13"  # a lost decimal point in the range
        rows[2].printed_flag = ""  # a dropped high mark
        del rows[4]  # a row left out
        return report

    result = scan_score.run(folder, reader_from(folder, spoil))
    fields = result["fields"]
    assert fields["found"]["errors"] == 1 and fields["value"]["errors"] == 3
    assert fields["unit"]["errors"] == 1 and fields["high"]["errors"] == 1 and fields["flag"]["errors"] == 1 and fields["low"]["errors"] == 0
    assert fields["value"]["total"] == 149 and fields["value"]["error_rate"] == round(3 / 149, 4)
    assert len(result["wrong_rows"]) == 2 and len(result["wrong_values"]) == 1 and len(result["missed"]) == 1
    assert all("close_values (blurred)" in item for item in result["wrong_rows"] + result["wrong_values"] + result["missed"])
    assert result["by_condition"]["blurred"]["value"]["errors"] == 3 and result["by_condition"]["clean"]["value"]["errors"] == 0


def test_an_invented_row_is_counted_as_extra_not_as_a_hit(folder):
    def add(scan, report):
        if scan["file"] == "missing_fields__clean.jpg":
            report.results.append(report.results[0].model_copy(update={"test_name": "Troponin I", "value": "0.01"}))
        return report

    result = scan_score.run(folder, reader_from(folder, add))
    assert result["extra"] == ["missing_fields (clean): Troponin I"]
    assert result["fields"]["found"]["errors"] == 0


def test_a_scan_the_model_could_not_answer_counts_every_row_as_missed(folder):
    def fail(data, content_type):
        raise llm.AIUnavailable("no answer")

    result = scan_score.run(folder, fail)
    assert result["fields"]["found"] == {"errors": 150, "total": 150, "error_rate": 1.0}
    assert len(result["unreadable_scans"]) == 40
    assert result["fields"]["value"] == {"errors": 0, "total": 0, "error_rate": None}  # no rate where nothing was compared


def test_a_scan_called_not_a_lab_report_is_listed(folder):
    def deny(scan, report):
        report.is_lab_report = scan["file"] != "single_lines__clean.jpg"
        return report

    result = scan_score.run(folder, reader_from(folder, deny))
    assert result["not_called_a_lab_report"] == ["single_lines (clean)"]
    assert result["fields"]["found"]["errors"] == 4


def test_the_table_is_ready_for_the_baselines_file(folder):
    text = scan_score.table(scan_score.run(folder, reader_from(folder)))
    assert text.splitlines()[0] == "| Field | Wrong | Of | Error rate |"
    assert "| value | 0 | 150 | 0.0% |" in text


def test_without_a_key_the_command_refuses_and_gives_no_score(folder, capsys):
    assert settings.groq_api_key == "" and settings.gemini_api_key == ""
    assert scan_score.main([str(folder)]) == 2
    printed = capsys.readouterr()
    assert "No AI key" in printed.err and "Error rate" not in printed.out


def test_the_command_needs_a_set_to_score(tmp_path, capsys):
    assert scan_score.main([str(tmp_path)]) == 2
    assert "scan_set" in capsys.readouterr().err


def test_the_command_scores_through_the_real_reading_path(folder, monkeypatch, capsys):
    # The same function an uploaded scan goes through, with the model call replaced.
    monkeypatch.setattr(extract, "read_with_ai", reader_from(folder))
    out = folder / "score.json"
    assert scan_score.main([str(folder), "--out", str(out)]) == 0
    assert json.loads(out.read_text(encoding="utf-8"))["scans"] == 40
    assert "| found | 0 | 150 | 0.0% |" in capsys.readouterr().out
    out.unlink()


def test_a_rate_limit_stops_the_run_instead_of_counting_as_misreading(folder, monkeypatch, capsys):
    def limited(data, content_type):
        raise llm.AIRateLimited("slow down")

    monkeypatch.setattr(extract, "read_with_ai", limited)
    assert scan_score.main([str(folder)]) == 2
    printed = capsys.readouterr()
    assert "no score" in printed.err and "Error rate" not in printed.out
