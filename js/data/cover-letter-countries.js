/* ==========================================================================
   Khanna Travels & Holidays — Cover Letter country / consulate config
   Frontend rework, sections 6-9. A single, self-contained configuration
   layer: which countries the Cover Letter feature supports, which real
   reference-template region each maps to, and a starting-point consulate
   name/address for each — kept OUT of cover-letter.js's own UI code
   (explicit instruction: "keep the consulate information configurable in
   the application's data/configuration layer... do not hard-code this
   throughout the UI"). cover-letter.js only ever reads this through the
   small helper API at the bottom.

   Region values ("Europe" | "Japan" | "Singapore") are exactly the same
   values the region selector used before this rework and that
   cover_letter_engine.py's dispatch keys, template folders and person-count
   rules already depend on (see cover-letter.js's own file header) — this
   module only adds a country-level layer ABOVE that, it does not change
   what a "region" means anywhere else in the app.

   IMPORTANT — consulate data accuracy (project rules 9 & 11: never fake
   functionality, never invent data that could end up on a real client
   document): a country's real visa jurisdiction (which consulate/embassy/
   VFS Global centre an Indian applicant actually submits to) depends on
   the applicant's home state and can change over time — it is not
   something this app can safely guess from the country name alone.
   `consulateName` below is only ever a plausible STARTING LABEL ("Consulate
   General of France"); `consulateAddress` is deliberately left blank
   rather than filled with an invented-but-plausible-looking street
   address. Khanna Travels & Holidays staff should fill in and keep current
   the real jurisdiction/address for each country they actually process —
   either by editing COUNTRY_LIST below, or (simplest, no code change) by
   just correcting the auto-filled "Consulate name & address" field in the
   Cover Letter UI itself before generating, exactly like correcting an
   OCR-extracted field.
   ========================================================================== */
(function (global) {
  "use strict";

  // The exact Schengen/Europe destination list from the frontend rework
  // spec, section 7. Every one of these maps to the same real Europe
  // reference template (cover_letter_engine.py — one template already
  // covers every Schengen destination with the same fixed wording; there
  // is no separate per-country template to point to).
  var EUROPE_COUNTRIES = [
    "Austria",
    "Belgium",
    "Bulgaria",
    "Croatia",
    "Czech Republic",
    "Denmark",
    "Estonia",
    "Finland",
    "France",
    "Germany",
    "Greece",
    "Hungary",
    "Iceland",
    "Italy",
    "Latvia",
    "Liechtenstein",
    "Lithuania",
    "Luxembourg",
    "Malta",
    "Netherlands",
    "Norway",
    "Poland",
    "Portugal",
    "Romania",
    "Slovakia",
    "Slovenia",
    "Spain",
    "Sweden",
    "Switzerland",
  ];

  function countryEntry(name, region, consulateName) {
    return {
      name: name,
      region: region, // "Europe" | "Japan" | "Singapore" — cover_letter_engine.py's dispatch key
      consulateName: consulateName,
      // Deliberately blank — see the file header. Never shown as if it
      // were a verified real address; the UI always keeps this in a
      // plain, editable text field.
      consulateAddress: "",
    };
  }

  var COUNTRY_LIST = EUROPE_COUNTRIES.map(function (name) {
    return countryEntry(name, "Europe", "Consulate General of " + name);
  }).concat([
    countryEntry("Japan", "Japan", "Consulate General of Japan"),
    countryEntry("Singapore", "Singapore", "High Commission of the Republic of Singapore"),
  ]);

  function all() {
    return COUNTRY_LIST.slice();
  }

  function search(query) {
    var q = (query || "").trim().toLowerCase();
    if (!q) return all();
    var matches = COUNTRY_LIST.filter(function (c) {
      return c.name.toLowerCase().indexOf(q) !== -1;
    });
    // Names that START with what was typed come first ("n" -> Netherlands,
    // Norway before Denmark), the rest keep their alphabetical order.
    var starts = matches.filter(function (c) { return c.name.toLowerCase().indexOf(q) === 0; });
    var others = matches.filter(function (c) { return c.name.toLowerCase().indexOf(q) !== 0; });
    return starts.concat(others);
  }

  function byName(name) {
    if (!name) return null;
    var lower = String(name).trim().toLowerCase();
    var match = COUNTRY_LIST.filter(function (c) {
      return c.name.toLowerCase() === lower;
    });
    return match[0] || null;
  }

  // The consulate line auto-filled the moment a country is selected:
  // "The Consulate General of Japan" (wording and the few countries that read
  // "of the Netherlands" come from js/consulate.js). Its address is a
  // separate, editable field that starts as Mumbai, India (see the file
  // header on why no street address is ever invented here).
  function consulateDefaultText(entry) {
    if (!entry) return "";
    if (entry.region === "Singapore") return "The " + entry.consulateName;
    return global.KhannaConsulate ? global.KhannaConsulate.consulateName(entry.name) : "The " + entry.consulateName;
  }

  global.KhannaCoverLetterCountries = {
    all: all,
    search: search,
    byName: byName,
    consulateDefaultText: consulateDefaultText,
  };
})(window);
