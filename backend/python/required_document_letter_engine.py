"""
Khanna Travels & Holidays — Required Document Letter engine
==============================================================

Generates the real "Required Document Letter" — a standalone checklist
letter (not tied to any Applicant/Traveller record) sent to a prospective
client, listing what documents Khanna needs for a given country/visa-type
enquiry. Built from the real, unmodified reference template at
`reference-templates/Required Document Letter/Required Document Letter.docx`
(Document Template Rule, project rule 5) — never a from-scratch layout.

Reference-template inspection (done before writing this module, matching
every prior engine's own discipline): the template DOES carry the real
khannatravels.com letterhead — a logo/contact-details header and a blue
"Head office"/red "Front office" footer bar (`header2.xml`/`footer1.xml`,
wired into `document.xml`'s `sectPr`), confirmed by both direct docx
inspection and a visual PDF-conversion check — it survives the exact same
`docx_utils.convert_docx_bytes_to_pdf` path every other document type
uses, unchanged. (An earlier version of this comment claimed the template
was letterhead-free; that was simply wrong — corrected here, no code
changed.) 35 body paragraphs, 0 tables. Its
document list is almost entirely FIXED common content (Passport Copy,
Aadhar Card, Bank Statement, ITR, Investment Papers) with exactly three
genuinely conditional bullets (Employed / Self-Employed / Invited) plus
four fill-in-the-blank spots: [Country], [Type of Visa], a bank-statement
[DURATION] token, and three literal (non-bracketed) blanks — ITR "__
Years", "Processing Time: __ Months", and "Visa Fees ... INR _____" — each
confirmed by direct run-level inspection (see the per-paragraph run dump
in this session's own notes) to sit in its own dedicated run, so it can be
overwritten without disturbing the bold "Label:" run beside it.

Because several of these label/value paragraphs mix a BOLD label run with
plain-formatted value runs in the same paragraph (e.g. paragraph "Country:
[Country]" — "Country" bold, ": [Country]" not), this module deliberately
does NOT use docx_utils.replace_token_in_paragraph for them: that helper
merges every run's text into the paragraph's first run, which would make
the whole line adopt run 0's formatting and silently bold text that should
stay plain. Instead, the exact run holding each bracket/blank is looked up
by its own known text and overwritten directly — preserving every other
run's formatting untouched, the same "only change the text, never the
formatting" discipline every other engine in this project already follows.
"""

from __future__ import annotations

import io
from typing import Optional

import os

import docx
from docx.text.paragraph import Paragraph

import document_blocks
import docx_utils
import visa_requirements_data


class RequiredDocumentLetterError(docx_utils.DocxBuildError):
    """Raised when the real reference template's structure doesn't match
    what this engine expects — never silently produces a wrong/empty
    document (project rule 9)."""


# Same "resolve once, at import time, relative to this file" convention as
# hotel_voucher_engine.py's own TEMPLATE_PATH — an absolute path, not a raw
# relative string, so it's correct regardless of the process's working
# directory (and so tests' skip_if_missing(rdl.TEMPLATE_PATH) works).
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATE_PATH = os.path.normpath(
    os.path.join(_THIS_DIR, "..", "..", "reference-templates", "Required Document Letter", "Required Document Letter.docx")
)

VALID_VISA_TYPES = tuple(visa_requirements_data.VISA_TYPES)
VALID_EMPLOYMENT_STATUSES = tuple(visa_requirements_data.EMPLOYMENT_STATUSES)

# "Documents Required (Digital Copies):" vs "...(Hard Copies):" — a single
# structural toggle for the WHOLE listed checklist (the user's own explicit
# choice over a per-document toggle, matching how the template already has
# one heading above one list). This is deliberately a plain enum selector,
# not one of the REQUIRED_DOCUMENT_LETTER_EDITABLE_FIELD_KEYS free-text
# fields below — same "never let a structured selection become free text"
# discipline already applied to the document checkbox selection itself.
VALID_COPY_TYPES = ("Digital", "Hard")


