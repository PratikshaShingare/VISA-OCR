"""
Unit tests for pdf_conversion.py — the docx->PDF provider selection/
dispatch logic introduced for the Vercel-serverless architecture
(CloudConvert replaces local LibreOffice/'soffice' there, since no system
binary can be installed in a serverless function).

The real end-to-end "does this actually produce a PDF" test already exists
in test_docx_utils.py (test_convert_docx_bytes_to_pdf_produces_a_real_pdf)
and continues to pass unchanged against the local LibreOffice path — this
file only covers the new SELECTION logic and honest failure messages, and
never makes a real network call to CloudConvert (no live API key exists in
this environment, and a unit test must not depend on, or spend, a real
paid quota).
"""

import pytest

import pdf_conversion


def test_auto_uses_local_when_no_cloudconvert_key_is_set(monkeypatch):
    monkeypatch.delenv("PDF_CONVERSION_PROVIDER", raising=False)
    monkeypatch.delenv("CLOUDCONVERT_API_KEY", raising=False)
    calls = []
    monkeypatch.setattr(pdf_conversion, "_find_soffice", lambda: "/fake/soffice")
    monkeypatch.setattr(pdf_conversion, "convert_via_local_libreoffice", lambda b, base_name: calls.append("local") or b"LOCAL")
    monkeypatch.setattr(pdf_conversion, "convert_via_cloudconvert", lambda b, base_name: calls.append("cloud") or b"CLOUD")

    result = pdf_conversion.convert_docx_bytes_to_pdf(b"fake docx bytes", base_name="test")
    assert result == b"LOCAL"
    assert calls == ["local"]


def test_auto_uses_cloudconvert_once_an_api_key_is_present(monkeypatch):
    monkeypatch.delenv("PDF_CONVERSION_PROVIDER", raising=False)
    monkeypatch.setenv("CLOUDCONVERT_API_KEY", "fake-test-key")
    calls = []
    monkeypatch.setattr(pdf_conversion, "_find_soffice", lambda: "/fake/soffice")
    monkeypatch.setattr(pdf_conversion, "convert_via_local_libreoffice", lambda b, base_name: calls.append("local") or b"LOCAL")
    monkeypatch.setattr(pdf_conversion, "convert_via_cloudconvert", lambda b, base_name: calls.append("cloud") or b"CLOUD")

    result = pdf_conversion.convert_docx_bytes_to_pdf(b"fake docx bytes", base_name="test")
    assert result == b"CLOUD"
    assert calls == ["cloud"]


def test_explicit_local_choice_is_honored_even_with_a_cloudconvert_key_set(monkeypatch):
    monkeypatch.setenv("PDF_CONVERSION_PROVIDER", "local")
    monkeypatch.setenv("CLOUDCONVERT_API_KEY", "fake-test-key")
    calls = []
    monkeypatch.setattr(pdf_conversion, "_find_soffice", lambda: "/fake/soffice")
    monkeypatch.setattr(pdf_conversion, "convert_via_local_libreoffice", lambda b, base_name: calls.append("local") or b"LOCAL")
    monkeypatch.setattr(pdf_conversion, "convert_via_cloudconvert", lambda b, base_name: calls.append("cloud") or b"CLOUD")

    result = pdf_conversion.convert_docx_bytes_to_pdf(b"fake docx bytes", base_name="test")
    assert result == b"LOCAL"
    assert calls == ["local"]


def test_cloudconvert_without_an_api_key_raises_a_clear_actionable_error(monkeypatch):
    monkeypatch.delenv("CLOUDCONVERT_API_KEY", raising=False)
    with pytest.raises(pdf_conversion.PdfConversionError, match="CLOUDCONVERT_API_KEY"):
        pdf_conversion.convert_via_cloudconvert(b"fake docx bytes", base_name="test")


