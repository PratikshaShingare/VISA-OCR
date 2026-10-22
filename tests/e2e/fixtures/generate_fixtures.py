"""
Generates the synthetic test assets the e2e suite runs OCR/upload flows
against. Run directly (`python3 generate_fixtures.py`) or let
`_common.ensure_fixtures()` call it automatically the first time a script
needs one of these files.

Both outputs are obviously fake, generated-from-code assets — never a real
travel document or a real person's signature (project rule 11: real client
passport data must never be used as sample/test data).

  synthetic_passport.png — a fake passport bio-data page for "REPUBLIC OF
  UTOPIA", rendered with PIL and rotated a few degrees (so the real
  auto-orientation-correction step in the OCR pipeline has something real
  to do), with a real, check-digit-valid MRZ so the real MRZ validator
  genuinely exercises its pass path — not a mocked/stubbed one.

  fake_signature.png — a small squiggle standing in for an uploaded
  staff/inviter signature image, used to exercise the real
  docx_utils.insert_signature_image() embedding path end-to-end.

  synthetic_hotel_voucher_1.png / synthetic_hotel_voucher_2.png — two
  distinctly-labeled fake hotel/OTA booking confirmations (never a real
  hotel's or a real guest's data — project rule 11), used to exercise the
  real hotel_voucher_ocr.py label-search pipeline end-to-end for the
  Hotel Blocking "Upload Hotel Vouchers" (multi-file) flow.
"""

import os
import sys

from PIL import Image, ImageDraw, ImageFont

FIXTURES_DIR = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.normpath(os.path.join(FIXTURES_DIR, "..", "..", "..", "backend", "python"))
sys.path.insert(0, BACKEND_DIR)

import ocr_runner as ocr  # noqa: E402  (path insert must happen first)


def _build_valid_mrz_line2() -> str:
    passport_no = "X1234567U"[:9].ljust(9, "<")
    dob = "900101"
    expiry = "300101"
    nat = "UTO"
    sex = "M"
    personal = "<" * 14
    c1 = ocr.compute_icao_check_digit(passport_no)
    c2 = ocr.compute_icao_check_digit(dob)
    c3 = ocr.compute_icao_check_digit(expiry)
    c4 = "<"  # unused personal-number field
    composite_input = f"{passport_no}{c1}{dob}{c2}{expiry}{c3}{personal}{c4}"
    composite = ocr.compute_icao_check_digit(composite_input)
    line2 = f"{passport_no}{c1}{nat}{dob}{c2}{sex}{expiry}{c3}{personal}{c4}{composite}"
    assert len(line2) == 44, len(line2)
    return line2


def render_synthetic_passport_page(rotate_deg: int = 7) -> Image.Image:
    line1 = "P<UTOTESTPERSON<<SAMPLE<<<<<<<<<<<<<<<<<<<<<"
    line2 = _build_valid_mrz_line2()

    W, H = 1400, 1000
    img = Image.new("RGB", (W, H), "white")
    draw = ImageDraw.Draw(img)

    try:
        font_big = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 30)
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 24)
        mono = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf", 28)
    except Exception:
        font_big = font = mono = ImageFont.load_default()

    draw.rectangle([40, 40, W - 40, H - 40], outline="black", width=3)
    draw.text((80, 80), "REPUBLIC OF UTOPIA", font=font_big, fill="black")
    draw.text((80, 130), "PASSPORT (SYNTHETIC TEST DOCUMENT)", font=font_big, fill="black")

    rows = [
        ("Surname", "TESTPERSON"),
        ("Given Names", "SAMPLE"),
        ("Nationality", "UTOPIAN"),
        ("Date of Birth", "01 JAN 1990"),
        ("Sex", "M"),
        ("Place of Birth", "UTOPIA CITY"),
        ("Date of Issue", "02 JAN 2020"),
        ("Date of Expiry", "01 JAN 2030"),
        ("Passport No.", "X1234567U"),
        ("Old Passport No", "Y7654321Z"),
    ]
    y = 200
    for label, value in rows:
        draw.text((80, y), f"{label}:", font=font, fill="black")
        draw.text((380, y), value, font=font, fill="black")
        y += 42

    draw.text((80, H - 160), line1, font=mono, fill="black")
    draw.text((80, H - 110), line2, font=mono, fill="black")

    if rotate_deg:
        img = img.rotate(rotate_deg, expand=True, fillcolor="white")
    return img


