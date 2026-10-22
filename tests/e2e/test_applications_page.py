"""
Applications page — same row look as Recent Hotel Blockings / Recent Cover Letters.

Covers:
  - Each row has a small secondary "Open Full Application" button and a RED
    outline "Delete" button with the trash icon + label (not an icon-only grey button).
  - Delete asks first (popup): Cancel keeps the application, confirming removes it.
  - No status dropdown (application status was removed from the product).
  - No horizontal overflow at 320px / 390px / 1280px.
  - Application status is gone: no badge on the 'Working on' bar, Admin overview shows only the total,
    Admin table has no Status column, Excel export has no Status column/sheet (backend test).
  - Profile / Settings titles line up with every other page's title (left edge).
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

        rows = page.locator("[data-applications-list] .hb-row")
        n = await rows.count()
        checks.check("Applications page lists rows with the shared .hb-row look", n >= 2, str(n))

        dele = rows.first.locator("[data-action='delete-application']")
        cls = await dele.get_attribute("class")
        txt = (await dele.inner_text()).strip()
        checks.check("Delete is a red-outline small button", "btn-danger-outline" in cls and "btn-sm" in cls, cls)
        checks.check("Delete button shows the word Delete (not icon-only)", txt == "Delete", txt)
        color = await dele.evaluate("e => getComputedStyle(e).color")
        checks.check("Delete text is red", color.startswith("rgb(") and int(color[4:].split(",")[0]) > 150, color)
        opn = rows.first.locator("[data-action='open-application']")
        checks.check("Open Full Application is a small secondary button", "btn-sm" in (await opn.get_attribute("class")))

        # Cancel keeps it
        await dele.click()
        await page.wait_for_timeout(200)
        modal = page.locator("[data-app-delete-modal]")
        checks.check("Delete opens a confirmation popup", not await modal.evaluate("e => e.hidden"))
        await page.click("[data-app-delete-cancel].btn-secondary")
        await page.wait_for_timeout(200)
        checks.check("Cancel keeps the application", await rows.count() == n)

        # Confirm deletes
        await dele.click()
        await page.click("[data-app-delete-confirm]")
        await page.wait_for_timeout(300)
        checks.check("Confirming removes exactly one application", await rows.count() == n - 1, f"{n} -> {await rows.count()}")

        checks.check("No status dropdown or badge on the Applications rows", await rows.first.locator("[data-action='change-status'], .status-select, .badge").count() == 0)

        # overflow
        for w in (1280, 390, 320):
            await page.set_viewport_size({"width": w, "height": 800})
            await page.wait_for_timeout(200)
            checks.check(f"No horizontal overflow on Applications at {w}px", not await overflow(page))

        # Title alignment
        await page.set_viewport_size({"width": 1280, "height": 800})
        xs = {}
        for v in ("hotel-blockings", "applications", "settings", "profile"):
            await page.evaluate(f"location.hash = '#/{v}'")
            await page.wait_for_timeout(300)
            xs[v] = await page.evaluate(f"document.querySelector(\"[data-view='{v}'] h1\").getBoundingClientRect().left")
        checks.check("Settings/Profile titles line up with other pages", abs(xs["settings"] - xs["hotel-blockings"]) < 1 and abs(xs["profile"] - xs["hotel-blockings"]) < 1, str(xs))

        # status removed elsewhere
        await page.evaluate("location.hash = '#/hotel-blocking'")
        await page.wait_for_timeout(400)
        checks.check("'Working on' bar has no status badge", await page.locator("[data-view='hotel-blocking'] .doc-page-app-bar .badge").count() == 0)
        await page.evaluate("location.hash = '#/admin'")
        await page.wait_for_timeout(500)
        cards = await page.locator("[data-admin-overview] .stat-card").count()
        checks.check("Admin overview shows only the total card", cards == 1, str(cards))
        heads = await page.locator("[data-admin-applications-table] thead th").all_inner_texts()
        checks.check("Admin applications table has no Status column", "Status" not in [h.strip() for h in heads] and len(heads) == 5, str(heads))
        checks.check("Admin table has no status dropdowns", await page.locator("[data-admin-applications-table] .status-select").count() == 0)

        checks.check("No page errors", not errors, str(errors[:2]))
        await browser.close()


asyncio.run(main())
checks.report_and_exit()
