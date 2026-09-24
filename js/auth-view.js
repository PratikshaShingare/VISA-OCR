/* ==========================================================================
   Khanna Travels & Holidays — Authentication-aware UI
   Wires KhannaAuth into the header profile menu, the Login/Profile/Settings
   views, and Admin-only visibility. Every element that should only appear
   for a signed-in (or admin) user is driven from here — nothing is shown
   decoratively.
   ========================================================================== */

(function (global) {
  "use strict";

  var utils = global.KhannaUtils;
  var auth = global.KhannaAuth;

  function initials(name) {
    var parts = String(name || "").trim().split(/\s+/).filter(Boolean);
    if (parts.length === 0) return "?";
    if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
    return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
  }

  /* ---------------- Header / mobile nav auth state ---------------- */

  function renderAuthState() {
    var loggedIn = auth.isLoggedIn();
    var user = auth.getCurrentUser();

    utils.qsa("[data-auth-logged-out]").forEach(function (el) {
      el.hidden = loggedIn;
    });
    utils.qsa("[data-auth-logged-in]").forEach(function (el) {
      el.hidden = !loggedIn;
    });

    if (loggedIn) {
      utils.qsa("[data-profile-avatar]").forEach(function (el) {
        el.textContent = initials(user.name);
      });
      utils.qsa("[data-profile-name]").forEach(function (el) {
        el.textContent = user.name;
      });
      utils.qsa("[data-profile-dropdown-name]").forEach(function (el) {
        el.textContent = user.name;
      });
      utils.qsa("[data-profile-dropdown-email]").forEach(function (el) {
        el.textContent = user.email;
      });
    }

    utils.qsa("[data-admin-only]").forEach(function (el) {
      el.hidden = !auth.isAdmin();
    });

    renderProfileView();
    renderSettingsView();
    renderAdminGate();
  }

  function closeProfileDropdown() {
    var dropdown = utils.qs("[data-profile-dropdown]");
    var trigger = utils.qs("[data-profile-toggle]");
    if (dropdown) dropdown.classList.remove("is-open");
    if (trigger) trigger.setAttribute("aria-expanded", "false");
  }

  function initProfileDropdown() {
    utils.on(document, "click", "[data-profile-toggle]", function (e, target) {
      e.stopPropagation();
      var dropdown = utils.qs("[data-profile-dropdown]");
      if (!dropdown) return;
      var willOpen = !dropdown.classList.contains("is-open");
      dropdown.classList.toggle("is-open", willOpen);
      target.setAttribute("aria-expanded", willOpen ? "true" : "false");
    });

    document.addEventListener("click", function (e) {
      var menu = utils.qs(".profile-menu");
      if (menu && !menu.contains(e.target)) closeProfileDropdown();
    });
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape") closeProfileDropdown();
    });
    utils.on(document, "click", ".profile-menu__item", closeProfileDropdown);
  }

  /* ---------------- Login form ---------------- */

  function initLoginForm() {
    utils.on(document, "submit", "[data-login-form]", function (e) {
      e.preventDefault();
      var form = this;
      var email = form.querySelector("#loginEmail").value;
      var password = form.querySelector("#loginPassword").value;
      var result = auth.login(email, password);
      var errorBox = form.querySelector("[data-login-error]");
      var errorText = form.querySelector("[data-login-error-text]");

      if (!result.ok) {
        errorText.textContent = result.error;
        errorBox.style.display = "flex";
        return;
      }

      errorBox.style.display = "none";
      form.reset();

      var intent = auth.consumeRedirectIntent();
      // Replay whatever the user was trying to do before being redirected
      // to log in, so they land back in the wizard with an actual
      // application selected instead of an empty step 1.
      if (intent.action === "new") {
        global.KhannaState.createApplication(result.user.email);
      } else if (intent.action === "open" && intent.actionArg) {
        global.KhannaState.setActiveApplicationId(intent.actionArg);
      }
      global.KhannaRouter.navigate(intent.view, intent.step);
    });
  }

  function initLogout() {
    utils.on(document, "click", "[data-action='logout']", function (e) {
      e.preventDefault();
      auth.logout();
      global.KhannaRouter.navigate("dashboard");
    });
  }

  /* ---------------- Profile / Settings views ---------------- */

  function accountSummaryHtml(user) {
    return (
      '<div class="field"><label>Name</label><div>' + utils.escapeHtml(user.name) + "</div></div>" +
      '<div class="field"><label>Email</label><div>' + utils.escapeHtml(user.email) + "</div></div>" +
      '<div class="field"><label>Role</label><div><span class="badge ' +
      (user.role === "admin" ? "badge-info" : "") +
      '">' + utils.escapeHtml(user.role) + "</span></div></div>"
    );
  }

  function renderProfileView() {
    var container = utils.qs("[data-profile-view-content]");
    if (!container) return;
    var user = auth.getCurrentUser();
    if (!user) {
      container.innerHTML =
        '<p style="margin:0;">You need to be logged in to view your profile.</p>' +
        '<a class="btn btn-primary btn-sm" href="#/auth" data-nav-link="auth" style="align-self:flex-start;">Log In</a>';
      return;
    }
    container.innerHTML = accountSummaryHtml(user);
  }

  function renderSettingsView() {
    var container = utils.qs("[data-settings-account]");
    if (!container) return;
    var user = auth.getCurrentUser();
    container.innerHTML = user
      ? accountSummaryHtml(user)
      : '<p style="margin:0;">Log in to see account settings.</p>';
  }

  /* ---------------- Admin gate ---------------- */

  function renderAdminGate() {
    var gate = utils.qs("[data-admin-gate]");
    var denied = utils.qs("[data-admin-denied]");
    if (!gate || !denied) return;
    var admin = auth.isAdmin();
    gate.hidden = !admin;
    denied.hidden = admin;
  }

  /* ---------------- Route guards ---------------- */

  // Views that require a logged-in user. "new-application" was the only
  // entry originally; the document-first redesign (Phase 1) adds the six
  // standalone document workspaces plus the passport-upload entry point,
  // since they all read/write the same protected Application data the
  // wizard already gates — same gating, same underlying data model.
  var PROTECTED_VIEWS = [
    "new-application",
    "cover-letter",
    "hotel-blocking",
    "company-authorization",
    "passport-authorization",
    "checklist-letter",
    "invitation-letter",
    "upload-passport",
  ];

  function initRouteGuards() {
    // Defense in depth: catches a direct hash edit / bookmark to a
    // protected view, not just a button click (router.js already gates the
    // "new-application"/"open-application" button clicks themselves before
    // an Application record is created; the standalone document views have
    // no such click gate, so this is their only guard).
    document.addEventListener("khanna:navigate", function (e) {
      if (PROTECTED_VIEWS.indexOf(e.detail.view) !== -1 && !auth.isLoggedIn()) {
        auth.requireLogin(e.detail.view, e.detail.step || 1);
        return;
      }
      if (e.detail.view === "admin") {
        renderAdminGate();
      }
    });
  }

  function init() {
    renderAuthState();
    auth.subscribe(renderAuthState);
    initProfileDropdown();
    initLoginForm();
    initLogout();
    initRouteGuards();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})(window);
