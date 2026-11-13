"""
Khanna Travels & Holidays — "Check Forms" (compare filled forms with the passport)
=================================================================================

Two jobs, both deterministic (no AI, no guessing presented as fact):

1. extract_document(path)  — reads what an uploaded file says:
     * a fillable PDF: every form field's label and value (most reliable);
       a form we have a definition for (visa_forms/) is read field by field
       with exact meanings, including which radio button is ticked;
     * a PDF with a text layer: its text;
     * a scanned PDF or a photo: OCR text (the same OCR engine the hotel
       voucher reader uses — Tesseract or Google Vision).

2. check_form(form, passports, supporting) — compares one filled form with
   the passport details staff confirmed on the page (and, for details a
   passport does not hold — address, phone, hotel — with the supporting
   documents) and lists what to correct.

Every result is a suggestion for staff to verify (project rules 10 and 19).
Nothing is logged: passport data stays in this request only (rule 11).
"""

from __future__ import annotations

import os
import re
import unicodedata
from datetime import date, datetime
from difflib import SequenceMatcher
from typing import Any, Dict, Iterable, List, Optional, Tuple

import visa_forms

MAX_OCR_PAGES = 6
TEXT_LAYER_MIN_LETTERS = 40

# ---------------------------------------------------------------------------
# Extraction
# ---------------------------------------------------------------------------

_BUTTON_LOOKS = {"/Type", "/Subtype", "/FormType", "/BBox", "/Matrix", "/Resources", "/Filter", "/Length"}


def _pdf_fields(path: str) -> Tuple[List[Dict[str, Any]], Dict[str, str], int, str]:
    """Returns (fields, raw values by qualified name, page count, text layer)."""
    from pypdf import PdfReader

    reader = PdfReader(path)
    if reader.is_encrypted:
        try:
            reader.decrypt("")
        except Exception:  # noqa: BLE001 — a form we cannot open simply has no fields
            return [], {}, len(reader.pages), ""

    raw_values: Dict[str, str] = {}
    fields: List[Dict[str, Any]] = []
    seen = set()
    for page_index, page in enumerate(reader.pages):
        for ref in page.get("/Annots", []) or []:
            widget = ref.get_object()
            if widget.get("/Subtype") != "/Widget":
                continue
            name = visa_forms.qualified_name(widget)
            if name in seen:
                continue
            seen.add(name)
            parent_ref = widget.get("/Parent")
            parent = parent_ref.get_object() if parent_ref is not None else None
            holder = widget if "/T" in widget else (parent or widget)
            ftype = str(holder.get("/FT") or (parent.get("/FT") if parent else "") or "")
            value = holder.get("/V")
            if value is None and parent is not None:
                value = parent.get("/V")
            text = "" if value is None else str(value)
            if ftype == "/Btn":
                # Checkbox / radio: "/Off" = nothing ticked; a push button has no value.
                text = "" if text in ("", "/Off", "None") else text
            label = str(holder.get("/TU") or (parent.get("/TU") if parent else "") or "").strip()
            label = re.sub(r"\s+", " ", label)
            raw_values[name] = text
            short = name.split(".")[-1]
            fields.append({
                "name": name,
                "label": label if label and label != re.sub(r"\[\d+\]$", "", short) else "",
                "value": re.sub(r"\s+", " ", text).strip(),
                "type": {"/Tx": "text", "/Ch": "choice", "/Btn": "button"}.get(ftype, "other"),
                "page": page_index + 1,
            })
    try:
        text_layer = "\n".join((p.extract_text() or "") for p in reader.pages)
    except Exception:  # noqa: BLE001
        text_layer = ""
    return fields, raw_values, len(reader.pages), text_layer


OCR_MIN_SIDE = 2000


def _ocr_text(path: str, max_pages: int = MAX_OCR_PAGES) -> Tuple[str, int]:
    import cv2
    import numpy as np

    import ocr_providers
    import ocr_runner

    pages = ocr_runner.load_pages(path)
    provider = ocr_providers.get_ocr_provider()
    texts = []
    for pil in pages[:max_pages]:
        gray = cv2.cvtColor(np.array(pil.convert("RGB")), cv2.COLOR_RGB2GRAY)
        # Phone screenshots (a WhatsApp reply, an email) have small text that
        # Tesseract misreads — "gmaicom", "820012345". Enlarging small images
        # first (to about OCR_MIN_SIDE px on the long side, at most 3x) reads
        # them much more reliably. Large scans and PDF pages are left as they are.
        longest = max(gray.shape[:2])
        if longest < OCR_MIN_SIDE:
            scale = min(3.0, OCR_MIN_SIDE / float(longest))
            gray = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
        texts.append(provider.ocr_text(gray, config="--oem 3 --psm 3"))
    return "\n".join(t for t in texts if t), len(pages)


def _letters(text: str) -> int:
    return sum(1 for ch in text or "" if ch.isalpha())


