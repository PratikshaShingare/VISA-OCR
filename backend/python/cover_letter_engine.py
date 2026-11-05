"""
Khanna Travels & Holidays — Cover Letter document generators
================================================================

Generates the three real, region-specific Khanna Travels & Holidays
Tourist Visa Cover Letters, each from its own real, unmodified reference
template (project rule 5 — Document Template Rule):

    reference-cover-letter-formats/Europe/Europe_covering_letter_template_clean.docx
    reference-cover-letter-formats/Japan/Japan_covering_letter_template_clean.docx
    reference-templates/Singapore/ (Singapore has its own two templates and its own
    engine, singapore_letter_engine.py — see the Singapore section at the bottom)

Unlike the Passport Authorization templates (Phase 8), these three ARE
genuine blank templates — every dynamic paragraph in all three is a
single run holding bracketed `[Token]` placeholders, confirmed by direct
inspection before writing any fill logic here. Token substitution is
still done paragraph-by-paragraph (`docx_utils.apply_token_map_to_paragraph`)
rather than as one document-wide sweep, because the SAME bracket token
(e.g. `[Passport Number]`, `[Job Title]`) legitimately needs two
different real values in two different places — an applicant's vs. a
companion's — and a blind find-and-replace-everywhere would silently
write the same value into both. A few Europe sentences additionally have
the identical token appearing *twice within one paragraph* with two
different values (e.g. "[Number of Nights]" for a primary destination
and an optional second-country leg) — those specific paragraphs are
composed directly as plain Python strings instead of token-substituted,
for the same reason.

One deliberate, documented judgement call on a real template quirk
(neither left in the generated output — project rule 9, no faked/broken
content reaches a client):
  - Japan's companion sentence carries a literal, human-authored
    instruction, `[Add additional family member details here if
    applicable].` — stripped outright rather than ever shown to a client,
    consistent with this letter's own real person cap (see below).

Traveller counts (frontend rework, Stage 2 — no cap on any region):
  - Europe: the applicant alone, or with any number of companions. With
    one companion the wording is exactly the reference template's
    ("along with my wife, Name ..."); with several, every companion is
    named with their own relation and only companions with job details
    entered get a "... is working for ..." sentence (children etc. do not).
  - Japan: the applicant alone, or with any number of companions — the
    template's single companion line ("[Relation] [Passenger 2 Name] ...
    [Occupation]") is repeated once per companion, and the template's own
    "[Add additional family member details here if applicable]" hint is
    still stripped, never shown to a client.
  - Singapore: applicant alone, or applicant + any number of companions —
    its passenger table is a genuinely repeatable row (Sr no./Name/
    Passport/Relation/Occupation), cloned the same way the Company
    Authorization Letter's applicant line is cloned (Phase 8), and its
    intro sentence is composed (not just token-filled) so "along with my
    Family" is dropped cleanly when travelling solo.
"""

from __future__ import annotations

import io
import os
from typing import Optional

from docx import Document
from docx.table import Table
from docx.text.paragraph import Paragraph

import document_blocks
import docx_utils
import letter_shared
import singapore_letter_engine

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_REFERENCE_ROOT = os.path.normpath(os.path.join(_THIS_DIR, "..", "..", "reference-cover-letter-formats"))

EUROPE_TEMPLATE_PATH = os.path.join(_REFERENCE_ROOT, "Europe", "Europe_covering_letter_template_clean.docx")
JAPAN_TEMPLATE_PATH = os.path.join(_REFERENCE_ROOT, "Japan", "Japan_covering_letter_template_clean.docx")


class CoverLetterError(docx_utils.DocxBuildError):
    """Raised whenever a cover letter genuinely cannot be generated —
    never swallowed to produce a fake/empty document (project rule 9)."""


def _load_template(path: str, label: str) -> Document:
    if not os.path.isfile(path):
        raise CoverLetterError(
            f"{label} reference template not found at {path}. This file is part "
            "of the project's read-only reference material (reference-cover-letter-"
            "formats/) and must already exist on this machine — it is never created "
            "by this app."
        )
    return Document(path)  # only ever read, never written back to


