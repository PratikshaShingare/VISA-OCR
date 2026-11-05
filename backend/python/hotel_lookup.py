"""
Khanna Travels & Holidays — hotel details lookup
=================================================
A hotel voucher names the hotel but often has no usable address, city or phone
number (or prints the booking agent's own). Given the hotel's name — plus any
street address / city / country the voucher did print, used only to pick the
right hotel among namesakes — this looks the hotel up online and returns the
hotel's name, address, phone number and city so the Hotel Blocking form can be
filled automatically. The internet's wording wins: if the voucher's hotel name
differs slightly from the listing, the listing's name is returned.

Sources, tried in this order; the first hit is the base and any field it lacks
(typically the phone number) is completed from the next sources:
  1. Google Places API (New) "Text Search" — needs an API key with the Places
     API enabled, read server side only from GOOGLE_PLACES_API_KEY (falling
     back to GOOGLE_VISION_API_KEY). Missing / restricted / rejected -> skipped.
  2. The hotel's own website, found with a web search (DuckDuckGo's HTML
     results). Only the page's structured data (schema.org JSON-LD: name,
     telephone, address) is trusted — never loose text — and booking portals
     (Booking.com, Expedia, ...) are skipped.
  3. OpenStreetMap Nominatim (no key): address, city, and a phone / website
     when the place's entry carries one. Only lodging entries are accepted, so
     a square or street that merely shares a word with the hotel's name is
     never returned. A website found here is read as in step 2 for the phone.
  4. Photon (OpenStreetMap, no key): address and city, as a last resort.

Honesty (project rules 9/10): every value is what a source returned for the
best-matching lodging — never invented — and the result names its source(s) so
the UI can label it "looked up — please verify". Nothing found -> status
"not_found" and the form keeps what the voucher itself said. A result in a
different COUNTRY than the voucher's is reported (countryConflict) and not used.
"""

from __future__ import annotations

import ipaddress
import json
import os
import re
import socket
import time
import unicodedata
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qs, quote_plus, unquote, urlparse

import requests

PLACES_URL = "https://places.googleapis.com/v1/places:searchText"
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
PHOTON_URL = "https://photon.komoot.io/api/"
SEARCH_URL = "https://html.duckduckgo.com/html/"
USER_AGENT = "KhannaTravelsVisaPlatform/1.0 (hotel details lookup; customercare@khannatravels.com)"
TIMEOUT_S = 8

_last_nominatim_call = 0.0


def _fold(text: str) -> str:
    """Lower-case, accents removed ("Trần Bình Trọng" -> "tran binh trong", "đ" -> "d")."""
    text = (text or "").replace("đ", "d").replace("Đ", "D")
    return "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c)).lower()


_NAME_FILLER = {"the", "and", "hotel", "hotels", "resort", "inn", "by", "of", "at", "in"}


def _tokens(text: str) -> set:
    folded = _fold(text).replace("&", "")  # "B&B" -> "bb"
    return {t for t in re.findall(r"[a-z0-9]{2,}", folded) if t not in _NAME_FILLER}


def _clean_name(name: str) -> str:
    """The voucher's hotel name without OCR debris: bracketed bits, stars and
    bullets, and dangling 1-3 character fragments at the end ("... Rimiang B&")."""
    n = re.sub(r"\([^)]*\)", " ", name or "")
    n = re.sub(r"[★*•|_~=]+", " ", n)
    n = re.sub(r"\s+", " ", n).strip(" -,.:;/")
    parts = n.split(" ")
    while len(parts) > 2 and len(re.sub(r"\W", "", parts[-1])) <= 2 and not parts[-1].isdigit():
        parts.pop()
    return " ".join(parts).strip(" -,.:;/")


def _name_score(wanted: str, found: str) -> float:
    """0..1: how much of the wanted name's distinctive words the result carries."""
    w, f = _tokens(wanted), _tokens(found)
    if not w:
        return 1.0 if (found or "").lower().find((wanted or "").lower()) >= 0 else 0.0
    return len(w & f) / len(w)


