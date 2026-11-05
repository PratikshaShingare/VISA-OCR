"""
Accounts: one merged "Profile & Settings" page, backend-checked logins, and
admin-only staff creation.

  * Wrong password is refused by the backend; the right one signs in.
  * Profile & Settings is a single page (old #/settings address lands on it)
    with name edit, read-only email/role, change-password and theme toggle.
  * A staff member never sees the "Staff accounts" panel; the backend also
    refuses a staff token on the admin endpoints (403), so hiding is not the
    only protection.
  * Admin creates a staff login -> that person can sign in, change their own
    password (old one stops working), admin resets it, admin removes them
    (they can no longer sign in).
  * Admin cannot remove their own account from the UI.

Requires the static server and the backend (see run_e2e_suite.py). Creates
a uniquely-named staff account; the suite points the backend at a throwaway
accounts database, and the account is removed again at the end anyway.
"""

import asyncio
import time

from playwright.async_api import async_playwright

from _common import (
    ADMIN_EMAIL, ADMIN_PASSWORD, BASE, BACKEND_BASE, STAFF_EMAIL, STAFF_PASSWORD,
    Checks, fresh_load_and_login, login,
)

checks = Checks()

NEW_EMAIL = f"e2e.staff.{int(time.time())}@example.com"
PW1 = "First-pass-123"
PW2 = "Second-pass-456"
PW3 = "Third-pass-789"


async def is_signed_in(page):
    return await page.evaluate("() => { var p = document.querySelector('.profile-menu[data-auth-logged-in]'); return !!p && !p.hidden; }")


async def logout(page):
    await page.click("[data-profile-toggle]")
    await page.click("[data-action='logout']")
    await page.wait_for_timeout(300)


