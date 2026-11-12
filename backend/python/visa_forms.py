"""
Khanna Travels & Holidays — official visa application forms
==========================================================

Fills an embassy's own fillable PDF form (backend/python/visa_forms/) from the
values staff entered on the "Fill Forms" page, and reads the values back out of
a filled form (used by the "Check Forms" page, form_check.py).

One JSON definition per form (visa_forms/<name>.json) says which PDF field holds
which value, what the radio-button states mean, and the house style (capitals,
"-" for not applicable). A new country's form is a new PDF + JSON pair — no new
code — as long as it is a fillable PDF.

Why the XFA part is removed from the filled copy
-------------------------------------------------
The Japan form was made with Adobe LiveCycle: it stores every value twice,
once in ordinary PDF form fields (AcroForm) and once in an XFA data packet.
Adobe Acrobat/Reader shows the XFA copy when it exists, so a file whose
AcroForm fields were filled but whose XFA packet still holds the old values
would show the OLD values in Adobe. The generated copy therefore drops the XFA
packet (the printed page itself is ordinary PDF content and is unchanged) and
keeps the AcroForm fields, so every viewer shows the same values and staff can
still edit any field in Adobe before printing.
"""

from __future__ import annotations

import copy
import io
import json
import os
import re
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Tuple

FORMS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "visa_forms")

_DEFINITION_CACHE: Dict[str, Dict[str, Any]] = {}


class FormError(Exception):
    """A problem staff can act on (unknown form, missing template file)."""


# ---------------------------------------------------------------------------
# Definitions
# ---------------------------------------------------------------------------


def _load_all() -> Dict[str, Dict[str, Any]]:
    if _DEFINITION_CACHE:
        return _DEFINITION_CACHE
    if not os.path.isdir(FORMS_DIR):
        return _DEFINITION_CACHE
    for name in sorted(os.listdir(FORMS_DIR)):
        if not name.lower().endswith(".json"):
            continue
        with open(os.path.join(FORMS_DIR, name), "r", encoding="utf-8") as fh:
            definition = json.load(fh)
        _DEFINITION_CACHE[definition["id"]] = definition
    return _DEFINITION_CACHE


def reset_cache_for_tests() -> None:
    _DEFINITION_CACHE.clear()


def list_forms() -> List[Dict[str, Any]]:
    """Every available form, with its full field list (the page builds its
    inputs from this). The PDF field names stay on the server."""
    out = []
    for definition in _load_all().values():
        public = copy.deepcopy(definition)
        public.pop("identify", None)
        public["available"] = os.path.isfile(template_path(definition))
        for section in public.get("sections", []):
            for field in section.get("fields", []):
                field.pop("pdf", None)
                field.pop("pdfParts", None)
                for opt in field.get("options", []) or []:
                    opt.pop("state", None)
        out.append(public)
    return out


def get_definition(form_id: str) -> Dict[str, Any]:
    definition = _load_all().get(form_id)
    if not definition:
        raise FormError(f"Unknown form '{form_id}'.")
    return definition


def template_path(definition: Dict[str, Any]) -> str:
    return os.path.join(FORMS_DIR, definition["file"])


def iter_fields(definition: Dict[str, Any]):
    for section in definition.get("sections", []):
        for field in section.get("fields", []):
            yield field


def pdf_names(field: Dict[str, Any]) -> List[str]:
    """Every PDF field one definition field writes to: one name, a list of
    rows (a long name over two rows of letter boxes) or the three
    DD / MM / YYYY box groups of a date."""
    names: List[str] = []
    pdf = field.get("pdf")
    if isinstance(pdf, list):
        names.extend(pdf)
    elif pdf:
        names.append(pdf)
    names.extend(field.get("pdfParts") or [])
    return names


def split_rows(text: str, row_lengths: List[int]) -> Tuple[List[str], str]:
    """Spreads text over rows of letter boxes, breaking between words when
    possible. Returns (rows, what did not fit)."""
    words = (text or "").split()
    rows: List[str] = []
    for length in row_lengths:
        row = ""
        while words:
            word = words[0]
            candidate = (row + " " + word) if row else word
            if len(candidate) <= length:
                row = candidate
                words.pop(0)
            elif not row and len(word) > length:
                row, words[0] = word[:length], word[length:]
                break
            else:
                break
        rows.append(row)
    return rows, " ".join(words)


