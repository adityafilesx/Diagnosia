"""WI-244: the referral form. What a browser shows is checked by hand at three widths; these keep
the structure from slipping back."""
import re

from backend.config import WEB_DIR

SCRIPT = (WEB_DIR / "js" / "care" / "referrals.js").read_text(encoding="utf-8")


def test_the_destination_is_a_required_choice_with_nothing_picked_for_the_clinician():
    assert "type: 'radio', name: 'destination', value, required: true" in SCRIPT
    assert "h('legend', {}, 'Send to')" in SCRIPT
    assert "checked: true" not in SCRIPT  # no default destination
    assert "Phone, fax or paper'], ...organizations" not in SCRIPT  # the old select that defaulted to paper


def test_each_field_reports_its_own_error():
    assert "role: 'alert'" in SCRIPT and "aria-invalid" in SCRIPT and "aria-describedby" in SCRIPT
    for message in ("Choose where to send this referral.", "Say who it is going to.", "Give the reason for this referral."):
        assert message in SCRIPT
    assert "first.control.focus()" in SCRIPT  # focus goes to the first field that needs fixing


def test_priority_is_chosen_from_a_list_never_typed():
    assert "ask('New priority" not in SCRIPT
    assert re.search(r"name: 'priority'.*type: 'select'", SCRIPT)


def test_new_referral_comes_before_the_lists():
    page = SCRIPT[SCRIPT.index("export async function renderReferrals("):]
    assert page.index("id: 'new-referral'") < page.index("        area,\n        lists,")


def test_nothing_asks_for_a_patient_when_none_is_open():
    page = SCRIPT[SCRIPT.index("export async function renderReferrals("):]
    assert "const writing = Boolean(patient) && isClinician;" in page
    # Every use of the open patient's id or name is behind a check that there is one.
    for match in re.finditer(r"patient\.(id|first_name)", page):
        before = page[max(0, match.start() - 220):match.start()]
        assert "writing" in before or "patient ?" in before or "patient)" in before, page[match.start() - 80:match.end()]
    assert "Open a patient to send a new referral" in page
