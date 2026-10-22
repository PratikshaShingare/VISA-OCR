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
from html.parser import HTMLParser
from typing import Optional

from docx.enum.text import WD_ALIGN_PARAGRAPH
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


_QUILL_ALIGN_CLASS_MAP = {
    "ql-align-center": "center",
    "ql-align-right": "right",
    "ql-align-justify": "both",
    # No class at all (Quill's own default) means left — deliberately not
    # listed here; callers treat a missing/unrecognized class as "left".
}

_ALIGN_TO_WD = {
    "left": WD_ALIGN_PARAGRAPH.LEFT,
    "center": WD_ALIGN_PARAGRAPH.CENTER,
    "right": WD_ALIGN_PARAGRAPH.RIGHT,
    "both": WD_ALIGN_PARAGRAPH.JUSTIFY,
    "justify": WD_ALIGN_PARAGRAPH.JUSTIFY,
}


_NAMED_COLORS = {
    "black": "000000", "white": "FFFFFF", "red": "FF0000", "green": "008000",
    "blue": "0000FF", "yellow": "FFFF00", "cyan": "00FFFF", "aqua": "00FFFF",
    "magenta": "FF00FF", "orange": "FFA500", "gray": "808080", "grey": "808080",
}


def _parse_css_color(value: str) -> Optional[str]:
    """CSS colour (#rgb, #rrggbb, rgb(r,g,b), a handful of names) -> 'RRGGBB'
    or None when it is not something we can represent (never raises)."""
    v = (value or "").strip().lower()
    if not v or v in ("transparent", "inherit", "initial"):
        return None
    if v in _NAMED_COLORS:
        return _NAMED_COLORS[v]
    if v.startswith("#"):
        h = v[1:]
        if len(h) == 3 and all(c in "0123456789abcdef" for c in h):
            return "".join(c * 2 for c in h).upper()
        if len(h) == 6 and all(c in "0123456789abcdef" for c in h):
            return h.upper()
        return None
    if v.startswith("rgb"):
        inner = v[v.find("(") + 1 : v.rfind(")")]
        parts = [p.strip() for p in inner.replace("/", ",").split(",")]
        try:
            r, g, b = (max(0, min(255, int(float(p)))) for p in parts[:3])
        except (ValueError, TypeError):
            return None
        return f"{r:02X}{g:02X}{b:02X}"
    return None


def _parse_span_style(style: str) -> dict:
    """The subset of an inline CSS `style` attribute the editable preview's
    toolbar can produce: color, background-color (highlight), font-size
    (pt or px), font-family, bold/italic/underline. Anything else is
    ignored — never an error."""
    out: dict = {}
    for decl in (style or "").split(";"):
        if ":" not in decl:
            continue
        name, _, value = decl.partition(":")
        name = name.strip().lower()
        value = value.strip()
        if name == "color":
            out["color"] = _parse_css_color(value)
        elif name in ("background-color", "background"):
            out["highlight"] = _parse_css_color(value)
        elif name == "font-size":
            v = value.lower()
            try:
                if v.endswith("pt"):
                    out["size_pt"] = float(v[:-2])
                elif v.endswith("px"):
                    out["size_pt"] = round(float(v[:-2]) * 0.75, 1)
            except ValueError:
                pass
            if out.get("size_pt") is not None and not (4 <= out["size_pt"] <= 96):
                del out["size_pt"]
        elif name == "font-family":
            first = value.split(",")[0].strip().strip("\"'").strip()
            if first and len(first) <= 60:
                out["font"] = first
        elif name == "font-weight" and (value in ("bold", "bolder") or value.isdigit() and int(value) >= 600):
            out["bold"] = True
        elif name == "font-style" and value == "italic":
            out["italic"] = True
        elif name == "text-decoration" and "underline" in value:
            out["underline"] = True
    return out


