"""
Hotel Blocking — two DIFFERENT voucher layouts uploaded together.

A TBO-style voucher (two rooms, four guests, lead guest marked) and a
"Confirmed Booking" voucher (Booking Summary panel, Leader, Guest Details) are
rendered here from invented data (never real client vouchers), uploaded in one
selection, and must come out as two hotels IN UPLOAD ORDER, each with its own
confirmation number, nights, adults, room type, lead guest and a guest list that
holds the lead exactly once — with no blank hotel row left behind.

Requires the static server and the backend (see run_e2e_suite.py).
"""

import asyncio
import os
import sys
import tempfile

from playwright.async_api import async_playwright

from _common import BASE, Checks, STAFF_EMAIL, STAFF_PASSWORD, fresh_load_and_login, start_guided_wizard_application

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "backend", "python", "tests"))
sys.path.insert(0, os.path.join(HERE, "..", "..", "backend", "python"))

checks = Checks()


def make_vouchers(folder):
    import test_hotel_voucher_layout as fx  # renders synthetic vouchers

    tbo = fx._tbo_voucher(
        [("Standard Queen Room", ["Mr. Alpha Tester", "Mrs. Beta Tester"]), ("Standard Queen Room", ["Mr. Delta Tester", "Mr. Echo Tester"])]
    )
    booking = fx._booking_summary_voucher()
    paths = [os.path.join(folder, "1_tbo.png"), os.path.join(folder, "2_booking.png")]
    tbo.save(paths[0])
    booking.save(paths[1])
    return paths


async def main():
    with tempfile.TemporaryDirectory() as tmp:
        paths = make_vouchers(tmp)
        async with async_playwright() as p:
            browser = await p.chromium.launch()
            page = await browser.new_page(viewport={"width": 1280, "height": 1000})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            await fresh_load_and_login(page, base=BASE, email=STAFF_EMAIL, password=STAFF_PASSWORD)
            await start_guided_wizard_application(page)
            await page.evaluate("location.hash = '#/new-application/5'")
            await page.wait_for_timeout(400)

            await page.locator("[data-hotel-batch-upload-input]").set_input_files(paths)
            status = ""
            for _ in range(300):
                status = (await page.inner_text("[data-hotel-batch-upload-status]")).strip()
                if status.startswith("2 hotel(s) added"):
                    break
                await page.wait_for_timeout(500)
            checks.check("Both vouchers were processed", status.startswith("2 hotel(s) added"), status)

            hotels = await page.evaluate("KhannaState.getActiveApplication().hotels")
            checks.check("Exactly two hotels, no blank leftover row", len(hotels) == 2 and all((h.get("hotelName") or "").strip() for h in hotels), str([h.get("hotelName") for h in hotels]))
            names = [h.get("hotelName") for h in hotels]
            checks.check("Hotels are in upload order", names == ["Aurora Bay Palace", "Lakeside Test Residence"], str(names))

            a, b = hotels[0], hotels[1]
            checks.check("TBO: confirmation / dates / nights", a.get("confirmationNumber") == "TBZZ9Q4K2M" and a.get("checkIn") == "2027-10-07" and a.get("checkOut") == "2027-10-12", f"{a.get('confirmationNumber')} {a.get('checkIn')} {a.get('checkOut')}")
            checks.check("TBO: rooms / adults / room type", a.get("noOfRooms") == "2" and a.get("noOfAdults") == "4" and a.get("roomType") == "Standard Queen Room", f"{a.get('noOfRooms')} {a.get('noOfAdults')} {a.get('roomType')}")
            checks.check("TBO: lead guest once, other three guests listed", a.get("leadGuestName") == "Mr. Alpha Tester" and list(a.get("guestNames") or []) == ["Mrs. Beta Tester", "Mr. Delta Tester", "Mr. Echo Tester"], f"{a.get('leadGuestName')} / {a.get('guestNames')}")
            checks.check("Booking summary: dates / rooms / adults", b.get("checkIn") == "2027-12-24" and b.get("checkOut") == "2027-12-27" and b.get("noOfRooms") == "2" and b.get("noOfAdults") == "4", f"{b.get('checkIn')} {b.get('checkOut')} {b.get('noOfRooms')} {b.get('noOfAdults')}")
            others = [g.lower() for g in (b.get("guestNames") or [])]
            checks.check("Booking summary: leader is the lead guest and not repeated", "john tester" in (b.get("leadGuestName") or "").lower() and not any("john tester" in g for g in others) and len(others) == 3, f"{b.get('leadGuestName')} / {b.get('guestNames')}")
            checks.check("The two hotels do not share data", a.get("confirmationNumber") != b.get("confirmationNumber"))

            checks.check("No page errors", not errors, str(errors[:2]))
            await browser.close()
    checks.report_and_exit()


if __name__ == "__main__":
    asyncio.run(main())
