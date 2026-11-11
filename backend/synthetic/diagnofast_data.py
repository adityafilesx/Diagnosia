"""Makes labelled DiagnoFast test data: made-up interviews and single answers, with known answers.

    python -m backend.synthetic.diagnofast_data            # writes backend/tests/ai_eval/diagnofast/v1/

Two sets come out, each split into a "dev" half to tune against and a frozen "test" half:

- interviews: complete scripted interviews for all six specialty forms, in English, Hindi
  (Devanagari), romanised Hindi and code-mixed Hinglish. Each has the answers a patient gives, the
  form values a correct interview would capture, and whether it must stop early as urgent.
- screening: single answers, each labelled with the urgent symptoms it contains (or none). This
  includes negated mentions ("no chest pain"), history ("my father had a stroke") and clause
  breaks ("no fever, but chest pain"), which are the cases rule-based screening gets wrong.

Everything is made up. The wording is written by hand and combined by a seeded generator, so the same
seed always gives the same files. It has NOT been reviewed by a clinician or a native-speaker panel,
and the screening phrases were written knowing how the rules work, so scores on it are a floor for
regression checks, not a measure of real-world accuracy. See DATASHEET.md in the output folder.
"""
import argparse
import hashlib
import json
import random
from collections import Counter
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from backend.diagnofast import agent

VERSION = "v1"
SEED = 2026
OUTPUT_DIR = Path(__file__).resolve().parents[1] / "tests" / "ai_eval" / "diagnofast" / VERSION
TEST_SHARE = 0.2  # the frozen half. Never tune on it.

EN, DEV, ROM = "en", "dev", "rom"  # answer scripts: English, Devanagari, romanised Hindi

NUMBERS = {
    1: ("one", "एक", "ek"), 2: ("two", "दो", "do"), 3: ("three", "तीन", "teen"), 4: ("four", "चार", "chaar"),
    5: ("five", "पाँच", "paanch"), 7: ("seven", "सात", "saat"), 10: ("ten", "दस", "das"),
    14: ("fourteen", "चौदह", "chaudah"), 15: ("fifteen", "पंद्रह", "pandrah"), 30: ("thirty", "तीस", "tees"),
}
UNITS = {"day": ("days", "दिन", "din"), "week": ("weeks", "हफ़्ते", "hafte"), "month": ("months", "महीने", "mahine")}

# A bank entry is (gold value, polarity, must, english, devanagari, romanised).
# polarity: present (the answer says yes or gives a value), absent (says no), unknown (patient doesn't know).
# must: groups of alternatives. A captured value must contain one word from every group.
Entry = Tuple[str, str, List[List[str]], List[str], List[str], List[str]]
URGENT_OVERRIDE = "urgent"


def entry(gold, polarity, must, en, dev, rom, urgent=None) -> dict:
    return {"gold": gold, "polarity": polarity, "must": must, EN: en, DEV: dev, ROM: rom, URGENT_OVERRIDE: urgent or []}


def no(field: str = "") -> dict:
    return entry(f"No {field}".strip(), "absent", [], ["No", "No, nothing like that", "Not at all"], ["नहीं", "नहीं, ऐसा कुछ नहीं", "बिल्कुल नहीं"], ["Nahi", "Nahi, aisa kuch nahi", "Bilkul nahi"])


UNKNOWN = entry("Unknown", "unknown", [], ["I don't know", "Not sure", "I can't say"], ["पता नहीं", "मुझे नहीं पता", "पक्का नहीं कह सकता"], ["Pata nahi", "Mujhe nahi pata", "Pakka nahi keh sakta"])

# Shared fields -------------------------------------------------------------------------------------------

PAST = [
    entry("None", "absent", [], ["None", "Nothing, I'm usually healthy", "No long-term illness"], ["कुछ नहीं", "कोई पुरानी बीमारी नहीं"], ["Kuch nahi", "Koi purani bimari nahi"]),
    entry("Diabetes", "present", [["diabet", "sugar"]], ["I have diabetes", "Sugar, for five years"], ["मुझे शुगर है", "डायबिटीज़ है पाँच साल से"], ["Mujhe sugar hai", "Diabetes hai paanch saal se"]),
    entry("Hypertension", "present", [["hypertens", "blood pressure", "bp"]], ["High blood pressure", "BP problem"], ["ब्लड प्रेशर की दिक्कत है", "बीपी हाई रहता है"], ["Blood pressure ki dikkat hai", "BP high rehta hai"]),
    entry("Diabetes and hypertension", "present", [["diabet", "sugar"], ["hypertens", "blood pressure", "bp"]], ["Sugar and BP both", "Diabetes and high blood pressure"], ["शुगर और बीपी दोनों हैं"], ["Sugar aur BP dono hain"]),
    entry("Thyroid disorder", "present", [["thyroid"]], ["Thyroid", "I have a thyroid problem"], ["थायराइड है"], ["Thyroid hai"]),
    entry("Asthma", "present", [["asthma"]], ["Asthma since childhood"], ["बचपन से दमा है"], ["Bachpan se dama hai"]),
    entry("Arthritis", "present", [["arthritis"]], ["Arthritis in my knees"], ["घुटनों में गठिया है"], ["Ghutno mein gathiya hai"]),
]

MEDICINES = [
    entry("None", "absent", [], ["None", "I'm not taking anything", "No medicines"], ["कोई दवाई नहीं", "अभी कुछ नहीं ले रहा"], ["Koi dawai nahi", "Abhi kuch nahi le raha"]),
    entry("Dolo 650", "present", [["dolo"]], ["Dolo 650 when I have a fever", "Just Dolo"], ["बुखार में डोलो 650 लेता हूँ", "बस डोलो"], ["Bukhar mein Dolo 650 leta hoon", "Bas Dolo"]),
    entry("Metformin and amlodipine", "present", [["metformin"], ["amlodipine"]], ["Metformin and amlodipine daily", "Metformin for sugar and amlodipine for BP"], ["मेटफॉर्मिन और एम्लोडिपिन रोज़"], ["Metformin aur amlodipine roz"]),
    entry("Pantoprazole", "present", [["pantoprazole", "pan 40", "pan-40"]], ["Pantoprazole in the morning", "Pan 40 before food"], ["सुबह पैंटोप्राज़ोल लेता हूँ"], ["Subah pantoprazole leta hoon"]),
    entry("Cetirizine", "present", [["cetirizine", "cetrizine"]], ["Cetirizine at night", "A cetirizine tablet"], ["रात को सिट्रिज़िन"], ["Raat ko cetirizine"]),
    entry("Telmisartan", "present", [["telmisartan"]], ["Telmisartan 40 for BP"], ["बीपी के लिए टेल्मिसार्टन 40"], ["BP ke liye telmisartan 40"]),
    entry("Atorvastatin", "present", [["atorvastatin"]], ["Atorvastatin at night"], ["रात को एटोरवास्टेटिन"], ["Raat ko atorvastatin"]),
    entry("Levothyroxine", "present", [["levothyroxine", "thyronorm"]], ["Thyronorm every morning", "Levothyroxine 50"], ["रोज़ सुबह थायरोनॉर्म"], ["Roz subah Thyronorm"]),
    entry("Azithromycin", "present", [["azithromycin", "azee"]], ["Azithromycin for three days"], ["तीन दिन से एज़िथ्रोमाइसिन"], ["Teen din se azithromycin"]),
]

