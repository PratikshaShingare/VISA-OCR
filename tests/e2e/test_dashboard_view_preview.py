"""
Dashboard "View" (eye) icon -> preview-only mode, plus the profile-menu theme
toggle and the phone header.

The eye icon must open the generated document's PREVIEW only (router.js
"#/<doc>/preview", js/document-preview.js, css/document-preview.css) — not
the full wizard and not the document page's form fields. Documents here are
really generated through the real backend (hotel voucher + company
authorization letter), so the preview that appears is the real PDF.

Requires the static server and the backend (see run_e2e_suite.py).
"""

import asyncio

from playwright.async_api import async_playwright

from _common import BASE, Checks, fresh_load_and_login, future_date

checks = Checks()

SEED = """() => {
  var user = "customercare@khannatravels.com";
  function mk(name, passport) {
    var a = KhannaState.createApplication(user);
    KhannaState.updateApplication(a.id, { applicant: Object.assign({}, a.applicant, { fullName: name, passport: { current: { number: passport } } }) }, "seed");
    return a.id;
  }
  var ids = {};
  ids.none = mk("Nina NoDocs", "N0000001");
  ids.both = mk("Bhavna Both", "B0000002");
  ids.hotel = mk("Hari Hotel", "H0000003");
  [ids.hotel, ids.both].forEach(function (id) {
    var h = KhannaState.addHotel(id);
    KhannaState.updateHotel(id, h.id, { hotelName: "Grand Test Hotel", city: "Paris", checkIn: "2026-12-01", checkOut: "2026-12-05" }, "seed");
  });
  KhannaState.updateApplication(ids.both, { authorization: { company: { selectedPersonIds: ["applicant"], recipientText: "The Consulate General, Mumbai" } } }, "seed");
  return ids;
}"""

VISIBLE_FIELDS = """() => {
  var sec = document.querySelector('.view.is-active');
  return Array.prototype.slice.call(sec.querySelectorAll('input:not([type=hidden]), select, textarea, [contenteditable=true]'))
    .filter(function (el) { return !el.closest('.doc-viewer') && el.offsetParent !== null && getComputedStyle(el).visibility !== 'hidden'; }).length;
}"""


async def wait_preview(page, timeout_ms=60000):
    await page.wait_for_selector(".view.is-active .doc-viewer__canvas:not([hidden])", timeout=timeout_ms)
    # ...and no "Generating document…" status: a viewer that already rendered
    # earlier keeps its old canvas visible while it regenerates.
    await page.wait_for_function(
        """() => { var st = document.querySelector('.view.is-active [data-dv=status]');
                   return !st || st.hidden || st.textContent.trim() === '' || getComputedStyle(st).display === 'none'; }""",
        timeout=timeout_ms,
    )


async def generate_via_page(page, app_id, view, selector):
    await page.evaluate("(id) => KhannaState.setActiveApplicationId(id)", app_id)
    await page.evaluate(f"location.hash = '#/{view}'")
    await page.wait_for_timeout(500)
    await page.click(selector)
    await wait_preview(page)
    await page.wait_for_timeout(1000)  # the controller stamps generatedAt just after the preview renders


