"""An in-memory stand-in for Neo4j with the same named methods as backend.integrations.graph.Neo4jGraph.

It answers the same questions the Cypher in graph.py asks, so tests check the app's use of the graph
without a server. It proves nothing about the Cypher itself; the optional live test does that.
"""
from typing import Dict, List, Optional, Sequence

from backend.integrations.graph import GraphUnavailable, question_rows

RANK_OFFSET = {"follow_up": 0, "red_flag": 50, "associated": 100}


class FakeGraph:
    def __init__(self, down: bool = False):
        self.down = down
        self.rows: List[dict] = []
        self.visits: Dict[str, dict] = {}
        self.referrals: Dict[str, dict] = {}
        self.calls: List[str] = []
        self.loads = 0

    def _check(self, name: str) -> None:
        self.calls.append(name)
        if self.down:
            raise GraphUnavailable("ServiceUnavailable")

    def load_questions(self, seed: dict) -> None:
        self._check("load_questions")
        self.loads += 1
        self.rows = question_rows(seed)
        # As MERGE (q:Question {id}) does: one node per ID, so the last wording loaded wins everywhere.
        latest = {item["id"]: item for row in self.rows for item in row["questions"]}
        for row in self.rows:
            row["questions"] = [{**item, "en": latest[item["id"]]["en"], "hi": latest[item["id"]]["hi"]} for item in row["questions"]]

    def next_question(self, complaints: Sequence[str], asked: Sequence[str]) -> Optional[dict]:
        self._check("next_question")
        ranked = {}
        for row in self.rows:
            if row["complaint"] not in complaints:
                continue
            for item in row["questions"]:
                rank = RANK_OFFSET[item["kind"]] + item["rank"]
                if item["id"] not in ranked or rank < ranked[item["id"]][0]:
                    ranked[item["id"]] = (rank, item)
        left = sorted((value for key, value in ranked.items() if key not in asked), key=lambda pair: (pair[0], pair[1]["id"]))
        if not left:
            return None
        rank, item = left[0]
        return {"id": item["id"], "en": item["en"], "hi": item["hi"], "kind": item["kind"], "rank": rank}

    def department_votes(self, complaints: Sequence[str]) -> Dict[str, int]:
        self._check("department_votes")
        votes: Dict[str, int] = {}
        for row in self.rows:
            if row["complaint"] in complaints:
                votes[row["department"]] = votes.get(row["department"], 0) + 1
        return votes

    def merge_visit(self, visit: dict) -> None:
        self._check("merge_visit")
        self.visits[visit["visit_ref"]] = visit

    def history(self, patient_ref: str) -> List[dict]:
        self._check("history")
        found = [visit for visit in self.visits.values() if visit["patient_ref"] == patient_ref]
        return [
            {"visit_ref": visit["visit_ref"], "day": visit["day"], "department": visit["department"], "reviewed": visit["reviewed"],
             "doctor_ref": visit["doctor_ref"], "terms": [{"kind": t["kind"], "code": t["code"], "source": t["source"]} for t in visit["terms"]]}
            for visit in sorted(found, key=lambda visit: visit["day"], reverse=True)
        ]

    def evidence(self, visit_ref: str) -> List[dict]:
        self._check("evidence")
        visit = self.visits.get(visit_ref)
        if not visit:
            return []
        answers = {answer["turn"]: answer for answer in visit["answers"]}
        return [
            {"row": row["index"], "flag": row["flag"],
             "answers": [{"turn": turn, "has_recording": answers[turn]["has_recording"]} for turn in row["turns"] if turn in answers]}
            for row in sorted(visit["rows"], key=lambda row: row["index"])
        ]

    def merge_referral(self, referral: dict) -> None:
        self._check("merge_referral")
        self.referrals[referral["ref"]] = dict(referral)

    def referral_network(self, refs: Sequence[str]) -> List[dict]:
        self._check("referral_network")
        keys = ("ref", "from_ref", "to_ref", "specialty", "open", "respond_by", "priority", "status")
        return [{key: self.referrals[ref][key] for key in keys} for ref in sorted(refs) if ref in self.referrals]

    def clear(self) -> None:
        self._check("clear")
        self.visits = {}
        self.referrals = {}
