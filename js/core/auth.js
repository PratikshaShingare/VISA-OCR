/* ==========================================================================
   Khanna Travels & Holidays — Authentication state
   -----------------------------------------------------------------------
   IMPORTANT / HONEST LIMITATION: there is no backend server yet (it lands
   alongside Passport OCR in a later phase), so this checks credentials
   against a small local "staff directory" defined below and stores the
   resulting session in localStorage. This is a working login (it actually
   gates the UI, actually persists a session, actually restricts the Admin
   area) but it is NOT server-enforced security — anyone with browser dev
   tools could inspect this file or edit localStorage directly. Per the
   project's own Phase 39: "Admin authorization must eventually be enforced
   server-side." This module is the client-side half of that; the other
   half arrives once /backend/python/app.py exists.
   ========================================================================== */

(function (global) {
  "use strict";

  var utils = global.KhannaUtils;
  var storage = utils.storage;
  var SESSION_KEY = "khanna_session_v1";

  // Local demo staff directory — replace with a real backend call once
  // /backend/python/app.py exists. Passwords never get written to
  // localStorage; only the resulting {email, name, role} session does.
  var STAFF_DIRECTORY = [
    { email: "admin@khannatravels.com", password: "admin123", name: "Admin", role: "admin" },
    { email: "customercare@khannatravels.com", password: "khanna123", name: "Visa Team", role: "staff" },
  ];

  var currentUser = null; // { email, name, role } | null
  var redirectIntent = null; // { view, step } | null
  var subscribers = [];

  function notify() {
    subscribers.forEach(function (fn) {
      try {
        fn(currentUser);
      } catch (e) {
        console.error("KhannaAuth subscriber error:", e);
      }
    });
  }

  function init() {
    currentUser = storage.get(SESSION_KEY, null);
  }

  function login(email, password) {
    var normalizedEmail = String(email || "").trim().toLowerCase();
    var match = STAFF_DIRECTORY.find(function (u) {
      return u.email.toLowerCase() === normalizedEmail && u.password === password;
    });

    if (!match) {
      return { ok: false, error: "Invalid email or password." };
    }

    currentUser = { email: match.email, name: match.name, role: match.role };
    storage.set(SESSION_KEY, currentUser);
    notify();
    return { ok: true, user: currentUser };
  }

  function logout() {
    currentUser = null;
    storage.remove(SESSION_KEY);
    notify();
  }

  function getCurrentUser() {
    return currentUser;
  }

  function isLoggedIn() {
    return currentUser !== null;
  }

  function isAdmin() {
    return currentUser !== null && currentUser.role === "admin";
  }

  function subscribe(fn) {
    subscribers.push(fn);
    return function unsubscribe() {
      subscribers = subscribers.filter(function (f) {
        return f !== fn;
      });
    };
  }

  /**
   * Phase 11 — read-only accessor for the Admin dashboard's Staff Directory
   * card. Deliberately returns {email, name, role} only — never the
   * password field — and deliberately has no matching add/edit/remove
   * function: this directory is still the hardcoded array at the top of
   * this file (the same honest limitation documented there and on the
   * Login view since Phase 3), so a real CRUD UI here would silently not
   * persist anything and would be exactly the kind of decorative,
   * non-functional control project rule 9 rules out. Real user management
   * arrives once a real backend auth service exists (Phase 39).
   */
  function getStaffDirectory() {
    return STAFF_DIRECTORY.map(function (u) {
      return { email: u.email, name: u.name, role: u.role };
    });
  }

  /**
   * Gate an action behind login: if already logged in, returns true so the
   * caller can proceed immediately. Otherwise remembers where the user was
   * headed — and what to do once they're back (e.g. "create a new
   * Application" vs "open this existing one") — sends them to the login
   * view, and returns false. `action`/`actionArg` let the post-login
   * handler replay the exact intent instead of just landing on a view with
   * no application selected.
   */
  function requireLogin(intentView, intentStep, action, actionArg) {
    if (isLoggedIn()) return true;
    redirectIntent = {
      view: intentView || "dashboard",
      step: intentStep || null,
      action: action || null,
      actionArg: actionArg || null,
    };
    if (global.KhannaRouter) global.KhannaRouter.navigate("auth");
    return false;
  }

  function consumeRedirectIntent() {
    var intent = redirectIntent || { view: "dashboard", step: null, action: null, actionArg: null };
    redirectIntent = null;
    return intent;
  }

  global.KhannaAuth = {
    init: init,
    login: login,
    logout: logout,
    getCurrentUser: getCurrentUser,
    isLoggedIn: isLoggedIn,
    isAdmin: isAdmin,
    subscribe: subscribe,
    requireLogin: requireLogin,
    consumeRedirectIntent: consumeRedirectIntent,
    getStaffDirectory: getStaffDirectory,
  };

  // Load any persisted session immediately, same pattern as KhannaState, so
  // the very first render (profile menu, admin nav visibility) is correct
  // regardless of script order.
  init();
})(window);
