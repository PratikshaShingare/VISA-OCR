/* ============================================================================
   Khanna Travels & Holidays — Applicant Groups (Frontend rework, Phase E)

   A small, shared store for named "groups of applicants" — the same set of
   travellers a staff member ends up re-selecting, one by one, across the
   Cover Letter, Hotel Blocking and Company Authorization Letter tabs of the
   SAME application/trip. Saving that set once as a named group lets any of
   those tabs apply it in one action instead of re-checking every person
   (the user's own words: "add an option to create a group of applicants
   to save page space").

   Scope: one application's own groups, stored on the application itself
   (js/core/state.js's createEmptyApplication() -> applicantGroups: []) —
   not a global, cross-application store. A group only ever needs to carry
   the two fields any of these letters actually use to name an applicant
   (fullName, passportNumber) — never a full traveller/passport record —
   so a group stays meaningful even for a person who was never onboarded
   as a full traveller on this application (see authorization.js's
   "manualApplicants" — created via this exact same {fullName,
   passportNumber} shape).

   Wired into the Company Authorization Letter tab first (js/authorization.js
   — explicitly requested); Cover Letter/Hotel Blocking can reuse this same
   module later without a second, duplicated store (project rule 15).
   ============================================================================ */

(function (global) {
  "use strict";

  var utils = global.KhannaUtils;

  function groupsFor(app) {
    return (app && app.applicantGroups) || [];
  }

  function normalizeMembers(members) {
    return (members || [])
      .map(function (m) {
        return {
          fullName: (m.fullName || "").trim(),
          passportNumber: (m.passportNumber || "").trim(),
        };
      })
      .filter(function (m) {
        return m.fullName && m.passportNumber;
      });
  }

  /** Saves a new named group on the given application. `members` is any
   * array of objects carrying at least fullName/passportNumber (a real
   * traveller row and a manual applicant row both already have these) —
   * only those two fields are kept, matching what every caller of a saved
   * group actually needs. Returns the created group, or null if `name` or
   * every member was blank (never saves a pointless empty/unnamed group). */
  function saveGroup(appId, name, members) {
    var trimmedName = (name || "").trim();
    var cleanMembers = normalizeMembers(members);
    if (!trimmedName || !cleanMembers.length) return null;
    var app = global.KhannaState.getApplication(appId);
    if (!app) return null;
    var group = {
      id: utils.generateId("GRP"),
      name: trimmedName,
      members: cleanMembers,
      createdAt: new Date().toISOString(),
    };
    var groups = groupsFor(app).concat([group]);
    global.KhannaState.updateApplication(appId, { applicantGroups: groups }, 'Applicant group "' + trimmedName + '" saved');
    return group;
  }

  function deleteGroup(appId, groupId) {
    var app = global.KhannaState.getApplication(appId);
    if (!app) return;
    var group = groupsFor(app).filter(function (g) {
      return g.id === groupId;
    })[0];
    var groups = groupsFor(app).filter(function (g) {
      return g.id !== groupId;
    });
    global.KhannaState.updateApplication(appId, { applicantGroups: groups }, group ? 'Applicant group "' + group.name + '" deleted' : null);
  }

  global.KhannaApplicantGroups = {
    groupsFor: groupsFor,
    saveGroup: saveGroup,
    deleteGroup: deleteGroup,
  };
})(window);
