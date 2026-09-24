/* ==========================================================================
   Khanna Travels & Holidays — Travel details & visa checklist (wizard step 3)
   A plain form for the trip's shared details (one per Application, not per
   traveller), plus a live preview of the required/supporting document
   checklist that destination + visa category resolve to (js/documents/
   checklist-rules.js). The checklist is regenerated into KhannaState
   (which also reconciles the Application's `documents` array — see
   KhannaState.syncChecklistDocuments) every time destination or visa
   category changes, so step 4 always has an up-to-date document list to
   work from.
   ========================================================================== */
(function (global) {
  "use strict";

  var utils = global.KhannaUtils;
  var rules = global.KhannaChecklistRules;

  var TRAVEL_FIELDS = [
    { key: "destination", label: "Destination", type: "select", options: rules.DESTINATIONS },
    { key: "visaCategory", label: "Visa category", type: "select", options: rules.VISA_CATEGORIES },
    { key: "purpose", label: "Purpose of visit", placeholder: "e.g. Tourism, Business meeting" },
    { key: "countryOfResidence", label: "Country of residence", placeholder: "e.g. India" },
    { key: "startDate", label: "Travel start date", type: "date" },
    { key: "endDate", label: "Travel end date", type: "date" },
  ];

  function root() {
    return utils.qs("[data-travel-step-root]");
  }

  function getApp() {
    return global.KhannaState.getActiveApplication();
  }

  function fieldRow(f) {
    var id = "tf-" + f.key;
    var input;
    if (f.type === "select") {
      var opts = ['<option value="">— Select —</option>'].concat(
        f.options.map(function (o) {
          return '<option value="' + utils.escapeHtml(o) + '">' + utils.escapeHtml(o) + "</option>";
        })
      );
      input = '<select id="' + id + '" data-travel-field="' + f.key + '">' + opts.join("") + "</select>";
    } else {
      input =
        '<input type="' + (f.type || "text") + '" id="' + id + '" data-travel-field="' + f.key + '"' +
        (f.placeholder ? ' placeholder="' + utils.escapeHtml(f.placeholder) + '"' : "") +
        " />";
    }
    return (
      '<div class="field">' +
      '<label for="' + id + '">' + utils.escapeHtml(f.label) + "</label>" +
      input +
      "</div>"
    );
  }

  function checklistListHtml(items, emptyText) {
    if (!items.length) return '<p class="checklist-empty">' + emptyText + "</p>";
    return (
      '<ul class="checklist-preview-list">' +
      items
        .map(function (label) {
          return "<li>" + utils.escapeHtml(label) + "</li>";
        })
        .join("") +
      "</ul>"
    );
  }

  function renderChecklistPreview() {
    var r = root();
    var box = utils.qs("[data-checklist-preview]", r);
    if (!box) return;
    var app = getApp();
    if (!app) return;
    var travel = app.travel || {};

    if (!travel.destination || !travel.visaCategory) {
      box.innerHTML =
        '<div class="empty-state">' +
        '<svg class="icon" viewBox="0 0 24 24"><path d="M9 11l3 3L22 4"/><path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11"/></svg>' +
        "<h3>Select a destination and visa category</h3>" +
        "<p>The required and supporting document checklist appears here once both are set, and carries through to the Documents step.</p>" +
        "</div>";
      return;
    }

    var resolved = rules.getChecklist(travel.destination, travel.visaCategory);
    box.innerHTML =
      (resolved.isGeneric
        ? '<div class="notice notice-warning">' +
          '<svg class="icon icon-sm" viewBox="0 0 24 24"><path d="M12 9v4M12 17h.01"/><circle cx="12" cy="12" r="9"/></svg>' +
          "<span>No curated checklist exists yet for this destination/category combination — showing a generic starting checklist. Add or remove documents as needed on the Documents step.</span>" +
          "</div>"
        : "") +
      '<div class="notice">' +
      '<svg class="icon icon-sm" viewBox="0 0 24 24"><path d="M12 9v4M12 17h.01"/><circle cx="12" cy="12" r="9"/></svg>' +
      "<span>Standard starting checklist — always confirm current requirements with the relevant consulate/embassy, as they vary by case and change over time.</span>" +
      "</div>" +
      '<div class="checklist-preview-columns">' +
      '<div><h3>Required documents</h3>' + checklistListHtml(resolved.required, "None") + "</div>" +
      '<div><h3>Supporting documents</h3>' + checklistListHtml(resolved.supporting, "None") + "</div>" +
      "</div>";
  }

  function regenerateChecklist() {
    var app = getApp();
    if (!app) return;
    var travel = app.travel || {};
    if (!travel.destination || !travel.visaCategory) {
      renderChecklistPreview();
      return;
    }
    var resolved = rules.getChecklist(travel.destination, travel.visaCategory);
    global.KhannaState.syncChecklistDocuments(app.id, travel.destination, travel.visaCategory, resolved.required, resolved.supporting);
    renderChecklistPreview();
    if (global.KhannaRouter) global.KhannaRouter.refreshWizardFooter();
  }

  function loadForm() {
    var r = root();
    var app = getApp();
    if (!app) return;
    var travel = app.travel || {};
    TRAVEL_FIELDS.forEach(function (f) {
      var el = utils.qs('[data-travel-field="' + f.key + '"]', r);
      if (el) el.value = travel[f.key] || "";
    });
    renderChecklistPreview();
  }

  function isStepComplete() {
    var app = getApp();
    if (!app) return false;
    var travel = app.travel || {};
    return !!(travel.destination && travel.visaCategory && travel.startDate && travel.endDate);
  }

  function mountSkeleton() {
    var r = root();
    if (!r) return;
    r.innerHTML =
      '<div class="view-header">' +
      '<div class="view-header__text">' +
      "<h2>Travel details</h2>" +
      "<p>Shared trip details for this application. The visa document checklist below updates automatically from the destination and visa category.</p>" +
      "</div>" +
      "</div>" +
      '<div class="card">' +
      '<div class="field-grid">' +
      TRAVEL_FIELDS.map(fieldRow).join("") +
      "</div>" +
      "</div>" +
      '<div class="view-header" style="margin-top:var(--space-6);">' +
      '<div class="view-header__text">' +
      "<h2>Visa document checklist</h2>" +
      "</div>" +
      "</div>" +
      '<div data-checklist-preview></div>';

    utils.on(r, "change", "[data-travel-field]", function (e, target) {
      var app = getApp();
      if (!app) return;
      var key = target.getAttribute("data-travel-field");
      var patch = {};
      patch[key] = target.value;
      global.KhannaState.updateApplication(app.id, { travel: patch }, "Travel details updated");
      if (key === "destination" || key === "visaCategory") {
        regenerateChecklist();
      } else if (global.KhannaRouter) {
        global.KhannaRouter.refreshWizardFooter();
      }
    });
  }

  function render() {
    var r = root();
    if (!r) return;
    if (!r.dataset.mounted) {
      r.dataset.mounted = "1";
      mountSkeleton();
    }
    loadForm();
  }

  function init() {
    if (global.KhannaRouter) global.KhannaRouter.registerStepValidator("new-application", 3, isStepComplete);

    document.addEventListener("khanna:navigate", function (e) {
      if (e.detail.view === "new-application") render();
    });

    if (location.hash.indexOf("new-application") !== -1) render();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})(window);
