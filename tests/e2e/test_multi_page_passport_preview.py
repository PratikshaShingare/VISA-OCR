"""
Two-page passport PDF (data page + address page), synthetic names only:

  * the data page preview is cropped to the page (no desk / blank margins);
  * the address page is read automatically right after the data page (the user
    does not have to open page 2 to get the address / old passport);
  * page 2 never rewrites what page 1 supplied, paging back and forth leaves
    the form untouched, and a value typed by hand survives both;
  * old-passport number / date / place are filled and their section opened;
  * every date on the form is DD-MM-YYYY;
  * a salutation is worked out from the passport and flagged for review;
  * choosing a different file clears everything read from the previous one.
"""
import asyncio
import os
import sys
import tempfile

from playwright.async_api import async_playwright

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "..", "backend", "python", "tests"))
sys.path.insert(0, os.path.join(HERE, "..", "..", "backend", "python"))

from PIL import Image, ImageDraw, ImageFont  # noqa: E402

from _common import BASE, Checks, fresh_load_and_login  # noqa: E402

checks = Checks()


def build_pdf(path, with_back=True):
    from test_passport_layout import synthetic_bio_page, _synthetic_address_page

    bio, _ = synthetic_bio_page(surname="SHARMA", given="ANITA")
    if not with_back:
        bio.save(path, "PDF", resolution=150)
        return
    back = _synthetic_address_page()
    bio.save(path, "PDF", save_all=True, append_images=[back], resolution=150)


async def main():
    pdf = os.path.join(tempfile.mkdtemp(), "two_page_synthetic.pdf")
    build_pdf(pdf)
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        context = await browser.new_context(viewport={"width": 1280, "height": 900})
        page = await context.new_page()
        errors = []
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
        await fresh_load_and_login(page, base=BASE)
        await page.evaluate("(function(){ var a = KhannaState.createApplication('x'); KhannaState.setActiveApplicationId(a.id); location.hash = '#/upload-passport'; })()")
        await page.wait_for_timeout(800)
        await page.set_input_files("[data-passport-file-input]", pdf)

        await page.wait_for_function(
            "document.querySelector(\"[data-field='current.number']\") && document.querySelector(\"[data-field='current.number']\").value",
            timeout=120000,
        )
        checks.check("data page number is read", (await page.input_value("[data-field='current.number']")) == "P9988776")
        checks.check("surname read", (await page.input_value("[data-field='applicant.lastName']")) == "SHARMA")
        sal = await page.input_value("[data-field='applicant.salutation']")
        checks.check("adult female without spouse info is Ms", sal == "Ms", sal)

        img = page.locator("[data-passport-preview] img").first
        await img.wait_for(state="visible", timeout=20000)
        dims = await img.evaluate("e => [e.naturalWidth, e.naturalHeight]")
        checks.check("data page preview is cropped to the page shape", 1.25 <= dims[0] / dims[1] <= 1.5, str(dims))

        # ---- page 2 is read automatically (no click on "next page")
        await page.wait_for_function(
            "document.querySelector(\"[data-field='applicant.address.pincode']\").value === '411038'", timeout=180000
        )
        checks.check("address read without opening page 2", True)
        checks.check("address state", (await page.input_value("[data-field='applicant.address.state']")) == "MAHARASHTRA")
        checks.check("address city", (await page.input_value("[data-field='applicant.address.city']")) == "PUNE")
        checks.check("address line 1", (await page.input_value("[data-field='applicant.address.line1']")).startswith("FLAT 12"))
        checks.check("old-passport section opened", await page.locator("[data-old-passport-fields]").is_visible())
        checks.check("old passport number", (await page.input_value("[data-field='old.number']")) == "K1234567")
        checks.check("old passport issue date is DD-MM-YYYY", (await page.input_value("[data-field='old.issueDate']")) == "21-10-2011")
        checks.check("old passport place", (await page.input_value("[data-field='old.placeOfIssue']")) == "PUNE")
        sal2 = await page.input_value("[data-field='applicant.salutation']")
        checks.check("spouse name on page 2 upgrades Ms to Mrs", sal2 == "Mrs", sal2)

        # ---- every date field shows DD-MM-YYYY
        import re
        for path in ("applicant.dob", "current.expiryDate", "current.issueDate"):
            v = await page.input_value(f"[data-field='{path}']")
            checks.check(f"{path} is DD-MM-YYYY", bool(re.fullmatch(r"\d{2}-\d{2}-\d{4}", v)) or v == "", v)
        dob_type = await page.get_attribute("[data-field='applicant.dob']", "type")
        checks.check("date fields are text inputs (no locale-dependent picker)", dob_type == "text", dob_type)

        # ---- hand edit survives paging
        await page.fill("[data-field='applicant.lastName']", "MANUALNAME")
        dob_before = await page.input_value("[data-field='applicant.dob']")
        number_before = await page.input_value("[data-field='current.number']")
        await page.locator("[data-preview-page-next]").click()
        await page.wait_for_timeout(600)
        txt = await page.inner_text("[data-passport-preview]")
        checks.check("page 2 not stuck on processing", "Processing passport" not in txt, txt[:120])
        checks.check("page 2 preview image is shown", await page.locator("[data-passport-preview] img").first.is_visible())
        checks.check("page 2 does not change the date of birth", (await page.input_value("[data-field='applicant.dob']")) == dob_before)
        checks.check("page 2 does not change the passport number", (await page.input_value("[data-field='current.number']")) == number_before)
        checks.check("hand-typed surname survives page 2", (await page.input_value("[data-field='applicant.lastName']")) == "MANUALNAME")
        await page.locator("[data-preview-page-prev]").click()
        await page.wait_for_timeout(600)
        checks.check("back on page 1: values unchanged", (await page.input_value("[data-field='current.number']")) == number_before)
        checks.check("back on page 1: surname still the typed one", (await page.input_value("[data-field='applicant.lastName']")) == "MANUALNAME")

        # ---- an invalid date is refused with a clear message
        await page.fill("[data-field='applicant.dob']", "31-02-1990")
        await page.locator("[data-field='applicant.dob']").blur()
        checks.check("invalid date is marked", await page.locator("[data-field='applicant.dob'].is-invalid").count() == 1)
        # typing digits formats them
        await page.fill("[data-field='applicant.dob']", "")
        await page.locator("[data-field='applicant.dob']").press_sequentially("12051990")
        checks.check("typed digits become DD-MM-YYYY", (await page.input_value("[data-field='applicant.dob']")) == "12-05-1990")

        # ---- a different file clears what the previous one filled
        await page.click("[data-passport-replace]")
        pdf_single = os.path.join(tempfile.mkdtemp(), "single_page_synthetic.pdf")
        build_pdf(pdf_single, with_back=False)
        await page.set_input_files("[data-passport-file-input]", pdf_single)
        await page.wait_for_function(
            "document.querySelector(\"[data-field='current.number']\").value === 'P9988776' && document.querySelector(\"[data-field='applicant.lastName']\").value === 'SHARMA'",
            timeout=120000,
        )
        checks.check("new file: address from the previous file is gone", (await page.input_value("[data-field='applicant.address.pincode']")) == "")
        checks.check("new file: old passport from the previous file is gone", (await page.input_value("[data-field='old.number']")) == "")
        checks.check("new file: hand-typed value from the previous file is gone", (await page.input_value("[data-field='applicant.lastName']")) == "SHARMA")

        checks.check("no console errors", not errors, "; ".join(errors[:3]))
        await browser.close()
    checks.report_and_exit()


asyncio.run(main())
