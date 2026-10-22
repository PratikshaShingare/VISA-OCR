"""
Khanna Travels & Holidays — Invitation Letter + Initors Covering Letter
generators
================================================================

Two related, but structurally distinct, document categories, both housed
here because they're generated from wizard step 7 and both concern the
same real-world scenario found in the reference material: someone already
living abroad ("the inviter") invites family to visit, and — per the
user's own Phase 0 decision — the "Initors" category covers the
**spouse-accompanying** case specifically: two people who are married to
each other, invited together, each submitting their own individual cover
letter.

    reference-templates/Invitors letters/Invitation Letter Template.docx
    reference-templates/Invitors letters/Harsha Covering Letter Template.docx   (written in the WIFE's voice)
    reference-templates/Invitors letters/Sushil Covering Letter Template.docx   (written in the HUSBAND's voice)

Both are genuine blank templates (real `[Bracketed Token]` placeholders
throughout, confirmed by direct inspection before writing any code here —
project rule 5). A companion file, reference-templates/Invitation Letter/
Invitation Letter .docx, is a REAL PAST CLIENT LETTER generated from the
Invitation Letter template (Tanishka Sushil inviting her parents Sushil
Sukumaran and Harsha Sushil to Ireland for her convocation) — useful only
to confirm this engine's output has the right shape; that real family's
name, passport numbers, address and email must never appear in generated
output or be used as sample/default data (project rule 11), and the BLANK
template — not that filled instance — is the actual source this engine
builds from (Document Template Rule, project rule 5).

Two real, documented template quirks, handled the same honest way as
every prior phase's own reference-material surprises (project rule 9 —
never shown to a client, never silently propagated):
  - Both Covering Letter templates' final "Email Id:" line has a stray
    real email address (`harsha_sushil@yahoo.co.in`) glued directly onto
    the front of the line, with no separating space, clearly a leftover
    from when this template was itself cloned from a filled real letter.
    That whole line is composed fresh ("Email Id: <value>") rather than
    token-substituted, so the leftover text can never survive into
    output.
  - Both Covering Letter templates leave TWO blank paragraphs, and the
    Invitation Letter template leaves ONE, between their closing line and
    the printed signer's name — evidently meant for a wet/scanned
    signature. When a real signature image is supplied, it is embedded
    into that first blank paragraph (docx_utils.insert_signature_image);
    when none is supplied, the paragraph is left exactly as blank as the
    template's own original slot — never a fabricated signature.

Every token substitution here is paragraph-scoped
(docx_utils.apply_token_map_to_paragraph), matching the discipline
established in Phase 9's cover_letter_engine.py, even though — unlike
Europe/Japan's cover letters — no genuine same-paragraph or
cross-paragraph token/value collision was actually found in these two
templates on inspection (`[TRAVEL_START_DATE]`/`[TRAVEL_END_DATE]` each
repeat once in the Covering Letter templates, but with the same real
value both times). Paragraph-scoping is kept anyway for consistency and
because it costs nothing and stays defensively correct if the template
file is ever hand-edited later.

Real-person-count limits, each directly justified by what that
template's own FIXED sentences actually say (project rule 9 — never an
invented sentence structure beyond the reference material):
  - Invitation Letter: exactly 2 invitees. The template's subject line
    ("...for my Parents") and closing line ("...kindly grant my parents
    the necessary visa") are FIXED text naming "Parents" specifically,
    and its body has exactly two bracketed invitee blocks
    (PARENT_1_*/PARENT_2_*) — there is no reference example for one
    invitee or for 3+, so this engine does not attempt either.
  - Initors Covering Letter: generated ONE LETTER AT A TIME, for exactly
    one of the two spouses — because each spouse signs and submits their
    OWN letter (confirmed by the two real per-person example files,
    Harsha's and Sushil's, being near-identical apart from whose voice
    it's written in). The template used is chosen by the LETTER'S OWN
    subject's sex (F -> the "My Husband" template, M -> the "My Wife"
    template) — there is no third, gender-neutral template in the real
    material, so a subject whose sex isn't recorded as M or F raises a
    clear error rather than guessing which of the two real templates to
    use.
"""

from __future__ import annotations

import io
import os
from typing import Optional

from docx import Document

import document_blocks
import docx_utils
import letter_shared

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_INVITORS_ROOT = os.path.normpath(os.path.join(_THIS_DIR, "..", "..", "reference-templates", "Invitors letters"))

