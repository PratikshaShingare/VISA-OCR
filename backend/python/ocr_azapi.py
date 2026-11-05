"""
Khanna Travels & Holidays — azapi.ai Passport OCR (Indian passports)
=====================================================================

azapi.ai reads the printed passport page and returns named fields (number,
name, dates, places, address, parents, old passport). It is used as an extra
layer ON TOP of the local pipeline in ocr_runner.py, never instead of it:

  * the local pipeline (free) still straightens / crops the page, finds the
    machine-readable zone (MRZ) and validates its ICAO check digits;
  * azapi is called once per passport (one billable hit) with the straightened
    data page as `front`, plus the following page as `back` when the uploaded
    file has one;
  * every azapi value is cross-checked against the MRZ. Agreement raises
    confidence; disagreement is flagged, never silently resolved;
  * if azapi is not configured, out of credits, unreachable or cannot read
    the page, the local result is returned unchanged (a short notice records
    why) — a passport upload never fails because of azapi.

azapi's answer is NOT treated as verified: every result keeps the
"OCR Extracted — Please Verify" status and staff can correct any field. A
field is only flagged (coloured in the form) when something is actually
wrong with it: a disagreement with the MRZ, an impossible date, an unusual
number format, a guessed name split. A clean azapi reading shows no
per-field colours; the coloured boxes are for when azapi is not used.

Security (project rule 12): the token is read here, server-side only, from
AZAPI_API_KEY (backend/python/.env locally, the hosting platform's
environment variables in production). It is never sent to the browser and
never logged. Passport data is never logged either — log lines carry only the
error kind and HTTP status.

Credits: one call costs 2.5 credits. This module therefore never retries
automatically, never calls for a page without an MRZ, and remembers a result
for a few minutes (in memory only) so re-reading the same image costs nothing.
"""

from __future__ import annotations

import base64
import hashlib
import io
import logging
import os
import re
import threading
import time
from datetime import date, timedelta
from typing import Any, Callable, Dict, List, Optional, Tuple

import requests

logger = logging.getLogger("khanna.azapi")

DEFAULT_URL = "https://ocr.azapi.ai/ind0005d"
ENV_KEY = "AZAPI_API_KEY"
ENV_URL = "AZAPI_BASE_URL"
ENV_ENABLED = "AZAPI_ENABLED"
ENV_TIMEOUT = "AZAPI_TIMEOUT_SECONDS"

CONNECT_TIMEOUT_SECONDS = 10
DEFAULT_READ_TIMEOUT_SECONDS = 60
MAX_IMAGE_SIDE_PX = 2200
JPEG_QUALITY = 90
CACHE_TTL_SECONDS = 15 * 60
CACHE_MAX_ENTRIES = 32
AUTO_PAGE_LIMIT = 4  # the frontend reads at most this many pages of one upload

SOURCE_AZAPI = "azapi"
SOURCE_CONFIRMED = "mrz+azapi"


class AzapiError(Exception):
    """azapi could not give a usable answer. `kind` is one of: config, auth,
    credits, rate, bad-request, unreadable, network, server. The message never
    contains passport data."""

    def __init__(self, kind: str, message: str):
        super().__init__(message)
        self.kind = kind


# ---------------------------------------------------------------------------
# Settings / status
# ---------------------------------------------------------------------------


def _api_key() -> str:
    return (os.environ.get(ENV_KEY) or "").strip()


def _url() -> str:
    return (os.environ.get(ENV_URL) or "").strip() or DEFAULT_URL


def _read_timeout() -> float:
    try:
        return max(5.0, float(os.environ.get(ENV_TIMEOUT) or DEFAULT_READ_TIMEOUT_SECONDS))
    except ValueError:
        return float(DEFAULT_READ_TIMEOUT_SECONDS)


def is_enabled() -> bool:
    """On when a token is configured, unless AZAPI_ENABLED switches it off."""
    if (os.environ.get(ENV_ENABLED) or "").strip().lower() in ("off", "false", "0", "no", "disabled"):
        return False
    return bool(_api_key())


_usage_lock = threading.Lock()
_usage: Dict[str, Any] = {"calls": 0, "cacheHits": 0, "lastError": None}


