"""
Builds backend/python/visa_forms/singapore_visa_application.pdf — the
Singapore "Form 14A — Application for Entry Visa" (IMM 14A) with fillable
fields placed exactly on its printed boxes.

The printed form (4 pages, from the embassy PDF the user supplied) is kept
untouched; only form fields are added on top:
  * every row of letter boxes  -> a "comb" text field (one letter per box);
    two-row names are two fields, filled in order by visa_forms.py
  * DD / MM / YYYY boxes        -> three comb fields
  * tick boxes                  -> radio groups that CAN be unticked
                                   (NoToggleToOff is not set)
  * underlined answers          -> plain text fields sitting on the line
  * the signature lines         -> no field (signed by hand)

Box positions are read from the PDF's own drawing (pdfplumber), so a field
always sits on its printed box. Run:

    python visa_forms/tools/make_singapore_form.py <blank-form.pdf>

Needs pypdf, pdfplumber and reportlab (the last two only for this tool, not for the app).
"""

from __future__ import annotations

import os
import sys

import pdfplumber
from pypdf import PdfReader, PdfWriter
from pypdf.generic import (
    ArrayObject,
    BooleanObject,
    DecodedStreamObject,
    DictionaryObject,
    FloatObject,
    NameObject,
    NumberObject,
    TextStringObject,
)

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(os.path.dirname(HERE), "singapore_visa_application.pdf")

FF_MULTILINE = 1 << 12
FF_RADIO = 1 << 15
FF_DONOTSPELL = 1 << 22
FF_DONOTSCROLL = 1 << 23
FF_COMB = 1 << 24

