"""Tests focales del arnés clean-room W1, sin ejecutar los perfiles de escala."""

from __future__ import annotations

import contextlib
import copy
import importlib.util
import subprocess
import sys
import time
import zipfile
from pathlib import Path, PurePosixPath
from types import ModuleType

import pytest

_DARWIN_RESOURCE_PROBE_UNSUPPORTED = pytest.mark.skipif(
    sys.platform == "darwin",
    reason="S3 es fail-closed en Darwin: RLIMIT_AS no demuestra un límite duro",
)


def _driver() -> ModuleType:
    path = Path(__file__).resolve().parents[2] / "scripts" / "measure_readiness_w1.py"
    spec = importlib.util.spec_from_file_location("nikodym_readiness_w1_driver", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _FakeDistribution:
    def __init__(self, root: Path, files: tuple[PurePosixPath, ...]) -> None:
        self._root = root
        self.files = files

    def locate_file(self, relative: PurePosixPath) -> Path:
        return self._root / relative


def test_hash_metadata_compara_wheel_e_instalacion_y_detecta_drift(tmp_path: Path) -> None:
    driver = _driver()
    members = {
        "nikodym/__init__.py": b"__version__ = '1.0'\n",
        "nikodym-1.0.dist-info/METADATA": b"Name: nikodym\nVersion: 1.0\n",
        "nikodym-1.0.dist-info/WHEEL": b"Wheel-Version: 1.0\n",
        "nikodym-1.0.dist-info/licenses/LICENSE": b"Apache-2.0\n",
    }
    wheel = tmp_path / "nikodym-1.0-py3-none-any.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        for name, content in members.items():
            archive.writestr(name, content)
    install = tmp_path / "site-packages"
    for name, content in members.items():
        path = install / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    distribution = _FakeDistribution(
        install,
        tuple(PurePosixPath(name) for name in members),
    )

    expected = driver._wheel_metadata_hash(wheel)
    assert driver._installed_metadata_hash(distribution) == expected

    (install / "nikodym-1.0.dist-info" / "METADATA").write_text(
        "Name: nikodym\nVersion: 9.9\n", encoding="utf-8"
    )
    assert driver._installed_metadata_hash(distribution) != expected


def test_driver_no_importa_nikodym_al_cargar() -> None:
    module = _driver()
    assert "nikodym" not in module.__dict__


@pytest.mark.skipif(sys.platform != "win32", reason="API nativa específica de Windows")
def test_peak_rss_windows_usa_handle_sin_truncar() -> None:
    driver = _driver()
    assert driver._peak_rss_bytes() > 0


def test_evidencia_de_informe_exige_html_y_qmd_reales(tmp_path: Path) -> None:
    driver = _driver()
    (tmp_path / "scorecard_report.html").write_text("<html></html>", encoding="utf-8")
    (tmp_path / "scorecard_report.qmd").write_text("---\ntitle: prueba\n---\n", encoding="utf-8")

    evidence = driver._report_evidence(tmp_path)
    assert evidence["html_verified"] is True
    assert evidence["markdown_verified"] is True
    assert {item["path"] for item in evidence["files"]} == {
        "scorecard_report.html",
        "scorecard_report.qmd",
    }

    (tmp_path / "scorecard_report.qmd").unlink()
    (tmp_path / "scorecard_report.md").write_text("# salida equivocada\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match=r"HTML\+QMD"):
        driver._report_evidence(tmp_path)


def test_workdir_cleanroom_debe_quedar_fuera_del_checkout(tmp_path: Path) -> None:
    driver = _driver()
    external = tmp_path / "evidence"
    assert driver._validate_external_workdir(external) == external.resolve()

    inside = driver.ROOT / ".evidence-w1-prohibida"
    with pytest.raises(RuntimeError, match="workdir clean-room quedó dentro del checkout"):
        driver._validate_external_workdir(inside)


def test_generador_materializa_cardinalidad_exacta_con_special_soportado() -> None:
    driver = _driver()
    frame = driver._training_frame({"train_rows": 12, "variables": 2, "cardinality": 4})

    assert frame["x_000"].nunique() == 4
    assert set(frame["x_000"]) == {-88888, 0, 1, 2}
    assert int(frame["x_000"].eq(-88888).sum()) == 9
    assert set(frame.loc[frame["x_000"].eq(-88888), "bad_flag"]) == {0, 1}


def test_generador_garantiza_soporte_dev_para_cada_categoria_ordinaria() -> None:
    driver = _driver()
    frame = driver._training_frame({"train_rows": 1_000, "variables": 2, "cardinality": 100})

    desarrollo = frame.loc[frame["sample_split"].eq("DEV")]
    assert set(range(99)).issubset(set(desarrollo["x_000"]))
    assert set(desarrollo.loc[desarrollo["x_000"].eq(-88888), "bad_flag"]) == {0, 1}
    assert set(frame["sample_split"]) == {"DEV", "HOLDOUT", "OOT"}


def _supervisor_limits(driver: ModuleType, **overrides: int | float) -> dict[str, int | float]:
    limits: dict[str, int | float] = {
        "memory_bytes": 256 * driver.MIB,
        "cpu_seconds": 5,
        "wall_seconds": 5.0,
        "handshake_seconds": 5.0,
    }
    limits.update(overrides)
    return limits


def _run_probe(
    driver: ModuleType,
    tmp_path: Path,
    mode: str,
    *,
    limits: dict[str, int | float] | None = None,
    probe_delay_seconds: float = 1.0,
) -> dict[str, object]:
    workdir = tmp_path / mode
    workdir.mkdir()
    return driver._supervise_child(
        mode=mode,
        workdir=workdir,
        limits=limits or _supervisor_limits(driver),
        probe_delay_seconds=probe_delay_seconds,
    )


@_DARWIN_RESOURCE_PROBE_UNSUPPORTED
def test_supervisor_s3_ejecucion_normal_atestigua_limites_y_capturas(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    driver = _driver()
    monkeypatch.setenv("COV_CORE_SOURCE", "nikodym")
    monkeypatch.setenv("COVERAGE_PROCESS_START", "configurada-por-el-runner")
    evidence = _run_probe(driver, tmp_path, "probe-normal")

    assert evidence["outcome"] == "normal"
    assert evidence["returncode"]["signed"] == 0
    assert evidence["worker_returncode"]["signed"] == 0
    assert evidence["launcher_returncode"]["signed"] == 0
    assert evidence["handshake"]["boot"]["coverage_autostart_environment_keys"] == []
    assert evidence["handshake"]["limits_verified_before_start"] is True
    assert evidence["effective_limits"] == driver._expected_effective_limits(
        evidence["backend"], evidence["requested_limits"]
    )
    assert evidence["driver_sha256"]["all_equal"] is True
    assert evidence["child_result"]["reconciled"] is True
    assert evidence["tree_cleanup"]["descendants_detected_before_cleanup"] is False
    assert evidence["tree_cleanup"]["action"] == "none"
    assert evidence["tree_cleanup"]["complete"] is True
    assert evidence["peak_rss_bytes"] > 0
    assert len(evidence["stdout"]["sha256"]) == 64
    assert len(evidence["stderr"]["sha256"]) == 64


@_DARWIN_RESOURCE_PROBE_UNSUPPORTED
def test_supervisor_s3_wall_timeout_mata_antes_del_sentinel(tmp_path: Path) -> None:
    driver = _driver()
    evidence = _run_probe(
        driver,
        tmp_path,
        "probe-wall",
        limits=_supervisor_limits(driver, wall_seconds=0.2),
        probe_delay_seconds=1.0,
    )

    assert evidence["outcome"] == "wall_timeout"
    assert evidence["workload_wall_seconds"] <= 0.5
    assert evidence["returncode"]["signed"] != 0
    assert evidence["tree_cleanup"]["descendants_detected_before_cleanup"] is False
    assert evidence["tree_cleanup"]["untracked_processes_before_cleanup"] == 0
    assert evidence["tree_cleanup"]["late_sentinel_absent"] is True
    assert evidence["tree_cleanup"]["complete"] is True


@pytest.mark.skipif(sys.platform == "darwin", reason="RLIMIT_AS no es un gate fiable en macOS")
def test_supervisor_s3_limite_memoria_es_duro_y_clasificado(tmp_path: Path) -> None:
    driver = _driver()
    memory_bytes = 192 * driver.MIB if sys.platform == "win32" else 96 * driver.MIB
    evidence = _run_probe(
        driver,
        tmp_path,
        "probe-memory",
        limits=_supervisor_limits(driver, memory_bytes=memory_bytes, wall_seconds=10.0),
    )

    assert evidence["outcome"] == "memory_limit"
    assert evidence["returncode"]["signed"] == driver._S3_MEMORY_EXIT_CODE
    assert driver._S3_MEMORY_MARKER in evidence["stderr"]["tail_utf8"]
    assert evidence["tree_cleanup"]["complete"] is True
    if sys.platform == "win32":
        flags = evidence["effective_limits"]["limit_flags"]
        assert flags & 0x00000200
        assert not flags & 0x00000100
        accounting = evidence["accounting_before_cleanup"]
        assert accounting["total_processes"] >= 3
        assert accounting["peak_job_memory_commit_bytes"] >= int(memory_bytes * 0.70)


@_DARWIN_RESOURCE_PROBE_UNSUPPORTED
def test_supervisor_s3_limite_cpu_es_duro_y_clasificado(tmp_path: Path) -> None:
    driver = _driver()
    evidence = _run_probe(
        driver,
        tmp_path,
        "probe-cpu",
        limits=_supervisor_limits(driver, cpu_seconds=1, wall_seconds=8.0),
    )

    assert evidence["outcome"] == "cpu_limit"
    assert evidence["returncode"]["signed"] != 0
    assert evidence["tree_cleanup"]["complete"] is True
    if sys.platform == "win32":
        flags = evidence["effective_limits"]["limit_flags"]
        assert flags & 0x00000004
        assert not flags & 0x00000002
        assert evidence["accounting_before_cleanup"]["total_user_time_100ns"] >= 8_000_000


@_DARWIN_RESOURCE_PROBE_UNSUPPORTED
def test_supervisor_s3_cierra_descendiente_antes_del_sentinel_tardio(tmp_path: Path) -> None:
    driver = _driver()
    evidence = _run_probe(
        driver,
        tmp_path,
        "probe-descendant",
        probe_delay_seconds=0.5,
    )

    assert evidence["outcome"] == "normal"
    assert evidence["tree_cleanup"]["descendants_detected_before_cleanup"] is True
    assert evidence["tree_cleanup"]["untracked_processes_before_cleanup"] > 0
    assert evidence["tree_cleanup"]["action"] in {"terminate_job_object", "killpg_sigkill"}
    assert evidence["tree_cleanup"]["descendant_alive_after_cleanup"] is False
    assert evidence["tree_cleanup"]["late_sentinel_absent"] is True
    assert evidence["tree_cleanup"]["complete"] is True


@pytest.mark.skipif(sys.platform != "win32", reason="Job Object es exclusivo de Windows")
def test_job_object_kill_on_close_mata_arbol_antes_del_sentinel(tmp_path: Path) -> None:
    driver = _driver()
    start = tmp_path / "start.txt"
    ready = tmp_path / "ready.txt"
    sentinel = tmp_path / "late-sentinel.txt"
    descendant_code = (
        "import pathlib,time;"
        "time.sleep(0.5);"
        f"pathlib.Path({str(sentinel)!r}).write_text('orphan\\n',encoding='utf-8')"
    )
    parent_code = "\n".join(
        [
            "import pathlib, subprocess, sys, time",
            f"start = pathlib.Path({str(start)!r})",
            "while not start.exists():",
            "    time.sleep(0.01)",
            f"descendant = subprocess.Popen([sys.executable, '-c', {descendant_code!r}])",
            f"pathlib.Path({str(ready)!r}).write_text(str(descendant.pid), encoding='utf-8')",
            "time.sleep(30.0)",
        ]
    )
    parent: subprocess.Popen[bytes] | None = None
    job = driver._WindowsJob(memory_bytes=512 * driver.MIB, cpu_seconds=30)
    try:
        assert job.effective_limits()["limit_flags"] & 0x00002000
        parent = subprocess.Popen(
            [sys._base_executable, "-c", parent_code],
            env=driver._isolated_supervisor_environment(),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
        )
        job.assign(parent.pid)
        start.write_text("start\n", encoding="utf-8")
        deadline = time.monotonic() + 5.0
        descendant_pid: int | None = None
        while time.monotonic() < deadline and descendant_pid is None:
            assert parent.poll() is None
            if ready.is_file():
                with contextlib.suppress(OSError, ValueError):
                    descendant_pid = int(ready.read_text(encoding="utf-8"))
            time.sleep(0.01)
        assert descendant_pid is not None

        close_started = time.monotonic()
        job.close()
        parent.wait(timeout=5.0)
        assert time.monotonic() - close_started < 1.0
        time.sleep(0.75)
        assert not driver._pid_alive(descendant_pid)
        assert not sentinel.exists()
    finally:
        job.close()
        if parent is not None and parent.poll() is None:
            parent.kill()
            parent.wait(timeout=5.0)


@_DARWIN_RESOURCE_PROBE_UNSUPPORTED
def test_supervisor_s3_no_entrega_start_sin_limites_exactos(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    driver = _driver()
    original = driver._expected_effective_limits

    def mismatched(backend: str, requested: dict[str, int | float]) -> dict[str, object]:
        effective = dict(original(backend, requested))
        if backend == "windows_job_object":
            effective["job_memory_commit_limit_bytes"] += 1
        else:
            effective["rlimit_as_soft_bytes"] += 1
        return effective

    monkeypatch.setattr(driver, "_expected_effective_limits", mismatched)
    evidence = _run_probe(driver, tmp_path, "probe-normal")

    assert evidence["outcome"] == "limits_not_applied"
    assert evidence["handshake"]["started"] is None
    assert evidence["handshake"]["limits_verified_before_start"] is False
    assert evidence["tree_cleanup"]["late_sentinel_absent"] is True


def test_clasificacion_s3_exige_n_menos_1_n_y_n_mas_1_exactos() -> None:
    driver = _driver()
    expected = copy.deepcopy(driver.S3_EXPECTED_CLASSIFICATION)
    assert driver._classification_is_exact(expected)

    missing = copy.deepcopy(expected)
    del missing["train_rows"]["999999"]
    assert not driver._classification_is_exact(missing)

    mutated = copy.deepcopy(expected)
    mutated["batch_rows"]["5000001"] = "accepted"
    assert not driver._classification_is_exact(mutated)

    extra = copy.deepcopy(expected)
    extra["train_variables"]["102"] = "rejected"
    assert not driver._classification_is_exact(extra)


def test_pass_s3_exige_terminacion_normal_y_clasificacion_exacta() -> None:
    driver = _driver()
    limits = _supervisor_limits(driver)
    backend = "windows_job_object" if sys.platform == "win32" else "posix_rlimit_process_group"
    supervision = {
        "backend": backend,
        "qualification_supported": True,
        "requested_limits": limits,
        "effective_limits": driver._expected_effective_limits(backend, limits),
        "outcome": "normal",
        "returncode": {"signed": 0},
        "launcher_returncode": {"signed": 0},
        "handshake": {"limits_verified_before_start": True},
        "driver_sha256": {"all_equal": True},
        "child_result": {"reconciled": True},
        "accounting_before_cleanup": {"source": "test"},
        "accounting_after_cleanup": {"source": "test"},
        "peak_rss_bytes": 1,
        "tree_cleanup": {"complete": True},
    }
    workload = {"limits": copy.deepcopy(driver.S3_EXPECTED_CLASSIFICATION)}
    assert all(driver._s3_pass_conditions(supervision, workload).values())

    abnormal = copy.deepcopy(supervision)
    abnormal["outcome"] = "wall_timeout"
    assert driver._s3_pass_conditions(abnormal, workload)["normal_termination"] is False

    inexact = copy.deepcopy(workload)
    inexact["limits"]["train_rows"]["1000001"] = "accepted"
    assert driver._s3_pass_conditions(supervision, inexact)["classification_exact"] is False

    unsupported = copy.deepcopy(supervision)
    unsupported["qualification_supported"] = False
    assert driver._s3_pass_conditions(unsupported, workload)["backend_eligible"] is False

    missing_accounting = copy.deepcopy(supervision)
    missing_accounting["accounting_before_cleanup"] = None
    assert driver._s3_pass_conditions(missing_accounting, workload)["accounting_present"] is False

    mismatched_result = copy.deepcopy(supervision)
    mismatched_result["child_result"]["reconciled"] = False
    assert (
        driver._s3_pass_conditions(mismatched_result, workload)["child_result_reconciled"] is False
    )

    missing_peak_rss = copy.deepcopy(supervision)
    missing_peak_rss["peak_rss_bytes"] = None
    assert driver._s3_pass_conditions(missing_peak_rss, workload)["peak_rss_present"] is False


def test_schema_v2_es_exclusivo_de_s3() -> None:
    driver = _driver()
    assert driver.SCHEMA_VERSION_V1 == "nikodym.readiness.w1.v1"
    assert driver.S3_SCHEMA_VERSION == "nikodym.readiness.w1.v2"


def test_s3_aborta_en_darwin_antes_del_hijo_pesado(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    driver = _driver()
    monkeypatch.setattr(driver.sys, "platform", "darwin")

    with pytest.raises(RuntimeError, match="S3 no inicia en Darwin"):
        driver._supervise_s3(
            tmp_path / "candidate.whl",
            tmp_path / "candidate.tar.gz",
            tmp_path / "workdir",
            "0" * 40,
            tmp_path / "bundle",
        )

    assert not (tmp_path / "workdir").exists()
