"""Mide el fundamento productivo W1 desde un wheel instalado fuera del checkout.

El driver no importa Nikodym al cargar. Debe ejecutarse desde un venv clean-room, con cwd y
``nikodym.__file__`` fuera del repositorio, y recibe los bytes exactos del wheel que se instalaron.
S0 es ejecutable en CI/local; S1/S2 sólo cuentan como PASS si el hardware satisface H9.
"""

from __future__ import annotations

import argparse
import asyncio
import ctypes
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import time
import traceback
import zipfile
from pathlib import Path
from typing import Any, Final

SCHEMA_VERSION: Final = "nikodym.readiness.w1.v1"
ROOT: Final = Path(__file__).resolve().parents[1]
MIB: Final = 1024**2
GIB: Final = 1024**3
PROFILES: Final[dict[str, dict[str, int]]] = {
    "S0-smoke": {
        "train_rows": 10_000,
        "batch_rows": 10_000,
        "variables": 25,
        "cardinality": 100,
        "logical_cpus": 1,
        "ram_gib": 4,
        "peak_gib": 4,
        "train_seconds": 300,
        "batch_seconds": 300,
        "batch_chunk_size": 257,
        "disk_free_gib": 2,
    },
    "S1-local": {
        "train_rows": 100_000,
        "batch_rows": 100_000,
        "variables": 50,
        "cardinality": 10_000,
        "logical_cpus": 8,
        "ram_gib": 16,
        "peak_gib": 12,
        "train_seconds": 900,
        "batch_seconds": 1_200,
        "batch_chunk_size": 4_096,
        "disk_free_gib": 8,
    },
    "S2-equipo": {
        "train_rows": 1_000_000,
        "batch_rows": 5_000_000,
        "variables": 100,
        "cardinality": 100_000,
        "logical_cpus": 16,
        "ram_gib": 32,
        "peak_gib": 24,
        "train_seconds": 2_700,
        "batch_seconds": 1_200,
        "batch_chunk_size": 10_000,
        "disk_free_gib": 60,
    },
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(MIB), b""):
            digest.update(block)
    return digest.hexdigest()


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _total_memory_bytes() -> int | None:
    if sys.platform == "win32":

        class MemoryStatus(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]

        status = MemoryStatus()
        status.dwLength = ctypes.sizeof(status)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            return int(status.ullTotalPhys)
        return None
    try:
        return int(os.sysconf("SC_PHYS_PAGES")) * int(os.sysconf("SC_PAGE_SIZE"))
    except (AttributeError, OSError, ValueError):
        return None


def _peak_rss_bytes() -> int:
    if sys.platform == "win32":

        class ProcessMemoryCounters(ctypes.Structure):
            _fields_ = [
                ("cb", ctypes.c_ulong),
                ("PageFaultCount", ctypes.c_ulong),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
            ]

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        psapi = ctypes.WinDLL("psapi", use_last_error=True)
        kernel32.GetCurrentProcess.argtypes = []
        kernel32.GetCurrentProcess.restype = ctypes.c_void_p
        psapi.GetProcessMemoryInfo.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(ProcessMemoryCounters),
            ctypes.c_ulong,
        ]
        psapi.GetProcessMemoryInfo.restype = ctypes.c_bool

        counters = ProcessMemoryCounters()
        counters.cb = ctypes.sizeof(counters)
        process = kernel32.GetCurrentProcess()
        if not psapi.GetProcessMemoryInfo(process, ctypes.byref(counters), counters.cb):
            error_code = ctypes.get_last_error()
            raise OSError(error_code, "GetProcessMemoryInfo falló")
        return int(counters.PeakWorkingSetSize)
    import resource

    raw = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    return raw if sys.platform == "darwin" else raw * 1024


def _command_text(command: list[str]) -> str | None:
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    value = completed.stdout.strip()
    return value or None


def _hardware(workdir: Path) -> dict[str, Any]:
    logical = os.cpu_count() or 0
    physical: int | None = None
    cpu_model: str | None = None
    power_scheme: str | None = None
    if sys.platform == "win32":
        raw = _command_text(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                (
                    "$c=Get-CimInstance Win32_Processor | Select-Object -First 1 "
                    "Name,NumberOfCores,NumberOfLogicalProcessors; $c|ConvertTo-Json -Compress"
                ),
            ]
        )
        if raw:
            try:
                cpu = json.loads(raw)
                cpu_model = str(cpu["Name"]).strip()
                physical = int(cpu["NumberOfCores"])
                logical = int(cpu["NumberOfLogicalProcessors"])
            except (KeyError, TypeError, ValueError, json.JSONDecodeError):
                pass
        power_scheme = _command_text(["powercfg", "/getactivescheme"])
    elif sys.platform == "darwin":
        cpu_model = _command_text(["sysctl", "-n", "machdep.cpu.brand_string"])
        raw_physical = _command_text(["sysctl", "-n", "hw.physicalcpu"])
        if raw_physical and raw_physical.isdigit():
            physical = int(raw_physical)
    elif Path("/proc/cpuinfo").is_file():
        for line in Path("/proc/cpuinfo").read_text(encoding="utf-8").splitlines():
            if line.lower().startswith("model name"):
                cpu_model = line.split(":", 1)[1].strip()
                break
    memory = _total_memory_bytes()
    disk = shutil.disk_usage(workdir)
    return {
        "cpu_model": cpu_model or platform.processor() or "desconocido",
        "physical_cores": physical,
        "logical_cpus": logical,
        "memory_bytes": memory,
        "platform": platform.platform(),
        "system": platform.system(),
        "release": platform.release(),
        "machine": platform.machine(),
        "python": platform.python_version(),
        "power_scheme": power_scheme,
        "disk_total_bytes": disk.total,
        "disk_free_bytes_before": disk.free,
    }