async def api_status(page, method, path, token, body=None):
    return await page.evaluate(
        """async ([url, method, token, body]) => {
            const r = await fetch(url, { method, headers: Object.assign({ 'Authorization': 'Bearer ' + token }, body ? { 'Content-Type': 'application/json' } : {}), body: body ? JSON.stringify(body) : undefined });
            return r.status;
        }""",
        [BACKEND_BASE + path, method, token, body],
    )


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page(viewport={"width": 1280, "height": 900})
        page.on("dialog", lambda d: asyncio.ensure_future(d.accept()))
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))

        # ---- login is checked by the backend ----
        await page.goto(BASE + "/index.html")
        await page.evaluate("localStorage.clear()")
        await page.reload()
        await login(page, STAFF_EMAIL, "definitely-wrong-password")
        checks.check("Wrong password does not sign in", not await is_signed_in(page))
        checks.check("Wrong password shows an error", await page.locator("[data-login-error]").evaluate("e => e.style.display") == "flex")
        stored = await page.evaluate("localStorage.getItem('khanna_session_v1')")
        checks.check("No session stored after a failed login", stored is None)

        await login(page, STAFF_EMAIL, STAFF_PASSWORD)
        checks.check("Correct password signs in", await is_signed_in(page))
        stored = await page.evaluate("localStorage.getItem('khanna_session_v1')")
        checks.check("Password is never kept in the browser", STAFF_PASSWORD not in (stored or "") and "password" not in (stored or "").lower())

        # ---- merged Profile & Settings page ----
        await page.evaluate("location.hash = '#/settings'")
        await page.wait_for_timeout(400)
        checks.check("Old #/settings address lands on the merged page", await page.evaluate("location.hash") == "#/profile" or await page.locator("[data-view='profile'].is-active, [data-view='profile']:not([hidden])").count() > 0)
        checks.check("Page title is 'Profile & Settings'", (await page.locator("[data-view='profile'] h1").inner_text()).strip() == "Profile & Settings")
        checks.check("Email is shown on the profile page", STAFF_EMAIL in await page.locator("[data-profile-view-content]").inner_text())
        checks.check("Password form is on the same page", await page.locator("[data-password-form]").is_visible())
        checks.check("Theme control is on the same page", await page.locator("[data-view='profile'] [data-theme-toggle]").count() > 0)
        menu_items = await page.evaluate("() => Array.from(document.querySelectorAll('[data-nav-link]')).filter(a => a.offsetParent !== null).map(a => a.getAttribute('data-nav-link'))")
        checks.check("No separate Settings link anywhere", "settings" not in menu_items)

        # ---- staff cannot reach admin staff controls ----
        await page.evaluate("location.hash = '#/admin'")
        await page.wait_for_timeout(300)
        checks.check("Staff does not see the Staff accounts panel", not await page.locator("[data-staff-form]").is_visible())
        token = await page.evaluate("JSON.parse(localStorage.getItem('khanna_session_v1')).token")
        checks.check("Backend refuses staff on GET /api/admin/staff (403)", await api_status(page, "GET", "/api/admin/staff", token) == 403)
        checks.check("Backend refuses staff creating an account (403)", await api_status(page, "POST", "/api/admin/staff", token, {"name": "Sneaky", "email": "sneaky@example.com", "password": "Sneaky-pass-1", "role": "admin"}) == 403)

        # ---- admin adds a staff login ----
        await logout(page)
        await login(page, ADMIN_EMAIL, ADMIN_PASSWORD)
        checks.check("Admin signs in", await is_signed_in(page))
        await page.evaluate("location.hash = '#/profile'")
        await page.wait_for_timeout(300)
        checks.check("Admin uses the same Profile & Settings page", (await page.locator("[data-view='profile'] h1").inner_text()).strip() == "Profile & Settings" and await page.locator("[data-password-form]").is_visible())
        await page.evaluate("location.hash = '#/admin'")
        await page.wait_for_timeout(600)
        checks.check("Admin sees the Staff accounts panel", await page.locator("[data-staff-form]").is_visible())

        await page.fill("#staffName", "E2E Staff One")
        await page.fill("#staffEmail", NEW_EMAIL)
        await page.fill("#staffPassword", "short")
        await page.click("[data-staff-form] button[type='submit']")
        await page.wait_for_timeout(300)
        checks.check("A too-short password is not accepted", NEW_EMAIL not in await page.locator("[data-admin-staff-directory]").inner_text())

        await page.fill("#staffPassword", PW1)
        await page.click("[data-staff-form] button[type='submit']")
        await page.wait_for_timeout(800)
        table = await page.locator("[data-admin-staff-directory]").inner_text()
        checks.check("New staff appears in the staff table", NEW_EMAIL in table and "E2E Staff One" in table, table[:200])
        checks.check("Success message shown", "Added" in await page.locator("[data-staff-message]").inner_text())

        await page.fill("#staffName", "Duplicate")
        await page.fill("#staffEmail", NEW_EMAIL)
        await page.fill("#staffPassword", PW1)
        await page.click("[data-staff-form] button[type='submit']")
        await page.wait_for_timeout(500)
        checks.check("Adding the same email twice is refused", "already" in (await page.locator("[data-staff-message]").inner_text()).lower())

        own_row = page.locator(f"tr:has-text('{ADMIN_EMAIL}')")
        checks.check("Admin has no Remove button on their own row", await own_row.locator("[data-staff-remove]").count() == 0)

        # ---- the new staff member logs in and manages their own account ----
        await logout(page)
        await login(page, NEW_EMAIL, PW1)
        checks.check("New staff can sign in with the password the admin set", await is_signed_in(page))
        await page.evaluate("location.hash = '#/profile'")
        await page.wait_for_timeout(300)

        await page.fill("#profileNameInput", "E2E Staff Renamed")
        await page.click("[data-profile-form] button[type='submit']")
        await page.wait_for_timeout(600)
        checks.check("Name change is reflected in the header menu", "E2E Staff Renamed" in await page.locator("[data-profile-dropdown-name]").first.inner_text())

        await page.fill("#pwCurrent", "not-my-password")
        await page.fill("#pwNew", PW2)
        await page.fill("#pwConfirm", PW2)
        await page.click("[data-password-form] button[type='submit']")
        await page.wait_for_timeout(500)
        checks.check("Wrong current password is refused", await page.locator("[data-password-message] .notice-danger").count() == 1)

        await page.fill("#pwCurrent", PW1)
        await page.fill("#pwNew", PW2)
        await page.fill("#pwConfirm", PW2 + "x")
        await page.click("[data-password-form] button[type='submit']")
        await page.wait_for_timeout(300)
        checks.check("Mismatched new passwords are refused", "do not match" in await page.locator("[data-password-message]").inner_text())

        await page.fill("#pwCurrent", PW1)
        await page.fill("#pwNew", PW2)
        await page.fill("#pwConfirm", PW2)
        await page.click("[data-password-form] button[type='submit']")
        await page.wait_for_timeout(600)
        checks.check("Password change succeeds", await page.locator("[data-password-message] .notice-success").count() == 1)

        await logout(page)
        await login(page, NEW_EMAIL, PW1)
        checks.check("Old password no longer works", not await is_signed_in(page))
        await login(page, NEW_EMAIL, PW2)
        checks.check("New password works", await is_signed_in(page))
        checks.check("Renamed name persisted on the server", "E2E Staff Renamed" in await page.locator("[data-profile-dropdown-name]").first.inner_text())

        # ---- admin resets, then removes ----
        await logout(page)
        await login(page, ADMIN_EMAIL, ADMIN_PASSWORD)
        await page.evaluate("location.hash = '#/admin'")
        await page.wait_for_timeout(600)
        row = page.locator(f"tr:has-text('{NEW_EMAIL}')")
        await row.locator("[data-staff-reset-toggle]").click()
        await page.fill("[data-staff-reset-form] input[name='newPassword']", PW3)
        await page.click("[data-staff-reset-form] button[type='submit']")
        await page.wait_for_timeout(600)
        checks.check("Admin password reset confirmed", "Password changed" in await page.locator("[data-staff-message]").inner_text())

        await logout(page)
        await login(page, NEW_EMAIL, PW2)
        checks.check("Password before the admin reset stops working", not await is_signed_in(page))
        await login(page, NEW_EMAIL, PW3)
        checks.check("Password set by the admin works", await is_signed_in(page))

        await logout(page)
        await login(page, ADMIN_EMAIL, ADMIN_PASSWORD)
        await page.evaluate("location.hash = '#/admin'")
        await page.wait_for_timeout(600)
        await page.locator(f"tr:has-text('{NEW_EMAIL}') [data-staff-remove]").click()
        await page.wait_for_timeout(800)
        checks.check("Removed staff disappears from the table", NEW_EMAIL not in await page.locator("[data-admin-staff-directory]").inner_text())

        await logout(page)
        await login(page, NEW_EMAIL, PW3)
        checks.check("Removed staff can no longer sign in", not await is_signed_in(page))

        checks.check("No uncaught page errors", not errors, "; ".join(errors))
        await browser.close()

    checks.report_and_exit()


if __name__ == "__main__":
    asyncio.run(main())
