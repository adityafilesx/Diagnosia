"""Compares two independent readings of one prescription.

Handwriting reading varies from run to run, and a confident "clear" can still be wrong. Where two
readings disagree, at least one of them is wrong, so that field is shown as unsure for the patient
to check against the paper. This code never picks a winner and never merges values: the first
reading's words stay as they are, and the other reading's words are shown beside them.

It is an experiment until measured on the synthetic set (see ai_eval/run_eval.py --twice), so it is
behind a setting that starts off.
"""
import copy
import re
from typing import Dict, List, Optional, Sequence, Tuple

from rapidfuzz import fuzz

MEDICINE_FIELDS = ("name", "dose", "frequency", "day_pattern", "duration", "notes")
OTHER_FIELDS = ("follow_up_date", "doctor_notes")
_ORDER = {"clear": 0, "unsure": 1, "unreadable": 2}
SAME_MEDICINE = 70  # how alike two names must be to be the same line of the prescription


def _plain(value: str) -> str:
    return re.sub(r"[^a-z0-9ऀ-ॿ]", "", (value or "").lower())


def _stricter(first: str, second: str) -> str:
    return first if _ORDER[first] >= _ORDER[second] else second


def _pairs(first: List[dict], second: List[dict]) -> Tuple[List[Optional[int]], List[int]]:
    """For each medicine in the first reading, the most alike unused one in the second, or None."""
    unused = list(range(len(second)))
    partners: List[Optional[int]] = []
    for item in first:
        best, score = None, SAME_MEDICINE
        for index in unused:
            alike = fuzz.ratio(_plain(item["name"]["value"]), _plain(second[index]["name"]["value"]))
            if alike >= score:
                best, score = index, alike
        if best is None and len(first) == len(second) and len(partners) in unused:
            best = len(partners)  # same count: an unrecognisable name is still the same line
        if best is not None:
            unused.remove(best)
        partners.append(best)
    return partners, unused


def _compare_field(mine: dict, theirs: dict) -> Optional[str]:
    """Makes `mine` no more confident than the pair deserves. Returns the other value if it differs."""
    mine["legibility"] = _stricter(mine["legibility"], theirs["legibility"])
    if _plain(mine["value"]) == _plain(theirs["value"]):
        return None
    if mine["legibility"] == "clear":
        mine["legibility"] = "unsure"
    return theirs["value"]


def _all_unsure(medicine: dict) -> dict:
    for key in MEDICINE_FIELDS:
        if medicine[key]["legibility"] == "clear" and medicine[key]["value"].strip():
            medicine[key]["legibility"] = "unsure"
    medicine["differs"] = {}
    medicine["only_in_one_reading"] = True
    return medicine


def compare(first: dict, second: dict) -> dict:
    """The first reading, with every field the second disagrees on marked unsure."""
    result = copy.deepcopy(first)
    other = copy.deepcopy(second)
    partners, unused = _pairs(result["medicines"], other["medicines"])
    differing = 0
    for medicine, partner in zip(result["medicines"], partners):
        if partner is None:
            _all_unsure(medicine)
            differing += 1
            continue
        medicine["differs"] = {}
        for key in MEDICINE_FIELDS:
            theirs = _compare_field(medicine[key], other["medicines"][partner][key])
            if theirs is not None:
                medicine["differs"][key] = theirs
                differing += 1
    for index in unused:  # a medicine only the second reading found is kept for the patient to check
        result["medicines"].append(_all_unsure(other["medicines"][index]))
        differing += 1
    for key in OTHER_FIELDS:
        if _compare_field(result[key], other[key]) is not None:
            differing += 1
    result["is_prescription"] = first["is_prescription"] or second["is_prescription"]
    result["read_twice"] = True
    result["differing_fields"] = differing
    return result


def _find(reading: dict, name: str) -> Optional[dict]:
    wanted = _plain(name)
    return next((item for item in reading["medicines"] if wanted and wanted in _plain(item["name"]["value"])), None)


def _wrong(medicine: Optional[dict], kind: str, want: str) -> bool:
    if medicine is None:
        return True
    if kind == "name":
        return False  # found by name, so the name is right
    if kind == "pattern":
        return _plain(want) not in _plain(medicine["day_pattern"]["value"]) + _plain(medicine["frequency"]["value"])
    return bool(want) and re.sub(r"\D", "", medicine["duration"]["value"]) != want


def flag_quality(truth: Sequence[Tuple[str, str, str]], first: dict, second: dict) -> Dict[str, float]:
    """How well "the readings differ" predicts "the first reading is wrong", against known answers.

    `truth` holds (name, pattern, duration in days) for each medicine on a synthetic prescription.
    """
    tally = {"fields": 0, "errors": 0, "flagged": 0, "caught": 0, "missed": 0, "false_flags": 0}
    for name, pattern, duration in truth:
        mine, theirs = _find(first, name), _find(second, name)
        for kind, want in (("name", name), ("pattern", pattern), ("duration", duration)):
            wrong = _wrong(mine, kind, want)
            if mine is None or theirs is None:
                flagged = (mine is None) != (theirs is None)
            elif kind == "name":
                flagged = _plain(mine["name"]["value"]) != _plain(theirs["name"]["value"])
            elif kind == "pattern":
                flagged = (_plain(mine["day_pattern"]["value"]), _plain(mine["frequency"]["value"])) != (
                    _plain(theirs["day_pattern"]["value"]), _plain(theirs["frequency"]["value"]))
            else:
                flagged = _plain(mine["duration"]["value"]) != _plain(theirs["duration"]["value"])
            tally["fields"] += 1
            tally["errors"] += wrong
            tally["flagged"] += flagged
            tally["caught"] += wrong and flagged
            tally["missed"] += wrong and not flagged
            tally["false_flags"] += flagged and not wrong
    tally["precision"] = tally["caught"] / tally["flagged"] if tally["flagged"] else 0.0
    tally["recall"] = tally["caught"] / tally["errors"] if tally["errors"] else 0.0
    return tally
