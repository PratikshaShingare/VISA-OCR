/* ==========================================================================
   Khanna Travels & Holidays — App bootstrap
   Wires up the shell: theme, router, mobile nav drawer, footer year.
   Feature modules (passport, applicant, travellers, documents, ...) register
   themselves independently as they are added in later phases.
   ========================================================================== */

(function (global) {
  "use strict";

  var utils = global.KhannaUtils;

  function initMobileNav() {
    var drawer = utils.qs("[data-mobile-nav]");
    if (!drawer) return;

    function open() {
      drawer.classList.add("is-open");
      drawer.setAttribute("aria-hidden", "false");
    }
    function close() {
      drawer.classList.remove("is-open");
      drawer.setAttribute("aria-hidden", "true");
    }

    utils.on(document, "click", "[data-nav-toggle]", open);
    utils.on(document, "click", "[data-mobile-nav-close]", close);
    utils.on(document, "click", "[data-mobile-nav-backdrop]", close);

    // Close the drawer whenever a nav link inside it is used.
    utils.on(drawer, "click", "[data-nav-link]", close);

    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape") close();
    });
  }

  function initFooterYear() {
    var el = utils.qs("[data-current-year]");
    if (el) el.textContent = String(new Date().getFullYear());
  }

  // Header "New Application" quick-choice menu (document-first redesign,
  // Phase 1): open/close/outside-click/Escape toggle for the dropdown that
  // lists the guided wizard plus all six standalone document types and
  // Upload Passport. Written fresh rather than sharing auth-view.js's
  // profile-menu dropdown logic — that code is already working and tested,
  // and this menu's trigger/dropdown are a different pair of elements, so
  // reusing it would mean reaching into another module's DOM lookups for a
  // handful of near-identical lines (project rule 16: don't touch working
  // code without reason).
  function initNewApplicationMenu() {
    var wrap = utils.qs("[data-new-app-menu]");
    if (!wrap) return;

    function dropdown() {
      return utils.qs("[data-new-app-menu-dropdown]");
    }
    function toggleBtn() {
      return utils.qs("[data-new-app-menu-toggle]");
    }

    function close() {
      var dd = dropdown();
      var btn = toggleBtn();
      if (dd) dd.classList.remove("is-open");
      if (btn) btn.setAttribute("aria-expanded", "false");
    }

    utils.on(document, "click", "[data-new-app-menu-toggle]", function (e, target) {
      e.stopPropagation();
      var dd = dropdown();
      if (!dd) return;
      var willOpen = !dd.classList.contains("is-open");
      dd.classList.toggle("is-open", willOpen);
      target.setAttribute("aria-expanded", willOpen ? "true" : "false");
    });

    document.addEventListener("click", function (e) {
      if (!wrap.contains(e.target)) close();
    });
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape") close();
    });
    utils.on(wrap, "click", ".profile-menu__item", close);
  }

  function init() {
    // KhannaState loads its persisted data as soon as its own script runs
    // (see js/core/state.js), so no explicit init() call is needed here.
    global.KhannaTheme.init();
    global.KhannaRouter.init();
    initMobileNav();
    initFooterYear();
    initNewApplicationMenu();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})(window);
