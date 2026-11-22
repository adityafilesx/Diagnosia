"""Neo4j for DiagnoFast's graphs (docs/integrations/NEO4J.md).

Neo4j is a read-only copy. SQLite stays the record, nothing flows back, and SQLite decides access:
graph queries return IDs and coded terms, and anything shown is read again from SQLite.

The app talks to Neo4j only through the named methods of GraphClient, so tests swap in an in-memory
fake and never need a server. The driver is optional (requirements-integrations.txt): with it missing,
the switch off, no address, or real patient data allowed, client() returns None and every caller falls
back to today's behaviour.
"""
import logging
import sqlite3
import threading
from typing import Dict, List, Optional, Protocol, Sequence

from backend.config import settings

logger = logging.getLogger("diagnosia.graph")


class GraphUnavailable(Exception):
    """Neo4j couldn't be reached or answered badly. Callers fall back; nothing is invented."""


class GraphClient(Protocol):
    def load_questions(self, seed: dict) -> None: ...

    def next_question(self, complaints: Sequence[str], asked: Sequence[str]) -> Optional[dict]: ...

    def department_votes(self, complaints: Sequence[str]) -> Dict[str, int]: ...

    def merge_visit(self, visit: dict) -> None: ...

    def history(self, patient_ref: str) -> List[dict]: ...

    def evidence(self, visit_ref: str) -> List[dict]: ...

    def merge_referral(self, referral: dict) -> None: ...

    def referral_network(self, refs: Sequence[str]) -> List[dict]: ...

    def clear(self) -> None: ...


CONSTRAINTS = (
    "CREATE CONSTRAINT complaint_id IF NOT EXISTS FOR (n:Complaint) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT question_id IF NOT EXISTS FOR (n:Question) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT symptom_id IF NOT EXISTS FOR (n:Symptom) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT red_flag_id IF NOT EXISTS FOR (n:RedFlag) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT department_id IF NOT EXISTS FOR (n:Department) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT patient_ref IF NOT EXISTS FOR (n:Patient) REQUIRE n.ref IS UNIQUE",
    "CREATE CONSTRAINT visit_ref IF NOT EXISTS FOR (n:Visit) REQUIRE n.ref IS UNIQUE",
    "CREATE CONSTRAINT doctor_ref IF NOT EXISTS FOR (n:Doctor) REQUIRE n.ref IS UNIQUE",
    "CREATE CONSTRAINT term_key IF NOT EXISTS FOR (n:Term) REQUIRE n.key IS UNIQUE",
    "CREATE CONSTRAINT answer_ref IF NOT EXISTS FOR (n:Answer) REQUIRE n.ref IS UNIQUE",
    "CREATE CONSTRAINT row_ref IF NOT EXISTS FOR (n:ReportRow) REQUIRE n.ref IS UNIQUE",
    "CREATE CONSTRAINT referral_ref IF NOT EXISTS FOR (n:Referral) REQUIRE n.ref IS UNIQUE",
    "CREATE CONSTRAINT destination_ref IF NOT EXISTS FOR (n:Destination) REQUIRE n.ref IS UNIQUE",
)

LOAD_QUESTIONS = """
UNWIND $rows AS row
MERGE (c:Complaint {id: row.complaint})
SET c.version = row.version
MERGE (d:Department {id: row.department})
MERGE (c)-[:USUALLY_SEEN_IN]->(d)
WITH c, row
UNWIND row.questions AS item
MERGE (q:Question {id: item.id})
SET q.en = item.en, q.hi = item.hi, q.kind = item.kind, q.version = row.version
FOREACH (_ IN CASE WHEN item.kind = 'follow_up' THEN [1] ELSE [] END |
    MERGE (c)-[f:FOLLOW_UP]->(q) SET f.rank = item.rank)
FOREACH (_ IN CASE WHEN item.kind = 'associated' THEN [1] ELSE [] END |
    MERGE (s:Symptom {id: item.id}) MERGE (c)-[a:ASSOCIATED]->(s) SET a.rank = item.rank MERGE (s)-[:ASKED_BY]->(q))
FOREACH (_ IN CASE WHEN item.kind = 'red_flag' THEN [1] ELSE [] END |
    MERGE (r:RedFlag {id: item.id}) MERGE (c)-[x:SCREEN_FOR]->(r) SET x.rank = item.rank MERGE (r)-[:ASKED_BY]->(q))
"""

