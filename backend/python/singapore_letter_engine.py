"""
Khanna Travels & Holidays — Singapore letters
==============================================

Everything that is specific to Singapore lives here, so no other country's
letter is touched. Four documents, each built from its own clean reference
template (placeholders in square brackets, no client data):

  1. Singapore Cover Letter — Single Traveller          (applicant alone)
  2. Singapore Cover Letter — Two or Multiple Travellers (applicant + any
     number of companions, with the passenger table)
  3. Singapore Authorization 1 — Sub-Agent Declaration Form
  4. Singapore Authorization 2 — Authorisation Letter for Visa Application

Source of truth (read-only, never written by this module — project rule 5):
    reference-templates/Singapore/

The templates were prepared from the agency's own Singapore sample letters:
every name, passport number, phone number and e-mail in those samples was
replaced by a placeholder, obvious typos were corrected, and the wording /
fonts / layout were otherwise kept. Only the placeholders are filled here —
every other word, the QR codes and the signature blocks are the template's.

The cover letter picks the single or the multi-traveller template by itself
from how many people are on the letter (cover_letter_engine delegates here).
"""

from __future__ import annotations

import copy
import io
import os
import re
from datetime import date, datetime
from typing import Optional

from docx import Document
from docx.table import _Row
from docx.text.paragraph import Paragraph
from docx.text.run import Run

import document_blocks
import docx_utils
import letter_shared

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
SINGAPORE_TEMPLATE_DIR = os.path.normpath(os.path.join(_THIS_DIR, "..", "..", "reference-templates", "Singapore"))

COVER_SINGLE_TEMPLATE_PATH = os.path.join(SINGAPORE_TEMPLATE_DIR, "Singapore Cover Letter - Single Traveller.docx")
COVER_MULTI_TEMPLATE_PATH = os.path.join(SINGAPORE_TEMPLATE_DIR, "Singapore Cover Letter - Two or Multiple Travellers.docx")
SUB_AGENT_TEMPLATE_PATH = os.path.join(SINGAPORE_TEMPLATE_DIR, "Singapore Authorization 1 - Sub-Agent Declaration Form.docx")
AUTH_LETTER_TEMPLATE_PATH = os.path.join(
    SINGAPORE_TEMPLATE_DIR, "Singapore Authorization 2 - Authorisation Letter for Visa Application.docx"
)

# Agency staff who sign these forms, as printed on the agency's own samples.
# Both are editable on the form; they are only the starting values.
DEFAULT_CONTACT_PERSON = "Esha Sharma"
DEFAULT_DESIGNATION = "Visa Consultant"
DEFAULT_REPRESENTATIVE = "Mr. Amol Sonawane"


class SingaporeLetterError(docx_utils.DocxBuildError):
    """A Singapore letter genuinely could not be generated — never swallowed
    to produce a fake or half-empty document (project rule 9)."""


def _load(path: str, label: str) -> Document:
    if not os.path.isfile(path):
        raise SingaporeLetterError(
            f"{label} template not found at {path}. It belongs to the project's read-only "
            "reference material (reference-templates/Singapore/) and must already exist."
        )
    return Document(path)


# ---------------------------------------------------------------------------
# Dates and small wording helpers
# ---------------------------------------------------------------------------

_DATE_FORMATS = ("%Y-%m-%d", "%d/%m/%Y", "%d.%m.%Y", "%d-%m-%Y")


def _parse_date(value: Optional[str]) -> Optional[date]:
    text = (value or "").strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _letter_day(date_override: Optional[str]) -> date:
    return _parse_date(date_override) or datetime.now().date()


def _long_date_segments(value: Optional[str]) -> list:
    """'21st September 2026' with the ordinal raised, as the reference letters
    print it. Anything that is not a recognisable date is passed through."""
    d = _parse_date(value)
    if not d:
        return [((value or "").strip() or "—", None)]
    return [
        (str(d.day), None),
        (letter_shared.ordinal_suffix(d.day), "sup"),
        (f" {d.strftime('%B')} {d.year}", None),
    ]


