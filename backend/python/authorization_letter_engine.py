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

import document_blocks
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


def _fill_passport_common(
    document: Document, date_p, centre_p, address_p,
    recipient_centre_name: str, recipient_address: str, date_override: Optional[str],
    edited_fields: Optional[dict] = None,
) -> None:
    """Fills the Date/Recipient Centre/Recipient Address paragraphs —
    takes the three target Paragraph objects directly (captured by the
    caller BEFORE any editable-field mutation anywhere in this letter
    starts) rather than re-deriving them via `document.paragraphs[N]`
    itself, because an earlier edited field's replace_paragraph_range_
    with_html call can change the document's total paragraph count,
    which would silently invalidate a fresh index lookup for anything
    that comes after it (see generate_passport_authorization_docx's own
    comment for the full reasoning)."""
    edited_fields = edited_fields or {}

    date_html = edited_fields.get("date")
    if date_html is not None:
        docx_utils.replace_paragraph_range_with_html(document, date_p, date_p, date_html)
    else:
        docx_utils.set_paragraph_text(date_p, f"Date- {_format_letter_date(date_override)}")

    centre_html = edited_fields.get("recipientCentre")
    if centre_html is not None:
        docx_utils.replace_paragraph_range_with_html(document, centre_p, centre_p, centre_html)
    else:
        docx_utils.set_paragraph_text(centre_p, recipient_centre_name or "—")

    address_html = edited_fields.get("recipientAddress")
    if address_html is not None:
        docx_utils.replace_paragraph_range_with_html(document, address_p, address_p, address_html)
    else:
        docx_utils.set_paragraph_text(address_p, recipient_address or "—")


def _fill_passport_single(
    document: Document, sentence_p, collector_p, signature_p, email_p,
    person: dict, collector_name: str, edited_fields: Optional[dict] = None,
) -> None:
    edited_fields = edited_fields or {}

    sentence_html = edited_fields.get("applicantSentence")
    if sentence_html is not None:
        docx_utils.replace_paragraph_range_with_html(document, sentence_p, sentence_p, sentence_html)
    else:
        _assert_run_count(sentence_p, 9, "single-traveller applicant sentence")
        sentence_p.runs[1].text = _display_name(person)
        sentence_p.runs[3].text = person.get("passportNumber") or "—"

    collector_html = edited_fields.get("collectorSentence")
    if collector_html is not None:
        docx_utils.replace_paragraph_range_with_html(document, collector_p, collector_p, collector_html)
    else:
        _assert_run_count(collector_p, 3, "single-traveller collector sentence")
        collector_p.runs[1].text = f"{collector_name} from Khanna Holidays Pvt. Ltd."

    # The signature/email block is deliberately NEVER offered as an
    # editable field (unlike every other field on this letter): the
    # signature paragraph's two lines are held together by a real
    # `<w:br/>` element (docx_utils.set_two_line_paragraph) and the email
    # line is a real `<w:hyperlink>` (docx_utils.set_hyperlink_text_and_
    # target) — replace_paragraph_range_with_html rebuilds a paragraph
    # from plain runs and would silently destroy both the line break and
    # the real mailto: link, trading a working feature for a purely
    # cosmetic rewording convenience. Always auto-filled, exactly as
    # before Phase 4.
    digits = _local_phone_digits(person.get("phone"))
    phone_line = f"Phone No.: +91 {digits}" if digits else "Phone No.: —"
    docx_utils.set_two_line_paragraph(signature_p, _display_name(person), phone_line)

    email = (person.get("email") or "").strip()
    updated = docx_utils.set_hyperlink_text_and_target(
        email_p, document, email or "—", f"mailto:{email}" if email else None
    )
    if not updated:
        raise AuthorizationLetterError(
            "Authorization letter template structure has changed (signature block's "
            "'Email id:' line is no longer a hyperlink) — cannot safely fill it."
        )


