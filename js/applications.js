/* ==========================================================================
   Khanna Travels & Holidays — Applications list view controller
   Lists every Application record from the central state store. Search /
   filter / sort controls are deliberately left out until Phase 6 gives
   applications real distinguishing data (destination, documents) to filter
   by — an input box that doesn't filter anything yet would be decorative.
   ========================================================================== */

(function (global) {
  "use strict";

  var utils = global.KhannaUtils;

  var UNTITLED = "Untitled applicant";

  function clean(value) {
    return typeof value === "string" && value.trim() ? value.trim() : "";
  }

  // The name an application is listed under (Dashboard, Applications list,
  // pickers, "Working on ..." bar). Staff often start an application from a
  // document page (Cover Letter, Hotel Blocking, an Authorization Letter)
  // without ever filling the main applicant record, so after the real
  // applicant name the first name that was actually typed anywhere on the
  // application is used instead of "Untitled applicant". Nothing is
  // invented: if no name exists anywhere, it still reads "Untitled applicant".
  function applicantLabel(app) {
    var name = clean(app.applicant && app.applicant.fullName);
    if (name) return name;

    name = clean(app.coverLetter && app.coverLetter.manualApplicantName);
    if (name) return name;

    var travellers = app.travellers || [];
    for (var t = 0; t < travellers.length; t++) {
      name = clean(travellers[t] && travellers[t].fullName);
      if (name) return name;
    }

    // Passports added to the Cover Letter through "Use Existing Details".
    var imported = (app.coverLetter && app.coverLetter.importedPeople) || [];
    for (var i = 0; i < imported.length; i++) {
      name = clean(imported[i] && imported[i].fullName);
      if (name) return name;
    }

    var manual = (app.authorization && app.authorization.company && app.authorization.company.manualApplicants) || [];
    for (var m = 0; m < manual.length; m++) {
      name = clean(manual[m] && manual[m].fullName);
      if (name) return name;
    }

    var hotels = app.hotels || [];
    for (var h = 0; h < hotels.length; h++) {
      name = clean(hotels[h] && hotels[h].leadGuestName);
      if (name) return name;
      var guests = (hotels[h] && hotels[h].guestNames) || [];
      for (var g = 0; g < guests.length; g++) {
        name = clean(guests[g]);
        if (name) return name;
      }
    }
    return UNTITLED;
  }

  // True once a real name exists anywhere on the application.
  function hasName(app) {
    return !!app && applicantLabel(app) !== UNTITLED;
  }

  // An application whose ONLY content is hotel blocking (started from the
  // Hotel Blocking page, nothing else ever filled in). Those live on the
  // Hotel Blocking page's own "Recent Hotel Blockings" list, not on the
  // Dashboard's Recent Applications. Decided by comparing the record with a
  // pristine one, ignoring only bookkeeping (ids, dates, status, the hotels
  // themselves, notes, activity log) — so ANY other data (an applicant, a
  // traveller, a generated letter, an uploaded document...) makes it a normal
  // application again.
  var BOOKKEEPING_KEYS = ["id", "status", "createdBy", "createdAt", "updatedAt", "hotels", "notes", "activity", "lastDocView", "explicitlySavedAt"];

  function withoutIds(value) {
    return JSON.stringify(value, function (key, v) {
      return key === "id" ? undefined : v;
    });
  }

  // True when `app` holds nothing but its own `ownKey` section (everything
  // else is still exactly as a brand-new application starts).
  function holdsOnly(app, ownKey) {
    var pristine = global.KhannaState.createEmptyApplication("");
    return Object.keys(pristine)
      .concat(Object.keys(app))
      .every(function (key) {
        if (key === ownKey || BOOKKEEPING_KEYS.indexOf(key) !== -1) return true;
        return withoutIds(app[key]) === withoutIds(pristine[key]);
      });
  }

  function isHotelBlockingOnly(app) {
    if (!app || !(app.hotels || []).length) return false;
    var pristine = global.KhannaState.createEmptyApplication("");
    return Object.keys(pristine)
      .concat(Object.keys(app))
      .every(function (key) {
        if (BOOKKEEPING_KEYS.indexOf(key) !== -1) return true;
        return withoutIds(app[key]) === withoutIds(pristine[key]);
      });
  }

  // An application that exists only because of a Cover Letter (nothing else
  // saved on it). Used by Recent Cover Letters' Delete.
  function isCoverLetterOnly(app) {
    return !!(app && app.coverLetter && app.coverLetter.region) && holdsOnly(app, "coverLetter");
  }

  // An application that exists only because of a saved passport/applicant.
  function isPassportOnly(app) {
    return !!app && holdsOnly(app, "applicant");
  }

  var TRASH_ICON = '<svg class="icon icon-sm" viewBox="0 0 24 24"><path d="M4 7h16M9 7V5a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2m2 0-1 13a1 1 0 0 1-1 1H8a1 1 0 0 1-1-1L6 7"/></svg>';

  // Same row anatomy as Recent Hotel Blockings / Recent Cover Letters
  // (.hb-row in css/hotel-blockings.css): name + meta on the left, small
  // secondary action buttons and a red-outline Delete on the right.
  function rowHtml(app) {
    var id = utils.escapeHtml(app.id);
    return (
      '<div class="card hb-row">' +
      '<div class="hb-row__info">' +
      '<div class="hb-row__name">' + utils.escapeHtml(applicantLabel(app)) + "</div>" +
      '<div class="hb-row__meta hb-row__meta--faint">' +
      id + " · Created " + utils.formatDate(app.createdAt) +
      "</div>" +
      "</div>" +
      '<div class="hb-row__actions">' +
      '<button class="btn btn-secondary btn-sm" type="button" data-action="open-application" data-app-id="' + id + '">Open Full Application</button>' +
      '<button class="btn btn-danger-outline btn-sm" type="button" data-action="delete-application" data-app-id="' + id + '">' +
      TRASH_ICON + "Delete</button>" +
      "</div>" +
      "</div>"
    );
  }

  /* ---------------- delete confirmation popup (same pattern as Recent
     Hotel Blockings / Recent Cover Letters / Dashboard: a red Delete button
     must never delete on the first click) ---------------- */
  var modalEl = null;
  var pendingDeleteId = null;
  var lastFocus = null;

  function closeModal() {
    if (!modalEl) return;
    modalEl.hidden = true;
    pendingDeleteId = null;
    if (lastFocus && lastFocus.focus && document.contains(lastFocus)) lastFocus.focus();
  }

  function ensureModal() {
    if (modalEl) return;
    var wrap = document.createElement("div");
    wrap.className = "app-picker-overlay";
    wrap.setAttribute("hidden", "");
    wrap.setAttribute("data-app-delete-modal", "");
    wrap.innerHTML =
      '<div class="app-picker" role="dialog" aria-modal="true" aria-labelledby="appDeleteTitle" style="max-width:440px;">' +
      '<div class="app-picker__header">' +
      '<h3 id="appDeleteTitle">Delete application?</h3>' +
      '<button type="button" class="btn-icon" data-app-delete-cancel aria-label="Close">' +
      '<svg class="icon icon-sm" viewBox="0 0 24 24"><path d="M6 6l12 12M18 6 6 18"/></svg>' +
      "</button>" +
      "</div>" +
      '<p data-app-delete-text style="margin:0;"></p>' +
      '<div style="display:flex;gap:var(--space-2);justify-content:flex-end;flex-wrap:wrap;">' +
      '<button type="button" class="btn btn-secondary btn-sm" data-app-delete-cancel>Cancel</button>' +
      '<button type="button" class="btn btn-danger btn-sm" data-app-delete-confirm>Delete Application</button>' +
      "</div>" +
      "</div>";
    document.body.appendChild(wrap);
    modalEl = wrap;

    utils.on(wrap, "click", "[data-app-delete-cancel]", closeModal);
    wrap.addEventListener("click", function (e) {
      if (e.target === wrap) closeModal();
    });
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape" && !wrap.hasAttribute("hidden")) closeModal();
    });
    utils.on(wrap, "click", "[data-app-delete-confirm]", function () {
      var id = pendingDeleteId;
      closeModal();
      if (id) global.KhannaState.deleteApplication(id);
    });
  }

  function openDeleteModal(appId, trigger) {
    var app = global.KhannaState.getApplication(appId);
    if (!app) return;
    ensureModal();
    pendingDeleteId = appId;
    lastFocus = trigger || document.activeElement;
    utils.qs("[data-app-delete-text]", modalEl).textContent =
      "Are you sure you want to delete the application for " + applicantLabel(app) +
      "? This removes the application and everything saved on it (passport data, travellers, hotels, letters) from this browser and cannot be undone.";
    modalEl.hidden = false;
    var cancel = modalEl.querySelector("button[data-app-delete-cancel].btn-secondary");
    if (cancel) cancel.focus();
  }

  function render() {
    var container = utils.qs("[data-applications-list]");
    if (!container) return;
    var apps = global.KhannaState.getApplications().filter(hasName);

    if (apps.length === 0) {
      container.innerHTML =
        '<div class="empty-state">' +
        '<svg class="icon" viewBox="0 0 24 24"><path d="M4 6a2 2 0 0 1 2-2h4l2 2h6a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6Z"/></svg>' +
        "<h3>No applications yet</h3>" +
        "</div>";
      return;
    }

    container.innerHTML = '<div class="hb-list">' + apps.map(rowHtml).join("") + "</div>";
  }

  function init() {
    render();
    global.KhannaState.subscribe(render);
    document.addEventListener("khanna:navigate", function (e) {
      if (e.detail.view === "applications") render();
    });

    utils.on(document, "click", "[data-action='delete-application']", function (e, target) {
      e.preventDefault();
      var id = target.getAttribute("data-app-id");
      if (id) openDeleteModal(id, target);
    });
  }

  global.KhannaApplicationsList = {
    applicantLabel: applicantLabel,
    hasName: hasName,
    UNTITLED: UNTITLED,
    isHotelBlockingOnly: isHotelBlockingOnly,
    isCoverLetterOnly: isCoverLetterOnly,
    isPassportOnly: isPassportOnly,
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})(window);