def test_docx_utils_wrapper_converts_a_cloudconvert_failure_into_docxbuilderror(monkeypatch):
    import docx_utils

    def _boom(docx_bytes, base_name="document"):
        raise pdf_conversion.PdfConversionError("simulated failure")

    monkeypatch.setattr(pdf_conversion, "convert_docx_bytes_to_pdf", _boom)
    with pytest.raises(docx_utils.DocxBuildError, match="simulated failure"):
        docx_utils.convert_docx_bytes_to_pdf(b"fake docx bytes", base_name="test")


# ---------------------------------------------------------------------------
# convert_via_cloudconvert's own internal request/poll/download logic.
#
# This session's sandbox cannot reach api.cloudconvert.com at all (outbound
# HTTPS to that host is blocked by this environment's own network policy —
# confirmed directly: a real request to it returns a connection failure, not
# an HTTP error), so a genuine live round-trip against CloudConvert cannot be
# executed from here. That is a constraint of this development sandbox, not
# of Vercel (a deployed serverless function has normal outbound internet
# access) — but it means the tests above, which only ever exercised the
# "no API key" and provider-SELECTION paths, had never actually verified
# that convert_via_cloudconvert() correctly walks CloudConvert's own
# multi-step job API (create job -> read the upload form back -> upload the
# file -> poll until finished -> extract the export URL -> download the
# bytes). These tests close that gap the honest way available in this
# sandbox: a fake `requests` double that responds exactly the shape
# CloudConvert's real API documents at each step, so a real bug in how this
# function walks that contract (a wrong key path, a missed status, an
# off-by-one in the polling loop) would fail here even without live
# credentials. This is not a substitute for one real smoke test against a
# live account before relying on this in production — see
# VERCEL_DEPLOYMENT.md for that recommendation.
# ---------------------------------------------------------------------------


class _FakeResponse:
    def __init__(self, status_code=200, json_data=None, content=b"", text=""):
        self.status_code = status_code
        self._json_data = json_data
        self.content = content
        self.text = text or (str(json_data) if json_data is not None else "")

    def json(self):
        return self._json_data


def test_cloudconvert_walks_the_full_job_lifecycle_correctly(monkeypatch):
    """Simulates a realistic CloudConvert job: created -> processing (one
    poll) -> finished, then verifies the actual PDF bytes returned are the
    ones from the export URL — proving the function reads the upload form,
    the job id, the per-task status, and the final download URL from the
    correct places in the response shape, not just that it doesn't crash."""
    monkeypatch.setenv("CLOUDCONVERT_API_KEY", "fake-test-key")
    monkeypatch.setattr(pdf_conversion, "_CLOUDCONVERT_POLL_INTERVAL_SECONDS", 0.001)

    calls = {"post": [], "get": []}

    job_created = {
        "data": {
            "id": "job-123",
            "tasks": [
                {
                    "name": "import-file",
                    "result": {
                        "form": {
                            "url": "https://upload.example/put",
                            "parameters": {"key": "some-upload-key"},
                        }
                    },
                },
            ],
        }
    }
    job_processing = {"data": {"id": "job-123", "status": "processing", "tasks": []}}
    job_finished = {
        "data": {
            "id": "job-123",
            "status": "finished",
            "tasks": [
                {"name": "export-file", "status": "finished", "result": {"files": [{"url": "https://download.example/out.pdf"}]}},
            ],
        }
    }

    def fake_post(url, json=None, data=None, files=None, headers=None, timeout=None):
        calls["post"].append(url)
        if url.endswith("/jobs"):
            assert headers["Authorization"] == "Bearer fake-test-key"
            return _FakeResponse(200, job_created)
        if url == "https://upload.example/put":
            assert data == {"key": "some-upload-key"}
            assert files["file"][0] == "test.docx"
            return _FakeResponse(201, {})
        raise AssertionError(f"unexpected POST to {url}")

    poll_responses = [job_processing, job_finished]

    def fake_get(url, headers=None, timeout=None):
        calls["get"].append(url)
        if url == "https://download.example/out.pdf":
            return _FakeResponse(200, content=b"%PDF-1.4 fake pdf bytes")
        assert url == "https://api.cloudconvert.com/v2/jobs/job-123"
        return _FakeResponse(200, poll_responses.pop(0))

    monkeypatch.setattr(pdf_conversion.requests, "post", fake_post)
    monkeypatch.setattr(pdf_conversion.requests, "get", fake_get)

    result = pdf_conversion.convert_via_cloudconvert(b"fake docx bytes", base_name="test")

    assert result == b"%PDF-1.4 fake pdf bytes"
    assert calls["post"] == ["https://api.cloudconvert.com/v2/jobs", "https://upload.example/put"]
    # Polled once while "processing", then again to see "finished" — proves
    # the loop actually re-polls rather than trusting the first response.
    assert calls["get"] == [
        "https://api.cloudconvert.com/v2/jobs/job-123",
        "https://api.cloudconvert.com/v2/jobs/job-123",
        "https://download.example/out.pdf",
    ]


