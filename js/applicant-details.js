/* ==========================================================================
   Khanna Travels & Holidays — applicant basic details (shared helpers)
   One place that knows what an applicant's "basic details" are and how a
   letter or visa form reads them, so the Applicant Profiles page, the cover
   letter, the invitation letter and the Fill Forms page all agree and none
   of them keeps its own copy of the list (project rule 15).

   The values live on the person record itself (KhannaState emptyPerson():
   `details` for occupation / education / employer / marital status / income /
   emergency contact, `contact` for phone and email). The residential address
   is NOT a basic detail: it is read from the passport only.
   ========================================================================== */
(function (global) {
  "use strict";

  var MARITAL_OPTIONS = ["Single", "Married", "Divorced", "Widowed", "Separated"];

  // Groups, in the order the Applicant Profiles page shows them. `where` is the
  // honest list of places that really use the value (kept in step with the
  // code: js/cover-letter.js, js/invitation.js, js/fill-forms.js).
  var GROUPS = [
    {
      id: "contact",
      title: "Contact",
      fields: [
        { group: "contact", key: "phone", label: "Phone number", type: "tel", where: "Cover Letter, Passport Authorization Letter, visa form (mobile no.)" },
        { group: "contact", key: "email", label: "Email address", type: "email", where: "Cover Letter, Passport Authorization Letter" },
      ],
    },
    {
      id: "work",
      title: "Work and education",
      fields: [
        { group: "details", key: "occupation", label: "Occupation / job title", placeholder: "e.g. Software Engineer", where: "Cover Letter, Invitation Letter, visa form" },
        { group: "details", key: "education", label: "Education", placeholder: "e.g. B.Com, MBA", where: "kept on the profile" },
        { group: "details", key: "employerName", label: "Employer / business name", where: "Cover Letter, visa form" },
        { group: "details", key: "employerAddress", label: "Employer / business address", wide: true, where: "visa form" },
        { group: "details", key: "employerPhone", label: "Employer / business phone", type: "tel", where: "visa form" },
      ],
    },
    {
      id: "family",
      title: "Marital status",
      fields: [
        { group: "details", key: "maritalStatus", label: "Marital status", options: MARITAL_OPTIONS, where: "visa form" },
        { group: "details", key: "spouseName", label: "Spouse name", where: "kept on the profile" },
      ],
    },
    {
      id: "income",
      title: "Income",
      fields: [
        { group: "details", key: "monthlyIncome", label: "Monthly income", placeholder: "e.g. INR 85,000", where: "kept on the profile" },
        { group: "details", key: "annualIncome", label: "Annual income", placeholder: "e.g. INR 10,20,000", where: "kept on the profile" },
      ],
    },
    {
      id: "emergency",
      title: "Emergency contact",
      fields: [
        { group: "details", key: "emergencyName", label: "Name", where: "kept on the profile" },
        { group: "details", key: "emergencyRelation", label: "Relation", placeholder: "e.g. Brother", where: "kept on the profile" },
        { group: "details", key: "emergencyPhone", label: "Phone number", type: "tel", where: "kept on the profile" },
      ],
    },
  ];

  function s(v) {
    return v === null || v === undefined ? "" : String(v).trim();
  }

  /** The saved basic details of one person record (always a full object). */
  function of(person) {
    var base = global.KhannaState.createEmptyDetails();
    var d = (person && person.details) || {};
    Object.keys(base).forEach(function (k) {
      base[k] = s(d[k]);
    });
    base.phone = s(person && person.contact && person.contact.phone);
    base.email = s(person && person.contact && person.contact.email);
    return base;
  }

  /** Basic details of "applicant" or of the traveller with this id. */
  function ofPersonId(app, personId) {
    if (!app) return of(null);
    if (!personId || personId === "applicant") return of(app.applicant);
    var t = (app.travellers || []).filter(function (x) { return x.id === personId; })[0];
    return of(t || app.applicant);
  }

  /** The spouse name printed on the passport's last page, if one was read. */
  function passportSpouse(person) {
    return s(person && person.passportSpouseName);
  }

  /**
   * What the passport says about marital status: only "Married" can be
   * suggested (a spouse name is printed); anything else has to come from staff.
   */
  function maritalFromPassport(person) {
    return passportSpouse(person) ? "Married" : "";
  }

  /** Marital status to use: what staff saved, else the passport's hint. */
  function maritalStatus(person) {
    return of(person).maritalStatus || maritalFromPassport(person);
  }

  function spouseName(person) {
    return of(person).spouseName || passportSpouse(person);
  }

  /** "Software Engineer at Acme Corp" — occupation and employer in one line. */
  function occupationLine(d) {
    d = d || {};
    if (d.occupation && d.employerName) return d.occupation + " at " + d.employerName;
    return d.occupation || d.employerName || "";
  }

  /** The residential address printed in the passport, on one line. */
  function passportAddressLine(person) {
    var a = (person && person.address) || {};
    var seen = [];
    [a.line1, a.line2, a.city, a.state, a.pincode, a.country].forEach(function (part) {
      part = s(part);
      if (part && seen.join(", ").toUpperCase().indexOf(part.toUpperCase()) === -1) seen.push(part);
    });
    return seen.join(", ");
  }

  global.KhannaApplicantDetails = {
    MARITAL_OPTIONS: MARITAL_OPTIONS,
    GROUPS: GROUPS,
    of: of,
    ofPersonId: ofPersonId,
    passportSpouse: passportSpouse,
    maritalFromPassport: maritalFromPassport,
    maritalStatus: maritalStatus,
    spouseName: spouseName,
    occupationLine: occupationLine,
    passportAddressLine: passportAddressLine,
  };
})(window);
