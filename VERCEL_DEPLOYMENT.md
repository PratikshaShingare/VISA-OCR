# Deploying to Vercel

This document explains what changed in this codebase so the whole
application — frontend and backend — can run as a live Vercel deployment,
and exactly what you need to configure to make that work. Nothing here
changes how the app runs on a staff member's own machine for local
development; every change below is additive and defaults back to the
original local behaviour when the new environment variables aren't set.

## What changed, and why

Vercel runs the backend as **serverless functions** — short-lived,
stateless processes with no system binaries beyond what pip installs.
Two things this project relied on cannot run there:

1. **Tesseract OCR** — `pytesseract` is a pure-Python wrapper around a
   separate `tesseract` executable, which cannot be installed inside a
   Vercel function.
2. **LibreOffice (`soffice`)** — used to convert generated `.docx` files to
   PDF, same problem.

Both are now behind a provider abstraction that picks the right
implementation automatically:

| Concern | Local (unchanged) | Vercel |
|---|---|---|
| Passport OCR | Tesseract (offline, free) | Google Cloud Vision API (`ocr_providers.py`) |
| .docx → PDF | LibreOffice (`soffice`) | CloudConvert API (`pdf_conversion.py`) |

Everything else — the document-generation engines, the MRZ parser, field
extraction/confidence scoring, the whole frontend — is **completely
unchanged**. Only the two lowest-level "call the actual OCR/PDF engine"
call sites were swapped out; see the module docstrings in
`backend/python/ocr_providers.py` and `backend/python/pdf_conversion.py`
for the exact mechanics.

## Required environment variables (set these in the Vercel project's
## Settings → Environment Variables — never in frontend code, per project
## rule 12)

| Variable | Required on Vercel? | Purpose |
|---|---|---|
| `GOOGLE_VISION_API_KEY` | Yes | Authenticates OCR calls to the Google Cloud Vision API. |
| `CLOUDCONVERT_API_KEY` | Yes | Authenticates .docx→PDF conversion calls to CloudConvert. |
| `OCR_PROVIDER` | No (default `auto`) | Force `tesseract` or `google`. Leave unset — `auto` already picks Google Cloud Vision once its key is present. |
| `PDF_CONVERSION_PROVIDER` | No (default `auto`) | Force `local` or `cloudconvert`. Leave unset for the same reason. |

Getting the keys:

- **Google Cloud Vision**: create (or reuse) a project in the
  [Google Cloud Console](https://console.cloud.google.com/), enable the
  "Cloud Vision API", then create an API key under
  **APIs & Services → Credentials**. Restrict the key to the Cloud Vision
  API only. This project calls the plain REST `images:annotate` endpoint
  with an API key — no service-account JSON or SDK is required.
- **CloudConvert**: sign up at [cloudconvert.com](https://cloudconvert.com),
  and create an API key under **Dashboard → API Keys**. The free tier
  includes a daily conversion-minute allowance, which is enough for
  low-volume testing but should be reviewed against real usage before
  relying on it for production volume.

Neither key is ever read by the frontend — both are read exclusively by
backend/python code, server-side, from `os.environ`.

## Deployment steps

1. Push this repository to a Git provider Vercel can import from (GitHub,
   GitLab, or Bitbucket).
2. In Vercel, **Add New → Project**, import the repo.
3. Framework Preset: choose **Other** (this is a static HTML/CSS/JS
   frontend, not a JS framework — Vercel should still auto-detect
   `index.html` at the repo root as the static output).
4. Leave the build command empty (there is nothing to build — the
   frontend is already plain, deployable HTML/CSS/JS, per this project's
   own technology rule).
5. Add the environment variables above.
6. Deploy.
7. Once deployed, open `https://<your-project>.vercel.app/index.html#/auth`
   and confirm `/api/health` reports both `"status": "ok"` and a real,
   live `ocrEngine` status — not just that the deployment loaded.

## How the pieces fit together

- **`vercel.json`** rewrites every `/api/*` request to `/api/index.py`, so
  the one FastAPI app defined in `backend/python/app.py` keeps handling
  every route (`/api/health`, `/api/passport/process`,
  `/api/documents/...`, etc.) exactly as it already does locally — nothing
  about the route definitions themselves changed.
- **`api/index.py`** is a thin shim: it adds `backend/python/` to
  `sys.path` and re-exports `app.py`'s existing `app` object. It contains
  no logic of its own.
- **`requirements.txt`** at the repo root is a copy of
  `backend/python/requirements.txt` (Vercel's Python builder looks for
  `requirements.txt` starting from the function's own directory and
  walking up to the project root — the function lives in `api/`, so a
  root-level file is the standard place). **Keep these two files in sync
  by hand whenever you change one** — there are only two of them, and this
  avoids adding tooling to a project whose one hard technology rule is "no
  build step."

## Things you should verify after your first real deploy (I could not test
## these against live Vercel infrastructure or real cloud credentials from
## inside this development sandbox — this is an honest gap, not something
## papered over)

- **Reference template files.** The document-generation engines read the
  real `.docx` templates from `reference-templates/`,
  `reference-cover-letter-formats/`, and `reference-hotel-blocking-formats/`
  using paths resolved from each engine's own file location (not the
  process's working directory), so they should be location-independent —
  but whether Vercel's Python builder includes these non-Python binary
  files in the deployed function by default is something to confirm.
  `vercel.json`'s `includeFiles` glob explicitly lists these directories
  (plus `assets/` for the logo) to make sure they're bundled; if a
  generated document comes back with a "reference template not found"
  error in production, start here.
- **Function duration.** A single passport-processing request can call
  Google Cloud Vision up to ~7 times in sequence (4 orientation guesses +
  2 MRZ-band crops + 1 whole-page pass) — see
  `backend/python/ocr_providers.py`'s `GoogleVisionOCRProvider` docstring.
  Even though each call is a fast, synchronous HTTP request (not an
  async/poll pattern), 7 of them in a row adds up. `vercel.json` sets
  `maxDuration: 60` for this function; confirm against your current Vercel
  plan's actual function-duration limits (these have changed over time and
  differ by plan) that this is enough, and raise it if not. Staff can also
  skip the 4-way orientation guess entirely by picking rotation manually —
  the existing `forced_rotation` option on the passport-upload screen
  already supports this, and doing so cuts 4 of those 7 calls.
- **Upload size limits.** Vercel serverless functions have a maximum
  request body size that is smaller than this project's current 25MB
  passport-upload cap (`MAX_UPLOAD_BYTES` in `backend/python/app.py`).
  Check Vercel's current limit for your plan; if a real passport photo
  upload is rejected in production before it even reaches this app's own
  size check, that limit — not a bug in this code — is why, and either the
  cap needs lowering or a different upload path (e.g. direct-to-storage)
  is needed.
- **Python runtime version.** `vercel.json` intentionally does not pin an
  exact Python version, so Vercel will use its own current default. If a
  dependency (particularly `opencv-python-headless`, which ships
  platform-specific compiled wheels) fails to install, pinning a specific
  supported version in your Vercel project settings is the fix.

## Local development is unaffected

Running `uvicorn app:app --reload --port 8000` from `backend/python/` on a
staff member's own machine behaves exactly as it did before this change:
no `GOOGLE_VISION_API_KEY`/`CLOUDCONVERT_API_KEY` means `OCR_PROVIDER=auto`
and `PDF_CONVERSION_PROVIDER=auto` both fall back to the original local
Tesseract/LibreOffice path, with zero configuration required.
