"""
Khanna Travels & Holidays — hotel details lookup
=================================================
A hotel voucher names the hotel but often has no usable address or phone
number (or prints the booking agent's own). Given the hotel's name — plus any
street address / city the voucher did print, used only to pick the right hotel
among namesakes — this looks the hotel up online and returns its address,
phone number and city so the Hotel Blocking form can be filled automatically.

Sources, in order:
  1. Google Places API (New) "Text Search" — address, international phone
     number and city. Needs an API key with the Places API enabled, read here
     (server side only, never sent to the browser) from GOOGLE_PLACES_API_KEY,
     falling back to GOOGLE_VISION_API_KEY when that same Google Cloud key also
     has Places enabled. A key that is missing, restricted or rejected simply
     moves on to step 2.
  2. OpenStreetMap Nominatim (no key) — address and city; a phone number only
     when the place's OSM entry carries one.

Honesty (project rules 9/10): every value is whatever the source returned for
the best-matching place — never invented — and the result says which source it
came from so the UI can label it "looked up — please verify". When nothing
trustworthy matches, status is "not_found" and the form keeps what the voucher
itself said.
"""

from __future__ import annotations

import os
import re
import time
from typing import Any, Dict, List, Optional

import requests

PLACES_URL = "https://places.googleapis.com/v1/places:searchText"
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
USER_AGENT = "KhannaTravelsVisaPlatform/1.0 (hotel details lookup; customercare@khannatravels.com)"
TIMEOUT_S = 8

_last_nominatim_call = 0.0


def _tokens(text: str) -> set:
    return {t for t in re.findall(r"[a-z0-9]{3,}", (text or "").lower()) if t not in {"the", "and", "hotel", "resort", "inn"}}


def _name_score(wanted: str, found: str) -> float:
    """0..1: how much of the wanted name's distinctive words the result carries."""
    w, f = _tokens(wanted), _tokens(found)
    if not w:
        return 1.0 if (found or "").lower().find((wanted or "").lower()) >= 0 else 0.0
    return len(w & f) / len(w)


def _places_key() -> str:
    return (os.environ.get("GOOGLE_PLACES_API_KEY") or os.environ.get("GOOGLE_VISION_API_KEY") or "").strip()


def _component(components: List[dict], *types: str) -> str:
    for t in types:
        for c in components or []:
            if t in (c.get("types") or []):
                return c.get("longText") or c.get("long_name") or ""
    return ""


def _google_lookup(query: str, name: str) -> Optional[Dict[str, Any]]:
    key = _places_key()
    if not key:
        return None
    try:
        resp = requests.post(
            PLACES_URL,
            json={"textQuery": query, "maxResultCount": 5},
            headers={
                "X-Goog-Api-Key": key,
                "X-Goog-FieldMask": "places.displayName,places.formattedAddress,places.internationalPhoneNumber,places.nationalPhoneNumber,places.addressComponents",
                "Content-Type": "application/json",
            },
            timeout=TIMEOUT_S,
        )
    except requests.RequestException:
        return None
    if resp.status_code != 200:
        return None  # key missing the Places API / restricted / over quota: try the next source
    best, best_score = None, 0.0
    for place in (resp.json().get("places") or []):
        found = (place.get("displayName") or {}).get("text", "")
        score = _name_score(name, found)
        if score > best_score:
            best, best_score = place, score
    if not best or best_score < 0.5:
        return {"status": "not_found", "source": "google_places"}
    comps = best.get("addressComponents") or []
    return {
        "status": "ok",
        "source": "google_places",
        "name": (best.get("displayName") or {}).get("text", ""),
        "address": best.get("formattedAddress", ""),
        "phone": best.get("internationalPhoneNumber") or best.get("nationalPhoneNumber") or "",
        "city": _component(comps, "locality", "postal_town", "administrative_area_level_2", "administrative_area_level_1"),
        "country": _component(comps, "country"),
    }


def _osm_lookup(query: str, name: str) -> Optional[Dict[str, Any]]:
    global _last_nominatim_call
    wait = 1.1 - (time.time() - _last_nominatim_call)  # Nominatim's usage policy: at most one request per second
    if wait > 0:
        time.sleep(wait)
    _last_nominatim_call = time.time()
    try:
        resp = requests.get(
            NOMINATIM_URL,
            params={"q": query, "format": "jsonv2", "addressdetails": 1, "extratags": 1, "limit": 5},
            headers={"User-Agent": USER_AGENT, "Accept-Language": "en"},
            timeout=TIMEOUT_S,
        )
    except requests.RequestException:
        return None
    if resp.status_code != 200:
        return None
    best, best_score = None, 0.0
    for item in resp.json() or []:
        found = item.get("name") or (item.get("display_name") or "").split(",")[0]
        score = _name_score(name, found)
        if score > best_score:
            best, best_score = item, score
    if not best or best_score < 0.5:
        return {"status": "not_found", "source": "openstreetmap"}
    addr = best.get("address") or {}
    extra = best.get("extratags") or {}
    street = " ".join(x for x in (addr.get("house_number"), addr.get("road")) if x)
    city = addr.get("city") or addr.get("town") or addr.get("village") or addr.get("suburb") or addr.get("county") or ""
    parts = [street, addr.get("suburb") if addr.get("suburb") != city else "", city, addr.get("state"), addr.get("postcode"), addr.get("country")]
    return {
        "status": "ok",
        "source": "openstreetmap",
        "name": best.get("name") or "",
        "address": ", ".join(p for p in parts if p) or best.get("display_name", ""),
        "phone": extra.get("phone") or extra.get("contact:phone") or "",
        "city": city,
        "country": addr.get("country", ""),
    }


def lookup_hotel(name: str, address_hint: str = "", city_hint: str = "", country_hint: str = "") -> Dict[str, Any]:
    """{"status": "ok"|"not_found"|"unavailable", "source", "name", "address",
    "phone", "city", "country"}. Never raises: any network or API trouble is
    reported as status "unavailable"."""
    name = (name or "").strip()
    if len(name) < 3:
        return {"status": "not_found", "source": ""}
    # The hotel name alone is the query; the voucher's own street/city only
    # narrow it down (namesake hotels exist in many cities).
    query = " ".join(x for x in (name, city_hint, country_hint) if x).strip()
    if not city_hint and address_hint:
        query = f"{name} {address_hint}"
    results: List[Dict[str, Any]] = []
    for attempt in (_google_lookup, _osm_lookup):
        try:
            res = attempt(query, name)
            if res is None and query != name:
                res = attempt(name, name)
        except Exception:  # noqa: BLE001 — a lookup must never break the voucher upload
            res = None
        if res and res.get("status") == "ok":
            return res
        if res:
            results.append(res)
    return results[0] if results else {"status": "unavailable", "source": ""}
