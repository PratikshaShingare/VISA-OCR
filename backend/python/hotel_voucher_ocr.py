"""
Khanna Travels & Holidays — Hotel Voucher OCR
==============================================

Extracts hotel-booking-voucher fields from a staff-uploaded voucher image or
PDF (a hotel/OTA confirmation, NOT one of this app's own generated
vouchers) so the Hotel Blocking form doesn't have to be retyped by hand.

Reuses ocr_runner.py's existing generic image pipeline wholesale — document-
region crop, orientation detection/correction, deskew, margin crop, contrast
enhancement, and the same OCR-provider abstraction (Tesseract locally /
Google Cloud Vision in the Vercel deployment) already used for passports
(project rule 15: no duplicated OCR plumbing). Only the FIELD extraction
below is new, because a hotel voucher's vocabulary and layout have nothing
in common with a passport's MRZ + bio-data page.

Honesty notes (project rules 9/10):
  - Hotel vouchers are not a standardized document the way ICAO passports
    are — every hotel and OTA formats theirs differently. This is
    inherently a best-effort, label-based text search over the page's raw
    OCR text, exactly like the passport pipeline's own VIZ (non-MRZ) field
    extraction, and it is expected to miss fields on some real vouchers.
  - Every field this returns lands in an ordinary, already-editable Hotel
    Blocking input (js/hotels.js) — nothing here is ever auto-verified or
    presented as certain, and a field this cannot find is simply left blank
    for manual entry, never guessed.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

import cv2
from dateutil import parser as dateutil_parser

import ocr_runner as ocr


def _search_label(text: str, label_patterns: List[str]) -> Optional[str]:
    """Same approach as ocr_runner._search_label — find a label, return
    whatever short run of text follows it on the same line."""
    if not text:
        return None
    for pattern in label_patterns:
        m = re.search(pattern + r"\s*[:\-]?\s*([A-Za-z0-9 ,./#'&()+-]{2,80})", text, re.IGNORECASE)
        if m:
            value = m.group(1).strip().rstrip(".,")
            if value:
                return value
    return None


def _search_number(text: str, label_patterns: List[str]) -> Optional[str]:
    """Like _search_label, but pulls just the leading integer after the
    label (for "No. of Adults: 2", "Adults - 2", etc.)."""
    if not text:
        return None
    for pattern in label_patterns:
        m = re.search(pattern + r"\s*[:\-]?\s*(\d{1,2})", text, re.IGNORECASE)
        if m:
            return m.group(1)
    return None


def _normalize_date(raw: Optional[str]) -> Optional[str]:
    """Best-effort parse of whatever date format a real voucher prints
    (DD/MM/YYYY, "12 Jan 2026", "Jan 12, 2026", ...) into the YYYY-MM-DD
    shape the frontend's <input type="date"> fields expect. dayfirst=True
    since these vouchers are for Indian outbound travel agency clients and
    DD/MM/YYYY is the overwhelmingly common local convention; a value this
    can't parse at all is left out entirely rather than guessed."""
    if not raw:
        return None
    try:
        dt = dateutil_parser.parse(raw, dayfirst=True, fuzzy=True, default=None)
        return dt.strftime("%Y-%m-%d")
    except (ValueError, OverflowError, TypeError):
        return None


def _search_date(text: str, label_patterns: List[str]) -> Optional[str]:
    raw = _search_label(text, label_patterns)
    if not raw:
        return None
    # Trim trailing words a date-label line sometimes runs into (e.g.
    # "Check-in: 12 Jan 2026 Check-out: 15 Jan 2026" both matching the same
    # greedy label pattern) — keep only the date-looking prefix.
    m = re.match(r"([0-9]{1,4}[/\-.\s][A-Za-z0-9]{1,9}[/\-.\s][0-9]{2,4})", raw)
    candidate = m.group(1) if m else raw
    return _normalize_date(candidate)


# A voucher listing several travellers usually labels each one explicitly
# ("Guest 1:", "Guest 2 Name:", "Traveller 1:", ...) rather than repeating a
# bare "Guest Name:" label per person — captured globally (re.finditer, not
# just the first match) so every listed guest becomes its own entry in
# guestNames, matching the Hotel Blocking form's own guestNames list.
_GUEST_LINE_RE = re.compile(
    r"(?:GUEST|TRAVELLER|TRAVELER|PASSENGER)\s*(?:NO\.?)?\s*\d+\s*(?:NAME)?\s*[:\-]\s*([A-Za-z][A-Za-z .'-]{1,60})",
    re.IGNORECASE,
)


