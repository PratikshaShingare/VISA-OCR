# Backend — local passport OCR & processing server

This is a small local API, meant to run on the same machine as the staff
member using the app. It never sends a passport image or any extracted
field to any external/cloud service — OCR runs entirely offline via
Tesseract, which is also why there is no API key anywhere in this project
(there's nothing to authenticate to).

## One-time setup

1. Install the Tesseract OCR engine itself (a system binary, not a Python
   package):
   - Windows: install from https://github.com/UB-Mannheim/tesseract/wiki
     and make sure `tesseract.exe` is on your `PATH` (or set
     `pytesseract.pytesseract.tesseract_cmd` at the top of `ocr_runner.py`
     to its install path).
   - macOS: `brew install tesseract`
   - Linux: `sudo apt-get install tesseract-ocr`
2. Install the Python dependencies:
   ```
   pip install -r requirements.txt
   ```

## Running it

```
uvicorn app:app --reload --port 8000
```

Leave this running while staff use the app. The frontend (`js/core/api.js`)
talks to `http://localhost:8000` by default — if you run the backend on a
different port, update `API_BASE_URL` there.

## Endpoints

- `GET /api/health` — liveness check.
- `POST /api/passport/process` — multipart form: `file` (image or PDF),
  optional `page_index` (default 0), optional `forced_rotation`
  (0/90/180/270, only when the user manually overrides the detected
  orientation). Returns the full structured result: applied orientation,
  corrected skew angle, the processed preview image (base64 PNG), the
  parsed/validated MRZ, and every extracted field with a confidence score,
  its source (`mrz` or `viz`), and whether it needs manual review.
- `POST /api/passport/page-count` — multipart form: `file`. Returns how
  many pages a PDF has (1 for a plain image), so the frontend's page
  flipper knows how many pages to offer before processing each one.
- `GET /api/applications/status-list` — the canonical Application status
  list, shared from `data_model.py` so the frontend and backend can never
  drift on what counts as a valid status.

## Testing notes / known limitations

`ocr_runner.py` is unit- and integration-tested (check-digit math against
the official ICAO Doc 9303 worked example, MRZ parsing, deskew, safe-crop,
and a full synthetic-image run through the real Tesseract engine — see the
project's test notes). Two real issues were caught and fixed this way:

- Whole-page OCR frequently misread the MRZ's `<` filler run as stray
  letters. Fixed by cropping the bottom MRZ band, splitting it into its
  two lines, and OCRing each individually with the character set
  whitelisted to `A-Z0-9<` (see `_read_mrz_band_lines`).
- Tesseract sometimes read the letter `O` as the digit `0` inside
  letters-only fields (nationality, issuing country, document type).
  Fixed with context-aware coercion — those fields are letters-only per
  ICAO, date fields are digits-only, so the correction direction is known
  from the field, not guessed (see `_coerce_alpha` / `_coerce_numeric`).

What's still a known, honest limitation: on a synthetic test render (a
generic monospace font, not the real OCR-B font passports actually use),
Tesseract occasionally drops a single character from a long run of `<`
filler, which shifts the MRZ **composite** check digit's position and
fails that one check even when every individual field (passport number,
date of birth, expiry) reads and validates correctly. Real passports use
the OCR-B font specifically because it's far more machine-legible than a
generic font, so this should be materially rarer in production — but it
can still happen on a real photo (glare, low resolution, a worn page).
That's exactly why the UI always shows **"OCR Extracted — Please Verify"**
and never auto-verifies a passport from OCR alone: a composite-check
failure is surfaced as "please verify manually," not silently ignored and
not silently rejected.

## Security notes

- CORS is wide open (`allow_origins=["*"]`) because this server only ever
  listens on `localhost` and only ever talks to the staff member's own
  browser tab — there's no real cross-origin risk in that setup. Don't
  expose this server to the network as-is.
- There is no authentication on these endpoints yet. The frontend's own
  login (Phase 3) gates the *UI*, not this API — anyone who can reach
  `localhost:8000` on this machine can call it directly. That's an
  accepted limitation of a same-machine local tool for now; if this ever
  needs to run somewhere reachable by more than one machine, add real
  auth to these endpoints first.
