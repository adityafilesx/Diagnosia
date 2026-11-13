"""Finds urgent symptoms in a patient's answer with plain rules, before any AI.

The AI also lists urgent symptoms, but it can miss one, and when the AI call
fails it says nothing at all. A patient who says "my chest hurts" must reach a
person either way, so this check runs first and needs no network.

It is deliberately narrow:
- English, Hindi (Devanagari) and romanised Hindi only, like the rest of DiagnoFast.
- A clearly negated symptom ("no chest pain", "सीने में दर्द नहीं है") is skipped.
  A clause break ("No fever, but chest pain") ends the reach of a negation. In Hindi the
  "nahi" may follow a few filler words ("आत्महत्या के विचार कभी नहीं हुआ"), but only fillers.
- Words that usually describe past or family history (stroke, heart attack,
  paralysis, epilepsy, "fits", food poisoning) are not flagged. The AI still
  judges those in context. One fit told as an event ("she had a fit") is flagged.

It never diagnoses. It only says which kind of urgent symptom was mentioned, so
the interview can stop and send the patient to reception.
"""
import re
import unicodedata
from typing import List, Pattern, Tuple

# One word inside a symptom phrase ("seene me BAHUT dard"). It never crosses a clause break.
_WORD = r"[^\s,.;:!?।|]+"
_GAP1 = rf"(?:\s+{_WORD})?"
_GAP2 = rf"(?:\s+{_WORD}){{0,2}}?"
_GAP3 = rf"(?:\s+{_WORD}){{0,3}}?"
_GAP4 = rf"(?:\s+{_WORD}){{0,4}}?"

