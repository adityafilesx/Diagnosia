"""Checks a drafted note against its transcript with plain rules, not AI.

Adapted from OpenScribe's note verifier (MIT, see THIRD_PARTY_NOTICES.md), with
checks added for the errors that harm patients: "500mg" read as no number, a
lost negation, a swapped side, and a changed unit. A transcript in another
language can't be matched word by word, so those statements are left for the
clinician to check rather than marked wrong.

Version 2 checks numbers and units against the lines a statement cites, not the
whole transcript, so a dose that belongs to another medicine no longer passes. It
also checks medicine names, that a dose is said with its own medicine, and how
often, using the prescription tool's rules. Text a clinician types is checked for
a dose or frequency that conflicts with what was said.
"""
import re
from typing import Dict, List, Optional, Set, Tuple

from rapidfuzz import fuzz

from backend.prescription.medicines import CLOSE_SCORE, FORM_WORDS
from backend.prescription.shorthand import doses_a_day

VERSION = "2.0"

STOP_WORDS = {
    "a", "an", "the", "and", "or", "but", "if", "then", "of", "to", "in", "on", "for", "with", "by", "as", "is",
    "are", "was", "were", "be", "been", "it", "this", "that", "at", "from", "can", "do", "does", "we", "you",
    "they", "i", "he", "she", "has", "have", "had", "will", "patient", "reports", "states", "says", "no", "not",
    "denies", "denied", "without", "never", "nil", "negative",
}
NEGATION = re.compile(r"\b(no|not|denies|denied|without|never|nil|negative for|absent|none)\b|n't\b", re.IGNORECASE)
LATERALITY = {"left": "left", "lt": "left", "right": "right", "rt": "right", "bilateral": "both", "both": "both"}
NUMBER_UNIT = re.compile(
    r"(?<![\d.])(\d+(?:\.\d+)?)\s*(mcg|µg|ug|mg|gm|g|kg|ml|l|iu|units?|mmhg|%|tablets?|tabs?|days?|weeks?|months?)\b",
    re.IGNORECASE,
)
UNIT_ALIASES = {"µg": "mcg", "ug": "mcg", "gm": "g", "unit": "units", "tablet": "tab", "tablets": "tab", "tabs": "tab"}
NUMBER = re.compile(r"(?<![\d.])\d+(?:\.\d+)?")
DEVANAGARI_DIGITS = str.maketrans("०१२३४५६७८९", "0123456789")

# A dose, as against a measurement such as "70 kg" or "118 mg/dl".
DOSE = re.compile(r"(?<![\d.])(\d+(?:\.\d+)?)\s*(mcg|µg|ug|mg|gm|g|ml|iu|units?)\b(?!\s*/)", re.IGNORECASE)
FORM_LED = re.compile(r"\b(?:tab|tabs|tablet|cap|caps|capsule|syp|syrup|inj|injection)\b\.?\s+([a-z][a-z-]{2,})", re.IGNORECASE)
WORD = re.compile(r"[a-z][a-z-]*")
# Words that stand before a dose without naming a medicine.
NOT_A_NAME = {
    "dose", "doses", "daily", "take", "takes", "taking", "took", "increase", "increased", "reduce", "reduced",
    "continue", "continued", "start", "started", "stop", "stopped", "about", "around", "from", "only", "then",
    "each", "every", "once", "twice", "thrice", "total", "strength", "morning", "night", "evening", "afternoon",
    "sugar", "glucose", "level", "levels", "reading", "readings", "result", "value", "another", "extra", "over",
    "under", "above", "below", "nearly", "almost", "maximum", "minimum", "upto", "roughly",
}
# "2 times a day" is a frequency, checked as one. Its digit is not a number to look for in the transcript.
FREQUENCY_COUNT = re.compile(r"\b\d\s*(?:times|x)\b", re.IGNORECASE)

MIN_OVERLAP_SUPPORTED = 0.5
MIN_OVERLAP_UNCERTAIN = 0.25


def _normal(text: str) -> str:
    return (text or "").translate(DEVANAGARI_DIGITS).lower()


def tokens(text: str) -> Set[str]:
    words = re.sub(r"[^\w-]+", " ", _normal(text)).split()
    return {word for word in words if len(word) >= 2 and word not in STOP_WORDS and not word.isdigit()}


def numbers(text: str) -> Set[str]:
    return {_canonical_number(found) for found in NUMBER.findall(_normal(text))}


def _canonical_number(value: str) -> str:
    return value.rstrip("0").rstrip(".") if "." in value else value


def quantities(text: str) -> Set[tuple]:
    found = set()
    for number, unit in NUMBER_UNIT.findall(_normal(text)):
        unit = UNIT_ALIASES.get(unit, unit)
        found.add((_canonical_number(number), unit))
    return found


def sides(text: str) -> Set[str]:
    return {LATERALITY[word] for word in re.findall(r"[a-z]+", _normal(text)) if word in LATERALITY}


