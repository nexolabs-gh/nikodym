"""Controles causales de outputs y fronteras del arnés H9R (sin START)."""

from __future__ import annotations

import ctypes
import hashlib
import inspect
import json
import os
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

import scripts.readiness_h9r.artifacts as artifacts_module
from scripts.readiness_h9r.artifacts import (
    AtomicOutputPublisher,
    JsonlRecorder,
    atomic_write_bytes_exclusive,
    binary_sidecar_metadata,
    derive_golden_observed_sha256,
    file_storage_size,
    jsonl_sidecar_metadata,
    validate_output_manifest,
    verify_jsonl_sidecar,
    verify_sidecar,
)
from scripts.readiness_h9r.consumer import (
    ConsumerBoundary,
    ConsumerPublisher,
    reconstruct_boundary_sidecar,
    reconstruct_consumer_sidecars,
    reconstruct_filesystem_sidecar,
    validate_boundary_sidecar_equality,
    validate_consumer_sidecars_equality,
    validate_filesystem_sidecar_equality,
)
from scripts.readiness_h9r.contracts import (
    ContractError,
    canonical_json_bytes,
    canonical_json_sha256,
)


def test_file_standard_info_conserva_layout_abi_win32() -> None:
    layout = artifacts_module._WindowsFileStandardInfo
    assert ctypes.sizeof(layout) == 24
    assert layout.allocation_size.offset == 0
    assert layout.end_of_file.offset == 8
    assert layout.number_of_links.offset == 16
    assert layout.delete_pending.offset == 20
    assert layout.directory.offset == 21
    assert layout._fields_[-2][1] is ctypes.c_ubyte
    assert layout._fields_[-1][1] is ctypes.c_ubyte


def test_catalogo_contadores_deriva_formatos_y_bin_liga_sidecar(tmp_path: Path) -> None:
    output_root = tmp_path / "outputs"
    parquet_source = tmp_path / "source.parquet"
    pq.write_table(pa.table({"value": [1, 2, 3]}), parquet_source)
    publisher = AtomicOutputPublisher(output_root)

    publisher.publish("rows.jsonl", "jsonl", 0, b'{"x":1}\n{"x":2}\n')
    publisher.publish("rows.csv", "csv", 1, b"x,y\n1,2\n3,4\n")
    publisher.publish("rows.json", "json", 2, b"[1,2,3,4]")
    publisher.publish_file("rows.parquet", "parquet", 3, parquet_source)
    binary = publisher.publish("opaque.bin", "bin", 4, b"opaque", record_count=7)
    finalized = publisher.finalize()

    assert [item["record_count"] for item in publisher.artifacts] == [2, 2, 4, 3, 7]
    assert binary["count_evidence"]["mode"] == "hash_bound_attestation"
    counts = {"jsonl": 2, "csv": 2, "json": 4, "parquet": 3, "bin": 7}
    manifest = validate_output_manifest(
        output_root,
        expected_identities=list(counts),
        expected_counts=counts,
        expected_golden_sha256=finalized["manifest"]["golden_observed_sha256"],
    )
    assert manifest["golden_observed_sha256"] == derive_golden_observed_sha256(
        manifest["artifacts"]
    )

    # Rojo causal: el sidecar binario ya no liga sus bytes al hash firmado; luego restaura exacto.
    sidecar_path = output_root / "opaque.bin.count.json"
    original = sidecar_path.read_bytes()
    tampered = json.loads(original)
    tampered["records"] = 8
    sidecar_path.write_bytes(canonical_json_bytes(tampered) + b"\n")
    with pytest.raises(ContractError):
        validate_output_manifest(output_root, expected_identities=list(counts))
    sidecar_path.write_bytes(original)
    assert sidecar_path.read_bytes() == original
    validate_output_manifest(output_root, expected_identities=list(counts))


def test_conteos_derivables_rechazan_entero_de_consumidor_antes_de_escribir(
    tmp_path: Path,
) -> None:
    publisher = AtomicOutputPublisher(tmp_path / "outputs")
    with pytest.raises(ContractError, match="record_count externo prohibido"):
        publisher.publish("rows.json", "rows", 0, b"[1,2]", record_count=99)
    assert not any((tmp_path / "outputs").rglob("*"))


