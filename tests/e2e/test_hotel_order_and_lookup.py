"""
Hotel Blocking: hotels are arranged by their check-in / check-out dates, dates
that cannot be right are called out, and blank details are filled from the
internet when the voucher is generated.

The online lookup is answered by a stub here (what is tested is what the page
does with the answer; the lookup itself has backend tests).

Requires the static server and the backend (see run_e2e_suite.py).
"""

import asyncio
import json

from playwright.async_api import async_playwright

from _common import BASE, Checks, fresh_load_and_login, wait_preview_ready

checks = Checks()
SEED = """() => { var S = KhannaState; var a = S.createApplication("customercare@khannatravels.com");
 S.updateApplication(a.id,{applicant:Object.assign({},a.applicant,{fullName:"ORDER TEST",salutation:"Mr",sex:"M"})},"seed");
 S.setActiveApplicationId(a.id);
 function add(p){ var h=S.addHotel(a.id); S.updateHotel(a.id,h.id,p,"seed"); return h.id; }
 var ids = {
   third: add({hotelName:"Third Stay Hotel",city:"Rome",address:"Via Roma 3",phone:"+39 1",country:"Italy",checkIn:"2026-12-20",checkOut:"2026-12-24",leadGuestName:"Mr. Order Test",noOfRooms:"1",noOfAdults:"1"}),
   undated: add({hotelName:"No Dates Hotel",city:"Milan",address:"Via Milano 9",phone:"+39 2",country:"Italy"}),
   first: add({hotelName:"First Stay Hotel",checkIn:"2026-12-08",checkOut:"2026-12-12",leadGuestName:"Mr. Order Test",noOfRooms:"1",noOfAdults:"1"}),
   second: add({hotelName:"Second Stay Hotel",city:"Florence",address:"Typed Street 5",phone:"+39 3",country:"Italy",checkIn:"2026-12-11",checkOut:"2026-12-16",leadGuestName:"Mr. Order Test",noOfRooms:"1",noOfAdults:"1"}),
 };
 return {app: a.id, ids: ids}; }"""

