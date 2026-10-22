"""
Hotel Blocking page rework + "Recent Hotel Blockings" page + the red
Dashboard delete-confirm button.

Covers (all against the real static server + backend):
  - Dashboard "Delete application?" confirm button is red.
  - Hotel Blocking title row has a right-aligned "Recent Hotel Blockings" button.
  - "Working on ..." bar is compact; "Add hotel Manually" label; no
    Ready/Incomplete badges; no inner "Upload Hotel Voucher" button; the
    "Hotel Voucher document" card keeps only the button + last-generated date.
  - Uploading two vouchers: each shows (file name + thumbnail) with its hotel,
    details are extracted automatically, the voucher is generated automatically
    with one block (page) per uploaded voucher, flagged "OCR Extracted — Please Verify".
  - Hotel-blocking-only applications stay off the Dashboard; they appear on the
    Recent Hotel Blockings page with Edit / Download (DOCX, PDF) / Delete (with
    confirmation popup); Edit returns to the editable preview.
"""

import asyncio

import pypdfium2 as pdfium
from playwright.async_api import async_playwright

from _common import (
    BASE,
    Checks,
    SYNTHETIC_HOTEL_VOUCHER_1_PNG,
    SYNTHETIC_HOTEL_VOUCHER_2_PNG,
    ensure_fixtures,
    fresh_load_and_login,
)

checks = Checks()


async def wait_preview_ready(page, polls=100):
    for _ in range(polls):
        if await page.locator("[data-voucher-preview] [data-dv='status']").count():
            st = (await page.inner_text("[data-voucher-preview] [data-dv='status']")).strip()
            if st == "":
                break
        await page.wait_for_timeout(300)
    await page.wait_for_timeout(800)