def get_status() -> Dict[str, Any]:
    """For /api/health. Reports configuration and this run's own counters; it
    never calls azapi (a live check would spend credits) and never reveals the
    token."""
    with _usage_lock:
        usage = dict(_usage)
    return {
        "provider": "azapi",
        "configured": bool(_api_key()),
        "enabled": is_enabled(),
        "endpoint": _url(),
        "callsSinceStart": usage["calls"],
        "cacheHitsSinceStart": usage["cacheHits"],
        "lastError": usage["lastError"],
        "note": "Reflects configuration and this run's own calls, not a live test (a live call costs credits).",
    }


def reset_for_tests() -> None:
    with _usage_lock:
        _usage.update({"calls": 0, "cacheHits": 0, "lastError": None})
    with _cache_lock:
        _cache.clear()


def _record_error(error: Optional[AzapiError]) -> None:
    with _usage_lock:
        _usage["lastError"] = None if error is None else {"kind": error.kind, "message": str(error)}


# ---------------------------------------------------------------------------
# HTTP call
# ---------------------------------------------------------------------------

_CREDIT_WORDS = ("credit", "balance", "insufficient", "quota", "recharge")
_AUTH_WORDS = ("unauthor", "invalid key", "invalid token", "api key", "apikey", "token", "forbidden", "authentication")


def _safe_message(text: Any) -> str:
    """azapi's own `message`, reduced to a short plain sentence."""
    cleaned = re.sub(r"[^A-Za-z0-9 .,;:'()\-]", " ", str(text or ""))
    return re.sub(r"\s+", " ", cleaned).strip()[:140]


def _classify_failure(status_code: int, message: str) -> AzapiError:
    lowered = message.lower()
    if status_code in (401, 403) or any(w in lowered for w in _AUTH_WORDS):
        return AzapiError("auth", "azapi rejected the token (invalid, expired or not allowed for this service).")
    if status_code == 402 or any(w in lowered for w in _CREDIT_WORDS):
        return AzapiError("credits", "azapi reports that the account has no credits left.")
    if status_code == 429:
        return AzapiError("rate", "azapi is rate-limiting requests — try again in a moment.")
    if 400 <= status_code < 500:
        return AzapiError("bad-request", "azapi could not accept the image" + (f" ({message})." if message else "."))
    if status_code >= 500:
        return AzapiError("server", "azapi had a problem on its side.")
    return AzapiError("unreadable", "azapi could not read this passport" + (f" ({message})." if message else "."))


def call_api(front: bytes, back: Optional[bytes] = None, post: Optional[Callable[..., Any]] = None) -> Dict[str, Any]:
    """One billable call. Returns azapi's `output` object. Never retries: a
    request whose answer was lost may still have been billed, so a retry could
    cost twice — staff can simply upload again. `post` is only for tests."""
    key = _api_key()
    if not key:
        raise AzapiError("config", "AZAPI_API_KEY is not set.")
    files = {"front": ("front.jpg", front, "image/jpeg")}
    if back:
        files["back"] = ("back.jpg", back, "image/jpeg")
    try:
        resp = (post or requests.post)(
            _url(), headers={"Authorization": key}, files=files, timeout=(CONNECT_TIMEOUT_SECONDS, _read_timeout())
        )
    except requests.RequestException:
        raise AzapiError("network", "Could not reach azapi (network error or timeout).")

    try:
        body = resp.json()
    except ValueError:
        body = None
    message = _safe_message(body.get("message")) if isinstance(body, dict) else ""

    if resp.status_code != 200:
        raise _classify_failure(resp.status_code, message)
    if not isinstance(body, dict):
        raise AzapiError("server", "azapi sent a reply this system could not understand.")
    if str(body.get("status", "")).strip().lower() != "success":
        raise _classify_failure(200, message)
    output = body.get("output")
    if not isinstance(output, dict) or not any(str(output.get(k) or "").strip() for k in ("id_number", "id_name")):
        raise AzapiError("unreadable", "azapi returned no passport number or name for this image.")
    return output


# ---------------------------------------------------------------------------
# Normalising azapi's output
# ---------------------------------------------------------------------------


def _clean(value: Any) -> Optional[str]:
    text = re.sub(r"\s+", " ", str(value if value is not None else "")).strip()
    return text or None


def parse_date(value: Any) -> Optional[str]:
    """DD/MM/YYYY (also - or .) or YYYY-MM-DD -> ISO, None when not a real date."""
    text = _clean(value)
    if not text:
        return None
    m = re.fullmatch(r"(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{4})", text)
    try:
        if m:
            return date(int(m.group(3)), int(m.group(2)), int(m.group(1))).isoformat()
        m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", text)
        if m:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3))).isoformat()
    except ValueError:
        return None
    return None