INVITATION_LETTER_TEMPLATE_PATH = os.path.join(_INVITORS_ROOT, "Invitation Letter Template.docx")
# Covering Letter template chosen by the letter's own subject's sex — see
# module docstring. "Wife" template is written in a wife's voice (refers
# to "My Husband"); "Husband" template is written in a husband's voice
# (refers to "My Wife").
INITORS_WIFE_VOICE_TEMPLATE_PATH = os.path.join(_INVITORS_ROOT, "Harsha Covering Letter Template.docx")
INITORS_HUSBAND_VOICE_TEMPLATE_PATH = os.path.join(_INVITORS_ROOT, "Sushil Covering Letter Template.docx")


class InvitationLetterError(docx_utils.DocxBuildError):
    """Raised whenever an Invitation Letter or Initors Covering Letter
    genuinely cannot be generated — never swallowed to produce a
    fake/empty document (project rule 9)."""


def _load_template(path: str, label: str) -> Document:
    if not os.path.isfile(path):
        raise InvitationLetterError(
            f"{label} reference template not found at {path}. This file is part of the project's "
            "read-only reference material (reference-templates/Invitors letters/) and must already "
            "exist on this machine — it is never created by this app."
        )
    return Document(path)  # only ever read, never written back to


def _phone_or_dash(phone: Optional[str]) -> str:
    digits = letter_shared.local_phone_digits(phone)
    return f"+91 {digits}" if digits else "—"


# ---------------------------------------------------------------------------
# Invitation Letter
# ---------------------------------------------------------------------------


def _invitation_token_maps(inviter: dict, invitees: list[dict], fields: dict, date_override: Optional[str]) -> dict:
    """The Invitation Letter's own token substitutions, keyed by the SAME
    editable-field key every one of the letter's real generated content
    slots is known by (see INVITATION_EDITABLE_FIELD_KEYS below) — one
    shared source for the real generator's non-edited fallback AND the
    Word-like editor's seed values (project rule 15), so neither can ever
    drift from the other."""
    p1, p2 = invitees[0], invitees[1]
    return {
        "date": {"[DATE]": letter_shared.format_letter_date(date_override)},
        "inviterNameLine": {"[INVITER_FULL_NAME]": inviter.get("fullName") or "—"},
        "inviterAddressLine1": {"[INVITER_ADDRESS_LINE_1]": inviter.get("addressLine1") or "—"},
        "inviterAddressLine2": {"[INVITER_ADDRESS_LINE_2]": inviter.get("addressLine2") or "—"},
        "inviterCityPostcode": {"[CITY, POSTCODE]": inviter.get("cityPostcode") or "—"},
        "inviterCountry": {"[COUNTRY]": inviter.get("country") or "—"},
        "inviterCityCountry": {"[CITY, COUNTRY]": inviter.get("cityCountry") or "—"},
        "inviterDetails": {
            "[INVITER_FULL_NAME]": inviter.get("fullName") or "—",
            "[INVITER_PASSPORT_NUMBER]": inviter.get("passportNumber") or "—",
            "[INVITER_FULL_ADDRESS]": inviter.get("fullAddress") or "—",
            "[STUDYING / WORKING]": inviter.get("studyingOrWorking") or "—",
            "[UNIVERSITY / COMPANY NAME]": inviter.get("universityOrCompany") or "—",
        },
        "inviteesDetails": {
            "[PARENT_1_FULL_NAME]": p1.get("fullName") or "—",
            "[PARENT_1_PASSPORT_NUMBER]": p1.get("passportNumber") or "—",
            "[PARENT_1_PLACE_OF_ISSUE]": p1.get("placeOfIssue") or "—",
            "[PARENT_1_DATE_OF_ISSUE]": p1.get("passportIssueDate") or "—",
            "[PARENT_2_FULL_NAME]": p2.get("fullName") or "—",
            "[PARENT_2_PASSPORT_NUMBER]": p2.get("passportNumber") or "—",
            "[PARENT_2_PLACE_OF_ISSUE]": p2.get("placeOfIssue") or "—",
            "[PARENT_2_DATE_OF_ISSUE]": p2.get("passportIssueDate") or "—",
            "[TRAVEL_START_DATE]": fields.get("travelStartDate") or "—",
            "[TRAVEL_END_DATE]": fields.get("travelEndDate") or "—",
            "[PURPOSE OF VISIT]": fields.get("purpose") or "—",
        },
        "purposeStatement": {"[PURPOSE OF VISIT]": fields.get("purpose") or "—"},
        "accommodationAndReturn": {
            "[ACCOMMODATION DETAILS]": fields.get("accommodationDetails") or "—",
            "[RETURN_DATE]": fields.get("returnDate") or "—",
        },
        "fundingArrangement": {"[SPONSOR / PARENTS / APPLICANT]": fields.get("fundingArrangement") or "—"},
        "signOffName": {"[INVITER_FULL_NAME]": inviter.get("fullName") or "—"},
        "phone": {"[PHONE_NUMBER]": _phone_or_dash(inviter.get("phone"))},
        "email": {"[EMAIL_ADDRESS]": (inviter.get("email") or "").strip() or "—"},
    }


