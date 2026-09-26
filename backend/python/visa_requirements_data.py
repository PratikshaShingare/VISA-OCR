"""
Khanna Travels & Holidays — Visa requirements reference data
==============================================================

Backs the Required Document Letter module. Two deliberately separate
concerns live here:

1. COUNTRIES / VISA_TYPES — safe, static reference data (a country list and
   the exact three visa categories this letter supports, per the user's own
   explicit scope decision: Transit, Tourist, Business only).

2. KNOWN_FACTS — a lookup of REAL, SOURCED figures (bank-statement
   duration, ITR years, processing time, visa fee) for a small number of
   country+visaType combinations. Project rule 9 ("do not fake
   functionality") and the user's own explicit instruction ("never invent
   unspecified numbers... mark 'Check current official requirement'
   instead") both apply directly here: every entry in KNOWN_FACTS must be
   traceable to a real, named, dated source. This session could reach only
   two genuinely verifiable data points before real-time web search was
   blocked by this account's own org policy (WebSearch returned
   PROXY_REJECTED/403; most consulate/VFS pages are JS-rendered SPAs that a
   text fetch cannot read) — both are recorded below with their source and
   the date this session actually verified them. Every other country/visa
   combination is deliberately ABSENT from this dict (not filled with a
   guess), so lookup() correctly returns None for it and the frontend/PDF
   shows the honest "Check current official requirement" placeholder
   instead of a fabricated number.

   Extending this table later (a future session with working search, or a
   staff member typing in a verified figure) should always add a fully
   sourced entry here — never a bare number with no source/lastVerified.
"""

from __future__ import annotations

from typing import Optional, TypedDict

# Expanded per the 31-section rebuild spec (previously just Transit/
# Tourist/Business). Order here is the order shown in the frontend's own
# <select>, not alphabetical — most-requested categories first.
VISA_TYPES = [
    "Transit",
    "Visitor",
    "Tourist",
    "Business",
    "Student",
    "Employment",
    "Medical",
    "E-Visa",
    "Official",
    "Dependent",
    "Immigrant",
]

EMPLOYMENT_STATUSES = [
    "Employed",
    "Self-Employed",
    "Business Owner",
    "Student",
    "Retired",
    "Homemaker",
    "Minor",
    "Other",
]

BANK_STATEMENT_DURATION_OPTIONS = ["3 Months", "6 Months", "12 Months", "Custom"]
ITR_YEAR_OPTIONS = ["1 Year", "2 Years", "3 Years", "5 Years", "Custom"]

# Standard travel-agency processing-time buckets — a staff pick-list for
# convenience only, never a claim about any specific country/visa-type's
# actual processing time (that number, when genuinely known, still comes
# from KNOWN_FACTS below with a real source; when not, the frontend keeps
# showing "Check current official requirement" regardless of what's picked
# here). "Custom" lets staff type the consulate's own quoted wording
# verbatim (e.g. "6-8 Working Days").
PROCESSING_TIME_OPTIONS = [
    "3-5 Working Days",
    "1-2 Weeks",
    "2-3 Weeks",
    "3-4 Weeks",
    "4-6 Weeks",
    "6-8 Weeks",
    "Custom",
]

