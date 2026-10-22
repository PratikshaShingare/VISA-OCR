"""
Khanna Travels & Holidays — MRZ Reader v2 (free, local, offline)
==================================================================

A second-generation reader for the two-line machine-readable zone (ICAO 9303
TD3 passport MRZ). It exists because the production pipeline in
ocr_runner.py reads the MRZ ONCE from a fixed "bottom 22% of the page" crop
and then trusts whatever Tesseract returned. That fails on:

  * photos where the MRZ is not in the bottom 22% (cropped/zoomed/tilted),
  * photos where the page is rotated,
  * lines with a single misread character (O/0, I/1, S/5, B/8 ...), and
  * names whose trailing "<<<<<" filler is read as "KKKKK" / "CCCC" / "LLLL".

What is different here
----------------------
1. LOCATE the MRZ: a morphological text-block detector (black-hat + gradient
   + closing) finds the wide, dense two-line block anywhere on the page;
   fixed bottom-band crops are tried as fallbacks.
2. MANY READS, NOT ONE: several rotations x crops x pre-processing variants
   x Tesseract page-segmentation modes. Every read is a candidate.
3. TYPE-AWARE REPAIR: each MRZ character position has a known type (digit /
   letter / either) so letter<->digit confusions are corrected per position.
4. CHECK-DIGIT-GUIDED REPAIR: when a field's ICAO check digit fails, up to
   two visually-confusable characters are substituted until the check digit
   passes (dates must also be real calendar dates). Every such repair is
   recorded in `repairs` and lowers the reported confidence — nothing is
   silently "fixed".
5. VOTING: candidates are scored and the best (valid check digits, fewest
   repairs, most agreement) wins.

What it does NOT do
-------------------
It reads only what the MRZ contains: name, passport number, nationality,
issuing country, date of birth, sex, expiry, personal number. Place of
birth / place & date of issue / address are printed only in the visual zone
and are NOT in the MRZ — they are never guessed here.

Like everything in this project, the output is a PROPOSAL: it is shown as
"OCR Extracted — Please Verify" and staff can always correct it (project
rules 10 and 19).

Nothing is logged and no image or text leaves the machine.
"""

from __future__ import annotations

import itertools
import re
import time
from collections import Counter
from datetime import date, datetime
from typing import Any, Callable, Dict, List, Optional, Tuple

import cv2
import numpy as np

from ocr_runner import compute_icao_check_digit, parse_mrz_td3

MRZ_LEN = 44
MRZ_CHARSET = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789<"
_CHARSET_RE = re.compile(r"[^A-Z0-9<]")

# --------------------------------------------------------------------------
# Character confusion tables
# --------------------------------------------------------------------------

# Groups of glyphs OCR engines commonly swap. Used both for type coercion and
# for check-digit-guided substitution search.
_CONFUSION_GROUPS: List[str] = [
    "O0QD",
    "I1L",
    "Z2",
    "S5",
    "B8",
    "G6",
    "T7",
    "UV",
    "A4",
    "E3",
]

_SIMILAR: Dict[str, str] = {}
for _grp in _CONFUSION_GROUPS:
    for _ch in _grp:
        _SIMILAR[_ch] = _SIMILAR.get(_ch, "") + "".join(c for c in _grp if c != _ch)

# Digit<->digit confusions that happen on blurry / low-resolution photos.
_DIGIT_PAIRS = ["08", "06", "17", "38", "56", "58", "68", "27", "49", "89", "35", "03", "09"]
_DIGIT_SIMILAR: Dict[str, str] = {}
for _a, _b in _DIGIT_PAIRS:
    _DIGIT_SIMILAR[_a] = _DIGIT_SIMILAR.get(_a, "") + _b
    _DIGIT_SIMILAR[_b] = _DIGIT_SIMILAR.get(_b, "") + _a

_TO_DIGIT = {"O": "0", "Q": "0", "D": "0", "I": "1", "L": "1", "Z": "2", "S": "5", "B": "8", "G": "6", "T": "7", "A": "4", "E": "3"}
_TO_ALPHA = {"0": "O", "1": "I", "2": "Z", "5": "S", "6": "G", "8": "B", "4": "A", "3": "E", "7": "T"}
# What a run of the "<" filler is commonly misread as.
_FILLER_LOOKALIKES = set("KCLESXRIJ1")


def _to_digits(s: str) -> str:
    return "".join(_TO_DIGIT.get(c, c) if not c.isdigit() else c for c in s)


def _to_alpha(s: str) -> str:
    return "".join(_TO_ALPHA.get(c, c) if c.isdigit() else c for c in s)


# --------------------------------------------------------------------------
# ISO 3166 / ICAO 9303 three-letter codes (used to validate and repair the
# issuing-country / nationality fields)
# --------------------------------------------------------------------------

