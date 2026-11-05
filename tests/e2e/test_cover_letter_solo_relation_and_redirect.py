"""
Cover Letter: one traveller, the relation between travellers, sentence case,
and what the Dashboard's eye icon does with an unfinished cover letter.

  * Europe (and Japan) letters can be generated for the applicant alone; the
    companion-only fields and the relation controls only exist when a
    companion is ticked.
  * "Relation between the travellers" is a dropdown (pre-selected from the
    traveller record), with an optional typed wording that wins; both change
    the sentence the real generated DOCX contains ("along with my wife, ...").
  * Places / typed details are tidied to sentence case ("MUMBAI" -> "Mumbai").
  * Dashboard eye on an INCOMPLETE cover letter opens the normal Cover Letter
    page (not the "nothing to preview" notice); on a COMPLETE one it opens the
    preview.

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
      fullName: "MIHIR HARILAL KOTAK", salutation: "Mr", sex: "M",
      passport: { current: { number: "Z1234567", issuePlace: "MUMBAI", issueDate: "2020-01-01" } },
      contact: { phone: "9876543210", email: "mihir.test@example.com" },
      address: Object.assign({}, a.applicant.address, { city: "MUMBAI", country: "INDIA" })
    }),
    coverLetter: {
      region: "Europe", country: "Belgium", selectedPersonIds: ["applicant"],
      consulateName: "The Consulate General of Belgium", consulateAddress: "Mumbai, India",
      recipientText: "The Consulate General of Belgium\\nMumbai, India",
      destinationCountry: "Belgium", travelStartDate: "__START__", travelEndDate: "__END__",
      fundingType: "self", fundingArrangement: "myself",
      europe: { cityOfResidence: "Mumbai", countryOfResidence: "India", numberOfNights: "10 nights",
                applicantEmploymentStatus: "Self-employed", applicantJobTitle: "Director", applicantEmployerName: "Acme Traders" }
    }
  }, "seed");
  var t = KhannaState.addTraveller(a.id, "Spouse");
  KhannaState.updateTraveller(a.id, t.id, { fullName: "PRIYA MIHIR KOTAK", sex: "F", passport: { current: { number: "Z7654321" } } }, "seed");
  return { id: a.id, traveller: t.id };
}""".replace("__START__", future_date(40)).replace("__END__", future_date(50))

VISIBLE_FIELDS = """() => {
  var sec = document.querySelector('.view.is-active');
  return Array.prototype.slice.call(sec.querySelectorAll('input:not([type=hidden]), select, textarea, [contenteditable=true]'))
    .filter(function (el) { return !el.closest('.doc-viewer') && el.offsetParent !== null && getComputedStyle(el).visibility !== 'hidden'; }).length;
}"""

GEN = "[data-action='generate-cover-letter']"
SCOPE = ".view.is-active [data-doc-preview]"


def docx_text(download_path_bytes: bytes) -> str:
    return "\n".join(p.text for p in Document(io.BytesIO(download_path_bytes)).paragraphs)


async def read_download(dl) -> bytes:
    path = await dl.path()
    with open(path, "rb") as fh:
        return fh.read()


