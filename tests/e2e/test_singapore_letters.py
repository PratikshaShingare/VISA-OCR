"""
Singapore letters: the cover letter form and the two authorization pages
switch to Singapore's own templates.

  * Cover letter, applicant alone  -> single-traveller template: no consulate
    boxes (the template carries the address), an Occupation box that the
    "I am currently ..." sentence needs, no passenger table.
  * One companion ticked          -> multi-traveller template: relation box,
    passenger table, "me & my wife".
  * Two companions ticked         -> one relation card per companion,
    "me & my family", three table rows.
  * Passport Authorization page   -> "Authorisation Letter for Visa Application"
    when the application's destination is Singapore (and the standard letter
    otherwise); the Letter format box switches it by hand.
  * Company Authorization page    -> "Sub-Agent Declaration Form".

All names / numbers are obviously synthetic (project rule 11).
Requires the static server and the backend (see run_e2e_suite.py).
"""

import asyncio
import io

from docx import Document
from playwright.async_api import async_playwright

from _common import BASE, Checks, fresh_load_and_login, future_date, generate_and_download_docx

checks = Checks()

SEED = """() => {
  var a = KhannaState.createApplication("customercare@khannatravels.com");
  KhannaState.updateApplication(a.id, {
    applicant: Object.assign({}, a.applicant, {
      fullName: "TEST APPLICANT ONE", salutation: "Mr", sex: "M",
      passport: { current: { number: "X1234567", issuePlace: "MUMBAI", issueDate: "2020-01-05" } },
      contact: { phone: "9876543210", email: "applicant.test@example.com" }
    }),
    travel: Object.assign({}, a.travel, { destination: "Singapore" }),
    coverLetter: {
      region: "Singapore", country: "Singapore", selectedPersonIds: ["applicant"],
      travelStartDate: "__START__", travelEndDate: "__END__",
      fundingType: "self", fundingArrangement: "myself",
      singapore: { hotelName: "Test Hotel", hotelAddress: "1 Test Road, Singapore 000000", occupations: {} }
    }
  }, "seed");
  var w = KhannaState.addTraveller(a.id, "Spouse");
  KhannaState.updateTraveller(a.id, w.id, { fullName: "TEST SPOUSE TWO", sex: "F", salutation: "Mrs", passport: { current: { number: "Y7654321" } } }, "seed");
  var c = KhannaState.addTraveller(a.id, "Child");
  KhannaState.updateTraveller(a.id, c.id, { fullName: "TEST CHILD THREE", sex: "M", salutation: "Mstr", passport: { current: { number: "Z1111111" } } }, "seed");
  return { id: a.id, wife: w.id, child: c.id };
}""".replace("__START__", future_date(40)).replace("__END__", future_date(46))

GEN = "[data-action='generate-cover-letter']"
AUTH_GEN_PASSPORT = ".view.is-active [data-action='generate-authorization'][data-group='passport']"
AUTH_GEN_COMPANY = ".view.is-active [data-action='generate-authorization'][data-group='company']"
SCOPE = ".view.is-active [data-doc-preview]"


async def read_download(dl) -> bytes:
    with open(await dl.path(), "rb") as fh:
        return fh.read()


