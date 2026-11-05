/* ==========================================================================
   Khanna Travels & Holidays — which traveller details each letter prints
   One place that says, for every document that names people, WHICH of a
   person's details it prints (so the manual-entry form can ask for exactly
   those, mark them required, and the page can warn when one is missing
   instead of silently printing a dash).

   The names below are the field names of the people rows the document pages
   work with (js/saved-details.js recordToRow): salutation, fullName, sex,
   passportNumber, placeOfIssue, passportIssueDate, phone, email.

   The lists mirror what the backend engines actually read from a person
   (authorization_letter_engine, cover_letter_engine, singapore_letter_engine,
   invitation_letter_engine) — they are not a wish list. If an engine starts
   printing another detail, add it here too.
   ========================================================================== */
(function (global) {
  "use strict";

  // Every detail the manual-entry form can collect. `row` is the matching key
  // on a people row; `form` is the form's own field name; `ocr` marks the
  // fields the passport OCR also extracts (so typed and scanned people carry
  // the same details).
  var FIELDS = [
    { form: "salutation", row: "salutation", label: "Salutation", group: "person" },
    { form: "fullName", row: "fullName", label: "Full name", group: "person", ocr: true },
    { form: "sex", row: "sex", label: "Sex", group: "person", ocr: true },
    { form: "dob", row: "dob", label: "Date of birth", group: "person", ocr: true },
    { form: "nationality", row: "nationality", label: "Nationality", group: "person", ocr: true },
    { form: "placeOfBirth", row: "placeOfBirth", label: "Place of birth", group: "person", ocr: true },
    { form: "passportNumber", row: "passportNumber", label: "Passport number", group: "passport", ocr: true },
    { form: "issuePlace", row: "placeOfIssue", label: "Place of issue", group: "passport", ocr: true },
    { form: "issueDate", row: "passportIssueDate", label: "Date of issue", group: "passport", ocr: true },
    { form: "expiryDate", row: "passportExpiryDate", label: "Date of expiry", group: "passport", ocr: true },
    { form: "phone", row: "phone", label: "Phone number", group: "contact" },
    { form: "email", row: "email", label: "Email address", group: "contact" },
  ];

  // What each letter prints about a person. `applicant` = the person the
  // letter is written by / for; `others` = everyone else listed on it.
  var DOCS = {
    coverLetter: {
      title: "this cover letter",
      applicant: ["salutation", "fullName", "passportNumber", "issuePlace", "issueDate", "phone", "email"],
      others: ["salutation", "fullName", "passportNumber"],
    },
    passportAuth: {
      title: "this Passport Authorization Letter",
      applicant: ["salutation", "fullName", "passportNumber", "phone", "email"],
      others: ["salutation", "fullName", "passportNumber"],
    },
    passportAuthSingapore: {
      title: "this Singapore Authorisation Letter",
      applicant: ["salutation", "fullName", "passportNumber"],
      others: ["passportNumber"],
    },
    companyAuth: {
      title: "this Company Authorization Letter",
      applicant: ["fullName", "passportNumber"],
      others: ["fullName", "passportNumber"],
    },
    companyAuthSingapore: {
      title: "this Sub-Agent Declaration Form",
      applicant: ["passportNumber"],
      others: ["passportNumber"],
    },
    invitation: {
      title: "this invitation letter",
      applicant: ["fullName", "passportNumber"],
      others: ["fullName", "passportNumber"],
    },
  };

  function byForm(name) {
    for (var i = 0; i < FIELDS.length; i++) if (FIELDS[i].form === name) return FIELDS[i];
    return null;
  }

  // The required form-field names for a letter. `role` is "applicant" or
  // anything else (a companion / other person). A person's name and passport
  // number are always needed, whatever the letter.
  function required(docKey, role) {
    var doc = DOCS[docKey];
    var list = doc ? (role === "applicant" ? doc.applicant : doc.others) : [];
    var out = ["fullName", "passportNumber"];
    list.forEach(function (name) {
      if (out.indexOf(name) === -1) out.push(name);
    });
    return out;
  }

  function label(name) {
    var f = byForm(name);
    return f ? f.label : name;
  }

  // Sentence for the "enter manually" option: what this letter needs.
  function summary(docKey) {
    var doc = DOCS[docKey];
    if (!doc) return "Name and passport number are needed.";
    var names = required(docKey, "applicant").map(function (n) { return label(n).toLowerCase(); });
    return "Needed for " + doc.title + ": " + names.join(", ").replace(/, ([^,]*)$/, " and $1") + ".";
  }

  // The required details a people row is missing (form-field names).
  function missing(docKey, row, role) {
    return required(docKey, role).filter(function (name) {
      var f = byForm(name);
      var v = row && f ? row[f.row] : "";
      return !String(v == null ? "" : v).trim();
    });
  }

  global.KhannaDocFields = {
    FIELDS: FIELDS,
    DOCS: DOCS,
    required: required,
    missing: missing,
    label: label,
    summary: summary,
  };
})(window);
