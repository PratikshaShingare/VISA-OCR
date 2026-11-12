"""
Edit mode looks the same as the finished page.

On the Hotel Voucher (two hotels, so two blocks across two pages) this checks
that pressing Edit keeps the page's own letterhead / shading as the background,
that every value is on the cell where it is printed (not a neighbour's), that
each hotel's guests are numbered "1)" and the policy "1." from 1, that the
template's cyan highlight is shown, that the page keeps its size, and that
nothing shifts down the page when Edit is switched on.

Requires the static server and the backend (see run_e2e_suite.py).
"""

import asyncio

from playwright.async_api import async_playwright

from _common import BASE, Checks, fresh_load_and_login, set_edit_mode, wait_preview_ready

checks = Checks()
SEED = """() => { var a = KhannaState.createApplication("customercare@khannatravels.com");
 KhannaState.updateApplication(a.id,{applicant:Object.assign({},a.applicant,{fullName:"VIPUL MODAK",salutation:"Mr",sex:"M"})},"seed");
 KhannaState.setActiveApplicationId(a.id);
 var h1=KhannaState.addHotel(a.id); KhannaState.updateHotel(a.id,h1.id,{hotelName:"Hotel Weisses Kreuz",city:"St. Gallen",address:"Engelgasse 9, St. Gallen, 9000, Switzerland",phone:"+41 71 223 28 43",checkIn:"2026-12-08",checkOut:"2026-12-12",leadGuestName:"Mr. Vipul Modak",noOfRooms:"1",noOfAdults:"1",roomType:"Standard Single",confirmationNumber:"TBQQMHDVB"},"seed");
 var h2=KhannaState.addHotel(a.id); KhannaState.updateHotel(a.id,h2.id,{hotelName:"B&B Hotel Milano Ornato",leadGuestName:"Mr. Vipul Modak"},"seed");
 return a.id; }"""
SCOPE = ".view.is-active [data-voucher-preview]"