def test_golden_se_deriva_de_inventario_no_de_ruta_arbitraria(tmp_path: Path) -> None:
    assert (
        "golden_observed_path" not in inspect.signature(AtomicOutputPublisher.finalize).parameters
    )
    first = AtomicOutputPublisher(tmp_path / "first")
    first.publish("rows.json", "rows", 0, b"[1,2]")
    manifest_a = first.finalize()["manifest"]

    second = AtomicOutputPublisher(tmp_path / "second")
    second.publish("rows.json", "rows", 0, b"[1,2]")
    manifest_b = second.finalize()["manifest"]
    assert manifest_a["golden_observed_sha256"] == manifest_b["golden_observed_sha256"]

    manifest_path = tmp_path / "first" / "manifest.json"
    original = manifest_path.read_bytes()
    corrupted = dict(manifest_a)
    corrupted["golden_observed_sha256"] = "0123456789abcdef" * 4
    manifest_path.write_bytes(canonical_json_bytes(corrupted) + b"\n")
    with pytest.raises(ContractError, match="golden observado"):
        validate_output_manifest(tmp_path / "first", expected_identities=["rows"])
    manifest_path.write_bytes(original)
    assert manifest_path.read_bytes() == original
    validate_output_manifest(tmp_path / "first", expected_identities=["rows"])


