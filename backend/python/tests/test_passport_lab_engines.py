"""Tests for passport_lab/engines.py — comparison + scoring logic (synthetic data only)."""

import cv2
import numpy as np

import passport_lab.engines as E


def _res(engine, fields, ok=True):
    return {"engine": engine, "label": E.ENGINE_LABELS[engine], "ok": ok, "error": "", "seconds": 0, "fields": fields, "mrz": None, "warnings": [], "cloud": False}


def test_compare_marks_agreement_disagreement_single_and_empty():
    a = _res("current", {"surname": "KUMAR", "passportNumber": "21234567", "placeOfBirth": "Pune"})
    b = _res("mrz_v2", {"surname": "kumar", "passportNumber": "Z1234567"})
    rows = {r["field"]: r["status"] for r in E.compare_engines([a, b])}
    assert rows["surname"] == "agree"            # case-insensitive
    assert rows["passportNumber"] == "disagree"
    assert rows["placeOfBirth"] == "single"
    assert rows["issuingAuthority"] == "empty"


def test_failed_engine_is_ignored_in_comparison():
    a = _res("current", {"surname": "KUMAR"})
    b = _res("google", {}, ok=False)
    rows = {r["field"]: r["status"] for r in E.compare_engines([a, b])}
    assert rows["surname"] == "single"


def test_normalise_dates_sex_and_punctuation():
    assert E.normalise("dateOfBirth", "21/03/1978") == "1978-03-21"
    assert E.normalise("dateOfBirth", "1978-03-21") == "1978-03-21"
    assert E.normalise("sex", "Female") == "F"
    assert E.normalise("placeOfBirth", "New  Delhi.") == "NEWDELHI"


def test_score_against_truth_counts_correct_wrong_missing():
    a = _res("current", {"surname": "KUMAR", "passportNumber": "21234567"})
    b = _res("mrz_v2", {"surname": "KUMAR", "passportNumber": "Z1234567", "dateOfBirth": "1978-03-21"})
    truth = {"surname": "Kumar", "passportNumber": "Z1234567", "dateOfBirth": "21/03/1978"}
    s = E.score_against_truth([a, b], truth)
    assert s["current"]["correct"] == ["surname"]
    assert s["current"]["wrong"] == ["passportNumber"]
    assert s["current"]["missing"] == ["dateOfBirth"]
    assert len(s["mrz_v2"]["correct"]) == 3 and s["mrz_v2"]["checked"] == 3


def test_flatten_site_fields_maps_country_code_and_drops_empty():
    out = E._flatten_site_fields({
        "countryCode": {"value": "IND"}, "surname": {"value": None}, "passportType": {"value": "P"},
        "givenNames": {"value": " ANITA "},
    })
    assert out == {"issuingCountry": "IND", "givenNames": "ANITA"}


def test_cloud_engine_without_key_fails_cleanly(monkeypatch, tmp_path):
    monkeypatch.delenv("GOOGLE_VISION_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    p = tmp_path / "x.png"
    cv2.imwrite(str(p), np.full((50, 50, 3), 255, dtype="uint8"))
    for fn in (E.run_google, E.run_openrouter):
        r = fn(str(p), 0)
        assert r["ok"] is False and "KEY" in r["error"].upper()
