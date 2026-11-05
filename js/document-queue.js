/* ==========================================================================
   Khanna Travels & Holidays — "Documents to create" queue
   Upload Passport -> "Save Applicant & Generate Required Documents" lets staff
   tick which documents this applicant needs. The ticked list is saved on the
   application (app.docQueue = { items: ["cover-letter", ...] }) and every
   document page in it then shows one thin strip under its title:

        Documents for Mr Sample Person   1 Cover Letter · 2 Hotel Blocking · 3 ...
                                                    [← Back]  [Next: Hotel Blocking →]

   Nothing is generated automatically — each page is the normal page with the
   applicant already on the application; the strip only keeps your place in
   the list. "Done" (last page) or ✕ removes the queue.

   Public API
       KhannaDocQueue.DOCUMENTS            [{ view, label, hint }]  (the six documents)
       KhannaDocQueue.start(appId, views)  saves the queue and opens the first page
       KhannaDocQueue.get(app)             -> views[] (empty when none)
       KhannaDocQueue.clear(appId)
   ========================================================================== */
(function (global) {
  "use strict";

  var utils = global.KhannaUtils;

  var DOCUMENTS = [
    { view: "cover-letter", label: "Cover Letter", hint: "Letter to the consulate" },
    { view: "hotel-blocking", label: "Hotel Blocking", hint: "Hotel booking voucher" },
    { view: "passport-authorization", label: "Passport Authorization Letter", hint: "Authorises submitting the passport" },
    { view: "company-authorization", label: "Company Authorization Letter", hint: "Authorises the company / sub-agent" },
    { view: "invitation-letter", label: "Invitation Letter", hint: "Invitation from the host" },
    { view: "checklist-letter", label: "Checklist Letter", hint: "Required documents list" },
  ];

  function labelOf(view) {
    var d = DOCUMENTS.filter(function (x) { return x.view === view; })[0];
    return d ? d.label : view;
  }

  function get(app) {
    var q = app && app.docQueue;
    var items = q && Array.isArray(q.items) ? q.items : [];
    return items.filter(function (v) { return DOCUMENTS.some(function (d) { return d.view === v; }); });
  }

  function start(appId, views) {
    var order = DOCUMENTS.map(function (d) { return d.view; });
    var items = order.filter(function (v) { return views.indexOf(v) !== -1; }); // always in the usual order
    if (!items.length) return false;
    global.KhannaState.updateApplication(appId, { docQueue: { items: items } }, "Documents to create chosen: " + items.map(labelOf).join(", "));
    if (global.KhannaRouter) global.KhannaRouter.navigate(items[0]);
    else location.hash = "#/" + items[0];
    return true;
  }

  function clear(appId) {
    global.KhannaState.updateApplication(appId, { docQueue: { items: [] } }, null);
  }

  function currentView() {
    return global.KhannaRouter ? global.KhannaRouter.parseHash().view : null;
  }

  function stripHtml(app, view) {
    var items = get(app);
    var idx = items.indexOf(view);
    if (idx === -1) return "";
    var who = global.KhannaApplicationsList ? global.KhannaApplicationsList.applicantLabel(app) : "this applicant";
    var steps = items.map(function (v, i) {
      var cls = i < idx ? "is-done" : i === idx ? "is-current" : "";
      return (
        '<li class="doc-queue__step ' + cls + '"' + (i === idx ? ' aria-current="step"' : "") + ">" +
        '<a href="#/' + v + '"><span class="doc-queue__num">' + (i < idx ? "&#10003;" : i + 1) + "</span>" + utils.escapeHtml(labelOf(v)) + "</a></li>"
      );
    }).join("");
    var prev = idx > 0 ? items[idx - 1] : null;
    var next = idx < items.length - 1 ? items[idx + 1] : null;
    return (
      '<div class="doc-queue" data-doc-queue role="region" aria-label="Documents to create">' +
      '<div class="doc-queue__head"><span class="doc-queue__title">Documents for <strong>' + utils.escapeHtml(who) + "</strong></span>" +
      '<button type="button" class="btn-icon doc-queue__close" data-doc-queue-clear aria-label="Stop this list" title="Stop this list">' +
      '<svg class="icon icon-sm" viewBox="0 0 24 24"><path d="M6 6l12 12M18 6 6 18"/></svg></button></div>' +
      '<ol class="doc-queue__steps">' + steps + "</ol>" +
      '<div class="doc-queue__nav">' +
      (prev ? '<a class="btn btn-secondary btn-sm" href="#/' + prev + '">&larr; Back</a>' : "") +
      (next
        ? '<a class="btn btn-primary btn-sm" href="#/' + next + '">Next: ' + utils.escapeHtml(labelOf(next)) + " &rarr;</a>"
        : '<button type="button" class="btn btn-primary btn-sm" data-doc-queue-done>Done</button>') +
      "</div></div>"
    );
  }

  function render() {
    var view = currentView();
    var section = view ? utils.qs('.view[data-view="' + view + '"]') : null;
    utils.qsa("[data-doc-queue-slot]").forEach(function (slot) {
      if (!section || !section.contains(slot)) slot.innerHTML = "";
    });
    if (!section) return;
    var container = utils.qs(":scope > .container", section);
    if (!container) return;
    var slot = utils.qs("[data-doc-queue-slot]", container);
    var app = global.KhannaState.getActiveApplication();
    var html = app ? stripHtml(app, view) : "";
    if (!slot) {
      if (!html) return;
      slot = document.createElement("div");
      slot.setAttribute("data-doc-queue-slot", "");
      var header = utils.qs(":scope > .view-header", container);
      container.insertBefore(slot, header ? header.nextSibling : container.firstChild);
    }
    if (slot.innerHTML !== html) slot.innerHTML = html;
  }

  document.addEventListener("click", function (e) {
    var clearBtn = e.target.closest && e.target.closest("[data-doc-queue-clear]");
    var doneBtn = e.target.closest && e.target.closest("[data-doc-queue-done]");
    if (!clearBtn && !doneBtn) return;
    var app = global.KhannaState.getActiveApplication();
    if (!app) return;
    clear(app.id);
    if (doneBtn) {
      if (global.KhannaToast) global.KhannaToast.show("All the documents you chose have been visited", { type: "success" });
      if (global.KhannaRouter) global.KhannaRouter.navigate("applications");
    }
  });

  document.addEventListener("khanna:navigate", render);
  window.addEventListener("hashchange", function () { setTimeout(render, 0); });
  document.addEventListener("DOMContentLoaded", function () {
    if (global.KhannaState && global.KhannaState.subscribe) global.KhannaState.subscribe(render);
    render();
  });

  global.KhannaDocQueue = { DOCUMENTS: DOCUMENTS, start: start, get: get, clear: clear, labelOf: labelOf, render: render };
})(window);
