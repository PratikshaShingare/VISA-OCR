"""
Dashboard UI/UX pass — end-to-end checks (desktop 1366/1440, mobile
320/360/375/390/414). Covers: removed "Generate a Document" block, footer
(no Dashboard link, compact), drawer top spacing, Total Applications accent,
the 8-card grid, Recent Applications View/Delete (with confirm),
no horizontal overflow, and the mobile drawer auto-closing on every item.
"""

import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from playwright.async_api import async_playwright
from _common import BASE, Checks, fresh_load_and_login

checks = Checks()

SEED = """() => {
  var names = ["Asha Verma", "Rohit Khanna", "Meera Iyer", "Kabir Singh", "Zoya Ali"];
  names.forEach(function (n) {
    var app = KhannaState.createApplication("customercare@khannatravels.com");
    KhannaState.updateApplication(app.id, { applicant: Object.assign({}, app.applicant, { fullName: n }) }, "seed");
  });
}"""

METRICS = """() => {
  var de = document.documentElement;
  var grid = document.querySelector('[data-dashboard-doc-grid]');
  var cards = Array.prototype.slice.call(grid.children);
  var rects = cards.map(function (c) { var r = c.getBoundingClientRect(); return {l: r.left, t: r.top, w: r.width, h: r.height, r: r.right}; });
  var firstTop = rects[0].t;
  var cols = rects.filter(function (r) { return Math.abs(r.t - firstTop) < 2; }).length;
  var clipped = cards.some(function (c) { return c.scrollWidth > c.clientWidth + 1; });
  var view = document.querySelector('[data-view=dashboard]');
  return {
    sw: de.scrollWidth, cw: de.clientWidth,
    n: cards.length, cols: cols, clipped: clipped,
    maxRight: Math.max.apply(null, rects.map(function (r) { return r.r; })),
    minLeft: Math.min.apply(null, rects.map(function (r) { return r.l; })),
    main: document.querySelector('.app-main').getBoundingClientRect().width,
    h1w: view.querySelector('h1').getBoundingClientRect().width,
    heights: rects.map(function (r) { return Math.round(r.h); }),
  };
}"""