def _extract_guest_names(text: str) -> List[str]:
    if not text:
        return []
    names = []
    for m in _GUEST_LINE_RE.finditer(text):
        name = m.group(1).strip().rstrip(".,")
        if name and name.upper() not in [n.upper() for n in names]:
            names.append(name)
    return names


# ---------------------------------------------------------------------------
# Generic, label-independent helpers. Real vouchers (TBO, Booking.com, a
# hotel's own PDF, ...) do not share a layout, so beyond the plain "Label:
# value" search above, each of these recognises a field by what it LOOKS like
# (a confirmation code after any "... Confirmation No", a titled person name,
# a "Room 1 <room type>" row, a street address under the hotel name) and only
# ever returns text that really is on the page.
# ---------------------------------------------------------------------------

_TITLES = r"(?:Mrs|Mr|Miss|Ms|Mstr|Master|Dr|Prof|Shri|Smt)(?![a-z])"
# Words that follow a guest name on the same OCR line but are not part of it.
_NAME_STOP = {
    "no", "show", "add", "room", "adult", "adults", "child", "children", "raised", "cancel", "need", "last", "check",
    "phone", "contact", "email", "rate", "total", "sale", "guest", "details", "amendments", "special", "other",
}
_TITLED_NAME_RE = re.compile(_TITLES + r"\.?\s+((?:[A-Z][A-Za-z'\-]+)(?:\s+[A-Z][A-Za-z'\-]+){0,4})")
_AGENCY_WORDS = re.compile(r"\b(?:private|pvt|limited|ltd|holidays|travels|tours|booking\.com|llp)\b|\(HTL\)", re.IGNORECASE)
_HOTEL_KEYWORDS = (
    r"Hotels?|Resorts?|Inn|Suites?|Residency|Palace|Lodge|Villas?|Hostel|Apartments?|Retreat|Guest\s*House|Guesthouse|Motel|Lodging"
)
_HOTEL_NAME_RE = re.compile(r"((?:[A-Z][A-Za-z0-9'&.\-]*\s+){1,5}(?i:" + _HOTEL_KEYWORDS + r")\b)")
_ADDRESS_RE = re.compile(r"(\d{1,5}[A-Za-z]?[\s,]+[A-Za-z][A-Za-z0-9 .'/\-]*(?:,\s*[A-Za-z0-9 .'/\-]+){1,6})")
_CONF_RE = re.compile(
    r"(?:CONFIRMATION|BOOKING|RESERVATION)\s*(?:NO\.?|NUMBER|NUM|ID|REF(?:ERENCE)?|CODE)\b\s*[:#\-]?\s*([A-Z0-9][A-Z0-9\-/]{3,24})",
    re.IGNORECASE,
)


def _clean_name(raw: str) -> Optional[str]:
    words = raw.split()
    while words and words[-1].lower() in _NAME_STOP:
        words.pop()
    return " ".join(words) if words else None


def _titled_names(text: str) -> List[str]:
    names: List[str] = []
    for m in _TITLED_NAME_RE.finditer(text or ""):
        full = m.group(0)
        title = re.match(_TITLES + r"\.?", full).group(0)
        body = _clean_name(m.group(1))
        if not body:
            continue
        name = f"{title.rstrip('.')}. {body}" if not title.endswith(".") else f"{title} {body}"
        if name.upper() not in [n.upper() for n in names]:
            names.append(name)
    return names


def _find_lead_guest(text: str) -> Optional[str]:
    # "Adult 1 (Lead Guest) Mr. Aakarsh Vikrant Shukla" / "Lead Guest: Mr. A B"
    for m in re.finditer(r"LEAD\s*(?:GUEST|PAX|PASSENGER|TRAVELL?ER)(?:\s*NAME)?\)?\s*[:\-]?\s*(.{0,90})", text or "", re.IGNORECASE):
        tail = m.group(1)
        names = _titled_names(tail)
        if names:
            return names[0]
        plain = re.match(r"([A-Z][A-Za-z'\-]+(?:\s+[A-Z][A-Za-z'\-]+){1,3})", tail.strip())
        if plain:
            cleaned = _clean_name(plain.group(1))
            if cleaned and len(cleaned.split()) >= 2:
                return cleaned
    return None


