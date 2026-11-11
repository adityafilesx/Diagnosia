"""Makes synthetic doctors and patients with logins, so each tool can be tested by hand.

Everything here is made up: names come from short lists, phone numbers use a reserved
test pattern, and every email is @example.com. Development only. It refuses to run
with real patient data switched on, or outside the development environment.

    python -m backend.synthetic.seed_accounts            # creates what's missing
    python -m backend.synthetic.seed_accounts --patients 80

The logins are written to backend/storage/synthetic/ (git-ignored), as a CSV and a
short readable list. The same seed always makes the same people.
"""
import argparse
import csv
import random
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Dict, List

from fastapi.testclient import TestClient

from backend.app import app
from backend.config import settings
from backend.db import connect, init_db
from backend.records import staff
from backend.records.store import now_iso

OUTPUT_DIR = Path(__file__).resolve().parents[1] / "storage" / "synthetic"
# One shared password keeps manual testing quick. These accounts exist only on a local,
# development, synthetic database.
PASSWORD = "Synthetic-demo-only-1"
ORGANIZATION = "Synthetic Test Hospital"
CONSENTS = ("ai_processing", "ai_scribe", "referral_sharing")

# The six DiagnoFast forms, so every specialty has doctors to receive its intakes.
SPECIALTIES = {
    "general_physician": "General Medicine",
    "dermatologist": "Dermatology",
    "cardiologist": "Cardiology",
    "orthopedist": "Orthopedics",
    "ent_specialist": "ENT",
    "pediatrician": "Pediatrics",
}
DOCTOR_FIRST = ["Meera", "Arjun", "Farah", "Sanjay", "Priya", "Vikram", "Ananya", "Rohit", "Kavita", "Imran", "Neha", "Suresh"]
DOCTOR_LAST = ["Iyer", "Sharma", "Khan", "Reddy", "Nair", "Singh", "Das", "Patel", "Joshi", "Mehta", "Banerjee", "Gupta"]
PATIENT_FIRST_F = ["Sunita", "Lakshmi", "Pooja", "Geeta", "Anjali", "Rekha", "Fatima", "Savitri", "Deepa", "Radha", "Meena", "Shanti"]
PATIENT_FIRST_M = ["Ravi", "Mohan", "Ramesh", "Aarav", "Sunil", "Abdul", "Kishore", "Manoj", "Dinesh", "Harish", "Gopal", "Vijay"]
PATIENT_LAST = ["Kumar", "Devi", "Yadav", "Verma", "Pillai", "Chauhan", "Ansari", "Rao", "Mishra", "Thakur", "Bose", "Kaur"]

# Common reasons for a visit in India, by rough share. They give DiagnoFast and ClinScribe
# realistic starting points. They are plain visit reasons, not diagnoses.
VISIT_REASONS = [
    ("Fever and body ache for three days", 14), ("Diabetes follow-up", 12), ("High blood pressure review", 11),
    ("Cough and cold for one week", 10), ("Stomach pain and loose motions", 8), ("Joint pain in the knees", 8),
    ("Itchy skin rash", 6), ("Headache and dizziness", 6), ("Breathlessness on climbing stairs", 5),
    ("Ear pain and blocked nose", 4), ("Child with fever and cough", 6), ("Back pain after lifting", 5),
    ("Burning urine", 3), ("Pregnancy check-up", 2),
]
ALLERGIES = [("Penicillin", "Rash", "moderate"), ("Sulfa drugs", "Itching", "mild"), ("Peanuts", "Swelling of lips", "severe"), ("Dust", "Sneezing", "mild")]


def _pick(rng: random.Random, options: List[tuple]) -> str:
    return rng.choices([item for item, _ in options], weights=[weight for _, weight in options])[0]


def _check(response, expected=(200, 201, 204)):
    if response.status_code not in expected:
        raise RuntimeError(f"{response.request.method} {response.request.url.path} failed: {response.status_code} {response.text[:200]}")
    return response.json() if response.content else None


def _register(email: str, first: str, last: str, role: str) -> int:
    with TestClient(app) as client:
        response = client.post(
            "/api/auth/register",
            json={"first_name": first, "last_name": last, "email": email, "password": PASSWORD, "role": role},
        )
        if response.status_code == 409:
            return 0  # already made on an earlier run
        return _check(response)["id"]


