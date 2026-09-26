"""
Khanna Travels & Holidays — OpenRouter vision-model OCR (TESTING PATH)
=======================================================================

A second, independent passport-OCR path used to evaluate a vision-capable
LLM (via OpenRouter) against the existing Tesseract / Google Cloud Vision
pipeline in ocr_runner.py. This module does NOT replace, modify, or get
called by that pipeline — it is wired to its own, separately-labelled
frontend button (see js/passport/passport-processing.js) so staff can try
it side-by-side without touching the production OCR flow.

Security model (per the project's permanent instructions):
  - OPENROUTER_API_KEY is read from an environment variable only, at call
    time. It is never hardcoded, never logged, and never returned to the
    frontend in any response body.
  - The frontend never talks to OpenRouter directly. It calls this
    backend's own endpoint (POST /api/passport/process-openrouter, see
    app.py); this module is the only thing that ever sees the API key and
    is the only thing that calls out to https://openrouter.ai.

Trust model — why this module does NOT simply trust the model's own
confidence self-reports:
  A vision LLM can describe how confident it "feels," but that is a
  self-assessment, not a verifiable signal (project rule 9 — do not fake
  functionality; project rule 10 — OCR is never auto-verified). Instead,
  whenever the model returns MRZ lines that parse as a structurally valid
  TD3 MRZ, this module re-validates them with the SAME check-digit parser
  the existing pipeline already uses and trusts (ocr_runner.parse_mrz_td3,
  ICAO 9303 check digits) — a real, deterministic, tamper-evident signal —
  and derives confidence/needsReview from THAT, exactly like
  ocr_runner.extract_passport_fields already does for the Tesseract/Google
  path (project rule 15 — reuse tested logic, don't duplicate it). Fields
  the MRZ does not carry (place of birth, date of issue, place of issue)
  always come directly from the model's own read, always flagged for
  review, since there is no independent way to verify them.

Model selection: at the time this module was written (2026-09-25), the
current OpenRouter model catalogue was checked via a live fetch of
https://openrouter.ai/api/v1/models (WebSearch was unavailable in that
session, and direct API access was blocked by this sandbox's own egress
policy, so a browser-based fetch tool was the only way to check it — see
the accompanying chat report for that caveat). "google/gemini-3.8-flash-
20260902" was the model chosen: its `architecture.input_modalities` field
listed "image", confirmed on two separate fetches. If OpenRouter renames
or retires this model, set OPENROUTER_MODEL in the environment to override
it without any code change — no need to touch DEFAULT_MODEL below.
"""

from __future__ import annotations

import base64
import json
import os
import re
from typing import Any, Dict, List, Optional

import requests

from ocr_runner import MRZ_CHARSET_RE, _confidence_field, parse_mrz_td3

CHAT_COMPLETIONS_URL = "https://openrouter.ai/api/v1/chat/completions"
REQUEST_TIMEOUT_SECONDS = 60

# Overridable via the OPENROUTER_MODEL environment variable — see the
# module docstring above for how/why this was chosen and verified.
DEFAULT_MODEL = "google/gemini-3.8-flash-20260902"

MIME_BY_EXTENSION = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
}

# The 11 plain-text fields requested (Given Name / Surname / Full Name /
# Passport Number / Nationality / Date of Birth / Place of Birth / Sex /
# Date of Issue / Date of Expiry / Place of Issue), by the JSON key the
# model is asked to return them under. MRZ lines are handled separately
# (mrzLine1 / mrzLine2), since they drive the check-digit re-validation
# above rather than being surfaced as plain fields themselves.
MODEL_FIELD_KEYS = [
    "givenName",
    "surname",
    "fullName",
    "passportNumber",
    "nationality",
    "dateOfBirth",
    "placeOfBirth",
    "sex",
    "dateOfIssue",
    "dateOfExpiry",
    "placeOfIssue",
]

ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

