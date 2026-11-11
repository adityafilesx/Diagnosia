"""The DiagnoFast test data is frozen, reproducible and consistent, and its scorer works."""
import hashlib
import json
from pathlib import Path

import pytest

from backend import llm
from backend.diagnofast import agent
from backend.diagnofast.agent import FieldUpdate, Turn
from backend.synthetic import diagnofast_data as data
from backend.synthetic import diagnofast_eval as evaluation

FOLDER = data.OUTPUT_DIR


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_the_frozen_files_match_their_recorded_hashes():
    manifest = json.loads((FOLDER / "manifest.json").read_text(encoding="utf-8"))
    for name, expected in manifest["sha256"].items():
        assert sha(FOLDER / name) == expected, f"{name} changed. Make a new version instead of editing v1."


def test_the_same_seed_rebuilds_the_same_files(tmp_path):
    manifest = data.generate(tmp_path, data.SEED, 200)
    assert manifest["sha256"] == json.loads((FOLDER / "manifest.json").read_text(encoding="utf-8"))["sha256"]


def test_the_set_is_big_enough_and_covers_every_form_and_language():
    interviews = evaluation.load("interviews", "dev") + evaluation.load("interviews", "test")
    screening = evaluation.load("screening", "dev") + evaluation.load("screening", "test")
    assert len(interviews) >= 1000
    assert {item["form_id"] for item in interviews} == {form["id"] for form in agent.list_forms()}
    assert {item["language"] for item in interviews} == {"en-IN", "hi-IN"}
    assert {item["answer_style"] for item in interviews} == {"en", "dev", "rom", "mixed"}
    assert sum(1 for item in interviews if item["expect"]["urgent"]) >= 250
    assert sum(1 for item in interviews if item["trap"] in ("negated", "history")) >= 250
    assert {row["kind"] for row in screening} == {"positive", "negated", "clause_break", "history", "ordinary", "ambiguous"}


def test_the_test_half_is_a_fifth_and_never_overlaps_the_dev_half():
    for name in ("interviews", "screening"):
        dev, test = evaluation.load(name, "dev"), evaluation.load(name, "test")
        assert not {row["id"] for row in dev} & {row["id"] for row in test}
        assert 0.1 < len(test) / (len(dev) + len(test)) < 0.3


def test_every_gold_value_passes_its_own_check():
    for split in ("dev", "test"):
        for item in evaluation.load("interviews", split):
            for key, spec in item["gold"].items():
                assert evaluation.score_value(spec, spec["value"]), (item["form_id"], key, spec)


def test_interviews_only_ask_questions_on_their_form():
    for item in evaluation.load("interviews", "dev"):
        form = agent.load_form(item["form_id"])
        keys = {field["key"] for field in form["fields"]}
        assert all(turn["field_key"] in keys for turn in item["turns"])
        assert item["expect"]["urgent"] is False or item["expect"]["at_turn"] == len(item["turns"]) - 1


def test_the_value_check_is_strict_about_polarity():
    present = {"polarity": "present", "must": [["metformin"], ["amlodipine"]]}
    assert evaluation.score_value(present, "Metformin and Amlodipine daily")
    assert not evaluation.score_value(present, "Metformin")
    assert evaluation.score_value({"polarity": "absent", "must": []}, "No allergies")
    assert not evaluation.score_value({"polarity": "absent", "must": []}, "")
    assert evaluation.score_value({"polarity": "unknown", "must": []}, "")


def test_the_screening_scorer_counts_a_perfect_and_a_blind_screen():
    rows = evaluation.load("screening", "dev")
    perfect = {row["text"]: row["expected"] for row in rows if row["expected"] is not None}
    best = evaluation.score_screening(rows, screen=lambda text: perfect.get(text, []))
    assert not best["misses"]
    blind = evaluation.score_screening(rows, screen=lambda text: [])
    assert any(miss["kind"] == "positive" for miss in blind["misses"])
    assert blind["kinds"]["negated"]["wrong"] == 0


def test_a_perfect_ai_captures_every_field_through_the_real_interview_loop(monkeypatch):
    items = [item for item in evaluation.load("interviews", "dev") if not item["expect"]["urgent"] and item["trap"] is None][:25]
    current = {}

    def oracle(system, content, schema, **options):
        conversation = json.loads(content)["conversation"]
        turn = current["item"]["turns"][len(conversation) - 1]
        spec = current["item"]["gold"][turn["field_key"]]
        return Turn(updates=[FieldUpdate(key=turn["field_key"], value=spec["value"])], next_question="Next?", finished=False, urgent_symptoms=[])

    monkeypatch.setattr(llm, "ask", oracle)

    def advance(*args):
        return agent.advance(*args)

    tally = {"fields": 0, "right": 0}
    for item in items:
        current["item"] = item
        result = evaluation.run_interview(item, advance)
        for key, spec in item["gold"].items():
            tally["fields"] += 1
            tally["right"] += evaluation.score_value(spec, result["answers"].get(key))
    assert tally["fields"] > 100 and tally["right"] == tally["fields"]


def test_the_live_scorer_reports_a_provider_failure_instead_of_crashing():
    item = evaluation.load("interviews", "dev")[0]

    def broken(*args):
        raise llm.AIUnavailable("down")

    result = evaluation.score_interviews_live([item], broken)
    assert result["tally"]["errors"] == 1 and result["errors"][0]["error"] == "AIUnavailable"


def test_nothing_in_the_data_looks_like_a_real_contact_detail():
    text = (FOLDER / "interviews_dev.jsonl").read_text(encoding="utf-8") + (FOLDER / "screening_dev.jsonl").read_text(encoding="utf-8")
    assert "@" not in text


def test_test_interview_links_are_created_and_open_for_the_patient(client, tmp_path):
    from backend.synthetic import diagnofast_links, seed_accounts

    assert seed_accounts.run(patients=6, with_login=2, seed=3) == 0
    assert diagnofast_links.run(per_form=2, seed=1) == 0
    script = (tmp_path / "synthetic" / "diagnofast_script.md").read_text(encoding="utf-8")
    assert script.count("/intake.html?token=") == 12
    token = script.split("/intake.html?token=")[1].split()[0]
    client.cookies.clear()  # the patient has no account
    assert client.get(f"/api/diagnofast/patient/{token}").status_code == 200


def test_test_interview_links_refuse_to_run_before_the_accounts_exist(client, tmp_path, capsys):
    from backend.synthetic import diagnofast_links

    assert diagnofast_links.run(per_form=1, seed=1) == 1
    assert "make the test accounts" in capsys.readouterr().err
