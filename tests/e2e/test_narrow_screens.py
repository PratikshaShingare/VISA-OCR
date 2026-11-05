"""
Very small and small phones (250 - 414px):

  * the phone menu is readable: every link has text that differs from the panel it sits on
    (a white panel with white links once hid everything except the current page), in light
    and dark theme;
  * at 250 / 280px (folding phones closed) the dashboard cards are one per row, so words are
    never cut in the middle; from 300px the compact two-column grid is kept;
  * on every main page nothing is wider than the screen (fields, buttons, grids) at
    250 / 280 / 320 / 360 / 414px;
  * no console errors.
"""
import asyncio
import os
import sys

from playwright.async_api import async_playwright

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from _common import BASE, Checks, fresh_load_and_login  # noqa: E402

checks = Checks()
VIEWS = ["dashboard", "upload-passport", "hotel-blocking", "cover-letter", "company-authorization", "passport-authorization",
         "checklist-letter", "invitation-letter", "applications", "passport-applications", "hotel-blockings", "profile", "admin"]

LUMA = """(c) => { var m=c.match(/[\\d.]+/g).map(Number); return 0.2126*m[0]+0.7152*m[1]+0.0722*m[2]; }"""

OVERFLOW_JS = """() => { var de=document.documentElement; var off=[];
  document.querySelectorAll('.view.is-active *').forEach(function(e){
    var r=e.getBoundingClientRect();
    if (r.width>0 && r.right>de.clientWidth+1 && getComputedStyle(e).position!=='fixed') {
      var p=e.parentElement, clipped=false;
      while (p && p!==document.body) { var cs=getComputedStyle(p);
        if (/(auto|scroll|hidden)/.test(cs.overflowX) && p.getBoundingClientRect().right<=de.clientWidth+1) { clipped=true; break; } p=p.parentElement; }
      if (!clipped) off.push((e.className||e.tagName).toString().slice(0,40));
    } });
  return { page: de.scrollWidth-de.clientWidth, off: off.slice(0,3) }; }"""


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        errors = []
        for width in (250, 280, 320, 360, 414):
            page = await (await browser.new_context(viewport={"width": width, "height": 700})).new_page()
            page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
            page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
            await fresh_load_and_login(page, base=BASE)
            await page.evaluate("(function(){var a=KhannaState.createApplication('x');KhannaState.setActiveApplicationId(a.id);location.hash='#/dashboard';})()")
            await page.wait_for_timeout(600)

            cols = await page.evaluate("getComputedStyle(document.querySelector('[data-dashboard-doc-grid]')).gridTemplateColumns.split(' ').length")
            want = 1 if width < 300 else 2
            checks.check(f"{width}px: dashboard cards in {want} column(s)", cols == want, str(cols))

            for theme in ("light", "dark"):
                await page.evaluate(f"document.documentElement.setAttribute('data-theme','{theme}')")
                await page.click("[data-nav-toggle]")
                await page.wait_for_timeout(500)
                res = await page.evaluate("""(luma) => { var f = eval(luma); var panel = document.querySelector('.mobile-nav__panel'); var bg = f(getComputedStyle(panel).backgroundColor);
                    var links=[...panel.querySelectorAll('.primary-nav__link')].filter(e=>e.offsetParent && !e.classList.contains('is-active'));
                    var bad=links.filter(e=>Math.abs(f(getComputedStyle(e).color)-bg)<60).map(e=>e.textContent.trim());
                    return { n: links.length, bad: bad } }""", LUMA)
                checks.check(f"{width}px {theme}: phone menu shows {res['n']} readable links (none white-on-white)", res["n"] >= 7 and not res["bad"], str(res))
                await page.click("[data-mobile-nav-close]")
                await page.wait_for_timeout(400)
            await page.evaluate("document.documentElement.removeAttribute('data-theme')")

            bad = []
            for v in VIEWS:
                await page.evaluate(f"location.hash='#/{v}'")
                await page.wait_for_timeout(400)
                o = await page.evaluate(OVERFLOW_JS)
                if o["page"] > 0 or o["off"]:
                    bad.append((v, o))
            checks.check(f"{width}px: nothing wider than the screen on {len(VIEWS)} pages", not bad, str(bad)[:300])
            await page.close()
        checks.check("no console errors", not errors, "; ".join(errors[:3]))
        await browser.close()
    checks.report_and_exit()


asyncio.run(main())
