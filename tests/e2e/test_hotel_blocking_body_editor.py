"""
Hotel Blocking — editable preview (replaces the old per-hotel "Voucher
wording (editable)" section).

The preview is still the REAL generated PDF; every editable VALUE on it
(hotel name, dates, guests, ...) can be clicked and edited in place with a
Word-like toolbar that lives in the viewer's title line (font, size, bold,
italic, underline, text colour, highlight, alignment). "Regenerate" bakes the
edits into the PDF; Download as PDF / Download as DOCX / Print regenerate
first if there are unsaved edits, so they always match the screen.

Checked end to end against the real backend: overlays are positioned from
the real LibreOffice rendering, typed edits persist into KhannaState
(hotel.editedFields), and the downloaded .docx / .pdf really contain the
edited, formatted text — verified by parsing the files, not the DOM alone.

Requires: the static file server AND the backend both running (see
run_e2e_suite.py).
"""

import asyncio
import io

import pypdfium2 as pdfium
from docx import Document
from playwright.async_api import async_playwright

from _common import BASE, Checks, fresh_load_and_login, start_guided_wizard_application

checks = Checks()


def _all_paragraphs(container):
    out = list(container.paragraphs)
    for table in container.tables:
        for row in table.rows:
            for cell in row.cells:
                out.extend(_all_paragraphs(cell))
    return out


def _docx_text(doc):
    return "\n".join(p.text for p in _all_paragraphs(doc))


def _pdf_text(path):
    pdf = pdfium.PdfDocument(path)
    try:
        raw = "\n".join(pdf[i].get_textpage().get_text_range() for i in range(len(pdf)))
        return " ".join(raw.split())  # edited 20pt text wraps inside its cell
    finally:
        pdf.close()


async def _fill_hotel(page, name, city, checkin, checkout, confirmation):
    await page.fill("#hf-hotelName", name)
    await page.fill("#hf-phone", "+41 22 123 4567")
    await page.fill("#hf-address", f"1 Lakeside Avenue, {city}")
    await page.fill("#hf-city", city)
    await page.fill("#hf-confirmationNumber", confirmation)
    await page.fill("#hf-leadGuestName", "Rohan Mehta")
    await page.fill("#hf-noOfAdults", "2")
    await page.fill("#hf-noOfRooms", "1")
    await page.fill("#hf-roomType", "Deluxe")
    await page.fill("#hf-checkIn", checkin)
    await page.fill("#hf-checkOut", checkout)
    await page.locator("#hf-checkOut").blur()
    await page.wait_for_timeout(200)