def _find_confirmation(text: str) -> Optional[str]:
    for m in _CONF_RE.finditer(text or ""):
        code = m.group(1).strip("-/")
        if any(ch.isdigit() for ch in code) or len(code) >= 6:
            return code
    return None


def _find_room_type(text: str) -> Optional[str]:
    for line in (text or "").splitlines():
        m = re.search(r"\bRoom[ \t]*\d{1,2}\b[ \t]*[:\-]?[ \t]*(.+)$", line, re.IGNORECASE)
        if not m:
            continue
        rest = re.split(r"\s+[<\[(]?\d{1,2}\s*Adult|\s+Incl\b|\s+Show\b|\s{3,}", m.group(1))[0].strip(" :-|.,")
        if re.match(r"(?:show|details|guest|pax|room\s*\d)", rest, re.IGNORECASE):
            continue
        if re.match(r"[A-Za-z][A-Za-z0-9 ,&/'\-]{3,60}$", rest) and len(re.findall(r"[A-Za-z]{2,}", rest)) >= 2:
            return rest
    return None


def _find_room_count(text: str) -> Optional[str]:
    explicit = _search_number(text, [r"\bNO\.?\s*OF\s*ROOMS?\b", r"\bNUMBER\s*OF\s*ROOMS?\b", r"\bROOMS\b(?=\s*[:\-])"])
    if explicit and explicit != "0":
        return explicit
    numbers = {int(n) for n in re.findall(r"\bRoom[ \t]*(\d{1,2})\b", text or "", re.IGNORECASE) if 0 < int(n) <= 9}
    return str(max(numbers)) if numbers else None


def _find_occupants(text: str, word: str, label_re: str) -> Optional[str]:
    """Adults / children: 'N Adult(s)' per room (summed), else the labelled
    total, else the number of 'Adult 1', 'Adult 2' ... guest rows."""
    per_room = [int(n) for n in re.findall(r"(?<!\d)(\d{1,2})[ \t]*" + word + r"\b", text or "", re.IGNORECASE)]
    # A number glued to an icon in the scan ("21 Adult(s)" for "<icon>1 Adult(s)")
    # is not trusted: nobody books 21 adults in one room.
    if per_room and all(0 <= n <= 9 for n in per_room):
        total = sum(per_room)
        if total > 0 or word.lower().startswith("adult"):
            return str(total)
    labelled = _search_number(text, [label_re])
    if labelled and int(labelled) <= 20:
        return labelled
    rows = {int(n) for n in re.findall(r"\b" + word + r"[ \t]*(\d{1,2})\b", text or "", re.IGNORECASE)}
    return str(len(rows)) if rows else None


def _find_hotel_name(text: str) -> Optional[str]:
    for line in (text or "").splitlines():
        if _AGENCY_WORDS.search(line):
            continue
        m = _HOTEL_NAME_RE.search(line)
        if m:
            name = re.sub(r"^(?:[A-Za-z]\s+)+", "", m.group(1).strip())  # a lone letter before it is scan noise
            if not re.match(r"(?:cancel|show|check|manage|booking|hotel\s+voucher)", name, re.IGNORECASE):
                return name
    return None


def _find_address_after(text: str, hotel_name: Optional[str]) -> Optional[str]:
    lines = (text or "").splitlines()
    start = 0
    if hotel_name:
        for i, line in enumerate(lines):
            if hotel_name in line:
                start = i + 1
                break
        else:
            return None
    else:
        return None
    for line in lines[start:start + 4]:
        if _AGENCY_WORDS.search(line):
            continue
        m = _ADDRESS_RE.search(line)
        if m:
            addr = re.split(r"\s+(?:No\.?\s*of|Check\s*(?:In|Out)|Last\s)", m.group(1))[0]
            return addr.strip(" ,.|")
    return None


# ---------------------------------------------------------------------------
# Per-room parsing. A voucher can hold several rooms ("Room 1 ... Room 2 ..."),
# each with its own room type, occupancy and guests. Parsing room by room lets
# the form show every distinct room type, the total adults and the real number
# of rooms, and keeps each guest's name attached to the room they are in.
# ---------------------------------------------------------------------------

