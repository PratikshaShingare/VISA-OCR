"""
Shared helpers for the Khanna Travels & Holidays end-to-end (Playwright)
test suite. Every script under tests/e2e/ imports from here instead of
redefining its own login/OCR/check-collection boilerplate (project rule 15
— avoid duplicated logic), and every script is environment-configurable via
the env vars below rather than hardcoding a port, so the same script runs
unchanged whether the static file server / backend happen to be on the
ports used during development or different ones in CI.

These are plain asyncio + Playwright scripts, NOT pytest tests: a full
staff workflow involves real file uploads, real downloads, real OCR/
LibreOffice calls and deliberate waits between steps, which a pytest-style
assert-per-function shape does not fit naturally, and every one of this
project's own prior-phase test scripts already used this same
print-PASS/FAIL-and-collect convention. Each script exits with code 0 if
every check passed and 1 otherwise, so `run_e2e_suite.py` (or CI) can tell
pass from fail without parsing output text.
"""

from __future__ import annotations

import os
import subprocess
import sys

BASE = os.environ.get("KHANNA_E2E_BASE", "http://127.0.0.1:8766")
BACKEND_BASE = os.environ.get("KHANNA_E2E_BACKEND_BASE", "http://127.0.0.1:8000")

STAFF_EMAIL = "customercare@khannatravels.com"
STAFF_PASSWORD = "khanna123"
ADMIN_EMAIL = "admin@khannatravels.com"
ADMIN_PASSWORD = "admin123"

FIXTURES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")
SYNTHETIC_PASSPORT_PNG = os.path.join(FIXTURES_DIR, "synthetic_passport.png")
FAKE_SIGNATURE_PNG = os.path.join(FIXTURES_DIR, "fake_signature.png")
SYNTHETIC_HOTEL_VOUCHER_1_PNG = os.path.join(FIXTURES_DIR, "synthetic_hotel_voucher_1.png")
SYNTHETIC_HOTEL_VOUCHER_2_PNG = os.path.join(FIXTURES_DIR, "synthetic_hotel_voucher_2.png")

_ALL_FIXTURES = (SYNTHETIC_PASSPORT_PNG, FAKE_SIGNATURE_PNG, SYNTHETIC_HOTEL_VOUCHER_1_PNG, SYNTHETIC_HOTEL_VOUCHER_2_PNG)


def ensure_fixtures():
    """Generates the synthetic test assets on demand if they aren't
    already sitting in fixtures/ — see fixtures/generate_fixtures.py for
    exactly how (a synthetic, clearly-fake passport bio-data page with a
    valid MRZ, a small squiggle standing in for an uploaded signature, and
    two distinctly-labeled fake hotel vouchers). None of these is a real
    travel document or a real person's data (project rule 11)."""
    if all(os.path.isfile(f) for f in _ALL_FIXTURES):
        return
    subprocess.run(
        [sys.executable, os.path.join(FIXTURES_DIR, "generate_fixtures.py")],
        check=True,
    )


class Checks:
    """Collects (label, passed, extra) results the same way every prior
    phase's own test script did, but as a small reusable object instead of
    a bare module-level list, so one script can report several logical
    sections (e.g. one CheckList per document type) cleanly."""

    def __init__(self):
        self.failures: list[str] = []
        self.total = 0

    def check(self, label: str, cond: bool, extra: str = "") -> bool:
        self.total += 1
        status = "PASS" if cond else "FAIL"
        print(f"[{status}] {label}" + (f"  ({extra})" if extra and not cond else ""))
        if not cond:
            self.failures.append(label)
        return cond

    def report_and_exit(self):
        print()
        print(f"TOTAL: {self.total} check(s), {len(self.failures)} failing")
        for f in self.failures:
            print("  -", f)
        sys.exit(1 if self.failures else 0)


def future_date(days: int = 30) -> str:
    """YYYY-MM-DD, `days` from today — cover-letter dates may not be in the past, so tests must not hard-code them."""
    import datetime as _dt
    return (_dt.date.today() + _dt.timedelta(days=days)).isoformat()


async def login(page, email: str = STAFF_EMAIL, password: str = STAFF_PASSWORD):
    await page.evaluate("location.hash = '#/auth'")
    await page.wait_for_timeout(200)
    await page.fill("[data-login-form] input[type='email']", email)
    await page.fill("[data-login-form] input[type='password']", password)
    await page.click("[data-login-form] button[type='submit']")
    await page.wait_for_timeout(300)


async def fresh_load_and_login(page, base: str = BASE, email: str = STAFF_EMAIL, password: str = STAFF_PASSWORD):
    """Every script starts from a clean localStorage — these are
    isolated, repeatable test runs, not a shared persistent demo
    dataset."""
    await page.goto(base + "/index.html")
    await page.evaluate("localStorage.clear()")
    await page.reload()
    await login(page, email, password)