PROMPT = """You are transcribing a passport bio-data page for a travel agency's records. Look ONLY at the image provided. Return a single JSON object — nothing else, no markdown code fences, no commentary before or after it — with exactly these keys:

{
  "givenName": string or null,
  "surname": string or null,
  "fullName": string or null,
  "passportNumber": string or null,
  "nationality": string or null,
  "dateOfBirth": string or null,
  "placeOfBirth": string or null,
  "sex": string or null,
  "dateOfIssue": string or null,
  "dateOfExpiry": string or null,
  "placeOfIssue": string or null,
  "mrzLine1": string or null,
  "mrzLine2": string or null
}

Rules — follow all of these exactly:
1. Never guess, infer, autocomplete, or invent a value you cannot actually read in the image. If a field is missing, unreadable, cropped out of frame, or you are not reasonably sure, return null for that field. An honest null is far better than a wrong guess.
2. "dateOfBirth", "dateOfIssue" and "dateOfExpiry" must each be either a strict "YYYY-MM-DD" string, or null if you cannot determine the exact date in that format. Do not return a partial or differently-formatted date.
3. "sex" must be exactly "M", exactly "F", or null — nothing else.
4. "mrzLine1" and "mrzLine2" are the two 44-character machine-readable zone lines printed at the bottom of the bio-data page (the lines made of capital letters, digits, and "<" fill characters). Transcribe them character-for-character exactly as printed, including every "<" fill character — do not trim, reformat, or guess missing characters. If the MRZ is not visible or not present in the image, return null for both.
5. "fullName" is the person's complete name as printed on the passport (given name(s) and surname together). "givenName" and "surname" are the same name split into its two parts.
6. Do not include any explanation, apology, or extra text outside the single JSON object. Do not wrap the JSON in a markdown code fence.
"""


class OpenRouterOCRError(Exception):
    """Raised for any failure calling OpenRouter or interpreting its
    response — network failure, auth failure, rate limit, or a response
    that isn't usable JSON. Callers (app.py) map this to a clean 503,
    exactly like ocr_providers.OCRProviderError already is for the
    existing pipeline."""


def _mime_type_for(filename: str) -> str:
    ext = os.path.splitext(filename or "")[1].lower()
    mime = MIME_BY_EXTENSION.get(ext)
    if not mime:
        raise OpenRouterOCRError(
            f"Unsupported image type '{ext}' for OpenRouter OCR. "
            f"Allowed: {sorted(MIME_BY_EXTENSION)} (a scanned image, not a PDF — "
            "this testing path only implements single-image OCR per the current spec)."
        )
    return mime