# Frontend rework, Phase 4 (Word-like body editor extended to the
# Invitation Letter): every one of this letter's real generated-content
# paragraphs (never the entirely-fixed "From,"/"To,"/"Subject:"/
# "Respected Sir/Madam,"/"Thank you!"/"Yours Sincerely," lines, and never
# the blank signature slot) gets its own editable field, keyed here and
# mapped to the template's own real paragraph index — see module
# docstring's paragraph dump for exactly which paragraph each key is.
INVITATION_EDITABLE_FIELD_KEYS = (
    "date",
    "inviterNameLine",
    "inviterAddressLine1",
    "inviterAddressLine2",
    "inviterCityPostcode",
    "inviterCountry",
    "inviterCityCountry",
    "inviterDetails",
    "inviteesDetails",
    "purposeStatement",
    "accommodationAndReturn",
    "fundingArrangement",
    "signOffName",
    "phone",
    "email",
)
_INVITATION_FIELD_PARAGRAPH_INDEX = {
    "date": 0,
    "inviterNameLine": 2,
    "inviterAddressLine1": 3,
    "inviterAddressLine2": 4,
    "inviterCityPostcode": 5,
    "inviterCountry": 8,
    "inviterCityCountry": 9,
    "inviterDetails": 12,
    "inviteesDetails": 13,
    "purposeStatement": 14,
    "accommodationAndReturn": 15,
    "fundingArrangement": 16,
    "signOffName": 21,
    "phone": 22,
    "email": 23,
}


def compose_invitation_editable_fields(inviter: dict, invitees: list[dict], fields: dict, date_override: Optional[str] = None) -> dict:
    """The Word-like body editor's seed values for the Invitation Letter —
    one real, fully-rendered {fieldKey: html} entry per editable
    paragraph (see INVITATION_EDITABLE_FIELD_KEYS), computed from the
    SAME token maps `generate_invitation_letter_docx`'s own non-edited
    fallback uses (project rule 15 — never a second, hand-guessed copy
    of this wording)."""
    import html as _html_mod

    if len(invitees) != 2:
        raise ValueError(
            "The Invitation Letter is written for exactly two invitees (matching the reference "
            f"template's own fixed 'my Parents' wording) — {len(invitees)} were given."
        )
    document = _load_template(INVITATION_LETTER_TEMPLATE_PATH, "Invitation Letter")
    paragraphs = document.paragraphs
    token_maps = _invitation_token_maps(inviter, invitees, fields, date_override)
    fields_out = {}
    for key in INVITATION_EDITABLE_FIELD_KEYS:
        p = paragraphs[_INVITATION_FIELD_PARAGRAPH_INDEX[key]]
        docx_utils.apply_token_map_to_paragraph(p, token_maps[key])
        fields_out[key] = f"<p>{_html_mod.escape(p.text)}</p>"
    return fields_out


