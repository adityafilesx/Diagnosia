"""Scores how well lab report scans are read, field by field (WI-231).

Reads each scan in a folder made by scan_set, through the same path an uploaded scan takes
(the AI reading, then LabLens's own checks), and compares every result with the right answer.

    python -m backend.tests.lab_validation.scan_set /some/folder
    python -m backend.tests.lab_validation.scan_score /some/folder --out /some/folder/score.json

The second command needs a real Groq or Gemini key in .env: it sends the synthetic scans to the
model set for "LabLens: reading scanned reports". It is not part of the normal test run. The tests
use a stand-in reader, which proves the scoring is right and says nothing about any model.
"""
import argparse
import json
import sys
from pathlib import Path
from typing import Callable, Dict, List, Optional

from backend import llm
from backend.lablens import extract, parser
from backend.lablens.extract import ReadReport

FIELDS = ("found", "value", "unit", "low", "high", "flag")
Reader = Callable[[bytes, str], ReadReport]


def _close(first: Optional[float], second: Optional[float]) -> bool:
    if first is None or second is None:
        return first is second
    return abs(first - second) < 1e-9


def _same_name(read: dict, expected: dict) -> bool:
    if expected["code"] and read["loinc_code"]:
        return read["loinc_code"] == expected["code"]
    squeeze = lambda text: "".join(char for char in text.lower() if char.isalnum())  # noqa: E731
    return squeeze(read["original_name"]) == squeeze(expected["name"])


def score_scan(scan: dict, read: Optional[ReadReport]) -> dict:
    """One scan against its answers. `read` is None when the reader failed outright."""
    tally = {name: {"errors": 0, "total": 0} for name in FIELDS}
    problems: Dict[str, List[str]] = {"missed": [], "wrong_values": [], "wrong_rows": [], "extra": []}
    label = f"{scan['layout']} ({scan['condition']})"
    results = extract.ai_results(read) if read is not None and read.is_lab_report else []
    unused = list(results)
    for expected in scan["results"]:
        tally["found"]["total"] += 1
        found = next((item for item in unused if _same_name(item, expected)), None)
        if found is None:
            tally["found"]["errors"] += 1
            problems["missed"].append(f"{label}: {expected['name']}")
            continue
        unused.remove(found)
        tally["value"]["total"] += 1
        if not _close(found["value_number"], expected["number"]):
            tally["value"]["errors"] += 1
            # A value that is right for a different row of the same report is the dangerous kind.
            others = [other["number"] for other in scan["results"] if other is not expected]
            kind = "wrong_rows" if any(_close(found["value_number"], other) for other in others) else "wrong_values"
            problems[kind].append(f"{label}: {expected['name']} read {found['value_text']}, printed {expected['value']}")
        if expected["unit"]:
            tally["unit"]["total"] += 1
            tally["unit"]["errors"] += parser.normal_unit(found["unit"]) != parser.normal_unit(expected["unit"])
        if expected["low"] is not None:
            tally["low"]["total"] += 1
            tally["low"]["errors"] += not _close(found["reference_low"], expected["low"])
        if expected["high"] is not None:
            tally["high"]["total"] += 1
            tally["high"]["errors"] += not _close(found["reference_high"], expected["high"])
        if expected["flag"]:
            tally["flag"]["total"] += 1
            tally["flag"]["errors"] += found["reported_flag"].strip().lower() != expected["flag"].lower()
    problems["extra"] = [f"{label}: {item['original_name']}" for item in unused]
    return {"tally": tally, **problems}


def _rates(tally: dict) -> dict:
    return {
        name: {**counts, "error_rate": round(counts["errors"] / counts["total"], 4) if counts["total"] else None}
        for name, counts in tally.items()
    }


def _add(total: dict, tally: dict) -> None:
    for name in FIELDS:
        total[name]["errors"] += tally[name]["errors"]
        total[name]["total"] += tally[name]["total"]


