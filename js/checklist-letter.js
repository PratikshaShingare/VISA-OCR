/* ==========================================================================
   Khanna Travels & Holidays — Required Document Letter (Checklist Letter)
   A standalone document (not tied to any Applicant/Traveller Application
   record — there is no "Use existing application" bar on this page,
   deliberately, matching the real reference template: it is a
   country/visa-type checklist letter sent to a prospective client before
   any application record necessarily exists). Country + visa type +
   employment status + the FULL document catalog and rule engine live
   entirely on the backend (app.py + visa_requirements_data.py /
   required_document_letter_engine.py) — this file only renders whatever
   the backend returns, never its own country/visa if-else logic and never
   its own hardcoded document list.

   Checkbox-based document selection (31-section rebuild spec): every
   document in the backend's catalog is rendered as an editable checkbox.
   Changing country/visa type/employment status/circumstances re-asks the
   backend which ids it SUGGESTS pre-checking (resolve_suggested_document_ids
   — a structured rule engine, not frontend if/else) — but staff can always
   add or remove any document for the specific client in front of them, and
   only whatever is actually left checked at generation time is sent to the
   backend and appears in the letter.

   Anti-fabrication discipline (project rule 9, and the user's own explicit
   instruction not to invent visa-requirement numbers): the backend's
   /api/visa-requirements/lookup endpoint only ever returns a field when a
   real, sourced figure has been verified (see visa_requirements_data.py's
   own module docstring for how narrow that currently is). A field it does
   not return is shown here as "Check current official requirement," never
   silently left blank with no explanation, and a looked-up value only ever
   PRE-FILLS an empty input — it never overwrites something staff already
   typed. Bank-statement duration, ITR years and processing time are each a
   predefined pick-list (+ "Custom" free text) purely for staff convenience
   — never a claim about any specific country's actual requirement.
   ========================================================================== */
