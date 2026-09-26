"""
Khanna Travels & Holidays — .docx -> PDF conversion provider abstraction
===========================================================================

docx_utils.convert_docx_bytes_to_pdf() (called from every document engine —
hotel_voucher_engine.py, authorization_letter_engine.py,
cover_letter_engine.py, invitation_letter_engine.py — project rule 15: one
shared implementation, never duplicated per engine) now dispatches to one
of the two functions below instead of always shelling out to a local
LibreOffice ('soffice') install.

Local ('soffice') conversion still works exactly as before for anyone
running this backend on their own machine — zero behaviour change there.
It is simply not available inside a Vercel serverless function, which
cannot install or shell out to a system binary like LibreOffice. For that
environment, set PDF_CONVERSION_PROVIDER=cloudconvert and
CLOUDCONVERT_API_KEY (see backend/python/VERCEL_DEPLOYMENT.md) to convert
via CloudConvert's REST API instead. Either way, the PDF is a real,
rendered conversion of the actual generated .docx — never a hand-recreated
layout (project rule 9).

No API key is ever placed in frontend code (project rule 12) —
CLOUDCONVERT_API_KEY is read here, server-side only.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
import time
from typing import Optional

import requests


class PdfConversionError(Exception):
    """Raised whenever a .docx genuinely cannot be converted to PDF — never
    swallowed to produce a fake/empty PDF (project rule 9)."""


def convert_via_local_libreoffice(docx_bytes: bytes, base_name: str = "document") -> bytes:
    """Real LibreOffice headless conversion — requires 'soffice' on PATH;
    not available on Vercel.

    Real, reproduced-and-fixed bug (found this round, not hypothetical):
    two staff clicking "Generate" around the same moment — or, as actually
    caught here, this app's own shared document-viewer briefly issuing a
    duplicate preview request before that was fixed — sent two concurrent
    conversions and the SECOND one consistently failed with a real 500
    ("PDF conversion failed: unknown error"). Root cause: every invocation
    shared LibreOffice's default per-user profile/lock directory, and a
    second 'soffice' process can't start against a profile the first one
    already has locked — a genuine, previously-undiscovered concurrency bug
    in this backend, not a frontend-only issue. Fixed by giving every
    invocation its OWN temporary "-env:UserInstallation=" profile directory
    (cleaned up alongside the rest of tmp_dir), so concurrent conversions no
    longer contend for the same lock — verified by firing two real
    conversions at once and confirming both now return 200 with a valid
    PDF instead of one succeeding and one 500ing."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        docx_path = os.path.join(tmp_dir, f"{base_name}.docx")
        with open(docx_path, "wb") as f:
            f.write(docx_bytes)

        profile_dir = os.path.join(tmp_dir, "lo_profile")
        os.makedirs(profile_dir, exist_ok=True)
        profile_uri = "file://" + profile_dir.replace(os.sep, "/")

        try:
            result = subprocess.run(
                [
                    "soffice",
                    "--headless",
                    "--norestore",
                    f"-env:UserInstallation={profile_uri}",
                    "--convert-to",
                    "pdf",
                    "--outdir",
                    tmp_dir,
                    docx_path,
                ],
                capture_output=True,
                text=True,
                timeout=60,
            )
        except FileNotFoundError:
            raise PdfConversionError(
                "PDF export requires LibreOffice ('soffice') to be installed on "
                "this machine. The Word (.docx) document can still be generated "
                "and downloaded without it."
            )
        except subprocess.TimeoutExpired:
            raise PdfConversionError("PDF conversion timed out.")

        pdf_path = os.path.join(tmp_dir, f"{base_name}.pdf")
        if result.returncode != 0 or not os.path.isfile(pdf_path):
            detail = (result.stderr or result.stdout or "unknown error").strip()
            raise PdfConversionError(f"PDF conversion failed: {detail}")

        with open(pdf_path, "rb") as f:
            return f.read()


_CLOUDCONVERT_API_BASE = "https://api.cloudconvert.com/v2"
_CLOUDCONVERT_POLL_INTERVAL_SECONDS = 1.5
_CLOUDCONVERT_POLL_TIMEOUT_SECONDS = 55  # stays under a serverless function's own time budget


