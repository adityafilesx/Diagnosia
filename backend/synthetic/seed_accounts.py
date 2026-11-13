"""Makes synthetic doctors and patients with logins, so each tool can be tested by hand.

Everything here is made up: names come from short lists, phone numbers use a reserved
test pattern, and every email is @example.com. Development only. It refuses to run
with real patient data switched on, or outside the development environment.

    python -m backend.synthetic.seed_accounts            # creates what's missing
    python -m backend.synthetic.seed_accounts --patients 80

The logins are written to next to the database, in backend/storage/synthetic/ (git-ignored), as
CSV files and a short readable list. The same seed always makes the same people.
"""
import argparse
import csv
import random
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Dict, List

from fastapi.testclient import TestClient

from backend import ratelimit
from backend.app import app
from backend.config import settings
from backend.db import connect, init_db
from backend.records import staff
from backend.records.store import now_iso

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


def output_dir() -> Path:
    return settings.db_path.parent / "synthetic"


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
    # Dozens of sign-ups from this one process would trip the per-address limit meant for the public.
    with ratelimit.suspended():
        return _run(patients, with_login, seed)


def _run(patients: int, with_login: int, seed: int) -> int:
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
        print("The synthetic hospital already exists, so nothing was added. Rewriting the login list from the database.")
        return export_logins()

    return export_logins()


def export_logins() -> int:
    """Writes the logins from the database itself, so the files always match who can really sign in.

    They go next to the database (backend/storage/synthetic/ by default), so seeding a
    different database never overwrites another one's list.
    """
    out = output_dir()
    out.mkdir(parents=True, exist_ok=True)
    db = connect()
    try:
        users = db.execute(
            "SELECT id, email, first_name, last_name, role, account_status FROM users WHERE email LIKE '%@example.com' ORDER BY id"
        ).fetchall()
        charts = db.execute(
            """
            SELECT p.id, p.first_name, p.last_name, p.date_of_birth, p.sex, p.preferred_language, u.email AS login,
                   (SELECT d.email FROM care_team c JOIN users d ON d.id = c.user_id
                    WHERE c.patient_id = p.id AND c.role = 'clinician' AND c.revoked_at IS NULL ORDER BY c.granted_at LIMIT 1) AS owner,
                   (SELECT reason FROM encounters WHERE patient_id = p.id ORDER BY started_at LIMIT 1) AS reason,
                   (SELECT substance FROM allergies WHERE patient_id = p.id LIMIT 1) AS allergy
            FROM patients p LEFT JOIN users u ON u.id = p.user_id ORDER BY p.created_at, p.id
            """
        ).fetchall()
        specialty = {item["email"]: item for item in _doctor_rows(random.Random(0))}
    finally:
        db.close()

    with open(out / "accounts.csv", "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["role", "email", "password", "name", "status", "specialty", "note"])
        for user in users:
            known = specialty.get(user["email"], {})
            name = f"Dr {user['first_name']} {user['last_name']}" if user["role"] == "doctor" else f"{user['first_name']} {user['last_name']}"
            writer.writerow([user["role"], user["email"], PASSWORD, name, user["account_status"], known.get("specialty", ""), known.get("note", "")])
    with open(out / "patients.csv", "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["patient_id", "name", "date_of_birth", "sex", "language", "reason_for_visit", "allergy", "login_email", "chart_owner"])
        for chart in charts:
            writer.writerow([
                chart["id"], f"{chart['first_name']} {chart['last_name']}", chart["date_of_birth"], chart["sex"],
                chart["preferred_language"], chart["reason"] or "", chart["allergy"] or "", chart["login"] or "", chart["owner"] or "",
            ])
    staff_users = [user for user in users if user["role"] == "doctor"]
    patient_users = [user for user in users if user["role"] == "patient"]
    lines = [f"Synthetic logins. Shared password for every account: {PASSWORD}", "", "STAFF"]
    for user in staff_users:
        known = specialty.get(user["email"], {})
        lines.append(f"  {user['email']:30} {known.get('specialty') or '-':18} {user['account_status']}")
    lines += ["", f"PATIENTS WITH A LOGIN ({len(patient_users)}; the full list is in accounts.csv)"]
    lines += [f"  {user['email']:30} {user['first_name']} {user['last_name']}" for user in patient_users[:10]]
    (out / "README.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"{len(users)} logins and {len(charts)} charts written to {out} (git-ignored).")
    return 0


def main(arguments=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--patients", type=int, default=60, help="how many patient records to make")
    parser.add_argument("--with-login", type=int, default=30, help="how many of those also get a patient login")
    parser.add_argument("--seed", type=int, default=2026, help="same seed, same people")
    parser.add_argument("--export-only", action="store_true", help="only rewrite the login list from the database")
    args = parser.parse_args(arguments)
    if args.export_only:
        init_db()
        return export_logins()
    return run(args.patients, args.with_login, args.seed)


if __name__ == "__main__":
    raise SystemExit(main())
