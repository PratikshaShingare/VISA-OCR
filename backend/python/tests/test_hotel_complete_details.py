"""
Filling a hotel's BLANK details from the internet when the voucher is generated
(hotel_voucher_ocr.complete_hotel_details + POST /api/documents/hotel-voucher/complete-details).
The lookup is replaced by a fake: these tests are about what is filled and what is
left alone, not about any real provider.
"""

import pytest
from fastapi.testclient import TestClient

import app as app_module
import hotel_voucher_ocr as h


def _fake_found(**over):
    base = {
        "status": "ok", "source": "google_places", "name": "Hotel Weisses Kreuz",
        "address": "Engelgasse 9, 9000 St. Gallen, Switzerland", "phone": "+41 71 223 28 43",
        "city": "St. Gallen", "country": "Switzerland",
    }
    base.update(over)
    return base


def test_only_blank_details_are_filled_and_typed_ones_kept():
    calls = []

    def lookup(name, address_hint="", city_hint="", country_hint=""):
        calls.append((name, address_hint, city_hint, country_hint))
        return _fake_found()

    out = h.complete_hotel_details(
        [{"id": "a", "hotelName": "Hotel Weisses Kreuz", "city": "Sankt Gallen", "address": "", "phone": ""}], lookup=lookup
    )
    r = out[0]
    assert r["id"] == "a" and r["status"] == "ok"
    assert set(r["filled"]) == {"address", "phone", "country"}  # the typed city is not replaced
    assert "city" not in r["fields"]
    assert r["fields"]["phone"] == "+41 71 223 28 43"
    assert calls[0][2] == "Sankt Gallen"  # the typed city guides the search


def test_a_complete_hotel_is_not_looked_up_at_all():
    def lookup(*a, **k):
        raise AssertionError("must not be called")

    out = h.complete_hotel_details(
        [{"id": "a", "hotelName": "Hotel X Zurich", "address": "x", "phone": "y", "city": "z", "country": "w"}], lookup=lookup
    )
    assert out[0]["status"] == "skipped" and out[0]["filled"] == []


def test_listing_name_replaces_the_ocr_name_only_when_asked():
    lookup = lambda *a, **k: _fake_found(name="B&B Hotel Milano Ornato")  # noqa: E731
    asked = h.complete_hotel_details([{"id": "a", "hotelName": "B and B Hotel Milano Ornat0", "useListingName": True}], lookup=lookup)[0]
    assert asked["hotelName"] == "B&B Hotel Milano Ornato" and asked["voucherHotelName"] == "B and B Hotel Milano Ornat0"
    kept = h.complete_hotel_details([{"id": "b", "hotelName": "My own wording", "address": "a", "phone": "p", "city": "c", "country": "k"}], lookup=lookup)[0]
    assert "hotelName" not in kept


def test_nothing_found_or_a_crash_is_reported_never_raised():
    nf = h.complete_hotel_details([{"id": "a", "hotelName": "Hotel Nowhere"}], lookup=lambda *a, **k: {"status": "not_found"})[0]
    assert nf["status"] == "not_found" and nf["fields"] == {}

    def boom(*a, **k):
        raise RuntimeError("network down")

    assert h.complete_hotel_details([{"id": "a", "hotelName": "Hotel Nowhere"}], lookup=boom)[0]["status"] == "unavailable"


def test_a_short_name_and_an_empty_list_are_skipped():
    assert h.complete_hotel_details([]) == []
    assert h.complete_hotel_details([{"id": "a", "hotelName": "H"}], lookup=lambda *a, **k: _fake_found())[0]["status"] == "skipped"


def test_order_and_ids_follow_the_request():
    names = {"Hotel One Zurich": "+1", "Hotel Two Zurich": "+2"}
    lookup = lambda name, **k: _fake_found(phone=names[name])  # noqa: E731
    out = h.complete_hotel_details(
        [{"id": "x", "hotelName": "Hotel One Zurich"}, {"id": "y", "hotelName": "Hotel Two Zurich"}], lookup=lookup
    )
    assert [r["id"] for r in out] == ["x", "y"] and [r["fields"]["phone"] for r in out] == ["+1", "+2"]


def test_endpoint_returns_the_filled_details(monkeypatch):
    import hotel_lookup

    monkeypatch.setattr(hotel_lookup, "lookup_hotel", lambda *a, **k: _fake_found())
    client = TestClient(app_module.app)
    res = client.post(
        "/api/documents/hotel-voucher/complete-details",
        json={"hotels": [{"id": "h1", "hotelName": "Hotel Weisses Kreuz"}, {"id": "h2", "hotelName": ""}]},
    )
    assert res.status_code == 200
    r1, r2 = res.json()["results"]
    assert r1["id"] == "h1" and r1["fields"]["city"] == "St. Gallen" and r2["status"] == "skipped"


def test_endpoint_refuses_an_absurd_number_of_hotels():
    client = TestClient(app_module.app)
    res = client.post("/api/documents/hotel-voucher/complete-details", json={"hotels": [{"hotelName": "Hotel Zurich"}] * 31})
    assert res.status_code == 400
