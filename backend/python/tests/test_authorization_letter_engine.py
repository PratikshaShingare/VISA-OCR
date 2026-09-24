"""
Tests for authorization_letter_engine.py — Passport Authorization Letter
(single + two travellers) and Company Authorization Letter, generated
against the REAL reference-templates/ files (project rule 5). These
templates are real former-client letters with the client's own data mostly
NOT bracketed (see the module's own docstring) — every dynamic field is
filled by verified structural position, so these tests exist specifically
to catch a template-structure regression the position-based fills would
otherwise silently mis-fill.
"""

import io

import pytest
from docx import Document

import authorization_letter_engine as ale
from conftest import skip_if_missing, skip_if_missing_binary


def _full_text(doc: Document) -> str:
    return "\n".join(p.text for p in doc.paragraphs)


# ---------------------------------------------------------------------------
# Passport Authorization Letter
# ---------------------------------------------------------------------------


def test_passport_auth_requires_at_least_one_traveller():
    with pytest.raises(ValueError):
        ale.generate_passport_authorization_docx([], "Some Centre", "Some Address", "Some Collector")


def test_passport_auth_rejects_more_than_two_travellers(sample_applicant, sample_companion):
    third = dict(sample_applicant, fullName="Third Person", passportNumber="T0000003")
    with pytest.raises(ValueError):
        ale.generate_passport_authorization_docx(
            [sample_applicant, sample_companion, third], "Some Centre", "Some Address", "Some Collector"
        )


def test_passport_auth_requires_collector_and_centre_name(sample_applicant):
    with pytest.raises(ValueError):
        ale.generate_passport_authorization_docx([sample_applicant], "Some Centre", "Some Address", "")
    with pytest.raises(ValueError):
        ale.generate_passport_authorization_docx([sample_applicant], "", "Some Address", "Some Collector")


def test_passport_auth_single_traveller_fills_real_template(sample_applicant):
    skip_if_missing(ale.PASSPORT_SINGLE_TEMPLATE_PATH)
    docx_bytes = ale.generate_passport_authorization_docx(
        [sample_applicant],
        recipient_centre_name="Test Visa Application Centre",
        recipient_address="123 Test Road, Test City",
        collector_name="Ms. Test Collector",
    )
    assert docx_bytes[:2] == b"PK"
    doc = Document(io.BytesIO(docx_bytes))
    text = _full_text(doc)
    assert sample_applicant["fullName"] in text
    assert sample_applicant["passportNumber"] in text
    assert "Ms. Test Collector" in text
    assert "Test Visa Application Centre" in text
    assert sample_applicant["email"] in text


def test_passport_auth_two_travellers_fills_both_names(sample_applicant, sample_companion):
    skip_if_missing(ale.PASSPORT_MULTIPLE_TEMPLATE_PATH)
    docx_bytes = ale.generate_passport_authorization_docx(
        [sample_applicant, sample_companion],
        recipient_centre_name="Test Visa Application Centre",
        recipient_address="123 Test Road, Test City",
        collector_name="Ms. Test Collector",
    )
    doc = Document(io.BytesIO(docx_bytes))
    text = _full_text(doc)
    assert sample_applicant["fullName"] in text
    assert sample_applicant["passportNumber"] in text
    assert sample_companion["fullName"] in text
    assert sample_companion["passportNumber"] in text


def test_passport_auth_never_leaks_the_real_former_clients_data(sample_applicant):
    """Project rule 11 — the real former client's name/passport/phone/email
    baked into these reference letters must never survive into generated
    output. A regression here would be a genuine data-leak bug, not just a
    cosmetic one."""
    skip_if_missing(ale.PASSPORT_SINGLE_TEMPLATE_PATH)
    docx_bytes = ale.generate_passport_authorization_docx(
        [sample_applicant], "Test Centre", "Test Address", "Test Collector"
    )
    doc = Document(io.BytesIO(docx_bytes))
    text = _full_text(doc)
    assert "Dilip Bijlani" not in text, "the real former client's name must never appear in generated output"
    assert "9819347139" not in text, "the real former client's phone number must never appear in generated output"


def test_passport_auth_pdf_produces_a_real_pdf(sample_applicant):
    skip_if_missing(ale.PASSPORT_SINGLE_TEMPLATE_PATH)
    skip_if_missing_binary("soffice")
    pdf_bytes = ale.generate_passport_authorization_pdf(
        [sample_applicant], "Test Centre", "Test Address", "Test Collector"
    )
    assert pdf_bytes[:5] == b"%PDF-"


# ---------------------------------------------------------------------------
# Company Authorization Letter
# ---------------------------------------------------------------------------


def test_company_auth_requires_at_least_one_applicant():
    with pytest.raises(ValueError):
        ale.generate_company_authorization_docx([], "Visa Officer, Some Consulate")


def test_company_auth_single_applicant(sample_applicant):
    skip_if_missing(ale.COMPANY_TEMPLATE_PATH)
    docx_bytes = ale.generate_company_authorization_docx([sample_applicant], "Visa Officer, Some Consulate")
    doc = Document(io.BytesIO(docx_bytes))
    text = _full_text(doc)
    assert sample_applicant["fullName"] in text
    assert sample_applicant["passportNumber"] in text
    assert "Visa Officer, Some Consulate" in text


def test_company_auth_clones_one_line_per_applicant(sample_applicant, sample_companion):
    skip_if_missing(ale.COMPANY_TEMPLATE_PATH)
    third = {"fullName": "Third Traveller", "passportNumber": "T0000003"}
    people = [sample_applicant, sample_companion, third]
    docx_bytes = ale.generate_company_authorization_docx(people, "Visa Officer, Some Consulate")
    doc = Document(io.BytesIO(docx_bytes))
    text = _full_text(doc)
    for person in people:
        assert person["fullName"].strip() in text
        assert person["passportNumber"] in text


def test_company_auth_pdf_produces_a_real_pdf(sample_applicant):
    skip_if_missing(ale.COMPANY_TEMPLATE_PATH)
    skip_if_missing_binary("soffice")
    pdf_bytes = ale.generate_company_authorization_pdf([sample_applicant], "Visa Officer, Some Consulate")
    assert pdf_bytes[:5] == b"%PDF-"