def test_cloudconvert_job_error_status_raises_with_the_real_task_message(monkeypatch):
    """A job that reaches CloudConvert's own "error" status (e.g. a
    corrupted upload, an engine-side failure) must surface the REAL
    per-task error message, not a generic failure — project rule 9."""
    monkeypatch.setenv("CLOUDCONVERT_API_KEY", "fake-test-key")

    job_created = {
        "data": {
            "id": "job-456",
            "tasks": [
                {"name": "import-file", "result": {"form": {"url": "https://upload.example/put", "parameters": {}}}},
            ],
        }
    }
    job_error = {
        "data": {
            "id": "job-456",
            "status": "error",
            "tasks": [
                {"name": "convert-file", "status": "error", "message": "Input file is not a valid docx"},
            ],
        }
    }

    def fake_post(url, json=None, data=None, files=None, headers=None, timeout=None):
        if url.endswith("/jobs"):
            return _FakeResponse(200, job_created)
        return _FakeResponse(201, {})

    def fake_get(url, headers=None, timeout=None):
        return _FakeResponse(200, job_error)

    monkeypatch.setattr(pdf_conversion.requests, "post", fake_post)
    monkeypatch.setattr(pdf_conversion.requests, "get", fake_get)

    with pytest.raises(pdf_conversion.PdfConversionError, match="Input file is not a valid docx"):
        pdf_conversion.convert_via_cloudconvert(b"fake docx bytes", base_name="test")


def test_without_libreoffice_a_windows_pc_with_word_converts_through_word(monkeypatch):
    monkeypatch.delenv("PDF_CONVERSION_PROVIDER", raising=False)
    monkeypatch.delenv("CLOUDCONVERT_API_KEY", raising=False)
    calls = []
    monkeypatch.setattr(pdf_conversion, "_find_soffice", lambda: None)
    monkeypatch.setattr(pdf_conversion, "_word_is_installed", lambda: True)
    monkeypatch.setattr(pdf_conversion, "convert_via_local_libreoffice", lambda b, base_name: calls.append("local") or b"LOCAL")
    monkeypatch.setattr(pdf_conversion, "convert_via_word", lambda b, base_name: calls.append("word") or b"WORD")
    assert pdf_conversion.convert_docx_bytes_to_pdf(b"x") == b"WORD"
    assert calls == ["word"]


def test_libreoffice_wins_over_word_when_both_exist(monkeypatch):
    monkeypatch.delenv("PDF_CONVERSION_PROVIDER", raising=False)
    monkeypatch.delenv("CLOUDCONVERT_API_KEY", raising=False)
    calls = []
    monkeypatch.setattr(pdf_conversion, "_find_soffice", lambda: "C:/LO/soffice.exe")
    monkeypatch.setattr(pdf_conversion, "_word_is_installed", lambda: True)
    monkeypatch.setattr(pdf_conversion, "convert_via_local_libreoffice", lambda b, base_name: calls.append("local") or b"LOCAL")
    monkeypatch.setattr(pdf_conversion, "convert_via_word", lambda b, base_name: calls.append("word") or b"WORD")
    pdf_conversion.convert_docx_bytes_to_pdf(b"x")
    assert calls == ["local"]


