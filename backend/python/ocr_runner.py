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
import io
import os
import re
import statistics
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
    mean_conf, text = _provider.ocr_mean_confidence_and_text(gray)
    mrz_hits = text.count("<<")
    score = mean_conf + min(len(text), 400) * 0.1 + mrz_hits * 25
    return score, text


def evaluate_orientations(bgr: np.ndarray) -> Dict[str, Any]:
    """Tries all four right-angle orientations and scores each with a real
    OCR pass rather than assuming a fixed orientation. Returns the winning
    rotation plus every candidate's score, so the caller/frontend can flag
    a genuinely ambiguous result instead of silently guessing."""
    scores: Dict[int, float] = {}
    for rot in ORIENTATIONS:
        rotated = _rotate_90_multiple(bgr, rot)
        gray = cv2.cvtColor(rotated, cv2.COLOR_BGR2GRAY)
        score, _ = _ocr_score(gray)
        scores[rot] = score

    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    best_rot, best_score = ranked[0]
    second_score = ranked[1][1] if len(ranked) > 1 else 0.0

    # Ambiguous when the winner isn't clearly ahead, or when nothing scored
    # highly at all (likely a blank/unreadable page rather than a
    # confidently-wrong guess).
    gap = (best_score - second_score) / best_score if best_score > 0 else 0.0
    needs_review = best_score < 8.0 or gap < 0.12

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

    passport_number_raw = line2[0:9]
    passport_number = passport_number_raw.rstrip("<")
    passport_check_digit = line2[9:10]
    passport_number_valid = passport_check_digit.isdigit() and (
        compute_icao_check_digit(passport_number_raw) == int(passport_check_digit)
    )
    if not passport_number_valid:
        warnings.append("Passport number check digit failed — please verify manually.")

    nationality = _coerce_alpha(line2[10:13]).replace("<", "").strip()

    dob_raw = _coerce_numeric(line2[13:19])
    dob_check_digit = line2[19:20]
    dob_valid = dob_check_digit.isdigit() and (
        compute_icao_check_digit(dob_raw) == int(dob_check_digit)
    )
    dob_iso = _mrz_date_to_iso(dob_raw, is_expiry=False)
    if not dob_valid:
        warnings.append("Date of birth check digit failed — please verify manually.")

    sex_raw = line2[20:21]
    sex = sex_raw if sex_raw in ("M", "F") else ("Unspecified" if sex_raw == "<" else sex_raw)

    expiry_raw = _coerce_numeric(line2[21:27])
    expiry_check_digit = line2[27:28]
    expiry_valid = expiry_check_digit.isdigit() and (
        compute_icao_check_digit(expiry_raw) == int(expiry_check_digit)
    )
    expiry_iso = _mrz_date_to_iso(expiry_raw, is_expiry=True)
    if not expiry_valid:
        warnings.append("Passport expiry check digit failed — please verify manually.")

    personal_number_raw = line2[28:42]
    personal_check_char = line2[42:43]
    personal_number = personal_number_raw.rstrip("<")
    if personal_number == "":
        personal_number_valid = True  # field legitimately unused by many issuers
    else:
        personal_number_valid = personal_check_char.isdigit() and (
            compute_icao_check_digit(personal_number_raw) == int(personal_check_char)
        )

    composite_str = line2[0:10] + line2[13:20] + line2[21:28] + line2[28:43]
    composite_check_digit = line2[43:44]
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
    thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]

    band_h = thresh.shape[0]
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

    gray_check = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    if is_blank_page(gray_check):
        return {
            "isBlank": True,
            "orientationApplied": 0,
            "orientationNeedsReview": False,
            "orientationScores": {},
            "skewAngleCorrectedDegrees": 0.0,
            "processedImageBase64": bgr_to_base64_png(bgr),
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
    ocr_text = normalize_ocr_text(_provider.ocr_text(gray))

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
