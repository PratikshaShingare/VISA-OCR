/* ==========================================================================
   Khanna Travels & Holidays — Admin dashboard (Phase 11)
   Real content behind the Phase 3 Admin gate: a full status-breakdown
   overview, an all-applications management table (reusing the same
   status-change control as the Applications list), the Master Excel
   Export, CSV bulk import, a read-only Document Templates reference, and a
   read-only Staff Directory. Mounted into the existing [data-admin-gate]
   markup (index.html) — auth-view.js already owns showing/hiding that
   wrapper; this module only ever fills the mount points inside it.

   Honesty notes (project rule 9): the Staff Directory and Document
   Templates cards are explicitly read-only — there is no backend user
   store or template-editing capability to back a real CRUD UI, so none is
   offered. Everything else here (status changes, the export, the import)
   is fully real: every claimed action actually happens against
   KhannaState/the local backend, nothing is decorative.
   ========================================================================== */
(function (global) {
  "use strict";

  var utils = global.KhannaUtils;

  /* ---------------------------------------------------------------------
   * CSV parser — hand-rolled rather than a CDN library (project rule 16,
   * "avoid unnecessary dependencies"): this import only ever needs to read
   * plain applicant rows, not arbitrary binary spreadsheet data, and this
   * app's own README already emphasizes running self-contained on one
   * machine. Proven correct with a standalone Node test (quoted fields,
   * embedded commas/newlines, escaped quotes, CRLF, a trailing newline,
   * header aliasing) before ever being wired into this UI, matching the
   * "test the engine before trusting it" discipline every phase of this
   * project has followed for its document generators.
   * ------------------------------------------------------------------- */

  function parseCsv(text) {
    if (typeof text !== "string") return [];
    if (text.charCodeAt(0) === 0xfeff) text = text.slice(1); // strip BOM

    var rows = [];
    var row = [];
    var field = "";
    var inQuotes = false;
    var i = 0;
    var len = text.length;

    while (i < len) {
      var ch = text[i];
      if (inQuotes) {
        if (ch === '"') {
          if (text[i + 1] === '"') {
            field += '"';
            i += 2;
          } else {
            inQuotes = false;
            i += 1;
          }
        } else {
          field += ch;
          i += 1;
        }
        continue;
      }
      if (ch === '"') {
        inQuotes = true;
        i += 1;
      } else if (ch === ",") {
        row.push(field);
        field = "";
        i += 1;
      } else if (ch === "\r" || ch === "\n") {
        if (ch === "\r" && text[i + 1] === "\n") i += 1;
        row.push(field);
        field = "";
        rows.push(row);
        row = [];
        i += 1;
      } else {
        field += ch;
        i += 1;
      }
    }
    // Flush the final field/row — a file with no trailing newline still has
    // one last row's worth of content sitting in `field`/`row`.
    if (field !== "" || row.length > 0) {
      row.push(field);
      rows.push(row);
    }

    // A genuinely blank line parses to a single-field row holding an empty
    // string — drop those; they're formatting, not data. A row with real
    // empty *fields* (",,,") is kept.
    rows = rows.filter(function (r) {
      return !(r.length === 1 && r[0] === "");
    });

    return rows;
  }

  function normalizeHeader(h) {
    return String(h || "").trim().toLowerCase().replace(/[^a-z0-9]/g, "");
  }

  // Alias table: normalized header -> canonical field key, so a staff
  // member's own spelling/capitalization/punctuation still lines up
  // without renaming columns by hand first.
  var HEADER_ALIASES = {
    fullname: "fullName",
    applicantname: "fullName",
    name: "fullName",
    passportnumber: "passportNumber",
    passportno: "passportNumber",
    sex: "sex",
    gender: "sex",
    nationality: "nationality",
    email: "email",
    emailaddress: "email",
    phone: "phone",
    mobile: "phone",
    phonenumber: "phone",
    destination: "destination",
    visacategory: "visaCategory",
    visatype: "visaCategory",
    purpose: "purpose",
    countryofresidence: "countryOfResidence",
    residencecountry: "countryOfResidence",
    travelstartdate: "travelStartDate",
    startdate: "travelStartDate",
    travelenddate: "travelEndDate",
    enddate: "travelEndDate",
  };

  function parseCsvToRecords(text) {
    var rows = parseCsv(text);
    if (rows.length === 0) return { records: [], unknownColumns: [] };

    var headerRow = rows[0];
    var fieldKeys = [];
    var unknownColumns = [];
    headerRow.forEach(function (h) {
      var key = HEADER_ALIASES[normalizeHeader(h)] || null;
      fieldKeys.push(key);
      if (!key && String(h || "").trim()) unknownColumns.push(h.trim());
    });

    var records = [];
    for (var r = 1; r < rows.length; r++) {
      var row = rows[r];
      var record = {};
      for (var c = 0; c < fieldKeys.length; c++) {
        var key = fieldKeys[c];
        if (!key) continue;
        record[key] = (row[c] || "").trim();
      }
      records.push(record);
    }
    return { records: records, unknownColumns: unknownColumns };
  }

  /* ---------------------------------------------------------------------
   * Document Templates reference — a static, read-only list of the real
   * document categories this app can already generate (Phases 7-10). Not
   * editable: the reference .docx files themselves are read-only per
   * project rule 3, and this card exists only to show staff what's wired
   * up, not to let anyone touch the templates.
   * ------------------------------------------------------------------- */
  var DOCUMENT_TEMPLATES = [
    { name: "Hotel Voucher", category: "Hotel Blocking (step 5)" },
    { name: "Passport Authorization Letter", category: "Cover & Authorization (step 6)" },
    { name: "Company Authorization Letter", category: "Cover & Authorization (step 6)" },
    { name: "Cover Letter — Europe", category: "Cover & Authorization (step 6)" },
    { name: "Cover Letter — Japan", category: "Cover & Authorization (step 6)" },
    { name: "Cover Letter — Singapore", category: "Cover & Authorization (step 6)" },
    { name: "Invitation Letter", category: "Invitation Letter (step 7)" },
    { name: "Initors Covering Letter", category: "Invitation Letter (step 7)" },
  ];

  /* ---------------------------------------------------------------------
   * Overview — every real status (not just the dashboard's own curated
   * subset), since an admin needs the full lifecycle breakdown, including
   * statuses that legitimately read 0.
   * ------------------------------------------------------------------- */
  function renderOverview() {
    var container = utils.qs("[data-admin-overview]");
    if (!container) return;
    var stats = global.KhannaState.getStats();
    var statuses = global.KhannaState.STATUSES;
    var cards = [{ key: "total", label: "Total Applications" }].concat(
      statuses.map(function (s) {
        return { key: s, label: s };
      })
    );
    container.innerHTML = cards
      .map(function (c) {
        return (
          '<div class="card stat-card">' +
          '<span class="stat-card__label">' + utils.escapeHtml(c.label) + "</span>" +
          '<span class="stat-card__value">' + (stats[c.key] || 0) + "</span>" +
          "</div>"
        );
      })
      .join("");
  }

  /* ---------------------------------------------------------------------
   * All Applications table — reuses global.KhannaApplicationsList's own
   * statusSelectHtml()/applicantLabel() (applications.js, Phase 11) rather
   * than a second copy of that control or its change handler (project
   * rule 15); the single delegated listener registered in applications.js
   * already covers whatever this table renders.
   * ------------------------------------------------------------------- */
  function applicationRowHtml(app) {
    var list = global.KhannaApplicationsList;
    var name = list ? list.applicantLabel(app) : (app.applicant && app.applicant.fullName) || "Untitled applicant";
    var travel = app.travel || {};
    return (
      "<tr>" +
      "<td>" + utils.escapeHtml(name) + "</td>" +
      "<td>" + utils.escapeHtml(travel.destination || "—") + "</td>" +
      "<td>" + utils.escapeHtml(travel.visaCategory || "—") + "</td>" +
      "<td>" + (list ? list.statusSelectHtml(app) : utils.escapeHtml(app.status)) + "</td>" +
      "<td>" + ((app.travellers || []).length) + "</td>" +
      "<td>" + utils.formatDate(app.updatedAt) + "</td>" +
      "</tr>"
    );
  }

  function renderApplicationsTable() {
    var container = utils.qs("[data-admin-applications-table]");
    if (!container) return;
    var apps = global.KhannaState.getApplications();

    if (apps.length === 0) {
      container.innerHTML =
        '<div class="empty-state">' +
        '<svg class="icon" viewBox="0 0 24 24"><path d="M4 6a2 2 0 0 1 2-2h4l2 2h6a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6Z"/></svg>' +
        "<h3>No applications yet</h3>" +
        "<p>Applications created from the wizard, or imported below, will appear here.</p>" +
        "</div>";
      return;
    }

    container.innerHTML =
      '<div class="scroll-fade admin-table-scroll-fade"><div class="admin-table-wrap"><table class="admin-table"><thead><tr>' +
      "<th>Applicant</th><th>Destination</th><th>Visa Category</th><th>Status</th><th>Travellers</th><th>Updated</th>" +
      "</tr></thead><tbody>" +
      apps.map(applicationRowHtml).join("") +
      "</tbody></table></div></div>";
    wireTableScrollFade(container);
  }

  /* A real data table narrower than its own contents (project rule 13 —
     mobile must be designed intentionally) scrolls inside .admin-table-wrap
     but gave no visual hint it was scrollable until Phase 12 added the
     shared .scroll-fade affordance (components.css). Both admin tables
     re-render their whole innerHTML on every state change, so the scroll
     listener has to be re-attached each time rather than once at init —
     unlike the wizard stepper (static markup, wired once in router.js). */
  function wireTableScrollFade(container) {
    var scrollEl = utils.qs(".admin-table-wrap", container);
    var fadeEl = utils.qs(".admin-table-scroll-fade", container);
    if (scrollEl && utils.enableScrollShadows) {
      utils.enableScrollShadows(scrollEl, fadeEl);
    }
  }

  /* ---------------------------------------------------------------------
   * Document Templates (static reference list, no per-app data involved)
   * ------------------------------------------------------------------- */
  function renderTemplates() {
    var container = utils.qs("[data-admin-templates]");
    if (!container) return;
    container.innerHTML =
      '<div class="admin-template-list">' +
      DOCUMENT_TEMPLATES.map(function (t) {
        return (
          '<div class="admin-template-row">' +
          '<span class="admin-template-row__name">' + utils.escapeHtml(t.name) + "</span>" +
          '<span class="admin-template-row__category">' + utils.escapeHtml(t.category) + "</span>" +
          '<span class="badge badge-success">Wired up</span>' +
          "</div>"
        );
      }).join("") +
      "</div>";
  }

  /* ---------------------------------------------------------------------
   * Staff Directory (read-only — see the header comment above)
   * ------------------------------------------------------------------- */
  function renderStaffDirectory() {
    var container = utils.qs("[data-admin-staff-directory]");
    if (!container) return;
    var staff = global.KhannaAuth ? global.KhannaAuth.getStaffDirectory() : [];
    container.innerHTML =
      '<div class="scroll-fade admin-table-scroll-fade"><div class="admin-table-wrap"><table class="admin-table"><thead><tr>' +
      "<th>Name</th><th>Email</th><th>Role</th>" +
      "</tr></thead><tbody>" +
      staff
        .map(function (u) {
          return (
            "<tr><td>" + utils.escapeHtml(u.name) + "</td><td>" + utils.escapeHtml(u.email) + "</td><td>" +
            '<span class="badge ' + (u.role === "admin" ? "badge-info" : "") + '">' + utils.escapeHtml(u.role) + "</span>" +
            "</td></tr>"
          );
        })
        .join("") +
      "</tbody></table></div></div>";
    wireTableScrollFade(container);
  }

  /* ---------------------------------------------------------------------
   * Master Excel Export
   * ------------------------------------------------------------------- */
  function showExportNotice(kind, message) {
    var container = utils.qs("[data-admin-export-notice]");
    if (!container) return;
    if (!message) {
      container.innerHTML = "";
      return;
    }
    container.innerHTML =
      '<div class="notice notice-' + kind + '" style="margin-top:var(--space-3);">' +
      '<svg class="icon icon-sm" viewBox="0 0 24 24"><path d="M12 9v4M12 17h.01"/><circle cx="12" cy="12" r="9"/></svg>' +
      "<span>" + utils.escapeHtml(message) + "</span>" +
      "</div>";
  }

  function generateExport() {
    var btn = utils.qs("[data-action='export-excel']");
    if (!btn || btn.disabled) return;
    var apps = global.KhannaState.getApplications();
    var originalText = btn.textContent;
    btn.disabled = true;
    btn.textContent = "Exporting…";
    showExportNotice(null, null);

    global.KhannaApi
      .exportApplicationsExcel(apps)
      .then(function (result) {
        utils.triggerFileDownload(result.blob, result.filename);
        showExportNotice("success", "Exported " + apps.length + " application" + (apps.length === 1 ? "" : "s") + " — " + result.filename);
      })
      .catch(function (err) {
        showExportNotice("danger", err.message);
      })
      .then(function () {
        btn.disabled = false;
        btn.textContent = originalText;
      });
  }

  /* ---------------------------------------------------------------------
   * CSV Import
   * ------------------------------------------------------------------- */
  function csvTemplateBlob() {
    var header = "Full Name,Passport Number,Destination,Visa Category,Country of Residence,Travel Start Date,Travel End Date,Purpose\n";
    var example = "Rohan Mehta,N1234567,Europe,Tourist,India,2026-11-10,2026-11-20,Holiday\n";
    return new Blob([header + example], { type: "text/csv" });
  }

  function showImportResult(created, skipped, unknownColumns) {
    var container = utils.qs("[data-admin-import-result]");
    if (!container) return;
    if (created === null) {
      container.innerHTML = "";
      return;
    }
    var kind = created > 0 ? "success" : "warning";
    var lines = [];
    lines.push(created + " application" + (created === 1 ? "" : "s") + " created.");
    if (skipped.length) lines.push(skipped.length + " row" + (skipped.length === 1 ? "" : "s") + " skipped.");
    var html =
      '<div class="notice notice-' + kind + '" style="margin-top:var(--space-3);">' +
      '<svg class="icon icon-sm" viewBox="0 0 24 24"><path d="M12 9v4M12 17h.01"/><circle cx="12" cy="12" r="9"/></svg>' +
      "<span>" + utils.escapeHtml(lines.join(" ")) + "</span></div>";
    if (skipped.length) {
      html +=
        '<ul class="admin-import-issues">' +
        skipped.map(function (s) {
          return "<li>" + utils.escapeHtml(s) + "</li>";
        }).join("") +
        "</ul>";
    }
    if (unknownColumns && unknownColumns.length) {
      html +=
        '<p class="field-hint">Column' + (unknownColumns.length === 1 ? "" : "s") + " not recognized and ignored: " +
        utils.escapeHtml(unknownColumns.join(", ")) + "</p>";
    }
    container.innerHTML = html;
  }

  function importCsvText(text) {
    var parsed = parseCsvToRecords(text);
    var currentUser = global.KhannaAuth ? global.KhannaAuth.getCurrentUser() : null;
    var createdBy = currentUser ? currentUser.email : "";
    var created = 0;
    var skipped = [];

    parsed.records.forEach(function (record, idx) {
      var rowNum = idx + 2; // header row is row 1
      var name = (record.fullName || "").trim();
      if (!name) {
        skipped.push("Row " + rowNum + ": missing applicant full name — skipped.");
        return;
      }
      var sex = record.sex === "M" || record.sex === "F" || record.sex === "X" ? record.sex : "";
      var app = global.KhannaState.createApplication(createdBy);
      global.KhannaState.updateApplication(
        app.id,
        {
          applicant: {
            fullName: name,
            sex: sex,
            nationality: record.nationality || "",
            passport: { current: { number: record.passportNumber || "" } },
            contact: { email: record.email || "", phone: record.phone || "" },
          },
          travel: {
            destination: record.destination || "",
            visaCategory: record.visaCategory || "",
            purpose: record.purpose || "",
            countryOfResidence: record.countryOfResidence || "",
            startDate: record.travelStartDate || "",
            endDate: record.travelEndDate || "",
          },
        },
        "Imported via CSV (row " + rowNum + ")"
      );
      created += 1;
    });

    showImportResult(created, skipped, parsed.unknownColumns);
  }

  function handleCsvFile(file) {
    if (!file) return;
    var reader = new FileReader();
    reader.onload = function () {
      importCsvText(String(reader.result || ""));
    };
    reader.onerror = function () {
      showImportResult(0, ["Could not read the selected file."], []);
    };
    reader.readAsText(file);
  }

  /* ---------------------------------------------------------------------
   * Mount / render / init
   * ------------------------------------------------------------------- */
  function renderAll() {
    renderOverview();
    renderApplicationsTable();
    renderTemplates();
    renderStaffDirectory();
  }

  function init() {
    renderAll();
    global.KhannaState.subscribe(renderAll);
    if (global.KhannaAuth) global.KhannaAuth.subscribe(renderStaffDirectory);

    document.addEventListener("khanna:navigate", function (e) {
      if (e.detail.view === "admin") renderAll();
    });

    utils.on(document, "click", "[data-action='export-excel']", function (e) {
      e.preventDefault();
      generateExport();
    });

    utils.on(document, "click", "[data-action='download-csv-template']", function (e) {
      e.preventDefault();
      utils.triggerFileDownload(csvTemplateBlob(), "Khanna_Applications_Import_Template.csv");
    });

    utils.on(document, "click", "[data-action='choose-csv-file']", function (e) {
      e.preventDefault();
      var input = utils.qs("[data-csv-file-input]");
      if (input) input.click();
    });

    utils.on(document, "change", "[data-csv-file-input]", function (e, target) {
      var file = target.files && target.files[0];
      handleCsvFile(file);
      target.value = ""; // allow re-selecting the same file again later
    });
  }

  // Exposed narrowly for the standalone CSV-parser test to exercise the
  // exact functions this UI uses (project rule 17 — test before trusting).
  global.KhannaAdmin = {
    parseCsv: parseCsv,
    parseCsvToRecords: parseCsvToRecords,
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})(window);
