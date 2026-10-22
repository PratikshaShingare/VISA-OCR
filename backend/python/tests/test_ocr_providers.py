"""
Unit tests for ocr_providers.py — the OCR-engine selection/dispatch logic
introduced for the Vercel-serverless architecture (Google Cloud Vision
replaces local Tesseract there, since no system binary can be installed in
a serverless function).

These tests exercise only the SELECTION logic (which provider class gets
built for a given environment) and each provider's honest status()
reporting — never a real network call to Google Cloud Vision (no live
credentials exist in this environment, and a unit test must not depend on,
or spend, a real cloud quota). ocr_runner.py's own pipeline behaviour
against a real image is already covered by the existing OCR tests, which
run against the Tesseract provider (the only one actually installed here)
unchanged.
"""

import pytest

import ocr_providers


@pytest.fixture(autouse=True)
def _reset_provider_singleton():
    """Every test gets a clean slate: get_ocr_provider() caches its result
    process-wide, which would otherwise leak whichever provider an earlier
    test selected into a later test's different env vars."""
    ocr_providers.reset_provider_cache_for_tests()
    yield
    ocr_providers.reset_provider_cache_for_tests()


def test_defaults_to_tesseract_when_no_google_credentials_are_set(monkeypatch):
    monkeypatch.delenv("OCR_PROVIDER", raising=False)
    monkeypatch.delenv("GOOGLE_VISION_API_KEY", raising=False)

    provider = ocr_providers.get_ocr_provider()
    assert provider.name == "tesseract"


def test_auto_selects_google_once_an_api_key_is_present(monkeypatch):
    monkeypatch.delenv("OCR_PROVIDER", raising=False)
    monkeypatch.setenv("GOOGLE_VISION_API_KEY", "fake-test-key")

    provider = ocr_providers.get_ocr_provider()
    assert provider.name == "google"
    assert isinstance(provider, ocr_providers.FallbackOCRProvider)


def test_explicit_google_choice_without_a_key_raises_a_clear_error(monkeypatch):
    monkeypatch.setenv("OCR_PROVIDER", "google")
    monkeypatch.delenv("GOOGLE_VISION_API_KEY", raising=False)

    with pytest.raises(ocr_providers.OCRProviderError):
        ocr_providers.get_ocr_provider()


def test_explicit_tesseract_choice_is_honored_even_if_a_google_key_is_also_set(monkeypatch):
    monkeypatch.setenv("OCR_PROVIDER", "tesseract")
    monkeypatch.setenv("GOOGLE_VISION_API_KEY", "fake-test-key")

    provider = ocr_providers.get_ocr_provider()
    assert provider.name == "tesseract"


def test_google_provider_status_without_a_key_is_honestly_unavailable():
    provider = ocr_providers.GoogleVisionOCRProvider("")
    status = provider.status()
    assert status["available"] is False
    assert status["provider"] == "google"


def test_google_provider_status_with_a_key_never_claims_a_live_check_happened():
    provider = ocr_providers.GoogleVisionOCRProvider("fake-test-key")
    status = provider.status()
    assert status["available"] is True
    assert status["provider"] == "google"
    # Honesty check (project rule 9): this must not claim to have verified
    # live connectivity — only that a key is present.
    assert "note" in status


def test_word_reconstruction_joins_symbols_and_keeps_confidence():
    provider = ocr_providers.GoogleVisionOCRProvider("fake-test-key")
    full_text_annotation = {
        "text": "AB CD",
        "pages": [
            {
                "blocks": [
                    {
                        "paragraphs": [
                            {
                                "words": [
                                    {
                                        "symbols": [{"text": "A"}, {"text": "B"}],
                                        "confidence": 0.9,
                                    },
                                    {
                                        "symbols": [{"text": "C"}, {"text": "D"}],
                                        "confidence": 0.7,
                                    },
                                ]
                            }
                        ]
                    }
                ]
            }
        ],
    }
    words = provider._words(full_text_annotation)
    assert [w["text"] for w in words] == ["AB", "CD"]
    confidences = [w["confidence"] * 100 for w in words]
    assert confidences == [90.0, 70.0]