async def main():
    ensure_fixtures()
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        context = await browser.new_context(viewport={"width": 1280, "height": 1000}, accept_downloads=True)
        page = await context.new_page()
        console_errors = []
        page.on("console", lambda m: console_errors.append(m.text) if m.type == "error" else None)
        page.on("pageerror", lambda e: console_errors.append(f"pageerror: {e}"))
        await fresh_load_and_login(page, base=BASE)

        # ---------- 1) red delete-confirm button on the Dashboard ----------
        await page.evaluate(
            "(function(){var a=KhannaState.createApplication('x'); KhannaState.updateApplication(a.id,{applicant:{fullName:'Dash Person'}});})()"
        )
        await page.evaluate("location.hash = '#/dashboard'")
        await page.wait_for_timeout(400)
        await page.click("[data-action='dashboard-delete-application']")
        await page.wait_for_timeout(300)
        bg = await page.evaluate("getComputedStyle(document.querySelector('[data-dash-delete-confirm]')).backgroundColor")
        checks.check("Dashboard 'Delete Application' confirm button is red", bg == "rgb(198, 40, 40)", bg)
        fg = await page.evaluate("getComputedStyle(document.querySelector('[data-dash-delete-confirm]')).color")
        checks.check("...with white text", fg == "rgb(255, 255, 255)", fg)
        await page.click("[data-dash-delete-cancel].btn-secondary")
        await page.evaluate("KhannaState.getApplications().forEach(function(a){KhannaState.deleteApplication(a.id);})")

        # ---------- 2) Hotel Blocking page chrome ----------
        await page.evaluate("location.hash = '#/hotel-blocking'")
        await page.wait_for_timeout(400)
        link = page.locator("[data-recent-hotel-blockings-link]")
        checks.check("'Recent Hotel Blockings' button exists in the title row", (await link.inner_text()).strip() == "Recent Hotel Blockings")
        box = await link.bounding_box()
        h1 = await page.locator("[data-view='hotel-blocking'] h1").bounding_box()
        container = await page.locator("[data-view='hotel-blocking'] .container").bounding_box()
        checks.check(
            "...on the same line as the title and at the right-most side",
            abs((box["y"] + box["height"] / 2) - (h1["y"] + h1["height"] / 2)) < 40 and box["x"] + box["width"] > container["x"] + container["width"] - 40,
            f"{box} {h1} {container}",
        )

        await page.click("[data-action='create-doc-application']")
        await page.wait_for_timeout(400)
        bar = await page.locator("[data-view='hotel-blocking'] .doc-page-app-bar").bounding_box()
        checks.check("'Working on' bar is compact (<= 56px tall on desktop)", bar["height"] <= 56, str(bar["height"]))
        add_label = (await page.inner_text("[data-action='add-hotel']")).strip()
        checks.check("'+ Add hotel' is renamed 'Add hotel Manually'", add_label == "Add hotel Manually", add_label)

        await page.click("[data-action='add-hotel']")
        await page.wait_for_timeout(300)
        checks.check("No inner 'Upload Hotel Voucher' button inside the editing panel", await page.locator("[data-hotel-panel] [data-hotel-voucher-browse]").count() == 0)
        checks.check("No extraction hint/inner file input in the editing panel", await page.locator("[data-hotel-panel] [data-hotel-voucher-file-input]").count() == 0)
        checks.check("No 'Voucher wording' section", "Voucher wording" not in await page.inner_text("body"))
        checks.check("Hotel card has no Ready/Incomplete badge", await page.locator("[data-hotel-card] .badge").count() == 0)
        card_text = await page.inner_text("[data-hotel-card]")
        checks.check("...and no 'Incomplete'/'Ready' text", "Incomplete" not in card_text and "Ready" not in card_text, card_text)
        gen = await page.inner_text("[data-voucher-generate]")
        checks.check("Voucher card has no title/description", "Hotel Voucher document" not in gen and "Generates the official" not in gen, gen)
        checks.check("...and still has the Generate & Preview button", "Generate & Preview Hotel Voucher" in gen, gen)
        await page.click("[data-action='close-hotel-panel']")
        await page.click("[data-action='remove-hotel']")

        # ---------- 3) upload two vouchers ----------
        await page.set_input_files("[data-hotel-batch-upload-input]", [SYNTHETIC_HOTEL_VOUCHER_1_PNG, SYNTHETIC_HOTEL_VOUCHER_2_PNG])
        for _ in range(80):
            t = (await page.inner_text("[data-hotel-batch-upload-status]")).strip()
            if t.startswith("2 hotel(s) added"):
                break
            await page.wait_for_timeout(500)
        cards = page.locator("[data-hotel-card]")
        checks.check("One hotel card per uploaded voucher", await cards.count() == 2, str(await cards.count()))
        names = [await cards.nth(i).inner_text() for i in range(await cards.count())]
        checks.check("Each card shows its uploaded voucher's file name", "synthetic_hotel_voucher_1.png" in names[0] and "synthetic_hotel_voucher_2.png" in names[1], str(names))
        checks.check("Each card shows the uploaded voucher's thumbnail", await page.locator("[data-hotel-card] .hotel-voucher-thumb img").count() == 2)
        checks.check("OCR Extracted — Please Verify flag is shown", all("OCR Extracted — Please Verify" in n for n in names), str(names))
        checks.check("Details extracted automatically (hotel names)", "Fixture Grand Hotel" in names[0] and "Fixture Riviera Hotel" in names[1], str(names))

        await wait_preview_ready(page)
        checks.check("The voucher is generated automatically after the upload", await page.locator("[data-voucher-preview] .doc-viewer__canvas").is_visible())
        checks.check("Viewer shows 'Page 1 of 2' (one voucher block per uploaded voucher)", "of 2" in (await page.inner_text("[data-voucher-preview] [data-dv='page-label']")), "")
        async with page.expect_download() as dl_info:
            await page.click("[data-voucher-preview] [data-dv='download-pdf']")
        dl = await dl_info.value
        pdf = pdfium.PdfDocument(await dl.path())
        full = " ".join(" ".join(pdf[i].get_textpage().get_text_range().split()) for i in range(len(pdf)))
        checks.check("Downloaded PDF has one page per hotel", len(pdf) == 2, str(len(pdf)))
        checks.check("...hotel 1 on its own page", "Fixture Grand Hotel" in " ".join(pdf[0].get_textpage().get_text_range().split()) and "Fixture Riviera" not in " ".join(pdf[0].get_textpage().get_text_range().split()))
        checks.check("...hotel 2 on its own page", "Fixture Riviera Hotel" in " ".join(pdf[1].get_textpage().get_text_range().split()))
        pdf.close()

        # ---------- 4) Dashboard keeps hotel-only applications off ----------
        await page.evaluate("location.hash = '#/dashboard'")
        await page.wait_for_timeout(500)
        checks.check("Hotel-blocking-only application is NOT on the Dashboard's Recent Applications", await page.locator("[data-dashboard-recent] .dashboard-recent-row").count() == 0)
        total = (await page.inner_text("[data-dashboard-stats] .stat-card__value")).strip()
        checks.check("...and not counted in Total Applications", total == "0", total)

        # ---------- 5) Recent Hotel Blockings page ----------
        await page.evaluate("location.hash = '#/hotel-blocking'")
        await page.wait_for_timeout(500)
        await page.click("[data-recent-hotel-blockings-link]")
        await page.wait_for_timeout(500)
        checks.check("Link opens the Recent Hotel Blockings page", await page.evaluate("location.hash") == "#/hotel-blockings")
        checks.check("Page title is 'Recent Hotel Blockings'", (await page.inner_text("[data-view='hotel-blockings'] h1")).strip() == "Recent Hotel Blockings")
        rows = page.locator("[data-hb-row]")
        checks.check("The hotel blocking is listed", await rows.count() == 1, str(await rows.count()))
        row_text = await rows.first.inner_text()
        checks.check("Row shows the hotels and the Edit / Download / Delete actions",
                     "Fixture Grand Hotel" in row_text and "Edit" in row_text and "Download" in row_text and "Delete" in row_text, row_text)

        menu_hidden = await page.locator("[data-hb-row] .hb-menu__dropdown").is_hidden()
        checks.check("Download dropdown is closed by default", menu_hidden)
        await page.click("[data-action='hb-download-toggle']")
        items = [t.strip() for t in await page.locator("[data-hb-row] .hb-menu__item").all_inner_texts()]
        checks.check("Download dropdown offers DOCX and PDF", items == ["Download as DOCX", "Download as PDF"], str(items))
        async with page.expect_download() as dl_info:
            await page.click("[data-action='hb-download'][data-format='pdf']")
        dl = await dl_info.value
        pdf = pdfium.PdfDocument(await dl.path())
        checks.check("Row 'Download as PDF' gives a real 2-page PDF", dl.suggested_filename.endswith(".pdf") and len(pdf) == 2, f"{dl.suggested_filename} {len(pdf)}")
        pdf.close()
        await page.click("[data-action='hb-download-toggle']")
        async with page.expect_download() as dl_info:
            await page.click("[data-action='hb-download'][data-format='docx']")
        dl = await dl_info.value
        checks.check("Row 'Download as DOCX' gives a .docx", dl.suggested_filename.endswith(".docx"), dl.suggested_filename)

        await page.click("[data-action='hb-delete']")
        await page.wait_for_timeout(300)
        modal_visible = await page.locator("[data-hb-delete-modal]").is_visible()
        checks.check("Delete asks for confirmation in a popup", modal_visible)
        confirm_bg = await page.evaluate("getComputedStyle(document.querySelector('[data-hb-delete-confirm]')).backgroundColor")
        checks.check("...whose confirm button is red", confirm_bg == "rgb(198, 40, 40)", confirm_bg)
        await page.click("[data-hb-delete-cancel].btn-secondary")
        await page.wait_for_timeout(200)
        checks.check("Cancel keeps the hotel blocking", await page.locator("[data-hb-row]").count() == 1)

        await page.click("[data-action='hb-edit']")
        await page.wait_for_timeout(600)
        await wait_preview_ready(page)
        checks.check("Edit goes back to the Hotel Blocking page", await page.evaluate("location.hash") == "#/hotel-blocking")
        checks.check("...straight onto the editable preview", await page.locator("[data-voucher-preview] .pe-field").count() >= 14)

        # Delete (confirmed) of a hotel-blocking-only application removes it entirely
        await page.click("[data-recent-hotel-blockings-link]")
        await page.wait_for_timeout(400)
        await page.click("[data-action='hb-delete']")
        await page.click("[data-hb-delete-confirm]")
        await page.wait_for_timeout(400)
        checks.check("Confirmed delete removes the row (empty state shown)", await page.locator("[data-hb-row]").count() == 0 and "No hotel blockings yet" in await page.inner_text("[data-hotel-blockings-root]"))
        n_apps = await page.evaluate("KhannaState.getApplications().length")
        checks.check("...and the otherwise-empty application is gone", n_apps == 0, str(n_apps))

        # An application with other data keeps it when only its hotel blocking is deleted
        await page.evaluate(
            """(function(){var a=KhannaState.createApplication('x'); KhannaState.updateApplication(a.id,{applicant:{fullName:'Keep Me'}});
               var h=KhannaState.addHotel(a.id); KhannaState.updateHotel(a.id,h.id,{hotelName:'H1',city:'Rome',checkIn:'2026-12-01',checkOut:'2026-12-03'});})()"""
        )
        await page.evaluate("location.hash = '#/dashboard'")
        await page.wait_for_timeout(400)
        checks.check("An application with an applicant IS on the Dashboard", await page.locator("[data-dashboard-recent] .dashboard-recent-row").count() == 1)
        await page.evaluate("location.hash = '#/hotel-blockings'")
        await page.wait_for_timeout(400)
        await page.click("[data-action='hb-delete']")
        txt = await page.inner_text("[data-hb-delete-text]")
        checks.check("Popup says the application's other documents are kept", "other documents are kept" in txt, txt)
        await page.click("[data-hb-delete-confirm]")
        await page.wait_for_timeout(300)
        kept = await page.evaluate("(function(){var a=KhannaState.getApplications(); return a.length===1 && a[0].hotels.length===0 && a[0].applicant.fullName==='Keep Me';})()")
        checks.check("Only the hotel blocking is deleted; the application stays", kept)

        # ---------- 6) phone width ----------
        await page.set_viewport_size({"width": 390, "height": 800})
        await page.evaluate(
            """(function(){var a=KhannaState.getApplications()[0]; var h=KhannaState.addHotel(a.id); KhannaState.updateHotel(a.id,h.id,{hotelName:'Mobile Hotel',city:'Oslo',checkIn:'2026-12-01',checkOut:'2026-12-03'});})()"""
        )
        await page.wait_for_timeout(400)
        sw = await page.evaluate("[document.documentElement.scrollWidth, window.innerWidth]")
        checks.check("Recent Hotel Blockings has no horizontal overflow at 390px", sw[0] <= sw[1], str(sw))
        await page.evaluate("location.hash = '#/hotel-blocking'")
        await page.wait_for_timeout(500)
        sw = await page.evaluate("[document.documentElement.scrollWidth, window.innerWidth]")
        checks.check("Hotel Blocking has no horizontal overflow at 390px", sw[0] <= sw[1], str(sw))

        checks.check("Zero console errors throughout", len(console_errors) == 0, "; ".join(console_errors[:8]))
        await browser.close()
    checks.report_and_exit()


if __name__ == "__main__":
    asyncio.run(main())
