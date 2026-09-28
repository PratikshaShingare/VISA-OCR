"""
Khanna Travels & Holidays — local backend API
================================================

Thin FastAPI wrapper around ocr_runner.py. Runs entirely on the staff
member's own machine — no passport image or field ever leaves it (Phase 11
of the project instructions: passport data must not be exposed or sent
anywhere unnecessarily).

Run locally:
    pip install -r requirements.txt
    uvicorn app:app --reload --port 8000

The frontend (js/core/api.js) talks to this on http://localhost:8000 by
default. See README.md in this folder for full setup instructions,
including installing the Tesseract OCR binary itself.
"""

from __future__ import annotations

import io
import os
import re
import tempfile
from datetime import datetime, timezone
from typing import Any, Literal, Optional

from dotenv import load_dotenv

# Loads backend/python/.env (if present) into the process environment
# before any of this project's own modules are imported below — several of
# them (ocr_providers.py, pdf_conversion.py) read GOOGLE_VISION_API_KEY /
# CLOUDCONVERT_API_KEY / OCR_PROVIDER / PDF_CONVERSION_PROVIDER from
# os.environ at import time or on first call, so this must run first, before
# `import ocr_providers` / `import ocr_runner` below. This is a
# local-development convenience only: on Vercel there is no .env file (the
# platform injects real environment variables directly into the process),
# so this is a harmless no-op in production — no behaviour change there
# (project rule 16). See .env.example in this folder.
load_dotenv()

import pytesseract
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

import admin_export_engine
import authorization_letter_engine
import cover_letter_engine
import data_model
import docx_utils
import hotel_voucher_engine
import hotel_voucher_ocr
import invitation_letter_engine
import ocr_providers
import ocr_runner
import openrouter_ocr
import required_document_letter_engine
import visa_requirements_data

app = FastAPI(title="Khanna Travels & Holidays — Local Backend", version="0.1.0")

# Permissive CORS: this server only ever listens on localhost and only ever
# talks to the staff member's own browser tab running the app's index.html
# (opened via file:// or a local static server) — there is no real
# cross-origin risk in that setup, and it must work for every local origin
# without staff having to hand-configure anything.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
    # Content-Disposition isn't in the CORS-safelisted response headers by
    # default, so without this the frontend's fetch() can't read the real
    # filename we set for a generated document (js/core/api.js falls back
    # to a generic name) — needed as soon as any endpoint streams a file
    # download rather than JSON (Phase 7's hotel voucher, and later
    # cover/authorization/invitation letters).
    expose_headers=["Content-Disposition"],
)

MAX_UPLOAD_BYTES = 25 * 1024 * 1024  # 25MB
ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".pdf"}

# A signature is a small image embedded once into a generated .docx (Phase
# 10 — docx_utils.insert_signature_image), not a scanned document page, so
# it gets its own, much smaller cap and a narrower format allow-list than
# the passport-processing upload above.
MAX_SIGNATURE_BYTES = 5 * 1024 * 1024  # 5MB
SIGNATURE_ALLOWED_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}


@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "service": "khanna-backend",
        "version": app.version,
        # Real, live status of whichever OCR engine is actually active —
        # Tesseract (local) or Google Cloud Vision (cloud, used on Vercel) — so
        # whoever is setting this deployment up can confirm OCR will work
        # without needing to upload a passport first just to find out
        # (project rule 9 — never fake status).
        "ocrEngine": ocr_runner.get_ocr_engine_status(),
    }


@app.post("/api/passport/process")
async def process_passport(
    file: UploadFile = File(...),
    page_index: int = Form(0),
    forced_rotation: Optional[int] = Form(None),
):
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(400, f"Unsupported file type '{ext}'. Allowed: {sorted(ALLOWED_EXTENSIONS)}")

    contents = await file.read()
    if len(contents) > MAX_UPLOAD_BYTES:
        raise HTTPException(400, "File too large (max 25MB).")
    if not contents:
        raise HTTPException(400, "Uploaded file is empty.")

    with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
        tmp.write(contents)
        tmp_path = tmp.name

    try:
        result = ocr_runner.process_passport_file(
            tmp_path, page_index=page_index, forced_rotation=forced_rotation
        )
    except IndexError as e:
        raise HTTPException(400, str(e))
    except pytesseract.pytesseract.TesseractNotFoundError:
        status = ocr_runner.get_ocr_engine_status()
        raise HTTPException(
            503,
            "The Tesseract OCR engine isn't available on this machine "
            f"(looked for it at '{status.get('path')}'). {status.get('hint', '')}",
        )
    except ocr_providers.OCRProviderError as e:
        # The active provider (Google Cloud Vision in a Vercel deployment) is
        # genuinely unusable right now — missing/invalid credentials,
        # unreachable, or timed out. Surfaced as a clean 503, same as the
        # Tesseract-not-found case above, never a raw 500 stack trace.
        raise HTTPException(503, f"OCR is currently unavailable: {e}")
    except Exception as e:  # noqa: BLE001 — surface as a clean 500, never a raw stack trace to the UI
        raise HTTPException(500, f"Passport processing failed: {e}")
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass

    return result


