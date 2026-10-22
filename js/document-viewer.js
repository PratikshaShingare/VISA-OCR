/* ==========================================================================
   Khanna Travels & Holidays — Shared A4 document viewer
   ONE reusable preview/download/edit/regenerate component used by every
   document-generating module (Hotel Voucher, Passport Authorization,
   Company Authorization, Cover Letter, Invitation Letter, Required
   Document Letter). Per the 31-section rebuild spec: "Do not create a
   different viewer for every document. Use one shared component/system."

   Architecture — "the preview must NOT be an HTML imitation":
     Form data -> real backend docx generation -> real PDF conversion
     (docx_utils.convert_docx_bytes_to_pdf, same path every download
     already used) -> that EXACT PDF blob is both rendered here (via
     pdf.js) AND handed to the "Download PDF" button — the same bytes,
     never a second/different render. "Download DOCX" is a separate real
     request for the .docx format of the same generation call. Nothing
     here draws the document itself — it only rasterizes the real PDF
     pdf.js parses, so fonts/margins/logo/header/footer/tables/line
     wrapping are exactly what the generated file actually contains.

   Rendering library: pdf.js, vendored locally at
   assets/vendor/pdfjs/{pdf.min.js,pdf.worker.min.js} (project rule:
   external CDN libraries are fine for genuinely-required cases like PDF
   libraries; vendoring the same files locally avoids an external runtime
   dependency for a Vercel deployment and keeps this working with no
   network egress at all).

   Usage (see any of hotels.js/authorization.js/cover-letter.js/
   invitation.js/checklist-letter.js for a real caller):

     var handle = KhannaDocumentViewer.mount(containerEl, {
       title: "Hotel Voucher",
       loadPdf: function () { return api.downloadX(..., "pdf", ...); },   // -> Promise<{blob, filename}>
       loadDocx: function () { return api.downloadX(..., "docx", ...); }, // -> Promise<{blob, filename}> | null/omit
       onEdit: function () { ... scroll back to the form ... },
       onRegenerate: function () { return Promise.resolve(); }, // optional; omit to hide the Regenerate button
     });
     handle.refresh();   // re-runs loadPdf and re-renders (e.g. after external state change)
     handle.destroy();   // tears down listeners/canvas/object URLs

   Every module keeps its own <form> exactly as before; this component
   only owns the preview area a module mounts it into.
   ========================================================================== */
