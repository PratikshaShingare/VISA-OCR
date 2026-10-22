"""
Tests for hotel_voucher_engine.py, generating against the REAL
reference-hotel-blocking-formats/Single Hotel/Hotel Booking Format.docx
template (project rule 5 — the reference template is the source of truth;
these tests must fail loudly if that real file's structure ever changes in
a way the engine can't safely handle, not pass against a fake stand-in).
"""

import io

import pytest
from docx import Document

import hotel_voucher_engine as hve
from conftest import skip_if_missing, skip_if_missing_binary


def _all_paragraphs_including_nested_tables(container):
    """python-docx's `document.tables` / `cell.tables` are NOT recursive —
    a table nested inside a table cell (exactly the Hotel Voucher
    template's own real structure: an outer wrapper table containing a
    'Booking details' table and a guest/room table inside one cell) is
    invisible to a plain `doc.tables` walk. This helper walks paragraphs
    and nested tables recursively so tests can assert on the full,
    real rendered text."""
    paragraphs = list(container.paragraphs)
    for table in container.tables:
        for row in table.rows:
            for cell in row.cells:
                paragraphs.extend(_all_paragraphs_including_nested_tables(cell))
    return paragraphs


def _full_text(doc: Document) -> str:
    return "\n".join(p.text for p in _all_paragraphs_including_nested_tables(doc))


def test_generate_hotel_voucher_docx_requires_at_least_one_hotel():
    with pytest.raises(ValueError):
        hve.generate_hotel_voucher_docx([])


def test_single_hotel_voucher_contains_the_real_booking_data(sample_hotel):
    skip_if_missing(hve.TEMPLATE_PATH)
    docx_bytes = hve.generate_hotel_voucher_docx([sample_hotel])
    assert docx_bytes[:2] == b"PK", "must be a real .docx (zip) file"

    doc = Document(io.BytesIO(docx_bytes))
    full_text = _full_text(doc)
    assert sample_hotel["hotelName"] in full_text
    assert sample_hotel["confirmationNumber"] in full_text
    assert sample_hotel["leadGuestName"] in full_text
    assert "01 Dec 2026" in full_text, "check-in date must be formatted, not left as raw ISO"
    assert "4 Night(s)" in full_text, "nights must be computed from check-in/check-out"


def test_multiple_hotels_clone_a_full_block_per_hotel(sample_hotels):
    skip_if_missing(hve.TEMPLATE_PATH)
    docx_bytes = hve.generate_hotel_voucher_docx(sample_hotels)
    doc = Document(io.BytesIO(docx_bytes))

    heading_count = sum(
        1
        for t in doc.tables
        if t.rows and t.rows[0].cells and t.rows[0].cells[0].paragraphs
        and t.rows[0].cells[0].paragraphs[0].text.strip() == "HOTEL VOUCHER"
    )
    assert heading_count == len(sample_hotels), (
        f"expected one cloned 'HOTEL VOUCHER' block per hotel ({len(sample_hotels)}), found {heading_count}"
    )

    full_text = _full_text(doc)
    for hotel in sample_hotels:
        assert hotel["hotelName"] in full_text
        assert hotel["confirmationNumber"] in full_text


def test_guest_names_list_is_filled_with_one_paragraph_per_guest():
    skip_if_missing(hve.TEMPLATE_PATH)
    hotel = {
        "hotelName": "Guest List Hotel",
        "confirmationNumber": "CONF-GL",
        "leadGuestName": "Lead Guest",
        "checkIn": "2026-06-01",
        "checkOut": "2026-06-03",
        "guestNames": ["Guest One", "Guest Two", "Guest Three"],
    }
    docx_bytes = hve.generate_hotel_voucher_docx([hotel])
    doc = Document(io.BytesIO(docx_bytes))
    full_text = _full_text(doc)
    for name in hotel["guestNames"]:
        assert name in full_text


def test_missing_fields_render_as_an_em_dash_not_blank_or_none():
    skip_if_missing(hve.TEMPLATE_PATH)
    minimal_hotel = {"hotelName": "Bare Hotel"}
    docx_bytes = hve.generate_hotel_voucher_docx([minimal_hotel])
    doc = Document(io.BytesIO(docx_bytes))
    full_text = _full_text(doc)
    assert "—" in full_text, "unfilled fields should show an honest placeholder, never 'None' or 'undefined'"
    assert "None" not in full_text


def test_generate_hotel_voucher_pdf_produces_a_real_pdf(sample_hotel):
    skip_if_missing(hve.TEMPLATE_PATH)
    skip_if_missing_binary("soffice")
    pdf_bytes = hve.generate_hotel_voucher_pdf([sample_hotel])
    assert pdf_bytes[:5] == b"%PDF-"


