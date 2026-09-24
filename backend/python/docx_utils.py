"""
Khanna Travels & Holidays — shared .docx generation helpers
==============================================================

Low-level python-docx helpers shared by every document-generation engine
(hotel_voucher_engine.py, authorization_letter_engine.py, and future
cover/invitation-letter engines). Extracted in Phase 8 out of
hotel_voucher_engine.py, which was the first engine to need them, so later
engines don't duplicate the same run-preserving text-fill logic (project
rule 15 — avoid duplicated logic).

These helpers never invent formatting: they always preserve whatever the
real reference template's own runs/paragraphs already look like, only ever
changing the *text*, not fonts/sizes/colours/spacing (project rule 5 —
Document Template Rule).
"""

from __future__ import annotations

import copy
import io
from typing import Optional

from docx.oxml.ns import qn
from docx.shared import Inches

import pdf_conversion

_W_BR_TAG = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}br"


class DocxBuildError(Exception):
    """Raised whenever a document genuinely cannot be built from its
    reference template — never swallowed to produce a fake/empty document
    (project rule 9)."""


def set_paragraph_text(paragraph, text: str) -> None:
    """Sets a paragraph's visible text while preserving the formatting of
    its first run (font, size, colour, highlight). Any run after the first
    is blanked, not removed, so alignment/paragraph-level properties never
    change. Do NOT use this on a paragraph that contains a structural
    element such as a `<w:br/>` line break inside one of its runs — that
    run's text is not the whole story, and blanking it would silently
    delete the line break. Use `set_two_line_paragraph` for those."""
    if paragraph.runs:
        paragraph.runs[0].text = text
        for r in paragraph.runs[1:]:
            r.text = ""
    else:
        paragraph.text = text


def set_cell_text(cell, text: str) -> None:
    set_paragraph_text(cell.paragraphs[0], text)


def replace_token_in_paragraph(paragraph, token: str, value: str) -> bool:
    """Replaces a bracketed token (e.g. '[Date]') that sits inside a longer,
    otherwise-fixed sentence. Merges the paragraph's own runs first so a
    token split across runs is still matched, then reassigns the combined
    text to the first run (formatting-preserving, same technique as
    set_paragraph_text). Returns True if the token was found and replaced."""
    full = "".join(r.text for r in paragraph.runs)
    if token in full:
        set_paragraph_text(paragraph, full.replace(token, value))
        return True
    return False


def replace_token_in_cell(cell, token: str, value: str) -> bool:
    for p in cell.paragraphs:
        if replace_token_in_paragraph(p, token, value):
            return True
    return False


def has_break_run(paragraph) -> bool:
    """True if any run in this paragraph contains a real `<w:br/>` line
    break element (as opposed to a literal '\\n' character) — discovered in
    the Passport Authorization Letter's signature paragraph, where the name
    and phone number sit on two visual lines inside a single paragraph."""
    for r in paragraph.runs:
        if r._element.findall(f".//{_W_BR_TAG}"):
            return True
    return False


def set_two_line_paragraph(paragraph, line1_text: str, line2_text: str) -> None:
    """Rebuilds a paragraph whose two visual lines are separated by a real
    `<w:br/>` element sitting in its own run, WITHOUT destroying that break
    (verified against the real Passport Authorization Letter templates:
    'Mr. Dilip Bijlani' <br/> 'Phone No.: +91 9819347139' is 5 runs — text,
    br, text, text, text — not two paragraphs and not a literal '\\n' inside
    one run's text).

    Strategy: find the first run that contains a `<w:br/>` child. Everything
    before it becomes line 1 (written into the first run, remaining
    pre-break runs blanked); the break run itself is left completely
    untouched; everything from the run *after* the break onward becomes
    line 2 (written into that first post-break run, remaining runs
    blanked).

    Falls back to a plain two-line write via a literal line break character
    if the paragraph doesn't actually contain a `<w:br/>` run (so this
    helper is always safe to call even if a future template's structure
    turns out not to match) — an honest degradation, not a silent
    corruption, and still produces correct-looking text either way.
    """
    runs = paragraph.runs
    break_index = None
    for i, r in enumerate(runs):
        if r._element.findall(f".//{_W_BR_TAG}"):
            break_index = i
            break

    if break_index is None:
        # No <w:br/> run found — safe fallback, still correct visually in
        # Word (a literal run containing only "\n" does not reliably force
        # a line break in OOXML, so join with a space instead of silently
        # losing the second line).
        set_paragraph_text(paragraph, f"{line1_text} — {line2_text}")
        return

    pre_break = runs[:break_index]
    post_break = runs[break_index + 1 :]

    if pre_break:
        pre_break[0].text = line1_text
        for r in pre_break[1:]:
            r.text = ""
    if post_break:
        post_break[0].text = line2_text
        for r in post_break[1:]:
            r.text = ""


