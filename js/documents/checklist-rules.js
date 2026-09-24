/* ==========================================================================
   Khanna Travels & Holidays — Visa document checklist rules
   Pure config: which documents are typically required/supporting for a
   given destination + visa category. This is a STANDARD STARTING-POINT
   checklist, not sourced from any consulate's official published
   requirements — every checklist screen says so and lets staff add or
   remove items, because real embassy requirements vary by case and change
   over time (project rule 9: don't present this as more authoritative than
   it is).

   The three destinations with a real, populated checklist below (Europe,
   Japan, Singapore) are exactly the three the agency's own cover-letter
   reference templates already cover (see Phase 0 inspection notes) — the
   required-document lists were built from what those templates themselves
   reference (passport, visa form, financial proof, hotel/flight bookings,
   travel insurance, employment proof) plus standard, widely-published
   tourist-visa document requirements for each. Any other destination, or
   any non-Tourist category, falls back to GENERIC_CHECKLIST rather than
   inventing region-specific detail this project has no grounding for.
   ========================================================================== */
(function (global) {
  "use strict";

  var DESTINATIONS = ["Europe (Schengen)", "Japan", "Singapore", "Other"];
  var VISA_CATEGORIES = ["Tourist", "Business", "Student", "Work", "Other"];

  var GENERIC_CHECKLIST = {
    required: [
      "Valid passport (original + photocopy of first & last page)",
      "Passport-size photographs",
      "Visa application form (signed)",
      "Confirmed flight itinerary",
      "Hotel / accommodation booking for entire stay",
      "Bank statements (last 6 months)",
      "Proof of employment or business",
    ],
    supporting: ["Cover letter", "Travel insurance", "Income Tax Returns (last 2-3 years)"],
  };

  var RULES = {
    "Europe (Schengen)": {
      Tourist: {
        required: [
          "Valid passport (original + photocopy of first & last page)",
          "Passport-size photographs (Schengen specification)",
          "Visa application form (signed)",
          "Cover letter",
          "Confirmed return flight tickets",
          "Hotel / accommodation booking for entire stay",
          "Travel insurance (minimum €30,000 coverage)",
          "Bank statements (last 6 months)",
          "Proof of employment or business",
          "Income Tax Returns (last 2-3 years)",
        ],
        supporting: [
          "Sponsor's documents (if sponsored)",
          "Marriage certificate (if travelling with spouse)",
          "Property documents",
          "Previous visa copies (if any)",
        ],
      },
    },
    Japan: {
      Tourist: {
        required: [
          "Valid passport (original + photocopy)",
          "Visa application form (signed)",
          "Passport-size photograph",
          "Cover letter",
          "Confirmed flight itinerary",
          "Hotel booking confirmation",
          "Daily travel schedule / itinerary",
          "Bank statements (last 6 months)",
          "Proof of employment or business",
          "Income Tax Returns (last 2-3 years)",
        ],
        supporting: ["Sponsor's documents (if sponsored)", "Guarantor's letter (if applicable)"],
      },
    },
    Singapore: {
      Tourist: {
        required: [
          "Valid passport (original + photocopy)",
          "Visa application form (signed)",
          "Passport-size photograph",
          "Cover letter",
          "Confirmed return flight tickets",
          "Hotel booking confirmation",
          "Bank statement (last 6 months)",
          "Proof of employment or business",
        ],
        supporting: ["Income Tax Returns", "Sponsor's documents (if sponsored)"],
      },
    },
  };

  /**
   * @returns {{required: string[], supporting: string[], isGeneric: boolean}}
   */
  function getChecklist(destination, visaCategory) {
    var byDestination = RULES[destination];
    var match = byDestination && byDestination[visaCategory];
    if (match) {
      return { required: match.required.slice(), supporting: match.supporting.slice(), isGeneric: false };
    }
    return { required: GENERIC_CHECKLIST.required.slice(), supporting: GENERIC_CHECKLIST.supporting.slice(), isGeneric: true };
  }

  global.KhannaChecklistRules = {
    DESTINATIONS: DESTINATIONS,
    VISA_CATEGORIES: VISA_CATEGORIES,
    getChecklist: getChecklist,
  };
})(window);
