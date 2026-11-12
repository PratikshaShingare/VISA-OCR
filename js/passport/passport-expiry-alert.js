/* ==========================================================================
   Khanna Travels & Holidays — passport expiry alert
   After a passport is read (Upload Passport, Upload Documents, Fill Forms,
   Check Forms), staff get a popup when the passport has expired or expires
   within one year. Many countries refuse a visa when the passport is valid
   for less than 6 months after the trip, so this has to be seen before any
   documents are made.

   The date was read by OCR, so the popup says so (project rule 10). The same
   passport is reported once per page load. Nothing is stored or logged.

       KhannaPassportExpiry.check(expiryDate, label)
         expiryDate: ISO "YYYY-MM-DD" or "DD-MM-YYYY"; label: who (name / file)
   ========================================================================== */
(function (global) {
  "use strict";

  var utils = global.KhannaUtils;
  var shown = {};
  var modalEl = null;
  var lastFocus = null;

  function parse(value) {
    var form = global.KhannaPassportReviewForm;
    var p = form && form.parseDate ? form.parseDate(value) : null;
    if (!p) return null;
    var parts = p.iso.split("-");
    return { date: new Date(+parts[0], +parts[1] - 1, +parts[2]), display: p.display };
  }

  function today() {
    var d = new Date();
    return new Date(d.getFullYear(), d.getMonth(), d.getDate());
  }

  /** Whole months and leftover days from `from` to `to` (to >= from). */
  function monthsBetween(from, to) {
    var months = (to.getFullYear() - from.getFullYear()) * 12 + (to.getMonth() - from.getMonth());
    if (to.getDate() < from.getDate()) months -= 1;
    return Math.max(0, months);
  }

  /**
   * null when the passport is valid for more than a year (or the date is
   * unreadable); otherwise { level: "expired"|"soon", text }.
   */
  function assess(expiryValue, now) {
    var exp = parse(expiryValue);
    if (!exp) return null;
    var base = now || today();
    var oneYear = new Date(base.getFullYear() + 1, base.getMonth(), base.getDate());
    if (exp.date > oneYear) return null;
    var days = Math.round((exp.date - base) / 86400000);
    if (days < 0) {
      return { level: "expired", display: exp.display, text: "expired on " + exp.display + " (" + (-days) + " day" + (days === -1 ? "" : "s") + " ago)." };
    }
    if (days === 0) return { level: "expired", display: exp.display, text: "expires TODAY (" + exp.display + ")." };
    var months = monthsBetween(base, exp.date);
    var span = months >= 1 ? months + " month" + (months === 1 ? "" : "s") : days + " day" + (days === 1 ? "" : "s");
    return { level: "soon", display: exp.display, text: "expires on " + exp.display + " — in " + span + "." };
  }

  function ensureModal() {
    if (modalEl) return;
    var wrap = document.createElement("div");
    wrap.className = "app-picker-overlay";
    wrap.setAttribute("hidden", "");
    wrap.setAttribute("data-passport-expiry-modal", "");
    wrap.innerHTML =
      '<div class="app-picker passport-expiry" role="alertdialog" aria-modal="true" aria-labelledby="ppExpiryTitle" aria-describedby="ppExpiryList">' +
      '<div class="app-picker__header">' +
      '<h3 id="ppExpiryTitle">Passport expiry — please check</h3>' +
      '<button type="button" class="btn-icon" data-passport-expiry-close aria-label="Close">' +
      '<svg class="icon icon-sm" viewBox="0 0 24 24"><path d="M6 6l12 12M18 6 6 18"/></svg>' +
      "</button></div>" +
      '<ul class="passport-expiry__list" id="ppExpiryList" data-passport-expiry-list></ul>' +
      '<p class="field-hint" style="margin:0;">Many countries need the passport to be valid for at least 6 months after the trip. ' +
      "The expiry date was read by OCR — check it on the passport itself (OCR Extracted — Please Verify).</p>" +
      '<div style="display:flex;justify-content:flex-end;">' +
      '<button type="button" class="btn btn-primary btn-sm" data-passport-expiry-close>OK</button>' +
      "</div></div>";
    document.body.appendChild(wrap);
    modalEl = wrap;
    utils.on(wrap, "click", "[data-passport-expiry-close]", close);
    wrap.addEventListener("click", function (e) {
      if (e.target === wrap) close();
    });
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape" && modalEl && !modalEl.hasAttribute("hidden")) close();
    });
  }

  function close() {
    if (!modalEl) return;
    modalEl.setAttribute("hidden", "");
    utils.qs("[data-passport-expiry-list]", modalEl).innerHTML = "";
    if (lastFocus && lastFocus.focus && document.contains(lastFocus)) lastFocus.focus();
    lastFocus = null;
  }

  function show(label, result) {
    ensureModal();
    var list = utils.qs("[data-passport-expiry-list]", modalEl);
    var li = document.createElement("li");
    li.className = "passport-expiry__item passport-expiry__item--" + result.level;
    li.innerHTML = "<strong>" + utils.escapeHtml(label || "This passport") + "</strong> " + utils.escapeHtml(result.text);
    list.appendChild(li); // several passports read in one go share one popup
    if (modalEl.hasAttribute("hidden")) {
      lastFocus = document.activeElement;
      modalEl.removeAttribute("hidden");
      var ok = modalEl.querySelector(".btn-primary[data-passport-expiry-close]");
      if (ok) ok.focus();
    }
  }

  /** Shows the popup when needed; returns the assessment (or null). */
  function check(expiryValue, label, key) {
    var result = assess(expiryValue);
    if (!result) return null;
    var id = (key || label || "") + "|" + result.display;
    if (shown[id]) return result;
    shown[id] = true;
    show(label, result);
    return result;
  }

  global.KhannaPassportExpiry = { check: check, assess: assess, close: close };
})(window);
