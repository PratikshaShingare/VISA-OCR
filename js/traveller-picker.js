/* ==========================================================================
   Khanna Travels & Holidays — "Use Existing Traveller" picker
   The traveller-side equivalent of applicant-picker.js (Phase 2), added in
   the Phase 5 pass. Lets staff add a traveller already on file (saved from
   any earlier application) onto the CURRENT application instead of
   re-typing their passport/contact details from scratch — this was the one
   explicitly-flagged remaining gap from Phase 2 ("no picker UI yet to pull
   a saved traveller into a new application").

   Deliberately its own file, not folded into applicant-picker.js (project
   rule 15 cuts both ways: sharing the near-identical modal chrome would
   mean either file guessing which pool/callback shape the other wants).
   Any caller does:

       global.KhannaTravellerPicker.open(function (profile) {
         // do whatever "a traveller profile was chosen" means here
       });

   There is no "+ New Traveller" shortcut here the way applicant-picker.js
   has "+ New Applicant" -> Upload Passport: a traveller has no equivalent
   OCR-first entry point (Upload Passport only ever saves the ONE main
   applicant), so "new traveller" already means "click Add Traveller and
   type them in" — the existing, unchanged flow in travellers.js. This
   picker only ever ADDS a person who already exists in the saved pool.
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

  function country(p) {
    return (p.address && p.address.country) || "";
  }

  function resultMetaHtml(p) {
    var bits = [];
    if (p.relation) bits.push(utils.escapeHtml(p.relation));
    if (p.nationality) bits.push(utils.escapeHtml(p.nationality));
    if (passportNumber(p)) bits.push("Passport " + utils.escapeHtml(passportNumber(p)));
    if (country(p)) bits.push(utils.escapeHtml(country(p)));
    return bits.join(" · ");
  }

  function resultRowHtml(p) {
    return (
      '<button type="button" class="app-picker__result" data-action="pick-traveller" data-traveller-profile-id="' +
      utils.escapeHtml(p.id) +
      '">' +
      '<span class="app-picker__result-main">' +
      "<strong>" + utils.escapeHtml(p.fullName || "Untitled traveller") + "</strong>" +
      "</span>" +
      '<span class="app-picker__result-meta">' + resultMetaHtml(p) + "</span>" +
      "</button>"
    );
  }

  function allProfiles() {
    return (global.KhannaState && global.KhannaState.getTravellerProfiles && global.KhannaState.getTravellerProfiles()) || [];
  }

  function renderResults() {
    if (!listEl || !searchInput) return;
    var rawQuery = searchInput.value || "";
    var all = allProfiles();

    if (all.length === 0) {
      listEl.innerHTML = '<p class="app-picker__empty">No saved travellers yet — use "Add Traveller" to enter one, and it becomes reusable here from then on.</p>';
      return;
    }

    var matches = rawQuery.trim()
      ? global.KhannaState.searchTravellerProfiles(rawQuery)
      : all;

    if (matches.length === 0) {
      listEl.innerHTML = '<p class="app-picker__empty">No travellers match “' + utils.escapeHtml(rawQuery) + '”.</p>';
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
      '<div class="app-picker" role="dialog" aria-modal="true" aria-labelledby="travellerPickerTitle">' +
      '<div class="app-picker__header">' +
      '<h3 id="travellerPickerTitle">Use an existing traveller</h3>' +
      '<button type="button" class="btn-icon" data-action="close-traveller-picker" aria-label="Close">' +
      '<svg class="icon icon-sm" viewBox="0 0 24 24"><path d="M6 6l12 12M18 6 6 18"/></svg>' +
      "</button>" +
      "</div>" +
      '<div class="field app-picker__search-field">' +
      '<label for="travellerPickerSearch" class="sr-only">Search travellers by name, passport number, email, nationality or country</label>' +
      '<input type="search" id="travellerPickerSearch" placeholder="Search by name, passport number, email, nationality or country" autocomplete="off" />' +
      "</div>" +
      '<div class="app-picker__results" data-traveller-picker-results aria-live="polite"></div>' +
      "</div>";

    document.body.appendChild(wrap);
    overlayEl = wrap;
    listEl = wrap.querySelector("[data-traveller-picker-results]");
    searchInput = wrap.querySelector("#travellerPickerSearch");

    searchInput.addEventListener("input", renderResults);

    utils.on(wrap, "click", "[data-action='close-traveller-picker']", close);

    wrap.addEventListener("click", function (e) {
      if (e.target === wrap) close();
    });

    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape" && isOpen()) close();
    });

    utils.on(listEl, "click", "[data-action='pick-traveller']", function (e, target) {
      var id = target.getAttribute("data-traveller-profile-id");
      var profile = id && global.KhannaState.getTravellerProfile ? global.KhannaState.getTravellerProfile(id) : null;
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

  global.KhannaTravellerPicker = {
    open: open,
    close: close,
  };
})(window);
