/* ==========================================================================
   Khanna Travels & Holidays — Recent Cover Letters page
   "#/cover-letters" — every application that has a cover letter started
   (a destination country chosen), with per-row Edit / Download (DOCX or PDF)
   / Delete. Reached from the "Recent Cover Letters" button in the Cover
   Letter page's title row. Same look and behaviour as Recent Hotel Blockings
   (css/hotel-blockings.css supplies the shared row/menu styling).

   Nothing here is invented: each row is an application record from the
   central state store (KhannaState).
     Edit     -> makes that application active and opens the Cover Letter page
                 straight on its preview (when the letter is complete).
     Download -> asks the backend for the real Cover Letter (the same
                 /api/documents/cover-letter call the preview's download
                 buttons use), as .docx or .pdf. Built from the saved details,
                 so any wording typed into the Europe letter-wording box and
                 not yet generated is not part of it.
     Delete   -> asks first (popup). Deleting clears the cover letter; if the
                 cover letter was ALL that application had, the whole
                 (otherwise empty) application goes with it, and if it also
                 holds other documents/data those are kept.
   ========================================================================== */
(function (global) {
  "use strict";

  var utils = global.KhannaUtils;

  var PENCIL_ICON = '<svg class="icon icon-sm" viewBox="0 0 24 24"><path d="M12 20h9M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4Z"/></svg>';
  var DOWNLOAD_ICON = '<svg class="icon icon-sm" viewBox="0 0 24 24"><path d="M12 4v11m0 0-4-4m4 4 4-4M5 20h14"/></svg>';
  var CHEVRON_ICON = '<svg class="icon icon-sm" viewBox="0 0 24 24"><path d="m6 9 6 6 6-6"/></svg>';
  var TRASH_ICON = '<svg class="icon icon-sm" viewBox="0 0 24 24"><path d="M4 7h16M9 7V5a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2m2 0-1 13a1 1 0 0 1-1 1H8a1 1 0 0 1-1-1L6 7"/></svg>';

  function root() {
    return utils.qs("[data-cover-letters-root]");
  }

  function labelOf(app) {
    return global.KhannaApplicationsList ? global.KhannaApplicationsList.applicantLabel(app) : "Untitled applicant";
  }

  function letters() {
    return global.KhannaState.getApplications()
      .filter(function (a) { return a.coverLetter && a.coverLetter.region; })
      .sort(function (a, b) { return a.updatedAt < b.updatedAt ? 1 : a.updatedAt > b.updatedAt ? -1 : 0; });
  }

  function summary(app) {
    var c = app.coverLetter || {};
    var auth = global.KhannaAuthorization;
    var ids = c.selectedPersonIds || [];
    var names = [];
    if ((c.manualApplicantName || "").trim()) names.push(c.manualApplicantName.trim());
    var pool = auth ? auth.getSelectablePeople(app) : [];
    pool.concat((c.importedPeople || []).map(function (p) {
      return { id: p.id, fullName: p.fullName, salutation: p.salutation };
    })).forEach(function (p) {
      if (ids.indexOf(p.id) !== -1) {
        var n = ((p.salutation ? p.salutation + ". " : "") + (p.fullName || "")).trim();
        if (n) names.push(n);
      }
    });
    var dates = c.travelStartDate && c.travelEndDate
      ? utils.formatDate(c.travelStartDate) + " → " + utils.formatDate(c.travelEndDate)
      : "Travel dates not set";
    return {
      country: c.country || c.destinationCountry || "Country not chosen",
      names: names,
      dates: dates,
      generated: c.generatedAt || null,
      ready: global.KhannaCoverLetter ? global.KhannaCoverLetter.isReady(app) : false,
    };
  }

  function rowHtml(app) {
    var s = summary(app);
    var id = utils.escapeHtml(app.id);
    return (
      '<div class="card hb-row" data-cl-row="' + id + '">' +
      '<div class="hb-row__info">' +
      '<div class="hb-row__name">' + utils.escapeHtml(labelOf(app)) + "</div>" +
      '<div class="hb-row__meta">' + utils.escapeHtml(s.country) + " · " + utils.escapeHtml(s.dates) + "</div>" +
      '<div class="hb-row__hotels">' + utils.escapeHtml(s.names.length ? s.names.join(" · ") : "No applicant selected yet") + "</div>" +
      '<div class="hb-row__meta hb-row__meta--faint">Updated ' + utils.formatDate(app.updatedAt) +
      (s.generated ? " · Generated " + utils.formatDate(s.generated) : " · Not generated yet") +
      (s.ready ? "" : " · Details incomplete") +
      "</div>" +
      "</div>" +
      '<div class="hb-row__actions">' +
      '<button type="button" class="btn btn-secondary btn-sm" data-action="cl-edit" data-app-id="' + id + '">' + PENCIL_ICON + "Edit</button>" +
      '<div class="hb-menu" data-cl-menu>' +
      '<button type="button" class="btn btn-secondary btn-sm" data-action="cl-download-toggle" data-app-id="' + id + '" aria-haspopup="true" aria-expanded="false">' +
      DOWNLOAD_ICON + "Download" + CHEVRON_ICON + "</button>" +
      '<div class="hb-menu__dropdown" role="menu" hidden>' +
      '<button type="button" class="hb-menu__item" role="menuitem" data-action="cl-download" data-format="docx" data-app-id="' + id + '">Download as DOCX</button>' +
      '<button type="button" class="hb-menu__item" role="menuitem" data-action="cl-download" data-format="pdf" data-app-id="' + id + '">Download as PDF</button>' +
      "</div>" +
      "</div>" +
      '<button type="button" class="btn btn-danger-outline btn-sm" data-action="cl-delete" data-app-id="' + id + '">' + TRASH_ICON + "Delete</button>" +
      "</div>" +
      '<div class="hb-row__error" data-cl-error hidden></div>' +
      "</div>"
    );
  }

  function render() {
    var r = root();
    if (!r) return;
    var list = letters();
    if (!list.length) {
      r.innerHTML =
        '<div class="empty-state">' +
        '<svg class="icon" viewBox="0 0 24 24"><path d="M4 6h16v12H4zM4 7l8 6 8-6"/></svg>' +
        "<h3>No cover letters yet</h3>" +
        '<a class="btn btn-primary btn-sm" href="#/cover-letter" data-nav-link="cover-letter">Go to Cover Letter</a>' +
        "</div>";
      return;
    }
    r.innerHTML = '<div class="hb-list">' + list.map(rowHtml).join("") + "</div>";
  }

  /* ---------------- download menu ---------------- */
  function closeMenus() {
    utils.qsa("[data-cl-menu] .hb-menu__dropdown", root() || document).forEach(function (d) {
      d.hidden = true;
    });
    utils.qsa("[data-action='cl-download-toggle']", root() || document).forEach(function (b) {
      b.setAttribute("aria-expanded", "false");
    });
  }

  function showRowError(row, message) {
    var box = row && row.querySelector("[data-cl-error]");
    if (!box) return;
    box.hidden = !message;
    box.textContent = message || "";
  }

  function download(appId, format, btn) {
    var row = btn.closest("[data-cl-row]");
    showRowError(row, "");
    var original = btn.textContent;
    btn.disabled = true;
    btn.textContent = "Preparing…";
    global.KhannaCoverLetter.downloadFor(appId, format).then(
      function (res) {
        utils.triggerFileDownload(res.blob, res.filename || "Cover_Letter." + format);
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
    wrap.setAttribute("data-cl-delete-modal", "");
    wrap.innerHTML =
      '<div class="app-picker" role="dialog" aria-modal="true" aria-labelledby="clDeleteTitle" style="max-width:440px;">' +
      '<div class="app-picker__header">' +
      '<h3 id="clDeleteTitle">Delete cover letter?</h3>' +
      '<button type="button" class="btn-icon" data-cl-delete-cancel aria-label="Close">' +
      '<svg class="icon icon-sm" viewBox="0 0 24 24"><path d="M6 6l12 12M18 6 6 18"/></svg>' +
      "</button>" +
      "</div>" +
      '<p data-cl-delete-text style="margin:0;"></p>' +
      '<div style="display:flex;gap:var(--space-2);justify-content:flex-end;flex-wrap:wrap;">' +
      '<button type="button" class="btn btn-secondary btn-sm" data-cl-delete-cancel>Cancel</button>' +
      '<button type="button" class="btn btn-danger btn-sm" data-cl-delete-confirm>Delete Cover Letter</button>' +
      "</div>" +
      "</div>";
    document.body.appendChild(wrap);
    modalEl = wrap;

    utils.on(wrap, "click", "[data-cl-delete-cancel]", closeModal);
    wrap.addEventListener("click", function (e) {
      if (e.target === wrap) closeModal();
    });
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape" && !wrap.hasAttribute("hidden")) closeModal();
    });
    utils.on(wrap, "click", "[data-cl-delete-confirm]", function () {
      var id = pendingDeleteId;
      closeModal();
      if (id) deleteLetter(id);
    });
  }

  function openModal(appId) {
    var app = global.KhannaState.getApplication(appId);
    if (!app) return;
    ensureModal();
    pendingDeleteId = appId;
    lastFocus = document.activeElement;
    var only = global.KhannaApplicationsList && global.KhannaApplicationsList.isCoverLetterOnly(app);
    utils.qs("[data-cl-delete-text]", modalEl).textContent =
      "Are you sure you want to delete the cover letter for " + labelOf(app) + "? " +
      (only
        ? "This removes it from this browser and cannot be undone."
        : "This removes the cover letter details from this browser and cannot be undone. The application's other documents are kept.");
    modalEl.hidden = false;
    var cancel = modalEl.querySelector("button[data-cl-delete-cancel].btn-secondary");
    if (cancel) cancel.focus();
  }

  function closeModal() {
    if (!modalEl) return;
    modalEl.hidden = true;
    pendingDeleteId = null;
    if (lastFocus && lastFocus.focus && document.contains(lastFocus)) lastFocus.focus();
  }

  function deleteLetter(appId) {
    var app = global.KhannaState.getApplication(appId);
    if (!app) return;
    if (global.KhannaApplicationsList.isCoverLetterOnly(app)) {
      global.KhannaState.deleteApplication(appId);
    } else {
      // Back to a brand-new application's own (empty) cover letter section.
      var fresh = Object.assign({ manualApplicantName: "" }, global.KhannaState.createEmptyApplication("").coverLetter);
      global.KhannaState.updateApplication(appId, { coverLetter: fresh }, "Cover letter deleted");
    }
    render();
  }

  /* ---------------- wiring ---------------- */
  function init() {
    document.addEventListener("khanna:navigate", function (e) {
      if (e.detail.view === "cover-letters") render();
    });
    global.KhannaState.subscribe(function () {
      var r = root();
      if (r && r.closest(".view.is-active")) render();
    });

    document.addEventListener("click", function (e) {
      var r = root();
      if (!r) return;
      var toggle = e.target.closest("[data-action='cl-download-toggle']");
      if (toggle && r.contains(toggle)) {
        var dropdown = toggle.parentNode.querySelector(".hb-menu__dropdown");
        var wasOpen = !dropdown.hidden;
        closeMenus();
        dropdown.hidden = wasOpen;
        toggle.setAttribute("aria-expanded", wasOpen ? "false" : "true");
        return;
      }
      var dl = e.target.closest("[data-action='cl-download']");
      if (dl && r.contains(dl)) {
        download(dl.getAttribute("data-app-id"), dl.getAttribute("data-format"), dl);
        return;
      }
      if (!e.target.closest("[data-cl-menu]")) closeMenus();

      var edit = e.target.closest("[data-action='cl-edit']");
      if (edit && r.contains(edit)) {
        global.KhannaState.setActiveApplicationId(edit.getAttribute("data-app-id"));
        if (global.KhannaCoverLetter) global.KhannaCoverLetter.requestPreview();
        global.KhannaRouter.navigate("cover-letter");
        return;
      }
      var del = e.target.closest("[data-action='cl-delete']");
      if (del && r.contains(del)) {
        closeMenus();
        openModal(del.getAttribute("data-app-id"));
      }
    });
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape") closeMenus();
    });

    if (location.hash.indexOf("cover-letters") !== -1) render();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})(window);
