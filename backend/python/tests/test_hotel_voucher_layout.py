"""
Layout-aware hotel voucher reading (hotel_voucher_layout.py + the wiring in
hotel_voucher_ocr.py) for the two voucher layouts the agency receives:

  * "tbo"             — header (confirmation no, hotel name + address, Check In /
                        Check Out / No. of Nights), Room Details, Guest Details
                        with a "(Lead Guest)" marker, support/price boxes on the
                        right;
  * "booking_summary" — a "Confirmed Booking" page: Booking Summary panel on the
                        right (name, address, Travel Dates, Room Type(s), Total
                        Rooms / Adult(s)) and labelled boxes on the left (Booking
                        Id, Leader, Guest Details).

The vouchers are RENDERED HERE from invented data (project rule 11 — no real
client vouchers in the repo) in the same arrangement as the real pages, then
run through the real OCR pipeline.
"""

import shutil

import pytest
from PIL import Image, ImageDraw, ImageFont

import hotel_lookup as hl
import hotel_voucher_layout as layout
import hotel_voucher_ocr as h

pytestmark = pytest.mark.skipif(shutil.which("tesseract") is None, reason="Tesseract OCR is not installed")

_FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"


def _font(size, bold=False):
    try:
        return ImageFont.truetype(_BOLD if bold else _FONT, size)
    except OSError:  # pragma: no cover - font missing on an unusual machine
        return ImageFont.load_default()


def _tbo_voucher(rooms, hotel="Aurora Bay Palace", address="12 Sample Street, Testville", code="TBZZ9Q4K2M"):
    """rooms: [(room type, [guest names], ...)] — the first guest of room 1 is the lead."""
    img = Image.new("RGB", (1400, 560 + 190 * len(rooms)), "white")
    d = ImageDraw.Draw(img)
    f, fb = _font(14), _font(14, True)
    d.text((40, 20), "(HTL)SAMPLE TRAVELS PRIVATE LIMITED (Mumbai)", font=fb, fill="black")
    d.text((1040, 20), f"TBO Confirmation No : {code}", font=f, fill="black")
    d.text((40, 44), "1 EXAMPLE GARDEN", font=fb, fill="black")
    d.text((40, 66), "SAMPLE ROAD", font=fb, fill="black")
    d.text((200, 130), hotel, font=_font(16), fill=(30, 90, 170))
    d.text((200, 162), address, font=f, fill="black")
    d.text((880, 130), "Check In : 07-Oct-2027", font=f, fill="black")
    d.text((880, 150), "Check Out : 12-Oct-2027", font=f, fill="black")
    d.text((960, 170), "No. of Nights: 5", font=f, fill="black")
    d.text((1120, 230), "Last Cancellation Date : 04-Oct-2027", font=f, fill="black")
    d.text((40, 290), "Room Details", font=_font(16, True), fill=(30, 90, 170))
    d.text((1080, 300), "Need Modification in Booking?", font=fb, fill=(30, 90, 170))
    d.text((1080, 330), "Manage all post-booking requests from one place.", font=_font(11), fill="gray")
    y = 340
    for i, (rtype, guests) in enumerate(rooms, 1):
        d.text((40, y), f"Room {i}", font=f, fill="black")
        d.text((130, y), rtype, font=f, fill="black")
        d.text((960, y), f"{len(guests)} Adult(s)", font=f, fill="black")
        d.text((130, y + 22), "Incl:RoomOnly", font=f, fill="black")
        y += 70
    y += 20
    d.text((40, y), "Guest Details", font=_font(16, True), fill=(30, 90, 170))
    d.text((1080, y), "Raised Request", font=fb, fill=(30, 90, 170))
    y += 50
    for i, (rtype, guests) in enumerate(rooms, 1):
        d.text((40, y), f"Room {i}", font=fb, fill="black")
        d.text((900, y), "Hide Pax Details", font=f, fill=(200, 140, 0))
        y += 28
        for k, name in enumerate(guests, 1):
            lead = " (Lead Guest)" if (i == 1 and k == 1) else ""
            d.text((40, y), f"Adult {k}{lead}", font=f, fill=(30, 90, 170))
            d.text((250, y), name, font=fb, fill="black")
            if i == 1 and k == 1:
                d.text((1080, y), "No tickets found for the given booking", font=f, fill=(30, 90, 170))
            y += 40
        y += 12
    d.text((1080, 600), "Sale Summary", font=_font(16), fill="black")
    d.text((40, y + 10), "Cancellation Charges", font=_font(16, True), fill=(30, 90, 170))
    return img