ALLERGIES = [
    entry("None", "absent", [], ["No allergies", "None that I know of"], ["कोई एलर्जी नहीं"], ["Koi allergy nahi"]),
    entry("Penicillin", "present", [["penicillin"]], ["Penicillin gives me a rash"], ["पेनिसिलिन से दाने हो जाते हैं"], ["Penicillin se daane ho jaate hain"]),
    entry("Sulfa drugs", "present", [["sulfa", "sulpha"]], ["Sulfa drugs, I get itching"], ["सल्फा दवाओं से खुजली होती है"], ["Sulfa dawai se khujli hoti hai"]),
    entry("Dust", "present", [["dust"]], ["Dust makes me sneeze"], ["धूल से छींकें आती हैं"], ["Dhool se chheenk aati hain"]),
    entry("Peanuts", "present", [["peanut", "groundnut"]], ["I am allergic to peanuts"], ["मूंगफली से एलर्जी है"], ["Moongfali se allergy hai"]),
    UNKNOWN,
]

SEVERITY_GP = [
    entry("Getting worse", "present", [["worse", "worsen", "increas"]], ["It's getting worse", "Worse every day"], ["बढ़ता जा रहा है", "हर दिन ज़्यादा हो रहा है"], ["Badhta ja raha hai", "Har din zyada ho raha hai"]),
    entry("Getting better", "present", [["better", "improv"]], ["A little better now", "Slowly improving"], ["अब थोड़ा बेहतर है", "धीरे धीरे ठीक हो रहा है"], ["Ab thoda behtar hai", "Dheere dheere theek ho raha hai"]),
    entry("Same as before", "present", [["same", "unchanged", "no change"]], ["About the same", "No change since it began"], ["वैसा ही है", "कोई फर्क नहीं पड़ा"], ["Waisa hi hai", "Koi farak nahi pada"]),
]

PAIN_SCORE = [
    entry(f"{n} out of 10", "present", [[str(n)]], [f"About {n}", f"{n} out of 10"], [f"{n} के आसपास", f"दस में से {n}"], [f"{n} ke aaspaas", f"Das mein se {n}"])
    for n in (3, 4, 5, 6, 7, 8)
]


def duration_entry(rng: random.Random) -> dict:
    unit = rng.choice(["day", "day", "day", "week", "month"])
    n = rng.choice([1, 2, 3, 4, 5, 7, 10, 14, 15, 30] if unit == "day" else [1, 2, 3, 4])
    word_en, word_dev, word_rom = NUMBERS[n]
    plural, unit_dev, unit_rom = UNITS[unit]
    unit_en = unit if n == 1 else plural
    return entry(
        f"{n} {unit_en}", "present", [[str(n), word_en], [unit]],
        [f"{n} {unit_en}", f"Since {word_en} {unit_en}", f"For about {n} {unit_en} now"],
        [f"{word_dev} {unit_dev} से", f"{word_dev} {unit_dev} हो गए"],
        [f"{word_rom} {unit_rom} se", f"{word_rom} {unit_rom} ho gaye"],
    )


# Chief complaints, by form ---------------------------------------------------------------------------------

def c(gold, must, en, dev, rom):
    return entry(gold, "present", must, en, dev, rom)


