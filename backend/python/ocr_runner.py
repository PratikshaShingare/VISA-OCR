"""
Khanna Travels & Holidays — Passport OCR & Processing Engine
==============================================================

Real, local, offline processing pipeline for a passport page:

    load -> orientation evaluation (0/90/180/270) -> deskew -> safe crop
         -> OCR -> MRZ line detection -> MRZ (ICAO TD3) parsing/validation
         -> field extraction (MRZ-authoritative, VIZ-fallback)
         -> structured result with per-field confidence

No passport image or extracted field is ever sent to a third-party API —
OCR runs locally via Tesseract, which is also why there is no API key to
keep out of the frontend (Phase 12 of the project instructions). Every
field returned here is a *proposal*: the frontend always shows
"OCR Extracted — Please Verify" and lets staff correct it before anything
is treated as verified (Phase 10 / Phase 19 — OCR never auto-verifies,
final say stays with staff).

Dependencies: opencv-python, numpy, pillow, pytesseract (+ the Tesseract
binary installed on the machine, for local/offline use), pypdfium2 (for
PDF passport uploads).

OCR engine: this pipeline no longer calls pytesseract directly — every OCR
call goes through ocr_providers.get_ocr_provider(), which is Tesseract
(local, offline, unchanged behaviour) on a staff member's own machine, or
Google Cloud Vision (cloud) when this backend is deployed on Vercel, where no
system OCR binary can be installed. See ocr_providers.py and
VERCEL_DEPLOYMENT.md. Nothing about the MRZ parsing, field extraction, or
confidence scoring below changed — only where the raw recognized text and
per-word confidences come from.
"""

from __future__ import annotations

import base64
import os
import re
import sys
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np
from PIL import Image

import ocr_providers

_provider = ocr_providers.get_ocr_provider()


def get_tesseract_status() -> Dict[str, Any]:
    """Backward-compatible alias — app.py's /api/health has always called
    this exact name. Kept so nothing else needs to change, but it now
    honestly reports whichever OCR engine is actually active (Tesseract or
    Google Cloud Vision), not necessarily literally Tesseract (project rule 9 —
    a health check must never claim the wrong engine is running)."""
    return get_ocr_engine_status()


def get_ocr_engine_status() -> Dict[str, Any]:
    """Real, live status of the active OCR engine. Used by /api/health so a
    person setting this up (or the app itself) can confirm OCR is genuinely
    usable without needing to run a full passport upload first to find
    out."""
    return _provider.status()


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SAFE_CROP_PADDING_PX = 25
ORIENTATIONS = (0, 90, 180, 270)
MRZ_CHARSET_RE = re.compile(r"[^A-Z0-9<]")
OLD_PASSPORT_LABEL_RE = re.compile(
    r"(?:OLD|PREVIOUS|FORMER)\s+PASSPORT\s*(?:NO\.?|NUMBER)?\s*[:\-]?\s*([A-Z0-9]{6,9})",
    re.IGNORECASE,
)
# Indian PIN codes are always exactly 6 digits — reliably extractable by
# pattern alone (unlike a full postal address), but still requires an
# explicit "PIN"/"PIN CODE" label so this never guesses at an unrelated
# 6-digit number (an MRZ fragment, a phone number) elsewhere on the page.
INDIA_PIN_LABEL_RE = re.compile(r"PIN\s*(?:CODE)?\s*[:\-]?\s*(\d{6})", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Image loading
# ---------------------------------------------------------------------------


def load_pages(path: str) -> List[Image.Image]:
    """Returns every page of the upload as a PIL image (RGB). A PDF yields
    one image per page; any other image file yields a single-item list."""
    ext = os.path.splitext(path)[1].lower()
    if ext == ".pdf":
        import pypdfium2 as pdfium

        pdf = pdfium.PdfDocument(path)
        pages = []
        for i in range(len(pdf)):
            bitmap = pdf[i].render(scale=300 / 72)  # ~300 DPI
            pages.append(bitmap.to_pil().convert("RGB"))
        return pages
    return [Image.open(path).convert("RGB")]


def pil_to_bgr(img: Image.Image) -> np.ndarray:
    return cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)


def bgr_to_base64_png(bgr: np.ndarray) -> str:
    ok, buf = cv2.imencode(".png", bgr)
    if not ok:
        raise ValueError("Failed to encode processed image.")
    return base64.b64encode(buf.tobytes()).decode("ascii")


# ---------------------------------------------------------------------------
# Text cleanup
# ---------------------------------------------------------------------------


# Common OCR misreads between visually-similar letters and digits. MRZ
# fields are strictly typed (nationality/issuing country/document type are
# letters-only; dates are digits-only) so which direction to coerce is
# known from the field, not guessed — this is what catches e.g. Tesseract
# reading the "O" in "UTO" as a zero (caught during testing, see
# backend/python/README.md).
_ALPHA_FIX = {"0": "O", "1": "I", "2": "Z", "5": "S", "6": "G", "8": "B"}
_NUMERIC_FIX = {v: k for k, v in _ALPHA_FIX.items()}


def _coerce_alpha(s: str) -> str:
    return "".join(_ALPHA_FIX.get(ch, ch) if ch.isdigit() else ch for ch in s)


def _coerce_numeric(s: str) -> str:
    return "".join(_NUMERIC_FIX.get(ch, ch) if ch.isalpha() else ch for ch in s)


