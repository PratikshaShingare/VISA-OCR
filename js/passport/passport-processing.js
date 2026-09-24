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

  /**
   * @param {Object} config
   *   root: HTMLElement — mount point
   *   getApplication: () => Application|null
   *   getPerson: (app) => Person  (e.g. app.applicant)
   *   savePerson: (app, personPatch, activityMessage) => void
   *   registerValidator: (fn) => void  — wires this step's completeness into the wizard footer
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
        status: "idle", // idle | counting-pages | processing | error
        errorMessage: null,
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
        '<button type="button" class="btn btn-primary btn-sm" data-passport-run-ocr>Run OCR</button>' +
        '<button type="button" class="btn btn-ghost btn-sm" data-passport-replace>Replace file</button>' +
        '<span class="passport-review__status" data-passport-status></span>' +
        "</div>" +
        reviewForm.skeletonHtml(instanceId) +
        '<div class="passport-review__save-row">' +
        '<button type="button" class="btn btn-primary" data-passport-save>Save passport details</button>' +
        "</div>" +
        "</div>" +
        "</div>";

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
      } else if (session.file) {
        placeholderLabel = "Page not previewed until OCR runs — click Run OCR below.";
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
          rotationDeg: result ? 0 : currentRotation(), // once processed, the backend already returns an upright image
          pageIndex: session.currentPageIndex,
          totalPages: session.totalPages,
          busy: session.status === "processing",
        },
        {
          onRotate: function (delta) {
            var next = (currentRotation() + delta + 360) % 360;
            session.rotationByPage[session.currentPageIndex] = next;
            renderPreview(r);
          },
          onFlipPage: function () {
            session.currentPageIndex = (session.currentPageIndex + 1) % session.totalPages;
            renderPreview(r);
            var cachedResult = session.resultByPage[session.currentPageIndex];
            if (cachedResult) reviewForm.applyOcrResult(r, cachedResult);
          },
        }
      );
    }

    function showWorkspace(r) {
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
      showWorkspace(r);

      var isPdf = /pdf$/i.test(file.type) || /\.pdf$/i.test(file.name);
      if (!isPdf) {
        var reader = new FileReader();
        reader.onload = function () {
          imageStore.put(session.imageRef, { fileName: file.name, originalDataUrl: reader.result });
          renderPreview(r);
        };
        reader.readAsDataURL(file);
      } else {
        setStatus(r, "Reading page count...");
        api.getPageCount(file).then(
          function (res) {
            session.totalPages = res.totalPages || 1;
            setStatus(r, "");
            renderPreview(r);
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

    function runOcr(r) {
      if (!session || !session.file) return;
      session.status = "processing";
      setStatus(r, "Running OCR — this can take a few seconds...");
      renderPreview(r);

      var forcedRotation = session.rotationByPage[session.currentPageIndex] || null;
      api.processPassport(session.file, session.currentPageIndex, forcedRotation).then(
        function (result) {
          session.status = "idle";
          session.resultByPage[session.currentPageIndex] = result;
          if (session.imageRef) {
            imageStore.update(session.imageRef, { processedDataUrl: "data:image/png;base64," + result.processedImageBase64 });
          }
          setStatus(r, "");
          renderPreview(r);
          reviewForm.applyOcrResult(r, result);
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
      var lastResult = session ? session.resultByPage[session.currentPageIndex] : null;

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
      reviewForm.setBanner(r, values.verified ? "verified" : "extracted");
      if (global.KhannaRouter) global.KhannaRouter.refreshWizardFooter();
      setStatus(r, "Saved.");
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
        var filenameEl = utils.qs("[data-passport-filename]", r);
        if (filenameEl) filenameEl.hidden = true;
        fileInput.value = "";
      });

      utils.on(r, "click", "[data-passport-run-ocr]", function () {
        runOcr(r);
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
      }
      renderPreview(r);
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

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initApplicantStep);
  } else {
    initApplicantStep();
  }
})(window);