class _QuillHtmlParser(HTMLParser):
    """Parses the HTML a Quill 2 editor (the editable preview's Word-like
    editor) emits into plain blocks the .docx writer below consumes.

    Not a general HTML converter — it understands exactly what that editor
    can produce:

    * paragraph blocks  {"kind": "p", "align", "runs": [...], "list",
      "indent", "line_height", "space_before", "space_after"}
    * table blocks      {"kind": "table", "rows": [[{"blocks": [...]}, ...]]}

    Runs carry bold / italic / underline / strike / sub / sup plus the
    optional colour, highlight, size and font. Quill 2 writes every list as a
    flat `<ol><li data-list="bullet|ordered" class="ql-indent-N">` (nesting is
    the indent class), which becomes {"type", "level"}; `<ul>`/`<ol>` nesting
    from other sources is honoured as well. Block formats the toolbar adds
    (line height, space before/after) arrive as inline `style` on the block.
    `<br>` inside a paragraph is flattened to a space, as before.
    """

    _BLOCK_TAGS = ("p", "div", "h1", "h2", "h3", "h4", "h5", "h6", "li")

    def __init__(self, soft_breaks: bool = False):
        super().__init__(convert_charrefs=True)
        # soft_breaks: a <br> inside a paragraph is a real line break ("\n"
        # -> w:br) instead of a space (whole-document edits).
        self._soft_breaks = soft_breaks
        self.blocks: list[dict] = []
        self._target: list = self.blocks  # where finished blocks are appended
        self._current_block: Optional[dict] = None
        self._depth = {"bold": 0, "italic": 0, "underline": 0, "strike": 0, "sub": 0, "sup": 0}
        self._span_stack: list[dict] = []
        self._list_stack: list[str] = []  # enclosing <ul>/<ol> types
        self._skip_depth = 0  # inside <span class="ql-ui"> (list marker) — never text
        self._table: Optional[dict] = None
        self._row: Optional[list] = None
        self._cell: Optional[dict] = None

    # -- helpers ----------------------------------------------------------
    def _style_value(self, key: str):
        for frame in reversed(self._span_stack):
            if frame.get(key) is not None:
                return frame[key]
        return None

    @staticmethod
    def _block_style(attrs_d: dict) -> dict:
        out = {"line_height": None, "space_before": None, "space_after": None}
        for decl in (attrs_d.get("style") or "").split(";"):
            if ":" not in decl:
                continue
            name, _, value = decl.partition(":")
            name, value = name.strip().lower(), value.strip().lower()
            try:
                if name == "line-height":
                    v = float(value[:-1]) / 100 if value.endswith("%") else float(value)
                    if 0.5 <= v <= 6:
                        out["line_height"] = round(v, 2)
                elif name in ("margin-top", "margin-bottom"):
                    pt = float(value[:-2]) if value.endswith("pt") else float(value[:-2]) * 0.75 if value.endswith("px") else None
                    if pt is not None and 0 <= pt <= 200:
                        out["space_before" if name == "margin-top" else "space_after"] = round(pt, 1)
            except ValueError:
                pass
        return out

    def _open_block(self, attrs_d: dict, list_info=None) -> None:
        classes = (attrs_d.get("class") or "").split()
        align = None
        indent = 0
        for cls in classes:
            if cls in _QUILL_ALIGN_CLASS_MAP:
                align = _QUILL_ALIGN_CLASS_MAP[cls]
            if cls.startswith("ql-indent-"):
                try:
                    indent = max(0, min(8, int(cls[len("ql-indent-"):])))
                except ValueError:
                    pass
        block = {"kind": "p", "align": align, "runs": [], "list": None, "indent": indent}
        block.update(self._block_style(attrs_d))
        if list_info is not None:
            block["list"] = {"type": list_info, "level": indent}
            block["indent"] = 0
        self._current_block = block
        self._target.append(block)

    # -- HTMLParser -------------------------------------------------------
    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        a = dict(attrs)
        if tag == "table":
            self._table = {"kind": "table", "rows": []}
            self.blocks.append(self._table)
            self._target = self.blocks
        elif tag == "tr" and self._table is not None:
            self._row = []
            self._table["rows"].append(self._row)
        elif tag in ("td", "th") and self._table is not None:
            if self._row is None:
                self._row = []
                self._table["rows"].append(self._row)
            self._cell = {"blocks": []}
            self._row.append(self._cell)
            self._target = self._cell["blocks"]
            self._current_block = None
            # Quill puts the cell's own line formats on the <td>.
            self._open_block(a)
        elif tag in ("ol", "ul"):
            self._list_stack.append("ordered" if tag == "ol" else "bullet")
        elif tag == "li":
            kind = a.get("data-list")
            if kind not in ("bullet", "ordered", "checked", "unchecked"):
                kind = self._list_stack[-1] if self._list_stack else "bullet"
            kind = "ordered" if kind == "ordered" else "bullet"
            if "ql-indent-" not in (a.get("class") or "") and len(self._list_stack) > 1:
                a = dict(a, **{"class": ((a.get("class") or "") + f" ql-indent-{len(self._list_stack) - 1}").strip()})
            self._open_block(a, list_info=kind)
        elif tag in self._BLOCK_TAGS:
            self._open_block(a)
        elif tag == "span" and "ql-ui" in (a.get("class") or ""):
            self._skip_depth += 1
            self._span_stack.append({"_ui": True})
        elif tag in ("strong", "b", "em", "i", "u", "s", "strike", "del", "sub", "sup", "span"):
            frame = _parse_span_style(a.get("style") or "")
            for t, key, depth in (
                (("strong", "b"), "bold", "bold"), (("em", "i"), "italic", "italic"), (("u",), "underline", "underline"),
                (("s", "strike", "del"), "strike", "strike"), (("sub",), "sub", "sub"), (("sup",), "sup", "sup"),
            ):
                if tag in t:
                    frame[key] = True
            self._span_stack.append(frame)
            for key, depth in (("bold", "bold"), ("italic", "italic"), ("underline", "underline"),
                               ("strike", "strike"), ("sub", "sub"), ("sup", "sup")):
                if frame.get(key):
                    self._depth[depth] += 1
        elif tag == "br":
            self._append_text("\n" if self._soft_breaks else " ")

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in self._BLOCK_TAGS:
            self._drop_lone_break()
            self._current_block = None
        elif tag in ("ol", "ul"):
            if self._list_stack:
                self._list_stack.pop()
        elif tag in ("td", "th"):
            self._drop_lone_break()
            self._cell = None
            self._current_block = None
            self._target = self.blocks
        elif tag == "tr":
            self._row = None
        elif tag == "table":
            self._table, self._row, self._cell = None, None, None
            self._target = self.blocks
            self._current_block = None
        elif tag in ("strong", "b", "em", "i", "u", "s", "strike", "del", "sub", "sup", "span") and self._span_stack:
            frame = self._span_stack.pop()
            if frame.get("_ui"):
                self._skip_depth = max(0, self._skip_depth - 1)
                return
            for key in ("bold", "italic", "underline", "strike", "sub", "sup"):
                if frame.get(key):
                    self._depth[key] = max(0, self._depth[key] - 1)

    def _append_text(self, text: str) -> None:
        if not text or self._skip_depth:
            return
        if self._current_block is None:
            self._open_block({})
        self._current_block["runs"].append(
            {
                "text": text,
                "bold": self._depth["bold"] > 0,
                "italic": self._depth["italic"] > 0,
                "underline": self._depth["underline"] > 0,
                "strike": self._depth["strike"] > 0,
                "sub": self._depth["sub"] > 0 and self._depth["sup"] == 0,
                "sup": self._depth["sup"] > 0,
                "color": self._style_value("color"),
                "highlight": self._style_value("highlight"),
                "size_pt": self._style_value("size_pt"),
                "font": self._style_value("font"),
            }
        )

    def _drop_lone_break(self) -> None:
        """Quill writes an empty line as `<p><br></p>`; that lone break is the
        paragraph being empty, not a line break inside it."""
        block = self._current_block
        if block and self._soft_breaks and block.get("runs") and all(r["text"] == "\n" for r in block["runs"]):
            block["runs"] = []

    def handle_data(self, data):
        self._append_text(data)