@app.post("/api/passport/process-openrouter")
async def process_passport_openrouter(file: UploadFile = File(...)):
    """TESTING PATH — a second, independent passport-OCR route that calls an
    OpenRouter vision model instead of the existing Tesseract/Google Cloud
    Vision pipeline above. Deliberately separate from /api/passport/process:
    it does not call ocr_runner.process_passport_file, does not share its
    orientation/deskew/crop image pipeline, and is wired to its own,
    clearly-labelled frontend button (see js/passport/passport-processing.js)
    so staff can compare the two without the production OCR path being
    touched at all. See openrouter_ocr.py for the full design/security
    notes — in short: OPENROUTER_API_KEY lives only in this process's
    environment, is read fresh on every call, and is never sent to or
    accepted from the frontend.

    Single image only (JPG/PNG/WEBP) — this testing path implements
    "passport image -> OCR extraction -> structured JSON" only, not PDF or
    multi-page handling."""
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in openrouter_ocr.MIME_BY_EXTENSION:
        raise HTTPException(
            400,
            f"Unsupported file type '{ext}' for this OCR test path. "
            f"Allowed: {sorted(openrouter_ocr.MIME_BY_EXTENSION)} (a scanned image, not a PDF).",
        )

    contents = await file.read()
    if len(contents) > MAX_UPLOAD_BYTES:
        raise HTTPException(400, "File too large (max 25MB).")
    if not contents:
        raise HTTPException(400, "Uploaded file is empty.")

    try:
        result = openrouter_ocr.extract_passport_fields_via_openrouter(contents, file.filename or "")
    except openrouter_ocr.OpenRouterOCRError as e:
        raise HTTPException(503, str(e))
    except Exception as e:  # noqa: BLE001 — surface as a clean 500, never a raw stack trace to the UI
        raise HTTPException(500, f"OpenRouter passport processing failed: {e}")

    return result


@app.post("/api/passport/page-count")
async def page_count(file: UploadFile = File(...)):
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(400, f"Unsupported file type '{ext}'.")

    contents = await file.read()
    with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
        tmp.write(contents)
        tmp_path = tmp.name

    try:
        pages = ocr_runner.load_pages(tmp_path)
        return {"totalPages": len(pages)}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(500, f"Could not read file: {e}")
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


@app.post("/api/hotel-voucher/process")
async def process_hotel_voucher_upload(
    file: UploadFile = File(...),
    page_index: int = Form(0),
):
    """Hotel Blocking's "Upload Hotel Voucher" — extracts whatever fields
    hotel_voucher_ocr.py can find on a staff-uploaded hotel/OTA voucher
    (image or PDF) so the Hotel Blocking form doesn't have to be retyped by
    hand. Mirrors /api/passport/process's own request/error shape exactly
    (same upload-size/type limits, same clean-error-not-a-stack-trace
    handling) — this is a sibling endpoint, not a variant of that one, since
    hotel vouchers share nothing with passport MRZ/bio-data parsing beyond
    the underlying image pipeline (see hotel_voucher_ocr.py's own docstring)."""
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(400, f"Unsupported file type '{ext}'. Allowed: {sorted(ALLOWED_EXTENSIONS)}")

    contents = await file.read()
    if len(contents) > MAX_UPLOAD_BYTES:
        raise HTTPException(400, "File too large (max 25MB).")
    if not contents:
        raise HTTPException(400, "Uploaded file is empty.")

    with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
        tmp.write(contents)
        tmp_path = tmp.name

    try:
        result = hotel_voucher_ocr.process_hotel_voucher_file(tmp_path, page_index=page_index)
    except IndexError as e:
        raise HTTPException(400, str(e))
    except pytesseract.pytesseract.TesseractNotFoundError:
        status = ocr_runner.get_ocr_engine_status()
        raise HTTPException(
            503,
            "The Tesseract OCR engine isn't available on this machine "
            f"(looked for it at '{status.get('path')}'). {status.get('hint', '')}",
        )
    except ocr_providers.OCRProviderError as e:
        raise HTTPException(503, f"OCR is currently unavailable: {e}")
    except Exception as e:  # noqa: BLE001 — surface as a clean 500, never a raw stack trace to the UI
        raise HTTPException(500, f"Hotel voucher processing failed: {e}")
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass

    return result


PREVIEW_CONVERTIBLE_EXTENSIONS = {".docx"}
MAX_PREVIEW_UPLOAD_BYTES = 25 * 1024 * 1024  # 25MB — same cap as a passport upload