def _find_run_by_text(paragraph, expected_text: str):
    """Returns the first run in `paragraph` whose text matches
    `expected_text` exactly, or raises RequiredDocumentLetterError if the
    template's structure has changed since this module was written — never
    silently fills the wrong run (project rule 9's "never silently
    mis-fill" discipline, matching authorization_letter_engine.py's own
    "assert expected run count first" pattern)."""
    for run in paragraph.runs:
        if run.text == expected_text:
            return run
    raise RequiredDocumentLetterError(
        f"Expected a run with text {expected_text!r} in paragraph {paragraph.text!r}, "
        "but the template's structure has changed. Refusing to guess which run to fill."
    )


def _load_template() -> "docx.document.Document":
    if not os.path.isfile(TEMPLATE_PATH):
        raise RequiredDocumentLetterError(
            f"Reference template not found at {TEMPLATE_PATH}. This engine only ever fills the real, "
            "unmodified reference file — it never fabricates a letter layout."
        )
    return docx.Document(TEMPLATE_PATH)


# Frontend rework, Phase 4 (Word-like body editor extended to the
# Checklist Letter, per the user's own narrower instruction for this one
# document type: "editing only, with all existing design/functionality
# preserved" — the checkbox-driven document SELECTION mechanism and every
# fixed line are untouched; only each real generated-content slot's own
# FINAL WORDING becomes optionally overridable). Every key here maps to
# one real generated slot: five single-paragraph label/value/sentence
# lines, plus "checklistItems" — the one genuinely variable-length slot,
# covering the WHOLE selected-document bullet range as a single Word-like
# multi-line field (never the checkbox selection itself), matching the
# user's own explicit instruction that structured/list content should
# stay editable "in a sensible Word-like way".
REQUIRED_DOCUMENT_LETTER_EDITABLE_FIELD_KEYS = (
    "greetingSentence",
    "countryLine",
    "visaTypeLine",
    "checklistItems",
    "processingTime",
    "visaFees",
)