def _relation_word_or_fallback(relation: Optional[str], sex: Optional[str]) -> str:
    return letter_shared.relation_word(relation, sex) or "family member"


def _relation_phrase_or_fallback(relation: Optional[str], sex: Optional[str]) -> str:
    return letter_shared.relation_phrase(relation, sex) or "my family member"


def _phone_or_dash(phone: Optional[str]) -> str:
    digits = letter_shared.local_phone_digits(phone)
    return f"+91 {digits}" if digits else "—"


# ---------------------------------------------------------------------------
# Europe
# ---------------------------------------------------------------------------


def _companion_list(companion) -> list:
    """`companion` may be None (travelling alone), one companion dict, or a
    list of them — every letter below accepts all three, so the original
    one-companion callers keep working unchanged."""
    if not companion:
        return []
    if isinstance(companion, dict):
        return [companion]
    return [c for c in companion if c]


def _relations_for(companions: list, fields: dict, fallback: str) -> list:
    """[(phrase, bare)] per companion — ('my wife', 'wife'). With ONE
    companion the single relation control (travellerRelation /
    travellerRelationText) decides, exactly as before; with several, each
    person carries their own choice (falling back to what their traveller
    record says)."""
    out = []
    for c in companions:
        if len(companions) == 1:
            choice, text = fields.get("travellerRelation"), fields.get("travellerRelationText")
        else:
            choice, text = c.get("travellerRelation"), c.get("travellerRelationText")
        out.append(letter_shared.traveller_relation(choice, text, c, fallback))
    return out


def _join_list(items: list) -> str:
    """'a' / 'a and b' / 'a; b; and c' (semicolons once there are three or
    more, because each item already contains a comma: 'my wife, Anita')."""
    items = [i for i in items if i]
    if len(items) <= 1:
        return items[0] if items else ""
    if len(items) == 2:
        return f"{items[0]} and {items[1]}"
    return "; ".join(items[:-1]) + "; and " + items[-1]


def _join_simple(items: list) -> str:
    items = [i for i in items if i]
    if len(items) <= 1:
        return items[0] if items else ""
    return ", ".join(items[:-1]) + " and " + items[-1]


def _companion_job(companion: dict, fields: dict, single: bool) -> dict:
    """Employment details for one companion: the person's own entries, or —
    for the one-companion form — the original companion* form fields."""
    job = companion.get("jobTitle") or ""
    employer = companion.get("employerName") or ""
    since = companion.get("employmentStartYear") or ""
    if single:
        job = job or fields.get("companionJobTitle") or ""
        employer = employer or fields.get("companionEmployerName") or ""
        since = since or fields.get("companionEmploymentStartYear") or ""
    return {"job": job, "employer": employer, "since": since}