def is_negated(text: str) -> bool:
    return bool(NEGATION.search(_normal(text)))


def overlap(claim: str, evidence: str) -> float:
    claim_tokens = tokens(claim)
    if not claim_tokens:
        return 0.0
    return len(claim_tokens & tokens(evidence)) / len(claim_tokens)


def _is_english(text: str) -> bool:
    letters = [char for char in text if char.isalpha()]
    return not letters or sum(char.isascii() for char in letters) / len(letters) > 0.8


def _name(word: str) -> Optional[str]:
    """A word that could name a medicine: long enough, and not a form, a filler or a number word."""
    word = word.split("-")[0]
    if len(word) < 4 or word in NOT_A_NAME or word in FORM_WORDS or word in STOP_WORDS:
        return None
    return word


def _named(text: str) -> List[Tuple[int, str]]:
    """Each medicine named in the text, with where it is. A name is the word before a dose
    ("metformin 850 mg") or after a form ("Tab Pantop-D")."""
    text = _normal(text)
    found: Dict[int, str] = {}
    for dose in DOSE.finditer(text):
        before = list(WORD.finditer(text[: dose.start()]))[-2:]
        for word in reversed(before):
            name = _name(word.group())
            if name:
                found[word.start()] = name
                break
    for led in FORM_LED.finditer(text):
        name = _name(led.group(1).lower())
        if name:
            found[led.start(1)] = name
    return sorted(found.items())


def medicine_names(text: str) -> Set[str]:
    return {name for _position, name in _named(text)}


def doses_by_medicine(text: str) -> Dict[str, Set[tuple]]:
    """Which dose is written with which medicine: each dose goes to the nearest name before it."""
    text = _normal(text)
    named = _named(text)
    result: Dict[str, Set[tuple]] = {name: set() for _position, name in named}
    for dose in DOSE.finditer(text):
        earlier = [name for position, name in named if position < dose.start()]
        owner = earlier[-1] if earlier else (named[0][1] if named else None)
        if owner:
            unit = dose.group(2).lower()
            result[owner].add((_canonical_number(dose.group(1)), UNIT_ALIASES.get(unit, unit)))
    return result


def names_medicine(line: str, name: str) -> bool:
    """Whether a transcript line names this medicine, allowing for a misheard or split spelling."""
    squeezed = re.sub(r"[^a-z]+", "", _normal(line))
    return name in squeezed or fuzz.partial_ratio(name, squeezed) >= CLOSE_SCORE


def _dose_words(doses: Set[tuple]) -> str:
    return ", ".join(sorted(f"{number} {unit}" for number, unit in doses))


def _medicine_reasons(text: str, lines: Dict[int, str]) -> List[str]:
    """What is wrong with the medicines, doses and frequency in a statement, judged against these lines."""
    reasons: List[str] = []
    doses = doses_by_medicine(text)
    for name in sorted(doses):
        naming = {sequence: line for sequence, line in lines.items() if names_medicine(line, name)}
        if not naming:
            reasons.append(f"Medicine not named in the cited lines: {name}")
            continue
        said = set().union(*(quantities(line) for line in naming.values()))
        wrong = doses[name] - said
        if wrong:
            reasons.append(f"{_dose_words(wrong)} is not said with {name} in the cited lines")
    if doses:
        stated = doses_a_day(text)
        heard = {count for count in (doses_a_day(line) for line in lines.values()) if count is not None}
        if stated is not None and not heard:
            reasons.append("How often is not said in the cited lines")
        elif stated is not None and stated not in heard:
            reasons.append("How often differs from the cited lines")
    return reasons


def check_clinician_text(text: str, segments: Dict[int, str]) -> dict:
    """A line the clinician typed. It is theirs, and may say things nobody spoke aloud, so it is only
    flagged where it conflicts with the transcript: a different dose, or a different frequency, for a
    medicine that was discussed. A medicine the transcript never mentions is not questioned."""
    reasons: List[str] = []
    doses = doses_by_medicine(text)
    stated = doses_a_day(text) if doses else None
    for name in sorted(doses):
        naming = {sequence: line for sequence, line in segments.items() if names_medicine(line, name)}
        if not naming:
            continue
        where = ", ".join(f"line {sequence}" for sequence in sorted(naming))
        said = set().union(*(quantities(line) for line in naming.values()))
        wrong = doses[name] - said
        if wrong and said:
            reasons.append(f"You wrote {_dose_words(wrong)} for {name}; the transcript ({where}) says {_dose_words(said)}")
        heard = {count for count in (doses_a_day(line) for line in naming.values()) if count is not None}
        if stated is not None and heard and stated not in heard:
            reasons.append(f"How often differs from the transcript ({where})")
    if reasons:
        return {"verdict": "uncertain", "score": 1.0, "reasons": reasons, "evidence": []}
    return {"verdict": "clinician_entered", "score": 1.0, "reasons": [], "evidence": []}


