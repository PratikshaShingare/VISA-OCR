/* ==========================================================================
   Khanna Travels & Holidays — Recent Hotel Blockings page
   "#/hotel-blockings" — every application that has hotel blocking data, with
   per-row Edit / Download (DOCX or PDF) / Delete. Reached from the
   "Recent Hotel Blockings" button in the Hotel Blocking page's title row.

   Nothing here is invented: each row is an application record from the
   central state store (KhannaState) that has at least one hotel.
     Edit     -> makes that application active and opens the Hotel Blocking
                 page straight on its (editable) preview.
     Download -> asks the backend for the real Hotel Voucher (the same
                 /api/documents/hotel-voucher call the preview's download
                 buttons use), as .docx or .pdf.
     Delete   -> asks first (popup). Deleting removes the hotel blocking; if
                 hotel blocking was ALL that application had, the whole
                 (otherwise empty) application goes with it, and if it also
                 holds other documents/data those are kept.
   ========================================================================== */
(function (global) {
  "use strict";

  var utils = global.KhannaUtils;
  var api = global.KhannaApi;

  var PENCIL_ICON = '<svg class="icon icon-sm" viewBox="0 0 24 24"><path d="M12 20h9M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4Z"/></svg>';
  var DOWNLOAD_ICON = '<svg class="icon icon-sm" viewBox="0 0 24 24"><path d="M12 4v11m0 0-4-4m4 4 4-4M5 20h14"/></svg>';
  var CHEVRON_ICON = '<svg class="icon icon-sm" viewBox="0 0 24 24"><path d="m6 9 6 6 6-6"/></svg>';
  var TRASH_ICON = '<svg class="icon icon-sm" viewBox="0 0 24 24"><path d="M4 7h16M9 7V5a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2m2 0-1 13a1 1 0 0 1-1 1H8a1 1 0 0 1-1-1L6 7"/></svg>';

  function root() {
    return utils.qs("[data-hotel-blockings-root]");
  }

  function labelOf(app) {
    return global.KhannaApplicationsList ? global.KhannaApplicationsList.applicantLabel(app) : "Untitled applicant";
  }

  function fileNameLabel(app) {
    var l = labelOf(app);
    return l === "Untitled applicant" ? "Application" : l;
  }

  function blockings() {
    return global.KhannaState.getApplications()
      // A blocking is only worth listing once a hotel on it has real details
      // (name, date or city) — rows left completely empty are not a blocking.
      .filter(function (a) { return (a.hotels || []).some(function (h) { return h.hotelName || h.checkIn || h.checkOut || h.city; }); })
      .sort(function (a, b) { return a.updatedAt < b.updatedAt ? 1 : a.updatedAt > b.updatedAt ? -1 : 0; });
  }

  function summary(app) {
    var hotels = app.hotels || [];
    var names = hotels.map(function (h) { return h.hotelName || "Unnamed hotel"; });
    var cities = [];
    hotels.forEach(function (h) {
      if (h.city && cities.indexOf(h.city) === -1) cities.push(h.city);
    });
    var ins = hotels.map(function (h) { return h.checkIn; }).filter(Boolean).sort();
    var outs = hotels.map(function (h) { return h.checkOut; }).filter(Boolean).sort();
    var dates = ins.length && outs.length ? utils.formatDate(ins[0]) + " → " + utils.formatDate(outs[outs.length - 1]) : "Dates not set";
    var generated = hotels.reduce(function (latest, h) {
      return h.voucherGeneratedAt && (!latest || h.voucherGeneratedAt > latest) ? h.voucherGeneratedAt : latest;
    }, null);
    return {
      count: hotels.length,
      names: names,
      cities: cities,
      dates: dates,
      generated: generated,
    };
  }

  function rowHtml(app) {
    var s = summary(app);
    var id = utils.escapeHtml(app.id);
    var label = utils.escapeHtml(labelOf(app));
    return (
      '<div class="card hb-row" data-hb-row="' + id + '">' +
      '<div class="hb-row__info">' +
      '<div class="hb-row__name">' + label + "</div>" +
      '<div class="hb-row__meta">' +
      s.count + (s.count === 1 ? " hotel" : " hotels") +
      (s.cities.length ? " · " + utils.escapeHtml(s.cities.join(", ")) : "") +
      " · " + utils.escapeHtml(s.dates) +
      "</div>" +
      '<div class="hb-row__hotels">' + utils.escapeHtml(s.names.join(" · ")) + "</div>" +
      '<div class="hb-row__meta hb-row__meta--faint">Updated ' + utils.formatDate(app.updatedAt) +
      (s.generated ? " · Voucher generated " + utils.formatDate(s.generated) : " · Voucher not generated yet") +
      "</div>" +
      "</div>" +
      '<div class="hb-row__actions">' +
      '<button type="button" class="btn btn-secondary btn-sm" data-action="hb-edit" data-app-id="' + id + '">' + PENCIL_ICON + "Edit</button>" +
      '<div class="hb-menu" data-hb-menu>' +
      '<button type="button" class="btn btn-secondary btn-sm" data-action="hb-download-toggle" data-app-id="' + id + '" aria-haspopup="true" aria-expanded="false">' +
      DOWNLOAD_ICON + "Download" + CHEVRON_ICON + "</button>" +
      '<div class="hb-menu__dropdown" role="menu" hidden>' +
      '<button type="button" class="hb-menu__item" role="menuitem" data-action="hb-download" data-format="docx" data-app-id="' + id + '">Download as DOCX</button>' +
      '<button type="button" class="hb-menu__item" role="menuitem" data-action="hb-download" data-format="pdf" data-app-id="' + id + '">Download as PDF</button>' +
      "</div>" +
      "</div>" +
      '<button type="button" class="btn btn-danger-outline btn-sm" data-action="hb-delete" data-app-id="' + id + '">' + TRASH_ICON + "Delete</button>" +
      "</div>" +
      '<div class="hb-row__error" data-hb-error hidden></div>' +
      "</div>"
    );
  }

  function render() {
    var r = root();
    if (!r) return;
    var list = blockings();
    if (!list.length) {
      r.innerHTML =
        '<div class="empty-state">' +
        '<svg class="icon" viewBox="0 0 24 24"><path d="M3 21h18M5 21V7l7-4 7 4v14M9 9h1m-1 4h1m4-4h1m-1 4h1M9 21v-4a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v4"/></svg>' +
        "<h3>No hotel blockings yet</h3>" +
        '<a class="btn btn-primary btn-sm" href="#/hotel-blocking" data-nav-link="hotel-blocking">Go to Hotel Blocking</a>' +
        "</div>";
      return;
    }
    r.innerHTML = '<div class="hb-list">' + list.map(rowHtml).join("") + "</div>";
  }

  /* ---------------- download menu ---------------- */
  function closeMenus() {
    utils.qsa("[data-hb-menu] .hb-menu__dropdown", root() || document).forEach(function (d) {
      d.hidden = true;
    });
    utils.qsa("[data-action='hb-download-toggle']", root() || document).forEach(function (b) {
      b.setAttribute("aria-expanded", "false");
    });
  }

  function showRowError(row, message) {
    var box = row && row.querySelector("[data-hb-error]");
    if (!box) return;
    box.hidden = !message;
    box.textContent = message || "";
  }

  function download(appId, format, btn) {
    var app = global.KhannaState.getApplication(appId);
    if (!app) return;
    var row = btn.closest("[data-hb-row]");
    showRowError(row, "");
    var original = btn.textContent;
    btn.disabled = true;
    btn.textContent = "Preparing…";
    var usable = global.KhannaHotels ? global.KhannaHotels.completeHotels(app.hotels) : app.hotels;
    if (!usable.length) {
      btn.disabled = false;
      btn.textContent = original;
      showRowError(row, "No hotel here has its name, city and check-in/check-out dates yet — use Edit to complete it first.");
      return;
    }
    api.downloadHotelVoucher(usable, format, fileNameLabel(app)).then(
      function (res) {
        utils.triggerFileDownload(res.blob, res.filename || "Hotel_Voucher." + format);
        btn.disabled = false;
        btn.textContent = original;
        closeMenus();
      },
      function (err) {
        btn.disabled = false;
        btn.textContent = original;
        showRowError(row, (err && err.message) || "Could not prepare the download.");
      }
    );
  }

  /* ---------------- delete confirmation popup ---------------- */
  var modalEl = null;
  var pendingDeleteId = null;
  var lastFocus = null;

  function ensureModal() {
    if (modalEl) return;
    var wrap = document.createElement("div");
    wrap.className = "app-picker-overlay";
    wrap.setAttribute("hidden", "");
    wrap.setAttribute("data-hb-delete-modal", "");
    wrap.innerHTML =
      '<div class="app-picker" role="dialog" aria-modal="true" aria-labelledby="hbDeleteTitle" style="max-width:440px;">' +
      '<div class="app-picker__header">' +
      '<h3 id="hbDeleteTitle">Delete hotel blocking?</h3>' +
      '<button type="button" class="btn-icon" data-hb-delete-cancel aria-label="Close">' +
      '<svg class="icon icon-sm" viewBox="0 0 24 24"><path d="M6 6l12 12M18 6 6 18"/></svg>' +
      "</button>" +
      "</div>" +
      '<p data-hb-delete-text style="margin:0;"></p>' +
      '<div style="display:flex;gap:var(--space-2);justify-content:flex-end;flex-wrap:wrap;">' +
      '<button type="button" class="btn btn-secondary btn-sm" data-hb-delete-cancel>Cancel</button>' +
      '<button type="button" class="btn btn-danger btn-sm" data-hb-delete-confirm>Delete Hotel Blocking</button>' +
      "</div>" +
      "</div>";
    document.body.appendChild(wrap);
    modalEl = wrap;

    utils.on(wrap, "click", "[data-hb-delete-cancel]", closeModal);
    wrap.addEventListener("click", function (e) {
      if (e.target === wrap) closeModal();
    });
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape" && !wrap.hasAttribute("hidden")) closeModal();
    });
    utils.on(wrap, "click", "[data-hb-delete-confirm]", function () {
      var id = pendingDeleteId;
      closeModal();
      if (id) deleteBlocking(id);
    });
  }

  function openModal(appId) {
    var app = global.KhannaState.getApplication(appId);
    if (!app) return;
    ensureModal();
    pendingDeleteId = appId;
    lastFocus = document.activeElement;
    var n = (app.hotels || []).length;
    var only = global.KhannaApplicationsList && global.KhannaApplicationsList.isHotelBlockingOnly(app);
    utils.qs("[data-hb-delete-text]", modalEl).textContent =
      "Are you sure you want to delete the hotel blocking for " + labelOf(app) + " (" + n + (n === 1 ? " hotel" : " hotels") + ")? " +
      (only
        ? "This removes it from this browser and cannot be undone."
        : "This removes its hotels and voucher details from this browser and cannot be undone. The application's other documents are kept.");
    modalEl.hidden = false;
    var cancel = modalEl.querySelector("button[data-hb-delete-cancel].btn-secondary");
    if (cancel) cancel.focus();
  }

  function closeModal() {
    if (!modalEl) return;
    modalEl.hidden = true;
    pendingDeleteId = null;
    if (lastFocus && lastFocus.focus && document.contains(lastFocus)) lastFocus.focus();
  }

  function deleteBlocking(appId) {
    var app = global.KhannaState.getApplication(appId);
    if (!app) return;
    if (global.KhannaApplicationsList.isHotelBlockingOnly(app)) {
      global.KhannaState.deleteApplication(appId);
    } else {
      global.KhannaState.updateApplication(appId, { hotels: [] }, "Hotel blocking deleted");
    }
    render();
  }

  /* ---------------- wiring ---------------- */
  function init() {
    document.addEventListener("khanna:navigate", function (e) {
      if (e.detail.view === "hotel-blockings") render();
    });
    global.KhannaState.subscribe(function () {
      var r = root();
      if (r && r.closest(".view.is-active")) render();
    });

    document.addEventListener("click", function (e) {
      var r = root();
      if (!r) return;
      var toggle = e.target.closest("[data-action='hb-download-toggle']");
      if (toggle && r.contains(toggle)) {
        var dropdown = toggle.parentNode.querySelector(".hb-menu__dropdown");
        var wasOpen = !dropdown.hidden;
        closeMenus();
        dropdown.hidden = wasOpen;
        toggle.setAttribute("aria-expanded", wasOpen ? "false" : "true");
        return;
      }
      var dl = e.target.closest("[data-action='hb-download']");
      if (dl && r.contains(dl)) {
        download(dl.getAttribute("data-app-id"), dl.getAttribute("data-format"), dl);
        return;
      }
      if (!e.target.closest("[data-hb-menu]")) closeMenus();

      var edit = e.target.closest("[data-action='hb-edit']");
      if (edit && r.contains(edit)) {
        global.KhannaState.setActiveApplicationId(edit.getAttribute("data-app-id"));
        if (global.KhannaHotels) global.KhannaHotels.requestPreview();
        global.KhannaRouter.navigate("hotel-blocking");
        return;
      }
      var del = e.target.closest("[data-action='hb-delete']");
      if (del && r.contains(del)) {
        closeMenus();
        openModal(del.getAttribute("data-app-id"));
      }
    });
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape") closeMenus();
    });

    if (location.hash.indexOf("hotel-blockings") !== -1) render();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})(window);
