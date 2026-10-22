"""
Cover Letter page round (Recent Cover Letters, country picker, "Use Existing
Details", no "Unnamed" row) + the Hotel Blocking "can't generate" fix.

Covers (all against the real static server + backend):
  - "Recent Cover Letters" button in the Cover Letter title row (right-aligned).
  - Destination country picker: opens with the full list, NO region tags
    (Schengen Europe / Japan / Singapore), filters as you type, Enter picks,
    "No matching country" message, and the Consulate name follows
    the selected country (Japan -> "Consulate General of Japan").
  - No empty "Unnamed" checkbox row.
  - "Use Existing Details": a second small scrollable list opens beside the
    menu with saved passports / saved hotel blockings; choosing one fills the
    letter (applicant, companion, residence city/country, travel dates,
    nights, next-country leg) and reports what was not available.
  - Recent Cover Letters page: Edit (back to the preview), Download DOCX/PDF
    (real files), Delete with a confirmation popup.
  - Hotel Blocking: Generate works when only SOME hotels are complete, and the
    hotel left out is named with what it is missing.
"""

import asyncio

import pypdfium2 as pdfium
from playwright.async_api import async_playwright

from _common import BASE, Checks, ensure_fixtures, fresh_load_and_login, future_date

# Cover-letter dates may not be in the past, so the seeded hotel dates are relative to today.
D15, D25, D28 = future_date(24), future_date(34), future_date(37)

checks = Checks()

SEED = """
(function () {
  var S = KhannaState;
  // application with two saved passports (applicant + wife)
  var a = S.createApplication('x');
  S.updateApplication(a.id, { applicant: {
    salutation: 'Mr', firstName: 'Rahul', lastName: 'Sharma', fullName: 'Rahul Sharma', sex: 'Male',
    passport: { current: { number: 'P1111111', issuePlace: 'Mumbai', issueDate: '2020-01-01' } },
    address: { city: 'Pune', country: 'India' }, contact: { phone: '9999999999', email: 'r@example.com' } } });
  var t = S.addTraveller(a.id, 'Wife');
  S.updateTraveller(a.id, t.id, { salutation: 'Mrs', fullName: 'Priya Sharma', sex: 'Female',
    passport: { current: { number: 'P2222222', issuePlace: 'Mumbai', issueDate: '2021-02-02' } } }, null);
  // application with saved hotel blockings (two complete hotels + one incomplete)
  var b = S.createApplication('x');
  S.updateApplication(b.id, { applicant: { fullName: 'Hotel Guest' } });
  var h1 = S.addHotel(b.id); S.updateHotel(b.id, h1.id, { hotelName: 'Hotel Lowen Am See', city: 'Zug', country: 'Switzerland', address: 'Seestrasse 1, Zug', phone: '+41 41 000 00 00', checkIn: '__D15__', checkOut: '__D25__' }, null);
  var h2 = S.addHotel(b.id); S.updateHotel(b.id, h2.id, { hotelName: 'Hotel Roma Centro', city: 'Rome', country: 'Italy', checkIn: '__D25__', checkOut: '__D28__' }, null);
  // application whose hotel blocking has no dates at all
  var c = S.createApplication('x');
  S.updateApplication(c.id, { applicant: { fullName: 'No Dates Guest' } });
  var h3 = S.addHotel(c.id); S.updateHotel(c.id, h3.id, { hotelName: 'Hotel Without Dates', city: 'Oslo' }, null);
  // a hotel blocking whose voucher could not be read: one hotel with nothing filled in yet
  var blank = S.createApplication('x');
  S.addHotel(blank.id);
  // a person who only exists as a saved profile (their application was deleted)
  S.saveApplicantProfile({ salutation: 'Mr', firstName: 'Old', lastName: 'Profile', fullName: 'Old Profile',
    passport: { current: { number: 'P3333333' } } });
  // a person with a name but NO passport number yet
  var d = S.createApplication('x');
  S.updateApplication(d.id, { applicant: { salutation: 'Ms', fullName: 'No Number Person' } });
  // the application the cover letter is built on
  var target = S.createApplication('x');
  S.setActiveApplicationId(target.id);
  return { target: target.id, a: a.id, b: b.id, c: c.id, blank: blank.id };
})()
"""
SEED = SEED.replace("__D15__", D15).replace("__D25__", D25).replace("__D28__", D28)


