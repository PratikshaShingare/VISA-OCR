"""Reading flight bookings for the Fill Forms page (flight_itinerary.py).
All bookings below are invented (project rule 11)."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import flight_itinerary as fi  # noqa: E402

# Same layout as an Amadeus / CheckMyTrip booking: summary table + detailed blocks.
CHECKMYTRIP = """Travel Summary
Traveler Mr Test Person
Date Dep. Time From To Flight No Terminal Airline Name
23DEC 2000 MUMBAI BOM TOKYO NRT NH830 2 ALL NIPPON AIRWAYS
24DEC 1315 TOKYO HND OSAKA KIX NH991 2 ALL NIPPON AIRWAYS
02JAN 1115 TOKYO NRT MUMBAI BOM NH829 1 ALL NIPPON AIRWAYS
Document Issue Date: 19 September
2026
Wednesday 23 December 2026
All Nippon Airways NH 830
Departure 23 December 20:00 Mumbai, (Chhatrapati S Maharaj) (+) Terminal: 2
Arrival 24 December 07:25 Tokyo, (Narita Intl) (+) Terminal: 1
Thursday 24 December 2026
All Nippon Airways NH 991
Departure 24 December 13:15 Tokyo, (Tokyo Intl Haneda) (+) Terminal: 2
Arrival 24 December 14:40 Osaka, (Kansai International) (+) Terminal: 1
Saturday 02 January 2027
All Nippon Airways NH 829
Departure 02 January 11:15 Tokyo, (Narita Intl) (+) Terminal: 1
Arrival 02 January 18:35 Mumbai, (Chhatrapati S Maharaj) (+) Terminal: 2
Sunday 01 August 2027
Miscellaneous
"""


def test_overnight_flight_uses_landing_date_and_skips_domestic_connection():
    r = fi.read_itinerary(CHECKMYTRIP, "Japan")
    assert r["status"] == "ok"
    assert r["arrivalDate"] == "2026-12-24"  # left Mumbai on the 23rd, landed in Tokyo on the 24th
    assert r["departureDate"] == "2027-01-02"  # across New Year
    assert r["lengthOfStay"] == "10 DAYS"
    assert r["portOfEntry"] == "TOKYO"
    assert r["airline"] == "ALL NIPPON AIRWAYS"
    assert [leg["role"] for leg in r["legs"]] == ["arrival", "domestic", "departure"]


def test_transit_through_another_country():
    text = """Thursday 10 April 2031
Thai Airways TG 318
Departure 10 April 23:55 Delhi, (Indira Gandhi Intl)
Arrival 11 April 05:40 Bangkok, (Suvarnabhumi)
Friday 11 April 2031
Thai Airways TG 682
Departure 11 April 07:45 Bangkok, (Suvarnabhumi)
Arrival 11 April 16:00 Osaka, (Kansai International)
Monday 21 April 2031
Thai Airways TG 673
Departure 21 April 10:30 Osaka, (Kansai International)
Arrival 21 April 14:30 Bangkok, (Suvarnabhumi)
Thai Airways TG 323
Departure 21 April 17:00 Bangkok, (Suvarnabhumi)
Arrival 21 April 20:00 Delhi, (Indira Gandhi Intl)
"""
    r = fi.read_itinerary(text, "Japan")
    assert r["arrivalDate"] == "2031-04-11"
    assert r["portOfEntry"] == "OSAKA"
    assert r["flightNo"] == "TG 682"
    assert r["airline"] == "THAI AIRWAYS"
    assert r["departureDate"] == "2031-04-21"
    assert r["lengthOfStay"] == "11 DAYS"


def test_summary_table_only_is_flagged_for_checking():
    text = "\n".join(line for line in CHECKMYTRIP.splitlines() if line[:2].isdigit() or "Issue Date" in line or line.strip() == "2026")
    r = fi.read_itinerary(text, "Japan")
    assert r["layout"] == "summary"
    assert r["arrivalDate"] == "2026-12-23"
    assert r["departureDate"] == "2027-01-02"
    assert any("lands the next day" in w for w in r["warnings"])


def test_ocr_text_with_cities_on_separate_lines_and_noise():
    # What OCR gives for a scan of the same booking: the city sits away from
    # the "Departure ... 20:00" line, bullets and stray letters in front.
    text = """23DEC 2000 MUMBAI BOM TOKYO NRT NH830 2 ALL NIPPON AIRWAYS
24DEC 1315 TOKYO HND OSAKA KIX NH991 2 ALL NIPPON AIRWAYS
O2JAN 1115 TOKYO NRT MUMBAI BOM — NH829 1 ALL NIPPON AIRWAYS
Wednesday 23 December 2026
> All Nippon Airways NH 830
Departure 23 December 20:00
Arrival 24 December 07:25
> All Nippon Airways NH 991
Departure 24 December 13:15
Arrival 24 December 14:40
Saturday 02 January 2027
x All Nippon Airways NH 829
Departure 02 January 11:15
joa Arrival 02 January 18:35
"""
    r = fi.read_itinerary(text, "Japan")
    assert r["arrivalDate"] == "2026-12-24"
    assert r["departureDate"] == "2027-01-02"
    assert r["portOfEntry"] == "TOKYO"


def test_booking_without_japan_is_refused():
    text = """Monday 05 May 2031
Emirates EK 501
Departure 05 May 04:00 Mumbai, (Chhatrapati S Maharaj)
Arrival 05 May 05:50 Dubai, (Dubai Intl)
"""
    r = fi.read_itinerary(text, "Japan")
    assert r["status"] == "no-entry"


def test_nothing_readable():
    assert fi.read_itinerary("hello world", "Japan")["status"] == "not-found"
    assert fi.read_itinerary(CHECKMYTRIP, "Atlantis")["status"] == "unsupported"


def test_endpoint(tmp_path):
    from fastapi.testclient import TestClient

    import app as app_module

    client = TestClient(app_module.app)
    res = client.post("/api/flight-itinerary/read", files={"file": ("x.txt", b"x", "text/plain")})
    assert res.status_code == 400


def test_singapore_arrival():
    text = """Friday 04 December 2026
Singapore Airlines SQ 423
Departure 03 December 23:35 Mumbai, (Chhatrapati S Maharaj)
Arrival 04 December 07:45 Singapore, (Changi)
Thursday 10 December 2026
Singapore Airlines SQ 422
Departure 10 December 20:40 Singapore, (Changi)
Arrival 10 December 22:30 Mumbai, (Chhatrapati S Maharaj)
"""
    r = fi.read_itinerary(text, "Singapore")
    assert r["arrivalDate"] == "2026-12-04"
    assert r["lengthOfStay"] == "7 DAYS"
    assert r["portOfEntry"] == "SINGAPORE"