@pytest.mark.parametrize("control_kind", ["manifest", "count_sidecar"])
def test_controles_de_output_exigen_json_canonico_y_newline(
    tmp_path: Path,
    control_kind: str,
) -> None:
    output_root = tmp_path / "outputs"
    publisher = AtomicOutputPublisher(output_root)
    if control_kind == "manifest":
        publisher.publish("rows.json", "rows", 0, b"[1]")
        target = output_root / "manifest.json"
    else:
        publisher.publish("opaque.bin", "rows", 0, b"opaque", record_count=1)
        target = output_root / "opaque.bin.count.json"
    publisher.finalize()
    manifest_path = output_root / "manifest.json"
    original_manifest = manifest_path.read_bytes()
    original = target.read_bytes()
    raw = json.loads(original)
    target.write_text(json.dumps(raw, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if control_kind == "count_sidecar":
        manifest = json.loads(original_manifest)
        artifact = manifest["artifacts"][0]
        sidecar = artifact["count_evidence"]["sidecar"]
        sidecar["logical_bytes"] = target.stat().st_size
        sidecar["sha256"] = hashlib.sha256(target.read_bytes()).hexdigest()
        artifact["reconciliation_sha256"] = canonical_json_sha256(
            {
                key: artifact[key]
                for key in (
                    "relative_path",
                    "identity",
                    "ordinal",
                    "format",
                    "record_count",
                    "count_evidence",
                    "logical_bytes",
                    "sha256",
                    "chunks",
                )
            }
        )
        manifest["golden_observed_sha256"] = derive_golden_observed_sha256(manifest["artifacts"])
        manifest_path.write_bytes(canonical_json_bytes(manifest) + b"\n")
    with pytest.raises(ContractError, match="JSON no es canónico"):
        validate_output_manifest(output_root, expected_identities=["rows"])

    target.write_bytes(original)
    manifest_path.write_bytes(original_manifest)
    assert target.read_bytes() == original
    validate_output_manifest(output_root, expected_identities=["rows"])


def test_censo_storage_rechaza_handle_de_otro_file_id(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if sys.platform != "win32":
        pytest.skip("el sensor calificable por handle es Windows")
    target = tmp_path / "observed.bin"
    target.write_bytes(b"observed")
    expected = target.lstat()
    opened: list[str] = []

    class FakeCall:
        argtypes: object = None
        restype: object = None

        def __init__(self, callback: Callable[..., object]) -> None:
            self.callback = callback

        def __call__(self, *args: object) -> object:
            return self.callback(*args)

    def create_file(path: object, *args: object) -> int:
        del args
        opened.append(str(path))
        return 1

    def identity(_handle: object, pointer: object) -> int:
        raw = cast(Any, pointer)._obj
        raw.attributes = 32
        raw.number_of_links = 1
        wrong_file_id = int(expected.st_ino) + 1
        raw.file_index_high = wrong_file_id >> 32
        raw.file_index_low = wrong_file_id & 0xFFFFFFFF
        raw.file_size_high = 0
        raw.file_size_low = int(expected.st_size)
        return 1

    def standard(_handle: object, _kind: object, pointer: object, _size: object) -> int:
        raw = cast(Any, pointer)._obj
        raw.allocation_size = 4096
        raw.end_of_file = int(expected.st_size)
        raw.number_of_links = 1
        raw.delete_pending = 0
        raw.directory = 0
        return 1

    fake_kernel = type(
        "FakeKernel32",
        (),
        {
            "CreateFileW": FakeCall(create_file),
            "GetFileInformationByHandle": FakeCall(identity),
            "GetFileInformationByHandleEx": FakeCall(standard),
            "CloseHandle": FakeCall(lambda _handle: 1),
        },
    )()
    monkeypatch.setattr(
        "scripts.readiness_h9r.artifacts.ctypes.WinDLL",
        lambda *args, **kwargs: fake_kernel,
    )

    with pytest.raises(ContractError, match="identidad/almacenamiento"):
        file_storage_size(target)
    assert opened == [str(target.absolute())]


@pytest.mark.parametrize(  # type: ignore[untyped-decorator]
    "relative", ["../outside.json", "/outside.json", "C:/outside.json"]
)
def test_manifest_rechaza_ruta_fuera_antes_de_abrir(
    tmp_path: Path, relative: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    output_root = tmp_path / "outputs"
    publisher = AtomicOutputPublisher(output_root)
    publisher.publish("rows.json", "rows", 0, b"[1,2]")
    manifest = publisher.finalize()["manifest"]
    manifest_path = output_root / "manifest.json"
    original = manifest_path.read_bytes()
    manifest["artifacts"][0]["relative_path"] = relative
    manifest_path.write_bytes(canonical_json_bytes(manifest) + b"\n")
    opened: list[str] = []
    original_open = cast(Callable[..., Any], Path.open)

    def observed_open(path: Path, *args: object, **kwargs: object) -> Any:
        opened.append(str(path))
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", observed_open)
    with pytest.raises(ContractError, match="relative_path"):
        validate_output_manifest(output_root, expected_identities=["rows"])
    assert not any("outside.json" in path for path in opened)
    monkeypatch.undo()
    manifest_path.write_bytes(original)
    validate_output_manifest(output_root, expected_identities=["rows"])


def test_manifest_rechaza_junction_dinamica_en_outputs(tmp_path: Path) -> None:
    if sys.platform != "win32":
        pytest.skip("junction es un reparse point de Windows")
    output_root = tmp_path / "outputs"
    publisher = AtomicOutputPublisher(output_root)
    publisher.publish("rows.json", "rows", 0, b"[1,2]")
    publisher.finalize()
    external = tmp_path / "external"
    external.mkdir()
    (external / "extra.json").write_bytes(b"[]")
    junction = output_root / "escape"
    created = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(junction), str(external)],
        check=False,
        capture_output=True,
    )
    if created.returncode != 0:
        pytest.skip("el entorno no permitió crear junction")
    try:
        with pytest.raises(ContractError, match="reparse point"):
            validate_output_manifest(output_root, expected_identities=["rows"])
    finally:
        junction.rmdir()


def test_manifest_rechaza_replace_despues_de_checks_antes_del_censo(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output_root = tmp_path / "outputs"
    publisher = AtomicOutputPublisher(output_root)
    publisher.publish("rows.json", "rows", 0, b"[1]")
    finalized = publisher.finalize()
    target = output_root / "rows.json"
    replacement = tmp_path / "replacement.json"
    replacement.write_bytes(b"[2]")
    original_walk = artifacts_module._regular_files_no_reparse
    swapped = False

    def swap_before_census(root: Path) -> list[Path]:
        nonlocal swapped
        if root == output_root and not swapped:
            swapped = True
            os.replace(replacement, target)
        return original_walk(root)

    monkeypatch.setattr(artifacts_module, "_regular_files_no_reparse", swap_before_census)
    with pytest.raises(ContractError, match="cambió"):
        validate_output_manifest(
            output_root,
            expected_identities=["rows"],
            expected_golden_sha256=finalized["manifest"]["golden_observed_sha256"],
        )


def test_manifest_repite_censo_y_rechaza_extra_tardio(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output_root = tmp_path / "outputs"
    publisher = AtomicOutputPublisher(output_root)
    publisher.publish("rows.json", "rows", 0, b"[1]")
    finalized = publisher.finalize()
    original_walk = artifacts_module._regular_files_no_reparse
    calls = 0

    def add_on_final_census(root: Path) -> list[Path]:
        nonlocal calls
        calls += 1
        if root == output_root and calls == 2:
            (output_root / "extra.json").write_bytes(b"[]")
        return original_walk(root)

    monkeypatch.setattr(artifacts_module, "_regular_files_no_reparse", add_on_final_census)
    with pytest.raises(ContractError, match="cambió"):
        validate_output_manifest(
            output_root,
            expected_identities=["rows"],
            expected_golden_sha256=finalized["manifest"]["golden_observed_sha256"],
        )


def test_manifest_liga_versiones_del_censo_final(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output_root = tmp_path / "outputs"
    publisher = AtomicOutputPublisher(output_root)
    publisher.publish("rows.json", "rows", 0, b"[1]")
    finalized = publisher.finalize()
    target = output_root / "rows.json"
    original_walk = artifacts_module._regular_files_no_reparse
    calls = 0

    def mutate_after_final_census(root: Path) -> list[Path]:
        nonlocal calls
        paths = original_walk(root)
        if root == output_root:
            calls += 1
            if calls == 2:
                target.write_bytes(b"[2]")
        return paths

    monkeypatch.setattr(artifacts_module, "_regular_files_no_reparse", mutate_after_final_census)
    with pytest.raises(ContractError, match="cambió"):
        validate_output_manifest(
            output_root,
            expected_identities=["rows"],
            expected_golden_sha256=finalized["manifest"]["golden_observed_sha256"],
        )


def test_manifest_rechaza_junction_en_ancestro_de_outputs(tmp_path: Path) -> None:
    if sys.platform != "win32":
        pytest.skip("junction es un reparse point de Windows")
    external = tmp_path / "external"
    external.mkdir()
    output_root = external / "outputs"
    publisher = AtomicOutputPublisher(output_root)
    publisher.publish("rows.json", "rows", 0, b"[1,2]")
    publisher.finalize()
    junction = tmp_path / "alias"
    created = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(junction), str(external)],
        check=False,
        capture_output=True,
    )
    if created.returncode != 0:
        pytest.skip("el entorno no permitió crear junction")
    try:
        with pytest.raises(ContractError, match="reparse point"):
            validate_output_manifest(junction / "outputs", expected_identities=["rows"])
    finally:
        junction.rmdir()


@pytest.mark.parametrize("writer_kind", ["atomic", "jsonl"])
def test_escritores_rechazan_parent_junction_sin_escribir_fuera(
    tmp_path: Path,
    writer_kind: str,
) -> None:
    if sys.platform != "win32":
        pytest.skip("junction es un reparse point de Windows")
    external = tmp_path / "external"
    external.mkdir()
    junction = tmp_path / "alias"
    created = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(junction), str(external)],
        check=False,
        capture_output=True,
    )
    if created.returncode != 0:
        pytest.skip("el entorno no permitió crear junction")
    try:
        destination = junction / "nested" / "evidence.jsonl"
        with pytest.raises(ContractError, match="redirigido"):
            if writer_kind == "atomic":
                atomic_write_bytes_exclusive(destination, b"{}\n")
            else:
                JsonlRecorder(destination)
        assert not (external / "nested").exists()
    finally:
        junction.rmdir()


@pytest.mark.parametrize("target_kind", ["manifest", "output", "count_sidecar"])
def test_manifest_rechaza_hardlinks_antes_de_abrir_el_objetivo(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    target_kind: str,
) -> None:
    output_root = tmp_path / "outputs"
    publisher = AtomicOutputPublisher(output_root)
    if target_kind == "count_sidecar":
        publisher.publish("opaque.bin", "rows", 0, b"opaque", record_count=1)
        target = output_root / "opaque.bin.count.json"
    else:
        publisher.publish("rows.json", "rows", 0, b"[1]")
        target = output_root / ("manifest.json" if target_kind == "manifest" else "rows.json")
    publisher.finalize()
    alias = tmp_path / f"{target_kind}.alias"
    os.link(target, alias)

    opened: list[Path] = []
    original_open = cast(Callable[..., Any], Path.open)

    def observed_open(path: Path, *args: object, **kwargs: object) -> Any:
        opened.append(path)
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", observed_open)
    with pytest.raises(ContractError, match="hardlink"):
        validate_output_manifest(output_root, expected_identities=["rows"])
    assert target not in opened


@pytest.mark.parametrize("sidecar_format", ["jsonl", "binary"])
def test_sidecar_rechaza_symlink_antes_de_abrir(tmp_path: Path, sidecar_format: str) -> None:
    source = tmp_path / ("source.jsonl" if sidecar_format == "jsonl" else "source.bin")
    source.write_bytes(b'{"event":"ok"}\n' if sidecar_format == "jsonl" else b"opaque")
    linked = tmp_path / ("linked.jsonl" if sidecar_format == "jsonl" else "linked.bin")
    try:
        linked.symlink_to(source)
    except OSError:
        pytest.skip("el host no permitió crear symlink de control")

    with pytest.raises(ContractError, match="reparse point/symlink"):
        if sidecar_format == "jsonl":
            jsonl_sidecar_metadata(linked, name="linked")
        else:
            binary_sidecar_metadata(linked, name="linked")


@pytest.mark.parametrize("sidecar_format", ["jsonl", "binary"])
def test_verificador_sidecar_rechaza_hardlink(tmp_path: Path, sidecar_format: str) -> None:
    source = tmp_path / ("source.jsonl" if sidecar_format == "jsonl" else "source.bin")
    source.write_bytes(b'{"event":"ok"}\n' if sidecar_format == "jsonl" else b"opaque")
    linked = tmp_path / ("linked.jsonl" if sidecar_format == "jsonl" else "linked.bin")
    os.link(source, linked)
    metadata = {
        "name": "linked",
        "path": str(linked),
        "format": sidecar_format,
        "records": 1,
        "bytes": linked.stat().st_size,
        "sha256": hashlib.sha256(linked.read_bytes()).hexdigest(),
    }
    with pytest.raises(ContractError, match="hardlinks prohibidos"):
        if sidecar_format == "jsonl":
            verify_jsonl_sidecar(metadata)
        else:
            verify_sidecar(metadata)


@pytest.mark.parametrize(
    "corrupted",
    [
        b'{"event":"ok"}',
        b'{ "event": "ok" }\n',
        b'{"z":0,"event":"ok"}\n',
    ],
)
def test_sidecar_jsonl_exige_newline_y_json_canonico(
    tmp_path: Path,
    corrupted: bytes,
) -> None:
    path = tmp_path / "events.jsonl"
    path.write_bytes(corrupted)
    metadata = {
        "name": "events",
        "path": str(path),
        "format": "jsonl",
        "records": 1,
        "bytes": len(corrupted),
        "sha256": hashlib.sha256(corrupted).hexdigest(),
    }
    with pytest.raises(ContractError, match=r"newline final|no es canónico"):
        verify_jsonl_sidecar(metadata)
    with pytest.raises(ContractError, match=r"newline final|no es canónico"):
        jsonl_sidecar_metadata(path, name="events")

    restored = b'{"event":"ok"}\n'
    path.write_bytes(restored)
    restored_metadata = {
        **metadata,
        "bytes": len(restored),
        "sha256": hashlib.sha256(restored).hexdigest(),
    }
    assert verify_jsonl_sidecar(restored_metadata) == [{"event": "ok"}]
    assert jsonl_sidecar_metadata(path, name="events") == restored_metadata


def test_sidecar_jsonl_rechaza_replace_entre_hash_y_parseo(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "events.jsonl"
    original = b'{"x":1}\n'
    replacement = tmp_path / "replacement.jsonl"
    path.write_bytes(original)
    replacement.write_bytes(b'{"x":2}\n')
    metadata = {
        "name": "events",
        "path": str(path),
        "format": "jsonl",
        "records": 1,
        "bytes": len(original),
        "sha256": hashlib.sha256(original).hexdigest(),
    }
    original_sha256 = hashlib.sha256
    swapped = False

    def swap_after_hash(payload: bytes = b"") -> Any:
        nonlocal swapped
        digest = original_sha256(payload)
        if not swapped:
            swapped = True
            os.replace(replacement, path)
        return digest

    monkeypatch.setattr(artifacts_module.hashlib, "sha256", swap_after_hash)
    with pytest.raises(ContractError, match="cambió"):
        verify_jsonl_sidecar(metadata)


@pytest.mark.parametrize("sidecar_format", ["jsonl", "binary"])
def test_sidecar_rechaza_junction_en_ancestro(tmp_path: Path, sidecar_format: str) -> None:
    if sys.platform != "win32":
        pytest.skip("junction es un reparse point de Windows")
    external = tmp_path / "external"
    external.mkdir()
    filename = "source.jsonl" if sidecar_format == "jsonl" else "source.bin"
    source = external / filename
    source.write_bytes(b'{"event":"ok"}\n' if sidecar_format == "jsonl" else b"opaque")
    junction = tmp_path / "alias"
    created = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(junction), str(external)],
        check=False,
        capture_output=True,
    )
    if created.returncode != 0:
        pytest.skip("el entorno no permitió crear junction de control")
    try:
        with pytest.raises(ContractError, match="reparse point/symlink"):
            if sidecar_format == "jsonl":
                jsonl_sidecar_metadata(junction / filename, name="linked")
            else:
                binary_sidecar_metadata(junction / filename, name="linked")
    finally:
        junction.rmdir()


