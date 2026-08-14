"""Controles del Job de cleanup para el cliente UI externo H9R."""

from __future__ import annotations

import ctypes
import subprocess
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from scripts.readiness_h9r.windows_job import (
    WindowsApi,
    WindowsExternalJob,
    WindowsJob,
    resume_suspended_process,
)


def test_close_handle_y_job_no_ocultan_fallo_de_cleanup() -> None:
    api = object.__new__(WindowsApi)
    api.kernel32 = MagicMock()
    api.kernel32.CloseHandle.return_value = False
    with (
        patch.object(ctypes, "get_last_error", return_value=5, create=True),
        pytest.raises(OSError, match="CloseHandle") as captured,
    ):
        api.close_handle(41)
    assert captured.value.errno == 5

    job = object.__new__(WindowsJob)
    job.api = MagicMock()
    job.api.close_handle.side_effect = [OSError(5, "job handle"), None]
    job.handle = 41
    job._completion_port = 42
    job._closed = False
    with pytest.raises(OSError, match="job handle"):
        job.close()
    assert job.handle == 41
    assert job._completion_port is None
    assert job._closed is False
    assert job.api.close_handle.call_count == 2

    job.api.close_handle.side_effect = None
    job.close()
    assert job.handle == 0
    assert job._closed is True


@pytest.mark.skipif(sys.platform != "win32", reason="Job Object es exclusivo de Windows")
def test_external_job_asigna_suspendido_censa_y_limpia_arbol(tmp_path: Path) -> None:
    ready = tmp_path / "cliente-listo"
    descendant = "import time;time.sleep(30)"
    root = (
        "import subprocess,sys,time;from pathlib import Path;"
        f"subprocess.Popen([sys.executable,'-c',{descendant!r}]);"
        f"Path({str(ready)!r}).write_text('listo',encoding='utf-8');"
        "time.sleep(30)"
    )
    job = WindowsExternalJob()
    process: subprocess.Popen[bytes] | None = None
    try:
        effective = job.effective_controls()
        assert effective["kill_on_job_close"] is True
        assert effective["affinity_enforced"] is False
        assert effective["job_memory_enforced"] is False
        assert effective["affinity_mask"] == 0
        assert effective["job_memory_limit_bytes"] == 0

        assert not ready.exists()
        process = job.launch_suspended([sys.executable, "-c", root])
        assert process.pid in job.process_ids()
        assert not ready.exists()
        resume_suspended_process(process.pid, job.api)
        deadline = time.monotonic() + 10
        while not ready.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert ready.exists()

        deadline = time.monotonic() + 10
        while len(job.process_ids()) < 2 and time.monotonic() < deadline:
            time.sleep(0.01)
        census = job.census()
        assert process.pid in census["tree"]["pids"]
        assert len(census["tree"]["pids"]) >= 2
        assert census["tree"]["process_query_errors"] == []
        assert census["tree"]["thread_query_errors"] == []
        assert census["accounting"]["active_processes"] >= 2

        job.terminate(0xE0000001)
        process.wait(timeout=10)
        assert job.wait_empty(5)
    finally:
        if process is not None and process.poll() is None:
            try:
                job.terminate(0xE0000002)
            except OSError:
                process.kill()
            process.wait(timeout=10)
        job.close()
