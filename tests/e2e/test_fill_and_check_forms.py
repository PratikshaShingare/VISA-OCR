"""
End-to-end: the Fill Forms and Check Forms pages.

Fill Forms: a saved (invented) application pre-fills the Japan form, the
declaration questions stay unanswered until staff answer them, the PDF is
generated and the values are kept with the application.

Check Forms: a saved application's passport details + a supporting document
image (read by OCR) + a filled form with deliberate mistakes -> the mistakes
are listed, the correct details are not. Also narrow-screen overflow.

All data is invented (project rule 11).
"""

import asyncio
import os
import sys
import tempfile
import urllib.request
import json

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from playwright.async_api import async_playwright  # noqa: E402

from _common import BACKEND_BASE, BASE, Checks, fresh_load_and_login, future_date  # noqa: E402

C = Checks()

ARRIVAL = future_date(40)

SEED_APP = """(arrival) => {
  const S = window.KhannaState;
  const app = S.createApplication('e2e');
  S.updateApplication(app.id, {
    applicant: {
      firstName: 'ANITA RAJ', lastName: 'SHARMA', dob: '1980-05-14', sex: 'F', nationality: 'INDIAN',
      placeOfBirth: 'PUNE, MAHARASHTRA',
      address: { line1: '12 Sample Society', line2: 'Example Road', city: 'Pune', state: 'Maharashtra', pincode: '411001', country: 'India' },
      contact: { phone: '9800000000', email: '' },
      passport: { current: { number: 'Z1234567', issueDate: '2020-01-10', expiryDate: '2035-01-09', issuePlace: 'MUMBAI', type: 'P', countryCode: 'IND' } }
    },
    travel: { purpose: 'Tourism', startDate: arrival, endDate: '' },
    hotels: [{ id: 'H1', hotelName: 'Sample Hotel Tokyo', phone: '+81 3-0000-0000', address: '1-2-3 Sample Street, Koto City', city: 'Tokyo', country: 'Japan', checkIn: arrival, checkOut: '' }]
  });
  return app.id;
}"""


def make_bad_form(path):
    """A filled Japan form with three mistakes: surname typo, swapped
    passport-number digits, wrong sex. Made by the backend itself."""
    values = {
        "surname": "SHRAMA", "givenNames": "ANITA RAJ", "dob": "14/05/1980", "birthCity": "PUNE", "birthState": "MAHARASHTRA",
        "birthCountry": "INDIA", "sex": "M", "maritalStatus": "married", "nationality": "INDIAN", "passportType": "ordinary",
        "passportNumber": "Z1234576", "issuePlace": "MUMBAI", "issueDate": "10/01/2020", "issuingAuthority": "GOVERNMENT OF INDIA",
        "expiryDate": "09/01/2035", "purpose": "TOURISM", "lengthOfStay": "5 DAYS", "arrivalDate": ARRIVAL, "portOfEntry": "TOKYO",
        "airline": "SAMPLE AIR", "hotelName": "SAMPLE HOTEL TOKYO", "hotelTel": "+81 3-0000-0000", "hotelAddress": "1-2-3 SAMPLE STREET, KOTO CITY, TOKYO",
        "homeAddress": "12 SAMPLE SOCIETY, EXAMPLE ROAD, PUNE 411001", "mobile": "9800000000", "occupation": "ENGINEER",
        "guarantorName": "SAMPLE HOTEL TOKYO", "guarantorTel": "+81 3-0000-0000", "guarantorAddress": "1-2-3 SAMPLE STREET, KOTO CITY, TOKYO",
        "q1Crime": "no", "q2Prison": "no", "q3Deported": "no", "q4Drugs": "no", "q5Prostitution": "no", "q6Trafficking": "no",
    }
    req = urllib.request.Request(
        BACKEND_BASE + "/api/forms/fill",
        data=json.dumps({"formId": "japan-visa", "values": values}).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=60) as res, open(path, "wb") as fh:
        fh.write(res.read())


