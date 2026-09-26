/* ==========================================================================
   Khanna Travels & Holidays — "Use Existing Applicant" picker
   Phase 2 of the document-centric rebuild (2026-09-25). A single reusable
   modal over the new, shared Applicant profile pool (KhannaState's
   getApplicantProfiles/searchApplicantProfiles — see core/state.js) so any
   document page can let staff reuse a person already entered once, instead
   of re-typing their details for every new document. Searches name,
   passport number, email, nationality and country — the person-level
   equivalent of application-picker.js's application-level search.

   This is deliberately its own file, not a copy-paste of
   application-picker.js (project rule 15: no duplicated logic) — it is a
   different search domain (people, not applications) even though the two
   look similar. Any caller does:

       global.KhannaApplicantPicker.open(function (profile) {
         // do whatever "an applicant profile was chosen" means here
       });

   "+ New Applicant" does not fabricate a blank-profile form here — a new
   applicant's data still comes from the real passport OCR/verification
   flow (project rule 9: no decorative functionality), so it simply closes
   the picker and sends staff to the Upload Passport page, which already
   saves straight into this same pool once a passport is verified.
   ========================================================================== */
(function (global) {
  "use strict";

  var utils = global.KhannaUtils;

  var overlayEl = null;
  var listEl = null;
  var searchInput = null;
  var currentOnSelect = null;
  var lastFocused = null;

  function passportNumber(p) {
    return (p.passport && p.passport.current && p.passport.current.number) || "";
  }

  function email(p) {
    return (p.contact && p.contact.email) || "";
  }

  function country(p) {
    return (p.address && p.address.country) || "";
  }

  function resultMetaHtml(p) {
    var bits = [];
    if (p.nationality) bits.push(utils.escapeHtml(p.nationality));
    if (passportNumber(p)) bits.push("Passport " + utils.escapeHtml(passportNumber(p)));
    if (country(p)) bits.push(utils.escapeHtml(country(p)));
    return bits.join(" · ");
  }

  function resultRowHtml(p) {
    return (
      '<button type="button" class="app-picker__result" data-action="pick-applicant" data-applicant-id="' +
      utils.escapeHtml(p.id) +
      '">' +
      '<span class="app-picker__result-main">' +
      "<strong>" + utils.escapeHtml(p.fullName || "Untitled applicant") + "</strong>" +
      "</span>" +
      '<span class="app-picker__result-meta">' + resultMetaHtml(p) + "</span>" +
      "</button>"
    );
  }

  function allProfiles() {
    return (global.KhannaState && global.KhannaState.getApplicantProfiles && global.KhannaState.getApplicantProfiles()) || [];
  }

  function renderResults() {
    if (!listEl || !searchInput) return;
    var rawQuery = searchInput.value || "";
    var all = allProfiles();

    if (all.length === 0) {
      listEl.innerHTML = '<p class="app-picker__empty">No saved applicants yet — use "+ New Applicant" to add one via Upload Passport.</p>';
      return;
    }

    var matches = rawQuery.trim()
      ? global.KhannaState.searchApplicantProfiles(rawQuery)
      : all;

    if (matches.length === 0) {
      listEl.innerHTML = '<p class="app-picker__empty">No applicants match “' + utils.escapeHtml(rawQuery) + '”.</p>';
      return;
    }

    listEl.innerHTML = matches.map(resultRowHtml).join("");
  }

  function close() {
    if (!overlayEl) return;
    overlayEl.setAttribute("hidden", "");
    currentOnSelect = null;
    var toFocus = lastFocused;
    lastFocused = null;
    if (toFocus && typeof toFocus.focus === "function") toFocus.focus();
  }

  function isOpen() {
    return !!overlayEl && !overlayEl.hasAttribute("hidden");
  }

  function ensureModal() {
    if (overlayEl) return;

    var wrap = document.createElement("div");
    wrap.className = "app-picker-overlay";
    wrap.setAttribute("hidden", "");
    wrap.innerHTML =
      '<div class="app-picker" role="dialog" aria-modal="true" aria-labelledby="applicantPickerTitle">' +
      '<div class="app-picker__header">' +
      '<h3 id="applicantPickerTitle">Use an existing applicant</h3>' +
      '<button type="button" class="btn-icon" data-action="close-applicant-picker" aria-label="Close">' +
      '<svg class="icon icon-sm" viewBox="0 0 24 24"><path d="M6 6l12 12M18 6 6 18"/></svg>' +
      "</button>" +
      "</div>" +
      '<div class="field app-picker__search-field">' +
      '<label for="applicantPickerSearch" class="sr-only">Search applicants by name, passport number, email, nationality or country</label>' +
      '<input type="search" id="applicantPickerSearch" placeholder="Search by name, passport number, email, nationality or country" autocomplete="off" />' +
      "</div>" +
      '<div class="app-picker__results" data-applicant-picker-results aria-live="polite"></div>' +
      '<div class="app-picker__footer">' +
      '<a class="btn btn-secondary btn-sm" href="#/upload-passport" data-nav-link="upload-passport" data-action="new-applicant-from-picker">+ New Applicant</a>' +
      "</div>" +
      "</div>";

    document.body.appendChild(wrap);
    overlayEl = wrap;
    listEl = wrap.querySelector("[data-applicant-picker-results]");
    searchInput = wrap.querySelector("#applicantPickerSearch");

    searchInput.addEventListener("input", renderResults);

    utils.on(wrap, "click", "[data-action='close-applicant-picker']", close);
    utils.on(wrap, "click", "[data-action='new-applicant-from-picker']", close);

    wrap.addEventListener("click", function (e) {
      if (e.target === wrap) close();
    });

    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape" && isOpen()) close();
    });

    utils.on(listEl, "click", "[data-action='pick-applicant']", function (e, target) {
      var id = target.getAttribute("data-applicant-id");
      var profile = id && global.KhannaState.getApplicantProfile ? global.KhannaState.getApplicantProfile(id) : null;
      if (!profile) return;
      var callback = currentOnSelect;
      close();
      if (callback) callback(profile);
    });

    global.KhannaState.subscribe(function () {
      if (isOpen()) renderResults();
    });
  }

  function open(onSelect) {
    ensureModal();
    currentOnSelect = typeof onSelect === "function" ? onSelect : null;
    lastFocused = document.activeElement;
    overlayEl.removeAttribute("hidden");
    searchInput.value = "";
    renderResults();
    searchInput.focus();
  }

  global.KhannaApplicantPicker = {
    open: open,
    close: close,
  };
})(window);
