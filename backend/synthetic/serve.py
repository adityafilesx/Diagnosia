"""Starts the app with the synthetic test accounts already in place. Development only.

    python -m backend.synthetic.serve            # seeds if needed, then serves on 127.0.0.1:8000
    python -m backend.synthetic.serve --port 8001

It seeds the database named in your .env (or the default one), skips seeding when the
accounts already exist, and prints the logins before the server starts. One command, so
a fresh checkout can sign in straight away.
"""
import argparse
import socket
import sys

from backend.config import settings
from backend.db import connect, init_db
from backend.synthetic import seed_accounts


def _has_accounts() -> bool:
    init_db()
    db = connect()
    try:
        return db.execute("SELECT 1 FROM organizations WHERE name = ?", (seed_accounts.ORGANIZATION,)).fetchone() is not None
    finally:
        db.close()


def _port_busy(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(0.5)
        return probe.connect_ex((host, port)) == 0


def main(arguments=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=None, help="default 8000, or the next free port if 8000 is taken")
    parser.add_argument("--reload", action="store_true", help="restart when code changes")
    args = parser.parse_args(arguments)

    if args.port is None:
        args.port = 8000
        if _port_busy(args.host, args.port):
            # An older copy of the app is still running, with its own database and none of
            # these accounts. Don't make anyone hunt for it: use the next free port.
            taken = args.port
            while _port_busy(args.host, args.port):
                args.port += 1
                if args.port > taken + 50:
                    print("No free port found near 8000. Stop the other server or pass --port.", file=sys.stderr)
                    return 1
            print(
                f"\n*** Port {taken} is already used by another server, probably an older copy of this app with its own database\n"
                f"*** and none of the test accounts. The page you get on port {taken} is the OLD one. Use port {args.port} instead.\n"
            )
    elif _port_busy(args.host, args.port):
        print(
            f"Something is already running on {args.host}:{args.port}, probably an older copy of the app with its own\n"
            f"database and none of the test accounts. Stop it (Ctrl+C in its terminal), or pick another --port.",
            file=sys.stderr,
        )
        return 1
    if not _has_accounts():
        status = seed_accounts.run(patients=60, with_login=30, seed=2026)
        if status:
            return status
    else:
        seed_accounts.export_logins()
    print(f"\nDatabase: {settings.db_path}")
    print(f"Sign in at http://{args.host}:{args.port}/login.html with doctor01@example.com or patient001@example.com")
    print(f"Password for every test account: {seed_accounts.PASSWORD}")
    print(f"All logins: {seed_accounts.output_dir() / 'README.txt'}\n")

    import uvicorn

    uvicorn.run("backend.app:app", host=args.host, port=args.port, reload=args.reload)
    return 0


if __name__ == "__main__":
    sys.exit(main())
