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

  function shellHtml(title) {
    return (
      '<div class="doc-viewer">' +
      '<div class="doc-viewer__toolbar">' +
      '<div class="doc-viewer__title" data-dv-title>' +
      utils.escapeHtml(title || "Document preview") +
      "</div>" +
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
      '<canvas class="doc-viewer__canvas" data-dv="canvas" hidden></canvas>' +
      "</div>" +
      '<div class="doc-viewer__actions">' +
      '<div class="doc-viewer__actions-left" data-dv="meta"></div>' +
      '<div class="doc-viewer__actions-right">' +
      '<button type="button" class="btn btn-ghost btn-sm" data-dv="edit">Edit details</button>' +
      '<button type="button" class="btn btn-secondary btn-sm" data-dv="regenerate" hidden>Regenerate</button>' +
      '<button type="button" class="btn btn-secondary btn-sm" data-dv="download-docx" hidden>Download DOCX</button>' +
      '<button type="button" class="btn btn-primary btn-sm" data-dv="download-pdf">Download PDF</button>' +
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

    container.innerHTML = shellHtml(this.options.title);
    this.el = container.querySelector(".doc-viewer");
    this.statusEl = this.el.querySelector("[data-dv='status']");
    this.canvasEl = this.el.querySelector("[data-dv='canvas']");
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
    if (typeof this.options.onRegenerate === "function") {
      this.regenerateBtn.hidden = false;
    }

    this._bindEvents();
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
        case "edit":
          if (typeof self.options.onEdit === "function") self.options.onEdit();
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
    this._setStatus("Generating document…", false);
    this.docxBlob = null;
    this.pdfBlob = null;
    this._updatePdfButtonAvailability();

    if (typeof this.options.loadPdf !== "function") {
      this._setStatus("No preview available for this document.", true);
      return Promise.resolve();
    }

    return Promise.all([ensurePdfJs(), this.options.loadPdf()])
      .then(function (results) {
        if (token !== self._renderToken || self.destroyed) return;
        var pdfjsLib = results[0];
        var result = results[1];
        self.pdfBlob = result.blob;
        self.pdfFilename = result.filename || self.pdfFilename;
        self._updatePdfButtonAvailability();
        return self.pdfBlob.arrayBuffer().then(function (buf) {
          if (token !== self._renderToken || self.destroyed) return;
          return pdfjsLib.getDocument({ data: buf }).promise.then(function (doc) {
            if (token !== self._renderToken || self.destroyed) return;
            self.pdfDoc = doc;
            self.numPages = doc.numPages;
            self.currentPage = 1;
            self._setStatus("", false);
            self._updateMeta();
            return self._renderCurrentPage();
          });
        });
      })
      .catch(function (err) {
        if (token !== self._renderToken || self.destroyed) return;
        self.pdfBlob = null;
        self._updatePdfButtonAvailability();
        self._setPdfUnavailable((err && err.message ? err.message : "Unknown error.").replace(/\.?$/, "."));
      });
  };

  DocumentViewerInstance.prototype._updateMeta = function () {
    this.metaEl.textContent = "Last generated " + utils.formatDate(new Date().toISOString());
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
        self.scale = Math.max(0.25, Math.min(3, containerWidth / baseViewport.width));
      }
      var viewport = page.getViewport({ scale: self.scale * (global.devicePixelRatio || 1) });
      var canvas = self.canvasEl;
      canvas.width = viewport.width;
      canvas.height = viewport.height;
      canvas.style.width = viewport.width / (global.devicePixelRatio || 1) + "px";
      canvas.style.height = viewport.height / (global.devicePixelRatio || 1) + "px";
      canvas.hidden = false;
      var ctx = canvas.getContext("2d");
      var renderTask = page.render({ canvasContext: ctx, viewport: viewport });
      self.pageLabelEl.textContent = "Page " + self.currentPage + " of " + self.numPages;
      self.zoomLabelEl.textContent = Math.round(self.scale * 100) + "%";
      return renderTask.promise;
    });
  };

  DocumentViewerInstance.prototype._print = function () {
    if (!this.pdfBlob) return;
    var url = URL.createObjectURL(this.pdfBlob);
    var iframe = document.createElement("iframe");
    iframe.style.position = "fixed";
    iframe.style.right = "0";
    iframe.style.bottom = "0";
    iframe.style.width = "0";
    iframe.style.height = "0";
    iframe.style.border = "0";
    iframe.src = url;
    document.body.appendChild(iframe);
    iframe.onload = function () {
      try {
        iframe.contentWindow.focus();
        iframe.contentWindow.print();
      } catch (e) {
        /* Some browsers block programmatic print from a cross-context
           iframe; fall back to opening the PDF in a new tab so the user
           can print from there instead of failing silently. */
        global.open(url, "_blank");
      }
      setTimeout(function () {
        iframe.remove();
        URL.revokeObjectURL(url);
      }, 60000);
    };
  };

  DocumentViewerInstance.prototype._toggleFullscreen = function () {
    if (document.fullscreenElement) {
      document.exitFullscreen();
    } else if (this.el.requestFullscreen) {
      this.el.requestFullscreen();
    }
  };

  DocumentViewerInstance.prototype._regenerate = function () {
    var self = this;
    if (typeof this.options.onRegenerate !== "function") return Promise.resolve();
    var btn = this.regenerateBtn;
    var original = btn.textContent;
    btn.disabled = true;
    btn.textContent = "Regenerating…";
    return Promise.resolve(this.options.onRegenerate())
      .then(function () {
        return self.refresh();
      })
      .finally(function () {
        btn.disabled = false;
        btn.textContent = original;
      });
  };

  DocumentViewerInstance.prototype._downloadPdf = function () {
    if (!this.pdfBlob) return;
    utils.triggerFileDownload(this.pdfBlob, this.pdfFilename);
  };

  DocumentViewerInstance.prototype._downloadDocx = function () {
    var self = this;
    if (typeof this.options.loadDocx !== "function") return;
    if (this.docxBlob) {
      utils.triggerFileDownload(this.docxBlob, this.docxFilename);
      return;
    }
    var btn = this.docxBtn;
    var original = btn.textContent;
    btn.disabled = true;
    btn.textContent = "Preparing…";
    this.options
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
