"""
Hotel Voucher edit mode: every value is a cell, and edits stay in their cell.

Reproduces what went wrong for a real user: a value was deleted and Backspace
pressed again (the empty value line was merged into the label cell next to it),
then text copied from a web page (dark background, Google Sans) was pasted, and
ended up inside the label cell with the web page's styling. Checks:
  * deleting a value, then Backspace / Delete again, leaves the cell (empty)
  * typing into the empty cell goes into that cell, not the label
  * pasting rich text from a web page gives plain text with the cell's own look
  * a multi-line paste becomes one line
  * a selection across several cells empties them without removing any cell
  * the downloaded .docx has each value next to its own label and no foreign shading

Requires the static server and the backend (see run_e2e_suite.py).
"""

import asyncio
import io
import zipfile

from docx import Document
from docx.oxml.ns import qn
from playwright.async_api import async_playwright

from _common import BASE, Checks, fresh_load_and_login, select_unit_text, set_edit_mode, wait_preview_ready

checks = Checks()
SEED = """() => { var a = KhannaState.createApplication("customercare@khannatravels.com");
 KhannaState.updateApplication(a.id,{applicant:Object.assign({},a.applicant,{fullName:"CELL TEST",salutation:"Mr",sex:"M"})},"seed");
 KhannaState.setActiveApplicationId(a.id);
 var h=KhannaState.addHotel(a.id); KhannaState.updateHotel(a.id,h.id,{hotelName:"Bussaco Palace Hotel",city:"Luso",country:"Portugal",address:"Mata do Bussaco, Luso, Portugal",phone:"+351 1",checkIn:"2026-11-16",checkOut:"2026-11-20",leadGuestName:"Mr. Cell Test",noOfRooms:"1",noOfAdults:"1",roomType:"Standard Single",confirmationNumber:"ABC123"},"seed");
 return a.id; }"""
SCOPE = ".view.is-active [data-voucher-preview]"
ED = SCOPE + " .lw-stage .ql-editor"

UNITS = """() => Array.from(document.querySelectorAll('.view.is-active .lw-stage .ql-editor [data-unit]')).map(n => [n.getAttribute('data-unit').split('|').slice(1).join('|'), n.textContent])"""

PASTE = """([sel, html, text]) => {
  const ed = document.querySelector(sel);
  const dt = new DataTransfer();
  dt.setData('text/html', html); dt.setData('text/plain', text);
  const ev = new ClipboardEvent('paste', {clipboardData: dt, bubbles: true, cancelable: true});
  ed.dispatchEvent(ev);
  return ev.defaultPrevented;
}"""

DARK = ('<meta charset="utf-8"><div style="background-color:#22242a;color:#e8eaf2;font-family:\'Google Sans\';font-size:21pt">'
        '<span style="background-color:#22242a;color:#e8eaf2;font-family:\'Google Sans\',Arial;font-size:21pt">{}</span></div>')


def text_of(units, key):
    return next((t for k, t in units if k == key), None)