_ROOM_ROW_RE = re.compile(r"\bRoom[ \t]*(\d{1,2})\b[ \t]*[:\-]?[ \t]*(.+)$", re.IGNORECASE)
_PAX_HEAD_RE = re.compile(r"\bRoom[ \t]*(\d{1,2})\b[ \t]*(?:Show\s*)?(?:Pax|Guest)\s*Details", re.IGNORECASE)
_NIGHTS_RE = re.compile(r"NO\.?\s*OF\s*NIGHTS?\s*[:\-]?\s*(\d{1,3})\b", re.IGNORECASE)


def _room_type_from(rest: str) -> Optional[str]:
    rest = re.split(r"\s+[<\[(]?\d{1,2}\s*Adult|\s+Incl\b|\s+Show\b|\s{3,}", rest)[0].strip(" :-|.,")
    if re.match(r"(?:show|details|guest|pax|room\s*\d)", rest, re.IGNORECASE):
        return None
    if re.match(r"[A-Za-z][A-Za-z0-9 ,&/'\-]{3,60}$", rest) and len(re.findall(r"[A-Za-z]{2,}", rest)) >= 2:
        return rest
    return None


def _parse_rooms(text: str) -> List[Dict[str, Any]]:
    """[{"number", "roomType", "adults", "children", "guests": [names]}] in
    room order. Only what is really printed: a room that shows no type / no
    occupancy simply has None for it."""
    rooms: Dict[int, Dict[str, Any]] = {}

    def room(n: int) -> Dict[str, Any]:
        return rooms.setdefault(n, {"number": n, "roomType": None, "adults": None, "children": None, "guests": [], "_adultRows": set(), "_childRows": set()})

    current: Optional[int] = None
    for line in (text or "").splitlines():
        pax = _PAX_HEAD_RE.search(line)
        if pax:
            current = int(pax.group(1))
            if 0 < current <= 9:
                room(current)
            else:
                current = None
            continue
        row = _ROOM_ROW_RE.search(line)
        if row and 0 < int(row.group(1)) <= 9:
            n = int(row.group(1))
            rtype = _room_type_from(row.group(2))
            if rtype:
                r = room(n)
                if not r["roomType"]:
                    r["roomType"] = rtype
                adults = re.search(r"(?<!\d)(\d{1,2})[ \t]*Adults?(?:\(s\))?\b", row.group(2), re.IGNORECASE)
                if adults and int(adults.group(1)) <= 9 and r["adults"] is None:
                    r["adults"] = int(adults.group(1))
                kids = re.search(r"(?<!\d)(\d{1,2})[ \t]*Child(?:ren)?(?:\(s\))?\b", row.group(2), re.IGNORECASE)
                if kids and int(kids.group(1)) <= 9 and r["children"] is None:
                    r["children"] = int(kids.group(1))
            continue
        if current is not None:
            r = room(current)
            for m in re.finditer(r"\bAdult[ \t]*(\d{1,2})\b", line, re.IGNORECASE):
                r["_adultRows"].add(int(m.group(1)))
            for m in re.finditer(r"\bChild(?:ren)?[ \t]*(\d{1,2})\b", line, re.IGNORECASE):
                r["_childRows"].add(int(m.group(1)))
            for name in _titled_names(line):
                if name.upper() not in [g.upper() for g in r["guests"]]:
                    r["guests"].append(name)
    out = []
    for n in sorted(rooms):
        r = rooms[n]
        if r["adults"] is None and r["_adultRows"]:
            r["adults"] = len(r["_adultRows"])
        if r["children"] is None and r["_childRows"]:
            r["children"] = len(r["_childRows"])
        r.pop("_adultRows")
        r.pop("_childRows")
        out.append(r)
    return out


def _apply_rooms(fields: Dict[str, Optional[str]], rooms: List[Dict[str, Any]], keep_type: bool = False) -> None:
    """Room-derived fields override the single-line guesses: several rooms of
    different types read "Classic King Room, Deluxe Twin Room"; adults and
    children are the sum over rooms; the count is the number of rooms found.
    An explicit "Room Type:" label on the voucher (keep_type) is left alone."""
    if not rooms:
        return
    types: List[str] = []
    for r in rooms:
        if r["roomType"] and r["roomType"].lower() not in [t.lower() for t in types]:
            types.append(r["roomType"])
    if types and not keep_type:
        fields["roomType"] = ", ".join(types)
    fields["noOfRooms"] = str(len(rooms))
    adults = [r["adults"] for r in rooms if r["adults"] is not None]
    if adults and len(adults) == len(rooms):
        fields["noOfAdults"] = str(sum(adults))
    children = [r["children"] for r in rooms if r["children"] is not None]
    if children:
        fields["noOfChildren"] = str(sum(children))