def _fill_passport_multiple(
    document: Document, sentence_p, collector_p, signature_p, email_p,
    people: list[dict], collector_name: str, edited_fields: Optional[dict] = None,
) -> None:
    edited_fields = edited_fields or {}
    person1, person2 = people[0], people[1]

    sentence_html = edited_fields.get("applicantSentence")
    if sentence_html is not None:
        docx_utils.replace_paragraph_range_with_html(document, sentence_p, sentence_p, sentence_html)
    else:
        _assert_run_count(sentence_p, 24, "multiple-traveller applicant sentence")
        runs = sentence_p.runs
        runs[2].text = ""
        runs[3].text = _display_name(person1)
        runs[5].text = person1.get("passportNumber") or "—"
        relation = _relation_phrase(person2.get("relationToApplicant"), person2.get("sex"))
        runs[7].text = f" & {relation} " if relation else " & "
        runs[8].text = _display_name(person2)
        runs[10].text = f"(Passport No.: {person2.get('passportNumber') or '—'}"

    collector_html = edited_fields.get("collectorSentence")
    if collector_html is not None:
        docx_utils.replace_paragraph_range_with_html(document, collector_p, collector_p, collector_html)
    else:
        _assert_run_count(collector_p, 10, "multiple-traveller collector sentence")
        collector_p.runs[6].text = ""
        collector_p.runs[7].text = ""
        collector_p.runs[8].text = f"{collector_name} from Khanna Holidays Pvt. Ltd."

    # Same reasoning as _fill_passport_single's own comment: never an
    # editable field, always auto-filled — preserves the real <w:br/> line
    # break and the real mailto: hyperlink.
    digits = _local_phone_digits(person1.get("phone"))
    phone_line = f"Phone No.: +91 {digits}" if digits else "Phone No.: —"
    docx_utils.set_two_line_paragraph(signature_p, _display_name(person1), phone_line)

    email = (person1.get("email") or "").strip()
    updated = docx_utils.set_hyperlink_text_and_target(
        email_p, document, email or "—", f"mailto:{email}" if email else None
    )
    if not updated:
        raise AuthorizationLetterError(
            "Authorization letter template structure has changed (signature block's "
            "'Email id:' line is no longer a hyperlink) — cannot safely fill it."
        )


def compose_passport_editable_fields(
    people: list[dict],
    recipient_centre_name: str,
    recipient_address: str,
    collector_name: str,
    date_override: Optional[str] = None,
) -> dict:
    """The Word-like body editor's seed values for the Passport
    Authorization Letter (both single- and multiple-traveller variants) —
    computed by actually running the SAME fill logic the real generator
    uses, against a fresh, throwaway copy of the real template, then
    reading back each target paragraph's fully-rendered text (project
    rule 15: this can never drift from the real generator's own wording,
    because it directly reuses it rather than a hand-duplicated
    reconstruction of these sentences). Field keys: "date",
    "recipientCentre", "recipientAddress", "applicantSentence",
    "collectorSentence" — deliberately NOT the signature/email block (see
    _fill_passport_single's own comment for why that one stays
    auto-only)."""
    import html as _html_mod

    ordered = _order_people(people)
    collector_name = (collector_name or "").strip()

    if len(ordered) == 1:
        document = _load_template(PASSPORT_SINGLE_TEMPLATE_PATH, "Passport Authorization Letter (single traveller)")
        paragraphs = document.paragraphs
        _fill_passport_common(document, paragraphs[4], paragraphs[8], paragraphs[9], recipient_centre_name, recipient_address, date_override)
        paragraphs = document.paragraphs
        _fill_passport_single(document, paragraphs[15], paragraphs[17], paragraphs[25], paragraphs[26], ordered[0], collector_name)
    else:
        document = _load_template(PASSPORT_MULTIPLE_TEMPLATE_PATH, "Passport Authorization Letter (multiple travellers)")
        paragraphs = document.paragraphs
        _fill_passport_common(document, paragraphs[4], paragraphs[8], paragraphs[9], recipient_centre_name, recipient_address, date_override)
        paragraphs = document.paragraphs
        _fill_passport_multiple(document, paragraphs[15], paragraphs[17], paragraphs[25], paragraphs[26], ordered, collector_name)

    paragraphs = document.paragraphs
    return {
        "date": f"<p>{_html_mod.escape(paragraphs[4].text)}</p>",
        "recipientCentre": f"<p>{_html_mod.escape(paragraphs[8].text)}</p>",
        "recipientAddress": f"<p>{_html_mod.escape(paragraphs[9].text)}</p>",
        "applicantSentence": f"<p>{_html_mod.escape(paragraphs[15].text)}</p>",
        "collectorSentence": f"<p>{_html_mod.escape(paragraphs[17].text)}</p>",
    }


