"""
Unit tests for pdf_conversion.py — the docx->PDF provider selection/
dispatch logic introduced for the Vercel-serverless architecture
(CloudConvert replaces local LibreOffice/'soffice' there, since no system
binary can be installed in a serverless function).

The real end-to-end "does this actually produce a PDF" test already exists
in test_docx_utils.py (test_convert_docx_bytes_to_pdf_produces_a_real_pdf)
and continues to pass unchanged against the local LibreOffice path — this
file only covers the new SELECTION logic and honest failure messages, and
never makes a real network call to CloudConvert (no live API key exists in
this environment, and a unit test must not depend on, or spend, a real
paid quota).
"""

import pytest

import pdf_conversion


def test_auto_uses_local_when_no_cloudconvert_key_is_set(monkeypatch):
    monkeypatch.delenv("PDF_CONVERSION_PROVIDER", raising=False)
    monkeypatch.delenv("CLOUDCONVERT_API_KEY", raising=False)
    calls = []
    monkeypatch.setattr(pdf_conversion, "convert_via_local_libreoffice", lambda b, base_name: calls.append("local") or b"LOCAL")
    monkeypatch.setattr(pdf_conversion, "convert_via_cloudconvert", lambda b, base_name: calls.append("cloud") or b"CLOUD")

    result = pdf_conversion.convert_docx_bytes_to_pdf(b"fake docx bytes", base_name="test")
    assert result == b"LOCAL"
    assert calls == ["local"]


def test_auto_uses_cloudconvert_once_an_api_key_is_present(monkeypatch):
    monkeypatch.delenv("PDF_CONVERSION_PROVIDER", raising=False)
    monkeypatch.setenv("CLOUDCONVERT_API_KEY", "fake-test-key")
    calls = []
    monkeypatch.setattr(pdf_conversion, "convert_via_local_libreoffice", lambda b, base_name: calls.append("local") or b"LOCAL")
    monkeypatch.setattr(pdf_conversion, "convert_via_cloudconvert", lambda b, base_name: calls.append("cloud") or b"CLOUD")

    result = pdf_conversion.convert_docx_bytes_to_pdf(b"fake docx bytes", base_name="test")
    assert result == b"CLOUD"
    assert calls == ["cloud"]


def test_explicit_local_choice_is_honored_even_with_a_cloudconvert_key_set(monkeypatch):
    monkeypatch.setenv("PDF_CONVERSION_PROVIDER", "local")
    monkeypatch.setenv("CLOUDCONVERT_API_KEY", "fake-test-key")
    calls = []
    monkeypatch.setattr(pdf_conversion, "convert_via_local_libreoffice", lambda b, base_name: calls.append("local") or b"LOCAL")
    monkeypatch.setattr(pdf_conversion, "convert_via_cloudconvert", lambda b, base_name: calls.append("cloud") or b"CLOUD")

    result = pdf_conversion.convert_docx_bytes_to_pdf(b"fake docx bytes", base_name="test")
    assert result == b"LOCAL"
    assert calls == ["local"]


def test_cloudconvert_without_an_api_key_raises_a_clear_actionable_error(monkeypatch):
    monkeypatch.delenv("CLOUDCONVERT_API_KEY", raising=False)
    with pytest.raises(pdf_conversion.PdfConversionError, match="CLOUDCONVERT_API_KEY"):
        pdf_conversion.convert_via_cloudconvert(b"fake docx bytes", base_name="test")


def test_docx_utils_wrapper_converts_a_cloudconvert_failure_into_docxbuilderror(monkeypatch):
    import docx_utils

    def _boom(docx_bytes, base_name="document"):
        raise pdf_conversion.PdfConversionError("simulated failure")

    monkeypatch.setattr(pdf_conversion, "convert_docx_bytes_to_pdf", _boom)
    with pytest.raises(docx_utils.DocxBuildError, match="simulated failure"):
        docx_utils.convert_docx_bytes_to_pdf(b"fake docx bytes", base_name="test")