def _find_nights(text: str) -> Optional[int]:
    m = _NIGHTS_RE.search(text or "")
    return int(m.group(1)) if m else None


def extract_hotel_voucher_fields(ocr_text: str) -> Dict[str, Any]:
    """Returns a flat {field: value|None} dict matching js/hotels.js's own
    HOTEL_FIELDS keys, plus a separate 'guestNames' list. Every value is
    either a real string pulled from the page's text or None (never a
    fabricated default) — js/hotels.js only ever fills a form input from a
    key that is present and non-empty."""
    # \b word boundaries throughout — without them a short keyword like
    # "TEL" (for phone) or "IN" (for check-in) matches as a bare substring
    # inside an unrelated word (e.g. "TEL" inside "HOTEL" itself, which
    # matched the "HOTEL BOOKING CONFIRMATION" title line during testing
    # before this was added) rather than only a real standalone label.
    fields: Dict[str, Optional[str]] = {
        "hotelName": _search_label(ocr_text, [r"\bHOTEL\s*NAME\b", r"\bPROPERTY\s*NAME\b"]) or _find_hotel_name(ocr_text),
        "phone": _search_label(ocr_text, [r"\bHOTEL\s*PHONE\b", r"\bCONTACT\s*(?:NO\.?|NUMBER)?\b", r"\bPHONE\s*(?:NO\.?)?\b", r"\bTEL(?:EPHONE)?\b\s*(?:NO\.?)?"]),
        "address": _search_label(ocr_text, [r"\bHOTEL\s*ADDRESS\b", r"\bADDRESS\b"]),
        "city": _search_label(ocr_text, [r"\bCITY\b"]),
        # Frontend rework: js/hotels.js gained an explicit "Country" field
        # so the Cover Letter's Europe "Next Country" field can be pulled
        # from a Hotel Blocking record — attempt the same best-effort
        # label search for it here, on the same terms as every other field
        # (never guessed from city/address text, only ever a real "Country:"
        # label the voucher itself prints).
        "country": _search_label(ocr_text, [r"\bCOUNTRY\b"]),
        "confirmationNumber": _find_confirmation(ocr_text),
        "leadGuestName": _find_lead_guest(ocr_text) or _search_label(ocr_text, [r"\bLEAD\s*GUEST(?:\s*NAME)?\b", r"\bGUEST(?:'?S)?\s*NAME\b"]),
        "roomType": _search_label(ocr_text, [r"\bROOM\s*TYPE\b", r"\bROOM\s*CATEGORY\b"]) or _find_room_type(ocr_text),
        "noOfRooms": _find_room_count(ocr_text),
        "noOfAdults": _find_occupants(ocr_text, r"Adults?(?:\(s\))?", r"\b(?:NO\.?\s*OF\s*)?ADULTS?\b"),
        "noOfChildren": _find_occupants(ocr_text, r"Child(?:ren)?(?:\(s\))?", r"\b(?:NO\.?\s*OF\s*)?CHILD(?:REN)?\b"),
        "checkIn": _search_date(ocr_text, [r"\bCHECK[\s\-]*IN\b(?:\s*DATE)?"]),
        "checkOut": _search_date(ocr_text, [r"\bCHECK[\s\-]*OUT\b(?:\s*DATE)?"]),
    }
    if not fields["address"]:
        fields["address"] = _find_address_after(ocr_text, fields["hotelName"])
    # An agency / OTA support line is not the hotel's phone number.
    if fields["phone"] and re.search(r"call\s*us|helpline|customer\s*care", fields["phone"], re.IGNORECASE):
        fields["phone"] = None
    rooms = _parse_rooms(ocr_text)
    explicit_type = bool(fields["roomType"]) and bool(re.search(r"ROOM\s*(?:TYPE|CATEGORY)", ocr_text or "", re.IGNORECASE))
    _apply_rooms(fields, rooms, keep_type=explicit_type)
    guests = _extract_guest_names(ocr_text)
    for r in rooms:
        for name in r["guests"]:
            if name.upper() not in [g.upper() for g in guests]:
                guests.append(name)
    for name in _titled_names(ocr_text):
        if name.upper() not in [g.upper() for g in guests]:
            guests.append(name)
    if fields["leadGuestName"] and fields["leadGuestName"].upper() not in [g.upper() for g in guests]:
        guests.insert(0, fields["leadGuestName"])
    return {"fields": fields, "guestNames": guests, "rooms": rooms, "nights": _find_nights(ocr_text), "explicitRoomType": explicit_type}