COMPLAINTS: Dict[str, List[dict]] = {
    "general_physician": [
        c("Fever and body ache", [["fever"], ["ache", "pain"]], ["Fever and body ache", "I have a fever with body pain"], ["बुखार और बदन दर्द है"], ["Bukhar aur badan dard hai"]),
        c("Cough and cold", [["cough"], ["cold"]], ["Cough and cold", "A bad cough and runny nose"], ["खांसी और जुकाम है"], ["Khaansi aur zukaam hai"]),
        c("Loose motions and stomach pain", [["loose", "diarr"], ["stomach", "abdom"]], ["Loose motions and stomach pain", "Stomach ache with loose motions"], ["दस्त और पेट दर्द"], ["Dast aur pet dard"]),
        c("Headache and dizziness", [["headache"], ["dizz"]], ["Headache and some dizziness", "My head aches and I feel dizzy"], ["सिर दर्द और चक्कर"], ["Sir dard aur chakkar"]),
        c("Burning urine", [["burn"], ["urin"]], ["Burning while passing urine"], ["पेशाब में जलन"], ["Peshab mein jalan"]),
        c("Weakness and tiredness", [["weak", "tired", "fatigue"]], ["I feel very weak and tired"], ["बहुत कमज़ोरी और थकान है"], ["Bahut kamzori aur thakaan hai"]),
        c("Diabetes follow-up", [["diabet", "sugar"]], ["Sugar check-up", "Diabetes follow-up"], ["शुगर की जांच करानी है"], ["Sugar ki jaanch karani hai"]),
    ],
    "dermatologist": [
        c("Itchy rash", [["itch"], ["rash"]], ["An itchy rash", "Itching and red rash on my skin"], ["खुजली वाले लाल दाने"], ["Khujli wale laal daane"]),
        c("Acne", [["acne", "pimple"]], ["Pimples on my face", "Acne that won't go"], ["चेहरे पर मुहांसे"], ["Chehre par muhaase"]),
        c("Hair fall", [["hair"]], ["Lot of hair fall", "My hair is falling a lot"], ["बहुत बाल झड़ रहे हैं"], ["Bahut baal jhad rahe hain"]),
        c("Fungal infection", [["fungal", "ringworm"]], ["Ringworm in the groin", "Fungal infection between toes"], ["दाद है जांघ में"], ["Daad hai jaangh mein"]),
        c("White patches", [["patch"]], ["White patches on my hands"], ["हाथों पर सफेद दाग"], ["Haathon par safed daag"]),
        c("Dry flaky skin", [["dry"], ["flak", "scal", "peel"]], ["Dry flaky skin on elbows"], ["कोहनी पर रूखी पपड़ीदार त्वचा"], ["Kohni par rookhi papdi wali twacha"]),
    ],
    "cardiology": [
        c("Palpitations", [["palpit", "racing", "heartbeat"]], ["My heartbeat feels fast sometimes", "Palpitations in the evening"], ["कभी कभी धड़कन तेज़ हो जाती है"], ["Kabhi kabhi dhadkan tez ho jaati hai"]),
        c("Swelling in feet", [["swell"], ["feet", "foot", "ankle"]], ["Swelling in both feet"], ["दोनों पैरों में सूजन"], ["Dono pairon mein sujan"]),
        c("Blood pressure check", [["blood pressure", "bp"]], ["My BP has been high", "Blood pressure review"], ["बीपी हाई रहता है"], ["BP high rehta hai"]),
        c("Cholesterol follow-up", [["cholesterol"]], ["Cholesterol is high in the report"], ["रिपोर्ट में कोलेस्ट्रॉल ज़्यादा है"], ["Report mein cholesterol zyada hai"]),
        c("Routine heart check-up", [["check", "routine", "review"]], ["Routine heart check-up", "Just a check-up, my father had heart trouble"], ["दिल की नियमित जांच"], ["Dil ki niyamit jaanch"]),
    ],
    "ent": [
        c("Ear pain", [["ear"], ["pain"]], ["Pain in my right ear", "Earache since yesterday"], ["दाहिने कान में दर्द"], ["Daahine kaan mein dard"]),
        c("Blocked nose", [["nose", "nasal"], ["block"]], ["My nose is blocked all the time"], ["नाक हमेशा बंद रहती है"], ["Naak hamesha band rehti hai"]),
        c("Sore throat", [["throat"]], ["Sore throat and pain on swallowing"], ["गले में खराश और निगलने में दर्द"], ["Gale mein kharaash aur nigalne mein dard"]),
        c("Hearing difficulty", [["hear"]], ["I can't hear well on the left"], ["बाएं कान से कम सुनाई देता है"], ["Baayein kaan se kam sunaai deta hai"]),
        c("Sinus problem", [["sinus"]], ["Sinus headache and heaviness"], ["साइनस का सिर दर्द"], ["Sinus ka sir dard"]),
    ],
    "orthopedics": [
        c("Knee pain", [["knee"], ["pain"]], ["Pain in both knees", "Knee pain when climbing stairs"], ["दोनों घुटनों में दर्द"], ["Dono ghutno mein dard"]),
        c("Back pain", [["back"], ["pain"]], ["Lower back pain", "My back hurts after lifting"], ["कमर में दर्द"], ["Kamar mein dard"]),
        c("Shoulder pain", [["shoulder"]], ["Right shoulder pain"], ["दाहिने कंधे में दर्द"], ["Daahine kandhe mein dard"]),
        c("Ankle sprain", [["ankle"]], ["Twisted my ankle", "Pain in the ankle after a fall"], ["टखने में मोच"], ["Takhne mein moch"]),
        c("Neck pain", [["neck"]], ["Stiff neck and pain"], ["गर्दन में दर्द और अकड़न"], ["Gardan mein dard aur akdan"]),
    ],
    "pediatrics": [
        c("Fever and cough", [["fever"], ["cough"]], ["My child has fever and cough", "Fever and a dry cough"], ["बच्चे को बुखार और खांसी है"], ["Bachche ko bukhar aur khaansi hai"]),
        c("Loose motions", [["loose", "diarr"]], ["Loose motions since yesterday"], ["कल से दस्त हो रहे हैं"], ["Kal se dast ho rahe hain"]),
        c("Vomiting", [["vomit"]], ["He is vomiting after feeds"], ["दूध पीने के बाद उल्टी करता है"], ["Doodh peene ke baad ulti karta hai"]),
        c("Rash", [["rash"]], ["A rash on her chest and back"], ["पीठ पर लाल दाने"], ["Peeth par laal daane"]),
        c("Cold and runny nose", [["cold", "runny"]], ["Cold and runny nose"], ["जुकाम और नाक बह रही है"], ["Zukaam aur naak beh rahi hai"]),
    ],
}

# Form-specific fields. Entries marked with urgent labels are urgent BY DESIGN: the product sends a patient
# who reports these to reception at once, so a correct interview stops there.
S = [["present"]]  # placeholder for readability only


def yn(gold_yes, must, en, dev, rom, field):
    return [entry(gold_yes, "present", must, en, dev, rom), no(field)]


