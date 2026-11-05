"""
Word (docx-preview) fallback in the shared document viewer.

When the PDF cannot be made (here: the PDF request of the Hotel Voucher is
answered with the server error a missing LibreOffice produces) the generated
.docx is shown in the viewer instead of an empty preview:

  * the real python-docx file is rendered page by page (A4) by docx-preview,
    from the locally stored library (no CDN request is made);
  * a note explains why this is the Word version; "Download as PDF" is disabled
    with a reason; "Download as Docx" still gives a real .docx;
  * Edit is disabled with a reason; zoom / fit / page buttons work; Print opens
    the Word pages for printing;
  * no horizontal overflow at 390px; no console errors (apart from the
    deliberate 500).
Synthetic names only.
"""
import asyncio
import json
import os
import sys
import zipfile

from playwright.async_api import async_playwright

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from _common import BASE, Checks, fresh_load_and_login, start_guided_wizard_application  # noqa: E402
from test_hotel_blocking_body_editor import _fill_hotel  # noqa: E402

checks = Checks()


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        context = await browser.new_context(viewport={"width": 1280, "height": 1400}, accept_downloads=True)
        page = await context.new_page()
        errors, external = [], []
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" and "500" not in m.text else None)
        page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
        page.on("request", lambda r: external.append(r.url) if not r.url.startswith(("http://127.0.0.1", "http://localhost", "data:", "blob:")) else None)

        pdf_requests = {"n": 0}

        async def fail_pdf(route):
            # /preview is the call that makes the PDF the viewer shows
            pdf_requests["n"] += 1
            await route.fulfill(
                status=500, content_type="application/json",
                headers={"access-control-allow-origin": "*"},
                body=json.dumps({"detail": "PDF conversion failed: LibreOffice is not installed on this machine"}),
            )

        await fresh_load_and_login(page, base=BASE)
        await page.route("**/api/documents/hotel-voucher/preview", fail_pdf)
        await start_guided_wizard_application(page)
        await page.wait_for_timeout(300)
        await page.evaluate("location.hash = '#/new-application/5'")
        await page.wait_for_timeout(300)
        await page.click("[data-action='add-hotel']")
        await page.wait_for_timeout(250)
        await _fill_hotel(page, "The Grand Meridian", "Geneva", "2026-12-01", "2026-12-05", "CONF-GM01")
        await page.click("[data-action='close-hotel-panel']")
        await page.click("[data-action='generate-voucher']")

        v = "[data-voucher-preview]"
        await page.wait_for_selector(f"{v} .doc-viewer__docx section.docx", timeout=60000)
        await page.wait_for_timeout(600)

        checks.check("the PDF really was requested and refused", pdf_requests["n"] >= 1)
        sections = await page.locator(f"{v} .doc-viewer__docx section.docx").count()
        checks.check("the Word document is shown page by page", sections >= 1, str(sections))
        text = await page.inner_text(f"{v} .doc-viewer__docx")
        checks.check("the voucher content is on the Word page (hotel name)", "The Grand Meridian" in text or "THE GRAND MERIDIAN" in text.upper(), text[:200])
        checks.check("the confirmation number is on the Word page", "CONF-GM01" in text)
        checks.check("tables are rendered (voucher uses tables)", await page.locator(f"{v} .doc-viewer__docx table").count() >= 1)
        dims = await page.evaluate("""() => { var s = document.querySelector('[data-voucher-preview] .doc-viewer__docx section.docx');
            var cs = getComputedStyle(s); return { w: parseFloat(cs.width), h: parseFloat(cs.minHeight || cs.height) } }""")
        ratio = dims["w"] / dims["h"]
        checks.check("page keeps A4 proportions (210 x 297 mm)", abs(ratio - 210 / 297) < 0.01, str(dims))
        checks.check("the empty-preview message is gone", (await page.inner_text(f"{v} [data-dv='status']")).strip() == "")
        note = await page.inner_text(f"{v} [data-dv='note']")
        checks.check("a note explains it is the Word version and why", "Word version" in note and "PDF could not be made" in note, note[:160])
        checks.check("Download as PDF is disabled with a reason", await page.locator(f"{v} [data-dv='download-pdf']").is_disabled() and bool(await page.get_attribute(f"{v} [data-dv='download-pdf']", "title")))
        checks.check("Edit is disabled with a reason", await page.locator(f"{v} [data-dv='edit-toggle']").is_disabled() and "PDF" in (await page.get_attribute(f"{v} [data-dv='edit-toggle']", "title") or ""))
        label = await page.inner_text(f"{v} [data-dv='page-label']")
        checks.check("page label shows the page count", label.startswith("Page 1 of"), label)

        # ---- real .docx download still works
        async with page.expect_download(timeout=60000) as dl:
            await page.click(f"{v} [data-dv='download-docx']")
        download = await dl.value
        path = await download.path()
        ok_zip = zipfile.is_zipfile(path)
        checks.check("Download as Docx gives a real .docx", download.suggested_filename.lower().endswith(".docx") and ok_zip, download.suggested_filename)
        if ok_zip:
            with zipfile.ZipFile(path) as z:
                checks.check("the file is a Word document (word/document.xml)", "word/document.xml" in z.namelist())

        # ---- zoom / fit
        before = await page.inner_text(f"{v} [data-dv='zoom-label']")
        await page.click(f"{v} [data-dv='zoom-in']")
        after = await page.inner_text(f"{v} [data-dv='zoom-label']")
        checks.check("zoom in changes the zoom", before != after, f"{before} -> {after}")
        await page.click(f"{v} [data-dv='fit']")
        fit = await page.inner_text(f"{v} [data-dv='zoom-label']")
        checks.check("Fit restores the fitted zoom", fit == before, f"{before} / {fit}")

        # ---- print opens the Word pages in a hidden frame
        await page.evaluate("window.__frames = []; new MutationObserver(function (m) { m.forEach(function (r) { r.addedNodes.forEach(function (n) { if (n.tagName === 'IFRAME') window.__frames.push(n.srcdoc || ''); }); }); }).observe(document.body, { childList: true });")
        await page.click(f"{v} [data-dv='print']")
        await page.wait_for_timeout(800)
        frames = await page.evaluate("window.__frames")
        checks.check("Print builds an A4 print frame containing the Word pages", any("size:A4" in f and 'class="docx"' in f for f in frames), str(len(frames)))

        # ---- phone width: no sideways scrolling, the page fits
        await page.set_viewport_size({"width": 390, "height": 844})
        await page.wait_for_timeout(700)
        m = await page.evaluate("""() => { var b = document.querySelector('[data-voucher-preview] [data-dv=body]'); var s = document.querySelector('[data-voucher-preview] .doc-viewer__docx section.docx');
            return { page: document.documentElement.scrollWidth, client: document.documentElement.clientWidth, body: b.clientWidth, sec: s.getBoundingClientRect().width } }""")
        checks.check("390px: the page has no horizontal overflow", m["page"] <= m["client"], str(m))
        checks.check("390px: the Word page is fitted inside the preview", m["sec"] <= m["body"], str(m))

        checks.check("no request left this computer's own servers (no CDN)", not external, str(external[:3]))
        checks.check("no console errors", not errors, "; ".join(errors[:3]))
        await browser.close()
    checks.report_and_exit()


asyncio.run(main())
