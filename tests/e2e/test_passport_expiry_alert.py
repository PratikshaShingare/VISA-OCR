"""
End-to-end: a popup when an uploaded passport has expired or expires within
one year — on Upload Passport (single passport page) and on the pages that
read passports through KhannaDocumentIntake (Check Forms here; Upload
Documents and Fill Forms use the same code).

The synthetic passport (tests/e2e/fixtures) expires in 2030; the real backend
answer is intercepted and only its expiry date is changed, so the page runs
the real OCR and the real code path. All data is invented (rule 11).
"""

import asyncio
import datetime as dt
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from playwright.async_api import async_playwright  # noqa: E402

from _common import SYNTHETIC_PASSPORT_PNG, Checks, ensure_fixtures, fresh_load_and_login  # noqa: E402

C = Checks()


def iso_in(days):
    return (dt.date.today() + dt.timedelta(days=days)).isoformat()


async def set_expiry(page, iso):
    """Changes dateOfExpiry in every real /api/passport/process answer
    (None = leave it). Done in the page: the real OCR still runs."""
    await page.evaluate("""(iso) => {
      const api = window.KhannaApi;
      if (!api.__origProcessPassport) api.__origProcessPassport = api.processPassport;
      api.processPassport = function () {
        return api.__origProcessPassport.apply(api, arguments).then(function (res) {
          if (iso && res && res.fields && res.fields.dateOfExpiry) res.fields.dateOfExpiry.value = iso;
          if (iso && res && res.mrz && res.mrz.fields && res.mrz.fields.expiryDate) res.mrz.fields.expiryDate = iso;
          return res;
        });
      };
    }""", iso)


async def popup_text(page, timeout=90000):
    await page.wait_for_selector("[data-passport-expiry-modal]:not([hidden])", timeout=timeout)
    return await page.inner_text("[data-passport-expiry-modal]")


async def main():
    ensure_fixtures()
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page(viewport={"width": 1280, "height": 900})
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        await fresh_load_and_login(page)

        # The rule itself (dates relative to today).
        r = await page.evaluate("""() => {
          const A = window.KhannaPassportExpiry, iso = d => { const x = new Date(); x.setDate(x.getDate() + d);
            return x.getFullYear() + '-' + String(x.getMonth()+1).padStart(2,'0') + '-' + String(x.getDate()).padStart(2,'0'); };
          return { far: A.assess(iso(400)), year: A.assess(iso(360)), soon: A.assess(iso(45)), past: A.assess(iso(-3)), bad: A.assess('not a date') };
        }""")
        C.check("more than a year left: no alert", r["far"] is None, str(r["far"]))
        C.check("within a year: alert", r["year"] and r["year"]["level"] == "soon", str(r["year"]))
        C.check("45 days: says 1 month", r["soon"] and "1 month" in r["soon"]["text"], str(r["soon"]))
        C.check("expired: says expired", r["past"] and r["past"]["level"] == "expired" and "3 days ago" in r["past"]["text"], str(r["past"]))
        C.check("unreadable date: no alert", r["bad"] is None)

        # ---- Upload Passport page, expiry in ~5 months
        await set_expiry(page, iso_in(150))
        await page.evaluate("(() => { const a = KhannaState.createApplication('e2e'); KhannaState.setActiveApplicationId(a.id); location.hash = '#/upload-passport'; })()")
        await page.wait_for_selector("[data-view='upload-passport'] input[type='file']", state="attached", timeout=15000)
        await page.set_input_files("[data-view='upload-passport'] input[type='file']", SYNTHETIC_PASSPORT_PNG)
        text = await popup_text(page)
        C.check("Upload Passport: popup after reading", "expires on" in text and "month" in text, text[:300])
        C.check("popup names the passport holder", "TESTPERSON" in text.upper(), text[:300])
        C.check("popup says the date was read by OCR", "Please Verify" in text)
        await page.click("[data-passport-expiry-modal] .btn-primary")
        C.check("OK closes the popup", await page.locator("[data-passport-expiry-modal]").get_attribute("hidden") is not None)

        # ---- far expiry: no popup (fresh page so the same passport is checked again)
        await fresh_load_and_login(page)
        await set_expiry(page, None)
        await page.evaluate("(() => { const a = KhannaState.createApplication('e2e'); KhannaState.setActiveApplicationId(a.id); location.hash = '#/upload-passport'; })()")
        await page.wait_for_selector("[data-view='upload-passport'] input[type='file']", state="attached", timeout=15000)
        await page.set_input_files("[data-view='upload-passport'] input[type='file']", SYNTHETIC_PASSPORT_PNG)
        await page.wait_for_function("() => /TESTPERSON/i.test(document.querySelector(\"[data-view='upload-passport']\").innerHTML)", timeout=90000)
        await page.wait_for_timeout(3000)
        shown = await page.locator("[data-passport-expiry-modal]:not([hidden])").count()
        C.check("passport valid till 2030: no popup", shown == 0)

        # ---- Check Forms (passport read through document-intake), already expired
        await fresh_load_and_login(page)
        await set_expiry(page, iso_in(-10))
        await page.evaluate("location.hash = '#/form-check'")
        await page.wait_for_selector("[data-fc-file='passport']", state="attached", timeout=15000)
        await page.set_input_files("[data-fc-file='passport']", SYNTHETIC_PASSPORT_PNG)
        text = await popup_text(page)
        C.check("Check Forms: popup for an expired passport", "expired on" in text, text[:300])

        C.check("no page errors", not errors, " | ".join(errors[:3]))
        await browser.close()
    C.report_and_exit()


if __name__ == "__main__":
    asyncio.run(main())
