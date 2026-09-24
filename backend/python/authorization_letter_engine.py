"""
Khanna Travels & Holidays — Authorization Letter document generators
========================================================================

Generates the company's two real "Authorization Letter" documents:

  1. Passport Authorization Letter — the traveller(s) authorize Khanna
     Holidays Pvt. Ltd. (and a named staff collector) to collect their
     original passport(s) from a visa/consulate application centre.
  2. Company Authorization Letter — Khanna Holidays Pvt. Ltd. itself states
     to the Visa Officer that it has been authorized to collect the listed
     applicants' passports.

Source of truth (read-only, NEVER modified by this module — project rule 5,
Document Template Rule):
    reference-templates/Passport Authorization Letter/Passport Authorization Letter - Single traveller.docx
    reference-templates/Passport Authorization Letter/Passport Authorization Letter - two or multiple travellers.docx
    reference-templates/Company Authorization Letter/Company Authorization Letter.docx

Important note on these particular templates (unlike the Hotel Voucher
template, which was a genuine blank template): the two Passport
Authorization Letter files are REAL, PAST CLIENT LETTERS, not blank
templates with bracketed placeholders throughout. Only some fields (e.g.
'[Date]', '[Country]', '[Address of consulate]' in the "two or multiple
travellers" file) are still bracketed — the rest already contains a real
former client's name, passport number, phone and email. Because of this,
every dynamic field in this module is filled by verified structural
POSITION (paragraph index, run index) rather than by searching for
bracket tokens, since token-search would silently do nothing on the
Single-traveller file (it has no brackets left at all). Every fill
function asserts the expected run/paragraph shape first and raises
AuthorizationLetterError — never silently mis-fills — if the real
template's structure has changed (project rule 9).

The real former client's name, passport number, phone and email that
appear in these reference files must NEVER be copied into generated
output or used as sample/demo data (project rule 11).
"""

from __future__ import annotations

import os
from typing import Optional

from docx import Document
from docx.text.paragraph import Paragraph

import docx_utils
import letter_shared

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_REFERENCE_ROOT = os.path.normpath(os.path.join(_THIS_DIR, "..", "..", "reference-templates"))

PASSPORT_SINGLE_TEMPLATE_PATH = os.path.join(
    _REFERENCE_ROOT, "Passport Authorization Letter", "Passport Authorization Letter - Single traveller.docx"
)
PASSPORT_MULTIPLE_TEMPLATE_PATH = os.path.join(
    _REFERENCE_ROOT, "Passport Authorization Letter", "Passport Authorization Letter - two or multiple travellers.docx"
)
COMPANY_TEMPLATE_PATH = os.path.join(
    _REFERENCE_ROOT, "Company Authorization Letter", "Company Authorization Letter.docx"
)

MAX_PASSPORT_AUTH_PEOPLE = 2  # matches the two available reference templates exactly


class AuthorizationLetterError(docx_utils.DocxBuildError):
    """Raised whenever an authorization letter genuinely cannot be
    generated — never swallowed to produce a fake/empty document (project
    rule 9)."""


# ---------------------------------------------------------------------------
# Small, shared formatting helpers — date/name/relation/phone/ordering are
# all in letter_shared.py (Phase 9 extracted them there once
# cover_letter_engine.py needed the identical logic — project rule 15).
# ---------------------------------------------------------------------------

_format_letter_date = letter_shared.format_letter_date
_display_name = letter_shared.display_name
_relation_phrase = letter_shared.relation_phrase
_local_phone_digits = letter_shared.local_phone_digits
_order_people = letter_shared.order_people


def _load_template(path: str, label: str) -> Document:
    if not os.path.isfile(path):
        raise AuthorizationLetterError(
            f"{label} reference template not found at {path}. This file is part "
            "of the project's read-only reference material (reference-templates/) "
            "and must already exist on this machine — it is never created by this app."
        )
    return Document(path)  # only ever read, never written back to


def _assert_run_count(paragraph: Paragraph, expected: int, where: str) -> None:
    if len(paragraph.runs) != expected:
        raise AuthorizationLetterError(
            f"Authorization letter template structure has changed ({where}: expected "
            f"{expected} runs, found {len(paragraph.runs)}) — cannot safely fill it. "
            "Check the reference-templates/ file this letter is generated from."
        )


