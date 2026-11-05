/* ==========================================================================
   Khanna Travels & Holidays — Document intake (reads uploaded files)
   Turns one uploaded passport file or hotel voucher file into a plain record
   the Upload Documents page can sort and later save. It does NOT invent a
   second OCR path: it calls the same backend endpoints, and applies passport
   results through the same review-form logic the single-passport page uses
   (KhannaPassportReviewForm, on a detached element — the DOM inputs are that
   module's source of truth), so a passport read here fills the same fields,
   in the same formats, with the same pages-merging rules.

   Nothing read here is verified (project rule 10): every record carries
   `verification: "OCR Extracted — Please Verify"` and a list of `flags`
   (missing / suspicious fields) for the page to show.
   ========================================================================== */
(function (global) {
  "use strict";

  var utils = global.KhannaUtils;
  var api = global.KhannaApi;
  var form = global.KhannaPassportReviewForm;
  var imageStore = global.KhannaPassportImageStore;

  // A passport PDF is the data page plus the address / old-passport page; the
  // single-passport page reads the first four pages, so does this.
  var PASSPORT_PAGE_LIMIT = 4;
  var VOUCHER_PAGE_LIMIT = 6;
  var VERIFY_LABEL = "OCR Extracted — Please Verify";

  function isPdf(file) {
    return /pdf$/i.test(file.type || "") || /\.pdf$/i.test(file.name || "");
  }

  /** "Accepted" per the page: PDF, JPG, JPEG, PNG. */
  function isAcceptedFile(file) {
    return isPdf(file) || /\.(jpe?g|png)$/i.test(file.name || "") || /^image\/(jpeg|png)$/i.test(file.type || "");
  }

  function readAsDataUrl(file) {
    return new Promise(function (resolve) {
      var reader = new FileReader();
      reader.onload = function () { resolve(reader.result); };
      reader.onerror = function () { resolve(null); };
      reader.readAsDataURL(file);
    });
  }

  function pageCountOf(file) {
    if (!isPdf(file)) return Promise.resolve(1);
    return api.getPageCount(file).then(
      function (res) { return (res && res.totalPages) || 1; },
      function () { return 1; }
    );
  }

  /** Flags worth a human look, in plain words. */
  function passportFlags(values, bio, failedPages) {
    var flags = [];
    var a = values.applicant || {};
    var c = values.current || {};
    if (!a.lastName && !a.firstName) flags.push("Name not found");
    if (!c.number) flags.push("Passport number not found");
    if (!a.dob) flags.push("Date of birth not found");
    if (!c.expiryDate) flags.push("Expiry date not found");
    if (bio && bio.mrz) {
      if (bio.mrz.valid === false) flags.push("MRZ check digits do not all agree");
    } else if (!bio) {
      flags.push("No passport data page recognised");
    } else {
      flags.push("MRZ not read");
    }
    if (failedPages) flags.push(failedPages + " page(s) could not be read");
    return flags;
  }

  /**
   * Reads one passport file (image, or PDF of up to PASSPORT_PAGE_LIMIT pages).
   * Resolves { kind, fileName, imageRef, values, bio, flags, totalPages,
   * verification }. Rejects only when no page could be read at all.
   */
  function readPassport(file, onStatus) {
    var say = onStatus || function () {};
    var imageRef = utils.generateId("psp");
    var holder = document.createElement("div");
    holder.innerHTML = form.skeletonHtml(utils.generateId("udp"));
    var resultsByPage = {};
    var failed = 0;
    var firstError = null;

    var imageReady = isPdf(file)
      ? Promise.resolve()
      : readAsDataUrl(file).then(function (url) {
          if (url) imageStore.put(imageRef, { fileName: file.name, originalDataUrl: url });
        });

    return Promise.all([pageCountOf(file), imageReady]).then(function (res) {
      var totalPages = res[0];
      var limit = Math.min(totalPages, PASSPORT_PAGE_LIMIT);
      var chain = Promise.resolve();
      for (var i = 0; i < limit; i++) {
        (function (pageIndex) {
          chain = chain.then(function () {
            say("Reading page " + (pageIndex + 1) + " of " + limit + "…");
            return api.processPassport(file, pageIndex, null).then(
              function (result) {
                resultsByPage[pageIndex] = result;
                if (result.pageKind === "bio" || pageIndex === 0) {
                  imageStore.update(imageRef, { processedDataUrl: "data:image/png;base64," + result.processedImageBase64 });
                }
                form.applyOcrResult(holder, result, resultsByPage, { pageIndex: pageIndex });
              },
              function (err) {
                failed += 1;
                if (!firstError) firstError = err;
              }
            );
          });
        })(i);
      }
      return chain.then(function () {
        if (failed >= limit) throw firstError || new Error("This file could not be read.");
        form.finalizeMissing(holder);
        var values = form.readValues(holder);
        values.applicant.fullName = [values.applicant.firstName, values.applicant.lastName]
          .filter(function (p) { return p && p.trim(); })
          .join(" ");
        var bio = form.bioResultOf(resultsByPage);
        return {
          kind: "passport",
          fileName: file.name,
          imageRef: imageRef,
          values: values,
          bio: bio ? { mrz: bio.mrz || null } : null,
          flags: passportFlags(values, bio, failed),
          totalPages: totalPages,
          verification: VERIFY_LABEL,
        };
      });
    });
  }

  /** The state patch (applicant / traveller shape) for a record from readPassport(). */
  function personPatchFromPassport(record) {
    var v = record.values;
    var mrz = (record.bio && record.bio.mrz) || null;
    return Object.assign({}, v.applicant, {
      passport: {
        current: Object.assign({}, v.current, {
          mrzLine1: mrz ? mrz.line1 : "",
          mrzLine2: mrz ? mrz.line2 : "",
          mrzValid: mrz ? mrz.valid : null,
        }),
        old: v.old,
        imageRef: record.imageRef,
        rotation: 0,
        // Never "Verified" — staff verify on the passport page.
        verificationStatus: VERIFY_LABEL,
      },
    });
  }

  /**
   * Reads one hotel voucher file (image or PDF). Resolves { kind, fileName,
   * guestNames, hotels: [hotelPatch], flags, verification }. A multi-page PDF
   * can hold several vouchers; extra pages that are not vouchers (terms,
   * cancellation policy) are dropped, as on the Hotel Blocking page.
   */
  function readVoucher(file, onStatus) {
    var say = onStatus || function () {};
    var toPatch = global.KhannaHotels && global.KhannaHotels.ocrResultToPatch;
    if (!toPatch) return Promise.reject(new Error("Hotel voucher reading is not available."));
    var hotels = [];
    var guestNames = [];
    var flags = [];

    function addGuests(list) {
      (list || []).forEach(function (g) {
        if (g && guestNames.map(function (x) { return x.toUpperCase(); }).indexOf(String(g).toUpperCase()) === -1) guestNames.push(g);
      });
    }

    function readPage(pageIndex, total) {
      say(total > 1 ? "Reading page " + (pageIndex + 1) + " of " + total + "…" : "Reading voucher…");
      return api.processHotelVoucher(file, pageIndex).then(function (result) {
        var pages = (result && result.totalPages) || 1;
        var isVoucherPage = !!(result && (result.voucherType !== "unknown" || (result.fields && result.fields.hotelName)));
        if (pageIndex === 0 || isVoucherPage) {
          var patch = toPatch(result);
          patch.source = "voucher";
          patch.voucherFileName = pageIndex > 0 ? file.name + " (page " + (pageIndex + 1) + ")" : file.name;
          hotels.push(patch);
          // The lead guest is reported as a field, and not always repeated in the
          // guest list — both are people named on the voucher.
          addGuests([patch.leadGuestName]);
          addGuests(result.guestNames);
          (result.warnings || []).forEach(function (w) { flags.push(w); });
        }
        return pages;
      });
    }

    return readPage(0, 1).then(function (pages) {
      var limit = Math.min(pages, VOUCHER_PAGE_LIMIT);
      var chain = Promise.resolve();
      for (var p = 1; p < limit; p++) {
        (function (pageIndex) {
          chain = chain.then(function () {
            return readPage(pageIndex, limit).catch(function () { /* an unreadable extra page is simply skipped */ });
          });
        })(p);
      }
      return chain.then(function () {
        var anyFields = hotels.some(function (h) { return h.hotelName || h.checkIn || h.checkOut; });
        if (!anyFields) flags.push("No hotel details could be read");
        if (!guestNames.length) flags.push("No guest name found");
        return { kind: "voucher", fileName: file.name, guestNames: guestNames, hotels: hotels, flags: flags, verification: VERIFY_LABEL };
      });
    });
  }

  global.KhannaDocumentIntake = {
    isAcceptedFile: isAcceptedFile,
    readPassport: readPassport,
    readVoucher: readVoucher,
    personPatchFromPassport: personPatchFromPassport,
    VERIFY_LABEL: VERIFY_LABEL,
  };
})(window);