# Follow-ups first, then red-flag screening questions, then associated symptoms. The interview's own
# rules (red_flags.screen first, the 12-question cap, medicines and allergies last) stay in agent.py.
NEXT_QUESTION = """
MATCH (c:Complaint) WHERE c.id IN $complaints
CALL (c) {
    MATCH (c)-[f:FOLLOW_UP]->(q:Question) RETURN q, f.rank AS rank
    UNION
    MATCH (c)-[x:SCREEN_FOR]->(:RedFlag)-[:ASKED_BY]->(q:Question) RETURN q, 50 + x.rank AS rank
    UNION
    MATCH (c)-[a:ASSOCIATED]->(:Symptom)-[:ASKED_BY]->(q:Question) RETURN q, 100 + a.rank AS rank
}
WITH q, min(rank) AS rank WHERE NOT q.id IN $asked
RETURN q.id AS id, q.en AS en, q.hi AS hi, q.kind AS kind, rank
ORDER BY rank, id LIMIT 1
"""

DEPARTMENT_VOTES = """
MATCH (c:Complaint)-[:USUALLY_SEEN_IN]->(d:Department) WHERE c.id IN $complaints
RETURN d.id AS department, count(c) AS votes
"""

# FOREACH, not UNWIND, for terms and answers: an empty UNWIND would stop the rest of the query.
MERGE_VISIT = """
MERGE (p:Patient {ref: $patient_ref})
MERGE (v:Visit {ref: $visit_ref})
SET v.day = $day, v.department = $department, v.reviewed = $reviewed
MERGE (p)-[:HAD]->(v)
MERGE (d:Doctor {ref: $doctor_ref})
MERGE (v)-[:SEEN_BY]->(d)
FOREACH (term IN $terms |
    MERGE (t:Term {key: term.kind + ':' + term.code})
    SET t.kind = term.kind, t.code = term.code
    MERGE (v)-[:NOTED {source: term.source}]->(t))
FOREACH (answer IN $answers |
    MERGE (a:Answer {ref: answer.ref})
    SET a.turn = answer.turn, a.has_recording = answer.has_recording
    MERGE (v)-[:ANSWERED]->(a))
WITH v
UNWIND $rows AS row
MERGE (r:ReportRow {ref: row.ref})
SET r.index = row.index, r.flag = row.flag
MERGE (v)-[:REPORTED]->(r)
WITH r, row
UNWIND row.turns AS turn
MATCH (a:Answer {ref: $visit_ref + ':turn:' + toString(turn)})
MERGE (r)-[:CITES]->(a)
"""

# A referral: who sent it, where it went, its coded specialty and dates. No reason, question or patient.
MERGE_REFERRAL = """
MERGE (r:Referral {ref: $ref})
SET r.specialty = $specialty, r.priority = $priority, r.status = $status, r.open = $open,
    r.respond_by = $respond_by, r.day = $day
MERGE (f:Doctor {ref: $from_ref})
MERGE (f)-[:REFERRED]->(r)
WITH r
OPTIONAL MATCH (r)-[old:SENT_TO]->()
DELETE old
WITH DISTINCT r
MERGE (d:Destination {ref: $to_ref})
MERGE (r)-[:SENT_TO]->(d)
"""

# Only the referrals SQLite says this person may see ($refs). Overdue is worked out now, not when copied.
REFERRAL_NETWORK = """
MATCH (f:Doctor)-[:REFERRED]->(r:Referral)-[:SENT_TO]->(d:Destination)
WHERE r.ref IN $refs
RETURN r.ref AS ref, f.ref AS from_ref, d.ref AS to_ref, r.specialty AS specialty, r.open AS open,
       r.respond_by AS respond_by, r.priority AS priority, r.status AS status
ORDER BY ref
"""

HISTORY = """
MATCH (:Patient {ref: $patient_ref})-[:HAD]->(v:Visit)
OPTIONAL MATCH (v)-[n:NOTED]->(t:Term)
OPTIONAL MATCH (v)-[:SEEN_BY]->(d:Doctor)
RETURN v.ref AS visit_ref, v.day AS day, v.department AS department, v.reviewed AS reviewed, d.ref AS doctor_ref,
       collect(DISTINCT {kind: t.kind, code: t.code, source: n.source}) AS terms
ORDER BY day DESC
"""

