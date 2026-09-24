/* ==========================================================================
   Khanna Travels & Holidays — "Use Existing Application" picker
   Phase 3 of the document-first redesign. A single reusable modal that
   lists every Application record and filters it live as the user types,
   matching against applicant name, application ID, passport number, email
   and destination — the exact five fields the redesign spec calls for.

   This is deliberately ONE shared component (project rule 15: no
   duplicated logic) rather than a bespoke search box per page. Any part of
   the app that needs to let someone resume an existing application calls:

       global.KhannaApplicationPicker.open(function (app) {
         // do whatever "an application was chosen" means on this page
       });

   The picker itself never decides what happens next — it only finds an
   Application record and hands it back. Phase 2's document-workspace.js is
   the first caller (it sets the chosen application active and re-renders
   the current document controller in place); other callers are free to
   navigate elsewhere instead, exactly like the existing "Open Full
   Application" button in applications.js does today.

   Reuses global.KhannaState (getApplications/getApplication) and
   global.KhannaApplicationsList.applicantLabel — no new "what's this
   application called" logic, no second copy of the applicant-name
   fallback rule.
   ========================================================================== */
(function (global) {
  "use strict";

  var utils = global.KhannaUtils;

  var overlayEl = null;
  var listEl = null;
  var searchInput = null;
  var currentOnSelect = null;
  var lastFocused = null;

  function applicantLabel(app) {
    return global.KhannaApplicationsList ? global.KhannaApplicationsList.applicantLabel(app) : "Untitled applicant";
  }

  function passportNumber(app) {
    return (app.applicant && app.applicant.passport && app.applicant.passport.current && app.applicant.passport.current.number) || "";
  }

  function applicantEmail(app) {
    return (app.applicant && app.applicant.contact && app.applicant.contact.email) || "";
  }

  function destination(app) {
    return (app.travel && app.travel.destination) || "";
  }

  // One lowercased, space-joined string per application covering every
  // field the redesign spec asks this picker to search: name, passport,
  // application ID, email, destination.
  function haystack(app) {
    return [applicantLabel(app), app.id, passportNumber(app), applicantEmail(app), destination(app)]
      .join(" ")
      .toLowerCase();
  }

  function resultMetaHtml(app) {
    var bits = [];
    if (destination(app)) bits.push(utils.escapeHtml(destination(app)));
    if (passportNumber(app)) bits.push("Passport " + utils.escapeHtml(passportNumber(app)));
    bits.push(utils.escapeHtml(app.id));
    return bits.join(" · ");
  }

  function resultRowHtml(app) {
    return (
      '<button type="button" class="app-picker__result" data-action="pick-application" data-app-id="' +
      utils.escapeHtml(app.id) + '">' +
      '<span class="app-picker__result-main">' +
      "<strong>" + utils.escapeHtml(applicantLabel(app)) + "</strong>" +
      '<span class="badge ' + utils.statusBadgeClass(app.status) + '">' + utils.escapeHtml(app.status) + "</span>" +
      "</span>" +
      '<span class="app-picker__result-meta">' + resultMetaHtml(app) + "</span>" +
      "</button>"
    );
  }

  function allApplications() {
    return (global.KhannaState && global.KhannaState.getApplications && global.KhannaState.getApplications()) || [];
  }

  function renderResults() {
    if (!listEl || !searchInput) return;
    var rawQuery = searchInput.value || "";
    var query = rawQuery.trim().toLowerCase();
    var all = allApplications();

    if (all.length === 0) {
      listEl.innerHTML = '<p class="app-picker__empty">No applications yet — create one instead.</p>';
      return;
    }

    var matches = query
      ? all.filter(function (app) {
          return haystack(app).indexOf(query) !== -1;
        })
      : all;

    if (matches.length === 0) {
      listEl.innerHTML = '<p class="app-picker__empty">No applications match “' + utils.escapeHtml(rawQuery) + '”.</p>';
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
      '<div class="app-picker" role="dialog" aria-modal="true" aria-labelledby="appPickerTitle">' +
      '<div class="app-picker__header">' +
      '<h3 id="appPickerTitle">Use an existing application</h3>' +
      '<button type="button" class="btn-icon" data-action="close-app-picker" aria-label="Close">' +
      '<svg class="icon icon-sm" viewBox="0 0 24 24"><path d="M6 6l12 12M18 6 6 18"/></svg>' +
      "</button>" +
      "</div>" +
      '<div class="field app-picker__search-field">' +
      '<label for="appPickerSearch" class="sr-only">Search applications by name, passport number, application ID, email or destination</label>' +
      '<input type="search" id="appPickerSearch" placeholder="Search by name, passport number, ID, email or destination" autocomplete="off" />' +
      "</div>" +
      '<div class="app-picker__results" data-app-picker-results aria-live="polite"></div>' +
      "</div>";

    document.body.appendChild(wrap);
    overlayEl = wrap;
    listEl = wrap.querySelector("[data-app-picker-results]");
    searchInput = wrap.querySelector("#appPickerSearch");

    searchInput.addEventListener("input", renderResults);

    utils.on(wrap, "click", "[data-action='close-app-picker']", close);

    // Backdrop click closes — only when the click landed on the overlay
    // itself, not something inside the card.
    wrap.addEventListener("click", function (e) {
      if (e.target === wrap) close();
    });

    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape" && isOpen()) close();
    });

    utils.on(listEl, "click", "[data-action='pick-application']", function (e, target) {
      var id = target.getAttribute("data-app-id");
      var app = id && global.KhannaState.getApplication ? global.KhannaState.getApplication(id) : null;
      if (!app) return;
      var callback = currentOnSelect;
      close();
      if (callback) callback(app);
    });

    // Keep the list in sync with live state changes (e.g. another tab/admin
    // action deletes or renames an application) while the picker is open.
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

  global.KhannaApplicationPicker = {
    open: open,
    close: close,
  };
})(window);
