"""
Passport page layout helpers — everything that depends on *where* things are
printed rather than on the MRZ alone.

  * crop_to_bio_page: trims a photo/scan down to the data page using the MRZ
    position as the anchor (the MRZ always sits along the bottom of the bio
    page and is as wide as the page minus its margins), so the preview and the
    OCR input contain no desk, no neighbouring blank page and no white border.
  * read_value_rows: OCRs the printed value rows of the bio page one row at a
    time (far more accurate than one whole-page pass over a guilloche
    background) and returns them top-to-bottom.
  * extract_bio_viz: picks place of birth / place of issue / date of issue out
    of those rows, only when the row clearly is that field, and rejects
    garbage (lower-case noise, no vowels, too short, low engine confidence).
  * parse_back_page: label-based parsing of the endorsement/address page
    (father / mother / spouse / address / PIN / old passport).
  * derive_salutation: Mr / Mrs / Ms / Master from sex, age and spouse name.

Everything returned is a *suggestion* — callers flag it "OCR Extracted —
Please Verify"; nothing here marks data as verified.
"""
from __future__ import annotations

import re
from datetime import date
from typing import Any, Callable, Dict, List, Optional, Tuple

import cv2
import numpy as np

# Geometry of an ICAO TD3 bio page (125 x 88 mm) relative to the ink extent of
# its 44-character MRZ lines (first character's left edge to last character's
# right edge, ~111 mm). Calibrated on the Indian booklets in the test set.
_PAGE_W_OVER_MRZ_W = 1.125
_PAGE_ASPECT = 0.725  # page height / page width (88/125 plus a little for the page-top fold)
_MRZ_LEFT_MARGIN = 0.059
_MRZ_BOTTOM_MARGIN = 0.06
_CROP_MARGIN = 0.014
# A TD3 MRZ has 88 characters; the address block / barcode / stamps that also
# form stacked text strips measure well under 70 character-sized blobs.
_MRZ_MIN_CHARS = 70

_NOT_PLACE_WORDS = {
    "REPUBLIC", "INDIA", "PASSPORT", "SURNAME", "GIVEN", "NAMES", "NAME", "SEX", "DATE", "BIRTH",
    "PLACE", "ISSUE", "EXPIRY", "NATIONALITY", "TYPE", "CODE", "COUNTRY", "NUMBER", "AUTHORITY",
    "INDIAN", "FEMALE", "MALE", "OFFICE", "REGIONAL",
}
_VOWELS = set("AEIOUY")


# ---------------------------------------------------------------------------
# Crop
# ---------------------------------------------------------------------------