def _block_is_blank(block: dict) -> bool:
    if block.get("kind") == "table":
        return not block["rows"]
    return not any(r["text"].strip() for r in block["runs"])


def parse_editor_html(html_text: str, keep_blank: bool = False) -> list:
    """Parses HTML produced by a Quill editor instance into the block list
    `replace_paragraph_range_with_html` consumes. Blank/whitespace-only
    paragraph blocks (Quill's own empty-editor content, `<p><br></p>`) are
    dropped so a fully-cleared editor doesn't insert invisible paragraphs —
    the caller still always gets at least one paragraph back from
    `replace_paragraph_range_with_html` itself. Inside a table cell blank
    paragraphs are kept (a cell may legitimately be empty)."""
    parser = _QuillHtmlParser(soft_breaks=keep_blank)
    parser.feed(html_text or "")
    out = []
    for block in parser.blocks:
        if block.get("kind") == "table":
            rows = []
            for row in block["rows"]:
                cells = []
                for cell in row:
                    inner = [b for b in cell["blocks"] if b["runs"]] or [
                        {"kind": "p", "align": None, "runs": [], "list": None, "indent": 0,
                         "line_height": None, "space_before": None, "space_after": None}
                    ]
                    cells.append({"blocks": inner})
                if cells:
                    rows.append(cells)
            if rows:
                out.append({"kind": "table", "rows": rows})
        elif keep_blank or not _block_is_blank(block):
            if keep_blank and not block["runs"]:
                block = dict(block, runs=[{"text": "", "bold": False, "italic": False, "underline": False,
                                           "strike": False, "sub": False, "sup": False}])
            out.append(block)
    return out