def test_neither_libreoffice_nor_word_gives_the_actionable_error(monkeypatch):
    monkeypatch.delenv("PDF_CONVERSION_PROVIDER", raising=False)
    monkeypatch.delenv("CLOUDCONVERT_API_KEY", raising=False)
    monkeypatch.setattr(pdf_conversion, "_find_soffice", lambda: None)
    monkeypatch.setattr(pdf_conversion, "_word_is_installed", lambda: False)
    def _missing(*a, **k):
        raise FileNotFoundError("soffice")
    monkeypatch.setattr(pdf_conversion.subprocess, "Popen", _missing)
    with pytest.raises(pdf_conversion.PdfConversionError, match="LibreOffice"):
        pdf_conversion.convert_docx_bytes_to_pdf(b"x")


def test_find_soffice_checks_the_standard_windows_install_folder(monkeypatch, tmp_path):
    exe = tmp_path / "LibreOffice" / "program" / "soffice.exe"
    exe.parent.mkdir(parents=True)
    exe.write_bytes(b"")
    monkeypatch.delenv("SOFFICE_PATH", raising=False)
    monkeypatch.setattr(pdf_conversion.shutil, "which", lambda name: None)
    monkeypatch.setattr(pdf_conversion, "_soffice_candidates", lambda: [str(exe)])
    assert pdf_conversion._find_soffice() == str(exe)


def test_word_converter_refuses_cleanly_off_windows(monkeypatch):
    monkeypatch.setattr(pdf_conversion.sys, "platform", "linux")
    with pytest.raises(pdf_conversion.PdfConversionError, match="Windows"):
        pdf_conversion.convert_via_word(b"x")


# ---------------------------------------------------------------------------
# Bounded concurrency + whole-process-tree clean-up (LibreOffice runs)
# ---------------------------------------------------------------------------
import os
import sys
import threading
import time


def _fake_soffice_script(tmp_path, body):
    """A stand-in for 'soffice': a tiny python script (so no LibreOffice is needed)."""
    script = tmp_path / "fake_soffice.py"
    script.write_text(body)
    return [sys.executable, str(script)]


def test_parallel_cap_reads_the_environment_variable(monkeypatch):
    monkeypatch.setenv("KHANNA_MAX_PARALLEL_PDF", "7")
    assert pdf_conversion._max_parallel_conversions() == 7
    monkeypatch.setenv("KHANNA_MAX_PARALLEL_PDF", "0")
    assert 1 <= pdf_conversion._max_parallel_conversions() <= 4
    monkeypatch.setenv("KHANNA_MAX_PARALLEL_PDF", "abc")
    assert 1 <= pdf_conversion._max_parallel_conversions() <= 4