@app.post("/api/documents/preview-convert")
async def preview_convert(file: UploadFile = File(...)):
    """Phase 3 fix for the "DOCX preview does not work properly" bug report.

    A browser cannot reliably render a .docx file inline — window.open()-ing
    its raw bytes either downloads it or shows garbled XML, which is exactly
    the fake, non-functional "preview" project rule 9 rules out. The correct
    fix (per the project's own instructions) is a real backend conversion to
    PDF, which browsers DO render natively. This reuses the exact same,
    already-tested docx_utils.convert_docx_bytes_to_pdf() every generated
    document's own PDF download already goes through (project rule 15 — no
    second conversion path) — local LibreOffice or CloudConvert, whichever
    PDF_CONVERSION_PROVIDER resolves to.

    This is a READ-ONLY preview: the uploaded bytes are converted in memory
    and streamed straight back, never written anywhere the original staff
    upload could be confused with or overwrite. The frontend's own copy of
    the original .docx (js/documents/document-file-store.js, in-memory only)
    is never touched by this endpoint — the conversion result is a separate,
    disposable PDF the browser tab discards once closed."""
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in PREVIEW_CONVERTIBLE_EXTENSIONS:
        raise HTTPException(
            400,
            f"Preview conversion only supports {sorted(PREVIEW_CONVERTIBLE_EXTENSIONS)} files, not '{ext}'. "
            "Images and PDFs already open directly in the browser and don't need this endpoint.",
        )

    contents = await file.read()
    if len(contents) > MAX_PREVIEW_UPLOAD_BYTES:
        raise HTTPException(400, "File too large to preview (max 25MB).")
    if not contents:
        raise HTTPException(400, "Uploaded file is empty.")

    base_name = os.path.splitext(file.filename or "document")[0] or "document"
    try:
        pdf_bytes = docx_utils.convert_docx_bytes_to_pdf(contents, base_name=base_name)
    except docx_utils.DocxBuildError as e:
        # Never silently fall back to "just download the original" — that
        # would hide the real reason a staff member sees no preview at all
        # (project rule: "do not simply hide the error message").
        raise HTTPException(503, f"Could not convert this file for preview: {e}")
    except Exception as e:  # noqa: BLE001 — surface as a clean 500, never a raw stack trace to the UI
        raise HTTPException(500, f"Preview conversion failed: {e}")

    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        # "inline", not "attachment" — this is a preview to view in a new
        # tab, not a file to save, unlike every download endpoint above.
        headers={"Content-Disposition": 'inline; filename="preview.pdf"'},
    )


@app.get("/api/applications/status-list")
def status_list():
    """Exposes the canonical status list from data_model.py so the frontend
    and backend never drift apart on what a valid Application status is."""
    return {"statuses": data_model.STATUSES}


def _safe_filename(applicant_name: Optional[str], suffix: str, ext: str) -> str:
    """Builds "<Applicant_Name>_<Suffix>.<ext>" when a real applicant name
    was given, or just "<Suffix>.<ext>" when it wasn't — never
    "<Suffix>_<Suffix>.<ext>". Real bug found while testing the Required
    Document Letter endpoint (which, being a standalone letter with no
    Applicant/Traveller record, always calls this with applicant_name=None):
    the previous version fell back to using `suffix` itself as the
    applicant-name slot, then unconditionally appended `_{suffix}` again,
    producing a doubled, unprofessional-looking filename
    (`Required_Document_Letter_Required_Document_Letter.docx`) for every
    document type whenever no applicant name is available — not new to this
    endpoint, just newly surfaced by it."""
    if applicant_name:
        safe_name = re.sub(r"[^A-Za-z0-9_-]+", "_", applicant_name).strip("_")
        if safe_name:
            return f"{safe_name}_{suffix}.{ext}"
    return f"{suffix}.{ext}"


async def _read_optional_signature(signature: Optional[UploadFile]) -> Optional[bytes]:
    """Shared upload/validation for the one new kind of file the Phase 10
    document endpoints accept: a real staff-uploaded signature image,
    embedded via docx_utils.insert_signature_image. Returns None when no
    file was actually chosen (FastAPI still hands us an UploadFile with an
    empty filename in that case for an `Optional[UploadFile] = File(None)`
    field submitted via a browser form with the input left empty) — the
    generator engines already treat a None/falsy signature_bytes as "leave
    the template's own blank signature slot exactly as blank" (never a
    fabricated signature, project rule 9)."""
    if signature is None or not signature.filename:
        return None
    ext = os.path.splitext(signature.filename or "")[1].lower()
    if ext not in SIGNATURE_ALLOWED_EXTENSIONS:
        raise HTTPException(
            400, f"Unsupported signature image type '{ext}'. Allowed: {sorted(SIGNATURE_ALLOWED_EXTENSIONS)}"
        )
    contents = await signature.read()
    if len(contents) > MAX_SIGNATURE_BYTES:
        raise HTTPException(400, "Signature image too large (max 5MB).")
    return contents or None


