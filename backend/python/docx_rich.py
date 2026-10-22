"""
Khanna Travels & Holidays — Word list / table building blocks
=============================================================

Low-level OOXML helpers the editable preview's HTML -> .docx writer
(docx_utils.replace_paragraph_range_with_html) uses to turn what the Word-like
editor can produce into REAL Word structures rather than look-alikes:

* real bulleted / numbered lists (a `w:numPr` pointing at a numbering
  definition this module adds to the document if it has none), and
* real tables (`w:tbl`) sized to the width of the place they are inserted.

Nothing here touches the reference templates' own content; it only adds
numbering definitions / tables to the document being generated.
"""

from __future__ import annotations

import copy
from typing import Optional

from docx.oxml import OxmlElement, parse_xml
from docx.oxml.ns import nsdecls, qn

_W_NS = nsdecls("w")

_BULLET_CHARS = [
    ("", "Symbol"),
    ("o", "Courier New"),
    ("", "Wingdings"),
]
_ORDERED_FORMATS = ["decimal", "lowerLetter", "lowerRoman"]


def _bullet_abstract_xml(abstract_id: int) -> str:
    levels = []
    for lvl in range(9):
        char, font = _BULLET_CHARS[lvl % 3]
        levels.append(
            f'<w:lvl w:ilvl="{lvl}"><w:start w:val="1"/><w:numFmt w:val="bullet"/>'
            f'<w:lvlText w:val="{char}"/><w:lvlJc w:val="left"/>'
            f'<w:pPr><w:ind w:left="{720 + 360 * lvl}" w:hanging="360"/></w:pPr>'
            f'<w:rPr><w:rFonts w:ascii="{font}" w:hAnsi="{font}" w:cs="{font}" w:hint="default"/></w:rPr></w:lvl>'
        )
    return (
        f'<w:abstractNum {_W_NS} w:abstractNumId="{abstract_id}">'
        '<w:multiLevelType w:val="hybridMultilevel"/>' + "".join(levels) + "</w:abstractNum>"
    )


def _ordered_abstract_xml(abstract_id: int) -> str:
    levels = []
    for lvl in range(9):
        fmt = _ORDERED_FORMATS[lvl % 3]
        levels.append(
            f'<w:lvl w:ilvl="{lvl}"><w:start w:val="1"/><w:numFmt w:val="{fmt}"/>'
            f'<w:lvlText w:val="%{lvl + 1}."/><w:lvlJc w:val="left"/>'
            f'<w:pPr><w:ind w:left="{720 + 360 * lvl}" w:hanging="360"/></w:pPr></w:lvl>'
        )
    return (
        f'<w:abstractNum {_W_NS} w:abstractNumId="{abstract_id}">'
        '<w:multiLevelType w:val="hybridMultilevel"/>' + "".join(levels) + "</w:abstractNum>"
    )


def _numbering_element(document):
    """The document's `w:numbering` root, creating the part when the template
    has none."""
    from docx.opc.constants import CONTENT_TYPE as CT
    from docx.opc.constants import RELATIONSHIP_TYPE as RT
    from docx.opc.packuri import PackURI
    from docx.parts.numbering import NumberingPart

    part = document.part
    try:
        return part.part_related_by(RT.NUMBERING).element
    except KeyError:
        element = parse_xml(f"<w:numbering {_W_NS}/>")
        new_part = NumberingPart(PackURI("/word/numbering.xml"), CT.WML_NUMBERING, element, part.package)
        part.relate_to(new_part, RT.NUMBERING)
        return element


class NumberingManager:
    """Adds (once per document) one bullet and one ordered numbering
    definition, and hands out `w:num` ids: the bullet id is shared, every
    ordered list gets its own num that restarts at 1."""

    def __init__(self, document):
        self._el = _numbering_element(document)
        self._bullet_num: Optional[int] = None
        self._ordered_abstract: Optional[int] = None

    def _next_id(self, tag: str, attr: str) -> int:
        ids = [int(e.get(qn(attr))) for e in self._el.findall(qn(tag)) if e.get(qn(attr), "").isdigit()]
        return (max(ids) + 1) if ids else 1

    def _add_abstract(self, xml_for) -> int:
        abstract_id = self._next_id("w:abstractNum", "w:abstractNumId")
        abstract = parse_xml(xml_for(abstract_id))
        # Schema: every abstractNum comes before the first num.
        first_num = self._el.find(qn("w:num"))
        if first_num is not None:
            first_num.addprevious(abstract)
        else:
            self._el.append(abstract)
        return abstract_id

    def _add_num(self, abstract_id: int, restart: bool) -> int:
        num_id = self._next_id("w:num", "w:numId")
        overrides = ""
        if restart:
            overrides = "".join(
                f'<w:lvlOverride w:ilvl="{i}"><w:startOverride w:val="1"/></w:lvlOverride>' for i in range(9)
            )
        self._el.append(
            parse_xml(f'<w:num {_W_NS} w:numId="{num_id}"><w:abstractNumId w:val="{abstract_id}"/>{overrides}</w:num>')
        )
        return num_id

    def bullet_num_id(self) -> int:
        if self._bullet_num is None:
            self._bullet_num = self._add_num(self._add_abstract(_bullet_abstract_xml), restart=False)
        return self._bullet_num

    def new_ordered_num_id(self) -> int:
        if self._ordered_abstract is None:
            self._ordered_abstract = self._add_abstract(_ordered_abstract_xml)
        return self._add_num(self._ordered_abstract, restart=True)


