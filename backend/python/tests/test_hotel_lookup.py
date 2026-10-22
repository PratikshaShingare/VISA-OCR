"""
hotel_lookup.lookup_hotel with the network mocked: Google Places first, then
OpenStreetMap, never raising, never accepting a result for a different hotel.
All names/addresses are synthetic.
"""

import pytest

import hotel_lookup as hl


class FakeResp:
    def __init__(self, status=200, data=None):
        self.status_code = status
        self._data = data

    def json(self):
        return self._data


GOOGLE_OK = {
    "places": [
        {
            "displayName": {"text": "Sample Palace Hotel"},
            "formattedAddress": "1 Test Road, Testville 400001, India",
            "internationalPhoneNumber": "+91 22 0000 0000",
            "addressComponents": [
                {"longText": "Testville", "types": ["locality"]},
                {"longText": "India", "types": ["country"]},
            ],
        }
    ]
}
OSM_OK = [
    {
        "name": "Sample Palace Hotel",
        "display_name": "Sample Palace Hotel, Testville",
        "address": {"road": "Test Road", "house_number": "1", "city": "Testville", "postcode": "400001", "country": "India"},
        "extratags": {},
    }
]


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr(hl.time, "sleep", lambda s: None)
    monkeypatch.delenv("GOOGLE_PLACES_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_VISION_API_KEY", raising=False)


def test_google_places_result_is_used_when_a_key_is_set(monkeypatch):
    monkeypatch.setenv("GOOGLE_PLACES_API_KEY", "test-key")
    sent = {}

    def fake_post(url, json=None, headers=None, timeout=None):
        sent["key"] = headers["X-Goog-Api-Key"]
        sent["query"] = json["textQuery"]
        return FakeResp(200, GOOGLE_OK)

    monkeypatch.setattr(hl.requests, "post", fake_post)
    monkeypatch.setattr(hl.requests, "get", lambda *a, **k: pytest.fail("OSM must not be called when Google answered"))
    res = hl.lookup_hotel("Sample Palace Hotel", city_hint="Testville")
    assert res["status"] == "ok" and res["source"] == "google_places"
    assert res["address"].startswith("1 Test Road")
    assert res["phone"] == "+91 22 0000 0000"
    assert res["city"] == "Testville" and res["country"] == "India"
    assert sent["key"] == "test-key" and "Sample Palace Hotel" in sent["query"]


def test_falls_back_to_openstreetmap_without_a_key(monkeypatch):
    monkeypatch.setattr(hl.requests, "post", lambda *a, **k: pytest.fail("no Google call without a key"))
    monkeypatch.setattr(hl.requests, "get", lambda *a, **k: FakeResp(200, OSM_OK))
    res = hl.lookup_hotel("Sample Palace Hotel")
    assert res["status"] == "ok" and res["source"] == "openstreetmap"
    assert res["city"] == "Testville" and "Test Road" in res["address"]
    assert res["phone"] == ""  # never invented when the source has none


def test_google_rejection_falls_through_to_openstreetmap(monkeypatch):
    monkeypatch.setenv("GOOGLE_PLACES_API_KEY", "bad-key")
    monkeypatch.setattr(hl.requests, "post", lambda *a, **k: FakeResp(403, {}))
    monkeypatch.setattr(hl.requests, "get", lambda *a, **k: FakeResp(200, OSM_OK))
    assert hl.lookup_hotel("Sample Palace Hotel")["source"] == "openstreetmap"


def test_a_different_hotel_is_not_accepted(monkeypatch):
    other = [{"name": "Completely Unrelated Lodge", "display_name": "x", "address": {"city": "Elsewhere"}, "extratags": {}}]
    monkeypatch.setattr(hl.requests, "get", lambda *a, **k: FakeResp(200, other))
    res = hl.lookup_hotel("Sample Palace Hotel")
    assert res["status"] == "not_found"


def test_network_failure_never_raises(monkeypatch):
    def boom(*a, **k):
        raise hl.requests.ConnectionError("offline")

    monkeypatch.setenv("GOOGLE_PLACES_API_KEY", "k")
    monkeypatch.setattr(hl.requests, "post", boom)
    monkeypatch.setattr(hl.requests, "get", boom)
    assert hl.lookup_hotel("Sample Palace Hotel")["status"] == "unavailable"


def test_too_short_name_is_not_looked_up(monkeypatch):
    monkeypatch.setattr(hl.requests, "get", lambda *a, **k: pytest.fail("no request for an empty name"))
    assert hl.lookup_hotel("")["status"] == "not_found"
