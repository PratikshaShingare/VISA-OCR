"""
"+ Add another traveller" on the Cover Letter, Passport Authorization,
Company Authorization and Invitation Letter pages (js/add-traveller.js).

For every page: the button is there (same blue small button as Hotel
Blocking's "Add hotel Manually"), opens the form, refuses a missing name /
passport number, saves the person as a REAL traveller on the application,
ticks them on that page (letters no longer have a people limit). No backend needed - nothing generates here.
"""

import asyncio

from playwright.async_api import async_playwright

from _common import BASE, Checks, fresh_load_and_login

checks = Checks()

SEED = """(function(){
  var S = KhannaState;
  var a = S.createApplication('x');
  S.updateApplication(a.id, { applicant: { salutation: 'Mr', firstName: 'Rahul', lastName: 'Sharma', fullName: 'Rahul Sharma', sex: 'M',
    passport: { current: { number: 'P1111111', issuePlace: 'Mumbai', issueDate: '2020-01-01' } } } });
  S.setActiveApplicationId(a.id);
  return a.id;
})()"""


VIEW = [""]


async def fill_and_submit(page, name, passport):
    await page.fill("[data-add-traveller-field='fullName']", name)
    await page.fill("[data-add-traveller-field='passportNumber']", passport)
    await page.select_option("[data-add-traveller-field='sex']", "F")
    # whatever this letter marks as required (it differs per document)
    await page.select_option("[data-add-traveller-field='salutation']", "Ms")
    await page.fill("[data-add-traveller-field='phone']", "9000000001")
    await page.fill("[data-add-traveller-field='email']", "typed.person@example.com")
    await page.fill("[data-add-traveller-field='issuePlace']", "Pune")
    await page.fill("[data-add-traveller-field='issueDate']", "2020-03-03")
    await page.click("[data-add-traveller-form] button[type='submit']")
    await page.wait_for_timeout(300)


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page(viewport={"width": 1280, "height": 1000})
        errors = []
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        page.on("pageerror", lambda e: errors.append(str(e)))
        await fresh_load_and_login(page, base=BASE)
        app_id = await page.evaluate(SEED)

        # ---------- Passport Authorization (1-2 people) ----------
        VIEW[0] = "passport-authorization"
        await page.evaluate("location.hash = '#/passport-authorization'")
        await page.wait_for_timeout(600)
        btn = page.locator("[data-view='passport-authorization'] [data-action='add-another-traveller']")
        checks.check("Passport Authorization: button present, blue small button with a plus", await btn.count() == 1 and "btn-primary" in (await btn.get_attribute("class")) and "btn-sm" in (await btn.get_attribute("class")))
        checks.check("Button reads 'Enter details manually'", (await btn.inner_text()).strip() == "Enter details manually")
        await btn.click()
        await page.wait_for_timeout(200)
        checks.check("Click opens the form", await page.locator("[data-add-traveller-overlay]:not([hidden])").count() == 1)
        await page.click("[data-add-traveller-form] button[type='submit']")
        checks.check("Empty form is refused with a message", "full name" in (await page.inner_text("[data-add-traveller-error]")).lower())
        await page.fill("[data-add-traveller-field='fullName']", "Priya Sharma")
        await page.click("[data-add-traveller-form] button[type='submit']")
        checks.check("Missing passport number is refused", "passport number" in (await page.inner_text("[data-add-traveller-error]")).lower())
        await page.fill("[data-add-traveller-field='passportNumber']", "p2222222")
        await page.select_option("[data-add-traveller-field='sex']", "F")
        await page.fill("[data-add-traveller-field='issuePlace']", "Mumbai")
        await page.fill("[data-add-traveller-field='issueDate']", "2021-02-02")
        await page.click("[data-add-traveller-form] button[type='submit']")
        checks.check("A letter's required details (salutation, phone, email) are enforced",
                     "salutation" in (await page.inner_text("[data-add-traveller-error]")).lower(),
                     await page.inner_text("[data-add-traveller-error]"))
        await page.select_option("[data-add-traveller-field='salutation']", "Ms")
        await page.fill("[data-add-traveller-field='phone']", "9000000002")
        await page.fill("[data-add-traveller-field='email']", "priya@example.com")
        await page.click("[data-add-traveller-form] button[type='submit']")
        await page.wait_for_timeout(400)
        trav = await page.evaluate("KhannaState.getActiveApplication().travellers.map(t => ({n: t.fullName, p: t.passport.current.number, s: t.sex, pl: t.passport.current.issuePlace}))")
        checks.check("Saved as a real traveller (upper-cased passport number, sex, place)", trav == [{"n": "Priya Sharma", "p": "P2222222", "s": "F", "pl": "Mumbai"}], str(trav))
        sel = await page.evaluate("KhannaState.getActiveApplication().authorization.passport.selectedPersonIds.length")
        checks.check("The new traveller is ticked on the letter", sel == 1, str(sel))
        list_text = await page.inner_text("[data-view='passport-authorization'] [data-auth-checklist='passport']")
        checks.check("They appear in the people list", "Priya Sharma" in list_text, list_text)

        # duplicate passport number refused
        await btn.click()
        await fill_and_submit(page, "Someone Else", "P2222222")
        checks.check("A duplicate passport number is refused", "already on this application" in (await page.inner_text("[data-add-traveller-error]")))
        await page.click("[data-add-traveller-cancel].btn-secondary")

        # tick the applicant too (2 selected) -> a third is added AND ticked (no person limit any more)
        await page.evaluate("(function(){var a=KhannaState.getActiveApplication();KhannaState.updateApplication(a.id,{authorization:{passport:{selectedPersonIds:['applicant'].concat(a.authorization.passport.selectedPersonIds)}}},null);})()")
        await page.wait_for_timeout(300)
        await btn.click()
        await fill_and_submit(page, "Third Person", "P3333333")
        trav = await page.evaluate("KhannaState.getActiveApplication().travellers.length")
        sel = await page.evaluate("KhannaState.getActiveApplication().authorization.passport.selectedPersonIds.length")
        checks.check("With 2 already ticked the third is added and ticked too (no limit)", trav == 2 and sel == 3, f"{trav} / {sel}")
        status = await page.inner_text("[data-view='passport-authorization'] [data-auth-existing-status]")
        checks.check("...and the page says they were selected", "selected them" in status, status)

        # ---------- Company Authorization ----------
        await page.evaluate("location.hash = '#/company-authorization'")
        await page.wait_for_timeout(600)
        cbtn = page.locator("[data-view='company-authorization'] [data-action='add-another-traveller']")
        checks.check("Company Authorization: button present", await cbtn.count() == 1)
        before = await page.evaluate("KhannaState.getActiveApplication().authorization.company.selectedPersonIds.length")
        await cbtn.click()
        await fill_and_submit(page, "Company Person", "C4444444")
        after = await page.evaluate("KhannaState.getActiveApplication().authorization.company.selectedPersonIds.length")
        checks.check("Company letter: new traveller is ticked", after == before + 1, f"{before} -> {after}")
        checks.check("Company letter: listed", "Company Person" in await page.inner_text("[data-view='company-authorization'] [data-auth-checklist='company']"))

        # ---------- Invitation + inviter covering letter ----------
        await page.evaluate("(function(){var a=KhannaState.getActiveApplication();KhannaState.updateApplication(a.id,{invitation:{selectedInviteeIds:[]},initorsLetters:{selectedPersonIds:[]}},null);})()")
        await page.evaluate("location.hash = '#/invitation-letter'")
        await page.wait_for_timeout(700)
        ibtns = page.locator("[data-view='invitation-letter'] [data-action='add-another-traveller']")
        checks.check("Invitation page: a button on each of its two cards", await ibtns.count() == 2, str(await ibtns.count()))
        await ibtns.nth(0).click()
        await fill_and_submit(page, "Invitee One", "I5555555")
        n1 = await page.evaluate("KhannaState.getActiveApplication().invitation.selectedInviteeIds.length")
        checks.check("Invitation card: new traveller ticked as an invitee", n1 == 1, str(n1))
        n_other = await page.evaluate("(KhannaState.getActiveApplication().initorsLetters.selectedPersonIds || []).length")
        checks.check("...and the covering-letter card was not touched", n_other == 0, str(n_other))
        await ibtns.nth(1).click()
        await fill_and_submit(page, "Couple One", "I6666666")
        n2 = await page.evaluate("KhannaState.getActiveApplication().initorsLetters.selectedPersonIds.length")
        checks.check("Inviter covering letter card: new traveller ticked", n2 == 1, str(n2))

        # ---------- Cover letter (Europe) ----------
        await page.evaluate("location.hash = '#/cover-letter'")
        await page.wait_for_timeout(600)
        inp = page.locator("[data-cover-country-search]")
        await inp.click()
        await inp.fill("swit")
        await inp.press("Enter")
        await page.wait_for_timeout(500)
        kbtn = page.locator("[data-view='cover-letter'] [data-action='add-another-traveller']")
        checks.check("Cover Letter: button present once a country is chosen", await kbtn.count() == 1)
        await kbtn.click()
        await fill_and_submit(page, "Cover Person", "K7777777")
        n = await page.evaluate("KhannaState.getActiveApplication().coverLetter.selectedPersonIds.length")
        checks.check("Cover letter: new traveller ticked", n == 1, str(n))
        checks.check("Cover letter: listed in the people list", "Cover Person" in await page.inner_text("[data-view='cover-letter'] [data-cover-checklist]"))
        await kbtn.click()
        await fill_and_submit(page, "Cover Two", "K8888888")
        await kbtn.click()
        await fill_and_submit(page, "Cover Three", "K9999999")
        n = await page.evaluate("KhannaState.getActiveApplication().coverLetter.selectedPersonIds.length")
        checks.check("Cover letter (Europe): a third person is added and ticked (no limit)", n == 3, str(n))

        # ---------- layout ----------
        for w in (1280, 390, 320):
            await page.set_viewport_size({"width": w, "height": 900})
            await page.wait_for_timeout(200)
            over = await page.evaluate("document.documentElement.scrollWidth > document.documentElement.clientWidth")
            checks.check(f"No horizontal overflow on the Cover Letter page at {w}px", not over)
        await page.set_viewport_size({"width": 320, "height": 800})
        await kbtn.click()
        await page.wait_for_timeout(200)
        over = await page.evaluate("document.documentElement.scrollWidth > document.documentElement.clientWidth")
        box = await page.locator("[data-add-traveller-overlay] .app-picker").bounding_box()
        checks.check("The form fits inside a 320px screen", not over and box["x"] >= 0 and box["x"] + box["width"] <= 320, str(box))

        checks.check("No console errors", not errors, "; ".join(errors[:3]))
        await browser.close()
    checks.report_and_exit()


if __name__ == "__main__":
    asyncio.run(main())
