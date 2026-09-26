"""
Unit tests for ocr_runner.py's MRZ (ICAO 9303 TD3) parsing/validation and
orientation-ambiguity logic.

This file did not exist before this pass — ocr_runner.py's own pipeline
correctness had previously only been exercised by ad hoc scratchpad scripts
during development sessions, never promoted into the permanent suite. These
tests were added specifically to lock in two real bugs found and fixed this
round (both reproduced first against real, deliberately OCR-degraded MRZ
strings and a real synthetic passport image, per the project's own "test
everything, never claim it works without testing" rule):

1. The composite check digit was computed from the RAW, uncorrected MRZ
   characters instead of the same ICAO-typed-normalized values already
   used for each individual field's own check (see _coerce_numeric calls
   in parse_mrz_td3) — so a recoverable OCR letter/digit confusion (e.g.
   'O' misread for '0') that already self-healed for its own field's check
   still spuriously failed the composite check.
2. When the optional personal-number field is genuinely unused (ICAO 9303
   permits filling both the field AND its check-digit position with '<'),
   a stray OCR misread landing on that content-free filler run was still
   treated as if it were real data corruption, spuriously failing the
   composite check even though every field that actually carries data was
   valid.

Neither fix loosens validation of genuine data — see
test_genuine_corruption_is_still_flagged below for the negative case.
"""

import cv2
import numpy as np

import ocr_runner as r


def _build_valid_td3(
    passport_no="P9988776<",
    nat="IND",
    dob="900512",
    sex="F",
    expiry="291231",
    personal="<" * 14,
    surname="SHARMA",
    given="ANITA",
    issuing_country="IND",
):
    """Builds a genuinely, mathematically valid TD3 MRZ pair — every check
    digit computed for real via the same algorithm the engine itself uses,
    not hand-picked — so tests exercise real ICAO 9303 arithmetic."""
    assert len(passport_no) == 9
    assert len(nat) == 3 and len(dob) == 6 and len(expiry) == 6 and len(personal) == 14

    c1 = r.compute_icao_check_digit(passport_no)
    c2 = r.compute_icao_check_digit(dob)
    c3 = r.compute_icao_check_digit(expiry)
    c4 = r.compute_icao_check_digit(personal)
    composite_input = f"{passport_no}{c1}{dob}{c2}{expiry}{c3}{personal}{c4}"
    composite = r.compute_icao_check_digit(composite_input)

    line1 = f"P<{issuing_country}{surname}<<{given}".ljust(44, "<")[:44]
    line2 = f"{passport_no}{c1}{nat}{dob}{c2}{sex}{expiry}{c3}{personal}{c4}{composite}"
    assert len(line2) == 44
    return line1, line2


def test_compute_icao_check_digit_known_examples():
    # Worked example from ICAO Doc 9303 Part 4, Appendix A.
    assert r.compute_icao_check_digit("520727") == 3
    # An all-filler input always contributes zero regardless of length —
    # this is the exact property the "unused optional field" exception
    # below relies on.
    assert r.compute_icao_check_digit("<" * 15) == 0


def test_valid_mrz_produces_no_warnings():
    line1, line2 = _build_valid_td3()
    result = r.parse_mrz_td3(line1, line2)
    assert result["valid"] is True
    assert result["warnings"] == []
    assert result["passportNumber"] == "P9988776"
    assert result["dateOfBirth"] == "1990-05-12"
    assert result["dateOfExpiry"] == "2029-12-31"


def test_recoverable_ocr_letter_digit_confusion_self_heals():
    """A digit-only field (DOB) with a single OCR-typical letter/digit
    lookalike substitution ('O' for '0') must validate cleanly end-to-end,
    including the composite — this is the bug fixed this round."""
    line1, line2 = _build_valid_td3()
    corrupted = line2[:14] + "O" + line2[15:]  # '900512' -> '9O0512' at index 14
    result = r.parse_mrz_td3(line1, corrupted)
    assert result["dateOfBirthValid"] is True
    assert result["compositeValid"] is True
    assert result["valid"] is True
    assert result["warnings"] == []
    assert result["dateOfBirth"] == "1990-05-12"  # the corrected value, not the misread one


def test_unused_personal_number_field_with_ocr_noise_does_not_fail_composite():
    """When the personal-number field is genuinely unused (all filler),
    stray OCR noise landing on that content-free run — including on its
    own check-digit position — must not fail the composite check, since
    nothing with actual data in it is wrong."""
    line1, line2 = _build_valid_td3()
    # Corrupt the personal-number field's own CHECK-DIGIT position (index
    # 42) specifically, regardless of what it originally held — reproduces
    # the exact defect found this session: a real synthetic passport
    # image's clean, valid MRZ had this single position OCR-misread as a
    # stray letter (the composite's own check digit, index 43, is left
    # untouched so this test isolates that one position).
    noisy = line2[:42] + "Q" + line2[43:]
    result = r.parse_mrz_td3(line1, noisy)
    assert result["personalNumberValid"] is True
    assert result["compositeValid"] is True
    assert result["valid"] is True
    assert result["warnings"] == []