FOUND = {
    "results": [
        {"id": None, "status": "ok", "source": "google_places", "filled": ["address", "phone", "city", "country"],
         "fields": {"address": "Piazza Duomo 1, Milano, Italy", "phone": "+39 02 1234", "city": "Milano", "country": "Italy"}},
    ]
}


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page(viewport={"width": 1280, "height": 1000})
        errors = []
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        page.on("pageerror", lambda e: errors.append(str(e)))
        await fresh_load_and_login(page, base=BASE)
        seeded = await page.evaluate(SEED)
        ids = seeded["ids"]

        lookup_requests = []
        preview_requests = []

        async def lookup_route(route):
            body = json.loads(route.request.post_data or "{}")
            lookup_requests.append(body)
            results = []
            for h in body.get("hotels", []):
                if h["hotelName"] == "First Stay Hotel":
                    results.append({"id": h["id"], "status": "ok", "source": "google_places", "filled": ["address", "phone", "city", "country"],
                                    "fields": {"address": "Piazza Duomo 1, Milano, Italy", "phone": "+39 02 1234", "city": "Milano", "country": "Italy"}})
                else:
                    results.append({"id": h["id"], "status": "not_found", "source": "", "filled": [], "fields": {}})
            await route.fulfill(status=200, content_type="application/json", body=json.dumps({"results": results}))

        async def preview_route(route):
            preview_requests.append(json.loads(route.request.post_data or "{}"))
            await route.continue_()

        await page.route("**/api/documents/hotel-voucher/complete-details", lookup_route)
        await page.route("**/api/documents/hotel-voucher/preview", preview_route)

        await page.evaluate("location.hash = '#/hotel-blocking'")
        await page.wait_for_timeout(900)

        names = await page.locator("[data-hotel-card] .hotel-card__name").all_inner_texts()
        checks.check(
            "The list is arranged by check-in date, undated hotels last",
            names == ["First Stay Hotel", "Second Stay Hotel", "Third Stay Hotel", "No Dates Hotel"],
            str(names),
        )
        seq = await page.inner_text("[data-hotel-sequence-notice]")
        checks.check(
            "Overlapping stays are called out (Second starts before First ends)",
            "Second Stay Hotel" in seq and "First Stay Hotel" in seq and "1 night overlap" in seq,
            seq,
        )
        checks.check("...but a normal gap between stays is not", "Third Stay Hotel" not in seq, seq)

        await page.click("[data-action='generate-voucher']")
        await wait_preview_ready(page, ".view.is-active [data-voucher-preview]")

        checks.check("One lookup request was made for the voucher", len(lookup_requests) == 1, str(len(lookup_requests)))
        asked = {h["hotelName"] for h in lookup_requests[0]["hotels"]} if lookup_requests else set()
        checks.check("Third Stay Hotel and No Dates Hotel (nothing blank) were not looked up",
                     "Third Stay Hotel" not in asked and "No Dates Hotel" not in asked, str(asked))

        first = await page.evaluate("(id) => { var h = KhannaState.getActiveApplication().hotels.filter(x => x.id === id)[0]; return h; }", ids["first"])
        checks.check("The blank details were filled from the lookup", first["city"] == "Milano" and "+39 02" in first["phone"] and "Duomo" in first["address"], json.dumps(first)[:300])
        checks.check("...and it says where they came from", first.get("lookupSource") == "Google", str(first.get("lookupSource")))
        second = await page.evaluate("(id) => KhannaState.getActiveApplication().hotels.filter(x => x.id === id)[0]", ids["second"])
        checks.check("Details a person typed are never replaced", second["address"] == "Typed Street 5" and second["phone"] == "+39 3" and second["city"] == "Florence")
        checks.check("The page tells the person details were filled in — Please Verify",
                     "Please Verify" in await page.inner_text("[data-hotel-lookup-filled]"))
        checks.check("Second Stay Hotel has nothing blank except what is typed, so it was not searched",
                     "Second Stay Hotel" not in asked, str(asked))

        sent = [h["hotelName"] for h in preview_requests[-1]["hotels"]]
        checks.check("The voucher is generated in date order", sent == ["First Stay Hotel", "Second Stay Hotel", "Third Stay Hotel", "No Dates Hotel"], str(sent))
        sent_first = preview_requests[-1]["hotels"][0]
        checks.check("...with the looked-up details in it", sent_first["city"] == "Milano" and "+39 02" in sent_first["phone"])

        n_before = len(lookup_requests)
        await page.click("[data-action='generate-voucher']")
        await wait_preview_ready(page, ".view.is-active [data-voucher-preview]")
        checks.check("Regenerating does not search the same hotels again", len(lookup_requests) == n_before, f"{n_before} -> {len(lookup_requests)}")
        checks.check("The 'filled in' note is still on the page", await page.locator("[data-hotel-lookup-filled]").count() == 1)

        # a hotel the internet does not know is reported, and the voucher still comes out
        await page.evaluate("() => { var a = KhannaState.getActiveApplication(); var h = KhannaState.addHotel(a.id); KhannaState.updateHotel(a.id, h.id, {hotelName: 'Ghost Hotel Nowhere', checkIn: '2027-01-05', checkOut: '2027-01-07'}, 'seed'); }")
        await page.evaluate("location.hash = '#/applications'"); await page.wait_for_timeout(300)
        await page.evaluate("location.hash = '#/hotel-blocking'"); await page.wait_for_timeout(800)
        await page.click("[data-action='generate-voucher']")
        await wait_preview_ready(page, ".view.is-active [data-voucher-preview]")
        missing = await page.inner_text("[data-hotel-lookup-missing]") if await page.locator("[data-hotel-lookup-missing]").count() else ""
        checks.check("A hotel the internet does not know is named in a notice", "Ghost Hotel Nowhere" in missing, missing)
        checks.check("...and the voucher is still generated", await page.locator(".view.is-active [data-voucher-preview] canvas").count() > 0)

        # a check-out before its own check-in
        await page.evaluate("(id) => { var a = KhannaState.getActiveApplication(); KhannaState.updateHotel(a.id, id, {checkIn: '2026-12-30', checkOut: '2026-12-28'}, 'seed'); }", ids["third"])
        await page.evaluate("location.hash = '#/applications'"); await page.wait_for_timeout(300)
        await page.evaluate("location.hash = '#/hotel-blocking'"); await page.wait_for_timeout(800)
        seq = await page.inner_text("[data-hotel-sequence-notice]")
        checks.check("A check-out before its check-in is called out", "before the check-in" in seq and "Third Stay Hotel" in seq, seq)

        real = [e for e in errors if "favicon" not in e.lower()]
        checks.check("no browser console errors", not real, "; ".join(real[:3]))
        await browser.close()
    checks.report_and_exit()


asyncio.run(main())