# ---------------------------------------------------------------------------
# Passport Authorization Letter
# ---------------------------------------------------------------------------


def _fill_passport_common(document: Document, recipient_centre_name: str, recipient_address: str, date_override: Optional[str]) -> None:
    paragraphs = document.paragraphs
    docx_utils.set_paragraph_text(paragraphs[4], f"Date- {_format_letter_date(date_override)}")
    docx_utils.set_paragraph_text(paragraphs[8], recipient_centre_name or "—")
    docx_utils.set_paragraph_text(paragraphs[9], recipient_address or "—")


def _fill_passport_single(document: Document, person: dict, collector_name: str) -> None:
    paragraphs = document.paragraphs

    sentence = paragraphs[15]
    _assert_run_count(sentence, 9, "single-traveller applicant sentence")
    sentence.runs[1].text = _display_name(person)
    sentence.runs[3].text = person.get("passportNumber") or "—"

    collector = paragraphs[17]
    _assert_run_count(collector, 3, "single-traveller collector sentence")
    collector.runs[1].text = f"{collector_name} from Khanna Holidays Pvt. Ltd."

    signature = paragraphs[25]
    digits = _local_phone_digits(person.get("phone"))
    phone_line = f"Phone No.: +91 {digits}" if digits else "Phone No.: —"
    docx_utils.set_two_line_paragraph(signature, _display_name(person), phone_line)

    email_para = paragraphs[26]
    email = (person.get("email") or "").strip()
    updated = docx_utils.set_hyperlink_text_and_target(
        email_para, document, email or "—", f"mailto:{email}" if email else None
    )
    if not updated:
        raise AuthorizationLetterError(
            "Authorization letter template structure has changed (signature block's "
            "'Email id:' line is no longer a hyperlink) — cannot safely fill it."
        )


def _fill_passport_multiple(document: Document, people: list[dict], collector_name: str) -> None:
    paragraphs = document.paragraphs
    person1, person2 = people[0], people[1]

    sentence = paragraphs[15]
    _assert_run_count(sentence, 24, "multiple-traveller applicant sentence")
    runs = sentence.runs
    runs[2].text = ""
    runs[3].text = _display_name(person1)
    runs[5].text = person1.get("passportNumber") or "—"
    relation = _relation_phrase(person2.get("relationToApplicant"), person2.get("sex"))
    runs[7].text = f" & {relation} " if relation else " & "
    runs[8].text = _display_name(person2)
    runs[10].text = f"(Passport No.: {person2.get('passportNumber') or '—'}"

    collector = paragraphs[17]
    _assert_run_count(collector, 10, "multiple-traveller collector sentence")
    collector.runs[6].text = ""
    collector.runs[7].text = ""
    collector.runs[8].text = f"{collector_name} from Khanna Holidays Pvt. Ltd."

    signature = paragraphs[25]
    digits = _local_phone_digits(person1.get("phone"))
    phone_line = f"Phone No.: +91 {digits}" if digits else "Phone No.: —"
    docx_utils.set_two_line_paragraph(signature, _display_name(person1), phone_line)

    email_para = paragraphs[26]
    email = (person1.get("email") or "").strip()
    updated = docx_utils.set_hyperlink_text_and_target(
        email_para, document, email or "—", f"mailto:{email}" if email else None
    )
    if not updated:
        raise AuthorizationLetterError(
            "Authorization letter template structure has changed (signature block's "
            "'Email id:' line is no longer a hyperlink) — cannot safely fill it."
        )


