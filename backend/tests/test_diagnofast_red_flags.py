"""The rule-based urgent-symptom check, which runs before the AI on every answer."""
import pytest

from backend import llm
from backend.diagnofast import agent
from backend.diagnofast.agent import Turn, load_form
from backend.diagnofast.red_flags import normalise, screen
from backend.tests.test_diagnofast import (  # noqa: F401  (services is a fixture)
    ScriptedAI,
    create_intake,
    doctor_session,
    report,
    say,
    services,
    start,
    turn,
)


@pytest.mark.parametrize(
    "answer, flag",
    [
        # Chest pain
        ("I have chest pain since morning", "Chest pain"),
        ("My chest hurts when I walk", "Chest pain"),
        ("सीने में दर्द हो रहा है", "Chest pain"),
        ("छाती में भारीपन है", "Chest pain"),
        ("seene me dard hai", "Chest pain"),
        ("chhati mein bahut dard", "Chest pain"),
        # Trouble breathing
        ("I can't breathe properly", "Trouble breathing"),
        ("Shortness of breath at night", "Trouble breathing"),
        ("साँस नहीं आ रही", "Trouble breathing"),
        ("सांस लेने में तकलीफ है", "Trouble breathing"),
        ("saans nahi aa rahi", "Trouble breathing"),
        ("saans lene me dikkat ho rahi hai", "Trouble breathing"),
        # Possible stroke signs
        ("Her face is drooping on one side", "Possible stroke signs"),
        ("He has slurred speech since an hour", "Possible stroke signs"),
        ("मुँह टेढ़ा हो गया है", "Possible stroke signs"),
        ("जुबान लड़खड़ा रही है", "Possible stroke signs"),
        ("muh tedha ho gaya", "Possible stroke signs"),
        ("ek taraf kamzori hai", "Possible stroke signs"),
        # Heavy bleeding
        ("There is heavy bleeding from the cut", "Heavy bleeding"),
        ("The bleeding won't stop", "Heavy bleeding"),
        ("बहुत खून बह रहा है", "Heavy bleeding"),
        ("खून रुक नहीं रहा", "Heavy bleeding"),
        ("khoon ruk nahi raha", "Heavy bleeding"),
        # Fainting or unconsciousness
        ("I fainted this morning", "Fainting or unconsciousness"),
        ("He passed out in the bathroom", "Fainting or unconsciousness"),
        ("वह बेहोश हो गया", "Fainting or unconsciousness"),
        ("behosh ho gaya tha", "Fainting or unconsciousness"),
        # Seizure
        ("She had a seizure an hour ago", "Seizure"),
        ("बच्चे को दौरा पड़ा", "Seizure"),
        ("usko daura pada", "Seizure"),
        # Severe allergic reaction
        ("My throat is closing after the injection", "Severe allergic reaction"),
        ("His lips are swollen after eating peanuts", "Severe allergic reaction"),
        ("होंठ सूज गए हैं", "Severe allergic reaction"),
        ("jeebh sooj gayi hai", "Severe allergic reaction"),
        # Poisoning or overdose
        ("I took an overdose of my sleeping pills", "Poisoning or overdose"),
        ("He drank poison", "Poisoning or overdose"),
        ("उसने ज़हर खा लिया", "Poisoning or overdose"),
        ("zeher kha liya", "Poisoning or overdose"),
        # Thoughts of self-harm
        ("I want to kill myself", "Thoughts of self-harm"),
        ("Sometimes I want to die", "Thoughts of self-harm"),
        ("मैं आत्महत्या के बारे में सोचता हूँ", "Thoughts of self-harm"),
        ("मैं मरना चाहता हूँ", "Thoughts of self-harm"),
        ("aatmahatya ke vichar aate hain", "Thoughts of self-harm"),
        ("jeena nahi chahta", "Thoughts of self-harm"),
    ],
)
def test_urgent_symptoms_are_found_in_every_language(answer, flag):
    assert screen(answer) == [flag]


@pytest.mark.parametrize(
    "answer",
    [
        "Fever for three days",
        "मुझे बुखार है",
        "Bukhar hai",
        "no chest pain",
        "I don't have any chest pain",
        "सीने में दर्द नहीं है",
        "seene me dard nahi hai",
        "behosh nahi hua",
        "बेहोश नहीं हुआ",
        "never had seizures",
        "No shortness of breath",
        "My father had a stroke",
        "Food poisoning last year",
        "He had a heart attack in 2019",
        "दिल का दौरा पड़ा था",
        "Paralysis as a child",
        "I have epilepsy, on medicine",
        "He gets fits sometimes",
        "A faint rash on my arm",
        "",
    ],
)
def test_negated_and_ordinary_answers_are_not_flagged(answer):
    assert screen(answer) == []


@pytest.mark.parametrize(
    "answer, flags",
    [
        ("No fever, but chest pain", ["Chest pain"]),
        ("No fever but chest pain", ["Chest pain"]),
        ("No cough. Chest pain since morning", ["Chest pain"]),
        ("I have no chest pain but I can't breathe", ["Trouble breathing"]),
        ("बुखार नहीं है, लेकिन सीने में दर्द है", ["Chest pain"]),
        ("bukhar nahi hai lekin seene me dard hai", ["Chest pain"]),
        ("seene me dard nahi, saans phool rahi hai", ["Trouble breathing"]),
    ],
)
def test_a_clause_break_ends_the_reach_of_a_negation(answer, flags):
    assert screen(answer) == flags


def test_each_flag_is_reported_once_in_a_fixed_order():
    answer = "I can't breathe and chest pain, chest pain, my chest hurts. I fainted."
    assert screen(answer) == ["Chest pain", "Trouble breathing", "Fainting or unconsciousness"]


