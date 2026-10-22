"""
Khanna Travels & Holidays — shared letter-writing helpers
================================================================
Small, application-specific text helpers (NOT generic OOXML manipulation
— see docx_utils.py for that) shared by every letter-generating engine:
date formatting, a person's display name, and describing a companion
traveller's relation to the main applicant in natural language.

Used by authorization_letter_engine.py (Phase 8) and
cover_letter_engine.py (Phase 9) — extracted here, instead of being
defined twice, so a future invitation/initors-letter engine reuses it
too rather than duplicating it again (project rule 15).
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

import re

_ORDINAL_EXCEPTIONS = {11: "th", 12: "th", 13: "th"}


def ordinal_suffix(day: int) -> str:
    if day in _ORDINAL_EXCEPTIONS:
        return "th"
    return {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")


def format_letter_date(date_override: Optional[str]) -> str:
    """Matches the real reference letters' own date style, e.g.
    '22nd September 2026'. Defaults to today's date when no override is
    given — this is administrative letter-writing metadata (the day the
    letter is produced), not client data, so defaulting it is not a
    fabrication (project rule 11 is about passport/client data)."""
    if date_override:
        try:
            d = datetime.strptime(date_override, "%Y-%m-%d").date()
        except ValueError:
            return date_override  # honest passthrough of whatever was given
    else:
        d = datetime.now().date()
    return f"{d.day}{ordinal_suffix(d.day)} {d.strftime('%B')} {d.year}"


def display_name(person: dict) -> str:
    """'Mr. Dilip Bijlani' style — only prepends a salutation when a real,
    non-generic one is on file (project rule 9: never invent a title that
    wasn't actually entered)."""
    full_name = (person.get("fullName") or "").strip() or "—"
    salutation = (person.get("salutation") or "").strip()
    if salutation and salutation.lower() != "other":
        return f"{salutation}. {full_name}"
    return full_name


_RELATION_WORDS = {
    "Spouse": {"M": "husband", "F": "wife"},
    "Child": {"M": "son", "F": "daughter"},
    "Parent": {"M": "father", "F": "mother"},
    "Sibling": {"M": "brother", "F": "sister"},
    "Friend": {"*": "friend"},
    "Colleague": {"*": "colleague"},
}


def relation_word(relation: Optional[str], sex: Optional[str]) -> Optional[str]:
    """Bare relation word ('wife', 'son', ...), built only from genuinely
    available data (Phase 5's traveller.relation field, plus `sex` from
    passport OCR/MRZ). Returns None — never a guess — when the relation or
    sex isn't one this can confidently phrase, so callers fall back to
    their own honest, generic wording instead (project rule 9: no
    fabricated data)."""
    if not relation:
        return None
    by_sex = _RELATION_WORDS.get(relation)
    if not by_sex:
        return None
    if "*" in by_sex:
        return by_sex["*"]
    return by_sex.get((sex or "").upper())


def relation_phrase(relation: Optional[str], sex: Optional[str]) -> Optional[str]:
    """'my wife' style, ready to embed directly into a sentence. Returns
    None on the same honest-fallback terms as relation_word — callers
    decide their own generic wording (e.g. Passport Authorization drops
    the phrase entirely with a bare '&'; a Cover Letter's sentences need
    *some* noun there, so it substitutes 'my family member')."""
    word = relation_word(relation, sex)
    return f"my {word}" if word else None


def local_phone_digits(phone: Optional[str]) -> str:
    """Strips formatting and a leading '91' country code (every reference
    letter that shows a phone number hardcodes '+91' as fixed text),
    returning just the local number to slot in after it. Returns '' if
    nothing usable was entered — callers fall back to an honest '—' rather
    than printing '+91 —'."""
    digits = "".join(ch for ch in (phone or "") if ch.isdigit())
    if len(digits) > 10 and digits.startswith("91"):
        digits = digits[2:]
    return digits[-10:] if len(digits) >= 10 else digits


def order_people(people: list[dict]) -> list[dict]:
    """The lead/primary signer goes first (matching how the real reference
    letters always list the paying/primary applicant before a spouse or
    other companion). If one of the given people is flagged as the main
    applicant, they lead; otherwise the given order is kept as-is."""
    if not people:
        return []
    applicants = [p for p in people if p.get("isApplicant")]
    others = [p for p in people if not p.get("isApplicant")]
    return (applicants + others) if applicants else list(people)


# ---------------------------------------------------------------------------
# Person names in generated documents
# ---------------------------------------------------------------------------
# A passport prints a name in capitals ("MIHIR HARILAL KOTAK") and the app
# stores it exactly like that — the passport record is never altered. A letter
# or voucher, though, reads properly in ordinary capitalisation ("Mihir Harilal
# Kotak"), so every document engine receives names through this function.

_NAME_SPLIT_RE = re.compile(r"([\s\-'’]+)")


_TITLE_WORDS = {"mr", "mrs", "ms", "miss", "mstr", "master", "dr", "prof", "shri", "smt", "sri"}


def _capitalise_word(word: str) -> str:
    # Already mixed case ("McDonald", "Mr.", "de Souza") or a short initial /
    # abbreviation ("K.", "K.R.") — the writer meant it, leave it alone.
    if not word or (word != word.upper() and word != word.lower()):
        return word
    if word.rstrip(".").lower() in _TITLE_WORDS:
        return word[:1].upper() + word[1:].lower()  # "MR." -> "Mr."
    if len(word) <= 1 or "." in word:
        return word.upper()
    return word[:1].upper() + word[1:].lower()


def person_display_name(name: Optional[str]) -> str:
    """'MIHIR HARILAL KOTAK' -> 'Mihir Harilal Kotak'; 'Mr. AMARDEEP DIVEKAR' ->
    'Mr. Amardeep Divekar'; 'O\'BRIEN-SMITH' -> 'O\'Brien-Smith'. Words that already
    mix capitals and lower case, and initials, are left exactly as typed."""
    if not name:
        return name or ""
    cleaned = re.sub(r"[ \t]{2,}", " ", str(name).strip())  # stray double spaces from a scan
    parts = _NAME_SPLIT_RE.split(cleaned)
    return "".join(p if _NAME_SPLIT_RE.fullmatch(p) or not p else _capitalise_word(p) for p in parts)