COUNTRY_CODES = frozenset("""
AFG ALB DZA ASM AND AGO AIA ATA ATG ARG ARM ABW AUS AUT AZE BHS BHR BGD BRB BLR BEL BLZ BEN BMU BTN BOL BES BIH BWA BVT BRA IOT
BRN BGR BFA BDI CPV KHM CMR CAN CYM CAF TCD CHL CHN CXR CCK COL COM COG COD COK CRI CIV HRV CUB CUW CYP CZE DNK DJI DMA DOM ECU
EGY SLV GNQ ERI EST SWZ ETH FLK FRO FJI FIN FRA GUF PYF ATF GAB GMB GEO DEU GHA GIB GRC GRL GRD GLP GUM GTM GGY GIN GNB GUY HTI
HMD VAT HND HKG HUN ISL IND IDN IRN IRQ IRL IMN ISR ITA JAM JPN JEY JOR KAZ KEN KIR PRK KOR KWT KGZ LAO LVA LBN LSO LBR LBY LIE
LTU LUX MAC MDG MWI MYS MDV MLI MLT MHL MTQ MRT MUS MYT MEX FSM MDA MCO MNG MNE MSR MAR MOZ MMR NAM NRU NPL NLD NCL NZL NIC NER
NGA NIU NFK MKD MNP NOR OMN PAK PLW PSE PAN PNG PRY PER PHL PCN POL PRT PRI QAT REU ROU RUS RWA BLM SHN KNA LCA MAF SPM VCT WSM
SMR STP SAU SEN SRB SYC SLE SGP SXM SVK SVN SLB SOM ZAF SGS SSD ESP LKA SDN SUR SJM SWE CHE SYR TWN TJK TZA THA TLS TGO TKL TON
TTO TUN TUR TKM TCA TUV UGA UKR ARE GBR USA UMI URY UZB VUT VEN VNM VGB VIR WLF ESH YEM ZMB ZWE
D GBD GBN GBO GBP GBS UNO UNA UNK XXA XXB XXC XXX EUE RKS CSK YUG SUN ANT
""".split())


def _repair_country_code(code: str) -> Tuple[str, bool]:
    """Returns (code, changed). Accepts a valid code; otherwise tries
    single-letter confusable substitutions and accepts only a UNIQUE valid
    result (an ambiguous guess is never made)."""
    code = _to_alpha(code)
    padded = code.rstrip("<")
    if padded in COUNTRY_CODES:
        return code, False
    if len(padded) != 3:
        return code, False
    hits = []
    for i, ch in enumerate(padded):
        for alt in _SIMILAR.get(ch, ""):
            cand = padded[:i] + alt + padded[i + 1:]
            if cand in COUNTRY_CODES:
                hits.append(cand)
    hits = sorted(set(hits))
    if len(hits) == 1:
        return hits[0], True
    return code, False


# --------------------------------------------------------------------------
# Field repair
# --------------------------------------------------------------------------


def _is_plausible_date(yymmdd: str) -> bool:
    if not re.fullmatch(r"\d{6}", yymmdd):
        return False
    mm, dd = int(yymmdd[2:4]), int(yymmdd[4:6])
    if not (1 <= mm <= 12 and 1 <= dd <= 31):
        return False
    try:
        # leap-year-safe validity check (use 2000, a leap year, for 02-29)
        date(2000, mm, dd)
    except ValueError:
        return False
    return True


def _candidate_chars(ch: str, kind: str) -> str:
    """Characters `ch` might really have been. kind: 'digit' | 'alnum'."""
    if kind == "digit":
        alts = _DIGIT_SIMILAR.get(ch, "")
        if not ch.isdigit():
            alts = _TO_DIGIT.get(ch, "") + alts
        return alts
    # alphanumeric: only letter<->digit look-alikes (O/0, I/1, S/5 ...). Swapping
    # letter-for-letter or digit-for-digit in free-form data would make a
    # coincidental check-digit match far too likely.
    return "".join(c for c in _SIMILAR.get(ch, "") if c.isdigit() != ch.isdigit())


def _edit_cost(read: str, true: str) -> float:
    """How plausible is it that OCR printed `read` when the glyph really was
    `true`? Lower = more plausible. Letter->digit look-alikes (O for 0, I for
    1, S for 5 ...) are by far the most common OCR errors in MRZ text."""
    if read.isalpha() and true.isdigit():
        return 0.5 if _TO_DIGIT.get(read) == true else 1.0
    if read.isdigit() and true.isdigit():
        return 1.5
    return 2.0


