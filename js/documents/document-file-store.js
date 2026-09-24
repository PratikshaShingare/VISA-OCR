/* ==========================================================================
   Khanna Travels & Holidays — Document file store (in-memory only)
   Same honest trade-off as js/passport/passport-image-store.js: uploaded
   documents (bank statements, ID copies, tickets, etc.) are, if anything,
   MORE sensitive than a passport image, so they are kept in memory only,
   for this tab's lifetime, and never written into KhannaState/localStorage.
   KhannaState only ever stores a lightweight `fileRef` id and metadata
   (name, type) — never the file bytes.

   Trade-off, stated plainly: reloading the page loses the ability to
   preview/download an already-uploaded file in this session (the SAVED
   status/verification data is untouched, since that lives in KhannaState).
   The document row says so and lets staff re-upload if they need to look
   at it again.
   ========================================================================== */
(function (global) {
  "use strict";

  var store = {}; // fileRef -> { file: File, objectUrl: string }

  function put(fileRef, file) {
    var existing = store[fileRef];
    if (existing && existing.objectUrl) URL.revokeObjectURL(existing.objectUrl);
    store[fileRef] = { file: file, objectUrl: URL.createObjectURL(file) };
  }

  function get(fileRef) {
    return store[fileRef] || null;
  }

  function remove(fileRef) {
    var existing = store[fileRef];
    if (existing && existing.objectUrl) URL.revokeObjectURL(existing.objectUrl);
    delete store[fileRef];
  }

  global.KhannaDocumentFileStore = { put: put, get: get, remove: remove };
})(window);