def _fill_letter(
    country: str,
    visa_type: str,
    employment_status: str,
    document_ids: list,
    bank_statement_duration: str,
    itr_years: str,
    processing_time: str,
    visa_fees: str,
    copy_type: str = "Digital",
    edited_fields: Optional[dict] = None,
    _shader: Optional["docx_utils.ProbeShader"] = None,
) -> "docx.document.Document":
    if not country or not country.strip():
        raise ValueError("Country is required.")
    if visa_type not in VALID_VISA_TYPES:
        raise ValueError(f"Visa type must be one of {VALID_VISA_TYPES}, got {visa_type!r}.")
    if employment_status not in VALID_EMPLOYMENT_STATUSES:
        raise ValueError(f"Employment status must be one of {VALID_EMPLOYMENT_STATUSES}, got {employment_status!r}.")
    if copy_type not in VALID_COPY_TYPES:
        raise ValueError(f"Copy type must be one of {VALID_COPY_TYPES}, got {copy_type!r}.")

    unknown_ids = [d for d in (document_ids or []) if d not in visa_requirements_data.DOCUMENT_CATALOG]
    if unknown_ids:
        # Client-supplied input, not a template/structure integrity failure —
        # ValueError (mapped to HTTP 400 by app.py's _stream_document), same
        # as the country/visa-type/employment-status checks just above.
        # RequiredDocumentLetterError is reserved for cases where the real
        # reference template itself doesn't match what this engine expects.
        raise ValueError(
            f"Unknown document id(s) {unknown_ids!r} — not present in the document catalog. "
            "Refusing to silently drop or guess at an unrecognised selection."
        )

    doc = _load_template()
    paragraphs = doc.paragraphs

    def p(i):
        return paragraphs[i]

    country = country.strip()
    visa_type_text = visa_type.strip()
    edited_fields = edited_fields or {}

    # Frontend rework, Phase 4: every editable slot's own paragraph is
    # captured into a stable Python variable from this ONE untouched
    # `paragraphs` snapshot, before any edit or checklist-rebuild mutation
    # runs — never re-derived by index afterwards. The checklist rebuild
    # just below deletes/clones a variable number of paragraphs, which
    # would silently shift a later paragraphs[N] lookup (processingTime/
    # visaFees sit AFTER it) — the exact hazard already documented for the
    # Authorization Letters and Invitation Letter engines.
    greeting_p = p(6)
    country_p = p(10)
    visa_type_p = p(11)
    documents_required_p = p(13)
    processing_p = p(24)
    fees_p = p(26)

    if _shader is not None:  # layout probe only — see docx_utils.ProbeShader
        _shader.shade("greetingSentence", greeting_p)
        _shader.shade("countryLine", country_p)
        _shader.shade("visaTypeLine", visa_type_p)
        _shader.shade("processingTime", processing_p)
        _shader.shade("visaFees", fees_p)
        # The bullet that every checklist line is cloned from: shading it
        # first gives every line the same probe colour, so the whole
        # checklist reads back as one block.
        _shader.shade("checklistItems", p(15))

    # --- Hard copy / digital copy toggle: one heading, whole list ---
    # Template default is "Documents Required (Digital Copies):" — only
    # swap the word when Hard copies were explicitly requested, leaving the
    # heading's own bold run formatting untouched (single-run paragraph,
    # confirmed by direct inspection).
    if copy_type == "Hard":
        docx_utils.replace_token_in_paragraph(documents_required_p, "Digital Copies", "Hard Copies")

    # --- Greeting / heading paragraphs: bracketed tokens in their own runs ---
    # "Thank you for your inquiry for [Country] [Type of Visa] Visa. "
    greeting_html = edited_fields.get("greetingSentence")
    if greeting_html is not None:
        docx_utils.replace_paragraph_range_with_html(doc, greeting_p, greeting_p, greeting_html)
    else:
        _find_run_by_text(greeting_p, "[Country]").text = country
        _find_run_by_text(greeting_p, "[Type of Visa]").text = visa_type_text

    # "Country: [Country]" — "Country" stays bold (untouched), only the
    # value run's leading-space-plus-bracket text is replaced — unless a
    # staff member's own edit replaces the whole line (which may drop
    # that bold/plain split; that's the intended trade-off of overriding
    # a line's wording, same as every other document type's own edited
    # fields).
    country_html = edited_fields.get("countryLine")
    if country_html is not None:
        docx_utils.replace_paragraph_range_with_html(doc, country_p, country_p, country_html)
    else:
        _find_run_by_text(country_p, " [Country]").text = f" {country}"

    # "Visa Type: [Type of Visa] Visa" — same per-run precision.
    visa_type_html = edited_fields.get("visaTypeLine")
    if visa_type_html is not None:
        docx_utils.replace_paragraph_range_with_html(doc, visa_type_p, visa_type_p, visa_type_html)
    else:
        _find_run_by_text(visa_type_p, "[Type of Visa]").text = visa_type_text

    # --- Document checklist (paras 14-22 in the ORIGINAL template): fully
    # dynamic per the user's own instruction ("checkbox-based, only selected
    # documents appear") rather than the old fixed 9-line list with 4
    # hardcoded conditional bullets. Paragraph 15 ("- Aadhar Card") is a
    # clean single-run bullet line — used as the ONE canonical clone
    # template for every dynamic document line (same "pick one clean
    # existing paragraph as the clone source" precedent already used by
    # authorization_letter_engine.py's own applicant-line cloning), so every
    # inserted line inherits the template's real bullet formatting exactly.
    # Every OTHER original bullet paragraph (14, 16-22) is deleted outright
    # — their fixed wording is fully superseded by the catalog-resolved
    # list built below, selected document-for-document by the caller.
    #
    # "checklistItems" is the one editable field covering this whole
    # variable-length range at once (never the checkbox SELECTION UI
    # itself, which stays exactly as it is — project rule 5 and the
    # user's own "editing only" instruction for this document type): when
    # given, it replaces whatever bullet range would otherwise have been
    # auto-generated, in a single Word-like multi-line block.
    template_bullet_el = p(15)._p
    for idx in (22, 21, 20, 19, 18, 17, 16, 14):  # reverse order: never shifts an earlier index
        docx_utils.delete_paragraph(p(idx))

    resolved_labels = [
        visa_requirements_data.resolve_document_label(doc_id, bank_statement_duration, itr_years)
        for doc_id in visa_requirements_data.DOCUMENT_ORDER
        if doc_id in (document_ids or [])
    ]
    checklist_html = edited_fields.get("checklistItems")
    checklist_paragraphs: list = []

    if resolved_labels:
        clone_els = docx_utils.clone_and_insert_after(template_bullet_el, len(resolved_labels) - 1)
        bullet_els = [template_bullet_el] + clone_els
        if checklist_html is not None:
            first_p, last_p = Paragraph(bullet_els[0], doc), Paragraph(bullet_els[-1], doc)
            docx_utils.replace_paragraph_range_with_html(doc, first_p, last_p, checklist_html)
        else:
            for el, label in zip(bullet_els, resolved_labels):
                docx_utils.set_paragraph_text(Paragraph(el, doc), f"- {label}")
            checklist_paragraphs = [Paragraph(el, doc) for el in bullet_els]
    elif checklist_html is not None:
        # No documents were checkbox-selected, but the staff member wrote
        # their own checklist wording anyway — honour it rather than
        # discarding it just because the auto-generated path would have
        # been empty.
        anchor = Paragraph(template_bullet_el, doc)
        docx_utils.replace_paragraph_range_with_html(doc, anchor, anchor, checklist_html)
    else:
        # No documents selected at all and no edit given — an honest
        # empty checklist (still never a crash), not a fabricated
        # fallback list.
        docx_utils.delete_paragraph(Paragraph(template_bullet_el, doc))

    # --- Processing time / visa fees: literal blanks, own runs ---
    # The template's own fixed wording is "__ Months (Subject to Consulate
    # Approval)" — the blank is followed by a hardcoded unit. A real
    # consulate's processing time is often quoted in weeks or working days,
    # not months, so a caller-supplied value is treated as the FULL phrase
    # (e.g. "2-3 Weeks") and the template's own literal "Months" word is
    # dropped to avoid producing a nonsensical "2-3 Weeks Months" — the
    # explanatory "(Subject to Consulate Approval)" text is always kept.
    # When nothing is supplied, the original template wording (blank + the
    # literal "Months" hint) is left completely untouched, honestly showing
    # staff what still needs to be filled in.
    processing_html = edited_fields.get("processingTime")
    if processing_html is not None:
        docx_utils.replace_paragraph_range_with_html(doc, processing_p, processing_p, processing_html)
    else:
        processing_value = (processing_time or "").strip()
        if processing_value:
            _find_run_by_text(processing_p, "__").text = processing_value
            months_run = _find_run_by_text(processing_p, " Months (Subject to Consulate Approval)")
            months_run.text = " (Subject to Consulate Approval)"

    fees_html = edited_fields.get("visaFees")
    if fees_html is not None:
        docx_utils.replace_paragraph_range_with_html(doc, fees_p, fees_p, fees_html)
    else:
        fees_text = (visa_fees or "").strip() or "_____ "
        if not fees_text.endswith(" "):
            fees_text += " "
        _find_run_by_text(fees_p, "_____ ").text = fees_text

    field_texts = {
        "greetingSentence": greeting_p.text,
        "countryLine": country_p.text,
        "visaTypeLine": visa_type_p.text,
        "checklistItems": "\n".join(cp.text for cp in checklist_paragraphs),
        "processingTime": processing_p.text,
        "visaFees": fees_p.text,
    }
    return doc, field_texts


