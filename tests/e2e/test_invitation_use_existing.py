"""
Invitation Letter page — "Use Existing Details" (replaces the old "Use
Existing Application" / "Use Existing Applicant" buttons), modelled on the
Cover Letter's dropdown.

Covers (real static server, no backend needed — nothing here generates):
  - the top bar no longer offers "Use Existing Application" / "Applicant".
  - one "Use Existing Details" dropdown in each of the page's two cards.
  - Passport: two-box dropdown; picking a saved passport adds that person to
    the active application as a traveller (source untouched), ticks them;
    a third pick is refused (letter takes exactly 2) and adds nobody.
  - Hotel Blocking: fills travel dates + accommodation from a saved hotel
    blocking, never invents the return date and says so.
  - The couple's (Initors) letter's dropdown does the same for its own card
    (incl. destination country) and only touches that card.
  - The guided wizard's step 7 (same code) does not show the dropdown.
  - 375px: no horizontal overflow; no browser console errors.
"""

import asyncio

from playwright.async_api import async_playwright

from _common import BASE, Checks, ensure_fixtures, fresh_load_and_login, start_guided_wizard_application

checks = Checks()

SEED = """
(function () {
  var S = KhannaState;
  var a = S.createApplication('x');
  S.updateApplication(a.id, { applicant: {
    salutation: 'Mr', firstName: 'Rahul', lastName: 'Sharma', fullName: 'Rahul Sharma', sex: 'Male',
    passport: { current: { number: 'P1111111', issuePlace: 'Mumbai', issueDate: '2020-01-01' } } } });
  var t = S.addTraveller(a.id, 'Wife');
  S.updateTraveller(a.id, t.id, { salutation: 'Mrs', fullName: 'Priya Sharma', sex: 'Female',
    passport: { current: { number: 'P2222222', issuePlace: 'Mumbai', issueDate: '2021-02-02' } } }, null);
  var b = S.createApplication('x');
  S.updateApplication(b.id, { applicant: { fullName: 'Hotel Guest' } });
  var h1 = S.addHotel(b.id); S.updateHotel(b.id, h1.id, { hotelName: 'Hotel Lowen Am See', city: 'Zug', country: 'Switzerland', checkIn: '2026-11-15', checkOut: '2026-11-25' }, null);
  var h2 = S.addHotel(b.id); S.updateHotel(b.id, h2.id, { hotelName: 'Hotel Roma Centro', city: 'Rome', country: 'Italy', checkIn: '2026-11-25', checkOut: '2026-11-28' }, null);
  S.saveApplicantProfile({ salutation: 'Mr', firstName: 'Old', lastName: 'Profile', fullName: 'Old Profile',
    passport: { current: { number: 'P3333333' } } });
  var target = S.createApplication('x');
  S.setActiveApplicationId(target.id);
  return { target: target.id, a: a.id, b: b.id };
})()
"""