def extract_document(path: str, allow_ocr: bool = True) -> Dict[str, Any]:
    """What one uploaded file says. Shape:
    {method, formId, formName, pages, fields: [{label, value, key?, compare?}], text, notes}"""
    ext = os.path.splitext(path)[1].lower()
    result: Dict[str, Any] = {"method": "", "formId": None, "formName": None, "pages": 1, "fields": [], "text": "", "notes": []}

    if ext == ".pdf":
        fields, raw_values, pages, text_layer = _pdf_fields(path)
        result["pages"] = pages
        definition = visa_forms.identify_form(raw_values.keys()) if raw_values else None
        if definition:
            result["formId"] = definition["id"]
            result["formName"] = definition["name"]
            result["fields"] = visa_forms.read_known_form(definition, raw_values)
            result["method"] = "form-fields"
        else:
            filled = [f for f in fields if f["value"] and f["type"] != "button"]
            if filled:
                result["fields"] = [
                    {"key": f["name"], "label": f["label"] or f["name"].split(".")[-1], "value": f["value"], "compare": guess_compare_key(f["label"]), "type": f["type"]}
                    for f in fields if f["type"] != "button"
                ]
                result["method"] = "form-fields"
        result["text"] = text_layer.strip()
        if not result["method"]:
            if _letters(text_layer) >= TEXT_LAYER_MIN_LETTERS:
                result["method"] = "text-layer"
            elif allow_ocr:
                result["text"], result["pages"] = _ocr_text(path)
                result["method"] = "ocr"
                if pages > MAX_OCR_PAGES:
                    result["notes"].append(f"Only the first {MAX_OCR_PAGES} of {pages} pages were read.")
            else:
                result["method"] = "none"
    else:
        if allow_ocr:
            result["text"], result["pages"] = _ocr_text(path)
            result["method"] = "ocr"
        else:
            result["method"] = "none"

    if result["method"] == "ocr":
        result["notes"].append("Read by OCR — words can be misread; check anything flagged against the original.")
    if not result["fields"] and _letters(result["text"]) < 10:
        result["notes"].append("Almost no text could be read from this file.")
    return result


# ---------------------------------------------------------------------------
# Guessing what an unknown form's field holds (from its label)
# ---------------------------------------------------------------------------

_LABEL_RULES: List[Tuple[str, Tuple[str, ...], Tuple[str, ...]]] = [
    ("placeOfBirth", ("place of birth", "birth place", "city of birth", "town of birth"), ()),
    ("dob", ("date of birth", "birth date", "dob", "d.o.b"), ()),
    ("surname", ("surname", "family name", "last name"), ("father", "mother", "spouse", "maiden", "previous", "former")),
    ("givenNames", ("given name", "first name", "forename", "first and middle"), ("father", "mother", "spouse")),
    ("passportNumber", ("passport no", "passport number", "travel document no", "travel document number", "document number", "passport #"), ("old", "previous")),
    ("issueDate", ("date of issue", "issue date", "issued on", "date issued"), ("visa",)),
    ("expiryDate", ("date of expiry", "expiry date", "expiration", "valid until", "date of expiration", "expiry"), ("visa",)),
    ("issuePlace", ("place of issue", "issued at", "issuing place"), ()),
    ("issuingAuthority", ("issuing authority", "issued by"), ()),
    ("nationality", ("nationality", "citizenship"), ("former", "other", "previous", "at birth", "immigration")),
    ("sex", ("sex", "gender"), ()),
    ("arrivalDate", ("date of arrival", "arrival date", "intended date of arrival"), ()),
]


def guess_compare_key(label: str) -> str:
    text = (label or "").lower()
    if not text:
        return ""
    for key, includes, excludes in _LABEL_RULES:
        if any(word in text for word in includes) and not any(word in text for word in excludes):
            return key
    return ""


# ---------------------------------------------------------------------------
# Normalising values
# ---------------------------------------------------------------------------


def _ascii(text: str) -> str:
    return unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode("ascii")


def norm_words(text: str) -> List[str]:
    return [w for w in re.sub(r"[^A-Z0-9]+", " ", _ascii(text).upper()).split() if w]


def norm_compact(text: str) -> str:
    return "".join(norm_words(text))


_MONTHS = {m: i for i, m in enumerate(["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"], 1)}


def _safe_date(y: int, m: int, d: int) -> Optional[date]:
    try:
        if y < 100:
            y += 2000 if y < 50 else 1900
        return date(y, m, d)
    except ValueError:
        return None


