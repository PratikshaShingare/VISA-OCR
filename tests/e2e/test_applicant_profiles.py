"""
End-to-end: Applicant Profiles — basic details saved once and used by letters
and the Japan visa form; the residential address comes from the passport only.

Synthetic people only (project rule 11).
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from playwright.async_api import async_playwright  # noqa: E402

from _common import BASE, Checks, fresh_load_and_login, select_cover_letter_country  # noqa: E402

C = Checks()

SEED = """() => {
  const S = window.KhannaState;
  const a = S.createApplication('e2e');
  S.updateApplication(a.id, { applicant: {
    salutation: 'Mrs', firstName: 'ANITA RAJ', lastName: 'SHARMA', fullName: 'ANITA RAJ SHARMA', dob: '1980-05-14', sex: 'F',
    nationality: 'INDIAN', placeOfBirth: 'PUNE, MAHARASHTRA', passportSpouseName: 'RAJESH SHARMA',
    address: { line1: '12 Sample Society', line2: 'Example Road', city: 'Pune', state: 'Maharashtra', pincode: '411001', country: 'India' },
    passport: { current: { number: 'Z1234567', issueDate: '2020-01-10', expiryDate: '2035-01-09', issuePlace: 'MUMBAI', type: 'P', countryCode: 'IND' } }
  } });
  S.syncApplicantProfileFromApplication(a.id);
  S.setActiveApplicationId(a.id);
  return { appId: a.id, profileId: S.getApplication(a.id).applicantId };
}"""


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page(viewport={"width": 1280, "height": 1000})
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        await fresh_load_and_login(page)
        ids = await page.evaluate(SEED)
        app_id, profile_id = ids["appId"], ids["profileId"]

        # ---------------------------------------------------------- the page
        await page.evaluate("location.hash = '#/applicant-profiles'")
        await page.wait_for_selector("[data-ap-open]", timeout=10000)
        C.check("menu links to Applicant Profiles", await page.locator(".mobile-nav [data-nav-link='applicant-profiles']").count() == 1)
        C.check("list shows the person", "ANITA RAJ SHARMA" in await page.inner_text("[data-applicant-profiles-root]"))
        C.check("list says no details saved yet", "No basic details saved yet" in await page.inner_text("[data-applicant-profiles-root]"))
        await page.fill("[data-ap-search]", "zzzz")
        C.check("search narrows the list", await page.locator("[data-ap-open]").count() == 0)
        await page.fill("[data-ap-search]", "z1234")
        C.check("search by passport number", await page.locator("[data-ap-open]").count() == 1)

        await page.click("[data-ap-open]")
        text = await page.inner_text("[data-applicant-profiles-root]")
        C.check("editor shows passport address (read-only)", "12 Sample Society" in text and "Pune" in text)
        C.check("no editable address box on the profile", await page.locator("[data-ap-field*='address']").count() == 0)
        C.check("spouse hint from the passport shown", "RAJESH SHARMA" in text and await page.locator("[data-ap-use-spouse]").count() == 1)
        C.check("every field says where it is used", await page.locator(".ap-where").count() >= 10)
        await page.click("[data-ap-use-spouse]")
        C.check("hint fills Married", await page.input_value("[data-ap-field='details.maritalStatus']") == "Married")
        C.check("hint fills spouse name", await page.input_value("[data-ap-field='details.spouseName']") == "RAJESH SHARMA")
        C.check("hint disappears once applied", await page.locator("[data-ap-use-spouse]").count() == 0)

        await page.fill("[data-ap-field='contact.phone']", "9811111111")
        await page.fill("[data-ap-field='contact.email']", "not-an-email")
        await page.click("[data-ap-save]")
        saved_email = await page.evaluate(f"KhannaState.getApplicantProfile('{profile_id}').contact.email")
        C.check("bad email is refused", saved_email == "")
        await page.fill("[data-ap-field='contact.email']", "anita@example.com")
        await page.fill("[data-ap-field='details.occupation']", "Software Engineer")
        await page.fill("[data-ap-field='details.employerName']", "Acme Corp")
        await page.fill("[data-ap-field='details.employerAddress']", "5 Business Park, Pune")
        await page.fill("[data-ap-field='details.employerPhone']", "02011112222")
        await page.fill("[data-ap-field='details.education']", "MBA")
        await page.fill("[data-ap-field='details.monthlyIncome']", "INR 90,000")
        await page.fill("[data-ap-field='details.emergencyName']", "Ravi Sharma")
        await page.click("[data-ap-save]")
        await page.wait_for_selector(".ap-saved:has-text('Saved')", timeout=5000)
        prof = await page.evaluate(f"KhannaState.getApplicantProfile('{profile_id}')")
        C.check("profile saved: occupation", prof["details"]["occupation"] == "Software Engineer")
        C.check("profile saved: phone and email", prof["contact"]["phone"] == "9811111111" and prof["contact"]["email"] == "anita@example.com")
        C.check("profile saved: marital status", prof["details"]["maritalStatus"] == "Married")
        app = await page.evaluate(f"KhannaState.getApplication('{app_id}').applicant")
        C.check("saved details copied onto the linked application", app["details"]["occupation"] == "Software Engineer" and app["contact"]["phone"] == "9811111111")
        C.check("passport data untouched by saving", app["passport"]["current"]["number"] == "Z1234567" and app["address"]["line1"] == "12 Sample Society")

        # a later passport save (same person, new application, blank basics) must not wipe the profile
        app2 = await page.evaluate("""(appId) => {
          const S = window.KhannaState; const b = S.createApplication('e2e');
          // the same passport read again: every passport field present, basic details blank
          const again = JSON.parse(JSON.stringify(S.getApplication(appId).applicant));
          again.details = S.createEmptyDetails(); again.contact = { phone: '', email: '' };
          S.updateApplication(b.id, { applicant: again });
          S.syncApplicantProfileFromApplication(b.id);
          return { id: b.id, applicant: S.getApplication(b.id).applicant,
                   profile: S.getApplicantProfile(S.getApplication(b.id).applicantId) };
        }""", app_id)
        C.check("same passport -> same profile", app2["profile"]["id"] == profile_id)
        C.check("saving again does not wipe the profile's details", app2["profile"]["details"]["occupation"] == "Software Engineer")
        C.check("...and the new application receives them", app2["applicant"]["details"]["occupation"] == "Software Engineer" and app2["applicant"]["contact"]["phone"] == "9811111111")

        # clearing a value on purpose works
        await page.evaluate("location.hash = '#/dashboard'")
        await page.evaluate("location.hash = '#/applicant-profiles'")
        await page.wait_for_selector("[data-ap-open]")
        await page.click("[data-ap-open]")
        await page.fill("[data-ap-field='details.education']", "")
        await page.click("[data-ap-save]")
        cleared = await page.evaluate(f"KhannaState.getApplicantProfile('{profile_id}').details.education")
        C.check("a value can be cleared on purpose", cleared == "")

        # ---------------------------------------------------------- Fill Forms
        await page.evaluate("location.hash = '#/fill-forms'")
        await page.wait_for_selector("[data-ff-profile-list]", timeout=15000)
        await page.click("[data-ff-profile-list]")
        await page.click(f"[data-ff-profile='{profile_id}']")
        await page.wait_for_timeout(300)
        C.check("Fill Forms: occupation from the profile", await page.input_value("#ff-occupation") == "Software Engineer")
        C.check("Fill Forms: employer name / tel / address", await page.input_value("#ff-employerName") == "Acme Corp"
                and await page.input_value("#ff-employerTel") == "02011112222" and "BUSINESS PARK" in (await page.input_value("#ff-employerAddress")).upper())
        C.check("Fill Forms: mobile from the profile", await page.input_value("#ff-mobile") == "9811111111")
        C.check("Fill Forms: marital status Married", await page.is_checked("input[name='ffr-maritalStatus'][value='married']"))
        C.check("Fill Forms: profile values tagged to verify", "From the applicant profile" in await page.inner_text("[data-view='fill-forms']"))
        C.check("Fill Forms: person card shows who it is for", "ANITA RAJ SHARMA" in await page.inner_text("[data-ff-person-card]"))
        addr = page.locator("#ff-homeAddress")
        C.check("address comes from the passport", (await addr.input_value()).startswith("12 Sample Society"), repr(await addr.input_value()))
        C.check("address box is locked", await addr.get_attribute("readonly") is not None)
        await page.click("[data-ff-unlock='homeAddress']")
        C.check("'Type it by hand' unlocks the address", await page.locator("#ff-homeAddress").get_attribute("readonly") is None)
        await page.fill("#ff-homeAddress", "Typed by hand")
        C.check("typed address is kept", await page.input_value("#ff-homeAddress") == "Typed by hand")
        await page.click("[data-ff-lock='homeAddress']")
        C.check("'Use the passport address' relocks and refills", (await page.input_value("#ff-homeAddress")).startswith("12 Sample Society")
                and await page.locator("#ff-homeAddress").get_attribute("readonly") is not None)


        # a person without saved details: the page says so
        other = await page.evaluate("""() => {
          const S = window.KhannaState; const b = S.createApplication('e2e');
          S.updateApplication(b.id, { applicant: { firstName: 'RAVI', lastName: 'MEHTA', fullName: 'RAVI MEHTA',
            passport: { current: { number: 'Y7654321' } } } });
          S.syncApplicantProfileFromApplication(b.id);
          return S.getApplication(b.id).applicantId; }""")
        await page.click("[data-ff-profile-list]")
        await page.click(f"[data-ff-profile='{other}']")
        await page.wait_for_timeout(300)
        C.check("switching person clears the previous person's details", await page.input_value("#ff-occupation") == "")
        C.check("...and the previous person's address", await page.input_value("#ff-homeAddress") == "")
        C.check("...and says what is missing, with a link to the profiles", "Not saved for this person yet" in await page.inner_text("[data-ff-person-card] + p"))
        C.check("...the locked address says what to do", "address" in (await page.inner_text("#ff-homeAddress ~ .vf-row-actions")).lower())

        # ---------------------------------------------------------- Cover letter
        await page.evaluate(f"""() => {{
          const S = window.KhannaState;
          S.updateApplication('{app_id}', {{ coverLetter: {{ selectedPersonIds: ['applicant'] }} }});
          S.setActiveApplicationId('{app_id}');
        }}""")
        await page.evaluate("location.hash = '#/cover-letter'")
        await page.wait_for_timeout(600)
        await select_cover_letter_country(page, "Japan")
        await page.wait_for_selector("[data-cover-field='japan:applicantEmployerOccupation']", timeout=10000)
        C.check("Cover Letter (Japan): occupation and employer filled from the profile",
                await page.input_value("[data-cover-field='japan:applicantEmployerOccupation']") == "Software Engineer at Acme Corp")
        C.check("Cover Letter: says where it came from (behind its ⓘ)", "Applicant Profiles" in await page.text_content("[data-view='cover-letter']"))
        await page.fill("[data-cover-field='japan:applicantEmployerOccupation']", "Typed here")
        await page.press("[data-cover-field='japan:applicantEmployerOccupation']", "Tab")
        await page.evaluate("location.hash = '#/dashboard'")
        await page.evaluate("location.hash = '#/cover-letter'")
        await page.wait_for_timeout(500)
        C.check("Cover Letter: a typed value is never overwritten",
                await page.input_value("[data-cover-field='japan:applicantEmployerOccupation']") == "Typed here")
        await select_cover_letter_country(page, "France")
        await page.wait_for_selector("[data-cover-field='europe:applicantJobTitle']", timeout=10000)
        C.check("Cover Letter (Europe): job title and employer filled",
                await page.input_value("[data-cover-field='europe:applicantJobTitle']") == "Software Engineer"
                and await page.input_value("[data-cover-field='europe:applicantEmployerName']") == "Acme Corp")

        # ---------------------------------------------------------- phone widths
        for width in (320, 375, 768):
            await page.set_viewport_size({"width": width, "height": 900})
            for view in ("applicant-profiles", "fill-forms"):
                await page.evaluate(f"location.hash = '#/{view}'")
                await page.wait_for_timeout(400)
                if view == "applicant-profiles":
                    if await page.locator("[data-ap-open]").count():
                        await page.locator("[data-ap-open]").first.click()
                        await page.wait_for_timeout(200)
                over = await page.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth")
                C.check(f"{view} @ {width}px: no horizontal overflow", over <= 1, str(over))

        C.check("no console errors", not errors, "; ".join(errors[:3]))
        await browser.close()
    C.report_and_exit()


asyncio.run(main())
