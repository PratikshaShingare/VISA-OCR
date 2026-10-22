"""
Khanna Travels & Holidays — whole-document editable blocks
==========================================================

Every document engine already lets staff edit its *named* fields (date,
recipient, body wording …) right on the preview. This module makes the REST
of the document editable the same way, so a staff member can fix any sentence
of the printed letter without it being a pre-declared field.

How it works (one pass over the finished document, shared by every engine):

1. Every body paragraph that has visible text — including paragraphs inside
   table cells — is a "block". Its key is `blk-<hash of its text>-<n>`, where
   n counts blocks with identical text (so three identical "Yours faithfully,"
   lines stay distinguishable). The key depends only on the generated text,
   never on position, so it is identical in the real document and in the
   layout-probe copy.
2. `edited_fields["blk-…"] = html` replaces exactly that paragraph with the
   edited content (docx_utils.replace_paragraph_range_with_html — real Word
   lists, tables, spacing …). An edit whose block no longer exists (the text
   it was made against changed, e.g. a different applicant) is reported in
   `unmatched` rather than silently dropped.
3. For the layout probe (see docx_utils.ProbeShader) every block that is not
   already a named field is shaded in its own decodable colour and its
   original content is exported as Quill-ready HTML, so the browser can lay an
   editor over it. Headers, footers, the logo and images are never blocks —
   they stay exactly as the reference template has them (project rule 5).
"""

from __future__ import annotations

import hashlib
import html as _html
import re
from typing import Optional

from docx.oxml.ns import qn

import docx_utils

KEY_PREFIX = "blk-"

_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_SKIP_DESCENDANTS = ("drawing", "pict", "object", "fldChar", "fldSimple", "instrText", "sym")


class Block:
    __slots__ = ("key", "el", "text", "seed")

    def __init__(self, key, el, text, seed):
        self.key, self.el, self.text, self.seed = key, el, text, seed


def is_block_key(key: str) -> bool:
    return isinstance(key, str) and key.startswith(KEY_PREFIX)


def _paragraph_text(p_el) -> str:
    parts = []
    for node in p_el.iter():
        if node.tag == _W + "t":
            parts.append(node.text or "")
        elif node.tag in (_W + "tab", _W + "br"):
            parts.append(" ")
    return "".join(parts)


