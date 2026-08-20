"""Controles de componentes del runner H9R; no crean ni ejecutan unidades START/S0/S1/S2."""

from __future__ import annotations

import hashlib
import http.client
import json
import os
import socket
import socketserver
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from typing import Any, cast
from unittest.mock import MagicMock, patch

import pytest
from jsonschema import Draft202012Validator

from scripts.readiness_h9r.adapters import (
    _CANDIDATE_BOOTSTRAP,
    ADAPTER_CATALOG,
    ADAPTER_DESCRIPTOR_SCHEMA_VERSION,
    ADAPTER_REQUEST_SCHEMA_VERSION,
    ADAPTER_RESULT_SCHEMA_VERSION,
    AUTHORIZED_COUNTER_ADAPTER_IDS,
    CANDIDATE_SERVICE_READY_SCHEMA_VERSION,
    COUNTER_ADAPTER_SCHEMA_VERSION,
    COUNTER_RESULT_SCHEMA_VERSION,
    UI_CLIENT_REQUEST_SCHEMA_VERSION,
    _CandidateHttpProxy,
    _capture_candidate_process_census,
    _ConsumerOpenBroker,
    _file_identity,
    _open_readonly_no_follow,
    _prepare_sidecar,
    _read_canonical_control,
    _resume_suspended_before_deadline,
    _write_exclusive_regular_file,
    adapter_protocol_schemas,
    run_adapter_request,
    run_candidate_request,
    run_ui_client_request,
    validate_adapter_descriptor,
    validate_adapter_request,
    validate_candidate_http_exchange,
    validate_counter_adapter_descriptor,
    validate_native_pools_observation,
    validate_ui_client_request,
)
from scripts.readiness_h9r.artifacts import (
    OUTPUT_FORMAT_COUNTERS,
    canonical_tree_identity,
    derive_golden_observed_sha256,
)
from scripts.readiness_h9r.consumer import ConsumerBoundary, append_jsonl_event
from scripts.readiness_h9r.contracts import (
    ADAPTER_IDS,
    ContractError,
    canonical_json_bytes,
    canonical_json_sha256,
    sha256_file,
)
from scripts.readiness_h9r.windows_job import (
    WindowsJob,
    process_metrics,
    resume_suspended_process,
)