def test_sidecars_boundary_filesystem_reconstruyen_evidencia_e_inventario(
    tmp_path: Path,
) -> None:
    boundary_path = tmp_path / "boundary.jsonl"
    filesystem_path = tmp_path / "filesystem.jsonl"
    output_root = tmp_path / "outputs"
    boundary = ConsumerBoundary(boundary_path, filesystem_path)
    protected_identity = {
        "role": "input",
        "relative_name": "input.json",
        "logical_bytes": 2,
        "sha256": "1" * 64,
    }
    boundary.first_open(
        [
            {
                "logical_id": canonical_json_sha256(protected_identity),
                **protected_identity,
            }
        ],
        request_id="2" * 64,
        broker_request_sha256="3" * 64,
        nonce_commitment_sha256="4" * 64,
        candidate_process={"pid": 123, "creation_time_100ns": 456},
    )
    publisher = ConsumerPublisher(output_root, boundary)
    publisher.publish("rows.json", "rows", 0, b"[1,2,3]")
    finalized = publisher.finalize()

    boundary_metadata = jsonl_sidecar_metadata(boundary_path, name="boundary")
    filesystem_metadata = jsonl_sidecar_metadata(filesystem_path, name="filesystem")
    boundary_events = reconstruct_boundary_sidecar(boundary_metadata)
    filesystem_events = reconstruct_filesystem_sidecar(
        filesystem_metadata,
        output_root=output_root,
        manifest=finalized["manifest"],
        require_complete=True,
    )
    validate_boundary_sidecar_equality(boundary_metadata, boundary_events)
    validate_filesystem_sidecar_equality(
        filesystem_metadata,
        filesystem_events,
        output_root=output_root,
        manifest=finalized["manifest"],
        require_complete=True,
    )
    reconstructed = reconstruct_consumer_sidecars(
        boundary_metadata=boundary_metadata,
        filesystem_metadata=filesystem_metadata,
        output_root=output_root,
        manifest=finalized["manifest"],
        require_complete=True,
    )
    assert (
        validate_consumer_sidecars_equality(
            boundary_metadata=boundary_metadata,
            filesystem_metadata=filesystem_metadata,
            evidence=reconstructed,
            output_root=output_root,
            manifest=finalized["manifest"],
            require_complete=True,
        )
        == reconstructed
    )
    mismatched_manifest = {
        **finalized["manifest"],
        "artifacts": [dict(item) for item in finalized["manifest"]["artifacts"]],
    }
    mismatched_manifest["artifacts"][0]["logical_bytes"] += 1
    with pytest.raises(ContractError, match="flush_complete no deriva"):
        reconstruct_consumer_sidecars(
            boundary_metadata=boundary_metadata,
            filesystem_metadata=filesystem_metadata,
            output_root=output_root,
            manifest=mismatched_manifest,
            require_complete=True,
        )
    assert [event["event"] for event in filesystem_events] == [
        "create",
        "flush",
        "hash",
        "rename",
        "create",
        "flush",
        "hash",
        "rename",
    ]

    # Rojo de igualdad: una copia de evidencia no puede separarse del sidecar reabierto.
    altered = [dict(event) for event in boundary_events]
    altered[0]["path"] = "otro-input"
    with pytest.raises(ContractError, match="no coincide"):
        validate_boundary_sidecar_equality(boundary_metadata, altered)

    # Rojo del catálogo, con restauración byte-exacta y verde posterior.
    original = filesystem_path.read_bytes()
    tampered = original.replace(b'"event":"create"', b'"event":"chmod"', 1)
    filesystem_path.write_bytes(tampered)
    tampered_metadata = jsonl_sidecar_metadata(filesystem_path, name="filesystem")
    with pytest.raises(ContractError, match="catálogo/schema cerrado"):
        reconstruct_filesystem_sidecar(
            tampered_metadata,
            output_root=output_root,
            manifest=finalized["manifest"],
            require_complete=True,
        )
    filesystem_path.write_bytes(original)
    assert filesystem_path.read_bytes() == original
    reconstruct_filesystem_sidecar(
        filesystem_metadata,
        output_root=output_root,
        manifest=finalized["manifest"],
        require_complete=True,
    )