def parse_date_candidates(text: str) -> List[date]:
    """All readings of one date string, day-first first. "05/04/2030" gives
    5 Apr and 4 May — the second only matters for spotting a swapped order."""
    s = (text or "").strip().upper()
    if not s:
        return []
    out: List[date] = []
    m = re.fullmatch(r"(\d{4})[-/. ](\d{1,2})[-/. ](\d{1,2})", s)
    if m:
        d = _safe_date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        return [d] if d else []
    m = re.fullmatch(r"(\d{1,2})[-/. ]+(\d{1,2})[-/. ]+(\d{2}|\d{4})", s)
    if m:
        a, b, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        day_first, month_first = _safe_date(y, b, a), _safe_date(y, a, b)
        # The first item is always the day-first reading (None when that is
        # not a real date, e.g. "05/14/1980"), so callers can tell a
        # month-first date apart from a correct one.
        out = [day_first]
        if month_first and month_first != day_first:
            out.append(month_first)
        return out if any(out) else []
    m = re.fullmatch(r"(\d{2})(\d{2})(\d{4})", s)
    if m:
        d = _safe_date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        return [d] if d else []
    m = re.fullmatch(r"(\d{1,2})[ -/.]*([A-Z]{3})[A-Z]*[ -/.,]*(\d{2}|\d{4})", s)
    if m and m.group(2) in _MONTHS:
        d = _safe_date(int(m.group(3)), _MONTHS[m.group(2)], int(m.group(1)))
        return [d] if d else []
    m = re.fullmatch(r"([A-Z]{3})[A-Z]*[ -/.]*(\d{1,2})[ ,]+(\d{4})", s)
    if m and m.group(1) in _MONTHS:
        d = _safe_date(int(m.group(3)), _MONTHS[m.group(1)], int(m.group(2)))
        return [d] if d else []
    return out


_DATE_IN_TEXT = re.compile(
    r"\b(\d{4}[-/.]\d{1,2}[-/.]\d{1,2}|\d{1,2}[-/.]\d{1,2}[-/.](?:\d{4}|\d{2})|\d{1,2}[ -]?(?:JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)[A-Z]*[ -,]*\d{4})\b",
    re.I,
)


def dates_in_text(text: str) -> List[Tuple[str, List[date]]]:
    found = []
    for m in _DATE_IN_TEXT.finditer(text or ""):
        cands = parse_date_candidates(m.group(1))
        if cands:
            found.append((m.group(1), cands))
    return found


def primary_date(text: str) -> Optional[date]:
    cands = parse_date_candidates(text)
    return cands[0] if cands else None


def iso_to_date(value: str) -> Optional[date]:
    try:
        return datetime.strptime((value or "").strip()[:10], "%Y-%m-%d").date()
    except ValueError:
        return primary_date(value)


def show_date(d: Optional[date]) -> str:
    return d.strftime("%d/%m/%Y") if d else ""


def edit_distance(a: str, b: str) -> int:
    if a == b:
        return 0
    if not a or not b:
        return max(len(a), len(b))
    # Optimal-string-alignment distance: a swap of two neighbouring letters
    # ("SHRAMA" / "SHARMA") counts as ONE edit, the commonest typing slip.
    rows = [list(range(len(b) + 1))]
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cost = min(rows[-1][j] + 1, cur[j - 1] + 1, rows[-1][j - 1] + (ca != cb))
            if i > 1 and j > 1 and ca == b[j - 2] and a[i - 2] == cb:
                cost = min(cost, rows[-2][j - 2] + 1)
            cur.append(cost)
        rows.append(cur)
    return rows[-1][-1]


_LOOKALIKE = str.maketrans({"O": "0", "I": "1", "L": "1", "S": "5", "B": "8", "Z": "2", "Q": "0", "G": "6"})


def _lookalike(text: str) -> str:
    return text.translate(_LOOKALIKE)


_SEX_WORDS = {"M": "M", "MALE": "M", "F": "F", "FEMALE": "F", "X": "X", "OTHER": "X", "TRANSGENDER": "X"}


def norm_sex(value: str) -> str:
    words = norm_words(value)
    return _SEX_WORDS.get(words[0], "") if words else ""


# Nationality: the passport says "INDIAN" (or the code "IND"); forms write
# INDIA / INDIAN / IND / REPUBLIC OF INDIA. These are the same answer.
_NATIONALITY_ALIASES = {
    "IND": "INDIA", "INDIAN": "INDIA", "REPUBLIC OF INDIA": "INDIA", "BHARAT": "INDIA",
    "USA": "UNITED STATES", "AMERICAN": "UNITED STATES", "US": "UNITED STATES", "UNITED STATES OF AMERICA": "UNITED STATES",
    "GBR": "UNITED KINGDOM", "BRITISH": "UNITED KINGDOM", "UK": "UNITED KINGDOM", "BRITISH CITIZEN": "UNITED KINGDOM",
    "NPL": "NEPAL", "NEPALESE": "NEPAL", "NEPALI": "NEPAL",
    "LKA": "SRI LANKA", "SRI LANKAN": "SRI LANKA",
    "BGD": "BANGLADESH", "BANGLADESHI": "BANGLADESH",
    "ARE": "UNITED ARAB EMIRATES", "EMIRATI": "UNITED ARAB EMIRATES", "UAE": "UNITED ARAB EMIRATES",
    "CAN": "CANADA", "CANADIAN": "CANADA", "AUS": "AUSTRALIA", "AUSTRALIAN": "AUSTRALIA",
    "SGP": "SINGAPORE", "SINGAPOREAN": "SINGAPORE", "JPN": "JAPAN", "JAPANESE": "JAPAN",
}


