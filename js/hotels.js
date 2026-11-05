/* ==========================================================================
   Khanna Travels & Holidays — Hotel blocking (wizard step 5)
   Data entry for every hotel booked/blocked on this application, plus a
   real "Generate Hotel Voucher" action that calls the backend
   (backend/python/hotel_voucher_engine.py) to produce the actual company
   Hotel Voucher document — built from the real, unmodified reference
   template in reference-hotel-blocking-formats/, not a recreation (project
   rule 5). Supports any number of hotels: the backend clones the template's
   own heading+table block once per hotel, exactly matching how the real
   "Multiple Hotels" reference example itself repeats that block.

   Re-render discipline (same as travellers.js/documents.js): the hotel
   LIST redraws on every state change; the open EDIT PANEL only opens,
   closes or swaps on an explicit user action.
   ========================================================================== */
(function (global) {
  "use strict";

  var utils = global.KhannaUtils;
  var api = global.KhannaApi;

  // Phase 4 (document-first redesign) fix: "which hotel's panel is open" used
  // to be ONE shared module-level variable. That was safe when only a single
  // root (the wizard's step-5 root) could ever exist — but Phase 2 made this
  // controller dual-mount onto a SECOND, independent root (the standalone
  // Hotel Blocking page), and both can be mounted (and keep their own stale
  // DOM/listeners) at the same time. With one shared variable, opening a
  // hotel's panel on the wizard and then switching to the standalone page
  // (which may still be showing a DIFFERENT hotel's panel from an earlier
  // visit, never cleared on navigation) meant editing what looked like hotel
  // B's fields there could silently write to hotel A's record instead — the
  // exact same cross-record-corruption bug class the original build's own
  // Phase 13 hit once already (there, from a re-wired listener; here, from
  // shared state across two simultaneously-mounted roots). Found by
  // reasoning about this file's own historical bug comment below in light of
  // Phase 2's dual-mount change, then confirmed with a dedicated regression
  // test before this fix (see phase4_test.py).
  //
  // Fix: track the open hotel id PER ROOT (as a data attribute on that root
  // element) instead of in one shared variable, via getActiveHotelId(r)/
  // setActiveHotelId(r, id) below — mirroring how `dataset.mounted` already
  // solved this exact "two roots, one module" problem for mount state.
  function getActiveHotelId(r) {
    return (r && r.dataset.activeHotelId) || null;
  }

  function setActiveHotelId(r, id) {
    if (!r) return;
    if (id) r.dataset.activeHotelId = id;
    else delete r.dataset.activeHotelId;
  }

  // The voucher's wording is edited directly IN the preview (js/preview-editor.js):
  // click any value on the generated page, format it with the toolbar in the
  // viewer's title line, press Regenerate. Edits are stored per hotel in
  // hotel.editedFields (field key -> HTML), the shape the backend already
  // understands (hotel_voucher_engine.compose_hotel_editable_fields).

  // Uploaded voucher files, kept in memory only (never written to
  // localStorage — they can contain guest personal data, project rule 11).
  // hotelId -> { name, type, url }. hotel.voucherFileName (persisted) says
  // a voucher was uploaded even after a reload, when the file itself is gone.
  var voucherFiles = {};
  // hotelId -> true while that voucher is still being read by OCR.
  var readingVoucher = {};
  // Set by KhannaHotels.requestPreview() (the Recent Hotel Blockings page's
  // "Edit"): the next render opens the preview straight away.
  var pendingPreview = false;

  var HOTEL_FIELDS = [
    { key: "hotelName", label: "Hotel name", required: true },
    { key: "phone", label: "Hotel phone number" },
    { key: "address", label: "Hotel address" },
    { key: "city", label: "City", required: true },
    // Frontend rework, section 10: captured so the Cover Letter's Europe
    // "Next Country" field can be pulled from this hotel record (via "Use
    // Existing Details ▾ → Hotel Blocking" in cover-letter.js) instead of
    // being guessed from the city/address text.
    { key: "country", label: "Country", placeholder: "e.g. France" },
    { key: "confirmationNumber", label: "Booking confirmation number" },
    { key: "leadGuestName", label: "Lead guest name" },
    // Split from a single "No. of guests" field on explicit request — the
    // generated voucher now prints a combined "2 Adult(s), 2 Child(s)"-style
    // count (see hotel_voucher_engine.py's _format_guest_counts()) instead
    // of one undifferentiated number.
    { key: "noOfAdults", label: "No. of adults", type: "number" },
    { key: "noOfChildren", label: "No. of children", type: "number" },
    { key: "noOfRooms", label: "No. of rooms", type: "number" },
    { key: "roomType", label: "Room type", placeholder: "e.g. Deluxe Double" },
    { key: "checkIn", label: "Check-in date", type: "date", required: true },
    { key: "checkOut", label: "Check-out date", type: "date", required: true },
  ];

  // Document-first redesign (Phase 2): this controller now mounts into
  // either the wizard's step-5 root (unchanged) or the standalone Hotel
  // Blocking page's own root, chosen by the current view — every other
  // function in this file reaches the DOM exclusively through root() (or a
  // local var set from it), so this is the only change needed to make the
  // whole module dual-mount; nothing else here knows or cares which root
  // it ended up in.
  function root() {
    var view = global.KhannaRouter ? global.KhannaRouter.parseHash().view : null;
    if (view === "hotel-blocking") return utils.qs("[data-hotel-blocking-page-root]");
    return utils.qs("[data-hotels-step-root]");
  }

  function getApp() {
    return global.KhannaState.getActiveApplication();
  }

  function hotelLabel(h) {
    return h.hotelName || "Unnamed hotel";
  }

  function isHotelComplete(h) {
    return !!(h.hotelName && h.city && h.checkIn && h.checkOut);
  }

  // The voucher is generated for EVERY hotel on the application, complete or
  // not: a voucher the OCR could not fully read (or whose online lookup found
  // nothing) must never block the document. A detail that is still empty
  // prints as a dash and can be filled in afterwards (Edit on the hotel, or
  // editing the preview); renderGenerateBar() lists what is still missing so
  // nothing is hidden. (Name kept for the callers in other pages.)
  function completeHotels(hotels) {
    return sortHotels(hotels);
  }

  // The hotels in the order they are stayed in: by check-in date, then
  // check-out date. A hotel with only one of the two dates is placed by the
  // date it has; hotels with no date at all go last, in the order they were
  // added. (Stable, so equal dates keep their order.) The list, the voucher and
  // the downloads all use this one order.
  function sortHotels(hotels) {
    var list = (hotels || []).map(function (h, i) { return { h: h, i: i }; });
    function key(h) { return h.checkIn || h.checkOut || ""; }
    list.sort(function (a, b) {
      var ka = key(a.h), kb = key(b.h);
      if (ka && !kb) return -1;
      if (!ka && kb) return 1;
      if (ka !== kb) return ka < kb ? -1 : 1;
      var oa = a.h.checkOut || "", ob = b.h.checkOut || "";
      if (oa !== ob) return !oa ? 1 : !ob ? -1 : oa < ob ? -1 : 1;
      return a.i - b.i;
    });
    return list.map(function (x) { return x.h; });
  }

  // Looks at the stays in order and reports what cannot be right: a check-out
  // before its own check-in, or a stay that starts before the previous one
  // has ended. (A gap between two stays is normal — travel, another city —
  // so it is not reported.)
  function sequenceProblems(hotels) {
    var problems = [];
    var sorted = sortHotels(hotels).filter(function (h) { return h.checkIn && h.checkOut; });
    sorted.forEach(function (h, i) {
      if (h.checkOut < h.checkIn) {
        problems.push("<strong>" + utils.escapeHtml(hotelLabel(h)) + "</strong>: the check-out (" + utils.formatDate(h.checkOut) +
          ") is before the check-in (" + utils.formatDate(h.checkIn) + ")");
        return;
      }
      var prev = sorted[i - 1];
      if (prev && prev.checkOut >= prev.checkIn && h.checkIn < prev.checkOut) {
        var n = nightsBetween(h.checkIn, prev.checkOut);
        problems.push("<strong>" + utils.escapeHtml(hotelLabel(h)) + "</strong> starts on " + utils.formatDate(h.checkIn) +
          ", before <strong>" + utils.escapeHtml(hotelLabel(prev)) + "</strong> ends on " + utils.formatDate(prev.checkOut) +
          (n ? " (" + n + " night" + (n === 1 ? "" : "s") + " overlap)" : ""));
      }
    });
    return problems;
  }

  function missingFieldsOf(h) {
    var missing = [];
    if (!h.hotelName) missing.push("hotel name");
    if (!h.city) missing.push("city");
    if (!h.checkIn) missing.push("check-in date");
    if (!h.checkOut) missing.push("check-out date");
    return missing;
  }

  function nightsBetween(checkIn, checkOut) {
    if (!checkIn || !checkOut) return null;
    var d1 = new Date(checkIn + "T00:00:00");
    var d2 = new Date(checkOut + "T00:00:00");
    if (isNaN(d1.getTime()) || isNaN(d2.getTime())) return null;
    var n = Math.round((d2 - d1) / 86400000);
    return n >= 0 ? n : null;
  }

  var FILE_ICON =
    '<svg class="icon icon-sm" viewBox="0 0 24 24"><path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5M9 13h6M9 17h6"/></svg>';

  function voucherThumbHtml(h, large) {
    var f = voucherFiles[h.id];
    if (!f) return "";
    var isImage = /^image\//.test(f.type || "");
    return (
      '<a class="hotel-voucher-thumb' + (large ? " hotel-voucher-thumb--large" : "") + '" href="' + f.url + '" target="_blank" rel="noopener" ' +
      'data-voucher-thumb title="Open the uploaded voucher">' +
      (isImage ? '<img src="' + f.url + '" alt="Uploaded voucher: ' + utils.escapeHtml(f.name) + '" />' : FILE_ICON) +
      "</a>"
    );
  }

  // "google_places+website" -> "Google + the hotel's website"
  function lookupSourceLabel(source) {
    var names = { google_places: "Google", website: "the hotel's website", openstreetmap: "OpenStreetMap", photon: "OpenStreetMap" };
    var out = [];
    String(source || "").split("+").forEach(function (key) {
      var label = names[key];
      if (label && out.indexOf(label) === -1) out.push(label);
    });
    return out.join(" + ") || "the internet";
  }

  // How the online lookup relates to the address the voucher itself prints.
  function addressCheckHtml(h) {
    var src = utils.escapeHtml(h.lookupSource);
    if (h.addressCheck === "mismatch") {
      return '<span class="hotel-card__verify" title="' + utils.escapeHtml("Looked-up address: " + (h.lookupFoundAddress || "")) +
        '">Details from ' + src + " (address differs from the voucher) — Please Verify</span>";
    }
    if (h.addressCheck === "match") {
      return '<span class="hotel-card__verify" title="Address, phone and city were looked up by hotel name and the address agrees with the one printed on the voucher">Address matches the voucher (' + src + ") — Please Verify phone</span>";
    }
    if (h.addressCheck === "partial") {
      return '<span class="hotel-card__verify" title="Only part of the address printed on the voucher appears in the looked-up address">Address only partly matches the voucher (' + src + ") — Please Verify</span>";
    }
    return '<span class="hotel-card__verify" title="The voucher names the hotel; its address, phone and city were looked up online">Address / phone / city looked up on ' + src + " — Please Verify</span>";
  }

  function voucherLineHtml(h) {
    if (!h.voucherFileName && !readingVoucher[h.id]) return "";
    if (readingVoucher[h.id]) {
      return '<div class="hotel-card__voucher" data-voucher-reading>' + FILE_ICON + "<span>Reading voucher " + utils.escapeHtml(h.voucherFileName || "") + "…</span></div>";
    }
    var f = voucherFiles[h.id];
    return (
      '<div class="hotel-card__voucher" data-voucher-file>' +
      FILE_ICON +
      (f
        ? '<a href="' + f.url + '" target="_blank" rel="noopener">' + utils.escapeHtml(h.voucherFileName) + "</a>"
        : "<span>" + utils.escapeHtml(h.voucherFileName) + " (file not kept after reload)</span>") +
      (h.source === "voucher" ? '<span class="hotel-card__verify">OCR Extracted — Please Verify</span>' : "") +
      (h.source === "voucher" && h.voucherType ? '<span class="hotel-card__verify">Read as: ' + utils.escapeHtml(h.voucherType) + "</span>" : "") +
      (h.source === "voucher" && h.lookupSource ? addressCheckHtml(h) : "") +
      "</div>"
    );
  }

  function cardHtml(h, activeId) {
    var nights = nightsBetween(h.checkIn, h.checkOut);
    var dateRange = h.checkIn && h.checkOut
      ? utils.formatDate(h.checkIn) + " → " + utils.formatDate(h.checkOut) +
        (nights !== null ? " (" + nights + " night" + (nights === 1 ? "" : "s") + ")" : "")
      : "Dates not set";
    return (
      '<div class="hotel-card' + (h.id === activeId ? " is-editing" : "") + '" data-hotel-card="' + h.id + '">' +
      voucherThumbHtml(h, false) +
      '<div class="hotel-card__info">' +
      '<div class="hotel-card__name">' + utils.escapeHtml(hotelLabel(h)) + "</div>" +
      '<div class="hotel-card__meta">' + utils.escapeHtml((h.city ? h.city + " · " : "") + dateRange) + "</div>" +
      voucherLineHtml(h) +
      (!h.voucherFileName && h.lookupSource
        ? '<div class="hotel-card__voucher"><span class="hotel-card__verify" title="Blank details were filled in by searching the hotel\'s name online">Details from ' +
          utils.escapeHtml(h.lookupSource) + " — Please Verify</span></div>"
        : "") +
      "</div>" +
      '<div class="hotel-card__actions">' +
      '<button class="btn btn-secondary btn-sm" type="button" data-action="edit-hotel" data-hotel-id="' + h.id + '">' +
      (h.id === activeId ? "Editing…" : "Edit") +
      "</button>" +
      '<button class="btn-icon" type="button" data-action="remove-hotel" data-hotel-id="' + h.id + '" aria-label="Remove hotel">' +
      '<svg class="icon icon-sm" viewBox="0 0 24 24"><path d="M4 7h16M9 7V5a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2m2 0-1 13a1 1 0 0 1-1 1H8a1 1 0 0 1-1-1L6 7"/></svg>' +
      "</button>" +
      "</div>" +
      "</div>"
    );
  }

  function renderGenerateBar() {
    var r = root();
    var box = utils.qs("[data-voucher-generate]", r);
    if (!box) return;
    var app = getApp();
    var hotels = (app && app.hotels) || [];
    var ready = hotels.length > 0;
    var skipped = sortHotels(hotels).filter(function (h) { return !isHotelComplete(h); });
    var sequence = sequenceProblems(hotels);

    var lastGenerated = hotels.reduce(function (latest, h) {
      return h.voucherGeneratedAt && (!latest || h.voucherGeneratedAt > latest) ? h.voucherGeneratedAt : latest;
    }, null);

    var warningIcon = '<svg class="icon icon-sm" viewBox="0 0 24 24"><path d="M12 9v4M12 17h.01"/><circle cx="12" cy="12" r="9"/></svg>';
    var infoIcon = '<svg class="icon icon-sm" viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><path d="M12 11v5M12 8h.01"/></svg>';
    var notice = "";
    if (!ready) {
      notice =
        // A calm hint, not an alarm: an empty list is simply where you start.
        '<div class="notice">' + infoIcon +
        "<span>Add at least one hotel (upload a voucher or add it manually) to generate the hotel voucher.</span></div>";
    } else if (skipped.length) {
      notice =
        '<div class="notice" data-hotel-skipped-notice>' + infoIcon +
        "<span>You can generate now — every hotel is included. These details are still empty and will print as a dash until you fill them (use Edit on the hotel, or edit the preview): " +
        skipped.map(function (h) {
          return "<strong>" + utils.escapeHtml(hotelLabel(h)) + "</strong> — " + missingFieldsOf(h).join(", ");
        }).join("; ") +
        ".</span></div>";
    }

    if (sequence.length) {
      notice +=
        '<div class="notice notice-warning" data-hotel-sequence-notice>' + warningIcon +
        "<span>Please check the dates — " + sequence.join("; ") + ".</span></div>";
    }

    box.innerHTML =
      notice +
      '<div class="hotel-generate-bar">' +
      '<button class="btn btn-primary btn-sm" type="button" data-action="generate-voucher"' + (ready ? "" : " disabled") + ">" +
      "Generate &amp; Preview Hotel Voucher</button>" +
      (lastGenerated ? '<span class="hotel-generate-bar__meta">Last generated ' + utils.formatDate(lastGenerated) + "</span>" : "") +
      "</div>" +
      '<div data-voucher-lookup-report></div>' +
      '<div data-voucher-error></div>';
    showDetailsReport(null);
  }

  function renderList() {
    var r = root();
    if (!r) return;
    var listEl = utils.qs("[data-hotels-list]", r);
    if (!listEl) return;
    var app = getApp();
    var hotels = (app && app.hotels) || [];

    if (hotels.length === 0) {
      listEl.innerHTML =
        '<div class="empty-state">' +
        '<svg class="icon" viewBox="0 0 24 24"><path d="M3 21h18M5 21V7l7-4 7 4v14M9 9h1m-1 4h1m4-4h1m-1 4h1M9 21v-4a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v4"/></svg>' +
        "<h3>No hotels blocked yet</h3>" +
        "</div>";
    } else {
      var activeId = getActiveHotelId(r);
      listEl.innerHTML = sortHotels(hotels).map(function (h) { return cardHtml(h, activeId); }).join("");
    }

    renderGenerateBar();
    if (global.KhannaRouter) global.KhannaRouter.refreshWizardFooter();
  }

  function closePanel(r) {
    r = r || root();
    setActiveHotelId(r, null);
    var panel = utils.qs("[data-hotel-panel]", r);
    if (panel) panel.innerHTML = "";
    renderList();
  }

  function guestRowHtml(name, index) {
    return (
      '<div class="hotel-guest-row" data-guest-index="' + index + '">' +
      '<input type="text" data-guest-name-input value="' + utils.escapeHtml(name) + '" placeholder="Guest name" />' +
      '<button type="button" class="btn-icon" data-action="remove-guest-name" aria-label="Remove guest">' +
      '<svg class="icon icon-sm" viewBox="0 0 24 24"><path d="M18 6 6 18M6 6l12 12"/></svg>' +
      "</button>" +
      "</div>"
    );
  }

  function fieldRowHtml(f) {
    var id = "hf-" + f.key;
    return (
      '<div class="field">' +
      '<label for="' + id + '">' + utils.escapeHtml(f.label) + (f.required ? " *" : "") + "</label>" +
      '<input type="' + (f.type || "text") + '" id="' + id + '" data-hotel-field="' + f.key + '"' +
      (f.placeholder ? ' placeholder="' + utils.escapeHtml(f.placeholder) + '"' : "") +
      (f.type === "number" ? ' min="0"' : "") +
      " />" +
      "</div>"
    );
  }

  function renderGuestNames(hotel, r) {
    var panel = utils.qs("[data-hotel-panel]", r || root());
    if (!panel) return;
    var listEl = utils.qs("[data-guest-names-list]", panel);
    if (!listEl) return;
    var names = (hotel && hotel.guestNames) || [];
    listEl.innerHTML = names.map(guestRowHtml).join("");
  }

  function saveGuestNamesFromDom(appId, hotelId, r) {
    var panel = utils.qs("[data-hotel-panel]", r || root());
    if (!panel) return;
    var inputs = utils.qsa("[data-guest-name-input]", panel);
    var names = inputs.map(function (inp) {
      return inp.value;
    });
    global.KhannaState.updateHotel(appId, hotelId, { guestNames: names }, "Guest names updated");
  }

  // Turns one OCR result into a hotel patch object (used by the "Upload
  // Hotel Vouchers" batch flow below). Only fields the backend actually returned a non-empty value
  // for are included — a field it couldn't find is left out of the patch
  // entirely (never overwritten with a blank), same honesty rule as
  // passport OCR (project rule 10).
  function ocrResultToPatch(result) {
    var fields = (result && result.fields) || {};
    var patch = {};
    Object.keys(fields).forEach(function (key) {
      var value = fields[key];
      if (value !== null && value !== undefined && String(value).trim() !== "") {
        patch[key] = value;
      }
    });
    if (result && result.guestNames && result.guestNames.length) {
      patch.guestNames = result.guestNames;
    }
    // Where the address / phone / city came from, so the card can say so
    // ("looked up", not "read from the voucher") — only set on a real hit —
    // and whether the looked-up address agrees with the one the voucher prints.
    var lookup = result && result.lookup;
    patch.lookupSource = "";
    patch.addressCheck = "";
    if (lookup && (lookup.status === "ok" || lookup.status === "address_mismatch")) {
      patch.lookupSource = lookupSourceLabel(lookup.source);
      patch.addressCheck = (lookup.addressCheck && lookup.addressCheck.status) || "unverified";
    }
    if (lookup && lookup.status === "address_mismatch") {
      patch.lookupFoundAddress = lookup.address || "";
    }
    patch.voucherAddress = (result && result.voucherAddress) || "";
    patch.voucherType = (result && result.voucherTypeLabel && result.voucherType !== "unknown") ? result.voucherTypeLabel : "";
    return patch;
  }

  // "Upload Hotel Vouchers" (plural — frontend rework, section: Hotel
  // Blocking multi-voucher upload): one NEW hotel record per selected
  // file, each run through the same real OCR pipeline as the single-hotel
  // flow above (never a second, fake code path) and left just as
  // editable/unverified. Files are processed ONE AT A TIME (not
  // Promise.all) so the backend — a single local process — never gets N
  // simultaneous OCR requests at once, and so the status line can report
  // real per-file progress; a failure on one file is reported and the rest
  // still proceed (never lets one bad upload silently drop the others).
  var batchRunning = false;

  function isBlankHotel(h) {
    return !h.source && !h.voucherFileName && !(h.hotelName || h.city || h.checkIn || h.checkOut || h.address || h.phone ||
      h.confirmationNumber || h.leadGuestName || h.roomType || h.noOfAdults || h.noOfChildren || h.noOfRooms ||
      (h.guestNames && h.guestNames.length));
  }

  function runBatchHotelVoucherOcr(app, files, r) {
    var statusEl = utils.qs("[data-hotel-batch-upload-status]", r);
    var uploadBtn = utils.qs("[data-action='upload-hotel-vouchers']", r);
    if (batchRunning) {
      if (statusEl) statusEl.textContent = "Vouchers are still being read — please wait for the current upload to finish.";
      return;
    }
    batchRunning = true;
    if (uploadBtn) uploadBtn.disabled = true;
    // A completely empty hotel row (nothing typed, nothing uploaded) would
    // otherwise sit above the new vouchers; remove it so the list is exactly
    // the uploaded vouchers, in the order they were selected.
    (app.hotels || []).filter(isBlankHotel).forEach(function (h) {
      global.KhannaState.removeHotel(app.id, h.id);
    });
    // One work item per voucher PAGE, kept in upload order: a multi-page PDF
    // contributes extra items (pages 2..n) right after its first page once the
    // backend reports how many pages it has.
    var queue = files.map(function (file) { return { file: file, page: 0, optional: false, label: file.name }; });
    var total = files.length;
    var done = 0;
    var failures = []; // the OCR call itself errored (network/backend down/unreadable file)
    var noFieldsFound = []; // OCR ran fine but found nothing usable
    var extracted = 0;
    var lookedUp = 0;
    var notLookedUp = []; // hotel named on the voucher, but the online lookup found nothing
    var warned = []; // the backend flagged something to check (e.g. nights vs dates)
    var added = 0;

    function finish() {
      batchRunning = false;
      if (uploadBtn) uploadBtn.disabled = false;
      renderList();
      if (statusEl) {
        var parts = [added + " hotel(s) added, one per voucher, in the order uploaded — review every field below (extraction is never auto-verified)."];
        if (extracted > 0) parts.push(extracted + " had readable details filled in automatically.");
        if (lookedUp > 0) parts.push("Address, phone and city of " + lookedUp + " hotel(s) were looked up online by hotel name — please verify them.");
        if (notLookedUp.length) parts.push("Address / phone / city could not be looked up for: " + notLookedUp.join(", ") + " — fill them in from the voucher.");
        warned.forEach(function (w) { parts.push(w); });
        if (noFieldsFound.length) parts.push("No details found on: " + noFieldsFound.join(", ") + ".");
        if (failures.length) parts.push("Could not read: " + failures.join(", ") + ".");
        statusEl.textContent = parts.join(" ");
      }
      // Every hotel read OK and complete -> generate the voucher straight
      // away, one block per uploaded voucher. Anything missing stays for the
      // staff member to fill in first (never guessed).
      autoPreviewIfReady(false);
    }

    function next() {
      if (!queue.length) {
        finish();
        return;
      }
      var item = queue.shift();
      var file = item.file;
      done += 1;
      if (statusEl) {
        statusEl.textContent = "Processing voucher " + done + " of " + (done + queue.length) + " (" + item.label + ")…";
      }
      // The hotel record is created up front and kept regardless of what
      // happens below — a blank, manually-fillable entry is more useful
      // than silently dropping the voucher, and the card shows the uploaded
      // file immediately while it is being read. (A later page of a PDF is
      // only kept when it turns out to be a voucher itself.)
      var hotel = global.KhannaState.addHotel(app.id);
      voucherFiles[hotel.id] = { name: file.name, type: file.type || "", url: URL.createObjectURL(file) };
      readingVoucher[hotel.id] = true;
      global.KhannaState.updateHotel(app.id, hotel.id, { source: "voucher", voucherFileName: item.page > 0 ? file.name + " (page " + (item.page + 1) + ")" : file.name }, null);
      renderList();
      api.processHotelVoucher(file, item.page).then(
        function (result) {
          delete readingVoucher[hotel.id];
          if (item.page === 0 && result && result.totalPages > 1) {
            // Queue the remaining pages directly after this one so hotels stay in file order.
            var extra = [];
            for (var p = 1; p < result.totalPages; p++) {
              extra.push({ file: file, page: p, optional: true, label: file.name + ", page " + (p + 1) });
            }
            queue = extra.concat(queue);
          }
          var patch = ocrResultToPatch(result);
          var isVoucherPage = !!(result && (result.voucherType !== "unknown" || (result.fields && result.fields.hotelName)));
          if (item.optional && !isVoucherPage) {
            // An extra PDF page that is not a voucher (terms, cancellation policy ...).
            global.KhannaState.removeHotel(app.id, hotel.id);
            renderList();
            next();
            return;
          }
          added += 1;
          var hasFields = Object.keys(result.fields || {}).some(function (k) { return result.fields[k]; }) || (result.guestNames || []).length;
          if (hasFields) {
            global.KhannaState.updateHotel(app.id, hotel.id, patch, "Hotel voucher details extracted");
            extracted += 1;
            if (patch.lookupSource) lookedUp += 1;
            else if (result.lookup && result.lookup.status !== "skipped") notLookedUp.push(item.label);
            (result.warnings || []).forEach(function (w) { warned.push(item.label + ": " + w); });
          } else {
            noFieldsFound.push(item.label);
            renderList();
          }
          next();
        },
        function () {
          delete readingVoucher[hotel.id];
          if (item.optional) {
            global.KhannaState.removeHotel(app.id, hotel.id);
          } else {
            added += 1;
            failures.push(item.label);
          }
          renderList();
          next();
        }
      );
    }

    next();
  }

  function openPanel(hotelId, r) {
    r = r || root();
    var app = getApp();
    if (!app) return;
    var hotel = global.KhannaState.getHotel(app.id, hotelId);
    if (!hotel) return;

    setActiveHotelId(r, hotelId);
    renderList();

    var panel = utils.qs("[data-hotel-panel]", r);
    if (!panel) return;

    panel.innerHTML =
      '<div class="hotel-panel">' +
      '<div class="hotel-panel__header">' +
      "<h3>Editing: " + utils.escapeHtml(hotelLabel(hotel)) + "</h3>" +
      '<button class="btn btn-ghost btn-sm" type="button" data-action="close-hotel-panel">Close</button>' +
      "</div>" +
      (voucherFiles[hotel.id]
        ? '<div class="hotel-panel__voucher">' + voucherThumbHtml(hotel, true) +
          '<div><div class="hotel-panel__voucher-name">' + utils.escapeHtml(hotel.voucherFileName) + "</div>" +
          '<div class="field-hint">OCR Extracted — Please Verify.</div></div></div>'
        : hotel.voucherFileName
          ? '<p class="field-hint">Voucher "' + utils.escapeHtml(hotel.voucherFileName) + '" — OCR Extracted — Please Verify.</p>'
          : "") +
      '<div class="field-grid">' + HOTEL_FIELDS.map(fieldRowHtml).join("") + "</div>" +
      '<div class="hotel-panel__guests">' +
      "<label>Guest names on the voucher</label>" +
      '<div data-guest-names-list></div>' +
      '<button type="button" class="btn btn-secondary btn-sm" data-action="hotel-use-applicant-lead">Use existing applicant as lead guest</button> ' +
      '<button type="button" class="btn btn-secondary btn-sm" data-action="hotel-use-applicant-guest">Add existing applicant as guest</button> ' +
      '<button type="button" class="btn btn-ghost btn-sm" data-action="add-guest-name">' +
      '<svg class="icon icon-sm" viewBox="0 0 24 24"><path d="M12 5v14M5 12h14"/></svg>' +
      "Add guest name</button>" +
      "</div>" +
      "</div>";

    HOTEL_FIELDS.forEach(function (f) {
      var el = utils.qs('[data-hotel-field="' + f.key + '"]', panel);
      if (el) el.value = hotel[f.key] || "";
    });
    renderGuestNames(hotel, r);

    // The field-change listener itself is wired ONCE, in mountSkeleton()
    // (delegated on the whole step root, reading activeHotelId live) — not
    // here. openPanel() re-runs every time a hotel is added or a different
    // hotel's Edit is clicked, but panel (this function's own [data-hotel-
    // panel] container) is never replaced, only its innerHTML is rewritten
    // (see closePanel()) — so a listener attached here via utils.on(panel,
    // ...), which always calls addEventListener and never removes a prior
    // one, would silently accumulate: opening a second hotel's panel left
    // the FIRST hotel's own listener (closed over its own hotelId) still
    // attached, so typing into hotel 2's fields also patched hotel 1's
    // record with the same values. Real bug, caught by Phase 13's own
    // full-journey test (the first test to ever open a SECOND hotel's
    // panel in the same run) via a captured network payload showing both
    // hotels saved with identical data despite distinct ids.
    panel.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }

  function isStepComplete() {
    var app = getApp();
    if (!app) return false;
    var hotels = app.hotels || [];
    return hotels.length > 0;
  }

  function showVoucherError(message) {
    var r = root();
    var box = utils.qs("[data-voucher-error]", r);
    if (!box) return;
    box.innerHTML = message
      ? '<div class="notice notice-danger"><svg class="icon icon-sm" viewBox="0 0 24 24"><path d="M12 9v4M12 17h.01"/><circle cx="12" cy="12" r="9"/></svg><span>' +
        utils.escapeHtml(message) +
        "</span></div>"
      : "";
  }

  // Keyed by root element (not a single shared variable) for the same
  // reason getActiveHotelId/setActiveHotelId above are: this controller can
  // be mounted twice at once (wizard step 5 + the standalone Hotel
  // Blocking page), and a single shared viewer handle would let the wrong
  // root's "Regenerate" refresh a viewer instance actually mounted in the
  // other root's DOM.
  var viewerHandles = new WeakMap();

  function applicantNameOf(app) {
    var label = global.KhannaApplicationsList ? global.KhannaApplicationsList.applicantLabel(app) : "";
    return label && label !== "Untitled applicant" ? label : "Application";
  }

  function markVoucherGenerated() {
    // Previewing from the Dashboard's View icon only re-displays the
    // voucher — it must not change "Last generated" / "Updated" dates.
    if (global.KhannaRouter && global.KhannaRouter.isPreviewMode()) return;
    // Read the application FRESH: edits made in the preview are saved into
    // the hotel records while the PDF is being generated, and stamping from
    // an older snapshot would write them back out.
    var app = getApp();
    if (!app) return;
    var ts = new Date().toISOString();
    var hotels = (app.hotels || []).map(function (h) {
      return Object.assign({}, h, { voucherGeneratedAt: ts });
    });
    global.KhannaState.updateApplication(app.id, { hotels: hotels }, "Hotel voucher generated");
  }

  // Saves one edited value from the preview into its hotel record.
  function saveEditedField(hotelId, key, html) {
    var app = getApp();
    if (!app) return;
    var patch = {};
    patch[key] = html; // null clears the override; a string sets it
    global.KhannaState.updateHotel(app.id, hotelId, { editedFields: patch }, null);
  }

  // Mounts (once per root) the shared document viewer with the editable
  // layer, and returns its handle.
  function ensureViewer(r) {
    var handle = viewerHandles.get(r);
    if (handle) return handle;
    var previewBox = utils.qs("[data-voucher-preview]", r);
    if (!previewBox) return null;
    var editor = global.KhannaPreviewEditor.create({
      cellUnits: true, // every value is a table cell: edits never move into the next cell
      getHotels: function () {
        var a = getApp();
        return (a && a.hotels) || [];
      },
      composeFields: function (hotels) {
        return api.composeHotelFields(hotels);
      },
      onFieldChange: saveEditedField,
    });
    handle = global.KhannaDocumentViewer.mount(previewBox, {
      title: "Hotel Voucher",
      regenerateLabel: "Regenerate",
      editor: editor,
      // The PDF and where each editable value sits on its page come from ONE
      // backend call (the PDF is the exact file "Download as PDF" hands over).
      // Reads getApp()/app.hotels live at CALL time, so Regenerate — or any
      // Download/Print with unsaved edits — always reflects what is saved.
      loadPdf: function () {
        var a = getApp();
        var hotels = completeHotels(a.hotels);
        if (!hotels.length) {
          return Promise.reject(new Error("Add at least one hotel first."));
        }
        return api.previewHotelVoucher(hotels, applicantNameOf(a)).then(function (res) {
          res.hotelIds = hotels.map(function (h) { return h.id; });
          return res;
        });
      },
      loadDocx: function () {
        var a = getApp();
        return api.downloadHotelVoucher(completeHotels(a.hotels), "docx", applicantNameOf(a));
      },
      onRefreshed: markVoucherGenerated,
      onRegenerate: function () {
        return Promise.resolve();
      },
    });
    viewerHandles.set(r, handle);
    return handle;
  }

  // generateAndPreview() replaces the old "Generate (.docx)" / "Download
  // as PDF" two-button flow: preview shows the exact generated PDF, and
  // DOCX/PDF both come from the shared viewer. `btn` is optional (the
  // automatic previews after an upload / from Recent Hotel Blockings have no
  // button click behind them).
  // Hotels whose name has already been looked up this session, so a hotel the
  // internet does not know is not searched again on every Regenerate.
  var detailsLookedUp = {};

  function isMissingDetails(h) {
    return !h.address || !h.phone || !h.city || !h.country;
  }

  // Fills a hotel's BLANK address / phone / city / country from the internet
  // (Google Places when the backend has a key) before the voucher is made.
  // Details already on the hotel are never replaced. Resolves with a short
  // report for the page; a failed lookup never stops the voucher.
  function completeMissingDetails(app) {
    var todo = ((app && app.hotels) || []).filter(function (h) {
      return (h.hotelName || "").trim().length >= 3 && isMissingDetails(h) && !detailsLookedUp[h.id + "|" + h.hotelName];
    });
    if (!todo.length) return Promise.resolve({ filled: [], notFound: [] });
    todo.forEach(function (h) { detailsLookedUp[h.id + "|" + h.hotelName] = true; });
    var payload = todo.map(function (h) {
      return {
        id: h.id, hotelName: h.hotelName, address: h.address || "", phone: h.phone || "", city: h.city || "", country: h.country || "",
        // a voucher-read name that was never looked up: the listing's own name wins
        useListingName: h.source === "voucher" && !h.lookupSource,
      };
    });
    return api.completeHotelDetails(payload).then(function (res) {
      var filled = [];
      var notFound = [];
      (res.results || []).forEach(function (r) {
        var h = todo.filter(function (x) { return x.id === r.id; })[0];
        if (!h) return;
        var patch = {};
        Object.keys(r.fields || {}).forEach(function (k) { patch[k] = r.fields[k]; });
        if (r.hotelName) {
          patch.hotelName = r.hotelName;
          patch.voucherHotelName = r.voucherHotelName || h.hotelName;
        }
        if (Object.keys(patch).length) {
          patch.lookupSource = lookupSourceLabel(r.source);
          patch.addressCheck = h.addressCheck || "unverified";
          global.KhannaState.updateHotel(app.id, h.id, patch, "Hotel details looked up online");
          filled.push({ name: patch.hotelName || h.hotelName, fields: r.filled || [], source: patch.lookupSource });
        } else if (r.status !== "skipped") {
          notFound.push(h.hotelName);
        }
      });
      return { filled: filled, notFound: notFound };
    }).catch(function () { return { filled: [], notFound: [] }; });
  }

  var lastDetailsReport = null; // {appId, report}: kept so re-drawing the bar does not lose it

  function showDetailsReport(report) {
    var app = getApp();
    if (report) lastDetailsReport = { appId: app && app.id, report: report };
    else if (lastDetailsReport && app && lastDetailsReport.appId === app.id) report = lastDetailsReport.report;
    if (!report) return;
    var r = root();
    var box = r && utils.qs("[data-voucher-lookup-report]", r);
    if (!box) return;
    var parts = [];
    report.filled.forEach(function (f) {
      parts.push("<strong>" + utils.escapeHtml(f.name) + "</strong>: " + f.fields.join(", ") + " from " + utils.escapeHtml(f.source));
    });
    var html = "";
    if (parts.length) {
      html += '<div class="notice" data-hotel-lookup-filled><svg class="icon icon-sm" viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><path d="M12 11v5M12 8h.01"/></svg><span>Blank details were filled in from the internet — Please Verify: ' + parts.join("; ") + ".</span></div>";
    }
    if (report.notFound.length) {
      html += '<div class="notice notice-warning" data-hotel-lookup-missing><svg class="icon icon-sm" viewBox="0 0 24 24"><path d="M12 9v4M12 17h.01"/><circle cx="12" cy="12" r="9"/></svg><span>No online details found for ' +
        report.notFound.map(function (n) { return "<strong>" + utils.escapeHtml(n) + "</strong>"; }).join(", ") +
        ". Add them with Edit on the hotel, or edit the preview.</span></div>";
    }
    box.innerHTML = html;
  }

  function generateAndPreview(btn) {
    var app = getApp();
    if (!app) return Promise.resolve();
    showVoucherError("");
    var r = root();
    if (!r) return Promise.resolve();
    var handle = ensureViewer(r);
    if (!handle) return Promise.resolve();

    var originalText = btn ? btn.textContent : "";
    if (btn) {
      btn.disabled = true;
      btn.textContent = "Generating…";
    }
    return completeMissingDetails(app)
      .then(function (report) {
        if (report.filled.length) renderList();
        showDetailsReport(report.filled.length || report.notFound.length ? report : null);
        return handle.refresh();
      })
      .catch(function (err) {
        showVoucherError(err && err.message ? err.message : "Could not generate the hotel voucher.");
      })
      .finally(function () {
        if (btn) {
          btn.disabled = false;
          btn.textContent = originalText;
        }
      });
  }

  function isReadyToGenerate() {
    var app = getApp();
    var hotels = (app && app.hotels) || [];
    return completeHotels(hotels).length > 0 && !Object.keys(readingVoucher).length;
  }

  function autoPreviewIfReady(scroll) {
    var r = root();
    if (!r || !isReadyToGenerate()) return Promise.resolve();
    var p = generateAndPreview(null);
    if (scroll) {
      var box = utils.qs("[data-voucher-preview]", r);
      if (box && box.scrollIntoView) box.scrollIntoView({ behavior: "smooth", block: "start" });
    }
    return p;
  }

  function mountSkeleton() {
    var r = root();
    if (!r) return;
    r.innerHTML =
      '<div class="view-header">' +
      '<div class="view-header__text">' +
      "<h2>Hotel blocking</h2>" +
      "</div>" +
      '<div class="view-header__actions">' +
      // "Upload Hotel Vouchers" (plural, frontend rework): one NEW hotel
      // per selected file, each run through the real OCR pipeline — see
      // runBatchHotelVoucherOcr() above. A real <input multiple> file
      // picker, not a decorative button (project rule 9).
      '<input type="file" accept="image/jpeg,image/png,image/webp,image/bmp,application/pdf" multiple data-hotel-batch-upload-input hidden />' +
      '<button class="btn btn-secondary btn-sm" type="button" data-action="upload-hotel-vouchers">' +
      '<svg class="icon icon-sm" viewBox="0 0 24 24"><path d="M12 5v14M5 12h14"/></svg>' +
      "Upload Hotel Vouchers" +
      "</button>" +
      '<button class="btn btn-primary btn-sm" type="button" data-action="add-hotel">' +
      '<svg class="icon icon-sm" viewBox="0 0 24 24"><path d="M12 5v14M5 12h14"/></svg>' +
      "Add hotel Manually" +
      "</button>" +
      "</div>" +
      "</div>" +
      '<p class="field-hint" data-hotel-batch-upload-status></p>' +
      '<div class="hotel-list" data-hotels-list></div>' +
      '<div data-hotel-panel></div>' +
      '<div class="card" data-voucher-generate></div>' +
      '<div data-voucher-preview style="margin-top:var(--space-4);"></div>';

    utils.on(r, "click", "[data-action='add-hotel']", function () {
      var app = getApp();
      if (!app) return;
      var hotel = global.KhannaState.addHotel(app.id);
      openPanel(hotel.id, r);
    });

    utils.on(r, "click", "[data-action='upload-hotel-vouchers']", function () {
      var input = utils.qs("[data-hotel-batch-upload-input]", r);
      if (input) input.click();
    });

    // Auto-runs on selection — same "no separate Run button" pattern as
    // the single-hotel upload above and Upload Passport. `target.value =
    // ""` afterward lets staff re-select the SAME file(s) a second time
    // (e.g. after fixing something and wanting to re-run OCR fresh) —
    // browsers don't fire "change" again for an unchanged file list
    // otherwise.
    utils.on(r, "change", "[data-hotel-batch-upload-input]", function (e, target) {
      var app = getApp();
      var files = target.files ? Array.prototype.slice.call(target.files) : [];
      target.value = "";
      if (!app || !files.length) return;
      runBatchHotelVoucherOcr(app, files, r);
    });

    utils.on(r, "click", "[data-action='edit-hotel']", function (e, target) {
      openPanel(target.getAttribute("data-hotel-id"), r);
    });

    utils.on(r, "click", "[data-action='remove-hotel']", function (e, target) {
      var app = getApp();
      if (!app) return;
      var id = target.getAttribute("data-hotel-id");
      if (id === getActiveHotelId(r)) setActiveHotelId(r, null);
      global.KhannaState.removeHotel(app.id, id);
      var panel = utils.qs("[data-hotel-panel]", r);
      if (panel && !getActiveHotelId(r)) panel.innerHTML = "";
    });

    utils.on(r, "click", "[data-action='close-hotel-panel']", function () {
      closePanel(r);
    });

    utils.on(r, "click", "[data-action='add-guest-name']", function () {
      var app = getApp();
      var activeId = getActiveHotelId(r);
      if (!app || !activeId) return;
      var hotel = global.KhannaState.getHotel(app.id, activeId);
      if (!hotel) return;
      var names = (hotel.guestNames || []).concat([""]);
      global.KhannaState.updateHotel(app.id, activeId, { guestNames: names }, null);
      renderGuestNames(global.KhannaState.getHotel(app.id, activeId), r);
    });

    // "Use existing applicant" — same saved-people pool every other document
    // page uses (KhannaApplicantPicker), but a hotel voucher lists guests, not
    // an application's applicant, so the picked person only fills the lead
    // guest name or is added to the guest-name list of the hotel being edited.
    function applicantGuestName(profile) {
      var name = String((profile && profile.fullName) || "").trim();
      if (!name) return "";
      var sal = String((profile && profile.salutation) || "").trim();
      return sal ? sal.replace(/\.?$/, ".") + " " + name : name;
    }
    function pickApplicantForHotel(asLead) {
      var app = getApp();
      var activeId = getActiveHotelId(r);
      if (!app || !activeId || !global.KhannaApplicantPicker) return;
      global.KhannaApplicantPicker.open(function (profile) {
        var guest = applicantGuestName(profile);
        if (!guest) {
          global.KhannaToast && global.KhannaToast.show && global.KhannaToast.show("That saved applicant has no name.", "warning");
          return;
        }
        if (getActiveHotelId(r) !== activeId) return;
        saveGuestNamesFromDom(app.id, activeId, r); // keep in-progress typing
        var hotel = global.KhannaState.getHotel(app.id, activeId);
        if (!hotel) return;
        if (asLead) {
          global.KhannaState.updateHotel(app.id, activeId, { leadGuestName: guest }, "Lead guest set from saved applicant");
        } else {
          var names = (hotel.guestNames || []).slice();
          var already = names.some(function (n) { return String(n).trim().toLowerCase() === guest.toLowerCase(); }) ||
            String(hotel.leadGuestName || "").trim().toLowerCase() === guest.toLowerCase();
          if (!already) names.push(guest);
          global.KhannaState.updateHotel(app.id, activeId, { guestNames: names }, already ? null : "Guest added from saved applicant");
        }
        openPanel(activeId, r);
      });
    }
    utils.on(r, "click", "[data-action='hotel-use-applicant-lead']", function () { pickApplicantForHotel(true); });
    utils.on(r, "click", "[data-action='hotel-use-applicant-guest']", function () { pickApplicantForHotel(false); });

    utils.on(r, "click", "[data-action='remove-guest-name']", function (e, target) {
      var app = getApp();
      var activeId = getActiveHotelId(r);
      if (!app || !activeId) return;
      saveGuestNamesFromDom(app.id, activeId, r); // persist any in-progress edits first
      var hotel = global.KhannaState.getHotel(app.id, activeId);
      if (!hotel) return;
      var row = target.closest("[data-guest-index]");
      var idx = parseInt(row.getAttribute("data-guest-index"), 10);
      var names = (hotel.guestNames || []).slice();
      names.splice(idx, 1);
      global.KhannaState.updateHotel(app.id, activeId, { guestNames: names }, "Guest name removed");
      renderGuestNames(global.KhannaState.getHotel(app.id, activeId), r);
    });

    utils.on(r, "change", "[data-guest-name-input]", function () {
      var activeId = getActiveHotelId(r);
      if (!activeId) return;
      var app = getApp();
      if (!app) return;
      saveGuestNamesFromDom(app.id, activeId, r);
    });

    // Wired ONCE here (delegated on the whole step root, reading this root's
    // OWN active hotel id live at fire time via getActiveHotelId(r)) rather
    // than re-attached inside openPanel() on every open — see the comment in
    // openPanel() for the original build's listener-accumulation bug this
    // fixes, and the comment above getActiveHotelId()/setActiveHotelId() for
    // the Phase 4 dual-mount variant of the same bug class this `r`-scoped
    // (not module-level) tracking fixes.
    utils.on(r, "change", "[data-hotel-field]", function (e, target) {
      var activeId = getActiveHotelId(r);
      if (!activeId) return;
      var app = getApp();
      if (!app) return;
      var key = target.getAttribute("data-hotel-field");
      var patch = {};
      patch[key] = target.value;
      global.KhannaState.updateHotel(app.id, activeId, patch, "Hotel details updated");
    });

    utils.on(r, "click", "[data-action='generate-voucher']", function (e, target) {
      if (target.disabled) return;
      generateAndPreview(target);
    });
  }

  function render() {
    var r = root();
    if (!r) return;
    // The wizard can never reach this step without an active application
    // already existing, so this is a no-op there; the standalone Hotel
    // Blocking page CAN be opened directly with none yet, and mounting the
    // real "Add hotel" skeleton in that case would look interactive but
    // silently do nothing when clicked — document-workspace.js's app bar is
    // what tells the user to create one, not this panel pretending to work
    // in the meantime (project rule 9). Deliberately doesn't set
    // dataset.mounted here, so the real skeleton still mounts the first
    // time render() runs again with an application active.
    if (!getApp()) {
      // Also clears a STALE dataset.mounted flag from an earlier successful
      // mount (e.g. the user had an application active, this page mounted
      // for real, then they switched to no active application) — without
      // this, the next render() that DOES have an app would see
      // dataset.mounted already "1" and skip mountSkeleton() entirely,
      // leaving this placeholder text stuck permanently instead of the
      // real form. Caught by testing the full switch-away-and-back
      // sequence, not just the two states in isolation.
      delete r.dataset.mounted;
      r.innerHTML = '<p class="field-hint">Create or continue an application above to start adding hotels.</p>';
      return;
    }
    var app = getApp();
    if (r.dataset.mounted && r.dataset.appId !== app.id) {
      // Switched to a different application: the old preview/panel belong
      // to the previous one, so rebuild from scratch.
      delete r.dataset.mounted;
      setActiveHotelId(r, null);
    }
    if (!r.dataset.mounted) {
      r.dataset.mounted = "1";
      r.dataset.appId = app.id;
      var oldViewer = viewerHandles.get(r);
      if (oldViewer) {
        try { oldViewer.destroy(); } catch (e) { /* container already gone */ }
        viewerHandles.delete(r);
      }
      mountSkeleton();
    }
    renderList();
    if (pendingPreview && r === utils.qs("[data-hotel-blocking-page-root]")) {
      pendingPreview = false;
      // Straight to the editable preview (Recent Hotel Blockings -> Edit).
      autoPreviewIfReady(true);
    }
  }

  function init() {
    if (global.KhannaRouter) global.KhannaRouter.registerStepValidator("new-application", 5, isStepComplete);

    document.addEventListener("khanna:navigate", function (e) {
      if (e.detail.view === "new-application" || e.detail.view === "hotel-blocking") render();
    });

    // The list (not the open panel) reacts to every state change, matching
    // the discipline established in travellers.js/documents.js.
    global.KhannaState.subscribe(function () {
      if (root() && root().dataset.mounted) renderList();
    });

    var startView = global.KhannaRouter ? global.KhannaRouter.parseHash().view : "";
    if (startView === "new-application" || startView === "hotel-blocking") render();
  }

  global.KhannaHotels = {
    // Recent Hotel Blockings -> "Edit": make the next Hotel Blocking page
    // render open the (editable) preview straight away.
    requestPreview: function () {
      pendingPreview = true;
    },
    isHotelComplete: isHotelComplete,
    completeHotels: completeHotels,
    sortHotels: sortHotels,
    sequenceProblems: sequenceProblems,
    // Used by the Upload Documents page to read a voucher the same way the
    // Hotel Blocking page does (project rule 15: one mapping, not two).
    ocrResultToPatch: ocrResultToPatch,
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})(window);
