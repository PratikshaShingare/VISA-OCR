"""
End-to-end: a passport read on Upload Passport shows its cropped, straightened
data page again after the page is reloaded and the application reopened
(kept on this computer in IndexedDB — passport-image-store.js).
Synthetic passport only (project rule 11).
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from playwright.async_api import async_playwright  # noqa: E402

from _common import BASE, SYNTHETIC_PASSPORT_PNG, Checks, ensure_fixtures, login  # noqa: E402

C = Checks()


async def main():
    ensure_fixtures()
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        ctx = await browser.new_context(viewport={"width": 1280, "height": 900})
        page = await ctx.new_page()
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        await page.goto(BASE + "/index.html")
        await page.evaluate("localStorage.clear(); indexedDB.deleteDatabase('khanna-passport-images')")
        await page.reload()
        await login(page)
        app_id = await page.evaluate("(() => { const a = KhannaState.createApplication('e2e'); KhannaState.setActiveApplicationId(a.id); return a.id; })()")
        await page.evaluate("location.hash = '#/upload-passport'")
        await page.wait_for_selector("[data-view='upload-passport'] input[type='file']", state="attached")
        await page.set_input_files("[data-view='upload-passport'] input[type='file']", SYNTHETIC_PASSPORT_PNG)
        await page.wait_for_function("() => /TESTPERSON/i.test(document.querySelector(\"[data-view='upload-passport']\").innerHTML)", timeout=90000)
        await page.wait_for_timeout(1500)
        saved = await page.evaluate("""() => new Promise(res => { const r = indexedDB.open('khanna-passport-images'); r.onsuccess = () => {
            const t = r.result.transaction('processed', 'readonly').objectStore('processed').getAll(); t.onsuccess = () => res(t.result.map(x => x.processedDataUrl.slice(0, 23))); }; })""")
        C.check("processed page kept on this computer as JPEG", len(saved) == 1 and saved[0].startswith("data:image/jpeg"), str(saved))

        # Save, reload (memory gone), reopen the application.
        await page.click("[data-view='upload-passport'] [data-passport-save]")
        await page.wait_for_timeout(500)
        await page.reload()
        await page.wait_for_timeout(500)
        await page.evaluate(f"KhannaState.setActiveApplicationId('{app_id}'); location.hash = '#/dashboard'")
        await page.wait_for_timeout(200)
        await page.evaluate("location.hash = '#/upload-passport'")
        await page.wait_for_function("() => { const i = document.querySelector(\"[data-view='upload-passport'] [data-passport-preview] img\"); return i && i.src.startsWith('data:image/jpeg'); }", timeout=15000)
        text = await page.inner_text("[data-view='upload-passport'] [data-passport-preview]")
        C.check("reopened passport shows the saved image", "not available" not in text and "No saved image" not in text, text[:200])

        # Another passport with no saved image: honest message.
        await page.evaluate("indexedDB.deleteDatabase('khanna-passport-images')")
        await page.reload()
        await page.wait_for_timeout(500)
        await page.evaluate(f"KhannaState.setActiveApplicationId('{app_id}'); location.hash = '#/upload-passport'")
        await page.wait_for_function("() => /No saved image of this passport/.test(document.querySelector(\"[data-view='upload-passport']\").innerText)", timeout=15000)
        C.check("no saved image: clear message", True)
        C.check("no page errors", not errors, " | ".join(errors[:3]))
        await browser.close()
    C.report_and_exit()


if __name__ == "__main__":
    asyncio.run(main())
