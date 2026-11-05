"""
Khanna Travels & Holidays — hotel voucher layout reader
========================================================

Word-position (layout-aware) reading of a hotel-booking voucher. A voucher
screenshot is several columns of small text; reading it as one stream of text
mixes the columns ("Mrs. Simranpal Kaur Bhatia Need Further Help?"). Here each
recognised word keeps its pixel box, so a value can be taken from where it
really sits — to the right of its label, or directly below it in the same
column — instead of from whatever text happens to follow it.

Nothing is guessed: a label that is not on the page simply yields None.
"""

from __future__ import annotations

import re
from statistics import median
from typing import Any, Dict, List, Optional, Sequence, Tuple

import cv2

import ocr_runner as ocr

Word = Dict[str, Any]
Line = Dict[str, Any]

_TARGET_WIDTH = 2400


def read_words(gray) -> Tuple[List[Word], float]:
    """OCR words in the ORIGINAL image's pixel coordinates (the image is
    enlarged for reading — small screenshot text reads far better — and the
    boxes are mapped back). Returns (words, scale used)."""
    width = gray.shape[1]
    factor = min(2.0, _TARGET_WIDTH / float(width)) if width < _TARGET_WIDTH else 1.0
    img = cv2.resize(gray, None, fx=factor, fy=factor, interpolation=cv2.INTER_CUBIC) if factor > 1.0 else gray
    provider = ocr._provider
    words = provider.ocr_words(img, config="--psm 11")
    out: List[Word] = []
    for w in words:
        out.append({
            "text": w["text"], "left": w["left"] / factor, "top": w["top"] / factor,
            "width": w["width"] / factor, "height": w["height"] / factor, "conf": w.get("conf", 0.0),
        })
    return out, factor


def _right(w: Word) -> float:
    return w["left"] + w["width"]


def _bottom(w: Word) -> float:
    return w["top"] + w["height"]


def _mid_y(w: Word) -> float:
    return w["top"] + w["height"] / 2.0


def group_lines(words: Sequence[Word], x_min: float = -1e9, x_max: float = 1e9) -> List[Line]:
    """Words → reading-order lines (top to bottom, left to right), limited to
    the horizontal band [x_min, x_max). Each line: {"text", "words", "left",
    "right", "top", "bottom"}."""
    pool = [w for w in words if w["left"] >= x_min and w["left"] < x_max]
    if not pool:
        return []
    tol = max(4.0, median(w["height"] for w in pool) * 0.6)
    pool.sort(key=_mid_y)
    rows: List[List[Word]] = []
    for w in pool:
        if rows and abs(_mid_y(w) - median(_mid_y(r) for r in rows[-1])) <= tol:
            rows[-1].append(w)
        else:
            rows.append([w])
    lines: List[Line] = []
    for row in rows:
        row.sort(key=lambda w: w["left"])
        lines.append({
            "text": " ".join(w["text"] for w in row), "words": row, "left": row[0]["left"],
            "right": max(_right(w) for w in row), "top": min(w["top"] for w in row), "bottom": max(_bottom(w) for w in row),
        })
    return lines


def lines_text(lines: Sequence[Line]) -> str:
    return "\n".join(l["text"] for l in lines)


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def find_phrase(words: Sequence[Word], phrase: str, after_top: Optional[float] = None) -> Optional[Dict[str, float]]:
    """Box {"left","top","right","bottom"} of the first occurrence of the
    phrase (matched word by word, ignoring case/punctuation) on one line."""
    target = [_norm(t) for t in phrase.split()]
    target = [t for t in target if t]
    if not target:
        return None
    for line in group_lines(words):
        row = line["words"]
        for i in range(len(row) - len(target) + 1):
            chunk = row[i:i + len(target)]
            if all(_norm(c["text"]) == t or (len(t) >= 5 and _norm(c["text"]).startswith(t)) for c, t in zip(chunk, target)):
                box = {"left": min(c["left"] for c in chunk), "top": min(c["top"] for c in chunk),
                       "right": max(_right(c) for c in chunk), "bottom": max(_bottom(c) for c in chunk)}
                if after_top is not None and box["top"] < after_top:
                    continue
                return box
    return None


