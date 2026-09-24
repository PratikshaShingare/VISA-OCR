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

  function parseErrorResponse(response) {
    return response
      .json()
      .catch(function () {
        return null;
      })
      .then(function (body) {
        var detail = body && body.detail ? body.detail : "Request failed (HTTP " + response.status + ").";
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

  function checkHealth() {
    return request(API_BASE_URL + "/api/health", { method: "GET" });
  }

  function getPageCount(file) {
    var form = new FormData();
    form.append("file", file, file.name);
    return request(API_BASE_URL + "/api/passport/page-count", { method: "POST", body: form });
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

  global.KhannaApi = {
    API_BASE_URL: API_BASE_URL,
    checkHealth: checkHealth,
    getPageCount: getPageCount,
    processPassport: processPassport,
    downloadHotelVoucher: downloadHotelVoucher,
    downloadPassportAuthorization: downloadPassportAuthorization,
    downloadCompanyAuthorization: downloadCompanyAuthorization,
    downloadCoverLetter: downloadCoverLetter,
    downloadInvitationLetter: downloadInvitationLetter,
    downloadInitorsCoveringLetter: downloadInitorsCoveringLetter,
    exportApplicationsExcel: exportApplicationsExcel,
  };
})(window);
