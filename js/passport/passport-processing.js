/* ==========================================================================
   Khanna Travels & Holidays — Passport processing (wizard step 1)
   Orchestrates: file upload -> page selection -> per-page rotation ->
   OCR call to the local backend -> review form -> save into KhannaState.

   This file owns the session state for "the passport currently being
   worked on"; passport-preview.js and passport-review-form.js are pure
   renderers it drives. Written so a later phase can reuse the same
   pipeline for accompanying travellers (Phase 5) by calling
   createController() with a different person accessor instead of
   duplicating this logic.
   ========================================================================== */
(function (global) {
  "use strict";

  var utils = global.KhannaUtils;
  var api = global.KhannaApi;
  var imageStore = global.KhannaPassportImageStore;
  var reviewForm = global.KhannaPassportReviewForm;
  var preview = global.KhannaPassportPreview;

  // Shown only on the standalone Upload Passport page (config.showContinueToDocument),
  // never inside the wizard's own step 1 — once this person's passport is saved and
  // verified, staff can jump straight into generating any of this application's
  // documents without hunting through the sidebar.
  var CONTINUE_TO_DOCUMENT_LINKS = [
    { view: "cover-letter", label: "Cover Letter" },
    { view: "hotel-blocking", label: "Hotel Blocking" },
    { view: "passport-authorization", label: "Passport Authorization Letter" },
    { view: "company-authorization", label: "Company Authorization Letter" },
    { view: "invitation-letter", label: "Invitation Letter" },
    { view: "checklist-letter", label: "Checklist Letter" },
  ];

  function continueToDocumentHtml() {
    var links = CONTINUE_TO_DOCUMENT_LINKS.map(function (d) {
      return '<a class="btn btn-secondary btn-sm" href="#/' + d.view + '">' + d.label + "</a>";
    }).join("");
    return (
      '<div class="passport-continue-to-document card" data-passport-continue-to-document hidden>' +
      "<h3>Continue to document</h3>" +
      '<div class="passport-continue-to-document__grid">' + links + "</div>" +
      "</div>"
    );
  }

  /**
   * @param {Object} config
   *   root: HTMLElement — mount point
   *   getApplication: () => Application|null
   *   getPerson: (app) => Person  (e.g. app.applicant)
   *   savePerson: (app, personPatch, activityMessage) => void
   *   registerValidator: (fn) => void  — wires this step's completeness into the wizard footer
   *   showContinueToDocument: boolean — standalone Upload Passport page only
   */
  function createController(config) {
    var session = null; // built fresh each time a person is loaded
    // The applicant's step-1 form and an open traveller's panel can both be
    // in the DOM at once, so every field id this controller generates is
    // namespaced to stay unique document-wide (see passport-review-form.js
    // skeletonHtml()) — otherwise duplicate ids break <label for> focus.
    var instanceId = config.instanceId || utils.generateId("pp");

    function freshSession() {
      return {
        file: null,
        imageRef: null,
        totalPages: 1,
        currentPageIndex: 0,
        rotationByPage: {}, // pageIndex -> degrees, independent per page
        resultByPage: {}, // pageIndex -> last OCR result for that page
        pending: {}, // pageIndex -> true while that page is being processed
        failedPages: {}, // pageIndex -> true once processing that page failed
        status: "idle", // idle | counting-pages | processing | error
        errorMessage: null,
        isPdf: false,
      };
    }

    function isPersonComplete() {
      var app = config.getApplication();
      if (!app) return false;
      var person = config.getPerson(app);
      var passport = person && person.passport;
      return !!(
        person &&
        person.lastName &&
        passport &&
        passport.current &&
        passport.current.number &&
        passport.verificationStatus &&
        passport.verificationStatus !== "Not Started"
      );
    }

    function mountSkeleton() {
      var r = config.root;
      r.innerHTML =
        '<div class="notice notice-warning" data-backend-notice hidden></div>' +
        '<div class="upload-dropzone" data-passport-dropzone tabindex="0" role="button" aria-label="Upload passport image or PDF">' +
        '<input type="file" accept="image/jpeg,image/png,image/webp,image/bmp,application/pdf" data-passport-file-input hidden />' +
        '<svg class="icon" viewBox="0 0 24 24"><path d="M12 16V4M12 4 7 9M12 4l5 5"/><path d="M4 16v3a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-3"/></svg>' +
        "<h3>Upload passport — bio-data page</h3>" +
        "<p>JPG, PNG or PDF. Drag and drop a file here, or click to browse.</p>" +
        '<button type="button" class="btn btn-secondary btn-sm" data-passport-browse>Browse file</button>' +
        '<p class="upload-dropzone__filename" data-passport-filename hidden></p>' +
        "</div>" +
        '<div class="passport-workspace" data-passport-workspace hidden>' +
        '<div class="passport-preview" data-passport-preview></div>' +
        '<div class="passport-review">' +
        '<div class="passport-review__actions">' +
        '<button type="button" class="btn btn-secondary btn-sm" data-passport-run-ocr-openrouter ' +
        'title="Testing path — calls an OpenRouter vision model instead of the Tesseract/Google Vision pipeline above. Single image only.">' +
        "Run OCR (OpenRouter — testing)</button>" +
        '<button type="button" class="btn btn-ghost btn-sm passport-review__replace-btn" data-passport-replace>Replace file</button>' +
        '<span class="passport-review__status" data-passport-status></span>' +
        "</div>" +
        reviewForm.skeletonHtml(instanceId) +
        '<div class="passport-review__save-row">' +
        '<button type="button" class="btn btn-primary" data-passport-save>Save passport details</button>' +
        "</div>" +
        "</div>" +
        "</div>" +
        (config.showContinueToDocument ? continueToDocumentHtml() : "");

      reviewForm.bindInteractions(r);
      bindEvents(r);
      checkBackend(r);
    }

    function checkBackend(r) {
      var notice = utils.qs("[data-backend-notice]", r);
      if (!notice) return;
      api.checkHealth().then(
        function () {
          notice.hidden = true;
        },
        function (err) {
          notice.hidden = false;
          notice.innerHTML =
            '<svg class="icon icon-sm" viewBox="0 0 24 24"><path d="M12 9v4M12 17h.01"/><circle cx="12" cy="12" r="9"/></svg>' +
            "<span>" + utils.escapeHtml(err.message) + "</span>";
        }
      );
    }

    function setStatus(r, text) {
      var el = utils.qs("[data-passport-status]", r);
      if (el) el.textContent = text || "";
    }

    function updateContinueToDocumentVisibility(r) {
      if (!config.showContinueToDocument) return;
      var el = utils.qs("[data-passport-continue-to-document]", r);
      if (el) el.hidden = !isPersonComplete();
    }

    function currentRotation() {
      return session.rotationByPage[session.currentPageIndex] || 0;
    }

    function renderPreview(r) {
      var previewEl = utils.qs("[data-passport-preview]", r);
      var cached = session.imageRef ? imageStore.get(session.imageRef) : null;
      var result = session.resultByPage[session.currentPageIndex];
      var imageSrc = null;
      var placeholderLabel = null;

      if (result && result.processedImageBase64) {
        imageSrc = "data:image/png;base64," + result.processedImageBase64;
      } else if (cached && cached.originalDataUrl && session.totalPages === 1) {
        imageSrc = cached.originalDataUrl;
      } else if (session.file && session.status === "error") {
        placeholderLabel = "This page could not be processed: " + (session.errorMessage || "unknown error");
      } else if (session.file) {
        placeholderLabel = "Processing passport — preview will appear automatically...";
      } else if (session.imageRef) {
        // Resuming a draft: the saved fields below are real (they came from
        // KhannaState), but the raw image itself was only ever kept in this
        // tab's memory (see passport-image-store.js) and is gone after a
        // reload — upload the file again to see or reprocess the image.
        placeholderLabel = "Original image not available in this session — upload the file again to view or reprocess it.";
      }

      preview.render(
        previewEl,
        {
          imageSrc: imageSrc,
          placeholderLabel: placeholderLabel,
          // Real bug fixed here (Phase 3): this used to be `result ? 0 :
          // currentRotation()` — once a page had been OCR'd, the rotate
          // buttons still updated rotationByPage internally but the CSS
          // transform stayed frozen at 0deg, so clicking Rotate on an
          // already-processed page produced NO visible change at all (found
          // via a real Playwright test: rotate + flip + flip-back all
          // stayed "rotate(0deg)"). Always showing currentRotation() here
          // gives immediate visual feedback either way; runOcr() below now
          // resets a page's rotationByPage to 0 the moment its processed
          // image comes back (the backend has already baked that rotation
          // into the pixels via forced_rotation — confirmed against a real
          // image: forced_rotation=90 swaps the returned image's
          // width/height), so the display never double-rotates.
          rotationDeg: currentRotation(),
          pageIndex: session.currentPageIndex,
          totalPages: session.totalPages,
          busy: !!session.pending[session.currentPageIndex],
        },
        {
          onRotate: function (delta) {
            var next = (currentRotation() + delta + 360) % 360;
            session.rotationByPage[session.currentPageIndex] = next;
            renderPreview(r);
          },
          onPrevPage: function () {
            if (session.currentPageIndex <= 0) return;
            session.currentPageIndex -= 1;
            showPage(r);
          },
          onNextPage: function () {
            if (session.currentPageIndex >= session.totalPages - 1) return;
            session.currentPageIndex += 1;
            showPage(r);
          },
        }
      );
    }

    // Moves to the page now in session.currentPageIndex. Only the preview
    // changes: the form already holds the merged result of every page read so
    // far, so paging back and forth never rewrites (or loses) what is in it. A
    // page that has not been read yet is processed now.
    function showPage(r) {
      renderPreview(r);
      var idx = session.currentPageIndex;
      if (!session.resultByPage[idx] && session.file && !session.pending[idx]) runOcr(r, idx);
    }

    // Also hides/shows the upload dropzone: once a file is selected (or a
    // saved draft with a passport already on file is resumed) the "upload
    // passport / browse file" controls have no reason to stay visible —
    // "Replace file" (bindEvents() below) is the only way back to them.
    function showWorkspace(r) {
      var dropzone = utils.qs("[data-passport-dropzone]", r);
      if (dropzone) dropzone.hidden = true;
      utils.qs("[data-passport-workspace]", r).hidden = false;
      var filenameEl = utils.qs("[data-passport-filename]", r);
      if (filenameEl && session.file) {
        filenameEl.hidden = false;
        filenameEl.textContent = "Selected: " + session.file.name;
      }
    }

    function handleFileSelected(r, file) {
      if (!file) return;
      session = freshSession();
      session.file = file;
      session.imageRef = utils.generateId("psp");
      // A different passport: nothing read from the previous file (or typed
      // for it) may stay behind in the form.
      reviewForm.resetForNewUpload(r);
      showWorkspace(r);

      var isPdf = /pdf$/i.test(file.type) || /\.pdf$/i.test(file.name);
      session.isPdf = isPdf;
      var openRouterBtn = utils.qs("[data-passport-run-ocr-openrouter]", r);
      if (openRouterBtn) {
        openRouterBtn.disabled = isPdf;
        openRouterBtn.title = isPdf
          ? "This testing path only supports a single image (JPG/PNG/WEBP), not a PDF."
          : "Testing path — calls an OpenRouter vision model instead of the Tesseract/Google Vision pipeline above. Single image only.";
      }
      if (!isPdf) {
        var reader = new FileReader();
        reader.onload = function () {
          imageStore.put(session.imageRef, { fileName: file.name, originalDataUrl: reader.result });
          renderPreview(r);
        };
        reader.readAsDataURL(file);
        // No manual "Run OCR" button anymore — extraction starts the moment
        // a file is selected (project instruction: "it should automatically
        // run it and extract data from passport"). runOcr() only needs
        // session.file, not the FileReader result above, so it can start in
        // parallel rather than waiting on it.
        runOcr(r);
      } else {
        setStatus(r, "Reading page count...");
        api.getPageCount(file).then(
          function (res) {
            session.totalPages = res.totalPages || 1;
            setStatus(r, "");
            renderPreview(r);
            runOcr(r);
          },
          function (err) {
            setStatus(r, "");
            session.errorMessage = err.message;
            renderPreview(r);
            setStatus(r, err.message);
          }
        );
      }
      renderPreview(r);
    }

    // How many pages of one upload are read automatically, one after the
    // other, right after the first: a passport PDF is the data page plus the
    // address / old-passport page, and the user should not have to open the
    // last page to get the address.
    var AUTO_PAGE_LIMIT = 4;

    function anyPending() {
      return Object.keys(session.pending).length > 0;
    }

    // Processes the next page (in order) of this upload that has no result yet.
    function processNextPage(r) {
      if (!session || !session.file || anyPending()) return;
      var limit = Math.min(session.totalPages, AUTO_PAGE_LIMIT);
      for (var i = 0; i < limit; i++) {
        if (!session.resultByPage[i] && !session.failedPages[i]) {
          runOcr(r, i);
          return;
        }
      }
      // Every page that will be read automatically has been read.
      reviewForm.finalizeMissing(r);
      setStatus(r, "");
    }

    function runOcr(r, pageIndex, opts) {
      if (!session || !session.file) return;
      opts = opts || {};
      if (pageIndex === undefined) pageIndex = session.currentPageIndex;
      var thisSession = session;
      thisSession.pending[pageIndex] = true;
      thisSession.status = "processing";
      var pageLabel = thisSession.totalPages > 1 ? " (page " + (pageIndex + 1) + " of " + thisSession.totalPages + ")" : "";
      setStatus(r, "Reading passport" + pageLabel + " — this can take a little while...");
      renderPreview(r);

      var forcedRotation = thisSession.rotationByPage[pageIndex] || null;
      api.processPassport(thisSession.file, pageIndex, forcedRotation).then(
        function (result) {
          if (session !== thisSession) return; // a different file was chosen meanwhile
          delete thisSession.pending[pageIndex];
          thisSession.status = anyPending() ? "processing" : "idle";
          thisSession.resultByPage[pageIndex] = result;
          // The rotation just requested (forcedRotation, above) is now
          // baked into result.processedImageBase64's actual pixels — reset
          // this page's tracked rotation to 0 so the preview shows the
          // already-correct image at rotate(0deg) instead of rotating it a
          // second time on top of itself.
          thisSession.rotationByPage[pageIndex] = 0;
          if (thisSession.imageRef && (result.pageKind === "bio" || pageIndex === 0)) {
            imageStore.update(thisSession.imageRef, { processedDataUrl: "data:image/png;base64," + result.processedImageBase64 });
          }
          reviewForm.applyOcrResult(r, result, thisSession.resultByPage, { pageIndex: pageIndex });
          if (pageIndex === thisSession.currentPageIndex) renderPreview(r);
          processNextPage(r);
        },
        function (err) {
          if (session !== thisSession) return;
          delete thisSession.pending[pageIndex];
          thisSession.failedPages[pageIndex] = true;
          thisSession.status = "error";
          thisSession.errorMessage = err.message;
          renderPreview(r);
          setStatus(r, err.message);
          processNextPage(r);
        }
      );
    }

    /**
     * TESTING PATH — separate from runOcr() above: calls the OpenRouter
     * vision-model endpoint instead of the production Tesseract/Google
     * Vision pipeline, but still applies its result through the SAME
     * reviewForm.applyOcrResult() so it renders identically (same field
     * contract — see openrouter_ocr.py's module docstring). Does not touch
     * session.rotationByPage or imageStore's processedDataUrl the way
     * runOcr() does, since this path returns no processed/rotated image —
     * the existing original upload preview (or "not previewed" placeholder)
     * is left exactly as-is.
     */
    function runOcrOpenRouter(r) {
      if (!session || !session.file || session.isPdf) return;
      session.status = "processing";
      setStatus(r, "Running OCR via OpenRouter (testing) — this can take a few seconds...");
      renderPreview(r);

      api.processPassportOpenRouter(session.file).then(
        function (result) {
          session.status = "idle";
          session.resultByPage[session.currentPageIndex] = result;
          setStatus(r, "");
          renderPreview(r);
          reviewForm.applyOcrResult(r, result, session.resultByPage, { force: true });
        },
        function (err) {
          session.status = "error";
          session.errorMessage = err.message;
          renderPreview(r);
          setStatus(r, err.message);
        }
      );
    }

    function savePerson(r) {
      var app = config.getApplication();
      if (!app) return;
      var values = reviewForm.readValues(r);
      // The MRZ shown with the saved passport is the one of the data page
      // that supplied the form's details, not of whichever page is on screen.
      var lastResult = session ? reviewForm.bioResultOf(session.resultByPage) : null;

      // The "Full name" field was removed from the review form itself (the
      // user only edits Given Name / Last Name now), but several other
      // controllers still key off applicant.fullName as the one field that
      // marks a person as usable — e.g. authorization.js's
      // personHasCoreFields(), which gates who shows up in Cover
      // Letter/Authorization/Invitation Letter checklists. Deriving it here
      // keeps that working without resurrecting a field the user asked to
      // remove from the UI.
      var hasName = [values.applicant.firstName, values.applicant.lastName].some(function (part) {
        return part && part.trim();
      });
      var hasNumber = values.current && values.current.number && String(values.current.number).trim();
      if (!hasName || !hasNumber) {
        var message = !hasName && !hasNumber ? "Enter the applicant's name and passport number before saving." :
          !hasName ? "Enter the applicant's name before saving." : "Enter the passport number before saving.";
        setStatus(r, message);
        if (global.KhannaToast) global.KhannaToast.show(message, { type: "error" });
        return;
      }

      var badDates = reviewForm.invalidDates(r);
      if (badDates.length) {
        var dateMessage = "Enter dates as DD-MM-YYYY (check: " + badDates.join(", ") + ").";
        setStatus(r, dateMessage);
        if (global.KhannaToast) global.KhannaToast.show(dateMessage, { type: "error" });
        return;
      }

      values.applicant.fullName = [values.applicant.firstName, values.applicant.lastName]
        .filter(function (part) {
          return part && part.trim();
        })
        .join(" ");

      var personPatch = Object.assign({}, values.applicant, {
        passport: {
          current: Object.assign({}, values.current, {
            mrzLine1: lastResult && lastResult.mrz ? lastResult.mrz.line1 : (config.getPerson(app).passport.current || {}).mrzLine1 || "",
            mrzLine2: lastResult && lastResult.mrz ? lastResult.mrz.line2 : (config.getPerson(app).passport.current || {}).mrzLine2 || "",
            mrzValid: lastResult && lastResult.mrz ? lastResult.mrz.valid : (config.getPerson(app).passport.current || {}).mrzValid || null,
          }),
          old: values.old,
          imageRef: session ? session.imageRef : config.getPerson(app).passport.imageRef,
          rotation: session ? currentRotation() : config.getPerson(app).passport.rotation,
          verificationStatus: values.verified ? "Verified" : "OCR Extracted — Please Verify",
        },
      });

      config.savePerson(app, personPatch, "Passport details saved");
      // Phase 2 of the document-centric rebuild: mirror the just-saved
      // applicant into the reusable profile pool immediately, so it's
      // available to every document page's "Use Existing Applicant" picker
      // right away — not only from this one application (spec: "Save
      // Applicant -> becomes reusable immediately across all document
      // modules"). Traveller entries get the equivalent hook via
      // config.onPersonSaved in travellers.js when that flow adopts this
      // same controller; not every config here represents an applicant.
      if (config.onPersonSaved) config.onPersonSaved(app);
      reviewForm.setBanner(r, values.verified ? "verified" : "extracted");
      if (global.KhannaRouter) global.KhannaRouter.refreshWizardFooter();
      updateContinueToDocumentVisibility(r);
      setStatus(r, "Saved.");
      if (global.KhannaToast) global.KhannaToast.show("Passport details saved", { type: "success" });
    }

    function bindEvents(r) {
      var dropzone = utils.qs("[data-passport-dropzone]", r);
      var fileInput = utils.qs("[data-passport-file-input]", r);

      utils.on(r, "click", "[data-passport-browse]", function (e) {
        e.stopPropagation();
        fileInput.click();
      });
      utils.on(dropzone, "click", function (e) {
        if (e.target === dropzone) fileInput.click();
      });
      utils.on(dropzone, "keydown", function (e) {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          fileInput.click();
        }
      });
      fileInput.addEventListener("change", function () {
        if (fileInput.files && fileInput.files[0]) handleFileSelected(r, fileInput.files[0]);
      });

      ["dragover", "dragenter"].forEach(function (evt) {
        dropzone.addEventListener(evt, function (e) {
          e.preventDefault();
          dropzone.classList.add("is-dragover");
        });
      });
      ["dragleave", "dragend"].forEach(function (evt) {
        dropzone.addEventListener(evt, function () {
          dropzone.classList.remove("is-dragover");
        });
      });
      dropzone.addEventListener("drop", function (e) {
        e.preventDefault();
        dropzone.classList.remove("is-dragover");
        var file = e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files[0];
        if (file) handleFileSelected(r, file);
      });

      utils.on(r, "click", "[data-passport-replace]", function () {
        session = freshSession();
        utils.qs("[data-passport-workspace]", r).hidden = true;
        dropzone.hidden = false;
        var filenameEl = utils.qs("[data-passport-filename]", r);
        if (filenameEl) filenameEl.hidden = true;
        fileInput.value = "";
        reviewForm.resetForNewUpload(r);
        renderPreview(r);
      });

      utils.on(r, "click", "[data-passport-run-ocr-openrouter]", function () {
        runOcrOpenRouter(r);
      });

      utils.on(r, "click", "[data-passport-save]", function () {
        savePerson(r);
      });
    }

    function render() {
      var app = config.getApplication();
      if (!app || !config.root) return;
      var r = config.root;
      if (!r.dataset.mounted) {
        r.dataset.mounted = "1";
        mountSkeleton();
      } else {
        checkBackend(r);
      }
      session = freshSession();
      var person = config.getPerson(app);
      reviewForm.loadExisting(r, person);
      var hasSavedPassport =
        person && person.passport && person.passport.verificationStatus && person.passport.verificationStatus !== "Not Started";
      if (hasSavedPassport) {
        session.imageRef = person.passport.imageRef;
        showWorkspace(r);
      } else {
        // Switching to an application with nothing saved yet (e.g. "Create
        // new application") must reset the dropzone/workspace visibility —
        // otherwise a dropzone hidden by a PREVIOUS application's uploaded
        // file would stay hidden here with no file selected and no way to
        // reach "Browse file" again.
        var dropzoneEl = utils.qs("[data-passport-dropzone]", r);
        if (dropzoneEl) dropzoneEl.hidden = false;
        var workspaceEl = utils.qs("[data-passport-workspace]", r);
        if (workspaceEl) workspaceEl.hidden = true;
        var filenameEl = utils.qs("[data-passport-filename]", r);
        if (filenameEl) filenameEl.hidden = true;
      }
      renderPreview(r);
      updateContinueToDocumentVisibility(r);
    }

    if (config.registerValidator) config.registerValidator(isPersonComplete);

    return { render: render };
  }

  global.KhannaPassportProcessing = { createController: createController };

  // ---- Bootstrap the applicant instance used by wizard step 1 ----
  function initApplicantStep() {
    var utils2 = global.KhannaUtils;
    var mountPoint = utils2.qs('[data-step="1"] [data-passport-step-root]');
    if (!mountPoint) return;

    var controller = createController({
      root: mountPoint,
      instanceId: "applicant",
      getApplication: function () {
        return global.KhannaState.getActiveApplication();
      },
      getPerson: function (app) {
        return app.applicant;
      },
      savePerson: function (app, personPatch, activityMessage) {
        global.KhannaState.updateApplication(app.id, { applicant: personPatch }, activityMessage);
      },
      onPersonSaved: function (app) {
        if (global.KhannaState.syncApplicantProfileFromApplication) {
          global.KhannaState.syncApplicantProfileFromApplication(app.id);
        }
      },
      registerValidator: function (fn) {
        if (global.KhannaRouter) global.KhannaRouter.registerStepValidator("new-application", 1, fn);
      },
    });

    document.addEventListener("khanna:navigate", function (e) {
      if (e.detail.view === "new-application") controller.render();
    });

    // Cover the case where step 1 is already the active view on first load
    // (e.g. a page refresh while deep-linked into the wizard).
    if (location.hash.indexOf("new-application") !== -1) controller.render();
  }

  // ---- Bootstrap the standalone "Upload Passport" page instance (Phase 5) ----
  // A second, independent createController() instance — its own closure, its
  // own session — mounted into index.html's [data-upload-passport-page-root]
  // (the "Upload Passport" nav link / sidebar tile / dashboard card, all
  // pointing at #/upload-passport). Reuses the exact same OCR/preview/review
  // pipeline as the wizard's step 1 above; nothing here is reimplemented.
  // Like every other standalone document page (document-workspace.js's
  // DOC_VIEWS), it reads/writes whichever application is currently active —
  // if none is active yet, document-workspace.js's own "Create new
  // application" bar (rendered above this mount point) handles that, and
  // this controller's render() picks it up via the same khanna:navigate
  // event once one exists.
  function initStandalonePage() {
    var utils2 = global.KhannaUtils;
    var mountPoint = utils2.qs("[data-upload-passport-page-root]");
    if (!mountPoint) return;

    var controller = createController({
      root: mountPoint,
      instanceId: "applicant-standalone",
      showContinueToDocument: true,
      getApplication: function () {
        return global.KhannaState.getActiveApplication();
      },
      getPerson: function (app) {
        return app.applicant;
      },
      savePerson: function (app, personPatch, activityMessage) {
        global.KhannaState.updateApplication(app.id, { applicant: personPatch }, activityMessage);
      },
      onPersonSaved: function (app) {
        if (global.KhannaState.syncApplicantProfileFromApplication) {
          global.KhannaState.syncApplicantProfileFromApplication(app.id);
        }
      },
    });

    document.addEventListener("khanna:navigate", function (e) {
      if (e.detail.view === "upload-passport") controller.render();
    });

    if (location.hash.indexOf("upload-passport") !== -1) controller.render();
  }

  function initPassportProcessing() {
    initApplicantStep();
    initStandalonePage();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initPassportProcessing);
  } else {
    initPassportProcessing();
  }
})(window);
