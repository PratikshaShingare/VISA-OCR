/* ==========================================================================
   Khanna Travels & Holidays — Whole-letter editor (every document page)
   The preview stays the REAL generated PDF (js/document-viewer.js). Pressing
   Edit swaps the PDF page for ONE continuous, Word-like page holding the whole
   letter: every paragraph, list and table row of it, in reading order, in a
   single editor (Quill) — so the caret, selection, Enter, Backspace, Delete,
   copy / paste and undo work across the entire letter exactly as in Word or
   Notepad, never "one box at a time". The shared ribbon in the viewer's title
   line applies font, size, bold, italic, underline, colour, highlight,
   alignment, lists, spacing and tables to whatever is selected.

   The letterhead (logo, header, footer) is never part of the editable text: it
   always comes from the reference template (project rule 5) and appears on the
   finished page.

   How edits are saved. The backend splits a generated letter into "units" —
   each engine's named values (date, recipient, hotel name …) and, for the rest
   of the text, one "blk-…" unit per paragraph (backend/python/document_blocks.py).
   Every line in the editor remembers which unit it belongs to (a block-level
   attribute, data-unit). Typing inside a line, pressing Enter (the new line
   keeps the unit), merging two lines or deleting several all keep that link,
   so a unit's edited HTML is simply "all the lines that carry its id". A unit
   whose lines are all gone was deleted ("" for a paragraph). Units still equal
   to the auto-generated wording are never stored. Edits go into
   record.editedFields[key] = HTML — the same shape the backend's
   replace_paragraph_range_with_html already consumes — and show up in the real
   PDF when Edit is turned off ("Done editing") or the page is regenerated;
   Download PDF / DOCX / Print regenerate first if anything is unsaved-to-PDF,
   so what is downloaded or printed is always what was edited.

   Where each unit sits (page, reading order, table row) comes from the
   backend's layout probe (docx_utils.ProbeShader) — read from the very same
   LibreOffice rendering as the PDF.

   Used by js/hotels.js (several records on one document — one per hotel):
     var editor = KhannaPreviewEditor.create({
       getHotels:      function () { return [...hotels]; },
       composeFields:  function (hotels) { return Promise<{fields: [...]}>; },
       onFieldChange:  function (hotelId, key, htmlOrNull) { ... persist ... },
     });
     KhannaDocumentViewer.mount(box, { ..., editor: editor });

   Every single-document page (Passport/Company Authorization, Invitation,
   Required Document Letter, Cover Letters) uses the one-record shortcut:
     var editor = KhannaPreviewEditor.createForDocument({
       getEditedFields: function () { return {key: html} | null; },
       composeFields:   function () { return Promise<{key: html}>; },
       onFieldChange:   function (key, htmlOrNull) { ... persist ... },
       fieldLabel:      function (key) { return "…"; },   // optional
     });
   and its loadPdf resolves {blob, filename, layout, hotelIds: ["doc"]} where
   `layout` is the JSON the backend's `format: "layout"` request returns.

   The viewer owns the "Edit" toggle (top of the Preview section).
   ========================================================================== */
