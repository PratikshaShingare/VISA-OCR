/* ==========================================================================
   Khanna Travels & Holidays — Document collection & verification (step 4)
   Tracks upload/verify/reject status for every document the step-3
   checklist resolved to. Files themselves live only in
   KhannaDocumentFileStore (in-memory, this tab only — see that module's
   header comment); KhannaState only ever holds the lightweight metadata
   (name, type, status, who verified it and when).

   OCR/verification principle carried over from Phase 4: a document is
   never auto-verified just because it was uploaded — "Uploaded" and
   "Verified" are deliberately separate states, and only a staff action
   (the Verify button) makes that transition, recording who and when.
   ========================================================================== */
(function (global) {
  "use strict";

  var utils = global.KhannaUtils;
  var fileStore = global.KhannaDocumentFileStore;

  function root() {
    return utils.qs("[data-documents-step-root]");
  }

  function getApp() {
    return global.KhannaState.getActiveApplication();
  }

  function currentUserEmail() {
    var user = global.KhannaAuth && global.KhannaAuth.getCurrentUser();
    return user ? user.email : "";
  }

  function statusBadge(status) {
    if (status === "Verified") return '<span class="badge badge-success">Verified</span>';
    if (status === "Uploaded") return '<span class="badge badge-warning">Please verify</span>';
    if (status === "Rejected") return '<span class="badge badge-danger">Rejected</span>';
    return '<span class="badge">Missing</span>';
  }

  function docRowHtml(d) {
    var fileInfo =
      d.fileName
        ? utils.escapeHtml(d.fileName) + (d.uploadedAt ? " · uploaded " + utils.formatDate(d.uploadedAt) : "")
        : "No file uploaded yet";
    var verifiedLine =
      d.status === "Verified" && d.verifiedAt
        ? '<div class="doc-row__verified">Verified by ' + utils.escapeHtml(d.verifiedBy || "staff") + " on " + utils.formatDate(d.verifiedAt) + "</div>"
        : "";
    var noteBox =
      d.status === "Uploaded" || d.status === "Rejected"
        ? '<input type="text" class="doc-row__note-input" data-doc-note="' + d.id + '" placeholder="Note (e.g. reason if rejecting)" value="' + utils.escapeHtml(d.note || "") + '" />'
        : d.note
        ? '<div class="doc-row__note-readonly">' + utils.escapeHtml(d.note) + "</div>"
        : "";

    var actions = "";
    if (d.fileRef) {
      actions += '<button type="button" class="btn btn-ghost btn-sm" data-action="view-doc" data-doc-id="' + d.id + '">View</button>';
    }
    actions +=
      '<button type="button" class="btn btn-secondary btn-sm" data-action="upload-doc" data-doc-id="' + d.id + '">' +
      (d.fileRef ? "Replace" : "Upload") +
      "</button>";
    if (d.status === "Uploaded") {
      actions +=
        '<button type="button" class="btn btn-primary btn-sm" data-action="verify-doc" data-doc-id="' + d.id + '">Verify</button>' +
        '<button type="button" class="btn-icon" data-action="reject-doc" data-doc-id="' + d.id + '" aria-label="Reject document">' +
        '<svg class="icon icon-sm" viewBox="0 0 24 24"><path d="M18 6 6 18M6 6l12 12"/></svg>' +
        "</button>";
    } else if (d.status === "Rejected") {
      actions +=
        '<button type="button" class="btn btn-primary btn-sm" data-action="verify-doc" data-doc-id="' + d.id + '">Verify</button>';
    }

    return (
      '<div class="doc-row" data-doc-row="' + d.id + '">' +
      '<input type="file" hidden data-doc-file-input="' + d.id + '" />' +
      '<div class="doc-row__main">' +
      '<div class="doc-row__label">' + utils.escapeHtml(d.label) + "</div>" +
      '<div class="doc-row__meta">' + fileInfo + "</div>" +
      verifiedLine +
      noteBox +
      "</div>" +
      statusBadge(d.status) +
      '<div class="doc-row__actions">' + actions + "</div>" +
      "</div>"
    );
  }

  function renderList() {
    var r = root();
    if (!r) return;
    var listEl = utils.qs("[data-documents-list]", r);
    if (!listEl) return;
    var app = getApp();
    var travel = (app && app.travel) || {};

    if (!app || !travel.destination || !travel.visaCategory) {
      listEl.innerHTML =
        '<div class="empty-state">' +
        '<svg class="icon" viewBox="0 0 24 24"><path d="M14 3v4a1 1 0 0 0 1 1h4"/><path d="M17 21H7a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h7l5 5v11a2 2 0 0 1-2 2Z"/></svg>' +
        "<h3>No checklist yet</h3>" +
        "<p>Set a destination and visa category on the Travel &amp; Checklist step first — the document list here is built from that checklist.</p>" +
        '<button class="btn btn-secondary btn-sm" type="button" data-action="go-to-travel-step">Go to Travel &amp; Checklist</button>' +
        "</div>";
      return;
    }

    var documents = app.documents || [];
    var required = documents.filter(function (d) {
      return d.required;
    });
    var supporting = documents.filter(function (d) {
      return !d.required;
    });
    var pct = app.checklist.completionPct || 0;

    listEl.innerHTML =
      '<div class="checklist-progress">' +
      '<div class="checklist-progress__bar"><div class="checklist-progress__fill" style="width:' + pct + '%;"></div></div>' +
      "<span>" + pct + "% of required documents verified</span>" +
      "</div>" +
      '<h3>Required documents</h3>' +
      (required.length ? required.map(docRowHtml).join("") : '<p class="checklist-empty">None.</p>') +
      "<h3>Supporting documents</h3>" +
      (supporting.length ? supporting.map(docRowHtml).join("") : '<p class="checklist-empty">None.</p>');

    if (global.KhannaRouter) global.KhannaRouter.refreshWizardFooter();
  }

  function isStepComplete() {
    var app = getApp();
    if (!app) return false;
    var required = (app.documents || []).filter(function (d) {
      return d.required;
    });
    if (required.length === 0) return false; // no checklist generated yet -> nothing to be "complete"
    return required.every(function (d) {
      return d.status === "Verified";
    });
  }

  function handleFileChosen(appId, docId, file) {
    if (!file) return;
    var fileRef = utils.generateId("file");
    fileStore.put(fileRef, file);
    global.KhannaState.updateDocument(
      appId,
      docId,
      {
        status: "Uploaded",
        fileRef: fileRef,
        fileName: file.name,
        mimeType: file.type,
        uploadedAt: new Date().toISOString(),
        verifiedAt: null,
        verifiedBy: null,
      },
      "Document uploaded"
    );
    renderList();
  }

  function mountSkeleton() {
    var r = root();
    if (!r) return;
    r.innerHTML =
      '<div class="view-header">' +
      '<div class="view-header__text">' +
      "<h2>Document collection &amp; verification</h2>" +
      "<p>Upload each document from the checklist, then verify it against the original before moving on. Uploaded is not the same as verified — final verification always stays with staff.</p>" +
      "</div>" +
      "</div>" +
      '<div data-documents-list></div>';

    utils.on(r, "click", "[data-action='go-to-travel-step']", function () {
      if (global.KhannaRouter) global.KhannaRouter.navigate("new-application", 3);
    });

    utils.on(r, "click", "[data-action='upload-doc']", function (e, target) {
      var docId = target.getAttribute("data-doc-id");
      var input = utils.qs('[data-doc-file-input="' + docId + '"]', r);
      if (input) input.click();
    });

    utils.on(r, "change", "[data-doc-file-input]", function (e, target) {
      var app = getApp();
      if (!app) return;
      var docId = target.getAttribute("data-doc-file-input");
      if (target.files && target.files[0]) handleFileChosen(app.id, docId, target.files[0]);
    });

    utils.on(r, "click", "[data-action='view-doc']", function (e, target) {
      var app = getApp();
      if (!app) return;
      var docId = target.getAttribute("data-doc-id");
      var doc = (app.documents || []).find(function (d) {
        return d.id === docId;
      });
      var cached = doc && doc.fileRef ? fileStore.get(doc.fileRef) : null;
      if (cached && cached.objectUrl) {
        window.open(cached.objectUrl, "_blank", "noopener");
      } else {
        setStatusNote(docId, "Original file not available in this session — please re-upload to view it.");
      }
    });

    utils.on(r, "click", "[data-action='verify-doc']", function (e, target) {
      var app = getApp();
      if (!app) return;
      var docId = target.getAttribute("data-doc-id");
      var noteInput = utils.qs('[data-doc-note="' + docId + '"]', r);
      global.KhannaState.updateDocument(
        app.id,
        docId,
        {
          status: "Verified",
          verifiedAt: new Date().toISOString(),
          verifiedBy: currentUserEmail(),
          note: noteInput ? noteInput.value : "",
        },
        "Document verified"
      );
      renderList();
    });

    utils.on(r, "click", "[data-action='reject-doc']", function (e, target) {
      var app = getApp();
      if (!app) return;
      var docId = target.getAttribute("data-doc-id");
      var noteInput = utils.qs('[data-doc-note="' + docId + '"]', r);
      global.KhannaState.updateDocument(
        app.id,
        docId,
        { status: "Rejected", note: noteInput ? noteInput.value : "", verifiedAt: null, verifiedBy: null },
        "Document rejected"
      );
      renderList();
    });
  }

  function setStatusNote(docId, message) {
    var row = utils.qs('[data-doc-row="' + docId + '"]');
    if (!row) return;
    var meta = utils.qs(".doc-row__meta", row);
    if (meta) meta.textContent = message;
  }

  function render() {
    var r = root();
    if (!r) return;
    if (!r.dataset.mounted) {
      r.dataset.mounted = "1";
      mountSkeleton();
    }
    renderList();
  }

  function init() {
    if (global.KhannaRouter) global.KhannaRouter.registerStepValidator("new-application", 4, isStepComplete);

    document.addEventListener("khanna:navigate", function (e) {
      if (e.detail.view === "new-application") render();
    });

    global.KhannaState.subscribe(function () {
      if (root() && root().dataset.mounted) renderList();
    });

    if (location.hash.indexOf("new-application") !== -1) render();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})(window);