FIELDS: Dict[str, Dict[str, List[dict]]] = {
    "general_physician": {
        "fever": yn("Fever", [["fever", "temperature"]], ["Yes, fever at night", "Yes, 101 degrees yesterday"], ["हाँ, रात को बुखार आता है"], ["Haan, raat ko bukhar aata hai"], "fever"),
        "related_symptoms": yn("Loss of appetite", [["appetite"]], ["Yes, I don't feel like eating"], ["हाँ, भूख नहीं लगती"], ["Haan, bhookh nahi lagti"], "other symptoms") + yn("Body aches", [["ache", "pain"]], ["Yes, body aches"], ["हाँ, बदन दर्द भी है"], ["Haan, badan dard bhi hai"], "other symptoms"),
        "severity": SEVERITY_GP,
    },
    "dermatologist": {
        "location": [
            entry("Face", "present", [["face"]], ["On my face"], ["चेहरे पर"], ["Chehre par"]),
            entry("Hands", "present", [["hand"]], ["On both hands"], ["दोनों हाथों पर"], ["Dono haathon par"]),
            entry("Back", "present", [["back"]], ["Mostly on my back"], ["ज़्यादातर पीठ पर"], ["Zyadatar peeth par"]),
            entry("Scalp", "present", [["scalp", "head"]], ["On the scalp"], ["सिर की त्वचा पर"], ["Sir ki twacha par"]),
        ],
        "changes": yn("Spreading and darker", [["spread", "dark", "bigger", "larg", "grow"]], ["Yes, it is spreading", "It has become bigger and darker"], ["हाँ, फैल रहा है", "बड़ा और गहरा हो गया है"], ["Haan, phail raha hai", "Bada aur gehra ho gaya hai"], "change") ,
        "itching_pain_bleeding": yn("Itching", [["itch"]], ["Yes, it itches a lot at night"], ["हाँ, रात को बहुत खुजली होती है"], ["Haan, raat ko bahut khujli hoti hai"], "itching, pain or bleeding"),
        "family_history": yn("Family history", [["family", "mother", "father", "brother", "sister"]], ["My mother had the same"], ["मेरी माँ को भी था"], ["Meri maa ko bhi tha"], "family history"),
        "treatments_tried": yn("Applied an ointment", [["ointment", "cream", "applied"]], ["I applied an ointment from the chemist"], ["केमिस्ट की क्रीम लगाई थी"], ["Chemist ki cream lagayi thi"], "treatment"),
    },
    "cardiology": {
        "chest_pain": [
            no("chest discomfort"),
            entry("No chest discomfort", "absent", [], ["No pain, only a little tiredness"], ["दर्द नहीं, बस थोड़ी थकान"], ["Dard nahi, bas thodi thakaan"]),
            entry("Chest pain spreading to the left arm", "present", [["chest"], ["arm"]], ["Yes, chest pain that goes to my left arm"], ["हाँ, सीने में दर्द बाएं हाथ तक जाता है"], ["Haan, seene mein dard baayein haath tak jaata hai"], urgent=["Chest pain"]),
        ],
        "breathlessness": [
            no("shortness of breath"),
            entry("No breathlessness", "absent", [], ["No, I'm fine that way"], ["नहीं, सांस ठीक है"], ["Nahi, saans theek hai"]),
            entry("Trouble breathing", "present", [["breath"]], ["Yes, I can't breathe properly even sitting"], ["हाँ, बैठे हुए भी सांस नहीं ले पा रहा"], ["Haan, baithe hue bhi saans nahi le pa raha"], urgent=["Trouble breathing"]),
        ],
        "palpitations": yn("Palpitations", [["palpit", "racing", "fast", "uneven"]], ["Yes, it races for a minute or two"], ["हाँ, एक दो मिनट तेज़ धड़कता है"], ["Haan, ek do minute tez dhadakta hai"], "palpitations"),
        "edema": yn("Ankle swelling", [["swell"], ["ankle", "feet", "foot"]], ["Yes, my ankles swell by evening"], ["हाँ, शाम को टखने सूज जाते हैं"], ["Haan, shaam ko takhne sooj jaate hain"], "swelling"),
        "syncope": [
            no("fainting"),
            entry("Mild dizziness only", "present", [["dizz"]], ["A little dizzy when I stand up quickly"], ["जल्दी खड़े होने पर थोड़ा चक्कर"], ["Jaldi khade hone par thoda chakkar"]),
            entry("Fainting", "present", [["faint", "pass"]], ["Yes, I fainted last week"], ["हाँ, पिछले हफ़्ते मैं बेहोश हो गया"], ["Haan, pichhle hafte main behosh ho gaya"], urgent=["Fainting or unconsciousness"]),
        ],
    },
    "ent": {
        "ear_pain": yn("Ear pain", [["ear"], ["pain", "discharge"]], ["Yes, pain and some fluid from the ear"], ["हाँ, दर्द है और कान से पानी आता है"], ["Haan, dard hai aur kaan se paani aata hai"], "ear pain or discharge"),
        "nasal_discharge": yn("Blocked nose", [["block", "runny", "discharge"]], ["Yes, blocked and runny"], ["हाँ, बंद भी है और बह भी रही है"], ["Haan, band bhi hai aur beh bhi rahi hai"], "nasal problem"),
        "throat": yn("Sore throat", [["throat", "swallow"]], ["Yes, it hurts when I swallow"], ["हाँ, निगलने में दर्द होता है"], ["Haan, nigalne mein dard hota hai"], "throat problem"),
        "hoarseness": yn("Hoarse voice", [["hoarse", "voice"]], ["Yes, my voice is hoarse"], ["हाँ, आवाज़ बैठ गई है"], ["Haan, awaaz baith gayi hai"], "voice change"),
        "hearing": yn("Reduced hearing", [["hear"]], ["Yes, less hearing in the left ear"], ["हाँ, बाएं कान से कम सुनाई देता है"], ["Haan, baayein kaan se kam sunaai deta hai"], "hearing change"),
    },
    "orthopedics": {
        "location": [
            entry("Right knee", "present", [["knee"]], ["My right knee"], ["दाहिना घुटना"], ["Daahina ghutna"]),
            entry("Lower back", "present", [["back"]], ["The lower back"], ["कमर के नीचे"], ["Kamar ke neeche"]),
            entry("Left shoulder", "present", [["shoulder"]], ["Left shoulder"], ["बायां कंधा"], ["Baayan kandha"]),
            entry("Ankle", "present", [["ankle"]], ["The ankle"], ["टखना"], ["Takhna"]),
        ],
        "trauma": yn("Fall before it started", [["fall", "injur", "slip"]], ["Yes, I slipped in the bathroom"], ["हाँ, बाथरूम में फिसल गया था"], ["Haan, bathroom mein phisal gaya tha"], "injury"),
        "weight_bearing": [
            entry("Can walk with pain", "present", [["walk"]], ["I can walk but it hurts"], ["चल सकता हूँ पर दर्द होता है"], ["Chal sakta hoon par dard hota hai"]),
            entry("Cannot bear weight", "present", [["cannot", "can't", "unable", "not able"]], ["I can't put any weight on it"], ["पैर पर वज़न नहीं डाल सकता"], ["Pair par wazan nahi daal sakta"]),
        ],
        "swelling": yn("Swelling", [["swell"]], ["Yes, it is swollen and warm"], ["हाँ, सूजन है और गर्म है"], ["Haan, sujan hai aur garam hai"], "swelling"),
        "stiffness": yn("Morning stiffness", [["stiff"]], ["Yes, stiff for half an hour in the morning"], ["हाँ, सुबह आधे घंटे अकड़न रहती है"], ["Haan, subah aadhe ghante akdan rehti hai"], "stiffness"),
        "severity": PAIN_SCORE,
    },
    "pediatrics": {
        "age": [
            entry(f"{n} years", "present", [[str(n), NUMBERS[n][0]], ["year"]], [f"{n} years old", f"{NUMBERS[n][0].capitalize()} years"], [f"{NUMBERS[n][1]} साल का है"], [f"{NUMBERS[n][2]} saal ka hai"])
            for n in (2, 3, 4, 5, 7, 10)
        ],
        "fever_curve": [
            entry("Fever 101 F", "present", [["101", "fever"]], ["Yes, 101 last night"], ["हाँ, कल रात 101 था"], ["Haan, kal raat 101 tha"]),
            entry("Fever 102 F", "present", [["102", "fever"]], ["102 this morning, I checked"], ["आज सुबह 102 था, मैंने नापा"], ["Aaj subah 102 tha, maine naapa"]),
            no("fever"),
        ],
        "feeding": [
            entry("Drinking less", "present", [["less", "reduc", "poor"]], ["He is drinking much less than usual"], ["पहले से बहुत कम पी रहा है"], ["Pehle se bahut kam pee raha hai"]),
            entry("Feeding normally", "present", [["normal", "usual", "well", "fine"]], ["Feeding normally"], ["खाना पीना ठीक है"], ["Khana peena theek hai"]),
        ],
        "activity": [
            entry("Active and playful", "present", [["active", "play"]], ["Still playing and active"], ["खेल रहा है, ठीक है"], ["Khel raha hai, theek hai"]),
            entry("Sleepy and dull", "present", [["sleep", "dull", "less active", "lethar"]], ["Sleepier than usual and dull"], ["ज़्यादा सोता है और सुस्त है"], ["Zyada sota hai aur sust hai"]),
        ],
        "urine": [
            entry("Normal urine", "present", [["normal", "usual", "regular"]], ["Passing urine as usual"], ["पेशाब रोज़ जैसा है"], ["Peshab roz jaisa hai"]),
            entry("Fewer wet nappies", "present", [["fewer", "less", "reduc"]], ["Fewer wet nappies today"], ["आज कम गीले डायपर हैं"], ["Aaj kam geele diaper hain"]),
        ],
        "immunizations": [
            entry("Up to date", "present", [["up to date", "complete", "all"]], ["All vaccines are done"], ["सारे टीके लग चुके हैं"], ["Saare teeke lag chuke hain"]),
            UNKNOWN,
        ],
    },
}

