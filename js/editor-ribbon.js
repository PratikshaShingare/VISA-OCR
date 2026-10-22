/* ==========================================================================
   Khanna Travels & Holidays — Word-style editing ribbon
   The formatting tools shown above the document preview while Edit is on
   (js/preview-editor.js drives it). It follows Microsoft Word's Home tab:
   font, size, grow / shrink, change case, bold / italic / underline /
   strike-through / subscript / superscript, text highlight colour (Word's 15
   colours + No Color), font colour (Automatic, theme colours, standard
   colours, More Colors), bullets, numbering, indent, alignment incl. justify,
   line and paragraph spacing, clear formatting, undo / redo — plus a table
   group (Insert Table grid, rows / columns, delete).

   Every tool here does something real: it formats the text in the open
   editor, and the same formatting is written into the downloaded .docx
   (backend docx_utils.replace_paragraph_range_with_html).

   Tools Word has that this ribbon deliberately does not have (they have no
   safe equivalent in the generated letters): text effects, multilevel-list
   definitions, sort, show/hide ¶, paragraph shading / borders, Draw Table.

     var ribbon = KhannaEditorRibbon.create({
       host:        element the ribbon is built into,
       getQuill:    function () { return Quill|null; },       // the open editor
       getLastRange:function () { return {index,length}|null; },
       getBaseSize: function () { return pt|null; },          // size of unformatted text
       onReset:     function () {},   // "Reset this block"
       onResetAll:  function () {},   // "Reset all"
     });
     ribbon.setEnabled(bool); ribbon.sync(); ribbon.setResetAllCount(n);
   ========================================================================== */
