/* ==========================================================================
   Khanna Travels & Holidays — "Use Existing Application" picker
   Phase 3 of the document-first redesign. A single reusable component that
   lists every Application record and filters it live as the user types,
   matching against applicant name, application ID, passport number, email
   and destination — the exact five fields the redesign spec calls for.

   Frontend rework (section 17): converted from a centered full-screen
   modal to a small anchored popover directly under the "Use Existing
   Application" button that opens it — "a compact dropdown/popover...
   do NOT create a huge full-page selector". The search/filter/select logic
   below is unchanged from the original modal version (project rule 15 — no
   reason to rewrite working logic just to change how it's positioned).

   This is deliberately ONE shared component (project rule 15: no
   duplicated logic) rather than a bespoke search box per page. Any part of
   the app that needs to let someone resume an existing application calls:

       global.KhannaApplicationPicker.open(anchorEl, function (app) {
         // do whatever "an application was chosen" means on this page
       });

   `anchorEl` is the button the popover opens beneath (also where focus
   returns on close). The picker itself never decides what happens next —
   it only finds an Application record and hands it back.
   Document-workspace.js is the current caller (it sets the chosen
   application active and re-renders the current document controller in
   place).

   Reuses global.KhannaState (getApplications/getApplication) and
   global.KhannaApplicationsList.applicantLabel — no new "what's this
   application called" logic, no second copy of the applicant-name
   fallback rule.
   ========================================================================== */
(function (global) {
  "use strict";

  var utils = global.KhannaUtils;

  var popoverEl = null;
  var listEl = null;
  var searchInput = null;
  var currentOnSelect = null;
  var lastFocused = null;
  var anchorEl = null;

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
      listEl.innerHTML = '<p class="app-picker__empty">No applications yet.</p>';
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

  function outsideClick(e) {
    if (!popoverEl) return;
    if (popoverEl.contains(e.target)) return;
    if (anchorEl && anchorEl.contains(e.target)) return;
    close();
  }

  function close() {
    if (!popoverEl) return;
    popoverEl.setAttribute("hidden", "");
    if (anchorEl) anchorEl.setAttribute("aria-expanded", "false");
    currentOnSelect = null;
    document.removeEventListener("click", outsideClick, true);
    var toFocus = lastFocused;
    lastFocused = null;
    anchorEl = null;
    if (toFocus && typeof toFocus.focus === "function") toFocus.focus();
  }

  function isOpen() {
    return !!popoverEl && !popoverEl.hasAttribute("hidden");
  }

  // Positions the popover directly under its anchor button, flipping to
  // align with the anchor's right edge instead of its left when there
  // isn't room to the right (narrow viewports / a button near the edge of
  // the screen) — kept as plain fixed-position math (not CSS anchoring,
  // for wider browser support) since this only needs to run once per open.
  function positionPopover() {
    if (!popoverEl || !anchorEl) return;
    var rect = anchorEl.getBoundingClientRect();
    var popRect = popoverEl.getBoundingClientRect();
    var margin = 8;
    var left = rect.left;
    if (left + popRect.width > window.innerWidth - margin) {
      left = rect.right - popRect.width;
    }
    left = Math.max(margin, left);
    var top = rect.bottom + 6;
    popoverEl.style.left = left + "px";
    popoverEl.style.top = top + "px";
  }

  function ensurePopover() {
    if (popoverEl) return;

    var wrap = document.createElement("div");
    wrap.className = "app-picker-popover";
    wrap.setAttribute("hidden", "");
    wrap.innerHTML =
      '<div class="app-picker" role="dialog" aria-modal="false" aria-labelledby="appPickerTitle">' +
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
    popoverEl = wrap;
    listEl = wrap.querySelector("[data-app-picker-results]");
    searchInput = wrap.querySelector("#appPickerSearch");

    searchInput.addEventListener("input", renderResults);

    utils.on(wrap, "click", "[data-action='close-app-picker']", close);

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

    // Reposition on viewport resize while open (e.g. rotating a device, or
    // resizing a desktop window) rather than leaving it pinned to a stale
    // coordinate.
    window.addEventListener("resize", function () {
      if (isOpen()) positionPopover();
    });
  }

  /**
   * @param {HTMLElement} anchor - the button this popover opens beneath.
   * @param {function} onSelect - called with the chosen Application record.
   */
  function open(anchor, onSelect) {
    ensurePopover();
    if (isOpen() && anchorEl === anchor) {
      close();
      return;
    }
    anchorEl = anchor;
    currentOnSelect = typeof onSelect === "function" ? onSelect : null;
    lastFocused = document.activeElement;
    popoverEl.removeAttribute("hidden");
    if (anchorEl) anchorEl.setAttribute("aria-expanded", "true");
    searchInput.value = "";
    renderResults();
    positionPopover();
    searchInput.focus();
    // Registered after this click's own event has finished bubbling —
    // otherwise the very click that opens the popover would immediately
    // close it again (it's a document-level listener with no wrap-relative
    // check like the old backdrop click had).
    setTimeout(function () {
      document.addEventListener("click", outsideClick, true);
    }, 0);
  }

  global.KhannaApplicationPicker = {
    open: open,
    close: close,
  };
})(window);
