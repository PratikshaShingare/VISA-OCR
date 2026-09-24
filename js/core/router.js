/* ==========================================================================
   Khanna Travels & Holidays — Shell router
   Hash-based navigation between the top-level views (Dashboard / Applications /
   New Application / Admin) and, inside New Application, between wizard steps.
   Deliberately small: it only handles view switching for this shell. Real
   per-view behaviour (data loading, form logic, auth gating) is wired in by
   later phases without needing to change this file.
   ========================================================================== */

(function (global) {
  "use strict";

  var utils = global.KhannaUtils;
  var DEFAULT_VIEW = "dashboard";
  var VALID_VIEWS = [
    "dashboard",
    "applications",
    "new-application",
    "admin",
    "auth",
    "profile",
    "settings",
    // Document-first redesign (Phase 1): six standalone document workspaces
    // plus the passport-upload entry point. Each is a plain top-level view
    // like "dashboard"/"admin" above — setActiveView()'s existing generic
    // [data-view]/[data-nav-link] handling already covers navigating to and
    // highlighting these with no further changes to this file.
    "cover-letter",
    "hotel-blocking",
    "company-authorization",
    "passport-authorization",
    "checklist-letter",
    "invitation-letter",
    "upload-passport",
  ];
  var WIZARD_STEP_COUNT = 8;

  // Wizard-step completion gate: each step's own module (passport-processing.js
  // for step 1, later phases for the rest) registers a validator here instead
  // of each one reaching into the shared footer button itself. A step with no
  // registered validator keeps "Continue" disabled — that is the honest state
  // for a step that has not been built yet, not a bug.
  var stepValidators = {};

  function stepKey(view, step) {
    return view + "/" + step;
  }

  function registerStepValidator(view, step, fn) {
    stepValidators[stepKey(view, step)] = fn;
    refreshWizardFooter();
  }

  function refreshWizardFooter() {
    var parsed = parseHash();
    var btn = utils.qs("[data-wizard-continue]");
    if (!btn) return;
    if (parsed.view !== "new-application") return;
    var step = parsed.step || 1;
    if (step >= WIZARD_STEP_COUNT) {
      btn.disabled = true; // final-step submission flow arrives in a later phase
      return;
    }
    var validator = stepValidators[stepKey("new-application", step)];
    btn.disabled = validator ? !validator() : true;
  }

  function parseHash() {
    var raw = (location.hash || "").replace(/^#\/?/, "");
    var parts = raw.split("/").filter(Boolean);
    var view = VALID_VIEWS.indexOf(parts[0]) !== -1 ? parts[0] : DEFAULT_VIEW;
    var step = parts[1] ? parseInt(parts[1], 10) : null;
    return { view: view, step: step };
  }

  function navigate(view, step) {
    var hash = "#/" + view + (step ? "/" + step : "");
    if (location.hash === hash) {
      render();
    } else {
      location.hash = hash;
    }
  }

  function setActiveView(view) {
    utils.qsa(".view").forEach(function (el) {
      el.classList.toggle("is-active", el.getAttribute("data-view") === view);
    });
    utils.qsa("[data-nav-link]").forEach(function (el) {
      el.classList.toggle("is-active", el.getAttribute("data-nav-link") === view);
    });
    var main = utils.qs(".app-main");
    if (main) main.scrollTop = 0;
    window.scrollTo(0, 0);
  }

  // Below 768px the stepper strip scrolls horizontally (css/layout.css
  // .stepper-nav) rather than wrapping, so it only shows part of the 8
  // steps at once. Without this, jumping straight to a late step (the
  // wizard-footer Continue button, or reopening a resumed application)
  // left the highlighted step scrolled completely off-screen with zero
  // visual indication of where the user actually was — confirmed with a
  // real 320px measurement (the active item sat 900+px past the visible
  // 286px-wide strip) before this fix. "nearest" only moves the strip
  // itself, and only as far as needed — it's a no-op once the step is
  // already visible. Called both on navigation (setActiveStep, below) and
  // on window resize (init(), below): resizing the *viewport* — a phone
  // rotating, a desktop window shrinking — never fires khanna:navigate, so
  // without the resize hook too, an already-active-but-now-off-screen step
  // stayed hidden until the user navigated again (found via a real resize
  // test before this second hook was added). (Phase 12)
  function scrollActiveStepIntoView() {
    var activeNavItem = utils.qs(".stepper-nav__item.is-active");
    if (activeNavItem && activeNavItem.scrollIntoView) {
      activeNavItem.scrollIntoView({ block: "nearest", inline: "nearest" });
    }
  }

  function setActiveStep(step) {
    if (!step) return;
    utils.qsa(".step-view").forEach(function (el) {
      var stepNum = parseInt(el.getAttribute("data-step"), 10);
      el.classList.toggle("is-active", stepNum === step);
    });
    utils.qsa(".stepper-nav__item").forEach(function (el) {
      var stepNum = parseInt(el.getAttribute("data-step"), 10);
      el.classList.toggle("is-active", stepNum === step);
    });
    scrollActiveStepIntoView();
  }

  // Set up once in init() (below) — re-measures the stepper's own real
  // scrollLeft/scrollWidth. Kept null-safe since it's only assigned once
  // .stepper-nav actually exists in the DOM (Phase 12).
  var updateStepperScrollFade = null;

  function render() {
    var parsed = parseHash();
    setActiveView(parsed.view);
    if (parsed.view === "new-application") {
      setActiveStep(parsed.step || 1);
      // .stepper-nav sits inside a .view that's `display:none` until
      // active, so its scrollWidth reads 0 (and the fade can't tell it's
      // scrollable) until the view is actually shown — re-measure on every
      // entry into the wizard, not just once at page load (Phase 12).
      if (updateStepperScrollFade) updateStepperScrollFade();
    }
    refreshWizardFooter();
    document.dispatchEvent(
      new CustomEvent("khanna:navigate", { detail: parsed })
    );
  }

  function init() {
    window.addEventListener("hashchange", render);

    var stepperNav = utils.qs(".stepper-nav");
    var stepperFadeWrap = utils.qs(".stepper-nav-scroll-fade");
    if (stepperNav && utils.enableScrollShadows) {
      updateStepperScrollFade = utils.enableScrollShadows(stepperNav, stepperFadeWrap);
    }
    // Re-anchor the active step (and not just the fade) after a real
    // viewport resize — see scrollActiveStepIntoView()'s own comment above
    // for why this is a separate hook from render()'s own call. Debounced:
    // a live window drag fires many resize events per second.
    window.addEventListener("resize", utils.debounce(scrollActiveStepIntoView, 150));

    // Any [data-nav-link] (header nav, mobile drawer, footer) navigates to a view.
    utils.on(document, "click", "[data-nav-link]", function (e, target) {
      e.preventDefault();
      navigate(target.getAttribute("data-nav-link"));
    });

    // Stepper tabs inside the New Application wizard.
    utils.on(document, "click", ".stepper-nav__item", function (e, target) {
      navigate("new-application", parseInt(target.getAttribute("data-step"), 10));
    });

    // Shared wizard-footer "Continue" button — advances one step. Disabled
    // state (and therefore whether a click can even fire) is governed by
    // refreshWizardFooter()/the step's own registered validator.
    utils.on(document, "click", "[data-wizard-continue]", function () {
      var parsed = parseHash();
      if (parsed.view !== "new-application") return;
      navigate("new-application", (parsed.step || 1) + 1);
    });

    // Every "+ New Application" trigger across the app uses the same handler:
    // logged-out users are redirected to Login first (and returned here
    // afterwards); logged-in users get a fresh draft Application record.
    utils.on(document, "click", "[data-action='new-application']", function (e) {
      e.preventDefault();
      if (global.KhannaAuth && !global.KhannaAuth.requireLogin("new-application", 1, "new")) {
        return; // sent to /auth; login success replays this same "new" action
      }
      if (global.KhannaState) {
        var user = global.KhannaAuth ? global.KhannaAuth.getCurrentUser() : null;
        global.KhannaState.createApplication(user ? user.email : "");
      }
      navigate("new-application", 1);
    });

    // Resuming an existing application from the Applications list — same
    // login gate, since it leads into the same protected wizard.
    utils.on(document, "click", "[data-action='open-application']", function (e, target) {
      e.preventDefault();
      var id = target.getAttribute("data-app-id");
      if (global.KhannaAuth && !global.KhannaAuth.requireLogin("new-application", 1, "open", id)) {
        return;
      }
      if (global.KhannaState && id) {
        global.KhannaState.setActiveApplicationId(id);
      }
      navigate("new-application", 1);
    });

    if (!location.hash) {
      location.hash = "#/" + DEFAULT_VIEW;
    } else {
      render();
    }
  }

  global.KhannaRouter = {
    init: init,
    navigate: navigate,
    parseHash: parseHash,
    registerStepValidator: registerStepValidator,
    refreshWizardFooter: refreshWizardFooter,
  };
})(window);
