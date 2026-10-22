"""
Passport cross-checks — independent evidence layered on top of the MRZ read.

The MRZ's check digits protect the passport number, date of birth, date of
expiry and personal number. They do NOT protect the names, the nationality or
the document type, so a garbled name can still come out of an otherwise
"valid" MRZ. This module narrows that gap without guessing:

  * obvious OCR junk in MRZ line 1 (filler '<' read as K/C/G runs, an
    impossible document-type letter, an invalid country code) is repaired
    only where the fix is unambiguous, and every repair is reported;
  * every extracted value is compared with the visible (VIZ) text printed on
    the page, and each field is marked "confirmed by the printed page" or not;
  * dates printed on the page are parsed so the date of issue can be derived
    by elimination (the one printed date that is neither DOB nor expiry).

Nothing here marks data as verified — OCR results always stay
"OCR Extracted — Please Verify" and fully editable. The result only decides
which fields staff are asked to look at more closely.
"""
from __future__ import annotations

import difflib
import re
from datetime import date
from typing import Any, Callable, Dict, List, Optional, Tuple

from mrz_reader import COUNTRY_CODES, _repair_country_code
from ocr_runner import compute_icao_check_digit

_FILLER_CHARS = "KCLESXRIJGQO1"
_VOWELS = set("AEIOUY")
_MONTHS = {
    "JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6,
    "JUL": 7, "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12,
}

_NUMERIC_DATE_RE = re.compile(r"(?<!\d)(\d{1,2})\s*[/.\-]\s*(\d{1,2})\s*[/.\-]\s*(\d{4})(?!\d)")
_NAMED_DATE_RE = re.compile(r"(?<!\d)(\d{1,2})\s*([A-Z]{3})[A-Z]*\s*(?:/\s*[A-Z]{3,}\s*)?(\d{4})(?!\d)")
_MRZ_LIKE_RE = re.compile(r"^[A-Z0-9<]{28,}$")


# ---------------------------------------------------------------------------
# Visible-text helpers
# ---------------------------------------------------------------------------


def visible_text(ocr_text: str) -> str:
    """OCR text with the machine-readable-zone lines removed. The MRZ lines
    contain the very values being checked, so leaving them in would make every
    field look "confirmed" by itself."""
    kept: List[str] = []
    for line in (ocr_text or "").splitlines():
        compact = re.sub(r"\s+", "", line.upper())
        if "<<" in compact or _MRZ_LIKE_RE.match(compact):
            continue
        kept.append(line)
    return "\n".join(kept)


def viz_words(text: str) -> List[str]:
    return re.findall(r"[A-Z]{3,}", (text or "").upper())


def _to_iso(day: int, month: int, year: int) -> Optional[str]:
    try:
        return date(year, month, day).isoformat()
    except ValueError:
        return None


