"""
Khanna Travels & Holidays — Hotel Voucher document generator
==============================================================

Generates the company's actual "Hotel Voucher" document for one or more
hotel bookings on an Application, using the real, unmodified reference
template as the exact source of truth for layout, fonts, colours and the
company letterhead/footer (project rule 5 — "Document Template Rule").

Source of truth (read-only, NEVER modified by this module):
    reference-hotel-blocking-formats/Single Hotel/Hotel Booking Format.docx

For more than one hotel, the template's own "HOTEL VOUCHER" heading + table
block is cloned once per additional hotel. This exactly mirrors how the
real reference-hotel-blocking-formats/Multiple Hotels/ example itself
repeats that identical block per hotel (verified by inspecting that file
directly) — so a 3-hotel voucher generated here has the same structure as
the agency's own real 3-hotel example, not an approximation of it.

Only the applicant/booking data changes per block: hotel name, address,
city, phone, lead guest, room/guest counts, check-in/out dates, nights,
confirmation number and the guest-name list. Everything else — the red
"HOTEL VOUCHER" heading, the "Booking details" table structure, the hotel
policy text, the header/footer letterhead images — comes through untouched
because we only ever edit specific cells' text runs, never rebuild the
document from scratch.

Frontend rework, Phase 4 (Word-like body editor): every one of those
per-block generated VALUES above (never the fixed labels/headings/policy
text around them) is independently editable, real rich text, via the
shared Quill-based editor (js/body-editor.js) — see
`compose_hotel_editable_fields()` for the exact field list and
`_apply_field()`/`_fill_hotel_block()`'s `edited_fields` parameter for how
an edited field is written back using the SAME
`docx_utils.replace_paragraph_range_with_html` primitive the Europe Cover
Letter editor proved out. Editing a table cell's own paragraphs never
requires the stable-paragraph-reference dance that body-level paragraph
edits do — `document.paragraphs` never descends into table cells, so
touching one cell can never shift another cell's or the document body's
paragraph indices.
"""

from __future__ import annotations

import copy
import io
import os
from datetime import datetime
from typing import Optional

from docx import Document
from docx.table import Table

import document_blocks
import docx_utils

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATE_PATH = os.path.normpath(
    os.path.join(
        _THIS_DIR,
        "..",
        "..",
        "reference-hotel-blocking-formats",
        "Single Hotel",
        "Hotel Booking Format.docx",
    )
)


class HotelVoucherError(docx_utils.DocxBuildError):
    """Raised whenever a voucher genuinely cannot be generated — never
    swallowed to produce a fake/empty document (project rule 9). Subclasses
    the shared DocxBuildError so callers that only catch the shared type
    (e.g. a future generic document endpoint) still see it, while existing
    callers that catch HotelVoucherError specifically are unaffected."""


def _load_template() -> Document:
    if not os.path.isfile(TEMPLATE_PATH):
        raise HotelVoucherError(
            "Hotel voucher reference template not found at "
            f"{TEMPLATE_PATH}. This file is part of the project's read-only "
            "reference material (reference-hotel-blocking-formats/) and must "
            "already exist on this machine — it is never created by this app."
        )
    # Document() only reads this file; nothing is ever written back to it.
    return Document(TEMPLATE_PATH)


