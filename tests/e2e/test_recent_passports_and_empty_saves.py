"""
Recent Passports page + the "no empty applications" rules.

  * Upload Passport has a "Recent Passports" button that opens the list.
  * A saved passport appears with Edit / Delete; Delete asks first.
  * Unnamed applications are not listed on the Dashboard or Applications page
    and blank drafts are removed.
  * Save buttons refuse to save an application with no name.

Real static server + backend. All names synthetic.
"""
import asyncio

from playwright.async_api import async_playwright

from _common import BASE, Checks, fresh_load_and_login, future_date

checks = Checks()

SEED = """
(function () {
  var S = KhannaState;
  var blank = S.createApplication('x');
  var a = S.createApplication('x');
  S.updateApplication(a.id, { applicant: { fullName: 'ANITA SHARMA', firstName: 'ANITA', lastName: 'SHARMA', nationality: 'IND',
    passport: { verificationStatus: 'OCR Extracted — Please Verify', current: { number: 'Z1234567', expiryDate: '2033-06-15' } } } });
  S.setActiveApplicationId(a.id);
  return { appId: a.id, blankId: blank.id, count: S.getApplications().length, blankKept: !!S.getApplication(blank.id) };
})()
"""


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        context = await browser.new_context(viewport={"width": 1280, "height": 900})
        page = await context.new_page()
        errors = []
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
        await fresh_load_and_login(page, base=BASE)
        seeded = await page.evaluate(SEED)
        checks.check("a blank draft exists before reload", seeded["blankKept"] is True and seeded["count"] == 2, str(seeded))
        await page.reload()
        await page.wait_for_timeout(800)
        left = await page.evaluate("KhannaState.getApplications().length")
        checks.check("blank drafts are removed on the next load", left == 1, str(left))

        # ---- Recent Passports button + list
        await page.evaluate("location.hash = '#/upload-passport'")
        await page.wait_for_timeout(600)
        btn = page.locator("[data-recent-passports-link]")
        checks.check("Upload Passport shows a Recent Passports button", await btn.is_visible())
        await btn.click()
        await page.wait_for_timeout(500)
        checks.check("button opens the Recent Passports page", "passport-applications" in page.url)
        rows = page.locator("[data-pp-row]")
        checks.check("the saved passport is listed once", await rows.count() == 1)
        txt = await rows.first.inner_text()
        checks.check("row shows name, passport number and status", "ANITA SHARMA" in txt and "Z1234567" in txt and "Please Verify" in txt, txt)

        # ---- Edit opens Upload Passport with the saved details
        await page.locator("[data-action='pp-edit']").first.click()
        await page.wait_for_timeout(700)
        checks.check("Edit returns to Upload Passport", "upload-passport" in page.url)
        number = await page.input_value("[data-field='current.number']")
        checks.check("saved passport number is loaded", number == "Z1234567", number)

        # ---- Save refuses an empty form
        await page.fill("[data-field='current.number']", "")
        await page.locator("[data-passport-save]").click()
        status = (await page.locator("[data-passport-status]").inner_text()).strip()
        checks.check("saving without a passport number is refused", "passport number" in status.lower(), status)

        # ---- Dashboard hides unnamed applications
        await page.evaluate("""(function(){ var a = KhannaState.createApplication('x'); KhannaState.updateApplication(a.id, { travel: { destination: 'Japan' } }); })()""")
        await page.evaluate("location.hash = '#/dashboard'")
        await page.wait_for_timeout(600)
        dash = await page.inner_text("[data-dashboard-recent]")
        checks.check("Dashboard lists the named application", "ANITA SHARMA" in dash)
        checks.check("Dashboard does not list an unnamed application", "Untitled applicant" not in dash, dash)
        await page.evaluate("location.hash = '#/applications'")
        await page.wait_for_timeout(500)
        apps_text = await page.inner_text("[data-applications-list]")
        checks.check("Applications page does not list an unnamed application", "Untitled applicant" not in apps_text, apps_text)

        # ---- Save buttons refuse an unnamed active application
        await page.evaluate("location.hash = '#/cover-letter'")
        await page.wait_for_timeout(600)
        # give the (still unnamed) application something on the cover letter page so the
        # NAME check, not the "nothing filled in" check, is what refuses the save
        await page.evaluate("(d) => KhannaState.updateApplication(KhannaState.getActiveApplication().id, { coverLetter: { travelStartDate: d } }, null)", future_date(30))
        await page.wait_for_timeout(300)
        await page.locator(".view.is-active [data-action='save-doc-application']").first.click()
        await page.wait_for_timeout(300)
        shown = await page.locator(".toast", has_text="applicant's name").count()
        checks.check("document-page Save refuses an unnamed application", shown >= 1)
        saved = await page.evaluate("!!KhannaState.getActiveApplication().explicitlySavedAt")
        checks.check("unnamed application was not marked saved", saved is False)

        # ---- Delete asks first, then removes
        await page.evaluate("location.hash = '#/passport-applications'")
        await page.wait_for_timeout(500)
        await page.locator("[data-action='pp-delete']").first.click()
        modal = page.locator("[data-pp-delete-modal]")
        checks.check("Delete opens a confirmation first", await modal.is_visible())
        checks.check("passport is still listed before confirming", await page.locator("[data-pp-row]").count() == 1)
        await modal.locator("[data-pp-delete-confirm]").click()
        await page.wait_for_timeout(400)
        checks.check("confirming removes the passport", await page.locator("[data-pp-row]").count() == 0)
        checks.check("empty list shows an empty state", "No passports saved yet" in await page.inner_text("[data-passport-applications-root]"))

        # ---- 320px: no horizontal overflow
        await page.set_viewport_size({"width": 320, "height": 700})
        await page.wait_for_timeout(300)
        overflow = await page.evaluate("document.documentElement.scrollWidth > document.documentElement.clientWidth")
        checks.check("no horizontal overflow at 320px", overflow is False)

        checks.check("no console errors", not errors, "; ".join(errors[:4]))
        await browser.close()
    checks.report_and_exit()


asyncio.run(main())