_ADDRESS_FILLER = {
    "the", "and", "road", "street", "avenue", "boulevard", "district", "city", "ward", "floor", "box", "near", "opp", "opposite",
    "next", "behind", "block", "plot", "no", "hotel", "resort", "inn", "suites", "suite", "area", "zone", "state", "province",
}


def _address_tokens(text: str, name: str = "") -> set:
    """Distinctive words/numbers of an address — street names, house numbers,
    area, city, country — without filler like 'Road' or the hotel's own name."""
    skip = _tokens(name) | _ADDRESS_FILLER
    return {t for t in re.findall(r"[a-z0-9]{2,}", _fold(text)) if t not in skip and not (t in {"st", "rd", "ave", "po"})}


def address_overlap(voucher_address: str, found_address: str, name: str = "") -> Optional[float]:
    """0..1: how much of the voucher's printed address the looked-up address
    carries (None when the voucher printed no usable address to compare)."""
    v = _address_tokens(voucher_address, name)
    if len(v) < 2:
        return None
    f = _address_tokens(found_address, name)
    return len(v & f) / float(len(v))


def address_check(voucher_address: str, found_address: str, name: str = "") -> Dict[str, Any]:
    """{"status": "match"|"partial"|"mismatch"|"unverified", "score": float|None}
    — whether the looked-up address agrees with what the voucher itself printed."""
    score = address_overlap(voucher_address, found_address, name)
    if score is None:
        return {"status": "unverified", "score": None}
    if score >= 0.5:
        return {"status": "match", "score": round(score, 2)}
    if score >= 0.25:
        return {"status": "partial", "score": round(score, 2)}
    return {"status": "mismatch", "score": round(score, 2)}


NAME_OK = 0.34  # share of the wanted name's distinctive words a listing must carry

LODGING_TYPES = {
    "hotel", "hostel", "guest_house", "guesthouse", "motel", "apartment", "chalet", "resort", "aparthotel",
    "bed_and_breakfast", "inn", "lodge", "camp_site", "alpine_hut",
}

# Booking portals / aggregators: never taken as "the hotel's own website".
OTA_DOMAINS = (
    "booking.com", "expedia.", "agoda.", "tripadvisor.", "hotels.com", "trivago.", "kayak.", "skyscanner.", "makemytrip.",
    "goibibo.", "cleartrip.", "yatra.", "hrs.", "momondo.", "priceline.", "orbitz.", "travelocity.", "hostelworld.",
    "airbnb.", "facebook.", "instagram.", "twitter.", "x.com", "linkedin.", "youtube.", "pinterest.", "wikipedia.",
    "wikidata.", "google.", "bing.", "yelp.", "foursquare.", "mapcarta.", "wikivoyage.", "reddit.", "tiktok.",
    "tripadvisor", "lonelyplanet.", "zomato.", "justdial.", "sulekha.",
)

MAX_PAGE_BYTES = 1_500_000
DEADLINE_S = 40  # one hotel never keeps the voucher upload waiting longer than this overall


def _places_key() -> str:
    return (os.environ.get("GOOGLE_PLACES_API_KEY") or os.environ.get("GOOGLE_VISION_API_KEY") or "").strip()


def _component(components: List[dict], *types: str) -> str:
    for t in types:
        for c in components or []:
            if t in (c.get("types") or []):
                return c.get("longText") or c.get("long_name") or ""
    return ""


def _same_country(a: str, b: str) -> Optional[bool]:
    """True / False when both names are known (loosely compared), else None."""
    fa, fb = _fold(a).strip(), _fold(b).strip()
    if not fa or not fb:
        return None
    if fa == fb or fa in fb or fb in fa:
        return True
    return _tokens(fa) == _tokens(fb) and bool(_tokens(fa))


