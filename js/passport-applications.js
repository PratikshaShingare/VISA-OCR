/* ==========================================================================
   Khanna Travels & Holidays — Recent Passports page
   "#/passport-applications" — every application that has a passport saved,
   with per-row Edit / Delete. Reached from the "Recent Passports" button in
   the Upload Passport page's title row. Same look and behaviour as Recent
   Cover Letters / Recent Hotel Blockings (css/hotel-blockings.css supplies the
   shared row styling).

     Edit   -> makes that application active and opens Upload Passport with
               the saved details.
     Delete -> asks first (popup). If the passport was ALL that application
               held, the whole (otherwise empty) application goes with it;
               otherwise only the applicant/passport details are cleared and
               the application's other documents are kept.
   ========================================================================== */
(function (global) {
  "use strict";

  var utils = global.KhannaUtils;

  var PENCIL_ICON = '<svg class="icon icon-sm" viewBox="0 0 24 24"><path d="M12 20h9M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4Z"/></svg>';
  var TRASH_ICON = '<svg class="icon icon-sm" viewBox="0 0 24 24"><path d="M4 7h16M9 7V5a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2m2 0-1 13a1 1 0 0 1-1 1H8a1 1 0 0 1-1-1L6 7"/></svg>';

  function root() {
    return utils.qs("[data-passport-applications-root]");
  }

  function lists() {
    return global.KhannaApplicationsList;
  }

  function currentPassport(app) {
    return (app.applicant && app.applicant.passport && app.applicant.passport.current) || {};
  }

  function hasPassport(app) {
    var cur = currentPassport(app);
    return !!(cur.number && String(cur.number).trim()) && lists().hasName(app);
  }

  function passports() {
    return global.KhannaState.getApplications()
      .filter(hasPassport)
      .sort(function (a, b) { return a.updatedAt < b.updatedAt ? 1 : a.updatedAt > b.updatedAt ? -1 : 0; });
  }

  function rowHtml(app) {
    var cur = currentPassport(app);
    var verified = app.applicant.passport.verificationStatus === "Verified";
    var id = utils.escapeHtml(app.id);
    var details = [cur.number, app.applicant.nationality, cur.expiryDate ? "Expires " + utils.formatDate(cur.expiryDate) : ""]
      .filter(function (part) { return part && String(part).trim(); })
      .join(" · ");
    return (
      '<div class="card hb-row" data-pp-row="' + id + '">' +
      '<div class="hb-row__info">' +
      '<div class="hb-row__name">' + utils.escapeHtml(lists().applicantLabel(app)) + "</div>" +
      '<div class="hb-row__meta">' + utils.escapeHtml(details) + "</div>" +
      '<div class="hb-row__meta hb-row__meta--faint">Updated ' + utils.formatDate(app.updatedAt) +
      " · " + (verified ? "Verified" : "OCR Extracted — Please Verify") +
      "</div>" +
      "</div>" +
      '<div class="hb-row__actions">' +
      '<button type="button" class="btn btn-secondary btn-sm" data-action="pp-edit" data-app-id="' + id + '">' + PENCIL_ICON + "Edit</button>" +
      '<button type="button" class="btn btn-danger-outline btn-sm" data-action="pp-delete" data-app-id="' + id + '">' + TRASH_ICON + "Delete</button>" +
      "</div>" +
      "</div>"
    );
  }

  function render() {
    var r = root();
    if (!r) return;
    var list = passports();
    if (!list.length) {
      r.innerHTML =
        '<div class="empty-state">' +
        '<svg class="icon" viewBox="0 0 24 24"><rect x="5" y="3" width="14" height="18" rx="2"/><circle cx="12" cy="10" r="3"/><path d="M8.5 17h7"/></svg>' +
        "<h3>No passports saved yet</h3>" +
        '<a class="btn btn-primary btn-sm" href="#/upload-passport" data-nav-link="upload-passport">Upload Passport</a>' +
        "</div>";
      return;
    }
    r.innerHTML = '<div class="hb-list">' + list.map(rowHtml).join("") + "</div>";
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
    wrap.setAttribute("data-pp-delete-modal", "");
    wrap.innerHTML =
      '<div class="app-picker" role="dialog" aria-modal="true" aria-labelledby="ppDeleteTitle" style="max-width:440px;">' +
      '<div class="app-picker__header">' +
      '<h3 id="ppDeleteTitle">Delete passport?</h3>' +
      '<button type="button" class="btn-icon" data-pp-delete-cancel aria-label="Close">' +
      '<svg class="icon icon-sm" viewBox="0 0 24 24"><path d="M6 6l12 12M18 6 6 18"/></svg>' +
      "</button>" +
      "</div>" +
      '<p data-pp-delete-text style="margin:0;"></p>' +
      '<div style="display:flex;gap:var(--space-2);justify-content:flex-end;flex-wrap:wrap;">' +
      '<button type="button" class="btn btn-secondary btn-sm" data-pp-delete-cancel>Cancel</button>' +
      '<button type="button" class="btn btn-danger btn-sm" data-pp-delete-confirm>Delete Passport</button>' +
      "</div>" +
      "</div>";
    document.body.appendChild(wrap);
    modalEl = wrap;

    utils.on(wrap, "click", "[data-pp-delete-cancel]", closeModal);
    wrap.addEventListener("click", function (e) {
      if (e.target === wrap) closeModal();
    });
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape" && !wrap.hasAttribute("hidden")) closeModal();
    });
    utils.on(wrap, "click", "[data-pp-delete-confirm]", function () {
      var id = pendingDeleteId;
      closeModal();
      if (id) deletePassport(id);
    });
  }

  function openModal(appId) {
    var app = global.KhannaState.getApplication(appId);
    if (!app) return;
    ensureModal();
    pendingDeleteId = appId;
    lastFocus = document.activeElement;
    var only = lists().isPassportOnly(app);
    utils.qs("[data-pp-delete-text]", modalEl).textContent =
      "Are you sure you want to delete the passport for " + lists().applicantLabel(app) + "? " +
      (only
        ? "This removes it from this browser and cannot be undone."
        : "This removes the applicant and passport details from this browser and cannot be undone. The application's other documents are kept.");
    modalEl.hidden = false;
    var cancel = modalEl.querySelector("button[data-pp-delete-cancel].btn-secondary");
    if (cancel) cancel.focus();
  }

  function closeModal() {
    if (!modalEl) return;
    modalEl.hidden = true;
    pendingDeleteId = null;
    if (lastFocus && lastFocus.focus && document.contains(lastFocus)) lastFocus.focus();
  }

  function deletePassport(appId) {
    var app = global.KhannaState.getApplication(appId);
    if (!app) return;
    if (lists().isPassportOnly(app)) {
      global.KhannaState.deleteApplication(appId);
    } else {
      global.KhannaState.updateApplication(appId, { applicant: global.KhannaState.createEmptyApplication("").applicant }, "Passport deleted");
    }
    render();
  }

  /* ---------------- wiring ---------------- */
  function init() {
    document.addEventListener("khanna:navigate", function (e) {
      if (e.detail.view === "passport-applications") render();
    });
    global.KhannaState.subscribe(function () {
      var r = root();
      if (r && r.closest(".view.is-active")) render();
    });

    document.addEventListener("click", function (e) {
      var r = root();
      if (!r) return;
      var edit = e.target.closest("[data-action='pp-edit']");
      if (edit && r.contains(edit)) {
        global.KhannaState.setActiveApplicationId(edit.getAttribute("data-app-id"));
        global.KhannaRouter.navigate("upload-passport");
        return;
      }
      var del = e.target.closest("[data-action='pp-delete']");
      if (del && r.contains(del)) openModal(del.getAttribute("data-app-id"));
    });

    if (location.hash.indexOf("passport-applications") !== -1) render();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})(window);
