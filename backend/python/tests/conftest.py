"""
Shared pytest fixtures for the Khanna Travels & Holidays backend test suite.

Design notes
------------
- Every engine module here reads its real reference `.docx`/`.xlsx` source
  straight from the project's read-only reference directories (project rule
  3 — reference files are read-only; project rule 5 — the reference
  template is always the source of truth). These tests never fabricate a
  fake/blank template to test against: doing so would test a document this
  application can never actually produce for a real client, and would let
  a real template-structure regression slip through unnoticed.
- Because of that, a handful of tests are conditioned on the actual
  reference file being present on disk (`skip_if_missing_template`). On a
  correctly set-up Khanna Travels machine those files always exist; this
  guard exists only so `pytest` still runs cleanly (with an honest,
  informative skip reason, not a confusing collection error) on a fresh
  checkout that has not yet had `reference-templates/`,
  `reference-cover-letter-formats/` and `reference-hotel-blocking-formats/`
  populated.
- No real client passport data is ever used as sample data anywhere in this
  suite (project rule 11) — every name, passport number, phone and email
  below is obviously synthetic.
"""

from __future__ import annotations

import copy
import os
import sys

import pytest

# Make every backend module importable as `import app`, `import data_model`,
# etc. regardless of the directory pytest was invoked from.
BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

PROJECT_ROOT = os.path.normpath(os.path.join(BACKEND_DIR, "..", ".."))


def skip_if_missing(*paths: str):
    """Skips the current test (with a clear reason) if any given reference
    file is not present on this machine, instead of failing the whole
    collection or silently testing nothing."""
    for path in paths:
        if not os.path.isfile(path):
            pytest.skip(
                f"Reference template not present at {path!r} — this suite only "
                "generates documents from the project's real reference templates "
                "(project rule 5) and skips a test rather than fabricate one. "
                "Populate reference-templates/ / reference-cover-letter-formats/ / "
                "reference-hotel-blocking-formats/ to run this test."
            )


def skip_if_missing_binary(name: str):
    import shutil

    if name == "tesseract":
        # Use the same discovery the Tesseract OCR provider itself uses
        # (checks the Windows installer's default folders too, not just
        # PATH) so this guard can't give a false "not installed" skip on a
        # machine where it plainly is — see ocr_providers.find_tesseract_cmd.
        import ocr_providers

        if ocr_providers.find_tesseract_cmd() is None:
            pytest.skip("'tesseract' is not installed on this machine — skipping.")
        return

    if shutil.which(name) is None:
        pytest.skip(f"'{name}' is not installed on this machine — skipping.")


# ---------------------------------------------------------------------------
# Synthetic sample data (never real client data — project rule 11)
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_applicant():
    return {
        "id": "trav_applicant",
        "salutation": "Mr",
        "fullName": "Rohan Test Mehta",
        "firstName": "Rohan",
        "lastName": "Mehta",
        "passportNumber": "T1234567",
        "placeOfIssue": "Mumbai",
        "passportIssueDate": "2019-05-01",
        "relationToApplicant": "",
        "sex": "M",
        "phone": "9876500001",
        "email": "rohan.test@example.com",
        "occupation": "Software Engineer",
        "isApplicant": True,
    }


@pytest.fixture
def sample_companion():
    return {
        "id": "trav_companion",
        "salutation": "Mrs",
        "fullName": "Priya Test Mehta",
        "firstName": "Priya",
        "lastName": "Mehta",
        "passportNumber": "T7654321",
        "placeOfIssue": "Pune",
        "passportIssueDate": "2020-02-10",
        "relationToApplicant": "Spouse",
        "sex": "F",
        "phone": "9876500002",
        "email": "priya.test@example.com",
        "occupation": "Designer",
        "isApplicant": False,
    }


@pytest.fixture
def sample_hotel():
    return {
        "hotelName": "Test Grand Hotel",
        "phone": "+41 22 000 0000",
        "address": "1 Test Street, Test City",
        "city": "Geneva",
        "confirmationNumber": "CONF-TEST-1",
        "leadGuestName": "Rohan Test Mehta",
        "noOfGuests": "2",
        "noOfRooms": "1",
        "roomType": "Deluxe",
        "checkIn": "2026-12-01",
        "checkOut": "2026-12-05",
        "guestNames": ["Rohan Test Mehta", "Priya Test Mehta"],
    }


@pytest.fixture
def sample_hotels(sample_hotel):
    second = copy.deepcopy(sample_hotel)
    second["hotelName"] = "Test Alpine Hotel"
    second["city"] = "Zurich"
    second["confirmationNumber"] = "CONF-TEST-2"
    second["checkIn"] = "2026-12-05"
    second["checkOut"] = "2026-12-10"
    return [sample_hotel, second]
