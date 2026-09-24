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


def ensure_fixtures():
    """Generates the synthetic test assets on demand if they aren't
    already sitting in fixtures/ — see fixtures/generate_fixtures.py for
    exactly how (a synthetic, clearly-fake passport bio-data page with a
    valid MRZ, and a small squiggle standing in for an uploaded
    signature). Neither is a real travel document or a real person's
    signature (project rule 11)."""
    if os.path.isfile(SYNTHETIC_PASSPORT_PNG) and os.path.isfile(FAKE_SIGNATURE_PNG):
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


async def wait_ocr_done(page, scope: str, timeout_polls: int = 80):
    for _ in range(timeout_polls):
        status_text = (await page.inner_text(scope + " [data-passport-status]")).strip()
        if status_text == "" or "fail" in status_text.lower():
            break
        await page.wait_for_timeout(500)


async def fill_ocr_person(page, scope: str, relation_select: str | None = None, relation_value: str | None = None):
    """Runs a passport through the REAL OCR pipeline (real Tesseract,
    never mocked — matching every prior phase's own testing discipline)
    and saves it, verified-checkbox ticked (project rule 10 — OCR results
    are never auto-verified; a human tick is always required, even in a
    test)."""
    ensure_fixtures()
    if relation_select:
        await page.select_option(relation_select, relation_value)
        await page.wait_for_timeout(150)
    file_input = page.locator(f"{scope} [data-passport-file-input]")
    await file_input.set_input_files(SYNTHETIC_PASSPORT_PNG)
    await page.wait_for_timeout(300)
    await page.click(f"{scope} [data-passport-run-ocr]")
    await wait_ocr_done(page, scope)
    await page.check(f"{scope} [data-verified-checkbox]")
    await page.click(f"{scope} [data-passport-save]")
    await page.wait_for_timeout(300)
