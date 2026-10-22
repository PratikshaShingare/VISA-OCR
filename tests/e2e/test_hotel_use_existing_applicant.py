"""
Hotel Blocking — "Use existing applicant" (lead guest / additional guest).

Seeds one saved applicant profile into the shared pool, then checks that the
two buttons in the hotel panel open the shared picker and fill the lead guest
name / add a guest name (no duplicates), and that the hotel record keeps it.
"""
import asyncio

from playwright.async_api import async_playwright

from _common import BASE, Checks, fresh_load_and_login, start_guided_wizard_application

checks = Checks()


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await (await browser.new_context(viewport={"width": 1280, "height": 1400})).new_page()
        errors = []
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
        await fresh_load_and_login(page, base=BASE)
        await start_guided_wizard_application(page)
        await page.wait_for_timeout(300)
        await page.evaluate(
            "KhannaState.saveApplicantProfile({fullName:'Asha Verma', salutation:'Mrs', passport:{current:{number:'Z1234567'}}})"
        )
        await page.evaluate("location.hash = '#/new-application/5'")
        await page.wait_for_timeout(300)
        await page.click("[data-action='add-hotel']")
        await page.wait_for_timeout(250)
        await page.fill("#hf-hotelName", "Test Hotel")

        await page.click("[data-action='hotel-use-applicant-lead']")
        await page.wait_for_timeout(200)
        checks.check("picker opens", await page.locator(".app-picker__result").count() >= 1)
        await page.click("[data-action='pick-applicant']")
        await page.wait_for_timeout(300)
        checks.check("lead guest filled", (await page.input_value("#hf-leadGuestName")) == "Mrs. Asha Verma", await page.input_value("#hf-leadGuestName"))
        checks.check("typed hotel name kept", (await page.input_value("#hf-hotelName")) == "Test Hotel")

        await page.click("[data-action='hotel-use-applicant-guest']")
        await page.wait_for_timeout(200)
        await page.click("[data-action='pick-applicant']")
        await page.wait_for_timeout(300)
        checks.check("duplicate of lead guest is not added again", await page.locator("[data-guest-name-input]").count() == 0)

        await page.evaluate("KhannaState.saveApplicantProfile({fullName:'Ravi Verma'})")
        await page.click("[data-action='hotel-use-applicant-guest']")
        await page.wait_for_timeout(200)
        await page.locator(".app-picker__result", has_text="Ravi Verma").click()
        await page.wait_for_timeout(300)
        vals = await page.locator("[data-guest-name-input]").evaluate_all("els=>els.map(e=>e.value)")
        checks.check("second person added as guest", vals == ["Ravi Verma"], str(vals))
        checks.check("no console errors", not errors, "; ".join(errors[:3]))
        await browser.close()
    checks.report_and_exit()


asyncio.run(main())
