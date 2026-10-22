"""Cross-checks layered on the MRZ read (passport_crosscheck.py). Synthetic
data only — no real passport details."""
import passport_crosscheck as pc
import ocr_runner as r
from test_mrz_reader import build_td3


def _refine(l1, l2, text=""):
    parsed = r.parse_mrz_td3(l1, l2)
    return pc.refine_mrz(parsed, text, r.parse_mrz_td3)


def test_clean_mrz_is_left_untouched():
    l1, l2 = build_td3()
    parsed, repairs = _refine(l1, l2)
    assert repairs == []
    assert parsed["surname"] == "SHARMA" and parsed["givenNames"] == "ANITA"


def test_filler_run_read_as_letters_is_trimmed_and_reported():
    l1, l2 = build_td3()
    bad = "P<INDSHARMA<<ANITAKCKCKCKCKCKCKCKCKCKCKCKCKCKCKCKC"[:44]
    parsed, repairs = _refine(bad, l2)
    assert parsed["givenNames"] == "ANITA"
    assert any(x["field"] == "givenNames" for x in repairs)


def test_a_real_name_ending_in_filler_like_letters_is_not_cut():
    l1, l2 = build_td3(given="ALEXIS")
    parsed, repairs = _refine(l1, l2)
    assert parsed["givenNames"] == "ALEXIS"
    assert repairs == []


def test_impossible_document_code_is_repaired():
    l1, l2 = build_td3()
    bad = "PL" + l1[2:]
    parsed, repairs = _refine(bad, l2)
    assert parsed["line1"].startswith("P<")
    assert any(x["field"] == "documentType" for x in repairs)


def test_invalid_nationality_takes_the_valid_issuing_state():
    l1, l2 = build_td3()
    bad = l2[:10] + "SGB" + l2[13:]
    parsed, repairs = _refine(l1, bad)
    assert parsed["nationality"] == "IND"
    assert parsed["valid"] == r.parse_mrz_td3(l1, l2)["valid"]  # check digits untouched
    assert any(x["field"] == "nationality" for x in repairs)


def test_valid_but_different_nationality_is_not_overridden():
    l1, l2 = build_td3(nat="GBR")
    parsed, repairs = _refine(l1, l2)
    assert parsed["nationality"] == "GBR"
    assert repairs == []


def test_visible_text_drops_the_mrz_lines():
    l1, l2 = build_td3()
    text = f"Surname\nSHARMA\n{l1}\n{l2}"
    vis = pc.visible_text(text)
    assert "SHARMA" in vis and "<<" not in vis and "P9988776" not in vis


def test_dates_numeric_and_named_formats_are_read():
    dates = pc.viz_dates("Date of Birth 12/05/1990 Date of Issue 13 MAR 2025 Expiry 12-03-2035")
    assert dates == ["1990-05-12", "2025-03-13", "2035-03-12"]


def test_issue_date_by_elimination_needs_exactly_one_candidate():
    dates = ["1990-05-12", "2025-03-13", "2035-03-12"]
    assert pc.derive_issue_date(dates, "1990-05-12", "2035-03-12") == "2025-03-13"
    assert pc.derive_issue_date(dates + ["2026-01-01"], "1990-05-12", "2035-03-12") is None
    assert pc.derive_issue_date(["1990-05-12", "2035-03-12"], "1990-05-12", "2035-03-12") is None


def test_confirmations_match_printed_values_but_not_the_mrz_itself():
    l1, l2 = build_td3()
    parsed = r.parse_mrz_td3(l1, l2)
    page = f"Surname\nSHARMA\nGiven Names\nANITA\nDate of birth 12/05/1990\n{l1}\n{l2}"
    c = pc.confirmations(parsed, page)
    assert c["surname"] and c["givenNames"] and c["dateOfBirth"]
    assert not c["passportNumber"]  # the number only occurs inside the MRZ lines
    assert c["suspiciousNameTokens"] == []


def test_garbled_name_is_flagged_suspicious():
    l1, l2 = build_td3(given="KVIGWMALKCGGGGGGGG")
    c = pc.confirmations(r.parse_mrz_td3(l1, l2), "")
    assert c["suspiciousNameTokens"]


def test_name_not_on_the_page_is_flagged_for_review_unless_read_cleanly():
    l1, l2 = build_td3()
    parsed = r.parse_mrz_td3(l1, l2)
    fields = r.extract_passport_fields("", parsed, mrz_engine_confidence="medium", mrz_repair_count=2)
    assert fields["surname"]["needsReview"] is True
    fields = r.extract_passport_fields("", parsed, mrz_engine_confidence="high", mrz_repair_count=0)
    assert fields["surname"]["needsReview"] is False
    confirmed = r.extract_passport_fields("SHARMA\nANITA", parsed, mrz_engine_confidence="medium", mrz_repair_count=2)
    assert confirmed["surname"]["needsReview"] is False and confirmed["surname"]["confidence"] >= 0.95


# ----------------------------------------------------------- repairs backed by the printed page (sync27)


def test_passport_number_with_interior_filler_is_repaired_from_the_printed_number():
    from ocr_runner import compute_icao_check_digit

    # "1<816321" passes its check digit but the page prints C1816321.
    assert str(compute_icao_check_digit("1<816321<")) == str(compute_icao_check_digit("C1816321<"))
    fixed = pc._passport_number_from_page("1<816321<", "0", "PASSPORT NO C 1816321")
    assert fixed == "C1816321<"


def test_printed_number_that_fails_the_check_digit_is_not_used():
    assert pc._passport_number_from_page("1<816321<", "0", "NO C1816322") is None


def test_one_letter_surname_repeating_the_country_code_is_dropped():
    name, notes = pc._clean_name_field("D<<CHAND<PASHA<<<<<<<<<<<<<<<<<<<<<<<<<<", ["CHAND", "PASHA"], "IND")
    assert name.startswith("<<CHAND<PASHA")
    assert any(n["field"] == "surname" for n in notes)


def test_a_stray_extra_letter_is_removed_when_the_printed_name_shows_the_word():
    name, notes = pc._clean_name_field("SHARMA<<ANITA<KPRIYA<<<<<<<<<<<<<<<<<<<<<", ["SHARMA", "ANITA", "PRIYA"], "IND")
    assert name.startswith("SHARMA<<ANITA<PRIYA")
    assert any(n["to"] == "PRIYA" for n in notes)


def test_a_real_one_letter_surname_is_kept_when_it_is_not_the_country_code_letter():
    name, _ = pc._clean_name_field("X<<ANITA<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<", ["ANITA"], "IND")
    assert name.startswith("X<<ANITA")


def test_filler_misread_as_repeated_letters_is_removed_even_without_printed_confirmation():
    name, notes = pc._clean_name_field("SHARMA<<ANITA<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<"[:39].replace("ANITA<<", "ANITAKKK<KKK<"), [], "IND")
    assert name.startswith("SHARMA<<ANITA<<")
    assert "KKK" not in name


def test_a_repeated_letter_filler_token_after_a_real_name_is_dropped():
    name, _ = pc._clean_name_field("SHARMA<<ANITA<PRIYA<KK<<<<<<<<<<<<<<<<<<<<<", [], "IND")
    assert name.startswith("SHARMA<<ANITA<PRIYA<<")