# Single answers for screening ------------------------------------------------------------------------------
# (noun phrase in each script that fits "no X", "X nahi hai", and a positive sentence)
CATEGORIES = {
    "Chest pain": {
        "noun": ("chest pain", "सीने में दर्द", "seene mein dard"),
        "positive": {
            EN: ["I have chest pain", "My chest hurts a lot", "There is a heavy pressure in my chest", "Chest tightness since morning", "I get a crushing chest pain when I walk", "Pain in the chest and left arm", "Chest pain started an hour ago"],
            DEV: ["सीने में दर्द हो रहा है", "छाती में बहुत दर्द है", "सीने पर भारीपन और दबाव है", "छाती में जकड़न है सुबह से", "सीने में तेज़ दर्द उठा है"],
            ROM: ["seene mein dard ho raha hai", "chhati mein bahut dard hai", "seene par bhaaripan aur dabav hai", "seene mein tez dard utha hai", "seena dukh raha hai"],
        },
    },
    "Trouble breathing": {
        "noun": ("trouble breathing", "सांस लेने में तकलीफ", "saans lene mein takleef"),
        "positive": {
            EN: ["I can't breathe properly", "I am struggling to breathe", "Shortness of breath even at rest", "I'm gasping for air", "Breathing has become very difficult", "I feel breathless all of a sudden"],
            DEV: ["सांस नहीं आ रही", "सांस लेने में बहुत तकलीफ है", "सांस फूल रही है", "दम घुट रहा है", "साँस लेना मुश्किल हो गया है"],
            ROM: ["saans nahi aa rahi", "saans lene mein bahut takleef hai", "saans phool rahi hai", "dam ghut raha hai", "saans lena mushkil ho gaya hai"],
        },
    },
    "Possible stroke signs": {
        "noun": ("slurred speech", "बोलने में लड़खड़ाहट", "bolne mein ladkhadahat"),
        "positive": {
            EN: ["His face is drooping on one side", "She has slurred speech since an hour", "Sudden weakness on one side of my body", "My mouth has gone crooked", "Sudden numbness in my left arm and face", "He suddenly can't speak clearly"],
            DEV: ["मुंह टेढ़ा हो गया है", "ज़ुबान लड़खड़ा रही है", "एक तरफ का हाथ पैर अचानक कमज़ोर पड़ गया", "चेहरा एक तरफ लटक गया है"],
            ROM: ["muh tedha ho gaya hai", "zubaan ladkhada rahi hai", "ek taraf ka haath pair achanak kamzor pad gaya", "chehra ek taraf latak gaya hai"],
        },
    },
    "Heavy bleeding": {
        "noun": ("heavy bleeding", "बहुत खून बहना", "bahut khoon behna"),
        "positive": {
            EN: ["There is heavy bleeding from the cut", "The bleeding won't stop", "I am bleeding a lot", "I vomited blood this morning", "He is coughing up blood", "Severe bleeding after delivery"],
            DEV: ["बहुत खून बह रहा है", "खून रुक नहीं रहा", "खून की उल्टी हुई है", "खांसी में खून आ रहा है"],
            ROM: ["bahut khoon beh raha hai", "khoon ruk nahi raha", "khoon ki ulti hui hai", "khaansi mein khoon aa raha hai"],
        },
    },
    "Fainting or unconsciousness": {
        "noun": ("fainting", "बेहोशी", "behoshi"),
        "positive": {
            EN: ["I fainted this morning", "He passed out in the bathroom", "She became unconscious", "I blacked out for a minute", "He collapsed and is not responding"],
            DEV: ["वह बेहोश हो गया", "मैं सुबह बेहोश हो गया था", "होश खो बैठी थी", "बच्चा बेहोश पड़ा है"],
            ROM: ["woh behosh ho gaya", "main subah behosh ho gaya tha", "hosh kho baithi thi", "bachcha behosh pada hai"],
        },
    },
    "Seizure": {
        "noun": ("seizure", "दौरा", "daura"),
        "positive": {
            EN: ["She had a seizure an hour ago", "He is having convulsions", "My child is shaking and his eyes rolled up in a seizure", "She had a fit and bit her tongue"],
            DEV: ["बच्चे को दौरा पड़ा", "मिर्गी का दौरा पड़ रहा है", "हाथ पैर अकड़ गए हैं और झटके आ रहे हैं"],
            ROM: ["bachche ko daura pada", "mirgi ka daura pad raha hai", "haath pair akad gaye hain aur jhatke aa rahe hain"],
        },
    },
    "Severe allergic reaction": {
        "noun": ("throat swelling", "गला सूजना", "gala soojna"),
        "positive": {
            EN: ["My throat is closing after the injection", "His lips and tongue are swollen after the medicine", "Severe allergic reaction, swelling of the face", "I think it's anaphylaxis, I can't swallow"],
            DEV: ["गला बंद हो रहा है", "होंठ और जीभ सूज गए हैं", "दवा के बाद चेहरा सूज गया है और सांस रुक रही है"],
            ROM: ["gala band ho raha hai", "honth aur jeebh sooj gaye hain", "dawai ke baad chehra sooj gaya hai"],
        },
    },
    "Poisoning or overdose": {
        "noun": ("overdose", "ज़हर खाना", "zeher khana"),
        "positive": {
            EN: ["He drank poison", "I took an overdose of my tablets", "She swallowed rat poison", "He ate a whole strip of sleeping pills"],
            DEV: ["उसने ज़हर खा लिया है", "बच्चे ने कीटनाशक पी लिया", "सारी गोलियां खा लीं"],
            ROM: ["usne zeher kha liya hai", "bachche ne keetnashak pee liya", "saari goliyan kha li"],
        },
    },
    "Thoughts of self-harm": {
        "noun": ("thoughts of suicide", "आत्महत्या के विचार", "aatmahatya ke vichar"),
        "positive": {
            EN: ["I want to kill myself", "Sometimes I want to die", "I have been thinking of ending my life", "I don't want to live any more", "I feel I'd be better off dead"],
            DEV: ["मैं आत्महत्या के बारे में सोचता हूँ", "मैं मरना चाहता हूँ", "जीने का मन नहीं करता, खुद को खत्म करना चाहता हूँ"],
            ROM: ["main aatmahatya ke baare mein sochta hoon", "main marna chahta hoon", "jeene ka mann nahi karta, khud ko khatam karna chahta hoon"],
        },
    },
}

