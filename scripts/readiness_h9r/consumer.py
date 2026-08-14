"""Primitivas de frontera H9R; no acreditan por sí solas aislamiento frente al candidato.

La ruta productiva permanece bloqueada hasta contar con lease continuo del material ejecutable y
separación OS de ``OUTPUT_ROOT``. Los callbacks de filesystem registran sólo operaciones del
publisher confiable: no son un watcher del sistema operativo ni prueban ausencia de escrituras de
otro token.
"""

from __future__ import annotations

import os
import stat
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from .artifacts import (
    FILESYSTEM_EVENT_OPERATIONS,
    AtomicOutputPublisher,
    verify_jsonl_sidecar,
)
from .contracts import (
    ContractError,
    canonical_json_bytes,
    canonical_json_sha256,
    sha256_file,
    validate_sha256,
)

CONSUMER_BOUNDARY_EVENTS = (
    "first_open_or_byte",
    "flush_complete",
    "hash_complete",
    "rename_complete",
)


def _is_reparse_or_symlink(path: Path) -> bool:
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        return False
    return path.is_symlink() or bool(int(getattr(metadata, "st_file_attributes", 0)) & 0x400)


def _regular_files_no_follow(root: Path) -> list[Path]:
    """Censa archivos regulares sin atravesar junctions/symlinks ni nodos especiales."""
    root = Path(os.path.abspath(os.fspath(root)))
    if any(_is_reparse_or_symlink(item) for item in (root, *root.parents[:-1])):
        raise ContractError("filesystem output root o ancestro es symlink/reparse point")
    try:
        root_metadata = root.lstat()
    except FileNotFoundError as exc:
        raise ContractError("filesystem output root ausente") from exc
    if not stat.S_ISDIR(root_metadata.st_mode):
        raise ContractError("filesystem output root no es directorio regular")
    pending = [root]
    files: list[Path] = []
    while pending:
        directory = pending.pop()
        try:
            entries = sorted(os.scandir(directory), key=lambda entry: entry.name.casefold())
        except OSError as exc:
            raise ContractError(f"filesystem no pudo censar {directory}") from exc
        for entry in entries:
            candidate = Path(entry.path)
            try:
                metadata = entry.stat(follow_symlinks=False)
            except OSError as exc:
                raise ContractError(f"filesystem no pudo atestiguar {candidate}") from exc
            if entry.is_symlink() or bool(int(getattr(metadata, "st_file_attributes", 0)) & 0x400):
                raise ContractError(f"filesystem contiene symlink/reparse point: {candidate}")
            if stat.S_ISDIR(metadata.st_mode):
                pending.append(candidate)
            elif stat.S_ISREG(metadata.st_mode):
                files.append(candidate)
            else:
                raise ContractError(f"filesystem contiene nodo no regular: {candidate}")
    return sorted(files, key=lambda path: path.relative_to(root).as_posix())


def _lexical_absolute(path: Path) -> Path:
    return Path(os.path.abspath(os.fspath(path)))


def _node_identity(metadata: os.stat_result) -> tuple[int, int, int, int]:
    return (
        int(metadata.st_dev),
        int(metadata.st_ino),
        int(metadata.st_mode),
        int(getattr(metadata, "st_file_attributes", 0)),
    )


def _plain_directory_chain(directory: Path) -> tuple[tuple[Path, tuple[int, int, int, int]], ...]:
    chain = tuple(reversed((directory, *directory.parents)))
    observed: list[tuple[Path, tuple[int, int, int, int]]] = []
    for item in chain:
        try:
            metadata = item.lstat()
        except OSError as exc:
            raise ContractError(f"sidecar: directorio/ancestro ausente: {item}") from exc
        if (
            not stat.S_ISDIR(metadata.st_mode)
            or item.is_symlink()
            or bool(int(getattr(metadata, "st_file_attributes", 0)) & 0x400)
        ):
            raise ContractError(f"sidecar: directorio/ancestro no es plano: {item}")
        observed.append((item, _node_identity(metadata)))
    return tuple(observed)


