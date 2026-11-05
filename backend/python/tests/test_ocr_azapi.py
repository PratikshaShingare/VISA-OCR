"""
Tests for ocr_azapi.py — the azapi.ai Passport OCR layer.

No test here makes a real network call: azapi charges credits per call, and
this suite must be free to run. Every call goes through a fake `post`
function that returns canned responses shaped like azapi's documented JSON.
All people, passport numbers and addresses are obviously synthetic (project
rule 11) — never a real client's data.
"""

import base64
import io

import pytest
import requests
from PIL import Image

import ocr_azapi as az
import ocr_runner
from tests.test_ocr_runner import _build_valid_td3

# ---------------------------------------------------------------------------
# Synthetic fixtures
# ---------------------------------------------------------------------------

SYNTHETIC_OUTPUT = {
    "id_type": "Passport",
    "id_number": "P9988776",
    "id_gender": "F",
    "id_name": "ANITA SHARMA",
    "id_dob": "12/05/1990",
    "id_address": "FLAT 12,SAMPLE APARTMENTS,TEST ROAD\nEXAMPLE NAGAR,SAMPLEPUR\nPIN: 411001,SAMPLESTATE,INDIA.",
    "id_caretaker_name": "RAJ SHARMA",
    "id_country_code": "IND",
    "id_nationality": "INDIAN",
    "id_place_of_birth": "SAMPLEPUR,SAMPLESTATE",
    "id_place_of_issue": "SAMPLEPUR",
    "id_doi": "01/01/2022",
    "id_doe": "31/12/2031",
    "id_passport_type": "P",
    "id_file_num": "XX0000000000000",
    "id_old_doi": "24/04/2012",
    "id_old_passport_num": "K1234567",
    "id_old_place_of_issue": "TESTVILLE",
    "id_father_name": "RAJ SHARMA",
    "id_mother_name": "MEERA SHARMA",
    "id_spouse_name": "",
}


def synthetic_mrz():
    return ocr_runner.parse_mrz_td3(*_build_valid_td3(expiry="311231"))


def success_body(**overrides):
    out = dict(SYNTHETIC_OUTPUT)
    out.update(overrides)
    return {"status": "Success", "country": "India", "billable": "Yes", "message": "Details extraction completed successfully.", "output": out}


class FakeResp:
    def __init__(self, status_code=200, body=None, text_only=False):
        self.status_code = status_code
        self._body = body
        self._text_only = text_only

    def json(self):
        if self._text_only:
            raise ValueError("not json")
        return self._body


class FakePost:
    """Records every call; returns the queued response (or raises it)."""

    def __init__(self, *responses):
        self.responses = list(responses) or [FakeResp(200, success_body())]
        self.calls = []

    def __call__(self, url, headers=None, files=None, timeout=None):
        self.calls.append({"url": url, "headers": headers, "files": files, "timeout": timeout})
        r = self.responses[0] if len(self.responses) == 1 else self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def tiny_png_base64():
    buf = io.BytesIO()
    Image.new("RGB", (60, 40), (240, 240, 240)).save(buf, "PNG")
    return base64.b64encode(buf.getvalue()).decode()


def bio_result(mrz=True):
    m = synthetic_mrz() if mrz else None
    import ocr_runner as r

    fields = r.extract_passport_fields("", m) if m else r.extract_passport_fields("", None)
    return {
        "pageKind": "bio", "mrz": m, "fields": fields, "warnings": [], "notices": [],
        "processedImageBase64": tiny_png_base64(), "verificationStatus": "OCR Extracted — Please Verify",
    }


