/* ==========================================================================
   Khanna Travels & Holidays — Applications list view controller
   Lists every Application record from the central state store. Search /
   filter / sort controls are deliberately left out until Phase 6 gives
   applications real distinguishing data (destination, documents) to filter
   by — an input box that doesn't filter anything yet would be decorative.
   ========================================================================== */

(function (global) {
  "use strict";

  var utils = global.KhannaUtils;

  function applicantLabel(app) {
    var name = app.applicant && app.applicant.fullName;
    return name && name.trim() ? name : "Untitled applicant";
  }

  /**
   * Phase 11 — real, working "Application status" control (project rule 8
   * lists this as its own feature, distinct from "Application management").
   * Before this phase nothing in the app ever moved a status away from its
   * Phase 2 default of "Draft" — this <select> is the actual control that
   * does it, wired straight onto the existing KhannaState.updateApplication
   * read-modify-write path (no new state function needed: a status change
   * is just a one-field patch with its own activity-log message, exactly
   * like every other mutation in this app).
   *
   * Exported as `global.KhannaApplicationsList.statusSelectHtml` so the
   * Admin dashboard's own all-applications table (Phase 11, admin.js) can
   * render the identical control for the identical application without a
   * second copy of this markup or a second change handler — the single
   * delegated listener registered in init() below covers both, matching
   * the global.KhannaAuthorization/global.KhannaCoverLetter reuse pattern
   * already established in Phases 8-10 (project rule 15).
   */
  function statusSelectHtml(app) {
    var statuses = global.KhannaState.STATUSES;
    var options = statuses
      .map(function (s) {
        return (
          '<option value="' + utils.escapeHtml(s) + '"' +
          (s === app.status ? " selected" : "") +
          ">" + utils.escapeHtml(s) + "</option>"
        );
      })
      .join("");
    return (
      '<select class="status-select ' + utils.statusBadgeClass(app.status) +
      '" data-action="change-status" data-app-id="' + utils.escapeHtml(app.id) +
      '" aria-label="Status for ' + utils.escapeHtml(applicantLabel(app)) + '">' +
      options +
      "</select>"
    );
  }

  function rowHtml(app) {
    return (
      '<div class="card" style="display:flex;align-items:center;justify-content:space-between;gap:var(--space-3);flex-wrap:wrap;">' +
      '<div style="min-width:0;flex:1 1 220px;">' +
      '<div style="font-weight:600;">' + utils.escapeHtml(applicantLabel(app)) + "</div>" +
      '<div style="font-size:.78rem;color:var(--color-text-faint);">' +
      utils.escapeHtml(app.id) + " · Created " + utils.formatDate(app.createdAt) +
      "</div>" +
      "</div>" +
      statusSelectHtml(app) +
      '<div style="display:flex;gap:var(--space-2);">' +
      '<button class="btn btn-secondary btn-sm" type="button" data-action="open-application" data-app-id="' +
      utils.escapeHtml(app.id) +
      '">Open Full Application</button>' +
      '<button class="btn-icon" type="button" data-action="delete-application" data-app-id="' +
      utils.escapeHtml(app.id) +
      '" aria-label="Delete application">' +
      '<svg class="icon icon-sm" viewBox="0 0 24 24"><path d="M4 7h16M9 7V5a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2m2 0-1 13a1 1 0 0 1-1 1H8a1 1 0 0 1-1-1L6 7"/></svg>' +
      "</button>" +
      "</div>" +
      "</div>"
    );
  }

  function render() {
    var container = utils.qs("[data-applications-list]");
    if (!container) return;
    var apps = global.KhannaState.getApplications();

    if (apps.length === 0) {
      container.innerHTML =
        '<div class="empty-state">' +
        '<svg class="icon" viewBox="0 0 24 24"><path d="M4 6a2 2 0 0 1 2-2h4l2 2h6a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6Z"/></svg>' +
        "<h3>No applications yet</h3>" +
        "<p>Search, filtering and sorting will appear once there is at least one application to work with.</p>" +
        "</div>";
      return;
    }

    container.innerHTML = '<div style="display:flex;flex-direction:column;gap:var(--space-3);">' +
      apps.map(rowHtml).join("") +
      "</div>";
  }

  function init() {
    render();
    global.KhannaState.subscribe(render);
    document.addEventListener("khanna:navigate", function (e) {
      if (e.detail.view === "applications") render();
    });

    utils.on(document, "click", "[data-action='delete-application']", function (e, target) {
      e.preventDefault();
      var id = target.getAttribute("data-app-id");
      if (id) global.KhannaState.deleteApplication(id);
    });

    // Delegated on `document` (not scoped to the Applications list markup)
    // so the identical control rendered by admin.js's all-applications
    // table (Phase 11) is wired up for free, with no second listener.
    utils.on(document, "change", "[data-action='change-status']", function (e, target) {
      var id = target.getAttribute("data-app-id");
      var newStatus = target.value;
      if (!id || !newStatus) return;
      global.KhannaState.updateApplication(id, { status: newStatus }, "Status changed to " + newStatus);
    });
  }

  global.KhannaApplicationsList = {
    statusSelectHtml: statusSelectHtml,
    applicantLabel: applicantLabel,
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})(window);
