/* ==========================================================================
   Khanna Travels & Holidays — Cover Letter tab (wizard step 6, second half)
   Phase 9. Generates the three real, region-specific Khanna Travels &
   Holidays Tourist Visa Cover Letters (Europe / Japan / Singapore), each
   calling the real backend engine (backend/python/cover_letter_engine.py)
   to fill the actual, unmodified reference template (project rule 5) — not
   a recreation.

   Mounts inside the `[data-auth-tab-panel="cover"]` panel that
   authorization.js's mountSkeleton() builds (a single `<div
   data-cover-letter-root>` placeholder there) — this module owns
   everything inside that placeholder, the same way documents.js/hotels.js
   own their own step roots. Person data (applicant + every traveller,
   flattened to a person row) is reused from authorization.js's own
   `global.KhannaAuthorization` export rather than re-derived here (project
   rule 15).

   Traveller counts: no region limits how many people are on a letter. The
   applicant alone is written in the singular; one companion keeps the
   reference wording ("along with my wife, Name"); several companions each
   get their own relation (and Europe job / Japan occupation) card, and the
   backend (cover_letter_engine.py) names every one of them.

   Re-render discipline (same reasoning as authorization.js's own file
   header): the person checklist and Generate bar redraw freely on every
   KhannaState change. The rest of the per-region card — every text field,
   the Japan hotel-table editor, the Singapore per-person occupation list —
   only rebuilds on a real "entering this step" navigation, or immediately
   after an explicit action taken IN THIS PANEL that changes its own shape
   (switching region, selecting/deselecting a person, adding/removing a
   hotel row) — never from an unrelated background state change elsewhere
   in the app, so a staff member's in-progress typing is never silently
   overwritten. A click that lands on a checkbox or button always commits
   any pending text-field edit first (the browser fires that field's own
   "change"/blur event before the click's own handler runs), so rebuilding
   right after those explicit actions never loses unsaved input.
   ========================================================================== */