async def main():
    ensure_fixtures()
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page(viewport={"width": 1280, "height": 1200})
        console_errors = []
        page.on("console", lambda m: console_errors.append(m.text) if m.type == "error" else None)
        page.on("pageerror", lambda e: console_errors.append(f"pageerror: {e}"))
        await fresh_load_and_login(page, base=BASE)

        ids = await page.evaluate(SEED)
        await page.evaluate("location.hash = '#/invitation-letter'")
        await page.wait_for_timeout(700)

        # ---------- 1) top bar ----------
        bar = await page.inner_text("[data-view='invitation-letter'] [data-doc-page-app-bar]")
        checks.check("no 'Use Existing Application' button in the top bar", await page.locator("[data-view='invitation-letter'] [data-action='pick-doc-application']").count() == 0 and "Use Existing Application" not in bar, bar)
        checks.check("no 'Use Existing Applicant' button in the top bar", await page.locator("[data-view='invitation-letter'] [data-action='pick-doc-applicant']").count() == 0, bar)
        checks.check("top bar still has Save + Start a different application", "Save" in bar and "Start a different application" in bar, bar)

        # ---------- 2) one dropdown per card ----------
        checks.check("a 'Use Existing Details' dropdown in each of the two cards", await page.locator("[data-inv-use-existing-toggle]").count() == 2)
        inv = page.locator("[data-invitation-card]")
        toggle = inv.locator("[data-inv-use-existing-toggle]")
        await toggle.click()
        items = await inv.locator(".cover-existing-menu__item").all_inner_texts()
        checks.check("menu offers Passport and Hotel Blocking", [i.replace("▸", "").strip() for i in items] == ["Passport", "Hotel Blocking"], str(items))
        checks.check("second list hidden until a kind is chosen", await inv.locator("[data-inv-existing-list]").is_hidden())
        await inv.locator("[data-inv-use-existing-option='passport']").click()
        lst = inv.locator("[data-inv-existing-list]")
        m_box = await inv.locator(".cover-existing-menu").bounding_box()
        l_box = await lst.bounding_box()
        checks.check("choosing Passport opens a list beside the menu", await lst.is_visible() and l_box["x"] >= m_box["x"] + m_box["width"] - 1, f"{m_box} {l_box}")
        txt = await lst.inner_text()
        checks.check("lists saved passports incl. saved profiles", "Rahul Sharma" in txt and "P2222222" in txt and "Old Profile" in txt, txt)

        # ---------- 3) pick passports ----------
        await inv.locator("[data-inv-existing-pick='passport'][data-passport-key='P1111111']").click()
        await page.wait_for_timeout(400)
        rows = await inv.locator(".auth-person-row").all_inner_texts()
        checks.check("picked passport appears and is ticked as an invitee", len(rows) == 1 and "Rahul Sharma" in rows[0] and await inv.locator("[data-invitation-invitee]:checked").count() == 1, str(rows))
        n_trav = await page.evaluate(f"KhannaState.getApplication('{ids['target']}').travellers.length")
        checks.check("...and was added to this application as a traveller", n_trav == 1, str(n_trav))
        status = await inv.locator("[data-inv-existing-status]").inner_text()
        checks.check("status says who was selected and that they were added", "Rahul Sharma" in status and "added to this application" in status, status)

        await toggle.click()
        await inv.locator("[data-inv-use-existing-option='passport']").click()
        await inv.locator("[data-inv-existing-pick='passport'][data-passport-key='P2222222']").click()
        await page.wait_for_timeout(400)
        checks.check("second passport selected too (2 ticked)", await inv.locator("[data-invitation-invitee]:checked").count() == 2)

        await toggle.click()
        await inv.locator("[data-inv-use-existing-option='passport']").click()
        await inv.locator("[data-inv-existing-pick='passport'][data-passport-key='P3333333']").click()
        await page.wait_for_timeout(400)
        status = await inv.locator("[data-inv-existing-status]").inner_text()
        n_trav = await page.evaluate(f"KhannaState.getApplication('{ids['target']}').travellers.length")
        checks.check("a third pick is refused with an explanation", "exactly 2" in status, status)
        checks.check("...and adds nobody to the application", n_trav == 2, str(n_trav))
        src_name = await page.evaluate(f"KhannaState.getApplication('{ids['a']}').applicant.fullName")
        n_src = await page.evaluate(f"KhannaState.getApplication('{ids['a']}').travellers.length")
        checks.check("the source application is untouched", src_name == "Rahul Sharma" and n_src == 1)

        # ---------- 4) hotel blocking ----------
        await toggle.click()
        await inv.locator("[data-inv-use-existing-option='hotel-blocking']").click()
        txt = await inv.locator("[data-inv-existing-list]").inner_text()
        checks.check("lists saved hotel blockings", "Hotel Guest" in txt and "Hotel Lowen Am See" in txt, txt)
        await inv.locator(f"[data-inv-existing-pick='hotel-blocking'][data-app-id='{ids['b']}']").click()
        await page.wait_for_timeout(400)
        start = await page.input_value("#invitation-field-top-travelStartDate")
        end = await page.input_value("#invitation-field-top-travelEndDate")
        acc = await page.input_value("#invitation-field-top-accommodationDetails")
        ret = await page.input_value("#invitation-field-top-returnDate")
        checks.check("travel dates come from the hotel blocking", (start, end) == ("2026-11-15", "2026-11-28"), f"{start}/{end}")
        checks.check("accommodation reads after 'staying'", acc == "at Hotel Lowen Am See, Zug and Hotel Roma Centro, Rome", acc)
        checks.check("return date is NOT invented", ret == "", ret)
        status = await inv.locator("[data-inv-existing-status]").inner_text()
        checks.check("status names what was filled and the return date as manual", "Filled" in status and "return date" in status, status)
        still = await inv.locator("[data-invitation-invitee]:checked").count()
        checks.check("invitees stay ticked after the fill", still == 2, str(still))

        # ---------- 5) couple's letter card ----------
        ini = page.locator("[data-initors-card]")
        itoggle = ini.locator("[data-inv-use-existing-toggle]")
        await itoggle.click()
        await ini.locator("[data-inv-use-existing-option='passport']").click()
        await ini.locator("[data-inv-existing-pick='passport'][data-passport-key='P1111111']").click()
        await page.wait_for_timeout(400)
        status = await ini.locator("[data-inv-existing-status]").inner_text()
        n_trav = await page.evaluate(f"KhannaState.getApplication('{ids['target']}').travellers.length")
        checks.check("an already-present person is just selected (no duplicate traveller)", "added to this application" not in status and n_trav == 2, f"{status} / {n_trav}")
        await itoggle.click()
        await ini.locator("[data-inv-use-existing-option='passport']").click()
        await ini.locator("[data-inv-existing-pick='passport'][data-passport-key='P2222222']").click()
        await page.wait_for_timeout(400)
        checks.check("couple card: both selected, trip fields appear", await ini.locator("[data-initors-person]:checked").count() == 2 and await page.locator("#initors-field-top-country").count() == 1)
        await itoggle.click()
        await ini.locator("[data-inv-use-existing-option='hotel-blocking']").click()
        await ini.locator(f"[data-inv-existing-pick='hotel-blocking'][data-app-id='{ids['b']}']").click()
        await page.wait_for_timeout(400)
        country = await page.input_value("#initors-field-top-country")
        start = await page.input_value("#initors-field-top-travelStartDate")
        acc = await page.input_value("#initors-field-top-accommodationDetails")
        checks.check("couple card fills destination country, dates and accommodation", (country, start) == ("Switzerland", "2026-11-15") and acc.startswith("at Hotel Lowen"), f"{country}/{start}/{acc}")
        inv_acc = await page.input_value("#invitation-field-top-accommodationDetails")
        checks.check("...and only that card (the Invitation Letter card is unchanged)", inv_acc.startswith("at Hotel Lowen"))

        # ---------- 6) menu closes ----------
        await itoggle.click()
        checks.check("dropdown opens", await ini.locator("[data-inv-use-existing-dropdown]").evaluate("e => e.classList.contains('is-open')"))
        await page.keyboard.press("Escape")
        checks.check("Escape closes it", not await ini.locator("[data-inv-use-existing-dropdown]").evaluate("e => e.classList.contains('is-open')"))
        await itoggle.click()
        await page.click("[data-view='invitation-letter'] h1")
        checks.check("clicking elsewhere closes it", not await ini.locator("[data-inv-use-existing-dropdown]").evaluate("e => e.classList.contains('is-open')"))

        # ---------- 7) phone width ----------
        await page.set_viewport_size({"width": 375, "height": 800})
        await page.wait_for_timeout(300)
        overflow = await page.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth")
        checks.check("no horizontal overflow at 375px", overflow <= 1, str(overflow))
        await inv.locator("[data-inv-use-existing-toggle]").scroll_into_view_if_needed()
        await inv.locator("[data-inv-use-existing-toggle]").click()
        await inv.locator("[data-inv-use-existing-option='passport']").click()
        overflow = await page.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth")
        checks.check("...also with the dropdown open", overflow <= 1, str(overflow))
        await page.set_viewport_size({"width": 1280, "height": 1200})

        # ---------- 8) wizard step 7 (same code) has no dropdown ----------
        await start_guided_wizard_application(page)
        await page.evaluate("location.hash = '#/new-application/7'")
        await page.wait_for_timeout(500)
        checks.check("wizard step 7 shows the letters but no 'Use Existing Details'", await page.locator(".step-view[data-step='7'] [data-invitation-card]").count() == 1 and await page.locator(".step-view[data-step='7'] [data-inv-use-existing-toggle]").count() == 0)

        real_errors = [e for e in console_errors if "favicon" not in e.lower()]
        checks.check("no browser console errors", not real_errors, "; ".join(real_errors[:3]))
        await browser.close()
    checks.report_and_exit()


asyncio.run(main())
