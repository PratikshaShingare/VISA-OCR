"""
End-to-end: less text on screen (help behind an ⓘ) and needed fields
(js/core/form-guide.js). Invented data only (project rule 11).
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
  S.updateApplication(app.id, { applicant: { salutation: 'Mr', fullName: 'ANIL TESTER', firstName: 'ANIL', lastName: 'TESTER', dob: '1980-01-01',
    passport: { current: { number: 'Z1234567' } } }, authorization: { company: { selectedPersonIds: ['applicant'] } } });
  S.setActiveApplicationId(app.id);
  const p = S.saveApplicantProfile({ fullName: 'ANIL TESTER', passport: { current: { number: 'Z1234567' } } });
  return p.id;
}"""


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page(viewport={"width": 1280, "height": 900})
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        await fresh_load_and_login(page)
        pid = await page.evaluate(SEED)

        # ---- help texts behind an ⓘ ----
        await page.evaluate("location.hash = '#/applicant-profiles'")
        await page.click(f"[data-ap-open='{pid}']")
        await page.wait_for_selector("#ap-phone")
        await page.wait_for_timeout(200)
        hint = page.locator("#ap-phone").locator("xpath=..").locator(".ap-where")
        C.check("field explanation hidden", not await hint.is_visible())
        info = page.locator("label[for='ap-phone'] .fg-info")
        C.check("ⓘ next to the field label", await info.count() == 1)
        await info.click()
        C.check("ⓘ shows the explanation", await hint.is_visible() and "Used in" in await hint.inner_text())
        C.check("ⓘ does not move the cursor into the box", await page.evaluate("document.activeElement.id") != "ap-phone")
        await info.click()
        C.check("second press hides it again", not await hint.is_visible())
        C.check("page introduction behind an ⓘ on the title", not await page.locator(".ap-intro").first.is_visible()
                and await page.locator("[data-view='applicant-profiles'] h1 .fg-info").count() == 1)
        if SHOTS:
            await page.screenshot(path=os.path.join(SHOTS, "fg_profile.png"))

        # ---- needed fields: the details dialog (Save) ----
        await page.evaluate("location.hash = '#/company-authorization'")
        await page.wait_for_selector("[data-action='add-another-traveller']", timeout=15000)
        await page.click("[data-action='add-another-traveller']")
        await page.wait_for_selector("[data-add-traveller-overlay]:not([hidden])")
        await page.click("[data-add-traveller-submit]")
        C.check("Save blocked: needed boxes marked", await page.locator("[data-add-traveller-overlay] .fg-missing").count() >= 2)
        C.check("each marked box has its own ⓘ", await page.locator("[data-add-traveller-overlay] .fg-missing .fg-info--missing").count() >= 2)
        btn = page.locator("[data-add-traveller-overlay] .fg-missing .fg-info--missing").first
        await btn.click()
        C.check("ⓘ on a marked box says what is needed", "Needed:" in await page.locator("[data-add-traveller-overlay] .fg-need.fg-tip--open").first.inner_text())
        await page.fill("#at-fullName", "PRIYA TESTER")
        C.check("typing removes the mark", await page.locator("[data-add-traveller-overlay] .fg-missing #at-fullName").count() == 0)
        await page.fill("#at-passportNumber", "P7654321")
        await page.click("[data-add-traveller-submit]")
        await page.wait_for_timeout(300)
        C.check("filled in: dialog saves", await page.locator("[data-add-traveller-overlay][hidden]").count() == 1)

        # ---- a greyed-out Generate answers a press ----
        await page.wait_for_selector("[data-action='generate-authorization'][data-group='company']")
        C.check("Generate greyed out while the consulate country is empty", await page.is_disabled("[data-action='generate-authorization'][data-group='company']"))
        await page.click("[data-action='generate-authorization'][data-group='company']", force=True)
        await page.wait_for_timeout(400)
        marked = await page.locator("[data-view='company-authorization'] .fg-missing").count()
        toast = await page.locator(".toast, [data-toast], .toast-item").all_inner_texts()
        C.check("pressing it marks the empty needed field or says why", marked >= 1 or any(t.strip() for t in toast), f"{marked} {toast}")
        if SHOTS:
            await page.screenshot(path=os.path.join(SHOTS, "fg_company.png"), full_page=True)

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
