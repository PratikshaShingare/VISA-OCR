"""azapi is the ONLY passport reader while a token is configured: Tesseract /
Google Vision are not used for passports at all (works on Vercel, where neither
exists). AZAPI_ENABLED=off brings the local pipeline back. No real azapi call
is made — requests.post is replaced by a fake. All data is synthetic."""

import pytest
import requests
from PIL import Image

import ocr_azapi as az
import ocr_providers
import ocr_runner
from tests.test_ocr_azapi import SYNTHETIC_OUTPUT


class FakeResp:
    status_code = 200

    def __init__(self, output):
        self._output = output

    def json(self):
        return {"status": "success", "output": self._output}


@pytest.fixture
def setup(monkeypatch, tmp_path):
    az.reset_for_tests()
    monkeypatch.setenv(az.ENV_KEY, "prod-test-token-123")
    monkeypatch.delenv(az.ENV_ENABLED, raising=False)
    calls = []

    def fake_post(url, **kw):
        calls.append(sorted(kw["files"]))
        return FakeResp(SYNTHETIC_OUTPUT)

    monkeypatch.setattr(requests, "post", fake_post)

    def local_must_not_run(*a, **k):
        raise AssertionError("the local OCR pipeline must not run while azapi is configured")

    monkeypatch.setattr(ocr_runner, "process_passport_page", local_must_not_run)
    path = tmp_path / "p.png"
    Image.new("RGB", (200, 140), (240, 240, 240)).save(path)
    yield str(path), calls
    az.reset_for_tests()


def test_azapi_reads_the_passport_when_no_local_engine(setup):
    path, calls = setup
    r = ocr_runner.process_passport_file(path)
    assert calls == [["front"]]
    assert r["pageKind"] == "bio" and r["ocrProvider"] == "azapi" and r["azapi"]["standalone"] is True
    assert r["fields"]["passportNumber"]["value"] == "P9988776"
    assert r["mrz"] is None
    assert r["processedImageBase64"]
    assert r["verificationStatus"] == "OCR Extracted — Please Verify"
    text = " ".join(r["warnings"] + r["notices"])
    assert "not read" in text and "cross-check" in text


def test_later_pages_cost_nothing(setup, tmp_path):
    path, calls = setup
    pdf_like = [Image.new("RGB", (80, 60), (250, 250, 250)) for _ in range(3)]
    r = ocr_runner._azapi_only_page(pdf_like, 1, None)
    assert r["pageKind"] == "other" and calls == []


def test_first_page_sends_the_next_page_as_back(setup):
    path, calls = setup
    imgs = [Image.new("RGB", (80, 60), (250, 250, 250)) for _ in range(2)]
    r = ocr_runner._azapi_only_page(imgs, 0, None)
    assert calls == [["back", "front"]] and r["azapi"]["backPageIndex"] == 1


def test_manual_rotation_is_applied(setup):
    import base64, io

    _, _ = setup
    img = Image.new("RGB", (200, 100), (250, 250, 250))
    r = ocr_runner._azapi_only_page([img], 0, 90)
    out = Image.open(io.BytesIO(base64.b64decode(r["processedImageBase64"])))
    assert out.size == (100, 200) and r["orientationApplied"] == 90


def test_local_pipeline_returns_when_azapi_is_switched_off(setup, monkeypatch):
    path, calls = setup
    monkeypatch.setenv(az.ENV_ENABLED, "off")
    with pytest.raises(AssertionError):  # i.e. the local pipeline was called
        ocr_runner.process_passport_file(path)
    assert calls == []


def test_azapi_failure_is_reported_not_hidden(setup, monkeypatch):
    path, _ = setup

    def boom(*a, **k):
        raise requests.ConnectionError("x")

    monkeypatch.setattr(requests, "post", boom)
    with pytest.raises(az.AzapiError) as e:
        ocr_runner.process_passport_file(path)
    assert e.value.kind == "network"


def test_endpoint_reports_azapi_failure_as_503(setup, monkeypatch):
    from fastapi.testclient import TestClient

    import app as app_module

    path, _ = setup

    def boom(*a, **k):
        raise requests.ConnectionError("x")

    monkeypatch.setattr(requests, "post", boom)
    with open(path, "rb") as f:
        resp = TestClient(app_module.app).post("/api/passport/process", files={"file": ("p.png", f, "image/png")})
    assert resp.status_code == 503 and "azapi" in resp.json()["detail"]


def test_endpoint_returns_azapi_result_instead_of_503(setup):
    from fastapi.testclient import TestClient

    import app as app_module

    path, calls = setup
    with open(path, "rb") as f:
        resp = TestClient(app_module.app).post("/api/passport/process", files={"file": ("p.png", f, "image/png")})
    assert resp.status_code == 200
    assert resp.json()["ocrProvider"] == "azapi" and len(calls) == 1