# A standard, apolitical list of country names for the searchable dropdown.
# This is plain reference data (not a visa-requirement claim), safe to
# ship as-is.
COUNTRIES = [
    "Afghanistan", "Albania", "Algeria", "Andorra", "Angola", "Antigua and Barbuda",
    "Argentina", "Armenia", "Australia", "Austria", "Azerbaijan", "Bahamas", "Bahrain",
    "Bangladesh", "Barbados", "Belarus", "Belgium", "Belize", "Benin", "Bhutan",
    "Bolivia", "Bosnia and Herzegovina", "Botswana", "Brazil", "Brunei", "Bulgaria",
    "Burkina Faso", "Burundi", "Cambodia", "Cameroon", "Canada", "Cape Verde",
    "Central African Republic", "Chad", "Chile", "China", "Colombia", "Comoros",
    "Congo (Republic of the)", "Congo (DR)", "Costa Rica", "Croatia", "Cuba", "Cyprus",
    "Czech Republic", "Denmark", "Djibouti", "Dominica", "Dominican Republic", "Ecuador",
    "Egypt", "El Salvador", "Equatorial Guinea", "Eritrea", "Estonia", "Eswatini",
    "Ethiopia", "Fiji", "Finland", "France", "Gabon", "Gambia", "Georgia", "Germany",
    "Ghana", "Greece", "Grenada", "Guatemala", "Guinea", "Guinea-Bissau", "Guyana",
    "Haiti", "Honduras", "Hungary", "Iceland", "Indonesia", "Iran", "Iraq", "Ireland",
    "Israel", "Italy", "Ivory Coast", "Jamaica", "Japan", "Jordan", "Kazakhstan",
    "Kenya", "Kiribati", "Kuwait", "Kyrgyzstan", "Laos", "Latvia", "Lebanon", "Lesotho",
    "Liberia", "Libya", "Liechtenstein", "Lithuania", "Luxembourg", "Madagascar",
    "Malawi", "Malaysia", "Maldives", "Mali", "Malta", "Marshall Islands", "Mauritania",
    "Mauritius", "Mexico", "Micronesia", "Moldova", "Monaco", "Mongolia", "Montenegro",
    "Morocco", "Mozambique", "Myanmar", "Namibia", "Nauru", "Nepal", "Netherlands",
    "New Zealand", "Nicaragua", "Niger", "Nigeria", "North Korea", "North Macedonia",
    "Norway", "Oman", "Pakistan", "Palau", "Panama", "Papua New Guinea", "Paraguay",
    "Peru", "Philippines", "Poland", "Portugal", "Qatar", "Romania", "Russia", "Rwanda",
    "Saint Kitts and Nevis", "Saint Lucia", "Saint Vincent and the Grenadines", "Samoa",
    "San Marino", "Sao Tome and Principe", "Saudi Arabia", "Senegal", "Serbia",
    "Seychelles", "Sierra Leone", "Singapore", "Slovakia", "Slovenia", "Solomon Islands",
    "Somalia", "South Africa", "South Korea", "South Sudan", "Spain", "Sri Lanka",
    "Sudan", "Suriname", "Sweden", "Switzerland", "Syria", "Taiwan", "Tajikistan",
    "Tanzania", "Thailand", "Timor-Leste", "Togo", "Tonga", "Trinidad and Tobago",
    "Tunisia", "Turkey", "Turkmenistan", "Tuvalu", "Uganda", "Ukraine",
    "United Arab Emirates", "United Kingdom", "United States", "Uruguay", "Uzbekistan",
    "Vanuatu", "Vatican City", "Venezuela", "Vietnam", "Yemen", "Zambia", "Zimbabwe",
    # Schengen-area member states are listed individually above (France,
    # Germany, Italy, Spain, ...); "Schengen (Multiple Countries)" is added
    # as a distinct, explicit option since a single Schengen visa is a real,
    # commonly-requested category in its own right for this agency.
    "Schengen (Multiple Countries)",
]
COUNTRIES = sorted(set(COUNTRIES))


class KnownFact(TypedDict, total=False):
    bankStatementDuration: Optional[str]
    itrYears: Optional[str]
    processingTime: Optional[str]
    visaFees: Optional[str]
    source: str
    sourceUrl: str
    verifiedOn: str
    note: str


