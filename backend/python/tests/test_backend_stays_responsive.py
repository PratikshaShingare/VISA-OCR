"""
The backend must keep answering (login, health, other pages) while a slow OCR
read is running. The OCR endpoints used to run the blocking read directly on
the server's event loop, which froze every other request until it finished —
including login.

This needs a real server (an in-process TestClient gives each request its own
event loop, which would hide the problem), so uvicorn is started on a free
port in a background thread. OCR itself is replaced by a sleep: the test is
about the server, not the OCR engine.
"""

import socket
import threading
import time

import pytest
import requests
import uvicorn

import app as app_module
import hotel_voucher_ocr
import ocr_runner

SLOW_SECONDS = 1.5


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def server(monkeypatch):
    def slow_passport(path, page_index=0, forced_rotation=None):
        time.sleep(SLOW_SECONDS)
        return {"pageKind": "other", "fields": {}, "warnings": [], "notices": []}

    def slow_voucher(path, page_index=0):
        time.sleep(SLOW_SECONDS)
        return {"fields": {}, "guestNames": [], "warnings": [], "totalPages": 1, "voucherType": "unknown"}

    monkeypatch.setattr(ocr_runner, "process_passport_file", slow_passport)
    monkeypatch.setattr(hotel_voucher_ocr, "process_hotel_voucher_file", slow_voucher)
    monkeypatch.setattr(hotel_voucher_ocr, "enrich_with_hotel_lookup", lambda r: r)

    port = _free_port()
    srv = uvicorn.Server(uvicorn.Config(app_module.app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=srv.run, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{port}"
    for _ in range(100):
        try:
            requests.get(base + "/api/health", timeout=1)
            break
        except requests.RequestException:
            time.sleep(0.1)
    yield base
    srv.should_exit = True
    thread.join(timeout=5)


@pytest.mark.parametrize("path", ["/api/passport/process", "/api/hotel-voucher/process"])
def test_other_requests_are_answered_while_ocr_runs(server, path):
    started = {}

    def slow_request():
        started["status"] = requests.post(
            server + path, files={"file": ("x.png", b"\x89PNG\r\n\x1a\n" + b"0" * 64, "image/png")}, timeout=30
        ).status_code

    worker = threading.Thread(target=slow_request)
    worker.start()
    time.sleep(0.4)  # the slow read is now in progress
    t0 = time.time()
    health = requests.get(server + "/api/health", timeout=10)
    waited = time.time() - t0
    worker.join(timeout=30)
    assert health.status_code == 200
    assert waited < 0.8, f"/api/health had to wait {waited:.2f}s for an OCR read to finish"
    assert started.get("status") == 200


def test_parallel_ocr_reads_are_capped(monkeypatch):
    """No more than MAX_PARALLEL_OCR_JOBS reads run at the same time."""
    running = 0
    peak = 0
    lock = threading.Lock()

    def job():
        nonlocal running, peak
        with lock:
            running += 1
            peak = max(peak, running)
        time.sleep(0.2)
        with lock:
            running -= 1

    threads = [threading.Thread(target=app_module._limited_ocr_call, args=(job,)) for _ in range(6)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert 1 <= peak <= app_module.MAX_PARALLEL_OCR_JOBS