# Phrases that read as urgent words but describe the past, or someone else's history. The rules leave these
# to the AI, so the screening layer is expected NOT to flag them.
HISTORY = [
    ("My father had a stroke five years ago", EN), ("Food poisoning last year, now fine", EN), ("He had a heart attack in 2019", EN),
    ("I have epilepsy, taking tablets regularly", EN), ("Paralysis as a child, recovered", EN), ("My mother has had fits since youth", EN),
    ("दिल का दौरा पड़ा था दो साल पहले", DEV), ("पिताजी को लकवा हुआ था", DEV), ("मिर्गी की दवाई चल रही है", DEV), ("पिछले साल फूड पॉइज़निंग हुई थी", DEV),
    ("dil ka daura pada tha do saal pehle", ROM), ("pitaji ko lakwa hua tha", ROM), ("mirgi ki dawai chal rahi hai", ROM), ("pichhle saal food poisoning hui thi", ROM),
]
# Policy questions the product owner and a clinician must decide. Reported, never counted as right or wrong.
AMBIGUOUS = [
    ("I get short of breath on climbing stairs", EN), ("Chest pain about two years ago", EN), ("Mild chest burning after spicy food", EN),
    ("I feel dizzy sometimes", EN), ("My child had a seizure with fever last year", EN), ("I felt like giving up yesterday", EN),
    ("सीढ़ियां चढ़ने पर सांस फूलती है", DEV), ("खाने के बाद सीने में जलन होती है", DEV), ("कभी कभी चक्कर आते हैं", DEV),
    ("seedhiyan chadhne par saans phoolti hai", ROM), ("khane ke baad seene mein jalan hoti hai", ROM), ("kabhi kabhi chakkar aate hain", ROM),
]
ORDINARY = {
    EN: ["Fever for three days", "I have a cough and cold", "Pain in my knee", "Itching on my arms", "A headache since morning", "Loose motions twice today", "Blocked nose and sore throat", "Pimples on my face", "My child has a runny nose", "Back pain after lifting"],
    DEV: ["तीन दिन से बुखार है", "खांसी और जुकाम है", "घुटने में दर्द है", "बाहों पर खुजली है", "सुबह से सिर दर्द है", "आज दो बार दस्त हुए", "नाक बंद और गला खराब", "मुझे बुखार है"],
    ROM: ["teen din se bukhar hai", "khaansi aur zukaam hai", "ghutne mein dard hai", "baahon par khujli hai", "subah se sir dard hai", "aaj do baar dast hue", "bukhar hai", "mujhe bukhar hai"],
}
NEGATION_EN = ["No {x}", "I don't have any {x}", "I never had {x}", "There is no {x}", "Without any {x}", "I haven't had {x}"]
NEGATION_DEV = ["{x} नहीं है", "{x} कभी नहीं हुआ", "{x} नहीं हुआ"]
NEGATION_ROM = ["{x} nahi hai", "{x} kabhi nahi hua", "{x} nahi hua"]
CARRIERS = {
    EN: ["{x}", "Doctor, {x}", "{x}, since this morning", "Yes. {x}", "{x}, please help"],
    DEV: ["{x}", "डॉक्टर साहब, {x}", "{x}, सुबह से", "हाँ। {x}"],
    ROM: ["{x}", "doctor sahab, {x}", "{x}, subah se", "haan. {x}"],
}
JOINERS = {EN: ["{a}, but {b}", "{a}. {b}", "{a} and {b}"], DEV: ["{a}, लेकिन {b}", "{a}। {b}", "{a} और {b}"], ROM: ["{a}, lekin {b}", "{a}. {b}", "{a} aur {b}"]}
NEGATED_ORDINARY = {EN: "No fever", DEV: "बुखार नहीं है", ROM: "bukhar nahi hai"}


def _sid(*parts) -> str:
    return hashlib.sha256("|".join(str(part) for part in parts).encode("utf-8")).hexdigest()[:12]


def _split(identifier: str) -> str:
    return "test" if int(identifier[:6], 16) / 0xFFFFFF < TEST_SHARE else "dev"