async def _wait_preview_ready(page, polls=100):
    for _ in range(polls):
        st = (await page.inner_text("[data-voucher-preview] [data-dv='status']")).strip()
        if st == "":
            break
        await page.wait_for_timeout(300)
    await page.wait_for_timeout(800)


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        context = await browser.new_context(viewport={"width": 1280, "height": 1400}, accept_downloads=True)
        page = await context.new_page()
        console_errors = []
        page.on("console", lambda m: console_errors.append(m.text) if m.type == "error" else None)
        page.on("pageerror", lambda e: console_errors.append(f"pageerror: {e}"))

        await fresh_load_and_login(page, base=BASE)
        await start_guided_wizard_application(page)
        await page.wait_for_timeout(300)
        await page.evaluate("location.hash = '#/new-application/5'")
        await page.wait_for_timeout(300)

        await page.click("[data-action='add-hotel']")
        await page.wait_for_timeout(250)
        await _fill_hotel(page, "The Grand Meridian", "Geneva", "2026-12-01", "2026-12-05", "CONF-GM01")
        checks.check("The old 'Voucher wording (editable)' section is gone", await page.locator("[data-hotel-field-editors]").count() == 0)
        checks.check("No 'Voucher wording' text anywhere on the page", "Voucher wording" not in await page.inner_text("body"))
        await page.click("[data-action='close-hotel-panel']")
        await page.click("[data-action='add-hotel']")
        await page.wait_for_timeout(250)
        await _fill_hotel(page, "Hotel Alpenblick", "Zurich", "2026-12-05", "2026-12-15", "CONF-ALP02")
        await page.click("[data-action='close-hotel-panel']")

        await page.click("[data-action='generate-voucher']")
        await _wait_preview_ready(page)

        edit_btn = page.locator("[data-voucher-preview] [data-dv='edit-toggle']")
        checks.check("The preview has an Edit button at the top of the Preview section", await edit_btn.count() == 1 and await edit_btn.is_visible())
        checks.check("Overlays are not live (not visible) while Edit is off", await page.locator("[data-voucher-preview] .pe-field").first.is_hidden())
        checks.check("The formatting toolbar is hidden while Edit is off", await page.locator("[data-voucher-preview] [data-dv='format-tools']").is_hidden())
        await edit_btn.click()
        await page.wait_for_timeout(300)
        checks.check("Pressing Edit turns edit mode on (button shows 'Done editing')", (await edit_btn.inner_text()).strip() == "Done editing")

        regen = (await page.inner_text("[data-voucher-preview] [data-dv='regenerate']")).strip()
        checks.check("The preview's button is labelled 'Regenerate' (not 'Preview')", regen == "Regenerate", regen)
        checks.check(
            "Formatting toolbar sits in the viewer's title line (same toolbar row as 'Hotel Voucher')",
            await page.locator("[data-voucher-preview] .doc-viewer__toolbar [data-dv-title] ~ .doc-viewer__format [data-pe='bold']").count() == 1,
        )
        for ctl in ("font", "size", "bold", "italic", "underline", "color", "highlight", "align-left", "align-center", "align-right", "align-justify", "bullet", "ordered", "table-menu", "spacing-menu"):
            checks.check(f"Toolbar has a '{ctl}' control", await page.locator(f"[data-voucher-preview] [data-pe='{ctl}']").count() == 1)
        checks.check("Toolbar is disabled until a value is clicked", await page.locator("[data-voucher-preview] [data-pe='bold']").is_disabled())

        n_overlays = await page.locator("[data-voucher-preview] .pe-field").count()
        checks.check("Page 1 is editable as a whole document (every text block, not just the 14 value areas)", n_overlays >= 14, str(n_overlays))
        checks.check(
            "No overlay sits on a fixed label/heading (only values)",
            await page.locator("[data-voucher-preview] .pe-field[data-pe-key='confirmationSentence']").count() == 1,
        )

        # ---- edit hotel 1's name, with formatting ----
        field = page.locator("[data-voucher-preview] .pe-field[data-pe-key='hotelName']").first
        await field.click()
        await page.wait_for_timeout(700)
        checks.check("Clicking a value enables the toolbar", not await page.locator("[data-voucher-preview] [data-pe='bold']").is_disabled())
        seeded = (await page.inner_text("[data-voucher-preview] .pe-field.is-active .ql-editor")).strip()
        checks.check("The value opens seeded with the real current text", seeded == "The Grand Meridian", seeded)
        await page.keyboard.press("Control+A")
        await page.keyboard.type("Grand Meridian Lake View")
        await page.keyboard.press("Control+A")
        await page.click("[data-voucher-preview] [data-pe='bold']")
        await page.select_option("[data-voucher-preview] [data-pe='size']", "20pt")
        await page.select_option("[data-voucher-preview] [data-pe='font']", "Arial")
        await page.click("[data-voucher-preview] [data-pe='color-menu']")
        await page.click("[data-pe-popover] [data-hex='#FF0000'], .pe-pop [data-hex='#FF0000']")
        await page.click("[data-voucher-preview] [data-pe='highlight-menu']")
        await page.click(".pe-pop [data-hex='#FFFF00']")
        await page.wait_for_timeout(500)
        html = await page.inner_text("[data-voucher-preview] .pe-field.is-active .ql-editor")
        checks.check("Typed text is in the editor", "Grand Meridian Lake View" in html, html)
        await page.locator("[data-voucher-preview] .pe-field[data-pe-key='city']").first.click()  # commit by moving on
        await page.wait_for_timeout(500)
        saved = await page.evaluate("(KhannaState.getActiveApplication().hotels[0].editedFields || {}).hotelName || null")
        checks.check("The edit is saved into the hotel record", saved is not None and "Grand Meridian Lake View" in saved, str(saved))
        checks.check("Saved HTML carries bold", saved is not None and "<strong" in saved, str(saved))
        checks.check("Saved HTML carries the 20pt size", saved is not None and "20pt" in saved, str(saved))
        checks.check("Saved HTML carries the colour", saved is not None and ("255, 0, 0" in saved or "#ff0000" in saved.lower()), str(saved))
        checks.check("Saved HTML carries the highlight", saved is not None and "255, 255, 0" in saved, str(saved))
        checks.check("Saved HTML carries the font", saved is not None and "Arial" in saved, str(saved))
        checks.check(
            "The edited value shows over the stale PDF text until regenerated",
            await page.locator("[data-voucher-preview] .pe-field[data-pe-key='hotelName'].is-edited").count() == 1,
        )

        # ---- Regenerate bakes the edit into the real PDF ----
        await page.click("[data-voucher-preview] [data-dv='regenerate']")
        await page.wait_for_timeout(500)
        await _wait_preview_ready(page)
        checks.check(
            "After Regenerate the overlay is transparent again (edit lives in the real PDF)",
            await page.locator("[data-voucher-preview] .pe-field.is-edited").count() == 0,
        )

        async with page.expect_download() as dl_info:
            await page.click("[data-voucher-preview] [data-dv='download-pdf']")
        dl = await dl_info.value
        pdf_path = await dl.path()
        text = _pdf_text(pdf_path)
        checks.check("Downloaded PDF contains the edited hotel name", "Grand Meridian Lake View" in text)
        checks.check("Downloaded PDF no longer contains the original name", "The Grand Meridian" not in text)
        checks.check("Downloaded PDF still has hotel 2 untouched", "Hotel Alpenblick" in text and "CONF-ALP02" in text)
        checks.check("Downloaded PDF keeps the fixed Hotel Policy text", "Early check out will attract full cancellation charge" in text)

        # ---- Download without pressing Regenerate: unsaved edit is still included ----
        await page.locator("[data-voucher-preview] .pe-field[data-pe-key='leadGuestName']").first.click()
        await page.wait_for_timeout(700)
        await page.keyboard.press("Control+A")
        await page.keyboard.type("Rohan Q Mehta")
        await page.wait_for_timeout(500)
        async with page.expect_download() as dl_info:
            await page.click("[data-voucher-preview] [data-dv='download-pdf']")
        dl = await dl_info.value
        text2 = _pdf_text(await dl.path())
        checks.check("Download as PDF regenerates first, so a not-yet-regenerated edit is included", "Rohan Q Mehta" in text2)

        async with page.expect_download() as dl_info:
            await page.click("[data-voucher-preview] [data-dv='download-docx']")
        dl = await dl_info.value
        with open(await dl.path(), "rb") as f:
            doc = Document(io.BytesIO(f.read()))
        dtext = _docx_text(doc)
        checks.check("Downloaded DOCX contains both edits", "Grand Meridian Lake View" in dtext and "Rohan Q Mehta" in dtext)
        checks.check("DOCX has both HOTEL VOUCHER blocks", dtext.count("HOTEL VOUCHER") == 2, str(dtext.count("HOTEL VOUCHER")))
        checks.check("DOCX hotel 1's untouched confirmation number is still generated", "CONF-GM01" in dtext)

        # ---- Print: pages are rasterised into a hidden iframe and print() is called ----
        await page.evaluate(
            """() => { window.__printCalls = [];
                 new MutationObserver(() => document.querySelectorAll('iframe').forEach(f => {
                   if (f.__hooked) return; f.__hooked = true;
                   f.addEventListener('load', () => { try { f.contentWindow.print = () => window.__printCalls.push(f.contentDocument.images.length); } catch (e) {} });
                 })).observe(document.body, {childList: true}); }"""
        )
        await page.click("[data-voucher-preview] [data-dv='print']")
        for _ in range(40):
            if await page.evaluate("window.__printCalls.length"):
                break
            await page.wait_for_timeout(300)
        calls = await page.evaluate("window.__printCalls")
        checks.check("Print opens the print dialog with one image per PDF page (2 hotels = 2 pages)", calls == [2], str(calls))

        # ---- Reset restores the auto-generated text ----
        await page.locator("[data-voucher-preview] .pe-field[data-pe-key='hotelName']").first.click()
        await page.wait_for_timeout(700)
        await page.click("[data-voucher-preview] [data-pe='reset']")
        await page.wait_for_timeout(700)
        reset_text = (await page.inner_text("[data-voucher-preview] .pe-field.is-active .ql-editor")).strip()
        checks.check("Reset restores the real composed value", reset_text == "The Grand Meridian", reset_text)
        cleared = await page.evaluate("(KhannaState.getActiveApplication().hotels[0].editedFields || {}).hotelName")
        checks.check("Reset clears the saved override", cleared is None, str(cleared))

        checks.check("Zero console errors throughout", len(console_errors) == 0, "; ".join(console_errors[:8]))
        await browser.close()
    checks.report_and_exit()


if __name__ == "__main__":
    asyncio.run(main())
