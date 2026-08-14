"""Probes internos del arnés; nunca representan workloads ni unidades START."""

from __future__ import annotations

import argparse
import ctypes
import os
import threading
import time
from pathlib import Path

from .consumer import ConsumerBoundary, ConsumerPublisher, record_native_pools
from .contracts import canonical_json_sha256, sha256_file
from .telemetry import POOL_ENVIRONMENT_KEYS
from .windows_job import current_process_affinity, try_expand_current_process_affinity


def _paths_from_environment() -> tuple[Path, Path, Path, Path]:
    boundary = os.environ.get("NIKODYM_H9R_BOUNDARY_JSONL")
    filesystem = os.environ.get("NIKODYM_H9R_FILESYSTEM_JSONL")
    outputs = os.environ.get("NIKODYM_H9R_OUTPUT_ROOT")
    pools = os.environ.get("NIKODYM_H9R_NATIVE_POOLS_JSONL")
    if not boundary or not filesystem or not outputs or not pools:
        raise RuntimeError("probe sin paths H9R inyectados")
    return Path(boundary), Path(filesystem), Path(outputs), Path(pools)


def _synthetic_first_open(boundary: ConsumerBoundary, input_path: Path) -> None:
    """Registra una frontera sólo para probes no agregables con shape productiva cerrada."""
    logical_bytes = input_path.stat().st_size
    digest = sha256_file(input_path)
    identity = {
        "role": "input",
        "relative_name": input_path.name,
        "logical_bytes": logical_bytes,
        "sha256": digest,
    }
    protected = [{"logical_id": canonical_json_sha256(identity), **identity}]
    request_id = canonical_json_sha256(
        {"probe": "harness-test-only", "operation": "OPEN", "protected": protected}
    )
    boundary.first_open(
        protected,
        request_id=request_id,
        broker_request_sha256=canonical_json_sha256(
            {"request_id": request_id, "probe": "harness-test-only"}
        ),
        nonce_commitment_sha256=canonical_json_sha256(
            {"nonce": "harness-test-only", "request_id": request_id}
        ),
        candidate_process={"pid": os.getpid(), "creation_time_100ns": 1},
    )


def run_probe(mode: str, *, input_path: Path | None, delay_seconds: float) -> int:
    """Ejecuta un defecto controlado con bytes pequeños y sin importar Nikodym."""
    # Los probes de kernel no son consumidores y, por tanto, no deben fingir sidecars de
    # frontera ni exigir paths que sólo existen dentro del worker. Esto permite ejecutarlos en
    # ``harness-test`` sin materializar una unidad ni emitir un token START.
    if mode == "affinity-expand":
        before = current_process_affinity()["process_mask"]
        system = current_process_affinity()["system_mask"]
        outside = system & ~before
        requested = before | (outside & -outside) if outside else before
        result = try_expand_current_process_affinity(requested)
        # Dentro del Job correcto el effective mask no puede incorporar la quinta CPU.
        return 0 if int(result["effective_logical_cpu_count"]) <= 4 else 91
    if mode == "memory":
        raw_cap = os.environ.get("NIKODYM_H9R_CONTROL_JOB_CAP_BYTES")
        if raw_cap is None or not raw_cap.isdigit() or int(raw_cap) < 1:
            raise RuntimeError("probe memory exige NIKODYM_H9R_CONTROL_JOB_CAP_BYTES")
        request_bytes = int(raw_cap) + 1
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.VirtualAlloc.argtypes = [
            ctypes.c_void_p,
            ctypes.c_size_t,
            ctypes.c_uint32,
            ctypes.c_uint32,
        ]
        kernel32.VirtualAlloc.restype = ctypes.c_void_p
        kernel32.VirtualFree.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_uint32]
        kernel32.VirtualFree.restype = ctypes.c_bool
        allocation = kernel32.VirtualAlloc(None, request_bytes, 0x3000, 0x04)
        if allocation:
            kernel32.VirtualFree(allocation, 0, 0x8000)
            return 91
        # La causa autoritativa se consulta en JobObjectLimitViolationInformation; el exit code
        # sólo comunica que VirtualAlloc rechazó la solicitud exacta C+1.
        return 86
    if mode == "deadline" and input_path is None:
        time.sleep(delay_seconds)
        return 0

    boundary_path, filesystem_path, output_root, pools_path = _paths_from_environment()
    boundary = ConsumerBoundary(boundary_path, filesystem_path)
    record_native_pools(
        pools_path,
        total_processes=1,
        processes=[
            {
                "pid": os.getpid(),
                "creation_time_100ns": 1,
                "environment": {name: "4" for name in POOL_ENVIRONMENT_KEYS},
                "libraries": [],
                "process_thread_count": threading.active_count(),
            }
        ],
    )
    if mode == "normal":
        if input_path is None:
            raise RuntimeError("probe normal exige --input")
        _synthetic_first_open(boundary, input_path)
        input_bytes = input_path.read_bytes()
        publisher = ConsumerPublisher(output_root, boundary)
        publisher.publish("result.bin", "probe-result", 0, input_bytes[::-1], record_count=1)
        publisher.finalize()
        return 0
    if mode == "deadline":
        if input_path is not None:
            _synthetic_first_open(boundary, input_path)
        time.sleep(delay_seconds)
        return 0
    if mode == "partial-crash":
        if input_path is not None:
            _synthetic_first_open(boundary, input_path)
        output_root.mkdir(parents=True, exist_ok=True)
        partial = output_root / ".result.bin.partial"
        with partial.open("xb") as handle:
            boundary.filesystem_event("create", partial)
            handle.write(b"partial")
            handle.flush()
            os.fsync(handle.fileno())
            boundary.filesystem_event("flush", partial)
        return 92
    raise RuntimeError(f"probe desconocido: {mode}")


def main(argv: list[str] | None = None) -> int:
    """CLI interno de probes; no acepta nombres de flujo ni autorización START."""
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "mode", choices=("normal", "deadline", "memory", "affinity-expand", "partial-crash")
    )
    parser.add_argument("--input", type=Path)
    parser.add_argument("--delay-seconds", type=float, default=2.0)
    args = parser.parse_args(argv)
    return run_probe(args.mode, input_path=args.input, delay_seconds=args.delay_seconds)


if __name__ == "__main__":
    raise SystemExit(main())