# Word's own highlighter palette (the 15 colours of Home > Text Highlight
# Color) -> python-docx's WD_COLOR_INDEX member Word itself writes for each.
# A highlight chosen in the editor that is exactly one of these is saved as a
# real Word highlight; anything else falls back to run shading.
def _word_highlight_map() -> dict:
    from docx.enum.text import WD_COLOR_INDEX as C

    return {
        "FFFF00": C.YELLOW, "00FF00": C.BRIGHT_GREEN, "00FFFF": C.TURQUOISE, "FF00FF": C.PINK,
        "0000FF": C.BLUE, "FF0000": C.RED, "000080": C.DARK_BLUE, "008080": C.TEAL,
        "008000": C.GREEN, "800080": C.VIOLET, "800000": C.DARK_RED,
        "808000": C.DARK_YELLOW, "808080": C.GRAY_50, "C0C0C0": C.GRAY_25, "000000": C.BLACK,
    }


def set_run_highlight(run, hex_color: str) -> None:
    """Highlights a run: a real Word highlight when `hex_color` is one of
    Word's 15 highlighter colours, otherwise run shading."""
    from docx.oxml import OxmlElement

    r_pr = run._r.get_or_add_rPr()
    for tag in ("w:shd", "w:highlight"):
        for old in r_pr.findall(qn(tag)):
            r_pr.remove(old)
    index = _word_highlight_map().get((hex_color or "").upper())
    if index is not None:
        run.font.highlight_color = index
    else:
        shd = OxmlElement("w:shd")
        shd.set(qn("w:val"), "clear")
        shd.set(qn("w:color"), "auto")
        shd.set(qn("w:fill"), hex_color)
        r_pr.append(shd)


def _apply_extended_run_format(run, run_data: dict) -> None:
    """Applies the optional colour / highlight / size / font a run parsed
    from the editable preview carries — on top of (never instead of) the
    template-copied defaults set just before this call."""
    from docx.shared import Pt, RGBColor

    if run_data.get("font"):
        run.font.name = run_data["font"]
        r_pr = run._r.get_or_add_rPr()
        r_fonts = r_pr.find(qn("w:rFonts"))
        if r_fonts is not None:  # make the face apply to every script, as Word does
            for attr in ("w:hAnsi", "w:cs"):
                r_fonts.set(qn(attr), run_data["font"])
            # a theme font would otherwise win over the face just chosen
            for attr in ("w:asciiTheme", "w:hAnsiTheme", "w:cstheme", "w:eastAsiaTheme"):
                if r_fonts.get(qn(attr)) is not None:
                    del r_fonts.attrib[qn(attr)]
    if run_data.get("size_pt"):
        run.font.size = Pt(run_data["size_pt"])
    if run_data.get("color"):
        run.font.color.rgb = RGBColor.from_string(run_data["color"])
    if run_data.get("highlight"):
        set_run_highlight(run, run_data["highlight"])
    if run_data.get("strike"):
        run.font.strike = True
    if run_data.get("sub"):
        run.font.subscript = True
    if run_data.get("sup"):
        run.font.superscript = True


def _copy_template_run_format(run, template_run) -> None:
    if template_run is None:
        return
    run.font.name = template_run.font.name
    if template_run.font.size is not None:
        run.font.size = template_run.font.size
    try:
        if template_run.font.color is not None and template_run.font.color.type is not None:
            run.font.color.rgb = template_run.font.color.rgb
    except Exception:  # noqa: BLE001 — a theme/no-colour run is fine left uncoloured
        pass


_MANAGED_RUN_PROPS = ("rStyle", "b", "bCs", "i", "iCs", "u", "strike", "dstrike", "vertAlign", "sz", "szCs", "highlight", "shd")


def _base_run_properties(template_run):
    """The template run's own run properties, minus everything the editor
    states explicitly for every run (bold … size, highlight) — what is left
    (theme fonts, language, kerning …) is what keeps the edited text looking
    like the rest of the letter. A theme colour is kept too; a plain colour
    is stated by the editor."""
    if template_run is None:
        return None
    r_pr = template_run._r.find(qn("w:rPr"))
    if r_pr is None:
        return None
    base = copy.deepcopy(r_pr)
    for tag in _MANAGED_RUN_PROPS:
        for el in base.findall(qn("w:" + tag)):
            base.remove(el)
    for el in base.findall(qn("w:color")):
        if not el.get(qn("w:themeColor")):
            base.remove(el)
    return base


def _write_runs(paragraph, runs: list, template_run, inherit_run_format: bool) -> None:
    base_r_pr = None if inherit_run_format else _base_run_properties(template_run)
    for run_data in runs:
        run = paragraph.add_run(run_data["text"])
        if inherit_run_format:
            _copy_template_run_format(run, template_run)
            run.bold = run_data["bold"] or None
            run.italic = run_data["italic"] or None
            run.underline = run_data["underline"] or None
        else:
            # Whole-document edits start from the original run's own
            # properties and state every face explicitly, so a run the user
            # un-bolds does not silently inherit bold from its style.
            if base_r_pr is not None:
                run._r.insert(0, copy.deepcopy(base_r_pr))
            run.bold = bool(run_data["bold"])
            run.italic = bool(run_data["italic"])
            run.underline = bool(run_data["underline"])
        _apply_extended_run_format(run, run_data)