def run(folder: Path, reader: Reader) -> dict:
    """Reads every scan in the folder and returns the error rate for each field, overall and by
    condition. Nothing here is estimated: every count comes from comparing a reading with its answer."""
    truth = json.loads((folder / "truth.json").read_text(encoding="utf-8"))
    empty = lambda: {name: {"errors": 0, "total": 0} for name in FIELDS}  # noqa: E731
    overall, by_condition = empty(), {}
    listed: Dict[str, List[str]] = {"missed": [], "wrong_values": [], "wrong_rows": [], "extra": [], "unreadable_scans": [], "not_called_a_lab_report": []}
    models = set()
    for scan in truth["scans"]:
        data = (folder / scan["file"]).read_bytes()
        label = f"{scan['layout']} ({scan['condition']})"
        try:
            llm.forget_last_model()
            read = reader(data, "image/jpeg")
            if llm.last_model():
                models.add(llm.last_model())
        except (llm.AINotConfigured, llm.AIBudgetReached, llm.AIRateLimited):
            raise  # the model was never asked: stop, so a missing key or a used-up limit is never reported as an error rate
        except (llm.AIUnavailable, llm.AIDeclined) as error:
            # The model gave no usable answer. Every result on this scan counts as missed.
            listed["unreadable_scans"].append(f"{label}: {type(error).__name__}")
            read = None
        if read is not None and not read.is_lab_report:
            listed["not_called_a_lab_report"].append(label)
        scored = score_scan(scan, read)
        _add(overall, scored["tally"])
        _add(by_condition.setdefault(scan["condition"], empty()), scored["tally"])
        for kind in ("missed", "wrong_values", "wrong_rows", "extra"):
            listed[kind] += scored[kind]
    return {
        "set": truth["version"],
        "scans": len(truth["scans"]),
        "models": sorted(models),
        "fields": _rates(overall),
        "by_condition": {condition: _rates(tally) for condition, tally in by_condition.items()},
        **listed,
    }


def table(result: dict) -> str:
    """The per-field error rates as a Markdown table, ready for docs/BASELINES.md."""
    lines = ["| Field | Wrong | Of | Error rate |", "|---|---|---|---|"]
    for name in FIELDS:
        counts = result["fields"][name]
        rate = "n/a" if counts["error_rate"] is None else f"{counts['error_rate'] * 100:.1f}%"
        lines.append(f"| {name} | {counts['errors']} | {counts['total']} | {rate} |")
    return "\n".join(lines)


def main(arguments=None) -> int:
    options = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    options.add_argument("folder", type=Path, help="a folder made by scan_set")
    options.add_argument("--out", type=Path, help="also write the full result as JSON here")
    args = options.parse_args(arguments)
    if not (args.folder / "truth.json").exists():
        print(f"No truth.json in {args.folder}. Make the set first: python -m backend.tests.lab_validation.scan_set {args.folder}", file=sys.stderr)
        return 2
    try:
        result = run(args.folder, extract.read_with_ai)
    except llm.AINotConfigured:
        print("No AI key is set, so nothing was read and there is no score. Add GROQ_API_KEY or GEMINI_API_KEY to .env and run this again.", file=sys.stderr)
        return 2
    except (llm.AIBudgetReached, llm.AIRateLimited):
        print("The AI budget or the provider's rate limit was reached part-way, so there is no score. Run this again later.", file=sys.stderr)
        return 2
    if args.out:
        args.out.write_text(json.dumps(result, indent=1), encoding="utf-8")
    print(f"{result['scans']} scans from {result['set']}, read by {', '.join(result['models']) or 'an unnamed model'}.\n")
    print(table(result))
    for kind in ("wrong_rows", "wrong_values", "missed", "unreadable_scans", "not_called_a_lab_report"):
        if result[kind]:
            print(f"\n{kind.replace('_', ' ')} ({len(result[kind])}):")
            print("\n".join(f"  {item}" for item in result[kind]))
    print(f"\nExtra results not on the report: {len(result['extra'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
