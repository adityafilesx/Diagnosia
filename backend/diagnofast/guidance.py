"""Doctor-like follow-up questions for DiagnoFast (BUILD.md step 7). Everything here only advises.

Two Settings switches, both off by default:
- diagnofast.graph_followups: the Neo4j question graph picks the next question for the patient's
  complaint (complaint -> follow-ups -> red-flag screening questions -> associated symptoms). The AI
  only words it in the patient's language and pulls out the answer.
- diagnofast.doctor_like_interview: known context (age, sex, past visits, simulated ABHA records, each
  labelled with its source) so the interview confirms instead of re-asking; a probe for vague answers
  ("sometimes", "a lot"); a warmer tone; and good questions as examples.

With both off, nothing here runs and the interview is exactly as before. The code's rules never move:
red_flags.screen runs first on every answer, apply_turn keeps the 12-question cap and always asks about
medicines and allergies, and only fields on the form are kept. A red-flag node only ADDS a screening
question. The AI never diagnoses and never says anything is or isn't serious.
"""
import json
import logging
import re
import sqlite3
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Optional

from backend import addons
from backend.integrations import graph

logger = logging.getLogger("curai.diagnofast")

GRAPH_DIR = Path(__file__).parent / "graph"
SEED_FILE = GRAPH_DIR / "questions_v2.json"
EXAMPLES_FILE = GRAPH_DIR / "good_questions.json"
MAX_EXAMPLES = 6
DEVANAGARI = r"ऀ-ॿ"

GRAPH_RULES = """

Graph guidance (when the request has graph_suggestion):
- The clinic's question graph chose the next question for this complaint. Ask it next, worded naturally
  and briefly in the patient's language. Skip it only if the patient has already clearly answered it.
- A question of kind "red_flag_screen" is a screening question. Ask it plainly. Never say why it is
  asked and never suggest anything is or isn't serious.
- Fill form fields only from what the patient said, as always."""

DOCTOR_LIKE_RULES = """

Talk like a careful, kind doctor taking a history:
- One short question at a time, in simple words. Start with a brief acknowledgement of what they said
  ("Thank you", "I understand"), without reassuring them about seriousness.
- If the patient mixes Hindi and English (Hinglish), reply in the same mix.
- known_context lists facts we already have, each with its source. Confirm them instead of asking again
  ("Last time you said you take metformin. Are you still taking it?"). Facts from "abha_simulated" are
  made-up demo records: always confirm them with the patient and record only what the patient says.
  Never copy a known_context fact into a field unless the patient confirms it.
- If vague_answer is given, ask the probe it suggests, so the doctor gets a number or a pattern.
- examples shows good questions doctors liked. Follow their style, not their content."""

VAGUE = [
    # (pattern, what to ask instead)
    (r"\b(?:sometimes|occasionally|now and then|on and off|off and on|kabhi kabhi|kabhi-kabhi|kabhi kabhar)\b|कभी[- ]कभी|कभी कभार",
     "how many times a week, or a day, it happens"),
    (r"\b(?:a lot|very much|too much|lots|severe|bahut|bohot|bahut zyada|bahut jyada|zyada)\b|बहुत|ज़्यादा|ज्यादा",
     "how bad it is on a scale from 1 to 10"),
    (r"\b(?:long time|many days|for a while|kaafi din|kafi din|bahut din|kai din)\b|काफ़ी दिन|काफी दिन|बहुत दिन|कई दिन",
     "how many days, weeks or months exactly"),
]


@lru_cache(maxsize=1)
def seed() -> dict:
    return json.loads(SEED_FILE.read_text(encoding="utf-8"))


def _keyword_pattern(word: str) -> str:
    if re.search(f"[{DEVANAGARI}]", word):
        # Python's \b splits Devanagari at vowel signs, so mark the start by a non-Devanagari character.
        return rf"(?<![{DEVANAGARI}]){re.escape(word)}"
    return rf"\b{re.escape(word)}\b"


@lru_cache(maxsize=1)
def _complaint_patterns() -> Dict[str, re.Pattern]:
    return {
        complaint["id"]: re.compile("|".join(_keyword_pattern(word) for word in complaint["keywords"]), re.IGNORECASE)
        for complaint in seed()["complaints"]
    }


# A clause that denies something ("no rash", "कोई दाने नहीं", "khansi nahi") names no complaint.
CLAUSE_BREAK = re.compile(r"[,.;:!?।|]|\b(?:but|and|par|lekin|magar|aur)\b|(?<![\u0900-\u097F])(?:पर|लेकिन|मगर|और)(?![\u0900-\u097F])", re.IGNORECASE)
NEGATION = re.compile(r"\b(?:no|not|none|never|without|denies|nahi|nahin|nhi|na)\b|नहीं|नही|ना(?![\u0900-\u097F])", re.IGNORECASE)