FLIGHT_TEXT = [
    "Travel Summary", "Traveler Mr Test Person",
    "23DEC 2000 MUMBAI BOM TOKYO NRT NH830 2 ALL NIPPON AIRWAYS",
    "24DEC 1315 TOKYO HND OSAKA KIX NH991 2 ALL NIPPON AIRWAYS",
    "02JAN 1115 TOKYO NRT MUMBAI BOM NH829 1 ALL NIPPON AIRWAYS",
    "Wednesday 23 December 2026", "All Nippon Airways NH 830",
    "Departure 23 December 20:00 Mumbai, (Chhatrapati S Maharaj) (+) Terminal: 2",
    "Arrival 24 December 07:25 Tokyo, (Narita Intl) (+) Terminal: 1",
    "Thursday 24 December 2026", "All Nippon Airways NH 991",
    "Departure 24 December 13:15 Tokyo, (Tokyo Intl Haneda) (+) Terminal: 2",
    "Arrival 24 December 14:40 Osaka, (Kansai International) (+) Terminal: 1",
    "Saturday 02 January 2027", "All Nippon Airways NH 829",
    "Departure 02 January 11:15 Tokyo, (Narita Intl) (+) Terminal: 1",
    "Arrival 02 January 18:35 Mumbai, (Chhatrapati S Maharaj) (+) Terminal: 2",
]


def make_flight_pdf(path):
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    c = canvas.Canvas(path, pagesize=A4)
    y = 800
    for line in FLIGHT_TEXT:
        c.drawString(40, y, line)
        y -= 18
    c.save()


def make_supporting_image(path):
    from PIL import Image, ImageDraw, ImageFont

    img = Image.new("RGB", (1400, 500), "white")
    d = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("DejaVuSans.ttf", 36)
    except Exception:  # noqa: BLE001
        font = ImageFont.load_default()
    lines = ["HOTEL BOOKING CONFIRMATION", "Guest: SHARMA ANITA RAJ", "Hotel: Sample Hotel Tokyo", "Address: 1-2-3 Sample Street, Koto City, Tokyo", "Tel: +81 3 0000 0000"]
    for i, line in enumerate(lines):
        d.text((40, 40 + i * 80), line, fill="black", font=font)
    img.save(path)