def compose_europe_body_paragraphs(applicant: dict, companion: Optional[dict], fields: dict) -> list:
    """Composes the Europe Cover Letter's three free-composed body
    paragraphs (template indices 8-10) as plain {"text", "align"} blocks.
    Shared by the real DOCX generator below AND the Phase 4 'compose body
    text for editing' endpoint (app.py), so the exact same real wording
    seeds the Word-like editor as ends up in the generated document —
    never a second, hand-duplicated copy of this business logic (project
    rule 15).

    All three resolve to JUSTIFY alignment in the real reference
    template — paragraph 8 directly (`w:jc w:val="both"`), paragraphs 9
    and 10 by inheriting it from their own 'Body Text' paragraph style
    (confirmed by direct inspection of the template's styles.xml, not
    guessed) — so all three are reported here as "justify".

    `fields` keys used: travelStartDate, travelEndDate,
    cityCountryOfResidence, applicantEmploymentStatus, applicantJobTitle,
    applicantEmployerName, companionJobTitle, companionEmployerName,
    companionEmploymentStartYear, destinationCountry, nextCountry,
    nextTravelStartDate, nextTravelEndDate, nextNumberOfNights,
    numberOfNights, travellerRelation, travellerRelationText.

    `companion` None = the applicant travelling alone: every "we/our/along
    with my ..." is written in the singular instead."""
    companions = _companion_list(companion)
    solo = not companions
    many = len(companions) > 1
    if solo:
        relation_with_name = relation_bare = ""
    else:
        relations = _relations_for(companions, fields, "family member")
        with_names = [f"{phrase}, {c.get('fullName') or '—'}" for (phrase, _bare), c in zip(relations, companions)]
        relation_with_name = _join_list(with_names)
        relation_bare = relations[0][1]

    passport_part = (
        f"I, {letter_shared.display_name(applicant)} (holding Indian Passport No.: "
        f"{applicant.get('passportNumber') or '—'} issued at {applicant.get('placeOfIssue') or '—'} on "
        f"{applicant.get('passportIssueDate') or '—'}) would like to visit your admired country"
    )
    dates_part = (
        f"from {fields.get('travelStartDate') or '—'} to {fields.get('travelEndDate') or '—'} "
        "for the purpose of Tourism."
    )
    if solo:
        para8 = f"{passport_part} {dates_part}"
        para9 = (
            f"I reside in {fields.get('cityCountryOfResidence') or '—'} along with my parents and few close "
            "relatives. I am financially independent and Employed – "
            f"{fields.get('applicantEmploymentStatus') or '—'}. I am a {fields.get('applicantJobTitle') or '—'} at "
            f"{fields.get('applicantEmployerName') or '—'}. Kindly find my relevant documents for your reference."
        )
    elif not many:
        para8 = f"{passport_part} along with {relation_with_name} {dates_part}"
        para9 = (
            f"I and {relation_with_name} reside in {fields.get('cityCountryOfResidence') or '—'} along with our "
            "parents and few close relatives. We both are financially independent and Employed – "
            f"{fields.get('applicantEmploymentStatus') or '—'}. I am a {fields.get('applicantJobTitle') or '—'} at "
            f"{fields.get('applicantEmployerName') or '—'}. While my {relation_bare} is working for "
            f"{fields.get('companionEmployerName') or '—'} since {fields.get('companionEmploymentStartYear') or '—'}, "
            f"currently as {fields.get('companionJobTitle') or '—'}. Kindly find our relevant documents for your "
            "reference."
        )
    else:
        # Two or more companions: the same wording, with every companion named
        # with their relation. Not everyone travelling is employed (children,
        # parents), so each companion's job sentence appears only when staff
        # entered job details for them.
        para8 = f"{passport_part} along with {relation_with_name} {dates_part}"
        job_sentences = []
        for (phrase, _bare), c in zip(relations, companions):
            job = _companion_job(c, fields, single=False)
            if not (job["job"] or job["employer"]):
                continue
            lead = phrase[:1].upper() + phrase[1:]
            works = f"working for {job['employer']}" if job["employer"] else "working"
            since = f" since {job['since']}" if job["since"] else ""
            role = f", currently as {job['job']}" if job["job"] else ""
            job_sentences.append(f"{lead} is {works}{since}{role}.")
        para9 = (
            f"I, along with {relation_with_name}, reside in {fields.get('cityCountryOfResidence') or '—'} along with our "
            "parents and few close relatives. I am financially independent and Employed – "
            f"{fields.get('applicantEmploymentStatus') or '—'}. I am a {fields.get('applicantJobTitle') or '—'} at "
            f"{fields.get('applicantEmployerName') or '—'}. "
            + "".join(f"{sentence} " for sentence in job_sentences)
            + "Kindly find our relevant documents for your reference."
        )

    destination = fields.get("destinationCountry") or "—"
    next_country = (fields.get("nextCountry") or "").strip()
    destination_or_countries = f"{destination} and {next_country}" if next_country else destination
    next_leg = (
        f" and then to {next_country} for {fields.get('nextNumberOfNights') or '—'} from "
        f"{fields.get('nextTravelStartDate') or '—'} to {fields.get('nextTravelEndDate') or '—'}"
        if next_country
        else ""
    )
    visit_part = (
        f"{destination} for {fields.get('numberOfNights') or '—'} from {fields.get('travelStartDate') or '—'} to "
        f"{fields.get('travelEndDate') or '—'}{next_leg}."
    )
    if solo:
        para10 = (
            f"I have planned to visit {destination_or_countries} for the purpose of Tourism. I look forward to "
            "visiting the country, exploring the beautiful sights, witnessing its rich culture and spending "
            f"leisure time. I would be visiting {visit_part} Kindly find my relevant documents for your perusal. "
            "I will return back to India after the end of my visit as I need to rejoin and look after my work "
            "and personal commitments."
        )
    elif not many:
        para10 = (
            f"{relation_with_name[:1].upper() + relation_with_name[1:]} and I have planned to visit "
            f"{destination_or_countries} for the purpose of "
            "Tourism. We look forward to visiting the country, exploring the beautiful sights, witnessing its rich "
            f"culture and spending leisure time together. We would be visiting {visit_part} Kindly find our "
            "relevant documents for your perusal. "
            "We will return back to India after the end of our visit as we need to rejoin and look after our work "
            "and personal commitments."
        )
    else:
        para10 = (
            f"I, along with {relation_with_name}, have planned to visit "
            f"{destination_or_countries} for the purpose of "
            "Tourism. We look forward to visiting the country, exploring the beautiful sights, witnessing its rich "
            f"culture and spending leisure time together. We would be visiting {visit_part} Kindly find our "
            "relevant documents for your perusal. "
            "We will return back to India after the end of our visit as we need to rejoin and look after our work "
            "and personal commitments."
        )

    return [
        {"text": para8, "align": "justify"},
        {"text": para9, "align": "justify"},
        {"text": para10, "align": "justify"},
    ]


