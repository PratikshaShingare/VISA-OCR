"""
Regression: "Add hotel Manually" added several hotels per click.

Cause: every page wires its click handlers on a root element that lives for
the whole session, and re-mounting the page (switching application, or going
from "no application" to one) attached a second full set of handlers on top
of the first. Fixed once in js/core/utils.js (`on` replaces an earlier
identical delegated listener).

Covers: after the page has been re-mounted several times, ONE click adds
exactly ONE hotel (Hotel Blocking), and the same for adding a traveller,
plus: no JS errors.
"""

import asyncio

from playwright.async_api import async_playwright

from _common import BASE, Checks, ensure_fixtures, fresh_load_and_login

checks = Checks()


async def hotel_count(page, app_id):
    return await page.evaluate(f"KhannaState.getApplication('{app_id}').hotels.length")


async def main():
    ensure_fixtures()
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page(viewport={"width": 1280, "height": 900})
        errors = []
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
        await fresh_load_and_login(page, base=BASE)

        ids = await page.evaluate(
            "(function(){var S=KhannaState;var a=S.createApplication('x');var b=S.createApplication('x');S.setActiveApplicationId(a.id);return {a:a.id,b:b.id};})()"
        )
        await page.evaluate("location.hash = '#/hotel-blocking'")
        await page.wait_for_timeout(500)

        # Re-mount the page several times the ways a real user does:
        # switch application back and forth, and drop to "no application".
        for _ in range(3):
            await page.evaluate(f"KhannaState.setActiveApplicationId('{ids['b']}')")
            await page.evaluate("document.dispatchEvent(new CustomEvent('khanna:navigate',{detail:{view:'hotel-blocking',step:null}}))")
            await page.wait_for_timeout(200)
            await page.evaluate(f"KhannaState.setActiveApplicationId('{ids['a']}')")
            await page.evaluate("document.dispatchEvent(new CustomEvent('khanna:navigate',{detail:{view:'hotel-blocking',step:null}}))")
            await page.wait_for_timeout(200)
        await page.evaluate("KhannaState.setActiveApplicationId(null)")
        await page.evaluate("document.dispatchEvent(new CustomEvent('khanna:navigate',{detail:{view:'hotel-blocking',step:null}}))")
        await page.wait_for_timeout(200)
        await page.evaluate(f"KhannaState.setActiveApplicationId('{ids['a']}')")
        await page.evaluate("document.dispatchEvent(new CustomEvent('khanna:navigate',{detail:{view:'hotel-blocking',step:null}}))")
        await page.wait_for_timeout(400)

        before = await hotel_count(page, ids["a"])
        await page.click("[data-action='add-hotel']")
        await page.wait_for_timeout(400)
        after = await hotel_count(page, ids["a"])
        checks.check("one click on 'Add hotel Manually' adds exactly one hotel (after several re-mounts)", after - before == 1, f"{before} -> {after}")
        shown = await page.locator("[data-hotels-list] [data-action='edit-hotel']").count()
        checks.check("...and the list shows exactly that many rows", shown == after, f"{shown} vs {after}")

        await page.click("[data-action='add-hotel']")
        await page.wait_for_timeout(300)
        checks.check("a second click adds exactly one more", await hotel_count(page, ids["a"]) == after + 1)

        # Same fix covers every page: Travellers step "Add traveller".
        await page.evaluate("location.hash = '#/new-application/2'")
        await page.wait_for_timeout(400)
        btn = page.locator("[data-action='add-traveller']")
        if await btn.count():
            t0 = await page.evaluate(f"KhannaState.getApplication('{ids['a']}').travellers.length")
            await btn.first.click()
            await page.wait_for_timeout(300)
            t1 = await page.evaluate(f"KhannaState.getApplication('{ids['a']}').travellers.length")
            checks.check("one click on 'Add traveller' adds exactly one traveller", t1 - t0 == 1, f"{t0} -> {t1}")

        real = [e for e in errors if "favicon" not in e.lower()]
        checks.check("no browser console errors", not real, "; ".join(real[:3]))
        await browser.close()
    checks.report_and_exit()


asyncio.run(main())
