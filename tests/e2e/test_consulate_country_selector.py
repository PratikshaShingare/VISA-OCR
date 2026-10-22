"""
Consulate chosen by COUNTRY (Company Authorization Letter, Invitation Letter):
a searchable country list completes "The Consulate General of <country>" and
the address (default "Mumbai, India", editable) goes on the next line. Also:
a passport's capitalised name appears in ordinary capitalisation on the
generated letter while the stored passport name is untouched.

Real static server + backend. All names synthetic.
"""
import asyncio
import io

from docx import Document
from playwright.async_api import async_playwright

from _common import BASE, Checks, fresh_load_and_login, generate_and_download_docx

checks = Checks()

SEED = """
(function () {
  var S = KhannaState;
  var a = S.createApplication('x');
  S.updateApplication(a.id, { authorization: { company: {
    manualApplicants: [{ id: 'MAN1', fullName: 'MIHIR HARILAL KOTAK', passportNumber: 'Z1234567' }],
    selectedPersonIds: ['MAN1'] } } });
  S.setActiveApplicationId(a.id);
  return a.id;
})()
"""


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        context = await browser.new_context(viewport={"width": 1280, "height": 1100}, accept_downloads=True)
        page = await context.new_page()
        errors = []
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
        await fresh_load_and_login(page, base=BASE)
        app_id = await page.evaluate(SEED)
        await page.evaluate("location.hash = '#/company-authorization'")
        await page.wait_for_timeout(700)

        # ---------- Company Authorization ----------
        label = (await page.locator("label[for='auth-company-consulateCountry']").inner_text()).strip()
        checks.check("country selector replaces the single 'Consulate name & address' input", label.startswith("Consulate country") and "Consulate name & address" not in await page.inner_text("[data-company-auth-card]"), label)
        addr = await page.input_value("[data-auth-field='company:consulateAddress']")
        checks.check("'Address of Consulate' defaults to Mumbai, India", addr == "Mumbai, India", addr)
        disabled = await page.get_attribute("[data-action='generate-authorization'][data-group='company']", "disabled")
        checks.check("Generate stays disabled until a country is chosen", disabled is not None)

        inp = page.locator("#auth-company-consulateCountry")
        await inp.click()
        n_all = await page.locator("[data-ccombo-option]").count()
        checks.check("clicking the box lists the countries", n_all >= 150, str(n_all))
        await inp.fill("jap")
        opts = [o.strip() for o in await page.locator("[data-ccombo-option]").all_inner_texts()]
        checks.check("typing filters the list ('jap' -> Japan)", opts == ["Japan"], str(opts))
        await inp.fill("united")
        opts = [o.strip() for o in await page.locator("[data-ccombo-option]").all_inner_texts()]
        checks.check("'united' -> the United ... countries, name-starts first", opts[:3] == ["United Arab Emirates", "United Kingdom", "United States"], str(opts[:5]))
        await inp.fill("zzzz")
        checks.check("no match says so", "No matching country" in await page.inner_text(".country-combo__list"))
        await inp.fill("jap")
        await page.click("[data-ccombo-option='Japan']")
        await page.wait_for_timeout(300)
        recipient = await page.evaluate("KhannaState.getActiveApplication().authorization.company.recipientText")
        checks.check("choosing Japan completes 'The Consulate General of Japan' + address on the next line", recipient == "The Consulate General of Japan\nMumbai, India", repr(recipient))
        checks.check("the box shows the chosen country", await inp.input_value() == "Japan")
        hint = await page.inner_text("[data-consulate-hint]")
        checks.check("a hint shows exactly what goes on the letter", "The Consulate General of Japan" in hint and "Mumbai, India" in hint, hint)
        disabled = await page.get_attribute("[data-action='generate-authorization'][data-group='company']", "disabled")
        checks.check("Generate is enabled now", disabled is None)

        await page.fill("[data-auth-field='company:consulateAddress']", "New Delhi, India")
        await page.locator("[data-auth-field='company:consulateAddress']").blur()
        await page.wait_for_timeout(300)
        recipient = await page.evaluate("KhannaState.getActiveApplication().authorization.company.recipientText")
        checks.check("the address is editable and follows into the letter text", recipient == "The Consulate General of Japan\nNew Delhi, India", repr(recipient))

        await inp.click()
        await inp.fill("nether")
        await inp.press("Enter")
        await page.wait_for_timeout(300)
        recipient = await page.evaluate("KhannaState.getActiveApplication().authorization.company.recipientText")
        checks.check("another country re-completes the wording ('the Netherlands'), keeping the edited address", recipient == "The Consulate General of the Netherlands\nNew Delhi, India", repr(recipient))

        await inp.click()
        await inp.fill("zzz")
        await page.click("[data-company-auth-card] h3")
        await page.wait_for_timeout(200)
        checks.check("abandoned typing is restored to the chosen country", await inp.input_value() == "Netherlands")

        # the real document
        await inp.click()
        await inp.fill("japan")
        await inp.press("Enter")
        await page.fill("[data-auth-field='company:consulateAddress']", "Mumbai, India")
        await page.locator("[data-auth-field='company:consulateAddress']").blur()
        await page.wait_for_timeout(300)
        dl = await generate_and_download_docx(page, "[data-action='generate-authorization'][data-group='company']", "[data-doc-preview='company']")
        with open(await dl.path(), "rb") as f:
            doc = Document(io.BytesIO(f.read()))
        text = "\n".join(p.text for p in doc.paragraphs)
        checks.check("the downloaded letter has 'The Consulate General of Japan' with 'Mumbai, India' on the next line", "The Consulate General of Japan\nMumbai, India" in text, text[:400])
        checks.check("the passport name is written in ordinary capitalisation on the letter", "Mihir Harilal Kotak" in text and "MIHIR HARILAL KOTAK" not in text, text)
        checks.check("...with the passport number untouched", "Z1234567" in text)
        stored = await page.evaluate("KhannaState.getActiveApplication().authorization.company.manualApplicants[0].fullName")
        checks.check("the stored name stays exactly as on the passport", stored == "MIHIR HARILAL KOTAK", stored)

        # ---------- Dashboard: Recent Applications shows time as well as date ----------
        await page.evaluate("location.hash = '#/dashboard'")
        await page.wait_for_timeout(600)
        dash = await page.inner_text("[data-view='dashboard']")
        import re
        checks.check("Recent Applications shows the time with the date ('Updated 19 Oct 2026, 3:42 pm')", re.search(r"Updated \d{1,2} \w{3} \d{4}, \d{1,2}:\d{2} (am|pm)", dash) is not None, dash[:600])

        # ---------- Invitation Letter ----------
        await page.evaluate("location.hash = '#/invitation-letter'")
        await page.wait_for_timeout(700)
        label = (await page.locator("label[for='inv-inviter-country']").inner_text()).strip()
        checks.check("Invitation Letter: consulate country is a searchable list too", label.startswith("Consulate country"), label)
        cc = await page.input_value("[data-invitation-field='inviter:cityCountry']")
        checks.check("...and its address line defaults to Mumbai, India", cc == "Mumbai, India", cc)
        await page.locator("#inv-inviter-country").click()
        await page.locator("#inv-inviter-country").fill("ireland")
        await page.locator("#inv-inviter-country").press("Enter")
        await page.wait_for_timeout(300)
        country = await page.evaluate("KhannaState.getActiveApplication().invitation.inviter.country")
        checks.check("choosing a country stores it for the letter", country == "Ireland", country)

        # ---------- mobile ----------
        await page.set_viewport_size({"width": 375, "height": 800})
        await page.evaluate("location.hash = '#/company-authorization'")
        await page.wait_for_timeout(600)
        await page.locator("#auth-company-consulateCountry").click()
        await page.wait_for_timeout(200)
        overflow = await page.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth")
        checks.check("375px: no horizontal overflow with the list open", overflow <= 0, str(overflow))
        box = await page.locator("[data-ccombo-list]:not([hidden])").bounding_box()
        checks.check("375px: the list stays inside the screen", box is not None and box["x"] >= 0 and box["x"] + box["width"] <= 376, str(box))
        await page.screenshot(path="/tmp/dbg/consulate_m.png")
        await page.set_viewport_size({"width": 1280, "height": 900})
        await page.evaluate("location.hash = '#/company-authorization'")
        await page.wait_for_timeout(500)
        await page.screenshot(path="/tmp/dbg/consulate_d.png")

        checks.check("no console errors", not errors, "; ".join(errors[:4]))
        await browser.close()
    checks.report_and_exit()


asyncio.run(main())
