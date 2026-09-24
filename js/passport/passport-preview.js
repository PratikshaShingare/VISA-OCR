/* ==========================================================================
   Khanna Travels & Holidays — Passport preview widget
   Pure rendering + interaction for the image-preview panel used in the
   passport step: the page image itself, rotate controls, and a single
   "Flip Page" control for multi-page uploads (Phase 11/12 of the master
   prompt: rotation is tracked independently per page; one flip control
   replaces separate prev/next buttons; rotate controls are icon-only with
   aria-labels and no visible degree text — Phase 13).

   This module owns no session state of its own — it just renders whatever
   state object it is given and reports user actions back through callbacks.
   passport-processing.js is the single source of truth for that state.
   ========================================================================== */
(function (global) {
  "use strict";

  var utils = global.KhannaUtils;

  var ROTATE_ICON =
    '<svg class="icon" viewBox="0 0 24 24"><path d="M21 12a9 9 0 1 1-3.2-6.9"/><path d="M21 3v6h-6"/></svg>';
  var ROTATE_LEFT_ICON =
    '<svg class="icon" viewBox="0 0 24 24" style="transform:scaleX(-1);"><path d="M21 12a9 9 0 1 1-3.2-6.9"/><path d="M21 3v6h-6"/></svg>';
  var FLIP_ICON =
    '<svg class="icon" viewBox="0 0 24 24"><path d="M7 7h10M7 7l3-3M7 7l3 3M17 17H7M17 17l-3 3M17 17l-3-3"/></svg>';

  /**
   * @param {HTMLElement} container element to render the preview into
   * @param {Object} state
   *   imageSrc: string|null           — data URL or base64-PNG-with-prefix to show
   *   placeholderLabel: string|null   — shown instead of an image (e.g. "PDF — page not previewed until processed")
   *   rotationDeg: number             — current rotation for this page (0/90/180/270)
   *   pageIndex: number
   *   totalPages: number
   *   busy: boolean                   — OCR in progress, disable controls
   * @param {Object} callbacks
   *   onRotate(deltaDeg)
   *   onFlipPage()
   */
  function render(container, state, callbacks) {
    if (!container) return;
    var hasImage = !!state.imageSrc;
    var multiPage = state.totalPages > 1;

    // The rotation transform is applied to the IMAGE only, never to
    // .passport-preview__stage itself: rotating the whole (clipped) stage
    // box makes its painted/hit-testable shape bleed outside its own layout
    // footprint at 90/270deg, which can visually cover the controls sitting
    // right below it and swallow their clicks even though nothing in normal
    // document flow overlaps. Keeping the stage fixed and only rotating the
    // image inside it (still clipped by the stage's own overflow:hidden)
    // avoids that entirely.
    container.innerHTML =
      '<div class="passport-preview__stage">' +
      (hasImage
        ? '<img class="passport-preview__img" style="transform:rotate(' + (state.rotationDeg || 0) + 'deg);" src="' + state.imageSrc + '" alt="Passport page preview" />'
        : '<div class="passport-preview__placeholder">' +
          '<svg class="icon" viewBox="0 0 24 24"><path d="M4 4h16v16H4z"/><path d="M4 15l4-4 4 4 4-6 4 6"/></svg>' +
          "<span>" + utils.escapeHtml(state.placeholderLabel || "No page selected") + "</span>" +
          "</div>") +
      "</div>" +
      '<div class="passport-preview__controls">' +
      '<div class="passport-preview__rotate-group">' +
      '<button type="button" class="btn-icon" data-preview-rotate="-90" aria-label="Rotate left 90 degrees"' + (state.busy ? " disabled" : "") + ">" + ROTATE_LEFT_ICON + "</button>" +
      '<button type="button" class="btn-icon" data-preview-rotate="90" aria-label="Rotate right 90 degrees"' + (state.busy ? " disabled" : "") + ">" + ROTATE_ICON + "</button>" +
      "</div>" +
      (multiPage
        ? '<div class="passport-preview__page-control">' +
          '<button type="button" class="btn btn-ghost btn-sm" data-preview-flip-page aria-label="Flip to next page"' + (state.busy ? " disabled" : "") + ">" +
          FLIP_ICON +
          "<span>Flip page</span>" +
          "</button>" +
          '<span class="passport-preview__page-indicator">Page ' + (state.pageIndex + 1) + " of " + state.totalPages + "</span>" +
          "</div>"
        : "") +
      "</div>";

    utils.on(container, "click", "[data-preview-rotate]", function (e, target) {
      if (callbacks && callbacks.onRotate) {
        callbacks.onRotate(parseInt(target.getAttribute("data-preview-rotate"), 10));
      }
    });
    utils.on(container, "click", "[data-preview-flip-page]", function () {
      if (callbacks && callbacks.onFlipPage) callbacks.onFlipPage();
    });
  }

  global.KhannaPassportPreview = { render: render };
})(window);
