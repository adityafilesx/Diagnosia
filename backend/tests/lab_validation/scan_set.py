"""Makes a set of synthetic lab report scans with the right answers alongside (WI-231).

Every name, value and laboratory is invented. Each layout is drawn as an image with no text
layer, then spoiled the way a phone scan is: blurred, tilted, shaded and grainy, or small and
heavily compressed. The scans go through the AI reading path, which is what this set scores.

They are printed text, so they are easier than a crumpled report photographed in bad light. A
good score here proves little. A bad one proves a lot.

    python -m backend.tests.lab_validation.scan_set /some/folder

The folder gets one JPEG per layout and condition, and truth.json. The set is the same every
time it is made, so scores from different days and models can be compared.
"""
import io
import json
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import List, Optional

import numpy
from PIL import Image, ImageDraw, ImageFilter, ImageFont

VERSION = "lab-scans-1"
PAGE = (1240, 1754)  # A4 at 150 dots an inch
SEED = 231


@dataclass
class Row:
    """One printed result and what a perfect reading of it gives."""
    name: str
    value: str
    unit: str = ""
    reference: str = ""
    flag: str = ""
    code: Optional[str] = None
    number: Optional[float] = None
    low: Optional[float] = None
    high: Optional[float] = None


@dataclass
class Layout:
    name: str
    header: List[str]
    rows: List[Row]
    patient: Optional[str] = None
    collected: Optional[str] = None
    style: str = "lines"  # lines, grid, range_first or two_columns
    footer: List[str] = field(default_factory=list)