def _apply_block_paragraph_format(paragraph, block: dict) -> None:
    """Indent / line height / space before / space after the toolbar set on a
    block (all optional — absent means the template paragraph's own value)."""
    from docx.shared import Inches, Pt

    fmt = paragraph.paragraph_format
    if block.get("indent"):
        current = fmt.left_indent or 0
        fmt.left_indent = current + Inches(0.5 * block["indent"])
    if block.get("line_height"):
        fmt.line_spacing = block["line_height"]
    if block.get("space_before") is not None:
        fmt.space_before = Pt(block["space_before"])
    if block.get("space_after") is not None:
        fmt.space_after = Pt(block["space_after"])


def _bare_clone(template_el):
    """A copy of a template paragraph keeping only its paragraph properties —
    no runs, hyperlinks, bookmarks, and never a section break. A template
    list item's numbering (and its hanging indent) is removed too, so it does
    not leak into non-list blocks; list blocks get theirs back explicitly."""
    clone_el = copy.deepcopy(template_el)
    for child in list(clone_el):
        if child.tag != qn("w:pPr"):
            clone_el.remove(child)
    p_pr = clone_el.find(qn("w:pPr"))
    if p_pr is not None:
        for sect in p_pr.findall(qn("w:sectPr")):
            p_pr.remove(sect)
        numbered = bool(p_pr.findall(qn("w:numPr")))
        for num in p_pr.findall(qn("w:numPr")):
            p_pr.remove(num)
        if numbered:
            for ind in p_pr.findall(qn("w:ind")):
                p_pr.remove(ind)
    return clone_el


def _plain_cell_paragraph_el():
    from docx.oxml import OxmlElement

    p_el = OxmlElement("w:p")
    p_pr = p_el.get_or_add_pPr()
    spacing = OxmlElement("w:spacing")
    spacing.set(qn("w:before"), "0")
    spacing.set(qn("w:after"), "0")
    p_pr.append(spacing)
    return p_el


