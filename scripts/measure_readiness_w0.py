"""Congela el baseline W0 de readiness sin implementar superficies W1.

El arnés mide únicamente caminos que ya existen en Nikodym y proxies explícitos. Cada medición
pesada corre en un proceso aislado, con ``PYTHONHASHSEED=0`` y timeout. Las celdas que no pueden
medirse por ausencia de superficie o de hardware se publican como ``no_medible``; nunca se
convierten en PASS ni rebajan el envelope S2 aprobado por H9=B.

Uso desde un checkout limpio::

    .venv/bin/python scripts/measure_readiness_w0.py \
        --output docs/design/evidencia/readiness-w0-2026-08-09.json

El JSON resultante es evidencia factual de W0, no una API pública ni un benchmark de W1.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import resource
import subprocess
import sys
import tempfile
import time
import traceback
from collections import Counter
from importlib import metadata
from pathlib import Path
from typing import Any, Final

SCHEMA_VERSION: Final = "nikodym.readiness.w0.v1"
ROOT: Final = Path(__file__).resolve().parents[1]
MIB: Final = 1024 * 1024
GIB: Final = 1024 * MIB

PROFILES: Final[dict[str, dict[str, int]]] = {
    "S0-smoke": {
        "rows": 10_000,
        "variables": 25,
        "cardinality": 100,
        "horizon": 12,
        "scenarios": 1,
        "target_ram_gib": 4,
    },
    "S1-local": {
        "rows": 100_000,
        "variables": 50,
        "cardinality": 10_000,
        "horizon": 60,
        "scenarios": 3,
        "target_ram_gib": 16,
    },
    "S2-equipo": {
        "rows": 1_000_000,
        "batch_rows": 5_000_000,
        "temporal_operations": 100_000,
        "variables": 100,
        "cardinality": 100_000,
        "horizon": 120,
        "scenarios": 5,
        "target_ram_gib": 32,
    },
}

PROBES: Final[tuple[str, ...]] = (
    "contract-census",
    "frame-hash-s0",
    "frame-hash-s1",
    "frame-hash-s2",
    "preset-f1",
    "preset-f3",
    "preset-f4",
    "score-train-s0",
)

TIMEOUTS: Final[dict[str, int]] = {
    "contract-census": 60,
    "frame-hash-s0": 120,
    "frame-hash-s1": 180,
    "frame-hash-s2": 300,
    "preset-f1": 300,
    "preset-f3": 300,
    "preset-f4": 300,
    "score-train-s0": 300,
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _bytes_sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _git(*args: str) -> str:
    return subprocess.check_output(
        ("git", *args), cwd=ROOT, text=True, stderr=subprocess.STDOUT
    ).strip()


def _total_memory_bytes() -> int | None:
    try:
        return int(os.sysconf("SC_PHYS_PAGES")) * int(os.sysconf("SC_PAGE_SIZE"))
    except (OSError, ValueError):
        return None


def _rss_bytes() -> int:
    raw = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    return raw if sys.platform == "darwin" else raw * 1024


def _package_versions() -> dict[str, str]:
    versions: dict[str, str] = {}
    for package in ("nikodym", "numpy", "pandas", "pyarrow", "scikit-learn", "pydantic"):
        try:
            versions[package] = metadata.version(package)
        except metadata.PackageNotFoundError:
            versions[package] = "no_instalado"
    return versions


def _ui_settings(workdir: Path) -> Any:
    from nikodym.ui.settings import UiConfig

    return UiConfig(
        deploy_mode="local",
        theme="auto",
        upload_max_mb=100,
        workdir=str(workdir),
        exposed_sections=(),
        allow_live_execution=True,
    )


def _probe_contract_census() -> dict[str, Any]:
    import inspect

    import nikodym
    from nikodym.ui import jobs
    from nikodym.ui.routes import run_pipeline
    from nikodym.ui.serializers import serialize_study

    options = [
        option
        for points in jobs._ABANICO_POR_SECCION.values()
        for point in points
        for option in point["options"]
    ]
    counts = Counter(option["estado"] for option in options)
    serializer_parameters = inspect.signature(serialize_study).parameters
    run_source = inspect.getsource(run_pipeline)
    return {
        "kind": "census",
        "status": "measured",
        "option_pairs": len(options),
        "option_states": dict(sorted(counts.items())),
        "public_apply_exported": hasattr(nikodym, "apply"),
        "ui_upload_max_mib": _ui_settings(Path(".nikodym_ui")).upload_max_mb,
        "ui_run_calls_nikodym_directly": "nikodym.run(" in run_source,
        "ui_run_is_coroutine": inspect.iscoroutinefunction(run_pipeline),
        "ui_results_pagination": bool(
            {"page", "page_size", "cursor"} & serializer_parameters.keys()
        ),
    }


def _frame_for_profile(profile_name: str) -> Any:
    import numpy as np
    import pandas as pd

    profile = PROFILES[profile_name]
    rows = profile["rows"]
    variables = profile["variables"]
    cardinality = profile["cardinality"]
    base = np.arange(rows, dtype=np.uint32)
    columns = {
        f"x_{position:03d}": ((base * (2 * position + 1) + position) % cardinality).astype(
            "uint32", copy=False
        )
        for position in range(variables)
    }
    return pd.DataFrame(columns, index=pd.RangeIndex(rows, name="row_id"), copy=False)


def _probe_frame_hash(profile_name: str) -> dict[str, Any]:
    from nikodym.data.hashing import data_hash

    frame = _frame_for_profile(profile_name)
    started = time.perf_counter()
    digest = data_hash(frame)
    first_seconds = time.perf_counter() - started
    started = time.perf_counter()
    repeated = data_hash(frame)
    repeat_seconds = time.perf_counter() - started
    return {
        "kind": "current_component_proxy",
        "status": "proxy",
        "profile": profile_name,
        "surface": "nikodym.data.hashing.data_hash",
        "rows": int(frame.shape[0]),
        "variables": int(frame.shape[1]),
        "observed_cardinality": int(frame.iloc[:, 0].nunique()),
        "input_bytes_deep": int(frame.memory_usage(index=True, deep=True).sum()),
        "digest": digest,
        "repeat_digest_equal": repeated == digest,
        "first_hash_seconds": round(first_seconds, 6),
        "repeat_hash_seconds": round(repeat_seconds, 6),
        "limitation": "proxy tabular int32; no ejecuta un flujo M ni demuestra su envelope",
    }


def _client(workdir: Path) -> Any:
    from fastapi.testclient import TestClient

    from nikodym.ui.runtime import TOKEN_HEADER, build_runtime
    from nikodym.ui.server import create_app

    runtime = build_runtime(port=8000, workdir=workdir)
    app = create_app(_ui_settings(workdir), runtime)
    return TestClient(
        app,
        base_url=runtime.origin,
        headers={"Origin": runtime.origin, TOKEN_HEADER: runtime.token},
    )


def _run_preset(preset_id: str) -> dict[str, Any]:
    from nikodym.ui import datasets

    with tempfile.TemporaryDirectory(prefix="nikodym-w0-preset-") as temp:
        workdir = Path(temp)
        with _client(workdir) as client:
            preset = client.get(f"/api/config/preset/{preset_id}")
            preset.raise_for_status()
            descriptor = preset.json()
            started = time.perf_counter()
            run = client.post(
                "/api/run",
                json={"config": descriptor["config"], "dataset_id": descriptor["dataset_id"]},
            )
            run_seconds = time.perf_counter() - started
            run.raise_for_status()
            run_payload = run.json()
            if run_payload.get("status") != "done":
                failed = client.get(f"/api/results/{run_payload['run_id']}")
                raise RuntimeError(
                    f"preset {preset_id} terminó {run_payload!r}: {failed.text[:1_000]}"
                )
            run_id = run_payload["run_id"]
            results = client.get(f"/api/results/{run_id}")
            report = client.get(f"/api/report/{run_id}")
            results.raise_for_status()
            report.raise_for_status()
            result_payload = results.json()
            lineage = result_payload.get("lineage") or {}
            source = datasets.materialize(descriptor["dataset_id"], workdir=workdir)
            frame = datasets.load_frame(descriptor["dataset_id"], workdir=workdir)
            files = [path for path in workdir.rglob("*") if path.is_file()]
            suffix_counts = Counter(path.suffix or "<sin_sufijo>" for path in files)
            return {
                "kind": "current_surface_proxy",
                "status": "proxy",
                "preset_id": preset_id,
                "dataset_id": descriptor["dataset_id"],
                "input_rows": int(frame.shape[0]),
                "input_columns": int(frame.shape[1]),
                "input_file_bytes": source.stat().st_size,
                "run_seconds": round(run_seconds, 6),
                "results_bytes": len(results.content),
                "report_html_bytes": len(report.content),
                "workdir_file_count": len(files),
                "workdir_bytes": sum(path.stat().st_size for path in files),
                "workdir_suffix_counts": dict(sorted(suffix_counts.items())),
                "lineage_git_sha": lineage.get("git_sha"),
                "lineage_git_dirty": lineage.get("git_dirty"),
                "lineage_data_hash": lineage.get("data_hash"),
                "lineage_config_hash": lineage.get("config_hash"),
                "lineage_uv_lock_hash": lineage.get("uv_lock_hash"),
                "limitation": "preset real bajo S0; no sustituye una medición del perfil",
            }


def _schema_column(name: str, dtype: str) -> dict[str, Any]:
    return {
        "name": name,
        "dtype": dtype,
        "nullable": False,
        "required": True,
        "coerce": False,
        "ge": None,
        "le": None,
        "isin": None,
        "unique": False,
    }


def _score_s0_frame(workdir: Path) -> Any:
    import numpy as np
    import pandas as pd

    from nikodym.ui import datasets

    base_path = datasets.materialize("consumo_comportamiento", workdir=workdir)
    base = pd.read_parquet(base_path).reset_index()
    repeats = (PROFILES["S0-smoke"]["rows"] + len(base) - 1) // len(base)
    frame = pd.concat([base] * repeats, ignore_index=True).iloc[:10_000].copy()
    frame["loan_id"] = [f"w0-{position:06d}" for position in range(len(frame))]
    rng = np.random.default_rng(30_000)
    for position in range(1, 19):
        frame[f"proxy_num_{position:02d}"] = rng.normal(size=len(frame)).round(6)
    frame["proxy_cat_100"] = np.asarray(
        [f"c-{position % 100:03d}" for position in range(len(frame))], dtype=object
    )
    return frame.set_index("loan_id")


def _probe_score_train_s0() -> dict[str, Any]:
    import io

    from nikodym.ui.presets import standard_preset

    with tempfile.TemporaryDirectory(prefix="nikodym-w0-s0-") as temp:
        workdir = Path(temp)
        frame = _score_s0_frame(workdir)
        descriptor = standard_preset()
        config = descriptor["config"]
        numeric = [f"proxy_num_{position:02d}" for position in range(1, 19)]
        categorical = "proxy_cat_100"
        added = [*numeric, categorical]
        config["data"]["schema"]["columns"].extend(
            [_schema_column(name, "float") for name in numeric]
            + [_schema_column(categorical, "str")]
        )
        config["binning"]["feature_columns"].extend(added)
        config["binning"]["categorical_columns"].append(categorical)
        payload = io.BytesIO()
        frame.to_parquet(payload, index=True)

        with _client(workdir) as client:
            upload = client.post(
                "/api/upload",
                files={
                    "file": (
                        "readiness_s0.parquet",
                        payload.getvalue(),
                        "application/octet-stream",
                    )
                },
            )
            upload.raise_for_status()
            dataset_id = upload.json()["dataset_id"]
            started = time.perf_counter()
            run = client.post("/api/run", json={"config": config, "dataset_id": dataset_id})
            run_seconds = time.perf_counter() - started
            run.raise_for_status()
            run_payload = run.json()
            if run_payload.get("status") != "done":
                failed = client.get(f"/api/results/{run_payload['run_id']}")
                raise RuntimeError(f"S0 scorecard terminó {run_payload!r}: {failed.text[:1_000]}")
            run_id = run_payload["run_id"]
            results = client.get(f"/api/results/{run_id}")
            report = client.get(f"/api/report/{run_id}")
            results.raise_for_status()
            report.raise_for_status()
            result_payload = results.json()
            lineage = result_payload.get("lineage") or {}
            files = [path for path in workdir.rglob("*") if path.is_file()]
            suffix_counts = Counter(path.suffix or "<sin_sufijo>" for path in files)
            return {
                "kind": "current_surface",
                "status": "measured",
                "profile": "S0-smoke",
                "surface": "upload→nikodym.run(F1)→results+HTML",
                "input_rows": int(frame.shape[0]),
                "input_columns_total": int(frame.shape[1]),
                "feature_variables": len(config["binning"]["feature_columns"]),
                "observed_categorical_cardinality": int(frame[categorical].nunique()),
                "input_parquet_bytes": len(payload.getvalue()),
                "run_seconds": round(run_seconds, 6),
                "within_s0_time_budget": run_seconds <= 300,
                "results_bytes": len(results.content),
                "report_html_bytes": len(report.content),
                "workdir_file_count": len(files),
                "workdir_bytes": sum(path.stat().st_size for path in files),
                "workdir_suffix_counts": dict(sorted(suffix_counts.items())),
                "lineage_git_sha": lineage.get("git_sha"),
                "lineage_git_dirty": lineage.get("git_dirty"),
                "lineage_data_hash": lineage.get("data_hash"),
                "lineage_config_hash": lineage.get("config_hash"),
                "lineage_uv_lock_hash": lineage.get("uv_lock_hash"),
                "limitation": (
                    "mide la superficie F1/UI actual; no existe bundle apply y los resultados "
                    "siguen serializándose completos"
                ),
            }


def _execute_probe(name: str) -> dict[str, Any]:
    if name == "contract-census":
        return _probe_contract_census()
    if name.startswith("frame-hash-"):
        profile = {
            "frame-hash-s0": "S0-smoke",
            "frame-hash-s1": "S1-local",
            "frame-hash-s2": "S2-equipo",
        }[name]
        return _probe_frame_hash(profile)
    if name.startswith("preset-"):
        preset_id = {
            "preset-f1": "f1-estandar-consumo",
            "preset-f3": "f3-provisiones-consumo",
            "preset-f4": "f4-ifrs9-retail",
        }[name]
        return _run_preset(preset_id)
    if name == "score-train-s0":
        return _probe_score_train_s0()
    raise ValueError(f"probe desconocido: {name}")


def _child(name: str, result_path: Path) -> int:
    started_wall = time.perf_counter()
    started_cpu = time.process_time()
    try:
        payload = _execute_probe(name)
        exit_code = 0
    except Exception as exc:  # la evidencia debe conservar el fallo exacto del probe
        payload = {
            "kind": "probe_failure",
            "status": "error",
            "error_type": type(exc).__name__,
            "error": str(exc),
            "traceback": traceback.format_exc(),
        }
        exit_code = 1
    payload.update(
        {
            "probe": name,
            "wall_seconds": round(time.perf_counter() - started_wall, 6),
            "cpu_seconds": round(time.process_time() - started_cpu, 6),
            "peak_rss_bytes": _rss_bytes(),
        }
    )
    result_path.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True), encoding="utf-8"
    )
    return exit_code


def _no_medible_cells(total_memory: int | None) -> list[dict[str, Any]]:
    host = "desconocida" if total_memory is None else f"{total_memory / GIB:.1f} GiB"
    cells: list[dict[str, Any]] = []
    for profile in ("S1-local", "S2-equipo"):
        cells.append(
            {
                "channel": "score_train",
                "profile": profile,
                "status": "no_medible",
                "reason": (
                    f"host de {host} no cumple RAM de referencia "
                    f"{PROFILES[profile]['target_ram_gib']} GiB; W0 no fuerza OOM ni extrapola S0"
                ),
            }
        )
    for profile in PROFILES:
        cells.append(
            {
                "channel": "score_apply_batch",
                "profile": profile,
                "status": "no_medible",
                "reason": "F-SCORE-APPLY/F-SCORE-BATCH no tienen bundle/API targetless actual",
            }
        )
        cells.append(
            {
                "channel": "temporal_forward_stress",
                "profile": profile,
                "status": "no_medible",
                "reason": (
                    "no existe flujo integrado forward real→IFRS 9 real→stress; el preset F4 "
                    "es sólo proxy bajo S0"
                ),
            }
        )
    for profile in ("S1-local", "S2-equipo"):
        cells.append(
            {
                "channel": "ui",
                "profile": profile,
                "status": "no_medible",
                "reason": (
                    "la UI actual parsea/spool multipart antes del handler, serializa resultados "
                    "completos y no pagina; medir sólo el tamaño aceptado no demostraría el perfil"
                ),
            }
        )
    return cells


def _run_parent(output: Path) -> int:
    dirty = _git("status", "--porcelain", "--untracked-files=no")
    if dirty:
        raise SystemExit(
            "W0 exige un commit limpio para congelar evidencia; hay cambios tracked:\n" + dirty
        )
    total_memory = _total_memory_bytes()
    with tempfile.TemporaryDirectory(prefix="nikodym-w0-run-") as temp:
        temp_root = Path(temp)
        measurements: list[dict[str, Any]] = []
        for probe in PROBES:
            result_path = temp_root / f"{probe}.json"
            env = os.environ.copy()
            env["PYTHONHASHSEED"] = "0"
            env["MPLCONFIGDIR"] = str(temp_root / "matplotlib")
            command = (
                sys.executable,
                str(Path(__file__).resolve()),
                "--_probe",
                probe,
                "--_result",
                str(result_path),
            )
            try:
                completed = subprocess.run(
                    command,
                    cwd=ROOT,
                    env=env,
                    capture_output=True,
                    timeout=TIMEOUTS[probe],
                    check=False,
                )
            except subprocess.TimeoutExpired as exc:
                measurements.append(
                    {
                        "probe": probe,
                        "kind": "guarded_timeout",
                        "status": "no_medible",
                        "timeout_seconds": TIMEOUTS[probe],
                        "stdout_sha256": _bytes_sha256(exc.stdout or b""),
                        "stderr_sha256": _bytes_sha256(exc.stderr or b""),
                    }
                )
                continue
            if not result_path.exists():
                measurements.append(
                    {
                        "probe": probe,
                        "kind": "probe_failure",
                        "status": "error",
                        "returncode": completed.returncode,
                        "stdout_sha256": _bytes_sha256(completed.stdout),
                        "stderr_sha256": _bytes_sha256(completed.stderr),
                    }
                )
                continue
            payload = json.loads(result_path.read_text(encoding="utf-8"))
            payload["returncode"] = completed.returncode
            payload["stdout_sha256"] = _bytes_sha256(completed.stdout)
            payload["stderr_sha256"] = _bytes_sha256(completed.stderr)
            measurements.append(payload)

    profile_cells: list[dict[str, Any]] = [
        {
            "channel": "score_train",
            "profile": "S0-smoke",
            "status": "measured",
            "evidence_probe": "score-train-s0",
        },
        {
            "channel": "ui",
            "profile": "S0-smoke",
            "status": "measured",
            "evidence_probe": "score-train-s0",
            "limitation": "sin paginación ni lifecycle de job",
        },
        *_no_medible_cells(total_memory),
    ]
    evidence = {
        "schema_version": SCHEMA_VERSION,
        "scope": "W0_only",
        "source": {
            "git_sha": _git("rev-parse", "HEAD"),
            "git_branch": _git("branch", "--show-current"),
            "git_dirty": False,
            "measurement_script": str(Path(__file__).resolve().relative_to(ROOT)),
            "measurement_script_sha256": _sha256(Path(__file__).resolve()),
            "uv_lock_sha256": _sha256(ROOT / "uv.lock"),
        },
        "runtime": {
            "python": sys.version.split()[0],
            "platform": platform.platform(),
            "machine": platform.machine(),
            "cpu_count_logical": os.cpu_count(),
            "memory_bytes": total_memory,
            "package_versions": _package_versions(),
        },
        "profiles": PROFILES,
        "measurements": measurements,
        "profile_cells": profile_cells,
        "guardrails": {
            "isolated_process_per_probe": True,
            "pythonhashseed": 0,
            "timeouts_seconds": TIMEOUTS,
            "s1_s2_full_flows_skipped_on_hardware_mismatch": True,
            "no_w1_capabilities_added": True,
        },
    }
    statuses = Counter(item["status"] for item in measurements)
    evidence["summary"] = {
        "measurement_statuses": dict(sorted(statuses.items())),
        "profile_cells_no_medible": sum(item["status"] == "no_medible" for item in profile_cells),
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(output)
    print(json.dumps(evidence["summary"], ensure_ascii=False, sort_keys=True))
    return 1 if statuses.get("error", 0) else 0


def main() -> int:
    """Ejecuta el orquestador público o un probe interno aislado."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--_probe", choices=PROBES, help=argparse.SUPPRESS)
    parser.add_argument("--_result", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args._probe:
        if args._result is None:
            parser.error("--_probe exige --_result")
        return _child(args._probe, args._result)
    if args.output is None:
        parser.error("--output es obligatorio")
    return _run_parent(args.output.resolve())


if __name__ == "__main__":
    raise SystemExit(main())
