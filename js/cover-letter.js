/* ==========================================================================
   Khanna Travels & Holidays — Cover Letter tab (wizard step 6, second half)
   Phase 9. Generates the three real, region-specific Khanna Travels &
   Holidays Tourist Visa Cover Letters (Europe / Japan / Singapore), each
   calling the real backend engine (backend/python/cover_letter_engine.py)
   to fill the actual, unmodified reference template (project rule 5) — not
   a recreation.

   Mounts inside the `[data-auth-tab-panel="cover"]` panel that
   authorization.js's mountSkeleton() builds (a single `<div
   data-cover-letter-root>` placeholder there) — this module owns
   everything inside that placeholder, the same way documents.js/hotels.js
   own their own step roots. Person data (applicant + every traveller,
   flattened to a person row) is reused from authorization.js's own
   `global.KhannaAuthorization` export rather than re-derived here (project
   rule 15).

   Real-person-count limits, enforced both in the UI (checkbox caps, exactly
   like Passport Authorization's own 1-2 cap in authorization.js) and by the
   backend itself: Europe and Japan each require the applicant plus exactly
   one companion (their own reference templates' fixed sentences assume
   exactly one); Singapore accepts the applicant alone or with any number of
   companions.

   Re-render discipline (same reasoning as authorization.js's own file
   header): the person checklist and Generate bar redraw freely on every
   KhannaState change. The rest of the per-region card — every text field,
   the Japan hotel-table editor, the Singapore per-person occupation list —
   only rebuilds on a real "entering this step" navigation, or immediately
   after an explicit action taken IN THIS PANEL that changes its own shape
   (switching region, selecting/deselecting a person, adding/removing a
   hotel row) — never from an unrelated background state change elsewhere
   in the app, so a staff member's in-progress typing is never silently
   overwritten. A click that lands on a checkbox or button always commits
   any pending text-field edit first (the browser fires that field's own
   "change"/blur event before the click's own handler runs), so rebuilding
   right after those explicit actions never loses unsaved input.
   ========================================================================== */