# ---------------------------------------------------------------------------
# Frontend rework, Phase 4 — Word-like body editor extended to Hotel Blocking
# ---------------------------------------------------------------------------


def test_compose_hotel_editable_fields_matches_the_real_generated_text(sample_hotel):
    """The editor's seed HTML must always describe exactly the same text a
    non-edited generation would have produced (project rule 15 — one shared
    source of truth, never two copies of the formatting logic)."""
    skip_if_missing(hve.TEMPLATE_PATH)
    fields = hve.compose_hotel_editable_fields(sample_hotel)
    assert set(fields.keys()) == set(hve._HOTEL_EDITABLE_FIELD_KEYS)
    assert f"<p>{sample_hotel['hotelName']}</p>" == fields["hotelName"]
    assert sample_hotel["confirmationNumber"] in fields["confirmationSentence"]
    assert "01 Dec 2026" in fields["checkIn"]
    assert "4 Night(s)" in fields["nights"]

    docx_bytes = hve.generate_hotel_voucher_docx([sample_hotel])
    doc = Document(io.BytesIO(docx_bytes))
    full_text = _full_text(doc)
    assert sample_hotel["hotelName"] in full_text
    assert "01 Dec 2026" in full_text


def test_compose_hotel_editable_fields_escapes_html_special_characters():
    skip_if_missing(hve.TEMPLATE_PATH)
    hotel = {"hotelName": "Tom & Jerry's <Resort>", "checkIn": "2026-06-01", "checkOut": "2026-06-03"}
    fields = hve.compose_hotel_editable_fields(hotel)
    assert "&amp;" in fields["hotelName"]
    assert "&lt;Resort&gt;" in fields["hotelName"]
    assert "<Resort>" not in fields["hotelName"]


def test_compose_hotel_editable_fields_guest_names_is_one_paragraph_per_name():
    skip_if_missing(hve.TEMPLATE_PATH)
    hotel = {"hotelName": "H", "guestNames": ["Alpha One", "Beta Two"]}
    fields = hve.compose_hotel_editable_fields(hotel)
    assert fields["guestNames"] == "<p>Alpha One</p><p>Beta Two</p>"


def test_edited_field_replaces_only_that_cell_others_stay_auto_generated(sample_hotel):
    """Editing ONE field (hotelName) must not disturb any other field's
    normal auto-generated value, and must not touch the fixed Hotel Policy
    text or the "HOTEL VOUCHER" heading at all (project rule 5)."""
    skip_if_missing(hve.TEMPLATE_PATH)
    hotel = dict(sample_hotel, editedFields={"hotelName": "<p><strong>Edited</strong> Grand Hotel</p>"})
    docx_bytes = hve.generate_hotel_voucher_docx([hotel])
    doc = Document(io.BytesIO(docx_bytes))
    full_text = _full_text(doc)

    assert "Edited Grand Hotel" in full_text
    assert sample_hotel["hotelName"] not in full_text
    # Every other field is untouched — still auto-generated from the same data.
    assert sample_hotel["confirmationNumber"] in full_text
    assert sample_hotel["leadGuestName"] in full_text
    assert "01 Dec 2026" in full_text
    assert "4 Night(s)" in full_text
    # Fixed template content (never a field) is completely unaffected.
    assert "HOTEL VOUCHER" in full_text
    assert "Early check out will attract full cancellation charge" in full_text

    # And the edited run really is bold, not just correct text — confirms
    # replace_paragraph_range_with_html's formatting parsing actually ran.
    # (Uses the module's own recursive helper since the hotel-name cell
    # lives inside a table nested inside a table cell — plain doc.tables
    # doesn't descend into that.)
    hotel_name_cell_para = None
    for p in _all_paragraphs_including_nested_tables(doc):
        if "Edited" in p.text:
            hotel_name_cell_para = p
    assert hotel_name_cell_para is not None
    assert any(r.bold for r in hotel_name_cell_para.runs if r.text.strip())


def test_edited_guest_names_field_replaces_the_whole_list(sample_hotel):
    skip_if_missing(hve.TEMPLATE_PATH)
    hotel = dict(
        sample_hotel,
        guestNames=["Original Guest"],
        editedFields={"guestNames": "<p>New Guest A</p><p>New Guest B</p><p>New Guest C</p>"},
    )
    docx_bytes = hve.generate_hotel_voucher_docx([hotel])
    doc = Document(io.BytesIO(docx_bytes))
    full_text = _full_text(doc)
    assert "New Guest A" in full_text
    assert "New Guest B" in full_text
    assert "New Guest C" in full_text
    assert "Original Guest" not in full_text


