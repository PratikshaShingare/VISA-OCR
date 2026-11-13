/* ==========================================================================
   Khanna Travels & Holidays — Recycle Bin page ("#/recycle-bin")

   Deleted applications — and applicants deleted with all their applications
   (Applicant Profiles' Delete) — wait here for 30 days
   (KhannaState.RECYCLE_BIN_DAYS), then are deleted permanently when the app
   next loads. Staff can:
     - tick one, several or all entries (the header box ticks every one);
     - Restore the ticked entries (back where they were);
     - Delete the ticked entries permanently, after a confirmation popup.
   Each row also has its own Restore / Delete permanently buttons.
   The data and rules live in js/core/state.js; this file is only the page.
   ========================================================================== */
(function (global) {
  "use strict";

  var utils = global.KhannaUtils;
  var S = global.KhannaState;

  var TRASH_ICON = '<svg class="icon icon-sm" viewBox="0 0 24 24" aria-hidden="true"><path d="M4 7h16M9 7V5a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2m2 0-1 13a1 1 0 0 1-1 1H8a1 1 0 0 1-1-1L6 7"/></svg>';
  var RESTORE_ICON = '<svg class="icon icon-sm" viewBox="0 0 24 24" aria-hidden="true"><path d="M3 12a9 9 0 1 0 3-6.7L3 8"/><path d="M3 3v5h5"/></svg>';

  var st = { selected: {} }; // bin entry id -> true
  var modalEl = null;
  var pendingIds = [];

  function root() {
    return utils.qs("[data-recycle-bin-root]");
  }

  function esc(v) {
    return utils.escapeHtml(v == null ? "" : String(v));
  }

  function entries() {
    return S.getRecycleBin ? S.getRecycleBin() : [];
  }

  function selectedIds() {
    var ids = entries().map(function (e) { return e.id; });
    return Object.keys(st.selected).filter(function (id) { return st.selected[id] && ids.indexOf(id) !== -1; });
  }

  function daysLeft(entry) {
    var ms = new Date(S.recycleBinExpiresAt(entry)).getTime() - Date.now();
    return Math.max(0, Math.ceil(ms / 86400000));
  }

  function docCount(apps) {
    var n = 0;
    (apps || []).forEach(function (a) {
      if (a.coverLetter && a.coverLetter.generatedAt) n += 1;
      var auth = a.authorization || {};
      if (auth.passport && auth.passport.generatedAt) n += 1;
      if (auth.company && auth.company.generatedAt) n += 1;
      if (a.invitation && a.invitation.generatedAt) n += 1;
      (a.hotels || []).forEach(function (h) { if (h.voucherGeneratedAt) n += 1; });
    });
    return n;
  }

  function whatLine(e) {
    var apps = (e.applications || []).length;
    var docs = docCount(e.applications);
    var parts = [];
    if (e.kind === "applicant") parts.push("Applicant profile");
    if (apps) parts.push(apps + " application" + (apps === 1 ? "" : "s"));
    if (docs) parts.push(docs + " generated document" + (docs === 1 ? "" : "s"));
    if ((e.companions || []).length) parts.push("companion on " + e.companions.length + " other application" + (e.companions.length === 1 ? "" : "s"));
    return parts.join(" · ");
  }

  function rowHtml(e) {
    var left = daysLeft(e);
    var checked = !!st.selected[e.id];
    return (
      '<div class="card hb-row rb-row' + (checked ? " is-selected" : "") + '">' +
      '<label class="rb-check"><input type="checkbox" data-rb-select="' + esc(e.id) + '"' + (checked ? " checked" : "") +
      ' aria-label="Select ' + esc(e.label) + '" /></label>' +
      '<div class="hb-row__info">' +
      '<div class="hb-row__name">' + esc(e.label || "Untitled") + ' <span class="badge rb-kind">' + (e.kind === "applicant" ? "Applicant" : "Application") + "</span></div>" +
      '<div class="hb-row__meta">' + (e.passportNumber ? "Passport " + esc(e.passportNumber) + " · " : "") + esc(whatLine(e)) + "</div>" +
      '<div class="hb-row__meta">Deleted ' + esc(utils.formatDate(e.deletedAt)) + ' · <span class="rb-left' + (left <= 3 ? " rb-left--soon" : "") + '">' +
      (left === 0 ? "deleted permanently today" : "deleted permanently in " + left + " day" + (left === 1 ? "" : "s")) + "</span></div>" +
      "</div>" +
      '<div class="hb-row__actions">' +
      '<button type="button" class="btn btn-secondary btn-sm" data-rb-restore="' + esc(e.id) + '">' + RESTORE_ICON + "Restore</button>" +
      '<button type="button" class="btn btn-ghost btn-sm rb-danger" data-rb-delete="' + esc(e.id) + '">' + TRASH_ICON + "Delete permanently</button>" +
      "</div></div>"
    );
  }

  function toolbarHtml(list) {
    var ids = selectedIds();
    var all = list.length && ids.length === list.length;
    return (
      '<div class="rb-toolbar" role="toolbar" aria-label="Selected items">' +
      '<label class="rb-check rb-check--all"><input type="checkbox" data-rb-select-all' + (all ? " checked" : "") + " /> " +
      "<span>" + (ids.length ? ids.length + " selected" : "Select all") + "</span></label>" +
      '<div class="rb-toolbar__actions">' +
      '<button type="button" class="btn btn-secondary btn-sm" data-rb-restore-selected' + (ids.length ? "" : " disabled") + ">" + RESTORE_ICON + "Restore selected</button>" +
      '<button type="button" class="btn btn-danger btn-sm" data-rb-delete-selected' + (ids.length ? "" : " disabled") + ">" + TRASH_ICON + "Delete selected permanently</button>" +
      "</div></div>"
    );
  }

  function render() {
    var r = root();
    if (!r) return;
    var list = entries();
    var days = S.RECYCLE_BIN_DAYS || 30;
    var intro =
      '<p class="rb-intro">Deleted applications and applicants stay here for <strong>' + days + " days</strong>, then they are deleted permanently. " +
      "Restore anything deleted by mistake, or delete it permanently now.</p>";
    if (!list.length) {
      r.innerHTML =
        '<div class="rb-layout">' + intro +
        '<div class="empty-state">' + TRASH_ICON.replace('icon-sm', '') + "<h3>The Recycle Bin is empty</h3><p>Nothing has been deleted in the last " + days + " days.</p></div></div>";
      return;
    }
    r.innerHTML = '<div class="rb-layout">' + intro + toolbarHtml(list) + '<div class="hb-list">' + list.map(rowHtml).join("") + "</div></div>";
  }

  /* ---- confirmation popup for permanent deletion ---- */

  function closeModal() {
    if (!modalEl) return;
    modalEl.setAttribute("hidden", "");
    pendingIds = [];
  }

  function ensureModal() {
    if (modalEl) return;
    var wrap = document.createElement("div");
    wrap.className = "app-picker-overlay";
    wrap.setAttribute("hidden", "");
    wrap.setAttribute("data-rb-confirm", "");
    wrap.innerHTML =
      '<div class="app-picker" role="dialog" aria-modal="true" aria-labelledby="rbConfirmTitle" style="max-width:440px;">' +
      '<div class="app-picker__header"><h3 id="rbConfirmTitle">Delete permanently?</h3>' +
      '<button type="button" class="btn-icon" data-rb-cancel aria-label="Close"><svg class="icon icon-sm" viewBox="0 0 24 24"><path d="M6 6l12 12M18 6 6 18"/></svg></button></div>' +
      '<p data-rb-confirm-text style="margin:0;"></p>' +
      '<div style="display:flex;gap:var(--space-2);justify-content:flex-end;flex-wrap:wrap;">' +
      '<button type="button" class="btn btn-secondary btn-sm" data-rb-cancel>Cancel</button>' +
      '<button type="button" class="btn btn-danger btn-sm" data-rb-confirm-delete>Delete permanently</button>' +
      "</div></div>";
    document.body.appendChild(wrap);
    modalEl = wrap;
    utils.on(wrap, "click", "[data-rb-cancel]", closeModal);
    wrap.addEventListener("click", function (e) {
      if (e.target === wrap) closeModal();
    });
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape" && !wrap.hasAttribute("hidden")) closeModal();
    });
    utils.on(wrap, "click", "[data-rb-confirm-delete]", function () {
      var ids = pendingIds.slice();
      closeModal();
      var n = S.deleteFromBinPermanently(ids);
      ids.forEach(function (id) { delete st.selected[id]; });
      render();
      if (global.KhannaToast) global.KhannaToast.show(n + " item" + (n === 1 ? "" : "s") + " deleted permanently.");
    });
  }

  function askDelete(ids) {
    if (!ids.length) return;
    ensureModal();
    pendingIds = ids;
    var list = entries().filter(function (e) { return ids.indexOf(e.id) !== -1; });
    utils.qs("[data-rb-confirm-text]", modalEl).textContent =
      (list.length === 1 ? '"' + list[0].label + '"' : list.length + " items") +
      " will be deleted permanently, with " + (list.length === 1 ? "its" : "their") + " documents and saved passport pictures. This cannot be undone.";
    modalEl.removeAttribute("hidden");
    utils.qs("[data-rb-cancel].btn", modalEl).focus();
  }

  function restore(ids) {
    if (!ids.length) return;
    var n = S.restoreFromBin(ids);
    ids.forEach(function (id) { delete st.selected[id]; });
    render();
    if (global.KhannaToast) global.KhannaToast.show(n + " item" + (n === 1 ? "" : "s") + " restored.");
  }

  function wire(r) {
    utils.on(r, "change", "[data-rb-select]", function (e, box) {
      st.selected[box.getAttribute("data-rb-select")] = box.checked;
      render();
    });
    utils.on(r, "change", "[data-rb-select-all]", function (e, box) {
      st.selected = {};
      if (box.checked) entries().forEach(function (en) { st.selected[en.id] = true; });
      render();
    });
    utils.on(r, "click", "[data-rb-restore]", function (e, btn) { restore([btn.getAttribute("data-rb-restore")]); });
    utils.on(r, "click", "[data-rb-delete]", function (e, btn) { askDelete([btn.getAttribute("data-rb-delete")]); });
    utils.on(r, "click", "[data-rb-restore-selected]", function () { restore(selectedIds()); });
    utils.on(r, "click", "[data-rb-delete-selected]", function () { askDelete(selectedIds()); });
  }

  var wired = false;

  function build() {
    var r = root();
    if (!r) return;
    if (!wired) {
      wired = true;
      wire(r);
      S.subscribe(function () {
        var rr = root();
        if (rr && rr.closest(".view.is-active")) render();
      });
    }
    render();
  }

  function init() {
    document.addEventListener("khanna:navigate", function (e) {
      if (e.detail.view !== "recycle-bin") return;
      st.selected = {};
      build();
    });
    if (location.hash.indexOf("recycle-bin") !== -1) build();
  }

  global.KhannaRecycleBin = { build: build, _state: st };

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})(window);
