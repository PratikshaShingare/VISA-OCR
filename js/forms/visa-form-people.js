/* ==========================================================================
   Khanna Travels & Holidays — people for the Fill Forms / Check Forms pages
   One place that turns a saved applicant / traveller, or a passport just read
   by OCR (js/documents/document-intake.js), into the flat "passport details"
   both pages work with:
     { surname, givenNames, dob (ISO), sex, nationality, countryCode,
       placeOfBirth, passportNumber, passportType, issueDate, expiryDate,
       issuePlace, issuingAuthority }
   No second OCR path and no second copy of the application shape.
   ========================================================================== */
(function (global) {
  "use strict";

  var DETAIL_FIELDS = [
    { key: "surname", label: "Surname" },
    { key: "givenNames", label: "Given names" },
    { key: "dob", label: "Date of birth", date: true },
    { key: "sex", label: "Sex", options: [["", "—"], ["M", "Male"], ["F", "Female"], ["X", "Other"]] },
    { key: "nationality", label: "Nationality" },
    { key: "placeOfBirth", label: "Place of birth" },
    { key: "passportNumber", label: "Passport number" },
    { key: "passportType", label: "Passport type (P = ordinary)" },
    { key: "issueDate", label: "Date of issue", date: true },
    { key: "expiryDate", label: "Date of expiry", date: true },
    { key: "issuePlace", label: "Place of issue" },
    { key: "issuingAuthority", label: "Issuing authority" },
  ];

  function s(v) {
    return v === null || v === undefined ? "" : String(v).trim();
  }

  function joinName(parts) {
    return parts.map(s).filter(Boolean).join(" ");
  }

  /** A saved person (KhannaState emptyPerson() shape) -> passport details. */
  function fromPerson(person) {
    var p = person || {};
    var cur = (p.passport && p.passport.current) || {};
    return {
      surname: s(p.lastName),
      givenNames: joinName([p.firstName, p.middleName]),
      dob: s(p.dob),
      sex: s(p.sex),
      nationality: s(p.nationality),
      countryCode: s(cur.countryCode),
      placeOfBirth: s(p.placeOfBirth),
      passportNumber: s(cur.number),
      passportType: s(cur.type),
      issueDate: s(cur.issueDate),
      expiryDate: s(cur.expiryDate),
      issuePlace: s(cur.issuePlace),
      issuingAuthority: s(cur.issuingAuthority),
    };
  }

  /** A record from KhannaDocumentIntake.readPassport() -> passport details. */
  function fromIntakeRecord(record) {
    var v = (record && record.values) || {};
    var person = Object.assign({}, v.applicant || {}, { passport: { current: v.current || {} } });
    return fromPerson(person);
  }

  function displayName(details) {
    return joinName([details.givenNames, details.surname]) || details.passportNumber || "Unnamed passport";
  }

  /** Everyone in one saved application who has at least a name or passport number. */
  function peopleOfApplication(app) {
    if (!app) return [];
    var out = [];
    function add(person, role, id) {
      var d = fromPerson(person);
      if (!d.surname && !d.givenNames && !d.passportNumber) return;
      out.push({ id: id, role: role, person: person, details: d });
    }
    add(app.applicant, "Main applicant", "applicant");
    (app.travellers || []).forEach(function (t, i) {
      add(t, t.relation ? "Traveller (" + t.relation + ")" : "Traveller " + (i + 1), t.id || "traveller-" + i);
    });
    return out;
  }

  global.KhannaVisaFormPeople = {
    DETAIL_FIELDS: DETAIL_FIELDS,
    fromPerson: fromPerson,
    fromIntakeRecord: fromIntakeRecord,
    displayName: displayName,
    peopleOfApplication: peopleOfApplication,
  };
})(window);