def compose_europe_body_html(applicant: dict, companion: Optional[dict], fields: dict) -> str:
    """HTML seed for the Phase 4 Quill body editor — the exact same real
    wording `compose_europe_body_paragraphs` returns (and therefore the
    same wording the real generator writes when nothing has been edited
    yet), wrapped as Quill-compatible `<p>` blocks with its own
    `ql-align-justify` class so the editor shows/preserves the template's
    real justified alignment by default. Text is HTML-escaped since
    applicant/companion names are real, uncontrolled data."""
    import html as _html

    parts = []
    for block in compose_europe_body_paragraphs(applicant, companion, fields):
        cls = ' class="ql-align-justify"' if block["align"] == "justify" else ""
        parts.append(f"<p{cls}>{_html.escape(block['text'])}</p>")
    return "".join(parts)


def generate_europe_cover_letter_docx(
    applicant: dict,
    companion: Optional[dict],
    fields: dict,
    date_override: Optional[str] = None,
    edited_body_html: Optional[str] = None,
    _shader: Optional["docx_utils.ProbeShader"] = None,
    edited_blocks: Optional[dict] = None,
) -> bytes:
    """`fields` keys used: recipientText, destinationCountry,
    travelStartDate, travelEndDate, cityCountryOfResidence,
    numberOfNights, applicantEmploymentStatus, applicantJobTitle,
    applicantEmployerName, companionJobTitle, companionEmployerName,
    companionEmploymentStartYear, nextCountry, nextTravelStartDate,
    nextTravelEndDate, nextNumberOfNights, fundingArrangement.

    `edited_body_html` — Phase 4 proof of concept: when given (not None),
    real HTML from the staff member's own Quill edits to the letter's
    three free-composed body paragraphs (template indices 8-10) —
    everything else in the letter (header/footer/margins/fonts, every
    other paragraph, the signature block) is produced by this exact same
    unmodified code path regardless (project rule 5 — Document Template
    Rule). When None (the normal/default path), the body is composed
    automatically via `compose_europe_body_paragraphs`, unchanged from
    before Phase 4."""
    if not applicant:
        raise ValueError("At least the applicant is required to generate this letter.")

    document = _load_template(EUROPE_TEMPLATE_PATH, "Europe Cover Letter")
    paragraphs = document.paragraphs

    docx_utils.apply_token_map_to_paragraph(paragraphs[0], {"[Date]": letter_shared.format_letter_date(date_override)})
    docx_utils.set_paragraph_text(paragraphs[3], (fields.get("recipientText") or "").strip() or "—")
    docx_utils.apply_token_map_to_paragraph(
        paragraphs[5], {"[Destination Country]": fields.get("destinationCountry") or "—"}
    )

    # Every paragraph AFTER the editable 8-10 body range is captured into
    # a stable Python reference BEFORE that range is touched below:
    # docx_utils.replace_paragraph_range_with_html inserts/removes real
    # paragraph elements, and python-docx's `document.paragraphs` is a
    # live view whose indices shift the moment that happens — re-indexing
    # into `paragraphs[11]`/`[17]`/`[18]`/`[19]` AFTER that call could
    # silently grab the wrong paragraph if the edited body ends up with a
    # different paragraph count than the original 3 (see that helper's
    # own docstring).
    funding_paragraph = paragraphs[11]
    enclosed_paragraph = paragraphs[12]
    request_paragraph = paragraphs[13]
    signature_name_paragraph = paragraphs[17]
    signature_phone_paragraph = paragraphs[18]
    signature_email_paragraph = paragraphs[19]

    if _shader is not None:  # layout probe only — the three body paragraphs read back as one block
        for body_index in (8, 9, 10):
            _shader.shade("body", paragraphs[body_index])

    if edited_body_html is not None:
        docx_utils.replace_paragraph_range_with_html(document, paragraphs[8], paragraphs[10], edited_body_html)
    else:
        body_blocks = compose_europe_body_paragraphs(applicant, companion, fields)
        docx_utils.set_paragraph_text(paragraphs[8], body_blocks[0]["text"])
        docx_utils.set_paragraph_text(paragraphs[9], body_blocks[1]["text"])
        docx_utils.set_paragraph_text(paragraphs[10], body_blocks[2]["text"])

    docx_utils.apply_token_map_to_paragraph(
        funding_paragraph, {"[Funding Arrangement]": fields.get("fundingArrangement") or "—"}
    )
    if not companion:
        # Travelling alone: the template's three fixed closing sentences say
        # "us / our" — only those pronouns change, the rest (and the
        # formatting) stays exactly as the template has it.
        docx_utils.apply_token_map_to_paragraph(
            funding_paragraph, {"expenses for us will": "expenses for me will", "find our financial": "find my financial"}
        )
        docx_utils.apply_token_map_to_paragraph(
            enclosed_paragraph, {"find our visa": "find my visa", "support our visa": "support my visa"}
        )
        docx_utils.apply_token_map_to_paragraph(request_paragraph, {"grant us the": "grant me the"})

    docx_utils.apply_token_map_to_paragraph(signature_name_paragraph, {"[Applicant Full Name]": letter_shared.display_name(applicant)})
    docx_utils.apply_token_map_to_paragraph(signature_phone_paragraph, {"[Phone Number]": _phone_or_dash(applicant.get("phone"))})
    docx_utils.apply_token_map_to_paragraph(signature_email_paragraph, {"[Email Address]": (applicant.get("email") or "").strip() or "—"})

    document_blocks.finalize(document, edited_blocks, _shader)
    buf = io.BytesIO()
    document.save(buf)
    return buf.getvalue()


