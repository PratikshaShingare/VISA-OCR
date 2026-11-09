/* ==========================================================================
   Khanna Travels & Holidays — Check Forms page ("#/form-check")
   Staff upload, in three SEPARATE places:
     1. the passport(s) — read with the same passport OCR as everywhere else
        (KhannaDocumentIntake.readPassport), or taken from a saved
        application; the details stay editable and must be verified;
     2. supporting documents (optional) — tickets, bookings, ID, letters;
     3. the filled forms to check.
   "Check forms" compares every form with the passport details and the
   supporting documents (backend form_check.py) and lists what to correct.

   Nothing here is saved: files, read text and results live in this page only
   (passport data, project rule 11). Results are suggestions — staff decide
   (rules 10 and 19).
   ========================================================================== */
(function (global) {
  "use strict";

  var utils = global.KhannaUtils;
  var api = global.KhannaApi;
  var Intake = global.KhannaDocumentIntake;
  var People = global.KhannaVisaFormPeople;
  var reviewForm = global.KhannaPassportReviewForm;

  var VERIFY = "OCR Extracted — Please Verify";
  var ACCEPT = ".pdf,.jpg,.jpeg,.png,application/pdf,image/jpeg,image/png";

  var st = {
    passports: [], // { id, fileName, status: queued|reading|done|error, message, details, flags, origin }
    supporting: [], // { id, file, status, message, extract }
    forms: [], // { id, file, status, message, extract, result }
    queueRunning: false,
    checking: false,
    stale: false,
    notice: "",
  };

  var built = false;

  function root() {
    return utils.qs("[data-form-check-root]");
  }

  function esc(v) {
    return utils.escapeHtml(v);
  }

  /* ----------------------------------------------------------------------
   * Shell
   * -------------------------------------------------------------------- */

  function dropHtml(kind, title, hint) {
    return (
      '<label class="ud-drop" data-fc-drop="' + kind + '">' +
      '<input type="file" multiple accept="' + ACCEPT + '" data-fc-file="' + kind + '" />' +
      '<svg class="icon" viewBox="0 0 24 24"><path d="M12 16V4M7 9l5-5 5 5"/><path d="M4 20h16"/></svg>' +
      "<strong>" + title + "</strong>" +
      "<span>" + hint + "</span>" +
      '<span class="ud-drop__or">click to choose, or drop files here</span>' +
      "</label>"
    );
  }

  function build() {
    var r = root();
    if (!r || built) return;
    built = true;
    r.innerHTML =
      '<div class="ud-layout vf-layout">' +
      '<p class="field-hint">Upload the passport, any supporting documents and the filled forms separately. ' +
      "Each form is compared with the passport details and the supporting documents. The results are suggestions — staff check and decide. " +
      "Nothing on this page is saved.</p>" +

      '<section class="card ud-card">' +
      '<h2 class="ud-card__title"><span class="ud-step">1</span> Passport</h2>' +
      dropHtml("passport", "Upload passport", "One file per passport — PDF, JPG, JPEG or PNG") +
      '<div class="vf-row-actions"><button type="button" class="btn btn-secondary btn-sm" data-fc-use-app>Use a saved application instead</button></div>' +
      '<div data-fc-passports></div>' +
      "</section>" +

      '<section class="card ud-card">' +
      '<h2 class="ud-card__title"><span class="ud-step">2</span> Supporting documents <span class="vf-optional">optional</span></h2>' +
      '<p class="field-hint">Tickets, hotel bookings, ID cards, letters… Used to check details a passport does not have (address, phone, hotel) and to spot a name or passport number written differently.</p>' +
      dropHtml("supporting", "Upload supporting documents", "PDF, JPG, JPEG or PNG — several allowed") +
      '<div data-fc-supporting></div>' +
      "</section>" +

      '<section class="card ud-card">' +
      '<h2 class="ud-card__title"><span class="ud-step">3</span> Forms to check</h2>' +
      '<p class="field-hint">Filled visa forms. A fillable PDF is read field by field (most reliable); a scanned form is read by OCR.</p>' +
      dropHtml("form", "Upload filled forms", "PDF, JPG, JPEG or PNG — several allowed") +
      '<div data-fc-forms></div>' +
      "</section>" +

      '<section class="card ud-card">' +
      '<h2 class="ud-card__title"><span class="ud-step">4</span> Corrections</h2>' +
      '<p class="field-hint" data-fc-ready role="status"></p>' +
      '<div class="vf-row-actions"><button type="button" class="btn btn-primary" data-fc-check>Check forms</button></div>' +
      '<div data-fc-results aria-live="polite"></div>' +
      "</section>" +
      "</div>";

    wire(r);
    renderAll();
  }

  /* ----------------------------------------------------------------------
   * Adding files
   * -------------------------------------------------------------------- */

  function addFiles(kind, fileList) {
    var files = Array.prototype.slice.call(fileList || []);
    var rejected = [];
    files.forEach(function (file) {
      if (!Intake.isAcceptedFile(file)) {
        rejected.push(file.name);
        return;
      }
      var item = { id: utils.generateId("fc"), file: file, fileName: file.name, status: "queued", message: "Waiting…" };
      if (kind === "passport") {
        item.origin = "upload";
        st.passports.push(item);
      } else if (kind === "supporting") {
        st.supporting.push(item);
      } else {
        st.forms.push(item);
      }
    });
    if (rejected.length) global.KhannaToast.show("Not a PDF, JPG or PNG: " + rejected.join(", "), { type: "error" });
    markStale();
    renderAll();
    runQueue();
  }

  function nextQueued() {
    var lists = [st.passports, st.supporting, st.forms];
    for (var i = 0; i < lists.length; i++) {
      for (var j = 0; j < lists[i].length; j++) {
        if (lists[i][j].status === "queued") return { item: lists[i][j], kind: i === 0 ? "passport" : "doc" };
      }
    }
    return null;
  }

  function runQueue() {
    if (st.queueRunning) return;
    var next = nextQueued();
    if (!next) {
      renderAll();
      return;
    }
    st.queueRunning = true;
    var item = next.item;
    item.status = "reading";
    item.message = "Reading…";
    renderAll();
    var job;
    if (next.kind === "passport") {
      job = Intake.readPassport(item.file, function (msg) {
        item.message = msg;
        renderLists();
      }).then(function (record) {
        item.details = People.fromIntakeRecord(record);
        item.flags = record.flags || [];
      });
    } else {
      job = api.extractFormDocument(item.file).then(function (extract) {
        item.extract = extract;
      });
    }
    job.then(
      function () {
        item.status = "done";
        item.message = "";
      },
      function (err) {
        item.status = "error";
        item.message = (err && err.message) || "This file could not be read.";
      }
    ).then(function () {
      st.queueRunning = false;
      markStale();
      runQueue();
    });
  }

  function addFromApplication(app) {
    var people = People.peopleOfApplication(app);
    if (!people.length) {
      global.KhannaToast.show("That application has no passport details yet.", { type: "error" });
      return;
    }
    people.forEach(function (p) {
      st.passports.push({
        id: utils.generateId("fc"),
        fileName: p.role + " — saved application",
        status: "done",
        message: "",
        details: p.details,
        flags: [],
        origin: "application",
      });
    });
    markStale();
    renderAll();
  }

  function removeItem(listName, id) {
    st[listName] = st[listName].filter(function (i) { return i.id !== id || i.status === "reading"; });
    markStale();
    renderAll();
  }

  function markStale() {
    if (st.forms.some(function (f) { return f.result; })) st.stale = true;
  }

  /* ----------------------------------------------------------------------
   * Rendering the three lists
   * -------------------------------------------------------------------- */

  function statusText(item) {
    if (item.status === "error") return '<span class="vf-status vf-status--error">' + esc(item.message) + "</span>";
    if (item.status !== "done") return '<span class="vf-status">' + esc(item.message || "Waiting…") + "</span>";
    return "";
  }

  function removeBtn(listName, item) {
    if (item.status === "reading") return "";
    return '<button type="button" class="btn btn-ghost btn-sm" data-fc-remove="' + listName + '" data-id="' + item.id + '" aria-label="Remove ' + esc(item.fileName) + '">Remove</button>';
  }

  function dateDisplay(iso) {
    var p = reviewForm.parseDate(iso);
    return p ? p.display : iso || "";
  }

  function passportHtml(item) {
    var head =
      '<div class="vf-item__head"><div class="vf-item__title"><strong>' +
      esc(item.status === "done" ? People.displayName(item.details) : item.fileName) + "</strong>" +
      '<span class="vf-item__meta">' + esc(item.origin === "application" ? item.fileName : item.fileName) + "</span></div>" +
      removeBtn("passports", item) + "</div>";
    if (item.status !== "done") return '<div class="vf-item">' + head + statusText(item) + "</div>";
    var flags = (item.flags || []).length
      ? '<p class="vf-flags">' + item.flags.map(esc).join(" · ") + "</p>"
      : "";
    var badge = item.origin === "application"
      ? '<span class="badge badge-info">From saved application — check it is current</span>'
      : '<span class="badge badge-warning">' + VERIFY + "</span>";
    var fields = People.DETAIL_FIELDS.map(function (f) {
      var id = "fc-" + item.id + "-" + f.key;
      var value = f.date ? dateDisplay(item.details[f.key]) : item.details[f.key] || "";
      var input;
      if (f.options) {
        input = '<select id="' + id + '" data-fc-detail="' + f.key + '" data-id="' + item.id + '">' +
          f.options.map(function (o) { return '<option value="' + o[0] + '"' + (o[0] === value ? " selected" : "") + ">" + o[1] + "</option>"; }).join("") +
          "</select>";
      } else {
        input = '<input id="' + id + '" type="text" value="' + esc(value) + '" data-fc-detail="' + f.key + '" data-id="' + item.id + '"' +
          (f.date ? ' placeholder="DD-MM-YYYY" inputmode="numeric" data-date="1"' : "") + " />";
      }
      return '<div class="field"><label for="' + id + '">' + esc(f.label) + "</label>" + input + "</div>";
    }).join("");
    return (
      '<div class="vf-item">' + head +
      '<div class="vf-item__badges">' + badge + "</div>" + flags +
      '<details class="vf-details"' + (st.passports.length === 1 ? " open" : "") + "><summary>Passport details used for checking</summary>" +
      '<div class="vf-detail-grid">' + fields + "</div></details>" +
      "</div>"
    );
  }

  function extractSummary(extract) {
    if (!extract) return "";
    var how = { "form-fields": "Form fields read", "text-layer": "Text read", ocr: "Read by OCR", none: "Nothing read" }[extract.method] || "";
    var bits = [];
    if (extract.formName) bits.push(extract.formName);
    if (how) bits.push(how);
    if (extract.pages) bits.push(extract.pages + " page" + (extract.pages === 1 ? "" : "s"));
    if (extract.method === "form-fields") {
      var filled = (extract.fields || []).filter(function (f) { return f.value; }).length;
      bits.push(filled + " filled field" + (filled === 1 ? "" : "s"));
    }
    return bits.join(" · ");
  }

  function readContentHtml(extract) {
    if (!extract) return "";
    var body = "";
    var filled = (extract.fields || []).filter(function (f) { return f.value; });
    if (filled.length) {
      body = '<dl class="vf-read">' + filled.map(function (f) {
        return "<dt>" + esc(f.label) + "</dt><dd>" + esc(f.value) + "</dd>";
      }).join("") + "</dl>";
    } else if (extract.text) {
      body = '<pre class="vf-text">' + esc(extract.text.slice(0, 6000)) + (extract.text.length > 6000 ? "\n…" : "") + "</pre>";
    } else {
      body = '<p class="ud-empty">Nothing could be read.</p>';
    }
    return '<details class="vf-details"><summary>What was read</summary>' + body + "</details>";
  }

  function docHtml(listName, item) {
    var head =
      '<div class="vf-item__head"><div class="vf-item__title"><strong>' + esc(item.fileName) + "</strong>" +
      '<span class="vf-item__meta">' + esc(item.status === "done" ? extractSummary(item.extract) : "") + "</span></div>" +
      removeBtn(listName, item) + "</div>";
    if (item.status !== "done") return '<div class="vf-item">' + head + statusText(item) + "</div>";
    var notes = (item.extract.notes || []).length ? '<p class="vf-flags">' + item.extract.notes.map(esc).join(" ") + "</p>" : "";
    return '<div class="vf-item">' + head + notes + readContentHtml(item.extract) + "</div>";
  }

  function renderLists() {
    var r = root();
    if (!r) return;
    var p = utils.qs("[data-fc-passports]", r);
    var s = utils.qs("[data-fc-supporting]", r);
    var f = utils.qs("[data-fc-forms]", r);
    // Keep focus inside a passport field the user is typing in.
    var active = document.activeElement;
    var typing = active && active.hasAttribute && active.hasAttribute("data-fc-detail") && p.contains(active);
    if (!typing) p.innerHTML = st.passports.map(passportHtml).join("");
    s.innerHTML = st.supporting.map(function (i) { return docHtml("supporting", i); }).join("");
    f.innerHTML = st.forms.map(function (i) { return docHtml("forms", i); }).join("");
  }

  function readyState() {
    var forms = st.forms.filter(function (f) { return f.status === "done"; });
    var busy = st.queueRunning || [st.passports, st.supporting, st.forms].some(function (l) {
      return l.some(function (i) { return i.status === "queued" || i.status === "reading"; });
    });
    var passports = st.passports.filter(function (p) { return p.status === "done"; });
    var badDates = [];
    passports.forEach(function (p) {
      ["dob", "issueDate", "expiryDate"].forEach(function (k) {
        if (p.details[k] && !reviewForm.parseDate(p.details[k])) badDates.push(People.displayName(p.details) + ": " + k);
      });
    });
    if (busy) return { ok: false, text: "Still reading the uploaded files…" };
    if (!forms.length) return { ok: false, text: "Upload at least one filled form." };
    if (!passports.length && !st.supporting.some(function (d) { return d.status === "done"; })) {
      return { ok: false, text: "Upload a passport (or choose a saved application) to compare the forms with." };
    }
    if (badDates.length) return { ok: false, text: "A passport date is not a valid DD-MM-YYYY date — correct it first." };
    if (!passports.length) return { ok: true, text: "No passport given: forms are only checked against the supporting documents." };
    return { ok: true, text: st.stale ? "Something changed since the last check — check again." : "" };
  }

  function renderReady() {
    var r = root();
    if (!r) return;
    var ready = readyState();
    var btn = utils.qs("[data-fc-check]", r);
    btn.disabled = !ready.ok || st.checking;
    btn.textContent = st.checking ? "Checking…" : st.forms.some(function (f) { return f.result; }) ? "Check again" : "Check forms";
    utils.qs("[data-fc-ready]", r).textContent = ready.text;
  }

  /* ----------------------------------------------------------------------
   * Results
   * -------------------------------------------------------------------- */

  var STATUS_LABEL = { correct: "Correct this", missing: "Missing", check: "Please check", info: "Note", ok: "Matches" };

  function findingRow(f) {
    return (
      '<tr class="vf-finding vf-finding--' + f.status + '">' +
      '<td data-th="Result"><span class="vf-pill vf-pill--' + f.status + '">' + STATUS_LABEL[f.status] + "</span></td>" +
      '<td data-th="Field">' + esc(f.label) + "</td>" +
      '<td data-th="In the form">' + (f.formValue ? esc(f.formValue) : '<span class="vf-muted">—</span>') + "</td>" +
      '<td data-th="Should be">' + (f.expected ? esc(f.expected) : '<span class="vf-muted">—</span>') +
      (f.source ? '<span class="vf-source">' + esc(f.source) + "</span>" : "") + "</td>" +
      '<td data-th="Advice">' + esc(f.message) + "</td>" +
      "</tr>"
    );
  }

  function tableHtml(rows) {
    return (
      '<div class="vf-table-wrap"><table class="vf-table"><thead><tr>' +
      "<th>Result</th><th>Field</th><th>In the form</th><th>Should be</th><th>Advice</th>" +
      "</tr></thead><tbody>" + rows.map(findingRow).join("") + "</tbody></table></div>"
    );
  }

  function resultHtml(item) {
    if (item.checkError) {
      return '<div class="vf-result"><h3>' + esc(item.fileName) + '</h3><p class="ud-warn">' + esc(item.checkError) + "</p></div>";
    }
    var r = item.result;
    if (!r) return "";
    var problems = r.findings.filter(function (f) { return f.status === "correct" || f.status === "missing" || f.status === "check"; });
    var fine = r.findings.filter(function (f) { return f.status === "ok" || f.status === "info"; });
    var sum = r.summary || {};
    var chips =
      '<div class="vf-chips">' +
      '<span class="vf-pill vf-pill--correct">' + (sum.correct || 0) + " to correct</span>" +
      '<span class="vf-pill vf-pill--missing">' + (sum.missing || 0) + " missing</span>" +
      '<span class="vf-pill vf-pill--check">' + (sum.check || 0) + " to check</span>" +
      '<span class="vf-pill vf-pill--ok">' + (sum.ok || 0) + " matching</span>" +
      "</div>";
    var used = r.passportUsed ? '<p class="field-hint">Compared with passport: <strong>' + esc(r.passportUsed) + "</strong></p>" : "";
    var notes = (r.notes || []).length ? '<p class="vf-flags">' + r.notes.map(esc).join(" ") + "</p>" : "";
    var body = problems.length
      ? tableHtml(problems)
      : '<p class="notice notice-success"><span>No corrections found. Staff must still check the form before it is submitted.</span></p>';
    var fineHtml = fine.length
      ? '<details class="vf-details"><summary>Matching details and notes (' + fine.length + ")</summary>" + tableHtml(fine) + "</details>"
      : "";
    return (
      '<div class="vf-result"><h3>' + esc(item.fileName) + (r.formName ? ' <span class="vf-item__meta">' + esc(r.formName) + "</span>" : "") + "</h3>" +
      chips + used + notes + body + fineHtml + "</div>"
    );
  }

  function renderResults() {
    var r = root();
    if (!r) return;
    var out = utils.qs("[data-fc-results]", r);
    var withResults = st.forms.filter(function (f) { return f.result || f.checkError; });
    if (!withResults.length) {
      out.innerHTML = "";
      return;
    }
    out.innerHTML =
      '<p class="field-hint vf-verify">Suggestions only — compare with the original documents before correcting. ' +
      (st.passports.some(function (p) { return p.origin === "upload"; }) ? VERIFY + " applies to passport details read by OCR." : "") +
      "</p>" +
      withResults.map(resultHtml).join("");
  }

  function renderAll() {
    renderLists();
    renderReady();
    renderResults();
  }

  /* ----------------------------------------------------------------------
   * Checking
   * -------------------------------------------------------------------- */

  function passportPayload() {
    return st.passports.filter(function (p) { return p.status === "done"; }).map(function (p) {
      var d = Object.assign({}, p.details);
      ["dob", "issueDate", "expiryDate"].forEach(function (k) {
        var parsed = reviewForm.parseDate(d[k]);
        d[k] = parsed ? parsed.iso : "";
      });
      d.label = People.displayName(p.details);
      return d;
    });
  }

  function supportingPayload() {
    return st.supporting.filter(function (d) { return d.status === "done"; }).map(function (d) {
      return { fileName: d.fileName, text: d.extract.text || "", fields: (d.extract.fields || []).map(function (f) { return { label: f.label, value: f.value }; }) };
    });
  }

  function check() {
    var ready = readyState();
    if (!ready.ok || st.checking) return;
    st.checking = true;
    renderReady();
    var passports = passportPayload();
    var supporting = supportingPayload();
    var forms = st.forms.filter(function (f) { return f.status === "done"; });
    var chain = Promise.resolve();
    forms.forEach(function (item) {
      chain = chain.then(function () {
        var payload = Object.assign({}, item.extract, { fileName: item.fileName });
        return api.compareFormDocument(payload, passports, supporting).then(
          function (result) {
            item.result = result;
            item.checkError = "";
          },
          function (err) {
            item.result = null;
            item.checkError = (err && err.message) || "This form could not be checked.";
          }
        );
      });
    });
    chain.then(function () {
      st.checking = false;
      st.stale = false;
      renderReady();
      renderResults();
    });
  }

  /* ----------------------------------------------------------------------
   * Events
   * -------------------------------------------------------------------- */

  function wire(r) {
    utils.on(r, "change", "[data-fc-file]", function (e, input) {
      addFiles(input.getAttribute("data-fc-file"), input.files);
      input.value = "";
    });
    ["dragover", "dragenter"].forEach(function (ev) {
      utils.on(r, ev, "[data-fc-drop]", function (e, el) {
        e.preventDefault();
        el.classList.add("is-over");
      });
    });
    utils.on(r, "dragleave", "[data-fc-drop]", function (e, el) {
      el.classList.remove("is-over");
    });
    utils.on(r, "drop", "[data-fc-drop]", function (e, el) {
      e.preventDefault();
      el.classList.remove("is-over");
      addFiles(el.getAttribute("data-fc-drop"), e.dataTransfer && e.dataTransfer.files);
    });
    utils.on(r, "click", "[data-fc-remove]", function (e, btn) {
      removeItem(btn.getAttribute("data-fc-remove"), btn.getAttribute("data-id"));
    });
    utils.on(r, "click", "[data-fc-use-app]", function (e, btn) {
      if (!global.KhannaApplicationPicker) return;
      global.KhannaApplicationPicker.open(btn, addFromApplication);
    });
    function onDetail(e, input) {
      var item = st.passports.filter(function (p) { return p.id === input.getAttribute("data-id"); })[0];
      if (!item) return;
      var key = input.getAttribute("data-fc-detail");
      item.details[key] = input.value.trim();
      if (input.hasAttribute("data-date")) {
        var ok = !input.value.trim() || reviewForm.parseDate(input.value);
        input.setAttribute("aria-invalid", ok ? "false" : "true");
      }
      markStale();
      renderReady();
    }
    utils.on(r, "input", "[data-fc-detail]", onDetail);
    utils.on(r, "change", "[data-fc-detail]", onDetail);
    utils.on(r, "click", "[data-fc-check]", check);
  }

  function init() {
    document.addEventListener("khanna:navigate", function (e) {
      if (e.detail.view !== "form-check") return;
      build();
    });
    if (location.hash.indexOf("form-check") !== -1) build();
  }

  global.KhannaFormCheck = { build: build, _state: st };

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})(window);
