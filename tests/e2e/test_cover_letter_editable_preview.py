"""
Editable preview — the Europe Cover Letter.

Fill the form, press Generate & Preview: the Preview section shows the real
generated page; its Edit button makes the letter's values editable right on
that page (no separate "Letter wording" form). Checks the real flow end to end
(real backend, real LibreOffice PDF, real downloads) — values open seeded with
the generator's own wording, edits persist, Download/Print regenerate with the
edit included, fixed template text is untouched (project rule 5), "Reset all"
restores the auto-generated wording.

Requires: the static file server AND the backend both running (see
run_e2e_suite.py).
"""

import asyncio
import io

from docx import Document
from playwright.async_api import async_playwright

from _common import (
    BASE,
    Checks,
    commit_preview_edit,
    future_date,
    edit_value_on_preview,
    fill_ocr_person,
    fresh_load_and_login,
    select_cover_letter_country,
    start_guided_wizard_application,
    wait_preview_ready,
)

checks = Checks()

COVER_FIELDS = {
    "#cover-top-consulateName": "The Consulate General of France",
    "#cover-top-destinationCountry": "France",
    "#cover-top-travelStartDate": future_date(40),
    "#cover-top-travelEndDate": future_date(54),
    "#cover-europe-cityOfResidence": "Mumbai",
    "#cover-europe-countryOfResidence": "India",
    "#cover-europe-numberOfNights": "14 nights",
    "#cover-europe-applicantEmploymentStatus": "Salaried",
    "#cover-europe-applicantJobTitle": "Software Engineer",
    "#cover-europe-applicantEmployerName": "Acme Corp",
    "#cover-europe-companionJobTitle": "Homemaker",
    "#cover-europe-companionEmployerName": "N/A",
    "#cover-europe-companionEmploymentStartYear": "2015",
}


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

        await page.evaluate("location.hash = '#/new-application/2'")
        await page.wait_for_timeout(300)
        await page.click("[data-action='add-traveller']")
        await page.wait_for_timeout(300)
        await fill_ocr_person(page, ".traveller-panel", "[data-traveller-relation]", "Spouse")
        await page.click("[data-action='close-traveller-panel']")
        await page.wait_for_timeout(200)

        await page.evaluate("location.hash = '#/new-application/6'")
        await page.wait_for_timeout(300)
        await page.click("[data-auth-tab='cover']")
        await page.wait_for_timeout(200)
        await select_cover_letter_country(page, "France")
        await page.wait_for_timeout(200)
        cover_checks = page.locator("[data-cover-checklist] input[type=checkbox]")
        await cover_checks.nth(0).check()
        await cover_checks.nth(1).check()
        await page.wait_for_timeout(150)
        await page.select_option("#cover-top-fundingType", "self")
        for sel, val in COVER_FIELDS.items():
            await page.fill(sel, val)
        await page.locator("#cover-europe-companionEmploymentStartYear").blur()
        await page.wait_for_timeout(300)

        checks.check(
            "Europe Cover Letter Generate enabled once every required field is filled",
            await page.get_attribute("[data-action='generate-cover-letter']", "disabled") is None,
        )

        applicant_name = (
            await page.evaluate(
                "(KhannaState.getActiveApplication().applicant.firstName || '') + ' ' + "
                "(KhannaState.getActiveApplication().applicant.lastName || '')"
            )
        ).strip()

        checks.check(
            "The old 'Letter wording (editable)' section is gone from the Europe Cover Letter card",
            await page.locator("[data-cover-body-editor-mount]").count() == 0
            and "Letter wording" not in await page.inner_text("[data-cover-letter-card]"),
        )

        # --- Generate & Preview, then edit the body ON the preview ---
        scope = "[data-doc-preview='']"
        await page.click("[data-action='generate-cover-letter']")
        await wait_preview_ready(page, scope)
        edit_btn = page.locator(f"{scope} [data-dv='edit-toggle']")
        checks.check("The preview has an Edit button", await edit_btn.count() == 1 and await edit_btn.is_enabled())
        await edit_btn.click()
        await page.wait_for_timeout(300)
        n_fields = await page.locator(f"{scope} .pe-field").count()
        checks.check("Edit mode makes the whole cover letter editable (body plus every other text block)", n_fields >= 1, str(n_fields))

        seeded_text = await edit_value_on_preview(
            page, scope, "body", "E2E EDITED WORDING for the Europe Cover Letter body — Phase 4 regression check."
        )
        checks.check("The body opens seeded with the real composed wording", len(seeded_text) > 50, seeded_text[:120])
        checks.check(
            "Seeded wording is the real composed text (contains the real applicant's name)",
            applicant_name.title() in seeded_text,  # letters use ordinary capitalisation (passport stays in capitals)
            f"applicant_name={applicant_name!r}",
        )
        checks.check(
            "Seeded wording matches the known real Europe Cover Letter opening sentence",
            "would like to visit your admired country" in seeded_text,
        )
        await commit_preview_edit(page, scope)
        persisted = await page.evaluate("((KhannaState.getActiveApplication().coverLetter || {}).editedFields || {}).body || null")
        checks.check("The edit is persisted into the application", persisted is not None and "E2E EDITED WORDING" in persisted, str(persisted))

        # --- Download carries the edit (regenerates first) ---
        async with page.expect_download() as dl_info:
            await page.click(f"{scope} [data-dv='download-docx']")
        dl = await dl_info.value
        checks.check("Real .docx download triggered", dl.suggested_filename.endswith(".docx"), dl.suggested_filename)
        with open(await dl.path(), "rb") as f:
            content = f.read()
        paragraphs = Document(io.BytesIO(content)).paragraphs
        full_text = "\n".join(p.text for p in paragraphs)

        checks.check("Downloaded .docx contains the staff's real edited wording", "E2E EDITED WORDING" in full_text)
        checks.check(
            "Downloaded .docx no longer contains the original auto-composed opening sentence",
            "would like to visit your admired country" not in full_text,
        )
        checks.check(
            "Signature block AFTER the shrunken/grown body range is still correct "
            "(the stable-paragraph-reference regression this proof of concept exists to guard against)",
            applicant_name.title() in full_text,
        )
        checks.check(
            "Funding arrangement paragraph (also after the body range) is still correct",
            "ourselves" in full_text,
        )

        # --- Reset all restores the real auto-generated wording ---
        await wait_preview_ready(page, scope)
        await page.click(f"{scope} [data-pe='reset-all']")
        await wait_preview_ready(page, scope)
        cleared = await page.evaluate("((KhannaState.getActiveApplication().coverLetter || {}).editedFields || {}).body")
        checks.check("Reset all clears the saved edit", cleared is None, str(cleared))
        async with page.expect_download() as dl_info:
            await page.click(f"{scope} [data-dv='download-docx']")
        dl = await dl_info.value
        with open(await dl.path(), "rb") as f:
            text_after = "\n".join(p.text for p in Document(io.BytesIO(f.read())).paragraphs)
        checks.check(
            "After Reset all the document has the real composed wording again",
            "would like to visit your admired country" in text_after and "E2E EDITED WORDING" not in text_after,
        )

        # --- A document with no editable wording says so honestly ---
        # (Japan, Singapore and Initors previews are mounted without an editor
        # and with a reason; this mounts exactly that and checks the button.)
        info = await page.evaluate(
            """() => { const host = document.createElement('div'); document.body.appendChild(host);
                 const h = KhannaDocumentViewer.mount(host, {title: 'x', editUnavailableReason: 'No free wording here.'});
                 const b = host.querySelector('[data-dv=edit-toggle]');
                 const out = {hidden: b.hidden, disabled: b.disabled, title: b.title};
                 h.destroy(); host.remove(); return out; }"""
        )
        checks.check(
            "A preview without editable wording shows a disabled Edit button that says why",
            info["hidden"] is False and info["disabled"] is True and "No free wording here." in info["title"],
            str(info),
        )

        checks.check("Zero console errors throughout", len(console_errors) == 0, "; ".join(console_errors[:8]))

        await browser.close()

    checks.report_and_exit()


if __name__ == "__main__":
    asyncio.run(main())
