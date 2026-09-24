/* ==========================================================================
   Khanna Travels & Holidays — shared utilities
   Small, dependency-free helpers used across the app's JS modules.
   ========================================================================== */

(function (global) {
  "use strict";

  function qs(selector, scope) {
    return (scope || document).querySelector(selector);
  }

  function qsa(selector, scope) {
    return Array.prototype.slice.call((scope || document).querySelectorAll(selector));
  }

  function on(el, event, selectorOrHandler, maybeHandler) {
    if (!el) return;
    if (typeof selectorOrHandler === "function") {
      el.addEventListener(event, selectorOrHandler);
      return;
    }
    // Delegated listener: on(container, 'click', '.btn', handler)
    el.addEventListener(event, function (e) {
      var target = e.target.closest(selectorOrHandler);
      if (target && el.contains(target)) {
        maybeHandler.call(target, e, target);
      }
    });
  }

  function debounce(fn, wait) {
    var timer = null;
    return function () {
      var args = arguments;
      var ctx = this;
      clearTimeout(timer);
      timer = setTimeout(function () {
        fn.apply(ctx, args);
      }, wait || 200);
    };
  }

  function escapeHtml(value) {
    if (value === null || value === undefined) return "";
    return String(value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function generateId(prefix) {
    var rand = Math.random().toString(36).slice(2, 9);
    return (prefix || "id") + "_" + Date.now().toString(36) + rand;
  }

  function formatDate(value) {
    if (!value) return "";
    var d = value instanceof Date ? value : new Date(value);
    if (isNaN(d.getTime())) return String(value);
    return d.toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "numeric" });
  }

  /**
   * localStorage wrapper that never throws (private browsing / disabled storage
   * safe) and always deals in parsed JSON.
   */
  var storage = {
    get: function (key, fallback) {
      try {
        var raw = window.localStorage.getItem(key);
        return raw === null ? fallback : JSON.parse(raw);
      } catch (e) {
        return fallback;
      }
    },
    set: function (key, value) {
      try {
        window.localStorage.setItem(key, JSON.stringify(value));
        return true;
      } catch (e) {
        return false;
      }
    },
    remove: function (key) {
      try {
        window.localStorage.removeItem(key);
      } catch (e) {
        /* no-op */
      }
    },
  };

  var STATUS_BADGE_CLASS = {
    Draft: "badge",
    New: "badge-info",
    "Documents Pending": "badge-warning",
    "Documents Received": "badge-info",
    "Under Review": "badge-warning",
    "Ready for Submission": "badge-info",
    Submitted: "badge-info",
    Processing: "badge-warning",
    Approved: "badge-success",
    Rejected: "badge-danger",
    Cancelled: "badge-danger",
  };

  function statusBadgeClass(status) {
    return STATUS_BADGE_CLASS[status] || "badge";
  }

  /**
   * Saves a downloaded file Blob to the user's machine via a temporary
   * `<a download>` link. Extracted in Phase 8 out of hotels.js (the first
   * module that needed it, for the Hotel Voucher download) so the
   * Authorization Letter downloads — and any future document download —
   * don't duplicate the same few lines (project rule 15).
   */
  function triggerFileDownload(blob, filename) {
    var url = URL.createObjectURL(blob);
    var a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(function () {
      URL.revokeObjectURL(url);
    }, 1000);
  }

  /**
   * Wires a real, scroll-position-driven "there's more content this way"
   * fade onto a horizontally-scrollable strip (a wide data table, the
   * wizard's own step strip, etc.) — added in Phase 12 after confirming,
   * with real measurements, that several such strips in this app scroll
   * with zero visual hint at narrow widths (project rule 13: "mobile must
   * be designed intentionally").
   *
   * `scrollEl` is the actual `overflow-x: auto` element; `fadeEl` (often a
   * non-scrolling wrapper around it — see .scroll-fade in components.css)
   * is the element whose `.has-scroll-start`/`.has-scroll-end` classes get
   * toggled, matching its own real scroll position. Passing `fadeEl` equal
   * to `scrollEl` is fine too, but the two are only ever the same
   * element when nothing inside needs to sit fixed at the edges. The fade
   * is CSS (components.css's `.scroll-fade`); this only ever reflects real
   * scrollable state, never shows an affordance for content that isn't
   * actually there (project rule 9).
   *
   * Returns the `update()` function so a caller whose content changes size
   * after render (e.g. more table rows) can re-check without waiting for a
   * scroll/resize event.
   */
  function enableScrollShadows(scrollEl, fadeEl) {
    if (!scrollEl) return function () {};
    var target = fadeEl || scrollEl;
    function update() {
      var maxScroll = scrollEl.scrollWidth - scrollEl.clientWidth;
      target.classList.toggle("has-scroll-start", scrollEl.scrollLeft > 1);
      target.classList.toggle("has-scroll-end", scrollEl.scrollLeft < maxScroll - 1);
    }
    scrollEl.addEventListener("scroll", update, { passive: true });
    window.addEventListener("resize", debounce(update, 150));
    update();
    return update;
  }

  global.KhannaUtils = {
    qs: qs,
    qsa: qsa,
    on: on,
    debounce: debounce,
    escapeHtml: escapeHtml,
    generateId: generateId,
    formatDate: formatDate,
    statusBadgeClass: statusBadgeClass,
    storage: storage,
    triggerFileDownload: triggerFileDownload,
    enableScrollShadows: enableScrollShadows,
  };
})(window);