def _booking_summary_voucher(hotel="Lakeside Test Residence", address="5 Example Lane, Sample District, Testville"):
    img = Image.new("RGB", (1360, 640), "white")
    d = ImageDraw.Draw(img)
    f, fb = _font(11), _font(11, True)
    d.text((289, 28), "Confirmed Booking", font=_font(24, True), fill=(50, 20, 120))
    d.text((289, 80), "Pax Summary", font=_font(14, True), fill=(50, 20, 120))
    d.text((780, 80), "Booking Summary", font=_font(14, True), fill=(50, 20, 120))
    d.text((819, 104), hotel, font=_font(15, True), fill="black")
    d.text((819, 142), address, font=_font(10), fill="black")
    d.text((779, 195), "Travel Dates", font=fb, fill=(50, 20, 120))
    d.text((811, 217), "Check-in", font=fb, fill="black")
    d.text((877, 217), "Check-out", font=fb, fill="black")
    d.text((1009, 217), "Total Nights", font=fb, fill="black")
    d.text((811, 232), "24/12/2027", font=f, fill="black")
    d.text((877, 232), "27/12/2027", font=f, fill="black")
    d.text((1012, 232), "3", font=f, fill="black")
    d.text((779, 278), "Room Type(s)", font=fb, fill=(50, 20, 120))
    for i, y in enumerate((311, 356)):
        d.text((779, y), "Superior Room", font=f, fill="black")
        d.text((800, y + 14), "Breakfast", font=f, fill="black")
    d.text((779, 472), "Total Rooms", font=fb, fill=(50, 20, 120))
    d.text((875, 472), "Total Adult(s)", font=fb, fill=(50, 20, 120))
    d.text((972, 472), "Total Children", font=fb, fill=(50, 20, 120))
    d.text((781, 490), "2", font=f, fill="black")
    d.text((877, 490), "4", font=f, fill="black")
    d.text((974, 490), "0", font=f, fill="black")
    d.text((298, 358), "Booking Id", font=fb, fill="black")
    d.text((451, 358), "Leader", font=fb, fill="black")
    d.text((603, 358), "Agent Ref.No", font=fb, fill="black")
    for x in (298, 451, 603):
        d.rectangle([x, 372, x + 122, 400], outline=(50, 20, 120))
    d.text((306, 380), "RQTEST48K2", font=f, fill="black")
    d.text((460, 380), "JOHN TESTER", font=f, fill="black")
    d.text((611, 380), "AGENT", font=f, fill="black")
    d.text((298, 426), "Booking Status", font=fb, fill="black")
    d.text((451, 426), "Guest Details", font=fb, fill="black")
    d.text((603, 426), "Voucher No", font=fb, fill="black")
    y = 444
    for name in ("Mr. JOHN TESTER", "Mrs. JANE TESTER", "Mstr. JACK TESTER", "Ms. JILL TESTER"):
        d.rectangle([451, y, 573, y + 40], outline=(50, 20, 120))
        d.text((462, y + 6), name.split(" ", 1)[0] + " " + name.split(" ", 1)[1].rsplit(" ", 1)[0], font=f, fill="black")
        d.text((462, y + 22), name.rsplit(" ", 1)[1], font=f, fill="black")
        y += 52
    d.text((298, 444), "Confirmed", font=f, fill="black")
    d.text((298, 494), "Booking Date", font=fb, fill="black")
    d.text((603, 570), "Destination", font=fb, fill="black")
    d.text((611, 590), "Testville City,", font=f, fill="black")
    return img


# ---------------------------------------------------------------------------
# full pipeline on rendered vouchers
# ---------------------------------------------------------------------------


def test_tbo_voucher_single_room():
    res = h.process_hotel_voucher_page(_tbo_voucher([("Deluxe Test Room, 1 King", ["Mr. Alpha Tester", "Mrs. Beta Tester", "Miss. Gamma Tester"])]))
    f = res["fields"]
    assert res["voucherType"] == "tbo"
    assert f["hotelName"] == "Aurora Bay Palace"
    assert f["confirmationNumber"] == "TBZZ9Q4K2M"
    assert f["checkIn"] == "2027-10-07" and f["checkOut"] == "2027-10-12"
    assert res["nights"] == 5
    assert f["roomType"] == "Deluxe Test Room, 1 King"
    assert f["noOfRooms"] == "1" and f["noOfAdults"] == "3"
    assert f["leadGuestName"] == "Mr. Alpha Tester"
    # the lead guest has their own field and is never repeated in the other-guest list
    assert res["guestNames"] == ["Mrs. Beta Tester", "Miss. Gamma Tester"]
    assert res["allGuests"] == ["Mr. Alpha Tester", "Mrs. Beta Tester", "Miss. Gamma Tester"]
    assert "Sample Street" in res["voucherAddress"]
    # nothing from the support / price boxes leaks into a guest name
    assert not any("Need" in g or "tickets" in g.lower() for g in res["allGuests"])


