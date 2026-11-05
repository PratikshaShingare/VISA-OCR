/* ==========================================================================
   Khanna Travels & Holidays — "Enter details manually" (shared)
   The Cover Letter, Passport / Company Authorization and Invitation pages
   each list the people on the application and let staff tick who the letter
   is for. Every one of them now offers the same TWO ways to bring a person
   in, side by side, so nobody has to guess:

     1. "Use existing applicant" — pick someone already saved (the page's own
        "Use Existing Details" menu, unchanged);
     2. "Enter details manually"  — this module: a form with every detail the
        letter prints, the required ones marked *, plus the passport details
        the OCR would have read (date of birth, nationality, place of birth,
        expiry …) so a typed person is as complete as a scanned one.

   The person is saved as a REAL traveller on the active application
   (KhannaState.addTraveller) — so they also show up on every other letter
   page and on the Travellers step — and handed back to the calling page,
   which ticks them subject to its own people limit.

   The same form edits an existing person ("Complete details") when a letter
   would otherwise print a dash for something that is missing.

   Nothing here is OCR output: every value is typed by staff.

       KhannaAddTraveller.sourceChoiceHtml(existingWidgetHtml, docKey)
                                              -> the two-option block
       KhannaAddTraveller.buttonHtml(label)   -> the "manual" button
       KhannaAddTraveller.missingDetailsHtml(docKey, rows, attrs)
                                              -> "these would print as a dash" notice
       KhannaAddTraveller.open(function (id, row) { ... }, opts)
           opts: { docKey, role: "applicant"|"other", personId (edit mode) }
   ========================================================================== */
