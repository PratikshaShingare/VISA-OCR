/* ==========================================================================
   Khanna Travels & Holidays — Accompanying travellers (wizard step 2)
   A list of traveller records on the active Application, each edited with
   the SAME passport upload/OCR/review pipeline built for the applicant in
   Phase 4 (KhannaPassportProcessing.createController) — reused here exactly
   as the master prompt intended, not reimplemented.

   Design note on re-rendering: the traveller LIST (summary cards) redraws
   freely on every state change, same as dashboard.js/applications.js. The
   currently-open EDIT PANEL does not — it is only created/replaced by an
   explicit user action (Add / Edit / Close / switch traveller), never by a
   generic state-change redraw, because it holds a live passport-processing
   controller with its own in-progress session (an uploaded file, an
   unsaved OCR result) that a surprise re-render would destroy.
   ========================================================================== */
(function (global) {
  "use strict";

  var utils = global.KhannaUtils;

  var RELATIONS = ["", "Spouse", "Child", "Parent", "Sibling", "Friend", "Colleague", "Other"];

  var activeTravellerId = null; // which traveller's panel is currently open, if any

  function root() {
    return utils.qs("[data-travellers-step-root]");
  }

  function getApp() {
    return global.KhannaState.getActiveApplication();
  }

  function travellerLabel(t) {
    var name = (t.fullName || [t.firstName, t.lastName].filter(Boolean).join(" ")).trim();
    return name || "Unnamed traveller";
  }

  function verificationBadge(t) {
    var status = t.passport && t.passport.verificationStatus;
    if (status === "Verified") return '<span class="badge badge-success">Verified</span>';
    if (status === "OCR Extracted — Please Verify") return '<span class="badge badge-warning">Please verify</span>';
    return '<span class="badge">Not started</span>';
  }

  function cardHtml(t) {
    var passportNo = t.passport && t.passport.current && t.passport.current.number;
    return (
      '<div class="traveller-card' + (t.id === activeTravellerId ? " is-editing" : "") + '" data-traveller-card="' + t.id + '">' +
      '<div class="traveller-card__info">' +
      '<div class="traveller-card__name">' + utils.escapeHtml(travellerLabel(t)) + "</div>" +
      '<div class="traveller-card__meta">' +
      (t.relation ? utils.escapeHtml(t.relation) : "Relation not set") +
      (passportNo ? " · Passport " + utils.escapeHtml(passportNo) : " · No passport on file") +
      "</div>" +
      "</div>" +
      verificationBadge(t) +
      '<div class="traveller-card__actions">' +
      '<button class="btn btn-secondary btn-sm" type="button" data-action="edit-traveller" data-traveller-id="' + t.id + '">' +
      (t.id === activeTravellerId ? "Editing…" : "Edit") +
      "</button>" +
      '<button class="btn-icon" type="button" data-action="remove-traveller" data-traveller-id="' + t.id + '" aria-label="Remove traveller">' +
      '<svg class="icon icon-sm" viewBox="0 0 24 24"><path d="M4 7h16M9 7V5a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2m2 0-1 13a1 1 0 0 1-1 1H8a1 1 0 0 1-1-1L6 7"/></svg>' +
      "</button>" +
      "</div>" +
      "</div>"
    );
  }

  function renderList() {
    var r = root();
    if (!r) return;
    var listEl = utils.qs("[data-travellers-list]", r);
    if (!listEl) return;
    var app = getApp();
    var travellers = (app && app.travellers) || [];

    if (travellers.length === 0) {
      listEl.innerHTML =
        '<div class="empty-state">' +
        '<svg class="icon" viewBox="0 0 24 24"><path d="M17 21v-2a4 4 0 0 0-4-4H7a4 4 0 0 0-4 4v2"/><circle cx="10" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75"/></svg>' +
        "<h3>No accompanying travellers</h3>" +
        "<p>If the applicant is travelling alone, you can continue to the next step. Otherwise, add each accompanying traveller here — spouse, children, or anyone else on the same application.</p>" +
        "</div>";
    } else {
      listEl.innerHTML = travellers.map(cardHtml).join("");
    }

    if (global.KhannaRouter) global.KhannaRouter.refreshWizardFooter();
  }

  function closePanel() {
    activeTravellerId = null;
    var panel = utils.qs("[data-traveller-panel]", root());
    if (panel) panel.innerHTML = "";
    renderList();
  }

  function openPanel(travellerId) {
    var app = getApp();
    if (!app) return;
    var traveller = global.KhannaState.getTraveller(app.id, travellerId);
    if (!traveller) return;

    activeTravellerId = travellerId;
    renderList();

    var panel = utils.qs("[data-traveller-panel]", root());
    if (!panel) return;

    panel.innerHTML =
      '<div class="traveller-panel">' +
      '<div class="traveller-panel__header">' +
      "<h3>Editing: " + utils.escapeHtml(travellerLabel(traveller)) + "</h3>" +
      '<button class="btn btn-ghost btn-sm" type="button" data-action="close-traveller-panel">Close</button>' +
      "</div>" +
      '<div class="field traveller-panel__relation">' +
      '<label for="travellerRelation">Relation to applicant</label>' +
      '<select id="travellerRelation" data-traveller-relation>' +
      RELATIONS.map(function (rel) {
        return '<option value="' + utils.escapeHtml(rel) + '">' + (rel || "— Select —") + "</option>";
      }).join("") +
      "</select>" +
      "</div>" +
      '<div data-traveller-passport-root></div>' +
      "</div>";

    var relationSelect = utils.qs("[data-traveller-relation]", panel);
    if (relationSelect) {
      relationSelect.value = traveller.relation || "";
      relationSelect.addEventListener("change", function () {
        global.KhannaState.updateTraveller(app.id, travellerId, { relation: relationSelect.value }, "Traveller relation updated");
      });
    }

    var passportRoot = utils.qs("[data-traveller-passport-root]", panel);
    var controller = global.KhannaPassportProcessing.createController({
      root: passportRoot,
      instanceId: travellerId,
      getApplication: getApp,
      getPerson: function (currentApp) {
        return global.KhannaState.getTraveller(currentApp.id, travellerId) || traveller;
      },
      savePerson: function (currentApp, personPatch, activityMessage) {
        global.KhannaState.updateTraveller(currentApp.id, travellerId, personPatch, activityMessage);
      },
      // No registerValidator here: step 2's Continue gating is one combined
      // check over every traveller (see isStepComplete below), not a single
      // traveller's own completeness.
    });
    controller.render();

    panel.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }

  function isStepComplete() {
    var app = getApp();
    if (!app) return false;
    var travellers = app.travellers || [];
    return travellers.every(function (t) {
      var passport = t.passport;
      return !!(
        t.lastName &&
        passport &&
        passport.current &&
        passport.current.number &&
        passport.verificationStatus &&
        passport.verificationStatus !== "Not Started"
      );
    });
  }

  function mountSkeleton() {
    var r = root();
    if (!r) return;
    r.innerHTML =
      '<div class="view-header">' +
      '<div class="view-header__text">' +
      "<h2>Accompanying travellers</h2>" +
      "<p>Anyone travelling with the applicant on this same application. Each traveller gets their own passport upload and OCR review, just like the applicant.</p>" +
      "</div>" +
      '<div class="view-header__actions">' +
      '<button class="btn btn-secondary btn-sm" type="button" data-action="use-existing-traveller">' +
      "Use Existing Traveller" +
      "</button>" +
      '<button class="btn btn-primary btn-sm" type="button" data-action="add-traveller">' +
      '<svg class="icon icon-sm" viewBox="0 0 24 24"><path d="M12 5v14M5 12h14"/></svg>' +
      "Add traveller" +
      "</button>" +
      "</div>" +
      "</div>" +
      '<div class="traveller-list" data-travellers-list></div>' +
      '<div data-traveller-panel></div>';

    utils.on(r, "click", "[data-action='add-traveller']", function () {
      var app = getApp();
      if (!app) return;
      var traveller = global.KhannaState.addTraveller(app.id, "");
      openPanel(traveller.id);
    });

    // Phase 5: the traveller-side equivalent of the document pages' "Use
    // Existing Applicant" button (Phase 2) — pulls a traveller already
    // saved from any earlier application onto this one instead of staff
    // re-typing their passport/contact details from scratch.
    utils.on(r, "click", "[data-action='use-existing-traveller']", function () {
      var app = getApp();
      if (!app || !global.KhannaTravellerPicker) return;
      global.KhannaTravellerPicker.open(function (profile) {
        var traveller = global.KhannaState.applyTravellerProfileToApplication(app.id, profile.id, profile.relation || "");
        if (traveller) openPanel(traveller.id);
      });
    });

    utils.on(r, "click", "[data-action='edit-traveller']", function (e, target) {
      openPanel(target.getAttribute("data-traveller-id"));
    });

    utils.on(r, "click", "[data-action='remove-traveller']", function (e, target) {
      var app = getApp();
      if (!app) return;
      var id = target.getAttribute("data-traveller-id");
      if (id === activeTravellerId) activeTravellerId = null;
      global.KhannaState.removeTraveller(app.id, id);
      var panel = utils.qs("[data-traveller-panel]", r);
      if (panel && activeTravellerId === null) panel.innerHTML = "";
    });

    utils.on(r, "click", "[data-action='close-traveller-panel']", function () {
      closePanel();
    });
  }

  function render() {
    var r = root();
    if (!r) return;
    if (!r.dataset.mounted) {
      r.dataset.mounted = "1";
      mountSkeleton();
    }
    renderList();
  }

  function init() {
    if (global.KhannaRouter) global.KhannaRouter.registerStepValidator("new-application", 2, isStepComplete);

    document.addEventListener("khanna:navigate", function (e) {
      if (e.detail.view === "new-application") render();
    });

    // The list (not the open panel) reacts to every state change, so saves
    // made inside a traveller's own passport-processing panel are reflected
    // in the card summary and the Continue button immediately.
    global.KhannaState.subscribe(function () {
      if (root() && root().dataset.mounted) renderList();
    });

    if (location.hash.indexOf("new-application") !== -1) render();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})(window);
