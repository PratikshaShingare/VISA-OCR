/* ==========================================================================
   Khanna Travels & Holidays — "Ask the client" panel (Applicant Profiles)

   Two halves, used on the Applicant Profiles page:
     1. Ask: the fixed visa-form message for Singapore or Japan
        (js/data/client-details-messages.js) with the applicant's name filled
        in — Copy, or open it in WhatsApp.
     2. Reply: paste the client's answer (or upload it: a .txt, or a PDF /
        screenshot which the backend reads with OCR). The answers are shown
        field by field to check and correct, then saved to the profile —
        the same basic details Cover Letters, Authorization Letters and Fill
        Forms already read from the profile.

   On the profile list the reply is matched to a profile by the applicant's
   name (staff can pick another). On one profile's page the reply goes into
   that profile's fields as an unsaved change; "Save profile" saves it.
   Nothing is saved without staff pressing a Save button (project rule 19).
   ========================================================================== */
(function (global) {
  "use strict";

  var utils = global.KhannaUtils;
  var S = global.KhannaState;
  var M = global.KhannaClientMessages;
  var D = global.KhannaApplicantDetails;

  var st = {
    country: "singapore",
    profileId: "", // the applicant whose name goes in the message
    open: false, // list page: panel folded open
    replyText: "",
    status: "",
    statusKind: "",
    results: null, // { applicants: [...], unread: [...] } after "Read reply"
    savedIndex: {}, // applicant index -> saved profile id
  };

  function esc(v) {
    return utils.escapeHtml(v == null ? "" : String(v));
  }

  function s(v) {
    return v === null || v === undefined ? "" : String(v).trim();
  }

  /* ---- profiles ---- */

  function profiles() {
    var ap = global.KhannaApplicantProfiles;
    return ap && ap.people ? ap.people().map(function (x) { return x.profile; }) : [];
  }

  function profileById(id) {
    return profiles().filter(function (p) { return p.id === id; })[0] || null;
  }

  function bestProfileFor(name) {
    if (!s(name)) return "";
    var best = null;
    var bestScore = 0;
    profiles().forEach(function (p) {
      var score = M.nameScore(name, p.fullName);
      if (score > bestScore) {
        best = p;
        bestScore = score;
      }
    });
    return best ? best.id : "";
  }

  /* ---- field labels (from the profile's own field list) ---- */

  // "Save to profile" choice that creates a new Applicant Profile from the reply.
  var NEW_APPLICANT = "__new__";

  var LABELS = (function () {
    var out = {};
    (D.GROUPS || []).forEach(function (g) {
      g.fields.forEach(function (f) { out[f.group + "." + f.key] = f.label; });
    });
    return out;
  })();

  function labelOf(field, fallback) {
    return LABELS[field] || fallback || field;
  }

  /* ---------------------------------------------------------------------
   * HTML
   * ------------------------------------------------------------------- */

  function countryOptions() {
    return M.COUNTRIES.map(function (c) {
      return '<option value="' + c.id + '"' + (c.id === st.country ? " selected" : "") + ">" + esc(c.label) + "</option>";
    }).join("");
  }

  function profileOptions(selected, emptyLabel, offerNew) {
    return (
      '<option value="">' + esc(emptyLabel) + "</option>" +
      (offerNew ? '<option value="' + NEW_APPLICANT + '"' + (selected === NEW_APPLICANT ? " selected" : "") + ">+ New applicant (create a profile)</option>" : "") +
      profiles().map(function (p) {
        var no = (p.passport && p.passport.current && p.passport.current.number) || "";
        return '<option value="' + esc(p.id) + '"' + (p.id === selected ? " selected" : "") + ">" + esc((p.fullName || "Unnamed") + (no ? " · " + no : "")) + "</option>";
      }).join("")
    );
  }

  function currentMessage(fixedProfile) {
    var p = fixedProfile || profileById(st.profileId);
    return M.message(st.country, p ? [p.fullName] : []);
  }

  /** "1 Ask the client": country, applicant, message, Copy / WhatsApp. */
  function askHtml(fixedProfile) {
    var msg = currentMessage(fixedProfile);
    return (
      '<div class="cdm-step">' +
      '<h3 class="cdm-step__title"><span class="cdm-step__no">1</span>Ask the client</h3>' +
      '<div class="cdm-row">' +
      '<div class="field"><label for="cdmCountry">Visa form</label><select id="cdmCountry" data-cdm-country>' + countryOptions() + "</select></div>" +
      (fixedProfile
        ? ""
        : '<div class="field cdm-grow"><label for="cdmApplicant">Applicant</label><select id="cdmApplicant" data-cdm-applicant>' +
          profileOptions(st.profileId, "Leave the name blank") + "</select></div>") +
      "</div>" +
      '<div class="field"><label for="cdmMessage">Message to send <span class="field-hint">(you can edit it before copying)</span></label>' +
      '<textarea id="cdmMessage" class="cdm-text" rows="12" data-cdm-message spellcheck="false">' + esc(msg) + "</textarea></div>" +
      '<div class="cdm-actions">' +
      '<button type="button" class="btn btn-primary btn-sm" data-cdm-copy>Copy message</button>' +
      '<a class="btn btn-secondary btn-sm" data-cdm-whatsapp target="_blank" rel="noopener" href="https://wa.me/?text=' + esc(encodeURIComponent(msg)) + '">Open in WhatsApp</a>' +
      '<span class="cdm-status" data-cdm-copy-status role="status"></span>' +
      "</div></div>"
    );
  }

  function statusHtml() {
    if (!st.status) return "";
    return '<p class="cdm-status cdm-status--' + (st.statusKind || "info") + '" role="status">' + esc(st.status) + "</p>";
  }

  /** "2 Paste the reply": textarea, upload, Read. */
  function replyHtml(onProfilePage) {
    return (
      '<div class="cdm-step">' +
      '<h3 class="cdm-step__title"><span class="cdm-step__no">2</span>Paste the client\'s reply</h3>' +
      '<p class="field-hint cdm-help">Paste the whole reply (WhatsApp or email) — the same message with the answers typed in. ' +
      (onProfilePage ? "The answers go into the fields below for you to check, then press <strong>Save profile</strong>." : "Several applicants in one reply are fine: one \"Applicant Name\" each.") +
      "</p>" +
      '<div class="field"><label for="cdmReply" class="sr-only">Client\'s reply</label>' +
      '<textarea id="cdmReply" class="cdm-text" rows="9" data-cdm-reply placeholder="Applicant Name: …&#10;1) Email Address: …">' + esc(st.replyText) + "</textarea></div>" +
      '<div class="cdm-actions">' +
      '<button type="button" class="btn btn-primary btn-sm" data-cdm-read>Read reply</button>' +
      '<label class="btn btn-secondary btn-sm cdm-upload">Upload reply (text, PDF or screenshot)' +
      '<input type="file" accept=".txt,.pdf,.jpg,.jpeg,.png,.webp" data-cdm-file hidden /></label>' +
      (st.replyText || st.results ? '<button type="button" class="btn btn-ghost btn-sm" data-cdm-clear>Clear</button>' : "") +
      "</div>" +
      statusHtml() +
      "</div>"
    );
  }

  function valueControl(i, row) {
    var id = "cdm-" + i + "-" + row.field.replace(/\./g, "-");
    if (row.field === "details.maritalStatus") {
      var opts = (D.MARITAL_OPTIONS || []).slice();
      if (row.value && opts.indexOf(row.value) === -1) opts.unshift(row.value);
      return '<select id="' + id + '" data-cdm-value="' + i + '" data-field="' + row.field + '"><option value="">Not set</option>' +
        opts.map(function (o) { return '<option value="' + esc(o) + '"' + (o === row.value ? " selected" : "") + ">" + esc(o) + "</option>"; }).join("") + "</select>";
    }
    return '<input id="' + id + '" type="text" data-cdm-value="' + i + '" data-field="' + row.field + '" value="' + esc(row.value) + '" />';
  }

  function resultHtml(a, i) {
    var saved = st.savedIndex[i];
    var rows = a.rows.map(function (row) {
      var id = "cdm-" + i + "-" + row.field.replace(/\./g, "-");
      return (
        '<div class="cdm-answer' + (row.note ? " cdm-answer--flag" : "") + '">' +
        '<label for="' + id + '">' + esc(labelOf(row.field, row.label)) + "</label>" +
        valueControl(i, row) +
        (row.note ? '<span class="cdm-note">' + esc(row.note) + "</span>" : "") +
        "</div>"
      );
    }).join("");
    return (
      '<div class="cdm-result" data-cdm-result="' + i + '">' +
      '<div class="cdm-result__head">' +
      '<div><span class="cdm-result__label">Applicant Name in the reply</span><strong>' + esc(a.name || "(no name written)") + "</strong></div>" +
      '<div class="field cdm-grow"><label for="cdmProfile' + i + '">Save to profile</label>' +
      '<select id="cdmProfile' + i + '" data-cdm-profile="' + i + '">' + profileOptions(a.profileId, "Choose the applicant…", true) + "</select>" +
      (a.profileId === NEW_APPLICANT
        ? '<span class="field-hint">A new profile will be created. When this applicant\'s passport is uploaded later, it joins this profile.</span>'
        : a.profileId ? "" : '<span class="cdm-note">Choose who this is, or "+ New applicant".</span>') +
      "</div></div>" +
      (a.profileId === NEW_APPLICANT
        ? '<div class="field cdm-newname"><label for="cdmNewName' + i + '">Applicant\'s full name (as in the passport)</label>' +
          '<input id="cdmNewName' + i + '" type="text" data-cdm-new-name="' + i + '" value="' + esc(a.newName != null ? a.newName : a.name) + '" /></div>'
        : "") +
      (rows ? '<div class="cdm-answers">' + rows + "</div>" : '<p class="field-hint">No answers found for this applicant.</p>') +
      '<div class="cdm-actions">' +
      '<button type="button" class="btn btn-primary btn-sm" data-cdm-save="' + i + '"' + (a.rows.length ? "" : " disabled") + ">Save to profile</button>" +
      (saved ? '<span class="cdm-status cdm-status--ok">Saved.</span> <button type="button" class="btn btn-ghost btn-sm" data-cdm-open-profile="' + esc(saved) + '">Open profile</button>' : "") +
      "</div></div>"
    );
  }

  function unreadHtml() {
    var lines = (st.results && st.results.unread) || [];
    if (!lines.length) return "";
    return (
      '<div class="cdm-unread"><strong>Lines not understood — check these yourself:</strong><ul>' +
      lines.slice(0, 20).map(function (l) { return "<li>" + esc(l) + "</li>"; }).join("") +
      "</ul></div>"
    );
  }

  function resultsHtml() {
    if (!st.results) return "";
    if (!st.results.applicants.length) {
      return '<div class="cdm-results">' + unreadHtml() + "</div>";
    }
    return (
      '<div class="cdm-results">' +
      '<p class="cdm-verify">Read from the client\'s message — please check every value before saving.</p>' +
      st.results.applicants.map(resultHtml).join("") +
      unreadHtml() +
      "</div>"
    );
  }

  /** The panel on the profile list. */
  function listHtml() {
    return (
      '<section class="card ud-card cdm" data-cdm>' +
      '<button type="button" class="cdm-toggle" data-cdm-toggle aria-expanded="' + (st.open ? "true" : "false") + '">' +
      '<span><strong>Get basic details from the client</strong>' +
      '<span class="cdm-toggle__sub">Send the Singapore / Japan details message, paste the reply, save it to the profile.</span></span>' +
      '<svg class="icon icon-sm" viewBox="0 0 24 24" aria-hidden="true"><path d="m6 9 6 6 6-6"/></svg>' +
      "</button>" +
      (st.open ? '<div class="cdm-body">' + askHtml(null) + replyHtml(false) + resultsHtml() + "</div>" : "") +
      "</section>"
    );
  }

  /** The panel on one profile's page. */
  function editorHtml(profile) {
    return (
      '<section class="card ud-card cdm" data-cdm data-cdm-profile-page="' + esc(profile.id) + '">' +
      '<button type="button" class="cdm-toggle" data-cdm-toggle aria-expanded="' + (st.open ? "true" : "false") + '">' +
      '<span><strong>Get these details from the client</strong>' +
      '<span class="cdm-toggle__sub">Copy the Singapore / Japan details message for ' + esc(profile.fullName || "this applicant") + ", then paste the reply here.</span></span>" +
      '<svg class="icon icon-sm" viewBox="0 0 24 24" aria-hidden="true"><path d="m6 9 6 6 6-6"/></svg>' +
      "</button>" +
      (st.open ? '<div class="cdm-body">' + askHtml(profile) + replyHtml(true) + (st.results && !st.results.applicants.length ? resultsHtml() : unreadHtml()) + "</div>" : "") +
      "</section>"
    );
  }

  /* ---------------------------------------------------------------------
   * Actions
   * ------------------------------------------------------------------- */

  function toast(msg, type) {
    if (global.KhannaToast) global.KhannaToast.show(msg, type ? { type: type } : undefined);
  }

  function copyText(text) {
    if (global.navigator && navigator.clipboard && navigator.clipboard.writeText) {
      return navigator.clipboard.writeText(text).then(function () { return true; }, function () { return fallbackCopy(text); });
    }
    return Promise.resolve(fallbackCopy(text));
  }

  function fallbackCopy(text) {
    try {
      var ta = document.createElement("textarea");
      ta.value = text;
      ta.setAttribute("readonly", "");
      ta.style.position = "fixed";
      ta.style.opacity = "0";
      document.body.appendChild(ta);
      ta.select();
      var ok = document.execCommand("copy");
      document.body.removeChild(ta);
      return ok;
    } catch (e) {
      return false;
    }
  }

  /** Values of one result as a savePersonBasics patch (only answered fields). */
  function patchOf(values) {
    var patch = { details: {}, contact: {} };
    Object.keys(values).forEach(function (field) {
      var v = s(values[field]);
      if (!v) return;
      var parts = field.split(".");
      if (patch[parts[0]]) patch[parts[0]][parts[1]] = v;
    });
    return patch;
  }

  function badEmail(values) {
    return ["contact.email", "details.sponsorEmail"].filter(function (f) {
      var v = s(values[f]);
      return v && !/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(v);
    })[0];
  }

  function readReply(text, profilePageId) {
    st.replyText = text;
    var res = M.read(text);
    st.savedIndex = {};
    res.applicants.forEach(function (a) {
      a.profileId = profilePageId || bestProfileFor(a.name) || (s(a.name) ? NEW_APPLICANT : "");
    });
    st.results = res;
    var n = res.applicants.reduce(function (sum, a) { return sum + Object.keys(a.values).length; }, 0);
    if (!res.applicants.length || !n) {
      st.status = "No answers found. Check that the reply still has the question labels (e.g. \"Email Address:\").";
      st.statusKind = "warn";
    } else {
      st.status = n + " answer" + (n === 1 ? "" : "s") + " read" + (res.applicants.length > 1 ? " for " + res.applicants.length + " applicants" : "") + ".";
      st.statusKind = "ok";
    }
    return res;
  }

  /** On a profile page: the applicant in the reply that is this profile (or the only one). */
  function pickForProfile(res, profile) {
    var list = res.applicants.filter(function (a) { return Object.keys(a.values).length; });
    if (!list.length) return null;
    if (list.length === 1) return list[0];
    var best = null;
    var bestScore = 0;
    list.forEach(function (a) {
      var sc = M.nameScore(a.name, profile.fullName);
      if (sc > bestScore) {
        best = a;
        bestScore = sc;
      }
    });
    return best || list[0];
  }

  function readFile(file, done) {
    var name = (file && file.name) || "";
    if (/\.txt$/i.test(name) || file.type === "text/plain") {
      var fr = new FileReader();
      fr.onload = function () { done(String(fr.result || ""), ""); };
      fr.onerror = function () { done("", "The file could not be read."); };
      fr.readAsText(file);
      return;
    }
    if (!global.KhannaApi || !global.KhannaApi.extractFormDocument) {
      done("", "Only .txt files can be read here.");
      return;
    }
    global.KhannaApi.extractFormDocument(file).then(
      function (result) {
        var text = s(result && result.text);
        done(text, text ? "" : "No text found in " + name + ".", true);
      },
      function (err) {
        done("", (err && err.message) || "The file could not be read.");
      }
    );
  }

  /**
   * Wires the panel inside `root`. hooks:
   *   rerender()                 redraw the page
   *   openProfile(id)            list page: open a profile
   *   applyToProfilePage(values) profile page: put values into the unsaved fields
   *   profilePage()              the profile shown, or null on the list
   */
  function wire(root, hooks) {
    function profileFromPage() {
      return hooks.profilePage ? hooks.profilePage() : null;
    }
    function refreshMessage() {
      var box = utils.qs("[data-cdm-message]", root);
      if (!box) return;
      var msg = currentMessage(profileFromPage());
      box.value = msg;
      var wa = utils.qs("[data-cdm-whatsapp]", root);
      if (wa) wa.href = "https://wa.me/?text=" + encodeURIComponent(msg);
    }
    utils.on(root, "click", "[data-cdm-toggle]", function () {
      st.open = !st.open;
      hooks.rerender();
    });
    utils.on(root, "change", "[data-cdm-country]", function (e, el) {
      st.country = el.value;
      refreshMessage();
    });
    utils.on(root, "change", "[data-cdm-applicant]", function (e, el) {
      st.profileId = el.value;
      refreshMessage();
    });
    utils.on(root, "input", "[data-cdm-message]", function (e, el) {
      var wa = utils.qs("[data-cdm-whatsapp]", root);
      if (wa) wa.href = "https://wa.me/?text=" + encodeURIComponent(el.value);
    });
    utils.on(root, "click", "[data-cdm-copy]", function () {
      var box = utils.qs("[data-cdm-message]", root);
      var note = utils.qs("[data-cdm-copy-status]", root);
      copyText(box ? box.value : "").then(function (ok) {
        if (note) note.textContent = ok ? "Copied — paste it in WhatsApp or email." : "Could not copy — select the text and copy it.";
      });
    });
    utils.on(root, "input", "[data-cdm-reply]", function (e, el) {
      st.replyText = el.value;
    });
    utils.on(root, "click", "[data-cdm-clear]", function () {
      st.replyText = "";
      st.results = null;
      st.status = "";
      st.savedIndex = {};
      hooks.rerender();
    });

    function useReply(text) {
      var page = profileFromPage();
      var res = readReply(text, page ? page.id : "");
      if (page) {
        var a = pickForProfile(res, page);
        if (a) {
          var n = Object.keys(a.values).length;
          hooks.applyToProfilePage(a.values);
          var notes = a.rows.filter(function (r) { return r.note && r.value; }).map(function (r) { return labelOf(r.field, r.label) + ": " + r.note; });
          st.status = n + " detail" + (n === 1 ? "" : "s") + " put into the fields below — not saved yet. Check them and press Save profile." + (notes.length ? " Check: " + notes.join("; ") + "." : "");
          st.statusKind = "ok";
          if (res.applicants.length > 1) st.status += " The reply has " + res.applicants.length + " applicants; the one named \"" + (a.name || "—") + "\" was used.";
        }
      }
      hooks.rerender();
    }

    utils.on(root, "click", "[data-cdm-read]", function () {
      var box = utils.qs("[data-cdm-reply]", root);
      var text = box ? box.value : st.replyText;
      if (!s(text)) {
        st.status = "Paste the client's reply first.";
        st.statusKind = "warn";
        hooks.rerender();
        return;
      }
      useReply(text);
    });
    utils.on(root, "change", "[data-cdm-file]", function (e, input) {
      var file = input.files && input.files[0];
      if (!file) return;
      st.status = "Reading " + file.name + "…";
      st.statusKind = "info";
      hooks.rerender();
      readFile(file, function (text, error, fromOcr) {
        if (error) {
          st.status = error;
          st.statusKind = "warn";
          hooks.rerender();
          return;
        }
        useReply(text);
        if (fromOcr) {
          st.status = "OCR Extracted — Please Verify. " + st.status;
          hooks.rerender();
        }
      });
    });
    utils.on(root, "change", "[data-cdm-profile]", function (e, el) {
      var i = parseInt(el.getAttribute("data-cdm-profile"), 10);
      if (st.results && st.results.applicants[i]) st.results.applicants[i].profileId = el.value;
      hooks.rerender();
    });
    utils.on(root, "input", "[data-cdm-new-name]", function (e, el) {
      var a = st.results && st.results.applicants[parseInt(el.getAttribute("data-cdm-new-name"), 10)];
      if (a) a.newName = el.value;
    });
    function onValue(e, el) {
      var i = parseInt(el.getAttribute("data-cdm-value"), 10);
      var a = st.results && st.results.applicants[i];
      if (!a) return;
      var field = el.getAttribute("data-field");
      a.values[field] = el.value;
      a.rows.forEach(function (r) { if (r.field === field) r.value = el.value; });
    }
    utils.on(root, "input", "[data-cdm-value]", onValue);
    utils.on(root, "change", "[data-cdm-value]", onValue);
    utils.on(root, "click", "[data-cdm-save]", function (e, btn) {
      var i = parseInt(btn.getAttribute("data-cdm-save"), 10);
      var a = st.results && st.results.applicants[i];
      if (!a) return;
      if (!a.profileId) {
        toast("Choose the applicant, or \"+ New applicant\" to create a profile.", "error");
        var sel = utils.qs('[data-cdm-profile="' + i + '"]', root);
        if (sel) sel.focus();
        return;
      }
      var bad = badEmail(a.values);
      if (bad) {
        toast("The " + labelOf(bad).toLowerCase() + " does not look right — correct it first.", "error");
        return;
      }
      var created = false;
      if (a.profileId === NEW_APPLICANT) {
        var name = s(a.newName != null ? a.newName : a.name).toUpperCase().replace(/\s+/g, " ");
        if (!name) {
          toast("Enter the applicant's full name for the new profile.", "error");
          var nameBox = utils.qs('[data-cdm-new-name="' + i + '"]', root);
          if (nameBox) nameBox.focus();
          return;
        }
        var parts = name.split(" ");
        var profile = S.saveApplicantProfile({
          fullName: name,
          firstName: parts.length > 1 ? parts.slice(0, -1).join(" ") : name,
          lastName: parts.length > 1 ? parts[parts.length - 1] : "",
        });
        if (!profile) {
          toast("The new profile could not be created.", "error");
          return;
        }
        a.profileId = profile.id;
        created = true;
      }
      var saved = S.savePersonBasics(a.profileId, patchOf(a.values));
      if (!saved) {
        toast("That profile could not be found.", "error");
        return;
      }
      st.savedIndex[i] = a.profileId;
      toast(created ? "New applicant profile created for " + (saved.fullName || "the applicant") + "." : "Details saved to " + (saved.fullName || "the profile") + ".");
      hooks.rerender();
    });
    utils.on(root, "click", "[data-cdm-open-profile]", function (e, btn) {
      if (hooks.openProfile) hooks.openProfile(btn.getAttribute("data-cdm-open-profile"));
    });
  }

  /** Forget the reply (e.g. when another profile is opened). */
  function reset(keepOpen) {
    st.replyText = "";
    st.results = null;
    st.status = "";
    st.savedIndex = {};
    if (!keepOpen) st.open = false;
  }

  global.KhannaClientDetailsPanel = { listHtml: listHtml, editorHtml: editorHtml, wire: wire, reset: reset, _state: st };
})(window);