async def desktop():
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page(viewport={"width": 1366, "height": 900})
        errors = []
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        page.on("pageerror", lambda e: errors.append(str(e)))
        await fresh_load_and_login(page, base=BASE)
        ids = await page.evaluate(SEED)

        # Really generate: hotel voucher for 'hotel' and 'both'; company letter for 'both'.
        await generate_via_page(page, ids["hotel"], "hotel-blocking", "[data-action='generate-voucher']")
        await generate_via_page(page, ids["both"], "hotel-blocking", "[data-action='generate-voucher']")
        await generate_via_page(page, ids["both"], "company-authorization",
                                "[data-action='generate-authorization'][data-group='company']")
        stamps = await page.evaluate("""(ids) => ({
          hotel: !!KhannaState.getApplications().find(a => a.id === ids.hotel).hotels[0].voucherGeneratedAt,
          bothCompany: !!KhannaState.getApplications().find(a => a.id === ids.both).authorization.company.generatedAt })""", ids)
        checks.check("setup: documents really generated through the backend", stamps["hotel"] and stamps["bothCompany"], str(stamps))

        # ---- single generated document: eye opens that preview directly ----
        await page.evaluate("location.hash = '#/dashboard'")
        await page.wait_for_timeout(300)
        row = page.locator(".dashboard-recent-row", has_text="Hari Hotel")
        await row.locator("[data-action='dashboard-view-application']").click()
        await wait_preview(page)
        hash_ = await page.evaluate("location.hash")
        checks.check("eye -> hotel preview page, not the wizard", hash_ == "#/hotel-blocking/preview", hash_)
        checks.check("html carries preview mode", await page.evaluate("document.documentElement.getAttribute('data-doc-mode')") == "preview")
        active_id = await page.evaluate("KhannaState.getActiveApplicationId()")
        checks.check("the clicked application became the active one", active_id == ids["hotel"], active_id)
        checks.check("no form fields are visible (preview only)", await page.evaluate(VISIBLE_FIELDS) == 0, str(await page.evaluate(VISIBLE_FIELDS)))
        vis = await page.evaluate("""() => { var s = document.querySelector('.view.is-active');
          function shown(sel) { var e = s.querySelector(sel); return !!e && e.offsetParent !== null; }
          return { viewer: shown('.doc-viewer'), canvas: shown('.doc-viewer__canvas'), bar: shown('.doc-preview-bar'),
                   h1: shown('.view-header'), appbar: shown('[data-doc-page-app-bar]'), hotelsList: shown('[data-hotels-list]'),
                   generate: shown('[data-voucher-generate]'), download: shown('[data-dv=download-pdf]') } }""")
        checks.check("real PDF preview + download button shown", vis["viewer"] and vis["canvas"] and vis["download"], str(vis))
        checks.check("page header, 'working on' bar, hotel list and generate card are hidden",
                     not vis["h1"] and not vis["appbar"] and not vis["hotelsList"] and not vis["generate"], str(vis))
        bar = await page.inner_text(".view.is-active .doc-preview-bar")
        checks.check("preview bar names the document and applicant", "Hotel Blocking" in bar and "Hari Hotel" in bar, bar)
        notice = await page.evaluate("document.querySelector('.view.is-active [data-pv-notice]').hidden")
        checks.check("no warning shown when the preview works", notice is True)

        # Edit details -> normal page with fields
        await page.click(".view.is-active [data-pv-edit]")
        await page.wait_for_timeout(500)
        checks.check("Edit details leaves preview mode", await page.evaluate("location.hash") == "#/hotel-blocking"
                     and await page.evaluate("document.documentElement.getAttribute('data-doc-mode')") == "")
        checks.check("normal page is back (generate card + hotel list visible)",
                     await page.evaluate("""() => { var s = document.querySelector('.view.is-active');
                        return !!s.querySelector('[data-voucher-generate]') && s.querySelector('[data-voucher-generate]').offsetParent !== null
                          && s.querySelector('.doc-preview-bar').offsetParent === null }"""))

        # Back to Dashboard
        await page.evaluate("location.hash = '#/hotel-blocking/preview'")
        await wait_preview(page)
        await page.click(".view.is-active [data-pv-back]")
        await page.wait_for_timeout(300)
        checks.check("Back to Dashboard works", await page.evaluate("location.hash") == "#/dashboard")

        # ---- several documents: chooser ----
        await page.locator(".dashboard-recent-row", has_text="Bhavna Both").locator("[data-action='dashboard-view-application']").click()
        await page.wait_for_timeout(300)
        picks = await page.locator("[data-dash-view-pick]").all_inner_texts()
        checks.check("two generated documents -> chooser lists both (not the wizard)",
                     len(picks) == 2 and any("Hotel Blocking" in t for t in picks) and any("Company Authorization" in t for t in picks)
                     and "new-application" not in await page.evaluate("location.hash"), str(picks))
        await page.locator("[data-dash-view-pick]", has_text="Company Authorization").click()
        await wait_preview(page)
        hash_ = await page.evaluate("location.hash")
        checks.check("choosing Company Authorization opens its preview", hash_ == "#/company-authorization/preview", hash_)
        checks.check("company page: no form fields visible", await page.evaluate(VISIBLE_FIELDS) == 0, str(await page.evaluate(VISIBLE_FIELDS)))
        vis = await page.evaluate("""() => { var s = document.querySelector('.view.is-active');
          function shown(sel) { var e = s.querySelector(sel); return !!e && e.offsetParent !== null; }
          return { viewer: shown('.doc-viewer'), checklist: shown('[data-auth-checklist]'), card: shown('[data-company-auth-card]'),
                   fields: shown('[data-company-field-editors]') } }""")
        checks.check("company page: preview shown, checklist/editors hidden", vis["viewer"] and not vis["checklist"] and not vis["fields"], str(vis))

        # leaving via the drawer / nav link leaves preview mode
        await page.evaluate("location.hash = '#/dashboard'")
        await page.wait_for_timeout(300)
        checks.check("navigating away clears preview mode", await page.evaluate("document.documentElement.getAttribute('data-doc-mode')") == "")

        # reload straight onto a preview URL keeps working
        await page.evaluate("location.hash = '#/hotel-blocking/preview'")
        await page.evaluate("KhannaState.setActiveApplicationId('" + ids["hotel"] + "')")
        await page.reload()
        await page.wait_for_timeout(500)
        await wait_preview(page)
        checks.check("reloading on the preview URL regenerates the preview", await page.evaluate(VISIBLE_FIELDS) == 0)

        # ---- no documents yet: still redirects (no popup) ----
        await page.evaluate("location.hash = '#/dashboard'")
        await page.wait_for_timeout(300)
        await page.locator(".dashboard-recent-row", has_text="Nina NoDocs").locator("[data-action='dashboard-view-application']").click()
        await page.wait_for_timeout(3500)
        toast = await page.evaluate("document.querySelectorAll('.toast').length")
        hash_ = await page.evaluate("location.hash")
        checks.check("application with nothing generated still redirects to a preview page (no popup/toast)",
                     toast == 0 and hash_.endswith("/preview") and "new-application" not in hash_, f"{hash_} toasts={toast}")
        note = await page.evaluate("""() => { var n = document.querySelector('.view.is-active [data-pv-notice]'); return { hidden: n.hidden, text: n.textContent } }""")
        checks.check("...and the preview bar explains there is nothing to preview yet", note["hidden"] is False and "yet" in note["text"], str(note))
        bar = await page.inner_text(".view.is-active .doc-preview-bar")
        checks.check("preview bar shows the application number", ids["none"] in bar, bar)

        # Viewing must not change generated/updated dates.
        before = await page.evaluate("""(id) => { var a = KhannaState.getApplications().find(x => x.id === id);
          return { u: a.updatedAt, g: a.hotels[0].voucherGeneratedAt } }""", ids["hotel"])
        await page.evaluate("(id) => KhannaState.setActiveApplicationId(id)", ids["hotel"])
        await page.evaluate("location.hash = '#/hotel-blocking/preview'")
        await wait_preview(page)
        await page.wait_for_timeout(1500)
        after = await page.evaluate("""(id) => { var a = KhannaState.getApplications().find(x => x.id === id);
          return { u: a.updatedAt, g: a.hotels[0].voucherGeneratedAt } }""", ids["hotel"])
        checks.check("previewing does not change 'Updated' or 'Last generated'", before == after, f"{before} vs {after}")

        # Not generated yet, but details saved on the hotel page -> View goes to that page's preview.
        hid = await page.evaluate("""() => { var a = KhannaState.createApplication('customercare@khannatravels.com');
          location.hash = '#/hotel-blocking';
          return a.id }""")
        await page.wait_for_timeout(500)
        await page.evaluate("""(id) => { var h = KhannaState.addHotel(id);
          KhannaState.updateHotel(id, h.id, { hotelName: 'Lone Hotel', city: 'Rome', checkIn: '2026-12-01', checkOut: '2026-12-03', leadGuestName: 'Lena Lonehotel' }, 'seed') }""", hid)
        # An application with ONLY hotel blocking lives on the Hotel Blocking
        # page's "Recent Hotel Blockings" (see test_hotel_blockings_page.py),
        # not the Dashboard — give this one a destination so it is a normal
        # application whose name still comes from its hotel.
        await page.evaluate("(id) => KhannaState.updateApplication(id, { travel: { destination: 'Italy' } }, 'seed')", hid)
        await page.wait_for_timeout(300)
        last = await page.evaluate("(id) => KhannaState.getApplications().find(a => a.id === id).lastDocView", hid)
        checks.check("application remembers the page it was worked on (lastDocView)", last == "hotel-blocking", str(last))
        await page.evaluate("location.hash = '#/dashboard'")
        await page.wait_for_timeout(300)
        row = page.locator(".dashboard-recent-row", has_text="Lena Lonehotel")
        checks.check("untitled application is listed under the name typed on its hotel page", await row.count() == 1)
        await row.locator("[data-action='dashboard-view-application']").click()
        await wait_preview(page)
        hash_ = await page.evaluate("location.hash")
        checks.check("View on a not-yet-generated hotel application opens the hotel preview", hash_ == "#/hotel-blocking/preview", hash_)
        gen = await page.evaluate("(id) => KhannaState.getApplications().find(a => a.id === id).hotels[0].voucherGeneratedAt", hid)
        checks.check("...without marking it as generated", gen is None, str(gen))

        # ---- missing details: honest notice ----
        await page.evaluate("(id) => KhannaState.updateApplication(id, { authorization: { company: { recipientText: '' } } }, 'seed')", ids["both"])
        await page.evaluate("(id) => KhannaState.setActiveApplicationId(id)", ids["both"])
        await page.evaluate("location.hash = '#/company-authorization/preview'")
        await page.wait_for_timeout(800)
        warn = await page.evaluate("""() => { var n = document.querySelector('.view.is-active [data-pv-notice]'); return { hidden: n.hidden, text: n.textContent } }""")
        checks.check("incomplete details -> honest 'can't be previewed' notice", warn["hidden"] is False and "missing" in warn["text"], str(warn))

        # ---- passport authorization: really generated, then previewed ----
        await page.evaluate("""(id) => KhannaState.updateApplication(id, { authorization: { passport: { selectedPersonIds: ["applicant"],
            recipientCentreName: "Germany Visa Application Centre", recipientAddress: "Andheri, Mumbai", collectorName: "Mr. Suresh Patil" } } }, 'seed')""", ids["hotel"])
        await generate_via_page(page, ids["hotel"], "passport-authorization",
                                "[data-action='generate-authorization'][data-group='passport']")
        await page.wait_for_timeout(1000)
        await page.evaluate("location.hash = '#/dashboard'")
        await page.wait_for_timeout(300)
        await page.locator(".dashboard-recent-row", has_text="Hari Hotel").locator("[data-action='dashboard-view-application']").click()
        await page.wait_for_timeout(300)
        picks = await page.locator("[data-dash-view-pick]").all_inner_texts()
        checks.check("passport authorization joins the chooser", any("Passport Authorization" in t for t in picks), str(picks))
        await page.locator("[data-dash-view-pick]", has_text="Passport Authorization").click()
        await wait_preview(page)
        checks.check("passport authorization preview: no form fields visible", await page.evaluate(VISIBLE_FIELDS) == 0,
                     str(await page.evaluate(VISIBLE_FIELDS)))

        # ---- cover letter (the main use case): really generated, eye opens ONLY its preview ----
        cid = await page.evaluate("""() => { var a = KhannaState.createApplication('customercare@khannatravels.com');
          KhannaState.updateApplication(a.id, { applicant: Object.assign({}, a.applicant, { fullName: 'Cora Cover', passport: { current: { number: 'C0000009' } } }),
            coverLetter: { region: 'Singapore', country: 'Singapore', selectedPersonIds: ['applicant'], recipientText: 'The Embassy of Singapore, New Delhi',
              destinationCountry: 'Singapore', travelStartDate: '__START__', travelEndDate: '__END__', fundingType: 'self', fundingArrangement: 'myself',
              singapore: { hotelName: 'Test Hotel Singapore', hotelAddress: '1 Orchard Road, Singapore' } } }, 'seed');
          return a.id }""".replace("__START__", future_date(40)).replace("__END__", future_date(47)))
        await generate_via_page(page, cid, "cover-letter", "[data-action='generate-cover-letter']")
        await page.wait_for_timeout(1000)
        checks.check("cover letter really generated (stamped)", await page.evaluate(
            "(id) => !!KhannaState.getApplications().find(a => a.id === id).coverLetter.generatedAt", cid))
        await page.evaluate("location.hash = '#/dashboard'")
        await page.wait_for_timeout(300)
        await page.locator(".dashboard-recent-row", has_text="Cora Cover").locator("[data-action='dashboard-view-application']").click()
        await wait_preview(page)
        hash_ = await page.evaluate("location.hash")
        checks.check("eye on a cover-letter application opens the cover letter preview directly", hash_ == "#/cover-letter/preview", hash_)
        checks.check("cover letter preview: no form fields (no country box, checklist, wording editor)",
                     await page.evaluate(VISIBLE_FIELDS) == 0, str(await page.evaluate(VISIBLE_FIELDS)))
        vis = await page.evaluate("""() => { var s = document.querySelector('.view.is-active');
          function shown(sel) { var e = s.querySelector(sel); return !!e && e.offsetParent !== null; }
          return { viewer: shown('.doc-viewer'), canvas: shown('.doc-viewer__canvas'), card: shown('[data-cover-letter-card]'), bar: shown('.doc-preview-bar') } }""")
        checks.check("cover letter preview: real PDF shown, the form card is not", vis["viewer"] and vis["canvas"] and not vis["card"] and vis["bar"], str(vis))
        await page.click(".view.is-active [data-pv-edit]")
        await page.wait_for_timeout(600)
        checks.check("cover letter: Edit details brings the form back",
                     await page.evaluate("""() => { var c = document.querySelector('.view.is-active [data-cover-letter-card]'); return !!c && c.offsetParent !== null }"""))

        # ---- every previewable page hides its form (cover letter, invitation too) ----
        for view in ("cover-letter", "invitation-letter", "hotel-blocking", "company-authorization", "passport-authorization"):
            await page.evaluate("(id) => KhannaState.setActiveApplicationId(id)", ids["none"])
            await page.evaluate(f"location.hash = '#/{view}/preview'")
            await page.wait_for_timeout(3500)  # waits out the module's ~2.5s retry for a generate button
            info = await page.evaluate("""() => { var s = document.querySelector('.view.is-active');
              return { bar: s.querySelector('.doc-preview-bar').offsetParent !== null,
                       title: s.querySelector('.view-header').offsetParent !== null,
                       notice: !s.querySelector('[data-pv-notice]').hidden } }""")
            checks.check(f"{view}/preview: bar shown, page heading hidden, explains why nothing to preview",
                         info["bar"] and not info["title"] and info["notice"], str(info))
            checks.check(f"{view}/preview: no form fields visible", await page.evaluate(VISIBLE_FIELDS) == 0,
                         str(await page.evaluate(VISIBLE_FIELDS)))

        checks.check("zero console errors (desktop)", len(errors) == 0, "\n".join(errors))
        await browser.close()


