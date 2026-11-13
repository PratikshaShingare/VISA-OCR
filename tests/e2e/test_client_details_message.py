"""
End-to-end: the "Get basic details from the client" messages and the
dashboard workflow guide.

- Applicant Profiles: the Singapore / Japan message is built with the
  applicant's name; a pasted reply (two applicants, WhatsApp style) is read,
  matched to the saved profiles by name, checked and saved.
- One profile's page: a reply goes into its fields as an unsaved change.
- Fill Forms (Singapore): the saved answers fill email, phone, occupation,
  qualification tick, SGD income, religion and the "resided abroad" tick.
- Dashboard: "How it works" shows the six steps, can be hidden; pages show
  "Step N of 6".
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
  const a = S.saveApplicantProfile({ fullName: 'ANITA RAJ SHARMA', firstName: 'ANITA RAJ', lastName: 'SHARMA', dob: '1980-05-14', nationality: 'INDIAN',
    passport: { current: { number: 'Z1234567', issueDate: '2020-01-10', expiryDate: '2035-01-09', issuePlace: 'MUMBAI', type: 'P' } } });
  const b = S.saveTravellerProfile({ fullName: 'RAVI KUMAR SHARMA', firstName: 'RAVI KUMAR', lastName: 'SHARMA', dob: '1978-02-03',
    passport: { current: { number: 'Z7654321' } } });
  const c = S.saveApplicantProfile({ fullName: 'MEERA SAMPLE', passport: { current: { number: 'M1112223' } } });
  return [a.id, b.id, c.id];
}"""

SG_REPLY = """[12/11/26, 10:30 am] Client: Please help me with below details for Singapore Visa form filling -

Applicant Name: Anita Raj Sharma

1) Email Address: Anita.Test@Example.com
2) Contact Number: +91 98000 00000
3) Occupation: Business owner
4) Highest Qualifications Attained: B.Com
5) Annual Income in Singapore dollars: SGD 25,000
6) Religion: Hindu
7) Did you reside in other countries/places, other than your country/place of origin, for one year or more during the last 5 years? No

Applicant Name: Ravi Sharma
1) Email Address:
ravi@example.com
2) Contact Number: 98111 22222
3) Occupation: Engineer
7) Did you reside in other countries? Yes, Dubai 2020-2022"""

JP_REPLY = """Please share details for Japan Visa form filling-
Applicant Name: Meera Sample
* Phone No - 9876543210
* Email ID - meera@example.com
* Occupation - Doctor
* Married - yes
* Ever visited Japan Visa - Yes, May 2019 for 7 days
* Sponsor Phone Number - 9123456789
* Sponsor Email id - sponsor@example.com
* Sponsors Occupation - Retired"""

PROFILE = """(no) => {
  const all = window.KhannaState.getApplicantProfiles().concat(window.KhannaState.getTravellerProfiles());
  const p = all.find(x => ((x.passport || {}).current || {}).number === no);
  return p ? Object.assign({}, p.details, p.contact) : null;
}"""