def build_screening(rng: random.Random) -> List[dict]:
    cases: List[dict] = []

    def add(text, script, kind, urgent, note=""):
        cases.append({"id": _sid("s", text), "script": script, "text": text, "kind": kind, "expected": urgent, "note": note})

    # Positives: every phrasing, bare and in a carrier sentence.
    for label, data in CATEGORIES.items():
        for script, phrases in data["positive"].items():
            for phrase in phrases:
                add(phrase, script, "positive", [label])
                carrier = rng.choice(CARRIERS[script])
                add(carrier.format(x=phrase), script, "positive", [label], "carrier sentence")
    # Two urgent symptoms in one answer.
    labels = list(CATEGORIES)
    for _ in range(18):
        first, second = rng.sample(labels, 2)
        script = rng.choice([EN, DEV, ROM])
        a, b = rng.choice(CATEGORIES[first]["positive"][script]), rng.choice(CATEGORIES[second]["positive"][script])
        add(rng.choice(JOINERS[script]).format(a=a, b=b), script, "positive", sorted([first, second], key=labels.index), "two symptoms")
    # Negated mentions: no flag.
    for label, data in CATEGORIES.items():
        for script, noun, templates in ((EN, data["noun"][0], NEGATION_EN), (DEV, data["noun"][1], NEGATION_DEV), (ROM, data["noun"][2], NEGATION_ROM)):
            for template in templates:
                add(template.format(x=noun), script, "negated", [])
    # A negation that must not hide a later symptom ("No fever, but chest pain").
    for label, data in CATEGORIES.items():
        for script in (EN, DEV, ROM):
            for _ in range(2):
                phrase = rng.choice(data["positive"][script])
                add(rng.choice(JOINERS[script]).format(a=NEGATED_ORDINARY[script], b=phrase), script, "clause_break", [label], "negation then symptom")
    # Negated symptom then a different positive one.
    for _ in range(24):
        first, second = rng.sample(labels, 2)
        script = rng.choice([EN, DEV, ROM])
        noun = CATEGORIES[first]["noun"][{EN: 0, DEV: 1, ROM: 2}[script]]
        negated = rng.choice({EN: NEGATION_EN, DEV: NEGATION_DEV, ROM: NEGATION_ROM}[script]).format(x=noun)
        phrase = rng.choice(CATEGORIES[second]["positive"][script])
        add(rng.choice(JOINERS[script]).format(a=negated, b=phrase), script, "clause_break", [second], f"no {first}, but {second}")
    for text, script in HISTORY:
        add(text, script, "history", [])
        add(rng.choice(CARRIERS[script]).format(x=text), script, "history", [], "carrier sentence")
    for script, phrases in ORDINARY.items():
        for phrase in phrases:
            add(phrase, script, "ordinary", [])
            add(rng.choice(CARRIERS[script]).format(x=phrase), script, "ordinary", [], "carrier sentence")
    for text, script in AMBIGUOUS:
        add(text, script, "ambiguous", None, "needs a clinician's decision")

    unique = {case["id"]: case for case in cases}
    result = sorted(unique.values(), key=lambda case: case["id"])
    for case in result:
        case["split"] = _split(case["id"])
    return result


def _render(item: dict, style: str, rng: random.Random) -> str:
    """Picks the wording of a bank entry in one answer style."""
    if style == EN:
        return rng.choice(item[EN])
    if style == DEV:
        return rng.choice(item[DEV])
    if style == ROM:
        return rng.choice(item[ROM])
    return rng.choice(item[rng.choice([EN, ROM, ROM, DEV])])  # code-mixed: a different script per answer


def _style(language: str, rng: random.Random) -> str:
    if language == "en-IN":
        return EN
    return rng.choices([DEV, ROM, "mixed"], weights=[45, 35, 20])[0]


def _field_entry(form_id: str, key: str, rng: random.Random) -> dict:
    if key == "chief_complaint":
        return rng.choice(COMPLAINTS[form_id])
    if key == "duration":
        return duration_entry(rng)
    if key == "past_illnesses":
        return rng.choice(PAST)
    if key == "current_medicines":
        return rng.choice(MEDICINES)
    if key == "allergies":
        return rng.choice(ALLERGIES)
    bank = FIELDS[form_id][key]
    # Urgent-by-design entries are rare, as in a real clinic.
    calm = [item for item in bank if not item[URGENT_OVERRIDE]]
    urgent = [item for item in bank if item[URGENT_OVERRIDE]]
    return rng.choice(urgent) if urgent and rng.random() < 0.06 else rng.choice(calm)


def build_interviews(rng: random.Random, per_form: int = 200) -> List[dict]:
    items: List[dict] = []
    forms = [form["id"] for form in agent.list_forms()]
    for form_id in forms:
        form = agent.load_form(form_id)
        for index in range(per_form):
            language = rng.choices(["hi-IN", "en-IN"], weights=[60, 40])[0]
            style = _style(language, rng)
            turns, gold, expect = [], {}, {"urgent": False, "at_turn": None, "labels": []}
            trap = None
            roll = rng.random()
            planned = "urgent" if roll < 0.22 else ("negated" if roll < 0.34 else ("history" if roll < 0.46 else None))
            target = rng.choice([1, 1, 2, 3])  # which question carries the planted urgent, negated or history phrase
            for position, field in enumerate(form["fields"]):
                if not field["required"] and rng.random() < 0.25:
                    continue  # patients aren't asked every optional question
                item = _field_entry(form_id, field["key"], rng)
                answer = _render(item, style, rng)
                labels = list(item[URGENT_OVERRIDE])
                if planned == "urgent" and not labels and position == target:
                    label = rng.choice(list(CATEGORIES))
                    script = style if style != "mixed" else rng.choice([EN, ROM])
                    answer = f"{answer}. {rng.choice(CATEGORIES[label]['positive'][script])}"
                    labels, planned = [label], None
                    trap = "urgent_added"
                elif planned in ("negated", "history") and trap is None and position == target:
                    script = style if style != "mixed" else rng.choice([EN, ROM])
                    if planned == "negated":
                        label = rng.choice(list(CATEGORIES))
                        noun = CATEGORIES[label]["noun"][{EN: 0, DEV: 1, ROM: 2}[script]]
                        extra = rng.choice({EN: NEGATION_EN, DEV: NEGATION_DEV, ROM: NEGATION_ROM}[script]).format(x=noun)
                    else:
                        extra = rng.choice([text for text, s in HISTORY if s == script])
                    answer = f"{answer}. {extra}"
                    trap = planned
                turns.append({"field_key": field["key"], "question": field["question"][language], "answer": answer})
                gold[field["key"]] = {"polarity": item["polarity"], "must": item["must"], "value": item["gold"]}
                if labels:
                    expect = {"urgent": True, "at_turn": len(turns) - 1, "labels": labels}
                    break
            identifier = _sid("i", form_id, index, language, turns[0]["answer"], len(turns))
            items.append({
                "id": identifier, "form_id": form_id, "language": language, "answer_style": style,
                "patient": {"age": rng.randint(2, 12) if form_id == "pediatrics" else rng.randint(18, 80), "sex": rng.choice(["female", "male"])},
                "trap": trap, "turns": turns, "gold": gold if not expect["urgent"] else {key: gold[key] for key in list(gold)[:-1]},
                "expect": expect,
            })
    unique = {item["id"]: item for item in items}
    result = sorted(unique.values(), key=lambda item: item["id"])
    for item in result:
        item["split"] = _split(item["id"])
    return result