# Python's \b splits Devanagari words at vowel signs, so the Hindi patterns use
# no word boundaries at all. Latin patterns do.
_CATEGORIES: List[Tuple[str, List[str]]] = [
    ("Chest pain", [
        r"\bchest (?:pains?|tightness|pressure|discomfort|heaviness|hurts?|is hurting|feels (?:tight|heavy))\b",
        r"\b(?:pain|pressure|tightness|heaviness|discomfort) in (?:my |the )?chest\b",
        r"\b(?:tight|heavy|crushing|squeezing) chest\b",
        r"\bmy chest (?:hurts|is hurting|is tight|is heavy)\b",
        rf"\b(?:seene|sine|seena|sina|chhati|chati|chhaati|chaati){_GAP2}\s+(?:dard|dabav|dabaav|bharipan|bhaaripan|jakdan|pain)\b",
        rf"(?:सीने|सीना|छाती){_GAP2}\s*(?:दर्द|दबाव|भारीपन|जकडन)",
        rf"\b(?:seene|sine|seena|sina|chhati|chati|chhaati|chaati){_GAP1}\s+dukh\w*",
        rf"(?:सीने|सीना|छाती){_GAP1}\s*दुख",
    ]),
    ("Trouble breathing", [
        r"\b(?:trouble|difficulty|difficult|problems?) (?:in |with )?breathing\b",
        r"\b(?:hard|difficult|difficulty|trouble|struggling) to breathe\b",
        r"\bbreathing (?:trouble|difficulty|problems?)\b",
        r"\bbreathing (?:is |has become |has got |has gotten |is getting |became |got )(?:very |really |so |quite |too )?(?:difficult|hard)\b",
        r"\b(?:can't|cant|cannot|can not|unable to|not able to|couldn't) (?:breathe|breath)\b",
        r"\bshort(?:ness)? of breath\b",
        r"\bbreathless(?:ness)?\b",
        r"\b(?:gasping|struggling) for (?:air|breath)\b",
        rf"\b(?:saans|sans|saas|swas|shwas){_GAP2}\s+(?:nahi|nahin|nhi) (?:aa|aana|aati|aata|le|lena|leni|li|liya)\b",
        rf"\b(?:saans|sans|saas){_GAP2}\s+(?:phool|phul|fool|ful)\w*",
        rf"\b(?:saans|sans|saas|swas|shwas){_GAP3}\s+(?:dikkat|dikat|takleef|taklif|takleef|pareshani|mushkil|problem)\b",
        rf"\bdam (?:ghut|phool|phul)\w*",
        rf"(?:सांस|श्वास){_GAP2}\s*नहीं\s+(?:आ|ले)",
        rf"(?:सांस|श्वास){_GAP2}\s*फूल",
        rf"(?:सांस|श्वास){_GAP3}\s*(?:तकलीफ|दिक्कत|परेशानी|मुश्किल)",
        r"दम\s+(?:घुट|फूल)",
    ]),
    ("Possible stroke signs", [
        r"\b(?:face|mouth|smile) (?:is |has )?(?:gone |become |turned )?(?:drooping|droops|drooped|crooked|twisted)\b",
        r"\bsudden(?:ly)? (?:can't|cant|cannot|can not|couldn't|unable to|not able to) (?:speak|talk|see|walk|move)\b",
        r"\b(?:drooping|crooked) (?:face|mouth|smile)\b",
        r"\bslurred speech\b",
        r"\b(?:speech|words) (?:is |are )?slurr(?:ed|ing)\b",
        r"\bslurring\b",
        r"\bsudden(?:ly)? (?:numbness|weakness|confusion|loss of (?:vision|speech)|trouble (?:speaking|seeing|walking))\b",
        r"\b(?:numb|weak|numbness|weakness) (?:on|in) one side\b",
        rf"\bone side of (?:my |his |her |the )?(?:face|body){_GAP3}\s+(?:is )?(?:numb|weak|drooping|paralysed|paralyzed)\b",
        rf"\b(?:muh|munh|muhn|chehra|chehre){_GAP2}\s+(?:tedha|tedhi|terha|terhi|latak)\w*",
        rf"\b(?:zuban|zubaan|juban|jubaan|jaban|zaban){_GAP2}\s+(?:ladkhada|larkhara|ladkhad|larkhad)\w*",
        rf"\bek (?:taraf|side){_GAP4}\s+(?:sunn|kamzor|kamjor)\w*",
        rf"(?:मुंह|चेहरा|चेहरे){_GAP2}\s*(?:टेढा|टेढी|लटक)",
        rf"(?:जुबान|जबान|आवाज){_GAP2}\s*लडखडा",
        rf"एक\s+(?:तरफ|साइड){_GAP4}\s*(?:सुन्न|कमजोर)",
    ]),
    ("Heavy bleeding", [
        r"\b(?:heavy|severe|profuse|uncontrolled|non-stop|nonstop|lots of|a lot of) (?:bleeding|blood loss)\b",
        r"\bbleeding (?:heavily|a lot|badly|profusely|(?:that )?(?:won't|will not|doesn't|does not|isn't|is not) stop(?:ping)?|not stopping)\b",
        r"\b(?:vomiting|vomited|coughing|coughed|throwing up|threw up|spitting|spat) (?:up )?blood\b",
        r"\b(?:khansi|khaansi|khasi|khaasi) (?:me|mein|men) (?:khoon|khun)\b",
        r"खांसी\s+में\s+खून",
        r"\bblood in (?:my |the )?vomit\b",
        rf"\b(?:bahut|bohot|bahot|zyada|jyada|zyaada|jyaada){_GAP2}\s+(?:khoon|khun)\s+(?:beh|bah|nikal)\w*",
        rf"\b(?:khoon|khun){_GAP2}\s+(?:ruk|band) (?:nahi|nahin|nhi)\b",
        rf"\b(?:khoon|khun){_GAP2}\s+(?:nahi|nahin|nhi) (?:ruk|band)\w*",
        r"\b(?:khoon|khun) ki (?:ulti|ultee)\b",
        r"\b(?:ulti|ultee) (?:me|mein|men) (?:khoon|khun)\b",
        rf"(?:बहुत|ज्यादा){_GAP2}\s*खून\s+(?:बह|निकल)",
        rf"खून{_GAP2}\s*(?:रुक|बंद)\s+नहीं",
        rf"खून{_GAP2}\s*नहीं\s+(?:रुक|बंद)",
        r"खून\s+की\s+उल्टी",
        r"उल्टी\s+में\s+खून",
    ]),
    ("Fainting or unconsciousness", [
        r"\b(?:fainted|fainting|passed out|passing out|pass out|blacked out|blacking out|unconscious|lost consciousness|loss of consciousness|collapsed|unresponsive)\b",
        r"\b(?:feel|feels|feeling|felt) faint\b",
        r"\b(?:behosh|behoshi|be hosh|behos)\b",
        r"\bhosh kho\w*",
        r"बेहोश",
        r"होश\s+खो",
    ]),
    ("Seizure", [
        r"\b(?:seizures?|seizing|convulsions?|convulsing)\b",
        # "dil ka daura" is a heart attack, usually history, which the AI judges.
        rf"(?<!dil ka )(?<!dil ke )\b(?:daura|daure|dora|dore){_GAP1}\s+(?:pada|pade|padaa|padna|padte|padta|aaya|aaye|aata|pad rah\w*|aa rah\w*)\b",
        # One fit, said as an event. "Fits" in general is usually history, which the AI judges.
        r"\b(?:having|had|has) a fit\b(?! of)",
        r"\bjhatke (?:aa|lag) rah\w*",
        r"झटके\s+(?:आ|लग)\s+रह",
        rf"(?<!दिल का )(?<!दिल के )(?:दौरा|दौरे){_GAP1}\s*(?:पड|आया|आए|आते|आता)",
    ]),
    ("Severe allergic reaction", [
        r"\banaphyla\w*",
        r"\bsevere allergic reaction\b",
        r"\bthroat (?:is )?(?:closing|closed)\b",
        rf"\b(?:tongue|lips?){_GAP2}\s+(?:are |is )?(?:swelling|swollen|swelled)\b",
        r"\bswelling (?:of|in) (?:my |the )?(?:tongue|lips?)\b",
        r"\bswollen (?:tongue|lips?|face)\b",
        rf"\bface{_GAP2}\s+(?:is |has )?(?:swelling|swollen|swelled|swelled up|puffed up)\b",
        r"\bswelling (?:of|in|on) (?:my |the |his |her )?face\b",
        rf"\b(?:chehra|chehre){_GAP2}\s+(?:sooj|suj)\w*",
        rf"(?:चेहरा|चेहरे){_GAP2}\s*सूज",
        rf"\b(?:gala|gale){_GAP2}\s+(?:band|bandh) ho\w*",
        rf"\b(?:jeebh|jibh|honth|hoth|hont|honthon){_GAP2}\s+(?:sooj|suj|fool|phool|phul)\w*",
        rf"(?:जीभ|होंठ|होठ|होंठों){_GAP2}\s*(?:सूज|फूल)",
        rf"गला{_GAP2}\s*बंद\s+हो",
    ]),
    ("Poisoning or overdose", [
        r"\boverdos\w*",
        r"\b(?:took|taken|swallowed|drank|drunk|ate|eaten|consumed) (?:some |a |the )?(?:rat |insect )?(?:poison|pesticide|insecticide|rat killer)\b",
        r"\btook (?:too many|a lot of|lots of|all (?:my|the)) (?:pills|tablets|medicines?)\b",
        r"\b(?:ate|eaten|took|taken|swallowed|drank|drunk) (?:a |the |an )?(?:whole|entire|full) (?:strip|bottle|pack|packet|box) of\b",
        rf"\b(?:keetnashak|kitnashak|keetnasak|kitnasak){_GAP1}\s+(?:kha|pi|pee)\w*",
        rf"कीटनाशक{_GAP1}\s*(?:खा|पी|पि)",
        rf"\b(?:saari|sari|bahut saari|bohot saari|zyada|jyada) (?:goliyan|goliya|goli|dawai|dawaiyan|dawa){_GAP1}\s+(?:kha|le|li)\w*",
        rf"\b(?:zeher|zehar|jeher|jehar|zahar|jahar|zehr|jahr){_GAP1}\s+(?:kha|pi|pee|piya|pi li|li|liya)\w*",
        rf"जहर{_GAP1}\s*(?:खा|पी|पि)",
        rf"(?:ज्यादा|बहुत सारी|सारी)\s+(?:गोलियां|गोली|दवाई|दवा|दवाइयां){_GAP1}\s*(?:खा|ले)",
    ]),
    ("Thoughts of self-harm", [
        r"\b(?:kill|killing|hurt|hurting|harm|harming) (?:myself|my self)\b",
        r"\bself[- ]?harm\w*",
        r"\bsuicid\w*",
        r"\b(?:want|wanted|wanting|thinking of|thinking about|thoughts of|thought of|thought about) (?:to )?(?:die|dying|end(?:ing)? (?:it all|my life))\b",
        r"\bend(?:ing)? (?:it all|my life)\b",
        r"\b(?:don't|do not|dont) want to (?:live|be alive)\b",
        r"\bbetter off dead\b",
        r"\bno reason to live\b",
        r"\b(?:aatmahatya|atmahatya|aatmhatya|atmhatya|khudkushi|khudkhushi|khud khushi)\b",
        r"\b(?:marna|mar jana|mar jaana) (?:chahta|chahti|chahte)\b",
        r"\b(?:jeena|jina|jeene|jine) (?:nahi|nahin|nhi) (?:chahta|chahti|chahte)\b",
        r"\bkhud ko (?:nuksan|nuksaan|chot|maar|khatam)\w*",
        r"आत्महत्या",
        r"खुदकुशी",
        r"(?:मरना|मर\s+जाना)\s+(?:चाहता|चाहती|चाहते)",
        r"(?:जीना|जीने)\s+(?:नहीं|नही)\s+(?:चाहता|चाहती|चाहते)",
        r"खुद\s+को\s+(?:नुकसान|चोट|मार|खत्म)",
    ]),
]