def pages(n):
    return [Image.new("RGB", (80, 60), (250, 250, 250)) for _ in range(n)]


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    az.reset_for_tests()
    monkeypatch.delenv(az.ENV_ENABLED, raising=False)
    monkeypatch.delenv(az.ENV_URL, raising=False)
    monkeypatch.setenv(az.ENV_KEY, "prod-test-token-123")
    yield
    az.reset_for_tests()


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def test_address_is_split_into_the_six_form_fields():
    a = az.parse_address(SYNTHETIC_OUTPUT["id_address"])
    assert a == {
        "line1": "FLAT 12, SAMPLE APARTMENTS, TEST ROAD",
        "line2": "EXAMPLE NAGAR",
        "city": "SAMPLEPUR",
        "state": "SAMPLESTATE",
        "pincode": "411001",
        "country": "INDIA",
    }


def test_address_shape_from_the_real_sample_layout():
    raw = "F2,101,KASTURI CHS,PLOT-1,MORAJ RESIDENCY,SEC16\nPALM BEACH ROAD,SANPADA,NAVI MUMBAI\nPIN: 400705,MAHARASHTRA,INDIA."
    a = az.parse_address(raw)
    assert a["line1"] == "F2, 101, KASTURI CHS, PLOT-1, MORAJ RESIDENCY, SEC16"
    assert a["line2"] == "PALM BEACH ROAD, SANPADA"
    assert (a["city"], a["state"], a["pincode"], a["country"]) == ("NAVI MUMBAI", "MAHARASHTRA", "400705", "INDIA")


@pytest.mark.parametrize("raw", [None, "", "  \n ", "---"])
def test_empty_address_gives_all_none(raw):
    assert set(az.parse_address(raw).values()) == {None}


def test_address_without_pin_keeps_text_and_no_pincode():
    a = az.parse_address("1 TEST STREET,SAMPLEPUR")
    assert a["pincode"] is None and a["line1"] == "1 TEST STREET" and a["city"] == "SAMPLEPUR"


def test_dates_are_iso_and_bad_dates_are_reported_not_dropped_silently():
    assert az.parse_date("20/10/2021") == "2021-10-20"
    assert az.parse_date("2021-10-20") == "2021-10-20"
    assert az.parse_date("31/02/2021") is None
    n = az.normalize(dict(SYNTHETIC_OUTPUT, id_dob="31/02/1990"))
    assert n["dob"] is None and n["badDates"] == ["Date of birth"]


def test_normalize_uppercases_and_blank_spouse_is_none():
    n = az.normalize(dict(SYNTHETIC_OUTPUT, id_name=" anita   sharma "))
    assert n["name"] == "ANITA SHARMA" and n["spouse"] is None and n["issue"] == "2022-01-01"


# ---------------------------------------------------------------------------
# Cross-checking
# ---------------------------------------------------------------------------


def build(mrz=True, **overrides):
    result = bio_result(mrz)
    n = az.normalize(dict(SYNTHETIC_OUTPUT, **overrides))
    return az.build_fields(result["fields"], result["mrz"], n)


def test_everything_agreeing_is_confirmed_without_warnings():
    fields, warnings = build()
    assert warnings == []
    for key in ("passportNumber", "dateOfBirth", "dateOfExpiry", "surname", "givenNames", "sex"):
        assert fields[key]["source"] == az.SOURCE_CONFIRMED and fields[key]["needsReview"] is False, key
    assert fields["passportNumber"]["confidence"] == 0.99
    assert (fields["givenNames"]["value"], fields["surname"]["value"]) == ("ANITA", "SHARMA")
    assert fields["dateOfIssue"]["value"] == "2022-01-01" and fields["dateOfIssue"]["needsReview"] is False


def test_printed_page_details_are_filled_and_not_flagged_when_nothing_is_wrong():
    fields, _ = build()
    assert fields["addressLine1"]["value"] == "FLAT 12, SAMPLE APARTMENTS, TEST ROAD"
    assert fields["addressPincode"]["value"] == "411001"
    assert fields["fatherName"]["value"] == "RAJ SHARMA" and fields["motherName"]["value"] == "MEERA SHARMA"
    assert fields["oldPassportNumber"]["value"] == "K1234567" and fields["oldPassportIssueDate"]["value"] == "2012-04-24"
    for key in ("addressLine1", "addressCity", "fatherName", "oldPassportNumber", "oldPassportPlace"):
        assert fields[key]["source"] == az.SOURCE_AZAPI and fields[key]["needsReview"] is False, key
    assert "spouseName" not in fields or not fields["spouseName"].get("value")


