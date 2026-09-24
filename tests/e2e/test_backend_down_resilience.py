"""
Backend-down honest-failure path.

Every document-generation feature in this app calls the local Python
backend (js/core/api.js). If that backend isn't running — the single most
likely real-world failure mode for a per-machine local backend like this
one — the UI must show an honest "couldn't reach the backend" message and
let the staff member try again, never hang on "Generating…" forever, and
never silently pretend to succeed (project rule 9 — never fake
functionality).

Unlike every other script in this suite, this one REQUIRES the backend to
be stopped before it runs (the static file server must still be running).
run_e2e_suite.py handles that sequencing automatically; run standalone
only after confirming the backend is actually down (e.g. `curl -s -o
/dev/null -w '%{http_code}' http://127.0.0.1:8000/api/health` returns
"000").
"""

import asyncio

from playwright.async_api import async_playwright

from _common import BASE, Checks, STAFF_EMAIL, STAFF_PASSWORD

checks = Checks()


async def _expect_honest_failure(page, generate_selector: str, error_selector: str, button_selector: str | None = None):
    button_selector = button_selector or generate_selector
    original_text = (await page.locator(button_selector).inner_text()).strip()
    await page.click(generate_selector)
    await page.wait_for_timeout(1500)

    error_text = (await page.locator(error_selector).inner_text()).strip()
    honest = any(word in error_text.lower() for word in ("reach", "backend", "connect", "unavailable"))
    checks.check(f"{generate_selector}: an honest backend-unreachable message is shown", honest, error_text)

    btn_disabled = await page.get_attribute(button_selector, "disabled")
    checks.check(f"{generate_selector}: button re-enabled after the failure (not stuck disabled)", btn_disabled is None)

    btn_text_after = (await page.locator(button_selector).inner_text()).strip()
    checks.check(f"{generate_selector}: button text reverted to its normal label (not stuck on 'Generating…')", btn_text_after == original_text, btn_text_after)


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page(viewport={"width": 1280, "height": 1000})
        await page.goto(BASE + "/index.html")
        await page.evaluate("localStorage.clear()")
        await page.reload()
        await page.evaluate("location.hash = '#/auth'")
        await page.wait_for_timeout(200)
        await page.fill("[data-login-form] input[type='email']", STAFF_EMAIL)
        await page.fill("[data-login-form] input[type='password']", STAFF_PASSWORD)
        await page.click("[data-login-form] button[type='submit']")
        await page.wait_for_timeout(300)
        await page.click("[data-action='new-application']")
        await page.wait_for_timeout(300)

        # Seed enough state directly (rather than re-running real OCR,
        # which needs the backend that this test deliberately keeps down)
        # to reach each document-generation feature's "ready to generate"
        # state.
        await page.evaluate(
            """() => {
            const app = KhannaState.getActiveApplication();
            KhannaState.updateApplication(app.id, {
                applicant: {
                    salutation: 'Ms', firstName: 'Anita', lastName: 'Rao', fullName: 'Anita Rao',
                    sex: 'F', passport: { current: { number: 'Z9990001' } },
                    contact: { phone: '9998887770', email: 'anita.rao@example.com' }
                },
                travel: { destination: 'Europe (Schengen)', visaCategory: 'Tourist' }
            }, 'e2e-down-seed');
            const spouse = KhannaState.addTraveller(app.id, 'Spouse');
            KhannaState.updateTraveller(app.id, spouse.id, {
                fullName: 'Rohan Rao', passport: { current: { number: 'Z9990002' } }
            }, 'e2e-down-seed');
        }"""
        )

        # ---- Hotel Voucher (Step 5) ----
        await page.evaluate("location.hash = '#/new-application/5'")
        await page.wait_for_timeout(300)
        await page.click("[data-action='add-hotel']")
        await page.wait_for_timeout(250)
        await page.fill("#hf-hotelName", "Down-Test Hotel")
        await page.fill("#hf-city", "Geneva")
        await page.fill("#hf-checkIn", "2026-12-01")
        await page.fill("#hf-checkOut", "2026-12-05")
        await page.locator("#hf-checkOut").blur()
        await page.wait_for_timeout(200)
        await page.click("[data-action='close-hotel-panel']")
        await page.wait_for_timeout(200)
        await _expect_honest_failure(
            page,
            "[data-action='generate-voucher'][data-format='docx']",
            "[data-voucher-error]",
        )

        # ---- Passport Authorization (Step 6) ----
        await page.evaluate("location.hash = '#/new-application/6'")
        await page.wait_for_timeout(300)
        await page.locator('[data-auth-checklist="passport"] input[type=checkbox]').first.check()
        await page.fill("#auth-passport-recipientCentreName", "Test Visa Application Centre")
        await page.fill("#auth-passport-collectorName", "Ms. Test Collector")
        await page.locator("#auth-passport-collectorName").blur()
        await page.wait_for_timeout(200)
        await _expect_honest_failure(
            page,
            "[data-action='generate-authorization'][data-group='passport'][data-format='docx']",
            "[data-auth-error='passport']",
        )

        # ---- Europe Cover Letter (Step 6) ----
        await page.click("[data-auth-tab='cover']")
        await page.wait_for_timeout(150)
        await page.click("[data-cover-region='Europe']")
        await page.wait_for_timeout(150)
        cover_checkboxes = page.locator("[data-cover-checklist] input[type=checkbox]")
        await cover_checkboxes.nth(0).check()
        await cover_checkboxes.nth(1).check()
        for sel, val in [
            ("#cover-top-recipientText", "Consulate General of France, Mumbai"),
            ("#cover-top-destinationCountry", "France"),
            ("#cover-top-travelStartDate", "2026-11-10"),
            ("#cover-top-travelEndDate", "2026-11-20"),
            ("#cover-top-fundingArrangement", "Applicant"),
            ("#cover-europe-cityCountryOfResidence", "Mumbai, India"),
            ("#cover-europe-numberOfNights", "10 nights"),
            ("#cover-europe-applicantEmploymentStatus", "Salaried"),
            ("#cover-europe-applicantJobTitle", "Software Engineer"),
            ("#cover-europe-applicantEmployerName", "Acme Corp"),
            ("#cover-europe-companionJobTitle", "Designer"),
            ("#cover-europe-companionEmployerName", "Beta LLC"),
            ("#cover-europe-companionEmploymentStartYear", "2015"),
        ]:
            await page.fill(sel, val)
        await page.locator("#cover-europe-companionEmploymentStartYear").blur()
        await page.wait_for_timeout(200)
        await _expect_honest_failure(
            page,
            "[data-action='generate-cover-letter'][data-format='docx']",
            "[data-cover-error]",
        )

        # ---- Admin Excel export ----
        await page.click("[data-profile-toggle]")
        await page.wait_for_timeout(100)
        await page.click("[data-action='logout']")
        await page.wait_for_timeout(200)
        await page.evaluate("location.hash = '#/auth'")
        await page.wait_for_timeout(200)
        from _common import ADMIN_EMAIL, ADMIN_PASSWORD

        await page.fill("[data-login-form] input[type='email']", ADMIN_EMAIL)
        await page.fill("[data-login-form] input[type='password']", ADMIN_PASSWORD)
        await page.click("[data-login-form] button[type='submit']")
        await page.wait_for_timeout(300)
        await page.evaluate("location.hash = '#/admin'")
        await page.wait_for_timeout(400)
        await _expect_honest_failure(
            page,
            "[data-action='export-excel']",
            "[data-admin-export-notice]",
        )

        await browser.close()

    checks.report_and_exit()


if __name__ == "__main__":
    asyncio.run(main())
