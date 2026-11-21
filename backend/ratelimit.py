"""Limits how often the public and costly routes can be called.

The kiosk needs no account, and a patient link is all a caller needs to make the
AI and the speech service work. Without a limit, anyone could run up the AI bill
or fill a doctor's queue with made-up patients.

Hits are counted in SQLite, not in memory, so a limit holds across several
workers and survives a restart. Only a hash of each key (an address, a link,
an account) is stored, so the table never holds who called.

The limits are generous on purpose. A waiting-room tablet is one address for
every patient who uses it, and a real interview takes up to 12 answers, a few
retried recordings and a page reload or two.

Behind a reverse proxy every request seems to come from the proxy. Run uvicorn
with `--proxy-headers --forwarded-allow-ips=<the proxy's address>` so the real
client address reaches this code. Headers a client sends itself are never trusted.
"""
import hashlib
import math
import sqlite3
import time
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Callable, Dict, Iterator

from fastapi import Depends, HTTPException, Request, status

from backend.auth import require_user
from backend.db import connect

HOUR = 60 * 60
DAY = 24 * HOUR


@dataclass(frozen=True)
class Rule:
    name: str
    limit: int  # hits allowed in any window
    window: int  # seconds
    message: str


KIOSK_PER_DEVICE = "kiosk_per_device"
KIOSK_OVERALL = "kiosk_overall"
INTERVIEW_ANSWERS = "interview_answers"
INTERVIEW_PREVIEWS = "interview_previews"
INTERVIEW_STARTS_PER_DEVICE = "interview_starts_per_device"
INTERVIEW_HELP = "interview_help"
CONSENT_AUDIO = "consent_audio"
SPEECH_PER_USER = "speech_per_user"
REGISTER_PER_ADDRESS = "register_per_address"
LOGIN_PER_ADDRESS = "login_per_address"
# Each signed-in AI route has its own hourly limit, and all of them share one daily quota per account.
PRESCRIPTION_READS = "prescription_reads"
PRESCRIPTION_EXPLAINS = "prescription_explains"
SCRIBE_CALLS = "scribe_calls"
LAB_READS = "lab_reads"
PACK_QUESTIONS = "pack_questions"
AI_DAILY_PER_USER = "ai_daily_per_user"

_BUSY = "Too many requests. Please ask the reception staff for help."

# Looked up by name on every call, so a test can swap in a smaller rule.
RULES: Dict[str, Rule] = {
    # A busy clinic's shared tablet: about one new patient every 90 seconds.
    KIOSK_PER_DEVICE: Rule(KIOSK_PER_DEVICE, 40, HOUR, _BUSY),
    # However many addresses are used, the kiosk can't flood a doctor's queue.
    KIOSK_OVERALL: Rule(KIOSK_OVERALL, 400, DAY, "The kiosk is busy right now. Please ask the reception staff for a patient link."),
    # 12 questions at most, with room for retries.
    INTERVIEW_ANSWERS: Rule(INTERVIEW_ANSWERS, 40, 6 * HOUR, _BUSY),
    INTERVIEW_PREVIEWS: Rule(INTERVIEW_PREVIEWS, 60, 6 * HOUR, _BUSY),
    INTERVIEW_STARTS_PER_DEVICE: Rule(INTERVIEW_STARTS_PER_DEVICE, 60, HOUR, _BUSY),
    INTERVIEW_HELP: Rule(INTERVIEW_HELP, 10, HOUR, _BUSY),
    # Consent words read aloud, with replays. Each one can cost a paid voice call.
    CONSENT_AUDIO: Rule(CONSENT_AUDIO, 20, HOUR, _BUSY),
    # Reading a prescription aloud, a section at a time, with replays.
    SPEECH_PER_USER: Rule(SPEECH_PER_USER, 120, HOUR, "You have played a lot of audio. Please try again later."),
    # A clinic's staff and patients may share one address, so these leave room for a busy morning.
    REGISTER_PER_ADDRESS: Rule(REGISTER_PER_ADDRESS, 20, HOUR, "Too many new accounts from here. Please try again later."),
    LOGIN_PER_ADDRESS: Rule(LOGIN_PER_ADDRESS, 100, HOUR, "Too many sign-in attempts from here. Please try again later."),
    PRESCRIPTION_READS: Rule(PRESCRIPTION_READS, 20, HOUR, "You have read a lot of prescriptions this hour. Please try again later."),
    PRESCRIPTION_EXPLAINS: Rule(PRESCRIPTION_EXPLAINS, 30, HOUR, "You have asked for a lot of explanations this hour. Please try again later."),
    # A consultation sends a transcript chunk every few seconds while recording.
    SCRIBE_CALLS: Rule(SCRIBE_CALLS, 600, HOUR, "The scribe has had a lot of requests this hour. Please try again later."),
    LAB_READS: Rule(LAB_READS, 30, HOUR, "You have uploaded a lot of lab reports this hour. Please try again later."),
    PACK_QUESTIONS: Rule(PACK_QUESTIONS, 60, HOUR, "You have asked a lot of questions this hour. Please try again later."),
    AI_DAILY_PER_USER: Rule(AI_DAILY_PER_USER, 2000, DAY, "You have reached today's limit for AI help. Please try again tomorrow."),
}

