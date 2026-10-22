/* ==========================================================================
   Khanna Travels & Holidays — Shared "Word-like" body-wording editor
   Frontend rework, Phase 4. ONE reusable component every document-
   generating module (Cover Letter, Hotel Blocking, Company/Passport
   Authorization, Invitation Letter, Checklist Letter) mounts to let a
   staff member fine-tune a document's own free-composed body wording in
   a real rich-text editor (Quill), WITHOUT ever touching that document's
   header, footer, margins, fonts, logo, or any other fixed paragraph —
   those always come from the real reference template exactly as before
   (project rule 5). Extracted out of js/cover-letter.js, which was the
   first (proof-of-concept) caller, so the 2nd-5th document types reuse
   this instead of a copy-pasted ~200-line block each (project rule 15).

   Architecture (unchanged from the Europe Cover Letter POC that proved
   it out — see claude/frontend-rework-phase4-word-like-body-editor-
   europe-poc.md in the project for the full write-up):
     - The backend composes a document's free-composed paragraph(s) with
       the SAME function used by both the real generator and a small
       "compose body text" JSON endpoint (never two copies of the
       wording).
     - This module seeds Quill from that endpoint the moment its own
       readiness condition is met, lets the staff member edit freely, and
       hands back the edited HTML on demand — the caller's own
       "Generate & Preview"/download flow includes that HTML in its
       existing request payload; the real backend then replaces ONLY
       that document's own editable paragraph range
       (docx_utils.replace_paragraph_range_with_html) and regenerates
       through the exact same unmodified template-loading code path.

   Usage (see js/cover-letter.js for the original real caller):

     var handle = KhannaBodyEditor.attach(mountEl, {
       description: "This edits ONLY ...",             // hint shown above the editor
       isReady: function () { return boolean; },        // same condition the backend itself enforces
       notReadyMessage: "Complete ... above ...",       // shown instead of the editor until isReady()
       seed: function () { return Promise<{html}>; },   // the real compose-body API call
     });
     handle.refresh();          // call after every relevant state change (mirrors refreshGenerateBar())
     handle.getEditedHtml();    // string once seeded, else null — fold into the download payload
                                 // when non-null; a null return means "don't send editedBodyHtml at
                                 // all", never an empty string that could blank the real wording.

   mountEl is a plain container the CALLER creates fresh each time its own
   panel rebuilds (e.g. inside a region/step's own re-rendered markup, at
   the exact visual position the editor should appear — see each caller's
   own placement). attach() takes ownership of mountEl's contents from
   that point on; calling attach() again on a NEW mountEl (after the
   caller's own panel rebuilds) is the normal, expected way this gets used
   — there is no cross-render persistence to manage here, matching how
   this file's callers already treat "an explicit action that rebuilds
   this panel" as a natural reset point.

   Quill is vendored locally at assets/vendor/quill/{quill.js,
   quill.snow.css} rather than a live CDN link — see this repo's own
   pdf.js precedent (js/document-viewer.js) for why — and lazy-loaded
   once here, shared by every document type that uses this module.
   ========================================================================== */