def _installed_tree_hash(distribution: Any) -> str:
    digest = hashlib.sha256(b"nikodym.wheel-tree.v1\0")
    selected = sorted(
        file for file in (distribution.files or ()) if file.parts and file.parts[0] == "nikodym"
    )
    if not selected:
        raise RuntimeError("la distribución instalada no enumera archivos nikodym")
    for relative in selected:
        path = Path(distribution.locate_file(relative))
        if not path.is_file():
            raise RuntimeError(f"archivo instalado ausente: {relative}")
        digest.update(str(relative).replace("\\", "/").encode() + b"\0")
        digest.update(bytes.fromhex(_sha256(path)))
    return digest.hexdigest()


def _wheel_tree_hash(wheel: Path) -> str:
    digest = hashlib.sha256(b"nikodym.wheel-tree.v1\0")
    with zipfile.ZipFile(wheel) as archive:
        selected = sorted(
            name
            for name in archive.namelist()
            if name.startswith("nikodym/") and not name.endswith("/")
        )
        if not selected:
            raise RuntimeError("el wheel no contiene el paquete nikodym")
        for relative in selected:
            digest.update(relative.encode() + b"\0")
            digest.update(hashlib.sha256(archive.read(relative)).digest())
    return digest.hexdigest()


def _wheel_metadata_hash(wheel: Path) -> str:
    digest = hashlib.sha256(b"nikodym.wheel-metadata.v1\0")
    with zipfile.ZipFile(wheel) as archive:
        selected: list[tuple[str, str]] = []
        for name in archive.namelist():
            if ".dist-info/" not in name or name.endswith("/"):
                continue
            tail = name.split(".dist-info/", 1)[1]
            if tail in {"METADATA", "WHEEL", "entry_points.txt"} or tail.startswith("licenses/"):
                selected.append((tail, name))
        if not any(tail == "METADATA" for tail, _ in selected):
            raise RuntimeError("el wheel no contiene METADATA verificable")
        for tail, name in sorted(selected):
            digest.update(f"dist-info/{tail}".encode() + b"\0")
            digest.update(hashlib.sha256(archive.read(name)).digest())
    return digest.hexdigest()


def _installed_metadata_hash(distribution: Any) -> str:
    digest = hashlib.sha256(b"nikodym.wheel-metadata.v1\0")
    selected: list[tuple[str, Path]] = []
    for relative in distribution.files or ():
        normalized = str(relative).replace("\\", "/")
        if ".dist-info/" not in normalized:
            continue
        tail = normalized.split(".dist-info/", 1)[1]
        if tail in {"METADATA", "WHEEL", "entry_points.txt"} or tail.startswith("licenses/"):
            path = Path(distribution.locate_file(relative))
            if path.is_file():
                selected.append((tail, path))
    if not any(tail == "METADATA" for tail, _ in selected):
        raise RuntimeError("la instalación no expone METADATA verificable")
    for tail, path in sorted(selected):
        digest.update(f"dist-info/{tail}".encode() + b"\0")
        digest.update(bytes.fromhex(_sha256(path)))
    return digest.hexdigest()


def _cleanroom_identity(wheel: Path, *, source_sha: str) -> dict[str, Any]:
    from importlib import metadata

    import nikodym
    from nikodym.core.build import (
        build_uv_lock_hash,
        installed_distribution_hash,
        runtime_environment_hash,
    )

    module = Path(nikodym.__file__).resolve()
    checkout_sha = _command_text(["git", "-C", str(ROOT), "rev-parse", "HEAD"])
    checkout_status = _command_text(["git", "-C", str(ROOT), "status", "--porcelain"])
    if checkout_sha != source_sha:
        raise RuntimeError(
            f"driver no proviene del SHA declarado: checkout={checkout_sha}, source={source_sha}"
        )
    if checkout_status:
        raise RuntimeError("el checkout del driver no está limpio")
    cwd = Path.cwd().resolve()
    if cwd.is_relative_to(ROOT):
        raise RuntimeError(f"el cwd clean-room quedó dentro del checkout: {cwd}")
    raw_pythonpath = os.environ.get("PYTHONPATH", "")
    if raw_pythonpath:
        raise RuntimeError("clean-room requiere PYTHONPATH vacío")
    if module.is_relative_to(ROOT):
        raise RuntimeError(f"clean-room importó Nikodym desde el checkout: {module}")
    if "site-packages" not in module.parts:
        raise RuntimeError(f"Nikodym no se resolvió desde site-packages: {module}")
    distribution = metadata.distribution("nikodym")
    wheel_tree_hash = _wheel_tree_hash(wheel)
    installed_tree_hash = _installed_tree_hash(distribution)
    if wheel_tree_hash != installed_tree_hash:
        raise RuntimeError("el árbol instalado no coincide byte a byte con el wheel declarado")
    wheel_metadata_hash = _wheel_metadata_hash(wheel)
    installed_metadata_hash = _installed_metadata_hash(distribution)
    if wheel_metadata_hash != installed_metadata_hash:
        raise RuntimeError("la metadata instalada no coincide byte a byte con el wheel declarado")
    return {
        "wheel_name": wheel.name,
        "wheel_bytes": wheel.stat().st_size,
        "wheel_sha256": _sha256(wheel),
        "nikodym_version": distribution.version,
        "nikodym_file": str(module),
        "wheel_tree_hash": wheel_tree_hash,
        "installed_tree_hash": installed_tree_hash,
        "installed_matches_wheel": True,
        "wheel_metadata_hash": wheel_metadata_hash,
        "installed_metadata_hash": installed_metadata_hash,
        "metadata_matches_wheel": True,
        "installed_distribution_hash": installed_distribution_hash(),
        "checkout_sha": checkout_sha,
        "checkout_clean": True,
        "cwd": str(cwd),
        "pythonpath_empty": True,
        "uv_lock_hash": build_uv_lock_hash(),
        "runtime_environment_hash": runtime_environment_hash(),
    }