def _display_date(iso: Optional[str]) -> str:
    if not iso:
        return ""
    y, m, d = iso.split("-")
    return f"{d}/{m}/{y}"


_PIN_RE = re.compile(r"\bP\s*I\s*N\s*(?:CODE)?\s*[:\-]?\s*(\d{6})\b", re.I)


def _tidy(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"\s*,\s*", ", ", text)).strip(" ,.-").upper()


def parse_address(raw: Optional[str]) -> Dict[str, Optional[str]]:
    """azapi returns the address as one text block ("house, street...\\nlocality,
    city\\nPIN: 400705,STATE,COUNTRY."). Split it into the form's six fields."""
    out: Dict[str, Optional[str]] = {
        "line1": None, "line2": None, "city": None, "state": None, "pincode": None, "country": None,
    }
    lines = [ln.strip() for ln in re.split(r"[\r\n]+", raw or "") if re.sub(r"[^A-Za-z0-9]", "", ln)]
    if not lines:
        return out

    body: List[str] = []
    pin_found = False
    for ln in lines:
        m = _PIN_RE.search(ln)
        if not m or pin_found:
            body.append(ln)
            continue
        pin_found = True
        out["pincode"] = m.group(1)
        before = ln[: m.start()].strip(" ,")
        if before:
            body.append(before)
        tail = [t.strip(" .") for t in re.split(r"[,;]", ln[m.end():]) if t.strip(" .")]
        if tail:
            out["state"] = _tidy(tail[0])
        if len(tail) > 1:
            out["country"] = _tidy(tail[1])
    body = [_tidy(b) for b in body if _tidy(b)]
    if not body:
        return out

    last_parts = [p.strip() for p in body[-1].split(",") if p.strip()]
    if len(last_parts) >= 2:
        out["city"] = last_parts[-1]
        body[-1] = ", ".join(last_parts[:-1])
    elif len(body) >= 2 and re.fullmatch(r"[A-Z]+(?: [A-Z]+)?", body[-1]):
        out["city"] = body.pop()
    body = [b for b in body if b]
    if body:
        out["line1"] = body[0]
    if len(body) > 1:
        out["line2"] = ", ".join(body[1:])
    return out


def normalize(output: Dict[str, Any]) -> Dict[str, Any]:
    """azapi's `output` -> a flat dict with ISO dates and cleaned text. Dates
    that azapi sent but that are not real dates are listed in `badDates` so
    they can be flagged instead of silently dropped."""
    bad_dates: List[str] = []

    def dated(key: str, label: str) -> Optional[str]:
        raw = _clean(output.get(key))
        if not raw:
            return None
        iso = parse_date(raw)
        if iso is None:
            bad_dates.append(label)
        return iso

    def upper(key: str) -> Optional[str]:
        v = _clean(output.get(key))
        return v.upper() if v else None

    def place(key: str) -> Optional[str]:
        v = upper(key)
        return re.sub(r"\s*,\s*", ", ", v).strip(" ,.") if v else None

    return {
        "number": upper("id_number"),
        "name": upper("id_name"),
        "gender": upper("id_gender"),
        "dob": dated("id_dob", "Date of birth"),
        "expiry": dated("id_doe", "Date of expiry"),
        "issue": dated("id_doi", "Date of issue"),
        "countryCode": upper("id_country_code"),
        "nationality": upper("id_nationality"),
        "passportType": upper("id_passport_type"),
        "placeOfBirth": place("id_place_of_birth"),
        "placeOfIssue": place("id_place_of_issue"),
        "father": upper("id_father_name"),
        "mother": upper("id_mother_name"),
        "spouse": upper("id_spouse_name"),
        "address": parse_address(output.get("id_address")),
        "oldNumber": upper("id_old_passport_num"),
        "oldIssue": dated("id_old_doi", "Old passport date of issue"),
        "oldPlace": place("id_old_place_of_issue"),
        "badDates": bad_dates,
    }


# ---------------------------------------------------------------------------
# Cross-checking against the MRZ and building the form fields
# ---------------------------------------------------------------------------


def confidence_field(value: Any, confidence: float, source: str, needs_review: bool, note: Optional[str] = None) -> Dict[str, Any]:
    field = {"value": value, "confidence": round(confidence, 2), "source": source, "needsReview": needs_review}
    if note:
        field["note"] = note
    return field