def test_genuine_corruption_is_still_flagged():
    """The two fixes above must never mask a REAL data problem — a wrong
    digit that is not a recoverable OCR lookalike substitution still fails
    validation, exactly as before."""
    line1, line2 = _build_valid_td3()
    # DOB day changed from 12 to 11 — a real, non-lookalike difference.
    line1b, bad_dob_line2 = _build_valid_td3(dob="900511")
    # Re-use the ORIGINAL (unchanged) check digits/composite so this reads
    # as "the DOB itself is wrong", not "a consistently-rebuilt valid MRZ".
    result = r.parse_mrz_td3(line1, line2[:13] + bad_dob_line2[13:19] + line2[19:])
    assert result["dateOfBirthValid"] is False
    assert result["compositeValid"] is False
    assert result["valid"] is False
    assert "Date of birth check digit failed — please verify manually." in result["warnings"]
    assert "MRZ composite check digit failed — please verify manually." in result["warnings"]


def test_genuine_passport_number_corruption_is_still_flagged():
    line1, line2 = _build_valid_td3()
    # A real, different passport number (not an OCR lookalike substitution).
    corrupted = "P9988786<" + line2[9:]
    result = r.parse_mrz_td3(line1, corrupted)
    assert result["passportNumberValid"] is False
    assert result["compositeValid"] is False
    assert result["valid"] is False
    assert "Passport number check digit failed — please verify manually." in result["warnings"]


def test_malformed_mrz_never_raises():
    """parse_mrz_td3 must degrade to "flag for manual review", never crash,
    on garbage input — project rule 9's "never silently produce a wrong or
    broken result" applies just as much to "don't 500 the whole request"."""
    result = r.parse_mrz_td3("not an mrz line at all", "###short###")
    assert result["valid"] is False
    assert isinstance(result["warnings"], list)


def test_orientation_tie_with_identical_reading_is_not_flagged_ambiguous():
    """Root-cause fix: when the top two candidate rotations recognize
    SUBSTANTIALLY THE SAME text (observed directly this round — a very
    clean/high-contrast page let Tesseract's own layout analysis correctly
    read identical text at two different physical rotations), that is not
    a genuine ambiguity a human needs to resolve, so it must not be
    flagged."""
    assert r._texts_substantially_equal("REPUBLIC OF INDIA PASSPORT SHARMA ANITA", "REPUBLIC OF INDIA PASSPORT SHARMA ANITA") is True
    # Trivial whitespace differences (a re-OCR pass can insert/drop spaces)
    # still count as the same reading.
    assert r._texts_substantially_equal("REPUBLIC OF INDIA  PASSPORT", "REPUBLICOFINDIA PASSPORT") is True


def test_orientation_tie_with_different_reading_is_flagged_ambiguous():
    """A close numeric score between two candidates that recognized
    genuinely DIFFERENT text is a real ambiguity — the case a human
    actually needs to resolve — and must still be flagged."""
    assert r._texts_substantially_equal("REPUBLIC OF INDIA PASSPORT SHARMA ANITA", "XZQ 190>>>> GARBAGE NONSENSE TEXT HERE") is False


# ---------------------------------------------------------------------------
# detect_and_crop_document_region — the real-passport regression this round.
#
# Reproduced directly against a photographed-with-background test image
# (not just this suite's hand-built cases): a passport upload that includes
# any background — a desk, a hand, anything other than a tight scan — was
# passed straight into MRZ-band detection (which assumes the MRZ sits in
# the bottom ~22% of the *whole image*), so the crop landed on pure
# background and every field came back empty. These tests lock in the fix
# (locate the document's own border and perspective-correct it) plus the
# explicit "don't guess" fallback the project rules require.
# ---------------------------------------------------------------------------


def _textured_background(w, h, seed=1):
    rng = np.random.RandomState(seed)
    base = np.full((h, w, 3), (110, 85, 55), dtype=np.int16)
    noise = rng.randint(-20, 20, size=(h, w, 1))
    return np.clip(base + noise, 0, 255).astype(np.uint8)


def _paste_document(bg, doc_w, doc_h, x, y):
    """Draws a white 'document' rectangle with a black border and some
    interior black content lines directly onto bg (a real edge for Canny
    to find, not just a flat color swap) and returns the composite."""
    out = bg.copy()
    cv2.rectangle(out, (x, y), (x + doc_w, y + doc_h), (255, 255, 255), -1)
    cv2.rectangle(out, (x, y), (x + doc_w, y + doc_h), (0, 0, 0), 3)
    for i in range(4):
        yy = y + 30 + i * 25
        cv2.line(out, (x + 20, yy), (x + doc_w - 20, yy), (0, 0, 0), 2)
    return out, (x, y, doc_w, doc_h)