async def mobile_pass(browser, w):
    page = await browser.new_page(viewport={"width": w, "height": 800})
    errors = []
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    page.on("pageerror", lambda e: errors.append(str(e)))
    await fresh_load_and_login(page, base=BASE)
    await page.evaluate(SEED)
    await page.evaluate("location.hash = '#/dashboard'")
    await page.wait_for_timeout(300)

    m = await page.evaluate(METRICS)
    checks.check(f"[{w}] no horizontal overflow (closed menu)", m["sw"] <= m["cw"], str(m))
    checks.check(f"[{w}] 8 cards (stat + 7 documents), 2 columns", m["n"] == 8 and m["cols"] == 2, str(m))
    checks.check(f"[{w}] cards inside viewport, none clipped", m["minLeft"] >= 0 and m["maxRight"] <= m["cw"] and not m["clipped"], str(m))
    checks.check(f"[{w}] content uses full width (main = viewport)", m["main"] >= m["cw"] - 2, str(m))
    ib = await page.evaluate("""() => Array.prototype.slice.call(document.querySelectorAll('.dashboard-icon-btn')).map(function (b) {
      var r = b.getBoundingClientRect(); var row = b.closest('.dashboard-recent-row').getBoundingClientRect();
      return { w: Math.round(r.width), h: Math.round(r.height), inRow: r.right <= row.right + 0.5 && r.left >= row.left } })""")
    checks.check(f"[{w}] icon buttons are >= 40px touch targets and stay inside their row",
                 len(ib) == 8 and all(b["w"] >= 40 and b["h"] >= 40 and b["inRow"] for b in ib), str(ib[:2]))
    sc = await page.evaluate("""() => { var c = document.querySelector('.dashboard-stat-card'); var r = c.getBoundingClientRect();
      return { clipped: c.scrollWidth > c.clientWidth + 1, h: Math.round(r.height) } }""")
    checks.check(f"[{w}] stat card text fits its cell", not sc["clipped"], str(sc))
    mb = await page.evaluate("""() => { function shown(sel) { var e = document.querySelector(sel); return !!e && e.offsetParent !== null }
      var v = parseFloat(getComputedStyle(document.querySelector('.dashboard-stat-card .stat-card__value')).fontSize);
      var l = parseFloat(getComputedStyle(document.querySelector('.dashboard-stat-card .stat-card__label')).fontSize);
      var name = document.querySelector('.dashboard-recent-row__name').textContent;
      return { logo: shown('.brand__logo'), text: shown('.brand__text'), plus: shown('[data-new-app-menu-toggle]'), prof: shown('[data-profile-toggle]'), nav: shown('[data-nav-toggle]'),
               theme: shown('.header-actions > .btn-icon.theme-toggle'), v: v, l: l, name: name } }""")
    checks.check(f"[{w}] phone header: only logo, '+', profile icon and menu button (no company name text)",
                 mb["logo"] and not mb["text"] and mb["plus"] and mb["prof"] and mb["nav"] and not mb["theme"], str(mb))
    checks.check(f"[{w}] Total Applications number is small (<= 16px)", mb["v"] <= 16, str(mb))
    checks.check(f"[{w}] recent applications show applicant names, not 'Untitled applicant'", "Untitled" not in mb["name"], mb["name"])
    checks.check(f"[{w}] heading has a normal line length", m["h1w"] >= m["cw"] - 40, str(m))

    # Open the menu: it must overlay, not squeeze main.
    await page.click("[data-nav-toggle]")
    await page.wait_for_timeout(350)
    open_state = await page.evaluate("""() => ({
      open: document.querySelector('[data-mobile-nav]').classList.contains('is-open'),
      main: document.querySelector('.app-main').getBoundingClientRect().width,
      panel: document.querySelector('.mobile-nav__panel').getBoundingClientRect().width,
      sw: document.documentElement.scrollWidth, cw: document.documentElement.clientWidth})""")
    checks.check(f"[{w}] menu opens as an overlay (main keeps full width)", open_state["open"] and open_state["main"] >= open_state["cw"] - 2, str(open_state))
    checks.check(f"[{w}] no horizontal overflow (open menu)", open_state["sw"] <= open_state["cw"], str(open_state))
    checks.check(f"[{w}] drawer panel leaves backdrop visible", open_state["panel"] < open_state["cw"], str(open_state))

    # Every visible drawer item must close the drawer after navigating.
    hrefs = await page.evaluate("""() => Array.prototype.slice.call(document.querySelectorAll('[data-mobile-nav] [data-nav-link]'))
        .filter(function (a) { return a.offsetParent !== null; }).map(function (a) { return a.getAttribute('data-nav-link'); })""")
    expected = {"dashboard", "hotel-blocking", "cover-letter", "company-authorization", "passport-authorization",
                "checklist-letter", "invitation-letter", "upload-passport", "profile", "settings"}
    checks.check(f"[{w}] drawer lists all expected items", expected.issubset(set(hrefs)), str(hrefs))
    for nav in hrefs:
        if not await page.evaluate("document.querySelector('[data-mobile-nav]').classList.contains('is-open')"):
            await page.click("[data-nav-toggle]")
            await page.wait_for_timeout(300)
        await page.click(f"[data-mobile-nav] [data-nav-link='{nav}']")
        await page.wait_for_timeout(300)
        closed = not await page.evaluate("document.querySelector('[data-mobile-nav]').classList.contains('is-open')")
        routed = await page.evaluate(f"location.hash.indexOf('/{nav}') !== -1")
        checks.check(f"[{w}] '{nav}' navigates and closes the drawer", closed and routed)

    # Backdrop closes it too.
    await page.evaluate("location.hash = '#/dashboard'")
    await page.click("[data-nav-toggle]")
    await page.wait_for_timeout(300)
    await page.mouse.click(w - 4, 400)
    await page.wait_for_timeout(300)
    checks.check(f"[{w}] backdrop tap closes the drawer", not await page.evaluate("document.querySelector('[data-mobile-nav]').classList.contains('is-open')"))

    # Footer.
    foot = await page.evaluate("""() => { var f = document.querySelector('.app-footer');
      return { h: f.getBoundingClientRect().height, dash: !!f.querySelector('[data-nav-link=dashboard]'),
               apps: !!f.querySelector('[data-nav-link=applications]'), copy: f.textContent.indexOf('Khanna Travels') !== -1,
               sw: f.scrollWidth, cw: f.clientWidth } }""")
    checks.check(f"[{w}] footer: no Dashboard link, Applications + copyright kept", (not foot["dash"]) and foot["apps"] and foot["copy"], str(foot))
    checks.check(f"[{w}] footer fits the viewport", foot["sw"] <= foot["cw"], str(foot))

    # Log Out closes the drawer too (do it last — it ends the session).
    await page.click("[data-nav-toggle]")
    await page.wait_for_timeout(300)
    await page.click("[data-mobile-nav] [data-auth-logged-in] [data-action='logout']")
    await page.wait_for_timeout(400)
    checks.check(f"[{w}] 'Log Out' closes the drawer", not await page.evaluate("document.querySelector('[data-mobile-nav]').classList.contains('is-open')"))

    checks.check(f"[{w}] zero console errors", len(errors) == 0, "\n".join(errors))
    await page.close()