(function (global) {
  "use strict";

  var utils = global.KhannaUtils;
  var SALUTATIONS = ["", "Mr", "Mrs", "Ms", "Dr", "Master", "Other"];
  var PLUS_ICON = '<svg class="icon icon-sm" viewBox="0 0 24 24" aria-hidden="true"><path d="M12 5v14M5 12h14"/></svg>';

  var overlayEl = null;
  var onAdded = null;
  var lastFocus = null;
  var session = { docKey: "", role: "other", personId: "" };

  function docFields() {
    return global.KhannaDocFields;
  }

  function buttonHtml(label) {
    return (
      '<button class="btn btn-primary btn-sm" type="button" data-action="add-another-traveller">' +
      PLUS_ICON +
      utils.escapeHtml(label || "Enter details manually") +
      "</button>"
    );
  }

  // The two ways to bring a person in. `existingWidgetHtml` is the page's own
  // "Use Existing Details" menu (kept exactly as it was); the manual option is
  // the button below. Keeps the .use-existing-row class every page's click
  // handlers already look up.
  function sourceChoiceHtml(existingWidgetHtml, docKey) {
    var needed = docFields() ? docFields().summary(docKey) : "";
    return (
      '<div class="use-existing-row source-choice" data-source-choice role="group" aria-label="Where do the traveller details come from?">' +
      '<div class="source-option">' +
      '<h4 class="source-option__title">Use existing applicant</h4>' +
      '<p class="source-option__help">Pick someone already saved on an application or in your profiles.</p>' +
      existingWidgetHtml +
      "</div>" +
      '<div class="source-option">' +
      '<h4 class="source-option__title">Enter details manually</h4>' +
      '<p class="source-option__help">Type the details yourself. ' + utils.escapeHtml(needed) + "</p>" +
      buttonHtml("Enter details manually") +
      "</div>" +
      "</div>"
    );
  }

  // A warning for people already ticked on a letter whose required details are
  // empty (the letter would print a dash there), each with a button that opens
  // the form on that person. `people` are rows (js/saved-details.js shape);
  // `buttonAttrs` is added to every button so the page can tell its own apart.
  function missingDetailsHtml(docKey, people, buttonAttrs) {
    var D = docFields();
    if (!D || !people || !people.length) return "";
    var items = [];
    people.forEach(function (p, i) {
      var miss = D.missing(docKey, p, p.isApplicant || i === 0 ? "applicant" : "other");
      if (miss.length) items.push({ person: p, miss: miss });
    });
    if (!items.length) return "";
    return (
      '<div class="notice notice-warning missing-details" data-missing-details>' +
      '<svg class="icon icon-sm" viewBox="0 0 24 24"><path d="M12 9v4M12 17h.01"/><circle cx="12" cy="12" r="9"/></svg>' +
      "<div><strong>Some details are empty and would print as a dash:</strong>" +
      '<ul class="missing-details__list">' +
      items.map(function (it) {
        var who = (it.person.salutation ? it.person.salutation + ". " : "") + (it.person.fullName || "Unnamed");
        var what = it.miss.map(function (n) { return D.label(n).toLowerCase(); }).join(", ");
        var button = it.person.isManual
          ? ""
          : ' <button type="button" class="btn btn-secondary btn-sm" data-complete-details="' + utils.escapeHtml(it.person.id) + '" ' +
            (buttonAttrs || "") + ">Complete details</button>";
        return "<li><span>" + utils.escapeHtml(who) + " — " + utils.escapeHtml(what) + "</span>" + button + "</li>";
      }).join("") +
      "</ul></div></div>"
    );
  }

  function todayIso() {
    var d = new Date();
    return d.getFullYear() + "-" + String(d.getMonth() + 1).padStart(2, "0") + "-" + String(d.getDate()).padStart(2, "0");
  }

  function close() {
    if (!overlayEl) return;
    overlayEl.hidden = true;
    onAdded = null;
    if (lastFocus && lastFocus.focus && document.contains(lastFocus)) lastFocus.focus();
  }

  function showError(message) {
    var box = utils.qs("[data-add-traveller-error]", overlayEl);
    if (!box) return;
    box.hidden = !message;
    box.textContent = message || "";
  }

  function value(name) {
    var el = utils.qs('[data-add-traveller-field="' + name + '"]', overlayEl);
    return el ? el.value.trim() : "";
  }

  // The main applicant's letters need more of a person than a companion's. A
  // person typed in while the application has no main applicant yet (no
  // passport number on file) is taken to be that main applicant.
  function defaultRole(personId) {
    if (personId) return personId === "applicant" ? "applicant" : "other";
    var app = global.KhannaState.getActiveApplication();
    var cur = app && app.applicant && app.applicant.passport && app.applicant.passport.current;
    return cur && cur.number ? "other" : "applicant";
  }

  function requiredNames() {
    return docFields() ? docFields().required(session.docKey, session.role) : ["fullName", "passportNumber"];
  }

  function isRequired(name) {
    return requiredNames().indexOf(name) !== -1;
  }

  /* ---------------------------------------------------------------------
   * The form
   * ------------------------------------------------------------------- */

  function fieldHtml(name, label, type) {
    var id = "at-" + name;
    var star = isRequired(name) ? " *" : "";
    var control;
    if (name === "salutation") {
      control = '<select id="' + id + '" data-add-traveller-field="salutation">' +
        SALUTATIONS.map(function (s) { return '<option value="' + s + '">' + (s || "—") + "</option>"; }).join("") + "</select>";
    } else if (name === "sex") {
      control = '<select id="' + id + '" data-add-traveller-field="sex"><option value="">—</option><option value="M">Male</option><option value="F">Female</option><option value="X">Other / Unspecified</option></select>';
    } else if (type === "date") {
      var max = name === "issueDate" || name === "dob" ? ' max="' + todayIso() + '"' : "";
      control = '<input id="' + id + '" type="date" data-add-traveller-field="' + name + '"' + max + " />";
    } else {
      var inputType = name === "email" ? "email" : name === "phone" ? "tel" : "text";
      control = '<input id="' + id + '" type="' + inputType + '" autocomplete="off" data-add-traveller-field="' + name + '" />';
    }
    return '<div class="field" data-at-row="' + name + '"><label for="' + id + '">' + utils.escapeHtml(label) + star + "</label>" + control + "</div>";
  }

  var DATE_FIELDS = { dob: 1, issueDate: 1, expiryDate: 1 };

  // Two sections: what this letter needs (always open) and the remaining
  // passport details the OCR also reads (folded away, never required).
  function formBodyHtml() {
    var all = docFields() ? docFields().FIELDS : [];
    var req = [];
    var rest = [];
    all.forEach(function (f) {
      (isRequired(f.form) ? req : rest).push(f);
    });
    function grid(list) {
      return '<div class="add-traveller__grid">' + list.map(function (f) {
        return fieldHtml(f.form, f.label, DATE_FIELDS[f.form] ? "date" : "text");
      }).join("") + "</div>";
    }
    return (
      '<fieldset class="add-traveller__section"><legend>' +
      (session.docKey ? "Printed on this letter" : "Traveller details") +
      "</legend>" + grid(req) + "</fieldset>" +
      (rest.length
        ? '<details class="add-traveller__more" open><summary>Other passport details (as the OCR reads them)</summary>' + grid(rest) + "</details>"
        : "")
    );
  }

  function ensureOverlay() {
    if (overlayEl) return;
    var wrap = document.createElement("div");
    wrap.className = "app-picker-overlay";
    wrap.setAttribute("hidden", "");
    wrap.setAttribute("data-add-traveller-overlay", "");
    wrap.innerHTML =
      '<div class="app-picker add-traveller" role="dialog" aria-modal="true" aria-labelledby="addTravellerTitle">' +
      '<div class="app-picker__header">' +
      '<h3 id="addTravellerTitle" data-add-traveller-title>Enter traveller details</h3>' +
      '<button type="button" class="btn-icon" data-add-traveller-cancel aria-label="Close">' +
      '<svg class="icon icon-sm" viewBox="0 0 24 24"><path d="M6 6l12 12M18 6 6 18"/></svg>' +
      "</button>" +
      "</div>" +
      '<form class="add-traveller__form" data-add-traveller-form novalidate>' +
      '<div data-add-traveller-body></div>' +
      '<p class="field-hint" style="margin:0;">Fields marked * are needed. Typed by staff — check against the physical passport.</p>' +
      '<div class="notice notice-danger" data-add-traveller-error role="alert" hidden></div>' +
      '<div class="add-traveller__actions">' +
      '<button type="button" class="btn btn-secondary btn-sm" data-add-traveller-cancel>Cancel</button>' +
      '<button type="submit" class="btn btn-primary btn-sm" data-add-traveller-submit>Add traveller</button>' +
      "</div>" +
      "</form>" +
      "</div>";
    document.body.appendChild(wrap);
    overlayEl = wrap;

    utils.on(wrap, "click", "[data-add-traveller-cancel]", close);
    wrap.addEventListener("click", function (e) {
      if (e.target === wrap) close();
    });
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape" && !wrap.hasAttribute("hidden")) close();
    });
    utils.qs("[data-add-traveller-form]", wrap).addEventListener("submit", function (e) {
      e.preventDefault();
      submit();
    });
  }

  /* ---------------------------------------------------------------------
   * Reading and writing a person
   * ------------------------------------------------------------------- */

  function personRecord(app, personId) {
    if (personId === "applicant") return app.applicant;
    return (app.travellers || []).filter(function (t) { return t.id === personId; })[0] || null;
  }

  function fillFormFrom(rec) {
    var cur = (rec.passport && rec.passport.current) || {};
    var contact = rec.contact || {};
    var map = {
      salutation: rec.salutation,
      fullName: rec.fullName || [rec.firstName, rec.lastName].filter(Boolean).join(" "),
      sex: rec.sex,
      dob: rec.dob,
      nationality: rec.nationality,
      placeOfBirth: rec.placeOfBirth,
      passportNumber: cur.number,
      issuePlace: cur.issuePlace,
      issueDate: cur.issueDate,
      expiryDate: cur.expiryDate,
      phone: contact.phone,
      email: contact.email,
    };
    Object.keys(map).forEach(function (name) {
      var el = utils.qs('[data-add-traveller-field="' + name + '"]', overlayEl);
      if (el) el.value = map[name] || "";
    });
    // A detail already on file that the form folds away must stay visible.
    var more = utils.qs(".add-traveller__more", overlayEl);
    if (more && utils.qsa(".add-traveller__more input, .add-traveller__more select", overlayEl).some(function (el) { return el.value; })) {
      more.open = true;
    }
  }

  function patchFromForm(fullName, passportNumber) {
    var parts = fullName.split(/\s+/);
    return {
      salutation: value("salutation"),
      fullName: fullName,
      firstName: parts.length > 1 ? parts.slice(0, -1).join(" ") : fullName,
      lastName: parts.length > 1 ? parts[parts.length - 1] : "",
      sex: value("sex"),
      dob: value("dob"),
      nationality: value("nationality"),
      placeOfBirth: value("placeOfBirth"),
      passport: {
        current: {
          number: passportNumber,
          issuePlace: value("issuePlace"),
          issueDate: value("issueDate"),
          expiryDate: value("expiryDate"),
        },
      },
      contact: { phone: value("phone"), email: value("email") },
    };
  }

  function submit() {
    var app = global.KhannaState.getActiveApplication();
    if (!app) {
      showError("Choose or create an application first.");
      return;
    }
    var fullName = value("fullName");
    var passportNumber = value("passportNumber").toUpperCase().replace(/\s+/g, "");
    if (!fullName) {
      showError("Enter the traveller's full name.");
      return;
    }
    if (!passportNumber) {
      showError("Enter the traveller's passport number.");
      return;
    }
    var lacking = requiredNames().filter(function (name) {
      return name !== "fullName" && name !== "passportNumber" && !value(name);
    });
    if (lacking.length) {
      var label = docFields() ? docFields().label(lacking[0]) : lacking[0];
      showError("Enter the " + label.toLowerCase() + (lacking.length > 1 ? " (and " + (lacking.length - 1) + " more marked *)." : "."));
      var firstBad = utils.qs('[data-add-traveller-field="' + lacking[0] + '"]', overlayEl);
      if (firstBad) firstBad.focus();
      return;
    }
    var issueDate = value("issueDate");
    if (issueDate && issueDate > todayIso()) {
      showError("The date of issue cannot be in the future.");
      return;
    }
    var people = [app.applicant].concat(app.travellers || []).filter(Boolean);
    var clash = people.filter(function (p) {
      if (session.personId && (session.personId === "applicant" ? p === app.applicant : p.id === session.personId)) return false;
      var n = (p.passport && p.passport.current && p.passport.current.number) || "";
      return n && n.toUpperCase() === passportNumber;
    })[0];
    if (clash) {
      showError("A traveller with this passport number is already on this application.");
      return;
    }

    var patch = patchFromForm(fullName, passportNumber);
    var callback = onAdded;
    var id;
    if (session.personId === "applicant") {
      global.KhannaState.updateApplication(app.id, { applicant: patch }, "Applicant details completed");
      id = "applicant";
    } else if (session.personId) {
      global.KhannaState.updateTraveller(app.id, session.personId, patch, 'Traveller "' + fullName + '" updated');
      id = session.personId;
    } else {
      var traveller = global.KhannaState.addTraveller(app.id, "");
      global.KhannaState.updateTraveller(app.id, traveller.id, patch, 'Traveller "' + fullName + '" added');
      id = traveller.id;
    }
    close();
    if (callback) callback(id, { fullName: fullName, passportNumber: passportNumber, edited: !!session.personId });
  }

  /**
   * @param callback  runs with (personId, {fullName, passportNumber, edited})
   * @param opts      { docKey, role, personId } — see the file header
   */
  function open(callback, opts) {
    opts = opts || {};
    session = {
      docKey: opts.docKey || "",
      role: opts.role || defaultRole(opts.personId),
      personId: opts.personId || "",
    };
    ensureOverlay();
    onAdded = callback || null;
    lastFocus = document.activeElement;
    utils.qs("[data-add-traveller-body]", overlayEl).innerHTML = formBodyHtml();
    utils.qs("[data-add-traveller-title]", overlayEl).textContent = session.personId ? "Complete traveller details" : "Enter traveller details manually";
    utils.qs("[data-add-traveller-submit]", overlayEl).textContent = session.personId ? "Save details" : "Add traveller";
    utils.qs("[data-add-traveller-form]", overlayEl).reset();
    if (session.personId) {
      var app = global.KhannaState.getActiveApplication();
      var rec = app && personRecord(app, session.personId);
      if (rec) fillFormFrom(rec);
    }
    showError("");
    overlayEl.hidden = false;
    var first = utils.qs('[data-add-traveller-field="fullName"]', overlayEl);
    if (first) first.focus();
  }

  global.KhannaAddTraveller = {
    buttonHtml: buttonHtml,
    sourceChoiceHtml: sourceChoiceHtml,
    missingDetailsHtml: missingDetailsHtml,
    open: open,
  };
})(window);