def test_passport_number_disagreeing_with_a_valid_mrz_keeps_the_mrz_value_and_warns():
    fields, warnings = build(id_number="P9988778")
    f = fields["passportNumber"]
    assert f["value"] == "P9988776" and f["needsReview"] is True and f["source"] == "mrz"
    assert "P9988778" in f["note"] and any(w.startswith("Passport number:") for w in warnings)


def test_disagreement_with_an_mrz_whose_check_digit_failed_uses_azapi_and_warns():
    result = bio_result()
    result["mrz"]["passportNumberValid"] = False
    n = az.normalize(dict(SYNTHETIC_OUTPUT, id_number="P9988778"))
    fields, warnings = az.build_fields(result["fields"], result["mrz"], n)
    assert fields["passportNumber"]["value"] == "P9988778" and fields["passportNumber"]["needsReview"] is True
    assert warnings


def test_name_disagreement_is_flagged_and_both_readings_are_named():
    fields, warnings = build(id_name="ANITA SHARNA")
    assert fields["surname"]["needsReview"] is True and fields["givenNames"]["needsReview"] is True
    assert "SHARNA" in fields["surname"]["note"] and "SHARMA" in fields["surname"]["note"]
    assert any(w.startswith("Name:") for w in warnings)


def test_without_an_mrz_values_are_azapi_only_and_only_the_guessed_name_split_is_flagged():
    fields, warnings = build(mrz=False)
    for key in ("passportNumber", "dateOfBirth", "dateOfExpiry", "sex"):
        assert fields[key]["needsReview"] is False and fields[key]["source"] == az.SOURCE_AZAPI, key
        assert "not cross-checked" in fields[key]["note"]
    assert (fields["givenNames"]["value"], fields["surname"]["value"]) == ("ANITA", "SHARMA")
    assert fields["surname"]["needsReview"] is True and "guess" in fields["surname"]["note"]
    assert fields["countryCode"]["value"] == "IND" and fields["passportType"]["value"] == "P"
    assert warnings == []


def test_single_word_name_goes_to_given_names_and_is_flagged():
    fields, _ = build(mrz=False, id_name="ANITA")
    assert fields["givenNames"]["value"] == "ANITA" and fields["surname"]["value"] is None
    assert fields["surname"]["needsReview"] is True


def test_unusual_passport_number_format_is_still_flagged():
    fields, warnings = build(mrz=False, id_number="12345")
    assert fields["passportNumber"]["needsReview"] is True
    assert any("format is unusual" in w for w in warnings)


def test_issue_date_after_expiry_is_flagged():
    fields, warnings = build(id_doi="01/01/2035")
    assert fields["dateOfIssue"]["needsReview"] is True and fields["dateOfIssue"]["confidence"] <= 0.3
    assert any(w.startswith("Date of issue:") for w in warnings)


def test_issue_date_before_birth_is_flagged():
    _, warnings = build(id_doi="01/01/1980")
    assert any("date of birth" in w for w in warnings)


def test_odd_validity_is_noted_but_not_flagged_or_warned():
    fields, warnings = build(id_doi="15/03/2024")
    assert fields["dateOfIssue"]["needsReview"] is False and warnings == []
    assert "usual 5 or 10 years" in fields["dateOfIssue"]["note"]


def test_an_invalid_date_from_azapi_is_warned_and_the_local_value_is_kept():
    result = bio_result()
    before = result["fields"]["dateOfBirth"]
    n = az.normalize(dict(SYNTHETIC_OUTPUT, id_dob="99/99/1990"))
    fields, warnings = az.build_fields(result["fields"], result["mrz"], n)
    assert fields["dateOfBirth"] == before
    assert any("not a valid date" in w for w in warnings)