def _replace_range(document, first_paragraph, last_paragraph, html_text: str, inherit_run_format: bool = True,
                   keep_template_list: Optional[str] = None, keep_blank: bool = False):
    """Implementation of replace_paragraph_range_with_html; also returns every
    top-level element it inserted (paragraphs and tables, in order).
    `keep_template_list` ("bullet"/"ordered"), when the template paragraph is
    itself a Word list item: list blocks of that type keep the template's own
    numbering and indent instead of getting a new numbering definition."""
    import docx_rich
    from docx.text.paragraph import Paragraph

    blocks = parse_editor_html(html_text, keep_blank=keep_blank)
    if not blocks:
        blocks = [{"kind": "p", "align": None, "runs": [{"text": "", "bold": False, "italic": False, "underline": False}],
                   "list": None, "indent": 0, "line_height": None, "space_before": None, "space_after": None}]

    template_el = first_paragraph._p
    parent = template_el.getparent()
    template_run = first_paragraph.runs[0] if first_paragraph.runs else None

    range_els = []
    el = first_paragraph._p
    while True:
        range_els.append(el)
        if el is last_paragraph._p:
            break
        el = el.getnext()
        if el is None:
            raise DocxBuildError(
                "replace_paragraph_range_with_html: last_paragraph is not reachable by "
                "walking forward from first_paragraph — the two paragraphs given are not "
                "a contiguous range."
            )

    t_ppr = template_el.find(qn("w:pPr"))
    template_numpr = copy.deepcopy(t_ppr.find(qn("w:numPr"))) if t_ppr is not None and t_ppr.find(qn("w:numPr")) is not None else None
    template_ind = copy.deepcopy(t_ppr.find(qn("w:ind"))) if t_ppr is not None and t_ppr.find(qn("w:ind")) is not None else None
    numbering = None
    new_paragraphs: list = []
    new_elements: list = []
    anchor_el = range_els[-1]
    list_state = {"type": None, "num_id": None}

    def numbering_mgr():
        nonlocal numbering
        if numbering is None:
            numbering = docx_rich.numbering_for(document)
        return numbering

    def write_paragraph_block(block, p_el, runs_template_run):
        paragraph = Paragraph(p_el, document)
        paragraph.alignment = _ALIGN_TO_WD[block["align"] or "left"]
        _write_runs(paragraph, block["runs"], runs_template_run, inherit_run_format)
        if block.get("list") and keep_template_list == block["list"]["type"] and template_numpr is not None:
            from docx.shared import Twips

            num_id_el = template_numpr.find(qn("w:numId"))
            ilvl_el = template_numpr.find(qn("w:ilvl"))
            base_level = int(ilvl_el.get(qn("w:val"))) if ilvl_el is not None else 0
            if num_id_el is not None:
                docx_rich.set_paragraph_numbering(p_el, int(num_id_el.get(qn("w:val"))), base_level + block["list"]["level"])
            if template_ind is not None:
                fmt = paragraph.paragraph_format
                if template_ind.get(qn("w:left")):
                    fmt.left_indent = Twips(int(template_ind.get(qn("w:left"))))
                if template_ind.get(qn("w:hanging")):
                    fmt.first_line_indent = Twips(-int(template_ind.get(qn("w:hanging"))))
            list_state["type"] = None
        elif block.get("list"):
            kind = block["list"]["type"]
            if list_state["type"] != kind:
                list_state["type"] = kind
                list_state["num_id"] = (
                    numbering_mgr().bullet_num_id() if kind == "bullet" else numbering_mgr().new_ordered_num_id()
                )
            docx_rich.set_paragraph_numbering(p_el, list_state["num_id"], block["list"]["level"])
        else:
            list_state["type"] = None
        _apply_block_paragraph_format(paragraph, block)
        return paragraph

    for block in blocks:
        if block.get("kind") == "table":
            list_state["type"] = None
            n_cols = max(len(r) for r in block["rows"])
            width = docx_rich.content_width_twips(document, parent)
            tbl = docx_rich.new_table_element(len(block["rows"]), n_cols, width)
            from docx.oxml.ns import qn as _qn

            for r_idx, tr in enumerate(tbl.findall(_qn("w:tr"))):
                row = block["rows"][r_idx] if r_idx < len(block["rows"]) else []
                for c_idx, tc in enumerate(tr.findall(_qn("w:tc"))):
                    cell_blocks = row[c_idx]["blocks"] if c_idx < len(row) else []
                    old_list_state = dict(list_state)
                    list_state.update({"type": None, "num_id": None})
                    # Replace the empty placeholder paragraph with the cell's content.
                    for ph in tc.findall(_qn("w:p")):
                        tc.remove(ph)
                    if not cell_blocks:
                        cell_blocks = [{"kind": "p", "align": None, "runs": [], "list": None, "indent": 0,
                                        "line_height": None, "space_before": None, "space_after": None}]
                    for cb in cell_blocks:
                        cp_el = _plain_cell_paragraph_el()
                        tc.append(cp_el)
                        write_paragraph_block(cb, cp_el, template_run)
                    list_state.update(old_list_state)
            anchor_el.addnext(tbl)
            anchor_el = tbl
            new_elements.append(tbl)
            continue

        clone_el = _bare_clone(template_el)
        anchor_el.addnext(clone_el)
        anchor_el = clone_el
        new_paragraphs.append(write_paragraph_block(block, clone_el, template_run))
        new_elements.append(clone_el)

    for e in range_els:
        parent.remove(e)
    docx_rich.ensure_container_ends_with_paragraph(parent)
    return new_paragraphs, new_elements


def replace_paragraph_range_with_html(document, first_paragraph, last_paragraph, html_text: str) -> list:
    """Replaces a CONTIGUOUS range of existing paragraphs (inclusive,
    `first_paragraph` through `last_paragraph` — e.g. the Europe Cover
    Letter's three free-composed body paragraphs, template indices 8-10)
    with the content of `html_text` (real HTML from a Quill editor
    instance — see `parse_editor_html`), one new paragraph per parsed
    block; real Word lists, tables, line spacing, indents, strike-through,
    sub/superscript and highlights are written as the real Word structures.

    Modeled directly on `clone_and_insert_after`'s own technique (deep-
    clone an existing template element, insert with `.addnext()`): each
    new paragraph is a deep clone of `first_paragraph`'s own XML with its
    runs stripped, so it inherits that paragraph's real style/pPr: page
    position, spacing, and (unless the parsed block's own alignment says
    otherwise) its default alignment — never invented formatting (project
    rule 5). Each new run copies `first_paragraph`'s own first run's font
    name/size/colour, then applies only the parsed run's own formatting on
    top — so the letter's actual font never changes, only what the editor
    itself changed.

    Callers MUST capture every paragraph reference they still need AFTER
    this range into stable Python variables BEFORE calling this —
    python-docx's `document.paragraphs` is a live view whose indices shift
    the moment paragraphs are inserted/removed here.

    Always inserts at least one paragraph (blank, in the first
    paragraph's own style) even if `html_text` parses to zero blocks, so
    the letter never ends up missing a paragraph where the template
    expects one.

    Returns the list of newly-inserted `Paragraph` objects, in order
    (paragraphs inside inserted tables are not included).
    """
    return _replace_range(document, first_paragraph, last_paragraph, html_text, True)[0]


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