# ---------------------------------------------------------------------------
# Value formatting
# ---------------------------------------------------------------------------

_DATE_PATTERNS = ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%d.%m.%Y", "%d %m %Y")


def parse_any_date(value: str) -> Optional[date]:
    text = (value or "").strip()
    if not text:
        return None
    for pattern in _DATE_PATTERNS:
        try:
            return datetime.strptime(text, pattern).date()
        except ValueError:
            continue
    return None


def format_date(value: str, pattern: str) -> str:
    """ISO or DD-MM-YYYY in, the form's own pattern out. Anything that is
    not a date (e.g. "-") is passed through unchanged."""
    parsed = parse_any_date(value)
    if not parsed:
        return (value or "").strip()
    sep = "/" if "/" in pattern else "-" if "-" in pattern else "."
    return f"{parsed.day:02d}{sep}{parsed.month:02d}{sep}{parsed.year:04d}"


_NOT_APPLICABLE = {"NA", "N/A", "-", "NOT APPLICABLE"}


def _to_form_letters(text: str) -> str:
    """Letters the form's font can print: accents are dropped ("CHŪŌ" -> "CHUO"),
    curly quotes / dashes become plain ones."""
    import unicodedata

    text = text.replace("\u2019", "'").replace("\u2018", "'").replace("\u201c", '"').replace("\u201d", '"')
    text = text.replace("\u2013", "-").replace("\u2014", "-")
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")


def _clean_text(value: Any, upper: bool) -> str:
    text = _to_form_letters("" if value is None else str(value))
    text = re.sub(r"[ \t]+", " ", text.replace("\r\n", "\n").replace("\r", "\n")).strip()
    return text.upper() if upper else text


# ---------------------------------------------------------------------------
# Field-name helpers (pypdf)
# ---------------------------------------------------------------------------


def qualified_name(obj) -> str:
    parts: List[str] = []
    node = obj
    seen = 0
    while node is not None and seen < 50:
        seen += 1
        if "/T" in node:
            parts.append(str(node["/T"]))
        parent = node.get("/Parent")
        node = parent.get_object() if parent is not None else None
    return ".".join(reversed(parts))


def _field_type(widget) -> Optional[str]:
    node = widget
    for _ in range(50):
        if node is None:
            return None
        if "/FT" in node:
            return str(node["/FT"])
        parent = node.get("/Parent")
        node = parent.get_object() if parent is not None else None
    return None


def _widgets_by_name(pages) -> Dict[str, List[Any]]:
    """Fully-qualified field name -> its widget annotations (a radio group
    has one widget per button, all children of the one named field)."""
    found: Dict[str, List[Any]] = {}
    for page in pages:
        for ref in page.get("/Annots", []) or []:
            widget = ref.get_object()
            if widget.get("/Subtype") != "/Widget":
                continue
            found.setdefault(qualified_name(widget), []).append(widget)
    return found


def _on_states(widget) -> List[str]:
    ap = widget.get("/AP")
    if not ap:
        return []
    normal = ap.get_object().get("/N")
    if normal is None:
        return []
    normal = normal.get_object()
    if not hasattr(normal, "keys"):
        return []
    return [str(k) for k in normal.keys() if str(k) != "/Off" and str(k).startswith("/") and str(k) not in (
        "/Type", "/Subtype", "/FormType", "/BBox", "/Matrix", "/Resources", "/Filter", "/Length")]


# ---------------------------------------------------------------------------
# Place-of-birth style "columns" (one PDF field printed under 3 sub-labels)
# ---------------------------------------------------------------------------

# Myriad Pro / Helvetica-like average advance widths (per 1000 em) — enough to
# line text up under the form's printed "(City)  (State)  (Country)" labels.
_NARROW = set("iIl.,:;'|!")
_WIDE = set("MWmw@")


def _approx_width(text: str, size: float) -> float:
    total = 0.0
    for ch in text:
        if ch == " ":
            total += 212
        elif ch in _NARROW:
            total += 240
        elif ch in _WIDE:
            total += 800
        elif ch.isupper() or ch.isdigit():
            total += 600
        else:
            total += 500
    return total * size / 1000.0


