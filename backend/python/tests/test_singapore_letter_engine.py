"""
Tests for singapore_letter_engine.py — Singapore's own two cover letters and
two authorization letters, generated from the clean reference templates in
reference-templates/Singapore/ (project rule 5). All people, passports and
contact details below are obviously synthetic (project rule 11).
"""

import io

import pytest
from docx import Document

import singapore_letter_engine as sg
from conftest import skip_if_missing, skip_if_missing_binary

APPLICANT = {
    "id": "a", "salutation": "Mr", "fullName": "Test Applicant", "passportNumber": "X1234567",
    "placeOfIssue": "Mumbai", "passportIssueDate": "2020-01-05", "phone": "9876543210",
    "email": "test@example.com", "isApplicant": True,
}
WIFE = {"id": "b", "salutation": "Mrs", "fullName": "Test Spouse", "passportNumber": "Y7654321",
        "relationToApplicant": "Spouse", "sex": "F"}
SON = {"id": "c", "salutation": "Mstr", "fullName": "Test Child", "passportNumber": "Z1111111",
       "relationToApplicant": "Child", "sex": "M"}
FIELDS = {
    "travelStartDate": "2026-09-21", "travelEndDate": "2026-09-26", "hotelName": "Test Hotel",
    "hotelAddress": "1 Test Road, Singapore 000000", "fundingArrangement": "myself",
    "occupations": {"a": "a student at Test College", "b": "Homemaker", "c": "Student"},
}


def _paragraphs(container):
    out = list(container.paragraphs)
    for table in container.tables:
        for row in table.rows:
            for cell in row.cells:
                out.extend(_paragraphs(cell))
    return out


def _text(docx_bytes: bytes) -> str:
    return "\n".join(p.text for p in _paragraphs(Document(io.BytesIO(docx_bytes))))


def _no_placeholders_left(text: str):
    assert "[" not in text and "]" not in text, [line for line in text.splitlines() if "[" in line]


@pytest.fixture(autouse=True)
def _need_templates():
    for path in (sg.COVER_SINGLE_TEMPLATE_PATH, sg.COVER_MULTI_TEMPLATE_PATH, sg.SUB_AGENT_TEMPLATE_PATH,
                 sg.AUTH_LETTER_TEMPLATE_PATH):
        skip_if_missing(path)


# -- the templates themselves hold no client data --------------------------------


def test_templates_are_clean_placeholder_files():
    for path in (sg.COVER_SINGLE_TEMPLATE_PATH, sg.COVER_MULTI_TEMPLATE_PATH, sg.SUB_AGENT_TEMPLATE_PATH,
                 sg.AUTH_LETTER_TEMPLATE_PATH):
        doc = Document(path)
        text = "\n".join(p.text for p in _paragraphs(doc))
        core = doc.core_properties
        assert core.author == "Khanna Travels & Holidays", path
        assert core.last_modified_by == "Khanna Travels & Holidays", path
        # No passport-number-shaped value (1-2 capitals + 6-8 digits) may remain.
        import re
        assert not re.search(r"\b[A-Z]{1,2}\d{6,8}\b", text), path
        assert "@gmail" not in text and "@hotmail" not in text, path


# -- single-traveller cover letter ------------------------------------------------


def test_single_cover_letter_fills_every_field():
    text = _text(sg.generate_cover_letter_docx(APPLICANT, [], FIELDS, "2026-11-02"))
    _no_placeholders_left(text)
    assert "November 2, 2026" in text
    assert "Mr. Test Applicant (holding Indian Passport No.: X1234567 issued at Mumbai on 05/01/2020)" in text
    assert "from 21st September 2026 to 26th September 2026" in text
    assert "I am currently a student at Test College." in text
    assert "I will be staying at Test Hotel - 1 Test Road, Singapore 000000." in text
    assert "will be borne by me." in text
    assert "for the issuance of my visa." in text
    assert "Phone No.: +91 9876543210" in text and "Email ID: test@example.com" in text


def test_single_cover_letter_raises_the_date_ordinals():
    doc = Document(io.BytesIO(sg.generate_cover_letter_docx(APPLICANT, [], FIELDS)))
    raised = [r.text for p in doc.paragraphs for r in p.runs if r.font.superscript]
    assert raised == ["st", "th"]


def test_single_cover_letter_names_a_payer_as_entered():
    text = _text(sg.generate_cover_letter_docx(APPLICANT, [], dict(FIELDS, fundingArrangement="Test Payer (Father)")))
    assert "will be borne by Test Payer (Father)." in text


def test_single_cover_letter_without_an_occupation_leaves_the_sentence_out():
    text = _text(sg.generate_cover_letter_docx(APPLICANT, [], dict(FIELDS, occupations={})))
    _no_placeholders_left(text)
    assert "I am currently" not in text


def test_single_cover_letter_uses_the_corrected_consulate_wording():
    text = _text(sg.generate_cover_letter_docx(APPLICANT, [], FIELDS))
    assert "Maker Chambers IV" in text and "Marker" not in text


# -- two or multiple travellers ----------------------------------------------------