def render_fake_signature() -> Image.Image:
    img = Image.new("RGB", (300, 100), "white")
    draw = ImageDraw.Draw(img)
    # A simple looping squiggle — visibly a placeholder, not a traced real signature.
    points = [(20, 70), (60, 30), (90, 80), (130, 25), (170, 75), (210, 35), (250, 65), (280, 45)]
    draw.line(points, fill="black", width=3, joint="curve")
    return img


def render_synthetic_hotel_voucher(rows: list[tuple[str, str]], guest_lines: list[str]) -> Image.Image:
    W, H = 1200, 900
    img = Image.new("RGB", (W, H), "white")
    draw = ImageDraw.Draw(img)

    try:
        font_big = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 28)
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 22)
    except Exception:
        font_big = font = ImageFont.load_default()

    draw.rectangle([30, 30, W - 30, H - 30], outline="black", width=2)
    draw.text((60, 60), "HOTEL BOOKING CONFIRMATION", font=font_big, fill="black")

    y = 130
    for label, value in rows:
        draw.text((60, y), f"{label}: {value}", font=font, fill="black")
        y += 40

    y += 20
    for line in guest_lines:
        draw.text((60, y), line, font=font, fill="black")
        y += 36

    return img


def main():
    os.makedirs(FIXTURES_DIR, exist_ok=True)
    passport_path = os.path.join(FIXTURES_DIR, "synthetic_passport.png")
    signature_path = os.path.join(FIXTURES_DIR, "fake_signature.png")
    voucher1_path = os.path.join(FIXTURES_DIR, "synthetic_hotel_voucher_1.png")
    voucher2_path = os.path.join(FIXTURES_DIR, "synthetic_hotel_voucher_2.png")

    render_synthetic_passport_page(rotate_deg=7).save(passport_path)
    render_fake_signature().save(signature_path)

    render_synthetic_hotel_voucher(
        rows=[
            ("Hotel Name", "Fixture Grand Hotel"),
            ("Hotel Phone", "01 23456789"),
            ("Address", "1 Fixture Street"),
            ("City", "Paris"),
            ("Country", "France"),
            ("Confirmation No", "FIX111222"),
            ("Lead Guest Name", "Test Guestone"),
            ("Room Type", "Deluxe Double"),
            ("No of Rooms", "1"),
            ("Adults", "2"),
            ("Children", "0"),
            ("Check-in", "01/12/2026"),
            ("Check-out", "05/12/2026"),
        ],
        guest_lines=["Guest 1 Name: Test Guestone", "Guest 2 Name: Test Guesttwo"],
    ).save(voucher1_path)

    render_synthetic_hotel_voucher(
        rows=[
            ("Hotel Name", "Fixture Riviera Hotel"),
            ("Hotel Phone", "09 87654321"),
            ("Address", "2 Fixture Avenue"),
            ("City", "Nice"),
            ("Country", "France"),
            ("Confirmation No", "FIX333444"),
            ("Lead Guest Name", "Test Guestthree"),
            ("Room Type", "Standard Twin"),
            ("No of Rooms", "1"),
            ("Adults", "1"),
            ("Children", "1"),
            ("Check-in", "06/12/2026"),
            ("Check-out", "10/12/2026"),
        ],
        guest_lines=["Guest 1 Name: Test Guestthree"],
    ).save(voucher2_path)

    print(f"Wrote {passport_path}")
    print(f"Wrote {signature_path}")
    print(f"Wrote {voucher1_path}")
    print(f"Wrote {voucher2_path}")


if __name__ == "__main__":
    main()
