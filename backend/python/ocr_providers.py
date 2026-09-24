"""
Khanna Travels & Holidays — OCR provider abstraction
=======================================================

Everything in ocr_runner.py that used to call `pytesseract` directly now
goes through one of the two provider classes below instead, selected once
by get_ocr_provider(). This is the ONLY thing that changes between running
this backend locally (Tesseract — completely unchanged behaviour from
before this file existed) and running it on Vercel (Google Cloud Vision —
Tesseract's own binary cannot be installed inside a Vercel serverless
Python function; see backend/python/VERCEL_DEPLOYMENT.md). Every
downstream MRZ-parsing / field-extraction / confidence-scoring rule that
already lived in ocr_runner.py is completely untouched by this refactor —
this file only ever answers the two questions an engine needs answered
regardless of which one is actually running underneath: "what text is in
this image" and "how confident was the engine, on average, about the
words it found."

No API key is ever read by, or reachable from, the frontend (project rule
12) — GOOGLE_VISION_API_KEY is read here, server-side only, from an
environment variable the hosting platform injects at runtime (Vercel
project settings, or a local .env for a staff member's own machine —
never committed, never hardcoded).
"""

from __future__ import annotations

import base64
import os
import shutil
import statistics
import sys
from typing import Any, Dict, List, Optional, Tuple

import requests

# ---------------------------------------------------------------------------
# Tesseract binary discovery (moved here unchanged from ocr_runner.py — this
# is now the OCR-engine-specific module, so engine-specific configuration
# belongs here rather than in the orchestration file)
# ---------------------------------------------------------------------------

TESSERACT_CMD_ENV_VAR = "KHANNA_TESSERACT_CMD"

_WINDOWS_TESSERACT_CANDIDATES = [
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Programs\Tesseract-OCR\tesseract.exe"),
    os.path.expandvars(r"%LOCALAPPDATA%\Tesseract-OCR\tesseract.exe"),
]


def find_tesseract_cmd() -> Optional[str]:
    """Best-effort discovery of the real tesseract executable. Checked in
    order: an explicit KHANNA_TESSERACT_CMD environment variable (for a
    non-default install location), whatever `tesseract` already resolves to
    on PATH (works on every OS — checked first so a correct PATH setup is
    always respected over a hardcoded guess), then the exact folders the
    official Windows installer uses by default. Returns None — never
    raises, never guesses — if nothing real is found."""
    override = os.environ.get(TESSERACT_CMD_ENV_VAR)
    if override and os.path.isfile(override):
        return override

    on_path = shutil.which("tesseract") or shutil.which("tesseract.exe")
    if on_path:
        return on_path

    if sys.platform.startswith("win"):
        for candidate in _WINDOWS_TESSERACT_CANDIDATES:
            if candidate and os.path.isfile(candidate):
                return candidate

    return None


class OCRProviderError(Exception):
    """Raised when the configured OCR engine genuinely cannot process an
    image — never swallowed to fabricate a result (project rule 9)."""


class OCRProvider:
    """Common interface ocr_runner.py codes against. Every image argument
    is a single-channel (grayscale) numpy array — exactly what ocr_runner.py
    already had on hand at each of its three OCR call sites before this
    refactor."""

    name = "base"

    def ocr_text(self, gray_image, config: str = "") -> str:
        raise NotImplementedError

    def ocr_mean_confidence_and_text(self, gray_image) -> Tuple[float, str]:
        """Returns (mean word confidence on a 0-100 scale, joined recognized
        text) — used only for scoring which of 4 candidate rotations looks
        most like real, confidently-read text
        (see ocr_runner.evaluate_orientations)."""
        raise NotImplementedError

    def status(self) -> Dict[str, Any]:
        """Real, non-fabricated status for /api/health — never claims
        'available' without having actually checked something real."""
        raise NotImplementedError


# ---------------------------------------------------------------------------
# Tesseract (local/offline) — unchanged behaviour from before this refactor
# ---------------------------------------------------------------------------


