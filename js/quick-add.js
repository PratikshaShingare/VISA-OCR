/* ==========================================================================
   Khanna Travels & Holidays — "+ Upload new ..." inside Use Existing Details
   Every page that has a "Use Existing Details ▾" menu (Cover Letter,
   Invitation Letter, Passport / Company Authorization) lists the saved
   passports / hotel blockings there (js/saved-details.js). When the one you
   need is not in that list, the first row of the list is now

        +  Upload new passport          /          +  Upload new hotel voucher

   which opens a small window right on the page — nothing to leave, nothing
   to come back to:

     * Passport: the SAME upload -> OCR (azapi / local) -> review form the
       Upload Passport page uses (KhannaPassportProcessing.createController),
       so every field is checked and editable and nothing is auto-verified.
       "Save passport details" adds the person to the active application (as
       the applicant when it has none yet, otherwise as a traveller) and to
       the reusable profiles, then the page picks them up exactly as if they
       had been chosen from the list.
     * Hotel voucher: the SAME voucher reader as the Hotel Blocking page
       (api.processHotelVoucher + KhannaHotels.ocrResultToPatch, one file at a
       time, multi-page PDFs included). The result is shown for checking
       (hotel, city, dates, confirmation number are editable), and only when
       "Use these hotels" is pressed are the hotels added to the active
       application's Hotel Blocking; then the page picks them up.

   How a page learns about the result without a line of page-specific code:
   the row that opened this window carries the page's own pick attribute
   (e.g. data-cover-existing-pick). When the window finishes it clicks a
   short-lived button carrying that same attribute — the page's existing
   handler (the one a list row triggers) runs unchanged.

   Public API
       KhannaQuickAdd.rowHtml(kind, pickAttr)   -> the "+ Upload new ..." row
       KhannaQuickAdd.open(kind, { pickAttr, host })   (also used by tests)
   ========================================================================== */