def generate_invitation_letter_docx(
    inviter: dict,
    invitees: list[dict],
    fields: dict,
    signature_bytes: Optional[bytes] = None,
    date_override: Optional[str] = None,
    edited_fields: Optional[dict] = None,
    _shader: Optional["docx_utils.ProbeShader"] = None,
) -> bytes:
    """`inviter`: {fullName, addressLine1, addressLine2, cityPostcode,
    country, cityCountry, passportNumber, fullAddress, studyingOrWorking,
    universityOrCompany, phone, email} — a person living abroad, entered
    freely (they are not one of this application's own travellers, since
    Khanna isn't processing their visa). `invitees`: exactly 2 of this
    application's own people (each {fullName, passportNumber,
    placeOfIssue, passportIssueDate}) — the two being invited. `fields`:
    {travelStartDate, travelEndDate, purpose, accommodationDetails,
    returnDate, fundingArrangement}. `edited_fields`: a {fieldKey: html}
    map (see INVITATION_EDITABLE_FIELD_KEYS/compose_invitation_editable_fields
    for the key set) — a staff member's own Word-like edits, applied
    instead of the auto-generated token substitution for exactly the
    fields present; None/absent means "auto-generate every field as
    normal", same contract as every other document type's edited_fields.

    Frontend rework, Phase 4: every editable paragraph — AND the blank
    signature-slot paragraph, which sits between them (index 20) — is
    captured into a stable Python variable from ONE untouched
    `document.paragraphs` snapshot taken before any edit runs, never
    re-derived by index afterwards. This matters here specifically
    because an edited field's docx_utils.replace_paragraph_range_with_html
    call can change the document's total paragraph count (a multi-line
    edit doesn't have to stay one paragraph), which would silently shift
    every later paragraph's real index if any were looked up fresh after
    an earlier one was mutated — the exact hazard already documented for
    the Authorization Letters engine."""
    if len(invitees) != 2:
        raise ValueError(
            "The Invitation Letter is written for exactly two invitees (matching the reference "
            f"template's own fixed 'my Parents' wording) — {len(invitees)} were given."
        )
    if not inviter or not (inviter.get("fullName") or "").strip():
        raise ValueError("The inviter's own name is required to generate this letter.")

    document = _load_template(INVITATION_LETTER_TEMPLATE_PATH, "Invitation Letter")
    paragraphs = document.paragraphs
    token_maps = _invitation_token_maps(inviter, invitees, fields, date_override)
    edited_fields = edited_fields or {}

    field_paragraphs = {key: paragraphs[idx] for key, idx in _INVITATION_FIELD_PARAGRAPH_INDEX.items()}
    signature_paragraph = paragraphs[20]

    if _shader is not None:  # layout probe only — see docx_utils.ProbeShader
        for key in INVITATION_EDITABLE_FIELD_KEYS:
            _shader.shade(key, field_paragraphs[key])

    for key in INVITATION_EDITABLE_FIELD_KEYS:
        p = field_paragraphs[key]
        html = edited_fields.get(key)
        if html is not None:
            docx_utils.replace_paragraph_range_with_html(document, p, p, html)
        else:
            docx_utils.apply_token_map_to_paragraph(p, token_maps[key])

    if signature_bytes:
        docx_utils.insert_signature_image(signature_paragraph, signature_bytes)

    document_blocks.finalize(document, edited_fields, _shader)
    buf = io.BytesIO()
    document.save(buf)
    return buf.getvalue()


def generate_invitation_letter_pdf(
    inviter: dict,
    invitees: list[dict],
    fields: dict,
    signature_bytes: Optional[bytes] = None,
    date_override: Optional[str] = None,
    edited_fields: Optional[dict] = None,
) -> bytes:
    docx_bytes = generate_invitation_letter_docx(inviter, invitees, fields, signature_bytes, date_override, edited_fields)
    try:
        return docx_utils.convert_docx_bytes_to_pdf(docx_bytes, base_name="invitation_letter")
    except docx_utils.DocxBuildError as e:
        raise InvitationLetterError(str(e))


def compute_invitation_field_layout(
    inviter: dict,
    invitees: list[dict],
    fields: dict,
    signature_bytes: Optional[bytes] = None,
    date_override: Optional[str] = None,
    edited_fields: Optional[dict] = None,
) -> dict:
    """Page + rectangle + font of each editable value of the Invitation
    Letter, for the editable preview (see docx_utils.ProbeShader)."""
    shader = docx_utils.ProbeShader()
    probe = generate_invitation_letter_docx(
        inviter, invitees, fields, signature_bytes, date_override, edited_fields, _shader=shader
    )
    try:
        pdf = docx_utils.convert_docx_bytes_to_pdf(probe, base_name="invitation_letter_layout")
    except docx_utils.DocxBuildError as e:
        raise InvitationLetterError(str(e))
    return shader.layout_from_pdf(pdf)


# ---------------------------------------------------------------------------
# Initors Covering Letter (Spouse-Accompanying Cover Letter)
# ---------------------------------------------------------------------------