(function (global) {
  "use strict";

  var utils = global.KhannaUtils;

  var PDFJS_READY = null;
  function ensurePdfJs() {
    if (PDFJS_READY) return PDFJS_READY;
    if (global.pdfjsLib) {
      global.pdfjsLib.GlobalWorkerOptions.workerSrc = "assets/vendor/pdfjs/pdf.worker.min.js";
      PDFJS_READY = Promise.resolve(global.pdfjsLib);
      return PDFJS_READY;
    }
    PDFJS_READY = new Promise(function (resolve, reject) {
      var script = document.createElement("script");
      script.src = "assets/vendor/pdfjs/pdf.min.js";
      script.onload = function () {
        if (!global.pdfjsLib) {
          reject(new Error("pdf.js loaded but window.pdfjsLib is missing"));
          return;
        }
        global.pdfjsLib.GlobalWorkerOptions.workerSrc = "assets/vendor/pdfjs/pdf.worker.min.js";
        resolve(global.pdfjsLib);
      };
      script.onerror = function () {
        reject(new Error("Could not load the PDF viewer library (assets/vendor/pdfjs/pdf.min.js)."));
      };
      document.head.appendChild(script);
    });
    return PDFJS_READY;
  }

  var ZOOM_STEPS = [0.5, 0.67, 0.75, 0.9, 1, 1.1, 1.25, 1.5, 1.75, 2, 2.5, 3];

  // Must match css/document-viewer.css's own `.doc-viewer__body { max-height: 72vh }`
  // — kept as one named constant so the "fit whole page, header AND footer,
  // without scrolling" calculation below stays in sync with the actual CSS
  // box it's fitting into, rather than drifting out of step with it later.
  var BODY_MAX_HEIGHT_VH = 0.72;

  function nearestZoomIndex(scale) {
    var best = 0;
    var bestDiff = Infinity;
    for (var i = 0; i < ZOOM_STEPS.length; i++) {
      var diff = Math.abs(ZOOM_STEPS[i] - scale);
      if (diff < bestDiff) {
        bestDiff = diff;
        best = i;
      }
    }
    return best;
  }

  function shellHtml(title, regenerateLabel) {
    return (
      '<div class="doc-viewer">' +
      '<div class="doc-viewer__toolbar">' +
      '<div class="doc-viewer__title" data-dv-title>' +
      utils.escapeHtml(title || "Document preview") +
      "</div>" +
      // Edit toggle (top of the Preview section). Shown for every document;
      // live only when the document has an editable layout, otherwise it is
      // disabled with an honest reason in its tooltip.
      '<button type="button" class="btn btn-secondary btn-sm doc-viewer__edit" data-dv="edit-toggle" aria-pressed="false" hidden>' +
      '<svg class="icon icon-sm" viewBox="0 0 24 24"><path d="M4 20h4L19 9l-4-4L4 16v4zM14 6l4 4"/></svg>' +
      '<span data-dv-label>Edit</span></button>' +
      // Word-like formatting tools (js/preview-editor.js) — only filled and
      // shown for documents mounted with an `editor` option.
      '<div class="doc-viewer__format" data-dv="format-tools" hidden></div>' +
      '<div class="doc-viewer__group">' +
      '<button type="button" class="btn-icon" data-dv="zoom-out" aria-label="Zoom out" title="Zoom out">' +
      '<svg class="icon icon-sm" viewBox="0 0 24 24"><circle cx="11" cy="11" r="7"/><path d="M21 21l-3.5-3.5M8 11h6"/></svg>' +
      "</button>" +
      '<button type="button" class="doc-viewer__zoom-label" data-dv="zoom-label" title="Set zoom">100%</button>' +
      '<button type="button" class="btn-icon" data-dv="zoom-in" aria-label="Zoom in" title="Zoom in">' +
      '<svg class="icon icon-sm" viewBox="0 0 24 24"><circle cx="11" cy="11" r="7"/><path d="M21 21l-3.5-3.5M11 8v6M8 11h6"/></svg>' +
      "</button>" +
      '<button type="button" class="btn btn-ghost btn-sm" data-dv="fit" title="Fit to page width">Fit</button>' +
      "</div>" +
      '<div class="doc-viewer__group">' +
      '<button type="button" class="btn-icon" data-dv="prev-page" aria-label="Previous page" title="Previous page">' +
      '<svg class="icon icon-sm" viewBox="0 0 24 24"><path d="M15 6l-6 6 6 6"/></svg>' +
      "</button>" +
      '<span class="doc-viewer__page-label" data-dv="page-label">Page 1 of 1</span>' +
      '<button type="button" class="btn-icon" data-dv="next-page" aria-label="Next page" title="Next page">' +
      '<svg class="icon icon-sm" viewBox="0 0 24 24"><path d="M9 6l6 6-6 6"/></svg>' +
      "</button>" +
      "</div>" +
      '<div class="doc-viewer__group">' +
      '<button type="button" class="btn-icon" data-dv="print" aria-label="Print" title="Print">' +
      '<svg class="icon icon-sm" viewBox="0 0 24 24"><path d="M6 9V3h12v6M6 18H4a1 1 0 0 1-1-1v-5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2v5a1 1 0 0 1-1 1h-2M6 14h12v7H6z"/></svg>' +
      "</button>" +
      '<button type="button" class="btn-icon" data-dv="fullscreen" aria-label="Full screen" title="Full screen">' +
      '<svg class="icon icon-sm" viewBox="0 0 24 24"><path d="M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5"/></svg>' +
      "</button>" +
      "</div>" +
      "</div>" +
      '<div class="doc-viewer__body" data-dv="body">' +
      '<div class="doc-viewer__status" data-dv="status">Generating document…</div>' +
      '<div class="doc-viewer__page" data-dv="page" hidden>' +
      '<canvas class="doc-viewer__canvas" data-dv="canvas" hidden></canvas>' +
      '<div class="doc-viewer__overlay" data-dv="overlay"></div>' +
      "</div>" +
      "</div>" +
      '<div class="doc-viewer__actions">' +
      '<div class="doc-viewer__actions-left" data-dv="meta"></div>' +
      '<div class="doc-viewer__actions-right">' +
      // Client-requested exact 3-button set: Preview / Download as Docx /
      // Download as PDF. "Preview" replaces the old separate "Edit
      // details" + "Regenerate" pair — every real caller's own
      // onRegenerate is a no-op today (it exists only so refresh() runs
      // again against the CURRENT form state), so "re-show the current
      // preview" is exactly what "Preview" means here; "Edit details"
      // (scroll back up to the form) is dropped to keep the count at
      // exactly 3, since the Word-like editable-fields section already
      // sits directly above this button on every document page.
      '<button type="button" class="btn btn-secondary btn-sm" data-dv="regenerate">' + utils.escapeHtml(regenerateLabel || "Preview") + "</button>" +
      '<button type="button" class="btn btn-secondary btn-sm" data-dv="download-docx" hidden>Download as Docx</button>' +
      '<button type="button" class="btn btn-primary btn-sm" data-dv="download-pdf">Download as PDF</button>' +
      "</div>" +
      "</div>" +
      "</div>"
    );
  }

  function DocumentViewerInstance(container, options) {
    this.container = container;
    this.options = options || {};
    this.scale = 1;
    this.fitMode = true;
    this.currentPage = 1;
    this.numPages = 0;
    this.pdfDoc = null;
    this.pdfBlob = null;
    this.pdfFilename = "document.pdf";
    this.docxBlob = null;
    this.docxFilename = null;
    this.destroyed = false;
    this._renderToken = 0;

    container.innerHTML = shellHtml(this.options.title, this.options.regenerateLabel);
    this.el = container.querySelector(".doc-viewer");
    this.statusEl = this.el.querySelector("[data-dv='status']");
    this.canvasEl = this.el.querySelector("[data-dv='canvas']");
    this.pageEl = this.el.querySelector("[data-dv='page']");
    this.overlayEl = this.el.querySelector("[data-dv='overlay']");
    this.formatToolsEl = this.el.querySelector("[data-dv='format-tools']");
    this.editBtn = this.el.querySelector("[data-dv='edit-toggle']");
    this.editLabelEl = this.el.querySelector("[data-dv-label]");
    this.editing = false;
    this.lastResult = null;
    this.bodyEl = this.el.querySelector("[data-dv='body']");
    this.pageLabelEl = this.el.querySelector("[data-dv='page-label']");
    this.zoomLabelEl = this.el.querySelector("[data-dv='zoom-label']");
    this.metaEl = this.el.querySelector("[data-dv='meta']");
    this.docxBtn = this.el.querySelector("[data-dv='download-docx']");
    this.pdfBtn = this.el.querySelector("[data-dv='download-pdf']");
    this.regenerateBtn = this.el.querySelector("[data-dv='regenerate']");

    // Root-cause UX fix: "Download PDF" must never sit there enabled while
    // there is no actual PDF to download — before this fix it stayed
    // clickable even after a failed/pending generation and silently did
    // nothing when clicked (this.pdfBlob was null, so _downloadPdf() just
    // returned). Reproduced live: with PDF conversion unavailable (no
    // LibreOffice/CloudConvert), clicking "Download PDF" gave no feedback
    // at all — indistinguishable from a broken button. Disabled by default
    // here and only re-enabled once a real PDF blob exists (see refresh()).
    this.pdfBtn.disabled = true;

    if (typeof this.options.loadDocx === "function") {
      this.docxBtn.hidden = false;
    }
    // "Preview" (the regenerate button, relabeled) is always shown now —
    // it just re-runs refresh() against the current form state, which
    // works with or without an onRegenerate hook (see _regenerate()).

    this._bindEvents();
    // Optional in-preview editing layer (see js/preview-editor.js). The
    // viewer stays document-agnostic: it only hands the editor its own
    // toolbar/overlay elements and calls back on result / page render.
    this.editor = this.options.editor || null;
    if (this.editor) {
      this.el.classList.add("has-format");
      this.editor.attach(this);
      this.formatToolsEl.hidden = true; // only shown while Edit is on
    }
    this._syncEditUi();
    // Deliberately does NOT auto-call refresh() here. mount() only builds
    // the shell (shown with its neutral "Generating…" status). Every
    // caller — a first mount or a cache-hit reuse of an existing handle —
    // follows the same "mount-if-needed, then always call handle.refresh()
    // exactly once" pattern (see hotels.js's generateAndPreview() for the
    // reference implementation). An earlier version called refresh() here
    // AND left callers also calling it right after mount, which fired the
    // real backend generation endpoint twice concurrently for a single
    // click — caught via a real Playwright test that logged the network
    // requests and found two near-simultaneous POSTs (one of which failed
    // with a 500 from LibreOffice's headless conversion not tolerating a
    // second concurrent invocation) instead of one.
  }

  DocumentViewerInstance.prototype._bindEvents = function () {
    var self = this;

    this._onClick = function (e) {
      var btn = e.target.closest("[data-dv]");
      if (!btn || !self.el.contains(btn)) return;
      var action = btn.getAttribute("data-dv");
      switch (action) {
        case "zoom-in":
          self._setScale(self._nextZoom(1));
          break;
        case "zoom-out":
          self._setScale(self._nextZoom(-1));
          break;
        case "fit":
          self.fitMode = true;
          self._renderCurrentPage();
          break;
        case "prev-page":
          if (self.currentPage > 1) {
            self.currentPage -= 1;
            self._renderCurrentPage();
          }
          break;
        case "next-page":
          if (self.currentPage < self.numPages) {
            self.currentPage += 1;
            self._renderCurrentPage();
          }
          break;
        case "print":
          self._print();
          break;
        case "fullscreen":
          self._toggleFullscreen();
          break;
        case "edit-toggle":
          self.setEditing(!self.editing);
          break;
        case "regenerate":
          self._regenerate();
          break;
        case "download-pdf":
          self._downloadPdf();
          break;
        case "download-docx":
          self._downloadDocx();
          break;
      }
    };
    this.el.addEventListener("click", this._onClick);

    this._onResize = function () {
      if (self.fitMode) self._renderCurrentPage();
    };
    global.addEventListener("resize", this._onResize);
  };

  DocumentViewerInstance.prototype._nextZoom = function (dir) {
    this.fitMode = false;
    var idx = nearestZoomIndex(this.scale);
    idx = Math.max(0, Math.min(ZOOM_STEPS.length - 1, idx + dir));
    return ZOOM_STEPS[idx];
  };

  DocumentViewerInstance.prototype._setScale = function (scale) {
    this.scale = scale;
    this._renderCurrentPage();
  };

  // `level` is one of undefined/"neutral" (plain, e.g. "Generating…"),
  // "warning" (something needs attention but the rest of the workflow
  // still works — e.g. PDF unavailable while DOCX is fine), or "error"
  // (nothing usable came back at all). Kept backward-compatible with the
  // original boolean isError callers (true -> "error").
  DocumentViewerInstance.prototype._setStatus = function (message, level) {
    if (level === true) level = "error";
    if (level === false || level == null) level = "neutral";
    this.statusEl.hidden = !message;
    this.statusEl.textContent = message || "";
    this.statusEl.classList.toggle("doc-viewer__status--error", level === "error");
    this.statusEl.classList.toggle("doc-viewer__status--warning", level === "warning");
    this.canvasEl.hidden = !!message;
    this.pageEl.hidden = !!message;
  };

  // Root-cause fix: PDF conversion can genuinely be unavailable in an
  // environment (no LibreOffice installed, or CloudConvert not yet
  // configured — see pdf_conversion.py) without the DOCX generation itself
  // being broken at all; they are two entirely separate backend calls.
  // Before this fix the viewer surfaced PDF failures as a single raw,
  // technical error string with no distinction between "the whole feature
  // is down" and "only the preview/PDF path is down, DOCX is fine" — which
  // reads as alarming/broken even when most of the document workflow is
  // completely healthy. This keeps the FULL real error message (nothing is
  // hidden — project rule 9) but leads with a calm, accurate headline and
  // explicitly points at the DOCX download when it's available.
  DocumentViewerInstance.prototype._setPdfUnavailable = function (reason) {
    var hasDocx = typeof this.options.loadDocx === "function";
    var message = "PDF preview temporarily unavailable. " + reason;
    if (hasDocx) {
      message += " You can still download the Word (.docx) document below.";
    }
    // "warning", not "error": when DOCX is still available this is a
    // partial, recoverable degradation, not a broken feature — the whole
    // point of this fix is that it must not read as one.
    this._setStatus(message, hasDocx ? "warning" : "error");
  };

  DocumentViewerInstance.prototype._updatePdfButtonAvailability = function () {
    if (!this.pdfBtn) return;
    this.pdfBtn.disabled = !this.pdfBlob;
    this.pdfBtn.title = this.pdfBlob ? "" : "PDF preview is currently unavailable — see the message above.";
  };

  DocumentViewerInstance.prototype.refresh = function () {
    var self = this;
    var token = ++this._renderToken;
    this._loading = true; // keeps Edit mode on across a regeneration
    this._setStatus("Generating document…", false);
    this.docxBlob = null;
    this.pdfBlob = null;
    this._updatePdfButtonAvailability();
    this._syncEditUi();

    if (typeof this.options.loadPdf !== "function") {
      this._loading = false;
      this._setStatus("No preview available for this document.", true);
      return Promise.resolve();
    }

    return Promise.all([ensurePdfJs(), this.options.loadPdf()])
      .then(function (results) {
        if (token !== self._renderToken || self.destroyed) return;
        var pdfjsLib = results[0];
        var result = results[1];
        self.pdfBlob = result.blob;
        self.lastResult = result;
        if (self.editor) self.editor.onResult(result);
        self.pdfFilename = result.filename || self.pdfFilename;
        self._updatePdfButtonAvailability();
        self.options.editLayoutError = result.layoutError || "";
        self._loading = false;
        self._syncEditUi();
        return self.pdfBlob.arrayBuffer().then(function (buf) {
          if (token !== self._renderToken || self.destroyed) return;
          return pdfjsLib.getDocument({ data: buf }).promise.then(function (doc) {
            if (token !== self._renderToken || self.destroyed) return;
            self.pdfDoc = doc;
            self.numPages = doc.numPages;
            self.currentPage = 1;
            self._setStatus("", false);
            self._updateMeta();
            if (typeof self.options.onRefreshed === "function") {
              try { self.options.onRefreshed(result); } catch (e) { /* a caller's bookkeeping must never break the preview */ }
            }
            return self._renderCurrentPage();
          });
        });
      })
      .catch(function (err) {
        if (token !== self._renderToken || self.destroyed) return;
        self.pdfBlob = null;
        self._loading = false;
        self._updatePdfButtonAvailability();
        self._syncEditUi();
        self._setPdfUnavailable((err && err.message ? err.message : "Unknown error.").replace(/\.?$/, "."));
      });
  };

  DocumentViewerInstance.prototype._updateMeta = function () {
    var hint = "";
    if (this.editor && this.editor.hasLayout()) {
      hint = this.editing
        ? " · Click anywhere on the page's text to edit it — the whole letter is editable. Turn Edit off to see the finished page."
        : " · Press Edit to change the wording right on the page.";
    }
    var edited = this.editor && this.editor.editedCount ? this.editor.editedCount() : 0;
    var lost = this.editor && this.editor.unmatchedCount ? this.editor.unmatchedCount() : 0;
    if (lost) hint += " · " + lost + (lost === 1 ? " edit no longer matches" : " edits no longer match") + " the regenerated text and " + (lost === 1 ? "was" : "were") + " left out (Reset all clears them)";
    if (edited) hint += " · " + edited + (edited === 1 ? " value" : " values") + " edited by hand (Reset all, in Edit mode, restores the auto-generated wording)";
    this.metaEl.textContent = "Last generated " + utils.formatDate(new Date().toISOString()) + hint;
  };

  // The Edit button: available once the current PDF has an editable layout.
  DocumentViewerInstance.prototype._syncEditUi = function () {
    var btn = this.editBtn;
    var reason = this.options.editUnavailableReason || "";
    if (!this.editor && !reason) {
      btn.hidden = true;
      return;
    }
    btn.hidden = false;
    var ready = !!(this.editor && this.pdfBlob && this.editor.hasLayout());
    if (!ready && this.editing && !this._loading) this.editing = false;
    btn.disabled = !ready;
    if (ready) btn.title = this.editing ? "Stop editing and show the finished page" : "Edit the wording directly on the page";
    else if (!this.editor) btn.title = reason;
    else if (!this.pdfBlob) btn.title = "Press Preview first — editing works on the generated page.";
    else btn.title = this.options.editLayoutError || "Editing is not available for this preview right now.";
    btn.setAttribute("aria-pressed", this.editing ? "true" : "false");
    btn.classList.toggle("is-on", this.editing);
    this.editLabelEl.textContent = this.editing ? "Done editing" : "Edit";
    this.el.classList.toggle("is-editing", this.editing);
    if (this.editor) this.formatToolsEl.hidden = !this.editing;
  };

  // Turning Edit off commits the open value and, if anything was changed
  // that is not on the page yet, regenerates the real PDF so what is shown
  // is exactly what will be downloaded.
  DocumentViewerInstance.prototype.setEditing = function (on) {
    if (!this.editor || on === this.editing) return Promise.resolve();
    if (on && !(this.pdfBlob && this.editor.hasLayout())) return Promise.resolve();
    var wasEditing = this.editing;
    if (wasEditing) this.editor.commit();
    this.editing = on;
    this._syncEditUi();
    this._updateMeta();
    if (wasEditing && !on && this.editor.isDirty()) return this.refresh();
    return Promise.resolve();
  };

  DocumentViewerInstance.prototype._renderCurrentPage = function () {
    var self = this;
    if (!this.pdfDoc) return Promise.resolve();
    var token = this._renderToken;
    return this.pdfDoc.getPage(this.currentPage).then(function (page) {
      if (token !== self._renderToken || self.destroyed) return;
      var baseViewport = page.getViewport({ scale: 1 });
      var containerWidth = self.bodyEl.clientWidth - 32; /* padding allowance */
      if (self.fitMode) {
        // Fit the WHOLE page — width AND height — rather than width only.
        // A width-only fit let a full-length page (with its own real
        // header and footer) render taller than the visible box, so the
        // footer sat below the fold and needed scrolling to reach even
        // though it was always genuinely present in the generated file.
        // Fitting the whole page into view by default both surfaces the
        // footer immediately and, as a side effect, renders at a more
        // comfortable (smaller) default size than a width-only fit did —
        // "Fit"/zoom controls still let staff zoom in for a closer read.
        var heightBudget = Math.max(320, global.innerHeight * BODY_MAX_HEIGHT_VH) - 32;
        var widthScale = containerWidth / baseViewport.width;
        var heightScale = heightBudget / baseViewport.height;
        self.scale = Math.max(0.25, Math.min(3, Math.min(widthScale, heightScale)));
      }
      var viewport = page.getViewport({ scale: self.scale * (global.devicePixelRatio || 1) });
      var canvas = self.canvasEl;
      canvas.width = viewport.width;
      canvas.height = viewport.height;
      canvas.style.width = viewport.width / (global.devicePixelRatio || 1) + "px";
      canvas.style.height = viewport.height / (global.devicePixelRatio || 1) + "px";
      canvas.hidden = false;
      self.pageEl.hidden = false;
      self.overlayEl.innerHTML = "";
      var ctx = canvas.getContext("2d");
      var renderTask = page.render({ canvasContext: ctx, viewport: viewport });
      self.pageLabelEl.textContent = "Page " + self.currentPage + " of " + self.numPages;
      self.zoomLabelEl.textContent = Math.round(self.scale * 100) + "%";
      return renderTask.promise.then(function () {
        if (token !== self._renderToken || self.destroyed) return;
        if (self.editor) {
          self.editor.onPageRendered({
            viewer: self,
            overlayEl: self.overlayEl,
            canvasEl: canvas,
            scale: self.scale,
            pageNumber: self.currentPage,
            result: self.lastResult,
          });
        }
      });
    });
  };

  // If the editable preview holds edits that are not in the displayed PDF yet,
  // regenerate first — Print / Download must never hand over a document that
  // differs from what the user edited on screen.
  DocumentViewerInstance.prototype._freshen = function () {
    if (this.editor && this.editor.isDirty()) return this.refresh();
    return Promise.resolve();
  };

  // Prints the real generated PDF without depending on a browser PDF plug-in
  // or on printing a blob: URL inside an iframe (which several browsers —
  // and every file:// page — silently refuse): every page of the PDF is
  // rasterised from the already-loaded pdf.js document into an <img>, laid
  // out one per page in a hidden iframe, and that iframe's own print dialog
  // is opened. Falls back to opening the PDF in a new tab if even that fails.
  DocumentViewerInstance.prototype._print = function () {
    var self = this;
    return this._freshen().then(function () {
      if (!self.pdfBlob || !self.pdfDoc) return;
      var doc = self.pdfDoc;
      var pagePromises = [];
      var sizePt = null;
      for (var n = 1; n <= doc.numPages; n++) {
        pagePromises.push(
          doc.getPage(n).then(function (page) {
            var base = page.getViewport({ scale: 1 });
            if (!sizePt) sizePt = { w: base.width, h: base.height };
            var vp = page.getViewport({ scale: 2.2 });
            var c = document.createElement("canvas");
            c.width = vp.width;
            c.height = vp.height;
            return page.render({ canvasContext: c.getContext("2d"), viewport: vp }).promise.then(function () {
              return c.toDataURL("image/jpeg", 0.92);
            });
          })
        );
      }
      return Promise.all(pagePromises).then(function (images) {
        var iframe = document.createElement("iframe");
        iframe.setAttribute("aria-hidden", "true");
        iframe.style.cssText = "position:fixed;right:0;bottom:0;width:0;height:0;border:0;";
        var html =
          "<!doctype html><html><head><meta charset=\"utf-8\"><title>" + utils.escapeHtml(self.pdfFilename || "Document") + "</title><style>" +
          "@page{size:" + sizePt.w + "pt " + sizePt.h + "pt;margin:0}" +
          "html,body{margin:0;padding:0}" +
          "img{display:block;width:" + sizePt.w + "pt;height:" + sizePt.h + "pt;page-break-after:always;break-after:page}" +
          "img:last-child{page-break-after:auto;break-after:auto}" +
          "</style></head><body>" +
          images.map(function (src) { return '<img alt="" src="' + src + '">'; }).join("") +
          "</body></html>";
        iframe.onload = function () {
          var imgs = iframe.contentDocument ? Array.prototype.slice.call(iframe.contentDocument.images) : [];
          Promise.all(imgs.map(function (im) { return im.decode ? im.decode().catch(function () {}) : Promise.resolve(); })).then(function () {
            try {
              iframe.contentWindow.focus();
              iframe.contentWindow.print();
            } catch (e) {
              var url = URL.createObjectURL(self.pdfBlob);
              global.open(url, "_blank");
            }
            setTimeout(function () { iframe.remove(); }, 60000);
          });
        };
        document.body.appendChild(iframe);
        iframe.srcdoc = html;
      });
    });
  };

  DocumentViewerInstance.prototype._toggleFullscreen = function () {
    if (document.fullscreenElement) {
      document.exitFullscreen();
    } else if (this.el.requestFullscreen) {
      this.el.requestFullscreen();
    }
  };

  // "Preview" button handler — always refreshes against the current form
  // state (calling an onRegenerate hook first if the caller passed one;
  // every real caller's own hook is a no-op today, kept only so a future
  // document type can run real pre-refresh logic if it ever needs to).
  DocumentViewerInstance.prototype._regenerate = function () {
    var self = this;
    var btn = this.regenerateBtn;
    var original = btn.textContent;
    var hook = typeof this.options.onRegenerate === "function" ? this.options.onRegenerate : function () { return Promise.resolve(); };
    if (this.editor) this.editor.commit(); // saves the value being typed, if any
    btn.disabled = true;
    btn.textContent = "Loading…";
    return Promise.resolve(hook())
      .then(function () {
        return self.refresh();
      })
      .finally(function () {
        btn.disabled = false;
        btn.textContent = original;
      });
  };

  DocumentViewerInstance.prototype._downloadPdf = function () {
    var self = this;
    return this._freshen().then(function () {
      if (!self.pdfBlob) return;
      utils.triggerFileDownload(self.pdfBlob, self.pdfFilename);
    });
  };

  DocumentViewerInstance.prototype._downloadDocx = function () {
    var self = this;
    if (typeof this.options.loadDocx !== "function") return;
    return this._freshen().then(function () {
      return self._downloadDocxNow();
    });
  };

  DocumentViewerInstance.prototype._downloadDocxNow = function () {
    var self = this;
    if (this.docxBlob) {
      utils.triggerFileDownload(this.docxBlob, this.docxFilename);
      return;
    }
    var btn = this.docxBtn;
    var original = btn.textContent;
    btn.disabled = true;
    btn.textContent = "Preparing…";
    return this.options
      .loadDocx()
      .then(function (result) {
        self.docxBlob = result.blob;
        self.docxFilename = result.filename || "document.docx";
        utils.triggerFileDownload(self.docxBlob, self.docxFilename);
      })
      .catch(function (err) {
        global.alert("Could not prepare the DOCX download: " + (err && err.message ? err.message : "unknown error"));
      })
      .finally(function () {
        btn.disabled = false;
        btn.textContent = original;
      });
  };

  DocumentViewerInstance.prototype.destroy = function () {
    this.destroyed = true;
    if (this.editor) this.editor.commit();
    this.el.removeEventListener("click", this._onClick);
    global.removeEventListener("resize", this._onResize);
    if (this.pdfDoc && this.pdfDoc.destroy) this.pdfDoc.destroy();
    this.container.innerHTML = "";
  };

  function mount(container, options) {
    return new DocumentViewerInstance(container, options);
  }

  global.KhannaDocumentViewer = { mount: mount };
})(window);
