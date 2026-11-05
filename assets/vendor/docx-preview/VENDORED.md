# Vendored libraries (served locally — no CDN at runtime)

| File | Library | Version | Licence |
|---|---|---|---|
| docx-preview.min.js | docx-preview (https://github.com/VolodymyrBaydalka/docxjs) | 0.4.1 | Apache-2.0 |
| jszip.min.js | JSZip (https://stuartk.com/jszip) — required by docx-preview | 3.10.2 | MIT (or GPL-3.0-or-later); used under MIT — see JSZIP-LICENSE.md |

Used by js/document-viewer.js to show a generated Word (.docx) document in the browser when its PDF cannot be made (for example LibreOffice is not installed on the machine running the backend). Both are free and open source; there is no per-document cost and no external service.