def words_in(words: Sequence[Word], left: float, right: float, top: float, bottom: float) -> List[Word]:
    return [w for w in words if w["left"] >= left and w["left"] < right and _mid_y(w) >= top and _mid_y(w) < bottom]


# ---------------------------------------------------------------------------
# Shared field helpers
# ---------------------------------------------------------------------------

_TITLE_RE = re.compile(r"^(?:Mrs|Mr|Miss|Ms|Mstr|Master|Dr|Prof|Shri|Smt)\b\.?\s*", re.IGNORECASE)
_DATE_RES = [
    re.compile(r"\b(\d{1,2})[-/ .]([A-Za-z]{3,9})[-/ .,]*(\d{4})\b"),
    re.compile(r"\b(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})\b"),
]
_MONTHS = {m: i + 1 for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}


def parse_date(text: str, dayfirst: bool = True) -> Optional[str]:
    """First date in the text → YYYY-MM-DD. "07-Oct-2026" and "24/12/2026"
    (day first — these vouchers are for Indian outbound bookings) are read
    exactly; anything else is left unread rather than guessed."""
    from datetime import date
    for rx in _DATE_RES:
        m = rx.search(text or "")
        if not m:
            continue
        a, b, c = m.groups()
        try:
            if b.isdigit():
                d, mo, y = int(a), int(b), int(c)
                if mo > 12 and d <= 12:
                    d, mo = mo, d
            else:
                d, mo, y = int(a), _MONTHS.get(b[:3].lower()), int(c)
                if not mo:
                    continue
            return date(y, mo, d).isoformat()
        except ValueError:
            continue
    return None


def strip_title(name: str) -> str:
    return _TITLE_RE.sub("", (name or "").strip())


def name_key(name: str) -> str:
    return re.sub(r"[^a-z]", "", strip_title(name).lower())


def clean_person_name(raw: str) -> Optional[str]:
    """A guest name as printed ("Mr. Raunaq SinghJaspalSingh Bhui") minus
    stray icon / punctuation noise at either end."""
    s = re.sub(r"[|\\\[\]{}<>_=]+", " ", raw or "")
    s = re.sub(r"\s+", " ", s).strip(" .,:;-&*+")
    if len(re.findall(r"[A-Za-z]", s)) < 3:
        return None
    return s


def add_unique_name(names: List[str], name: Optional[str]) -> None:
    if not name:
        return
    key = name_key(name)
    if not key:
        return
    for i, have in enumerate(names):
        if name_key(have) == key:
            # Keep the version that carries the title ("Mr. X" over "X").
            if not _TITLE_RE.match(have) and _TITLE_RE.match(name):
                names[i] = name
            return
    names.append(name)


