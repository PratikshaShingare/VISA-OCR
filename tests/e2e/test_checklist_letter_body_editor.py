"""
Checklist Letter (Required Document Letter) — Frontend rework, Phase 4
extension: the Word-like body editor proven on the Europe Cover Letter,
Hotel Blocking, the Authorization Letters, and the Invitation Letter,
extended to the Checklist Letter's own narrower scope for this document
type specifically: "editing only, with all existing design/functionality
preserved" (the user's own instruction). The checkbox-driven document
SELECTION mechanism is completely untouched here — only the 6 pieces of
generated WORDING become optionally editable (see
required_document_letter_engine.REQUIRED_DOCUMENT_LETTER_EDITABLE_FIELD_KEYS
/ js/checklist-letter.js's own REQUIRED_DOCUMENT_LETTER_EDITABLE_FIELDS):
the greeting sentence, the country/visa-type lines, the WHOLE variable-
length checklist bullet range as one field, the processing-time line and
the visa-fees line.

Exercises the REAL flow end to end: the editors are seeded via a real call
to /api/documents/required-document-letter/compose-fields, a real edit is
typed into a real Quill contenteditable surface, the edit is persisted into
this page's own module state (this document has no Application record —
see checklist-letter.js's own module docstring), and the resulting
"Generate & Preview" download is a real .docx produced by the real backend
with that edited wording actually substituted in — checked by parsing the
downloaded file with python-docx. Also confirms the checkbox-driven
document checklist itself still works completely unchanged alongside the
new editors (this document type's own narrower scope).

Requires: the static file server AND the backend both running (see
run_e2e_suite.py) — KHANNA_E2E_BASE/KHANNA_E2E_BACKEND_BASE override the
default localhost ports.
"""

import asyncio
import io

from docx import Document
from playwright.async_api import async_playwright

from _common import BASE, Checks, fresh_load_and_login, generate_and_download_docx

checks = Checks()