(function (global) {
  "use strict";

  var utils = global.KhannaUtils;

  var PX_PER_PT = 96 / 72; // CSS pixels per PDF point at 100% zoom

  // Lazy-load the vendored Quill once.
  var QUILL_READY = null;
  function ensureQuill() {
    if (QUILL_READY) return QUILL_READY;
    var load = global.Quill
      ? Promise.resolve(global.Quill)
      : new Promise(function (resolve, reject) {
          var script = document.createElement("script");
          script.src = "assets/vendor/quill/quill.js";
          script.onload = function () {
            if (global.Quill) resolve(global.Quill);
            else reject(new Error("Quill loaded but window.Quill is missing"));
          };
          script.onerror = function () {
            reject(new Error("Could not load the editor library (assets/vendor/quill/quill.js)."));
          };
          document.head.appendChild(script);
        });
    QUILL_READY = load.then(function (Quill) {
      // Inline-style attributors so font/size are written as
      // style="font-family:…;font-size:…pt" (which the backend's HTML parser
      // reads) rather than Quill's default CSS classes. No whitelist: the
      // letters' own fonts and sizes (e.g. 10.5pt, "Times New Roman") must
      // survive a round trip.
      var Size = Quill.import("attributors/style/size");
      Size.whitelist = null;
      var Font = Quill.import("attributors/style/font");
      Font.whitelist = null;
      // Paragraph-level formats of Word's line-spacing menu, written as inline
      // style on the block (the backend reads them back: docx_utils parser).
      var Parchment = Quill.import("parchment");
      var blockScope = { scope: Parchment.Scope.BLOCK };
      Quill.register(
        {
          // Which unit of the letter (a named value or one paragraph) a line
          // belongs to. Block-scope, so Enter copies it to the new line.
          "formats/unit": new Parchment.Attributor("unit", "data-unit", blockScope),
          "formats/size": Size,
          "formats/font": Font,
          "formats/lineheight": new Parchment.StyleAttributor("lineheight", "line-height", blockScope),
          "formats/spacebefore": new Parchment.StyleAttributor("spacebefore", "margin-top", blockScope),
          "formats/spaceafter": new Parchment.StyleAttributor("spaceafter", "margin-bottom", blockScope),
        },
        true
      );
      return Quill;
    });
    return QUILL_READY;
  }

  var QUILL_FORMATS = [
    "bold", "italic", "underline", "strike", "script", "color", "background", "font", "size",
    "align", "indent", "list", "lineheight", "spacebefore", "spaceafter", "table", "unit",
  ];

  // A pdf font name (e.g. "DejaVuSans-Bold", "ArialMT") -> a CSS font stack
  // close enough to read like the printed value while editing it.
  function cssFontStack(pdfFontName) {
    var n = String(pdfFontName || "").replace(/^[A-Z]{6}\+/, "");
    var base = n.replace(/[-,](Bold|Italic|Oblique|Regular|BoldItalic|BoldOblique)$/i, "").replace(/MT$/, "");
    var friendly = base.replace(/([a-z])([A-Z])/g, "$1 $2");
    if (/dejavu/i.test(base)) return '"DejaVu Sans", Verdana, sans-serif';
    return (friendly ? '"' + friendly + '", ' : "") + "Arial, sans-serif";
  }

  function htmlEqual(a, b) {
    return (a == null ? null : String(a)) === (b == null ? null : String(b));
  }

  // A run's font that is not installed on this computer must not make the browser
  // fall back to its default (a serif) font: every font gets a sans-serif
  // fallback while editing, and the fallback is stripped again when saving.
  var FONT_FALLBACK = ", Arial, sans-serif";
  var FONT_FALLBACK_RE = /,\s*Arial,\s*sans-serif/g;

  var INLINE_FORMATS = ["bold", "italic", "underline", "strike", "script", "color", "background", "font", "size"];

  // Splits every "\n" of an inserted string into its own op (Delta merges "a\n"
  // into one op when the attributes match) and drops inline formats from the
  // newline itself, so each line's end can carry block formats on its own.
  function normaliseOps(ops) {
    var out = [];
    ops.forEach(function (op) {
      if (typeof op.insert !== "string") {
        out.push(op);
        return;
      }
      var parts = op.insert.split("\n");
      parts.forEach(function (piece, i) {
        if (piece) out.push({ insert: piece, attributes: op.attributes ? Object.assign({}, op.attributes) : undefined });
        if (i < parts.length - 1) {
          var attrs = Object.assign({}, op.attributes || {});
          INLINE_FORMATS.forEach(function (f) { delete attrs[f]; });
          out.push({ insert: "\n", attributes: attrs });
        }
      });
    });
    out.forEach(function (op) {
      if (op.attributes && !Object.keys(op.attributes).length) delete op.attributes;
    });
    if (!out.length || out[out.length - 1].insert !== "\n") out.push({ insert: "\n" });
    return out;
  }

  // Cells hold one line each in Quill: a unit that is several paragraphs is
  // joined into one line inside a table cell.
  function flattenToOneLine(ops) {
    var lastNewline = -1;
    ops.forEach(function (op, i) { if (op.insert === "\n") lastNewline = i; });
    return ops.map(function (op, i) {
      return op.insert === "\n" && i !== lastNewline ? { insert: " " } : op;
    });
  }

  function lineClean(domNode) {
    var clone = domNode.cloneNode(true);
    clone.removeAttribute("data-unit");
    // where the stage put the line is not part of the letter's text
    ["position", "left", "top", "width", "margin-top", "counter-reset"].forEach(function (p) { clone.style.removeProperty(p); });
    if (!clone.getAttribute("style")) clone.removeAttribute("style");
    return clone;
  }

  // One line of the editor as the HTML the backend reads (Quill-style).
  function lineHtml(domNode) {
    var tag = domNode.tagName;
    var clone = lineClean(domNode);
    var html;
    if (tag === "LI") {
      html = "<ol>" + clone.outerHTML + "</ol>";
    } else if (tag === "TD") {
      var cls = (domNode.className || "").split(/\s+/).filter(function (c) { return /^ql-(align|indent)/.test(c); }).join(" ");
      html = "<p" + (cls ? ' class="' + cls + '"' : "") + ">" + clone.innerHTML + "</p>";
    } else {
      html = clone.outerHTML;
    }
    return html.replace(/<p([^>]*)><br><\/p>/g, "<p$1></p>").replace(FONT_FALLBACK_RE, "");
  }

  // Reading order of the units: by page, then top-to-bottom, then left-to-right
  // (a table row reads left to right). The editor's lines follow this order so
  // the caret, selection and arrow keys move through the letter as it reads.
  function sortUnits(units) {
    return units.slice().sort(function (a, b) {
      var ra = a.info.rect, rb = b.info.rect;
      // units on the same printed row (within a third of the smaller height) read left to right
      var sameRow = a.info.page === b.info.page &&
        Math.min(ra[3], rb[3]) - Math.max(ra[1], rb[1]) > 0.6 * Math.min(ra[3] - ra[1], rb[3] - rb[1]);
      if (a.info.page !== b.info.page) return a.info.page - b.info.page;
      if (sameRow) return ra[0] - rb[0];
      return ra[1] - rb[1] || ra[0] - rb[0];
    });
  }

  function create(cfg) {
    var viewer = null;
    var getRecords = cfg.getRecords || cfg.getHotels;
    var layout = null; // {pages, groups|hotels:[{key:{page,rect,fontSize,bold,fontName,align,html?}}]}
    var hotelIds = []; // ids in the order the CURRENT pdf was generated from
    var baked = {}; // "hotelId|key" -> html|null as of the current PDF
    var composed = {}; // hotelId -> {key: html}
    var composePromise = Promise.resolve();
    var letter = null; // the open whole-letter editor, see openLetter()
    var ribbon = null;

    function hotelById(id) {
      var list = getRecords() || [];
      for (var i = 0; i < list.length; i++) if (list[i].id === id) return list[i];
      return null;
    }
    function editedHtml(hotelId, key) {
      var h = hotelById(hotelId);
      var v = h && h.editedFields ? h.editedFields[key] : null;
      return v == null ? null : v;
    }

    // Hotel Voucher's layout lists one entry per hotel under "hotels"; every
    // single-document letter's lists its one entry under "groups".
    function layoutGroups() {
      return layout ? layout.groups || layout.hotels || null : null;
    }

    function isBlockKey(key) {
      return typeof key === "string" && key.indexOf("blk-") === 0;
    }

    /* ---------------- ribbon (js/editor-ribbon.js) ------------------------ */
    function setToolbarEnabled(on) {
      if (ribbon) ribbon.setEnabled(on);
      syncResetAll();
    }

    // "Reset all" does not need anything selected — it only needs something
    // to reset.
    function editedCount() {
      var n = 0;
      (getRecords() || []).forEach(function (rec) {
        if (hotelIds.indexOf(rec.id) === -1) return;
        var ef = rec.editedFields || {};
        Object.keys(ef).forEach(function (k) { if (ef[k] != null) n += 1; });
      });
      return n;
    }

    function syncResetAll() {
      if (ribbon) ribbon.setResetAllCount(editedCount());
    }

    function syncToolbarState() {
      if (ribbon) ribbon.sync();
    }

    function resetAll() {
      (getRecords() || []).forEach(function (rec) {
        if (hotelIds.indexOf(rec.id) === -1) return;
        Object.keys(rec.editedFields || {}).forEach(function (k) {
          if (rec.editedFields[k] != null) cfg.onFieldChange(rec.id, k, null);
        });
      });
      // What is on the page is being thrown away: it must not be saved again
      // when the regenerated letter replaces it.
      if (letter) {
        clearTimeout(letter.saveTimer);
        letter.quill = null;
      }
      return viewer ? viewer.refresh() : Promise.resolve();
    }

    /* ---------------- units: what the editor is made of -------------------- */
    // The auto-generated wording of a unit (never a hand edit): the engine's
    // composed text for a named value, else the block's own original content
    // exported with the layout.
    function autoSource(rid, key, info) {
      var map = composed[rid] || {};
      if (map[key]) return { html: map[key], seeded: false };
      if (info && info.html) return { html: info.html, seeded: true };
      return { html: "<p>—</p>", seeded: false };
    }

    function collectUnits() {
      var groups = layoutGroups();
      var units = [];
      if (!groups) return units;
      groups.forEach(function (fields, hIdx) {
        var rid = hotelIds[hIdx];
        if (!rid) return;
        Object.keys(fields).forEach(function (key) {
          units.push({ rid: rid, key: key, id: rid + "|" + key, info: fields[key], block: isBlockKey(key) });
        });
      });
      return units;
    }

    // The Delta of the whole letter. `useOverrides` false builds the pristine,
    // auto-generated letter (what "Reset" returns to).
    function buildOps(Quill, q, units, useOverrides) {
      var ops = [];
      units.forEach(function (u) {
        var override = useOverrides ? editedHtml(u.rid, u.key) : null;
        var auto = autoSource(u.rid, u.key, u.info);
        var html = override != null ? override : auto.html;
        var unitOps = normaliseOps(q.clipboard.convert({ html: html }).ops);
        unitOps.forEach(function (op) {
          if (op.attributes && typeof op.attributes.font === "string" && op.attributes.font.indexOf(FONT_FALLBACK) === -1) {
            op.attributes.font = op.attributes.font.replace(/;+\s*$/, "") + FONT_FALLBACK;
          }
        });
        // A freshly-composed NAMED value must carry the template's own look
        // as EXPLICIT formatting: the backend writes an edited value as new
        // runs that copy the template's font/size/colour but not its
        // bold/alignment, so anything the template shows bold or centred
        // has to be stated here to survive the round trip. (Whole-document
        // blocks are seeded from the .docx with every format explicit.)
        if (override == null && !auto.seeded) {
          unitOps.forEach(function (op) {
            if (op.insert === "\n") {
              if (u.info.align && u.info.align !== "left" && !(op.attributes && op.attributes.align)) {
                op.attributes = Object.assign({}, op.attributes, { align: u.info.align });
              }
            } else if (u.info.bold && typeof op.insert === "string") {
              op.attributes = Object.assign({ bold: true }, op.attributes);
            }
          });
        }
        unitOps.forEach(function (op) {
          if (op.insert !== "\n") return;
          op.attributes = Object.assign({}, op.attributes, { unit: u.id });
        });
        ops = ops.concat(unitOps);
      });
      return ops;
    }

    // Every unit's current HTML, read from the editor's lines.
    function serialize(q, unitIds) {
      var out = {};
      var tablesDone = [];
      var lastId = unitIds[0] || null;
      q.getLines().forEach(function (line) {
        var dn = line.domNode;
        var id = dn.getAttribute && dn.getAttribute("data-unit");
        var html;
        if (dn.tagName === "TD" && !id) {
          // A table the user inserted: its cells belong to no unit of their own,
          // so the whole table is kept as one piece of the unit before it.
          var table = dn.closest("table");
          var keyed = table && table.querySelector("td[data-unit]");
          if (table && !keyed) {
            if (tablesDone.indexOf(table) !== -1) return;
            tablesDone.push(table);
            var tc = table.cloneNode(true);
            tc.removeAttribute("style"); // the stage's placement, not the table's
            html = tc.outerHTML;
          } else {
            html = lineHtml(dn);
          }
        } else {
          html = lineHtml(dn);
        }
        if (id && unitIds.indexOf(id) !== -1) lastId = id;
        else id = lastId; // a line with no (or an unknown) unit joins the unit before it
        if (!id) return;
        out[id] = (out[id] || "") + html;
      });
      return out;
    }

    // Per-unit look: the printed font and size.
    function unitCss(units) {
      return units.map(function (u) {
        var rules = [];
        if (u.info.fontSize) rules.push("font-size:" + u.info.fontSize + "pt");
        rules.push("font-family:" + cssFontStack(u.info.fontName));
        rules.push("line-height:1.2");
        if (/\|guestNames$/.test(u.id)) rules.push("counter-increment:lwnum");
        return '.lw-stage [data-unit="' + u.id + '"]{' + rules.join(";") + "}";
      }).join("\n");
    }

    /* ---------------- the whole-letter editor ------------------------------ */
    function unitAtSelection() {
      if (!letter || !letter.quill) return null;
      var range = letter.quill.getSelection() || letter.lastRange;
      if (!range) return null;
      var found = letter.quill.getLine(range.index);
      var line = found && found[0];
      var id = line && line.domNode.getAttribute("data-unit");
      return id && letter.units[id] ? letter.units[id] : null;
    }

    function openLetter(pane) {
      closeLetter();
      if (!pane || !layoutGroups()) return Promise.resolve();
      var token = {};
      letter = { token: token, pane: pane, quill: null, units: {}, shown: {}, orig: {}, saveTimer: null, lastRange: null };
      pane.innerHTML = '<p class="field-hint lw-status">Opening the letter…</p>';
      return Promise.all([ensureQuill(), composePromise]).then(function (res) {
        if (!letter || letter.token !== token) return;
        buildLetter(res[0]);
      });
    }

    /* ---------------- the page stage -------------------------------------- */
    // Edit mode looks exactly like the finished page: each page of the real PDF
    // is drawn as the background WITHOUT its text (pdf.js is told to skip glyphs;
    // shading, borders, logo, header and footer stay), and the editor's lines
    // sit exactly where the printed text was. The letterhead is therefore
    // visible, in place, while editing — never a different-looking "paper".
    var STAGE_GAP = 16; // px between pages
    var BACKDROP_RES = 2; // canvas pixels per CSS pixel of the page

    function pageHeightsPx() {
      return ((layout && layout.pages) || []).map(function (pg) { return Math.round(pg.height * PX_PER_PT); });
    }

    function renderBackdrop(pdfDoc, pageIndex, rectsPt) {
      return pdfDoc.getPage(pageIndex + 1).then(function (page) {
        var vp = page.getViewport({ scale: PX_PER_PT * BACKDROP_RES });
        var withText = document.createElement("canvas");
        var base = document.createElement("canvas");
        withText.width = base.width = Math.ceil(vp.width);
        withText.height = base.height = Math.ceil(vp.height);
        var ctxText = withText.getContext("2d");
        var ctxBase = base.getContext("2d");
        // Every glyph is drawn through fillText / strokeText: no-op'ing them
        // leaves only shading, borders and images.
        ctxBase.fillText = function () {};
        ctxBase.strokeText = function () {};
        return Promise.all([
          page.render({ canvasContext: ctxText, viewport: vp }).promise,
          page.render({ canvasContext: ctxBase, viewport: vp }).promise,
        ]).then(function () {
          var k = PX_PER_PT * BACKDROP_RES;
          var out = document.createElement("canvas");
          out.width = base.width;
          out.height = base.height;
          var c = out.getContext("2d");
          c.drawImage(base, 0, 0);
          // Anything that is NOT an editable unit (rare) keeps its printed text.
          c.save();
          c.beginPath();
          c.rect(0, 0, out.width, out.height);
          rectsPt.forEach(function (r) { c.rect(r[0] * k, r[1] * k, (r[2] - r[0]) * k, (r[3] - r[1]) * k); });
          c.clip("evenodd");
          c.drawImage(withText, 0, 0);
          c.restore();
          // Each unit's area is cleared to the colour around it, so the template's
          // own highlight behind a value does not stay behind once it is edited
          // (the editor draws the highlight itself).
          var probe = base.getContext("2d");
          function lum(d) { return 0.299 * d[0] + 0.587 * d[1] + 0.114 * d[2]; }
          rectsPt.forEach(function (r) {
            var x0 = r[0] * k, y0 = r[1] * k, x1 = r[2] * k, y1 = r[3] * k;
            var ym = (y0 + y1) / 2, xm = (x0 + x1) / 2, pad = 2.2 * k, inset = 1.4 * k;
            // The colour of the cell itself: its four corners (a highlight sits
            // behind the text only), the most common light colour wins; else
            // the colour just outside the box.
            var corners = [[x0 + inset, y0 + inset], [x1 - inset, y0 + inset], [x0 + inset, y1 - inset], [x1 - inset, y1 - inset]];
            var spots = corners.concat([[x0 - pad, ym], [x1 + pad, ym], [xm, y0 - pad], [xm, y1 + pad]]);
            var chosen = null;
            var votes = {};
            for (var i = 0; i < spots.length; i++) {
              var sx = Math.round(spots[i][0]), sy = Math.round(spots[i][1]);
              if (sx < 0 || sy < 0 || sx >= base.width || sy >= base.height) continue;
              var d = probe.getImageData(sx, sy, 1, 1).data;
              if (lum(d) < 140) continue; // a border line is dark: not a background
              if (i < 4) {
                var ck = d[0] + "," + d[1] + "," + d[2];
                votes[ck] = votes[ck] || { n: 0, d: d };
                votes[ck].n += 1;
              } else if (!chosen) {
                chosen = d;
              }
            }
            var best = null;
            Object.keys(votes).forEach(function (ck) { if (!best || votes[ck].n > best.n) best = votes[ck]; });
            if (best) chosen = best.d;
            if (!chosen) return;
            c.fillStyle = "rgb(" + chosen[0] + "," + chosen[1] + "," + chosen[2] + ")";
            c.fillRect(x0 + 0.5 * k, y0 + 0.5 * k, Math.max(0, x1 - x0 - k), Math.max(0, y1 - y0 - k));
          });
          return out;
        });
      });
    }

    // Puts every line of the editor where its unit was printed. A unit that has
    // grown (more lines than before) pushes the units printed below it down by
    // the same amount, keeping the printed gaps; the real page is regenerated
    // when editing is finished.
    function placeLines() {
      if (!letter || !letter.quill || !letter.stage) return;
      var q = letter.quill;
      var tops = letter.pageTops;
      var groups = [];
      var byUnit = {};
      var lastGroup = null;
      q.getLines().forEach(function (line) {
        var dn = line.domNode;
        var id = dn.getAttribute && dn.getAttribute("data-unit");
        if (dn.tagName === "TD") {
          var table = dn.closest("table");
          if (!table || table.getAttribute("data-lw-seen") === "1") return;
          table.setAttribute("data-lw-seen", "1");
          groups.push({ table: table, lines: [], prev: lastGroup });
          return;
        }
        if (!id || !letter.units[id]) id = lastGroup && lastGroup.id;
        if (!id) return;
        var g = byUnit[id];
        if (!g) {
          g = byUnit[id] = { id: id, unit: letter.units[id], lines: [] };
          groups.push(g);
        }
        g.lines.push(dn);
        lastGroup = g;
      });
      q.root.querySelectorAll("table[data-lw-seen]").forEach(function (t) { t.removeAttribute("data-lw-seen"); });

      var placed = {}; // page -> [{x0,x1,origBottom,newBottom}]
      groups.forEach(function (g) {
        var base = g.unit || (g.prev && g.prev.unit);
        if (!base) return;
        var info = base.info;
        var page = info.page;
        var rect = info.rect;
        var textBox = info.text || null; // where the printed text sat inside its box
        // The cell's own padding: the editor's lines keep the printed margins.
        var pad = textBox ? Math.max(0, Math.min(7.5, textBox[0] - rect[0])) : 0;
        var numbered = /\|guestNames$/.test(base.id); // its "1)" numbers sit left of the names
        if (numbered && textBox) pad = textBox[0] - rect[0];
        var left = (rect[0] + pad) * PX_PER_PT;
        var width = Math.max(30, (rect[2] - rect[0] - 2 * pad) * PX_PER_PT);
        var origTop = (textBox ? textBox[1] : rect[1]) * PX_PER_PT;
        var origBottom = (textBox ? textBox[3] : rect[3]) * PX_PER_PT;
        var fsPx = (info.fontSize || letter.baseSize || 11) * PX_PER_PT;
        // The printed baselines (first and last line) pin the text exactly,
        // whatever glyphs it holds; the ink box is only the fallback.
        var bl = info.baseline || null;
        if (bl) {
          origTop = bl[0] * PX_PER_PT - 0.8 * fsPx;
          origBottom = bl[1] * PX_PER_PT + 0.25 * fsPx;
        }
        // A paragraph that was printed over several lines wrapped where the
        // printed text ended (its right indent is not in the layout): wrap at the
        // same place, so the lines break exactly as on the finished page.
        var printedLines = bl ? (bl[1] - bl[0]) * PX_PER_PT > 0.8 * fsPx : (textBox && (textBox[3] - textBox[1]) * PX_PER_PT > 1.7 * fsPx);
        if (textBox && !numbered && printedLines) {
          width = Math.min(width, (textBox[2] - textBox[0]) * PX_PER_PT + 0.4 * fsPx);
          width = Math.max(width, 30);
        }
        // The first printed line's tallest glyph starts at origTop; the line box
        // starts that far above the glyph (so the baseline lands where it was).
        var shift = (bl ? 0.8 : 0.75) * fsPx - baselineOffset(base);
        if (g.table) { // a table inserted by the user follows the unit before it
          origTop = origBottom = g.prev ? (g.prev.origBottom != null ? g.prev.origBottom : origBottom) : origBottom;
          if (g.prev && g.prev.newTop != null) { left = g.prev.left; width = g.prev.width; }
          shift = 0;
        }
        // how far the units above (that overlap sideways) have grown
        var top = origTop;
        (placed[page] || []).forEach(function (p) {
          if (Math.min(p.x1, left + width) - Math.max(p.x0, left) <= 2) return;
          var need = p.newBottom + Math.max(0, origTop - p.origBottom);
          if (origTop >= p.origBottom - 0.5 && need > top) top = need;
        });
        var growth = 0;
        if (g.table) {
          var t = g.table;
          t.style.cssText = "position:absolute;left:" + left + "px;top:" + (letter.pageTops[page] + top) + "px;width:" + width + "px;";
          growth = Math.max(0, t.offsetHeight);
        } else {
          var y = top + shift;
          var lastBaseline = y;
          var bo = baselineOffset(base);
          g.lines.forEach(function (dn, i) {
            if (numbered) { dn.style.counterReset = i === 0 ? "lwnum" : ""; }
            dn.style.position = "absolute";
            dn.style.left = left + "px";
            dn.style.width = width + "px";
            dn.style.top = tops[page] + y + "px";
            dn.style.marginTop = "0px";
            lastBaseline = y + bo;
            y += dn.offsetHeight + (i < g.lines.length - 1 ? parseFloat(getComputedStyle(dn).marginBottom) || 0 : 0);
          });
          // Growth is only what goes beyond the printed bottom (a descender's
          // worth of slack is not growth).
          var printedLast = bl ? bl[1] * PX_PER_PT : origBottom - 0.25 * fsPx;
          growth = Math.max(0, lastBaseline - (printedLast + (top - origTop)) - 0.15 * fsPx);
        }
        g.origBottom = origBottom;
        g.newTop = top;
        g.left = left;
        g.width = width;
        var newBottom = origBottom + (top - origTop) + growth;
        (placed[page] = placed[page] || []).push({ x0: left, x1: left + width, origBottom: origBottom, newBottom: newBottom });
      });
    }

    // Distance from the top of a line box to its baseline, for the unit's font
    // (measured once per font and size in the stage itself).
    function baselineOffset(unit) {
      var info = unit.info;
      var key = (info.fontName || "") + "|" + (info.fontSize || "");
      letter.baselines = letter.baselines || {};
      if (letter.baselines[key] != null) return letter.baselines[key];
      var probe = document.createElement("div");
      probe.setAttribute("aria-hidden", "true");
      probe.style.cssText = "position:absolute;visibility:hidden;white-space:nowrap;left:0;top:0;line-height:1.2;" +
        "font-size:" + (info.fontSize || letter.baseSize || 11) + "pt;font-family:" + cssFontStack(info.fontName) + ";";
      probe.innerHTML = 'Hg<span style="display:inline-block;width:0;height:0"></span>';
      letter.stage.appendChild(probe);
      var off = probe.lastChild.offsetTop;
      letter.stage.removeChild(probe);
      letter.baselines[key] = off;
      return off;
    }

    function applyStageScale() {
      if (!letter || !letter.stage) return;
      var avail = letter.pane.clientWidth || letter.stageWidth;
      // The page keeps the size it has in the viewer (so switching to Edit does
      // not resize the letter), unless the pane is too narrow to hold it.
      var wanted = viewer && viewer.scale ? viewer.scale / PX_PER_PT : 1.1;
      var s = Math.max(0.25, Math.min(wanted, (avail - 4) / letter.stageWidth));
      letter.stage.style.transform = "scale(" + s + ")";
      letter.scaler.style.width = Math.round(letter.stageWidth * s) + "px";
      letter.scaler.style.height = Math.round(letter.stageHeight * s) + "px";
    }

    function buildLetter(Quill) {
      var pane = letter.pane;
      var Delta = Quill.import("delta");
      var list = sortUnits(collectUnits());
      var pages = (layout.pages && layout.pages.length) ? layout.pages : [{ width: 595, height: 842 }];
      var heights = pageHeightsPx();
      var pageW = Math.round(pages[0].width * PX_PER_PT);
      var pageTops = [];
      var total = 0;
      heights.forEach(function (h, i) { pageTops[i] = total; total += h + (i < heights.length - 1 ? STAGE_GAP : 0); });
      var sizes = list.map(function (u) { return u.info.fontSize; }).filter(Boolean).sort(function (a, b) { return a - b; });
      var baseSize = sizes.length ? sizes[Math.floor(sizes.length / 2)] : 11; // the usual size: the median

      letter.units = {};
      list.forEach(function (u) { letter.units[u.id] = u; });
      var unitIds = list.map(function (u) { return u.id; });
      letter.unitIds = unitIds;
      letter.pageTops = pageTops;
      letter.stageWidth = pageW;
      letter.stageHeight = total;

      pane.innerHTML =
        '<div class="lw">' +
        '<div class="lw-scaler" data-lw-scaler>' +
        '<div class="lw-stage" data-lw-stage style="width:' + pageW + "px;height:" + total + 'px;">' +
        "<style data-lw-style></style>" +
        heights.map(function (h, i) {
          return '<div class="lw-page" style="top:' + pageTops[i] + "px;height:" + h + 'px;" data-lw-page="' + i + '"></div>';
        }).join("") +
        '<div class="lw-quill" data-lw-quill></div>' +
        "</div></div></div>";
      pane.querySelector("[data-lw-style]").textContent = unitCss(list);
      letter.stage = pane.querySelector("[data-lw-stage]");
      letter.scaler = pane.querySelector("[data-lw-scaler]");
      applyStageScale();
      if (global.ResizeObserver) {
        letter.resizer = new global.ResizeObserver(function () { applyStageScale(); });
        letter.resizer.observe(pane);
      }

      // The page backgrounds are drawn from the real PDF (when it is loaded).
      var pdfDoc = viewer && viewer.pdfDoc;
      var token = letter.token;
      if (pdfDoc) {
        heights.forEach(function (h, i) {
          var rects = list.filter(function (u) { return u.info.page === i; }).map(function (u) { return u.info.rect; });
          renderBackdrop(pdfDoc, i, rects).then(function (canvas) {
            if (!letter || letter.token !== token) return;
            var host = letter.stage.querySelector('[data-lw-page="' + i + '"]');
            if (!host) return;
            canvas.className = "lw-page__bg";
            host.appendChild(canvas);
          }, function () { /* the page simply stays white */ });
        });
      }

      var mount = pane.querySelector("[data-lw-quill]");
      var q = new Quill(mount, {
        formats: QUILL_FORMATS,
        modules: { toolbar: false, table: true, history: { userOnly: true } },
        placeholder: "",
      });
      q.root.setAttribute("aria-label", "Letter text — edit like a Word document");
      installEditGuards(q);
      q.setContents(new Delta(buildOps(Quill, q, list, true)), "silent");
      q.history.clear();
      letter.quill = q;
      letter.baseSize = baseSize;
      letter.shown = serialize(q, unitIds);
      // What each unit is when nothing is edited by hand: only needed when
      // something already is (otherwise what is shown IS the original).
      var anyOverride = list.some(function (u) { return editedHtml(u.rid, u.key) != null; });
      if (!anyOverride) {
        letter.orig = Object.assign({}, letter.shown);
      } else {
        var holder = document.createElement("div");
        holder.style.cssText = "position:fixed;left:-99999px;top:0;width:600px;";
        document.body.appendChild(holder);
        var scratch = new Quill(holder, { formats: QUILL_FORMATS, modules: { toolbar: false, table: true } });
        scratch.setContents(new Delta(buildOps(Quill, scratch, list, false)), "silent");
        letter.orig = serialize(scratch, unitIds);
        document.body.removeChild(holder);
      }

      function relayout() {
        if (!letter || letter.quill !== q) return;
        cancelAnimationFrame(letter.layoutFrame);
        letter.layoutFrame = requestAnimationFrame(function () { placeLines(); });
      }
      letter.relayout = relayout;
      q.on("text-change", function (delta, old, source) {
        relayout();
        if (source !== "user") return;
        clearTimeout(letter.saveTimer);
        letter.saveTimer = setTimeout(persistLetter, 350);
        syncToolbarState();
      });
      q.on("selection-change", function (range) {
        if (range) letter.lastRange = range;
        syncToolbarState();
      });
      placeLines();
      if (document.fonts && document.fonts.ready) document.fonts.ready.then(relayout);
      setToolbarEnabled(true);
      q.focus({ preventScroll: true });
      q.setSelection(0, 0, "silent");
      letter.lastRange = q.getSelection();
      syncToolbarState();
    }

    /* ---------------- editing rules ------------------------------------- */
    // Pasted text is always plain text that takes on the formatting at the
    // caret: what a web page or another program brings along (a dark
    // background, its own font and size, colours) never reaches the letter.
    // On a document laid out in cells (the Hotel Voucher: cfg.cellUnits) every
    // value belongs to its own cell: nothing typed, pasted, deleted or merged
    // can move into the cell next to it, and a cell can be emptied but never
    // removed.
    function lineUnit(line) {
      return line && line.domNode && line.domNode.getAttribute ? line.domNode.getAttribute("data-unit") : null;
    }

    function inlineFormatsAt(q, range) {
      var fmt = {};
      var f = q.getFormat(range.index, Math.max(0, range.length || 0)) || {};
      INLINE_FORMATS.forEach(function (k) { if (f[k] != null && f[k] !== false) fmt[k] = f[k]; });
      return fmt;
    }

    // Deletes the selection but keeps every cell: for each unit the selection
    // touches, its text goes and the unit's last line break stays.
    function deleteKeepingCells(q, range) {
      var lines = q.getLines(range.index, range.length);
      var end = range.index + range.length;
      var groups = [];
      lines.forEach(function (line) {
        var id = lineUnit(line) || "";
        var g = groups[groups.length - 1];
        if (!g || g.id !== id) { g = { id: id, lines: [] }; groups.push(g); }
        g.lines.push(line);
      });
      groups.slice().reverse().forEach(function (g) {
        var first = g.lines[0];
        var last = g.lines[g.lines.length - 1];
        var from = Math.max(range.index, q.getIndex(first));
        var lastNewline = q.getIndex(last) + last.length() - 1; // index of the unit's final line break
        var to = Math.min(end, lastNewline);
        if (to > from) q.deleteText(from, to - from, "user");
      });
    }

    function pastePlain(q, text) {
      var range = q.getSelection(true);
      if (!range) return;
      var cells = !!cfg.cellUnits;
      if (cells) text = text.replace(/\s*[\r\n]+\s*/g, " ").trim();
      text = text.replace(/[\u200b\u200c\u200d\ufeff]/g, "");
      var fmt = inlineFormatsAt(q, range);
      var found = q.getLine(range.index);
      var unitId = found && found[0] ? lineUnit(found[0]) : null;
      if (range.length) {
        if (cells) deleteKeepingCells(q, range);
        else q.deleteText(range.index, range.length, "user");
      }
      if (!text) { q.setSelection(range.index, 0, "user"); return; }
      q.insertText(range.index, text, fmt, "user");
      if (!cells && unitId && text.indexOf("\n") !== -1) {
        // lines made by the paste belong to the unit they were pasted into
        q.formatLine(range.index, text.length, "unit", unitId, "user");
      }
      q.setSelection(range.index + text.length, 0, "user");
    }

    function installEditGuards(q) {
      var cells = !!cfg.cellUnits;
      q.root.addEventListener("paste", function (e) {
        var cd = e.clipboardData;
        if (!cd) return;
        var text = cd.getData("text/plain");
        if (!text && (!cd.types || Array.prototype.indexOf.call(cd.types, "text/html") === -1)) return; // files etc.: not ours
        e.preventDefault();
        e.stopImmediatePropagation();
        pastePlain(q, text || "");
      }, true);
      if (!cells) return;

      function addFirst(key, handler) {
        q.keyboard.addBinding({ key: key }, handler);
        var list = q.keyboard.bindings[key];
        list.unshift(list.pop()); // ahead of the editor's own Backspace / Delete
      }
      function guard(back) {
        return function (range) {
          if (range.length) {
            deleteKeepingCells(q, range);
            q.setSelection(range.index, 0, "user");
            return false;
          }
          var found = q.getLine(range.index);
          var line = found && found[0];
          if (!line) return true;
          var offset = found[1];
          if (back && offset === 0) {
            var prev = line.prev;
            return !!prev && lineUnit(prev) === lineUnit(line); // never merge into another cell
          }
          if (!back && offset === line.length() - 1) {
            var next = line.next;
            return !!next && lineUnit(next) === lineUnit(line);
          }
          return true;
        };
      }
      addFirst("Backspace", guard(true));
      addFirst("Delete", guard(false));

      // typing over, cutting or dragging away a selection (which can reach into
      // other cells): done here, so each cell keeps its own line
      q.root.addEventListener("beforeinput", function (e) {
        var type = e.inputType || "";
        var range = q.getSelection();
        if (!range || !range.length) return;
        var isInsert = type === "insertText" || type === "insertReplacementText";
        var isDelete = /^(deleteByCut|deleteContent|deleteByDrag|insertParagraph|insertLineBreak)/.test(type);
        if (!isInsert && !isDelete) return;
        e.preventDefault();
        var fmt = inlineFormatsAt(q, range);
        deleteKeepingCells(q, range);
        var at = range.index;
        if (isInsert && e.data) {
          q.insertText(at, e.data, fmt, "user");
          at += e.data.length;
        }
        q.setSelection(at, 0, "user");
      }, true);
    }

    function persistLetter() {
      if (!letter || !letter.quill) return;
      clearTimeout(letter.saveTimer);
      var now = serialize(letter.quill, letter.unitIds);
      letter.unitIds.forEach(function (id) {
        var u = letter.units[id];
        var html = now[id];
        if (html == null) html = u.block ? "" : "<p></p>"; // every line of it was deleted
        if (html === letter.shown[id]) return; // untouched since the last save
        letter.shown[id] = html;
        var target = html === letter.orig[id] ? null : html;
        if (!htmlEqual(target, editedHtml(u.rid, u.key))) cfg.onFieldChange(u.rid, u.key, target);
      });
      syncResetAll();
    }

    function closeLetter() {
      if (!letter) return;
      persistLetter();
      var pane = letter.pane;
      if (letter.resizer) letter.resizer.disconnect();
      cancelAnimationFrame(letter.layoutFrame);
      letter = null;
      if (pane) pane.innerHTML = "";
      setToolbarEnabled(false);
    }

    // "Reset" in the ribbon: the unit under the caret goes back to the
    // auto-generated wording.
    function resetActive() {
      var unit = unitAtSelection();
      if (!letter || !unit) return;
      persistLetter();
      cfg.onFieldChange(unit.rid, unit.key, null);
      rebuildLetter();
    }

    function rebuildLetter() {
      if (!letter) return Promise.resolve();
      var pane = letter.pane;
      var scroller = pane.closest(".doc-viewer__body");
      var top = scroller ? scroller.scrollTop : 0;
      return openLetter(pane).then(function () {
        if (scroller) scroller.scrollTop = top;
      });
    }

    /* ---------------- hooks the viewer calls ------------------------------- */
    function attach(v) {
      viewer = v;
      if (ribbon) ribbon.destroy();
      ribbon = global.KhannaEditorRibbon.create({
        host: v.formatToolsEl,
        getQuill: function () { return letter ? letter.quill : null; },
        getLastRange: function () { return letter ? letter.lastRange : null; },
        getBaseSize: function () {
          var u = unitAtSelection();
          return (u && u.info.fontSize) || (letter && letter.baseSize) || null;
        },
        onReset: resetActive,
        onResetAll: resetAll,
      });
      setToolbarEnabled(false);
      v.formatToolsEl.hidden = false;
    }

    function onResult(result) {
      var wasOpen = letter ? letter.pane : null;
      commit();
      layout = result.layout || null;
      hotelIds = result.hotelIds || [];
      baked = {};
      var hotels = getRecords() || [];
      hotelIds.forEach(function (id) {
        var h = null;
        for (var i = 0; i < hotels.length; i++) if (hotels[i].id === id) h = hotels[i];
        var ef = (h && h.editedFields) || {};
        Object.keys(ef).forEach(function (k) {
          baked[id + "|" + k] = ef[k] == null ? null : ef[k];
        });
      });
      composed = {};
      var snapshot = hotels.filter(function (h) { return hotelIds.indexOf(h.id) !== -1; });
      // The compose endpoint must see the hotels WITHOUT edits so the seed is
      // always the auto-generated wording (edits are layered on top).
      var plain = snapshot.map(function (h) {
        return Object.assign({}, h, { editedFields: null });
      });
      composePromise = plain.length
        ? Promise.resolve(cfg.composeFields(plain)).then(
            function (res) {
              (res && res.fields ? res.fields : []).forEach(function (f, i) {
                composed[snapshot[i].id] = f;
              });
            },
            function () { /* named values fall back to an em dash; the PDF itself is unaffected */ }
          )
        : Promise.resolve();
      // A regeneration while Edit is on (Reset all) re-opens the letter on the new layout.
      if (wasOpen && viewer && viewer.editing) openLetter(wasOpen);
    }

    // Kept for the viewer's per-page callback: nothing is laid over the PDF any more.
    function commit() {
      persistLetter();
    }

    function isDirty() {
      persistLetter();
      for (var i = 0; i < hotelIds.length; i++) {
        var h = hotelById(hotelIds[i]);
        var ef = (h && h.editedFields) || {};
        var keys = Object.keys(ef);
        for (var k = 0; k < keys.length; k++) {
          if (!htmlEqual(ef[keys[k]], baked[hotelIds[i] + "|" + keys[k]])) return true;
        }
        // an override that existed when the PDF was made and has since been reset
        var bakedKeys = Object.keys(baked);
        for (var b = 0; b < bakedKeys.length; b++) {
          if (bakedKeys[b].indexOf(hotelIds[i] + "|") === 0) {
            var key = bakedKeys[b].split("|")[1];
            if (baked[bakedKeys[b]] != null && ef[key] == null) return true;
          }
        }
      }
      return false;
    }

    // Edits made against text that has since changed (e.g. another applicant
    // was chosen) match no block of the regenerated page: report them.
    function unmatchedCount() {
      var u = layout && layout.unmatched;
      if (!u) return 0;
      return u.reduce(function (n, x) { return n + (Array.isArray(x) ? x.length : 1); }, 0);
    }

    return {
      attach: attach,
      unmatchedCount: unmatchedCount,
      editedCount: editedCount,
      resetAll: resetAll,
      onResult: onResult,
      openLetter: openLetter,
      closeLetter: closeLetter,
      commit: commit,
      isDirty: isDirty,
      hasLayout: function () { return !!layout; },
    };
  }

  // The one-record shortcut every single-document page uses (see header).
  function createForDocument(cfg) {
    function records() {
      return [{ id: "doc", editedFields: cfg.getEditedFields() || {} }];
    }
    return create({
      getRecords: records,
      composeFields: function () {
        return Promise.resolve(cfg.composeFields()).then(function (fields) {
          return { fields: [fields || {}] };
        });
      },
      onFieldChange: function (id, key, html) {
        cfg.onFieldChange(key, html);
      },
      fieldLabel: cfg.fieldLabel,
    });
  }

  global.KhannaPreviewEditor = { create: create, createForDocument: createForDocument };
})(window);
