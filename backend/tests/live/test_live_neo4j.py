"""Real Neo4j, with made-up data only. Off unless asked for.

    CURAI_LIVE_TESTS=1 .venv/bin/python -m pytest -m live backend/tests/live/test_live_neo4j.py -s

Needs the local server from docker-compose.integrations.yml and NEO4J_URI, NEO4J_USER and NEO4J_PASSWORD in
.env. It loads the question graph, compares the real next-question order with the in-memory fake the
unit tests use, writes and reads back made-up visits under a "livetest" prefix, and removes them after.
"""
import os
import time
import uuid

import pytest

from backend.config import settings
from backend.diagnofast import guidance
from backend.integrations import graph
from backend.tests.fake_graph import FakeGraph

pytestmark = pytest.mark.live
ENABLED = os.environ.get("CURAI_LIVE_TESTS") == "1"
TIMINGS = {}


@pytest.fixture(scope="module")
def real():
    if not ENABLED:
        pytest.skip("Set CURAI_LIVE_TESTS=1")
    if not (settings.neo4j_uri and settings.neo4j_api_key):
        pytest.fail("BLOCKED_MISSING_CREDENTIALS: NEO4J_URI and NEO4J_PASSWORD")
    from neo4j import GraphDatabase

    driver = GraphDatabase.driver(settings.neo4j_uri, auth=(settings.neo4j_user, settings.neo4j_api_key))
    driver.verify_connectivity()
    client = graph.Neo4jGraph(driver, settings.neo4j_database)
    yield client
    client._run("MATCH (n) WHERE n.ref STARTS WITH 'livetest' DETACH DELETE n")  # visits, referrals, doctors, destinations
    driver.close()
    print("\nNeo4j query timings (ms):", {name: round(ms, 1) for name, ms in TIMINGS.items()})


def timed(name, call, *args):
    started = time.perf_counter()
    result = call(*args)
    TIMINGS[name] = (time.perf_counter() - started) * 1000
    return result


def counts(client):
    return client._run(
        "MATCH (n) WHERE n:Complaint OR n:Question OR n:Symptom OR n:RedFlag OR n:Department "
        "OPTIONAL MATCH (n)-[r]->() RETURN count(DISTINCT n) AS nodes, count(r) AS relationships"
    )[0]


def test_loading_the_question_graph_twice_changes_nothing(real):
    timed("load_questions (first)", real.load_questions, guidance.seed())
    before = counts(real)
    timed("load_questions (again)", real.load_questions, guidance.seed())
    assert counts(real) == before
    assert before["nodes"] > 50


@pytest.mark.parametrize("complaint", [c["id"] for c in guidance.seed()["complaints"]])
def test_the_real_next_question_order_matches_the_fake(real, complaint):
    fake = FakeGraph()
    fake.load_questions(guidance.seed())
    real.load_questions(guidance.seed())
    asked_real, asked_fake = [], []
    started = time.perf_counter()
    while True:
        got, want = real.next_question([complaint], asked_real), fake.next_question([complaint], asked_fake)
        if want is None:
            assert got is None
            break
        assert (got["id"], got["kind"], got["en"], got["hi"]) == (want["id"], want["kind"], want["en"], want["hi"])
        asked_real.append(got["id"])
        asked_fake.append(want["id"])
    TIMINGS[f"next_question walk ({complaint}, {len(asked_real)} steps)"] = (time.perf_counter() - started) * 1000


def test_the_order_is_follow_ups_then_red_flags_then_associated(real):
    real.load_questions(guidance.seed())
    seen, asked = [], []
    while (found := real.next_question(["fever"], asked)) is not None:
        seen.append(found["kind"])
        asked.append(found["id"])
    assert seen == sorted(seen, key=["follow_up", "red_flag", "associated"].index)
    assert seen.count("follow_up") == 6 and seen.count("red_flag") == 2 and seen.count("associated") == 3


def test_department_votes(real):
    real.load_questions(guidance.seed())
    votes = timed("department_votes", real.department_votes, ["ear_problem", "fever"])
    assert votes == {"ent": 1, "general_physician": 1}