def _find_hotel_block_table(document: Document):
    """Locates the template's single self-contained "HOTEL VOUCHER" block.
    In the reference file this is ONE top-level table whose single cell
    nests both the red "HOTEL VOUCHER" heading paragraph and the wrapper
    table holding everything else — not a heading paragraph sitting as a
    separate sibling before the table (verified directly against the
    template's own XML: document.paragraphs has no "HOTEL VOUCHER" text at
    all, because it lives nested inside the table cell). Cloning this one
    table element whole is therefore enough to duplicate an entire block.
    Fails loudly (not silently) if the reference template's structure ever
    changes in a way this engine can't safely handle — an honest error
    beats a wrong document."""
    if not document.tables:
        raise HotelVoucherError(
            "Hotel voucher template structure has changed (no table found) — "
            "cannot safely generate a voucher. Check reference-hotel-blocking-"
            "formats/Single Hotel/Hotel Booking Format.docx."
        )
    table = document.tables[0]
    try:
        heading_text = table.rows[0].cells[0].paragraphs[0].text.strip()
    except IndexError:
        heading_text = ""
    if heading_text != "HOTEL VOUCHER":
        raise HotelVoucherError(
            "Hotel voucher template structure has changed (expected the first "
            "table's first cell to start with a 'HOTEL VOUCHER' heading, found "
            f"{heading_text!r}) — cannot safely generate a voucher. Check "
            "reference-hotel-blocking-formats/Single Hotel/Hotel Booking Format.docx."
        )
    return table._tbl


_set_paragraph_text = docx_utils.set_paragraph_text
_set_cell_text = docx_utils.set_cell_text
_replace_token_in_cell = docx_utils.replace_token_in_cell


def _set_guest_names(cell, names: list[str]) -> None:
    """Fills the guest-name cell with one paragraph per name, adding or
    removing paragraphs (cloned from the cell's own first paragraph, so
    formatting matches) to fit however many names were supplied."""
    if not names:
        names = ["—"]

    # The template cell holds two numbered example lines plus an unnumbered
    # spacer paragraph. Every guest must look like the template's FIRST
    # numbered line (same list numbering, font and size), so keep only that
    # line and clone it once per additional name — otherwise a 3rd guest would
    # land in the spacer paragraph, unnumbered and in a different font.
    for extra in cell.paragraphs[1:]:
        extra._p.getparent().remove(extra._p)
    template_p = cell.paragraphs[0]._p
    for _ in range(len(names) - 1):
        new_p = copy.deepcopy(template_p)
        cell.paragraphs[-1]._p.addnext(new_p)

    for i, name in enumerate(names):
        _set_paragraph_text(cell.paragraphs[i], name or "—")


def _all_guest_names(hotel: dict) -> list[str]:
    """Every guest for the voucher's guest table: the lead guest FIRST, then
    each name added through "Add guest name +". A name already present (e.g.
    the lead guest typed again, or the same name read from an uploaded
    voucher) is listed once — compared ignoring case and extra spaces."""
    names: list[str] = []
    seen: set[str] = set()
    for raw in [hotel.get("leadGuestName")] + list(hotel.get("guestNames") or []):
        name = " ".join(str(raw or "").split())
        key = name.casefold()
        if name and key not in seen:
            seen.add(key)
            names.append(name)
    return names or ["—"]


def _fmt_date(value: Optional[str]) -> str:
    if not value:
        return "—"
    try:
        return datetime.strptime(value, "%Y-%m-%d").strftime("%d %b %Y")
    except ValueError:
        return str(value)  # show whatever was given rather than hide it


def _format_guest_counts(hotel: dict) -> str:
    """Combines the (explicitly split, on request) adults/children counts
    into one "2 Adult(s), 2 Child(s)"-style string for both cells that used
    to just print the single, undifferentiated noOfGuests value. Children
    is only appended when a real, non-zero count was actually entered — a
    booking with no children shouldn't print "0 Child(s)"."""
    adults = str(hotel.get("noOfAdults") or "").strip()
    children = str(hotel.get("noOfChildren") or "").strip()
    parts = []
    if adults:
        parts.append(f"{adults} Adult(s)")
    if children and children != "0":
        parts.append(f"{children} Child(s)")
    return ", ".join(parts) if parts else "—"


def _guest_total(hotel: dict) -> str:
    """Just the NUMBER of guests (adults + children, no "Adult(s)" wording) —
    for the upper Booking-details box. Falls back to the older single
    noOfGuests value when no adults/children split was entered."""
    def _to_int(v):
        try:
            return int(str(v).strip())
        except (TypeError, ValueError):
            return None
    adults, children = _to_int(hotel.get("noOfAdults")), _to_int(hotel.get("noOfChildren"))
    if adults is not None or children is not None:
        return str((adults or 0) + (children or 0))
    legacy = _to_int(hotel.get("noOfGuests"))
    return str(legacy) if legacy is not None else "—"