def generate_passport_authorization_docx(
    people: list[dict],
    recipient_centre_name: str,
    recipient_address: str,
    collector_name: str,
    date_override: Optional[str] = None,
) -> bytes:
    """Builds the Passport Authorization Letter .docx for 1 or 2
    travellers — the exact set the real reference templates cover.
    Returns raw .docx bytes. Raises ValueError / AuthorizationLetterError
    on any problem — never returns a silently-wrong or empty document."""
    if not people:
        raise ValueError("At least one traveller is required to generate this letter.")
    if len(people) > MAX_PASSPORT_AUTH_PEOPLE:
        raise ValueError(
            "Passport Authorization Letter can be generated for 1 or 2 travellers at a "
            "time, matching the two reference templates on file. For a group of 3 or "
            "more, please generate separate letters for now."
        )
    if not collector_name or not collector_name.strip():
        raise ValueError("Please enter who will collect the passport(s) on the applicant's behalf.")
    if not recipient_centre_name or not recipient_centre_name.strip():
        raise ValueError("Please enter the visa application centre name.")

    ordered = _order_people(people)
    collector_name = collector_name.strip()

    if len(ordered) == 1:
        document = _load_template(PASSPORT_SINGLE_TEMPLATE_PATH, "Passport Authorization Letter (single traveller)")
        _fill_passport_common(document, recipient_centre_name, recipient_address, date_override)
        _fill_passport_single(document, ordered[0], collector_name)
    else:
        document = _load_template(
            PASSPORT_MULTIPLE_TEMPLATE_PATH, "Passport Authorization Letter (multiple travellers)"
        )
        _fill_passport_common(document, recipient_centre_name, recipient_address, date_override)
        _fill_passport_multiple(document, ordered, collector_name)

    import io

    buf = io.BytesIO()
    document.save(buf)
    return buf.getvalue()


def generate_passport_authorization_pdf(
    people: list[dict],
    recipient_centre_name: str,
    recipient_address: str,
    collector_name: str,
    date_override: Optional[str] = None,
) -> bytes:
    docx_bytes = generate_passport_authorization_docx(
        people, recipient_centre_name, recipient_address, collector_name, date_override
    )
    try:
        return docx_utils.convert_docx_bytes_to_pdf(docx_bytes, base_name="passport_authorization")
    except docx_utils.DocxBuildError as e:
        raise AuthorizationLetterError(str(e))


# ---------------------------------------------------------------------------
# Company Authorization Letter
# ---------------------------------------------------------------------------


def generate_company_authorization_docx(
    people: list[dict],
    recipient_text: str,
    date_override: Optional[str] = None,
) -> bytes:
    """Builds the Company Authorization Letter .docx for any number of
    applicants — the template's one real applicant-line paragraph is used
    as the clone-template and repeated once per applicant (the same
    clone-a-real-block technique as the Hotel Voucher engine's multi-hotel
    handling). Returns raw .docx bytes. Raises ValueError /
    AuthorizationLetterError on any problem — never returns a silently-
    wrong or empty document."""
    if not people:
        raise ValueError("At least one applicant is required to generate this letter.")

    document = _load_template(COMPANY_TEMPLATE_PATH, "Company Authorization Letter")
    paragraphs = document.paragraphs

    docx_utils.set_paragraph_text(paragraphs[2], f"Date- {_format_letter_date(date_override)}")
    docx_utils.set_paragraph_text(paragraphs[6], (recipient_text or "").strip() or "—")

    line1 = paragraphs[14]
    line2 = paragraphs[15]
    _assert_run_count(line1, 3, "first applicant line")

    # paragraphs[15] in the real template is a second hand-typed example
    # line with an extra run-split artifact ("[Applicant" / "2" / " Full
    # Name]") — rather than special-case that shape, line1's clean 3-run
    # paragraph is used as the ONE canonical clone-template for every
    # applicant line (itself included), and line2 is simply removed first.
    line2_el = line2._p
    line2_el.getparent().remove(line2_el)

    template_el = line1._p
    clone_els = docx_utils.clone_and_insert_after(template_el, len(people) - 1)
    line_els = [template_el] + clone_els

    for el, person in zip(line_els, people):
        para = Paragraph(el, document)
        _assert_run_count(para, 3, "applicant line")
        name = (person.get("fullName") or "").strip() or "—"
        para.runs[0].text = f"{name} "
        para.runs[2].text = person.get("passportNumber") or "—"

    import io

    buf = io.BytesIO()
    document.save(buf)
    return buf.getvalue()


def generate_company_authorization_pdf(
    people: list[dict],
    recipient_text: str,
    date_override: Optional[str] = None,
) -> bytes:
    docx_bytes = generate_company_authorization_docx(people, recipient_text, date_override)
    try:
        return docx_utils.convert_docx_bytes_to_pdf(docx_bytes, base_name="company_authorization")
    except docx_utils.DocxBuildError as e:
        raise AuthorizationLetterError(str(e))
