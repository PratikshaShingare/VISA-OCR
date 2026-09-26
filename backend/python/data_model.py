"""
Khanna Travels & Holidays — Application data model.

This is the Python-side twin of /js/core/state.js. Field names and nesting
match exactly (camelCase, same keys, same defaults) so that once a real
backend exists, the JSON an endpoint receives from the frontend and the JSON
it returns need no field-name translation.

Kept as plain dict-building factories (not dataclasses) on purpose: the
model is just JSON going over the wire and into storage, and a dict factory
can't drift from its JS counterpart the way a dataclass-to-camelCase mapping
layer could. Each factory below has a one-to-one match in state.js — when
one changes, change the other.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List

# Canonical application status list (Master Prompt, Phase 26).
STATUSES: List[str] = [
    "Draft",
    "New",
    "Documents Pending",
    "Documents Received",
    "Under Review",
    "Ready for Submission",
    "Submitted",
    "Processing",
    "Approved",
    "Rejected",
    "Cancelled",
]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def generate_id(prefix: str = "id") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def empty_passport() -> Dict[str, Any]:
    return {
        "current": {
            "number": "",
            "issueDate": "",
            "expiryDate": "",
            "issuePlace": "",
            "issuingAuthority": "",
            "type": "",
            "countryCode": "",
            "mrzLine1": "",
            "mrzLine2": "",
            "mrzValid": None,  # None = not checked, True/False once MRZ processed
        },
        "old": None,  # same shape as "current", or None if not applicable
        "imageRef": None,
        "rotation": 0,
        "verificationStatus": "Not Started",  # Not Started | OCR Extracted — Please Verify | Verified
    }


def empty_person() -> Dict[str, Any]:
    return {
        "salutation": "",
        "firstName": "",
        "middleName": "",
        "lastName": "",
        "fullName": "",
        "dob": "",
        "sex": "",
        "nationality": "",
        "placeOfBirth": "",
        "passport": empty_passport(),
        "address": {"line1": "", "line2": "", "city": "", "state": "", "pincode": "", "country": ""},
        "contact": {"phone": "", "email": ""},
    }


def create_empty_application(created_by: str = "") -> Dict[str, Any]:
    ts = _now_iso()
    return {
        "id": generate_id("APP"),
        "status": "Draft",
        "createdBy": created_by,
        "createdAt": ts,
        "updatedAt": ts,
        "applicant": empty_person(),
        "travellers": [],  # each item: empty_person() + {"id": ..., "relation": ...}
        "travel": {
            "destination": "",
            "visaCategory": "",
            "purpose": "",
            "countryOfResidence": "",
            "startDate": "",
            "endDate": "",
        },
        "checklist": {"destination": "", "requiredDocs": [], "supportingDocs": [], "completionPct": 0},
        "documents": [],
        "hotels": [],
        "coverLetter": {"templateRegion": "", "fields": {}, "generatedDocRef": None},
        "authorization": {
            "passport": {"mode": "single", "fields": {}},
            "company": {"fields": {}},
        },
        "invitation": {"fields": {}, "signatureImageRef": None},
        "initorsLetters": {"fields": {}},
        "notes": [],
        "activity": [{"ts": ts, "type": "created", "message": "Application created"}],
    }


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

REQUIRED_TOP_LEVEL_KEYS = [
    "id",
    "status",
    "createdAt",
    "updatedAt",
    "applicant",
    "travellers",
    "travel",
    "checklist",
    "documents",
    "hotels",
    "coverLetter",
    "authorization",
    "invitation",
    "initorsLetters",
    "notes",
    "activity",
]


def validate_application(app: Dict[str, Any]) -> List[str]:
    """Returns a list of problems (empty list = valid). Intentionally shallow
    — a structural sanity check for API boundaries, not a full schema
    validator. Extend as real endpoints start accepting partial updates."""
    errors: List[str] = []
    if not isinstance(app, dict):
        return ["Application payload must be a JSON object."]

    for key in REQUIRED_TOP_LEVEL_KEYS:
        if key not in app:
            errors.append(f"Missing required field: {key}")

    status = app.get("status")
    if status is not None and status not in STATUSES:
        errors.append(f"Unknown status '{status}'. Must be one of: {', '.join(STATUSES)}")

    if "travellers" in app and not isinstance(app["travellers"], list):
        errors.append("'travellers' must be a list.")
    if "documents" in app and not isinstance(app["documents"], list):
        errors.append("'documents' must be a list.")

    return errors


def to_json(app: Dict[str, Any]) -> str:
    return json.dumps(app, ensure_ascii=False, indent=2)


def from_json(raw: str) -> Dict[str, Any]:
    return json.loads(raw)


if __name__ == "__main__":
    # Quick self-test: create → serialize → parse back → validate.
    app = create_empty_application(created_by="customercare@khannatravels.com")
    raw = to_json(app)
    round_tripped = from_json(raw)

    assert round_tripped == app, "Round-trip through JSON changed the data."
    problems = validate_application(round_tripped)
    assert not problems, f"New application should be valid, got: {problems}"

    broken = {"id": "x"}
    broken_problems = validate_application(broken)
    assert broken_problems, "Validator should flag an incomplete application."

    print("data_model.py self-test passed.")
    print(f"Sample application id: {app['id']}, status: {app['status']}")
    print(f"Required-field check on incomplete payload found {len(broken_problems)} issue(s), as expected.")