def _nights(check_in: Optional[str], check_out: Optional[str]) -> Optional[int]:
    try:
        d1 = datetime.strptime(check_in, "%Y-%m-%d").date()
        d2 = datetime.strptime(check_out, "%Y-%m-%d").date()
        n = (d2 - d1).days
        return n if n >= 0 else None
    except (ValueError, TypeError):
        return None


def _hotel_field_plain_values(hotel: dict) -> dict:
    """Computes the plain-text (pre-HTML-escaping) value every editable
    field would auto-render as, from the SAME formatting helpers
    `_fill_hotel_block` itself uses (`_fmt_date`, `_format_guest_counts`,
    `_nights`) — so the Word-like editor's seeded text is always guaranteed
    to match what a non-edited generation would have produced (never two
    copies of the same formatting logic, project rule 15). `guest_names` is
    the one multi-line field, returned as a list of lines rather than a
    single string.

    This is every field the real reference template's own booking/guest
    tables actually vary per hotel (see module docstring's own "Only the
    applicant/booking data changes per block" list) — the two genuinely
    static "Hotel Policy" sentences are deliberately NOT included here: they
    never vary with `hotel`, so they are fixed template content (project
    rule 5), not generated content, and stay completely out of scope for
    this editor."""
    nights = _nights(hotel.get("checkIn"), hotel.get("checkOut"))
    guest_names = _all_guest_names(hotel)
    nights_text = f"{nights} Night(s)" if nights is not None else "—"
    return {
        # The template's own three text runs of this sentence (see
        # `_set_confirmation_sentence`), used to seed the editor faithfully.
        "confirmationFirstLine": 'Thanks for booking with us, your booking has been "',
        "confirmationBoldTail": "Confirmed” with",
        "confirmationLabel": "Confirmation Number- ",
        "confirmationNumber": str(hotel.get("confirmationNumber") or "—"),
        "confirmationSentence": (
            'Thanks for booking with us, your booking has been "Confirmed" with '
            f'Confirmation Number- {hotel.get("confirmationNumber") or "—"}'
        ),
        "hotelName": hotel.get("hotelName") or "—",
        "leadGuestName": hotel.get("leadGuestName") or "—",
        "guestCounts": _format_guest_counts(hotel),
        "noOfRooms": str(hotel.get("noOfRooms") or "—"),
        "phone": hotel.get("phone") or "—",
        "checkIn": _fmt_date(hotel.get("checkIn")),
        "checkOut": _fmt_date(hotel.get("checkOut")),
        "nights": nights_text,
        # The upper Booking-details box shows the plain NUMBER of guests under
        # a "No. of Guest(s):" label (staff request — the template's own label
        # is "No Guest:"); the guest table below keeps the full "4 Adult(s)".
        "guestTotal": _guest_total(hotel),
        "city": hotel.get("city") or "—",
        "address": hotel.get("address") or "—",
        "guestNames": guest_names,
        "roomType": hotel.get("roomType") or "—",
    }


_HOTEL_EDITABLE_FIELD_KEYS = (
    "confirmationSentence",
    "hotelName",
    "leadGuestName",
    "guestTotal",
    "guestCounts",
    "noOfRooms",
    "phone",
    "checkIn",
    "checkOut",
    "nights",
    "city",
    "address",
    "guestNames",
    "roomType",
)