# --------------------------------------------------------------------------
# Source 1: Google Places
# --------------------------------------------------------------------------
def _google_lookup(query: str, name: str, address_hint: str = "") -> Optional[Dict[str, Any]]:
    key = _places_key()
    if not key:
        return None
    try:
        resp = requests.post(
            PLACES_URL,
            json={"textQuery": query, "maxResultCount": 5, "includedType": "lodging"},
            headers={
                "X-Goog-Api-Key": key,
                "X-Goog-FieldMask": "places.displayName,places.formattedAddress,places.internationalPhoneNumber,places.nationalPhoneNumber,places.addressComponents,places.websiteUri",
                "Content-Type": "application/json",
            },
            timeout=TIMEOUT_S,
        )
    except requests.RequestException:
        return None
    if resp.status_code != 200:
        return None  # key missing the Places API / restricted / over quota: try the next source
    best, best_total = None, -1.0
    for place in (resp.json().get("places") or []):
        found = (place.get("displayName") or {}).get("text", "")
        score = _name_score(name, found)
        if score < NAME_OK:
            continue
        # Namesakes exist in many cities: among results with the right name, the
        # one whose address agrees with the voucher's wins.
        overlap = address_overlap(address_hint, place.get("formattedAddress", ""), name)
        total = score + (1.5 * overlap if overlap is not None else 0.0)
        if total > best_total:
            best, best_total = place, total
    if not best:
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
        "website": best.get("websiteUri") or "",
    }


# --------------------------------------------------------------------------
# Safe page fetching (the web search returns arbitrary URLs)
# --------------------------------------------------------------------------
def _is_public_host(host: str) -> bool:
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError:
        return False
    for info in infos:
        try:
            if not ipaddress.ip_address(info[4][0]).is_global:
                return False
        except ValueError:
            return False
    return bool(infos)


def _fetch_page(url: str, timeout: float = 6.0) -> Optional[str]:
    """GET a public http(s) page (max 3 redirects, each re-checked, size
    capped). Returns its HTML, or None. Never touches localhost / private
    networks, so a poisoned search result cannot reach the user's own network."""
    for _ in range(4):
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https") or not parsed.hostname or not _is_public_host(parsed.hostname):
            return None
        try:
            resp = requests.get(
                url,
                headers={"User-Agent": "Mozilla/5.0 (compatible; KhannaTravelsHotelLookup/1.0)", "Accept-Language": "en"},
                timeout=timeout,
                allow_redirects=False,
                stream=True,
            )
        except requests.RequestException:
            return None
        try:
            if resp.status_code in (301, 302, 303, 307, 308):
                loc = resp.headers.get("Location") or ""
                if not loc:
                    return None
                from urllib.parse import urljoin
                url = urljoin(url, loc)
                continue
            if resp.status_code != 200:
                return None
            ctype = (resp.headers.get("Content-Type") or "").lower()
            if ctype and "html" not in ctype and "xml" not in ctype:
                return None
            raw = b""
            for chunk in resp.iter_content(65536):
                raw += chunk
                if len(raw) > MAX_PAGE_BYTES:
                    break
            return raw.decode(resp.encoding or "utf-8", errors="replace")
        finally:
            resp.close()
    return None


def _walk_jsonld(node: Any):
    if isinstance(node, dict):
        yield node
        for v in node.values():
            yield from _walk_jsonld(v)
    elif isinstance(node, list):
        for v in node:
            yield from _walk_jsonld(v)