(function (global) {
  "use strict";

  var utils = global.KhannaUtils;
  var api = global.KhannaApi;

  var REGIONS = ["Europe", "Japan", "Singapore"];

  // Displayed labels only — per explicit instruction, the region picker no
  // longer names the destination country/region directly on its buttons.
  // The underlying values above (region selection, backend dispatch key,
  // and reference-template directory names in cover_letter_engine.py) are
  // completely unchanged; only what staff SEE on the button changes here.
  // Each existing region folder is in practice already the one real
  // template usable for every country in that group (e.g. "Europe" already
  // covers every Schengen destination with the same fixed wording) — there
  // is no separate per-country template to point to, so the "Countries"
  // list names the group each format is actually built for rather than
  // inventing additional countries no real template exists for.
  var REGION_FORMAT_LABELS = {
    Europe: "Format 1 (Countries — Schengen Europe)",
    Japan: "Format 2 (Countries — Japan)",
    Singapore: "Format 3 (Countries — Singapore)",
  };

  /* ---------------------------------------------------------------------
   * Editable preview (every region)
   *
   * A staff member can edit ANY text of the real preview page (Edit button,
   * js/document-viewer.js) — Europe's three free-composed body paragraphs as
   * one named block ("body"), and every other paragraph / table cell of all
   * three formats as a whole-document block ("blk-…", backend
   * document_blocks.py) — WITHOUT touching the letterhead, footer, margins
   * or fonts, which always come from the real reference template (project
   * rule 5). Edits are kept in app.coverLetter.editedFields.
   * ------------------------------------------------------------------- */

  function makeCoverEditor() {
    return global.KhannaPreviewEditor.createForDocument({
      getEditedFields: function () {
        var a = getApp();
        return a ? coverState(a).editedFields : null;
      },
      // Europe's auto-composed body, as it would be WITHOUT edits. The other
      // formats have no composed wording — their blocks come from the layout.
      composeFields: function () {
        var app = getApp();
        if (!app || coverState(app).region !== "Europe") return {};
        var payload = buildPayload(app, "docx");
        delete payload.editedBodyHtml;
        return api.composeCoverLetterBody(payload).then(function (res) {
          return { body: (res && res.html) || "<p></p>" };
        });
      },
      onFieldChange: function (key, html) {
        var a = getApp();
        if (!a) return;
        var patch = { coverLetter: { editedFields: {} } };
        patch.coverLetter.editedFields[key] = html; // null clears the override
        global.KhannaState.updateApplication(a.id, patch, null);
      },
      fieldLabel: function () { return "letter body"; },
    });
  }

  // The preview request for one cover letter, plus where its editable text
  // sits on the page.
  function loadCoverPreview(app) {
    return api.previewWithLayout(api.downloadCoverLetter, buildPayload(app, "pdf"));
  }

  // Document-first redesign (Phase 2): dual-mount. In the wizard this still
  // resolves to the sub-root authorization.js's own mountSkeleton() creates
  // inside its "Cover Letter" tab (unchanged — authorization.js still
  // drives render() for that case, see its own render()). On the
  // standalone Cover Letter page there is no authorization.js involved at
  // all, so this module gets its own root and its own navigate listener
  // below instead.
  function root() {
    var view = global.KhannaRouter ? global.KhannaRouter.parseHash().view : null;
    if (view === "cover-letter") return utils.qs("[data-cover-letter-page-root]");
    return utils.qs("[data-cover-letter-root]");
  }

  function getApp() {
    return global.KhannaState.getActiveApplication();
  }

  function authHelpers() {
    return global.KhannaAuthorization;
  }

  /* ---------------------------------------------------------------------
   * Person selection
   * ------------------------------------------------------------------- */

  function coverState(app) {
    return (app && app.coverLetter) || {};
  }

  // The people this letter can use: the application's own applicant and
  // travellers that actually have a name or a passport number on file (an
  // empty "Unnamed" placeholder row is never listed), plus any passports
  // added through "Use Existing Details -> Passport" from an earlier
  // application (stored on this letter as `importedPeople`, copied — the
  // source application is never modified).
  function importedRows(app) {
    return (coverState(app).importedPeople || []).map(function (p) {
      return {
        id: p.id,
        imported: true,
        isApplicant: false,
        relationLabel: p.relation || "Travelling companion",
        relation: p.relation || "",
        salutation: p.salutation || "",
        fullName: p.fullName || "",
        sex: p.sex || "",
        passportNumber: p.passportNumber || "",
        placeOfIssue: p.placeOfIssue || "",
        passportIssueDate: p.passportIssueDate || "",
        phone: p.phone || "",
        email: p.email || "",
        address: p.address || {},
      };
    });
  }

  function hasNameOrPassport(p) {
    return !!((p.fullName || "").trim() || (p.passportNumber || "").trim());
  }

  function peoplePool(app) {
    var auth = authHelpers();
    var own = auth ? auth.getSelectablePeople(app).filter(hasNameOrPassport) : [];
    var rows = own.concat(importedRows(app));
    var state = coverState(app);
    var ids = state.selectedPersonIds || [];
    // The first passport added from another application becomes the
    // applicant when nobody selected is the applicant yet; every later one
    // is a companion. Worked out here (not stored) so unticking the
    // applicant can never leave a letter without one.
    var hasApplicant =
      !!(state.manualApplicantName || "").trim() ||
      rows.some(function (p) { return p.isApplicant && ids.indexOf(p.id) !== -1; });
    if (!hasApplicant) {
      var first = rows.filter(function (p) { return p.imported && ids.indexOf(p.id) !== -1; })[0];
      if (first) {
        first.isApplicant = true;
        first.relationLabel = "Main applicant";
        first.relation = "";
      }
    }
    return rows;
  }

  function selectedPeople(app) {
    var ids = coverState(app).selectedPersonIds || [];
    return peoplePool(app).filter(function (p) {
      return ids.indexOf(p.id) !== -1;
    });
  }

  // No region limits how many people can be on a cover letter any more
  // (Europe and Japan used to stop at the applicant plus one companion).
  // Kept as a function so every place that checks a limit still reads the
  // same way — it simply never reports one.
  function maxPeopleFor() {
    return null;
  }

  /* ---------------------------------------------------------------------
   * Sentence case — "MUMBAI" -> "Mumbai". Mirrors
   * backend/python/letter_shared.sentence_case_value (which also applies it
   * to everything that reaches a letter): short all-capital words are kept
   * because they are almost always abbreviations (UAE, TCS).
   * ------------------------------------------------------------------- */

  var KNOWN_ACRONYMS = ["UAE", "USA", "UK", "US", "UN", "NCR", "NYC", "LLP", "PVT", "LTD", "IT", "HR", "CEO", "CFO"];
  var WORD_SEPARATORS = /([\s,\/()&\-]+)/;

  function sentenceCase(value, isPlace) {
    var text = String(value == null ? "" : value).trim().replace(/[ \t]{2,}/g, " ");
    return text
      .split(WORD_SEPARATORS)
      .map(function (part) {
        if (!part || WORD_SEPARATORS.test(part) || !/[A-Za-z]/.test(part)) return part;
        var isUpper = part === part.toUpperCase();
        var isLower = part === part.toLowerCase();
        if (isUpper && KNOWN_ACRONYMS.indexOf(part) !== -1) return part;
        if (isUpper) {
          var letters = part.replace(/[^A-Za-z]/g, "");
          if (part.indexOf(".") !== -1 || (!isPlace && letters.length <= 3)) return part;
          return part.charAt(0).toUpperCase() + part.slice(1).toLowerCase();
        }
        if (isPlace && isLower) return part.charAt(0).toUpperCase() + part.slice(1);
        return part;
      })
      .join("");
  }

  // Fields whose typed value is tidied to sentence case as soon as it is
  // entered: places in full, other details only lose long ALL-CAPITAL words.
  var PLACE_FIELDS = ["top:destinationCountry", "europe:cityOfResidence", "europe:countryOfResidence", "europe:nextCountry"];
  var DETAIL_FIELDS = [
    "europe:applicantJobTitle", "europe:applicantEmployerName", "europe:companionJobTitle", "europe:companionEmployerName",
    "japan:applicantEmployerOccupation", "japan:companionOccupation", "singapore:hotelName",
  ];

  /* ---------------------------------------------------------------------
   * How two travellers are related ("along with my wife")
   * ------------------------------------------------------------------- */

  var TRAVELLER_RELATIONS = [
    "Family member", "Husband", "Wife", "Father", "Mother", "Son", "Daughter",
    "Brother", "Sister", "Cousin", "Friend", "Colleague", "Business partner",
  ];

  // The Passport/Traveller record stores Spouse/Child/Parent/Sibling plus a
  // sex; the dropdown is gendered words, so a recorded relation pre-selects
  // the matching one.
  var RECORD_RELATIONS = {
    Spouse: { M: "Husband", F: "Wife" },
    Child: { M: "Son", F: "Daughter" },
    Parent: { M: "Father", F: "Mother" },
    Sibling: { M: "Brother", F: "Sister" },
    Friend: { "*": "Friend" },
    Colleague: { "*": "Colleague" },
  };

  // The one non-applicant person ticked on this letter (Europe/Japan).
  function companionOf(app) {
    return selectedPeople(app).filter(function (p) { return !p.isApplicant; })[0] || null;
  }

  function recordedRelationChoice(companion) {
    if (!companion || !companion.relation) return "";
    var by = RECORD_RELATIONS[companion.relation];
    if (!by) return "";
    return by["*"] || by[String(companion.sex || "").toUpperCase()] || "";
  }

  // What the dropdown shows: staff's own pick, else what the traveller
  // record says, else the generic "Family member".
  function relationChoiceFor(app) {
    return coverState(app).travellerRelation || recordedRelationChoice(companionOf(app)) || "Family member";
  }

  // "my wife" / the typed wording — mirrors letter_shared.traveller_relation.
  function relationPhrase(app) {
    var custom = (coverState(app).travellerRelationText || "").replace(/\s+/g, " ").trim().replace(/^[ ,.;]+|[ ,.;]+$/g, "");
    if (custom) return /^(my|our)\s/i.test(custom) ? custom : "my " + custom;
    return "my " + relationChoiceFor(app).toLowerCase();
  }

  // "my wife" -> "Wife" (how the Singapore passenger table prints a relation).
  function bareRelation(phrase) {
    var bare = String(phrase || "").replace(/^(my|our)\s+/i, "");
    return bare.charAt(0).toUpperCase() + bare.slice(1);
  }

  function relationPreviewText(app) {
    var companion = companionOf(app);
    if (!companion) return "";
    // Names print in capitals on a passport; the letter shows them in sentence case.
    // The letter names the companion by their full name, without a salutation.
    var name = sentenceCase(companion.fullName || "", true);
    if (coverState(app).region === "Singapore") {
      return "The letter will read: \u201Cfor me & " + relationPhrase(app) + "\u201D, and the passenger table lists " + (name || "them") + " as \u201C" + bareRelation(relationPhrase(app)) + "\u201D.";
    }
    return "The letter will read: \u201Calong with " + relationPhrase(app) + (name ? ", " + name : "") + "\u201D.";
  }

  function relationFieldsHtml(app, state) {
    var choice = relationChoiceFor(app);
    var options = TRAVELLER_RELATIONS.map(function (o) {
      return '<option value="' + o + '"' + (o === choice ? " selected" : "") + ">" + o + "</option>";
    }).join("");
    return (
      '<div class="field-grid">' +
      '<div class="field">' +
      '<label for="cover-top-travellerRelation">Relation between the travellers</label>' +
      '<select id="cover-top-travellerRelation" data-cover-field="top:travellerRelation">' + options + "</select>" +
      "</div>" +
      fieldRowHtml("top", "travellerRelationText", "Or write the relation in your own words (optional)", state.travellerRelationText, false, {
        placeholder: "e.g. business partner",
      }) +
      "</div>" +
      '<p class="field-hint cover-relation-hint" data-cover-relation-preview>' + utils.escapeHtml(relationPreviewText(app)) + "</p>"
    );
  }

  function refreshRelationPreview() {
    var app = getApp();
    var el = utils.qs("[data-cover-relation-preview]", root());
    if (app && el) el.textContent = relationPreviewText(app);
  }

  /* ---------------------------------------------------------------------
   * Several companions (Europe/Japan, three or more people on the letter)
   *
   * With ONE companion the letter keeps its original single set of fields
   * (the relation control above and the companion job/occupation fields).
   * With two or more, each companion gets their own small card: how they
   * are related to the applicant, and — Europe: job title, employer, year
   * employed since; Japan: occupation — all optional, because not everyone
   * travelling works (a child, a parent). Only what is entered is used in
   * the letter.
   * ------------------------------------------------------------------- */

  function companionsOf(app) {
    var auth = authHelpers();
    var chosen = selectedPeople(app).filter(function (p) { return !p.isApplicant; });
    return auth ? auth.orderPeopleForLetter(chosen) : chosen;
  }

  function companionDetail(app, personId) {
    return (coverState(app).companionDetails || {})[personId] || {};
  }

  function companionRelationChoice(app, person) {
    return companionDetail(app, person.id).relationChoice || recordedRelationChoice(person) || "Family member";
  }

  function companionRelationPhrase(app, person) {
    var custom = (companionDetail(app, person.id).relationText || "").replace(/\s+/g, " ").trim().replace(/^[ ,.;]+|[ ,.;]+$/g, "");
    if (custom) return /^(my|our)\s/i.test(custom) ? custom : "my " + custom;
    return "my " + companionRelationChoice(app, person).toLowerCase();
  }

  function companionPreviewText(app, person) {
    var name = sentenceCase(person.fullName || "", true);
    if (coverState(app).region === "Singapore") {
      return "The passenger table will list " + (name || "this person") + " as \u201C" + bareRelation(companionRelationPhrase(app, person)) + "\u201D.";
    }
    return "The letter will say: \u201C" + companionRelationPhrase(app, person) + (name ? ", " + name : "") + "\u201D.";
  }

  function companionInputHtml(person, key, label, value, placeholder) {
    var id = "cover-companion-" + person.id + "-" + key;
    return (
      '<div class="field">' +
      '<label for="' + utils.escapeHtml(id) + '">' + utils.escapeHtml(label) + "</label>" +
      '<input type="text" id="' + utils.escapeHtml(id) + '" data-cover-companion="' + utils.escapeHtml(person.id) + ":" + key + '"' +
      (placeholder ? ' placeholder="' + utils.escapeHtml(placeholder) + '"' : "") +
      ' value="' + utils.escapeHtml(value || "") + '" />' +
      "</div>"
    );
  }

  function companionDetailsHtml(app, region) {
    var auth = authHelpers();
    var companions = companionsOf(app);
    if (companions.length < 2 || !auth) return "";
    var cards = companions
      .map(function (p) {
        var d = companionDetail(app, p.id);
        var choice = companionRelationChoice(app, p);
        var options = TRAVELLER_RELATIONS.map(function (o) {
          return '<option value="' + o + '"' + (o === choice ? " selected" : "") + ">" + o + "</option>";
        }).join("");
        var selectId = "cover-companion-" + p.id + "-relationChoice";
        var fields =
          '<div class="field"><label for="' + utils.escapeHtml(selectId) + '">Relation to the applicant</label>' +
          '<select id="' + utils.escapeHtml(selectId) + '" data-cover-companion="' + utils.escapeHtml(p.id) + ':relationChoice">' + options + "</select></div>" +
          companionInputHtml(p, "relationText", "Or write it in your own words (optional)", d.relationText, "e.g. business partner");
        if (region === "Europe") {
          fields +=
            companionInputHtml(p, "jobTitle", "Job title (optional)", d.jobTitle) +
            companionInputHtml(p, "employerName", "Employer (optional)", d.employerName) +
            companionInputHtml(p, "employmentStartYear", "Employed since — year (optional)", d.employmentStartYear);
        } else if (region === "Japan") {
          fields += companionInputHtml(p, "occupation", "Occupation (optional)", d.occupation);
        }
        return (
          '<div class="cover-companion-card" data-cover-companion-card="' + utils.escapeHtml(p.id) + '">' +
          '<h4 class="cover-subheading">' + utils.escapeHtml(auth.personDisplayName(p)) + "</h4>" +
          '<div class="field-grid">' + fields + "</div>" +
          '<p class="field-hint" data-cover-companion-preview="' + utils.escapeHtml(p.id) + '">' + utils.escapeHtml(companionPreviewText(app, p)) + "</p>" +
          "</div>"
        );
      })
      .join("");
    return (
      '<h4 class="cover-subheading">Travelling companions</h4>' +
      '<p class="field-hint">' +
      (region === "Singapore"
        ? "Each companion's relation to the applicant is printed in the passenger table; the letter itself says \u201Cme & my family\u201D."
        : "Each companion is named in the letter with their own relation to the applicant. " +
          (region === "Europe"
        ? "Add job details only for companions who work — the letter mentions them only when entered."
        : "Add an occupation only for companions who have one — it is left out of their line otherwise.")) +
      "</p>" +
      '<div class="cover-companion-list">' + cards + "</div>"
    );
  }

  function refreshCompanionPreview(personId) {
    var app = getApp();
    var el = root() && root().querySelector('[data-cover-companion-preview="' + personId + '"]');
    var person = app && companionsOf(app).filter(function (p) { return p.id === personId; })[0];
    if (el && person) el.textContent = companionPreviewText(app, person);
  }

  /* ---------------------------------------------------------------------
   * Travel dates — never in the past, an end never before its start
   * ------------------------------------------------------------------- */

  var DATE_LABELS = {
    travelStartDate: "Travel start date",
    travelEndDate: "Travel end date",
    nextTravelStartDate: "Next country start date",
    nextTravelEndDate: "Next country end date",
  };

  function isoOnly(value) {
    return /^\d{4}-\d{2}-\d{2}$/.test(value || "") ? value : "";
  }

  function laterOf(a, b) {
    return a && b ? (a > b ? a : b) : a || b || "";
  }

  // Earliest date a given date field may take: today, or the start date of
  // the same trip leg when this is an end date.
  function dateMin(state, scope, key) {
    var today = utils.todayIso();
    if (scope === "top" && key === "travelEndDate") return laterOf(today, isoOnly(state.travelStartDate));
    if (scope === "europe" && key === "nextTravelEndDate") return laterOf(today, isoOnly((state.europe || {}).nextTravelStartDate));
    return today;
  }

  // What is wrong with ONE edited date, in plain words — null when fine.
  // `state` is the letter's current state; `value` the new value.
  function dateEditProblem(state, scope, key, value) {
    value = isoOnly(value);
    if (!value) return null; // cleared
    var label = DATE_LABELS[key] || "This date";
    if (value < utils.todayIso()) return label + " can't be in the past — choose today or a later date.";
    var min = dateMin(state, scope, key);
    if (value < min) {
      var startLabel = key === "nextTravelEndDate" ? "next country start date" : "travel start date";
      return label + " can't be before the " + startLabel + ".";
    }
    return null;
  }

  // Every date problem currently in the letter (used for readiness and to
  // explain a disabled Generate button) — includes values that were saved
  // before this rule existed, or came from a hotel blocking.
  function dateProblems(state) {
    var problems = [];
    var e = state.europe || {};
    [["top", "travelStartDate", state.travelStartDate], ["top", "travelEndDate", state.travelEndDate]].forEach(function (d) {
      var msg = dateEditProblem(state, d[0], d[1], d[2]);
      if (msg) problems.push(msg);
    });
    if (state.region === "Europe") {
      [["nextTravelStartDate", e.nextTravelStartDate], ["nextTravelEndDate", e.nextTravelEndDate]].forEach(function (d) {
        var msg = dateEditProblem(state, "europe", d[0], d[1]);
        if (msg) problems.push(msg);
      });
    }
    if (state.region === "Japan") {
      ((state.japan || {}).hotels || []).forEach(function (h, i) {
        var n = "Hotel " + (i + 1);
        if (isoOnly(h.checkIn) && h.checkIn < utils.todayIso()) problems.push(n + " check-in can't be in the past.");
        if (isoOnly(h.checkOut) && h.checkOut < laterOf(utils.todayIso(), isoOnly(h.checkIn))) problems.push(n + " check-out can't be in the past or before its check-in.");
      });
    }
    return problems;
  }

  /* ---------------------------------------------------------------------
   * Who pays for the trip — dropdown + payer name/relation
   * ------------------------------------------------------------------- */

  // How many people the letter is for: the manually typed applicant (if any)
  // plus everyone ticked in the list.
  function travellerCount(app) {
    var state = coverState(app);
    var manual = (state.manualApplicantName || "").trim();
    var selected = selectedPeople(app).filter(function (p) { return !(manual && p.isApplicant); });
    return selected.length + (manual ? 1 : 0);
  }

  function fundingOptions(multiple) {
    return [
      { value: "self", label: multiple ? "Individual" : "Self" },
      { value: "inviter", label: "Inviter" },
      { value: "company", label: "Company" },
      { value: "other", label: "Other" },
    ];
  }

  var FUNDING_PAYER_LABELS = {
    inviter: { name: "Inviter's name", relation: "Relation with the inviter" },
    company: { name: "Company name", relation: "Relation with the company" },
    other: { name: "Paying person's name", relation: "Relation with the paying person" },
  };

  var PERSON_PAYER_RELATIONS = ["Brother", "Sister", "Father", "Mother", "Son", "Daughter", "Spouse", "Uncle", "Aunt", "Cousin", "Friend", "Relative", "Other"];
  var COMPANY_PAYER_RELATIONS = ["Employer", "Own company", "Business partner", "Client", "Other"];

  function fundingRelationOptions(type) {
    return type === "company" ? COMPANY_PAYER_RELATIONS : PERSON_PAYER_RELATIONS;
  }

  // The relation as it reads in the letter, from the dropdown (and, for
  // "Other", the typed value).
  function fundingRelationFrom(state) {
    var choice = state.fundingRelationChoice || "";
    return choice === "Other" ? (state.fundingRelationCustom || "").trim() : choice;
  }

  // The one phrase the letter templates read after "will be borne by".
  // Self -> "myself" (one traveller) / "ourselves" (several, paying individually);
  // anyone else -> "Name (relation)". Empty until the dropdown is chosen and,
  // for a payer, a name is entered.
  function composeFunding(state, multiple) {
    var type = state.fundingType || "";
    if (!type) return "";
    if (type === "self") return multiple ? "ourselves" : "myself";
    var name = (state.fundingPayerName || "").trim();
    if (!name) return "";
    var relation = (state.fundingRelation || "").trim();
    return relation ? name + " (" + relation + ")" : name;
  }

  // Keeps `fundingArrangement` (what the letter and backend read) in step
  // with the three funding fields and the number of travellers. A letter
  // that predates the dropdown has only the old free-text value: it is kept
  // as an "Other" payer name so nothing typed earlier is lost.
  function syncFunding(app) {
    var state = coverState(app);
    var patch = {};
    var working = Object.assign({}, state);
    if (!state.fundingType && (state.fundingArrangement || "").trim()) {
      working.fundingType = patch.fundingType = "other";
      working.fundingPayerName = patch.fundingPayerName = state.fundingArrangement.trim();
    }
    // A letter saved before the relation dropdown has the relation as plain
    // text: a matching option is selected, anything else becomes "Other".
    if (!state.fundingRelationChoice && (state.fundingRelation || "").trim() && FUNDING_PAYER_LABELS[state.fundingType]) {
      var saved = state.fundingRelation.trim();
      var match = fundingRelationOptions(state.fundingType).filter(function (o) { return o.toLowerCase() === saved.toLowerCase(); })[0];
      working.fundingRelationChoice = patch.fundingRelationChoice = match || "Other";
      working.fundingRelationCustom = patch.fundingRelationCustom = match ? "" : saved;
      working.fundingRelation = patch.fundingRelation = match || saved;
    }
    var composed = composeFunding(working, travellerCount(app) > 1);
    if (composed !== (state.fundingArrangement || "") && (working.fundingType || state.fundingArrangement)) patch.fundingArrangement = composed;
    if (!Object.keys(patch).length) return app;
    global.KhannaState.updateApplication(app.id, { coverLetter: patch }, null);
    return getApp();
  }

  function fundingProblems(state) {
    var type = state.fundingType || "";
    if (!type) return [];
    if (type === "self") return [];
    var problems = [];
    var names = FUNDING_PAYER_LABELS[type];
    if (!(state.fundingPayerName || "").trim()) problems.push("Enter the " + names.name.toLowerCase() + " for the travel expenses.");
    if (!(state.fundingRelation || "").trim()) {
      problems.push(
        state.fundingRelationChoice === "Other"
          ? "Specify the " + names.relation.toLowerCase() + "."
          : "Choose the " + names.relation.toLowerCase() + "."
      );
    }
    return problems;
  }

  /* ---------------------------------------------------------------------
   * Readiness — mirrors authorization.js's passportReadiness/companyReadiness
   * ------------------------------------------------------------------- */

  // Singapore's single-traveller letter has a sentence "I am currently ..."
  // that needs the applicant's occupation; the multi-traveller letter only
  // prints an optional occupation column.
  function singaporePeople(app) {
    var state = coverState(app);
    var manual = (state.manualApplicantName || "").trim();
    var list = [];
    if (manual) list.push({ id: "manual-applicant", name: manual, isApplicant: true });
    selectedPeople(app).forEach(function (p) {
      if (manual && p.isApplicant) return;
      list.push({ id: p.id, name: authHelpers().personDisplayName(p), isApplicant: !!p.isApplicant });
    });
    return list;
  }

  function singaporeProblems(app) {
    var people = singaporePeople(app);
    if (people.length !== 1) return [];
    var occupations = (coverState(app).singapore || {}).occupations || {};
    return (occupations[people[0].id] || "").trim() ? [] : ["Enter the applicant's occupation."];
  }

  function isReady(app) {
    var auth = authHelpers();
    if (!app || !auth) return false;
    var state = coverState(app);
    var region = state.region;
    if (!region) return false;

    var selected = selectedPeople(app);
    var manualName = (state.manualApplicantName || "").trim();
    // A manually typed applicant name (for generating a cover letter
    // without using this application's saved passport/hotel details — see
    // the field above the checklist) fills the applicant's own slot in
    // place of a checked-off, core-fields-complete applicant row. Every
    // OTHER selected person (real travellers/companions) still has to have
    // a name and passport number on file exactly as before — this never
    // relaxes that for anyone but the applicant.
    var applicantSelected = manualName || selected.some(function (p) {
      return p.isApplicant;
    });
    var companionsToCheck = manualName ? selected.filter(function (p) { return !p.isApplicant; }) : selected;
    if (!applicantSelected || !companionsToCheck.every(auth.personHasCoreFields)) return false;
    var effectiveCount = (manualName ? 1 : 0) + companionsToCheck.length;

    // Singapore's letters are addressed to its Consulate General by the
    // template itself, so there is no consulate to fill in for it.
    var commonOk =
      (region === "Singapore" || !!(state.recipientText && state.recipientText.trim())) &&
      !!state.travelStartDate &&
      !!state.travelEndDate &&
      !!state.fundingType &&
      !!(state.fundingArrangement && state.fundingArrangement.trim()) &&
      fundingProblems(state).length === 0 &&
      dateProblems(state).length === 0;
    if (region !== "Singapore") {
      commonOk = commonOk && !!(state.destinationCountry && state.destinationCountry.trim());
    }
    if (!commonOk) return false;

    if (region === "Europe") {
      // The applicant alone, or with companions. With exactly one companion
      // their job details are required (the reference wording names them);
      // with several, each companion's job details are optional (children,
      // parents ...) and only used when entered.
      if (effectiveCount < 1) return false;
      var e = state.europe || {};
      var europeKeys = ["cityOfResidence", "countryOfResidence", "numberOfNights", "applicantEmploymentStatus", "applicantJobTitle", "applicantEmployerName"];
      if (effectiveCount === 2) europeKeys = europeKeys.concat(["companionJobTitle", "companionEmployerName", "companionEmploymentStartYear"]);
      return europeKeys.every(function (key) {
        return !!(e[key] && String(e[key]).trim());
      });
    }

    if (region === "Japan") {
      // One companion: their occupation is required (the reference line
      // asks for it); with several it is optional per person.
      if (effectiveCount < 1) return false;
      var j = state.japan || {};
      return (
        !!(j.applicantEmployerOccupation && j.applicantEmployerOccupation.trim()) &&
        (effectiveCount !== 2 || !!(j.companionOccupation && j.companionOccupation.trim()))
      );
    }

    if (region === "Singapore") {
      if (effectiveCount < 1) return false;
      var s = state.singapore || {};
      return !!(s.hotelName && s.hotelName.trim()) && !!(s.hotelAddress && s.hotelAddress.trim()) && singaporeProblems(app).length === 0;
    }

    return false;
  }

  /* ---------------------------------------------------------------------
   * Rendering — region selector
   * ------------------------------------------------------------------- */

  function regionSelectorHtml(region) {
    return (
      '<div class="cover-region-select" role="radiogroup" aria-label="Cover letter format">' +
      REGIONS.map(function (r) {
        return (
          '<button type="button" class="cover-region-btn' +
          (region === r ? " is-active" : "") +
          '" data-cover-region="' +
          r +
          '" aria-pressed="' +
          (region === r ? "true" : "false") +
          '">' +
          utils.escapeHtml(REGION_FORMAT_LABELS[r] || r) +
          "</button>"
        );
      }).join("") +
      "</div>"
    );
  }

  /* ---------------------------------------------------------------------
   * Rendering — searchable country selector (frontend rework, sections
   * 6-9). Replaces the 3-button regionSelectorHtml() above as what staff
   * actually see/use (regionSelectorHtml() itself is left in place, unused,
   * rather than deleted — no other file references it, but removing a
   * working function outright when it isn't causing a problem isn't a
   * requirement of this rework either).
   *
   * Selecting a country here sets BOTH `country` (the specific destination,
   * e.g. "France") and `region` ("Europe"/"Japan"/"Singapore" — unchanged
   * dispatch key every other function in this file already keys off), plus
   * auto-populates the consulate name/address and destination-country
   * fields from js/data/cover-letter-countries.js's config (section 9).
   * ------------------------------------------------------------------- */

  function countryLib() {
    return global.KhannaCoverLetterCountries;
  }

  // Plain country names only — the old right-hand "Schengen Europe" / "Japan"
  // / "Singapore" tags were removed on request; the format that applies is
  // still shown once a country is chosen (see the hint under the field).
  function suggestedCoverCountry() {
    var lib = countryLib();
    var app = getApp();
    var dest = app && app.travel && app.travel.destination;
    var entry = lib && dest ? lib.byName(dest) : null;
    return entry ? entry.name : "";
  }

  function countryOptionHtml(name, i, chosen) {
    var selected = chosen && name === chosen;
    return (
      '<button type="button" class="country-combo__option' + (selected ? " is-selected" : "") + '" role="option" id="cover-country-opt-' + i +
      '" aria-selected="' + (selected ? "true" : "false") + '" data-cover-country-option="' + utils.escapeHtml(name) + '">' +
      "<span>" + utils.escapeHtml(name) + "</span></button>"
    );
  }

  function countryOptionsHtml(query) {
    var lib = countryLib();
    var matches = lib ? lib.search(query) : [];
    if (!matches.length) {
      return '<p class="field-hint country-combo__empty">No matching country.</p>';
    }
    var chosen = coverState(getApp()).country || "";
    var html = "";
    var i = 0;
    var suggested = (query || "").trim() ? "" : suggestedCoverCountry();
    if (suggested) {
      html += '<p class="country-combo__group">Suggested for this application</p>' + countryOptionHtml(suggested, i++, chosen);
      html += '<p class="country-combo__group">All countries</p>';
    }
    matches.forEach(function (c) {
      html += countryOptionHtml(c.name, i++, chosen);
    });
    return html;
  }

  function countrySelectorHtml(state) {
    var selectedCountry = state.country || "";
    var hint = selectedCountry
      ? "Using " + (REGION_FORMAT_LABELS[state.region] || state.region) + " for " + selectedCountry + "."
      : "";
    return (
      '<div class="cover-country-select" data-cover-country-select>' +
      '<div class="field">' +
      '<label for="cover-country-input">Destination country</label>' +
      '<div class="country-combo" data-country-combo>' +
      '<input type="text" id="cover-country-input" data-cover-country-search autocomplete="off" role="combobox" ' +
      'aria-expanded="false" aria-haspopup="listbox" placeholder="Type to search a country…" value="' +
      utils.escapeHtml(selectedCountry) +
      '" />' +
      '<div class="country-combo__list" role="listbox" data-cover-country-list hidden></div>' +
      "</div>" +
      "</div>" +
      (hint ? '<p class="field-hint">' + utils.escapeHtml(hint) + "</p>" : "") +
      "</div>"
    );
  }

  /* ---------------------------------------------------------------------
   * Rendering — person checklist (same shape as authorization.js's own)
   * ------------------------------------------------------------------- */

  function checklistHtml(app, region) {
    var auth = authHelpers();
    var people = auth ? peoplePool(app) : [];
    if (!people.length) {
      return '<p class="field-hint">No applicant added yet.</p>';
    }
    var state = coverState(app);
    var selectedIds = state.selectedPersonIds || [];
    var manualName = (state.manualApplicantName || "").trim();
    var maxCount = maxPeopleFor(region);
    // When a manual applicant name is in use it fills the applicant's own
    // slot instead of a checklist selection (see the "Applicant name" field
    // above this list and buildPayload()/isReady() below), so the applicant
    // row here is shown but locked unchecked — only companions/travellers
    // stay selectable, and the region's people cap is reduced by one slot
    // to account for the manual applicant already occupying it.
    // While a manual name is in use, the applicant is never itself in
    // selectedIds (see the manual-name change handler in mountSkeleton(),
    // which clears it), so selectedIds.length here already only counts real
    // companion/traveller selections — comparing it against a cap reduced
    // by one slot reproduces exactly the original single-cap comparison
    // below, just leaving room for the manual applicant's own slot.
    var effectiveMax = manualName && maxCount ? Math.max(0, maxCount - 1) : maxCount;
    return people
      .map(function (p) {
        if (manualName && p.isApplicant) {
          return (
            '<label class="auth-person-row is-disabled">' +
            '<input type="checkbox" disabled />' +
            '<span class="auth-person-row__name">' + utils.escapeHtml(auth.personDisplayName(p)) + "</span>" +
            '<span class="auth-person-row__meta">Using the manually entered applicant name below instead.</span>' +
            "</label>"
          );
        }
        var checked = selectedIds.indexOf(p.id) !== -1;
        var atMax = !!effectiveMax && !checked && selectedIds.length >= effectiveMax;
        var incomplete = !auth.personHasCoreFields(p);
        return (
          '<label class="auth-person-row' + (atMax ? " is-disabled" : "") + '">' +
          '<input type="checkbox" data-cover-person data-person-id="' + utils.escapeHtml(p.id) + '"' +
          (checked ? " checked" : "") +
          (atMax ? " disabled" : "") +
          " />" +
          '<span class="auth-person-row__name">' + utils.escapeHtml(auth.personDisplayName(p)) + "</span>" +
          '<span class="auth-person-row__meta">' +
          utils.escapeHtml(p.relationLabel) +
          (incomplete ? " · missing name or passport number" : "") +
          "</span>" +
          "</label>"
        );
      })
      .join("");
  }

  function refreshChecklist() {
    var app = getApp();
    var box = utils.qs("[data-cover-checklist]", root());
    if (!app || !box) return;
    box.innerHTML = checklistHtml(app, coverState(app).region);
  }

  /* ---------------------------------------------------------------------
   * Rendering — generate bar + readiness notice + error box
   * ------------------------------------------------------------------- */

  function generateBarHtml(ready, generatedAt) {
    return (
      '<div class="hotel-generate-bar">' +
      '<button class="btn btn-primary btn-sm" type="button" data-action="generate-cover-letter"' +
      (ready ? "" : " disabled") +
      ">Generate &amp; Preview</button>" +
      (generatedAt ? '<span class="hotel-generate-bar__meta">Last generated ' + utils.formatDate(generatedAt) + "</span>" : "") +
      "</div>"
    );
  }

  function refreshGenerateBar() {
    var app = getApp();
    var box = utils.qs("[data-cover-generate-bar]", root());
    if (!app || !box) return;
    var state = coverState(app);
    box.innerHTML = generateBarHtml(isReady(app), state.generatedAt);
  }

  function readinessMessage(region) {
    if (region) {
      return "Select the applicant (with a name and passport number on file), any travelling companions, and fill in every required field above to generate this letter.";
    }
    return "Choose a region to begin.";
  }

  function refreshReadinessNotice() {
    var app = getApp();
    var box = utils.qs("[data-cover-readiness]", root());
    if (!app || !box) return;
    var region = coverState(app).region;
    // Details the letter prints that are still empty (they would show as a dash).
    var emptyDetails = region
      ? global.KhannaAddTraveller.missingDetailsHtml("coverLetter", selectedPeople(app), "data-complete-cover")
      : "";
    if (!region || isReady(app)) {
      box.innerHTML = emptyDetails;
      return;
    }
    var reasons = peopleProblems(app, region);
    dateProblems(coverState(app)).forEach(function (m) { reasons.push(m); });
    if (region === "Singapore") singaporeProblems(app).forEach(function (m) { reasons.push(m); });
    var missing = missingRequiredFieldLabels();
    if (missing.length) reasons.push("Fill in: " + missing.join(", ") + ".");
    // Specific reasons when there are any; the generic sentence only as a fallback.
    var text = reasons.length ? reasons.join(" ") : readinessMessage(region);
    box.innerHTML =
      '<div class="notice notice-warning">' +
      '<svg class="icon icon-sm" viewBox="0 0 24 24"><path d="M12 9v4M12 17h.01"/><circle cx="12" cy="12" r="9"/></svg>' +
      "<span>" + utils.escapeHtml("Can't generate yet. " + text) + "</span>" +
      "</div>" + emptyDetails;
  }

  // Why the people checklist above is not yet acceptable, in plain words —
  // mirrors the people part of isReady() so the two never disagree.
  function peopleProblems(app, region) {
    var auth = authHelpers();
    if (!auth) return [];
    var state = coverState(app);
    var manualName = (state.manualApplicantName || "").trim();
    var selected = selectedPeople(app);
    var problems = [];
    var applicantSelected = manualName || selected.some(function (p) { return p.isApplicant; });
    if (!applicantSelected) {
      problems.push("Tick the main applicant in the people list above (or type an applicant name).");
    }
    selected.forEach(function (p) {
      if (manualName && p.isApplicant) return;
      if (!auth.personHasCoreFields(p)) {
        var missingBits = [];
        if (!(p.fullName && p.fullName.trim())) missingBits.push("a name");
        if (!(p.passportNumber && p.passportNumber.trim())) missingBits.push("a passport number");
        problems.push(auth.personDisplayName(p) + " is missing " + missingBits.join(" and ") + " on file.");
      }
    });
    var count = selected.filter(function (p) { return !(manualName && p.isApplicant); }).length + (manualName ? 1 : 0);
    if (count < 1 && applicantSelected) {
      problems.push("Tick at least the applicant in the people list above.");
    }
    return problems;
  }

  // Names of the required (*) fields that are still empty, read from the form
  // itself so the list always matches exactly what staff see on screen.
  function missingRequiredFieldLabels() {
    var r = root();
    if (!r) return [];
    return utils.qsa("[data-cover-field]", r)
      .filter(function (input) {
        return !String(input.value || "").trim();
      })
      .map(function (input) {
        var label = input.id ? utils.qs('label[for="' + input.id + '"]', r) : null;
        var text = label ? label.textContent.trim() : "";
        return /\*$/.test(text) ? text.replace(/\s*\*$/, "").replace(/\s*\(.*?\)\s*$/, "") : "";
      })
      .filter(Boolean);
  }

  function showError(message) {
    var box = utils.qs("[data-cover-error]", root());
    if (!box) return;
    box.innerHTML = message
      ? '<div class="notice notice-danger">' +
        '<svg class="icon icon-sm" viewBox="0 0 24 24"><path d="M12 9v4M12 17h.01"/><circle cx="12" cy="12" r="9"/></svg>' +
        "<span>" + utils.escapeHtml(message) + "</span>" +
        "</div>"
      : "";
  }

  /* ---------------------------------------------------------------------
   * Rendering — the per-region card (full rebuild; see file header for
   * when this is and isn't called)
   * ------------------------------------------------------------------- */

  function fieldRowHtml(scope, key, label, value, required, opts) {
    opts = opts || {};
    var id = "cover-" + scope.replace(":", "-") + "-" + key;
    return (
      '<div class="field">' +
      '<label for="' + id + '">' + utils.escapeHtml(label) + (required ? " *" : "") + "</label>" +
      '<input type="' + (opts.type || "text") + '" id="' + id + '" data-cover-field="' + scope + ":" + key + '"' +
      (opts.placeholder ? ' placeholder="' + utils.escapeHtml(opts.placeholder) + '"' : "") +
      (opts.min ? ' min="' + utils.escapeHtml(opts.min) + '"' : "") +
      ' value="' + utils.escapeHtml(value || "") + '" />' +
      "</div>"
    );
  }

  function isLegacyConsulate(state) {
    return !(state.consulateName || "").trim() && !!(state.recipientText || "").trim();
  }

  function consulateNameValue(state) {
    return isLegacyConsulate(state) ? state.recipientText : state.consulateName || "";
  }

  function consulateAddressValue(state) {
    return isLegacyConsulate(state) ? "" : global.KhannaConsulate.addressOrDefault(state.consulateAddress);
  }

  // "Travel expenses funded by": a dropdown, plus — for an inviter, a company
  // or anyone else — the payer's name and their relation to the traveller(s).
  function fundingFieldsHtml(app, state) {
    var multiple = travellerCount(app) > 1;
    var type = state.fundingType || "";
    var options =
      '<option value="">Select…</option>' +
      fundingOptions(multiple).map(function (o) {
        return '<option value="' + o.value + '"' + (type === o.value ? " selected" : "") + ">" + utils.escapeHtml(o.label) + "</option>";
      }).join("");
    var html =
      '<div class="field">' +
      '<label for="cover-top-fundingType">Travel expenses funded by *</label>' +
      '<select id="cover-top-fundingType" data-cover-field="top:fundingType">' + options + "</select>" +
      "</div>";
    if (type && type !== "self" && FUNDING_PAYER_LABELS[type]) {
      var l = FUNDING_PAYER_LABELS[type];
      var relChoice = state.fundingRelationChoice || "";
      html +=
        fieldRowHtml("top", "fundingPayerName", l.name, state.fundingPayerName, true) +
        '<div class="field">' +
        '<label for="cover-top-fundingRelationChoice">' + utils.escapeHtml(l.relation) + " *</label>" +
        '<select id="cover-top-fundingRelationChoice" data-cover-field="top:fundingRelationChoice">' +
        '<option value="">Select…</option>' +
        fundingRelationOptions(type).map(function (o) {
          return '<option value="' + o + '"' + (relChoice === o ? " selected" : "") + ">" + o + "</option>";
        }).join("") +
        "</select></div>";
      if (relChoice === "Other") {
        html += fieldRowHtml("top", "fundingRelationCustom", "Specify the relation", state.fundingRelationCustom, true, { placeholder: "e.g. Neighbour" });
      }
    }
    return html;
  }

  function commonFieldsHtml(app, state, region) {
    var rows =
      // The consulate follows the destination country chosen above: its
      // name is filled in automatically and its address (default Mumbai,
      // India) sits on the next line of the letter. Both stay editable.
      // A letter saved before this split only has the old single line —
      // that line is shown as the name with no address, untouched.
      // Singapore's templates carry the Consulate General's address
      // themselves, so neither box is shown for it.
      (region === "Singapore" ? "" : fieldRowHtml("top", "consulateName", "Consulate name", consulateNameValue(state), true, {
        placeholder: "e.g. The Consulate General of France",
      }) +
      fieldRowHtml("top", "consulateAddress", "Address of Consulate", consulateAddressValue(state), false, {
        placeholder: "e.g. Mumbai, India",
      })) +
      (region === "Singapore"
        ? ""
        : fieldRowHtml("top", "destinationCountry", "Destination country", state.destinationCountry, true)) +
      fieldRowHtml("top", "travelStartDate", "Travel start date", state.travelStartDate, true, { type: "date", min: dateMin(state, "top", "travelStartDate") }) +
      fieldRowHtml("top", "travelEndDate", "Travel end date", state.travelEndDate, true, { type: "date", min: dateMin(state, "top", "travelEndDate") }) +
      fundingFieldsHtml(app, state);
    return '<div class="field-grid">' + rows + "</div>";
  }

  // Frontend rework, section 10: this figure is required by every date the
  // template exists for, but not something the reference wording ever
  // spells out numerically anywhere else — computed straight from real
  // check-in/check-out dates rather than left for staff to work out and
  // retype (project rule 9 — don't leave a field manual when the real data
  // to compute it already exists on this application).
  function nightsBetween(checkIn, checkOut) {
    if (!checkIn || !checkOut) return "";
    var start = new Date(checkIn);
    var end = new Date(checkOut);
    if (isNaN(start.getTime()) || isNaN(end.getTime())) return "";
    var ms = end.getTime() - start.getTime();
    var nights = Math.round(ms / (1000 * 60 * 60 * 24));
    if (nights <= 0) return "";
    return nights + (nights === 1 ? " night" : " nights");
  }

  // Frontend rework, section 10 (and Phase E): "City"/"Country" are listed
  // as automatically-populated (from the applicant's own saved passport/
  // address details), not manually typed — but as two SEPARATE fields, each
  // independently auto-filled and independently editable, rather than one
  // combined text box. Only ever seeds an EMPTY field, and never when a
  // manually-typed applicant name is in use (there is no real
  // passport/address to source it from in that case) — never overwrites
  // something staff already typed or edited. The two are joined back into
  // the single combined "City, Country" string the reference template's
  // fixed wording (and cover_letter_engine.py's `cityCountryOfResidence`
  // field key) expects only at the point buildPayload() sends the request —
  // see that function below — so the backend/API contract is unchanged.
  function autoSeedEuropeResidence(app) {
    var state = coverState(app);
    if (state.region !== "Europe") return app;
    var manualName = (state.manualApplicantName || "").trim();
    if (manualName) return app;
    var e = state.europe || {};
    var selectedApplicant = selectedPeople(app).filter(function (p) { return p.isApplicant; })[0];
    var addr = (selectedApplicant && selectedApplicant.imported && selectedApplicant.address) ||
      (app.applicant && app.applicant.address) || {};
    var city = (addr.city || "").trim();
    var country = (addr.country || "").trim();
    var patch = {};
    if (!(e.cityOfResidence && e.cityOfResidence.trim()) && city) patch.cityOfResidence = sentenceCase(city, true);
    if (!(e.countryOfResidence && e.countryOfResidence.trim()) && country) patch.countryOfResidence = sentenceCase(country, true);
    if (!Object.keys(patch).length) return app;
    global.KhannaState.updateApplication(app.id, { coverLetter: { europe: patch } }, null);
    return getApp();
  }

  // Joins the two separate City/Country fields into the single "City,
  // Country" combined string the reference template's fixed wording (and
  // the backend's `cityCountryOfResidence` field key) expects — the one
  // place this combination happens, so isReady()/buildPayload() below never
  // duplicate the join logic.
  function europeCombinedResidence(e) {
    var city = (e && e.cityOfResidence || "").trim();
    var country = (e && e.countryOfResidence || "").trim();
    return [city, country].filter(Boolean).join(", ");
  }

  function europeFieldsHtml(state, withCompanion) {
    var e = state.europe || {};
    return (
      '<div class="field-grid">' +
      fieldRowHtml(
        "europe",
        "cityOfResidence",
        "City of residence (auto-filled from the applicant's address — edit if needed)",
        e.cityOfResidence,
        true,
        { placeholder: "e.g. Mumbai" }
      ) +
      fieldRowHtml(
        "europe",
        "countryOfResidence",
        "Country of residence (auto-filled from the applicant's address — edit if needed)",
        e.countryOfResidence,
        true,
        { placeholder: "e.g. India" }
      ) +
      fieldRowHtml("europe", "numberOfNights", "Number of nights (or pull it from Hotel Blocking below)", e.numberOfNights, true, {
        placeholder: "e.g. 10 nights",
      }) +
      fieldRowHtml("europe", "applicantEmploymentStatus", "Applicant employment status", e.applicantEmploymentStatus, true, {
        placeholder: "e.g. Salaried",
      }) +
      fieldRowHtml("europe", "applicantJobTitle", "Applicant job title", e.applicantJobTitle, true) +
      fieldRowHtml("europe", "applicantEmployerName", "Applicant employer", e.applicantEmployerName, true) +
      (withCompanion
        ? fieldRowHtml("europe", "companionJobTitle", "Companion job title", e.companionJobTitle, true) +
          fieldRowHtml("europe", "companionEmployerName", "Companion employer", e.companionEmployerName, true) +
          fieldRowHtml("europe", "companionEmploymentStartYear", "Companion employed since (year)", e.companionEmploymentStartYear, true)
        : "") +
      "</div>" +
      "<p class=\"field-hint\">Optional — only if the trip continues to a second country.</p>" +
      '<div class="field-grid">' +
      fieldRowHtml("europe", "nextCountry", "Next country (optional)", e.nextCountry, false) +
      fieldRowHtml("europe", "nextTravelStartDate", "Next country — start date", e.nextTravelStartDate, false, { type: "date", min: dateMin(state, "europe", "nextTravelStartDate") }) +
      fieldRowHtml("europe", "nextTravelEndDate", "Next country — end date", e.nextTravelEndDate, false, { type: "date", min: dateMin(state, "europe", "nextTravelEndDate") }) +
      fieldRowHtml("europe", "nextNumberOfNights", "Next country — number of nights", e.nextNumberOfNights, false) +
      "</div>"
    );
  }

  function japanHotelRowHtml(hotel) {
    return (
      '<div class="cover-hotel-row" data-hotel-id="' + utils.escapeHtml(hotel.id) + '">' +
      '<div class="field-grid">' +
      '<div class="field"><label>Hotel name</label><input type="text" data-cover-hotel-field="name" value="' +
      utils.escapeHtml(hotel.name || "") +
      '" /></div>' +
      '<div class="field"><label>Check-in</label><input type="date" data-cover-hotel-field="checkIn" min="' + utils.todayIso() + '" value="' +
      utils.escapeHtml(hotel.checkIn || "") +
      '" /></div>' +
      '<div class="field"><label>Check-out</label><input type="date" data-cover-hotel-field="checkOut" min="' + laterOf(utils.todayIso(), isoOnly(hotel.checkIn)) + '" value="' +
      utils.escapeHtml(hotel.checkOut || "") +
      '" /></div>' +
      '<div class="field"><label>Contact no.</label><input type="text" data-cover-hotel-field="contactNo" value="' +
      utils.escapeHtml(hotel.contactNo || "") +
      '" /></div>' +
      "</div>" +
      '<button type="button" class="btn btn-ghost btn-sm cover-hotel-row__remove" data-action="remove-cover-hotel" data-hotel-id="' +
      utils.escapeHtml(hotel.id) +
      '">Remove hotel</button>' +
      "</div>"
    );
  }

  function japanFieldsHtml(state, withCompanion) {
    var j = state.japan || {};
    var hotels = j.hotels || [];
    return (
      '<div class="field-grid">' +
      fieldRowHtml("japan", "applicantEmployerOccupation", "Applicant employer / occupation", j.applicantEmployerOccupation, true, {
        placeholder: "e.g. Software Engineer at Acme Corp",
      }) +
      (withCompanion ? fieldRowHtml("japan", "companionOccupation", "Companion occupation", j.companionOccupation, true) : "") +
      "</div>" +
      '<h4 class="cover-subheading">Hotels in Japan (optional)</h4>' +
      '<div class="cover-hotel-list">' +
      (hotels.length ? hotels.map(japanHotelRowHtml).join("") : '<p class="field-hint">No hotels added yet.</p>') +
      "</div>" +
      '<button type="button" class="btn btn-secondary btn-sm" data-action="add-cover-hotel">+ Add hotel</button>'
    );
  }

  function singaporeFieldsHtml(app, state) {
    var s = state.singapore || {};
    var occupations = s.occupations || {};
    var people = singaporePeople(app);
    var single = people.length === 1;
    var occupationRows = people.length
      ? people
          .map(function (p) {
            var label = single
              ? "Occupation *"
              : utils.escapeHtml(p.name) + " — occupation (optional)";
            var id = "cover-occupation-" + p.id;
            return (
              '<div class="field">' +
              '<label for="' + utils.escapeHtml(id) + '">' + (single ? label : label) + "</label>" +
              '<input type="text" id="' + utils.escapeHtml(id) + '" data-cover-occupation="' + utils.escapeHtml(p.id) + '" placeholder="' +
              (single ? "e.g. a student at XYZ College" : "e.g. Employed, Homemaker, Student") + '" value="' +
              utils.escapeHtml(occupations[p.id] || "") +
              '" /></div>'
            );
          })
          .join("")
      : '<p class="field-hint">Select at least the applicant above to enter occupations.</p>';
    return (
      '<h4 class="cover-subheading">Singapore letter details</h4>' +
      '<p class="field-hint" style="margin-bottom:var(--space-3);">' +
      (single
        ? "Single-traveller letter: addressed to the Consulate General of the Republic of Singapore, Mumbai (already in the template); no passenger table."
        : "Two-or-multiple-traveller letter: addressed to the Consulate General of the Republic of Singapore, Mumbai (already in the template); every traveller is listed in the passenger table.") +
      "</p>" +
      '<div class="field-grid">' +
      fieldRowHtml("singapore", "hotelName", "Hotel name", s.hotelName, true) +
      fieldRowHtml("singapore", "hotelAddress", "Hotel address", s.hotelAddress, true) +
      "</div>" +
      '<h4 class="cover-subheading">' + (single ? "Occupation" : "Occupations (shown in the passenger table)") + "</h4>" +
      (single ? '<p class="field-hint" style="margin-bottom:var(--space-3);">Completes the sentence \u201CI am currently \u2026\u201D.</p>' : "") +
      '<div class="field-grid">' + occupationRows + "</div>"
    );
  }

  // "Use Existing Details ▾" (replaces the removed "Use Existing
  // Applicant"/"Use existing application" buttons for this page — see
  // document-workspace.js's VIEW_BUTTON_CONFIG). Unlike those, which pulled
  // in a DIFFERENT application/profile entirely, this pulls the CURRENT
  // application's own already-saved Passport and/or Hotel Blocking details
  // into this cover letter — "Hotels Details and the name will be added
  // from either passport or hotel blocking or from both" (explicit
  // instruction). Reuses the same .profile-menu__dropdown/__item styling
  // as the header's own "New Application" menu (app.js) rather than
  // inventing a second dropdown look.
  function useExistingDetailsHtml() {
    var existing =
      '<div class="cover-use-existing" data-cover-use-existing>' +
      '<button type="button" class="btn btn-secondary btn-sm" data-cover-use-existing-toggle aria-haspopup="true" aria-expanded="false">' +
      "Use Existing Details " +
      '<span aria-hidden="true">&#9662;</span>' +
      "</button>" +
      // Opens as two small boxes side by side: the kind of detail on the
      // left, and — once one is chosen — a short scrollable list of the
      // saved passports / hotel blockings to pick from on the right.
      '<div class="cover-existing-panel" data-cover-use-existing-dropdown>' +
      '<div class="cover-existing-menu" role="menu">' +
      '<button type="button" class="cover-existing-menu__item" role="menuitem" data-cover-use-existing-option="passport">Passport <span aria-hidden="true">&#9656;</span></button>' +
      '<button type="button" class="cover-existing-menu__item" role="menuitem" data-cover-use-existing-option="hotel-blocking">Hotel Blocking <span aria-hidden="true">&#9656;</span></button>' +
      "</div>" +
      '<div class="cover-existing-list" data-cover-existing-list hidden></div>' +
      "</div>" +
      "</div>";
    return (
      global.KhannaAddTraveller.sourceChoiceHtml(existing, "coverLetter") +
      '<div class="cover-existing-status" data-cover-existing-status role="status" aria-live="polite" hidden></div>'
    );
  }

  /* ---------------------------------------------------------------------
   * "Use Existing Details" — sources and actions
   * ------------------------------------------------------------------- */

  // The saved-passport / saved-hotel-blocking lists are shared with the
  // Invitation Letter page's own "Use Existing Details" — see
  // js/saved-details.js (project rule 15: one copy of that logic).
  function savedDetails() {
    return global.KhannaSavedDetails;
  }

  function appLabel(app) {
    return savedDetails().appLabel(app);
  }

  function passportSources() {
    return savedDetails().passportSources();
  }

  function hotelDateSpan(hotels) {
    return savedDetails().hotelDateSpan(hotels);
  }

  function existingListHtml(kind) {
    return savedDetails().listHtml(kind, "data-cover-existing-pick");
  }

  function authLib() {
    return authHelpers();
  }

  function setExistingStatus(message, isWarning) {
    var box = utils.qs("[data-cover-existing-status]", root());
    if (!box) return;
    box.hidden = !message;
    box.classList.toggle("is-warning", !!isWarning);
    box.textContent = message || "";
  }

  // Adds a saved passport to this letter. Passports that belong to another
  // application are copied into this letter (never moved); a passport that
  // is already one of this application's own people is simply selected.
  function usePassportFromSource(key) {
    var app = getApp();
    if (!app) return;
    var src = passportSources().filter(function (s) { return s.key === key; })[0];
    if (!src) return;
    var state = coverState(app);
    var ids = (state.selectedPersonIds || []).slice();
    var imported = (state.importedPeople || []).slice();

    var existing = peoplePool(app).filter(function (p) {
      if (src.row.passportNumber) return (p.passportNumber || "").trim().toUpperCase() === key;
      return !(p.passportNumber || "").trim() && (p.fullName || "").trim().toLowerCase() === src.row.fullName.toLowerCase();
    })[0];
    if (existing && ids.indexOf(existing.id) !== -1) {
      renderCard();
      setExistingStatus(authLib().personDisplayName(existing) + " is already on this letter.", true);
      return;
    }

    // A passport chosen here takes the place of a typed-in applicant name.
    var hadManualName = !!(state.manualApplicantName || "").trim();
    var maxCount = maxPeopleFor(state.region);
    if (maxCount && ids.length >= maxCount) {
      renderCard();
      setExistingStatus("This letter format takes only " + maxCount + " people. Untick one below before adding another.", true);
      return;
    }

    var id;
    if (existing) {
      id = existing.id;
    } else {
      id = utils.generateId("CLP");
      imported.push({
        id: id,
        salutation: src.row.salutation || "",
        fullName: src.row.fullName || "",
        sex: src.row.sex || "",
        passportNumber: src.row.passportNumber || "",
        placeOfIssue: src.row.placeOfIssue || "",
        passportIssueDate: src.row.passportIssueDate || "",
        phone: src.row.phone || "",
        email: src.row.email || "",
        relation: src.row.isApplicant ? "" : src.row.relation || "",
        address: { city: src.address.city || "", country: src.address.country || "" },
        sourceApplicationId: src.appId || null,
      });
    }
    ids.push(id);
    var patch = { coverLetter: { selectedPersonIds: ids, importedPeople: imported } };
    if (hadManualName) patch.coverLetter.manualApplicantName = "";
    global.KhannaState.updateApplication(app.id, patch, null);

    var after = getApp();
    var chosen = peoplePool(after).filter(function (p) { return p.id === id; })[0];
    var role = chosen && chosen.isApplicant ? "applicant" : "companion";
    renderCard();
    setExistingStatus(
      "Added " + authLib().personDisplayName(src.row) + " as " + role + " (from " + src.appLabel + "). " +
        (src.row.passportNumber ? "" : "No passport number is saved for this person — add it on their passport page before generating. ") +
        "Job and employer details are not stored on a passport — fill those in below.",
      false
    );
    if (global.KhannaRouter) global.KhannaRouter.refreshWizardFooter();
  }

  // Fills the letter's trip details from a saved hotel blocking: overall
  // travel dates, number of nights, further stops and hotel details
  // (whichever this letter format uses). Only ever fills values the hotel
  // blocking actually has — anything missing there is left as it was and
  // named in the status line so it can be typed in.
  function useHotelBlockingFromSource(appId) {
    var app = getApp();
    var src = global.KhannaState.getApplication(appId);
    if (!app || !src) return;
    var state = coverState(app);
    var region = state.region;
    var hotels = (src.hotels || []).filter(function (h) { return h.hotelName || h.checkIn || h.checkOut || h.city; });
    if (!hotels.length) {
      setExistingStatus("That hotel blocking has no hotel details to use.", true);
      return;
    }
    var span = hotelDateSpan(hotels);
    var filled = [];
    var missing = [];
    var coverPatch = {};

    if (span.start) { coverPatch.travelStartDate = span.start; filled.push("travel start date"); } else missing.push("travel start date");
    if (span.end) { coverPatch.travelEndDate = span.end; filled.push("travel end date"); } else missing.push("travel end date");

    var first = hotels[0];
    if (region === "Europe") {
      // The first hotel is this trip's primary stay (its nights feed the
      // required "Number of nights"); a genuine SECOND hotel is a second leg
      // of the same trip (its own country/dates feed the optional "Next
      // country" fields) — never invented when only one hotel exists.
      var europePatch = {};
      var nights = nightsBetween(first.checkIn, first.checkOut);
      if (nights) { europePatch.numberOfNights = nights; filled.push("number of nights"); } else missing.push("number of nights");
      var second = hotels[1];
      if (second) {
        if (second.country) europePatch.nextCountry = sentenceCase(second.country, true);
        europePatch.nextTravelStartDate = second.checkIn || "";
        europePatch.nextTravelEndDate = second.checkOut || "";
        europePatch.nextNumberOfNights = nightsBetween(second.checkIn, second.checkOut) || "";
        filled.push("next-country leg");
      }
      coverPatch.europe = europePatch;
    } else if (region === "Singapore") {
      var sg = {};
      if (first.hotelName) { sg.hotelName = sentenceCase(first.hotelName); filled.push("hotel name"); } else missing.push("hotel name");
      if (first.address) { sg.hotelAddress = first.address; filled.push("hotel address"); } else missing.push("hotel address");
      coverPatch.singapore = sg;
    } else if (region === "Japan") {
      coverPatch.japan = {
        hotels: hotels.map(function (h) {
          return {
            id: utils.generateId("CLH"),
            name: sentenceCase(h.hotelName || ""),
            checkIn: h.checkIn || "",
            checkOut: h.checkOut || "",
            contactNo: h.phone || "",
          };
        }),
      };
      filled.push(hotels.length === 1 ? "hotel" : hotels.length + " hotels");
    }

    global.KhannaState.updateApplication(app.id, { coverLetter: coverPatch }, null);
    renderCard();
    setExistingStatus(
      "Filled " + (filled.join(", ") || "nothing") + " from " + appLabel(src) + "’s hotel blocking." +
        (missing.length ? " Not available there — fill in manually: " + missing.join(", ") + "." : ""),
      missing.length > 0
    );
    if (global.KhannaRouter) global.KhannaRouter.refreshWizardFooter();
  }

  // "Enter name of the applicant if the name is not taken from any existing
  // details" (explicit instruction) — lets staff generate a cover letter
  // for a name that was never run through Upload Passport at all. See
  // checklistHtml()/isReady()/buildPayload() above for how this overrides
  // the applicant's checklist slot the moment it has a value.
  //
  // When the applicant is instead ticked from the existing details below (or
  // added through "Use Existing Details"), there is nothing to type: the
  // field becomes a plain "Applicant Name" showing that saved name (read-only
  // — a saved name is corrected on its own passport record, not here), and
  // the optional-input wording only returns for a genuinely new applicant.
  function manualApplicantNameHtml(app, state) {
    var existing = (state.manualApplicantName || "").trim() ? null : selectedPeople(app).filter(function (p) { return p.isApplicant; })[0];
    if (existing) {
      return (
        '<div class="field-grid">' +
        '<div class="field">' +
        '<label for="cover-top-applicantName">Applicant Name</label>' +
        '<input type="text" id="cover-top-applicantName" data-cover-existing-applicant-name readonly value="' + utils.escapeHtml(authLib().personDisplayName(existing)) + '" />' +
        "</div>" +
        "</div>" +
        ''
      );
    }
    return (
      '<div class="field-grid">' +
      fieldRowHtml("top", "manualApplicantName", "Applicant name (optional)", state.manualApplicantName, false, {
        placeholder: "e.g. Mr. John Doe",
      }) +
      "</div>" +
      ''
    );
  }

  var stepHeadingHtml = utils.stepHeadingHtml;

  function regionBodyHtml(app, state, region) {
    var selected = selectedPeople(app);
    var body = stepHeadingHtml(1, "Who is travelling", "Pick travellers already on this application, or add someone manually.");
    body += useExistingDetailsHtml();
    body += manualApplicantNameHtml(app, state);
    body += '<div class="auth-person-list" data-cover-checklist>' + checklistHtml(app, region) + "</div>";
    var count = travellerCount(app);
    var withCompanion = count === 2; // exactly one companion: the original single-companion fields
    var severalCompanions = count >= 3;
    if (withCompanion) body += relationFieldsHtml(app, state);
    body += stepHeadingHtml(2, "Letter details", "Fields marked * are needed before the letter can be generated.");
    body += commonFieldsHtml(app, state, region);
    if (region === "Europe") body += europeFieldsHtml(state, withCompanion);
    else if (region === "Japan") body += japanFieldsHtml(state, withCompanion);
    if (severalCompanions) body += companionDetailsHtml(app, region);
    if (region === "Singapore") body += singaporeFieldsHtml(app, state);
    body += '<div data-cover-readiness></div><div data-cover-generate-bar></div><div data-cover-error></div>';
    return body;
  }

  function renderCard() {
    var app = getApp();
    var box = utils.qs("[data-cover-letter-card]", root());
    if (!app || !box) return;
    // Auto-populate City/Country of residence from the applicant's own
    // saved address the first time this card renders for a Europe letter
    // with that field still empty (section 10) — re-fetch app/state after,
    // since this may have just written to it.
    app = autoSeedEuropeResidence(app);
    app = syncFunding(app);
    var state = coverState(app);
    var region = state.region || "";
    box.innerHTML = region
      ? regionBodyHtml(app, state, region)
      : '<p class="field-hint">Select a destination country above.</p>';
    refreshGenerateBar();
    refreshReadinessNotice();
  }

  /* ---------------------------------------------------------------------
   * Generation
   * ------------------------------------------------------------------- */

  function buildPayload(app, format) {
    var auth = authHelpers();
    var state = coverState(app);
    var region = state.region;
    var manualName = (state.manualApplicantName || "").trim();
    var selected = auth.orderPeopleForLetter(selectedPeople(app));
    var occupations = (state.singapore && state.singapore.occupations) || {};

    var people = selected.map(function (p) {
      return {
        id: p.id,
        salutation: p.salutation || "",
        fullName: p.fullName || "",
        passportNumber: p.passportNumber || "",
        placeOfIssue: p.placeOfIssue || "",
        passportIssueDate: p.passportIssueDate || "",
        relationToApplicant: p.isApplicant ? "" : p.relation || "",
        sex: p.sex || "",
        phone: p.phone || "",
        email: p.email || "",
        isApplicant: !!p.isApplicant,
        occupation: region === "Singapore" ? occupations[p.id] || "" : "",
      };
    });

    // Several companions (Europe/Japan): each one's own relation and
    // job/occupation details travel with them. With a single companion the
    // original single set of fields is sent instead (below), unchanged.
    if (people.filter(function (q) { return !q.isApplicant; }).length >= 2) {
      people.forEach(function (q, i) {
        if (q.isApplicant) return;
        var d = companionDetail(app, q.id);
        var source = selected[i];
        q.travellerRelation = d.relationChoice || recordedRelationChoice(source) || "";
        q.travellerRelationText = (d.relationText || "").trim();
        q.jobTitle = d.jobTitle || "";
        q.employerName = d.employerName || "";
        q.employmentStartYear = d.employmentStartYear || "";
        // Singapore keeps each person's occupation in its own list (above).
        if (region !== "Singapore") q.occupation = d.occupation || "";
      });
    }

    // Manual applicant name (used instead of this application's own saved
    // passport data — see the field above the checklist): stands in for
    // the applicant row only. Every field besides the name itself is left
    // blank rather than guessed, matching the OCR principle elsewhere in
    // this app of never fabricating a value nobody actually entered.
    if (manualName) {
      people = [{
        id: "manual-applicant",
        salutation: "",
        fullName: manualName,
        passportNumber: "",
        placeOfIssue: "",
        passportIssueDate: "",
        relationToApplicant: "",
        sex: "",
        phone: "",
        email: "",
        isApplicant: true,
        occupation: region === "Singapore" ? occupations["manual-applicant"] || "" : "",
      }].concat(people);
    }

    var applicantName = manualName || [app.applicant.firstName, app.applicant.lastName].filter(Boolean).join(" ") || "Application";

    var payload = {
      region: region,
      people: people,
      recipientText: state.recipientText || "",
      destinationCountry: state.destinationCountry || "",
      travelStartDate: state.travelStartDate || "",
      travelEndDate: state.travelEndDate || "",
      fundingArrangement: composeFunding(state, travellerCount(app) > 1) || state.fundingArrangement || "",
      fundingPayerName: (state.fundingPayerName || "").trim(),
      travellerRelation: relationChoiceFor(app),
      travellerRelationText: (state.travellerRelationText || "").trim(),
      format: format,
      applicantName: applicantName,
    };

    if (region === "Europe") {
      var e = state.europe || {};
      Object.assign(payload, {
        cityCountryOfResidence: europeCombinedResidence(e),
        numberOfNights: e.numberOfNights || "",
        applicantEmploymentStatus: e.applicantEmploymentStatus || "",
        applicantJobTitle: e.applicantJobTitle || "",
        applicantEmployerName: e.applicantEmployerName || "",
        companionJobTitle: e.companionJobTitle || "",
        companionEmployerName: e.companionEmployerName || "",
        companionEmploymentStartYear: e.companionEmploymentStartYear || "",
        nextCountry: e.nextCountry || "",
        nextTravelStartDate: e.nextTravelStartDate || "",
        nextTravelEndDate: e.nextTravelEndDate || "",
        nextNumberOfNights: e.nextNumberOfNights || "",
      });
      // The staff member's hand edit of the three body paragraphs (made on
      // the preview itself); absent/null means "auto-compose as normal".
      var editedBody = (state.editedFields || {}).body;
      if (editedBody != null) payload.editedBodyHtml = editedBody;
    } else if (region === "Japan") {
      var j = state.japan || {};
      payload.applicantEmployerOccupation = j.applicantEmployerOccupation || "";
      payload.companionOccupation = j.companionOccupation || "";
      payload.hotels = (j.hotels || []).map(function (h) {
        return { name: h.name || "", checkIn: h.checkIn || "", checkOut: h.checkOut || "", contactNo: h.contactNo || "" };
      });
    } else if (region === "Singapore") {
      var s = state.singapore || {};
      payload.hotelName = s.hotelName || "";
      payload.hotelAddress = s.hotelAddress || "";
    }

    // Whole-document edits (every paragraph that is not a named field).
    var blocks = {};
    Object.keys(state.editedFields || {}).forEach(function (k) {
      if (k.indexOf("blk-") === 0 && state.editedFields[k] != null) blocks[k] = state.editedFields[k];
    });
    if (Object.keys(blocks).length) payload.editedFields = blocks;

    return payload;
  }

  // Keyed by root element — this module dual-mounts (wizard root vs. the
  // standalone Cover Letter page root; see root() above), same hazard
  // hotels.js's own viewerHandles WeakMap already guards against.
  var viewerHandles = new WeakMap();
  var pendingPreview = false;

  function generate(btn) {
    var app = getApp();
    if (!app || !isReady(app)) return;
    showError("");
    var r = root();
    if (!r) return;
    var previewBox = utils.qs("[data-doc-preview]", r);
    if (!previewBox) return;

    var handle = viewerHandles.get(r);
    if (!handle) {
      handle = global.KhannaDocumentViewer.mount(previewBox, {
        title: "Cover Letter",
        editor: makeCoverEditor(),
        loadPdf: function () {
          return loadCoverPreview(getApp());
        },
        loadDocx: function () {
          var a = getApp();
          return api.downloadCoverLetter(buildPayload(a, "docx"));
        },
        onEdit: function () {
          var box = utils.qs("[data-cover-letter-card]", root());
          if (box) box.scrollIntoView({ behavior: "smooth", block: "start" });
        },
        onRegenerate: function () {
          return Promise.resolve();
        },
      });
      viewerHandles.set(r, handle);
    }

    var originalText = btn ? btn.textContent : "";
    if (btn) {
      btn.disabled = true;
      btn.textContent = "Generating…";
    }
    var region = coverState(app).region;
    handle
      .refresh()
      .then(function () {
        // Previewing from the Dashboard's View icon only re-displays a
        // document — it must not change "Last generated" / "Updated" dates.
        if (global.KhannaRouter && global.KhannaRouter.isPreviewMode()) return;
        var ts = new Date().toISOString();
        global.KhannaState.updateApplication(app.id, { coverLetter: { generatedAt: ts } }, region + " Cover Letter generated");
      })
      .catch(function (err) {
        showError((err && err.message) || "Could not generate the cover letter.");
      })
      .finally(function () {
        if (btn) {
          btn.disabled = false;
          btn.textContent = originalText;
        }
      });
  }

  /* ---------------------------------------------------------------------
   * Skeleton, wiring
   * ------------------------------------------------------------------- */

  function mountSkeleton() {
    var r = root();
    if (!r) return;
    var app = getApp();
    var state = coverState(app);
    r.innerHTML =
      '<div class="card">' +
      "<h3>Cover Letter</h3>" +
      countrySelectorHtml(state) +
      '<div data-cover-letter-card></div>' +
      "</div>" +
      // Deliberately a SIBLING of [data-cover-letter-card], not nested
      // inside it: renderCard() replaces that card's entire innerHTML on
      // every region change and person-selection change (see renderCard()
      // callers below), which would otherwise destroy a mounted preview on
      // any such edit. Living one level up here, it only remounts fresh on
      // a full mountSkeleton() (a real navigation), matching hotels.js's/
      // authorization.js's own "preview div lives outside the part that
      // rebuilds on every edit" placement.
      '<div data-doc-preview style="margin-top:var(--space-4);"></div>';

    // Searchable country selector: opens with the full list when the field
    // is focused, then filters as the staff member types. Picking a country
    // sets the letter format AND replaces the "Consulate name & address"
    // and "Destination country" fields with that country's own values.
    function countryInput() {
      return utils.qs("[data-cover-country-search]", r);
    }

    function closeCountryList(restoreText) {
      var list = utils.qs("[data-cover-country-list]", r);
      var input = countryInput();
      if (list) list.setAttribute("hidden", "");
      if (input) {
        input.setAttribute("aria-expanded", "false");
        input.removeAttribute("aria-activedescendant");
        // Typed text that was never turned into a selection goes back to the
        // country that is actually selected (never left looking selected).
        if (restoreText) input.value = coverState(getApp()).country || "";
      }
    }

    function openCountryList(query) {
      var list = utils.qs("[data-cover-country-list]", r);
      var input = countryInput();
      if (!list) return;
      list.innerHTML = countryOptionsHtml(query);
      list.removeAttribute("hidden");
      if (input) input.setAttribute("aria-expanded", "true");
      setActiveCountryOption(0);
    }

    function countryOptionEls() {
      return utils.qsa("[data-cover-country-option]", r);
    }

    function setActiveCountryOption(index) {
      var opts = countryOptionEls();
      opts.forEach(function (o, i) { o.classList.toggle("is-active", i === index); });
      var input = countryInput();
      if (!opts.length) {
        if (input) input.removeAttribute("aria-activedescendant");
        return;
      }
      var active = opts[Math.max(0, Math.min(index, opts.length - 1))];
      if (input) input.setAttribute("aria-activedescendant", active.id);
      if (active.scrollIntoView) active.scrollIntoView({ block: "nearest" });
    }

    function activeCountryIndex() {
      var opts = countryOptionEls();
      for (var i = 0; i < opts.length; i++) if (opts[i].classList.contains("is-active")) return i;
      return -1;
    }

    function chooseCountry(name) {
      var current = getApp();
      if (!current) return;
      var lib = countryLib();
      var entry = lib ? lib.byName(name) : null;
      if (!entry) return;
      var patch = { coverLetter: { country: entry.name, region: entry.region } };
      // The consulate name/address follows the selected country (e.g. Japan
      // -> the Japan consulate line) and stays a plain, editable text field
      // afterward — see js/data/cover-letter-countries.js on why the street
      // address half starts blank rather than invented.
      var consulateName = lib.consulateDefaultText(entry);
      var addrInput = utils.qs('[data-cover-field="top:consulateAddress"]', r);
      var consulateAddress = addrInput ? addrInput.value : global.KhannaConsulate.addressOrDefault(coverState(current).consulateAddress);
      patch.coverLetter.consulateName = consulateName;
      patch.coverLetter.consulateAddress = consulateAddress;
      patch.coverLetter.recipientText = global.KhannaConsulate.composeRecipient(consulateName, consulateAddress);
      if (entry.region !== "Singapore") patch.coverLetter.destinationCountry = entry.name;
      global.KhannaState.updateApplication(current.id, patch, null);
      closeCountryList(false);
      var selectWrap = utils.qs("[data-cover-country-select]", r);
      if (selectWrap) selectWrap.outerHTML = countrySelectorHtml(coverState(getApp()));
      renderCard();
      if (global.KhannaRouter) global.KhannaRouter.refreshWizardFooter();
    }

    // "focusin" (not "focus") — the latter doesn't bubble, so a delegated
    // listener on the root would never see it; this also keeps working after
    // the country-select wrapper's outerHTML is replaced on every selection.
    utils.on(r, "focusin", "[data-cover-country-search]", function (e, target) {
      if (target.select) target.select(); // typing replaces the current country straight away
      openCountryList("");
    });

    utils.on(r, "input", "[data-cover-country-search]", function (e, target) {
      openCountryList(target.value);
    });

    utils.on(r, "keydown", "[data-cover-country-search]", function (e, target) {
      var list = utils.qs("[data-cover-country-list]", r);
      var isOpen = list && !list.hasAttribute("hidden");
      if (e.key === "ArrowDown" || e.key === "ArrowUp") {
        e.preventDefault();
        if (!isOpen) openCountryList(target.value);
        var n = countryOptionEls().length;
        if (!n) return;
        var cur = activeCountryIndex();
        setActiveCountryOption(e.key === "ArrowDown" ? (cur + 1) % n : (cur - 1 + n) % n);
      } else if (e.key === "Enter") {
        if (!isOpen) return;
        e.preventDefault();
        var opts = countryOptionEls();
        var idx = activeCountryIndex();
        var pick = opts[idx >= 0 ? idx : 0];
        if (pick) chooseCountry(pick.getAttribute("data-cover-country-option"));
      } else if (e.key === "Escape") {
        closeCountryList(true);
      }
    });

    utils.on(r, "click", "[data-cover-country-option]", function (e, target) {
      chooseCountry(target.getAttribute("data-cover-country-option"));
    });

    document.addEventListener("click", function (e) {
      var wrap = utils.qs("[data-country-combo]", r);
      if (!wrap || wrap.contains(e.target)) return;
      closeCountryList(true);
    });

    // "Use Existing Details ▾" — open/close (same is-open + outside-click +
    // Escape pattern as app.js's own header "New Application" menu, kept
    // local here rather than shared since the trigger/dropdown pair is
    // different and renderCard() rebuilds this markup on every region/
    // person change, so the listeners below re-query the DOM at click time
    // instead of caching element references that would go stale.
    utils.on(r, "click", "[data-cover-use-existing-toggle]", function (e, target) {
      e.stopPropagation();
      var dd = utils.qs("[data-cover-use-existing-dropdown]", r);
      if (!dd) return;
      var willOpen = !dd.classList.contains("is-open");
      dd.classList.toggle("is-open", willOpen);
      if (willOpen) {
        dd.classList.remove("has-list");
        var secondList = utils.qs("[data-cover-existing-list]", r);
        if (secondList) secondList.hidden = true;
        utils.qsa("[data-cover-use-existing-option]", r).forEach(function (b) { b.classList.remove("is-active"); });
      }
      target.setAttribute("aria-expanded", willOpen ? "true" : "false");
    });
    document.addEventListener("click", function (e) {
      var wrap = utils.qs("[data-cover-use-existing]", r);
      if (!wrap || wrap.contains(e.target)) return;
      var dd = utils.qs("[data-cover-use-existing-dropdown]", r);
      var toggle = utils.qs("[data-cover-use-existing-toggle]", r);
      if (dd) dd.classList.remove("is-open");
      if (toggle) toggle.setAttribute("aria-expanded", "false");
    });
    document.addEventListener("keydown", function (e) {
      if (e.key !== "Escape") return;
      var dd = utils.qs("[data-cover-use-existing-dropdown]", r);
      var toggle = utils.qs("[data-cover-use-existing-toggle]", r);
      if (dd) dd.classList.remove("is-open");
      if (toggle) toggle.setAttribute("aria-expanded", "false");
    });

    // Choosing "Passport" or "Hotel Blocking" opens the second small list
    // beside the menu with the saved passports / hotel blockings.
    utils.on(r, "click", "[data-cover-use-existing-option]", function (e, target) {
      e.stopPropagation();
      var kind = target.getAttribute("data-cover-use-existing-option");
      var list = utils.qs("[data-cover-existing-list]", r);
      if (!list) return;
      utils.qsa("[data-cover-use-existing-option]", r).forEach(function (b) {
        b.classList.toggle("is-active", b === target);
      });
      list.innerHTML = existingListHtml(kind);
      list.hidden = false;
      var dd = utils.qs("[data-cover-use-existing-dropdown]", r);
      if (dd) dd.classList.add("has-list");
    });

    utils.on(r, "click", "[data-cover-existing-pick]", function (e, target) {
      var kind = target.getAttribute("data-cover-existing-pick");
      showError("");
      if (kind === "passport") usePassportFromSource(target.getAttribute("data-passport-key"));
      else useHotelBlockingFromSource(target.getAttribute("data-app-id"));
    });

    // "+ Add another traveller": a person typed in here becomes a real
    // traveller on the application and is ticked on this letter (within the
    // region's people limit).
    // "Complete details" beside a person whose printed details are empty.
    utils.on(r, "click", "[data-complete-cover]", function (e, target) {
      var personId = target.getAttribute("data-complete-details");
      if (!personId || !global.KhannaAddTraveller) return;
      global.KhannaAddTraveller.open(function () {
        renderCard();
      }, { docKey: "coverLetter", personId: personId });
    });

    utils.on(r, "click", "[data-action='add-another-traveller']", function () {
      var app0 = getApp();
      if (!app0 || !global.KhannaAddTraveller) return;
      global.KhannaAddTraveller.open(function (travellerId, info) {
        var app1 = getApp();
        if (!app1) return;
        var state1 = coverState(app1);
        var ids1 = (state1.selectedPersonIds || []).slice();
        var maxCount1 = maxPeopleFor(state1.region);
        var selectedNow = !(maxCount1 && ids1.length >= maxCount1);
        if (selectedNow) {
          ids1.push(travellerId);
          global.KhannaState.updateApplication(app1.id, { coverLetter: { selectedPersonIds: ids1 } }, null);
        }
        renderCard();
        setExistingStatus(
          selectedNow
            ? "Added " + info.fullName + " and selected them on this letter."
            : "Added " + info.fullName + " to the application. This letter format takes only " + maxCount1 + " people — untick one below to select them.",
          !selectedNow
        );
      }, { docKey: "coverLetter" });
    });

    utils.on(r, "change", "[data-cover-person]", function (e, target) {
      var current = getApp();
      if (!current) return;
      var state = coverState(current);
      var maxCount = maxPeopleFor(state.region);
      var ids = (state.selectedPersonIds || []).slice();
      var personId = target.getAttribute("data-person-id");
      var idx = ids.indexOf(personId);
      if (target.checked) {
        if (idx === -1) {
          if (maxCount && ids.length >= maxCount) {
            target.checked = false; // guard, in addition to the disabled attribute
            return;
          }
          ids.push(personId);
        }
      } else if (idx !== -1) {
        ids.splice(idx, 1);
      }
      global.KhannaState.updateApplication(current.id, { coverLetter: { selectedPersonIds: ids } }, null);
      // Selecting/deselecting a person is an explicit action taken in this
      // panel, and Singapore's per-person occupation fields (and the
      // checklist's own disabled/checked state) depend directly on this
      // list — a full card rebuild here is correct, not a background
      // overwrite (see file header).
      renderCard();
      if (global.KhannaRouter) global.KhannaRouter.refreshWizardFooter();
    });

    utils.on(r, "change", "[data-cover-field]", function (e, target) {
      var current = getApp();
      if (!current) return;
      var parts = target.getAttribute("data-cover-field").split(":");
      var scope = parts[0];
      var key = parts[1];
      // Dates: never in the past, an end never before its start. A refused
      // edit puts the previous value back and says why.
      if (DATE_LABELS[key]) {
        var before = coverState(current);
        var problem = dateEditProblem(before, scope, key, target.value);
        if (problem) {
          target.value = (scope === "top" ? before[key] : (before[scope] || {})[key]) || "";
          showError(problem);
          return;
        }
        showError("");
      }
      // Places and typed details are tidied to sentence case ("MUMBAI" -> "Mumbai").
      var fieldId = scope + ":" + key;
      var typedValue = target.value;
      if (PLACE_FIELDS.indexOf(fieldId) !== -1 || DETAIL_FIELDS.indexOf(fieldId) !== -1) {
        typedValue = sentenceCase(typedValue, PLACE_FIELDS.indexOf(fieldId) !== -1);
        if (typedValue !== target.value) target.value = typedValue;
      }
      if (fieldId === "top:fundingRelationCustom" && typedValue) {
        typedValue = typedValue.trim().charAt(0).toUpperCase() + typedValue.trim().slice(1);
        target.value = typedValue;
      }
      var patch = { coverLetter: {} };
      if (scope === "top") {
        patch.coverLetter[key] = typedValue;
      } else {
        patch.coverLetter[scope] = {};
        patch.coverLetter[scope][key] = typedValue;
      }
      if (scope === "top" && (key === "consulateName" || key === "consulateAddress")) {
        // recipientText is what the letter reads: the two lines joined.
        // Read both from the form (not state) so a letter saved with the old
        // single line is not suddenly given a default address.
        var nameEl = utils.qs('[data-cover-field="top:consulateName"]', r);
        var addrEl = utils.qs('[data-cover-field="top:consulateAddress"]', r);
        patch.coverLetter.consulateName = nameEl ? nameEl.value : "";
        patch.coverLetter.consulateAddress = addrEl ? addrEl.value : "";
        patch.coverLetter.recipientText = global.KhannaConsulate.composeRecipient(patch.coverLetter.consulateName, patch.coverLetter.consulateAddress);
      }
      // A new start date later than the end date already entered: the end
      // date can no longer be right, so it is cleared (and the user told).
      var endOf = { travelStartDate: ["top", "travelEndDate"], nextTravelStartDate: ["europe", "nextTravelEndDate"] }[key];
      var endCleared = null;
      if (endOf && target.value) {
        var cur = coverState(current);
        var curEnd = endOf[0] === "top" ? cur[endOf[1]] : (cur[endOf[0]] || {})[endOf[1]];
        if (curEnd && curEnd < target.value) {
          if (endOf[0] === "top") patch.coverLetter[endOf[1]] = "";
          else (patch.coverLetter[endOf[0]] = patch.coverLetter[endOf[0]] || {})[endOf[1]] = "";
          endCleared = endOf;
        }
      }
      // Funding: choosing "Self" drops any payer details; every change
      // recomposes the one sentence-ready value the letter reads.
      var fundingKeys = ["fundingType", "fundingPayerName", "fundingRelation", "fundingRelationChoice", "fundingRelationCustom"];
      if (scope === "top" && fundingKeys.indexOf(key) !== -1) {
        var clearRelation = function () {
          patch.coverLetter.fundingRelation = "";
          patch.coverLetter.fundingRelationChoice = "";
          patch.coverLetter.fundingRelationCustom = "";
        };
        if (key === "fundingType" && target.value !== "inviter" && target.value !== "company" && target.value !== "other") {
          patch.coverLetter.fundingPayerName = "";
          clearRelation();
        } else if (key === "fundingType") {
          // The relation list depends on who pays: drop a choice the new list doesn't have.
          var keptChoice = coverState(current).fundingRelationChoice || "";
          if (keptChoice && fundingRelationOptions(target.value).indexOf(keptChoice) === -1) clearRelation();
        }
        if (key === "fundingRelationChoice" || key === "fundingRelationCustom") {
          var merged = Object.assign({}, coverState(current), patch.coverLetter);
          if (key === "fundingRelationChoice" && target.value !== "Other") patch.coverLetter.fundingRelationCustom = "";
          patch.coverLetter.fundingRelation = fundingRelationFrom(Object.assign(merged, patch.coverLetter));
        }
        patch.coverLetter.fundingArrangement = composeFunding(Object.assign({}, coverState(current), patch.coverLetter), travellerCount(current) > 1);
      }
      var isManualNameField = key === "manualApplicantName";
      if (isManualNameField && target.value.trim()) {
        // The manual name takes the applicant's own slot (see checklistHtml()
        // above and buildPayload() below) — drop the applicant out of
        // selectedPersonIds so the checklist and the generated letter never
        // try to use both at once.
        // getSelectablePeople() (authorization.js) always gives the
        // applicant the fixed id "applicant" (travellers use their own real
        // ids) — see toPersonRow() there.
        var state = coverState(current);
        var ids = (state.selectedPersonIds || []).filter(function (id) {
          return id !== "applicant";
        });
        patch.coverLetter.selectedPersonIds = ids;
      }
      global.KhannaState.updateApplication(current.id, patch, null);
      // Keep the date inputs' own limits in step with what was just chosen.
      if (endOf) {
        var endEl = utils.qs('[data-cover-field="' + endOf[0] + ":" + endOf[1] + '"]', r);
        if (endEl) {
          endEl.min = target.value ? laterOf(utils.todayIso(), target.value) : utils.todayIso();
          if (endCleared) {
            endEl.value = "";
            showError("The end date was cleared because it came before the new start date — pick it again.");
          }
        }
      }
      // The funding dropdown decides which payer boxes exist: rebuild.
      if (scope === "top" && (key === "fundingType" || key === "fundingRelationChoice")) renderCard();
      if (scope === "top" && (key === "travellerRelation" || key === "travellerRelationText")) refreshRelationPreview();
      // This one field is an exception to "never rebuild the card on a
      // plain field edit" (see file header) — filling or clearing it changes
      // who counts as selected (the Singapore occupation list and the
      // Europe/Japan people cap both key off that), the same class of
      // "changes this panel's own shape" action as a checklist toggle.
      if (isManualNameField) renderCard();
      if (global.KhannaRouter) global.KhannaRouter.refreshWizardFooter();
    });

    utils.on(r, "change", "[data-cover-companion]", function (e, target) {
      var current = getApp();
      if (!current) return;
      var spec = target.getAttribute("data-cover-companion");
      var cut = spec.lastIndexOf(":");
      var personId = spec.slice(0, cut);
      var key = spec.slice(cut + 1);
      var value = target.value;
      if (key === "jobTitle" || key === "employerName" || key === "occupation") value = sentenceCase(value, false);
      if (key !== "relationChoice" && key !== "relationText" && value !== target.value) target.value = value;
      var details = {};
      details[key] = value;
      var patch = { coverLetter: { companionDetails: {} } };
      patch.coverLetter.companionDetails[personId] = details;
      global.KhannaState.updateApplication(current.id, patch, null);
      refreshCompanionPreview(personId);
      if (global.KhannaRouter) global.KhannaRouter.refreshWizardFooter();
    });

    utils.on(r, "change", "[data-cover-occupation]", function (e, target) {
      var current = getApp();
      if (!current) return;
      var personId = target.getAttribute("data-cover-occupation");
      var patch = { coverLetter: { singapore: { occupations: {} } } };
      patch.coverLetter.singapore.occupations[personId] = target.value;
      global.KhannaState.updateApplication(current.id, patch, null);
      refreshGenerateBar();
      refreshReadinessNotice();
      if (global.KhannaRouter) global.KhannaRouter.refreshWizardFooter();
    });

    utils.on(r, "change", "[data-cover-hotel-field]", function (e, target) {
      var current = getApp();
      if (!current) return;
      var row = target.closest("[data-hotel-id]");
      if (!row) return;
      var hotelId = row.getAttribute("data-hotel-id");
      var key = target.getAttribute("data-cover-hotel-field");
      var state = coverState(current);
      if (key === "checkIn" || key === "checkOut") {
        var existing = ((state.japan || {}).hotels || []).filter(function (h) { return h.id === hotelId; })[0] || {};
        var v = isoOnly(target.value);
        var floor = key === "checkOut" ? laterOf(utils.todayIso(), isoOnly(existing.checkIn)) : utils.todayIso();
        if (v && v < floor) {
          target.value = existing[key] || "";
          showError(
            v < utils.todayIso()
              ? "Hotel dates can't be in the past — choose today or a later date."
              : "Hotel check-out can't be before check-in."
          );
          return;
        }
        showError("");
      }
      var hotels = ((state.japan || {}).hotels || []).map(function (h) {
        if (h.id !== hotelId) return h;
        var updated = Object.assign({}, h);
        updated[key] = target.value;
        return updated;
      });
      global.KhannaState.updateApplication(current.id, { coverLetter: { japan: { hotels: hotels } } }, null);
    });

    utils.on(r, "click", "[data-action='add-cover-hotel']", function () {
      var current = getApp();
      if (!current) return;
      var state = coverState(current);
      var hotels = ((state.japan || {}).hotels || []).concat([global.KhannaState.createEmptyCoverLetterHotel()]);
      global.KhannaState.updateApplication(current.id, { coverLetter: { japan: { hotels: hotels } } }, "Cover Letter hotel added");
      renderCard();
    });

    utils.on(r, "click", "[data-action='remove-cover-hotel']", function (e, target) {
      var current = getApp();
      if (!current) return;
      var hotelId = target.getAttribute("data-hotel-id");
      var state = coverState(current);
      var hotels = ((state.japan || {}).hotels || []).filter(function (h) {
        return h.id !== hotelId;
      });
      global.KhannaState.updateApplication(current.id, { coverLetter: { japan: { hotels: hotels } } }, "Cover Letter hotel removed");
      renderCard();
    });

    utils.on(r, "click", "[data-action='generate-cover-letter']", function (e, target) {
      if (target.disabled) return;
      generate(target);
    });
  }

  // Frontend rework, section 5: shown below the "No application selected
  // yet" bar (document-workspace.js) on the standalone Cover Letter page
  // only — every application that already has a generated cover letter, so
  // staff can jump straight back into one instead of hunting for it via
  // "Use Existing Application". Nothing to show (and this returns "") once
  // an application IS active, or when none has ever generated one yet.
  function previousCoverLetterApplicationsHtml() {
    var apps = (global.KhannaState.getApplications() || []).filter(function (a) {
      return a.coverLetter && a.coverLetter.generatedAt;
    });
    if (!apps.length) return "";
    var rows = apps
      .map(function (a) {
        var label = global.KhannaApplicationsList
          ? global.KhannaApplicationsList.applicantLabel(a)
          : (a.applicant && a.applicant.fullName) || "Untitled applicant";
        var region = a.coverLetter.region || "";
        var countryOrRegion = a.coverLetter.country || REGION_FORMAT_LABELS[region] || region || "Cover Letter";
        return (
          '<button type="button" class="cover-previous-app-row" data-cover-previous-app="' + utils.escapeHtml(a.id) + '">' +
          '<span class="cover-previous-app-row__name">' + utils.escapeHtml(label) + "</span>" +
          '<span class="cover-previous-app-row__meta">' +
          utils.escapeHtml(countryOrRegion) +
          " · generated " + utils.escapeHtml(utils.formatDate(a.coverLetter.generatedAt)) +
          "</span>" +
          "</button>"
        );
      })
      .join("");
    return (
      '<div class="card" style="margin-top:var(--space-4);">' +
      "<h3>Previous Cover Letter Applications</h3>" +
      '<div class="cover-previous-app-list">' + rows + "</div>" +
      "</div>"
    );
  }

  function render() {
    var r = root();
    if (!r) return;
    // Same reasoning as hotels.js's own render(): the wizard is never
    // entered without an active application, so this only ever matters for
    // the standalone Cover Letter page, which can be opened directly with
    // none yet. Left unmounted (not dataset.mounted) so the real skeleton
    // still mounts the next time render() runs with an application active.
    if (!getApp()) {
      // See hotels.js's own render() for why this also clears a stale
      // dataset.mounted flag, not just the placeholder text.
      delete r.dataset.mounted;
      r.innerHTML =
        '<p class="field-hint">Create or continue an application above to start a cover letter.</p>' +
        previousCoverLetterApplicationsHtml();
      return;
    }
    if (!r.dataset.mounted) {
      r.dataset.mounted = "1";
      mountSkeleton();
    }
    renderCard();
    if (pendingPreview && r === utils.qs("[data-cover-letter-page-root]")) {
      pendingPreview = false;
      // Recent Cover Letters -> Edit: straight to the (real) preview when the
      // letter is complete enough to generate; otherwise the form is shown.
      if (isReady(getApp())) {
        generate(null);
        var box = utils.qs("[data-doc-preview]", r);
        if (box && box.scrollIntoView) box.scrollIntoView({ behavior: "smooth", block: "start" });
      }
    }
  }

  function init() {
    // Only the checklist + generate bar + readiness notice (+ Phase 4's
    // body editor readiness/seeding, same reasoning) react to every
    // background state change — never the text fields, hotel rows or
    // occupation rows (see file header).
    global.KhannaState.subscribe(function () {
      var r = root();
      if (!r || !r.dataset.mounted) return;
      refreshChecklist();
      refreshGenerateBar();
      refreshReadinessNotice();
    });

    // Standalone Cover Letter page (Phase 2): the wizard case is still
    // driven by authorization.js's own render() calling
    // global.KhannaCoverLetter.render() directly — this listener only ever
    // fires for the new standalone view, so it's additive and changes
    // nothing about how the wizard already works.
    document.addEventListener("khanna:navigate", function (e) {
      if (e.detail.view === "cover-letter") render();
    });

    // "Previous Cover Letter Applications" row click (section 5): makes
    // that application active and re-renders through the SAME
    // "khanna:navigate" event document-workspace.js's own picker already
    // uses for this (see its rerenderCurrentDocumentController()), so its
    // shared "Working on ..." bar updates too, not just this card.
    utils.on(document, "click", "[data-cover-previous-app]", function (e, target) {
      var id = target.getAttribute("data-cover-previous-app");
      if (!id) return;
      global.KhannaState.setActiveApplicationId(id);
      document.dispatchEvent(new CustomEvent("khanna:navigate", { detail: { view: "cover-letter", step: null } }));
    });

    if (location.hash.indexOf("cover-letter") !== -1) render();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }

  global.KhannaCoverLetter = {
    render: render,
    isReady: isReady,
    // Recent Cover Letters -> "Edit": the next Cover Letter page render
    // opens the preview straight away.
    requestPreview: function () {
      pendingPreview = true;
    },
    // Recent Cover Letters -> "Download": the real backend document for ANY
    // saved application (not only the active one), as docx or pdf. Built
    // from saved data only (never from an open editor), and refused —
    // with the reason — while required fields are still missing.
    downloadFor: function (appId, format) {
      var target = global.KhannaState.getApplication(appId);
      if (!target) return Promise.reject(new Error("That application no longer exists."));
      if (!isReady(target)) {
        return Promise.reject(new Error("This cover letter is not complete yet — use Edit to fill in the missing details."));
      }
      return api.downloadCoverLetter(buildPayload(target, format));
    },
  };
})(window);
