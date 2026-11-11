"""Scores DiagnoFast against the labelled test data from diagnofast_data.py.

    python -m backend.synthetic.diagnofast_eval                 # urgent-symptom rules, dev split. No keys, no network
    python -m backend.synthetic.diagnofast_eval --split test    # the frozen split: report it once, before and after a change
    python -m backend.synthetic.diagnofast_eval --live --limit 100   # whole interviews with your configured AI

The rules check is deterministic, so any change in its numbers comes from the code. The live check
sends made-up text to the AI providers in your .env and is not repeatable run to run.
"""
import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional

from backend.diagnofast import agent, red_flags
from backend.synthetic.diagnofast_data import OUTPUT_DIR

NEGATIVE_WORDS = ("no ", "none", "nil", "not ", "denies", "without", "absent", "n/a")
UNKNOWN_WORDS = ("unknown", "not sure", "unsure", "don't know", "do not know", "unclear")


def load(name: str, split: str, folder: Path = OUTPUT_DIR) -> List[dict]:
    with open(folder / f"{name}_{split}.jsonl", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def score_value(spec: dict, value: Optional[str]) -> bool:
    """A coarse check that a captured form value says what the patient said."""
    text = (value or "").strip().lower()
    polarity = spec["polarity"]
    if polarity == "unknown":
        return not text or any(word in text for word in UNKNOWN_WORDS)
    if not text:
        return False
    if polarity == "absent":
        return text.startswith(("no", "none", "nil", "not", "denies", "without")) or any(word in text for word in NEGATIVE_WORDS)
    return all(any(option in text for option in group) for group in spec["must"])


def score_screening(rows: Iterable[dict], screen: Callable[[str], List[str]] = red_flags.screen) -> dict:
    kinds: Dict[str, Counter] = defaultdict(Counter)
    categories: Dict[str, Counter] = defaultdict(Counter)
    scripts: Dict[str, Counter] = defaultdict(Counter)
    misses: List[dict] = []
    ambiguous: List[dict] = []
    for row in rows:
        found = screen(row["text"])
        if row["expected"] is None:
            ambiguous.append({"text": row["text"], "flagged": found})
            continue
        right = found == row["expected"]
        kinds[row["kind"]]["right" if right else "wrong"] += 1
        scripts[row["script"]]["right" if right else "wrong"] += 1
        for label in row["expected"]:
            categories[label]["found" if label in found else "missed"] += 1
        if not row["expected"] and found:
            categories["(false alarm)"]["flagged"] += 1
        if not right:
            misses.append({"text": row["text"], "kind": row["kind"], "expected": row["expected"], "found": found})
    return {"kinds": kinds, "categories": categories, "scripts": scripts, "misses": misses, "ambiguous": ambiguous}


def rule_stop(item: dict, screen: Callable[[str], List[str]] = red_flags.screen) -> dict:
    """Where the rules would end this interview, if anywhere."""
    for position, turn in enumerate(item["turns"]):
        found = screen(turn["answer"])
        if found:
            return {"urgent": True, "at_turn": position, "labels": found}
    return {"urgent": False, "at_turn": None, "labels": []}


def score_interviews_rules(items: Iterable[dict]) -> dict:
    tally = Counter()
    wrong: List[dict] = []
    for item in items:
        got, want = rule_stop(item), item["expect"]
        tally["interviews"] += 1
        if want["urgent"]:
            tally["urgent_expected"] += 1
            tally["urgent_caught"] += got["urgent"] and got["at_turn"] == want["at_turn"] and got["labels"] == want["labels"]
        else:
            tally["calm_expected"] += 1
            tally["false_stops"] += got["urgent"]
        if got != want:
            wrong.append({"id": item["id"], "form": item["form_id"], "trap": item["trap"], "want": want, "got": got})
    return {"tally": tally, "wrong": wrong}


def run_interview(item: dict, advance: Callable = agent.advance) -> dict:
    """Plays one interview through the real controlled loop and returns what it captured."""
    form = agent.load_form(item["form_id"])
    answers: Dict[str, str] = {}
    conversation: List[dict] = []
    stopped = None
    for position, turn in enumerate(item["turns"]):
        conversation.append({"question": turn["question"], "answer": turn["answer"]})
        step = advance(form, answers, conversation, position + 1, item["language"])
        answers = step.answers
        if step.urgent:
            stopped = {"urgent": True, "at_turn": position, "labels": step.urgent}
            break
        if step.question is None:
            break
    return {"answers": answers, "stopped": stopped or {"urgent": False, "at_turn": None, "labels": []}}


def score_interviews_live(items: Iterable[dict], advance: Callable = agent.advance) -> dict:
    tally = Counter()
    by_form: Dict[str, Counter] = defaultdict(Counter)
    errors: List[dict] = []
    for item in items:
        try:
            result = run_interview(item, advance)
        except Exception as error:  # a provider failure shouldn't hide the rest of the run
            tally["errors"] += 1
            errors.append({"id": item["id"], "error": type(error).__name__})
            continue
        tally["interviews"] += 1
        want = item["expect"]
        if want["urgent"]:
            tally["urgent_expected"] += 1
            tally["urgent_caught"] += result["stopped"]["urgent"] and result["stopped"]["at_turn"] == want["at_turn"]
            continue
        tally["calm_expected"] += 1
        tally["false_stops"] += result["stopped"]["urgent"]
        for key, spec in item["gold"].items():
            by_form[item["form_id"]]["fields"] += 1
            tally["fields"] += 1
            if score_value(spec, result["answers"].get(key)):
                by_form[item["form_id"]]["right"] += 1
                tally["fields_right"] += 1
            if spec["polarity"] == "present" and not result["answers"].get(key):
                tally["required_missed"] += 1
    return {"tally": tally, "by_form": by_form, "errors": errors}


def _percent(part: int, whole: int) -> str:
    return f"{part}/{whole} ({100 * part / whole:.1f}%)" if whole else "n/a"


def report_rules(split: str, folder: Path = OUTPUT_DIR, show: int = 12) -> int:
    screening = score_screening(load("screening", split, folder))
    print(f"\n== Urgent-symptom rules on the {split} split ==")
    print("\nSingle answers, exact set of flags:")
    for kind in ("positive", "clause_break", "negated", "history", "ordinary"):
        count = screening["kinds"][kind]
        print(f"  {kind:13} {_percent(count['right'], count['right'] + count['wrong'])}")
    print("\nRecall by urgent category (an expected flag was raised):")
    for label, count in sorted(screening["categories"].items()):
        if label.startswith("("):
            continue
        print(f"  {label:30} {_percent(count['found'], count['found'] + count['missed'])}")
    print(f"\nBy script (right answers): " + ", ".join(f"{name} {_percent(c['right'], c['right'] + c['wrong'])}" for name, c in sorted(screening["scripts"].items())))
    print(f"\nNeeds a clinician's decision (not scored): {len(screening['ambiguous'])} answers, "
          f"{sum(1 for a in screening['ambiguous'] if a['flagged'])} flagged by the rules")
    for case in screening["ambiguous"]:
        print(f"    {'FLAG' if case['flagged'] else 'pass'}  {case['text']}")
    interviews = score_interviews_rules(load("interviews", split, folder))
    tally = interviews["tally"]
    print(f"\nWhole interviews, did the rules stop at the right turn with the right labels:")
    print(f"  urgent interviews caught   {_percent(tally['urgent_caught'], tally['urgent_expected'])}")
    print(f"  calm interviews stopped    {tally['false_stops']} of {tally['calm_expected']} (should be 0)")
    if screening["misses"]:
        print(f"\nFirst {min(show, len(screening['misses']))} of {len(screening['misses'])} wrong single answers:")
        for miss in screening["misses"][:show]:
            print(f"  [{miss['kind']}] {miss['text']!r}: expected {miss['expected']}, found {miss['found']}")
    return 0


def report_live(split: str, limit: int, folder: Path = OUTPUT_DIR) -> int:
    items = load("interviews", split, folder)[:limit]
    print(f"\n== Whole interviews with the configured AI, {len(items)} from the {split} split ==")
    result = score_interviews_live(items)
    tally = result["tally"]
    print(f"  form fields captured right {_percent(tally['fields_right'], tally['fields'])}")
    print(f"  urgent interviews stopped  {_percent(tally['urgent_caught'], tally['urgent_expected'])}")
    print(f"  calm interviews stopped    {tally['false_stops']} of {tally['calm_expected']} (should be 0)")
    print(f"  fields left empty          {tally['required_missed']}   errors {tally['errors']}")
    for form, count in sorted(result["by_form"].items()):
        print(f"    {form:18} {_percent(count['right'], count['fields'])}")
    return 0


def main(arguments=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--split", choices=["dev", "test"], default="dev")
    parser.add_argument("--live", action="store_true", help="run whole interviews through the configured AI")
    parser.add_argument("--limit", type=int, default=50)
    args = parser.parse_args(arguments)
    if args.split == "test":
        print("Reminder: the test split is frozen. Report it before and after a change, and never tune on it.")
    if args.live:
        return report_live(args.split, args.limit)
    return report_rules(args.split)


if __name__ == "__main__":
    raise SystemExit(main())
