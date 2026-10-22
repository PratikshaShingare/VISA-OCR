"""
Europe Cover Letter — Phase 4 "Word-like" body editor proof of concept.

Frontend rework, Phase 4: staff can now fine-tune the wording of the
Europe Cover Letter's own three free-composed body paragraphs in a real
rich-text editor (Quill, vendored at assets/vendor/quill/ — see
js/cover-letter.js's own header comment for why), without touching the
header/footer/margins/fonts or any other paragraph of the real reference
template (project rule 5). This is deliberately scoped to Europe only —
Japan and Singapore are unaffected (the user's own "proof of concept
first, one document type" rollout choice).

Exercises the REAL flow end to end: the editor is seeded via a real call
to /api/documents/cover-letter/compose-body (never placeholder/fake
text — project rule 9), a real edit is typed into the real Quill
contenteditable surface, and the resulting "Generate & Preview" download
is a real .docx produced by the real backend with that edited wording
actually substituted in — checked by parsing the downloaded file with
python-docx, not by inspecting the page DOM alone.

Requires: the static file server AND the backend both running (see
run_e2e_suite.py) — KHANNA_E2E_BASE/KHANNA_E2E_BACKEND_BASE override the
default localhost ports.
"""

import asyncio
import io

from docx import Document
from playwright.async_api import async_playwright

from _common import (
    BASE,
    Checks,
    fill_ocr_person,
    fresh_load_and_login,
    generate_and_download_docx,
    select_cover_letter_country,
    start_guided_wizard_application,
)

checks = Checks()

COVER_FIELDS = {
    "#cover-top-recipientText": "Consulate General of France, Mumbai",
    "#cover-top-destinationCountry": "France",
    "#cover-top-travelStartDate": "2026-12-01",
    "#cover-top-travelEndDate": "2026-12-15",
    "#cover-top-fundingArrangement": "Applicant",
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

        # --- The body editor mounts and seeds itself with REAL composed text ---
        quill_editor = page.locator("[data-cover-body-editor-mount] .ql-editor")
        seeded_text = ""
        for _ in range(40):
            if await quill_editor.count():
                seeded_text = (await quill_editor.inner_text()).strip()
                if seeded_text:
                    break
            await page.wait_for_timeout(300)
        checks.check("Body editor (Quill) mounted and self-seeded without any extra click", len(seeded_text) > 50, seeded_text[:120])
        checks.check(
            "Seeded wording is the real composed text (contains the real applicant's name)",
            applicant_name in seeded_text,
            f"applicant_name={applicant_name!r}",
        )
        checks.check(
            "Seeded wording matches the known real Europe Cover Letter opening sentence",
            "would like to visit your admired country" in seeded_text,
        )

        # --- A real edit, typed into the real contenteditable surface ---
        await quill_editor.click()
        await page.keyboard.press("Control+A")
        await page.keyboard.type("E2E EDITED WORDING for the Europe Cover Letter body — Phase 4 regression check.")
        await page.wait_for_timeout(200)

        # --- The shared "Generate & Preview" download must carry the edit ---
        dl = await generate_and_download_docx(page, "[data-action='generate-cover-letter']", "[data-doc-preview='']")
        checks.check("Real .docx download triggered", dl.suggested_filename.endswith(".docx"), dl.suggested_filename)
        docx_bytes = await dl.path()
        with open(docx_bytes, "rb") as f:
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
            applicant_name in full_text,
        )
        checks.check(
            "Funding arrangement paragraph (also after the body range) is still correct",
            COVER_FIELDS["#cover-top-fundingArrangement"] in full_text,
        )

        # --- Reset restores the real auto-generated wording ---
        await page.click("[data-body-editor-action='reset']")
        for _ in range(20):
            reset_text = (await quill_editor.inner_text()).strip()
            if "would like to visit your admired country" in reset_text:
                break
            await page.wait_for_timeout(300)
        checks.check(
            "“Reset to auto-generated text” restores the real composed wording",
            "would like to visit your admired country" in reset_text,
            reset_text[:150],
        )

        # --- Japan/Singapore are unaffected by this Europe-only POC ---
        await select_cover_letter_country(page, "Japan")
        await page.wait_for_timeout(500)
        japan_editor_visible = await page.locator("[data-cover-body-editor-mount] .body-editor").count()
        checks.check("Body editor does NOT appear for Japan (Europe-only proof of concept)", japan_editor_visible == 0)

        checks.check("Zero console errors throughout", len(console_errors) == 0, "; ".join(console_errors[:8]))

        await browser.close()

    checks.report_and_exit()


if __name__ == "__main__":
    asyncio.run(main())