def normalize_ocr_text(text: str) -> str:
    """Generic cleanup applied to all raw OCR output before further parsing:
    normalize curly quotes/dashes, collapse whitespace runs, uppercase is
    NOT applied here (names should keep their case) — callers that need
    uppercase (MRZ) do it themselves."""
    text = text.replace("‘", "'").replace("’", "'")
    text = text.replace("“", '"').replace("”", '"')
    text = text.replace("–", "-").replace("—", "-")
    text = re.sub(r"[ \t]+", " ", text)
    return text.strip()


def is_blank_page(gray: np.ndarray, std_threshold: float = 12.0) -> bool:
    """A near-blank passport page (inside cover, visa page) has very low
    pixel variance."""
    return float(gray.std()) < std_threshold


# ---------------------------------------------------------------------------
# Orientation, deskew, safe crop
# ---------------------------------------------------------------------------


def _rotate_90_multiple(bgr: np.ndarray, degrees: int) -> np.ndarray:
    degrees = degrees % 360
    if degrees == 0:
        return bgr
    if degrees == 90:
        return cv2.rotate(bgr, cv2.ROTATE_90_CLOCKWISE)
    if degrees == 180:
        return cv2.rotate(bgr, cv2.ROTATE_180)
    if degrees == 270:
        return cv2.rotate(bgr, cv2.ROTATE_90_COUNTERCLOCKWISE)
    raise ValueError("degrees must be one of 0/90/180/270")


def _ocr_score(gray: np.ndarray) -> Tuple[float, str]:
    """Runs the active OCR provider on a candidate orientation and returns a
    score combining mean word confidence, recognized text volume, and how
    MRZ-like the text looks ('<<' is essentially unique to MRZ lines)."""
    mean_conf, text = _provider.ocr_mean_confidence_and_text(gray, config=FULL_PAGE_TESSERACT_CONFIG)
    mrz_hits = text.count("<<")
    score = mean_conf + min(len(text), 400) * 0.1 + mrz_hits * 25
    return score, text


def _texts_substantially_equal(a: str, b: str) -> bool:
    """True when two OCR passes recognized essentially the same content —
    used to tell a genuine rotation ambiguity (two DIFFERENT readings that
    happen to score similarly) apart from a numeric tie that isn't actually
    ambiguous at all (the same reading, twice)."""
    if not a and not b:
        return True
    norm_a = re.sub(r"\s+", "", a)
    norm_b = re.sub(r"\s+", "", b)
    if norm_a == norm_b:
        return True
    import difflib

    return difflib.SequenceMatcher(None, norm_a, norm_b).ratio() >= 0.92


def evaluate_orientations(bgr: np.ndarray) -> Dict[str, Any]:
    """Tries all four right-angle orientations and scores each with a real
    OCR pass rather than assuming a fixed orientation. Returns the winning
    rotation plus every candidate's score, so the caller/frontend can flag
    a genuinely ambiguous result instead of silently guessing.

    Root-cause fix: a very clean/high-contrast page can legitimately score
    identically (or near-identically) at two different rotations — observed
    directly on a synthetic test passport, where Tesseract's own automatic
    layout analysis (independent of this pipeline's explicit rotation loop)
    recognized the exact same correct text at both 0° and 90°, tying the
    score exactly. Flagging that as "orientation could not be determined"
    would be an overly strict false alarm: nothing is actually in doubt,
    since re-reading the runner-up rotation would show staff the identical
    result. Genuine ambiguity is when two DIFFERENT candidate rotations
    both score plausibly — i.e. the page could honestly be read either way
    with different results — which is exactly the case a human needs to
    resolve."""
    scores: Dict[int, float] = {}
    texts: Dict[int, str] = {}
    for rot in ORIENTATIONS:
        rotated = _rotate_90_multiple(bgr, rot)
        gray = cv2.cvtColor(rotated, cv2.COLOR_BGR2GRAY)
        score, text = _ocr_score(gray)
        scores[rot] = score
        texts[rot] = text

    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    best_rot, best_score = ranked[0]
    second_rot, second_score = ranked[1] if len(ranked) > 1 else (None, 0.0)

    # Ambiguous when the winner isn't clearly ahead, or when nothing scored
    # highly at all (likely a blank/unreadable page rather than a
    # confidently-wrong guess) — but only when the top two candidates
    # actually disagree on what the page says.
    gap = (best_score - second_score) / best_score if best_score > 0 else 0.0
    runner_up_is_same_reading = second_rot is not None and _texts_substantially_equal(texts[best_rot], texts[second_rot])
    needs_review = best_score < 8.0 or (gap < 0.12 and not runner_up_is_same_reading)

    return {
        "bestRotation": best_rot,
        "scores": {str(k): round(v, 2) for k, v in scores.items()},
        "needsReview": needs_review,
    }


def detect_skew_angle(bgr: np.ndarray) -> float:
    """Estimates the small in-plane skew (document photographed slightly
    crooked, not a 90°-multiple misorientation) using the minimum-area
    bounding rectangle of the foreground (thresholded) pixels."""
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1]
    coords = cv2.findNonZero(thresh)
    if coords is None or len(coords) < 50:
        return 0.0

    angle = cv2.minAreaRect(coords)[-1]
    # cv2.minAreaRect's angle convention differs by OpenCV version/shape;
    # normalize to a signed angle in (-45, 45] representing how far the
    # document is rotated from axis-aligned.
    if angle < -45:
        angle = 90 + angle
    if angle > 45:
        angle = angle - 90
    return float(angle)


