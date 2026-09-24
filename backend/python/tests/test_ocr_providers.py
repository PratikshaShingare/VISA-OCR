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
