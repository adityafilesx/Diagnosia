"""Suggestion features held for regulatory review are off by default, on screen and in the API (WI-113)."""
from backend import llm, settings_store
from backend.auth import SESSION_COOKIE
from backend.diagnofast.agent import Report, Turn
from backend.tests.test_diagnofast import ALL_REQUIRED, create_intake, doctor_session, say, services, start, turn  # noqa: F401


class AIWithInvestigations:
    def __init__(self):
        self.turns = [turn(ALL_REQUIRED, finished=True)]

    def __call__(self, system, content, schema, **options):
        if schema is Turn:
            return self.turns.pop(0)
        return Report(
            chief_complaint="Fever", present_illness="Three days of fever.", highlights=[], current_medicines=[],
            allergies=[], past_history="", gaps=[], suggested_investigations=["Complete blood count"],
        )


def _report(client, details, monkeypatch):
    monkeypatch.setattr(llm, "ask", AIWithInvestigations())
    doctor_session(client, details)
    intake_id, token = create_intake(client)
    cookie = client.cookies[SESSION_COOKIE]
    client.cookies.clear()
    start(client, token)
    say(client, token)
    client.cookies.set(SESSION_COOKIE, cookie)
    return client.get(f"/api/diagnofast/intakes/{intake_id}").json()["report"]


def test_held_features_start_switched_off():
    for key in settings_store.HELD_FEATURES:
        assert settings_store.SETTINGS[key]["default"] is False


def test_investigations_are_neither_stored_nor_shown_while_held(client, details, services, monkeypatch):
    report = _report(client, details, monkeypatch)
    assert report["chief_complaint"] == "Fever"
    assert "suggested_investigations" not in report


def test_investigations_appear_once_switched_on(client, details, services, monkeypatch):
    monkeypatch.setitem(settings_store.SETTINGS["features.diagnofast_investigations"], "default", True)
    assert _report(client, details, monkeypatch)["suggested_investigations"] == ["Complete blood count"]


def test_the_pack_brief_is_refused_while_held(client, details):
    doctor_session(client, details)
    config = client.get("/api/platform/config").json()
    assert config["features"] == {"diagnofast_investigations": False, "patient_pack_brief": False}
    for path in ("brief", "ask"):
        refused = client.post(f"/api/patients/any-patient/pack/{path}", json={"question": "Any allergies?"})
        assert refused.status_code == 403
        assert refused.json()["detail"]["code"] == "feature_held"