def deskew_image(bgr: np.ndarray, angle: float) -> np.ndarray:
    """Rotates the image to correct `angle` of skew, expanding the canvas
    (white fill) rather than cropping, so no passport content is lost."""
    if abs(angle) < 0.3:
        return bgr  # not worth touching — avoids re-encoding artifacts

    (h, w) = bgr.shape[:2]
    center = (w / 2, h / 2)
    matrix = cv2.getRotationMatrix2D(center, angle, 1.0)

    cos = abs(matrix[0, 0])
    sin = abs(matrix[0, 1])
    new_w = int((h * sin) + (w * cos))
    new_h = int((h * cos) + (w * sin))
    matrix[0, 2] += (new_w / 2) - center[0]
    matrix[1, 2] += (new_h / 2) - center[1]

    return cv2.warpAffine(
        bgr,
        matrix,
        (new_w, new_h),
        flags=cv2.INTER_CUBIC,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=(255, 255, 255),
    )


def _order_quad_points(pts: np.ndarray) -> np.ndarray:
    """Orders 4 arbitrary corner points as top-left, top-right,
    bottom-right, bottom-left — the order cv2.getPerspectiveTransform
    needs, regardless of what order cv2.approxPolyDP happened to return
    them in."""
    s = pts.sum(axis=1)
    diff = np.diff(pts, axis=1).reshape(-1)
    ordered = np.zeros((4, 2), dtype="float32")
    ordered[0] = pts[np.argmin(s)]       # top-left: smallest x+y
    ordered[2] = pts[np.argmax(s)]       # bottom-right: largest x+y
    ordered[1] = pts[np.argmin(diff)]    # top-right: smallest y-x
    ordered[3] = pts[np.argmax(diff)]    # bottom-left: largest y-x
    return ordered


def detect_and_crop_document_region(bgr: np.ndarray) -> Tuple[np.ndarray, bool]:
    """Finds the passport page's own rectangular border inside a larger
    photographed frame (a desk, a hand, whatever else is in the shot) and
    perspective-corrects it to a flat, top-down crop — the step this
    pipeline was missing entirely (root cause of real-world extraction
    failures: see backend/python/README.md, 'Real passports vs the
    synthetic fixture'). The existing safe_crop_white_margins() below only
    ever trims excess white margin around a document that already fills
    most of the frame; it has no way to separate the document from a
    genuinely different background (a wood-grain desk, a patterned
    surface), so a photographed-with-background passport passed straight
    through untouched, and MRZ detection (which assumes the MRZ sits in
    the bottom ~22% of the *whole image*) then reads pure background.

    Detection method: Canny edges -> the largest 4-sided convex contour in
    a plausible size/aspect range is taken to be the document, then
    perspective-warped flat. This is edge-based (looks for the document's
    own drawn/printed border), not brightness-threshold-based, so it does
    not depend on the background being white.

    Returns (corrected_bgr, region_detected). When no confidently
    document-shaped quadrilateral is found — blur obscuring the border,
    a background that itself looks rectangular, an already-tightly-cropped
    upload with no border margin to find — this returns the ORIGINAL image
    unchanged and region_detected=False. Per the project's explicit rule
    (never produce a bad automatic crop), an uncertain detection must never
    replace the image with a guess; downstream steps then simply run on the
    original frame exactly as before this function existed.
    """
    h, w = bgr.shape[:2]
    frame_area = float(w * h)

    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    edges = cv2.Canny(blurred, 50, 150)
    # A light dilation (not the 5x5/2-iteration version tried and rejected
    # during testing) just closes small gaps in the traced border without
    # rounding its corners — a heavier dilation was found, by direct
    # comparison against a known document position, to blur the true
    # corners enough that the warp below straightens the outer frame while
    # leaving the actual printed content inside still visibly skewed.
    edges = cv2.dilate(edges, np.ones((3, 3), np.uint8), iterations=1)

    # RETR_EXTERNAL (outermost contours only) + minAreaRect (the tightest
    # rotated bounding rectangle over ALL of a contour's points) rather than
    # approxPolyDP: a document's traced edge is rarely a mathematically
    # perfect quadrilateral (JPEG noise, a slightly uneven border, corner
    # rounding from the dilation above), and forcing it through
    # approxPolyDP's fixed-epsilon corner search — tried first, see
    # backend/python/README.md's 'document-region detection' note — was
    # found to pick corners a few pixels off the true ones. minAreaRect is
    # far less sensitive to that kind of per-pixel noise along the edge.
    contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return bgr, False

    best_box = None
    best_area = 0.0
    for c in contours:
        area = cv2.contourArea(c)
        # Too small to plausibly be the document, or so close to the full
        # frame that there's no real background to separate from anyway
        # (that case is exactly what safe_crop_white_margins already
        # handles fine) — skip both rather than risk a spurious "detection".
        if area < frame_area * 0.15 or area > frame_area * 0.97:
            continue
        rect = cv2.minAreaRect(c)
        rect_w, rect_h = rect[1]
        rect_area = rect_w * rect_h
        if rect_area <= 0:
            continue
        # How much of its own minimum bounding rectangle the contour
        # actually fills — a genuine flat rectangular document is close to
        # 1.0; an irregular blob (a shadow, a curled corner, a hand) is
        # not. Guards against latching onto a non-document shape that
        # happened to pass the area filter above.
        rectangularity = area / rect_area
        if rectangularity < 0.80:
            continue
        if area > best_area:
            best_area = area
            best_box = cv2.boxPoints(rect)

    if best_box is None:
        return bgr, False

    ordered = _order_quad_points(best_box.astype("float32"))
    (tl, tr, br, bl) = ordered
    max_width = int(max(np.linalg.norm(br - bl), np.linalg.norm(tr - tl)))
    max_height = int(max(np.linalg.norm(tr - br), np.linalg.norm(tl - bl)))

    if max_width < 200 or max_height < 140:
        return bgr, False  # too small to be a trustworthy detection

    # A passport bio-data page is roughly landscape or portrait but never
    # an extreme sliver — reject implausible shapes (more likely a
    # spurious edge loop than the real document) rather than warp to a
    # useless result.
    long_side, short_side = max(max_width, max_height), max(1, min(max_width, max_height))
    if long_side / short_side > 3.2:
        return bgr, False

    dst = np.array(
        [[0, 0], [max_width - 1, 0], [max_width - 1, max_height - 1], [0, max_height - 1]],
        dtype="float32",
    )
    matrix = cv2.getPerspectiveTransform(ordered, dst)
    warped = cv2.warpPerspective(
        bgr, matrix, (max_width, max_height), flags=cv2.INTER_CUBIC, borderValue=(255, 255, 255)
    )
    return warped, True