def _validate_external_workdir(workdir: Path) -> Path:
    """Impide que el driver o el consumidor usen el checkout como área de trabajo."""
    resolved = workdir.resolve()
    if resolved.is_relative_to(ROOT):
        raise RuntimeError(f"el workdir clean-room quedó dentro del checkout: {resolved}")
    return resolved


def _schema_column(name: str, *, dtype: str = "int") -> dict[str, Any]:
    return {
        "name": name,
        "dtype": dtype,
        "nullable": False,
        "required": True,
        "coerce": True,
        "ge": None,
        "le": None,
        "isin": None,
        "unique": False,
    }


def _training_frame(profile: dict[str, int]) -> Any:
    import numpy as np
    import pandas as pd

    rows = profile["train_rows"]
    cardinality = profile["cardinality"]
    rng = np.random.default_rng(30_001)
    columns: dict[str, Any] = {}
    for position in range(profile["variables"]):
        if position == 0:
            ordinary = max(cardinality - 1, 1)
            values = (np.arange(rows, dtype="int64") % ordinary).astype("int32")
            special_support = min(100, rows - ordinary)
            if special_support < 2:
                raise RuntimeError("el perfil no permite soporte special con ambas clases")
            values[:special_support] = -88888
        else:
            values = rng.integers(0, cardinality, size=rows, dtype="int32")
        columns[f"x_{position:03d}"] = values
    bad_noise = rng.random(rows)
    bad_probability = np.where((columns["x_000"] % 100) < 12, 0.20, 0.04)
    bad_flag = (bad_noise < bad_probability).astype("int8")
    bad_flag[:special_support] = np.arange(special_support, dtype="int8") % 2
    columns["bad_flag"] = bad_flag
    occurrence_cycle = (np.arange(rows, dtype="int64") // ordinary) % 10
    columns["sample_split"] = np.where(
        occurrence_cycle < 7,
        "DEV",
        np.where(occurrence_cycle < 9, "HOLDOUT", "OOT"),
    )
    return pd.DataFrame(columns, index=pd.RangeIndex(rows, name="row_id"), copy=False)


def _config(profile: dict[str, int], *, report_dir: Path) -> Any:
    from nikodym.core.config import NikodymConfig
    from nikodym.core.config.schema import cargar_configs_de_dominio
    from nikodym.ui.presets import standard_preset

    cargar_configs_de_dominio()
    raw = standard_preset()["config"]
    features = [f"x_{position:03d}" for position in range(profile["variables"])]
    raw["run"]["steps"] = [
        "data",
        "binning",
        "selection",
        "model",
        "scorecard",
        "calibration",
        "performance",
        "report",
    ]
    raw["data"]["schema"]["columns"] = [
        *[_schema_column(feature) for feature in features],
        _schema_column("bad_flag"),
        _schema_column("sample_split", dtype="str"),
    ]
    raw["data"]["schema"]["index_col"] = "row_id"
    raw["data"]["missing"]["special_values"] = [
        {
            "columns": ["x_000"],
            "sentinels": [-88888],
            "label": "special_supported",
        },
        {"columns": ["x_001"], "sentinels": [-99999], "label": "special_apply_only"},
    ]
    raw["data"]["partition"] = {
        "strategy": {
            "type": "columna",
            "partition_col": "sample_split",
            "desarrollo": ["DEV"],
            "holdout": ["HOLDOUT"],
            "oot": ["OOT"],
        },
        "ttd_includes_excluded": True,
        "min_bads_per_partition": 30,
    }
    raw["binning"]["feature_columns"] = features
    raw["binning"]["categorical_columns"] = ["x_000"]
    raw["binning"]["max_n_prebins"] = 20
    raw["binning"]["max_n_bins"] = 6
    raw["binning"]["n_jobs"] = min(os.cpu_count() or 1, profile["variables"])
    raw["selection"]["min_iv"] = 0.0
    raw["selection"]["correlation"]["enabled"] = False
    raw["selection"]["vif"]["enabled"] = False
    raw["model"]["optimizer"] = "lbfgs"
    raw["model"]["stepwise"]["enabled"] = False
    raw["report"]["output_dir"] = str(report_dir)
    raw["report"]["formats"] = ["md"]
    raw["report"]["sections"]["required_sections"] = [
        "binning",
        "selection",
        "model",
        "scorecard",
        "calibration",
        "performance",
    ]
    return NikodymConfig.model_validate(raw)


def _write_batch(path: Path, profile: dict[str, int]) -> dict[str, Any]:
    import numpy as np
    import pyarrow as pa
    import pyarrow.parquet as pq

    rows = profile["batch_rows"]
    variables = profile["variables"]
    cardinality = profile["cardinality"]
    batch_rows = min(50_000, rows)
    rng = np.random.default_rng(30_002)
    writer: Any = None
    started = time.perf_counter()
    try:
        for start in range(0, rows, batch_rows):
            size = min(batch_rows, rows - start)
            columns: dict[str, Any] = {"row_id": np.arange(start, start + size, dtype="int64")}
            for position in range(variables):
                upper = max(cardinality - 1, 1) if position == 0 else cardinality
                values = rng.integers(0, upper, size=size, dtype="int32")
                if position == 0 and start <= rows // 2 - 1 < start + size:
                    values[rows // 2 - 1 - start] = -88888
                if position == 1 and start <= rows // 2 < start + size:
                    values[rows // 2 - start] = -99999
                columns[f"x_{position:03d}"] = values
            table = pa.table(columns)
            if writer is None:
                writer = pq.ParquetWriter(  # type: ignore[no-untyped-call]
                    path, table.schema, compression="zstd"
                )
            writer.write_table(table, row_group_size=batch_rows)
    finally:
        if writer is not None:
            writer.close()
    return {
        "rows": rows,
        "variables": variables,
        "bytes": path.stat().st_size,
        "sha256": _sha256(path),
        "write_seconds": round(time.perf_counter() - started, 6),
    }


def _verify_batch(result: Any, *, expected_rows: int, expected_features: int) -> dict[str, Any]:
    import pandas as pd
    import pyarrow.parquet as pq

    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    if manifest["rows"] != expected_rows or manifest["output_hash"] != result.output_hash:
        raise RuntimeError("el manifest batch no reconcilia con el resultado")
    expected_start = 0
    output_bytes = result.manifest_path.stat().st_size
    scored = 0
    not_scorable = 0
    null_failed = 0
    supported_special_scored = 0
    for number, chunk in enumerate(manifest["chunks"]):
        if chunk["chunk"] != number or chunk["start"] != expected_start:
            raise RuntimeError(f"gap/reorden en chunk {number}")
        expected_start = int(chunk["end"])
        if chunk["input_rows"] != chunk["end"] - chunk["start"]:
            raise RuntimeError(f"rango incoherente en chunk {number}")
        for view, expected_multiplier in (
            ("application", 1),
            ("woe", 1),
            ("trace", expected_features),
        ):
            descriptor = chunk["files"][view]
            path = result.output_dir / descriptor["path"]
            metadata = pq.ParquetFile(path).metadata  # type: ignore[no-untyped-call]
            expected_view_rows = int(chunk["input_rows"]) * expected_multiplier
            if (
                descriptor["sha256"] != _sha256(path)
                or descriptor["bytes"] != path.stat().st_size
                or descriptor["rows"] != expected_view_rows
                or metadata.num_rows != expected_view_rows
            ):
                raise RuntimeError(f"artefacto {view}/{number} no reconcilia")
            output_bytes += path.stat().st_size
        application_path = result.output_dir / chunk["files"]["application"]["path"]
        application = pd.read_parquet(
            application_path,
            columns=[
                "input_position",
                "scoring_status",
                "not_scorable_reason",
                "linear_predictor",
                "eta",
                "pd_raw",
                "score_unrounded",
                "score",
                "pd_calibrated",
            ],
        )
        positions = application["input_position"].to_numpy()
        if positions[0] != chunk["start"] or positions[-1] != chunk["end"] - 1:
            raise RuntimeError(f"posición física incoherente en chunk {number}")
        failures = application["scoring_status"].eq("not_scorable")
        scored += int((~failures).sum())
        not_scorable += int(failures.sum())
        if failures.any():
            null_failed += int(
                application.loc[
                    failures,
                    [
                        "linear_predictor",
                        "eta",
                        "pd_raw",
                        "score_unrounded",
                        "score",
                        "pd_calibrated",
                    ],
                ]
                .isna()
                .all(axis=1)
                .sum()
            )
            if (
                not application.loc[failures, "not_scorable_reason"]
                .str.contains("special_sin_soporte_en_fit")
                .all()
            ):
                raise RuntimeError("el special no soportado perdió su motivo estructurado")
        supported_position = expected_rows // 2 - 1
        supported = application["input_position"].eq(supported_position)
        if supported.any():
            numeric = application.loc[
                supported,
                [
                    "linear_predictor",
                    "eta",
                    "pd_raw",
                    "score_unrounded",
                    "score",
                    "pd_calibrated",
                ],
            ]
            trace_path = result.output_dir / chunk["files"]["trace"]["path"]
            trace = pd.read_parquet(
                trace_path,
                columns=["input_position", "feature", "raw_state", "bin_id"],
            )
            trace_special = trace.loc[
                trace["input_position"].eq(supported_position) & trace["feature"].eq("x_000")
            ]
            if (
                application.loc[supported, "scoring_status"].eq("scored").all()
                and numeric.notna().all(axis=None)
                and len(trace_special.index) == 1
                and trace_special["raw_state"].eq("special").all()
                and trace_special["bin_id"].notna().all()
            ):
                supported_special_scored += 1
    if expected_start != expected_rows or scored + not_scorable != expected_rows:
        raise RuntimeError("la salida batch no conserva una fila por entrada")
    if not_scorable != 1 or null_failed != 1 or supported_special_scored != 1:
        raise RuntimeError(
            "se esperaba un -88888 soportado y un -99999 no puntuable; "
            f"observado={supported_special_scored}/{not_scorable}/{null_failed}"
        )
    return {
        "chunks": len(manifest["chunks"]),
        "output_bytes": output_bytes,
        "scored_rows": scored,
        "not_scorable_rows": not_scorable,
        "supported_special_scored": True,
        "input_hash": result.input_hash,
        "output_hash": result.output_hash,
        "ranges_contiguous": True,
        "physical_hashes_verified": True,
    }


def _semantic_hash(bundle: Any, frame: Any, chunk_size: int) -> str:
    from pandas.util import hash_pandas_object

    digest = hashlib.sha256(b"nikodym.batch.output.v1\0")
    rows = len(frame.index)
    for start in range(0, rows, chunk_size):
        result = bundle.apply(frame.iloc[start : start + chunk_size])
        application = result.application_frame.copy(deep=False)
        application["input_position"] += start
        for column in application.select_dtypes(include="object").columns:
            if application[column].map(lambda value: isinstance(value, list | dict | tuple)).any():
                application[column] = application[column].map(
                    lambda value: (
                        _canonical_json(value).decode("utf-8")
                        if isinstance(value, list | dict | tuple)
                        else value
                    )
                )
        hashes = hash_pandas_object(
            application,
            index=False,
            encoding="utf8",
            hash_key="0123456789123456",
            categorize=True,
        ).to_numpy(dtype="<u8", copy=True)
        digest.update(hashes.tobytes())
    return digest.hexdigest()


def _s0_chunk_equivalence(bundle: Any, batch_path: Path, expected: str) -> dict[str, Any]:
    import pandas as pd

    frame = pd.read_parquet(batch_path).set_index("row_id", drop=False)
    hashes = {str(size): _semantic_hash(bundle, frame, size) for size in (257, 4_096, len(frame))}
    prefix = frame.iloc[:257]
    prefix_hashes = {str(size): _semantic_hash(bundle, prefix, size) for size in (1, 257)}
    if set(hashes.values()) != {expected} or len(set(prefix_hashes.values())) != 1:
        raise RuntimeError("la salida semántica cambia al variar chunks 1/257/4096/full")
    return {"full_input_hashes": hashes, "chunk_1_prefix_257_hashes": prefix_hashes}


def _negative_contracts(
    bundle: Any, bundle_path: Path, sample: Any, workdir: Path
) -> dict[str, Any]:
    from unittest.mock import patch

    from nikodym.binning.transformer import WoEBinner
    from nikodym.calibration.calibrator import PDCalibrator
    from nikodym.scorecard.bundle import FittedScorecardBundle
    from nikodym.scorecard.exceptions import ScorecardBundleError
    from nikodym.scorecard.scaler import PointsScaler

    def explode(*args: Any, **kwargs: Any) -> None:
        del args, kwargs
        raise AssertionError("apply intentó refit")

    with (
        patch.object(WoEBinner, "fit", explode),
        patch.object(PDCalibrator, "fit", explode),
        patch.object(PointsScaler, "fit", explode),
    ):
        bundle.apply(sample.iloc[:2])
    incomplete = workdir / "bundle-incompleto"
    shutil.copytree(bundle_path, incomplete)
    (incomplete / "bins.parquet").unlink()
    try:
        FittedScorecardBundle.load(incomplete)
    except ScorecardBundleError:
        incomplete_rejected = True
    else:
        incomplete_rejected = False
    if not incomplete_rejected:
        raise RuntimeError("un bundle incompleto fue aceptado")
    return {"anti_refit_spies": True, "incomplete_bundle_rejected": True}


async def _body_case(limit: int, *, declared: int | None, sent: int) -> dict[str, Any]:
    from fastapi import FastAPI, Request
    from starlette.responses import JSONResponse

    from nikodym.ui.security import install_body_limit
    from nikodym.ui.settings import UiConfig

    app = FastAPI()
    consumed = 0

    async def sink(request: Any) -> JSONResponse:
        nonlocal consumed
        async for chunk in request.stream():
            consumed += len(chunk)
        return JSONResponse({"consumed": consumed})

    sink.__annotations__["request"] = Request
    app.post("/")(sink)

    install_body_limit(
        app,
        UiConfig(
            deploy_mode="local",
            theme="auto",
            upload_max_mb=limit // MIB,
            workdir=str(Path.cwd() / ".nikodym-ui-limit"),
            exposed_sections=(),
            allow_live_execution=True,
        ),
    )
    requested = 0
    responses: list[dict[str, Any]] = []
    remaining = sent

    async def receive() -> dict[str, Any]:
        nonlocal requested, remaining
        requested += 1
        size = min(MIB, remaining)
        remaining -= size
        return {
            "type": "http.request",
            "body": b"x" * size,
            "more_body": remaining > 0,
        }

    async def send(message: dict[str, Any]) -> None:
        responses.append(message)

    headers = [(b"content-type", b"application/octet-stream")]
    if declared is not None:
        headers.append((b"content-length", str(declared).encode()))
    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/",
        "raw_path": b"/",
        "root_path": "",
        "query_string": b"",
        "headers": headers,
        "client": ("127.0.0.1", 1),
        "server": ("127.0.0.1", 2),
    }
    await app(scope, receive, send)  # type: ignore[arg-type]
    status = [
        message["status"] for message in responses if message["type"] == "http.response.start"
    ]
    return {"status": status[0], "receive_calls": requested, "downstream_bytes": consumed}


def _ui_body_limit() -> dict[str, Any]:
    limit = 100 * MIB
    cases = {
        "content_length_n_minus_1": asyncio.run(
            _body_case(limit, declared=limit - 1, sent=limit - 1)
        ),
        "content_length_n": asyncio.run(_body_case(limit, declared=limit, sent=limit)),
        "content_length_n_plus_1": asyncio.run(
            _body_case(limit, declared=limit + 1, sent=limit + 1)
        ),
        "chunked_n_plus_1": asyncio.run(_body_case(limit, declared=None, sent=limit + 1)),
    }
    if cases["content_length_n_minus_1"]["status"] != 200:
        raise RuntimeError("N-1 fue rechazado")
    if cases["content_length_n"]["status"] != 200:
        raise RuntimeError("N fue rechazado")
    if cases["content_length_n_plus_1"] != {
        "status": 422,
        "receive_calls": 0,
        "downstream_bytes": 0,
    }:
        raise RuntimeError("Content-Length N+1 no fue rechazado antes del consumidor")
    chunked = cases["chunked_n_plus_1"]
    if chunked["status"] != 422 or chunked["downstream_bytes"] != limit:
        raise RuntimeError("chunked N+1 no cortó antes de entregar el byte N+1")
    return {"limit_bytes": limit, "cases": cases}


def _consume_request(request_path: Path) -> dict[str, Any]:
    """CR-02: load/apply/batch en un consumidor nuevo que sólo importa el wheel instalado."""
    import pandas as pd

    import nikodym
    from nikodym.scorecard.bundle import FittedScorecardBundle

    module = Path(nikodym.__file__).resolve()
    if module.is_relative_to(ROOT) or "site-packages" not in module.parts:
        raise RuntimeError(f"el consumidor resolvió Nikodym fuera de site-packages: {module}")
    request = json.loads(request_path.read_text(encoding="utf-8"))
    bundle_path = Path(request["bundle_path"])
    sample_path = Path(request["sample_path"])
    source = Path(request["batch_source"])
    output_dir = Path(request["batch_output"])
    profile = request["profile"]
    loaded = FittedScorecardBundle.load(bundle_path)
    sample = pd.read_parquet(sample_path)

    started = time.perf_counter()
    cold = loaded.apply(sample)
    cold_seconds = time.perf_counter() - started
    started = time.perf_counter()
    hot = loaded.apply(sample)
    hot_seconds = time.perf_counter() - started
    pd.testing.assert_frame_equal(cold.application_frame, hot.application_frame)
    if cold.summary["input_rows"] != len(sample) or cold.summary["not_scorable_rows"] != 0:
        raise RuntimeError("apply limpio no conservó/puntuó todas las filas")
    first_application = cold.application_frame.iloc[0]
    first_trace = cold.trace_frame.loc[
        cold.trace_frame["input_position"].eq(0) & cold.trace_frame["feature"].eq("x_000")
    ]
    supported_special_scored = bool(
        first_application["scoring_status"] == "scored"
        and first_application[
            ["linear_predictor", "eta", "pd_raw", "score_unrounded", "score", "pd_calibrated"]
        ]
        .notna()
        .all()
        and len(first_trace.index) == 1
        and first_trace["raw_state"].eq("special").all()
        and first_trace["bin_id"].notna().all()
    )
    if not supported_special_scored:
        raise RuntimeError("CR-02 no puntuó el special con soporte congelado")
    negatives = _negative_contracts(loaded, bundle_path, sample, request_path.parent)

    started = time.perf_counter()
    batch = loaded.apply_file(
        source,
        output_dir,
        chunk_size=int(profile["batch_chunk_size"]),
        id_column="row_id",
    )
    batch_seconds = time.perf_counter() - started
    final_features = len(loaded.manifest["model"]["features"])
    verified = _verify_batch(
        batch,
        expected_rows=int(profile["batch_rows"]),
        expected_features=final_features,
    )
    chunk_equivalence = (
        _s0_chunk_equivalence(loaded, source, batch.output_hash)
        if request["profile_name"] == "S0-smoke"
        else None
    )
    return {
        "pid": os.getpid(),
        "nikodym_file": str(module),
        "bundle_hash": loaded.bundle_hash,
        "final_features": final_features,
        "apply": {
            "sample_rows": len(sample),
            "cold_seconds": round(cold_seconds, 6),
            "hot_seconds": round(hot_seconds, 6),
            "cold_under_2_seconds": cold_seconds <= 2.0,
            "hot_under_2_seconds": hot_seconds <= 2.0,
            "summary": dict(cold.summary),
            "supported_special_scored": True,
            "lineage": dict(cold.lineage),
            "negatives": negatives,
        },
        "batch": {
            "seconds": round(batch_seconds, 6),
            "chunk_size": int(profile["batch_chunk_size"]),
            **verified,
            "chunk_equivalence": chunk_equivalence,
        },
        "peak_rss_bytes": _peak_rss_bytes(),
    }


def _spawn_consumer(
    *,
    workdir: Path,
    bundle_path: Path,
    sample_path: Path,
    batch_source: Path,
    profile_name: str,
    profile: dict[str, int],
) -> dict[str, Any]:
    request = workdir / "consumer-request.json"
    output = workdir / "consumer-result.json"
    request.write_bytes(
        _canonical_json(
            {
                "bundle_path": str(bundle_path),
                "sample_path": str(sample_path),
                "batch_source": str(batch_source),
                "batch_output": str(workdir / "batch-output"),
                "profile_name": profile_name,
                "profile": profile,
            }
        )
        + b"\n"
    )
    environment = dict(os.environ)
    environment["PYTHONPATH"] = ""
    completed = subprocess.run(
        [
            sys.executable,
            str(Path(__file__).resolve()),
            "--internal-consumer",
            str(request),
            str(output),
        ],
        cwd=workdir,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=profile["batch_seconds"] + 300,
    )
    process_evidence = {
        "returncode": completed.returncode,
        "stdout_sha256": hashlib.sha256(completed.stdout.encode()).hexdigest(),
        "stderr_sha256": hashlib.sha256(completed.stderr.encode()).hexdigest(),
    }
    if completed.returncode != 0 or not output.is_file():
        raise RuntimeError(
            "el consumidor clean-room falló: "
            f"returncode={completed.returncode}; stderr={completed.stderr[-2_000:]}"
        )
    payload = json.loads(output.read_text(encoding="utf-8"))
    payload["process"] = process_evidence
    return payload


def _report_evidence(report_dir: Path) -> dict[str, Any]:
    files = sorted(path for path in report_dir.rglob("*") if path.is_file())
    suffixes = {path.suffix.lower() for path in files}
    if ".html" not in suffixes or ".qmd" not in suffixes:
        raise RuntimeError("CR-01 no publicó el informe HTML+QMD esperado")
    return {
        "files": [
            {
                "path": str(path.relative_to(report_dir)),
                "bytes": path.stat().st_size,
                "sha256": _sha256(path),
            }
            for path in files
        ],
        "html_verified": True,
        "markdown_verified": True,
    }


def _run(profile_name: str, wheel: Path, workdir: Path, source_sha: str) -> dict[str, Any]:
    import pandas as pd

    from nikodym.scorecard.bundle import fit_scorecard_bundle

    profile = PROFILES[profile_name]
    hardware = _hardware(workdir)
    memory = hardware["memory_bytes"] or 0
    eligible = (
        hardware["logical_cpus"] >= profile["logical_cpus"] and memory >= profile["ram_gib"] * GIB
    )
    if hardware["disk_free_bytes_before"] < profile["disk_free_gib"] * GIB:
        raise RuntimeError(
            f"disco insuficiente: requiere {profile['disk_free_gib']} GiB libres antes de medir"
        )
    identity = _cleanroom_identity(wheel, source_sha=source_sha)
    generated = _training_frame(profile)
    training_source = workdir / "training.csv"
    generated.to_csv(training_source, index=True)
    del generated
    frame = pd.read_csv(training_source, index_col="row_id")
    observed_cardinality = int(frame["x_000"].nunique())
    if observed_cardinality != profile["cardinality"]:
        raise RuntimeError(
            "el generador no materializó la cardinalidad categórica contractual: "
            f"esperado={profile['cardinality']}, observado={observed_cardinality}"
        )
    report_dir = workdir / "report"
    config = _config(profile, report_dir=report_dir)
    started = time.perf_counter()
    bundle = fit_scorecard_bundle(config, frame)
    train_seconds = time.perf_counter() - started
    bundle_path = bundle.save(workdir / "scorecard-bundle")
    targetless = frame.drop(columns=["bad_flag"])
    sample = targetless.iloc[: min(10_000, len(targetless))]
    sample_path = workdir / "consumer-sample.parquet"
    sample.to_parquet(sample_path)
    source = workdir / "portfolio.parquet"
    source_evidence = _write_batch(source, profile)
    consumer = _spawn_consumer(
        workdir=workdir,
        bundle_path=bundle_path,
        sample_path=sample_path,
        batch_source=source,
        profile_name=profile_name,
        profile=profile,
    )
    if consumer["bundle_hash"] != bundle.bundle_hash:
        raise RuntimeError("save/load en consumidor cambió el bundle_hash")
    final_features = int(consumer["final_features"])
    if final_features != profile["variables"]:
        raise RuntimeError(
            "el perfil no preservó la geometría final requerida: "
            f"esperado={profile['variables']}, observado={final_features}"
        )
    body_limit = _ui_body_limit() if profile_name == "S0-smoke" else None
    report = _report_evidence(report_dir)
    peak = max(_peak_rss_bytes(), int(consumer["peak_rss_bytes"]))
    disk_after = shutil.disk_usage(workdir).free
    budgets = {
        "train": train_seconds <= profile["train_seconds"],
        "batch": consumer["batch"]["seconds"] <= profile["batch_seconds"],
        "peak_rss": peak <= profile["peak_gib"] * GIB,
    }
    status = "pass" if eligible and all(budgets.values()) else "informative"
    if eligible and not all(budgets.values()):
        status = "fail"
    return {
        "schema_version": SCHEMA_VERSION,
        "source_sha": source_sha,
        "driver_sha256": _sha256(Path(__file__)),
        "profile": profile_name,
        "profile_contract": profile,
        "profile_status": status,
        "hardware_eligible": eligible,
        "hardware": {**hardware, "disk_free_bytes_after": disk_after},
        "cleanroom": identity,
        "train": {
            "rows": profile["train_rows"],
            "variables": profile["variables"],
            "cardinality_observed": observed_cardinality,
            "categorical_cardinality_observed": observed_cardinality,
            "input_bytes_deep": int(frame.memory_usage(index=True, deep=True).sum()),
            "csv_bytes": training_source.stat().st_size,
            "csv_sha256": _sha256(training_source),
            "seconds": round(train_seconds, 6),
            "bundle_hash": bundle.bundle_hash,
            "bundle_manifest_sha256": _sha256(bundle_path / "manifest.json"),
            "bundle_rules_sha256": _sha256(bundle_path / "bins.parquet"),
            "final_features": final_features,
            "lineage_uv_lock_hash": bundle.manifest["fit_lineage"]["uv_lock_hash"],
            "lineage_runtime_environment_hash": bundle.manifest["fit_lineage"][
                "runtime_environment_hash"
            ],
            "report": report,
        },
        "apply": consumer["apply"],
        "batch_source": source_evidence,
        "batch": consumer["batch"],
        "consumer_process": {
            "pid": consumer["pid"],
            "nikodym_file": consumer["nikodym_file"],
            **consumer["process"],
        },
        "ui_body_limit": body_limit,
        "resources": {"peak_rss_bytes": peak},
        "budgets": budgets,
    }


def _run_s3(wheel: Path, workdir: Path, source_sha: str, bundle_path: Path) -> dict[str, Any]:
    """Prueba los cuatro techos H9=B por superficies públicas y sin crear solver/output."""
    from unittest.mock import patch

    import numpy as np
    import pandas as pd
    import pyarrow as pa
    import pyarrow.parquet as pq

    from nikodym.scorecard.bundle import FittedScorecardBundle, fit_scorecard_bundle
    from nikodym.scorecard.exceptions import ScorecardBundleError

    identity = _cleanroom_identity(wheel, source_sha=source_sha)

    class AcceptedPreflightError(Exception):
        pass

    def stop_before_engine(*args: Any, **kwargs: Any) -> None:
        del args, kwargs
        raise AcceptedPreflightError

    def observed_fit(frame: Any, config: Any) -> str:
        try:
            with patch("nikodym.api.run", stop_before_engine):
                fit_scorecard_bundle(config, frame)
        except AcceptedPreflightError:
            return "accepted"
        except ScorecardBundleError:
            return "rejected"
        raise RuntimeError("el fit cruzó el preflight y llegó a ejecutar el motor")

    row_cases: dict[str, str] = {}
    for rows in (999_999, 1_000_000, 1_000_001):
        profile = {**PROFILES["S0-smoke"], "train_rows": rows, "variables": 1, "cardinality": 1}
        frame = pd.DataFrame(
            {"x_000": np.zeros(rows, dtype="int8"), "bad_flag": np.zeros(rows, dtype="int8")},
            index=pd.RangeIndex(rows, name="row_id"),
        )
        row_cases[str(rows)] = observed_fit(
            frame, _config(profile, report_dir=workdir / f"report-rows-{rows}")
        )

    variable_cases: dict[str, str] = {}
    for variables in (99, 100, 101):
        profile = {
            **PROFILES["S0-smoke"],
            "train_rows": 1,
            "variables": variables,
            "cardinality": 1,
        }
        frame = pd.DataFrame(
            {
                **{f"x_{position:03d}": np.zeros(1, dtype="int8") for position in range(variables)},
                "bad_flag": np.zeros(1, dtype="int8"),
            },
            index=pd.RangeIndex(1, name="row_id"),
        )
        config = _config(profile, report_dir=workdir / f"report-variables-{variables}")
        assert config.binning is not None
        config = config.model_copy(
            update={"binning": config.binning.model_copy(update={"feature_columns": "*"})}
        )
        variable_cases[str(variables)] = observed_fit(frame, config)

    cardinality_cases: dict[str, str] = {}
    for cardinality in (99_999, 100_000, 100_001):
        profile = {
            **PROFILES["S0-smoke"],
            "train_rows": cardinality,
            "variables": 1,
            "cardinality": cardinality,
        }
        frame = pd.DataFrame(
            {
                "x_000": np.arange(cardinality, dtype="int32"),
                "bad_flag": np.zeros(cardinality, dtype="int8"),
            },
            index=pd.RangeIndex(cardinality, name="row_id"),
        )
        cardinality_cases[str(cardinality)] = observed_fit(
            frame, _config(profile, report_dir=workdir / f"report-cardinality-{cardinality}")
        )

    loaded = FittedScorecardBundle.load(bundle_path)
    features = tuple(loaded.manifest["model"]["features"])
    batch_cases: dict[str, str] = {}
    for rows in (4_999_999, 5_000_000, 5_000_001):
        source = workdir / f"batch-limit-{rows}.parquet"
        writer: Any = None
        try:
            for start in range(0, rows, 100_000):
                size = min(100_000, rows - start)
                table = pa.table(
                    {
                        "row_id": np.arange(start, start + size, dtype="int64"),
                        **{feature: np.zeros(size, dtype="int8") for feature in features},
                    }
                )
                if writer is None:
                    writer = pq.ParquetWriter(source, table.schema, compression="zstd")
                writer.write_table(table, row_group_size=100_000)
        finally:
            if writer is not None:
                writer.close()
        try:
            with patch.object(FittedScorecardBundle, "apply", stop_before_engine):
                loaded.apply_file(
                    source,
                    workdir / f"batch-limit-output-{rows}",
                    chunk_size=1,
                    id_column="row_id",
                )
        except AcceptedPreflightError:
            batch_cases[str(rows)] = "accepted"
        except ScorecardBundleError:
            batch_cases[str(rows)] = "rejected"
        else:
            raise RuntimeError("el batch cruzó el preflight y llegó a materializar salida")
    cases = {
        "train_rows": row_cases,
        "train_variables": variable_cases,
        "train_cardinality": cardinality_cases,
        "batch_rows": batch_cases,
    }
    expected = {
        "train_rows": {"999999": "accepted", "1000000": "accepted", "1000001": "rejected"},
        "train_variables": {"99": "accepted", "100": "accepted", "101": "rejected"},
        "train_cardinality": {
            "99999": "accepted",
            "100000": "accepted",
            "100001": "rejected",
        },
        "batch_rows": {"4999999": "accepted", "5000000": "accepted", "5000001": "rejected"},
    }
    if cases != expected:
        raise RuntimeError(f"los límites S3 no respetan N-1/N/N+1: {cases!r}")
    return {
        "schema_version": SCHEMA_VERSION,
        "source_sha": source_sha,
        "driver_sha256": _sha256(Path(__file__)),
        "profile": "S3-limite",
        "profile_status": "pass",
        "cleanroom": identity,
        "bundle_hash": loaded.bundle_hash,
        "limits": cases,
        "hardware": _hardware(workdir),
    }


def main() -> int:
    """Ejecuta un perfil y escribe evidencia canónica inmutable."""
    if len(sys.argv) == 4 and sys.argv[1] == "--internal-consumer":
        request = Path(sys.argv[2]).resolve()
        output = Path(sys.argv[3]).resolve()
        try:
            payload = _consume_request(request)
        except Exception as exc:
            print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
            return 1
        output.write_bytes(_canonical_json(payload) + b"\n")
        return 0
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", choices=(*PROFILES, "S3-limite"), required=True)
    parser.add_argument("--wheel", type=Path, required=True)
    parser.add_argument("--workdir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--s3-bundle", type=Path)
    args = parser.parse_args()
    if args.output.exists():
        raise SystemExit(f"la evidencia W1 no se sobrescribe: {args.output}")
    if not args.wheel.is_file():
        raise SystemExit(f"wheel ausente: {args.wheel}")
    workdir = _validate_external_workdir(args.workdir)
    workdir.mkdir(parents=True, exist_ok=False)
    started_wall = time.perf_counter()
    started_cpu = time.process_time()
    try:
        if args.profile == "S3-limite":
            if args.s3_bundle is None:
                raise RuntimeError("S3-limite exige --s3-bundle producido por S0")
            payload = _run_s3(
                args.wheel.resolve(),
                workdir,
                args.source_sha,
                args.s3_bundle.resolve(),
            )
        else:
            payload = _run(
                args.profile,
                args.wheel.resolve(),
                workdir,
                args.source_sha,
            )
        exit_code = 0 if payload["profile_status"] != "fail" else 1
    except Exception as exc:
        payload = {
            "schema_version": SCHEMA_VERSION,
            "source_sha": args.source_sha,
            "profile": args.profile,
            "profile_status": "error",
            "error_type": type(exc).__name__,
            "error": str(exc),
            "traceback": traceback.format_exc(),
        }
        exit_code = 1
    payload["process"] = {
        "wall_seconds": round(time.perf_counter() - started_wall, 6),
        "cpu_seconds": round(time.process_time() - started_cpu, 6),
        "peak_rss_bytes": _peak_rss_bytes(),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(_canonical_json(payload) + b"\n")
    print(json.dumps({"output": str(args.output), "status": payload["profile_status"]}))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
