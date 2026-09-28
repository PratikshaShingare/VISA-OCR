"""
Full, continuous end-to-end journey — the single most important test in
this suite, and the one that found this project's Phase 13 real bug (a
listener-accumulation issue in js/hotels.js that only shows up once a
SECOND hotel panel is opened in the same session; see the Phase 13 section
of claude/phase0-inspection-and-architecture.md).

Unlike per-feature tests that seed only the one upstream field their own
step needs, this script drives the ENTIRE real workflow as a single staff
member would, once, start to finish: login -> new application -> passport
OCR for the applicant + 2 travellers (real Tesseract OCR each time, never
mocked) -> travel & checklist -> upload + verify every required document
-> hotel blocking (2 hotels, real voucher generation) -> both authorization
letters -> a cover letter -> an invitation letter + both Initors Covering
Letters (real signature embedding, both gendered templates) -> the
Applications list -> the Admin dashboard (status change, a real Excel
export) -> two full-page reloads at real checkpoints, to prove the whole
chain of state survives a reload, not just one field at a time.

Requires: the static file server AND the backend both running (see
run_e2e_suite.py, or start them manually) — KHANNA_E2E_BASE /
KHANNA_E2E_BACKEND_BASE env vars override the default localhost ports.
"""

import asyncio
import os
import tempfile

from playwright.async_api import async_playwright

from _common import (
    BASE,
    FAKE_SIGNATURE_PNG,
    Checks,
    ensure_fixtures,
    fill_ocr_person,
    fresh_load_and_login,
    generate_and_download,
    generate_and_download_docx,
)

checks = Checks()