class TesseractOCRProvider(OCRProvider):
    name = "tesseract"

    def __init__(self):
        # Imported lazily (only when this provider is actually selected) so
        # a Tesseract-less deployment running the Google Cloud Vision provider instead
        # never needs this import to succeed at all.
        import pytesseract

        self._pytesseract = pytesseract
        cmd = find_tesseract_cmd()
        if cmd:
            pytesseract.pytesseract.tesseract_cmd = cmd

    def ocr_text(self, gray_image, config: str = "") -> str:
        return self._pytesseract.image_to_string(gray_image, config=config)

    def ocr_mean_confidence_and_text(self, gray_image) -> Tuple[float, str]:
        data = self._pytesseract.image_to_data(gray_image, output_type=self._pytesseract.Output.DICT)
        confidences = [int(c) for c in data.get("conf", []) if str(c).strip() not in ("-1", "")]
        mean_conf = statistics.mean(confidences) if confidences else 0.0
        text = " ".join(t for t in data.get("text", []) if t.strip())
        return mean_conf, text

    def status(self) -> Dict[str, Any]:
        """Real, live status: actually invokes the configured binary and
        reports what happened, rather than just checking a file exists —
        unchanged behaviour from the original get_tesseract_status()."""
        cmd = self._pytesseract.pytesseract.tesseract_cmd
        try:
            version = str(self._pytesseract.get_tesseract_version())
            return {"available": True, "provider": "tesseract", "path": cmd, "version": version}
        except Exception as e:  # noqa: BLE001 — genuinely means "not usable"; report why, don't hide it
            return {
                "available": False,
                "provider": "tesseract",
                "path": cmd,
                "error": str(e),
                "hint": (
                    "Install Tesseract OCR (https://github.com/UB-Mannheim/tesseract/wiki on "
                    f"Windows), or set the {TESSERACT_CMD_ENV_VAR} environment variable to its "
                    "full path if it's installed somewhere this couldn't find automatically."
                ),
            }


# ---------------------------------------------------------------------------
# Google Cloud Vision — the cloud provider used on Vercel, where no system
# OCR binary can be installed
# ---------------------------------------------------------------------------