def _search_fix(data: str, check_char: str, kind: str, validator: Optional[Callable[[str], bool]] = None, max_edits: int = 2) -> Optional[str]:
    """Finds the most plausible data string (fewest / cheapest look-alike
    edits) whose ICAO check digit equals `check_char`. Returns None when
    nothing fits or when the two best candidates tie on plausibility
    (ambiguous — never guessed)."""
    if not check_char.isdigit():
        return None
    target = int(check_char)
    positions = [i for i, c in enumerate(data) if _candidate_chars(c, kind)]
    found: Dict[str, float] = {}
    for n_edits in range(1, max_edits + 1):
        for pos_combo in itertools.combinations(positions, n_edits):
            choices = [list(_candidate_chars(data[i], kind)) for i in pos_combo]
            for combo in itertools.product(*choices):
                cand = list(data)
                cost = 0.0
                for i, alt in zip(pos_combo, combo):
                    cost += _edit_cost(data[i], alt)
                    cand[i] = alt
                cs = "".join(cand)
                if compute_icao_check_digit(cs) == target and (validator is None or validator(cs)):
                    if cs not in found or cost < found[cs]:
                        found[cs] = cost
    if not found:
        return None
    if kind == "alnum":
        # Document/personal numbers are mostly digits: a look-alike LETTER
        # left in the middle of the number is less plausible than a digit.
        # (Index 0 is exempt — many issuers start the number with a letter.)
        def residual(cs: str) -> float:
            return 0.7 * sum(1 for ch in cs[1:] if ch in _TO_DIGIT)

        found = {cs: cost + residual(cs) for cs, cost in found.items()}
    ranked = sorted(found.items(), key=lambda kv: kv[1])
    if len(ranked) > 1 and abs(ranked[0][1] - ranked[1][1]) < 1e-9:
        return None
    return ranked[0][0]


def _fit_length(s: str, want: int = MRZ_LEN) -> str:
    return (s + "<" * want)[:want]


def repair_line2(raw: str) -> Dict[str, Any]:
    """Type-aware + check-digit-guided repair of MRZ line 2. Returns
    {line, repairs[], checks{...}, score}. Never raises."""
    line = list(_fit_length(raw))
    repairs: List[Dict[str, str]] = []

    def note(field: str, before: str, after: str, why: str) -> None:
        if before != after:
            kind = "search" if "check digit only matches" in why else "type"
            repairs.append({"field": field, "from": before, "to": after, "reason": why, "kind": kind})

    def put(start: int, end: int, new: str) -> None:
        for i, ch in enumerate(new):
            line[start + i] = ch

    def seg(start: int, end: int) -> str:
        return "".join(line[start:end])

    # 1. Strict type coercion (positions whose type is fixed by ICAO 9303)
    for field, a, b, fn in (
        ("nationality", 10, 13, _to_alpha),
        ("dateOfBirth", 13, 19, _to_digits),
        ("dateOfBirthCheck", 19, 20, _to_digits),
        ("dateOfExpiry", 21, 27, _to_digits),
        ("dateOfExpiryCheck", 27, 28, _to_digits),
        ("passportNumberCheck", 9, 10, _to_digits),
        ("compositeCheck", 43, 44, _to_digits),
    ):
        before = seg(a, b)
        after = fn(before)
        if before != after:
            put(a, b, after)
            note(field, before, after, "letter/digit confusion for a field that can only be " + ("letters" if fn is _to_alpha else "digits"))

    # nationality code validation
    nat_before = seg(10, 13)
    nat_fixed, changed = _repair_country_code(nat_before)
    if changed:
        put(10, 13, nat_fixed)
        note("nationality", nat_before, nat_fixed, "not a valid country code; one unambiguous look-alike fix")

    # sex
    sex = line[20]
    if sex not in "MF<":
        fixed = {"H": "M", "N": "M", "P": "F", "E": "F", "K": "<", "X": "<"}.get(sex)
        if fixed:
            line[20] = fixed
            note("sex", sex, fixed, "sex must be M, F or <")

    # 2. Per-field check-digit guided repair
    # Passport number (alphanumeric)
    pn_data, pn_chk = seg(0, 9), line[9]
    pn_ok = pn_chk.isdigit() and compute_icao_check_digit(pn_data) == int(pn_chk)
    if not pn_ok:
        fix = _search_fix(pn_data, pn_chk, "alnum")
        if fix is not None:
            put(0, 9, fix)
            note("passportNumber", pn_data, fix, "check digit only matches after fixing look-alike characters")
            pn_ok = True

    # Dates
    def date_field(name: str, a: int, b: int, c: int) -> bool:
        data, chk = seg(a, b), line[c]
        ok = chk.isdigit() and compute_icao_check_digit(data) == int(chk) and _is_plausible_date(data)
        if ok:
            return True
        fix = _search_fix(data, chk, "digit", validator=_is_plausible_date)
        if fix is not None:
            put(a, b, fix)
            note(name, data, fix, "check digit only matches (and the date is real) after fixing look-alike digits")
            return True
        return False

    dob_ok = date_field("dateOfBirth", 13, 19, 19)
    exp_ok = date_field("dateOfExpiry", 21, 27, 27)

    # Personal number
    pers_data, pers_chk = seg(28, 42), line[42]
    if set(pers_data) <= {"<"}:
        pers_ok = True  # unused field — its check position may legitimately be "<" or 0
        if line[42] not in "<0":
            line[42] = "0"  # unused field: its check position can only be "<" or "0"
    else:
        pers_chk = _to_digits(pers_chk)
        line[42] = pers_chk
        pers_ok = pers_chk.isdigit() and compute_icao_check_digit(pers_data) == int(pers_chk)
        if not pers_ok:
            fix = _search_fix(pers_data, pers_chk, "alnum")
            if fix is not None:
                put(28, 42, fix)
                note("personalNumber", pers_data, fix, "check digit only matches after fixing look-alike characters")
                pers_ok = True

    # Composite
    def composite_str() -> str:
        pers_seg = "<" * 15 if set(seg(28, 42)) <= {"<"} else seg(28, 43)
        return seg(0, 10) + seg(13, 20) + seg(21, 28) + pers_seg

    comp_chk = line[43]
    comp_ok = comp_chk.isdigit() and compute_icao_check_digit(composite_str()) == int(comp_chk)
    if not comp_ok and pn_ok and dob_ok and exp_ok and pers_ok:
        # Every field is individually proven correct, so only the composite
        # digit itself can be wrong (it has no neighbours to anchor it).
        good = str(compute_icao_check_digit(composite_str()))
        line[43] = good
        note("compositeCheck", comp_chk, good, "all four field checks pass, so only the final check digit was misread")
        comp_ok = True

    checks = {
        "passportNumber": pn_ok,
        "dateOfBirth": dob_ok,
        "dateOfExpiry": exp_ok,
        "personalNumber": pers_ok,
        "composite": comp_ok,
    }
    valid_count = sum(1 for v in checks.values() if v)
    nat_valid = seg(10, 13).rstrip("<") in COUNTRY_CODES
    sex_valid = line[20] in "MF<"
    score = valid_count * 10 + (4 if nat_valid else 0) + (2 if sex_valid else 0) - 2 * len(repairs)
    # Expiry should come after birth — free extra sanity signal
    if dob_ok and exp_ok:
        try:
            if _yymmdd_to_date(seg(21, 27), True) > _yymmdd_to_date(seg(13, 19), False):
                score += 2
        except Exception:
            pass
    return {"line": "".join(line), "repairs": repairs, "checks": checks, "score": score, "validCount": valid_count}