(function (global) {
  "use strict";

  var utils = global.KhannaUtils;

  var QUILL_READY = null;
  function ensureQuill() {
    if (QUILL_READY) return QUILL_READY;
    if (global.Quill) {
      QUILL_READY = Promise.resolve(global.Quill);
      return QUILL_READY;
    }
    QUILL_READY = new Promise(function (resolve, reject) {
      var script = document.createElement("script");
      script.src = "assets/vendor/quill/quill.js";
      script.onload = function () {
        if (!global.Quill) {
          reject(new Error("Quill loaded but window.Quill is missing"));
          return;
        }
        resolve(global.Quill);
      };
      script.onerror = function () {
        reject(new Error("Could not load the letter body editor library (assets/vendor/quill/quill.js)."));
      };
      document.head.appendChild(script);
    });
    return QUILL_READY;
  }

  function shellHtml(opts) {
    return (
      '<div class="card body-editor">' +
      "<h4>" + utils.escapeHtml(opts.title || "Wording (editable)") + "</h4>" +
      '<p class="field-hint">' + opts.description + "</p>" +
      '<div data-body-editor-status class="field-hint"></div>' +
      '<div class="body-editor__toolbar-extra">' +
      '<button type="button" class="btn btn-ghost btn-sm" data-body-editor-action="undo">Undo</button>' +
      '<button type="button" class="btn btn-ghost btn-sm" data-body-editor-action="redo">Redo</button>' +
      '<button type="button" class="btn btn-secondary btn-sm" data-body-editor-action="reset">Reset to auto-generated text</button>' +
      "</div>" +
      '<div class="body-editor__page"><div data-body-editor-quill></div></div>' +
      "</div>"
    );
  }

  function placeholderHtml(opts) {
    return (
      '<div class="card body-editor">' +
      "<h4>" + utils.escapeHtml(opts.title || "Wording (editable)") + "</h4>" +
      '<p class="field-hint">' + utils.escapeHtml(opts.notReadyMessage || "Complete the fields above to edit this document's wording here.") + "</p>" +
      "</div>"
    );
  }

  function setStatus(mountEl, message, isError) {
    var box = utils.qs("[data-body-editor-status]", mountEl);
    if (!box) return;
    box.textContent = message || "";
    box.classList.toggle("body-editor__status--error", !!isError);
  }

  /**
   * @param {HTMLElement} mountEl a fresh, empty container this call takes
   *   ownership of.
   * @param {Object} opts
   *   {string} title - defaults to "Wording (editable)"
   *   {string} description - HTML-safe hint shown above the editor
   *   {function(): boolean} isReady
   *   {string} notReadyMessage
   *   {function(): Promise<{html: string}>} seed
   *   {Array} [toolbar] - optional Quill toolbar module config override
   * @returns {{refresh: function(), getEditedHtml: function(): (string|null)}}
   */
  function attach(mountEl, opts) {
    var state = { quill: null, seeded: false, seeding: false, failed: false, mode: null };

    function seed() {
      if (!state.quill || state.seeding) return;
      state.seeding = true;
      state.failed = false;
      setStatus(mountEl, "Loading the current wording…");
      opts
        .seed()
        .then(function (result) {
          // Single-argument form replaces the editor's ENTIRE contents.
          state.quill.clipboard.dangerouslyPasteHTML((result && result.html) || "<p></p>");
          // Frontend rework, Phase 4 bugfix: Quill's own clipboard paste
          // silently steals real keyboard focus (confirmed via a live
          // document.activeElement check — nothing in THIS codebase asks
          // for it) — left alone, whichever editor seeds LAST ends up
          // focused, and the very next click anywhere else on the page
          // fires a native 'blur' on it first. If that blur's onChange
          // persists an edit and the resulting KhannaState notify()
          // rebuilds a DOM node under the pointer mid-click (e.g. a
          // "Generate & Preview" button that re-renders on every state
          // change), the click can be lost entirely — reproduced live
          // with the Authorization Letters' own Generate button.
          // Explicitly releasing focus after every programmatic seed
          // (never after a real user edit — seed() is only ever called
          // by refresh()/Reset, not by typing) closes that hole at its
          // one shared source rather than special-casing every caller.
          state.quill.blur();
          state.seeded = true;
          state.seeding = false;
          setStatus(mountEl, "");
        })
        .catch(function (err) {
          state.seeding = false;
          state.failed = true;
          setStatus(mountEl, (err && err.message) || "Could not load the current wording.", true);
        });
    }

    function mountEditor() {
      mountEl.innerHTML = shellHtml(opts);
      state.mode = "editor";
      var quillTarget = utils.qs("[data-body-editor-quill]", mountEl);
      setStatus(mountEl, "Loading the editor…");

      utils.on(mountEl, "click", "[data-body-editor-action='undo']", function () {
        if (state.quill) state.quill.history.undo();
      });
      utils.on(mountEl, "click", "[data-body-editor-action='redo']", function () {
        if (state.quill) state.quill.history.redo();
      });
      utils.on(mountEl, "click", "[data-body-editor-action='reset']", function () {
        state.seeded = false;
        seed();
      });

      ensureQuill()
        .then(function (Quill) {
          state.quill = new Quill(quillTarget, {
            theme: "snow",
            modules: {
              toolbar: opts.toolbar || [["bold", "italic", "underline"], [{ align: [] }], [{ list: "ordered" }, { list: "bullet" }], ["clean"]],
            },
          });
          // Chained directly here rather than left for a later refresh()
          // call — without this the editor mounts but sits blank until
          // something unrelated happens to call refresh() again.
          seed();
        })
        .catch(function (err) {
          state.failed = true;
          setStatus(mountEl, (err && err.message) || "Could not load the letter body editor.", true);
        });
    }

    function mountPlaceholder() {
      mountEl.innerHTML = placeholderHtml(opts);
      state.mode = "placeholder";
      state.quill = null;
      state.seeded = false;
      state.seeding = false;
      state.failed = false;
    }

    function refresh() {
      var ready = !!opts.isReady();
      if (!ready) {
        if (state.mode !== "placeholder") mountPlaceholder();
        return;
      }
      if (state.mode !== "editor") {
        mountEditor();
        return; // mountEditor()'s own ensureQuill().then() chains the first seed itself.
      }
      if (state.quill && !state.seeded && !state.seeding && !state.failed) {
        seed();
      }
    }

    function getEditedHtml() {
      if (!state.seeded || !state.quill) return null;
      return state.quill.root.innerHTML;
    }

    return { refresh: refresh, getEditedHtml: getEditedHtml };
  }

  /* -----------------------------------------------------------------------
   * attachCompact() — the SAME editor primitive (Quill, ensureQuill()'s one
   * shared lazy-load, the seed/getEditedHtml contract, real HTML in and
   * out), presented as a small single-field row instead of a full
   * title+description+toolbar-extras "card". Written for Phase 4's
   * extension beyond the Europe Cover Letter's one long free-composed
   * passage: a document like Hotel Blocking has MANY short independently-
   * editable generated values (hotel name, a date, a guest-name list, a
   * confirmation sentence, ...) — mounting attach()'s full card once per
   * value would bury a hotel's whole booking-details table under a dozen
   * oversized cards. attachCompact() keeps the label directly beside the
   * value (like the row it's replacing/augmenting in the underlying real
   * document table) and drops the description/Undo/Redo button row down to
   * one small reset control, while still being genuine rich text (bold/
   * italic/underline) and still round-tripping through
   * docx_utils.replace_paragraph_range_with_html on the backend exactly
   * like attach()'s own fields do.
   *
   * opts = {label, isReady, notReadyMessage, seed, toolbar?} — same
   * contract as attach() minus {title, description}; returns the same
   * {refresh, getEditedHtml} handle shape, so callers can treat a compact
   * field and a full card interchangeably when gathering edited fields.
   * ------------------------------------------------------------------- */

  function compactShellHtml(opts) {
    return (
      '<div class="body-editor-compact">' +
      '<div class="body-editor-compact__row">' +
      '<span class="body-editor-compact__label">' + utils.escapeHtml(opts.label || "") + "</span>" +
      '<button type="button" class="body-editor-compact__reset" data-body-editor-action="reset" ' +
      'title="Reset to auto-generated text" aria-label="Reset ' + utils.escapeHtml(opts.label || "this field") + ' to auto-generated text">' +
      "↺</button>" +
      "</div>" +
      '<div data-body-editor-status class="body-editor-compact__status"></div>' +
      '<div class="body-editor-compact__quill"><div data-body-editor-quill></div></div>' +
      "</div>"
    );
  }

  function compactPlaceholderHtml(opts) {
    return (
      '<div class="body-editor-compact body-editor-compact--placeholder">' +
      '<span class="body-editor-compact__label">' + utils.escapeHtml(opts.label || "") + "</span>" +
      '<span class="field-hint">' + utils.escapeHtml(opts.notReadyMessage || "Not available yet.") + "</span>" +
      "</div>"
    );
  }

  function attachCompact(mountEl, opts) {
    var state = { quill: null, seeded: false, seeding: false, failed: false, mode: null };

    function seed() {
      if (!state.quill || state.seeding) return;
      state.seeding = true;
      state.failed = false;
      opts
        .seed()
        .then(function (result) {
          state.quill.clipboard.dangerouslyPasteHTML((result && result.html) || "<p></p>");
          // Frontend rework, Phase 4 bugfix — see attach()'s own seed()
          // for the full explanation: Quill's clipboard paste silently
          // steals real keyboard focus, and a stray focused editor's
          // 'blur' firing mid-click on an unrelated button elsewhere on
          // the page (e.g. Authorization Letters' Generate & Preview,
          // which sits directly below these compact fields with no
          // intervening "close panel" step) can lose that click
          // entirely if the blur's own onChange triggers a re-render of
          // the very button being clicked. Releasing focus after every
          // programmatic seed (never after a real user edit) closes
          // this at its one shared source.
          state.quill.blur();
          state.seeded = true;
          state.seeding = false;
          setStatus(mountEl, "");
        })
        .catch(function (err) {
          state.seeding = false;
          state.failed = true;
          setStatus(mountEl, (err && err.message) || "Could not load this field.", true);
        });
    }

    function mountEditor() {
      mountEl.innerHTML = compactShellHtml(opts);
      state.mode = "editor";
      var quillTarget = utils.qs("[data-body-editor-quill]", mountEl);

      utils.on(mountEl, "click", "[data-body-editor-action='reset']", function () {
        state.seeded = false;
        // "Reset" clears any persisted override FIRST (a null value means
        // "no override — always show whatever auto-generates", never
        // "override = whatever text happened to be composed today"), then
        // re-seeds from the fresh composed value for display.
        if (opts.onChange) opts.onChange(null);
        seed();
      });

      ensureQuill()
        .then(function (Quill) {
          state.quill = new Quill(quillTarget, {
            theme: "snow",
            modules: {
              toolbar: opts.toolbar || [["bold", "italic", "underline"]],
            },
          });
          // Real edits (not this module's own programmatic seed() calls,
          // which dangerouslyPasteHTML marks as source 'silent') are
          // persisted on blur — the same "commit when the field loses
          // focus" moment this codebase's plain <input> fields already use
          // (a "change" event), not on every keystroke.
          state.quill.root.addEventListener("blur", function () {
            if (opts.onChange && state.seeded) opts.onChange(state.quill.root.innerHTML);
          });
          seed(); // chained here for the same reason attach()'s mountEditor() does.
        })
        .catch(function (err) {
          state.failed = true;
          setStatus(mountEl, (err && err.message) || "Could not load the editor.", true);
        });
    }

    function mountPlaceholder() {
      mountEl.innerHTML = compactPlaceholderHtml(opts);
      state.mode = "placeholder";
      state.quill = null;
      state.seeded = false;
      state.seeding = false;
      state.failed = false;
    }

    function refresh() {
      var ready = !!opts.isReady();
      if (!ready) {
        if (state.mode !== "placeholder") mountPlaceholder();
        return;
      }
      if (state.mode !== "editor") {
        mountEditor();
        return;
      }
      if (state.quill && !state.seeded && !state.seeding && !state.failed) {
        seed();
      }
    }

    function getEditedHtml() {
      if (!state.seeded || !state.quill) return null;
      return state.quill.root.innerHTML;
    }

    return { refresh: refresh, getEditedHtml: getEditedHtml };
  }

  global.KhannaBodyEditor = { attach: attach, attachCompact: attachCompact };
})(window);