EVIDENCE = """
MATCH (:Visit {ref: $visit_ref})-[:REPORTED]->(r:ReportRow)
OPTIONAL MATCH (r)-[:CITES]->(a:Answer)
RETURN r.index AS row, r.flag AS flag, collect(DISTINCT {turn: a.turn, has_recording: a.has_recording}) AS answers
ORDER BY row
"""


def question_rows(seed: dict) -> List[dict]:
    """The seed file as rows for LOAD_QUESTIONS (and for the fake)."""
    rows = []
    for complaint in seed["complaints"]:
        questions = []
        for kind, key in (("follow_up", "follow_ups"), ("associated", "associated"), ("red_flag", "red_flags")):
            for rank, item in enumerate(complaint.get(key, [])):
                questions.append({"id": item["id"], "en": item["en"], "hi": item["hi"], "kind": kind, "rank": rank})
        rows.append({"complaint": complaint["id"], "department": complaint["department"], "version": seed["version"], "questions": questions})
    return rows


class Neo4jGraph:
    """The real client. One driver per process, shared across threads, as the driver's docs advise."""

    def __init__(self, driver, database: str):
        self.driver = driver
        self.database = database
        self._constraints_done = False

    def _run(self, query: str, **params) -> List[dict]:
        try:
            records, _summary, _keys = self.driver.execute_query(query, params, database_=self.database)
        except Exception as error:  # the driver's own errors, a closed pool, a network failure
            # Only the type: a driver message can quote the query's parameters.
            raise GraphUnavailable(type(error).__name__) from None
        return [record.data() if hasattr(record, "data") else dict(record) for record in records]

    def _constraints(self) -> None:
        if not self._constraints_done:
            for statement in CONSTRAINTS:
                self._run(statement)
            self._constraints_done = True

    def load_questions(self, seed: dict) -> None:
        self._constraints()
        self._run(LOAD_QUESTIONS, rows=question_rows(seed))

    def next_question(self, complaints: Sequence[str], asked: Sequence[str]) -> Optional[dict]:
        found = self._run(NEXT_QUESTION, complaints=list(complaints), asked=list(asked))
        return found[0] if found else None

    def department_votes(self, complaints: Sequence[str]) -> Dict[str, int]:
        return {row["department"]: row["votes"] for row in self._run(DEPARTMENT_VOTES, complaints=list(complaints))}

    def merge_visit(self, visit: dict) -> None:
        self._constraints()
        self._run(MERGE_VISIT, **visit)

    def history(self, patient_ref: str) -> List[dict]:
        return self._run(HISTORY, patient_ref=patient_ref)

    def evidence(self, visit_ref: str) -> List[dict]:
        return self._run(EVIDENCE, visit_ref=visit_ref)

    def merge_referral(self, referral: dict) -> None:
        self._constraints()
        self._run(MERGE_REFERRAL, **referral)

    def referral_network(self, refs: Sequence[str]) -> List[dict]:
        return self._run(REFERRAL_NETWORK, refs=list(refs))

    def clear(self) -> None:
        # Only the projection's own labels. The question graph is reloaded from its seed file afterwards.
        self._run(
            "MATCH (n) WHERE n:Patient OR n:Visit OR n:Doctor OR n:Term OR n:Answer OR n:ReportRow OR n:Referral OR n:Destination DETACH DELETE n"
        )


_lock = threading.Lock()
_shared: Optional[Neo4jGraph] = None
_override: Optional[GraphClient] = None  # tests put a fake here


def use(fake: Optional[GraphClient]) -> None:
    """For tests: every caller gets this client instead of a real one. None restores normal behaviour."""
    global _override
    _override = fake


def client(db: sqlite3.Connection) -> Optional[GraphClient]:
    """The graph client, or None when Neo4j may not or can't be used. Never raises."""
    from backend import addons, settings_store

    try:
        if not addons.neo4j_ready(db):
            return None
    except sqlite3.Error:
        return None
    if _override is not None:
        return _override
    global _shared
    with _lock:
        if _shared is None:
            try:
                from neo4j import GraphDatabase  # optional: requirements-integrations.txt
            except ImportError:
                logger.warning("Neo4j is switched on but the neo4j package isn't installed")
                return None
            password = settings_store.api_key(db, "neo4j")
            try:
                driver = GraphDatabase.driver(settings.neo4j_uri, auth=(settings.neo4j_user, password), connection_timeout=5)
            except Exception as error:
                logger.warning("Couldn't set up the Neo4j driver: %s", type(error).__name__)
                return None
            _shared = Neo4jGraph(driver, settings.neo4j_database)
    return _shared