def enhance_for_ocr(gray: np.ndarray) -> np.ndarray:
    """Mild, non-destructive contrast normalization applied only to the copy
    of the image handed to OCR (never the copy returned for on-screen
    display/download) — CLAHE (contrast-limited adaptive histogram
    equalization) plus a light unsharp-mask sharpen. Helps the low-light /
    glare / slightly-blurry real-photo cases without the aggressive,
    detail-destroying thresholding the project rules warn against (rule
    'Do not apply aggressive processing blindly')."""
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    enhanced = clahe.apply(gray)
    blurred = cv2.GaussianBlur(enhanced, (0, 0), sigmaX=1.2)
    sharpened = cv2.addWeighted(enhanced, 1.5, blurred, -0.5, 0)
    return sharpened


def safe_crop_white_margins(bgr: np.ndarray, padding: int = SAFE_CROP_PADDING_PX) -> np.ndarray:
    """Crops excess white/background margin around the passport page while
    always preserving at least `padding` pixels around the detected
    document content. When detection looks unreliable (content region
    implausibly small — likely a thresholding failure, not a small
    document) it skips cropping entirely: per the project rule, when
    uncertain, preserve more content rather than risk cutting off the
    photo, MRZ or passport number."""
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1]
    coords = cv2.findNonZero(thresh)
    if coords is None:
        return bgr

    x, y, w, h = cv2.boundingRect(coords)
    img_h, img_w = bgr.shape[:2]

    area_ratio = (w * h) / float(img_w * img_h)
    if area_ratio < 0.15:
        return bgr  # detection looks unreliable — don't risk an aggressive crop

    x0 = max(0, x - padding)
    y0 = max(0, y - padding)
    x1 = min(img_w, x + w + padding)
    y1 = min(img_h, y + h + padding)
    return bgr[y0:y1, x0:x1]


# ---------------------------------------------------------------------------
# MRZ (ICAO Doc 9303, TD3 — passport booklet) check digits & parsing
# ---------------------------------------------------------------------------


def compute_icao_check_digit(data: str) -> int:
    """ICAO 9303 check-digit algorithm: weights 7,3,1 repeating; '<' = 0,
    digits = themselves, letters = A=10 .. Z=35."""
    weights = (7, 3, 1)
    total = 0
    for i, ch in enumerate(data):
        if ch == "<":
            value = 0
        elif ch.isdigit():
            value = int(ch)
        elif "A" <= ch <= "Z":
            value = ord(ch) - ord("A") + 10
        else:
            value = 0  # unexpected OCR noise — treat as filler rather than crash
        total += value * weights[i % 3]
    return total % 10


def _mrz_date_to_iso(yymmdd: str, *, is_expiry: bool) -> Optional[str]:
    if not re.fullmatch(r"\d{6}", yymmdd):
        return None
    yy, mm, dd = int(yymmdd[0:2]), int(yymmdd[2:4]), int(yymmdd[4:6])
    if is_expiry:
        year = 2000 + yy
    else:
        # Date of birth is always in the past: pick whichever century
        # doesn't put it in the future.
        current_yy = datetime.now().year % 100
        year = 2000 + yy if yy <= current_yy else 1900 + yy
    try:
        return datetime(year, mm, dd).date().isoformat()
    except ValueError:
        return None


