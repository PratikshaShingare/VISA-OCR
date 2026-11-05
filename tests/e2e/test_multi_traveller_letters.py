"""
Any number of travellers on every letter (Stage 2).

  * Cover Letter, Europe and Japan: more than the applicant + one companion
    can be ticked (nothing is disabled), each extra companion gets a card
    with their own relation (pre-filled from the traveller record), and the
    real generated .docx names every person with the right relation.
  * Passport Authorization Letter: three travellers on one letter, all
    passport numbers in the real generated .docx.
  * Invitation Letter: three invitees (and the exactly-two wording is kept
    for two).

Synthetic people only (project rule 11). Requires the static server and the
backend (see run_e2e_suite.py).
"""

import asyncio
import io

from docx import Document
from playwright.async_api import async_playwright

from _common import (
    BASE, Checks, fresh_load_and_login, future_date, generate_and_download_docx, pick_inviter_country,
    select_cover_letter_country,
)

checks = Checks()

SEED = """() => {
  var a = KhannaState.createApplication("customercare@khannatravels.com");
  KhannaState.updateApplication(a.id, {
    applicant: Object.assign({}, a.applicant, {
      fullName: "MIHIR HARILAL KOTAK", salutation: "Mr", sex: "M",
      passport: { current: { number: "Z1234567", issuePlace: "MUMBAI", issueDate: "2020-01-01" } },
      contact: { phone: "9876543210", email: "mihir.test@example.com" },
      address: Object.assign({}, a.applicant.address, { city: "MUMBAI", country: "INDIA" })
    })
  }, "seed");
  var ids = ["applicant"];
  [["Spouse", "ANITA MIHIR KOTAK", "F", "Z1000001", "Mrs"], ["Child", "ROHAN MIHIR KOTAK", "M", "Z1000002", "Master"],
   ["Child", "RIYA MIHIR KOTAK", "F", "Z1000003", "Miss"]].forEach(function (spec) {
    var t = KhannaState.addTraveller(a.id, spec[0]);
    KhannaState.updateTraveller(a.id, t.id, { fullName: spec[1], sex: spec[2], salutation: spec[4],
      passport: { current: { number: spec[3], issuePlace: "MUMBAI", issueDate: "2021-02-02" } } }, "seed");
    ids.push(t.id);
  });
  KhannaState.updateApplication(a.id, {
    coverLetter: {
      region: "Europe", country: "Belgium", selectedPersonIds: ["applicant"],
      consulateName: "The Consulate General of Belgium", consulateAddress: "Mumbai, India",
      recipientText: "The Consulate General of Belgium\\nMumbai, India",
      destinationCountry: "Belgium", travelStartDate: "__START__", travelEndDate: "__END__",
      fundingType: "self", fundingArrangement: "ourselves",
      europe: { cityOfResidence: "Mumbai", countryOfResidence: "India", numberOfNights: "10 nights",
                applicantEmploymentStatus: "Self-employed", applicantJobTitle: "Director", applicantEmployerName: "Acme Traders" },
      japan: { applicantEmployerOccupation: "Director at Acme Traders" }
    }
  }, "seed");
  return { id: a.id, ids: ids };
}""".replace("__START__", future_date(40)).replace("__END__", future_date(50))

NAMES = ("Anita Mihir Kotak", "Rohan Mihir Kotak", "Riya Mihir Kotak")
NUMBERS = ("Z1000001", "Z1000002", "Z1000003")


def docx_text(path_bytes: bytes) -> str:
    return "\n".join(p.text for p in Document(io.BytesIO(path_bytes)).paragraphs)


async def read_download(dl) -> bytes:
    with open(await dl.path(), "rb") as fh:
        return fh.read()


