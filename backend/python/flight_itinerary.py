"""
Khanna Travels & Holidays — reading a flight booking / itinerary
================================================================

Used by the Fill Forms page: staff upload the flight booking (PDF, or a scan)
and the form gets the date of ARRIVAL IN THE DESTINATION COUNTRY, the port of
entry, the airline and the length of stay.

The arrival date is the date the traveller LANDS at the first airport of the
destination country — not the departure date from India (an overnight flight
leaves on the 23rd and lands on the 24th), and not the date of a later
domestic connection (Tokyo -> Osaka). Likewise the stay ends on the day of
the last flight that leaves the country.

Two layouts are read:
  * detailed flight blocks (Amadeus / CheckMyTrip, airline e-tickets):
        All Nippon Airways NH 830
        Departure 23 December 20:00 Mumbai, (Chhatrapati S Maharaj)
        Arrival 24 December 07:25 Tokyo, (Narita Intl)
    These give the real landing date and are always preferred.
  * the one-line summary table ("23DEC 2000 MUMBAI BOM TOKYO NRT NH830 ...").
    It has no landing date, so when only this is found the result says the
    arrival date must be checked (the flight may land the next day).

Everything returned is a suggestion for staff to verify (project rule 10).
Nothing is logged (rule 11).
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Airports of the destination countries the app fills forms for
# ---------------------------------------------------------------------------

JAPAN_AIRPORTS: Dict[str, str] = {
    "NRT": "TOKYO", "HND": "TOKYO", "KIX": "OSAKA", "ITM": "OSAKA", "UKB": "KOBE", "NGO": "NAGOYA",
    "CTS": "SAPPORO", "OKD": "SAPPORO", "FUK": "FUKUOKA", "OKA": "OKINAWA", "KOJ": "KAGOSHIMA",
    "HIJ": "HIROSHIMA", "SDJ": "SENDAI", "KMJ": "KUMAMOTO", "NGS": "NAGASAKI", "OIT": "OITA",
    "KMQ": "KOMATSU", "TAK": "TAKAMATSU", "MYJ": "MATSUYAMA", "KCZ": "KOCHI", "OKJ": "OKAYAMA",
    "AOJ": "AOMORI", "AKJ": "ASAHIKAWA", "HKD": "HAKODATE", "KIJ": "NIIGATA", "ISG": "ISHIGAKI",
    "MMY": "MIYAKO", "TOY": "TOYAMA", "KMI": "MIYAZAKI", "FSZ": "SHIZUOKA", "IBR": "IBARAKI",
    "KKJ": "KITAKYUSHU", "AXT": "AKITA", "GAJ": "YAMAGATA", "FKS": "FUKUSHIMA", "IZO": "IZUMO",
    "YGJ": "YONAGO", "TTJ": "TOTTORI", "UBJ": "UBE", "HSG": "SAGA", "OBO": "OBIHIRO", "KUH": "KUSHIRO",
}

JAPAN_PLACE_WORDS = {
    "TOKYO", "NARITA", "HANEDA", "OSAKA", "KANSAI", "ITAMI", "KOBE", "NAGOYA", "CHUBU", "CENTRAIR",
    "SAPPORO", "CHITOSE", "FUKUOKA", "OKINAWA", "NAHA", "KAGOSHIMA", "HIROSHIMA", "SENDAI", "KUMAMOTO",
    "NAGASAKI", "OITA", "KOMATSU", "TAKAMATSU", "MATSUYAMA", "KOCHI", "OKAYAMA", "AOMORI", "ASAHIKAWA",
    "HAKODATE", "NIIGATA", "ISHIGAKI", "TOYAMA", "MIYAZAKI", "SHIZUOKA", "IBARAKI", "KITAKYUSHU", "JAPAN",
}

SINGAPORE_AIRPORTS: Dict[str, str] = {"SIN": "SINGAPORE", "XSP": "SINGAPORE"}
SINGAPORE_PLACE_WORDS = {"SINGAPORE", "CHANGI", "SELETAR"}

COUNTRIES = {
    "japan": {"airports": JAPAN_AIRPORTS, "places": JAPAN_PLACE_WORDS},
    "singapore": {"airports": SINGAPORE_AIRPORTS, "places": SINGAPORE_PLACE_WORDS},
}

AIRLINE_NAMES = {
    "NH": "ALL NIPPON AIRWAYS", "JL": "JAPAN AIRLINES", "AI": "AIR INDIA", "6E": "INDIGO", "SQ": "SINGAPORE AIRLINES",
    "CX": "CATHAY PACIFIC", "TG": "THAI AIRWAYS", "EK": "EMIRATES", "QR": "QATAR AIRWAYS", "MH": "MALAYSIA AIRLINES",
    "VN": "VIETNAM AIRLINES", "KE": "KOREAN AIR", "OZ": "ASIANA AIRLINES", "CA": "AIR CHINA", "MU": "CHINA EASTERN",
    "CZ": "CHINA SOUTHERN", "BR": "EVA AIR", "CI": "CHINA AIRLINES", "UK": "VISTARA", "ZG": "ZIPAIR", "MM": "PEACH AVIATION",
    "TR": "SCOOT", "D7": "AIRASIA X", "EY": "ETIHAD AIRWAYS", "LH": "LUFTHANSA", "AF": "AIR FRANCE", "BA": "BRITISH AIRWAYS",
}

_MONTHS = {m: i for i, m in enumerate(
    ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"], 1)}

_MONTH_WORD = r"(?:JAN(?:UARY)?|FEB(?:RUARY)?|MAR(?:CH)?|APR(?:IL)?|MAY|JUNE?|JULY?|AUG(?:UST)?|SEP(?:T(?:EMBER)?)?|OCT(?:OBER)?|NOV(?:EMBER)?|DEC(?:EMBER)?)"

# "23 December", "23 Dec 2026", "23DEC", "23-Dec-26"
_DAY_MONTH = re.compile(r"\b(\d{1,2})[\s\-/.]?(" + _MONTH_WORD + r")\b[\s\-/.,]*(\d{4}|\d{2}(?!\d|:))?", re.I)
# "December 23, 2026"
_MONTH_DAY = re.compile(r"\b(" + _MONTH_WORD + r")\s+(\d{1,2}),?\s+(\d{4})\b", re.I)
_FLIGHT_LINE = re.compile(r"^\s*([A-Za-z][A-Za-z .&'\-]{2,}?)\s+([A-Z0-9]{2})\s?(\d{1,4})\s*$")
_DEP_WORDS = re.compile(r"^\s*(DEPARTURE|DEPART(?:S|ING)?|DEP\.?|FROM)\b[:\s]*", re.I)
_ARR_WORDS = re.compile(r"^\s*(ARRIVAL|ARRIVE(?:S)?|ARR\.?|TO)\b[:\s]*", re.I)
_SUMMARY_ROW = re.compile(
    r"^\s*(\d{1,2})(" + "|".join(_MONTHS) + r")\s+(\d{4})\s+(.+?)\s+([A-Z]{3})\s+(.+?)\s+([A-Z]{3})\s+([A-Z0-9]{2})\s?(\d{1,4})\b(.*)$"
)


def _month_num(word: str) -> int:
    return _MONTHS.get(word[:3].upper(), 0)


def _year_of(text: str) -> Optional[int]:
    """The booking's year: from a written-out date first ("23 December 2026");
    otherwise a lone 20xx that is not a departure time ("23DEC 2000")."""
    for m in _DAY_MONTH.finditer(text or ""):
        if m.group(3) and len(m.group(3)) == 4 and not re.match(r"\d{1,2}[A-Z]{3}$", m.group(0).split()[0].upper() if m.group(0).split() else ""):
            return int(m.group(3))
    for m in _MONTH_DAY.finditer(text or ""):
        return int(m.group(3))
    for m in re.finditer(r"(\S+)\s+(20\d{2})\b", text or ""):
        if re.fullmatch(r"\d{1,2}[A-Za-z]{3}", m.group(1)):
            continue  # "23DEC 2000": that is a time
        return int(m.group(2))
    return None


def _find_date(text: str) -> Optional[Tuple[int, int, Optional[int]]]:
    """(day, month, year or None) of the first date in text."""
    m = _MONTH_DAY.search(text)
    if m:
        return int(m.group(2)), _month_num(m.group(1)), int(m.group(3))
    m = _DAY_MONTH.search(text)
    if m:
        year = m.group(3)
        y = None
        if year:
            y = int(year) if len(year) == 4 else 2000 + int(year)
        return int(m.group(1)), _month_num(m.group(2)), y
    return None


def _find_time(text: str) -> str:
    """First clock time written with a colon or dot (20:00, 07.25). A bare
    four-digit number is not trusted here — it is as likely to be a year."""
    m = re.search(r"\b([01]?\d|2[0-3])[:.]([0-5]\d)\b", text or "")
    return f"{int(m.group(1)):02d}:{m.group(2)}" if m else ""


def _place_after_time(text: str) -> str:
    """'23 December 20:00 Mumbai, (Chhatrapati S Maharaj) (+) Terminal: 2' -> 'Mumbai, (Chhatrapati S Maharaj)'"""
    m = re.search(r"\d{1,2}[:.]\d{2}\s*(.*)$", text)
    place = m.group(1) if m else text
    place = re.split(r"\(\+\)|TERMINAL|TERM\.", place, flags=re.I)[0]
    return place.strip(" ,-")


def _city_of(place: str) -> str:
    first = re.split(r"[,(]", place)[0].strip()
    return re.sub(r"\s+", " ", first).upper()


def _codes_in(place: str) -> List[str]:
    return re.findall(r"\b([A-Z]{3})\b", place or "")


# ---------------------------------------------------------------------------
# Leg parsing
# ---------------------------------------------------------------------------


def _blank_leg() -> Dict[str, Any]:
    return {"airline": "", "flightNo": "", "depDate": None, "depTime": "", "depPlace": "", "arrDate": None, "arrTime": "",
            "arrPlace": "", "arrivalDateCertain": True, "layout": ""}


def parse_detailed(text: str) -> List[Dict[str, Any]]:
    lines = [ln.strip() for ln in (text or "").splitlines()]
    legs: List[Dict[str, Any]] = []
    current_year: Optional[int] = _year_of(text)
    last_flight: Tuple[str, str] = ("", "")
    pending: Optional[Dict[str, Any]] = None
    for line in lines:
        line = re.sub(r"^[^A-Za-z0-9]+", "", line)  # OCR bullets / arrows ("> All Nippon ...")
        line = re.sub(r"^[a-z]{1,3}\s+(?=[A-Z])", "", line)  # OCR noise before a word ("joa Arrival")
        if not line:
            continue
        found = _find_date(line)
        if found and found[2] and not _DEP_WORDS.match(line) and not _ARR_WORDS.match(line):
            current_year = found[2]
        fm = _FLIGHT_LINE.match(line)
        if fm and not _DEP_WORDS.match(line) and not _ARR_WORDS.match(line) and any(ch.isdigit() for ch in fm.group(3)):
            name = fm.group(1).strip()
            if not re.search(r"\b(BOOKING|REF|TERMINAL|SEAT|PAGE|CLASS|DURATION)\b", name, re.I):
                last_flight = (name.upper(), f"{fm.group(2)} {fm.group(3)}")
        dep = _DEP_WORDS.match(line)
        arr = _ARR_WORDS.match(line)
        if dep and found and _find_time(line):
            pending = _blank_leg()
            pending["layout"] = "detailed"
            pending["airline"], pending["flightNo"] = last_flight
            pending["depDate"] = (found[0], found[1], found[2] or current_year)
            pending["depTime"] = _find_time(line)
            pending["depPlace"] = _place_after_time(line)
        elif arr and found and pending is not None and _find_time(line):
            pending["arrDate"] = (found[0], found[1], found[2] or current_year)
            pending["arrTime"] = _find_time(line)
            pending["arrPlace"] = _place_after_time(line)
            legs.append(pending)
            pending = None
    return legs


def parse_summary(text: str) -> List[Dict[str, Any]]:
    year = _year_of(text)
    legs = []
    for line in (text or "").splitlines():
        line = re.sub(r"^\s*O(\d)([A-Z]{3})\b", r"0\1\2", line.strip().upper())  # OCR: "O2JAN"
        line = re.sub(r"\s+[—–-]\s+", " ", line)
        m = _SUMMARY_ROW.match(line)
        if not m:
            continue
        leg = _blank_leg()
        leg["layout"] = "summary"
        hhmm = m.group(3)
        leg["depDate"] = (int(m.group(1)), _MONTHS[m.group(2)], year)
        leg["depTime"] = f"{hhmm[:2]}:{hhmm[2:]}"
        leg["depPlace"] = f"{m.group(4)} {m.group(5)}"
        leg["arrPlace"] = f"{m.group(6)} {m.group(7)}"
        leg["flightNo"] = f"{m.group(8)} {m.group(9)}"
        tail = re.sub(r"^\s*\d\s+", "", m.group(10)).strip()
        leg["airline"] = tail if re.search(r"[A-Z]{3,}", tail) else AIRLINE_NAMES.get(m.group(8), "")
        # The summary table has no landing date: assume the same day, flagged.
        leg["arrDate"] = leg["depDate"]
        leg["arrivalDateCertain"] = False
        legs.append(leg)
    return legs


def _norm_flight(no: str) -> str:
    return re.sub(r"\s+", "", (no or "").upper())


_PLACE_LINE = re.compile(r"^\s*([A-Za-z][A-Za-z .'\-]+,\s*\(.+?\))")


def _fill_missing_places(legs: List[Dict[str, Any]], summary: List[Dict[str, Any]], text: str) -> None:
    """A scanned booking read by OCR often loses the city that sat on the
    same line as "Departure ... 20:00" (the page is read column by column).
    The city is then taken from the summary table row of the same flight
    number, or else from the "City, (Airport)" lines in the order they
    appear."""
    by_flight = {_norm_flight(s["flightNo"]): s for s in summary if s.get("flightNo")}
    for leg in legs:
        row = by_flight.get(_norm_flight(leg["flightNo"]))
        if row:
            if not leg["depPlace"]:
                leg["depPlace"] = row["depPlace"]
            if not leg["arrPlace"]:
                leg["arrPlace"] = row["arrPlace"]
            if not leg["airline"]:
                leg["airline"] = row["airline"]
    missing = [leg for leg in legs if not leg["depPlace"] or not leg["arrPlace"]]
    if not missing:
        return
    places = [m.group(1).strip() for m in (_PLACE_LINE.match(ln) for ln in (text or "").splitlines()) if m]
    if len(places) >= 2 * len(legs):
        for i, leg in enumerate(legs):
            leg["depPlace"] = leg["depPlace"] or places[2 * i]
            leg["arrPlace"] = leg["arrPlace"] or places[2 * i + 1]


def _to_date(parts: Optional[Tuple[int, int, Optional[int]]], fallback_year: Optional[int]) -> Optional[date]:
    if not parts:
        return None
    day, month, year = parts
    year = year or fallback_year or date.today().year
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _resolve_dates(legs: List[Dict[str, Any]], doc_year: Optional[int]) -> None:
    """Turns (day, month, year?) into dates, rolling the year over when the
    itinerary crosses New Year (Dec -> Jan) without printing the new year."""
    previous: Optional[date] = None
    for leg in legs:
        for key in ("depDate", "arrDate"):
            parts = leg[key]
            if parts is None:
                leg[key] = None
                continue
            explicit_year = parts[2] is not None and key == "depDate" and leg["layout"] == "detailed"
            d = _to_date(parts, (previous.year if previous else doc_year))
            if d and previous and d < previous - timedelta(days=2) and not explicit_year:
                try:
                    d = d.replace(year=d.year + 1)
                except ValueError:
                    pass
            if d and previous and key == "arrDate" and d < previous:
                try:
                    d = d.replace(year=d.year + 1)
                except ValueError:
                    pass
            leg[key] = d
            if d:
                previous = d


def _in_country(place: str, country: Dict[str, Any]) -> bool:
    up = (place or "").upper()
    if any(code in country["airports"] for code in _codes_in(up)):
        return True
    words = set(re.findall(r"[A-Z]+", up))
    return bool(words & country["places"])


def _city_in_country(place: str, country: Dict[str, Any]) -> str:
    up = (place or "").upper()
    for code in _codes_in(up):
        if code in country["airports"]:
            return country["airports"][code]
    city = _city_of(place)
    return city


def read_itinerary(text: str, destination: str = "Japan") -> Dict[str, Any]:
    """{status, legs, arrivalDate, departureDate, lengthOfStay, portOfEntry,
    airline, flightNo, warnings}. Dates are ISO strings."""
    country = COUNTRIES.get((destination or "").strip().lower())
    if not country:
        return {"status": "unsupported", "legs": [], "warnings": [f"Flights to {destination} cannot be read yet."]}

    doc_year = _year_of(text)
    legs = parse_detailed(text)
    used_summary = False
    if legs:
        _fill_missing_places(legs, parse_summary(text), text)
    else:
        legs = parse_summary(text)
        used_summary = bool(legs)
    _resolve_dates(legs, doc_year)
    legs = [leg for leg in legs if leg["depDate"]]
    legs.sort(key=lambda l: (l["depDate"], l["depTime"] or "00:00"))

    for leg in legs:
        leg["depInCountry"] = _in_country(leg["depPlace"], country)
        leg["arrInCountry"] = _in_country(leg["arrPlace"], country)

    warnings: List[str] = []
    entry = next((l for l in legs if l["arrInCountry"] and not l["depInCountry"]), None)
    exit_leg = None
    if entry:
        after = [l for l in legs if (l["depDate"], l["depTime"]) >= (entry["depDate"], entry["depTime"])]
        exit_leg = next((l for l in reversed(after) if l["depInCountry"] and not l["arrInCountry"]), None)

    out_legs = [{
        "airline": l["airline"], "flightNo": l["flightNo"],
        "depDate": l["depDate"].isoformat() if l["depDate"] else "", "depTime": l["depTime"], "from": l["depPlace"],
        "arrDate": l["arrDate"].isoformat() if l["arrDate"] else "", "arrTime": l["arrTime"], "to": l["arrPlace"],
        "arrivalDateCertain": l["arrivalDateCertain"],
        "role": "arrival" if l is entry else "departure" if l is exit_leg else ("domestic" if l["depInCountry"] and l["arrInCountry"] else ""),
    } for l in legs]

    if not legs:
        return {"status": "not-found", "legs": [], "warnings": ["No flights could be read from this file — enter the dates by hand."]}
    if not entry:
        return {"status": "no-entry", "legs": out_legs,
                "warnings": [f"None of the flights lands in {destination} — is this the right booking?"]}

    arrival = entry["arrDate"]
    if not entry["arrivalDateCertain"]:
        warnings.append("This booking shows only departure dates. The arrival date was taken as the departure day — "
                        "check whether the flight lands the next day.")
    departure = exit_leg["depDate"] if exit_leg else None
    if not exit_leg:
        warnings.append(f"No flight leaving {destination} was found, so the length of stay is not known.")
    length = ""
    if arrival and departure:
        days = (departure - arrival).days + 1
        if days > 0:
            length = f"{days} DAY" + ("S" if days != 1 else "")
        else:
            warnings.append("The departure flight is before the arrival — check the dates.")
    if entry["depDate"] and arrival and arrival != entry["depDate"]:
        warnings.append(
            f"The flight leaves on {entry['depDate'].strftime('%d-%m-%Y')} and lands in {destination} on "
            f"{arrival.strftime('%d-%m-%Y')} — the landing date is used."
        )
    domestic = [l for l in legs if l["depInCountry"] and l["arrInCountry"]]
    if domestic:
        warnings.append(f"{len(domestic)} flight(s) inside {destination} (connections) were not counted as the arrival.")
    airline = entry["airline"] or AIRLINE_NAMES.get((entry["flightNo"] or "")[:2], "")
    return {
        "status": "ok",
        "legs": out_legs,
        "arrivalDate": arrival.isoformat() if arrival else "",
        "departureDate": departure.isoformat() if departure else "",
        "lengthOfStay": length,
        "portOfEntry": _city_in_country(entry["arrPlace"], country),
        "airline": airline.upper(),
        "flightNo": entry["flightNo"],
        "layout": "summary" if used_summary else "detailed",
        "warnings": warnings,
    }
