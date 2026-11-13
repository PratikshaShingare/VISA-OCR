/* ==========================================================================
   Khanna Travels & Holidays — Applicant Profiles page ("#/applicant-profiles")
   One saved profile per person (applicants and travellers read from their
   passports). A profile keeps the basic details staff type once — phone,
   email, occupation, education, employer, marital status / spouse, income,
   emergency contact — so letters and visa forms fill them in instead of the
   same things being typed again for every application.

   What this page does NOT do:
     - create people: a profile appears when a passport is saved (Upload
       Passport / Upload Documents); "New profile" goes there.
     - edit passport data: name, passport number, date of birth, nationality
       and the residential address are shown read-only. They come from the
       passport, and are corrected on the passport page (project rule 10).

   Saving copies the values to every copy of the same person (both profile
   pools and every saved application) through KhannaState.savePersonBasics.
   ========================================================================== */
(function (global) {
  "use strict";

  var utils = global.KhannaUtils;
  var S = global.KhannaState;
  var D = global.KhannaApplicantDetails;
  var Panel = global.KhannaClientDetailsPanel; // "Get basic details from the client" (js/client-details-panel.js)

  var st = {
    query: "",
    selectedId: null, // profile id being edited, or null for the list
    draft: null, // { details: {...}, contact: {...} } typed but not saved yet
    saved: false, // show "Saved" after a save until the next edit
    fromReply: {}, // "details.religion": true — filled from the client's reply, not saved yet
  };

  var TRASH_ICON = '<svg class="icon icon-sm" viewBox="0 0 24 24" aria-hidden="true"><path d="M4 7h16M9 7V5a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2m2 0-1 13a1 1 0 0 1-1 1H8a1 1 0 0 1-1-1L6 7"/></svg>';

  function root() {
    return utils.qs("[data-applicant-profiles-root]");
  }

  function esc(v) {
    return utils.escapeHtml(v);
  }

  function trim(v) {
    return v === null || v === undefined ? "" : String(v).trim();
  }

  /* ---- who is listed ---- */

  function passportOf(p) {
    return (p.passport && p.passport.current) || {};
  }

  function dedupeKey(p) {
    var n = trim(passportOf(p).number).toUpperCase();
    if (n) return "pp:" + n;
    return "nd:" + trim(p.fullName).toLowerCase() + "|" + trim(p.dob);
  }

  /** Applicant-pool people first, then traveller-pool people not already listed. */
  function people() {
    var seen = {};
    var out = [];
    function add(p, kind) {
      if (!trim(p.fullName) && !trim(passportOf(p).number)) return;
      var k = dedupeKey(p);
      if (seen[k]) return;
      seen[k] = true;
      out.push({ profile: p, kind: kind });
    }
    (S.getApplicantProfiles() || []).forEach(function (p) { add(p, "Applicant"); });
    (S.getTravellerProfiles() || []).forEach(function (p) { add(p, "Traveller"); });
    return out;
  }

  function findById(id) {
    return people().filter(function (x) { return x.profile.id === id; })[0] || null;
  }

  function haystack(x) {
    var p = x.profile;
    var d = D.of(p);
    return [p.fullName, passportOf(p).number, d.phone, d.email, d.occupation, d.employerName].join(" ").toLowerCase();
  }

  /* ---- list ---- */

  function rowHtml(x) {
    var p = x.profile;
    var d = D.of(p);
    var line = [D.occupationLine(d), d.phone, d.email].filter(Boolean).join(" · ");
    var passport = trim(passportOf(p).number);
    return (
      '<div class="card hb-row ap-row">' +
      '<div class="hb-row__info">' +
      '<div class="hb-row__name">' + esc(p.fullName || "Unnamed") + ' <span class="badge ap-kind">' + esc(x.kind) + "</span></div>" +
      '<div class="hb-row__meta">' + (passport ? "Passport " + esc(passport) : "No passport number") + (p.nationality ? " · " + esc(p.nationality) : "") + "</div>" +
      '<div class="hb-row__meta ' + (line ? "" : "hb-row__meta--faint") + '">' + (line ? esc(line) : "No basic details saved yet") + "</div>" +
      "</div>" +
      '<div class="hb-row__actions"><button type="button" class="btn btn-secondary btn-sm" data-ap-open="' + esc(p.id) + '">' +
      (line ? "Open" : "Add details") + "</button>" +
      '<button type="button" class="btn btn-ghost btn-sm ap-delete" data-ap-delete="' + esc(p.id) + '" aria-label="Delete ' + esc(p.fullName || "this profile") + '">' + TRASH_ICON + "Delete</button>" +
      "</div>" +
      "</div>"
    );
  }

  function listHtml() {
    var all = people();
    var q = trim(st.query).toLowerCase();
    var shown = q ? all.filter(function (x) { return haystack(x).indexOf(q) !== -1; }) : all;
    var intro =
      '<p class="ap-intro">Save an applicant\'s phone, email, occupation and other basic details <strong>once</strong>. ' +
      "Cover letters, invitation letters and the visa form then fill them in for you.</p>";
    var bar =
      '<div class="ap-bar">' +
      '<div class="field ap-search"><label for="apSearch">Search</label>' +
      '<input id="apSearch" type="search" placeholder="Name, passport number, phone…" value="' + esc(st.query) + '" data-ap-search /></div>' +
      '<a class="btn btn-primary btn-sm" href="#/upload-passport" data-nav-link="upload-passport">New profile (upload passport)</a>' +
      "</div>";
    if (!all.length) {
      return (
        intro + (Panel ? Panel.listHtml() : "") +
        '<div class="empty-state"><h3>No profiles yet</h3>' +
        "<p>A profile is created automatically when a passport is saved.</p>" +
        '<a class="btn btn-primary btn-sm" href="#/upload-passport" data-nav-link="upload-passport">Upload Passport</a></div>'
      );
    }
    return (
      intro + (Panel ? Panel.listHtml() : "") + bar +
      (shown.length ? '<div class="hb-list">' + shown.map(rowHtml).join("") + "</div>" : '<p class="field-hint">Nobody matches that search.</p>')
    );
  }

  /* ---- editor ---- */

  function currentValue(group, key, profile) {
    if (st.draft && st.draft[group] && st.draft[group][key] !== undefined) return st.draft[group][key];
    return (D.of(profile))[key] || "";
  }

  function fieldHtml(f, profile) {
    var id = "ap-" + f.key;
    var value = currentValue(f.group, f.key, profile);
    var control;
    if (f.options) {
      control =
        '<select id="' + id + '" data-ap-field="' + f.group + "." + f.key + '"><option value="">Not set</option>' +
        f.options.map(function (o) { return '<option value="' + esc(o) + '"' + (o === value ? " selected" : "") + ">" + esc(o) + "</option>"; }).join("") +
        "</select>";
    } else {
      control =
        '<input id="' + id + '" type="' + (f.type || "text") + '" data-ap-field="' + f.group + "." + f.key + '" value="' + esc(value) + '"' +
        (f.placeholder ? ' placeholder="' + esc(f.placeholder) + '"' : "") + " />";
    }
    var fromReply = !!st.fromReply[f.group + "." + f.key];
    return (
      '<div class="field' + (f.wide ? " ap-wide" : "") + (fromReply ? " ap-from-reply" : "") + '"><label for="' + id + '">' + esc(f.label) + "</label>" + control +
      (fromReply ? '<span class="field-hint ap-reply-tag">From the client\'s reply — please check</span>' : "") +
      '<span class="field-hint ap-where">Used in: ' + esc(f.where) + "</span></div>"
    );
  }

  function passportHintHtml(profile) {
    var spouse = D.passportSpouse(profile);
    if (!spouse) return "";
    var status = currentValue("details", "maritalStatus", profile);
    var name = currentValue("details", "spouseName", profile);
    if (status === "Married" && name.toUpperCase() === spouse.toUpperCase()) return "";
    return (
      '<div class="ap-hint" role="note">' +
      "<span>The passport shows a spouse: <strong>" + esc(spouse) + "</strong>. OCR Extracted — Please Verify.</span>" +
      '<button type="button" class="btn btn-secondary btn-sm" data-ap-use-spouse>Use: Married, spouse ' + esc(spouse) + "</button>" +
      "</div>"
    );
  }

  function passportBlockHtml(profile) {
    var cur = passportOf(profile);
    var rows = [
      ["Name", profile.fullName],
      ["Passport number", cur.number],
      ["Date of birth", profile.dob ? utils.formatDate(profile.dob) : ""],
      ["Nationality", profile.nationality],
      ["Residential address", D.passportAddressLine(profile)],
    ];
    return (
      '<section class="card ud-card"><h2 class="ud-card__title">From the passport</h2>' +
      '<p class="field-hint">These come from the passport and cannot be edited here — correct the passport on the Upload Passport page if one is wrong. ' +
      "The residential address is always taken from the passport.</p>" +
      '<dl class="ap-read">' +
      rows.map(function (r) {
        return "<dt>" + esc(r[0]) + "</dt><dd>" + (trim(r[1]) ? esc(r[1]) : '<span class="ap-missing">Not on the passport</span>') + "</dd>";
      }).join("") +
      "</dl></section>"
    );
  }

  function editorHtml(x) {
    var profile = x.profile;
    var groups = D.GROUPS.map(function (g) {
      return (
        '<section class="card ud-card"><h2 class="ud-card__title">' + esc(g.title) + "</h2>" +
        (g.id === "family" ? passportHintHtml(profile) : "") +
        '<div class="field-grid ap-grid">' + g.fields.map(function (f) { return fieldHtml(f, profile); }).join("") + "</div></section>"
      );
    }).join("");
    return (
      '<div class="ap-top">' +
      '<button type="button" class="btn btn-ghost btn-sm" data-ap-back>← All profiles</button>' +
      '<button type="button" class="btn btn-ghost btn-sm ap-delete" data-ap-delete="' + esc(profile.id) + '">' + TRASH_ICON + "Delete profile</button>" +
      "</div>" +
      '<h2 class="ap-name">' + esc(profile.fullName || "Unnamed") + ' <span class="badge ap-kind">' + esc(x.kind) + "</span></h2>" +
      '<p class="ap-intro">Edit the details below, then press <strong>Save profile</strong>. Letters and forms made after saving use the new values.</p>' +
      (Panel ? Panel.editorHtml(profile) : "") +
      passportBlockHtml(profile) +
      groups +
      '<div class="ap-save">' +
      '<button type="button" class="btn btn-primary" data-ap-save>Save profile</button>' +
      '<span class="ap-saved" role="status">' + (st.saved ? "Saved." : st.draft ? "Not saved yet." : "") + "</span>" +
      "</div>"
    );
  }

  /* ---- delete popup ---- */

  var deleteEl = null;
  var deleteId = null;

  function closeDelete() {
    if (!deleteEl) return;
    deleteEl.setAttribute("hidden", "");
    deleteId = null;
  }

  function appLabel(a) {
    var L = global.KhannaApplicationsList;
    return L && L.applicantLabel ? L.applicantLabel(a) : a.id;
  }

  function docCount(a) {
    var n = 0;
    if (a.coverLetter && a.coverLetter.generatedAt) n += 1;
    var auth = a.authorization || {};
    if (auth.passport && auth.passport.generatedAt) n += 1;
    if (auth.company && auth.company.generatedAt) n += 1;
    if (a.invitation && a.invitation.generatedAt) n += 1;
    (a.hotels || []).forEach(function (h) { if (h.voucherGeneratedAt) n += 1; });
    return n;
  }

  function deleteBodyHtml(impact) {
    var apps = impact.applications;
    var docs = apps.reduce(function (sum, a) { return sum + docCount(a); }, 0);
    var name = impact.profile.fullName || "this applicant";
    var comp = impact.companionApplications.length;
    var days = S.RECYCLE_BIN_DAYS || 30;
    return (
      '<p class="ap-del__lead">What do you want to delete for <strong>' + esc(name) + "</strong>?</p>" +
      '<div class="ap-del__option">' +
      '<button type="button" class="btn btn-secondary btn-sm" data-ap-delete-details>Delete basic details</button>' +
      "<p>Empties the saved phone, email, occupation and other basic details of " + esc(name) + ". " +
      "The applicant, the passport and the documents stay.</p>" +
      "</div>" +
      '<div class="ap-del__option">' +
      '<button type="button" class="btn btn-danger btn-sm" data-ap-delete-all>Delete all the generated documents for this applicant</button>' +
      "<p>Deletes " + esc(name) + " from the whole website: Applicant Profiles" +
      (apps.length
        ? ", and " + apps.length + " application" + (apps.length === 1 ? "" : "s") + " where they are the main applicant" +
          (docs ? " (" + docs + " generated document" + (docs === 1 ? "" : "s") + ")" : "") +
          " — gone from Recent Applications, Recent Passports, Recent Cover Letters and Recent Hotel Blockings"
        : "") +
      (comp ? ". They are also taken off " + comp + " other application" + (comp === 1 ? "" : "s") + " where they travel as a companion" : "") +
      ".</p>" +
      (apps.length
        ? '<ul class="ap-del__apps">' + apps.slice(0, 6).map(function (a) { return "<li>" + esc(appLabel(a)) + " · " + esc(utils.formatDate(a.updatedAt || a.createdAt)) + "</li>"; }).join("") +
          (apps.length > 6 ? "<li>… and " + (apps.length - 6) + " more</li>" : "") + "</ul>"
        : "") +
      '<p class="ap-del__bin">Everything goes to the <strong>Recycle Bin</strong> — it can be restored there for ' + days + " days, then it is deleted permanently.</p>" +
      "</div>"
    );
  }

  function ensureDelete() {
    if (deleteEl) return;
    var wrap = document.createElement("div");
    wrap.className = "app-picker-overlay";
    wrap.setAttribute("hidden", "");
    wrap.setAttribute("data-ap-delete-dialog", "");
    wrap.innerHTML =
      '<div class="app-picker ap-del" role="dialog" aria-modal="true" aria-labelledby="apDeleteTitle">' +
      '<div class="app-picker__header"><h3 id="apDeleteTitle">Delete applicant profile</h3>' +
      '<button type="button" class="btn-icon" data-ap-delete-cancel aria-label="Close">' +
      '<svg class="icon icon-sm" viewBox="0 0 24 24"><path d="M6 6l12 12M18 6 6 18"/></svg></button></div>' +
      '<div data-ap-delete-body></div>' +
      '<div class="ap-del__actions"><button type="button" class="btn btn-secondary btn-sm" data-ap-delete-cancel>Cancel</button></div>' +
      "</div>";
    document.body.appendChild(wrap);
    deleteEl = wrap;
    utils.on(wrap, "click", "[data-ap-delete-cancel]", closeDelete);
    wrap.addEventListener("click", function (e) {
      if (e.target === wrap) closeDelete();
    });
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape" && !wrap.hasAttribute("hidden")) closeDelete();
    });
    utils.on(wrap, "click", "[data-ap-delete-details]", function () { doDelete(false); });
    utils.on(wrap, "click", "[data-ap-delete-all]", function () { doDelete(true); });
  }

  function openDelete(id) {
    var impact = S.personDeletionImpact ? S.personDeletionImpact(id) : null;
    if (!impact) return;
    ensureDelete();
    deleteId = id;
    utils.qs("[data-ap-delete-body]", deleteEl).innerHTML = deleteBodyHtml(impact);
    deleteEl.removeAttribute("hidden");
    utils.qs("[data-ap-delete-cancel].btn", deleteEl).focus();
  }

  function doDelete(documents) {
    var id = deleteId;
    closeDelete();
    if (!id) return;
    var name = (findById(id) || { profile: {} }).profile.fullName || "The applicant";
    var result = S.deletePersonProfile(id, { documents: documents });
    if (!result) return;
    st.draft = null;
    st.saved = false;
    st.fromReply = {};
    if (Panel) Panel.reset();
    // Basic details only: stay on the (now empty) profile. Everything: back to the list.
    if (documents) st.selectedId = null;
    render();
    if (global.KhannaToast) {
      global.KhannaToast.show(
        documents
          ? name + " moved to the Recycle Bin" + (result.applications ? ", with " + result.applications + " application" + (result.applications === 1 ? "" : "s") : "") + "."
          : "Basic details of " + name + " deleted."
      );
    }
  }

  /* ---- render / actions ---- */

  function render() {
    var r = root();
    if (!r) return;
    var x = st.selectedId ? findById(st.selectedId) : null;
    if (st.selectedId && !x) st.selectedId = null;
    r.innerHTML = '<div class="ud-layout ap-layout">' + (x ? editorHtml(x) : listHtml()) + "</div>";
  }

  function setField(path, value) {
    var parts = path.split(".");
    st.draft = st.draft || { details: {}, contact: {} };
    st.draft[parts[0]][parts[1]] = value;
    st.saved = false;
  }

  function save() {
    var x = st.selectedId ? findById(st.selectedId) : null;
    if (!x || !st.draft) {
      st.saved = !!x;
      render();
      return;
    }
    var email = trim(st.draft.contact.email);
    if (email && !/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email)) {
      if (global.KhannaToast) global.KhannaToast.show("That email address does not look right.", { type: "error" });
      return;
    }
    S.savePersonBasics(x.profile.id, st.draft);
    st.draft = null;
    st.fromReply = {};
    st.saved = true;
    render();
    if (global.KhannaToast) global.KhannaToast.show("Profile saved.");
  }

  function wire(r) {
    utils.on(r, "input", "[data-ap-search]", function (e, input) {
      st.query = input.value;
      // Only the list below the box changes, so typing is never interrupted.
      var list = utils.qs(".hb-list, .field-hint", r);
      var holder = document.createElement("div");
      holder.innerHTML = listHtml();
      var fresh = utils.qs(".hb-list", holder) || utils.qs(".field-hint", holder);
      if (list && fresh) list.replaceWith(fresh);
    });
    utils.on(r, "click", "[data-ap-open]", function (e, btn) {
      st.selectedId = btn.getAttribute("data-ap-open");
      st.draft = null;
      st.saved = false;
      st.fromReply = {};
      if (Panel) Panel.reset();
      render();
      window.scrollTo(0, 0);
    });
    utils.on(r, "click", "[data-ap-back]", function () {
      if (st.draft && !global.confirm("You have changes that are not saved. Leave without saving?")) return;
      st.selectedId = null;
      st.draft = null;
      st.saved = false;
      st.fromReply = {};
      if (Panel) Panel.reset();
      render();
    });
    function onValue(e, el) {
      setField(el.getAttribute("data-ap-field"), el.value);
      var note = utils.qs(".ap-saved", r);
      if (note) note.textContent = "Not saved yet.";
    }
    utils.on(r, "input", "[data-ap-field]", onValue);
    utils.on(r, "change", "[data-ap-field]", onValue);
    utils.on(r, "click", "[data-ap-use-spouse]", function () {
      var x = st.selectedId ? findById(st.selectedId) : null;
      if (!x) return;
      setField("details.maritalStatus", "Married");
      setField("details.spouseName", D.passportSpouse(x.profile));
      render();
    });
    utils.on(r, "click", "[data-ap-save]", save);
    utils.on(r, "click", "[data-ap-delete]", function (e, btn) {
      if (st.draft && !global.confirm("You have changes that are not saved. Continue?")) return;
      openDelete(btn.getAttribute("data-ap-delete"));
    });
    if (Panel) {
      Panel.wire(r, {
        rerender: render,
        profilePage: function () {
          var x = st.selectedId ? findById(st.selectedId) : null;
          return x ? x.profile : null;
        },
        openProfile: function (id) {
          st.selectedId = id;
          st.draft = null;
          st.saved = false;
          st.fromReply = {};
          Panel.reset();
          render();
          window.scrollTo(0, 0);
        },
        // The client's answers go into this profile's fields as an unsaved change.
        applyToProfilePage: function (values) {
          Object.keys(values).forEach(function (path) {
            if (!trim(values[path])) return;
            setField(path, values[path]);
            st.fromReply[path] = true;
          });
        },
      });
    }
  }

  var wired = false;

  function build() {
    var r = root();
    if (!r) return;
    if (!wired) {
      wired = true;
      wire(r);
      S.subscribe(function () {
        var rr = root();
        // Never redraw under someone who is typing in the editor.
        if (rr && rr.closest(".view.is-active") && !st.draft && !(document.activeElement && rr.contains(document.activeElement) && document.activeElement.matches("input, select, textarea"))) render();
      });
    }
    render();
  }

  function init() {
    document.addEventListener("khanna:navigate", function (e) {
      if (e.detail.view !== "applicant-profiles") return;
      st.selectedId = null;
      st.draft = null;
      st.saved = false;
      st.fromReply = {};
      if (Panel) Panel.reset();
      build();
    });
    if (location.hash.indexOf("applicant-profiles") !== -1) build();
  }

  global.KhannaApplicantProfiles = { build: build, people: people, _state: st };

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})(window);