def test_only_the_allowed_number_of_conversions_run_at_once_and_all_finish(monkeypatch, tmp_path):
    monkeypatch.setattr(pdf_conversion, "_conversion_slots", threading.BoundedSemaphore(2))
    cmd = _fake_soffice_script(tmp_path, "import time; time.sleep(0.4)\n")

    running = {"now": 0, "peak": 0}
    lock = threading.Lock()
    real_popen = pdf_conversion.subprocess.Popen

    class _Counting(real_popen):
        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            with lock:
                running["now"] += 1
                running["peak"] = max(running["peak"], running["now"])

        def communicate(self, *a, **k):
            try:
                return super().communicate(*a, **k)
            finally:
                with lock:
                    running["now"] -= 1

    monkeypatch.setattr(pdf_conversion.subprocess, "Popen", _Counting)
    results = []
    threads = [threading.Thread(target=lambda: results.append(pdf_conversion._run_libreoffice(cmd))) for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    assert len(results) == 6  # nothing refused: the extra ones simply waited
    assert all(rc == 0 for rc, _o, _e in results)
    assert running["peak"] <= 2


def test_a_full_queue_gives_a_clear_busy_error_not_a_hang(monkeypatch, tmp_path):
    sem = threading.BoundedSemaphore(1)
    sem.acquire()  # the only slot is taken
    monkeypatch.setattr(pdf_conversion, "_conversion_slots", sem)
    monkeypatch.setattr(pdf_conversion, "_QUEUE_WAIT_SECONDS", 0.2)
    with pytest.raises(pdf_conversion.PdfConversionError, match="busy"):
        pdf_conversion._run_libreoffice([sys.executable, "-c", "pass"])


def test_the_slot_is_released_when_the_program_is_missing(monkeypatch):
    sem = threading.BoundedSemaphore(1)
    monkeypatch.setattr(pdf_conversion, "_conversion_slots", sem)
    with pytest.raises(FileNotFoundError):
        pdf_conversion._run_libreoffice(["/definitely/not/installed/soffice"])
    assert sem.acquire(timeout=1)  # would block forever if the slot had leaked
    sem.release()


@pytest.mark.skipif(os.name == "nt", reason="uses a POSIX process group; Windows uses taskkill /T")
def test_a_timeout_kills_the_launcher_and_its_child_process(monkeypatch, tmp_path):
    pid_file = tmp_path / "child.pid"
    body = (
        "import subprocess, sys, time\n"
        "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
        f"open(r'{pid_file}', 'w').write(str(child.pid))\n"
        "time.sleep(60)\n"
    )
    cmd = _fake_soffice_script(tmp_path, body)
    sem = threading.BoundedSemaphore(1)
    monkeypatch.setattr(pdf_conversion, "_conversion_slots", sem)
    with pytest.raises(pdf_conversion.PdfConversionError, match="timed out"):
        pdf_conversion._run_libreoffice(cmd, timeout=2)

    child_pid = int(pid_file.read_text())
    deadline = time.time() + 5
    alive = True
    while time.time() < deadline:
        try:
            os.kill(child_pid, 0)
            # a killed child can linger as a zombie until reaped by init; check its state
            try:
                state = open(f"/proc/{child_pid}/stat").read().split()[2]
            except OSError:
                state = "gone"
            alive = state not in ("Z", "gone")
        except ProcessLookupError:
            alive = False
        if not alive:
            break
        time.sleep(0.1)
    assert not alive, "the LibreOffice helper process was left running after the timeout"
    assert sem.acquire(timeout=1)  # slot freed after the timeout
    sem.release()


# --- convert_via_word's own body (it was once broken by an undefined name; the
# tests above replace the whole function, so none of them would have noticed) ---


class _Done:
    def __init__(self, code, out="", err=""):
        self.returncode, self.stdout, self.stderr = code, out, err


def test_convert_via_word_returns_the_pdf_word_made(monkeypatch):
    monkeypatch.setattr(pdf_conversion.sys, "platform", "win32")

    def fake_run(cmd, **kw):
        open(cmd[-1], "wb").write(b"%PDF-from-word")  # last argument is the .pdf path
        return _Done(0)

    monkeypatch.setattr(pdf_conversion.subprocess, "run", fake_run)
    assert pdf_conversion.convert_via_word(b"docx", base_name="x") == b"%PDF-from-word"


def test_convert_via_word_reports_a_word_failure_clearly(monkeypatch):
    monkeypatch.setattr(pdf_conversion.sys, "platform", "win32")
    monkeypatch.setattr(pdf_conversion.subprocess, "run", lambda cmd, **kw: _Done(1, "", "Word is busy"))
    with pytest.raises(pdf_conversion.PdfConversionError) as e:
        pdf_conversion.convert_via_word(b"docx", base_name="x")
    assert "Word is busy" in str(e.value)