def _normalise(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def _is_eligible(p_el) -> bool:
    node = p_el.getparent()
    while node is not None:
        if node.tag == _W + "txbxContent":
            return False
        node = node.getparent()
    for desc in p_el.iter():
        if desc.tag in tuple(_W + n for n in _SKIP_DESCENDANTS):
            return False
    p_pr = p_el.find(qn("w:pPr"))
    if p_pr is not None and p_pr.find(qn("w:sectPr")) is not None:
        return False
    return bool(_normalise(_paragraph_text(p_el)))


def _is_probe_fill(fill: Optional[str]) -> bool:
    if not fill or len(fill) != 6:
        return False
    try:
        r, g, b = int(fill[0:2], 16), int(fill[2:4], 16), int(fill[4:6], 16)
    except ValueError:
        return False
    return b == docx_utils._PROBE_B and r >= 20 and g >= 20


def is_probe_shaded(p_el) -> bool:
    """True when this paragraph (or the table cell around it) already carries
    a layout-probe colour — i.e. it is a named field the engine shades itself."""
    p_pr = p_el.find(qn("w:pPr"))
    if p_pr is not None:
        shd = p_pr.find(qn("w:shd"))
        if shd is not None and _is_probe_fill(shd.get(qn("w:fill"))):
            return True
    node = p_el.getparent()
    while node is not None:
        if node.tag == qn("w:tc"):
            shd = node.find(f"{qn('w:tcPr')}/{qn('w:shd')}")
            if shd is not None and _is_probe_fill(shd.get(qn("w:fill"))):
                return True
        node = node.getparent()
    return False


# --------------------------------------------------------------------------
# paragraph -> Quill-ready HTML (the seed an editor starts from)
# --------------------------------------------------------------------------


def _style_chain(style):
    while style is not None:
        yield style
        style = style.base_style


def _effective_flag(run, paragraph, attr: str) -> bool:
    value = getattr(run.font, attr)
    if value is None:
        for style in _style_chain(run.style):
            if getattr(style.font, attr) is not None:
                value = getattr(style.font, attr)
                break
    if value is None:
        for style in _style_chain(paragraph.style):
            if getattr(style.font, attr) is not None:
                value = getattr(style.font, attr)
                break
    return bool(value)


def _hex_to_highlight() -> dict:
    return {index: "#" + hex_ for hex_, index in docx_utils._word_highlight_map().items()}


def _run_html(run, paragraph, highlight_lookup: dict) -> str:
    from docx.enum.text import WD_UNDERLINE

    text_parts = []
    for node in run._r:
        if node.tag == _W + "t":
            text_parts.append(_html.escape(node.text or "", quote=False))
        elif node.tag == _W + "tab":
            text_parts.append("\t")
        elif node.tag == _W + "br":
            text_parts.append("<br>")
    inner = "".join(text_parts)
    if not inner:
        return ""

    styles = []
    font = run.font
    if font.name:
        styles.append(f"font-family: {font.name}")
    if font.size is not None:
        styles.append(f"font-size: {round(font.size.pt, 1):g}pt")
    try:
        if font.color is not None and font.color.type is not None and font.color.rgb is not None:
            styles.append(f"color: #{font.color.rgb}")
    except Exception:  # noqa: BLE001 — theme colours have no rgb; leave uncoloured
        pass
    highlight = None
    if font.highlight_color is not None:
        highlight = highlight_lookup.get(font.highlight_color)
    if highlight is None:
        shd = run._r.find(f"{qn('w:rPr')}/{qn('w:shd')}")
        if shd is not None and (shd.get(qn("w:fill")) or "auto").lower() not in ("auto", "ffffff"):
            highlight = "#" + shd.get(qn("w:fill"))
    if highlight:
        styles.append(f"background-color: {highlight}")
    if styles:
        inner = f'<span style="{"; ".join(styles)}">{inner}</span>'

    underline = font.underline
    if _effective_flag(run, paragraph, "bold"):
        inner = f"<strong>{inner}</strong>"
    if _effective_flag(run, paragraph, "italic"):
        inner = f"<em>{inner}</em>"
    if underline not in (None, False, WD_UNDERLINE.NONE):
        inner = f"<u>{inner}</u>"
    if _effective_flag(run, paragraph, "strike"):
        inner = f"<s>{inner}</s>"
    if font.subscript:
        inner = f"<sub>{inner}</sub>"
    elif font.superscript:
        inner = f"<sup>{inner}</sup>"
    return inner


def _list_info(document, paragraph) -> Optional[tuple]:
    """(type, level) when the paragraph is a Word list item, else None."""
    p_pr = paragraph._p.find(qn("w:pPr"))
    num_pr = p_pr.find(qn("w:numPr")) if p_pr is not None else None
    if num_pr is None:
        for style in _style_chain(paragraph.style):
            s_pr = style.element.find(qn("w:pPr"))
            if s_pr is not None and s_pr.find(qn("w:numPr")) is not None:
                num_pr = s_pr.find(qn("w:numPr"))
                break
    if num_pr is None:
        return None
    num_id_el = num_pr.find(qn("w:numId"))
    ilvl_el = num_pr.find(qn("w:ilvl"))
    if num_id_el is None or num_id_el.get(qn("w:val")) in (None, "0"):
        return None
    level = int(ilvl_el.get(qn("w:val"))) if ilvl_el is not None else 0
    kind = "bullet"
    try:
        from docx.opc.constants import RELATIONSHIP_TYPE as RT

        numbering = document.part.part_related_by(RT.NUMBERING).element
        abstract_id = None
        for num in numbering.findall(qn("w:num")):
            if num.get(qn("w:numId")) == num_id_el.get(qn("w:val")):
                abstract_id = num.find(qn("w:abstractNumId")).get(qn("w:val"))
        for abstract in numbering.findall(qn("w:abstractNum")):
            if abstract.get(qn("w:abstractNumId")) == abstract_id:
                for lvl in abstract.findall(qn("w:lvl")):
                    if lvl.get(qn("w:ilvl")) == str(level):
                        fmt = lvl.find(qn("w:numFmt"))
                        if fmt is not None and fmt.get(qn("w:val")) not in ("bullet", "none"):
                            kind = "ordered"
    except Exception:  # noqa: BLE001 — unreadable numbering: treat as bullet
        pass
    return kind, level


def paragraph_seed_html(document, p_el) -> str:
    """The paragraph as Quill-ready HTML (alignment, list status and every run's
    direct formatting stated explicitly)."""
    from docx.text.paragraph import Paragraph
    from docx.text.run import Run

    paragraph = Paragraph(p_el, document)
    lookup = _hex_to_highlight()
    pieces = []
    for child in p_el:
        if child.tag == _W + "r":
            pieces.append(_run_html(Run(child, paragraph), paragraph, lookup))
        elif child.tag == _W + "hyperlink":
            for r_el in child.findall(_W + "r"):
                pieces.append(_run_html(Run(r_el, paragraph), paragraph, lookup))
    inner = "".join(pieces) or "<br>"
    align = docx_utils.ProbeShader._effective_alignment(paragraph)
    cls = {"center": "ql-align-center", "right": "ql-align-right", "justify": "ql-align-justify"}.get(align)
    info = _list_info(document, paragraph)
    if info is not None:
        kind, level = info
        indent = f' class="ql-indent-{level}"' if level else ""
        return f'<ol><li data-list="{kind}"{indent}>{inner}</li></ol>'
    return f'<p class="{cls}">{inner}</p>' if cls else f"<p>{inner}</p>"


# --------------------------------------------------------------------------
# enumeration + edits + probe shading
# --------------------------------------------------------------------------


def enumerate_blocks(document, root=None) -> list:
    """Every block under `root` (default: the whole body), in document order.
    A multi-record document (the Hotel Voucher) enumerates each record's own
    table as its own root, so keys are scoped to that record."""
    counts: dict = {}
    blocks = []
    for p_el in (root if root is not None else document.element.body).iter(qn("w:p")):
        if not _is_eligible(p_el):
            continue
        text = _paragraph_text(p_el)
        digest = hashlib.sha1(_normalise(text).encode("utf-8")).hexdigest()[:8]
        n = counts.get(digest, 0)
        counts[digest] = n + 1
        blocks.append(Block(f"{KEY_PREFIX}{digest}-{n}", p_el, text, None))
    return blocks


def finalize(document, edited_fields: Optional[dict], shader=None, root=None) -> list:
    """Applies the whole-document edits and, for a layout probe, shades every
    remaining block. Returns the keys of edits that matched no block.
    `shader` is anything with `add_block(key, paragraphs, seed_html, align)`
    and an `unmatched` attribute (docx_utils.ProbeShader is one)."""
    from docx.text.paragraph import Paragraph

    edits = {k: v for k, v in (edited_fields or {}).items() if is_block_key(k) and v is not None}
    if not edits and shader is None:
        return []

    blocks = enumerate_blocks(document, root)
    # Seeds are the ORIGINAL content, captured before any edit is applied, so
    # "reset" always returns to the generated wording.
    if shader is not None:
        for b in blocks:
            b.seed = paragraph_seed_html(document, b.el)
    by_key = {b.key: b for b in blocks}
    unmatched = [k for k in edits if k not in by_key]

    resulting: dict = {}
    for key, html in edits.items():
        block = by_key.get(key)
        if block is None:
            continue
        paragraph = Paragraph(block.el, document)
        list_kind = _list_info(document, paragraph)
        _paragraphs, elements = docx_utils._replace_range(
            document, paragraph, paragraph, html, inherit_run_format=False,
            keep_template_list=list_kind[0] if list_kind else None, keep_blank=True,
        )
        resulting[key] = elements

    if shader is not None:
        for b in blocks:
            if b.key in resulting:
                els = resulting[b.key]
            elif is_probe_shaded(b.el):
                continue  # a named field the engine already shades
            else:
                els = [b.el]
            paragraphs = []
            for el in els:
                if el.tag == qn("w:tbl"):
                    paragraphs.extend(el.iter(qn("w:p")))
                else:
                    paragraphs.append(el)
            if paragraphs:
                align = docx_utils.ProbeShader._effective_alignment(Paragraph(paragraphs[0], document))
                shader.add_block(b.key, paragraphs, b.seed, align)
        shader.unmatched = unmatched
    return unmatched
