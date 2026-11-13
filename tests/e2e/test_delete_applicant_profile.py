"""
End-to-end: deleting an applicant profile (Applicant Profiles page).

The Delete button opens a popup with two choices:
  - "Delete basic details": empties the saved phone, email, … everywhere.
  - "Delete all the generated documents for this applicant": the applicant
    leaves the whole website (profiles, their applications, companion
    entries) into the Recycle Bin; restore, select several, delete
    permanently, and the 30-day automatic removal are checked too.
All data is invented (project rule 11).
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from playwright.async_api import async_playwright  # noqa: E402

from _common import Checks, fresh_load_and_login  # noqa: E402

C = Checks()
SHOTS = os.environ.get("KHANNA_E2E_SHOTS", "")

SEED = """() => {
  const S = window.KhannaState;
  function person(name, no) {
    const parts = name.split(' ');
    return { fullName: name, firstName: parts.slice(0, -1).join(' '), lastName: parts[parts.length - 1], dob: '1980-01-01',
             passport: { current: { number: no } }, contact: { phone: '98000 00000', email: 'x@example.com' } };
  }
  const anita = person('ANITA TESTER', 'A1111111');
  const ravi = person('RAVI TESTER', 'R2222222');
  // Anita: main applicant of two applications (one with a generated cover letter).
  const a1 = S.createApplication('e2e');
  S.updateApplication(a1.id, { applicant: anita, coverLetter: { generatedAt: '2026-11-01T10:00:00Z' } });
  const a2 = S.createApplication('e2e');
  S.updateApplication(a2.id, { applicant: anita });
  // Ravi's application lists Anita as a companion.
  const r1 = S.createApplication('e2e');
  S.updateApplication(r1.id, { applicant: ravi, travellers: [Object.assign({ id: 'T1', relation: 'Friend' }, anita)] });
  const pa = S.saveApplicantProfile(anita);
  const pr = S.saveApplicantProfile(ravi);
  S.saveTravellerProfile(anita);
  return { a1: a1.id, a2: a2.id, r1: r1.id, pa: pa.id, pr: pr.id };
}"""

COUNTS = """() => {
  const S = window.KhannaState;
  const all = S.getApplicantProfiles().concat(S.getTravellerProfiles());
  return {
    anitaProfiles: all.filter(p => ((p.passport || {}).current || {}).number === 'A1111111').length,
    raviProfiles: all.filter(p => ((p.passport || {}).current || {}).number === 'R2222222').length,
    apps: S.getApplications().map(a => a.id)
  };
}"""


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page(viewport={"width": 1280, "height": 900})
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        await fresh_load_and_login(page)
        ids = await page.evaluate(SEED)
        await page.evaluate("location.hash = '#/applicant-profiles'")
        await page.wait_for_selector(f"[data-ap-delete='{ids['pa']}']")
        C.check("each profile row has a Delete button", await page.locator("[data-ap-delete]").count() == 2)

        # Popup shows both options with the right counts.
        await page.click(f"[data-ap-delete='{ids['pa']}']")
        await page.wait_for_selector("[data-ap-delete-dialog]:not([hidden])")
        body = await page.inner_text("[data-ap-delete-body]")
        C.check("option 1: Delete basic details", await page.locator("[data-ap-delete-details]").inner_text() == "Delete basic details")
        C.check("option 2: Delete all the generated documents", await page.locator("[data-ap-delete-all]").inner_text() == "Delete all the generated documents for this applicant")
        C.check("popup counts 2 applications and 1 generated document", "2 applications where they are the main applicant (1 generated document)" in body, body)
        C.check("popup mentions the companion entry and the Recycle Bin", "1 other application where they travel as a companion" in body and "Recycle Bin" in body, body)
        if SHOTS:
            await page.screenshot(path=os.path.join(SHOTS, "delete_popup.png"))
        await page.click("[data-ap-delete-cancel].btn")
        C.check("Cancel deletes nothing", (await page.evaluate(COUNTS))["anitaProfiles"] == 2)

        # Option 1 on Ravi (from his profile page): basic details emptied, everything else stays.
        await page.click(f"[data-ap-open='{ids['pr']}']")
        await page.wait_for_selector(f".ap-top [data-ap-delete='{ids['pr']}']")
        await page.click(f".ap-top [data-ap-delete='{ids['pr']}']")
        await page.click("[data-ap-delete-details]")
        c = await page.evaluate(COUNTS)
        basics = await page.evaluate("""() => { const S = window.KhannaState; const p = S.getApplicantProfiles().find(x => x.passport.current.number === 'R2222222');
            const a = S.getApplications().find(x => x.applicant.passport.current.number === 'R2222222');
            return { profile: p.contact.phone + p.contact.email, app: a.applicant.contact.phone + a.applicant.contact.email }; }""")
        C.check("basic details: emptied on the profile and the application", basics == {"profile": "", "app": ""}, str(basics))
        C.check("basic details: profile and applications kept", c["raviProfiles"] == 1 and len(c["apps"]) == 3, str(c))
        C.check("basic details: stays on the profile page", await page.locator("[data-ap-save]").count() == 1 and await page.input_value("#ap-phone") == "")
        await page.click("[data-ap-back]")

        # Option 2 on Anita: gone everywhere, into the Recycle Bin.
        await page.click(f"[data-ap-delete='{ids['pa']}']")
        await page.click("[data-ap-delete-all]")
        c = await page.evaluate(COUNTS)
        C.check("all: every copy of the profile removed", c["anitaProfiles"] == 0, str(c))
        C.check("all: her applications removed", ids["a1"] not in c["apps"] and ids["a2"] not in c["apps"], str(c))
        travellers = await page.evaluate("(id) => window.KhannaState.getApplication(id).travellers.length", ids["r1"])
        C.check("all: taken off Ravi's application as a companion", travellers == 0)
        C.check("confirmation mentions the Recycle Bin", await page.locator("text=moved to the Recycle Bin").count() >= 1)

        await page.evaluate("location.hash = '#/dashboard'")
        await page.wait_for_timeout(300)
        recent = await page.inner_text("[data-dashboard-recent]")
        C.check("gone from Recent Applications", "ANITA" not in recent.upper() and "RAVI" in recent.upper(), recent)

        # ---- Recycle Bin ----
        await page.evaluate("location.hash = '#/recycle-bin'")
        await page.wait_for_selector(".rb-row")
        C.check("bin lists the deleted applicant", await page.locator(".rb-row").count() == 1 and "ANITA TESTER" in await page.inner_text(".rb-row"))
        C.check("bin shows 30 days left", "deleted permanently in 30 days" in await page.inner_text(".rb-row"))
        await page.click("[data-rb-restore]")
        c = await page.evaluate(COUNTS)
        travellers = await page.evaluate("(id) => window.KhannaState.getApplication(id).travellers.length", ids["r1"])
        C.check("restore brings back profiles, applications and the companion entry",
                c["anitaProfiles"] == 2 and ids["a1"] in c["apps"] and ids["a2"] in c["apps"] and travellers == 1, str(c))
        C.check("bin empty after restore", await page.locator("text=The Recycle Bin is empty").count() == 1)

        # Deleting applications from the dashboard also goes to the bin; select several, delete permanently.
        await page.evaluate("(ids) => { const S = window.KhannaState; S.deleteApplication(ids.a1); S.deleteApplication(ids.a2); S.deleteApplication(ids.r1); }", ids)
        await page.wait_for_selector(".rb-row")
        C.check("three deleted applications in the bin", await page.locator(".rb-row").count() == 3)
        C.check("bulk buttons disabled until something is ticked", await page.is_disabled("[data-rb-delete-selected]"))
        rows = page.locator("[data-rb-select]")
        await rows.nth(0).check()
        await page.locator("[data-rb-select]").nth(1).check()
        C.check("2 selected", "2 selected" in await page.inner_text(".rb-toolbar"))
        if SHOTS:
            await page.screenshot(path=os.path.join(SHOTS, "recycle_bin.png"), full_page=True)
        await page.click("[data-rb-delete-selected]")
        await page.wait_for_selector("[data-rb-confirm]:not([hidden])")
        C.check("permanent delete asks first", "2 items will be deleted permanently" in await page.inner_text("[data-rb-confirm-text]"))
        await page.click("[data-rb-confirm-delete]")
        C.check("two deleted permanently, one left", await page.locator(".rb-row").count() == 1)
        await page.check("[data-rb-select-all]")
        C.check("select all ticks every row", await page.locator("[data-rb-select]:checked").count() == 1 and "1 selected" in await page.inner_text(".rb-toolbar"))
        await page.click("[data-rb-delete]")
        await page.click("[data-rb-confirm-delete]")
        C.check("bin empty", await page.locator("text=The Recycle Bin is empty").count() == 1)

        # Entries older than 30 days are removed when the app loads.
        await page.evaluate("""() => { const S = window.KhannaState; const a = S.createApplication('e2e');
            S.updateApplication(a.id, { applicant: { fullName: 'OLD TESTER', passport: { current: { number: 'O4444444' } } } }); S.deleteApplication(a.id);
            const bin = JSON.parse(localStorage.getItem('khanna_recycle_bin_v1')); bin[0].deletedAt = new Date(Date.now() - 31 * 86400000).toISOString();
            localStorage.setItem('khanna_recycle_bin_v1', JSON.stringify(bin)); }""")
        await page.reload()
        await page.wait_for_timeout(800)
        left = await page.evaluate("window.KhannaState.getRecycleBin().length")
        C.check("entries older than 30 days are deleted automatically", left == 0, str(left))
        C.check("Recycle Bin in the menus", await page.locator("a[data-nav-link='recycle-bin']").count() >= 2)

        for width in (320, 390):
            await page.set_viewport_size({"width": width, "height": 800})
            await page.evaluate(ids and """() => { const S = window.KhannaState; S.saveApplicantProfile({ fullName: 'MEERA SAMPLE', passport: { current: { number: 'M3333333' } } }); }""")
            await page.evaluate("location.hash = '#/applicant-profiles'")
            await page.wait_for_timeout(300)
            await page.click("[data-ap-delete]")
            await page.wait_for_selector("[data-ap-delete-dialog]:not([hidden])")
            overflow = await page.evaluate("document.documentElement.scrollWidth - innerWidth")
            C.check(f"popup fits at {width}px", overflow <= 1, str(overflow))
            await page.click("[data-ap-delete-cancel].btn")
        C.check("no page errors", not errors, " | ".join(errors[:3]))
        await browser.close()
    C.report_and_exit()


if __name__ == "__main__":
    asyncio.run(main())
