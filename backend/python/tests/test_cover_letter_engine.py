"""
Tests for cover_letter_engine.py — the Europe / Japan / Singapore Cover
Letters, generated against the REAL reference-cover-letter-formats/ files
(project rule 5). Each region has its own real template with a different
fixed shape (Europe/Japan are always applicant + exactly one companion;
Singapore takes any number of companions, including zero), so each is
exercised on its own real template.
"""

import io

import pytest
from docx import Document

import cover_letter_engine as cle
from conftest import skip_if_missing, skip_if_missing_binary


def _all_paragraphs_including_nested_tables(container):
    paragraphs = list(container.paragraphs)
    for table in container.tables:
        for row in table.rows:
            for cell in row.cells:
                paragraphs.extend(_all_paragraphs_including_nested_tables(cell))
    return paragraphs


def _full_text(doc: Document) -> str:
    return "\n".join(p.text for p in _all_paragraphs_including_nested_tables(doc))


EUROPE_FIELDS = {
    "recipientText": "Consulate General of France, Mumbai",
    "destinationCountry": "France",
    "travelStartDate": "2026-11-10",
    "travelEndDate": "2026-11-20",
    "cityCountryOfResidence": "Mumbai, India",
    "numberOfNights": "10 nights",
    "applicantEmploymentStatus": "Salaried",
    "applicantJobTitle": "Software Engineer",
    "applicantEmployerName": "Acme Corp",
    "companionJobTitle": "Designer",
    "companionEmployerName": "Beta LLC",
    "companionEmploymentStartYear": "2015",
    "fundingArrangement": "Self-funded by the applicant",
}


def test_europe_cover_letter_requires_applicant_and_companion():
    with pytest.raises(ValueError):
        cle.generate_europe_cover_letter_docx({}, {}, EUROPE_FIELDS)


def test_europe_cover_letter_fills_real_template(sample_applicant, sample_companion):
    skip_if_missing(cle.EUROPE_TEMPLATE_PATH)
    docx_bytes = cle.generate_europe_cover_letter_docx(sample_applicant, sample_companion, EUROPE_FIELDS)
    assert docx_bytes[:2] == b"PK"
    text = _full_text(Document(io.BytesIO(docx_bytes)))
    assert sample_applicant["fullName"] in text
    assert sample_applicant["passportNumber"] in text
    assert EUROPE_FIELDS["destinationCountry"] in text
    assert EUROPE_FIELDS["applicantEmployerName"] in text
    assert sample_applicant["email"] in text


def test_europe_cover_letter_pdf(sample_applicant, sample_companion):
    skip_if_missing(cle.EUROPE_TEMPLATE_PATH)
    skip_if_missing_binary("soffice")
    pdf_bytes = cle.generate_europe_cover_letter_pdf(sample_applicant, sample_companion, EUROPE_FIELDS)
    assert pdf_bytes[:5] == b"%PDF-"


JAPAN_FIELDS = {
    "destinationCountry": "Japan",
    "travelStartDate": "2026-10-01",
    "travelEndDate": "2026-10-10",
    "applicantEmployerOccupation": "Software Engineer at Acme Corp",
    "companionOccupation": "Designer",
    "fundingArrangement": "Self-funded",
}


def test_japan_cover_letter_requires_applicant_and_companion():
    with pytest.raises(ValueError):
        cle.generate_japan_cover_letter_docx({}, {}, JAPAN_FIELDS, [])


def test_japan_cover_letter_fills_real_template_with_hotels(sample_applicant, sample_companion):
    skip_if_missing(cle.JAPAN_TEMPLATE_PATH)
    hotels = [
        {"name": "Tokyo Test Hotel", "checkIn": "2026-10-01", "checkOut": "2026-10-05", "contactNo": "+81 3 0000 0000"},
        {"name": "Osaka Test Hotel", "checkIn": "2026-10-05", "checkOut": "2026-10-10", "contactNo": "+81 6 0000 0000"},
    ]
    docx_bytes = cle.generate_japan_cover_letter_docx(sample_applicant, sample_companion, JAPAN_FIELDS, hotels)
    text = _full_text(Document(io.BytesIO(docx_bytes)))
    assert sample_applicant["fullName"] in text
    assert sample_companion["fullName"] in text
    for hotel in hotels:
        assert hotel["name"] in text


def test_japan_cover_letter_with_no_hotels_removes_the_templateless_row(sample_applicant, sample_companion):
    skip_if_missing(cle.JAPAN_TEMPLATE_PATH)
    # Must not raise, and must not leave literal "[Hotel Name 1]" placeholder text.
    docx_bytes = cle.generate_japan_cover_letter_docx(sample_applicant, sample_companion, JAPAN_FIELDS, [])
    text = _full_text(Document(io.BytesIO(docx_bytes)))
    assert "[Hotel Name" not in text


def test_japan_cover_letter_pdf(sample_applicant, sample_companion):
    skip_if_missing(cle.JAPAN_TEMPLATE_PATH)
    skip_if_missing_binary("soffice")
    pdf_bytes = cle.generate_japan_cover_letter_pdf(sample_applicant, sample_companion, JAPAN_FIELDS, [])
    assert pdf_bytes[:5] == b"%PDF-"


SINGAPORE_FIELDS = {
    "recipientText": "Consulate General of Singapore, Mumbai",
    "travelStartDate": "2026-09-01",
    "travelEndDate": "2026-09-08",
    "fundingArrangement": "Self-funded",
    "hotelName": "Singapore Test Hotel",
    "hotelAddress": "1 Test Ave, Singapore",
    "occupations": {},
}


def test_singapore_cover_letter_requires_at_least_the_applicant():
    with pytest.raises(ValueError):
        cle.generate_singapore_cover_letter_docx({}, [], SINGAPORE_FIELDS)


def test_singapore_cover_letter_with_no_companions(sample_applicant):
    skip_if_missing(cle.SINGAPORE_TEMPLATE_PATH)
    docx_bytes = cle.generate_singapore_cover_letter_docx(sample_applicant, [], SINGAPORE_FIELDS)
    text = _full_text(Document(io.BytesIO(docx_bytes)))
    assert sample_applicant["fullName"] in text
    assert "along with my Family" not in text, "solo traveller must not get the family clause"


def test_singapore_cover_letter_with_companions(sample_applicant, sample_companion):
    skip_if_missing(cle.SINGAPORE_TEMPLATE_PATH)
    docx_bytes = cle.generate_singapore_cover_letter_docx(sample_applicant, [sample_companion], SINGAPORE_FIELDS)
    text = _full_text(Document(io.BytesIO(docx_bytes)))
    assert sample_applicant["fullName"] in text
    assert "along with my Family" in text
    assert sample_companion["fullName"] in text, "companion must appear in the passenger table"


def test_singapore_cover_letter_pdf(sample_applicant):
    skip_if_missing(cle.SINGAPORE_TEMPLATE_PATH)
    skip_if_missing_binary("soffice")
    pdf_bytes = cle.generate_singapore_cover_letter_pdf(sample_applicant, [], SINGAPORE_FIELDS)
    assert pdf_bytes[:5] == b"%PDF-"
