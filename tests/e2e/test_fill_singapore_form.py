"""
End-to-end: Fill Forms with the Singapore Form 14A.

A saved (invented) application fills the passport part; Hotel Blocking fills
the "Address in Singapore" and Part III boxes; a flight booking fills the
arrival date and the "less than 30 days" tick; the PDF is generated with the
answers in the letter boxes. All data is invented (project rule 11).
"""

import asyncio
import os
import sys
import tempfile
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from playwright.async_api import async_playwright  # noqa: E402

from _common import BASE, Checks, fresh_load_and_login  # noqa: E402

C = Checks()

SEED = """() => {
  const S = window.KhannaState;
  const app = S.createApplication('e2e');
  S.updateApplication(app.id, {
    applicant: {
      firstName: 'ANITA RAJ', lastName: 'SHARMA', dob: '1980-05-14', sex: 'F', nationality: 'INDIAN', placeOfBirth: 'PUNE, MAHARASHTRA',
      address: { line1: 'E-6, 202 Sample Co-operative Housing Society, Plot 1, Sector 16', line2: 'Example Beach Road, Sanpada East', city: 'Navi Mumbai', state: 'Maharashtra', pincode: '400705', country: 'India' },
      contact: { phone: '+91 98000 00000', email: 'anita@example.com' },
      passport: { current: { number: 'Z1234567', issueDate: '2020-01-10', expiryDate: '2035-01-09', issuePlace: 'MUMBAI', type: 'P', countryCode: 'IND' } }
    },
    hotels: [{ id: 'H1', hotelName: 'Sample Garden Inn Singapore', phone: '+65 6000 0000', address: '#05-12, 3 Sample Rd, Singapore 219924', city: 'Singapore', country: 'Singapore', checkIn: '2030-12-04', checkOut: '2030-12-10' }]
  });
  return app.id;
}"""

FLIGHT_LINES = [
    "Friday 04 December 2026", "Singapore Airlines SQ 423",
    "Departure 03 December 23:35 Mumbai, (Chhatrapati S Maharaj)",
    "Arrival 04 December 07:45 Singapore, (Changi)",
    "Thursday 10 December 2026", "Singapore Airlines SQ 422",
    "Departure 10 December 20:40 Singapore, (Changi)",
    "Arrival 10 December 22:30 Mumbai, (Chhatrapati S Maharaj)",
]


def make_flight_pdf(path):
    from reportlab.pdfgen import canvas

    c = canvas.Canvas(path)
    y = 800
    for line in FLIGHT_LINES:
        c.drawString(40, y, line)
        y -= 18
    c.save()


