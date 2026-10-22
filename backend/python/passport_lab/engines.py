"""
Passport Lab — engine adapters and comparison logic (no Streamlit imports, so
everything here is unit-testable).

Every engine returns the SAME shape:

    {
      "engine":  "mrz_v2",
      "label":   "Free local MRZ reader (v2)",
      "ok":      True,                 # engine ran without an error
      "error":   "",                   # why it did not, if ok is False
      "seconds": 1.8,
      "fields":  {"surname": "SHARMA", ...},   # only keys it actually produced
      "mrz":     {"line1": ..., "line2": ..., "checks": {...},
                  "confidence": "high", "repairs": [...]}   # or None
      "warnings": [...],
      "cloud":   False,                # True if the image left this computer
    }

Nothing is written to disk and nothing is logged. Cloud engines are only run
when the caller explicitly asks (the UI makes the person tick a consent box).
"""

from __future__ import annotations

import io
import os
import re
import threading
import time
from typing import Any, Callable, Dict, List, Optional

PASSPORT_FIELDS: List[str] = [
    "surname", "givenNames", "passportNumber", "nationality", "issuingCountry",
    "dateOfBirth", "sex", "dateOfExpiry", "placeOfBirth", "placeOfIssue",
    "dateOfIssue", "issuingAuthority",
]
# Fields printed in the MRZ (machine-readable zone) — check-digit protected.
MRZ_FIELDS = {"surname", "givenNames", "passportNumber", "nationality", "issuingCountry", "dateOfBirth", "sex", "dateOfExpiry"}

FIELD_LABELS = {
    "surname": "Surname", "givenNames": "Given names", "passportNumber": "Passport number",
    "nationality": "Nationality", "issuingCountry": "Issuing country", "dateOfBirth": "Date of birth",
    "sex": "Sex", "dateOfExpiry": "Date of expiry", "placeOfBirth": "Place of birth",
    "placeOfIssue": "Place of issue", "dateOfIssue": "Date of issue", "issuingAuthority": "Issuing authority",
}

ENGINE_LABELS = {
    "current": "Current website pipeline",
    "mrz_v2": "Free local MRZ reader (v2)",
    "google": "Google Vision (website pipeline on Google OCR)",
    "openrouter": "AI vision model (OpenRouter)",
}
CLOUD_ENGINES = {"google", "openrouter"}

_provider_lock = threading.Lock()


def load_env_file() -> None:
    """Loads backend/python/.env (if present) so keys the website already uses
    are found. Values are never printed or stored by the lab."""
    try:
        from dotenv import load_dotenv

        here = os.path.dirname(os.path.abspath(__file__))
        load_dotenv(os.path.join(os.path.dirname(here), ".env"))
    except Exception:
        pass


def key_status() -> Dict[str, bool]:
    return {
        "google": bool(os.environ.get("GOOGLE_VISION_API_KEY", "").strip()),
        "openrouter": bool(os.environ.get("OPENROUTER_API_KEY", "").strip()),
    }


def _result(engine: str, **kw: Any) -> Dict[str, Any]:
    base = {
        "engine": engine, "label": ENGINE_LABELS[engine], "ok": False, "error": "", "seconds": 0.0,
        "fields": {}, "mrz": None, "warnings": [], "cloud": engine in CLOUD_ENGINES,
    }
    base.update(kw)
    return base


def _flatten_site_fields(fields: Dict[str, Any]) -> Dict[str, str]:
    """The website pipeline's {key: {value, confidence, ...}} -> {key: value}."""
    mapping = {"countryCode": "issuingCountry"}
    out: Dict[str, str] = {}
    for key, entry in (fields or {}).items():
        target = mapping.get(key, key)
        if target not in PASSPORT_FIELDS:
            continue
        val = entry.get("value") if isinstance(entry, dict) else entry
        if val not in (None, ""):
            out[target] = str(val).strip()
    return out