def norm_nationality(value: str) -> str:
    text = " ".join(norm_words(value))
    if not text:
        return ""
    if text in _NATIONALITY_ALIASES:
        return _NATIONALITY_ALIASES[text]
    for suffix in ("IAN", "AN", "ESE", "I", "N"):
        if text.endswith(suffix) and len(text) - len(suffix) >= 4:
            stem = text[: -len(suffix)]
            for full in set(_NATIONALITY_ALIASES.values()):
                if full.startswith(stem):
                    return full
    return text


# ---------------------------------------------------------------------------
# One comparison
# ---------------------------------------------------------------------------

FIELD_LABELS = {
    "fullName": "Full name",
    "surname": "Surname",
    "givenNames": "Given names",
    "dob": "Date of birth",
    "placeOfBirth": "Place of birth",
    "sex": "Sex",
    "nationality": "Nationality",
    "passportNumber": "Passport number",
    "passportType": "Passport type",
    "issueDate": "Date of issue",
    "expiryDate": "Date of expiry",
    "issuePlace": "Place of issue",
    "issuingAuthority": "Issuing authority",
}

OK, CORRECT, CHECK, MISSING, INFO = "ok", "correct", "check", "missing", "info"


def _finding(status: str, field: str, form_value: str, expected: str, source: str, message: str, label: str = "") -> Dict[str, Any]:
    return {
        "status": status,
        "field": field,
        "label": label or FIELD_LABELS.get(field, field),
        "formValue": form_value,
        "expected": expected,
        "source": source,
        "message": message,
    }


def _is_blankish(value: str) -> bool:
    return norm_compact(value) in ("", "NA", "NIL", "NONE", "NOTAPPLICABLE")