def _shade_passport_fields(shader, date_p, centre_p, address_p, sentence_p, collector_p) -> None:
    """Layout probe only (see docx_utils.ProbeShader): marks the five
    editable paragraphs of the Passport Authorization Letter."""
    if shader is None:
        return
    shader.shade("date", date_p)
    shader.shade("recipientCentre", centre_p)
    shader.shade("recipientAddress", address_p)
    shader.shade("applicantSentence", sentence_p)
    shader.shade("collectorSentence", collector_p)


def generate_passport_authorization_docx(
    people: list[dict],
    recipient_centre_name: str,
    recipient_address: str,
    collector_name: str,
    date_override: Optional[str] = None,
    edited_fields: Optional[dict] = None,
    _shader: Optional[docx_utils.ProbeShader] = None,
) -> bytes:
    """Builds the Passport Authorization Letter .docx for 1 or 2
    travellers — the exact set the real reference templates cover.
    Returns raw .docx bytes. Raises ValueError / AuthorizationLetterError
    on any problem — never returns a silently-wrong or empty document.

    `edited_fields`, when given, is a `{fieldKey: html}` map (see
    `compose_passport_editable_fields` for the key set) — a staff
    member's Word-like edits, applied instead of the auto-generated value
    for exactly the fields present.

    Frontend rework, Phase 4: every target paragraph (date, recipient
    centre/address, applicant sentence, collector sentence, AND the
    signature/email paragraphs those last two sit before) is captured
    into a stable Python variable from ONE untouched `document.paragraphs`
    snapshot, taken BEFORE any editable-field mutation anywhere in this
    letter runs — never re-derived by index afterwards. This matters
    here specifically because the date/recipient paragraphs (indices 4,
    8, 9) sit BEFORE the applicant/collector sentences (15, 17), which
    sit before the signature/email block (25, 26): an edited field's
    docx_utils.replace_paragraph_range_with_html call can change the
    document's total paragraph count (a multi-line edit doesn't have to
    stay one paragraph), which would silently shift every later index if
    any of these were looked up fresh after an earlier one was mutated."""
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
        p = document.paragraphs
        date_p, centre_p, address_p, sentence_p, collector_p, signature_p, email_p = (
            p[4], p[8], p[9], p[15], p[17], p[25], p[26]
        )
        _shade_passport_fields(_shader, date_p, centre_p, address_p, sentence_p, collector_p)
        _fill_passport_common(document, date_p, centre_p, address_p, recipient_centre_name, recipient_address, date_override, edited_fields)
        _fill_passport_single(document, sentence_p, collector_p, signature_p, email_p, ordered[0], collector_name, edited_fields)
    else:
        document = _load_template(
            PASSPORT_MULTIPLE_TEMPLATE_PATH, "Passport Authorization Letter (multiple travellers)"
        )
        p = document.paragraphs
        date_p, centre_p, address_p, sentence_p, collector_p, signature_p, email_p = (
            p[4], p[8], p[9], p[15], p[17], p[25], p[26]
        )
        _shade_passport_fields(_shader, date_p, centre_p, address_p, sentence_p, collector_p)
        _fill_passport_common(document, date_p, centre_p, address_p, recipient_centre_name, recipient_address, date_override, edited_fields)
        _fill_passport_multiple(document, sentence_p, collector_p, signature_p, email_p, ordered, collector_name, edited_fields)

    import io

    document_blocks.finalize(document, edited_fields, _shader)
    buf = io.BytesIO()
    document.save(buf)
    return buf.getvalue()