def test_tbo_voucher_two_rooms_sums_adults_and_keeps_every_guest_once():
    res = h.process_hotel_voucher_page(
        _tbo_voucher([("Standard Queen Room", ["Mr. Alpha Tester", "Mrs. Beta Tester"]), ("Standard Queen Room", ["Mr. Delta Tester", "Mr. Echo Tester"])])
    )
    f = res["fields"]
    assert f["noOfRooms"] == "2" and f["noOfAdults"] == "4"
    assert f["roomType"] == "Standard Queen Room"  # two rooms of one type read as one type
    assert res["allGuests"] == ["Mr. Alpha Tester", "Mrs. Beta Tester", "Mr. Delta Tester", "Mr. Echo Tester"]
    assert len({layout.name_key(g) for g in res["allGuests"]}) == 4


def test_booking_summary_voucher():
    res = h.process_hotel_voucher_page(_booking_summary_voucher())
    f = res["fields"]
    assert res["voucherType"] == "booking_summary"
    assert f["hotelName"] == "Lakeside Test Residence"  # the line under "Booking Summary"
    assert f["checkIn"] == "2027-12-24" and f["checkOut"] == "2027-12-27"
    assert res["nights"] == 3
    assert f["noOfRooms"] == "2" and f["noOfAdults"] == "4"
    assert f["roomType"] == "Superior Room"  # two room lines of one type; the meal lines are not room types
    assert f["leadGuestName"] == "Mr. JOHN TESTER"  # "Leader", with the title the guest list spells
    assert res["allGuests"][0] == "Mr. JOHN TESTER"
    assert [layout.name_key(g) for g in res["allGuests"]].count("johntester") == 1  # the leader is in the list once
    assert len(res["allGuests"]) == 4
    assert f["city"] == "Testville City"  # "Destination", until an online lookup gives its own
    assert "Sample District" in res["voucherAddress"]


def test_unrecognised_layout_falls_back_to_generic_reading():
    img = Image.new("RGB", (900, 300), "white")
    d = ImageDraw.Draw(img)
    d.text((30, 30), "Hotel Name: Plain Sample Inn", font=_font(18), fill="black")
    d.text((30, 70), "Check-in: 12/01/2027", font=_font(18), fill="black")
    d.text((30, 110), "Check-out: 15/01/2027", font=_font(18), fill="black")
    res = h.process_hotel_voucher_page(img)
    assert res["voucherType"] == "unknown"
    assert res["fields"]["checkIn"] == "2027-01-12"


# ---------------------------------------------------------------------------
# small pure helpers
# ---------------------------------------------------------------------------


def test_parse_date_reads_both_voucher_styles_day_first():
    assert layout.parse_date("Check In : 07-Oct-2026") == "2026-10-07"
    assert layout.parse_date("24/12/2026") == "2026-12-24"
    assert layout.parse_date("no date here") is None
    assert layout.parse_date("31/02/2026") is None  # impossible date: not guessed


def test_name_dedupe_ignores_titles_and_keeps_the_titled_spelling():
    names = []
    layout.add_unique_name(names, "SAURABH SUNIL POL")
    layout.add_unique_name(names, "Mr. SAURABH SUNIL POL")
    layout.add_unique_name(names, "mr saurabh sunil pol")
    layout.add_unique_name(names, "Ms. SPOORTY POL")
    assert names == ["Mr. SAURABH SUNIL POL", "Ms. SPOORTY POL"]


def test_hotel_name_alt_text_of_a_broken_photo_is_not_repeated():
    row = [{"text": t, "left": i * 30, "top": 0, "width": 25, "height": 10, "conf": 90}
           for i, t in enumerate("Novotel Prague Square Novotel Prague Square".split())]
    assert layout._clean_hotel_name_tokens(row) == "Novotel Prague Square"
    broken = [{"text": t, "left": i * 30, "top": 0, "width": 25, "height": 10, "conf": 90}
              for i, t in enumerate("Prague Square Novotel Prague Square".split())]  # first alt word eaten by the broken-image icon
    assert layout._clean_hotel_name_tokens(broken) == "Novotel Prague Square"


