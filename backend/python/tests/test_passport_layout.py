"""passport_layout.py — bio-page crop, back-page parsing, salutation, place
cleaning. Synthetic people only (project rule 11)."""
from datetime import date

import cv2
import numpy as np
import pytest
from PIL import Image, ImageDraw, ImageFont

import ocr_runner as r
import passport_crosscheck as pc
import passport_layout as pl
from conftest import skip_if_missing_binary
from test_mrz_reader import build_td3

FONT_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf"


def _font(size):
    try:
        return ImageFont.truetype(FONT_PATH, size)
    except OSError:
        pytest.skip("DejaVu Sans Mono Bold not installed")


def synthetic_bio_page(surname="SHARMA", given="ANITA", pad=(120, 200, 150, 260)):
    """A fake bio page (white card, MRZ along the bottom, a few value rows)
    on a grey desk with extra blank area around it."""
    l1, l2 = build_td3(surname=surname, given=given)
    page_w, page_h = 1300, 920
    page = Image.new("RGB", (page_w, page_h), (252, 252, 252))
    d = ImageDraw.Draw(page)
    f_mrz = _font(44)
    d.text((60, 720), l1, fill=(20, 20, 20), font=f_mrz)
    d.text((60, 790), l2, fill=(20, 20, 20), font=f_mrz)
    f = _font(30)
    d.rectangle((90, 190, 430, 560), fill=(200, 190, 185))  # photo
    d.text((480, 255), surname, fill=(20, 20, 20), font=f)
    d.text((480, 335), given, fill=(20, 20, 20), font=f)
    d.text((480, 410), "12/05/1990", fill=(20, 20, 20), font=f)
    d.text((480, 490), "PUNE", fill=(20, 20, 20), font=f)
    d.text((480, 565), "MUMBAI", fill=(20, 20, 20), font=f)
    d.text((480, 640), "01/01/2020", fill=(20, 20, 20), font=f)
    canvas = Image.new("RGB", (page_w + pad[0] + pad[2], page_h + pad[1] + pad[3]), (225, 225, 225))
    canvas.paste(page, (pad[0], pad[1]))
    return canvas, (page_w, page_h)


# ----------------------------------------------------------- salutation


@pytest.mark.parametrize(
    "sex,dob,spouse,expected",
    [
        ("M", "1985-03-01", None, "Mr"),
        ("M", "2015-03-01", None, "Master"),
        ("F", "2015-03-01", None, "Ms"),
        ("F", "1985-03-01", "SOME SPOUSE", "Mrs"),
        ("F", "1985-03-01", None, "Ms"),
    ],
)
def test_salutation_rules(sex, dob, spouse, expected):
    out = pl.derive_salutation(sex, dob, spouse, today=date(2026, 10, 21))
    assert out["value"] == expected


def test_salutation_none_when_sex_unknown():
    assert pl.derive_salutation("X", "1985-03-01") is None
    assert pl.derive_salutation(None, None) is None


def test_adult_female_without_spouse_can_be_upgraded():
    assert pl.derive_salutation("F", "1985-03-01", None, today=date(2026, 10, 21))["canBeMrs"] is True


def test_age_boundary_on_birthday():
    assert pl.age_on("2008-10-21", date(2026, 10, 21)) == 18
    assert pl.age_on("2008-10-22", date(2026, 10, 21)) == 17


# ----------------------------------------------------------- places


def test_clean_place_accepts_real_place_and_rejects_garbage():
    assert pl.clean_place("MUMBAI", 50, 80) == "MUMBAI"
    assert pl.clean_place("NEW DELHI", 50, 80) == "NEW DELHI"
    for junk in ("ae", "os cies", "een ha", "acs pesomcnes Bice", "XQZ", "||", "SURNAME", ""):
        assert pl.clean_place(junk, 0, 100) is None


def test_clean_place_rejects_low_confidence_and_mrz_names():
    assert pl.clean_place("MUMBAI", 55, 20) is None
    assert pl.clean_place("SHARMA", 0, 100, exclude={"SHARMA"}) is None


def test_extract_bio_viz_assigns_two_rows_after_dob():
    mrz = {"surname": "SHARMA", "givenNames": "ANITA", "dateOfBirth": "1990-05-12"}
    rows = [
        {"y": 10, "text": "SHARMA", "conf": 90},
        {"y": 20, "text": "ANITA", "conf": 90},
        {"y": 30, "text": "12/05/1990", "conf": 90},
        {"y": 40, "text": "PUNE", "conf": 80},
        {"y": 50, "text": "MUMBAI", "conf": 80},
    ]
    out = pl.extract_bio_viz(rows, mrz)
    assert out["placeOfBirth"]["value"] == "PUNE"
    assert out["placeOfIssue"]["value"] == "MUMBAI"


