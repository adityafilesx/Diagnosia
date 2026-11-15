"""WI-250: the family's checklist in plain words: who to call first, the approved summary, a large
Done, and a notice when a step is added after approval."""
import re

from backend.config import WEB_DIR
from backend.tests.conftest import linked_patient
from backend.tests.test_dischargecare import BASE, active, approve, create, instruction, task  # noqa: F401 (fixtures)

SCRIPT = (WEB_DIR / "js" / "care" / "discharge.js").read_text(encoding="utf-8")


def checklist(account, episode):
    return account.get(f"{BASE}/episodes/{episode['id']}/checklist").json()


# --- what the family is sent -------------------------------------------------------------------


def test_the_checklist_carries_the_approved_summary_in_plain_fields(doctor, active):
    account, _, episode = active
    data = checklist(account, episode)
    assert data["discharge_date"] == "2026-11-01" and data["destination"] == "Home with family"
    assert data["approved_at"] and data["approved_by"]  # who approved it, by name
    assert data["emergency_contact"].startswith("Ward 4")
    assert "problems" not in data and "procedures" not in data  # the team's clinical wording stays with the team


def test_a_step_holds_only_what_a_family_needs(doctor, active):
    account, _, episode = active
    [step] = checklist(account, episode)["tasks"]
    assert set(step) == {"id", "title", "detail", "due_at", "status", "overdue", "added_after_approval"}
    assert step["title"] == "Book chest X-ray" and step["added_after_approval"] is False


def test_a_step_for_the_care_team_is_not_on_the_family_checklist(doctor, active):
    account, _, episode = active
    task(doctor, episode["id"], title="Chase the culture result", audience="care_team")
    assert [step["title"] for step in checklist(account, episode)["tasks"]] == ["Book chest X-ray"]


# --- a step added after approval ---------------------------------------------------------------


def test_the_family_is_told_when_a_step_is_added_after_approval(doctor, active):
    account, _, episode = active
    before = len(account.get("/api/notifications").json())
    assert task(doctor, episode["id"], title="Collect the oxygen cylinder").status_code == 201
    notices = account.get("/api/notifications").json()
    assert len(notices) == before + 1
    assert "new step" in notices[0]["title"].lower()
    assert notices[0]["body"] == "Collect the oxygen cylinder"
    steps = {step["title"]: step for step in checklist(account, episode)["tasks"]}
    assert steps["Collect the oxygen cylinder"]["added_after_approval"] is True
    assert steps["Book chest X-ray"]["added_after_approval"] is False


def test_a_care_team_task_added_later_does_not_notify_the_family(doctor, active):
    account, _, episode = active
    before = len(account.get("/api/notifications").json())
    task(doctor, episode["id"], title="Chase the culture result", audience="care_team")
    assert len(account.get("/api/notifications").json()) == before


def test_nothing_is_announced_before_approval(doctor, person):
    account, record = linked_patient(doctor, person)
    episode = create(doctor, record["id"])
    task(doctor, episode["id"])
    assert account.get("/api/notifications").json() == []


def test_the_family_can_mark_a_step_done_and_say_they_could_not(doctor, active):
    account, record, episode = active
    [step] = checklist(account, episode)["tasks"]
    assert account.post(f"/api/tasks/{step['id']}/status", json={"status": "done"}).status_code == 200
    assert checklist(account, episode)["tasks"][0]["status"] == "done"
    assert account.post(f"/api/tasks/{step['id']}/status", json={"status": "blocked", "note": "No transport"}).status_code == 200
    assert doctor.get(f"/api/patients/{record['id']}/tasks").json()[0]["status_note"] == "No transport"


# --- the screen --------------------------------------------------------------------------------


def patient_view():
    return SCRIPT[SCRIPT.index("function checklist("):SCRIPT.index("export async function renderDischarge(")]


def test_who_to_call_comes_first():
    view = patient_view()
    assert view.index("Who to call") < view.index("What to do") < view.index("Your instructions")
    assert "112" in view


def shown_text(source):
    """The words a family can read: every quoted string in the view, without the code inside ${...}.
    Field names such as data.pending_results are code, never shown, so they are left out."""
    texts = re.findall(r"'((?:[^'\\]|\\.)*)'|\"((?:[^\"\\]|\\.)*)\"|`((?:[^`\\]|\\.)*)`", source)
    return " ".join(re.sub(r"\$\{[^}]*\}", " ", "".join(parts)) for parts in texts)


def test_the_family_view_uses_plain_words_and_a_large_done():
    view = patient_view()
    assert "class: 'big-done'" in view and "'Done'" in view
    assert "taskList(" not in view  # the staff table, with its priority and status columns, is not shown to families
    words = shown_text(view)
    assert "Who to call" in words and "Not back yet" in words  # the extraction does see the visible text
    for staff_word in ("Priority", "priority", "pending", "Pending", "escalat", "Blocked", "Missed", "audience", "episode"):
        assert staff_word not in words, staff_word
    assert "Not back yet" in view and "I couldn't do this" in view


def test_a_step_added_later_is_marked_new():
    assert "added_after_approval" in patient_view() and "New" in patient_view()