def numbering_for(document) -> NumberingManager:
    mgr = getattr(document.part, "_khanna_numbering", None)
    if mgr is None:
        mgr = NumberingManager(document)
        document.part._khanna_numbering = mgr
    return mgr


def set_paragraph_numbering(p_el, num_id: int, level: int) -> None:
    """Points a paragraph at a numbering definition (and drops any direct
    indent copied from the template paragraph so the list's own hanging
    indent applies)."""
    p_pr = p_el.get_or_add_pPr()
    for old in p_pr.findall(qn("w:numPr")):
        p_pr.remove(old)
    for old in p_pr.findall(qn("w:ind")):
        p_pr.remove(old)
    num_pr = OxmlElement("w:numPr")
    ilvl = OxmlElement("w:ilvl")
    ilvl.set(qn("w:val"), str(max(0, min(8, level))))
    num_id_el = OxmlElement("w:numId")
    num_id_el.set(qn("w:val"), str(num_id))
    num_pr.append(ilvl)
    num_pr.append(num_id_el)
    # Schema order: pStyle, keepNext, keepLines, pageBreakBefore, framePr,
    # widowControl, numPr, … — numPr goes right after those if present.
    before = [qn("w:" + n) for n in ("pStyle", "keepNext", "keepLines", "pageBreakBefore", "framePr", "widowControl")]
    anchor = None
    for child in p_pr:
        if child.tag in before:
            anchor = child
    if anchor is not None:
        anchor.addnext(num_pr)
    else:
        p_pr.insert(0, num_pr)


def content_width_twips(document, parent_el) -> int:
    """Usable width (twips) of the place new content is inserted: the table
    cell it sits in, or the page text width."""
    node = parent_el
    while node is not None and node.tag != qn("w:tc"):
        node = node.getparent()
    if node is not None:
        tc_w = node.find(f"{qn('w:tcPr')}/{qn('w:tcW')}")
        if tc_w is not None and tc_w.get(qn("w:type")) in (None, "dxa") and (tc_w.get(qn("w:w")) or "").isdigit():
            return max(1200, int(tc_w.get(qn("w:w"))) - 216)
        return 4000
    try:
        s = document.sections[-1]
        return int((s.page_width - s.left_margin - s.right_margin) / 635)
    except Exception:  # noqa: BLE001 — a template without usable section metrics
        return 9000


def new_table_element(n_rows: int, n_cols: int, total_width: int):
    """An empty bordered `w:tbl` with `n_rows` x `n_cols` cells, each holding
    one empty paragraph, equal column widths, filling `total_width`."""
    col_w = max(400, total_width // max(1, n_cols))
    borders = "".join(
        f'<w:{side} w:val="single" w:sz="4" w:space="0" w:color="auto"/>'
        for side in ("top", "left", "bottom", "right", "insideH", "insideV")
    )
    grid = "".join(f'<w:gridCol w:w="{col_w}"/>' for _ in range(n_cols))
    rows = ""
    for _ in range(n_rows):
        cells = "".join(
            f'<w:tc><w:tcPr><w:tcW w:w="{col_w}" w:type="dxa"/></w:tcPr><w:p/></w:tc>' for _ in range(n_cols)
        )
        rows += f"<w:tr>{cells}</w:tr>"
    return parse_xml(
        f"<w:tbl {_W_NS}><w:tblPr><w:tblW w:w=\"{col_w * n_cols}\" w:type=\"dxa\"/>"
        f"<w:tblBorders>{borders}</w:tblBorders><w:tblLayout w:type=\"fixed\"/>"
        '<w:tblCellMar><w:left w:w="108" w:type="dxa"/><w:right w:w="108" w:type="dxa"/></w:tblCellMar>'
        f"</w:tblPr><w:tblGrid>{grid}</w:tblGrid>{rows}</w:tbl>"
    )


def ensure_container_ends_with_paragraph(parent_el) -> None:
    """A table cell must end with a paragraph; add an empty one if the last
    child is a table."""
    if parent_el.tag == qn("w:tc"):
        last = parent_el[-1] if len(parent_el) else None
        if last is None or last.tag != qn("w:p"):
            parent_el.append(copy.deepcopy(OxmlElement("w:p")))
