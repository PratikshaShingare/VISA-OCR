"""
Khanna Travels & Holidays — Passport Lab (Streamlit)
====================================================

A LOCAL test bench: upload a passport photo/PDF, run it through several
extraction engines, and see them side by side so you can pick the one that
reads YOUR real-world passports best. It does not change the website.

Run:   streamlit run backend/python/passport_lab/app.py
(or double-click "Start Passport Lab.bat")

Privacy
-------
* Nothing is saved: the upload lives in a temporary file that is deleted as
  soon as the engines finish. No passport data is logged.
* The two CLOUD engines (Google Vision, OpenRouter AI) send the image to a
  third party, so they run ONLY if you tick the consent box AND the key is
  present in backend/python/.env. Keys are never shown here.
* Every result is a proposal — "OCR Extracted — Please Verify".
"""

from __future__ import annotations

import csv
import html
import io
import os
import sys
import tempfile

import streamlit as st

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.dirname(HERE)
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from passport_lab import engines as E  # noqa: E402

E.load_env_file()

st.set_page_config(page_title="Passport Lab — Khanna Travels", page_icon=None, layout="wide")

STATUS_STYLE = {
    "agree": ("#e6f4ea", "#137333", "Engines agree"),
    "disagree": ("#fce8e6", "#a50e0e", "Engines DISAGREE — check this one"),
    "single": ("#fef7e0", "#8a6100", "Only one engine produced a value"),
    "empty": ("#f1f3f4", "#5f6368", "No engine produced a value"),
}


def save_upload(uploaded) -> str:
    suffix = os.path.splitext(uploaded.name)[1].lower() or ".png"
    fd, path = tempfile.mkstemp(suffix=suffix, prefix="passport_lab_")
    with os.fdopen(fd, "wb") as fh:
        fh.write(uploaded.getvalue())
    return path


def pdf_page_count(path: str) -> int:
    if not path.lower().endswith(".pdf"):
        return 1
    import ocr_runner

    return len(ocr_runner.load_pages(path))


def mrz_block(res: dict) -> None:
    mrz = res.get("mrz")
    if not mrz:
        st.caption("No MRZ was read by this engine.")
        return
    st.code(f"{mrz['line1']}\n{mrz['line2']}", language=None)
    checks = mrz.get("checks") or {}
    st.write("Check digits: " + ", ".join(f"{k} {'✔' if v else '✘'}" for k, v in checks.items() if v is not None))
    st.write(f"Confidence: **{mrz.get('confidence', '-')}**")
    for rep in mrz.get("repairs") or []:
        st.warning(f"Corrected {rep['field']}: `{rep['from']}` → `{rep['to']}` — {rep['reason']}")


def comparison_table(rows, results) -> str:
    ok = [r for r in results if r["ok"]]
    head = "".join(f"<th>{html.escape(r['label'])}</th>" for r in ok)
    body = []
    for row in rows:
        bg, fg, tip = STATUS_STYLE[row["status"]]
        cells = "".join(
            f"<td>{html.escape(str(row['values'].get(r['engine'], '') or '—'))}</td>" for r in ok
        )
        zone = "MRZ" if row["inMrz"] else "printed"
        body.append(
            f"<tr style='background:{bg};color:{fg}' title='{html.escape(tip)}'>"
            f"<td><b>{html.escape(row['label'])}</b><br><span style='font-size:11px;opacity:.75'>{zone}</span></td>{cells}</tr>"
        )
    return (
        "<table style='width:100%;border-collapse:collapse' border='1' cellpadding='6'>"
        f"<thead><tr><th>Field</th>{head}</tr></thead><tbody>{''.join(body)}</tbody></table>"
    )


# ------------------------------------------------------------------ sidebar

st.sidebar.header("Engines")
status = E.key_status()
use = {
    "current": st.sidebar.checkbox(E.ENGINE_LABELS["current"], value=True, help="Exactly what the website does today."),
    "mrz_v2": st.sidebar.checkbox(E.ENGINE_LABELS["mrz_v2"], value=True, help="New: finds the MRZ anywhere, tries many reads, repairs characters using the passport's check digits."),
}
st.sidebar.markdown("**Cloud engines** (image is sent to a third party)")
consent = st.sidebar.checkbox("I agree to send this passport image to the selected cloud engines", value=False)
use["google"] = st.sidebar.checkbox(
    E.ENGINE_LABELS["google"], value=False, disabled=not (consent and status["google"]),
    help="Needs GOOGLE_VISION_API_KEY in backend/python/.env" if not status["google"] else None,
)
use["openrouter"] = st.sidebar.checkbox(
    E.ENGINE_LABELS["openrouter"], value=False, disabled=not (consent and status["openrouter"]),
    help="Needs OPENROUTER_API_KEY in backend/python/.env" if not status["openrouter"] else None,
)
st.sidebar.caption(
    f"Google key: {'found' if status['google'] else 'not set'} · OpenRouter key: {'found' if status['openrouter'] else 'not set'}"
)
st.sidebar.divider()
st.sidebar.caption("Use test or consented passports only. Nothing is saved by this page.")

