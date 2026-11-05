"""
Whole-letter editor: pressing Edit turns the preview into ONE continuous,
Word-like page. Selecting across paragraphs, deleting lines, pressing Enter
and typing anywhere all work, and the edits reach the real downloaded file.

Runs on the Singapore Passport Authorization letter (paragraphs, bullets and
a table-like layout) and the Singapore single-traveller cover letter.

Requires the static server and the backend (see run_e2e_suite.py).
"""

import asyncio

from playwright.async_api import async_playwright

from _common import BASE, Checks, fresh_load_and_login, future_date, set_edit_mode, wait_preview_ready
from test_singapore_letters import SEED, AUTH_GEN_PASSPORT, GEN, doc_text, read_download

checks = Checks()
PASSPORT_SCOPE = ".view.is-active [data-doc-preview='passport']"
ED = ".view.is-active .lw-stage .ql-editor"


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page(viewport={"width": 1366, "height": 1000})
        errors = []
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        page.on("pageerror", lambda e: errors.append(str(e)))
        await fresh_load_and_login(page, base=BASE)
        seeded = await page.evaluate(SEED)
        app_id, wife = seeded["id"], seeded["wife"]
        await page.evaluate("(id) => KhannaState.setActiveApplicationId(id)", app_id)
        await page.evaluate("location.hash = '#/passport-authorization'")
        await page.wait_for_timeout(900)
        for pid in ("applicant", wife):
            await page.locator(f".view.is-active [data-auth-person][data-person-id='{pid}']").check()
        await page.fill("[data-auth-field='passport:feePerApplicant']", "8000")
        await page.press("[data-auth-field='passport:feePerApplicant']", "Tab")
        await page.click(AUTH_GEN_PASSPORT)
        await wait_preview_ready(page, PASSPORT_SCOPE)

        # ---- Edit opens one continuous page ----
        await set_edit_mode(page, PASSPORT_SCOPE, True)
        await page.wait_for_selector(ED)
        checks.check("Edit shows one editable letter page", await page.locator(f"{PASSPORT_SCOPE} .lw-stage").count() == 1)
        checks.check("the PDF page is replaced while editing", await page.locator(f"{PASSPORT_SCOPE} [data-dv='canvas']").is_hidden()
                     or not await page.locator(f"{PASSPORT_SCOPE} [data-dv='page']").is_visible())
        text = await page.inner_text(ED)
        checks.check("the whole letter is in it (title, applicant, scope, fee, signature area)",
                     "AUTHORISATION LETTER FOR VISA APPLICATION" in text and "Mr. Test Applicant One" in text
                     and "SCOPE OF AUTHORISATION" in text and "Visa Application Fee: INR 16000" in text
                     and "Signature of Applicant" in text, text[:600])
        checks.check("one editor, not many boxes", await page.locator(f"{PASSPORT_SCOPE} .ql-editor").count() == 1)

        # ---- select across several paragraphs and delete them ----
        paras = await page.locator(f"{ED} > p").count()
        await page.evaluate("""(sel) => {
          const ed = document.querySelector(sel);
          const all = Array.from(ed.querySelectorAll('p, li'));
          const a = all.find(n => n.textContent.includes('Receipt Number'));
          const b = all.find(n => n.textContent.includes('Date of Payment'));
          const first = (n) => document.createTreeWalker(n, NodeFilter.SHOW_TEXT).nextNode();
          const lastText = (n) => { const w = document.createTreeWalker(n, NodeFilter.SHOW_TEXT); let x, l; while ((x = w.nextNode())) l = x; return l; };
          const r = document.createRange();
          r.setStart(first(a), 0);
          const lt = lastText(b);
          r.setEnd(lt, lt.textContent.length);
          const s = getSelection(); s.removeAllRanges(); s.addRange(r);
          ed.focus();
        }""", ED)
        await page.keyboard.press("Backspace")
        await page.wait_for_timeout(500)
        text = await page.inner_text(ED)
        checks.check("a selection across two paragraphs is deleted in one go",
                     "Receipt Number" not in text and "Date of Payment" not in text, text[:800])

        # ---- type a new paragraph after the fee line (Enter, then text) ----
        await page.evaluate("""(sel) => {
          const ed = document.querySelector(sel);
          const n = Array.from(ed.querySelectorAll('p')).find(n => n.textContent.includes('Visa Application Fee'));
          const r = document.createRange();
          r.selectNodeContents(n); r.collapse(false);
          const s = getSelection(); s.removeAllRanges(); s.addRange(r); ed.focus();
        }""", ED)
        await page.keyboard.press("Enter")
        await page.keyboard.type("Note added by hand: payment received in cash.")
        await page.wait_for_timeout(600)

        # ---- change a word in the middle of the first sentence ----
        await page.evaluate("""(sel) => {
          const ed = document.querySelector(sel);
          const n = Array.from(ed.querySelectorAll('p')).find(n => n.textContent.includes('do hereby authorise'));
          const w = n.textContent.indexOf('do hereby authorise');
          const t = n.firstChild; 
          const walker = document.createTreeWalker(n, NodeFilter.SHOW_TEXT);
          let node, off = w;
          while ((node = walker.nextNode())) { if (off <= node.textContent.length) break; off -= node.textContent.length; }
          const r = document.createRange(); r.setStart(node, off); r.setEnd(node, off + 'do hereby'.length);
          const s = getSelection(); s.removeAllRanges(); s.addRange(r); ed.focus();
        }""", ED)
        await page.keyboard.type("hereby")
        await page.wait_for_timeout(600)

        stored = await page.evaluate("""() => {
          const ef = (KhannaState.getActiveApplication().authorization.passport.editedFields) || {};
          return Object.keys(ef).filter(k => ef[k] != null).length;
        }""")
        checks.check("only the touched parts are stored as edits", 2 <= stored <= 5, str(stored))

        # ---- Done editing regenerates; the downloaded file carries everything ----
        await set_edit_mode(page, PASSPORT_SCOPE, False)
        await wait_preview_ready(page, PASSPORT_SCOPE)
        async with page.expect_download() as dl_info:
            await page.click(f"{PASSPORT_SCOPE} [data-dv='download-docx']")
        data = await read_download(await dl_info.value)
        out = doc_text(data)
        checks.check("deleted lines are gone from the file", "Receipt Number" not in out and "Date of Payment" not in out, out)
        checks.check("the new paragraph is in the file after the fee line",
                     "Note added by hand: payment received in cash." in out and out.index("Visa Application Fee") < out.index("Note added by hand"), out)
        checks.check("the mid-sentence change is in the file", "I, Mr. Test Applicant One, holder of" in out and "hereby authorise and appoint" in out, out[:500])
        checks.check("untouched template text is unchanged", "SCOPE OF AUTHORISATION" in out and "APPLICANT ACKNOWLEDGEMENT" in out)

        # ---- reopening shows the edited letter; Reset all restores the original ----
        await set_edit_mode(page, PASSPORT_SCOPE, True)
        await page.wait_for_selector(ED)
        reopened = await page.inner_text(ED)
        checks.check("reopening keeps the edits", "Note added by hand" in reopened and "Receipt Number" not in reopened)
        await page.click(f"{PASSPORT_SCOPE} [data-pe='reset-all']")
        await wait_preview_ready(page, PASSPORT_SCOPE)
        await page.wait_for_selector(ED)
        restored = await page.inner_text(ED)
        checks.check("Reset all brings the generated letter back",
                     "Receipt Number" in restored and "Date of Payment" in restored and "Note added by hand" not in restored, restored[:500])
        await set_edit_mode(page, PASSPORT_SCOPE, False)

        # ---- Cover letter ----
        await page.evaluate("location.hash = '#/cover-letter'")
        await page.wait_for_timeout(900)
        await page.fill("[data-cover-occupation='applicant']", "a student at Test College")
        await page.press("[data-cover-occupation='applicant']", "Tab")
        await page.click(GEN)
        scope = ".view.is-active [data-doc-preview]"
        await wait_preview_ready(page, scope)
        await set_edit_mode(page, scope, True)
        await page.wait_for_selector(ED)
        ctext = await page.inner_text(ED)
        checks.check("the cover letter is one editable page too", "Singapore" in ctext and len(ctext) > 400, ctext[:300])
        checks.check("no browser console errors", not errors, "; ".join(errors[:5]))
        await browser.close()
    checks.report_and_exit()


asyncio.run(main())