def _doc_to_bytes(doc) -> bytes:
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def generate_required_document_letter_docx(
    country: str,
    visa_type: str,
    employment_status: str = "Other",
    document_ids: Optional[list] = None,
    bank_statement_duration: str = "",
    itr_years: str = "",
    processing_time: str = "",
    visa_fees: str = "",
    copy_type: str = "Digital",
    edited_fields: Optional[dict] = None,
    _shader: Optional["docx_utils.ProbeShader"] = None,
) -> bytes:
    doc, _field_texts = _fill_letter(
        country, visa_type, employment_status, document_ids or [],
        bank_statement_duration, itr_years, processing_time, visa_fees,
        copy_type=copy_type, edited_fields=edited_fields, _shader=_shader,
    )
    document_blocks.finalize(doc, edited_fields, _shader)
    return _doc_to_bytes(doc)


def generate_required_document_letter_pdf(
    country: str,
    visa_type: str,
    employment_status: str = "Other",
    document_ids: Optional[list] = None,
    bank_statement_duration: str = "",
    itr_years: str = "",
    processing_time: str = "",
    visa_fees: str = "",
    copy_type: str = "Digital",
    edited_fields: Optional[dict] = None,
) -> bytes:
    docx_bytes = generate_required_document_letter_docx(
        country, visa_type, employment_status, document_ids,
        bank_statement_duration, itr_years, processing_time, visa_fees,
        copy_type=copy_type, edited_fields=edited_fields,
    )
    return docx_utils.convert_docx_bytes_to_pdf(docx_bytes, base_name="Required_Document_Letter")