def test_edited_guest_counts_field_applies_to_the_guest_table_cell(sample_hotel):
    """The guest count now appears once — in the guest table's "No. of Guests"
    column (the upper box shows the number of nights instead)."""
    skip_if_missing(hve.TEMPLATE_PATH)
    hotel = dict(sample_hotel, editedFields={"guestCounts": "<p>3 Adults (custom note)</p>"})
    doc = Document(io.BytesIO(hve.generate_hotel_voucher_docx([hotel])))
    assert _full_text(doc).count("3 Adults (custom note)") == 1


def _booking_table(docx_bytes):
    doc = Document(io.BytesIO(docx_bytes))
    return doc.tables[0].rows[0].cells[0].tables[0].rows[1].cells[0].tables[0]


def test_upper_box_shows_plain_guest_number_with_no_adult_wording(sample_hotel):
    skip_if_missing(hve.TEMPLATE_PATH)
    hotel = dict(sample_hotel, noOfAdults="4", noOfChildren="0")
    docx_bytes = hve.generate_hotel_voucher_docx([hotel])
    row = _booking_table(docx_bytes).rows[2]
    assert row.cells[2].text.strip() == "No. of Guest(s):"
    assert row.cells[3].text.strip() == "4"
    # the guest table below keeps the full wording
    assert "4 Adult(s)" in _full_text(Document(io.BytesIO(docx_bytes)))


def test_upper_box_guest_number_adds_adults_and_children():
    skip_if_missing(hve.TEMPLATE_PATH)
    row = _booking_table(hve.generate_hotel_voucher_docx([{"hotelName": "H", "noOfAdults": "2", "noOfChildren": "3"}])).rows[2]
    assert row.cells[3].text.strip() == "5"
    row = _booking_table(hve.generate_hotel_voucher_docx([{"hotelName": "H"}])).rows[2]
    assert row.cells[3].text.strip() == "—"


def test_duration_is_calculated_from_check_in_and_check_out(sample_hotel):
    skip_if_missing(hve.TEMPLATE_PATH)
    for check_in, check_out, expected in [
        ("2026-10-24", "2026-11-07", "14 Night(s)"),   # across a month end
        ("2026-12-30", "2027-01-02", "3 Night(s)"),    # across a year end
        ("2028-02-27", "2028-03-01", "3 Night(s)"),    # leap year
        ("2026-10-30", "2026-10-16", "—"),             # check-out before check-in
    ]:
        hotel = dict(sample_hotel, checkIn=check_in, checkOut=check_out)
        assert _booking_table(hve.generate_hotel_voucher_docx([hotel])).rows[5].cells[1].text.strip() == expected


def test_upper_box_guest_number_can_be_edited(sample_hotel):
    skip_if_missing(hve.TEMPLATE_PATH)
    hotel = dict(sample_hotel, editedFields={"guestTotal": "<p>Four</p>"})
    assert _booking_table(hve.generate_hotel_voucher_docx([hotel])).rows[2].cells[3].text.strip() == "Four"


def test_confirmation_number_is_bold_and_highlighted_like_the_template(sample_hotel):
    skip_if_missing(hve.TEMPLATE_PATH)
    hotel = dict(sample_hotel, confirmationNumber="ABC123")
    doc = Document(io.BytesIO(hve.generate_hotel_voucher_docx([hotel])))
    thanks = doc.tables[0].rows[0].cells[0].tables[0].rows[0].cells[0].paragraphs[0]
    runs = [r for r in thanks.runs if "ABC123" in r.text]
    assert len(runs) == 1
    assert runs[0].font.highlight_color is not None and runs[0].bold
    assert "Confirmation Number- ABC123" in thanks.text.replace("\n", "")
    # the fixed words keep the template's own formatting (bold "Confirmed")
    assert any(r.bold and "Confirmed" in r.text for r in thanks.runs)


def test_multiple_hotels_each_apply_their_own_independent_edited_fields(sample_hotels):
    """Two hotels in the same document, each with a DIFFERENT edited field —
    editing one hotel's block must never leak into or affect the other's."""
    skip_if_missing(hve.TEMPLATE_PATH)
    hotels = [dict(sample_hotels[0], editedFields={"hotelName": "<p>First Hotel Edited</p>"}), sample_hotels[1]]
    docx_bytes = hve.generate_hotel_voucher_docx(hotels)
    doc = Document(io.BytesIO(docx_bytes))
    full_text = _full_text(doc)
    assert "First Hotel Edited" in full_text
    assert sample_hotels[0]["hotelName"] not in full_text
    assert sample_hotels[1]["hotelName"] in full_text  # untouched, still auto-generated


def test_empty_edited_field_html_collapses_to_one_blank_paragraph_not_a_crash(sample_hotel):
    skip_if_missing(hve.TEMPLATE_PATH)
    hotel = dict(sample_hotel, editedFields={"hotelName": ""})
    docx_bytes = hve.generate_hotel_voucher_docx([hotel])
    doc = Document(io.BytesIO(docx_bytes))  # must not raise
    assert doc is not None