def viz_dates(text: str) -> List[str]:
    """Every plausible calendar date printed on the page, as ISO strings, in
    reading order, without duplicates."""
    found: List[Tuple[int, str]] = []
    upper = (text or "").upper()
    for m in _NUMERIC_DATE_RE.finditer(upper):
        iso = _to_iso(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        if iso and 1900 <= int(iso[:4]) <= 2100:
            found.append((m.start(), iso))
    for m in _NAMED_DATE_RE.finditer(upper):
        month = _MONTHS.get(m.group(2))
        if month:
            iso = _to_iso(int(m.group(1)), month, int(m.group(3)))
            if iso and 1900 <= int(iso[:4]) <= 2100:
                found.append((m.start(), iso))
    found.sort()
    out: List[str] = []
    for _, iso in found:
        if iso not in out:
            out.append(iso)
    return out


def derive_issue_date(dates: List[str], dob: Optional[str], expiry: Optional[str]) -> Optional[str]:
    """The date of issue by elimination: the only printed date that is not the
    birth or expiry date and falls between them with a plausible validity
    period (5 or 10 years). Returns None unless exactly one date qualifies —
    an ambiguous page is never guessed at."""
    if not expiry:
        return None
    candidates = []
    for d in dates:
        if d in (dob, expiry):
            continue
        if dob and d <= dob:
            continue
        if d >= expiry:
            continue
        years = (date.fromisoformat(expiry) - date.fromisoformat(d)).days / 365.25
        if 4.5 <= years <= 10.6:
            candidates.append(d)
    return candidates[0] if len(candidates) == 1 else None


def word_confirmed(token: str, words: List[str]) -> bool:
    """True when `token` (an MRZ name part) appears on the printed page,
    allowing the one- or two-character OCR slips a real read contains."""
    token = (token or "").upper()
    if len(token) < 3:
        return False
    for w in words:
        if w == token:
            return True
        if w[0] == token[0] and abs(len(w) - len(token)) <= 2:
            if difflib.SequenceMatcher(None, w, token).ratio() >= 0.84:
                return True
    return False


# ---------------------------------------------------------------------------
# MRZ line repairs that no check digit can validate
# ---------------------------------------------------------------------------


def _suspicious_token(token: str) -> bool:
    if len(token) >= 20:
        return True
    if len(token) >= 5 and not (set(token) & _VOWELS):
        return True
    if re.search(r"(.)\1{3,}", token):
        return True
    return False


def _strip_filler_tail(token: str) -> str:
    """Drops a trailing run that is clearly the '<' filler misread as letters
    (e.g. 'GGGG', 'KCKCKC'), but never touches a real name ending such as
    ALEXIS — real endings have varied letters."""
    # The same filler-lookalike letter three or more times in a row at the end
    # (VIRKKK) is never a real ending.
    same = re.search(r"([" + _FILLER_CHARS + r"])\1{2,}$", token)
    if same and len(token) - len(same.group(0)) >= 2:
        return token[: same.start()]
    m = re.search(r"[" + _FILLER_CHARS + r"]{4,}$", token)
    if not m:
        return token
    run = m.group(0)
    if len(set(run)) <= 2 or len(run) >= 7:
        return token[: m.start()]
    return token


def _viz_exact_word(token: str, words: List[str]) -> Optional[str]:
    """The one printed word that `token` becomes when a single stray character
    (an inserted letter, typically a misread filler '<') is removed - e.g.
    KPASHA -> PASHA. None when there is no such unique word."""
    if len(token) < 5:
        return None
    hits = set()
    for i in range(len(token)):
        shorter = token[:i] + token[i + 1:]
        if len(shorter) >= 4 and shorter in words:
            hits.add(shorter)
    return hits.pop() if len(hits) == 1 else None


def _clean_name_field(field: str, words: List[str], country_tail: str = "") -> Tuple[str, List[Dict[str, str]]]:
    notes: List[Dict[str, str]] = []
    base = field.rstrip("<")
    surname_part, sep, given_part = base.partition("<<")
    # A real name field never has a second '<<' inside the given names: once
    # the separator has been seen, a further run of two or more '<' is the
    # filler that pads the line, and whatever follows it is OCR noise.
    if "<<" in given_part:
        kept, _, dropped = given_part.partition("<<")
        dropped = dropped.strip("<")
        if dropped:
            notes.append({"field": "givenNames", "from": dropped, "to": "", "reason": "text after the '<' filler run is not part of the name"})
        given_part = kept
    surname_tokens = [t for t in surname_part.split("<") if t]
    given_tokens = [t for t in given_part.split("<") if t]
    # "P<IND" + "D<<CHAND..." - a one-letter surname that merely repeats the
    # last letter of the country code is the code read twice, not a surname.
    if len(surname_tokens) == 1 and len(surname_tokens[0]) == 1 and country_tail and surname_tokens[0] == country_tail[-1] and given_tokens:
        notes.append({"field": "surname", "from": surname_tokens[0], "to": "", "reason": "a stray repeat of the country code's last letter"})
        surname_tokens = []

    def clean(tokens: List[str], label: str) -> List[str]:
        out: List[str] = []
        for tok in tokens:
            if tok in words:
                out.append(tok)
                continue
            exact = _viz_exact_word(tok, words)
            if exact:
                notes.append({"field": label, "from": tok, "to": exact, "reason": "one stray character removed to match the printed name"})
                out.append(exact)
                continue
            if word_confirmed(tok, words):
                out.append(tok)
                continue
            stripped = _strip_filler_tail(tok)
            if stripped != tok:
                notes.append({"field": label, "from": tok, "to": stripped, "reason": "trailing '<' filler was read as letters"})
            if out and len(stripped) >= 2 and len(set(stripped)) == 1 and stripped[0] in _FILLER_CHARS:
                # "KK" / "CCC" standing alone after a real name part: filler.
                notes.append({"field": label, "from": stripped, "to": "", "reason": "a run of one repeated letter that looks like the '<' filler"})
                continue
            if len(stripped) == 1 and stripped in _FILLER_CHARS and out:
                # A lone filler-lookalike letter after a real name part
                # ("VISHAL<K") is the filler, not an initial.
                notes.append({"field": label, "from": stripped, "to": "", "reason": "a single stray letter that looks like the '<' filler"})
                continue
            if stripped:
                out.append(stripped)
        return out

    surname_tokens = clean(surname_tokens, "surname")
    given_tokens = clean(given_tokens, "givenNames")
    rebuilt = "<".join(surname_tokens)
    if given_tokens:
        rebuilt += "<<" + "<".join(given_tokens)
    return rebuilt.ljust(39, "<")[:39], notes


def refine_mrz(
    parsed: Dict[str, Any],
    ocr_text: str,
    parse_fn: Callable[[str, str], Dict[str, Any]],
) -> Tuple[Dict[str, Any], List[Dict[str, str]]]:
    """Applies the unambiguous repairs described in the module docstring and
    re-parses. Returns (parsed, repairs). Check-digit-protected positions are
    never altered here, so a valid MRZ stays valid."""
    line1 = (parsed.get("line1") or "").ljust(44, "<")[:44]
    line2 = (parsed.get("line2") or "").ljust(44, "<")[:44]
    words = viz_words(visible_text(ocr_text))
    repairs: List[Dict[str, str]] = []

    # Document type: second character is '<' or a type letter (D, O, S, ...).
    if line1[1] in "KCLEXIJGS1":
        repairs.append({"field": "documentType", "from": line1[:2], "to": "P<", "reason": "second document-code character cannot be a letter that looks like the filler"})
        line1 = line1[0] + "<" + line1[2:]

    # Issuing state and nationality — neither is covered by a check digit.
    issuing = line1[2:5]
    nationality = line2[10:13]
    issuing_fixed, _ = _repair_country_code(issuing)
    nationality_fixed, _ = _repair_country_code(nationality)
    issuing_fixed = issuing_fixed.rstrip("<")
    nationality_fixed = nationality_fixed.rstrip("<")
    issuing_ok = issuing_fixed in COUNTRY_CODES
    nationality_ok = nationality_fixed in COUNTRY_CODES
    if issuing_ok and not nationality_ok:
        nationality_fixed, nationality_ok = issuing_fixed, True
        reason = "nationality is not a valid country code; the issuing state is"
    elif nationality_ok and not issuing_ok:
        issuing_fixed, issuing_ok = nationality_fixed, True
        reason = "issuing state is not a valid country code; the nationality is"
    else:
        reason = "not a valid country code; one unambiguous look-alike fix"
    if issuing_ok and issuing_fixed.ljust(3, "<") != issuing:
        repairs.append({"field": "issuingCountry", "from": issuing, "to": issuing_fixed, "reason": reason})
        line1 = line1[:2] + issuing_fixed.ljust(3, "<") + line1[5:]
    if nationality_ok and nationality_fixed.ljust(3, "<") != nationality:
        repairs.append({"field": "nationality", "from": nationality, "to": nationality_fixed, "reason": reason})
        line2 = line2[:10] + nationality_fixed.ljust(3, "<") + line2[13:]

    # Name field (no check digit).
    name_field, name_notes = _clean_name_field(line1[5:44], words, line1[2:5].rstrip("<"))
    if name_notes:
        repairs.extend(name_notes)
        line1 = line1[:5] + name_field

    # Passport number: a check digit can still pass on a number with a '<' or
    # other wrong character inside it (the digit depends on the characters, and
    # several different numbers can share one). When the printed number on the
    # page, read separately, is a close match that satisfies the same check
    # digit, it is the real one.
    number_field = line2[:9]
    if re.search(r"[A-Z0-9]<+[A-Z0-9]", number_field.rstrip("<")) or not re.fullmatch(r"[A-Z0-9]+<*", number_field):
        fixed = _passport_number_from_page(number_field, line2[9], visible_text(ocr_text))
        if fixed:
            repairs.append({"field": "passportNumber", "from": number_field.rstrip("<"), "to": fixed.rstrip("<"), "reason": "the passport number printed on the page matches the check digit"})
            line2 = fixed + line2[9:]

    if line1 == parsed.get("line1") and line2 == parsed.get("line2"):
        return parsed, repairs
    return parse_fn(line1, line2), repairs


def _passport_number_from_page(mrz_field: str, check_digit: str, vis_text: str) -> Optional[str]:
    """The 9-character passport-number field implied by a printed number: a
    7-9 character run of letters/digits in the page text whose ICAO check digit
    equals the MRZ one and which differs from the MRZ read in at most three
    positions. Exactly one such run must exist."""
    if not check_digit.isdigit():
        return None
    compact = re.sub(r"[^A-Z0-9]", "", (vis_text or "").upper())
    found = set()
    for n in (9, 8, 7):
        for i in range(len(compact) - n + 1):
            cand = compact[i:i + n]
            if not re.fullmatch(r"[A-Z]\d{%d}" % (n - 1), cand) and not re.fullmatch(r"[A-Z]{1,2}\d{%d}" % (n - 2 if n > 7 else 6), cand):
                continue
            padded = cand.ljust(9, "<")
            if str(compute_icao_check_digit(padded)) != check_digit:
                continue
            diff = sum(1 for a, b in zip(padded, mrz_field.ljust(9, "<")) if a != b)
            if diff <= 3:
                found.add(padded)
    return found.pop() if len(found) == 1 else None


# ---------------------------------------------------------------------------
# Evidence from the printed page
# ---------------------------------------------------------------------------


def confirmations(parsed: Dict[str, Any], ocr_text: str) -> Dict[str, Any]:
    """Which MRZ values are independently visible on the printed page, plus the
    dates printed there (for the issue-date derivation)."""
    vis = visible_text(ocr_text)
    words = viz_words(vis)
    dates = viz_dates(vis)
    compact = re.sub(r"[^A-Z0-9]", "", vis.upper())

    def tokens(value: str) -> List[str]:
        return [t for t in re.split(r"[\s<]+", (value or "").upper()) if t]

    surname_tokens = tokens(parsed.get("surname", ""))
    given_tokens = tokens(parsed.get("givenNames", ""))
    number = (parsed.get("passportNumber") or "").upper().replace("<", "")

    return {
        "surname": bool(surname_tokens) and all(word_confirmed(t, words) for t in surname_tokens),
        "givenNames": bool(given_tokens) and all(word_confirmed(t, words) for t in given_tokens),
        "dateOfBirth": bool(parsed.get("dateOfBirth")) and parsed["dateOfBirth"] in dates,
        "dateOfExpiry": bool(parsed.get("dateOfExpiry")) and parsed["dateOfExpiry"] in dates,
        "passportNumber": len(number) >= 6 and number in compact,
        "dates": dates,
        "suspiciousNameTokens": [t for t in surname_tokens + given_tokens if _suspicious_token(t)],
        "issueDate": derive_issue_date(dates, parsed.get("dateOfBirth"), parsed.get("dateOfExpiry")),
    }
