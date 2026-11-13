/* ==========================================================================
   Khanna Travels & Holidays — the workflow, shown to staff

   One list of the steps a visa file goes through, and the pages for each.
   Used in two places so they always agree:
     - the Dashboard's "How it works" guide (all steps, each with its pages);
     - a slim "Step N of 6" line under the title of every page that belongs
       to a step, with a link to the next step.

   It only shows where things are and links to them: it does not change how
   any page works, and nothing is required in this order — every page can
   still be opened on its own from the menu.
   ========================================================================== */
(function (global) {
  "use strict";

  var utils = global.KhannaUtils;
  var HIDE_KEY = "khanna.dashboardGuideHidden";

  var STEPS = [
    {
      title: "Passport",
      text: "Upload the passport; OCR reads it — check every field. This starts the application and the applicant's profile.",
      links: [{ view: "upload-passport", label: "Upload Passport" }],
      views: ["upload-passport", "passport-applications"],
    },
    {
      title: "Applicant details",
      text: "Send the client the Singapore / Japan details message and paste the reply. Saved once, used by every letter and form.",
      links: [{ view: "applicant-profiles", label: "Applicant Profiles" }],
      views: ["applicant-profiles"],
    },
    {
      title: "Hotel",
      text: "Upload the hotel voucher — the hotel and stay details are read from it.",
      links: [{ view: "hotel-blocking", label: "Hotel Blocking" }],
      views: ["hotel-blocking", "hotel-blockings"],
    },
    {
      title: "Letters",
      text: "The letters fill from the steps above. Generate, check the preview, download.",
      links: [
        { view: "cover-letter", label: "Cover Letter" },
        { view: "company-authorization", label: "Company Authorization" },
        { view: "passport-authorization", label: "Passport Authorization" },
        { view: "checklist-letter", label: "Checklist Letter" },
        { view: "invitation-letter", label: "Invitation Letter" },
      ],
      views: ["cover-letter", "cover-letters", "company-authorization", "passport-authorization", "checklist-letter", "invitation-letter"],
    },
    {
      title: "Visa form",
      text: "Fill the Japan or Singapore visa form from the profile, the hotel and the flight booking.",
      links: [{ view: "fill-forms", label: "Fill Forms" }],
      views: ["fill-forms"],
    },
    {
      title: "Final check",
      text: "Compare the filled forms with the passport before the file is submitted.",
      links: [{ view: "form-check", label: "Check Forms" }],
      views: ["form-check"],
    },
  ];

  function esc(v) {
    return utils.escapeHtml(v);
  }

  function stepIndexFor(view) {
    for (var i = 0; i < STEPS.length; i++) if (STEPS[i].views.indexOf(view) !== -1) return i;
    return -1;
  }

  function link(l, cls) {
    return '<a class="' + cls + '" href="#/' + l.view + '" data-nav-link="' + l.view + '">' + esc(l.label) + "</a>";
  }

  /* ---- Dashboard guide ---- */

  // The guide starts folded: the Dashboard shows only "Show how it works".
  // Opening it is remembered in this browser until "Hide" is pressed.
  var SHOW_KEY = "khanna.dashboardGuideShown";

  function isHidden() {
    try {
      return global.localStorage.getItem(SHOW_KEY) !== "1";
    } catch (e) {
      return true;
    }
  }

  function setHidden(hidden) {
    try {
      if (hidden) global.localStorage.removeItem(SHOW_KEY);
      else global.localStorage.setItem(SHOW_KEY, "1");
      global.localStorage.removeItem(HIDE_KEY); // the older "hidden" setting is no longer used
    } catch (e) {
      /* the guide simply starts folded next time */
    }
  }

  function dashboardHtml() {
    if (isHidden()) {
      return (
        '<div class="wf-guide wf-guide--hidden"><button type="button" class="btn btn-secondary btn-sm wf-show" data-wf-show aria-expanded="false">' +
        '<svg class="icon icon-sm" viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="9"/><path d="M9.5 9a2.5 2.5 0 1 1 3.5 2.3c-.6.3-1 .8-1 1.5V14M12 17h.01"/></svg>' +
        "Show how it works</button></div>"
      );
    }
    return (
      '<section class="wf-guide" aria-labelledby="wfGuideTitle">' +
      '<div class="wf-guide__head">' +
      '<div><h2 id="wfGuideTitle" class="wf-guide__title">How it works</h2>' +
      '<p class="wf-guide__sub">A visa file usually goes through these six steps. Each step is saved on the application, and every page can also be opened on its own.</p></div>' +
      '<button type="button" class="btn btn-ghost btn-sm" data-wf-hide>Hide</button>' +
      "</div>" +
      '<ol class="wf-steps">' +
      STEPS.map(function (s, i) {
        return (
          '<li class="wf-step">' +
          '<div class="wf-step__top"><span class="wf-step__no" aria-hidden="true">' + (i + 1) + "</span>" +
          '<h3 class="wf-step__title"><span class="sr-only">Step ' + (i + 1) + ": </span>" + esc(s.title) + "</h3></div>" +
          '<p class="wf-step__text">' + esc(s.text) + "</p>" +
          '<div class="wf-step__links">' + s.links.map(function (l) { return link(l, "wf-step__link"); }).join("") + "</div>" +
          "</li>"
        );
      }).join("") +
      "</ol></section>"
    );
  }

  function renderDashboard() {
    var box = utils.qs("[data-workflow-guide]");
    if (box) box.innerHTML = dashboardHtml();
  }

  /* ---- "Step N of 6" line on each page ---- */

  function stripHtml(view, index) {
    var step = STEPS[index];
    var next = STEPS[index + 1];
    return (
      '<nav class="wf-strip" aria-label="Where this page is in the workflow" data-wf-strip="' + view + '">' +
      '<span class="wf-strip__here">Step ' + (index + 1) + " of " + STEPS.length + ": <strong>" + esc(step.title) + "</strong></span>" +
      '<ol class="wf-strip__steps">' +
      STEPS.map(function (s, i) {
        var target = s.links[0];
        return (
          '<li class="wf-strip__step' + (i === index ? " is-current" : i < index ? " is-before" : "") + '">' +
          '<a href="#/' + target.view + '" data-nav-link="' + target.view + '"' + (i === index ? ' aria-current="step"' : "") + ">" +
          '<span class="wf-strip__no">' + (i + 1) + "</span>" + esc(s.title) + "</a></li>"
        );
      }).join("") +
      "</ol>" +
      (next ? '<a class="wf-strip__next" href="#/' + next.links[0].view + '" data-nav-link="' + next.links[0].view + '">Next: ' + esc(next.title) + " →</a>" : "") +
      "</nav>"
    );
  }

  function placeStrip(view) {
    var index = stepIndexFor(view);
    if (index === -1) return;
    var section = utils.qs('.view[data-view="' + view + '"]');
    if (!section || utils.qs("[data-wf-strip]", section)) return;
    var header = utils.qs(".view-header", section);
    if (!header) return;
    header.insertAdjacentHTML("afterend", stripHtml(view, index));
  }

  function init() {
    renderDashboard();
    document.addEventListener("click", function (e) {
      var hide = e.target.closest && e.target.closest("[data-wf-hide]");
      var show = e.target.closest && e.target.closest("[data-wf-show]");
      if (!hide && !show) return;
      setHidden(!!hide);
      renderDashboard();
      var focus = utils.qs(hide ? "[data-wf-show]" : "[data-wf-hide]");
      if (focus) focus.focus();
    });
    document.addEventListener("khanna:navigate", function (e) {
      var view = e.detail && e.detail.view;
      if (view === "dashboard") renderDashboard();
      if (view) placeStrip(view);
    });
    var m = location.hash.match(/^#\/([^/]+)/);
    if (m) placeStrip(m[1]);
  }

  global.KhannaWorkflowGuide = { STEPS: STEPS, stepIndexFor: stepIndexFor };

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})(window);