async def start_guided_wizard_application(page, tap: bool = False):
    """Starts a fresh "Full Application (guided wizard)" application via the
    header's "New Application" dropdown (index.html's [data-new-app-menu]).

    Frontend rework, section 2: the Dashboard's own inline "New Application"
    button (which used to be what every prior version of this helper's
    call sites clicked directly, via a bare
    `[data-action='new-application']:visible` selector) was removed as an
    explicitly-requested duplicate of this one — the header button is now
    the ONLY entry point for this action at every viewport width (there is
    no equivalent item in the mobile-nav drawer). Opening the dropdown
    first is therefore required, not optional, before
    `[data-action='new-application']` (the "Full Application (guided
    wizard)" item inside it) is even visible enough for Playwright to
    click. `[data-new-app-menu-toggle]` is a real click/tap target at every
    width (css/responsive.css only collapses its text label on narrow
    screens, never the button itself), so this one helper covers desktop,
    mobile-emulation and touch call sites alike — pass `tap=True` for a
    real touch tap (test_device_emulation.py) instead of a mouse click.
    """
    toggle = page.locator("[data-new-app-menu-toggle]")
    item = page.locator("[data-new-app-menu-dropdown] [data-action='new-application']")
    if tap:
        await toggle.tap()
        await page.wait_for_timeout(150)
        await item.tap()
    else:
        await toggle.click()
        await page.wait_for_timeout(150)
        await item.click()


async def select_cover_letter_country(page, country_name: str):
    """Frontend rework, section 6: the Cover Letter's old 3-button region
    selector ([data-cover-region='Europe'|'Japan'|'Singapore']) was replaced
    by a searchable country combobox (js/cover-letter.js's
    countrySelectorHtml()/countryOptionsHtml()) — this types into it and
    clicks the matching result, which is what every call site that used to
    click a region button directly now does instead. Selecting a country
    also derives and sets the underlying region (Europe/Japan/Singapore)
    exactly the same way the old buttons did, so nothing downstream of that
    (the person checklist, the region-specific fields) needed to change."""
    await page.fill("[data-cover-country-search]", country_name)
    await page.wait_for_timeout(200)
    await page.click(f"[data-cover-country-option='{country_name}']")
    await page.wait_for_timeout(200)


async def wait_ocr_done(page, scope: str, timeout_polls: int = 80):
    for _ in range(timeout_polls):
        status_text = (await page.inner_text(scope + " [data-passport-status]")).strip()
        if status_text == "" or "fail" in status_text.lower():
            break
        await page.wait_for_timeout(500)


async def generate_and_download(page, generate_selector: str, preview_scope: str, fmt: str = "docx", timeout_polls: int = 40):
    """Clicks a document type's "Generate & Preview" button, waits for that
    specific document-viewer instance (js/document-viewer.js) to finish its
    refresh() call, then clicks its own "Download DOCX"/"Download PDF"
    button and returns the real triggered download.

    Replaces the old direct `[data-action='...'][data-format='docx'|'pdf']`
    single-click download pattern from before the document-first redesign
    (every document engine now shares ONE preview/download component
    instead of a per-format button, project rule 15): generation and
    download are two separate steps now, and the DOCX itself is only
    fetched lazily on the download click (see
    DocumentViewerInstance.prototype._downloadDocx), so this always
    exercises the exact same real backend calls a staff member's click
    would. The PDF, unlike the DOCX, is fetched eagerly during refresh() —
    downloading it is just triggerFileDownload() on the blob refresh()
    already has, so waiting for the same ready-signal below covers both.

    `preview_scope` MUST be that document type's own mount container (e.g.
    "[data-doc-preview='passport']", "[data-voucher-preview]") — several
    document-viewer instances can exist in the DOM at once (one per
    authorization group, one for the cover letter, one per Initors person),
    each with its own `[data-dv='status']`/download buttons, so an unscoped
    page-wide selector could read a DIFFERENT instance's already-settled
    status and return before the one just generated is actually ready.

    Waiting on `[data-dv='status']`'s text leaving "Generating document…" is
    the correct ready-signal regardless of whether the PDF preview itself
    succeeded or failed (project rule 9 — PDF conversion being unavailable
    must never block the DOCX download): refresh() always clears/replaces
    that message once its real backend call(s) resolve, on every path.
    """
    await page.click(generate_selector)
    status_sel = f"{preview_scope} [data-dv='status']"
    for _ in range(timeout_polls):
        status_text = (await page.inner_text(status_sel)).strip()
        if status_text != "Generating document…":
            break
        await page.wait_for_timeout(300)
    download_attr = "download-docx" if fmt == "docx" else "download-pdf"
    async with page.expect_download() as dl_info:
        await page.click(f"{preview_scope} [data-dv='{download_attr}']")
    return await dl_info.value