def generate_europe_cover_letter_pdf(
    applicant: dict,
    companion: dict,
    fields: dict,
    date_override: Optional[str] = None,
    edited_body_html: Optional[str] = None,
    edited_blocks: Optional[dict] = None,
) -> bytes:
    docx_bytes = generate_europe_cover_letter_docx(
        applicant, companion, fields, date_override, edited_body_html, edited_blocks=edited_blocks
    )
    try:
        return docx_utils.convert_docx_bytes_to_pdf(docx_bytes, base_name="europe_cover_letter")
    except docx_utils.DocxBuildError as e:
        raise CoverLetterError(str(e))


def compute_europe_field_layout(
    applicant: dict,
    companion: dict,
    fields: dict,
    date_override: Optional[str] = None,
    edited_body_html: Optional[str] = None,
    edited_blocks: Optional[dict] = None,
) -> dict:
    """Page + rectangle + font of the editable body of the Europe Cover
    Letter, for the editable preview (see docx_utils.ProbeShader)."""
    shader = docx_utils.ProbeShader()
    probe = generate_europe_cover_letter_docx(
        applicant, companion, fields, date_override, edited_body_html, _shader=shader, edited_blocks=edited_blocks
    )
    try:
        pdf = docx_utils.convert_docx_bytes_to_pdf(probe, base_name="europe_cover_letter_layout")
    except docx_utils.DocxBuildError as e:
        raise CoverLetterError(str(e))
    return shader.layout_from_pdf(pdf)


