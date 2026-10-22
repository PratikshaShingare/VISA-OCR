"""
Hotel voucher field extraction (hotel_voucher_ocr.extract_hotel_voucher_fields)
on the OCR text of differently-laid-out vouchers. Vouchers vary per client and
per booking site, so each case below is a different style; all names, codes and
addresses are synthetic (project rule 11).
"""

import hotel_voucher_ocr as h

PORTAL_STYLE = """\
= Booking Details <<BackToQueue
(HTL)SAMPLE TRAVELS PRIVATE LIMITED (Mumbai) TBO Confirmation No : ABC4D53X7Z
1 EXAMPLE GARDEN Add Another item
S Mercure Sample Coast Resort vr vr vr ve Check In : 08-Dec-2026
64 Palm Meadows Dr, Carrara QLD 4211, No. of Nights: 1
Last Cancellation Date : 06-Dec-2026
Room 1 Classic King Room 21 Adult(s) -
Room1 Show Pax Details.
Adult 1 (Lead Guest) Mr. Test Person Sample No tickets found for the given booking
Check Out : 09-Dec-2026
Need Further Help?
callus at: 0124-0000000
Room 1: Classic King Room
Classic King Room
07-Dec-2026 07-Dec-2026 213,975
"""

LABELLED_STYLE = """\
HOTEL BOOKING CONFIRMATION
Hotel Name: Grand Test Palace
Hotel Address: 12 Lake Road, Testville
City: Testville
Country: Switzerland
Confirmation No: GTP-99120
Lead Guest: Mrs. Asha Example
Guest 2 Name: Mr. Ravi Example
Room Type: Deluxe Twin
No. of Rooms: 2
No. of Adults: 3
No. of Children: 1
Check-in: 12/01/2027
Check-out: 15/01/2027
Phone: +41 22 555 0100
"""


def test_portal_style_voucher():
    r = h.extract_hotel_voucher_fields(PORTAL_STYLE)
    f = r["fields"]
    assert f["hotelName"] == "Mercure Sample Coast Resort"  # the scan-noise letter and the agency line are not the hotel
    assert f["confirmationNumber"] == "ABC4D53X7Z"
    assert f["checkIn"] == "2026-12-08" and f["checkOut"] == "2026-12-09"
    assert f["roomType"] == "Classic King Room"
    assert f["noOfRooms"] == "1"
    assert f["noOfAdults"] == "1", "'21 Adult(s)' is an icon read as a digit; the one 'Adult 1' guest row decides"
    assert f["leadGuestName"] == "Mr. Test Person Sample"
    assert f["address"] == "64 Palm Meadows Dr, Carrara QLD 4211"
    assert f["phone"] is None, "an OTA support line is not the hotel's phone"
    assert r["guestNames"] == ["Mr. Test Person Sample"]


def test_labelled_style_voucher_still_works():
    r = h.extract_hotel_voucher_fields(LABELLED_STYLE)
    f = r["fields"]
    assert f["hotelName"] == "Grand Test Palace"
    assert f["address"] == "12 Lake Road, Testville"
    assert f["city"] == "Testville" and f["country"] == "Switzerland"
    assert f["confirmationNumber"] == "GTP-99120"
    assert f["leadGuestName"] == "Mrs. Asha Example"
    assert f["roomType"] == "Deluxe Twin"
    assert f["noOfRooms"] == "2" and f["noOfAdults"] == "3" and f["noOfChildren"] == "1"
    assert f["checkIn"] == "2027-01-12" and f["checkOut"] == "2027-01-15"
    assert f["phone"] == "+41 22 555 0100"
    assert "Mr. Ravi Example" in " ".join(r["guestNames"]) or "Ravi Example" in " ".join(r["guestNames"])


def test_nothing_is_invented_when_the_text_has_no_voucher_fields():
    r = h.extract_hotel_voucher_fields("Invoice 123\nThank you for shopping with us\nTotal 55.00")
    assert not any(r["fields"].values()) and r["guestNames"] == []


def test_several_rooms_are_counted_and_adults_summed():
    text = "Room 1 Standard Room 2 Adult(s)\nRoom 2 Standard Room 1 Adult(s)\nAdult 1 (Lead Guest) Mr. A Test\n"
    f = h.extract_hotel_voucher_fields(text)["fields"]
    assert f["noOfRooms"] == "2" and f["noOfAdults"] == "3"


def test_a_room_number_on_the_next_line_is_not_a_room_count():
    f = h.extract_hotel_voucher_fields("Classic King Room\n07-Dec-2026 07-Dec-2026\n")["fields"]
    assert f["noOfRooms"] is None