def _doctor_rows(rng: random.Random) -> List[dict]:
    rows = []
    forms = list(SPECIALTIES)
    for index in range(12):
        form = forms[index % len(forms)]
        rows.append({
            "role": "doctor", "email": f"doctor{index + 1:02d}@example.com",
            "first_name": DOCTOR_FIRST[index], "last_name": DOCTOR_LAST[index],
            "specialty": SPECIALTIES[form], "form_id": form,
            "profession": "doctor", "note": "Administrator of the hospital" if index == 0 else "Verified doctor, same hospital",
        })
    rows.append({
        "role": "doctor", "email": "lab.reviewer@example.com", "first_name": "Lata", "last_name": "Menon",
        "specialty": "Laboratory", "form_id": "", "profession": "laboratory_professional", "note": "Reviews lab results",
    })
    rows.append({
        "role": "doctor", "email": "pending.doctor@example.com", "first_name": "Pending", "last_name": "Doctor",
        "specialty": "", "form_id": "", "profession": "doctor", "note": "NOT verified: tests the pending-staff screens",
    })
    return rows


def _patient_rows(rng: random.Random, count: int, with_login: int) -> List[dict]:
    rows = []
    for index in range(count):
        female = rng.random() < 0.5
        first = rng.choice(PATIENT_FIRST_F if female else PATIENT_FIRST_M)
        last = rng.choice(PATIENT_LAST)
        child = rng.random() < 0.12
        age = rng.randint(2, 14) if child else rng.randint(18, 82)
        born = date.today() - timedelta(days=age * 365 + rng.randint(0, 364))
        rows.append({
            "role": "patient" if index < with_login else "record_only",
            "email": f"patient{index + 1:03d}@example.com" if index < with_login else "",
            "first_name": first, "last_name": last, "sex": "female" if female else "male",
            "date_of_birth": born.isoformat(), "age": age,
            "language": rng.choice(["hi-IN", "hi-IN", "en-IN"]),
            "phone": f"+91 90000 {index + 1:05d}",  # reserved-looking, not a real number
            "reason": "Child with fever and cough" if child and rng.random() < 0.5 else _pick(rng, VISIT_REASONS),
            "allergy": rng.choice(ALLERGIES) if rng.random() < 0.2 else None,
        })
    return rows