def test_interrupcion_flush_registra_delete_y_no_publica_manifest(tmp_path: Path) -> None:
    filesystem_path = tmp_path / "filesystem.jsonl"
    boundary = ConsumerBoundary(tmp_path / "boundary.jsonl", filesystem_path)

    def interrupt_after_record(operation: str, path: Path) -> None:
        boundary.filesystem_event(operation, path)
        if operation == "flush":
            raise RuntimeError("interrupción inyectada")

    output_root = tmp_path / "outputs"
    publisher = AtomicOutputPublisher(output_root, event_callback=interrupt_after_record)
    with pytest.raises(RuntimeError, match="interrupción inyectada"):
        publisher.publish("rows.json", "rows", 0, b"[1,2]")
    assert not (output_root / "manifest.json").exists()
    metadata = jsonl_sidecar_metadata(filesystem_path, name="filesystem")
    events = reconstruct_filesystem_sidecar(
        metadata,
        output_root=output_root,
        manifest=None,
        require_complete=False,
    )
    assert [event["event"] for event in events] == ["create", "flush", "delete"]
    assert not any(output_root.rglob("*.partial"))


def test_identidad_de_arbol_repite_censo_y_rechaza_archivo_tardio(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "tree"
    root.mkdir()
    (root / "a.py").write_bytes(b"a")
    original_census = artifacts_module._regular_files_no_reparse
    calls = 0

    def add_after_first_census(candidate: Path) -> list[Path]:
        nonlocal calls
        calls += 1
        paths = original_census(candidate)
        if calls == 1:
            (root / "z.py").write_bytes(b"late")
        return paths

    monkeypatch.setattr(
        artifacts_module,
        "_regular_files_no_reparse",
        add_after_first_census,
    )
    with pytest.raises(ContractError, match="árbol instalado cambió"):
        artifacts_module.canonical_tree_identity(root)


@pytest.mark.parametrize("operation", ["tree", "inventory"])
def test_identidad_e_inventario_ligan_versiones_del_ultimo_censo(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
) -> None:
    root = tmp_path / "tree"
    root.mkdir()
    target = root / "a.py"
    target.write_bytes(b"A")
    original_census = artifacts_module._regular_files_no_reparse
    calls = 0

    def mutate_after_third_census(candidate: Path) -> list[Path]:
        nonlocal calls
        paths = original_census(candidate)
        if candidate == root:
            calls += 1
            if calls == 3:
                target.write_bytes(b"B")
        return paths

    monkeypatch.setattr(
        artifacts_module,
        "_regular_files_no_reparse",
        mutate_after_third_census,
    )
    with pytest.raises(ContractError, match="cambió"):
        if operation == "tree":
            artifacts_module.canonical_tree_identity(root)
        else:
            artifacts_module.final_inventory(root)


@pytest.mark.parametrize("operation", ["tree", "inventory"])
def test_identidad_e_inventario_no_mezclan_versiones_entre_tamano_y_hash(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
) -> None:
    root = tmp_path / "tree"
    root.mkdir()
    target = root / "a.py"
    target.write_bytes(b"a")
    original_hash_bound = artifacts_module._hash_bound_file
    swapped = False

    def swap_after_bound_hash(
        candidate: Path,
        *,
        context: str,
        deadline_monotonic: float | None = None,
    ) -> tuple[Path, int, str, os.stat_result]:
        nonlocal swapped
        result = original_hash_bound(
            candidate,
            context=context,
            deadline_monotonic=deadline_monotonic,
        )
        if candidate == target and not swapped:
            swapped = True
            target.write_bytes(b"BBBB")
        return result

    def legacy_hash(candidate: Path, *, deadline_monotonic: float | None = None) -> str:
        del deadline_monotonic
        nonlocal swapped
        if candidate == target and not swapped:
            swapped = True
            target.write_bytes(b"BBBB")
        return hashlib.sha256(candidate.read_bytes()).hexdigest()

    monkeypatch.setattr(artifacts_module, "_hash_bound_file", swap_after_bound_hash)
    monkeypatch.setattr(artifacts_module, "sha256_file", legacy_hash, raising=False)
    with pytest.raises(ContractError, match=r"cambió|mezcló versiones"):
        if operation == "tree":
            artifacts_module.canonical_tree_identity(root)
        else:
            artifacts_module.final_inventory(root)


def test_publicacion_deriva_tamano_y_hash_de_la_misma_version(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    destination = tmp_path / "evidence.json"
    original_hash_bound = artifacts_module._hash_bound_file
    swapped = False

    def swap_after_final_hash(
        candidate: Path,
        *,
        context: str,
        deadline_monotonic: float | None = None,
    ) -> tuple[Path, int, str, os.stat_result]:
        nonlocal swapped
        result = original_hash_bound(
            candidate,
            context=context,
            deadline_monotonic=deadline_monotonic,
        )
        if candidate == destination and not swapped:
            swapped = True
            destination.write_bytes(b"BBBB")
        return result

    def legacy_hash(candidate: Path, *, deadline_monotonic: float | None = None) -> str:
        del deadline_monotonic
        nonlocal swapped
        if candidate == destination and not swapped:
            swapped = True
            destination.write_bytes(b"BBBB")
        return hashlib.sha256(candidate.read_bytes()).hexdigest()

    monkeypatch.setattr(artifacts_module, "_hash_bound_file", swap_after_final_hash)
    monkeypatch.setattr(artifacts_module, "sha256_file", legacy_hash, raising=False)
    with pytest.raises(ContractError, match="archivo cambió"):
        atomic_write_bytes_exclusive(destination, b"a")
    assert not os.path.lexists(destination)
    quarantines = list(tmp_path.glob(".evidence.json.*.failed.quarantine"))
    assert len(quarantines) == 1
    assert quarantines[0].read_bytes() == b"BBBB"


def test_publicacion_fallida_no_mueve_un_destino_sustituido(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    destination = tmp_path / "evidence.json"
    replacement = tmp_path / "replacement.json"
    replacement.write_bytes(b"objeto-ajeno")
    original_hash_bound = artifacts_module._hash_bound_file
    swapped = False

    def replace_after_final_hash(
        candidate: Path,
        *,
        context: str,
        deadline_monotonic: float | None = None,
    ) -> tuple[Path, int, str, os.stat_result]:
        nonlocal swapped
        result = original_hash_bound(
            candidate,
            context=context,
            deadline_monotonic=deadline_monotonic,
        )
        if candidate == destination and not swapped:
            swapped = True
            os.replace(replacement, destination)
        return result

    monkeypatch.setattr(artifacts_module, "_hash_bound_file", replace_after_final_hash)
    with pytest.raises(ContractError, match="archivo cambió"):
        atomic_write_bytes_exclusive(destination, b"a")
    assert destination.read_bytes() == b"objeto-ajeno"
    assert list(tmp_path.glob(".evidence.json.*.failed.quarantine")) == []


def test_publicacion_rechaza_mutacion_del_temporal_despues_de_fsync(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    destination = tmp_path / "evidence.json"
    original_hash_bound = artifacts_module._hash_bound_file
    swapped = False

    def swap_before_temporary_hash(
        candidate: Path,
        *,
        context: str,
        deadline_monotonic: float | None = None,
    ) -> tuple[Path, int, str, os.stat_result]:
        nonlocal swapped
        if candidate.name.endswith(".partial") and not swapped:
            swapped = True
            candidate.write_bytes(b"BBBB")
        return original_hash_bound(
            candidate,
            context=context,
            deadline_monotonic=deadline_monotonic,
        )

    def legacy_hash(candidate: Path, *, deadline_monotonic: float | None = None) -> str:
        del deadline_monotonic
        nonlocal swapped
        if candidate.name.endswith(".partial") and not swapped:
            swapped = True
            candidate.write_bytes(b"BBBB")
        return hashlib.sha256(candidate.read_bytes()).hexdigest()

    monkeypatch.setattr(artifacts_module, "_hash_bound_file", swap_before_temporary_hash)
    monkeypatch.setattr(artifacts_module, "sha256_file", legacy_hash, raising=False)
    with pytest.raises(ContractError, match="temporal cambió de versión"):
        atomic_write_bytes_exclusive(destination, b"a")


def test_fallback_portable_retira_destino_si_falla_unlink_del_origen(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source.partial"
    destination = tmp_path / "destination.json"
    source.write_bytes(b"payload")
    original_unlink = Path.unlink
    injected = False

    def fail_source_once(path: Path, *args: Any, **kwargs: Any) -> None:
        nonlocal injected
        if path == source and not injected:
            injected = True
            raise OSError("fallo inyectado tras crear el hardlink")
        original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(artifacts_module.sys, "platform", "linux")
    monkeypatch.setattr(Path, "unlink", fail_source_once)
    with pytest.raises(OSError, match="fallo inyectado"):
        artifacts_module._move_file_exclusive(source, destination)
    assert source.read_bytes() == b"payload"
    assert not os.path.lexists(destination)