def _slash_date(value: Optional[str]) -> str:
    d = _parse_date(value)
    return d.strftime("%d/%m/%Y") if d else ((value or "").strip() or "—")


def _phone(value: Optional[str]) -> str:
    digits = letter_shared.local_phone_digits(value)
    return f"+91 {digits}" if digits else "—"


def _dash(value: Optional[str]) -> str:
    return (value or "").strip() or "—"


_SELF_FUNDING = {"myself", "ourselves", "self", "me", "individual"}


def _funding_phrase(fields: dict) -> str:
    """What follows 'will be borne by': 'me' when the traveller pays, or the
    payer exactly as entered ('Name (Father)')."""
    raw = (fields.get("fundingArrangement") or "").strip()
    if not raw:
        return "—"
    return "me" if raw.lower() in _SELF_FUNDING else raw


def _bank_statement_owner(fields: dict) -> str:
    """'my bank account' when the traveller pays; otherwise the payer's."""
    raw = (fields.get("fundingArrangement") or "").strip()
    if not raw or raw.lower() in _SELF_FUNDING:
        return "my bank account"
    payer = (fields.get("fundingPayerName") or "").strip() or re.sub(r"\s*\([^)]*\)\s*$", "", raw).strip()
    return f"{payer}'s bank account"


def _join_and(items: list) -> str:
    items = [i for i in items if i]
    if len(items) <= 1:
        return items[0] if items else "—"
    return ", ".join(items[:-1]) + " and " + items[-1]


# ---------------------------------------------------------------------------
# Placeholder replacement that keeps the template's own run formatting
# ---------------------------------------------------------------------------


def _replace_token(paragraph, token: str, segments) -> bool:
    """Replaces `token` (which sits inside ONE run in the clean templates) by
    `segments` — a plain string or a list of (text, style) with style None
    (as the placeholder's own run), 'sup' (raised) or 'plain' (not bold).
    Every new run is a clone of the placeholder's run, so font, size and
    colour never change."""
    if isinstance(segments, str):
        segments = [(segments, None)]
    for run in paragraph.runs:
        if token not in run.text:
            continue
        before, _, after = run.text.partition(token)
        template_el = copy.deepcopy(run._r)
        run.text = before
        anchor = run._r
        new_runs = [(text, style) for text, style in segments] + ([(after, None)] if after else [])
        if not before:
            # Reuse the original (now empty) run as the first new piece.
            first_text, first_style = new_runs.pop(0)
            run.text = first_text
            _style_run(run, first_style)
        for text, style in new_runs:
            el = copy.deepcopy(template_el)
            for child in list(el):
                if not child.tag.endswith("}rPr"):
                    el.remove(child)
            anchor.addnext(el)
            anchor = el
            new = Run(el, paragraph)
            new.text = text
            _style_run(new, style)
        return True
    return False


def _style_run(run, style) -> None:
    if style == "sup":
        run.font.superscript = True
    elif style == "plain":
        run.bold = None


def _fill(paragraph, mapping: dict) -> None:
    for token, value in mapping.items():
        _replace_token(paragraph, token, value)


def _fill_document(document, mapping: dict) -> None:
    """Applies `mapping` to every paragraph of the document (body and table
    cells). Used only for tokens that mean the same thing everywhere."""
    for p in _all_paragraphs(document):
        _fill(p, mapping)


def _all_paragraphs(container):
    out = list(container.paragraphs)
    for table in container.tables:
        for row in table.rows:
            for cell in row.cells:
                out.extend(_all_paragraphs(cell))
    return out


def _find_paragraph(document, needle: str) -> Paragraph:
    for p in _all_paragraphs(document):
        if needle in p.text:
            return p
    raise SingaporeLetterError(
        f"The Singapore template no longer contains the placeholder {needle!r} — it has been changed, "
        "so it cannot be filled safely."
    )


def _finish(document, edited_blocks, shader) -> bytes:
    document_blocks.finalize(document, edited_blocks, shader)
    buf = io.BytesIO()
    document.save(buf)
    return buf.getvalue()


def _to_pdf(docx_bytes: bytes, base_name: str) -> bytes:
    try:
        return docx_utils.convert_docx_bytes_to_pdf(docx_bytes, base_name=base_name)
    except docx_utils.DocxBuildError as e:
        raise SingaporeLetterError(str(e))


