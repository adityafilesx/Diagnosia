"""WI-212: the real name checker runs in CI on a made-up list, and a missing list is visible.

The fixture holds invented names only. The real dataset is never committed."""
import csv

import pytest

from backend import app as app_module
from backend import llm
from backend.config import ROOT_DIR, WEB_DIR
from backend.prescription import analyzer, medicines
from backend.tests.test_prescription import RecordingAI, medicine, post_photo, read_result, signed_in

FIXTURE = ROOT_DIR / "backend" / "tests" / "fixtures" / "medicine_list_fixture.csv"


@pytest.fixture
def real_checker(monkeypatch):
    """The checker as it runs in production, reading a list from disk: nothing stubbed."""
    medicines._load.cache_clear()
    monkeypatch.setattr(medicines, "DATA_FILE", FIXTURE)
    monkeypatch.setattr(analyzer, "check_name", medicines.check_name)
    yield
    medicines._load.cache_clear()


@pytest.fixture
def no_list(monkeypatch, tmp_path):
    medicines._load.cache_clear()
    monkeypatch.setattr(medicines, "DATA_FILE", tmp_path / "missing.csv")
    monkeypatch.setattr(analyzer, "check_name", medicines.check_name)
    yield
    medicines._load.cache_clear()


def test_the_fixture_holds_only_made_up_names():
    with FIXTURE.open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert 0 < len(rows) <= 20  # tiny on purpose: it is a fixture, never the dataset
    assert {row["manufacturer_name"] for row in rows} == {"Made-up Labs"}


def test_the_real_dataset_is_not_in_git():
    ignored = (ROOT_DIR / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert "datasets/" in ignored
    assert "datasets" not in FIXTURE.parts


@pytest.mark.parametrize(
    "written, status, suggestion",
    [
        ("Tab. Quorvex 250", "found", "Quorvex"),
        ("Quorvx", "close", "Quorvex"),  # a near miss, as a misread letter would give
        ("Tesolin 500", "close", "Tessolin"),
        ("Fictamol", "found", "Fictamol"),  # a generic
        ("Zzyzzle", "not_found", None),
    ],
)
def test_the_checker_loaded_from_disk_classifies_names(real_checker, written, status, suggestion):
    result = medicines.check_name(written)
    assert result["status"] == status
    assert result["name"] == suggestion


def reading_with(name):
    result = read_result()
    result.medicines[0].name.value = name
    result.medicines[0].name.legibility = "clear"
    return result


def test_a_near_miss_read_from_a_photo_is_close_and_marked_unsure_and_never_changed(client, details, monkeypatch, real_checker):
    monkeypatch.setattr(llm, "ask", RecordingAI(reading_with("Quorvx")))
    signed_in(client, details)
    body = post_photo(client).json()
    entry = body["medicines"][0]
    assert entry["match"]["status"] == "close" and entry["match"]["name"] == "Quorvex"
    assert entry["name"] == {"value": "Quorvx", "legibility": "unsure"}  # flagged, never corrected
    assert body["names_checked"] is True


def test_with_no_list_every_name_is_unchecked_and_the_reading_says_so(client, details, monkeypatch, no_list):
    monkeypatch.setattr(llm, "ask", RecordingAI(reading_with("Quorvx")))
    signed_in(client, details)
    body = post_photo(client).json()
    assert body["medicines"][0]["match"]["status"] == "unchecked"
    assert body["names_checked"] is False


def test_the_page_says_when_a_name_could_not_be_checked():
    script = (WEB_DIR / "js" / "care" / "prescription.js").read_text(encoding="utf-8")
    assert "We could not check this name against a list" in script
    assert "medicine_list_ready" in script and "names_checked" in script


def test_the_config_and_readyz_report_a_missing_list(client, details, no_list):
    signed_in(client, details)
    assert client.get("/api/platform/config").json()["medicine_list_ready"] is False
    ready = client.get("/readyz")
    assert "medicine_list_missing" in ready.json()["warnings"]
    assert ready.status_code == 200  # a warning: the site still works, names just aren't checked


def test_the_config_and_readyz_are_quiet_when_the_list_is_there(client, details, real_checker):
    signed_in(client, details)
    assert client.get("/api/platform/config").json()["medicine_list_ready"] is True
    assert client.get("/readyz").json()["warnings"] == []


def test_the_list_can_live_somewhere_else(monkeypatch):
    from backend.config import Settings

    monkeypatch.setenv("DIAGNOSIA_MEDICINE_LIST", str(FIXTURE))
    assert Settings().medicine_list == FIXTURE
