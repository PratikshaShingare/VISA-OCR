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
every prior engine's own discipline): the template is a genuine blank
template — no letterhead/footer (confirmed against Phase 0's own finding
that only the Company Authorization Letter and Hotel Voucher templates
carry the khannatravels.com letterhead), 35 paragraphs, 0 tables. Its
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


def _fill_letter(
    country: str,
    visa_type: str,
    employment_status: str,
    document_ids: list,
    bank_statement_duration: str,
    itr_years: str,
    processing_time: str,
    visa_fees: str,
) -> "docx.document.Document":
    if not country or not country.strip():
        raise ValueError("Country is required.")
    if visa_type not in VALID_VISA_TYPES:
        raise ValueError(f"Visa type must be one of {VALID_VISA_TYPES}, got {visa_type!r}.")
    if employment_status not in VALID_EMPLOYMENT_STATUSES:
        raise ValueError(f"Employment status must be one of {VALID_EMPLOYMENT_STATUSES}, got {employment_status!r}.")

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

    # --- Greeting / heading paragraphs: bracketed tokens in their own runs ---
    # "Thank you for your inquiry for [Country] [Type of Visa] Visa. "
    _find_run_by_text(p(6), "[Country]").text = country
    _find_run_by_text(p(6), "[Type of Visa]").text = visa_type_text

    # "Country: [Country]" — "Country" stays bold (untouched), only the
    # value run's leading-space-plus-bracket text is replaced.
    _find_run_by_text(p(10), " [Country]").text = f" {country}"

    # "Visa Type: [Type of Visa] Visa" — same per-run precision.
    _find_run_by_text(p(11), "[Type of Visa]").text = visa_type_text

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
    template_bullet_el = p(15)._p
    for idx in (22, 21, 20, 19, 18, 17, 16, 14):  # reverse order: never shifts an earlier index
        docx_utils.delete_paragraph(p(idx))

    resolved_labels = [
        visa_requirements_data.resolve_document_label(doc_id, bank_statement_duration, itr_years)
        for doc_id in visa_requirements_data.DOCUMENT_ORDER
        if doc_id in (document_ids or [])
    ]

    if resolved_labels:
        clone_els = docx_utils.clone_and_insert_after(template_bullet_el, len(resolved_labels) - 1)
        bullet_els = [template_bullet_el] + clone_els
        for el, label in zip(bullet_els, resolved_labels):
            docx_utils.set_paragraph_text(Paragraph(el, doc), f"- {label}")
    else:
        # No documents selected at all — an honest empty checklist (still
        # never a crash), not a fabricated fallback list.
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
    processing_value = (processing_time or "").strip()
    if processing_value:
        _find_run_by_text(p(24), "__").text = processing_value
        months_run = _find_run_by_text(p(24), " Months (Subject to Consulate Approval)")
        months_run.text = " (Subject to Consulate Approval)"

    fees_text = (visa_fees or "").strip() or "_____ "
    if not fees_text.endswith(" "):
        fees_text += " "
    _find_run_by_text(p(26), "_____ ").text = fees_text

    return doc


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
) -> bytes:
    doc = _fill_letter(
        country, visa_type, employment_status, document_ids or [],
        bank_statement_duration, itr_years, processing_time, visa_fees,
    )
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
) -> bytes:
    docx_bytes = generate_required_document_letter_docx(
        country, visa_type, employment_status, document_ids,
        bank_statement_duration, itr_years, processing_time, visa_fees,
    )
    return docx_utils.convert_docx_bytes_to_pdf(docx_bytes, base_name="Required_Document_Letter")