# ---------------------------------------------------------------------------
# Cover letters
# ---------------------------------------------------------------------------


def _relations(companions: list, fields: dict) -> list:
    """[(phrase, bare)] per companion — ('my wife', 'wife'). One companion:
    the form's single relation control decides; several: each person's own."""
    out = []
    for c in companions:
        if len(companions) == 1:
            choice, text = fields.get("travellerRelation"), fields.get("travellerRelationText")
        else:
            choice, text = c.get("travellerRelation"), c.get("travellerRelationText")
        out.append(letter_shared.traveller_relation(choice, text, c, "family member"))
    return out


def _remove_paragraph_and_following_blank(paragraph) -> None:
    nxt = paragraph._p.getnext()
    docx_utils.delete_paragraph(paragraph)
    if nxt is not None and nxt.tag.endswith("}p") and not "".join(nxt.itertext()).strip():
        nxt.getparent().remove(nxt)


def _fill_single_cover(document, applicant: dict, fields: dict, date_override: Optional[str]) -> None:
    day = _letter_day(date_override)
    name = letter_shared.display_name(applicant)
    _fill_document(document, {
        "[Date]": f"{day.strftime('%B')} {day.day}, {day.year}",
        "[Applicant Name]": name,
        "[Passport Number]": _dash(applicant.get("passportNumber")),
        "[Place of Issue]": _dash(applicant.get("placeOfIssue")),
        "[Passport Issue Date]": _slash_date(applicant.get("passportIssueDate")),
        "[Hotel Name]": _dash(fields.get("hotelName")),
        "[Hotel Address]": _dash(fields.get("hotelAddress")),
        "[Funding Arrangement]": _funding_phrase(fields),
        "[Phone Number]": _phone(applicant.get("phone")),
        "[Email Address]": _dash(applicant.get("email")),
    })
    intro = _find_paragraph(document, "[Travel Start Date]")
    _replace_token(intro, "[Travel Start Date]", _long_date_segments(fields.get("travelStartDate")))
    _replace_token(intro, "[Travel End Date]", _long_date_segments(fields.get("travelEndDate")))

    occupations = fields.get("occupations") or {}
    occupation = (occupations.get(applicant.get("id")) or "").strip().rstrip(".").strip()
    sentence = _find_paragraph(document, "[Occupation Details]")
    if occupation:
        _replace_token(sentence, "[Occupation Details]", occupation)
    else:
        # Nothing entered: leave the sentence out rather than print a dash.
        _remove_paragraph_and_following_blank(sentence)


def _fill_multi_cover(document, applicant: dict, companions: list, fields: dict, date_override: Optional[str]) -> None:
    day = _letter_day(date_override)
    relations = _relations(companions, fields)
    travelling_with = relations[0][0] if len(companions) == 1 else "my family"
    _fill_document(document, {
        "[Date]": day.strftime("%d.%m.%Y"),
        "[Applicant Name]": letter_shared.display_name(applicant),
        "[Travelling With]": travelling_with,
        "[Hotel Name]": _dash(fields.get("hotelName")),
        "[Hotel Address]": _dash(fields.get("hotelAddress")),
        "[Funding Arrangement]": _funding_phrase(fields),
        "[Bank Statement Of]": _bank_statement_owner(fields),
        "[Phone Number]": _phone(applicant.get("phone")),
        "[Email Address]": _dash(applicant.get("email")),
    })
    intro = _find_paragraph(document, "[Travel Start Date]")
    _replace_token(intro, "[Travel Start Date]", _long_date_segments(fields.get("travelStartDate")))
    _replace_token(intro, "[Travel End Date]", _long_date_segments(fields.get("travelEndDate")))

    # Passenger table: header, the applicant (Relation printed as "Self" in the
    # template) and one template row that is repeated for every companion.
    table = document.tables[0]
    header = [c.text.strip() for c in table.rows[0].cells]
    if header != ["Sr no.", "Passengers Name", "Passport No", "Relation", "Occupation"] or len(table.rows) < 3:
        raise SingaporeLetterError(
            f"The Singapore multi-traveller template's passenger table has changed (header {header!r}) — "
            "it cannot be filled safely."
        )
    occupations = fields.get("occupations") or {}

    def fill_row(row_el, number: int, person: dict, relation: Optional[str]):
        cells = _Row(row_el, table).cells
        mapping = {
            "[Sr No]": str(number),
            "[Passenger Name]": letter_shared.display_name(person),
            "[Passport Number]": _dash(person.get("passportNumber")),
            "[Occupation]": (occupations.get(person.get("id")) or "").strip() or "—",
        }
        if relation is not None:
            mapping["[Relation]"] = relation
        for cell in cells:
            for p in cell.paragraphs:
                _fill(p, mapping)

    applicant_row, template_row = table.rows[1]._tr, table.rows[2]._tr
    clone_els = docx_utils.clone_and_insert_after(template_row, len(companions) - 1)
    fill_row(applicant_row, 1, applicant, None)
    for number, (row_el, companion, (_phrase, bare)) in enumerate(
        zip([template_row] + clone_els, companions, relations), start=2
    ):
        fill_row(row_el, number, companion, bare.capitalize())