(function (global) {
  "use strict";

  var FONTS = ["Arial", "Calibri", "Cambria", "Courier New", "Georgia", "Segoe UI", "Tahoma", "Times New Roman", "Trebuchet MS", "Verdana"];
  var SIZES = [8, 9, 10, 10.5, 11, 12, 14, 16, 18, 20, 22, 24, 26, 28, 36, 48, 72];

  // Word's Text Highlight Color palette (the 15 real highlighter colours).
  var HIGHLIGHTS = [
    ["#FFFF00", "Yellow"], ["#00FF00", "Bright Green"], ["#00FFFF", "Turquoise"], ["#FF00FF", "Pink"], ["#0000FF", "Blue"],
    ["#FF0000", "Red"], ["#000080", "Dark Blue"], ["#008080", "Teal"], ["#008000", "Green"], ["#800080", "Violet"],
    ["#800000", "Dark Red"], ["#808000", "Dark Yellow"], ["#808080", "Gray-50%"], ["#C0C0C0", "Gray-25%"], ["#000000", "Black"],
  ];

  // Word's Office-theme colours (Font Color > Theme Colors) and Standard Colors.
  var THEME = [
    ["#FFFFFF", "White, Background 1"], ["#000000", "Black, Text 1"], ["#E7E6E6", "Tan, Background 2"], ["#44546A", "Blue-Gray, Text 2"],
    ["#4472C4", "Blue, Accent 1"], ["#ED7D31", "Orange, Accent 2"], ["#A5A5A5", "Gray, Accent 3"], ["#FFC000", "Gold, Accent 4"],
    ["#5B9BD5", "Blue, Accent 5"], ["#70AD47", "Green, Accent 6"],
  ];
  var STANDARD = [
    ["#C00000", "Dark Red"], ["#FF0000", "Red"], ["#FFC000", "Orange"], ["#FFFF00", "Yellow"], ["#92D050", "Light Green"],
    ["#00B050", "Green"], ["#00B0F0", "Light Blue"], ["#0070C0", "Blue"], ["#002060", "Dark Blue"], ["#7030A0", "Purple"],
  ];

  function hex2(n) {
    var s = Math.max(0, Math.min(255, Math.round(n))).toString(16).toUpperCase();
    return s.length < 2 ? "0" + s : s;
  }
  function mix(hex, toward, amount) {
    var c = [1, 3, 5].map(function (i) { return parseInt(hex.slice(i, i + 2), 16); });
    return "#" + c.map(function (v) { return hex2(v + (toward - v) * amount); }).join("");
  }
  // The five shades under each theme colour, as Word lays them out.
  function themeShades(hex) {
    if (hex === "#FFFFFF") return ["#F2F2F2", "#D9D9D9", "#BFBFBF", "#A6A6A6", "#7F7F7F"];
    if (hex === "#000000") return ["#7F7F7F", "#595959", "#3F3F3F", "#262626", "#0C0C0C"];
    return [mix(hex, 255, 0.8), mix(hex, 255, 0.6), mix(hex, 255, 0.4), mix(hex, 0, 0.25), mix(hex, 0, 0.5)];
  }

  var LINE_SPACINGS = ["1.0", "1.15", "1.5", "2.0", "2.5", "3.0"];

  var ICON = {
    undo: "M9 14L4 9l5-5M4 9h10a6 6 0 0 1 0 12h-3",
    redo: "M15 14l5-5-5-5M20 9H10a6 6 0 0 0 0 12h3",
    bullets: "M9 6h11M9 12h11M9 18h11M4.5 6h.01M4.5 12h.01M4.5 18h.01",
    numbers: "M10 6h10M10 12h10M10 18h10M4 5.5l1.5-1v4M4 11.5h2.5L4 14.5h2.5M4 17h2.5v1.5H5M4 20h2.5",
    outdent: "M11 6h9M11 12h9M11 18h9M8 9l-4 3 4 3",
    indent: "M11 6h9M11 12h9M11 18h9M4 9l4 3-4 3",
    left: "M4 6h16M4 10h10M4 14h16M4 18h10",
    center: "M4 6h16M7 10h10M4 14h16M7 18h10",
    right: "M4 6h16M10 10h10M4 14h16M10 18h10",
    justify: "M4 6h16M4 10h16M4 14h16M4 18h16",
    spacing: "M9 5h11M9 12h11M9 19h11M5 4v16M3 6l2-2 2 2M3 18l2 2 2-2",
    clear: "M5 19h8M7 15l8-10 4 3-6 8zM4 4l16 16",
    table: "M4 5h16v14H4zM4 10h16M4 15h16M10 5v14M15 5v14",
    rowAbove: "M4 12h16v7H4zM4 15.5h16M12 12v7M12 8V3M9 5.5h6",
    rowBelow: "M4 5h16v7H4zM4 8.5h16M12 5v7M12 16v5M9 18.5h6",
    colLeft: "M12 4v16h7V4zM15.5 4v16M12 12h7M8 12H3M5.5 9v6",
    colRight: "M5 4v16h7V4zM8.5 4v16M5 12h7M16 12h5M18.5 9v6",
    delRow: "M4 9h16v6H4zM9 9v6M15 9v6M8 4l8 4M8 20l8-4",
    delCol: "M9 4h6v16H9zM9 9h6M9 15h6M4 8l4 8M20 8l-4 8",
    delTable: "M4 5h16v14H4zM4 10h16M10 5v14M6 6l12 12",
    reset: "M3 12a9 9 0 1 0 3-6.7M3 4v5h5",
  };
  function svg(name) {
    return '<svg class="icon icon-sm" viewBox="0 0 24 24" aria-hidden="true"><path d="' + ICON[name] + '"/></svg>';
  }

  function esc(s) {
    return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/"/g, "&quot;");
  }

  function btn(act, label, inner, extraClass) {
    return (
      '<button type="button" class="pe-btn' + (extraClass ? " " + extraClass : "") + '" data-pe="' + act + '" aria-label="' + esc(label) + '" title="' + esc(label) + '">' +
      inner + "</button>"
    );
  }
  function splitBtn(act, label, glyphHtml) {
    return (
      '<span class="pe-split">' +
      '<button type="button" class="pe-btn pe-split__main" data-pe="' + act + '" aria-label="' + esc(label) + '" title="' + esc(label) + '">' + glyphHtml + "</button>" +
      '<button type="button" class="pe-btn pe-split__arrow" data-pe="' + act + "-menu" + '" aria-label="' + esc(label) + ' options" aria-haspopup="true" title="' + esc(label) + ' options">' +
      '<svg class="icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M7 10l5 5 5-5"/></svg></button>' +
      "</span>"
    );
  }

  function create(cfg) {
    var host = cfg.host;
    var pop = null; // {el, anchor}
    var lastHighlight = "#FFFF00";
    var lastColor = "#FF0000";
    var enabled = false;
    var resetAllCount = 0;
    var offDocClick = null;

    /* ----------------------------- markup ---------------------------------- */
    function markup() {
      function opt(v, label) {
        return '<option value="' + esc(v) + '">' + esc(label) + "</option>";
      }
      return (
        '<div class="pe-ribbon" role="toolbar" aria-label="Text formatting">' +
        // ---- Row 1: font ----------------------------------------------------
        '<div class="pe-row">' +
        '<div class="pe-group" role="group" aria-label="Undo">' +
        btn("undo", "Undo (Ctrl+Z)", svg("undo")) + btn("redo", "Redo (Ctrl+Y)", svg("redo")) +
        "</div>" +
        '<div class="pe-group" role="group" aria-label="Font">' +
        '<select class="pe-select pe-select--font" data-pe="font" aria-label="Font" title="Font">' +
        opt("", "Font") + FONTS.map(function (f) { return opt(f, f); }).join("") + "</select>" +
        '<select class="pe-select pe-select--size" data-pe="size" aria-label="Font size" title="Font size (pt)">' +
        opt("", "Size") + SIZES.map(function (n) { return opt(n + "pt", String(n)); }).join("") + "</select>" +
        btn("grow", "Increase font size (Ctrl+Shift+>)", '<span class="pe-txt">A<sup>▲</sup></span>') +
        btn("shrink", "Decrease font size (Ctrl+Shift+<)", '<span class="pe-txt">A<sup>▼</sup></span>') +
        btn("case-menu", "Change case", '<span class="pe-txt">Aa<svg class="icon pe-caret" viewBox="0 0 24 24"><path d="M7 10l5 5 5-5"/></svg></span>') +
        btn("clear", "Clear all formatting", svg("clear")) +
        "</div>" +
        '<div class="pe-group" role="group" aria-label="Character style">' +
        btn("bold", "Bold (Ctrl+B)", "<b>B</b>") +
        btn("italic", "Italic (Ctrl+I)", "<i>I</i>") +
        btn("underline", "Underline (Ctrl+U)", "<u>U</u>") +
        btn("strike", "Strikethrough", "<s>ab</s>") +
        btn("sub", "Subscript", '<span class="pe-txt">x<sub>2</sub></span>') +
        btn("sup", "Superscript", '<span class="pe-txt">x<sup>2</sup></span>') +
        splitBtn("highlight", "Text Highlight Color", '<span class="pe-glyph pe-glyph--hl" data-pe-swatch="highlight">ab</span>') +
        splitBtn("color", "Font Color", '<span class="pe-glyph pe-glyph--color" data-pe-swatch="color">A</span>') +
        "</div>" +
        "</div>" +
        // ---- Row 2: paragraph + table ---------------------------------------
        '<div class="pe-row">' +
        '<div class="pe-group" role="group" aria-label="Paragraph">' +
        btn("bullet", "Bullets", svg("bullets")) +
        btn("ordered", "Numbering", svg("numbers")) +
        btn("outdent", "Decrease indent", svg("outdent")) +
        btn("indent", "Increase indent", svg("indent")) +
        btn("align-left", "Align left (Ctrl+L)", svg("left")) +
        btn("align-center", "Center (Ctrl+E)", svg("center")) +
        btn("align-right", "Align right (Ctrl+R)", svg("right")) +
        btn("align-justify", "Justify (Ctrl+J)", svg("justify")) +
        btn("spacing-menu", "Line and paragraph spacing", svg("spacing") + '<svg class="icon pe-caret" viewBox="0 0 24 24"><path d="M7 10l5 5 5-5"/></svg>') +
        "</div>" +
        '<div class="pe-group" role="group" aria-label="Table">' +
        btn("table-menu", "Insert table", svg("table") + '<svg class="icon pe-caret" viewBox="0 0 24 24"><path d="M7 10l5 5 5-5"/></svg>') +
        btn("row-above", "Insert row above", svg("rowAbove")) +
        btn("row-below", "Insert row below", svg("rowBelow")) +
        btn("col-left", "Insert column to the left", svg("colLeft")) +
        btn("col-right", "Insert column to the right", svg("colRight")) +
        btn("del-row", "Delete row", svg("delRow")) +
        btn("del-col", "Delete column", svg("delCol")) +
        btn("del-table", "Delete table", svg("delTable")) +
        "</div>" +
        '<div class="pe-group pe-group--end" role="group" aria-label="Reset">' +
        btn("reset", "Reset this block to the auto-generated text", svg("reset"), "") +
        '<button type="button" class="pe-btn pe-btn--text" data-pe="reset-all" title="Throw away every hand edit and go back to the auto-generated wording">Reset all</button>' +
        "</div>" +
        "</div>" +
        "</div>"
      );
    }

    /* --------------------------- helpers ----------------------------------- */
    function quill() {
      return cfg.getQuill ? cfg.getQuill() : null;
    }
    function currentRange(q) {
      return q.getSelection() || (cfg.getLastRange && cfg.getLastRange()) || { index: 0, length: Math.max(0, q.getLength() - 1) };
    }
    function formatOf(q) {
      var r = currentRange(q);
      try { return q.getFormat(r.index, r.length) || {}; } catch (e) { return {}; }
    }
    function sizeNumber(v) {
      var n = parseFloat(String(v || ""));
      return isFinite(n) ? n : null;
    }
    function cleanFont(v) {
      return typeof v === "string" ? v.split(",")[0].replace(/["']/g, "").trim() : "";
    }

    // Inline formats apply to the selection (or to what is typed next when
    // it is only a caret); block formats apply to every line it touches.
    function applyInline(name, value) {
      var q = quill();
      if (!q) return;
      var r = currentRange(q);
      q.focus();
      q.setSelection(r.index, r.length, "silent");
      if (r.length === 0) q.format(name, value, "user");
      else q.formatText(r.index, r.length, name, value, "user");
      afterChange(q, r);
    }
    function applyBlock(name, value) {
      var q = quill();
      if (!q) return;
      var r = currentRange(q);
      q.focus();
      q.setSelection(r.index, r.length, "silent");
      q.formatLine(r.index, Math.max(r.length, 1), name, value, "user");
      afterChange(q, r);
    }
    function afterChange(q, r) {
      var now = q.getSelection();
      if (!now) q.setSelection(r.index, r.length, "silent");
      sync();
    }
    function toggleInline(name, onValue) {
      var q = quill();
      if (!q) return;
      var f = formatOf(q);
      applyInline(name, f[name] ? false : onValue === undefined ? true : onValue);
    }

    function grow(direction) {
      var q = quill();
      if (!q) return;
      var f = formatOf(q);
      var cur = sizeNumber(f.size) || (cfg.getBaseSize && cfg.getBaseSize()) || 11;
      var next = cur;
      if (direction > 0) {
        next = SIZES.filter(function (s) { return s > cur; })[0] || cur + 10;
      } else {
        var smaller = SIZES.filter(function (s) { return s < cur; });
        next = smaller.length ? smaller[smaller.length - 1] : Math.max(4, cur - 1);
      }
      applyInline("size", next + "pt");
    }

    function changeCase(mode) {
      var q = quill();
      if (!q) return;
      var r = currentRange(q);
      if (r.length === 0) return;
      var Delta = global.Quill.import("delta");
      var ops = q.getContents(r.index, r.length).ops || [];
      function map(text) {
        var out;
        if (mode === "upper") out = text.toUpperCase();
        else if (mode === "lower") out = text.toLowerCase();
        else if (mode === "title") out = text.toLowerCase().replace(/(^|[\s\-/(])([a-zÀ-ɏ])/g, function (m, a, b) { return a + b.toUpperCase(); });
        else if (mode === "sentence") out = text.toLowerCase().replace(/(^|[.!?]\s+)([a-zÀ-ɏ])/g, function (m, a, b) { return a + b.toUpperCase(); }).replace(/^([a-zÀ-ɏ])/, function (m) { return m.toUpperCase(); });
        else out = text.split("").map(function (ch) { return ch === ch.toUpperCase() ? ch.toLowerCase() : ch.toUpperCase(); }).join("");
        return out.length === text.length ? out : text; // never change the length (keeps every format in place)
      }
      // One insert (new case, same formats) + delete per run, so every format stays in place.
      var edit = new Delta().retain(r.index);
      ops.forEach(function (op) {
        if (typeof op.insert === "string") {
          edit = edit.insert(map(op.insert), op.attributes).delete(op.insert.length);
        } else {
          edit = edit.retain(1);
        }
      });
      q.updateContents(edit, "user");
      q.setSelection(r.index, r.length, "silent");
      sync();
    }

    function setLineHeight(value) {
      applyBlock("lineheight", value === "1.0" ? false : value);
    }
    function toggleSpace(which) {
      var q = quill();
      if (!q) return;
      var name = which === "before" ? "spacebefore" : "spaceafter";
      var cur = formatOf(q)[name];
      applyBlock(name, cur === "0pt" ? "12pt" : "0pt");
    }

    function indentBy(delta) {
      var q = quill();
      if (!q) return;
      var f = formatOf(q);
      var next = Math.max(0, Math.min(8, (parseInt(f.indent, 10) || 0) + delta));
      applyBlock("indent", next === 0 ? false : next);
    }

    function listToggle(type) {
      var q = quill();
      if (!q) return;
      applyBlock("list", formatOf(q).list === type ? false : type);
    }

    function insertTable(rows, cols) {
      var q = quill();
      if (!q) return;
      var tableModule = q.getModule("table");
      if (!tableModule) return;
      var r = currentRange(q);
      var lineInfo = q.getLine(r.index + r.length);
      var line = lineInfo[0];
      var offset = lineInfo[1];
      var lineStart = r.index + r.length - offset;
      var lineEnd = lineStart + line.length() - 1;
      q.focus();
      // Word puts a new table after the current paragraph, so open a blank
      // line there first (inserting at the caret would split the paragraph).
      q.insertText(lineEnd, "\n", "user");
      q.setSelection(lineEnd + 1, 0, "silent");
      tableModule.insertTable(rows, cols);
      sync();
    }
    function tableOp(name) {
      var q = quill();
      if (!q) return;
      var tableModule = q.getModule("table");
      if (!tableModule || !formatOf(q).table) return;
      q.focus();
      var map = {
        "row-above": "insertRowAbove", "row-below": "insertRowBelow", "col-left": "insertColumnLeft",
        "col-right": "insertColumnRight", "del-row": "deleteRow", "del-col": "deleteColumn", "del-table": "deleteTable",
      };
      if (tableModule[map[name]]) tableModule[map[name]]();
      sync();
    }

    /* ---------------------------- popovers --------------------------------- */
    function closePopover() {
      if (pop) {
        if (pop.anchor) pop.anchor.setAttribute("aria-expanded", "false");
        pop.el.remove();
        pop = null;
      }
      if (offDocClick) {
        document.removeEventListener("mousedown", offDocClick, true);
        document.removeEventListener("keydown", onDocKey, true);
        window.removeEventListener("resize", closePopover);
        offDocClick = null;
      }
    }
    function onDocKey(e) {
      if (e.key === "Escape" && pop) {
        e.stopPropagation();
        closePopover();
      }
    }
    function openPopover(anchor, className, html) {
      var same = pop && pop.anchor === anchor;
      closePopover();
      if (same) return null;
      var el = document.createElement("div");
      el.className = "pe-pop " + className;
      el.setAttribute("role", "dialog");
      el.innerHTML = html;
      document.body.appendChild(el);
      var a = anchor.getBoundingClientRect();
      var w = el.offsetWidth;
      var h = el.offsetHeight;
      var left = Math.max(8, Math.min(a.left, window.innerWidth - w - 8));
      var top = a.bottom + 4;
      if (top + h > window.innerHeight - 8 && a.top - h - 4 > 8) top = a.top - h - 4;
      el.style.left = left + "px";
      el.style.top = Math.max(8, top) + "px";
      pop = { el: el, anchor: anchor };
      anchor.setAttribute("aria-expanded", "true");
      // keep the editor's focus: nothing in a popover should steal it
      el.addEventListener("mousedown", function (e) {
        if (!e.target.closest("input, select")) e.preventDefault();
      });
      offDocClick = function (e) {
        if (pop && !pop.el.contains(e.target) && !anchor.contains(e.target)) closePopover();
      };
      document.addEventListener("mousedown", offDocClick, true);
      document.addEventListener("keydown", onDocKey, true);
      window.addEventListener("resize", closePopover);
      return el;
    }

    function swatch(hex, name, extra) {
      return (
        '<button type="button" class="pe-sw' + (extra ? " " + extra : "") + '" data-hex="' + hex + '" title="' + esc(name) +
        '" aria-label="' + esc(name) + '" style="background:' + hex + '"></button>'
      );
    }

    function highlightMenu(anchor) {
      var html =
        '<div class="pe-pop__title">Text Highlight Color</div>' +
        '<div class="pe-sw-grid pe-sw-grid--5">' + HIGHLIGHTS.map(function (c) { return swatch(c[0], c[1]); }).join("") + "</div>" +
        '<button type="button" class="pe-pop__item" data-nocolor="1"><span class="pe-sw pe-sw--none"></span>No Color</button>';
      var el = openPopover(anchor, "pe-pop--palette", html);
      if (!el) return;
      el.addEventListener("click", function (e) {
        var s = e.target.closest("[data-hex]");
        var none = e.target.closest("[data-nocolor]");
        if (s) {
          lastHighlight = s.getAttribute("data-hex");
          applyInline("background", lastHighlight);
          closePopover();
        } else if (none) {
          applyInline("background", false);
          closePopover();
        }
      });
    }

    function colorMenu(anchor) {
      var themeRow = THEME.map(function (c) { return swatch(c[0], c[1]); }).join("");
      var shadeRows = [0, 1, 2, 3, 4].map(function (i) {
        return '<div class="pe-sw-grid pe-sw-grid--10">' + THEME.map(function (c) { return swatch(themeShades(c[0])[i], c[1] + ", shade " + (i + 1)); }).join("") + "</div>";
      }).join("");
      var html =
        '<div class="pe-pop__title">Font Color</div>' +
        '<button type="button" class="pe-pop__item" data-auto="1"><span class="pe-sw pe-sw--auto"></span>Automatic</button>' +
        '<div class="pe-pop__sub">Theme Colors</div>' +
        '<div class="pe-sw-grid pe-sw-grid--10">' + themeRow + "</div>" + shadeRows +
        '<div class="pe-pop__sub">Standard Colors</div>' +
        '<div class="pe-sw-grid pe-sw-grid--10">' + STANDARD.map(function (c) { return swatch(c[0], c[1]); }).join("") + "</div>" +
        '<label class="pe-pop__item pe-pop__item--more"><span class="pe-sw pe-sw--more"></span>More Colors…' +
        '<input type="color" class="pe-pop__colorinput" value="' + lastColor + '" aria-label="More colors" /></label>';
      var el = openPopover(anchor, "pe-pop--palette pe-pop--wide", html);
      if (!el) return;
      el.addEventListener("click", function (e) {
        var s = e.target.closest("[data-hex]");
        var auto = e.target.closest("[data-auto]");
        if (s) {
          lastColor = s.getAttribute("data-hex");
          applyInline("color", lastColor);
          closePopover();
        } else if (auto) {
          applyInline("color", false);
          closePopover();
        }
      });
      var input = el.querySelector(".pe-pop__colorinput");
      input.addEventListener("change", function () {
        lastColor = input.value.toUpperCase();
        applyInline("color", lastColor);
        closePopover();
      });
    }

    function caseMenu(anchor) {
      var items = [
        ["sentence", "Sentence case."], ["lower", "lowercase"], ["upper", "UPPERCASE"], ["title", "Capitalize Each Word"], ["toggle", "tOGGLE cASE"],
      ];
      var el = openPopover(anchor, "pe-pop--menu", items.map(function (i) {
        return '<button type="button" class="pe-pop__item" data-case="' + i[0] + '">' + esc(i[1]) + "</button>";
      }).join(""));
      if (!el) return;
      el.addEventListener("click", function (e) {
        var b = e.target.closest("[data-case]");
        if (!b) return;
        changeCase(b.getAttribute("data-case"));
        closePopover();
      });
    }

    function spacingMenu(anchor) {
      var q = quill();
      var f = q ? formatOf(q) : {};
      var cur = f.lineheight || "1.0";
      var before = f.spacebefore === "0pt";
      var after = f.spaceafter === "0pt";
      var html =
        LINE_SPACINGS.map(function (v) {
          var on = String(parseFloat(cur)) === String(parseFloat(v));
          return '<button type="button" class="pe-pop__item" data-ls="' + v + '"><span class="pe-check">' + (on ? "✓" : "") + "</span>" + v + "</button>";
        }).join("") +
        '<div class="pe-pop__sep"></div>' +
        '<button type="button" class="pe-pop__item" data-opts="1"><span class="pe-check"></span>Line Spacing Options…</button>' +
        '<div class="pe-pop__sep"></div>' +
        '<button type="button" class="pe-pop__item" data-space="before"><span class="pe-check"></span>' + (before ? "Add Space Before Paragraph" : "Remove Space Before Paragraph") + "</button>" +
        '<button type="button" class="pe-pop__item" data-space="after"><span class="pe-check"></span>' + (after ? "Add Space After Paragraph" : "Remove Space After Paragraph") + "</button>";
      var el = openPopover(anchor, "pe-pop--menu", html);
      if (!el) return;
      el.addEventListener("click", function (e) {
        var ls = e.target.closest("[data-ls]");
        var sp = e.target.closest("[data-space]");
        var opts = e.target.closest("[data-opts]");
        if (ls) {
          setLineHeight(ls.getAttribute("data-ls"));
          closePopover();
        } else if (sp) {
          toggleSpace(sp.getAttribute("data-space"));
          closePopover();
        } else if (opts) {
          spacingOptions(anchor);
        }
      });
    }

    // Word's Paragraph > Spacing options: exact multiple + points before / after.
    function spacingOptions(anchor) {
      var q = quill();
      var f = q ? formatOf(q) : {};
      var html =
        '<div class="pe-pop__title">Line Spacing Options</div>' +
        '<label class="pe-field-row">Line spacing (multiple)' +
        '<input type="number" class="pe-num" data-o="line" min="0.5" max="6" step="0.05" value="' + (parseFloat(f.lineheight) || 1) + '"></label>' +
        '<label class="pe-field-row">Before (pt)' +
        '<input type="number" class="pe-num" data-o="before" min="0" max="200" step="1" value="' + (sizeNumber(f.spacebefore) == null ? "" : sizeNumber(f.spacebefore)) + '" placeholder="auto"></label>' +
        '<label class="pe-field-row">After (pt)' +
        '<input type="number" class="pe-num" data-o="after" min="0" max="200" step="1" value="' + (sizeNumber(f.spaceafter) == null ? "" : sizeNumber(f.spaceafter)) + '" placeholder="auto"></label>' +
        '<div class="pe-pop__actions"><button type="button" class="btn btn-primary btn-sm" data-ok="1">OK</button>' +
        '<button type="button" class="btn btn-ghost btn-sm" data-cancel="1">Cancel</button></div>';
      closePopover();
      var el = openPopover(anchor, "pe-pop--dialog", html);
      if (!el) return;
      el.addEventListener("click", function (e) {
        if (e.target.closest("[data-cancel]")) closePopover();
        if (!e.target.closest("[data-ok]")) return;
        var line = parseFloat(el.querySelector('[data-o="line"]').value);
        var b = el.querySelector('[data-o="before"]').value;
        var a = el.querySelector('[data-o="after"]').value;
        if (isFinite(line) && line >= 0.5 && line <= 6) setLineHeight(String(line));
        if (b !== "") applyBlock("spacebefore", Math.max(0, Math.min(200, parseFloat(b))) + "pt");
        if (a !== "") applyBlock("spaceafter", Math.max(0, Math.min(200, parseFloat(a))) + "pt");
        closePopover();
      });
    }

    function tableMenu(anchor) {
      var ROWS = 8;
      var COLS = 10;
      var cells = "";
      for (var r = 1; r <= ROWS; r++) {
        for (var c = 1; c <= COLS; c++) {
          cells += '<button type="button" class="pe-tcell" data-r="' + r + '" data-c="' + c + '" aria-label="' + r + " by " + c + ' table"></button>';
        }
      }
      var html =
        '<div class="pe-pop__title" data-tlabel>Insert Table</div>' +
        '<div class="pe-tgrid" style="grid-template-columns:repeat(' + COLS + ',18px)">' + cells + "</div>";
      var el = openPopover(anchor, "pe-pop--table", html);
      if (!el) return;
      var label = el.querySelector("[data-tlabel]");
      function paint(r, c) {
        Array.prototype.forEach.call(el.querySelectorAll(".pe-tcell"), function (b) {
          b.classList.toggle("is-on", +b.getAttribute("data-r") <= r && +b.getAttribute("data-c") <= c);
        });
        label.textContent = r && c ? c + " × " + r + " Table" : "Insert Table";
      }
      el.addEventListener("mouseover", function (e) {
        var b = e.target.closest(".pe-tcell");
        if (b) paint(+b.getAttribute("data-r"), +b.getAttribute("data-c"));
      });
      el.addEventListener("focusin", function (e) {
        var b = e.target.closest(".pe-tcell");
        if (b) paint(+b.getAttribute("data-r"), +b.getAttribute("data-c"));
      });
      el.addEventListener("click", function (e) {
        var b = e.target.closest(".pe-tcell");
        if (!b) return;
        var rr = +b.getAttribute("data-r");
        var cc = +b.getAttribute("data-c");
        closePopover();
        insertTable(rr, cc);
      });
    }

    /* ------------------------------ events --------------------------------- */
    function onClick(e) {
      var b = e.target.closest("[data-pe]");
      if (!b || !host.contains(b) || b.disabled) return;
      var act = b.getAttribute("data-pe");
      if (act === "reset-all") return cfg.onResetAll && cfg.onResetAll();
      if (act === "reset") return cfg.onReset && cfg.onReset();
      var q = quill();
      if (!q) return;
      switch (act) {
        case "undo": q.history.undo(); sync(); break;
        case "redo": q.history.redo(); sync(); break;
        case "bold": toggleInline("bold"); break;
        case "italic": toggleInline("italic"); break;
        case "underline": toggleInline("underline"); break;
        case "strike": toggleInline("strike"); break;
        case "sub": applyInline("script", formatOf(q).script === "sub" ? false : "sub"); break;
        case "sup": applyInline("script", formatOf(q).script === "super" ? false : "super"); break;
        case "grow": grow(1); break;
        case "shrink": grow(-1); break;
        case "clear": {
          var r = currentRange(q);
          q.focus();
          q.removeFormat(r.index, Math.max(r.length, 1), "user");
          q.setSelection(r.index, r.length, "silent");
          sync();
          break;
        }
        case "case-menu": caseMenu(b); break;
        case "highlight": applyInline("background", lastHighlight); break;
        case "highlight-menu": highlightMenu(b); break;
        case "color": applyInline("color", lastColor); break;
        case "color-menu": colorMenu(b); break;
        case "bullet": listToggle("bullet"); break;
        case "ordered": listToggle("ordered"); break;
        case "outdent": indentBy(-1); break;
        case "indent": indentBy(1); break;
        case "align-left": applyBlock("align", false); break;
        case "align-center": applyBlock("align", "center"); break;
        case "align-right": applyBlock("align", "right"); break;
        case "align-justify": applyBlock("align", "justify"); break;
        case "spacing-menu": spacingMenu(b); break;
        case "table-menu": tableMenu(b); break;
        case "row-above": case "row-below": case "col-left": case "col-right":
        case "del-row": case "del-col": case "del-table":
          tableOp(act);
          break;
      }
    }
    function onChange(e) {
      var ctl = e.target.closest("[data-pe]");
      if (!ctl || !quill()) return;
      var act = ctl.getAttribute("data-pe");
      if (act === "font") applyInline("font", ctl.value || false);
      else if (act === "size") applyInline("size", ctl.value || false);
    }

    /* ------------------------------ state ---------------------------------- */
    function setOn(act, on) {
      var b = host.querySelector('[data-pe="' + act + '"]');
      if (b) b.classList.toggle("is-on", !!on);
    }
    function sync() {
      var q = quill();
      var f = q && enabled ? formatOf(q) : {};
      setOn("bold", f.bold);
      setOn("italic", f.italic);
      setOn("underline", f.underline);
      setOn("strike", f.strike);
      setOn("sub", f.script === "sub");
      setOn("sup", f.script === "super");
      setOn("bullet", f.list === "bullet");
      setOn("ordered", f.list === "ordered");
      var al = f.align || "left";
      ["left", "center", "right", "justify"].forEach(function (a) { setOn("align-" + a, al === a); });
      var fontSel = host.querySelector('[data-pe="font"]');
      var sizeSel = host.querySelector('[data-pe="size"]');
      var font = cleanFont(f.font);
      if (fontSel) {
        if (font && !fontSel.querySelector('option[value="' + font.replace(/"/g, "") + '"]')) {
          var o = document.createElement("option");
          o.value = font;
          o.textContent = font;
          fontSel.appendChild(o);
        }
        fontSel.value = font;
      }
      if (sizeSel) {
        var sz = typeof f.size === "string" ? f.size : "";
        if (sz && !sizeSel.querySelector('option[value="' + sz + '"]')) {
          var o2 = document.createElement("option");
          o2.value = sz;
          o2.textContent = String(sizeNumber(sz));
          sizeSel.appendChild(o2);
        }
        sizeSel.value = sz;
      }
      var colorSw = host.querySelector('[data-pe-swatch="color"]');
      if (colorSw) colorSw.style.borderBottomColor = typeof f.color === "string" ? f.color : lastColor;
      var hlSw = host.querySelector('[data-pe-swatch="highlight"]');
      if (hlSw) hlSw.style.background = typeof f.background === "string" ? f.background : lastHighlight;
      var inTable = !!f.table;
      ["row-above", "row-below", "col-left", "col-right", "del-row", "del-col", "del-table"].forEach(function (a) {
        var b = host.querySelector('[data-pe="' + a + '"]');
        if (b) b.disabled = !enabled || !inTable;
      });
      var tblBtn = host.querySelector('[data-pe="table-menu"]');
      if (tblBtn) tblBtn.disabled = !enabled || inTable; // no table inside a table cell
    }

    function setEnabled(on) {
      enabled = !!on;
      var root = host.querySelector(".pe-ribbon");
      if (root) root.classList.toggle("is-disabled", !enabled);
      Array.prototype.forEach.call(host.querySelectorAll("button, select"), function (c) {
        c.disabled = !enabled;
      });
      if (!enabled) closePopover();
      syncResetAll();
      sync();
    }
    function syncResetAll() {
      var b = host.querySelector('[data-pe="reset-all"]');
      if (!b) return;
      b.disabled = resetAllCount === 0;
      b.textContent = resetAllCount ? "Reset all (" + resetAllCount + ")" : "Reset all";
    }

    host.innerHTML = markup();
    host.addEventListener("mousedown", function (e) {
      // clicking a tool must not move focus out of the open editor
      if (e.target.closest("button")) e.preventDefault();
    });
    host.addEventListener("click", onClick);
    host.addEventListener("change", onChange);
    setEnabled(false);

    return {
      setEnabled: setEnabled,
      sync: sync,
      setResetAllCount: function (n) {
        resetAllCount = n;
        syncResetAll();
      },
      closePopover: closePopover,
      destroy: function () {
        closePopover();
        host.innerHTML = "";
      },
    };
  }

  global.KhannaEditorRibbon = { create: create, FONTS: FONTS, SIZES: SIZES, HIGHLIGHTS: HIGHLIGHTS };
})(window);