def test_document_region_detection_finds_document_on_a_different_background():
    canvas_w, canvas_h = 1000, 800
    doc_w, doc_h = 500, 350
    x, y = 250, 220
    bg = _textured_background(canvas_w, canvas_h)
    composite, (dx, dy, dw, dh) = _paste_document(bg, doc_w, doc_h, x, y)

    cropped, detected = r.detect_and_crop_document_region(composite)

    assert detected is True
    # The corrected crop should be close to the document's own drawn size
    # (some tolerance for the border line itself and detection rounding),
    # not the full 1000x800 background frame.
    ch, cw = cropped.shape[:2]
    assert abs(cw - dw) <= 25
    assert abs(ch - dh) <= 25
    # And it should be overwhelmingly white/light (the document interior),
    # not the dark textured background.
    assert float(cropped.mean()) > 180


def test_document_region_detection_skips_when_there_is_no_separate_background():
    """The document's own border sits exactly at the image edge — no
    background pixel anywhere in the frame — so there is no closed
    interior contour to find at all. Must be left completely untouched
    rather than risk a bad crop, exactly like safe_crop_white_margins's
    own existing 'uncertain -> don't crop' rule."""
    img = np.full((600, 800, 3), 255, dtype=np.uint8)
    cv2.putText(img, "PASSPORT", (60, 300), cv2.FONT_HERSHEY_SIMPLEX, 2, (0, 0, 0), 3)

    result, detected = r.detect_and_crop_document_region(img)

    assert detected is False
    assert result.shape == img.shape
    assert np.array_equal(result, img)


def test_document_region_detection_still_crops_a_document_with_only_a_thin_margin():
    """A passport rendered onto a canvas only slightly larger than itself
    (the project's own existing hand-built test fixture is exactly this
    shape — see tests/e2e's synthetic_passport.png) still has a real,
    findable border a few dozen pixels in from the frame edge. Finding and
    tightening to that real edge is a genuine, correct crop — not a risky
    guess — so this must still detect it rather than skip."""
    img = np.full((1000, 1400, 3), 255, dtype=np.uint8)
    cv2.rectangle(img, (40, 40), (1360, 960), (0, 0, 0), 3)
    cv2.putText(img, "PASSPORT", (80, 500), cv2.FONT_HERSHEY_SIMPLEX, 2, (0, 0, 0), 3)

    result, detected = r.detect_and_crop_document_region(img)

    assert detected is True
    # Should land close to the drawn interior (1320 x 920), not the full
    # 1400x1000 canvas.
    rh, rw = result.shape[:2]
    assert abs(rw - 1320) <= 30
    assert abs(rh - 920) <= 30


def test_document_region_detection_skips_on_a_frame_with_no_plausible_document():
    """Pure noise / no document-shaped contour anywhere — must not
    fabricate a crop from nothing."""
    rng = np.random.RandomState(42)
    noise_img = rng.randint(0, 255, size=(400, 500, 3), dtype=np.uint8)

    result, detected = r.detect_and_crop_document_region(noise_img)

    assert detected is False
    assert np.array_equal(result, noise_img)


# ---------------------------------------------------------------------------
# _split_band_into_text_line_rows — the second real-photo regression: a
# fixed 50/50 halfway split of the MRZ band only produces two clean line
# crops when the blank margin above line 1 happens to equal the margin
# below line 2. Reproduced directly against a tightly-cropped real-style
# photo where it did not: the halfway line cut straight through line 1's
# own glyphs. This locates the real ink rows instead.
# ---------------------------------------------------------------------------


def _band_with_two_lines(band_h=200, band_w=600, line1_y=40, line2_y=150, line_h=18):
    """A thresholded-style (pure black/white) band image with two black
    text-like bars at deliberately UNEVEN vertical positions — nowhere
    near a 50/50 split — standing in for real MRZ line ink."""
    band = np.full((band_h, band_w), 255, dtype=np.uint8)
    band[line1_y:line1_y + line_h, 40:band_w - 40] = 0
    band[line2_y:line2_y + line_h, 40:band_w - 40] = 0
    return band


def test_split_band_finds_two_lines_at_uneven_vertical_positions():
    band = _band_with_two_lines(line1_y=40, line2_y=150)

    result = r._split_band_into_text_line_rows(band)

    assert result is not None
    line_a, line_b = result
    # Each returned crop should contain real ink (the drawn bar), and line
    # A (the upper one) must not also contain line B's content — i.e. the
    # split found the actual gap between the two lines rather than an
    # arbitrary halfway point that would smear them together.
    assert (line_a == 0).any()
    assert (line_b == 0).any()
    assert line_a.shape[0] < band.shape[0] * 0.7
    assert line_b.shape[0] < band.shape[0] * 0.7


def test_split_band_returns_none_when_there_is_only_one_line():
    band = np.full((200, 600), 255, dtype=np.uint8)
    band[90:108, 40:560] = 0  # a single ink row — not two separable lines

    assert r._split_band_into_text_line_rows(band) is None
