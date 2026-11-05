"""
Upload Documents page ("document sorter") end-to-end check.

Uses ONLY synthetic documents (fixtures/generate_fixtures.py's clearly-fake
passport and vouchers, plus a few variants built here from the same
generator) through the REAL backend OCR — nothing is mocked (project rule 9).

Covers: the page and menu entry exist ("Upload Passport" replaced), real file
inputs (PDF/JPG/PNG accepted), passports/vouchers read and sorted around the
typed main applicant, manual overrides, the progress popup, real generated
downloads (Hotel Blocking + Passport Authorization), honest "needs details"
hand-off for Cover Letter / Company Authorization, passports saved as
"OCR Extracted — Please Verify" (never verified), and no layout overflow.

Requires the static server and the backend (see run_e2e_suite.py).
"""

import asyncio
import inspect
import os
import sys
import tempfile

from playwright.async_api import async_playwright

from _common import (
    BASE,
    Checks,
    FIXTURES_DIR,
    STAFF_EMAIL,
    STAFF_PASSWORD,
    SYNTHETIC_HOTEL_VOUCHER_2_PNG,
    SYNTHETIC_PASSPORT_PNG,
    ensure_fixtures,
    fresh_load_and_login,
)

checks = Checks()


def build_variants(tmp):
    """A second (different-name) passport and a voucher that names the first passport's holder."""
    sys.path.insert(0, FIXTURES_DIR)
    import generate_fixtures as gf  # noqa: E402

    src = inspect.getsource(gf.render_synthetic_passport_page)
    # Same-length replacements keep the MRZ line 44 characters long.
    src = src.replace("TESTPERSON", "OTHERFAMLY").replace("SAMPLE", "ALPHAB")
    ns = dict(vars(gf))
    exec(src, ns)  # noqa: S102 — local synthetic-fixture generator, not user input
    other_passport = os.path.join(tmp, "other_family_passport.png")
    ns["render_synthetic_passport_page"](rotate_deg=3).save(other_passport)

    voucher = os.path.join(tmp, "voucher_for_group.png")
    gf.render_synthetic_hotel_voucher(
        rows=[
            ("Hotel Name", "Group Fixture Hotel"),
            ("Hotel Phone", "01 11112222"),
            ("Address", "3 Fixture Road"),
            ("City", "Rome"),
            ("Country", "Italy"),
            ("Confirmation No", "GRP555666"),
            ("Lead Guest Name", "Sample Testperson"),
            ("Room Type", "Deluxe Double"),
            ("No of Rooms", "1"),
            ("Adults", "1"),
            ("Children", "0"),
            ("Check-in", "12/12/2026"),
            ("Check-out", "16/12/2026"),
        ],
        guest_lines=["Guest 1 Name: Sample Testperson"],
    ).save(voucher)
    return other_passport, voucher


async def wait_all_read(page, minutes=6):
    for _ in range(minutes * 120):
        state = await page.evaluate(
            """() => {
                const rows = [...document.querySelectorAll('[data-ud-item]')];
                const busy = rows.filter(r => /Reading|Waiting/.test(r.querySelector('.badge')?.textContent || '')).length;
                return {rows: rows.length, busy};
            }"""
        )
        if state["rows"] and state["busy"] == 0:
            return True
        await page.wait_for_timeout(500)
    return False


