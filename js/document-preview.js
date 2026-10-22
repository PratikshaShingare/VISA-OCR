/* ==========================================================================
   Khanna Travels & Holidays — Document preview-only mode
   Opened from the Dashboard's "View" (eye) icon via "#/<doc-view>/preview"
   (router.js). The document page is shown with ONLY its generated-document
   preview: the form / field inputs are hidden (css/document-preview.css),
   and the preview is produced the same way a normal "Generate & Preview"
   click produces it — this module simply presses that page's own generate
   button for the active application, so the PDF is the real backend
   output built from the saved application data (nothing is imitated or
   cached here, and each controller's own readiness rules still apply).

   A slim bar above the preview names the document and applicant, and offers
   "Back to Dashboard" and "Edit details" (leaves preview mode and shows the
   normal full page for the same document).
   ========================================================================== */
(function (global) {
  "use strict";

  var utils = global.KhannaUtils;
  var MAX_ATTEMPTS = 25; // x100ms: waits for the controller to finish rendering its generate button

  var CONFIG = {
    "cover-letter": {
      label: "Cover Letter",
      triggers: function () {
        return ["[data-action='generate-cover-letter']"];
      },
    },
    "hotel-blocking": {
      label: "Hotel Blocking",
      triggers: function () {
        return ["[data-action='generate-voucher']"];
      },
    },
    "company-authorization": {
      label: "Company Authorization Letter",
      triggers: function () {
        return ["[data-action='generate-authorization'][data-group='company']"];
      },
    },
    "passport-authorization": {
      label: "Passport Authorization Letter",
      triggers: function () {
        return ["[data-action='generate-authorization'][data-group='passport']"];
      },
    },
    "invitation-letter": {
      label: "Invitation Letter",
      // Preview whatever this application actually generated on this page:
      // the main invitation letter and/or each inviter covering letter.
      triggers: function (app) {
        var sels = [];
        if (app.invitation && app.invitation.generatedAt) sels.push("[data-action='generate-invitation']");
        var per = (app.initorsLetters && app.initorsLetters.perPerson) || {};
        Object.keys(per).forEach(function (pid) {
          if (per[pid] && per[pid].generatedAt) {
            sels.push("[data-action='generate-initors'][data-person-id=\"" + pid + "\"]");
          }
        });
        return sels;
      },
    },
  };

  function sectionFor(view) {
    return utils.qs('.view[data-view="' + view + '"]');
  }

  // Same naming rule as the Dashboard list (applications.js).
  function applicantLabel(app) {
    return global.KhannaApplicationsList ? global.KhannaApplicationsList.applicantLabel(app) : "Untitled applicant";
  }

  // The bar is created once per document page and only shown in preview
  // mode (css/document-preview.css).
  function ensureBar(view) {
    var section = sectionFor(view);
    if (!section) return null;
    var bar = utils.qs("[data-doc-preview-bar]", section);
    if (!bar) {
      bar = document.createElement("div");
      bar.className = "card doc-preview-bar";
      bar.setAttribute("data-doc-preview-bar", "");
      bar.innerHTML =
        '<div class="doc-preview-bar__row">' +
        '<div class="doc-preview-bar__info">' +
        '<span class="field-hint">Preview</span> ' +
        '<strong data-pv-title></strong> ' +
        '<span class="field-hint" data-pv-who></span>' +
        '<div class="field-hint doc-preview-bar__id" data-pv-id></div>' +
        "</div>" +
        '<div class="doc-preview-bar__actions">' +
        '<button type="button" class="btn btn-secondary btn-sm" data-pv-back>Back to Dashboard</button>' +
        '<button type="button" class="btn btn-secondary btn-sm" data-pv-edit>Edit details</button>' +
        "</div>" +
        "</div>" +
        '<div class="notice notice-warning" data-pv-notice hidden role="alert">' +
        '<svg class="icon icon-sm" viewBox="0 0 24 24"><path d="M12 9v4M12 17h.01"/><circle cx="12" cy="12" r="9"/></svg>' +
        "<span data-pv-notice-text></span>" +
        "</div>";
      var container = utils.qs(".container", section);
      container.insertBefore(bar, container.firstChild);
      utils.on(bar, "click", "[data-pv-back]", function () {
        global.KhannaRouter.navigate("dashboard");
      });
      utils.on(bar, "click", "[data-pv-edit]", function () {
        global.KhannaRouter.navigate(view);
      });
    }
    return bar;
  }

  function setNotice(bar, text) {
    var box = utils.qs("[data-pv-notice]", bar);
    utils.qs("[data-pv-notice-text]", bar).textContent = text || "";
    box.hidden = !text;
  }

  var timer = null;
  var runId = 0;

  function run(view, attempt, id) {
    if (id !== runId) return; // superseded by a newer navigation
    var parsed = global.KhannaRouter.parseHash();
    if (parsed.mode !== "preview" || parsed.view !== view) return;

    var cfg = CONFIG[view];
    var bar = ensureBar(view);
    var app = global.KhannaState.getActiveApplication();
    utils.qs("[data-pv-title]", bar).textContent = cfg.label;
    utils.qs("[data-pv-who]", bar).textContent = app ? "· " + applicantLabel(app) : "";
    // The application number lives here (not in the Dashboard list).
    utils.qs("[data-pv-id]", bar).textContent = app ? "Application " + app.id : "";

    if (!app) {
      setNotice(bar, "No application is selected, so there is nothing to preview. Go back to the Dashboard and choose one.");
      return;
    }

    var section = sectionFor(view);
    var selectors = cfg.triggers(app);
    if (selectors.length === 0) {
      setNotice(bar, "No " + cfg.label + " has been generated for this application yet. Use Edit details to create it.");
      return;
    }
    var buttons = selectors
      .map(function (sel) {
        return utils.qs(sel, section);
      })
      .filter(Boolean);

    if (buttons.length === 0) {
      if (attempt < MAX_ATTEMPTS) {
        timer = setTimeout(function () { run(view, attempt + 1, id); }, 100);
        return;
      }
      setNotice(bar, "Nothing has been generated for this application on this page yet. Use Edit details to fill in the details and generate it.");
      return;
    }

    var blocked = buttons.filter(function (b) { return b.disabled; });
    if (blocked.length === buttons.length) {
      setNotice(
        bar,
        "There is nothing to preview yet: some required details are missing. Use Edit details to complete them."
      );
      return;
    }
    setNotice(bar, "");
    buttons.forEach(function (b) {
      if (!b.disabled) b.click();
    });
  }

  function onNavigate() {
    var parsed = global.KhannaRouter.parseHash();
    clearTimeout(timer);
    runId += 1;
    if (parsed.mode !== "preview" || !CONFIG[parsed.view]) return;
    var id = runId;
    // After the document controller's own khanna:navigate handler (it runs
    // first) has built the page, so its generate button exists.
    timer = setTimeout(function () { run(parsed.view, 0, id); }, 0);
  }

  // Remember which document page an application was last worked on, so the
  // Dashboard's View icon knows where to send an application that has no
  // generated document yet. Stamped when the application changes while one
  // of these pages is open; a no-op once it already matches (so it cannot
  // loop through the state subscription).
  function trackLastDocView() {
    var parsed = global.KhannaRouter.parseHash();
    if (!CONFIG[parsed.view] || parsed.mode === "preview") return;
    var app = global.KhannaState.getActiveApplication();
    if (!app || app.lastDocView === parsed.view) return;
    global.KhannaState.updateApplication(app.id, { lastDocView: parsed.view }, null);
  }

  function init() {
    global.KhannaState.subscribe(trackLastDocView);
    document.addEventListener("khanna:navigate", onNavigate);
    // Direct load / refresh on "#/<view>/preview": router.js's own first
    // render() fires before this listener exists on some load orders.
    if (global.KhannaRouter.parseHash().mode === "preview") onNavigate();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})(window);
