"""
Clarity pass: the country selector, numbered form sections, the two-option
"existing / manual" cards and the missing-details warning, on the Cover Letter
and the Passport Authorization pages.
"""
import asyncio

from playwright.async_api import async_playwright

from _common import BASE, Checks, fresh_load_and_login

checks = Checks()

SEED = """() => {
  var a = KhannaState.createApplication("customercare@khannatravels.com");
  KhannaState.updateApplication(a.id, {
    applicant: Object.assign({}, a.applicant, { fullName: "TEST APPLICANT ONE", salutation: "Mr", sex: "M",
      passport: { current: { number: "X1234567" } } }),
    travel: Object.assign({}, a.travel, { destination: "Germany" })
  }, "seed");
  KhannaState.setActiveApplicationId(a.id);
  return a.id;
}"""


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        for width in (1280, 390, 320):
            page = await (await browser.new_context(viewport={"width": width, "height": 900})).new_page()
            errors = []
            page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
            page.on("pageerror", lambda e: errors.append(str(e)))
            await fresh_load_and_login(page, base=BASE)
            await page.evaluate(SEED)
            tag = f"[{width}px] "

            # ---- Cover letter ----
            await page.evaluate("location.hash = '#/cover-letter'")
            await page.wait_for_selector("#cover-country-input")
            await page.click("#cover-country-input")
            checks.check(tag + "list opens with a 'Suggested' group holding the application's destination",
                         await page.locator(".country-combo__group").first.inner_text() != ""
                         and await page.locator("[data-cover-country-option]").first.get_attribute("data-cover-country-option") == "Germany")
            await page.fill("#cover-country-input", "sing")
            await page.wait_for_timeout(150)
            checks.check(tag + "typing filters and drops the 'Suggested' group",
                         await page.locator(".country-combo__group").count() == 0
                         and await page.locator("[data-cover-country-option='Singapore']").count() == 1)
            await page.click("[data-cover-country-option='Germany']") if await page.locator("[data-cover-country-option='Germany']").count() else None
            await page.fill("#cover-country-input", "germ")
            await page.click("[data-cover-country-option='Germany']")
            await page.wait_for_timeout(700)
            await page.click("#cover-country-input")
            checks.check(tag + "the chosen country is marked with a tick state",
                         await page.locator("[data-cover-country-option='Germany'].is-selected").count() >= 1)
            await page.keyboard.press("Escape")
            titles = await page.locator(".view.is-active .form-step__title").all_inner_texts()
            checks.check(tag + "cover letter form is split into two numbered sections",
                         titles == ["Who is travelling", "Letter details"], str(titles))
            checks.check(tag + "both source cards are shown",
                         await page.locator(".view.is-active .source-option").count() == 2)
            noscroll = await page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth")
            checks.check(tag + "no horizontal overflow", noscroll)

            # ---- missing-details warning: spouse with no passport data, ticked ----
            if width == 1280:
                await page.evaluate("""() => { var a = KhannaState.getActiveApplication();
                  var w = KhannaState.addTraveller(a.id, "Spouse");
                  KhannaState.updateTraveller(a.id, w.id, { fullName: "TEST SPOUSE TWO" }, "seed"); }""")
                await page.evaluate("location.hash = '#/dashboard'")
                await page.wait_for_timeout(300)
                await page.evaluate("location.hash = '#/cover-letter'")
                await page.wait_for_timeout(900)
                boxes = page.locator(".view.is-active [data-cover-person]")
                for i in range(await boxes.count()):
                    await boxes.nth(i).check()
                await page.wait_for_timeout(400)
                checks.check(tag + "ticked people with empty required details trigger the missing-details warning",
                             await page.locator(".view.is-active [data-missing-details]").count() == 1)
                btn = page.locator(".view.is-active [data-complete-cover]").first
                checks.check(tag + "...with a 'Complete details' button", await btn.count() == 1)

            # ---- Passport authorization ----
            await page.evaluate("location.hash = '#/passport-authorization'")
            await page.wait_for_selector("#auth-passport-country")
            titles = await page.locator(".view.is-active [data-passport-auth-card] .form-step__title").all_inner_texts()
            checks.check(tag + "passport authorization form has its numbered sections",
                         titles == ["Who is authorising", "Letter details"], str(titles))
            checks.check(tag + "no horizontal overflow (authorization)",
                         await page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth"))
            checks.check(tag + "no console errors", not errors, "; ".join(errors[:3]))
            await page.context.close()
        await browser.close()
    checks.report_and_exit()


asyncio.run(main())