# Keyed by (country, visaType). Every field a specific entry does not set is
# left absent — lookup() below returns None for a missing field rather than
# 0/"" so the caller can distinguish "genuinely unknown" from "verified as
# zero/none".
KNOWN_FACTS: dict[tuple[str, str], KnownFact] = {
    ("United Kingdom", "Tourist"): {
        "visaFees": "GBP 135 (approx.) for a Standard Visitor visa valid up to 6 months",
        "source": "GOV.UK — Standard Visitor visa",
        "sourceUrl": "https://www.gov.uk/standard-visitor-visa",
        "verifiedOn": "2026-09-26",
        "note": (
            "Only the headline visa fee was confirmed on the official page fetched this "
            "session; it does not itself state bank-statement duration, ITR years, or "
            "processing time, and UK visa fees change periodically — reconfirm on gov.uk "
            "before quoting to a client."
        ),
    },
    ("Japan", "Tourist"): {
        "visaFees": "INR 500 (visa fee only, effective 1 Jul 2026) plus separate VFS Global service charges",
        "source": "Embassy of Japan in India — Visa page",
        "sourceUrl": "https://www.in.emb-japan.go.jp/itpr_en/visa.html",
        "verifiedOn": "2026-09-26",
        "note": (
            "The embassy page states processing times 'can vary significantly' and gives no "
            "fixed duration — bank-statement/ITR duration and a concrete processing time were "
            "not published on this page and are left unset here rather than guessed."
        ),
    },
}


def lookup(country: str, visa_type: str) -> KnownFact:
    """Returns whatever is genuinely known for this exact (country, visaType)
    pair, or an empty dict if nothing has been verified — never a guess."""
    return dict(KNOWN_FACTS.get((country, visa_type), {}))


"""
Required Document Letter — document rule engine
==============================================================
Replaces the old hardcoded engine (which only ever supported exactly 4
conditional bullets — Employed / Self-Employed / Invited / has-a-US-visa —
baked directly into required_document_letter_engine.py's own Python
if-statements). Per the user's own explicit instruction, this must be "a
maintainable, structured, data-driven configuration... NOT hundreds of
scattered if/else statements", and must "support future additions".

DOCUMENT_CATALOG is the single source of truth for every document this
letter can ever list. Each entry is a real, generic travel-visa-agency
document category (never a fabricated country-specific number — those stay
gated behind KNOWN_FACTS above, with a real source). A document is either:
  - always required (shown checked by default, every enquiry), or
  - conditionally SUGGESTED (pre-checked) when the enquiry's visa type,
    employment status, or a free-form "circumstance" flag matches — but
    every document, suggested or not, is always shown as an editable
    checkbox: staff can add or remove any of them for the specific client
    in front of them, matching the user's own "checkbox-based, only
    selected documents appear" instruction.

COUNTRY_VISA_DOCUMENT_OVERRIDES is the "Country -> Visa Type -> Documents"
hook the user asked for, kept structurally ready but genuinely EMPTY: no
country-specific document REQUIREMENT (as opposed to a generic category)
has been verified against an official source this session (WebSearch was
blocked — see this module's own top-of-file docstring), so it is left
empty rather than guessed, exactly like KNOWN_FACTS above. A future session
with working search (or a staff member's own verified input) extends this
dict with entries shaped like:
    ("Germany", "Student"): {"require": ["admission_letter", ...], "source": "...", "verifiedOn": "..."}
never a bare list with no source.
"""