async def tick_everyone(page, selector):
    boxes = page.locator(selector)
    n = await boxes.count()
    for i in range(n):
        if not await boxes.nth(i).is_checked():
            await boxes.nth(i).check()
    return n


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page(viewport={"width": 1366, "height": 900})
        errors = []
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        page.on("pageerror", lambda e: errors.append(str(e)))
        await fresh_load_and_login(page, base=BASE)
        seeded = await page.evaluate(SEED)
        await page.evaluate("(id) => KhannaState.setActiveApplicationId(id)", seeded["id"])

        # ================= Cover Letter: Europe =================
        await page.evaluate("location.hash = '#/cover-letter'")
        await page.wait_for_timeout(900)
        boxes = "[data-cover-checklist] input[data-cover-person]"
        n = await tick_everyone(page, boxes)
        await page.wait_for_timeout(400)
        checks.check("Europe: all four people can be ticked", n == 4 and await page.locator(f"{boxes}:checked").count() == 4)
        checks.check("Europe: nothing in the list is disabled", await page.locator(f"{boxes}:disabled").count() == 0)
        cards = page.locator("[data-cover-companion-card]")
        checks.check("Europe: one card per companion", await cards.count() == 3, str(await cards.count()))
        checks.check("Europe: the single-companion fields are replaced by the per-person cards",
                     await page.locator("#cover-europe-companionJobTitle").count() == 0
                     and await page.locator("[data-cover-field='top:travellerRelation']").count() == 0)
        rels = []
        for i in range(3):
            rels.append((await cards.nth(i).locator("select option:checked").inner_text()).strip())
        checks.check("Europe: relations are pre-selected from the traveller records", sorted(rels) == ["Daughter", "Son", "Wife"], str(rels))
        previews = await page.locator("[data-cover-companion-preview]").all_inner_texts()
        checks.check("Europe: each card shows how that person will read", any("my wife, Anita Mihir Kotak" in t for t in previews), str(previews))
        checks.check("Europe: Generate is enabled without any companion job details",
                     not await page.locator("[data-action='generate-cover-letter']").is_disabled(),
                     await page.inner_text("[data-cover-readiness]"))

        wife_card = page.locator("[data-cover-companion-card]", has_text="Anita")
        await wife_card.locator("input[data-cover-companion$=':jobTitle']").fill("Teacher")
        await wife_card.locator("input[data-cover-companion$=':employerName']").fill("City School")
        await wife_card.locator("input[data-cover-companion$=':employmentStartYear']").fill("2012")
        await wife_card.locator("input[data-cover-companion$=':employmentStartYear']").press("Tab")
        await page.wait_for_timeout(300)

        dl = await generate_and_download_docx(page, "[data-action='generate-cover-letter']", ".view.is-active [data-doc-preview]")
        text = docx_text(await read_download(dl))
        for name in NAMES:
            checks.check(f"Europe .docx names {name}", name in text, text[:700])
        checks.check("Europe .docx uses each person's own relation",
                     "my wife, Anita Mihir Kotak" in text and "my son, Rohan Mihir Kotak" in text and "my daughter, Riya Mihir Kotak" in text, text[:900])
        checks.check("Europe .docx mentions the working companion only",
                     "My wife is working for City School since 2012, currently as Teacher." in text and text.count("is working for") == 1, text[:1200])
        checks.check("Europe .docx has no leftover '—' placeholders for the optional job details", "since —" not in text and "as —" not in text)

        # ================= Cover Letter: Japan =================
        await select_cover_letter_country(page, "Japan")
        await page.wait_for_timeout(900)
        await tick_everyone(page, boxes)
        await page.wait_for_timeout(400)
        checks.check("Japan: all four people ticked, per-person cards shown",
                     await page.locator(f"{boxes}:checked").count() == 4 and await page.locator("[data-cover-companion-card]").count() == 3)
        checks.check("Japan: occupation (not job/employer) is asked per companion",
                     await page.locator("[data-cover-companion-card] input[data-cover-companion$=':occupation']").count() == 3
                     and await page.locator("[data-cover-companion-card] input[data-cover-companion$=':jobTitle']").count() == 0)
        wife_card = page.locator("[data-cover-companion-card]", has_text="Anita")
        await wife_card.locator("input[data-cover-companion$=':occupation']").fill("Teacher")
        await wife_card.locator("input[data-cover-companion$=':occupation']").press("Tab")
        await page.wait_for_timeout(300)
        checks.check("Japan: Generate enabled", not await page.locator("[data-action='generate-cover-letter']").is_disabled(),
                     await page.inner_text("[data-cover-readiness]"))
        dl = await generate_and_download_docx(page, "[data-action='generate-cover-letter']", ".view.is-active [data-doc-preview]")
        text = docx_text(await read_download(dl))
        for name, number in zip(NAMES, NUMBERS):
            checks.check(f"Japan .docx lists {name} with passport {number}", name in text and number in text, text[:900])
        checks.check("Japan .docx: 'along with my wife, my son and my daughter'", "along with my wife, my son and my daughter" in text, text[:700])
        checks.check("Japan .docx: the template's own instruction is not shown", "Add additional family member" not in text)

        # one companion keeps the original single-companion fields
        for i in (3, 2):
            await page.locator(f"{boxes}").nth(i).uncheck()
        await page.wait_for_timeout(400)
        checks.check("Japan: back to one companion -> the original companion field returns",
                     await page.locator("#cover-japan-companionOccupation").count() == 1
                     and await page.locator("[data-cover-companion-card]").count() == 0)

        # ================= Passport Authorization =================
        await page.evaluate("location.hash = '#/passport-authorization'")
        await page.wait_for_timeout(900)
        pa_boxes = '[data-auth-checklist="passport"] input[type=checkbox]'
        n = await tick_everyone(page, pa_boxes)
        await page.wait_for_timeout(300)
        checks.check("Passport Authorization: all four can be ticked, none disabled",
                     n == 4 and await page.locator(f"{pa_boxes}:disabled").count() == 0)
        await page.fill("#auth-passport-recipientCentreName", "Germany Visa Application Centre")
        await page.fill("#auth-passport-recipientAddress", "Andheri, Mumbai")
        await page.fill("#auth-passport-collectorName", "Mr. Suresh Patil")
        await page.locator("#auth-passport-collectorName").blur()
        await page.wait_for_timeout(300)
        checks.check("Passport Authorization: Generate enabled",
                     await page.get_attribute("[data-action='generate-authorization'][data-group='passport']", "disabled") is None)
        dl = await generate_and_download_docx(page, "[data-action='generate-authorization'][data-group='passport']", "[data-doc-preview='passport']")
        text = docx_text(await read_download(dl))
        for number in ("Z1234567",) + NUMBERS:
            checks.check(f"Passport Authorization .docx has {number}", number in text, text[:900])
        checks.check("Passport Authorization .docx is in the plural", "original passports" in text, text[:700])

        # ================= Invitation Letter =================
        await page.evaluate("location.hash = '#/invitation-letter'")
        await page.wait_for_timeout(900)
        inv_boxes = "[data-invitation-invitee-checklist] input[type=checkbox]"
        n = await tick_everyone(page, inv_boxes)
        await page.wait_for_timeout(300)
        checks.check("Invitation: all four can be ticked, none disabled", n == 4 and await page.locator(f"{inv_boxes}:disabled").count() == 0)
        fields = {
            "#invitation-field-inviter-fullName": "Ms. Test Inviter",
            "#invitation-field-inviter-passportNumber": "Z9999999",
            "#invitation-field-inviter-addressLine1": "1 Example Street",
            "#invitation-field-inviter-cityPostcode": "Example City EX1",
            "#invitation-field-inviter-fullAddress": "1 Example Street, Example City EX1",
            "#invitation-field-inviter-cityCountry": "Mumbai, India",
            "#invitation-field-inviter-studyingOrWorking": "Working",
            "#invitation-field-inviter-universityOrCompany": "Example Corp",
            "#invitation-field-inviter-phone": "9999999999",
            "#invitation-field-inviter-email": "inviter@example.com",
            "#invitation-field-top-travelStartDate": future_date(40),
            "#invitation-field-top-travelEndDate": future_date(50),
            "#invitation-field-top-purpose": "attending a family event",
            "#invitation-field-top-accommodationDetails": "with the inviter",
            "#invitation-field-top-returnDate": future_date(50),
            "#invitation-field-top-fundingArrangement": "the inviter",
        }
        for sel, val in fields.items():
            await page.fill(sel, val)
        await page.locator("#invitation-field-top-fundingArrangement").blur()
        await pick_inviter_country(page)
        await page.wait_for_timeout(300)
        checks.check("Invitation: Generate enabled with four invitees", await page.get_attribute("[data-action='generate-invitation']", "disabled") is None,
                     await page.inner_text("[data-invitation-readiness]"))
        dl = await generate_and_download_docx(page, "[data-action='generate-invitation']", "[data-invitation-preview]")
        text = docx_text(await read_download(dl))
        for number in ("Z1234567",) + NUMBERS:
            checks.check(f"Invitation .docx has {number}", number in text, text[:900])
        checks.check("Invitation .docx says 'my family' for four invitees", "for my Family" in text and "invite my family" in text, text[:900])

        # exactly two keeps the template's own wording
        for i in (3, 2):
            await page.locator(inv_boxes).nth(i).uncheck()
        await page.wait_for_timeout(400)
        dl = await generate_and_download_docx(page, "[data-action='generate-invitation']", "[data-invitation-preview]")
        text = docx_text(await read_download(dl))
        checks.check("Invitation .docx keeps 'my Parents' for exactly two", "for my Parents" in text and "invite my parents" in text, text[:900])

        real_errors = [e for e in errors if "favicon" not in e.lower()]
        checks.check("No console errors", not real_errors, "; ".join(real_errors[:3]))
        await browser.close()

    checks.report_and_exit()


if __name__ == "__main__":
    asyncio.run(main())
