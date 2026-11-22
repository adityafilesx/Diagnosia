"""Checks the AI's "how to take" sentence against the numbers on the prescription, with plain rules.

The explanation is written by a model, and a model can say "three times a day" for a medicine
written as twice. Every number in its sentence must be one the prescription gives: an amount, a
dose, how many times a day, or how long. A sentence with any other number is not shown. The patient
gets the prescription's own words instead. This only ever rejects: it never rewrites the sentence.
"""
import re
from typing import List, Optional, Set

from backend.prescription.shorthand import _day_amounts, decode, parse_duration_days

DEVANAGARI_DIGITS = str.maketrans("०१२३४५६७८९", "0123456789")
ENGLISH = {
    "half": 0.5, "once": 1, "twice": 2, "thrice": 3,
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
    "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "fourteen": 14, "fifteen": 15, "twenty": 20, "thirty": 30,
}
HINDI = {
    "आधा": 0.5, "आधी": 0.5, "आधे": 0.5, "डेढ़": 1.5, "ढाई": 2.5,
    "एक": 1, "दो": 2, "तीन": 3, "चार": 4, "पाँच": 5, "पांच": 5, "छह": 6, "छः": 6, "सात": 7, "आठ": 8,
    "नौ": 9, "दस": 10, "पंद्रह": 15, "बीस": 20, "तीस": 30,
}
FRACTION = {"½": 0.5, "1/2": 0.5}
AMOUNTS = {"0": 0.0, "1": 1.0, "2": 2.0, "3": 3.0, "½": 0.5, "1/2": 0.5}


def numbers(text: str) -> Set[float]:
    """Every quantity said in this text: digits in either script, fractions, and number words."""
    text = (text or "").translate(DEVANAGARI_DIGITS).lower()
    found: Set[float] = set()
    for mark, value in FRACTION.items():
        if mark in text:
            found.add(value)
            text = text.replace(mark, " ")
    found.update(float(match) for match in re.findall(r"\d+(?:\.\d+)?", text))
    found.update(ENGLISH[word] for word in re.findall(r"[a-z]+", text) if word in ENGLISH)
    # Whole Devanagari words only, so "दोपहर" (afternoon) is not read as "दो" (two).
    found.update(HINDI[word] for word in re.findall(r"[ऀ-ॿ]+", text) if word in HINDI)
    return found


def written(medicine) -> str:
    """The prescription's own words for this medicine, as read and confirmed."""
    parts = (medicine.dose.value, medicine.frequency.value, medicine.day_pattern.value, medicine.duration.value)
    return ", ".join(part.strip() for part in parts if part.strip())


def decoded(medicine) -> Optional[str]:
    """The rule-decoded directions in plain English, or None if the rules decode nothing."""
    duration = medicine.duration.value
    frequency = f"{medicine.frequency.value} x {duration}" if duration else medicine.frequency.value
    return ". ".join(filter(None, (decode(medicine.day_pattern.value), decode(frequency)))) or None


def allowed(medicine) -> Set[float]:
    """The numbers the prescription itself gives for this medicine."""
    fields = (medicine.name, medicine.dose, medicine.frequency, medicine.day_pattern, medicine.duration, medicine.notes)
    found: Set[float] = set()
    for field in fields:
        found |= numbers(field.value)
    found |= numbers(decoded(medicine) or "")  # "Twice a day" from BD, and the like
    for raw in (medicine.day_pattern.value, medicine.frequency.value):
        marks = _day_amounts(raw) if raw else None
        if marks:
            amounts = [AMOUNTS.get(mark, 0.0) for mark in marks]
            found.update(amounts)
            found.add(sum(amounts))  # "two tablets a day" for 1-0-1
    days = parse_duration_days(medicine.duration.value)
    if days:
        found.add(float(days))  # "14 days" for a course written as 2 weeks
    return found


def agrees(sentence: str, medicine) -> bool:
    """True when the sentence states no number the prescription doesn't give. Zero never counts."""
    return (numbers(sentence) - {0.0}) <= allowed(medicine)


FALLBACK = {
    "en-IN": ("Follow what is written on your prescription: {written}. Ask your pharmacist if it isn't clear.",
              "Follow what is written on your prescription. Ask your pharmacist if it isn't clear."),
    "hi-IN": ("अपने पर्चे पर जो लिखा है वही मानें: {written}। समझ न आए तो अपने फार्मासिस्ट से पूछें।",
              "अपने पर्चे पर जो लिखा है वही मानें। समझ न आए तो अपने फार्मासिस्ट से पूछें।"),
}


def fallback(medicine, language: str) -> str:
    with_words, without = FALLBACK.get(language, FALLBACK["en-IN"])
    words = written(medicine)
    return with_words.format(written=words) if words else without


def check_guidance(guidance: List[dict], medicines: list, language: str) -> List[dict]:
    """Pairs each explanation with its confirmed medicine and checks its sentence.

    An explanation for a medicine nobody confirmed is dropped: the AI may never add one."""
    unused = list(medicines)
    paired = []
    for entry in guidance:
        match = next((item for item in unused if item.name.value.strip().lower() == entry["name"].strip().lower()), None)
        if match is not None:
            unused.remove(match)
        paired.append((entry, match))
    # A name the AI respelled or translated still belongs to a medicine, when each has exactly one partner left.
    unmatched = [index for index, (_entry, match) in enumerate(paired) if match is None]
    if len(guidance) == len(medicines) and len(unmatched) == len(unused):
        for index, medicine in zip(unmatched, unused):
            paired[index] = (paired[index][0], medicine)
    checked = []
    for entry, medicine in paired:
        if medicine is None:
            continue
        rejected = not agrees(entry["how_to_take"], medicine)
        checked.append(
            {
                **entry,
                "how_to_take": fallback(medicine, language) if rejected else entry["how_to_take"],
                "directions_rejected": rejected,
                "decoded": decoded(medicine),
                "as_written": written(medicine),
            }
        )
    return checked