def generate_passport_authorization_pdf(
    people: list[dict],
    recipient_centre_name: str,
    recipient_address: str,
    collector_name: str,
    date_override: Optional[str] = None,
    edited_fields: Optional[dict] = None,
) -> bytes:
    docx_bytes = generate_passport_authorization_docx(
        people, recipient_centre_name, recipient_address, collector_name, date_override, edited_fields
    )
    try:
        return docx_utils.convert_docx_bytes_to_pdf(docx_bytes, base_name="passport_authorization")
    except docx_utils.DocxBuildError as e:
        raise AuthorizationLetterError(str(e))



def compute_passport_field_layout(
    people, recipient_centre_name, recipient_address, collector_name, date_override=None, edited_fields=None
) -> dict:
    """Page + rectangle + font of each editable value of the Passport
    Authorization Letter, for the editable preview (see
    docx_utils.ProbeShader for how)."""
    shader = docx_utils.ProbeShader()
    probe = generate_passport_authorization_docx(
        people, recipient_centre_name, recipient_address, collector_name, date_override, edited_fields, _shader=shader
    )
    try:
        pdf = docx_utils.convert_docx_bytes_to_pdf(probe, base_name="passport_authorization_layout")
    except docx_utils.DocxBuildError as e:
        raise AuthorizationLetterError(str(e))
    return shader.layout_from_pdf(pdf, probe)


# ---------------------------------------------------------------------------
# Company Authorization Letter
# ---------------------------------------------------------------------------


def _company_applicant_line_text(person: dict) -> str:
    name = (person.get("fullName") or "").strip() or "—"
    return f"{name} - Passport No.: {person.get('passportNumber') or '—'}"


def compose_company_editable_fields(people: list[dict], recipient_text: str, date_override: Optional[str] = None) -> dict:
    """The Word-like body editor's seed values for the Company
    Authorization Letter — the SAME shared-compose-function pattern
    established for the Europe Cover Letter and Hotel Voucher (project
    rule 15): one place that turns this letter's inputs into display
    text, used by both the real generator's non-edited fallback and the
    `/compose-fields` endpoint that seeds the editor. Field keys:
    "date", "recipient", and one "applicant_<index>" per person (index
    matches `people`'s own order)."""
    import html as _html_mod

    fields = {
        "date": f"<p>Date- {_html_mod.escape(_format_letter_date(date_override))}</p>",
        # "The Consulate General of Japan\nMumbai, India" — the address sits on
        # its own line inside the same paragraph, in the editor as in the file.
        "recipient": "<p>" + _html_mod.escape((recipient_text or "").strip() or chr(8212)).replace("\n", "<br>") + "</p>",
    }
    for i, person in enumerate(people):
        fields[f"applicant_{i}"] = f"<p>{_html_mod.escape(_company_applicant_line_text(person))}</p>"
    return fields