async def shot(page, name):
    if SHOTS:
        await page.screenshot(path=os.path.join(SHOTS, name + ".png"), full_page=True)


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        ctx = await browser.new_context(viewport={"width": 1280, "height": 900})
        await ctx.grant_permissions(["clipboard-read", "clipboard-write"])
        page = await ctx.new_page()
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        await fresh_load_and_login(page)

        # ---- Dashboard guide ----
        await page.evaluate("location.hash = '#/dashboard'")
        await page.wait_for_selector("[data-wf-show]")
        C.check("dashboard shows only 'Show how it works' at first", await page.locator(".wf-step").count() == 0)
        await page.click("[data-wf-show]")
        C.check("dashboard shows the six workflow steps", await page.locator(".wf-step").count() == 6)
        C.check("each step links to its page", await page.locator(".wf-step a[data-nav-link='applicant-profiles']").count() == 1
                and await page.locator(".wf-step a[data-nav-link='fill-forms']").count() == 1)
        await page.reload()
        await page.wait_for_selector(".wf-step", timeout=10000)
        C.check("opened guide stays open after reload", await page.locator(".wf-step").count() == 6)
        await page.click("[data-wf-hide]")
        C.check("guide can be hidden again", await page.locator(".wf-step").count() == 0 and await page.locator("[data-wf-show]").count() == 1)
        await page.click("[data-wf-show]")
        await page.click(".wf-step a[data-nav-link='hotel-blocking']")
        await page.wait_for_selector("[data-wf-strip='hotel-blocking']")
        C.check("Hotel Blocking shows step 3 of 6", "Step 3 of 6" in await page.text_content("[data-wf-strip='hotel-blocking']"))
        C.check("current step marked", (await page.text_content("[data-wf-strip='hotel-blocking'] [aria-current='step']")).strip() == "3Hotel")

        ids = await page.evaluate(SEED)

        # ---- Ask: the message ----
        await page.evaluate("location.hash = '#/applicant-profiles'")
        await page.wait_for_selector("[data-cdm-toggle]")
        await page.click("[data-cdm-toggle]")
        await page.select_option("[data-cdm-applicant]", ids[0])
        msg = await page.input_value("[data-cdm-message]")
        C.check("Singapore message with the applicant's name", msg.startswith("Please help me with below details for Singapore Visa form filling") and "Applicant Name: ANITA RAJ SHARMA" in msg and "7) Did you reside" in msg)
        await page.select_option("[data-cdm-country]", "japan")
        msg = await page.input_value("[data-cdm-message]")
        C.check("Japan message", msg.startswith("Please share details for Japan Visa form filling") and "* Sponsors Occupation -" in msg)
        C.check("WhatsApp link carries the message", "wa.me/?text=Please%20share%20details" in (await page.get_attribute("[data-cdm-whatsapp]", "href") or ""))
        await page.click("[data-cdm-copy]")
        await page.wait_for_timeout(200)
        clip = await page.evaluate("navigator.clipboard.readText()")
        C.check("Copy puts the message on the clipboard", clip == msg)

        # ---- Reply: two applicants ----
        await page.fill("[data-cdm-reply]", SG_REPLY)
        await page.click("[data-cdm-read]")
        await page.wait_for_selector("[data-cdm-result='1']")
        await shot(page, "profiles_reply_read")
        C.check("reply read for two applicants", await page.locator("[data-cdm-result]").count() == 2)
        C.check("first matched to ANITA by name", await page.input_value("[data-cdm-profile='0']") == ids[0])
        C.check("'Ravi Sharma' matched to RAVI KUMAR SHARMA", await page.input_value("[data-cdm-profile='1']") == ids[1])
        C.check("email tidied", await page.input_value("#cdm-0-contact-email") == "anita.test@example.com")
        C.check("SGD income without the currency", await page.input_value("#cdm-0-details-annualIncomeSgd") == "25,000")
        C.check("answer on the next line read", await page.input_value("#cdm-1-contact-email") == "ravi@example.com")
        C.check("'Yes, Dubai…' kept with the details", await page.input_value("#cdm-1-details-residedAbroad") == "Yes — Dubai 2020-2022")
        C.check("check-before-saving note shown", await page.locator("text=please check every value before saving").count() == 1)
        await page.fill("#cdm-0-details-religion", "Hinduism")
        await page.click("[data-cdm-save='0']")
        prof = await page.evaluate(PROFILE, "Z1234567")
        C.check("saved to the profile (with the staff correction)", prof and prof["email"] == "anita.test@example.com" and prof["religion"] == "Hinduism"
                and prof["education"] == "B.Com" and prof["annualIncomeSgd"] == "25,000" and prof["residedAbroad"] == "No" and prof["phone"] == "+91 98000 00000", str(prof))
        await page.click("[data-cdm-save='1']")
        prof = await page.evaluate(PROFILE, "Z7654321")
        C.check("second applicant saved to the traveller profile", prof and prof["occupation"] == "Engineer" and prof["residedAbroad"].startswith("Yes"), str(prof))
        C.check("'Open profile' offered after saving", await page.locator("[data-cdm-open-profile]").count() == 2)

        # A name with no saved profile: "+ New applicant" is chosen, the profile is created on Save.
        await page.fill("[data-cdm-reply]", "Applicant Name: Mandar Test\n1) Email Address: mandar@example.com\n2) Contact Number: 9820012345\n3) Occupation: Chief Manager")
        await page.click("[data-cdm-read]")
        await page.wait_for_selector("[data-cdm-result='0']")
        C.check("unknown name: '+ New applicant' selected", await page.input_value("[data-cdm-profile='0']") == "__new__")
        C.check("new applicant name box prefilled", await page.input_value("[data-cdm-new-name='0']") == "Mandar Test")
        before = await page.evaluate("window.KhannaState.getApplicantProfiles().length")
        await page.click("[data-cdm-save='0']")
        made = await page.evaluate("""() => { const p = window.KhannaState.getApplicantProfiles().find(x => x.fullName === 'MANDAR TEST');
            return p ? { phone: p.contact.phone, email: p.contact.email, occ: p.details.occupation } : null; }""")
        C.check("new applicant profile created with the details", made == {"phone": "9820012345", "email": "mandar@example.com", "occ": "Chief Manager"}, str(made))
        C.check("one new profile", await page.evaluate("window.KhannaState.getApplicantProfiles().length") == before + 1)
        joined = await page.evaluate("""() => { const S = window.KhannaState;
            S.saveApplicantProfile({ fullName: 'TEST MANDAR', firstName: 'MANDAR', lastName: 'TEST', dob: '1985-01-01', passport: { current: { number: 'N5555555' } } });
            const all = S.getApplicantProfiles().filter(x => /MANDAR/.test(x.fullName));
            return { count: all.length, phone: all[0].contact.phone, passport: all[0].passport.current.number }; }""")
        C.check("passport saved later joins that profile (no duplicate)", joined == {"count": 1, "phone": "9820012345", "passport": "N5555555"}, str(joined))
        await page.click("[data-cdm-clear]")

        # Bad email is refused.
        await page.fill("[data-cdm-reply]", "Applicant Name: Meera Sample\n* Email ID - not-an-email\n* Occupation - Doctor")
        await page.click("[data-cdm-read]")
        await page.wait_for_selector("[data-cdm-result='0']")
        await page.click("[data-cdm-save='0']")
        prof = await page.evaluate(PROFILE, "M1112223")
        C.check("a wrong email is not saved", not prof.get("occupation"), str(prof))

        # Screenshot read by OCR: question 7 wraps onto a second line (with a stray quote), labels with OCR typos.
        ocr = await page.evaluate("""() => window.KhannaClientMessages.read(
          "Applicant Name: Rahul Test\\n1} Emall Address: rahul.test@example.com\\n2) Contact Nurnber: 98200 12345\\n" +
          "3) Occupation: Chief Manager\\n4) Highest Qualifications Attained: Bachelor's of Science\\n" +
          "5) Annual income in Singapore dollars: 25000\\n6) Religion: Hindu\\n" +
          "7) Did you reside in other countries/places, other than your country/place of origin, for one year or\\n" +
          "\u2018more during the last 5 years? No").applicants[0].values""")
        C.check("OCR reply: all 7 answers read", len(ocr) == 7, str(ocr))
        C.check("OCR reply: wrapped question 7 answered No", ocr.get("details.residedAbroad") == "No", str(ocr))
        C.check("OCR reply: labels with OCR typos still read", ocr.get("contact.email") == "rahul.test@example.com" and ocr.get("contact.phone") == "98200 12345", str(ocr))

        # Email / phone that OCR put on their own lines, away from the labels: found and flagged.
        loose = await page.evaluate("""() => window.KhannaClientMessages.read(
          "Applicant Name: Rahul Test\\n1) Email Address:\\n2) Contact Number:\\n3) Occupation: Chief Manager\\n" +
          "7) Did you reside in other countries/places, other than your country/place of origin, for one year or more during the last 5 years? No\\n" +
          "rahul.test@gmail,com\\n+91 98200 12345").applicants[0]""")
        C.check("loose email and phone picked up", loose["values"].get("contact.email") == "rahul.test@gmail.com" and loose["values"].get("contact.phone") == "+91 98200 12345", str(loose["values"]))
        C.check("loose values flagged for checking", all("not next to its label" in r["note"] for r in loose["rows"] if r["field"] in ("contact.email", "contact.phone")))

        # ---- One profile's page: reply fills the fields, unsaved ----
        await page.click("[data-cdm-clear]")
        await page.click(f"[data-ap-open='{ids[2]}']")
        await page.wait_for_selector("[data-ap-save]")
        name = await page.inner_text(".ap-name")
        C.check("profile page opened (Meera)", "MEERA SAMPLE" in name, name)
        await page.click("[data-cdm-toggle]")
        msg = await page.input_value("[data-cdm-message]")
        C.check("profile page message carries this name", "Applicant Name: MEERA SAMPLE" in msg)
        await page.fill("[data-cdm-reply]", JP_REPLY)
        await page.click("[data-cdm-read]")
        await page.wait_for_timeout(200)
        C.check("fields filled from the reply", await page.input_value("#ap-occupation") == "Doctor" and await page.input_value("#ap-maritalStatus") == "Married"
                and await page.input_value("#ap-visitedJapan") == "Yes — May 2019 for 7 days" and await page.input_value("#ap-sponsorOccupation") == "Retired")
        C.check("marked as from the reply, not saved yet", await page.locator(".ap-from-reply").count() >= 6 and "Not saved yet" in await page.inner_text(".ap-saved"))
        await shot(page, "profile_reply_filled")
        prof = await page.evaluate(PROFILE, "M1112223")
        C.check("nothing saved before Save profile", not prof.get("occupation"))
        await page.click("[data-ap-save]")
        prof = await page.evaluate(PROFILE, "M1112223")
        C.check("Save profile saves the reply", prof["occupation"] == "Doctor" and prof["sponsorPhone"] == "9123456789" and prof["email"] == "meera@example.com", str(prof))

        # ---- Fill Forms reads the saved answers ----
        await page.evaluate("location.hash = '#/fill-forms'")
        await page.wait_for_selector("[data-ff-form]", timeout=15000)
        await page.select_option("[data-ff-form]", "singapore-visa")
        await page.wait_for_selector("#ff-fullName")
        await page.click("[data-ff-profile-list]")
        await page.click(f"[data-ff-profile='{ids[0]}']")
        await page.wait_for_timeout(300)
        C.check("form: email from the reply", await page.input_value("#ff-email") == "anita.test@example.com", await page.input_value("#ff-email"))
        C.check("form: occupation", await page.input_value("#ff-occupation") == "Business owner")
        C.check("form: B.Com ticks University", await page.is_checked("input[name='ffr-education'][value='university']"))
        C.check("form: SGD income", await page.input_value("#ff-annualIncome") == "25,000")
        C.check("form: religion", (await page.input_value("#ff-religion")).upper() == "HINDUISM")
        C.check("form: resided abroad 'No' ticked", await page.is_checked("input[name='ffr-residedAbroad'][value='no']"))

        for width in (320, 390, 768):
            await page.set_viewport_size({"width": width, "height": 800})
            for view in ("applicant-profiles", "dashboard", "hotel-blocking", "fill-forms"):
                await page.evaluate(f"location.hash = '#/{view}'")
                await page.wait_for_timeout(250)
                if view == "applicant-profiles" and await page.locator("[data-cdm-toggle][aria-expanded='false']").count():
                    await page.click("[data-cdm-toggle]")
                overflow = await page.evaluate("document.documentElement.scrollWidth - innerWidth")
                C.check(f"no horizontal overflow on {view} at {width}px", overflow <= 1, str(overflow))
        C.check("no page errors", not errors, " | ".join(errors[:3]))
        await browser.close()
    C.report_and_exit()


if __name__ == "__main__":
    asyncio.run(main())