def _initors_template_path_for_sex(sex: Optional[str]) -> str:
    normalized = (sex or "").strip().upper()
    if normalized == "F":
        return INITORS_WIFE_VOICE_TEMPLATE_PATH
    if normalized == "M":
        return INITORS_HUSBAND_VOICE_TEMPLATE_PATH
    raise ValueError(
        "The Initors Covering Letter is written in a real gendered voice — 'My Husband' (wife's own "
        "letter) or 'My Wife' (husband's own letter) — matching the two real reference templates on "
        "file. The letter's subject needs sex recorded as Male or Female to pick the right one; no "
        "third, gender-neutral template exists to fall back to."
    )


def generate_initors_covering_letter_docx(
    subject: dict,
    spouse: dict,
    inviting_person: dict,
    fields: dict,
    signature_bytes: Optional[bytes] = None,
    date_override: Optional[str] = None,
    edited_fields: Optional[dict] = None,
    _shader: Optional["docx_utils.ProbeShader"] = None,
) -> bytes:
    """`subject`: the person THIS letter is for/signed by — {fullName,
    passportNumber, placeOfIssue, passportIssueDate, sex, phone, email,
    occupation, relationWithInvitingPerson}. `spouse`: the accompanying
    husband/wife — {fullName, passportNumber, placeOfIssue,
    passportIssueDate, occupation}. `inviting_person`: the person abroad
    they're visiting — {fullName, passportNumber, countryOfResidence,
    visaResidenceStatus}. `fields`: {country, purpose, travelStartDate,
    travelEndDate, returnDate, accommodationDetails, otherCommitments,
    invitationSupportingDocuments}."""
    if not subject or not (subject.get("fullName") or "").strip():
        raise ValueError("The letter's own subject (the person signing it) is required.")
    if not spouse or not (spouse.get("fullName") or "").strip():
        raise ValueError(
            "The Initors Covering Letter is written for a traveller accompanied by their spouse — "
            "the accompanying spouse's details are required too."
        )

    template_path = _initors_template_path_for_sex(subject.get("sex"))
    document = _load_template(template_path, "Initors Covering Letter")
    paragraphs = document.paragraphs

    docx_utils.apply_token_map_to_paragraph(paragraphs[0], {"[DATE]": letter_shared.format_letter_date(date_override)})
    docx_utils.apply_token_map_to_paragraph(paragraphs[3], {"[COUNTRY]": fields.get("country") or "—"})
    docx_utils.apply_token_map_to_paragraph(paragraphs[4], {"[CITY, COUNTRY]": fields.get("country") or "—"})

    docx_utils.apply_token_map_to_paragraph(
        paragraphs[9],
        {
            "[APPLICANT_NAME]": subject.get("fullName") or "—",
            "[APPLICANT_PASSPORT_NUMBER]": subject.get("passportNumber") or "—",
            "[PLACE_OF_ISSUE]": subject.get("placeOfIssue") or "—",
            "[DATE_OF_ISSUE]": subject.get("passportIssueDate") or "—",
            "[TRAVEL_START_DATE]": fields.get("travelStartDate") or "—",
            "[TRAVEL_END_DATE]": fields.get("travelEndDate") or "—",
            "[RELATION_WITH_INVITING_PERSON]": subject.get("relationWithInvitingPerson") or "—",
        },
    )
    docx_utils.apply_token_map_to_paragraph(
        paragraphs[11],
        {
            "[OCCUPATION / BUSINESS DETAILS]": subject.get("occupation") or "—",
            "[SPOUSE_NAME]": spouse.get("fullName") or "—",
            "[SPOUSE_PASSPORT_NUMBER]": spouse.get("passportNumber") or "—",
            "[SPOUSE_PLACE_OF_ISSUE]": spouse.get("placeOfIssue") or "—",
            "[SPOUSE_DATE_OF_ISSUE]": spouse.get("passportIssueDate") or "—",
            "[SPOUSE_OCCUPATION / BUSINESS DETAILS]": spouse.get("occupation") or "—",
        },
    )
    docx_utils.apply_token_map_to_paragraph(
        paragraphs[13],
        {
            "[COUNTRY]": fields.get("country") or "—",
            "[PURPOSE OF VISIT]": fields.get("purpose") or "—",
            "[INVITING_PERSON_NAME]": inviting_person.get("fullName") or "—",
            "[INVITING_PERSON_PASSPORT_NUMBER]": inviting_person.get("passportNumber") or "—",
            "[COUNTRY_OF_RESIDENCE]": inviting_person.get("countryOfResidence") or "—",
            "[VISA / RESIDENCE STATUS]": inviting_person.get("visaResidenceStatus") or "—",
        },
    )
    docx_utils.apply_token_map_to_paragraph(
        paragraphs[15],
        {
            "[ACCOMMODATION DETAILS]": fields.get("accommodationDetails") or "—",
            "[TRAVEL_START_DATE]": fields.get("travelStartDate") or "—",
            "[TRAVEL_END_DATE]": fields.get("travelEndDate") or "—",
            "[RETURN_DATE]": fields.get("returnDate") or "—",
            "[BUSINESS / EMPLOYMENT / OTHER COMMITMENTS]": fields.get("otherCommitments") or "—",
        },
    )
    # Paragraph 18's "borne equally by me and my husband/wife" sentence is
    # entirely FIXED text in both real templates — no token in it, so it is
    # deliberately left completely untouched here (Document Template Rule).
    docx_utils.apply_token_map_to_paragraph(
        paragraphs[20],
        {"[INVITATION / SUPPORTING DOCUMENTS]": fields.get("invitationSupportingDocuments") or "—"},
    )
    # Paragraph 24 ("Thanking you...\n\nYours Faithfully,") is entirely
    # fixed text too (a real <w:br/> line break inside one run) — left
    # untouched.

    docx_utils.apply_token_map_to_paragraph(paragraphs[27], {"[APPLICANT_FULL_NAME]": subject.get("fullName") or "—"})
    docx_utils.apply_token_map_to_paragraph(paragraphs[28], {"[CONTACT_NUMBER]": _phone_or_dash(subject.get("phone"))})
    # Paragraph 29 in BOTH real reference templates carries a stray real
    # mailto: hyperlink ("harsha_sushil@yahoo.co.in") sitting in front of
    # the "Email Id: [EMAIL_ADDRESS]" run — leftover cruft from when the
    # template was itself cloned from a filled real letter. Confirmed by
    # direct XML inspection during testing: paragraph.runs (what
    # set_paragraph_text/apply_token_map_to_paragraph operate on) does NOT
    # include that hyperlink's run at all, so composing the visible text
    # alone is not enough — the real hyperlink survives untouched unless
    # explicitly removed first. Stripped before composing the line fresh,
    # so the real leftover email can never survive into generated output
    # either as visible text or as a hidden link target (project rules 9
    # and 11).
    docx_utils.remove_hyperlinks_in_paragraph(paragraphs[29])
    docx_utils.set_paragraph_text(
        paragraphs[29], f"Email Id: {(subject.get('email') or '').strip() or '—'}"
    )

    if signature_bytes:
        docx_utils.insert_signature_image(paragraphs[25], signature_bytes)

    document_blocks.finalize(document, edited_fields, _shader)
    buf = io.BytesIO()
    document.save(buf)
    return buf.getvalue()


