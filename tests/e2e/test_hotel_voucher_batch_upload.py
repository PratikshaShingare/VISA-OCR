"""
Hotel Blocking — "Upload Hotel Vouchers" (multi-file) end-to-end check.

Frontend rework, Phase 3: staff can now select SEVERAL hotel/OTA voucher
files at once on the standalone Hotel Blocking page (or the wizard's own
step 5) and get one new hotel record per file, each run through the real
backend OCR pipeline (backend/python/hotel_voucher_ocr.py) — not a second,
fake/mocked upload path (project rule 9). This exercises that flow against
two distinctly-labeled synthetic vouchers (fixtures/generate_fixtures.py)
and checks that both hotels are created with their OWN distinct extracted
data (the exact regression class Phase 13's own single-hotel listener bug
was — see js/hotels.js's file header — proven not to have resurfaced in
the new batch path).

Requires: the static file server AND the backend both running (see
run_e2e_suite.py) — KHANNA_E2E_BASE overrides the default localhost port.
"""

import asyncio

from playwright.async_api import async_playwright

from _common import (
    BASE,
    Checks,
    STAFF_EMAIL,
    STAFF_PASSWORD,
    SYNTHETIC_HOTEL_VOUCHER_1_PNG,
    SYNTHETIC_HOTEL_VOUCHER_2_PNG,
    ensure_fixtures,
    fresh_load_and_login,
    start_guided_wizard_application,
)

checks = Checks()


async def main():
    ensure_fixtures()
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page(viewport={"width": 1280, "height": 1000})
        console_errors = []
        page.on("console", lambda m: console_errors.append(m.text) if m.type == "error" else None)

        await fresh_load_and_login(page, base=BASE, email=STAFF_EMAIL, password=STAFF_PASSWORD)
        await start_guided_wizard_application(page)
        await page.wait_for_timeout(300)
        await page.evaluate("location.hash = '#/new-application/5'")
        await page.wait_for_timeout(300)

        upload_input = page.locator("[data-hotel-batch-upload-input]")
        checks.check("A real <input type=file multiple> backs 'Upload Hotel Vouchers' (not a decorative button)", await upload_input.get_attribute("multiple") is not None)

        await upload_input.set_input_files([SYNTHETIC_HOTEL_VOUCHER_1_PNG, SYNTHETIC_HOTEL_VOUCHER_2_PNG])

        status_sel = "[data-hotel-batch-upload-status]"
        final_status = ""
        for _ in range(240):  # up to ~2 min: two real Tesseract runs, slower on small/shared machines
            final_status = (await page.inner_text(status_sel)).strip()
            if final_status.startswith("2 hotel(s) added"):
                break
            await page.wait_for_timeout(500)
        checks.check("Batch status reports both vouchers processed", final_status.startswith("2 hotel(s) added"), final_status)
        checks.check("Batch status confirms extraction is never auto-verified", "never auto-verified" in final_status, final_status)

        hotels = await page.evaluate("KhannaState.getActiveApplication().hotels")
        checks.check("Exactly 2 hotels were created (one per uploaded file)", len(hotels) == 2, str(len(hotels)))

        by_name = {h.get("hotelName"): h for h in hotels}
        checks.check(
            "Both hotels kept their OWN distinct extracted data (not cross-contaminated)",
            "Fixture Grand Hotel" in by_name and "Fixture Riviera Hotel" in by_name,
            str(sorted(by_name.keys())),
        )

        h1 = by_name.get("Fixture Grand Hotel") or {}
        checks.check("Hotel 1: city extracted", h1.get("city") == "Paris", str(h1.get("city")))
        checks.check("Hotel 1: country extracted (new OCR field)", h1.get("country") == "France", str(h1.get("country")))
        checks.check("Hotel 1: confirmation number extracted", h1.get("confirmationNumber") == "FIX111222", str(h1.get("confirmationNumber")))
        checks.check("Hotel 1: check-in/check-out dates extracted", h1.get("checkIn") == "2026-12-01" and h1.get("checkOut") == "2026-12-05", f"{h1.get('checkIn')} / {h1.get('checkOut')}")
        checks.check("Hotel 1: adults/children extracted", h1.get("noOfAdults") == "2" and h1.get("noOfChildren") == "0", f"{h1.get('noOfAdults')} / {h1.get('noOfChildren')}")
        checks.check("Hotel 1: lead guest and the other guest captured separately", h1.get("leadGuestName") == "Test Guestone" and list(h1.get("guestNames") or []) == ["Test Guesttwo"], f"{h1.get('leadGuestName')} / {h1.get('guestNames')}")

        h2 = by_name.get("Fixture Riviera Hotel") or {}
        checks.check("Hotel 2: city extracted", h2.get("city") == "Nice", str(h2.get("city")))
        checks.check("Hotel 2: country extracted (new OCR field)", h2.get("country") == "France", str(h2.get("country")))
        checks.check("Hotel 2: confirmation number extracted (distinct from hotel 1's)", h2.get("confirmationNumber") == "FIX333444", str(h2.get("confirmationNumber")))
        checks.check("Hotel 2: check-in/check-out dates extracted", h2.get("checkIn") == "2026-12-06" and h2.get("checkOut") == "2026-12-10", f"{h2.get('checkIn')} / {h2.get('checkOut')}")

        # Every field, including every OCR-extracted one, must still be a
        # plain editable input in each hotel's own edit panel (project rule
        # 10 — never auto-verified/locked).
        first_hotel_id = hotels[0]["id"]
        await page.click(f"[data-action='edit-hotel'][data-hotel-id='{first_hotel_id}']")
        await page.wait_for_timeout(200)
        city_input_editable = await page.evaluate(
            """() => { const el = document.querySelector('[data-hotel-field="city"]'); return !!el && !el.disabled && !el.readOnly; }"""
        )
        checks.check("An OCR-extracted field (city) remains a plain, editable input", city_input_editable)

        checks.check("Zero console errors during the batch-upload pass", len(console_errors) == 0, "; ".join(console_errors[:5]))

        await browser.close()

    checks.report_and_exit()


if __name__ == "__main__":
    asyncio.run(main())