def layouts() -> List[Layout]:
    return [
        Layout(
            "single_lines",
            ["Sunrise Diagnostics Laboratory", "Patient Name : Mr. Ravi Kumar   Age : 56 Years", "Sample Collected On : 12/03/2026", "Test   Result   Unit   Reference Range"],
            [
                Row("Haemoglobin", "11.2", "g/dL", "13.0 - 17.0", "L", "718-7", 11.2, 13, 17),
                Row("Total Leucocyte Count", "7,800", "/cumm", "4000 - 11000", "", "6690-2", 7800, 4000, 11000),
                Row("Platelet Count", "2.5", "lakh/cumm", "1.5 - 4.5", "", "777-3", 2.5, 1.5, 4.5),
                Row("Creatinine", "1.02", "mg/dl", "< 1.3", "", "2160-0", 1.02, None, 1.3),
            ],
            "Ravi Kumar", "2026-03-12",
        ),
        Layout(
            "bordered_table",
            ["City Care Labs", "Patient Name : Mrs. Sita Devi   Age : 44", "Report Date : 03-Jan-2026"],
            [
                Row("Hemoglobin", "12.4", "g/dL", "12.0 - 15.0", "", "718-7", 12.4, 12, 15),
                Row("Glucose, Fasting", "104", "mg/dL", "70 - 100", "H", "1558-6", 104, 70, 100),
                Row("HbA1c", "6.4", "%", "4.0 - 5.6", "H", "4548-4", 6.4, 4, 5.6),
                Row("TSH", "3.20", "uIU/mL", "0.27 - 4.20", "", "3016-3", 3.2, 0.27, 4.2),
            ],
            "Sita Devi", "2026-01-03", style="grid",
        ),
        Layout(
            "range_before_unit",
            ["Metro Lab", "Name : Mr. Imran Shaikh", "Collection Date : 15/06/2026", "Investigation   Value   Biological Ref. Interval   Unit"],
            [
                Row("Hemoglobin", "14.1", "g/dL", "13.0 - 17.0", "", "718-7", 14.1, 13, 17),
                Row("Total Cholesterol", "212", "mg/dL", "< 200", "", "2093-3", 212, None, 200),
                Row("HDL Cholesterol", "41", "mg/dL", "> 40", "", "2085-9", 41, 40, None),
                Row("Triglycerides", "168", "mg/dL", "< 150", "", "2571-8", 168, None, 150),
            ],
            "Imran Shaikh", "2026-06-15", style="range_first",
        ),
        Layout(
            "abnormal_marks",
            ["Lifeline Pathology Lab", "Patient Name : Mr. Mohan Das", "Reported On : 09/09/2026"],
            [
                Row("Hemoglobin", "7.1", "g/dL", "13.0 - 17.0", "Low", "718-7", 7.1, 13, 17),
                Row("Glucose, Fasting", "312", "mg/dL", "70 - 100", "H", "1558-6", 312, 70, 100),
                Row("Potassium", "6.2", "mmol/L", "3.5 - 5.1", "HH", "2823-3", 6.2, 3.5, 5.1),
                Row("ALT", "188", "U/L", "0 - 41", "*", "1742-6", 188, 0, 41),
            ],
            "Mohan Das", "2026-09-09",
        ),
        Layout(
            "two_columns",
            ["Northside Diagnostics", "Patient Name : Mr. Arun Patil", "Collected On : 05/02/2026"],
            [
                Row("Hemoglobin", "13.2", "g/dL", "13.0 - 17.0", "", "718-7", 13.2, 13, 17),
                Row("Creatinine", "1.1", "mg/dL", "0.7 - 1.3", "", "2160-0", 1.1, 0.7, 1.3),
                Row("MCV", "90", "fL", "83 - 101", "", "787-2", 90, 83, 101),
                Row("Urea", "31", "mg/dL", "15 - 40", "", "3091-6", 31, 15, 40),
            ],
            "Arun Patil", "2026-02-05", style="two_columns",
        ),
        Layout(
            "close_values",  # neighbouring rows with look-alike numbers: the wrong-row trap
            ["Apex Diagnostics", "Patient Name : Mrs. Rekha Iyer", "Collected On : 18 March 2026", "Test   Result   Unit   Reference Range"],
            [
                Row("Sodium", "138", "mmol/L", "136 - 145", "", "2951-2", 138, 136, 145),
                Row("Potassium", "4.1", "mmol/L", "3.5 - 5.1", "", "2823-3", 4.1, 3.5, 5.1),
                Row("Urea", "41", "mg/dL", "15 - 40", "H", "3091-6", 41, 15, 40),
                Row("Creatinine", "1.4", "mg/dL", "0.7 - 1.3", "H", "2160-0", 1.4, 0.7, 1.3),
                Row("Uric Acid", "6.1", "mg/dL", "3.5 - 7.2", "", "3084-1", 6.1, 3.5, 7.2),
            ],
            "Rekha Iyer", "2026-03-18",
        ),
        Layout(
            "indian_number_grouping",
            ["Heritage Lab", "Patient Name : Mr. Vikram Singh", "Collected On : 01/10/2026"],
            [
                Row("Platelet Count", "1,85,000", "/cumm", "1,50,000 - 4,10,000", "", "777-3", 185000, 150000, 410000),
                Row("Total Leucocyte Count", "11,240", "/cumm", "4,000 - 11,000", "H", "6690-2", 11240, 4000, 11000),
            ],
            "Vikram Singh", "2026-10-01",
        ),
        Layout(
            "missing_fields",
            ["Community Health Lab"],
            [
                Row("Hemoglobin", "11.8", "g/dL", "", "", "718-7", 11.8),
                Row("Creatinine", "0.9", "", "", "", "2160-0", 0.9),
                Row("Uric Acid", "6.1", "mg/dL", "3.5 - 7.2", "", "3084-1", 6.1, 3.5, 7.2),
            ],
            footer=["This report is for the treating doctor. Page 1 of 1"],
        ),
    ]


CONDITIONS = ("clean", "blurred", "tilted", "shaded_and_grainy", "small_and_compressed")


def _font(size: int):
    try:
        return ImageFont.load_default(size=size)
    except TypeError:  # an older Pillow has one small built-in size
        return ImageFont.load_default()


def _line(row: Row, style: str) -> str:
    parts = [row.name, row.value, row.flag, row.reference, row.unit] if style == "range_first" else [row.name, row.value, row.flag, row.unit, row.reference]
    return "   ".join(part for part in parts if part)