def test_edited_field_formatting_reaches_the_docx(sample_hotel):
    skip_if_missing(hve.TEMPLATE_PATH)
    from docx.shared import Pt

    hotel = dict(sample_hotel)
    hotel["editedFields"] = {
        "hotelName": '<p><span style="font-size: 20pt; color: #e60000; background-color: #ffff00"><strong>Edited Name</strong></span></p>'
    }
    doc = Document(io.BytesIO(hve.generate_hotel_voucher_docx([hotel])))
    runs = [r for p in _all_paragraphs_including_nested_tables(doc) for r in p.runs if r.text == "Edited Name"]
    assert len(runs) == 1
    run = runs[0]
    assert run.bold is True
    assert run.font.size == Pt(20)
    assert str(run.font.color.rgb) == "E60000"
    # yellow is one of Word's own highlighter colours -> a real Word highlight
    assert 'w:highlight w:val="yellow"' in run._r.xml


def test_compute_field_layout_locates_every_editable_value(sample_hotels):
    skip_if_missing(hve.TEMPLATE_PATH)
    skip_if_missing_binary("soffice")
    layout = hve.compute_field_layout(sample_hotels)
    assert len(layout["hotels"]) == len(sample_hotels)
    for fields in layout["hotels"]:
        # the named values, plus the whole-document blocks (blk-…)
        assert set(hve.LAYOUT_FIELD_KEYS) <= set(fields)
        assert all(k.startswith("blk-") for k in set(fields) - set(hve.LAYOUT_FIELD_KEYS))
        for info in fields.values():
            x0, y0, x1, y1 = info["rect"]
            assert x1 > x0 and y1 > y0
            assert info["fontSize"] and info["align"] in ("left", "center", "right", "justify")
    # hotels land on different pages / positions, never overlapping each other
    a, b = layout["hotels"][0]["hotelName"], layout["hotels"][1]["hotelName"]
    assert (a["page"], a["rect"]) != (b["page"], b["rect"])


def _guest_cell_paragraphs(docx_bytes):
    doc = Document(io.BytesIO(docx_bytes))
    # Same structural path the engine fills: block table -> wrapper -> detail cell -> guest table.
    wrapper = doc.tables[0].rows[0].cells[0].tables[0]
    guest = wrapper.rows[1].cells[0].tables[1]
    return [p.text for p in guest.rows[1].cells[0].paragraphs]


def test_guest_table_lists_lead_guest_first_then_every_added_guest():
    skip_if_missing(hve.TEMPLATE_PATH)
    hotel = {
        "hotelName": "All Guests Hotel",
        "leadGuestName": "Lead Person",
        "checkIn": "2026-06-01",
        "checkOut": "2026-06-03",
        "guestNames": ["Second Person", "Third Person"],
    }
    assert _guest_cell_paragraphs(hve.generate_hotel_voucher_docx([hotel])) == [
        "Lead Person", "Second Person", "Third Person",
    ]


def test_guest_table_does_not_repeat_the_lead_guest_or_blank_rows():
    skip_if_missing(hve.TEMPLATE_PATH)
    hotel = {
        "hotelName": "Dedupe Hotel",
        "leadGuestName": "Lead Person",
        "guestNames": ["  lead   person ", "", "Second Person", "SECOND PERSON"],
    }
    assert _guest_cell_paragraphs(hve.generate_hotel_voucher_docx([hotel])) == [
        "Lead Person", "Second Person",
    ]


def test_guest_table_with_only_lead_guest_or_only_added_guests():
    skip_if_missing(hve.TEMPLATE_PATH)
    assert _guest_cell_paragraphs(hve.generate_hotel_voucher_docx([{"hotelName": "H", "leadGuestName": "Only Lead"}])) == ["Only Lead"]
    assert _guest_cell_paragraphs(hve.generate_hotel_voucher_docx([{"hotelName": "H", "guestNames": ["A One", "B Two"]}])) == ["A One", "B Two"]


def test_every_guest_line_keeps_the_templates_numbered_list_format():
    skip_if_missing(hve.TEMPLATE_PATH)
    hotel = {"hotelName": "H", "leadGuestName": "Lead", "guestNames": ["B", "C", "D", "E"]}
    doc = Document(io.BytesIO(hve.generate_hotel_voucher_docx([hotel])))
    guest = doc.tables[0].rows[0].cells[0].tables[0].rows[1].cells[0].tables[1]
    paragraphs = guest.rows[1].cells[0].paragraphs
    assert [p.text for p in paragraphs] == ["Lead", "B", "C", "D", "E"]
    for p in paragraphs:
        assert p._p.pPr is not None and p._p.pPr.numPr is not None, f"{p.text!r} lost its list numbering"
