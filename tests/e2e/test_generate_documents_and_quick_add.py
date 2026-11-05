"""
Two additions made together (synthetic data only; the OCR answers are faked so no
credit is spent):

 A) Upload Passport -> "Save Applicant & Generate Required Documents"
      * the extra button sits beside "Save Applicant"; plain Save does not open the list;
      * it runs the same checks as Save (nothing saved / no list when the form is empty);
      * after saving, a checklist of the six documents opens, nothing is ticked, Start is off;
      * ticked documents become a queue on the application; every page in it shows a
        "Documents for ..." strip with Back / Next, ending in Done which clears it.

 B) "+ Upload new passport / hotel voucher" as the first row of every Use Existing Details list
      * present on Cover Letter, Invitation Letter, Passport and Company Authorization even
        when nothing is saved yet;
      * passport: upload -> review -> save adds the person to the application and the page
        ticks them, exactly as if they had been picked from the list; a second passport is
        added as a traveller;
      * hotel voucher: upload -> the read hotel can be corrected -> "Use these hotels" adds it
        to Hotel Blocking and the Cover Letter takes its dates from it;
      * without an open application the window says so; Escape closes; phone width has no
        sideways overflow; no console errors.
"""
import asyncio
import base64
import io
import json
import os
import sys
import tempfile

from playwright.async_api import async_playwright

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "..", "backend", "python", "tests"))
sys.path.insert(0, os.path.join(HERE, "..", "..", "backend", "python"))

from PIL import Image  # noqa: E402

from _common import BASE, Checks, fresh_load_and_login, select_cover_letter_country  # noqa: E402

checks = Checks()


def png_b64():
    buf = io.BytesIO()
    Image.new("RGB", (130, 90), (245, 245, 245)).save(buf, "PNG")
    return base64.b64encode(buf.getvalue()).decode()


def field(value, source="mrz", review=False, conf=0.95):
    return {"value": value, "confidence": conf, "source": source, "needsReview": review}


def bio_result(number="P9988776", surname="SHARMA", given="ANITA"):
    return {
        "isBlank": False, "pageKind": "bio", "pageIndex": 0, "totalPages": 2, "orientationApplied": 0,
        "orientationNeedsReview": False, "orientationScores": {}, "skewAngleCorrectedDegrees": 0,
        "processedImageBase64": png_b64(), "documentRegionDetected": False,
        "mrz": {"valid": True, "passportNumberValid": True, "dateOfBirthValid": True, "dateOfExpiryValid": True,
                "compositeValid": True, "line1": "P<IND" + surname + "<<" + given + "<<<<<<<<<<<<<<<<<<<<<<<<<<<", "line2": number + "1IND9005125F3112313<<<<<<<<<<<<<<04"},
        "fields": {
            "surname": field(surname), "givenNames": field(given), "dateOfBirth": field("1990-05-12"),
            "sex": field("F"), "nationality": field("IND"), "countryCode": field("IND"),
            "passportNumber": field(number), "passportType": field("P"), "dateOfExpiry": field("2031-12-31"),
            "dateOfIssue": field("2022-01-01"), "placeOfBirth": field("SAMPLEPUR"), "placeOfIssue": field("SAMPLEPUR"),
        },
        "warnings": [], "notices": [], "verificationStatus": "OCR Extracted — Please Verify",
    }


def back_result():
    return {
        "isBlank": False, "pageKind": "back", "pageIndex": 1, "totalPages": 2, "orientationApplied": 0,
        "orientationNeedsReview": False, "orientationScores": {}, "skewAngleCorrectedDegrees": 0,
        "processedImageBase64": png_b64(), "documentRegionDetected": False, "mrz": None,
        "fields": {"addressLine1": field("1 SAMPLE ROAD", "viz", True, 0.5), "addressCity": field("SAMPLEPUR", "viz", True, 0.5)},
        "warnings": [], "notices": [], "verificationStatus": "OCR Extracted — Please Verify",
    }