def test_ocr_mean_confidence_and_text_uses_the_reconstructed_words(monkeypatch):
    provider = ocr_providers.GoogleVisionOCRProvider("fake-test-key")
    full_text_annotation = {
        "pages": [
            {
                "blocks": [
                    {
                        "paragraphs": [
                            {
                                "words": [
                                    {"symbols": [{"text": "H"}, {"text": "I"}], "confidence": 0.8},
                                ]
                            }
                        ]
                    }
                ]
            }
        ]
    }
    monkeypatch.setattr(provider, "_annotate", lambda gray_image: full_text_annotation)

    mean_conf, text = provider.ocr_mean_confidence_and_text(None)
    assert text == "HI"
    assert mean_conf == 80.0


class _FakeResponse:
    def __init__(self, status, body):
        self.status_code = status
        self._body = body
        self.text = str(body)

    def json(self):
        return self._body


_INVALID_KEY_BODY = {
    "error": {"code": 400, "message": "API key not valid. Please pass a valid API key.", "status": "INVALID_ARGUMENT",
              "details": [{"reason": "API_KEY_INVALID"}]}
}


def test_invalid_google_key_raises_an_auth_error_with_a_short_message(monkeypatch):
    import numpy as np

    monkeypatch.setattr(ocr_providers.requests, "post", lambda *a, **k: _FakeResponse(400, _INVALID_KEY_BODY))
    provider = ocr_providers.GoogleVisionOCRProvider("bad-key")
    with pytest.raises(ocr_providers.OCRProviderAuthError) as exc:
        provider.ocr_text(np.zeros((10, 10), dtype="uint8"))
    assert "API key not valid" in str(exc.value)
    assert "details" not in str(exc.value)


def test_other_google_400_errors_are_not_treated_as_a_bad_key(monkeypatch):
    import numpy as np

    body = {"error": {"code": 400, "message": "Bad image data.", "status": "INVALID_ARGUMENT"}}
    monkeypatch.setattr(ocr_providers.requests, "post", lambda *a, **k: _FakeResponse(400, body))
    provider = ocr_providers.GoogleVisionOCRProvider("good-key")
    with pytest.raises(ocr_providers.OCRProviderError) as exc:
        provider.ocr_text(np.zeros((10, 10), dtype="uint8"))
    assert not isinstance(exc.value, ocr_providers.OCRProviderAuthError)


class _StubProvider(ocr_providers.OCRProvider):
    def __init__(self, name, text="", error=None):
        self.name = name
        self._text = text
        self._error = error
        self.calls = 0

    def ocr_text(self, gray_image, config=""):
        self.calls += 1
        if self._error:
            raise self._error
        return self._text

    def ocr_mean_confidence_and_text(self, gray_image, config=""):
        return 77.0, self.ocr_text(gray_image, config)

    def status(self):
        return {"available": True, "provider": self.name}


def test_fallback_switches_to_tesseract_after_an_auth_failure_and_stays_there():
    primary = _StubProvider("google", error=ocr_providers.OCRProviderAuthError("API key not valid"))
    secondary = _StubProvider("tesseract", text="local text")
    fb = ocr_providers.FallbackOCRProvider(primary, lambda: secondary)

    assert fb.name == "google"
    assert fb.ocr_text(None) == "local text"
    assert fb.name == "tesseract"
    assert fb.ocr_text(None) == "local text"
    assert primary.calls == 1  # Google is not retried on every call
    st = fb.status()
    assert st["provider"] == "tesseract"
    assert "API key not valid" in st["warning"]


def test_fallback_does_not_hide_transient_google_errors():
    primary = _StubProvider("google", error=ocr_providers.OCRProviderError("Could not reach Google Cloud Vision"))
    fb = ocr_providers.FallbackOCRProvider(primary, lambda: _StubProvider("tesseract", text="x"))
    with pytest.raises(ocr_providers.OCRProviderError):
        fb.ocr_text(None)
    assert fb.fallback_reason is None


def test_fallback_reports_clearly_when_tesseract_is_missing_too():
    primary = _StubProvider("google", error=ocr_providers.OCRProviderAuthError("API key not valid"))

    def boom():
        raise RuntimeError("tesseract is not installed")

    fb = ocr_providers.FallbackOCRProvider(primary, boom)
    with pytest.raises(ocr_providers.OCRProviderError) as exc:
        fb.ocr_text(None)
    assert "GOOGLE_VISION_API_KEY" in str(exc.value) and "Tesseract" in str(exc.value)
