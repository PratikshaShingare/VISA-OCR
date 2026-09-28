/* ==========================================================================
   Khanna Travels & Holidays — Backend API client
   Talks to the FastAPI backend (backend/python/app.py). Two supported
   deployments share this exact same file unmodified:
     - Local development: the backend runs on the SAME machine as the staff
       member using the app (see backend/python/README.md), reached at
       http://localhost:8000.
     - Vercel: the frontend and the backend's serverless functions are
       served from the SAME domain (see VERCEL_DEPLOYMENT.md), so every
       request is made relative to the page itself instead of a hardcoded
       host — there is no separate "production API URL" to configure.
   Which one applies is detected once, below, from the page's own origin.

   Started out OCR-only (Phase 4); now also serves document generation such
   as the Hotel Voucher (Phase 7), so errors here are phrased generically
   ("the backend"), not OCR-specific. No passport image, field, or booking
   detail is ever sent anywhere else.

   Honesty rule (project rule 9 — never fake functionality): every call here
   either resolves with a real backend result or rejects with a clear error.
   There is no client-side fallback that invents data when the backend is
   unreachable — the UI must show that failure plainly, not paper over it.
   ========================================================================== */
(function (global) {
  "use strict";

  function resolveApiBaseUrl() {
    var loc = global.location;
    var isLocalHost = !loc || loc.hostname === "localhost" || loc.hostname === "127.0.0.1" || loc.protocol === "file:";
    if (isLocalHost) {
      // Unchanged from before this app supported Vercel: the local backend
      // started via `uvicorn app:app --port 8000` (backend/python/README.md).
      return "http://localhost:8000";
    }
    // Any other real origin (a Vercel deployment's own domain) — the
    // frontend and the /api/* serverless functions are served from that
    // exact same domain, so requests go out relative to it, never to a
    // hardcoded host that would break the moment the deployment URL
    // changes (a new Vercel project, a custom domain, a preview
    // deployment, ...).
    return "";
  }

  var API_BASE_URL = resolveApiBaseUrl();

  function unreachableError() {
    var err = new Error(
      API_BASE_URL
        ? "Could not reach the local backend at " + API_BASE_URL + ". " +
          "Make sure it is running — see backend/python/README.md " +
          "(uvicorn app:app --port 8000)."
        : "Could not reach the backend API. If this deployment was just " +
          "updated, the serverless functions may still be starting — " +
          "try again in a moment."
    );
    err.isBackendUnreachable = true;
    return err;
  }

  // Phase 3 fix — traced a real "Request failed (HTTP 404)" bug report to
  // its actual root cause instead of just rephrasing the message.
  //
  // FastAPI itself ALWAYS returns a JSON body (`{"detail": "..."}`) for
  // every response this backend can produce, including its own built-in
  // 404 for an unmatched route (confirmed against the real running
  // app.py: `{"detail":"Not Found"}`, already surfaced by the `body.detail`
  // branch below). The ONLY way to hit the generic fallback message is a
  // response whose body ISN'T parseable JSON at all — proving whatever
  // answered this request was NOT this FastAPI backend.
  //
  // Reproduced two concrete ways this actually happens with a real browser
  // (not guessed — both confirmed end-to-end against this exact codebase):
  //   1. resolveApiBaseUrl() (below) only recognizes "localhost", "127.0.0.1"
  //      and file: as local — opening the app via any other address (a LAN
  //      IP, a machine hostname, an IDE Live-Server-style URL) makes it use
  //      a RELATIVE "" API base meant for a same-origin production
  //      deployment. Every "API" call then silently goes to the FRONTEND's
  //      own static server (Start Frontend.bat, port 8766) instead of the
  //      real backend — which has no /api/* routes and returns its own
  //      genuine, same-origin (so not CORS-blocked either) 404/501 with a
  //      plain HTML body. This is almost certainly what a real staff member
  //      hit: it reproduces the bare "Request failed (HTTP 404)" symptom
  //      exactly, with OCR doing nothing, and no console/CORS error to hint
  //      at why.
  //   2. Less likely locally (blocked by CORS in a real browser unless the
  //      impostor also sets permissive CORS headers, which most simple dev
  //      servers don't): a second local server occupying port 8000 instead
  //      of the real backend.
  // Both are covered below so this is right whichever one it turns out to
  // be, rather than only handling the one that happened to reproduce here.
  function parseErrorResponse(response) {
    return response
      .json()
      .catch(function () {
        return null;
      })
      .then(function (body) {
        var detail;
        if (body && body.detail) {
          detail = body.detail;
        } else if (body) {
          // Valid JSON, but not this backend's own error shape — some other
          // JSON API is answering here.
          detail =
            "Something answered at " + response.url + " (HTTP " + response.status + "), but its response " +
            "doesn't look like it came from the Khanna backend. Check that nothing else is using port 8000.";
        } else if (!API_BASE_URL) {
          // The single most likely cause, confirmed by reproduction (see
          // the comment above): API_BASE_URL is relative, so this request
          // went to the page's own origin, not the backend.
          detail =
            "This page was opened from an address (" + global.location.origin + ") this app doesn't recognize " +
            "as a local address, so it sent this request to itself instead of the real backend at " +
            "http://localhost:8000 (HTTP " + response.status + ", not from the Khanna backend). Open the app " +
            "using the exact address Start Frontend.bat prints — http://localhost:8766/index.html — not a LAN " +
            "IP, a different hostname, or an IDE's own preview URL.";
        } else {
          // Not JSON at all, and API_BASE_URL correctly pointed at
          // localhost:8000 — this is the "something else is using port
          // 8000" case (see comment above; less likely with a real browser
          // due to CORS, but not impossible).
          detail =
            "Unexpected response from " + response.url + " (HTTP " + response.status + "). This backend always " +
            "replies with real JSON, so something other than the Khanna backend is answering on this address — " +
            "most likely another program is already using port 8000. Close any other local server bound to " +
            "that port, make sure only \"Start Backend.bat\" is running, and try again.";
        }
        var err = new Error(detail);
        err.status = response.status;
        return err;
      });
  }

  function request(url, options) {
    return fetch(url, options).then(
      function (res) {
        if (!res.ok) {
          return parseErrorResponse(res).then(function (err) {
            throw err;
          });
        }
        return res.json();
      },
      function () {
        // fetch() itself rejected: network error, refused connection, CORS —
        // in this app's setup that almost always means the local server
        // simply isn't running.
        throw unreachableError();
      }
    );
  }

  // Phase 3: catches the "wrong server on this port" failure mode (see
  // parseErrorResponse's comment above) proactively, before staff ever get
  // as far as uploading a passport — a 200 OK with valid JSON that just
  // isn't THIS backend's own health shape (`service: "khanna-backend"`)
  // would otherwise look identical to a real, working connection.
  function checkHealth() {
    return request(API_BASE_URL + "/api/health", { method: "GET" }).then(function (body) {
      if (!body || body.service !== "khanna-backend") {
        var err = new Error(
          "Something is responding at " + API_BASE_URL + "/api/health, but it isn't the Khanna backend " +
          "(unexpected response). Check that nothing else is using port 8000 and that \"Start Backend.bat\" " +
          "is the server actually running there."
        );
        err.isWrongServer = true;
        throw err;
      }
      return body;
    });
  }

  function getPageCount(file) {
    var form = new FormData();
    form.append("file", file, file.name);
    return request(API_BASE_URL + "/api/passport/page-count", { method: "POST", body: form });
  }

  /**
   * Hotel Blocking's "Upload Hotel Voucher" (backend/python/hotel_voucher_ocr.py)
   * — extracts whatever fields can be found on a staff-uploaded hotel/OTA
   * voucher (image or PDF), for js/hotels.js to prefill into the already-
   * editable Hotel Blocking form fields. A sibling of processPassport()
   * above, not a variant — completely separate backend module, since a
   * hotel voucher shares nothing with passport MRZ/bio-data parsing beyond
   * the underlying image pipeline.
   * @param {File} file
   * @param {number} [pageIndex]
   */
  function processHotelVoucher(file, pageIndex) {
    var form = new FormData();
    form.append("file", file, file.name);
    form.append("page_index", String(pageIndex || 0));
    return request(API_BASE_URL + "/api/hotel-voucher/process", { method: "POST", body: form });
  }

  /**
   * @param {File} file
   * @param {number} pageIndex
   * @param {number|null} forcedRotation 0/90/180/270, or null to let the
   *   backend's own orientation detection decide.
   */
  function processPassport(file, pageIndex, forcedRotation) {
    var form = new FormData();
    form.append("file", file, file.name);
    form.append("page_index", String(pageIndex || 0));
    if (forcedRotation !== null && forcedRotation !== undefined) {
      form.append("forced_rotation", String(forcedRotation));
    }
    return request(API_BASE_URL + "/api/passport/process", { method: "POST", body: form });
  }

  /**
   * TESTING PATH — calls the separate OpenRouter vision-model OCR endpoint
   * (backend/python/openrouter_ocr.py) instead of the production Tesseract/
   * Google Vision pipeline above. Single image only (no PDF, no page
   * index/rotation) — see that module's docstring for why. The API key
   * lives only on the backend; nothing about it crosses into this file.
   * @param {File} file a JPG/PNG/WEBP image
   */
  function processPassportOpenRouter(file) {
    var form = new FormData();
    form.append("file", file, file.name);
    return request(API_BASE_URL + "/api/passport/process-openrouter", { method: "POST", body: form });
  }

  /**
   * Phase 3 fix — converts a .docx to PDF purely for inline preview (see
   * app.py's /api/documents/preview-convert docstring for why this exists:
   * a browser can't render .docx directly, and faking a preview is exactly
   * what project rule 9 forbids). Returns the PDF as a Blob the caller can
   * open with URL.createObjectURL — this never touches or replaces the
   * original file the caller already has.
   * @param {File} file a .docx File (e.g. from KhannaDocumentFileStore)
   * @returns {Promise<Blob>}
   */
  function previewConvertToPdf(file) {
    var form = new FormData();
    form.append("file", file, file.name);
    return fetch(API_BASE_URL + "/api/documents/preview-convert", { method: "POST", body: form }).then(
      function (res) {
        if (!res.ok) {
          return parseErrorResponse(res).then(function (err) {
            throw err;
          });
        }
        return res.blob();
      },
      function () {
        throw unreachableError();
      }
    );
  }

  /**
   * Shared plumbing for every document-generation endpoint (Hotel Voucher,
   * Passport Authorization, Company Authorization, and future cover/
   * invitation letters): POSTs a JSON payload and resolves with the raw
   * file blob + a suggested filename, extracted from the real
   * Content-Disposition header the backend sets. Unlike `request()` above
   * this does not parse the response as JSON — a successful response body
   * IS the file (.docx or .pdf) — but it follows the exact same honesty
   * rule: a network failure or non-2xx response always rejects with a
   * clear, real error, never a silently-empty file. Extracted in Phase 8
   * out of `downloadHotelVoucher`, which was the first caller to need it
   * (project rule 15 — avoid duplicated logic); that function's own
   * signature is unchanged, so hotels.js needed no edits.
   *
   * @param {string} path e.g. "/api/documents/hotel-voucher"
   * @param {Object} payload
   * @param {string} fallbackFilename used only if the response is somehow
   *   missing a Content-Disposition header
   */
  function downloadDocumentFile(path, payload, fallbackFilename) {
    return fetch(API_BASE_URL + path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }).then(
      function (res) {
        if (!res.ok) {
          return parseErrorResponse(res).then(function (err) {
            throw err;
          });
        }
        var disposition = res.headers.get("Content-Disposition") || "";
        var match = /filename="?([^"]+)"?/.exec(disposition);
        var filename = match ? match[1] : fallbackFilename;
        return res.blob().then(function (blob) {
          return { blob: blob, filename: filename };
        });
      },
      function () {
        throw unreachableError();
      }
    );
  }

  /**
   * Generates the Hotel Voucher document (Phase 7) for one or more hotels.
   * @param {Array} hotels
   * @param {"docx"|"pdf"} format
   * @param {string} [applicantName]
   */
  function downloadHotelVoucher(hotels, format, applicantName) {
    return downloadDocumentFile(
      "/api/documents/hotel-voucher",
      { hotels: hotels, format: format || "docx", applicantName: applicantName || null },
      "Hotel_Voucher." + (format || "docx")
    );
  }

  /**
   * Generates the Passport Authorization Letter (Phase 8) for 1-2
   * travellers — the backend enforces that limit itself (it matches the
   * two real reference templates on file), this is just the request shape.
   * @param {Object} payload { people, recipientCentreName, recipientAddress, collectorName, dateOverride, format, applicantName }
   */
  function downloadPassportAuthorization(payload) {
    return downloadDocumentFile(
      "/api/documents/passport-authorization",
      payload,
      "Passport_Authorization." + (payload.format || "docx")
    );
  }

  /**
   * Generates the Company Authorization Letter (Phase 8) for any number of
   * applicants.
   * @param {Object} payload { people, recipientText, dateOverride, format, applicantName }
   */
  function downloadCompanyAuthorization(payload) {
    return downloadDocumentFile(
      "/api/documents/company-authorization",
      payload,
      "Company_Authorization." + (payload.format || "docx")
    );
  }

  /**
   * Generates a Cover Letter (Phase 9) — Europe/Japan/Singapore, discriminated
   * by `payload.region`. The backend itself enforces each region's real
   * person-count limit (Europe/Japan: applicant + exactly 1 companion;
   * Singapore: applicant alone or + any number), matching what each
   * region's own reference template's fixed wording actually supports.
   * @param {Object} payload { region, people, recipientText, destinationCountry,
   *   travelStartDate, travelEndDate, fundingArrangement, dateOverride, format,
   *   applicantName, ...region-specific fields (see backend/python/app.py) }
   */
  function downloadCoverLetter(payload) {
    return downloadDocumentFile(
      "/api/documents/cover-letter",
      payload,
      (payload.region || "Cover_Letter") + "_Cover_Letter." + (payload.format || "docx")
    );
  }

  /**
   * Shared plumbing for the two Phase 10 document endpoints that take a
   * real file upload alongside their structured data (a staff-uploaded
   * signature image, embedded via docx_utils.insert_signature_image) — a
   * new pattern, not a duplicate of downloadDocumentFile() above: those
   * endpoints are multipart/form-data (the JSON payload carried in a
   * `payload` form field, per backend/python/app.py) rather than a plain
   * JSON body, so a signature file part can ride alongside it. Same
   * honesty rule as every download helper here: a network failure or
   * non-2xx response always rejects with a clear, real error.
   *
   * @param {string} path e.g. "/api/documents/invitation-letter"
   * @param {Object} payloadObject
   * @param {File|null} signatureFile omit/pass null when no signature was
   *   uploaded — the backend and the generator engines both already treat
   *   that as "leave the template's own blank signature slot blank"
   *   (project rule 9 — never a fabricated signature)
   * @param {string} fallbackFilename
   */
  function downloadDocumentFileMultipart(path, payloadObject, signatureFile, fallbackFilename) {
    var form = new FormData();
    form.append("payload", JSON.stringify(payloadObject));
    if (signatureFile) form.append("signature", signatureFile, signatureFile.name);

    return fetch(API_BASE_URL + path, { method: "POST", body: form }).then(
      function (res) {
        if (!res.ok) {
          return parseErrorResponse(res).then(function (err) {
            throw err;
          });
        }
        var disposition = res.headers.get("Content-Disposition") || "";
        var match = /filename="?([^"]+)"?/.exec(disposition);
        var filename = match ? match[1] : fallbackFilename;
        return res.blob().then(function (blob) {
          return { blob: blob, filename: filename };
        });
      },
      function () {
        throw unreachableError();
      }
    );
  }

  /**
   * Generates the Invitation Letter (Phase 10) for exactly 2 invitees,
   * with an optional staff-uploaded signature image. The backend enforces
   * the 2-invitee limit itself (it matches the real reference template's
   * own fixed "my Parents" wording).
   * @param {Object} payload { inviter, invitees, travelStartDate, travelEndDate,
   *   purpose, accommodationDetails, returnDate, fundingArrangement, dateOverride,
   *   format, applicantName }
   * @param {File|null} signatureFile
   */
  function downloadInvitationLetter(payload, signatureFile) {
    return downloadDocumentFileMultipart(
      "/api/documents/invitation-letter",
      payload,
      signatureFile || null,
      "Invitation_Letter." + (payload.format || "docx")
    );
  }

  /**
   * Generates ONE Initors Covering Letter (Phase 10) — for exactly one of
   * the two married travellers (`payload.subject`), naming the other as
   * `payload.spouse`, since each spouse signs and submits their own
   * letter. The backend itself picks the right gendered-voice reference
   * template from `subject.sex` (M/F) and rejects anything else — see
   * invitation_letter_engine.py's module docstring.
   * @param {Object} payload { subject, spouse, invitingPerson, country, purpose,
   *   travelStartDate, travelEndDate, returnDate, accommodationDetails,
   *   otherCommitments, invitationSupportingDocuments, dateOverride, format,
   *   applicantName }
   * @param {File|null} signatureFile
   */
  function downloadInitorsCoveringLetter(payload, signatureFile) {
    return downloadDocumentFileMultipart(
      "/api/documents/initors-covering-letter",
      payload,
      signatureFile || null,
      "Initors_Covering_Letter." + (payload.format || "docx")
    );
  }

  /**
   * Phase 11 — Master Excel export. This app has no backend datastore for
   * Application records (they live in the browser's own localStorage — see
   * state.js's header comment), so the frontend posts its current
   * `KhannaState.getApplications()` array and the backend turns it into a
   * real, multi-sheet .xlsx workbook (backend/python/admin_export_engine.py)
   * and streams it straight back — same shape as every other document
   * download, built on the same shared helper (project rule 15).
   * @param {Array} applications
   */
  function exportApplicationsExcel(applications) {
    return downloadDocumentFile(
      "/api/admin/export-excel",
      { applications: applications || [] },
      "Khanna_Applications_Export.xlsx"
    );
  }

  /**
   * Required Document Letter module — real, static reference data for the
   * country dropdown/typeahead, the expanded visa-type and employment-
   * status lists, the bank-statement/ITR/processing-time pick-lists, and
   * the full document catalog (every checkbox this letter can ever show).
   * A plain GET, not a document download.
   */
  function getVisaCountries() {
    return request(API_BASE_URL + "/api/visa-requirements/countries", { method: "GET" });
  }

  /**
   * Returns which document catalog ids should be PRE-CHECKED for a given
   * enquiry (the structured rule-engine result from
   * visa_requirements_data.resolve_suggested_document_ids) — still just a
   * suggestion; checklist-letter.js renders every id as an editable
   * checkbox and only sends back whatever is actually still checked.
   * @param {Object} args { visaType, employmentStatus, invited, hasUsVisaCopy, country }
   */
  function getSuggestedDocuments(args) {
    args = args || {};
    var params = ["visaType=" + encodeURIComponent(args.visaType || "")];
    if (args.employmentStatus) params.push("employmentStatus=" + encodeURIComponent(args.employmentStatus));
    if (args.invited) params.push("invited=true");
    if (args.hasUsVisaCopy) params.push("hasUsVisaCopy=true");
    if (args.country) params.push("country=" + encodeURIComponent(args.country));
    return request(API_BASE_URL + "/api/visa-requirements/suggested-documents?" + params.join("&"), { method: "GET" });
  }

  /**
   * Looks up whatever REAL, sourced figures this app currently has for one
   * exact country+visaType combination (see backend/python/
   * visa_requirements_data.py's own module docstring for how narrow that
   * currently is). Resolves with an EMPTY object when nothing has been
   * verified — never a guessed number (project rule 9) — the caller (
   * checklist-letter.js) treats that as "show 'Check current official
   * requirement'," not as an error.
   * @param {string} country
   * @param {string} visaType "Transit" | "Tourist" | "Business"
   */
  function lookupVisaRequirement(country, visaType) {
    var qs = "?country=" + encodeURIComponent(country) + "&visaType=" + encodeURIComponent(visaType);
    return request(API_BASE_URL + "/api/visa-requirements/lookup" + qs, { method: "GET" });
  }

  /**
   * Generates the Required Document Letter — a standalone checklist letter
   * (no Applicant/Traveller record required). `documentIds` is the final,
   * staff-editable list of checked catalog ids — the backend resolves each
   * id to its real label (substituting bank-statement/ITR dynamic values)
   * via visa_requirements_data.py's own rule engine; nothing is invented
   * frontend-side.
   * @param {Object} payload { country, visaType, employmentStatus,
   *   documentIds, bankStatementDuration, itrYears, processingTime,
   *   visaFees, format, applicantName }
   */
  function downloadRequiredDocumentLetter(payload) {
    return downloadDocumentFile(
      "/api/documents/required-document-letter",
      payload,
      "Required_Document_Letter." + (payload.format || "docx")
    );
  }

  global.KhannaApi = {
    API_BASE_URL: API_BASE_URL,
    checkHealth: checkHealth,
    getPageCount: getPageCount,
    processPassport: processPassport,
    processPassportOpenRouter: processPassportOpenRouter,
    previewConvertToPdf: previewConvertToPdf,
    downloadHotelVoucher: downloadHotelVoucher,
    processHotelVoucher: processHotelVoucher,
    downloadPassportAuthorization: downloadPassportAuthorization,
    downloadCompanyAuthorization: downloadCompanyAuthorization,
    downloadCoverLetter: downloadCoverLetter,
    downloadInvitationLetter: downloadInvitationLetter,
    downloadInitorsCoveringLetter: downloadInitorsCoveringLetter,
    exportApplicationsExcel: exportApplicationsExcel,
    getVisaCountries: getVisaCountries,
    getSuggestedDocuments: getSuggestedDocuments,
    lookupVisaRequirement: lookupVisaRequirement,
    downloadRequiredDocumentLetter: downloadRequiredDocumentLetter,
  };
})(window);
