/* ==========================================================================
   Khanna Travels & Holidays — Authentication-aware UI
   Wires KhannaAuth into the header profile menu, the Login and the merged
   Profile & Settings views, and Admin-only visibility. Every element that should only appear
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
    // The dark-mode switch keeps the menu open so the switch visibly flips.
    utils.on(document, "click", ".profile-menu__item:not(.profile-menu__theme)", closeProfileDropdown);
  }

  /* ---------------- Login form ---------------- */

  function initLoginForm() {
    utils.on(document, "submit", "[data-login-form]", function (e) {
      e.preventDefault();
      var form = this;
      var email = form.querySelector("#loginEmail").value;
      var password = form.querySelector("#loginPassword").value;
      var errorBox = form.querySelector("[data-login-error]");
      var errorText = form.querySelector("[data-login-error-text]");
      var submit = form.querySelector("[type='submit']");
      if (submit) submit.disabled = true;

      auth.login(email, password).then(function (result) {
        if (submit) submit.disabled = false;
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
    });
  }

  function initLogout() {
    utils.on(document, "click", "[data-action='logout']", function (e) {
      e.preventDefault();
      auth.logout();
      global.KhannaRouter.navigate("dashboard");
    });
  }

  /* ---------------- Profile & Settings (one page) ---------------- */

  function showMessage(selector, kind, text) {
    var box = utils.qs(selector);
    if (!box) return;
    if (!text) {
      box.innerHTML = "";
      return;
    }
    box.innerHTML =
      '<div class="notice notice-' + kind + '" role="status"><span>' + utils.escapeHtml(text) + "</span></div>";
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
    // Don't rebuild the form while the person is typing in it: a refresh
    // triggered by something else (e.g. the session check finishing) would
    // wipe an edit in progress.
    var existing = container.querySelector("[data-profile-name-input]");
    if (existing && document.activeElement === existing) return;

    container.innerHTML =
      '<form data-profile-form autocomplete="off">' +
      '<div class="account-name-row">' +
      '<div class="field"><label for="profileNameInput">Name</label>' +
      '<input id="profileNameInput" data-profile-name-input type="text" required maxlength="80" value="' +
      utils.escapeHtml(user.name) + '" /></div>' +
      '<button class="btn btn-primary btn-sm" type="submit">Save name</button>' +
      "</div></form>" +
      '<div data-profile-message></div>' +
      '<div class="account-fact"><span class="account-fact__label">Email (your login)</span><span>' +
      utils.escapeHtml(user.email) + "</span></div>" +
      '<div class="account-fact"><span class="account-fact__label">Role</span><span><span class="badge ' +
      (user.role === "admin" ? "badge-info" : "") + '">' + utils.escapeHtml(user.role) + "</span></span></div>";
  }

  function initProfileForms() {
    utils.on(document, "submit", "[data-profile-form]", function (e) {
      e.preventDefault();
      var input = this.querySelector("[data-profile-name-input]");
      var name = input.value.trim();
      if (!name) {
        showMessage("[data-profile-message]", "danger", "Enter your name.");
        return;
      }
      global.KhannaApi.updateMyName(name).then(
        function (body) {
          auth.setCurrentUserName((body && body.user && body.user.name) || name);
          showMessage("[data-profile-message]", "success", "Name saved.");
        },
        function (err) {
          showMessage("[data-profile-message]", "danger", (err && err.message) || "Could not save the name.");
        }
      );
    });

    utils.on(document, "submit", "[data-password-form]", function (e) {
      e.preventDefault();
      var form = this;
      var current = form.querySelector("#pwCurrent").value;
      var next = form.querySelector("#pwNew").value;
      var again = form.querySelector("#pwConfirm").value;
      if (next !== again) {
        showMessage("[data-password-message]", "danger", "The two new passwords do not match.");
        return;
      }
      if (next.length < 8) {
        showMessage("[data-password-message]", "danger", "The new password must be at least 8 characters.");
        return;
      }
      global.KhannaApi.changeMyPassword(current, next).then(
        function () {
          form.reset();
          showMessage("[data-password-message]", "success", "Password changed. Use it the next time you log in.");
        },
        function (err) {
          showMessage("[data-password-message]", "danger", (err && err.message) || "Could not change the password.");
        }
      );
    });
  }

  /* ---------------- Admin gate ---------------- */

  // Generalized from a single Admin-page pair to `qsa` (frontend rework,
  // section 3) so the same gate/denied pattern also covers the Applications
  // view, which is now admin-only too — both pairs toggle the same way, so
  // one function still serves both instead of a second copy of this logic
  // (project rule 15).
  function renderAdminGate() {
    var admin = auth.isAdmin();
    utils.qsa("[data-admin-gate]").forEach(function (el) {
      el.hidden = !admin;
    });
    utils.qsa("[data-admin-denied]").forEach(function (el) {
      el.hidden = admin;
    });
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
    "upload-documents",
    "fill-forms",
    "form-check",
    "applicant-profiles",
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
      if (e.detail.view === "admin" || e.detail.view === "applications") {
        renderAdminGate();
      }
    });
  }

  function init() {
    renderAuthState();
    auth.subscribe(renderAuthState);
    initProfileDropdown();
    initLoginForm();
    initProfileForms();
    initLogout();
    auth.verifySession();
    initRouteGuards();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})(window);