def _tidy_room_type(raw: str) -> Optional[str]:
    s = re.split(r"\s+[<\[(+&©¢]?\s*(?:\d\s+)?\d{1,2}\s*Adult|\s+Incl\b|\s+Show\b|\s{3,}", raw or "")[0]
    s = re.sub(r"[|\\\[\]{}<>_=©¢]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip(" :-|.,&+*")
    if len(re.findall(r"[A-Za-z]{2,}", s)) < 1 or len(s) < 4:
        return None
    return s


# ---------------------------------------------------------------------------
# Type detection
# ---------------------------------------------------------------------------

TYPE_TBO = "tbo"
TYPE_BOOKING_SUMMARY = "booking_summary"
TYPE_UNKNOWN = "unknown"

TYPE_LABELS = {
    TYPE_TBO: "TBO booking voucher (Room Details / Guest Details)",
    TYPE_BOOKING_SUMMARY: "Confirmed Booking voucher (Booking Summary / Pax Summary)",
    TYPE_UNKNOWN: "Unrecognised layout",
}


def detect_voucher_type(words: Sequence[Word]) -> str:
    blob = _norm(" ".join(w["text"] for w in words))
    score_tbo = sum(k in blob for k in ("tboconfirmation", "leadguest", "roomdetails", "guestdetails", "noofnights", "paxdetails"))
    score_bs = sum(k in blob for k in ("bookingsummary", "paxsummary", "traveldates", "totalnights", "roomtypes", "confirmedbooking", "totaladult"))
    if score_tbo >= 2 and score_tbo >= score_bs:
        return TYPE_TBO
    if score_bs >= 2:
        return TYPE_BOOKING_SUMMARY
    return TYPE_UNKNOWN


# ---------------------------------------------------------------------------
# Type 1 — TBO booking voucher
#   header : agency block, "TBO Confirmation No", hotel name + address,
#            Check In / Check Out / No. of Nights
#   body   : Room Details ("Room 1 <type> ... N Adult(s)"),
#            Guest Details ("Adult 1 (Lead Guest) Mr. ..."), right-hand panel
#            of support / price boxes (never read for guest data)
# ---------------------------------------------------------------------------

_ROOM_LINE_RE = re.compile(r"^\W{0,3}Room\s*(\d{1,2})\b[\s:\-]*(.*)$", re.IGNORECASE)
_PERSON_ROW_RE = re.compile(r"^\W{0,3}(Adult|Child(?:ren)?|Infant)\s*(\d{1,2})\b(.*)$", re.IGNORECASE)
_LEAD_MARK_RE = re.compile(r"[\(\[]?\s*Lead\s*Guest\s*[\)\]]?", re.IGNORECASE)
_SECTION_END = ("supplement", "cancellation", "salesummary", "needfurther", "importantnote")


def _count_before(text: str, word_re: str) -> Optional[int]:
    m = re.search(r"(\d{1,3})\s*" + word_re, text, re.IGNORECASE)
    if not m:
        return None
    n = m.group(1)
    # A person icon glued to the digit ("21 Adult(s)" for "<icon>1 Adult(s)").
    return int(n[-1]) if len(n) > 1 else int(n)


def _clean_hotel_name_tokens(row: List[Word]) -> str:
    toks = [w for w in row if len(re.findall(r"[A-Za-z0-9]", w["text"])) >= 2
            and (w.get("conf", 100) >= 40 or len(re.findall(r"[A-Za-z]", w["text"])) >= 4)]
    # Star icons read as short junk ("x&", "ve", "wf") after the name; photo
    # fragments read as junk before it.
    while toks and (len(toks[-1]["text"]) <= 2 and not toks[-1]["text"].isupper() and not toks[-1]["text"].isdigit()):
        toks.pop()
    while toks and not re.match(r"[A-Z0-9(]", re.sub(r"^[a-z]{1,2}(?=[A-Z])", "", toks[0]["text"])):
        toks.pop(0)
    texts = []
    for t in toks:
        # a broken-image icon glues junk letters to the first word ("lsHilton")
        t = re.sub(r"^[a-z]{1,2}(?=[A-Z])", "", t["text"]).strip("_|")
        if t:
            texts.append(t)
    # A photo that failed to load prints its alt text (= the hotel name) right
    # before the real name — sometimes with its first word eaten by the broken
    # image icon: keep only the last, complete copy.
    n = len(texts)
    for k in range(n // 2, 1, -1):
        if [_norm(t) for t in texts[:k]] == [_norm(t) for t in texts[n - k:]]:
            texts = texts[k:]
            break
    return " ".join(texts).strip(" ,.-")


_CODE_WHITELIST = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
_DIGITS_WHITELIST = "0123456789"


def read_strip(gray, left: float, top: float, right: float, bottom: float, whitelist: Optional[str] = None,
               scales: Sequence[int] = (3, 4, 5)) -> Optional[str]:
    """Close-up reading of one line of small text inside a pixel rectangle:
    enlarged, read as a single line (optionally restricted to a character
    set), the reading repeated most often across the scales wins."""
    from collections import Counter
    h, w = gray.shape[:2]
    x0, x1, y0, y1 = max(0, int(left)), min(w, int(right)), max(0, int(top)), min(h, int(bottom))
    if y1 - y0 < 4 or x1 - x0 < 8:
        return None
    crop = gray[y0:y1, x0:x1]
    cfg = "--psm 7" + (" -c tessedit_char_whitelist=" + whitelist if whitelist else "")
    votes: Counter = Counter()
    for scale in scales:
        big = cv2.resize(crop, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
        big = cv2.copyMakeBorder(big, 20, 20, 20, 20, cv2.BORDER_CONSTANT, value=255)
        text = (ocr._provider.ocr_text(big, config=cfg) or "").strip().split("\n")[0].strip()
        if text:
            votes[text] += 1
    return votes.most_common(1)[0][0] if votes else None


def reread_code(gray, box: Dict[str, float], span_after: float = 170.0) -> Optional[str]:
    """Second, close-up reading of the booking code to the right of a label (a
    small screenshot prints it in ~7px type, where one pass may drop or garble
    characters): capitals and digits only."""
    text = read_strip(gray, box["right"] + 2, box["top"] - 5, box["right"] + 2 + span_after, box["bottom"] + 5, _CODE_WHITELIST)
    tok = re.sub(r"[^A-Z0-9]", "", (text or "").split(" ")[0].upper())
    return tok if 6 <= len(tok) <= 14 else None


def parse_tbo(words: Sequence[Word], gray=None) -> Dict[str, Any]:
    out: Dict[str, Any] = {"hotelName": None, "address": None, "checkIn": None, "checkOut": None, "nights": None,
                           "confirmationNumber": None, "rooms": [], "guests": [], "lead": None}
    rd = find_phrase(words, "Room Details")
    gd = find_phrase(words, "Guest Details")
    panel_marks = [find_phrase(words, p) for p in ("Need Modification", "Raised Request", "Sale Summary", "Need Further")]
    panel_left = min([b["left"] for b in panel_marks if b], default=1e9) - 12
    header_bottom = (rd["top"] - 4) if rd else 1e9
    header_words = [w for w in words if _mid_y(w) < header_bottom]

    # confirmation
    conf = find_phrase(header_words, "Confirmation No")
    if conf:
        row = [w for w in header_words if abs(_mid_y(w) - (conf["top"] + conf["bottom"]) / 2) <= 9 and w["left"] >= conf["right"] - 2]
        row.sort(key=lambda w: w["left"])
        for w in row:
            tok = re.sub(r"[^A-Za-z0-9]", "", w["text"])
            if len(tok) >= 5 and any(c.isdigit() for c in tok) or len(tok) >= 7:
                out["confirmationNumber"] = tok.upper()
                break
        # TBO codes are 10 characters starting "TB"; anything else was misread.
        code = out["confirmationNumber"]
        if gray is not None and (not code or len(code) != 10 or not code.startswith("TB")):
            again = reread_code(gray, conf)
            if again and len(again) == 10 and again.startswith("TB"):
                out["confirmationNumber"] = again
            elif again and not code:
                out["confirmationNumber"] = again

    # dates + hotel name/address share the band around "Check In"
    ci = find_phrase(header_words, "Check In")
    co = find_phrase(header_words, "Check Out")

    def date_after(box: Optional[Dict[str, float]]) -> Optional[str]:
        if not box:
            return None
        mid = (box["top"] + box["bottom"]) / 2
        row = [w for w in header_words if abs(_mid_y(w) - mid) <= 9 and w["left"] >= box["right"] - 2]
        row.sort(key=lambda w: w["left"])
        return parse_date(" ".join(w["text"] for w in row))

    out["checkIn"], out["checkOut"] = date_after(ci), date_after(co)

    if ci:
        ci_mid = (ci["top"] + ci["bottom"]) / 2
        name_row = sorted([w for w in header_words if abs(_mid_y(w) - ci_mid) <= 12 and _right(w) <= ci["left"] + 2], key=lambda w: w["left"])
        name = _clean_hotel_name_tokens(name_row)
        out["hotelName"] = name or None
        if name:
            first_left = next((w["left"] for w in name_row if w["text"] == name.split()[0]), name_row[0]["left"] if name_row else 0)
            low = max(w["top"] + w["height"] for w in name_row) if name_row else ci["bottom"]
            addr_words = [w for w in header_words if w["top"] >= low - 3 and _mid_y(w) <= low + 34 and w["left"] >= first_left - 22
                          and w["left"] < min(ci["left"], co["left"] if co else ci["left"]) - 25]
            addr_lines = group_lines(addr_words)
            if addr_lines:
                parts = [w["text"] for w in addr_lines[0]["words"] if len(re.findall(r"[A-Za-z0-9]", w["text"])) >= 1]
                text = " ".join(parts)
                text = re.split(r"\s+(?:No\.?\s*of|Check\s*(?:In|Out)|Last\s)", text)[0]
                out["address"] = text.strip(" ,.|") or None

    # nights: the number printed beside "No. of Nights"
    hdr_right = [w for w in header_words if ci and w["left"] >= ci["left"] - 20]
    for w in sorted(hdr_right, key=lambda w: (_mid_y(w), w["left"])):
        if ci and co and w["text"].isdigit() and len(w["text"]) <= 3 and co["top"] - 4 <= w["top"] <= co["bottom"] + 45:
            out["nights"] = int(w["text"])
            break
    if out["nights"] is None:
        m = re.search(r"No\.?\s*of\s*Nights?\s*[:\-]?\s*(\d{1,3})", " ".join(w["text"] for w in hdr_right), re.IGNORECASE)
        if m:
            out["nights"] = int(m.group(1))

    # --- Room Details
    body_end_rooms = gd["top"] - 4 if gd else 1e9
    room_lines = group_lines([w for w in words if rd and _mid_y(w) > rd["bottom"] and _mid_y(w) < body_end_rooms and w["left"] < panel_left])
    rooms: Dict[int, Dict[str, Any]] = {}
    for line in room_lines:
        m = _ROOM_LINE_RE.match(line["text"])
        if not m or not (0 < int(m.group(1)) <= 9):
            continue
        n = int(m.group(1))
        if n in rooms:
            continue
        rest = m.group(2)
        rooms[n] = {"number": n, "roomType": _tidy_room_type(rest), "adults": _count_before(rest, r"Adult"),
                    "children": _count_before(rest, r"Child"), "guests": []}
    # --- Guest Details
    guest_lines: List[Line] = []
    if gd:
        end = 1e9
        for key in ("Supplement Details", "Cancellation Charges", "Sale Summary"):
            b = find_phrase([w for w in words if w["left"] < panel_left], key, after_top=gd["bottom"])
            if b:
                end = min(end, b["top"] - 2)
        guest_lines = group_lines([w for w in words if _mid_y(w) > gd["bottom"] and _mid_y(w) < end and w["left"] < panel_left])
    current = 1
    lead: Optional[str] = None
    all_guests: List[str] = []
    rows_by_room: Dict[int, Dict[str, set]] = {}
    for line in guest_lines:
        text = line["text"]
        room_m = _ROOM_LINE_RE.match(text)
        if room_m and not _PERSON_ROW_RE.match(text) and re.match(r"(?:\W*$|(?:hide|show|pax|guest))", room_m.group(2).strip(), re.IGNORECASE):
            current = int(room_m.group(1))
            continue
        pm = _PERSON_ROW_RE.match(text)
        if not pm:
            continue
        kind, idx, rest = pm.group(1).lower(), int(pm.group(2)), pm.group(3)
        rows_by_room.setdefault(current, {"adult": set(), "child": set()})["child" if kind.startswith(("child", "infant")) else "adult"].add(idx)
        is_lead = bool(_LEAD_MARK_RE.search(rest))
        rest = _LEAD_MARK_RE.sub(" ", rest)
        # drop trailing page-furniture that shares the row
        rest = re.split(r"\s+(?:No\s+tickets|Need\s+Further|Call\s+us|Hide\s+Pax|Show\s+Pax)", rest, flags=re.IGNORECASE)[0]
        name = clean_person_name(rest)
        if not name:
            continue
        rooms.setdefault(current, {"number": current, "roomType": None, "adults": None, "children": None, "guests": []})
        add_unique_name(rooms[current]["guests"], name)
        add_unique_name(all_guests, name)
        if is_lead and not lead:
            lead = name
    for n, r in rooms.items():
        rows = rows_by_room.get(n)
        if rows:
            if r["adults"] is None and rows["adult"]:
                r["adults"] = len(rows["adult"])
            if r["children"] is None and rows["child"]:
                r["children"] = len(rows["child"])
    out["rooms"] = [rooms[n] for n in sorted(rooms)]
    out["guests"] = all_guests
    out["lead"] = lead or (all_guests[0] if all_guests else None)
    return out


# ---------------------------------------------------------------------------
# Type 2 — "Confirmed Booking" voucher
#   right panel "Booking Summary": hotel name + address, Travel Dates
#     (Check-in / Check-out / Total Nights), Room Type(s), Total Rooms /
#     Total Adult(s) / Total Children
#   left columns of labelled boxes: Booking Id | Leader / Guest Details | ...
# ---------------------------------------------------------------------------

_FIELD_LABELS = [
    "Booking Id", "Booking Status", "Booking Date", "Deadline Date", "Leader", "Guest Details", "Agent Ref", "Voucher No",
    "Hotel Conf", "Destination", "Pax Summary", "Add Pancard", "Back", "Create Ticket", "Cancel", "Booking Summary", "Travel Dates",
    "Room Type", "Total Rooms", "Gross Rate", "Cancellation",
]
_MEAL_WORDS = re.compile(r"breakfast|room\s*only|half\s*board|full\s*board|all\s*inclusive|dinner|lunch|meal|wifi|wi-fi|free\s", re.IGNORECASE)


def _is_label_line(text: str) -> bool:
    n = _norm(text)
    return any(n.startswith(_norm(l)) for l in _FIELD_LABELS)


def _below(words: Sequence[Word], box: Dict[str, float], left: float, right: float, max_dy: float, min_dy: float = 0.0) -> List[Word]:
    return [w for w in words if w["left"] >= left and w["left"] < right and _mid_y(w) > box["bottom"] + min_dy and _mid_y(w) <= box["bottom"] + max_dy]


def _number_below(words: Sequence[Word], box: Optional[Dict[str, float]], width: float = 90.0, max_dy: float = 40.0,
                  gray=None, left_off: float = 8.0) -> Optional[int]:
    """The small integer printed under a label. A single enlarged close-up is
    taken when the page-wide reading missed it (one digit in ~7px type often
    is)."""
    if not box:
        return None
    cands = [w for w in _below(words, box, box["left"] - left_off, box["left"] + width, max_dy) if re.fullmatch(r"\d{1,3}", w["text"])]
    if cands:
        cands.sort(key=lambda w: (_mid_y(w), w["left"]))
        return int(cands[0]["text"])
    if gray is not None:
        text = read_strip(gray, box["left"] - left_off, box["bottom"] + 2, box["left"] + width, box["bottom"] + max_dy, _DIGITS_WHITELIST, scales=(4, 6))
        m = re.search(r"\d{1,3}", text or "")
        if m:
            return int(m.group(0))
    return None


def _text_left(line: Line) -> float:
    """Left edge of a line's real text, ignoring a leading icon glyph."""
    for w in line["words"]:
        if len(re.findall(r"[A-Za-z]", w["text"])) >= 3:
            return w["left"]
    return line["left"]


def parse_booking_summary(words: Sequence[Word], gray=None) -> Dict[str, Any]:
    out: Dict[str, Any] = {"hotelName": None, "address": None, "checkIn": None, "checkOut": None, "nights": None,
                           "confirmationNumber": None, "rooms": [], "guests": [], "lead": None,
                           "noOfRooms": None, "noOfAdults": None, "noOfChildren": None, "roomType": None}
    bs = find_phrase(words, "Booking Summary")
    panel_left = (bs["left"] - 12) if bs else 1e9
    panel = [w for w in words if w["left"] >= panel_left]
    main = [w for w in words if w["left"] < panel_left]

    if bs:
        td = find_phrase(panel, "Travel Dates")
        name_zone_bottom = td["top"] - 2 if td else bs["bottom"] + 90
        zone = [w for w in panel if _mid_y(w) > bs["bottom"] + 2 and _mid_y(w) < name_zone_bottom and w["left"] >= bs["left"] + 20]
        lines = group_lines(zone)
        # drop pure-icon lines (a few stray glyphs, nothing alphabetic)
        lines = [l for l in lines if len(re.findall(r"[A-Za-z]{2,}", l["text"])) >= 1]
        if lines:
            heights = [median(w["height"] for w in l["words"]) for l in lines]
            name_lines = [lines[0]]
            # a long name wraps onto a second line of the same type size
            if len(lines) > 2 and heights[1] >= heights[0] * 0.92 and lines[1]["top"] - lines[0]["bottom"] < heights[0]:
                name_lines.append(lines[1])
            rest = lines[len(name_lines):]
            out["hotelName"] = " ".join(clean_leading_icon(l["text"]) for l in name_lines).strip(" ,.-") or None
            if rest:
                out["address"] = " ".join(clean_leading_icon(l["text"]) for l in rest).strip(" ,.|") or None

        # Travel dates: each date sits directly under its own label
        def under(label: str, width: float = 95.0) -> str:
            b = find_phrase(panel, label)
            if not b:
                return ""
            near = _below(panel, b, b["left"] - 6, b["left"] + width, 34)
            near.sort(key=lambda w: (_mid_y(w), w["left"]))
            return " ".join(w["text"] for w in near)

        out["checkIn"] = parse_date(under("Check-in") or under("Check in"))
        out["checkOut"] = parse_date(under("Check-out") or under("Check out"))
        nights_label = find_phrase(panel, "Total Nights") or find_phrase(panel, "Nights")
        out["nights"] = _number_below(panel, nights_label, width=60, max_dy=34, gray=gray, left_off=48)

        # Room Type(s): room names, left-aligned under the heading; the
        # indented lines beneath each one are meal plans.
        rt = find_phrase(panel, "Room Type") or find_phrase(panel, "Room Types")
        tr = find_phrase(panel, "Total Rooms")
        tr_bottom_guess = (tr["top"] - 2) if tr else (rt["bottom"] + 260 if rt else 0)
        if rt:
            zone = [w for w in panel if _mid_y(w) > rt["bottom"] + 2 and _mid_y(w) < tr_bottom_guess]
            types: List[str] = []
            count = 0
            for line in group_lines(zone):
                if _text_left(line) > rt["left"] + 12:
                    continue  # indented: meal plan / inclusions
                text = clean_leading_icon(line["text"])
                if len(re.findall(r"[A-Za-z]{2,}", text)) < 1 or _MEAL_WORDS.fullmatch(text.strip()):
                    continue
                count += 1
                if text.lower() not in [t.lower() for t in types]:
                    types.append(text)
            out["roomType"] = ", ".join(types) or None
            out["_roomRows"] = count

        out["noOfRooms"] = _number_below(panel, tr, width=80, gray=gray)
        out["noOfAdults"] = _number_below(panel, find_phrase(panel, "Total Adult") or find_phrase(panel, "Total Adults"), width=80, gray=gray)
        out["noOfChildren"] = _number_below(panel, find_phrase(panel, "Total Children"), width=80, gray=gray)

    # ---- left column boxes
    cols = {}
    for key in ("Booking Id", "Leader", "Agent Ref"):
        b = find_phrase(main, key)
        if b:
            cols[key] = b
    all_label_lefts = sorted({round(b["left"]) for b in cols.values()})

    def col_bounds(box: Dict[str, float]) -> Tuple[float, float]:
        rights = [l for l in all_label_lefts if l > box["left"] + 40]
        gaps = [b - a for a, b in zip(all_label_lefts, all_label_lefts[1:]) if b - a > 40]
        pitch = min(gaps) if gaps else 160.0  # columns are evenly spaced; the last one is as wide as the others
        return box["left"] - 6, (rights[0] - 6 if rights else box["left"] + pitch - 10)

    other_labels = [find_phrase(main, k) for k in ("Booking Status", "Booking Date", "Deadline Date", "Guest Details", "Voucher No", "Hotel Conf", "Destination", "Agent Ref")]

    def value_lines(key: str, stop_keys: Sequence[str], max_dy: float = 90.0) -> List[Line]:
        b = cols.get(key) or find_phrase(main, key)
        if not b:
            return []
        lo, hi = col_bounds(b)
        stop = b["bottom"] + max_dy
        for sk in stop_keys:
            sb = find_phrase([w for w in main if lo <= w["left"] < hi], sk, after_top=b["bottom"] + 2)
            if sb:
                stop = min(stop, sb["top"] - 2)
        return group_lines([w for w in main if lo <= w["left"] < hi and _mid_y(w) > b["bottom"] + 2 and _mid_y(w) < stop])

    all_stops = ["Booking Status", "Booking Date", "Deadline Date", "Guest Details", "Voucher No", "Hotel Conf", "Destination", "Agent Ref", "Leader"]
    bid_lines = value_lines("Booking Id", all_stops, max_dy=60)
    code = ""
    if bid_lines:
        code = re.sub(r"[^A-Za-z0-9\-]", "", "".join(w["text"] for w in bid_lines[0]["words"])).upper()
    b = cols.get("Booking Id")
    if len(code) < 6 and gray is not None and b:
        # the box's value is small type inside a bordered field: read it close-up
        lo, hi = col_bounds(b)
        text = read_strip(gray, lo + 10, b["bottom"] + 6, hi - 6, b["bottom"] + 40, _CODE_WHITELIST)
        code = re.sub(r"[^A-Z0-9]", "", (text or "").upper())
    out["confirmationNumber"] = code if len(code) >= 5 else None

    dest = find_phrase(main, "Destination")
    if dest and cols:
        lo, hi = col_bounds(cols.get("Agent Ref") or {"left": dest["left"]})
        lo = dest["left"] - 6
        hi = dest["left"] + (min([b - a for a, b in zip(all_label_lefts, all_label_lefts[1:]) if b - a > 40] or [160.0]) - 10)
        dl = group_lines([w for w in main if lo <= w["left"] < hi and _mid_y(w) > dest["bottom"] + 2 and _mid_y(w) < dest["bottom"] + 40])
        if dl:
            out["city"] = clean_leading_icon(dl[0]["text"]).strip(" ,.") or None

    lead_lines = value_lines("Leader", ["Guest Details"] + [k for k in all_stops if k != "Leader"], max_dy=60)
    if lead_lines:
        out["lead"] = clean_person_name(" ".join(l["text"] for l in lead_lines))

    guests: List[str] = []
    g_label = find_phrase(main, "Guest Details")
    if g_label and "Leader" in cols:
        lo, hi = col_bounds(cols["Leader"])
        zone = [w for w in main if lo <= w["left"] < hi and _mid_y(w) > g_label["bottom"] + 2]
        current: Optional[List[str]] = None
        prev_bottom = g_label["bottom"]
        for line in group_lines(zone):
            text = clean_person_name(line["text"]) or ""
            if not text:
                continue
            if _is_label_line(text) and not _TITLE_RE.match(text):
                break
            if _TITLE_RE.match(text):
                if current:
                    add_unique_name(guests, " ".join(current))
                current = [text]
            elif current and line["top"] - prev_bottom < 16 and len(current) < 3:
                current.append(text)  # the box wrapped a long name onto a second line
            else:
                break
            prev_bottom = line["bottom"]
        if current:
            add_unique_name(guests, " ".join(current))
    # The leader is also a traveller: make sure they are in the list once,
    # and use the titled spelling from the guest list for the lead field.
    lead = out["lead"]
    if lead:
        match = next((g for g in guests if name_key(g) == name_key(lead)), None)
        if match:
            out["lead"] = match
        else:
            guests.insert(0, lead)
    elif guests:
        out["lead"] = guests[0]
    out["guests"] = guests
    return out


def clean_leading_icon(text: str) -> str:
    """Drops a stray icon glyph / lone symbol read before a printed line."""
    return re.sub(r"^(?:[^A-Za-z0-9(]|\b[A-Za-z]\b\s)+\s*", "", text or "").strip()
