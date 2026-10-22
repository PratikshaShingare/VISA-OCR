/* ==========================================================================
   Khanna Travels & Holidays — Standalone document page: active-application bar
   Phase 2 of the document-first redesign. Every standalone document page
   that now has a real, working document controller mounted (Cover Letter,
   Hotel Blocking, Company/Passport Authorization, Invitation Letter,
   Upload Passport since Phase 5 — Checklist Letter joins once it exists)
   shows the SAME small bar at the top: which application is currently
   active, and a way to start a fresh one without leaving the page.

   Phase 3 adds the other half: a "Use Existing Application" button next to
   "Create new application" (or "Start a different application"), backed by
   the shared global.KhannaApplicationPicker popover (a compact dropdown
   anchored under that button since the frontend rework's section 17 —
   originally a centered modal) — searchable by name, passport number,
   application ID, email and destination. Picking a result sets it active
   and re-renders the current document controller in place, exactly like
   the "create new" action already did.

   Frontend rework additions (sections 16-18): "Start a different
   application" now warns before discarding an application that was never
   explicitly saved (a Save/Discard/Cancel modal built further down this
   file), and a plain "Save" button sits next to it that just marks the
   active application explicitly saved and confirms with a toast — neither
   changes the underlying autosave-to-localStorage behaviour every field
   edit already had (see KhannaState.markApplicationSaved's own comment).

   Reuses global.KhannaState (createApplication/setActiveApplicationId/
   getActiveApplication/markApplicationSaved/applicationHasMeaningfulData),
   global.KhannaApplicationsList.applicantLabel, global.KhannaToast and
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
    // Invitation Letter: same treatment as Cover Letter — both pickers hidden
    // here, replaced by the page-level "Use Existing Details" dropdown
    // (Passport / Hotel Blocking) inside each of its two cards (invitation.js).
    "invitation-letter": { showApplicantPicker: false, showApplicationPicker: false, createLabelActive: null },
    // Company / Passport Authorization: same treatment as Cover Letter and
    // Invitation — both pickers hidden here, replaced by the page-level
    // "Use Existing Details" dropdown (Passport) inside each letter's card
    // (authorization.js).
    "company-authorization": { showApplicantPicker: false, showApplicationPicker: false, createLabelActive: null },
    "passport-authorization": { showApplicantPicker: false, showApplicationPicker: false, createLabelActive: null },
  };

  function configFor(view) {
    return VIEW_BUTTON_CONFIG[view] || { showApplicantPicker: true, showApplicationPicker: true, createLabelActive: null };
  }

  // ---- "Nothing filled in yet" guard for Save ---------------------------
  // An explicitly saved application is what the "Recent ..." lists and the
  // unsaved-work prompt treat as real work, so Save must refuse a page that
  // has nothing on it. Each document page reports whether the active
  // application holds anything for THAT page; the keys listed per page are
  // defaults or values derived from other fields (the consulate address
  // default, the country-derived recipient line ...) that don't count as the
  // user having filled something in.
  function hasAnyValue(value, ignore) {
    if (value === null || value === undefined) return false;
    if (typeof value === "string") return value.trim() !== "";
    if (typeof value === "number") return true;
    if (typeof value === "boolean") return false;
    if (Array.isArray(value)) {
      return value.some(function (v) { return hasAnyValue(v, ignore); });
    }
    return Object.keys(value).some(function (k) {
      return ignore.indexOf(k) === -1 && hasAnyValue(value[k], ignore);
    });
  }

  var COMMON_IGNORED = ["id", "generatedAt", "editedFields", "region", "recipientText", "consulateAddress", "cityCountry", "signatureFileRef", "signatureFileName"];
  // Filled in automatically (the destination country's consulate, and the
  // applicant's city/country of residence from their passport address), so
  // they don't count as the user having filled the letter in.
  var COVER_AUTO_KEYS = ["country", "consulateName", "destinationCountry", "cityOfResidence", "countryOfResidence"];

  function hasUsableHotel(app) {
    return (app.hotels || []).some(function (h) { return h.hotelName || h.checkIn || h.checkOut || h.city; });
  }

  // { ok, message } — message names what is missing, for the toast.
  function documentContentCheck(view, app) {
    if (!app) return { ok: false, message: "Nothing to save yet." };
    var ignore = COMMON_IGNORED;
    switch (view) {
      case "hotel-blocking":
        return hasUsableHotel(app) ? { ok: true } : { ok: false, message: "Nothing to save yet — add at least one hotel's details first." };
      case "cover-letter":
        return hasAnyValue(app.coverLetter, ignore.concat(COVER_AUTO_KEYS))
          ? { ok: true }
          : { ok: false, message: "Nothing to save yet — fill in the cover letter first." };
      case "passport-authorization":
        return hasAnyValue((app.authorization || {}).passport, ignore) ? { ok: true } : { ok: false, message: "Nothing to save yet — fill in the passport authorization letter first." };
      case "company-authorization": {
        var company = Object.assign({}, (app.authorization || {}).company || {});
        delete company.consulateCountry; // picking only the consulate fills nothing about the letter itself
        return hasAnyValue(company, ignore) ? { ok: true } : { ok: false, message: "Nothing to save yet — fill in the company authorization letter first." };
      }
      case "invitation-letter":
        return hasAnyValue(app.invitation, ignore) || hasAnyValue(app.initorsLetters, ignore)
          ? { ok: true }
          : { ok: false, message: "Nothing to save yet — fill in the invitation letter first." };
      default:
        return { ok: true };
    }
  }

  function actionButtonsHtml(view, hasActiveApp) {
    var cfg = configFor(view);
    var html = "";
    if (cfg.showApplicantPicker) {
      html += '<button class="btn btn-secondary btn-sm" type="button" data-action="pick-doc-applicant">Use Existing Applicant</button>';
    }
    if (cfg.showApplicationPicker) {
      // Section 17: labelled and marked up as a dropdown trigger — the
      // actual popover is js/application-picker.js's KhannaApplicationPicker,
      // opened anchored to this button (see the click handler below).
      html +=
        '<button class="btn btn-secondary btn-sm" type="button" data-action="pick-doc-application" aria-haspopup="true" aria-expanded="false">' +
        "Use Existing Application " +
        '<svg class="icon icon-sm" viewBox="0 0 24 24"><path d="m6 9 6 6 6-6"/></svg>' +
        "</button>";
    }
    // Section 18: a plain explicit Save, separate from "start fresh" — only
    // meaningful once there's an active application to save.
    if (hasActiveApp) {
      var check = documentContentCheck(view, global.KhannaState.getActiveApplication());
      // Looks unavailable but stays focusable/clickable so the click can say why.
      html +=
        '<button class="btn btn-secondary btn-sm' + (check.ok ? "" : " is-disabled") + '" type="button" data-action="save-doc-application"' +
        (check.ok ? "" : ' aria-disabled="true" title="' + utils.escapeHtml(check.message) + '"') +
        ">Save</button>";
    }
    var createLabel = hasActiveApp ? (cfg.createLabelActive || "Start a different application") : "Create new application";
    // Section 16: "Start a different application" gets a clearly
    // distinguishable style (not a plain .btn-secondary blending into the
    // row) since — unlike the other secondary actions here — it can
    // discard the current application's not-yet-saved work; "Create new
    // application" (no active app yet, nothing to lose) keeps the ordinary
    // primary look.
    var createClass = hasActiveApp ? "btn-warning" : "btn-primary";
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
    // This rebuilds the bar's innerHTML wholesale on every KhannaState
    // change (any field edit anywhere on the page, not just here) — which
    // would orphan the "Use Existing Application" popover (section 17) if
    // it happened to be open, since it's anchored to the specific button
    // DOM node this is about to replace. Closing it first is simpler and
    // safer than trying to re-anchor it to the freshly-rendered button.
    if (global.KhannaApplicationPicker) global.KhannaApplicationPicker.close();
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

  // ---------------------------------------------------------------------
  // Section 16: "Start a different application" confirmation modal.
  // A plain, self-built modal (same document.createElement pattern as
  // js/application-picker.js — project rule 15, one pattern for "a small
  // popup this file owns") rather than a bespoke confirm() call, since it
  // needs three distinct outcomes (Save & Continue / Discard & Continue /
  // Cancel), not a yes/no.
  // ---------------------------------------------------------------------
  var switchModalEl = null;
  var switchModalOnSave = null;
  var switchModalOnDiscard = null;

  function ensureSwitchModal() {
    if (switchModalEl) return;
    var wrap = document.createElement("div");
    wrap.className = "app-picker-overlay";
    wrap.setAttribute("hidden", "");
    wrap.innerHTML =
      '<div class="app-picker" role="dialog" aria-modal="true" aria-labelledby="switchAppModalTitle" style="max-width:420px;">' +
      '<div class="app-picker__header">' +
      '<h3 id="switchAppModalTitle">Unsaved application</h3>' +
      '<button type="button" class="btn-icon" data-action="switch-modal-cancel" aria-label="Close">' +
      '<svg class="icon icon-sm" viewBox="0 0 24 24"><path d="M6 6l12 12M18 6 6 18"/></svg>' +
      "</button>" +
      "</div>" +
      "<p>You have unsaved changes in this application. What would you like to do?</p>" +
      '<div style="display:flex;flex-direction:column;gap:var(--space-2);">' +
      '<button type="button" class="btn btn-primary btn-sm" data-action="switch-modal-save">Save &amp; Continue</button>' +
      '<button type="button" class="btn btn-warning btn-sm" data-action="switch-modal-discard">Discard &amp; Continue</button>' +
      '<button type="button" class="btn btn-secondary btn-sm" data-action="switch-modal-cancel">Cancel</button>' +
      "</div>" +
      "</div>";
    document.body.appendChild(wrap);
    switchModalEl = wrap;

    function close() {
      wrap.setAttribute("hidden", "");
      switchModalOnSave = null;
      switchModalOnDiscard = null;
    }

    utils.on(wrap, "click", "[data-action='switch-modal-cancel']", close);
    wrap.addEventListener("click", function (e) {
      if (e.target === wrap) close();
    });
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape" && !wrap.hasAttribute("hidden")) close();
    });
    utils.on(wrap, "click", "[data-action='switch-modal-save']", function () {
      var fn = switchModalOnSave;
      close();
      if (fn) fn();
    });
    utils.on(wrap, "click", "[data-action='switch-modal-discard']", function () {
      var fn = switchModalOnDiscard;
      close();
      if (fn) fn();
    });
  }

  function openSwitchConfirmModal(onSave, onDiscard) {
    ensureSwitchModal();
    switchModalOnSave = onSave;
    switchModalOnDiscard = onDiscard;
    switchModalEl.removeAttribute("hidden");
  }

  function startFreshApplication() {
    var user = global.KhannaAuth ? global.KhannaAuth.getCurrentUser() : null;
    global.KhannaState.createApplication(user ? user.email : "");
    rerenderCurrentDocumentController();
  }

  function init() {
    document.addEventListener("khanna:navigate", function (e) {
      if (isDocView(e.detail.view)) render();
    });
    global.KhannaState.subscribe(render);

    utils.on(document, "click", "[data-action='create-doc-application']", function (e) {
      e.preventDefault();
      var activeApp = global.KhannaState.getActiveApplication();
      // Only prompt when there's real, never-explicitly-saved work that
      // switching away from would actually lose — an application with
      // nothing entered yet, or one already saved, has nothing to confirm
      // (section 16: the modal is about protecting unsaved changes, not a
      // speed bump on every click).
      var needsConfirm =
        activeApp &&
        !activeApp.explicitlySavedAt &&
        global.KhannaState.applicationHasMeaningfulData(activeApp);
      if (needsConfirm) {
        openSwitchConfirmModal(
          function onSave() {
            var content = documentContentCheck(currentView(), activeApp);
            if (!content.ok) {
              if (global.KhannaToast) global.KhannaToast.show(content.message, { type: "error" });
              return;
            }
            if (!global.KhannaApplicationsList.hasName(activeApp)) {
              if (global.KhannaToast) global.KhannaToast.show("Enter the applicant's name before saving.", { type: "error" });
              return;
            }
            global.KhannaState.markApplicationSaved(activeApp.id);
            startFreshApplication();
          },
          function onDiscard() {
            global.KhannaState.deleteApplication(activeApp.id);
            startFreshApplication();
          }
        );
        return;
      }
      startFreshApplication();
    });

    utils.on(document, "click", "[data-action='save-doc-application']", function (e) {
      e.preventDefault();
      var app = global.KhannaState.getActiveApplication();
      if (!app) return;
      var content = documentContentCheck(currentView(), app);
      if (!content.ok) {
        if (global.KhannaToast) global.KhannaToast.show(content.message, { type: "error" });
        return;
      }
      if (!global.KhannaApplicationsList.hasName(app)) {
        if (global.KhannaToast) global.KhannaToast.show("Enter the applicant's name before saving.", { type: "error" });
        return;
      }
      global.KhannaState.markApplicationSaved(app.id);
      if (global.KhannaToast) global.KhannaToast.show("Saved successfully");
    });

    utils.on(document, "click", "[data-action='pick-doc-application']", function (e, target) {
      e.preventDefault();
      if (!global.KhannaApplicationPicker) return;
      global.KhannaApplicationPicker.open(target, function (app) {
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
