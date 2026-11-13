"""
End-to-end: every date box is typed and shown as DD/MM/YYYY
(js/core/date-input.js, and the passport / visa-form date boxes).
The date is still saved as YYYY-MM-DD. Invented data only (project rule 11).
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from playwright.async_api import async_playwright  # noqa: E402

from _common import Checks, fresh_load_and_login  # noqa: E402

C = Checks()
SHOTS = os.environ.get("KHANNA_E2E_SHOTS", "")

SEED = """() => {
  const S = window.KhannaState;
  const app = S.createApplication('e2e');
  S.updateApplication(app.id, { applicant: { salutation: 'Mr', fullName: 'ANIL TESTER', firstName: 'ANIL', lastName: 'TESTER',
    passport: { current: { number: 'Z1234567' } } }, invitation: { travelStartDate: '2030-12-04' } });
  S.setActiveApplicationId(app.id);
  return app.id;
}"""


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page(viewport={"width": 1280, "height": 900})
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        await fresh_load_and_login(page)
        app_id = await page.evaluate(SEED)

        await page.evaluate("location.hash = '#/invitation-letter'")
        await page.wait_for_selector(".ddmm__text", timeout=15000)
        start = page.locator("[data-invitation-field='top:travelStartDate']")
        box = start.locator("xpath=preceding-sibling::input[contains(@class,'ddmm__text')]")
        C.check("browser date boxes replaced by DD/MM/YYYY boxes", await page.locator(".ddmm__text").count() >= 3
                and await page.get_attribute(".ddmm__text", "placeholder") == "DD/MM/YYYY")
        C.check("a saved date is shown as DD/MM/YYYY", await box.input_value() == "04/12/2030", await box.input_value())

        end_native = page.locator("[data-invitation-field='top:travelEndDate']")
        end_box = end_native.locator("xpath=preceding-sibling::input[contains(@class,'ddmm__text')]")
        await end_box.click()
        await end_box.press_sequentially("10122030")
        C.check("slashes put in while typing", await end_box.input_value() == "10/12/2030")
        C.check("saved as YYYY-MM-DD in the date box", await end_native.input_value() == "2030-12-10")
        await end_box.press("Tab")
        await page.wait_for_timeout(300)
        saved = await page.evaluate("(id) => (window.KhannaState.getApplication(id).invitation || {}).travelEndDate", app_id)
        C.check("…and saved with the application", saved == "2030-12-10", str(saved))

        await end_box.fill("31/02/2030")
        await end_box.press("Tab")
        C.check("an impossible date is outlined and not used", "is-invalid" in (await end_box.get_attribute("class") or "")
                and await end_native.input_value() == "2030-12-10")

        await page.evaluate("""() => { document.querySelector("[data-invitation-field='top:returnDate']").value = '2030-12-12'; }""")
        ret_box = page.locator("[data-invitation-field='top:returnDate']").locator("xpath=preceding-sibling::input[contains(@class,'ddmm__text')]")
        C.check("a date set by the page shows as DD/MM/YYYY", await ret_box.input_value() == "12/12/2030")
        await page.fill("[data-invitation-field='top:travelStartDate']", "2030-11-30")
        C.check("filling the date box directly still works", await box.input_value() == "30/11/2030")
        if SHOTS:
            await page.screenshot(path=os.path.join(SHOTS, "dates_invitation.png"))

        # Passport and visa-form date boxes (typed text boxes) also use slashes.
        await page.evaluate("location.hash = '#/fill-forms'")
        await page.wait_for_selector("#ff-dob", timeout=15000)
        C.check("visa form date box placeholder DD/MM/YYYY", await page.get_attribute("#ff-dob", "placeholder") == "DD/MM/YYYY")
        await page.fill("#ff-dob", "14-05-1980")
        await page.locator("#ff-dob").blur()
        await page.wait_for_timeout(200)
        C.check("visa form date shown as DD/MM/YYYY", await page.input_value("#ff-dob") == "14/05/1980", await page.input_value("#ff-dob"))

        for width in (320, 390):
            await page.set_viewport_size({"width": width, "height": 800})
            await page.evaluate("location.hash = '#/invitation-letter'")
            await page.wait_for_timeout(300)
            overflow = await page.evaluate("document.documentElement.scrollWidth - innerWidth")
            C.check(f"no horizontal overflow at {width}px", overflow <= 1, str(overflow))
        C.check("no page errors", not errors, " | ".join(errors[:3]))
        await browser.close()
    C.report_and_exit()


if __name__ == "__main__":
    asyncio.run(main())