def test_extract_bio_viz_does_not_guess_with_one_row():
    mrz = {"surname": "SHARMA", "givenNames": "ANITA", "dateOfBirth": "1990-05-12"}
    rows = [{"y": 30, "text": "12/05/1990", "conf": 90}, {"y": 40, "text": "PUNE", "conf": 80}]
    out = pl.extract_bio_viz(rows, mrz)
    assert out["placeOfBirth"] is None and out["placeOfIssue"] is None


# ----------------------------------------------------------- back page


BACK_TEXT = """Name of Father / Legal Guardian
RAMESH SHARMA
Name of Mother
KAVITA SHARMA
Name of Spouse
ARUN SHARMA
Address
FLAT 12 SAMPLE APARTMENTS
MG ROAD PUNE
PIN:411001,MAHARASHTRA,INDIA
Old Passport No. A1234567
"""


def test_parse_back_page_extracts_names_address_and_pin():
    out = pl.parse_back_page(BACK_TEXT)
    assert out["fatherName"] == "RAMESH SHARMA"
    assert out["motherName"] == "KAVITA SHARMA"
    assert out["spouseName"] == "ARUN SHARMA"
    assert out["addressLine1"] == "FLAT 12 SAMPLE APARTMENTS"
    assert out["addressLine2"] == "MG ROAD PUNE"
    assert out["addressPincode"] == "411001"
    assert out["addressState"] == "MAHARASHTRA"
    assert out["addressCountry"] == "INDIA"


def test_back_page_detection():
    assert pl.looks_like_back_page(BACK_TEXT)
    assert not pl.looks_like_back_page("P<INDSHARMA<<ANITA REPUBLIC OF INDIA")


def test_back_page_rejects_noise_names():
    out = pl.parse_back_page("Name of Father\nae\nName of Mother\nos cies\n")
    assert out["fatherName"] is None and out["motherName"] is None


# ----------------------------------------------------------- name cleanup


def test_text_after_filler_run_is_dropped():
    name, notes = pc._clean_name_field("SHARMA<<ANITA<<<<<<KKGCCANITA<<<<<<<<", [])
    assert name.startswith("SHARMA<<ANITA<<<") and "KK" not in name
    assert notes


def test_single_stray_filler_lookalike_after_name_is_dropped_but_real_initial_kept():
    dropped, _ = pc._clean_name_field("SHARMA<<ANITA<K<<<<<<<<<<<<<<<<<<<<<<<<", [])
    kept, _ = pc._clean_name_field("SHARMA<<ANITA<P<<<<<<<<<<<<<<<<<<<<<<<<<<", [])
    assert dropped.startswith("SHARMA<<ANITA<<")
    assert kept.startswith("SHARMA<<ANITA<P<<")


# ----------------------------------------------------------- crop + pipeline


def test_crop_trims_desk_and_blank_area_to_the_bio_page():
    skip_if_missing_binary("tesseract")
    canvas, (pw, ph) = synthetic_bio_page()
    bgr = cv2.cvtColor(np.array(canvas), cv2.COLOR_RGB2BGR)
    cropped, did = pl.crop_to_bio_page(bgr)
    assert did
    h, w = cropped.shape[:2]
    assert w <= pw * 1.12 and h <= ph * 1.15
    assert w >= pw * 0.9 and h >= ph * 0.85
    assert w < bgr.shape[1] * 0.92 and h < bgr.shape[0] * 0.85


def test_pipeline_on_padded_synthetic_page_is_cropped_clean_and_quiet():
    skip_if_missing_binary("tesseract")
    canvas, _ = synthetic_bio_page()
    out = r.process_passport_page(canvas)
    assert out["pageKind"] == "bio"
    assert out["croppedToPage"] is True
    assert out["fields"]["surname"]["value"] == "SHARMA"
    assert out["fields"]["givenNames"]["value"] == "ANITA"
    assert out["fields"]["salutation"]["value"] == "Ms"
    assert out["fields"]["salutation"]["needsReview"] is True
    assert out["orientationNeedsReview"] is False
    assert not any("rientation" in w for w in out["warnings"])
    # no loose-regex garbage
    for key in ("placeOfBirth", "placeOfIssue", "issuingAuthority", "addressLine1"):
        v = out["fields"][key]["value"]
        assert v is None or (v.isupper() and len(v) >= 3)