def _yymmdd_to_date(s: str, is_expiry: bool) -> date:
    yy, mm, dd = int(s[0:2]), int(s[2:4]), int(s[4:6])
    if is_expiry:
        year = 2000 + yy
    else:
        year = 2000 + yy if yy <= datetime.now().year % 100 else 1900 + yy
    return date(year, mm, dd)


def repair_line1(raw: str) -> Dict[str, Any]:
    """Type-aware repair of MRZ line 1 (document code, issuing state and the
    name field — letters and '<' only)."""
    line = list(_fit_length(raw))
    repairs: List[Dict[str, str]] = []

    def note(field: str, before: str, after: str, why: str) -> None:
        if before != after:
            repairs.append({"field": field, "from": before, "to": after, "reason": why})

    before = "".join(line[0:2])
    # Document code: 'P' then '<' or a letter. Passports (TD3) always start with P.
    if line[0] != "P":
        line[0] = "P"
    if line[1].isdigit():
        line[1] = _TO_ALPHA.get(line[1], "<")
    note("documentType", before, "".join(line[0:2]), "passport document code must start with P")

    cb = "".join(line[2:5])
    ca, changed = _repair_country_code(cb)
    for i, ch in enumerate(ca[:3]):
        line[2 + i] = ch
    note("issuingCountry", cb, ca, "digits are not allowed in a country code" if not changed else "not a valid country code; one unambiguous look-alike fix")

    name = "".join(line[5:44])
    fixed = _to_alpha(name)
    note("name", name, fixed, "digits are not allowed in the name field")
    name = fixed

    # Trailing filler misread as K/C/L/E/S... : the real name ends, then only '<'.
    base = name.rstrip("<")
    m = re.search(r"[KCLESXRIJ]{4,}$", base)
    if m:
        run = m.group(0)
        most_common, cnt = Counter(run).most_common(1)[0]
        if cnt >= max(3, int(len(run) * 0.6)):
            cut = m.start() + run.find(most_common)
            fixed = name[:cut] + "<" * (len(name) - cut)
            note("name", name, fixed, "trailing filler run was read as letters")
            name = fixed

    if "<<" not in name.rstrip("<"):
        # Surname/given separator missing — look for a 2+ run of look-alikes.
        m2 = re.search(r"[KCLESX<]{2,}", name[2:])
        if m2:
            s = m2.start() + 2
            fixed = name[:s] + "<<" + name[s + 2:]
            note("name", name, fixed, "surname/given-name separator was read as letters")
            name = fixed

    line[5:44] = list(_fit_length(name, 39))
    out = "".join(line)

    score = 0
    if out[0] == "P":
        score += 2
    if out[2:5].rstrip("<") in COUNTRY_CODES:
        score += 4
    stripped = out[5:].rstrip("<")
    if "<<" in stripped:
        score += 4
        surname, _, given = stripped.partition("<<")
        if surname and given:
            score += 2
    if re.fullmatch(r"[A-Z<]+", out):
        score += 2
    # After the surname/given-name separator, names are separated by a single
    # "<". A second "<<" followed by more letters means stray junk in what
    # should be the filler tail.
    if re.search(r"<<[A-Z<]*?[A-Z]+[A-Z<]*<<+[A-Z]", stripped.partition("<<")[2] if "<<" in stripped else ""):
        score -= 6
    tail = out[5:]
    score += min(len(tail) - len(tail.rstrip("<")), 20) / 10.0
    score -= 2 * len(repairs)
    return {"line": out, "repairs": repairs, "score": score}


