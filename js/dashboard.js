/* ==========================================================================
   Khanna Travels & Holidays — Dashboard view controller
   Renders real counts and recent applications from the central state store.
   No fabricated numbers: every figure here is computed from
   KhannaState.getApplications() — most will legitimately read 0 until later
   phases (applicant intake, checklist, submission) drive status changes.
   ========================================================================== */

(function (global) {
  "use strict";

  var utils = global.KhannaUtils;

  // Per explicit instruction, the dashboard shows only the one real,
  // unambiguous count — Total Applications. "Active Applications",
  // "Documents Generated" and "Documents This Week" (added in an earlier
  // pass) were removed again on request; collectGeneratedTimestamps()
  // below is kept regardless, since renderRecent() still uses it to show
  // each application's own "N documents generated" line.
  var STAT_CARDS = [{ key: "total", label: "Total Applications" }];

  var EYE_ICON = '<svg class="icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12Z"/><circle cx="12" cy="12" r="3"/></svg>';
  var TRASH_ICON = '<svg class="icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M4 7h16M9 7V5a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2m2 0-1 13a1 1 0 0 1-1 1H8a1 1 0 0 1-1-1L6 7"/></svg>';

  // Every real generatedAt timestamp across every document type a single
  // application has produced (hotel vouchers, both authorization letters,
  // the cover letter, the invitation letter, and each initor's own covering
  // letter) — used by renderRecent() below for each application's own
  // "N documents generated" line.
  function collectGeneratedTimestamps(app) {
    var stamps = [];
    if (app.coverLetter && app.coverLetter.generatedAt) stamps.push(app.coverLetter.generatedAt);
    if (app.authorization) {
      if (app.authorization.passport && app.authorization.passport.generatedAt) stamps.push(app.authorization.passport.generatedAt);
      if (app.authorization.company && app.authorization.company.generatedAt) stamps.push(app.authorization.company.generatedAt);
    }
    if (app.invitation && app.invitation.generatedAt) stamps.push(app.invitation.generatedAt);
    if (app.initorsLetters && app.initorsLetters.perPerson) {
      Object.keys(app.initorsLetters.perPerson).forEach(function (personId) {
        var entry = app.initorsLetters.perPerson[personId];
        if (entry && entry.generatedAt) stamps.push(entry.generatedAt);
      });
    }
    (app.hotels || []).forEach(function (hotel) {
      if (hotel.voucherGeneratedAt) stamps.push(hotel.voucherGeneratedAt);
    });
    return stamps;
  }

  // The generated documents of one application that can be opened in
  // preview-only mode (router.js "#/<view>/preview"), newest first. "ts" is
  // the real generatedAt the owning controller stamped when the staff member
  // last generated it; nothing here is inferred. Inviter covering letters
  // (initorsLetters) live on the Invitation Letter page, so they count
  // toward that entry.
  function previewableDocuments(app) {
    var docs = [];
    function add(view, label, ts) {
      if (ts) docs.push({ view: view, label: label, ts: ts });
    }
    add("cover-letter", "Cover Letter", app.coverLetter && app.coverLetter.generatedAt);
    var hotelTs = null;
    (app.hotels || []).forEach(function (h) {
      if (h.voucherGeneratedAt && (!hotelTs || h.voucherGeneratedAt > hotelTs)) hotelTs = h.voucherGeneratedAt;
    });
    add("hotel-blocking", "Hotel Blocking", hotelTs);
    var auth = app.authorization || {};
    add("company-authorization", "Company Authorization Letter", auth.company && auth.company.generatedAt);
    add("passport-authorization", "Passport Authorization Letter", auth.passport && auth.passport.generatedAt);
    var inviteTs = app.invitation && app.invitation.generatedAt;
    var per = (app.initorsLetters && app.initorsLetters.perPerson) || {};
    Object.keys(per).forEach(function (pid) {
      if (per[pid] && per[pid].generatedAt && (!inviteTs || per[pid].generatedAt > inviteTs)) inviteTs = per[pid].generatedAt;
    });
    add("invitation-letter", "Invitation Letter", inviteTs);
    docs.sort(function (a, b) { return a.ts < b.ts ? 1 : a.ts > b.ts ? -1 : 0; });
    return docs;
  }

  // One shared "what is this application called" rule (applications.js):
  // the applicant's name, else the first name typed anywhere on it.
  function applicantLabel(app) {
    return global.KhannaApplicationsList ? global.KhannaApplicationsList.applicantLabel(app) : "Untitled applicant";
  }

  // Applications that only ever had hotel blocking filled in are listed on the
  // Hotel Blocking page ("Recent Hotel Blockings"), not here.
  function dashboardApplications() {
    var list = global.KhannaState.getApplications();
    var lists = global.KhannaApplicationsList;
    if (!lists) return list;
    // Hotel-blocking-only drafts and applications nobody has named yet are not
    // applications worth listing.
    return list.filter(function (a) { return !lists.isHotelBlockingOnly(a) && lists.hasName(a); });
  }

  function renderStats() {
    var container = utils.qs("[data-dashboard-stats]");
    if (!container) return;
    var stats = global.KhannaState.getStats();
    stats.total = dashboardApplications().length;
    // The container itself is the card (first cell of the document-card
    // grid in index.html); only its label and live count are rendered here.
    container.innerHTML = STAT_CARDS.map(function (card) {
      return (
        '<span class="stat-card__label">' + utils.escapeHtml(card.label) + "</span>" +
        '<span class="stat-card__value">' + (stats[card.key] || 0) + "</span>"
      );
    }).join("");
  }

  function renderRecent() {
    var container = utils.qs("[data-dashboard-recent]");
    if (!container) return;
    var all = dashboardApplications();
    var apps = all.slice(0, 4);

    if (apps.length === 0) {
      container.innerHTML =
        '<div class="empty-state">' +
        '<svg class="icon" viewBox="0 0 24 24"><path d="M3 11.5 12 4l9 7.5"/><path d="M5 10v9a1 1 0 0 0 1 1h4v-6h4v6h4a1 1 0 0 0 1-1v-9"/></svg>' +
        "<h3>No applications yet</h3>" +
        "</div>";
      return;
    }

    container.innerHTML =
      '<div class="card dashboard-recent-list">' +
      apps
        .map(function (app) {
          var docCount = collectGeneratedTimestamps(app).length;
          var docLabel = docCount === 0 ? "No documents yet" : docCount === 1 ? "1 document generated" : docCount + " documents generated";
          var id = utils.escapeHtml(app.id);
          var label = utils.escapeHtml(applicantLabel(app));
          return (
            '<div class="dashboard-recent-row">' +
            '<div class="dashboard-recent-row__info">' +
            '<div class="dashboard-recent-row__name">' + label + "</div>" +
            // Two stacked lines (reads cleanly on a phone). The APP_… id is
            // not shown here — it appears in the document preview bar.
            '<div class="dashboard-recent-row__meta">' +
            "<span>Updated " + utils.formatDateTime(app.updatedAt) + "</span>" +
            "<span>" + docLabel + "</span>" +
            "</div>" +
            "</div>" +
            '<div class="dashboard-recent-row__actions">' +
            // Icon-only buttons: no border or box, blue eye to view, red
            // bin to delete. The visible text is gone, so aria-label + title
            // carry the accessible name.
            // "View" opens the generated document's PREVIEW only (not the
            // full wizard / form) — see openPreview() below.
            '<button class="btn-icon dashboard-icon-btn dashboard-icon-btn--view" type="button" data-action="dashboard-view-application" data-app-id="' + id + '" aria-label="View application ' + label + '" title="View documents">' + EYE_ICON + "</button>" +
            // A dashboard-specific action name (NOT the Applications list's
            // "delete-application", which deletes instantly): this one asks
            // for confirmation first, then calls the same
            // KhannaState.deleteApplication.
            '<button class="btn-icon dashboard-icon-btn dashboard-icon-btn--delete" type="button" data-action="dashboard-delete-application" data-app-id="' + id + '" aria-label="Delete application ' + label + '" title="Delete application">' + TRASH_ICON + "</button>" +
            "</div>" +
            "</div>"
          );
        })
        .join("") +
      "</div>" +
      // Applications is an admin-only page (section 3) — no point showing a
      // link to it a non-admin can't actually open.
      (all.length > 4 && global.KhannaAuth && global.KhannaAuth.isAdmin()
        ? '<div style="margin-top:var(--space-3);"><a class="btn btn-secondary btn-sm" href="#/applications" data-nav-link="applications">View All Applications</a></div>'
        : "");
  }

  // ---------------------------------------------------------------------
  // Delete confirmation. A small self-built modal reusing the existing
  // .app-picker-overlay / .app-picker styles (same pattern as
  // document-workspace.js's switch-application modal) rather than a native
  // confirm(), so it matches the app and works inside any embedded browser.
  // ---------------------------------------------------------------------
  var deleteModalEl = null;
  var pendingDeleteId = null;

  function closeDeleteModal() {
    if (deleteModalEl) deleteModalEl.setAttribute("hidden", "");
    pendingDeleteId = null;
  }

  function ensureDeleteModal() {
    if (deleteModalEl) return;
    var wrap = document.createElement("div");
    wrap.className = "app-picker-overlay";
    wrap.setAttribute("hidden", "");
    wrap.innerHTML =
      '<div class="app-picker" role="dialog" aria-modal="true" aria-labelledby="dashDeleteTitle" style="max-width:420px;">' +
      '<div class="app-picker__header">' +
      '<h3 id="dashDeleteTitle">Delete application?</h3>' +
      '<button type="button" class="btn-icon" data-dash-delete-cancel aria-label="Close">' +
      '<svg class="icon icon-sm" viewBox="0 0 24 24"><path d="M6 6l12 12M18 6 6 18"/></svg>' +
      "</button>" +
      "</div>" +
      '<p data-dash-delete-text style="margin:0;"></p>' +
      '<div style="display:flex;gap:var(--space-2);justify-content:flex-end;flex-wrap:wrap;">' +
      '<button type="button" class="btn btn-secondary btn-sm" data-dash-delete-cancel>Cancel</button>' +
      '<button type="button" class="btn btn-danger btn-sm" data-dash-delete-confirm>Delete Application</button>' +
      "</div>" +
      "</div>";
    document.body.appendChild(wrap);
    deleteModalEl = wrap;

    utils.on(wrap, "click", "[data-dash-delete-cancel]", closeDeleteModal);
    wrap.addEventListener("click", function (e) {
      if (e.target === wrap) closeDeleteModal();
    });
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape" && !wrap.hasAttribute("hidden")) closeDeleteModal();
    });
    utils.on(wrap, "click", "[data-dash-delete-confirm]", function () {
      var id = pendingDeleteId;
      closeDeleteModal();
      // deleteApplication() persists and notifies subscribers, which
      // re-renders both the Total Applications card and this list.
      if (id) global.KhannaState.deleteApplication(id);
    });
  }

  function openDeleteModal(id) {
    var app = global.KhannaState.getApplications().filter(function (a) { return a.id === id; })[0];
    if (!app) return;
    ensureDeleteModal();
    pendingDeleteId = id;
    utils.qs("[data-dash-delete-text]", deleteModalEl).textContent =
      "Are you sure you want to delete the application for " + applicantLabel(app) +
      "? This removes it and its saved details from this browser and cannot be undone.";
    deleteModalEl.removeAttribute("hidden");
    utils.qs("[data-dash-delete-cancel].btn", deleteModalEl).focus();
  }

  // ---------------------------------------------------------------------
  // View (eye icon): open the generated document's PREVIEW only.
  // The application becomes the active one, then the document page opens in
  // router.js preview-only mode ("#/<view>/preview") — js/document-preview.js
  // regenerates that document from the saved application data and shows just
  // the preview, not the form fields. One generated document opens straight
  // away; several show a small chooser; none opens the page the application
  // was last worked on (its preview bar explains if nothing can be shown yet).
  // ---------------------------------------------------------------------
  var chooseModalEl = null;

  function closeChooseModal() {
    if (chooseModalEl) chooseModalEl.setAttribute("hidden", "");
  }

  function openPreview(appId, doc) {
    closeChooseModal();
    global.KhannaState.setActiveApplicationId(appId);
    global.KhannaRouter.navigate(doc.view, null, "preview");
  }

  function ensureChooseModal() {
    if (chooseModalEl) return;
    var wrap = document.createElement("div");
    wrap.className = "app-picker-overlay";
    wrap.setAttribute("hidden", "");
    wrap.innerHTML =
      '<div class="app-picker" role="dialog" aria-modal="true" aria-labelledby="dashViewTitle" style="max-width:420px;">' +
      '<div class="app-picker__header">' +
      '<h3 id="dashViewTitle">Which document?</h3>' +
      '<button type="button" class="btn-icon" data-dash-view-close aria-label="Close">' +
      '<svg class="icon icon-sm" viewBox="0 0 24 24"><path d="M6 6l12 12M18 6 6 18"/></svg>' +
      "</button>" +
      "</div>" +
      '<p data-dash-view-text style="margin:0;"></p>' +
      '<div data-dash-view-list style="display:flex;flex-direction:column;gap:var(--space-2);"></div>' +
      "</div>";
    document.body.appendChild(wrap);
    chooseModalEl = wrap;
    utils.on(wrap, "click", "[data-dash-view-close]", closeChooseModal);
    wrap.addEventListener("click", function (e) {
      if (e.target === wrap) closeChooseModal();
    });
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape" && !wrap.hasAttribute("hidden")) closeChooseModal();
    });
  }

  // Where "View" goes when nothing has been generated yet. The page the
  // application was last worked on (router-independent hint stamped by
  // js/document-preview.js as app.lastDocView), else whichever document page
  // holds saved details for it, else the Cover Letter page. Never a popup:
  // the preview page itself explains what is missing.
  var DOC_VIEWS = ["cover-letter", "hotel-blocking", "company-authorization", "passport-authorization", "invitation-letter"];

  function fallbackDocView(app) {
    if (app.lastDocView && DOC_VIEWS.indexOf(app.lastDocView) !== -1) return app.lastDocView;
    var cl = app.coverLetter || {};
    if ((cl.selectedPersonIds || []).length || (cl.recipientText || "").trim() || (cl.manualApplicantName || "").trim()) return "cover-letter";
    if ((app.hotels || []).some(function (h) { return (h.hotelName || "").trim(); })) return "hotel-blocking";
    var au = app.authorization || {};
    if (au.company && ((au.company.selectedPersonIds || []).length || (au.company.recipientText || "").trim())) return "company-authorization";
    if (au.passport && ((au.passport.selectedPersonIds || []).length || (au.passport.recipientCentreName || "").trim())) return "passport-authorization";
    if (app.invitation && (app.invitation.selectedInviteeIds || []).length) return "invitation-letter";
    return "cover-letter";
  }

  function viewApplication(appId) {
    var app = global.KhannaState.getApplications().filter(function (a) { return a.id === appId; })[0];
    if (!app) return;
    var docs = previewableDocuments(app);
    if (docs.length === 0) {
      openPreview(appId, { view: fallbackDocView(app) });
      return;
    }
    if (docs.length === 1) {
      openPreview(appId, docs[0]);
      return;
    }
    ensureChooseModal();
    utils.qs("[data-dash-view-text]", chooseModalEl).textContent =
      applicantLabel(app) + " has " + docs.length + " generated documents. Choose one to preview.";
    var list = utils.qs("[data-dash-view-list]", chooseModalEl);
    list.innerHTML = docs
      .map(function (d, i) {
        return (
          '<button type="button" class="btn btn-secondary" data-dash-view-pick="' + i + '" style="justify-content:space-between;text-align:left;">' +
          "<span>" + utils.escapeHtml(d.label) + "</span>" +
          '<span class="field-hint" style="margin:0;">Generated ' + utils.escapeHtml(utils.formatDate(d.ts)) + "</span>" +
          "</button>"
        );
      })
      .join("");
    list.onclick = function (e) {
      var btn = e.target.closest("[data-dash-view-pick]");
      if (btn) openPreview(appId, docs[parseInt(btn.getAttribute("data-dash-view-pick"), 10)]);
    };
    chooseModalEl.removeAttribute("hidden");
    var first = utils.qs("[data-dash-view-pick]", chooseModalEl);
    if (first) first.focus();
  }

  function render() {
    renderStats();
    renderRecent();
  }

  function init() {
    render();
    global.KhannaState.subscribe(render);
    // Re-render on login/logout too, not just state/navigation changes —
    // the "View All Applications" link's visibility depends on
    // KhannaAuth.isAdmin() (section 3: Applications is admin-only).
    if (global.KhannaAuth) global.KhannaAuth.subscribe(render);
    utils.on(document, "click", "[data-action='dashboard-view-application']", function (e, target) {
      e.preventDefault();
      viewApplication(target.getAttribute("data-app-id"));
    });
    utils.on(document, "click", "[data-action='dashboard-delete-application']", function (e, target) {
      e.preventDefault();
      openDeleteModal(target.getAttribute("data-app-id"));
    });
    document.addEventListener("khanna:navigate", function (e) {
      if (e.detail.view === "dashboard") render();
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})(window);