def test_two_travellers_name_the_relation_in_the_sentence_and_the_subject():
    fields = dict(FIELDS, travellerRelation="Wife")
    text = _text(sg.generate_cover_letter_docx(APPLICANT, [WIFE], fields, "2026-11-02"))
    _no_placeholders_left(text)
    assert "Date: 02.11.2026" in text
    assert "Sub: Request for issue of Tourism Visa for me & my wife" in text
    assert "along with my wife & would like to travel on 21st September 2026 and will stay until 26th September 2026." in text
    assert "All our travel expenses will be borne by me." in text
    assert "bank statement of my bank account" in text


def test_several_travellers_say_family_and_fill_one_table_row_each():
    docx_bytes = sg.generate_cover_letter_docx(APPLICANT, [WIFE, SON], FIELDS)
    doc = Document(io.BytesIO(docx_bytes))
    text = _text(docx_bytes)
    _no_placeholders_left(text)
    assert "for me & my family" in text and "along with my family" in text
    rows = [[c.text.strip() for c in row.cells] for row in doc.tables[0].rows]
    assert rows[0] == ["Sr no.", "Passengers Name", "Passport No", "Relation", "Occupation"]
    assert rows[1] == ["1", "Mr. Test Applicant", "X1234567", "Self", "a student at Test College"]
    assert rows[2] == ["2", "Mrs. Test Spouse", "Y7654321", "Wife", "Homemaker"]
    assert rows[3] == ["3", "Mstr. Test Child", "Z1111111", "Son", "Student"]


def test_a_sponsor_changes_the_funding_and_bank_statement_wording():
    fields = dict(FIELDS, fundingArrangement="Test Payer (Father)", fundingPayerName="Test Payer")
    text = _text(sg.generate_cover_letter_docx(APPLICANT, [WIFE], fields))
    assert "will be borne by Test Payer (Father)." in text
    assert "bank statement of Test Payer's bank account" in text


def test_a_companion_with_no_occupation_gets_a_dash_in_the_table():
    fields = dict(FIELDS, occupations={"a": "Employed"})
    doc = Document(io.BytesIO(sg.generate_cover_letter_docx(APPLICANT, [WIFE], fields)))
    assert doc.tables[0].rows[2].cells[4].text.strip() == "—"


def test_cover_letter_requires_an_applicant():
    with pytest.raises(ValueError):
        sg.generate_cover_letter_docx({}, [], FIELDS)


# -- Authorization 1: Sub-Agent Declaration Form -----------------------------------


def test_sub_agent_declaration_lists_every_passport_and_counts_applications():
    text = _text(sg.generate_sub_agent_declaration_docx([APPLICANT, WIFE, SON], "", "", "2026-11-02"))
    _no_placeholders_left(text)
    assert "Total Number of Applications: 3" in text
    for line in ("1. X1234567", "2. Y7654321", "3. Z1111111"):
        assert line in text
    assert text.count("Date: 02/11/2026") == 2
    assert "Contact Person: Esha Sharma" in text and "Designation: Visa Consultant" in text


def test_sub_agent_declaration_uses_the_signer_entered():
    text = _text(sg.generate_sub_agent_declaration_docx([APPLICANT], "Test Signer", "Manager"))
    assert "Contact Person: Test Signer" in text and "Name: Test Signer" in text
    assert "Designation: Manager" in text and "Esha Sharma" not in text


def test_sub_agent_declaration_requires_an_applicant():
    with pytest.raises(ValueError):
        sg.generate_sub_agent_declaration_docx([])


# -- Authorization 2: Authorisation Letter for Visa Application ----------------------


def test_authorisation_letter_for_one_applicant_is_singular():
    text = _text(sg.generate_authorisation_letter_docx([APPLICANT], "Mr. Test Rep", "8000"))
    _no_placeholders_left(text)
    assert "I, Mr. Test Applicant, holder of Passport Type & Number / Identity Card No. X1234567 do hereby" in text
    assert "appoint Mr. Test Rep as my representative" in text
    assert "Visa Application Fee: INR 8000/- Pax - 01" in text


def test_authorisation_letter_for_several_applicants_names_one_person_lists_all_passports():
    text = _text(sg.generate_authorisation_letter_docx([APPLICANT, WIFE], "", "8000"))
    assert "I, Mr. Test Applicant, holder of Passport Type & Number / Identity Card No. X1234567 and Y7654321 do hereby" in text
    assert "Test Spouse" not in text
    assert "holders" not in text
    assert "as my representative" in text
    assert "Visa Application Fee: INR 16000/- Pax - 02" in text
    assert "Mr. Amol Sonawane" in text  # the default representative


def test_authorisation_letter_leaves_the_fee_to_write_by_hand_when_not_entered():
    text = _text(sg.generate_authorisation_letter_docx([APPLICANT, WIFE], "", ""))
    assert "Visa Application Fee: INR ______/- Pax - 02" in text


def test_authorisation_letter_keeps_its_qr_codes():
    doc = Document(io.BytesIO(sg.generate_authorisation_letter_docx([APPLICANT])))
    assert len(doc.inline_shapes) == 2


# -- PDFs and the editable preview ----------------------------------------------------


