"""Docs that state a number the code also holds. A doc that drifts from the code fails here."""
import re
from pathlib import Path

from backend import settings_store

DOCS = Path(__file__).resolve().parents[2] / "docs"
WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10}


def _count(text: str) -> int:
    return WORDS[text.lower()] if text.lower() in WORDS else int(text)


def test_the_setup_doc_counts_the_gemini_first_tools_as_the_code_does():
    text = (DOCS / "PLATFORM_SETUP.md").read_text(encoding="utf-8")
    stated = re.search(r"\b(\w+) tools prefer Gemini", text)
    assert stated, "PLATFORM_SETUP.md must say how many tools prefer Gemini"
    assert _count(stated.group(1)) == len(settings_store.READING_TOOLS)
    # "these three" style references must agree too.
    for word in re.findall(r"\bthese (\w+)\b", text):
        if word.lower() in WORDS:
            assert WORDS[word.lower()] == len(settings_store.READING_TOOLS)


def test_the_setup_doc_says_interview_answers_go_to_gemini_first():
    text = " ".join((DOCS / "PLATFORM_SETUP.md").read_text(encoding="utf-8").split())
    assert "diagnofast_turn" in settings_store.READING_TOOLS
    assert re.search(r"interview answers go to Gemini first by default", text)