async def wait_preview_ready(page, scope, polls=100):
    for _ in range(polls):
        if await page.locator(f"{scope} [data-dv='status']").count():
            st = (await page.inner_text(f"{scope} [data-dv='status']")).strip()
            if st == "":
                break
        await page.wait_for_timeout(300)
    await page.wait_for_timeout(800)


async def main():
    ensure_fixtures()
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        context = await browser.new_context(viewport={"width": 1280, "height": 1000}, accept_downloads=True)
        page = await context.new_page()
        console_errors = []
        page.on("console", lambda m: console_errors.append(m.text) if m.type == "error" else None)
        page.on("pageerror", lambda e: console_errors.append(f"pageerror: {e}"))
        await fresh_load_and_login(page, base=BASE)

        ids = await page.evaluate(SEED)
        await page.evaluate("location.hash = '#/cover-letter'")
        await page.wait_for_timeout(600)

        # ---------- 1) title row button ----------
        link = page.locator("[data-recent-cover-letters-link]")
        checks.check("'Recent Cover Letters' button exists in the Cover Letter title row", (await link.inner_text()).strip() == "Recent Cover Letters")
        box = await link.bounding_box()
        h1 = await page.locator("[data-view='cover-letter'] h1").bounding_box()
        container = await page.locator("[data-view='cover-letter'] .container").bounding_box()
        checks.check(
            "...on the title line, at the right-most side",
            abs((box["y"] + box["height"] / 2) - (h1["y"] + h1["height"] / 2)) < 40 and box["x"] + box["width"] > container["x"] + container["width"] - 40,
            f"{box} {h1} {container}",
        )

        # ---------- 2) country picker ----------
        inp = page.locator("[data-cover-country-search]")
        await inp.click()
        n_all = await page.locator("[data-cover-country-option]").count()
        checks.check("focusing the country field lists every country", n_all >= 29, str(n_all))
        list_text = await page.inner_text("[data-cover-country-list]")
        checks.check(
            "no 'Schengen Europe' / 'Japan' / 'Singapore' tags on the right of the options",
            "Schengen Europe" not in list_text and await page.locator(".country-combo__option-region").count() == 0 and list_text.count("Japan") == 1 and list_text.count("Singapore") == 1,
            list_text[:200],
        )
        await inp.fill("jap")
        opts = await page.locator("[data-cover-country-option]").all_inner_texts()
        checks.check("typing filters the list ('jap' -> Japan only)", [o.strip() for o in opts] == ["Japan"], str(opts))
        await inp.fill("n")
        first = (await page.locator("[data-cover-country-option]").first.inner_text()).strip()
        checks.check("names that START with the typed letters come first ('n' -> Netherlands)", first == "Netherlands", first)
        await inp.fill("xyzzy")
        checks.check("no match shows 'No matching country.'", "No matching country" in await page.inner_text("[data-cover-country-list]"))
        await inp.fill("swit")
        await inp.press("Enter")
        await page.wait_for_timeout(400)
        recipient = await page.input_value("[data-cover-field='top:consulateName']")
        checks.check("Enter picks the highlighted match -> Switzerland, consulate follows", recipient == "The Consulate General of Switzerland", recipient)
        address = await page.input_value("[data-cover-field='top:consulateAddress']")
        checks.check("Address of Consulate defaults to Mumbai, India", address == "Mumbai, India", address)
        dest = await page.input_value("[data-cover-field='top:destinationCountry']")
        checks.check("Destination country field follows", dest == "Switzerland", dest)

        await inp.click()
        await inp.fill("japan")
        await page.click("[data-cover-country-option='Japan']")
        await page.wait_for_timeout(400)
        recipient = await page.input_value("[data-cover-field='top:consulateName']")
        checks.check("selecting Japan -> 'The Consulate General of Japan'", recipient == "The Consulate General of Japan", recipient)
        shown = await page.input_value("[data-cover-country-search]")
        checks.check("the country field shows the chosen country", shown == "Japan", shown)
        await inp.click()
        await inp.fill("norw")
        await page.click("[data-cover-country-option='Norway']")
        await page.wait_for_timeout(400)
        recipient = await page.input_value("[data-cover-field='top:consulateName']")
        checks.check("changing the country again updates the consulate again", recipient == "The Consulate General of Norway", recipient)

        # typed text that was never picked goes back to the real selection
        await inp.click()
        await inp.fill("zzz")
        await page.click("[data-view='cover-letter'] h1")
        await page.wait_for_timeout(200)
        shown = await page.input_value("[data-cover-country-search]")
        checks.check("abandoned typing is restored to the selected country", shown == "Norway", shown)

        # ---------- 3) no 'Unnamed' checkbox ----------
        body = await page.inner_text("[data-cover-letter-card]")
        checks.check("no 'Unnamed' person row", "Unnamed" not in body and await page.locator("[data-cover-person]").count() == 0, body[:300])
        checks.check("an empty-state hint points to Use Existing Details", "Use Existing Details" in body)

        # ---------- 3b) applicant-name label ----------
        lbl = (await page.locator("label[for='cover-top-manualApplicantName']").inner_text()).strip()
        checks.check("with no existing applicant the optional-name input is shown", lbl.startswith("Applicant name (optional"), lbl)

        # ---------- 4) Use Existing Details -> Passport ----------
        await page.click("[data-cover-use-existing-toggle]")
        menu_items = await page.locator(".cover-existing-menu__item").all_inner_texts()
        checks.check("menu offers Passport and Hotel Blocking", [m.replace("▸", "").strip() for m in menu_items] == ["Passport", "Hotel Blocking"], str(menu_items))
        checks.check("second list is hidden until a kind is chosen", await page.locator("[data-cover-existing-list]").is_hidden())
        await page.click("[data-cover-use-existing-option='passport']")
        lst = page.locator("[data-cover-existing-list]")
        checks.check("choosing Passport opens a second list", await lst.is_visible())
        m_box = await page.locator(".cover-existing-menu").bounding_box()
        l_box = await lst.bounding_box()
        checks.check("...beside the menu (to its right)", l_box["x"] >= m_box["x"] + m_box["width"] - 1 and abs(l_box["y"] - m_box["y"]) < 12, f"{m_box} {l_box}")
        scroll = await page.evaluate("(function(){var e=document.querySelector('[data-cover-existing-list]');var s=getComputedStyle(e);return [s.overflowY,s.maxHeight];})()")
        checks.check("...a small scrollable box", scroll[0] in ("auto", "scroll") and scroll[1] != "none", str(scroll))
        txt = await lst.inner_text()
        checks.check("lists the saved passports (name + number)", "Rahul Sharma" in txt and "P1111111" in txt and "Priya Sharma" in txt and "P2222222" in txt, txt)
        checks.check("also lists people who only exist as a saved profile", "Old Profile" in txt and "P3333333" in txt, txt)
        checks.check("...and people whose passport number is not saved yet (flagged, not hidden)", "No Number Person" in txt and "No passport number on file" in txt, txt)

        await page.click("[data-cover-existing-pick='passport'][data-passport-key='P1111111']")
        await page.wait_for_timeout(400)
        rows = await page.locator(".auth-person-row").all_inner_texts()
        checks.check("picking a passport adds that person, ticked, as Main applicant", len(rows) == 1 and "Rahul Sharma" in rows[0] and "Main applicant" in rows[0], str(rows))
        checks.check("...and it is ticked", await page.locator("[data-cover-person]").first.is_checked())
        status = await page.inner_text("[data-cover-existing-status]")
        checks.check("a status line says what was added", "Rahul Sharma" in status and "applicant" in status, status)
        lbl2 = (await page.locator("label[for='cover-top-applicantName']").inner_text()).strip()
        val2 = await page.input_value("#cover-top-applicantName")
        checks.check("an existing applicant is selected -> the label becomes 'Applicant Name'", lbl2 == "Applicant Name", lbl2)
        checks.check("...prefilled with that applicant's name, and not editable", "Rahul Sharma" in val2 and await page.locator("#cover-top-applicantName").get_attribute("readonly") is not None, val2)
        checks.check("...and the optional new-applicant input is not shown then", await page.locator("[data-cover-field='top:manualApplicantName']").count() == 0)
        await page.locator("[data-cover-person]").first.uncheck()
        await page.wait_for_timeout(300)
        lbl3 = (await page.locator("label[for='cover-top-manualApplicantName']").inner_text()).strip()
        checks.check("untick the applicant -> the new-applicant input (original label) returns", lbl3.startswith("Applicant name (optional"), lbl3)
        await page.locator("[data-cover-person]").first.check()
        await page.wait_for_timeout(300)
        city = await page.input_value("[data-cover-field='europe:cityOfResidence']")
        country = await page.input_value("[data-cover-field='europe:countryOfResidence']")
        checks.check("city / country of residence filled from the passport's address", (city, country) == ("Pune", "India"), f"{city}/{country}")

        await page.click("[data-cover-use-existing-toggle]")
        await page.click("[data-cover-use-existing-option='passport']")
        await page.click("[data-cover-existing-pick='passport'][data-passport-key='P2222222']")
        await page.wait_for_timeout(400)
        rows = await page.locator(".auth-person-row").all_inner_texts()
        checks.check("second passport joins as the companion (relation kept)", len(rows) == 2 and "Priya Sharma" in rows[1] and "Wife" in rows[1], str(rows))
        checks.check("both ticked", await page.locator("[data-cover-person]:checked").count() == 2)
        src_still = await page.evaluate(f"KhannaState.getApplication('{ids['a']}').applicant.fullName")
        checks.check("the source application is untouched", src_still == "Rahul Sharma")

        # ---------- 5) Use Existing Details -> Hotel Blocking ----------
        await page.click("[data-cover-use-existing-toggle]")
        await page.click("[data-cover-use-existing-option='hotel-blocking']")
        txt = await page.locator("[data-cover-existing-list]").inner_text()
        checks.check("lists saved hotel blockings with hotels and dates", "Hotel Guest" in txt and "Hotel Lowen Am See" in txt and "Hotel Without Dates" in txt, txt)
        n_apps_with_hotels = await page.evaluate("KhannaState.getApplications().filter(function(a){return (a.hotels||[]).some(function(h){return h.hotelName||h.checkIn||h.checkOut||h.city})}).length")
        n_listed = await page.locator("[data-cover-existing-pick='hotel-blocking']").count()
        checks.check("EVERY hotel blocking that has hotel details is listed here", n_listed == n_apps_with_hotels and n_listed >= 2, f"{n_listed} vs {n_apps_with_hotels}")
        checks.check("a blocking with no hotel details at all is NOT listed", "Unnamed hotel" not in txt, txt)
        await page.click(f"[data-cover-existing-pick='hotel-blocking'][data-app-id='{ids['b']}']")
        await page.wait_for_timeout(400)
        start = await page.input_value("[data-cover-field='top:travelStartDate']")
        end = await page.input_value("[data-cover-field='top:travelEndDate']")
        checks.check("travel dates come from the hotel blocking (first check-in -> last check-out)", (start, end) == (D15, D28), f"{start}/{end}")
        nights = await page.input_value("[data-cover-field='europe:numberOfNights']")
        checks.check("number of nights computed from the first hotel", nights == "10 nights", nights)
        nxt = await page.input_value("[data-cover-field='europe:nextCountry']")
        checks.check("second hotel becomes the next-country leg", nxt == "Italy", nxt)
        status = await page.inner_text("[data-cover-existing-status]")
        checks.check("status names what was filled", "Filled" in status and "Hotel Guest" in status, status)

        await page.click("[data-cover-use-existing-toggle]")
        await page.click("[data-cover-use-existing-option='hotel-blocking']")
        await page.click(f"[data-cover-existing-pick='hotel-blocking'][data-app-id='{ids['c']}']")
        await page.wait_for_timeout(400)
        status = await page.inner_text("[data-cover-existing-status]")
        checks.check("details a hotel blocking lacks are reported, not invented", "Not available there" in status and "travel start date" in status, status)
        start = await page.input_value("[data-cover-field='top:travelStartDate']")
        checks.check("...and existing values are left alone", start == D15, start)

        # ---------- 6) complete the letter and generate ----------
        await page.select_option("[data-cover-field='top:fundingType']", "self")
        for key, val in [
            ("europe:applicantEmploymentStatus", "Employed"),
            ("europe:applicantJobTitle", "Engineer"),
            ("europe:applicantEmployerName", "Acme Pvt Ltd"),
            ("europe:companionJobTitle", "Teacher"),
            ("europe:companionEmployerName", "City School"),
            ("europe:companionEmploymentStartYear", "2015"),
        ]:
            await page.fill(f"[data-cover-field='{key}']", val)
            await page.press(f"[data-cover-field='{key}']", "Tab")
        await page.wait_for_timeout(500)
        gen = page.locator("[data-action='generate-cover-letter']")
        checks.check("Generate & Preview is enabled once everything is filled", await gen.is_enabled())
        await gen.click()
        await wait_preview_ready(page, "[data-doc-preview]")
        checks.check("a real preview is shown", await page.locator("[data-doc-preview] canvas").count() > 0)

        # ---------- 7) Recent Cover Letters page ----------
        await page.click("[data-recent-cover-letters-link]")
        await page.wait_for_timeout(500)
        rows = page.locator("[data-cl-row]")
        n_rows = await rows.count()
        checks.check("Recent Cover Letters lists the saved cover letter", n_rows == 1, str(n_rows))
        row_text = await rows.first.inner_text()
        checks.check("row shows applicant, country, dates", "Rahul Sharma" in row_text and "Norway" in row_text and "15" in row_text, row_text)
        checks.check("row is titled with the applicant's name, not 'Untitled applicant'", "Untitled applicant" not in row_text, row_text)
        checks.check("row has Edit, Download, Delete", all(k in row_text for k in ("Edit", "Download", "Delete")), row_text)

        await rows.first.locator("[data-action='cl-download-toggle']").click()
        opts = await rows.first.locator(".hb-menu__item").all_inner_texts()
        checks.check("Download opens a dropdown with DOCX and PDF", [o.strip() for o in opts] == ["Download as DOCX", "Download as PDF"], str(opts))
        async with page.expect_download(timeout=90000) as dl:
            await rows.first.locator("[data-action='cl-download'][data-format='pdf']").click()
        d = await dl.value
        path = await d.path()
        pdf = pdfium.PdfDocument(path)
        pdf_text = pdf[0].get_textpage().get_text_range()
        checks.check("PDF download is a real cover letter with the applicant's name", d.suggested_filename.lower().endswith(".pdf") and "Rahul Sharma" in pdf_text, d.suggested_filename)
        await rows.first.locator("[data-action='cl-download-toggle']").click()
        async with page.expect_download(timeout=90000) as dl:
            await rows.first.locator("[data-action='cl-download'][data-format='docx']").click()
        d = await dl.value
        checks.check("DOCX download works", d.suggested_filename.lower().endswith(".docx"), d.suggested_filename)

        await rows.first.locator("[data-action='cl-edit']").click()
        await page.wait_for_timeout(500)
        on_page = await page.evaluate("location.hash")
        checks.check("Edit goes back to the Cover Letter page", "cover-letter" in on_page and "cover-letters" not in on_page, on_page)
        await wait_preview_ready(page, "[data-doc-preview]")
        checks.check("...and opens the preview straight away", await page.locator("[data-doc-preview] canvas").count() > 0)

        await page.click("[data-recent-cover-letters-link]")
        await page.wait_for_timeout(400)
        await page.locator("[data-cl-row] [data-action='cl-delete']").first.click()
        modal = page.locator("[data-cl-delete-modal]")
        checks.check("Delete asks for confirmation first", await modal.is_visible() and "Are you sure" in await modal.inner_text())
        await page.click("[data-cl-delete-cancel].btn-secondary")
        checks.check("Cancel keeps the cover letter", await page.locator("[data-cl-row]").count() == 1)
        await page.locator("[data-cl-row] [data-action='cl-delete']").first.click()
        await page.click("[data-cl-delete-confirm]")
        await page.wait_for_timeout(400)
        checks.check("confirming removes it from the list", await page.locator("[data-cl-row]").count() == 0)
        checks.check("...and the empty state is shown", "No cover letters yet" in await page.inner_text("[data-cover-letters-root]"))
        # the source applications that merely lent their passports/hotels are untouched
        still = await page.evaluate(f"!!KhannaState.getApplication('{ids['a']}') && !!KhannaState.getApplication('{ids['b']}')")
        checks.check("applications used as sources are untouched by the delete", still)

        # ---------- 8) Hotel Blocking: generate with some hotels incomplete ----------
        await page.evaluate("KhannaState.getApplications().forEach(function(a){KhannaState.deleteApplication(a.id);})")
        hid = await page.evaluate(
            """(function(){var S=KhannaState;var a=S.createApplication('x');S.updateApplication(a.id,{applicant:{fullName:'Gen Test'}});
            var h1=S.addHotel(a.id);S.updateHotel(a.id,h1.id,{hotelName:'Hotel Lowen Am See',city:'Zug',country:'Switzerland',checkIn:'2026-11-15',checkOut:'2026-11-25'},null);
            var h2=S.addHotel(a.id);S.updateHotel(a.id,h2.id,{hotelName:'mage at 15.17.34.jpeg Uploaded vouc'},null);
            S.setActiveApplicationId(a.id);return a.id;})()"""
        )
        await page.evaluate("location.hash = '#/hotel-blocking'")
        await page.wait_for_timeout(600)
        btn = page.locator("[data-action='generate-voucher']")
        checks.check("Generate is enabled when at least one hotel is complete", await btn.is_enabled())
        notice = await page.inner_text("[data-hotel-skipped-notice]")
        checks.check(
            "the incomplete hotel is named, with what it is missing",
            "mage at 15.17.34.jpeg" in notice and "city" in notice and "check-in" in notice,
            notice,
        )
        await btn.click()
        await wait_preview_ready(page, "[data-voucher-preview]")
        checks.check("clicking Generate produces the preview", await page.locator("[data-voucher-preview] canvas").count() > 0)
        checks.check("no error shown", await page.locator("[data-voucher-error] .notice-danger").count() == 0)

        # nothing complete -> still disabled, with the reason
        await page.evaluate(
            f"(function(){{var a=KhannaState.getApplication('{hid}');KhannaState.updateHotel(a.id,a.hotels[0].id,{{city:''}},null);}})()"
        )
        await page.wait_for_timeout(400)
        checks.check("with no complete hotel the button stays disabled", await page.locator("[data-action='generate-voucher']").is_disabled())
        checks.check("...and says why", "Add at least one hotel" in await page.inner_text("[data-voucher-generate]"))

        real_errors = [e for e in console_errors if "favicon" not in e.lower()]
        checks.check("no browser console errors", not real_errors, "; ".join(real_errors[:3]))
        await browser.close()
    checks.report_and_exit()


asyncio.run(main())
