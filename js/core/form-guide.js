/* ==========================================================================
   Khanna Travels & Holidays — less text on screen, and needed fields

   Works on every page without changing any page's own code:

   1. Explanations behind an ⓘ.
      The small grey help texts under fields (.field > .field-hint), under
      step headings (.form-step__hint) and the page / panel introductions
      listed in COLLAPSE are hidden. An ⓘ button is put next to the field's
      label (or the heading) instead; pressing it shows the text, pressing
      again hides it. Status lines, warnings, errors and every "OCR Extracted
      — Please Verify" note are NOT touched — they stay visible.

   2. Needed fields (marked * on their label, or required) are checked when
      staff press a Generate / Save button (or submit a form):
        - if one is empty, nothing happens except: those fields are outlined
          in red, each gets an ⓘ saying what is needed (with the field's own
          explanation), the first one is scrolled to, and a short message
          says how many are missing;
        - a Generate button that is greyed out because the page is not ready
          yet answers a press the same way, or — when no field is empty —
          shows the page's own reason in a short message.
      Typing in a field removes its red outline.

   New content drawn later by any page is handled too (MutationObserver).
   ========================================================================== */
(function (global) {
  "use strict";

  var INFO_SVG =
    '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="9"/><path d="M12 11v5M12 8h.01"/></svg>';

  // Help texts to put behind an ⓘ. Each entry: the text element, and where its ⓘ goes.
  var COLLAPSE = [
    { sel: ".field > .field-hint", anchor: "label" },
    { sel: ".form-step__hint", anchor: ".form-step__title" },
    { sel: ".source-option__help", anchor: ".source-option__title" },
    { sel: ".ap-intro", anchor: "page" },
    { sel: ".rb-intro", anchor: "page" },
    { sel: ".cdm-help", anchor: "previous" },
    { sel: ".auth-subhead__hint", anchor: "parent" },
    { sel: ".vf-intro", anchor: "page" },
    { sel: ".quick-add__intro", anchor: "previous" },
    // A grey explanation right under a heading (section and card titles).
    { sel: "h1 + p.field-hint, h2 + p.field-hint, h3 + p.field-hint, h4 + p.field-hint", anchor: "previous" },
    // A help line under a grid of fields belongs to the last field above it.
    { sel: ".field-grid + .field-hint", anchor: "gridLast" },
    // Explanations a page marks on purpose: ⓘ on the nearest heading above.
    { sel: ".fg-explain", anchor: "heading" },
  ];

  // Never hidden: states, warnings, results, things staff must see.
  var KEEP_CLASSES = ["ap-reply-tag", "vf-verify", "lw-status", "doc-preview-bar__id", "country-combo__empty", "cover-existing-list__empty", "vf-count", "cdm-note"];
  var KEEP_TEXT = /please verify|not saved|cannot be undone|warning|error/i;

  var SUBMIT_TEXT = /^\s*(generate|save|create)\b/i;

  var uid = 0;

  function qsa(sel, root) {
    return Array.prototype.slice.call((root || document).querySelectorAll(sel));
  }

  function visible(el) {
    return !!(el && el.getClientRects().length && getComputedStyle(el).visibility !== "hidden");
  }

  function keep(el) {
    if (el.hasAttribute("data-keep-text") || el.getAttribute("role") === "status" || el.getAttribute("role") === "alert") return true;
    if (el.closest(".notice, [data-keep-text], .app-picker__header")) return true;
    for (var i = 0; i < KEEP_CLASSES.length; i++) if (el.classList.contains(KEEP_CLASSES[i])) return true;
    var text = (el.textContent || "").trim();
    return !text || KEEP_TEXT.test(text);
  }

  function infoButton(label, missing) {
    var b = document.createElement("button");
    b.type = "button";
    b.className = "fg-info" + (missing ? " fg-info--missing" : "");
    b.setAttribute("aria-label", label);
    b.setAttribute("title", label);
    b.setAttribute("aria-expanded", "false");
    b.innerHTML = INFO_SVG;
    return b;
  }

  /* ---------------------------------------------------------------------
   * 1. Help texts behind an ⓘ
   * ------------------------------------------------------------------- */

  function anchorFor(el, how) {
    if (how === "label") {
      var field = el.parentElement;
      return field && (field.querySelector(":scope > label, :scope > .vf-label, :scope > legend") || null);
    }
    if (how === "page") {
      var view = el.closest(".view");
      return view && view.querySelector(".view-header__text h1");
    }
    if (how === "previous") {
      var prev = el.previousElementSibling;
      return prev && /^(H[1-6]|LABEL|LEGEND)$/.test(prev.tagName) ? prev : prev && prev.querySelector("h2, h3, h4");
    }
    if (how === "parent") return el.parentElement;
    if (how === "gridLast") {
      var grid = el.previousElementSibling;
      var fields = grid ? grid.querySelectorAll(":scope > .field") : [];
      var last = fields.length ? fields[fields.length - 1] : null;
      return last && last.querySelector(":scope > label");
    }
    if (how === "heading") {
      var node = el;
      for (var depth = 0; node && depth < 6; depth++) {
        var sib = node.previousElementSibling;
        while (sib) {
          if (/^H[1-4]$/.test(sib.tagName)) return sib;
          if (sib.classList && sib.classList.contains("form-step")) return sib.querySelector(".form-step__title");
          sib = sib.previousElementSibling;
        }
        node = node.parentElement;
        if (node && node.classList && node.classList.contains("view")) break;
      }
      return null;
    }
    var box = el.closest(".form-step, .source-option, .card, .field") || el.parentElement;
    return box && box.querySelector(how);
  }

  function collapseHint(el, how) {
    if (el.getAttribute("data-fg")) return;
    el.setAttribute("data-fg", "1");
    if (keep(el)) return;
    var anchor = anchorFor(el, how);
    if (!anchor) return;
    // One ⓘ per anchor: several texts for the same label open together.
    var btn = anchor.querySelector(":scope > .fg-info:not(.fg-info--missing)");
    if (!btn) {
      btn = infoButton("What is this?");
      anchor.appendChild(btn);
    }
    if (!el.id) el.id = "fg-tip-" + ++uid;
    var ids = (btn.getAttribute("aria-controls") || "").split(" ").filter(Boolean);
    if (ids.indexOf(el.id) === -1) ids.push(el.id);
    btn.setAttribute("aria-controls", ids.join(" "));
    el.classList.add("fg-tip");
  }

  function collapseAll(root) {
    COLLAPSE.forEach(function (c) {
      qsa(c.sel, root).forEach(function (el) { collapseHint(el, c.anchor); });
      if (root.matches && root.matches(c.sel)) collapseHint(root, c.anchor);
    });
  }

  function toggleTip(btn) {
    var open = btn.getAttribute("aria-expanded") !== "true";
    btn.setAttribute("aria-expanded", open ? "true" : "false");
    (btn.getAttribute("aria-controls") || "").split(" ").forEach(function (id) {
      var tip = id && document.getElementById(id);
      if (tip) tip.classList.toggle("fg-tip--open", open);
    });
  }

  /* ---------------------------------------------------------------------
   * 2. Needed fields
   * ------------------------------------------------------------------- */

  function labelTextOf(control) {
    var field = control.closest(".field");
    var label = (control.id && document.querySelector('label[for="' + CSS.escape(control.id) + '"]')) ||
      (field && field.querySelector(":scope > label, :scope > .vf-label, :scope > legend"));
    return label ? (label.textContent || "").replace(/\s+/g, " ").trim() : "";
  }

  function isNeeded(control) {
    if (control.required || control.getAttribute("aria-required") === "true") return true;
    var field = control.closest(".field");
    if (field && field.querySelector(":scope > label .vf-req, :scope > .vf-label .vf-req, :scope > label .required-star")) return true;
    return /\*\s*$/.test(labelTextOf(control));
  }

  function isEmpty(control) {
    if (control.type === "radio" || control.type === "checkbox") {
      var field = control.closest(".field");
      var group = field ? qsa('input[type="' + control.type + '"]', field) : [control];
      return !group.some(function (c) { return c.checked; });
    }
    return !String(control.value || "").trim();
  }

  /** The empty needed fields of a container: one entry per field. */
  function missingFields(container) {
    var seen = [];
    var out = [];
    qsa("input, select, textarea", container).forEach(function (c) {
      if (c.disabled || c.type === "hidden" || c.type === "file" || c.readOnly || !visible(c)) return;
      if (c.closest("[data-fg-skip]")) return;
      var field = c.closest(".field") || c.parentElement;
      if (seen.indexOf(field) !== -1) return;
      if (!isNeeded(c)) return;
      seen.push(field);
      if (isEmpty(c)) out.push({ field: field, control: c, label: labelTextOf(c).replace(/\s*\*\s*$/, "") });
    });
    return out;
  }

  function markMissing(item) {
    var field = item.field;
    field.classList.add("fg-missing");
    if (field.querySelector(".fg-need")) return;
    var label = field.querySelector(":scope > label, :scope > .vf-label, :scope > legend");
    var tip = document.createElement("span");
    tip.className = "fg-need fg-tip";
    tip.id = "fg-tip-" + ++uid;
    var own = field.querySelector(":scope > .fg-tip:not(.fg-need)");
    tip.textContent = "Needed: " + (item.label || "this field") + "." + (own ? " " + own.textContent.trim() : "");
    var btn = infoButton("Why is this needed?", true);
    btn.setAttribute("aria-controls", tip.id);
    if (label) label.appendChild(btn);
    else field.insertBefore(btn, field.firstChild);
    field.appendChild(tip);
  }

  function clearMissing(field) {
    field.classList.remove("fg-missing");
    qsa(":scope > .fg-need, :scope .fg-info--missing", field).forEach(function (n) {
      if (n.closest(".field") === field || n.parentElement === field) n.remove();
    });
  }

  function containerOf(btn) {
    return btn.closest("form, [role='dialog']") || btn.closest(".view") || document.body;
  }

  function toast(msg, type) {
    if (global.KhannaToast) global.KhannaToast.show(msg, type ? { type: type } : undefined);
  }

  /** Marks the empty needed fields; returns how many there were. */
  function checkNeeded(container) {
    var missing = missingFields(container);
    missing.forEach(markMissing);
    if (missing.length) {
      var first = missing[0].control;
      try {
        first.scrollIntoView({ block: "center", behavior: "smooth" });
      } catch (e) {
        first.scrollIntoView();
      }
      if (first.focus) first.focus({ preventScroll: true });
      toast(missing.length === 1 ? "Fill in " + (missing[0].label || "the field marked in red") + " first." : "Fill in the " + missing.length + " fields marked in red first.", "error");
    }
    return missing.length;
  }

  function isSubmitButton(btn) {
    if (!btn || btn.closest("[data-fg-skip]")) return false;
    if (btn.type === "submit" && btn.form) return true;
    if (!btn.classList.contains("btn-primary")) return false;
    return SUBMIT_TEXT.test(btn.textContent || "") || /^generate/i.test(btn.getAttribute("data-action") || "");
  }

  function onClickCapture(e) {
    var btn = e.target.closest && e.target.closest("button");
    if (!btn || btn.disabled || !isSubmitButton(btn)) return;
    if (checkNeeded(containerOf(btn))) {
      e.preventDefault();
      e.stopImmediatePropagation();
    }
  }

  // A greyed-out Generate button gets no "click" — answer the press itself.
  function onPointerUp(e) {
    var btn = e.target.closest && e.target.closest("button");
    if (!btn || !btn.disabled || !isSubmitButton(btn)) return;
    var container = containerOf(btn);
    if (checkNeeded(container)) return;
    var reason = qsa(".notice-warning, .notice-danger, .ud-warn", container).filter(visible)[0];
    var text = reason ? (reason.textContent || "").replace(/\s+/g, " ").trim() : "";
    if (text) toast(text.length > 220 ? text.slice(0, 217) + "…" : text, "error");
  }

  function onInput(e) {
    var field = e.target.closest && e.target.closest(".fg-missing");
    if (field && !isEmpty(e.target)) clearMissing(field);
  }

  function onInfoClick(e) {
    var btn = e.target.closest && e.target.closest(".fg-info");
    if (!btn) return;
    // Inside a <label>: do not also tick its checkbox / focus its input.
    e.preventDefault();
    e.stopPropagation();
    toggleTip(btn);
  }

  /* ---------------------------------------------------------------------
   * Start
   * ------------------------------------------------------------------- */

  var pending = [];
  var scheduled = false;

  function flush() {
    scheduled = false;
    var nodes = pending;
    pending = [];
    nodes.forEach(function (n) {
      if (n.isConnected) collapseAll(n);
    });
  }

  function init() {
    collapseAll(document.body);
    new MutationObserver(function (records) {
      records.forEach(function (r) {
        r.addedNodes.forEach(function (n) {
          if (n.nodeType === 1 && !n.classList.contains("fg-info") && !n.classList.contains("fg-need")) pending.push(n);
        });
      });
      if (pending.length && !scheduled) {
        scheduled = true;
        (global.requestAnimationFrame || setTimeout)(flush);
      }
    }).observe(document.body, { childList: true, subtree: true });
    document.addEventListener("click", onInfoClick, true);
    document.addEventListener("click", onClickCapture, true);
    document.addEventListener("pointerup", onPointerUp, true);
    document.addEventListener("input", onInput, true);
    document.addEventListener("change", onInput, true);
  }

  global.KhannaFormGuide = { checkNeeded: checkNeeded, missingFields: missingFields };

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})(window);
