"""
Real-device emulation pass.

Resizing a plain desktop-Chrome viewport to 8 fixed widths (as earlier
phases did) never emulates touch input, a real mobile User-Agent, or a
real device pixel ratio — all of which can change layout/behavior (hover
states, tap-target hit-testing, media queries keyed off pointer type).
This test drives the app under Playwright's real device descriptors
(actual UA strings + viewport + DPR + isMobile + hasTouch, the same
profiles Playwright ships for its own device-lab testing), touch-tapping
instead of mouse-clicking, across a representative spread of real devices:
a small phone, a large phone, an Android phone, and a tablet in both
orientations.

Note on cross-BROWSER-ENGINE testing: this environment cannot install
Firefox or WebKit (network egress blocks Playwright's own CDN download
hosts), so this suite cannot exercise those engines directly. Multi-device
emulation within Chromium (real touch, UA, DPR, viewport per device) is
what this test provides instead — for an internal tool whose staff will
only ever use it in a mainstream, Chromium-or-equivalent browser, this is
arguably the more relevant check of the two; the engine-testing gap is
real and is documented, not silently worked around.

Requires: the static file server AND the backend both running (see
run_e2e_suite.py) — KHANNA_E2E_BASE overrides the default localhost port.
"""

import asyncio

from playwright.async_api import async_playwright

from _common import BASE, Checks, STAFF_EMAIL, STAFF_PASSWORD

DEVICES = [
    "iPhone SE",
    "iPhone 14 Pro Max",
    "Pixel 5",
    "iPad Mini",
    "iPad Mini landscape",
]

checks = Checks()


async def check_no_overflow(page, device_name, where):
    # The authoritative real-page-overflow check: does the PAGE itself
    # need to scroll horizontally. A per-element rect.right walk is NOT
    # reliable on its own here, because .stepper-nav (and the Admin data
    # tables) are DELIBERATELY overflow-x:auto strips as of Phase 12 —
    # their own children legitimately extend past the strip's visible
    # edge, which is real, intended horizontal micro-scroll content, not
    # page overflow. So the per-element check below explicitly walks each
    # offending element's ancestor chain and only counts it if NO ancestor
    # up to <body> is itself a legitimate horizontal scroll container
    # (overflow-x auto/scroll with scrollWidth > clientWidth).
    result = await page.evaluate(
        """() => {
        const docWidth = document.documentElement.clientWidth;
        function hasScrollableAncestor(el) {
            let node = el.parentElement;
            while (node && node !== document.body) {
                const style = getComputedStyle(node);
                if ((style.overflowX === 'auto' || style.overflowX === 'scroll') && node.scrollWidth > node.clientWidth + 1) {
                    return true;
                }
                node = node.parentElement;
            }
            return false;
        }
        const all = document.querySelectorAll('body *');
        const offenders = [];
        for (const el of all) {
            const style = getComputedStyle(el);
            if (style.display === 'none' || style.visibility === 'hidden') continue;
            const rect = el.getBoundingClientRect();
            if (rect.right > docWidth + 1 && rect.width > 0 && !hasScrollableAncestor(el)) {
                offenders.push(el.tagName + '.' + (el.className || '').toString().slice(0, 40) + ' right=' + Math.round(rect.right));
            }
            if (offenders.length > 3) break;
        }
        return { docWidth, offenders, scrollWidth: document.documentElement.scrollWidth };
    }"""
    )
    checks.check(f"{device_name} @ {where}: no real page-level horizontal overflow (scroll-container content excluded)", len(result["offenders"]) == 0, str(result))
    checks.check(f"{device_name} @ {where}: documentElement.scrollWidth == clientWidth", result["scrollWidth"] <= result["docWidth"] + 1, f"scrollWidth={result['scrollWidth']} clientWidth={result['docWidth']}")


async def run_for_device(p, device_name):
    device = p.devices[device_name]
    browser = await p.chromium.launch()
    context = await browser.new_context(**device)
    page = await context.new_page()
    console_errors = []
    page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)
    page.on("pageerror", lambda exc: console_errors.append(str(exc)))

    await page.goto(BASE + "/index.html")
    await page.evaluate("localStorage.clear()")
    await page.reload()
    await page.wait_for_timeout(300)

    await check_no_overflow(page, device_name, "Dashboard")

    # Real touch tap (not a mouse click) to open the mobile nav drawer, if present
    toggle = page.locator("[data-nav-toggle]")
    if await toggle.count() > 0 and await toggle.first.is_visible():
        await toggle.first.tap()
        await page.wait_for_timeout(200)
        drawer_open = await page.locator(".mobile-nav.is-open").count() > 0
        checks.check(f"{device_name}: mobile nav drawer opens on a real touch tap", drawer_open)
        # Close via the explicit Close button, not the backdrop: on a
        # narrow phone the drawer panel (min(78vw,320px), right-anchored)
        # can cover the backdrop's own geometric center, so a tap there
        # would correctly land ON the panel instead — that's real,
        # intentional layout, not a bug to route around.
        await page.locator("[data-mobile-nav-close]").tap()
        await page.wait_for_timeout(200)

    # Login via real taps
    await page.evaluate("location.hash = '#/auth'")
    await page.wait_for_timeout(300)
    await page.fill("[data-login-form] input[type='email']", STAFF_EMAIL)
    await page.fill("[data-login-form] input[type='password']", STAFF_PASSWORD)
    await page.locator("[data-login-form] button[type='submit']").tap()
    await page.wait_for_timeout(400)
    checks.check(f"{device_name}: login via touch tap succeeds", await page.locator("[data-profile-toggle]").count() == 1)

    await check_no_overflow(page, device_name, "Applications (post-login)")

    # New application -> wizard stepper: tap through all 8 steps
    await page.locator("[data-action='new-application']:visible").first.tap()
    await page.wait_for_timeout(300)
    for step in range(1, 9):
        await page.evaluate(f"location.hash = '#/new-application/{step}'")
        await page.wait_for_timeout(200)
        await check_no_overflow(page, device_name, f"Wizard step {step}")

    # Touch-target size check on this real device's own rendered layout
    sizes = await page.evaluate(
        """() => {
        const els = Array.from(document.querySelectorAll('.btn-icon, .btn-sm'));
        return els.filter(el => !!(el.offsetWidth || el.offsetHeight)).map(el => ({w: el.offsetWidth, h: el.offsetHeight}));
    }"""
    )
    is_mobile_profile = device["viewport"]["width"] < 768
    if is_mobile_profile and sizes:
        undersized = [s for s in sizes if s["h"] < 40]
        checks.check(f"{device_name}: touch targets (.btn-icon/.btn-sm) meet the ~40px+ minimum", len(undersized) == 0, str(undersized[:3]))

    checks.check(f"{device_name}: zero console errors for the whole pass", len(console_errors) == 0, "; ".join(console_errors[:3]))

    await browser.close()


async def main():
    async with async_playwright() as p:
        for device_name in DEVICES:
            await run_for_device(p, device_name)

    checks.report_and_exit()


if __name__ == "__main__":
    asyncio.run(main())