_suspended = False

_clock: Callable[[], float] = time.time  # tests move time forward by replacing this


def _key_hash(bucket: str, key: str) -> str:
    # The bucket is part of the hash, so a link's hash here never equals intakes.token_hash.
    return hashlib.sha256(f"{bucket}:{key}".encode("utf-8")).hexdigest()


def hit(rule_name: str, key: str) -> None:
    """Counts one hit, or refuses with 429 when the limit is reached.

    It uses its own connection and commits at once, so the hit counts even when
    the request fails afterwards: a failing call costs as much as a good one.
    """
    if _suspended:
        return
    rule = RULES[rule_name]
    now = _clock()
    key_hash = _key_hash(rule.name, key)
    connection = connect()
    connection.isolation_level = None  # this code manages the transaction itself
    try:
        # IMMEDIATE takes the write lock first, so two workers can't both see room for one more.
        connection.execute("BEGIN IMMEDIATE")
        rows = connection.execute(
            """
            SELECT COUNT(*) AS hits, MIN(hit_at) AS oldest FROM rate_limit_hits
            WHERE bucket = ? AND key_hash = ? AND hit_at > ?
            """,
            (rule.name, key_hash, now - rule.window),
        ).fetchone()
        if rows["hits"] >= rule.limit:
            connection.execute("ROLLBACK")
            retry_after = max(1, math.ceil(rows["oldest"] + rule.window - now))
            raise HTTPException(
                status.HTTP_429_TOO_MANY_REQUESTS, rule.message, headers={"Retry-After": str(retry_after)}
            )
        connection.execute(
            "INSERT INTO rate_limit_hits (bucket, key_hash, hit_at) VALUES (?, ?, ?)",
            (rule.name, key_hash, now),
        )
        connection.execute("COMMIT")
    finally:
        connection.close()


@contextmanager
def suspended() -> Iterator[None]:
    """Lifts every limit for a trusted command-line job, such as seeding test accounts in this process."""
    global _suspended
    _suspended = True
    try:
        yield
    finally:
        _suspended = False


def forget_expired(db: sqlite3.Connection) -> None:
    """Deletes hits that no rule looks at any more. The caller commits."""
    longest = max(rule.window for rule in RULES.values())
    db.execute("DELETE FROM rate_limit_hits WHERE hit_at <= ?", (_clock() - longest,))


def _client_address(request: Request) -> str:
    # The socket's address, never a header the client chose. See the note at the top.
    return request.client.host if request.client else "unknown"


def per_client(rule_name: str) -> Callable:
    """A dependency that limits each client address."""

    def check(request: Request) -> None:
        hit(rule_name, _client_address(request))

    return check


def overall(rule_name: str) -> Callable:
    """A dependency that limits everyone together."""

    def check() -> None:
        hit(rule_name, "all")

    return check


def per_path_value(rule_name: str, name: str) -> Callable:
    """A dependency that limits each value of a path parameter, such as a patient link."""

    def check(request: Request) -> None:
        hit(rule_name, str(request.path_params.get(name, "")))

    return check


def per_user(rule_name: str) -> Callable:
    """A dependency that signs the user in and limits each account."""

    def check(user: sqlite3.Row = Depends(require_user)) -> sqlite3.Row:
        hit(rule_name, f"user:{user['id']}")
        return user

    return check


def per_user_ai(rule_name: str) -> Callable:
    """An AI route: its own hourly limit, and the account's shared daily quota."""

    def check(user: sqlite3.Row = Depends(require_user)) -> sqlite3.Row:
        hit(rule_name, f"user:{user['id']}")
        hit(AI_DAILY_PER_USER, f"user:{user['id']}")
        return user

    return check
