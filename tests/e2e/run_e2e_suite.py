"""
Orchestrator for the Khanna Travels & Holidays end-to-end test suite.

Starts a static file server (if one isn't already serving the project) and
always starts its OWN backend process — killing whatever was already
listening on that port first, if anything was — so it holds a real handle
it can stop and restart on command. That matters specifically for the
"backend down" honest-failure script: several of this project's own
pre-Phase-13 down-tests (test_backend_down.py through
test_phase11_down.py) required an EXTERNAL orchestrator to actually stop
the backend before they'd produce a meaningful result; this script IS that
orchestrator, done properly and persisted instead of being redone ad hoc
by hand every time.

The backend is always left running when this script exits (success,
failure, or Ctrl-C), so a normal `python3 run_e2e_suite.py` run doesn't
leave the dev environment without a working backend afterwards.

Usage:
    python3 tests/e2e/run_e2e_suite.py

Environment overrides (also read by the individual scripts via
_common.py):
    KHANNA_E2E_STATIC_PORT   (default 8766)
    KHANNA_E2E_BACKEND_PORT  (default 8000)
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
import urllib.request

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.normpath(os.path.join(THIS_DIR, "..", ".."))
BACKEND_DIR = os.path.join(PROJECT_ROOT, "backend", "python")

STATIC_PORT = os.environ.get("KHANNA_E2E_STATIC_PORT", "8766")
BACKEND_PORT = os.environ.get("KHANNA_E2E_BACKEND_PORT", "8000")
STATIC_BASE = f"http://127.0.0.1:{STATIC_PORT}"
BACKEND_BASE = f"http://127.0.0.1:{BACKEND_PORT}"

UP_SCRIPTS = ["test_full_journey.py", "test_accessibility.py", "test_device_emulation.py"]
DOWN_SCRIPTS = ["test_backend_down_resilience.py"]


def _is_up(url: str) -> bool:
    try:
        urllib.request.urlopen(url, timeout=1)
        return True
    except Exception:
        return False


def _wait_for(url: str, timeout_s: float = 20.0) -> bool:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if _is_up(url):
            return True
        time.sleep(0.3)
    return False


def _wait_for_down(url: str, timeout_s: float = 10.0) -> bool:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if not _is_up(url):
            return True
        time.sleep(0.3)
    return not _is_up(url)


def kill_whatever_is_on(port: str):
    """Best-effort: frees the backend port before we start our own
    process there, in case a previous manual `uvicorn` run was left
    running. Not fatal if this can't find anything (e.g. `lsof`/`fuser`
    missing) — starting our own uvicorn will simply fail loudly instead,
    which is still an honest, understandable error."""
    for cmd in (["fuser", "-k", f"{port}/tcp"], ["bash", "-c", f"kill -9 $(lsof -ti:{port}) 2>/dev/null"]):
        try:
            subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)
        except Exception:
            continue
    time.sleep(0.5)


def start_static_server_if_needed():
    if _is_up(STATIC_BASE + "/index.html"):
        print(f"Static file server already serving {STATIC_BASE} — reusing it.")
        return None
    print(f"Starting static file server on {STATIC_PORT} ...")
    return subprocess.Popen(
        [sys.executable, "-m", "http.server", STATIC_PORT],
        cwd=PROJECT_ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def start_backend():
    return subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app:app", "--host", "127.0.0.1", "--port", BACKEND_PORT],
        cwd=BACKEND_DIR,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def stop(proc):
    if proc is None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=5)


def run_script(name: str) -> int:
    print(f"\n{'=' * 70}\nRunning {name}\n{'=' * 70}", flush=True)
    env = dict(os.environ, KHANNA_E2E_BASE=STATIC_BASE, KHANNA_E2E_BACKEND_BASE=BACKEND_BASE)
    return subprocess.run([sys.executable, name], cwd=THIS_DIR, env=env).returncode


def main() -> int:
    subprocess.run([sys.executable, os.path.join(THIS_DIR, "fixtures", "generate_fixtures.py")], check=True)

    static_proc = start_static_server_if_needed()
    if not _wait_for(STATIC_BASE + "/index.html"):
        print(f"FATAL: static file server never came up at {STATIC_BASE}")
        return 1

    if _is_up(BACKEND_BASE + "/api/health"):
        print(f"A backend is already listening on {BACKEND_PORT} — stopping it so this run owns a fresh one.")
        kill_whatever_is_on(BACKEND_PORT)
        _wait_for_down(BACKEND_BASE + "/api/health")

    print(f"Starting backend on {BACKEND_PORT} ...")
    backend_proc = start_backend()
    if not _wait_for(BACKEND_BASE + "/api/health"):
        print(f"FATAL: backend never came up at {BACKEND_BASE}")
        stop(backend_proc)
        return 1

    results: dict[str, int] = {}
    try:
        for script in UP_SCRIPTS:
            results[script] = run_script(script)

        print(f"\n{'=' * 70}\nStopping the backend for the honest-failure ('backend down') scripts\n{'=' * 70}", flush=True)
        stop(backend_proc)
        backend_proc = None
        if not _wait_for_down(BACKEND_BASE + "/api/health"):
            print("FATAL: backend still responding after being asked to stop — aborting the down-phase.")
            return 1

        for script in DOWN_SCRIPTS:
            results[script] = run_script(script)
    finally:
        print(f"\n{'=' * 70}\nRestarting the backend so it's left running afterwards\n{'=' * 70}", flush=True)
        backend_proc = start_backend()
        _wait_for(BACKEND_BASE + "/api/health")
        # The static server, if we started it, is left running too — this
        # is a dev environment, not a CI container that tears itself down.
        del static_proc

    print(f"\n{'=' * 70}\nSUMMARY\n{'=' * 70}")
    any_failed = False
    for script, code in results.items():
        status = "PASS" if code == 0 else "FAIL"
        any_failed = any_failed or code != 0
        print(f"  [{status}] {script} (exit code {code})")

    return 1 if any_failed else 0


if __name__ == "__main__":
    sys.exit(main())