async def wait_preview(page, timeout_ms=60000):
    await page.wait_for_selector(".view.is-active .doc-viewer__canvas:not([hidden])", timeout=timeout_ms)
    await page.wait_for_function(
        """() => { var st = document.querySelector('.view.is-active [data-dv=status]');
                   return !st || st.hidden || st.textContent.trim() === '' || getComputedStyle(st).display === 'none'; }""",
        timeout=timeout_ms,
    )


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page(viewport={"width": 1366, "height": 900})
        errors = []
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        page.on("pageerror", lambda e: errors.append(str(e)))
        await fresh_load_and_login(page, base=BASE)
        seeded = await page.evaluate(SEED)
        app_id, trav_id = seeded["id"], seeded["traveller"]
        await page.evaluate("(id) => KhannaState.setActiveApplicationId(id)", app_id)
        await page.evaluate("location.hash = '#/cover-letter'")
        await page.wait_for_timeout(800)

        # ---------- 1) the applicant alone ----------
        checks.check("applicant alone: Generate & Preview is enabled (no 'need a companion' rule)",
                     not await page.locator(GEN).is_disabled(), await page.inner_text("[data-cover-readiness]"))
        checks.check("no 'Can't generate yet' notice", (await page.inner_text("[data-cover-readiness]")).strip() == "")
        checks.check("companion-only fields are not shown", await page.locator("#cover-europe-companionJobTitle").count() == 0)
        checks.check("relation dropdown is not shown for one traveller", await page.locator("[data-cover-field='top:travellerRelation']").count() == 0)

        dl = await generate_and_download_docx(page, GEN, SCOPE)
        text = docx_text(await read_download(dl))
        checks.check("solo letter: written in the singular", "I reside in Mumbai, India" in text and "for me will be borne" in text and "grant me the necessary visa" in text, text[:900])
        checks.check("solo letter: no 'we / our / along with my <relation>'",
                     "We both" not in text and "I and my" not in text and "grant us" not in text, text[:900])
        checks.check("solo letter: place of issue in sentence case", "issued at Mumbai on" in text and "MUMBAI" not in text, text[:600])
        await page.wait_for_timeout(800)

        # ---------- 2) tick the companion ----------
        await page.locator(f"[data-person-id='{trav_id}']").check()
        await page.wait_for_timeout(400)
        checks.check("companion ticked: companion fields appear", await page.locator("#cover-europe-companionJobTitle").count() == 1)
        rel = "[data-cover-field='top:travellerRelation']"
        checks.check("relation dropdown appears", await page.locator(rel).count() == 1)
        opts = [o.strip() for o in await page.locator(f"{rel} option").all_inner_texts()]
        checks.check("dropdown offers family / friend / colleague style relations", "Family member" in opts and "Wife" in opts and "Husband" in opts and "Friend" in opts and "Business partner" in opts, str(opts))
        sel = (await page.locator(f"{rel} option:checked").inner_text()).strip()
        checks.check("pre-selected from the traveller record (Spouse + female -> Wife)", sel == "Wife", sel)
        hint = await page.inner_text("[data-cover-relation-preview]")
        checks.check("a live line shows how the letter will read", "along with my wife, Priya Mihir Kotak" in hint, hint)
        checks.check("Generate waits for the companion's job details", await page.locator(GEN).is_disabled())
        notice = await page.inner_text("[data-cover-readiness]")
        checks.check("...and the notice no longer talks about 'exactly one companion'", "exactly one" not in notice and "Companion job title" in notice, notice)

        await page.fill("#cover-europe-companionJobTitle", "Homemaker")
        await page.fill("#cover-europe-companionEmployerName", "n/a")
        await page.fill("#cover-europe-companionEmploymentStartYear", "2015")
        await page.press("#cover-europe-companionEmploymentStartYear", "Tab")
        await page.wait_for_timeout(300)
        checks.check("all filled: Generate enabled", not await page.locator(GEN).is_disabled(), await page.inner_text("[data-cover-readiness]"))

        # dropdown choice changes the sentence
        await page.select_option(rel, "Friend")
        await page.wait_for_timeout(300)
        hint = await page.inner_text("[data-cover-relation-preview]")
        checks.check("choosing Friend updates the line", "along with my friend" in hint, hint)
        dl = await generate_and_download_docx(page, GEN, SCOPE)
        text = docx_text(await read_download(dl))
        checks.check("DOCX says 'along with my friend, <name>'", "along with my friend, " in text and "While my friend is working for" in text, text[:900])
        checks.check("...and still names the companion", "Priya Mihir Kotak" in text, text[:900])

        # typed wording wins
        custom = "[data-cover-field='top:travellerRelationText']"
        await page.fill(custom, "business partner")
        await page.press(custom, "Tab")
        await page.wait_for_timeout(300)
        hint = await page.inner_text("[data-cover-relation-preview]")
        checks.check("typed wording overrides the dropdown in the live line", "along with my business partner" in hint, hint)
        dl = await generate_and_download_docx(page, GEN, SCOPE)
        text = docx_text(await read_download(dl))
        checks.check("DOCX uses the typed wording everywhere", "along with my business partner, " in text and "My business partner, " in text and "While my business partner is working for" in text, text[:1200])
        await page.wait_for_timeout(800)

        # ---------- 3) sentence case ----------
        city = "#cover-europe-cityOfResidence"
        await page.fill(city, "NAVI MUMBAI")
        await page.press(city, "Tab")
        await page.wait_for_timeout(300)
        checks.check("typed place is tidied to sentence case", await page.input_value(city) == "Navi Mumbai", await page.input_value(city))
        stored = await page.evaluate("(id) => KhannaState.getApplication(id).coverLetter.europe.cityOfResidence", app_id)
        checks.check("...and stored that way", stored == "Navi Mumbai", stored)
        job = "#cover-europe-applicantEmployerName"
        await page.fill(job, "TCS CONSULTANCY")
        await page.press(job, "Tab")
        await page.wait_for_timeout(300)
        checks.check("a long ALL-CAPITAL word in a typed detail is tidied, short abbreviations kept",
                     await page.input_value(job) == "TCS Consultancy", await page.input_value(job))
        dest = "[data-cover-field='top:destinationCountry']"
        await page.fill(dest, "BELGIUM")
        await page.press(dest, "Tab")
        await page.wait_for_timeout(200)
        checks.check("destination country in sentence case", await page.input_value(dest) == "Belgium", await page.input_value(dest))

        # un-tick the companion again: back to the solo form
        await page.locator(f"[data-person-id='{trav_id}']").uncheck()
        await page.wait_for_timeout(400)
        checks.check("unticking the companion removes the companion fields and the relation dropdown again",
                     await page.locator("#cover-europe-companionJobTitle").count() == 0 and await page.locator(rel).count() == 0)
        checks.check("...and the letter is still generatable", not await page.locator(GEN).is_disabled())
        await page.locator(f"[data-person-id='{trav_id}']").check()
        await page.wait_for_timeout(300)

        # ---------- 4) Japan, applicant alone ----------
        jp = await page.evaluate("""() => { var a = KhannaState.createApplication("customercare@khannatravels.com");
          KhannaState.updateApplication(a.id, { applicant: Object.assign({}, a.applicant, { fullName: "Jay Japan", passport: { current: { number: "J1111111" } } }),
            coverLetter: { region: "Japan", country: "Japan", selectedPersonIds: ["applicant"], recipientText: "The Consulate General of Japan\\nMumbai, India",
              destinationCountry: "Japan", travelStartDate: "__S__", travelEndDate: "__E__", fundingType: "self", fundingArrangement: "myself",
              japan: { applicantEmployerOccupation: "Engineer at Acme" } } }, "seed");
          return a.id }""".replace("__S__", future_date(40)).replace("__E__", future_date(45)))
        await page.evaluate("(id) => KhannaState.setActiveApplicationId(id)", jp)
        await page.evaluate("location.hash = '#/dashboard'")
        await page.wait_for_timeout(300)
        await page.evaluate("location.hash = '#/cover-letter'")
        await page.wait_for_timeout(800)
        checks.check("Japan: applicant alone -> Generate enabled and no companion occupation box",
                     not await page.locator(GEN).is_disabled() and await page.locator("#cover-japan-companionOccupation").count() == 0)
        dl = await generate_and_download_docx(page, GEN, SCOPE)
        text = docx_text(await read_download(dl))
        checks.check("Japan solo letter: no companion sentence, singular wording",
                     "along with my family" not in text and "I will be staying at the below hotels" in text and "All my travel expenses" in text, text[:900])
        await page.wait_for_timeout(800)

        # ---------- 5) Dashboard eye ----------
        # (a) INCOMPLETE: the Europe letter now has a companion without job details.
        await page.evaluate("""(id) => KhannaState.updateApplication(id, { coverLetter: { generatedAt: null, europe: { companionJobTitle: "", companionEmployerName: "", companionEmploymentStartYear: "" } } }, "seed")""", app_id)
        await page.evaluate("location.hash = '#/dashboard'")
        await page.wait_for_timeout(400)
        row = page.locator("[data-view='dashboard'] .dashboard-recent-row", has_text="Mihir Harilal Kotak")
        checks.check("dashboard lists the application under the sentence-case name", await row.count() >= 1)
        await row.first.locator("[data-action='dashboard-view-application']").click()
        await page.wait_for_selector(".view.is-active [data-cover-letter-card] .field", timeout=15000)
        await page.wait_for_timeout(600)
        hash_ = await page.evaluate("location.hash")
        checks.check("incomplete cover letter: eye opens the normal Cover Letter page (not /preview)", hash_ == "#/cover-letter", hash_)
        checks.check("...with the normal form visible", await page.evaluate(VISIBLE_FIELDS) > 5, str(await page.evaluate(VISIBLE_FIELDS)))
        checks.check("...not in preview mode", await page.evaluate("document.documentElement.getAttribute('data-doc-mode')") in ("", None))
        checks.check("...and the 'Working on' bar names the applicant", "mihir" in (await page.inner_text(".view.is-active [data-doc-page-app-bar]")).lower())
        pv_notice = await page.evaluate("""() => { var n = document.querySelector('.view.is-active [data-pv-notice]'); return !n || n.hidden }""")
        checks.check("...and no 'nothing to preview yet' error is shown", pv_notice is True)
        checks.check("the saved partial details are all still there", await page.input_value("#cover-europe-applicantJobTitle") == "Director")

        # (b) COMPLETE: fill the missing details and generate -> eye opens the preview.
        await page.fill("#cover-europe-companionJobTitle", "Homemaker")
        await page.fill("#cover-europe-companionEmployerName", "n/a")
        await page.fill("#cover-europe-companionEmploymentStartYear", "2015")
        await page.press("#cover-europe-companionEmploymentStartYear", "Tab")
        await page.wait_for_timeout(300)
        await page.click(GEN)
        await wait_preview(page)
        await page.wait_for_timeout(1200)
        await page.evaluate("location.hash = '#/dashboard'")
        await page.wait_for_timeout(400)
        await page.locator("[data-view='dashboard'] .dashboard-recent-row", has_text="Mihir Harilal Kotak").first.locator("[data-action='dashboard-view-application']").click()
        await wait_preview(page)
        hash_ = await page.evaluate("location.hash")
        checks.check("complete cover letter: eye still opens the preview", hash_ == "#/cover-letter/preview", hash_)
        checks.check("...preview only (no form fields)", await page.evaluate(VISIBLE_FIELDS) == 0, str(await page.evaluate(VISIBLE_FIELDS)))

        # (c) A partial application can be saved: Save works with half a letter.
        await page.evaluate("location.hash = '#/cover-letter'")
        await page.wait_for_timeout(600)
        await page.click(".view.is-active [data-action='save-doc-application']")
        await page.wait_for_timeout(400)
        saved = await page.evaluate("(id) => !!KhannaState.getApplication(id).explicitlySavedAt", app_id)
        checks.check("Save works on a cover letter", saved)

        checks.check("no console errors", not errors, "; ".join(errors[:3]))
        await browser.close()
    checks.report_and_exit()


if __name__ == "__main__":
    asyncio.run(main())