(function (global) {
  "use strict";

  var utils = global.KhannaUtils;
  var PLUS_ICON = '<svg class="icon icon-sm" viewBox="0 0 24 24" aria-hidden="true"><path d="M12 5v14M5 12h14"/></svg>';

  var overlayEl = null;
  var current = null; // { kind, pickAttr, host, controller, hotels:[...] }
  var lastFocus = null;
  var running = false;

  var KIND_TEXT = {
    passport: { row: "Upload new passport", title: "Add a passport" },
    hotel: { row: "Upload new hotel voucher", title: "Add a hotel voucher" },
  };

  function rowHtml(kind, pickAttr) {
    var text = KIND_TEXT[kind];
    if (!text) return "";
    return (
      '<button type="button" class="cover-existing-item cover-existing-item--add" data-quick-add="' + kind + '" ' +
      'data-quick-add-pick="' + utils.escapeHtml(pickAttr || "") + '">' +
      '<span class="cover-existing-item__name">' + PLUS_ICON + utils.escapeHtml(text.row) + "</span>" +
      '<span class="cover-existing-item__meta">' +
      (kind === "passport"
        ? "Not in the list? Upload it here — it is read and added for you."
        : "Not in the list? Upload the voucher here — it is read and added for you.") +
      "</span></button>"
    );
  }

  /* ---------------------------------------------------------------------
   * The window
   * ------------------------------------------------------------------- */
  function ensureOverlay() {
    if (overlayEl) return;
    var wrap = document.createElement("div");
    wrap.className = "app-picker-overlay quick-add-overlay";
    wrap.setAttribute("hidden", "");
    wrap.setAttribute("data-quick-add-overlay", "");
    wrap.innerHTML =
      '<div class="app-picker quick-add" role="dialog" aria-modal="true" aria-labelledby="quickAddTitle">' +
      '<div class="app-picker__header">' +
      '<h3 id="quickAddTitle" data-quick-add-title></h3>' +
      '<button type="button" class="btn-icon" data-quick-add-close aria-label="Close">' +
      '<svg class="icon icon-sm" viewBox="0 0 24 24"><path d="M6 6l12 12M18 6 6 18"/></svg>' +
      "</button>" +
      "</div>" +
      '<div class="quick-add__body" data-quick-add-body></div>' +
      "</div>";
    document.body.appendChild(wrap);
    overlayEl = wrap;

    utils.on(wrap, "click", "[data-quick-add-close]", close);
    wrap.addEventListener("mousedown", function (e) {
      // A click on the dimmed area closes — but never while a voucher is being read.
      if (e.target === wrap && !running) close();
    });
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape" && overlayEl && !overlayEl.hasAttribute("hidden") && !running) close();
    });
  }

  function close() {
    if (!overlayEl) return;
    overlayEl.hidden = true;
    var body = utils.qs("[data-quick-add-body]", overlayEl);
    if (body) body.innerHTML = "";
    current = null;
    document.body.classList.remove("has-quick-add");
    if (lastFocus && lastFocus.focus && document.contains(lastFocus)) lastFocus.focus();
  }

  function body() {
    return utils.qs("[data-quick-add-body]", overlayEl);
  }

  // Tells the page the result is ready: clicks a button carrying the page's own
  // pick attribute inside the list that opened this window, so the page's
  // existing "a row was chosen" code runs unchanged.
  function handBackToPage(kind, value) {
    var s = current;
    if (!s || !s.pickAttr) return;
    // The page may have redrawn its card while the window was open (saving a
    // person refreshes it): then use the same list, by position, in the new DOM.
    var host = s.host && document.contains(s.host) ? s.host : null;
    if (!host && s.section) host = s.section.querySelectorAll(".cover-existing-list")[s.hostIndex] || s.section;
    if (!host) return;
    var btn = document.createElement("button");
    btn.type = "button";
    btn.hidden = true;
    if (kind === "passport") {
      btn.setAttribute(s.pickAttr, "passport");
      btn.setAttribute("data-passport-key", value);
    } else {
      btn.setAttribute(s.pickAttr, "hotel-blocking");
      btn.setAttribute("data-app-id", value);
    }
    host.appendChild(btn);
    btn.click();
    if (btn.parentNode) btn.parentNode.removeChild(btn);
  }

  function noApplicationHtml() {
    return (
      '<div class="notice notice-warning"><svg class="icon icon-sm" viewBox="0 0 24 24"><path d="M12 9v4M12 17h.01"/><circle cx="12" cy="12" r="9"/></svg>' +
      "<span>There is no application open yet. Use “Create new application” at the top of the page first, then upload here.</span></div>" +
      '<div class="quick-add__actions"><button type="button" class="btn btn-secondary btn-sm" data-quick-add-close>Close</button></div>'
    );
  }

  /* ---------------------------------------------------------------------
   * Passport
   * ------------------------------------------------------------------- */
  function personHasPassportNumber(p) {
    return !!(p && p.passport && p.passport.current && String(p.passport.current.number || "").trim());
  }

  // Puts the checked passport on the active application: as the applicant when
  // it has none yet, otherwise as a traveller — and into the reusable profiles.
  // Returns the key the pages use for a saved passport (its number, upper-case).
  function commitPassport(person) {
    var S = global.KhannaState;
    var app = S.getActiveApplication();
    if (!app) return null;
    var key = String(person.passport.current.number || "").trim().toUpperCase();
    var alreadyThere = [app.applicant].concat(app.travellers || []).some(function (p) {
      return personHasPassportNumber(p) && String(p.passport.current.number).trim().toUpperCase() === key;
    });
    if (alreadyThere) return key; // the same passport again: just select it
    var message = "Passport added from a document page";
    if (!personHasPassportNumber(app.applicant) && !(app.applicant && (app.applicant.fullName || "").trim())) {
      S.updateApplication(app.id, { applicant: person }, message);
      if (S.syncApplicantProfileFromApplication) S.syncApplicantProfileFromApplication(app.id);
    } else {
      var t = S.addTraveller(app.id, "");
      S.updateTraveller(app.id, t.id, person, message);
      if (S.syncTravellerProfileFromApplication) S.syncTravellerProfileFromApplication(app.id, t.id);
    }
    return key;
  }

  function openPassport() {
    var S = global.KhannaState;
    if (!S.getActiveApplication()) {
      body().innerHTML = noApplicationHtml();
      return;
    }
    body().innerHTML =
      '<p class="field-hint quick-add__intro">Upload the passport’s photo page. It is read automatically — check every field, correct what is wrong, then save.</p>' +
      '<div data-quick-add-passport-root></div>';
    var pseudo = { id: "quick-add", applicant: S.createEmptyPerson() };
    var saved = false;
    current.controller = global.KhannaPassportProcessing.createController({
      root: utils.qs("[data-quick-add-passport-root]", overlayEl),
      instanceId: "quick-add",
      hideTestTools: true,
      quietSave: true,
      getApplication: function () { return pseudo; },
      getPerson: function (app) { return app.applicant; },
      savePerson: function (app, personPatch) {
        app.applicant = Object.assign({}, app.applicant, personPatch);
      },
      onPersonSaved: function (app) {
        if (saved) return;
        saved = true;
        var key = commitPassport(app.applicant);
        if (!key) return;
        var name = (app.applicant.fullName || "").trim();
        handBackToPage("passport", key);
        close();
        if (global.KhannaToast) global.KhannaToast.show((name || "Passport") + " added and saved for reuse", { type: "success" });
      },
    });
    current.controller.render();
  }

  /* ---------------------------------------------------------------------
   * Hotel voucher
   * ------------------------------------------------------------------- */
  function hotelFormHtml(h, i) {
    function field(name, label, type, value) {
      var id = "qa-h" + i + "-" + name;
      return (
        '<div class="field"><label for="' + id + '">' + label + "</label>" +
        '<input id="' + id + '" type="' + type + '" data-qa-hotel="' + i + '" data-qa-field="' + name + '" value="' + utils.escapeHtml(value || "") + '" /></div>'
      );
    }
    return (
      '<div class="quick-add__hotel">' +
      '<div class="quick-add__hotel-head"><strong>' + utils.escapeHtml(h.label) + "</strong>" +
      (h.problem ? '<span class="badge badge-warning">' + utils.escapeHtml(h.problem) + "</span>" : '<span class="badge badge-warning">OCR Extracted — Please Verify</span>') +
      "</div>" +
      '<div class="field-grid">' +
      field("hotelName", "Hotel name", "text", h.patch.hotelName) +
      field("city", "City", "text", h.patch.city) +
      field("checkIn", "Check-in", "date", h.patch.checkIn) +
      field("checkOut", "Check-out", "date", h.patch.checkOut) +
      field("confirmationNumber", "Confirmation number", "text", h.patch.confirmationNumber) +
      "</div>" +
      (h.warnings && h.warnings.length ? '<p class="field-hint">' + h.warnings.map(utils.escapeHtml).join(" ") + "</p>" : "") +
      "</div>"
    );
  }

  function renderHotelResults() {
    var s = current;
    var rows = s.hotels;
    body().innerHTML =
      '<p class="field-hint quick-add__intro">' + rows.length + (rows.length === 1 ? " hotel was" : " hotels were") +
      " read. Check each one, correct anything that is wrong, then add them. They are saved on this application’s Hotel Blocking.</p>" +
      rows.map(hotelFormHtml).join("") +
      '<div class="quick-add__actions">' +
      '<button type="button" class="btn btn-secondary btn-sm" data-quick-add-close>Cancel</button>' +
      '<button type="button" class="btn btn-primary btn-sm" data-quick-add-confirm-hotels>Use these hotels</button>' +
      "</div>";
  }

  function confirmHotels() {
    var S = global.KhannaState;
    var app = S.getActiveApplication();
    var s = current;
    if (!app || !s) return;
    var edited = s.hotels.map(function (h) { return Object.assign({}, h.patch); });
    utils.qsa("[data-qa-hotel]", overlayEl).forEach(function (el) {
      edited[Number(el.getAttribute("data-qa-hotel"))][el.getAttribute("data-qa-field")] = el.value.trim();
    });
    var bad = edited.filter(function (p) { return p.checkIn && p.checkOut && p.checkOut < p.checkIn; });
    if (bad.length) {
      var err = utils.qs("[data-quick-add-error]", overlayEl);
      if (!err) {
        err = document.createElement("div");
        err.className = "notice notice-danger";
        err.setAttribute("data-quick-add-error", "");
        err.setAttribute("role", "alert");
        body().insertBefore(err, utils.qs(".quick-add__actions", overlayEl));
      }
      err.textContent = "A check-out date is before its check-in date. Please correct it.";
      return;
    }
    // A blank hotel row (nothing typed) would sit above the uploaded ones.
    (app.hotels || []).forEach(function (h) {
      if (!h.source && !(h.hotelName || h.city || h.checkIn || h.checkOut || h.address || h.phone || h.confirmationNumber)) {
        S.removeHotel(app.id, h.id);
      }
    });
    edited.forEach(function (patch, i) {
      var hotel = S.addHotel(app.id);
      S.updateHotel(app.id, hotel.id, Object.assign({}, patch, { source: "voucher", voucherFileName: s.hotels[i].fileLabel }), "Hotel voucher added from a document page");
    });
    var appId = app.id;
    var count = edited.length;
    handBackToPage("hotel", appId);
    close();
    if (global.KhannaToast) global.KhannaToast.show(count + (count === 1 ? " hotel" : " hotels") + " added to Hotel Blocking — please verify", { type: "success" });
  }

  function readVouchers(files) {
    var api = global.KhannaApi;
    var s = current;
    var queue = files.map(function (f) { return { file: f, page: 0, optional: false, label: f.name }; });
    var total = files.length;
    var done = 0;
    var failures = [];
    s.hotels = [];
    running = true;

    function progress(text) {
      var el = utils.qs("[data-quick-add-status]", overlayEl);
      if (el) el.textContent = text;
    }

    function finish() {
      running = false;
      if (!s.hotels.length) {
        body().innerHTML =
          '<div class="notice notice-warning"><svg class="icon icon-sm" viewBox="0 0 24 24"><path d="M12 9v4M12 17h.01"/><circle cx="12" cy="12" r="9"/></svg>' +
          "<span>No hotel details could be read" + (failures.length ? " from: " + utils.escapeHtml(failures.join(", ")) : "") +
          ". Try a clearer photo or PDF, or add the hotel by hand on the Hotel Blocking page.</span></div>" +
          '<div class="quick-add__actions"><button type="button" class="btn btn-secondary btn-sm" data-quick-add-close>Close</button>' +
          '<button type="button" class="btn btn-primary btn-sm" data-quick-add-retry>Try another file</button></div>';
        return;
      }
      renderHotelResults();
      if (failures.length) {
        var note = document.createElement("div");
        note.className = "notice notice-warning";
        note.textContent = "Could not read: " + failures.join(", ") + ".";
        body().insertBefore(note, body().firstChild);
      }
    }

    function next() {
      if (!current || current !== s) { running = false; return; }
      if (!queue.length) { finish(); return; }
      var item = queue.shift();
      done += 1;
      progress("Reading voucher " + done + " of " + (done + queue.length) + " (" + item.label + ")…");
      api.processHotelVoucher(item.file, item.page).then(function (result) {
        if (item.page === 0 && result && result.totalPages > 1) {
          var extra = [];
          for (var p = 1; p < result.totalPages; p++) {
            extra.push({ file: item.file, page: p, optional: true, label: item.file.name + ", page " + (p + 1) });
          }
          queue = extra.concat(queue);
        }
        var patch = global.KhannaHotels.ocrResultToPatch(result);
        var hasFields = Object.keys(result.fields || {}).some(function (k) { return result.fields[k]; });
        var isVoucherPage = !!(result && (result.voucherType !== "unknown" || (result.fields && result.fields.hotelName)));
        if (item.optional && !isVoucherPage) { next(); return; }
        if (hasFields) {
          s.hotels.push({
            patch: patch,
            label: patch.hotelName || item.label,
            fileLabel: item.page > 0 ? item.file.name + " (page " + (item.page + 1) + ")" : item.file.name,
            warnings: (result.warnings || []).slice(),
          });
        } else if (!item.optional) {
          failures.push(item.label);
        }
        next();
      }, function () {
        if (!item.optional) failures.push(item.label);
        next();
      });
    }
    body().innerHTML =
      '<div class="quick-add__reading" role="status" aria-live="polite"><span class="quick-add__spinner" aria-hidden="true"></span>' +
      '<span data-quick-add-status>Reading…</span></div>';
    next();
  }

  function openHotel() {
    if (!global.KhannaState.getActiveApplication()) {
      body().innerHTML = noApplicationHtml();
      return;
    }
    body().innerHTML =
      '<p class="field-hint quick-add__intro">Upload the hotel booking voucher (image or PDF). More than one file is fine — each hotel is read in turn.</p>' +
      '<div class="upload-dropzone quick-add__dropzone" data-quick-add-dropzone tabindex="0" role="button" aria-label="Upload hotel voucher">' +
      '<input type="file" multiple accept="image/jpeg,image/png,image/webp,image/bmp,application/pdf" data-quick-add-file hidden />' +
      '<svg class="icon" viewBox="0 0 24 24"><path d="M12 16V4M12 4 7 9M12 4l5 5"/><path d="M4 16v3a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-3"/></svg>' +
      "<h3>Upload hotel voucher</h3><p>JPG, PNG or PDF. Drag and drop, or click to browse.</p>" +
      '<button type="button" class="btn btn-secondary btn-sm" data-quick-add-browse>Browse file</button></div>';
    var dz = utils.qs("[data-quick-add-dropzone]", overlayEl);
    var input = utils.qs("[data-quick-add-file]", overlayEl);
    function pick(files) {
      files = Array.prototype.slice.call(files || []);
      if (files.length && current) readVouchers(files);
    }
    utils.on(dz, "click", "[data-quick-add-browse]", function (e) { e.stopPropagation(); input.click(); });
    dz.addEventListener("click", function (e) { if (e.target === dz) input.click(); });
    dz.addEventListener("keydown", function (e) { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); input.click(); } });
    input.addEventListener("change", function () { var f = input.files; pick(f); input.value = ""; });
    ["dragover", "dragenter"].forEach(function (evt) {
      dz.addEventListener(evt, function (e) { e.preventDefault(); dz.classList.add("is-dragover"); });
    });
    ["dragleave", "dragend"].forEach(function (evt) {
      dz.addEventListener(evt, function () { dz.classList.remove("is-dragover"); });
    });
    dz.addEventListener("drop", function (e) {
      e.preventDefault();
      dz.classList.remove("is-dragover");
      pick(e.dataTransfer && e.dataTransfer.files);
    });
  }

  /* ---------------------------------------------------------------------
   * Entry point
   * ------------------------------------------------------------------- */
  function open(kind, options) {
    options = options || {};
    if (!KIND_TEXT[kind]) return;
    ensureOverlay();
    lastFocus = document.activeElement;
    current = { kind: kind, pickAttr: options.pickAttr || "", host: options.host || null, section: options.section || null, hostIndex: options.hostIndex || 0, hotels: [] };
    utils.qs("[data-quick-add-title]", overlayEl).textContent = KIND_TEXT[kind].title;
    overlayEl.hidden = false;
    document.body.classList.add("has-quick-add");
    if (kind === "passport") openPassport();
    else openHotel();
  }

  document.addEventListener("click", function (e) {
    var t = e.target.closest && e.target.closest("[data-quick-add]");
    if (t) {
      e.preventDefault();
      e.stopPropagation();
      var host = t.closest(".cover-existing-list") || t.parentNode;
      var section = host.closest(".view") || document.body;
      var hostIndex = Array.prototype.indexOf.call(section.querySelectorAll(".cover-existing-list"), host);
      open(t.getAttribute("data-quick-add"), { pickAttr: t.getAttribute("data-quick-add-pick"), host: host, section: section, hostIndex: hostIndex });
      return;
    }
    if (e.target.closest && e.target.closest("[data-quick-add-confirm-hotels]")) {
      confirmHotels();
    } else if (e.target.closest && e.target.closest("[data-quick-add-retry]") && current) {
      openHotel();
    }
  }, true);

  global.KhannaQuickAdd = { rowHtml: rowHtml, open: open };
})(window);