# ---------------------------------------------------------------------------
# Editable-preview support (shared by every document engine)
# ---------------------------------------------------------------------------
# The preview of every document is the REAL generated PDF; to let staff edit
# a value right where it is printed, the browser needs each editable value's
# on-page rectangle. The only way to get that exactly right is to read it
# back out of the same LibreOffice rendering: an engine builds a "probe"
# copy of its document in which every editable paragraph/cell is shaded in a
# unique, decodable colour (never shown or served), converts it with the same
# converter, and this module reads the filled rectangles back. Shading
# changes no layout, so each value lands exactly where it does in the real
# PDF. Hotel Voucher shades table cells itself; every letter engine shades
# whole paragraphs through ProbeShader below.

_PROBE_B = 177


def probe_rgb(index: int) -> tuple[int, int, int]:
    return (index % 200 + 20, index // 200 + 20, _PROBE_B)


def shade_element_fill(properties_el, rgb: tuple[int, int, int]) -> None:
    """Sets a w:shd fill on a w:pPr / w:tcPr element (replacing any
    existing shading) — the building block of the layout probe."""
    from docx.oxml import OxmlElement

    for old in properties_el.findall(qn("w:shd")):
        properties_el.remove(old)
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), "%02X%02X%02X" % rgb)
    # Schema order inside w:pPr puts shading before tabs/spacing/ind/jc/rPr…;
    # inside w:tcPr it goes after tcBorders and before noWrap/tcMar/vAlign.
    after = [
        qn("w:" + n) for n in (
            ("tabs", "suppressAutoHyphens", "kinsoku", "wordWrap", "overflowPunct", "topLinePunct",
             "autoSpaceDE", "autoSpaceDN", "bidi", "adjustRightInd", "snapToGrid", "spacing", "ind",
             "contextualSpacing", "mirrorIndents", "suppressOverlap", "jc", "textDirection",
             "textAlignment", "textboxTightWrap", "outlineLvl", "divId", "cnfStyle", "rPr", "sectPr", "pPrChange")
            if properties_el.tag == qn("w:pPr")
            else ("noWrap", "tcMar", "textDirection", "tcFitText", "vAlign", "hideMark")
        )
    ]
    anchor = next((child for child in properties_el if child.tag in after), None)
    if anchor is not None:
        anchor.addprevious(shd)
    else:
        properties_el.append(shd)


class ProbeShader:
    """Collects the editable fields of ONE single-document letter while its
    probe copy is being built. Engines call `shade(key, paragraph)` on each
    editable paragraph BEFORE filling it (an edited value is rebuilt from a
    clone of that paragraph, so the shading carries over to every line of it),
    then pass `.decode()` to read_probe_layout()."""

    def __init__(self):
        self.keys: list = []
        self.aligns: dict = {}
        self.seeds: dict = {}  # whole-document block key -> its original content as Quill HTML
        self.unmatched: list = []  # whole-document edits that matched no block

    @staticmethod
    def _effective_alignment(paragraph) -> str:
        """The paragraph's own alignment as the template states it (directly
        or through its style chain). Read from the .docx rather than guessed
        from the rendered page, because a justified line that fills the
        width looks centred to a position-based guess."""
        al = paragraph.alignment
        style = paragraph.style
        while al is None and style is not None:
            al = style.paragraph_format.alignment
            style = style.base_style
        return {
            WD_ALIGN_PARAGRAPH.CENTER: "center",
            WD_ALIGN_PARAGRAPH.RIGHT: "right",
            WD_ALIGN_PARAGRAPH.JUSTIFY: "justify",
        }.get(al, "left")

    def shade(self, key: str, paragraph) -> None:
        if key not in self.keys:
            self.keys.append(key)
            self.aligns[key] = self._effective_alignment(paragraph)
        shade_element_fill(paragraph._p.get_or_add_pPr(), probe_rgb(self.keys.index(key)))

    def add_block(self, key: str, paragraphs: list, seed_html: Optional[str], align: str = "left") -> None:
        """Registers a whole-document block (document_blocks.finalize): every
        paragraph given is shaded in the block's one colour, so a block that
        is a table (an edit inserted one) is read back as the table's extent."""
        if key not in self.keys:
            self.keys.append(key)
            self.aligns[key] = align
            if seed_html is not None:
                self.seeds[key] = seed_html
        idx = self.keys.index(key)
        for p_el in paragraphs:
            p_pr = p_el.get_or_add_pPr()
            shade_element_fill(p_pr, probe_rgb(idx))

    def decode(self) -> dict:
        return {probe_rgb(i): (0, key) for i, key in enumerate(self.keys)}

    def layout_from_pdf(self, pdf_bytes: bytes) -> dict:
        layout = read_probe_layout(pdf_bytes, self.decode(), 1)
        for key, info in layout["groups"][0].items():
            info["align"] = self.aligns.get(key, info.get("align", "left"))
            if key in self.seeds:
                info["html"] = self.seeds[key]
        layout["unmatched"] = list(self.unmatched)
        return layout


