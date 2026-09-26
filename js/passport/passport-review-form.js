/* ==========================================================================
   Khanna Travels & Holidays — Passport OCR review form
   Renders the editable applicant/passport field groups, applies OCR results
   onto them with per-field confidence styling, and reads the current
   (possibly hand-edited) values back out. The DOM inputs are the single
   source of truth for "what does the form currently say" — there is no
   parallel JS draft object to keep in sync, which keeps this file small.

   OCR principle (project rule 10): a field the OCR engine did not return is
   never silently left blank without explanation, and a field it did return
   is always marked "please verify" until a staff member has looked at (or
   edited) it — never auto-accepted.
   ========================================================================== */
(function (global) {
  "use strict";

  var utils = global.KhannaUtils;

  var SALUTATIONS = ["", "Mr", "Mrs", "Ms", "Dr", "Master", "Other"];
  var SEXES = [
    { value: "", label: "—" },
    { value: "M", label: "Male" },
    { value: "F", label: "Female" },
    { value: "X", label: "Other / Unspecified" },
  ];

  var PERSONAL_FIELDS = [
    { path: "applicant.salutation", label: "Salutation", type: "select", options: SALUTATIONS },
    { path: "applicant.firstName", label: "First name" },
    { path: "applicant.middleName", label: "Middle name" },
    { path: "applicant.lastName", label: "Last name" },
    { path: "applicant.fullName", label: "Full name (as printed in passport)" },
    { path: "applicant.dob", label: "Date of birth", type: "date" },
    { path: "applicant.sex", label: "Sex", type: "select", options: SEXES },
    { path: "applicant.nationality", label: "Nationality" },
    { path: "applicant.placeOfBirth", label: "Place of birth" },
  ];

  // Address (project spec's field list: "address, PIN where available").
  // A 3-level path ("applicant.address.line1") — readValues()/loadExisting()
  // handle this group separately from PERSONAL_FIELDS below since those two
  // only ever split off a single flat key (f.path.split(".")[1]); this is
  // the one nested exception, matching the applicant.address shape
  // KhannaState's emptyPerson() already models.
  var ADDRESS_FIELDS = [
    { path: "applicant.address.line1", label: "Address line 1" },
    { path: "applicant.address.line2", label: "Address line 2" },
    { path: "applicant.address.city", label: "City" },
    { path: "applicant.address.state", label: "State" },
    { path: "applicant.address.pincode", label: "PIN code" },
    { path: "applicant.address.country", label: "Country" },
  ];

  var CURRENT_PASSPORT_FIELDS = [
    { path: "current.number", label: "Passport number" },
    { path: "current.type", label: "Document type" },
    { path: "current.countryCode", label: "Issuing country code" },
    { path: "current.issueDate", label: "Date of issue" },
    { path: "current.expiryDate", label: "Date of expiry", type: "date" },
    { path: "current.issuingAuthority", label: "Issuing authority" },
    { path: "current.issuePlace", label: "Place of issue" },
  ];

  var OLD_PASSPORT_FIELDS = [
    { path: "old.number", label: "Old passport number" },
    { path: "old.issueDate", label: "Date of issue" },
    { path: "old.expiryDate", label: "Date of expiry" },
  ];

  function fieldId(path, instanceId) {
    return "pf-" + (instanceId ? instanceId + "-" : "") + path.replace(/\./g, "-");
  }

  function fieldRow(f, instanceId) {
    var id = fieldId(f.path, instanceId);
    var input;
    if (f.type === "select") {
      var opts = f.options
        .map(function (o) {
          var val = typeof o === "object" ? o.value : o;
          var label = typeof o === "object" ? o.label : val || "—";
          return '<option value="' + utils.escapeHtml(val) + '">' + utils.escapeHtml(label) + "</option>";
        })
        .join("");
      input = '<select id="' + id + '" data-field="' + f.path + '">' + opts + "</select>";
    } else {
      input =
        '<input type="' + (f.type || "text") + '" id="' + id + '" data-field="' + f.path + '" autocomplete="off" />';
    }
    return (
      '<div class="field ocr-field" data-field-wrap="' + f.path + '">' +
      '<label for="' + id + '">' + utils.escapeHtml(f.label) + "</label>" +
      input +
      '<span class="ocr-field__meta" data-field-meta="' + f.path + '"></span>' +
      "</div>"
    );
  }

  /**
   * @param {string} [instanceId] Unique per passport-processing controller
   *   instance (e.g. "applicant" or a traveller id). Multiple instances can
   *   be in the DOM at once (the applicant's step-1 form stays mounted
   *   while a traveller's panel is open on step 2), so every generated
   *   `id`/`for` pair is namespaced by it to stay valid HTML and keep
   *   label click-to-focus working on the right field.
   */
  function skeletonHtml(instanceId) {
    var row = function (f) {
      return fieldRow(f, instanceId);
    };
    return (
      '<div class="notice" data-ocr-banner hidden></div>' +
      '<div data-ocr-warnings></div>' +
      "" +
      '<div class="passport-form-group">' +
      "<h3>Personal details</h3>" +
      '<div class="field-grid">' +
      PERSONAL_FIELDS.map(row).join("") +
      "</div>" +
      "</div>" +
      "" +
      '<div class="passport-form-group">' +
      "<h3>Address</h3>" +
      '<div class="field-grid">' +
      ADDRESS_FIELDS.map(row).join("") +
      "</div>" +
      "</div>" +
      "" +
      '<div class="passport-form-group">' +
      '<div class="passport-form-group__header">' +
      "<h3>Current passport</h3>" +
      '<span class="badge" data-mrz-badge>MRZ not read yet</span>' +
      "</div>" +
      '<div class="field-grid">' +
      CURRENT_PASSPORT_FIELDS.map(row).join("") +
      "</div>" +
      '<div class="mrz-strip" data-mrz-strip hidden>' +
      '<code data-mrz-line1></code>' +
      '<code data-mrz-line2></code>' +
      "</div>" +
      "</div>" +
      "" +
      '<div class="passport-form-group">' +
      '<label class="checkbox-row">' +
      '<input type="checkbox" data-old-passport-toggle />' +
      "<span>This applicant has an old / previous passport to record</span>" +
      "</label>" +
      '<div class="field-grid" data-old-passport-fields hidden>' +
      OLD_PASSPORT_FIELDS.map(row).join("") +
      "</div>" +
      "</div>" +
      "" +
      '<div class="passport-form-group passport-verify-group">' +
      '<label class="checkbox-row">' +
      '<input type="checkbox" data-verified-checkbox />' +
      "<span>I have compared these details against the physical passport and confirm they are correct.</span>" +
      "</label>" +
      '<p class="passport-verify-note">Final passport verification always stays with authorized staff — OCR never marks itself as verified.</p>' +
      "</div>"
    );
  }

  function el(container, path) {
    return utils.qs('[data-field="' + path + '"]', container);
  }

  function metaEl(container, path) {
    return utils.qs('[data-field-meta="' + path + '"]', container);
  }

  function setFieldValue(container, path, value) {
    var input = el(container, path);
    if (input) input.value = value === null || value === undefined ? "" : value;
  }

  function getFieldValue(container, path) {
    var input = el(container, path);
    return input ? input.value : "";
  }

  function setFieldState(container, path, state, metaText) {
    var wrap = utils.qs('[data-field-wrap="' + path + '"]', container);
    if (!wrap) return;
    wrap.classList.remove("field-ok", "field-review", "field-missing", "field-manual");
    if (state) wrap.classList.add("field-" + state);
    var meta = metaEl(container, path);
    if (meta) meta.textContent = metaText || "";
  }

  /** Applies one OCR field ({value, confidence, source, needsReview}) onto a form input. */
  function applyOcrField(container, path, ocrField) {
    if (!ocrField || ocrField.value === null || ocrField.value === undefined || ocrField.value === "") {
      setFieldState(container, path, "missing", "Not detected by OCR — please enter manually.");
      return;
    }
    setFieldValue(container, path, ocrField.value);
    var pct = Math.round((ocrField.confidence || 0) * 100);
    var sourceLabel = ocrField.source === "mrz" ? "machine-readable zone" : "visual inspection zone";
    if (ocrField.needsReview) {
      setFieldState(
        container,
        path,
        "review",
        "OCR extracted — please verify (" + pct + "% confidence, " + sourceLabel + ")."
      );
    } else {
      setFieldState(container, path, "ok", "OCR extracted (" + pct + "% confidence, " + sourceLabel + ").");
    }
    var wrap = utils.qs('[data-field-wrap="' + path + '"]', container);
    if (wrap) wrap.dataset.ocrTouched = "1";
  }

  /** Splits MRZ givenNames into firstName/middleName, sharing that field's own confidence. */
  function applyGivenNames(container, ocrField) {
    if (!ocrField || !ocrField.value) {
      applyOcrField(container, "applicant.firstName", null);
      applyOcrField(container, "applicant.middleName", null);
      return;
    }
    var parts = ocrField.value.trim().split(/\s+/);
    applyOcrField(container, "applicant.firstName", { value: parts[0], confidence: ocrField.confidence, source: ocrField.source, needsReview: ocrField.needsReview });
    if (parts.length > 1) {
      applyOcrField(container, "applicant.middleName", {
        value: parts.slice(1).join(" "),
        confidence: ocrField.confidence,
        source: ocrField.source,
        needsReview: ocrField.needsReview,
      });
    }
  }

  function renderMrzBadge(container, mrz) {
    var badge = utils.qs("[data-mrz-badge]", container);
    var strip = utils.qs("[data-mrz-strip]", container);
    if (!badge) return;
    if (!mrz) {
      badge.className = "badge";
      badge.textContent = "MRZ not detected";
      if (strip) strip.hidden = true;
      return;
    }
    if (mrz.valid) {
      badge.className = "badge badge-success";
      badge.textContent = "MRZ Valid";
    } else {
      badge.className = "badge badge-warning";
      badge.textContent = "MRZ Needs Review";
    }
    if (strip) {
      strip.hidden = false;
      var l1 = utils.qs("[data-mrz-line1]", container);
      var l2 = utils.qs("[data-mrz-line2]", container);
      if (l1) l1.textContent = mrz.line1 || "";
      if (l2) l2.textContent = mrz.line2 || "";
    }
  }

  function renderWarnings(container, warnings) {
    var box = utils.qs("[data-ocr-warnings]", container);
    if (!box) return;
    if (!warnings || !warnings.length) {
      box.innerHTML = "";
      return;
    }
    box.innerHTML = warnings
      .map(function (w) {
        return (
          '<div class="notice notice-warning">' +
          '<svg class="icon icon-sm" viewBox="0 0 24 24"><path d="M12 9v4M12 17h.01M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0Z"/></svg>' +
          "<span>" + utils.escapeHtml(w) + "</span>" +
          "</div>"
        );
      })
      .join("");
  }

  function setBanner(container, mode) {
    var banner = utils.qs("[data-ocr-banner]", container);
    if (!banner) return;
    if (mode === "extracted") {
      banner.hidden = false;
      banner.className = "notice notice-warning";
      banner.innerHTML =
        '<svg class="icon icon-sm" viewBox="0 0 24 24"><path d="M12 8v5M12 16h.01"/><circle cx="12" cy="12" r="9"/></svg>' +
        "<span><strong>OCR Extracted — Please Verify.</strong> Every field below was read automatically and must be checked against the physical passport before saving.</span>";
    } else if (mode === "verified") {
      banner.hidden = false;
      banner.className = "notice notice-success";
      banner.innerHTML =
        '<svg class="icon icon-sm" viewBox="0 0 24 24"><path d="m20 6-11 11-5-5"/></svg>' +
        "<span><strong>Verified</strong> by a staff member against the physical passport.</span>";
    } else {
      banner.hidden = true;
    }
  }

  /** Reads the current form state back out, keyed to match the applicant/passport data model. */
  function readValues(container) {
    var applicant = {};
    PERSONAL_FIELDS.forEach(function (f) {
      applicant[f.path.split(".")[1]] = getFieldValue(container, f.path);
    });
    var address = {};
    ADDRESS_FIELDS.forEach(function (f) {
      address[f.path.split(".")[2]] = getFieldValue(container, f.path);
    });
    applicant.address = address;
    var current = {};
    CURRENT_PASSPORT_FIELDS.forEach(function (f) {
      current[f.path.split(".")[1]] = getFieldValue(container, f.path);
    });
    var oldToggle = utils.qs("[data-old-passport-toggle]", container);
    var old = null;
    if (oldToggle && oldToggle.checked) {
      old = {};
      OLD_PASSPORT_FIELDS.forEach(function (f) {
        old[f.path.split(".")[1]] = getFieldValue(container, f.path);
      });
    }
    var verifiedEl = utils.qs("[data-verified-checkbox]", container);
    return { applicant: applicant, current: current, old: old, verified: !!(verifiedEl && verifiedEl.checked) };
  }

  /** Pre-fills the form from an already-saved applicant/passport record (resuming a draft). */
  function loadExisting(container, applicant) {
    applicant = applicant || {};
    var passport = applicant.passport || {};
    var current = passport.current || {};
    var old = passport.old;

    PERSONAL_FIELDS.forEach(function (f) {
      var key = f.path.split(".")[1];
      setFieldValue(container, f.path, applicant[key]);
    });
    var address = applicant.address || {};
    ADDRESS_FIELDS.forEach(function (f) {
      var key = f.path.split(".")[2];
      setFieldValue(container, f.path, address[key]);
    });
    CURRENT_PASSPORT_FIELDS.forEach(function (f) {
      var key = f.path.split(".")[1];
      setFieldValue(container, f.path, current[key]);
    });
    renderMrzBadge(container, current.mrzLine1 ? { valid: current.mrzValid, line1: current.mrzLine1, line2: current.mrzLine2 } : null);

    var toggle = utils.qs("[data-old-passport-toggle]", container);
    var oldFields = utils.qs("[data-old-passport-fields]", container);
    if (old) {
      if (toggle) toggle.checked = true;
      if (oldFields) oldFields.hidden = false;
      OLD_PASSPORT_FIELDS.forEach(function (f) {
        var key = f.path.split(".")[1];
        setFieldValue(container, f.path, old[key]);
      });
    }

    var verifiedEl = utils.qs("[data-verified-checkbox]", container);
    if (verifiedEl) verifiedEl.checked = passport.verificationStatus === "Verified";

    if (passport.verificationStatus === "Verified") {
      setBanner(container, "verified");
    } else if (passport.verificationStatus === "OCR Extracted — Please Verify") {
      setBanner(container, "extracted");
    } else {
      setBanner(container, null);
    }
  }

  /** Applies a fresh OCR result onto the form, overwriting values + confidence styling. */
  function applyOcrResult(container, result) {
    var fields = result.fields || {};
    applyOcrField(container, "applicant.lastName", fields.surname);
    applyOcrField(container, "applicant.fullName", fields.fullName);
    applyGivenNames(container, fields.givenNames);
    applyOcrField(container, "applicant.dob", fields.dateOfBirth);
    applyOcrField(container, "applicant.sex", fields.sex);
    applyOcrField(container, "applicant.nationality", fields.nationality);
    applyOcrField(container, "applicant.placeOfBirth", fields.placeOfBirth);

    applyOcrField(container, "applicant.address.line1", fields.addressLine1);
    applyOcrField(container, "applicant.address.line2", fields.addressLine2);
    applyOcrField(container, "applicant.address.city", fields.addressCity);
    applyOcrField(container, "applicant.address.state", fields.addressState);
    applyOcrField(container, "applicant.address.pincode", fields.addressPincode);
    applyOcrField(container, "applicant.address.country", fields.addressCountry);

    applyOcrField(container, "current.number", fields.passportNumber);
    applyOcrField(container, "current.type", fields.passportType);
    applyOcrField(container, "current.countryCode", fields.countryCode);
    applyOcrField(container, "current.issueDate", fields.dateOfIssue);
    applyOcrField(container, "current.expiryDate", fields.dateOfExpiry);
    applyOcrField(container, "current.issuingAuthority", fields.issuingAuthority);
    applyOcrField(container, "current.issuePlace", fields.placeOfIssue);

    if (fields.oldPassportNumber && fields.oldPassportNumber.value) {
      var toggle = utils.qs("[data-old-passport-toggle]", container);
      var oldFields = utils.qs("[data-old-passport-fields]", container);
      if (toggle) toggle.checked = true;
      if (oldFields) oldFields.hidden = false;
      applyOcrField(container, "old.number", fields.oldPassportNumber);
    }

    renderMrzBadge(container, result.mrz);
    renderWarnings(container, result.warnings);
    setBanner(container, "extracted");

    var verifiedEl = utils.qs("[data-verified-checkbox]", container);
    if (verifiedEl) verifiedEl.checked = false; // a fresh OCR read always needs a fresh human check
  }

  /** Wires the "downgrade to manual once edited" + old-passport toggle behaviour. Call once per mount. */
  function bindInteractions(container) {
    utils.on(container, "input", "input[data-field], select[data-field]", function (e, target) {
      var wrap = target.closest(".field");
      if (wrap && wrap.dataset.ocrTouched) {
        wrap.classList.remove("field-ok", "field-review", "field-missing");
        wrap.classList.add("field-manual");
        var path = target.getAttribute("data-field");
        var meta = metaEl(container, path);
        if (meta) meta.textContent = "Manually entered / edited by staff.";
      }
    });
    utils.on(container, "change", "[data-old-passport-toggle]", function (e, target) {
      var oldFields = utils.qs("[data-old-passport-fields]", container);
      if (oldFields) oldFields.hidden = !target.checked;
    });
  }

  global.KhannaPassportReviewForm = {
    skeletonHtml: skeletonHtml,
    bindInteractions: bindInteractions,
    loadExisting: loadExisting,
    applyOcrResult: applyOcrResult,
    readValues: readValues,
    setBanner: setBanner,
  };
})(window);