def _write_jsonl(path: Path, rows: List[dict]) -> None:
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def _datasheet(interviews: List[dict], screening: List[dict], manifest: dict) -> str:
    def count(rows, key):
        return ", ".join(f"{name} {number}" for name, number in sorted(Counter(row[key] for row in rows).items(), key=lambda pair: str(pair[0])))

    test_i = [item for item in interviews if item["split"] == "test"]
    test_s = [item for item in screening if item["split"] == "test"]
    return f"""# DiagnoFast test data {VERSION}

Made-up, labelled data for the DiagnoFast interview. Generated by `python -m backend.synthetic.diagnofast_data`
with seed {SEED}. Nothing here comes from a real patient.

| Set | Total | Dev (tune on this) | Test (frozen, never tune on it) |
|---|---|---|---|
| Interviews | {len(interviews)} | {len(interviews) - len(test_i)} | {len(test_i)} |
| Screening answers | {len(screening)} | {len(screening) - len(test_s)} | {len(test_s)} |

Cases for the urgent-symptom check, single answers and interviews together:
{sum(1 for row in screening if row['kind'] in ('positive', 'clause_break'))} single answers with an urgent symptom and
{sum(1 for item in interviews if item['expect']['urgent'])} interviews that must stop as urgent;
{sum(1 for row in screening if row['kind'] in ('negated', 'history'))} single answers and
{sum(1 for item in interviews if item['trap'] in ('negated', 'history'))} interviews with a negated or history mention that must NOT stop.

Interviews by form: {count(interviews, 'form_id')}.
Interviews by language: {count(interviews, 'language')}. By answer style: {count(interviews, 'answer_style')}.
Screening by kind: {count(screening, 'kind')}.

## What each file holds
- `interviews_*.jsonl`: a form, a language, the questions and the patient's answers in order, the form values a
  correct interview captures (`gold`: polarity, required words, and a reference value), and whether the interview
  must stop early as urgent (`expect`).
- `screening_*.jsonl`: one answer, the urgent symptoms it contains (`expected`, or null for questions that need a
  clinician's decision), and its `kind`: positive, negated, clause_break, history, ordinary or ambiguous.
- `manifest.json`: the seed, counts and a SHA-256 of every file. A test fails if a frozen file changes.

## How to use it
- Rules layer: `python -m backend.synthetic.diagnofast_eval` needs no keys or network.
- Whole interview with a real model: `python -m backend.synthetic.diagnofast_eval --live --limit 100`
  (uses your configured keys and sends only made-up text to the AI providers).
- Report dev numbers while tuning. Report the test split once, before and after a change, and never edit it. To
  change the data, make a new version (`v2`) so old scores stay comparable.

## Known limits (read before quoting a number)
- **Not clinician reviewed.** The urgent labels follow the product's rules (chest pain, trouble breathing, stroke
  signs, heavy bleeding, fainting, seizure, severe allergy, poisoning, self-harm). A clinician has not agreed them.
- **Not native-speaker reviewed.** Hindi and romanised Hindi were written by an AI model from templates. Real speakers
  vary more: spellings, dialects, other Indian languages, and speech recognition errors are not covered.
- **Written knowing the rules.** The screening phrases were written by someone who knew how the rules work, so a high
  score is a regression floor, not real-world accuracy. The negated, history and clause-break cases are where
  rules fail most.
- **The split is by case, not by wording.** Dev and test are drawn from the same hand-written phrase bank, so a rule
  rewritten to match this bank's wording would pass both. The frozen test set stops tuning on specific cases. It
  can't prove the rules handle phrasings nobody wrote. New wording needs new data from real speakers (v2).
- **Ambiguous cases are reported, not scored.** For example "short of breath on stairs" or "chest pain two years
  ago". The product owner and a clinician must decide what the right behaviour is.
- **Medically incoherent patients.** Each field's answer is chosen independently, so a patient can take a thyroid
  tablet with no thyroid history, or have a fever answer that doesn't fit their complaint. That is fine for
  testing how answers are captured, and wrong for testing clinical reasoning or report quality.
- **Text only.** No audio, no noise, no recognition mistakes. Spoken test data needs consented recordings.
- **Cardiology interviews** include rare answers that are urgent by design (chest pain, trouble breathing, fainting).
  A correct interview ends there.

Manifest: seed {manifest['seed']}, version {manifest['version']}.
"""


def generate(output: Path = OUTPUT_DIR, seed: int = SEED, per_form: int = 200) -> dict:
    rng = random.Random(seed)
    screening = build_screening(rng)
    interviews = build_interviews(rng, per_form)
    output.mkdir(parents=True, exist_ok=True)
    files = {}
    for name, rows in (("interviews", interviews), ("screening", screening)):
        for split in ("dev", "test"):
            path = output / f"{name}_{split}.jsonl"
            _write_jsonl(path, [row for row in rows if row["split"] == split])
            files[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
    manifest = {
        "version": VERSION, "seed": seed, "per_form": per_form,
        "counts": {"interviews": len(interviews), "screening": len(screening),
                   "interviews_test": sum(1 for row in interviews if row["split"] == "test"),
                   "screening_test": sum(1 for row in screening if row["split"] == "test")},
        "sha256": files,
    }
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (output / "DATASHEET.md").write_text(_datasheet(interviews, screening, manifest), encoding="utf-8")
    return manifest


def main(arguments: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--output", type=Path, default=OUTPUT_DIR)
    parser.add_argument("--seed", type=int, default=SEED)
    parser.add_argument("--per-form", type=int, default=200)
    args = parser.parse_args(arguments)
    if args.output.resolve() == OUTPUT_DIR.resolve() and (args.seed != SEED or args.per_form != 200) and (OUTPUT_DIR / "manifest.json").exists():
        print("The frozen v1 set doesn't change. Use --output for a different set, or make a v2.")
        return 1
    manifest = generate(args.output, args.seed, args.per_form)
    print(f"Wrote {manifest['counts']['interviews']} interviews and {manifest['counts']['screening']} screening answers to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
