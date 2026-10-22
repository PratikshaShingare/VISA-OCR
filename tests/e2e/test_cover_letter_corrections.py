"""Cover Letter page corrections:
  1) Save is refused (and the button looks unavailable) while the page has nothing
     filled in; hotel blockings with no hotel details are not listed for reuse.
  2) Travel dates: never in the past, an end date never before its start date.
  3) "Travel expenses funded by" is a dropdown (Self / Inviter / Company / Other,
     or Individual / ... when several people travel) with payer name + relation.
Synthetic people only."""
import asyncio

from playwright.async_api import async_playwright

from _common import BASE, Checks, ensure_fixtures, fresh_load_and_login, future_date, select_cover_letter_country

checks = Checks()

SEED = """
(function () {
  var S = KhannaState;
  var a = S.createApplication('x');
  S.updateApplication(a.id, { applicant: {
    salutation: 'Mr', firstName: 'Test', lastName: 'Traveller', fullName: 'Test Traveller', sex: 'Male',
    passport: { current: { number: 'P1111111', issuePlace: 'Mumbai', issueDate: '2020-01-01' } },
    address: { city: 'Pune', country: 'India' } } });
  var t = S.addTraveller(a.id, 'Wife');
  S.updateTraveller(a.id, t.id, { salutation: 'Mrs', fullName: 'Test Companion', sex: 'Female',
    passport: { current: { number: 'P2222222', issuePlace: 'Mumbai', issueDate: '2021-02-02' } } }, null);
  // an application whose hotel blocking has only an empty hotel row
  var b = S.createApplication('x');
  S.updateApplication(b.id, { applicant: { fullName: 'Empty Hotel Guest' } });
  S.addHotel(b.id);
  S.setActiveApplicationId(a.id);
  return { a: a.id, b: b.id };
})()
"""


async def toast_text(page):
    return (await page.evaluate("(document.querySelector('.toast, [data-toast]') || {}).innerText || ''")) or ""