def test_address_page_is_not_mistaken_for_a_data_page():
    skip_if_missing_binary("tesseract")
    page = Image.new("RGB", (1300, 920), (252, 252, 252))
    d = ImageDraw.Draw(page)
    f = _font(34)
    y = 150
    for line in ("Name of Father / Legal Guardian", "RAMESH SHARMA", "Name of Mother", "KAVITA SHARMA",
                 "Name of Spouse", "ARUN SHARMA", "Address", "FLAT 12 SAMPLE APARTMENTS", "MG ROAD PUNE",
                 "PIN:411001,MAHARASHTRA,INDIA"):
        d.text((150, y), line, fill=(20, 20, 20), font=f)
        y += 70
    out = r.process_passport_page(page)
    assert out["pageKind"] == "back"
    assert out["mrz"] is None
    assert out["fields"]["addressPincode"]["value"] == "411001"
    assert "passportNumber" not in out["fields"] and "surname" not in out["fields"]
    assert not any("MRZ lines were not detected" in w for w in out["warnings"])


# ----------------------------------------------------------- MRZ-anchored crop on awkward photos


def test_small_passport_on_a_large_sheet_is_found_and_cropped():
    """A passport lying on an A4 scan is only ~45% of the image width; the
    old block detector required 55%+ and the crop was silently skipped."""
    skip_if_missing_binary("tesseract")
    canvas, (pw, ph) = synthetic_bio_page(pad=(900, 700, 900, 1500))
    bgr = cv2.cvtColor(np.array(canvas), cv2.COLOR_RGB2BGR)
    assert bgr.shape[1] > 2.2 * pw
    box = pl.locate_mrz_ink(cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY))
    assert box is not None and box[2] < 0.5 * bgr.shape[1]
    cropped, did = pl.crop_to_bio_page(bgr)
    assert did
    h, w = cropped.shape[:2]
    assert pw * 0.9 <= w <= pw * 1.15
    assert ph * 0.85 <= h <= ph * 1.2


def test_crop_covers_the_whole_page_not_just_a_strip():
    """The whole page (photo and value rows included) stays in the crop, not
    only the MRZ strip along the bottom."""
    skip_if_missing_binary("tesseract")
    canvas, (pw, ph) = synthetic_bio_page(pad=(200, 300, 200, 300))
    bgr = cv2.cvtColor(np.array(canvas), cv2.COLOR_RGB2BGR)
    cropped, did = pl.crop_to_bio_page(bgr)
    assert did
    assert cropped.shape[0] >= 0.85 * ph
    # the photo block (a distinct colour) is inside the crop
    photo_like = np.all(np.abs(cropped.astype(int) - np.array([185, 190, 200])) < 12, axis=2).sum()
    assert photo_like > 20000


def test_locate_mrz_ink_ignores_pages_without_an_mrz():
    page = Image.new("RGB", (1300, 920), (252, 252, 252))
    d = ImageDraw.Draw(page)
    f = _font(34)
    for i, line in enumerate(("RAMESH SHARMA", "KAVITA SHARMA", "FLAT 12,MG ROAD", "PUNE")):
        d.text((150, 150 + i * 80), line, fill=(20, 20, 20), font=f)
    assert pl.locate_mrz_ink(cv2.cvtColor(np.array(page), cv2.COLOR_RGB2GRAY)) is None


def test_mrz_skew_angle_measures_the_page_tilt_and_deskew_removes_it():
    skip_if_missing_binary("tesseract")
    canvas, _ = synthetic_bio_page(pad=(300, 300, 300, 300))
    tilted = canvas.rotate(3.0, resample=Image.BICUBIC, fillcolor=(225, 225, 225))
    bgr = cv2.cvtColor(np.array(tilted), cv2.COLOR_RGB2BGR)
    angle = pl.mrz_skew_angle(cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY))
    assert angle is not None and abs(abs(angle) - 3.0) < 0.5
    fixed = r.deskew_image(bgr, angle)
    after = pl.mrz_skew_angle(cv2.cvtColor(fixed, cv2.COLOR_BGR2GRAY))
    assert after is not None and abs(after) < 0.5


# ----------------------------------------------------------- address page, read from its dark ink


INK_TEXT = """EMIGRATION CHECK REQUIRED
A1234567
RAMESH SHARMA
KAVITA SHARMA
ARUN SHARMA
FLAT 12,SAMPLE APARTMENTS,MG ROAD
KOTHRUD,PUNE
PIN: 411038,MAHARASHTRA,INDIA
K1234567 21/10/2011 PUNE
PN1234567890123
"""


