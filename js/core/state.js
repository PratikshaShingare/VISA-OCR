/* ==========================================================================
   Khanna Travels & Holidays — Central application state
   Single source of truth for Application records. Every feature module
   (applicant, travellers, documents, checklist, hotel, cover letter,
   authorization, invitation, admin, ...) reads and writes through this
   module instead of holding its own copy of applicant/passport data, so a
   passport number entered once is the same value the cover letter,
   authorization letter and Excel export all read later.

   Persistence: localStorage for now (this app has no backend server yet —
   later phases can swap loadAll()/persist() for real API calls without
   touching the public API below).
   ========================================================================== */

(function (global) {
  "use strict";

  var utils = global.KhannaUtils;
  var storage = utils.storage;

  var APPLICATIONS_KEY = "khanna_applications_v1";
  var ACTIVE_KEY = "khanna_active_application_id_v1";
  var APPLICANT_PROFILES_KEY = "khanna_applicant_profiles_v1";
  var TRAVELLER_PROFILES_KEY = "khanna_traveller_profiles_v1";

  // Canonical application status list (Master Prompt, Phase 26).
  var STATUSES = [
    "Draft",
    "New",
    "Documents Pending",
    "Documents Received",
    "Under Review",
    "Ready for Submission",
    "Submitted",
    "Processing",
    "Approved",
    "Rejected",
    "Cancelled",
  ];

  var applications = []; // in-memory mirror of what's persisted
  var activeApplicationId = null;
  var subscribers = [];

  function nowIso() {
    return new Date().toISOString();
  }

  function isPlainObject(value) {
    return Object.prototype.toString.call(value) === "[object Object]";
  }

  /** Recursively merges `patch` into `target`. Arrays and primitives in the
   *  patch replace the target's value outright (no array item-merging). */
  function deepMerge(target, patch) {
    if (!isPlainObject(patch)) return patch;
    var out = isPlainObject(target) ? Object.assign({}, target) : {};
    Object.keys(patch).forEach(function (key) {
      var patchVal = patch[key];
      if (isPlainObject(patchVal) && isPlainObject(out[key])) {
        out[key] = deepMerge(out[key], patchVal);
      } else {
        out[key] = patchVal;
      }
    });
    return out;
  }

  /* ---------------------------------------------------------------------
   * Data model factories
   * ------------------------------------------------------------------- */

  function emptyPassport() {
    return {
      current: {
        number: "",
        issueDate: "",
        expiryDate: "",
        issuePlace: "",
        issuingAuthority: "",
        type: "",
        countryCode: "",
        mrzLine1: "",
        mrzLine2: "",
        mrzValid: null, // null = not checked, true/false once MRZ processed
      },
      old: null, // same shape as `current`, or null if not applicable
      imageRef: null,
      rotation: 0,
      verificationStatus: "Not Started", // Not Started | OCR Extracted — Please Verify | Verified
    };
  }

  function emptyPerson() {
    return {
      salutation: "",
      firstName: "",
      middleName: "",
      lastName: "",
      fullName: "",
      dob: "",
      sex: "",
      nationality: "",
      placeOfBirth: "",
      passport: emptyPassport(),
      address: { line1: "", line2: "", city: "", state: "", pincode: "", country: "" },
      contact: { phone: "", email: "" },
    };
  }

  function emptyDocument(label, required) {
    return {
      id: utils.generateId("DOC"),
      label: label,
      required: !!required,
      status: "Missing", // Missing | Uploaded | Verified | Rejected
      fileRef: null, // key into KhannaDocumentFileStore (in-memory only, see that module)
      fileName: null,
      mimeType: null,
      uploadedAt: null,
      verifiedAt: null,
      verifiedBy: null,
      note: "", // e.g. rejection reason
    };
  }

  function emptyHotel() {
    return {
      id: utils.generateId("HTL"),
      hotelName: "",
      phone: "",
      address: "",
      city: "",
      confirmationNumber: "",
      leadGuestName: "",
      // Split from a single "noOfGuests" field on explicit request, so the
      // generated Hotel Voucher can print a real "2 Adult(s), 2 Child(s)"
      // combined count (see hotel_voucher_engine.py's _format_guest_counts()
      // on the backend) instead of one undifferentiated number.
      noOfAdults: "",
      noOfChildren: "",
      noOfRooms: "",
      roomType: "",
      checkIn: "",
      checkOut: "",
      guestNames: [], // extra guest-name lines for the voucher's guest table; empty = use leadGuestName only
      voucherGeneratedAt: null,
    };
  }

  function emptyCoverLetterHotel() {
    // Deliberately smaller than emptyHotel() above — this is only the
    // Japan Cover Letter's own 3-column hotel table (name/dates/contact
    // no.), not the full Hotel Blocking record used for the Hotel Voucher.
    return { id: utils.generateId("CLH"), name: "", checkIn: "", checkOut: "", contactNo: "" };
  }

  function createEmptyApplication(createdBy) {
    var ts = nowIso();
    return {
      id: utils.generateId("APP"),
      status: "Draft",
      createdBy: createdBy || "",
      createdAt: ts,
      updatedAt: ts,
      applicant: emptyPerson(),
      travellers: [], // each item: emptyPerson() + { id, relation }
      travel: {
        destination: "",
        visaCategory: "",
        purpose: "",
        countryOfResidence: "",
        startDate: "",
        endDate: "",
      },
      checklist: { destination: "", visaCategory: "", requiredDocs: [], supportingDocs: [], completionPct: 0 },
      documents: [],
      hotels: [],
      coverLetter: {
        // Phase 9 shape. `selectedPersonIds` holds "applicant" plus zero or
        // more traveller ids — Europe/Japan require exactly one companion
        // (their own reference templates' fixed wording assumes exactly
        // one), Singapore accepts the applicant alone or with any number
        // of companions (its passenger table is a genuinely repeatable
        // row). See cover_letter_engine.py's module docstring for the full
        // reasoning.
        region: "", // "" | "Europe" | "Japan" | "Singapore"
        selectedPersonIds: [],
        recipientText: "",
        destinationCountry: "",
        travelStartDate: "",
        travelEndDate: "",
        fundingArrangement: "",
        generatedAt: null,
        europe: {
          cityCountryOfResidence: "",
          numberOfNights: "",
          applicantEmploymentStatus: "",
          applicantJobTitle: "",
          applicantEmployerName: "",
          companionJobTitle: "",
          companionEmployerName: "",
          companionEmploymentStartYear: "",
          nextCountry: "",
          nextTravelStartDate: "",
          nextTravelEndDate: "",
          nextNumberOfNights: "",
        },
        japan: {
          applicantEmployerOccupation: "",
          companionOccupation: "",
          hotels: [], // { id, name, checkIn, checkOut, contactNo }
        },
        singapore: {
          hotelName: "",
          hotelAddress: "",
          occupations: {}, // keyed by personId ("applicant" or a traveller id)
        },
      },
      authorization: {
        // Phase 8 shape. `selectedPersonIds` holds "applicant" and/or
        // traveller ids; Passport Authorization supports 1-2 (matching the
        // two real reference templates), Company Authorization any number.
        passport: {
          selectedPersonIds: [],
          recipientCentreName: "",
          recipientAddress: "",
          collectorName: "",
          generatedAt: null,
        },
        company: {
          selectedPersonIds: [],
          recipientText: "",
          generatedAt: null,
        },
      },
      invitation: {
        // Phase 10 shape. The inviter is a person living abroad, entered
        // freely — NOT one of this application's own applicant/travellers
        // (Khanna isn't processing their visa) — while `selectedInviteeIds`
        // holds exactly 2 of this application's own people, matching the
        // real reference template's fixed "my Parents" wording (see
        // backend/python/invitation_letter_engine.py's module docstring).
        selectedInviteeIds: [],
        inviter: {
          fullName: "",
          addressLine1: "",
          addressLine2: "",
          cityPostcode: "",
          country: "",
          cityCountry: "",
          passportNumber: "",
          fullAddress: "",
          studyingOrWorking: "",
          universityOrCompany: "",
          phone: "",
          email: "",
        },
        travelStartDate: "",
        travelEndDate: "",
        purpose: "",
        accommodationDetails: "",
        returnDate: "",
        fundingArrangement: "",
        signatureFileRef: null, // key into KhannaDocumentFileStore (in-memory only)
        signatureFileName: null,
        generatedAt: null,
      },
      initorsLetters: {
        // Phase 10 shape. `selectedPersonIds` holds exactly 2 of this
        // application's own people — a married couple travelling together
        // — each of whom signs and submits their OWN letter, so the
        // per-person fields (occupation, relation to the inviting person,
        // signature) live in `perPerson`, keyed by personId, rather than
        // once at the top level.
        selectedPersonIds: [],
        invitingPerson: {
          fullName: "",
          passportNumber: "",
          countryOfResidence: "",
          visaResidenceStatus: "",
        },
        country: "",
        purpose: "",
        travelStartDate: "",
        travelEndDate: "",
        returnDate: "",
        accommodationDetails: "",
        otherCommitments: "",
        invitationSupportingDocuments: "",
        perPerson: {
          // keyed by personId -> { occupation, relationWithInvitingPerson,
          // signatureFileRef, signatureFileName, generatedAt }
        },
      },
      notes: [],
      activity: [{ ts: ts, type: "created", message: "Application created" }],
    };
  }

  /* ---------------------------------------------------------------------
   * Reusable Applicant/Traveller profile pool (Phase 2 of the
   * document-centric rebuild — 2026-09-25).
   *
   * Before this, an Application's `applicant` and each `travellers[]` entry
   * were data that existed ONLY inside that one Application record — the
   * exact same person had to be re-entered from scratch for every new
   * document/application. This adds a separate, shared pool of person
   * profiles ("APR"/"TPR" ids) that any document page can search and reuse,
   * per the explicit spec: "Applicant/Traveller Profile -> saved reusable
   * information -> Documents use this information".
   *
   * Deliberately NOT a breaking change: `application.applicant` and
   * `application.travellers[]` keep exactly their old shape and are still
   * what every document engine/controller reads today (project rule
   * "EXISTING DATA MUST REMAIN REUSABLE"). A profile is a denormalized
   * COPY of a person's data (same emptyPerson() shape, project rule 15 — no
   * second copy of that shape), linked back to the application via a plain
   * `applicantId` / traveller `profileId` string. `makeProfileStore()` is
   * one generic factory shared by both pools instead of two hand-written
   * copies of the same CRUD/search logic.
   * ------------------------------------------------------------------- */

  // Same person, same passport number (or, lacking that, same name+DOB) ==
  // same profile. This is the one place "is this the same person" is
  // decided, so both Applicant and Traveller pools — and the migration
  // below — agree on it.
  function profileDedupeKey(person) {
    var passportNo = person && person.passport && person.passport.current && person.passport.current.number;
    if (passportNo && String(passportNo).trim()) return "pp:" + String(passportNo).trim().toUpperCase();
    var full = person && person.fullName && person.fullName.trim();
    if (!full) return null;
    return "nd:" + full.toLowerCase() + "|" + ((person && person.dob) || "");
  }

  function personHasData(person) {
    if (!person) return false;
    var passportNo = person.passport && person.passport.current && person.passport.current.number;
    return !!((person.fullName && person.fullName.trim()) || (passportNo && String(passportNo).trim()));
  }

  function profileHaystack(p) {
    var passportNo = (p.passport && p.passport.current && p.passport.current.number) || "";
    var email = (p.contact && p.contact.email) || "";
    var country = (p.address && p.address.country) || "";
    return [p.fullName, passportNo, email, p.nationality, country].join(" ").toLowerCase();
  }

  function makeProfileStore(kind, storageKey) {
    var list = storage.get(storageKey, []);
    if (!Array.isArray(list)) list = [];

    function persistStore() {
      storage.set(storageKey, list);
    }

    function getAll() {
      return list
        .slice()
        .sort(function (a, b) {
          return new Date(b.updatedAt) - new Date(a.updatedAt);
        });
    }

    function get(id) {
      return (
        list.find(function (p) {
          return p.id === id;
        }) || null
      );
    }

    function findByPerson(person) {
      var key = profileDedupeKey(person);
      if (!key) return null;
      return (
        list.find(function (p) {
          return profileDedupeKey(p) === key;
        }) || null
      );
    }

    function search(query) {
      var q = (query || "").trim().toLowerCase();
      var all = getAll();
      if (!q) return all;
      return all.filter(function (p) {
        return profileHaystack(p).indexOf(q) !== -1;
      });
    }

    // Upserts by explicit id when given (an edit), else by dedupe match
    // (passport number / name+dob) so saving the same person twice updates
    // one profile instead of creating duplicates ("Do NOT duplicate
    // applicant data unnecessarily").
    function upsert(personData, id) {
      var existing = id ? get(id) : findByPerson(personData);
      var ts = nowIso();
      if (existing) {
        var merged = deepMerge(existing, personData);
        merged.updatedAt = ts;
        list = list.map(function (p) {
          return p.id === existing.id ? merged : p;
        });
        persistStore();
        notify();
        return merged;
      }
      var created = Object.assign(deepMerge(emptyPerson(), personData), {
        id: utils.generateId(kind === "traveller" ? "TPR" : "APR"),
        kind: kind,
        createdAt: ts,
        updatedAt: ts,
      });
      list.push(created);
      persistStore();
      notify();
      return created;
    }

    function remove(id) {
      var before = list.length;
      list = list.filter(function (p) {
        return p.id !== id;
      });
      persistStore();
      notify();
      return list.length !== before;
    }

    return { getAll: getAll, get: get, findByPerson: findByPerson, search: search, upsert: upsert, remove: remove };
  }

  var applicantProfiles = makeProfileStore("applicant", APPLICANT_PROFILES_KEY);
  var travellerProfiles = makeProfileStore("traveller", TRAVELLER_PROFILES_KEY);

  // Strips profile-only bookkeeping fields (id/kind/createdAt/updatedAt) so
  // the rest can be dropped straight into an application's applicant/
  // traveller person shape without leaking pool metadata onto it.
  function personDataFromProfile(profile) {
    var copy = Object.assign({}, profile);
    delete copy.id;
    delete copy.kind;
    delete copy.createdAt;
    delete copy.updatedAt;
    return copy;
  }

  // Called by the document-centric app-bar's "Use Existing Applicant"
  // picker: copies a saved profile's data onto the given application (which
  // is exactly what every existing document controller already reads from
  // `application.applicant`) and records the link.
  function applyApplicantProfileToApplication(appId, profileId) {
    var profile = applicantProfiles.get(profileId);
    if (!profile) return null;
    return updateApplication(
      appId,
      { applicant: personDataFromProfile(profile), applicantId: profile.id },
      'Applicant "' + (profile.fullName || "Untitled applicant") + '" applied from a saved profile'
    );
  }

  // Called right after the passport OCR/review flow saves an applicant onto
  // the active application (passport-processing.js) — mirrors that same
  // data into the reusable pool immediately, per spec ("Save Applicant ->
  // becomes reusable immediately across all document modules"), and links
  // the application to that profile going forward.
  function syncApplicantProfileFromApplication(appId) {
    var app = getApplication(appId);
    if (!app || !personHasData(app.applicant)) return null;
    var profile = applicantProfiles.upsert(app.applicant, app.applicantId || null);
    if (app.applicantId !== profile.id) {
      updateApplication(appId, { applicantId: profile.id });
    }
    return profile;
  }

  // Same idea, for one traveller entry within an application's own
  // `travellers[]` array.
  function syncTravellerProfileFromApplication(appId, travellerId) {
    var traveller = getTraveller(appId, travellerId);
    if (!traveller || !personHasData(traveller)) return null;
    var profile = travellerProfiles.upsert(traveller, traveller.profileId || null);
    if (traveller.profileId !== profile.id) {
      updateTraveller(appId, travellerId, { profileId: profile.id });
    }
    return profile;
  }

  // The reverse direction for travellers, mirroring applyApplicantProfileToApplication
  // above: called by the new "Use Existing Traveller" picker (travellers.js)
  // to add a saved traveller profile onto the current application as a new
  // traveller entry, instead of staff re-typing someone already on file
  // (this was the one explicitly-flagged remaining gap from Phase 2 — "no
  // picker UI yet to pull a saved traveller into a new application"). Always
  // APPENDS a new traveller (never overwrites an existing one) since an
  // application can have several travellers; `relation` lets the caller
  // override the profile's last-used relation label for this application
  // (the same person can be "Spouse" on one trip and "Colleague" on
  // another).
  function applyTravellerProfileToApplication(appId, profileId, relation) {
    var app = getApplication(appId);
    var profile = travellerProfiles.get(profileId);
    if (!app || !profile) return null;
    var traveller = Object.assign({}, personDataFromProfile(profile), {
      id: utils.generateId("TRV"),
      relation: relation || profile.relation || "",
      profileId: profile.id,
    });
    var travellers = (app.travellers || []).concat([traveller]);
    updateApplication(
      appId,
      { travellers: travellers },
      'Traveller "' + (profile.fullName || "Untitled traveller") + '" applied from a saved profile'
    );
    return traveller;
  }

  // One-time (per app record) backfill: applications saved before this pool
  // existed already have real applicant/traveller data embedded, just no
  // profileId/applicantId link yet. Every already-saved application must
  // stay fully usable (project rule "EXISTING DATA MUST REMAIN REUSABLE"),
  // so this links them into the pool rather than requiring re-entry.
  // Idempotent and cheap: only applications/travellers still missing a
  // link are touched, so this is a no-op on every load after the first.
  function migrateApplicantAndTravellerProfiles() {
    var changed = false;
    applications = applications.map(function (app) {
      var next = app;
      if (!next.applicantId && personHasData(next.applicant)) {
        var applicantProfile = applicantProfiles.upsert(next.applicant);
        next = Object.assign({}, next, { applicantId: applicantProfile.id });
        changed = true;
      }
      if (
        Array.isArray(next.travellers) &&
        next.travellers.some(function (t) {
          return !t.profileId && personHasData(t);
        })
      ) {
        next = Object.assign({}, next, {
          travellers: next.travellers.map(function (t) {
            if (t.profileId || !personHasData(t)) return t;
            var travellerProfile = travellerProfiles.upsert(t);
            return Object.assign({}, t, { profileId: travellerProfile.id });
          }),
        });
        changed = true;
      }
      return next;
    });
    if (changed) persist();
  }

  /* ---------------------------------------------------------------------
   * Persistence
   * ------------------------------------------------------------------- */

  function persist() {
    storage.set(APPLICATIONS_KEY, applications);
    storage.set(ACTIVE_KEY, activeApplicationId);
  }

  function notify() {
    subscribers.forEach(function (fn) {
      try {
        fn(getApplications());
      } catch (e) {
        /* a subscriber's own error must never break the store */
        console.error("KhannaState subscriber error:", e);
      }
    });
  }

  /* ---------------------------------------------------------------------
   * Public API
   * ------------------------------------------------------------------- */

  function init() {
    applications = storage.get(APPLICATIONS_KEY, []);
    if (!Array.isArray(applications)) applications = [];
    activeApplicationId = storage.get(ACTIVE_KEY, null);
    migrateApplicantAndTravellerProfiles();
  }

  function getApplications() {
    return applications
      .slice()
      .sort(function (a, b) {
        return new Date(b.updatedAt) - new Date(a.updatedAt);
      });
  }

  function getApplication(id) {
    return applications.find(function (a) {
      return a.id === id;
    }) || null;
  }

  function createApplication(createdBy) {
    var app = createEmptyApplication(createdBy);
    applications.push(app);
    activeApplicationId = app.id;
    persist();
    notify();
    return app;
  }

  function updateApplication(id, patch, activityMessage) {
    var index = applications.findIndex(function (a) {
      return a.id === id;
    });
    if (index === -1) return null;

    var merged = deepMerge(applications[index], patch);
    merged.updatedAt = nowIso();
    if (activityMessage) {
      merged.activity = (merged.activity || []).concat([
        { ts: merged.updatedAt, type: "update", message: activityMessage },
      ]);
    }
    applications[index] = merged;
    persist();
    notify();
    return merged;
  }

  function deleteApplication(id) {
    var before = applications.length;
    applications = applications.filter(function (a) {
      return a.id !== id;
    });
    if (activeApplicationId === id) activeApplicationId = null;
    persist();
    notify();
    return applications.length !== before;
  }

  /* ---------------------------------------------------------------------
   * Travellers (Phase 5) — each traveller is emptyPerson() + { id, relation }.
   * Implemented as read-modify-write over the parent Application's own
   * `travellers` array through updateApplication(), so every traveller
   * change goes through the same persist()/notify()/activity-log path as
   * everything else — no separate storage key to keep in sync.
   * ------------------------------------------------------------------- */

  function addTraveller(appId, relation) {
    var app = getApplication(appId);
    if (!app) return null;
    var traveller = Object.assign({}, emptyPerson(), {
      id: utils.generateId("TRV"),
      relation: relation || "",
    });
    var travellers = (app.travellers || []).concat([traveller]);
    updateApplication(appId, { travellers: travellers }, "Traveller added");
    return traveller;
  }

  function updateTraveller(appId, travellerId, patch, activityMessage) {
    var app = getApplication(appId);
    if (!app) return null;
    var travellers = (app.travellers || []).map(function (t) {
      return t.id === travellerId ? deepMerge(t, patch) : t;
    });
    return updateApplication(appId, { travellers: travellers }, activityMessage);
  }

  function removeTraveller(appId, travellerId) {
    var app = getApplication(appId);
    if (!app) return false;
    var before = (app.travellers || []).length;
    var travellers = (app.travellers || []).filter(function (t) {
      return t.id !== travellerId;
    });
    updateApplication(appId, { travellers: travellers }, "Traveller removed");
    return travellers.length !== before;
  }

  function getTraveller(appId, travellerId) {
    var app = getApplication(appId);
    if (!app) return null;
    return (app.travellers || []).find(function (t) {
      return t.id === travellerId;
    }) || null;
  }

  /* ---------------------------------------------------------------------
   * Checklist & documents (Phase 6). The DESTINATION/VISA-CATEGORY rules
   * (which labels are required vs supporting for a given trip) are domain
   * config that lives in js/documents/checklist-rules.js, not here — this
   * module only knows how to reconcile a resolved label list against the
   * Application's own `documents` array without ever silently discarding
   * an already-uploaded file, and how to keep `checklist.completionPct` in
   * sync whenever a document's status changes.
   * ------------------------------------------------------------------- */

  function computeCompletionPct(documents) {
    var required = (documents || []).filter(function (d) {
      return d.required;
    });
    if (required.length === 0) return 0;
    var verified = required.filter(function (d) {
      return d.status === "Verified";
    }).length;
    return Math.round((verified / required.length) * 100);
  }

  function syncChecklistDocuments(appId, destination, visaCategory, requiredLabels, supportingLabels) {
    var app = getApplication(appId);
    if (!app) return null;
    var existing = app.documents || [];

    function reconcile(labels, required) {
      return labels.map(function (label) {
        var found = existing.find(function (d) {
          return d.label === label;
        });
        if (found) {
          return found.required === required ? found : deepMerge(found, { required: required });
        }
        return emptyDocument(label, required);
      });
    }

    var current = reconcile(requiredLabels, true).concat(reconcile(supportingLabels, false));
    // A document that was uploaded under a previous checklist but no longer
    // matches the current required/supporting label set is kept, not
    // dropped — staff's uploaded file is real work, never discarded
    // silently — just marked not-required-by-the-current-checklist.
    var currentIds = current.map(function (d) {
      return d.id;
    });
    var orphaned = existing
      .filter(function (d) {
        return d.fileRef && currentIds.indexOf(d.id) === -1;
      })
      .map(function (d) {
        return deepMerge(d, { required: false });
      });

    var documents = current.concat(orphaned);
    return updateApplication(
      appId,
      {
        checklist: {
          destination: destination,
          visaCategory: visaCategory,
          requiredDocs: requiredLabels,
          supportingDocs: supportingLabels,
          completionPct: computeCompletionPct(documents),
        },
        documents: documents,
      },
      "Checklist generated for " + destination
    );
  }

  function updateDocument(appId, docId, patch, activityMessage) {
    var app = getApplication(appId);
    if (!app) return null;
    var documents = (app.documents || []).map(function (d) {
      return d.id === docId ? deepMerge(d, patch) : d;
    });
    return updateApplication(
      appId,
      { documents: documents, checklist: { completionPct: computeCompletionPct(documents) } },
      activityMessage
    );
  }

  /* ---------------------------------------------------------------------
   * Hotel blocking (Phase 7) — each hotel is emptyHotel(). Same
   * read-modify-write pattern over updateApplication() as travellers and
   * documents: no parallel storage key, every change goes through the one
   * persist()/notify()/activity-log path.
   * ------------------------------------------------------------------- */

  function addHotel(appId) {
    var app = getApplication(appId);
    if (!app) return null;
    var hotel = emptyHotel();
    var hotels = (app.hotels || []).concat([hotel]);
    updateApplication(appId, { hotels: hotels }, "Hotel added");
    return hotel;
  }

  function updateHotel(appId, hotelId, patch, activityMessage) {
    var app = getApplication(appId);
    if (!app) return null;
    var hotels = (app.hotels || []).map(function (h) {
      return h.id === hotelId ? deepMerge(h, patch) : h;
    });
    return updateApplication(appId, { hotels: hotels }, activityMessage);
  }

  function removeHotel(appId, hotelId) {
    var app = getApplication(appId);
    if (!app) return false;
    var before = (app.hotels || []).length;
    var hotels = (app.hotels || []).filter(function (h) {
      return h.id !== hotelId;
    });
    updateApplication(appId, { hotels: hotels }, "Hotel removed");
    return hotels.length !== before;
  }

  function getHotel(appId, hotelId) {
    var app = getApplication(appId);
    if (!app) return null;
    return (app.hotels || []).find(function (h) {
      return h.id === hotelId;
    }) || null;
  }

  function setActiveApplicationId(id) {
    activeApplicationId = id;
    persist();
  }

  function getActiveApplicationId() {
    return activeApplicationId;
  }

  function getActiveApplication() {
    return activeApplicationId ? getApplication(activeApplicationId) : null;
  }

  function getStats() {
    var counts = {};
    STATUSES.forEach(function (s) {
      counts[s] = 0;
    });
    applications.forEach(function (a) {
      if (counts[a.status] === undefined) counts[a.status] = 0;
      counts[a.status] += 1;
    });
    counts.total = applications.length;
    return counts;
  }

  function subscribe(fn) {
    subscribers.push(fn);
    return function unsubscribe() {
      subscribers = subscribers.filter(function (f) {
        return f !== fn;
      });
    };
  }

  global.KhannaState = {
    STATUSES: STATUSES,
    init: init,
    getApplications: getApplications,
    getApplication: getApplication,
    createApplication: createApplication,
    updateApplication: updateApplication,
    deleteApplication: deleteApplication,
    addTraveller: addTraveller,
    updateTraveller: updateTraveller,
    removeTraveller: removeTraveller,
    getTraveller: getTraveller,
    syncChecklistDocuments: syncChecklistDocuments,
    updateDocument: updateDocument,
    addHotel: addHotel,
    updateHotel: updateHotel,
    removeHotel: removeHotel,
    getHotel: getHotel,
    setActiveApplicationId: setActiveApplicationId,
    getActiveApplicationId: getActiveApplicationId,
    getActiveApplication: getActiveApplication,
    getStats: getStats,
    subscribe: subscribe,
    // exposed for other modules that need to build a fresh person record
    // (e.g. adding a traveller) without duplicating this shape elsewhere.
    createEmptyPerson: emptyPerson,
    // exposed for cover-letter.js's Japan hotel-table editor (Phase 9).
    createEmptyCoverLetterHotel: emptyCoverLetterHotel,

    // ---- Reusable Applicant/Traveller profile pool (Phase 2) ----
    getApplicantProfiles: applicantProfiles.getAll,
    getApplicantProfile: applicantProfiles.get,
    searchApplicantProfiles: applicantProfiles.search,
    saveApplicantProfile: applicantProfiles.upsert,
    deleteApplicantProfile: applicantProfiles.remove,
    applyApplicantProfileToApplication: applyApplicantProfileToApplication,
    syncApplicantProfileFromApplication: syncApplicantProfileFromApplication,

    getTravellerProfiles: travellerProfiles.getAll,
    getTravellerProfile: travellerProfiles.get,
    searchTravellerProfiles: travellerProfiles.search,
    saveTravellerProfile: travellerProfiles.upsert,
    deleteTravellerProfile: travellerProfiles.remove,
    syncTravellerProfileFromApplication: syncTravellerProfileFromApplication,
    applyTravellerProfileToApplication: applyTravellerProfileToApplication,
  };

  // Load persisted state immediately (synchronous, no DOM dependency) so
  // every other module's own DOMContentLoaded handler — regardless of
  // script order — sees real data on its very first render.
  init();
})(window);
