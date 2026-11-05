/* ==========================================================================
   Khanna Travels & Holidays — Document sorter (pure logic, no DOM)
   Decides which uploaded passports and hotel vouchers belong to the group
   of the main applicant whose name staff typed on the Upload Documents page.

   Honest scope (project rules 9, 10, 19): this is NAME MATCHING over text the
   OCR already extracted. It does not "know" who anybody is. Every decision it
   makes carries a confidence label and a short reason, and the page shows all
   of them to staff, who can move any document in or out of the group before
   anything is generated. A match is never presented as verified.

   Pure functions only, so the same file runs in the browser (window.
   KhannaDocumentSorter) and in a Node unit test (module.exports).
   ========================================================================== */
(function (root, factory) {
  "use strict";
  var api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.KhannaDocumentSorter = api;
})(typeof window !== "undefined" ? window : this, function () {
  "use strict";

  // Honorifics and filler words that appear in typed names / voucher guest
  // lines but are never part of the name itself.
  var STOP_TOKENS = {
    MR: 1, MRS: 1, MS: 1, MISS: 1, MSTR: 1, MASTER: 1, DR: 1, SHRI: 1, SMT: 1, SH: 1,
    SRI: 1, MD: 1, PROF: 1, ADULT: 1, CHILD: 1, GUEST: 1, LEAD: 1,
  };

  /** Uppercase, accent-free, letters-and-spaces-only name tokens (honorifics dropped). */
  function nameTokens(text) {
    if (text === null || text === undefined) return [];
    var cleaned = String(text)
      .normalize("NFD")
      .replace(/[̀-ͯ]/g, "")
      .toUpperCase()
      .replace(/[^A-Z\s]/g, " ");
    return cleaned
      .split(/\s+/)
      .filter(function (t) { return t && !STOP_TOKENS[t]; });
  }

  /** Levenshtein distance, capped: returns cap+1 as soon as it is exceeded. */
  function editDistance(a, b, cap) {
    if (a === b) return 0;
    if (Math.abs(a.length - b.length) > cap) return cap + 1;
    var prev = [];
    for (var j = 0; j <= b.length; j++) prev[j] = j;
    for (var i = 1; i <= a.length; i++) {
      var cur = [i];
      var rowMin = cur[0];
      for (var k = 1; k <= b.length; k++) {
        var cost = a[i - 1] === b[k - 1] ? 0 : 1;
        cur[k] = Math.min(prev[k] + 1, cur[k - 1] + 1, prev[k - 1] + cost);
        if (cur[k] < rowMin) rowMin = cur[k];
      }
      if (rowMin > cap) return cap + 1;
      prev = cur;
    }
    return prev[b.length];
  }

  /**
   * How well does `typed` token match `candidate` token?
   *  1    exact
   *  0.85 one OCR-style slip in a token of 5+ letters
   *  0.6  an initial ("R" for "RAJESH") — weak, never enough on its own
   *  0    otherwise
   */
  function tokenScore(typed, candidate) {
    if (typed === candidate) return 1;
    if (typed.length === 1 || candidate.length === 1) {
      return typed[0] === candidate[0] ? 0.6 : 0;
    }
    if (typed.length >= 5 && candidate.length >= 5 && editDistance(typed, candidate, 1) <= 1) return 0.85;
    // Same consonants, different vowels (SUNITA / SUNEETA, KAVITA / KAVEETA):
    // a common transliteration difference between a passport and a voucher.
    // Deliberately below "high" and never counted as a strong hit, so it
    // only ever supports a match that another name part already proves.
    if (typed.length >= 5 && candidate.length >= 5 && consonantSkeleton(typed) === consonantSkeleton(candidate)) return 0.7;
    return 0;
  }

  /** First letter + consonants only, doubled letters collapsed: SUNEETA -> SNT. */
  function consonantSkeleton(token) {
    return token.charAt(0) + token.slice(1).replace(/[AEIOUY]/g, "").replace(/(.)\1+/g, "$1");
  }

  /**
   * The token list plus, for each pair of neighbouring tokens, a version with
   * that pair run together: names are split differently on different
   * documents (RAJESHKUMAR / RAJESH KUMAR, ANITA DEVI / ANITADEVI).
   */
  function tokenVariants(tokens) {
    var out = [tokens];
    for (var i = 0; i + 1 < tokens.length; i++) {
      out.push(tokens.slice(0, i).concat([tokens[i] + tokens[i + 1]], tokens.slice(i + 2)));
    }
    return out;
  }

  /**
   * Scores how likely `candidateName` is the person typed as `typedName`.
   * Order-independent (passports print SURNAME before given names, people type
   * the other way round). Returns a number 0..1.
   *
   * Each typed token is matched to its best unused candidate token. The score
   * is the share of typed tokens found, slightly discounted when the passport
   * carries many more names than were typed (people usually leave out middle
   * names, so that discount is small). A single typed word is capped at
   * "medium" — a first name alone cannot be a confident match.
   */
  function nameMatchScore(typedName, candidateName) {
    var typed = nameTokens(typedName);
    var cand = nameTokens(candidateName);
    if (!typed.length || !cand.length) return 0;
    // Best score over the ways of splitting / joining neighbouring name parts.
    var best = 0;
    tokenVariants(typed).forEach(function (t) {
      tokenVariants(cand).forEach(function (c) {
        var s = scoreTokens(t, c, typed.length);
        if (s > best) best = s;
      });
    });
    return best;
  }

  function scoreTokens(typed, cand, typedWordCount) {

    var used = {};
    var typedTotal = 0;
    var strongHits = 0;
    var weakNameHits = 0; // matched only by the same-consonants rule
    typed.forEach(function (t) {
      var best = 0;
      var bestIdx = -1;
      cand.forEach(function (c, idx) {
        if (used[idx]) return;
        var s = tokenScore(t, c);
        if (s > best) { best = s; bestIdx = idx; }
      });
      if (bestIdx >= 0) {
        used[bestIdx] = true;
        typedTotal += best;
        if (best >= 0.85) strongHits++;
        else if (best === 0.7) weakNameHits++;
      }
    });
    // Initials alone are never evidence of the same person.
    if (strongHits === 0) return 0;
    var typedShare = typedTotal / typed.length;
    var candShare = Math.min(1, typedTotal / cand.length);
    var score = typedShare * (0.8 + 0.2 * candShare);
    // A single typed word (just a first name or just a surname) is never a
    // confident match for a whole passport name.
    if (typedWordCount < 2) score = Math.min(score, 0.7);
    // Same-consonants matches (SAMIR / SAMAR) can be two different people:
    // never "high", always left for staff to verify.
    if (weakNameHits > 0) score = Math.min(score, 0.8);
    return score;
  }

  var HIGH = 0.85;
  var MEDIUM = 0.6;

  function confidenceLabel(score) {
    if (score >= HIGH) return "high";
    if (score >= MEDIUM) return "medium";
    if (score > 0) return "low";
    return "none";
  }

  /** The name a passport record carries, in a single matchable string. */
  function passportDisplayName(p) {
    var given = (p && (p.givenNames || p.firstName)) || "";
    var sur = (p && (p.surname || p.lastName)) || "";
    return (given + " " + sur).replace(/\s+/g, " ").trim();
  }

  function sharedSurname(a, b) {
    var ta = nameTokens((a && (a.surname || a.lastName)) || "");
    var tb = nameTokens((b && (b.surname || b.lastName)) || "");
    if (!ta.length || !tb.length) return false;
    return ta.some(function (x) { return x.length >= 3 && tb.indexOf(x) >= 0; });
  }

  /**
   * Best score of `person` (a passport record) against any of the voucher's
   * guest names. Returns { score, guest }.
   */
  function bestGuestMatch(person, guestNames) {
    var name = passportDisplayName(person);
    var best = { score: 0, guest: null };
    (guestNames || []).forEach(function (g) {
      var s = nameMatchScore(name, g);
      if (s > best.score) best = { score: s, guest: g };
    });
    return best;
  }

  /**
   * Sorts uploaded documents around the main applicant.
   *
   * @param {string} typedName  main applicant name typed by staff
   * @param {Array} passports   [{ id, fileName, surname, givenNames, passportNumber, ... }]
   *                            (only passports whose OCR produced a name can be placed)
   * @param {Array} vouchers    [{ id, fileName, guestNames: [string] }]
   * @returns {{
   *   mainPassportId: string|null,
   *   mainScore: number,
   *   passports: Array<{id, role, score, confidence, reason, include}>,
   *   vouchers:  Array<{id, score, confidence, reason, include, matchedPassportId}>
   * }}
   *   role: "main" | "companion" | "unmatched" | "unreadable"
   *   `include` is only the pre-ticked default; the page lets staff change it.
   */
  function sortDocuments(typedName, passports, vouchers) {
    passports = passports || [];
    vouchers = vouchers || [];

    var scored = passports.map(function (p) {
      var hasName = nameTokens(passportDisplayName(p)).length > 0;
      return { passport: p, hasName: hasName, score: hasName ? nameMatchScore(typedName, passportDisplayName(p)) : 0 };
    });

    // Main applicant: the single best-scoring passport at or above MEDIUM.
    var main = null;
    scored.forEach(function (s) {
      if (s.score >= MEDIUM && (!main || s.score > main.score)) main = s;
    });
    var mainPassport = main ? main.passport : null;

    var passportResults = scored.map(function (s) {
      var p = s.passport;
      if (!s.hasName) {
        return { id: p.id, role: "unreadable", score: 0, confidence: "none", include: false,
          reason: "No name could be read from this file — check it and add the traveller manually." };
      }
      if (main && s === main) {
        return { id: p.id, role: "main", score: s.score, confidence: confidenceLabel(s.score), include: true,
          reason: "Name matches the main applicant" + (s.score < HIGH ? " (partial match — please verify)." : ".") };
      }
      var voucherLink = bestVoucherLink(p, vouchers);
      var sameFamily = mainPassport && sharedSurname(p, mainPassport);
      if (sameFamily && voucherLink.score >= MEDIUM) {
        return { id: p.id, role: "companion", score: 0.9, confidence: "high", include: true,
          reason: "Shares the surname and is listed on the same hotel voucher as the group." };
      }
      if (sameFamily) {
        return { id: p.id, role: "companion", score: 0.7, confidence: "medium", include: true,
          reason: "Shares a surname with the main applicant — assumed to be travelling together. Please verify." };
      }
      if (mainPassport && voucherLink.score >= MEDIUM && voucherLink.withMain) {
        return { id: p.id, role: "companion", score: 0.7, confidence: "medium", include: true,
          reason: "Named on a hotel voucher that also names the main applicant. Please verify." };
      }
      return { id: p.id, role: "unmatched", score: s.score, confidence: confidenceLabel(s.score), include: false,
        reason: main ? "Not linked to the main applicant by name or hotel voucher." : "Main applicant not found yet." };
    });

    var groupPassports = passports.filter(function (p) {
      var r = passportResults.filter(function (x) { return x.id === p.id; })[0];
      return r && r.include;
    });

    var voucherResults = vouchers.map(function (v) {
      var names = v.guestNames || [];
      if (!names.length) {
        return { id: v.id, score: 0, confidence: "none", include: false, matchedPassportId: null,
          reason: "No guest name could be read from this voucher — tick it manually if it belongs to this group." };
      }
      var best = { score: 0, passportId: null };
      groupPassports.forEach(function (p) {
        var m = bestGuestMatch(p, names);
        if (m.score > best.score) best = { score: m.score, passportId: p.id };
      });
      if (best.score >= MEDIUM) {
        return { id: v.id, score: best.score, confidence: confidenceLabel(best.score), include: true, matchedPassportId: best.passportId,
          reason: "Guest name matches a traveller in this group" + (best.score < HIGH ? " (partial — please verify)." : ".") };
      }
      // Fall back to the typed name directly (main passport may be unreadable).
      var typedBest = 0;
      names.forEach(function (g) { typedBest = Math.max(typedBest, nameMatchScore(typedName, g)); });
      if (typedBest >= MEDIUM) {
        return { id: v.id, score: typedBest, confidence: confidenceLabel(typedBest), include: true, matchedPassportId: null,
          reason: "Guest name matches the typed applicant name." };
      }
      return { id: v.id, score: Math.max(best.score, typedBest), confidence: confidenceLabel(Math.max(best.score, typedBest)),
        include: false, matchedPassportId: null,
        reason: "Guest names (" + names.slice(0, 3).join(", ") + ") do not match anyone in this group." };
    });

    return { mainPassportId: mainPassport ? mainPassport.id : null, mainScore: main ? main.score : 0,
      passports: passportResults, vouchers: voucherResults };
  }

  // How strongly passport `p` is named on any voucher, and whether the same
  // voucher also names the best-matching candidate for being the main person
  // (computed lazily by the caller through `withMain`, see below).
  function bestVoucherLink(p, vouchers) {
    var best = { score: 0, withMain: false };
    (vouchers || []).forEach(function (v) {
      var m = bestGuestMatch(p, v.guestNames);
      if (m.score > best.score) best = { score: m.score, withMain: !!v._namesMain };
    });
    return best;
  }

  /**
   * Marks, on each voucher, whether it names the typed main applicant, so
   * sortDocuments' "same voucher as the main applicant" rule can use it.
   * Kept separate (and called by sortDocuments' wrapper below) so the scoring
   * above stays readable.
   */
  function annotateVouchers(typedName, vouchers) {
    return (vouchers || []).map(function (v) {
      var names = v.guestNames || [];
      var namesMain = names.some(function (g) { return nameMatchScore(typedName, g) >= MEDIUM; });
      return Object.assign({}, v, { _namesMain: namesMain });
    });
  }

  function sort(typedName, passports, vouchers) {
    return sortDocuments(typedName, passports, annotateVouchers(typedName, vouchers));
  }

  return {
    nameTokens: nameTokens,
    nameMatchScore: nameMatchScore,
    confidenceLabel: confidenceLabel,
    passportDisplayName: passportDisplayName,
    sort: sort,
    THRESHOLDS: { high: HIGH, medium: MEDIUM },
  };
});