# --------------------------------------------------------------------------
# Field list: (page, kind, name, locator...)
#   comb:    (page, "comb", name, top, x0)          -> the box row found there
#   (PDF field names may not contain a full stop, hence fullName_1, dob_day ...)
#   radio:   (page, "radio", group, state, top, x0) -> one tick box
#   line:    (page, "line", name, x0, x1, line_top, height, multiline)
# `top` / `x0` are approximate (points from the top-left); the exact box is
# looked up in the PDF drawing.
# --------------------------------------------------------------------------
FIELDS = [
    # ---- page 1: Part I
    (0, "comb", "fullName_1", 177.3, 139.9), (0, "comb", "fullName_2", 199.6, 140.0),
    (0, "comb", "alias_1", 227.8, 140.1), (0, "comb", "alias_2", 249.7, 140.1),
    (0, "comb", "dob_day", 283.3, 112.2), (0, "comb", "dob_month", 283.3, 159.7), (0, "comb", "dob_year", 283.3, 208.7),
    (0, "radio", "sex", "Male", 290.0, 347.0), (0, "radio", "sex", "Female", 289.7, 398.4),
    (0, "radio", "maritalStatus", "Single", 325.3, 104.8), (0, "radio", "maritalStatus", "Married", 325.3, 157.0),
    (0, "radio", "maritalStatus", "Separated", 325.2, 213.4), (0, "radio", "maritalStatus", "Divorced", 325.3, 277.4),
    (0, "radio", "maritalStatus", "Widowed", 324.4, 336.2), (0, "radio", "maritalStatus", "Cohabited", 324.9, 398.6),
    (0, "radio", "maritalStatus", "Customary", 324.5, 465.6),
    (0, "radio", "spouseStatus", "Citizen", 357.6, 159.4), (0, "radio", "spouseStatus", "PR", 377.0, 159.7),
    (0, "radio", "spouseStatus", "Others", 399.6, 159.8),
    (0, "comb", "spouseNricCitizen", 351.7, 370.9), (0, "comb", "spouseNricPR", 376.5, 371.2),
    (0, "line", "spouseOtherNationality", 281.6, 553.8, 418.2, 14, False),
    (0, "comb", "birthCountryPlace", 429.5, 141.7), (0, "comb", "birthState", 455.3, 141.5),
    (0, "comb", "race", 480.9, 140.9), (0, "comb", "nationality", 506.3, 140.7),
    (0, "radio", "documentType", "International", 558.3, 197.1), (0, "radio", "documentType", "Diplomatic", 558.3, 316.3),
    (0, "radio", "documentType", "Official", 558.3, 426.2), (0, "radio", "documentType", "Service", 571.4, 197.0),
    (0, "radio", "documentType", "Identity", 571.3, 316.2), (0, "radio", "documentType", "CertIdentity", 571.3, 426.5),
    (0, "radio", "documentType", "Others", 584.9, 197.2),
    (0, "line", "documentTypeOther", 310.8, 563.4, 598.3, 13, False),
    (0, "comb", "passportNumber", 609.6, 139.2),
    (0, "comb", "issueDate_day", 642.3, 139.3), (0, "comb", "issueDate_month", 642.3, 188.3), (0, "comb", "issueDate_year", 642.3, 237.2),
    (0, "comb", "expiryDate_day", 642.3, 395.3), (0, "comb", "expiryDate_month", 642.9, 444.1), (0, "comb", "expiryDate_year", 642.9, 493.4),
    (0, "comb", "issueCountryPlace", 682.8, 139.9),
    (0, "comb", "prcId", 733.4, 141.6),
    # ---- page 2: address in country of origin, Part II
    (1, "comb", "originCountry", 70.4, 141.2), (1, "comb", "originState", 104.4, 141.2),
    (1, "comb", "originPrefecture", 137.9, 140.7), (1, "comb", "originCounty", 168.5, 141.2),
    # Address: the printed line, plus the space above it (as in the handwritten sample).
    (1, "line", "originAddress_1", 72.5, 569.5, 206.2, 13, False),
    (1, "line", "originAddress_2", 72.5, 569.5, 221.2, 13, False),
    (1, "comb", "email", 259.9, 139.9), (1, "comb", "contactNumber", 286.1, 139.8), (1, "comb", "occupation", 313.3, 139.9),
    (1, "radio", "education", "None", 345.2, 142.3), (1, "radio", "education", "Primary", 344.7, 258.1),
    (1, "radio", "education", "Secondary", 344.7, 318.6), (1, "radio", "education", "PreUniversity", 345.1, 390.4),
    (1, "radio", "education", "Diploma", 366.8, 142.3), (1, "radio", "education", "University", 366.4, 207.8),
    (1, "radio", "education", "PostGraduate", 366.8, 286.9),
    (1, "comb", "annualIncome", 397.8, 142.6), (1, "comb", "religion", 428.2, 142.2),
    (1, "comb", "arrivalDate_day", 455.8, 200.8), (1, "comb", "arrivalDate_month", 455.8, 249.8), (1, "comb", "arrivalDate_year", 455.8, 298.6),
    (1, "radio", "visaType", "Single", 503.1, 95.9), (1, "radio", "visaType", "Double", 502.9, 184.9),
    (1, "radio", "visaType", "Triple", 502.6, 275.0), (1, "radio", "visaType", "Multiple", 502.6, 364.4),
    (1, "radio", "purpose", "Social", 525.3, 137.7), (1, "radio", "purpose", "Business", 525.3, 210.4),
    (1, "line", "purposeDetails", 114.0, 542.5, 574.2, 14, False),
    (1, "radio", "stayLength", "Less30", 587.6, 240.1), (1, "radio", "stayLength", "More30", 586.7, 353.1),
    # One field per printed line, so the writing sits on the lines.
    (1, "line", "stayReason_1", 33.5, 567.4, 654.7, 13, False),
    (1, "line", "stayReason_2", 34.5, 567.4, 672.7, 13, False),
    # ---- page 3: address in Singapore, residence abroad, travelling companion
    (2, "radio", "stayPlace", "NextOfKin", 89.6, 24.1), (2, "radio", "stayPlace", "Relative", 89.6, 121.8),
    (2, "radio", "stayPlace", "Friend", 90.1, 213.0), (2, "radio", "stayPlace", "Hotel", 89.6, 300.6),
    (2, "radio", "stayPlace", "Others", 89.6, 348.4),
    (2, "line", "stayPlaceOther", 466.9, 568.0, 103.6, 13, False),
    (2, "comb", "sgBlock", 127.7, 29.6), (2, "comb", "sgFloor", 127.7, 159.2), (2, "comb", "sgUnit", 127.7, 245.6),
    (2, "comb", "sgPostalCode", 127.7, 360.8), (2, "comb", "sgStreet", 152.8, 97.5),
    (2, "line", "sgContactNo", 501.3, 572.3, 168.4, 13, False),
    (2, "line", "sgBuildingName", 97.8, 566.4, 200.3, 14, False),
    (2, "radio", "residedAbroad", "Yes", 243.5, 58.8), (2, "radio", "residedAbroad", "No", 243.2, 111.7),
    (2, "line", "abroadCountry", 22.9, 134.2, 428.8, 125, True),
    (2, "line", "abroadAddress", 134.7, 453.2, 428.8, 125, True),
    (2, "line", "abroadFrom", 453.7, 516.9, 428.8, 125, True),
    (2, "line", "abroadTo", 517.4, 580.8, 428.8, 125, True),
    (2, "comb", "companionRelationship", 481.2, 139.0),
    (2, "comb", "companionName_1", 538.3, 139.2), (2, "comb", "companionName_2", 557.6, 139.1),
    (2, "comb", "companionDob_day", 593.3, 141.9), (2, "comb", "companionDob_month", 593.3, 189.3), (2, "comb", "companionDob_year", 593.3, 238.3),
    (2, "radio", "companionSex", "Male", 594.9, 371.3), (2, "radio", "companionSex", "Female", 595.1, 423.5),
    (2, "comb", "companionNationality", 634.7, 139.7), (2, "comb", "companionDocument", 663.1, 140.3),
    # ---- page 4: Part III local contact, Part IV antecedents, Part V (date only — no signature field)
    (3, "comb", "localContactName_1", 74.3, 139.7), (3, "comb", "localContactName_2", 94.1, 139.8),
    (3, "comb", "localContactRelationship", 133.2, 139.7),
    (3, "line", "localContactNo", 90.8, 205.4, 195.7, 14, False),
    (3, "line", "localContactEmail", 320.2, 537.9, 195.3, 14, False),
    (3, "radio", "qRefused", "Yes", 254.4, 501.9), (3, "radio", "qRefused", "No", 254.4, 549.0),
    (3, "radio", "qConvicted", "Yes", 272.4, 501.9), (3, "radio", "qConvicted", "No", 272.4, 549.0),
    (3, "radio", "qProhibited", "Yes", 290.4, 501.9), (3, "radio", "qProhibited", "No", 290.4, 549.0),
    (3, "radio", "qOtherIdentity", "Yes", 307.4, 501.9), (3, "radio", "qOtherIdentity", "No", 307.4, 549.0),
    (3, "line", "yesDetails_1", 27.2, 567.5, 375.5, 13, False),
    (3, "line", "yesDetails_2", 27.8, 568.0, 391.5, 13, False),
    (3, "line", "yesDetails_3", 27.2, 567.5, 406.5, 13, False),
    (3, "line", "declarationDate", 84.8, 162.9, 787.3, 13, False),
]


