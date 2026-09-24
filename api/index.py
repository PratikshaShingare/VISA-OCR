"""
Khanna Travels & Holidays — Vercel serverless entry point
=============================================================

Vercel's Python runtime looks for a WSGI/ASGI `app` object in a file under
/api — this file is that entry point. It does not duplicate any backend
logic (project rule 15): it only makes backend/python's existing,
already-tested FastAPI app (backend/python/app.py) importable from here,
then re-exports it completely unchanged.

Locally, nothing uses this file at all — a staff member's own machine
keeps running `uvicorn app:app --port 8000` from backend/python/ exactly
as before (see backend/python/README.md). This file exists solely for the
Vercel deployment described in VERCEL_DEPLOYMENT.md, and every request to
/api/* is rewritten (see vercel.json) to invoke this one function, which
FastAPI's own router then dispatches internally — the routes themselves
(/api/health, /api/passport/process, /api/documents/..., etc.) are defined
exactly once, in app.py, regardless of which way the app is being run.
"""

import os
import sys

_BACKEND_DIR = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "backend", "python")
)
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

from app import app  # noqa: E402,F401 — the real FastAPI app, unmodified by this file