# ---------------------------------------------------------------------------
# Japan
# ---------------------------------------------------------------------------


def _fill_japan_hotel_table(document: Document, hotels: list[dict]) -> None:
    table = document.tables[0]
    header = [c.text.strip() for c in table.rows[0].cells]
    if header != ["NAME", "DATE", "CONTACT NO."]:
        raise CoverLetterError(
            "Japan Cover Letter template structure has changed (hotel table header "
            f"was {header!r}) — cannot safely fill it."
        )
    if len(table.rows) < 3:
        raise CoverLetterError(
            "Japan Cover Letter template structure has changed (expected 2 example "
            "hotel rows) — cannot safely fill it."
        )
    template_row_el = table.rows[1]._tr
    extra_row_el = table.rows[2]._tr
    extra_row_el.getparent().remove(extra_row_el)

    if not hotels:
        # No hotel info given at all — remove the now-templateless row too
        # rather than leave literal "[Hotel Name 1]" placeholder text in a
        # real client-facing letter.
        template_row_el.getparent().remove(template_row_el)
        return

    clone_els = docx_utils.clone_and_insert_after(template_row_el, len(hotels) - 1)
    row_els = [template_row_el] + clone_els
    for row_el, hotel in zip(row_els, hotels):
        cells = _cells_of_row_element(table, row_el)
        docx_utils.set_cell_text(cells[0], hotel.get("name") or "—")
        stay = f"{hotel.get('checkIn') or '—'} - {hotel.get('checkOut') or '—'}"
        docx_utils.set_cell_text(cells[1], stay)
        docx_utils.set_cell_text(cells[2], hotel.get("contactNo") or "—")


def _cells_of_row_element(table: Table, row_el):
    """Returns the docx Cell objects belonging to a specific `<w:tr>`
    element, even one just cloned and not yet reflected in `table.rows`
    (python-docx's Table wraps the live XML, so a freshly inserted row is
    already valid to address this way — the same technique the Hotel
    Voucher engine's multi-hotel cloning already relies on)."""
    from docx.table import _Row

    row = _Row(row_el, table)
    return row.cells