def run(patients: int, with_login: int, seed: int) -> int:
    if settings.environment != "development" or settings.allow_real_patient_data:
        print("Synthetic accounts only run in development, without real patient data.", file=sys.stderr)
        return 1
    rng = random.Random(seed)
    init_db()
    doctors = _doctor_rows(rng)
    people = _patient_rows(rng, patients, min(with_login, patients))

    db = connect()
    try:
        done = db.execute("SELECT id FROM organizations WHERE name = ?", (ORGANIZATION,)).fetchone()
    finally:
        db.close()

    for doctor in doctors:
        doctor["id"] = _register(doctor["email"], doctor["first_name"], doctor["last_name"], "doctor")
    if not done:
        db = connect()
        try:
            organization_id = staff.operator_verify_organization(
                db, doctors[0]["email"], ORGANIZATION, "hospital", "Synthetic seed", "SYNTHETIC", "seed_accounts"
            )
            admin_id = db.execute("SELECT id FROM users WHERE email = ?", (doctors[0]["email"],)).fetchone()["id"]
            for doctor in doctors[1:-1]:  # the last one stays pending on purpose
                user = db.execute("SELECT id FROM users WHERE email = ?", (doctor["email"],)).fetchone()
                staff.record_decision(
                    db, user["id"], "verified", None, "operator:seed_accounts", evidence_type="Synthetic seed",
                    evidence_reference="SYNTHETIC", verified_profession=doctor["profession"],
                )
                db.execute(
                    "INSERT INTO organization_members (organization_id, user_id, role, added_by, created_at) VALUES (?, ?, 'staff', ?, ?)",
                    (organization_id, user["id"], admin_id, now_iso()),
                )
            db.commit()
        finally:
            db.close()

        # Patients: each record is made by one doctor. The first `with_login` are then claimed
        # by a patient account, so the patient portal and the doctor chart show the same person.
        with TestClient(app) as http:
            clients: Dict[str, TestClient] = {}
            login_doctors = [item for item in doctors if item["form_id"]]
            for index, person in enumerate(people):
                owner = login_doctors[index % len(login_doctors)]
                if owner["email"] not in clients:
                    clients[owner["email"]] = TestClient(app)
                    _check(clients[owner["email"]].post("/api/auth/login", json={"email": owner["email"], "password": PASSWORD}))
                doctor = clients[owner["email"]]
                record = _check(doctor.post("/api/patients", json={
                    "first_name": person["first_name"], "last_name": person["last_name"],
                    "date_of_birth": person["date_of_birth"], "sex": person["sex"],
                    "phone": person["phone"], "preferred_language": person["language"],
                }))
                person["patient_id"] = record["id"]
                person["doctor_email"] = owner["email"]
                for purpose in CONSENTS:
                    _check(doctor.post(f"/api/patients/{record['id']}/consents", json={"purpose": purpose}))
                _check(doctor.post(f"/api/patients/{record['id']}/encounters", json={"reason": person["reason"]}))
                if person["allergy"]:
                    substance, reaction, severity = person["allergy"]
                    _check(doctor.post(f"/api/patients/{record['id']}/allergies", json={"substance": substance, "reaction": reaction, "severity": severity}))
                if person["role"] == "patient":
                    _register(person["email"], person["first_name"], person["last_name"], "patient")
                    code = _check(doctor.post(f"/api/patients/{record['id']}/share-codes", json={"purpose": "claim"}))["code"]
                    with TestClient(app) as patient:
                        _check(patient.post("/api/auth/login", json={"email": person["email"], "password": PASSWORD}))
                        _check(patient.post("/api/patients/join", json={"code": code}))
            for client in clients.values():
                client.close()
            http.close()
        print(f"Created {len(doctors)} staff accounts and {len(people)} patient records.")
    else:
        print("The synthetic hospital already exists, so nothing was added. Your earlier logins are still in")
        print(f"{OUTPUT_DIR}. To make new ones, use a fresh database (set DIAGNOSIA_DB to a new file).")
        return 0

    return _write_files(doctors, people)


def _write_files(doctors: List[dict], people: List[dict]) -> int:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    accounts = doctors + [item for item in people if item["role"] == "patient"]
    with open(OUTPUT_DIR / "accounts.csv", "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["role", "email", "password", "name", "specialty_or_visit_reason", "note"])
        for item in doctors:
            writer.writerow(["doctor", item["email"], PASSWORD, f"Dr {item['first_name']} {item['last_name']}", item["specialty"], item["note"]])
        for item in people:
            if item["role"] == "patient":
                writer.writerow(["patient", item["email"], PASSWORD, f"{item['first_name']} {item['last_name']}", item["reason"], f"Chart owner: {item['doctor_email']}"])
    with open(OUTPUT_DIR / "patients.csv", "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["patient_id", "name", "age", "sex", "language", "reason_for_visit", "allergy", "has_login", "login_email", "chart_owner"])
        for item in people:
            writer.writerow([
                item["patient_id"], f"{item['first_name']} {item['last_name']}", item["age"], item["sex"], item["language"],
                item["reason"], item["allergy"][0] if item["allergy"] else "", item["role"] == "patient", item["email"], item["doctor_email"],
            ])
    lines = [f"Synthetic logins. Shared password for every account: {PASSWORD}", "", "STAFF"]
    lines += [f"  {item['email']:30} {item['specialty'] or '-':18} {item['note']}" for item in doctors]
    lines += ["", "PATIENTS WITH A LOGIN (first 10 of the CSV)"]
    lines += [f"  {item['email']:30} {item['first_name']} {item['last_name']} ({item['reason']})" for item in [p for p in people if p['role'] == 'patient'][:10]]
    (OUTPUT_DIR / "README.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Logins written to {OUTPUT_DIR} ({len(accounts)} accounts). That folder is git-ignored.")
    return 0


def main(arguments=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--patients", type=int, default=60, help="how many patient records to make")
    parser.add_argument("--with-login", type=int, default=30, help="how many of those also get a patient login")
    parser.add_argument("--seed", type=int, default=2026, help="same seed, same people")
    args = parser.parse_args(arguments)
    return run(args.patients, args.with_login, args.seed)


if __name__ == "__main__":
    raise SystemExit(main())