def _full_text(doc: Document) -> str:
    return "\n".join(p.text for p in doc.paragraphs)


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page(viewport={"width": 1280, "height": 1400})
        console_errors = []
        page.on("console", lambda m: console_errors.append(m.text) if m.type == "error" else None)
        page.on("pageerror", lambda e: console_errors.append(f"pageerror: {e}"))

        await fresh_load_and_login(page, base=BASE)

        await page.evaluate("location.hash = '#/checklist-letter'")
        await page.wait_for_timeout(500)

        # The editable-fields section shares the Generate button's own
        # readiness gate (country filled) — the ONLY field this document
        # type genuinely requires, since processing time/visa fees are
        # legitimately optional (an honest "_____" placeholder otherwise —
        # project rule 9/10). Exactly like every other document type's own
        # compact editors (see hotels.js's own mountHotelFieldEditors header
        # comment), a field seeds ONCE, the moment its gate flips true, and
        # does not keep re-syncing to a later keystroke into the fields
        # above it — so this fills every field THAT gate does not already
        # cover first, then fills country LAST, matching the realistic
        # order a staff member filling in supporting details before the
        # one truly required field would produce.
        r = "[data-checklist-letter-root]"
        await page.select_option(f"{r} [data-field='visaType']", "Tourist")
        await page.select_option(f"{r} [data-field='employmentStatus']", "Employed")
        await page.fill(f"{r} [data-field='visaFees']", "5,000")
        await page.locator(f"{r} [data-field='visaFees']").blur()
        await page.fill(f"{r} [data-field='country']", "Germany")
        await page.locator(f"{r} [data-field='country']").blur()
        await page.wait_for_timeout(800)  # let the async suggested-documents lookup settle first

        # ---------- The checkbox-driven document SELECTION mechanism is
        # untouched by this phase's own work — confirm it still behaves
        # exactly as before: at least one document got auto-suggested and
        # is checked. ----------
        doc_checkboxes = page.locator(f"{r} [data-rdl-document]")
        checked_count = 0
        for i in range(await doc_checkboxes.count()):
            if await doc_checkboxes.nth(i).is_checked():
                checked_count += 1
        checks.check("At least one document is auto-suggested/checked (selection UI unchanged)", checked_count > 0, str(checked_count))

        # ---------- Editable-fields section ----------
        editors = page.locator(f"{r} [data-rdl-field-editors] [data-rdl-field-editor]")
        checks.check(
            "All 6 Checklist Letter editable-field editors are mounted",
            await editors.count() == 6,
            str(await editors.count()),
        )

        country_editor = page.locator(f"{r} [data-rdl-field-editor='countryLine'] .ql-editor")
        seeded_text = ""
        for _ in range(40):
            if await country_editor.count():
                seeded_text = (await country_editor.inner_text()).strip()
                if seeded_text and seeded_text != "—":
                    break
            await page.wait_for_timeout(300)
        checks.check("countryLine field self-seeds with the real composed wording (no extra click)", "Germany" in seeded_text, seeded_text)

        checklist_editor = page.locator(f"{r} [data-rdl-field-editor='checklistItems'] .ql-editor")
        checklist_text = (await checklist_editor.inner_text()).strip()
        checks.check("checklistItems field seeds the real auto-generated document labels", "Passport Copy" in checklist_text, checklist_text)

        fees_editor = page.locator(f"{r} [data-rdl-field-editor='visaFees'] .ql-editor")
        fees_text = (await fees_editor.inner_text()).strip()
        checks.check("visaFees field seeds the real typed-in figure", "5,000" in fees_text, fees_text)

        # ---------- Edit the whole checklist range as one field ----------
        custom_checklist = "A completely staff-rewritten checklist line."
        await checklist_editor.click()
        await page.keyboard.press("Control+A")
        await page.keyboard.type(custom_checklist)
        await checklist_editor.blur()
        await page.wait_for_timeout(300)

        # ---------- Edit a single fixed field (greetingSentence) ----------
        custom_greeting = "A warm, staff-edited greeting for this enquiry."
        greeting_editor = page.locator(f"{r} [data-rdl-field-editor='greetingSentence'] .ql-editor")
        await greeting_editor.click()
        await page.keyboard.press("Control+A")
        await page.keyboard.type(custom_greeting)
        await greeting_editor.blur()
        await page.wait_for_timeout(300)

        gen_disabled = await page.get_attribute(f"{r} [data-action='generate-rdl']", "disabled")
        checks.check("Checklist Letter Generate enabled", gen_disabled is None)

        dl = await generate_and_download_docx(page, f"{r} [data-action='generate-rdl']", f"{r} [data-rdl-preview]")
        docx_path = await dl.path()
        with open(docx_path, "rb") as f:
            content = f.read()
        doc = Document(io.BytesIO(content))
        full_text = _full_text(doc)

        checks.check("The edited checklist line reached the downloaded .docx", custom_checklist in full_text)
        checks.check("The edited greeting sentence reached the downloaded .docx", custom_greeting in full_text)
        checks.check("The un-edited auto-generated documents are gone (replaced, not appended)", "Passport Copy" not in full_text)
        checks.check(
            "The un-edited fields (country/visa type/fees) are still correct alongside the two edited fields",
            "Country: Germany" in full_text and "5,000" in full_text,
        )
        checks.check("Fixed closing wording untouched (project rule 5)", "Warm Regards," in full_text)

        # ---------- "Reset" restores the auto-generated wording ----------
        reset_btn = page.locator(f"{r} [data-rdl-field-editor='greetingSentence'] [data-body-editor-action='reset']")
        await reset_btn.click()
        await page.wait_for_timeout(400)
        reset_text = (await page.locator(f"{r} [data-rdl-field-editor='greetingSentence'] .ql-editor").inner_text()).strip()
        checks.check(
            "'Reset to auto-generated text' restores the real composed greetingSentence",
            "Thank you for your inquiry" in reset_text and custom_greeting not in reset_text,
            reset_text,
        )

        checks.check("Zero console errors throughout", len(console_errors) == 0, "; ".join(console_errors[:8]))

        await browser.close()
    checks.report_and_exit()


if __name__ == "__main__":
    asyncio.run(main())
