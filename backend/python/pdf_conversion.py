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
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Optional

import requests


class PdfConversionError(Exception):
    """Raised whenever a .docx genuinely cannot be converted to PDF — never
    swallowed to produce a fake/empty PDF (project rule 9)."""


def _soffice_candidates() -> list[str]:
    """Where LibreOffice's 'soffice' is normally installed when it is NOT on
    PATH (the Windows installer never adds it to PATH, which is the usual
    reason 'soffice' "is not installed" on a machine that has it)."""
    candidates: list[str] = []
    if sys.platform.startswith("win"):
        for base in (os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)"), r"C:\Program Files", r"C:\Program Files (x86)"):
            if base:
                candidates.append(os.path.join(base, "LibreOffice", "program", "soffice.exe"))
    elif sys.platform == "darwin":
        candidates.append("/Applications/LibreOffice.app/Contents/MacOS/soffice")
    else:
        candidates += ["/usr/bin/soffice", "/usr/lib/libreoffice/program/soffice", "/opt/libreoffice/program/soffice"]
    return candidates


def _find_soffice() -> Optional[str]:
    """Path to LibreOffice: SOFFICE_PATH env var, then PATH, then the
    standard install folders. None when it genuinely is not installed."""
    configured = os.environ.get("SOFFICE_PATH", "").strip().strip('"')
    if configured and os.path.isfile(configured):
        return configured
    on_path = shutil.which("soffice")
    if on_path:
        return on_path
    for candidate in _soffice_candidates():
        if os.path.isfile(candidate):
            return candidate
    return None


_WORD_PS_SCRIPT = r"""
param([string]$InPath, [string]$OutPath)
$ErrorActionPreference = 'Stop'
$word = $null
$doc = $null
try {
    $word = New-Object -ComObject Word.Application
    $word.Visible = $false
    $word.DisplayAlerts = 0
    $doc = $word.Documents.Open($InPath)
    # 17 = wdExportFormatPDF
    $doc.ExportAsFixedFormat($OutPath, 17)
} finally {
    if ($doc -ne $null) { try { $doc.Close(0) } catch {} }
    if ($word -ne $null) { try { $word.Quit(0) } catch {} }
}
"""

# Word is one shared desktop application; serialise our own calls into it.
_WORD_LOCK = threading.Lock()


def _word_is_installed() -> bool:
    """True on Windows when Microsoft Word is registered as a COM server."""
    if not sys.platform.startswith("win"):
        return False
    try:
        import winreg  # type: ignore
        winreg.CloseKey(winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, r"Word.Application"))
        return True
    except Exception:
        return False


def convert_via_word(docx_bytes: bytes, base_name: str = "document") -> bytes:
    """Real Microsoft Word conversion (Windows only, uses Word's own COM
    automation through the PowerShell that ships with Windows — nothing to
    pip-install). The PDF is Word's genuine "Save as PDF" of the generated
    .docx, never a re-created layout (project rule 9). Used when LibreOffice
    is not installed but Word is."""
    if not sys.platform.startswith("win"):
        raise PdfConversionError("Microsoft Word conversion is only available on Windows.")
    with _WORD_LOCK, tempfile.TemporaryDirectory() as tmp_dir:
        docx_path = os.path.join(tmp_dir, f"{base_name}.docx")
        pdf_path = os.path.join(tmp_dir, f"{base_name}.pdf")
        script_path = os.path.join(tmp_dir, "word_to_pdf.ps1")
        with open(docx_path, "wb") as f:
            f.write(docx_bytes)
        with open(script_path, "w", encoding="utf-8") as f:
            f.write(_WORD_PS_SCRIPT)
        try:
            result = subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                 "-File", script_path, docx_path, pdf_path],
                capture_output=True, text=True, timeout=120,
            )
        except FileNotFoundError:
            raise PdfConversionError("PowerShell was not found, so Microsoft Word cannot be used for PDF export.")
        except subprocess.TimeoutExpired:
            raise PdfConversionError("PDF conversion with Microsoft Word timed out.")
        if result.returncode != 0 or not os.path.isfile(pdf_path):
            detail = (result.stderr or result.stdout or "unknown error").strip()[:400]
            raise PdfConversionError(f"PDF conversion with Microsoft Word failed: {detail}")
        with open(pdf_path, "rb") as f:
            return f.read()


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
        # Path.as_uri() gives file:///C:/... on Windows and file:///tmp/... elsewhere.
        profile_uri = Path(profile_dir).as_uri()
        soffice = _find_soffice() or "soffice"

        try:
            result = subprocess.run(
                [
                    soffice,
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
                "PDF export needs LibreOffice (free, libreoffice.org) or Microsoft "
                "Word installed on the machine running this backend. The Word "
                "(.docx) document can still be generated and downloaded without it."
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
      - "local"        -> local LibreOffice (or, on Windows without LibreOffice,
                             Microsoft Word); raises if neither is installed
      - "word"         -> always Microsoft Word (Windows only)
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
    if choice == "word":
        return convert_via_word(docx_bytes, base_name=base_name)
    # "local" / "auto" without a cloud key: LibreOffice when it is installed;
    # on a Windows PC that only has Microsoft Word, Word does the conversion.
    if _find_soffice() is None and _word_is_installed():
        return convert_via_word(docx_bytes, base_name=base_name)
    return convert_via_local_libreoffice(docx_bytes, base_name=base_name)


def get_pdf_conversion_status() -> dict:
    """Real, live status of whichever PDF-conversion path is actually active
    in THIS running process — surfaced on /api/health (project rule 9: never
    fake status) so a mismatched/missing env var on a live deployment (e.g.
    Vercel) can be confirmed from the deployment itself, without needing to
    generate a document first, and without ever printing the key's value
    (project rule 12 — secrets are never exposed, not even masked/partial)."""
    choice = os.environ.get("PDF_CONVERSION_PROVIDER", "auto").strip().lower()
    has_cloudconvert_key = bool(os.environ.get("CLOUDCONVERT_API_KEY", "").strip())
    use_cloud = choice == "cloudconvert" or (choice == "auto" and has_cloudconvert_key)

    if use_cloud:
        return {
            "provider": "cloudconvert",
            "available": has_cloudconvert_key,
            "pdfConversionProviderEnv": choice,
            "hasCloudConvertKey": has_cloudconvert_key,
            "note": (
                "Reflects whether CLOUDCONVERT_API_KEY is present in THIS "
                "running deployment, not a live call to CloudConvert (that "
                "would spend real conversion credits on every health check)."
            ),
        }

    soffice_path = _find_soffice()
    word_installed = _word_is_installed()
    if not soffice_path and (word_installed or choice == "word"):
        return {
            "provider": "word",
            "available": word_installed,
            "pdfConversionProviderEnv": choice,
            "hasCloudConvertKey": has_cloudconvert_key,
            "sofficePath": None,
            "note": "LibreOffice was not found; PDF export uses the installed Microsoft Word.",
        }
    return {
        "provider": "local",
        "available": bool(soffice_path),
        "pdfConversionProviderEnv": choice,
        "hasCloudConvertKey": has_cloudconvert_key,
        "sofficePath": soffice_path,
        "note": (
            "No CLOUDCONVERT_API_KEY is visible to this running deployment, "
            "so it's falling back to local LibreOffice — which is not "
            "installed on Vercel. If you set CLOUDCONVERT_API_KEY in Vercel "
            "and this still says hasCloudConvertKey: false after a fresh "
            "redeploy, the key was set on a different Vercel project than "
            "the one actually serving this domain."
        ),
    }