def cells_of(doc_bytes):
    """[(label_text, next_cell_text)] over every row of every (nested) table."""
    doc = Document(io.BytesIO(doc_bytes))
    out = []

    def walk(tbl):
        for tr in tbl.findall(qn("w:tr")):
            texts = []
            for tc in tr.findall(qn("w:tc")):
                texts.append("".join(t.text or "" for t in tc.iter(qn("w:t"))))
                for nt in tc.findall(qn("w:tbl")):
                    walk(nt)
            for i in range(len(texts) - 1):
                out.append((texts[i], texts[i + 1]))

    for t in doc.element.body.findall(qn("w:tbl")):
        walk(t)
    return out


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page(viewport={"width": 1280, "height": 1000}, accept_downloads=True)
        errors = []
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        page.on("pageerror", lambda e: errors.append(str(e)))
        await fresh_load_and_login(page, base=BASE)
        await page.evaluate(SEED)
        await page.evaluate("location.hash = '#/hotel-blocking'")
        await page.wait_for_timeout(900)
        await page.click("[data-action='generate-voucher']")
        await wait_preview_ready(page, SCOPE)
        await set_edit_mode(page, SCOPE, True)
        await page.wait_for_selector(ED)
        await page.wait_for_timeout(800)
        start = await page.evaluate(UNITS)
        start_keys = [k for k, _ in start]

        # ---- empty a value, then Backspace and Delete again ----
        await select_unit_text(page, SCOPE, "hotelName", True)
        await page.keyboard.press("Backspace")
        await page.wait_for_timeout(200)
        await page.keyboard.press("Backspace")
        await page.keyboard.press("Delete")
        await page.wait_for_timeout(200)
        now = await page.evaluate(UNITS)
        checks.check("The emptied value is still its own (empty) cell", [k for k, _ in now] == start_keys and text_of(now, "hotelName") == "", str([k for k in start_keys if k not in [x for x, _ in now]]))
        checks.check("...and the label next to it is untouched", text_of(now, "blk-71938076-0") == "Hotel Name:" and text_of(now, "blk-53de6ba0-0") == "Lead Guest:", str(text_of(now, "blk-71938076-0")))
        await page.keyboard.type("Typed Name")
        await page.wait_for_timeout(200)
        now = await page.evaluate(UNITS)
        checks.check("Typing goes into the value cell, not the label", text_of(now, "hotelName") == "Typed Name" and text_of(now, "blk-71938076-0") == "Hotel Name:", str(text_of(now, "hotelName")))

        # ---- paste from a web page ----
        await select_unit_text(page, SCOPE, "hotelName", True)
        await page.evaluate(PASTE, [ED, DARK.format("Buçaco Palace Hotel"), "Buçaco Palace Hotel"])
        await page.wait_for_timeout(300)
        now = await page.evaluate(UNITS)
        checks.check("Pasted text replaces the selected value in its own cell", text_of(now, "hotelName") == "Buçaco Palace Hotel", str(text_of(now, "hotelName")))
        styles = await page.evaluate(
            """(sel) => { const n = document.querySelector(sel + " [data-unit$='|hotelName']"); return n ? n.innerHTML : ''; }""", ED
        )
        checks.check("...without the web page's colours, background, font or size", not any(w in styles.lower() for w in ("22242a", "e8eaf2", "google sans", "21pt")), styles[:300])

        await select_unit_text(page, SCOPE, "phone", True)
        await page.evaluate(PASTE, [ED, DARK.format("+351 231 937 970"), "+351 231 937 970\n"])
        await page.wait_for_timeout(300)
        now = await page.evaluate(UNITS)
        checks.check("A pasted line break does not create a second line in a cell", text_of(now, "phone") == "+351 231 937 970" and [k for k, _ in now] == start_keys, str(text_of(now, "phone")))

        await select_unit_text(page, SCOPE, "address", True)
        await page.evaluate(PASTE, [ED, DARK.format("Mata do Bussaco, 3050-261 Luso, Portugal"), "Mata do Bussaco, 3050-261 Luso, Portugal"])
        await page.wait_for_timeout(300)

        # ---- a selection across cells empties them but removes none ----
        await page.evaluate(
            """(sel) => {
              const ed = document.querySelector(sel);
              const a = ed.querySelector("[data-unit$='|noOfRooms']");
              const b = ed.querySelector("[data-unit$='|nights']");
              const ta = document.createTreeWalker(a, NodeFilter.SHOW_TEXT).nextNode();
              const tb = document.createTreeWalker(b, NodeFilter.SHOW_TEXT).nextNode();
              const r = document.createRange(); r.setStart(ta, 0); r.setEnd(tb, tb.textContent.length);
              ed.focus(); const s = getSelection(); s.removeAllRanges(); s.addRange(r);
            }""",
            ED,
        )
        before = await page.evaluate(UNITS)
        await page.keyboard.press("Delete")
        await page.wait_for_timeout(300)
        now = await page.evaluate(UNITS)
        labels_before = {k: t for k, t in before if k.startswith("blk-")}
        labels_now = {k: t for k, t in now if k.startswith("blk-")}
        checks.check("Deleting across several cells keeps every cell", [k for k, _ in now] == start_keys, str(len(now)))
        outside = ("blk-71938076-0", "blk-53de6ba0-0", "blk-3360423d-0")  # labels before the selection started
        checks.check("...keeps the labels outside the selection", all(labels_now[k] == labels_before[k] for k in outside), str(labels_now))
        checks.check("...and empties the values it covered", all(text_of(now, k) == "" for k in ("noOfRooms", "phone", "checkIn", "checkOut", "nights")), str([text_of(now, k) for k in ("noOfRooms", "phone", "nights")]))
        checks.check("A value outside the selection is kept", text_of(now, "hotelName") == "Buçaco Palace Hotel" and text_of(now, "leadGuestName") == "Mr. Cell Test")

        # type over a selection that reaches the next cell
        await select_unit_text(page, SCOPE, "city", True)
        await page.keyboard.press("Shift+ArrowRight")  # reaches past the end of the value
        await page.keyboard.type("Luso")
        await page.wait_for_timeout(300)
        now = await page.evaluate(UNITS)
        checks.check("Typing over a selection that spills into the next cell stays in the first cell", text_of(now, "city") == "Luso" and [k for k, _ in now] == start_keys, str(text_of(now, "city")))

        # ---- what is saved, and what the real document says ----
        await set_edit_mode(page, SCOPE, False)
        await wait_preview_ready(page, SCOPE)
        saved = await page.evaluate("() => JSON.stringify(KhannaState.getActiveApplication().hotels[0].editedFields || {})")
        checks.check("The saved edits carry no foreign styling", not any(w in saved.lower() for w in ("22242a", "e8eaf2", "google sans")), saved[:300])
        async with page.expect_download() as dl:
            await page.click(f"{SCOPE} [data-dv='download-docx']")
        data = open(await (await dl.value).path(), "rb").read()
        pairs = dict(cells_of(data))
        checks.check("In the .docx the hotel name is in the cell next to 'Hotel Name:'", pairs.get("Hotel Name:") == "Buçaco Palace Hotel", str(pairs.get("Hotel Name:")))
        checks.check("...'Lead Guest:' is followed by the lead guest, not by a pasted value", pairs.get("Lead Guest:") == "Mr. Cell Test", str(pairs.get("Lead Guest:")))
        checks.check("...the address is in the address cell", "Bussaco" in str(pairs.get("Hotel Address:")), str(pairs.get("Hotel Address:")))
        xml = zipfile.ZipFile(io.BytesIO(data)).read("word/document.xml").decode("utf8").lower()
        checks.check("...and no foreign shading or font came along", "22242a" not in xml and "google sans" not in xml)

        real = [e for e in errors if "favicon" not in e.lower()]
        checks.check("no browser console errors", not real, "; ".join(real[:3]))
        await browser.close()
    checks.report_and_exit()


if __name__ == "__main__":
    asyncio.run(main())
