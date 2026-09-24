"""
Unit tests for docx_utils.py — the shared, formatting-preserving .docx
helpers every document-generation engine builds on.

These tests build small SYNTHETIC .docx documents on the fly with
python-docx (not the project's real reference templates — see
test_hotel_voucher_engine.py / test_authorization_letter_engine.py /
test_cover_letter_engine.py / test_invitation_letter_engine.py for tests
against the real templates). That is deliberate here: these are unit tests
of the low-level mechanics themselves (run-preserving text replacement,
`<w:br/>`-aware two-line paragraphs, hyperlink rewriting, element cloning),
so a minimal, purpose-built document makes the exact structure under test
unambiguous.
"""

import io

import pytest
from docx import Document
from docx.oxml.ns import qn

import docx_utils
from conftest import skip_if_missing_binary


def _new_doc_with_paragraph(text: str = "Hello world"):
    doc = Document()
    doc.add_paragraph(text)
    return doc


def test_set_paragraph_text_preserves_first_run_formatting():
    doc = _new_doc_with_paragraph("Original text")
    para = doc.paragraphs[0]
    para.runs[0].bold = True
    docx_utils.set_paragraph_text(para, "Replaced text")
    assert para.text == "Replaced text"
    assert para.runs[0].bold is True


def test_set_paragraph_text_blanks_extra_runs_without_removing_them():
    doc = Document()
    para = doc.add_paragraph()
    para.add_run("Hello ")
    para.add_run("World")
    assert len(para.runs) == 2
    docx_utils.set_paragraph_text(para, "New")
    assert para.text == "New"
    assert len(para.runs) == 2, "run count must stay the same — never delete a run"
    assert para.runs[1].text == ""


def test_set_cell_text():
    doc = Document()
    table = doc.add_table(rows=1, cols=1)
    table.cell(0, 0).paragraphs[0].add_run("old")
    docx_utils.set_cell_text(table.cell(0, 0), "new value")
    assert table.cell(0, 0).text == "new value"


def test_replace_token_in_paragraph_found_and_not_found():
    doc = Document()
    para = doc.add_paragraph()
    para.add_run("Dear [Name], welcome.")
    found = docx_utils.replace_token_in_paragraph(para, "[Name]", "Rohan")
    assert found is True
    assert para.text == "Dear Rohan, welcome."

    found_again = docx_utils.replace_token_in_paragraph(para, "[Name]", "Someone Else")
    assert found_again is False, "token no longer present after the first replacement"


def test_replace_token_in_paragraph_merges_a_token_split_across_runs():
    doc = Document()
    para = doc.add_paragraph()
    # Simulate Word having split a single bracket token across three runs —
    # a real-world authoring artifact this helper exists specifically to
    # survive (see its own docstring).
    para.add_run("Dear [Na")
    para.add_run("me")
    para.add_run("], welcome.")
    found = docx_utils.replace_token_in_paragraph(para, "[Name]", "Priya")
    assert found is True
    assert para.text == "Dear Priya, welcome."


def test_apply_token_map_to_paragraph_replaces_every_pair():
    doc = Document()
    para = doc.add_paragraph()
    para.add_run("[A] and [B] and [A] again")
    docx_utils.apply_token_map_to_paragraph(para, {"[A]": "x", "[B]": "y"})
    assert para.text == "x and y and x again"


def test_replace_token_in_cell_scans_every_paragraph():
    doc = Document()
    table = doc.add_table(rows=1, cols=1)
    cell = table.cell(0, 0)
    cell.paragraphs[0].add_run("first paragraph")
    cell.add_paragraph("second paragraph with [Token] inside")
    found = docx_utils.replace_token_in_cell(cell, "[Token]", "REPLACED")
    assert found is True
    assert "REPLACED" in cell.text


def _add_run_with_break(paragraph, before_text: str, after_text: str):
    """Builds a paragraph with three runs — text, a real <w:br/>, more text
    — matching the exact shape docx_utils.set_two_line_paragraph documents
    itself as handling (verified against the real Passport Authorization
    Letter templates)."""
    r1 = paragraph.add_run(before_text)
    r_break = paragraph.add_run()
    br = r_break._element.makeelement(qn("w:br"), {})
    r_break._element.append(br)
    paragraph.add_run(after_text)
    return r1, r_break


def test_has_break_run_true_and_false():
    doc = Document()
    p_with_break = doc.add_paragraph()
    _add_run_with_break(p_with_break, "line1", "line2")
    assert docx_utils.has_break_run(p_with_break) is True

    p_without = doc.add_paragraph("plain text, no break")
    assert docx_utils.has_break_run(p_without) is False


