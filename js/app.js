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

    function setToggleState(isOpen) {
      utils.qsa("[data-nav-toggle]").forEach(function (btn) {
        btn.setAttribute("aria-expanded", isOpen ? "true" : "false");
        btn.setAttribute("aria-label", isOpen ? "Close menu" : "Open menu");
      });
    }
    function open() {
      drawer.classList.add("is-open");
      drawer.setAttribute("aria-hidden", "false");
      setToggleState(true);
    }
    function close() {
      drawer.classList.remove("is-open");
      drawer.setAttribute("aria-hidden", "true");
      setToggleState(false);
    }

    // The hamburger button is a real open/close TOGGLE (not open-only) —
    // clicking it while the drawer is already open closes it again, the
    // expected behaviour for the only nav entry point in the app now that
    // the header nav bar and sidebar have been removed (see
    // vercel-migration-status.md). stopPropagation keeps this click from
    // also being seen by any outside-click-to-close logic elsewhere.
    utils.on(document, "click", "[data-nav-toggle]", function (e) {
      e.stopPropagation();
      if (drawer.classList.contains("is-open")) {
        close();
      } else {
        open();
      }
    });
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
