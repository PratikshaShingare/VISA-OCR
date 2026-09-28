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
        "hotelName": _search_label(ocr_text, [r"\bHOTEL\s*NAME\b", r"\bPROPERTY\s*NAME\b"]),
        "phone": _search_label(ocr_text, [r"\bHOTEL\s*PHONE\b", r"\bCONTACT\s*(?:NO\.?|NUMBER)?\b", r"\bPHONE\s*(?:NO\.?)?\b", r"\bTEL(?:EPHONE)?\b\s*(?:NO\.?)?"]),
        "address": _search_label(ocr_text, [r"\bHOTEL\s*ADDRESS\b", r"\bADDRESS\b"]),
        "city": _search_label(ocr_text, [r"\bCITY\b"]),
        "confirmationNumber": _search_label(ocr_text, [r"\bCONFIRMATION\s*(?:NO\.?|NUMBER|ID)\b", r"\bBOOKING\s*(?:REF(?:ERENCE)?|ID|NO\.?)\b"]),
        "leadGuestName": _search_label(ocr_text, [r"\bLEAD\s*GUEST(?:\s*NAME)?\b", r"\bGUEST(?:'?S)?\s*NAME\b"]),
        "roomType": _search_label(ocr_text, [r"\bROOM\s*TYPE\b", r"\bROOM\s*CATEGORY\b"]),
        "noOfRooms": _search_number(ocr_text, [r"\b(?:NO\.?\s*OF\s*)?ROOMS?\b"]),
        "noOfAdults": _search_number(ocr_text, [r"\b(?:NO\.?\s*OF\s*)?ADULTS?\b"]),
        "noOfChildren": _search_number(ocr_text, [r"\b(?:NO\.?\s*OF\s*)?CHILD(?:REN)?\b"]),
        "checkIn": _search_date(ocr_text, [r"\bCHECK[\s\-]*IN\b(?:\s*DATE)?"]),
        "checkOut": _search_date(ocr_text, [r"\bCHECK[\s\-]*OUT\b(?:\s*DATE)?"]),
    }
    return {"fields": fields, "guestNames": _extract_guest_names(ocr_text)}


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
    ocr_text = ocr.normalize_ocr_text(
        ocr._provider.ocr_text(ocr.enhance_for_ocr(gray), config=ocr.FULL_PAGE_TESSERACT_CONFIG)
    )

    extracted = extract_hotel_voucher_fields(ocr_text)
    if not any(extracted["fields"].values()) and not extracted["guestNames"]:
        warnings.append(
            "No recognizable hotel-voucher fields were found on this page — every field below still needs to be entered manually."
        )

    return {
        "isBlank": False,
        "processedImageBase64": ocr.bgr_to_base64_png(bgr),
        "documentRegionDetected": region_detected,
        "ocrText": ocr_text,
        "fields": extracted["fields"],
        "guestNames": extracted["guestNames"],
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