# A voucher screenshot / PDF page is mostly small, dense text in several
# columns. Tesseract reads it far better enlarged, and a second page-segmentation
# mode (4: columns of variable-size text) catches lines the first one (6: one
# block) merges or drops, so the text is read twice and each field is taken from
# the first reading that contains it.
_MIN_OCR_WIDTH = 2400


def _read_page_texts(gray) -> List[str]:
    enhanced = ocr.enhance_for_ocr(gray)
    if getattr(ocr._provider, "name", "") != "tesseract":
        # Cloud OCR reads the page as a whole at its own resolution.
        return [ocr.normalize_ocr_text(ocr._provider.ocr_text(enhanced, config=ocr.FULL_PAGE_TESSERACT_CONFIG))]
    height, width = gray.shape[:2]
    factor = min(2.0, _MIN_OCR_WIDTH / float(width)) if width < _MIN_OCR_WIDTH else 1.0

    def scaled(img):
        return cv2.resize(img, None, fx=factor, fy=factor, interpolation=cv2.INTER_CUBIC) if factor > 1.0 else img

    # Clean screenshots read best untouched (contrast enhancement smears their
    # thin text); photographs of paper read better enhanced — both readings are
    # taken and each field comes from the first one that has it.
    readings = [
        (scaled(gray), ocr.FULL_PAGE_TESSERACT_CONFIG),
        (scaled(gray), "--psm 4"),
        (scaled(enhanced), ocr.FULL_PAGE_TESSERACT_CONFIG),
    ]
    texts = []
    for image, config in readings:
        text = ocr.normalize_ocr_text(ocr._provider.ocr_text(image, config=config))
        if text and text not in texts:
            texts.append(text)
    return texts or [""]