def find_boxes(page, top, x0, tol=2.5):
    """The run of adjacent boxes whose first box is at (top, x0)."""
    cells = [r for r in page.rects if 8 <= r["width"] <= 20 and 8 <= r["height"] <= 21 and abs(r["top"] - top) <= tol]
    cells.sort(key=lambda r: r["x0"])
    start = [r for r in cells if abs(r["x0"] - x0) <= tol]
    if not start:
        raise SystemExit(f"No box at page {page.page_number} top {top} x0 {x0}")
    run = [start[0]]
    for r in cells:
        if r["x0"] <= run[-1]["x0"] + 1:
            continue
        if r["x0"] - run[-1]["x1"] > 2:
            break
        run.append(r)
    return run


def stream(writer, content: bytes, bbox, resources=None):
    s = DecodedStreamObject()
    s.set_data(content)
    s.update({
        NameObject("/Type"): NameObject("/XObject"),
        NameObject("/Subtype"): NameObject("/Form"),
        NameObject("/BBox"): ArrayObject([FloatObject(v) for v in bbox]),
    })
    if resources is not None:
        s[NameObject("/Resources")] = resources
    return writer._add_object(s)


def rect_obj(x0, y0, x1, y1):
    return ArrayObject([FloatObject(round(v, 2)) for v in (x0, y0, x1, y1)])


