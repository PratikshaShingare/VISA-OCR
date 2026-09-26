/* ==========================================================================
   Khanna Travels & Holidays — Light/Dark theme
   Light is always the default. Persists the user's explicit choice once
   they toggle to dark via [data-theme-toggle]; the toggle itself is
   unchanged and still required (project rule 8 — the app must support
   both light and dark theme, this just stops auto-switching to dark based
   on the staff member's OS preference, which is what made the app look
   "stuck in dark mode" for anyone whose Windows/browser default is dark).
   ========================================================================== */

(function (global) {
  "use strict";

  var STORAGE_KEY = "khanna_theme"; // "light" | "dark" | not set = light (default)
  var storage = global.KhannaUtils.storage;

  function getStoredTheme() {
    return storage.get(STORAGE_KEY, null);
  }

  function currentTheme() {
    return getStoredTheme() || "light";
  }

  function apply(theme) {
    document.documentElement.setAttribute("data-theme", theme);
    var meta = document.querySelector('meta[name="color-scheme"]');
    if (meta) meta.setAttribute("content", theme === "dark" ? "dark light" : "light dark");
    updateToggleButtons(theme);
  }

  function updateToggleButtons(theme) {
    global.KhannaUtils.qsa("[data-theme-toggle]").forEach(function (btn) {
      btn.setAttribute("aria-pressed", theme === "dark" ? "true" : "false");
      btn.setAttribute(
        "aria-label",
        theme === "dark" ? "Switch to light theme" : "Switch to dark theme"
      );
    });
  }

  function toggle() {
    var next = currentTheme() === "dark" ? "light" : "dark";
    storage.set(STORAGE_KEY, next);
    apply(next);
  }

  function init() {
    apply(currentTheme());

    global.KhannaUtils.on(document, "click", "[data-theme-toggle]", function () {
      toggle();
    });
  }

  global.KhannaTheme = { init: init, toggle: toggle, current: currentTheme };
})(window);