def _require_single_link_regular(metadata: os.stat_result, *, path: Path) -> None:
    if (
        not stat.S_ISREG(metadata.st_mode)
        or int(metadata.st_nlink) != 1
        or bool(int(getattr(metadata, "st_file_attributes", 0)) & 0x400)
    ):
        raise ContractError(f"sidecar no es archivo regular single-link: {path}")


def _open_safe_append(path: Path, *, require_empty: bool) -> tuple[int, Path]:
    lexical = _lexical_absolute(path)
    parent_before = _plain_directory_chain(lexical.parent)
    flags = os.O_WRONLY | os.O_APPEND | getattr(os, "O_BINARY", 0)
    try:
        leaf_before = lexical.lstat()
    except FileNotFoundError:
        try:
            descriptor = os.open(lexical, flags | os.O_CREAT | os.O_EXCL, 0o600)
        except OSError as exc:
            raise ContractError(f"sidecar no pudo crearse en forma exclusiva: {lexical}") from exc
    else:
        if lexical.is_symlink():
            raise ContractError(f"sidecar es symlink/reparse point: {lexical}")
        _require_single_link_regular(leaf_before, path=lexical)
        try:
            descriptor = os.open(lexical, flags)
        except OSError as exc:
            raise ContractError(f"sidecar no pudo abrirse para append: {lexical}") from exc
    try:
        opened = os.fstat(descriptor)
        current = lexical.lstat()
        _require_single_link_regular(opened, path=lexical)
        _require_single_link_regular(current, path=lexical)
        if lexical.is_symlink() or _node_identity(opened) != _node_identity(current):
            raise ContractError("sidecar cambió entre lstat y open")
        if _plain_directory_chain(lexical.parent) != parent_before:
            raise ContractError("ancestro del sidecar cambió entre lstat y open")
        if require_empty and opened.st_size != 0:
            raise ContractError("sidecar previo no está vacío")
        return descriptor, lexical
    except BaseException:
        os.close(descriptor)
        raise


def prepare_jsonl_sidecar(path: Path) -> None:
    """Precrea o reabre vacío un sidecar, sin seguir aliases ni reparses."""
    descriptor, _lexical = _open_safe_append(path, require_empty=True)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def append_jsonl_event(path: Path, event: Mapping[str, Any]) -> None:
    """Agrega un evento pequeño, lo hace visible y fuerza sus bytes al filesystem."""
    payload = canonical_json_bytes(dict(event)) + b"\n"
    descriptor, lexical = _open_safe_append(path, require_empty=False)
    try:
        written = 0
        while written < len(payload):
            written += os.write(descriptor, payload[written:])
        os.fsync(descriptor)
        opened = os.fstat(descriptor)
        current = lexical.lstat()
        _require_single_link_regular(opened, path=lexical)
        _require_single_link_regular(current, path=lexical)
        if _node_identity(opened) != _node_identity(current):
            raise ContractError("sidecar cambió durante append")
    finally:
        os.close(descriptor)


