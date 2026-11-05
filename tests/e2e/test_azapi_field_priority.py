"""
azapi.ai results in the passport review form (frontend rules only — the
backend side is covered by backend/python/tests/test_ocr_azapi.py, and no real
azapi call is ever made here, so no credits are spent):

  * a clean azapi reading shows NO green/amber boxes and no per-field notes (the banner stays); coloured boxes return when azapi is not used or a value is genuinely suspicious;
  * a field read by azapi shows "azapi OCR" (or "confirmed by azapi OCR") as its source when it is flagged;
  * the weaker local read of the passport's address page, which arrives right
    afterwards, never replaces a value azapi already supplied;
  * a field azapi had nothing for is still filled from the local read;
  * a value typed by hand still wins over everything;
  * choosing a different file clears the azapi bookkeeping.
Synthetic names only.
"""
import asyncio
import base64
import io
import json
import os
import sys
import tempfile

from playwright.async_api import async_playwright

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "..", "backend", "python", "tests"))
sys.path.insert(0, os.path.join(HERE, "..", "..", "backend", "python"))

from PIL import Image  # noqa: E402

from _common import BASE, Checks, fresh_load_and_login  # noqa: E402

checks = Checks()


def png_b64():
    buf = io.BytesIO()
    Image.new("RGB", (130, 90), (245, 245, 245)).save(buf, "PNG")
    return base64.b64encode(buf.getvalue()).decode()


def field(value, source, review=True, conf=0.85, note=None):
    f = {"value": value, "confidence": conf, "source": source, "needsReview": review}
    if note:
        f["note"] = note
    return f


def bio_result():
    return {
        "isBlank": False, "pageKind": "bio", "pageIndex": 0, "totalPages": 2, "orientationApplied": 0,
        "orientationNeedsReview": False, "orientationScores": {}, "skewAngleCorrectedDegrees": 0,
        "processedImageBase64": png_b64(), "documentRegionDetected": False, "ocrProvider": "azapi",
        "azapi": {"used": True, "fromCache": False, "backPageIndex": 1},
        "mrz": {"valid": True, "passportNumberValid": True, "dateOfBirthValid": True, "dateOfExpiryValid": True,
                "compositeValid": True, "line1": "P<INDSHARMA<<ANITA<<<<<<<<<<<<<<<<<<<<<<<<<<<", "line2": "P99887761IND9005125F3112313<<<<<<<<<<<<<<04"},
        "fields": {
            "surname": field("SHARMA", "mrz+azapi", False, 0.98),
            "givenNames": field("ANITA", "mrz+azapi", False, 0.98),
            "dateOfBirth": field("1990-05-12", "mrz+azapi", False, 0.99),
            "sex": field("F", "mrz+azapi", False, 0.99),
            "nationality": field("IND", "mrz", False, 0.95),
            "countryCode": field("IND", "mrz", False, 0.95),
            "passportNumber": field("P9988776", "mrz+azapi", False, 0.99),
            "passportType": field("P", "mrz", False, 0.9),
            "dateOfExpiry": field("2031-12-31", "mrz+azapi", False, 0.99),
            "dateOfIssue": field("2022-01-01", "azapi", False, 0.95),
            "placeOfBirth": field("SAMPLEPUR, SAMPLESTATE", "azapi", False),
            "placeOfIssue": field("SAMPLEPUR", "azapi", False),
            "addressLine1": field("AZAPI LINE ONE", "azapi", False),
            "addressCity": field("AZAPICITY", "azapi", False),
            "addressState": field("SAMPLESTATE", "azapi", False),
            "addressPincode": field("411001", "azapi", False),
            "addressCountry": field("INDIA", "azapi", False),
        },
        "warnings": [], "notices": [], "verificationStatus": "OCR Extracted — Please Verify",
    }


def back_result():
    return {
        "isBlank": False, "pageKind": "back", "pageIndex": 1, "totalPages": 2, "orientationApplied": 0,
        "orientationNeedsReview": False, "orientationScores": {}, "skewAngleCorrectedDegrees": 0,
        "processedImageBase64": png_b64(), "documentRegionDetected": False, "mrz": None,
        "fields": {
            "addressLine1": field("LOCAL MISREAD LINE", "viz", True, 0.4),
            "addressCity": field("LOCALCITY", "viz", True, 0.4),
            "addressPincode": field("411999", "viz", True, 0.6),
            "addressLine2": field("LOCAL LINE TWO", "viz", True, 0.4),
            "fatherName": field("LOCAL FATHER", "viz", True, 0.5),
        },
        "warnings": [], "notices": [], "verificationStatus": "OCR Extracted — Please Verify",
    }