def compose_columns(parts: List[Tuple[str, float]], font_size: float = 11.0) -> str:
    """[(text, x_offset_pt), ...] -> one string padded with spaces so each
    part starts near its offset inside the field."""
    out = ""
    space = _approx_width(" ", font_size)
    for text, offset in parts:
        text = (text or "").strip()
        if not text:
            continue
        current = _approx_width(out, font_size)
        gap = max(1 if out else 0, int(round((offset - current) / space)))
        out += " " * gap + text
    return out


# ---------------------------------------------------------------------------
# Fitting long text inside a field (wrap onto the next line / smaller font)
# ---------------------------------------------------------------------------

MIN_FONT_SIZE = 6.0
TEXT_LIFT = 2.0  # points between written text and the printed line below it
DEFAULT_FONT_SIZE = 11.0
_MULTILINE_FLAG = 1 << 12

# Line answers that start on the LOWEST printed line when they are short (an
# address whose printed line is at the bottom, with free space above it).
# Line answers that use the printed (lowest) line when they are short: a
# short address sits on the "Address:" line; a longer one starts on the free
# line above and continues on the printed line, both left-aligned.
LINE_ROWS_FROM_BOTTOM = {"originAddress"}
_COMB_FLAG = 1 << 24


class FontMetrics:
    """Advance widths (per 1000 em) and line spacing of the form's own font,
    read from the PDF itself, so text is measured the way it will be drawn."""

    def __init__(self, widths: Dict[int, float], default_width: float, leading: float):
        self.widths = widths
        self.default_width = default_width
        self.leading = leading  # line height as a multiple of the font size

    def width(self, text: str, size: float) -> float:
        return sum(self.widths.get(ord(ch), self.default_width) for ch in text) * size / 1000.0


def font_metrics(acroform, font_name: str) -> FontMetrics:
    try:
        font = acroform["/DR"]["/Font"][font_name].get_object()
        first = int(font.get("/FirstChar", 0))
        widths = {first + i: float(w) for i, w in enumerate(font.get("/Widths", []))}
        descriptor = font.get("/FontDescriptor")
        bbox = descriptor.get_object().get("/FontBBox") if descriptor is not None else None
        leading = (float(bbox[3]) - float(bbox[1])) / 1000.0 if bbox else 1.2
        if widths:
            return FontMetrics(widths, sum(widths.values()) / len(widths), max(leading, 1.0))
    except Exception:  # noqa: BLE001 — fall back to Helvetica-like widths
        pass
    return FontMetrics({32: 278}, 556, 1.2)


def _split_long_word(word: str, max_width: float, size: float, metrics: FontMetrics) -> List[str]:
    pieces, current = [], ""
    for ch in word:
        if current and metrics.width(current + ch, size) > max_width:
            pieces.append(current)
            current = ch
        else:
            current += ch
    if current:
        pieces.append(current)
    return pieces


def wrap_text(text: str, max_width: float, size: float, metrics: FontMetrics) -> List[str]:
    """Breaks text into lines no wider than max_width: between words where
    possible, inside a word only when one word alone is too long."""
    lines: List[str] = []
    for paragraph in (text or "").split("\n"):
        words = paragraph.split()
        if not words:
            lines.append("")
            continue
        current = ""
        for word in words:
            candidate = (current + " " + word) if current else word
            if metrics.width(candidate, size) <= max_width:
                current = candidate
                continue
            if current:
                lines.append(current)
            if metrics.width(word, size) <= max_width:
                current = word
            else:
                pieces = _split_long_word(word, max_width, size, metrics)
                lines.extend(pieces[:-1])
                current = pieces[-1] if pieces else ""
        lines.append(current)
    return lines


def fit_text(text: str, box_width: float, box_height: float, multiline: bool, metrics: FontMetrics,
             base_size: float = DEFAULT_FONT_SIZE, min_size: float = MIN_FONT_SIZE) -> Tuple[List[str], float, bool]:
    """(lines, font size, fits). Keeps the form's normal size when the text
    fits; otherwise wraps onto further lines (multi-line boxes) and steps the
    size down until everything fits inside the box. `fits` is False only when
    even the smallest size cannot hold it all — the caller tells staff."""
    width = max(box_width - 4, 10)   # the viewer's own inner margins
    height = max(box_height - 2, 4)
    size = base_size
    while True:
        if multiline:
            lines = wrap_text(text, width, size, metrics)
            ok = len(lines) * size * metrics.leading <= height + 0.5 or (len(lines) == 1 and metrics.width(lines[0], size) <= width)
        else:
            lines = [re.sub(r"\s+", " ", text or "").strip()]
            ok = metrics.width(lines[0], size) <= width
        if ok:
            return lines, size, True
        if size <= min_size:
            return lines, min_size, False
        size = max(min_size, round(size - 0.5, 1))