def test_every_singapore_letter_converts_to_pdf():
    skip_if_missing_binary("soffice")
    assert sg.generate_cover_letter_pdf(APPLICANT, [], FIELDS)[:5] == b"%PDF-"
    assert sg.generate_cover_letter_pdf(APPLICANT, [WIFE], FIELDS)[:5] == b"%PDF-"
    assert sg.generate_sub_agent_declaration_pdf([APPLICANT])[:5] == b"%PDF-"
    assert sg.generate_authorisation_letter_pdf([APPLICANT])[:5] == b"%PDF-"


def test_every_singapore_letter_reports_editable_blocks():
    skip_if_missing_binary("soffice")
    layouts = [
        sg.compute_cover_letter_layout(APPLICANT, [], FIELDS),
        sg.compute_cover_letter_layout(APPLICANT, [WIFE], FIELDS),
        sg.compute_sub_agent_declaration_layout([APPLICANT]),
        sg.compute_authorisation_letter_layout([APPLICANT]),
    ]
    for layout in layouts:
        groups = layout["groups"][0]
        assert len(groups) > 5 and all(k.startswith("blk-") for k in groups)


def test_a_whole_document_edit_replaces_just_that_block():
    import document_blocks
    base = sg.generate_cover_letter_docx(APPLICANT, [], FIELDS)
    blocks = document_blocks.enumerate_blocks(Document(io.BytesIO(base)))
    target = next(b for b in blocks if b.text.startswith("Thanking You"))
    edited = sg.generate_cover_letter_docx(APPLICANT, [], FIELDS, edited_blocks={target.key: "<p>EDITED LINE</p>"})
    text = _text(edited)
    assert "EDITED LINE" in text and "Thanking You" not in text


# -- over HTTP -------------------------------------------------------------------------

from fastapi.testclient import TestClient  # noqa: E402

import app as backend_app  # noqa: E402

client = TestClient(backend_app.app)


def test_cover_letter_endpoint_picks_single_or_multi_template_by_people():
    base = {
        "region": "Singapore", "travelStartDate": "2026-09-21", "travelEndDate": "2026-09-26",
        "fundingArrangement": "myself", "hotelName": "Test Hotel", "hotelAddress": "1 Test Road",
        "people": [{"id": "a", "fullName": "Test Applicant", "isApplicant": True, "passportNumber": "X1234567",
                    "occupation": "a student"}],
    }
    single = client.post("/api/documents/cover-letter", json=base)
    assert single.status_code == 200
    assert not Document(io.BytesIO(single.content)).tables
    two = dict(base, people=base["people"] + [{"id": "b", "fullName": "Test Spouse", "passportNumber": "Y7654321",
                                                "relationToApplicant": "Spouse", "sex": "F"}])
    multi = client.post("/api/documents/cover-letter", json=two)
    assert multi.status_code == 200
    assert len(Document(io.BytesIO(multi.content)).tables[0].rows) == 3


def test_passport_authorization_endpoint_returns_the_singapore_authorisation_letter():
    res = client.post("/api/documents/passport-authorization", json={
        "letterFormat": "singapore", "representativeName": "Mr. Test Rep", "feePerApplicant": "8000",
        "people": [{"fullName": "Test Applicant", "passportNumber": "X1234567", "isApplicant": True}],
    })
    assert res.status_code == 200
    text = _text(res.content)
    assert "AUTHORISATION LETTER FOR VISA APPLICATION" in text and "Mr. Test Rep" in text and "INR 8000/-" in text


def test_company_authorization_endpoint_returns_the_singapore_sub_agent_declaration():
    res = client.post("/api/documents/company-authorization", json={
        "letterFormat": "singapore", "contactPerson": "Test Signer", "designation": "Manager",
        "people": [{"fullName": "Test Applicant", "passportNumber": "X1234567"}],
    })
    assert res.status_code == 200
    text = _text(res.content)
    assert "SUB-AGENT DECLARATION FORM" in text and "Test Signer" in text and "1. X1234567" in text


def test_standard_authorization_letters_are_unchanged_by_the_new_field():
    res = client.post("/api/documents/company-authorization", json={
        "people": [{"fullName": "Test Applicant", "passportNumber": "X1234567"}], "recipientText": "Visa Officer",
    })
    assert res.status_code == 200
    assert "SUB-AGENT" not in _text(res.content)


def test_singapore_compose_fields_has_no_named_fields():
    for path in ("passport-authorization", "company-authorization"):
        res = client.post(f"/api/documents/{path}/compose-fields", json={
            "letterFormat": "singapore", "people": [{"fullName": "A", "passportNumber": "P1"}],
        })
        assert res.status_code == 200 and res.json() == {"fields": {}}


def test_singapore_authorisation_layout_over_http():
    skip_if_missing_binary("soffice")
    res = client.post("/api/documents/passport-authorization", json={
        "letterFormat": "singapore", "format": "layout",
        "people": [{"fullName": "Test Applicant", "passportNumber": "X1234567"}],
    })
    assert res.status_code == 200
    assert all(k.startswith("blk-") for k in res.json()["groups"][0])