def _tokens(text: Optional[str]) -> List[str]:
    return sorted(re.sub(r"[^A-Z0-9 ]", " ", (text or "").upper()).split())


def _same_text(a: Optional[str], b: Optional[str]) -> bool:
    return bool(a and b) and _tokens(a) == _tokens(b)


def _overlaps(a: Optional[str], b: Optional[str]) -> bool:
    """One place name contains the other ("MUMBAI" vs "MUMBAI, MAHARASHTRA")."""
    ta, tb = set(_tokens(a)), set(_tokens(b))
    return bool(ta and tb) and (ta <= tb or tb <= ta)


_INDIA_PASSPORT_RE = re.compile(r"[A-Z][0-9]{7}")


def _checked(
    az_value: Optional[str],
    mrz_value: Optional[str],
    mrz_valid: bool,
    label: str,
    warnings: List[str],
    shown: Callable[[Optional[str]], str] = lambda v: v or "",
) -> Optional[Dict[str, Any]]:
    """A value that both azapi and the MRZ carry. None means "leave whatever
    the local pipeline produced" (azapi had nothing to add)."""
    if not az_value:
        return None
    if not mrz_value:
        return confidence_field(
            az_value, 0.8, SOURCE_AZAPI, False,
            "Read by azapi OCR. The machine-readable zone was not read, so this was not cross-checked.",
        )
    if az_value == mrz_value:
        if mrz_valid:
            return confidence_field(mrz_value, 0.99, SOURCE_CONFIRMED, False, "Check digit valid and confirmed by azapi OCR.")
        return confidence_field(
            mrz_value, 0.9, SOURCE_CONFIRMED, False,
            "azapi OCR and the machine-readable zone agree (the zone's own check digit did not validate).",
        )
    detail = f"azapi OCR read '{shown(az_value)}' but the machine-readable zone read '{shown(mrz_value)}'"
    warnings.append(f"{label}: {detail} — please verify manually.")
    if mrz_valid:
        return confidence_field(mrz_value, 0.7, "mrz", True, detail + " (check digit valid) — compare with the passport.")
    return confidence_field(az_value, 0.6, SOURCE_AZAPI, True, detail + " (check digit failed) — compare with the passport.")


def _split_name(az_name: str, mrz: Optional[Dict[str, Any]]) -> Tuple[Optional[str], Optional[str], str]:
    """(given, surname, how). azapi returns the whole name in one line (given
    names first, surname last), so the split comes from the MRZ whenever the two
    agree; otherwise it is a guess and is flagged."""
    tokens = az_name.split()
    if mrz and mrz.get("surname") is not None:
        n_sur = len(str(mrz.get("surname") or "").split())
        if 0 < n_sur < len(tokens):
            return " ".join(tokens[:-n_sur]), " ".join(tokens[-n_sur:]), "mrz-count"
    if len(tokens) >= 2:
        return " ".join(tokens[:-1]), tokens[-1], "guess"
    return (tokens[0] if tokens else None), None, "single"


def _name_fields(az_name: Optional[str], mrz: Optional[Dict[str, Any]], mrz_valid: bool, warnings: List[str]) -> Dict[str, Dict[str, Any]]:
    if not az_name:
        return {}
    if mrz and mrz.get("surname") is not None and _same_text(az_name, f"{mrz.get('givenNames', '')} {mrz.get('surname', '')}"):
        note = "Matches the machine-readable zone and azapi OCR."
        conf = 0.98 if mrz_valid else 0.9
        return {
            "surname": confidence_field(mrz["surname"], conf, SOURCE_CONFIRMED, False, note),
            "givenNames": confidence_field(mrz["givenNames"], conf, SOURCE_CONFIRMED, False, note),
            "fullName": confidence_field(mrz["fullName"], conf, SOURCE_CONFIRMED, False, note),
        }
    given, surname, how = _split_name(az_name, mrz)
    if mrz and mrz.get("surname") is not None:
        mrz_name = f"{mrz.get('givenNames', '')} {mrz.get('surname', '')}".strip()
        detail = f"azapi OCR read the name as '{az_name}' but the machine-readable zone read '{mrz_name}'"
        note = detail + " — compare with the passport."
        warnings.append("Name: " + detail + " — please verify manually.")
    elif how == "guess":
        note = "azapi OCR gives the name on one line; the split into given name and surname is a guess — please check."
    elif how == "single":
        note = "The passport shows a single name — please check which field it belongs in."
    else:
        note = "Read by azapi OCR. The machine-readable zone was not read, so this was not cross-checked."
    out = {
        "givenNames": confidence_field(given, 0.6, SOURCE_AZAPI, True, note),
        "fullName": confidence_field(az_name, 0.6, SOURCE_AZAPI, True, note),
    }
    if surname:
        out["surname"] = confidence_field(surname, 0.6, SOURCE_AZAPI, True, note)
    else:
        out["surname"] = confidence_field(None, 0.0, "none", True, note)
    return out