def generate_japan_cover_letter_docx(
    applicant: dict,
    companion: Optional[dict],
    fields: dict,
    hotels: list[dict],
    date_override: Optional[str] = None,
    edited_blocks: Optional[dict] = None,
    _shader: Optional["docx_utils.ProbeShader"] = None,
) -> bytes:
    """`fields` keys used: destinationCountry, travelStartDate,
    travelEndDate, applicantEmployerOccupation, companionOccupation,
    fundingArrangement, travellerRelation, travellerRelationText.
    `companion` None = the applicant travelling alone."""
    if not applicant:
        raise ValueError("At least the applicant is required to generate this letter.")

    document = _load_template(JAPAN_TEMPLATE_PATH, "Japan Cover Letter")
    paragraphs = document.paragraphs

    docx_utils.apply_token_map_to_paragraph(paragraphs[1], {"[Date]": letter_shared.format_letter_date(date_override)})
    docx_utils.apply_token_map_to_paragraph(
        paragraphs[8], {"[Destination Country]": fields.get("destinationCountry") or "—"}
    )
    # Captured before anything is removed (python-docx's paragraph list is a
    # live view — indices shift as soon as one is deleted).
    companion_paragraph = paragraphs[12]
    hotels_intro_paragraph = paragraphs[13]
    funding_paragraph = paragraphs[15]
    attachment_paragraph = paragraphs[16]

    # "along with my family" in the template — with the relation staff chose
    # ("my wife", or their own wording) when there is a companion, and left
    # out altogether when the applicant travels alone. Several companions:
    # each is named by their own relation ("my wife, my son and my daughter").
    companions = _companion_list(companion)
    if companions:
        relations = _relations_for(companions, fields, "family")
        along_with = "along with " + _join_simple([phrase for phrase, _bare in relations])
    else:
        along_with = ""
    para10_map = {
        "[Passenger 1 Name]": letter_shared.display_name(applicant),
        "[Passport Number]": applicant.get("passportNumber") or "—",
        "[Place of Issue]": applicant.get("placeOfIssue") or "—",
        "[Passport Issue Date]": applicant.get("passportIssueDate") or "—",
        "[Travel Start Date]": fields.get("travelStartDate") or "—",
        "[Travel End Date]": fields.get("travelEndDate") or "—",
    }
    docx_utils.apply_token_map_to_paragraph(paragraphs[10], para10_map)
    docx_utils.apply_token_map_to_paragraph(
        paragraphs[10],
        {" along with my family": f" {along_with}" if along_with else ""},
    )
    docx_utils.apply_token_map_to_paragraph(
        paragraphs[11], {"[Employer / Occupation]": fields.get("applicantEmployerOccupation") or "—"}
    )
    if companions:
        # The template has one line per travelling companion ("[Relation]
        # [Passenger 2 Name] ... [Occupation]"); it is repeated for each
        # additional companion, in the same position and formatting.
        extra_elements = docx_utils.clone_and_insert_after(companion_paragraph._p, len(companions) - 1)
        line_paragraphs = [companion_paragraph] + [
            Paragraph(el, companion_paragraph._parent) for el in extra_elements
        ]
        for line, person, (_phrase, relation_bare) in zip(line_paragraphs, companions, relations):
            occupation = person.get("occupation") or (
                fields.get("companionOccupation") if len(companions) == 1 else ""
            )
            if not occupation and len(companions) > 1:
                # Not everyone travelling works (children, parents): drop the
                # "is [Occupation]" tail instead of printing "is —".
                docx_utils.apply_token_map_to_paragraph(line, {" is [Occupation]": ""})
            docx_utils.apply_token_map_to_paragraph(
                line,
                {
                    "[Relation]": relation_bare[:1].upper() + relation_bare[1:],
                    "[Passenger 2 Name]": letter_shared.display_name(person),
                    "[Passport Number]": person.get("passportNumber") or "—",
                    "[Place of Issue]": person.get("placeOfIssue") or "—",
                    "[Passport Issue Date]": person.get("passportIssueDate") or "—",
                    "[Occupation]": occupation or "—",
                    # The template's own human-authored instruction — never shown
                    # to a client (see module docstring).
                    " [Add additional family member details here if applicable].": "",
                },
            )
    else:
        # Travelling alone: there is no companion sentence, and the template's
        # "we / our" closing lines become "I / my".
        docx_utils.delete_paragraph(companion_paragraph)
        docx_utils.apply_token_map_to_paragraph(hotels_intro_paragraph, {"We will be": "I will be"})
        docx_utils.apply_token_map_to_paragraph(funding_paragraph, {"All our travel": "All my travel"})
        docx_utils.apply_token_map_to_paragraph(
            attachment_paragraph,
            {"attachment to our visa": "attachment to my visa", "issuance of our visa": "issuance of my visa"},
        )
    docx_utils.apply_token_map_to_paragraph(
        funding_paragraph, {"[Sponsor Name / Funding Arrangement]": fields.get("fundingArrangement") or "—"}
    )
    docx_utils.apply_token_map_to_paragraph(paragraphs[21], {"[Passenger 1 Name]": letter_shared.display_name(applicant)})
    docx_utils.apply_token_map_to_paragraph(paragraphs[22], {"[Phone Number]": _phone_or_dash(applicant.get("phone"))})
    docx_utils.apply_token_map_to_paragraph(
        paragraphs[23], {"[Email Address]": (applicant.get("email") or "").strip() or "—"}
    )

    _fill_japan_hotel_table(document, hotels)

    document_blocks.finalize(document, edited_blocks, _shader)
    buf = io.BytesIO()
    document.save(buf)
    return buf.getvalue()


