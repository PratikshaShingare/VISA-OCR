/* ==========================================================================
   Khanna Travels & Holidays — Invitation Letter (wizard step 7)
   Phase 10. Builds both real document categories this step covers, each
   calling the real backend engine (backend/python/invitation_letter_engine.py)
   to fill the actual, unmodified reference template (project rule 5) — not
   a recreation:

     - Invitation Letter: written by a person already living abroad (the
       inviter — entered freely here, since they are NOT one of this
       application's own applicant/travellers) inviting exactly 2 of this
       application's own people, matching the real reference template's
       fixed "my Parents" wording.
     - Initors Covering Letter (the user's own "Spouse-Accompanying Cover
       Letter" framing, Phase 0): for a married couple travelling
       together, invited by the same person abroad. Each spouse signs and
       submits their OWN letter — generated ONE AT A TIME below, in that
       spouse's own real gendered-voice template (chosen by their `sex`
       field, matching the backend's own selection logic) — so this view
       renders one sub-section per selected person, each with its own
       occupation/relation fields, its own signature upload, and its own
       pair of Generate/Download buttons.

   Person data (applicant + every traveller, flattened to a person row) is
   reused from authorization.js's own `global.KhannaAuthorization` export
   rather than re-derived here (project rule 15) — same as cover-letter.js.
   Signature images are staff-uploaded files, kept only in
   KhannaDocumentFileStore (in-memory, this tab only — see that module's
   header) and embedded server-side into the blank signature-slot paragraph
   the reference templates already leave; when none is uploaded, that slot
   is left exactly as blank as the template's own original (project rule 9
   — never a fabricated signature).

   Re-render discipline: identical reasoning to authorization.js/
   cover-letter.js's own file headers. The two checklists and every
   generate bar redraw freely on every KhannaState change. Everything else
   (free-text fields, the per-person Initors sub-sections themselves — since
   which sub-sections even exist depends on who's selected) only rebuilds
   on a real "entering this step" navigation, or immediately after an
   explicit action taken IN THIS PANEL that changes its own shape
   (selecting/deselecting a person, uploading/removing a signature) — never
   from an unrelated background state change, so in-progress typing is
   never overwritten out from under a staff member.
   ========================================================================== */