def _da_parts(da: str) -> Tuple[str, float, str]:
    """'/MyriadPro-Regular 11.00 Tf 0 g' -> ('/MyriadPro-Regular', 11.0, '0 g')."""
    match = re.search(r"(/[^\s]+)\s+([\d.]+)\s+Tf", da or "")
    if not match:
        return "/Helv", DEFAULT_FONT_SIZE, "0 g"
    color = (da[: match.start()] + da[match.end():]).strip() or "0 g"
    size = float(match.group(2)) or DEFAULT_FONT_SIZE
    return match.group(1), size, color


# ---------------------------------------------------------------------------
# Filling
# ---------------------------------------------------------------------------


def build_field_values(definition: Dict[str, Any], values: Dict[str, Any]) -> Tuple[Dict[str, str], Dict[str, str], List[str], List[str]]:
    """Staff values -> (text values by PDF name, radio states by PDF name,
    list of required fields still empty, fields cut short because they are
    longer than their letter boxes)."""
    upper = definition.get("uppercase", True)
    texts: Dict[str, str] = {}
    radios: Dict[str, str] = {}
    missing: List[str] = []
    cut: List[str] = []
    line_rows: Dict[str, Tuple[List[str], str, str]] = {}
    for field in iter_fields(definition):
        key = field["key"]
        kind = field.get("type", "text")
        pdf_name = field.get("pdf")
        if kind == "date" and field.get("pdfParts"):
            # DD / MM / YYYY written in three groups of boxes.
            parsed = parse_any_date(str(values.get(key) or ""))
            day, month, year = field["pdfParts"]
            if parsed:
                texts[day], texts[month], texts[year] = f"{parsed.day:02d}", f"{parsed.month:02d}", f"{parsed.year:04d}"
            else:
                texts[day] = texts[month] = texts[year] = ""
                if field.get("required"):
                    missing.append(field["label"])
            continue
        if isinstance(pdf_name, list) and field.get("rows") == "lines":
            # One answer written over several printed lines: split by width
            # in fill_form (it needs the real width of each line).
            text = _clean_text(values.get(key), upper)
            line_rows[key] = (list(pdf_name), text, field["label"])
            for name in pdf_name:
                texts[name] = ""
            if not text and field.get("required"):
                missing.append(field["label"])
            continue
        if isinstance(pdf_name, list):
            # One answer over several rows of letter boxes (a long name).
            text = _clean_text(values.get(key), upper)
            rows, rest = split_rows(text, [int(n) for n in field.get("rowLength", [25] * len(pdf_name))]
                                    if isinstance(field.get("rowLength"), list) else [int(field.get("rowLength", 25))] * len(pdf_name))
            for name, row in zip(pdf_name, rows):
                texts[name] = row
            if rest:
                cut.append(field["label"])
            if not text and field.get("required"):
                missing.append(field["label"])
            continue
        if not pdf_name:
            continue
        if kind in ("radio", "yesno"):
            chosen = str(values.get(key) or "").strip()
            option = next((o for o in field.get("options", []) if o["value"].lower() == chosen.lower()), None)
            if option:
                radios[pdf_name] = option["state"]
            elif field.get("required"):
                missing.append(field["label"])
            continue
        if kind == "columns":
            parts = []
            for part in field.get("parts", []):
                parts.append((_clean_text(values.get(part["key"]), upper), float(part.get("offset", 0))))
            text = compose_columns(parts)
            if not text.strip() and field.get("required"):
                missing.append(field["label"])
            texts[pdf_name] = text
            continue
        raw = values.get(key)
        if kind == "date":
            text = format_date(str(raw or ""), field.get("dateFormat", "DD/MM/YYYY"))
        else:
            text = _clean_text(raw, upper)
        max_len = field.get("maxLength")
        if max_len and len(text) > max_len:
            text = text[: int(max_len)]
            if field.get("boxes"):
                cut.append(field["label"])
        if not text and field.get("required"):
            missing.append(field["label"])
        texts[pdf_name] = text
    return texts, radios, missing, cut, line_rows


