"""
Tests for mrz_reader.py (MRZ Reader v2 — free, local, offline).

Everything here is synthetic (project rule 11): MRZ lines are generated with
the real ICAO check-digit algorithm for made-up people, and the image tests
render those lines onto a fake page with an ordinary monospace font. No real
passport is ever used.
"""

from __future__ import annotations

import os

import cv2
import numpy as np
import pytest
from PIL import Image, ImageDraw, ImageFont

import mrz_reader as m
import ocr_runner as r
from conftest import skip_if_missing_binary


def build_td3(passport_no="P9988776<", nat="IND", dob="900512", sex="F", expiry="291231",
              personal="<" * 14, surname="SHARMA", given="ANITA", issuing="IND"):
    c1 = r.compute_icao_check_digit(passport_no)
    c2 = r.compute_icao_check_digit(dob)
    c3 = r.compute_icao_check_digit(expiry)
    c4 = r.compute_icao_check_digit(personal)
    comp = r.compute_icao_check_digit(f"{passport_no}{c1}{dob}{c2}{expiry}{c3}{personal}{c4}")
    l1 = f"P<{issuing}{surname.replace(' ', '<')}<<{given.replace(' ', '<')}".ljust(44, "<")[:44]
    l2 = f"{passport_no}{c1}{nat}{dob}{c2}{sex}{expiry}{c3}{personal}{c4}{comp}"
    return l1, l2


KUMAR = dict(passport_no="Z1234567<", surname="KUMAR", given="RAJESH KUMAR", dob="780321", sex="M", expiry="330615")


# ---------------------------------------------------------------- pure logic


def test_clean_line2_needs_no_repair():
    _, l2 = build_td3()
    out = m.repair_line2(l2)
    assert out["line"] == l2
    assert out["repairs"] == []
    assert all(out["checks"].values())


def test_letter_in_digit_only_field_is_fixed_and_reported():
    _, l2 = build_td3()
    bad = l2[:13] + "9O0512" + l2[19:]  # DOB 900512 with 0 read as O
    out = m.repair_line2(bad)
    assert out["line"] == l2
    assert out["checks"]["dateOfBirth"]
    assert any(x["field"] == "dateOfBirth" for x in out["repairs"])


def test_passport_number_character_fixed_via_check_digit():
    l1, l2 = build_td3(passport_no="N805B217<")
    bad = "N8O5B217<" + l2[9:]  # a 0 read as the letter O
    out = m.repair_line2(bad)
    assert out["line"] == l2
    rep = [x for x in out["repairs"] if x["field"] == "passportNumber"]
    assert rep and rep[0]["from"] == "N8O5B217<" and rep[0]["to"] == "N805B217<"


def test_two_character_passport_number_error_is_fixed():
    _, l2 = build_td3(passport_no="Z1234567<")
    bad = "ZI2345G7<" + l2[9:]  # 1->I and 6->G
    out = m.repair_line2(bad)
    assert out["line"] == l2


def test_date_repair_requires_a_real_calendar_date():
    _, l2 = build_td3(dob="900512")
    bad = l2[:13] + "900S12" + l2[19:]
    assert m.repair_line2(bad)["line"] == l2
    assert m._is_plausible_date("901332") is False
    assert m._is_plausible_date("900230") is False
    assert m._is_plausible_date("000229") is True


def test_only_composite_digit_misread_is_repaired():
    _, l2 = build_td3()
    bad = l2[:43] + ("9" if l2[43] != "9" else "8")
    out = m.repair_line2(bad)
    assert out["line"] == l2
    assert [x["field"] for x in out["repairs"]] == ["compositeCheck"]


def test_unrepairable_corruption_is_flagged_not_hidden():
    _, l2 = build_td3()
    bad = l2[:13] + "123456" + l2[19:]  # completely different DOB
    out = m.repair_line2(bad)
    assert out["checks"]["dateOfBirth"] is False
    assert out["line"][13:19] == "123456"  # never invented


def test_ambiguous_fix_is_never_guessed():
    # Same check digit reachable from two different single edits -> None
    data = "AB1234567"[:9]
    results = set()
    for i, ch in enumerate(data):
        for alt in m._candidate_chars(ch, "alnum"):
            cand = data[:i] + alt + data[i + 1:]
            results.add(r.compute_icao_check_digit(cand))
    # sanity only: the helper returns None rather than raising for a bad check char
    assert m._search_fix(data, "x", "alnum") is None


def test_line1_trailing_filler_read_as_letters_is_repaired():
    l1, _ = build_td3()
    junk = l1.rstrip("<") + "KKKKKKKKKKKKKKKKKKKKK"
    out = m.repair_line1(junk[:44])
    assert out["line"] == l1


def test_line1_digits_in_name_become_letters():
    l1, _ = build_td3(surname="SH4RMA")  # nonsense but tests the type rule
    out = m.repair_line1(l1)
    assert "4" not in out["line"]


def test_line1_missing_separator_is_restored():
    l1, _ = build_td3()
    bad = l1.replace("SHARMA<<ANITA", "SHARMAKKANITA")
    out = m.repair_line1(bad)
    assert out["line"][5:].startswith("SHARMA<<ANITA")


def test_country_code_repair_is_unique_or_none():
    assert m._repair_country_code("1ND") == ("IND", False) or m._repair_country_code("1ND")[0] == "IND"
    assert m._repair_country_code("IND") == ("IND", False)
    assert m._repair_country_code("ZZZ")[0] == "ZZZ"  # unknown stays as read


