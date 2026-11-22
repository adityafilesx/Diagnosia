"""Starts the app with the synthetic test accounts already in place. Development only.

    python -m backend.synthetic.serve            # seeds if needed, then serves on 127.0.0.1:8000
    python -m backend.synthetic.serve --port 8001
    python -m backend.synthetic.serve --host 0.0.0.0 --https   # phones on the same Wi-Fi, with the microphone

It seeds the database named in your .env (or the default one), skips seeding when the
accounts already exist, and prints the logins before the server starts. One command, so
a fresh checkout can sign in straight away.

Browsers open the microphone only on https or localhost. A phone opening http://<laptop address>:8000
gets no microphone at all, so --https serves with a self-signed certificate that names this
machine's Wi-Fi address. The phone warns about it once; accept it ("Advanced", then "Proceed").
"""
import argparse
import datetime
import ipaddress
import json
import socket
import sys
from pathlib import Path
from typing import List, Tuple

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


def lan_addresses() -> List[str]:
    """This machine's address on the local network, found by asking which interface would reach the internet.
    Nothing is sent: a UDP connect only picks a route."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
        try:
            probe.connect(("10.255.255.255", 1))
            return [probe.getsockname()[0]]
        except OSError:
            return []


def dev_certificate(folder: Path, addresses: List[str]) -> Tuple[Path, Path]:
    """A self-signed certificate for localhost and the given addresses, made once and reused while
    the addresses stay the same, so a phone that accepted it isn't asked again. Development only."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID

    from backend import private_files

    cert_path, key_path, names_path = folder / "dev-cert.pem", folder / "dev-key.pem", folder / "dev-names.json"
    wanted = sorted(set(["127.0.0.1", *addresses]))
    if cert_path.exists() and key_path.exists() and names_path.exists():
        if json.loads(names_path.read_text(encoding="utf-8")) == wanted:
            return cert_path, key_path
    private_files.create_private_dir(folder)
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Diagnosia development")])
    now = datetime.datetime.now(datetime.timezone.utc)
    alternative = [x509.DNSName("localhost")] + [x509.IPAddress(ipaddress.ip_address(item)) for item in wanted]
    cert = (
        x509.CertificateBuilder()
        .subject_name(name).issuer_name(name).public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(minutes=5)).not_valid_after(now + datetime.timedelta(days=397))
        .add_extension(x509.SubjectAlternativeName(alternative), critical=False)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )
    key_path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    private_files.make_private(key_path)
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    names_path.write_text(json.dumps(wanted), encoding="utf-8")
    return cert_path, key_path


def main(arguments=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=None, help="default 8000, or the next free port if 8000 is taken")
    parser.add_argument("--reload", action="store_true", help="restart when code changes")
    parser.add_argument("--https", action="store_true", help="self-signed https, so phones on the Wi-Fi can use the microphone")
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
    scheme = "https" if args.https else "http"
    print(f"\nDatabase: {settings.db_path}")
    print(f"Sign in at {scheme}://{args.host}:{args.port}/login.html with doctor01@example.com or patient001@example.com")
    print(f"Password for every test account: {seed_accounts.PASSWORD}")
    print(f"All logins: {seed_accounts.output_dir() / 'README.txt'}\n")

    tls = {}
    if args.https:
        addresses = lan_addresses() if args.host in ("0.0.0.0", "::") else [args.host] if args.host != "localhost" else []
        cert, key = dev_certificate(settings.db_path.parent / "dev-tls", addresses)
        tls = {"ssl_certfile": str(cert), "ssl_keyfile": str(key)}
        for address in addresses:
            print(f"On a phone on the same Wi-Fi: https://{address}:{args.port}/ (accept the certificate warning once)")
    elif args.host not in ("127.0.0.1", "localhost"):
        print("*** Plain http on a network address: phones and other computers get NO microphone. Add --https.")

    import uvicorn

    uvicorn.run("backend.app:app", host=args.host, port=args.port, reload=args.reload, **tls)
    return 0


if __name__ == "__main__":
    sys.exit(main())