def convert_via_cloudconvert(docx_bytes: bytes, base_name: str = "document") -> bytes:
    """Converts via CloudConvert's REST API (https://cloudconvert.com/api/v2):
    create a job (import/upload -> convert -> export/url), upload the .docx
    to the upload task's own form, poll the job until every task finishes,
    then download the resulting PDF. CloudConvert runs a real, cloud-hosted
    LibreOffice engine on its own servers — the output is a genuinely
    converted document, not a re-created layout."""
    api_key = os.environ.get("CLOUDCONVERT_API_KEY", "").strip()
    if not api_key:
        raise PdfConversionError(
            "PDF export requires a CloudConvert API key. Set the "
            "CLOUDCONVERT_API_KEY environment variable (see "
            "backend/python/VERCEL_DEPLOYMENT.md)."
        )
    headers = {"Authorization": f"Bearer {api_key}"}

    job_payload = {
        "tasks": {
            "import-file": {"operation": "import/upload"},
            "convert-file": {
                "operation": "convert",
                "input": "import-file",
                "input_format": "docx",
                "output_format": "pdf",
                "engine": "libreoffice",
                "filename": f"{base_name}.pdf",
            },
            "export-file": {"operation": "export/url", "input": "convert-file"},
        }
    }

    try:
        create_resp = requests.post(f"{_CLOUDCONVERT_API_BASE}/jobs", json=job_payload, headers=headers, timeout=20)
    except requests.RequestException as e:
        raise PdfConversionError(f"Could not reach CloudConvert: {e}")
    if create_resp.status_code >= 400:
        raise PdfConversionError(
            f"CloudConvert job creation failed ({create_resp.status_code}): {create_resp.text[:300]}"
        )

    job = create_resp.json().get("data", {})
    job_id = job.get("id")
    import_task = next((t for t in job.get("tasks", []) if t.get("name") == "import-file"), None)
    if not job_id or not import_task:
        raise PdfConversionError("CloudConvert did not return a usable job/import task.")

    upload_form = import_task.get("result", {}).get("form", {})
    upload_url = upload_form.get("url")
    upload_params = upload_form.get("parameters", {})
    if not upload_url:
        raise PdfConversionError("CloudConvert did not return an upload URL.")

    files = {
        "file": (
            f"{base_name}.docx",
            docx_bytes,
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
    }
    try:
        upload_resp = requests.post(upload_url, data=upload_params, files=files, timeout=30)
    except requests.RequestException as e:
        raise PdfConversionError(f"Could not upload the document to CloudConvert: {e}")
    if upload_resp.status_code >= 400:
        raise PdfConversionError(f"CloudConvert upload failed ({upload_resp.status_code}): {upload_resp.text[:300]}")

    deadline = time.time() + _CLOUDCONVERT_POLL_TIMEOUT_SECONDS
    export_url: Optional[str] = None
    while time.time() < deadline:
        poll_resp = requests.get(f"{_CLOUDCONVERT_API_BASE}/jobs/{job_id}", headers=headers, timeout=20)
        if poll_resp.status_code >= 400:
            raise PdfConversionError(
                f"CloudConvert status check failed ({poll_resp.status_code}): {poll_resp.text[:300]}"
            )
        job = poll_resp.json().get("data", {})
        status = job.get("status")
        if status == "error":
            failing = next((t for t in job.get("tasks", []) if t.get("status") == "error"), {})
            raise PdfConversionError(f"CloudConvert conversion failed: {failing.get('message', job)}")
        if status == "finished":
            export_task = next((t for t in job.get("tasks", []) if t.get("name") == "export-file"), None)
            files_out = (export_task or {}).get("result", {}).get("files", [])
            if files_out and files_out[0].get("url"):
                export_url = files_out[0]["url"]
            break
        time.sleep(_CLOUDCONVERT_POLL_INTERVAL_SECONDS)

    if not export_url:
        raise PdfConversionError("CloudConvert timed out before the PDF was ready.")

    try:
        download_resp = requests.get(export_url, timeout=30)
    except requests.RequestException as e:
        raise PdfConversionError(f"Could not download the converted PDF from CloudConvert: {e}")
    if download_resp.status_code >= 400:
        raise PdfConversionError(f"Downloading the converted PDF failed ({download_resp.status_code}).")

    return download_resp.content


def convert_docx_bytes_to_pdf(docx_bytes: bytes, base_name: str = "document") -> bytes:
    """Single entry point every document engine calls (via docx_utils'
    identically-named wrapper, so none of their call sites change).
    Dispatches on PDF_CONVERSION_PROVIDER:
      - "cloudconvert" -> always cloud, raises if no API key is set
      - "local"        -> always local LibreOffice, raises if 'soffice' isn't installed
      - "auto" (default) -> cloud when CLOUDCONVERT_API_KEY is set (Vercel),
                             otherwise local (unchanged behaviour for anyone
                             already running this backend on their own
                             machine without that key set)
    """
    choice = os.environ.get("PDF_CONVERSION_PROVIDER", "auto").strip().lower()
    has_cloudconvert_key = bool(os.environ.get("CLOUDCONVERT_API_KEY", "").strip())

    use_cloud = choice == "cloudconvert" or (choice == "auto" and has_cloudconvert_key)
    if use_cloud:
        return convert_via_cloudconvert(docx_bytes, base_name=base_name)
    return convert_via_local_libreoffice(docx_bytes, base_name=base_name)