def match_complaints(texts: List[str]) -> List[str]:
    """The seed's complaints mentioned in the patient's own words, in the order they first appear.

    Clauses that deny something are skipped, so "fever since Monday, no cough" is fever only."""
    found: List[str] = []
    for text in texts:
        for clause in CLAUSE_BREAK.split(text or ""):
            if not clause or NEGATION.search(clause):
                continue
            for complaint_id, pattern in _complaint_patterns().items():
                if complaint_id not in found and pattern.search(clause):
                    found.append(complaint_id)
    return found


def vague_probe(answer: str) -> Optional[dict]:
    """A short answer that names no number or pattern gets a probe. Longer, detailed answers don't."""
    text = (answer or "").strip()
    if not text or re.search(r"\d", text) or len(text.split()) > 12:
        return None
    for pattern, probe in VAGUE:
        found = re.search(pattern, text, re.IGNORECASE)
        if found:
            return {"word": found.group(0), "ask_about": probe}
    return None


def examples(db: Optional[sqlite3.Connection] = None) -> List[dict]:
    """Good follow-up questions, as prompt examples. Hand-written for the demo at first, then reviewed
    doctor feedback that a person promoted (operator_cli feedback-promote). Newest promoted first.
    Fine-tuning comes later, and only on reviewed real data."""
    found: List[dict] = []
    if db is not None:
        try:
            found = [
                {"source": "doctor_feedback", "patient_said": "", "good_question": row["good_question"]}
                for row in db.execute(
                    "SELECT good_question FROM diagnofast_feedback WHERE promoted_at IS NOT NULL AND good_question IS NOT NULL ORDER BY promoted_at DESC LIMIT ?",
                    (MAX_EXAMPLES,),
                )
            ]
        except sqlite3.Error:
            found = []
    if EXAMPLES_FILE.exists():
        found += json.loads(EXAMPLES_FILE.read_text(encoding="utf-8")).get("examples", [])
    return found[:MAX_EXAMPLES]


def ensure_questions(client) -> bool:
    """Loads the seed into Neo4j once per process. Idempotent, so a second load changes nothing."""
    version = seed()["version"]
    if getattr(client, "_questions_loaded", None) == version:
        return True
    client.load_questions(seed())
    try:
        client._questions_loaded = version
    except AttributeError:
        pass
    return True


def graph_suggestion(db: sqlite3.Connection, complaints: List[str], asked: List[str], language: str) -> Optional[dict]:
    """The graph's next question, or None (switch off, Neo4j down, nothing left). Never raises."""
    if not complaints or not addons.enabled("diagnofast.graph_followups", db):
        return None
    client = graph.client(db)
    if client is None:
        return None
    try:
        ensure_questions(client)
        found = client.next_question(complaints, asked)
    except graph.GraphUnavailable as error:
        logger.warning("Question graph unavailable, the AI chooses alone: %s", error)
        return None
    if not found:
        return None
    kind = {"red_flag": "red_flag_screen"}.get(found["kind"], found["kind"])
    return {"id": found["id"], "kind": kind, "question": found["hi" if language == "hi-IN" else "en"], "english": found["en"]}


def known_context(db: sqlite3.Connection, row: sqlite3.Row) -> List[dict]:
    """Facts we already hold, each labelled with its source, for the interview to confirm, not re-ask."""
    facts: List[dict] = []
    if row["patient_age"] is not None:
        facts.append({"source": "booking", "fact": f"Age {row['patient_age']}"})
    if row["patient_sex"]:
        facts.append({"source": "booking", "fact": f"Sex {row['patient_sex']}"})
    if row["patient_id"]:
        # Past finished visits for the same patient record. The link already belongs to that record, so
        # this is the patient's own care team's information, read through the same database.
        past = db.execute(
            """
            SELECT created_at, report, reviewed_at FROM intakes
            WHERE patient_id = ? AND id != ? AND status = 'done' AND report IS NOT NULL
            ORDER BY id DESC LIMIT 3
            """,
            (row["patient_id"], row["id"]),
        ).fetchall()
        for visit in past:
            report = json.loads(visit["report"])
            source = "past_visit_reviewed" if visit["reviewed_at"] else "past_visit_unreviewed"
            day = (visit["created_at"] or "")[:10]
            if report.get("chief_complaint"):
                facts.append({"source": source, "fact": f"{day}: came with {report['chief_complaint']}"})
            for medicine in report.get("current_medicines", [])[:5]:
                facts.append({"source": source, "fact": f"{day}: said they take {medicine}"})
            for allergy in report.get("allergies", [])[:5]:
                facts.append({"source": source, "fact": f"{day}: said they are allergic to {allergy}"})
    if row["records"]:
        records = json.loads(row["records"])
        for kind in ("conditions", "prescriptions"):
            for item in records.get(kind, [])[:5]:
                facts.append({"source": "abha_simulated", "fact": f"{kind[:-1]}: {item}"})
    return facts