async def desktop_pass(browser, w):
    page = await browser.new_page(viewport={"width": w, "height": 900})
    errors = []
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    page.on("pageerror", lambda e: errors.append(str(e)))
    await fresh_load_and_login(page, base=BASE)
    await page.evaluate(SEED)
    await page.evaluate("location.hash = '#/dashboard'")
    await page.wait_for_timeout(300)

    text = await page.inner_text("[data-view=dashboard]")
    checks.check(f"[{w}] 'Generate a Document' heading/subtitle removed",
                 "Generate a Document" not in text and "Jump straight to one document type" not in text)
    checks.check(f"[{w}] header reads Dashboard with no extra subtitle",
                 "Dashboard" in text and "An overview of your visa applications will appear here." not in text)

    m = await page.evaluate(METRICS)
    checks.check(f"[{w}] no horizontal overflow", m["sw"] <= m["cw"], str(m))
    checks.check(f"[{w}] 8 cards in a 4-column grid (2 rows of 4)", m["n"] == 8 and m["cols"] == 4, str(m))
    checks.check(f"[{w}] all 8 cards share one height", len(set(m["heights"])) == 1, str(m["heights"]))

    order = await page.evaluate("""() => Array.prototype.slice.call(document.querySelector('[data-dashboard-doc-grid]').children).map(function (c) {
      var t = c.querySelector('strong') || c.querySelector('.stat-card__label'); return t.textContent.trim() })""")
    expected_order = ["Total Applications", "Upload Passport", "Hotel Blocking", "Cover Letter",
                      "Company Authorization Letter", "Passport Authorization Letter", "Checklist Letter", "Invitation Letter"]
    checks.check(f"[{w}] card order: row 1 and row 2 exactly as requested", order == expected_order, str(order))
    first = await page.evaluate("""() => { var c = document.querySelector('[data-dashboard-doc-grid]').children[0];
      return { stat: c.classList.contains('stat-card'), link: c.tagName === 'A', standalone: !!document.querySelector('.card-grid.dashboard-stats') } }""")
    checks.check(f"[{w}] Total Applications is the first cell of the grid, a static (non-link) card, no separate stats block",
                 first["stat"] and not first["link"] and not first["standalone"], str(first))

    colors = await page.evaluate("""() => ({
      stat: getComputedStyle(document.querySelector('.stat-card')).backgroundColor,
      card: getComputedStyle(document.querySelector('.dashboard-doc-card')).backgroundColor,
      value: document.querySelector('.stat-card__value').textContent.trim(),
      label: document.querySelector('.stat-card__label').textContent.trim() })""")
    checks.check(f"[{w}] Total Applications card has its own subtle background", colors["stat"] != colors["card"], str(colors))
    checks.check(f"[{w}] Total Applications shows the real count (5)", colors["value"] == "5" and colors["label"] == "Total Applications", str(colors))

    foot = await page.evaluate("""() => { var f = document.querySelector('.app-footer');
      return { h: f.getBoundingClientRect().height, dash: !!f.querySelector('[data-nav-link=dashboard]'),
               apps: !!f.querySelector('[data-nav-link=applications]') } }""")
    checks.check(f"[{w}] footer shorter (<= 56px) with no Dashboard link, Applications kept",
                 foot["h"] <= 56 and (not foot["dash"]) and foot["apps"], str(foot))

    # Drawer: top spacing reduced, and it stays open on desktop navigation.
    await page.click("[data-nav-toggle]")
    await page.wait_for_timeout(350)
    gap = await page.evaluate("""() => { var p = document.querySelector('.mobile-nav__panel').getBoundingClientRect();
      var a = document.querySelector('.mobile-nav__panel [data-nav-link=dashboard]').getBoundingClientRect();
      return Math.round(a.top - p.top) }""")
    checks.check(f"[{w}] drawer: Dashboard link sits higher (gap {gap}px, was ~68px)", gap <= 52, str(gap))
    await page.click("[data-mobile-nav] [data-nav-link='cover-letter']")
    await page.wait_for_timeout(300)
    checks.check(f"[{w}] desktop drawer stays open after navigation (unchanged)",
                 await page.evaluate("document.querySelector('[data-mobile-nav]').classList.contains('is-open')"))
    await page.click("[data-mobile-nav-close]")
    await page.evaluate("location.hash = '#/dashboard'")
    await page.wait_for_timeout(300)

    # Recent Applications: View / Delete.
    rows = await page.locator(".dashboard-recent-row").count()
    checks.check(f"[{w}] Recent Applications shows 4 rows", rows == 4, str(rows))
    btns = await page.evaluate("""() => Array.prototype.slice.call(document.querySelectorAll('.dashboard-recent-row')).every(function (r) {
      return !!r.querySelector("[data-action='dashboard-view-application']") && !!r.querySelector("[data-action='dashboard-delete-application']") })""")
    checks.check(f"[{w}] every row has a View and a Delete button", btns)
    meta = await page.evaluate("""() => { var m = document.querySelector('.dashboard-recent-row__meta'); var sp = m.querySelectorAll('span');
      var a = sp[0].getBoundingClientRect(), b = sp[1].getBoundingClientRect();
      return { text: m.innerText, spans: sp.length, stacked: b.top >= a.bottom - 1, row: document.querySelector('.dashboard-recent-row').innerText } }""")
    checks.check(f"[{w}] Recent Applications: 'Updated …' and the document status sit on two lines",
                 meta["spans"] == 2 and meta["stacked"] and meta["text"].startswith("Updated"), str(meta))
    checks.check(f"[{w}] Recent Applications: no APP_… number shown in the list", "APP_" not in meta["row"], meta["row"])
    ic = await page.evaluate("""() => {
      function tok(name) { var p = document.createElement('span'); p.style.color = 'var(' + name + ')'; document.body.appendChild(p);
        var c = getComputedStyle(p).color; p.remove(); return c; }
      function info(sel) { var b = document.querySelector(sel); var cs = getComputedStyle(b);
        return { text: b.textContent.trim(), svg: !!b.querySelector('svg'), label: b.getAttribute('aria-label'), title: b.getAttribute('title'),
          border: ['Top','Right','Bottom','Left'].map(function (k) { return parseFloat(cs['border' + k + 'Width']) || 0 }).reduce(function (a, x) { return a + x }, 0),
          bg: cs.backgroundColor, shadow: cs.boxShadow, color: cs.color, w: b.getBoundingClientRect().width, h: b.getBoundingClientRect().height }; }
      return { view: info(".dashboard-recent-row [data-action='dashboard-view-application']"),
               del: info(".dashboard-recent-row [data-action='dashboard-delete-application']"),
               primary: tok('--color-primary'), danger: tok('--color-danger') } }""")
    for key, tokname in (("view", "primary"), ("del", "danger")):
        b = ic[key]
        checks.check(f"[{w}] {key} button is icon-only (svg, no visible text, accessible name)", b["svg"] and b["text"] == "" and b["label"] and b["title"], str(b))
        checks.check(f"[{w}] {key} button has no border/box (0 border, transparent bg, no shadow)",
                     b["border"] == 0 and b["bg"] in ("rgba(0, 0, 0, 0)", "transparent") and b["shadow"] == "none", str(b))
    checks.check(f"[{w}] eye (View) icon is blue (--color-primary)", ic["view"]["color"] == ic["primary"], str((ic["view"]["color"], ic["primary"])))
    checks.check(f"[{w}] bin (Delete) icon is red (--color-danger)", ic["del"]["color"] == ic["danger"], str((ic["del"]["color"], ic["danger"])))

    if w == 1366:
        first_id = await page.locator(".dashboard-recent-row [data-action='dashboard-delete-application']").first.get_attribute("data-app-id")
        first_name = await page.locator(".dashboard-recent-row__name").first.inner_text()
        # View on an application with no generated document must not open the
        # wizard (the full flow is covered in test_dashboard_view_preview.py).
        await page.locator(".dashboard-recent-row [data-action='dashboard-view-application']").first.click()
        await page.wait_for_timeout(400)
        checks.check(f"[{w}] View never opens the full wizard", "new-application" not in await page.evaluate("location.hash"),
                     await page.evaluate("location.hash"))
        await page.evaluate("location.hash = '#/dashboard'")
        await page.wait_for_timeout(300)

        # Delete: cancel keeps it, confirm removes it, count + list update.
        await page.locator(".dashboard-recent-row [data-action='dashboard-delete-application']").first.click()
        await page.wait_for_timeout(200)
        modal_visible = await page.locator("[data-dash-delete-confirm]").is_visible()
        checks.check(f"[{w}] Delete asks for confirmation first", modal_visible)
        still = await page.evaluate("KhannaState.getApplications().length")
        checks.check(f"[{w}] nothing is deleted before confirming", still == 5, str(still))
        await page.locator("[data-dash-delete-cancel].btn").click()
        await page.wait_for_timeout(200)
        checks.check(f"[{w}] Cancel keeps the application", await page.evaluate("KhannaState.getApplications().length") == 5)

        await page.locator(".dashboard-recent-row [data-action='dashboard-delete-application']").first.click()
        await page.wait_for_timeout(200)
        await page.locator("[data-dash-delete-confirm]").click()
        await page.wait_for_timeout(300)
        remaining = await page.evaluate("KhannaState.getApplications().map(function (a) { return a.id })")
        checks.check(f"[{w}] Confirm deletes exactly the chosen application", len(remaining) == 4 and first_id not in remaining, f"{first_id} {remaining}")
        total = await page.inner_text(".stat-card__value")
        checks.check(f"[{w}] Total Applications count updates to 4", total.strip() == "4", total)
        stored = await page.evaluate("JSON.stringify(Object.keys(localStorage).map(function (k) { return localStorage.getItem(k) }))")
        checks.check(f"[{w}] deletion is persisted (gone from localStorage)", first_id not in stored)
        names = await page.locator(".dashboard-recent-row__name").all_inner_texts()
        checks.check(f"[{w}] deleted applicant no longer listed in Recent Applications", first_name not in names, str(names))

        # Dashboard-only: Applications page's own instant delete untouched.
        has_old = await page.evaluate("document.querySelectorAll(\"[data-view=dashboard] [data-action='delete-application']\").length")
        checks.check(f"[{w}] dashboard does not use the Applications page's unconfirmed delete", has_old == 0)

        # Dark theme sanity: accent tokens still produce a distinct card.
        await page.click("[data-profile-toggle]")
        await page.click("[data-profile-dropdown] [data-theme-toggle]")
        await page.wait_for_timeout(200)
        dark = await page.evaluate("""() => ({ stat: getComputedStyle(document.querySelector('.stat-card')).backgroundColor,
            card: getComputedStyle(document.querySelector('.dashboard-doc-card')).backgroundColor })""")
        checks.check(f"[{w}] dark theme keeps the stat card distinct", dark["stat"] != dark["card"], str(dark))

    checks.check(f"[{w}] zero console errors", len(errors) == 0, "\n".join(errors))
    await page.close()