_COMPILED: List[Tuple[str, List[Pattern[str]]]] = [
    (label, [re.compile(pattern) for pattern in patterns]) for label, patterns in _CATEGORIES
]

# A clause break ends the reach of a negation: "No fever, but chest pain".
# Extra breaks only ever make the check flag more, never less.
_CLAUSE_BREAK = re.compile(
    r"[,.;:!?।|]"
    r"|\b(?:but|and|though|although|however|yet|except|because|since|so|lekin|magar|aur|kintu|parantu)\b"
    r"|लेकिन|मगर|और|किंतु|परंतु|क्योंकि"
)
# English negation comes before the symptom, a few words at most: "I don't have any chest pain".
_NEGATION_BEFORE = re.compile(
    r"\b(?:no|not|never|without|denies|denied|deny|don't|dont|do not|doesn't|didn't|haven't|hasn't|hadn't|isn't|wasn't|nor|none)\b"
    r"(?:\s+\S+){0,4}\s*$"
)
# Hindi negation comes after it: "सीने में दर्द नहीं है", "behosh kabhi nahi hua".
# \b fails next to Devanagari, so the Latin words end with a lookahead instead.
# The symptom can be the start of a longer phrase ("आत्महत्या के विचार कभी नहीं हुआ", "ज़हर खाना कभी
# नहीं हुआ"), so the rest of its word and a few filler words may come first. Only fillers: any other
# word in between could be a second statement ("dard hai, saha nahi jaata" without the comma), and
# hiding a real symptom is the worse mistake. One free word stays allowed, as before.
_FILLER = (
    r"(?:ke|ka|ki|ko|to|bhi|kabhi|bilkul|bilkool|koi|aisa|aisi|kuch|vichar|vichaar|khayal|khyal|hona|"
    r"के|का|की|को|तो|भी|कभी|बिल्कुल|बिलकुल|कोई|ऐसा|ऐसी|कुछ|विचार|खयाल|ख्याल|होना)"
)
_NEGATION_AFTER = re.compile(
    rf"^\S*\s*(?:{_FILLER}\s+){{0,3}}(?:\S+\s+)?(?:(?:nahi|nahin|nahee|nhi)(?![a-z])|नहीं|नही)"
)