def test_spellings_are_folded_before_matching():
    assert normalise("  साँस   ") == "सांस"  # chandrabindu becomes anusvara
    assert normalise("ज़हर") == "जहर"  # nukta is dropped
    assert normalise("I DON’T") == "i don't"  # curly quote and case
    assert screen("I don’t have any chest pain") == []


# The interview step


@pytest.fixture
def form():
    return load_form("general_physician")


def test_a_flag_stops_the_interview_without_asking_the_ai(form, monkeypatch):
    def no_ai(*args, **kwargs):
        raise AssertionError("the AI should not be asked")

    monkeypatch.setattr(llm, "ask", no_ai)
    conversation = [{"question": "What brings you in?", "answer": "seene me dard ho raha hai"}]
    step = agent.advance(form, {"duration": "1 day"}, conversation, 1, "hi-IN")
    assert step.urgent == ["Chest pain"]
    assert step.question is None
    assert step.answers == {"duration": "1 day"}


def test_the_ai_still_decides_when_the_rules_find_nothing(form, monkeypatch):
    ai = ScriptedAI([turn({"chief_complaint": "Fever"}, question="Since when?", urgent=["Severe headache"])])
    monkeypatch.setattr(llm, "ask", ai)
    conversation = [{"question": "What brings you in?", "answer": "Fever and a bad headache"}]
    step = agent.advance(form, {}, conversation, 1, "en-IN")
    assert len(ai.calls) == 1
    assert step.urgent == ["Severe headache"]
    assert step.answers == {"chief_complaint": "Fever"}


def test_an_urgent_answer_reaches_reception_even_when_the_ai_is_down(client, details, services, monkeypatch):
    def turns_fail(system, content, schema, **options):
        if schema is Turn:
            raise llm.AIUnavailable("down")
        return report()

    monkeypatch.setattr(llm, "ask", turns_fail)
    doctor_session(client, details)
    urgent_id, urgent_token = create_intake(client)
    calm_id, _ = create_intake(client)

    start(client, urgent_token)
    response = say(client, urgent_token, "सीने में दर्द हो रहा है")
    assert response.status_code == 200
    body = response.json()
    assert body["finished"] is True
    assert body["urgent"] is True

    queue = client.get("/api/diagnofast/intakes").json()
    assert queue[0]["id"] == urgent_id
    assert queue[0]["urgent"] == ["Chest pain"]
    assert queue[1]["id"] == calm_id


# Phrasings and negations the first rules missed on the dev split (audit plan WI-201)


@pytest.mark.parametrize("answer, label", [
    ("There is a heavy pressure in my chest", "Chest pain"),
    ("seena dukh raha hai", "Chest pain"),
    ("छाती दुख रही है", "Chest pain"),
    ("Breathing has become very difficult", "Trouble breathing"),
    ("My mouth has gone crooked", "Possible stroke signs"),
    ("He suddenly can't speak clearly", "Possible stroke signs"),
    ("ek taraf ka haath pair achanak kamzor pad gaya", "Possible stroke signs"),
    ("एक तरफ का हाथ पैर अचानक कमज़ोर पड़ गया", "Possible stroke signs"),
    ("I vomited blood this morning", "Heavy bleeding"),
    ("khaansi mein khoon aa raha hai", "Heavy bleeding"),
    ("खांसी में खून आ रहा है", "Heavy bleeding"),
    ("She had a fit and bit her tongue", "Seizure"),
    ("mirgi ka daura pad raha hai", "Seizure"),
    ("haath pair akad gaye hain aur jhatke aa rahe hain", "Seizure"),
    ("हाथ पैर अकड़ गए हैं और झटके आ रहे हैं", "Seizure"),
    ("dawai ke baad chehra sooj gaya hai", "Severe allergic reaction"),
    ("दवा के बाद चेहरा सूज गया है", "Severe allergic reaction"),
    ("My face is swollen after the injection", "Severe allergic reaction"),
    ("He ate a whole strip of sleeping pills", "Poisoning or overdose"),
    ("saari goliyan kha li", "Poisoning or overdose"),
    ("bachche ne keetnashak pee liya", "Poisoning or overdose"),
    ("बच्चे ने कीटनाशक पी लिया", "Poisoning or overdose"),
])
def test_more_ways_of_saying_an_urgent_symptom_are_caught(answer, label):
    assert label in screen(answer)


@pytest.mark.parametrize("answer", [
    "आत्महत्या के विचार नहीं है",
    "आत्महत्या के विचार कभी नहीं हुआ",
    "aatmahatya ke vichar kabhi nahi hua",
    "बेहोशी कभी नहीं हुआ",
    "बहुत खून बहना कभी नहीं हुआ",
    "ज़हर खाना कभी नहीं हुआ",
    "seene mein dard bilkul nahi hai",
])
def test_a_hindi_negation_a_few_words_after_the_symptom_is_still_a_negation(answer):
    assert screen(answer) == []


@pytest.mark.parametrize("answer, label", [
    # The longer reach must not swallow a real symptom: only filler words may sit before the "nahi".
    ("seene mein dard hai saha nahi jaata", "Chest pain"),
    ("सीने में दर्द है नींद नहीं आती", "Chest pain"),
    ("aatmahatya ke vichar nahi hua aur seena dukh raha hai", "Chest pain"),
    ("bukhar nahi hai aur mirgi ka daura pad raha hai", "Seizure"),
    ("A fit of coughing at night", None),
])
def test_the_longer_negation_reach_does_not_hide_a_symptom(answer, label):
    found = screen(answer)
    assert (label in found) if label else found == []
