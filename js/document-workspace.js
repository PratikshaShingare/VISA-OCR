/* ==========================================================================
   Khanna Travels & Holidays — Standalone document page: active-application bar
   Phase 2 of the document-first redesign. Every standalone document page
   that now has a real, working document controller mounted (Cover Letter,
   Hotel Blocking, Company/Passport Authorization, Invitation Letter,
   Upload Passport since Phase 5 — Checklist Letter joins once it exists)
   shows the SAME small bar at the top: which application is currently
   active, and a way to start a fresh one without leaving the page.

   Phase 3 adds the other half: a "Use existing application" button next to
   "Create new application" (or "Start a different application"), backed by
   the shared global.KhannaApplicationPicker modal — searchable by name,
   passport number, application ID, email and destination. Picking a result
   sets it active and re-renders the current document controller in place,
   exactly like the "create new" action already did.

   Reuses global.KhannaState (createApplication/setActiveApplicationId/
   getActiveApplication), global.KhannaApplicationsList.applicantLabel and
   global.KhannaApplicationPicker — no new state, no duplicated "what's
   this application called" or "find an application" logic (project rule 15).
   ========================================================================== */
(function (global) {
  "use strict";

  var utils = global.KhannaUtils;

  // Every standalone document view that has a real controller mounted.
  // "upload-passport" (Phase 5): passport-processing.js's own second
  // createController() instance for that page reads/writes
  // KhannaState.getActiveApplication() exactly like every entry already
  // here, so it needs the same "Create new application" / "Use existing
  // application" bar and the same re-render-on-application-switch wiring
  // — no page-specific logic added here.
  var DOC_VIEWS = [
    "cover-letter",
    "hotel-blocking",
    "company-authorization",
    "passport-authorization",
    "invitation-letter",
    "upload-passport",
  ];

  function currentView() {
    return global.KhannaRouter ? global.KhannaRouter.parseHash().view : null;
  }

  function isDocView(view) {
    return DOC_VIEWS.indexOf(view) !== -1;
  }

  // Per-view button set for this shared bar. Most document pages keep all
  // three actions (unchanged, original behaviour). Three pages asked for a
  // reduced/relabeled set:
  //  - upload-passport: uploading a passport must never pull in another
  //    applicant's or application's saved data (project instruction), so
  //    both pickers are hidden — only "start fresh" stays.
  //  - hotel-blocking: same picker removal, no relabeling.
  //  - cover-letter: both pickers hidden here too — replaced by its own
  //    page-level "Use Existing Details" control (Passport / Hotel
  //    Blocking) plus a manual name-entry field, added in cover-letter.js
  //    itself rather than this shared bar — and its create-button label
  //    reads "Create Different Cover Letter" instead of the generic text.
  var VIEW_BUTTON_CONFIG = {
    "upload-passport": { showApplicantPicker: false, showApplicationPicker: false, createLabelActive: null },
    "hotel-blocking": { showApplicantPicker: false, showApplicationPicker: false, createLabelActive: null },
    "cover-letter": { showApplicantPicker: false, showApplicationPicker: false, createLabelActive: "Create Different Cover Letter" },
  };

  function configFor(view) {
    return VIEW_BUTTON_CONFIG[view] || { showApplicantPicker: true, showApplicationPicker: true, createLabelActive: null };
  }

  function actionButtonsHtml(view, hasActiveApp) {
    var cfg = configFor(view);
    var html = "";
    if (cfg.showApplicantPicker) {
      html += '<button class="btn btn-secondary btn-sm" type="button" data-action="pick-doc-applicant">Use Existing Applicant</button>';
    }
    if (cfg.showApplicationPicker) {
      html += '<button class="btn btn-secondary btn-sm" type="button" data-action="pick-doc-application">Use existing application</button>';
    }
    var createLabel = hasActiveApp ? (cfg.createLabelActive || "Start a different application") : "Create new application";
    var createClass = hasActiveApp ? "btn-secondary" : "btn-primary";
    html += '<button class="btn ' + createClass + ' btn-sm" type="button" data-action="create-doc-application">' + utils.escapeHtml(createLabel) + "</button>";
    return html;
  }

  function barHtml(view) {
    var app = global.KhannaState.getActiveApplication();
    if (app) {
      var label = global.KhannaApplicationsList ? global.KhannaApplicationsList.applicantLabel(app) : "Untitled applicant";
      return (
        '<div class="card doc-page-app-bar">' +
        '<div class="doc-page-app-bar__info">' +
        '<span class="field-hint">Working on</span>' +
        "<strong>" + utils.escapeHtml(label) + "</strong>" +
        '<span class="badge ' + utils.statusBadgeClass(app.status) + '">' + utils.escapeHtml(app.status) + "</span>" +
        "</div>" +
        '<div class="doc-page-app-bar__actions">' +
        actionButtonsHtml(view, true) +
        "</div>" +
        "</div>"
      );
    }
    return (
      '<div class="card doc-page-app-bar">' +
      '<div class="doc-page-app-bar__info">' +
      "<strong>No application selected yet</strong>" +
      '<span class="field-hint">Reuse a saved applicant, or create a fresh application to generate this document.</span>' +
      "</div>" +
      '<div class="doc-page-app-bar__actions">' +
      actionButtonsHtml(view, false) +
      "</div>" +
      "</div>"
    );
  }

  function render() {
    var view = currentView();
    if (!isDocView(view)) return;
    var section = utils.qs('.view[data-view="' + view + '"]');
    if (!section) return;
    utils.qsa("[data-doc-page-app-bar]", section).forEach(function (bar) {
      bar.innerHTML = barHtml(view);
    });
  }

  // Re-dispatches the same "khanna:navigate" event router.js itself fires
  // after every hash-driven render() — every document controller
  // (hotels.js/cover-letter.js/authorization.js/invitation.js) already
  // listens for this and does a full rebuild for its own standalone view,
  // so switching the active application from this bar (which deliberately
  // does NOT change the URL hash — the user stays on the same page) reuses
  // that exact same wiring instead of each controller needing a second,
  // bespoke "the active application changed under me" code path.
  function rerenderCurrentDocumentController() {
    var view = currentView();
    if (!isDocView(view)) return;
    document.dispatchEvent(new CustomEvent("khanna:navigate", { detail: { view: view, step: null } }));
  }

  function init() {
    document.addEventListener("khanna:navigate", function (e) {
      if (isDocView(e.detail.view)) render();
    });
    global.KhannaState.subscribe(render);

    utils.on(document, "click", "[data-action='create-doc-application']", function (e) {
      e.preventDefault();
      var user = global.KhannaAuth ? global.KhannaAuth.getCurrentUser() : null;
      global.KhannaState.createApplication(user ? user.email : "");
      rerenderCurrentDocumentController();
    });

    utils.on(document, "click", "[data-action='pick-doc-application']", function (e) {
      e.preventDefault();
      if (!global.KhannaApplicationPicker) return;
      global.KhannaApplicationPicker.open(function (app) {
        // setActiveApplicationId() does not call notify() (see
        // core/state.js) — it's a lightweight "which one is active"
        // pointer change, not a data mutation — so this bar and the
        // document controller are refreshed explicitly, same as the
        // "create new" path above.
        global.KhannaState.setActiveApplicationId(app.id);
        rerenderCurrentDocumentController();
      });
    });

    // "Use Existing Applicant" (Phase 2): pulls a saved person profile from
    // the reusable pool (core/state.js) onto whichever application is
    // active on this document page — creating a fresh one first if none is
    // active yet — so every field this document's controller reads from
    // `application.applicant` is auto-populated without retyping it.
    utils.on(document, "click", "[data-action='pick-doc-applicant']", function (e) {
      e.preventDefault();
      if (!global.KhannaApplicantPicker) return;
      global.KhannaApplicantPicker.open(function (profile) {
        var app = global.KhannaState.getActiveApplication();
        if (!app) {
          var user = global.KhannaAuth ? global.KhannaAuth.getCurrentUser() : null;
          app = global.KhannaState.createApplication(user ? user.email : "");
        }
        global.KhannaState.applyApplicantProfileToApplication(app.id, profile.id);
        rerenderCurrentDocumentController();
      });
    });

    if (isDocView(currentView())) render();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})(window);
