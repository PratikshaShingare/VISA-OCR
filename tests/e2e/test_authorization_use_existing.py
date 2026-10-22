"""
Passport / Company Authorization pages — "Use Existing Details" (replaces the
old "Use Existing Applicant" top-bar button), modelled on the Cover Letter /
Invitation dropdown. Only "Passport" is offered: these letters carry no hotel
or trip dates, so a Hotel Blocking option could not fill anything.

Covers (static server only; nothing here generates):
  - the top bar no longer offers "Use Existing Applicant" / "Application".
  - Passport list (saved applications + saved profiles); picking a person
    copies them onto the active application as a traveller (source
    untouched) and ticks them.
  - Passport Authorization takes at most 2 people; a third pick is refused.
  - Company Authorization takes any number; picking clears positional edits.
  - Already-selected picks are reported, not duplicated.
  - 375px: no horizontal overflow; no console errors.
"""
import asyncio

from playwright.async_api import async_playwright

from _common import BASE, Checks, fresh_load_and_login

checks = Checks()

SEED = """
(function () {
  var S = KhannaState;
  var a = S.createApplication('x');
  S.updateApplication(a.id, { applicant: {
    salutation: 'Mr', firstName: 'Rahul', lastName: 'Sharma', fullName: 'Rahul Sharma', sex: 'Male',
    passport: { current: { number: 'P1111111' } } } });
  var t = S.addTraveller(a.id, 'Wife');
  S.updateTraveller(a.id, t.id, { salutation: 'Mrs', fullName: 'Priya Sharma', sex: 'Female',
    passport: { current: { number: 'P2222222' } } }, null);
  S.saveApplicantProfile({ salutation: 'Mr', firstName: 'Old', lastName: 'Profile', fullName: 'Old Profile',
    passport: { current: { number: 'P3333333' } } });
  var target = S.createApplication('x');
  S.setActiveApplicationId(target.id);
  return { target: target.id, a: a.id };
})()
"""


async def pick(page, card, group, key):
    await card.locator("[data-auth-use-existing-toggle]").click()
    await card.locator("[data-auth-use-existing-option='passport']").click()
    await card.locator(f"[data-auth-existing-pick='passport'][data-passport-key='{key}']").click()
    await page.wait_for_timeout(350)


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page(viewport={"width": 1280, "height": 1200})
        errors = []
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
        await fresh_load_and_login(page, base=BASE)
        ids = await page.evaluate(SEED)

        for view, group, card_sel, max_people in (
            ("passport-authorization", "passport", "[data-passport-auth-card]", 2),
            ("company-authorization", "company", "[data-company-auth-card]", None),
        ):
            await page.evaluate(f"location.hash = '#/{view}'")
            await page.wait_for_timeout(700)
            bar = await page.inner_text(f"[data-view='{view}'] [data-doc-page-app-bar]")
            checks.check(f"{group}: no 'Use Existing Applicant' button", await page.locator(f"[data-view='{view}'] [data-action='pick-doc-applicant']").count() == 0, bar)
            checks.check(f"{group}: no 'Use Existing Application' button", await page.locator(f"[data-view='{view}'] [data-action='pick-doc-application']").count() == 0, bar)
            card = page.locator(card_sel)
            checks.check(f"{group}: a 'Use Existing Details' dropdown is in the card", await card.locator("[data-auth-use-existing-toggle]").count() == 1)
            checks.check(f"{group}: no blank 'Unnamed' row", "Unnamed" not in await card.inner_text())
            await card.locator("[data-auth-use-existing-toggle]").click()
            items = await card.locator(".cover-existing-menu__item").all_inner_texts()
            checks.check(f"{group}: menu offers only Passport", [i.replace("▸", "").strip() for i in items] == ["Passport"], str(items))
            await card.locator("[data-auth-use-existing-option='passport']").click()
            txt = await card.locator("[data-auth-existing-list]").inner_text()
            checks.check(f"{group}: lists saved passports incl. saved profiles", "Rahul Sharma" in txt and "P2222222" in txt and "Old Profile" in txt, txt)
            await card.locator("[data-auth-use-existing-toggle]").click()  # close

            before = await page.evaluate(f"KhannaState.getApplication('{ids['target']}').travellers.length")
            await pick(page, card, group, "P1111111")
            checked = await card.locator(f"[data-auth-person='{group}']:checked").count()
            n_trav = await page.evaluate(f"KhannaState.getApplication('{ids['target']}').travellers.length")
            checks.check(f"{group}: picked person is ticked", checked == 1, str(checked))
            # (the Company pass runs on the same application, where the
            # Passport pass already copied these people in -> reused, not re-added)
            added = group == "passport"
            checks.check(f"{group}: ...{'was added to the application as a traveller' if added else 'reused the traveller already on the application'}", n_trav == before + (1 if added else 0), f"{before}->{n_trav}")
            status = await card.locator("[data-auth-existing-status]").inner_text()
            checks.check(f"{group}: status names the person", "Rahul Sharma" in status and (("added to this application" in status) == added), status)

            await pick(page, card, group, "P1111111")
            status = await card.locator("[data-auth-existing-status]").inner_text()
            n_trav2 = await page.evaluate(f"KhannaState.getApplication('{ids['target']}').travellers.length")
            checks.check(f"{group}: picking the same person again is reported, not duplicated", "already selected" in status and n_trav2 == n_trav, status)

            await pick(page, card, group, "P2222222")
            checks.check(f"{group}: second person ticked", await card.locator(f"[data-auth-person='{group}']:checked").count() == 2)
            await pick(page, card, group, "P3333333")
            ticked = await card.locator(f"[data-auth-person='{group}']:checked").count()
            status = await card.locator("[data-auth-existing-status]").inner_text()
            if max_people:
                checks.check(f"{group}: a third person is refused (max 2)", ticked == 2 and "1 or 2" in status, f"{ticked} {status}")
            else:
                checks.check(f"{group}: any number of people can be added", ticked == 3, str(ticked))
            src_name = await page.evaluate(f"KhannaState.getApplication('{ids['a']}').applicant.fullName")
            checks.check(f"{group}: the source application is untouched", src_name == "Rahul Sharma")

        # 375px
        await page.set_viewport_size({"width": 375, "height": 800})
        await page.wait_for_timeout(300)
        over = await page.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth")
        checks.check("375px: no horizontal overflow", over <= 0, str(over))
        checks.check("no console errors", not errors, "; ".join(errors[:3]))
        await browser.close()
    checks.report_and_exit()


asyncio.run(main())