async def theme_menu():
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        for w, h in ((1366, 800), (375, 700)):
            page = await browser.new_page(viewport={"width": w, "height": h})
            await fresh_load_and_login(page, base=BASE)
            await page.evaluate("location.hash = '#/dashboard'")
            await page.wait_for_timeout(300)
            # old header button is gone when logged in
            hdr = await page.evaluate("""() => { var t = document.querySelector('.header-actions > .btn-icon.theme-toggle');
              var fb = document.querySelector('.header-actions [data-auth-logged-out] .theme-toggle');
              return { headerBtn: !!t, fallbackVisible: !!fb && fb.offsetParent !== null } }""")
            checks.check(f"[{w}] header theme button is gone while signed in", not hdr["headerBtn"] and not hdr["fallbackVisible"], str(hdr))
            await page.click("[data-profile-toggle]")
            await page.wait_for_timeout(200)
            order = await page.evaluate("""() => Array.prototype.slice.call(document.querySelectorAll('[data-profile-dropdown] .profile-menu__item'))
              .filter(e => e.offsetParent !== null).map(e => e.innerText.trim().replace(/\\s+/g, ' '))""")
            checks.check(f"[{w}] theme sits between Settings and Log Out", order[-3:] == ["Settings", "Light", "Log Out"], str(order))
            ic = await page.evaluate("""() => { var b = document.querySelector('[data-profile-dropdown] [data-theme-toggle]');
              function vis(s) { var e = b.querySelector(s); return !!e && getComputedStyle(e).display !== 'none'; }
              var r = document.querySelector('[data-profile-dropdown]').getBoundingClientRect();
              return { sun: vis('.icon-sun'), moon: vis('.icon-moon'), left: Math.round(r.left), right: Math.round(r.right), vw: innerWidth } }""")
            checks.check(f"[{w}] Light shows the sun icon only", ic["sun"] and not ic["moon"], str(ic))
            checks.check(f"[{w}] dropdown fully inside the screen", ic["left"] >= 0 and ic["right"] <= ic["vw"], str(ic))
            await page.click("[data-profile-dropdown] [data-theme-toggle]")
            await page.wait_for_timeout(250)
            checks.check(f"[{w}] click switches to dark theme", await page.evaluate("document.documentElement.getAttribute('data-theme')") == "dark")
            checks.check(f"[{w}] menu closes after choosing", not await page.evaluate("document.querySelector('[data-profile-dropdown]').classList.contains('is-open')"))
            await page.click("[data-profile-toggle]")
            await page.wait_for_timeout(200)
            ic = await page.evaluate("""() => { var b = document.querySelector('[data-profile-dropdown] [data-theme-toggle]');
              function vis(s) { var e = b.querySelector(s); return !!e && getComputedStyle(e).display !== 'none'; }
              return { moon: vis('.icon-moon'), sun: vis('.icon-sun'), text: b.innerText.trim(), aria: b.getAttribute('aria-pressed'), label: b.getAttribute('aria-label') } }""")
            checks.check(f"[{w}] Dark shows the moon icon and the name 'Dark'", ic["moon"] and not ic["sun"] and ic["text"] == "Dark" and ic["aria"] == "true", str(ic))
            stored = await page.evaluate("localStorage.getItem('khanna_theme')")
            checks.check(f"[{w}] choice is remembered", stored is not None and "dark" in stored, str(stored))
            await page.close()

        # signed-out fallback keeps a theme control
        page = await browser.new_page(viewport={"width": 1366, "height": 800})
        await page.goto(BASE + "/index.html")
        await page.evaluate("localStorage.clear()")
        await page.reload()
        await page.wait_for_timeout(400)
        fb = await page.evaluate("""() => { var fb = document.querySelector('.header-actions [data-auth-logged-out] .theme-toggle');
          return !!fb && fb.offsetParent !== null }""")
        checks.check("signed out: a theme toggle is still available in the header", fb)
        await browser.close()