def test_back_page_values_without_any_label_text():
    out = pl.parse_back_page(INK_TEXT)
    assert out["recognised"]
    assert (out["fatherName"], out["motherName"], out["spouseName"]) == ("RAMESH SHARMA", "KAVITA SHARMA", "ARUN SHARMA")
    assert out["addressLine1"] == "FLAT 12, SAMPLE APARTMENTS, MG ROAD"
    assert out["addressLine2"] == "KOTHRUD"
    assert out["addressCity"] == "PUNE"
    assert (out["addressState"], out["addressCountry"], out["addressPincode"]) == ("MAHARASHTRA", "INDIA", "411038")
    assert out["oldPassportNumber"] == "K1234567"
    assert out["oldPassportIssueDate"] == "2011-10-21"
    assert out["oldPassportPlace"] == "PUNE"
    assert out["oldPassportNumberCertain"] is True


def test_two_names_means_no_spouse_and_noise_lines_are_ignored():
    text = "Ae AG\nEMIGRATION CuctdK REQUIRED | aida\nU9421149\nVIRAT SAMPLE\nRADHIKA SAMPLE\nA 1301,SOME HEIGHTS,PLOT 12\nGHANSOLI,NAVI MUMBAI\nPIN: 400701 ,MAHARASHTRA,INDIA : ‘\nR0193070 28/04/2017 THANE '\n804075086928620 |\nt"
    out = pl.parse_back_page(text)
    assert out["fatherName"] == "VIRAT SAMPLE" and out["motherName"] == "RADHIKA SAMPLE"
    assert out["spouseName"] is None
    assert out["addressLine1"] == "A 1301, SOME HEIGHTS, PLOT 12"
    assert out["addressLine2"] == "GHANSOLI" and out["addressCity"] == "NAVI MUMBAI"
    assert out["addressPincode"] == "400701" and out["addressCountry"] == "INDIA"
    assert out["oldPassportNumber"] == "R0193070"


def test_speck_tokens_are_dropped_from_address_lines():
    text = "RAMESH SHARMA\nKAVITA SHARMA\n38,SOME NAGAR,CIVIL ROAD a\nNANAKWADA,VALSAD oo.\nPIN: 396001,GUJARAT, INDIA\n"
    out = pl.parse_back_page(text)
    assert out["addressLine1"] == "38, SOME NAGAR, CIVIL ROAD"
    assert out["addressCity"] == "VALSAD"


def test_old_passport_number_normalisation():
    assert pl.normalise_old_passport_number("£4311420") == ("E4311420", True)
    assert pl.normalise_old_passport_number("R0I93O7O") == ("R0193070", True)
    assert pl.normalise_old_passport_number("69355663") == ("69355663", False)  # first char could be a letter
    assert pl.normalise_old_passport_number("$8323309") == ("S8323309", True)


def test_old_passport_line_with_an_impossible_date_is_ignored():
    out = pl.parse_back_page("RAMESH SHARMA\nKAVITA SHARMA\nPIN: 411001,MAHARASHTRA,INDIA\nK1234567 31/02/2011 PUNE\n")
    assert out["oldPassportNumber"] is None


def _synthetic_address_page(rotation=0):
    """Pale-blue labels, dark values, like the real page; optionally turned."""
    page = Image.new("RGB", (1800, 1250), (235, 240, 248))
    d = ImageDraw.Draw(page)
    label_font, value_font = _font(26), _font(40)
    rows = [
        ("Name of Father / Legal Guardian", "RAMESH SHARMA"),
        ("Name of Mother", "KAVITA SHARMA"),
        ("Name of Spouse", "ARUN SHARMA"),
        ("Address", "FLAT 12,SAMPLE APARTMENTS,MG ROAD"),
        ("", "KOTHRUD,PUNE"),
        ("", "PIN:411038,MAHARASHTRA,INDIA"),
        ("Old Passport No. with Date and Place of Issue", "K1234567   21/10/2011   PUNE"),
    ]
    y = 120
    for label, value in rows:
        if label:
            d.text((160, y), label, fill=(150, 175, 215), font=label_font)
            y += 50
        d.text((160, y), value, fill=(25, 25, 30), font=value_font)
        y += 95
    return page.rotate(rotation, expand=True, fillcolor=(255, 255, 255)) if rotation else page


