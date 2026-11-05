/* ==========================================================================
   Khanna Travels & Holidays — Authentication state
   -----------------------------------------------------------------------
   Real login: credentials are checked by the backend (backend/python/
   auth_service.py — hashed passwords, server-side sessions). This module
   keeps the signed-in user and the session token in this browser
   (localStorage) so a refresh does not sign anyone out, and re-checks the
   token with the backend when the page opens. Only an admin can create or
   remove staff accounts: the backend enforces it, the UI merely hides the
   controls from everyone else.

   No password is ever stored in the browser — only {email, name, role,
   token}.
   ========================================================================== */

(function (global) {
  "use strict";

  var utils = global.KhannaUtils;
  var storage = utils.storage;
  var SESSION_KEY = "khanna_session_v1";

  var currentUser = null; // { email, name, role, token } | null
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
    if (currentUser && !currentUser.token) currentUser = null; // a session from before real logins
    if (!currentUser) storage.remove(SESSION_KEY);
  }

  // Asks the backend whether the saved session is still good (and refreshes
  // the name/role). Only a definite "no" signs the user out — a backend that
  // is simply not running right now leaves them where they are.
  function verifySession() {
    if (!currentUser || !global.KhannaApi) return Promise.resolve();
    return global.KhannaApi.getMe().then(
      function (body) {
        if (body && body.user && currentUser) {
          currentUser = Object.assign({}, currentUser, body.user);
          storage.set(SESSION_KEY, currentUser);
          notify();
        }
      },
      function () { /* 401 is handled by sessionEnded(); anything else: keep the session */ }
    );
  }

  // Returns a Promise of { ok: true, user } or { ok: false, error }.
  function login(email, password) {
    var api = global.KhannaApi;
    if (!api) return Promise.resolve({ ok: false, error: "The app is still loading — try again." });
    return api.login(String(email || "").trim(), password || "").then(
      function (body) {
        currentUser = { email: body.user.email, name: body.user.name, role: body.user.role, token: body.token };
        storage.set(SESSION_KEY, currentUser);
        notify();
        return { ok: true, user: currentUser };
      },
      function (err) {
        return { ok: false, error: (err && err.message) || "Could not log in." };
      }
    );
  }

  function clearSession() {
    currentUser = null;
    storage.remove(SESSION_KEY);
    notify();
  }

  function logout() {
    var api = global.KhannaApi;
    if (currentUser && api) api.logoutOnServer().catch(function () {});
    clearSession();
  }

  // The backend said this session is no longer valid.
  function sessionEnded() {
    if (!currentUser) return;
    clearSession();
    if (global.KhannaToast) global.KhannaToast.show("Your session has ended. Please log in again.", { type: "error" });
    if (global.KhannaRouter) global.KhannaRouter.navigate("auth");
  }

  function getToken() {
    return currentUser ? currentUser.token : null;
  }

  // Name changed on the Profile & Settings page.
  function setCurrentUserName(name) {
    if (!currentUser) return;
    currentUser = Object.assign({}, currentUser, { name: name });
    storage.set(SESSION_KEY, currentUser);
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
    getToken: getToken,
    verifySession: verifySession,
    sessionEnded: sessionEnded,
    setCurrentUserName: setCurrentUserName,
  };

  // Load any persisted session immediately, same pattern as KhannaState, so
  // the very first render (profile menu, admin nav visibility) is correct
  // regardless of script order.
  init();
})(window);
