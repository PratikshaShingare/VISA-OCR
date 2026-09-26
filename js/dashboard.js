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

  // Phase 1 (document-centric redesign): per explicit instruction, the
  // per-status KPI cards (New / Documents Pending / Under Review / Ready for
  // Submission / Submitted / Processing / Approved / Rejected) were removed
  // and NOT replaced with anything else — that decision is unchanged here.
  // Dashboard-improvements pass (31-section rebuild spec, "visual
  // hierarchy"): ONE additional real, computed card is added alongside it —
  // never a second row of per-status cards, and never a guessed number.
  // "Documents Generated" counts real generatedAt timestamps already
  // written by hotels.js/authorization.js/cover-letter.js/invitation.js/
  // checklist-letter.js's own KhannaState.updateApplication() calls; an
  // application with zero real generation events contributes 0, honestly.
  var STAT_CARDS = [
    { key: "total", label: "Total Applications" },
    { key: "documentsGenerated", label: "Documents Generated" },
  ];

  // Counts real generation EVENTS across every document type this app
  // supports, not just "has this application generated anything" — each
  // hotel voucher, each authorization letter, each cover letter, the
  // invitation letter, and each spouse's own initors letter all count
  // separately, matching what a staff member would actually think of as
  // "how many documents have we generated." Never invents a number: an
  // application with none of these timestamps set contributes 0.
  function countDocumentsGenerated(apps) {
    var count = 0;
    apps.forEach(function (app) {
      if (app.coverLetter && app.coverLetter.generatedAt) count += 1;
      if (app.authorization) {
        if (app.authorization.passport && app.authorization.passport.generatedAt) count += 1;
        if (app.authorization.company && app.authorization.company.generatedAt) count += 1;
      }
      if (app.invitation && app.invitation.generatedAt) count += 1;
      if (app.initorsLetters && app.initorsLetters.perPerson) {
        Object.keys(app.initorsLetters.perPerson).forEach(function (personId) {
          var entry = app.initorsLetters.perPerson[personId];
          if (entry && entry.generatedAt) count += 1;
        });
      }
      (app.hotels || []).forEach(function (hotel) {
        if (hotel.voucherGeneratedAt) count += 1;
      });
    });
    return count;
  }

  function applicantLabel(app) {
    var name = app.applicant && app.applicant.fullName;
    return name && name.trim() ? name : "Untitled applicant";
  }

  function renderStats() {
    var container = utils.qs("[data-dashboard-stats]");
    if (!container) return;
    var stats = global.KhannaState.getStats();
    stats.documentsGenerated = countDocumentsGenerated(global.KhannaState.getApplications());
    container.innerHTML = STAT_CARDS.map(function (card) {
      return (
        '<div class="card stat-card">' +
        '<span class="stat-card__label">' + utils.escapeHtml(card.label) + "</span>" +
        '<span class="stat-card__value">' + (stats[card.key] || 0) + "</span>" +
        "</div>"
      );
    }).join("");
  }

  function renderRecent() {
    var container = utils.qs("[data-dashboard-recent]");
    if (!container) return;
    var all = global.KhannaState.getApplications();
    var apps = all.slice(0, 4);

    if (apps.length === 0) {
      container.innerHTML =
        '<div class="empty-state">' +
        '<svg class="icon" viewBox="0 0 24 24"><path d="M3 11.5 12 4l9 7.5"/><path d="M5 10v9a1 1 0 0 0 1 1h4v-6h4v6h4a1 1 0 0 0 1-1v-9"/></svg>' +
        "<h3>No applications yet</h3>" +
        "<p>Application counts and recent activity will show up here once applications start coming in. Start from a document card above, or upload a passport to create an applicant.</p>" +
        "</div>";
      return;
    }

    container.innerHTML =
      '<div class="card" style="padding:0;">' +
      apps
        .map(function (app, i) {
          var border = i < apps.length - 1 ? "border-bottom:1px solid var(--color-border);" : "";
          return (
            '<div style="display:flex;align-items:center;justify-content:space-between;gap:var(--space-3);padding:var(--space-4) var(--space-5);' +
            border +
            '">' +
            '<div style="min-width:0;">' +
            '<div style="font-weight:600;">' + utils.escapeHtml(applicantLabel(app)) + "</div>" +
            '<div style="font-size:.78rem;color:var(--color-text-faint);">' +
            utils.escapeHtml(app.id) + " · Updated " + utils.formatDate(app.updatedAt) +
            "</div>" +
            "</div>" +
            '<span class="badge ' + utils.statusBadgeClass(app.status) + '">' + utils.escapeHtml(app.status) + "</span>" +
            "</div>"
          );
        })
        .join("") +
      "</div>" +
      (all.length > 4
        ? '<div style="margin-top:var(--space-3);"><a class="btn btn-secondary btn-sm" href="#/applications" data-nav-link="applications">View All Applications</a></div>'
        : "");
  }

  function render() {
    renderStats();
    renderRecent();
  }

  function init() {
    render();
    global.KhannaState.subscribe(render);
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
