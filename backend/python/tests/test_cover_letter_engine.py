"""
Tests for cover_letter_engine.py — the Europe / Japan / Singapore Cover
Letters, generated against the REAL reference-cover-letter-formats/ files
(project rule 5). Each region has its own real template with a different
fixed shape (Europe/Japan are the applicant alone or with one companion;
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


def test_europe_cover_letter_requires_an_applicant():
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


# ---------------------------------------------------------------------------
# Phase 4 proof of concept — Europe Cover Letter "Word-like" body editor
# ---------------------------------------------------------------------------


def test_compose_europe_body_paragraphs_matches_generated_docx(sample_applicant, sample_companion):
    """The shared composer (also used to seed the Quill editor) must
    produce the EXACT same wording that ends up in the real generated
    document when nothing has been edited — never a second,
    hand-duplicated copy of this business logic (project rule 15)."""
    skip_if_missing(cle.EUROPE_TEMPLATE_PATH)
    blocks = cle.compose_europe_body_paragraphs(sample_applicant, sample_companion, EUROPE_FIELDS)
    assert len(blocks) == 3
    assert all(b["align"] == "justify" for b in blocks)

    docx_bytes = cle.generate_europe_cover_letter_docx(sample_applicant, sample_companion, EUROPE_FIELDS)
    paragraphs = Document(io.BytesIO(docx_bytes)).paragraphs
    assert paragraphs[8].text == blocks[0]["text"]
    assert paragraphs[9].text == blocks[1]["text"]
    assert paragraphs[10].text == blocks[2]["text"]


def test_compose_europe_body_html_is_escaped_and_carries_justify_class(sample_applicant, sample_companion):
    skip_if_missing(cle.EUROPE_TEMPLATE_PATH)
    html = cle.compose_europe_body_html(sample_applicant, sample_companion, EUROPE_FIELDS)
    assert html.count("<p") == 3
    assert html.count('class="ql-align-justify"') == 3
    assert sample_applicant["fullName"] in html


def test_compose_europe_body_html_escapes_special_characters():
    applicant = {"fullName": "A & B <Co>", "passportNumber": "X1", "placeOfIssue": "Y", "passportIssueDate": "Z"}
    companion = {"fullName": "C & D", "relationToApplicant": "Spouse", "sex": "F"}
    html = cle.compose_europe_body_html(applicant, companion, EUROPE_FIELDS)
    assert "&amp;" in html
    assert "<Co>" not in html


def test_europe_cover_letter_with_edited_body_html_replaces_only_body_paragraphs(sample_applicant, sample_companion):
    """Every paragraph OUTSIDE the editable 8-10 range — including the
    signature block, which comes AFTER a range whose paragraph count the
    edit shrinks from 3 to 2 — must still be filled correctly. This is
    the concrete regression test for the 'capture stable paragraph
    references before mutating the live document.paragraphs view' rule
    documented in docx_utils.replace_paragraph_range_with_html."""
    skip_if_missing(cle.EUROPE_TEMPLATE_PATH)
    edited_html = (
        '<p class="ql-align-justify">Edited paragraph one with <strong>bold</strong> text.</p>'
        '<p class="ql-align-center">Edited paragraph two, centered and <em>italic</em>.</p>'
    )
    docx_bytes = cle.generate_europe_cover_letter_docx(
        sample_applicant, sample_companion, EUROPE_FIELDS, edited_body_html=edited_html
    )
    paragraphs = Document(io.BytesIO(docx_bytes)).paragraphs

    assert paragraphs[8].text == "Edited paragraph one with bold text."
    assert paragraphs[8].runs[1].text == "bold" and paragraphs[8].runs[1].bold is True
    assert paragraphs[9].text == "Edited paragraph two, centered and italic."
    from docx.enum.text import WD_ALIGN_PARAGRAPH

    assert paragraphs[9].alignment == WD_ALIGN_PARAGRAPH.CENTER

    # The body shrank from 3 paragraphs to 2, so every paragraph the real
    # generator fills AFTER the body range now sits one index earlier —
    # this must still be the real funding/signature text, not garbage
    # left over from a stale index into the old paragraph list.
    full_text = "\n".join(p.text for p in paragraphs)
    assert EUROPE_FIELDS["fundingArrangement"] in full_text
    assert sample_applicant["fullName"] in full_text
    assert sample_applicant["email"] in full_text
    assert "9819347139" in full_text or (sample_applicant.get("phone") or "") in full_text


def test_europe_cover_letter_with_empty_edited_body_html_leaves_one_blank_paragraph(sample_applicant, sample_companion):
    """An explicitly-cleared editor (editedBodyHtml="") is a real edit,
    not 'no edit was made' — the letter must never end up silently
    missing a paragraph where the template expects one."""
    skip_if_missing(cle.EUROPE_TEMPLATE_PATH)
    docx_bytes = cle.generate_europe_cover_letter_docx(
        sample_applicant, sample_companion, EUROPE_FIELDS, edited_body_html=""
    )
    paragraphs = Document(io.BytesIO(docx_bytes)).paragraphs
    full_text = "\n".join(p.text for p in paragraphs)
    # The signature block must still be present and correct even though
    # the body range collapsed to a single blank paragraph.
    assert sample_applicant["fullName"] in full_text
    assert sample_applicant["email"] in full_text


JAPAN_FIELDS = {
    "destinationCountry": "Japan",
    "travelStartDate": "2026-10-01",
    "travelEndDate": "2026-10-10",
    "applicantEmployerOccupation": "Software Engineer at Acme Corp",
    "companionOccupation": "Designer",
    "fundingArrangement": "Self-funded",
}


def test_japan_cover_letter_requires_an_applicant():
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


def test_singapore_cover_letter_with_no_companions_uses_the_single_traveller_letter(sample_applicant):
    skip_if_missing(cle.SINGAPORE_TEMPLATE_PATH)
    docx_bytes = cle.generate_singapore_cover_letter_docx(sample_applicant, [], SINGAPORE_FIELDS)
    doc = Document(io.BytesIO(docx_bytes))
    text = _full_text(doc)
    assert sample_applicant["fullName"] in text
    assert "along with my" not in text, "solo traveller must not get the family clause"
    assert not doc.tables, "the single-traveller letter has no passenger table"


def test_singapore_cover_letter_with_companions_uses_the_multi_traveller_letter(sample_applicant, sample_companion):
    skip_if_missing(cle.SINGAPORE_MULTI_TEMPLATE_PATH)
    docx_bytes = cle.generate_singapore_cover_letter_docx(sample_applicant, [sample_companion], SINGAPORE_FIELDS)
    doc = Document(io.BytesIO(docx_bytes))
    text = _full_text(doc)
    assert sample_applicant["fullName"] in text
    assert "along with my" in text
    assert sample_companion["fullName"] in text, "companion must appear in the passenger table"
    assert len(doc.tables[0].rows) == 3  # header + applicant + one companion


def test_singapore_cover_letter_pdf(sample_applicant):
    skip_if_missing(cle.SINGAPORE_TEMPLATE_PATH)
    skip_if_missing_binary("soffice")
    pdf_bytes = cle.generate_singapore_cover_letter_pdf(sample_applicant, [], SINGAPORE_FIELDS)
    assert pdf_bytes[:5] == b"%PDF-"


# ---------------------------------------------------------------------------
# One traveller, and how two travellers are related
# ---------------------------------------------------------------------------


def _paragraph_texts(docx_bytes):
    return [p.text for p in Document(io.BytesIO(docx_bytes)).paragraphs]


def test_europe_cover_letter_with_only_the_applicant_is_written_in_the_singular(sample_applicant):
    skip_if_missing(cle.EUROPE_TEMPLATE_PATH)
    text = "\n".join(_paragraph_texts(cle.generate_europe_cover_letter_docx(sample_applicant, None, EUROPE_FIELDS)))
    assert sample_applicant["fullName"] in text
    for plural in ("along with my family", "I and my", "We both", "We look forward", "our relevant documents", "for us will", "grant us", "our visa application"):
        assert plural not in text, plural
    assert "I reside in Mumbai, India" in text
    assert "for me will be borne" in text
    assert "grant me the necessary visa" in text
    assert "[" not in text, "no template placeholder may be left behind"


@pytest.mark.parametrize(
    "choice, custom, expected",
    [
        ("Wife", "", "along with my wife, "),
        ("Friend", "", "along with my friend, "),
        ("Husband", "business partner", "along with my business partner, "),  # typed wording wins
        ("", "", "along with my family member, "),  # nothing known about them
    ],
)
def test_europe_cover_letter_relation_wording_follows_the_dropdown_or_typed_text(
    sample_applicant, sample_companion, choice, custom, expected
):
    skip_if_missing(cle.EUROPE_TEMPLATE_PATH)
    companion = dict(sample_companion, relationToApplicant="", sex="")
    fields = dict(EUROPE_FIELDS, travellerRelation=choice, travellerRelationText=custom)
    text = "\n".join(_paragraph_texts(cle.generate_europe_cover_letter_docx(sample_applicant, companion, fields)))
    assert expected + companion["fullName"] in text
    bare = expected.replace("along with my ", "").rstrip(", ")
    assert f"While my {bare} is working for" in text


def test_europe_cover_letter_relation_falls_back_to_the_traveller_record(sample_applicant, sample_companion):
    companion = dict(sample_companion, relationToApplicant="Spouse", sex="F")
    paras = cle.compose_europe_body_paragraphs(sample_applicant, companion, EUROPE_FIELDS)
    assert "along with my wife, " in paras[0]["text"]


def test_europe_body_paragraphs_solo_have_no_companion_sentence(sample_applicant):
    paras = cle.compose_europe_body_paragraphs(sample_applicant, None, EUROPE_FIELDS)
    assert len(paras) == 3
    joined = " ".join(p["text"] for p in paras)
    assert "While my" not in joined and "companion" not in joined


def test_japan_cover_letter_with_only_the_applicant(sample_applicant):
    skip_if_missing(cle.JAPAN_TEMPLATE_PATH)
    text = "\n".join(_paragraph_texts(cle.generate_japan_cover_letter_docx(sample_applicant, None, JAPAN_FIELDS, [])))
    assert "along with my family" not in text
    assert "(holding Indian Passport No." in text
    assert "My " + "Family" not in text and "[Passenger 2 Name]" not in text and "[Occupation]" not in text
    assert "I will be staying at the below hotels:" in text
    assert "All my travel expenses" in text
    assert "attachment to my visa application form" in text


def test_japan_cover_letter_relation_wording(sample_applicant, sample_companion):
    skip_if_missing(cle.JAPAN_TEMPLATE_PATH)
    companion = dict(sample_companion, relationToApplicant="", sex="")
    fields = dict(JAPAN_FIELDS, travellerRelation="Brother")
    text = "\n".join(_paragraph_texts(cle.generate_japan_cover_letter_docx(sample_applicant, companion, fields, [])))
    assert "along with my brother from" in text
    assert "My Brother, " in text and companion["fullName"] in text
    custom = dict(JAPAN_FIELDS, travellerRelationText="close friend")
    text = "\n".join(_paragraph_texts(cle.generate_japan_cover_letter_docx(sample_applicant, companion, custom, [])))
    assert "along with my close friend from" in text


def test_traveller_relation_helper():
    import letter_shared as ls

    assert ls.traveller_relation("Wife", "", None) == ("my wife", "wife")
    assert ls.traveller_relation("Wife", "business partner", None) == ("my business partner", "business partner")
    assert ls.traveller_relation("", "Our friend", None) == ("Our friend", "friend")
    assert ls.traveller_relation("Other", "", None) == ("my family member", "family member")
    assert ls.traveller_relation("", "", {"relationToApplicant": "Parent", "sex": "M"}) == ("my father", "father")


def test_sentence_case_value():
    import letter_shared as ls

    assert ls.sentence_case_value("MUMBAI", place=True) == "Mumbai"
    assert ls.sentence_case_value("navi mumbai, india", place=True) == "Navi Mumbai, India"
    assert ls.sentence_case_value("NEW DELHI", place=True) == "New Delhi"
    assert ls.sentence_case_value("UAE", place=True) == "UAE"
    assert ls.sentence_case_value("TCS CONSULTANCY SERVICES") == "TCS Consultancy Services"
    assert ls.sentence_case_value("Software Engineer") == "Software Engineer"
    assert ls.sentence_case_value("") == ""


# ---------------------------------------------------------------------------
# Several companions (Stage 2 — no cap on any region)
# ---------------------------------------------------------------------------


def _text(docx_bytes: bytes) -> str:
    return _full_text(Document(io.BytesIO(docx_bytes)))


def _three_companions(sample_companion):
    return [
        dict(sample_companion, id="c1", fullName="Anita Test", passportNumber="C0000001", relationToApplicant="Spouse",
             sex="F", jobTitle="Teacher", employerName="Test School", employmentStartYear="2010", occupation="Teacher"),
        dict(sample_companion, id="c2", fullName="Rohan Test", passportNumber="C0000002", relationToApplicant="Child", sex="M"),
        dict(sample_companion, id="c3", fullName="Riya Test", passportNumber="C0000003", relationToApplicant="Child", sex="F"),
    ]


def test_europe_body_with_several_companions_names_each_with_their_relation(sample_applicant, sample_companion):
    fields = {"travelStartDate": "01/12/2026", "travelEndDate": "10/12/2026", "destinationCountry": "France"}
    paras = cle.compose_europe_body_paragraphs(sample_applicant, _three_companions(sample_companion), fields)
    text = "\n".join(p["text"] for p in paras)
    for needle in ("my wife, Anita Test", "my son, Rohan Test", "my daughter, Riya Test"):
        assert needle in text
    # Only the companion with job details gets a job sentence.
    assert "My wife is working for Test School since 2010" in text
    assert text.count("is working for") == 1
    assert "We both" not in text


def test_europe_body_with_one_companion_is_unchanged_by_the_list_form(sample_applicant, sample_companion):
    fields = {"travelStartDate": "1", "travelEndDate": "2", "companionJobTitle": "Teacher",
              "companionEmployerName": "School", "companionEmploymentStartYear": "2010"}
    as_dict = cle.compose_europe_body_paragraphs(sample_applicant, sample_companion, fields)
    as_list = cle.compose_europe_body_paragraphs(sample_applicant, [sample_companion], fields)
    assert as_dict == as_list
    assert "We both are financially independent" in as_dict[1]["text"]


def test_europe_and_japan_docx_with_several_companions(sample_applicant, sample_companion):
    skip_if_missing(cle.EUROPE_TEMPLATE_PATH)
    skip_if_missing(cle.JAPAN_TEMPLATE_PATH)
    companions = _three_companions(sample_companion)
    fields = {"travelStartDate": "01/12/2026", "travelEndDate": "10/12/2026", "destinationCountry": "Japan"}
    europe = _text(cle.generate_europe_cover_letter_docx(sample_applicant, companions, fields))
    japan = _text(cle.generate_japan_cover_letter_docx(sample_applicant, companions, fields, []))
    for name in ("Anita Test", "Rohan Test", "Riya Test"):
        assert name in europe and name in japan
    for number in ("C0000001", "C0000002", "C0000003"):
        assert number in japan
    # One template line per companion, the template's own instruction never shown.
    assert japan.count("(holding Indian Passport No.:") == 4  # applicant + 3
    assert "Add additional family member details" not in japan
    assert "is —" not in japan  # a companion without an occupation has no "is —" tail