async def main():
    ensure_fixtures()
    tmp = tempfile.mkdtemp(prefix="ud_fixtures_")
    other_passport, group_voucher = build_variants(tmp)

    async with async_playwright() as p:
        browser = await p.chromium.launch()
        ctx = await browser.new_context(viewport={"width": 1280, "height": 1000}, accept_downloads=True)
        page = await ctx.new_page()
        console_errors = []
        page.on("console", lambda m: console_errors.append(m.text) if m.type == "error" else None)
        downloads = []
        page.on("download", lambda d: downloads.append(d))

        await fresh_load_and_login(page, base=BASE, email=STAFF_EMAIL, password=STAFF_PASSWORD)

        # ---------- menu + page ----------
        nav_text = await page.evaluate("[...document.querySelectorAll('[data-nav-link]')].map(a => a.textContent.trim()).join(' | ')")
        # Menus offer "Upload Passport" again (single passport -> check -> save as applicant);
        # this multi-file sorter page is still reachable by its address but is not in the menus.
        checks.check("Menu offers 'Upload Passport' (not 'Upload Documents')", "Upload Passport" in nav_text and "Upload Documents" not in nav_text, nav_text[:200])
        menu_only = await page.evaluate("[...document.querySelectorAll('.primary-nav [data-nav-link], .profile-menu [data-nav-link], .dashboard-doc-card')].map(a => a.textContent.trim()).join(' | ')")
        checks.check("Menu, profile menu and dashboard say 'Upload Passport' and not 'Upload Documents'", "Upload Passport" in menu_only and "Upload Documents" not in menu_only, menu_only[:300])
        await page.evaluate("location.hash = '#/upload-documents'")
        await page.wait_for_timeout(500)
        checks.check("Upload Documents page is shown", await page.locator("[data-view='upload-documents'].is-active").count() == 1)
        checks.check("Heading says 'Upload Documents'", "Upload Documents" in await page.inner_text("[data-view='upload-documents'] h1"))
        checks.check("A real file input backs the passport upload (multiple)", await page.locator("[data-ud-file='passport']").get_attribute("multiple") is not None)
        checks.check("A real file input backs the voucher upload (multiple)", await page.locator("[data-ud-file='voucher']").get_attribute("multiple") is not None)
        accept = await page.locator("[data-ud-file='passport']").get_attribute("accept")
        checks.check("Accepted formats include pdf, jpg, jpeg, png", all(x in accept for x in (".pdf", ".jpg", ".jpeg", ".png")), accept)
        checks.check("Generate is disabled before anything is entered", await page.locator("[data-ud-generate]").is_disabled())

        # ---------- upload + read + sort ----------
        await page.fill("[data-ud-main-name]", "Sample Testperson")
        await page.locator("[data-ud-file='passport']").set_input_files([SYNTHETIC_PASSPORT_PNG, other_passport])
        await page.locator("[data-ud-file='voucher']").set_input_files([group_voucher, SYNTHETIC_HOTEL_VOUCHER_2_PNG])
        checks.check("All four files were read (OCR finished)", await wait_all_read(page))
        rows = page.locator("[data-ud-item]")
        checks.check("Four rows are listed", await rows.count() == 4, str(await rows.count()))

        info = await page.evaluate(
            """() => [...document.querySelectorAll('[data-ud-item]')].map(r => ({
                text: r.innerText,
                checked: r.querySelector('[data-ud-include]').checked,
                badge: r.querySelector('.badge')?.textContent || ''
            }))"""
        )
        main_row = next((r for r in info if "Main applicant" in r["badge"]), None)
        checks.check("The passport matching the typed name is the main applicant", main_row is not None and "SAMPLE" in main_row["text"].upper(), str(info)[:300])
        checks.check("...and it is ticked", bool(main_row and main_row["checked"]))
        other_row = next((r for r in info if "OTHERFAMLY" in r["text"].upper() or "ALPHAB" in r["text"].upper()), None)
        checks.check("The other-family passport is not linked to the main applicant", bool(other_row) and "Not linked" in other_row["badge"], str(other_row)[:200])
        checks.check("...and it is NOT ticked", bool(other_row) and not other_row["checked"])
        v_group = next((r for r in info if "Group Fixture Hotel" in r["text"]), None)
        checks.check("The voucher naming the applicant belongs to the group (ticked)", bool(v_group) and v_group["checked"], str(v_group)[:200])
        v_other = next((r for r in info if "Fixture Riviera Hotel" in r["text"]), None)
        checks.check("The unrelated voucher is not matched (unticked)", bool(v_other) and not v_other["checked"], str(v_other)[:200])
        checks.check("Every decision shows a reason", all("Name" in r["text"] or "name" in r["text"] or "match" in r["text"].lower() for r in info))
        note = await page.inner_text("[data-ud-verify-note]")
        checks.check("The page says OCR results must be verified", "OCR Extracted — Please Verify" in note, note)

        # manual override: untick/tick
        tick = page.locator("[data-ud-item] [data-ud-include]").nth(1)
        await tick.check()
        checks.check("Staff can include a document the sorter left out", await tick.is_checked())
        await tick.uncheck()
        checks.check("...and take it out again", not await tick.is_checked())

        # no match warning
        await page.fill("[data-ud-main-name]", "Nobody Matching")
        await page.wait_for_timeout(200)
        warn = await page.locator(".ud-warn").count()
        checks.check("A name that matches no passport shows a warning", warn == 1)
        await page.fill("[data-ud-main-name]", "Sample Testperson")
        await page.wait_for_timeout(200)
        checks.check("Typing the right name finds the applicant again", await page.locator(".ud-warn").count() == 0)

        # ---------- generate ----------
        await page.check("[data-ud-doc='hotel']")
        await page.check("[data-ud-doc='passportAuth']")
        await page.check("[data-ud-doc='cover']")
        await page.check("[data-ud-doc='companyAuth']")
        await page.fill("[data-ud-pa='centre']", "Test Visa Centre")
        await page.fill("[data-ud-pa='collector']", "Test Collector")
        checks.check("Generate is enabled once name + documents are set", await page.locator("[data-ud-generate]").is_enabled())
        await page.click("[data-ud-generate]")
        checks.check("A popup says documents are being generated", await page.locator("[data-ud-modal]:not([hidden])").count() == 1)
        title = await page.inner_text("[data-ud-modal-title]")
        checks.check("Popup title is the 'being generated' message at first or the finished one", "generat" in title.lower() or "finished" in title.lower(), title)
        for _ in range(240):
            if not await page.locator("[data-ud-modal-close]").is_disabled():
                break
            await page.wait_for_timeout(500)
        body = await page.inner_text("[data-ud-modal-body]")
        done_title = await page.inner_text("[data-ud-modal-title]")
        checks.check("Popup finishes with a result message", "Documents generated" in done_title or "Finished" in done_title, done_title)
        jobs = await page.evaluate("[...document.querySelectorAll('.ud-job')].map(j => j.innerText)")
        job = lambda key: next((j for j in jobs if key in j), "")
        checks.check("Hotel Blocking: generated", "Done" in job("Hotel Blocking"), job("Hotel Blocking"))
        checks.check("Passport Authorization: generated", "Done" in job("Passport Authorization"), job("Passport Authorization"))
        checks.check("Company Authorization without a country: needs details (not faked)", "Needs details" in job("Company Authorization"), job("Company Authorization"))
        checks.check("Cover Letter: honest 'needs details' hand-off", "Needs details" in job("Cover Letter"), job("Cover Letter"))
        await page.wait_for_timeout(500)
        names = [d.suggested_filename for d in downloads]
        checks.check("Two real files were downloaded", len(names) == 2, str(names))
        checks.check("Downloads are .docx", all(n.lower().endswith(".docx") for n in names), str(names))
        sizes = []
        for d in downloads:
            path = await d.path()
            sizes.append(os.path.getsize(path) if path else 0)
        checks.check("Downloaded files are not empty", all(s > 2000 for s in sizes), str(sizes))

        # ---------- what was saved ----------
        app = await page.evaluate(
            """() => { const a = KhannaState.getActiveApplication(); return {
                first: a.applicant.firstName, last: a.applicant.lastName,
                status: a.applicant.passport.verificationStatus, num: a.applicant.passport.current.number,
                travellers: a.travellers.length, hotels: a.hotels.map(h => h.hotelName),
                paIds: a.authorization.passport.selectedPersonIds, cover: a.coverLetter.selectedPersonIds,
                start: a.coverLetter.travelStartDate, end: a.coverLetter.travelEndDate }; }"""
        )
        checks.check("The main applicant was saved from the passport", "SAMPLE" in (app["first"] or "").upper() and "TESTPERSON" in (app["last"] or "").upper(), str(app))
        checks.check("Passport is saved as OCR Extracted — Please Verify (never Verified)", app["status"] == "OCR Extracted — Please Verify", str(app["status"]))
        checks.check("Only the ticked passports became people (no companions here)", app["travellers"] == 0, str(app["travellers"]))
        checks.check("Only the matching voucher became a hotel", app["hotels"] == ["Group Fixture Hotel"], str(app["hotels"]))
        checks.check("People were pre-selected on the letters", app["paIds"] == ["applicant"] and app["cover"] == ["applicant"], str(app))
        checks.check("Cover letter travel dates come from the voucher", app["start"] == "2026-12-12" and app["end"] == "2026-12-16", f"{app['start']} / {app['end']}")

        # hand-off link opens the real page with the application active
        await page.click("[data-ud-open-page='cover-letter']")
        await page.wait_for_timeout(600)
        checks.check("Hand-off opens the Cover Letter page", "cover-letter" in page.url)
        sel = await page.evaluate("KhannaState.getActiveApplication().coverLetter.selectedPersonIds")
        checks.check("...with the applicant already selected", sel == ["applicant"], str(sel))

        # ---------- second generate reuses the application ----------
        await page.evaluate("location.hash = '#/upload-documents'")
        await page.wait_for_timeout(500)
        before = await page.evaluate("KhannaState.getApplications().length")
        await page.uncheck("[data-ud-doc='cover']")
        await page.uncheck("[data-ud-doc='companyAuth']")
        await page.uncheck("[data-ud-doc='passportAuth']")
        await page.select_option("[data-ud-format]", "pdf")
        await page.click("[data-ud-generate]")
        for _ in range(240):
            if not await page.locator("[data-ud-modal-close]").is_disabled():
                break
            await page.wait_for_timeout(500)
        await page.click("[data-ud-modal-close]")
        after = await page.evaluate("KhannaState.getApplications().length")
        checks.check("Generating again with the same documents does not create a duplicate application", before == after, f"{before} -> {after}")
        await page.wait_for_timeout(500)
        checks.check("PDF format gives a PDF download", any(d.suggested_filename.lower().endswith(".pdf") for d in downloads), str([d.suggested_filename for d in downloads]))

        # ---------- companion pickup via 'Make main applicant' ----------
        await page.locator("[data-ud-make-main]").first.click()
        await page.wait_for_timeout(300)
        main_after = await page.evaluate(
            "[...document.querySelectorAll('[data-ud-item]')].filter(r => /Main applicant/.test(r.querySelector('.badge').textContent)).length"
        )
        checks.check("'Make main applicant' moves the role to the chosen passport (exactly one main)", main_after == 1, str(main_after))

        # ---------- layout ----------
        for w in (1280, 768, 390, 320):
            await page.set_viewport_size({"width": w, "height": 900})
            await page.wait_for_timeout(250)
            overflow = await page.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth")
            checks.check(f"No horizontal overflow on Upload Documents at {w}px", overflow <= 1, str(overflow))

        # ---------- rejected type ----------
        junk = os.path.join(tmp, "notes.txt")
        with open(junk, "w") as f:
            f.write("not a document")
        before_rows = await page.locator("[data-ud-item]").count()
        await page.locator("[data-ud-file='passport']").set_input_files(junk)
        await page.wait_for_timeout(300)
        notice = await page.inner_text("[data-ud-notice]")
        checks.check("A .txt file is refused with a message", "notes.txt" in notice and await page.locator("[data-ud-item]").count() == before_rows, notice)

        checks.check("Zero console errors", len(console_errors) == 0, "; ".join(console_errors[:5]))
        await browser.close()

    checks.report_and_exit()


if __name__ == "__main__":
    asyncio.run(main())