def _viz_place(az_value: Optional[str], local: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not az_value:
        return None
    local_value = (local or {}).get("value")
    if local_value and _overlaps(az_value, local_value):
        return confidence_field(az_value, 0.95, SOURCE_CONFIRMED, False, "azapi OCR and the local reader agree.")
    return confidence_field(az_value, 0.85, SOURCE_AZAPI, False, "Read by azapi OCR from the printed page.")


def _plus_years(day: date, years: int) -> Optional[date]:
    try:
        return day.replace(year=day.year + years)
    except ValueError:  # 29 February
        return day.replace(year=day.year + years, day=28)


def _issue_field(
    az_issue: Optional[str], local: Optional[Dict[str, Any]], expiry: Optional[str], dob: Optional[str], warnings: List[str]
) -> Optional[Dict[str, Any]]:
    if not az_issue:
        return None
    issue = date.fromisoformat(az_issue)
    exp = date.fromisoformat(expiry) if expiry else None
    born = date.fromisoformat(dob) if dob else None
    if exp and issue >= exp:
        warnings.append("Date of issue: azapi OCR read an issue date that is not before the expiry date — please verify manually.")
        return confidence_field(az_issue, 0.3, SOURCE_AZAPI, True, "Issue date is not before the expiry date — compare with the passport.")
    if born and issue <= born:
        warnings.append("Date of issue: azapi OCR read an issue date that is not after the date of birth — please verify manually.")
        return confidence_field(az_issue, 0.3, SOURCE_AZAPI, True, "Issue date is not after the date of birth — compare with the passport.")
    if exp:
        for years in (10, 5):  # Indian passports: 10 years for adults, 5 for minors; expiry = issue + N years - 1 day
            start = _plus_years(exp, -years)
            if start and start + timedelta(days=1) == issue:
                return confidence_field(az_issue, 0.95, SOURCE_AZAPI, False, f"Consistent with the expiry date ({years}-year validity).")
    local_value = (local or {}).get("value")
    if local_value == az_issue:
        return confidence_field(az_issue, 0.9, SOURCE_CONFIRMED, False, "azapi OCR and the printed-date reading agree.")
    return confidence_field(az_issue, 0.8, SOURCE_AZAPI, False, "Read by azapi OCR. The validity is not the usual 5 or 10 years.")


def _azapi_only(value: Optional[str], note: str = "Read by azapi OCR from the passport.", conf: float = 0.85, review: bool = False) -> Optional[Dict[str, Any]]:
    return confidence_field(value, conf, SOURCE_AZAPI, review, note) if value else None


def build_fields(local_fields: Dict[str, Any], mrz: Optional[Dict[str, Any]], az: Dict[str, Any]) -> Tuple[Dict[str, Any], List[str]]:
    """Returns (fields, warnings): the local fields with azapi's values
    cross-checked and merged in. A key azapi had no value for keeps its local
    value exactly as it was."""
    fields = dict(local_fields)
    warnings: List[str] = []
    mrz_ok = bool(mrz and mrz.get("valid"))

    def put(key: str, field: Optional[Dict[str, Any]]) -> None:
        if field is not None:
            fields[key] = field

    for label in az.get("badDates") or []:
        warnings.append(f"{label}: azapi OCR returned something that is not a valid date — please verify manually.")

    # Name
    for key, field in _name_fields(az.get("name"), mrz, mrz_ok, warnings).items():
        fields[key] = field

    # Passport number, date of birth, expiry: protected by MRZ check digits.
    number = _checked(
        az.get("number"), mrz and mrz.get("passportNumber"), bool(mrz and mrz.get("passportNumberValid")),
        "Passport number", warnings,
    )
    if number is not None and az.get("number") and not _INDIA_PASSPORT_RE.fullmatch(az["number"]) and number["source"] != SOURCE_CONFIRMED:
        number["needsReview"] = True
        number["note"] = (number.get("note", "") + " The format is unusual for an Indian passport (one letter and seven digits).").strip()
        warnings.append("Passport number: the format is unusual for an Indian passport — please verify manually.")
    put("passportNumber", number)
    put("dateOfBirth", _checked(
        az.get("dob"), mrz and mrz.get("dateOfBirth"), bool(mrz and mrz.get("dateOfBirthValid")),
        "Date of birth", warnings, _display_date,
    ))
    put("dateOfExpiry", _checked(
        az.get("expiry"), mrz and mrz.get("dateOfExpiry"), bool(mrz and mrz.get("dateOfExpiryValid")),
        "Date of expiry", warnings, _display_date,
    ))
    put("sex", _checked(az.get("gender") if az.get("gender") in ("M", "F", "X") else None,
                        mrz and mrz.get("sex"), mrz_ok, "Sex", warnings))

    # Country / nationality / type. The MRZ values (already in `fields`) stand
    # unless the MRZ was not read at all.
    if not mrz:
        code = az.get("countryCode")
        put("countryCode", _azapi_only(code, "Read by azapi OCR; the machine-readable zone was not read."))
        put("nationality", _azapi_only(code, "Country code from azapi OCR; the machine-readable zone was not read."))
        put("passportType", _azapi_only(az.get("passportType"), "Read by azapi OCR; the machine-readable zone was not read."))
    elif az.get("countryCode") and mrz.get("issuingCountry") and az["countryCode"] != mrz["issuingCountry"]:
        warnings.append(
            f"Country code: azapi OCR read '{az['countryCode']}' but the machine-readable zone read "
            f"'{mrz['issuingCountry']}' — please verify manually."
        )

    # Issue date, places
    exp_final = (fields.get("dateOfExpiry") or {}).get("value")
    dob_final = (fields.get("dateOfBirth") or {}).get("value")
    put("dateOfIssue", _issue_field(az.get("issue"), fields.get("dateOfIssue"), exp_final, dob_final, warnings))
    put("placeOfBirth", _viz_place(az.get("placeOfBirth"), fields.get("placeOfBirth")))
    put("placeOfIssue", _viz_place(az.get("placeOfIssue"), fields.get("placeOfIssue")))

    # Back-page details (only present when azapi was sent the back page).
    addr = az.get("address") or {}
    put("addressLine1", _azapi_only(addr.get("line1")))
    put("addressLine2", _azapi_only(addr.get("line2")))
    put("addressCity", _azapi_only(addr.get("city")))
    put("addressState", _azapi_only(addr.get("state")))
    put("addressCountry", _azapi_only(addr.get("country")))
    pin = addr.get("pincode")
    put("addressPincode", _azapi_only(pin) if pin and re.fullmatch(r"\d{6}", pin) else None)
    put("fatherName", _azapi_only(az.get("father")))
    put("motherName", _azapi_only(az.get("mother")))
    put("spouseName", _azapi_only(az.get("spouse")))
    old_ok = bool(az.get("oldNumber") and _INDIA_PASSPORT_RE.fullmatch(az["oldNumber"]))
    put("oldPassportNumber", _azapi_only(
        az.get("oldNumber"),
        "Read by azapi OCR from the old-passport line."
        if old_ok else "Read by azapi OCR; the format is unusual for an Indian passport — compare with the old passport.",
        review=not old_ok,
    ))
    put("oldPassportIssueDate", _azapi_only(az.get("oldIssue")))
    put("oldPassportPlace", _azapi_only(az.get("oldPlace")))
    return fields, warnings


# ---------------------------------------------------------------------------
# Images and the short-lived cache
# ---------------------------------------------------------------------------


def to_jpeg_bytes(image: Any) -> bytes:
    """PIL image -> JPEG bytes, longest side capped so uploads stay small."""
    from PIL import Image

    img = image.convert("RGB")
    img.thumbnail((MAX_IMAGE_SIDE_PX, MAX_IMAGE_SIDE_PX), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=JPEG_QUALITY)
    return buf.getvalue()


def _png_base64_to_jpeg(png_base64: str) -> bytes:
    from PIL import Image

    return to_jpeg_bytes(Image.open(io.BytesIO(base64.b64decode(png_base64))))


_cache_lock = threading.Lock()
_cache: Dict[str, Tuple[float, Dict[str, Any]]] = {}


def _cache_key(front: bytes, back: Optional[bytes]) -> str:
    h = hashlib.sha256()
    h.update(front)
    h.update(b"\x00" if back is None else b"\x01" + back)
    return h.hexdigest()


def _cache_get(key: str) -> Optional[Dict[str, Any]]:
    with _cache_lock:
        entry = _cache.get(key)
        if entry and time.monotonic() - entry[0] <= CACHE_TTL_SECONDS:
            return entry[1]
        _cache.pop(key, None)
    return None


def _cache_put(key: str, output: Dict[str, Any]) -> None:
    with _cache_lock:
        now = time.monotonic()
        for stale in [k for k, (t, _) in _cache.items() if now - t > CACHE_TTL_SECONDS]:
            _cache.pop(stale, None)
        while len(_cache) >= CACHE_MAX_ENTRIES:
            _cache.pop(min(_cache, key=lambda k: _cache[k][0]), None)
        _cache[key] = (now, output)


def fetch_output(front: bytes, back: Optional[bytes], post: Optional[Callable[..., Any]] = None) -> Tuple[Dict[str, Any], bool]:
    """(azapi output, served_from_cache). Counts real calls for /api/health."""
    key = _cache_key(front, back)
    cached = _cache_get(key)
    if cached is not None:
        with _usage_lock:
            _usage["cacheHits"] += 1
        return cached, True
    try:
        output = call_api(front, back, post=post)
    except AzapiError as e:
        logger.warning("azapi call failed: %s", e.kind)
        _record_error(e)
        raise
    with _usage_lock:
        _usage["calls"] += 1
    _record_error(None)
    _cache_put(key, output)
    return output, False


# ---------------------------------------------------------------------------
# Entry point used by ocr_runner.process_passport_file
# ---------------------------------------------------------------------------


def _back_page_bytes(pages: List[Any], bio_index: int) -> Tuple[Optional[bytes], Optional[int]]:
    """The page after the data page, when the uploaded file has one within the
    pages the app reads automatically."""
    nxt = bio_index + 1
    if nxt < min(len(pages), AUTO_PAGE_LIMIT):
        return to_jpeg_bytes(pages[nxt]), nxt
    return None, None


def enrich_bio_result(result: Dict[str, Any], pages: List[Any], bio_index: int, post: Optional[Callable[..., Any]] = None) -> None:
    """Adds azapi's reading to a data-page result IN PLACE. Never raises: any
    problem leaves the local result as it was and records a notice."""
    if not is_enabled() or result.get("pageKind") != "bio" or not result.get("processedImageBase64"):
        return
    try:
        front = _png_base64_to_jpeg(result["processedImageBase64"])
        back, back_index = _back_page_bytes(pages, bio_index)
        output, from_cache = fetch_output(front, back, post=post)
        az = normalize(output)
        fields, warnings = build_fields(result.get("fields") or {}, result.get("mrz"), az)
    except AzapiError as e:
        result.setdefault("notices", []).append(f"azapi OCR was not used ({e}) — the local reader was used instead.")
        result["azapi"] = {"used": False, "reason": e.kind}
        return
    except Exception as e:  # noqa: BLE001 — never let an extra reader break the upload; the local result stands
        logger.warning("azapi merge failed: %s", type(e).__name__)
        result.setdefault("notices", []).append("azapi OCR could not be applied — the local reader was used instead.")
        result["azapi"] = {"used": False, "reason": "unexpected"}
        return

    # Salutation depends on the final sex / date of birth / spouse.
    try:
        import passport_layout

        sal = passport_layout.derive_salutation(
            (fields.get("sex") or {}).get("value"), (fields.get("dateOfBirth") or {}).get("value"), az.get("spouse")
        )
        if sal:
            fields["salutation"] = confidence_field(
                sal["value"], 0.6, "derived", True, "Worked out from sex and date of birth: " + sal["reason"]
            )
            fields["salutation"]["canBeMrs"] = bool(sal.get("canBeMrs"))
    except Exception:  # noqa: BLE001 — the salutation is a convenience; the local one stays
        pass

    result["fields"] = fields
    result["warnings"] = list(result.get("warnings") or []) + warnings
    result.setdefault("notices", []).append("Details were read with azapi OCR and cross-checked against the machine-readable zone.")
    result["ocrProvider"] = "azapi"
    result["azapi"] = {"used": True, "fromCache": from_cache, "backPageIndex": back_index}