def test_a_bad_pincode_is_not_filled_in():
    fields, _ = build(id_address="1 TEST ROAD\nSAMPLEPUR\nPIN: 12345,SAMPLESTATE,INDIA.")
    assert not fields["addressPincode"].get("value")


def test_front_only_response_leaves_local_back_fields_untouched():
    out = {k: v for k, v in SYNTHETIC_OUTPUT.items() if k not in (
        "id_address", "id_father_name", "id_mother_name", "id_old_doi", "id_old_passport_num", "id_old_place_of_issue")}
    result = bio_result()
    fields, _ = az.build_fields(result["fields"], result["mrz"], az.normalize(out))
    for key in ("addressLine1", "fatherName", "oldPassportNumber"):
        assert fields[key] == result["fields"][key]


# ---------------------------------------------------------------------------
# The HTTP call
# ---------------------------------------------------------------------------


def test_request_shape_matches_azapis_documented_call():
    post = FakePost()
    out = az.call_api(b"FRONT", b"BACK", post=post)
    call = post.calls[0]
    assert call["url"] == "https://ocr.azapi.ai/ind0005d"
    assert call["headers"] == {"Authorization": "prod-test-token-123"}  # no "Bearer"
    assert set(call["files"]) == {"front", "back"} and call["files"]["front"][1] == b"FRONT"
    assert out["id_number"] == "P9988776"


def test_front_only_sends_no_back_field():
    post = FakePost()
    az.call_api(b"FRONT", None, post=post)
    assert set(post.calls[0]["files"]) == {"front"}


def test_endpoint_can_be_overridden(monkeypatch):
    monkeypatch.setenv(az.ENV_URL, "https://example.invalid/sandbox")
    post = FakePost()
    az.call_api(b"F", None, post=post)
    assert post.calls[0]["url"] == "https://example.invalid/sandbox"


@pytest.mark.parametrize("response, kind", [
    (FakeResp(401, {"message": "Unauthorized"}), "auth"),
    (FakeResp(403, {}), "auth"),
    (FakeResp(402, {"message": "Payment required"}), "credits"),
    (FakeResp(200, {"status": "Failed", "message": "Insufficient credits"}), "credits"),
    (FakeResp(429, {}), "rate"),
    (FakeResp(400, {"message": "Invalid image"}), "bad-request"),
    (FakeResp(500, {}), "server"),
    (FakeResp(502, None, text_only=True), "server"),
    (FakeResp(200, None, text_only=True), "server"),
    (FakeResp(200, {"status": "Failed", "message": "Could not read document"}), "unreadable"),
    (FakeResp(200, {"status": "Success", "output": {}}), "unreadable"),
    (FakeResp(200, {"status": "Success", "output": {"id_number": "", "id_name": ""}}), "unreadable"),
    (requests.ConnectionError("down"), "network"),
    (requests.Timeout("slow"), "network"),
])
def test_failures_are_classified(response, kind):
    with pytest.raises(az.AzapiError) as exc:
        az.call_api(b"F", None, post=FakePost(response))
    assert exc.value.kind == kind


def test_missing_token_is_a_config_error(monkeypatch):
    monkeypatch.delenv(az.ENV_KEY)
    with pytest.raises(az.AzapiError) as exc:
        az.call_api(b"F", None, post=FakePost())
    assert exc.value.kind == "config"


def test_error_messages_never_contain_the_token_or_raw_reply():
    with pytest.raises(az.AzapiError) as exc:
        az.call_api(b"F", None, post=FakePost(FakeResp(400, {"message": "bad <script>alert(1)</script>"})))
    assert "prod-test-token-123" not in str(exc.value) and "<" not in str(exc.value)