def parse_mrz_td3(line1: str, line2: str) -> Dict[str, Any]:
    """Parses and validates a TD3 (passport booklet) MRZ pair. Returns
    every derived field plus a validity flag per check digit and an
    overall `valid` flag — parsing never raises on malformed input, it
    reports what it could and flags the rest for manual review."""
    line1 = (line1 or "").upper().ljust(44, "<")[:44]
    line2 = (line2 or "").upper().ljust(44, "<")[:44]
    warnings: List[str] = []

    doc_type = _coerce_alpha(line1[0:2]).replace("<", "").strip()
    issuing_country = _coerce_alpha(line1[2:5]).replace("<", "").strip()

    name_field = line1[5:44]
    if "<<" in name_field:
        surname_raw, given_raw = name_field.split("<<", 1)
    else:
        surname_raw, given_raw = name_field, ""
    surname = re.sub(r"<+", " ", surname_raw).strip()
    given_names = re.sub(r"<+", " ", given_raw).strip()
    full_name = (given_names + " " + surname).strip()

    # Passport number itself is NOT coerced (see _coerce_alpha/_coerce_numeric's
    # own docstring: which direction to correct is only known when a field is
    # strictly typed digits-only or letters-only; passport number formats mix
    # both by country, so blindly coercing it could silently overwrite real
    # data — exactly the "do not blindly correct characters" line staff drew).
    # Its OWN check-digit position, however, is always strictly digit-only
    # per ICAO 9303, so — same principle already applied to DOB/expiry below —
    # a common OCR letter/digit confusion there is normalized before checking.
    passport_number_raw = line2[0:9]
    passport_number = passport_number_raw.rstrip("<")
    passport_check_digit = _coerce_numeric(line2[9:10])
    passport_number_valid = passport_check_digit.isdigit() and (
        compute_icao_check_digit(passport_number_raw) == int(passport_check_digit)
    )
    if not passport_number_valid:
        warnings.append("Passport number check digit failed — please verify manually.")

    nationality = _coerce_alpha(line2[10:13]).replace("<", "").strip()

    dob_raw = _coerce_numeric(line2[13:19])
    dob_check_digit = _coerce_numeric(line2[19:20])
    dob_valid = dob_check_digit.isdigit() and (
        compute_icao_check_digit(dob_raw) == int(dob_check_digit)
    )
    dob_iso = _mrz_date_to_iso(dob_raw, is_expiry=False)
    if not dob_valid:
        warnings.append("Date of birth check digit failed — please verify manually.")

    sex_raw = line2[20:21]
    sex = sex_raw if sex_raw in ("M", "F") else ("Unspecified" if sex_raw == "<" else sex_raw)

    expiry_raw = _coerce_numeric(line2[21:27])
    expiry_check_digit = _coerce_numeric(line2[27:28])
    expiry_valid = expiry_check_digit.isdigit() and (
        compute_icao_check_digit(expiry_raw) == int(expiry_check_digit)
    )
    expiry_iso = _mrz_date_to_iso(expiry_raw, is_expiry=True)
    if not expiry_valid:
        warnings.append("Passport expiry check digit failed — please verify manually.")

    # Personal number itself is NOT coerced — like passport number, ICAO
    # 9303 leaves this "other optional data" field's format up to the
    # issuer (numeric, alphanumeric, or unused), so there is no single
    # correct typed direction to normalize it in. Its check-digit position
    # is strictly digit-only when the field is used, same as every other
    # check digit here.
    personal_number_raw = line2[28:42]
    personal_check_char = _coerce_numeric(line2[42:43])
    personal_number = personal_number_raw.rstrip("<")
    personal_field_unused = personal_number == ""
    if personal_field_unused:
        personal_number_valid = True  # field legitimately unused by many issuers
    else:
        personal_number_valid = personal_check_char.isdigit() and (
            compute_icao_check_digit(personal_number_raw) == int(personal_check_char)
        )

    # Root-cause fix, two parts, both applied here:
    #
    # 1. The composite check digit must be computed from the SAME
    #    ICAO-typed-normalized values already used for the individual field
    #    checks above (passport_check_digit, dob_raw+dob_check_digit,
    #    expiry_raw+expiry_check_digit) — not the raw, uncorrected line2
    #    slices. Before this fix, a common OCR letter/digit confusion (e.g.
    #    an 'O' misread in place of a '0') was already self-healed for that
    #    field's OWN check, but the composite check kept using the raw,
    #    uncorrected character, so it failed anyway even though nothing was
    #    actually wrong with the passport data — reproduced directly this
    #    session with a deliberately-corrupted-then-coerced DOB digit.
    #
    # 2. When the optional personal-number field is unused, issuers are
    #    permitted (ICAO 9303) to fill BOTH the 14-character field and its
    #    own check-digit position with the filler character '<'. That
    #    position carries no visually-distinctive glyph to anchor an OCR
    #    read against (just a long run of one repeated filler character),
    #    which real-world testing this session showed is the single most
    #    common site of a stray misread — so, exactly like
    #    personal_number_valid's own exception just above, a misread there
    #    must not be allowed to fail the composite check either.
    #
    # Neither of these is the kind of blind O/0-style character-guessing
    # that passport/personal-number field DATA is deliberately never
    # subjected to — each only reuses a normalization already trusted for
    # that exact position's own individual check, applied consistently.
    if personal_field_unused:
        composite_personal_segment = "<" * 15
    else:
        composite_personal_segment = personal_number_raw + personal_check_char

    composite_str = (
        passport_number_raw + passport_check_digit
        + dob_raw + dob_check_digit
        + expiry_raw + expiry_check_digit
        + composite_personal_segment
    )
    composite_check_digit = _coerce_numeric(line2[43:44])
    composite_valid = composite_check_digit.isdigit() and (
        compute_icao_check_digit(composite_str) == int(composite_check_digit)
    )
    if not composite_valid:
        warnings.append("MRZ composite check digit failed — please verify manually.")

    overall_valid = passport_number_valid and dob_valid and expiry_valid and composite_valid

    return {
        "line1": line1,
        "line2": line2,
        "documentType": doc_type,
        "issuingCountry": issuing_country,
        "surname": surname,
        "givenNames": given_names,
        "fullName": full_name,
        "passportNumber": passport_number,
        "passportNumberValid": passport_number_valid,
        "nationality": nationality,
        "dateOfBirth": dob_iso,
        "dateOfBirthValid": dob_valid,
        "sex": sex,
        "dateOfExpiry": expiry_iso,
        "dateOfExpiryValid": expiry_valid,
        "personalNumber": personal_number,
        "personalNumberValid": personal_number_valid,
        "compositeValid": composite_valid,
        "valid": overall_valid,
        "warnings": warnings,
    }


MRZ_TESSERACT_CONFIG = "--psm 7 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789<"
# PSM 6 ("assume a single uniform block of text") rather than Tesseract's
# own default (PSM 3, fully-automatic page/layout segmentation). Found by
# direct comparison on a realistically photographed (bordered, slightly
# blurry) passport image: PSM 3 returned a completely empty string on an
# image a human reads perfectly easily, while PSM 6 read almost all of it
# — automatic layout analysis was misjudging the framed photo as not
# containing a real text region at all. A passport bio-data page (labels
# + values, no columns/tables) is exactly the layout PSM 6 is meant for.
FULL_PAGE_TESSERACT_CONFIG = "--psm 6"