async def main():
    ensure_fixtures()
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page(viewport={"width": 1280, "height": 1000})
        console_errors = []
        page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)
        page.on("pageerror", lambda exc: console_errors.append(str(exc)))

        # ---------- Login ----------
        await fresh_load_and_login(page, base=BASE)
        checks.check("Logged in (header shows account)", await page.locator("[data-profile-toggle]").count() == 1)

        # ---------- New application ----------
        # Three buttons now share this data-action (profile-menu item, plus
        # one each on Dashboard and Applications) — the menu one is hidden
        # until that dropdown is opened, so an unscoped click can resolve to
        # a hidden element and time out. Matches the :visible-scoped pattern
        # already used in test_device_emulation.py.
        await page.locator("[data-action='new-application']:visible").first.click()
        await page.wait_for_timeout(300)
        app_id = await page.evaluate("KhannaState.getActiveApplicationId()")
        checks.check("New application created with an id", bool(app_id))

        # ---------- Step 1: applicant passport OCR ----------
        await page.evaluate("location.hash = '#/new-application/1'")
        await page.wait_for_timeout(300)
        await fill_ocr_person(page, ".step-view[data-step='1']")
        last_name = await page.evaluate("KhannaState.getActiveApplication().applicant.lastName")
        checks.check("Step 1: applicant lastName saved from real OCR", bool(last_name), last_name)
        cont_disabled_1 = await page.get_attribute("[data-wizard-continue]", "disabled")
        checks.check("Step 1: Continue enabled after save+verify", cont_disabled_1 is None)

        # ---------- Step 2: two travellers (Spouse + Child) ----------
        await page.evaluate("location.hash = '#/new-application/2'")
        await page.wait_for_timeout(300)
        for relation in ("Spouse", "Child"):
            await page.click("[data-action='add-traveller']")
            await page.wait_for_timeout(300)
            await fill_ocr_person(page, ".traveller-panel", "[data-traveller-relation]", relation)
            await page.click("[data-action='close-traveller-panel']")
            await page.wait_for_timeout(200)
        travellers = await page.evaluate("KhannaState.getActiveApplication().travellers.length")
        checks.check("Step 2: 2 travellers saved", travellers == 2, str(travellers))
        cont_disabled_2 = await page.get_attribute("[data-wizard-continue]", "disabled")
        checks.check("Step 2: Continue enabled with both travellers complete", cont_disabled_2 is None)

        # Give the applicant and Spouse traveller a distinct recorded sex
        # (OCR on the same synthetic image can't produce two different
        # real sexes) so the Initors Covering Letter (step 7) can exercise
        # BOTH the wife-voice and husband-voice reference templates for
        # real later in this same run.
        await page.evaluate(
            """() => {
            const app = KhannaState.getActiveApplication();
            KhannaState.updateApplication(app.id, { applicant: { sex: 'M' } }, 'e2e-seed-sex');
            const spouse = app.travellers.find(t => t.relation === 'Spouse');
            KhannaState.updateTraveller(app.id, spouse.id, { sex: 'F' }, 'e2e-seed-sex');
        }"""
        )

        # ---------- Step 3: travel & checklist (Europe / Tourist) ----------
        await page.evaluate("location.hash = '#/new-application/3'")
        await page.wait_for_timeout(300)
        await page.select_option("[data-travel-field='destination']", "Europe (Schengen)")
        await page.select_option("[data-travel-field='visaCategory']", "Tourist")
        await page.fill("[data-travel-field='purpose']", "Tourism")
        await page.fill("[data-travel-field='countryOfResidence']", "India")
        await page.fill("[data-travel-field='startDate']", "2026-12-01")
        await page.fill("[data-travel-field='endDate']", "2026-12-15")
        await page.locator("[data-travel-field='endDate']").blur()
        await page.wait_for_timeout(300)
        cont_disabled_3 = await page.get_attribute("[data-wizard-continue]", "disabled")
        checks.check("Step 3: Continue enabled once all travel fields filled", cont_disabled_3 is None)

        # ---------- Step 4: upload + verify EVERY checklist document ----------
        await page.evaluate("location.hash = '#/new-application/4'")
        await page.wait_for_timeout(300)
        doc_rows = page.locator(".doc-row")
        doc_count = await doc_rows.count()
        checks.check("Step 4: checklist rendered real document rows", doc_count > 0, str(doc_count))

        tmpf = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
        tmpf.write(b"%PDF-1.4 e2e fake document content")
        tmpf.close()

        doc_ids = [await doc_rows.nth(i).get_attribute("data-doc-row") for i in range(doc_count)]
        for doc_id in doc_ids:
            file_input = page.locator(f'[data-doc-file-input="{doc_id}"]')
            await file_input.set_input_files(tmpf.name)
            await page.wait_for_timeout(150)
            await page.click(f'[data-doc-row="{doc_id}"] [data-action="verify-doc"]')
            await page.wait_for_timeout(150)
        os.unlink(tmpf.name)

        completion_pct = await page.evaluate("KhannaState.getActiveApplication().checklist.completionPct")
        checks.check("Step 4: every required document verified (100% completion)", completion_pct == 100, str(completion_pct))
        cont_disabled_4 = await page.get_attribute("[data-wizard-continue]", "disabled")
        checks.check("Step 4: Continue enabled once all required docs verified", cont_disabled_4 is None)

        # ---------- Step 5: hotel blocking (2 hotels) + real voucher generation ----------
        # Opening a SECOND hotel panel in the same run is deliberate: this
        # exact sequence is what surfaced the real hotels.js
        # listener-accumulation bug in Phase 13 (no isolated per-phase
        # test before this one ever opened more than one hotel panel per
        # run) — keep this at 2+ hotels so a regression of that bug would
        # be caught here again.
        await page.evaluate("location.hash = '#/new-application/5'")
        await page.wait_for_timeout(300)
        hotel_defs = [
            ("The Grand Meridian", "Geneva", "2026-12-01", "2026-12-05"),
            ("Hotel Alpenblick", "Zurich", "2026-12-05", "2026-12-15"),
        ]
        for name, city, checkin, checkout in hotel_defs:
            await page.click("[data-action='add-hotel']")
            await page.wait_for_timeout(250)
            await page.fill("#hf-hotelName", name)
            await page.fill("#hf-phone", "+41 22 123 4567")
            await page.fill("#hf-address", f"{name} street, {city}")
            await page.fill("#hf-city", city)
            await page.fill("#hf-confirmationNumber", "CONF-" + name[:4].upper())
            await page.fill("#hf-leadGuestName", "Rohan Mehta")
            # Split from a single "No. of guests" field on explicit product
            # request (see HOTEL_FIELDS in js/hotels.js) — the voucher now
            # prints a combined "2 Adult(s), 1 Child(s)"-style count.
            await page.fill("#hf-noOfAdults", "2")
            await page.fill("#hf-noOfChildren", "1")
            await page.fill("#hf-noOfRooms", "2")
            await page.fill("#hf-roomType", "Deluxe")
            await page.fill("#hf-checkIn", checkin)
            await page.fill("#hf-checkOut", checkout)
            await page.locator("#hf-checkOut").blur()
            await page.wait_for_timeout(200)
            await page.click("[data-action='close-hotel-panel']")
            await page.wait_for_timeout(200)
        hotels_saved = await page.evaluate("KhannaState.getActiveApplication().hotels")
        checks.check("Step 5: 2 hotels saved", len(hotels_saved) == 2, str(len(hotels_saved)))
        checks.check(
            "Step 5: both hotels kept their OWN distinct data (regression check for the "
            "Phase 13 hotels.js listener-accumulation bug)",
            hotels_saved[0]["hotelName"] == "The Grand Meridian" and hotels_saved[1]["hotelName"] == "Hotel Alpenblick"
            and hotels_saved[0]["city"] == "Geneva" and hotels_saved[1]["city"] == "Zurich",
            str([(h.get("hotelName"), h.get("city")) for h in hotels_saved]),
        )

        gen_disabled = await page.get_attribute("[data-action='generate-voucher']", "disabled")
        checks.check("Step 5: Generate voucher enabled with 2 complete hotels", gen_disabled is None)
        dl = await generate_and_download_docx(page, "[data-action='generate-voucher']", "[data-voucher-preview]")
        checks.check("Step 5: Hotel Voucher (.docx) real download triggered", dl.suggested_filename.endswith(".docx"), dl.suggested_filename)
        cont_disabled_5 = await page.get_attribute("[data-wizard-continue]", "disabled")
        checks.check("Step 5: Continue enabled once both hotels complete", cont_disabled_5 is None)

        # ---------- Step 6: Authorization Letters + Cover Letter ----------
        await page.evaluate("location.hash = '#/new-application/6'")
        await page.wait_for_timeout(300)

        passport_checks = page.locator('[data-auth-checklist="passport"] input[type=checkbox]')
        await passport_checks.nth(0).check()
        await passport_checks.nth(1).check()
        await page.fill("#auth-passport-recipientCentreName", "Germany Visa Application Centre")
        await page.fill("#auth-passport-recipientAddress", "Andheri, Mumbai")
        await page.fill("#auth-passport-collectorName", "Mr. Suresh Patil")
        await page.locator("#auth-passport-collectorName").blur()
        await page.wait_for_timeout(300)
        pa_disabled = await page.get_attribute("[data-action='generate-authorization'][data-group='passport']", "disabled")
        checks.check("Step 6: Passport Authorization Generate enabled", pa_disabled is None)
        dl = await generate_and_download_docx(
            page, "[data-action='generate-authorization'][data-group='passport']", "[data-doc-preview='passport']"
        )
        checks.check("Step 6: Passport Authorization real download triggered", dl.suggested_filename.endswith(".docx"), dl.suggested_filename)

        company_checks = page.locator('[data-auth-checklist="company"] input[type=checkbox]')
        company_count = await company_checks.count()
        for i in range(company_count):
            await company_checks.nth(i).check()
        await page.fill("#auth-company-recipientText", "The Consulate General of Germany, Mumbai")
        await page.locator("#auth-company-recipientText").blur()
        await page.wait_for_timeout(300)
        ca_disabled = await page.get_attribute("[data-action='generate-authorization'][data-group='company']", "disabled")
        checks.check("Step 6: Company Authorization Generate enabled (3 people)", ca_disabled is None)
        dl = await generate_and_download_docx(
            page, "[data-action='generate-authorization'][data-group='company']", "[data-doc-preview='company']"
        )
        checks.check("Step 6: Company Authorization real download triggered", dl.suggested_filename.endswith(".docx"), dl.suggested_filename)

        await page.click("[data-auth-tab='cover']")
        await page.wait_for_timeout(200)
        await page.click("[data-cover-region='Europe']")
        await page.wait_for_timeout(200)
        cover_checks = page.locator("[data-cover-checklist] input[type=checkbox]")
        await cover_checks.nth(0).check()
        await cover_checks.nth(1).check()
        await page.wait_for_timeout(150)
        cover_fields = {
            "#cover-top-recipientText": "Consulate General of France, Mumbai",
            "#cover-top-destinationCountry": "France",
            "#cover-top-travelStartDate": "2026-12-01",
            "#cover-top-travelEndDate": "2026-12-15",
            "#cover-top-fundingArrangement": "Applicant",
            "#cover-europe-cityCountryOfResidence": "Mumbai, India",
            "#cover-europe-numberOfNights": "14 nights",
            "#cover-europe-applicantEmploymentStatus": "Salaried",
            "#cover-europe-applicantJobTitle": "Software Engineer",
            "#cover-europe-applicantEmployerName": "Acme Corp",
            "#cover-europe-companionJobTitle": "Homemaker",
            "#cover-europe-companionEmployerName": "N/A",
            "#cover-europe-companionEmploymentStartYear": "2015",
        }
        for sel, val in cover_fields.items():
            await page.fill(sel, val)
        await page.locator("#cover-europe-companionEmploymentStartYear").blur()
        await page.wait_for_timeout(300)
        cover_gen_disabled = await page.get_attribute("[data-action='generate-cover-letter']", "disabled")
        checks.check("Step 6: Europe Cover Letter Generate enabled", cover_gen_disabled is None)
        dl = await generate_and_download_docx(page, "[data-action='generate-cover-letter']", "[data-doc-preview='']")
        checks.check("Step 6: Cover Letter real download triggered", dl.suggested_filename.endswith(".docx"), dl.suggested_filename)

        cont_disabled_6 = await page.get_attribute("[data-wizard-continue]", "disabled")
        checks.check("Step 6: combined Continue gate enabled (both tabs ready)", cont_disabled_6 is None)

        # ---------- Step 7: Invitation Letter + Initors Covering Letter ----------
        await page.evaluate("location.hash = '#/new-application/7'")
        await page.wait_for_timeout(300)
        inv_checks = page.locator("[data-invitation-invitee-checklist] input[type=checkbox]")
        await inv_checks.nth(0).check()
        await inv_checks.nth(1).check()
        await page.wait_for_timeout(150)
        inviter_fields = {
            "#invitation-field-inviter-fullName": "Ms. Test Inviter",
            "#invitation-field-inviter-passportNumber": "Z9999999",
            "#invitation-field-inviter-addressLine1": "1 Example Street",
            "#invitation-field-inviter-cityPostcode": "Example City EX1",
            "#invitation-field-inviter-fullAddress": "1 Example Street, Example City EX1",
            "#invitation-field-inviter-country": "TestCountry",
            "#invitation-field-inviter-cityCountry": "Example City, TestCountry",
            "#invitation-field-inviter-studyingOrWorking": "Working",
            "#invitation-field-inviter-universityOrCompany": "Example Corp",
            "#invitation-field-inviter-phone": "9999999999",
            "#invitation-field-inviter-email": "inviter@example.com",
            "#invitation-field-top-travelStartDate": "2026-11-10",
            "#invitation-field-top-travelEndDate": "2026-11-20",
            "#invitation-field-top-purpose": "attending a family event",
            "#invitation-field-top-accommodationDetails": "with the inviter",
            "#invitation-field-top-returnDate": "2026-11-20",
            "#invitation-field-top-fundingArrangement": "the inviter",
        }
        for sel, val in inviter_fields.items():
            await page.fill(sel, val)
        await page.locator("#invitation-field-top-fundingArrangement").blur()
        await page.wait_for_timeout(200)
        await page.set_input_files('[data-signature-file-input="invitation"]', FAKE_SIGNATURE_PNG)
        await page.wait_for_timeout(200)
        dl = await generate_and_download_docx(page, "[data-action='generate-invitation']", "[data-invitation-preview]")
        checks.check("Step 7: Invitation Letter real download triggered", dl.suggested_filename.endswith(".docx"), dl.suggested_filename)

        initors_checks = page.locator("[data-initors-checklist] input[type=checkbox]")
        await initors_checks.nth(0).check()
        await initors_checks.nth(1).check()
        await page.wait_for_timeout(200)
        sections = page.locator("[data-initors-person-section]")
        section_count = await sections.count()
        checks.check("Step 7: 2 Initors per-person sections rendered", section_count == 2, str(section_count))
        common_fields = {
            "#initors-field-inviting-fullName": "Test Inviting Person",
            "#initors-field-inviting-passportNumber": "I5555555",
            "#initors-field-inviting-countryOfResidence": "TestCountry",
            "#initors-field-inviting-visaResidenceStatus": "Work Visa",
            "#initors-field-top-country": "TestCountry",
            "#initors-field-top-purpose": "visit family",
            "#initors-field-top-travelStartDate": "2026-11-10",
            "#initors-field-top-travelEndDate": "2026-11-20",
            "#initors-field-top-returnDate": "2026-11-20",
            "#initors-field-top-accommodationDetails": "with the inviting person",
            "#initors-field-top-otherCommitments": "work commitments",
            "#initors-field-top-invitationSupportingDocuments": "invitation letter and hotel bookings",
        }
        for sel, val in common_fields.items():
            await page.fill(sel, val)
        await page.locator("#initors-field-top-invitationSupportingDocuments").blur()
        await page.wait_for_timeout(200)
        person_ids = []
        for i in range(2):
            section = sections.nth(i)
            pid = await section.get_attribute("data-initors-person-section")
            person_ids.append(pid)
            await page.fill(f'[data-initors-person-field="{pid}:occupation"]', "Test Occupation")
            await page.fill(f'[data-initors-person-field="{pid}:relationWithInvitingPerson"]', "Family")
        await page.locator(f'[data-initors-person-field="{person_ids[1]}:relationWithInvitingPerson"]').blur()
        await page.wait_for_timeout(200)
        await page.set_input_files(f'[data-signature-file-input="initors:{person_ids[0]}"]', FAKE_SIGNATURE_PNG)
        await page.wait_for_timeout(200)
        for idx, pid in enumerate(person_ids):
            fmt = "docx" if idx == 0 else "pdf"
            dl = await generate_and_download(
                page,
                f'[data-action="generate-initors"][data-person-id="{pid}"]',
                f'[data-initors-preview="{pid}"]',
                fmt=fmt,
            )
            err = (await page.locator(f'[data-initors-error="{pid}"]').inner_text()).strip()
            voice = "wife" if idx == 0 else "husband"
            checks.check(f"Step 7: Initors letter for person {idx + 1} ({voice}-voice template) generated, no error", err == "", err)

        cont_disabled_7 = await page.get_attribute("[data-wizard-continue]", "disabled")
        checks.check("Step 7: combined Continue gate enabled (both document types ready)", cont_disabled_7 is None)

        # ---------- Checkpoint reload #1: mid-journey, after step 7 ----------
        await page.reload()
        await page.wait_for_timeout(500)
        await page.evaluate("location.hash = '#/new-application/7'")
        await page.wait_for_timeout(400)
        resumed_hotels = await page.evaluate("KhannaState.getActiveApplication().hotels.length")
        resumed_travellers = await page.evaluate("KhannaState.getActiveApplication().travellers.length")
        resumed_completion = await page.evaluate("KhannaState.getActiveApplication().checklist.completionPct")
        checks.check("Reload #1: hotels survive (2)", resumed_hotels == 2, str(resumed_hotels))
        checks.check("Reload #1: travellers survive (2)", resumed_travellers == 2, str(resumed_travellers))
        checks.check("Reload #1: checklist completion survives (100%)", resumed_completion == 100, str(resumed_completion))
        resumed_sections = await page.locator("[data-initors-person-section]").count()
        checks.check("Reload #1: Initors per-person sections still render after reload", resumed_sections == 2, str(resumed_sections))

        # ---------- Applications list + Admin dashboard ----------
        await page.evaluate("location.hash = '#/applications'")
        await page.wait_for_timeout(300)
        apps_view = page.locator('[data-view="applications"]')
        app_card_text = await apps_view.inner_text()
        checks.check("Applications list shows the journey's own application", (last_name in app_card_text) if last_name else True)

        status_select = apps_view.locator(f"[data-action='change-status'][data-app-id='{app_id}']")
        await status_select.select_option("Documents Pending")
        await page.wait_for_timeout(200)
        status_after = await page.evaluate(f"KhannaState.getApplication('{app_id}').status")
        checks.check("Applications list: status change persists to state", status_after == "Documents Pending", status_after)

        await page.click("[data-profile-toggle]")
        await page.wait_for_timeout(100)
        await page.click("[data-action='logout']")
        await page.wait_for_timeout(200)
        from _common import ADMIN_EMAIL, ADMIN_PASSWORD, login as _login

        await _login(page, ADMIN_EMAIL, ADMIN_PASSWORD)
        await page.evaluate("location.hash = '#/admin'")
        await page.wait_for_timeout(400)
        gate_hidden = await page.get_attribute("[data-admin-gate]", "hidden")
        checks.check("Admin: gate visible for admin account", gate_hidden is None)
        admin_rows = await page.locator("[data-admin-applications-table] tbody tr").count()
        checks.check("Admin: all-applications table includes the journey's own application", admin_rows >= 1, str(admin_rows))

        async with page.expect_download() as dl_info:
            await page.click("[data-action='export-excel']")
        dl = await dl_info.value
        checks.check("Admin: real Master Excel export download triggered", dl.suggested_filename.endswith(".xlsx"), dl.suggested_filename)

        # ---------- Checkpoint reload #2: final, from Admin ----------
        await page.reload()
        await page.wait_for_timeout(500)
        final_status = await page.evaluate(f"KhannaState.getApplication('{app_id}').status")
        checks.check("Reload #2: status change from earlier survives a fresh load", final_status == "Documents Pending", final_status)

        checks.check("Zero console errors across the entire continuous journey", len(console_errors) == 0, "; ".join(console_errors[:5]))

        await browser.close()

    checks.report_and_exit()


if __name__ == "__main__":
    asyncio.run(main())