def hotel_result():
    return {
        "totalPages": 1, "voucherType": "booking", "voucherTypeLabel": "Booking.com",
        "fields": {"hotelName": "Sample Grand Hotel", "city": "Geneva", "checkIn": "2026-12-01", "checkOut": "2026-12-05",
                   "confirmationNumber": "CONF-QA-77", "address": "1 Lake Road", "phone": "+41 22 000 00 00"},
        "guestNames": [], "warnings": [], "lookup": {"status": "skipped"}, "voucherAddress": "1 Lake Road",
    }


def sample_file(tmp):
    from test_passport_layout import synthetic_bio_page, _synthetic_address_page
    bio, _ = synthetic_bio_page(surname="SHARMA", given="ANITA")
    path = os.path.join(tmp, "two_page_synthetic.pdf")
    bio.save(path, "PDF", save_all=True, append_images=[_synthetic_address_page()], resolution=150)
    return path


SHOTS = os.environ.get("KHANNA_SHOTS")  # optional folder: save screenshots for a visual check


async def shot(page, name, full=False):
    if SHOTS:
        os.makedirs(SHOTS, exist_ok=True)
        await page.screenshot(path=os.path.join(SHOTS, name + ".png"), full_page=full)


async def main():
    tmp = tempfile.mkdtemp()
    pdf = sample_file(tmp)
    voucher = os.path.join(tmp, "voucher.png")
    Image.new("RGB", (300, 200), (255, 255, 255)).save(voucher, "PNG")

    numbers = {"next": "P9988776"}

    async def passport_handler(route):
        body = route.request.post_data_buffer or b""
        is_page_two = b'name="page_index"\r\n\r\n1' in body
        payload = back_result() if is_page_two else bio_result(numbers["next"])
        await route.fulfill(status=200, content_type="application/json", headers={"access-control-allow-origin": "*"}, body=json.dumps(payload))

    async def hotel_handler(route):
        await route.fulfill(status=200, content_type="application/json", headers={"access-control-allow-origin": "*"}, body=json.dumps(hotel_result()))

    async with async_playwright() as p:
        browser = await p.chromium.launch()
        context = await browser.new_context(viewport={"width": 1280, "height": 900})
        page = await context.new_page()
        errors = []
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
        await fresh_load_and_login(page, base=BASE)
        await page.route("**/api/passport/process", passport_handler)
        await page.route("**/api/hotel-voucher/process", hotel_handler)

        # ===================================================== A) Upload Passport
        await page.evaluate("(function(){ var a = KhannaState.createApplication('x'); KhannaState.setActiveApplicationId(a.id); location.hash = '#/upload-passport'; })()")
        await page.wait_for_timeout(800)
        u = "[data-view='upload-passport']"

        await page.set_input_files(f"{u} [data-passport-file-input]", pdf)
        await page.wait_for_function("document.querySelector(\"[data-view='upload-passport'] [data-field='current.number']\") && document.querySelector(\"[data-view='upload-passport'] [data-field='current.number']\").value === 'P9988776'", timeout=60000)
        await page.wait_for_function("document.querySelector(\"[data-view='upload-passport'] [data-field='applicant.address.line1']\").value !== ''", timeout=60000)

        save_btn = page.locator(f"{u} [data-passport-save]")
        gen_btn = page.locator(f"{u} [data-passport-save-generate]")
        checks.check("'Save Applicant' button is there", (await save_btn.inner_text()).strip() == "Save Applicant")
        checks.check("'Save Applicant & Generate Required Documents' sits beside it", (await gen_btn.inner_text()).strip() == "Save Applicant & Generate Required Documents")
        b1, b2 = await save_btn.bounding_box(), await gen_btn.bounding_box()
        checks.check("...on the same row, to its right", abs(b1["y"] - b2["y"]) < 8 and b2["x"] > b1["x"], f"{b1} {b2}")
        checks.check("the document list is closed to begin with", await page.locator(f"{u} [data-passport-generate-panel]").is_hidden())

        # plain Save: saves, list stays closed
        await save_btn.click()
        await page.wait_for_timeout(300)
        saved = await page.evaluate("KhannaState.getActiveApplication().applicant.passport.current.number")
        checks.check("plain Save saves the passport", saved == "P9988776", saved)
        checks.check("plain Save does not open the document list", await page.locator(f"{u} [data-passport-generate-panel]").is_hidden())

        # the check that stops Save also stops the new button
        await page.fill(f"{u} [data-field='current.number']", "")
        await gen_btn.click()
        await page.wait_for_timeout(300)
        checks.check("an empty passport number stops the new button too (no list)", await page.locator(f"{u} [data-passport-generate-panel]").is_hidden())
        await page.fill(f"{u} [data-field='current.number']", "P9988776")

        await gen_btn.click()
        await page.wait_for_timeout(400)
        panel = page.locator(f"{u} [data-passport-generate-panel]")
        checks.check("the new button opens the document list below", await panel.is_visible())
        await panel.scroll_into_view_if_needed()
        await shot(page, "01_generate_panel", full=True)
        pb = await panel.bounding_box()
        sb = await page.locator(f"{u} .passport-review__save-row").bounding_box()
        checks.check("...below the save buttons", pb["y"] >= sb["y"] + sb["height"] - 1, f"{pb} {sb}")
        labels = [t.strip().split("\n")[0] for t in await page.locator(f"{u} .passport-generate__item").all_inner_texts()]
        checks.check("it lists all six documents, one checkbox each", labels == ["Cover Letter", "Hotel Blocking", "Passport Authorization Letter", "Company Authorization Letter", "Invitation Letter", "Checklist Letter"], str(labels))
        checks.check("nothing is ticked and Start is off", await page.locator(f"{u} [data-passport-generate-doc]:checked").count() == 0 and await page.locator(f"{u} [data-passport-generate-start]").is_disabled())
        checks.check("the applicant's name is in the heading", "Anita" in (await panel.locator("h3").inner_text()) or "ANITA" in (await panel.locator("h3").inner_text()).upper())
        checks.check("the Continue-to-document shortcuts are not repeated beside it", await page.locator(f"{u} [data-passport-continue-to-document]").is_hidden())
        checks.check("the application was saved (applicant name stored)", bool(await page.evaluate("KhannaState.getActiveApplication().applicant.fullName")))

        await page.locator(f"{u} [data-passport-generate-all]").click()
        checks.check("Select all ticks all six", await page.locator(f"{u} [data-passport-generate-doc]:checked").count() == 6)
        await page.locator(f"{u} [data-passport-generate-all]").click()
        checks.check("Select all again clears them", await page.locator(f"{u} [data-passport-generate-doc]:checked").count() == 0)

        # phone width with the list open
        await page.set_viewport_size({"width": 390, "height": 844})
        await page.wait_for_timeout(300)
        m = await page.evaluate("({page: document.documentElement.scrollWidth, client: document.documentElement.clientWidth})")
        checks.check("390px: no sideways overflow with the list open", m["page"] <= m["client"], str(m))
        await page.set_viewport_size({"width": 1280, "height": 900})

        for view in ("cover-letter", "hotel-blocking", "invitation-letter"):
            await page.locator(f"{u} [data-passport-generate-doc='{view}']").check()
        start = page.locator(f"{u} [data-passport-generate-start]")
        checks.check("Start now says how many", (await start.inner_text()).strip() == "Start with 3 documents" and await start.is_enabled(), await start.inner_text())
        await start.click()
        await page.wait_for_timeout(700)
        checks.check("it opens the first ticked document (Cover Letter)", (await page.evaluate("location.hash")) == "#/cover-letter")
        queue = await page.evaluate("KhannaState.getActiveApplication().docQueue.items")
        checks.check("the choice is saved on the application, in the usual order", queue == ["cover-letter", "hotel-blocking", "invitation-letter"], str(queue))

        strip = page.locator("[data-view='cover-letter'] [data-doc-queue]")
        await shot(page, "02_queue_strip")
        checks.check("the Cover Letter page shows the 'Documents for' strip", await strip.is_visible())
        text = (await strip.inner_text()).replace("\n", " ")
        checks.check("...naming the applicant and the three documents", ("Anita" in text or "ANITA" in text.upper()) and "Cover Letter" in text and "Hotel Blocking" in text and "Invitation Letter" in text, text)
        checks.check("...marking Cover Letter as the current step", "Cover Letter" in (await strip.locator(".is-current").inner_text()))
        checks.check("...no Back on the first page, Next names the next document", await strip.locator("a:has-text('Back')").count() == 0 and "Next: Hotel Blocking" in text, text)

        await strip.locator("a:has-text('Next: Hotel Blocking')").click()
        await page.wait_for_timeout(700)
        strip = page.locator("[data-view='hotel-blocking'] [data-doc-queue]")
        checks.check("Next goes to Hotel Blocking, which shows the strip with Cover Letter done", await strip.is_visible() and await strip.locator(".is-done").count() == 1 and await strip.locator("a:has-text('Back')").count() == 1)
        await strip.locator("a:has-text('Next: Invitation Letter')").click()
        await page.wait_for_timeout(700)
        strip = page.locator("[data-view='invitation-letter'] [data-doc-queue]")
        checks.check("the last page offers Done instead of Next", await strip.locator("[data-doc-queue-done]").count() == 1 and await strip.locator("a:has-text('Next')").count() == 0)
        await page.set_viewport_size({"width": 390, "height": 844})
        await page.wait_for_timeout(300)
        m = await page.evaluate("({page: document.documentElement.scrollWidth, client: document.documentElement.clientWidth})")
        checks.check("390px: the strip causes no sideways overflow", m["page"] <= m["client"], str(m))
        await page.set_viewport_size({"width": 1280, "height": 900})
        await page.evaluate("location.hash = '#/passport-authorization'")
        await page.wait_for_timeout(600)
        checks.check("a page that was not ticked has no strip", await page.locator("[data-view='passport-authorization'] [data-doc-queue]").count() == 0)
        await page.evaluate("location.hash = '#/invitation-letter'")
        await page.wait_for_timeout(600)
        await page.locator("[data-view='invitation-letter'] [data-doc-queue-done]").click()
        await page.wait_for_timeout(600)
        queue = await page.evaluate("KhannaState.getApplications().map(function(a){return (a.docQueue||{}).items||[]}).filter(function(i){return i.length}).length")
        checks.check("Done removes the queue", queue == 0, str(queue))
        checks.check("...and leaves the document pages (goes to Applications)", (await page.evaluate("location.hash")) == "#/applications")

        # ===================================================== B) "+" in Use Existing Details
        await page.evaluate("(function(){ var a = KhannaState.createApplication('x'); KhannaState.setActiveApplicationId(a.id); location.hash = '#/cover-letter'; })()")
        await page.wait_for_timeout(800)
        await select_cover_letter_country(page, "Germany")
        await page.wait_for_timeout(400)

        async def open_list(view_sel, toggle, option):
            await page.click(f"{view_sel} {toggle}")
            await page.click(f"{view_sel} {option}")

        cv = "[data-view='cover-letter']"
        await page.click(f"{cv} [data-cover-use-existing-toggle]")
        await page.click(f"{cv} [data-cover-use-existing-option='passport']")
        await shot(page, "03_use_existing_menu")
        first = page.locator(f"{cv} [data-cover-existing-list] > *").first
        checks.check("Cover Letter: the first row of the Passport list is '+ Upload new passport' ", "Upload new passport" in await first.inner_text() and await first.get_attribute("data-quick-add") == "passport")
        checks.check("...followed by the usual 'Previous passports' list", "previous passports" in (await page.locator(f"{cv} [data-cover-existing-list]").inner_text()).lower())
        await page.click(f"{cv} [data-cover-use-existing-option='hotel-blocking']")
        first_h = page.locator(f"{cv} [data-cover-existing-list] > *").first
        checks.check("Cover Letter: the Hotel Blocking list starts with '+ Upload new hotel voucher'", "Upload new hotel voucher" in await first_h.inner_text() and await first_h.get_attribute("data-quick-add") == "hotel")

        # ---- passport through the Cover Letter
        await page.click(f"{cv} [data-cover-use-existing-option='passport']")
        await page.locator(f"{cv} [data-quick-add='passport']").click()
        await page.wait_for_timeout(400)
        overlay = page.locator("[data-quick-add-overlay]")
        checks.check("clicking it opens the upload window", await overlay.is_visible() and "Add a passport" in await overlay.inner_text())
        checks.check("...with the passport dropzone", await overlay.locator("[data-passport-dropzone]").is_visible())
        numbers["next"] = "P9988776"
        await overlay.locator("[data-passport-file-input]").set_input_files(pdf)
        await page.wait_for_function("document.querySelector(\"[data-quick-add-overlay] [data-field='current.number']\") && document.querySelector(\"[data-quick-add-overlay] [data-field='current.number']\").value === 'P9988776'", timeout=60000)
        await shot(page, "04_passport_window")
        checks.check("the passport is read into the review form, to be checked", "OCR Extracted" in await overlay.locator("[data-ocr-banner]").inner_text())
        await page.wait_for_function("document.querySelector(\"[data-quick-add-overlay] [data-field='applicant.address.line1']\").value !== ''", timeout=60000)
        checks.check("nothing was added before it is saved", await page.evaluate("(KhannaState.getActiveApplication().applicant.passport.current.number || '')") == "")
        await overlay.locator("[data-passport-save]").click()
        await page.wait_for_timeout(900)
        checks.check("saving closes the window", await overlay.is_hidden())
        app = await page.evaluate("(function(){var a=KhannaState.getActiveApplication(); return {num:a.applicant.passport.current.number, trav:a.travellers.length}})()")
        checks.check("the person became the application's applicant", app["num"] == "P9988776" and app["trav"] == 0, str(app))
        rows = await page.locator(f"{cv} .auth-person-row").all_inner_texts()
        checks.check("the Cover Letter ticked them, as if picked from the list", len(rows) == 1 and "Main applicant" in rows[0] and await page.locator(f"{cv} [data-cover-person]:checked").count() == 1, str(rows))
        in_profiles = await page.evaluate("KhannaState.getApplicantProfiles().some(function(p){return p.passport && p.passport.current && p.passport.current.number === 'P9988776'})")
        checks.check("the passport is also saved for reuse (profiles)", in_profiles)

        # ---- a second passport becomes a traveller
        numbers["next"] = "P1234567"
        await page.click(f"{cv} [data-cover-use-existing-toggle]")
        await page.click(f"{cv} [data-cover-use-existing-option='passport']")
        listed = await page.locator(f"{cv} [data-cover-existing-list]").inner_text()
        checks.check("the list now shows the saved passport under the '+' row", "P9988776" in listed and "Upload new passport" in listed)
        await page.locator(f"{cv} [data-quick-add='passport']").click()
        await page.wait_for_timeout(300)
        await overlay.locator("[data-passport-file-input]").set_input_files(pdf)
        await page.wait_for_function("document.querySelector(\"[data-quick-add-overlay] [data-field='current.number']\") && document.querySelector(\"[data-quick-add-overlay] [data-field='current.number']\").value === 'P1234567'", timeout=60000)
        await overlay.locator("[data-passport-save]").click()
        await page.wait_for_timeout(900)
        app = await page.evaluate("(function(){var a=KhannaState.getActiveApplication(); return {trav:a.travellers.map(function(t){return t.passport.current.number})}})()")
        checks.check("a second passport is added as a traveller", app["trav"] == ["P1234567"], str(app))
        checks.check("...and both are ticked on the Cover Letter", await page.locator(f"{cv} [data-cover-person]:checked").count() == 2)

        # ---- the same passport again does not duplicate
        numbers["next"] = "P1234567"
        await page.click(f"{cv} [data-cover-use-existing-toggle]")
        await page.click(f"{cv} [data-cover-use-existing-option='passport']")
        await page.locator(f"{cv} [data-quick-add='passport']").click()
        await page.wait_for_timeout(300)
        await overlay.locator("[data-passport-file-input]").set_input_files(pdf)
        await page.wait_for_function("document.querySelector(\"[data-quick-add-overlay] [data-field='current.number']\") && document.querySelector(\"[data-quick-add-overlay] [data-field='current.number']\").value === 'P1234567'", timeout=60000)
        await overlay.locator("[data-passport-save]").click()
        await page.wait_for_timeout(900)
        count = await page.evaluate("KhannaState.getActiveApplication().travellers.length")
        checks.check("uploading a passport that is already on the application does not add it twice", count == 1, str(count))

        # ---- hotel voucher through the Cover Letter
        await page.click(f"{cv} [data-cover-use-existing-toggle]")
        await page.click(f"{cv} [data-cover-use-existing-option='hotel-blocking']")
        await page.locator(f"{cv} [data-quick-add='hotel']").click()
        await page.wait_for_timeout(300)
        checks.check("hotel: the window offers a voucher dropzone", await overlay.locator("[data-quick-add-dropzone]").is_visible() and "Add a hotel voucher" in await overlay.inner_text())
        await overlay.locator("[data-quick-add-file]").set_input_files(voucher)
        await overlay.locator("[data-quick-add-confirm-hotels]").wait_for(timeout=30000)
        await shot(page, "05_hotel_window")
        checks.check("hotel: the read hotel is shown for checking (name, city, dates, confirmation)", await overlay.locator("[data-qa-field='hotelName']").input_value() == "Sample Grand Hotel" and await overlay.locator("[data-qa-field='checkIn']").input_value() == "2026-12-01" and await overlay.locator("[data-qa-field='confirmationNumber']").input_value() == "CONF-QA-77")
        checks.check("hotel: marked 'OCR Extracted — Please Verify'", "OCR Extracted" in await overlay.inner_text())
        checks.check("hotel: nothing is added before confirming", await page.evaluate("KhannaState.getActiveApplication().hotels.filter(function(h){return h.hotelName}).length") == 0)
        await overlay.locator("[data-qa-field='city']").fill("Zurich")
        await overlay.locator("[data-qa-field='checkOut']").fill("2026-11-20")
        await overlay.locator("[data-quick-add-confirm-hotels]").click()
        err = await overlay.locator("[data-quick-add-error]").count()
        checks.check("hotel: a check-out before the check-in is refused with a message", err == 1 and await overlay.is_visible())
        await overlay.locator("[data-qa-field='checkOut']").fill("2026-12-05")
        await overlay.locator("[data-quick-add-confirm-hotels]").click()
        await page.wait_for_timeout(900)
        hotels = await page.evaluate("KhannaState.getActiveApplication().hotels.filter(function(h){return h.hotelName}).map(function(h){return [h.hotelName,h.city,h.checkIn,h.checkOut,h.confirmationNumber]})")
        checks.check("hotel: 'Use these hotels' adds it to Hotel Blocking with the corrections", hotels == [["Sample Grand Hotel", "Zurich", "2026-12-01", "2026-12-05", "CONF-QA-77"]], str(hotels))
        checks.check("hotel: the window closed", await overlay.is_hidden())
        start_date = await page.input_value(f"{cv} [data-cover-field='top:travelStartDate']")
        end_date = await page.input_value(f"{cv} [data-cover-field='top:travelEndDate']")
        checks.check("hotel: the Cover Letter took its travel dates from it", (start_date, end_date) == ("2026-12-01", "2026-12-05"), f"{start_date} {end_date}")

        # ---- the other pages
        for view, toggle, opt, pick in [
            ("invitation-letter", "[data-inv-use-existing-toggle]", "[data-inv-use-existing-option='passport']", "passport"),
            ("passport-authorization", "[data-auth-use-existing-toggle]", "[data-auth-use-existing-option='passport']", "passport"),
            ("company-authorization", "[data-auth-use-existing-toggle]", "[data-auth-use-existing-option='passport']", "passport"),
        ]:
            await page.evaluate(f"location.hash='#/{view}'")
            await page.wait_for_timeout(700)
            sel = f"[data-view='{view}']"
            await page.locator(f"{sel} {toggle}").first.click()
            await page.locator(f"{sel} {opt}").first.click()
            row = page.locator(f"{sel} [data-quick-add='passport']").first
            checks.check(f"{view}: '+ Upload new passport' is the first row", await row.is_visible())
        # invitation also has Hotel Blocking
        await page.evaluate("location.hash='#/invitation-letter'")
        await page.wait_for_timeout(600)
        sel = "[data-view='invitation-letter']"
        await page.locator(f"{sel} [data-inv-use-existing-toggle]").first.click()
        await page.locator(f"{sel} [data-inv-use-existing-option='hotel-blocking']").first.click()
        checks.check("invitation-letter: the Hotel Blocking list has '+ Upload new hotel voucher'", await page.locator(f"{sel} [data-quick-add='hotel']").first.is_visible())

        # ---- passport through the Passport Authorization page picks them up
        await page.evaluate("location.hash='#/passport-authorization'")
        await page.wait_for_timeout(700)
        sel = "[data-view='passport-authorization']"
        numbers["next"] = "P7654321"
        await page.locator(f"{sel} [data-auth-use-existing-toggle]").first.click()
        await page.locator(f"{sel} [data-auth-use-existing-option='passport']").first.click()
        await page.locator(f"{sel} [data-quick-add='passport']").first.click()
        await page.wait_for_timeout(300)
        await overlay.locator("[data-passport-file-input]").set_input_files(pdf)
        await page.wait_for_function("document.querySelector(\"[data-quick-add-overlay] [data-field='current.number']\") && document.querySelector(\"[data-quick-add-overlay] [data-field='current.number']\").value === 'P7654321'", timeout=60000)
        await overlay.locator("[data-passport-save]").click()
        await page.wait_for_timeout(900)
        checks.check("passport-authorization: the new person was added (travellers now 2)", await page.evaluate("KhannaState.getActiveApplication().travellers.length") == 2)
        ticked = await page.evaluate("document.querySelectorAll(\"[data-view='passport-authorization'] .auth-person-row input:checked\").length")
        checks.check("passport-authorization: and ticked on that page", ticked >= 1, str(ticked))

        # ---- Escape closes; no application -> clear message
        await page.locator(f"{sel} [data-auth-use-existing-toggle]").first.click()
        await page.locator(f"{sel} [data-auth-use-existing-option='passport']").first.click()
        await page.locator(f"{sel} [data-quick-add='passport']").first.click()
        await page.wait_for_timeout(300)
        await page.keyboard.press("Escape")
        await page.wait_for_timeout(200)
        checks.check("Escape closes the window", await overlay.is_hidden())

        await page.evaluate("KhannaState.setActiveApplicationId(null); location.hash='#/invitation-letter'")
        await page.wait_for_timeout(500)
        await page.evaluate("KhannaQuickAdd.open('passport', {})")
        await page.wait_for_timeout(200)
        checks.check("with no application open the window says so", "no application open" in (await overlay.inner_text()).lower())
        await page.keyboard.press("Escape")

        # ---- phone width
        await page.evaluate("(function(){var a=KhannaState.getApplications()[KhannaState.getApplications().length-1]; KhannaState.setActiveApplicationId(a.id);})()")
        await page.set_viewport_size({"width": 390, "height": 844})
        await page.evaluate("KhannaQuickAdd.open('hotel', {})")
        await page.wait_for_timeout(300)
        await shot(page, "06_phone_window")
        m = await page.evaluate("({page: document.documentElement.scrollWidth, client: document.documentElement.clientWidth, box: document.querySelector('.quick-add').getBoundingClientRect().width})")
        checks.check("390px: the window fits the screen", m["page"] <= m["client"] and m["box"] <= m["client"], str(m))

        checks.check("no console errors", not errors, "; ".join(errors[:3]))
        await browser.close()
    checks.report_and_exit()


asyncio.run(main())
