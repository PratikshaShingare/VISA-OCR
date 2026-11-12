/* ==========================================================================
   Khanna Travels & Holidays — Passport image store

   Two layers:
     1. In memory (this tab): the uploaded file and the processed preview, as
        before — fast, used while a passport is being read.
     2. On this computer (the browser's IndexedDB): ONLY the processed
        bio-data page — the cropped, straightened image the backend returns
        after OCR — so a saved passport can show its picture again when it is
        reopened (Upload Passport, Recent Passports), instead of "Original
        image not available".

   What is NOT kept: the original upload (other pages, background, other
   documents in the same photo). The processed page is stored as a JPEG of
   at most 1600 px, inside this browser on this computer only — it is never
   sent anywhere and is not in localStorage (project rule 11). At most
   MAX_SAVED images are kept; the oldest are removed first. Removing a
   passport's image (remove()) deletes it from the computer too.

   If IndexedDB is unavailable (private window, blocked storage) everything
   still works as before, in memory only.
   ========================================================================== */
(function (global) {
  "use strict";

  var DB_NAME = "khanna-passport-images";
  var STORE = "processed";
  var MAX_SAVED = 300;
  var MAX_SIDE = 1600;

  var store = {}; // imageRef -> { fileName, originalDataUrl, processedDataUrl }
  var dbPromise = null;

  function openDb() {
    if (dbPromise) return dbPromise;
    dbPromise = new Promise(function (resolve) {
      try {
        if (!global.indexedDB) return resolve(null);
        var req = global.indexedDB.open(DB_NAME, 1);
        req.onupgradeneeded = function () {
          var db = req.result;
          if (!db.objectStoreNames.contains(STORE)) db.createObjectStore(STORE, { keyPath: "imageRef" });
        };
        req.onsuccess = function () { resolve(req.result); };
        req.onerror = function () { resolve(null); };
        req.onblocked = function () { resolve(null); };
      } catch (e) {
        resolve(null);
      }
    });
    return dbPromise;
  }

  function tx(mode, fn) {
    return openDb().then(function (db) {
      if (!db) return null;
      return new Promise(function (resolve) {
        try {
          var t = db.transaction(STORE, mode);
          var result = fn(t.objectStore(STORE));
          t.oncomplete = function () { resolve(result && "result" in result ? result.result : null); };
          t.onerror = function () { resolve(null); };
          t.onabort = function () { resolve(null); };
        } catch (e) {
          resolve(null);
        }
      });
    });
  }

  /** PNG data URL -> smaller JPEG data URL (max MAX_SIDE px). */
  function compact(dataUrl) {
    return new Promise(function (resolve) {
      var img = new Image();
      img.onload = function () {
        try {
          var scale = Math.min(1, MAX_SIDE / Math.max(img.naturalWidth, img.naturalHeight));
          var canvas = document.createElement("canvas");
          canvas.width = Math.max(1, Math.round(img.naturalWidth * scale));
          canvas.height = Math.max(1, Math.round(img.naturalHeight * scale));
          var ctx = canvas.getContext("2d");
          ctx.fillStyle = "#fff";
          ctx.fillRect(0, 0, canvas.width, canvas.height);
          ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
          resolve(canvas.toDataURL("image/jpeg", 0.85));
        } catch (e) {
          resolve(dataUrl);
        }
      };
      img.onerror = function () { resolve(null); };
      img.src = dataUrl;
    });
  }

  function prune() {
    return tx("readonly", function (os) { return os.getAll(); }).then(function (all) {
      if (!all || all.length <= MAX_SAVED) return;
      all.sort(function (a, b) { return (a.savedAt || "").localeCompare(b.savedAt || ""); });
      var extra = all.slice(0, all.length - MAX_SAVED);
      return tx("readwrite", function (os) {
        extra.forEach(function (rec) { os.delete(rec.imageRef); });
      });
    });
  }

  /** Keeps the processed (cropped, straightened) page on this computer. */
  function persistProcessed(imageRef, dataUrl, fileName) {
    if (!imageRef || !dataUrl) return Promise.resolve();
    return compact(dataUrl).then(function (small) {
      if (!small) return;
      return tx("readwrite", function (os) {
        os.put({ imageRef: imageRef, processedDataUrl: small, fileName: fileName || "", savedAt: new Date().toISOString() });
      }).then(prune);
    });
  }

  function put(imageRef, data) {
    store[imageRef] = data;
    if (data && data.processedDataUrl) persistProcessed(imageRef, data.processedDataUrl, data.fileName);
  }

  function get(imageRef) {
    return store[imageRef] || null;
  }

  function update(imageRef, patch) {
    store[imageRef] = Object.assign({}, store[imageRef] || {}, patch);
    if (patch && patch.processedDataUrl) persistProcessed(imageRef, patch.processedDataUrl, store[imageRef].fileName);
    return store[imageRef];
  }

  /**
   * Brings a saved processed page back into memory. Resolves the record
   * ({ processedDataUrl, ... }) or null when this computer has none.
   */
  function load(imageRef) {
    if (!imageRef) return Promise.resolve(null);
    var have = store[imageRef];
    if (have && have.processedDataUrl) return Promise.resolve(have);
    return tx("readonly", function (os) { return os.get(imageRef); }).then(function (rec) {
      if (!rec || !rec.processedDataUrl) return null;
      store[imageRef] = Object.assign({}, store[imageRef] || {}, { processedDataUrl: rec.processedDataUrl, fileName: rec.fileName, fromComputer: true });
      return store[imageRef];
    });
  }

  function remove(imageRef) {
    delete store[imageRef];
    tx("readwrite", function (os) { os.delete(imageRef); });
  }

  global.KhannaPassportImageStore = { put: put, get: get, update: update, load: load, remove: remove };
})(window);
