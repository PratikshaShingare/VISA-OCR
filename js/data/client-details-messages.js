/* ==========================================================================
   Khanna Travels & Holidays — "basic details" messages sent to the client

   For each visa form there is one fixed message the team sends to the client
   (WhatsApp / email) asking for the details the passport does not show. This
   file holds:
     - the message wording, per country, exactly as the team writes it;
     - which Applicant Profile field each answer belongs to;
     - read(text): reads the client's reply (the same message with the
       answers typed in) back into those fields.

   Adding a country = adding one entry to COUNTRIES (wording + items). Every
   item points at a profile field ("contact.phone", "details.religion", …);
   the reader knows all items of all countries, so a reply is understood
   whichever message it answers.

   The reader never decides on its own: what it read is shown to staff to
   check and correct before anything is saved (project rules 10 and 19).
   ========================================================================== */
(function (global) {
  "use strict";

  /*
   * Items: label (as printed in the message), field (profile path), aliases
   * (other ways a client may write the label), kind (how the answer is
   * tidied), question (label is a question: the answer may follow the "?").
   */
  var COUNTRIES = [
    {
      id: "singapore",
      label: "Singapore",
      intro: "Please help me with below details for Singapore Visa form filling - ",
      bullet: function (i) { return i + 1 + ") "; },
      separator: ": ",
      items: [
        { label: "Email Address", field: "contact.email", kind: "email", aliases: ["email address", "email id", "email", "e-mail", "mail id"] },
        { label: "Contact Number", field: "contact.phone", kind: "phone", aliases: ["contact number", "contact no", "mobile number", "mobile no", "phone number", "phone no", "mobile", "phone"] },
        { label: "Occupation", field: "details.occupation", kind: "text", aliases: ["occupation", "profession"] },
        { label: "Highest Qualifications Attained", field: "details.education", kind: "text", aliases: ["highest qualifications attained", "highest qualification attained", "highest qualifications", "highest qualification", "qualifications", "qualification", "education"] },
        { label: "Annual Income in Singapore dollars", field: "details.annualIncomeSgd", kind: "amount", aliases: ["annual income in singapore dollars", "annual income in singapore dollar", "annual income in sgd", "annual income sgd", "annual income"] },
        { label: "Religion", field: "details.religion", kind: "text", aliases: ["religion"] },
        {
          label: "Did you reside in other countries/places, other than your country/place of origin, for one year or more during the last 5 years?",
          field: "details.residedAbroad",
          kind: "yesNoText",
          question: true,
          noSeparator: true,
          aliases: ["did you reside in other countries", "did you reside", "reside in other countries", "resided in other countries"],
        },
      ],
    },
    {
      id: "japan",
      label: "Japan",
      intro: "Please share details for Japan Visa form filling- ",
      bullet: function () { return "* "; },
      separator: " - ",
      items: [
        { label: "Phone No", field: "contact.phone", kind: "phone", aliases: ["phone no", "phone number", "phone", "mobile no", "mobile number", "mobile", "contact number", "contact no"] },
        { label: "Email ID", field: "contact.email", kind: "email", aliases: ["email id", "email address", "email", "e-mail", "mail id"] },
        { label: "Occupation", field: "details.occupation", kind: "text", aliases: ["occupation", "profession"] },
        { label: "Married", field: "details.maritalStatus", kind: "marital", aliases: ["married", "marital status"] },
        { label: "Ever visited Japan Visa", field: "details.visitedJapan", kind: "yesNoText", aliases: ["ever visited japan visa", "ever visited japan", "visited japan before", "visited japan", "previous visit to japan", "previous japan visa"] },
        { label: "Sponsor Phone Number", field: "details.sponsorPhone", kind: "phone", aliases: ["sponsor phone number", "sponsors phone number", "sponsor's phone number", "sponsor phone no", "sponsor phone", "sponsor mobile number", "sponsor mobile", "sponsor contact number"] },
        { label: "Sponsor Email id", field: "details.sponsorEmail", kind: "email", aliases: ["sponsor email id", "sponsors email id", "sponsor's email id", "sponsor email address", "sponsor email"] },
        { label: "Sponsors Occupation", field: "details.sponsorOccupation", kind: "text", aliases: ["sponsors occupation", "sponsor occupation", "sponsor's occupation", "sponsor profession"] },
      ],
    },
  ];

  var NAME_ALIASES = ["applicant name", "applicants name", "applicant's name", "name of applicant", "name"];

  var MARITAL = { married: "Married", single: "Single", unmarried: "Single", divorced: "Divorced", widowed: "Widowed", widow: "Widowed", separated: "Separated" };

  function s(v) {
    return v === null || v === undefined ? "" : String(v).trim();
  }

  function byId(id) {
    return COUNTRIES.filter(function (c) { return c.id === id; })[0] || null;
  }

  /* ---------------------------------------------------------------------
   * The message
   * ------------------------------------------------------------------- */

  /** The message for one country; `names` = applicant names (one block each; none = a blank name line). */
  function message(countryId, names) {
    var c = byId(countryId);
    if (!c) return "";
    var list = (names || []).map(s).filter(Boolean);
    if (!list.length) list = [""];
    var blocks = list.map(function (name) {
      return (
        "Applicant Name: " + name + "\n\n" +
        c.items.map(function (it, i) {
          return c.bullet(i) + it.label + (it.noSeparator ? "" : c.separator.replace(/\s+$/, " "));
        }).join("\n")
      );
    });
    return c.intro + "\n\n" + blocks.join("\n\n") + "\n";
  }

  /* ---------------------------------------------------------------------
   * Reading the reply
   * ------------------------------------------------------------------- */

  // "Email Address" -> /^email[\W_]*address(?![a-z])/i — tolerant of the
  // punctuation, spacing and apostrophes clients add or drop.
  function aliasPattern(alias) {
    var words = alias.toLowerCase().replace(/'/g, "").split(/[^a-z0-9]+/).filter(Boolean);
    return new RegExp("^" + words.map(function (w) { return w.replace(/s$/, "") + "s?'?s?"; }).join("[\\W_]*") + "(?![a-z0-9])", "i");
  }

  var MATCHERS = (function () {
    var list = [];
    var seen = {};
    COUNTRIES.forEach(function (c) {
      c.items.forEach(function (it) {
        it.aliases.concat([it.label]).forEach(function (a) {
          var key = it.field + "|" + a.toLowerCase();
          if (seen[key]) return;
          seen[key] = true;
          list.push({ alias: a, re: aliasPattern(a), item: it });
        });
      });
    });
    // Longest label first: "sponsor phone number" before "phone number".
    list.sort(function (a, b) { return b.alias.length - a.alias.length; });
    return list;
  })();

  var NAME_RES = NAME_ALIASES.map(aliasPattern);

  // WhatsApp copies start each line with "[12/11/26, 10:30 am] Name: " or
  // "12/11/26, 10:30 am - Name: "; the bullets/numbers of the message itself
  // ("1)", "*", "-", "•") are dropped too.
  function cleanLine(line) {
    var t = String(line || "").replace(/\u200e|\u200f|\u202a|\u202c/g, "");
    t = t.replace(/^\s*\[\d{1,2}[\/.\-]\d{1,2}[\/.\-]\d{2,4},?[^\]]*\]\s*[^:]{1,40}:\s*/, "");
    t = t.replace(/^\s*\d{1,2}[\/.\-]\d{1,2}[\/.\-]\d{2,4},?\s+\d{1,2}:\d{2}(?:\s*[ap]\.?m\.?)?\s+-\s+[^:]{1,40}:\s*/i, "");
    // Stray quotes / marks OCR leaves at the start of a wrapped line ("'more during …").
    t = t.replace(/^[\s'‘’"“”`´|]+/, "");
    // "1)", "1.", "1:", and OCR's "1}", "1]", "l)" for the numbers of the message.
    t = t.replace(/^\s*(?:[*•●▪◦·>]+|[-–—]+(?=\s)|\(?(?:\d{1,2}|[lI])\s*[).:}\]]|\d{1,2}\s+[-–])\s*/, "");
    t = t.replace(/\*+/g, ""); // WhatsApp bold
    return t.trim();
  }

  function afterLabel(rest, item, wholeLabel) {
    var r = rest;
    // wholeLabel: the line held the complete question, so whatever follows is the answer.
    if (item.question && !(wholeLabel && r.indexOf("?") === -1)) {
      // The label is a long question: the answer is what follows its "?".
      var q = r.lastIndexOf("?");
      if (q !== -1) r = r.slice(q + 1);
      else {
        // No "?" on this line: either "… last 5 years No" or the question
        // goes on to the next line (a wrapped screenshot / message).
        var y = r.match(/\blast\s*(?:5|five)\s*y[e3]ars?\b/i);
        if (!y) return { value: "", questionGoesOn: true };
        r = r.slice(y.index + y[0].length);
      }
    }
    return { value: r.replace(/^[\s:\-–—=?.)>]+/, "").trim() };
  }

  function editDistance(a, b) {
    var prev = [];
    var i, j;
    for (j = 0; j <= b.length; j++) prev[j] = j;
    for (i = 1; i <= a.length; i++) {
      var cur = [i];
      for (j = 1; j <= b.length; j++) {
        cur[j] = Math.min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (a.charAt(i - 1) === b.charAt(j - 1) ? 0 : 1));
      }
      prev = cur;
    }
    return prev[b.length];
  }

  function letters(text) {
    return String(text || "").toLowerCase().replace(/[^a-z0-9]+/g, " ").trim();
  }

  function labelHit(item, rest, wholeLabel) {
    var after = afterLabel(rest, item, wholeLabel);
    return { item: item, value: after.value, questionGoesOn: !!after.questionGoesOn };
  }

  function matchLabel(line) {
    var i;
    for (i = 0; i < MATCHERS.length; i++) {
      var m = line.match(MATCHERS[i].re);
      if (m) return labelHit(MATCHERS[i].item, line.slice(m[0].length), MATCHERS[i].alias === MATCHERS[i].item.label);
    }
    // Screenshots read by OCR: a label with a letter or two wrong
    // ("Emall Address", "Contact Nurnber"). The label is what comes before
    // the ":" / " - "; it must be close to a known label.
    var sep = line.match(/^(.{4,60}?)\s*(?::|\s[-–—]\s|\s[-–—]$|[-–—]\s)([\s\S]*)$/);
    if (!sep) return null;
    var head = letters(sep[1]);
    if (head.length < 4) return null;
    var best = null;
    var bestDist = 99;
    for (i = 0; i < MATCHERS.length; i++) {
      if (MATCHERS[i].item.question) continue;
      var alias = letters(MATCHERS[i].alias);
      if (alias.length < 5) continue;
      var d = editDistance(head, alias);
      if (d <= Math.max(1, Math.floor(alias.length * 0.2)) && d < bestDist) {
        best = MATCHERS[i];
        bestDist = d;
      }
    }
    return best ? labelHit(best.item, sep[2]) : null;
  }

  function matchName(line) {
    for (var i = 0; i < NAME_RES.length; i++) {
      var m = line.match(NAME_RES[i]);
      if (m) {
        var rest = line.slice(m[0].length);
        // "Name" alone must be followed by ":" or "-" to count as the name line.
        if (i === NAME_RES.length - 1 && !/^\s*[:\-–—]/.test(rest)) return null;
        return rest.replace(/^[\s:\-–—=.]+/, "").trim();
      }
    }
    return null;
  }

  function isBlankAnswer(v) {
    return !v || /^[-–—_.]+$/.test(v);
  }

  function yesNoText(v) {
    var t = s(v).replace(/\.$/, "");
    if (/^(no|nope|never|nil|none|n|not\s+(yet|visited|applicable)|na|n\/a)\b/i.test(t) && t.split(/\s+/).length <= 3) return { value: "No" };
    var m = t.match(/^(yes|yeah|yep|y)\b[\s,.:;\-–—]*(.*)$/i);
    if (m) return { value: m[2] ? "Yes — " + m[2] : "Yes" };
    return { value: t };
  }

  function tidy(item, raw) {
    var v = s(raw).replace(/\s+/g, " ");
    switch (item.kind) {
      case "email": {
        var mail = v.replace(/^mailto:/i, "").replace(/\s+/g, "").replace(/,(?=[a-z]{2,4}$)/i, ".").toLowerCase();
        return /^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(mail) ? { value: mail } : { value: mail, note: "Does not look like an email address" };
      }
      case "phone": {
        var digits = v.replace(/[^\d]/g, "");
        return digits.length >= 8 ? { value: v.replace(/[^\d+\s-]/g, "").trim() } : { value: v, note: "Does not look like a phone number" };
      }
      case "amount": {
        var amount = v.replace(/\b(sgd|s\$|singapore dollars?|dollars?|approx\.?|approximately|around|about|per\s+annum|p\.?a\.?|yearly|annually)\b/gi, "").replace(/\$/g, "").trim();
        return /\d/.test(amount) ? { value: amount.replace(/^[,.\s]+|[,.\s]+$/g, "") } : { value: v, note: "No amount found" };
      }
      case "marital": {
        var word = v.toLowerCase().replace(/[^a-z ]/g, "").trim();
        if (/^(yes|y|yeah)\b/.test(word)) return { value: "Married" };
        if (/^(no|n|nope)\b/.test(word)) return { value: "Single", note: "\"No\" was read as Single — change it if divorced / widowed" };
        var first = word.split(" ")[0];
        return MARITAL[first] ? { value: MARITAL[first] } : { value: v, note: "Not understood — choose the marital status" };
      }
      case "yesNoText":
        return yesNoText(v);
      default:
        return { value: v };
    }
  }

  // An email address / an Indian (or international) phone number anywhere in a line.
  var EMAIL_RE = /[A-Za-z0-9._%+-]+\s*@\s*[A-Za-z0-9-]+(?:\s*[.,]\s*[A-Za-z0-9-]+)+/;
  var PHONE_RE = /(?:\+|00)?(?:\d[\s-]?){10,13}\d?/;

  /**
   * The email / phone answer left empty while the reply does hold one
   * elsewhere — on a line no label claimed (a screenshot read by OCR can put
   * a value on its own line, away from its label). Used only when exactly one
   * such value is there, and flagged for checking.
   */
  function findLooseContacts(a, unread) {
    var pool = a.loose || [];
    [["contact.email", EMAIL_RE, "email"], ["contact.phone", PHONE_RE, "phone"]].forEach(function (spec) {
      var field = spec[0];
      var e = a.raw[field];
      if (e && e.value) return;
      var found = [];
      pool.forEach(function (line) {
        var m = line.match(spec[1]);
        if (m && found.indexOf(m[0]) === -1) found.push(m[0]);
      });
      // Not a value already given to the sponsor.
      var sponsor = a.raw[field === "contact.email" ? "details.sponsorEmail" : "details.sponsorPhone"];
      found = found.filter(function (v) { return !(sponsor && sponsor.value && sponsor.value.replace(/\s/g, "") === v.replace(/\s/g, "")); });
      if (found.length !== 1) return;
      var item = e ? e.item : COUNTRIES[0].items.filter(function (it) { return it.field === field; })[0];
      a.raw[field] = { item: item, value: found[0], note: "Found in the reply, not next to its label — please check" };
      if (a.order.indexOf(field) === -1) a.order.unshift(field);
      pool.forEach(function (line) {
        var i = unread.indexOf(line);
        if (i !== -1 && line.replace(spec[1], "").replace(/[^A-Za-z0-9]/g, "") === "") unread.splice(i, 1);
      });
    });
  }

  /**
   * Reads a reply. Returns { applicants: [{ name, values: {field: value},
   * rows: [{ label, field, value, note }] }], unread: [lines not understood] }.
   * One applicant per "Applicant Name" line (or one unnamed applicant).
   */
  function read(text) {
    var lines = String(text || "").replace(/\r/g, "").split("\n").map(cleanLine);
    var applicants = [];
    var unread = [];
    var cur = null;
    var last = null; // { item } waiting for / continuing an answer

    function current() {
      if (!cur) {
        cur = { name: "", raw: {}, order: [], loose: [] };
        applicants.push(cur);
      }
      return cur;
    }

    lines.forEach(function (line) {
      if (!line) return;
      var name = matchName(line);
      if (name !== null) {
        // A new block — unless the open one has neither a name nor answers yet.
        if (cur && !cur.name && !cur.order.length) cur.name = name;
        else {
          cur = { name: name, raw: {}, order: [], loose: [] };
          applicants.push(cur);
        }
        last = name ? null : { name: true };
        return;
      }
      var hit = matchLabel(line);
      if (hit) {
        var a = current();
        if (a.order.indexOf(hit.item.field) === -1) a.order.push(hit.item.field);
        a.raw[hit.item.field] = { item: hit.item, value: isBlankAnswer(hit.value) ? "" : hit.value };
        last = { item: hit.item, questionGoesOn: hit.questionGoesOn };
        return;
      }
      // The rest of a question that wrapped onto this line: the answer follows its "?".
      if (last && last.questionGoesOn) {
        var q = line.lastIndexOf("?");
        var shortAnswer = /^(yes|no|nope|never|nil|none|y|n)\b/i.test(line) && line.split(/\s+/).length <= 8;
        if (q !== -1 || shortAnswer) {
          var answer = q !== -1 ? line.slice(q + 1).replace(/^[\s:\-–—=.]+/, "").trim() : line;
          current().raw[last.item.field].value = isBlankAnswer(answer) ? "" : answer;
          last = { item: last.item };
        }
        return;
      }
      if (/^(please (help|share)|thank|thanks|regards)/i.test(line)) return;
      if (last && last.name && cur && !cur.name) {
        cur.name = line;
        last = null;
        return;
      }
      if (last && last.item) {
        var entry = current().raw[last.item.field];
        if (entry && !entry.value) {
          entry.value = isBlankAnswer(line) ? "" : line;
          return;
        }
        // A second line of a longer answer (where they lived, previous visits, job) —
        // but never an email address or a phone number standing on its own line.
        if (entry && /^(yesNoText|text)$/.test(last.item.kind) && !EMAIL_RE.test(line) && !PHONE_RE.test(line)) {
          entry.value = entry.value + ", " + line;
          return;
        }
      }
      unread.push(line);
      current().loose.push(line);
    });

    return {
      applicants: applicants
        .map(function (a) {
          var values = {};
          var rows = [];
          findLooseContacts(a, unread);
          a.order.forEach(function (field) {
            var e = a.raw[field];
            if (!e.value) {
              rows.push({ label: e.item.label, field: field, value: "", note: "No answer" });
              return;
            }
            var t = tidy(e.item, e.value);
            values[field] = t.value;
            rows.push({ label: e.item.label, field: field, value: t.value, note: e.note || t.note || "" });
          });
          return { name: s(a.name), values: values, rows: rows };
        })
        .filter(function (a) { return a.rows.length || a.name; }),
      unread: unread,
    };
  }

  /* ---------------------------------------------------------------------
   * Matching a reply to a saved profile
   * ------------------------------------------------------------------- */

  function nameTokens(name) {
    return s(name).toUpperCase().replace(/^(MR|MRS|MS|MISS|DR|MASTER)\.?\s+/, "").split(/[^A-Z]+/).filter(function (w) { return w.length > 1; });
  }

  /** How well a typed name fits a profile name: 2 = same words, 1 = one inside the other, 0 = no. */
  function nameScore(typed, profileName) {
    var a = nameTokens(typed);
    var b = nameTokens(profileName);
    if (!a.length || !b.length) return 0;
    var inB = a.filter(function (w) { return b.indexOf(w) !== -1; }).length;
    var inA = b.filter(function (w) { return a.indexOf(w) !== -1; }).length;
    if (inB === a.length && inA === b.length) return 2;
    if ((inB === a.length && a.length >= 2) || (inA === b.length && b.length >= 2)) return 1;
    return 0;
  }

  global.KhannaClientMessages = {
    COUNTRIES: COUNTRIES,
    country: byId,
    message: message,
    read: read,
    nameScore: nameScore,
  };
})(window);