def main(src):
    plumber = pdfplumber.open(src)
    reader = PdfReader(src)
    writer = PdfWriter(clone_from=reader)
    height = float(reader.pages[0].mediabox.height)

    helv = writer._add_object(DictionaryObject({
        NameObject("/Type"): NameObject("/Font"), NameObject("/Subtype"): NameObject("/Type1"),
        NameObject("/BaseFont"): NameObject("/Helvetica"), NameObject("/Encoding"): NameObject("/WinAnsiEncoding"),
    }))
    # Answers are written in Times, the printed form's own typeface (Times New
    # Roman), so filled text looks like part of the form. Times-Roman is one of
    # the 14 standard PDF fonts every viewer has; its widths are written into
    # the font so visa_forms.py can measure text exactly (wrapping, centring).
    from reportlab.pdfbase import pdfmetrics

    times_widths = pdfmetrics.getFont("Times-Roman").widths  # 256 entries, WinAnsi order
    tiro = writer._add_object(DictionaryObject({
        NameObject("/Type"): NameObject("/Font"), NameObject("/Subtype"): NameObject("/Type1"),
        NameObject("/BaseFont"): NameObject("/Times-Roman"), NameObject("/Encoding"): NameObject("/WinAnsiEncoding"),
        NameObject("/FirstChar"): NumberObject(32), NameObject("/LastChar"): NumberObject(255),
        NameObject("/Widths"): ArrayObject([NumberObject(int(w)) for w in times_widths[32:256]]),
    }))
    zadb = writer._add_object(DictionaryObject({
        NameObject("/Type"): NameObject("/Font"), NameObject("/Subtype"): NameObject("/Type1"),
        NameObject("/BaseFont"): NameObject("/ZapfDingbats"),
    }))
    dr = DictionaryObject({NameObject("/Font"): DictionaryObject({NameObject("/Helv"): helv, NameObject("/TiRo"): tiro, NameObject("/ZaDb"): zadb})})
    fields = ArrayObject()
    radio_groups = {}

    def annots_of(page_index):
        page = writer.pages[page_index]
        if "/Annots" not in page:
            page[NameObject("/Annots")] = ArrayObject()
        return page["/Annots"]

    for spec in FIELDS:
        page_index, kind = spec[0], spec[1]
        ppage = plumber.pages[page_index]
        page_ref = writer.pages[page_index].indirect_reference
        if kind == "comb":
            name, top, x0 = spec[2], spec[3], spec[4]
            run = find_boxes(ppage, top, x0)
            x_left, x_right = run[0]["x0"], run[-1]["x1"]
            y_top, y_bottom = run[0]["top"], run[0]["bottom"]
            size = 12 if (y_bottom - y_top) >= 18 else 11
            field = DictionaryObject({
                NameObject("/Type"): NameObject("/Annot"), NameObject("/Subtype"): NameObject("/Widget"),
                NameObject("/FT"): NameObject("/Tx"), NameObject("/T"): TextStringObject(name),
                NameObject("/Ff"): NumberObject(FF_COMB | FF_DONOTSCROLL | FF_DONOTSPELL),
                NameObject("/MaxLen"): NumberObject(len(run)),
                NameObject("/DA"): TextStringObject(f"/TiRo {size} Tf 0 g"),
                NameObject("/Rect"): rect_obj(x_left, height - y_bottom, x_right, height - y_top),
                NameObject("/F"): NumberObject(4), NameObject("/P"): page_ref,
                NameObject("/V"): TextStringObject(""),
            })
            ref = writer._add_object(field)
            annots_of(page_index).append(ref)
            fields.append(ref)
        elif kind == "line":
            name, x0, x1, line_top, h, multiline = spec[2:8]
            y_bottom = height - line_top + 1
            flags = FF_DONOTSPELL | (FF_MULTILINE if multiline else 0)
            field = DictionaryObject({
                NameObject("/Type"): NameObject("/Annot"), NameObject("/Subtype"): NameObject("/Widget"),
                NameObject("/FT"): NameObject("/Tx"), NameObject("/T"): TextStringObject(name),
                NameObject("/Ff"): NumberObject(flags),
                NameObject("/DA"): TextStringObject("/TiRo 11 Tf 0 g"),
                NameObject("/Rect"): rect_obj(x0 + 1, y_bottom, x1 - 1, y_bottom + h),
                NameObject("/F"): NumberObject(4), NameObject("/P"): page_ref,
                NameObject("/V"): TextStringObject(""),
            })
            ref = writer._add_object(field)
            annots_of(page_index).append(ref)
            fields.append(ref)
        elif kind == "radio":
            group, state, top, x0 = spec[2:6]
            box = find_boxes(ppage, top, x0)[0]
            w, h = box["x1"] - box["x0"], box["bottom"] - box["top"]
            if group not in radio_groups:
                parent = DictionaryObject({
                    NameObject("/FT"): NameObject("/Btn"), NameObject("/T"): TextStringObject(group),
                    # Radio, but NoToggleToOff is NOT set: a tick can be removed again.
                    NameObject("/Ff"): NumberObject(FF_RADIO),
                    NameObject("/V"): NameObject("/Off"),
                    NameObject("/Kids"): ArrayObject(),
                })
                pref = writer._add_object(parent)
                radio_groups[group] = pref
                fields.append(pref)
            pref = radio_groups[group]
            size = round(min(w, h) * 0.85, 1)
            on = stream(
                writer,
                f"q BT 0 g /ZaDb {size} Tf {round((w - size * 0.8) / 2, 2)} {round((h - size * 0.7) / 2, 2)} Td (4) Tj ET Q".encode(),
                (0, 0, w, h),
                DictionaryObject({NameObject("/Font"): DictionaryObject({NameObject("/ZaDb"): zadb})}),
            )
            off = stream(writer, b"", (0, 0, w, h))
            kid = DictionaryObject({
                NameObject("/Type"): NameObject("/Annot"), NameObject("/Subtype"): NameObject("/Widget"),
                NameObject("/Parent"): pref, NameObject("/F"): NumberObject(4), NameObject("/P"): page_ref,
                NameObject("/Rect"): rect_obj(box["x0"], height - box["bottom"], box["x1"], height - box["top"]),
                NameObject("/MK"): DictionaryObject({NameObject("/CA"): TextStringObject("4")}),
                NameObject("/DA"): TextStringObject(f"/ZaDb {size} Tf 0 g"),
                NameObject("/AS"): NameObject("/Off"),
                NameObject("/AP"): DictionaryObject({NameObject("/N"): DictionaryObject({NameObject("/" + state): on, NameObject("/Off"): off})}),
            })
            kref = writer._add_object(kid)
            pref.get_object()["/Kids"].append(kref)
            annots_of(page_index).append(kref)
        else:
            raise SystemExit(f"unknown kind {kind}")

    writer._root_object[NameObject("/AcroForm")] = DictionaryObject({
        NameObject("/Fields"): fields,
        NameObject("/DR"): dr,
        NameObject("/DA"): TextStringObject("/TiRo 12 Tf 0 g"),
        NameObject("/NeedAppearances"): BooleanObject(True),
    })
    writer.add_metadata({"/Title": "Form 14A — Application for Entry Visa (Singapore) — fillable"})
    with open(OUT, "wb") as fh:
        writer.write(fh)
    print("written", OUT, len(fields), "fields")


if __name__ == "__main__":
    main(sys.argv[1])
