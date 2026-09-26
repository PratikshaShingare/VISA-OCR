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
  // as their own full row — that decision is unchanged here: this pass adds
  // a small number of additional real, computed cards, never a second row
  // of per-status cards, and never a guessed number.
  // "Documents Generated" / "Documents This Week" count real generatedAt
  // timestamps already written by hotels.js/authorization.js/
  // cover-letter.js/invitation.js/checklist-letter.js's own
  // KhannaState.updateApplication() calls; an application with zero real
  // generation events contributes 0, honestly. "Active Applications" is
  // total minus the statuses that mean the work is effectively done
  // (Submitted / Processing / Approved / Rejected / Cancelled) — a real
  // aggregate derived from KhannaState.getStats()'s own per-status counts,
  // not a new source of truth.
  var STAT_CARDS = [
    { key: "total", label: "Total Applications" },
    { key: "active", label: "Active Applications" },
    { key: "documentsGenerated", label: "Documents Generated" },
    { key: "documentsThisWeek", label: "Documents This Week" },
  ];

  var CLOSED_STATUSES = ["Submitted", "Processing", "Approved", "Rejected", "Cancelled"];
  var WEEK_MS = 7 * 24 * 60 * 60 * 1000;

  // Every real generatedAt timestamp across every document type a single
  // application has produced (hotel vouchers, both authorization letters,
  // the cover letter, the invitation letter, and each initor's own covering
  // letter) — the shared source both countDocumentsGenerated() and
  // countRecentDocumentEvents() fold over, so the two stats and the
  // per-application badge in Recent Applications can never drift apart.
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
      count += collectGeneratedTimestamps(app).length;
    });
    return count;
  }

  // Same events, but only those genuinely timestamped within the last 7
  // days — real recent activity, not a rolling guess. Timestamps are
  // ISO strings (see utils.formatDate's own callers); Date.parse returns
  // NaN for anything malformed, which correctly never counts as "recent".
  function countRecentDocumentEvents(apps) {
    var cutoff = Date.now() - WEEK_MS;
    var count = 0;
    apps.forEach(function (app) {
      collectGeneratedTimestamps(app).forEach(function (stamp) {
        var t = Date.parse(stamp);
        if (!isNaN(t) && t >= cutoff) count += 1;
      });
    });
    return count;
  }

  // Total minus the statuses that mean the work is effectively out of
  // staff's hands (submitted onward) — every value here comes straight out
  // of KhannaState.getStats()'s own real per-status counts.
  function countActiveApplications(stats) {
    var closed = 0;
    CLOSED_STATUSES.forEach(function (s) {
      closed += stats[s] || 0;
    });
    return (stats.total || 0) - closed;
  }

  function applicantLabel(app) {
    var name = app.applicant && app.applicant.fullName;
    return name && name.trim() ? name : "Untitled applicant";
  }

  function renderStats() {
    var container = utils.qs("[data-dashboard-stats]");
    if (!container) return;
    var stats = global.KhannaState.getStats();
    var apps = global.KhannaState.getApplications();
    stats.documentsGenerated = countDocumentsGenerated(apps);
    stats.documentsThisWeek = countRecentDocumentEvents(apps);
    stats.active = countActiveApplications(stats);
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
