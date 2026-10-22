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

  // Middle Name and Full Name were removed from this form on explicit
  // request — "Given Name" (still applicant.firstName under the hood, so
  // every other consumer of that path keeps working) now holds the OCR's
  // whole given-names string unsplit; applicant.fullName is still derived
  // automatically at save time in passport-processing.js's savePerson()
  // (from Given Name + Last Name) since other controllers — e.g.
  // authorization.js's personHasCoreFields() — still key off it, it just no
  // longer has its own input on this form.
  var PERSONAL_FIELDS = [
    { path: "applicant.salutation", label: "Salutation", type: "select", options: SALUTATIONS },
    { path: "applicant.firstName", label: "Given Name" },
    { path: "applicant.lastName", label: "Last Name" },
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
    { path: "current.issueDate", label: "Date of issue", type: "date" },
    { path: "current.expiryDate", label: "Date of expiry", type: "date" },
    { path: "current.issuingAuthority", label: "Issuing authority" },
    { path: "current.issuePlace", label: "Place of issue" },
  ];

  var OLD_PASSPORT_FIELDS = [
    { path: "old.number", label: "Old passport number" },
    { path: "old.issueDate", label: "Date of issue", type: "date" },
    { path: "old.expiryDate", label: "Date of expiry", type: "date" },
    { path: "old.placeOfIssue", label: "Place of issue" },
  ];

  // ---- Dates: always DD-MM-YYYY on screen, ISO (YYYY-MM-DD) in saved data ----
  // The browser's own <input type="date"> shows the visitor's locale (mm/dd/yyyy
  // on a US-English browser), so these are plain text inputs with a fixed
  // DD-MM-YYYY format; the rest of the app keeps receiving ISO strings.
  function pad2(n) {
    return (n < 10 ? "0" : "") + n;
  }

  /** Parses ISO, DD-MM-YYYY, DD/MM/YYYY, DD.MM.YYYY or DDMMYYYY. Returns {iso, display} or null. */
  function parseDate(text) {
    var t = String(text === null || text === undefined ? "" : text).trim();
    var m, d, mo, y;
    if ((m = /^(\d{4})-(\d{1,2})-(\d{1,2})(?:$|T)/.exec(t))) {
      y = +m[1]; mo = +m[2]; d = +m[3];
    } else if ((m = /^(\d{1,2})\s*[-\/.]\s*(\d{1,2})\s*[-\/.]\s*(\d{4})$/.exec(t))) {
      d = +m[1]; mo = +m[2]; y = +m[3];
    } else if ((m = /^(\d{2})(\d{2})(\d{4})$/.exec(t))) {
      d = +m[1]; mo = +m[2]; y = +m[3];
    } else {
      return null;
    }
    var dt = new Date(y, mo - 1, d);
    if (dt.getFullYear() !== y || dt.getMonth() !== mo - 1 || dt.getDate() !== d || y < 1900 || y > 2100) return null;
    return { iso: y + "-" + pad2(mo) + "-" + pad2(d), display: pad2(d) + "-" + pad2(mo) + "-" + y };
  }

  function isDateInput(input) {
    return !!(input && input.hasAttribute && input.hasAttribute("data-date"));
  }

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
    } else if (f.type === "date") {
      input =
        '<input type="text" inputmode="numeric" maxlength="10" placeholder="DD-MM-YYYY" data-date="1" id="' + id +
        '" data-field="' + f.path + '" autocomplete="off" />';
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
    if (!input) return;
    var text = value === null || value === undefined ? "" : String(value);
    if (isDateInput(input)) {
      var parsed = parseDate(text);
      input.value = parsed ? parsed.display : text;
      input.classList.remove("is-invalid");
    } else {
      input.value = text;
    }
  }

  /** The field's value; a date comes back as ISO (YYYY-MM-DD), or the raw text when it is not a valid date. */
  function getFieldValue(container, path) {
    var input = el(container, path);
    if (!input) return "";
    if (isDateInput(input)) {
      var raw = input.value.trim();
      if (!raw) return "";
      var parsed = parseDate(raw);
      return parsed ? parsed.iso : raw;
    }
    return input.value;
  }

  /** Labels of date fields that hold something that is not a valid DD-MM-YYYY date. */
  function invalidDates(container) {
    var bad = [];
    utils.qsa("input[data-date]", container).forEach(function (input) {
      var raw = input.value.trim();
      if (!raw || parseDate(raw)) return;
      var wrap = input.closest(".field");
      var label = wrap ? utils.qs("label", wrap) : null;
      bad.push(label ? label.textContent : input.getAttribute("data-field"));
    });
    return bad;
  }

  function setFieldState(container, path, state, metaText) {
    var wrap = utils.qs('[data-field-wrap="' + path + '"]', container);
    if (!wrap) return;
    wrap.classList.remove("field-ok", "field-review", "field-missing", "field-manual");
    if (state) wrap.classList.add("field-" + state);
    var meta = metaEl(container, path);
    if (meta) meta.textContent = metaText || "";
  }

  function isManual(container, path) {
    var wrap = utils.qs('[data-field-wrap="' + path + '"]', container);
    return !!(wrap && wrap.classList.contains("field-manual"));
  }

  /**
   * Applies one OCR field ({value, confidence, source, needsReview}) onto a
   * form input. A field staff have typed into is never overwritten. When the
   * OCR has no value the input is left as it is: it is only flagged "missing"
   * when it is empty (and, with opts.quiet, not at all - the caller flags what
   * is still missing once every page has been read).
   */
  function applyOcrField(container, path, ocrField, opts) {
    opts = opts || {};
    if (isManual(container, path)) return false;
    if (!ocrField || ocrField.value === null || ocrField.value === undefined || ocrField.value === "") {
      if (!opts.quiet && !getFieldValue(container, path)) {
        setFieldState(container, path, "missing", "Not detected by OCR — please enter manually.");
      }
      return false;
    }
    setFieldValue(container, path, ocrField.value);
    var pct = Math.round((ocrField.confidence || 0) * 100);
    var sourceLabel =
      ocrField.source === "mrz" ? "machine-readable zone" :
      ocrField.source === "derived" ? "worked out from passport data" :
      "visual inspection zone";
    if (ocrField.needsReview) {
      setFieldState(
        container,
        path,
        "review",
        "OCR extracted — please verify (" + pct + "% confidence, " + sourceLabel + ")." + (ocrField.note ? " " + ocrField.note : "")
      );
    } else {
      setFieldState(container, path, "ok", "OCR extracted (" + pct + "% confidence, " + sourceLabel + ").");
    }
    var wrap = utils.qs('[data-field-wrap="' + path + '"]', container);
    if (wrap) wrap.dataset.ocrTouched = "1";
    return true;
  }

  /**
   * Applies the OCR's full givenNames string onto the single "Given Name"
   * field. Previously split into firstName/middleName across two form
   * fields — Middle Name was removed from the form on request, so the
   * whole given-names string (which may itself contain multiple words) now
   * goes into applicant.firstName unsplit, sharing the OCR field's own
   * confidence/source/needsReview exactly as returned.
   */
  function applyGivenNames(container, ocrField) {
    applyOcrField(container, "applicant.firstName", ocrField);
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

  // Maps a raw backend warning sentence to a short field label for the
  // collapsible detail list. Backend-owned wording (ocr_runner.py) stays
  // the single source of truth for WHY something needs review; this is
  // purely a presentation label so the compact list reads as "Field —
  // reason" instead of a wall of full sentences. Falls back to "Page"
  // for anything unrecognized rather than silently dropping a warning —
  // a genuine backend warning must never disappear just because its
  // wording doesn't match a known pattern here.
  var WARNING_LABEL_PATTERNS = [
    { re: /passport number check digit/i, label: "Passport number" },
    { re: /date of birth check digit/i, label: "Date of birth" },
    { re: /passport expiry check digit/i, label: "Passport expiry" },
    { re: /mrz composite check digit/i, label: "MRZ" },
    { re: /mrz lines were not detected/i, label: "MRZ" },
    { re: /mrz (surname|given names) needed clean-up/i, label: "Name" },
    { re: /orientation could not be determined/i, label: "Page orientation" },
    { re: /this page looks blank/i, label: "Page image" },
  ];

  function warningLabel(message) {
    for (var i = 0; i < WARNING_LABEL_PATTERNS.length; i++) {
      if (WARNING_LABEL_PATTERNS[i].re.test(message)) return WARNING_LABEL_PATTERNS[i].label;
    }
    return "Page";
  }

  // Trims the backend's own standard "— please verify manually." suffix
  // for the compact detail line (the collapsible section's own heading
  // already says "needs review" / "Verification required", so repeating
  // it on every single line was exactly the noisy repetition being fixed)
  // — never touches the message itself, only this display copy.
  function warningReason(message) {
    return message.replace(/\s*[—-]\s*please verify manually\.?\s*$/i, "").trim();
  }

  /**
   * Compact-by-default OCR warning UI (redesigned per explicit staff
   * feedback that a wall of individual warning banners looked alarming
   * even when the underlying OCR read was largely reliable):
   *
   *  - Zero warnings: a single small, calm confirmation — never nothing,
   *    so staff still get an explicit "this was checked" signal, and
   *    never a big banner, since nothing here needs their attention.
   *  - One or more warnings: ONE compact summary line ("Verification
   *    required — N field(s) need review") that expands, on click, into
   *    the actual per-field detail. Nothing is hidden or downgraded —
   *    every genuine warning the backend returned is still listed in
   *    full — this only changes how much space it takes up before staff
   *    choose to look.
   */
  function renderWarnings(container, warnings, notices) {
    var box = utils.qs("[data-ocr-warnings]", container);
    if (!box) return;
    var list = warnings || [];
    var info = notices || [];

    var html = "";
    if (list.length) {
      var itemsHtml = list
        .map(function (w) {
          return (
            "<li><strong>" + utils.escapeHtml(warningLabel(w)) + "</strong> — " +
            utils.escapeHtml(warningReason(w)) + "</li>"
          );
        })
        .join("");
      html +=
        '<details class="notice notice-warning ocr-warning-summary">' +
        "<summary>" +
        '<svg class="icon icon-sm" viewBox="0 0 24 24"><path d="M12 9v4M12 17h.01M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0Z"/></svg>' +
        "<span>Verification required — " + list.length + (list.length === 1 ? " field needs review" : " fields need review") + "</span>" +
        "</summary>" +
        '<div class="ocr-warning-summary__body">' +
        '<ul class="ocr-warning-summary__list">' + itemsHtml + "</ul>" +
        "</div>" +
        "</details>";
    }
    if (info.length) {
      html +=
        '<ul class="ocr-notices">' +
        info.map(function (n) { return "<li>" + utils.escapeHtml(n) + "</li>"; }).join("") +
        "</ul>";
    }
    box.innerHTML = html;
  }

  function setBanner(container, mode) {
    var banner = utils.qs("[data-ocr-banner]", container);
    if (!banner) return;
    if (mode === "extracted") {
      banner.hidden = false;
      banner.className = "notice notice-warning";
      banner.innerHTML =
        '<svg class="icon icon-sm" viewBox="0 0 24 24"><path d="M12 8v5M12 16h.01"/><circle cx="12" cy="12" r="9"/></svg>' +
        "<span><strong>OCR Extracted — Please Verify.</strong></span>";
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

  // A back/address page can only add what it actually found: it must never
  // blank or "missing"-flag the name, number and dates read from the data
  // page, and a blank or unrecognised page must not touch the form at all.
  var ADDRESS_RESULT_PATHS = [
    ["applicant.address.line1", "addressLine1"],
    ["applicant.address.line2", "addressLine2"],
    ["applicant.address.city", "addressCity"],
    ["applicant.address.state", "addressState"],
    ["applicant.address.pincode", "addressPincode"],
    ["applicant.address.country", "addressCountry"],
  ];

  var OLD_PASSPORT_RESULT_PATHS = [
    ["old.number", "oldPassportNumber"],
    ["old.issueDate", "oldPassportIssueDate"],
    ["old.placeOfIssue", "oldPassportPlace"],
  ];

  function hasValue(field) {
    return !!(field && field.value !== null && field.value !== undefined && field.value !== "");
  }

  function applyAddress(container, fields) {
    ADDRESS_RESULT_PATHS.forEach(function (pair) {
      if (hasValue(fields[pair[1]])) applyOcrField(container, pair[0], fields[pair[1]], { quiet: true });
    });
  }

  // An old / previous passport printed on the address page is filled in and
  // the "has an old passport" section opened - never left for staff to find.
  function applyOldPassport(container, fields) {
    if (!OLD_PASSPORT_RESULT_PATHS.some(function (pair) { return hasValue(fields[pair[1]]); })) return;
    var toggle = utils.qs("[data-old-passport-toggle]", container);
    var oldFields = utils.qs("[data-old-passport-fields]", container);
    if (toggle) toggle.checked = true;
    if (oldFields) oldFields.hidden = false;
    OLD_PASSPORT_RESULT_PATHS.forEach(function (pair) {
      if (hasValue(fields[pair[1]])) applyOcrField(container, pair[0], fields[pair[1]], { quiet: true });
    });
  }

  // Mr / Master / Ms come from the data page (sex + age). "Mrs" needs a
  // spouse name, which is printed on the LAST page, so a female adult read as
  // "Ms" is upgraded when any processed page of this passport shows one.
  function salutationFor(result, resultsByPage) {
    var sal = result.fields && result.fields.salutation;
    if (!hasValue(sal)) return null;
    if (!sal.canBeMrs) return sal;
    var pages = resultsByPage || {};
    for (var key in pages) {
      if (!Object.prototype.hasOwnProperty.call(pages, key)) continue;
      var f = pages[key] && pages[key].fields;
      if (f && hasValue(f.spouseName)) {
        return {
          value: "Mrs",
          confidence: sal.confidence,
          source: "derived",
          needsReview: true,
          note: "Female adult with a spouse name printed on the passport (" + f.spouseName.value + ").",
        };
      }
    }
    return sal;
  }

  /** How well a data-page read is backed by its MRZ check digits (0 = none). */
  function bioScore(result) {
    var m = result && result.mrz;
    if (!m) return 0;
    var score = 0;
    ["passportNumberValid", "dateOfBirthValid", "dateOfExpiryValid", "compositeValid"].forEach(function (k) {
      if (m[k]) score += 10;
    });
    return score + (m.valid ? 5 : 1);
  }

  function upgradeSalutation(container, resultsByPage) {
    var pages = resultsByPage || {};
    for (var key in pages) {
      if (!Object.prototype.hasOwnProperty.call(pages, key)) continue;
      if (pages[key] && pages[key].pageKind === "bio") {
        var upgraded = salutationFor(pages[key], pages);
        if (upgraded) applyOcrField(container, "applicant.salutation", upgraded);
        return;
      }
    }
  }

  /**
   * Applies one page's OCR result onto the form. Pages of one upload are
   * merged, never overwritten by each other:
   *  - the data (bio) page with the best MRZ validation supplies name, number,
   *    dates, sex and nationality; a later page cannot replace those unless it
   *    is a strictly better data-page read (or is the same page re-read);
   *  - an address page only adds address, old-passport details and the spouse
   *    for the salutation;
   *  - blank / other pages change nothing;
   *  - a field staff have edited by hand is never touched.
   * opts: { pageIndex, force } - force applies regardless of earlier pages
   * (used by the OpenRouter testing path).
   */
  function applyOcrResult(container, result, resultsByPage, opts) {
    opts = opts || {};
    var fields = result.fields || {};
    var kind = result.pageKind || "bio";

    if (kind === "blank" || kind === "other") {
      if (container.dataset.bioScore === undefined && container.dataset.pagesApplied === undefined) {
        renderWarnings(container, result.warnings, result.notices);
      }
      return;
    }

    if (kind === "back") {
      applyAddress(container, fields);
      applyOldPassport(container, fields);
      upgradeSalutation(container, resultsByPage);
      container.dataset.pagesApplied = "1";
      setBanner(container, "extracted");
      return;
    }

    var score = bioScore(result);
    var current = container.dataset.bioScore;
    var samePage = opts.pageIndex !== undefined && String(opts.pageIndex) === container.dataset.bioPage;
    if (!opts.force && current !== undefined && !samePage && score <= Number(current)) return;
    container.dataset.bioScore = String(score);
    if (opts.pageIndex !== undefined) container.dataset.bioPage = String(opts.pageIndex);
    container.dataset.pagesApplied = "1";

    applyOcrField(container, "applicant.lastName", fields.surname);
    applyGivenNames(container, fields.givenNames);
    applyOcrField(container, "applicant.dob", fields.dateOfBirth);
    applyOcrField(container, "applicant.sex", fields.sex);
    applyOcrField(container, "applicant.nationality", fields.nationality);
    applyOcrField(container, "applicant.placeOfBirth", fields.placeOfBirth);
    var salutation = salutationFor(result, resultsByPage);
    if (salutation) applyOcrField(container, "applicant.salutation", salutation);

    // Address and old-passport details usually live on another page; whatever
    // this page happens to carry is used, nothing is flagged missing yet.
    applyAddress(container, fields);
    applyOldPassport(container, fields);

    applyOcrField(container, "current.number", fields.passportNumber);
    applyOcrField(container, "current.type", fields.passportType);
    applyOcrField(container, "current.countryCode", fields.countryCode);
    applyOcrField(container, "current.issueDate", fields.dateOfIssue);
    applyOcrField(container, "current.expiryDate", fields.dateOfExpiry);
    applyOcrField(container, "current.issuingAuthority", fields.issuingAuthority);
    applyOcrField(container, "current.issuePlace", fields.placeOfIssue);

    renderMrzBadge(container, result.mrz);
    renderWarnings(container, result.warnings, result.notices);
    setBanner(container, "extracted");

    var verifiedEl = utils.qs("[data-verified-checkbox]", container);
    if (verifiedEl) verifiedEl.checked = false; // a fresh OCR read always needs a fresh human check
  }

  // After every page has been read: fields that are still empty and were not
  // typed by staff are flagged as missing, so nothing silently stays blank.
  var OPTIONAL_PATHS = { "current.issuingAuthority": 1, "applicant.address.line2": 1 };

  function finalizeMissing(container) {
    ADDRESS_FIELDS.concat(PERSONAL_FIELDS, CURRENT_PASSPORT_FIELDS).forEach(function (f) {
      if (OPTIONAL_PATHS[f.path] || isManual(container, f.path) || getFieldValue(container, f.path)) return;
      var wrap = utils.qs('[data-field-wrap="' + f.path + '"]', container);
      if (wrap && !wrap.classList.contains("field-missing")) {
        setFieldState(container, f.path, "missing", "Not found on the scanned pages — please enter manually.");
      }
    });
  }

  /** Clears every OCR-filled value and state: called when a different passport file is chosen, so nothing from the previous one lingers. */
  function resetForNewUpload(container) {
    utils.qsa("input[data-field], select[data-field]", container).forEach(function (input) {
      input.value = "";
      input.classList.remove("is-invalid");
    });
    utils.qsa("[data-field-wrap]", container).forEach(function (wrap) {
      wrap.classList.remove("field-ok", "field-review", "field-missing", "field-manual");
      delete wrap.dataset.ocrTouched;
    });
    utils.qsa("[data-field-meta]", container).forEach(function (m) {
      m.textContent = "";
    });
    var toggle = utils.qs("[data-old-passport-toggle]", container);
    var oldFields = utils.qs("[data-old-passport-fields]", container);
    if (toggle) toggle.checked = false;
    if (oldFields) oldFields.hidden = true;
    var verifiedEl = utils.qs("[data-verified-checkbox]", container);
    if (verifiedEl) verifiedEl.checked = false;
    renderMrzBadge(container, null);
    renderWarnings(container, [], []);
    setBanner(container, null);
    delete container.dataset.bioScore;
    delete container.dataset.bioPage;
    delete container.dataset.pagesApplied;
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
    // Dates are typed as digits: the dashes are inserted for you, and the
    // value is normalised (and validated) when the field loses focus.
    utils.on(container, "input", "input[data-date]", function (e, target) {
      var raw = target.value;
      if (/[^\d\-\/. ]/.test(raw)) return;
      if (e.inputType && /^delete/.test(e.inputType)) return;
      if (target.selectionStart !== null && target.selectionStart < raw.length) return;
      var digits = raw.replace(/\D/g, "").slice(0, 8);
      var out = digits.slice(0, 2);
      if (digits.length > 2) out += "-" + digits.slice(2, 4);
      if (digits.length > 4) out += "-" + digits.slice(4);
      if (out !== raw) target.value = out;
    });
    utils.on(container, "focusout", "input[data-date]", function (e, target) {
      var raw = target.value.trim();
      var path = target.getAttribute("data-field");
      if (!raw) {
        target.classList.remove("is-invalid");
        return;
      }
      var parsed = parseDate(raw);
      if (parsed) {
        target.value = parsed.display;
        target.classList.remove("is-invalid");
      } else {
        target.classList.add("is-invalid");
        var meta = metaEl(container, path);
        if (meta) meta.textContent = "Enter the date as DD-MM-YYYY.";
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
    renderWarnings: renderWarnings,
    resetForNewUpload: resetForNewUpload,
    finalizeMissing: finalizeMissing,
    invalidDates: invalidDates,
    bioResultOf: function (resultsByPage) {
      var best = null;
      Object.keys(resultsByPage || {}).forEach(function (k) {
        var r = resultsByPage[k];
        if (r && r.pageKind === "bio" && (!best || bioScore(r) > bioScore(best))) best = r;
      });
      return best;
    },
    parseDate: parseDate,
  };
})(window);