# --------------------------------------------------------------------- main

st.title("Passport Lab")
st.write(
    "Upload a passport page, run the engines, and compare. Fields printed in the **MRZ** (the two lines of `<<<<` at the "
    "bottom) are protected by check digits, so they are the most trustworthy; **printed** fields (place of birth/issue, "
    "dates of issue) are not in the MRZ and are always only a proposal."
)

uploaded = st.file_uploader("Passport image or PDF", type=["png", "jpg", "jpeg", "webp", "bmp", "tif", "tiff", "pdf"])

if uploaded:
    path = save_upload(uploaded)
    try:
        pages = pdf_page_count(path)
        page_index = 0
        if pages > 1:
            page_index = int(st.number_input("PDF page", min_value=1, max_value=pages, value=1)) - 1
        left, right = st.columns([1, 2])
        with left:
            st.image(E.render_page_png(path, page_index), caption="Page being read", use_container_width=True)
        with right:
            chosen = [k for k, v in use.items() if v]
            if st.button("Run selected engines", type="primary", disabled=not chosen):
                results = []
                for key in chosen:
                    with st.spinner(f"Running {E.ENGINE_LABELS[key]} …"):
                        results.append(E.RUNNERS[key](path, page_index))
                st.session_state["results"] = results
                st.session_state["result_name"] = uploaded.name
    finally:
        try:
            os.remove(path)
        except OSError:
            pass

results = st.session_state.get("results")
if results and st.session_state.get("result_name") == (uploaded.name if uploaded else None):
    st.subheader("Side-by-side result")
    st.caption("OCR Extracted — Please Verify. Green = engines agree · Red = they disagree · Amber = only one engine had a value.")

    for r in results:
        if not r["ok"]:
            st.error(f"{r['label']}: {r['error']}")

    ok_results = [r for r in results if r["ok"]]
    if ok_results:
        rows = E.compare_engines(ok_results)
        st.markdown(comparison_table(rows, ok_results), unsafe_allow_html=True)
        st.caption("Time: " + " · ".join(f"{r['label']} {r['seconds']}s" for r in ok_results))

        st.subheader("MRZ details")
        cols = st.columns(len(ok_results))
        for col, r in zip(cols, ok_results):
            with col:
                st.markdown(f"**{r['label']}**" + (" ☁" if r["cloud"] else ""))
                mrz_block(r)
                for w in r["warnings"][:6]:
                    st.caption("• " + w)

        st.subheader("Score against the real passport (optional)")
        st.caption("Type what the passport REALLY says for the fields you want to check. Leave the rest blank.")
        truth = {}
        grid = st.columns(3)
        for i, field in enumerate(E.PASSPORT_FIELDS):
            truth[field] = grid[i % 3].text_input(E.FIELD_LABELS[field], key=f"truth_{field}", help="Dates as YYYY-MM-DD")
        scores = E.score_against_truth(ok_results, truth)
        if any(s["checked"] for s in scores.values()):
            for r in ok_results:
                s = scores[r["engine"]]
                st.markdown(
                    f"**{r['label']}** — {len(s['correct'])}/{s['checked']} correct"
                    + (f" · wrong: {', '.join(E.FIELD_LABELS[f] for f in s['wrong'])}" if s["wrong"] else "")
                    + (f" · missing: {', '.join(E.FIELD_LABELS[f] for f in s['missing'])}" if s["missing"] else "")
                )
        if st.checkbox("Add this passport to my scoreboard (kept only until you close this page)"):
            board = st.session_state.setdefault("board", [])
            if st.button("Add to scoreboard"):
                board.append({"file": uploaded.name if uploaded else "", "scores": scores})
                st.success("Added.")

board = st.session_state.get("board") or []
if board:
    st.subheader("Scoreboard (this session)")
    totals = {}
    for entry in board:
        for eng, s in entry["scores"].items():
            t = totals.setdefault(eng, {"correct": 0, "checked": 0})
            t["correct"] += len(s["correct"])
            t["checked"] += s["checked"]
    for eng, t in totals.items():
        pct = 100 * t["correct"] / t["checked"] if t["checked"] else 0
        st.write(f"**{E.ENGINE_LABELS[eng]}** — {t['correct']}/{t['checked']} fields correct ({pct:.0f}%) over {len(board)} passport(s)")
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["engine", "correct", "checked"])
    for eng, t in totals.items():
        w.writerow([E.ENGINE_LABELS[eng], t["correct"], t["checked"]])
    st.download_button("Download scoreboard (counts only, no passport data)", buf.getvalue(), "passport_lab_scoreboard.csv", "text/csv")