def _split_band_into_text_line_rows(thresh: np.ndarray) -> Optional[Tuple[np.ndarray, np.ndarray]]:
    """Locates the MRZ's two actual text-line rows within the cropped
    bottom-of-page band via a horizontal ink-density profile (row-by-row
    count of foreground pixels), instead of assuming they fall exactly in
    the first and second half of the band.

    Root cause this replaces: the previous fixed 50/50 halfway split only
    produced two clean line-crops when the blank margin above the first
    MRZ line happened to be roughly equal to the blank margin below the
    second — true of the original hand-built test fixture, but NOT
    generally true, and confirmed directly to fail on a realistically
    tightly-cropped photo: the halfway line cut straight through the
    first MRZ line's own glyphs (garbling it) while leaving the second
    line's crop containing parts of both lines. Finding the real ink rows
    is robust to however much blank space surrounds the two lines.
    """
    h, w = thresh.shape[:2]
    if h < 10 or w < 10:
        return None

    background_val = 255 if int((thresh == 255).sum()) >= int((thresh == 0).sum()) else 0
    ink_rows = (thresh != background_val).sum(axis=1) > max(2, int(w * 0.01))

    runs: List[List[int]] = []
    start = None
    for y, is_ink in enumerate(ink_rows.tolist()):
        if is_ink and start is None:
            start = y
        elif not is_ink and start is not None:
            runs.append([start, y])
            start = None
    if start is not None:
        runs.append([start, h])

    # Merge runs separated by only a tiny gap — a character's own internal
    # gaps (the counter of an 'A', a break between characters at this
    # resolution) must not fragment one real text line into several runs.
    merged: List[List[int]] = []
    for r in runs:
        if merged and r[0] - merged[-1][1] <= 4:
            merged[-1][1] = r[1]
        else:
            merged.append(r)

    # A specks/noise row-run is much shorter than an actual line of text.
    plausible = [r for r in merged if (r[1] - r[0]) >= max(6, int(h * 0.08))]
    if len(plausible) < 2:
        return None

    (y0a, y1a), (y0b, y1b) = plausible[-2:]  # bottommost two, already top-to-bottom order
    pad = 4
    line_a = thresh[max(0, y0a - pad):min(h, y1a + pad), :]
    line_b = thresh[max(0, y0b - pad):min(h, y1b + pad), :]
    return line_a, line_b