def compose_required_document_letter_editable_fields(
    country: str,
    visa_type: str,
    employment_status: str = "Other",
    document_ids: Optional[list] = None,
    bank_statement_duration: str = "",
    itr_years: str = "",
    processing_time: str = "",
    visa_fees: str = "",
    copy_type: str = "Digital",
) -> dict:
    """Render the same real template with no edits applied, then read back
    each editable field's real generated text, escaped into the seed-HTML
    shape the Word-like body editor expects. Mirrors compose_hotel_fields /
    compose_passport_editable_fields / compose_invitation_editable_fields —
    used purely to seed the editor with the exact wording the real generator
    would otherwise produce (project rule 15: never duplicate wording logic).

    checklistItems is a variable-length, newline-joined string of one bullet
    per line (see field_texts in _fill_letter) — split into one <p> per
    line so the editor shows/edits it as one block of separate lines,
    matching the Hotel Blocking guestNames precedent. When no documents are
    selected the field is seeded as an empty paragraph so the editor still
    mounts (a person may want to type checklist wording in even with none
    ticked yet).
    """
    import html as _html_mod

    _doc, field_texts = _fill_letter(
        country, visa_type, employment_status, document_ids or [],
        bank_statement_duration, itr_years, processing_time, visa_fees,
        copy_type=copy_type, edited_fields=None,
    )

    fields_out = {}
    for key in REQUIRED_DOCUMENT_LETTER_EDITABLE_FIELD_KEYS:
        text = field_texts.get(key, "") or ""
        if key == "checklistItems":
            lines = [line for line in text.split("\n") if line.strip()]
            if lines:
                fields_out[key] = "".join(f"<p>{_html_mod.escape(line)}</p>" for line in lines)
            else:
                fields_out[key] = "<p></p>"
        else:
            fields_out[key] = f"<p>{_html_mod.escape(text)}</p>"
    return fields_out


def compute_required_document_letter_field_layout(
    country: str,
    visa_type: str,
    employment_status: str = "Other",
    document_ids: Optional[list] = None,
    bank_statement_duration: str = "",
    itr_years: str = "",
    processing_time: str = "",
    visa_fees: str = "",
    copy_type: str = "Digital",
    edited_fields: Optional[dict] = None,
) -> dict:
    """Page + rectangle + font of each editable value of the Required
    Document Letter, for the editable preview (see docx_utils.ProbeShader)."""
    shader = docx_utils.ProbeShader()
    probe = generate_required_document_letter_docx(
        country, visa_type, employment_status, document_ids,
        bank_statement_duration, itr_years, processing_time, visa_fees,
        copy_type=copy_type, edited_fields=edited_fields, _shader=shader,
    )
    try:
        pdf = docx_utils.convert_docx_bytes_to_pdf(probe, base_name="Required_Document_Letter_layout")
    except docx_utils.DocxBuildError as e:
        raise RequiredDocumentLetterError(str(e))
    return shader.layout_from_pdf(pdf)