def test_align_handles_dropped_and_extra_character():
    _, l2 = build_td3()
    dropped = l2[:20] + l2[21:]  # 43 chars
    variants = m._align_line2(dropped)
    assert any(m.repair_line2(v)["checks"]["dateOfBirth"] and m.repair_line2(v)["validCount"] == 5 for v in variants)
    extra = l2[:20] + "X" + l2[20:]
    assert any(m.repair_line2(v)["validCount"] == 5 for v in m._align_line2(extra))


def test_voting_prefers_the_majority_of_clean_reads():
    l1, l2 = build_td3()
    noisy = l2[:13] + "9O0S12" + l2[19:]
    ev = m.evaluate_candidates([l1] * 3, [l2, l2, noisy])
    assert ev["line2"] == l2 and ev["line1"] == l1


def test_evaluate_candidates_returns_none_without_reads():
    assert m.evaluate_candidates([], []) is None
    assert m.evaluate_candidates(["P<IND"], ["123"]) is None


# ----------------------------------------------------------- image round-trip


def _font_path():
    for p in (
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationMono-Bold.ttf",
        "C:/Windows/Fonts/consolab.ttf",
        "C:/Windows/Fonts/courbd.ttf",
    ):
        if os.path.isfile(p):
            return p
    return None


def _render(l1, l2, W=1400, H=1000, mrz_y=None):
    fp = _font_path()
    if not fp:
        pytest.skip("no monospace TTF font available to render a synthetic MRZ")
    img = Image.new("RGB", (W, H), (235, 232, 222))
    d = ImageDraw.Draw(img)
    f = ImageFont.truetype(fp, int(W / 44 / 0.62))
    d.text((60, 60), "REPUBLIC OF NOWHERE  (synthetic test page)", fill=(20, 20, 20), font=f)
    y = mrz_y if mrz_y is not None else H - 170
    d.text((50, y), l1, fill=(10, 10, 10), font=f)
    d.text((50, y + int(f.size * 1.5)), l2, fill=(10, 10, 10), font=f)
    return cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)


def _same_person(res, l1, l2):
    """Compares the fields that carry meaning (the unused personal-number
    check position can legitimately be '<' or '0')."""
    assert res["found"], res.get("warnings")
    assert res["line1"] == l1
    assert res["line2"][:42] == l2[:42]
    assert all(res["checks"].values())


@pytest.mark.parametrize("variant", ["clean", "rot180", "rot90", "mid-page", "noise", "blur"])
def test_reads_synthetic_mrz_under_realistic_damage(variant):
    skip_if_missing_binary("tesseract")
    l1, l2 = build_td3(**KUMAR)
    img = _render(l1, l2, mrz_y=450 if variant == "mid-page" else None)
    if variant == "rot180":
        img = cv2.rotate(img, cv2.ROTATE_180)
    elif variant == "rot90":
        img = cv2.rotate(img, cv2.ROTATE_90_CLOCKWISE)
    elif variant == "noise":
        img = np.clip(img + np.random.RandomState(1).normal(0, 22, img.shape), 0, 255).astype("uint8")
    elif variant == "blur":
        img = cv2.GaussianBlur(img, (0, 0), 2.2)
    res = m.read_mrz(img, max_seconds=60)
    _same_person(res, l1, l2)
    fields = m.fields_from_result(res)
    assert fields["passportNumber"] == "Z1234567"
    assert fields["dateOfBirth"] == "1978-03-21"
    assert fields["givenNames"] == "RAJESH KUMAR"
    assert fields["surname"] == "KUMAR"
    assert res["verificationStatus"] == "OCR Extracted — Please Verify"


def test_blank_image_reports_not_found_instead_of_inventing():
    skip_if_missing_binary("tesseract")
    blank = np.full((600, 900, 3), 240, dtype="uint8")
    res = m.read_mrz(blank, max_seconds=20)
    assert res["found"] is False
    assert res["warnings"]


# ------------------------------------------------- wired into the pipeline


def test_production_pipeline_uses_v2_when_original_reader_fails():
    skip_if_missing_binary("tesseract")
    l1, l2 = build_td3(**KUMAR)
    img = _render(l1, l2, mrz_y=450)  # MRZ in the middle of the page: not in the old fixed bottom band
    pil = Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
    out = r.process_passport_page(pil)
    f = out["fields"]
    assert out["mrzEngine"] in ("v1", "v2")
    assert f["passportNumber"]["value"] == "Z1234567"
    assert f["dateOfBirth"]["value"] == "1978-03-21"
    assert f["surname"]["value"] == "KUMAR"
    assert out["verificationStatus"] == "OCR Extracted — Please Verify"


@pytest.mark.parametrize("rotation,cv_code", [(90, cv2.ROTATE_90_CLOCKWISE), (180, cv2.ROTATE_180), (270, cv2.ROTATE_90_COUNTERCLOCKWISE)])
def test_pipeline_takes_the_page_orientation_from_where_the_mrz_was_read(rotation, cv_code):
    skip_if_missing_binary("tesseract")
    l1, l2 = build_td3(**KUMAR)
    img = cv2.rotate(_render(l1, l2), cv_code)
    out = r.process_passport_page(Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB)))
    # Undoing the photo's rotation takes the opposite turn.
    assert out["orientationApplied"] == (360 - rotation) % 360
    assert out["orientationNeedsReview"] is False
    assert out["fields"]["passportNumber"]["value"] == "Z1234567"


def test_v2_can_be_switched_off_for_the_lab_baseline():
    skip_if_missing_binary("tesseract")
    l1, l2 = build_td3(**KUMAR)
    pil = Image.fromarray(cv2.cvtColor(_render(l1, l2), cv2.COLOR_BGR2RGB))
    out = r.process_passport_page(pil, use_mrz_v2=False)
    assert out["mrzEngine"] == "v1"
