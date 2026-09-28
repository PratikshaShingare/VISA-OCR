/* ==========================================================================
   Khanna Travels & Holidays — Toast / snackbar notifications
   A small, generic, reusable notification component — there was previously
   no toast/snackbar anywhere in this codebase (only inline notice-class
   banners scoped to one form at a time), so the first caller that needed a
   transient confirmation ("Passport details saved") needed this built from
   scratch. Kept deliberately minimal and dependency-free so any other page
   can reuse it the same way: global.KhannaToast.show("message").
   ========================================================================== */
(function (global) {
  "use strict";

  var ROOT_ID = "khanna-toast-root";
  var DEFAULT_DURATION = 3200;

  function ensureRoot() {
    var root = document.getElementById(ROOT_ID);
    if (!root) {
      root = document.createElement("div");
      root.id = ROOT_ID;
      root.className = "toast-root";
      root.setAttribute("aria-live", "polite");
      root.setAttribute("aria-atomic", "true");
      document.body.appendChild(root);
    }
    return root;
  }

  /**
   * @param {string} message
   * @param {Object} [opts]
   *   type: "success" | "error" | "info" (default "success")
   *   duration: ms before auto-dismiss (default 3200)
   */
  function show(message, opts) {
    if (!message) return;
    opts = opts || {};
    var root = ensureRoot();
    var type = opts.type || "success";
    var duration = typeof opts.duration === "number" ? opts.duration : DEFAULT_DURATION;

    var toast = document.createElement("div");
    toast.className = "toast toast-" + type;
    toast.setAttribute("role", "status");
    toast.textContent = message;
    root.appendChild(toast);

    // Force a layout flush before adding the "visible" class so the CSS
    // transition actually runs instead of the toast just appearing already
    // in its end state.
    void toast.offsetWidth;
    toast.classList.add("is-visible");

    var dismissed = false;
    function dismiss() {
      if (dismissed) return;
      dismissed = true;
      toast.classList.remove("is-visible");
      var removed = false;
      function remove() {
        if (removed) return;
        removed = true;
        if (toast.parentNode) toast.parentNode.removeChild(toast);
      }
      toast.addEventListener("transitionend", remove);
      // Fallback in case transitionend never fires (e.g. prefers-reduced-motion).
      setTimeout(remove, 400);
    }

    toast.addEventListener("click", dismiss);
    setTimeout(dismiss, duration);
  }

  global.KhannaToast = { show: show };
})(window);