def fill_form(form_id: str, values: Dict[str, Any]) -> Tuple[bytes, List[str], List[str]]:
    """Returns (filled PDF bytes, required fields left empty, fields whose
    text is too long to fit even at the smallest size). Neither stops the
    PDF — staff may want to finish by hand — but the caller shows both.

    Long text never runs off the printed line: a multi-line box (addresses)
    continues on the next line, and any box whose text is still too long
    uses a smaller font until it fits."""
    from pypdf import PdfReader, PdfWriter
    from pypdf.generic import ArrayObject, BooleanObject, FloatObject, NameObject, NumberObject, TextStringObject

    definition = get_definition(form_id)
    path = template_path(definition)
    if not os.path.isfile(path):
        raise FormError(f"The blank form file '{definition['file']}' is missing from backend/python/visa_forms.")

    texts, radios, missing, cut, line_rows = build_field_values(definition, values or {})

    writer = PdfWriter(clone_from=PdfReader(path))
    acroform = writer._root_object["/AcroForm"]
    if "/XFA" in acroform:
        del acroform["/XFA"]  # see module docstring
    acroform[NameObject("/NeedAppearances")] = BooleanObject(True)

    widgets = _widgets_by_name(writer.pages)

    # Answers written over several printed lines: wrap at the lines' width
    # (smaller letters only if the text would not fit on the lines).
    for key, (names, text, label) in line_rows.items():
        if not text:
            continue
        boxes = [w[0] for w in (widgets.get(n) for n in names) if w]
        if not boxes:
            continue
        font_name, base_size, color = _da_parts(str(boxes[0].get("/DA") or acroform.get("/DA") or ""))
        metrics = font_metrics(acroform, font_name)
        width = min(abs(float(b["/Rect"][2]) - float(b["/Rect"][0])) for b in boxes) - 4
        size = base_size
        while True:
            lines = wrap_text(text, width, size, metrics)
            if len(lines) <= len(boxes) or size <= MIN_FONT_SIZE:
                break
            size = max(MIN_FONT_SIZE, round(size - 0.5, 1))
        if len(lines) > len(boxes):
            lines = lines[: len(boxes) - 1] + [" ".join(lines[len(boxes) - 1:])]
            cut.append(label)
        if len(lines) < len(boxes) and key in LINE_ROWS_FROM_BOTTOM:
            # A short address sits on the printed line; a long one starts on
            # the free line above and continues on the printed line.
            lines = [""] * (len(boxes) - len(lines)) + lines
        for name, line in zip(names, lines + [""] * len(boxes)):
            texts[name] = line
        if size != base_size:
            for b in boxes:
                b[NameObject("/DA")] = TextStringObject(f"{font_name} {size:.1f} Tf {color}")
    centered = {n for f in iter_fields(definition) if f.get("align") == "center" for n in pdf_names(f)}

    # Radio groups: the group's value plus each button's on/off look.
    for name, state in radios.items():
        buttons = widgets.get(name) or []
        if not buttons:
            continue
        parent_ref = buttons[0].get("/Parent")
        group = parent_ref.get_object() if parent_ref is not None and "/T" not in buttons[0] else buttons[0]
        group[NameObject("/V")] = NameObject(state)
        for button in buttons:
            button[NameObject("/AS")] = NameObject(state if state in _on_states(button) else "/Off")

    # Text fields: value set on the field, appearance drawn by pypdf (and
    # redrawn by Adobe because of NeedAppearances).
    by_page: Dict[int, Dict[str, str]] = {}
    for page_index, page in enumerate(writer.pages):
        names = set()
        for ref in page.get("/Annots", []) or []:
            widget = ref.get_object()
            if widget.get("/Subtype") == "/Widget":
                names.add(qualified_name(widget))
        for name, text in texts.items():
            if name in names:
                by_page.setdefault(page_index, {})[name] = text

    labels = {n: f["label"] for f in iter_fields(definition) for n in pdf_names(f)}
    overflow: List[str] = list(cut)
    for page_index, mapping in by_page.items():
        page = writer.pages[page_index]
        for name in list(mapping):
            for widget in widgets.get(name, []):
                if name in centered:
                    widget[NameObject("/Q")] = NumberObject(1)
                text = mapping[name]
                if text:
                    parent_ref = widget.get("/Parent")
                    parent = parent_ref.get_object() if parent_ref is not None else None
                    da = widget.get("/DA") or (parent.get("/DA") if parent is not None else None) or acroform.get("/DA") or ""
                    font_name, base_size, color = _da_parts(str(da))
                    flags = int(widget.get("/Ff", parent.get("/Ff", 0) if parent is not None else 0) or 0)
                    if flags & _COMB_FLAG:
                        # One letter per printed box: the size and place are fixed by
                        # the boxes, so no wrapping, shrinking or lifting.
                        max_len = int(widget.get("/MaxLen", 0) or 0)
                        if text.strip() in _NOT_APPLICABLE and max_len > len(text.strip()):
                            # "Not applicable" written in the middle of the row, as by hand.
                            mapping[name] = text = " " * ((max_len - len(text.strip())) // 2) + text.strip()
                        if max_len and len(text) > max_len:
                            mapping[name] = text[:max_len]
                            if labels.get(name) not in overflow:
                                overflow.append(labels.get(name, name))
                        continue
                    multiline = bool(flags & _MULTILINE_FLAG)
                    rect = [float(x) for x in widget["/Rect"]]
                    lines, size, fits = fit_text(text, abs(rect[2] - rect[0]), abs(rect[3] - rect[1]), multiline,
                                                 font_metrics(acroform, font_name), base_size=base_size)
                    if size != base_size:
                        widget[NameObject("/DA")] = TextStringObject(f"{font_name} {size:.1f} Tf {color}")
                    # A little space between the written text and the printed
                    # line under it: the box is moved up by TEXT_LIFT points
                    # (every viewer then draws the text that much higher).
                    widget[NameObject("/Rect")] = ArrayObject(
                        [FloatObject(rect[0]), FloatObject(rect[1] + TEXT_LIFT), FloatObject(rect[2]), FloatObject(rect[3] + TEXT_LIFT)]
                    )
                    if multiline:
                        mapping[name] = "\n".join(lines)
                    if not fits and labels.get(name) not in overflow:
                        overflow.append(labels.get(name, name))
                if _field_type(widget) == "/Ch":
                    # Editable combo box (Nationality): the typed value is used as is.
                    widget[NameObject("/V")] = TextStringObject(mapping[name])
        writer.update_page_form_field_values(page, mapping, auto_regenerate=False)

    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue(), missing, overflow


# ---------------------------------------------------------------------------
# Reading a filled form back (for the Check Forms page)
# ---------------------------------------------------------------------------


def identify_form(field_names) -> Optional[Dict[str, Any]]:
    names = set(field_names)
    for definition in _load_all().values():
        marks = definition.get("identify") or []
        if marks and all(m in names for m in marks):
            return definition
    return None


def read_known_form(definition: Dict[str, Any], pdf_values: Dict[str, str]) -> List[Dict[str, Any]]:
    """pdf_values: qualified field name -> raw value ('/1' for a radio).
    Returns one entry per definition field: {key, label, value, compare}."""
    rows = []
    for field in iter_fields(definition):
        name = field.get("pdf")
        if field.get("pdfParts"):
            parts = [(pdf_values.get(n) or "").strip() for n in field["pdfParts"]]
            raw = "/".join(parts) if all(parts) else ""
        elif isinstance(name, list):
            raw = " ".join((pdf_values.get(n) or "").strip() for n in name).strip()
        elif name:
            raw = (pdf_values.get(name) or "").strip()
        else:
            continue
        kind = field.get("type", "text")
        value = raw
        if kind in ("radio", "yesno"):
            option = next((o for o in field.get("options", []) if o.get("state") == raw), None)
            value = option["label"] if option else ""
        rows.append({
            "key": field["key"],
            "label": field["label"],
            "value": re.sub(r"\s+", " ", value).strip(),
            "compare": field.get("compare") or "",
            "type": kind,
        })
    return rows
