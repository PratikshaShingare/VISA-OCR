"""
Applications page — same row look as Recent Hotel Blockings / Recent Cover Letters.

Covers:
  - Rows are the Dashboard's Recent Applications rows (blue eye opens the document
    preview, red bin deletes).
  - Delete asks first (popup): Cancel keeps the application, confirming removes it.
  - No status dropdown (application status was removed from the product).
  - No horizontal overflow at 320px / 390px / 1280px.
  - Application status is gone: no badge on the 'Working on' bar, Admin overview shows only the total,
    Admin table has no Status column, Excel export has no Status column/sheet (backend test).
  - Profile & Settings title lines up with every other page's title (left edge).
"""

import asyncio

from playwright.async_api import async_playwright

from _common import ADMIN_EMAIL, ADMIN_PASSWORD, Checks, fresh_load_and_login

checks = Checks()

SEED = """(() => {
  const S = window.KhannaState;
  ["ANITA SHARMA", "RAJESH KUMAR"].forEach(function (name) {
    const a = S.createApplication("test");
    S.updateApplication(a.id, { applicant: { fullName: name } });
  });
})()"""


async def overflow(page):
    return await page.evaluate("document.documentElement.scrollWidth > document.documentElement.clientWidth")


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page(viewport={"width": 1280, "height": 800})
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        await fresh_load_and_login(page, email=ADMIN_EMAIL, password=ADMIN_PASSWORD)
        await page.evaluate(SEED)
        await page.evaluate("location.hash = '#/applications'")
        await page.wait_for_timeout(500)

        rows = page.locator("[data-applications-list] .dashboard-recent-row")
        n = await rows.count()
        checks.check("Applications page lists rows with the Dashboard's Recent Applications row look", n >= 2, str(n))
        checks.check("No old 'Open Full Application' / text Delete buttons remain",
                     await page.locator("[data-applications-list] [data-action='open-application'], [data-applications-list] [data-action='delete-application']").count() == 0)
        eye = rows.first.locator("[data-action='dashboard-view-application']")
        dele = rows.first.locator("[data-action='dashboard-delete-application']")
        checks.check("Each row has the blue eye (view) and red bin (delete) icon buttons", await eye.count() == 1 and await dele.count() == 1)
        color = await dele.evaluate("e => getComputedStyle(e).color")
        checks.check("Bin icon is red", color.startswith("rgb(") and int(color[4:].split(",")[0]) > 150, color)

        # Eye opens the same preview flow as the Dashboard (here: nothing generated yet -> last-worked page)
        await eye.click()
        await page.wait_for_timeout(500)
        hash_now = await page.evaluate("location.hash")
        checks.check("Eye opens a document preview page like the Dashboard does", hash_now.endswith("/preview"), hash_now)
        await page.evaluate("location.hash = '#/applications'")
        await page.wait_for_timeout(400)

        # Cancel keeps it
        await dele.click()
        await page.wait_for_timeout(200)
        modal = page.locator(".app-picker-overlay:not([hidden]) #dashDeleteTitle")
        checks.check("Delete opens a confirmation popup", await modal.count() == 1)
        await page.click("[data-dash-delete-cancel].btn-secondary")
        await page.wait_for_timeout(200)
        checks.check("Cancel keeps the application", await rows.count() == n)

        # Confirm deletes
        await dele.click()
        await page.click("[data-dash-delete-confirm]")
        await page.wait_for_timeout(300)
        checks.check("Confirming removes exactly one application", await rows.count() == n - 1, f"{n} -> {await rows.count()}")

        # overflow
        for w in (1280, 390, 320):
            await page.set_viewport_size({"width": w, "height": 800})
            await page.wait_for_timeout(200)
            checks.check(f"No horizontal overflow on Applications at {w}px", not await overflow(page))

        # Title alignment
        await page.set_viewport_size({"width": 1280, "height": 800})
        xs = {}
        for v in ("hotel-blockings", "applications", "profile"):
            await page.evaluate(f"location.hash = '#/{v}'")
            await page.wait_for_timeout(300)
            xs[v] = await page.evaluate(f"document.querySelector(\"[data-view='{v}'] h1\").getBoundingClientRect().left")
        checks.check("Profile & Settings title lines up with other pages", abs(xs["profile"] - xs["hotel-blockings"]) < 1, str(xs))

        # status removed elsewhere
        await page.evaluate("location.hash = '#/hotel-blocking'")
        await page.wait_for_timeout(400)
        checks.check("'Working on' bar has no status badge", await page.locator("[data-view='hotel-blocking'] .doc-page-app-bar .badge").count() == 0)
        await page.evaluate("location.hash = '#/admin'")
        await page.wait_for_timeout(500)
        cards = await page.locator("[data-admin-overview] .stat-card").count()
        checks.check("Admin overview shows only the total card", cards == 1, str(cards))
        admin_rows = await page.locator("[data-admin-applications-table] .dashboard-recent-row").count()
        checks.check("Admin 'All Applications' uses the same rows as the Dashboard and matches the overview total",
                     admin_rows >= 1 and str(admin_rows) == (await page.locator("[data-admin-overview] .stat-card__value").inner_text()).strip(), str(admin_rows))
        checks.check("Admin list has no status dropdowns", await page.locator("[data-admin-applications-table] .status-select").count() == 0)

        checks.check("No page errors", not errors, str(errors[:2]))
        await browser.close()


asyncio.run(main())
checks.report_and_exit()
