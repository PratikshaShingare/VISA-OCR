/* ==========================================================================
   Khanna Travels & Holidays — Passport image store (in-memory only)

   IMPORTANT / HONEST LIMITATION: raw passport images and OCR preview images
   are kept in memory only, for the lifetime of this browser tab. They are
   never written into KhannaState / localStorage.

   Why: passport images are sensitive (project rule 11 — don't expose or
   persist passport data unnecessarily), and localStorage is unencrypted,
   has a small quota, and every other Application field already lives there
   in full. KhannaState only ever stores a lightweight `imageRef` id on the
   applicant's passport record — the actual image bytes live here, and are
   gone on a page reload.

   That is a deliberate trade-off, not a bug: if the page is reloaded mid
   review, the already-saved passport fields are untouched (they're in
   KhannaState like everything else); only the raw image preview needs to
   be re-opened by the staff member (still on their own machine) if they
   want to re-run OCR or look at it again.
   ========================================================================== */
(function (global) {
  "use strict";

  var store = {}; // imageRef -> { fileName, originalDataUrl, processedDataUrl }

  function put(imageRef, data) {
    store[imageRef] = data;
  }

  function get(imageRef) {
    return store[imageRef] || null;
  }

  function update(imageRef, patch) {
    store[imageRef] = Object.assign({}, store[imageRef] || {}, patch);
    return store[imageRef];
  }

  function remove(imageRef) {
    delete store[imageRef];
  }

  global.KhannaPassportImageStore = { put: put, get: get, update: update, remove: remove };
})(window);