def _digest(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def test_bootstrap_candidato_compila_y_detecta_else_reindentado() -> None:
    compile(_CANDIDATE_BOOTSTRAP, "<candidate-bootstrap>", "exec")
    broken = _CANDIDATE_BOOTSTRAP.replace("\nelse:\n", "\n    else:\n", 1)
    with pytest.raises(SyntaxError):
        compile(broken, "<candidate-bootstrap-broken>", "exec")


def test_candidate_deadline_vencido_no_reanuda_child() -> None:
    with (
        patch("scripts.readiness_h9r.adapters.resume_suspended_process") as resume,
        pytest.raises(ContractError, match="deadline contractual"),
    ):
        _resume_suspended_before_deadline(
            321,
            object(),
            deadline=time.monotonic() - 1.0,
            context="antes de reanudar el child",
        )
    resume.assert_not_called()


def test_controles_y_material_protegido_rechazan_hardlink_antes_de_ejecutar(
    tmp_path: Path,
) -> None:
    control = tmp_path / "request.json"
    control.write_bytes(canonical_json_bytes({"value": 1}) + b"\n")
    control_alias = tmp_path / "request-alias.json"
    protected = tmp_path / "input.csv"
    protected.write_bytes(b"x\n1\n")
    protected_alias = tmp_path / "input-alias.csv"
    try:
        os.link(control, control_alias)
        os.link(protected, protected_alias)
    except OSError as exc:  # pragma: no cover - filesystem CI sin hardlinks.
        pytest.skip(f"filesystem sin hardlinks: {exc}")

    with pytest.raises(ContractError, match="hardlink"):
        _read_canonical_control(control_alias, context="adapter request")
    with pytest.raises(ContractError, match="hardlink"):
        _file_identity(
            {
                "path": str(protected_alias.resolve()),
                "logical_bytes": protected_alias.stat().st_size,
                "sha256": sha256_file(protected_alias),
            },
            context="protected input",
            verify_content=True,
        )


def _first_material_broker(
    path: Path, boundary: Any, *, expected_payload: bytes
) -> _ConsumerOpenBroker:
    protected = [
        {
            "logical_id": _digest("first-input"),
            "role": "input",
            "relative_name": path.name,
            "logical_bytes": len(expected_payload),
            "sha256": hashlib.sha256(expected_payload).hexdigest(),
        }
    ]
    material = [{**protected[0], "path": str(path.absolute())}]
    return _ConsumerOpenBroker(
        broker={
            "host": "127.0.0.1",
            "port": 1,
            "request_id": _digest("broker-request"),
            "nonce_commitment_sha256": _digest("broker-nonce"),
        },
        attempt_id=_digest("attempt"),
        protected=protected,
        protected_material=material,
        candidate_start_path=path.parent / "candidate-start.json",
        candidate_request_sha256=_digest("candidate-request"),
        boundary=boundary,
        audit_path=path.parent / "adapter-audit.jsonl",
    )


def test_primer_input_broker_rechaza_swap_antes_de_leer_o_aceptar(tmp_path: Path) -> None:
    first = tmp_path / "first.csv"
    first.write_bytes(b"original\n")
    replacement = tmp_path / "outside.csv"
    replacement.write_bytes(b"exterior\n")
    boundary = MagicMock()
    broker = _first_material_broker(first, boundary, expected_payload=b"original\n")
    real_open = _open_readonly_no_follow
    exterior_reads = 0

    class TrackingHandle:
        def __init__(self, inner: Any) -> None:
            self.inner = inner

        def __enter__(self) -> TrackingHandle:
            self.inner.__enter__()
            return self

        def __exit__(self, *args: Any) -> Any:
            return self.inner.__exit__(*args)

        def fileno(self) -> int:
            return cast(int, self.inner.fileno())

        def read(self) -> bytes:
            nonlocal exterior_reads
            exterior_reads += 1
            return cast(bytes, self.inner.read())

    def swap_then_open(path: Path) -> Any:
        os.replace(replacement, first)
        return TrackingHandle(real_open(path))

    with (
        patch(
            "scripts.readiness_h9r.adapters._open_readonly_no_follow",
            side_effect=swap_then_open,
        ),
        pytest.raises(ContractError, match="identidad cambió antes de leer"),
    ):
        broker._open_first_material(
            broker_request_sha256=_digest("wire"),
            candidate_process={"pid": 123, "creation_time_100ns": 456},
        )
    assert exterior_reads == 0
    boundary.first_open.assert_not_called()


def test_primer_input_broker_rechaza_symlink_sin_abrir_exterior(tmp_path: Path) -> None:
    outside = tmp_path / "outside.csv"
    outside.write_bytes(b"secreto\n")
    link = tmp_path / "first.csv"
    try:
        link.symlink_to(outside)
    except OSError as exc:
        if sys.platform != "win32":
            pytest.skip(f"host POSIX sin symlink de control: {exc}")
        outside_root = tmp_path / "outside-root"
        outside_root.mkdir()
        outside = outside_root / "first.csv"
        outside.write_bytes(b"secreto\n")
        junction = tmp_path / "first-junction"
        created = subprocess.run(
            ["cmd.exe", "/d", "/c", "mklink", "/J", str(junction), str(outside_root)],
            check=False,
            capture_output=True,
            text=True,
        )
        if created.returncode != 0:  # pragma: no cover - política Windows excepcional.
            pytest.skip(f"host sin symlink/junction de control: {created.stderr}")
        link = junction / "first.csv"
    boundary = MagicMock()
    broker = _first_material_broker(link, boundary, expected_payload=b"secreto\n")
    with (
        patch("scripts.readiness_h9r.adapters._open_readonly_no_follow") as opener,
        pytest.raises(ContractError, match="symlink/reparse"),
    ):
        broker._open_first_material(
            broker_request_sha256=_digest("wire"),
            candidate_process={"pid": 123, "creation_time_100ns": 456},
        )
    opener.assert_not_called()
    boundary.first_open.assert_not_called()


def test_primer_input_broker_rechaza_hardlink_sin_abrir_ni_aceptar(tmp_path: Path) -> None:
    outside = tmp_path / "outside.csv"
    outside.write_bytes(b"secreto\n")
    first = tmp_path / "first.csv"
    try:
        os.link(outside, first)
    except OSError as exc:  # pragma: no cover - filesystem CI sin hardlinks.
        pytest.skip(f"filesystem sin hardlinks: {exc}")
    boundary = MagicMock()
    broker = _first_material_broker(first, boundary, expected_payload=b"secreto\n")
    with (
        patch("scripts.readiness_h9r.adapters._open_readonly_no_follow") as opener,
        pytest.raises(ContractError, match="hardlink"),
    ):
        broker._open_first_material(
            broker_request_sha256=_digest("wire"),
            candidate_process={"pid": 123, "creation_time_100ns": 456},
        )
    opener.assert_not_called()
    boundary.first_open.assert_not_called()


def test_ui_sidecar_exclusivo_no_sigue_symlink_dangling(tmp_path: Path) -> None:
    outside = tmp_path / "outside-first-byte.json"
    sidecar = tmp_path / "ui-first-byte.jsonl"
    try:
        os.symlink(outside, sidecar)
    except OSError as exc:
        if sys.platform != "win32":
            pytest.skip(f"host POSIX sin symlink de control: {exc}")
        outside_root = tmp_path / "outside"
        outside_root.mkdir()
        junction = tmp_path / "telemetry-junction"
        created = subprocess.run(
            ["cmd.exe", "/d", "/c", "mklink", "/J", str(junction), str(outside_root)],
            check=False,
            capture_output=True,
            text=True,
        )
        if created.returncode != 0:  # pragma: no cover - política Windows excepcional.
            pytest.skip(f"host sin symlink/junction: {created.stderr}")
        outside = outside_root / "ui-first-byte.jsonl"
        sidecar = junction / "ui-first-byte.jsonl"
    with pytest.raises(ContractError, match=r"enlace dangling|symlink/reparse"):
        _write_exclusive_regular_file(sidecar, b"{}\n", context="ui first-byte")
    assert not outside.exists()


def test_append_y_precreate_sidecar_no_escriben_hardlink_ni_junction(
    tmp_path: Path,
) -> None:
    outside_file = tmp_path / "outside.jsonl"
    outside_file.write_bytes(b"original\n")
    hardlink = tmp_path / "hardlink.jsonl"
    try:
        os.link(outside_file, hardlink)
    except OSError as exc:  # pragma: no cover - filesystem CI sin hardlinks.
        pytest.skip(f"filesystem sin hardlinks: {exc}")
    with pytest.raises(ContractError, match="single-link"):
        append_jsonl_event(hardlink, {"event": "forbidden"})
    with pytest.raises(ContractError, match="seguro/vacío"):
        _prepare_sidecar(hardlink, context="audit")
    assert outside_file.read_bytes() == b"original\n"

    outside_root = tmp_path / "outside-root"
    outside_root.mkdir()
    junction = tmp_path / "junction"
    if sys.platform == "win32":
        created = subprocess.run(
            ["cmd.exe", "/d", "/c", "mklink", "/J", str(junction), str(outside_root)],
            check=False,
            capture_output=True,
            text=True,
        )
        if created.returncode != 0:  # pragma: no cover - política Windows excepcional.
            pytest.skip(f"host sin junction: {created.stderr}")
    else:
        try:
            junction.symlink_to(outside_root, target_is_directory=True)
        except (NotImplementedError, OSError) as exc:  # pragma: no cover - host POSIX excepcional.
            pytest.skip(f"host POSIX sin symlink de directorio: {exc}")
    outside_target = outside_root / "escaped.jsonl"
    try:
        with pytest.raises(ContractError, match="directorio/ancestro no es plano"):
            append_jsonl_event(junction / "escaped.jsonl", {"event": "forbidden"})
        assert not outside_target.exists()
    finally:
        if junction.is_symlink():
            junction.unlink()
        else:
            junction.rmdir()


def _native_process_payload(*, execution_sha: str, pid: int, creation: int) -> dict[str, Any]:
    return {
        "schema_version": "nikodym.readiness.h9r.native-pools-process-observation.v1",
        "candidate_execution_request_sha256": execution_sha,
        "pid": pid,
        "creation_time_100ns": creation,
        "environment": {
            name: "4"
            for name in (
                "OMP_NUM_THREADS",
                "MKL_NUM_THREADS",
                "OPENBLAS_NUM_THREADS",
                "NUMEXPR_NUM_THREADS",
                "BLIS_NUM_THREADS",
                "VECLIB_MAXIMUM_THREADS",
            )
        },
        "libraries": [],
        "process_thread_count": 1,
    }


def test_native_pools_multiproceso_reconcilia_reporters_con_censo_kernel(
    tmp_path: Path,
) -> None:
    execution_sha = _digest("candidate-execution")
    native_root = tmp_path / "native-pools"
    native_root.mkdir()
    census = [
        {"pid": 101, "creation_time_100ns": 1_001},
        {"pid": 202, "creation_time_100ns": 2_002},
    ]
    processes: list[dict[str, Any]] = []
    for identity in census:
        pid = identity["pid"]
        creation = identity["creation_time_100ns"]
        source = native_root / f"process-{pid}-{creation}.json"
        payload = _native_process_payload(execution_sha=execution_sha, pid=pid, creation=creation)
        source.write_bytes(canonical_json_bytes(payload) + b"\n")
        processes.append(
            {
                **{
                    name: payload[name]
                    for name in (
                        "pid",
                        "creation_time_100ns",
                        "environment",
                        "libraries",
                        "process_thread_count",
                    )
                },
                "source": _file_entry(source),
            }
        )
    aggregate = {
        "schema_version": "nikodym.readiness.h9r.native-pools-observation.v2",
        "candidate_execution_request_sha256": execution_sha,
        "total_processes": 2,
        "processes": processes,
    }
    aggregate_path = tmp_path / "native-pools-observation.json"
    aggregate_path.write_bytes(canonical_json_bytes(aggregate) + b"\n")

    observed = validate_native_pools_observation(
        aggregate_path,
        candidate_execution_request_sha256=execution_sha,
        native_pools_root=native_root,
        expected_process_census=census,
    )
    assert observed["total_processes"] == 2
    assert all(process["libraries"] == [] for process in observed["processes"])

    (native_root / "process-202-2002.json").unlink()
    with pytest.raises(ContractError, match="ausente"):
        validate_native_pools_observation(
            aggregate_path,
            candidate_execution_request_sha256=execution_sha,
            native_pools_root=native_root,
            expected_process_census=census,
        )


def test_censo_candidate_falla_si_completion_port_no_captura_descendiente() -> None:
    class _FakeProcess:
        pid = 101

        @staticmethod
        def wait(*, timeout: float) -> int:
            assert timeout > 0
            return 0

    class _FakeJob:
        JOB_OBJECT_MSG_NEW_PROCESS = 6
        api = object()

        @staticmethod
        def completion_messages(*, wait_timeout_ms: int = 0) -> list[dict[str, int]]:
            assert wait_timeout_ms >= 0
            return [
                {"message_id": 6, "message_specific_value": 101},
                {"message_id": 6, "message_specific_value": 202},
            ]

        @staticmethod
        def process_ids() -> list[int]:
            return []

        @staticmethod
        def accounting() -> dict[str, Any]:
            return {"active_processes": 0, "total_processes": 2}

        @staticmethod
        def terminate(_code: int) -> None:
            raise AssertionError("no debe terminar antes del deadline")

    def metrics(pid: int, _api: object) -> dict[str, int]:
        if pid == 202:
            raise OSError("descendiente ya no observable")
        return {"pid": pid, "creation_time_100ns": 1_001}

    with (
        patch("scripts.readiness_h9r.adapters.process_metrics", side_effect=metrics),
        pytest.raises(ContractError, match="completion port no acreditó"),
    ):
        _capture_candidate_process_census(
            cast(Any, _FakeJob()),
            cast(Any, _FakeProcess()),
            root_process={"pid": 101, "creation_time_100ns": 1_001},
            workload_deadline=time.monotonic() + 5.0,
        )


@pytest.mark.skipif(  # type: ignore[untyped-decorator]
    sys.platform != "win32", reason="Job Object sólo existe en Windows"
)
def test_censo_candidate_captura_raiz_y_descendiente_reales() -> None:
    job = WindowsJob(memory_bytes=256 * 1024 * 1024)
    process: subprocess.Popen[bytes] | None = None
    try:
        child_code = "import time; time.sleep(0.35)"
        root_code = (
            "import subprocess,sys,time; "
            f"p=subprocess.Popen([sys.executable,'-c',{child_code!r}]); "
            "time.sleep(0.15); p.wait()"
        )
        process = subprocess.Popen(
            [sys.executable, "-I", "-B", "-S", "-c", root_code],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
            creationflags=0x00000004,
        )
        job.assign(process.pid)
        root_metrics = process_metrics(process.pid, job.api)
        root = {
            "pid": process.pid,
            "creation_time_100ns": root_metrics["creation_time_100ns"],
        }
        resume_suspended_process(process.pid, job.api)
        returncode, accounting, census, _tree_empty_ns = _capture_candidate_process_census(
            job,
            process,
            root_process=root,
            workload_deadline=time.monotonic() + 10.0,
        )
        assert returncode == 0
        # El redirector de un venv Windows puede añadir un proceso por intérprete;
        # el censo debe conservarlos, no colapsarlos al árbol lógico raíz+hijo.
        assert accounting["total_processes"] >= 2
        assert census["total_processes"] == accounting["total_processes"]
        assert root in census["processes"]
    finally:
        if process is not None and process.poll() is None:
            job.terminate(0xE0000004)
            process.wait(timeout=10)
        job.close()


def _run_ui_authorized_for_test(request_path: Path, request: dict[str, Any]) -> int:
    """Ejercita sólo el cliente sintético; los overrides no existen como opción productiva."""
    with (
        patch(
            "scripts.readiness_h9r.supervisor.consume_internal_authorization_gate",
            return_value={},
        ),
        patch("scripts.readiness_h9r.adapters._validate_pycache_isolation"),
        patch("scripts.readiness_h9r.supervisor.QUALIFYING_BOUNDARY_ADAPTERS_AVAILABLE", True),
        patch("scripts.readiness_h9r.supervisor.TRUSTED_HARNESS_RUNTIME_SNAPSHOT_AVAILABLE", True),
        patch("scripts.readiness_h9r.supervisor.MULTIPROCESS_NATIVE_POOL_OBSERVER_AVAILABLE", True),
        patch(
            "scripts.readiness_h9r.supervisor.CANDIDATE_EXECUTION_MATERIAL_LEASE_AVAILABLE", True
        ),
        patch("scripts.readiness_h9r.supervisor.CANDIDATE_OUTPUT_OS_ISOLATION_AVAILABLE", True),
        patch("scripts.readiness_h9r.supervisor.consume_launch_capability"),
    ):
        return run_ui_client_request(
            request_path,
            canonical_json_sha256(request),
            authorization_gate_path=request_path.parent / "test-gate.json",
            trusted_authority_public_key_path=request_path.parent / "test-key.pem",
            workdir=request_path.parent,
            capability_commitment_sha256=_digest("test-ui-capability"),
        )


def _ui_request(tmp_path: Path, *, attempt: str, host: str, port: int, path: str) -> dict[str, Any]:
    body_path = tmp_path / f"{attempt}-body.bin"
    body_path.write_bytes(b"fixture-body")
    body = _file_entry(body_path)
    request_id = canonical_json_sha256(
        {
            "attempt_id": _digest(attempt),
            "method": "POST",
            "host": host,
            "port": port,
            "path": path,
            "body_sha256": body["sha256"],
            "body_bytes": body["logical_bytes"],
        }
    )
    return {
        "schema_version": UI_CLIENT_REQUEST_SCHEMA_VERSION,
        "attempt_id": _digest(attempt),
        "method": "POST",
        "loopback_host": host,
        "port": port,
        "path": path,
        "timeout_seconds": 5.0,
        "expected_status": 200,
        "body": body,
        "request_id": request_id,
        "first_byte_path": str((tmp_path / f"{attempt}-first-byte.jsonl").resolve()),
    }


def _file_entry(path: Path) -> dict[str, Any]:
    return {
        "path": str(path.resolve()),
        "logical_bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def _descriptor(*, script: Path, candidate_root: Path, bindings: dict[str, str]) -> dict[str, Any]:
    unit = {
        "candidate_manifest_sha256": bindings["candidate_manifest_sha256"],
        "flow_id": "F-LGD-BASE",
        "flow_step": "run",
        "fixture_manifest_sha256": bindings["fixture_manifest_sha256"],
        "config_hash": bindings["config_hash"],
        "geometry_id": "G-",
        "cap_id": "C4",
        "attempt_ordinal": 1,
    }
    return {
        "schema_version": ADAPTER_DESCRIPTOR_SCHEMA_VERSION,
        "attempt_id": canonical_json_sha256(unit),
        "unit": unit,
        "adapter_id": "nikodym.h9r.lgd_base.run.v1",
        "flow_id": "F-LGD-BASE",
        "flow_step": "run",
        "boundary_kind": "first_open",
        "bindings": bindings,
        "input_contract": {
            "protocol_version": "nikodym.readiness.h9r.consumer-open.v1",
            "protected": [
                {
                    "logical_id": canonical_json_sha256(
                        {
                            "role": "input",
                            "relative_name": "rows.json",
                            "logical_bytes": 2,
                            "sha256": _digest("rows"),
                        }
                    ),
                    "role": "input",
                    "relative_name": "rows.json",
                    "logical_bytes": 2,
                    "sha256": _digest("rows"),
                }
            ],
            "max_open_requests": 1,
        },
        "implementation": {
            "kind": "candidate_brokered_script",
            "script": {
                "relative_path": script.relative_to(candidate_root).as_posix(),
                "bytes": script.stat().st_size,
                "sha256": sha256_file(script),
            },
            "argv_template": [
                "${BROKERED_INPUTS_JSON}",
                "${STAGING_ROOT}",
                "${ADAPTER_RESULT}",
            ],
            "isolation_flags": ["-I", "-B", "-S"],
        },
        "expected": {
            "identities": ["lgd_by_operation", "provenance"],
            "counts": {"lgd_by_operation": 3, "provenance": 1},
            "golden_sha256": _digest("golden"),
        },
    }


def _golden_for_json_outputs(
    definitions: list[tuple[str, str, bytes, int]],
) -> str:
    artifacts: list[dict[str, Any]] = []
    for ordinal, (relative_path, identity, payload, records) in enumerate(definitions):
        digest = hashlib.sha256(payload).hexdigest()
        artifacts.append(
            {
                "relative_path": relative_path,
                "identity": identity,
                "ordinal": ordinal,
                "format": "json",
                "record_count": records,
                "logical_bytes": len(payload),
                "sha256": digest,
                "count_evidence": {
                    "mode": "derived",
                    "counter_id": OUTPUT_FORMAT_COUNTERS["json"],
                    "records": records,
                    "output_sha256": digest,
                    "sidecar": None,
                },
            }
        )
    return str(derive_golden_observed_sha256(artifacts))


def _component_request(tmp_path: Path) -> tuple[dict[str, Any], Path]:
    fixture = tmp_path / "fixture"
    inputs = fixture / "inputs"
    bundle = fixture / "bundle"
    inputs.mkdir(parents=True)
    bundle.mkdir()
    input_path = inputs / "rows.json"
    input_path.write_bytes(b"[1,2,3]\n")
    config_path = fixture / "config.json"
    config_path.write_bytes(b"{}\n")

    candidate = tmp_path / "candidate"
    candidate.mkdir()
    script = candidate / "adapter.py"
    script.write_text(
        """from __future__ import annotations
import json
import os
import sys
from pathlib import Path

inputs = Path(sys.argv[1])
staging = Path(sys.argv[2])
result = Path(sys.argv[3])
for forbidden in (
    "NIKODYM_H9R_OUTPUT_ROOT",
    "NIKODYM_H9R_BOUNDARY_JSONL",
    "NIKODYM_H9R_FILESYSTEM_JSONL",
    "NIKODYM_H9R_NATIVE_POOLS_JSONL",
):
    assert forbidden not in os.environ
json.loads(next(inputs.glob("*.json")).read_text(encoding="utf-8"))
first = b"[1,2,3]"
second = b"[4]"
(staging / "lgd.json").write_bytes(first)
(staging / "provenance.json").write_bytes(second)
result.write_bytes((json.dumps({
    "schema_version": "nikodym.readiness.h9r.adapter-result.v1",
    "attempt_id": "ATTEMPT_ID",
    "outputs": [
        {
            "identity": "lgd_by_operation",
            "source_relative_path": "lgd.json",
            "output_relative_path": "lgd.json",
            "format": "json"
        },
        {
            "identity": "provenance",
            "source_relative_path": "provenance.json",
            "output_relative_path": "provenance.json",
            "format": "json"
        }
    ]
}, sort_keys=True, separators=(",", ":")) + "\\n").encode("utf-8"))
""",
        encoding="utf-8",
        newline="\n",
    )
    bindings = {
        "config_hash": _digest("config"),
        "candidate_manifest_sha256": _digest("candidate"),
        "fixture_manifest_sha256": _digest("fixture"),
        "tooling_manifest_sha256": _digest("tooling"),
    }
    unit = {
        "candidate_manifest_sha256": bindings["candidate_manifest_sha256"],
        "flow_id": "F-LGD-BASE",
        "flow_step": "run",
        "fixture_manifest_sha256": bindings["fixture_manifest_sha256"],
        "config_hash": bindings["config_hash"],
        "geometry_id": "G-",
        "cap_id": "C4",
        "attempt_ordinal": 1,
    }
    attempt_id = canonical_json_sha256(unit)
    descriptor = _descriptor(script=script, candidate_root=candidate, bindings=bindings)
    descriptor["attempt_id"] = attempt_id
    descriptor["unit"] = unit
    script.write_text(
        script.read_text(encoding="utf-8").replace("ATTEMPT_ID", attempt_id),
        encoding="utf-8",
        newline="\n",
    )
    descriptor["implementation"]["script"]["bytes"] = script.stat().st_size
    descriptor["implementation"]["script"]["sha256"] = sha256_file(script)
    work = tmp_path / "work"
    telemetry = work / "telemetry"
    staging = work / "scratch" / "consumer-staging"
    outputs = work / "outputs"
    first = b"[1,2,3]"
    second = b"[4]"
    request = {
        "schema_version": ADAPTER_REQUEST_SCHEMA_VERSION,
        "attempt_id": attempt_id,
        "flow_id": "F-LGD-BASE",
        "flow_step": "run",
        "adapter_id": "nikodym.h9r.lgd_base.run.v1",
        "bindings": bindings,
        "descriptor": {},
        "runtime": {
            "candidate_root": str(candidate.resolve()),
            "candidate_tree_sha256": canonical_tree_identity(candidate)["sha256"],
            "python_executable": _file_entry(Path(sys.executable)),
            "isolation_flags": ["-I", "-B", "-S"],
        },
        "paths": {
            "fixture_root": str(fixture.resolve()),
            "inputs_root": str(inputs.resolve()),
            "inputs": [_file_entry(input_path)],
            "bundle_root": str(bundle.resolve()),
            "bundle": None,
            "config": _file_entry(config_path),
            "staging": str(staging.resolve()),
            "adapter_result": str((staging / "adapter-result.json").resolve()),
            "outputs": str(outputs.resolve()),
            "boundary": str((telemetry / "boundary.jsonl").resolve()),
            "filesystem_events": str((telemetry / "filesystem.jsonl").resolve()),
            "native_pools": str((telemetry / "native-pools.jsonl").resolve()),
            "audit": str((telemetry / "adapter-audit.jsonl").resolve()),
            "ui_first_byte": str((telemetry / "ui-first-byte.jsonl").resolve()),
        },
        "ui_ingress": None,
        "expected": {
            "identities": ["lgd_by_operation", "provenance"],
            "counts": {"lgd_by_operation": 3, "provenance": 1},
            "golden_observed_sha256": _golden_for_json_outputs(
                [
                    ("lgd.json", "lgd_by_operation", first, 3),
                    ("provenance.json", "provenance", second, 1),
                ]
            ),
        },
        "counter_adapter": None,
    }
    descriptor_expected = cast(dict[str, Any], descriptor["expected"])
    request_expected = cast(dict[str, Any], request["expected"])
    descriptor_expected["golden_sha256"] = request_expected["golden_observed_sha256"]
    descriptor_path = tmp_path / "adapter-descriptor.json"
    descriptor_path.write_bytes(canonical_json_bytes(descriptor) + b"\n")
    request["descriptor"] = _file_entry(descriptor_path)
    return request, work


def test_catalogo_estatico_liga_exactamente_las_quince_fronteras() -> None:
    assert len(ADAPTER_CATALOG) == 15
    assert {(item.flow_id, item.flow_step): item.adapter_id for item in ADAPTER_CATALOG} == dict(
        ADAPTER_IDS
    )
    assert sum(item.boundary_kind == "first_byte" for item in ADAPTER_CATALOG) == 1


def test_descriptor_prohibe_modulo_comando_y_escape(tmp_path: Path) -> None:
    candidate = tmp_path / "candidate"
    candidate.mkdir()
    script = candidate / "adapter.py"
    script.write_bytes(b"pass\n")
    bindings = {
        "config_hash": _digest("config"),
        "candidate_manifest_sha256": _digest("candidate"),
        "fixture_manifest_sha256": _digest("fixture"),
        "tooling_manifest_sha256": _digest("tooling"),
    }
    descriptor = _descriptor(script=script, candidate_root=candidate, bindings=bindings)
    descriptor["implementation"] = {
        "kind": "candidate_python_module",
        "script": descriptor["implementation"]["script"],
        "argv_template": descriptor["implementation"]["argv_template"],
        "isolation_flags": ["-I", "-B", "-S"],
    }
    with pytest.raises(ContractError, match="candidate_brokered_script"):
        validate_adapter_descriptor(
            descriptor,
            candidate_root=candidate,
            expected_flow_id="F-LGD-BASE",
            expected_flow_step="run",
            expected_bindings=bindings,
        )

    descriptor = _descriptor(script=script, candidate_root=candidate, bindings=bindings)
    descriptor["implementation"]["script"]["relative_path"] = "../adapter.py"
    with pytest.raises(ContractError, match="ruta relativa"):
        validate_adapter_descriptor(
            descriptor,
            candidate_root=candidate,
            expected_flow_id="F-LGD-BASE",
            expected_flow_step="run",
            expected_bindings=bindings,
        )


def test_counter_binario_tiene_interfaz_cerrada_pero_registro_vacio(tmp_path: Path) -> None:
    candidate = tmp_path / "candidate"
    candidate.mkdir()
    script = candidate / "counter.py"
    script.write_bytes(b"pass\n")
    bindings = {
        "config_hash": _digest("config"),
        "candidate_manifest_sha256": _digest("candidate"),
        "fixture_manifest_sha256": _digest("fixture"),
        "tooling_manifest_sha256": _digest("tooling"),
    }
    descriptor = {
        "schema_version": COUNTER_ADAPTER_SCHEMA_VERSION,
        "counter_id": "nikodym.h9r.counter.binary.example.v1",
        "format": "bin",
        "bindings": bindings,
        "implementation": {
            "kind": "signed_python_script",
            "script": {
                "relative_path": "counter.py",
                "bytes": script.stat().st_size,
                "sha256": sha256_file(script),
            },
        },
        "result_contract": {
            "schema_version": COUNTER_RESULT_SCHEMA_VERSION,
            "required_fields": ["schema_version", "counter_id", "output_sha256", "records"],
        },
    }
    assert frozenset() == AUTHORIZED_COUNTER_ADAPTER_IDS
    with pytest.raises(ContractError, match="no existe un counter adapter"):
        validate_counter_adapter_descriptor(
            descriptor, candidate_root=candidate, expected_bindings=bindings
        )


def test_runner_productivo_falla_cerrado_sin_adapter_frontera_calificable(
    tmp_path: Path,
) -> None:
    request_path = tmp_path / "no-debe-leerse.json"
    with (
        patch("scripts.readiness_h9r.adapters._read_canonical_control") as reader,
        patch("scripts.readiness_h9r.supervisor.consume_launch_capability") as capability,
        pytest.raises(ContractError, match="blockers="),
    ):
        run_adapter_request(
            request_path,
            _digest("request"),
            authorization_gate_path=tmp_path / "gate.json",
            trusted_authority_public_key_path=tmp_path / "key.pem",
            workdir=tmp_path,
            capability_commitment_sha256=_digest("capability"),
        )
    reader.assert_not_called()
    capability.assert_not_called()


@pytest.mark.parametrize(
    "entrypoint",
    [run_adapter_request, run_candidate_request, run_ui_client_request],
)
def test_roles_internos_no_omiten_nuevos_blockers_aunque_parcheen_flags_antiguos(
    tmp_path: Path, entrypoint: Any
) -> None:
    request_path = tmp_path / "no-debe-leerse.json"
    with (
        patch("scripts.readiness_h9r.supervisor.QUALIFYING_BOUNDARY_ADAPTERS_AVAILABLE", True),
        patch("scripts.readiness_h9r.supervisor.TRUSTED_HARNESS_RUNTIME_SNAPSHOT_AVAILABLE", True),
        patch("scripts.readiness_h9r.supervisor.MULTIPROCESS_NATIVE_POOL_OBSERVER_AVAILABLE", True),
        patch("scripts.readiness_h9r.adapters._read_canonical_control") as reader,
        pytest.raises(
            ContractError,
            match=r"candidate_execution_material_lease_unimplemented",
        ),
    ):
        entrypoint(
            request_path,
            _digest("request"),
            authorization_gate_path=tmp_path / "gate.json",
            trusted_authority_public_key_path=tmp_path / "key.pem",
            workdir=tmp_path,
            capability_commitment_sha256=_digest("capability"),
        )
    reader.assert_not_called()


def test_blocker_output_impide_create_delete_manifest_por_candidate(tmp_path: Path) -> None:
    output_root = tmp_path / "outputs"
    attack_executed = False

    def create_delete_manifest(*_args: Any, **_kwargs: Any) -> Any:
        nonlocal attack_executed
        attack_executed = True
        output_root.mkdir()
        manifest = output_root / "manifest.json"
        manifest.write_bytes(b'{"candidate":true}\n')
        manifest.unlink()
        output_root.rmdir()
        raise AssertionError("el runner bloqueado no puede ceder el publisher al candidate")

    with (
        patch("scripts.readiness_h9r.supervisor.QUALIFYING_BOUNDARY_ADAPTERS_AVAILABLE", True),
        patch("scripts.readiness_h9r.supervisor.TRUSTED_HARNESS_RUNTIME_SNAPSHOT_AVAILABLE", True),
        patch("scripts.readiness_h9r.supervisor.MULTIPROCESS_NATIVE_POOL_OBSERVER_AVAILABLE", True),
        patch(
            "scripts.readiness_h9r.supervisor.CANDIDATE_EXECUTION_MATERIAL_LEASE_AVAILABLE", True
        ),
        patch("scripts.readiness_h9r.supervisor.CANDIDATE_OUTPUT_OS_ISOLATION_AVAILABLE", False),
        patch("scripts.readiness_h9r.adapters._read_canonical_control") as reader,
        patch(
            "scripts.readiness_h9r.adapters.subprocess.run",
            side_effect=create_delete_manifest,
        ) as candidate_runner,
        pytest.raises(ContractError, match="candidate_output_os_isolation_unimplemented"),
    ):
        run_adapter_request(
            tmp_path / "no-debe-leerse.json",
            _digest("request"),
            authorization_gate_path=tmp_path / "gate.json",
            trusted_authority_public_key_path=tmp_path / "key.pem",
            workdir=tmp_path,
            capability_commitment_sha256=_digest("capability"),
        )
    assert attack_executed is False
    assert not output_root.exists()
    reader.assert_not_called()
    candidate_runner.assert_not_called()


def test_schemas_auxiliares_son_draft_2020_12_y_rechazan_extra() -> None:
    schemas = adapter_protocol_schemas()
    assert set(schemas) == {
        "adapter_descriptor",
        "candidate_launch_request",
        "candidate_execution_request",
        "candidate_start",
        "native_pools_process_observation",
        "native_pools_observation",
        "candidate_service_ready",
        "candidate_http_exchange",
        "candidate_result",
        "adapter_request",
        "adapter_result",
        "counter_adapter",
        "ui_client_request",
    }
    for schema in schemas.values():
        Draft202012Validator.check_schema(schema)
        assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
        assert schema["type"] == "object"
        assert schema["additionalProperties"] is False
    stale_result = {
        "schema_version": ADAPTER_RESULT_SCHEMA_VERSION,
        "attempt_id": _digest("attempt"),
        "outputs": [],
    }
    arbitrary_command = {
        **stale_result,
        "command": ["python", "-m", "arbitrary"],
    }
    validator = Draft202012Validator(schemas["adapter_result"])
    assert list(validator.iter_errors(stale_result))
    assert list(validator.iter_errors(arbitrary_command))


def test_ui_client_harness_owned_emite_solo_despues_del_primer_byte(
    tmp_path: Path,
) -> None:
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            if self.path != "/health":
                self.send_error(404)
                return
            self.rfile.read(int(self.headers["Content-Length"]))
            self.send_response(200)
            self.send_header("Content-Length", "2")
            self.end_headers()
            self.wfile.write(b"OK")

        def log_message(self, format: str, *args: Any) -> None:
            del format, args

    class Server(socketserver.TCPServer):
        allow_reuse_address = True

    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = int(reservation.getsockname()[1])

    def delayed_server() -> None:
        time.sleep(0.1)
        with Server(("127.0.0.1", port), Handler) as server:
            server.handle_request()

    thread = threading.Thread(target=delayed_server, daemon=True)
    thread.start()
    request = _ui_request(
        tmp_path, attempt="ui-attempt", host="127.0.0.1", port=port, path="/health"
    )
    first_byte_path = Path(cast(str, request["first_byte_path"]))
    request_path = tmp_path / "ui-client-request.json"
    validate_ui_client_request(request)
    request_path.write_bytes(canonical_json_bytes(request) + b"\n")
    assert _run_ui_authorized_for_test(request_path, request) == 0
    thread.join(timeout=5)
    assert not thread.is_alive()
    event = json.loads(first_byte_path.read_text(encoding="utf-8"))
    assert event["event"] == "first_byte"
    assert event["attempt_id"] == request["attempt_id"]
    assert event["request_id"] == request["request_id"]


@pytest.mark.skipif(  # type: ignore[untyped-decorator]
    sys.platform != "win32", reason="owner PID del listener exige Windows"
)
def test_proxy_ui_reenvia_servicio_real_y_persiste_exchange_durable(
    tmp_path: Path,
) -> None:
    def free_port() -> int:
        with socket.socket() as reservation:
            reservation.bind(("127.0.0.1", 0))
            return cast(int, reservation.getsockname()[1])

    attempt = _digest("ui-attempt-proxy")
    candidate_request_sha = _digest("candidate-request-proxy")
    service_descriptor_sha = _digest("service-descriptor-proxy")
    endpoint_sha = _digest("endpoint-proxy")
    request_id = _digest("request-id-proxy")
    request_body = b"fixture-ui-byte-exacto"
    response_body = b"<html><body>pagina-real</body></html>"
    body_path = tmp_path / "request.bin"
    body_path.write_bytes(request_body)
    backend_port = free_port()
    front_port = free_port()
    candidate_process = {
        "pid": os.getpid(),
        "creation_time_100ns": process_metrics(os.getpid())["creation_time_100ns"],
    }
    first_page = {
        "identity": "first_verifiable_page",
        "relative_path": "first-page.html",
        "logical_bytes": len(response_body),
        "sha256": hashlib.sha256(response_body).hexdigest(),
    }
    service = {
        "host": "127.0.0.1",
        "port": backend_port,
        "ready_timeout_seconds": 5.0,
        "first_page_oracle": {
            "kind": "exact_http_response_v1",
            "expected_status": 200,
            "content_type": "text/html",
            "response_body_bytes": len(response_body),
            "response_body_sha256": hashlib.sha256(response_body).hexdigest(),
            "first_verifiable_page": first_page,
        },
    }
    ingress = {
        "loopback_host": "127.0.0.1",
        "port": front_port,
        "path": "/render",
        "timeout_seconds": 5.0,
        "expected_status": 200,
        "request_id": request_id,
        "body": _file_entry(body_path),
        "service_descriptor_sha256": service_descriptor_sha,
        "endpoint_sha256": endpoint_sha,
    }
    start_path = tmp_path / "candidate-start.json"
    start_path.write_bytes(
        canonical_json_bytes(
            {
                "attempt_id": attempt,
                "candidate_request_sha256": candidate_request_sha,
                "candidate_process": candidate_process,
            }
        )
        + b"\n"
    )
    ready_path = tmp_path / "service-ready.json"
    ready_path.write_bytes(
        canonical_json_bytes(
            {
                "schema_version": CANDIDATE_SERVICE_READY_SCHEMA_VERSION,
                "attempt_id": attempt,
                "candidate_request_sha256": candidate_request_sha,
                "candidate_process": candidate_process,
                "host": "127.0.0.1",
                "port": backend_port,
                "ready_monotonic_ns": time.monotonic_ns(),
            }
        )
        + b"\n"
    )
    backend_ready = threading.Event()
    backend_error: list[BaseException] = []

    def backend() -> None:
        try:
            with socket.socket() as server:
                server.bind(("127.0.0.1", backend_port))
                server.listen(1)
                server.settimeout(5.0)
                backend_ready.set()
                connection, _ = server.accept()
                with connection:
                    raw = b""
                    while b"\r\n\r\n" not in raw:
                        raw += connection.recv(64 * 1024)
                    headers, body = raw.split(b"\r\n\r\n", 1)
                    length = int(
                        next(
                            line.split(b":", 1)[1]
                            for line in headers.split(b"\r\n")
                            if line.lower().startswith(b"content-length:")
                        )
                    )
                    while len(body) < length:
                        body += connection.recv(length - len(body))
                    assert body == request_body
                    time.sleep(0.1)
                    connection.sendall(
                        b"HTTP/1.1 200 OK\r\n"
                        b"Content-Type: text/html\r\n"
                        + f"Content-Length: {len(response_body)}\r\n".encode("ascii")
                        + b"Connection: close\r\n\r\n"
                        + response_body
                    )
        except BaseException as exc:  # pragma: no cover - se reeleva en hilo principal.
            backend_error.append(exc)
            backend_ready.set()

    backend_thread = threading.Thread(target=backend, daemon=True)
    backend_thread.start()
    assert backend_ready.wait(2.0)
    boundary = ConsumerBoundary(tmp_path / "boundary.jsonl", tmp_path / "filesystem.jsonl")
    exchange_path = tmp_path / "candidate-http-exchange.json"
    proxy = _CandidateHttpProxy(
        ingress=ingress,
        service=service,
        service_ready_path=ready_path,
        http_exchange_path=exchange_path,
        candidate_start_path=start_path,
        candidate_request_sha256=candidate_request_sha,
        attempt_id=attempt,
        boundary=boundary,
    )
    proxy.start()
    connection = http.client.HTTPConnection("127.0.0.1", front_port, timeout=5.0)
    try:
        connection.request(
            "POST",
            "/render",
            body=request_body,
            headers={
                "Content-Length": str(len(request_body)),
                "X-Nikodym-Request-Id": request_id,
            },
        )
        try:
            response = connection.getresponse()
        except http.client.RemoteDisconnected:
            if backend_error:
                raise backend_error[0] from None
            proxy.finish()
            raise
        assert response.status == 200
        assert response.read() == response_body
        exchange_identity = proxy.finish()
    finally:
        connection.close()
        proxy.close()
        backend_thread.join(timeout=5.0)
    assert not backend_error
    exchange = validate_candidate_http_exchange(
        Path(cast(str, exchange_identity["path"])),
        attempt_id=attempt,
        candidate_request_sha256=candidate_request_sha,
        expected_ingress=ingress,
        expected_service=service,
        expected_candidate_process=candidate_process,
        expected_service_ready=_file_entry(ready_path),
    )
    assert exchange["response"]["body_sha256"] == hashlib.sha256(response_body).hexdigest()
    assert (
        exchange["request"]["first_byte_to_service_monotonic_ns"]
        < exchange["response"]["first_byte_from_service_monotonic_ns"]
    )


def test_ui_client_rechaza_host_no_loopback_sin_crear_sidecar(tmp_path: Path) -> None:
    request = _ui_request(tmp_path, attempt="ui-invalid", host="192.0.2.1", port=8080, path="/")
    request_path = tmp_path / "ui-client-request.json"
    request_path.write_bytes(canonical_json_bytes(request) + b"\n")
    with pytest.raises(ContractError, match="loopback"):
        _run_ui_authorized_for_test(request_path, request)
    assert not Path(cast(str, request["first_byte_path"])).exists()


def test_ui_client_no_sigue_redirect_ni_afirma_first_byte(tmp_path: Path) -> None:
    class RedirectHandler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            self.rfile.read(int(self.headers["Content-Length"]))
            self.send_response(302)
            self.send_header("Location", "http://example.invalid/")
            self.send_header("Content-Length", "1")
            self.end_headers()
            self.wfile.write(b"x")

        def log_message(self, format: str, *args: Any) -> None:
            del format, args

    class Server(socketserver.TCPServer):
        allow_reuse_address = True

    with Server(("127.0.0.1", 0), RedirectHandler) as server:
        port = int(server.server_address[1])
        thread = threading.Thread(target=server.handle_request, daemon=True)
        thread.start()
        request = _ui_request(
            tmp_path,
            attempt="ui-redirect",
            host="127.0.0.1",
            port=port,
            path="/redirect",
        )
        first_byte = Path(cast(str, request["first_byte_path"]))
        request_path = tmp_path / "redirect-request.json"
        request_path.write_bytes(canonical_json_bytes(request) + b"\n")
        with pytest.raises(ContractError, match="status 302"):
            _run_ui_authorized_for_test(request_path, request)
        thread.join(timeout=5)
    assert not first_byte.exists()


def test_api_publica_solo_funcion_de_request_no_comando(tmp_path: Path) -> None:
    # Control estructural: incluso un request bien formado no puede incluir candidate_command.
    request, _ = _component_request(tmp_path)
    request["candidate_command"] = [sys.executable, "-m", "cualquier.modulo"]
    with pytest.raises(ContractError, match=r"extra=.*candidate_command"):
        validate_adapter_request(request)
    assert callable(run_adapter_request)


def test_no_existe_executor_importable_sin_gate() -> None:
    import scripts.readiness_h9r.adapters as adapters

    assert not hasattr(adapters, "_run_adapter_request_unchecked")
    assert not hasattr(adapters, "_run_ui_client_request_unchecked")
    assert not hasattr(adapters, "_execute_signed_script")