def check_statement(text: str, cited: List[int], segments: Dict[int, str]) -> dict:
    """Finds the best evidence for one statement and says what doesn't line up."""
    scored = sorted(
        ((overlap(text, line), sequence) for sequence, line in segments.items()),
        key=lambda item: (item[0], item[1] in cited),
        reverse=True,
    )
    best_score, best_sequence = scored[0] if scored else (0.0, None)
    transcript = " ".join(segments.values())
    english = _is_english(transcript)
    # The lines this statement rests on: the ones it cites, and the one that matches it best. A
    # transcript in another language can't be matched, so there it is the cited lines, or all of them.
    near = {*cited, *([best_sequence] if english and best_sequence is not None else [])}
    lines = {n: segments[n] for n in sorted(near) if n in segments}
    if not english and not lines:
        lines = dict(segments)
    evidence = " ".join(lines.values())
    reasons: List[str] = []

    stated_numbers = numbers(FREQUENCY_COUNT.sub(" ", text))
    missing_numbers = stated_numbers - numbers(transcript)
    if missing_numbers:
        reasons.append(f"Number not in the transcript: {', '.join(sorted(missing_numbers))}")
    # Said somewhere, but not in the lines this statement rests on: it may belong to something else.
    for number in sorted(stated_numbers - numbers(evidence) - missing_numbers):
        places = ", ".join(f"line {n}" for n, line in segments.items() if number in numbers(line))
        reasons.append(f"Number {number} is in {places}, not in the lines this cites")
    unplaced = stated_numbers - numbers(evidence)
    changed_units = {f"{number} {unit}" for number, unit in quantities(text) - quantities(evidence) if number not in unplaced}
    if changed_units:
        reasons.append(f"Amount or unit differs from the cited lines: {', '.join(sorted(changed_units))}")

    if not english:
        if not cited:
            reasons.append("No transcript line cited")
        reasons.append("Transcript is in another language: compare by hand")
        return {"verdict": "unsupported" if missing_numbers else "uncertain", "score": 0.0, "reasons": reasons, "evidence": sorted(cited)}

    if sides(text) and sides(text) - sides(transcript):
        reasons.append("Side of the body differs from the transcript")
    if best_score >= MIN_OVERLAP_UNCERTAIN and evidence and is_negated(text) != is_negated(evidence):
        reasons.append("Possible lost or added negation: check 'no' or 'denies'")
    # A wrong medicine, a dose said with another medicine, or a different frequency is never "close enough".
    medicine_reasons = _medicine_reasons(text, lines)
    wrong_medicine = [reason for reason in medicine_reasons if reason != "How often is not said in the cited lines"]
    reasons.extend(medicine_reasons)

    if best_score < MIN_OVERLAP_UNCERTAIN or missing_numbers or wrong_medicine:
        verdict = "unsupported"
        if best_score < MIN_OVERLAP_UNCERTAIN:
            reasons.append("Couldn't find this in the transcript")
    elif reasons or best_score < MIN_OVERLAP_SUPPORTED:
        verdict = "uncertain"
    else:
        verdict = "supported"
    return {
        "verdict": verdict,
        "score": round(best_score, 2),
        "reasons": reasons,
        "evidence": sorted({*[n for n in cited if n in segments], *([best_sequence] if best_sequence is not None and best_score > 0 else [])}),
    }


def verify_note(content: dict, segments: Dict[int, str]) -> dict:
    """Adds a check to every statement, and a summary for the review screen."""
    counts = {"supported": 0, "uncertain": 0, "unsupported": 0}
    for section in content["sections"]:
        for statement in section["statements"]:
            check = check_statement(statement["text"], statement.get("evidence_segments", []), segments)
            if statement.get("origin") == "ai_summary" and check["verdict"] == "supported":
                check["verdict"] = "uncertain"
                check["reasons"].append("AI summary: confirm this reflects your judgement")
            if statement.get("uncertain"):
                reason = statement.get("uncertainty_reason") or "The AI marked this as uncertain"
                check["reasons"].append(reason)
                check["verdict"] = "uncertain" if check["verdict"] == "supported" else check["verdict"]
            statement["check"] = check
            counts[check["verdict"]] += 1
    checked = counts["supported"] + counts["unsupported"] + counts["uncertain"]
    status = "verified"
    if checked and counts["unsupported"] / checked > 0.3:
        status = "failed"
    elif counts["unsupported"] or counts["uncertain"]:
        status = "partial"
    content["verification"] = {"status": status, "version": VERSION, **counts}
    return content


def open_flags(content: dict) -> int:
    return sum(
        1
        for section in content["sections"]
        for statement in section["statements"]
        if statement.get("check", {}).get("verdict") in ("uncertain", "unsupported")
    )