async def phone_header():
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        for w, h in ((320, 640), (360, 740), (375, 667), (390, 844), (414, 736)):
            page = await browser.new_page(viewport={"width": w, "height": h}, is_mobile=True, has_touch=True)
            await fresh_load_and_login(page, base=BASE)
            await page.evaluate("location.hash = '#/dashboard'")
            await page.wait_for_timeout(300)
            m = await page.evaluate("""() => {
              function box(sel) { var e = document.querySelector(sel); if (!e) return null; var r = e.getBoundingClientRect(); return { w: Math.round(r.width), vis: e.offsetParent !== null || getComputedStyle(e).position === 'fixed', r: Math.round(r.right) }; }
              var de = document.documentElement;
              return { sw: de.scrollWidth, cw: de.clientWidth,
                newChev: getComputedStyle(document.querySelector('[data-new-app-menu-toggle] .menu-chevron')).display,
                profChev: getComputedStyle(document.querySelector('[data-profile-toggle] .menu-chevron')).display,
                theme: !!document.querySelector('.header-actions > .btn-icon.theme-toggle'),
                plus: box('[data-new-app-menu-toggle]'), prof: box('[data-profile-toggle]'), nav: box('[data-nav-toggle]'),
                hdr: document.querySelector('.app-header').scrollWidth <= document.querySelector('.app-header').clientWidth } }""")
            checks.check(f"[{w}] phone: '+' and avatar buttons have no 'v' arrow",
                         m["newChev"] == "none" and m["profChev"] == "none", str(m))
            checks.check(f"[{w}] phone: no horizontal scroll, header fits", m["sw"] <= m["cw"] and m["hdr"], str(m))
            # '+' dropdown still works and stays on screen
            await page.click("[data-new-app-menu-toggle]")
            await page.wait_for_timeout(250)
            d = await page.evaluate("""() => { var r = document.querySelector('[data-new-app-menu-dropdown]').getBoundingClientRect();
              var de = document.documentElement;
              return { open: document.querySelector('[data-new-app-menu-dropdown]').classList.contains('is-open'), l: Math.round(r.left), r: Math.round(r.right), vw: innerWidth, sw: de.scrollWidth, cw: de.clientWidth, bottom: Math.round(r.bottom), vh: innerHeight } }""")
            checks.check(f"[{w}] phone: '+' menu opens, inside the screen, no sideways scroll",
                         d["open"] and d["l"] >= 0 and d["r"] <= d["vw"] and d["sw"] <= d["cw"], str(d))
            await page.click("[data-new-app-menu-dropdown] [data-nav-link='cover-letter']")
            await page.wait_for_timeout(300)
            checks.check(f"[{w}] phone: choosing from the '+' menu navigates", await page.evaluate("location.hash") == "#/cover-letter")
            await page.click("[data-profile-toggle]")
            await page.wait_for_timeout(250)
            d = await page.evaluate("""() => { var r = document.querySelector('[data-profile-dropdown]').getBoundingClientRect(); var de = document.documentElement;
              return { open: document.querySelector('[data-profile-dropdown]').classList.contains('is-open'), l: Math.round(r.left), r: Math.round(r.right), vw: innerWidth, sw: de.scrollWidth, cw: de.clientWidth } }""")
            checks.check(f"[{w}] phone: account menu opens, inside the screen, no sideways scroll",
                         d["open"] and d["l"] >= 0 and d["r"] <= d["vw"] and d["sw"] <= d["cw"], str(d))
            await page.close()
        await browser.close()


async def main():
    await desktop()
    await theme_menu()
    await phone_header()
    checks.report_and_exit()


asyncio.run(main())