def doc_text(data: bytes) -> str:
    doc = Document(io.BytesIO(data))
    parts = [p.text for p in doc.paragraphs]
    for table in doc.tables:
        for row in table.rows:
            parts.append(" | ".join(c.text.strip() for c in row.cells))
    return "\n".join(parts)


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page(viewport={"width": 1366, "height": 900})
        errors = []
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        page.on("pageerror", lambda e: errors.append(str(e)))
        await fresh_load_and_login(page, base=BASE)
        seeded = await page.evaluate(SEED)
        app_id, wife, child = seeded["id"], seeded["wife"], seeded["child"]
        await page.evaluate("(id) => KhannaState.setActiveApplicationId(id)", app_id)
        await page.evaluate("location.hash = '#/cover-letter'")
        await page.wait_for_timeout(900)

        # ---------- 1) applicant alone: the single-traveller letter ----------
        checks.check("no consulate name / address boxes for Singapore",
                     await page.locator("[data-cover-field='top:consulateName']").count() == 0
                     and await page.locator("[data-cover-field='top:consulateAddress']").count() == 0)
        checks.check("hotel name and address boxes are there",
                     await page.locator("[data-cover-field='singapore:hotelName']").count() == 1
                     and await page.locator("[data-cover-field='singapore:hotelAddress']").count() == 1)
        checks.check("no relation box for one traveller", await page.locator("[data-cover-field='top:travellerRelation']").count() == 0)
        occ = "[data-cover-occupation='applicant']"
        checks.check("one Occupation box for the applicant, marked required",
                     await page.locator(occ).count() == 1 and "Occupation *" in await page.inner_text("label[for='cover-occupation-applicant']"))
        checks.check("Generate waits for the occupation", await page.locator(GEN).is_disabled())
        notice = await page.inner_text("[data-cover-readiness]")
        checks.check("...and says why", "occupation" in notice.lower(), notice)

        await page.fill(occ, "a student at Test College")
        await page.press(occ, "Tab")
        await page.wait_for_timeout(300)
        checks.check("occupation entered: Generate is enabled", not await page.locator(GEN).is_disabled(), await page.inner_text("[data-cover-readiness]"))

        dl = await generate_and_download_docx(page, GEN, SCOPE)
        data = await read_download(dl)
        text = doc_text(data)
        checks.check("single letter: no passenger table", not Document(io.BytesIO(data)).tables)
        checks.check("single letter: passport sentence", "Mr. Test Applicant One (holding Indian Passport No.: X1234567 issued at Mumbai on 05/01/2020)" in text, text[:800])
        checks.check("single letter: occupation sentence", "I am currently a student at Test College." in text, text)
        checks.check("single letter: hotel, funding and closing", "I will be staying at Test Hotel - 1 Test Road, Singapore 000000." in text
                     and "will be borne by me." in text and "Phone No.: +91 9876543210" in text, text)
        checks.check("single letter: fixed consulate address", "Maker Chambers IV" in text and "Mumbai - 400021" in text)
        await page.wait_for_timeout(600)

        # ---------- 2) one companion: the multi-traveller letter ----------
        await page.locator(f"[data-person-id='{wife}']").check()
        await page.wait_for_timeout(400)
        rel = "[data-cover-field='top:travellerRelation']"
        checks.check("one companion: relation dropdown appears", await page.locator(rel).count() == 1)
        sel = (await page.locator(f"{rel} option:checked").inner_text()).strip()
        checks.check("...pre-selected Wife from the traveller record", sel == "Wife", sel)
        hint = await page.inner_text("[data-cover-relation-preview]")
        checks.check("...with a live line naming the table entry", "for me & my wife" in hint and "“Wife”" in hint, hint)
        checks.check("occupation boxes now one per traveller, optional",
                     await page.locator("[data-cover-occupation]").count() == 2)
        checks.check("still generatable", not await page.locator(GEN).is_disabled(), await page.inner_text("[data-cover-readiness]"))
        await page.fill(f"[data-cover-occupation='{wife}']", "Homemaker")
        await page.press(f"[data-cover-occupation='{wife}']", "Tab")
        await page.wait_for_timeout(300)

        dl = await generate_and_download_docx(page, GEN, SCOPE)
        data = await read_download(dl)
        text = doc_text(data)
        checks.check("multi letter: subject and sentence say 'my wife'",
                     "Sub: Request for issue of Tourism Visa for me & my wife" in text and "along with my wife & would like to travel on" in text, text[:900])
        checks.check("multi letter: passenger table has both travellers",
                     "1 | Mr. Test Applicant One | X1234567 | Self | a student at Test College" in text
                     and "2 | Mrs. Test Spouse Two | Y7654321 | Wife | Homemaker" in text, text)
        checks.check("multi letter: funding and bank statement", "will be borne by me." in text and "bank statement of my bank account" in text, text)
        await page.wait_for_timeout(600)

        # a typed relation wins
        custom = "[data-cover-field='top:travellerRelationText']"
        await page.fill(custom, "business partner")
        await page.press(custom, "Tab")
        await page.wait_for_timeout(300)
        dl = await generate_and_download_docx(page, GEN, SCOPE)
        text = doc_text(await read_download(dl))
        checks.check("typed relation reaches the subject and the table",
                     "for me & my business partner" in text and "Business partner" in text, text[:900])
        await page.fill(custom, "")
        await page.press(custom, "Tab")
        await page.wait_for_timeout(300)
        await page.wait_for_timeout(600)

        # ---------- 3) two companions ----------
        await page.locator(f"[data-person-id='{child}']").check()
        await page.wait_for_timeout(400)
        checks.check("two companions: one relation card each",
                     await page.locator("[data-cover-companion-card]").count() == 2)
        checks.check("...and the single relation box is gone", await page.locator(rel).count() == 0)
        card_hint = await page.inner_text(f"[data-cover-companion-preview='{child}']")
        checks.check("...child card previews the table entry", "“Son”" in card_hint, card_hint)
        checks.check("three occupation boxes", await page.locator("[data-cover-occupation]").count() == 3)
        dl = await generate_and_download_docx(page, GEN, SCOPE)
        text = doc_text(await read_download(dl))
        checks.check("several travellers: 'me & my family' and three rows",
                     "for me & my family" in text and "3 | Mstr. Test Child Three | Z1111111 | Son |" in text, text)
        await page.wait_for_timeout(600)

        # sponsor changes the funding + bank statement wording
        fund = "[data-cover-field='top:fundingType']"
        await page.select_option(fund, "other")
        await page.wait_for_timeout(300)
        await page.fill("[data-cover-field='top:fundingPayerName']", "Test Payer")
        await page.select_option("[data-cover-field='top:fundingRelationChoice']", "Father")
        await page.wait_for_timeout(300)
        dl = await generate_and_download_docx(page, GEN, SCOPE)
        text = doc_text(await read_download(dl))
        checks.check("a sponsor is named and the bank statement is theirs",
                     "will be borne by Test Payer (Father)." in text and "bank statement of Test Payer's bank account" in text, text)

        # ---------- 4) other countries are untouched ----------
        eu = await page.evaluate("""() => { var a = KhannaState.createApplication("customercare@khannatravels.com");
          KhannaState.updateApplication(a.id, { applicant: Object.assign({}, a.applicant, { fullName: "Eve Europe", passport: { current: { number: "E1111111" } } }),
            coverLetter: { region: "Europe", country: "France", selectedPersonIds: ["applicant"] } }, "seed"); return a.id }""")
        await page.evaluate("(id) => KhannaState.setActiveApplicationId(id)", eu)
        await page.evaluate("location.hash = '#/dashboard'")
        await page.wait_for_timeout(300)
        await page.evaluate("location.hash = '#/cover-letter'")
        await page.wait_for_timeout(800)
        checks.check("Europe still shows its consulate boxes and no Singapore occupation list",
                     await page.locator("[data-cover-field='top:consulateName']").count() == 1
                     and await page.locator("[data-cover-occupation]").count() == 0)

        # ---------- 5) Authorization pages ----------
        await page.evaluate("(id) => KhannaState.setActiveApplicationId(id)", app_id)
        await page.evaluate("location.hash = '#/passport-authorization'")
        await page.wait_for_timeout(900)
        pcountry = "#auth-passport-country"
        checks.check("no 'Letter format' box any more", await page.locator("[data-auth-format]").count() == 0)
        checks.check("Singapore application: Passport page selects Singapore by itself",
                     await page.input_value(pcountry) == "Singapore"
                     and await page.locator("[data-auth-field='passport:representativeName']").count() == 1)
        checks.check("...no centre / collector boxes", await page.locator("[data-auth-field='passport:recipientCentreName']").count() == 0)
        checks.check("...representative box starts with the form's default",
                     (await page.input_value("[data-auth-field='passport:representativeName']")).strip() != "")
        for pid in ("applicant", wife):
            await page.locator(f".view.is-active [data-auth-person][data-person-id='{pid}']").check()
        await page.wait_for_timeout(300)
        checks.check("two people ticked: Generate is enabled without any centre or collector",
                     not await page.locator(AUTH_GEN_PASSPORT).is_disabled(), await page.inner_text("[data-auth-readiness='passport']"))
        await page.fill("[data-auth-field='passport:feePerApplicant']", "8000")
        await page.press("[data-auth-field='passport:feePerApplicant']", "Tab")
        await page.wait_for_timeout(300)
        dl = await generate_and_download_docx(page, AUTH_GEN_PASSPORT, ".view.is-active [data-doc-preview='passport']")
        text = doc_text(await read_download(dl))
        checks.check("Authorisation Letter: one name, every passport number",
                     "AUTHORISATION LETTER FOR VISA APPLICATION" in text and "I, Mr. Test Applicant One, holder of" in text
                     and "Test Spouse Two" not in text and "X1234567 and Y7654321" in text, text[:900])
        checks.check("Authorisation Letter: fee is 8000 x 2", "Visa Application Fee: INR 16000/- Pax - 02" in text, text)

        # choosing another country by hand switches the letter by itself
        await page.fill(pcountry, "Germany")
        await page.click(".view.is-active [data-ccombo-option='Germany']")
        await page.wait_for_timeout(400)
        checks.check("choosing Germany brings the centre / collector boxes back",
                     await page.locator("[data-auth-field='passport:recipientCentreName']").count() == 1
                     and await page.locator("[data-auth-field='passport:representativeName']").count() == 0)
        await page.fill(pcountry, "Singapore")
        await page.click(".view.is-active [data-ccombo-option='Singapore']")
        await page.wait_for_timeout(400)
        checks.check("choosing Singapore again returns to the Singapore letter",
                     await page.locator("[data-auth-field='passport:representativeName']").count() == 1)
        for pid in ("applicant", wife):
            if not await page.locator(f".view.is-active [data-auth-person][data-person-id='{pid}']").is_checked():
                await page.locator(f".view.is-active [data-auth-person][data-person-id='{pid}']").check()
        await page.fill("[data-auth-field='passport:feePerApplicant']", "8000")
        await page.press("[data-auth-field='passport:feePerApplicant']", "Tab")

        await page.evaluate("location.hash = '#/company-authorization'")
        await page.wait_for_timeout(900)
        checks.check("Company page selects Singapore by itself (Sub-Agent Declaration Form)",
                     await page.input_value("#auth-company-consulateCountry") == "Singapore"
                     and await page.locator("[data-auth-field='company:contactPerson']").count() == 1
                     and await page.locator("[data-auth-field='company:consulateAddress']").count() == 0)
        for pid in ("applicant", wife, child):
            await page.locator(f".view.is-active [data-auth-person][data-person-id='{pid}']").check()
        await page.wait_for_timeout(300)
        checks.check("three people ticked: Generate is enabled", not await page.locator(AUTH_GEN_COMPANY).is_disabled(),
                     await page.inner_text("[data-auth-readiness='company']"))
        dl = await generate_and_download_docx(page, AUTH_GEN_COMPANY, ".view.is-active [data-doc-preview='company']")
        text = doc_text(await read_download(dl))
        checks.check("Sub-Agent Declaration: count and passport list",
                     "SUB-AGENT DECLARATION FORM" in text and "Total Number of Applications: 3" in text
                     and "1. X1234567" in text and "3. Z1111111" in text, text[:900])

        # a non-Singapore application keeps the standard letter by default
        await page.evaluate("(id) => KhannaState.setActiveApplicationId(id)", eu)
        await page.evaluate("location.hash = '#/dashboard'")
        await page.wait_for_timeout(300)
        await page.evaluate("location.hash = '#/company-authorization'")
        await page.wait_for_timeout(800)
        checks.check("non-Singapore application: Company page stays on the standard letter",
                     await page.locator("[data-auth-field='company:contactPerson']").count() == 0
                     and await page.locator("[data-auth-field='company:consulateAddress']").count() == 1)

        real_errors = [e for e in errors if "favicon" not in e.lower()]
        checks.check("no browser console errors", not real_errors, "; ".join(real_errors)[:500])
        await browser.close()
    checks.report_and_exit()


if __name__ == "__main__":
    asyncio.run(main())