# --------------------------------------------------------------------------
# Aligning a read of odd length (a dropped/duplicated character) to 44
# --------------------------------------------------------------------------


def _align_line2(raw: str) -> List[str]:
    """For a line-2 read that is 43/45/46 characters long, produce the 44-char
    variants made by dropping/inserting one char, so the check digits can pick
    the right one. Reads of exactly 44 are returned unchanged."""
    n = len(raw)
    if n == MRZ_LEN:
        return [raw]
    if n < 36 or n > 48:
        return [_fit_length(raw)]
    out = []
    if n > MRZ_LEN:
        extra = n - MRZ_LEN
        if extra == 1:
            out = [raw[:i] + raw[i + 1:] for i in range(n)]
        else:
            out = [raw[:MRZ_LEN]]
    else:
        missing = MRZ_LEN - n
        if missing == 1:
            out = [raw[:i] + "<" + raw[i:] for i in range(n + 1)] + [raw + "<"]
        else:
            out = [_fit_length(raw)]
    return out


# --------------------------------------------------------------------------
# Image side: locate, preprocess, read
# --------------------------------------------------------------------------


def _locate_mrz_block(gray: np.ndarray) -> Optional[Tuple[int, int, int, int]]:
    """Morphological text-block detector. Returns (x, y, w, h) of the most
    MRZ-like region (wide, short, bottom-most) or None."""
    h0, w0 = gray.shape[:2]
    scale = 800.0 / w0 if w0 > 800 else 1.0
    small = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA) if scale != 1.0 else gray
    h, w = small.shape[:2]
    rect_k = cv2.getStructuringElement(cv2.MORPH_RECT, (max(13, w // 40), max(5, w // 120)))
    blur = cv2.GaussianBlur(small, (3, 3), 0)
    blackhat = cv2.morphologyEx(blur, cv2.MORPH_BLACKHAT, rect_k)
    grad = cv2.Sobel(blackhat, cv2.CV_32F, 1, 0, ksize=-1)
    grad = np.absolute(grad)
    mn, mx = grad.min(), grad.max()
    if mx - mn < 1e-6:
        return None
    grad = (255 * (grad - mn) / (mx - mn)).astype("uint8")
    grad = cv2.morphologyEx(grad, cv2.MORPH_CLOSE, rect_k)
    thresh = cv2.threshold(grad, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)[1]
    close_k = cv2.getStructuringElement(cv2.MORPH_RECT, (max(21, w // 30), max(9, w // 60)))
    thresh = cv2.morphologyEx(thresh, cv2.MORPH_CLOSE, close_k)
    thresh = cv2.erode(thresh, None, iterations=2)
    contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    lines_found = []
    for c in contours:
        x, y, cw, ch = cv2.boundingRect(c)
        if cw < w * 0.55 or ch < max(5, h * 0.008) or ch > h * 0.2:
            continue
        if cw / float(ch) < 6.0:
            continue
        lines_found.append((y, x, cw, ch))
    if not lines_found:
        return None
    lines_found.sort(reverse=True)  # bottom-most first
    y, x, cw, ch = lines_found[0]
    x0, y0, x1, y1 = x, y, x + cw, y + ch
    # A TD3 MRZ is TWO lines: absorb the next line up when it is close by.
    for (y2, x2, cw2, ch2) in lines_found[1:]:
        if y0 - (y2 + ch2) <= 3.0 * max(ch, ch2) and abs(cw2 - cw) <= 0.25 * cw:
            x0, y0 = min(x0, x2), min(y0, y2)
            x1, y1 = max(x1, x2 + cw2), max(y1, y + ch)
            break
    x, y, cw, ch = x0, y0, x1 - x0, y1 - y0
    inv = 1.0 / scale
    # pad: MRZ line height is small relative to the block; keep a safe margin
    padx, pady = int(cw * 0.03), int(ch * 0.35)
    X0 = max(0, int((x - padx) * inv))
    Y0 = max(0, int((y - pady) * inv))
    X1 = min(w0, int((x + cw + padx) * inv))
    Y1 = min(h0, int((y + ch + pady) * inv))
    return X0, Y0, X1 - X0, Y1 - Y0


def _crop_candidates(gray: np.ndarray) -> List[Tuple[str, np.ndarray]]:
    h, w = gray.shape[:2]
    out: List[Tuple[str, np.ndarray]] = []
    box = _locate_mrz_block(gray)
    if box:
        x, y, bw, bh = box
        out.append(("detected-block", gray[y:y + bh, x:x + bw]))
    for frac, label in ((0.78, "bottom-22%"), (0.66, "bottom-34%"), (0.50, "bottom-50%")):
        out.append((label, gray[int(h * frac):h, :]))
    return out


def _binarise_variants(gray: np.ndarray) -> List[Tuple[str, np.ndarray]]:
    """Several pre-processings of one crop. All return dark-text-on-white."""
    h, w = gray.shape[:2]
    target_w = 2000
    scale = target_w / float(w) if w else 1.0
    interp = cv2.INTER_CUBIC if scale > 1 else cv2.INTER_AREA
    g = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=interp)
    g = cv2.GaussianBlur(g, (3, 3), 0)

    variants: List[Tuple[str, np.ndarray]] = []
    variants.append(("otsu", cv2.threshold(g, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)[1]))
    clahe = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(4, 8))
    gc = clahe.apply(g)
    variants.append(("clahe-otsu", cv2.threshold(gc, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)[1]))
    variants.append(("adaptive", cv2.adaptiveThreshold(g, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 41, 14)))
    variants.append(("gray", g))
    return variants


def _split_two_lines(binary: np.ndarray) -> Optional[List[np.ndarray]]:
    """Finds the two text rows with a horizontal ink profile. Works with
    either polarity (the majority colour is treated as background)."""
    h, w = binary.shape[:2]
    if h < 20 or w < 40:
        return None
    # Work on Otsu of the input so grey variants also work
    if binary.dtype != np.uint8 or len(np.unique(binary)) > 2:
        binary = cv2.threshold(binary, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)[1]
    bg = 255 if (binary == 255).sum() >= (binary == 0).sum() else 0
    ink = (binary != bg)
    rows = ink.sum(axis=1) > max(3, int(w * 0.02))
    runs: List[List[int]] = []
    start = None
    for y, on in enumerate(rows.tolist()):
        if on and start is None:
            start = y
        elif not on and start is not None:
            runs.append([start, y])
            start = None
    if start is not None:
        runs.append([start, h])
    merged: List[List[int]] = []
    for r in runs:
        if merged and r[0] - merged[-1][1] <= max(4, int(h * 0.02)):
            merged[-1][1] = r[1]
        else:
            merged.append(r)
    if not merged:
        return None
    tallest = max(r[1] - r[0] for r in merged)
    plausible = [r for r in merged if (r[1] - r[0]) >= max(8, tallest * 0.4)]
    if len(plausible) < 2:
        return None
    (a0, a1), (b0, b1) = plausible[-2:]
    pad = max(6, int((a1 - a0) * 0.3))
    return [binary[max(0, a0 - pad):min(h, a1 + pad), :], binary[max(0, b0 - pad):min(h, b1 + pad), :]]


def _with_margin(img: np.ndarray) -> np.ndarray:
    bg = int(np.median(img[:3, :])) if img.size else 255
    return cv2.copyMakeBorder(img, 14, 14, 30, 30, cv2.BORDER_CONSTANT, value=bg)


def _tesseract_ocr_fn() -> Callable[[np.ndarray, str], str]:
    import ocr_providers

    prov = ocr_providers.TesseractOCRProvider()

    def fn(img: np.ndarray, config: str) -> str:
        return prov.ocr_text(img, config=config)

    return fn


def _clean(raw: str) -> str:
    return _CHARSET_RE.sub("", raw.upper().replace(" ", "").replace("\n", ""))


_LINE_CFG_7 = f"--psm 7 -c tessedit_char_whitelist={MRZ_CHARSET}"
_LINE_CFG_13 = f"--psm 13 -c tessedit_char_whitelist={MRZ_CHARSET}"
_BLOCK_CFG_6 = f"--psm 6 -c tessedit_char_whitelist={MRZ_CHARSET}"


def _rotate(img: np.ndarray, deg: int) -> np.ndarray:
    if deg == 0:
        return img
    code = {90: cv2.ROTATE_90_CLOCKWISE, 180: cv2.ROTATE_180, 270: cv2.ROTATE_90_COUNTERCLOCKWISE}[deg]
    return cv2.rotate(img, code)


def _deskew_small(gray: np.ndarray) -> np.ndarray:
    """Straightens a slightly tilted crop using the ink's min-area rectangle."""
    try:
        th = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)[1]
        ys, xs = np.where(th > 0)
        if len(xs) < 200:
            return gray
        pts = np.column_stack((xs, ys)).astype(np.float32)
        (_, _), (rw, rh), ang = cv2.minAreaRect(pts)
        if rw < rh:
            ang = ang - 90 if ang > 45 else ang
        else:
            ang = ang if ang < 45 else ang - 90
        if ang > 45:
            ang -= 90
        if ang < -45:
            ang += 90
        if abs(ang) < 0.4 or abs(ang) > 12:
            return gray
        h, w = gray.shape[:2]
        M = cv2.getRotationMatrix2D((w / 2, h / 2), ang, 1.0)
        return cv2.warpAffine(gray, M, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)
    except Exception:
        return gray


# --------------------------------------------------------------------------
# Public API
# --------------------------------------------------------------------------


def evaluate_candidates(line1_reads: List[str], line2_reads: List[str]) -> Optional[Dict[str, Any]]:
    """Pure (image-free) selection logic: given many raw reads of line 1 and
    line 2, repair each, vote, and return the best pair. Exposed separately
    so it can be unit-tested without OCR."""
    l2_variants: List[str] = []
    for r in line2_reads:
        if len(r) >= 30:
            l2_variants.extend(_align_line2(r))
    l1_reads = [r for r in line1_reads if len(r) >= 25]
    if not l2_variants or not l1_reads:
        return None

    repaired2 = [repair_line2(v) for v in l2_variants]
    votes2 = Counter(x["line"] for x in repaired2)
    best2 = max(repaired2, key=lambda x: (x["score"] + 0.6 * min(votes2[x["line"]], 6), -len(x["repairs"])))

    # Position-wise consensus of the 44-char reads is also a candidate.
    exact = [v for v in l2_variants if len(v) == MRZ_LEN]
    if len(exact) >= 3:
        consensus = "".join(Counter(col).most_common(1)[0][0] for col in zip(*exact))
        rc = repair_line2(consensus)
        if rc["score"] > best2["score"]:
            best2 = rc

    repaired1 = [repair_line1(r) for r in l1_reads]
    votes1 = Counter(x["line"] for x in repaired1)
    best1 = max(repaired1, key=lambda x: (x["score"] + 0.6 * min(votes1[x["line"]], 6), -len(x["repairs"])))

    return {"line1": best1["line"], "line2": best2["line"], "line1Info": best1, "line2Info": best2}


def _rotation_order(gray: np.ndarray, rotations: Tuple[int, ...], ocr: Callable[[np.ndarray, str], str]) -> List[int]:
    """Cheaply ranks the rotations so the right one is tried first: for each,
    locate the MRZ block (or use the bottom band) and measure how MRZ-like one
    quick OCR read is (long runs of A-Z0-9< and many '<' fillers)."""
    scored = []
    for order, rot in enumerate(rotations):
        rimg = _rotate(gray, rot)
        box = _locate_mrz_block(rimg)
        if box:
            x, y, bw, bh = box
            crop = rimg[y:y + bh, x:x + bw]
        else:
            crop = rimg[int(rimg.shape[0] * 0.66):, :]
        if crop.size == 0:
            scored.append((0.0, -order, rot))
            continue
        try:
            variant = _binarise_variants(crop)[0][1]
            txt = ocr(_with_margin(variant), _BLOCK_CFG_6)
        except Exception:
            txt = ""
        rows = [_clean(t) for t in txt.splitlines()]
        sc = sum(len(r) for r in rows if len(r) >= 30) + 3 * sum(r.count("<") for r in rows if len(r) >= 30)
        scored.append((float(sc) + (5 if box else 0), -order, rot))
    scored.sort(reverse=True)
    return [rot for _, _, rot in scored]


# Repairs that CHANGE real data characters via the check-digit SEARCH (as
# opposed to a letter/digit type fix that the check digit then confirms). A
# read that needed one of these keeps being cross-checked against further
# attempts instead of ending the search.
_RISKY_REPAIR_FIELDS = ("passportNumber", "dateOfBirth", "dateOfExpiry", "personalNumber")


def _confidence_label(checks: Dict[str, bool], n_repairs: int, name_ok: bool) -> str:
    all_ok = all(checks.values())
    if all_ok and n_repairs == 0 and name_ok:
        return "high"
    if all_ok and n_repairs <= 3:
        return "medium"
    if sum(1 for v in checks.values() if v) >= 3:
        return "low"
    return "very-low"


def read_mrz(
    image_bgr: np.ndarray,
    ocr_fn: Optional[Callable[[np.ndarray, str], str]] = None,
    max_seconds: float = 60.0,
    rotations: Tuple[int, ...] = (0, 180, 90, 270),
) -> Dict[str, Any]:
    """Reads the TD3 MRZ from an image (BGR numpy array). Always returns a
    dict; `found` is False when nothing MRZ-like could be read."""
    t0 = time.time()
    ocr = ocr_fn or _tesseract_ocr_fn()
    gray0 = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY) if image_bgr.ndim == 3 else image_bgr

    line1_reads: List[str] = []
    line2_reads: List[str] = []
    attempts = 0
    best: Optional[Dict[str, Any]] = None
    best_meta: Dict[str, Any] = {}
    warnings: List[str] = []

    def consider(meta: Dict[str, Any]) -> bool:
        """Re-evaluates the pooled reads. Returns True when a clean,
        unrepaired, fully check-digit-valid result exists (early exit)."""
        nonlocal best, best_meta
        ev = evaluate_candidates(line1_reads, line2_reads)
        if not ev:
            return False
        total = ev["line2Info"]["score"] + ev["line1Info"]["score"]
        if best is None or total > best["_total"]:
            ev["_total"] = total
            best = ev
            best_meta = dict(meta)
        risky = [r for r in ev["line2Info"]["repairs"] if r.get("kind") == "search" and r["field"] in _RISKY_REPAIR_FIELDS]
        return all(ev["line2Info"]["checks"].values()) and not risky and ev["line1Info"]["score"] >= 10

    done = False
    for rot in _rotation_order(gray0, rotations, ocr):
        if done or time.time() - t0 > max_seconds:
            break
        rimg = _rotate(gray0, rot)
        for crop_name, crop in _crop_candidates(rimg):
            if done or time.time() - t0 > max_seconds:
                break
            if crop.size == 0:
                continue
            crop = _deskew_small(crop)
            for var_name, variant in _binarise_variants(crop):
                if done or time.time() - t0 > max_seconds:
                    break
                lines = _split_two_lines(variant)
                got_any = False
                if lines:
                    for cfg in (_LINE_CFG_7, _LINE_CFG_13):
                        try:
                            a = _clean(ocr(_with_margin(lines[0]), cfg))
                            b = _clean(ocr(_with_margin(lines[1]), cfg))
                        except Exception as exc:  # OCR engine failure must never crash the lab/site
                            warnings.append(f"OCR engine error: {type(exc).__name__}")
                            a = b = ""
                        attempts += 2
                        if len(a) >= 25 and len(b) >= 30:
                            line1_reads.append(a)
                            line2_reads.append(b)
                            got_any = True
                # Whole-block read as an extra opinion (some crops don't split cleanly)
                if not got_any:
                    try:
                        txt = ocr(_with_margin(variant), _BLOCK_CFG_6)
                    except Exception:
                        txt = ""
                    attempts += 1
                    rows = [_clean(t) for t in txt.splitlines()]
                    rows = [r for r in rows if len(r) >= 30]
                    if len(rows) >= 2:
                        line1_reads.append(rows[-2])
                        line2_reads.append(rows[-1])
                        got_any = True
                if got_any and consider({"rotation": rot, "crop": crop_name, "preprocess": var_name}):
                    done = True
        # If this rotation already produced a fully valid MRZ, don't try the others.
        if best is not None and all(best["line2Info"]["checks"].values()) and best["line1Info"]["score"] >= 10:
            break

    elapsed = round(time.time() - t0, 2)
    if best is None:
        return {
            "found": False,
            "confidence": "none",
            "attempts": attempts,
            "elapsedSeconds": elapsed,
            "warnings": warnings + ["No MRZ could be located/read. Try a sharper, better-lit photo with the two MRZ lines fully visible."],
            "repairs": [],
        }

    parsed = parse_mrz_td3(best["line1"], best["line2"])
    repairs = best["line1Info"]["repairs"] + best["line2Info"]["repairs"]
    checks = best["line2Info"]["checks"]
    name_ok = "<<" in best["line1"][5:].rstrip("<")
    label_repairs = [r for r in repairs if r["field"] != "compositeCheck"]
    confidence = _confidence_label(checks, len(label_repairs), name_ok)
    out_warnings = list(warnings)
    if confidence != "high":
        out_warnings.append("MRZ was read with corrections or failed check digits — please verify every field against the passport.")
    for k, ok in checks.items():
        if not ok:
            out_warnings.append(f"Check digit failed for {k}.")
    return {
        "found": True,
        "line1": best["line1"],
        "line2": best["line2"],
        "parsed": parsed,
        "checks": checks,
        "repairs": repairs,
        "confidence": confidence,
        "winningAttempt": best_meta,
        "attempts": attempts,
        "elapsedSeconds": elapsed,
        "warnings": out_warnings,
        "verificationStatus": "OCR Extracted — Please Verify",
    }


def fields_from_result(result: Dict[str, Any]) -> Dict[str, str]:
    """Flat, display-ready field dict (same keys every lab engine returns)."""
    if not result.get("found"):
        return {}
    p = result["parsed"]
    return {
        "surname": p.get("surname", ""),
        "givenNames": p.get("givenNames", ""),
        "passportNumber": p.get("passportNumber", ""),
        "nationality": p.get("nationality", ""),
        "issuingCountry": p.get("issuingCountry", ""),
        "dateOfBirth": p.get("dateOfBirth") or "",
        "sex": p.get("sex", ""),
        "dateOfExpiry": p.get("dateOfExpiry") or "",
        "personalNumber": p.get("personalNumber", ""),
    }


def read_mrz_from_path(path: str, page_index: int = 0, **kw: Any) -> Dict[str, Any]:
    """Convenience: image or PDF file -> read_mrz()."""
    import ocr_runner

    pages = ocr_runner.load_pages(path)
    img = ocr_runner.pil_to_bgr(pages[page_index])
    return read_mrz(img, **kw)