def test_a_number_on_the_previous_line_is_not_an_occupant_count():
    f = h.extract_hotel_voucher_fields("Rooms: 1\nAdults: 2\nChildren: 0\n")["fields"]
    assert f["noOfRooms"] == "1" and f["noOfAdults"] == "2" and f["noOfChildren"] == "0"


# ---------------------------------------------------------------------------
# Several rooms on one voucher, nights, and the online hotel lookup merge.
# ---------------------------------------------------------------------------

TWO_ROOMS = """\
TBO Confirmation No : TBO9X8Y7Z
Sample Palace Hotel Check In : 08-Dec-2026
Check Out : 11-Dec-2026
No. of Nights: 3
Room 1 Deluxe King Room <2 Adult(s)
Room 2 Twin Garden Room 1 Adult(s) 1 Child(ren)
Guest Details
Room 1 Show Pax Details
Adult 1 (Lead Guest) Mr. Test Person Sample
Adult 2 Mrs. Test Spouse Sample
Room 2 Show Pax Details
Adult 1 Mr. Other Traveller Example
Child 1 Mstr. Small Kid Example
"""


def test_two_rooms_are_read_room_by_room():
    r = h.extract_hotel_voucher_fields(TWO_ROOMS)
    f = r["fields"]
    assert f["roomType"] == "Deluxe King Room, Twin Garden Room"
    assert f["noOfRooms"] == "2"
    assert f["noOfAdults"] == "3"
    assert f["noOfChildren"] == "1"
    assert f["leadGuestName"] == "Mr. Test Person Sample"
    assert [x["guests"] for x in r["rooms"]] == [
        ["Mr. Test Person Sample", "Mrs. Test Spouse Sample"],
        ["Mr. Other Traveller Example", "Mstr. Small Kid Example"],
    ]
    assert r["nights"] == 3


def test_same_room_type_in_two_rooms_is_listed_once():
    text = TWO_ROOMS.replace("Twin Garden Room", "Deluxe King Room")
    r = h.extract_hotel_voucher_fields(text)
    assert r["fields"]["roomType"] == "Deluxe King Room"
    assert r["fields"]["noOfRooms"] == "2"


def test_adults_fall_back_to_guest_rows_when_the_room_row_has_no_count():
    text = TWO_ROOMS.replace("<2 Adult(s)", "").replace("1 Adult(s) 1 Child(ren)", "")
    r = h.extract_hotel_voucher_fields(text)
    assert r["fields"]["noOfAdults"] == "3"
    assert r["fields"]["noOfChildren"] == "1"


def test_merge_keeps_every_room_across_readings():
    first = h.extract_hotel_voucher_fields("Room 1 Deluxe King Room <2 Adult(s)\n")
    second = h.extract_hotel_voucher_fields(TWO_ROOMS)
    merged = h._merge_extractions([first, second])
    assert merged["fields"]["noOfRooms"] == "2"
    assert merged["nights"] == 3


def test_nights_mismatch_is_flagged_and_match_is_not():
    assert h._nights_warnings(3, "2026-12-08", "2026-12-11") == []
    msg = h._nights_warnings(2, "2026-12-08", "2026-12-11")
    assert len(msg) == 1 and "2 night" in msg[0] and "3" in msg[0]
    assert h._nights_warnings(None, "2026-12-08", "2026-12-11") == []


def test_lookup_fills_address_phone_city_and_keeps_ocr_values_when_nothing_found():
    base = lambda: {"fields": {"hotelName": "Sample Palace Hotel", "address": "1 Voucher Rd", "phone": None, "city": None, "country": None}}
    found = {"status": "ok", "source": "google_places", "name": "Sample Palace Hotel", "address": "1 Voucher Road, Testville 400001, India", "phone": "+91 22 0000 0000", "city": "Testville", "country": "India"}
    res = h.enrich_with_hotel_lookup(base(), lookup=lambda *a, **k: found)
    assert res["fields"]["address"] == found["address"]
    assert res["fields"]["phone"] == "+91 22 0000 0000"
    assert res["fields"]["city"] == "Testville"
    assert res["fields"]["country"] == "India"
    assert res["lookup"]["source"] == "google_places"

    res = h.enrich_with_hotel_lookup(base(), lookup=lambda *a, **k: {"status": "not_found", "source": "google_places"})
    assert res["fields"]["address"] == "1 Voucher Rd" and res["fields"]["city"] is None
    assert res["lookup"]["status"] == "not_found"


def test_lookup_is_skipped_without_a_hotel_name():
    called = []
    res = h.enrich_with_hotel_lookup({"fields": {"hotelName": None}}, lookup=lambda *a, **k: called.append(1))
    assert not called and res["lookup"]["status"] == "skipped"