def compose_hotel_editable_fields(hotel: dict) -> dict:
    """The Word-like body editor's seed values for ONE hotel block, as real
    Quill-ready HTML — the exact same shared-compose-function pattern the
    Europe Cover Letter's `compose_europe_body_html` established: this is
    the ONLY place that turns `hotel` into these fields' display text, used
    by both the real generator (`_fill_hotel_block`, for its un-edited
    default) and the `/compose-fields` endpoint that seeds the editor
    (project rule 15 — never duplicate the same wording logic)."""
    import html as _html_mod

    values = _hotel_field_plain_values(hotel)
    fields = {}
    for key in _HOTEL_EDITABLE_FIELD_KEYS:
        value = values[key]
        if key == "guestNames":
            fields[key] = "".join(f"<p>{_html_mod.escape(line)}</p>" for line in value)
        elif key == "confirmationSentence":
            fields[key] = (
                f"<p>{_html_mod.escape(values['confirmationFirstLine'])}<strong>{_html_mod.escape(values['confirmationBoldTail'])}</strong></p>"
                f"<p><strong>{_html_mod.escape(values['confirmationLabel'])}"
                f'<span style="background-color: rgb(0, 255, 255);">{_html_mod.escape(values["confirmationNumber"])}</span></strong></p>'
            )
        else:
            fields[key] = f"<p>{_html_mod.escape(value)}</p>"
    return fields


def _apply_field(document: Document, cell, key: str, edited_fields: Optional[dict], fallback_text) -> None:
    """Applies field `key` to `cell`: if `edited_fields` carries real (non-
    None) HTML for it, that edited wording is written in via the same
    `replace_paragraph_range_with_html` primitive the Europe Cover Letter
    editor uses (safe here with no stable-reference dance needed at all —
    a table cell's own paragraphs are never part of `document.paragraphs`,
    so editing one cell can never shift another cell's or the document
    body's paragraph indices); otherwise `fallback_text` (a plain string,
    or a callable producing one) is written the normal, non-edited way."""
    html_text = (edited_fields or {}).get(key)
    if html_text is not None:
        docx_utils.replace_paragraph_range_with_html(document, cell.paragraphs[0], cell.paragraphs[-1], html_text)
    else:
        text = fallback_text() if callable(fallback_text) else fallback_text
        _set_cell_text(cell, text)


def _set_confirmation_sentence(cell, number: str) -> None:
    """Fills the "Thanks for booking …" sentence the way the reference
    template is built: its fixed words stay exactly as they are (including the
    bold "Confirmed" part and the line break), and ONLY the run that holds the
    "[Confirmation No.]" placeholder gets the number — that run is already bold
    and highlighted cyan in the template, like the other generated values
    (hotel name, dates, city). The previous code flattened the whole sentence
    into one plain run, which dropped that bold + highlight."""
    paragraph = cell.paragraphs[0]
    for run in paragraph.runs:
        if "[Confirmation No.]" in run.text:
            run.text = run.text.replace("[Confirmation No.]", number)
            return
    # Template structure changed — fall back to plain full-sentence text.
    _set_paragraph_text(paragraph, f'Thanks for booking with us, your booking has been "Confirmed" with Confirmation Number- {number}')


