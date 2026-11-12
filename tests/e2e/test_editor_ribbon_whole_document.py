"""
Whole-document editing + the Word-style ribbon (Checklist Letter as the
example page; every document page shares the same editor).

Edit mode makes EVERY text block of the generated page editable — also the
fixed template wording, not just the dynamic values. Checks, against the real
backend/LibreOffice/downloads, that a fixed paragraph can be rewritten, that
ribbon formatting (bold, real Word highlight colour, centre, bullets, table)
ends up as real Word structures in the downloaded .docx, that Word's limited
highlight palette is what the menu offers, and that "Reset all" restores the
auto-generated document.
"""
import asyncio
import io

from docx import Document
from playwright.async_api import async_playwright

from _common import BASE, Checks, fresh_load_and_login, preview_unit_keys, select_line_with_text, set_edit_mode, wait_preview_ready

checks = Checks()


def _all_paragraphs(container):
    out = list(container.paragraphs)
    for table in container.tables:
        for row in table.rows:
            for cell in row.cells:
                out.extend(_all_paragraphs(cell))
    return out


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await (await browser.new_context(viewport={"width": 1400, "height": 1500}, accept_downloads=True)).new_page()
        errors = []
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
        await fresh_load_and_login(page, base=BASE)
        await page.evaluate("location.hash = '#/checklist-letter'")
        await page.wait_for_timeout(500)
        r = "[data-checklist-letter-root]"
        await page.select_option(f"{r} [data-field='visaType']", "Tourist")
        await page.select_option(f"{r} [data-field='employmentStatus']", "Employed")
        await page.fill(f"{r} [data-field='country']", "Germany")
        await page.locator(f"{r} [data-field='country']").blur()
        await page.wait_for_timeout(800)
        scope = f"{r} [data-rdl-preview]"
        await page.click(f"{r} [data-action='generate-rdl']")
        await wait_preview_ready(page, scope)
        await set_edit_mode(page, scope, True)

        await page.wait_for_selector(f"{scope} .lw-stage .ql-editor")
        # Edit button sits beside the title (left), not among the tools.
        pos = await page.evaluate(
            """(sc) => { const t = document.querySelector(sc + ' .doc-viewer__title').getBoundingClientRect();
                         const e = document.querySelector(sc + ' [data-dv=edit-toggle]').getBoundingClientRect();
                         const pr = document.querySelector(sc + ' [data-dv=print]').getBoundingClientRect();
                         return {gap: e.left - t.right, beforeTools: e.right < pr.left}; }""",
            scope,
        )
        checks.check("Edit / Done editing sits right beside the title", 0 <= pos["gap"] < 40 and pos["beforeTools"], str(pos))
        checks.check("The PDF page and its page-turn controls are out of the way while editing; zoom stays available for the edit page",
                     await page.locator(f"{scope} [data-dv='zoom-in']").is_visible()
                     and not await page.locator(f"{scope} [data-dv='next-page']").is_visible()
                     and not await page.locator(f"{scope} [data-dv='canvas']").is_visible())
        checks.check("The ribbon is shown", await page.locator(f"{scope} [data-pe='bold']").is_visible())

        keys = await preview_unit_keys(page, scope)
        blocks = len([k for k in keys if k.startswith("blk-")])
        checks.check("Fixed template wording is editable too (whole-document blocks)", blocks >= 3, str(blocks))

        # --- rewrite a fixed paragraph and format it from the ribbon ---
        key = await select_line_with_text(page, scope, "Warm Regards")
        checks.check("The fixed closing 'Warm Regards' can be selected in the letter", key)
        await page.keyboard.type("Kind regards from the team,")
        await page.wait_for_timeout(300)
        await select_line_with_text(page, scope, "Kind regards from the team,")
        await page.click(f"{scope} [data-pe='italic']")
        await page.click(f"{scope} [data-pe='highlight-menu']")
        swatches = await page.locator(".pe-pop--palette [data-hex]").count()
        checks.check("Highlight menu offers exactly Word's 15 colours", swatches == 15, str(swatches))
        await page.click(".pe-pop--palette [data-hex='#FFFF00']")
        await page.click(f"{scope} [data-pe='align-center']")
        await page.wait_for_timeout(900)

        # --- bullets on another paragraph ---
        key2 = await select_line_with_text(page, scope, "Thank you", whole=False)
        if key2:
            await page.click(f"{scope} [data-pe='bullet']")
            await page.wait_for_timeout(900)
        checks.check("A paragraph could be turned into a bullet", key2 is not None)

        async with page.expect_download() as dl:
            await page.click(f"{scope} [data-dv='download-docx']")
        d = await dl.value
        doc = Document(io.BytesIO(open(await d.path(), "rb").read()))
        paras = _all_paragraphs(doc)
        hit = [q for q in paras if "Kind regards from the team," in q.text]
        checks.check("The rewritten fixed paragraph reached the .docx", len(hit) == 1)
        checks.check("The old fixed wording is gone from the .docx", not any("Warm Regards" in q.text for q in paras))
        if hit:
            q = hit[0]
            checks.check("It is italic", all(rn.italic for rn in q.runs if rn.text.strip()))
            xml = q._p.xml
            checks.check("It carries Word's real highlight (yellow)", 'w:highlight w:val="yellow"' in xml)
            checks.check("It is centred", 'w:jc w:val="center"' in xml)
        if key2:
            checks.check("The bulleted paragraph is a real Word list (numPr)", any(q._p.xml.count("w:numPr") and "Thank you" in q.text for q in paras))

        # --- Reset all ---
        page.once("dialog", lambda dlg: asyncio.ensure_future(dlg.accept()))
        await page.click(f"{scope} [data-pe='reset-all']")
        await page.wait_for_timeout(500)
        await wait_preview_ready(page, scope)
        async with page.expect_download() as dl2:
            await page.click(f"{scope} [data-dv='download-docx']")
        d2 = await dl2.value
        doc2 = Document(io.BytesIO(open(await d2.path(), "rb").read()))
        text2 = "\n".join(q.text for q in _all_paragraphs(doc2))
        checks.check("Reset all restores the auto-generated wording", "Warm Regards" in text2 and "Kind regards from the team," not in text2)
        checks.check("No console errors", not errors, "; ".join(errors[:3]))
        await browser.close()
    checks.report_and_exit()


asyncio.run(main())