def _mrz_summary_from_parsed(parsed: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not parsed:
        return None
    return {
        "line1": parsed.get("line1", ""), "line2": parsed.get("line2", ""),
        "checks": {
            "passportNumber": parsed.get("passportNumberValid"), "dateOfBirth": parsed.get("dateOfBirthValid"),
            "dateOfExpiry": parsed.get("dateOfExpiryValid"), "personalNumber": parsed.get("personalNumberValid"),
            "composite": parsed.get("compositeValid"),
        },
        "confidence": "all checks pass" if parsed.get("valid") else "check digit failed",
        "repairs": [],
    }


def render_page_png(path: str, page_index: int = 0) -> bytes:
    import ocr_runner

    pages = ocr_runner.load_pages(path)
    buf = io.BytesIO()
    pages[page_index].convert("RGB").save(buf, format="PNG")
    return buf.getvalue()


def _timed(engine: str, fn: Callable[[], Dict[str, Any]]) -> Dict[str, Any]:
    t0 = time.time()
    try:
        res = fn()
        res["ok"] = True
    except Exception as exc:  # an engine failing must never take the lab down
        res = _result(engine, error=f"{type(exc).__name__}: {str(exc)[:300]}")
    res["seconds"] = round(time.time() - t0, 2)
    return res


# ---------------------------------------------------------------- engines


def run_current(path: str, page_index: int = 0) -> Dict[str, Any]:
    def go() -> Dict[str, Any]:
        import ocr_runner

        # use_mrz_v2=False: this column must stay the ORIGINAL pipeline so the
        # comparison against the new reader remains meaningful.
        out = ocr_runner.process_passport_file(path, page_index=page_index, use_mrz_v2=False)
        return _result(
            "current", fields=_flatten_site_fields(out.get("fields")),
            mrz=_mrz_summary_from_parsed(out.get("mrz")), warnings=list(out.get("warnings", [])),
        )

    return _timed("current", go)


def run_mrz_v2(path: str, page_index: int = 0) -> Dict[str, Any]:
    def go() -> Dict[str, Any]:
        import mrz_reader
        import ocr_runner

        pages = ocr_runner.load_pages(path)
        img = ocr_runner.pil_to_bgr(pages[page_index])
        out = mrz_reader.read_mrz(img, max_seconds=60)
        mrz = None
        if out.get("found"):
            mrz = {
                "line1": out["line1"], "line2": out["line2"], "checks": out["checks"],
                "confidence": out["confidence"], "repairs": out["repairs"],
            }
        return _result("mrz_v2", fields=mrz_reader.fields_from_result(out), mrz=mrz, warnings=out.get("warnings", []))

    return _timed("mrz_v2", go)


def run_google(path: str, page_index: int = 0) -> Dict[str, Any]:
    def go() -> Dict[str, Any]:
        import ocr_providers
        import ocr_runner

        key = os.environ.get("GOOGLE_VISION_API_KEY", "").strip()
        if not key:
            raise RuntimeError("GOOGLE_VISION_API_KEY is not set (put it in backend/python/.env).")
        # ocr_runner reads a module-level provider; swap it for this one call.
        with _provider_lock:
            original = ocr_runner._provider
            ocr_runner._provider = ocr_providers.GoogleVisionOCRProvider(key)
            try:
                out = ocr_runner.process_passport_file(path, page_index=page_index, use_mrz_v2=False)
            finally:
                ocr_runner._provider = original
        return _result(
            "google", fields=_flatten_site_fields(out.get("fields")),
            mrz=_mrz_summary_from_parsed(out.get("mrz")), warnings=list(out.get("warnings", [])),
        )

    return _timed("google", go)


def run_openrouter(path: str, page_index: int = 0) -> Dict[str, Any]:
    def go() -> Dict[str, Any]:
        import openrouter_ocr

        png = render_page_png(path, page_index)
        out = openrouter_ocr.extract_passport_fields_via_openrouter(png, "passport.png")
        res = _result(
            "openrouter", fields=_flatten_site_fields(out.get("fields")),
            mrz=_mrz_summary_from_parsed(out.get("mrz")), warnings=list(out.get("warnings", [])),
        )
        res["model"] = out.get("model")
        return res

    return _timed("openrouter", go)


RUNNERS: Dict[str, Callable[[str, int], Dict[str, Any]]] = {
    "current": run_current, "mrz_v2": run_mrz_v2, "google": run_google, "openrouter": run_openrouter,
}


# ---------------------------------------------------------------- comparison


def normalise(field: str, value: Any) -> str:
    """Canonical form for comparing/scoring values from different engines."""
    s = str(value or "").strip().upper()
    if not s:
        return ""
    if field in ("dateOfBirth", "dateOfExpiry", "dateOfIssue"):
        m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", s)
        if m:
            return s
        m = re.fullmatch(r"(\d{1,2})[./\- ](\d{1,2})[./\- ](\d{4})", s)
        if m:
            return f"{m.group(3)}-{int(m.group(2)):02d}-{int(m.group(1)):02d}"
        return s
    if field == "sex":
        return {"MALE": "M", "FEMALE": "F", "UNSPECIFIED": "X", "<": "X"}.get(s, s[:1])
    return re.sub(r"[^A-Z0-9]+", "", s)


def compare_engines(results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """One row per field: each engine's value + status
    ('agree' | 'disagree' | 'single' | 'empty')."""
    rows = []
    for field in PASSPORT_FIELDS:
        values = {r["engine"]: r["fields"].get(field, "") for r in results if r["ok"]}
        non_empty = {e: normalise(field, v) for e, v in values.items() if normalise(field, v)}
        distinct = set(non_empty.values())
        if not non_empty:
            status = "empty"
        elif len(non_empty) == 1:
            status = "single"
        elif len(distinct) == 1:
            status = "agree"
        else:
            status = "disagree"
        rows.append({"field": field, "label": FIELD_LABELS[field], "values": values, "status": status, "inMrz": field in MRZ_FIELDS})
    return rows


def score_against_truth(results: List[Dict[str, Any]], truth: Dict[str, str]) -> Dict[str, Dict[str, Any]]:
    """Per-engine accuracy on the fields the person typed in as ground truth."""
    checked = [f for f in PASSPORT_FIELDS if normalise(f, truth.get(f, ""))]
    out: Dict[str, Dict[str, Any]] = {}
    for r in results:
        if not r["ok"]:
            continue
        correct, wrong, missing = [], [], []
        for f in checked:
            got = normalise(f, r["fields"].get(f, ""))
            want = normalise(f, truth[f])
            if not got:
                missing.append(f)
            elif got == want:
                correct.append(f)
            else:
                wrong.append(f)
        out[r["engine"]] = {"checked": len(checked), "correct": correct, "wrong": wrong, "missing": missing}
    return out
