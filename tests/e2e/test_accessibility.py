"""
Accessibility spot-check: real keyboard-only interaction (Tab/Shift+Tab/
Enter/Space), not just clicks, plus checks for label/for wiring,
aria-labels on icon-only controls, and visible focus indication — across
the login form, the wizard stepper, a document upload row, and the Admin
status-select.

Requires: the static file server AND the backend both running (see
run_e2e_suite.py) — KHANNA_E2E_BASE overrides the default localhost port.
"""

import asyncio
import tempfile

from playwright.async_api import async_playwright

from _common import ADMIN_EMAIL, ADMIN_PASSWORD, BASE, Checks, STAFF_EMAIL, STAFF_PASSWORD

checks = Checks()


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page(viewport={"width": 1280, "height": 1000})
        console_errors = []
        page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)

        await page.goto(BASE + "/index.html")
        await page.evaluate("localStorage.clear()")
        await page.reload()
        await page.evaluate("location.hash = '#/auth'")
        await page.wait_for_timeout(300)

        # ---- Keyboard-only login ----
        email_input = page.locator("[data-login-form] input[type='email']")
        await email_input.click()  # focus the first field the way Tab would land on it
        await page.keyboard.type(STAFF_EMAIL)
        await page.keyboard.press("Tab")
        focused_is_password = await page.evaluate(
            "document.activeElement.matches(\"[data-login-form] input[type='password']\")"
        )
        checks.check("Tab from email moves focus to password field", focused_is_password)
        await page.keyboard.type(STAFF_PASSWORD)
        await page.keyboard.press("Tab")
        focused_after_password = await page.evaluate("document.activeElement.tagName + ':' + (document.activeElement.type||'')")
        await page.keyboard.press("Enter")
        await page.wait_for_timeout(400)
        logged_in = await page.locator("[data-profile-toggle]").count() == 1
        checks.check("Keyboard-only login (type, Tab, type, Enter on submit button) succeeds", logged_in, focused_after_password)

        # ---- Focus is visible (outline) once a keyboard Tab lands on a control ----
        await page.keyboard.press("Tab")
        outline_style = await page.evaluate("getComputedStyle(document.activeElement).outlineStyle")
        checks.check("A keyboard-focused element gets a real visible outline (:focus-visible)", outline_style not in ("none", ""), outline_style)

        # ---- New application, step 1: label/for wiring + keyboard reachability ----
        # Scoped to a visible match — three buttons now share this
        # data-action and one (the profile-menu item) is hidden by default.
        await page.locator("[data-action='new-application']:visible").first.click()
        await page.wait_for_timeout(300)
        await page.evaluate("location.hash = '#/new-application/1'")
        await page.wait_for_timeout(300)

        upload_trigger_reachable = await page.evaluate(
            """() => {
            const btn = document.querySelector("[data-passport-browse]");
            return !!btn && btn.tabIndex !== -1 && (btn.tagName === 'BUTTON' || btn.getAttribute('role') === 'button');
        }"""
        )
        checks.check("Step 1 upload trigger is a real, keyboard-reachable control", upload_trigger_reachable)

        # ---- Wizard stepper: every step tab has an accessible name ----
        stepper_items_missing_text = await page.evaluate(
            """() => Array.from(document.querySelectorAll('.stepper-nav__item')).filter(el => !el.textContent.trim()).length"""
        )
        checks.check("Every stepper tab has real, non-empty accessible text (not icon-only)", stepper_items_missing_text == 0, str(stepper_items_missing_text))

        # ---- All icon-only buttons app-wide carry an aria-label ----
        icon_btns_missing_label = await page.evaluate(
            """() => Array.from(document.querySelectorAll('.btn-icon')).filter(el => !el.getAttribute('aria-label') && !el.textContent.trim()).length"""
        )
        checks.check("Every icon-only .btn-icon has an aria-label (checked on live, rendered DOM)", icon_btns_missing_label == 0, str(icon_btns_missing_label))

        # ---- Every <label for=...> resolves to a real element with that id, on live DOM ----
        dangling_labels = await page.evaluate(
            """() => Array.from(document.querySelectorAll('label[for]')).filter(l => !document.getElementById(l.getAttribute('for'))).map(l => l.getAttribute('for'))"""
        )
        checks.check("Every <label for> on step 1's live DOM resolves to a real element id", len(dangling_labels) == 0, str(dangling_labels))

        # ---- Heading structure sanity: exactly one VISIBLE <h1> ----
        # Every top-level .view stays mounted in the DOM at once (only
        # .is-active toggles display) — intentional architecture — so a
        # raw DOM-wide h1 count always reads one per view. What matters
        # for a screen reader is how many are actually exposed (not
        # display:none) at once.
        visible_h1_count = await page.evaluate(
            """() => Array.from(document.querySelectorAll('h1')).filter(el => !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length)).length"""
        )
        checks.check("Exactly one VISIBLE <h1> at a time (others are display:none, not exposed to AT)", visible_h1_count == 1, str(visible_h1_count))

        # ---- Step 4: document row Verify/Reject buttons are real buttons with text (not icon-only, div-based) ----
        await page.evaluate("location.hash = '#/new-application/3'")
        await page.wait_for_timeout(200)
        await page.select_option("[data-travel-field='destination']", "Europe (Schengen)")
        await page.select_option("[data-travel-field='visaCategory']", "Tourist")
        await page.wait_for_timeout(200)
        await page.evaluate("location.hash = '#/new-application/4'")
        await page.wait_for_timeout(300)
        first_doc_id = await page.locator(".doc-row").first.get_attribute("data-doc-row")
        tmpf = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
        tmpf.write(b"%PDF-1.4 a11y test file")
        tmpf.close()
        await page.locator(f'[data-doc-file-input="{first_doc_id}"]').set_input_files(tmpf.name)
        await page.wait_for_timeout(300)
        verify_btn = page.locator(f'[data-doc-row="{first_doc_id}"] [data-action="verify-doc"]')
        verify_is_button_with_text = await verify_btn.evaluate("el => el.tagName === 'BUTTON' && el.textContent.trim().length > 0")
        checks.check("Document row Verify action is a real <button> with visible text", verify_is_button_with_text)

        # Operate it via keyboard (focus + Enter), not a click
        await verify_btn.focus()
        await page.keyboard.press("Enter")
        await page.wait_for_timeout(300)
        status_after_keyboard_verify = await page.inner_text(f'[data-doc-row="{first_doc_id}"] .badge')
        checks.check("Verify action activates via keyboard Enter (not mouse-only)", "Verified" in status_after_keyboard_verify, status_after_keyboard_verify)

        # ---- Admin: status-select is a real, keyboard-operable <select> with an accessible name ----
        await page.click("[data-profile-toggle]")
        await page.wait_for_timeout(100)
        await page.click("[data-action='logout']")
        await page.wait_for_timeout(200)
        await page.evaluate("location.hash = '#/auth'")
        await page.wait_for_timeout(200)
        await page.fill("[data-login-form] input[type='email']", ADMIN_EMAIL)
        await page.fill("[data-login-form] input[type='password']", ADMIN_PASSWORD)
        await page.click("[data-login-form] button[type='submit']")
        await page.wait_for_timeout(300)
        await page.evaluate("location.hash = '#/applications'")
        await page.wait_for_timeout(300)
        select_is_real = await page.evaluate(
            """() => { const s = document.querySelector("[data-view='applications'] [data-action='change-status']"); return !!s && s.tagName === 'SELECT'; }"""
        )
        checks.check("Status control is a real <select> (native keyboard support), not a styled div", select_is_real)

        checks.check("Zero console errors across the accessibility pass", len(console_errors) == 0, "; ".join(console_errors[:5]))

        await browser.close()

    checks.report_and_exit()


if __name__ == "__main__":
    asyncio.run(main())