def generate_japan_cover_letter_pdf(
    applicant: dict, companion: dict, fields: dict, hotels: list[dict], date_override: Optional[str] = None,
    edited_blocks: Optional[dict] = None,
) -> bytes:
    docx_bytes = generate_japan_cover_letter_docx(
        applicant, companion, fields, hotels, date_override, edited_blocks=edited_blocks
    )
    try:
        return docx_utils.convert_docx_bytes_to_pdf(docx_bytes, base_name="japan_cover_letter")
    except docx_utils.DocxBuildError as e:
        raise CoverLetterError(str(e))


def compute_japan_field_layout(
    applicant: dict, companion: dict, fields: dict, hotels: list[dict], date_override: Optional[str] = None,
    edited_blocks: Optional[dict] = None,
) -> dict:
    """Where every block of the Japan Cover Letter sits on the page of the
    real PDF, for the editable preview (see document_blocks)."""
    shader = docx_utils.ProbeShader()
    probe = generate_japan_cover_letter_docx(
        applicant, companion, fields, hotels, date_override, edited_blocks=edited_blocks, _shader=shader
    )
    try:
        pdf = docx_utils.convert_docx_bytes_to_pdf(probe, base_name="japan_cover_letter_layout")
    except docx_utils.DocxBuildError as e:
        raise CoverLetterError(str(e))
    return shader.layout_from_pdf(pdf)


# ---------------------------------------------------------------------------
# Singapore
#
# Singapore has its own two templates (single traveller / two or multiple
# travellers) and its own engine, singapore_letter_engine.py — nothing else in
# this module is shared with it. These wrappers keep the names the rest of the
# app already calls; the single/multi choice is made from the companion list.
# ---------------------------------------------------------------------------

SINGAPORE_TEMPLATE_PATH = singapore_letter_engine.COVER_SINGLE_TEMPLATE_PATH
SINGAPORE_MULTI_TEMPLATE_PATH = singapore_letter_engine.COVER_MULTI_TEMPLATE_PATH


def generate_singapore_cover_letter_docx(
    applicant: dict,
    companions: list[dict],
    fields: dict,
    date_override: Optional[str] = None,
    edited_blocks: Optional[dict] = None,
    _shader: Optional["docx_utils.ProbeShader"] = None,
) -> bytes:
    try:
        return singapore_letter_engine.generate_cover_letter_docx(
            applicant, companions, fields, date_override, edited_blocks=edited_blocks, _shader=_shader
        )
    except singapore_letter_engine.SingaporeLetterError as e:
        raise CoverLetterError(str(e))


def generate_singapore_cover_letter_pdf(
    applicant: dict, companions: list[dict], fields: dict, date_override: Optional[str] = None,
    edited_blocks: Optional[dict] = None,
) -> bytes:
    try:
        return singapore_letter_engine.generate_cover_letter_pdf(
            applicant, companions, fields, date_override, edited_blocks=edited_blocks
        )
    except singapore_letter_engine.SingaporeLetterError as e:
        raise CoverLetterError(str(e))


def compute_singapore_field_layout(
    applicant: dict, companions: list[dict], fields: dict, date_override: Optional[str] = None,
    edited_blocks: Optional[dict] = None,
) -> dict:
    """Where every block of the Singapore Cover Letter sits on the page of
    the real PDF, for the editable preview (see document_blocks)."""
    try:
        return singapore_letter_engine.compute_cover_letter_layout(
            applicant, companions, fields, date_override, edited_blocks=edited_blocks
        )
    except singapore_letter_engine.SingaporeLetterError as e:
        raise CoverLetterError(str(e))