DOCUMENT_CATALOG: dict[str, dict] = {
    # --- Always required, every enquiry (matches the template's own
    # original fixed bullets 14/15/18 verbatim) ---
    "passport_copy": {"label": "Passport Copy (First and Last Page)", "always": True},
    "aadhar_card": {"label": "Aadhar Card", "always": True},
    "investment_papers": {
        "label": "Investment Papers (Mutual Funds, FDs, Property Papers - if any)",
        "always": True,
    },
    "photographs": {
        "label": "Recent Passport-size Photographs (as per visa specifications)",
        "always": True,
    },
    # --- Financial documents whose wording carries a dynamic value
    # (bank-statement duration / ITR years) — resolved at generation time by
    # resolve_document_label() below, never hardcoded to one figure. ---
    "bank_statement": {
        "label_template": "Personal Bank Statement of Last {duration} (with sufficient balance)",
        "always": True,
    },
    "itr": {
        "label_template": "Personal Income Tax Returns of Last {years} (Acknowledgment Page Only)",
        "always": True,
    },
    # --- Employment-status-conditional (template's original bullets 19/20,
    # generalised to the newly expanded status list) ---
    "salary_slips": {
        "label": "Salary Slips of Last 6 Months & Employee ID Card",
        "employmentStatuses": ["Employed"],
    },
    "noc_employer": {
        "label": "No-Objection Certificate (NOC) from Employer",
        "employmentStatuses": ["Employed"],
        "visaTypes": ["Business", "Employment", "Official"],
    },
    "company_registration_docs": {
        "label": "Company Registration Certificate, Company Bank Statements & ITR",
        "employmentStatuses": ["Self-Employed", "Business Owner"],
    },
    "business_registration": {
        "label": "Business Registration Certificate / Trade License",
        "employmentStatuses": ["Business Owner"],
    },
    "retirement_proof": {
        "label": "Pension Statement / Retirement Proof",
        "employmentStatuses": ["Retired"],
    },
    "sponsor_income_proof": {
        "label": "Spouse's / Sponsor's Income Proof & Bank Statements",
        "employmentStatuses": ["Homemaker", "Minor", "Student"],
    },
    "guardian_documents": {
        "label": "Guardian's ID Proof, Passport Copy & Notarized Consent Letter",
        "employmentStatuses": ["Minor"],
    },
    # --- Visa-type-conditional (new categories for the expanded visa-type list) ---
    "invitation_docs": {
        "label": "Invitation Letter, Passport Copy, Visa Copy & Address Proof of Invitee",
        "circumstances": ["invited"],
    },
    "us_visa_copy": {
        "label": "Valid USA Visa Copy (if any)",
        "circumstances": ["hasUsVisaCopy"],
    },
    "cover_letter": {
        "label": "Cover Letter / Purpose-of-Visit Letter",
        "visaTypes": ["Business", "Student", "Employment", "Medical", "Official", "Immigrant"],
    },
    "flight_itinerary": {
        "label": "Confirmed Return Flight Ticket / Itinerary",
        "visaTypes": ["Visitor", "Tourist", "Business", "Medical", "E-Visa"],
    },
    "hotel_booking": {
        "label": "Hotel Booking Confirmation / Accommodation Proof",
        "visaTypes": ["Visitor", "Tourist", "E-Visa"],
    },
    "admission_letter": {
        "label": "Admission / Offer Letter from Educational Institution",
        "visaTypes": ["Student"],
    },
    "education_certificates": {
        "label": "Educational Certificates & Mark Sheets",
        "visaTypes": ["Student"],
    },
    "employment_contract": {
        "label": "Employment Contract / Job Offer Letter",
        "visaTypes": ["Employment"],
    },
    "police_clearance": {
        "label": "Police Clearance Certificate (PCC)",
        "visaTypes": ["Employment", "Immigrant"],
    },
    "medical_certificate": {
        "label": "Medical Certificate / Fitness Report from Registered Physician",
        "visaTypes": ["Medical"],
    },
    "hospital_letter": {
        "label": "Hospital Appointment Letter / Treatment Cost Estimate",
        "visaTypes": ["Medical"],
    },
    "government_deputation_letter": {
        "label": "Government Deputation / Duty Letter",
        "visaTypes": ["Official"],
    },
    "diplomatic_note": {
        "label": "Diplomatic Note / Note Verbale from the Ministry",
        "visaTypes": ["Official"],
    },
    "onward_ticket": {
        "label": "Onward / Connecting Flight Ticket",
        "visaTypes": ["Transit"],
    },
    "destination_visa": {
        "label": "Valid Visa / Entry Permit of the Final Destination Country",
        "visaTypes": ["Transit"],
    },
    "marriage_certificate": {
        "label": "Marriage Certificate",
        "visaTypes": ["Dependent"],
    },
    "relationship_proof": {
        "label": "Proof of Relationship with Sponsor (Birth / Marriage Certificate)",
        "visaTypes": ["Dependent", "Immigrant"],
    },
    "sponsor_documents": {
        "label": "Sponsor's ID Proof, Passport Copy & Financial Documents",
        "visaTypes": ["Dependent", "Immigrant"],
    },
}