def _extract_json_object(raw_text: str) -> Dict[str, Any]:
    """Parses the model's response as a JSON object. Models asked to
    "return only JSON" sometimes still wrap it in a ```json ... ``` fence
    or add a stray leading/trailing character — both are stripped
    defensively — but this never invents field values on a genuine parse
    failure: it raises instead, so the caller surfaces a clear error
    rather than silently fabricating a result (project rule 9)."""
    text = (raw_text or "").strip()

    # Strip a markdown code fence if the model added one despite being
    # told not to (```json ... ``` or plain ``` ... ```).
    fence_match = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, re.DOTALL)
    if fence_match:
        text = fence_match.group(1).strip()

    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass

    # Fall back to locating the first balanced {...} block in the text,
    # in case the model added stray text around an otherwise-valid object.
    start = text.find("{")
    if start != -1:
        depth = 0
        for i in range(start, len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    candidate = text[start : i + 1]
                    try:
                        parsed = json.loads(candidate)
                        if isinstance(parsed, dict):
                            return parsed
                    except json.JSONDecodeError:
                        break

    raise OpenRouterOCRError(
        "The model's response wasn't valid JSON, so nothing was extracted. "
        f"First 200 characters of what it returned: {text[:200]!r}"
    )


def _call_openrouter_vision(image_bytes: bytes, filename: str, api_key: str, model: str) -> str:
    mime = _mime_type_for(filename)
    data_url = "data:" + mime + ";base64," + base64.b64encode(image_bytes).decode("ascii")

    payload = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": PROMPT},
                    {"type": "image_url", "image_url": {"url": data_url}},
                ],
            }
        ],
        "temperature": 0,
        # Without an explicit cap, some models/providers routed through
        # OpenRouter default to a small max output length — easily enough
        # to truncate this response (full name + two 44-character MRZ
        # lines + 8 more fields), which would otherwise fail downstream
        # with a confusing "wasn't valid JSON" error rather than a clear
        # one. 1024 tokens is comfortably more than this JSON object needs.
        "max_tokens": 1024,
    }
    headers = {
        "Authorization": "Bearer " + api_key,
        "Content-Type": "application/json",
        # Required/recommended by OpenRouter for attributing usage — no
        # secret information, just identifies the calling app.
        "HTTP-Referer": "https://khannatravels.com",
        "X-Title": "Khanna Travels & Holidays - Passport OCR (testing)",
    }

    try:
        resp = requests.post(
            CHAT_COMPLETIONS_URL, headers=headers, json=payload, timeout=REQUEST_TIMEOUT_SECONDS
        )
    except requests.RequestException as e:
        raise OpenRouterOCRError(f"Could not reach OpenRouter: {e}")

    if resp.status_code == 401:
        raise OpenRouterOCRError(
            "OpenRouter rejected the request (401 Unauthorized) — the OPENROUTER_API_KEY "
            "environment variable is missing, invalid, or has been revoked."
        )
    if resp.status_code == 402:
        raise OpenRouterOCRError(
            "OpenRouter rejected the request (402 Payment Required) — this account has no "
            "credit available for this model. Add credit at https://openrouter.ai/settings/credits "
            "or switch OPENROUTER_MODEL to a free model."
        )
    if resp.status_code == 429:
        raise OpenRouterOCRError("OpenRouter rate-limited this request (429). Please wait and try again.")
    if resp.status_code != 200:
        raise OpenRouterOCRError(
            f"OpenRouter request failed (HTTP {resp.status_code}): {resp.text[:300]}"
        )

    try:
        body = resp.json()
    except ValueError:
        raise OpenRouterOCRError("OpenRouter returned a response that wasn't valid JSON.")

    choices = body.get("choices") or []
    if not choices:
        raise OpenRouterOCRError(f"OpenRouter returned no choices in its response: {json.dumps(body)[:300]}")

    message = choices[0].get("message") or {}
    content = message.get("content")
    if not content or not isinstance(content, str):
        raise OpenRouterOCRError("OpenRouter's response had no readable text content.")

    return content


def _looks_like_mrz_line(raw: Optional[str]) -> Optional[str]:
    """Cleans a candidate MRZ line the same way ocr_runner.find_mrz_lines
    does (uppercase, strip anything outside A-Z0-9<, require >=30 usable
    characters) and returns the cleaned line, or None if it doesn't look
    like real MRZ text. Reused tolerance, not a new rule, so a model's MRZ
    read is judged by the exact same bar the existing pipeline already
    uses."""
    if not raw or not isinstance(raw, str):
        return None
    cleaned = MRZ_CHARSET_RE.sub("", raw.upper().replace(" ", ""))
    if len(cleaned) < 30:
        return None
    return cleaned


def _clean_text_field(value: Any) -> Optional[str]:
    # The prompt asks for strings, but a model can still return a bare
    # number (e.g. a passport number with no letters) unquoted as JSON —
    # treated as real data, not dropped, since the value itself is genuine
    # and only its JSON type is unexpected (project rule 7 — never lose a
    # real value the model actually read). Any other JSON type (an object,
    # a list, a boolean) is too ambiguous to safely coerce, so it's treated
    # as not provided rather than guessed at.
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        value = str(value)
    if not isinstance(value, str):
        return None
    value = value.strip()
    if not value or value.lower() in ("null", "none", "n/a", "na", "unknown"):
        return None
    return value


