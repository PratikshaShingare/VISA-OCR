# End-to-end (Playwright) test suite

Real, persisted, re-runnable browser-driven tests for the Khanna Travels &
Holidays platform — written in Phase 13 as this project's first organized
E2E suite. Everything before this was one-off scratch scripts (one per
phase, seeding only that phase's own upstream state, run once and
discarded).

## Running

```bash
python3 tests/e2e/run_e2e_suite.py
```

This one command: generates the synthetic test fixtures if they don't
already exist, starts (or reuses) a static file server for the app, starts
its own backend, runs the three "backend up" scripts, stops the backend,
runs the "backend down" honest-failure script against it, then restarts
the backend so the environment is left usable afterwards. It prints a
final PASS/FAIL summary and exits non-zero if anything failed.

Takes 3–5 minutes overall (the device-emulation pass across 5 real device
profiles is the slowest part).

To run one script on its own against servers you're already running
manually:

```bash
KHANNA_E2E_BASE=http://127.0.0.1:8766 KHANNA_E2E_BACKEND_BASE=http://127.0.0.1:8000 \
    python3 tests/e2e/test_full_journey.py
```

(`test_backend_down_resilience.py` specifically requires the backend to
already be stopped when it runs — see its own docstring.)

## What's covered, and why this shape

- **`test_full_journey.py`** — the single most important script here, and
  the one that actually found a real production bug in Phase 13 (see
  below). Drives the ENTIRE real staff workflow as one continuous session:
  login → new application → passport OCR (applicant + 2 travellers, real
  Tesseract OCR every time) → travel & checklist → upload + verify every
  required document → hotel blocking with 2 hotels + a real voucher
  download → both authorization letters → a cover letter → an invitation
  letter + both Initors Covering Letters (real signature embedding, both
  gendered templates) → the Applications list → the Admin dashboard
  (status change, a real Excel export) → two full-page reloads at real
  checkpoints. No per-phase test before this one had ever opened a SECOND
  hotel panel in the same run — that's exactly the sequence that surfaced
  a real listener-accumulation bug in `js/hotels.js` (editing hotel 2's
  fields was silently also overwriting hotel 1's saved data). The fix is
  now a standing regression check inside this same script (Step 5).
- **`test_accessibility.py`** — real keyboard-only interaction (Tab/Enter,
  not clicks), label/for wiring, aria-labels on icon-only controls,
  visible focus outlines, and native-control checks (a real `<select>`,
  not a styled div).
- **`test_device_emulation.py`** — drives the app under Playwright's real
  device descriptors (actual User-Agent strings, viewport, device pixel
  ratio, `isMobile`, `hasTouch`) across 5 real device profiles (iPhone SE,
  iPhone 14 Pro Max, Pixel 5, iPad Mini portrait + landscape), tapping
  rather than clicking, with a scrollable-ancestor-aware horizontal
  overflow check (so Phase 12's own deliberate `overflow-x:auto` scroll
  strips — the wizard stepper nav, the Admin data tables — aren't
  misreported as page overflow).
- **`test_backend_down_resilience.py`** — the honest-failure path: with
  the backend stopped, every document-generation feature (hotel voucher,
  passport authorization, cover letter, admin Excel export) must show a
  real "couldn't reach the backend" message and let the button recover,
  never hang on "Generating…" or silently fake success (project rule 9).

### A note on cross-browser-ENGINE testing

This sandboxed environment cannot install Firefox or WebKit for
Playwright (network egress blocks Playwright's own CDN download hosts —
confirmed, not a workaround-able restriction), so this suite cannot
exercise those rendering engines directly. `test_device_emulation.py`'s
real multi-device emulation within Chromium — genuine touch input, UA,
device pixel ratio and viewport per device — is what this suite offers
instead. For an internal staff tool that will only ever run in a
mainstream, Chromium-or-equivalent browser, that is arguably the more
relevant check of the two; the engine-testing gap is real and is
documented here rather than silently worked around.

## Fixtures

`fixtures/generate_fixtures.py` renders two synthetic test assets on
first use (or run it directly to regenerate them):

- `synthetic_passport.png` — a fake "REPUBLIC OF UTOPIA" passport bio-data
  page with a real, check-digit-valid MRZ, rotated a few degrees so the
  real auto-orientation step has something to do. Not a real travel
  document (project rule 11).
- `fake_signature.png` — a simple squiggle standing in for an uploaded
  signature image. Not a real person's signature.

Neither file is committed as a static binary — they're generated from
code, so there's never any ambiguity about what they contain.

## What's deliberately NOT here

Fast, in-process unit/API tests for the backend engines and endpoints live
in `backend/python/tests/` instead (no browser, no servers to start,
~15–20 seconds total). See `backend/python/tests/README.md`. This split
matches what each kind of test actually needs: the backend suite for "is
this document/response correct," this suite for "does a staff member
clicking through the real UI actually get the right result."