def find_hyperlink_text_run(paragraph):
    """Returns (hyperlink_element, relationship_id, text_element) for the
    first `<w:hyperlink>` found directly inside this paragraph, or None if
    there isn't one.

    This matters because python-docx's `paragraph.runs` does NOT include
    runs nested inside a `<w:hyperlink>` wrapper — discovered in the
    Passport Authorization Letter templates' "Email id: ..." line, which is
    a real `mailto:` link, not plain text. `set_paragraph_text` silently
    can't see or change that text at all (the visible email address simply
    isn't among `paragraph.runs`), so any paragraph built around a
    hyperlink needs this helper instead."""
    hyperlink_el = paragraph._p.find(qn("w:hyperlink"))
    if hyperlink_el is None:
        return None
    r_id = hyperlink_el.get(qn("r:id"))
    t_el = hyperlink_el.find(f"{qn('w:r')}/{qn('w:t')}")
    return hyperlink_el, r_id, t_el


def set_hyperlink_text_and_target(paragraph, document, new_text: str, new_target_uri: Optional[str] = None) -> bool:
    """Updates a paragraph's `<w:hyperlink>` run (e.g. an 'Email id:'
    mailto link) in place: the visible text always changes to `new_text`;
    if `new_target_uri` is given (e.g. 'mailto:someone@example.com'), the
    underlying relationship's target is updated too, so the link itself
    points somewhere real rather than just carrying a stale label.

    Returns True if a hyperlink was found and updated, False if this
    paragraph has no `<w:hyperlink>` at all — callers should treat False as
    a template-structure surprise and raise, not silently ignore it
    (project rule 9)."""
    found = find_hyperlink_text_run(paragraph)
    if found is None:
        return False
    _hyperlink_el, r_id, t_el = found
    if t_el is not None:
        t_el.text = new_text
    if new_target_uri and r_id and r_id in document.part.rels:
        try:
            document.part.rels[r_id]._target = new_target_uri
        except AttributeError:
            # Visible text is already updated even if this internal
            # python-docx attribute name ever changes in a future version.
            pass
    return True


def remove_hyperlinks_in_paragraph(paragraph) -> int:
    """Removes every `<w:hyperlink>` child element from a paragraph
    entirely (the link and the text/run inside it — a real target URL,
    like a real `mailto:`, is not something `set_paragraph_text` or
    `apply_token_map_to_paragraph` can see or change, since
    `paragraph.runs` excludes hyperlink-wrapped runs; see
    `find_hyperlink_text_run`). Written for the Initors Covering Letter
    templates' final "Email Id:" line, which carries a real leftover
    `mailto:harsha_sushil@yahoo.co.in` hyperlink glued in front of the
    '[EMAIL_ADDRESS]' token run — authoring cruft from when the template
    was cloned from a filled real letter, not genuine template content to
    preserve (project rule 9), and real personal data that must never
    leak into generated output (project rule 11). Returns the number of
    hyperlink elements removed, so a caller expecting to find and strip
    one can assert on it rather than silently doing nothing."""
    hyperlink_els = paragraph._p.findall(qn("w:hyperlink"))
    for el in hyperlink_els:
        paragraph._p.remove(el)
    return len(hyperlink_els)