@pytest.mark.parametrize("rotation", [0, 90, 270])
def test_pipeline_reads_a_rotated_address_page_from_its_dark_ink(rotation):
    skip_if_missing_binary("tesseract")
    out = r.process_passport_page(_synthetic_address_page(rotation))
    assert out["pageKind"] == "back"
    f = out["fields"]
    assert f["addressPincode"]["value"] == "411038"
    assert f["addressState"]["value"] == "MAHARASHTRA"
    assert f["addressCity"]["value"] == "PUNE"
    assert f["fatherName"]["value"] == "RAMESH SHARMA"
    assert f["spouseName"]["value"] == "ARUN SHARMA"
    assert f["oldPassportNumber"]["value"] == "K1234567"
    assert f["oldPassportIssueDate"]["value"] == "2011-10-21"
    assert f["oldPassportPlace"]["value"] == "PUNE"
    assert all(v["needsReview"] for v in f.values())  # never auto-accepted
    # a back page never carries data-page fields
    assert not {"surname", "givenNames", "passportNumber", "dateOfBirth"} & set(f)
    assert out["warnings"] == []


def test_data_page_value_rows_keep_commas_and_complete_cut_off_words():
    mrz = {"surname": "SHARMA", "givenNames": "ANITA", "dateOfBirth": "1990-05-12"}
    rows = [
        {"y": 10, "text": "SHARMA", "conf": 90},
        {"y": 20, "text": "ANITA", "conf": 90},
        {"y": 30, "text": "12/05/1990 M", "conf": 90},
        {"y": 40, "text": "Place of Birth", "conf": 50},
        {"y": 50, "text": "KHALNE DHULE ,MAHARASHT", "conf": 54, "wideText": "KHALNE DHULE ,MAHARASHTRA", "wideConf": 60},
        {"y": 60, "text": "Place of Issue", "conf": 50},
        {"y": 70, "text": "PUNE", "conf": 90},
    ]
    out = pl.extract_bio_viz(rows, mrz)
    assert out["placeOfBirth"]["value"] == "KHALNE DHULE, MAHARASHTRA"
    assert out["placeOfIssue"]["value"] == "PUNE"


def test_place_labels_decide_which_row_is_which():
    mrz = {"surname": "SHARMA", "givenNames": "ANITA", "dateOfBirth": "1990-05-12"}
    rows = [
        {"y": 30, "text": "12/05/1990 M", "conf": 90},
        {"y": 40, "text": "WA Pi7/ Place of Birth GE", "conf": 60},
        {"y": 50, "text": "KUDAL,MAHARASHTRA os", "conf": 60},
    ]
    out = pl.extract_bio_viz(rows, mrz)
    assert out["placeOfBirth"]["value"] == "KUDAL, MAHARASHTRA"
    assert out["placeOfIssue"] is None


def _stacked_leaf():
    """Synthetic scan: white scanner background on the left and below, a black
    lid bar on top, and one booklet leaf with a blank page above a text page."""
    import cv2
    img = np.full((1400, 1000, 3), 255, np.uint8)
    img[0:6, :] = 0
    leaf = np.full((960, 640, 3), 246, np.uint8)       # pale paper
    leaf[470:490, :] = (205, 195, 190)                  # gutter band (uniform)
    cv2.putText(leaf, "FATHER NAME", (40, 560), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0, 0, 0), 5)
    cv2.putText(leaf, "MOTHER NAME", (40, 680), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0, 0, 0), 5)
    cv2.rectangle(leaf, (300, 505), (600, 530), (0, 0, 0), -1)  # barcode-like dark block just below the gutter
    img[20:980, 340:980] = leaf
    return img


def test_crop_back_page_keeps_text_half_and_drops_background():
    out, cropped = pl.crop_back_page(_stacked_leaf())
    assert cropped is True
    h, w = out.shape[:2]
    assert w < 700                      # white scanner margin removed
    assert 430 <= h <= 520              # only the lower (text) page is kept
    assert (out < 110).any()            # the text survived


def test_parse_back_page_flags_date_with_lost_leading_digit():
    text = "BHIKSHAPATHI CHINTALA\nUMA RANI CHINTALA\nH NO 12-11-337, WARASIGUDA\nSECUNDERABAD, HYDERABAD\nPIN:500061,TELANGANA,INDIA\nH0384593 4/08/2008 HYDERABAD\n"
    out = pl.parse_back_page(text)
    assert out["oldPassportDateCertain"] is False
    ok = pl.parse_back_page(text.replace(" 4/08/2008", " 14/08/2008"))
    assert ok["oldPassportDateCertain"] is True and ok["oldPassportIssueDate"] == "2008-08-14"