def test_set_two_line_paragraph_preserves_the_break_and_sets_both_lines():
    doc = Document()
    para = doc.add_paragraph()
    _add_run_with_break(para, "Old Name", "Old Phone")
    docx_utils.set_two_line_paragraph(para, "Rohan Mehta", "Phone No.: +91 9876500001")

    assert docx_utils.has_break_run(para), "the <w:br/> element itself must survive"
    full_text_via_xml = "".join(t.text or "" for t in para._p.findall(f".//{qn('w:t')}"))
    assert "Rohan Mehta" in full_text_via_xml
    assert "Phone No.: +91 9876500001" in full_text_via_xml


def test_set_two_line_paragraph_falls_back_gracefully_without_a_break_run():
    doc = Document()
    para = doc.add_paragraph("single run, no break at all")
    docx_utils.set_two_line_paragraph(para, "Line One", "Line Two")
    assert "Line One" in para.text
    assert "Line Two" in para.text


def _add_hyperlink(paragraph, document, text: str, target: str):
    part = document.part
    r_id = part.relate_to(target, "http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink", is_external=True)
    hyperlink = paragraph._p.makeelement(qn("w:hyperlink"), {qn("r:id"): r_id})
    run = paragraph.add_run(text)
    run_el = run._element
    paragraph._p.remove(run_el)
    hyperlink.append(run_el)
    paragraph._p.append(hyperlink)
    return r_id


def test_find_hyperlink_text_run_and_update_text_and_target():
    doc = Document()
    para = doc.add_paragraph("Email id: ")
    _add_hyperlink(para, doc, "old@example.com", "mailto:old@example.com")

    found = docx_utils.find_hyperlink_text_run(para)
    assert found is not None
    _hyperlink_el, r_id, t_el = found
    assert t_el.text == "old@example.com"

    updated = docx_utils.set_hyperlink_text_and_target(para, doc, "new@example.com", "mailto:new@example.com")
    assert updated is True
    _hyperlink_el2, r_id2, t_el2 = docx_utils.find_hyperlink_text_run(para)
    assert t_el2.text == "new@example.com"


def test_set_hyperlink_text_and_target_returns_false_when_no_hyperlink():
    doc = Document()
    para = doc.add_paragraph("plain paragraph, no hyperlink")
    assert docx_utils.set_hyperlink_text_and_target(para, doc, "irrelevant") is False


def test_remove_hyperlinks_in_paragraph():
    doc = Document()
    para = doc.add_paragraph("Email Id: ")
    _add_hyperlink(para, doc, "leftover@example.com", "mailto:leftover@example.com")
    assert docx_utils.find_hyperlink_text_run(para) is not None

    removed = docx_utils.remove_hyperlinks_in_paragraph(para)
    assert removed == 1
    assert docx_utils.find_hyperlink_text_run(para) is None


def test_insert_signature_image_with_a_real_image(tmp_path):
    from PIL import Image

    img_path = tmp_path / "sig.png"
    Image.new("RGB", (100, 40), color="white").save(img_path)

    doc = Document()
    para = doc.add_paragraph()
    docx_utils.insert_signature_image(para, img_path.read_bytes())
    assert len(para.runs) == 1
    # A picture-bearing run contains a <w:drawing> element, not text.
    assert para.runs[0]._element.find(qn("w:drawing")) is not None


def test_insert_signature_image_raises_on_garbage_bytes():
    doc = Document()
    para = doc.add_paragraph()
    with pytest.raises(docx_utils.DocxBuildError):
        docx_utils.insert_signature_image(para, b"not a real image")


def test_delete_paragraph_removes_it_from_the_document():
    doc = Document()
    doc.add_paragraph("keep me")
    doc.add_paragraph("delete me")
    assert len(doc.paragraphs) == 2
    docx_utils.delete_paragraph(doc.paragraphs[1])
    assert len(doc.paragraphs) == 1
    assert doc.paragraphs[0].text == "keep me"


def test_clone_and_insert_after_duplicates_a_table_row_n_times():
    doc = Document()
    table = doc.add_table(rows=2, cols=1)
    template_row = table.rows[1]
    template_row.cells[0].text = "template"

    new_elements = docx_utils.clone_and_insert_after(template_row._tr, 3)
    assert len(new_elements) == 3
    assert len(table.rows) == 5, "1 header + 1 template + 3 clones = 5 rows"
    assert all(r.cells[0].text == "template" for r in table.rows[1:])


def test_convert_docx_bytes_to_pdf_produces_a_real_pdf():
    skip_if_missing_binary("soffice")
    doc = Document()
    doc.add_paragraph("PDF conversion smoke test")
    buf = io.BytesIO()
    doc.save(buf)
    pdf_bytes = docx_utils.convert_docx_bytes_to_pdf(buf.getvalue(), base_name="smoke_test")
    assert pdf_bytes[:5] == b"%PDF-", "output must be a real PDF, not a stub"
    assert len(pdf_bytes) > 200