def _read_mrz_band_lines(bgr: np.ndarray) -> Optional[Tuple[str, str]]:
    """Dedicated MRZ read: crops the bottom band of the page (where a TD3
    MRZ always sits), splits it into its two constituent lines, and OCRs
    each individually with "single text line" page segmentation and the
    character set whitelisted to A-Z0-9<.

    Generic whole-page OCR — and even a combined whitelisted pass over both
    lines at once — were caught by testing (see backend/python/README.md)
    truncating long runs of the trailing '<' filler character. Since the
    filler is content-free by definition, that's harmless here: the result
    is right-padded with '<' to 44 characters by the caller regardless, so
    a short-but-clean read is exactly as usable as a long one. This
    function trusts the crop geometry to know which half is which, so it
    skips the generic noisy-text candidate search entirely — that search
    (find_mrz_lines) is reserved for the whole-page fallback below, where
    the MRZ's location isn't already known.
    """
    h, w = bgr.shape[:2]
    band = bgr[int(h * 0.78):h, 0:w]
    gray = cv2.cvtColor(band, cv2.COLOR_BGR2GRAY)
    gray = enhance_for_ocr(gray)
    thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]

    band_h = thresh.shape[0]
    split = _split_band_into_text_line_rows(thresh)
    if split is not None:
        top_half, bottom_half = split
    else:
        # Row-projection couldn't confidently find two separate lines
        # (e.g. the two lines' ink rows run together at this resolution) —
        # fall back to the original halfway split rather than giving up.
        top_half = thresh[0:band_h // 2, :]
        bottom_half = thresh[band_h // 2:band_h, :]

    def _clean(raw: str) -> str:
        return MRZ_CHARSET_RE.sub("", raw.upper().replace(" ", "").replace("\n", ""))

    line_a = _clean(_provider.ocr_text(top_half, config=MRZ_TESSERACT_CONFIG))
    line_b = _clean(_provider.ocr_text(bottom_half, config=MRZ_TESSERACT_CONFIG))

    if len(line_a) < 10 or len(line_b) < 10:
        return None  # too little read to be worth trusting over the fallback
    return line_a, line_b


def find_mrz_lines(ocr_text: str) -> Optional[Tuple[str, str]]:
    """Scans OCR'd text for the two 44-character MRZ lines. Tolerant of
    minor OCR noise: keeps only A-Z0-9< characters per line, accepts lines
    from 30 characters up (short reads are padded with '<' by the caller/
    parser), and picks the best two by closeness to the expected length of
    44, in their original order."""
    candidates = []
    for raw_line in ocr_text.upper().splitlines():
        cleaned = MRZ_CHARSET_RE.sub("", raw_line.replace(" ", ""))
        if len(cleaned) >= 30:
            candidates.append(cleaned)

    if len(candidates) < 2:
        return None

    # Prefer the two longest (closest to 44 chars) candidates, then restore
    # their original relative order for line1/line2.
    ranked = sorted(candidates, key=len, reverse=True)[:2]
    ordered = [c for c in candidates if c in ranked][:2]
    if len(ordered) < 2:
        ordered = ranked
    return ordered[0], ordered[1]


# ---------------------------------------------------------------------------
# Field extraction (MRZ-authoritative, VIZ-fallback, current vs old number)
# ---------------------------------------------------------------------------


def _confidence_field(value: Any, confidence: float, source: str, needs_review: bool) -> Dict[str, Any]:
    return {"value": value, "confidence": round(confidence, 2), "source": source, "needsReview": needs_review}


def extract_passport_fields(ocr_text: str, mrz: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Builds the field set the frontend shows for review. MRZ data is
    authoritative (per ICAO 9303) when its own check digits are valid;
    a failed check digit still surfaces the OCR'd value but at low
    confidence and flagged for review rather than being discarded."""
    fields: Dict[str, Any] = {}

    if mrz:
        fields["fullName"] = _confidence_field(mrz["fullName"], 0.95 if mrz["valid"] else 0.5, "mrz", not mrz["valid"])
        fields["surname"] = _confidence_field(mrz["surname"], 0.95 if mrz["valid"] else 0.5, "mrz", not mrz["valid"])
        fields["givenNames"] = _confidence_field(mrz["givenNames"], 0.95 if mrz["valid"] else 0.5, "mrz", not mrz["valid"])
        fields["passportNumber"] = _confidence_field(
            mrz["passportNumber"], 0.95 if mrz["passportNumberValid"] else 0.4, "mrz", not mrz["passportNumberValid"]
        )
        fields["nationality"] = _confidence_field(mrz["nationality"], 0.9 if mrz["valid"] else 0.5, "mrz", not mrz["valid"])
        fields["dateOfBirth"] = _confidence_field(
            mrz["dateOfBirth"], 0.95 if mrz["dateOfBirthValid"] else 0.4, "mrz", not mrz["dateOfBirthValid"]
        )
        fields["sex"] = _confidence_field(mrz["sex"], 0.9 if mrz["valid"] else 0.5, "mrz", not mrz["valid"])
        fields["dateOfExpiry"] = _confidence_field(
            mrz["dateOfExpiry"], 0.95 if mrz["dateOfExpiryValid"] else 0.4, "mrz", not mrz["dateOfExpiryValid"]
        )
        fields["countryCode"] = _confidence_field(mrz["issuingCountry"], 0.9 if mrz["valid"] else 0.5, "mrz", not mrz["valid"])
        fields["passportType"] = _confidence_field(mrz["documentType"], 0.9 if mrz["valid"] else 0.5, "mrz", not mrz["valid"])
    else:
        for key in (
            "fullName", "surname", "givenNames", "passportNumber", "nationality",
            "dateOfBirth", "sex", "dateOfExpiry", "countryCode", "passportType",
        ):
            fields[key] = _confidence_field(None, 0.0, "none", True)

    # Fields the MRZ does not carry: pulled from the visible (VIZ) text with
    # simple label matching — inherently less reliable, always flagged.
    place_of_birth = _search_label(ocr_text, [r"PLACE\s+OF\s+BIRTH"])
    fields["placeOfBirth"] = _confidence_field(place_of_birth, 0.4 if place_of_birth else 0.0, "viz", True)

    date_of_issue = _search_label(ocr_text, [r"DATE\s+OF\s+ISSUE"])
    fields["dateOfIssue"] = _confidence_field(date_of_issue, 0.4 if date_of_issue else 0.0, "viz", True)

    issuing_authority = _search_label(ocr_text, [r"ISSUING\s+AUTHORITY", r"AUTHORITY"])
    fields["issuingAuthority"] = _confidence_field(issuing_authority, 0.4 if issuing_authority else 0.0, "viz", True)

    # "Place of issue" is a distinct printed field from "issuing authority"
    # on Indian passports (e.g. authority = "REGIONAL PASSPORT OFFICE",
    # place of issue = "MUMBAI") and from "date of issue" — the review form
    # (current.issuePlace) already has an editable field for it; this was
    # missing here, silently leaving it OCR-blank on every passport.
    place_of_issue = _search_label(ocr_text, [r"PLACE\s+OF\s+ISSUE"])
    fields["placeOfIssue"] = _confidence_field(place_of_issue, 0.4 if place_of_issue else 0.0, "viz", True)

    # Applicant's home address, and PIN code specifically (spec: "address,
    # PIN where available"). A full multi-line postal address (line 2,
    # city, state, country as separate fields) cannot be reliably split out
    # from OCR text alone without real layout/line-structure parsing this
    # pipeline does not do — rather than guess and risk silently wrong data
    # in a field staff might not double-check as carefully as a passport
    # number, only the two pieces that ARE reliably extractable from VIZ
    # text are attempted here: whatever follows an "Address" label on its
    # own line (addressLine1), and the 6-digit Indian PIN code specifically
    # (see INDIA_PIN_LABEL_RE above). addressLine2/city/state/country are
    # intentionally left for manual entry — the review form has real,
    # editable fields for all six either way (project rule 10: a field OCR
    # did not return is never silently hidden, just marked "please enter
    # manually").
    address_line1 = _search_label(ocr_text, [r"PRESENT\s+ADDRESS", r"ADDRESS"])
    fields["addressLine1"] = _confidence_field(address_line1, 0.3 if address_line1 else 0.0, "viz", True)
    fields["addressLine2"] = _confidence_field(None, 0.0, "none", True)
    fields["addressCity"] = _confidence_field(None, 0.0, "none", True)
    fields["addressState"] = _confidence_field(None, 0.0, "none", True)
    fields["addressCountry"] = _confidence_field(None, 0.0, "none", True)

    pin_match = INDIA_PIN_LABEL_RE.search(ocr_text or "")
    address_pincode = pin_match.group(1) if pin_match else None
    fields["addressPincode"] = _confidence_field(address_pincode, 0.5 if address_pincode else 0.0, "viz", True)

    # Phase 10 — current vs old passport number must never be confused.
    # The MRZ number above is always the CURRENT passport. An "old /
    # previous / former passport" number, if present at all, only ever
    # shows up as printed VIZ text (endorsement page) — never in the MRZ —
    # so it is extracted completely separately and always flagged for
    # manual confirmation.
    old_match = OLD_PASSPORT_LABEL_RE.search(ocr_text or "")
    old_number = old_match.group(1) if old_match else None
    fields["oldPassportNumber"] = _confidence_field(old_number, 0.3 if old_number else 0.0, "viz", True)

    return fields


def _search_label(text: str, label_patterns: List[str]) -> Optional[str]:
    if not text:
        return None
    for pattern in label_patterns:
        m = re.search(pattern + r"\s*[:\-]?\s*([A-Z0-9 ,./-]{2,40})", text, re.IGNORECASE)
        if m:
            value = m.group(1).strip().rstrip(".,")
            if value:
                return value
    return None


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def process_passport_page(
    pil_image: Image.Image,
    forced_rotation: Optional[int] = None,
) -> Dict[str, Any]:
    """Runs the full pipeline on a single passport page image and returns a
    structured, JSON-serializable result."""
    warnings: List[str] = []
    bgr = pil_to_bgr(pil_image)

    # Locate the passport's own border and flatten it out of whatever else
    # is in the photo (a desk, a hand, a background) BEFORE anything else
    # runs — orientation scoring, the MRZ-band crop (which assumes the MRZ
    # sits in the bottom ~22% of the *whole image*), and the blank-page
    # check all only make sense once the frame actually just IS the
    # document. See detect_and_crop_document_region()'s own docstring for
    # why this step was the real root cause of real-photo extraction
    # failures. A low-confidence detection leaves `bgr` completely
    # untouched (region_detected=False) — every step below then behaves
    # exactly as it did before this function existed.
    bgr, region_detected = detect_and_crop_document_region(bgr)

    gray_check = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    if is_blank_page(gray_check):
        return {
            "isBlank": True,
            "orientationApplied": 0,
            "orientationNeedsReview": False,
            "orientationScores": {},
            "skewAngleCorrectedDegrees": 0.0,
            "processedImageBase64": bgr_to_base64_png(bgr),
            "documentRegionDetected": region_detected,
            "mrz": None,
            "fields": {},
            "warnings": ["This page looks blank — no processing was attempted."],
        }

    if forced_rotation is not None:
        orientation = {"bestRotation": forced_rotation % 360, "scores": {}, "needsReview": False}
    else:
        orientation = evaluate_orientations(bgr)
    bgr = _rotate_90_multiple(bgr, orientation["bestRotation"])
    if orientation["needsReview"]:
        warnings.append("Orientation could not be determined with confidence — please check the page is right-side up.")

    skew_angle = detect_skew_angle(bgr)
    bgr = deskew_image(bgr, skew_angle)

    bgr = safe_crop_white_margins(bgr)

    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    # The enhanced copy is used for OCR only — bgr (returned to the caller
    # as processedImageBase64) stays exactly as deskewed/cropped, unedited,
    # so what staff see and download is never a contrast-boosted rendering
    # of their document, only the real one.
    ocr_text = normalize_ocr_text(_provider.ocr_text(enhance_for_ocr(gray), config=FULL_PAGE_TESSERACT_CONFIG))

    # Try the dedicated, character-whitelisted MRZ-band pass first (far more
    # accurate — see _read_mrz_band_lines); fall back to scanning the
    # whole-page OCR text if that band doesn't yield two usable lines.
    mrz_lines = _read_mrz_band_lines(bgr) or find_mrz_lines(ocr_text)
    mrz_parsed = None
    if mrz_lines:
        mrz_parsed = parse_mrz_td3(*mrz_lines)
        warnings.extend(mrz_parsed["warnings"])
    else:
        warnings.append("MRZ lines were not detected — passport data will need to be entered manually.")

    fields = extract_passport_fields(ocr_text, mrz_parsed)

    return {
        "isBlank": False,
        "orientationApplied": orientation["bestRotation"],
        "orientationNeedsReview": orientation["needsReview"],
        "orientationScores": orientation["scores"],
        "skewAngleCorrectedDegrees": round(skew_angle, 2),
        "processedImageBase64": bgr_to_base64_png(bgr),
        "documentRegionDetected": region_detected,
        "ocrText": ocr_text,
        "mrz": mrz_parsed,
        "fields": fields,
        "verificationStatus": "OCR Extracted — Please Verify",
        "warnings": warnings,
    }


def process_passport_file(path: str, page_index: int = 0, forced_rotation: Optional[int] = None) -> Dict[str, Any]:
    pages = load_pages(path)
    total_pages = len(pages)
    if page_index < 0 or page_index >= total_pages:
        raise IndexError(f"page_index {page_index} out of range (file has {total_pages} page(s))")

    result = process_passport_page(pages[page_index], forced_rotation=forced_rotation)
    result["pageIndex"] = page_index
    result["totalPages"] = total_pages
    return result


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 ocr_runner.py <passport_image_or_pdf> [page_index]")
        sys.exit(1)
    target = sys.argv[1]
    page = int(sys.argv[2]) if len(sys.argv) > 2 else 0
    import json as _json

    out = process_passport_file(target, page_index=page)
    out.pop("processedImageBase64", None)  # too large for terminal output
    print(_json.dumps(out, indent=2, ensure_ascii=False))
