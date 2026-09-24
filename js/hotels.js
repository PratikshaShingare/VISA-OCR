/* ==========================================================================
   Khanna Travels & Holidays — Hotel blocking (wizard step 5)
   Data entry for every hotel booked/blocked on this application, plus a
   real "Generate Hotel Voucher" action that calls the backend
   (backend/python/hotel_voucher_engine.py) to produce the actual company
   Hotel Voucher document — built from the real, unmodified reference
   template in reference-hotel-blocking-formats/, not a recreation (project
   rule 5). Supports any number of hotels: the backend clones the template's
   own heading+table block once per hotel, exactly matching how the real
   "Multiple Hotels" reference example itself repeats that block.

   Re-render discipline (same as travellers.js/documents.js): the hotel
   LIST redraws on every state change; the open EDIT PANEL only opens,
   closes or swaps on an explicit user action.
   ========================================================================== */
(function (global) {
  "use strict";

  var utils = global.KhannaUtils;
  var api = global.KhannaApi;

  // Phase 4 (document-first redesign) fix: "which hotel's panel is open" used
  // to be ONE shared module-level variable. That was safe when only a single
  // root (the wizard's step-5 root) could ever exist — but Phase 2 made this
  // controller dual-mount onto a SECOND, independent root (the standalone
  // Hotel Blocking page), and both can be mounted (and keep their own stale
  // DOM/listeners) at the same time. With one shared variable, opening a
  // hotel's panel on the wizard and then switching to the standalone page
  // (which may still be showing a DIFFERENT hotel's panel from an earlier
  // visit, never cleared on navigation) meant editing what looked like hotel
  // B's fields there could silently write to hotel A's record instead — the
  // exact same cross-record-corruption bug class the original build's own
  // Phase 13 hit once already (there, from a re-wired listener; here, from
  // shared state across two simultaneously-mounted roots). Found by
  // reasoning about this file's own historical bug comment below in light of
  // Phase 2's dual-mount change, then confirmed with a dedicated regression
  // test before this fix (see phase4_test.py).
  //
  // Fix: track the open hotel id PER ROOT (as a data attribute on that root
  // element) instead of in one shared variable, via getActiveHotelId(r)/
  // setActiveHotelId(r, id) below — mirroring how `dataset.mounted` already
  // solved this exact "two roots, one module" problem for mount state.
  function getActiveHotelId(r) {
    return (r && r.dataset.activeHotelId) || null;
  }

  function setActiveHotelId(r, id) {
    if (!r) return;
    if (id) r.dataset.activeHotelId = id;
    else delete r.dataset.activeHotelId;
  }

  var HOTEL_FIELDS = [
    { key: "hotelName", label: "Hotel name", required: true },
    { key: "phone", label: "Hotel phone number" },
    { key: "address", label: "Hotel address" },
    { key: "city", label: "City", required: true },
    { key: "confirmationNumber", label: "Booking confirmation number" },
    { key: "leadGuestName", label: "Lead guest name" },
    { key: "noOfGuests", label: "No. of guests", type: "number" },
    { key: "noOfRooms", label: "No. of rooms", type: "number" },
    { key: "roomType", label: "Room type", placeholder: "e.g. Deluxe Double" },
    { key: "checkIn", label: "Check-in date", type: "date", required: true },
    { key: "checkOut", label: "Check-out date", type: "date", required: true },
  ];

  // Document-first redesign (Phase 2): this controller now mounts into
  // either the wizard's step-5 root (unchanged) or the standalone Hotel
  // Blocking page's own root, chosen by the current view — every other
  // function in this file reaches the DOM exclusively through root() (or a
  // local var set from it), so this is the only change needed to make the
  // whole module dual-mount; nothing else here knows or cares which root
  // it ended up in.
  function root() {
    var view = global.KhannaRouter ? global.KhannaRouter.parseHash().view : null;
    if (view === "hotel-blocking") return utils.qs("[data-hotel-blocking-page-root]");
    return utils.qs("[data-hotels-step-root]");
  }

  function getApp() {
    return global.KhannaState.getActiveApplication();
  }

  function hotelLabel(h) {
    return h.hotelName || "Unnamed hotel";
  }

  function isHotelComplete(h) {
    return !!(h.hotelName && h.city && h.checkIn && h.checkOut);
  }

  function nightsBetween(checkIn, checkOut) {
    if (!checkIn || !checkOut) return null;
    var d1 = new Date(checkIn + "T00:00:00");
    var d2 = new Date(checkOut + "T00:00:00");
    if (isNaN(d1.getTime()) || isNaN(d2.getTime())) return null;
    var n = Math.round((d2 - d1) / 86400000);
    return n >= 0 ? n : null;
  }

  function cardHtml(h, activeId) {
    var nights = nightsBetween(h.checkIn, h.checkOut);
    var dateRange = h.checkIn && h.checkOut
      ? utils.formatDate(h.checkIn) + " → " + utils.formatDate(h.checkOut) +
        (nights !== null ? " (" + nights + " night" + (nights === 1 ? "" : "s") + ")" : "")
      : "Dates not set";
    return (
      '<div class="hotel-card' + (h.id === activeId ? " is-editing" : "") + '" data-hotel-card="' + h.id + '">' +
      '<div class="hotel-card__info">' +
      '<div class="hotel-card__name">' + utils.escapeHtml(hotelLabel(h)) + "</div>" +
      '<div class="hotel-card__meta">' + utils.escapeHtml((h.city ? h.city + " · " : "") + dateRange) + "</div>" +
      "</div>" +
      (isHotelComplete(h) ? '<span class="badge badge-success">Ready</span>' : '<span class="badge badge-warning">Incomplete</span>') +
      '<div class="hotel-card__actions">' +
      '<button class="btn btn-secondary btn-sm" type="button" data-action="edit-hotel" data-hotel-id="' + h.id + '">' +
      (h.id === activeId ? "Editing…" : "Edit") +
      "</button>" +
      '<button class="btn-icon" type="button" data-action="remove-hotel" data-hotel-id="' + h.id + '" aria-label="Remove hotel">' +
      '<svg class="icon icon-sm" viewBox="0 0 24 24"><path d="M4 7h16M9 7V5a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2m2 0-1 13a1 1 0 0 1-1 1H8a1 1 0 0 1-1-1L6 7"/></svg>' +
      "</button>" +
      "</div>" +
      "</div>"
    );
  }

  function renderGenerateBar() {
    var r = root();
    var box = utils.qs("[data-voucher-generate]", r);
    if (!box) return;
    var app = getApp();
    var hotels = (app && app.hotels) || [];
    var ready = hotels.length > 0 && hotels.every(isHotelComplete);

    var lastGenerated = hotels.reduce(function (latest, h) {
      return h.voucherGeneratedAt && (!latest || h.voucherGeneratedAt > latest) ? h.voucherGeneratedAt : latest;
    }, null);

    box.innerHTML =
      "<h3>Hotel Voucher document</h3>" +
      "<p>Generates the official Khanna Travels &amp; Holidays Hotel Voucher — one block per hotel below, in the exact reference format (letterhead, fonts, tables preserved).</p>" +
      (ready
        ? ""
        : '<div class="notice notice-warning">' +
          '<svg class="icon icon-sm" viewBox="0 0 24 24"><path d="M12 9v4M12 17h.01"/><circle cx="12" cy="12" r="9"/></svg>' +
          "<span>Add at least one hotel with name, city and check-in/check-out dates before generating a voucher.</span>" +
          "</div>") +
      '<div class="hotel-generate-bar">' +
      '<button class="btn btn-primary btn-sm" type="button" data-action="generate-voucher" data-format="docx"' + (ready ? "" : " disabled") + ">" +
      "Generate Hotel Voucher (.docx)</button>" +
      '<button class="btn btn-secondary btn-sm" type="button" data-action="generate-voucher" data-format="pdf"' + (ready ? "" : " disabled") + ">" +
      "Download as PDF</button>" +
      (lastGenerated ? '<span class="hotel-generate-bar__meta">Last generated ' + utils.formatDate(lastGenerated) + "</span>" : "") +
      "</div>" +
      '<div data-voucher-error></div>';
  }

  function renderList() {
    var r = root();
    if (!r) return;
    var listEl = utils.qs("[data-hotels-list]", r);
    if (!listEl) return;
    var app = getApp();
    var hotels = (app && app.hotels) || [];

    if (hotels.length === 0) {
      listEl.innerHTML =
        '<div class="empty-state">' +
        '<svg class="icon" viewBox="0 0 24 24"><path d="M3 21h18M5 21V7l7-4 7 4v14M9 9h1m-1 4h1m4-4h1m-1 4h1M9 21v-4a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v4"/></svg>' +
        "<h3>No hotels blocked yet</h3>" +
        "<p>Add each hotel booking made for this application. Once at least one hotel has its core details filled in, generate the Hotel Voucher document below.</p>" +
        "</div>";
    } else {
      var activeId = getActiveHotelId(r);
      listEl.innerHTML = hotels.map(function (h) { return cardHtml(h, activeId); }).join("");
    }

    renderGenerateBar();
    if (global.KhannaRouter) global.KhannaRouter.refreshWizardFooter();
  }

  function closePanel(r) {
    r = r || root();
    setActiveHotelId(r, null);
    var panel = utils.qs("[data-hotel-panel]", r);
    if (panel) panel.innerHTML = "";
    renderList();
  }

  function guestRowHtml(name, index) {
    return (
      '<div class="hotel-guest-row" data-guest-index="' + index + '">' +
      '<input type="text" data-guest-name-input value="' + utils.escapeHtml(name) + '" placeholder="Guest name" />' +
      '<button type="button" class="btn-icon" data-action="remove-guest-name" aria-label="Remove guest">' +
      '<svg class="icon icon-sm" viewBox="0 0 24 24"><path d="M18 6 6 18M6 6l12 12"/></svg>' +
      "</button>" +
      "</div>"
    );
  }

  function fieldRowHtml(f) {
    var id = "hf-" + f.key;
    return (
      '<div class="field">' +
      '<label for="' + id + '">' + utils.escapeHtml(f.label) + (f.required ? " *" : "") + "</label>" +
      '<input type="' + (f.type || "text") + '" id="' + id + '" data-hotel-field="' + f.key + '"' +
      (f.placeholder ? ' placeholder="' + utils.escapeHtml(f.placeholder) + '"' : "") +
      (f.type === "number" ? ' min="0"' : "") +
      " />" +
      "</div>"
    );
  }

  function renderGuestNames(hotel, r) {
    var panel = utils.qs("[data-hotel-panel]", r || root());
    if (!panel) return;
    var listEl = utils.qs("[data-guest-names-list]", panel);
    if (!listEl) return;
    var names = (hotel && hotel.guestNames) || [];
    listEl.innerHTML = names.map(guestRowHtml).join("");
  }

  function saveGuestNamesFromDom(appId, hotelId, r) {
    var panel = utils.qs("[data-hotel-panel]", r || root());
    if (!panel) return;
    var inputs = utils.qsa("[data-guest-name-input]", panel);
    var names = inputs.map(function (inp) {
      return inp.value;
    });
    global.KhannaState.updateHotel(appId, hotelId, { guestNames: names }, "Guest names updated");
  }

  function openPanel(hotelId, r) {
    r = r || root();
    var app = getApp();
    if (!app) return;
    var hotel = global.KhannaState.getHotel(app.id, hotelId);
    if (!hotel) return;

    setActiveHotelId(r, hotelId);
    renderList();

    var panel = utils.qs("[data-hotel-panel]", r);
    if (!panel) return;

    panel.innerHTML =
      '<div class="hotel-panel">' +
      '<div class="hotel-panel__header">' +
      "<h3>Editing: " + utils.escapeHtml(hotelLabel(hotel)) + "</h3>" +
      '<button class="btn btn-ghost btn-sm" type="button" data-action="close-hotel-panel">Close</button>' +
      "</div>" +
      '<div class="field-grid">' + HOTEL_FIELDS.map(fieldRowHtml).join("") + "</div>" +
      '<div class="hotel-panel__guests">' +
      "<label>Guest names on the voucher</label>" +
      '<div data-guest-names-list></div>' +
      '<button type="button" class="btn btn-ghost btn-sm" data-action="add-guest-name">' +
      '<svg class="icon icon-sm" viewBox="0 0 24 24"><path d="M12 5v14M5 12h14"/></svg>' +
      "Add guest name</button>" +
      '<p class="field-hint">Leave empty to use the lead guest name only.</p>' +
      "</div>" +
      "</div>";

    HOTEL_FIELDS.forEach(function (f) {
      var el = utils.qs('[data-hotel-field="' + f.key + '"]', panel);
      if (el) el.value = hotel[f.key] || "";
    });
    renderGuestNames(hotel, r);

    // The field-change listener itself is wired ONCE, in mountSkeleton()
    // (delegated on the whole step root, reading activeHotelId live) — not
    // here. openPanel() re-runs every time a hotel is added or a different
    // hotel's Edit is clicked, but panel (this function's own [data-hotel-
    // panel] container) is never replaced, only its innerHTML is rewritten
    // (see closePanel()) — so a listener attached here via utils.on(panel,
    // ...), which always calls addEventListener and never removes a prior
    // one, would silently accumulate: opening a second hotel's panel left
    // the FIRST hotel's own listener (closed over its own hotelId) still
    // attached, so typing into hotel 2's fields also patched hotel 1's
    // record with the same values. Real bug, caught by Phase 13's own
    // full-journey test (the first test to ever open a SECOND hotel's
    // panel in the same run) via a captured network payload showing both
    // hotels saved with identical data despite distinct ids.
    panel.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }

  function isStepComplete() {
    var app = getApp();
    if (!app) return false;
    var hotels = app.hotels || [];
    return hotels.length > 0 && hotels.every(isHotelComplete);
  }

  function showVoucherError(message) {
    var r = root();
    var box = utils.qs("[data-voucher-error]", r);
    if (!box) return;
    box.innerHTML = message
      ? '<div class="notice notice-danger"><svg class="icon icon-sm" viewBox="0 0 24 24"><path d="M12 9v4M12 17h.01"/><circle cx="12" cy="12" r="9"/></svg><span>' +
        utils.escapeHtml(message) +
        "</span></div>"
      : "";
  }

  function generateVoucher(format, btn) {
    var app = getApp();
    if (!app) return;
    showVoucherError("");
    var originalText = btn.textContent;
    btn.disabled = true;
    btn.textContent = "Generating…";

    var applicantName = [app.applicant.firstName, app.applicant.lastName].filter(Boolean).join(" ") || "Application";

    api.downloadHotelVoucher(app.hotels, format, applicantName).then(
      function (result) {
        utils.triggerFileDownload(result.blob, result.filename);
        var ts = new Date().toISOString();
        var hotels = (app.hotels || []).map(function (h) {
          return Object.assign({}, h, { voucherGeneratedAt: ts });
        });
        // Goes through the normal state-change subscription, which calls
        // renderList() -> renderGenerateBar() and rebuilds this whole card
        // (including a fresh "Last generated" line) — correct here because
        // there is no error message that a rebuild would need to preserve.
        global.KhannaState.updateApplication(
          app.id,
          { hotels: hotels },
          "Hotel voucher generated (" + format.toUpperCase() + ", " + hotels.length + " hotel(s))"
        );
      },
      function (err) {
        // Deliberately does NOT call renderGenerateBar() here: that would
        // rebuild this card's HTML (a fresh, empty [data-voucher-error]
        // included) and immediately erase the message showVoucherError is
        // about to set — a real bug caught by testing the backend-down
        // path, not just the happy path. Only the button itself is reset.
        btn.disabled = false;
        btn.textContent = originalText;
        showVoucherError(err && err.message ? err.message : "Could not generate the hotel voucher.");
      }
    );
  }

  function mountSkeleton() {
    var r = root();
    if (!r) return;
    r.innerHTML =
      '<div class="view-header">' +
      '<div class="view-header__text">' +
      "<h2>Hotel blocking</h2>" +
      "<p>Add every hotel booked/blocked for this application, then generate the official Khanna Travels &amp; Holidays Hotel Voucher document straight from the reference format.</p>" +
      "</div>" +
      '<button class="btn btn-primary btn-sm" type="button" data-action="add-hotel">' +
      '<svg class="icon icon-sm" viewBox="0 0 24 24"><path d="M12 5v14M5 12h14"/></svg>' +
      "Add hotel" +
      "</button>" +
      "</div>" +
      '<div class="hotel-list" data-hotels-list></div>' +
      '<div data-hotel-panel></div>' +
      '<div class="card" data-voucher-generate></div>';

    utils.on(r, "click", "[data-action='add-hotel']", function () {
      var app = getApp();
      if (!app) return;
      var hotel = global.KhannaState.addHotel(app.id);
      openPanel(hotel.id, r);
    });

    utils.on(r, "click", "[data-action='edit-hotel']", function (e, target) {
      openPanel(target.getAttribute("data-hotel-id"), r);
    });

    utils.on(r, "click", "[data-action='remove-hotel']", function (e, target) {
      var app = getApp();
      if (!app) return;
      var id = target.getAttribute("data-hotel-id");
      if (id === getActiveHotelId(r)) setActiveHotelId(r, null);
      global.KhannaState.removeHotel(app.id, id);
      var panel = utils.qs("[data-hotel-panel]", r);
      if (panel && !getActiveHotelId(r)) panel.innerHTML = "";
    });

    utils.on(r, "click", "[data-action='close-hotel-panel']", function () {
      closePanel(r);
    });

    utils.on(r, "click", "[data-action='add-guest-name']", function () {
      var app = getApp();
      var activeId = getActiveHotelId(r);
      if (!app || !activeId) return;
      var hotel = global.KhannaState.getHotel(app.id, activeId);
      if (!hotel) return;
      var names = (hotel.guestNames || []).concat([""]);
      global.KhannaState.updateHotel(app.id, activeId, { guestNames: names }, null);
      renderGuestNames(global.KhannaState.getHotel(app.id, activeId), r);
    });

    utils.on(r, "click", "[data-action='remove-guest-name']", function (e, target) {
      var app = getApp();
      var activeId = getActiveHotelId(r);
      if (!app || !activeId) return;
      saveGuestNamesFromDom(app.id, activeId, r); // persist any in-progress edits first
      var hotel = global.KhannaState.getHotel(app.id, activeId);
      if (!hotel) return;
      var row = target.closest("[data-guest-index]");
      var idx = parseInt(row.getAttribute("data-guest-index"), 10);
      var names = (hotel.guestNames || []).slice();
      names.splice(idx, 1);
      global.KhannaState.updateHotel(app.id, activeId, { guestNames: names }, "Guest name removed");
      renderGuestNames(global.KhannaState.getHotel(app.id, activeId), r);
    });

    utils.on(r, "change", "[data-guest-name-input]", function () {
      var activeId = getActiveHotelId(r);
      if (!activeId) return;
      var app = getApp();
      if (!app) return;
      saveGuestNamesFromDom(app.id, activeId, r);
    });

    // Wired ONCE here (delegated on the whole step root, reading this root's
    // OWN active hotel id live at fire time via getActiveHotelId(r)) rather
    // than re-attached inside openPanel() on every open — see the comment in
    // openPanel() for the original build's listener-accumulation bug this
    // fixes, and the comment above getActiveHotelId()/setActiveHotelId() for
    // the Phase 4 dual-mount variant of the same bug class this `r`-scoped
    // (not module-level) tracking fixes.
    utils.on(r, "change", "[data-hotel-field]", function (e, target) {
      var activeId = getActiveHotelId(r);
      if (!activeId) return;
      var app = getApp();
      if (!app) return;
      var key = target.getAttribute("data-hotel-field");
      var patch = {};
      patch[key] = target.value;
      global.KhannaState.updateHotel(app.id, activeId, patch, "Hotel details updated");
    });

    utils.on(r, "click", "[data-action='generate-voucher']", function (e, target) {
      if (target.disabled) return;
      generateVoucher(target.getAttribute("data-format"), target);
    });
  }

  function render() {
    var r = root();
    if (!r) return;
    // The wizard can never reach this step without an active application
    // already existing, so this is a no-op there; the standalone Hotel
    // Blocking page CAN be opened directly with none yet, and mounting the
    // real "Add hotel" skeleton in that case would look interactive but
    // silently do nothing when clicked — document-workspace.js's app bar is
    // what tells the user to create one, not this panel pretending to work
    // in the meantime (project rule 9). Deliberately doesn't set
    // dataset.mounted here, so the real skeleton still mounts the first
    // time render() runs again with an application active.
    if (!getApp()) {
      // Also clears a STALE dataset.mounted flag from an earlier successful
      // mount (e.g. the user had an application active, this page mounted
      // for real, then they switched to no active application) — without
      // this, the next render() that DOES have an app would see
      // dataset.mounted already "1" and skip mountSkeleton() entirely,
      // leaving this placeholder text stuck permanently instead of the
      // real form. Caught by testing the full switch-away-and-back
      // sequence, not just the two states in isolation.
      delete r.dataset.mounted;
      r.innerHTML = '<p class="field-hint">Create or continue an application above to start adding hotels.</p>';
      return;
    }
    if (!r.dataset.mounted) {
      r.dataset.mounted = "1";
      mountSkeleton();
    }
    renderList();
  }

  function init() {
    if (global.KhannaRouter) global.KhannaRouter.registerStepValidator("new-application", 5, isStepComplete);

    document.addEventListener("khanna:navigate", function (e) {
      if (e.detail.view === "new-application" || e.detail.view === "hotel-blocking") render();
    });

    // The list (not the open panel) reacts to every state change, matching
    // the discipline established in travellers.js/documents.js.
    global.KhannaState.subscribe(function () {
      if (root() && root().dataset.mounted) renderList();
    });

    if (location.hash.indexOf("new-application") !== -1 || location.hash.indexOf("hotel-blocking") !== -1) render();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})(window);