_JSONLD_RE = re.compile(r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', re.I | re.S)
_LODGING_LD = ("hotel", "lodgingbusiness", "resort", "bedandbreakfast", "hostel", "motel", "apartmenthotel", "campground")


def _address_from_ld(addr: Any) -> Dict[str, str]:
    if isinstance(addr, str):
        return {"address": addr.strip(), "city": "", "country": ""}
    if not isinstance(addr, dict):
        return {"address": "", "city": "", "country": ""}
    country = addr.get("addressCountry")
    if isinstance(country, dict):
        country = country.get("name")
    city = addr.get("addressLocality") or ""
    parts = [addr.get("streetAddress"), addr.get("postalCode"), city, addr.get("addressRegion"), country]
    street = ", ".join(str(p).strip() for p in parts if p and str(p).strip())
    return {"address": street, "city": str(city or "").strip(), "country": str(country or "").strip()}


def _page_details(html: str, wanted: str) -> Optional[Dict[str, Any]]:
    """Name / phone / address from a hotel page's schema.org JSON-LD, only when
    the entity looks like a lodging (or the page's own name matches the wanted
    one). Loose text is never used."""
    best = None
    for m in _JSONLD_RE.finditer(html or ""):
        try:
            data = json.loads(m.group(1).strip())
        except ValueError:
            continue
        for node in _walk_jsonld(data):
            types = node.get("@type")
            types = [types] if isinstance(types, str) else (types or [])
            tl = [str(t).lower() for t in types]
            lodging = any(t in _LODGING_LD for t in tl)
            business = any(t in ("localbusiness", "organization", "place") for t in tl)
            if not (lodging or business) or not node.get("name"):
                continue
            score = _name_score(wanted, str(node.get("name")))
            if score < NAME_OK:
                continue
            addr = _address_from_ld(node.get("address"))
            cand = {
                "name": str(node.get("name")).strip(),
                "phone": str(node.get("telephone") or "").strip(),
                "score": score + (0.5 if lodging else 0.0),
                **addr,
            }
            if not (cand["phone"] or cand["address"]):
                continue
            if best is None or cand["score"] > best["score"]:
                best = cand
    return best


def _phone_from_site(website: str, wanted: str) -> Optional[Dict[str, Any]]:
    html = _fetch_page(website)
    if not html:
        return None
    found = _page_details(html, wanted)
    if found and found.get("phone"):
        return found
    # One hop: the site's own contact page.
    for m in re.finditer(r'href=["\']([^"\']*contact[^"\']*)["\']', html, re.I):
        from urllib.parse import urljoin
        target = urljoin(website, m.group(1))
        if urlparse(target).hostname != urlparse(website).hostname:
            continue
        html2 = _fetch_page(target)
        if html2:
            found2 = _page_details(html2, wanted)
            if found2 and found2.get("phone"):
                return found2
        break
    return found


# --------------------------------------------------------------------------
# Source 2: web search -> the hotel's own site -> structured data
# --------------------------------------------------------------------------
def _search_result_urls(query: str) -> Optional[List[str]]:
    try:
        resp = requests.get(
            SEARCH_URL,
            params={"q": query},
            headers={"User-Agent": "Mozilla/5.0 (compatible; KhannaTravelsHotelLookup/1.0)", "Accept-Language": "en"},
            timeout=TIMEOUT_S,
        )
    except requests.RequestException:
        return None
    if resp.status_code != 200:
        return None
    urls: List[str] = []
    for href in re.findall(r'class="result__a"[^>]*href="([^"]+)"', resp.text or ""):
        href = href.replace("&amp;", "&")
        if "uddg=" in href:
            href = unquote((parse_qs(urlparse(href).query).get("uddg") or [""])[0])
        elif href.startswith("//"):
            href = "https:" + href
        host = (urlparse(href).hostname or "").lower()
        if not host or any(d in host for d in OTA_DOMAINS):
            continue
        if href not in urls:
            urls.append(href)
    return urls


def _web_lookup(query: str, name: str, address_hint: str = "") -> Optional[Dict[str, Any]]:
    urls = _search_result_urls(query + " hotel official website")
    if urls is None:
        return None
    for url in urls[:4]:
        html = _fetch_page(url)
        if not html:
            continue
        found = _page_details(html, name)
        if not found:
            continue
        return {
            "status": "ok",
            "source": "website",
            "name": found["name"],
            "address": found.get("address", ""),
            "phone": found.get("phone", ""),
            "city": found.get("city", ""),
            "country": found.get("country", ""),
            "website": url,
        }
    return {"status": "not_found", "source": "website"}


# --------------------------------------------------------------------------
# Source 3: OpenStreetMap Nominatim
# --------------------------------------------------------------------------
def _is_lodging(item: dict) -> bool:
    typ = str(item.get("type") or "").lower()
    cat = str(item.get("category") or item.get("class") or "").lower()
    return typ in LODGING_TYPES and cat in ("tourism", "building", "amenity", "")


def _osm_lookup(query: str, name: str, address_hint: str = "") -> Optional[Dict[str, Any]]:
    global _last_nominatim_call
    wait = 1.1 - (time.time() - _last_nominatim_call)  # Nominatim's usage policy: at most one request per second
    if wait > 0:
        time.sleep(wait)
    _last_nominatim_call = time.time()
    try:
        resp = requests.get(
            NOMINATIM_URL,
            params={"q": query, "format": "jsonv2", "addressdetails": 1, "extratags": 1, "limit": 8},
            headers={"User-Agent": USER_AGENT, "Accept-Language": "en"},
            timeout=TIMEOUT_S,
        )
    except requests.RequestException:
        return None
    if resp.status_code != 200:
        return None
    best, best_total = None, -1.0
    for item in resp.json() or []:
        if not _is_lodging(item):
            continue  # a square, street or shop that merely shares a word with the hotel's name
        found = item.get("name") or (item.get("display_name") or "").split(",")[0]
        score = _name_score(name, found)
        if score < NAME_OK:
            continue
        overlap = address_overlap(address_hint, item.get("display_name", ""), name)
        total = score + (1.5 * overlap if overlap is not None else 0.0)
        if total > best_total:
            best, best_total = item, total
    if not best:
        return {"status": "not_found", "source": "openstreetmap"}
    addr = best.get("address") or {}
    extra = best.get("extratags") or {}
    street = " ".join(x for x in (addr.get("road"), addr.get("house_number")) if x)
    city = addr.get("city") or addr.get("town") or addr.get("village") or addr.get("municipality") or addr.get("suburb") or addr.get("county") or ""
    parts = [street, addr.get("suburb") if addr.get("suburb") != city else "", addr.get("postcode"), city, addr.get("state"), addr.get("country")]
    return {
        "status": "ok",
        "source": "openstreetmap",
        "name": best.get("name") or "",
        "address": ", ".join(p for p in parts if p) or best.get("display_name", ""),
        "phone": extra.get("phone") or extra.get("contact:phone") or "",
        "city": city,
        "country": addr.get("country", ""),
        "website": extra.get("website") or extra.get("contact:website") or "",
    }


# --------------------------------------------------------------------------
# Source 4: Photon (OpenStreetMap)
# --------------------------------------------------------------------------
def _photon_lookup(query: str, name: str, address_hint: str = "") -> Optional[Dict[str, Any]]:
    try:
        resp = requests.get(
            PHOTON_URL,
            params={"q": query, "limit": 8, "lang": "en"},
            headers={"User-Agent": USER_AGENT},
            timeout=TIMEOUT_S,
        )
    except requests.RequestException:
        return None
    if resp.status_code != 200:
        return None
    best, best_total = None, -1.0
    for feat in (resp.json() or {}).get("features") or []:
        props = feat.get("properties") or {}
        if str(props.get("osm_value") or "").lower() not in LODGING_TYPES:
            continue
        score = _name_score(name, props.get("name") or "")
        if score < NAME_OK:
            continue
        line = ", ".join(str(props.get(k)) for k in ("street", "city", "country") if props.get(k))
        overlap = address_overlap(address_hint, line, name)
        total = score + (1.5 * overlap if overlap is not None else 0.0)
        if total > best_total:
            best, best_total = props, total
    if not best:
        return {"status": "not_found", "source": "photon"}
    street = " ".join(x for x in (best.get("street"), best.get("housenumber")) if x)
    city = best.get("city") or best.get("town") or best.get("village") or best.get("district") or ""
    parts = [street, best.get("postcode"), city, best.get("state"), best.get("country")]
    return {
        "status": "ok",
        "source": "photon",
        "name": best.get("name") or "",
        "address": ", ".join(str(p) for p in parts if p),
        "phone": "",
        "city": city,
        "country": best.get("country") or "",
        "website": "",
    }


# --------------------------------------------------------------------------
# Orchestration
# --------------------------------------------------------------------------
def _queries(name: str, address_hint: str, city_hint: str, country_hint: str) -> List[str]:
    out: List[str] = []
    if address_hint:
        out.append(f"{name} {address_hint}"[:200])
    if city_hint or country_hint:
        out.append(" ".join(x for x in (name, city_hint, country_hint) if x).strip())
    out.append(name)
    words = name.split()
    if len(words) > 4:
        out.append(" ".join(words[:4]))
    seen: List[str] = []
    return [q for q in out if not (q in seen or seen.append(q))]


def _merge(candidates: List[Dict[str, Any]], wanted: str) -> Dict[str, Any]:
    """The first candidate is the base; fields it lacks come from later
    candidates that are plainly the same hotel (same distinctive name words,
    same country when both are known)."""
    base = dict(candidates[0])
    sources = [base["source"]]
    for other in candidates[1:]:
        if _name_score(base.get("name") or wanted, other.get("name") or "") < 0.5:
            continue
        if _same_country(base.get("country", ""), other.get("country", "")) is False:
            continue
        used = False
        for key in ("phone", "city", "address", "country", "website"):
            if not base.get(key) and other.get(key):
                base[key] = other[key]
                used = True
        if used and other["source"] not in sources:
            sources.append(other["source"])
    base["source"] = "+".join(sources)
    return base


def lookup_hotel(name: str, address_hint: str = "", city_hint: str = "", country_hint: str = "") -> Dict[str, Any]:
    """{"status": "ok"|"not_found"|"unavailable", "source", "name", "address",
    "phone", "city", "country", "website", "addressCheck": {...},
    "countryConflict": bool}. Never raises: any network or API trouble is
    reported as status "unavailable".

    The OCR'd hotel name is cleaned of debris and searched with several query
    shapes (with the voucher's address / city / country when it printed them).
    The returned `name` is the listing's own — callers should prefer it over the
    voucher's wording."""
    raw_name = (name or "").strip()
    if len(raw_name) < 3:
        return {"status": "not_found", "source": ""}
    name = _clean_name(raw_name) or raw_name
    queries = _queries(name, address_hint, city_hint, country_hint)
    deadline = time.time() + DEADLINE_S
    candidates: List[Dict[str, Any]] = []
    saw_not_found = False
    saw_response = False

    def complete(c: Dict[str, Any]) -> bool:
        return bool(c.get("phone") and c.get("city") and c.get("address"))

    for attempt in (_google_lookup, _web_lookup, _osm_lookup, _photon_lookup):
        if candidates and complete(candidates[0]):
            break
        for query in queries:
            if time.time() > deadline:
                break
            try:
                res = attempt(query, name, address_hint)
            except Exception:  # noqa: BLE001 — a lookup must never break the voucher upload
                res = None
            if res is None:
                break  # source unavailable (no key / blocked / error): next source
            saw_response = True
            if res.get("status") == "ok":
                if _same_country(country_hint, res.get("country", "")) is False:
                    res["countryConflict"] = True
                    saw_not_found = True
                    continue  # right name, wrong country: try the next, broader query
                candidates.append(res)
                break
            saw_not_found = True
    if not candidates:
        return {"status": "not_found" if saw_response else "unavailable", "source": ""}
    result = _merge(candidates, name)
    # A found website without a phone: read the hotel's own page for it.
    if not result.get("phone") and result.get("website") and time.time() < deadline:
        try:
            site = _phone_from_site(result["website"], name)
        except Exception:  # noqa: BLE001
            site = None
        if site and site.get("phone") and _name_score(result.get("name") or name, site.get("name") or "") >= 0.5:
            result["phone"] = site["phone"]
            if "website" not in result["source"]:
                result["source"] += "+website"
    result["status"] = "ok"
    result["addressCheck"] = address_check(address_hint, result.get("address", ""), name)
    result["countryConflict"] = False
    return result
