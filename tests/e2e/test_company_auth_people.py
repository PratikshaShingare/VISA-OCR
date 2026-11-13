"""
End-to-end: Company Authorization Letter — "Who is authorising" list.

Each person has a ×: someone from the application is taken off this letter's
list (unticked, still on the application; "Show again" brings them back), a
manually-added applicant is deleted. "Tick all" / "Untick all" and the
"N of M ticked" line. All data is invented (project rule 11).
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
  S.updateApplication(app.id, {
    applicant: { salutation: 'Mr', fullName: 'MANDAR TESTER', firstName: 'MANDAR', lastName: 'TESTER', passport: { current: { number: 'M1234567' } } },
    travellers: [{ id: 'T1', fullName: 'PRIYA TESTER', firstName: 'PRIYA', lastName: 'TESTER', relation: 'Spouse', passport: { current: { number: 'P7654321' } } }],
    authorization: { company: { selectedPersonIds: ['applicant', 'T1'] } }
  });
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
        await page.evaluate("location.hash = '#/company-authorization'")
        await page.wait_for_selector("[data-action='hide-company-person']", timeout=15000)

        C.check("every person row has a ×", await page.locator("[data-action='hide-company-person']").count() == 2)
        C.check("'2 of 2 ticked'", "2 of 2" in await page.inner_text(".auth-select-bar"))
        if SHOTS:
            await page.locator("[data-company-auth-card]").screenshot(path=os.path.join(SHOTS, "company_auth_people.png"))

        await page.click("[data-action='hide-company-person'][data-person-id='T1']")
        app = await page.evaluate("(id) => window.KhannaState.getApplication(id)", app_id)
        C.check("× takes the person off this letter", app["authorization"]["company"]["selectedPersonIds"] == ["applicant"])
        C.check("…but keeps them on the application", len(app["travellers"]) == 1)
        C.check("row gone, 'Show again' offered", await page.locator("[data-person-id='T1'][data-auth-person]").count() == 0
                and "1 person removed from this letter" in await page.inner_text("[data-auth-checklist='company']"))
        await page.click("[data-action='show-company-people']")
        C.check("Show again lists them (unticked)", await page.locator("[data-person-id='T1'][data-auth-person]").count() == 1
                and not await page.is_checked("[data-person-id='T1'][data-auth-person]"))

        hint = await page.inner_text("[data-auth-readiness='company']")
        C.check("notice says exactly what is missing", "To generate this letter:" in hint and "choose the consulate country" in hint and "tick at least one" not in hint, hint)
        await page.click("[data-action='company-untick-all']")
        await page.wait_for_timeout(150)
        hint = await page.inner_text("[data-auth-readiness='company']")
        C.check("…and asks to tick someone when nobody is ticked", "tick at least one person" in hint, hint)
        await page.click("[data-action='company-tick-all']")
        C.check("Tick all", "2 of 2" in await page.inner_text(".auth-select-bar"))
        await page.click("[data-action='company-untick-all']")
        C.check("Untick all", "0 of 2" in await page.inner_text(".auth-select-bar"))

        await page.fill("[data-manual-applicant-field='fullName']", "RAVI SAMPLE")
        await page.fill("[data-manual-applicant-field='passportNumber']", "R1111111")
        await page.click("[data-action='add-manual-applicant']")
        C.check("manually added person listed with a ×", await page.locator("[data-action='remove-manual-applicant']").count() == 1)
        await page.click("[data-action='remove-manual-applicant']")
        C.check("× deletes the manually added person", await page.locator("[data-action='remove-manual-applicant']").count() == 0)
        C.check("groups explained, 'Delete group' is words not a bare ×", await page.locator("text=Saved groups").count() >= 1
                and await page.locator("text=Save ticked people as group").count() == 1)

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
