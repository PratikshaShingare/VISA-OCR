"""
Hotel Blocking voucher upload — what the browser does with a voucher result
that carries per-room data, nights, and an online hotel lookup. The backend's
OCR / lookup are covered by pytest (test_hotel_voucher_ocr_extraction.py,
test_hotel_lookup.py); here the /api/hotel-voucher/process answer is a canned
JSON so the check is of the FRONT END only: every extracted value lands in the
right form field, a looked-up address/phone/city is labelled as looked up, and
three vouchers (same travellers in two hotels, different travellers in one
hotel with other rooms) make three separate hotel records. Synthetic data only.
"""
import asyncio
import json

from playwright.async_api import async_playwright

from _common import BASE, Checks, SYNTHETIC_HOTEL_VOUCHER_1_PNG, ensure_fixtures, fresh_load_and_login, start_guided_wizard_application

checks = Checks()


def result(hotel, conf, lead, others, room, adults, lookup_ok=True, warnings=None):
    return {
        "isBlank": False,
        "fields": {
            "hotelName": hotel, "confirmationNumber": conf, "leadGuestName": lead,
            "roomType": room, "noOfRooms": "1", "noOfAdults": str(adults),
            "checkIn": "2026-12-08", "checkOut": "2026-12-09",
            "address": "1 Test Road, Testville 400001, India" if lookup_ok else None,
            "phone": "+91 22 0000 0000" if lookup_ok else None,
            "city": "Testville" if lookup_ok else None, "country": "India" if lookup_ok else None,
        },
        "guestNames": others,
        "rooms": [],
        "nights": 1,
        "warnings": warnings or [],
        "lookup": {"status": "ok", "source": "google_places"} if lookup_ok else {"status": "not_found", "source": "google_places"},
        "ocrText": "",
        "processedImageBase64": "",
    }


RESULTS = [
    result("Sample Palace Hotel", "TBO111", "Mr. Test Person Sample", ["Mrs. Test Spouse Sample"], "Deluxe King Room", 2),
    result("Sample Lagoon Resort", "TBO222", "Mr. Test Person Sample", ["Mrs. Test Spouse Sample"], "Twin Room", 2, lookup_ok=False),
    result("Sample Palace Hotel", "TBO333", "Mr. Other Traveller Example", [], "Classic King Room", 1,
           warnings=["The voucher says 2 night(s) but the dates read give 1 — please check the check-in and check-out dates against the voucher."]),
]


async def main():
    ensure_fixtures()
    png = open(SYNTHETIC_HOTEL_VOUCHER_1_PNG, "rb").read()
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page(viewport={"width": 1280, "height": 1100})
        errors = []
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
        calls = {"n": 0}

        async def handle(route):
            body = RESULTS[min(calls["n"], len(RESULTS) - 1)]
            calls["n"] += 1
            await route.fulfill(status=200, content_type="application/json", body=json.dumps(body))

        await page.route("**/api/hotel-voucher/process", handle)
        await fresh_load_and_login(page, base=BASE)
        await start_guided_wizard_application(page)
        await page.wait_for_timeout(300)
        await page.evaluate("location.hash = '#/new-application/5'")
        await page.wait_for_timeout(300)

        files = [{"name": n, "mimeType": "image/png", "buffer": png} for n in ("voucher_palace_A.png", "voucher_lagoon_A.png", "voucher_palace_B.png")]
        await page.locator("[data-hotel-batch-upload-input]").set_input_files(files)
        status = ""
        for _ in range(60):
            status = (await page.inner_text("[data-hotel-batch-upload-status]")).strip()
            if status.startswith("3 hotel(s) added"):
                break
            await page.wait_for_timeout(300)
        checks.check("three vouchers -> three hotel records", status.startswith("3 hotel(s) added"), status)
        hotels = await page.evaluate("KhannaState.getActiveApplication().hotels")
        checks.check("exactly three hotels exist", len(hotels) == 3, str(len(hotels)))

        h1, h2, h3 = hotels
        checks.check("hotel 1: name, confirmation, lead guest, other guest, room, adults in the right fields",
                     (h1["hotelName"], h1["confirmationNumber"], h1["leadGuestName"], h1["guestNames"], h1["roomType"], h1["noOfAdults"])
                     == ("Sample Palace Hotel", "TBO111", "Mr. Test Person Sample", ["Mrs. Test Spouse Sample"], "Deluxe King Room", "2"), json.dumps(h1)[:400])
        checks.check("hotel 1: check-in / check-out placed", (h1["checkIn"], h1["checkOut"]) == ("2026-12-08", "2026-12-09"))
        checks.check("hotel 1: address, phone and city came from the lookup", (h1["address"], h1["phone"], h1["city"]) == ("1 Test Road, Testville 400001, India", "+91 22 0000 0000", "Testville"))
        checks.check("hotel 1: remembered where the details came from", h1.get("lookupSource") == "Google", str(h1.get("lookupSource")))
        checks.check("hotel 2 (same travellers, another hotel) has its own data", (h2["hotelName"], h2["confirmationNumber"], h2["roomType"]) == ("Sample Lagoon Resort", "TBO222", "Twin Room"))
        checks.check("hotel 2: nothing found online -> no lookup label, no invented address", not h2.get("lookupSource") and not h2.get("address"), json.dumps(h2)[:300])
        checks.check("hotel 3 (other traveller, same hotel, different room) is a separate record", (h3["hotelName"], h3["leadGuestName"], h3["roomType"], h3["noOfAdults"]) == ("Sample Palace Hotel", "Mr. Other Traveller Example", "Classic King Room", "1"))
        checks.check("status says address/phone/city were looked up and must be verified", "looked up online" in status and "verify" in status.lower(), status)
        checks.check("status names the hotel that could not be looked up", "could not be looked up" in status and "voucher_lagoon_A.png" in status, status)
        checks.check("status relays the nights-vs-dates warning", "voucher_palace_B.png" in status and "2 night(s)" in status, status)

        cards = await page.locator(".hotel-card").all_inner_texts()
        joined = "\n".join(cards)
        checks.check("cards still say 'OCR Extracted — Please Verify'", joined.count("OCR Extracted — Please Verify") == 3, joined[:500])
        checks.check("a looked-up hotel's card says so", "looked up on Google" in joined, joined[:500])

        await page.locator("[data-action='edit-hotel']").first.click()
        await page.wait_for_timeout(300)
        vals = {k: await page.input_value(f"#hf-{k}") for k in ("hotelName", "address", "phone", "city", "roomType", "noOfAdults", "leadGuestName", "confirmationNumber")}
        checks.check("the edit form shows the extracted values (editable fields, not read-only)", vals["roomType"] == "Deluxe King Room" and vals["address"].startswith("1 Test Road") and vals["leadGuestName"] == "Mr. Test Person Sample", str(vals))
        others = await page.locator("[data-guest-name-input]").evaluate_all("els=>els.map(e=>e.value)")
        checks.check("other guests listed under 'Guest names on the voucher'", others == ["Mrs. Test Spouse Sample"], str(others))
        await page.fill("#hf-address", "Edited by staff")
        await page.locator("#hf-address").blur()
        edited = await page.evaluate("KhannaState.getActiveApplication().hotels[0].address")
        checks.check("staff can still correct the looked-up address", edited == "Edited by staff", edited)

        checks.check("no console errors", not errors, "; ".join(errors[:4]))
        await browser.close()
    checks.report_and_exit()


asyncio.run(main())