def _mrz_candidate_lines(gray: np.ndarray):
    """Wide, thin ink strips (candidate MRZ lines) on a downscaled copy.
    Returns (small_gray, scale, raw_ink_mask, [(x, y, w, h), ...])."""
    h0, w0 = gray.shape[:2]
    scale = 1200.0 / max(w0, h0) if max(w0, h0) > 1200 else 1.0
    small = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA) if scale != 1.0 else gray
    h, w = small.shape[:2]
    blur = cv2.GaussianBlur(small, (3, 3), 0)
    blackhat = cv2.morphologyEx(blur, cv2.MORPH_BLACKHAT, cv2.getStructuringElement(cv2.MORPH_RECT, (15, 15)))
    _, ink = cv2.threshold(blackhat, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)
    joined = cv2.morphologyEx(ink, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (max(15, w // 40), 3)))
    contours, _ = cv2.findContours(joined, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    lines = []
    for c in contours:
        x, y, cw, ch = cv2.boundingRect(c)
        if ch < 6 or ch > 0.06 * max(w, h) or cw < 0.15 * max(w, h) or cw / float(ch) < 8:
            continue
        lines.append((x, y, cw, ch))
    return small, scale, ink, lines


def _tighten_to_characters(ink: np.ndarray, box: Tuple[int, int, int, int]) -> Tuple[Tuple[int, int, int, int], int]:
    """Shrinks a candidate strip to the character-sized blobs inside it
    (drops page-edge shading / stamps merged into the strip). Returns the new
    box and the number of character-like blobs found."""
    x, y, w, h = box
    pad = 3
    ys, xs = max(0, y - pad), max(0, x - pad)
    roi = ink[ys:y + h + pad, xs:x + w + pad]
    n, _, stats, _ = cv2.connectedComponentsWithStats(roi, connectivity=8)
    comps = [tuple(int(v) for v in stats[i][:4]) for i in range(1, n) if stats[i][3] >= 5 and stats[i][2] <= 2.4 * stats[i][3]]
    if len(comps) < 20:
        return box, len(comps)
    med_h = float(np.median([c[3] for c in comps]))
    keep = [c for c in comps if 0.6 * med_h <= c[3] <= 1.5 * med_h]
    if len(keep) < 20:
        return box, len(keep)
    kx0 = min(c[0] for c in keep)
    ky0 = min(c[1] for c in keep)
    kx1 = max(c[0] + c[2] for c in keep)
    ky1 = max(c[1] + c[3] for c in keep)
    return (xs + kx0, ys + ky0, kx1 - kx0, ky1 - ky0), len(keep)


def _find_mrz(gray: np.ndarray):
    """(nchars, box_in_small_coords, ink, scale) of the best MRZ-like pair of
    text strips, or None."""
    small, scale, ink, lines = _mrz_candidate_lines(gray)
    best = None
    for i, a in enumerate(lines):
        for b in lines[i + 1:]:
            top, bot = (a, b) if a[1] < b[1] else (b, a)
            gap = bot[1] - (top[1] + top[3])
            wmax = max(a[2], b[2])
            if not (
                abs(a[0] - b[0]) <= 0.05 * wmax
                and abs(a[2] - b[2]) <= 0.2 * wmax
                and -0.8 * min(a[3], b[3]) <= gap <= 3 * max(a[3], b[3])
                and abs(a[1] - b[1]) >= 0.4 * min(a[3], b[3])
            ):
                continue
            x0 = min(a[0], b[0])
            x1 = max(a[0] + a[2], b[0] + b[2])
            box, nchars = _tighten_to_characters(ink, (x0, top[1], x1 - x0, bot[1] + bot[3] - top[1]))
            if nchars < _MRZ_MIN_CHARS or box[2] / float(max(box[3], 1)) < 6.0:
                continue
            if best is None or nchars > best[0]:
                best = (nchars, box, ink, scale)
    return best


def locate_mrz_ink(gray: np.ndarray) -> Optional[Tuple[int, int, int, int]]:
    """(x, y, w, h) in the coordinates of ``gray`` of the two-line MRZ block,
    tight around the printed characters. Unlike the block detector in
    mrz_reader it has no minimum width relative to the image, so a small
    passport lying on a large A4 scan is found too, and it measures the
    character ink itself (so a dark page edge just below the MRZ does not
    stretch the box). Of all pairs of stacked, equally long text strips the
    one with the most character-like blobs wins (an MRZ has ~88). None when
    there is no such pair."""
    found = _find_mrz(gray)
    if found is None:
        return None
    _, (x, y, w, h), _, scale = found
    inv = 1.0 / scale
    return int(x * inv), int(y * inv), int(w * inv), int(h * inv)


def mrz_skew_angle(gray: np.ndarray) -> Optional[float]:
    """Skew of the passport page in degrees, measured on the MRZ text lines
    themselves (the page's own printing, unaffected by a skewed scanner sheet
    or desk behind it). The sign matches ocr_runner.deskew_image: pass the
    value straight to it. None when no MRZ is found."""
    found = _find_mrz(gray)
    if found is None:
        return None
    _, (x, y, w, h), ink, _ = found
    pad = 4
    ys, xs = max(0, y - pad), max(0, x - pad)
    roi = ink[ys:y + h + pad, xs:x + w + pad]
    n, _, stats, cents = cv2.connectedComponentsWithStats(roi, connectivity=8)
    pts = np.array(
        [cents[i] for i in range(1, n) if stats[i][3] >= 5 and stats[i][2] <= 2.4 * stats[i][3]], dtype=np.float64
    )
    if len(pts) < 40:
        return None
    centered = pts - pts.mean(axis=0)
    cov = np.cov(centered.T)
    vals, vecs = np.linalg.eigh(cov)
    vx, vy = vecs[:, int(np.argmax(vals))]
    if vals.max() < 4.0 * max(vals.min(), 1e-6):
        return None  # not an elongated block — no reliable direction
    angle = float(np.degrees(np.arctan2(vy, vx)))
    if angle > 90:
        angle -= 180
    if angle <= -90:
        angle += 180
    if abs(angle) > 20:
        return None
    return angle


def bio_page_box(mrz_box: Tuple[int, int, int, int], image_shape: Tuple[int, int]) -> Tuple[int, int, int, int]:
    """(x0, y0, x1, y1) of the bio page implied by the MRZ ink box, clamped to
    the image, with a small safety margin so nothing printed is ever cut."""
    img_h, img_w = image_shape[:2]
    mx, my, mw, mh = mrz_box
    left = mx - _MRZ_LEFT_MARGIN * mw
    width = _PAGE_W_OVER_MRZ_W * mw
    bottom = my + mh + _MRZ_BOTTOM_MARGIN * mw
    top = bottom - _PAGE_ASPECT * width
    m = _CROP_MARGIN * mw
    return (
        int(max(0, left - m)),
        int(max(0, top - m)),
        int(min(img_w, left + width + m)),
        int(min(img_h, bottom + m)),
    )


def _crop_result(img, cropped, box, return_box):
    return (img, cropped, box) if return_box else (img, cropped)


def find_mrz_rotation(bgr: np.ndarray, rotate: Callable[[np.ndarray, int], np.ndarray]) -> Optional[int]:
    """The rotation (0/90/180/270, as ``rotate`` defines it) at which a TD3
    MRZ block lies horizontally in the lower half of the image - i.e. the page
    is upright. None when no MRZ-like block exists at any rotation (which also
    means a page that is not a data page, so the costly MRZ readers can be
    skipped). Fast: four downscaled morphology passes."""
    best: Optional[Tuple[int, int]] = None
    for rot in (0, 90, 180, 270):
        g = cv2.cvtColor(rotate(bgr, rot), cv2.COLOR_BGR2GRAY)
        found = _find_mrz(g)
        if found is None:
            continue
        nchars, (x, y, w, h), _, scale = found
        cy = (y + h / 2.0) * (1.0 / scale) / g.shape[0]
        if cy < 0.5:
            continue  # upside-down: the same block is also found 180 degrees away
        if best is None or nchars > best[0]:
            best = (nchars, rot)
    return best[1] if best else None


def crop_to_bio_page(bgr: np.ndarray, return_box: bool = False):
    """Crops to the passport data page, anchored on the MRZ. Returns
    (image, cropped). Uncertain input is left whole rather than risking a
    cut-off photo or number: the MRZ must be in the lower part of the image,
    and the crop is only kept when the MRZ found again inside it sits where a
    TD3 page puts it (centred, close to the bottom edge)."""
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    try:
        box = locate_mrz_ink(gray)
    except Exception:
        return _crop_result(bgr, False, None, return_box)
    if box is None:
        return _crop_result(bgr, False, None, return_box)
    img_h, img_w = bgr.shape[:2]
    mx, my, mw, mh = box
    if my + mh / 2.0 < img_h * 0.45 or mw / float(max(mh, 1)) < 5.0:
        return _crop_result(bgr, False, None, return_box)
    x0, y0, x1, y1 = bio_page_box(box, bgr.shape)
    if (x1 - x0) < 0.9 * mw or (y1 - y0) < 0.6 * mw:
        return _crop_result(bgr, False, None, return_box)
    if x0 <= 0.01 * img_w and y0 <= 0.01 * img_h and x1 >= 0.99 * img_w and y1 >= 0.99 * img_h:
        return _crop_result(bgr, False, None, return_box)
    cropped = bgr[y0:y1, x0:x1]
    # Validate: the MRZ must still be found, spanning most of the width.
    again = locate_mrz_ink(cv2.cvtColor(cropped, cv2.COLOR_BGR2GRAY))
    if again is None:
        return _crop_result(bgr, False, None, return_box)
    ax, ay, aw, ah = again
    ch_, cw_ = cropped.shape[:2]
    if aw < 0.7 * cw_ or ay + ah < 0.8 * ch_:
        return _crop_result(bgr, False, None, return_box)
    return _crop_result(cropped, True, (x0, y0, x1, y1), return_box)


# ---------------------------------------------------------------------------
# Value rows of the bio page
# ---------------------------------------------------------------------------


def _row_bands(dark: np.ndarray, min_height: int) -> List[Tuple[int, int]]:
    """Horizontal bands of dark ink (the printed values are dark; the bilingual
    labels are pale blue and fall below the threshold)."""
    prof = dark.sum(axis=1) / 255.0
    rows: List[Tuple[int, int]] = []
    start: Optional[int] = None
    for i, v in enumerate(prof):
        if v > 6 and start is None:
            start = i
        elif v <= 6 and start is not None:
            if i - start >= min_height:
                rows.append((start, i))
            start = None
    if start is not None and len(prof) - start >= min_height:
        rows.append((start, len(prof)))
    return rows


def _ocr_strip(strip: np.ndarray) -> Optional[Tuple[str, float]]:
    import pytesseract

    scaled = cv2.resize(strip, None, fx=4, fy=4, interpolation=cv2.INTER_LANCZOS4)
    lo, hi = np.percentile(scaled, [1, 60])
    stretched = np.clip((scaled - lo) * 255.0 / max(hi - lo, 1), 0, 255).astype(np.uint8)
    best: Optional[Tuple[str, float]] = None
    for variant in (stretched, cv2.GaussianBlur(stretched, (5, 5), 0)):
        padded = cv2.copyMakeBorder(variant, 12, 12, 12, 12, cv2.BORDER_CONSTANT, value=255)
        try:
            data = pytesseract.image_to_data(padded, config="--oem 3 --psm 7", output_type=pytesseract.Output.DICT)
        except Exception:
            continue
        words, confs = [], []
        for t, c in zip(data["text"], data["conf"]):
            t = (t or "").strip()
            try:
                c = float(c)
            except (TypeError, ValueError):
                continue
            if t and c >= 0:
                words.append(t)
                confs.append(c)
        if words:
            cand = (" ".join(words), sum(confs) / len(confs))
            if best is None or cand[1] > best[1]:
                best = cand
    return best


def read_value_rows(bgr: np.ndarray, mrz_top: Optional[int] = None) -> List[Dict[str, Any]]:
    """OCRs the left data column of the bio page (the part beside the photo,
    where surname, given names, date of birth, place of birth, place of issue
    and date of issue are printed) row by row. Returns
    [{"y": int, "text": str, "conf": float}] top-to-bottom. Local Tesseract
    only; returns [] when it is unavailable."""
    try:
        import pytesseract  # noqa: F401
    except Exception:
        return []
    h, w = bgr.shape[:2]
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    x0, x1 = int(w * 0.35), int(w * 0.70)
    x1_wide = int(w * 0.84)
    y0 = int(h * 0.10)
    y1 = int(mrz_top - 4) if mrz_top else int(h * 0.86)
    if y1 - y0 < 40 or x1 - x0 < 80:
        return []
    col = gray[y0:y1, x0:x1]
    dark = (col < 165).astype(np.uint8) * 255
    dark = cv2.dilate(dark, cv2.getStructuringElement(cv2.MORPH_RECT, (1, 5)))
    out: List[Dict[str, Any]] = []
    for a, b in _row_bands(dark, max(8, int(h * 0.01))):
        strip = col[max(0, a - 4):min(col.shape[0], b + 4), :]
        read = _ocr_strip(strip)
        if read:
            row = {"y": y0 + a, "text": read[0], "conf": read[1]}
            # A long place name ("KHALNE DHULE, MAHARASHTRA") runs past the
            # narrow column; the same band read wider is offered as an
            # alternative that extract_bio_viz uses only when it is cleaner.
            wide = _ocr_strip(gray[y0 + max(0, a - 4):y0 + min(col.shape[0], b + 4), x0:x1_wide])
            if wide:
                row["wideText"], row["wideConf"] = wide
            out.append(row)
    return out


def clean_place(text: str, min_conf: float, conf: float, exclude: Optional[set] = None) -> Optional[str]:
    """A printed place name, or None when the row is not trustworthy. The
    value must be upper-case; trailing specks (lower-case or one-character
    tokens) are dropped, a row that STARTS with lower-case text is a label
    row, and the result needs 3+ letters, a vowel in every word, and must not
    be a label word or a name from the MRZ. A comma is kept: 'KUDAL,
    MAHARASHTRA'."""
    if conf < min_conf:
        return None
    text = re.sub(r"[^A-Za-z ,.\-]", " ", text or "")
    text = re.sub(r"\s+", " ", text).strip()
    tokens = text.split(" ")
    while tokens and (re.search(r"[a-z]", tokens[-1]) or len(re.sub(r"[^A-Za-z]", "", tokens[-1])) < 2):
        tokens.pop()
    if not tokens or re.search(r"[a-z]", " ".join(tokens)):
        return None
    cleaned = re.sub(r"\s*,\s*", ", ", " ".join(tokens)).strip(" ,.-")
    words = [w for w in re.split(r"[\s,.\-]+", cleaned.upper()) if w]
    if not words or sum(len(w) for w in words) < 3:
        return None
    if any(not (set(w) & _VOWELS) and len(w) >= 3 for w in words):
        return None
    if any(w in _NOT_PLACE_WORDS for w in words):
        return None
    if exclude and any(w in exclude for w in words):
        return None
    if len(words) > 5:
        return None
    return cleaned.upper()


def _completes(narrow: str, wide: str) -> bool:
    """True when `wide` is `narrow` with its last word completed (the narrow
    column cut it off): same words before it, and the last word of `wide`
    starts with the last word of `narrow` and is longer."""
    nw = re.split(r"[\s,]+", narrow.strip(" ,"))
    ww = re.split(r"[\s,]+", wide.strip(" ,"))
    if len(nw) != len(ww) or not nw:
        return False
    return nw[:-1] == ww[:-1] and len(nw[-1]) >= 3 and ww[-1].startswith(nw[-1]) and len(ww[-1]) > len(nw[-1])


_LABEL_BIRTH = re.compile(r"b[il1]rth|girth|irth", re.I)
_LABEL_ISSUE = re.compile(r"[il1t]?ssue|iésue", re.I)


def extract_bio_viz(
    rows: List[Dict[str, Any]],
    mrz: Dict[str, Any],
    dates_in_rows: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Place of birth / place of issue from the value rows.

    Nothing is guessed from thin air. The surname / given-name rows (matching
    the MRZ) or the date-of-birth row anchor the position; the clean
    upper-case place rows after it are, in printed order, place of birth then
    place of issue. The pale label printed above each value (when the OCR
    managed to read any of it - 'Place of Birth', 'Place of Issue') decides
    which is which, and overrides the order. A single clean row with no usable
    label is not assigned."""
    from passport_crosscheck import viz_dates, word_confirmed

    result: Dict[str, Any] = {"placeOfBirth": None, "placeOfIssue": None, "dateOfIssue": None}
    if not rows:
        return result
    names = set()
    for key in ("surname", "givenNames"):
        for tok in re.split(r"[\s<]+", (mrz.get(key) or "").upper()):
            if len(tok) >= 3:
                names.add(tok)

    dob = mrz.get("dateOfBirth")
    anchor_idx = -1
    for i, row in enumerate(rows):
        if dob and dob in viz_dates(row["text"]):
            anchor_idx = i
            break
    if anchor_idx < 0:
        for i, row in enumerate(rows):
            toks = re.findall(r"[A-Z]{3,}", row["text"].upper())
            if toks and not re.search(r"[a-z]{3,}", row["text"]) and any(word_confirmed(t, list(names)) for t in toks):
                anchor_idx = max(anchor_idx, i)
    if anchor_idx < 0:
        return result
    candidates: List[Tuple[int, str, float, Optional[str]]] = []
    for i in range(anchor_idx + 1, len(rows)):
        row = rows[i]
        if viz_dates(row["text"]):
            continue
        place = clean_place(row["text"], min_conf=40.0, conf=row["conf"], exclude=names)
        wide_place = clean_place(row.get("wideText", ""), min_conf=40.0, conf=row.get("wideConf", 0.0), exclude=names)
        if place and wide_place and _completes(place, wide_place):
            place = wide_place
        if not place:
            continue
        label_text = rows[i - 1]["text"] if i - 1 > anchor_idx or i - 1 >= 0 else ""
        kind = None
        if re.search(r"place", label_text, re.I) or _LABEL_BIRTH.search(label_text) or _LABEL_ISSUE.search(label_text):
            if _LABEL_BIRTH.search(label_text) and not re.search(r"issue", label_text, re.I):
                kind = "birth"
            elif _LABEL_ISSUE.search(label_text) and not _LABEL_BIRTH.search(label_text):
                kind = "issue"
        candidates.append((row["y"], place, row["conf"], kind))
    assigned: Dict[str, Tuple[str, float]] = {}
    leftovers = []
    for _, place, conf, kind in candidates:
        if kind and kind not in assigned:
            assigned[kind] = (place, conf)
        else:
            leftovers.append((place, conf))
    for place, conf in leftovers:
        if len(candidates) < 2 and not assigned:
            break  # one unlabelled row: could be either - not assigned
        slot = "birth" if "birth" not in assigned else ("issue" if "issue" not in assigned else None)
        # With one label known the other row is the remaining slot.
        if slot:
            assigned[slot] = (place, conf)
    if "birth" in assigned:
        result["placeOfBirth"] = {"value": assigned["birth"][0], "confidence": min(0.7, assigned["birth"][1] / 100.0)}
    if "issue" in assigned:
        result["placeOfIssue"] = {"value": assigned["issue"][0], "confidence": min(0.7, assigned["issue"][1] / 100.0)}
    return result


# ---------------------------------------------------------------------------
# Back (endorsement / address) page
# ---------------------------------------------------------------------------
#
# On Indian passports the labels of this page are printed in pale blue and the
# values in dark dot-matrix type. Reading only the DARK ink (a plain grey-level
# threshold) therefore gives clean value lines without the labels, the guilloche
# background or the stamps' colours, and the values come in a fixed order:
#
#     [barcode number]  father  mother  [spouse]  address lines...
#     PIN:nnnnnn,STATE,COUNTRY   old-passport-no  date  place   file-no
#
# so the parser is positional, anchored on the PIN line, and does not depend on
# the labels being legible.

_BACK_MARKERS = re.compile(r"(FATHER|MOTHER|SPOUSE|LEGAL\s+GUARDIAN|ADDRESS|OLD\s*PASSPORT|FILE\s*NO|EMIGRATION|CHECK\s+REQUIRED)", re.I)
_PIN_RE = re.compile(r"P\s*I\s*N\s*[:;.\-]?\s*([0-9OoIlSB]{6})\b", re.I)
_OLD_PASSPORT_RE = re.compile(
    r"(?P<num>[A-Z0-9\u00a3$]{6,9})\s+(?P<d>\d{1,2}\s*[/.\-]\s*\d{1,2}\s*[/.\-]\s*\d{4})(?:\s+(?P<place>[A-Z][A-Z .]{2,}))?"
)
_NOISE_LINE = re.compile(
    r"EMIGRATION|CHECK|REQUIRED|PASSPORT|SURNAME|GIVEN|NAME\s+OF|LEGAL|GUARDIAN|SPOUSE|MOTHER|FATHER|ADDRESS|BARCODE|FILE\s*NO", re.I
)
_INK_THRESHOLD = 110


def ink_binary(gray: np.ndarray, threshold: int = _INK_THRESHOLD) -> np.ndarray:
    """Black text on white: keeps only dark ink (printed values), drops the
    pale-blue labels, background pattern and light stamps."""
    return np.where(gray < threshold, 0, 255).astype(np.uint8)


def looks_like_back_page(text: str) -> bool:
    return len(set(m.group(1).upper().split()[0] for m in _BACK_MARKERS.finditer(text or ""))) >= 2


def _coerce_digits(s: str) -> str:
    return s.translate(str.maketrans({"O": "0", "o": "0", "I": "1", "l": "1", "S": "5", "B": "8", "Z": "2", "G": "6"}))


def _name_value(line: str) -> Optional[str]:
    """An upper-case personal name from the start of a line. Trailing junk
    (a half-read label such as '/ Surname', stray marks) is dropped when at
    least two clean words precede it; a line with digits or commas is not a
    name, and neither is a line of 2-letter fragments (background noise)."""
    line = re.sub(r"^[^A-Za-z0-9]+|[^A-Za-z0-9]+$", "", line or "")
    if re.search(r"[\d,]", line):
        return None
    tokens = re.sub(r"[^A-Za-z.' \-]", " ", line).split()
    words: List[str] = []
    junk_after = False
    for tok in tokens:
        letters = re.sub(r"[^A-Za-z]", "", tok)
        ok = bool(letters) and letters.isupper() and (
            (len(letters) >= 3 and (set(letters) & _VOWELS)) or (len(letters) == 1 and bool(words))
        )
        if ok and not junk_after:
            words.append(letters)
        else:
            junk_after = True
    if not words or max(len(w) for w in words) < 4:
        return None
    if junk_after and len(words) < 2:
        return None
    if _NOISE_LINE.search(" ".join(words)):
        return None
    return " ".join(words)


def _is_barcode_line(line: str) -> bool:
    compact = re.sub(r"[^A-Za-z0-9]", "", line)
    return 7 <= len(compact) <= 10 and sum(c.isdigit() for c in compact) >= 4 and not re.search(r"[ ,]", line.strip())


def _clean_address_line(line: str) -> str:
    """Upper-cased address text with OCR specks removed. The values are printed
    in capitals, so a lower-case token is a misread speck; trailing one-letter
    tokens are dropped too (a stray 'a' after 'CIVIL ROAD')."""
    line = re.sub(r"[^A-Za-z0-9 ,./\-]", " ", line)
    parts = [p for p in re.split(r",", line)]
    cleaned_parts: List[str] = []
    for part in parts:
        toks = part.split()
        while toks and (re.search(r"[a-z]", toks[-1]) or (len(toks[-1]) == 1 and toks[-1].isalpha())) and len(toks) > 1:
            toks.pop()
        if len(toks) == 1 and re.search(r"[a-z]", toks[0]) and len(cleaned_parts) > 0:
            toks = []
        cleaned_parts.append(" ".join(toks))
    line = ", ".join(p for p in cleaned_parts if p)
    line = re.sub(r"\s+", " ", line).strip(" ,.-")
    return line.upper()


def _iso_from_ddmmyyyy(text: str) -> Optional[str]:
    m = re.match(r"\s*(\d{1,2})\s*[/.\-]\s*(\d{1,2})\s*[/.\-]\s*(\d{4})", text or "")
    if not m:
        return None
    try:
        return date(int(m.group(3)), int(m.group(2)), int(m.group(1))).isoformat()
    except ValueError:
        return None


def normalise_old_passport_number(raw: str) -> Tuple[str, bool]:
    """(number, firstCharCertain). Indian numbers are one letter + seven
    digits; letter-for-digit look-alikes in the digit part are corrected. A
    first character that came out as a digit is left as read (it could be a
    letter such as G/B/S/O) and reported as uncertain."""
    t = re.sub(r"[^A-Za-z0-9\u00a3$]", "", raw or "").replace("\u00a3", "E").replace("$", "S").upper()
    if len(t) == 8:
        head, tail = t[0], _coerce_digits(t[1:])
        return head + tail, head.isalpha()
    return t, False


def parse_back_page(text: str) -> Dict[str, Any]:
    """{fatherName, motherName, spouseName, addressLine1, addressLine2,
    addressCity, addressState, addressPincode, addressCountry,
    oldPassportNumber, oldPassportIssueDate (ISO), oldPassportPlace,
    oldPassportNumberCertain} - each None when not found, plus
    "recognised": True when the text really looks like an address page (a PIN
    line, an old-passport line, or two or more name lines)."""
    keys = (
        "fatherName", "motherName", "spouseName", "addressLine1", "addressLine2", "addressCity",
        "addressState", "addressPincode", "addressCountry", "oldPassportNumber", "oldPassportIssueDate",
        "oldPassportPlace",
    )
    out: Dict[str, Any] = {k: None for k in keys}
    out["oldPassportNumberCertain"] = None
    out["recognised"] = False
    lines = [re.sub(r"\s+", " ", ln).strip() for ln in (text or "").splitlines()]
    lines = [ln for ln in lines if re.sub(r"[^A-Za-z0-9]", "", ln)]

    pin_i = next((i for i, ln in enumerate(lines) if _PIN_RE.search(ln)), None)
    if pin_i is not None:
        m = _PIN_RE.search(lines[pin_i])
        out["addressPincode"] = _coerce_digits(m.group(1))
        tail = [re.sub(r"[^A-Za-z ]", "", t).upper().strip() for t in re.split(r"[,;]", lines[pin_i][m.end():])]
        tail = [t for t in tail if len(t) >= 3]
        if tail:
            out["addressState"] = tail[0]
        if len(tail) >= 2:
            out["addressCountry"] = "INDIA" if tail[1].startswith("INDIA") else tail[1].split()[0]
        if out["addressState"]:
            out["addressState"] = out["addressState"].split(" INDIA")[0].strip()

    # Old passport: number, date and place on one line (after the PIN line).
    start = (pin_i + 1) if pin_i is not None else 0
    for ln in lines[start:]:
        m = _OLD_PASSPORT_RE.search(ln.upper())
        if not m:
            continue
        iso = _iso_from_ddmmyyyy(m.group("d"))
        if not iso:
            continue
        number, certain = normalise_old_passport_number(m.group("num"))
        if len(number) < 7:
            continue
        out["oldPassportNumber"] = number
        out["oldPassportNumberCertain"] = certain and len(number) == 8
        out["oldPassportIssueDate"] = iso
        # Printed dates are zero-padded (dd/mm/yyyy); a one-digit day or month
        # means a leading digit was lost (e.g. a pale-printed "1").
        out["oldPassportDateCertain"] = bool(re.match(r"\d{2}\s*[/.\-]\s*\d{2}\s*[/.\-]\s*\d{4}", m.group("d")))
        place = re.sub(r"[^A-Z ]", "", (m.group("place") or "").upper()).strip()
        if len(place) >= 3 and (set(place) & _VOWELS):
            out["oldPassportPlace"] = place
        break

    # Names and address: the lines before the PIN line, header/barcode noise removed.
    body_end = pin_i if pin_i is not None else len(lines)
    body = [ln for ln in lines[:body_end] if not _is_barcode_line(ln) and not _NOISE_LINE.search(ln)]
    names: List[str] = []
    idx = 0
    # The names are the first run of 2-3 consecutive name-like lines; anything
    # before them is header / stamp noise, anything after them is the address.
    start_i = next(
        (i for i in range(len(body) - 1) if _name_value(body[i]) and _name_value(body[i + 1])), None
    )
    if start_i is not None:
        idx = start_i
        while idx < len(body) and len(names) < 3:
            v = _name_value(body[idx])
            if not v:
                break
            names.append(v)
            idx += 1
    addr_lines = [_clean_address_line(ln) for ln in body[idx:]]
    addr_lines = [a for a in addr_lines if len(re.sub(r"[^A-Za-z0-9]", "", a)) >= 3 and not _NOISE_LINE.search(a)]
    if len(names) == 3 and not addr_lines and pin_i is not None:
        addr_lines = [names.pop()]  # the "third name" was really the address
    for key, value in zip(("fatherName", "motherName", "spouseName"), names):
        out[key] = value

    if addr_lines and pin_i is not None:
        last = [p.strip() for p in addr_lines[-1].split(",") if p.strip()]
        city = None
        if len(last) >= 2:
            city = last[-1]
            addr_lines[-1] = ", ".join(last[:-1])
        elif len(addr_lines) >= 2 and re.fullmatch(r"[A-Z]+( [A-Z]+)?", addr_lines[-1] or ""):
            city = addr_lines.pop()
        addr_lines = [a for a in addr_lines if a]
        if addr_lines:
            out["addressLine1"] = addr_lines[0]
        if len(addr_lines) > 1:
            out["addressLine2"] = ", ".join(addr_lines[1:])
        out["addressCity"] = city
    out["recognised"] = bool(out["addressPincode"] or out["oldPassportNumber"] or len(names) >= 2)
    return out


def score_back_text(text: str) -> int:
    markers = len(set(m.group(1).upper().split()[0] for m in _BACK_MARKERS.finditer(text or "")))
    words = sum(1 for w in re.findall(r"[A-Za-z]{4,}", text or "") if set(w.upper()) & _VOWELS)
    pins = len(_PIN_RE.findall(text or ""))
    return markers * 10 + pins * 15 + words


def read_back_page(
    bgr: np.ndarray,
    ocr: Callable[[np.ndarray], str],
    rotations: Tuple[int, ...] = (0, 270, 90, 180),
    rotate: Optional[Callable[[np.ndarray, int], np.ndarray]] = None,
) -> Optional[Dict[str, Any]]:
    """Finds the orientation of a page with no MRZ by reading its dark ink at
    each rotation, and parses it. Returns {rotation, text, parsed, score} for
    the first rotation that yields a recognised address page (best score
    otherwise), or None when nothing looks like text at all."""
    rotate = rotate or (lambda img, deg: np.ascontiguousarray(np.rot90(img, k=(deg // 90) % 4)))
    best: Optional[Dict[str, Any]] = None
    for rot in rotations:
        gray = cv2.cvtColor(rotate(bgr, rot), cv2.COLOR_BGR2GRAY)
        try:
            text = ocr(ink_binary(gray))
        except Exception:
            continue
        parsed = parse_back_page(text)
        score = score_back_text(text)
        cand = {"rotation": rot, "text": text, "parsed": parsed, "score": score}
        if parsed["recognised"] and (parsed["addressPincode"] or looks_like_back_page(text)):
            return cand
        if best is None or score > best["score"]:
            best = cand
    return best


def text_skew_angle(gray: np.ndarray) -> Optional[float]:
    """Skew (degrees, same sign convention as ocr_runner.deskew_image) of an
    upright page of printed text: the rotation that makes the dark ink's row
    profile the most 'peaky'. None when there is too little ink to tell."""
    h0, w0 = gray.shape[:2]
    scale = 900.0 / max(w0, h0) if max(w0, h0) > 900 else 1.0
    small = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA) if scale != 1.0 else gray
    ink = (small < _INK_THRESHOLD).astype(np.uint8) * 255
    if ink.sum() / 255.0 < 400:
        return None
    h, w = ink.shape
    center = (w / 2.0, h / 2.0)

    def score(angle: float) -> float:
        m = cv2.getRotationMatrix2D(center, angle, 1.0)
        rot = cv2.warpAffine(ink, m, (w, h), flags=cv2.INTER_NEAREST)
        prof = rot.sum(axis=1).astype(np.float64)
        return float(np.var(prof))

    coarse = max(np.arange(-6.0, 6.01, 0.5), key=score)
    fine = max(np.arange(coarse - 0.5, coarse + 0.51, 0.1), key=score)
    if score(fine) < 1.03 * score(0.0):
        return 0.0
    return float(fine)


def _trim_scanner_edges(gray: np.ndarray) -> Tuple[int, int, int, int]:
    """(top, bottom, left, right) after dropping near-black scanner-lid /
    page-edge bands that touch the image border."""
    h, w = gray.shape[:2]
    dark = gray < 70
    top, bottom, left, right = 0, h, 0, w
    limit_y, limit_x = int(h * 0.04), int(w * 0.04)
    while top < limit_y and dark[top, left:right].mean() > 0.5:
        top += 1
    while bottom - 1 > h - limit_y and dark[bottom - 1, left:right].mean() > 0.5:
        bottom -= 1
    while left < limit_x and dark[top:bottom, left].mean() > 0.5:
        left += 1
    while right - 1 > w - limit_x and dark[top:bottom, right - 1].mean() > 0.5:
        right -= 1
    return top, bottom, left, right


def _paper_box(bgr: np.ndarray) -> Optional[Tuple[int, int, int, int]]:
    """(x0, y0, x1, y1) of the scanned paper: the largest non-white region,
    ignoring scanner-edge bands and specks. None when it cannot be told apart
    from the background."""
    h, w = bgr.shape[:2]
    t, b, l, r = _trim_scanner_edges(cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY))
    sub = bgr[t:b, l:r]
    if sub.size == 0:
        return None
    soft = cv2.blur(sub.min(axis=2), (9, 9))
    mask = (soft < 253).astype(np.uint8) * 255
    k = max(9, int(min(sub.shape[:2]) * 0.04)) | 1
    # Join the pale paper and its printed pattern first, then drop thin
    # scanner-edge strips and specks.
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((k + 1, k + 1), np.uint8))
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((k, k), np.uint8))
    n, _, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    if n <= 1:
        return None
    i = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    x, y, bw, bh = (int(stats[i, c]) for c in (cv2.CC_STAT_LEFT, cv2.CC_STAT_TOP, cv2.CC_STAT_WIDTH, cv2.CC_STAT_HEIGHT))
    if bw * bh < 0.12 * h * w:
        return None
    return l + x, t + y, l + x + bw, t + y + bh


def crop_back_page(bgr: np.ndarray) -> Tuple[np.ndarray, bool]:
    """Crops an upright photo/scan of a booklet leaf to the one address page.
    Removes the scanner background and edge bands, then - when the leaf shows
    two pages stacked (the visa page above / below the address page) - splits
    at the gutter (searched around the middle) and keeps the half that holds
    the printed text. Unchanged when nothing can be told apart."""
    h, w = bgr.shape[:2]
    if h < 200 or w < 200:
        return bgr, False
    box = _paper_box(bgr)
    if box is None:
        return bgr, False
    x0, y0, x1, y1 = box
    paper = bgr[y0:y1, x0:x1]
    ph, pw = paper.shape[:2]
    changed = (ph < 0.97 * h) or (pw < 0.97 * w)
    if ph < 0.25 * h or pw < 0.25 * w:
        return bgr, False
    # A single landscape page (about 1.41:1) needs no split.
    if pw / ph >= 1.15:
        return (paper, True) if changed else (bgr, False)
    if not 1.1 <= ph / pw <= 1.9:
        return (paper, True) if changed else (bgr, False)

    gray = cv2.cvtColor(paper, cv2.COLOR_BGR2GRAY)
    cols = gray[:, int(pw * 0.15):int(pw * 0.85)].astype(np.float32)
    prof = np.median(cols, axis=1)  # median: ink (barcode, text) must not look like the gutter
    k = max(5, ph // 150) | 1
    prof = cv2.GaussianBlur(prof.reshape(-1, 1), (1, k * 3 | 1), 0).reshape(-1)
    lo, hi = int(ph * 0.38), int(ph * 0.62)
    idx = np.arange(lo, hi)
    cost = prof[lo:hi] + 150.0 * np.abs(idx - ph / 2.0) / ph
    i = int(idx[int(np.argmin(cost))])
    sat = paper.max(axis=2).astype(np.int16) - paper.min(axis=2).astype(np.int16)
    ink = (gray < _INK_THRESHOLD) & (sat < 60)  # printed text is neutral dark; coloured stamps are not
    my, mx = int(ph * 0.04), int(pw * 0.04)
    inner = ink[my:ph - my, mx:pw - mx]
    cut = i - my
    top_ink, bottom_ink = int(inner[:max(cut, 0)].sum()), int(inner[max(cut, 0):].sum())
    pad = int(ph * 0.01)
    out = paper[max(0, i - pad):] if bottom_ink >= top_ink else paper[:min(ph, i + pad)]
    if out.shape[0] < 0.25 * h:
        return paper, True
    return out, True


# ---------------------------------------------------------------------------
# Salutation
# ---------------------------------------------------------------------------


def age_on(dob_iso: Optional[str], today: Optional[date] = None) -> Optional[int]:
    if not dob_iso:
        return None
    try:
        d = date.fromisoformat(dob_iso)
    except ValueError:
        return None
    today = today or date.today()
    return today.year - d.year - ((today.month, today.day) < (d.month, d.day))


def derive_salutation(
    sex: Optional[str], dob_iso: Optional[str], spouse_name: Optional[str] = None, today: Optional[date] = None
) -> Optional[Dict[str, str]]:
    """{"value", "reason"} or None when sex is unknown. Rules: male adult →
    Mr, male minor → Master, female minor → Ms, female adult with a spouse
    printed on the passport → Mrs, other adult female → Ms (marital status is
    not otherwise on the passport). Never claims certainty — the field stays
    flagged for review."""
    s = (sex or "").upper()
    if s not in ("M", "F"):
        return None
    age = age_on(dob_iso, today)
    adult = age is None or age >= 18
    if s == "M":
        if adult:
            return {"value": "Mr", "reason": "Male, age 18 or over."}
        return {"value": "Master", "reason": f"Male, age {age}."}
    if not adult:
        return {"value": "Ms", "reason": f"Female, age {age}."}
    if spouse_name:
        return {"value": "Mrs", "reason": "Female adult with a spouse name printed on the passport."}
    return {"value": "Ms", "canBeMrs": True, "reason": "Female adult; no spouse name found on the scanned pages (use Mrs if married)."}
