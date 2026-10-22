/* ==========================================================================
   Khanna Travels & Holidays — Saved details (shared "Use Existing Details")
   The pure data half of the "Use Existing Details ▾" dropdown that first
   shipped on the Cover Letter page, pulled out so the Invitation Letter page
   uses the exact same lists instead of a second copy (project rule 15):

     - passportSources(): every saved person with a name or passport number,
       from BOTH places passports live — the applications themselves (newest
       first) and the reusable applicant/traveller profile pool (which still
       holds people whose application was deleted). One entry per passport
       number; people without a number are told apart by name.
     - hotelBlockingSources(): applications that have a hotel saved on Hotel
       Blocking, newest first.
     - listHtml(kind, pickAttr): the small scrollable list shown beside the
       menu. `pickAttr` is the data-attribute each row carries
       (e.g. "data-cover-existing-pick") so every page keeps its own
       click-handler selector.

   Read-only: nothing in here changes an application or a profile.
   ========================================================================== */
(function (global) {
  "use strict";

  var utils = global.KhannaUtils;

  function appLabel(app) {
    return global.KhannaApplicationsList ? global.KhannaApplicationsList.applicantLabel(app) : "Application";
  }

  function newestFirst(apps) {
    return apps.slice().sort(function (a, b) {
      return a.updatedAt < b.updatedAt ? 1 : a.updatedAt > b.updatedAt ? -1 : 0;
    });
  }

  function hasNameOrPassport(p) {
    return !!((p.fullName || "").trim() || (p.passportNumber || "").trim());
  }

  function recordToRow(rec, id, isApplicant, relation) {
    var cur = (rec.passport && rec.passport.current) || {};
    var fullName = (rec.fullName || [rec.firstName, rec.lastName].filter(Boolean).join(" ") || "").trim();
    return {
      id: id,
      isApplicant: !!isApplicant,
      relation: relation || "",
      salutation: rec.salutation || "",
      fullName: fullName,
      sex: rec.sex || "",
      passportNumber: (cur.number || "").trim(),
      placeOfIssue: cur.issuePlace || "",
      passportIssueDate: cur.issueDate || "",
      phone: (rec.contact && rec.contact.phone) || "",
      email: (rec.contact && rec.contact.email) || "",
    };
  }

  // Each entry: { key, appId, appLabel, row, address, record }. `record` is
  // the full saved person (so a page that must add them to the active
  // application can copy everything, not just the letter fields).
  function passportSources() {
    var seen = {};
    var out = [];
    function add(row, rec, appId, label) {
      if (!hasNameOrPassport(row)) return;
      var key = row.passportNumber ? row.passportNumber.toUpperCase() : "NAME:" + row.fullName.toLowerCase();
      if (seen[key]) return;
      seen[key] = true;
      out.push({ key: key, appId: appId, appLabel: label, row: row, address: (rec && rec.address) || {}, record: rec });
    }
    newestFirst(global.KhannaState.getApplications()).forEach(function (a) {
      var label = appLabel(a);
      if (a.applicant) add(recordToRow(a.applicant, "applicant", true, ""), a.applicant, a.id, label);
      (a.travellers || []).forEach(function (t) {
        add(recordToRow(t, t.id, false, t.relation), t, a.id, label);
      });
    });
    var S = global.KhannaState;
    (S.getApplicantProfiles ? S.getApplicantProfiles() : []).forEach(function (pr) {
      add(recordToRow(pr, pr.id, true, ""), pr, null, "Saved applicant profile");
    });
    (S.getTravellerProfiles ? S.getTravellerProfiles() : []).forEach(function (pr) {
      add(recordToRow(pr, pr.id, false, pr.relation), pr, null, "Saved traveller profile");
    });
    return out;
  }

  function usableHotels(app) {
    return (app.hotels || []).filter(function (h) { return h.hotelName || h.checkIn || h.checkOut || h.city; });
  }

  // Every application whose Hotel Blocking holds at least one hotel with real
  // details (a name, a date or a city), newest first. A blocking with only
  // empty hotel rows is nothing to reuse — it is not listed here or on Recent
  // Hotel Blockings, and Save refuses it (js/document-workspace.js).
  function hotelBlockingSources() {
    return newestFirst(global.KhannaState.getApplications()).filter(function (a) {
      return usableHotels(a).length > 0;
    });
  }

  function hotelDateSpan(hotels) {
    var ins = hotels.map(function (h) { return h.checkIn; }).filter(Boolean).sort();
    var outs = hotels.map(function (h) { return h.checkOut; }).filter(Boolean).sort();
    return { start: ins[0] || "", end: outs[outs.length - 1] || "" };
  }

  function listHtml(kind, pickAttr) {
    if (kind === "passport") {
      var passports = passportSources();
      if (!passports.length) {
        return '<p class="field-hint cover-existing-list__empty">No saved passports yet.</p>';
      }
      var auth = global.KhannaAuthorization;
      return (
        '<div class="cover-existing-list__title">Previous passports</div>' +
        passports.map(function (src) {
          return (
            '<button type="button" class="cover-existing-item" ' + pickAttr + '="passport" data-passport-key="' + utils.escapeHtml(src.key) + '">' +
            '<span class="cover-existing-item__name">' + utils.escapeHtml(auth.personDisplayName(src.row)) + "</span>" +
            '<span class="cover-existing-item__meta">' +
            (src.row.passportNumber ? "Passport " + utils.escapeHtml(src.row.passportNumber) : "No passport number on file") +
            " · " + utils.escapeHtml(src.appLabel) + "</span>" +
            "</button>"
          );
        }).join("")
      );
    }
    var blockings = hotelBlockingSources();
    if (!blockings.length) {
      return '<p class="field-hint cover-existing-list__empty">No hotel blockings yet.</p>';
    }
    return (
      '<div class="cover-existing-list__title">Previous hotel blockings</div>' +
      blockings.map(function (a) {
        var hotels = usableHotels(a);
        var span = hotelDateSpan(hotels);
        var names = hotels.map(function (h) { return h.hotelName || "Unnamed hotel"; }).join(", ");
        return (
          '<button type="button" class="cover-existing-item" ' + pickAttr + '="hotel-blocking" data-app-id="' + utils.escapeHtml(a.id) + '">' +
          '<span class="cover-existing-item__name">' + utils.escapeHtml(appLabel(a)) + "</span>" +
          '<span class="cover-existing-item__meta">' + hotels.length + (hotels.length === 1 ? " hotel" : " hotels") +
          (names ? " · " + utils.escapeHtml(names) : "") +
          (span.start && span.end ? " · " + utils.escapeHtml(utils.formatDate(span.start) + " → " + utils.formatDate(span.end)) : " · Dates not set") +
          (a.updatedAt ? " · Updated " + utils.escapeHtml(utils.formatDateTime(a.updatedAt)) : "") +
          "</span>" +
          "</button>"
        );
      }).join("")
    );
  }

  // Is this saved passport the same person as an on-application person row?
  function samePassportPerson(person, src) {
    var num = (person.passportNumber || "").trim().toUpperCase();
    if (src.row.passportNumber) return num === src.key;
    return !num && (person.fullName || "").trim().toLowerCase() === src.row.fullName.toLowerCase();
  }

  // Copies a saved person (from another application or the profile pool)
  // onto the active application as a new traveller; the source is untouched.
  // Returns the new traveller's id.
  function addSavedPersonAsTraveller(app, src) {
    var copy = JSON.parse(JSON.stringify(src.record || {}));
    ["id", "kind", "createdAt", "updatedAt", "applicantId"].forEach(function (k) { delete copy[k]; });
    if (src.row.isApplicant) delete copy.profileId; // that id points into the applicant pool, not the traveller pool
    copy.id = utils.generateId("TRV");
    copy.relation = src.row.isApplicant ? "" : src.row.relation || "";
    var travellers = (app.travellers || []).concat([copy]);
    global.KhannaState.updateApplication(
      app.id,
      { travellers: travellers },
      'Traveller "' + (src.row.fullName || "Untitled traveller") + '" added from saved passports'
    );
    return copy.id;
  }

  global.KhannaSavedDetails = {
    samePassportPerson: samePassportPerson,
    addSavedPersonAsTraveller: addSavedPersonAsTraveller,
    appLabel: appLabel,
    hasNameOrPassport: hasNameOrPassport,
    passportSources: passportSources,
    hotelBlockingSources: hotelBlockingSources,
    usableHotels: usableHotels,
    hotelDateSpan: hotelDateSpan,
    listHtml: listHtml,
  };
})(window);
