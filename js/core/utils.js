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

  // Delegated listeners are remembered per element + event + selector, and
  // registering the same one again REPLACES the earlier listener instead of
  // stacking a second copy. Every page's mountSkeleton() wires its handlers
  // on a root element that lives for the whole session (it only rebuilds the
  // root's contents), so every re-mount — switching application, or going
  // from "no application" to one — used to add another full set of
  // listeners: one click on "Add hotel Manually" then added a hotel per
  // stacked copy (3-5 hotels at once). `onReplaced` is a test hook only.
  var delegatedListeners = new WeakMap();

  function on(el, event, selectorOrHandler, maybeHandler) {
    if (!el) return;
    if (typeof selectorOrHandler === "function") {
      el.addEventListener(event, selectorOrHandler);
      return;
    }
    // Delegated listener: on(container, 'click', '.btn', handler)
    var key = event + "\u0000" + selectorOrHandler;
    var registry = delegatedListeners.get(el);
    if (!registry) {
      registry = {};
      delegatedListeners.set(el, registry);
    }
    if (registry[key]) {
      el.removeEventListener(event, registry[key]);
      if (global.__khannaOnReplaced) global.__khannaOnReplaced.push(key);
    }
    var listener = function (e) {
      var target = e.target.closest(selectorOrHandler);
      if (target && el.contains(target)) {
        maybeHandler.call(target, e, target);
      }
    };
    registry[key] = listener;
    el.addEventListener(event, listener);
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

  // Today's date as YYYY-MM-DD in the user's own clock — the value date
  // inputs use for `min` ("no dates in the past") and what stored ISO dates
  // are compared against. Not toISOString(): that is UTC and can be a day off.
  function todayIso() {
    var d = new Date();
    var m = String(d.getMonth() + 1).padStart(2, "0");
    var day = String(d.getDate()).padStart(2, "0");
    return d.getFullYear() + "-" + m + "-" + day;
  }

  // "19 Oct 2026, 3:42 pm" — the date plus the time, in the user's own clock.
  function formatDateTime(value) {
    if (!value) return "";
    var d = value instanceof Date ? value : new Date(value);
    if (isNaN(d.getTime())) return String(value);
    var time = d.toLocaleTimeString("en-IN", { hour: "numeric", minute: "2-digit", hour12: true }).replace(/\s?(am|pm)/i, function (m) { return " " + m.trim().toLowerCase(); });
    return formatDate(d) + ", " + time;
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
    todayIso: todayIso,
    formatDateTime: formatDateTime,
    statusBadgeClass: statusBadgeClass,
    storage: storage,
    triggerFileDownload: triggerFileDownload,
    enableScrollShadows: enableScrollShadows,
  };
})(window);