(function (global) {
  "use strict";

  var utils = global.KhannaUtils;
  var api = global.KhannaApi;

  var state = {
    countries: [],
    visaTypes: ["Tourist"],
    employmentStatuses: ["Other"],
    bankStatementDurationOptions: ["Custom"],
    itrYearOptions: ["Custom"],
    processingTimeOptions: ["Custom"],
    documentCatalog: [], // [{id, label}], label may still contain a raw {duration}/{years} placeholder token
    checkedDocumentIds: {}, // id -> true, staff-editable set (checkbox state lives here, not re-derived every render)
    // Bumped on every MANUAL checkbox toggle. A real, reproduced race:
    // selecting a new visa type / employment status fires an async
    // /api/visa-requirements/suggested-documents request, and if staff
    // start checking/unchecking boxes before that request resolves, its
    // (now-stale) result would otherwise silently overwrite their own
    // edits — caught via a real Playwright test that toggled a checkbox
    // right after an employment-status change and found the manual edit
    // reverted a moment later. Fixed the same way document-viewer.js's own
    // refresh() guards a stale render with `token !== this._renderToken`:
    // refreshSuggestedDocuments() snapshots this counter before firing its
    // request and only applies the result if nothing was manually toggled
    // in the meantime.
    checklistVersion: 0,
    // Separate monotonic token guarding against a SECOND race: two
    // suggested-document requests fired close together (e.g. visa type
    // changed, then employment status changed a moment later) resolving
    // out of network order — only the most-recently-DISPATCHED request's
    // result is ever applied, exactly like document-viewer.js's own
    // `_renderToken` guards its refresh() calls.
    suggestionRequestToken: 0,
    knownFacts: null,
    loadingLookup: false,
    generating: false,
  };

  // Single standalone root (no dual-mount for this page), so a plain
  // module-level handle is enough — unlike hotels.js/authorization.js/
  // cover-letter.js/invitation.js, which all need a WeakMap because they
  // can each mount into two different DOM roots.
  var viewerHandle = null;

  function root() {
    return utils.qs("[data-checklist-letter-root]");
  }

  function fieldValue(selector) {
    var el = utils.qs(selector, root());
    return el ? el.value : "";
  }

  function isCustomSelected(selector) {
    return fieldValue(selector) === "Custom";
  }

  /* ---------------------------------------------------------------------
   * Pick-list field: a <select> of predefined options + "Custom", paired
   * with a free-text input that only appears/matters when "Custom" is
   * picked. Shared shape for bank-statement duration / ITR years /
   * processing time (project spec: "predefined values + Custom" for all
   * three).
   * ------------------------------------------------------------------- */

  function pickListHtml(fieldKey, label, options, customFieldKey) {
    return (
      '<div class="field">' +
      '<label for="rdl' + fieldKey + '">' + utils.escapeHtml(label) + "</label>" +
      '<select id="rdl' + fieldKey + '" data-field="' + fieldKey + '">' +
      options.map(function (v) { return '<option value="' + utils.escapeHtml(v) + '">' + utils.escapeHtml(v) + "</option>"; }).join("") +
      "</select>" +
      '<input type="text" data-field="' + customFieldKey + '" data-custom-for="' + fieldKey + '" placeholder="Type the exact figure/wording" style="margin-top:var(--space-2);" hidden />' +
      "</div>"
    );
  }

  function resolvedPickListValue(fieldKey, customFieldKey) {
    var picked = fieldValue("[data-field='" + fieldKey + "']");
    if (picked === "Custom") return fieldValue("[data-field='" + customFieldKey + "']");
    return picked;
  }

  function updateCustomFieldVisibility() {
    var r = root();
    utils.qsa("[data-custom-for]", r).forEach(function (input) {
      var fieldKey = input.getAttribute("data-custom-for");
      input.hidden = fieldValue("[data-field='" + fieldKey + "']") !== "Custom";
    });
  }

  function skeletonHtml() {
    return (
      '<div class="card" style="margin-bottom:var(--space-4);">' +
      '<h3 style="margin-top:0;">Enquiry details</h3>' +
      '<div class="field-grid">' +
      '<div class="field">' +
      "<label for=\"rdlCountry\">Country</label>" +
      '<input type="text" id="rdlCountry" list="rdlCountryList" data-field="country" placeholder="Start typing a country…" autocomplete="off" />' +
      '<datalist id="rdlCountryList"></datalist>' +
      "</div>" +
      '<div class="field">' +
      "<label for=\"rdlVisaType\">Visa type</label>" +
      '<select id="rdlVisaType" data-field="visaType">' +
      state.visaTypes.map(function (v) { return '<option value="' + v + '">' + v + "</option>"; }).join("") +
      "</select>" +
      "</div>" +
      '<div class="field">' +
      "<label for=\"rdlEmployment\">Applicant's employment status</label>" +
      '<select id="rdlEmployment" data-field="employmentStatus">' +
      state.employmentStatuses.map(function (v) { return '<option value="' + v + '">' + v + "</option>"; }).join("") +
      "</select>" +
      "</div>" +
      "</div>" +
      '<div style="display:flex;gap:var(--space-4);flex-wrap:wrap;margin-top:var(--space-3);">' +
      '<label style="display:flex;align-items:center;gap:var(--space-2);font-size:.85rem;">' +
      '<input type="checkbox" data-field="invited" /> Invited by someone abroad</label>' +
      '<label style="display:flex;align-items:center;gap:var(--space-2);font-size:.85rem;">' +
      '<input type="checkbox" data-field="hasUsVisaCopy" /> Applicant holds a valid USA visa</label>' +
      "</div>" +
      '<div data-known-facts-notice style="margin-top:var(--space-3);"></div>' +
      "</div>" +

      '<div class="card" style="margin-bottom:var(--space-4);">' +
      '<h3 style="margin-top:0;">Figures for this letter</h3>' +
      '<p class="field-hint" style="margin-top:0;">Pre-filled automatically when a verified figure is on file for this country/visa type — always editable, and never invented when nothing is on file (you\'ll see "Check current official requirement" instead). Bank statement/ITR/processing-time pick-lists are staff convenience shortcuts, not a claim about this specific country\'s actual requirement — pick "Custom" to type the consulate\'s own exact wording.</p>' +
      '<div class="field-grid">' +
      pickListHtml("bankStatementDuration", "Bank statement — last how long", state.bankStatementDurationOptions, "bankStatementDurationCustom") +
      pickListHtml("itrYears", "Income Tax Returns — last how many years", state.itrYearOptions, "itrYearsCustom") +
      pickListHtml("processingTime", "Processing time", state.processingTimeOptions, "processingTimeCustom") +
      '<div class="field"><label for="rdlVisaFees">Visa fees &amp; charges (INR)</label>' +
      '<input type="text" id="rdlVisaFees" data-field="visaFees" placeholder="e.g. 8,500" /></div>' +
      "</div>" +
      "</div>" +

      '<div class="card">' +
      '<h3 style="margin-top:0;">Documents required</h3>' +
      '<p class="field-hint" style="margin-top:0;">Every document Khanna Travels can ever list on this letter — checked ones are this enquiry\'s own suggestions (country/visa-type/employment-status/circumstance rules on the backend), but every checkbox is yours to add or remove for this specific client. Only checked documents appear in the generated letter.</p>' +
      '<div data-rdl-document-checklist class="auth-person-list"></div>' +
      "</div>" +

      '<div class="card" style="margin-top:var(--space-4);">' +
      '<div class="hotel-generate-bar">' +
      '<button type="button" class="btn btn-primary btn-sm" data-action="generate-rdl">Generate &amp; Preview Letter</button>' +
      '<span class="hotel-generate-bar__meta" data-rdl-meta></span>' +
      "</div>" +
      '<div data-rdl-error></div>' +
      "</div>" +
      '<div data-rdl-preview style="margin-top:var(--space-4);"></div>'
    );
  }

  function documentChecklistHtml() {
    if (!state.documentCatalog.length) {
      return '<p class="field-hint">Could not load the document catalog from the backend.</p>';
    }
    return state.documentCatalog
      .map(function (doc) {
        var checked = !!state.checkedDocumentIds[doc.id];
        // A live-preview of the label: substitutes the CURRENT pick-list
        // selection into {duration}/{years} so staff see the real sentence
        // that will appear, not a raw template token.
        var previewLabel = doc.label
          .replace("{duration}", resolvedPickListValue("bankStatementDuration", "bankStatementDurationCustom") || "[DURATION]")
          .replace("{years}", resolvedPickListValue("itrYears", "itrYearsCustom") || "__");
        return (
          '<label class="auth-person-row">' +
          '<input type="checkbox" data-rdl-document data-doc-id="' + utils.escapeHtml(doc.id) + '"' +
          (checked ? " checked" : "") +
          " />" +
          '<span class="auth-person-row__name">' + utils.escapeHtml(previewLabel) + "</span>" +
          "</label>"
        );
      })
      .join("");
  }

  function renderDocumentChecklist() {
    var el = utils.qs("[data-rdl-document-checklist]", root());
    if (el) el.innerHTML = documentChecklistHtml();
  }

  function knownFactsNoticeHtml() {
    var facts = state.knownFacts;
    if (state.loadingLookup) {
      return '<div class="notice">Checking for a verified figure on file…</div>';
    }
    if (!facts || Object.keys(facts).length === 0) {
      return (
        '<div class="notice notice-warning"><span>No verified figures are on file yet for this country/visa type — ' +
        "confirm current bank-statement duration, ITR years, processing time and fees with the consulate/VFS before quoting a client.</span></div>"
      );
    }
    var lines = [];
    ["bankStatementDuration", "itrYears", "processingTime", "visaFees"].forEach(function (k) {
      if (facts[k]) lines.push(utils.escapeHtml(String(facts[k])));
    });
    return (
      '<div class="notice notice-success"><span>' +
      (lines.length ? lines.join(" · ") + " — " : "") +
      "Verified against " + utils.escapeHtml(facts.source || "an official source") +
      (facts.verifiedOn ? " on " + utils.escapeHtml(facts.verifiedOn) : "") +
      (facts.note ? ". " + utils.escapeHtml(facts.note) : "") +
      "</span></div>"
    );
  }

  function renderKnownFactsNotice() {
    var el = utils.qs("[data-known-facts-notice]", root());
    if (el) el.innerHTML = knownFactsNoticeHtml();
  }

  function populateCountryList() {
    var listEl = utils.qs("#rdlCountryList", root());
    if (listEl) listEl.innerHTML = state.countries.map(function (c) { return '<option value="' + utils.escapeHtml(c) + '"></option>'; }).join("");
  }

  function readForm() {
    var r = root();
    var checkedIds = Object.keys(state.checkedDocumentIds).filter(function (id) {
      return state.checkedDocumentIds[id];
    });
    return {
      country: fieldValue("[data-field='country']"),
      visaType: fieldValue("[data-field='visaType']") || state.visaTypes[0],
      employmentStatus: fieldValue("[data-field='employmentStatus']") || state.employmentStatuses[0],
      invited: !!(utils.qs("[data-field='invited']", r) || {}).checked,
      hasUsVisaCopy: !!(utils.qs("[data-field='hasUsVisaCopy']", r) || {}).checked,
      bankStatementDuration: resolvedPickListValue("bankStatementDuration", "bankStatementDurationCustom"),
      itrYears: resolvedPickListValue("itrYears", "itrYearsCustom"),
      processingTime: resolvedPickListValue("processingTime", "processingTimeCustom"),
      visaFees: fieldValue("[data-field='visaFees']"),
      documentIds: checkedIds,
    };
  }

  function isReady(payload) {
    return !!(payload.country && payload.country.trim());
  }

  function updateGenerateButtons() {
    var r = root();
    var payload = readForm();
    var ready = isReady(payload);
    utils.qsa("[data-action='generate-rdl']", r).forEach(function (btn) {
      btn.disabled = !ready || state.generating;
    });
  }

  function fillIfEmpty(selector, value) {
    if (!value) return;
    var el = utils.qs(selector, root());
    if (el && !el.value) el.value = value;
  }

  function runLookup() {
    var payload = readForm();
    if (!payload.country || !payload.country.trim()) {
      state.knownFacts = null;
      renderKnownFactsNotice();
      return;
    }
    state.loadingLookup = true;
    renderKnownFactsNotice();
    api.lookupVisaRequirement(payload.country.trim(), payload.visaType).then(
      function (facts) {
        state.loadingLookup = false;
        state.knownFacts = facts;
        renderKnownFactsNotice();
        fillIfEmpty("[data-field='visaFees']", facts.visaFees);
      },
      function () {
        state.loadingLookup = false;
        state.knownFacts = null;
        renderKnownFactsNotice();
      }
    );
  }

  function refreshSuggestedDocuments() {
    var payload = readForm();
    var versionAtDispatch = state.checklistVersion;
    var token = ++state.suggestionRequestToken;
    api
      .getSuggestedDocuments({
        visaType: payload.visaType,
        employmentStatus: payload.employmentStatus,
        invited: payload.invited,
        hasUsVisaCopy: payload.hasUsVisaCopy,
        country: payload.country,
      })
      .then(function (result) {
        if (token !== state.suggestionRequestToken) {
          // A newer visa-type/employment-status/circumstance change already
          // fired its own request — this one resolved late; discard it so
          // an out-of-order response can never overwrite a more current one.
          return;
        }
        if (state.checklistVersion !== versionAtDispatch) {
          // Staff already manually toggled a checkbox while this request
          // was in flight — their edit wins; this now-stale suggestion is
          // discarded rather than silently overwriting it.
          return;
        }
        var suggested = result.suggestedDocumentIds || [];
        var next = {};
        suggested.forEach(function (id) {
          next[id] = true;
        });
        state.checkedDocumentIds = next;
        renderDocumentChecklist();
        updateGenerateButtons();
      })
      .catch(function () {
        // Honest degradation: keep whatever was already checked rather than
        // silently clearing the checklist on a transient backend error.
      });
  }

  function showError(message) {
    var el = utils.qs("[data-rdl-error]", root());
    if (el) {
      el.innerHTML = message
        ? '<div class="notice notice-danger"><span>' + utils.escapeHtml(message) + "</span></div>"
        : "";
    }
  }

  function generate(btn) {
    var payload = readForm();
    if (!isReady(payload)) return;
    var r = root();
    if (!r) return;
    var previewBox = utils.qs("[data-rdl-preview]", r);
    if (!previewBox) return;

    if (!viewerHandle) {
      viewerHandle = global.KhannaDocumentViewer.mount(previewBox, {
        title: "Required Document Letter",
        loadPdf: function () {
          return api.downloadRequiredDocumentLetter(Object.assign({}, readForm(), { format: "pdf" }));
        },
        loadDocx: function () {
          return api.downloadRequiredDocumentLetter(Object.assign({}, readForm(), { format: "docx" }));
        },
        onEdit: function () {
          var box = root();
          if (box) box.scrollIntoView({ behavior: "smooth", block: "start" });
        },
        onRegenerate: function () {
          return Promise.resolve();
        },
      });
    }

    state.generating = true;
    showError("");
    updateGenerateButtons();
    var meta = utils.qs("[data-rdl-meta]", root());
    if (meta) meta.textContent = "Generating…";

    viewerHandle
      .refresh()
      .then(function () {
        if (meta) meta.textContent = "Last generated " + utils.formatDate(new Date().toISOString());
      })
      .catch(function (err) {
        showError(err && err.message ? err.message : "Could not generate the letter.");
      })
      .finally(function () {
        state.generating = false;
        updateGenerateButtons();
      });
  }

  function mountSkeleton() {
    var r = root();
    if (!r) return;
    r.innerHTML = skeletonHtml();
    populateCountryList();
    renderKnownFactsNotice();
    renderDocumentChecklist();
    updateCustomFieldVisibility();
    updateGenerateButtons();
    refreshSuggestedDocuments();

    utils.on(r, "input", "[data-field]", updateGenerateButtons);

    utils.on(r, "change", "[data-field='country'], [data-field='visaType']", function () {
      runLookup();
      refreshSuggestedDocuments();
      updateGenerateButtons();
    });

    utils.on(r, "change", "[data-field='employmentStatus'], [data-field='invited'], [data-field='hasUsVisaCopy']", function () {
      refreshSuggestedDocuments();
      updateGenerateButtons();
    });

    // Bank-statement/ITR pick-list changes only need the checklist's own
    // live label PREVIEW re-rendered (the resolved figure shown inline
    // next to "Personal Bank Statement of Last ...") — never a fresh
    // suggested-documents lookup, since which documents are suggested
    // never depends on the actual duration/years VALUE, only on visa
    // type/employment status/circumstances.
    utils.on(r, "change", "[data-field='bankStatementDuration'], [data-field='bankStatementDurationCustom'], [data-field='itrYears'], [data-field='itrYearsCustom']", function () {
      renderDocumentChecklist();
    });

    utils.on(r, "change", "[data-field]", function (e, target) {
      if (target.hasAttribute("data-custom-for")) return; // handled above already
      var key = target.getAttribute("data-field");
      if (key === "bankStatementDuration" || key === "itrYears" || key === "processingTime") {
        updateCustomFieldVisibility();
      }
    });

    utils.on(r, "change", "[data-rdl-document]", function (e, target) {
      var id = target.getAttribute("data-doc-id");
      state.checkedDocumentIds[id] = target.checked;
      state.checklistVersion += 1;
    });

    utils.on(r, "click", "[data-action='generate-rdl']", function (e, target) {
      generate(target);
    });
  }

  function loadReferenceDataThenMount() {
    api.getVisaCountries().then(
      function (data) {
        state.countries = data.countries || [];
        state.visaTypes = data.visaTypes && data.visaTypes.length ? data.visaTypes : state.visaTypes;
        state.employmentStatuses = data.employmentStatuses && data.employmentStatuses.length ? data.employmentStatuses : state.employmentStatuses;
        state.bankStatementDurationOptions = data.bankStatementDurationOptions && data.bankStatementDurationOptions.length ? data.bankStatementDurationOptions : state.bankStatementDurationOptions;
        state.itrYearOptions = data.itrYearOptions && data.itrYearOptions.length ? data.itrYearOptions : state.itrYearOptions;
        state.processingTimeOptions = data.processingTimeOptions && data.processingTimeOptions.length ? data.processingTimeOptions : state.processingTimeOptions;
        state.documentCatalog = data.documentCatalog || [];
        mountSkeleton();
      },
      function () {
        // Honest degradation: the backend is unreachable — still render the
        // form (country becomes a plain free-text field, no typeahead, and
        // the document checklist stays empty with its own honest message)
        // so the page isn't a dead end, matching this app's own "never a
        // fake functionality claim, but never a total blank page either"
        // pattern.
        mountSkeleton();
        showError("Could not load reference data from the backend — you can still type a country name manually, but the document checklist and pick-lists could not be loaded.");
      }
    );
  }

  function render() {
    var r = root();
    if (!r) return;
    if (!r.dataset.mounted) {
      r.dataset.mounted = "1";
      loadReferenceDataThenMount();
      return;
    }
  }

  function init() {
    document.addEventListener("khanna:navigate", function (e) {
      if (e.detail.view === "checklist-letter") render();
    });
    if (location.hash.indexOf("checklist-letter") !== -1) render();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})(window);
