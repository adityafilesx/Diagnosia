"""WI-263: security headers on every route family, and a sliding idle timeout for sessions."""
import base64
import hashlib
import re
from datetime import datetime, timedelta, timezone

import pytest

from backend import app as app_module
from backend import auth
from backend.config import WEB_DIR, settings

PAGES = sorted(path.name for path in WEB_DIR.glob("*.html"))
# One address from each family: a page, the site root, a script, a stylesheet, an API route that
# needs no sign-in, one that does, a health route, and a path that doesn't exist.
FAMILIES = ["/", "/login.html", "/js/care/app.js", "/css/care.css", "/api/me", "/api/platform/config", "/healthz", "/nothing-here"]


@pytest.mark.parametrize("path", FAMILIES)
def test_every_route_family_carries_the_basic_headers(client, path):
    headers = client.get(path).headers
    assert headers["x-content-type-options"] == "nosniff"
    assert headers["x-frame-options"] == "SAMEORIGIN"
    assert headers["referrer-policy"] == "same-origin"
    assert "content-security-policy" in headers


@pytest.mark.parametrize("path", FAMILIES)
def test_hsts_is_sent_only_when_the_site_is_https(client, monkeypatch, path):
    monkeypatch.setattr(settings, "cookie_secure", False)
    assert "strict-transport-security" not in client.get(path).headers
    monkeypatch.setattr(settings, "cookie_secure", True)
    value = client.get(path).headers["strict-transport-security"]
    assert int(re.search(r"max-age=(\d+)", value).group(1)) >= 15552000  # 180 days or more


@pytest.mark.parametrize("page", PAGES)
def test_every_page_has_a_policy_that_blocks_unknown_scripts(client, page):
    policy = client.get(f"/{page}").headers["content-security-policy"]
    rules = {part.split()[0]: part.split()[1:] for part in policy.split(";") if part.strip()}
    assert rules["default-src"] == ["'self'"]
    assert "'unsafe-inline'" not in rules["script-src"] and "'unsafe-eval'" not in rules["script-src"]
    assert not any(source.startswith("http") or source == "*" for source in rules["script-src"])
    assert rules["object-src"] == ["'none'"]
    assert rules["frame-ancestors"] == ["'self'"]


@pytest.mark.parametrize("page", PAGES)
def test_each_inline_script_on_a_page_is_allowed_by_its_hash_and_nothing_else(client, page):
    text = (WEB_DIR / page).read_text(encoding="utf-8")
    policy = client.get(f"/{page}").headers["content-security-policy"]
    for body in re.findall(r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>", text, re.S):
        digest = base64.b64encode(hashlib.sha256(body.encode("utf-8")).digest()).decode()
        assert f"'sha256-{digest}'" in policy
    assert not re.search(r"\son[a-z]+\s*=\s*[\"']", re.sub(r"<meta[^>]*>", "", text)), "inline handlers are blocked by the policy"


def test_the_workspace_and_interview_pages_keep_the_strict_policy(client):
    for page in ("care.html", "intake.html"):
        policy = client.get(f"/{page}").headers["content-security-policy"]
        assert "script-src 'self';" in policy
        assert "google" not in policy


def test_api_answers_can_load_nothing(client):
    policy = client.get("/api/me").headers["content-security-policy"]
    assert "default-src 'none'" in policy and "frame-ancestors 'none'" in policy


# --- idle timeout -----------------------------------------------------------------------------


@pytest.fixture
def clock(monkeypatch):
    now = {"value": datetime(2026, 11, 14, 9, 0, tzinfo=timezone.utc)}
    monkeypatch.setattr(auth, "_now", lambda: now["value"])

    def forward(**step):
        now["value"] += timedelta(**step)

    return forward


def test_a_session_ends_after_thirty_idle_minutes_by_default(client, details, clock):
    assert settings.session_idle_minutes == 30
    client.post("/api/auth/register", json=details)
    clock(minutes=29)
    assert client.get("/api/me").status_code == 200
    clock(minutes=31)
    assert client.get("/api/me").status_code == 401


def test_using_the_app_keeps_the_session_alive(client, details, clock):
    client.post("/api/auth/register", json=details)
    for _ in range(6):  # two hours of steady use
        clock(minutes=20)
        assert client.get("/api/me").status_code == 200


def test_an_idle_session_is_gone_for_good(client, details, clock):
    client.post("/api/auth/register", json=details)
    clock(minutes=31)
    assert client.get("/api/me").status_code == 401
    clock(minutes=-31)  # even a clock that goes back can't revive it
    assert client.get("/api/me").status_code == 401


def test_background_polling_does_not_count_as_activity(client, details, clock):
    client.post("/api/auth/register", json=details)
    for _ in range(4):  # the page polls for 40 minutes while nobody touches it
        clock(minutes=10)
        client.get("/api/me", headers={"X-Curai-Background": "1"})
    assert client.get("/api/me").status_code == 401


def test_the_idle_limit_is_a_setting_and_zero_turns_it_off(client, details, clock, monkeypatch):
    monkeypatch.setattr(settings, "session_idle_minutes", 5)
    client.post("/api/auth/register", json=details)
    clock(minutes=6)
    assert client.get("/api/me").status_code == 401

    monkeypatch.setattr(settings, "session_idle_minutes", 0)
    client.post("/api/auth/login", json={"email": details["email"], "password": details["password"]})
    clock(hours=11)
    assert client.get("/api/me").status_code == 200


def test_the_absolute_lifetime_still_ends_a_busy_session(client, details, clock):
    client.post("/api/auth/register", json=details)  # a staff session lasts 12 hours at most
    for _ in range(37):
        clock(minutes=20)
        last = client.get("/api/me").status_code
    assert last == 401


def test_the_public_policy_is_built_from_the_pages(client):
    assert set(app_module.PAGE_POLICIES) == set(PAGES)


@pytest.mark.parametrize("page", PAGES)
def test_no_page_embeds_an_object_the_policy_would_block(page):
    text = (WEB_DIR / page).read_text(encoding="utf-8")
    assert "<object" not in text and "<embed" not in text


def test_a_route_that_sets_its_own_policy_keeps_it(doctor, patient):
    # The original of a lab report or document is shown in a frame inside the workspace. Its route
    # says the workspace may frame it; the general API policy ("frame-ancestors 'none'") must not replace that.
    image = b"\x89PNG\r\n\x1a\n" + b"PIXELDATA" * 8
    stored = doctor.post(
        f"/api/patients/{patient['id']}/documents", files={"file": ("xray.png", image, "image/png")},
        data={"document_type": "x_ray", "description": "Chest X-ray"},
    ).json()
    headers = doctor.get(f"/api/documents/{stored['id']}/file?inline=1").headers
    assert headers["content-security-policy"] == "frame-ancestors 'self'"
    assert headers["x-content-type-options"] == "nosniff"