class ConsumerBoundary:
    """Registra la frontera first-open/byte→flush→hash→rename del consumidor."""

    def __init__(self, boundary_path: Path, filesystem_events_path: Path) -> None:
        self.boundary_path = boundary_path
        self.filesystem_events_path = filesystem_events_path
        self._consumer_started = False

    def event(self, name: str, **evidence: Any) -> dict[str, Any]:
        """Registra un evento monotónico con evidencia adicional."""
        if name not in CONSUMER_BOUNDARY_EVENTS:
            raise ContractError(f"evento consumidor fuera del catálogo: {name!r}")
        event = {"event": name, "monotonic_ns": time.monotonic_ns(), **evidence}
        append_jsonl_event(self.boundary_path, event)
        return event

    def filesystem_event(self, operation: str, path: Path) -> None:
        """Registra el catálogo create/flush/hash/rename/delete con bytes causales."""
        if operation not in FILESYSTEM_EVENT_OPERATIONS:
            raise ContractError(f"operación filesystem fuera del catálogo: {operation!r}")
        evidence: dict[str, Any] = {
            "event": operation,
            "monotonic_ns": time.monotonic_ns(),
            "path": str(path.resolve()),
        }
        if operation in {"hash", "rename"}:
            if not path.is_file():
                raise ContractError(f"{operation}: archivo ausente al observarlo: {path}")
            evidence.update(
                {
                    "logical_bytes": path.stat().st_size,
                    "sha256": sha256_file(path),
                }
            )
        append_jsonl_event(
            self.filesystem_events_path,
            evidence,
        )

    def first_open(
        self,
        protected: Sequence[Mapping[str, Any]],
        *,
        request_id: str,
        broker_request_sha256: str,
        nonce_commitment_sha256: str,
        candidate_process: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Marca la primera apertura solicitada por el consumidor al broker del arnés."""
        if self._consumer_started:
            raise RuntimeError("la frontera inicial del consumidor ya fue registrada")
        normalized = [dict(item) for item in protected]
        if not normalized:
            raise ContractError("first_open exige inventario protegido no vacío")
        process = dict(candidate_process)
        if set(process) != {"pid", "creation_time_100ns"} or any(
            isinstance(process.get(name), bool)
            or not isinstance(process.get(name), int)
            or process[name] <= 0
            for name in process
        ):
            raise ContractError("first_open exige identidad exacta del proceso candidato")
        self._consumer_started = True
        return self.event(
            "first_open_or_byte",
            kind="first_open",
            provider="harness_owned_consumer_open_v1",
            request_id=validate_sha256(request_id, context="consumer_open.request_id"),
            protected=normalized,
            broker_request_sha256=validate_sha256(
                broker_request_sha256, context="consumer_open.broker_request_sha256"
            ),
            nonce_commitment_sha256=validate_sha256(
                nonce_commitment_sha256, context="consumer_open.nonce_commitment_sha256"
            ),
            candidate_process=process,
        )

    def first_byte(
        self,
        *,
        request_id: str,
        request_body_bytes: int,
        request_body_sha256: str,
        service_descriptor_sha256: str,
        endpoint_sha256: str,
    ) -> dict[str, Any]:
        """Marca el primer byte futuro del servicio candidato tras el ingress transparente."""
        if self._consumer_started:
            raise RuntimeError("la frontera inicial del consumidor ya fue registrada")
        self._consumer_started = True
        return self.event(
            "first_open_or_byte",
            kind="first_byte",
            provider="harness_owned_candidate_http_ingress_v1",
            request_id=request_id,
            request_body_bytes=request_body_bytes,
            request_body_sha256=validate_sha256(
                request_body_sha256, context="consumer first_byte body sha256"
            ),
            service_descriptor_sha256=validate_sha256(
                service_descriptor_sha256, context="consumer first_byte service descriptor"
            ),
            endpoint_sha256=validate_sha256(
                endpoint_sha256, context="consumer first_byte endpoint"
            ),
            non_transforming=True,
        )


def record_native_pools(
    path: Path,
    *,
    total_processes: int,
    processes: Sequence[Mapping[str, Any]],
) -> None:
    """Registra el censo efectivo PID/creation derivado del agregado controller-owned."""
    append_jsonl_event(
        path,
        {
            "event": "native_pools",
            "monotonic_ns": time.monotonic_ns(),
            "total_processes": total_processes,
            "processes": [dict(process) for process in processes],
        },
    )


def validate_consumer_boundary_events(
    events: Sequence[Mapping[str, Any]], *, require_complete: bool = True
) -> list[dict[str, Any]]:
    """Cierra forma, cardinalidad y orden de la frontera escrita por el consumidor."""
    observed = [dict(event) for event in events]
    positions: dict[str, int] = {}
    last_ns = -1
    for index, event in enumerate(observed):
        name = event.get("event")
        monotonic_ns = event.get("monotonic_ns")
        if name not in CONSUMER_BOUNDARY_EVENTS:
            raise ContractError(f"boundary consumidor fuera del catálogo: {name!r}")
        if (
            isinstance(monotonic_ns, bool)
            or not isinstance(monotonic_ns, int)
            or monotonic_ns < last_ns
        ):
            raise ContractError("reloj monotónico inválido en boundary consumidor")
        last_ns = monotonic_ns
        if name in positions:
            raise ContractError(f"evento boundary consumidor duplicado: {name}")
        positions[str(name)] = index
        if name == "first_open_or_byte":
            kind = event.get("kind")
            if kind == "first_open":
                expected = {
                    "event",
                    "monotonic_ns",
                    "kind",
                    "provider",
                    "request_id",
                    "protected",
                    "broker_request_sha256",
                    "nonce_commitment_sha256",
                    "candidate_process",
                }
                if event.get("provider") != "harness_owned_consumer_open_v1":
                    raise ContractError("first_open no usa provider harness-owned aprobado")
                validate_sha256(event.get("request_id"), context="first_open.request_id")
                protected = event.get("protected")
                if not isinstance(protected, list) or not protected:
                    raise ContractError("first_open no contiene inventario protegido")
                logical_ids: list[str] = []
                for item in protected:
                    if not isinstance(item, dict) or set(item) != {
                        "logical_id",
                        "role",
                        "relative_name",
                        "logical_bytes",
                        "sha256",
                    }:
                        raise ContractError("first_open.protected no tiene identidad exacta")
                    logical_id = item.get("logical_id")
                    role = item.get("role")
                    relative_name = item.get("relative_name")
                    size = item.get("logical_bytes")
                    logical_id = validate_sha256(
                        logical_id, context="first_open.protected.logical_id"
                    )
                    if role not in {"input", "bundle", "config"}:
                        raise ContractError("first_open.protected.role inválido")
                    if not isinstance(relative_name, str) or not relative_name:
                        raise ContractError("first_open.protected.relative_name inválido")
                    _require_non_negative_int(size, "first_open.protected.logical_bytes")
                    validate_sha256(item.get("sha256"), context="first_open.protected.sha256")
                    if logical_id != canonical_json_sha256(
                        {
                            "role": role,
                            "relative_name": relative_name,
                            "logical_bytes": size,
                            "sha256": item["sha256"],
                        }
                    ):
                        raise ContractError(
                            "first_open.protected.logical_id no deriva de su identidad"
                        )
                    logical_ids.append(logical_id)
                if logical_ids != sorted(set(logical_ids)):
                    raise ContractError("first_open.protected no está ordenado o tiene duplicados")
                validate_sha256(
                    event.get("broker_request_sha256"),
                    context="first_open.broker_request_sha256",
                )
                validate_sha256(
                    event.get("nonce_commitment_sha256"),
                    context="first_open.nonce_commitment_sha256",
                )
                process = event.get("candidate_process")
                if not isinstance(process, dict) or set(process) != {
                    "pid",
                    "creation_time_100ns",
                }:
                    raise ContractError("first_open.candidate_process no es exacto")
                for name in process:
                    value = process[name]
                    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                        raise ContractError(f"first_open.candidate_process.{name} inválido")
            elif kind == "first_byte":
                expected = {
                    "event",
                    "monotonic_ns",
                    "kind",
                    "provider",
                    "request_id",
                    "request_body_bytes",
                    "request_body_sha256",
                    "service_descriptor_sha256",
                    "endpoint_sha256",
                    "non_transforming",
                }
                if event.get("provider") != "harness_owned_candidate_http_ingress_v1":
                    raise ContractError("first_byte no usa ingress harness-owned aprobado")
                if not isinstance(event.get("request_id"), str) or not event["request_id"]:
                    raise ContractError("first_byte no contiene request_id")
                _require_non_negative_int(
                    event.get("request_body_bytes"), "first_byte.request_body_bytes"
                )
                validate_sha256(
                    event.get("request_body_sha256"),
                    context="first_byte.request_body_sha256",
                )
                validate_sha256(
                    event.get("service_descriptor_sha256"),
                    context="first_byte.service_descriptor_sha256",
                )
                validate_sha256(event.get("endpoint_sha256"), context="first_byte.endpoint_sha256")
                if event.get("non_transforming") is not True:
                    raise ContractError("first_byte no acredita ingress no transformante")
            else:
                raise ContractError("kind de first_open_or_byte fuera del catálogo")
        elif name == "flush_complete":
            expected = {"event", "monotonic_ns", "artifact_count", "logical_bytes"}
            _require_non_negative_int(event.get("artifact_count"), "artifact_count")
            _require_non_negative_int(event.get("logical_bytes"), "logical_bytes")
        elif name == "hash_complete":
            expected = {"event", "monotonic_ns", "artifact_count", "artifact_sha256"}
            _require_non_negative_int(event.get("artifact_count"), "artifact_count")
            hashes = event.get("artifact_sha256")
            if not isinstance(hashes, list):
                raise ContractError("hash_complete.artifact_sha256 no es lista")
            for digest in hashes:
                validate_sha256(digest, context="hash_complete.artifact_sha256[]")
            if event["artifact_count"] != len(hashes):
                raise ContractError("hash_complete no reconcilia cardinalidad de hashes")
        else:
            expected = {"event", "monotonic_ns", "path", "sha256"}
            if not isinstance(event.get("path"), str) or not event["path"]:
                raise ContractError("rename_complete no contiene path")
            validate_sha256(event.get("sha256"), context="rename_complete.sha256")
        if set(event) != expected:
            raise ContractError(f"{name}: campos boundary consumidor no son exactos")
    names = [str(event["event"]) for event in observed]
    if require_complete and names != list(CONSUMER_BOUNDARY_EVENTS):
        raise ContractError("frontera consumidor incompleta, duplicada o fuera de orden")
    expected_prefix = list(CONSUMER_BOUNDARY_EVENTS[: len(names)])
    if not require_complete and names != expected_prefix:
        raise ContractError("frontera consumidor parcial no es un prefijo válido")
    return observed


def reconstruct_boundary_sidecar(
    metadata: Mapping[str, Any], *, require_complete: bool = True
) -> list[dict[str, Any]]:
    """Reabre el JSONL de boundary y devuelve exclusivamente su reconstrucción validada."""
    return validate_consumer_boundary_events(
        verify_jsonl_sidecar(metadata), require_complete=require_complete
    )


def validate_boundary_sidecar_equality(
    metadata: Mapping[str, Any],
    evidence_events: Sequence[Mapping[str, Any]],
    *,
    require_complete: bool = True,
) -> list[dict[str, Any]]:
    """Prueba igualdad byte-semantics entre sidecar reabierto y eventos de evidencia."""
    reconstructed = reconstruct_boundary_sidecar(metadata, require_complete=require_complete)
    observed = [dict(event) for event in evidence_events]
    if reconstructed != observed:
        raise ContractError("boundary de evidencia no coincide con su sidecar reabierto")
    return reconstructed


def validate_filesystem_events(
    events: Sequence[Mapping[str, Any]],
    *,
    output_root: Path,
    manifest: Mapping[str, Any] | None,
    require_complete: bool,
) -> list[dict[str, Any]]:
    """Reconstruye el state machine de publicación y lo cruza con disco/manifiesto."""
    root = output_root.resolve()
    observed = [dict(event) for event in events]
    active: dict[Path, dict[str, Any]] = {}
    renamed: dict[str, dict[str, Any]] = {}
    last_hashed: Path | None = None
    last_ns = -1
    for index, event in enumerate(observed):
        operation = event.get("event")
        expected_fields = {"event", "monotonic_ns", "path"}
        if operation in {"hash", "rename"}:
            expected_fields |= {"logical_bytes", "sha256"}
        if operation not in FILESYSTEM_EVENT_OPERATIONS or set(event) != expected_fields:
            raise ContractError(f"filesystem[{index}] fuera del catálogo/schema cerrado")
        monotonic_ns = event["monotonic_ns"]
        if (
            isinstance(monotonic_ns, bool)
            or not isinstance(monotonic_ns, int)
            or monotonic_ns < last_ns
        ):
            raise ContractError("reloj monotónico inválido en filesystem events")
        last_ns = monotonic_ns
        raw_path = event["path"]
        if not isinstance(raw_path, str) or not raw_path:
            raise ContractError("filesystem event no contiene path")
        path = Path(raw_path).resolve()
        relative = _relative_under(path, root)
        if operation == "create":
            if not path.name.endswith(".partial") or path in active or active:
                raise ContractError("create no abre un parcial nuevo")
            active[path] = {"state": "created"}
            last_hashed = None
        elif operation == "flush":
            if active.get(path, {}).get("state") != "created":
                raise ContractError("flush no sigue exactamente a create")
            active[path]["state"] = "flushed"
            last_hashed = None
        elif operation == "hash":
            if active.get(path, {}).get("state") != "flushed":
                raise ContractError("hash no sigue exactamente a flush")
            size = _require_non_negative_int(event["logical_bytes"], "logical_bytes")
            digest = validate_sha256(event["sha256"], context="filesystem.hash.sha256")
            active[path].update({"state": "hashed", "logical_bytes": size, "sha256": digest})
            last_hashed = path
        elif operation == "rename":
            if path.name.endswith(".partial") or relative in renamed:
                raise ContractError("rename final inválido o duplicado")
            if last_hashed is None or active.get(last_hashed, {}).get("state") != "hashed":
                raise ContractError("rename no sigue a un parcial flush+hash")
            state = active.pop(last_hashed)
            size = _require_non_negative_int(event["logical_bytes"], "logical_bytes")
            digest = validate_sha256(event["sha256"], context="filesystem.rename.sha256")
            if size != state["logical_bytes"] or digest != state["sha256"]:
                raise ContractError("rename no preserva bytes/hash del parcial")
            renamed[relative] = {"logical_bytes": size, "sha256": digest}
            last_hashed = None
        else:
            if path not in active:
                raise ContractError("delete no corresponde a un parcial activo")
            active.pop(path)
            if last_hashed == path:
                last_hashed = None
    if active:
        raise ContractError("filesystem events dejan parciales activos")
    files = _regular_files_no_follow(root)
    partials = [path for path in files if path.name.endswith(".partial")]
    if partials:
        raise ContractError(f"filesystem conserva parciales: {partials!r}")
    actual = {
        path.relative_to(root).as_posix(): {
            "logical_bytes": path.stat().st_size,
            "sha256": sha256_file(path),
        }
        for path in files
    }
    if require_complete:
        if manifest is None:
            raise ContractError("filesystem completo exige manifiesto")
        expected = _manifest_paths(manifest)
        if set(actual) != expected or set(renamed) != expected:
            raise ContractError("filesystem events/inventario/manifiesto no son bidireccionales")
        if any(event["event"] == "delete" for event in observed):
            raise ContractError("filesystem success contiene cleanup de publicación fallida")
        for relative, identity in actual.items():
            if renamed[relative] != identity:
                raise ContractError(f"{relative}: rename no reconcilia con bytes finales")
        if (
            not observed
            or observed[-1]["event"] != "rename"
            or Path(str(observed[-1]["path"])).name != "manifest.json"
        ):
            raise ContractError("manifest.json no fue el último rename observado")
    elif manifest is not None:
        raise ContractError("filesystem parcial no puede declarar manifiesto publicable")
    elif set(actual) != set(renamed):
        raise ContractError("filesystem parcial conserva finales sin rename reconciliado")
    return observed


def reconstruct_filesystem_sidecar(
    metadata: Mapping[str, Any],
    *,
    output_root: Path,
    manifest: Mapping[str, Any] | None,
    require_complete: bool,
) -> list[dict[str, Any]]:
    """Reabre y valida causalmente el sidecar filesystem completo o interrumpido."""
    return validate_filesystem_events(
        verify_jsonl_sidecar(metadata),
        output_root=output_root,
        manifest=manifest,
        require_complete=require_complete,
    )


def validate_filesystem_sidecar_equality(
    metadata: Mapping[str, Any],
    evidence_events: Sequence[Mapping[str, Any]],
    *,
    output_root: Path,
    manifest: Mapping[str, Any] | None,
    require_complete: bool,
) -> list[dict[str, Any]]:
    """Prueba igualdad entre sidecar filesystem reconstruido y su copia en evidencia."""
    reconstructed = reconstruct_filesystem_sidecar(
        metadata,
        output_root=output_root,
        manifest=manifest,
        require_complete=require_complete,
    )
    if reconstructed != [dict(event) for event in evidence_events]:
        raise ContractError("filesystem de evidencia no coincide con su sidecar reabierto")
    return reconstructed


def reconstruct_consumer_sidecars(
    *,
    boundary_metadata: Mapping[str, Any],
    filesystem_metadata: Mapping[str, Any],
    output_root: Path,
    manifest: Mapping[str, Any] | None,
    require_complete: bool,
) -> dict[str, list[dict[str, Any]]]:
    """Reconstruye en una sola operación ambas fronteras causales del consumidor."""
    reconstructed = {
        "boundary_events": reconstruct_boundary_sidecar(
            boundary_metadata, require_complete=require_complete
        ),
        "filesystem_events": reconstruct_filesystem_sidecar(
            filesystem_metadata,
            output_root=output_root,
            manifest=manifest,
            require_complete=require_complete,
        ),
    }
    if require_complete:
        if manifest is None:
            raise ContractError("frontera consumidora completa exige manifiesto")
        _validate_boundary_against_manifest(
            reconstructed["boundary_events"], manifest=manifest, output_root=output_root
        )
    return reconstructed


def validate_consumer_sidecars_equality(
    *,
    boundary_metadata: Mapping[str, Any],
    filesystem_metadata: Mapping[str, Any],
    evidence: Mapping[str, Any],
    output_root: Path,
    manifest: Mapping[str, Any] | None,
    require_complete: bool,
) -> dict[str, list[dict[str, Any]]]:
    """Exige igualdad exacta entre reconstrucción de sidecars y objeto de evidencia."""
    if set(evidence) != {"boundary_events", "filesystem_events"}:
        raise ContractError("evidencia de sidecars consumidores no tiene campos exactos")
    reconstructed = reconstruct_consumer_sidecars(
        boundary_metadata=boundary_metadata,
        filesystem_metadata=filesystem_metadata,
        output_root=output_root,
        manifest=manifest,
        require_complete=require_complete,
    )
    observed_boundary = evidence.get("boundary_events")
    observed_filesystem = evidence.get("filesystem_events")
    if not isinstance(observed_boundary, list) or not isinstance(observed_filesystem, list):
        raise ContractError("evidencia de sidecars consumidores no contiene listas")
    observed = {
        "boundary_events": [dict(event) for event in observed_boundary if isinstance(event, dict)],
        "filesystem_events": [
            dict(event) for event in observed_filesystem if isinstance(event, dict)
        ],
    }
    if len(observed["boundary_events"]) != len(observed_boundary) or len(
        observed["filesystem_events"]
    ) != len(observed_filesystem):
        raise ContractError("evidencia de sidecars consumidores contiene no-objetos")
    if reconstructed != observed:
        raise ContractError("evidencia consumidora no coincide con ambos sidecars reabiertos")
    return reconstructed


def _require_non_negative_int(value: Any, context: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ContractError(f"{context}: entero no negativo inválido")
    return value


def _validate_boundary_against_manifest(
    events: Sequence[Mapping[str, Any]], *, manifest: Mapping[str, Any], output_root: Path
) -> None:
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, list) or any(not isinstance(item, dict) for item in artifacts):
        raise ContractError("manifiesto inválido al reconciliar boundary")
    by_name = {str(event["event"]): event for event in events}
    flush = by_name["flush_complete"]
    hashes = by_name["hash_complete"]
    rename = by_name["rename_complete"]
    expected_count = len(artifacts)
    expected_logical = sum(int(item["logical_bytes"]) for item in artifacts)
    expected_hashes = [str(item["sha256"]) for item in artifacts]
    if flush["artifact_count"] != expected_count or flush["logical_bytes"] != expected_logical:
        raise ContractError("flush_complete no deriva del manifiesto")
    if hashes["artifact_count"] != expected_count or hashes["artifact_sha256"] != expected_hashes:
        raise ContractError("hash_complete no deriva del manifiesto ordenado")
    manifest_path = (output_root.resolve() / "manifest.json").resolve()
    if Path(str(rename["path"])).resolve() != manifest_path or not manifest_path.is_file():
        raise ContractError("rename_complete no apunta al manifiesto final")
    if rename["sha256"] != sha256_file(manifest_path):
        raise ContractError("rename_complete no liga el hash del manifiesto final")


def _relative_under(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError as exc:
        raise ContractError(f"filesystem event escapa de outputs: {path}") from exc


def _manifest_paths(manifest: Mapping[str, Any]) -> set[str]:
    if not isinstance(manifest.get("artifacts"), list):
        raise ContractError("manifiesto no contiene artifacts")
    paths = {"manifest.json"}
    for raw in manifest["artifacts"]:
        if not isinstance(raw, dict) or not isinstance(raw.get("relative_path"), str):
            raise ContractError("artifact inválido al reconciliar filesystem")
        paths.add(str(raw["relative_path"]))
        count_evidence = raw.get("count_evidence")
        if not isinstance(count_evidence, dict):
            raise ContractError("artifact no contiene count_evidence")
        sidecar = count_evidence.get("sidecar")
        if sidecar is not None:
            if not isinstance(sidecar, dict) or not isinstance(sidecar.get("relative_path"), str):
                raise ContractError("sidecar de conteo inválido")
            paths.add(str(sidecar["relative_path"]))
    return paths


class ConsumerPublisher:
    """Publica outputs, hashea todo y deja el manifiesto como último rename."""

    def __init__(self, output_root: Path, boundary: ConsumerBoundary) -> None:
        self.boundary = boundary
        self.publisher = AtomicOutputPublisher(
            output_root,
            event_callback=lambda operation, path: self.boundary.filesystem_event(operation, path),
        )

    def publish(
        self,
        relative_path: str,
        identity: str,
        ordinal: int,
        payload: bytes,
        *,
        output_format: str | None = None,
        record_count: int | None = None,
    ) -> None:
        """Publica un output y deriva su conteo, salvo bin atestiguado por sidecar."""
        self.publisher.publish(
            relative_path,
            identity,
            ordinal,
            payload,
            output_format=output_format,
            record_count=record_count,
        )

    def publish_file(
        self,
        relative_path: str,
        identity: str,
        ordinal: int,
        source_path: Path,
        *,
        output_format: str | None = None,
        record_count: int | None = None,
    ) -> None:
        """Publica un output grande por bloques y conserva orden/conteo."""
        self.publisher.publish_file(
            relative_path,
            identity,
            ordinal,
            source_path,
            output_format=output_format,
            record_count=record_count,
        )

    def finalize(self) -> dict[str, Any]:
        """Publica el manifiesto derivado sólo de los artifacts reabiertos."""
        artifacts = list(self.publisher.artifacts)
        self.boundary.event(
            "flush_complete",
            artifact_count=len(artifacts),
            logical_bytes=sum(int(item["logical_bytes"]) for item in artifacts),
        )
        self.boundary.event(
            "hash_complete",
            artifact_count=len(artifacts),
            artifact_sha256=[str(item["sha256"]) for item in artifacts],
        )
        result = self.publisher.finalize()
        manifest_path = self.publisher.output_root / "manifest.json"
        self.boundary.event(
            "rename_complete", path=str(manifest_path), sha256=sha256_file(manifest_path)
        )
        return result