def generate_cover_letter_docx(
    applicant: dict,
    companions: list,
    fields: dict,
    date_override: Optional[str] = None,
    edited_blocks: Optional[dict] = None,
    _shader: Optional["docx_utils.ProbeShader"] = None,
) -> bytes:
    """The applicant alone gets the single-traveller letter; the applicant
    with one or more companions gets the multi-traveller letter.

    `fields` keys used: travelStartDate, travelEndDate, hotelName,
    hotelAddress, fundingArrangement, fundingPayerName, occupations (dict
    keyed by person id), travellerRelation, travellerRelationText."""
    if not applicant:
        raise ValueError("At least the applicant is required to generate this letter.")
    companions = [c for c in (companions or []) if c]
    if companions:
        document = _load(COVER_MULTI_TEMPLATE_PATH, "Singapore Cover Letter (two or multiple travellers)")
        _fill_multi_cover(document, applicant, companions, fields, date_override)
    else:
        document = _load(COVER_SINGLE_TEMPLATE_PATH, "Singapore Cover Letter (single traveller)")
        _fill_single_cover(document, applicant, fields, date_override)
    return _finish(document, edited_blocks, _shader)


def generate_cover_letter_pdf(applicant, companions, fields, date_override=None, edited_blocks=None) -> bytes:
    return _to_pdf(
        generate_cover_letter_docx(applicant, companions, fields, date_override, edited_blocks=edited_blocks),
        "singapore_cover_letter",
    )


def compute_cover_letter_layout(applicant, companions, fields, date_override=None, edited_blocks=None) -> dict:
    """Where every block of the letter sits on the page of the real PDF, for
    the editable preview (see document_blocks)."""
    shader = docx_utils.ProbeShader()
    probe = generate_cover_letter_docx(
        applicant, companions, fields, date_override, edited_blocks=edited_blocks, _shader=shader
    )
    return shader.layout_from_pdf(_to_pdf(probe, "singapore_cover_letter_layout"))


# ---------------------------------------------------------------------------
# Authorization 1 — Sub-Agent Declaration Form
# ---------------------------------------------------------------------------


def generate_sub_agent_declaration_docx(
    people: list,
    contact_person: str = "",
    designation: str = "",
    date_override: Optional[str] = None,
    edited_blocks: Optional[dict] = None,
    _shader: Optional["docx_utils.ProbeShader"] = None,
) -> bytes:
    """One declaration for all the listed applicants: how many applications
    are handed over and their passport numbers, signed by the agency's
    contact person."""
    if not people:
        raise ValueError("At least one applicant is required to generate this form.")
    document = _load(SUB_AGENT_TEMPLATE_PATH, "Singapore Sub-Agent Declaration Form")
    day = _letter_day(date_override)

    passport_line = _find_paragraph(document, "[Passport Line]")
    clones = docx_utils.clone_and_insert_after(passport_line._p, len(people) - 1)
    lines = [passport_line] + [Paragraph(el, document) for el in clones]
    for number, (paragraph, person) in enumerate(zip(lines, people), start=1):
        _fill(paragraph, {"[Passport Line]": f"{number}. {_dash(person.get('passportNumber'))}"})

    _fill_document(document, {
        "[Date]": day.strftime("%d/%m/%Y"),
        "[Contact Person]": (contact_person or "").strip() or DEFAULT_CONTACT_PERSON,
        "[Designation]": (designation or "").strip() or DEFAULT_DESIGNATION,
        "[Total Applications]": str(len(people)),
    })
    return _finish(document, edited_blocks, _shader)


