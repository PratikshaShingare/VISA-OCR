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
          var docCount = collectGeneratedTimestamps(app).length;
          var docLabel = docCount === 0 ? "No documents yet" : docCount === 1 ? "1 document generated" : docCount + " documents generated";
          return (
            '<div style="display:flex;align-items:center;justify-content:space-between;gap:var(--space-3);flex-wrap:wrap;padding:var(--space-4) var(--space-5);' +
            border +
            '">' +
            '<div style="min-width:0;">' +
            '<div style="font-weight:600;">' + utils.escapeHtml(applicantLabel(app)) + "</div>" +
            '<div style="font-size:.78rem;color:var(--color-text-faint);">' +
            utils.escapeHtml(app.id) + " · Updated " + utils.formatDate(app.updatedAt) + " · " + docLabel +
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