def generate_initors_covering_letter_pdf(
    subject: dict,
    spouse: dict,
    inviting_person: dict,
    fields: dict,
    signature_bytes: Optional[bytes] = None,
    date_override: Optional[str] = None,
    edited_fields: Optional[dict] = None,
) -> bytes:
    docx_bytes = generate_initors_covering_letter_docx(
        subject, spouse, inviting_person, fields, signature_bytes, date_override, edited_fields
    )
    try:
        return docx_utils.convert_docx_bytes_to_pdf(docx_bytes, base_name="initors_covering_letter")
    except docx_utils.DocxBuildError as e:
        raise InvitationLetterError(str(e))


def compute_initors_field_layout(
    subject: dict,
    spouse: dict,
    inviting_person: dict,
    fields: dict,
    signature_bytes: Optional[bytes] = None,
    date_override: Optional[str] = None,
    edited_fields: Optional[dict] = None,
) -> dict:
    """Where every block of the Initors Covering Letter sits on the page of
    the real PDF, for the editable preview (see document_blocks)."""
    shader = docx_utils.ProbeShader()
    probe = generate_initors_covering_letter_docx(
        subject, spouse, inviting_person, fields, signature_bytes, date_override, edited_fields, _shader=shader
    )
    try:
        pdf = docx_utils.convert_docx_bytes_to_pdf(probe, base_name="initors_covering_letter_layout")
    except docx_utils.DocxBuildError as e:
        raise InvitationLetterError(str(e))
    return shader.layout_from_pdf(pdf)