def read_probe_layout(pdf_bytes: bytes, decode: dict, group_count: int = 1) -> dict:
    import ctypes

    import pypdfium2 as pdfium
    import pypdfium2.raw as raw

    doc = pdfium.PdfDocument(pdf_bytes)
    pages = []
    groups = [dict() for _ in range(group_count)]
    try:
        for page_index in range(len(doc)):
            page = doc[page_index]
            width, height = page.get_size()
            pages.append({"width": round(width, 2), "height": round(height, 2)})
            found = {}  # (group, key) -> [left, top, right, bottom] in top-left origin points
            for obj in page.get_objects(filter=[raw.FPDF_PAGEOBJ_PATH]):
                r, g, b, a = (ctypes.c_uint(), ctypes.c_uint(), ctypes.c_uint(), ctypes.c_uint())
                if not raw.FPDFPageObj_GetFillColor(obj.raw, r, g, b, a):
                    continue
                hit = decode.get((r.value, g.value, b.value))
                if hit is None:
                    continue
                left, bottom, right, top = obj.get_bounds()
                if top - bottom < 4 or right - left < 4:
                    # Text underlines/strike-throughs are drawn as thin filled
                    # paths in whatever fill colour was last set — not a field.
                    continue
                rect = [left, height - top, right, height - bottom]
                prev = found.get(hit)
                if prev is None:
                    found[hit] = rect
                else:  # a cell drawn as several fragments: union them
                    found[hit] = [min(prev[0], rect[0]), min(prev[1], rect[1]), max(prev[2], rect[2]), max(prev[3], rect[3])]
            if not found:
                continue
            textpage = page.get_textpage()
            try:
                n_chars = textpage.count_chars()
                char_boxes = []
                for i in range(n_chars):
                    l, b_, r_, t = textpage.get_charbox(i)
                    char_boxes.append((i, l, height - t, r_, height - b_))
                for (h_idx, key), rect in found.items():
                    style = {"fontSize": None, "bold": False, "fontName": "", "align": "left"}
                    inside = [
                        c for c in char_boxes
                        if rect[0] <= (c[1] + c[3]) / 2 <= rect[2] and rect[1] <= (c[2] + c[4]) / 2 <= rect[3] and c[3] - c[1] > 0.1
                    ]
                    if inside:
                        i0 = inside[0][0]
                        style["fontSize"] = round(raw.FPDFText_GetFontSize(textpage.raw, i0), 2)
                        try:
                            style["bold"] = raw.FPDFText_GetFontWeight(textpage.raw, i0) >= 600
                        except Exception:  # noqa: BLE001
                            pass
                        buf = ctypes.create_string_buffer(128)
                        flags = ctypes.c_int()
                        try:
                            raw.FPDFText_GetFontInfo(textpage.raw, i0, buf, 128, flags)
                            style["fontName"] = buf.value.decode("utf-8", "ignore")
                            if "bold" in style["fontName"].lower():
                                style["bold"] = True
                        except Exception:  # noqa: BLE001
                            pass
                        # Alignment from where the first printed line sits in its cell.
                        first_cy = (inside[0][2] + inside[0][4]) / 2
                        line = [c for c in inside if abs((c[2] + c[4]) / 2 - first_cy) < (style["fontSize"] or 10) * 0.5]
                        left_gap = min(c[1] for c in line) - rect[0]
                        right_gap = rect[2] - max(c[3] for c in line)
                        tolerance = max(3.0, (rect[2] - rect[0]) * 0.06)
                        if abs(left_gap - right_gap) <= tolerance:
                            style["align"] = "center"
                        elif right_gap < left_gap - tolerance:
                            style["align"] = "right"
                    if key in groups[h_idx]:
                        continue  # a field spanning pages keeps its first piece
                    groups[h_idx][key] = {
                        "page": page_index,
                        "rect": [round(v, 2) for v in rect],
                        **style,
                    }
            finally:
                textpage.close()
            page.close()
    finally:
        doc.close()
    return {"pages": pages, "groups": groups}
