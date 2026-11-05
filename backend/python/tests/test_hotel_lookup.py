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
        "category": "tourism",
        "type": "hotel",
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
    other = [{"category": "tourism", "type": "hotel", "name": "Completely Unrelated Lodge", "display_name": "x", "address": {"city": "Elsewhere"}, "extratags": {}}]
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


# ---------------------------------------------------------------------------
# Lodging-only, name cleaning, country conflict, website structured data
# ---------------------------------------------------------------------------

def test_a_square_that_shares_a_word_with_the_hotel_name_is_not_a_hotel(monkeypatch):
    plaza = [{"category": "place", "type": "square", "name": "Plazoleta Leopoldo Lugones", "display_name": "Plazoleta Leopoldo Lugones, La Plata",
              "address": {"city": "La Plata", "country": "Argentina"}, "extratags": {}}]
    monkeypatch.setattr(hl.requests, "get", lambda *a, **k: FakeResp(200, plaza))
    assert hl.lookup_hotel("B&B Leopoldo")["status"] == "not_found"


def test_the_listing_name_is_returned_not_the_vouchers_wording(monkeypatch):
    osm = [{"category": "tourism", "type": "hotel", "name": "Hotel Weisses Kreuz St. Gallen", "display_name": "x",
            "address": {"road": "Engelgasse", "house_number": "9", "city": "St. Gallen", "postcode": "9000", "country": "Switzerland"},
            "extratags": {"phone": "+41 71 223 28 43"}}]
    monkeypatch.setattr(hl.requests, "get", lambda *a, **k: FakeResp(200, osm))
    res = hl.lookup_hotel("Hotel Weisses Kreuz")
    assert res["status"] == "ok" and res["name"] == "Hotel Weisses Kreuz St. Gallen"
    assert res["phone"] == "+41 71 223 28 43" and res["city"] == "St. Gallen"


def test_ocr_debris_is_cleaned_from_the_name():
    assert hl._clean_name("B&B Hotel Zurich Airport Rimiang B&") == "B&B Hotel Zurich Airport Rimiang"
    assert hl._clean_name("Ibis Styles Luzern (HTL) ★★★") == "Ibis Styles Luzern"
    assert hl._clean_name("B&B Hotel Milano Ornato") == "B&B Hotel Milano Ornato"


def test_a_hotel_of_that_name_in_another_country_is_not_used(monkeypatch):
    osm = [{"category": "tourism", "type": "hotel", "name": "Sample Palace Hotel", "display_name": "x",
            "address": {"city": "Paris", "country": "France"}, "extratags": {}}]
    monkeypatch.setattr(hl.requests, "get", lambda *a, **k: FakeResp(200, osm))
    res = hl.lookup_hotel("Sample Palace Hotel", country_hint="Italy")
    assert res["status"] == "not_found"


LD_PAGE = """<html><head><script type="application/ld+json">
{"@context":"https://schema.org","@type":"Hotel","name":"Sample Palace Hotel","telephone":"+39 02 1234 5678",
 "address":{"@type":"PostalAddress","streetAddress":"Via Test 1","postalCode":"20100","addressLocality":"Milano","addressCountry":"IT"}}
</script></head><body>x</body></html>"""


def test_website_structured_data_gives_name_phone_and_address(monkeypatch):
    html = ('<a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fwww.booking.com%2Fh">b</a>'
            '<a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fwww.samplepalace.example%2F">s</a>')

    class Search(FakeResp):
        text = html

    monkeypatch.setattr(hl.requests, "get", lambda *a, **k: Search(200))
    monkeypatch.setattr(hl, "_fetch_page", lambda url, timeout=6.0: LD_PAGE if "samplepalace" in url else pytest.fail("OTA page fetched: " + url))
    res = hl.lookup_hotel("Sample Palace Hotel")
    assert res["status"] == "ok" and res["source"] == "website"
    assert res["phone"] == "+39 02 1234 5678" and res["city"] == "Milano" and "Via Test 1" in res["address"]


def test_missing_phone_is_completed_from_the_hotels_own_site(monkeypatch):
    osm = [{"category": "tourism", "type": "hotel", "name": "Sample Palace Hotel", "display_name": "x",
            "address": {"road": "Via Test", "city": "Milano", "country": "Italy"},
            "extratags": {"website": "https://www.samplepalace.example"}}]

    def fake_get(url, **k):
        if "nominatim" in url:
            return FakeResp(200, osm)
        return FakeResp(500, {})  # the search engine and photon are down

    monkeypatch.setattr(hl.requests, "get", fake_get)
    monkeypatch.setattr(hl, "_fetch_page", lambda url, timeout=6.0: LD_PAGE)
    res = hl.lookup_hotel("Sample Palace Hotel")
    assert res["status"] == "ok" and res["phone"] == "+39 02 1234 5678" and "website" in res["source"]
    assert res["city"] == "Milano"


def test_pages_on_private_networks_are_never_fetched(monkeypatch):
    monkeypatch.setattr(hl.requests, "get", lambda *a, **k: pytest.fail("must not connect"))
    assert hl._fetch_page("http://127.0.0.1:8000/secret") is None
    assert hl._fetch_page("http://192.168.1.10/x") is None
    assert hl._fetch_page("file:///etc/passwd") is None
