"""Plain checks on the AI's report, run after it is written. They flag; they never change it.

The doctor sees each problem beside the row it is about, and the patient's own answers stay one
click away. The checks are deliberately narrow, so a flag means something:

- A NORMAL row must cite at least one answer, and a cited answer must contain a negative ("no",
  "nahi", "नहीं"...). "Not asked" is never normal.
- An H* or L* row must give a number and a printed range. A symptom is never a lab value.
- An investigation to consider must not name a medicine or a dose. Treatment is the doctor's.
"""
import re
from typing import Dict, List

NEGATIVE = re.compile(
    r"\b(?:no|not|none|never|nothing|nil|denies|denied|without|nahi|nahin|nhi|nahee|kabhi nahi)\b|नहीं|नही|कभी नहीं|बिल्कुल नहीं"
)
NUMBER = re.compile(r"\d")
RANGE = re.compile(r"\d\s*(?:-|–|to)\s*\d|[<>≤≥]\s*\d|\bup to\s*\d|\bbelow\s*\d|\babove\s*\d")
# Words that make an investigation read as a treatment. The list is short on purpose: common medicines
# a model is likely to name, and words that only appear with a dose.
DOSE = re.compile(r"\b\d+\s*(?:mg|mcg|g|ml|iu|units?)\b|\b(?:tablets?|tabs?|capsules?|caps?|syrups?|injections?|inj|start|give|prescribe)\b")
MEDICINES = re.compile(
    r"\b(?:paracetamol|acetaminophen|ibuprofen|diclofenac|aspirin|amoxicillin|amoxyclav|azithromycin|ciprofloxacin|"
    r"doxycycline|cefixime|ceftriaxone|metronidazole|metformin|glimepiride|insulin|amlodipine|telmisartan|losartan|"
    r"atorvastatin|rosuvastatin|pantoprazole|omeprazole|ranitidine|ondansetron|domperidone|cetirizine|levocetirizine|"
    r"montelukast|salbutamol|prednisolone|dexamethasone|antibiotics?|steroids?|painkillers?|antacids?)\b"
)


def _cited_negative(row: dict, conversation: List[dict]) -> bool:
    for turn in row.get("evidence_turns") or []:
        if isinstance(turn, int) and 1 <= turn <= len(conversation):
            if NEGATIVE.search(conversation[turn - 1]["answer"].lower()):
                return True
    return False


def check_report(report: dict, conversation: List[dict]) -> List[Dict]:
    """Each problem found, with the field and row it belongs to. An empty list means nothing stood out."""
    found: List[Dict] = []
    for index, row in enumerate(report.get("review_of_systems") or []):
        flag = row.get("flag")
        if flag == "NORMAL" and not _cited_negative(row, conversation):
            found.append({"field": "review_of_systems", "index": index,
                          "problem": "Marked normal, but no cited answer contains a negative. Check the patient's own answers."})
        if flag in ("H*", "L*"):
            if not NUMBER.search(row.get("finding", "")):
                found.append({"field": "review_of_systems", "index": index,
                              "problem": f"Marked {flag} without a measured number."})
            if not RANGE.search(row.get("norm", "").lower()):
                found.append({"field": "review_of_systems", "index": index,
                              "problem": f"Marked {flag} without a printed reference range."})
    for index, text in enumerate(report.get("suggested_investigations") or []):
        lowered = text.lower()
        if MEDICINES.search(lowered) or DOSE.search(lowered):
            found.append({"field": "suggested_investigations", "index": index,
                          "problem": "Names a medicine or a dose. Investigations to consider must never suggest treatment."})
    return found
