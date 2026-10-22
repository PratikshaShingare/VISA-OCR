/* ==========================================================================
   Khanna Travels & Holidays — Cover & Authorization (wizard step 6)
   This module builds the "Authorization Letters" tab (Passport
   Authorization + Company Authorization), each calling the real backend
   engine (backend/python/authorization_letter_engine.py) to produce the
   actual company letter from the real, unmodified reference template
   (project rule 5) — not a recreation. The sibling "Cover Letter" tab
   (Europe/Japan/Singapore, Phase 9) is a separate module, js/cover-letter.js
   — this file only owns the mount point for it inside mountSkeleton() below
   and the combined step-6 "Continue" gate (isStep6Complete), which asks
   both modules whether they're ready.

   Passport Authorization is intentionally capped at 1-2 selected people:
   the two real reference letters on file cover exactly those cases (a
   single traveller, or a traveller + spouse/companion), and there is no
   reference example for a group of 3+ to build from — offering more would
   mean inventing a document design that doesn't exist (project rule 9).
   Company Authorization has no such cap; its template's one applicant line
   is cloned once per selected person.

   Re-render discipline: the person checklist and the Generate bar (no
   persistent text input in either) redraw freely on every KhannaState
   change, same as hotels.js's card list. The recipient/collector TEXT
   FIELDS are only re-synced from state when this step is freshly entered
   (a "khanna:navigate" event) — never on a background state notification —
   so a staff member's in-progress typing is never overwritten out from
   under them.
   ========================================================================== */