async def generate_and_download_docx(page, generate_selector: str, preview_scope: str, timeout_polls: int = 40):
    """docx-format convenience wrapper around generate_and_download() — see
    its docstring for the full explanation of this two-step flow."""
    return await generate_and_download(page, generate_selector, preview_scope, fmt="docx", timeout_polls=timeout_polls)


async def fill_ocr_person(page, scope: str, relation_select: str | None = None, relation_value: str | None = None):
    """Runs a passport through the REAL OCR pipeline (real Tesseract,
    never mocked — matching every prior phase's own testing discipline)
    and saves it, verified-checkbox ticked (project rule 10 — OCR results
    are never auto-verified; a human tick is always required, even in a
    test).

    There is no manual "Run OCR" button to click anymore — extraction now
    starts the moment a file is selected (see runOcr() in
    js/passport/passport-processing.js, called right after
    set_input_files() below), per an explicit product instruction that OCR
    "should automatically run ... and extract data from passport". The
    only OTHER OCR-related button left on this page,
    `[data-passport-run-ocr-openrouter]`, is a separate, optional TESTING
    PATH that calls a real external OpenRouter vision model instead of the
    production Tesseract/Google Vision pipeline — it is not part of the
    main flow, needs its own OPENROUTER_API_KEY, and clicking it
    unconditionally here (an earlier version of this helper did) makes
    every run of this suite depend on a real paid external API being
    configured, and fail loudly with a real 503 when it isn't (caught live
    running this exact suite — the automatic runOcr() above already
    produces the real OCR data this test actually checks)."""
    ensure_fixtures()
    if relation_select:
        await page.select_option(relation_select, relation_value)
        await page.wait_for_timeout(150)
    file_input = page.locator(f"{scope} [data-passport-file-input]")
    await file_input.set_input_files(SYNTHETIC_PASSPORT_PNG)
    await wait_ocr_done(page, scope)
    await page.check(f"{scope} [data-verified-checkbox]")
    await page.click(f"{scope} [data-passport-save]")
    await page.wait_for_timeout(300)


async def wait_preview_ready(page, preview_scope: str, timeout_polls: int = 100):
    """Waits until the document viewer mounted in `preview_scope` has
    finished generating AND drawn its page (status cleared, canvas visible)."""
    status_sel = f"{preview_scope} [data-dv='status']"
    for _ in range(timeout_polls):
        status_text = (await page.inner_text(status_sel)).strip()
        if status_text == "" and await page.locator(f"{preview_scope} [data-dv='canvas']").is_visible():
            break
        await page.wait_for_timeout(300)
    await page.wait_for_timeout(700)


async def set_edit_mode(page, preview_scope: str, on: bool = True):
    """Presses the Preview section's Edit button until edit mode matches `on`."""
    btn = page.locator(f"{preview_scope} [data-dv='edit-toggle']")
    pressed = (await btn.get_attribute("aria-pressed")) == "true"
    if pressed != on:
        await btn.click()
        await page.wait_for_timeout(300)


async def edit_value_on_preview(page, preview_scope: str, key: str, text: str, select_all: bool = True):
    """Edit mode on -> click the on-page value `key` -> replace its text with
    `text` the way a person would (Ctrl+A, type) -> move on so it is saved.
    Returns the text the value was seeded with before the edit."""
    await set_edit_mode(page, preview_scope, True)
    field = page.locator(f"{preview_scope} .pe-field[data-pe-key='{key}']").first
    await field.click()
    await page.wait_for_timeout(700)
    seeded = (await page.inner_text(f"{preview_scope} .pe-field.is-active .ql-editor")).strip()
    if select_all:
        await page.keyboard.press("Control+A")
    await page.keyboard.type(text)
    await page.wait_for_timeout(450)
    return seeded


async def commit_preview_edit(page, preview_scope: str):
    """Leaves the open value (Escape) so it is saved into the record."""
    await page.keyboard.press("Escape")
    await page.wait_for_timeout(400)


async def pick_company_consulate(page, country="Germany"):
    """Company Authorization Letter: choose the consulate by COUNTRY from the
    searchable list (type, then Enter picks the highlighted match) — the
    wording "The Consulate General of <country>" and the default address
    "Mumbai, India" complete themselves."""
    inp = page.locator("#auth-company-consulateCountry")
    await inp.click()
    await inp.fill(country)
    await inp.press("Enter")
    await page.wait_for_timeout(300)


async def pick_inviter_country(page, country="Ireland"):
    """Invitation Letter: choose the consulate's country from the searchable
    list (type, then Enter picks the highlighted match)."""
    inp = page.locator("#inv-inviter-country")
    await inp.click()
    await inp.fill(country)
    await inp.press("Enter")
    await page.wait_for_timeout(300)
