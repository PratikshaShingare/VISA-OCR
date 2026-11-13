/* ==========================================================================
   Khanna Travels & Holidays — every date is typed as DD/MM/YYYY

   A browser's own date box (<input type="date">) shows the computer's
   language setting — MM/DD/YYYY on an English (US) Windows. This file puts a
   DD/MM/YYYY box in front of every date box on every page, without changing
   any page's own code:

     - the original date box stays in the page (hidden), with its id, name
       and data-* attributes, and keeps holding the date as YYYY-MM-DD — so
       everything that reads or saves dates works exactly as before;
     - staff type digits ("14052026") and the slashes are put in for them;
       "14-05-2026" and "14.05.2026" are accepted too;
     - a complete, real date is written into the original box, which then
       fires its normal "input" and "change" events; an impossible date
       ("31/02/2026") or one outside the box's min / max is outlined in red
       and not used;
     - the calendar button opens the browser's own calendar; a date picked
       there shows up as DD/MM/YYYY;
     - when a page fills a date in by itself (from a passport, a voucher, a
       saved application), the DD/MM/YYYY box follows.

   New date boxes drawn later by any page are handled too (MutationObserver).
   ========================================================================== */
(function (global) {
  "use strict";

  var CAL_SVG =
    '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="3" y="5" width="18" height="16" rx="2"/><path d="M16 3v4M8 3v4M3 10h18"/></svg>';

  var nativeValue = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value");

  function pad2(n) {
    return (n < 10 ? "0" : "") + n;
  }

  /** "2026-05-14" -> "14/05/2026" ("" for anything else). */
  function isoToDisplay(iso) {
    var m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(iso || ""));
    return m ? m[3] + "/" + m[2] + "/" + m[1] : "";
  }

  /** "14/05/2026", "14-05-2026", "14.05.2026", "14052026" -> "2026-05-14", or null. */
  function displayToIso(text) {
    var t = String(text || "").trim();
    var m = /^(\d{1,2})\s*[\/.\-]\s*(\d{1,2})\s*[\/.\-]\s*(\d{4})$/.exec(t) || /^(\d{2})(\d{2})(\d{4})$/.exec(t);
    if (!m) return null;
    var d = +m[1];
    var mo = +m[2];
    var y = +m[3];
    var dt = new Date(y, mo - 1, d);
    if (dt.getFullYear() !== y || dt.getMonth() !== mo - 1 || dt.getDate() !== d || y < 1900 || y > 2100) return null;
    return y + "-" + pad2(mo) + "-" + pad2(d);
  }

  function inRange(native, iso) {
    if (native.min && iso < native.min) return false;
    if (native.max && iso > native.max) return false;
    return true;
  }

  function fire(el, type) {
    el.dispatchEvent(new Event(type, { bubbles: true }));
  }

  function enhance(native) {
    if (native.__ddmm || native.closest("[data-native-date]")) return;
    native.__ddmm = true;

    var wrap = document.createElement("span");
    wrap.className = "ddmm";
    var box = document.createElement("input");
    box.type = "text";
    box.className = "ddmm__text";
    box.inputMode = "numeric";
    box.autocomplete = "off";
    box.maxLength = 10;
    box.placeholder = "DD/MM/YYYY";
    var label = native.id && document.querySelector('label[for="' + CSS.escape(native.id) + '"]');
    box.setAttribute("aria-label", ((label && label.textContent) || native.getAttribute("aria-label") || "Date").replace(/\s*\*\s*$/, "").trim() + " (DD/MM/YYYY)");
    var cal = document.createElement("button");
    cal.type = "button";
    cal.className = "ddmm__cal";
    cal.tabIndex = -1;
    cal.setAttribute("aria-label", "Open calendar");
    cal.innerHTML = CAL_SVG;

    native.parentNode.insertBefore(wrap, native);
    wrap.appendChild(box);
    wrap.appendChild(cal);
    wrap.appendChild(native);
    native.classList.add("ddmm__native");
    native.tabIndex = -1;
    native.setAttribute("aria-hidden", "true");

    function sync() {
      box.value = isoToDisplay(nativeValue.get.call(native));
      box.classList.remove("is-invalid");
      box.disabled = native.disabled;
      box.readOnly = native.readOnly;
    }

    // A page that sets the date itself (native.value = "2026-05-14") updates the box too.
    Object.defineProperty(native, "value", {
      configurable: true,
      get: function () { return nativeValue.get.call(native); },
      set: function (v) {
        nativeValue.set.call(native, v);
        sync();
      },
    });

    function commit(iso) {
      if (nativeValue.get.call(native) === iso) return;
      nativeValue.set.call(native, iso);
      fire(native, "input");
      fire(native, "change");
    }

    box.addEventListener("input", function (e) {
      var raw = box.value;
      // Digits only: put the slashes in (not while deleting or editing in the middle).
      if (!/[^\d\/.\- ]/.test(raw) && !(e.inputType && /^delete/.test(e.inputType)) && box.selectionStart === raw.length) {
        var digits = raw.replace(/\D/g, "").slice(0, 8);
        var out = digits.slice(0, 2);
        if (digits.length > 2) out += "/" + digits.slice(2, 4);
        if (digits.length > 4) out += "/" + digits.slice(4);
        if (out !== raw && /^[\d\/]*$/.test(raw)) box.value = out;
      }
      var iso = displayToIso(box.value);
      if (iso && inRange(native, iso)) {
        box.classList.remove("is-invalid");
        commit(iso);
      } else if (!box.value.trim()) {
        box.classList.remove("is-invalid");
        commit("");
      }
    });
    box.addEventListener("blur", function () {
      var text = box.value.trim();
      if (!text) {
        commit("");
        return;
      }
      var iso = displayToIso(text);
      if (iso && inRange(native, iso)) {
        box.value = isoToDisplay(iso);
        box.classList.remove("is-invalid");
        commit(iso);
      } else {
        box.classList.add("is-invalid");
        box.title = iso ? "This date is not allowed here." : "Enter the date as DD/MM/YYYY.";
      }
      fire(native, "blur");
    });
    // The browser's calendar: what is picked there comes back as DD/MM/YYYY.
    cal.addEventListener("click", function () {
      if (native.disabled || native.readOnly) return;
      try {
        if (native.showPicker) native.showPicker();
      } catch (e) {
        box.focus();
      }
    });
    if (native.form) native.form.addEventListener("reset", function () { setTimeout(sync, 0); });
    native.addEventListener("input", sync);
    native.addEventListener("change", sync);
    // Something sending the cursor to the hidden box (a label, a "fill this in" jump) lands in the text box.
    native.addEventListener("focus", function () {
      if (document.activeElement === native) box.focus();
    });
    sync();
  }

  function scan(root) {
    if (root.matches && root.matches('input[type="date"]')) enhance(root);
    if (root.querySelectorAll) Array.prototype.forEach.call(root.querySelectorAll('input[type="date"]'), enhance);
  }

  function init() {
    scan(document.body);
    new MutationObserver(function (records) {
      records.forEach(function (r) {
        r.addedNodes.forEach(function (n) {
          if (n.nodeType === 1) scan(n);
        });
        // A date box whose disabled / min / max changed after it was drawn.
        if (r.type === "attributes" && r.target.__ddmm) {
          var box = r.target.parentNode && r.target.parentNode.querySelector(".ddmm__text");
          if (box) box.disabled = r.target.disabled;
        }
      });
    }).observe(document.body, { childList: true, subtree: true, attributes: true, attributeFilter: ["disabled"] });
  }

  global.KhannaDateInput = { isoToDisplay: isoToDisplay, displayToIso: displayToIso };

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})(window);
