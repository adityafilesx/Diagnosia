"""Creates waiting DiagnoFast interview links for the test patients, with a script of what to answer.

    python -m backend.synthetic.diagnofast_links                # 2 interviews per specialty
    python -m backend.synthetic.diagnofast_links --per-form 5

Run it after the synthetic accounts exist (`python -m backend.synthetic.serve` or `seed_accounts`), against
the same database the server uses. Each link serves one interview, expires after a day, and belongs to the specialty's test doctor, so
that doctor sees the report in their queue. The script is written next to the database, in
backend/storage/synthetic/diagnofast_script.md (git-ignored). Open a link, then type or speak the answers
in the script, and compare with what the interview and the doctor's report captured.

The links are made fresh each run, so they are not committed. The answers come from the frozen dev split.
"""
import argparse
import random
import sys
from urllib.parse import parse_qs, urlparse

from fastapi.testclient import TestClient

from backend.app import app
from backend.config import settings
from backend.db import init_db
from backend.synthetic import diagnofast_eval
from backend.synthetic.seed_accounts import PASSWORD, output_dir

DOCTORS = {
    "general_physician": "doctor01@example.com", "dermatologist": "doctor02@example.com", "cardiology": "doctor03@example.com",
    "orthopedics": "doctor04@example.com", "ent": "doctor05@example.com", "pediatrics": "doctor06@example.com",
}
NAMES = ["Asha Verma", "Ravi Patel", "Sunita Rao", "Imran Ansari", "Lakshmi Nair", "Vijay Singh", "Meena Das", "Arjun Yadav"]


def _pick(items, per_form: int, rng: random.Random) -> list:
    """A mix per specialty: an ordinary one, an urgent one, and ones that plant a negated or history mention."""
    chosen = []
    for form_id in DOCTORS:
        pool = [item for item in items if item["form_id"] == form_id]
        order = ["clean", "urgent", "negated", "history"]
        for slot in range(per_form):
            kind = order[slot % len(order)]
            matching = [
                item for item in pool
                if (kind == "urgent" and item["expect"]["urgent"])
                or (kind in ("negated", "history") and item["trap"] == kind and not item["expect"]["urgent"])
                or (kind == "clean" and item["trap"] is None and not item["expect"]["urgent"])
            ]
            if matching:
                chosen.append(rng.choice(matching))
    return chosen


def run(per_form: int = 2, seed: int = 7) -> int:
    if settings.environment != "development" or settings.allow_real_patient_data:
        print("Test interview links only run in development, without real patient data.", file=sys.stderr)
        return 1
    init_db()
    rng = random.Random(seed)
    items = diagnofast_eval.load("interviews", "dev")
    lines = ["# DiagnoFast test interviews", "", "Open each link (it works once), choose the language shown, and answer in order.",
             "Made-up patients only. Not clinician reviewed. See backend/tests/ai_eval/diagnofast/v1/DATASHEET.md.", ""]
    count = 0
    sessions = {}
    for number, item in enumerate(_pick(items, per_form, rng), start=1):
        email = DOCTORS[item["form_id"]]
        if email not in sessions:
            sessions[email] = TestClient(app)
            login = sessions[email].post("/api/auth/login", json={"email": email, "password": PASSWORD})
            if login.status_code != 200:
                print(f"Couldn't sign in as {email}. Run `python -m backend.synthetic.serve` first to make the test accounts.", file=sys.stderr)
                return 1
        name = NAMES[(number - 1) % len(NAMES)]
        response = sessions[email].post("/api/diagnofast/intakes", json={"form_id": item["form_id"], "patient_name": name})
        if response.status_code != 201:
            print(f"Couldn't create an interview: {response.status_code} {response.text[:120]}", file=sys.stderr)
            return 1
        token = parse_qs(urlparse(response.json()["link"]).query)["token"][0]
        expect = item["expect"]
        if expect["urgent"]:
            outcome = f"Must stop as urgent at answer {expect['at_turn'] + 1} ({', '.join(expect['labels'])}), and the patient is sent to reception."
        elif item["trap"]:
            outcome = f"Must NOT stop: it mentions a {item['trap']} symptom that is not happening now. Then it should finish normally."
        else:
            outcome = "Should finish normally and capture the values below."
        lines += [f"## {number}. {item['form_id']}, {name}, language {item['language']} ({item['answer_style']})", "",
                  f"- Doctor: {email} (password {PASSWORD})", f"- Link: /intake.html?token={token}", f"- Expected: {outcome}", "", "| # | Question | Answer to give |", "|---|---|---|"]
        for position, turn in enumerate(item["turns"], start=1):
            lines.append(f"| {position} | {turn['question']} | {turn['answer']} |")
        if not expect["urgent"]:
            lines += ["", "Values the report should capture:", ""] + [f"- {key}: {spec['value']}" for key, spec in item["gold"].items()]
        lines.append("")
        count += 1
    for client in sessions.values():
        client.close()
    out = output_dir()
    out.mkdir(parents=True, exist_ok=True)
    (out / "diagnofast_script.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Made {count} waiting interviews. Script: {out / 'diagnofast_script.md'}")
    return 0


def main(arguments=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--per-form", type=int, default=2)
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args(arguments)
    return run(args.per_form, args.seed)


if __name__ == "__main__":
    raise SystemExit(main())
