/* ==========================================================================
   Khanna Travels & Holidays — consulate country selector (shared)
   Letters that are addressed to a consulate (Company Authorization,
   Invitation, Cover Letter) no longer ask staff to type the consulate's
   name. They pick the COUNTRY from a searchable list and the wording is
   completed automatically:

       The Consulate General of Japan
       Mumbai, India                      <- "Address of Consulate", editable

   This module holds the three shared pieces so no letter keeps its own copy:
     - the wording (consulateName / composeRecipient),
     - the default address line (Khanna's visa work goes through Mumbai),
     - the searchable country combobox (html + wiring).

   Only wording is generated here. Nothing claims a particular consulate
   really sits at the default address or covers the applicant's state — the
   address stays a plain editable field, exactly like an OCR-extracted value
   staff are expected to check.
   ========================================================================== */
(function (global) {
  "use strict";

  var utils = global.KhannaUtils;

  var DEFAULT_ADDRESS = "Mumbai, India";

  // Countries whose ordinary English name takes "the" after "of".
  var TAKES_THE = {
    Bahamas: 1,
    Comoros: 1,
    "Czech Republic": 1,
    "Dominican Republic": 1,
    Gambia: 1,
    Maldives: 1,
    Netherlands: 1,
    Philippines: 1,
    Seychelles: 1,
    "Solomon Islands": 1,
    "United Arab Emirates": 1,
    "United Kingdom": 1,
    "United States": 1,
    "Marshall Islands": 1,
    "Central African Republic": 1,
  };

  function countryNames() {
    return global.KhannaCountries ? global.KhannaCountries.all() : [];
  }

  function search(query) {
    var q = (query || "").trim().toLowerCase();
    var all = countryNames();
    if (!q) return all;
    var starts = [];
    var others = [];
    all.forEach(function (name) {
      var i = name.toLowerCase().indexOf(q);
      if (i === 0) starts.push(name);
      else if (i > 0) others.push(name);
    });
    return starts.concat(others);
  }

  function byName(name) {
    var lower = String(name || "").trim().toLowerCase();
    if (!lower) return "";
    var hit = countryNames().filter(function (n) {
      return n.toLowerCase() === lower;
    })[0];
    return hit || "";
  }

  function consulateName(country) {
    var c = (country || "").trim();
    if (!c) return "";
    return "The Consulate General of " + (TAKES_THE[c] ? "the " : "") + c;
  }

  // "The Consulate General of Japan" + newline + "Mumbai, India". With no
  // address the name stands alone; with no name there is nothing to address.
  function composeRecipient(name, address) {
    var n = (name || "").trim();
    var a = (address || "").trim();
    if (!n) return "";
    return a ? n + "\n" + a : n;
  }

  // `undefined` means "never touched" (default applies); an empty string is
  // a deliberate blank the user typed, and is respected.
  function addressOrDefault(address) {
    return address === undefined || address === null ? DEFAULT_ADDRESS : address;
  }

  /* ---------------------------------------------------------------------
   * Searchable combobox
   * ------------------------------------------------------------------- */

  var comboSeq = 0;

  function optionsHtml(listId, query) {
    var matches = search(query);
    if (!matches.length) return '<p class="field-hint country-combo__empty">No matching country.</p>';
    return matches
      .map(function (name, i) {
        return (
          '<button type="button" class="country-combo__option" role="option" id="' + listId + "-opt-" + i + '" data-ccombo-option="' +
          utils.escapeHtml(name) + '"><span>' + utils.escapeHtml(name) + "</span></button>"
        );
      })
      .join("");
  }

  /**
   * @param {object} o  { key: identifies this combobox to the onChoose callback,
   *   id: input id, label, value: the chosen country, required, placeholder }
   */
  function comboHtml(o) {
    comboSeq += 1;
    var listId = (o.id || "ccombo") + "-list-" + comboSeq;
    return (
      '<div class="field">' +
      '<label for="' + o.id + '">' + utils.escapeHtml(o.label) + (o.required ? " *" : "") + "</label>" +
      '<div class="country-combo" data-ccombo="' + utils.escapeHtml(o.key) + '" data-ccombo-chosen="' + utils.escapeHtml(o.value || "") + '">' +
      '<input type="text" id="' + o.id + '" data-ccombo-input autocomplete="off" role="combobox" aria-autocomplete="list" ' +
      'aria-expanded="false" aria-haspopup="listbox" aria-controls="' + listId + '" ' +
      'placeholder="' + utils.escapeHtml(o.placeholder || "Type to search a country…") + '" value="' + utils.escapeHtml(o.value || "") + '" />' +
      '<div class="country-combo__list" role="listbox" id="' + listId + '" data-ccombo-list hidden></div>' +
      "</div>" +
      "</div>"
    );
  }

  function closeCombo(combo, restoreText) {
    var list = combo.querySelector("[data-ccombo-list]");
    var input = combo.querySelector("[data-ccombo-input]");
    if (list) list.setAttribute("hidden", "");
    if (input) {
      input.setAttribute("aria-expanded", "false");
      input.removeAttribute("aria-activedescendant");
      // Typed text that never became a selection reverts to the real choice.
      if (restoreText) input.value = combo.getAttribute("data-ccombo-chosen") || "";
    }
  }

  function openCombo(combo, query) {
    var list = combo.querySelector("[data-ccombo-list]");
    var input = combo.querySelector("[data-ccombo-input]");
    if (!list) return;
    list.innerHTML = optionsHtml(list.id, query);
    list.removeAttribute("hidden");
    if (input) input.setAttribute("aria-expanded", "true");
    setActive(combo, 0);
  }

  function optionEls(combo) {
    return Array.prototype.slice.call(combo.querySelectorAll("[data-ccombo-option]"));
  }

  function setActive(combo, index) {
    var opts = optionEls(combo);
    var input = combo.querySelector("[data-ccombo-input]");
    opts.forEach(function (o, i) { o.classList.toggle("is-active", i === index); });
    if (!opts.length) {
      if (input) input.removeAttribute("aria-activedescendant");
      return;
    }
    var active = opts[Math.max(0, Math.min(index, opts.length - 1))];
    if (input) input.setAttribute("aria-activedescendant", active.id);
    if (active.scrollIntoView) active.scrollIntoView({ block: "nearest" });
  }

  function activeIndex(combo) {
    var opts = optionEls(combo);
    for (var i = 0; i < opts.length; i++) if (opts[i].classList.contains("is-active")) return i;
    return -1;
  }

  var outsideClickWired = false;

  /**
   * Wires every combobox inside `root` (delegated, so it keeps working when the
   * card is re-rendered). `onChoose(key, countryName)` runs when a country is
   * picked; the caller stores it and re-renders. Wiring the same root again
   * replaces the earlier listeners (utils.on), never stacks them.
   */
  function wire(root, onChoose) {
    if (!root) return;

    function choose(combo, name) {
      var input = combo.querySelector("[data-ccombo-input]");
      combo.setAttribute("data-ccombo-chosen", name);
      if (input) input.value = name;
      closeCombo(combo, false);
      onChoose(combo.getAttribute("data-ccombo"), name);
    }

    utils.on(root, "focusin", "[data-ccombo-input]", function (e, input) {
      if (input.select) input.select(); // typing replaces the current country straight away
      openCombo(input.closest("[data-ccombo]"), "");
    });
    utils.on(root, "input", "[data-ccombo-input]", function (e, input) {
      openCombo(input.closest("[data-ccombo]"), input.value);
    });
    utils.on(root, "keydown", "[data-ccombo-input]", function (e, input) {
      var combo = input.closest("[data-ccombo]");
      var list = combo.querySelector("[data-ccombo-list]");
      var isOpen = list && !list.hasAttribute("hidden");
      if (e.key === "ArrowDown" || e.key === "ArrowUp") {
        e.preventDefault();
        if (!isOpen) openCombo(combo, input.value);
        var n = optionEls(combo).length;
        if (!n) return;
        var cur = activeIndex(combo);
        setActive(combo, e.key === "ArrowDown" ? (cur + 1) % n : (cur - 1 + n) % n);
      } else if (e.key === "Enter") {
        if (!isOpen) return;
        e.preventDefault();
        var opts = optionEls(combo);
        var idx = activeIndex(combo);
        var pick = opts[idx >= 0 ? idx : 0];
        if (pick) choose(combo, pick.getAttribute("data-ccombo-option"));
      } else if (e.key === "Escape") {
        closeCombo(combo, true);
      } else if (e.key === "Tab") {
        closeCombo(combo, true);
      }
    });
    utils.on(root, "click", "[data-ccombo-option]", function (e, option) {
      choose(option.closest("[data-ccombo]"), option.getAttribute("data-ccombo-option"));
    });

    if (!outsideClickWired) {
      outsideClickWired = true;
      document.addEventListener("click", function (e) {
        Array.prototype.slice.call(document.querySelectorAll("[data-ccombo]")).forEach(function (combo) {
          if (!combo.contains(e.target)) closeCombo(combo, true);
        });
      });
    }
  }

  global.KhannaConsulate = {
    DEFAULT_ADDRESS: DEFAULT_ADDRESS,
    search: search,
    byName: byName,
    consulateName: consulateName,
    composeRecipient: composeRecipient,
    addressOrDefault: addressOrDefault,
    comboHtml: comboHtml,
    wire: wire,
  };
})(window);