async def main():
    tmp = tempfile.mkdtemp(prefix="khanna_forms_e2e_")
    bad_form = os.path.join(tmp, "japan_form_with_mistakes.pdf")
    support = os.path.join(tmp, "hotel_booking.png")
    make_bad_form(bad_form)
    make_supporting_image(support)
    global FLIGHT_PDF, VOUCHER_PNG
    FLIGHT_PDF = os.path.join(tmp, "flight_booking.pdf")
    make_flight_pdf(FLIGHT_PDF)
    VOUCHER_PNG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "synthetic_hotel_voucher_1.png")

    async with async_playwright() as p:
        browser = await p.chromium.launch()
        ctx = await browser.new_context(viewport={"width": 1280, "height": 900}, accept_downloads=True)
        page = await ctx.new_page()
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)

        await fresh_load_and_login(page)
        app_id = await page.evaluate(SEED_APP, ARRIVAL)

        # ------------------------------------------------------------ Fill Forms
        await page.evaluate("location.hash = '#/fill-forms'")
        await page.wait_for_selector("[data-ff-form]", state="attached", timeout=15000)
        C.check("Fill Forms: Japan form listed", await page.locator("[data-ff-form] option[value='japan-visa']").count() == 1)
        C.check("Fill Forms: defaults applied before any source", await page.input_value("#ff-previousStays") == "NOT APPLICABLE")
        C.check("Fill Forms: nav link present in menu", await page.locator(".mobile-nav [data-nav-link='fill-forms']").count() == 1)

        await page.click("[data-ff-use-app]")
        await page.click(f"[data-action='pick-application'][data-app-id='{app_id}']")
        await page.wait_for_timeout(300)
        C.check("prefill: surname", await page.input_value("#ff-surname") == "SHARMA")
        C.check("prefill: given names", await page.input_value("#ff-givenNames") == "ANITA RAJ")
        C.check("prefill: DOB as DD-MM-YYYY", await page.input_value("#ff-dob") == "14-05-1980")
        C.check("prefill: birth city / state split", await page.input_value("#ff-birthCity") == "PUNE" and await page.input_value("#ff-birthState") == "MAHARASHTRA")
        C.check("prefill: sex radio Female", await page.is_checked("input[name='ffr-sex'][value='F']"))
        C.check("prefill: passport type Ordinary from 'P'", await page.is_checked("input[name='ffr-passportType'][value='ordinary']"))
        C.check("prefill: issuing authority for Indian passport", await page.input_value("#ff-issuingAuthority") == "GOVERNMENT OF INDIA")
        C.check("prefill: hotel name from Hotel Blocking", await page.input_value("#ff-hotelName") == "Sample Hotel Tokyo")
        C.check("prefill: hotel address joined with city/country", "Tokyo" in await page.input_value("#ff-hotelAddress") and "Japan" in await page.input_value("#ff-hotelAddress"))
        C.check("prefill: home address", (await page.input_value("#ff-homeAddress")).startswith("12 Sample Society"))
        C.check("prefill: arrival date", await page.input_value("#ff-arrivalDate") != "")
        C.check("prefill: tagged 'please verify'", await page.locator(".vf-tag").count() > 5)
        C.check("declaration questions NOT answered automatically", await page.locator("input[name='ffr-q1Crime']:checked").count() == 0)
        ready_text = await page.inner_text("[data-ff-generate-area]")
        C.check("generate area names what is still empty, as text", "Fill these before generating" in ready_text and "convicted of a crime" in ready_text, ready_text[:300])
        C.check("no progress block / jump buttons / open-close buttons", await page.locator("[data-ff-progress], [data-ff-jump], [data-ff-expand]").count() == 0)
        C.check("all sections are shown open (no folding)", await page.locator("details[data-ff-section]").count() == 0 and await page.locator("section[data-ff-section]").count() >= 6)
        C.check("empty needed answers are outlined", await page.locator(".vf-field--empty input[name='ffr-q1Crime']").count() == 2)

        await page.click("[data-ff-all-no]")
        C.check("answered questions are no longer outlined", await page.locator(".vf-field--empty input[name='ffr-q1Crime']").count() == 0)
        C.check("'answered No to all' ticks No", await page.is_checked("input[name='ffr-q6Trafficking'][value='no']"))
        await page.fill("#ff-portOfEntry", "Tokyo")
        await page.fill("#ff-airline", "Sample Air")
        await page.fill("#ff-occupation", "Engineer")
        await page.fill("#ff-dob", "31-02-1980")
        C.check("invalid date blocks Generate", await page.is_disabled("[data-ff-generate]"))
        await page.fill("#ff-dob", "14-05-1980")
        await page.click("[data-section-copy], [data-ff-copy]")
        C.check("'Same as the hotel above' copies guarantor", await page.input_value("#ff-guarantorName") == "Sample Hotel Tokyo")

        # Needed boxes still empty: Generate does not go ahead; those boxes are marked with an ⓘ.
        await page.click("[data-ff-generate]")
        await page.wait_for_timeout(400)
        C.check("Generate blocked while needed boxes are empty", await page.locator("iframe.vf-preview").count() == 0
                and await page.locator(".fg-missing").count() >= 2 and await page.locator(".fg-missing .fg-info--missing").count() >= 2)
        await page.check("input[name='ffr-maritalStatus'][value='single']")
        await page.fill("#ff-lengthOfStay", "7 DAYS")
        C.check("filling a box removes its red mark", await page.locator(".fg-missing #ff-lengthOfStay").count() == 0)
        await page.click("[data-ff-generate]")
        await page.wait_for_selector("iframe.vf-preview", timeout=60000)
        C.check("PDF preview shown", await page.locator("iframe.vf-preview").count() == 1)
        async with page.expect_download() as dl:
            await page.click("[data-ff-download]")
        download = await dl.value
        path = os.path.join(tmp, download.suggested_filename)
        await download.save_as(path)
        C.check("download is a PDF named after the applicant", download.suggested_filename == "Japan_Visa_Application_Form_ANITA_RAJ_SHARMA.pdf", download.suggested_filename)
        with open(path, "rb") as fh:
            C.check("download starts with %PDF", fh.read(4) == b"%PDF")
        C.check("no 'too long' warning for normal text", "Too long to fit" not in await page.inner_text("[data-ff-generate-area]"))
        await page.fill("#ff-employerAddress", "A" * 700)
        await page.click("[data-ff-generate]")
        await page.wait_for_selector("iframe.vf-preview", timeout=60000)
        warn = await page.inner_text("[data-ff-generate-area]")
        C.check("text too long even when shrunk is reported", "Too long to fit" in warn and "Employer — Address" in warn, warn[:300])
        await page.fill("#ff-employerAddress", "-")
        saved = await page.evaluate(f"KhannaState.getApplication('{app_id}').visaForms['japan-visa'].values.occupation")
        C.check("values kept with the application", saved == "Engineer", str(saved))

        # Reopen: saved values come back (not re-filled from the application)
        await page.click("[data-ff-reset]")
        C.check("Start empty clears", await page.input_value("#ff-surname") == "")
        await page.click("[data-ff-use-app]")
        await page.click(f"[data-action='pick-application'][data-app-id='{app_id}']")
        await page.wait_for_timeout(300)
        C.check("reopen restores saved values", await page.input_value("#ff-occupation") == "Engineer")

        # ---- Hotel Blocking pick, hotel voucher, flight booking
        other_id = await page.evaluate("""() => {
          const S = window.KhannaState; const a = S.createApplication('e2e');
          S.updateApplication(a.id, { applicant: { firstName: 'RAVI', lastName: 'MEHTA' },
            hotels: [{ id: 'H9', hotelName: 'Second Hotel Osaka', phone: '+81 6-0000-0000', address: '9 Example Dori', city: 'Osaka', country: 'Japan', checkIn: '2031-01-05', checkOut: '2031-01-08' }] });
          return a.id; }""")
        await page.click("[data-ff-hotel-list]")
        await page.click(f"[data-ff-hotel-app='{other_id}']")
        C.check("Use Hotel Blocking fills the hotel", await page.input_value("#ff-hotelName") == "Second Hotel Osaka")
        C.check("...and the guarantor follows the hotel", await page.input_value("#ff-guarantorName") == "Second Hotel Osaka")
        C.check("...tagged From Hotel Blocking", "From Hotel Blocking" in await page.inner_text("[data-view='fill-forms']"))
        C.check("...applicant left unchanged", await page.input_value("#ff-surname") == "SHARMA")

        await page.set_input_files("[data-ff-voucher]", VOUCHER_PNG)
        await page.wait_for_function("() => /Hotel details from|No hotel name|could not/.test(document.querySelector('[data-ff-source]').innerText)", timeout=120000)
        status = await page.inner_text("[data-ff-source]")
        C.check("hotel voucher read and applied", "Hotel details from synthetic_hotel_voucher_1.png" in status, status[-300:])
        C.check("...hotel name changed from the voucher", await page.input_value("#ff-hotelName") not in ("", "Second Hotel Osaka"))

        await page.set_input_files("[data-ff-flight]", FLIGHT_PDF)
        await page.wait_for_selector(".vf-legs", timeout=60000)
        C.check("flight: arrival = landing date in Japan", await page.input_value("#ff-arrivalDate") == "24-12-2026")
        C.check("flight: length of stay", await page.input_value("#ff-lengthOfStay") == "10 DAYS")
        C.check("flight: port of entry", await page.input_value("#ff-portOfEntry") == "TOKYO")
        C.check("flight: airline", await page.input_value("#ff-airline") == "ALL NIPPON AIRWAYS")
        legs = await page.inner_text(".vf-legs")
        C.check("flight: legs shown with the connection marked", "Connection inside the country" in legs and "Arrival into Japan" in legs, legs[:300])

        # ------------------------------------------------------------ Check Forms
        await page.evaluate("location.hash = '#/form-check'")
        await page.wait_for_selector("[data-fc-check]", timeout=10000)
        C.check("Check: button disabled with nothing uploaded", await page.is_disabled("[data-fc-check]"))
        C.check("Check: three separate upload areas", await page.locator("[data-fc-file]").count() == 3)
        await page.click("[data-fc-use-app]")
        await page.click(f"[data-action='pick-application'][data-app-id='{app_id}']")
        await page.wait_for_selector("[data-fc-detail='passportNumber']")
        C.check("Check: passport details from application", await page.input_value("[data-fc-detail='passportNumber']") == "Z1234567")
        await page.set_input_files("[data-fc-file='supporting']", support)
        await page.set_input_files("[data-fc-file='form']", bad_form)
        await page.wait_for_function("() => !document.querySelector('[data-fc-check]').disabled", timeout=120000)
        forms_text = await page.inner_text("[data-fc-forms]")
        C.check("Check: form recognised as the Japan form", "Japan" in forms_text, forms_text[:200])
        await page.click("[data-fc-check]")
        await page.wait_for_selector(".vf-result", timeout=60000)
        result = await page.inner_text("[data-fc-results]")
        C.check("result: surname typo found", "SHRAMA" in result and "should be 'SHARMA'" in result, result[:600])
        C.check("result: passport number swap found", "Z1234576" in result)
        C.check("result: wrong sex tick found", "The wrong box is ticked" in result)
        problems = await page.inner_text(".vf-result .vf-mistakes")
        C.check("result: correct DOB not listed as a problem", "Date of birth" not in problems)
        C.check("result: only mistakes are shown (no 'matching' list, chip or table)",
                "matching" not in result.lower() and await page.locator(".vf-result table").count() == 0
                and await page.locator(".vf-mistake").count() >= 3, result[:300])
        first = await page.inner_text(".vf-mistake >> nth=0")
        C.check("result: each mistake says what the form says and what it should say", "the form says" in first.lower() and "it should say" in first.lower(), first)
        hotel = await page.evaluate("KhannaFormCheck._state.forms[0].result.findings.filter(f => f.field === 'hotelName').map(f => f.status + ':' + f.source)")
        C.check("result: hotel found in supporting document (OCR)", hotel == ["ok:hotel_booking.png"], str(hotel))

        # Edit a passport detail -> stale -> check again
        await page.fill("[data-fc-detail='surname']", "SHRAMA")
        C.check("editing a passport detail asks to check again", "check again" in (await page.inner_text("[data-fc-ready]")).lower())
        await page.click("[data-fc-check]")
        await page.wait_for_function("() => !KhannaFormCheck._state.checking && !KhannaFormCheck._state.stale", timeout=60000)
        surname_rows = await page.evaluate("KhannaFormCheck._state.forms[0].result.findings.filter(f => f.field === 'surname' && f.label.indexOf('hotel_booking') === -1).map(f => f.status)")
        C.check("after edit the form's surname matches", surname_rows == ["ok"], str(surname_rows))
        flagged_support = await page.evaluate("KhannaFormCheck._state.forms[0].result.findings.some(f => f.field === 'surname' && f.label.indexOf('hotel_booking.png') !== -1 && f.status === 'check')")
        C.check("...and the supporting document's spelling is now the one flagged", flagged_support)

        # ------------------------------------------------------------ narrow screens
        for width in (320, 375, 768):
            await page.set_viewport_size({"width": width, "height": 800})
            for view in ("form-check", "fill-forms"):
                await page.evaluate(f"location.hash = '#/{view}'")
                await page.wait_for_timeout(300)
                overflow = await page.evaluate("document.documentElement.scrollWidth - window.innerWidth")
                C.check(f"{view} @ {width}px: no horizontal overflow", overflow <= 1, f"overflow {overflow}px")
        await page.set_viewport_size({"width": 390, "height": 800})
        await page.evaluate("location.hash = '#/form-check'")
        await page.wait_for_timeout(300)
        await page.screenshot(path=os.path.join(tmp, "form_check_390.png"), full_page=True)
        await page.set_viewport_size({"width": 1280, "height": 900})
        await page.screenshot(path=os.path.join(tmp, "form_check_1280.png"), full_page=True)
        await page.evaluate("location.hash = '#/fill-forms'")
        await page.wait_for_timeout(300)
        await page.screenshot(path=os.path.join(tmp, "fill_forms_1280.png"), full_page=True)
        print("screenshots in", tmp)

        real_errors = [e for e in errors if "favicon" not in e and "ERR_" not in e]
        C.check("no console errors", not real_errors, " | ".join(real_errors[:5]))
        await browser.close()
    C.report_and_exit()


if __name__ == "__main__":
    asyncio.run(main())
