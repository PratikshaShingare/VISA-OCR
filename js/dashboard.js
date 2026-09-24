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

  // Phase 27: the KPI cards shown on the dashboard.
  var STAT_CARDS = [
    { key: "total", label: "Total Applications" },
    { key: "New", label: "New Applications" },
    { key: "Documents Pending", label: "Documents Pending" },
    { key: "Under Review", label: "Under Review" },
    { key: "Ready for Submission", label: "Ready for Submission" },
    { key: "Submitted", label: "Submitted" },
    { key: "Processing", label: "Processing" },
    { key: "Approved", label: "Approved" },
    { key: "Rejected", label: "Rejected" },
  ];

  function applicantLabel(app) {
    var name = app.applicant && app.applicant.fullName;
    return name && name.trim() ? name : "Untitled applicant";
  }

  function renderStats() {
    var container = utils.qs("[data-dashboard-stats]");
    if (!container) return;
    var stats = global.KhannaState.getStats();
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
    var apps = global.KhannaState.getApplications().slice(0, 5);

    if (apps.length === 0) {
      container.innerHTML =
        '<div class="empty-state">' +
        '<svg class="icon" viewBox="0 0 24 24"><path d="M3 11.5 12 4l9 7.5"/><path d="M5 10v9a1 1 0 0 0 1 1h4v-6h4v6h4a1 1 0 0 0 1-1v-9"/></svg>' +
        "<h3>No applications yet</h3>" +
        "<p>Application counts, recent activity and pending documents will show up here once applications start coming in.</p>" +
        '<button class="btn btn-secondary btn-sm" type="button" data-action="new-application">Create the first application</button>' +
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
      "</div>";
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