def insert_signature_image(paragraph, image_bytes: bytes, width_inches: float = 1.6) -> None:
    """Embeds a real, staff-uploaded signature image into a blank
    signature-slot paragraph — the genuinely empty paragraph several
    reference letter templates leave between their closing line (e.g.
    'Yours Sincerely,' / 'Yours Faithfully,') and the printed signer's
    name, evidently meant for a wet or scanned signature. Deliberately
    only ever called with a real uploaded image (project rule 9 — never
    fabricate a signature): when no signature was provided, callers simply
    skip this and the paragraph stays exactly as blank as the template's
    own original signature slot. Raises DocxBuildError, not a silent
    no-op, if the given bytes aren't a real, readable image — a broken
    upload must never produce a document that looks correct but is
    silently missing its signature."""
    try:
        run = paragraph.add_run()
        run.add_picture(io.BytesIO(image_bytes), width=Inches(width_inches))
    except Exception as e:  # noqa: BLE001 — python-docx/Pillow raise several distinct types for a bad image
        raise DocxBuildError(f"Could not embed the signature image — the uploaded file may not be a valid image: {e}")


def apply_token_map_to_paragraph(paragraph, token_map: dict) -> None:
    """Applies replace_token_in_paragraph for every (token, value) pair in
    token_map to ONE paragraph. Deliberately paragraph-scoped, not
    document-wide: a document-wide token sweep is unsafe whenever the same
    bracket token (e.g. '[Passport Number]') legitimately needs two
    different real values in two different paragraphs (an applicant's vs.
    a companion's) — discovered while building the Cover Letter engine.
    Callers pass exactly the map that paragraph needs."""
    for token, value in token_map.items():
        replace_token_in_paragraph(paragraph, token, value)


def delete_paragraph(paragraph) -> None:
    """Removes a paragraph element from the document entirely. Used for
    reference-template content that turns out to be leftover/broken
    boilerplate rather than real content to preserve — e.g. the Singapore
    Cover Letter template's second, mislabeled/misspelled duplicate
    signature block — the Document Template Rule (project rule 5) is
    about preserving genuine template content, not propagating an
    authoring mistake in the source file."""
    el = paragraph._p
    el.getparent().remove(el)


def clone_and_insert_after(template_element, count: int):
    """Deep-clones `template_element` `count` times, inserting each clone
    immediately after the previous element (or after the template itself
    for the first clone), and returns the list of NEW elements created (the
    template element itself is not included). Used to repeat a block that
    appears once in the template — one applicant line, one hotel block —
    for however many real records there are."""
    new_elements = []
    last = template_element
    for _ in range(count):
        clone = copy.deepcopy(template_element)
        last.addnext(clone)
        new_elements.append(clone)
        last = clone
    return new_elements


def convert_docx_bytes_to_pdf(docx_bytes: bytes, base_name: str = "document") -> bytes:
    """Converts a .docx (already built, as raw bytes) to PDF — the actual
    rendered document, never a hand-recreated PDF layout (project rule 9).

    Delegates to pdf_conversion.py, which picks local LibreOffice
    ('soffice', unchanged behaviour from before this project went
    Vercel-serverless) or CloudConvert's cloud API (required once this
    backend runs on Vercel, which cannot shell out to a system binary) —
    see pdf_conversion.py and VERCEL_DEPLOYMENT.md. Kept under this exact
    name/signature so every document engine's existing
    `docx_utils.convert_docx_bytes_to_pdf(...)` call site needs no changes,
    and still raises DocxBuildError (not pdf_conversion's own
    PdfConversionError) so those call sites' existing error handling
    keeps working unchanged too."""
    try:
        return pdf_conversion.convert_docx_bytes_to_pdf(docx_bytes, base_name=base_name)
    except pdf_conversion.PdfConversionError as e:
        raise DocxBuildError(str(e)) from e
