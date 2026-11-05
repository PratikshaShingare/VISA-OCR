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
  var BOOKKEEPING_KEYS = ["id", "status", "createdBy", "createdAt", "updatedAt", "hotels", "notes", "activity", "lastDocView", "explicitlySavedAt", "docQueue"];

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

  // The Applications page lists applications with exactly the same rows as the
  // Dashboard's Recent Applications (KhannaDashboard.listHtml, js/dashboard.js):
  // name, updated time, documents generated, a blue eye that opens the
  // generated document's preview and a red bin that asks before deleting.
  // Both buttons are handled by dashboard.js's document-level listeners.
  var EMPTY_HTML =
    '<div class="empty-state">' +
    '<svg class="icon" viewBox="0 0 24 24"><path d="M4 6a2 2 0 0 1 2-2h4l2 2h6a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6Z"/></svg>' +
    "<h3>No applications yet</h3>" +
    "</div>";

  // Every application that has a name, newest activity first (the store
  // already keeps newest first). Shared with the Admin page's overview.
  function listedApplications() {
    return global.KhannaState.getApplications().filter(hasName);
  }

  // Row list markup for `apps` (or the empty state).
  function listHtml(apps) {
    if (!apps.length) return EMPTY_HTML;
    return global.KhannaDashboard ? global.KhannaDashboard.listHtml(apps) : EMPTY_HTML;
  }

  function render() {
    var container = utils.qs("[data-applications-list]");
    if (!container) return;
    container.innerHTML = listHtml(listedApplications());
  }

  function init() {
    render();
    global.KhannaState.subscribe(render);
    document.addEventListener("khanna:navigate", function (e) {
      if (e.detail.view === "applications") render();
    });
  }

  global.KhannaApplicationsList = {
    applicantLabel: applicantLabel,
    hasName: hasName,
    UNTITLED: UNTITLED,
    isHotelBlockingOnly: isHotelBlockingOnly,
    isCoverLetterOnly: isCoverLetterOnly,
    isPassportOnly: isPassportOnly,
    listedApplications: listedApplications,
    listHtml: listHtml,
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})(window);