# ---------------------------------------------------------------------------
# address cross-check against Google (network mocked)
# ---------------------------------------------------------------------------


def _result(name="Aurora Bay Palace", address="12 Sample Street, Testville"):
    return {"isBlank": False, "voucherAddress": address, "fields": {"hotelName": name, "address": address, "city": None, "country": None, "phone": None}, "warnings": []}


def test_google_address_that_matches_the_voucher_is_used():
    res = h.enrich_with_hotel_lookup(
        _result(),
        lookup=lambda *a, **k: {"status": "ok", "source": "google_places", "name": "Aurora Bay Palace", "address": "12 Sample Street, Testville 400001, India",
                                "phone": "+91 22 0000 0000", "city": "Testville", "country": "India",
                                "addressCheck": hl.address_check("12 Sample Street, Testville", "12 Sample Street, Testville 400001, India", "Aurora Bay Palace")},
    )
    assert res["lookup"]["addressCheck"]["status"] == "match"
    assert res["fields"]["phone"] == "+91 22 0000 0000"
    assert res["fields"]["address"].startswith("12 Sample Street, Testville 400001")
    assert res["voucherAddress"] == "12 Sample Street, Testville"  # what the voucher printed stays available


def test_online_details_are_used_even_when_the_address_differs_from_the_voucher():
    other = {"status": "ok", "source": "google_places", "name": "Aurora Bay Palace Hotel", "address": "99 Far Away Avenue, Elsewhere", "phone": "+33 1 00 00 00 00",
             "city": "Elsewhere", "country": "France",
             "addressCheck": hl.address_check("12 Sample Street, Testville", "99 Far Away Avenue, Elsewhere", "Aurora Bay Palace")}
    res = h.enrich_with_hotel_lookup(_result(), lookup=lambda *a, **k: dict(other))
    assert res["lookup"]["status"] == "address_mismatch"
    # staff asked for the internet's details to win, with a "please compare" warning
    assert res["fields"]["address"] == "99 Far Away Avenue, Elsewhere"
    assert res["fields"]["phone"] == "+33 1 00 00 00 00"
    assert res["fields"]["city"] == "Elsewhere"
    assert res["fields"]["hotelName"] == "Aurora Bay Palace Hotel"  # the listing's own name replaces the voucher's wording
    assert res["voucherHotelName"] == "Aurora Bay Palace"
    assert any("differ from the address printed" in w for w in res["warnings"])


def test_without_a_printed_address_the_lookup_is_used_but_marked_unverified():
    r = _result(address="")
    res = h.enrich_with_hotel_lookup(
        r, lookup=lambda *a, **k: {"status": "ok", "source": "openstreetmap", "name": "Aurora Bay Palace", "address": "1 Road, Town", "phone": "", "city": "Town", "country": "X",
                                   "addressCheck": hl.address_check("", "1 Road, Town", "Aurora Bay Palace")})
    assert res["lookup"]["addressCheck"]["status"] == "unverified"
    assert res["fields"]["city"] == "Town"


def test_lookup_prefers_the_candidate_whose_address_agrees_with_the_voucher(monkeypatch):
    monkeypatch.setenv("GOOGLE_PLACES_API_KEY", "k")

    class R:
        status_code = 200

        def json(self):
            return {"places": [
                {"displayName": {"text": "Aurora Bay Palace"}, "formattedAddress": "1 Other Road, Elsewhere", "internationalPhoneNumber": "+1 000", "addressComponents": []},
                {"displayName": {"text": "Aurora Bay Palace"}, "formattedAddress": "12 Sample Street, Testville", "internationalPhoneNumber": "+91 111", "addressComponents": []},
            ]}

    monkeypatch.setattr(hl.requests, "post", lambda *a, **k: R())
    found = hl.lookup_hotel("Aurora Bay Palace", address_hint="12 Sample Street, Testville")
    assert found["phone"] == "+91 111"
    assert found["addressCheck"]["status"] == "match"


def test_address_check_ignores_accents_and_filler_words():
    assert hl.address_check("242 Tran Binh Trong,District 5,Ho Chi Minh City", "242 Trần Bình Trọng, Quận 5, Hồ Chí Minh, Vietnam", "Equatorial Ho Chi Minh City")["status"] == "match"
    assert hl.address_check("Katerinska 38, Nove Mesto", "1 Other Street, Paris", "Novotel")["status"] == "mismatch"