def _fill_hotel_block(table: Table, hotel: dict, document: Document, edited_fields: Optional[dict] = None) -> None:
    """Fills one HOTEL VOUCHER block's fields at their known structural cell
    positions (verified against the real template — see module docstring),
    rather than text-searching for placeholders: several placeholders (e.g.
    '[Date]', '[Hotel Address]') repeat identically more than once in the
    template, so only position reliably distinguishes them.

    `edited_fields`, when given, is this ONE hotel's own
    `{fieldKey: html}` map (see `compose_hotel_editable_fields` for the
    full set of keys) — a staff member's Word-like edits, applied instead
    of the auto-generated value for exactly the fields present. Any field
    NOT present in the map still gets its normal auto-generated value —
    editing one field never blanks the others (`editedBodyHtml`/
    `getEditedHtml()` on the frontend only ever includes fields that were
    actually seeded, matching the Europe Cover Letter's own "null means
    don't touch it" contract)."""
    outer_cell = table.rows[0].cells[0]
    wrapper = outer_cell.tables[0]  # 2 rows: [0]=confirmation sentence, [1]=nested detail tables
    thanks_cell = wrapper.rows[0].cells[0]
    detail_cell = wrapper.rows[1].cells[0]
    booking = detail_cell.tables[0]  # 7x4 "Booking details" table
    guest = detail_cell.tables[1]  # 2x3 guest/room table
    # detail_cell.tables[2] is the static Hotel Policy table — fixed
    # template content (never driven by `hotel`), always left untouched.

    values = _hotel_field_plain_values(hotel)

    # Non-edited path: same final text `_replace_token_in_cell`'s token
    # substitution would have produced, written the normal
    # `_apply_field`/`_set_cell_text` way so the edited and non-edited
    # branches share one code path (project rule 15).
    if (edited_fields or {}).get("confirmationSentence") is not None:
        _apply_field(document, thanks_cell, "confirmationSentence", edited_fields, values["confirmationSentence"])
    else:
        _set_confirmation_sentence(thanks_cell, values["confirmationNumber"])
    _apply_field(document, booking.rows[1].cells[3], "hotelName", edited_fields, values["hotelName"])
    _apply_field(document, booking.rows[2].cells[1], "leadGuestName", edited_fields, values["leadGuestName"])
    # Staff request: the upper box's "No Guest: [No. of Guest]" pair reads
    # "No. of Guest(s): <number>" (just the number — the guest table below
    # keeps the full "4 Adult(s)" text). Only the generated copy changes —
    # the reference template file itself is never touched.
    _set_cell_text(booking.rows[2].cells[2], "No. of Guest(s):")
    _apply_field(document, booking.rows[2].cells[3], "guestTotal", edited_fields, values["guestTotal"])
    _apply_field(document, booking.rows[3].cells[1], "noOfRooms", edited_fields, values["noOfRooms"])
    _apply_field(document, booking.rows[3].cells[3], "phone", edited_fields, values["phone"])
    _apply_field(document, booking.rows[4].cells[1], "checkIn", edited_fields, values["checkIn"])
    _apply_field(document, booking.rows[4].cells[3], "checkOut", edited_fields, values["checkOut"])
    _apply_field(document, booking.rows[5].cells[1], "nights", edited_fields, values["nights"])
    _apply_field(document, booking.rows[5].cells[3], "city", edited_fields, values["city"])
    _apply_field(document, booking.rows[6].cells[1], "address", edited_fields, values["address"])  # merged across cols 1-3

    if edited_fields and edited_fields.get("guestNames") is not None:
        docx_utils.replace_paragraph_range_with_html(
            document, guest.rows[1].cells[0].paragraphs[0], guest.rows[1].cells[0].paragraphs[-1],
            edited_fields["guestNames"],
        )
    else:
        _set_guest_names(guest.rows[1].cells[0], values["guestNames"])
    _apply_field(document, guest.rows[1].cells[1], "roomType", edited_fields, values["roomType"])
    # The guest count is now shown only here, in the guest table's own
    # "No. of Guests" column.
    _apply_field(document, guest.rows[1].cells[2], "guestCounts", edited_fields, values["guestCounts"])


class _HotelBlockProbe:
    """The layout probe's side of document_blocks.finalize for ONE hotel's
    block: hands out decodable colours after the named cells' own range and
    records each block (hotel index, key, seed, alignment)."""

    def __init__(self, registry: dict, base: int, hotel_index: int):
        self._registry, self._base, self._hotel = registry, base, hotel_index
        self._unmatched: list = []

    @property
    def unmatched(self) -> list:
        return self._unmatched

    @unmatched.setter
    def unmatched(self, keys: list) -> None:
        self._unmatched = list(keys)
        self._registry["unmatched"][self._hotel] = self._unmatched

    def add_block(self, key, paragraphs, seed_html, align="left") -> None:
        idx = self._base + len(self._registry["blocks"])
        self._registry["blocks"].append((self._hotel, key, seed_html, align))
        for p_el in paragraphs:
            docx_utils.shade_element_fill(p_el.get_or_add_pPr(), docx_utils.probe_rgb(idx))