def draw(layout: Layout) -> Image.Image:
    """The page as a scanner would see a clean print: an image, with no text behind it."""
    page = Image.new("L", PAGE, 255)
    pen = ImageDraw.Draw(page)
    head, body = _font(34), _font(28)
    height = 90
    for index, text in enumerate(layout.header):
        pen.text((90, height), text, fill=0, font=head if index == 0 else body)
        height += 56
    height += 24
    if layout.style == "grid":
        columns = (90, 470, 650, 830, 1150)
        cells = [["Test", "Result", "Unit", "Reference"]] + [[row.name, f"{row.value} {row.flag}".strip(), row.unit, row.reference] for row in layout.rows]
        for cell_row in cells:
            for left, text in zip(columns, cell_row):
                pen.text((left + 10, height + 12), text, fill=0, font=body)
            pen.line((columns[0], height, columns[-1], height), fill=0, width=2)
            height += 58
        pen.line((columns[0], height, columns[-1], height), fill=0, width=2)
        for left in columns:
            pen.line((left, height - 58 * len(cells), left, height), fill=0, width=2)
    elif layout.style == "two_columns":
        half = (len(layout.rows) + 1) // 2
        top = height
        for index, row in enumerate(layout.rows):
            left = 90 if index % 2 == 0 else 650
            pen.text((left, top + (index // 2) * 56), _line(row, "lines").replace("   ", "  "), fill=0, font=_font(24))
        height = top + half * 56
    else:
        for row in layout.rows:
            pen.text((90, height), _line(row, layout.style), fill=0, font=body)
            height += 56
    height += 40
    for text in layout.footer:
        pen.text((90, height), text, fill=0, font=_font(22))
        height += 44
    return page


def spoil(page: Image.Image, condition: str, noise: numpy.random.Generator) -> bytes:
    """One way a scan goes wrong. Returns a JPEG."""
    image, quality = page, 85
    if condition == "blurred":
        image = image.filter(ImageFilter.GaussianBlur(1.6))
    elif condition == "tilted":
        image = image.rotate(2.5, expand=True, fillcolor=255, resample=Image.BICUBIC)
    elif condition == "shaded_and_grainy":
        shade = Image.linear_gradient("L").rotate(90).resize(image.size)
        image = Image.blend(image, shade, 0.22)
        # Grain from a seeded generator, so the same scan comes out every time the set is made.
        speckle = noise.normal(128, 40, (image.height, image.width)).clip(0, 255).astype("uint8")
        image = Image.blend(image, Image.fromarray(speckle, "L"), 0.12).filter(ImageFilter.GaussianBlur(0.6))
    elif condition == "small_and_compressed":
        image = image.resize((image.width // 2, image.height // 2), Image.BILINEAR)
        quality = 35
    buffer = io.BytesIO()
    image.convert("RGB").save(buffer, format="JPEG", quality=quality)
    return buffer.getvalue()


def truth_for(layout: Layout) -> dict:
    return {
        "layout": layout.name,
        "patient": layout.patient,
        "collected": layout.collected,
        "results": [asdict(row) for row in layout.rows],
    }


def build() -> List[dict]:
    """Every scan with its answers: {"file", "condition", "image" (JPEG bytes), **truth}."""
    noise = numpy.random.default_rng(SEED)
    made = []
    for layout in layouts():
        page = draw(layout)
        for condition in CONDITIONS:
            made.append({"file": f"{layout.name}__{condition}.jpg", "condition": condition, "image": spoil(page, condition, noise), **truth_for(layout)})
    return made


def write(folder: Path) -> dict:
    folder.mkdir(parents=True, exist_ok=True)
    items = build()
    for item in items:
        (folder / item["file"]).write_bytes(item["image"])
    truth = {
        "version": VERSION,
        "note": "Synthetic scans. Every name and value is invented.",
        "scans": [{key: value for key, value in item.items() if key != "image"} for item in items],
    }
    (folder / "truth.json").write_text(json.dumps(truth, indent=1), encoding="utf-8")
    return truth


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("Usage: python -m backend.tests.lab_validation.scan_set /some/folder")
    made = write(Path(sys.argv[1]))
    rows = sum(len(scan["results"]) for scan in made["scans"])
    print(f"Wrote {len(made['scans'])} scans with {rows} results to {sys.argv[1]} ({VERSION}).")