def _clean_date_field(value: Any, warnings: List[str], field_label: str) -> Optional[str]:
    """Defensive backend-side check alongside the prompt's own instruction:
    the frontend's date inputs (applicant.dob, current.expiryDate) are
    native <input type="date">, which silently blanks any value that isn't
    exactly YYYY-MM-DD — passing through a malformed date here would look
    like data loss with no explanation, so it's nulled out with a clear
    warning instead."""
    cleaned = _clean_text_field(value)
    if cleaned is None:
        return None
    if not ISO_DATE_RE.match(cleaned):
        warnings.append(
            f"The model returned {field_label} as \"{cleaned}\", which isn't a plain YYYY-MM-DD date — "
            "left blank for manual entry rather than guessing the format."
        )
        return None
    return cleaned


def _clean_sex_field(value: Any) -> Optional[str]:
    cleaned = _clean_text_field(value)
    if cleaned is None:
        return None
    cleaned = cleaned.upper()
    return cleaned if cleaned in ("M", "F") else None


def extract_passport_fields_via_openrouter(image_bytes: bytes, filename: str) -> Dict[str, Any]:
    """Main entry point. Reads OPENROUTER_API_KEY / OPENROUTER_MODEL from
    the environment, calls the vision model once, and returns a result
    shaped exactly like ocr_runner.process_passport_file's own return
    value so js/passport/passport-review-form.js's applyOcrResult() can
    render it without any frontend-side special-casing."""
    api_key = (os.environ.get("OPENROUTER_API_KEY") or "").strip()
    if not api_key:
        raise OpenRouterOCRError(
            "OPENROUTER_API_KEY is not set on this backend. Set it as an environment variable "
            "(see .env.example) — it is never read from, or accepted from, the frontend."
        )
    model = (os.environ.get("OPENROUTER_MODEL") or "").strip() or DEFAULT_MODEL

    raw_content = _call_openrouter_vision(image_bytes, filename, api_key, model)
    parsed = _extract_json_object(raw_content)

    warnings: List[str] = []

    model_values = {key: _clean_text_field(parsed.get(key)) for key in MODEL_FIELD_KEYS}
    model_values["dateOfBirth"] = _clean_date_field(parsed.get("dateOfBirth"), warnings, "date of birth")
    model_values["dateOfIssue"] = _clean_date_field(parsed.get("dateOfIssue"), warnings, "date of issue")
    model_values["dateOfExpiry"] = _clean_date_field(parsed.get("dateOfExpiry"), warnings, "date of expiry")
    model_values["sex"] = _clean_sex_field(parsed.get("sex"))

    mrz_line1 = _looks_like_mrz_line(parsed.get("mrzLine1"))
    mrz_line2 = _looks_like_mrz_line(parsed.get("mrzLine2"))

    mrz_parsed: Optional[Dict[str, Any]] = None
    if mrz_line1 and mrz_line2:
        mrz_parsed = parse_mrz_td3(mrz_line1, mrz_line2)
        warnings.extend(mrz_parsed["warnings"])
    elif parsed.get("mrzLine1") or parsed.get("mrzLine2"):
        warnings.append(
            "The model returned MRZ text, but it didn't look like two valid 44-character MRZ lines — "
            "please verify passport number, dates, name and nationality manually."
        )
    else:
        warnings.append("MRZ lines were not returned — passport data will need to be double-checked manually.")

    fields: Dict[str, Any] = {}

    # MRZ-authoritative when the MRZ itself parsed (same pattern, and same
    # confidence/needsReview thresholds, as ocr_runner.extract_passport_fields
    # uses for the Tesseract/Google Vision path — project rule 15).
    if mrz_parsed:
        fields["fullName"] = _confidence_field(mrz_parsed["fullName"], 0.95 if mrz_parsed["valid"] else 0.5, "mrz", not mrz_parsed["valid"])
        fields["surname"] = _confidence_field(mrz_parsed["surname"], 0.95 if mrz_parsed["valid"] else 0.5, "mrz", not mrz_parsed["valid"])
        fields["givenNames"] = _confidence_field(mrz_parsed["givenNames"], 0.95 if mrz_parsed["valid"] else 0.5, "mrz", not mrz_parsed["valid"])
        fields["passportNumber"] = _confidence_field(
            mrz_parsed["passportNumber"], 0.95 if mrz_parsed["passportNumberValid"] else 0.4, "mrz", not mrz_parsed["passportNumberValid"]
        )
        fields["nationality"] = _confidence_field(mrz_parsed["nationality"], 0.9 if mrz_parsed["valid"] else 0.5, "mrz", not mrz_parsed["valid"])
        fields["dateOfBirth"] = _confidence_field(
            mrz_parsed["dateOfBirth"], 0.95 if mrz_parsed["dateOfBirthValid"] else 0.4, "mrz", not mrz_parsed["dateOfBirthValid"]
        )
        fields["sex"] = _confidence_field(mrz_parsed["sex"], 0.9 if mrz_parsed["valid"] else 0.5, "mrz", not mrz_parsed["valid"])
        fields["dateOfExpiry"] = _confidence_field(
            mrz_parsed["dateOfExpiry"], 0.95 if mrz_parsed["dateOfExpiryValid"] else 0.4, "mrz", not mrz_parsed["dateOfExpiryValid"]
        )
        fields["countryCode"] = _confidence_field(mrz_parsed["issuingCountry"], 0.9 if mrz_parsed["valid"] else 0.5, "mrz", not mrz_parsed["valid"])
        fields["passportType"] = _confidence_field(mrz_parsed["documentType"], 0.9 if mrz_parsed["valid"] else 0.5, "mrz", not mrz_parsed["valid"])
    else:
        # No usable MRZ — fall back to the model's own direct read of the
        # visible text, always at a flat, lower confidence and always
        # flagged for review (no deterministic check available for these).
        fields["fullName"] = _confidence_field(model_values["fullName"], 0.55 if model_values["fullName"] else 0.0, "openrouter", True)
        fields["surname"] = _confidence_field(model_values["surname"], 0.55 if model_values["surname"] else 0.0, "openrouter", True)
        fields["givenNames"] = _confidence_field(model_values["givenName"], 0.55 if model_values["givenName"] else 0.0, "openrouter", True)
        fields["passportNumber"] = _confidence_field(model_values["passportNumber"], 0.55 if model_values["passportNumber"] else 0.0, "openrouter", True)
        fields["nationality"] = _confidence_field(model_values["nationality"], 0.5 if model_values["nationality"] else 0.0, "openrouter", True)
        fields["dateOfBirth"] = _confidence_field(model_values["dateOfBirth"], 0.5 if model_values["dateOfBirth"] else 0.0, "openrouter", True)
        fields["sex"] = _confidence_field(model_values["sex"], 0.5 if model_values["sex"] else 0.0, "openrouter", True)
        fields["dateOfExpiry"] = _confidence_field(model_values["dateOfExpiry"], 0.5 if model_values["dateOfExpiry"] else 0.0, "openrouter", True)

    # Fields the MRZ never carries — always the model's own direct read,
    # regardless of whether the MRZ itself was usable.
    fields["placeOfBirth"] = _confidence_field(model_values["placeOfBirth"], 0.5 if model_values["placeOfBirth"] else 0.0, "openrouter", True)
    fields["dateOfIssue"] = _confidence_field(model_values["dateOfIssue"], 0.5 if model_values["dateOfIssue"] else 0.0, "openrouter", True)
    fields["placeOfIssue"] = _confidence_field(model_values["placeOfIssue"], 0.5 if model_values["placeOfIssue"] else 0.0, "openrouter", True)

    return {
        "isBlank": False,
        "fields": fields,
        "mrz": mrz_parsed,
        "verificationStatus": "OCR Extracted — Please Verify",
        "warnings": warnings,
        "provider": "openrouter",
        "model": model,
    }
