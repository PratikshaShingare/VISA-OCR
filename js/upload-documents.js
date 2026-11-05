/* ==========================================================================
   Khanna Travels & Holidays — Upload Documents page ("document sorter")
   "#/upload-documents". Staff type the MAIN APPLICANT's name, drop in the
   passports and hotel vouchers of one traveller or a whole group, and the
   page:
     1. reads every file with the existing OCR (js/documents/document-intake.js),
     2. sorts them around the typed name (js/documents/document-sorter.js),
        showing each decision with its confidence and reason — staff can tick /
        untick any document or pick a different main applicant,
     3. on "Generate", saves the chosen people and hotels into ONE application
        (so every other page can open it) and builds the ticked documents
        with the same generators the individual pages use.

   What it does NOT do (project rules 9, 10, 19): it never claims a match or
   an OCR read is verified; passports are saved as "OCR Extracted — Please
   Verify". Cover Letter and Invitation Letter need facts no passport or
   voucher contains (consulate, funding, employment ...), so when those are
   ticked the page pre-selects the people and travel dates and hands over to
   that page instead of pretending it could finish them.
   ========================================================================== */
(function (global) {
  "use strict";

  var utils = global.KhannaUtils;
  var api = global.KhannaApi;
  var Sorter = global.KhannaDocumentSorter;
  var Intake = global.KhannaDocumentIntake;

  var DOC_TYPES = [
    { key: "hotel", label: "Hotel Blocking (hotel vouchers)", page: "hotel-blocking", pageLabel: "Hotel Blocking" },
    { key: "passportAuth", label: "Passport Authorization Letter", page: "passport-authorization", pageLabel: "Passport Authorization Letter" },
    { key: "companyAuth", label: "Company Authorization Letter", page: "company-authorization", pageLabel: "Company Authorization Letter" },
    { key: "cover", label: "Cover Letter", page: "cover-letter", pageLabel: "Cover Letter" },
    { key: "invitation", label: "Invitation Letter", page: "invitation-letter", pageLabel: "Invitation Letter" },
  ];

  var st = {
    mainName: "",
    items: [], // { id, kind, file, status: queued|reading|done|error, message, record }
    mainOverride: null, // item id of a passport staff chose as the main applicant
    includeOverride: {}, // item id -> true/false (staff ticked or unticked it)
    docs: { hotel: true, passportAuth: true, companyAuth: false, cover: false, invitation: false },
    format: "docx",
    passportAuth: { centre: "", address: "", collector: "" },
    company: { country: "", address: "" },
    working: false, // the reading queue is running
    generating: false,
    appSignature: "",
    appId: null,
    notice: "",
  };

  var shellBuilt = false;

  function root() {
    return utils.qs("[data-upload-documents-root]");
  }

  /* ----------------------------------------------------------------------
   * Sorting (pure logic lives in document-sorter.js; this only adapts)
   * -------------------------------------------------------------------- */

  function passportRecordOf(item) {
    var a = item.record.values.applicant;
    return { id: item.id, fileName: item.file.name, surname: a.lastName || "", givenNames: a.firstName || "", passportNumber: (item.record.values.current || {}).number || "" };
  }

  function currentSort() {
    var done = st.items.filter(function (i) { return i.status === "done"; });
    var passports = done.filter(function (i) { return i.kind === "passport"; }).map(passportRecordOf);
    var vouchers = done.filter(function (i) { return i.kind === "voucher"; }).map(function (i) {
      return { id: i.id, fileName: i.file.name, guestNames: i.record.guestNames || [] };
    });
    var typed = st.mainName;
    if (st.mainOverride) {
      var chosen = passports.filter(function (p) { return p.id === st.mainOverride; })[0];
      if (chosen) typed = Sorter.passportDisplayName(chosen);
    }
    var result = Sorter.sort(typed, passports, vouchers);
    var byId = {};
    result.passports.forEach(function (r) { byId[r.id] = Object.assign({}, r); });
    result.vouchers.forEach(function (r) { byId[r.id] = Object.assign({}, r); });
    Object.keys(byId).forEach(function (id) {
      if (Object.prototype.hasOwnProperty.call(st.includeOverride, id)) byId[id].include = !!st.includeOverride[id];
    });
    return { byId: byId, mainPassportId: result.mainPassportId };
  }

  function included(kind, sort) {
    return st.items.filter(function (i) {
      return i.kind === kind && i.status === "done" && sort.byId[i.id] && sort.byId[i.id].include;
    });
  }

  /* ----------------------------------------------------------------------
   * Reading queue — one file at a time (OCR is heavy), in upload order
   * -------------------------------------------------------------------- */

  function pump() {
    if (st.working) return;
    var next = st.items.filter(function (i) { return i.status === "queued"; })[0];
    if (!next) {
      renderResults();
      return;
    }
    st.working = true;
    next.status = "reading";
    next.message = "Starting…";
    renderResults();
    var onStatus = function (text) {
      next.message = text;
      var line = utils.qs('[data-ud-item="' + next.id + '"] [data-ud-status]');
      if (line) line.textContent = text;
    };
    var run = next.kind === "passport" ? Intake.readPassport(next.file, onStatus) : Intake.readVoucher(next.file, onStatus);
    run.then(
      function (record) {
        next.status = "done";
        next.record = record;
        next.message = "";
      },
      function (err) {
        next.status = "error";
        next.message = (err && err.message) || "This file could not be read.";
      }
    ).then(function () {
      st.working = false;
      pump();
    });
  }

  function addFiles(kind, fileList) {
    var rejected = [];
    var added = 0;
    Array.prototype.slice.call(fileList || []).forEach(function (file) {
      if (!Intake.isAcceptedFile(file)) {
        rejected.push(file.name);
        return;
      }
      var duplicate = st.items.some(function (i) {
        return i.kind === kind && i.file.name === file.name && i.file.size === file.size && i.file.lastModified === file.lastModified;
      });
      if (duplicate) return;
      st.items.push({ id: utils.generateId("udf"), kind: kind, file: file, status: "queued", message: "Waiting…", record: null });
      added += 1;
    });
    st.notice = rejected.length ? "Not added (only PDF, JPG, JPEG and PNG are accepted): " + rejected.join(", ") + "." : "";
    renderResults();
    if (added) pump();
  }

  function removeItem(id) {
    var item = st.items.filter(function (i) { return i.id === id; })[0];
    if (!item || item.status === "reading") return;
    st.items = st.items.filter(function (i) { return i.id !== id; });
    delete st.includeOverride[id];
    if (st.mainOverride === id) st.mainOverride = null;
    renderResults();
  }

  /* ----------------------------------------------------------------------
   * Rendering
   * -------------------------------------------------------------------- */

  var ROLE_BADGE = {
    main: ["badge badge-info", "Main applicant"],
    companion: ["badge", "Travelling with applicant"],
    unmatched: ["badge badge-warning", "Not linked to this applicant"],
    unreadable: ["badge badge-danger", "Could not read name"],
  };

  function shellHtml() {
    return (
      '<div class="ud-layout">' +
      '<section class="card ud-card">' +
      '<h2 class="ud-card__title"><span class="ud-step">1</span> Main applicant</h2>' +
      '<div class="field"><label for="udMainName">Main applicant name *</label>' +
      '<input type="text" id="udMainName" data-ud-main-name autocomplete="off" placeholder="e.g. Rajesh Kumar Sharma" /></div>' +
      '<p class="field-hint">Passports and hotel vouchers are matched to this name. Matching is by name only — every match is shown below and you can change it.</p>' +
      "</section>" +
      '<section class="card ud-card">' +
      '<h2 class="ud-card__title"><span class="ud-step">2</span> Upload documents</h2>' +
      '<div class="ud-drops">' +
      dropHtml("passport", "Passports", "One file per passport — PDF, JPG, JPEG or PNG") +
      dropHtml("voucher", "Hotel vouchers", "PDF, JPG, JPEG or PNG — several allowed") +
      "</div>" +
      '<p class="field-hint" data-ud-notice role="status"></p>' +
      "</section>" +
      '<section class="card ud-card" data-ud-results-card>' +
      '<h2 class="ud-card__title"><span class="ud-step">3</span> Sorted documents</h2>' +
      '<p class="field-hint" data-ud-verify-note>OCR Extracted — Please Verify. Everything read from a file may be wrong or incomplete; check it before relying on it.</p>' +
      '<div data-ud-results></div>' +
      "</section>" +
      '<section class="card ud-card">' +
      '<h2 class="ud-card__title"><span class="ud-step">4</span> Generate</h2>' +
      '<fieldset class="ud-docs"><legend class="sr-only">Documents to generate</legend>' +
      DOC_TYPES.map(function (d) {
        return '<label class="ud-check"><input type="checkbox" data-ud-doc="' + d.key + '"' + (st.docs[d.key] ? " checked" : "") + " /> <span>" + d.label + "</span></label>";
      }).join("") +
      "</fieldset>" +
      '<div data-ud-details></div>' +
      '<div class="ud-format field"><label for="udFormat">File format</label>' +
      '<select id="udFormat" data-ud-format><option value="docx">Word (.docx)</option><option value="pdf">PDF</option></select></div>' +
      '<p class="field-hint" data-ud-ready role="status"></p>' +
      '<div class="ud-actions"><button type="button" class="btn btn-primary" data-ud-generate>Generate</button>' +
      '<a class="btn btn-secondary btn-sm" href="#/upload-passport" data-nav-link="upload-passport">Review a single passport in detail</a></div>' +
      "</section>" +
      "</div>"
    );
  }

  function dropHtml(kind, title, hint) {
    return (
      '<label class="ud-drop" data-ud-drop="' + kind + '">' +
      '<input type="file" multiple accept=".pdf,.jpg,.jpeg,.png,application/pdf,image/jpeg,image/png" data-ud-file="' + kind + '" />' +
      '<svg class="icon" viewBox="0 0 24 24"><path d="M12 16V4M7 9l5-5 5 5"/><path d="M4 20h16"/></svg>' +
      "<strong>Upload " + title + "</strong>" +
      "<span>" + hint + "</span>" +
      '<span class="ud-drop__or">click to choose, or drop files here</span>' +
      "</label>"
    );
  }

  function itemMeta(item) {
    if (item.kind === "passport") {
      var v = item.record.values;
      var bits = [];
      if (v.current && v.current.number) bits.push("Passport " + v.current.number);
      if (v.applicant.dob) bits.push("Born " + v.applicant.dob);
      if (v.applicant.nationality) bits.push(v.applicant.nationality);
      return bits.join(" · ");
    }
    var h = item.record.hotels[0] || {};
    var parts = [];
    if (h.hotelName) parts.push(h.hotelName);
    if (h.checkIn && h.checkOut) parts.push(utils.formatDate(h.checkIn) + " → " + utils.formatDate(h.checkOut));
    if (item.record.hotels.length > 1) parts.push(item.record.hotels.length + " vouchers in this file");
    if (item.record.guestNames.length) parts.push("Guests: " + item.record.guestNames.join(", "));
    return parts.join(" · ");
  }

  function itemTitle(item) {
    if (item.status !== "done") return item.file.name;
    if (item.kind === "passport") {
      var a = item.record.values.applicant;
      var name = [a.firstName, a.lastName].filter(Boolean).join(" ");
      return name || item.file.name;
    }
    return (item.record.hotels[0] && item.record.hotels[0].hotelName) || item.file.name;
  }

  function rowHtml(item, sort) {
    var res = sort.byId[item.id];
    var kindLabel = item.kind === "passport" ? "Passport" : "Hotel voucher";
    var body;
    var badge = "";
    var actions = "";
    var checked = res && res.include ? " checked" : "";
    if (item.status === "done" && res) {
      if (item.kind === "passport") {
        var rb = ROLE_BADGE[res.role] || ROLE_BADGE.unmatched;
        badge = '<span class="' + rb[0] + '">' + rb[1] + "</span>";
        if (res.role !== "main") {
          actions += '<button type="button" class="btn btn-ghost btn-sm" data-ud-make-main="' + item.id + '">Make main applicant</button>';
        }
      } else {
        badge = res.include ? '<span class="badge badge-info">Belongs to this group</span>' : '<span class="badge badge-warning">Not matched to this group</span>';
      }
      var conf = res.confidence && res.confidence !== "none" ? " · match confidence: " + res.confidence : "";
      body =
        '<div class="ud-row__meta">' + utils.escapeHtml(itemMeta(item)) + "</div>" +
        '<div class="ud-row__reason">' + utils.escapeHtml(res.reason) + utils.escapeHtml(conf) + "</div>" +
        (item.record.flags.length ? '<div class="ud-row__flags">Check: ' + utils.escapeHtml(item.record.flags.join("; ")) + "</div>" : "");
    } else if (item.status === "error") {
      badge = '<span class="badge badge-danger">Could not read</span>';
      body = '<div class="ud-row__flags">' + utils.escapeHtml(item.message) + " Remove it and add it again, or enter the details on the page for this document.</div>";
    } else {
      badge = '<span class="badge">' + (item.status === "reading" ? "Reading" : "Waiting") + "</span>";
      body = '<div class="ud-row__meta" data-ud-status>' + utils.escapeHtml(item.message) + "</div>";
    }
    if (item.status !== "reading") {
      actions += '<button type="button" class="btn btn-ghost btn-sm" data-ud-remove="' + item.id + '">Remove</button>';
    }
    var canTick = item.status === "done";
    return (
      '<div class="ud-row" data-ud-item="' + item.id + '">' +
      '<label class="ud-row__tick" title="Include in the generated documents">' +
      '<input type="checkbox" data-ud-include="' + item.id + '"' + checked + (canTick ? "" : " disabled") + ' aria-label="Include ' + utils.escapeHtml(item.file.name) + '" />' +
      "</label>" +
      '<div class="ud-row__body">' +
      '<div class="ud-row__head"><strong>' + utils.escapeHtml(itemTitle(item)) + "</strong>" + badge + "</div>" +
      '<div class="ud-row__file">' + kindLabel + " · " + utils.escapeHtml(item.file.name) + "</div>" +
      body +
      "</div>" +
      '<div class="ud-row__actions">' + actions + "</div>" +
      "</div>"
    );
  }

  function renderResults() {
    var r = root();
    if (!r || !shellBuilt) return;
    var sort = currentSort();
    var box = utils.qs("[data-ud-results]", r);
    var passports = st.items.filter(function (i) { return i.kind === "passport"; });
    var vouchers = st.items.filter(function (i) { return i.kind === "voucher"; });
    var html = "";
    if (!st.items.length) {
      html = '<p class="ud-empty">Nothing uploaded yet. Add passports and hotel vouchers above.</p>';
    } else {
      if (st.mainName.trim() && passports.some(function (p) { return p.status === "done"; }) && !sort.mainPassportId) {
        html += '<p class="ud-warn" role="alert">No passport matches “' + utils.escapeHtml(st.mainName.trim()) +
          '”. Check the spelling, or use “Make main applicant” on the right passport.</p>';
      }
      if (passports.length) html += '<h3 class="ud-group">Passports</h3>' + passports.map(function (i) { return rowHtml(i, sort); }).join("");
      if (vouchers.length) html += '<h3 class="ud-group">Hotel vouchers</h3>' + vouchers.map(function (i) { return rowHtml(i, sort); }).join("");
    }
    box.innerHTML = html;
    var notice = utils.qs("[data-ud-notice]", r);
    if (notice) notice.textContent = st.notice;
    renderDetails();
    refreshReady();
  }

  function renderDetails() {
    var r = root();
    if (!r || !shellBuilt) return;
    var box = utils.qs("[data-ud-details]", r);
    if (!box) return;
    // Don't rebuild while the user is typing in it.
    var wanted = (st.docs.passportAuth ? "p" : "") + (st.docs.companyAuth ? "c" : "") + ((st.docs.cover || st.docs.invitation) ? "h" : "");
    if (box.getAttribute("data-built") === wanted) return;
    box.setAttribute("data-built", wanted);
    var html = "";
    if (st.docs.passportAuth) {
      html +=
        '<div class="ud-details"><h3>Passport Authorization Letter</h3><div class="ud-grid">' +
        field("udPaCentre", "Recipient centre name *", st.passportAuth.centre, "data-ud-pa=\"centre\"", "e.g. visa application centre name") +
        field("udPaAddress", "Recipient address", st.passportAuth.address, "data-ud-pa=\"address\"", "") +
        field("udPaCollector", "Collector name *", st.passportAuth.collector, "data-ud-pa=\"collector\"", "Who collects the passports") +
        "</div></div>";
    }
    if (st.docs.companyAuth) {
      html +=
        '<div class="ud-details"><h3>Company Authorization Letter</h3><div class="ud-grid">' +
        global.KhannaConsulate.comboHtml({ key: "ud-company", id: "udCoCountry", label: "Consulate country", value: st.company.country, required: true }) +
        field("udCoAddress", "Address of Consulate", st.company.address || global.KhannaConsulate.DEFAULT_ADDRESS, "data-ud-co=\"address\"", "") +
        "</div></div>";
    }
    if (st.docs.cover || st.docs.invitation) {
      html += '<p class="field-hint">Cover Letter and Invitation Letter need details that are not on a passport or voucher (consulate, funding, employment …). The people and travel dates are filled in for you, then the page opens so you can complete and generate them there.</p>';
    }
    box.innerHTML = html;
  }

  function field(id, label, value, attr, placeholder) {
    return '<div class="field"><label for="' + id + '">' + label + '</label><input type="text" id="' + id + '" ' + attr +
      ' value="' + utils.escapeHtml(value || "") + '" placeholder="' + utils.escapeHtml(placeholder || "") + '" autocomplete="off" /></div>';
  }

  function problems(sort) {
    var list = [];
    if (!st.mainName.trim()) list.push("Type the main applicant's name.");
    if (st.working || st.items.some(function (i) { return i.status === "queued" || i.status === "reading"; })) list.push("Documents are still being read.");
    if (!st.items.some(function (i) { return i.status === "done"; })) list.push("Upload at least one passport or hotel voucher.");
    if (!DOC_TYPES.some(function (d) { return st.docs[d.key]; })) list.push("Tick at least one document to generate.");
    if (st.generating) list.push("Generating…");
    return list;
  }

  function refreshReady() {
    var r = root();
    if (!r || !shellBuilt) return;
    var sort = currentSort();
    var list = problems(sort);
    var btn = utils.qs("[data-ud-generate]", r);
    var hint = utils.qs("[data-ud-ready]", r);
    if (btn) btn.disabled = list.length > 0;
    if (hint) {
      var np = included("passport", sort).length;
      var nv = included("voucher", sort).length;
      hint.textContent = list.length ? list[0] : np + " passport(s) and " + nv + " hotel voucher(s) will be used.";
    }
  }

  /* ----------------------------------------------------------------------
   * Generate
   * -------------------------------------------------------------------- */

  function userEmail() {
    var u = global.KhannaAuth ? global.KhannaAuth.getCurrentUser() : null;
    return u ? u.email : "";
  }

  function typedNamePatch() {
    var tokens = st.mainName.trim().split(/\s+/);
    var last = tokens.length > 1 ? tokens[tokens.length - 1] : "";
    var first = tokens.length > 1 ? tokens.slice(0, -1).join(" ") : tokens[0] || "";
    return { firstName: first, lastName: last, fullName: st.mainName.trim().replace(/\s+/g, " ") };
  }

  /** Saves the chosen people and hotels into one application (reused if nothing changed). */
  function buildApplication(sort) {
    var S = global.KhannaState;
    var passports = included("passport", sort);
    var vouchers = included("voucher", sort);
    var mainItem = passports.filter(function (i) { return i.id === sort.mainPassportId; })[0] || null;
    var others = passports.filter(function (i) { return i !== mainItem; });

    var signature = JSON.stringify([st.mainName.trim(), mainItem && mainItem.id, others.map(function (i) { return i.id; }), vouchers.map(function (i) { return i.id; })]);
    var existing = st.appId ? S.getApplication(st.appId) : null;
    if (existing && st.appSignature === signature) {
      S.setActiveApplicationId(existing.id);
      return existing;
    }

    var app = S.createApplication(userEmail());
    S.updateApplication(app.id, { applicant: mainItem ? Intake.personPatchFromPassport(mainItem.record) : typedNamePatch() }, "Created from Upload Documents");
    others.forEach(function (item) {
      var t = S.addTraveller(app.id, "");
      S.updateTraveller(app.id, t.id, Intake.personPatchFromPassport(item.record), "Traveller read from an uploaded passport");
    });
    vouchers.forEach(function (item) {
      item.record.hotels.forEach(function (patch) {
        var h = S.addHotel(app.id);
        S.updateHotel(app.id, h.id, patch, "Hotel voucher details extracted");
      });
    });
    // Same hook the Upload Passport page uses: saved people become reusable profiles.
    if (S.syncApplicantProfileFromApplication) S.syncApplicantProfileFromApplication(app.id);
    var fresh = S.getApplication(app.id);
    (fresh.travellers || []).forEach(function (t) {
      if (S.syncTravellerProfileFromApplication) S.syncTravellerProfileFromApplication(app.id, t.id);
    });
    st.appId = app.id;
    st.appSignature = signature;
    return S.getApplication(app.id);
  }

  function personIds(app) {
    return ["applicant"].concat((app.travellers || []).map(function (t) { return t.id; }));
  }

  function applicantLabel(app) {
    var n = [app.applicant.firstName, app.applicant.lastName].filter(Boolean).join(" ");
    return n || "Application";
  }

  function tripDates(app) {
    var ins = (app.hotels || []).map(function (h) { return h.checkIn; }).filter(Boolean).sort();
    var outs = (app.hotels || []).map(function (h) { return h.checkOut; }).filter(Boolean).sort();
    return { start: ins[0] || "", end: outs[outs.length - 1] || "" };
  }

  function needs(reason, page, pageLabel, appId) {
    return { state: "needs", message: reason, page: page, pageLabel: pageLabel, appId: appId };
  }

  /** Runs one document type; resolves {state: "done"|"needs"|"error", ...}. */
  function generateOne(def, app) {
    var S = global.KhannaState;
    var format = st.format;
    var ids = personIds(app);
    var wrap = function (promise, fallbackName) {
      return promise.then(
        function (res) { return { state: "done", blob: res.blob, filename: res.filename || fallbackName }; },
        function (err) { return { state: "error", message: (err && err.message) || "Could not generate this document." }; }
      );
    };

    if (def.key === "hotel") {
      var usable = global.KhannaHotels.completeHotels(app.hotels);
      if (!usable.length) {
        var n = (app.hotels || []).length;
        return Promise.resolve(needs(
          "No hotel voucher is selected.",
          def.page, def.pageLabel, app.id));
      }
      return wrap(api.downloadHotelVoucher(usable, format, applicantLabel(app)), "Hotel_Voucher." + format);
    }

    if (def.key === "passportAuth") {
      if (!st.passportAuth.centre.trim() || !st.passportAuth.collector.trim()) {
        return Promise.resolve(needs("Enter the recipient centre name and the collector name above.", def.page, def.pageLabel, app.id));
      }
      S.updateApplication(app.id, { authorization: { passport: {
        selectedPersonIds: ids,
        recipientCentreName: st.passportAuth.centre.trim(),
        recipientAddress: st.passportAuth.address.trim(),
        collectorName: st.passportAuth.collector.trim(),
      } } }, null);
      return wrapAuth("passport", app.id, format, def);
    }

    if (def.key === "companyAuth") {
      if (!st.company.country) {
        return Promise.resolve(needs("Choose the consulate country above.", def.page, def.pageLabel, app.id));
      }
      var C = global.KhannaConsulate;
      var address = C.addressOrDefault(st.company.address);
      S.updateApplication(app.id, { authorization: { company: {
        selectedPersonIds: ids,
        consulateCountry: st.company.country,
        consulateAddress: address,
        recipientText: C.composeRecipient(C.consulateName(st.company.country), address),
      } } }, null);
      return wrapAuth("company", app.id, format, def);
    }

    if (def.key === "cover") {
      var dates = tripDates(app);
      S.updateApplication(app.id, { coverLetter: { selectedPersonIds: ids, travelStartDate: dates.start, travelEndDate: dates.end } }, null);
      var fresh = S.getApplication(app.id);
      if (global.KhannaCoverLetter.isReady(fresh)) {
        return wrap(global.KhannaCoverLetter.downloadFor(app.id, format), "Cover_Letter." + format);
      }
      return Promise.resolve(needs("Needs the destination country, consulate, funding and other details that are not on a passport or voucher.", def.page, def.pageLabel, app.id));
    }

    // invitation
    S.updateApplication(app.id, { invitation: { selectedInviteeIds: ids } }, null);
    return Promise.resolve(needs("Needs the inviter's details and the consulate, which are not on a passport or voucher.", def.page, def.pageLabel, app.id));
  }

  function wrapAuth(group, appId, format, def) {
    var A = global.KhannaAuthorization;
    return A.downloadFor(appId, group, format).then(
      function (res) { return { state: "done", blob: res.blob, filename: res.filename }; },
      function (err) {
        var message = (err && err.message) || "Could not generate this document.";
        return err && err.notReady ? needs(message, def.page, def.pageLabel, appId) : { state: "error", message: message };
      }
    );
  }

  function generate() {
    var sort = currentSort();
    if (problems(sort).length) return;
    st.generating = true;
    refreshReady();
    var app = buildApplication(sort);
    var defs = DOC_TYPES.filter(function (d) { return st.docs[d.key]; });
    var rows = defs.map(function (d) { return { def: d, state: "pending", message: "" }; });
    openModal(rows, false);

    var chain = Promise.resolve();
    rows.forEach(function (row, idx) {
      chain = chain.then(function () {
        row.state = "running";
        updateModal(rows, false);
        return generateOne(row.def, S().getApplication(app.id)).then(function (res) {
          Object.assign(row, res);
          if (res.state === "done" && res.blob) utils.triggerFileDownload(res.blob, res.filename);
          updateModal(rows, false);
        });
      });
    });
    chain.then(function () {
      st.generating = false;
      updateModal(rows, true);
      refreshReady();
    });
  }

  function S() {
    return global.KhannaState;
  }

  /* ----------------------------------------------------------------------
   * Progress popup (same overlay/dialog styling as the other popups)
   * -------------------------------------------------------------------- */

  var modalEl = null;

  function ensureModal() {
    if (modalEl) return;
    var wrap = document.createElement("div");
    wrap.className = "app-picker-overlay";
    wrap.setAttribute("hidden", "");
    wrap.setAttribute("data-ud-modal", "");
    wrap.innerHTML =
      '<div class="app-picker" role="dialog" aria-modal="true" aria-labelledby="udModalTitle" style="max-width:520px;">' +
      '<div class="app-picker__header"><h3 id="udModalTitle" data-ud-modal-title>Generating documents…</h3></div>' +
      '<div data-ud-modal-body role="status" aria-live="polite"></div>' +
      '<div style="display:flex;justify-content:flex-end;"><button type="button" class="btn btn-primary btn-sm" data-ud-modal-close disabled>Close</button></div>' +
      "</div>";
    document.body.appendChild(wrap);
    modalEl = wrap;
    utils.on(wrap, "click", "[data-ud-modal-close]", function (e, btn) {
      if (!btn.disabled) wrap.setAttribute("hidden", "");
    });
    utils.on(wrap, "click", "[data-ud-open-page]", function (e, a) {
      var appId = a.getAttribute("data-app-id");
      var page = a.getAttribute("data-ud-open-page");
      wrap.setAttribute("hidden", "");
      if (appId) global.KhannaState.setActiveApplicationId(appId);
      if (global.KhannaRouter) global.KhannaRouter.navigate(page);
    });
    utils.on(wrap, "click", "[data-ud-redownload]", function (e, a) {
      var row = modalRows[Number(a.getAttribute("data-ud-redownload"))];
      if (row && row.blob) utils.triggerFileDownload(row.blob, row.filename);
    });
  }

  var modalRows = [];

  function openModal(rows) {
    ensureModal();
    modalRows = rows;
    modalEl.removeAttribute("hidden");
    updateModal(rows, false);
  }

  function rowStatusHtml(row, i) {
    var label = row.def.label;
    if (row.state === "pending") return '<li class="ud-job"><span class="badge">Waiting</span> ' + label + "</li>";
    if (row.state === "running") return '<li class="ud-job"><span class="badge badge-info">Generating…</span> ' + label + " is being generated…</li>";
    if (row.state === "done") {
      return '<li class="ud-job"><span class="badge badge-success">Done</span> ' + label + " — generated" +
        ' <button type="button" class="btn btn-ghost btn-sm" data-ud-redownload="' + i + '">Download again</button></li>';
    }
    if (row.state === "needs") {
      return '<li class="ud-job"><span class="badge badge-warning">Needs details</span> ' + label + ": " + utils.escapeHtml(row.message) +
        ' <button type="button" class="btn btn-secondary btn-sm" data-ud-open-page="' + row.page + '" data-app-id="' + row.appId + '">Open ' + row.pageLabel + "</button></li>";
    }
    return '<li class="ud-job"><span class="badge badge-danger">Failed</span> ' + label + ": " + utils.escapeHtml(row.message) + "</li>";
  }

  function updateModal(rows, finished) {
    if (!modalEl) return;
    modalEl.querySelector("[data-ud-modal-body]").innerHTML = '<ul class="ud-jobs">' + rows.map(rowStatusHtml).join("") + "</ul>";
    var title = modalEl.querySelector("[data-ud-modal-title]");
    var closeBtn = modalEl.querySelector("[data-ud-modal-close]");
    if (finished) {
      var allDone = rows.every(function (r) { return r.state === "done"; });
      title.textContent = allDone ? "Documents generated" : "Finished — some documents need attention";
      closeBtn.disabled = false;
    } else {
      title.textContent = "Generating documents…";
      closeBtn.disabled = true;
    }
  }

  /* ----------------------------------------------------------------------
   * Wiring
   * -------------------------------------------------------------------- */

  function build() {
    var r = root();
    if (!r || shellBuilt) return;
    r.innerHTML = shellHtml();
    shellBuilt = true;
    utils.qs("[data-ud-format]", r).value = st.format;
    utils.qs("[data-ud-main-name]", r).value = st.mainName;

    utils.on(r, "input", "[data-ud-main-name]", function (e, input) {
      st.mainName = input.value;
      st.mainOverride = null; // a new name means the earlier manual pick no longer applies
      renderResults();
    });
    utils.on(r, "change", "[data-ud-file]", function (e, input) {
      addFiles(input.getAttribute("data-ud-file"), input.files);
      input.value = "";
    });
    ["dragover", "dragleave", "drop"].forEach(function (type) {
      r.addEventListener(type, function (e) {
        var zone = e.target.closest && e.target.closest("[data-ud-drop]");
        if (!zone) return;
        e.preventDefault();
        zone.classList.toggle("is-over", type === "dragover");
        if (type === "drop") addFiles(zone.getAttribute("data-ud-drop"), e.dataTransfer && e.dataTransfer.files);
      });
    });
    utils.on(r, "change", "[data-ud-include]", function (e, box) {
      st.includeOverride[box.getAttribute("data-ud-include")] = box.checked;
      renderResults();
    });
    utils.on(r, "click", "[data-ud-remove]", function (e, btn) {
      removeItem(btn.getAttribute("data-ud-remove"));
    });
    utils.on(r, "click", "[data-ud-make-main]", function (e, btn) {
      var id = btn.getAttribute("data-ud-make-main");
      st.mainOverride = id;
      // The chosen passport is the main applicant by definition: include it.
      st.includeOverride[id] = true;
      renderResults();
    });
    utils.on(r, "change", "[data-ud-doc]", function (e, box) {
      st.docs[box.getAttribute("data-ud-doc")] = box.checked;
      renderDetails();
      refreshReady();
    });
    utils.on(r, "change", "[data-ud-format]", function (e, sel) {
      st.format = sel.value;
    });
    utils.on(r, "input", "[data-ud-pa]", function (e, input) {
      st.passportAuth[input.getAttribute("data-ud-pa")] = input.value;
    });
    utils.on(r, "input", "[data-ud-co]", function (e, input) {
      st.company[input.getAttribute("data-ud-co")] = input.value;
    });
    global.KhannaConsulate.wire(r, function (key, country) {
      if (key === "ud-company") st.company.country = country;
    });
    utils.on(r, "click", "[data-ud-generate]", generate);
    renderResults();
  }

  function init() {
    document.addEventListener("khanna:navigate", function (e) {
      if (e.detail.view !== "upload-documents") return;
      build();
      renderResults();
    });
    if (location.hash.indexOf("upload-documents") !== -1) build();
  }

  global.KhannaUploadDocuments = { build: build };

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})(window);