(function (global) {
  "use strict";

  var utils = global.KhannaUtils;
  var api = global.KhannaApi;

  var activeAuthTab = "authorization"; // "authorization" | "cover"

  function root() {
    return utils.qs("[data-authorization-step-root]");
  }

  // Document-first redesign (Phase 2): unlike hotels.js/cover-letter.js/
  // invitation.js, this module's wizard root always holds BOTH document
  // types (Passport Authorization and Company Authorization) in one tabbed
  // panel — but the standalone pages are one document type each, so a
  // single root()-style function can't serve every lookup here. Instead,
  // every group-scoped lookup (renderPassportCard/renderCompanyCard/
  // refreshChecklist/refreshGenerateBar/refreshReadinessNotice/showAuthError)
  // is changed to go through activeGroupRoot(group) below instead of the
  // bare root() above; root() itself is untouched and still means "the
  // wizard's shared step-6 root", so nothing about the wizard's own
  // behaviour changes.
  function standaloneRoot(group) {
    return utils.qs(group === "passport" ? "[data-passport-authorization-page-root]" : "[data-company-authorization-page-root]");
  }

  function activeGroupRoot(group) {
    var view = global.KhannaRouter ? global.KhannaRouter.parseHash().view : null;
    var standaloneView = group === "passport" ? "passport-authorization" : "company-authorization";
    if (view === standaloneView) return standaloneRoot(group);
    return root();
  }

  function getApp() {
    return global.KhannaState.getActiveApplication();
  }

  /* ---------------------------------------------------------------------
   * Person resolution — applicant + every traveller, flattened to the
   * shape this view (and the API payloads below) actually needs.
   * ------------------------------------------------------------------- */

  function toPersonRow(person, id, isApplicant, relationLabel) {
    var passportCurrent = (person.passport && person.passport.current) || {};
    return {
      id: id,
      isApplicant: !!isApplicant,
      relationLabel: relationLabel,
      relation: person.relation || "",
      salutation: person.salutation || "",
      fullName: person.fullName || "",
      sex: person.sex || "",
      passportNumber: passportCurrent.number || "",
      // Only Cover Letters (Phase 9) need these two — harmless to include
      // for every caller rather than keeping a second, near-identical
      // person-row builder in cover-letter.js (project rule 15).
      placeOfIssue: passportCurrent.issuePlace || "",
      passportIssueDate: passportCurrent.issueDate || "",
      phone: (person.contact && person.contact.phone) || "",
      email: (person.contact && person.contact.email) || "",
    };
  }

  function getSelectablePeople(app) {
    var list = [];
    if (app.applicant) {
      list.push(toPersonRow(app.applicant, "applicant", true, "Main applicant"));
    }
    (app.travellers || []).forEach(function (t) {
      list.push(toPersonRow(t, t.id, false, t.relation || "Traveller"));
    });
    return list;
  }

  function personDisplayName(p) {
    var sal = p.salutation ? p.salutation + ". " : "";
    return (sal + p.fullName).trim() || "Unnamed";
  }

  function personHasCoreFields(p) {
    return !!(p.fullName && p.fullName.trim() && p.passportNumber && p.passportNumber.trim());
  }

  function orderPeopleForLetter(people) {
    var applicants = people.filter(function (p) { return p.isApplicant; });
    var others = people.filter(function (p) { return !p.isApplicant; });
    return applicants.length ? applicants.concat(others) : people.slice();
  }

  function authState(app, group) {
    return (app.authorization && app.authorization[group]) || {};
  }

  /* ---------------------------------------------------------------------
   * Frontend rework, Phase E — "group of applicants" (Company
   * Authorization Letter only, as explicitly requested). This letter's
   * own generator (backend/python/authorization_letter_engine.py's
   * compose_company_editable_fields / _company_applicant_line_text) only
   * ever reads an applicant's fullName + passportNumber, so a person
   * doesn't need to be a fully onboarded traveller on this application
   * (with OCR'd passport data) just to be listed on this one letter — they
   * can be added here directly by those two fields alone. These "manual
   * applicants" live in company state, get folded into the same
   * checklist/selection machinery as real travellers via getCompanyPeople()
   * below, and can be saved as a named, reusable group
   * (js/applicant-groups.js) to avoid re-picking the same people on a
   * later application/tab.
   * ------------------------------------------------------------------- */

  function manualApplicantsFor(app) {
    return authState(app, "company").manualApplicants || [];
  }

  function manualApplicantRow(m) {
    return {
      id: m.id,
      isApplicant: false,
      isManual: true,
      relationLabel: "Manually added",
      relation: "",
      salutation: "",
      fullName: m.fullName || "",
      sex: "",
      passportNumber: m.passportNumber || "",
      placeOfIssue: "",
      passportIssueDate: "",
      phone: "",
      email: "",
    };
  }

  // Only the Company Authorization checklist/selection needs the manual
  // applicants folded in — Passport Authorization keeps using
  // getSelectablePeople(app) exactly as before (it still requires a real,
  // fully onboarded traveller, matching its own two fixed reference
  // letters — project rule 9, not extended here beyond what was asked).
  function getCompanyPeople(app) {
    return getSelectablePeople(app).concat(manualApplicantsFor(app).map(manualApplicantRow));
  }

  /* ---------------------------------------------------------------------
   * Editable preview — the letter's values are edited directly on the real
   * preview page (Edit button, js/document-viewer.js), never in a separate
   * "wording" form. Edits are stored per letter in
   * app.authorization.<group>.editedFields ({fieldKey: html}), the shape the
   * backend's replace_paragraph_range_with_html already consumes. The field
   * keys are the backend's: Passport — date, recipientCentre,
   * recipientAddress, applicantSentence, collectorSentence; Company — date,
   * recipient and one "applicant_<index>" per selected applicant.
   * ------------------------------------------------------------------- */

  var AUTH_FIELD_LABELS = {
    date: "letter date",
    recipientCentre: "visa application centre",
    recipientAddress: "centre address",
    applicantSentence: "authorization sentence",
    collectorSentence: "collector authorization sentence",
    recipient: "consulate name and address",
  };

  function authFieldLabel(key) {
    if (key.indexOf("applicant_") === 0) return "applicant line " + (parseInt(key.slice(10), 10) + 1);
    return AUTH_FIELD_LABELS[key] || key;
  }

  function makeAuthorizationEditor(group) {
    return global.KhannaPreviewEditor.createForDocument({
      getEditedFields: function () {
        var currentApp = getApp();
        return currentApp ? authState(currentApp, group).editedFields : null;
      },
      // The auto-generated wording each value would have WITHOUT edits, from
      // the real generator (so a value opens showing what the page printed).
      composeFields: function () {
        var currentApp = getApp();
        var state = authState(currentApp, group);
        var selected = selectedPeopleFor(currentApp, group);
        if (group === "passport") {
          return api
            .composePassportFields({
              people: orderPeopleForLetter(selected).map(personToPassportPayload),
              recipientCentreName: state.recipientCentreName || "",
              recipientAddress: state.recipientAddress || "",
              collectorName: state.collectorName || "",
            })
            .then(function (res) { return (res && res.fields) || {}; });
        }
        return api
          .composeCompanyFields({
            people: selected.map(personToCompanyPayload),
            recipientText: state.recipientText || "",
          })
          .then(function (res) { return (res && res.fields) || {}; });
      },
      onFieldChange: function (key, html) {
        var currentApp = getApp();
        if (!currentApp) return;
        var groupPatch = { editedFields: {} };
        groupPatch.editedFields[key] = html; // null clears the override
        var patch = { authorization: {} };
        patch.authorization[group] = groupPatch;
        global.KhannaState.updateApplication(currentApp.id, patch, null);
      },
      fieldLabel: authFieldLabel,
    });
  }

  function selectedPeopleFor(app, group) {
    var state = authState(app, group);
    var ids = state.selectedPersonIds || [];
    var pool = group === "company" ? getCompanyPeople(app) : getSelectablePeople(app);
    return pool.filter(function (p) {
      return ids.indexOf(p.id) !== -1;
    });
  }

  /* ---------------------------------------------------------------------
   * Readiness (mirrors hotels.js's isHotelComplete-style gating)
   * ------------------------------------------------------------------- */

  function passportReadiness(app) {
    var state = authState(app, "passport");
    var selected = selectedPeopleFor(app, "passport");
    return (
      selected.length >= 1 &&
      selected.length <= 2 &&
      selected.every(personHasCoreFields) &&
      !!(state.recipientCentreName && state.recipientCentreName.trim()) &&
      !!(state.collectorName && state.collectorName.trim())
    );
  }

  function companyReadiness(app) {
    var state = authState(app, "company");
    var selected = selectedPeopleFor(app, "company");
    return selected.length >= 1 && selected.every(personHasCoreFields) && !!(state.recipientText && state.recipientText.trim());
  }

  // Step 6's "Continue" gate covers BOTH tabs on this step — registered in
  // init() below as isStep6Complete(), once Phase 9's Cover Letter tab
  // (cover-letter.js) exists to ask about too. Matches hotels.js's own
  // isStepComplete precedent: gates on the underlying DATA being complete
  // enough to generate every one of this step's real documents, not on
  // whether a staff member has actually clicked "Generate" yet.
  function isStep6Complete() {
    var app = getApp();
    if (!app) return false;
    var coverOk = !!(global.KhannaCoverLetter && global.KhannaCoverLetter.isReady(app));
    return passportReadiness(app) && companyReadiness(app) && coverOk;
  }

  /* ---------------------------------------------------------------------
   * Rendering — checklist
   * ------------------------------------------------------------------- */

  function personRowHtml(p, selectedIds, group, maxCount) {
    var checked = selectedIds.indexOf(p.id) !== -1;
    var atMax = !!maxCount && !checked && selectedIds.length >= maxCount;
    var incomplete = !personHasCoreFields(p);
    return (
      '<label class="auth-person-row' + (atMax ? " is-disabled" : "") + '">' +
      '<input type="checkbox" data-auth-person="' + group + '" data-person-id="' + utils.escapeHtml(p.id) + '"' +
      (checked ? " checked" : "") +
      (atMax ? " disabled" : "") +
      " />" +
      '<span class="auth-person-row__name">' + utils.escapeHtml(personDisplayName(p)) + "</span>" +
      '<span class="auth-person-row__meta">' +
      utils.escapeHtml(p.relationLabel) +
      (incomplete ? " · missing name or passport number" : "") +
      "</span>" +
      "</label>"
    );
  }

  function checklistHtml(people, selectedIds, group, maxCount) {
    // The application's blank applicant placeholder (no name, no passport) is
    // never listed as an "Unnamed" row — same as the Cover Letter page.
    people = people.filter(function (p) { return p.isManual || savedDetails().hasNameOrPassport(p); });
    if (!people.length) {
      return isStandaloneGroup(group)
        ? '<p class="field-hint">No people on this application yet — choose “Use Existing Details” → Passport above, or add them on Upload Passport / Travellers.</p>'
        : '<p class="field-hint">Add the applicant and/or travellers in earlier steps first.</p>';
    }
    return people
      .map(function (p) {
        var rowHtml = personRowHtml(p, selectedIds, group, maxCount);
        // A manually-added applicant (Company Authorization's "group of
        // applicants" feature) can be deleted outright, not just
        // unchecked — its own remove button has to sit OUTSIDE the
        // <label>, as a sibling, not a nested descendant: a click
        // anywhere inside a <label> — including on a nested <button> —
        // also toggles that label's own checkbox (confirmed live), which
        // would silently re-check/uncheck the row every time "remove"
        // was clicked. Every other row (a real traveller) is untouched,
        // still the same bare <label> as before.
        if (!p.isManual) return rowHtml;
        return (
          '<div class="auth-person-row-wrap">' +
          rowHtml +
          '<button type="button" class="btn-icon" data-action="remove-manual-applicant" data-person-id="' +
          utils.escapeHtml(p.id) +
          '" aria-label="Remove ' +
          utils.escapeHtml(personDisplayName(p)) +
          '" title="Remove this manually-added applicant">' +
          '<svg class="icon icon-sm" viewBox="0 0 24 24"><path d="M18 6 6 18M6 6l12 12"/></svg></button>' +
          "</div>"
        );
      })
      .join("");
  }

  function refreshChecklist(group, maxCount) {
    var app = getApp();
    var box = utils.qs('[data-auth-checklist="' + group + '"]', activeGroupRoot(group));
    if (!app || !box) return;
    var state = authState(app, group);
    var pool = group === "company" ? getCompanyPeople(app) : getSelectablePeople(app);
    box.innerHTML = checklistHtml(pool, state.selectedPersonIds || [], group, maxCount);
  }

  /* ---------------------------------------------------------------------
   * Rendering — generate bar + readiness notice
   * ------------------------------------------------------------------- */

  function generateBarHtml(group, ready, generatedAt) {
    return (
      '<div class="hotel-generate-bar">' +
      '<button class="btn btn-primary btn-sm" type="button" data-action="generate-authorization" data-group="' +
      group +
      '"' +
      (ready ? "" : " disabled") +
      ">Generate &amp; Preview</button>" +
      (generatedAt ? '<span class="hotel-generate-bar__meta">Last generated ' + utils.formatDate(generatedAt) + "</span>" : "") +
      "</div>"
    );
  }

  function refreshGenerateBar(group) {
    var app = getApp();
    var box = utils.qs('[data-generate-bar="' + group + '"]', activeGroupRoot(group));
    if (!app || !box) return;
    var ready = group === "passport" ? passportReadiness(app) : companyReadiness(app);
    var state = authState(app, group);
    box.innerHTML = generateBarHtml(group, ready, state.generatedAt);
  }

  function refreshReadinessNotice(group, message) {
    var app = getApp();
    var box = utils.qs('[data-auth-readiness="' + group + '"]', activeGroupRoot(group));
    if (!app || !box) return;
    var ready = group === "passport" ? passportReadiness(app) : companyReadiness(app);
    box.innerHTML = ready
      ? ""
      : '<div class="notice notice-warning">' +
        '<svg class="icon icon-sm" viewBox="0 0 24 24"><path d="M12 9v4M12 17h.01"/><circle cx="12" cy="12" r="9"/></svg>' +
        "<span>" + utils.escapeHtml(message) + "</span>" +
        "</div>";
  }

  function showAuthError(group, message) {
    var box = utils.qs('[data-auth-error="' + group + '"]', activeGroupRoot(group));
    if (!box) return;
    box.innerHTML = message
      ? '<div class="notice notice-danger">' +
        '<svg class="icon icon-sm" viewBox="0 0 24 24"><path d="M12 9v4M12 17h.01"/><circle cx="12" cy="12" r="9"/></svg>' +
        "<span>" + utils.escapeHtml(message) + "</span>" +
        "</div>"
      : "";
  }

  /* ---------------------------------------------------------------------
   * "Use Existing Details ▾" (standalone Passport / Company Authorization
   * pages only) — replaces the removed "Use Existing Applicant" top-bar
   * button (document-workspace.js's VIEW_BUTTON_CONFIG), same two-box
   * dropdown as the Cover Letter and Invitation pages: the kind of detail on
   * the left, a scrollable list of saved ones on the right. These letters
   * carry no hotel or trip dates, so the only kind offered is Passport (an
   * option that could not fill anything would be decorative — project
   * rule 9). The saved list comes from js/saved-details.js, shared with the
   * other pages. A passport saved on another application (or in the saved
   * profile pool) is first copied onto the active application as a
   * traveller — the source is never changed — then ticked on this letter.
   * ------------------------------------------------------------------- */

  function isStandaloneGroup(group) {
    var r = activeGroupRoot(group);
    return !!r && r !== root();
  }

  function savedDetails() {
    return global.KhannaSavedDetails;
  }

  function useExistingHtml(group) {
    if (!isStandaloneGroup(group)) return "";
    return (
      '<div class="cover-use-existing" data-auth-use-existing="' + group + '">' +
      '<button type="button" class="btn btn-secondary btn-sm" data-auth-use-existing-toggle aria-haspopup="true" aria-expanded="false">' +
      "Use Existing Details " +
      '<span aria-hidden="true">&#9662;</span>' +
      "</button>" +
      '<div class="cover-existing-panel" data-auth-use-existing-dropdown>' +
      '<div class="cover-existing-menu" role="menu">' +
      '<button type="button" class="cover-existing-menu__item" role="menuitem" data-auth-use-existing-option="passport">Passport <span aria-hidden="true">&#9656;</span></button>' +
      "</div>" +
      '<div class="cover-existing-list" data-auth-existing-list hidden></div>' +
      "</div>" +
      "</div>" +
      '<div class="cover-existing-status" data-auth-existing-status role="status" aria-live="polite" hidden></div>'
    );
  }

  function closeUseExistingMenus() {
    ["passport", "company"].forEach(function (g) {
      var r = standaloneRoot(g);
      if (!r) return;
      utils.qsa("[data-auth-use-existing-dropdown]", r).forEach(function (dd) { dd.classList.remove("is-open"); });
      utils.qsa("[data-auth-use-existing-toggle]", r).forEach(function (t) { t.setAttribute("aria-expanded", "false"); });
    });
  }

  function setExistingStatus(group, message, isWarning) {
    var box = utils.qs("[data-auth-existing-status]", activeGroupRoot(group));
    if (!box) return;
    box.hidden = !message;
    box.classList.toggle("is-warning", !!isWarning);
    box.textContent = message || "";
  }

  function usePassportFromSource(group, key) {
    var app = getApp();
    if (!app) return;
    var src = savedDetails().passportSources().filter(function (s) { return s.key === key; })[0];
    if (!src) return;
    var state = authState(app, group);
    var ids = (state.selectedPersonIds || []).slice();
    var name = personDisplayName(src.row);
    var pool = group === "company" ? getCompanyPeople(app) : getSelectablePeople(app);

    var existing = pool.filter(function (p) { return !p.isManual && savedDetails().samePassportPerson(p, src); })[0];
    if (existing && ids.indexOf(existing.id) !== -1) {
      setExistingStatus(group, name + " is already selected on this letter.", true);
      return;
    }
    if (group === "passport" && ids.length >= 2) {
      setExistingStatus(group, "This letter takes 1 or 2 people. Untick one below before adding another.", true);
      return;
    }
    var id = existing ? existing.id : savedDetails().addSavedPersonAsTraveller(app, src);
    ids.push(id);
    var patch = { authorization: {} };
    patch.authorization[group] = selectionPatch(state, group, ids);
    global.KhannaState.updateApplication(app.id, patch, null);
    setExistingStatus(
      group,
      "Selected " + name + " (from " + src.appLabel + ")." +
        (existing ? "" : " They were also added to this application as a traveller.") +
        (src.row.passportNumber ? "" : " No passport number is saved for this person — add it on their passport page before generating."),
      !src.row.passportNumber
    );
  }

  var useExistingDocHandlersWired = false;
  function wireUseExistingHandlers(r) {
    utils.on(r, "click", "[data-auth-use-existing-toggle]", function (e, target) {
      e.stopPropagation();
      var wrap = target.closest("[data-auth-use-existing]");
      var dd = wrap && utils.qs("[data-auth-use-existing-dropdown]", wrap);
      if (!dd) return;
      var willOpen = !dd.classList.contains("is-open");
      closeUseExistingMenus();
      dd.classList.toggle("is-open", willOpen);
      if (willOpen) {
        dd.classList.remove("has-list");
        var list = utils.qs("[data-auth-existing-list]", wrap);
        if (list) list.hidden = true;
        utils.qsa("[data-auth-use-existing-option]", wrap).forEach(function (b) { b.classList.remove("is-active"); });
      }
      target.setAttribute("aria-expanded", willOpen ? "true" : "false");
    });
    utils.on(r, "click", "[data-auth-use-existing-option]", function (e, target) {
      e.stopPropagation();
      var wrap = target.closest("[data-auth-use-existing]");
      var list = wrap && utils.qs("[data-auth-existing-list]", wrap);
      if (!list) return;
      utils.qsa("[data-auth-use-existing-option]", wrap).forEach(function (b) { b.classList.toggle("is-active", b === target); });
      list.innerHTML = savedDetails().listHtml(target.getAttribute("data-auth-use-existing-option"), "data-auth-existing-pick");
      list.hidden = false;
      var dd = utils.qs("[data-auth-use-existing-dropdown]", wrap);
      if (dd) dd.classList.add("has-list");
    });
    utils.on(r, "click", "[data-auth-existing-pick]", function (e, target) {
      var wrap = target.closest("[data-auth-use-existing]");
      var group = wrap && wrap.getAttribute("data-auth-use-existing");
      if (!group) return;
      closeUseExistingMenus();
      usePassportFromSource(group, target.getAttribute("data-passport-key"));
    });
    if (!useExistingDocHandlersWired) {
      useExistingDocHandlersWired = true;
      document.addEventListener("click", function (e) {
        if (e.target.closest && e.target.closest("[data-auth-use-existing]")) return;
        closeUseExistingMenus();
      });
      document.addEventListener("keydown", function (e) {
        if (e.key === "Escape") closeUseExistingMenus();
      });
    }
  }

  /* ---------------------------------------------------------------------
   * Rendering — "group of applicants" (Company Authorization Letter only)
   * ------------------------------------------------------------------- */

  function manualApplicantFormHtml() {
    return (
      '<div class="auth-manual-applicant-form">' +
      '<input type="text" data-manual-applicant-field="fullName" placeholder="Full name" aria-label="New applicant full name" />' +
      '<input type="text" data-manual-applicant-field="passportNumber" placeholder="Passport number" aria-label="New applicant passport number" />' +
      '<button type="button" class="btn btn-secondary btn-sm" data-action="add-manual-applicant">+ Add applicant (name &amp; passport only)</button>' +
      "</div>"
    );
  }

  function companyGroupToolbarHtml(app) {
    var groups = global.KhannaApplicantGroups ? global.KhannaApplicantGroups.groupsFor(app) : [];
    // Deliberately NOT a "change" handler that applies the group the
    // instant it's picked: applying a group replaces the current
    // selection and rebuilds this whole card (see onApplyApplicantGroupClick),
    // which would reset the <select> back to blank before a staff member
    // could ever follow up with "now delete this one" — picking a group
    // here only decides which one "Apply"/"Delete" act on next.
    var usePart = !groups.length
      ? ""
      : '<div class="auth-group-toolbar__field">' +
        '<label for="auth-company-use-group">Saved groups</label>' +
        '<select id="auth-company-use-group" data-action="pick-applicant-group">' +
        '<option value="">Choose a group…</option>' +
        groups
          .map(function (g) {
            return (
              '<option value="' + utils.escapeHtml(g.id) + '">' +
              utils.escapeHtml(g.name) +
              " (" + g.members.length + (g.members.length === 1 ? " person" : " people") + ")" +
              "</option>"
            );
          })
          .join("") +
        "</select>" +
        '<button type="button" class="btn btn-secondary btn-sm" data-action="apply-applicant-group">Apply</button>' +
        '<button type="button" class="btn-icon" data-action="delete-applicant-group" aria-label="Delete the selected saved group" title="Delete the selected saved group">' +
        '<svg class="icon icon-sm" viewBox="0 0 24 24"><path d="M18 6 6 18M6 6l12 12"/></svg></button>' +
        "</div>";
    return (
      '<div class="auth-group-toolbar" data-auth-group-toolbar="company">' +
      usePart +
      '<div class="auth-group-toolbar__field">' +
      '<input type="text" data-group-name-input placeholder="Name this selection as a group" aria-label="New group name" />' +
      '<button type="button" class="btn btn-secondary btn-sm" data-action="save-applicant-group">Save selection as group</button>' +
      "</div>" +
      "</div>"
    );
  }

  /* ---------------------------------------------------------------------
   * Rendering — the two cards (full rebuild, incl. field values; only
   * called on real "entering this step" moments, never on background
   * state notifications — see file header)
   * ------------------------------------------------------------------- */

  function fieldRowHtml(group, key, label, value, required, placeholder) {
    var id = "auth-" + group + "-" + key;
    return (
      '<div class="field">' +
      '<label for="' + id + '">' + utils.escapeHtml(label) + (required ? " *" : "") + "</label>" +
      '<input type="text" id="' + id + '" data-auth-field="' + group + ":" + key + '"' +
      (placeholder ? ' placeholder="' + utils.escapeHtml(placeholder) + '"' : "") +
      ' value="' + utils.escapeHtml(value || "") + '" />' +
      "</div>"
    );
  }

  // Company Authorization's recipient: pick the consulate's COUNTRY and the
  // wording completes itself ("The Consulate General of Japan"), with the
  // address on the next line (defaults to Mumbai, India — editable).
  function consulateFieldsHtml(state) {
    var C = global.KhannaConsulate;
    var country = state.consulateCountry || "";
    var address = C.addressOrDefault(state.consulateAddress);
    var current = (state.recipientText || "").trim();
    var hint;
    if (country) {
      hint = "On the letter: " + C.composeRecipient(C.consulateName(country), address).replace("\n", " — ");
    } else if (current) {
      hint = "Currently on the letter: " + current.replace(/\n/g, " — ");
    } else {
      hint = "";
    }
    return (
      C.comboHtml({ key: "company", id: "auth-company-consulateCountry", label: "Consulate country", value: country, required: true }) +
      fieldRowHtml("company", "consulateAddress", "Address of Consulate", address, false, "e.g. Mumbai, India") +
      '<p class="field-hint" data-consulate-hint style="grid-column:1/-1;margin:0;">' + utils.escapeHtml(hint) + "</p>"
    );
  }

  function renderPassportCard(app) {
    var r = activeGroupRoot("passport");
    var box = utils.qs("[data-passport-auth-card]", r);
    if (!box) return;
    var state = authState(app, "passport");
    box.innerHTML =
      "<h3>Passport Authorization Letter</h3>" +
      useExistingHtml("passport") +
      '<div class="auth-person-list" data-auth-checklist="passport"></div>' +
      '<div class="field-grid">' +
      fieldRowHtml("passport", "recipientCentreName", "Visa application centre", state.recipientCentreName, true, "e.g. Germany Visa Application Centre") +
      fieldRowHtml("passport", "recipientAddress", "Centre address", state.recipientAddress, false, "e.g. Andheri, Mumbai") +
      fieldRowHtml("passport", "collectorName", "Collected by (staff name)", state.collectorName, true, "e.g. Mr. Suresh Patil") +
      "</div>" +
      '<div data-auth-readiness="passport"></div>' +
      '<div data-generate-bar="passport"></div>' +
      '<div data-auth-error="passport"></div>' +
      '<div data-doc-preview="passport" style="margin-top:var(--space-4);"></div>';
    refreshChecklist("passport", 2);
    refreshGenerateBar("passport");
    refreshReadinessNotice(
      "passport",
      "Select 1 or 2 travellers (each with a name and passport number on file), and fill the centre and collector fields, to generate this letter."
    );
  }

  function renderCompanyCard(app) {
    var r = activeGroupRoot("company");
    var box = utils.qs("[data-company-auth-card]", r);
    if (!box) return;
    var state = authState(app, "company");
    box.innerHTML =
      "<h3>Company Authorization Letter</h3>" +
      useExistingHtml("company") +
      '<div class="auth-person-list" data-auth-checklist="company"></div>' +
      manualApplicantFormHtml() +
      companyGroupToolbarHtml(app) +
      '<div class="field-grid">' +
      consulateFieldsHtml(state) +
      "</div>" +
      '<div data-auth-readiness="company"></div>' +
      '<div data-generate-bar="company"></div>' +
      '<div data-auth-error="company"></div>' +
      '<div data-doc-preview="company" style="margin-top:var(--space-4);"></div>';
    refreshChecklist("company", null);
    refreshGenerateBar("company");
    refreshReadinessNotice(
      "company",
      "Select at least one applicant (with a name and passport number on file) and choose the consulate country to generate this letter."
    );
  }

  function renderCards() {
    var app = getApp();
    var r = root();
    if (!r || !app) return;
    renderPassportCard(app);
    renderCompanyCard(app);
  }

  /* ---------------------------------------------------------------------
   * Generation
   * ------------------------------------------------------------------- */

  function personToPassportPayload(person, index, ordered) {
    var payload = {
      salutation: person.salutation,
      fullName: person.fullName,
      passportNumber: person.passportNumber,
      sex: person.sex,
      phone: person.phone,
      email: person.email,
      isApplicant: person.isApplicant,
      relationToApplicant: "",
    };
    // Only meaningful (and only sent) when the lead signer really is the
    // main applicant — a `relation` field between two arbitrary travellers
    // isn't real data, so it's never guessed at (project rule 9).
    if (index === 1 && ordered[0] && ordered[0].isApplicant) {
      payload.relationToApplicant = person.relation || "";
    }
    return payload;
  }

  function personToCompanyPayload(person) {
    return { fullName: person.fullName, passportNumber: person.passportNumber };
  }

  // Keyed by group ROOT element (activeGroupRoot(group)), not by "group"
  // string alone — the same group ("passport"/"company") can be mounted
  // simultaneously on the wizard root AND a standalone page root (same
  // dual-mount hazard hotels.js's viewerHandles WeakMap already guards
  // against), so the map key must identify which physical DOM root a
  // handle belongs to.
  var viewerHandles = new WeakMap();

  // The real request for one letter: which download function and which
  // payload. `editedFields` are the staff member's hand edits (made on the
  // preview itself); undefined means "every value auto-generates".
  function authorizationRequest(group, app) {
    var applicantName = [app.applicant.firstName, app.applicant.lastName].filter(Boolean).join(" ") || "Application";
    var state = authState(app, group);
    var selected = selectedPeopleFor(app, group);
    if (group === "passport") {
      return {
        download: api.downloadPassportAuthorization,
        payload: {
          people: orderPeopleForLetter(selected).map(personToPassportPayload),
          recipientCentreName: state.recipientCentreName || "",
          recipientAddress: state.recipientAddress || "",
          collectorName: state.collectorName || "",
          applicantName: applicantName,
          editedFields: state.editedFields || undefined,
        },
      };
    }
    return {
      download: api.downloadCompanyAuthorization,
      payload: {
        people: selected.map(personToCompanyPayload),
        recipientText: state.recipientText || "",
        applicantName: applicantName,
        editedFields: state.editedFields || undefined,
      },
    };
  }

  function buildAuthorizationPayload(group, app, format) {
    var req = authorizationRequest(group, app);
    return req.download(Object.assign({}, req.payload, { format: format }));
  }

  function loadAuthorizationPreview(group, app) {
    var req = authorizationRequest(group, app);
    return api.previewWithLayout(req.download, req.payload);
  }

  function generateAuthorization(group, btn) {
    var app = getApp();
    if (!app) return;
    showAuthError(group, "");
    var r = activeGroupRoot(group);
    if (!r) return;
    var previewBox = utils.qs('[data-doc-preview="' + group + '"]', r);
    if (!previewBox) return;

    var handle = viewerHandles.get(previewBox);
    if (!handle) {
      handle = global.KhannaDocumentViewer.mount(previewBox, {
        title: group === "passport" ? "Passport Authorization Letter" : "Company Authorization Letter",
        editor: makeAuthorizationEditor(group),
        loadPdf: function () {
          return loadAuthorizationPreview(group, getApp());
        },
        loadDocx: function () {
          return buildAuthorizationPayload(group, getApp(), "docx");
        },
        onEdit: function () {
          var box = utils.qs('[data-auth-checklist="' + group + '"]', activeGroupRoot(group));
          if (box) box.scrollIntoView({ behavior: "smooth", block: "start" });
        },
        onRegenerate: function () {
          return Promise.resolve();
        },
      });
      viewerHandles.set(previewBox, handle);
    }

    var originalText = btn.textContent;
    btn.disabled = true;
    btn.textContent = "Generating…";
    handle
      .refresh()
      .then(function () {
        // Previewing from the Dashboard's View icon only re-displays a
        // document — it must not change "Last generated" / "Updated" dates.
        if (global.KhannaRouter && global.KhannaRouter.isPreviewMode()) return;
        var ts = new Date().toISOString();
        var patch = { authorization: {} };
        patch.authorization[group] = { generatedAt: ts };
        var label = group === "passport" ? "Passport Authorization Letter" : "Company Authorization Letter";
        global.KhannaState.updateApplication(app.id, patch, label + " generated");
      })
      .catch(function (err) {
        showAuthError(group, (err && err.message) || "Could not generate the letter.");
      })
      .finally(function () {
        btn.disabled = false;
        btn.textContent = originalText;
      });
  }

  /* ---------------------------------------------------------------------
   * Skeleton, tabs, wiring
   * ------------------------------------------------------------------- */

  function switchTab(tab) {
    activeAuthTab = tab;
    var r = root();
    utils.qsa("[data-auth-tab]", r).forEach(function (btn) {
      btn.classList.toggle("is-active", btn.getAttribute("data-auth-tab") === tab);
    });
    utils.qsa("[data-auth-tab-panel]", r).forEach(function (panel) {
      panel.classList.toggle("is-active", panel.getAttribute("data-auth-tab-panel") === tab);
    });
  }

  function mountSkeleton() {
    var r = root();
    if (!r) return;
    r.innerHTML =
      '<div class="view-header">' +
      '<div class="view-header__text">' +
      "<h2>Cover &amp; Authorization</h2>" +
      "</div>" +
      "</div>" +
      '<div class="auth-tabs" role="tablist">' +
      '<button type="button" class="auth-tab is-active" data-auth-tab="authorization" role="tab">Authorization Letters</button>' +
      '<button type="button" class="auth-tab" data-auth-tab="cover" role="tab">Cover Letter</button>' +
      "</div>" +
      '<div class="auth-tab-panel is-active" data-auth-tab-panel="authorization">' +
      '<div class="card" data-passport-auth-card></div>' +
      '<div class="card" data-company-auth-card></div>' +
      "</div>" +
      '<div class="auth-tab-panel" data-auth-tab-panel="cover">' +
      '<div data-cover-letter-root></div>' +
      "</div>";

    utils.on(r, "click", "[data-auth-tab]", function (e, target) {
      switchTab(target.getAttribute("data-auth-tab"));
    });

    utils.on(r, "change", "[data-auth-person]", onAuthPersonChange);
    utils.on(r, "change", "[data-auth-field]", onAuthFieldChange);
    utils.on(r, "click", "[data-action='generate-authorization']", onGenerateAuthorizationClick);
    wireCompanyGroupHandlers(r);
    global.KhannaConsulate.wire(r, onConsulateCountryChosen);
  }

  // Extracted from mountSkeleton() (Phase 2) so the standalone Passport/
  // Company Authorization pages can wire the exact same handlers onto
  // their own root via mountStandaloneSkeleton() below, instead of a second
  // near-identical copy of this logic (project rule 15). Each handler
  // already reads its `group` from the clicked/changed element's own
  // attribute, so nothing here needs to know which root it was mounted on.
  // The state patch for "these people are now selected on this letter". The
  // Company letter's per-applicant editable fields are keyed by POSITION in
  // the selected list ("applicant_0", "applicant_1", ...), not by a stable
  // person id (see authorization_letter_engine.compose_company_editable_fields)
  // — adding, removing, or reordering a selected applicant changes what each
  // existing positional override would apply to, so every persisted
  // "applicant_*" override is cleared rather than silently reattaching a staff
  // member's edited wording to the WRONG applicant. "date"/"recipient"
  // overrides aren't positional and are left untouched.
  function selectionPatch(state, group, ids) {
    var groupPatch = { selectedPersonIds: ids };
    if (group === "company") {
      var existingEdited = state.editedFields || {};
      var clearPatch = {};
      Object.keys(existingEdited).forEach(function (key) {
        if (key.indexOf("applicant_") === 0) clearPatch[key] = null;
      });
      if (Object.keys(clearPatch).length > 0) groupPatch.editedFields = clearPatch;
    }
    return groupPatch;
  }

  function onAuthPersonChange(e, target) {
    var app = getApp();
    if (!app) return;
    var group = target.getAttribute("data-auth-person");
    var personId = target.getAttribute("data-person-id");
    var state = authState(app, group);
    var ids = (state.selectedPersonIds || []).slice();
    var idx = ids.indexOf(personId);
    if (target.checked) {
      if (idx === -1) {
        if (group === "passport" && ids.length >= 2) {
          target.checked = false; // guard, in addition to the disabled attribute
          return;
        }
        ids.push(personId);
      }
    } else if (idx !== -1) {
      ids.splice(idx, 1);
    }
    var groupPatch = selectionPatch(state, group, ids);
    var patch = { authorization: {} };
    patch.authorization[group] = groupPatch;
    global.KhannaState.updateApplication(app.id, patch, null);
  }

  function onAuthFieldChange(e, target) {
    var app = getApp();
    if (!app) return;
    var parts = target.getAttribute("data-auth-field").split(":");
    var group = parts[0];
    var key = parts[1];
    var patch = { authorization: {} };
    patch.authorization[group] = {};
    patch.authorization[group][key] = target.value;
    if (group === "company" && key === "consulateAddress") {
      // The address is the second line of the recipient: recompose it (and
      // drop any hand edit of that paragraph, which would hide the change).
      var country = authState(app, "company").consulateCountry;
      if (country) {
        var C = global.KhannaConsulate;
        patch.authorization.company.recipientText = C.composeRecipient(C.consulateName(country), target.value);
        patch.authorization.company.editedFields = { recipient: null };
      }
    }
    global.KhannaState.updateApplication(app.id, patch, null);
    if (group === "company" && key === "consulateAddress") refreshConsulateHint();
  }

  function refreshConsulateHint() {
    var app = getApp();
    var hintEl = utils.qs("[data-consulate-hint]", activeGroupRoot("company"));
    if (!app || !hintEl) return;
    var C = global.KhannaConsulate;
    var st = authState(app, "company");
    if (st.consulateCountry) {
      hintEl.textContent = "On the letter: " + C.composeRecipient(C.consulateName(st.consulateCountry), C.addressOrDefault(st.consulateAddress)).replace("\n", " — ");
    }
  }

  function onConsulateCountryChosen(key, country) {
    var app = getApp();
    if (!app || key !== "company") return;
    var C = global.KhannaConsulate;
    var st = authState(app, "company");
    var address = C.addressOrDefault(st.consulateAddress);
    var r = activeGroupRoot("company");
    var addrInput = utils.qs('[data-auth-field="company:consulateAddress"]', r);
    if (addrInput) address = addrInput.value;
    global.KhannaState.updateApplication(
      app.id,
      {
        authorization: {
          company: {
            consulateCountry: country,
            consulateAddress: address,
            recipientText: C.composeRecipient(C.consulateName(country), address),
            editedFields: { recipient: null },
          },
        },
      },
      null
    );
    var hintEl = utils.qs("[data-consulate-hint]", r);
    if (hintEl) refreshConsulateHint();
    refreshGenerateBar("company");
    refreshReadinessNotice(
      "company",
      "Select at least one applicant (with a name and passport number on file) and choose the consulate country to generate this letter."
    );
    if (global.KhannaRouter) global.KhannaRouter.refreshWizardFooter();
  }

  function onGenerateAuthorizationClick(e, target) {
    if (target.disabled) return;
    generateAuthorization(target.getAttribute("data-group"), target);
  }

  /* ---------------------------------------------------------------------
   * Handlers — "group of applicants" (Company Authorization Letter only)
   * ------------------------------------------------------------------- */

  // Company Authorization's per-applicant editable fields are keyed by
  // POSITION (see the editable-preview comment above) — adding,
  // removing or bulk-replacing the selected applicants (every action below
  // does one of these) invalidates any already-persisted "applicant_*"
  // override the same way toggling a single checkbox already does in
  // onAuthPersonChange, so every action here clears them the same way.
  function clearedPositionalEditedFieldsPatch(app) {
    var existingEdited = authState(app, "company").editedFields || {};
    var clearPatch = {};
    Object.keys(existingEdited).forEach(function (key) {
      if (key.indexOf("applicant_") === 0) clearPatch[key] = null;
    });
    return Object.keys(clearPatch).length > 0 ? clearPatch : null;
  }

  function onAddManualApplicantClick(e, target) {
    var app = getApp();
    if (!app) return;
    var r = activeGroupRoot("company");
    if (!r) return;
    var nameInput = utils.qs('[data-manual-applicant-field="fullName"]', r);
    var passportInput = utils.qs('[data-manual-applicant-field="passportNumber"]', r);
    var fullName = nameInput ? nameInput.value.trim() : "";
    var passportNumber = passportInput ? passportInput.value.trim() : "";
    if (!fullName || !passportNumber) {
      showAuthError("company", "Enter both a full name and a passport number to add an applicant.");
      return;
    }
    var state = authState(app, "company");
    var manual = (state.manualApplicants || []).concat([
      { id: utils.generateId("MAN"), fullName: fullName, passportNumber: passportNumber },
    ]);
    var ids = (state.selectedPersonIds || []).concat([manual[manual.length - 1].id]);
    var companyPatch = { manualApplicants: manual, selectedPersonIds: ids };
    var clearedFields = clearedPositionalEditedFieldsPatch(app);
    if (clearedFields) companyPatch.editedFields = clearedFields;
    global.KhannaState.updateApplication(app.id, { authorization: { company: companyPatch } }, 'Applicant "' + fullName + '" added to the Company Authorization Letter');
    renderCompanyCard(getApp());
  }

  function onRemoveManualApplicantClick(e, target) {
    e.preventDefault(); // this button sits inside checklistHtml()'s own row wrapper — never let it fall through to a native label click on a sibling checkbox
    var app = getApp();
    if (!app) return;
    var personId = target.getAttribute("data-person-id");
    var state = authState(app, "company");
    var manual = (state.manualApplicants || []).filter(function (m) { return m.id !== personId; });
    var ids = (state.selectedPersonIds || []).filter(function (id) { return id !== personId; });
    var companyPatch = { manualApplicants: manual, selectedPersonIds: ids };
    var clearedFields = clearedPositionalEditedFieldsPatch(app);
    if (clearedFields) companyPatch.editedFields = clearedFields;
    global.KhannaState.updateApplication(app.id, { authorization: { company: companyPatch } }, null);
    renderCompanyCard(getApp());
  }

  function onSaveApplicantGroupClick(e, target) {
    var app = getApp();
    if (!app || !global.KhannaApplicantGroups) return;
    var r = activeGroupRoot("company");
    var nameInput = r && utils.qs("[data-group-name-input]", r);
    var name = nameInput ? nameInput.value.trim() : "";
    if (!name) {
      showAuthError("company", "Enter a name for this group before saving.");
      return;
    }
    var selected = selectedPeopleFor(app, "company");
    if (!selected.length) {
      showAuthError("company", "Select at least one applicant above before saving a group.");
      return;
    }
    var group = global.KhannaApplicantGroups.saveGroup(app.id, name, selected);
    if (!group) {
      showAuthError("company", "Every selected applicant needs both a name and a passport number to be saved into a group.");
      return;
    }
    renderCompanyCard(getApp());
  }

  function onApplyApplicantGroupClick(e, target) {
    var app = getApp();
    if (!app || !global.KhannaApplicantGroups) return;
    var r = activeGroupRoot("company");
    var select = r && utils.qs("[data-action='pick-applicant-group']", r);
    var groupId = select ? select.value : "";
    if (!groupId) {
      showAuthError("company", "Choose a saved group from the dropdown first, then click Apply.");
      return;
    }
    var group = global.KhannaApplicantGroups.groupsFor(app).filter(function (g) { return g.id === groupId; })[0];
    if (!group) return;
    // Replaces the CURRENT Company Authorization selection with the
    // group's own members. A member who matches an existing real
    // traveller by name + passport number is pointed back at that
    // traveller's own stable id (so they stay a real traveller, not
    // turned into a duplicate manual copy); anyone else in the group
    // becomes a manual applicant here, in the same {fullName,
    // passportNumber}-only shape a group is built from.
    var existingPeople = getSelectablePeople(app);
    var manual = [];
    var ids = [];
    group.members.forEach(function (m) {
      var existing = existingPeople.filter(function (p) {
        return p.fullName === m.fullName && p.passportNumber === m.passportNumber;
      })[0];
      if (existing) {
        ids.push(existing.id);
      } else {
        var entry = { id: utils.generateId("MAN"), fullName: m.fullName, passportNumber: m.passportNumber };
        manual.push(entry);
        ids.push(entry.id);
      }
    });
    var companyPatch = { manualApplicants: manual, selectedPersonIds: ids };
    var clearedFields = clearedPositionalEditedFieldsPatch(app);
    if (clearedFields) companyPatch.editedFields = clearedFields;
    global.KhannaState.updateApplication(
      app.id,
      { authorization: { company: companyPatch } },
      'Applicant group "' + group.name + '" applied to the Company Authorization Letter'
    );
    renderCompanyCard(getApp());
  }

  function onDeleteApplicantGroupClick(e, target) {
    var app = getApp();
    if (!app || !global.KhannaApplicantGroups) return;
    var r = activeGroupRoot("company");
    var select = r && utils.qs("[data-action='pick-applicant-group']", r);
    var groupId = select ? select.value : "";
    if (!groupId) {
      showAuthError("company", "Choose a saved group from the dropdown first, then delete it.");
      return;
    }
    global.KhannaApplicantGroups.deleteGroup(app.id, groupId);
    renderCompanyCard(getApp());
  }

  function wireCompanyGroupHandlers(r) {
    utils.on(r, "click", "[data-action='add-manual-applicant']", onAddManualApplicantClick);
    utils.on(r, "click", "[data-action='remove-manual-applicant']", onRemoveManualApplicantClick);
    utils.on(r, "click", "[data-action='save-applicant-group']", onSaveApplicantGroupClick);
    utils.on(r, "click", "[data-action='apply-applicant-group']", onApplyApplicantGroupClick);
    utils.on(r, "click", "[data-action='delete-applicant-group']", onDeleteApplicantGroupClick);
  }

  // Standalone Passport/Company Authorization pages (Phase 2): a single
  // card for just this group, no tabs, no Cover Letter panel — the wizard's
  // combined tabbed skeleton above is untouched. Reuses renderPassportCard/
  // renderCompanyCard and the three handlers above as-is; only the markup
  // shape and which root it mounts to are different.
  function mountStandaloneSkeleton(group) {
    var r = standaloneRoot(group);
    if (!r) return;
    var cardAttr = group === "passport" ? "data-passport-auth-card" : "data-company-auth-card";
    r.innerHTML = '<div class="card" ' + cardAttr + '></div>';
    utils.on(r, "change", "[data-auth-person]", onAuthPersonChange);
    utils.on(r, "change", "[data-auth-field]", onAuthFieldChange);
    utils.on(r, "click", "[data-action='generate-authorization']", onGenerateAuthorizationClick);
    wireUseExistingHandlers(r);
    if (group === "company") {
      wireCompanyGroupHandlers(r);
      global.KhannaConsulate.wire(r, onConsulateCountryChosen);
    }
  }

  function renderStandalone(group) {
    var r = standaloneRoot(group);
    if (!r) return;
    if (!r.dataset.mounted) {
      r.dataset.mounted = "1";
      mountStandaloneSkeleton(group);
    }
    var app = getApp();
    // Mirrors renderCards()'s own guard below — without it, renderPassportCard/
    // renderCompanyCard reach into authState(app, group) = app.authorization,
    // which throws on a null app. renderCards() (the wizard's own entry
    // point) never hits this because the wizard can't be entered without an
    // active application already existing; a standalone page can be opened
    // directly with none yet, so this path needs its own guard. When there
    // is none, the card stays the empty shell mountStandaloneSkeleton() just
    // built — document-workspace.js's app bar is what tells the user to
    // create one, not this card pretending to be usable in the meantime.
    if (!app) return;
    if (group === "passport") renderPassportCard(app);
    else renderCompanyCard(app);
  }

  function render() {
    var r = root();
    if (!r) return;
    if (!r.dataset.mounted) {
      r.dataset.mounted = "1";
      mountSkeleton();
    }
    switchTab(activeAuthTab);
    renderCards();
    if (global.KhannaCoverLetter) global.KhannaCoverLetter.render();
    if (global.KhannaRouter) global.KhannaRouter.refreshWizardFooter();
  }

  function init() {
    if (global.KhannaRouter) global.KhannaRouter.registerStepValidator("new-application", 6, isStep6Complete);

    document.addEventListener("khanna:navigate", function (e) {
      if (e.detail.view === "new-application") render();
      // Standalone Passport/Company Authorization pages (Phase 2): each
      // renders only its own group, independent of the wizard and of each
      // other.
      if (e.detail.view === "passport-authorization") renderStandalone("passport");
      if (e.detail.view === "company-authorization") renderStandalone("company");
    });

    // Only the checklist + generate bar + readiness notice react to every
    // background state change — never the text fields (see file header).
    // Also re-checks the combined step-6 "Continue" gate, since a change on
    // either tab (or a background change to applicant/traveller data that
    // both tabs' readiness checks depend on) can flip it either way.
    // activeGroupRoot() (used inside refreshChecklist/refreshGenerateBar/
    // refreshReadinessNotice) already resolves to whichever of the three
    // possible roots (wizard, standalone-passport, standalone-company) is
    // relevant to the current view, so this one subscription covers all of
    // them without checking view here.
    global.KhannaState.subscribe(function () {
      var mountedAnywhere =
        (root() && root().dataset.mounted) ||
        (standaloneRoot("passport") && standaloneRoot("passport").dataset.mounted) ||
        (standaloneRoot("company") && standaloneRoot("company").dataset.mounted);
      if (!mountedAnywhere) return;
      refreshChecklist("passport", 2);
      refreshChecklist("company", null);
      refreshGenerateBar("passport");
      refreshGenerateBar("company");
      refreshReadinessNotice(
        "passport",
        "Select 1 or 2 travellers (each with a name and passport number on file), and fill the centre and collector fields, to generate this letter."
      );
      refreshReadinessNotice(
        "company",
        "Select at least one applicant (with a name and passport number on file) and choose the consulate country to generate this letter."
      );
      if (global.KhannaRouter) global.KhannaRouter.refreshWizardFooter();
    });

    if (location.hash.indexOf("new-application") !== -1) render();
    if (location.hash.indexOf("passport-authorization") !== -1) renderStandalone("passport");
    if (location.hash.indexOf("company-authorization") !== -1) renderStandalone("company");
  }

  // Small, deliberately narrow surface reused by cover-letter.js (Phase 9)
  // so it doesn't keep its own near-identical copy of "applicant + every
  // traveller, flattened to a person row" (project rule 15) — only the
  // read-only helpers are exposed, none of this module's own render/DOM
  // state.
  global.KhannaAuthorization = {
    getSelectablePeople: getSelectablePeople,
    personDisplayName: personDisplayName,
    personHasCoreFields: personHasCoreFields,
    orderPeopleForLetter: orderPeopleForLetter,
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})(window);