def generate_company_authorization_docx(
    people: list[dict],
    recipient_text: str,
    date_override: Optional[str] = None,
    edited_fields: Optional[dict] = None,
    _shader: Optional[docx_utils.ProbeShader] = None,
) -> bytes:
    """Builds the Company Authorization Letter .docx for any number of
    applicants — the template's one real applicant-line paragraph is used
    as the clone-template and repeated once per applicant (the same
    clone-a-real-block technique as the Hotel Voucher engine's multi-hotel
    handling). Returns raw .docx bytes. Raises ValueError /
    AuthorizationLetterError on any problem — never returns a silently-
    wrong or empty document.

    `edited_fields`, when given, is a `{fieldKey: html}` map (see
    `compose_company_editable_fields` for the key set) — a staff member's
    Word-like edits to this letter's own generated Date/Recipient/
    Applicant-line text, applied instead of the auto-generated value for
    exactly the fields present (the fixed "Dear Sir/Madam", boilerplate
    body sentences and signature block are never touched either way —
    project rule 5).

    Frontend rework, Phase 4: the applicant-line CLONING happens first,
    so every applicant line's own Paragraph object is captured directly
    from that operation — never re-derived by index afterwards. The date
    (paragraphs[2]) and recipient (paragraphs[6]) paragraphs are likewise
    captured into stable Python variables BEFORE any editable-field
    mutation runs, because replacing an EARLIER paragraph's content via
    docx_utils.replace_paragraph_range_with_html can change how many
    paragraphs the document has (a multi-line edit does not have to stay
    one paragraph), which would silently invalidate a later `paragraphs[N]`
    re-index — the exact hazard that helper's own docstring warns about."""
    if not people:
        raise ValueError("At least one applicant is required to generate this letter.")

    document = _load_template(COMPANY_TEMPLATE_PATH, "Company Authorization Letter")
    paragraphs = document.paragraphs

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
    applicant_paragraphs = [Paragraph(el, document) for el in line_els]

    # Captured NOW (stable Python object references), before either edit
    # below can shift what `document.paragraphs[2]`/`[6]` would mean.
    date_paragraph = document.paragraphs[2]
    recipient_paragraph = document.paragraphs[6]

    if _shader is not None:
        _shader.shade("date", date_paragraph)
        _shader.shade("recipient", recipient_paragraph)
        for i, para in enumerate(applicant_paragraphs):
            _shader.shade(f"applicant_{i}", para)

    edited_fields = edited_fields or {}

    date_html = edited_fields.get("date")
    if date_html is not None:
        docx_utils.replace_paragraph_range_with_html(document, date_paragraph, date_paragraph, date_html)
    else:
        docx_utils.set_paragraph_text(date_paragraph, f"Date- {_format_letter_date(date_override)}")

    recipient_html = edited_fields.get("recipient")
    if recipient_html is not None:
        docx_utils.replace_paragraph_range_with_html(document, recipient_paragraph, recipient_paragraph, recipient_html)
    else:
        docx_utils.set_paragraph_text(recipient_paragraph, (recipient_text or "").strip() or "—")

    for i, (para, person) in enumerate(zip(applicant_paragraphs, people)):
        field_html = edited_fields.get(f"applicant_{i}")
        if field_html is not None:
            docx_utils.replace_paragraph_range_with_html(document, para, para, field_html)
        else:
            _assert_run_count(para, 3, "applicant line")
            name = (person.get("fullName") or "").strip() or "—"
            para.runs[0].text = f"{name} "
            para.runs[2].text = person.get("passportNumber") or "—"

    import io

    document_blocks.finalize(document, edited_fields, _shader)
    buf = io.BytesIO()
    document.save(buf)
    return buf.getvalue()


def generate_company_authorization_pdf(
    people: list[dict],
    recipient_text: str,
    date_override: Optional[str] = None,
    edited_fields: Optional[dict] = None,
) -> bytes:
    docx_bytes = generate_company_authorization_docx(people, recipient_text, date_override, edited_fields)
    try:
        return docx_utils.convert_docx_bytes_to_pdf(docx_bytes, base_name="company_authorization")
    except docx_utils.DocxBuildError as e:
        raise AuthorizationLetterError(str(e))


def compute_company_field_layout(people, recipient_text, date_override=None, edited_fields=None) -> dict:
    """Same as compute_passport_field_layout, for the Company Authorization Letter."""
    shader = docx_utils.ProbeShader()
    probe = generate_company_authorization_docx(people, recipient_text, date_override, edited_fields, _shader=shader)
    try:
        pdf = docx_utils.convert_docx_bytes_to_pdf(probe, base_name="company_authorization_layout")
    except docx_utils.DocxBuildError as e:
        raise AuthorizationLetterError(str(e))
    return shader.layout_from_pdf(pdf, probe)