async def main():
    tmp = tempfile.mkdtemp(prefix="khanna_sg_e2e_")
    flight = os.path.join(tmp, "sg_flight.pdf")
    make_flight_pdf(flight)
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page(viewport={"width": 1280, "height": 900}, accept_downloads=True)
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        await fresh_load_and_login(page)
        app_id = await page.evaluate(SEED)

        await page.evaluate("location.hash = '#/fill-forms'")
        await page.wait_for_selector("[data-ff-form]", timeout=15000)
        options = await page.eval_on_selector_all("[data-ff-form] option", "els => els.map(e => e.value)")
        C.check("both forms offered", "japan-visa" in options and "singapore-visa" in options, str(options))
        await page.select_option("[data-ff-form]", "singapore-visa")
        await page.wait_for_selector("#ff-fullName")
        C.check("Singapore defaults: alias NOT APPLICABLE, visa type Multiple", await page.input_value("#ff-alias") == "NOT APPLICABLE"
                and await page.is_checked("input[name='ffr-visaType'][value='multiple']"))

        await page.click("[data-ff-use-app]")
        await page.click(f"[data-action='pick-application'][data-app-id='{app_id}']")
        await page.wait_for_timeout(300)
        C.check("name: surname then given names", await page.input_value("#ff-fullName") == "SHARMA ANITA RAJ")
        C.check("date of birth", await page.input_value("#ff-dob") == "14/05/1980")
        C.check("place of birth 'INDIA PUNE'", await page.input_value("#ff-birthCountryPlace") == "INDIA PUNE")
        C.check("state of birth", await page.input_value("#ff-birthState") == "MAHARASHTRA")
        C.check("race INDIAN", await page.input_value("#ff-race") == "INDIAN")
        C.check("international passport ticked", await page.is_checked("input[name='ffr-documentType'][value='international']"))
        C.check("place of issue 'INDIA MUMBAI'", await page.input_value("#ff-issueCountryPlace") == "INDIA MUMBAI")
        C.check("email", await page.input_value("#ff-email") == "anita@example.com")
        C.check("mobile without +91", await page.input_value("#ff-contactNumber") == "9800000000", await page.input_value("#ff-contactNumber"))
        C.check("letter-box fields limited to their boxes", await page.get_attribute("#ff-passportNumber", "maxlength") == "15")
        C.check("antecedent questions not answered automatically", await page.locator("input[name='ffr-qRefused']:checked").count() == 0)

        await page.click("[data-ff-hotel-list]")
        await page.click(f"[data-ff-hotel-app='{app_id}']")
        C.check("hotel: Hotel ticked", await page.is_checked("input[name='ffr-stayPlace'][value='hotel']"))
        C.check("hotel: building name", await page.input_value("#ff-sgBuildingName") == "Sample Garden Inn Singapore")
        C.check("hotel: only the street name", await page.input_value("#ff-sgStreet") == "Sample Rd", await page.input_value("#ff-sgStreet"))
        C.check("hotel: house no. / floor / unit from the address", (await page.input_value("#ff-sgBlock"), await page.input_value("#ff-sgFloor"), await page.input_value("#ff-sgUnit")) == ("3", "05", "12"))
        C.check("hotel: postal code", await page.input_value("#ff-sgPostalCode") == "219924")
        C.check("hotel: local contact + relationship HOTEL", await page.input_value("#ff-localContactName") == "Sample Garden Inn Singapore"
                and await page.input_value("#ff-localContactRelationship") == "HOTEL")

        await page.set_input_files("[data-ff-flight]", flight)
        await page.wait_for_selector(".vf-legs", timeout=60000)
        C.check("flight: arrival = landing day in Singapore", await page.input_value("#ff-arrivalDate") == "04/12/2026")
        C.check("flight: less than 30 days ticked", await page.is_checked("input[name='ffr-stayLength'][value='less30']"))

        C.check("spouse questions hidden until Married is ticked", await page.locator("input[name='ffr-spouseStatus']").count() == 0)
        C.check("companion part closed for an adult", await page.locator("#ff-companionRelationship").count() == 0)
        C.check(">30-day reason hidden while 'Less than 30 days' is ticked", await page.locator("#ff-stayReason").count() == 0)
        C.check("short box answers sit four to a row", "vf-field--quarter" in (await page.get_attribute("#ff-sgFloor", "class") or "") or
                await page.locator(".vf-field--quarter #ff-sgFloor").count() == 1)
        for key, value in (("education", "postGraduate"), ("maritalStatus", "married")):
            await page.check(f"input[name='ffr-{key}'][value='{value}']")
        C.check("Married shows the spouse question", await page.locator("input[name='ffr-spouseStatus']").count() == 3)
        await page.check("input[name='ffr-spouseStatus'][value='others']")
        await page.fill("#ff-spouseOtherNationality", "Indian")
        await page.check("[data-ff-optional]")
        C.check("ticking 'aged 12 or under' opens the companion part", await page.locator("#ff-companionRelationship").count() == 1)
        await page.uncheck("[data-ff-optional]")
        await page.fill("#ff-annualIncome", "25000")
        await page.fill("#ff-religion", "Hindu")
        await page.fill("#ff-occupation", "Self employed")
        await page.check("input[name='ffr-residedAbroad'][value='no']")
        await page.click("[data-ff-all-no]")
        C.check("'answered No to all' ticks Part IV", await page.is_checked("input[name='ffr-qOtherIdentity'][value='no']"))

        await page.click("[data-ff-generate]")
        await page.wait_for_selector("iframe.vf-preview", timeout=60000)
        async with page.expect_download() as dl:
            await page.click("[data-ff-download]")
        download = await dl.value
        out = os.path.join(tmp, download.suggested_filename)
        await download.save_as(out)
        C.check("download named Singapore_Visa_Form_14A_…", download.suggested_filename.startswith("Singapore_Visa_Form_14A"), download.suggested_filename)
        import pypdf

        f = {k: str(v.get("/V") or "") for k, v in pypdf.PdfReader(out).get_fields().items()}
        C.check("PDF: name in the boxes", f.get("fullName_1") == "SHARMA ANITA RAJ")
        C.check("PDF: date of birth boxes", (f.get("dob_day"), f.get("dob_month"), f.get("dob_year")) == ("14", "05", "1980"))
        C.check("PDF: arrival boxes", (f.get("arrivalDate_day"), f.get("arrivalDate_month"), f.get("arrivalDate_year")) == ("04", "12", "2026"))
        C.check("PDF: postal code", f.get("sgPostalCode") == "219924")
        C.check("PDF: long address starts on the line above and ends on the printed line", f.get("originAddress_1", "").startswith("E-6, 202 SAMPLE")
                and "400705" in f.get("originAddress_2", ""), (f.get("originAddress_1"), f.get("originAddress_2")))
        C.check("PDF: NOT APPLICABLE centred in the companion boxes", f.get("companionRelationship", "").strip() == "NOT APPLICABLE" and f.get("companionRelationship", "").startswith("     "))
        C.check("PDF: spouse 'Others: INDIAN'", f.get("spouseStatus") == "/Others" and f.get("spouseOtherNationality") == "INDIAN")
        C.check("PDF: ticks", f.get("stayPlace") == "/Hotel" and f.get("qRefused") == "/No" and f.get("education") == "/PostGraduate")

        for width in (320, 390):
            await page.set_viewport_size({"width": width, "height": 800})
            await page.wait_for_timeout(200)
            overflow = await page.evaluate("document.documentElement.scrollWidth - innerWidth")
            C.check(f"no horizontal overflow at {width}px", overflow <= 1, str(overflow))
        C.check("no page errors", not errors, " | ".join(errors[:3]))
        await browser.close()
    C.report_and_exit()


if __name__ == "__main__":
    asyncio.run(main())
