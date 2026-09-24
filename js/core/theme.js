/* ==========================================================================
   Khanna Travels & Holidays — Light/Dark theme
   Persists the user's explicit choice; otherwise follows the OS preference.
   ========================================================================== */

(function (global) {
  "use strict";

  var STORAGE_KEY = "khanna_theme"; // "light" | "dark" | not set = follow system
  var storage = global.KhannaUtils.storage;

  function getStoredTheme() {
    return storage.get(STORAGE_KEY, null);
  }

  function getSystemTheme() {
    return window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches
      ? "dark"
      : "light";
  }

  function currentTheme() {
    return getStoredTheme() || getSystemTheme();
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

    // Follow system changes only while the user hasn't made an explicit choice.
    if (window.matchMedia) {
      window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", function () {
        if (!getStoredTheme()) apply(getSystemTheme());
      });
    }

    global.KhannaUtils.on(document, "click", "[data-theme-toggle]", function () {
      toggle();
    });
  }

  global.KhannaTheme = { init: init, toggle: toggle, current: currentTheme };
})(window);