async def tablet_pass(browser, w, expected_cols):
    page = await browser.new_page(viewport={"width": w, "height": 900})
    await fresh_load_and_login(page, base=BASE)
    await page.evaluate("location.hash = '#/dashboard'")
    await page.wait_for_timeout(300)
    m = await page.evaluate(METRICS)
    checks.check(f"[{w}] tablet/small desktop: no overflow, 8 cards in {expected_cols} columns", m["sw"] <= m["cw"] and m["cols"] == expected_cols, str(m))
    await page.close()


async def fold_pass(browser, w, h):
    """Title + all 8 cards (Total Applications + 7 documents) must be visible in
    the first screen (no scrolling) on real phone viewport heights."""
    page = await browser.new_page(viewport={"width": w, "height": h})
    await fresh_load_and_login(page, base=BASE)
    await page.evaluate(SEED)
    await page.evaluate("location.hash = '#/dashboard'")
    await page.wait_for_timeout(300)
    r = await page.evaluate("""() => { var cards = document.querySelector('[data-dashboard-doc-grid]').children;
      var last = cards[cards.length - 1].getBoundingClientRect();
      var de = document.documentElement;
      return { bottom: Math.round(last.bottom), vh: window.innerHeight, sw: de.scrollWidth, cw: de.clientWidth } }""")
    checks.check(f"[{w}x{h}] all 8 cards (incl. stat card) fit in the first screen (last card ends at {r['bottom']}px)",
                 r["bottom"] <= r["vh"] and r["sw"] <= r["cw"], str(r))
    await page.close()


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        for w in (1366, 1440):
            await desktop_pass(browser, w)
        for w, cols in ((768, 3), (1023, 3), (1024, 4)):
            await tablet_pass(browser, w, cols)
        for w in (320, 360, 375, 390, 414):
            await mobile_pass(browser, w)
        for w, h in ((320, 640), (360, 640), (375, 667), (390, 700), (414, 736)):
            await fold_pass(browser, w, h)
        await browser.close()
    checks.report_and_exit()


asyncio.run(main())