def _merge_extractions(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    fields: Dict[str, Optional[str]] = {}
    guests: List[str] = []
    rooms: Dict[int, Dict[str, Any]] = {}
    nights: Optional[int] = None
    explicit_type = False
    for res in results:
        for key, value in res["fields"].items():
            if not fields.get(key) and value:
                fields[key] = value
            else:
                fields.setdefault(key, None)
        for name in res["guestNames"]:
            if name.upper() not in [g.upper() for g in guests]:
                guests.append(name)
        for r in res.get("rooms") or []:
            have = rooms.setdefault(r["number"], {"number": r["number"], "roomType": None, "adults": None, "children": None, "guests": []})
            for key in ("roomType", "adults", "children"):
                if have[key] is None and r[key] is not None:
                    have[key] = r[key]
            for name in r["guests"]:
                if name.upper() not in [g.upper() for g in have["guests"]]:
                    have["guests"].append(name)
        if nights is None and res.get("nights") is not None:
            nights = res["nights"]
        explicit_type = explicit_type or bool(res.get("explicitRoomType"))
    room_list = [rooms[n] for n in sorted(rooms)]
    _apply_rooms(fields, room_list, keep_type=explicit_type)
    return {"fields": fields, "guestNames": guests, "rooms": room_list, "nights": nights}


def _nights_between(check_in: Optional[str], check_out: Optional[str]) -> Optional[int]:
    try:
        from datetime import date
        a, b = date.fromisoformat(check_in or ""), date.fromisoformat(check_out or "")
    except ValueError:
        return None
    return (b - a).days if b >= a else None


def _nights_warnings(printed: Optional[int], check_in: Optional[str], check_out: Optional[str]) -> List[str]:
    """The voucher prints "No. of Nights: N" and the form works the number out
    from the dates; when both exist and disagree, one of them was misread."""
    computed = _nights_between(check_in, check_out)
    if printed is not None and computed is not None and printed != computed:
        return [
            f"The voucher says {printed} night(s) but the dates read give {computed} — "
            "please check the check-in and check-out dates against the voucher."
        ]
    return []


def process_hotel_voucher_page(pil_image) -> Dict[str, Any]:
    """Runs the shared image pipeline (ocr_runner.py) then this module's own
    hotel-voucher field extraction on a single page image. Mirrors
    ocr_runner.process_passport_page()'s shape/structure closely so the two
    endpoints in app.py read the same way, without sharing passport-only
    logic (MRZ parsing, etc.) that has no place here."""
    warnings: List[str] = []
    bgr = ocr.pil_to_bgr(pil_image)
    bgr, region_detected = ocr.detect_and_crop_document_region(bgr)

    gray_check = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    if ocr.is_blank_page(gray_check):
        return {
            "isBlank": True,
            "processedImageBase64": ocr.bgr_to_base64_png(bgr),
            "documentRegionDetected": region_detected,
            "fields": {},
            "guestNames": [],
            "rooms": [],
            "nights": None,
            "warnings": ["This page looks blank — no processing was attempted."],
        }

    orientation = ocr.evaluate_orientations(bgr)
    bgr = ocr._rotate_90_multiple(bgr, orientation["bestRotation"])
    if orientation["needsReview"]:
        warnings.append("Orientation could not be determined with confidence — please check the page is right-side up.")

    skew_angle = ocr.detect_skew_angle(bgr)
    bgr = ocr.deskew_image(bgr, skew_angle)
    bgr = ocr.safe_crop_white_margins(bgr)

    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    ocr_texts = _read_page_texts(gray)
    ocr_text = ocr_texts[0]
    extracted = _merge_extractions([extract_hotel_voucher_fields(t) for t in ocr_texts])
    if not any(extracted["fields"].values()) and not extracted["guestNames"]:
        warnings.append(
            "No recognizable hotel-voucher fields were found on this page — every field below still needs to be entered manually."
        )

    fields = extracted["fields"]
    nights = extracted.get("nights")
    warnings.extend(_nights_warnings(nights, fields.get("checkIn"), fields.get("checkOut")))
    # "Other guests" are everyone except the lead guest (who has their own field).
    lead = (fields.get("leadGuestName") or "").upper()
    other_guests = [g for g in extracted["guestNames"] if g.upper() != lead]
    return {
        "isBlank": False,
        "processedImageBase64": ocr.bgr_to_base64_png(bgr),
        "documentRegionDetected": region_detected,
        "ocrText": ocr_text,
        "fields": fields,
        "guestNames": other_guests,
        "rooms": extracted.get("rooms") or [],
        "nights": nights,
        "warnings": warnings,
    }


def process_hotel_voucher_file(path: str, page_index: int = 0) -> Dict[str, Any]:
    pages = ocr.load_pages(path)
    total_pages = len(pages)
    if page_index < 0 or page_index >= total_pages:
        raise IndexError(f"page_index {page_index} out of range (file has {total_pages} page(s))")
    result = process_hotel_voucher_page(pages[page_index])
    result["pageIndex"] = page_index
    result["totalPages"] = total_pages
    return result


def enrich_with_hotel_lookup(result: Dict[str, Any], lookup=None) -> Dict[str, Any]:
    """Fills the hotel's address, phone, city (and country when the voucher has
    none) from an online lookup by hotel NAME — the voucher's own address is
    only used to pick the right namesake. The looked-up values replace the
    OCR's, since the OCR address is often a partial or mis-read line; when the
    lookup finds nothing, whatever the voucher printed is left untouched.
    Adds result["lookup"] = {status, source, name, ...} for the UI to label."""
    fields = result.get("fields") or {}
    name = fields.get("hotelName")
    if result.get("isBlank") or not name:
        result["lookup"] = {"status": "skipped", "source": ""}
        return result
    if lookup is None:
        import hotel_lookup
        lookup = hotel_lookup.lookup_hotel
    found = lookup(name, address_hint=fields.get("address") or "", city_hint=fields.get("city") or "", country_hint=fields.get("country") or "")
    result["lookup"] = {k: found.get(k, "") for k in ("status", "source", "name", "address", "phone", "city", "country")}
    if found.get("status") == "ok":
        for key in ("address", "phone", "city", "country"):
            if found.get(key):
                fields[key] = found[key]
    return result