async def main():
    from test_passport_layout import synthetic_bio_page, _synthetic_address_page

    bio, _ = synthetic_bio_page(surname="SHARMA", given="ANITA")
    pdf = os.path.join(tempfile.mkdtemp(), "two_page_synthetic.pdf")
    bio.save(pdf, "PDF", save_all=True, append_images=[_synthetic_address_page()], resolution=150)

    azapi_failed = {"on": False}

    def local_only_bio():
        r = bio_result()
        r.pop("azapi"), r.pop("ocrProvider")
        r["notices"] = ["azapi OCR was not used (azapi reports that the account has no credits left.) — the local reader was used instead."]
        for key in ("surname", "givenNames", "dateOfBirth", "passportNumber"):
            r["fields"][key]["source"] = "mrz"
        r["fields"]["placeOfBirth"] = field("SAMPLEPUR", "viz", True, 0.5)
        return r

    async def handle(route):
        body = route.request.post_data_buffer or b""
        is_page_two = b'name="page_index"\r\n\r\n1' in body
        payload = back_result() if is_page_two else (local_only_bio() if azapi_failed["on"] else bio_result())
        await route.fulfill(
            status=200, content_type="application/json",
            headers={"access-control-allow-origin": "*"},
            body=json.dumps(payload),
        )

    async with async_playwright() as p:
        browser = await p.chromium.launch()
        context = await browser.new_context(viewport={"width": 1280, "height": 900})
        page = await context.new_page()
        errors = []
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
        await fresh_load_and_login(page, base=BASE)
        await page.route("**/api/passport/process", handle)
        await page.evaluate("(function(){ var a = KhannaState.createApplication('x'); KhannaState.setActiveApplicationId(a.id); location.hash = '#/upload-passport'; })()")
        await page.wait_for_timeout(800)
        await page.set_input_files("[data-passport-file-input]", pdf)

        # Wait until BOTH pages have been applied (the address page fills the father's name and line 2).
        await page.wait_for_function(
            "document.querySelector(\"[data-field='applicant.address.line2']\").value === 'LOCAL LINE TWO'", timeout=60000
        )
        v = lambda path: page.input_value(f"[data-field='{path}']")  # noqa: E731
        meta = lambda path: page.inner_text(f"[data-field-meta='{path}']")  # noqa: E731

        checks.check("azapi address line 1 is kept", (await v("applicant.address.line1")) == "AZAPI LINE ONE")
        checks.check("azapi city is kept", (await v("applicant.address.city")) == "AZAPICITY")
        checks.check("azapi PIN is kept", (await v("applicant.address.pincode")) == "411001")
        checks.check("a field azapi had nothing for is filled from the local read", (await v("applicant.address.line2")) == "LOCAL LINE TWO")
        # ---- colours: a clean azapi reading shows none; only a real problem is coloured
        coloured = await page.evaluate("document.querySelectorAll('[data-field-wrap].field-ok, [data-field-wrap].field-review').length")
        coloured_paths = await page.evaluate("Array.from(document.querySelectorAll('[data-field-wrap].field-ok, [data-field-wrap].field-review')).map(e => e.getAttribute('data-field-wrap'))")
        # The only coloured box is the one value filled by the weaker local read of the address page (azapi had no line 2).
        checks.check("clean azapi reading: no green / amber boxes except a value filled by the local reader", coloured_paths == ["applicant.address.line2"], str(coloured_paths))
        checks.check("clean azapi reading: no per-field notes", (await meta("applicant.address.line1")) == "" and (await meta("current.number")) == "")
        checks.check("the overall 'OCR Extracted — Please Verify' banner is still shown", "OCR Extracted" in await page.inner_text("[data-ocr-banner]"))
        checks.check("azapi place of birth filled", (await v("applicant.placeOfBirth")) == "SAMPLEPUR, SAMPLESTATE")
        checks.check("issue date is DD-MM-YYYY", (await v("current.issueDate")) == "01-01-2022")

        # ---- a hand-typed value beats azapi and anything that follows
        await page.fill("[data-field='applicant.address.city']", "TYPED BY HAND")
        await page.locator("[data-preview-page-next]").click()
        await page.wait_for_timeout(500)
        await page.locator("[data-preview-page-prev]").click()
        await page.wait_for_timeout(500)
        checks.check("hand-typed city survives", (await v("applicant.address.city")) == "TYPED BY HAND")

        # ---- a different file clears everything, including the azapi bookkeeping
        await page.click("[data-passport-replace]")
        await page.set_input_files("[data-passport-file-input]", pdf)
        await page.wait_for_function(
            "document.querySelector(\"[data-field='applicant.address.line2']\").value === 'LOCAL LINE TWO'", timeout=60000
        )
        checks.check("new file: azapi value applied again (not blocked by the previous file)", (await v("applicant.address.line1")) == "AZAPI LINE ONE")
        checks.check("new file: hand-typed value is gone", (await v("applicant.address.city")) == "AZAPICITY")

        # ---- azapi fails -> the coloured boxes come back (local reader's readings)
        azapi_failed["on"] = True
        await page.click("[data-passport-replace]")
        await page.set_input_files("[data-passport-file-input]", pdf)
        await page.wait_for_function(
            "document.querySelector(\"[data-field='applicant.address.line2']\").value === 'LOCAL LINE TWO'", timeout=60000
        )
        fallback = await page.evaluate("document.querySelectorAll('[data-field-wrap].field-ok, [data-field-wrap].field-review').length")
        checks.check("azapi not used: green / amber boxes are shown again", fallback >= 5, str(fallback))
        checks.check("azapi not used: per-field notes are shown again", "confidence" in (await meta("current.number")), await meta("current.number"))
        checks.check("azapi not used: local place of birth is flagged for review", await page.locator("[data-field-wrap='applicant.placeOfBirth'].field-review").count() == 1)

        checks.check("no console errors", not errors, "; ".join(errors[:3]))
        await browser.close()
    checks.report_and_exit()


asyncio.run(main())