(function (global) {
  "use strict";

  var utils = global.KhannaUtils;
  var api = global.KhannaApi;

  var REGIONS = ["Europe", "Japan", "Singapore"];

  // Document-first redesign (Phase 2): dual-mount. In the wizard this still
  // resolves to the sub-root authorization.js's own mountSkeleton() creates
  // inside its "Cover Letter" tab (unchanged — authorization.js still
  // drives render() for that case, see its own render()). On the
  // standalone Cover Letter page there is no authorization.js involved at
  // all, so this module gets its own root and its own navigate listener
  // below instead.
  function root() {
    var view = global.KhannaRouter ? global.KhannaRouter.parseHash().view : null;
    if (view === "cover-letter") return utils.qs("[data-cover-letter-page-root]");
    return utils.qs("[data-cover-letter-root]");
  }

  function getApp() {
    return global.KhannaState.getActiveApplication();
  }

  function authHelpers() {
    return global.KhannaAuthorization;
  }

  /* ---------------------------------------------------------------------
   * Person selection
   * ------------------------------------------------------------------- */

  function coverState(app) {
    return (app && app.coverLetter) || {};
  }

  function selectedPeople(app) {
    var auth = authHelpers();
    if (!auth) return [];
    var state = coverState(app);
    var ids = state.selectedPersonIds || [];
    return auth.getSelectablePeople(app).filter(function (p) {
      return ids.indexOf(p.id) !== -1;
    });
  }

  function maxPeopleFor(region) {
    return region === "Singapore" ? null : 2;
  }

  /* ---------------------------------------------------------------------
   * Readiness — mirrors authorization.js's passportReadiness/companyReadiness
   * ------------------------------------------------------------------- */

  function isReady(app) {
    var auth = authHelpers();
    if (!app || !auth) return false;
    var state = coverState(app);
    var region = state.region;
    if (!region) return false;

    var selected = selectedPeople(app);
    var applicantSelected = selected.some(function (p) {
      return p.isApplicant;
    });
    if (!applicantSelected || !selected.every(auth.personHasCoreFields)) return false;

    var commonOk =
      !!(state.recipientText && state.recipientText.trim()) &&
      !!state.travelStartDate &&
      !!state.travelEndDate &&
      !!(state.fundingArrangement && state.fundingArrangement.trim());
    if (region !== "Singapore") {
      commonOk = commonOk && !!(state.destinationCountry && state.destinationCountry.trim());
    }
    if (!commonOk) return false;

    if (region === "Europe") {
      if (selected.length !== 2) return false;
      var e = state.europe || {};
      return [
        "cityCountryOfResidence",
        "numberOfNights",
        "applicantEmploymentStatus",
        "applicantJobTitle",
        "applicantEmployerName",
        "companionJobTitle",
        "companionEmployerName",
        "companionEmploymentStartYear",
      ].every(function (key) {
        return !!(e[key] && String(e[key]).trim());
      });
    }

    if (region === "Japan") {
      if (selected.length !== 2) return false;
      var j = state.japan || {};
      return !!(j.applicantEmployerOccupation && j.applicantEmployerOccupation.trim()) && !!(j.companionOccupation && j.companionOccupation.trim());
    }

    if (region === "Singapore") {
      if (selected.length < 1) return false;
      var s = state.singapore || {};
      return !!(s.hotelName && s.hotelName.trim()) && !!(s.hotelAddress && s.hotelAddress.trim());
    }

    return false;
  }

  /* ---------------------------------------------------------------------
   * Rendering — region selector
   * ------------------------------------------------------------------- */

  function regionSelectorHtml(region) {
    return (
      '<div class="cover-region-select" role="radiogroup" aria-label="Cover letter region">' +
      REGIONS.map(function (r) {
        return (
          '<button type="button" class="cover-region-btn' +
          (region === r ? " is-active" : "") +
          '" data-cover-region="' +
          r +
          '" aria-pressed="' +
          (region === r ? "true" : "false") +
          '">' +
          r +
          "</button>"
        );
      }).join("") +
      "</div>"
    );
  }

  /* ---------------------------------------------------------------------
   * Rendering — person checklist (same shape as authorization.js's own)
   * ------------------------------------------------------------------- */

  function checklistHtml(app, region) {
    var auth = authHelpers();
    var people = auth ? auth.getSelectablePeople(app) : [];
    if (!people.length) {
      return '<p class="field-hint">Add the applicant and/or travellers in earlier steps first.</p>';
    }
    var state = coverState(app);
    var selectedIds = state.selectedPersonIds || [];
    var maxCount = maxPeopleFor(region);
    return people
      .map(function (p) {
        var checked = selectedIds.indexOf(p.id) !== -1;
        var atMax = !!maxCount && !checked && selectedIds.length >= maxCount;
        var incomplete = !auth.personHasCoreFields(p);
        return (
          '<label class="auth-person-row' + (atMax ? " is-disabled" : "") + '">' +
          '<input type="checkbox" data-cover-person data-person-id="' + utils.escapeHtml(p.id) + '"' +
          (checked ? " checked" : "") +
          (atMax ? " disabled" : "") +
          " />" +
          '<span class="auth-person-row__name">' + utils.escapeHtml(auth.personDisplayName(p)) + "</span>" +
          '<span class="auth-person-row__meta">' +
          utils.escapeHtml(p.relationLabel) +
          (incomplete ? " · missing name or passport number" : "") +
          "</span>" +
          "</label>"
        );
      })
      .join("");
  }

  function refreshChecklist() {
    var app = getApp();
    var box = utils.qs("[data-cover-checklist]", root());
    if (!app || !box) return;
    box.innerHTML = checklistHtml(app, coverState(app).region);
  }

  /* ---------------------------------------------------------------------
   * Rendering — generate bar + readiness notice + error box
   * ------------------------------------------------------------------- */

  function generateBarHtml(ready, generatedAt) {
    return (
      '<div class="hotel-generate-bar">' +
      '<button class="btn btn-primary btn-sm" type="button" data-action="generate-cover-letter"' +
      (ready ? "" : " disabled") +
      ">Generate &amp; Preview</button>" +
      (generatedAt ? '<span class="hotel-generate-bar__meta">Last generated ' + utils.formatDate(generatedAt) + "</span>" : "") +
      "</div>"
    );
  }

  function refreshGenerateBar() {
    var app = getApp();
    var box = utils.qs("[data-cover-generate-bar]", root());
    if (!app || !box) return;
    var state = coverState(app);
    box.innerHTML = generateBarHtml(isReady(app), state.generatedAt);
  }

  function readinessMessage(region) {
    if (region === "Europe" || region === "Japan") {
      return (
        "Select the applicant plus exactly one companion (matching " +
        region +
        "'s own fixed letter wording, each with a name and passport number on file), and fill in every required field above to generate this letter."
      );
    }
    if (region === "Singapore") {
      return "Select the applicant (with a name and passport number on file), any travelling companions, and fill in every required field above to generate this letter.";
    }
    return "Choose a region to begin.";
  }

  function refreshReadinessNotice() {
    var app = getApp();
    var box = utils.qs("[data-cover-readiness]", root());
    if (!app || !box) return;
    var region = coverState(app).region;
    if (!region || isReady(app)) {
      box.innerHTML = "";
      return;
    }
    box.innerHTML =
      '<div class="notice notice-warning">' +
      '<svg class="icon icon-sm" viewBox="0 0 24 24"><path d="M12 9v4M12 17h.01"/><circle cx="12" cy="12" r="9"/></svg>' +
      "<span>" + utils.escapeHtml(readinessMessage(region)) + "</span>" +
      "</div>";
  }

  function showError(message) {
    var box = utils.qs("[data-cover-error]", root());
    if (!box) return;
    box.innerHTML = message
      ? '<div class="notice notice-danger">' +
        '<svg class="icon icon-sm" viewBox="0 0 24 24"><path d="M12 9v4M12 17h.01"/><circle cx="12" cy="12" r="9"/></svg>' +
        "<span>" + utils.escapeHtml(message) + "</span>" +
        "</div>"
      : "";
  }

  /* ---------------------------------------------------------------------
   * Rendering — the per-region card (full rebuild; see file header for
   * when this is and isn't called)
   * ------------------------------------------------------------------- */

  function fieldRowHtml(scope, key, label, value, required, opts) {
    opts = opts || {};
    var id = "cover-" + scope.replace(":", "-") + "-" + key;
    return (
      '<div class="field">' +
      '<label for="' + id + '">' + utils.escapeHtml(label) + (required ? " *" : "") + "</label>" +
      '<input type="' + (opts.type || "text") + '" id="' + id + '" data-cover-field="' + scope + ":" + key + '"' +
      (opts.placeholder ? ' placeholder="' + utils.escapeHtml(opts.placeholder) + '"' : "") +
      ' value="' + utils.escapeHtml(value || "") + '" />' +
      "</div>"
    );
  }

  function commonFieldsHtml(state, region) {
    var rows =
      fieldRowHtml("top", "recipientText", "Consulate name & address", state.recipientText, true, {
        placeholder: "e.g. The Consulate General of France, Mumbai",
      }) +
      (region === "Singapore"
        ? ""
        : fieldRowHtml("top", "destinationCountry", "Destination country", state.destinationCountry, true)) +
      fieldRowHtml("top", "travelStartDate", "Travel start date", state.travelStartDate, true, { type: "date" }) +
      fieldRowHtml("top", "travelEndDate", "Travel end date", state.travelEndDate, true, { type: "date" }) +
      fieldRowHtml("top", "fundingArrangement", "Travel expenses funded by", state.fundingArrangement, true, {
        placeholder: "e.g. Applicant",
      });
    return '<div class="field-grid">' + rows + "</div>";
  }

  function europeFieldsHtml(state) {
    var e = state.europe || {};
    return (
      '<div class="field-grid">' +
      fieldRowHtml("europe", "cityCountryOfResidence", "City, country of residence", e.cityCountryOfResidence, true, {
        placeholder: "e.g. Mumbai, India",
      }) +
      fieldRowHtml("europe", "numberOfNights", "Number of nights", e.numberOfNights, true, { placeholder: "e.g. 10 nights" }) +
      fieldRowHtml("europe", "applicantEmploymentStatus", "Applicant employment status", e.applicantEmploymentStatus, true, {
        placeholder: "e.g. Salaried",
      }) +
      fieldRowHtml("europe", "applicantJobTitle", "Applicant job title", e.applicantJobTitle, true) +
      fieldRowHtml("europe", "applicantEmployerName", "Applicant employer", e.applicantEmployerName, true) +
      fieldRowHtml("europe", "companionJobTitle", "Companion job title", e.companionJobTitle, true) +
      fieldRowHtml("europe", "companionEmployerName", "Companion employer", e.companionEmployerName, true) +
      fieldRowHtml("europe", "companionEmploymentStartYear", "Companion employed since (year)", e.companionEmploymentStartYear, true) +
      "</div>" +
      "<p class=\"field-hint\">The fields below are optional — fill them in only if this trip also continues to a second country.</p>" +
      '<div class="field-grid">' +
      fieldRowHtml("europe", "nextCountry", "Next country (optional)", e.nextCountry, false) +
      fieldRowHtml("europe", "nextTravelStartDate", "Next country — start date", e.nextTravelStartDate, false, { type: "date" }) +
      fieldRowHtml("europe", "nextTravelEndDate", "Next country — end date", e.nextTravelEndDate, false, { type: "date" }) +
      fieldRowHtml("europe", "nextNumberOfNights", "Next country — number of nights", e.nextNumberOfNights, false) +
      "</div>"
    );
  }

  function japanHotelRowHtml(hotel) {
    return (
      '<div class="cover-hotel-row" data-hotel-id="' + utils.escapeHtml(hotel.id) + '">' +
      '<div class="field-grid">' +
      '<div class="field"><label>Hotel name</label><input type="text" data-cover-hotel-field="name" value="' +
      utils.escapeHtml(hotel.name || "") +
      '" /></div>' +
      '<div class="field"><label>Check-in</label><input type="date" data-cover-hotel-field="checkIn" value="' +
      utils.escapeHtml(hotel.checkIn || "") +
      '" /></div>' +
      '<div class="field"><label>Check-out</label><input type="date" data-cover-hotel-field="checkOut" value="' +
      utils.escapeHtml(hotel.checkOut || "") +
      '" /></div>' +
      '<div class="field"><label>Contact no.</label><input type="text" data-cover-hotel-field="contactNo" value="' +
      utils.escapeHtml(hotel.contactNo || "") +
      '" /></div>' +
      "</div>" +
      '<button type="button" class="btn btn-ghost btn-sm cover-hotel-row__remove" data-action="remove-cover-hotel" data-hotel-id="' +
      utils.escapeHtml(hotel.id) +
      '">Remove hotel</button>' +
      "</div>"
    );
  }

  function japanFieldsHtml(state) {
    var j = state.japan || {};
    var hotels = j.hotels || [];
    return (
      '<div class="field-grid">' +
      fieldRowHtml("japan", "applicantEmployerOccupation", "Applicant employer / occupation", j.applicantEmployerOccupation, true, {
        placeholder: "e.g. Software Engineer at Acme Corp",
      }) +
      fieldRowHtml("japan", "companionOccupation", "Companion occupation", j.companionOccupation, true) +
      "</div>" +
      '<h4 class="cover-subheading">Hotels in Japan (optional)</h4>' +
      '<div class="cover-hotel-list">' +
      (hotels.length ? hotels.map(japanHotelRowHtml).join("") : '<p class="field-hint">No hotels added yet.</p>') +
      "</div>" +
      '<button type="button" class="btn btn-secondary btn-sm" data-action="add-cover-hotel">+ Add hotel</button>'
    );
  }

  function singaporeFieldsHtml(state, selected) {
    var s = state.singapore || {};
    var occupations = s.occupations || {};
    var occupationRows = selected.length
      ? selected
          .map(function (p) {
            var auth = authHelpers();
            return (
              '<div class="field">' +
              "<label>" + utils.escapeHtml(auth.personDisplayName(p)) + " — occupation</label>" +
              '<input type="text" data-cover-occupation="' + utils.escapeHtml(p.id) + '" value="' +
              utils.escapeHtml(occupations[p.id] || "") +
              '" /></div>'
            );
          })
          .join("")
      : '<p class="field-hint">Select at least the applicant above to enter occupations.</p>';
    return (
      '<div class="field-grid">' +
      fieldRowHtml("singapore", "hotelName", "Hotel name", s.hotelName, true) +
      fieldRowHtml("singapore", "hotelAddress", "Hotel address", s.hotelAddress, true) +
      "</div>" +
      '<h4 class="cover-subheading">Occupations (optional)</h4>' +
      '<div class="field-grid">' + occupationRows + "</div>"
    );
  }

  function regionBodyHtml(app, state, region) {
    var selected = selectedPeople(app);
    var body = '<div class="auth-person-list" data-cover-checklist>' + checklistHtml(app, region) + "</div>";
    body += commonFieldsHtml(state, region);
    if (region === "Europe") body += europeFieldsHtml(state);
    else if (region === "Japan") body += japanFieldsHtml(state);
    else if (region === "Singapore") body += singaporeFieldsHtml(state, selected);
    body += '<div data-cover-readiness></div><div data-cover-generate-bar></div><div data-cover-error></div>';
    return body;
  }

  function renderCard() {
    var app = getApp();
    var box = utils.qs("[data-cover-letter-card]", root());
    if (!app || !box) return;
    var state = coverState(app);
    var region = state.region || "";
    box.innerHTML = region
      ? regionBodyHtml(app, state, region)
      : '<p class="field-hint">Choose Europe, Japan or Singapore above to start this cover letter.</p>';
    refreshGenerateBar();
    refreshReadinessNotice();
  }

  /* ---------------------------------------------------------------------
   * Generation
   * ------------------------------------------------------------------- */

  function buildPayload(app, format) {
    var auth = authHelpers();
    var state = coverState(app);
    var region = state.region;
    var selected = auth.orderPeopleForLetter(selectedPeople(app));
    var occupations = (state.singapore && state.singapore.occupations) || {};

    var people = selected.map(function (p) {
      return {
        id: p.id,
        salutation: p.salutation || "",
        fullName: p.fullName || "",
        passportNumber: p.passportNumber || "",
        placeOfIssue: p.placeOfIssue || "",
        passportIssueDate: p.passportIssueDate || "",
        relationToApplicant: p.isApplicant ? "" : p.relation || "",
        sex: p.sex || "",
        phone: p.phone || "",
        email: p.email || "",
        isApplicant: !!p.isApplicant,
        occupation: region === "Singapore" ? occupations[p.id] || "" : "",
      };
    });

    var applicantName = [app.applicant.firstName, app.applicant.lastName].filter(Boolean).join(" ") || "Application";

    var payload = {
      region: region,
      people: people,
      recipientText: state.recipientText || "",
      destinationCountry: state.destinationCountry || "",
      travelStartDate: state.travelStartDate || "",
      travelEndDate: state.travelEndDate || "",
      fundingArrangement: state.fundingArrangement || "",
      format: format,
      applicantName: applicantName,
    };

    if (region === "Europe") {
      var e = state.europe || {};
      Object.assign(payload, {
        cityCountryOfResidence: e.cityCountryOfResidence || "",
        numberOfNights: e.numberOfNights || "",
        applicantEmploymentStatus: e.applicantEmploymentStatus || "",
        applicantJobTitle: e.applicantJobTitle || "",
        applicantEmployerName: e.applicantEmployerName || "",
        companionJobTitle: e.companionJobTitle || "",
        companionEmployerName: e.companionEmployerName || "",
        companionEmploymentStartYear: e.companionEmploymentStartYear || "",
        nextCountry: e.nextCountry || "",
        nextTravelStartDate: e.nextTravelStartDate || "",
        nextTravelEndDate: e.nextTravelEndDate || "",
        nextNumberOfNights: e.nextNumberOfNights || "",
      });
    } else if (region === "Japan") {
      var j = state.japan || {};
      payload.applicantEmployerOccupation = j.applicantEmployerOccupation || "";
      payload.companionOccupation = j.companionOccupation || "";
      payload.hotels = (j.hotels || []).map(function (h) {
        return { name: h.name || "", checkIn: h.checkIn || "", checkOut: h.checkOut || "", contactNo: h.contactNo || "" };
      });
    } else if (region === "Singapore") {
      var s = state.singapore || {};
      payload.hotelName = s.hotelName || "";
      payload.hotelAddress = s.hotelAddress || "";
    }

    return payload;
  }

  // Keyed by root element — this module dual-mounts (wizard root vs. the
  // standalone Cover Letter page root; see root() above), same hazard
  // hotels.js's own viewerHandles WeakMap already guards against.
  var viewerHandles = new WeakMap();

  function generate(btn) {
    var app = getApp();
    if (!app || !isReady(app)) return;
    showError("");
    var r = root();
    if (!r) return;
    var previewBox = utils.qs("[data-doc-preview]", r);
    if (!previewBox) return;

    var handle = viewerHandles.get(r);
    if (!handle) {
      handle = global.KhannaDocumentViewer.mount(previewBox, {
        title: "Cover Letter",
        loadPdf: function () {
          var a = getApp();
          return api.downloadCoverLetter(buildPayload(a, "pdf"));
        },
        loadDocx: function () {
          var a = getApp();
          return api.downloadCoverLetter(buildPayload(a, "docx"));
        },
        onEdit: function () {
          var box = utils.qs("[data-cover-letter-card]", root());
          if (box) box.scrollIntoView({ behavior: "smooth", block: "start" });
        },
        onRegenerate: function () {
          return Promise.resolve();
        },
      });
      viewerHandles.set(r, handle);
    }

    var originalText = btn.textContent;
    btn.disabled = true;
    btn.textContent = "Generating…";
    var region = coverState(app).region;
    handle
      .refresh()
      .then(function () {
        var ts = new Date().toISOString();
        global.KhannaState.updateApplication(app.id, { coverLetter: { generatedAt: ts } }, region + " Cover Letter generated");
      })
      .catch(function (err) {
        showError((err && err.message) || "Could not generate the cover letter.");
      })
      .finally(function () {
        btn.disabled = false;
        btn.textContent = originalText;
      });
  }

  /* ---------------------------------------------------------------------
   * Skeleton, wiring
   * ------------------------------------------------------------------- */

  function mountSkeleton() {
    var r = root();
    if (!r) return;
    var app = getApp();
    var region = coverState(app).region || "";
    r.innerHTML =
      '<div class="card">' +
      "<h3>Cover Letter</h3>" +
      "<p>Choose the destination region — the letter's wording, required fields and person limits all come from that region's own real reference template.</p>" +
      '<div data-cover-region-select>' + regionSelectorHtml(region) + "</div>" +
      '<div data-cover-letter-card></div>' +
      "</div>" +
      // Deliberately a SIBLING of [data-cover-letter-card], not nested
      // inside it: renderCard() replaces that card's entire innerHTML on
      // every region change and person-selection change (see renderCard()
      // callers below), which would otherwise destroy a mounted preview on
      // any such edit. Living one level up here, it only remounts fresh on
      // a full mountSkeleton() (a real navigation), matching hotels.js's/
      // authorization.js's own "preview div lives outside the part that
      // rebuilds on every edit" placement.
      '<div data-doc-preview style="margin-top:var(--space-4);"></div>';

    utils.on(r, "click", "[data-cover-region]", function (e, target) {
      var current = getApp();
      if (!current) return;
      var newRegion = target.getAttribute("data-cover-region");
      global.KhannaState.updateApplication(current.id, { coverLetter: { region: newRegion } }, null);
      utils.qs("[data-cover-region-select]", r).innerHTML = regionSelectorHtml(newRegion);
      renderCard();
      if (global.KhannaRouter) global.KhannaRouter.refreshWizardFooter();
    });

    utils.on(r, "change", "[data-cover-person]", function (e, target) {
      var current = getApp();
      if (!current) return;
      var state = coverState(current);
      var maxCount = maxPeopleFor(state.region);
      var ids = (state.selectedPersonIds || []).slice();
      var personId = target.getAttribute("data-person-id");
      var idx = ids.indexOf(personId);
      if (target.checked) {
        if (idx === -1) {
          if (maxCount && ids.length >= maxCount) {
            target.checked = false; // guard, in addition to the disabled attribute
            return;
          }
          ids.push(personId);
        }
      } else if (idx !== -1) {
        ids.splice(idx, 1);
      }
      global.KhannaState.updateApplication(current.id, { coverLetter: { selectedPersonIds: ids } }, null);
      // Selecting/deselecting a person is an explicit action taken in this
      // panel, and Singapore's per-person occupation fields (and the
      // checklist's own disabled/checked state) depend directly on this
      // list — a full card rebuild here is correct, not a background
      // overwrite (see file header).
      renderCard();
      if (global.KhannaRouter) global.KhannaRouter.refreshWizardFooter();
    });

    utils.on(r, "change", "[data-cover-field]", function (e, target) {
      var current = getApp();
      if (!current) return;
      var parts = target.getAttribute("data-cover-field").split(":");
      var scope = parts[0];
      var key = parts[1];
      var patch = { coverLetter: {} };
      if (scope === "top") {
        patch.coverLetter[key] = target.value;
      } else {
        patch.coverLetter[scope] = {};
        patch.coverLetter[scope][key] = target.value;
      }
      global.KhannaState.updateApplication(current.id, patch, null);
      if (global.KhannaRouter) global.KhannaRouter.refreshWizardFooter();
    });

    utils.on(r, "change", "[data-cover-occupation]", function (e, target) {
      var current = getApp();
      if (!current) return;
      var personId = target.getAttribute("data-cover-occupation");
      var patch = { coverLetter: { singapore: { occupations: {} } } };
      patch.coverLetter.singapore.occupations[personId] = target.value;
      global.KhannaState.updateApplication(current.id, patch, null);
    });

    utils.on(r, "change", "[data-cover-hotel-field]", function (e, target) {
      var current = getApp();
      if (!current) return;
      var row = target.closest("[data-hotel-id]");
      if (!row) return;
      var hotelId = row.getAttribute("data-hotel-id");
      var key = target.getAttribute("data-cover-hotel-field");
      var state = coverState(current);
      var hotels = ((state.japan || {}).hotels || []).map(function (h) {
        if (h.id !== hotelId) return h;
        var updated = Object.assign({}, h);
        updated[key] = target.value;
        return updated;
      });
      global.KhannaState.updateApplication(current.id, { coverLetter: { japan: { hotels: hotels } } }, null);
    });

    utils.on(r, "click", "[data-action='add-cover-hotel']", function () {
      var current = getApp();
      if (!current) return;
      var state = coverState(current);
      var hotels = ((state.japan || {}).hotels || []).concat([global.KhannaState.createEmptyCoverLetterHotel()]);
      global.KhannaState.updateApplication(current.id, { coverLetter: { japan: { hotels: hotels } } }, "Cover Letter hotel added");
      renderCard();
    });

    utils.on(r, "click", "[data-action='remove-cover-hotel']", function (e, target) {
      var current = getApp();
      if (!current) return;
      var hotelId = target.getAttribute("data-hotel-id");
      var state = coverState(current);
      var hotels = ((state.japan || {}).hotels || []).filter(function (h) {
        return h.id !== hotelId;
      });
      global.KhannaState.updateApplication(current.id, { coverLetter: { japan: { hotels: hotels } } }, "Cover Letter hotel removed");
      renderCard();
    });

    utils.on(r, "click", "[data-action='generate-cover-letter']", function (e, target) {
      if (target.disabled) return;
      generate(target);
    });
  }

  function render() {
    var r = root();
    if (!r) return;
    // Same reasoning as hotels.js's own render(): the wizard is never
    // entered without an active application, so this only ever matters for
    // the standalone Cover Letter page, which can be opened directly with
    // none yet. Left unmounted (not dataset.mounted) so the real skeleton
    // still mounts the next time render() runs with an application active.
    if (!getApp()) {
      // See hotels.js's own render() for why this also clears a stale
      // dataset.mounted flag, not just the placeholder text.
      delete r.dataset.mounted;
      r.innerHTML = '<p class="field-hint">Create or continue an application above to start a cover letter.</p>';
      return;
    }
    if (!r.dataset.mounted) {
      r.dataset.mounted = "1";
      mountSkeleton();
    }
    renderCard();
  }

  function init() {
    // Only the checklist + generate bar + readiness notice react to every
    // background state change — never the text fields, hotel rows or
    // occupation rows (see file header).
    global.KhannaState.subscribe(function () {
      var r = root();
      if (!r || !r.dataset.mounted) return;
      refreshChecklist();
      refreshGenerateBar();
      refreshReadinessNotice();
    });

    // Standalone Cover Letter page (Phase 2): the wizard case is still
    // driven by authorization.js's own render() calling
    // global.KhannaCoverLetter.render() directly — this listener only ever
    // fires for the new standalone view, so it's additive and changes
    // nothing about how the wizard already works.
    document.addEventListener("khanna:navigate", function (e) {
      if (e.detail.view === "cover-letter") render();
    });
    if (location.hash.indexOf("cover-letter") !== -1) render();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }

  global.KhannaCoverLetter = {
    render: render,
    isReady: isReady,
  };
})(window);
