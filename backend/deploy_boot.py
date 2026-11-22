"""Gets a judge-mode host ready, on every boot, before the server starts. See docs/DEPLOY_RENDER.md.

Render's free tier wipes the disk on every restart, redeploy and spin-down, so each boot starts with
an empty database. This puts back what a judge needs, and is safe to run again on a full one:

1. Copies the document key ring from the host's secret file to a folder only this user can read
   (a host's secret files may be readable by others, and the key ring must not be).
2. Creates or upgrades the database (the numbered migrations).
3. Seeds the made-up staff and patients, if they are not there.
4. Turns every tool on and the Sarvam switch on, as Settings would.
5. Records the Sarvam terms sign-off ONLY when DIAGNOSIA_SARVAM_SIGNED_OFF_BY names the person who
   confirmed the Sarvam workspace keeps no data and does not train on it. It is that person's decision;
   this only writes it down. Without the name, Sarvam stays off and the earlier voices are used.

    python -m backend.deploy_boot            # on every boot, before the server starts
    python -m backend.deploy_boot --build    # in the build: steps 2 to 5, no key ring

Seeding hashes dozens of passwords, which takes minutes on the free tier's 0.1 CPU. Run in the build,
the seeded database becomes part of the deployed files, so every boot (and every wake from sleep)
starts from it and only checks it is there.

With judge mode off it seeds nothing and succeeds, so switching judge mode off really takes the demo down.
"""
import argparse
import os
import shutil
import sys
from pathlib import Path

from backend import safety, settings_store
from backend.config import judge_mode_active, settings
from backend.db import connect, init_db
from backend.private_files import create_private_dir, make_private
from backend.records.store import dumps, now_iso

KEY_SOURCE = "DIAGNOSIA_DOCUMENT_KEY_SOURCE"
SIGNED_OFF_BY = "DIAGNOSIA_SARVAM_SIGNED_OFF_BY"
SEED_PATIENTS = "DIAGNOSIA_DEMO_PATIENTS"
SARVAM_DECISION = (
    "Sarvam workspace set to zero data retention and opted out of model training, confirmed by the signer "
    "and recorded at boot from the host's DIAGNOSIA_SARVAM_SIGNED_OFF_BY"
)


def copy_key_ring() -> bool:
    source = os.environ.get(KEY_SOURCE, "").strip()
    if not source:
        return True  # the key ring is already where DIAGNOSIA_DOCUMENT_KEY_FILE says
    source_path, target = Path(source), Path(settings.document_key_file)
    if not settings.document_key_file:
        print(f"{KEY_SOURCE} is set, but DIAGNOSIA_DOCUMENT_KEY_FILE does not say where to put it.", file=sys.stderr)
        return False
    if not source_path.is_file():
        print(f"{KEY_SOURCE} names a file that does not exist. Upload the key ring as a secret file.", file=sys.stderr)
        return False
    create_private_dir(target.parent)
    shutil.copyfile(source_path, target)
    make_private(target)
    return True


def _admin_id(db) -> int:
    row = db.execute(
        "SELECT user_id FROM organization_members WHERE role = 'admin' ORDER BY created_at LIMIT 1"
    ).fetchone()
    return row["user_id"]


def restore_settings(db) -> None:
    """The switches a wiped database forgets. Written as the seeded administrator, as Settings would."""
    wanted = {f"tools.{name}": True for name in settings_store.TOOLS}
    wanted["sarvam.enabled"] = True  # still waits for the sign-off (addons.sarvam_ready)
    admin = _admin_id(db)
    for key, value in wanted.items():
        db.execute(
            """
            INSERT INTO platform_settings (key, value, updated_by, updated_at) VALUES (?, ?, ?, ?)
            ON CONFLICT (key) DO UPDATE SET value = excluded.value, updated_by = excluded.updated_by, updated_at = excluded.updated_at
            """,
            (key, dumps(value), admin, now_iso()),
        )


def record_sarvam_signoff(db) -> bool:
    name = os.environ.get(SIGNED_OFF_BY, "").strip()
    if not name:
        return False
    if safety.signed_off(db, "sarvam_terms"):
        return True
    db.execute(
        """
        INSERT INTO governance_signoffs (item, signed_by, signer_role, document_reference, recorded_by, recorded_at)
        VALUES ('sarvam_terms', ?, 'Project owner', ?, 'deploy_boot', ?)
        """,
        (name[:120], SARVAM_DECISION, now_iso()),
    )
    return True


def main(patients: int = 0, with_login: int = 0, build: bool = False) -> int:
    from backend.synthetic import seed_accounts

    if not build and not copy_key_ring():  # the build has no secret files, and needs no key
        return 1
    init_db()
    if not judge_mode_active():
        # Turning judge mode off must deploy cleanly: a failed deploy would leave the previous one, with
        # judge mode on, still serving. So: no demo data, nobody to sign in as, the demo door closed.
        print("Judge mode is off (it needs DIAGNOSIA_JUDGE_MODE=1, demo mode on, made-up patients only), so no demo data was seeded.")
        return 0
    patients = patients or int(os.environ.get(SEED_PATIENTS, "60"))
    with_login = with_login or max(8, patients // 2)
    status = seed_accounts.run(patients=patients, with_login=with_login, seed=2026)
    if status:
        return status
    db = connect()
    try:
        restore_settings(db)
        signed = record_sarvam_signoff(db)
        db.commit()
    finally:
        db.close()
    print("Demo settings restored. Sarvam sign-off " + ("recorded." if signed else f"not recorded: {SIGNED_OFF_BY} is not set, so Sarvam stays off."))
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--build", action="store_true", help="seed in the build; skips the key ring")
    raise SystemExit(main(build=parser.parse_args().build))
