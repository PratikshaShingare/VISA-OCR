/* ==========================================================================
   Khanna Travels & Holidays — Editable document preview (every document page)
   The preview stays the REAL generated PDF (js/document-viewer.js). This
   module lays a transparent, clickable "field" over every editable value of
   that page — hotel name, dates, guests, etc., never the fixed labels,
   headings or Hotel Policy text, which always come from the reference
   template (project rule 5). Clicking a field turns it into a small
   Word-like editor (Quill) right where the value is printed; the shared
   toolbar in the viewer's title line applies font, size, bold, italic,
   underline, text colour, highlight and alignment to whatever field is open.

   Edits are saved straight into the hotel record (hotel.editedFields[key] =
   HTML — the same shape the backend's replace_paragraph_range_with_html
   already consumes), so they survive closing the page. They show up in the
   real PDF when "Regenerate" is pressed; Download PDF / Download DOCX / Print
   regenerate first if there are unsaved-to-PDF edits, so what is downloaded
   or printed is always what is on screen.

   Where each field sits on the page comes from the backend
   (hotel_voucher_engine.compute_field_layout) — read from the very same
   LibreOffice rendering as the PDF, so overlays line up exactly.

   Used by js/hotels.js (several records on one document — one per hotel):
     var editor = KhannaPreviewEditor.create({
       getHotels:      function () { return [...hotels]; },
       composeFields:  function (hotels) { return Promise<{fields: [...]}>; },
       onFieldChange:  function (hotelId, key, htmlOrNull) { ... persist ... },
     });
     KhannaDocumentViewer.mount(box, { ..., editor: editor });

   Every single-document page (Passport/Company Authorization, Invitation,
   Required Document Letter, Europe Cover Letter) uses the one-record
   shortcut:
     var editor = KhannaPreviewEditor.createForDocument({
       getEditedFields: function () { return {key: html} | null; },
       composeFields:   function () { return Promise<{key: html}>; },
       onFieldChange:   function (key, htmlOrNull) { ... persist ... },
       fieldLabel:      function (key) { return "…"; },   // optional, for screen readers
     });
   and its loadPdf resolves {blob, filename, layout, hotelIds: ["doc"]} where
   `layout` is the JSON the backend's `format: "layout"` request returns.

   The viewer owns the "Edit" toggle (top of the Preview section): the
   fields are only live while it is on.
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
    "align", "indent", "list", "lineheight", "spacebefore", "spaceafter", "table",
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

  function create(cfg) {
    var viewer = null;
    var getRecords = cfg.getRecords || cfg.getHotels;
    var layout = null; // {pages, hotels:[{key:{page,rect,fontSize,bold,fontName,align}}]}
    var hotelIds = []; // ids in the order the CURRENT pdf was generated from
    var baked = {}; // "hotelId|key" -> html|null as of the current PDF
    var composed = {}; // hotelId -> {key: html}
    var composePromise = Promise.resolve();
    var active = null; // {el, quill, hotelId, key, touched, lastRange, saveTimer}
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
    function dataKey(key) {
      return key;
    }

    /* ---------------- ribbon (js/editor-ribbon.js) ------------------------ */
    function setToolbarEnabled(on) {
      if (ribbon) ribbon.setEnabled(on);
      syncResetAll();
    }

    // "Reset all" does not need a field to be open — it only needs something
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

    function resetAll() {
      active = null;
      (getRecords() || []).forEach(function (rec) {
        if (hotelIds.indexOf(rec.id) === -1) return;
        Object.keys(rec.editedFields || {}).forEach(function (k) {
          if (rec.editedFields[k] != null) cfg.onFieldChange(rec.id, k, null);
        });
      });
      return viewer ? viewer.refresh() : Promise.resolve();
    }

    function syncToolbarState() {
      if (ribbon) ribbon.sync();
    }

    /* ---------------- field overlays -------------------------------------- */
    // The value an editor starts from: a hand edit if there is one, else the
    // engine's composed wording (named fields), else the block's original
    // content exported with the layout (whole-document blocks).
    function layoutInfo(hotelId, key) {
      var groups = layoutGroups();
      var idx = hotelIds.indexOf(hotelId);
      return groups && idx !== -1 && groups[idx] ? groups[idx][key] || null : null;
    }
    function baseHtmlFor(hotelId, key) {
      var override = editedHtml(hotelId, dataKey(key));
      if (override != null) return { html: override, fromOverride: true };
      var map = composed[hotelId] || {};
      if (map[dataKey(key)]) return { html: map[dataKey(key)], fromOverride: false };
      var info = layoutInfo(hotelId, key);
      if (info && info.html) return { html: info.html, fromOverride: false, seeded: true };
      return { html: "<p>—</p>", fromOverride: false };
    }

    function isBlockKey(key) {
      return typeof key === "string" && key.indexOf("blk-") === 0;
    }

    function isEditedUnbaked(hotelId, key) {
      return !htmlEqual(editedHtml(hotelId, dataKey(key)), baked[hotelId + "|" + dataKey(key)]);
    }

    // The text inside a field is laid out at its natural size (1pt = 4/3 px,
    // so the document's own point sizes — also the ones the ribbon sets — mean
    // what they say) and the whole thing is zoomed to the page's current
    // scale; the field's own box is in on-screen pixels.
    function fieldStyle(info, scale) {
      var pt = info.fontSize || 11;
      return (
        "font-size:" + pt + "pt;" +
        "font-family:" + cssFontStack(info.fontName) + ";" +
        (info.bold && !info.html ? "font-weight:700;" : "")
      );
    }

    function staticView(el) {
      // An edited-but-not-yet-regenerated value: show the user's text over
      // the (stale) PDF text so they can see what they typed.
      var hotelId = el.getAttribute("data-pe-hotel");
      var key = el.getAttribute("data-pe-key");
      var holder = el.querySelector(".pe-field__text");
      var edited = isEditedUnbaked(hotelId, key);
      el.classList.toggle("is-edited", edited);
      if (edited) holder.innerHTML = baseHtmlFor(hotelId, key).html;
      else holder.innerHTML = "";
    }

    // The page colour under a value (so an edited value can cover the stale
    // PDF text behind it). Samples a small grid inside the value's rectangle
    // and takes the LIGHTEST opaque pixel: a single pixel can land on a letter
    // (dark), and a canvas that is still being redrawn after a zoom is fully
    // transparent (reads as black) — either used to turn the open value black.
    // Anything that is not clearly a light page colour falls back to white.
    function samplePageColour(ctx, canvas, rect, scale) {
      try {
        var dpr = global.devicePixelRatio || 1;
        var c2d = canvas.getContext("2d");
        var best = null;
        var bestLum = -1;
        for (var iy = 0; iy < 3; iy++) {
          for (var ix = 0; ix < 3; ix++) {
            var fx = rect[0] + (rect[2] - rect[0]) * (0.06 + 0.44 * ix);
            var fy = rect[1] + (rect[3] - rect[1]) * (0.06 + 0.44 * iy);
            var px = Math.max(0, Math.min(canvas.width - 1, Math.round(fx * scale * dpr)));
            var py = Math.max(0, Math.min(canvas.height - 1, Math.round(fy * scale * dpr)));
            var d = c2d.getImageData(px, py, 1, 1).data;
            if (d[3] < 250) continue; // not painted (yet)
            var lum = 0.299 * d[0] + 0.587 * d[1] + 0.114 * d[2];
            if (lum > bestLum) {
              bestLum = lum;
              best = d;
            }
          }
        }
        if (!best || bestLum < 170) return "#fff";
        return "rgb(" + best[0] + "," + best[1] + "," + best[2] + ")";
      } catch (err) {
        return "#fff";
      }
    }

    function buildOverlays(ctxInfo) {
      var overlayEl = ctxInfo.overlayEl;
      overlayEl.innerHTML = "";
      if (!layout || !layoutGroups()) return;
      var scale = ctxInfo.scale;
      layoutGroups().forEach(function (fields, hIdx) {
        var hotelId = hotelIds[hIdx];
        if (!hotelId) return;
        Object.keys(fields).forEach(function (key) {
          var info = fields[key];
          if (info.page !== ctxInfo.pageNumber - 1) return;
          var r = info.rect;
          var el = document.createElement("div");
          el.className = "pe-field" + (isBlockKey(key) ? " pe-field--block" : "");
          el.setAttribute("data-pe-hotel", hotelId);
          el.setAttribute("data-pe-key", key);
          el.setAttribute("data-pe-hotel-index", String(hIdx));
          el.style.left = r[0] * scale + "px";
          el.style.top = r[1] * scale + "px";
          el.style.width = (r[2] - r[0]) * scale + "px";
          el.style.height = (r[3] - r[1]) * scale + "px";
          el.style.setProperty("--pe-pad", (4 * scale).toFixed(1) + "px");
          el.style.setProperty("--pe-bg", samplePageColour(null, ctxInfo.canvasEl, r, scale));
          el._peResample = function () {
            el.style.setProperty("--pe-bg", samplePageColour(null, ctxInfo.canvasEl, r, scale));
          };
          el.style.setProperty("--pe-h", ((r[3] - r[1]) * scale).toFixed(1) + "px");
          el.setAttribute("tabindex", "0");
          el.setAttribute("role", "textbox");
          var plain = isBlockKey(key)
            ? (info.html || "").replace(/<[^>]*>/g, " ").replace(/\s+/g, " ").trim().slice(0, 60)
            : "";
          el.setAttribute(
            "aria-label",
            isBlockKey(key)
              ? "Edit text: " + (plain || "paragraph")
              : cfg.fieldLabel
              ? "Edit " + cfg.fieldLabel(key, hIdx)
              : "Edit " + key.replace(/([A-Z])/g, " $1").toLowerCase() + " of hotel " + (hIdx + 1)
          );
          el.title = "Click to edit";
          var text = document.createElement("div");
          text.className = "pe-field__text";
          text.style.cssText = fieldStyle(info, scale);
          text.style.zoom = String(scale / PX_PER_PT);
          text.style.width = ((r[2] - r[0]) - 8) * PX_PER_PT + "px";
          el.appendChild(text);
          overlayEl.appendChild(el);
          staticView(el);
        });
      });
    }

    // Hotel Voucher's layout lists one entry per hotel under "hotels"; every
    // single-document letter's lists its one entry under "groups".
    function layoutGroups() {
      return layout ? layout.groups || layout.hotels || null : null;
    }

    function fieldInfo(el) {
      var hIdx = parseInt(el.getAttribute("data-pe-hotel-index"), 10);
      var groups = layoutGroups();
      return groups && groups[hIdx] ? groups[hIdx][el.getAttribute("data-pe-key")] : null;
    }

    // opts.caret: "start" | "end" (keyboard moves between fields) or
    // {x, y} (a mouse click) — where the caret goes once the editor is open.
    function activate(el, opts) {
      if (active && active.el === el) return;
      commit();
      var hotelId = el.getAttribute("data-pe-hotel");
      var key = el.getAttribute("data-pe-key");
      var info = fieldInfo(el) || {};
      Promise.all([ensureQuill(), composePromise]).then(function (res) {
        var Quill = res[0];
        if (!el.isConnected) return; // page re-rendered while loading
        if (active && active.el === el) return;
        var holder = el.querySelector(".pe-field__text");
        holder.innerHTML = "";
        if (el._peResample) el._peResample(); // the page is painted by now
        el.classList.add("is-active");
        var mount = document.createElement("div");
        holder.appendChild(mount);
        var q = new Quill(mount, {
          formats: QUILL_FORMATS,
          modules: { toolbar: false, table: true, history: { userOnly: true } },
          placeholder: "—",
        });
        var base = baseHtmlFor(hotelId, key);
        q.setContents(q.clipboard.convert({ html: base.html }), "silent");
        if (!base.fromOverride && !base.seeded) {
          // A freshly-seeded NAMED value must carry the template's own look as
          // EXPLICIT formatting: the backend writes an edited value as new
          // runs that copy the template's font/size/colour but not its
          // bold/alignment, so anything the template shows bold or centred
          // has to be stated here to survive the round trip. (Whole-document
          // blocks are seeded from the .docx with every format explicit.)
          var len = q.getLength();
          if (info.bold) q.formatText(0, len, "bold", true, "silent");
          if (info.align && info.align !== "left") q.formatLine(0, len, "align", info.align, "silent");
        }
        q.history.clear();
        active = { el: el, quill: q, hotelId: hotelId, key: key, touched: false, lastRange: null, saveTimer: null, baseSize: info.fontSize || null };
        // A value that was only touched (typed then undone) and is still what
        // the auto-generated text would be is not a hand edit — never stored.
        active.initialHtml = base.fromOverride ? null : currentHtml(active);
        q.on("text-change", function (delta, old, source) {
          if (source !== "user") return;
          active.touched = true;
          clearTimeout(active.saveTimer);
          active.saveTimer = setTimeout(persistActive, 250);
          syncToolbarState();
        });
        q.on("selection-change", function (range) {
          if (range) active.lastRange = range;
          syncToolbarState();
        });
        q.root.addEventListener("keydown", onEditorKey);
        setToolbarEnabled(true);
        q.focus();
        placeCaret(q, opts && opts.caret);
        active.lastRange = q.getSelection();
        syncToolbarState();
      });
    }

    function placeCaret(q, where) {
      var end = Math.max(0, q.getLength() - 1);
      if (where === "start") return q.setSelection(0, 0, "silent");
      if (where && typeof where === "object") {
        // The point the user clicked, inside the freshly opened editor.
        var range = null;
        if (document.caretPositionFromPoint) {
          var pos = document.caretPositionFromPoint(where.x, where.y);
          if (pos) {
            range = document.createRange();
            range.setStart(pos.offsetNode, pos.offset);
          }
        } else if (document.caretRangeFromPoint) {
          range = document.caretRangeFromPoint(where.x, where.y);
        }
        if (range && q.root.contains(range.startContainer)) {
          var sel = global.getSelection();
          sel.removeAllRanges();
          range.collapse(true);
          sel.addRange(range);
          q.getSelection(); // lets Quill read the native selection
          return;
        }
      }
      q.setSelection(end, 0, "silent");
    }

    // Arrow keys carry the caret from one block of the page to the next, the
    // way they do through a Word document.
    function neighbourField(dir) {
      if (!active || !viewer || !viewer.overlayEl) return null;
      var fields = Array.prototype.slice.call(viewer.overlayEl.querySelectorAll(".pe-field"));
      var rect = function (f) { return f.getBoundingClientRect(); };
      fields.sort(function (a, b) {
        var ra = rect(a);
        var rb = rect(b);
        return Math.abs(ra.top - rb.top) < 2 ? ra.left - rb.left : ra.top - rb.top;
      });
      var i = fields.indexOf(active.el);
      return i === -1 ? null : fields[i + dir] || null;
    }
    function onEditorKey(e) {
      if (!active || !active.quill || e.shiftKey || e.ctrlKey || e.metaKey || e.altKey) return;
      var q = active.quill;
      var sel = q.getSelection();
      if (!sel || sel.length) return;
      var last = Math.max(0, q.getLength() - 1);
      var forward = false;
      var backward = false;
      if (e.key === "ArrowRight") forward = sel.index >= last;
      else if (e.key === "ArrowLeft") backward = sel.index <= 0;
      else if (e.key === "ArrowDown") forward = Math.abs(q.getBounds(sel.index).top - q.getBounds(last).top) < 2;
      else if (e.key === "ArrowUp") backward = Math.abs(q.getBounds(sel.index).top - q.getBounds(0).top) < 2;
      if (!forward && !backward) return;
      var next = neighbourField(forward ? 1 : -1);
      if (!next) return;
      e.preventDefault();
      activate(next, { caret: forward ? "start" : "end" });
    }

    function currentHtml(a) {
      var html = a.quill.root.innerHTML;
      return html === "<p><br></p>" ? "<p></p>" : html;
    }

    function persistActive() {
      if (!active || !active.touched) return;
      clearTimeout(active.saveTimer);
      if (active.initialHtml != null && currentHtml(active) === active.initialHtml) {
        // Back to the untouched wording: drop any override this editing session created.
        if (editedHtml(active.hotelId, dataKey(active.key)) != null) cfg.onFieldChange(active.hotelId, dataKey(active.key), null);
        syncResetAll();
        return;
      }
      cfg.onFieldChange(active.hotelId, dataKey(active.key), currentHtml(active));
      syncResetAll();
    }

    function commit() {
      if (!active) return;
      var a = active;
      persistActive();
      active = null;
      a.el.classList.remove("is-active");
      if (a.quill) a.quill = null;
      if (a.el.isConnected) {
        staticView(a.el);
        // Its mirror (the same value printed twice on the voucher) must show the edit too.
        refreshMirrors();
      }
      setToolbarEnabled(false);
      syncToolbarState();
    }

    function refreshMirrors() {
      var overlayEl = viewer && viewer.overlayEl;
      if (!overlayEl) return;
      Array.prototype.forEach.call(overlayEl.querySelectorAll(".pe-field"), function (f) {
        if (!f.classList.contains("is-active")) staticView(f);
      });
    }

    function resetActive() {
      if (!active) return;
      var a = active;
      clearTimeout(a.saveTimer);
      cfg.onFieldChange(a.hotelId, dataKey(a.key), null);
      var el = a.el;
      active = null;
      el.classList.remove("is-active");
      staticView(el);
      refreshMirrors();
      setToolbarEnabled(false);
      activate(el);
    }

    function onOverlayClick(e) {
      var el = e.target.closest(".pe-field");
      if (!el || !viewer.overlayEl.contains(el)) return;
      if (el.classList.contains("is-active")) return; // a click inside the open editor is just editing
      activate(el, { caret: { x: e.clientX, y: e.clientY } });
    }
    function onOverlayKey(e) {
      if ((e.key === "Enter" || e.key === " ") && e.target.classList && e.target.classList.contains("pe-field")) {
        e.preventDefault();
        activate(e.target);
      } else if (e.key === "Escape" && active) {
        var el = active.el;
        commit();
        el.focus();
      }
    }

    /* ---------------- hooks the viewer calls ------------------------------- */
    function attach(v) {
      viewer = v;
      if (ribbon) ribbon.destroy();
      ribbon = global.KhannaEditorRibbon.create({
        host: v.formatToolsEl,
        getQuill: function () { return active ? active.quill : null; },
        getLastRange: function () { return active ? active.lastRange : null; },
        getBaseSize: function () { return active ? active.baseSize : null; },
        onReset: resetActive,
        onResetAll: resetAll,
      });
      v.overlayEl.addEventListener("click", onOverlayClick);
      v.overlayEl.addEventListener("keydown", onOverlayKey);
      setToolbarEnabled(false);
      v.formatToolsEl.hidden = false;
    }

    function onResult(result) {
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
      // always the auto-generated wording (edits are layered on top above).
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
            function () { /* overlays fall back to an em dash; the PDF itself is unaffected */ }
          )
        : Promise.resolve();
    }

    function onPageRendered(ctxInfo) {
      commit();
      buildOverlays(ctxInfo);
      setToolbarEnabled(false);
    }

    function isDirty() {
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
      onPageRendered: onPageRendered,
      commit: commit,
      isDirty: function () {
        persistActive();
        return isDirty();
      },
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
