"""Frontend rework, Phase E — "group of applicants" (Company Authorization
Letter). Confirms, against the real running app (never mocked):

  * An applicant can be added directly by full name + passport number alone
    (js/authorization.js's manualApplicantsFor/getCompanyPeople) — no full
    traveller/OCR record required, matching this letter's own real
    requirement (backend/python/authorization_letter_engine.py's
    _company_applicant_line_text only ever reads fullName/passportNumber).
  * That manual applicant is auto-selected, appears in the checklist with
    its own remove ("x") button (a sibling of its .auth-person-row
    <label>, never a nested descendant — a click inside a <label>,
    including on a nested button, also toggles that label's own checkbox),
    and can be removed without disturbing anyone else.
  * The current selection can be saved as a named, reusable group
    (js/applicant-groups.js), which then shows up in the "Saved groups"
    dropdown.
  * Applying a saved group (the explicit "Apply" button, not an
    immediate on-change side effect — picking a group only decides which
    one Apply/Delete act on next, since applying one rebuilds the whole
    card and would otherwise reset the very <select> a follow-up "delete"
    needs to read) restores its members even after they were removed.
  * The real generated .docx actually contains the manually-added
    applicants' real name and passport number (project rule 9 — never
    claim this works without checking the real downloaded file).
  * A saved group can be deleted and disappears from the dropdown.

Run directly: `python3 test_applicant_groups.py` (servers already up), or
via run_e2e_suite.py.
"""

import asyncio
import subprocess
import sys

from playwright.async_api import async_playwright

from _common import (
    BASE,
    Checks,
    fill_ocr_person,
    fresh_load_and_login,
    pick_company_consulate,
    generate_and_download_docx,
    start_guided_wizard_application,
)

checks = Checks()


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page(viewport={"width": 1280, "height": 1100})
        console_errors = []
        page.on("console", lambda m: console_errors.append(m.text) if m.type == "error" else None)
        page.on("pageerror", lambda e: console_errors.append(f"pageerror: {e}"))

        await fresh_load_and_login(page, base=BASE)
        await start_guided_wizard_application(page)
        await page.wait_for_timeout(300)
        await page.evaluate("location.hash = '#/new-application/1'")
        await page.wait_for_timeout(300)
        await fill_ocr_person(page, ".step-view[data-step='1']")

        await page.evaluate("location.hash = '#/new-application/6'")
        await page.wait_for_timeout(300)
        await page.click("[data-auth-tab='authorization']")
        await page.wait_for_timeout(200)

        company = page.locator("[data-company-auth-card]")

        # 1. Add two manual applicants (name + passport number only).
        await company.locator('[data-manual-applicant-field="fullName"]').fill("Rakesh Sharma")
        await company.locator('[data-manual-applicant-field="passportNumber"]').fill("P1111111")
        await company.locator('[data-action="add-manual-applicant"]').click()
        await page.wait_for_timeout(200)

        await company.locator('[data-manual-applicant-field="fullName"]').fill("Sunita Sharma")
        await company.locator('[data-manual-applicant-field="passportNumber"]').fill("P2222222")
        await company.locator('[data-action="add-manual-applicant"]').click()
        await page.wait_for_timeout(200)

        rows = company.locator("[data-auth-checklist='company'] .auth-person-row__name")
        names = await rows.all_text_contents()
        checks.check("Both manually-added applicants appear in the checklist", "Rakesh Sharma" in names and "Sunita Sharma" in names)

        checked_count = await company.locator("[data-auth-checklist='company'] input[type=checkbox]:checked").count()
        checks.check("Both manually-added applicants are auto-selected", checked_count >= 2)

        # 2. Save the current selection as a named group.
        await company.locator("[data-group-name-input]").fill("Sharma Family")
        await company.locator("[data-action='save-applicant-group']").click()
        await page.wait_for_timeout(200)

        select = company.locator("[data-action='pick-applicant-group']")
        options = await select.locator("option").all_text_contents()
        checks.check("Saved group appears in the 'Saved groups' dropdown", any("Sharma Family" in o for o in options))

        # 3. Remove one manually-added applicant via its own remove button
        # (not the checkbox) — must not also flip the checkbox it sits next to.
        remove_btn = company.locator('[data-action="remove-manual-applicant"]').first
        await remove_btn.click()
        await page.wait_for_timeout(200)
        names_after_remove = await company.locator("[data-auth-checklist='company'] .auth-person-row__name").all_text_contents()
        checks.check(
            "Removed applicant no longer appears in the checklist",
            len([n for n in names_after_remove if n in ("Rakesh Sharma", "Sunita Sharma")]) == 1,
        )

        # 4. Re-applying the saved group (via the explicit Apply button)
        # should bring both back.
        await select.select_option(label=[o for o in options if "Sharma Family" in o][0])
        await company.locator("[data-action='apply-applicant-group']").click()
        await page.wait_for_timeout(300)
        names_reapplied = await company.locator("[data-auth-checklist='company'] .auth-person-row__name").all_text_contents()
        checks.check("Applying the saved group brings both applicants back", "Rakesh Sharma" in names_reapplied and "Sunita Sharma" in names_reapplied)

        checked_count2 = await company.locator("[data-auth-checklist='company'] input[type=checkbox]:checked").count()
        checks.check("Both group members are selected after applying the group", checked_count2 >= 2)

        # 5. The real generated .docx actually contains these applicants.
        await pick_company_consulate(page, "Germany")
        generate_btn = company.locator("[data-action='generate-authorization']")
        checks.check("Generate button enabled with group-applied manual applicants", await generate_btn.get_attribute("disabled") is None)

        download = await generate_and_download_docx(
            page, "[data-company-auth-card] [data-action='generate-authorization']", "[data-doc-preview='company']"
        )
        path = await download.path()
        checks.check("Real .docx download triggered with manually-added applicants", path is not None)

        if path:
            out = subprocess.run(
                [
                    "python3",
                    "-c",
                    "from docx import Document\n"
                    f"d = Document({str(path)!r})\n"
                    "text = '\\n'.join(p.text for p in d.paragraphs)\n"
                    "print('Rakesh Sharma' in text and 'P1111111' in text and 'Sunita Sharma' in text and 'P2222222' in text)",
                ],
                capture_output=True,
                text=True,
            )
            checks.check("Downloaded .docx contains both manual applicants' real name+passport", out.stdout.strip() == "True")

        # 6. Delete the saved group.
        select_now = company.locator("[data-action='pick-applicant-group']")
        option_pairs = await select_now.locator("option").evaluate_all("els => els.map(e => [e.value, e.textContent])")
        target_value = [v for v, t in option_pairs if "Sharma Family" in t][0]
        await select_now.select_option(value=target_value)
        await page.wait_for_timeout(150)
        await company.locator("[data-action='delete-applicant-group']").click()
        await page.wait_for_timeout(300)
        select_count_after = await company.locator("[data-action='pick-applicant-group']").count()
        options_after_delete = (
            await company.locator("[data-action='pick-applicant-group']").locator("option").all_text_contents() if select_count_after else []
        )
        checks.check("Deleted group no longer appears in the dropdown", not any("Sharma Family" in o for o in options_after_delete))

        checks.check("Zero console errors throughout", len(console_errors) == 0, "\n".join(console_errors))

        await browser.close()
        checks.report_and_exit()


if __name__ == "__main__":
    asyncio.run(main())