def compare_name(field: str, form_value: str, passport_value: str, source: str, label: str = "") -> Dict[str, Any]:
    fw, pw = norm_words(form_value), norm_words(passport_value)
    if not pw:
        return _finding(INFO, field, form_value, "", source, "The passport has no value to compare with.", label)
    if _is_blankish(form_value):
        return _finding(MISSING, field, form_value, passport_value, source, "Empty in the form — write it exactly as in the passport.", label)
    if fw == pw:
        exact = form_value.strip().upper() == passport_value.strip().upper()
        return _finding(OK, field, form_value, passport_value, source, "Matches the passport." if exact else "Matches the passport (only spacing / punctuation differs).", label)
    if sorted(fw) == sorted(pw):
        return _finding(CHECK, field, form_value, passport_value, source, "Same names in a different order — write them in the passport's order.", label)
    if "".join(fw) == "".join(pw):
        return _finding(CORRECT, field, form_value, passport_value, source, "Spaces between the names differ from the passport.", label)
    extra = [w for w in fw if w not in pw]
    missing = [w for w in pw if w not in fw]
    if not missing and extra and field == "givenNames":
        return _finding(CHECK, field, form_value, passport_value, source, "The form has extra name(s) not in the passport: " + ", ".join(extra) + ".", label)
    ratio = SequenceMatcher(None, " ".join(fw), " ".join(pw)).ratio()
    pairs = []
    for w in extra:
        best = min(missing, key=lambda p: edit_distance(w, p)) if missing else None
        if best and edit_distance(w, best) <= max(1, len(best) // 3):
            pairs.append(f"'{w}' should be '{best}'")
    if pairs:
        return _finding(CORRECT, field, form_value, passport_value, source, "Spelling differs from the passport: " + "; ".join(pairs) + ".", label)
    if missing and not extra:
        return _finding(CORRECT, field, form_value, passport_value, source, "Missing from the form: " + ", ".join(missing) + ".", label)
    msg = "Does not match the passport." if ratio < 0.6 else "Differs from the passport."
    return _finding(CORRECT, field, form_value, passport_value, source, msg, label)


def compare_date(field: str, form_value: str, passport_iso: str, source: str, label: str = "") -> Dict[str, Any]:
    expected = iso_to_date(passport_iso)
    if not expected:
        return _finding(INFO, field, form_value, "", source, "The passport has no date to compare with.", label)
    shown = show_date(expected)
    if _is_blankish(form_value):
        return _finding(MISSING, field, form_value, shown, source, "Empty in the form.", label)
    cands = parse_date_candidates(form_value)
    if not cands:
        return _finding(CHECK, field, form_value, shown, source, "Not a date the system can read — check the format.", label)
    if cands[0] is None:
        if expected in cands:
            return _finding(CORRECT, field, form_value, shown, source, "Written month first — write it as DD/MM/YYYY.", label)
        return _finding(CORRECT, field, form_value, shown, source, "Not a valid DD/MM/YYYY date, and does not match the passport.", label)
    if cands[0] == expected:
        return _finding(OK, field, form_value, shown, source, "Matches the passport.", label)
    if expected in cands[1:]:
        return _finding(CORRECT, field, form_value, shown, source, "Day and month are swapped — write it as DD/MM/YYYY.", label)
    got = cands[0]
    if (got.day, got.month) == (expected.day, expected.month):
        msg = f"The year is wrong ({got.year} instead of {expected.year})."
    elif got.year == expected.year and got.month == expected.month:
        msg = f"The day is wrong ({got.day} instead of {expected.day})."
    else:
        msg = "Does not match the passport."
    return _finding(CORRECT, field, form_value, shown, source, msg, label)


def compare_passport_number(form_value: str, passport_value: str, source: str, label: str = "") -> Dict[str, Any]:
    field = "passportNumber"
    p = norm_compact(passport_value)
    if not p:
        return _finding(INFO, field, form_value, "", source, "The passport has no number to compare with.", label)
    if _is_blankish(form_value):
        return _finding(MISSING, field, form_value, passport_value, source, "Empty in the form.", label)
    f = norm_compact(form_value)
    if f == p:
        return _finding(OK, field, form_value, passport_value, source, "Matches the passport.", label)
    if _lookalike(f) == _lookalike(p):
        return _finding(CORRECT, field, form_value, passport_value, source, "A look-alike character is wrong (e.g. O/0, I/1, S/5).", label)
    if sorted(f) == sorted(p) and len(f) == len(p):
        return _finding(CORRECT, field, form_value, passport_value, source, "Same characters in a different order — check for swapped digits.", label)
    d = edit_distance(f, p)
    if d <= 2:
        return _finding(CORRECT, field, form_value, passport_value, source, f"{d} character(s) differ from the passport.", label)
    return _finding(CORRECT, field, form_value, passport_value, source, "Does not match the passport — is this the right passport?", label)


def compare_place(field: str, form_value: str, passport_value: str, source: str, label: str = "") -> Dict[str, Any]:
    pw = norm_words(passport_value)
    if not pw:
        return _finding(INFO, field, form_value, "", source, "The passport has no value to compare with.", label)
    if _is_blankish(form_value):
        return _finding(MISSING, field, form_value, passport_value, source, "Empty in the form.", label)
    fw = norm_words(form_value)
    f, p = " ".join(fw), " ".join(pw)
    if f == p:
        return _finding(OK, field, form_value, passport_value, source, "Matches the passport.", label)
    if all(w in fw for w in pw):
        return _finding(OK, field, form_value, passport_value, source, "Contains the passport's wording.", label)
    if p in f or f in p:
        return _finding(OK, field, form_value, passport_value, source, "Matches the passport's wording in part.", label)
    if pw and pw[0] in fw:
        # e.g. passport "MUMBAI, MAHARASHTRA", form "INDIA MUMBAI": the city is there.
        return _finding(OK, field, form_value, passport_value, source, "The city matches the passport.", label)
    best = max((SequenceMatcher(None, w, x).ratio() for w in fw for x in pw), default=0)
    if best >= 0.8:
        return _finding(CORRECT, field, form_value, passport_value, source, "Spelling differs from the passport.", label)
    return _finding(CHECK, field, form_value, passport_value, source, "Different from the passport — check.", label)


def compare_sex(form_value: str, passport_value: str, source: str, label: str = "") -> Dict[str, Any]:
    field = "sex"
    p = norm_sex(passport_value)
    if not p:
        return _finding(INFO, field, form_value, "", source, "The passport has no sex to compare with.", label)
    shown = {"M": "Male", "F": "Female", "X": "Other"}.get(p, p)
    if _is_blankish(form_value):
        return _finding(MISSING, field, form_value, shown, source, "Nothing is ticked in the form.", label)
    f = norm_sex(form_value)
    if f == p:
        return _finding(OK, field, form_value, shown, source, "Matches the passport.", label)
    return _finding(CORRECT, field, form_value, shown, source, "The wrong box is ticked.", label)


def compare_nationality(form_value: str, passport: Dict[str, str], source: str, label: str = "") -> Dict[str, Any]:
    field = "nationality"
    expected_raw = passport.get("nationality") or passport.get("countryCode") or ""
    p = norm_nationality(expected_raw)
    if not p:
        return _finding(INFO, field, form_value, "", source, "The passport has no nationality to compare with.", label)
    if _is_blankish(form_value):
        return _finding(MISSING, field, form_value, expected_raw, source, "Empty in the form.", label)
    if norm_nationality(form_value) == p:
        return _finding(OK, field, form_value, expected_raw, source, "Matches the passport.", label)
    return _finding(CORRECT, field, form_value, expected_raw, source, "Different nationality from the passport.", label)


def compare_passport_type(form_value: str, passport_type: str, source: str, label: str = "") -> Dict[str, Any]:
    field = "passportType"
    code = norm_compact(passport_type)[:2]
    expected = {"P": "Ordinary", "PP": "Ordinary", "PD": "Diplomatic", "D": "Diplomatic", "PS": "Official", "S": "Official", "PO": "Official"}.get(code) or {"P": "Ordinary"}.get(code[:1], "")
    if not expected:
        return _finding(INFO, field, form_value, "", source, "The passport type is not known.", label)
    if _is_blankish(form_value):
        return _finding(MISSING, field, form_value, expected, source, "Nothing is ticked in the form.", label)
    if norm_compact(form_value).startswith(norm_compact(expected)[:5]):
        return _finding(OK, field, form_value, expected, source, "Matches the passport type.", label)
    return _finding(CORRECT, field, form_value, expected, source, f"An ordinary passport (type {passport_type or 'P'}) should be ticked as {expected}.", label)


# ---------------------------------------------------------------------------
# Passport details as the page sends them
# ---------------------------------------------------------------------------

PASSPORT_KEYS = ("surname", "givenNames", "dob", "sex", "nationality", "countryCode", "placeOfBirth",
                 "passportNumber", "passportType", "issueDate", "expiryDate", "issuePlace", "issuingAuthority")


def _clean_passport(p: Dict[str, Any]) -> Dict[str, str]:
    return {k: str((p or {}).get(k) or "").strip() for k in PASSPORT_KEYS + ("label",)}


def choose_passport(form_fields: List[Dict[str, Any]], text: str, passports: List[Dict[str, str]]) -> Tuple[Optional[Dict[str, str]], str]:
    """With several passports on the page, the one the form is about: the
    passport number first, then the name."""
    if not passports:
        return None, ""
    if len(passports) == 1:
        return passports[0], ""
    form_text = " ".join(f.get("value", "") for f in form_fields) + " " + (text or "")
    compact = norm_compact(form_text)
    words = set(norm_words(form_text))
    scored = []
    for p in passports:
        score = 0.0
        number = norm_compact(p.get("passportNumber"))
        if number and number in compact:
            score += 10
        name = norm_words(p.get("surname")) + norm_words(p.get("givenNames"))
        if name:
            score += 5 * sum(1 for w in name if w in words) / len(name)
        scored.append((score, p))
    scored.sort(key=lambda s: -s[0])
    best_score, best = scored[0]
    if best_score <= 0:
        return passports[0], "No passport's number or name was found in this form; compared with the first passport."
    if len(scored) > 1 and scored[1][0] == best_score:
        return best, "Two passports match this form equally well; compared with " + (best.get("label") or "the first") + "."
    return best, ""


# ---------------------------------------------------------------------------
# Fillable form: field by field
# ---------------------------------------------------------------------------


def _compare_field(key: str, value: str, passport: Dict[str, str], source: str, label: str) -> Optional[Dict[str, Any]]:
    if key == "fullName":
        # One box for the whole name (Singapore Form 14A): surname first as on
        # the passport; given names first is also accepted.
        surname_first = f"{passport.get('surname', '')} {passport.get('givenNames', '')}".strip()
        given_first = f"{passport.get('givenNames', '')} {passport.get('surname', '')}".strip()
        if norm_words(value) == norm_words(given_first) and norm_words(value) != norm_words(surname_first):
            return _finding(OK, "fullName", value, given_first, source, "Matches the passport (given names first).", label)
        result = compare_name("fullName", value, surname_first, source, label)
        if result["status"] == CHECK and "different order" in result["message"]:
            result["message"] = "Same names in a different order — the passport order is surname, then given names."
        return result
    if key == "surname":
        return compare_name("surname", value, passport.get("surname"), source, label)
    if key == "givenNames":
        return compare_name("givenNames", value, passport.get("givenNames"), source, label)
    if key in ("dob", "issueDate", "expiryDate"):
        return compare_date(key, value, passport.get(key), source, label)
    if key == "passportNumber":
        return compare_passport_number(value, passport.get("passportNumber"), source, label)
    if key in ("issuePlace", "placeOfBirth", "issuingAuthority"):
        if not passport.get(key):
            return None
        return compare_place(key, value, passport.get(key), source, label)
    if key == "sex":
        return compare_sex(value, passport.get("sex"), source, label)
    if key == "nationality":
        return compare_nationality(value, passport, source, label)
    if key == "passportType":
        return compare_passport_type(value, passport.get("passportType"), source, label)
    return None


def _date_rules(fields: List[Dict[str, Any]], passport: Optional[Dict[str, str]]) -> List[Dict[str, Any]]:
    """Checks that need no second document: passport valid 6 months beyond
    arrival, issue before expiry, birth date in the past."""
    out = []
    by_key = {f.get("compare"): f for f in fields if f.get("compare")}
    arrival_field = by_key.get("arrivalDate")
    arrival = primary_date(arrival_field["value"]) if arrival_field else None
    expiry = iso_to_date(passport.get("expiryDate")) if passport else None
    if not expiry and by_key.get("expiryDate"):
        expiry = primary_date(by_key["expiryDate"]["value"])
    if arrival:
        if arrival < date.today():
            out.append(_finding(CHECK, "arrivalDate", arrival_field["value"], "", "Form", "The arrival date is in the past.", arrival_field.get("label") or "Date of arrival"))
        if expiry:
            months = (expiry.year - arrival.year) * 12 + (expiry.month - arrival.month) - (1 if expiry.day < arrival.day else 0)
            if expiry <= arrival:
                out.append(_finding(CORRECT, "expiryDate", show_date(expiry), "", "Passport", "The passport expires before the arrival date.", "Passport validity"))
            elif months < 6:
                out.append(_finding(CHECK, "expiryDate", show_date(expiry), "", "Passport", f"The passport is valid for only {months} month(s) after arrival — many countries need 6.", "Passport validity"))
    dob_field = by_key.get("dob")
    if dob_field:
        born = primary_date(dob_field["value"])
        if born and born > date.today():
            out.append(_finding(CORRECT, "dob", dob_field["value"], "", "Form", "The date of birth is in the future.", dob_field.get("label") or "Date of birth"))
    return out


def _required_blanks(definition: Optional[Dict[str, Any]], fields: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not definition:
        return []
    required = {f["key"]: f for f in visa_forms.iter_fields(definition) if f.get("required") and (f.get("pdf") or f.get("pdfParts"))}
    out = []
    for f in fields:
        spec = required.get(f["key"])
        if spec and not f.get("compare") and not (f.get("value") or "").strip():
            what = "No answer is ticked." if spec.get("type") in ("radio", "yesno") else "Empty in the form."
            out.append(_finding(MISSING, f["key"], "", "", "Form", what, spec["label"]))
    return out


# ---------------------------------------------------------------------------
# Supporting documents
# ---------------------------------------------------------------------------


def _doc_corpus(doc: Dict[str, Any]) -> str:
    parts = [doc.get("text") or ""]
    parts += [str(f.get("value") or "") for f in doc.get("fields") or []]
    return "\n".join(parts)


def _coverage(value: str, corpus_words: List[str]) -> float:
    words = [w for w in norm_words(value) if len(w) >= 2]
    if not words:
        return 0.0
    bag = set(corpus_words)
    hit = 0
    for w in words:
        if w in bag:
            hit += 1
        elif len(w) >= 5 and any(abs(len(w) - len(b)) <= 1 and edit_distance(w, b) <= 1 for b in bag if b[:1] == w[:1]):
            hit += 0.8
    return hit / len(words)


_SKIP_SUPPORT_KEYS = set(FIELD_LABELS) | {"arrivalDate"}


def check_with_supporting(fields: List[Dict[str, Any]], supporting: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Details a passport does not hold (address, phone, hotel, employer ...)
    are looked for in the supporting documents. Found = consistent; not found
    = "please check", never "wrong" (the document may simply not say it)."""
    if not supporting:
        return []
    corpora = []
    for doc in supporting:
        corpus = _doc_corpus(doc)
        corpora.append((doc.get("fileName") or "Supporting document", norm_words(corpus), norm_compact(corpus)))
    out = []
    for f in fields:
        value = (f.get("value") or "").strip()
        if f.get("compare") in _SKIP_SUPPORT_KEYS or f.get("type") in ("radio", "yesno", "button"):
            continue
        if _is_blankish(value) or value == "-" or len(norm_compact(value)) < 4:
            continue
        digits = re.sub(r"\D", "", value)
        is_phone = len(digits) >= 7 and len(digits) >= len(norm_compact(value)) * 0.6
        best_name, best_score = "", 0.0
        for name, words, compact in corpora:
            if is_phone:
                score = 1.0 if digits[-8:] in re.sub(r"\D", "", compact) else 0.0
            else:
                score = _coverage(value, words)
            if score > best_score:
                best_name, best_score = name, score
        label = f.get("label") or f.get("key")
        if best_score >= 0.85:
            out.append(_finding(OK, f.get("key"), value, "", best_name, "Found in " + best_name + ".", label))
        elif best_score >= 0.5 and len([w for w in norm_words(value) if len(w) >= 2]) >= 3:
            # "Partly found" only means something for a longer value (an
            # address); for one or two words a single shared word is chance.
            out.append(_finding(CHECK, f.get("key"), value, "", best_name, f"Only partly found in {best_name} — compare the wording.", label))
        else:
            out.append(_finding(INFO, f.get("key"), value, "", "", "Not found in the supporting documents.", label))
    return out


# ---------------------------------------------------------------------------
# Text-only document (scanned or non-fillable form)
# ---------------------------------------------------------------------------


def check_text(text: str, passport: Dict[str, str], source: str) -> List[Dict[str, Any]]:
    """Without labelled fields the only honest check is: is each passport
    detail written somewhere in the form, and if not, is something very
    close to it written (a typo)?"""
    out = []
    words = norm_words(text)
    compact = norm_compact(text)
    bag = set(words)

    number = norm_compact(passport.get("passportNumber"))
    if number:
        if number in compact:
            out.append(_finding(OK, "passportNumber", passport["passportNumber"], passport["passportNumber"], source, "Found in the form."))
        else:
            near = [w for w in bag if len(w) == len(number) and any(ch.isdigit() for ch in w) and edit_distance(w, number) <= 2]
            near += [w for w in bag if _lookalike(w) == _lookalike(number) and w not in near]
            if near:
                out.append(_finding(CORRECT, "passportNumber", near[0], passport["passportNumber"], source, "Written differently in the form."))
            else:
                out.append(_finding(MISSING, "passportNumber", "", passport["passportNumber"], source, "Not found in the form."))

    for key in ("surname", "givenNames"):
        names = norm_words(passport.get(key))
        if not names:
            continue
        missing, typos = [], []
        for n in names:
            if n in bag:
                continue
            close = [w for w in bag if len(n) >= 4 and abs(len(w) - len(n)) <= 2 and w[:1] == n[:1] and edit_distance(w, n) <= max(1, len(n) // 4)]
            (typos if close else missing).append((n, close[0] if close else ""))
        if not missing and not typos:
            out.append(_finding(OK, key, passport[key], passport[key], source, "Found in the form."))
        elif typos:
            out.append(_finding(CORRECT, key, ", ".join(t[1] for t in typos), passport[key], source,
                                "Spelling differs: " + "; ".join(f"'{t[1]}' should be '{t[0]}'" for t in typos) + "."))
        else:
            out.append(_finding(MISSING, key, "", passport[key], source, "Not found in the form."))

    found_dates = dates_in_text(text)
    for key in ("dob", "issueDate", "expiryDate"):
        expected = iso_to_date(passport.get(key))
        if not expected:
            continue
        exact = [raw for raw, c in found_dates if c[0] == expected]
        swapped = [raw for raw, c in found_dates if c[0] != expected and expected in c]
        if exact:
            out.append(_finding(OK, key, exact[0], show_date(expected), source, "Found in the form."))
        elif swapped:
            out.append(_finding(CORRECT, key, swapped[0], show_date(expected), source, "Day and month are swapped."))
        else:
            near = [raw for raw, c in found_dates if c[0] and ((c[0].day, c[0].month) == (expected.day, expected.month) or (c[0].year == expected.year and c[0].month == expected.month))]
            if near:
                out.append(_finding(CORRECT, key, near[0], show_date(expected), source, "A similar date is written — check it."))
            else:
                out.append(_finding(MISSING, key, "", show_date(expected), source, "Not found in the form."))
    return out


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

_ORDER = {CORRECT: 0, MISSING: 1, CHECK: 2, INFO: 3, OK: 4}


def check_form(form: Dict[str, Any], passports: Iterable[Dict[str, Any]], supporting: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    """form / supporting: extract_document() results (+ fileName).
    passports: details staff confirmed on the page. Returns
    {fileName, passportUsed, notes, findings, summary}."""
    passports = [_clean_passport(p) for p in (passports or []) if p]
    passports = [p for p in passports if any(p.get(k) for k in PASSPORT_KEYS)]
    supporting = list(supporting or [])
    fields = form.get("fields") or []
    text = form.get("text") or ""
    notes = list(form.get("notes") or [])
    definition = None
    if form.get("formId"):
        try:
            definition = visa_forms.get_definition(form["formId"])
        except visa_forms.FormError:
            definition = None

    passport, choose_note = choose_passport(fields, text, passports)
    if choose_note:
        notes.append(choose_note)
    source = "Passport" + (f" ({passport.get('label')})" if passport and passport.get("label") else "")

    findings: List[Dict[str, Any]] = []
    if passport is None:
        notes.append("No passport details were given, so only the form's own dates and blanks were checked.")

    if fields:
        used = set()
        for f in fields:
            key = f.get("compare") or ""
            if not key or not passport or key in used:
                continue
            if key == "arrivalDate":
                continue
            used.add(key)
            result = _compare_field(key, f.get("value") or "", passport, source, f.get("label") or "")
            if result:
                findings.append(result)
        findings += _required_blanks(definition, fields)
        findings += _date_rules(fields, passport)
        findings += check_with_supporting(fields, supporting)
    elif text.strip():
        if passport:
            findings += check_text(text, passport, source)
        notes.append("This file has no fillable fields, so passport details were searched for in its text.")
    else:
        notes.append("Nothing could be read from this file.")

    if passport and supporting:
        # A supporting document that writes the passport number or the name
        # differently is worth knowing about (e.g. a ticket with a typo).
        for doc in supporting:
            corpus = _doc_corpus(doc)
            if not corpus.strip():
                continue
            name = doc.get("fileName") or "Supporting document"
            for item in check_text(corpus, passport, name):
                if item["status"] == CORRECT and item["field"] in ("passportNumber", "surname", "givenNames"):
                    item["label"] = FIELD_LABELS.get(item["field"], item["field"]) + " in " + name
                    item["message"] = "The supporting document writes this differently from the passport: " + item["message"]
                    item["status"] = CHECK
                    findings.append(item)

    findings.sort(key=lambda x: _ORDER.get(x["status"], 9))
    summary = {s: sum(1 for x in findings if x["status"] == s) for s in (CORRECT, MISSING, CHECK, INFO, OK)}
    return {
        "fileName": form.get("fileName") or "",
        "formName": form.get("formName") or "",
        "method": form.get("method") or "",
        "passportUsed": (passport or {}).get("label") or ("" if passport is None else "Passport"),
        "notes": notes,
        "findings": findings,
        "summary": summary,
    }