# where each unit's first line sits, relative to the stage, in page px
LINE_POS = """(key) => {
  const stage = document.querySelector('.view.is-active .lw-stage');
  const sb = stage.getBoundingClientRect(); const k = sb.width / stage.offsetWidth;
  return Array.from(stage.querySelectorAll("[data-unit$='|" + key + "']")).map(n => {
    const r = n.getBoundingClientRect();
    return {unit: n.getAttribute('data-unit'), x: (r.left - sb.left) / k, y: (r.top - sb.top) / k, text: n.innerText.trim()};
  });
}"""


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page(viewport={"width": 1280, "height": 1000})
        errors = []
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        page.on("pageerror", lambda e: errors.append(str(e)))
        await fresh_load_and_login(page, base=BASE)
        await page.evaluate(SEED)
        await page.evaluate("location.hash = '#/hotel-blocking'")
        await page.wait_for_timeout(900)
        checks.check("Generate is enabled although the second hotel has gaps", await page.locator("[data-action='generate-voucher']").is_enabled())
        await page.click("[data-action='generate-voucher']")
        await wait_preview_ready(page, SCOPE)
        view_w = await page.evaluate("(s) => document.querySelector(s + ' canvas').getBoundingClientRect().width", SCOPE)

        await set_edit_mode(page, SCOPE, True)
        await page.wait_for_selector(f"{SCOPE} .lw-stage .lw-page__bg", timeout=15000)
        await page.wait_for_timeout(700)
        n_bg = await page.locator(f"{SCOPE} .lw-page__bg").count()
        checks.check("Each page's printed background (letterhead, shading, footer) is drawn behind the text", n_bg == 2, str(n_bg))
        page_w = await page.evaluate("(s) => document.querySelector(s + ' .lw-page').getBoundingClientRect().width", SCOPE)
        pane_w = await page.evaluate("(s) => document.querySelector(s + ' .lw').parentElement.clientWidth", SCOPE)
        checks.check("In Edit mode the page is as wide as the editor (readable on a short window), not shrunk to the whole-page view size",
                     page_w >= view_w - 6 and page_w <= pane_w + 2 and page_w >= 0.85 * min(pane_w, 1.8 * 794 / 1.333 * 1.333), f"view {view_w} edit {page_w} pane {pane_w}")
        # + / - / Fit keep working while editing
        z0 = await page.evaluate("(s) => document.querySelector(s + ' .lw-page').getBoundingClientRect().width", SCOPE)
        await page.click(f"{SCOPE} [data-dv='zoom-out']")
        await page.wait_for_timeout(200)
        z1 = await page.evaluate("(s) => document.querySelector(s + ' .lw-page').getBoundingClientRect().width", SCOPE)
        checks.check("Zoom out works while editing", z1 < z0 - 10, f"{z0} -> {z1}")
        await page.click(f"{SCOPE} [data-dv='fit']")
        await page.wait_for_timeout(200)
        z2 = await page.evaluate("(s) => document.querySelector(s + ' .lw-page').getBoundingClientRect().width", SCOPE)
        checks.check("Fit brings the page back to the editor's width", abs(z2 - z0) < 6, f"{z0} -> {z2}")

        # every value sits on the cell it is printed in
        pos = {}
        for key in ("hotelName", "leadGuestName", "guestTotal", "noOfRooms", "phone", "checkIn", "checkOut", "nights", "city", "address", "guestNames", "roomType", "guestCounts"):
            pos[key] = await page.evaluate(LINE_POS, key)
        h1 = {k: v[0] for k, v in pos.items() if v}
        order_ok = (
            h1["hotelName"]["y"] < h1["leadGuestName"]["y"] < h1["noOfRooms"]["y"] < h1["checkIn"]["y"] < h1["nights"]["y"]
            < h1["address"]["y"] < h1["guestNames"]["y"]
        )
        checks.check("Values run down the page in the printed order", order_ok, str({k: round(v["y"]) for k, v in h1.items()}))
        left_col, right_col = h1["leadGuestName"]["x"], h1["hotelName"]["x"]
        checks.check(
            "Left-column values share one x, right-column values another",
            abs(h1["noOfRooms"]["x"] - left_col) < 3 and abs(h1["checkIn"]["x"] - left_col) < 3 and abs(h1["phone"]["x"] - right_col) < 3 and abs(h1["city"]["x"] - right_col) < 3,
            str({k: round(v["x"]) for k, v in h1.items()}),
        )
        checks.check("Each value is its own, not a neighbour's (phone, rooms, guests)",
                     "+41" in h1["phone"]["text"] and h1["noOfRooms"]["text"] == "1" and "Adult" in h1["guestCounts"]["text"],
                     f'{h1["phone"]["text"]!r} {h1["noOfRooms"]["text"]!r} {h1["guestCounts"]["text"]!r}')
        checks.check("Row mates are on the same line (rooms with phone, check-in with check-out)",
                     abs(h1["noOfRooms"]["y"] - h1["phone"]["y"]) < 8 and abs(h1["checkIn"]["y"] - h1["checkOut"]["y"] if "checkOut" in h1 else 0) < 8)

        # second hotel: on the second page, nothing pushed off it
        second = await page.evaluate(LINE_POS, "city")
        page_h = await page.evaluate("(s) => document.querySelector(s + ' .lw-page').offsetHeight", SCOPE)
        checks.check("The second hotel's values are there too", len(second) == 2, str(len(second)))
        checks.check("...and stay on their page (no drifting down)", second[1]["y"] < page_h * 2 + 16, str(second[1]["y"]))
        gap = second[1]["y"] - (await page.evaluate(LINE_POS, "hotelName"))[1]["y"]
        first_gap = h1["city"]["y"] - h1["hotelName"]["y"]
        checks.check("Second hotel's rows are spaced like the first's", abs(gap - first_gap) < 40, f"{gap} vs {first_gap}")

        # numbering of guests and policy restarts for each hotel
        nums = await page.evaluate(
            """() => Array.from(document.querySelectorAll(".view.is-active .lw-stage [data-unit$='|guestNames']")).map(n => n.style.counterReset)"""
        )
        checks.check("Each hotel's guest list restarts its numbering at 1)", len(nums) == 2 and all(x.startswith("lwnum") for x in nums), str(nums))
        marker = await page.evaluate(
            """() => getComputedStyle(document.querySelector(".view.is-active .lw-stage [data-unit$='|guestNames']"), '::before').content"""
        )
        checks.check("...shown as 'n)' before the name", "counter(lwnum)" in marker and ")" in marker, marker)
        policy = await page.evaluate(
            """() => Array.from(document.querySelectorAll(".view.is-active .lw-stage li")).map(n => (getComputedStyle(n, '::before').content || '').replace(/["\\u00a0]/g, ''))"""
        )
        checks.check("Each hotel's policy is numbered 1. 2.", policy[:2] == policy[2:4] and len(policy) >= 4, str(policy))

        # the template's cyan highlight on the values is shown
        hl = await page.evaluate(
            """() => ["hotelName","checkIn","checkOut","city"].map(k => { const line = document.querySelector(".view.is-active .lw-stage [data-unit$='|" + k + "']"); const hit = Array.from(line.querySelectorAll('*')).map(n => getComputedStyle(n).backgroundColor).find(c => c.includes('255')); return hit || ''; })"""
        )
        checks.check("The cyan highlight the template puts behind these values is shown", all("0, 255, 255" in c for c in hl), str(hl))

        # opening and closing Edit changes nothing in the saved record
        before = await page.evaluate("() => JSON.stringify(KhannaState.getActiveApplication().hotels.map(h => h.editedFields || null))")
        await set_edit_mode(page, SCOPE, False)
        await page.wait_for_timeout(500)
        after = await page.evaluate("() => JSON.stringify(KhannaState.getActiveApplication().hotels.map(h => h.editedFields || null))")
        stored = [e for e in __import__("json").loads(after) if e and any(v is not None for v in e.values())]
        checks.check("Just looking in Edit mode stores no edits", before == after and not stored, after)

        for w in (390, 320):
            await page.set_viewport_size({"width": w, "height": 900})
            await set_edit_mode(page, SCOPE, True)
            await page.wait_for_timeout(900)
            over = await page.evaluate("() => document.documentElement.scrollWidth - window.innerWidth")
            checks.check(f"No horizontal page overflow at {w}px in Edit mode", over <= 1, str(over))
            await set_edit_mode(page, SCOPE, False)

        real = [e for e in errors if "favicon" not in e.lower()]
        checks.check("no browser console errors", not real, "; ".join(real[:3]))
        await browser.close()
    checks.report_and_exit()


asyncio.run(main())
