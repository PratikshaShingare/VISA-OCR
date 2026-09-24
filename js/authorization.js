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

  function selectedPeopleFor(app, group) {
    var state = authState(app, group);
    var ids = state.selectedPersonIds || [];
    return getSelectablePeople(app).filter(function (p) {
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

  function checklistHtml(people, selectedIds, group, maxCount) {
    if (!people.length) {
      return '<p class="field-hint">Add the applicant and/or travellers in earlier steps first.</p>';
    }
    return people
      .map(function (p) {
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
      })
      .join("");
  }

  function refreshChecklist(group, maxCount) {
    var app = getApp();
    var box = utils.qs('[data-auth-checklist="' + group + '"]', activeGroupRoot(group));
    if (!app || !box) return;
    var state = authState(app, group);
    box.innerHTML = checklistHtml(getSelectablePeople(app), state.selectedPersonIds || [], group, maxCount);
  }

  /* ---------------------------------------------------------------------
   * Rendering — generate bar + readiness notice
   * ------------------------------------------------------------------- */

  function generateBarHtml(group, ready, generatedAt) {
    return (
      '<div class="hotel-generate-bar">' +
      '<button class="btn btn-primary btn-sm" type="button" data-action="generate-authorization" data-group="' +
      group +
      '" data-format="docx"' +
      (ready ? "" : " disabled") +
      ">Generate (.docx)</button>" +
      '<button class="btn btn-secondary btn-sm" type="button" data-action="generate-authorization" data-group="' +
      group +
      '" data-format="pdf"' +
      (ready ? "" : " disabled") +
      ">Download as PDF</button>" +
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

  function renderPassportCard(app) {
    var box = utils.qs("[data-passport-auth-card]", activeGroupRoot("passport"));
    if (!box) return;
    var state = authState(app, "passport");
    box.innerHTML =
      "<h3>Passport Authorization Letter</h3>" +
      "<p>Authorizes Khanna Holidays Pvt. Ltd. to collect the original passport(s) of 1 or 2 travellers from the visa application centre — matches the two real reference letters on file (single traveller, or traveller + companion).</p>" +
      '<div class="auth-person-list" data-auth-checklist="passport"></div>' +
      '<div class="field-grid">' +
      fieldRowHtml("passport", "recipientCentreName", "Visa application centre", state.recipientCentreName, true, "e.g. Germany Visa Application Centre") +
      fieldRowHtml("passport", "recipientAddress", "Centre address", state.recipientAddress, false, "e.g. Andheri, Mumbai") +
      fieldRowHtml("passport", "collectorName", "Collected by (staff name)", state.collectorName, true, "e.g. Mr. Suresh Patil") +
      "</div>" +
      '<div data-auth-readiness="passport"></div>' +
      '<div data-generate-bar="passport"></div>' +
      '<div data-auth-error="passport"></div>';
    refreshChecklist("passport", 2);
    refreshGenerateBar("passport");
    refreshReadinessNotice(
      "passport",
      "Select 1 or 2 travellers (each with a name and passport number on file), and fill the centre and collector fields, to generate this letter."
    );
  }

  function renderCompanyCard(app) {
    var box = utils.qs("[data-company-auth-card]", activeGroupRoot("company"));
    if (!box) return;
    var state = authState(app, "company");
    box.innerHTML =
      "<h3>Company Authorization Letter</h3>" +
      "<p>Khanna Holidays Pvt. Ltd.’s own letter to the Visa Officer, listing every selected applicant whose passport it is authorized to collect.</p>" +
      '<div class="auth-person-list" data-auth-checklist="company"></div>' +
      '<div class="field-grid">' +
      fieldRowHtml("company", "recipientText", "Consulate name & address", state.recipientText, true, "e.g. The Consulate General of Germany, Mumbai") +
      "</div>" +
      '<div data-auth-readiness="company"></div>' +
      '<div data-generate-bar="company"></div>' +
      '<div data-auth-error="company"></div>';
    refreshChecklist("company", null);
    refreshGenerateBar("company");
    refreshReadinessNotice(
      "company",
      "Select at least one applicant (with a name and passport number on file) and fill the consulate field to generate this letter."
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

  function generateAuthorization(group, format, btn) {
    var app = getApp();
    if (!app) return;
    showAuthError(group, "");
    var originalText = btn.textContent;
    btn.disabled = true;
    btn.textContent = "Generating…";

    var applicantName = [app.applicant.firstName, app.applicant.lastName].filter(Boolean).join(" ") || "Application";
    var state = authState(app, group);
    var selected = selectedPeopleFor(app, group);

    var promise;
    if (group === "passport") {
      var ordered = orderPeopleForLetter(selected);
      promise = api.downloadPassportAuthorization({
        people: ordered.map(personToPassportPayload),
        recipientCentreName: state.recipientCentreName || "",
        recipientAddress: state.recipientAddress || "",
        collectorName: state.collectorName || "",
        format: format,
        applicantName: applicantName,
      });
    } else {
      promise = api.downloadCompanyAuthorization({
        people: selected.map(personToCompanyPayload),
        recipientText: state.recipientText || "",
        format: format,
        applicantName: applicantName,
      });
    }

    promise.then(
      function (result) {
        utils.triggerFileDownload(result.blob, result.filename);
        var ts = new Date().toISOString();
        var patch = { authorization: {} };
        patch.authorization[group] = { generatedAt: ts };
        var label = group === "passport" ? "Passport Authorization Letter" : "Company Authorization Letter";
        global.KhannaState.updateApplication(app.id, patch, label + " generated (" + format.toUpperCase() + ")");
        // The generate bar picks up the fresh "Last generated" timestamp
        // via the KhannaState.subscribe callback below — deliberately NOT
        // called directly here, so success and failure both flow through
        // exactly one place (matches hotels.js's own discipline).
      },
      function (err) {
        btn.disabled = false;
        btn.textContent = originalText;
        showAuthError(group, (err && err.message) || "Could not generate the letter.");
      }
    );
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
      "<p>Authorization and cover letters are generated straight from the real Khanna Travels &amp; Holidays reference formats — nothing here is a recreation.</p>" +
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
  }

  // Extracted from mountSkeleton() (Phase 2) so the standalone Passport/
  // Company Authorization pages can wire the exact same handlers onto
  // their own root via mountStandaloneSkeleton() below, instead of a second
  // near-identical copy of this logic (project rule 15). Each handler
  // already reads its `group` from the clicked/changed element's own
  // attribute, so nothing here needs to know which root it was mounted on.
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
    var patch = { authorization: {} };
    patch.authorization[group] = { selectedPersonIds: ids };
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
    global.KhannaState.updateApplication(app.id, patch, null);
  }

  function onGenerateAuthorizationClick(e, target) {
    if (target.disabled) return;
    generateAuthorization(target.getAttribute("data-group"), target.getAttribute("data-format"), target);
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
        "Select at least one applicant (with a name and passport number on file) and fill the consulate field to generate this letter."
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
