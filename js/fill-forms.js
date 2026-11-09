/* ==========================================================================
   Khanna Travels & Holidays — Fill Forms page ("#/fill-forms")
   Fills an embassy's own fillable PDF form (first: the Japan visa
   application form). The form's fields come from the backend definition
   (backend/python/visa_forms/*.json), so a new country's form is a new
   definition file, not new page code.

   Staff can start from a saved application (any person in it) or from a
   passport uploaded here (read with the same passport OCR as everywhere
   else). Every pre-filled value is marked and stays editable (rule 10).
   The six "Have you ever…" questions are never answered automatically:
   staff must ask the applicant (rule 19).

   Values typed here are kept with the saved application (app.visaForms
   [formId]) when one is chosen, so the form can be reopened and corrected.
   ========================================================================== */
(function (global) {
  "use strict";

  var utils = global.KhannaUtils;
  var api = global.KhannaApi;
  var S = global.KhannaState;
  var Intake = global.KhannaDocumentIntake;
  var People = global.KhannaVisaFormPeople;
  var reviewForm = global.KhannaPassportReviewForm;

  var VERIFY = "OCR Extracted — Please Verify";

  var st = {
    forms: null, // definitions from the backend
    loadError: "",
    formId: "",
    values: {},
    filledFrom: {}, // key -> "application" | "passport" | "default"
    appId: null,
    personId: "applicant",
    sourceLabel: "",
    passportStatus: "",
    hotelStatus: "",
    flightStatus: "",
    flight: null, // last flight-booking reading (legs + warnings)
    hotelListOpen: false,
    generating: false,
    generated: null, // { url, filename, blob }
    error: "",
  };

  var built = false;

  function root() {
    return utils.qs("[data-fill-forms-root]");
  }

  function esc(v) {
    return utils.escapeHtml(v);
  }

  function currentForm() {
    return (st.forms || []).filter(function (f) { return f.id === st.formId; })[0] || null;
  }

  function eachField(form, fn) {
    (form.sections || []).forEach(function (section) {
      (section.fields || []).forEach(function (field) {
        if (field.type === "columns") {
          (field.parts || []).forEach(function (part) { fn(part, section, field); });
        } else {
          fn(field, section, null);
        }
      });
    });
  }

  /* ----------------------------------------------------------------------
   * Pre-filling from saved data
   * -------------------------------------------------------------------- */

  function getPath(obj, path) {
    return String(path || "").split(".").reduce(function (o, k) { return o === null || o === undefined ? undefined : o[k]; }, obj);
  }

  function joinParts(parts) {
    var seen = [];
    parts.forEach(function (p) {
      p = String(p || "").trim();
      if (p && seen.join(", ").toUpperCase().indexOf(p.toUpperCase()) === -1) seen.push(p);
    });
    return seen.join(", ");
  }

  function isoOf(text) {
    var p = reviewForm.parseDate(text);
    return p ? p.iso : "";
  }

  function hotelsByDate(app) {
    return (app.hotels || []).filter(function (h) { return (h.hotelName || "").trim(); }).slice().sort(function (a, b) {
      return String(a.checkIn || "9999").localeCompare(String(b.checkIn || "9999"));
    });
  }

  function lengthOfStay(start, end) {
    var a = isoOf(start), b = isoOf(end);
    if (!a || !b) return "";
    var days = Math.round((new Date(b) - new Date(a)) / 86400000) + 1;
    return days > 0 ? days + (days === 1 ? " DAY" : " DAYS") : "";
  }

  /** Everything a definition's "source" paths can point at. */
  function contextFor(app, person) {
    var hotels = app ? hotelsByDate(app) : [];
    var hotel = hotels[0] || {};
    var cover = (app && app.coverLetter) || {};
    var travel = (app && app.travel) || {};
    var start = travel.startDate || cover.travelStartDate || (hotels[0] && hotels[0].checkIn) || "";
    var end = travel.endDate || cover.travelEndDate || hotels.reduce(function (m, h) { return h.checkOut && h.checkOut > m ? h.checkOut : m; }, "");
    var p = person || {};
    var addr = p.address || {};
    return {
      applicant: Object.assign({}, p, {
        fullAddress: joinParts([addr.line1, addr.line2, addr.city, addr.state, addr.pincode]),
      }),
      travel: { purpose: travel.purpose || "", startDate: start, endDate: end, lengthOfStay: lengthOfStay(start, end) },
      hotel: Object.assign({}, hotel, { fullAddress: joinParts([hotel.address, hotel.city, hotel.country]) }),
    };
  }

  function transform(value, format, ctx) {
    var v = value === null || value === undefined ? "" : String(value).trim();
    if (format === "firstPart") return v.split(",")[0].trim();
    if (format === "secondPart") return (v.split(",")[1] || "").trim();
    if (format === "nationality") return /^(IND|INDIA)$/i.test(v) ? "INDIAN" : v;
    if (format === "passportType") {
      var c = v.toUpperCase().charAt(0);
      if (c === "P") return v.toUpperCase().charAt(1) === "D" ? "diplomatic" : v.toUpperCase().charAt(1) === "S" || v.toUpperCase().charAt(1) === "O" ? "official" : "ordinary";
      if (c === "D") return "diplomatic";
      if (c === "S" || c === "O") return "official";
      return "";
    }
    if (format === "issuingAuthority") {
      if (v) return v;
      var nat = String((ctx.applicant && ctx.applicant.nationality) || "").toUpperCase();
      return /^(IND|INDIA|INDIAN)$/.test(nat) ? "GOVERNMENT OF INDIA" : "";
    }
    return v;
  }

  function displayDate(value) {
    var p = reviewForm.parseDate(value);
    return p ? p.display : value || "";
  }

  /** Fills every field that has a source; keeps what staff typed for fields the source has nothing for. */
  function prefill(ctx, origin) {
    var form = currentForm();
    if (!form) return 0;
    var count = 0;
    eachField(form, function (field) {
      if (!field.source) return;
      var raw = transform(getPath(ctx, field.source), field.sourceFormat, ctx);
      if (!raw) return;
      if (field.type === "date") raw = displayDate(raw);
      if ((field.type === "radio" || field.type === "yesno") && !(field.options || []).some(function (o) { return o.value.toLowerCase() === raw.toLowerCase(); })) return;
      st.values[field.key] = raw;
      st.filledFrom[field.key] = origin;
      count += 1;
    });
    return count;
  }

  function applyDefaults() {
    var form = currentForm();
    if (!form) return;
    eachField(form, function (field) {
      if (field.default && !st.values[field.key]) {
        st.values[field.key] = field.default;
        st.filledFrom[field.key] = "default";
      }
    });
  }

  function personOf(app, personId) {
    if (!app) return null;
    if (personId === "applicant") return app.applicant;
    return (app.travellers || []).filter(function (t) { return t.id === personId; })[0] || app.applicant;
  }

  function useApplication(app, personId) {
    st.appId = app.id;
    st.personId = personId || "applicant";
    var saved = app.visaForms && app.visaForms[st.formId];
    st.values = {};
    st.filledFrom = {};
    if (saved && saved.personId === st.personId && saved.values) {
      st.values = Object.assign({}, saved.values);
      st.sourceLabel = "Saved form values reopened";
    } else {
      var ctx = contextFor(app, personOf(app, st.personId));
      var n = prefill(ctx, "application");
      st.sourceLabel = n + " field" + (n === 1 ? "" : "s") + " filled from the saved application";
    }
    applyDefaults();
    clearGenerated();
    render();
  }

  function useUploadedPassport(file) {
    if (!Intake.isAcceptedFile(file)) {
      st.passportStatus = "Not a PDF, JPG or PNG.";
      renderSource();
      return;
    }
    st.passportStatus = "Reading passport…";
    renderSource();
    Intake.readPassport(file, function (msg) {
      st.passportStatus = msg;
      renderSource();
    }).then(
      function (record) {
        var person = Intake.personPatchFromPassport(record);
        var ctx = contextFor(st.appId ? S.getApplication(st.appId) : null, person);
        // Only the passport's own fields: keep trip / hotel values already here.
        var before = Object.assign({}, st.values);
        var n = prefill({ applicant: ctx.applicant, travel: {}, hotel: {} }, "passport");
        Object.keys(before).forEach(function (k) {
          if (st.filledFrom[k] !== "passport") st.values[k] = before[k];
        });
        st.passportStatus = n + " field" + (n === 1 ? "" : "s") + " filled from " + file.name + (record.flags.length ? " — " + record.flags.join(" · ") : "");
        applyDefaults();
        clearGenerated();
        render();
      },
      function (err) {
        st.passportStatus = (err && err.message) || "The passport could not be read.";
        renderSource();
      }
    );
  }

  /* ---- Hotel details: Hotel Blocking, a hotel voucher, or the application ---- */

  var HOTEL_TO_GUARANTOR = { hotelName: "guarantorName", hotelTel: "guarantorTel", hotelAddress: "guarantorAddress" };

  /** Fills the form's hotel lines from one hotel record; the guarantor (the
   * hotel, in the Khanna sample) follows when it is empty or was the old hotel. */
  function applyHotel(hotel, origin) {
    var next = {
      hotelName: (hotel.hotelName || "").trim(),
      hotelTel: (hotel.phone || "").trim(),
      hotelAddress: joinParts([hotel.address, hotel.city, hotel.country]),
    };
    var count = 0;
    Object.keys(next).forEach(function (key) {
      if (!next[key]) return;
      var g = HOTEL_TO_GUARANTOR[key];
      var guarantorFollows = !st.values[g] || st.values[g] === st.values[key];
      st.values[key] = next[key];
      st.filledFrom[key] = origin;
      count += 1;
      if (guarantorFollows) {
        st.values[g] = next[key];
        st.filledFrom[g] = origin;
        if (!st.values.guarantorRelationship || st.values.guarantorRelationship === "-") st.values.guarantorRelationship = "HOTEL";
      }
    });
    return count;
  }

  function earliestHotel(hotels) {
    return (hotels || []).filter(function (h) { return (h.hotelName || "").trim(); }).slice().sort(function (a, b) {
      return String(a.checkIn || "9999").localeCompare(String(b.checkIn || "9999"));
    })[0] || null;
  }

  function useHotelBlocking(appId) {
    var app = S.getApplication(appId);
    var hotel = app && earliestHotel(app.hotels);
    st.hotelListOpen = false;
    if (!hotel) {
      st.hotelStatus = "That hotel blocking has no hotel name yet.";
    } else {
      applyHotel(hotel, "hotel-blocking");
      var count = (app.hotels || []).filter(function (h) { return (h.hotelName || "").trim(); }).length;
      st.hotelStatus = "Hotel details from Hotel Blocking: " + hotel.hotelName + (count > 1 ? " (the first of " + count + " hotels, by check-in date)" : "");
    }
    clearGenerated();
    render();
  }

  function useHotelVoucher(file) {
    if (!Intake.isAcceptedFile(file)) {
      st.hotelStatus = "Not a PDF, JPG or PNG.";
      renderSource();
      return;
    }
    st.hotelStatus = "Reading hotel voucher…";
    renderSource();
    Intake.readVoucher(file, function (msg) {
      st.hotelStatus = msg;
      renderSource();
    }).then(
      function (record) {
        var hotel = earliestHotel(record.hotels);
        if (!hotel) {
          st.hotelStatus = "No hotel name could be read from " + file.name + ". " + (record.flags || []).join(" · ");
        } else {
          applyHotel(hotel, "voucher");
          st.hotelStatus = "Hotel details from " + file.name + ": " + hotel.hotelName +
            (hotel.lookupSource ? " (address / phone looked up on " + hotel.lookupSource + ")" : "") +
            ((record.flags || []).length ? " — " + record.flags.join(" · ") : "");
        }
        clearGenerated();
        render();
      },
      function (err) {
        st.hotelStatus = (err && err.message) || "The hotel voucher could not be read.";
        renderSource();
      }
    );
  }

  /* ---- Flight booking: arrival in the destination country, port, airline, stay ---- */

  function useFlightBooking(file) {
    var form = currentForm();
    if (!Intake.isAcceptedFile(file)) {
      st.flightStatus = "Not a PDF, JPG or PNG.";
      renderSource();
      return;
    }
    st.flightStatus = "Reading flight booking…";
    st.flight = null;
    renderSource();
    api.readFlightBooking(file, (form && form.country) || "Japan").then(
      function (res) {
        st.flight = res;
        if (res.status !== "ok") {
          st.flightStatus = (res.warnings || []).join(" ") || "No usable flights were found.";
        } else {
          var filled = [];
          function put(key, value) {
            if (!value) return;
            st.values[key] = value;
            st.filledFrom[key] = "flight";
            filled.push(key);
          }
          put("arrivalDate", displayDate(res.arrivalDate));
          put("lengthOfStay", res.lengthOfStay);
          put("portOfEntry", res.portOfEntry);
          put("airline", res.airline);
          st.flightStatus = filled.length + " field" + (filled.length === 1 ? "" : "s") + " filled from " + file.name + ".";
        }
        clearGenerated();
        render();
      },
      function (err) {
        st.flightStatus = (err && err.message) || "The flight booking could not be read.";
        renderSource();
      }
    );
  }

  function flightHtml() {
    var f = st.flight;
    if (!f || !(f.legs || []).length) return "";
    var role = { arrival: "Arrival into " + ((currentForm() || {}).country || "the country"), departure: "Leaving the country", domestic: "Connection inside the country" };
    return (
      '<div class="vf-table-wrap"><table class="vf-table vf-legs"><thead><tr><th>Flight</th><th>Departs</th><th>Lands</th><th>Used as</th></tr></thead><tbody>' +
      f.legs.map(function (l) {
        return (
          '<tr class="' + (l.role === "arrival" || l.role === "departure" ? "vf-leg--used" : "") + '">' +
          '<td data-th="Flight">' + esc([l.airline, l.flightNo].filter(Boolean).join(" ")) + "</td>" +
          '<td data-th="Departs">' + esc(displayDate(l.depDate) + " " + (l.depTime || "")) + '<span class="vf-source">' + esc(l.from) + "</span></td>" +
          '<td data-th="Lands">' + esc(displayDate(l.arrDate) + " " + (l.arrTime || "")) + (l.arrivalDateCertain ? "" : " (?)") + '<span class="vf-source">' + esc(l.to) + "</span></td>" +
          '<td data-th="Used as">' + esc(role[l.role] || "—") + "</td></tr>"
        );
      }).join("") +
      "</tbody></table></div>" +
      ((f.warnings || []).length ? '<p class="field-hint">' + f.warnings.map(esc).join(" ") + "</p>" : "")
    );
  }

  function hotelListHtml() {
    if (!st.hotelListOpen) return "";
    var Saved = global.KhannaSavedDetails;
    var sources = Saved ? Saved.hotelBlockingSources() : [];
    if (!sources.length) return '<p class="field-hint">No hotel blockings saved yet.</p>';
    return (
      '<div class="vf-pick-list" role="list">' +
      sources.map(function (a) {
        var hotels = Saved.usableHotels(a);
        var span = Saved.hotelDateSpan(hotels);
        return (
          '<button type="button" class="vf-pick" role="listitem" data-ff-hotel-app="' + esc(a.id) + '">' +
          "<strong>" + esc(Saved.appLabel(a)) + "</strong>" +
          '<span class="vf-source">' + esc(hotels.map(function (h) { return h.hotelName || "Unnamed hotel"; }).join(", ")) +
          (span.start ? " · " + esc(utils.formatDate(span.start) + (span.end ? " → " + utils.formatDate(span.end) : "")) : "") + "</span>" +
          "</button>"
        );
      }).join("") +
      "</div>"
    );
  }

  function saveToApplication() {
    if (!st.appId || !S.getApplication(st.appId)) return;
    var patch = { visaForms: {} };
    patch.visaForms[st.formId] = { personId: st.personId, values: Object.assign({}, st.values), updatedAt: new Date().toISOString() };
    S.updateApplication(st.appId, patch);
  }

  /* ----------------------------------------------------------------------
   * Rendering
   * -------------------------------------------------------------------- */

  function originTag(key) {
    var o = st.filledFrom[key];
    if (o === "passport") return '<span class="vf-tag vf-tag--verify">' + VERIFY + "</span>";
    if (o === "application") return '<span class="vf-tag">From application — please verify</span>';
    if (o === "voucher") return '<span class="vf-tag vf-tag--verify">From hotel voucher — ' + VERIFY + "</span>";
    if (o === "hotel-blocking") return '<span class="vf-tag">From Hotel Blocking — please verify</span>';
    if (o === "flight") return '<span class="vf-tag vf-tag--verify">From flight booking — please verify</span>';
    return "";
  }

  function inputHtml(field, extraClass) {
    var id = "ff-" + field.key;
    var value = st.values[field.key] || "";
    var max = field.maxLength ? ' maxlength="' + field.maxLength + '"' : "";
    var label = '<label for="' + id + '">' + esc(field.label) + (field.required ? ' <span class="vf-req" aria-hidden="true">*</span>' : "") + "</label>";
    var help = field.help ? '<span class="field-hint">' + esc(field.help) + "</span>" : "";
    var control;
    if (field.type === "radio" || field.type === "yesno") {
      var name = "ffr-" + field.key;
      control =
        '<div class="vf-radios" role="radiogroup" aria-labelledby="' + id + '-l">' +
        (field.options || []).map(function (o) {
          return '<label class="vf-radio"><input type="radio" name="' + name + '" value="' + esc(o.value) + '" data-ff-key="' + field.key + '"' +
            (String(value).toLowerCase() === o.value.toLowerCase() ? " checked" : "") + " /> " + esc(o.label) + "</label>";
        }).join("") +
        (value ? '<button type="button" class="btn btn-ghost btn-sm" data-ff-clear="' + field.key + '">Clear</button>' : "") +
        "</div>";
      label = '<span class="vf-label" id="' + id + '-l">' + esc(field.label) + (field.required ? ' <span class="vf-req" aria-hidden="true">*</span>' : "") + "</span>";
    } else if (field.type === "textarea") {
      control = '<textarea id="' + id + '" rows="2" data-ff-key="' + field.key + '"' + max + ">" + esc(value) + "</textarea>";
    } else if (field.type === "date") {
      var bad = value && !reviewForm.parseDate(value);
      control = '<input id="' + id + '" type="text" inputmode="numeric" placeholder="DD-MM-YYYY" maxlength="10" data-ff-key="' + field.key + '" data-date="1" value="' + esc(value) + '" aria-invalid="' + (bad ? "true" : "false") + '" />';
    } else {
      control = '<input id="' + id + '" type="text" data-ff-key="' + field.key + '" value="' + esc(value) + '"' + max + " />";
    }
    return '<div class="field vf-field ' + (extraClass || "") + (field.type === "yesno" ? " vf-field--yesno" : "") + '">' + label + control + originTag(field.key) + help + "</div>";
  }

  function sectionHtml(section) {
    var fields = section.fields.map(function (field) {
      if (field.type === "columns") {
        return (
          '<fieldset class="vf-columns"><legend>' + esc(field.label) + "</legend>" +
          '<div class="vf-grid">' + field.parts.map(function (p) { return inputHtml(p); }).join("") + "</div></fieldset>"
        );
      }
      return inputHtml(field, field.type === "textarea" || field.type === "yesno" ? "vf-field--wide" : "");
    }).join("");
    var tools = "";
    if (section.copyFrom) tools += '<button type="button" class="btn btn-secondary btn-sm" data-ff-copy="' + esc(section.title) + '">' + esc(section.copyFrom.label) + "</button>";
    if (section.kind === "declaration") tools += '<button type="button" class="btn btn-secondary btn-sm" data-ff-all-no>Applicant answered No to all</button>';
    return (
      '<section class="vf-section"><h3>' + esc(section.title) + "</h3>" +
      (section.help ? '<p class="field-hint">' + esc(section.help) + "</p>" : "") +
      (tools ? '<div class="vf-row-actions">' + tools + "</div>" : "") +
      '<div class="vf-grid">' + fields + "</div></section>"
    );
  }

  function sourceHtml() {
    var app = st.appId ? S.getApplication(st.appId) : null;
    var people = app ? People.peopleOfApplication(app) : [];
    var personSelect = people.length > 1
      ? '<div class="field vf-person"><label for="ffPerson">Person</label><select id="ffPerson" data-ff-person>' +
        people.map(function (p) { return '<option value="' + esc(p.id) + '"' + (p.id === st.personId ? " selected" : "") + ">" + esc(People.displayName(p.details) + " — " + p.role) + "</option>"; }).join("") +
        "</select></div>"
      : "";
    var accept = 'accept=".pdf,.jpg,.jpeg,.png,application/pdf,image/jpeg,image/png"';
    return (
      '<div class="vf-source-group"><h3>Applicant</h3>' +
      '<div class="vf-row-actions">' +
      '<button type="button" class="btn btn-secondary btn-sm" data-ff-use-app>Use Existing Application</button>' +
      '<label class="btn btn-secondary btn-sm vf-file-btn">Upload Passport<input type="file" ' + accept + " data-ff-passport /></label>" +
      '<button type="button" class="btn btn-ghost btn-sm" data-ff-reset>Start empty</button>' +
      "</div>" +
      (app ? '<p class="field-hint">Application: <strong>' + esc(People.displayName(People.fromPerson(app.applicant))) + "</strong>" + (st.sourceLabel ? " · " + esc(st.sourceLabel) : "") + "</p>" : "") +
      personSelect +
      (st.passportStatus ? '<p class="field-hint" role="status">' + esc(st.passportStatus) + "</p>" : "") +
      "</div>" +
      '<div class="vf-source-group"><h3>Hotel</h3>' +
      '<div class="vf-row-actions">' +
      '<button type="button" class="btn btn-secondary btn-sm" data-ff-hotel-list aria-expanded="' + (st.hotelListOpen ? "true" : "false") + '">Use Hotel Blocking</button>' +
      '<label class="btn btn-secondary btn-sm vf-file-btn">Upload Hotel Voucher<input type="file" ' + accept + " data-ff-voucher /></label>" +
      "</div>" + hotelListHtml() +
      (st.hotelStatus ? '<p class="field-hint" role="status">' + esc(st.hotelStatus) + "</p>" : "") +
      "</div>" +
      '<div class="vf-source-group"><h3>Flights</h3>' +
      '<p class="field-hint">The arrival date is the day the flight lands in ' + esc((currentForm() || {}).country || "the country") +
      " — connections inside the country are skipped. Length of stay counts the arrival and departure days.</p>" +
      '<div class="vf-row-actions">' +
      '<label class="btn btn-secondary btn-sm vf-file-btn">Upload Flight Booking<input type="file" ' + accept + " data-ff-flight /></label>" +
      "</div>" +
      (st.flightStatus ? '<p class="field-hint" role="status">' + esc(st.flightStatus) + "</p>" : "") +
      flightHtml() +
      "</div>"
    );
  }

  function missingRequired() {
    var form = currentForm();
    var out = [];
    if (!form) return out;
    eachField(form, function (field, section, parent) {
      if (parent) return;
      if (field.required && !String(st.values[field.key] || "").trim()) out.push(field.label);
    });
    return out;
  }

  function invalidDates() {
    var form = currentForm();
    var out = [];
    if (!form) return out;
    eachField(form, function (field) {
      var v = st.values[field.key];
      if (field.type === "date" && v && !reviewForm.parseDate(v)) out.push(field.label);
    });
    return out;
  }

  function generateHtml() {
    var missing = missingRequired();
    var bad = invalidDates();
    var parts = [];
    if (bad.length) parts.push('<p class="ud-warn">Not a valid DD-MM-YYYY date: ' + bad.map(esc).join(", ") + ".</p>");
    if (missing.length) parts.push('<p class="field-hint">Still empty (they will be blank on the form): ' + missing.map(esc).join("; ") + ".</p>");
    if (st.error) parts.push('<p class="ud-warn">' + esc(st.error) + "</p>");
    var actions =
      '<div class="vf-row-actions"><button type="button" class="btn btn-primary" data-ff-generate' + (bad.length || st.generating ? " disabled" : "") + ">" +
      (st.generating ? "Filling the form…" : st.generated ? "Generate again" : "Generate filled form (PDF)") + "</button>" +
      (st.generated ? '<button type="button" class="btn btn-secondary" data-ff-download>Download PDF</button>' : "") +
      "</div>";
    if (st.generated && st.generated.overflow.length) {
      parts.push('<p class="ud-warn">Too long to fit in the box even in the smallest letters — shorten it, or the end will be cut off on the printed form: ' +
        st.generated.overflow.map(esc).join("; ") + ".</p>");
    }
    var preview = st.generated
      ? '<p class="field-hint">Long text continues on the next line of its box, or is printed in smaller letters so it stays inside the form. The PDF stays fillable — any field can still be corrected in Adobe Reader before printing. Check every page before submitting.</p>' +
        '<iframe class="vf-preview" title="Filled form preview" src="' + st.generated.url + '"></iframe>'
      : "";
    return parts.join("") + actions + preview;
  }

  function renderSource() {
    var el = utils.qs("[data-ff-source]", root());
    if (el) el.innerHTML = sourceHtml();
  }

  function renderGenerate() {
    var el = utils.qs("[data-ff-generate-area]", root());
    if (el) el.innerHTML = generateHtml();
  }

  function render() {
    var r = root();
    if (!r) return;
    if (st.forms === null) {
      r.innerHTML = '<p class="field-hint">Loading forms…</p>';
      return;
    }
    if (st.loadError) {
      r.innerHTML = '<div class="ud-layout"><p class="ud-warn">' + esc(st.loadError) + '</p><div><button type="button" class="btn btn-secondary btn-sm" data-ff-retry>Try again</button></div></div>';
      return;
    }
    var form = currentForm();
    var options = st.forms.map(function (f) {
      return '<option value="' + esc(f.id) + '"' + (f.id === st.formId ? " selected" : "") + (f.available ? "" : " disabled") + ">" + esc(f.name) + (f.available ? "" : " (file missing)") + "</option>";
    }).join("");
    r.innerHTML =
      '<div class="ud-layout vf-layout">' +
      '<section class="card ud-card">' +
      '<h2 class="ud-card__title"><span class="ud-step">1</span> Form</h2>' +
      '<div class="field"><label for="ffForm">Form to fill</label><select id="ffForm" data-ff-form>' + options + "</select></div>" +
      (form && form.notes ? '<ul class="vf-notes">' + form.notes.map(function (n) { return "<li>" + esc(n) + "</li>"; }).join("") + "</ul>" : "") +
      "</section>" +
      '<section class="card ud-card">' +
      '<h2 class="ud-card__title"><span class="ud-step">2</span> Fill from</h2>' +
      '<div data-ff-source>' + sourceHtml() + "</div>" +
      "</section>" +
      '<section class="card ud-card vf-form-card">' +
      '<h2 class="ud-card__title"><span class="ud-step">3</span> Form details</h2>' +
      '<p class="field-hint">Printed on the form in CAPITAL letters. <span class="vf-req">*</span> = needed on the form.</p>' +
      (form ? form.sections.map(sectionHtml).join("") : "") +
      "</section>" +
      '<section class="card ud-card">' +
      '<h2 class="ud-card__title"><span class="ud-step">4</span> Generate</h2>' +
      '<div data-ff-generate-area>' + generateHtml() + "</div>" +
      "</section>" +
      "</div>";
  }

  /* ----------------------------------------------------------------------
   * Actions
   * -------------------------------------------------------------------- */

  function clearGenerated() {
    if (st.generated && st.generated.url) URL.revokeObjectURL(st.generated.url);
    st.generated = null;
    st.error = "";
  }

  function applicantNameForFile() {
    return [st.values.givenNames, st.values.surname].filter(Boolean).join(" ");
  }

  function generate() {
    if (st.generating || invalidDates().length) return;
    st.generating = true;
    st.error = "";
    renderGenerate();
    saveToApplication();
    api.fillVisaForm(st.formId, Object.assign({}, st.values), applicantNameForFile()).then(
      function (res) {
        clearGenerated();
        st.generated = { blob: res.blob, filename: res.filename, url: URL.createObjectURL(res.blob), overflow: res.overflow || [] };
      },
      function (err) {
        st.error = (err && err.message) || "The form could not be filled.";
      }
    ).then(function () {
      st.generating = false;
      renderGenerate();
    });
  }

  function loadForms() {
    st.forms = null;
    st.loadError = "";
    render();
    api.listVisaForms().then(
      function (res) {
        st.forms = res.forms || [];
        if (!st.forms.length) st.loadError = "No forms are available on the backend yet.";
        if (!st.formId && st.forms.length) st.formId = st.forms[0].id;
        applyDefaults();
        render();
      },
      function (err) {
        st.forms = [];
        st.loadError = (err && err.message) || "The list of forms could not be loaded.";
        render();
      }
    );
  }

  function wire(r) {
    utils.on(r, "click", "[data-ff-retry]", loadForms);
    utils.on(r, "change", "[data-ff-form]", function (e, sel) {
      st.formId = sel.value;
      st.values = {};
      st.filledFrom = {};
      if (st.appId && S.getApplication(st.appId)) useApplication(S.getApplication(st.appId), st.personId);
      else {
        applyDefaults();
        clearGenerated();
        render();
      }
    });
    utils.on(r, "click", "[data-ff-use-app]", function (e, btn) {
      if (!global.KhannaApplicationPicker) return;
      global.KhannaApplicationPicker.open(btn, function (app) { useApplication(app, "applicant"); });
    });
    utils.on(r, "change", "[data-ff-person]", function (e, sel) {
      var app = S.getApplication(st.appId);
      if (app) useApplication(app, sel.value);
    });
    utils.on(r, "change", "[data-ff-passport]", function (e, input) {
      var file = input.files && input.files[0];
      input.value = "";
      if (file) useUploadedPassport(file);
    });
    utils.on(r, "click", "[data-ff-hotel-list]", function () {
      st.hotelListOpen = !st.hotelListOpen;
      renderSource();
    });
    utils.on(r, "click", "[data-ff-hotel-app]", function (e, btn) {
      useHotelBlocking(btn.getAttribute("data-ff-hotel-app"));
    });
    utils.on(r, "change", "[data-ff-voucher]", function (e, input) {
      var file = input.files && input.files[0];
      input.value = "";
      if (file) useHotelVoucher(file);
    });
    utils.on(r, "change", "[data-ff-flight]", function (e, input) {
      var file = input.files && input.files[0];
      input.value = "";
      if (file) useFlightBooking(file);
    });
    utils.on(r, "click", "[data-ff-reset]", function () {
      st.appId = null;
      st.personId = "applicant";
      st.values = {};
      st.filledFrom = {};
      st.sourceLabel = "";
      st.passportStatus = "";
      st.hotelStatus = "";
      st.flightStatus = "";
      st.flight = null;
      applyDefaults();
      clearGenerated();
      render();
    });
    function onValue(e, input) {
      var key = input.getAttribute("data-ff-key");
      // "change" also fires when a box loses focus — e.g. on the way to
      // clicking Generate. Nothing changed then, so do not redraw (a redraw
      // would replace the button under the click).
      if (st.values[key] === input.value && input.type !== "radio") return;
      st.values[key] = input.value;
      delete st.filledFrom[key];
      if (input.hasAttribute("data-date")) input.setAttribute("aria-invalid", input.value && !reviewForm.parseDate(input.value) ? "true" : "false");
      if (st.generated) clearGenerated();
      renderGenerate();
    }
    utils.on(r, "input", "[data-ff-key]", onValue);
    utils.on(r, "change", "[data-ff-key]", function (e, input) {
      onValue(e, input);
      if (input.type === "radio") render();
    });
    utils.on(r, "click", "[data-ff-clear]", function (e, btn) {
      delete st.values[btn.getAttribute("data-ff-clear")];
      clearGenerated();
      render();
    });
    utils.on(r, "click", "[data-ff-all-no]", function () {
      var form = currentForm();
      if (!form) return;
      form.sections.forEach(function (s) {
        if (s.kind !== "declaration") return;
        s.fields.forEach(function (f) { if (f.type === "yesno") st.values[f.key] = "no"; });
      });
      clearGenerated();
      render();
    });
    utils.on(r, "click", "[data-ff-copy]", function (e, btn) {
      var form = currentForm();
      var section = form && form.sections.filter(function (s) { return s.title === btn.getAttribute("data-ff-copy"); })[0];
      if (!section || !section.copyFrom) return;
      Object.keys(section.copyFrom.map || {}).forEach(function (to) {
        st.values[to] = st.values[section.copyFrom.map[to]] || "";
      });
      Object.keys(section.copyFrom.set || {}).forEach(function (to) {
        st.values[to] = section.copyFrom.set[to];
      });
      clearGenerated();
      render();
    });
    utils.on(r, "click", "[data-ff-generate]", generate);
    utils.on(r, "click", "[data-ff-download]", function () {
      if (st.generated) utils.triggerFileDownload(st.generated.blob, st.generated.filename);
    });
  }

  function build() {
    var r = root();
    if (!r) return;
    if (!built) {
      built = true;
      wire(r);
      loadForms();
      return;
    }
    if (st.forms && st.forms.length === 0 && st.loadError) loadForms();
  }

  function init() {
    document.addEventListener("khanna:navigate", function (e) {
      if (e.detail.view !== "fill-forms") return;
      build();
    });
    if (location.hash.indexOf("fill-forms") !== -1) build();
  }

  global.KhannaFillForms = { build: build, _state: st };

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})(window);