# Canonical display/insertion order — a plain list, not dict key order, so
# re-ordering the dict above for readability never silently changes the
# generated letter's own document order.
DOCUMENT_ORDER = [
    "passport_copy",
    "aadhar_card",
    "photographs",
    "bank_statement",
    "itr",
    "investment_papers",
    "salary_slips",
    "noc_employer",
    "company_registration_docs",
    "business_registration",
    "retirement_proof",
    "sponsor_income_proof",
    "guardian_documents",
    "cover_letter",
    "flight_itinerary",
    "hotel_booking",
    "admission_letter",
    "education_certificates",
    "employment_contract",
    "police_clearance",
    "medical_certificate",
    "hospital_letter",
    "government_deputation_letter",
    "diplomatic_note",
    "onward_ticket",
    "destination_visa",
    "marriage_certificate",
    "relationship_proof",
    "sponsor_documents",
    "invitation_docs",
    "us_visa_copy",
]
assert set(DOCUMENT_ORDER) == set(DOCUMENT_CATALOG), (
    "DOCUMENT_ORDER and DOCUMENT_CATALOG have drifted apart — every catalog "
    "id must appear in the order list exactly once."
)

# Structurally ready, deliberately empty — see the module docstring above
# this section for why no entry is filled in yet.
COUNTRY_VISA_DOCUMENT_OVERRIDES: dict[tuple[str, str], dict] = {}


def get_document_catalog() -> list[dict]:
    """Every document this letter can ever list, in canonical order, with a
    human-readable preview label (dynamic {duration}/{years} placeholders
    shown as their own literal token here — resolve_document_label() below
    substitutes the real value at generation time)."""
    out = []
    for doc_id in DOCUMENT_ORDER:
        entry = DOCUMENT_CATALOG[doc_id]
        preview = entry.get("label") or entry.get("label_template", "")
        out.append({"id": doc_id, "label": preview})
    return out


def resolve_suggested_document_ids(
    visa_type: str,
    employment_status: str,
    circumstances: Optional[list] = None,
    country: Optional[str] = None,
) -> list[str]:
    """Returns the document ids that should be pre-checked for this
    enquiry — every "always" document, plus any whose visaTypes/
    employmentStatuses/circumstances condition matches, plus any
    country+visaType-specific override on file. Every id returned is still
    just a SUGGESTION: the frontend renders it as a pre-checked checkbox a
    staff member can uncheck, and only documents actually left checked at
    generation time appear in the letter (never silently enforced)."""
    circumstances = set(circumstances or [])
    suggested = []
    for doc_id in DOCUMENT_ORDER:
        entry = DOCUMENT_CATALOG[doc_id]
        if entry.get("always"):
            suggested.append(doc_id)
            continue
        if visa_type and visa_type in (entry.get("visaTypes") or []):
            suggested.append(doc_id)
            continue
        if employment_status and employment_status in (entry.get("employmentStatuses") or []):
            suggested.append(doc_id)
            continue
        if circumstances & set(entry.get("circumstances") or []):
            suggested.append(doc_id)
            continue

    override = COUNTRY_VISA_DOCUMENT_OVERRIDES.get((country, visa_type)) if country else None
    if override:
        for doc_id in override.get("require", []):
            if doc_id in DOCUMENT_CATALOG and doc_id not in suggested:
                suggested.append(doc_id)

    # Stable canonical order regardless of which branch added each id.
    return [d for d in DOCUMENT_ORDER if d in suggested]


def resolve_document_label(doc_id: str, bank_statement_duration: str = "", itr_years: str = "") -> str:
    """Resolves one catalog id to its final display text for the letter,
    substituting the dynamic bank-statement-duration / ITR-years value into
    the two templated entries. Raises KeyError for an unknown id (never
    silently drops or mis-labels a document — project rule 9)."""
    entry = DOCUMENT_CATALOG[doc_id]
    if "label_template" in entry:
        duration = (bank_statement_duration or "").strip() or "[DURATION]"
        years = (itr_years or "").strip() or "__"
        return entry["label_template"].format(duration=duration, years=years)
    return entry["label"]
