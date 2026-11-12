"""
End-to-end: details typed on a letter page are also saved to Applicant Profiles.

Company Authorization Letter: the main applicant has no passport number, the
"Complete details" button opens the details form, staff type the missing
number — with "Also save these details in Applicant Profiles" ticked (the
default) the profile gets it; unticked, the profile is left alone. The
"name & passport only" row has the same option. All data is invented
(project rule 11).
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from playwright.async_api import async_playwright  # noqa: E402

from _common import Checks, fresh_load_and_login  # noqa: E402

C = Checks()

SEED = """() => {
  const S = window.KhannaState;
  const app = S.createApplication('e2e');
  S.updateApplication(app.id, {
    applicant: { fullName: 'RAVI KUMAR TESTER', firstName: 'RAVI KUMAR', lastName: 'TESTER', dob: '1985-02-03',
                 passport: { current: { number: '', issueDate: '2021-04-05' } } },
    authorization: { company: { selectedPersonIds: ['applicant'] } }
  });
  S.setActiveApplicationId(app.id);
  return app.id;
}"""

PROFILE = """(no) => {
  const all = window.KhannaState.getApplicantProfiles().concat(window.KhannaState.getTravellerProfiles());
  const p = all.find(x => ((x.passport || {}).current || {}).number === no);
  return p ? { name: p.fullName, issue: p.passport.current.issueDate || '', phone: (p.contact || {}).phone || '' } : null;
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
        await page.wait_for_selector("[data-complete-details]", timeout=15000)
        C.check("missing passport number listed with 'Complete details'", await page.locator("[data-missing-details]").count() >= 1)

        await page.click("[data-complete-details]")
        await page.wait_for_selector("[data-add-traveller-overlay]:not([hidden])")
        box = page.locator("[data-add-traveller-save-profile]")
        C.check("'Also save in Applicant Profiles' shown and ticked", await box.is_visible() and await box.is_checked())
        await page.fill("#at-passportNumber", "T7654321")
        await page.fill("#at-phone", "98111 22222")
        await page.click("[data-add-traveller-submit]")
        await page.wait_for_selector("[data-add-traveller-overlay][hidden]", state="attached")
        prof = await page.evaluate(PROFILE, "T7654321")
        C.check("profile saved with the typed passport number", prof is not None and prof["name"] == "RAVI KUMAR TESTER", str(prof))
        C.check("profile keeps the other details", prof is not None and prof["issue"] == "2021-04-05" and prof["phone"] == "98111 22222", str(prof))
        linked = await page.evaluate("(id) => window.KhannaState.getApplication(id).applicantId", app_id)
        C.check("application linked to that profile", bool(linked))
        C.check("confirmation shown", await page.locator("text=saved to Applicant Profiles").count() >= 1)
        C.check("warning gone once the number is filled", await page.locator("[data-missing-details]").count() == 0)
        count_before = await page.evaluate("window.KhannaState.getApplicantProfiles().length")

        # Opening again and unticking: the application changes, the profile does not.
        await page.evaluate("""(id) => window.KhannaAddTraveller.open(null, { docKey: 'companyAuth', personId: 'applicant' })""", app_id)
        await page.wait_for_selector("[data-add-traveller-overlay]:not([hidden])")
        C.check("box ticked again on reopening", await page.is_checked("[data-add-traveller-save-profile]"))
        await page.uncheck("[data-add-traveller-save-profile]")
        await page.fill("#at-phone", "98000 99999")
        await page.click("[data-add-traveller-submit]")
        prof = await page.evaluate(PROFILE, "T7654321")
        app_phone = await page.evaluate("(id) => window.KhannaState.getApplication(id).applicant.contact.phone", app_id)
        C.check("unticked: application updated", app_phone == "98000 99999", app_phone)
        C.check("unticked: profile unchanged", prof is not None and prof["phone"] == "98111 22222", str(prof))

        # "Name & passport only" row.
        C.check("quick row has the save option, ticked", await page.is_checked("[data-manual-applicant-save-profile]"))
        await page.fill("[data-manual-applicant-field='fullName']", "MEERA SAMPLE")
        await page.fill("[data-manual-applicant-field='passportNumber']", "s1112223")
        await page.click("[data-action='add-manual-applicant']")
        prof = await page.evaluate(PROFILE, "S1112223")
        C.check("quick row: saved to Applicant Profiles", prof is not None and prof["name"] == "MEERA SAMPLE", str(prof))
        C.check("one new profile, no duplicates", await page.evaluate("window.KhannaState.getApplicantProfiles().length") == count_before + 1)

        await page.evaluate("location.hash = '#/applicant-profiles'")
        await page.wait_for_timeout(500)
        body = await page.inner_text("body")
        C.check("both people listed on Applicant Profiles", "RAVI KUMAR TESTER" in body.upper() and "MEERA SAMPLE" in body.upper())

        await page.evaluate("location.hash = '#/company-authorization'")
        await page.wait_for_selector("[data-manual-applicant-save-profile]")
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