async def main():
    ensure_fixtures()
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page(viewport={"width": 1280, "height": 1100})
        errors = []
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
        await fresh_load_and_login(page, base=BASE)
        ids = await page.evaluate(SEED)
        today = await page.evaluate("KhannaUtils.todayIso()")
        await page.evaluate("location.hash = '#/cover-letter'")
        await page.wait_for_timeout(600)

        # ---------- 1) Save needs something filled ----------
        save = page.locator("[data-action='save-doc-application']")
        checks.check("Save looks unavailable on an empty cover letter", await save.get_attribute("aria-disabled") == "true")
        await save.click(force=True)
        await page.wait_for_timeout(250)
        saved = await page.evaluate(f"!!KhannaState.getApplication('{ids['a']}').explicitlySavedAt")
        checks.check("clicking Save on an empty cover letter saves nothing", saved is False)
        await select_cover_letter_country(page, "France")
        await page.wait_for_timeout(200)
        checks.check("choosing only the country is still 'nothing filled'", await page.locator("[data-action='save-doc-application']").get_attribute("aria-disabled") == "true")
        await page.fill("[data-cover-field='top:travelStartDate']", future_date(30))
        await page.press("[data-cover-field='top:travelStartDate']", "Tab")
        await page.wait_for_timeout(250)
        checks.check("Save becomes available once something is filled", await page.locator("[data-action='save-doc-application']").get_attribute("aria-disabled") is None)
        await page.click("[data-action='save-doc-application']")
        await page.wait_for_timeout(250)
        saved = await page.evaluate(f"!!KhannaState.getApplication('{ids['a']}').explicitlySavedAt")
        checks.check("...and then Save works", saved is True)

        # hotel blocking page: empty hotel row cannot be saved
        await page.evaluate(f"KhannaState.setActiveApplicationId('{ids['b']}')")
        await page.evaluate("location.hash = '#/hotel-blocking'")
        await page.wait_for_timeout(600)
        hsave = page.locator("[data-view='hotel-blocking'] [data-action='save-doc-application']")
        checks.check("Hotel Blocking: Save unavailable while the hotel has no details", await hsave.get_attribute("aria-disabled") == "true")
        await hsave.click(force=True)
        await page.wait_for_timeout(250)
        saved_b = await page.evaluate(f"!!KhannaState.getApplication('{ids['b']}').explicitlySavedAt")
        checks.check("...and nothing is saved", saved_b is False)
        usable = await page.evaluate("KhannaSavedDetails.hotelBlockingSources().length")
        checks.check("a blocking with only an empty hotel row is not offered for reuse", usable == 0, str(usable))

        # ---------- 2) dates ----------
        await page.evaluate(f"KhannaState.setActiveApplicationId('{ids['a']}')")
        await page.evaluate("location.hash = '#/cover-letter'")
        await page.wait_for_timeout(700)
        start = "[data-cover-field='top:travelStartDate']"
        end = "[data-cover-field='top:travelEndDate']"
        checks.check("start date input has today as its minimum", await page.get_attribute(start, "min") == today)
        s_val = future_date(30)
        checks.check("start date from the earlier step is kept", await page.input_value(start) == s_val, await page.input_value(start))
        await page.fill(start, "2020-01-01")
        await page.press(start, "Tab")
        await page.wait_for_timeout(250)
        checks.check("a past start date is refused (previous value restored)", await page.input_value(start) == s_val, await page.input_value(start))
        err = await page.inner_text("[data-cover-error]")
        checks.check("...with a clear message", "past" in err.lower(), err)
        checks.check("end date's minimum follows the start date", await page.get_attribute(end, "min") == s_val, str(await page.get_attribute(end, "min")))
        await page.fill(end, future_date(10))
        await page.press(end, "Tab")
        await page.wait_for_timeout(250)
        checks.check("an end date before the start date is refused", await page.input_value(end) == "", await page.input_value(end))
        err = await page.inner_text("[data-cover-error]")
        checks.check("...with a clear message", "before" in err.lower(), err)
        e_val = future_date(45)
        await page.fill(end, e_val)
        await page.press(end, "Tab")
        await page.wait_for_timeout(250)
        checks.check("a valid end date is accepted", await page.input_value(end) == e_val)
        later = future_date(60)
        await page.fill(start, later)
        await page.press(start, "Tab")
        await page.wait_for_timeout(250)
        checks.check("moving the start after the end clears the end date", await page.input_value(end) == "", await page.input_value(end))
        checks.check("...and tells the user", "cleared" in (await page.inner_text("[data-cover-error]")).lower())
        await page.fill(start, future_date(30))
        await page.press(start, "Tab")
        await page.fill(end, e_val)
        await page.press(end, "Tab")
        await page.wait_for_timeout(250)

        # ---------- 3) funded by ----------
        fund = "[data-cover-field='top:fundingType']"
        opts = await page.locator(f"{fund} option").all_inner_texts()
        checks.check("nobody ticked yet -> options are Self / Inviter / Company / Other", [o.strip() for o in opts] == ["Select…", "Self", "Inviter", "Company", "Other"], str(opts))
        boxes = page.locator("[data-cover-checklist] input[type=checkbox]")
        await boxes.nth(0).check()
        await page.wait_for_timeout(250)
        opts = await page.locator(f"{fund} option").all_inner_texts()
        checks.check("one applicant ticked -> Self / Inviter / Company / Other", [o.strip() for o in opts] == ["Select…", "Self", "Inviter", "Company", "Other"], str(opts))
        await boxes.nth(1).check()
        await page.wait_for_timeout(250)
        opts = await page.locator(f"{fund} option").all_inner_texts()
        checks.check("several applicants ticked -> Individual / Inviter / Company / Other", [o.strip() for o in opts] == ["Select…", "Individual", "Inviter", "Company", "Other"], str(opts))
        checks.check("no payer boxes before a choice", await page.locator("[data-cover-field='top:fundingPayerName']").count() == 0)

        await page.select_option(fund, "self")
        await page.wait_for_timeout(250)
        checks.check("Individual needs no payer details", await page.locator("[data-cover-field='top:fundingPayerName']").count() == 0)
        arrangement = await page.evaluate(f"KhannaState.getApplication('{ids['a']}').coverLetter.fundingArrangement")
        checks.check("Individual with two travellers reads 'ourselves'", arrangement == "ourselves", arrangement)

        for kind, label in [("inviter", "Inviter"), ("company", "Company"), ("other", "Other")]:
            await page.select_option(fund, kind)
            await page.wait_for_timeout(250)
            name_ok = await page.locator("[data-cover-field='top:fundingPayerName']").count() == 1
            rel_ok = await page.locator("[data-cover-field='top:fundingRelation']").count() == 1
            checks.check(f"{label}: payer name and relation boxes appear", name_ok and rel_ok)
        await page.select_option(fund, "inviter")
        await page.wait_for_timeout(250)
        notice = await page.inner_text("[data-cover-readiness]")
        checks.check("Generate is held back until the payer is named", await page.locator("[data-action='generate-cover-letter']").is_disabled())
        await page.fill("[data-cover-field='top:fundingPayerName']", "Ravi Kumar")
        await page.press("[data-cover-field='top:fundingPayerName']", "Tab")
        await page.fill("[data-cover-field='top:fundingRelation']", "Brother")
        await page.press("[data-cover-field='top:fundingRelation']", "Tab")
        await page.wait_for_timeout(250)
        arrangement = await page.evaluate(f"KhannaState.getApplication('{ids['a']}').coverLetter.fundingArrangement")
        checks.check("the letter reads 'Name (relation)'", arrangement == "Ravi Kumar (Brother)", arrangement)
        await page.select_option(fund, "self")
        await page.wait_for_timeout(250)
        cl = await page.evaluate(f"KhannaState.getApplication('{ids['a']}').coverLetter")
        checks.check("switching to Individual clears the payer details", cl["fundingPayerName"] == "" and cl["fundingRelation"] == "", str(cl))
        await boxes.nth(1).uncheck()
        await page.wait_for_timeout(250)
        arrangement = await page.evaluate(f"KhannaState.getApplication('{ids['a']}').coverLetter.fundingArrangement")
        checks.check("back to one traveller: Self reads 'myself'", arrangement == "myself", arrangement)
        label_txt = (await page.locator(f"{fund} option:checked").inner_text()).strip()
        checks.check("...and the choice is now labelled Self", label_txt == "Self", label_txt)

        checks.check("no console errors", not errors, "; ".join(errors[:3]))
        await browser.close()
    checks.report_and_exit()


if __name__ == "__main__":
    asyncio.run(main())