# ---------------------------------------------------------------------------
# Enrichment (what ocr_runner calls)
# ---------------------------------------------------------------------------


def test_off_without_a_token(monkeypatch):
    monkeypatch.delenv(az.ENV_KEY)
    result, post = bio_result(), FakePost()
    before = dict(result["fields"])
    az.enrich_bio_result(result, pages(2), 0, post=post)
    assert post.calls == [] and result["fields"] == before and "azapi" not in result


def test_can_be_switched_off_even_with_a_token(monkeypatch):
    monkeypatch.setenv(az.ENV_ENABLED, "off")
    result, post = bio_result(), FakePost()
    az.enrich_bio_result(result, pages(2), 0, post=post)
    assert post.calls == [] and not az.is_enabled()


@pytest.mark.parametrize("kind", ["back", "other", "blank"])
def test_only_data_pages_cost_a_call(kind):
    result, post = bio_result(), FakePost()
    result["pageKind"] = kind
    az.enrich_bio_result(result, pages(2), 0, post=post)
    assert post.calls == []


def test_a_data_page_makes_exactly_one_call_with_the_following_page_as_back():
    result, post = bio_result(), FakePost()
    az.enrich_bio_result(result, pages(2), 0, post=post)
    assert len(post.calls) == 1 and set(post.calls[0]["files"]) == {"front", "back"}
    assert result["azapi"] == {"used": True, "fromCache": False, "backPageIndex": 1}
    assert result["ocrProvider"] == "azapi"
    assert result["verificationStatus"] == "OCR Extracted — Please Verify"
    assert result["fields"]["addressPincode"]["value"] == "411001"


def test_single_page_upload_is_front_only():
    result, post = bio_result(), FakePost()
    az.enrich_bio_result(result, pages(1), 0, post=post)
    assert set(post.calls[0]["files"]) == {"front"} and result["azapi"]["backPageIndex"] is None


def test_page_beyond_the_auto_read_limit_is_not_sent():
    result, post = bio_result(), FakePost()
    az.enrich_bio_result(result, pages(6), 3, post=post)
    assert set(post.calls[0]["files"]) == {"front"}


def test_reading_the_same_image_again_does_not_spend_credits():
    post = FakePost()
    first, second = bio_result(), bio_result()
    az.enrich_bio_result(first, pages(2), 0, post=post)
    az.enrich_bio_result(second, pages(2), 0, post=post)
    assert len(post.calls) == 1
    assert second["azapi"]["fromCache"] is True
    status = az.get_status()
    assert status["callsSinceStart"] == 1 and status["cacheHitsSinceStart"] == 1


@pytest.mark.parametrize("response, kind", [
    (FakeResp(402, {"message": "no credits"}), "credits"),
    (FakeResp(401, {}), "auth"),
    (requests.Timeout("slow"), "network"),
    (FakeResp(200, {"status": "Failed", "message": "x"}), "unreadable"),
])
def test_azapi_failing_leaves_the_local_result_intact(response, kind):
    result = bio_result()
    before_fields = {k: dict(v) for k, v in result["fields"].items()}
    az.enrich_bio_result(result, pages(2), 0, post=FakePost(response))
    assert result["fields"] == before_fields
    assert result["azapi"] == {"used": False, "reason": kind}
    assert any("azapi OCR was not used" in n for n in result["notices"])
    assert az.get_status()["lastError"]["kind"] == kind


def test_a_failed_call_is_not_cached():
    post = FakePost(FakeResp(500, {}), FakeResp(200, success_body()))
    r1, r2 = bio_result(), bio_result()
    az.enrich_bio_result(r1, pages(1), 0, post=post)
    az.enrich_bio_result(r2, pages(1), 0, post=post)
    assert r1["azapi"]["used"] is False and r2["azapi"]["used"] is True
    assert az.get_status()["lastError"] is None