def generate_hotel_voucher_docx(hotels: list[dict], _probe: bool = False, _block_registry: Optional[dict] = None) -> bytes:
    """Builds the Hotel Voucher .docx for one or more hotel bookings.
    Returns raw .docx bytes. Raises HotelVoucherError / ValueError on any
    problem — never returns a silently-wrong or empty document.

    `_probe=True` is used ONLY by compute_field_layout() below: it shades
    every editable value cell with a unique, decodable colour so the
    converted PDF reveals exactly where each field sits. A probe document
    is never shown to or downloaded by anyone."""
    if not hotels:
        raise ValueError("At least one hotel is required to generate a voucher.")

    document = _load_template()
    table_el = _find_hotel_block_table(document)
    # The template's own trailing blank paragraph (body-level, after the
    # table) — reused as a spacer between blocks when there's more than one
    # hotel, so multiple vouchers in the same document aren't jammed
    # directly against each other. Real template content, not invented.
    spacer_el = document.paragraphs[-1]._p if document.paragraphs else None

    blocks_el = [table_el]
    last_el = table_el
    for _ in hotels[1:]:
        if spacer_el is not None:
            new_spacer_el = copy.deepcopy(spacer_el)
            last_el.addnext(new_spacer_el)
            last_el = new_spacer_el
        new_table_el = copy.deepcopy(table_el)
        last_el.addnext(new_table_el)
        blocks_el.append(new_table_el)
        last_el = new_table_el

    for hotel_index, (t_el, hotel) in enumerate(zip(blocks_el, hotels)):
        table = Table(t_el, document)
        _fill_hotel_block(table, hotel, document, edited_fields=hotel.get("editedFields"))
        if _probe:
            _shade_editable_cells(table, hotel_index)
        # Whole-voucher editing: every other paragraph of this hotel's block
        # (the boilerplate and policy text) is editable too — see document_blocks.
        probe_side = (
            _HotelBlockProbe(_block_registry, len(hotels) * len(LAYOUT_FIELD_KEYS), hotel_index)
            if _probe and _block_registry is not None else None
        )
        document_blocks.finalize(document, hotel.get("editedFields"), probe_side, root=t_el)

    buf = io.BytesIO()
    document.save(buf)
    return buf.getvalue()


def generate_hotel_voucher_pdf(hotels: list[dict]) -> bytes:
    """Converts the generated .docx to PDF via a real LibreOffice headless
    conversion, so the PDF is the actual rendered document rather than a
    hand-recreated approximation. Requires LibreOffice ('soffice') to be
    installed on the machine running this backend — if it isn't, this
    raises a clear, honest error instead of returning nothing or a fake
    file (project rule 9)."""
    docx_bytes = generate_hotel_voucher_docx(hotels)
    try:
        return docx_utils.convert_docx_bytes_to_pdf(docx_bytes, base_name="hotel_voucher")
    except docx_utils.DocxBuildError as e:
        # Re-raised as HotelVoucherError so existing callers (app.py) that
        # catch that specific type are unaffected by this refactor.
        raise HotelVoucherError(str(e))


# ---------------------------------------------------------------------------
# Editable-preview support: where does each editable value sit on the page?
# ---------------------------------------------------------------------------
# The Hotel Blocking preview is the REAL generated PDF (never an HTML
# imitation). To let staff edit a value directly in that preview, the
# frontend needs the on-page rectangle (and the text style) of every
# editable value. Reading it back out of the same LibreOffice rendering that
# produces the real PDF is the only way to get it exactly right:
#   1. build a "probe" copy of the document in which every editable value
#      cell is shaded with a unique, decodable colour (never shown/served);
#   2. convert it to PDF with the same converter as the real document —
#      shading changes no layout, so every cell lands exactly where it does
#      in the real PDF;
#   3. read the filled rectangles (pypdfium2, already a project dependency)
#      to get each cell's page + rectangle, and the first text character
#      inside each rectangle to get its font size/weight.