(function (global) {
  "use strict";

  var utils = global.KhannaUtils;
  var api = global.KhannaApi;
  var fileStore = global.KhannaDocumentFileStore;

  // Document-first redesign (Phase 2): dual-mount, same reasoning and same
  // one-function change as hotels.js's own root() — every lookup in this
  // file goes through root() (or a local `r` captured from it), so nothing
  // else here needs to know which page it's mounted in.
  function root() {
    var view = global.KhannaRouter ? global.KhannaRouter.parseHash().view : null;
    if (view === "invitation-letter") return utils.qs("[data-invitation-letter-page-root]");
    return utils.qs("[data-invitation-step-root]");
  }

  function getApp() {
    return global.KhannaState.getActiveApplication();
  }

  function authHelpers() {
    return global.KhannaAuthorization;
  }

  /* ---------------------------------------------------------------------
   * Field row helper — shared shape for both cards' free-text fields,
   * matching authorization.js/cover-letter.js's own fieldRowHtml exactly,
   * generalised with an explicit data-attribute name so the two cards'
   * fields (which patch two different parts of the Application record,
   * `invitation` vs `initorsLetters`) don't collide on the same selector.
   * ------------------------------------------------------------------- */

  function fieldRowHtml(attrName, scope, key, label, value, required, opts) {
    opts = opts || {};
    var id = attrName + "-" + scope.replace(":", "-") + "-" + key;
    return (
      '<div class="field">' +
      '<label for="' + id + '">' + utils.escapeHtml(label) + (required ? " *" : "") + "</label>" +
      '<input type="' + (opts.type || "text") + '" id="' + id + '" data-' + attrName + '="' + scope + ":" + key + '"' +
      (opts.placeholder ? ' placeholder="' + utils.escapeHtml(opts.placeholder) + '"' : "") +
      ' value="' + utils.escapeHtml(value || "") + '" />' +
      "</div>"
    );
  }

  /* ---------------------------------------------------------------------
   * Signature upload control — shared by both cards. `scope` is either
   * "invitation" (the Invitation Letter's own single signature) or
   * "initors:<personId>" (one signature per selected person, since each
   * spouse signs their own letter).
   * ------------------------------------------------------------------- */

  function signatureUploadHtml(scope, fileName) {
    return (
      '<div class="signature-upload" data-signature-scope="' + utils.escapeHtml(scope) + '">' +
      '<input type="file" hidden accept="image/png,image/jpeg,image/webp" data-signature-file-input="' + utils.escapeHtml(scope) + '" />' +
      '<button type="button" class="btn btn-secondary btn-sm" data-action="upload-signature" data-scope="' + utils.escapeHtml(scope) + '">' +
      (fileName ? "Replace signature" : "Upload signature (optional)") +
      "</button>" +
      (fileName
        ? '<span class="signature-upload__filename">' + utils.escapeHtml(fileName) + "</span>" +
          '<button type="button" class="btn-icon" data-action="remove-signature" data-scope="' + utils.escapeHtml(scope) + '" aria-label="Remove signature">' +
          '<svg class="icon icon-sm" viewBox="0 0 24 24"><path d="M18 6 6 18M6 6l12 12"/></svg></button>'
        : '<span class="field-hint">A wet or scanned signature image, optional — left blank, the letter’s own signature line stays exactly as blank as the reference template leaves it.</span>') +
      "</div>"
    );
  }

  /* ---------------------------------------------------------------------
   * Invitation Letter — state, readiness
   * ------------------------------------------------------------------- */

  function invitationState(app) {
    return (app && app.invitation) || {};
  }

  function selectedInvitees(app) {
    var auth = authHelpers();
    if (!auth) return [];
    var state = invitationState(app);
    var ids = state.selectedInviteeIds || [];
    return auth.getSelectablePeople(app).filter(function (p) {
      return ids.indexOf(p.id) !== -1;
    });
  }

  var INVITER_REQUIRED_FIELDS = [
    "fullName",
    "addressLine1",
    "cityPostcode",
    "country",
    "cityCountry",
    "passportNumber",
    "fullAddress",
    "studyingOrWorking",
    "universityOrCompany",
    "phone",
    "email",
  ];

  function inviterHasCoreFields(inviter) {
    inviter = inviter || {};
    return INVITER_REQUIRED_FIELDS.every(function (k) {
      return !!(inviter[k] && String(inviter[k]).trim());
    });
  }

  function invitationReady(app) {
    var auth = authHelpers();
    if (!app || !auth) return false;
    var state = invitationState(app);
    var invitees = selectedInvitees(app);
    if (invitees.length !== 2) return false;
    if (!invitees.every(auth.personHasCoreFields)) return false;
    if (!inviterHasCoreFields(state.inviter)) return false;
    return ["travelStartDate", "travelEndDate", "purpose", "accommodationDetails", "returnDate", "fundingArrangement"].every(
      function (k) {
        return !!(state[k] && String(state[k]).trim());
      }
    );
  }

  /* ---------------------------------------------------------------------
   * Invitation Letter — rendering
   * ------------------------------------------------------------------- */

  function inviteeChecklistHtml(app) {
    var auth = authHelpers();
    var people = auth ? auth.getSelectablePeople(app) : [];
    if (!people.length) {
      return '<p class="field-hint">Add the applicant and/or travellers in earlier steps first.</p>';
    }
    var state = invitationState(app);
    var selectedIds = state.selectedInviteeIds || [];
    return people
      .map(function (p) {
        var checked = selectedIds.indexOf(p.id) !== -1;
        var atMax = !checked && selectedIds.length >= 2;
        var incomplete = !auth.personHasCoreFields(p);
        return (
          '<label class="auth-person-row' + (atMax ? " is-disabled" : "") + '">' +
          '<input type="checkbox" data-invitation-invitee data-person-id="' + utils.escapeHtml(p.id) + '"' +
          (checked ? " checked" : "") +
          (atMax ? " disabled" : "") +
          " />" +
          '<span class="auth-person-row__name">' + utils.escapeHtml(auth.personDisplayName(p)) + "</span>" +
          '<span class="auth-person-row__meta">' +
          utils.escapeHtml(p.relationLabel) +
          (incomplete ? " · missing name or passport number" : "") +
          "</span>" +
          "</label>"
        );
      })
      .join("");
  }

  function refreshInviteeChecklist() {
    var app = getApp();
    var box = utils.qs("[data-invitation-invitee-checklist]", root());
    if (!app || !box) return;
    box.innerHTML = inviteeChecklistHtml(app);
  }

  function inviterFieldsHtml(state) {
    var inv = state.inviter || {};
    return (
      '<div class="field-grid">' +
      fieldRowHtml("invitation-field", "inviter", "fullName", "Inviter's full name", inv.fullName, true, {
        placeholder: "e.g. Ms. Tanishka Sushil",
      }) +
      fieldRowHtml("invitation-field", "inviter", "passportNumber", "Inviter's passport number", inv.passportNumber, true) +
      fieldRowHtml("invitation-field", "inviter", "addressLine1", "Address line 1", inv.addressLine1, true) +
      fieldRowHtml("invitation-field", "inviter", "addressLine2", "Address line 2 (optional)", inv.addressLine2, false) +
      fieldRowHtml("invitation-field", "inviter", "cityPostcode", "City, postcode", inv.cityPostcode, true, {
        placeholder: "e.g. Cork T12 FWK3",
      }) +
      fieldRowHtml("invitation-field", "inviter", "fullAddress", "Full address (one line)", inv.fullAddress, true, {
        placeholder: "Used in the letter's opening paragraph",
      }) +
      fieldRowHtml("invitation-field", "inviter", "country", "Country (of the consulate)", inv.country, true, {
        placeholder: "e.g. Ireland",
      }) +
      fieldRowHtml("invitation-field", "inviter", "cityCountry", "City, country (of the consulate)", inv.cityCountry, true, {
        placeholder: "e.g. Mumbai, India",
      }) +
      fieldRowHtml("invitation-field", "inviter", "studyingOrWorking", "Studying or working", inv.studyingOrWorking, true, {
        placeholder: "e.g. Studying",
      }) +
      fieldRowHtml("invitation-field", "inviter", "universityOrCompany", "University / company name", inv.universityOrCompany, true) +
      fieldRowHtml("invitation-field", "inviter", "phone", "Inviter's phone number", inv.phone, true) +
      fieldRowHtml("invitation-field", "inviter", "email", "Inviter's email", inv.email, true) +
      "</div>"
    );
  }

  function invitationTripFieldsHtml(state) {
    return (
      '<div class="field-grid">' +
      fieldRowHtml("invitation-field", "top", "travelStartDate", "Travel start date", state.travelStartDate, true, { type: "date" }) +
      fieldRowHtml("invitation-field", "top", "travelEndDate", "Travel end date", state.travelEndDate, true, { type: "date" }) +
      fieldRowHtml("invitation-field", "top", "purpose", "Purpose of visit", state.purpose, true, {
        placeholder: "e.g. attending my convocation ceremony",
      }) +
      fieldRowHtml("invitation-field", "top", "accommodationDetails", "Accommodation details", state.accommodationDetails, true, {
        placeholder: "e.g. with the inviter",
      }) +
      fieldRowHtml("invitation-field", "top", "returnDate", "Return date", state.returnDate, true, { type: "date" }) +
      fieldRowHtml("invitation-field", "top", "fundingArrangement", "Expenses covered by", state.fundingArrangement, true, {
        placeholder: "e.g. the invitees",
      }) +
      "</div>"
    );
  }

  function invitationGenerateBarHtml(ready, generatedAt) {
    return (
      '<div class="hotel-generate-bar">' +
      '<button class="btn btn-primary btn-sm" type="button" data-action="generate-invitation" data-format="docx"' +
      (ready ? "" : " disabled") +
      ">Generate (.docx)</button>" +
      '<button class="btn btn-secondary btn-sm" type="button" data-action="generate-invitation" data-format="pdf"' +
      (ready ? "" : " disabled") +
      ">Download as PDF</button>" +
      (generatedAt ? '<span class="hotel-generate-bar__meta">Last generated ' + utils.formatDate(generatedAt) + "</span>" : "") +
      "</div>"
    );
  }

  function refreshInvitationGenerateBar() {
    var app = getApp();
    var box = utils.qs("[data-invitation-generate-bar]", root());
    if (!app || !box) return;
    var state = invitationState(app);
    box.innerHTML = invitationGenerateBarHtml(invitationReady(app), state.generatedAt);
  }

  function refreshInvitationReadiness() {
    var app = getApp();
    var box = utils.qs("[data-invitation-readiness]", root());
    if (!app || !box) return;
    box.innerHTML = invitationReady(app)
      ? ""
      : '<div class="notice notice-warning">' +
        '<svg class="icon icon-sm" viewBox="0 0 24 24"><path d="M12 9v4M12 17h.01"/><circle cx="12" cy="12" r="9"/></svg>' +
        "<span>Select exactly 2 invitees (each with a name and passport number on file), fill in the inviter's own details and every trip field above, to generate this letter.</span>" +
        "</div>";
  }

  function showInvitationError(message) {
    var box = utils.qs("[data-invitation-error]", root());
    if (!box) return;
    box.innerHTML = message
      ? '<div class="notice notice-danger">' +
        '<svg class="icon icon-sm" viewBox="0 0 24 24"><path d="M12 9v4M12 17h.01"/><circle cx="12" cy="12" r="9"/></svg>' +
        "<span>" + utils.escapeHtml(message) + "</span>" +
        "</div>"
      : "";
  }

  function renderInvitationCard() {
    var app = getApp();
    var box = utils.qs("[data-invitation-card]", root());
    if (!app || !box) return;
    var state = invitationState(app);
    box.innerHTML =
      "<h3>Invitation Letter</h3>" +
      "<p>Written by a person already living abroad (the inviter), inviting exactly two of this application's own people — matches the real reference template's fixed “my Parents” wording.</p>" +
      '<h4 class="cover-subheading">Who is being invited</h4>' +
      '<div class="auth-person-list" data-invitation-invitee-checklist>' + inviteeChecklistHtml(app) + "</div>" +
      '<h4 class="cover-subheading">The inviter (not part of this application)</h4>' +
      inviterFieldsHtml(state) +
      '<h4 class="cover-subheading">Trip details</h4>' +
      invitationTripFieldsHtml(state) +
      '<h4 class="cover-subheading">Signature (optional)</h4>' +
      signatureUploadHtml("invitation", state.signatureFileName) +
      '<div data-invitation-readiness></div>' +
      '<div data-invitation-generate-bar></div>' +
      '<div data-invitation-error></div>';
    refreshInvitationGenerateBar();
    refreshInvitationReadiness();
  }

  /* ---------------------------------------------------------------------
   * Invitation Letter — generation
   * ------------------------------------------------------------------- */

  function buildInvitationPayload(app, format) {
    var invitees = selectedInvitees(app);
    var state = invitationState(app);
    var inv = state.inviter || {};
    return {
      inviter: {
        fullName: inv.fullName || "",
        addressLine1: inv.addressLine1 || "",
        addressLine2: inv.addressLine2 || "",
        cityPostcode: inv.cityPostcode || "",
        country: inv.country || "",
        cityCountry: inv.cityCountry || "",
        passportNumber: inv.passportNumber || "",
        fullAddress: inv.fullAddress || "",
        studyingOrWorking: inv.studyingOrWorking || "",
        universityOrCompany: inv.universityOrCompany || "",
        phone: inv.phone || "",
        email: inv.email || "",
      },
      invitees: invitees.map(function (p) {
        return {
          fullName: p.fullName || "",
          passportNumber: p.passportNumber || "",
          placeOfIssue: p.placeOfIssue || "",
          passportIssueDate: p.passportIssueDate || "",
        };
      }),
      travelStartDate: state.travelStartDate || "",
      travelEndDate: state.travelEndDate || "",
      purpose: state.purpose || "",
      accommodationDetails: state.accommodationDetails || "",
      returnDate: state.returnDate || "",
      fundingArrangement: state.fundingArrangement || "",
      format: format,
      // Unlike every other document endpoint in this app, this letter is
      // written in the INVITER's own voice, not the main applicant's — so
      // the downloaded filename uses the inviter's own name (falling back
      // to the backend's own generic "Invitation_Letter" suffix, exactly
      // like every other endpoint's own applicantName-omitted fallback,
      // when it's still blank).
      applicantName: inv.fullName || null,
    };
  }

  function generateInvitation(format, btn) {
    var app = getApp();
    if (!app || !invitationReady(app)) return;
    showInvitationError("");
    var originalText = btn.textContent;
    btn.disabled = true;
    btn.textContent = "Generating…";

    var payload = buildInvitationPayload(app, format);
    var state = invitationState(app);
    var cached = state.signatureFileRef ? fileStore.get(state.signatureFileRef) : null;
    var signatureFile = cached ? cached.file : null;

    api.downloadInvitationLetter(payload, signatureFile).then(
      function (result) {
        utils.triggerFileDownload(result.blob, result.filename);
        var ts = new Date().toISOString();
        global.KhannaState.updateApplication(
          app.id,
          { invitation: { generatedAt: ts } },
          "Invitation Letter generated (" + format.toUpperCase() + ")"
        );
        // The generate bar's "Last generated" text picks up the fresh
        // timestamp via the KhannaState.subscribe callback below —
        // deliberately not refreshed directly here, matching
        // authorization.js/cover-letter.js's own discipline (success and
        // failure both flow through exactly one place).
      },
      function (err) {
        btn.disabled = false;
        btn.textContent = originalText;
        showInvitationError((err && err.message) || "Could not generate the invitation letter.");
      }
    );
  }

  /* ---------------------------------------------------------------------
   * Initors Covering Letter — state, readiness
   * ------------------------------------------------------------------- */

  function initorsState(app) {
    return (app && app.initorsLetters) || {};
  }

  function selectedInitorsPeople(app) {
    var auth = authHelpers();
    if (!auth) return [];
    var state = initorsState(app);
    var ids = state.selectedPersonIds || [];
    return auth.getSelectablePeople(app).filter(function (p) {
      return ids.indexOf(p.id) !== -1;
    });
  }

  function invitingPersonHasCoreFields(ip) {
    ip = ip || {};
    return ["fullName", "passportNumber", "countryOfResidence", "visaResidenceStatus"].every(function (k) {
      return !!(ip[k] && String(ip[k]).trim());
    });
  }

  function perPersonEntry(app, personId) {
    var state = initorsState(app);
    return (state.perPerson && state.perPerson[personId]) || {};
  }

  function personHasValidSex(person) {
    return person.sex === "M" || person.sex === "F";
  }

  function personInitorsReady(app, person) {
    var auth = authHelpers();
    if (!auth || !auth.personHasCoreFields(person)) return false;
    if (!personHasValidSex(person)) return false;
    var entry = perPersonEntry(app, person.id);
    return !!(entry.occupation && entry.occupation.trim()) && !!(entry.relationWithInvitingPerson && entry.relationWithInvitingPerson.trim());
  }

  function initorsCommonReady(app) {
    var state = initorsState(app);
    if (!invitingPersonHasCoreFields(state.invitingPerson)) return false;
    return [
      "country",
      "purpose",
      "travelStartDate",
      "travelEndDate",
      "returnDate",
      "accommodationDetails",
      "otherCommitments",
      "invitationSupportingDocuments",
    ].every(function (k) {
      return !!(state[k] && String(state[k]).trim());
    });
  }

  function initorsPersonReadyToGenerate(app, person) {
    return selectedInitorsPeople(app).length === 2 && initorsCommonReady(app) && personInitorsReady(app, person);
  }

  // Step 7's "Continue" gate — mirrors authorization.js's own isStep6Complete
  // precedent (that step requires Passport Authorization AND Company
  // Authorization AND the Cover Letter all ready, not any one of them):
  // both document categories on this step must be genuinely ready, since
  // the underlying data being complete is what this gate has always
  // measured in this app, not whether a document has actually been
  // downloaded yet.
  function isStep7Complete() {
    var app = getApp();
    if (!app) return false;
    if (!invitationReady(app)) return false;
    var selected = selectedInitorsPeople(app);
    if (selected.length !== 2) return false;
    if (!initorsCommonReady(app)) return false;
    return selected.every(function (p) {
      return personInitorsReady(app, p);
    });
  }

  /* ---------------------------------------------------------------------
   * Initors Covering Letter — rendering
   * ------------------------------------------------------------------- */

  function initorsPersonChecklistHtml(app) {
    var auth = authHelpers();
    var people = auth ? auth.getSelectablePeople(app) : [];
    if (!people.length) {
      return '<p class="field-hint">Add the applicant and/or travellers in earlier steps first.</p>';
    }
    var state = initorsState(app);
    var selectedIds = state.selectedPersonIds || [];
    return people
      .map(function (p) {
        var checked = selectedIds.indexOf(p.id) !== -1;
        var atMax = !checked && selectedIds.length >= 2;
        var incomplete = !auth.personHasCoreFields(p) || !personHasValidSex(p);
        return (
          '<label class="auth-person-row' + (atMax ? " is-disabled" : "") + '">' +
          '<input type="checkbox" data-initors-person data-person-id="' + utils.escapeHtml(p.id) + '"' +
          (checked ? " checked" : "") +
          (atMax ? " disabled" : "") +
          " />" +
          '<span class="auth-person-row__name">' + utils.escapeHtml(auth.personDisplayName(p)) + "</span>" +
          '<span class="auth-person-row__meta">' +
          utils.escapeHtml(p.relationLabel) +
          (incomplete ? " · missing name, passport number, or sex (Male/Female)" : "") +
          "</span>" +
          "</label>"
        );
      })
      .join("");
  }

  function initorsCommonFieldsHtml(state) {
    var ip = state.invitingPerson || {};
    return (
      '<h4 class="cover-subheading">The person abroad they are visiting</h4>' +
      '<div class="field-grid">' +
      fieldRowHtml("initors-field", "inviting", "fullName", "Full name", ip.fullName, true) +
      fieldRowHtml("initors-field", "inviting", "passportNumber", "Passport number", ip.passportNumber, true) +
      fieldRowHtml("initors-field", "inviting", "countryOfResidence", "Country of residence", ip.countryOfResidence, true) +
      fieldRowHtml("initors-field", "inviting", "visaResidenceStatus", "Visa / residence status", ip.visaResidenceStatus, true, {
        placeholder: "e.g. Work Visa",
      }) +
      "</div>" +
      '<h4 class="cover-subheading">Trip details</h4>' +
      '<div class="field-grid">' +
      fieldRowHtml("initors-field", "top", "country", "Destination country", state.country, true) +
      fieldRowHtml("initors-field", "top", "purpose", "Purpose of visit", state.purpose, true) +
      fieldRowHtml("initors-field", "top", "travelStartDate", "Travel start date", state.travelStartDate, true, { type: "date" }) +
      fieldRowHtml("initors-field", "top", "travelEndDate", "Travel end date", state.travelEndDate, true, { type: "date" }) +
      fieldRowHtml("initors-field", "top", "returnDate", "Return date", state.returnDate, true, { type: "date" }) +
      fieldRowHtml("initors-field", "top", "accommodationDetails", "Accommodation details", state.accommodationDetails, true) +
      fieldRowHtml(
        "initors-field",
        "top",
        "otherCommitments",
        "Reason for return (business / employment / other)",
        state.otherCommitments,
        true,
        { placeholder: "e.g. work commitments" }
      ) +
      fieldRowHtml(
        "initors-field",
        "top",
        "invitationSupportingDocuments",
        "Enclosed supporting documents",
        state.invitationSupportingDocuments,
        true,
        { placeholder: "e.g. invitation letter and hotel bookings" }
      ) +
      "</div>"
    );
  }

  function personFieldRowHtml(personId, key, label, value, required, opts) {
    opts = opts || {};
    var id = "initors-person-" + personId + "-" + key;
    return (
      '<div class="field">' +
      '<label for="' + id + '">' + utils.escapeHtml(label) + (required ? " *" : "") + "</label>" +
      '<input type="text" id="' + id + '" data-initors-person-field="' + utils.escapeHtml(personId) + ":" + key + '"' +
      (opts.placeholder ? ' placeholder="' + utils.escapeHtml(opts.placeholder) + '"' : "") +
      ' value="' + utils.escapeHtml(value || "") + '" />' +
      "</div>"
    );
  }

  function personGenerateBarHtml(personId, ready, generatedAt) {
    return (
      '<div class="hotel-generate-bar">' +
      '<button class="btn btn-primary btn-sm" type="button" data-action="generate-initors" data-person-id="' +
      utils.escapeHtml(personId) +
      '" data-format="docx"' +
      (ready ? "" : " disabled") +
      ">Generate (.docx)</button>" +
      '<button class="btn btn-secondary btn-sm" type="button" data-action="generate-initors" data-person-id="' +
      utils.escapeHtml(personId) +
      '" data-format="pdf"' +
      (ready ? "" : " disabled") +
      ">Download as PDF</button>" +
      (generatedAt ? '<span class="hotel-generate-bar__meta">Last generated ' + utils.formatDate(generatedAt) + "</span>" : "") +
      "</div>"
    );
  }

  function personSectionHtml(app, person) {
    var auth = authHelpers();
    var entry = perPersonEntry(app, person.id);
    var ready = initorsPersonReadyToGenerate(app, person);
    var sexNote = !personHasValidSex(person)
      ? '<div class="notice notice-warning">' +
        '<svg class="icon icon-sm" viewBox="0 0 24 24"><path d="M12 9v4M12 17h.01"/><circle cx="12" cy="12" r="9"/></svg>' +
        "<span>This person's sex must be recorded as Male or Female (Passport &amp; Applicant / Travellers step) — the letter is written in a real gendered voice matching one of the two reference templates on file, and no gender-neutral template exists.</span>" +
        "</div>"
      : "";
    var voiceNote =
      person.sex === "F"
        ? "Written in the wife's voice (“My Husband…”)."
        : person.sex === "M"
        ? "Written in the husband's voice (“My Wife…”)."
        : "Which real template is used depends on this person's own sex.";
    return (
      '<div class="hotel-panel initors-person-section" data-initors-person-section="' + utils.escapeHtml(person.id) + '">' +
      '<div class="hotel-panel__header"><h4 class="initors-person-section__title">' +
      utils.escapeHtml(auth.personDisplayName(person)) +
      "’s Covering Letter</h4></div>" +
      '<p class="initors-person-section__subtitle">' + voiceNote + " Signed and submitted separately from their spouse's own letter.</p>" +
      sexNote +
      '<div class="field-grid">' +
      personFieldRowHtml(person.id, "occupation", "Occupation / business details", entry.occupation, true, {
        placeholder: "e.g. Business Owner",
      }) +
      personFieldRowHtml(
        person.id,
        "relationWithInvitingPerson",
        "Relation to the person abroad",
        entry.relationWithInvitingPerson,
        true,
        { placeholder: "e.g. Daughter" }
      ) +
      "</div>" +
      signatureUploadHtml("initors:" + person.id, entry.signatureFileName) +
      '<div data-initors-generate-bar="' + utils.escapeHtml(person.id) + '">' +
      personGenerateBarHtml(person.id, ready, entry.generatedAt) +
      "</div>" +
      '<div data-initors-error="' + utils.escapeHtml(person.id) + '"></div>' +
      "</div>"
    );
  }

  function renderInitorsCard() {
    var app = getApp();
    var box = utils.qs("[data-initors-card]", root());
    if (!app || !box) return;
    var state = initorsState(app);
    var selected = selectedInitorsPeople(app);
    box.innerHTML =
      "<h3>Initors Covering Letter</h3>" +
      "<p>For a married couple travelling together, invited by the same person abroad — each spouse signs and submits their own letter, matching the two real reference templates on file (the same letter, written once in each spouse's own voice).</p>" +
      '<h4 class="cover-subheading">The couple</h4>' +
      '<div class="auth-person-list" data-initors-checklist>' + initorsPersonChecklistHtml(app) + "</div>" +
      (selected.length === 2
        ? initorsCommonFieldsHtml(state) + selected.map(function (p) { return personSectionHtml(app, p); }).join("")
        : '<p class="field-hint">Select exactly 2 people above (a married couple travelling together) to continue.</p>');
  }

  /* ---------------------------------------------------------------------
   * Initors Covering Letter — generation (one spouse's own letter at a
   * time — see file header)
   * ------------------------------------------------------------------- */

  function buildInitorsPayload(app, subject, spouse, format) {
    var state = initorsState(app);
    var ip = state.invitingPerson || {};
    var subjectEntry = perPersonEntry(app, subject.id);
    var spouseEntry = perPersonEntry(app, spouse.id);
    return {
      subject: {
        fullName: subject.fullName || "",
        passportNumber: subject.passportNumber || "",
        placeOfIssue: subject.placeOfIssue || "",
        passportIssueDate: subject.passportIssueDate || "",
        sex: subject.sex || "",
        phone: subject.phone || "",
        email: subject.email || "",
        occupation: subjectEntry.occupation || "",
        relationWithInvitingPerson: subjectEntry.relationWithInvitingPerson || "",
      },
      spouse: {
        fullName: spouse.fullName || "",
        passportNumber: spouse.passportNumber || "",
        placeOfIssue: spouse.placeOfIssue || "",
        passportIssueDate: spouse.passportIssueDate || "",
        occupation: spouseEntry.occupation || "",
      },
      invitingPerson: {
        fullName: ip.fullName || "",
        passportNumber: ip.passportNumber || "",
        countryOfResidence: ip.countryOfResidence || "",
        visaResidenceStatus: ip.visaResidenceStatus || "",
      },
      country: state.country || "",
      purpose: state.purpose || "",
      travelStartDate: state.travelStartDate || "",
      travelEndDate: state.travelEndDate || "",
      returnDate: state.returnDate || "",
      accommodationDetails: state.accommodationDetails || "",
      otherCommitments: state.otherCommitments || "",
      invitationSupportingDocuments: state.invitationSupportingDocuments || "",
      format: format,
      // This is the SUBJECT's own individual letter, not the main
      // application's — the filename should say whose letter it is, same
      // reasoning as the Invitation Letter's own applicantName override
      // above.
      applicantName: subject.fullName || null,
    };
  }

  function showInitorsError(personId, message) {
    var box = utils.qs('[data-initors-error="' + personId + '"]', root());
    if (!box) return;
    box.innerHTML = message
      ? '<div class="notice notice-danger">' +
        '<svg class="icon icon-sm" viewBox="0 0 24 24"><path d="M12 9v4M12 17h.01"/><circle cx="12" cy="12" r="9"/></svg>' +
        "<span>" + utils.escapeHtml(message) + "</span>" +
        "</div>"
      : "";
  }

  function generateInitors(personId, format, btn) {
    var app = getApp();
    if (!app) return;
    var selected = selectedInitorsPeople(app);
    if (selected.length !== 2) return;
    var subject = selected.find(function (p) {
      return p.id === personId;
    });
    var spouse = selected.find(function (p) {
      return p.id !== personId;
    });
    if (!subject || !spouse || !initorsPersonReadyToGenerate(app, subject)) return;

    showInitorsError(personId, "");
    var originalText = btn.textContent;
    btn.disabled = true;
    btn.textContent = "Generating…";

    var payload = buildInitorsPayload(app, subject, spouse, format);
    var entry = perPersonEntry(app, personId);
    var cached = entry.signatureFileRef ? fileStore.get(entry.signatureFileRef) : null;
    var signatureFile = cached ? cached.file : null;

    api.downloadInitorsCoveringLetter(payload, signatureFile).then(
      function (result) {
        utils.triggerFileDownload(result.blob, result.filename);
        var ts = new Date().toISOString();
        var patch = { initorsLetters: { perPerson: {} } };
        patch.initorsLetters.perPerson[personId] = { generatedAt: ts };
        global.KhannaState.updateApplication(
          app.id,
          patch,
          "Initors Covering Letter generated for " + (subject.fullName || "traveller") + " (" + format.toUpperCase() + ")"
        );
      },
      function (err) {
        btn.disabled = false;
        btn.textContent = originalText;
        showInitorsError(personId, (err && err.message) || "Could not generate this covering letter.");
      }
    );
  }

  /* ---------------------------------------------------------------------
   * Signature upload/remove — shared handling for both cards
   * ------------------------------------------------------------------- */

  function handleSignatureChosen(app, scope, file) {
    if (!file) return;
    var fileRef = utils.generateId("sig");
    fileStore.put(fileRef, file);
    if (scope === "invitation") {
      global.KhannaState.updateApplication(app.id, { invitation: { signatureFileRef: fileRef, signatureFileName: file.name } }, null);
      renderInvitationCard();
    } else if (scope.indexOf("initors:") === 0) {
      var personId = scope.slice("initors:".length);
      var patch = { initorsLetters: { perPerson: {} } };
      patch.initorsLetters.perPerson[personId] = { signatureFileRef: fileRef, signatureFileName: file.name };
      global.KhannaState.updateApplication(app.id, patch, null);
      renderInitorsCard();
    }
  }

  function handleSignatureRemoved(app, scope) {
    if (scope === "invitation") {
      var state = invitationState(app);
      if (state.signatureFileRef) fileStore.remove(state.signatureFileRef);
      global.KhannaState.updateApplication(app.id, { invitation: { signatureFileRef: null, signatureFileName: null } }, null);
      renderInvitationCard();
    } else if (scope.indexOf("initors:") === 0) {
      var personId = scope.slice("initors:".length);
      var entry = perPersonEntry(app, personId);
      if (entry.signatureFileRef) fileStore.remove(entry.signatureFileRef);
      var patch = { initorsLetters: { perPerson: {} } };
      patch.initorsLetters.perPerson[personId] = { signatureFileRef: null, signatureFileName: null };
      global.KhannaState.updateApplication(app.id, patch, null);
      renderInitorsCard();
    }
  }

  /* ---------------------------------------------------------------------
   * Skeleton, wiring
   * ------------------------------------------------------------------- */

  function mountSkeleton() {
    var r = root();
    if (!r) return;
    r.innerHTML =
      '<div class="view-header">' +
      '<div class="view-header__text">' +
      "<h2>Invitation Letter</h2>" +
      "<p>Both letter types below are generated straight from the real Khanna Travels &amp; Holidays reference formats — nothing here is a recreation.</p>" +
      "</div>" +
      "</div>" +
      '<div class="card" data-invitation-card></div>' +
      '<div class="card" data-initors-card></div>';

    utils.on(r, "change", "[data-invitation-invitee]", function (e, target) {
      var app = getApp();
      if (!app) return;
      var state = invitationState(app);
      var ids = (state.selectedInviteeIds || []).slice();
      var personId = target.getAttribute("data-person-id");
      var idx = ids.indexOf(personId);
      if (target.checked) {
        if (idx === -1) {
          if (ids.length >= 2) {
            target.checked = false; // guard, in addition to the disabled attribute
            return;
          }
          ids.push(personId);
        }
      } else if (idx !== -1) {
        ids.splice(idx, 1);
      }
      global.KhannaState.updateApplication(app.id, { invitation: { selectedInviteeIds: ids } }, null);
      renderInvitationCard();
      if (global.KhannaRouter) global.KhannaRouter.refreshWizardFooter();
    });

    utils.on(r, "change", "[data-invitation-field]", function (e, target) {
      var current = getApp();
      if (!current) return;
      var parts = target.getAttribute("data-invitation-field").split(":");
      var scope = parts[0];
      var key = parts[1];
      var patch = { invitation: {} };
      if (scope === "top") {
        patch.invitation[key] = target.value;
      } else {
        patch.invitation[scope] = {};
        patch.invitation[scope][key] = target.value;
      }
      global.KhannaState.updateApplication(current.id, patch, null);
      if (global.KhannaRouter) global.KhannaRouter.refreshWizardFooter();
    });

    utils.on(r, "change", "[data-initors-person]", function (e, target) {
      var app = getApp();
      if (!app) return;
      var state = initorsState(app);
      var ids = (state.selectedPersonIds || []).slice();
      var personId = target.getAttribute("data-person-id");
      var idx = ids.indexOf(personId);
      if (target.checked) {
        if (idx === -1) {
          if (ids.length >= 2) {
            target.checked = false; // guard, in addition to the disabled attribute
            return;
          }
          ids.push(personId);
        }
      } else if (idx !== -1) {
        ids.splice(idx, 1);
      }
      global.KhannaState.updateApplication(app.id, { initorsLetters: { selectedPersonIds: ids } }, null);
      renderInitorsCard();
      if (global.KhannaRouter) global.KhannaRouter.refreshWizardFooter();
    });

    utils.on(r, "change", "[data-initors-field]", function (e, target) {
      var current = getApp();
      if (!current) return;
      var parts = target.getAttribute("data-initors-field").split(":");
      var scope = parts[0];
      var key = parts[1];
      var patch = { initorsLetters: {} };
      if (scope === "top") {
        patch.initorsLetters[key] = target.value;
      } else if (scope === "inviting") {
        patch.initorsLetters.invitingPerson = {};
        patch.initorsLetters.invitingPerson[key] = target.value;
      }
      global.KhannaState.updateApplication(current.id, patch, null);
      if (global.KhannaRouter) global.KhannaRouter.refreshWizardFooter();
    });

    utils.on(r, "change", "[data-initors-person-field]", function (e, target) {
      var current = getApp();
      if (!current) return;
      var attr = target.getAttribute("data-initors-person-field");
      var sep = attr.indexOf(":");
      var personId = attr.slice(0, sep);
      var key = attr.slice(sep + 1);
      var patch = { initorsLetters: { perPerson: {} } };
      patch.initorsLetters.perPerson[personId] = {};
      patch.initorsLetters.perPerson[personId][key] = target.value;
      global.KhannaState.updateApplication(current.id, patch, null);
      if (global.KhannaRouter) global.KhannaRouter.refreshWizardFooter();
    });

    utils.on(r, "click", "[data-action='upload-signature']", function (e, target) {
      var scope = target.getAttribute("data-scope");
      var input = utils.qs('[data-signature-file-input="' + scope + '"]', r);
      if (input) input.click();
    });

    utils.on(r, "change", "[data-signature-file-input]", function (e, target) {
      var app = getApp();
      if (!app) return;
      var scope = target.getAttribute("data-signature-file-input");
      if (target.files && target.files[0]) handleSignatureChosen(app, scope, target.files[0]);
    });

    utils.on(r, "click", "[data-action='remove-signature']", function (e, target) {
      var app = getApp();
      if (!app) return;
      handleSignatureRemoved(app, target.getAttribute("data-scope"));
    });

    utils.on(r, "click", "[data-action='generate-invitation']", function (e, target) {
      if (target.disabled) return;
      generateInvitation(target.getAttribute("data-format"), target);
    });

    utils.on(r, "click", "[data-action='generate-initors']", function (e, target) {
      if (target.disabled) return;
      generateInitors(target.getAttribute("data-person-id"), target.getAttribute("data-format"), target);
    });
  }

  function render() {
    var r = root();
    if (!r) return;
    // Same reasoning as hotels.js's own render(): the wizard is never
    // entered without an active application, so this only ever matters for
    // the standalone Invitation Letter page, which can be opened directly
    // with none yet. Left unmounted (not dataset.mounted) so the real
    // skeleton still mounts the next time render() runs with an
    // application active.
    if (!getApp()) {
      // See hotels.js's own render() for why this also clears a stale
      // dataset.mounted flag, not just the placeholder text.
      delete r.dataset.mounted;
      r.innerHTML = '<p class="field-hint">Create or continue an application above to start an invitation letter.</p>';
      return;
    }
    if (!r.dataset.mounted) {
      r.dataset.mounted = "1";
      mountSkeleton();
    }
    renderInvitationCard();
    renderInitorsCard();
    if (global.KhannaRouter) global.KhannaRouter.refreshWizardFooter();
  }

  function init() {
    if (global.KhannaRouter) global.KhannaRouter.registerStepValidator("new-application", 7, isStep7Complete);

    document.addEventListener("khanna:navigate", function (e) {
      if (e.detail.view === "new-application" || e.detail.view === "invitation-letter") render();
    });

    // Only the two checklists + every generate bar react to every
    // background state change — never the free-text fields or the
    // per-person Initors sub-sections themselves (see file header).
    global.KhannaState.subscribe(function () {
      var r = root();
      if (!r || !r.dataset.mounted) return;
      var app = getApp();
      refreshInviteeChecklist();
      refreshInvitationGenerateBar();
      refreshInvitationReadiness();
      var initorsChecklistBox = utils.qs("[data-initors-checklist]", r);
      if (app && initorsChecklistBox) initorsChecklistBox.innerHTML = initorsPersonChecklistHtml(app);
      if (app) {
        selectedInitorsPeople(app).forEach(function (p) {
          var bar = utils.qs('[data-initors-generate-bar="' + p.id + '"]', r);
          if (bar) bar.innerHTML = personGenerateBarHtml(p.id, initorsPersonReadyToGenerate(app, p), perPersonEntry(app, p.id).generatedAt);
        });
      }
      if (global.KhannaRouter) global.KhannaRouter.refreshWizardFooter();
    });

    if (location.hash.indexOf("new-application") !== -1 || location.hash.indexOf("invitation-letter") !== -1) render();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})(window);