_QUOTES = str.maketrans({"‘": "'", "’": "'", "‚": "'", "‛": "'", "′": "'",
                         "“": '"', "”": '"', "„": '"', "″": '"'})
_CHANDRABINDU = "ँ"
_ANUSVARA = "ं"
_NUKTA = "़"


def normalise(text: str) -> str:
    """Folds the spellings people type into one form the patterns expect."""
    text = unicodedata.normalize("NFC", text).lower()
    text = text.replace(_CHANDRABINDU, _ANUSVARA)  # साँस -> सांस
    # NFC leaves letters like ज़ as base + nukta, so dropping the nukta gives ज.
    text = text.replace(_NUKTA, "")
    text = text.translate(_QUOTES)
    return " ".join(text.split())


def _negated(text: str, start: int, end: int) -> bool:
    before = text[:start]
    breaks = list(_CLAUSE_BREAK.finditer(before))
    clause_before = before[breaks[-1].end():] if breaks else before
    if _NEGATION_BEFORE.search(clause_before):
        return True
    after = text[end:]
    first_break = _CLAUSE_BREAK.search(after)
    clause_after = after[: first_break.start()] if first_break else after
    return bool(_NEGATION_AFTER.search(clause_after))


def screen(answer: str) -> List[str]:
    """Returns the kinds of urgent symptom the answer mentions, each once, in a fixed order."""
    text = normalise(answer)
    found = []
    for label, patterns in _COMPILED:
        if any(
            not _negated(text, match.start(), match.end())
            for pattern in patterns
            for match in pattern.finditer(text)
        ):
            found.append(label)
    return found