def generate_sub_agent_declaration_pdf(people, contact_person="", designation="", date_override=None, edited_blocks=None) -> bytes:
    return _to_pdf(
        generate_sub_agent_declaration_docx(people, contact_person, designation, date_override, edited_blocks),
        "singapore_sub_agent_declaration",
    )


def compute_sub_agent_declaration_layout(people, contact_person="", designation="", date_override=None, edited_blocks=None) -> dict:
    shader = docx_utils.ProbeShader()
    probe = generate_sub_agent_declaration_docx(
        people, contact_person, designation, date_override, edited_blocks, _shader=shader
    )
    return shader.layout_from_pdf(_to_pdf(probe, "singapore_sub_agent_declaration_layout"))


# ---------------------------------------------------------------------------
# Authorization 2 — Authorisation Letter for Visa Application
# ---------------------------------------------------------------------------


def _fee_segments(fee_per_applicant: str, count: int) -> list:
    """'INR 16000/- Pax - 02' — the amount is the per-applicant fee times the
    number of applicants. With no fee entered the amount is left as a line to
    write on by hand."""
    cleaned = re.sub(r"[^0-9.]", "", fee_per_applicant or "")
    try:
        per = float(cleaned)
    except ValueError:
        per = None
    if per is None or per <= 0:
        amount = "INR ______"
    else:
        total = per * count
        amount = f"INR {int(total) if total == int(total) else round(total, 2)}"
    return [(amount, None), ("/-", "plain"), (f" Pax - {count:02d}", None)]


def generate_authorisation_letter_docx(
    people: list,
    representative_name: str = "",
    fee_per_applicant: str = "",
    edited_blocks: Optional[dict] = None,
    _shader: Optional["docx_utils.ProbeShader"] = None,
) -> bytes:
    """The applicant authorises the agency's representative. The letter names
    ONE person (the lead applicant, first in the list) but lists EVERY
    applicant's passport number ('I, A, holder of ... N1 and N2 ... my
    representative'); the fee covers every applicant."""
    if not people:
        raise ValueError("At least one applicant is required to generate this letter.")
    document = _load(AUTH_LETTER_TEMPLATE_PATH, "Singapore Authorisation Letter for Visa Application")
    _fill_document(document, {
        "[Applicant Names]": letter_shared.display_name(people[0]),
        "[Holder Word]": "holder",
        "[Passport Numbers]": _join_and([_dash(p.get("passportNumber")) for p in people]),
        "[Representative Name]": (representative_name or "").strip() or DEFAULT_REPRESENTATIVE,
        "[My Our]": "my",
    })
    fee = _find_paragraph(document, "[Fee Text]")
    _replace_token(fee, "[Fee Text]", _fee_segments(fee_per_applicant, len(people)))
    return _finish(document, edited_blocks, _shader)


def generate_authorisation_letter_pdf(people, representative_name="", fee_per_applicant="", edited_blocks=None) -> bytes:
    return _to_pdf(
        generate_authorisation_letter_docx(people, representative_name, fee_per_applicant, edited_blocks),
        "singapore_authorisation_letter",
    )


def compute_authorisation_letter_layout(people, representative_name="", fee_per_applicant="", edited_blocks=None) -> dict:
    shader = docx_utils.ProbeShader()
    probe = generate_authorisation_letter_docx(
        people, representative_name, fee_per_applicant, edited_blocks, _shader=shader
    )
    return shader.layout_from_pdf(_to_pdf(probe, "singapore_authorisation_letter_layout"))