def made_up_visit(patient_ref, visit_ref, terms, rows):
    return {
        "patient_ref": patient_ref, "visit_ref": visit_ref, "doctor_ref": "livetest:doctor:1", "day": "2026-11-22",
        "department": "general_physician", "reviewed": False, "terms": terms,
        "answers": [{"ref": f"{visit_ref}:turn:{n}", "turn": n, "has_recording": n == 1} for n in (1, 2, 3)],
        "rows": rows,
    }


def test_visits_merge_and_read_back_including_one_with_no_medicines_or_allergies(real):
    patient = f"livetest:patient:{uuid.uuid4().hex[:8]}"
    first = made_up_visit(patient, f"livetest:{uuid.uuid4().hex[:8]}", [
        {"kind": "complaint", "code": "fever", "source": "patient"},
        {"kind": "medicine", "code": "metformin", "source": "patient"},
        {"kind": "allergy", "code": "penicillin", "source": "patient"},
    ], [{"ref": "x:row:0", "index": 0, "flag": "NOT_ASSESSED", "turns": [1, 3]}, {"ref": "x:row:1", "index": 1, "flag": "NORMAL", "turns": [2]}])
    first["rows"] = [{**row, "ref": f"{first['visit_ref']}:row:{row['index']}"} for row in first["rows"]]
    # No medicines or allergies, and no report rows: the FOREACH and empty-UNWIND paths.
    second = made_up_visit(patient, f"livetest:{uuid.uuid4().hex[:8]}", [], [])
    second["day"] = "2026-11-20"
    timed("merge_visit", real.merge_visit, first)
    real.merge_visit(second)
    real.merge_visit(first)  # idempotent
    history = timed("history", real.history, patient)
    assert [visit["visit_ref"] for visit in history] == [first["visit_ref"], second["visit_ref"]]
    codes = {(term["kind"], term["code"]) for term in history[0]["terms"] if term.get("code")}
    assert codes == {("complaint", "fever"), ("medicine", "metformin"), ("allergy", "penicillin")}
    assert [term for term in history[1]["terms"] if term.get("code")] == []
    evidence = timed("evidence", real.evidence, first["visit_ref"])
    assert [(item["row"], sorted(a["turn"] for a in item["answers"])) for item in evidence] == [(0, [1, 3]), (1, [2])]
    assert real.evidence(second["visit_ref"]) == []
    fake = FakeGraph()
    fake.merge_visit(first)
    fake.merge_visit(second)
    assert [(i["row"], sorted(a["turn"] for a in i["answers"])) for i in fake.evidence(first["visit_ref"])] == [(0, [1, 3]), (1, [2])]
    assert [v["visit_ref"] for v in fake.history(patient)] == [v["visit_ref"] for v in history]


def test_referrals_merge_and_read_back_like_the_fake(real):
    refs = [f"livetest:referral:{uuid.uuid4().hex[:8]}" for _ in range(2)]
    rows = [
        {"ref": refs[0], "from_ref": "livetest:doctor:1", "to_ref": "livetest:org:a", "specialty": "cardiology", "priority": "routine",
         "status": "sent", "open": True, "respond_by": "2026-11-01", "day": "2026-10-20"},
        {"ref": refs[1], "from_ref": "livetest:doctor:1", "to_ref": "livetest:doctor:2", "specialty": "ent", "priority": "urgent",
         "status": "closed", "open": False, "respond_by": "2026-12-01", "day": "2026-11-20"},
    ]
    fake = FakeGraph()
    for row in rows:
        timed("merge_referral", real.merge_referral, row)
        fake.merge_referral(row)
    real.merge_referral({**rows[0], "to_ref": "livetest:org:b"})  # redirected: the old destination link goes
    fake.merge_referral({**rows[0], "to_ref": "livetest:org:b"})
    got = timed("referral_network", real.referral_network, refs + ["livetest:referral:not-there"])
    assert got == fake.referral_network(refs + ["livetest:referral:not-there"])
    assert {item["ref"]: item["to_ref"] for item in got} == {refs[0]: "livetest:org:b", refs[1]: "livetest:doctor:2"}
