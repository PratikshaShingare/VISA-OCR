# Backend automated test suite

Real, persisted, re-runnable `pytest` tests for the Khanna Travels &
Holidays backend (`backend/python/`) — written in Phase 13 as this
project's first organized automated test suite (everything before this was
one-off scratch scripts, run once and discarded).

## Running

```bash
cd backend/python
pip install -r requirements.txt -r requirements-dev.txt --break-system-packages
pytest
```

(or `pytest backend/python/tests` from the project root — both work; see
`pytest.ini`.)

91 tests, ~15–20 seconds. No servers need to be started first — everything
here calls the Python engine functions and the FastAPI app directly
in-process (via `fastapi.testclient.TestClient` for the HTTP-level tests),
never over a real socket.

## What's covered, and how

Every engine that builds a real client-facing document is tested **against
its real, unmodified reference template** — never a fake stand-in — because
project rule 5 (Document Template Rule) makes that real template the source
of truth, and a hand-built substitute template would let a genuine
structural regression slip straight past the tests:

- `test_data_model.py` — the Application data model: factory shape/defaults,
  id generation, JSON round-trip, and the shallow structural validator.
- `test_docx_utils.py` — the shared, formatting-preserving `.docx` helpers
  every engine builds on (run-preserving text replacement, `<w:br/>`-aware
  two-line paragraphs, real hyperlink rewriting/removal, element cloning,
  a real LibreOffice → PDF conversion). Uses small synthetic documents,
  since these are unit tests of the mechanics themselves.
- `test_hotel_voucher_engine.py` — against
  `reference-hotel-blocking-formats/Single Hotel/Hotel Booking Format.docx`:
  single- and multi-hotel generation, guest-name lists, missing-field
  placeholders, PDF export.
- `test_authorization_letter_engine.py` — against the real
  `reference-templates/Passport Authorization Letter/` (single + two
  traveller) and `Company Authorization Letter/` files, **including a
  regression test that the real former client's own name/phone baked into
  those reference letters never leaks into generated output** (project
  rule 11).
- `test_cover_letter_engine.py` — against the real Europe / Japan /
  Singapore templates in `reference-cover-letter-formats/`, including
  Japan's hotel table (with and without hotels) and Singapore's
  optional-companions family clause.
- `test_invitation_letter_engine.py` — against the real Invitation Letter
  template and both Initors Covering Letter templates (`reference-templates/
  Invitation Letter/` and `.../Invitors letters/`), including real signature
  image embedding, the "no signature uploaded → slot stays blank" rule
  (project rule 9), gendered-template selection, and a regression test that
  the templates' own leftover real `mailto:` hyperlink is stripped rather
  than leaked (project rule 11).
- `test_admin_export_engine.py` — the Master Excel export (3-sheet
  workbook), read back with `openpyxl` to check real data landed in the
  right sheet.
- `test_api_endpoints.py` — the actual HTTP contract `js/core/api.js`
  relies on: status codes, multipart vs. JSON request shapes,
  `Content-Disposition` filenames, and 400/422 validation errors — using
  FastAPI's `TestClient`, so no server process has to be started first.

## Graceful skipping, not fake passes

A handful of tests are conditioned on the real reference `.docx` file (or
`soffice`, for PDF export) actually being present on the machine running
them, via `conftest.skip_if_missing(...)` / `skip_if_missing_binary(...)`.
On a correctly set-up Khanna Travels machine these files always exist
(they're the project's own read-only reference material — project rule 3)
and every test runs for real. The skip guard exists only so a fresh
checkout without those files populated yet still gets an honest, named
`SKIPPED` reason instead of a confusing collection failure — it is never
used to quietly skip past a real, fixable problem.

No real client passport data is ever used as sample data anywhere in this
suite (project rule 11) — every name, passport number, phone and email in
the fixtures (`conftest.py`) is obviously synthetic.

## What's deliberately NOT here

Full browser-driven, multi-step user journeys (login → OCR → wizard →
document download, exactly as a staff member would use the app) live in
`tests/e2e/` at the project root instead, since they need a running
backend + static file server and a real browser (Playwright) rather than
an in-process function call. See `tests/e2e/README.md`.