def _stream_document(build_docx, build_pdf, fmt: str, error_types: tuple, applicant_name: Optional[str], suffix: str) -> StreamingResponse:
    """Shared "generate + stream" plumbing for every document-download
    endpoint (Hotel Voucher, and now both Authorization Letters) — the same
    docx-or-pdf branching, error mapping and Content-Disposition filename
    logic, factored out in Phase 8 so a future document endpoint doesn't
    duplicate it again (project rule 15)."""
    try:
        if fmt == "pdf":
            content = build_pdf()
            media_type = "application/pdf"
            ext = "pdf"
        else:
            content = build_docx()
            media_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            ext = "docx"
    except ValueError as e:
        raise HTTPException(400, str(e))
    except error_types as e:
        raise HTTPException(500, str(e))
    except Exception as e:  # noqa: BLE001 — surface as a clean 500, never a raw stack trace to the UI
        raise HTTPException(500, f"{suffix.replace('_', ' ')} generation failed: {e}")

    filename = _safe_filename(applicant_name, suffix, ext)
    return StreamingResponse(
        io.BytesIO(content),
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


class HotelItem(BaseModel):
    hotelName: str = ""
    phone: str = ""
    address: str = ""
    city: str = ""
    confirmationNumber: str = ""
    leadGuestName: str = ""
    # Split from a single "noOfGuests" field on explicit request, so the
    # generated voucher can print a real "2 Adult(s), 2 Child(s)"-style
    # combined count instead of one undifferentiated number (see
    # hotel_voucher_engine.py's _format_guest_counts()).
    noOfAdults: str = ""
    noOfChildren: str = ""
    noOfRooms: str = ""
    roomType: str = ""
    checkIn: str = ""
    checkOut: str = ""
    guestNames: list[str] = []


class HotelVoucherRequest(BaseModel):
    hotels: list[HotelItem]
    format: Literal["docx", "pdf"] = "docx"
    applicantName: Optional[str] = None


@app.post("/api/documents/hotel-voucher")
def hotel_voucher(payload: HotelVoucherRequest):
    if not payload.hotels:
        raise HTTPException(400, "At least one hotel is required.")

    hotels = [h.model_dump() for h in payload.hotels]
    return _stream_document(
        build_docx=lambda: hotel_voucher_engine.generate_hotel_voucher_docx(hotels),
        build_pdf=lambda: hotel_voucher_engine.generate_hotel_voucher_pdf(hotels),
        fmt=payload.format,
        error_types=(hotel_voucher_engine.HotelVoucherError,),
        applicant_name=payload.applicantName,
        suffix="Hotel_Voucher",
    )


class AuthPerson(BaseModel):
    salutation: str = ""
    fullName: str = ""
    passportNumber: str = ""
    relationToApplicant: str = ""
    sex: str = ""
    phone: str = ""
    email: str = ""
    isApplicant: bool = False


class PassportAuthorizationRequest(BaseModel):
    people: list[AuthPerson]
    recipientCentreName: str = ""
    recipientAddress: str = ""
    collectorName: str = ""
    dateOverride: Optional[str] = None
    format: Literal["docx", "pdf"] = "docx"
    applicantName: Optional[str] = None


class CompanyAuthPerson(BaseModel):
    fullName: str = ""
    passportNumber: str = ""


class CompanyAuthorizationRequest(BaseModel):
    people: list[CompanyAuthPerson]
    recipientText: str = ""
    dateOverride: Optional[str] = None
    format: Literal["docx", "pdf"] = "docx"
    applicantName: Optional[str] = None


@app.post("/api/documents/passport-authorization")
def passport_authorization(payload: PassportAuthorizationRequest):
    if not payload.people:
        raise HTTPException(400, "At least one traveller is required.")

    people = [p.model_dump() for p in payload.people]
    return _stream_document(
        build_docx=lambda: authorization_letter_engine.generate_passport_authorization_docx(
            people, payload.recipientCentreName, payload.recipientAddress, payload.collectorName, payload.dateOverride
        ),
        build_pdf=lambda: authorization_letter_engine.generate_passport_authorization_pdf(
            people, payload.recipientCentreName, payload.recipientAddress, payload.collectorName, payload.dateOverride
        ),
        fmt=payload.format,
        error_types=(authorization_letter_engine.AuthorizationLetterError, docx_utils.DocxBuildError),
        applicant_name=payload.applicantName,
        suffix="Passport_Authorization",
    )


@app.post("/api/documents/company-authorization")
def company_authorization(payload: CompanyAuthorizationRequest):
    if not payload.people:
        raise HTTPException(400, "At least one applicant is required.")

    people = [p.model_dump() for p in payload.people]
    return _stream_document(
        build_docx=lambda: authorization_letter_engine.generate_company_authorization_docx(
            people, payload.recipientText, payload.dateOverride
        ),
        build_pdf=lambda: authorization_letter_engine.generate_company_authorization_pdf(
            people, payload.recipientText, payload.dateOverride
        ),
        fmt=payload.format,
        error_types=(authorization_letter_engine.AuthorizationLetterError, docx_utils.DocxBuildError),
        applicant_name=payload.applicantName,
        suffix="Company_Authorization",
    )


class CoverLetterPerson(BaseModel):
    id: str = ""
    salutation: str = ""
    fullName: str = ""
    passportNumber: str = ""
    placeOfIssue: str = ""
    passportIssueDate: str = ""
    relationToApplicant: str = ""
    sex: str = ""
    phone: str = ""
    email: str = ""
    isApplicant: bool = False
    occupation: str = ""


class CoverLetterHotel(BaseModel):
    name: str = ""
    checkIn: str = ""
    checkOut: str = ""
    contactNo: str = ""


class CoverLetterRequest(BaseModel):
    region: Literal["Europe", "Japan", "Singapore"]
    people: list[CoverLetterPerson]
    recipientText: str = ""
    destinationCountry: str = ""
    travelStartDate: str = ""
    travelEndDate: str = ""
    fundingArrangement: str = ""
    dateOverride: Optional[str] = None
    format: Literal["docx", "pdf"] = "docx"
    applicantName: Optional[str] = None
    # Europe-only
    cityCountryOfResidence: str = ""
    numberOfNights: str = ""
    applicantEmploymentStatus: str = ""
    applicantJobTitle: str = ""
    applicantEmployerName: str = ""
    companionJobTitle: str = ""
    companionEmployerName: str = ""
    companionEmploymentStartYear: str = ""
    nextCountry: str = ""
    nextTravelStartDate: str = ""
    nextTravelEndDate: str = ""
    nextNumberOfNights: str = ""
    # Japan-only
    applicantEmployerOccupation: str = ""
    companionOccupation: str = ""
    hotels: list[CoverLetterHotel] = []
    # Singapore-only
    hotelName: str = ""
    hotelAddress: str = ""


def _split_applicant_and_companions(people: list[dict]) -> tuple[Optional[dict], list[dict]]:
    """Every cover letter is written in the applicant's own voice, so the
    person flagged isApplicant leads (falling back to the first person in
    the list if none is flagged, mirroring letter_shared.order_people's own
    fallback) — everyone else is a companion, in the order given."""
    if not people:
        return None, []
    applicant = next((p for p in people if p.get("isApplicant")), people[0])
    companions = [p for p in people if p is not applicant]
    return applicant, companions


@app.post("/api/documents/cover-letter")
def cover_letter(payload: CoverLetterRequest):
    if not payload.people:
        raise HTTPException(400, "At least the applicant is required.")

    people = [p.model_dump() for p in payload.people]
    applicant, companions = _split_applicant_and_companions(people)

    common_fields = {
        "recipientText": payload.recipientText,
        "destinationCountry": payload.destinationCountry,
        "travelStartDate": payload.travelStartDate,
        "travelEndDate": payload.travelEndDate,
        "fundingArrangement": payload.fundingArrangement,
    }

    if payload.region in ("Europe", "Japan"):
        if len(companions) != 1:
            raise HTTPException(
                400,
                f"The {payload.region} Cover Letter is written for the applicant plus exactly one companion "
                f"(matching the reference template's own fixed wording) — {len(companions)} companion(s) were given.",
            )
        companion = companions[0]

        if payload.region == "Europe":
            fields = dict(
                common_fields,
                cityCountryOfResidence=payload.cityCountryOfResidence,
                numberOfNights=payload.numberOfNights,
                applicantEmploymentStatus=payload.applicantEmploymentStatus,
                applicantJobTitle=payload.applicantJobTitle,
                applicantEmployerName=payload.applicantEmployerName,
                companionJobTitle=payload.companionJobTitle,
                companionEmployerName=payload.companionEmployerName,
                companionEmploymentStartYear=payload.companionEmploymentStartYear,
                nextCountry=payload.nextCountry,
                nextTravelStartDate=payload.nextTravelStartDate,
                nextTravelEndDate=payload.nextTravelEndDate,
                nextNumberOfNights=payload.nextNumberOfNights,
            )
            return _stream_document(
                build_docx=lambda: cover_letter_engine.generate_europe_cover_letter_docx(
                    applicant, companion, fields, payload.dateOverride
                ),
                build_pdf=lambda: cover_letter_engine.generate_europe_cover_letter_pdf(
                    applicant, companion, fields, payload.dateOverride
                ),
                fmt=payload.format,
                error_types=(cover_letter_engine.CoverLetterError, docx_utils.DocxBuildError),
                applicant_name=payload.applicantName,
                suffix="Europe_Cover_Letter",
            )

        # Japan
        fields = dict(
            common_fields,
            applicantEmployerOccupation=payload.applicantEmployerOccupation,
            companionOccupation=payload.companionOccupation,
        )
        hotels = [h.model_dump() for h in payload.hotels]
        return _stream_document(
            build_docx=lambda: cover_letter_engine.generate_japan_cover_letter_docx(
                applicant, companion, fields, hotels, payload.dateOverride
            ),
            build_pdf=lambda: cover_letter_engine.generate_japan_cover_letter_pdf(
                applicant, companion, fields, hotels, payload.dateOverride
            ),
            fmt=payload.format,
            error_types=(cover_letter_engine.CoverLetterError, docx_utils.DocxBuildError),
            applicant_name=payload.applicantName,
            suffix="Japan_Cover_Letter",
        )

    # Singapore — applicant alone, or applicant + any number of companions
    occupations = {p.get("id"): p.get("occupation") or "" for p in people if p.get("id")}
    fields = dict(
        common_fields,
        hotelName=payload.hotelName,
        hotelAddress=payload.hotelAddress,
        occupations=occupations,
    )
    return _stream_document(
        build_docx=lambda: cover_letter_engine.generate_singapore_cover_letter_docx(
            applicant, companions, fields, payload.dateOverride
        ),
        build_pdf=lambda: cover_letter_engine.generate_singapore_cover_letter_pdf(
            applicant, companions, fields, payload.dateOverride
        ),
        fmt=payload.format,
        error_types=(cover_letter_engine.CoverLetterError, docx_utils.DocxBuildError),
        applicant_name=payload.applicantName,
        suffix="Singapore_Cover_Letter",
    )


# ---------------------------------------------------------------------------
# Invitation Letter + Initors Covering Letter (Phase 10)
#
# The only two document endpoints that take a real file upload alongside
# their structured data (a staff-uploaded signature image), so — unlike
# every JSON-body document endpoint above — these are multipart/form-data:
# the same JSON shape as always, but carried in a `payload` form FIELD
# (parsed with Pydantic's model_validate_json) instead of the request
# body, so it can sit alongside an optional `signature` file part. This is
# a new pattern in this file, not a duplication of an existing one
# (project rule 15 — nothing above already does this).
# ---------------------------------------------------------------------------


class InvitationLetterInviter(BaseModel):
    fullName: str = ""
    addressLine1: str = ""
    addressLine2: str = ""
    cityPostcode: str = ""
    country: str = ""
    cityCountry: str = ""
    passportNumber: str = ""
    fullAddress: str = ""
    studyingOrWorking: str = ""
    universityOrCompany: str = ""
    phone: str = ""
    email: str = ""


class InvitationLetterInvitee(BaseModel):
    fullName: str = ""
    passportNumber: str = ""
    placeOfIssue: str = ""
    passportIssueDate: str = ""


class InvitationLetterRequest(BaseModel):
    inviter: InvitationLetterInviter
    invitees: list[InvitationLetterInvitee]
    travelStartDate: str = ""
    travelEndDate: str = ""
    purpose: str = ""
    accommodationDetails: str = ""
    returnDate: str = ""
    fundingArrangement: str = ""
    dateOverride: Optional[str] = None
    format: Literal["docx", "pdf"] = "docx"
    applicantName: Optional[str] = None


@app.post("/api/documents/invitation-letter")
async def invitation_letter(
    payload: str = Form(...),
    signature: Optional[UploadFile] = File(None),
):
    try:
        parsed = InvitationLetterRequest.model_validate_json(payload)
    except Exception as e:  # noqa: BLE001 — a malformed `payload` form field is a client error, not a 500
        raise HTTPException(400, f"Invalid request payload: {e}")

    signature_bytes = await _read_optional_signature(signature)

    inviter = parsed.inviter.model_dump()
    invitees = [i.model_dump() for i in parsed.invitees]
    fields = {
        "travelStartDate": parsed.travelStartDate,
        "travelEndDate": parsed.travelEndDate,
        "purpose": parsed.purpose,
        "accommodationDetails": parsed.accommodationDetails,
        "returnDate": parsed.returnDate,
        "fundingArrangement": parsed.fundingArrangement,
    }
    return _stream_document(
        build_docx=lambda: invitation_letter_engine.generate_invitation_letter_docx(
            inviter, invitees, fields, signature_bytes, parsed.dateOverride
        ),
        build_pdf=lambda: invitation_letter_engine.generate_invitation_letter_pdf(
            inviter, invitees, fields, signature_bytes, parsed.dateOverride
        ),
        fmt=parsed.format,
        error_types=(invitation_letter_engine.InvitationLetterError, docx_utils.DocxBuildError),
        applicant_name=parsed.applicantName,
        suffix="Invitation_Letter",
    )


class InitorsSubject(BaseModel):
    fullName: str = ""
    passportNumber: str = ""
    placeOfIssue: str = ""
    passportIssueDate: str = ""
    sex: str = ""
    phone: str = ""
    email: str = ""
    occupation: str = ""
    relationWithInvitingPerson: str = ""


class InitorsSpouse(BaseModel):
    fullName: str = ""
    passportNumber: str = ""
    placeOfIssue: str = ""
    passportIssueDate: str = ""
    occupation: str = ""


class InitorsInvitingPerson(BaseModel):
    fullName: str = ""
    passportNumber: str = ""
    countryOfResidence: str = ""
    visaResidenceStatus: str = ""


class InitorsCoveringLetterRequest(BaseModel):
    subject: InitorsSubject
    spouse: InitorsSpouse
    invitingPerson: InitorsInvitingPerson
    country: str = ""
    purpose: str = ""
    travelStartDate: str = ""
    travelEndDate: str = ""
    returnDate: str = ""
    accommodationDetails: str = ""
    otherCommitments: str = ""
    invitationSupportingDocuments: str = ""
    dateOverride: Optional[str] = None
    format: Literal["docx", "pdf"] = "docx"
    applicantName: Optional[str] = None


@app.post("/api/documents/initors-covering-letter")
async def initors_covering_letter(
    payload: str = Form(...),
    signature: Optional[UploadFile] = File(None),
):
    try:
        parsed = InitorsCoveringLetterRequest.model_validate_json(payload)
    except Exception as e:  # noqa: BLE001 — a malformed `payload` form field is a client error, not a 500
        raise HTTPException(400, f"Invalid request payload: {e}")

    signature_bytes = await _read_optional_signature(signature)

    subject = parsed.subject.model_dump()
    spouse = parsed.spouse.model_dump()
    inviting_person = parsed.invitingPerson.model_dump()
    fields = {
        "country": parsed.country,
        "purpose": parsed.purpose,
        "travelStartDate": parsed.travelStartDate,
        "travelEndDate": parsed.travelEndDate,
        "returnDate": parsed.returnDate,
        "accommodationDetails": parsed.accommodationDetails,
        "otherCommitments": parsed.otherCommitments,
        "invitationSupportingDocuments": parsed.invitationSupportingDocuments,
    }
    return _stream_document(
        build_docx=lambda: invitation_letter_engine.generate_initors_covering_letter_docx(
            subject, spouse, inviting_person, fields, signature_bytes, parsed.dateOverride
        ),
        build_pdf=lambda: invitation_letter_engine.generate_initors_covering_letter_pdf(
            subject, spouse, inviting_person, fields, signature_bytes, parsed.dateOverride
        ),
        fmt=parsed.format,
        error_types=(invitation_letter_engine.InvitationLetterError, docx_utils.DocxBuildError),
        applicant_name=parsed.applicantName,
        suffix="Initors_Covering_Letter",
    )


# ---------------------------------------------------------------------------
# Required Document Letter — a standalone checklist letter, not tied to any
# Applicant/Traveller record. The country/visa-type/employment-status rules
# live server-side (this file + visa_requirements_data.py /
# required_document_letter_engine.py), not as frontend if/else, so the
# frontend only ever needs to render whatever this backend returns.
# ---------------------------------------------------------------------------


@app.get("/api/visa-requirements/countries")
def visa_requirements_countries():
    """Real, static reference data for every dropdown/checklist on the
    Required Document Letter page: the country typeahead, the expanded
    visa-type and employment-status lists, the bank-statement/ITR/
    processing-time pick-lists, and the full document catalog (every
    document this letter can ever list, in canonical order) — a single
    source of truth the frontend renders from, never its own hardcoded
    option lists or document if/else chains."""
    return {
        "countries": visa_requirements_data.COUNTRIES,
        "visaTypes": visa_requirements_data.VISA_TYPES,
        "employmentStatuses": visa_requirements_data.EMPLOYMENT_STATUSES,
        "bankStatementDurationOptions": visa_requirements_data.BANK_STATEMENT_DURATION_OPTIONS,
        "itrYearOptions": visa_requirements_data.ITR_YEAR_OPTIONS,
        "processingTimeOptions": visa_requirements_data.PROCESSING_TIME_OPTIONS,
        "documentCatalog": visa_requirements_data.get_document_catalog(),
    }


@app.get("/api/visa-requirements/suggested-documents")
def visa_requirements_suggested_documents(
    visaType: str,
    employmentStatus: str = "Other",
    invited: bool = False,
    hasUsVisaCopy: bool = False,
    country: Optional[str] = None,
):
    """Returns which document ids should be PRE-CHECKED for this enquiry,
    computed from the structured DOCUMENT_CATALOG rule engine (never a
    frontend if/else chain — see visa_requirements_data.py's own module
    docstring). Every id returned is still just a suggestion: the frontend
    renders it as an editable, pre-checked checkbox, and only whatever is
    actually still checked at generation time is sent back to
    /api/documents/required-document-letter."""
    if visaType not in visa_requirements_data.VISA_TYPES:
        raise HTTPException(400, f"visaType must be one of {visa_requirements_data.VISA_TYPES}.")
    if employmentStatus not in visa_requirements_data.EMPLOYMENT_STATUSES:
        raise HTTPException(400, f"employmentStatus must be one of {visa_requirements_data.EMPLOYMENT_STATUSES}.")
    circumstances = []
    if invited:
        circumstances.append("invited")
    if hasUsVisaCopy:
        circumstances.append("hasUsVisaCopy")
    return {
        "suggestedDocumentIds": visa_requirements_data.resolve_suggested_document_ids(
            visaType, employmentStatus, circumstances, country
        )
    }


@app.get("/api/visa-requirements/lookup")
def visa_requirements_lookup(country: str, visaType: str):
    """Returns whatever REAL, sourced figures this app currently has for
    this exact country+visaType combination (see visa_requirements_data.py's
    own module docstring for how narrow that currently is) — an empty
    object when nothing has been verified, never a guessed number. The
    frontend uses this only to PRE-FILL editable fields; staff can always
    override it, and a missing field is shown as "Check current official
    requirement," never silently left blank with no explanation."""
    if visaType not in visa_requirements_data.VISA_TYPES:
        raise HTTPException(400, f"visaType must be one of {visa_requirements_data.VISA_TYPES}.")
    return visa_requirements_data.lookup(country, visaType)


class RequiredDocumentLetterRequest(BaseModel):
    country: str
    visaType: str
    employmentStatus: str = "Other"
    documentIds: list[str] = []
    bankStatementDuration: str = ""
    itrYears: str = ""
    processingTime: str = ""
    visaFees: str = ""
    format: Literal["docx", "pdf"] = "docx"
    applicantName: Optional[str] = None


@app.post("/api/documents/required-document-letter")
def required_document_letter(payload: RequiredDocumentLetterRequest):
    if not payload.country or not payload.country.strip():
        raise HTTPException(400, "Country is required.")
    if payload.visaType not in visa_requirements_data.VISA_TYPES:
        raise HTTPException(400, f"visaType must be one of {visa_requirements_data.VISA_TYPES}.")
    if payload.employmentStatus not in visa_requirements_data.EMPLOYMENT_STATUSES:
        raise HTTPException(400, f"employmentStatus must be one of {visa_requirements_data.EMPLOYMENT_STATUSES}.")

    kwargs = dict(
        country=payload.country,
        visa_type=payload.visaType,
        employment_status=payload.employmentStatus,
        document_ids=payload.documentIds,
        bank_statement_duration=payload.bankStatementDuration,
        itr_years=payload.itrYears,
        processing_time=payload.processingTime,
        visa_fees=payload.visaFees,
    )
    return _stream_document(
        build_docx=lambda: required_document_letter_engine.generate_required_document_letter_docx(**kwargs),
        build_pdf=lambda: required_document_letter_engine.generate_required_document_letter_pdf(**kwargs),
        fmt=payload.format,
        error_types=(required_document_letter_engine.RequiredDocumentLetterError, docx_utils.DocxBuildError),
        applicant_name=payload.applicantName,
        suffix="Required_Document_Letter",
    )


class AdminExportRequest(BaseModel):
    # Deliberately `list[dict]`, not a strict per-field Pydantic model: this
    # app has no backend datastore for Application records (they live in
    # the browser's localStorage — state.js's own header comment), so the
    # frontend simply posts its current in-memory `KhannaState.getApplications()`
    # array as-is. admin_export_engine.py already reads every field
    # defensively (`.get(...)`, em-dash for anything missing), matching the
    # same tolerance data_model.py's own `validate_application` uses for
    # this same reason.
    applications: list[dict[str, Any]] = []


@app.post("/api/admin/export-excel")
def admin_export_excel(payload: AdminExportRequest):
    """Phase 11 — Master Excel export. Builds a real, multi-sheet .xlsx
    workbook (Applications / Travellers / Status Summary) from whatever
    Application records the frontend currently holds and streams it back —
    the same "frontend sends the data it already has, backend does the real
    work, no fabrication" shape as every document-generation endpoint
    above, just producing a spreadsheet instead of a .docx."""
    try:
        content = admin_export_engine.build_applications_workbook(payload.applications)
    except admin_export_engine.AdminExportError as e:
        raise HTTPException(400, str(e))
    except Exception as e:  # noqa: BLE001 — surface as a clean 500, never a raw stack trace to the UI
        raise HTTPException(500, f"Excel export failed: {e}")

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M")
    filename = f"Khanna_Applications_Export_{stamp}.xlsx"
    return StreamingResponse(
        io.BytesIO(content),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