def test_salutation_follows_the_azapi_values():
    result = bio_result()
    az.enrich_bio_result(result, pages(1), 0, post=FakePost(FakeResp(200, success_body(id_spouse_name="RAVI SHARMA"))))
    assert result["fields"]["salutation"]["value"] == "Mrs"


def test_unexpected_internal_errors_never_break_the_upload():
    result = bio_result()
    result["processedImageBase64"] = "not-base64!!"
    az.enrich_bio_result(result, pages(1), 0, post=FakePost())
    assert result["azapi"] == {"used": False, "reason": "unexpected"}


def test_status_and_notices_never_expose_the_token():
    result = bio_result()
    az.enrich_bio_result(result, pages(1), 0, post=FakePost(FakeResp(401, {})))
    blob = repr(az.get_status()) + repr(result)
    assert "prod-test-token-123" not in blob


def test_health_endpoint_reports_azapi_without_the_token():
    from fastapi.testclient import TestClient

    import app as app_module

    body = TestClient(app_module.app).get("/api/health").json()
    assert body["azapi"]["configured"] is True and body["azapi"]["enabled"] is True
    assert "prod-test-token-123" not in repr(body)


# ---------------------------------------------------------------------------
# Whole pipeline: real local OCR on a synthetic 2-page passport, azapi faked
# ---------------------------------------------------------------------------


def _synthetic_two_page_pdf(tmp_path, with_back=True):
    from tests.test_passport_layout import _synthetic_address_page, synthetic_bio_page

    bio, _ = synthetic_bio_page(surname="SHARMA", given="ANITA")
    path = tmp_path / "synthetic_passport.pdf"
    if with_back:
        bio.save(path, "PDF", save_all=True, append_images=[_synthetic_address_page()], resolution=150)
    else:
        bio.save(path, "PDF", resolution=150)
    return str(path)


def test_whole_pipeline_makes_one_azapi_call_for_the_data_page_and_none_for_the_address_page(tmp_path, monkeypatch):
    path = _synthetic_two_page_pdf(tmp_path)
    post = FakePost(FakeResp(200, success_body(id_number="P9988776")))
    monkeypatch.setattr(az.requests, "post", post)

    bio = ocr_runner.process_passport_file(path, page_index=0)
    assert bio["pageKind"] == "bio" and bio["azapi"]["used"] is True
    assert bio["mrz"]["valid"] is True
    assert bio["fields"]["passportNumber"]["source"] == az.SOURCE_CONFIRMED
    assert bio["fields"]["addressPincode"]["value"] == "411001"  # azapi's address, not the local reader's
    assert set(post.calls[0]["files"]) == {"front", "back"}

    back = ocr_runner.process_passport_file(path, page_index=1)
    assert back["pageKind"] == "back" and "azapi" not in back
    assert len(post.calls) == 1  # the whole passport cost one call


def test_whole_pipeline_survives_azapi_being_down(tmp_path, monkeypatch):
    path = _synthetic_two_page_pdf(tmp_path, with_back=False)
    monkeypatch.setattr(az.requests, "post", FakePost(requests.ConnectionError("down")))
    result = ocr_runner.process_passport_file(path, page_index=0)
    assert result["pageKind"] == "bio" and result["fields"]["passportNumber"]["value"] == "P9988776"
    assert result["azapi"] == {"used": False, "reason": "network"}


def test_api_route_returns_the_azapi_result(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    import app as app_module

    path = _synthetic_two_page_pdf(tmp_path, with_back=False)
    monkeypatch.setattr(az.requests, "post", FakePost())
    with open(path, "rb") as fh:
        resp = TestClient(app_module.app).post(
            "/api/passport/process", files={"file": ("p.pdf", fh, "application/pdf")}, data={"page_index": "0"}
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ocrProvider"] == "azapi" and body["verificationStatus"] == "OCR Extracted — Please Verify"
    assert "prod-test-token-123" not in resp.text