LAYOUT_FIELD_KEYS = _HOTEL_EDITABLE_FIELD_KEYS


def _editable_cells(table: Table) -> list:
    """(field key, cell) for every editable value cell of one hotel block —
    the same structural positions `_fill_hotel_block` writes to."""
    outer_cell = table.rows[0].cells[0]
    wrapper = outer_cell.tables[0]
    thanks_cell = wrapper.rows[0].cells[0]
    detail_cell = wrapper.rows[1].cells[0]
    booking = detail_cell.tables[0]
    guest = detail_cell.tables[1]
    return [
        ("confirmationSentence", thanks_cell),
        ("hotelName", booking.rows[1].cells[3]),
        ("leadGuestName", booking.rows[2].cells[1]),
        ("guestTotal", booking.rows[2].cells[3]),
        ("noOfRooms", booking.rows[3].cells[1]),
        ("phone", booking.rows[3].cells[3]),
        ("checkIn", booking.rows[4].cells[1]),
        ("checkOut", booking.rows[4].cells[3]),
        ("nights", booking.rows[5].cells[1]),
        ("city", booking.rows[5].cells[3]),
        ("address", booking.rows[6].cells[1]),
        ("guestNames", guest.rows[1].cells[0]),
        ("roomType", guest.rows[1].cells[1]),
        ("guestCounts", guest.rows[1].cells[2]),
    ]


def _shade_editable_cells(table: Table, hotel_index: int) -> None:
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    for field_index, (_key, cell) in enumerate(_editable_cells(table)):
        r, g, b = docx_utils.probe_rgb(hotel_index * len(LAYOUT_FIELD_KEYS) + field_index)
        tc_pr = cell._tc.get_or_add_tcPr()
        for old in tc_pr.findall(qn("w:shd")):
            tc_pr.remove(old)
        shd = OxmlElement("w:shd")
        shd.set(qn("w:val"), "clear")
        shd.set(qn("w:color"), "auto")
        shd.set(qn("w:fill"), f"{r:02X}{g:02X}{b:02X}")
        tc_pr.append(shd)


def _read_probe_layout(pdf_bytes: bytes, hotel_count: int, block_registry: Optional[dict] = None) -> dict:
    n_fields = len(LAYOUT_FIELD_KEYS)
    decode = {}
    for h in range(hotel_count):
        for f, key in enumerate(LAYOUT_FIELD_KEYS):
            decode[docx_utils.probe_rgb(h * n_fields + f)] = (h, key)
    base = hotel_count * n_fields
    blocks = (block_registry or {}).get("blocks", [])
    for i, (h, key, _seed, _align) in enumerate(blocks):
        decode[docx_utils.probe_rgb(base + i)] = (h, key)
    result = docx_utils.read_probe_layout(pdf_bytes, decode, hotel_count)
    for h, key, seed, align in blocks:
        info = result["groups"][h].get(key)
        if info is not None:
            info["align"] = align
            if seed is not None:
                info["html"] = seed
    unmatched = [list((block_registry or {}).get("unmatched", {}).get(h, [])) for h in range(hotel_count)]
    return {"pages": result["pages"], "hotels": result["groups"], "unmatched": unmatched}


def compute_field_layout(hotels: list[dict]) -> dict:
    """Page + rectangle (PDF points, origin top-left) + font size/weight of
    every editable value of every hotel, for the editable preview. Raises
    HotelVoucherError if the probe can't be built/converted."""
    if not hotels:
        raise ValueError("At least one hotel is required.")
    registry: dict = {"blocks": [], "unmatched": {}}
    probe_docx = generate_hotel_voucher_docx(hotels, _probe=True, _block_registry=registry)
    try:
        probe_pdf = docx_utils.convert_docx_bytes_to_pdf(probe_docx, base_name="hotel_voucher_layout")
    except docx_utils.DocxBuildError as e:
        raise HotelVoucherError(str(e))
    return _read_probe_layout(probe_pdf, len(hotels), registry)