class GoogleVisionOCRProvider(OCRProvider):
    """Talks to the Google Cloud Vision API's `images:annotate` endpoint
    with the DOCUMENT_TEXT_DETECTION feature — chosen over plain
    TEXT_DETECTION because it's the one that returns real per-word
    confidence scores (needed for evaluate_orientations' scoring), not just
    bounding boxes. Unlike Azure's Read API this is a single synchronous
    HTTP call — no submit-then-poll — so it is materially faster in
    practice, but it is still a real, billed, network call: unlike
    Tesseract there is no free/offline path. ocr_runner.py's pipeline calls
    into this up to ~7 times per passport page (4 orientation candidates +
    2 MRZ-band crops + 1 whole-page pass) — see VERCEL_DEPLOYMENT.md for the
    honest cost tradeoff this implies, and for how staff can skip the 4-way
    orientation guess entirely by picking rotation manually (the existing
    `forced_rotation` parameter `/api/passport/process` already accepts)."""

    name = "google"
    ANNOTATE_URL = "https://vision.googleapis.com/v1/images:annotate"
    REQUEST_TIMEOUT_SECONDS = 20

    def __init__(self, api_key: str):
        self._api_key = api_key or ""

    def _annotate(self, gray_image) -> Dict[str, Any]:
        import cv2  # already a hard dependency of ocr_runner.py's own preprocessing

        ok, buf = cv2.imencode(".png", gray_image)
        if not ok:
            raise OCRProviderError("Could not encode image for Google Cloud Vision OCR.")
        image_b64 = base64.b64encode(buf.tobytes()).decode("ascii")

        payload = {
            "requests": [
                {
                    "image": {"content": image_b64},
                    "features": [{"type": "DOCUMENT_TEXT_DETECTION"}],
                }
            ]
        }
        try:
            resp = requests.post(
                self.ANNOTATE_URL,
                params={"key": self._api_key},
                json=payload,
                timeout=self.REQUEST_TIMEOUT_SECONDS,
            )
        except requests.RequestException as e:
            raise OCRProviderError(f"Could not reach Google Cloud Vision: {e}")
        if resp.status_code != 200:
            raise OCRProviderError(f"Google Cloud Vision request failed ({resp.status_code}): {resp.text[:300]}")

        body = resp.json()
        single = (body.get("responses") or [{}])[0]
        if "error" in single:
            raise OCRProviderError(f"Google Cloud Vision reported an error: {single['error']}")
        return single.get("fullTextAnnotation", {}) or {}

    @staticmethod
    def _words(full_text_annotation: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Walks pages -> blocks -> paragraphs -> words and reconstructs
        each word's text from its symbols (Google's response gives text per
        symbol/character, not per word, unlike Azure/Tesseract) alongside
        that word's own confidence score."""
        words: List[Dict[str, Any]] = []
        for page in full_text_annotation.get("pages", []):
            for block in page.get("blocks", []):
                for paragraph in block.get("paragraphs", []):
                    for word in paragraph.get("words", []):
                        text = "".join(s.get("text", "") for s in word.get("symbols", []))
                        words.append({"text": text, "confidence": word.get("confidence", 0.0)})
        return words

    def ocr_text(self, gray_image, config: str = "") -> str:
        # `config` carries Tesseract-specific flags (PSM mode, character
        # whitelist) that have no Google Cloud Vision equivalent —
        # deliberately ignored here rather than pretending to support them
        # (project rule 9). The caller's own MRZ_CHARSET_RE cleanup in
        # ocr_runner.py already strips anything outside A-Z0-9< regardless
        # of which engine produced the raw text, so MRZ reads still work,
        # just without the extra whitelist-accuracy hint Tesseract gets.
        full_text_annotation = self._annotate(gray_image)
        text = full_text_annotation.get("text")
        if text:
            return text
        return " ".join(w["text"] for w in self._words(full_text_annotation))

    def ocr_mean_confidence_and_text(self, gray_image) -> Tuple[float, str]:
        full_text_annotation = self._annotate(gray_image)
        words = self._words(full_text_annotation)
        text = " ".join(w["text"] for w in words) or full_text_annotation.get("text", "")
        confidences = [float(w.get("confidence", 0.0)) * 100 for w in words]
        mean_conf = statistics.mean(confidences) if confidences else 0.0
        return mean_conf, text

    def status(self) -> Dict[str, Any]:
        if not self._api_key:
            return {
                "available": False,
                "provider": "google",
                "error": "GOOGLE_VISION_API_KEY is not set.",
            }
        return {
            "available": True,
            "provider": "google",
            # Honest disclosure (project rule 9): this only confirms a key
            # is present, not that a live call has succeeded — a real
            # connectivity check would consume paid Google Cloud quota on
            # every single health check, so it is left to the first actual
            # passport upload to prove connectivity.
            "note": "Reflects configuration presence, not a live connectivity test.",
        }


# ---------------------------------------------------------------------------
# Provider selection
# ---------------------------------------------------------------------------

_provider_singleton: Optional[OCRProvider] = None


def get_ocr_provider() -> OCRProvider:
    """Selects and caches the active OCR provider for this process.

    OCR_PROVIDER env var:
      - "tesseract" -> always local Tesseract (raises if not installed when used)
      - "google"    -> always Google Cloud Vision (raises if the key is missing)
      - "auto" (default) -> Google Cloud Vision when GOOGLE_VISION_API_KEY is
                             set, otherwise Tesseract — so a staff member's
                             existing local machine (no Google Cloud key
                             set) keeps working exactly as before this
                             refactor, with zero configuration changes.
    """
    global _provider_singleton
    if _provider_singleton is not None:
        return _provider_singleton

    choice = os.environ.get("OCR_PROVIDER", "auto").strip().lower()
    google_api_key = os.environ.get("GOOGLE_VISION_API_KEY", "").strip()

    use_google = choice == "google" or (choice == "auto" and bool(google_api_key))

    if use_google:
        if not google_api_key:
            raise OCRProviderError("OCR_PROVIDER=google but GOOGLE_VISION_API_KEY is not set.")
        _provider_singleton = GoogleVisionOCRProvider(google_api_key)
    else:
        _provider_singleton = TesseractOCRProvider()

    return _provider_singleton


def reset_provider_cache_for_tests() -> None:
    """Test-only hook: forces get_ocr_provider() to re-resolve on its next
    call, so a test can change OCR_PROVIDER/env vars and see the effect
    without the singleton hiding it."""
    global _provider_singleton
    _provider_singleton = None
