"""Contratos cerrados y validadores del arnés H9R.

Los valores de este módulo son hipótesis de medición aprobadas, no perfiles finales ni copy de
capacidad. Los validadores son deliberadamente fail-closed: una identidad, clasificación o campo
de autoridad nuevo exige revisar el schema antes de poder producir evidencia.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import stat
import statistics
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final, cast

MIB: Final = 1024**2
GIB: Final = 1024**3

ATTEMPT_SCHEMA_VERSION: Final = "nikodym.readiness.h9r.calibration.v1"
AGGREGATE_SCHEMA_VERSION: Final = "nikodym.readiness.h9r.calibration.aggregate.v1"
AUTHORIZATION_SCHEMA_VERSION: Final = "nikodym.readiness.h9r.authorization.v1"
AUTHORIZATION_CONSUMPTION_SCHEMA_VERSION: Final = (
    "nikodym.readiness.h9r.authorization-consumption.v1"
)
HARNESS_TEST_SCHEMA_VERSION: Final = "nikodym.readiness.h9r.harness-test.v1"
PROTOCOL_VERSION: Final = "nikodym.readiness.h9r.supervisor.v1"
CONFIG_SCHEMA_VERSION: Final = "nikodym.readiness.h9r.config.v1"
SCHEDULE_SCHEMA_VERSION: Final = "nikodym.readiness.h9r.schedule.v1"
PREFLIGHT_REJECTION_SCHEMA_VERSION: Final = "nikodym.readiness.h9r.preflight-rejection.v1"
PRE_START_FAILURE_SCHEMA_VERSION: Final = "nikodym.readiness.h9r.pre-start-failure.v1"
POST_START_FAILURE_SCHEMA_VERSION: Final = "nikodym.readiness.h9r.post-start-failure.v1"
INTERNAL_AUTHORIZATION_GATE_SCHEMA_VERSION: Final = (
    "nikodym.readiness.h9r.internal-authorization-gate.v1"
)
INTERNAL_AUTHORIZATION_PRECOMMIT_SCHEMA_VERSION: Final = (
    "nikodym.readiness.h9r.internal-authorization-precommit.v1"
)
INTERNAL_AUTHORIZATION_RELEASE_SCHEMA_VERSION: Final = (
    "nikodym.readiness.h9r.internal-authorization-release.v1"
)
INTERNAL_AUTHORIZATION_ROLES: Final = ("worker", "adapter", "candidate", "ui-client")
ATTEMPT_SIDECAR_SPECS: Final = (
    ("resources", "jsonl"),
    ("boundary", "jsonl"),
    ("filesystem", "jsonl"),
    ("native_pools", "jsonl"),
    ("adapter_audit", "jsonl"),
    ("ui_first_byte", "jsonl"),
    ("worker_stdout", "binary"),
    ("worker_stderr", "binary"),
    ("client_boundary", "jsonl"),
    ("client_stdout", "binary"),
    ("client_stderr", "binary"),
    ("candidate_stdout", "binary"),
    ("candidate_stderr", "binary"),
    ("candidate_controller_stdout", "binary"),
    ("candidate_controller_stderr", "binary"),
)
ATTEMPT_SIDECAR_NAMES: Final = tuple(name for name, _format in ATTEMPT_SIDECAR_SPECS)
ATTEMPT_SIDECAR_FILENAMES: Final = {
    "resources": "resources.jsonl",
    "boundary": "boundary.jsonl",
    "filesystem": "filesystem-events.jsonl",
    "native_pools": "native-pools.jsonl",
    "adapter_audit": "adapter-audit.jsonl",
    "ui_first_byte": "ui-first-byte.jsonl",
    "worker_stdout": "worker.stdout.bin",
    "worker_stderr": "worker.stderr.bin",
    "client_boundary": "client-boundary.jsonl",
    "client_stdout": "client.stdout.bin",
    "client_stderr": "client.stderr.bin",
    "candidate_stdout": "candidate.stdout.bin",
    "candidate_stderr": "candidate.stderr.bin",
    "candidate_controller_stdout": "candidate-controller.stdout.bin",
    "candidate_controller_stderr": "candidate-controller.stderr.bin",
}

CAPS: Final[dict[str, int]] = {
    "C4": 4_294_967_296,
    "C5": 5_368_709_120,
    "C6": 6_442_450_944,
}
GEOMETRY_IDS: Final = ("G-", "G0", "G+")
MAX_LOGICAL_CPUS: Final = 4
SAMPLE_INTERVAL_SECONDS: Final = 0.250
MAX_SAMPLE_GAP_SECONDS: Final = 2.0
PREFLIGHT_DEADLINE_SECONDS: Final = 300.0
HANDSHAKE_DEADLINE_SECONDS: Final = 60.0
PREFLIGHT_MIN_AVAILABLE_PHYSICAL_BYTES: Final = 2 * GIB
PREFLIGHT_MIN_COMMIT_HEADROOM_BYTES: Final = 2 * GIB
RUN_MIN_AVAILABLE_PHYSICAL_BYTES: Final = 1 * GIB
RUN_MIN_COMMIT_HEADROOM_BYTES: Final = 1 * GIB
RUN_MIN_DISK_FREE_BYTES: Final = 1 * GIB
PREFLIGHT_MIN_DISK_FREE_BYTES: Final = 4 * GIB
SCREENING_ATTEMPTS: Final = 3
CONFIRMATION_ATTEMPTS_TOTAL: Final = 10
CONFIRMATION_EXTENSION_ATTEMPTS: Final = CONFIRMATION_ATTEMPTS_TOTAL - SCREENING_ATTEMPTS
MAX_RELATIVE_MAD: Final = 0.20
CAP_HEADROOM_RATIO: Final = 0.85

CLASSIFICATIONS: Final = (
    "success",
    "preflight_rejected",
    "limits_not_applied",
    "job_memory_limit",
    "watchdog_deadline",
    "safety_abort_system_memory",
    "safety_abort_disk",
    "host_contamination",
    "host_oom",
    "cancelled",
    "consumer_error",
    "supervisor_error",
    "invariant_failure",
    "orphan_detected",
    "evidence_incomplete",
)
PRE_START_FAILURE_CLASSIFICATIONS: Final = (
    "limits_not_applied",
    "watchdog_deadline",
    "safety_abort_system_memory",
    "safety_abort_disk",
    "host_contamination",
    "host_oom",
    "cancelled",
    "supervisor_error",
    "invariant_failure",
    "orphan_detected",
    "evidence_incomplete",
)


@dataclass(frozen=True)
class FlowSpec:
    """Hipótesis de una frontera consumidora, sin hashes ni autorización START."""

    wave: str
    flow_id: str
    step: str
    workload_deadline_seconds: float
    geometries: Mapping[str, Mapping[str, int | str]]
    outputs: tuple[str, ...]

    @property
    def key(self) -> tuple[str, str]:
        """Devuelve la identidad estable ``flow_id x flow_step``."""
        return (self.flow_id, self.step)

    @property
    def expected_output_identities(self) -> tuple[str, ...]:
        """Enumera outputs de negocio; el manifiesto final es el contenedor, no otro output."""
        return tuple(identity for identity in self.outputs if identity != "manifest")


def _g(**dimensions: int | str) -> Mapping[str, int | str]:
    return dimensions


FLOW_SPECS: Final = (
    FlowSpec(
        "W1",
        "F-SCORE-TRAIN",
        "train",
        7_200.0,
        {
            "G-": _g(rows=100_000, variables=50, max_cardinality=10_000),
            "G0": _g(rows=250_000, variables=75, max_cardinality=25_000),
            "G+": _g(rows=500_000, variables=100, max_cardinality=50_000),
        },
        ("bundle", "rules", "hashes", "lineage", "manifest"),
    ),
    FlowSpec(
        "W1",
        "F-SCORE-APPLY",
        "apply",
        7_200.0,
        {"G-": _g(rows=100_000), "G0": _g(rows=250_000), "G+": _g(rows=500_000)},
        ("application", "woe", "trace", "summary", "manifest"),
    ),
    FlowSpec(
        "W1",
        "F-SCORE-BATCH",
        "batch",
        7_200.0,
        {"G-": _g(rows=250_000), "G0": _g(rows=500_000), "G+": _g(rows=1_000_000)},
        ("application", "woe", "trace", "summary", "manifest"),
    ),
    FlowSpec(
        "W1",
        "F-UI",
        "run",
        1_800.0,
        {
            "G-": _g(payload_bytes=16 * MIB),
            "G0": _g(payload_bytes=32 * MIB),
            "G+": _g(payload_bytes=64 * MIB),
        },
        ("receipt", "execution", "first_verifiable_page", "flow_artifacts", "manifest"),
    ),
    FlowSpec(
        "W2",
        "F-LGD-BASE",
        "run",
        3_600.0,
        {
            "G-": _g(operations=250_000),
            "G0": _g(operations=500_000),
            "G+": _g(operations=1_000_000),
        },
        ("lgd_by_operation", "provenance", "manifest"),
    ),
    FlowSpec(
        "W2",
        "F-LGD-OOS",
        "fit",
        7_200.0,
        {
            "G-": _g(operations=100_000),
            "G0": _g(operations=250_000),
            "G+": _g(operations=500_000),
        },
        ("modeled_bundle", "raw_covariates", "hashes", "lineage", "manifest"),
    ),
    FlowSpec(
        "W2",
        "F-LGD-OOS",
        "apply",
        7_200.0,
        {
            "G-": _g(operations=250_000),
            "G0": _g(operations=500_000),
            "G+": _g(operations=1_000_000),
        },
        ("lgd_oos_by_operation", "provenance", "hashes", "manifest"),
    ),
    FlowSpec(
        "W2",
        "F-EAD-BASE",
        "run",
        3_600.0,
        {
            "G-": _g(operations=250_000),
            "G0": _g(operations=500_000),
            "G+": _g(operations=1_000_000),
        },
        ("ead_by_operation", "reconciliation", "manifest"),
    ),
    FlowSpec(
        "W2",
        "F-EAD-T",
        "run",
        3_600.0,
        {
            "G-": _g(operations=25_000, periods=60, expanded_rows=1_500_000),
            "G0": _g(operations=50_000, periods=60, expanded_rows=3_000_000),
            "G+": _g(operations=100_000, periods=60, expanded_rows=6_000_000),
        },
        ("operation_period_detail", "movements", "reconciliation", "manifest"),
    ),
    FlowSpec(
        "W2",
        "F-CMF-REFERENCE",
        "run",
        3_600.0,
        {
            "G-": _g(operations=100_000),
            "G0": _g(operations=250_000),
            "G+": _g(operations=500_000),
        },
        ("frozen_reference_outputs", "report", "manifest"),
    ),
    FlowSpec(
        "W3",
        "F-PD-SURVIVAL",
        "run",
        7_200.0,
        {
            "G-": _g(observations=250_000),
            "G0": _g(observations=500_000),
            "G+": _g(observations=1_000_000),
        },
        ("bundle", "term_structure", "basis", "unit", "lineage", "manifest"),
    ),
    FlowSpec(
        "W3",
        "F-PD-MARKOV",
        "run",
        7_200.0,
        {
            "G-": _g(transitions=250_000),
            "G0": _g(transitions=500_000),
            "G+": _g(transitions=1_000_000),
        },
        ("segmented_matrices", "curves", "reconciliation", "manifest"),
    ),
    FlowSpec(
        "W4",
        "F-IFRS9",
        "run",
        10_800.0,
        {
            "G-": _g(operations=25_000, periods=60, scenarios=3, expanded_rows=4_500_000),
            "G0": _g(operations=50_000, periods=60, scenarios=3, expanded_rows=9_000_000),
            "G+": _g(operations=100_000, periods=60, scenarios=3, expanded_rows=18_000_000),
        },
        ("staging", "detail", "summary", "scenarios", "manifest"),
    ),
    FlowSpec(
        "W4",
        "F-FORWARD-IFRS9",
        "run",
        10_800.0,
        {
            "G-": _g(operations=10_000, periods=60, scenarios=3, expanded_rows=1_800_000),
            "G0": _g(operations=25_000, periods=60, scenarios=3, expanded_rows=4_500_000),
            "G+": _g(operations=50_000, periods=60, scenarios=3, expanded_rows=9_000_000),
        },
        ("macro", "basis", "staging", "detail", "reconciliation", "manifest"),
    ),
    FlowSpec(
        "W5",
        "F-STRESS-ECON",
        "run",
        10_800.0,
        {
            "G-": _g(operations=5_000, periods=60, scenarios=3),
            "G0": _g(operations=10_000, periods=60, scenarios=3),
            "G+": _g(operations=25_000, periods=60, scenarios=3),
        },
        ("baseline", "three_functional_shocks", "reconciliation", "manifest"),
    ),
)

FLOW_BY_KEY: Final = {spec.key: spec for spec in FLOW_SPECS}
ADAPTER_IDS: Final = {
    spec.key: f"nikodym.h9r.{spec.flow_id[2:].lower().replace('-', '_')}.{spec.step}.v1"
    for spec in FLOW_SPECS
}

GEOMETRY_DERIVATION_ALGORITHMS: Final = {
    "rows": "input-data-record-count.v1",
    "operations": "input-data-record-count.v1",
    "observations": "input-data-record-count.v1",
    "transitions": "input-data-record-count.v1",
    "variables": "fixture-schema-feature-columns.v1",
    "max_cardinality": "input-data-max-distinct.v1",
    "periods": "input-period-cardinality.v1",
    "scenarios": "fixture-catalog-scenario-cardinality.v1",
    "expanded_rows": "dimensions-product.v1",
    "payload_bytes": "ui-request-body-bytes.v1",
}

ATTEMPT_UNIT_FIELDS: Final = (
    "candidate_manifest_sha256",
    "flow_id",
    "flow_step",
    "fixture_manifest_sha256",
    "config_hash",
    "geometry_id",
    "cap_id",
    "attempt_ordinal",
)
SCHEDULE_CELL_FIELDS: Final = ATTEMPT_UNIT_FIELDS[:-1]
SCHEDULE_PHASE_ATTEMPTS: Final = {
    "screening": SCREENING_ATTEMPTS,
    "confirmation": CONFIRMATION_EXTENSION_ATTEMPTS,
    "bracket_following": SCREENING_ATTEMPTS,
}

# Ninguna clave humana para START ha sido aprobada. Este valor durable se completa únicamente por
# una decisión humana posterior; ``None`` mantiene todo ``calibration-start`` cerrado aunque el
# llamador aporte una clave y una firma criptográficamente válidas fabricadas por él mismo.
CALIBRATION_AUTHORITY_PUBLIC_KEY_SHA256: Final[str | None] = None
ATTEMPT_TOP_LEVEL_OBJECTS: Final = (
    "identity",
    "authority",
    "authorization_consumption",
    "candidate",
    "tooling",
    "fixture",
    "environment",
    "limits",
    "boundary",
    "resources",
    "outputs",
    "termination",
    "gates",
    "result",
)


class ContractError(ValueError):
    """Indica evidencia o autoridad que no satisface el contrato cerrado."""


def canonical_json_bytes(value: Any) -> bytes:
    """Serializa JSON UTF-8 canónico, sin valores no finitos."""
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    """Calcula SHA-256 hexadecimal en minúsculas."""
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path, *, deadline_monotonic: float | None = None) -> str:
    """Calcula SHA-256 por bloques sin materializar el archivo completo."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(MIB), b""):
            if deadline_monotonic is not None and time.monotonic() > deadline_monotonic:
                raise ContractError("preflight_rejected: preflight excedió 300 s durante hashing")
            digest.update(block)
    return digest.hexdigest()


def canonical_json_sha256(value: Any) -> str:
    """Firma el JSON canónico de un objeto."""
    return sha256_bytes(canonical_json_bytes(value))


def read_json_object(path: Path) -> dict[str, Any]:
    """Lee un objeto JSON y rechaza arrays o escalares."""
    raw: Any = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ContractError(f"JSON no es un objeto: {path}")
    return cast(dict[str, Any], raw)


def _require_exact_keys(value: Mapping[str, Any], expected: Sequence[str], *, context: str) -> None:
    observed = set(value)
    required = set(expected)
    if observed != required:
        missing = sorted(required - observed)
        extra = sorted(observed - required)
        raise ContractError(f"{context}: campos faltantes={missing!r}, extra={extra!r}")


def _require_object(value: Any, *, context: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ContractError(f"{context}: se esperaba objeto")
    return cast(dict[str, Any], value)


def _require_non_negative_int(value: Any, *, context: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ContractError(f"{context}: se esperaba entero no negativo")
    return value


def _require_bool(value: Any, *, context: str) -> bool:
    if not isinstance(value, bool):
        raise ContractError(f"{context}: se esperaba booleano")
    return value


def _require_text(value: Any, *, context: str, allow_empty: bool = False) -> str:
    if not isinstance(value, str) or (not allow_empty and not value):
        raise ContractError(
            f"{context}: se esperaba texto{' (puede ser vacío)' if allow_empty else ''}"
        )
    return value


def validate_sha256(value: Any, *, context: str) -> str:
    """Valida un digest real, canónico lowercase, y veta placeholders obvios."""
    if not isinstance(value, str) or len(value) != 64:
        raise ContractError(f"{context}: SHA-256 debe tener 64 hexadecimales")
    if any(character not in "0123456789abcdef" for character in value):
        raise ContractError(f"{context}: SHA-256 no es hexadecimal lowercase canónico")
    if value == "0" * 64 or value == "f" * 64:
        raise ContractError(f"{context}: SHA-256 placeholder prohibido")
    return value


def _validate_git_sha(value: Any, *, context: str) -> str:
    """Valida SHA Git de 40/64 hex lowercase sin aceptar placeholders."""
    source_sha = _require_text(value, context=context)
    if (
        len(source_sha) not in {40, 64}
        or any(character not in "0123456789abcdef" for character in source_sha)
        or source_sha in {"0" * len(source_sha), "f" * len(source_sha)}
    ):
        raise ContractError(f"{context}: no es SHA Git lowercase canónico")
    return source_sha


def flow_spec(flow_id: str, flow_step: str) -> FlowSpec:
    """Resuelve una frontera cerrada o falla."""
    try:
        return FLOW_BY_KEY[(flow_id, flow_step)]
    except KeyError as exc:
        raise ContractError(f"flow/step fuera del catálogo: {flow_id}/{flow_step}") from exc


def validate_attempt_unit(value: Mapping[str, Any]) -> dict[str, Any]:
    """Valida la identidad mínima expandida de una unidad START."""
    _require_exact_keys(value, ATTEMPT_UNIT_FIELDS, context="unidad START")
    normalized = dict(value)
    normalized["candidate_manifest_sha256"] = validate_sha256(
        value["candidate_manifest_sha256"], context="candidate_manifest_sha256"
    )
    normalized["fixture_manifest_sha256"] = validate_sha256(
        value["fixture_manifest_sha256"], context="fixture_manifest_sha256"
    )
    normalized["config_hash"] = validate_sha256(value["config_hash"], context="config_hash")
    flow_id = value["flow_id"]
    flow_step = value["flow_step"]
    if not isinstance(flow_id, str) or not isinstance(flow_step, str):
        raise ContractError("flow_id/flow_step deben ser texto")
    spec = flow_spec(flow_id, flow_step)
    geometry_id = value["geometry_id"]
    if geometry_id not in spec.geometries:
        raise ContractError(f"geometry_id inválido: {geometry_id!r}")
    cap_id = value["cap_id"]
    if cap_id not in CAPS:
        raise ContractError(f"cap_id inválido: {cap_id!r}")
    ordinal = value["attempt_ordinal"]
    if isinstance(ordinal, bool) or not isinstance(ordinal, int) or ordinal < 1:
        raise ContractError("attempt_ordinal debe ser entero positivo")
    return normalized


def attempt_id(unit: Mapping[str, Any]) -> str:
    """Deriva la identidad inmutable del intento desde la unidad completa."""
    return canonical_json_sha256(validate_attempt_unit(unit))


def authorization_consumption_path_digest(path: Path) -> str:
    """Liga una autorización one-shot a su ruta absoluta lexical, sin seguir reparse points."""
    normalized = os.path.abspath(os.fspath(path)).replace("\\", "/").casefold()
    return sha256_bytes(normalized.encode("utf-8"))


def authorization_statement(
    unit: Mapping[str, Any],
    *,
    authorization_id: str,
    authorization_consumption_path_sha256: str,
    tooling_sha256: str,
    schedule_sha256: str,
    schedule_position: int,
    scope: str,
) -> bytes:
    """Construye el único texto estructurado que puede autorizar o probar una unidad."""
    if scope not in {"calibration-start", "harness-test-only"}:
        raise ContractError(f"scope de autorización desconocido: {scope}")
    normalized = validate_attempt_unit(unit)
    normalized_authorization_id = validate_sha256(authorization_id, context="authorization_id")
    consumption_path_sha256 = validate_sha256(
        authorization_consumption_path_sha256,
        context="authorization_consumption_path_sha256",
    )
    tooling = validate_sha256(tooling_sha256, context="tooling_sha256")
    schedule = validate_sha256(schedule_sha256, context="schedule_sha256")
    if (
        isinstance(schedule_position, bool)
        or not isinstance(schedule_position, int)
        or schedule_position < 0
    ):
        raise ContractError("schedule_position inválida")
    start_authorized = scope == "calibration-start"
    lines = (
        "NIKODYM-H9R-AUTHORIZATION-V1",
        f"scope={scope}",
        f"start_authorized={'true' if start_authorized else 'false'}",
        f"authorization_id={normalized_authorization_id}",
        f"authorization_consumption_path_sha256={consumption_path_sha256}",
        f"attempt_id={attempt_id(normalized)}",
        f"tooling_sha256={tooling}",
        f"schedule_sha256={schedule}",
        f"schedule_position={schedule_position}",
        f"unit={canonical_json_bytes(normalized).decode('utf-8')}",
    )
    return ("\n".join(lines) + "\n").encode("utf-8")


def authority_signing_bytes(authority: Mapping[str, Any]) -> bytes:
    """Serializa el acto que firma la persona, excluyendo únicamente la firma misma."""
    unsigned = dict(authority)
    if "signature_ed25519" not in unsigned:
        raise ContractError("autoridad sin campo signature_ed25519")
    unsigned.pop("signature_ed25519")
    return canonical_json_bytes(unsigned)


def _trusted_authority_key_identity_from_bytes(payload: bytes, *, context: str) -> tuple[Any, str]:
    """Parsea una clave Ed25519 desde la misma captura que se atesta."""
    try:
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    except ImportError as exc:  # pragma: no cover - el entorno de desarrollo la declara.
        raise ContractError(
            "cryptography no está disponible para verificar autoridad Ed25519"
        ) from exc
    try:
        key = serialization.load_pem_public_key(payload)
    except (TypeError, ValueError) as exc:
        raise ContractError(f"{context}: trust anchor Ed25519 PEM inválido") from exc
    if not isinstance(key, Ed25519PublicKey):
        raise ContractError(f"{context}: trust anchor no es una clave pública Ed25519")
    raw = key.public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return key, sha256_bytes(raw)


def trusted_authority_key_identity(path: Path) -> tuple[Any, str]:
    """Carga una clave Ed25519 mediante una única captura descriptor-bound."""
    payload = _read_descriptor_bound_regular_file(
        path=path,
        context="trust anchor Ed25519",
        reject_hardlinks=True,
    )
    return _trusted_authority_key_identity_from_bytes(payload, context="trust anchor Ed25519")


def verify_authority_signature(
    authority: Mapping[str, Any], *, trusted_authority_public_key_path: Path
) -> str:
    """Distingue aprobación humana de hashes autofabricados con un trust anchor externo."""
    key, key_sha256 = trusted_authority_key_identity(trusted_authority_public_key_path)
    declared_key = validate_sha256(
        authority.get("signer_public_key_sha256"), context="signer_public_key_sha256"
    )
    if declared_key != key_sha256:
        raise ContractError("firmante de autoridad no coincide con el trust anchor externo")
    scope = authority.get("scope")
    if scope == "calibration-start":
        if CALIBRATION_AUTHORITY_PUBLIC_KEY_SHA256 is None:
            raise ContractError(
                "calibration-start cerrado: no existe fingerprint humano durable aprobado"
            )
        if key_sha256 != CALIBRATION_AUTHORITY_PUBLIC_KEY_SHA256:
            raise ContractError("calibration-start no coincide con el fingerprint humano durable")
    elif scope != "harness-test-only":
        raise ContractError("scope de autoridad desconocido para verificar firma")
    signature_hex = authority.get("signature_ed25519")
    if (
        not isinstance(signature_hex, str)
        or len(signature_hex) != 128
        or any(character not in "0123456789abcdef" for character in signature_hex)
        or signature_hex in {"0" * 128, "f" * 128}
    ):
        raise ContractError("signature_ed25519 debe contener 64 bytes hex no-placeholder")
    try:
        key.verify(bytes.fromhex(signature_hex), authority_signing_bytes(authority))
    except Exception as exc:
        # ``InvalidSignature`` no se importa a nivel módulo para mantener la dependencia confinada
        # al arnés de desarrollo; cualquier otra falla criptográfica también debe cerrar la puerta.
        raise ContractError("firma Ed25519 de autoridad inválida") from exc
    return key_sha256


def validate_authority(
    authority: Mapping[str, Any],
    unit: Mapping[str, Any],
    *,
    document_hashes: Mapping[str, str],
    tooling_sha256: str,
    schedule_sha256: str,
    schedule_position: int,
    trusted_authority_public_key_path: Path,
) -> dict[str, Any]:
    """Exige autoridad humana exacta para una sola unidad y documentos vivos.

    La mera presencia de un archivo no basta: el texto autorizado, la unidad, su ``attempt_id`` y
    los digests del protocolo/SDD/enmienda deben reconciliar.
    """
    expected_fields = (
        "schema_version",
        "scope",
        "start_authorized",
        "authorization_id",
        "authorization_consumption_path_sha256",
        "authorized_unit",
        "attempt_id",
        "authorization_text_sha256",
        "document_sha256",
        "tooling_sha256",
        "schedule_sha256",
        "schedule_position",
        "signer_public_key_sha256",
        "signature_ed25519",
    )
    _require_exact_keys(authority, expected_fields, context="autoridad")
    if authority["schema_version"] != AUTHORIZATION_SCHEMA_VERSION:
        raise ContractError("schema de autorización inesperado")
    verify_authority_signature(
        authority, trusted_authority_public_key_path=trusted_authority_public_key_path
    )
    scope = authority["scope"]
    if scope not in {"calibration-start", "harness-test-only"}:
        raise ContractError("scope de autorización inesperado")
    expected_start = scope == "calibration-start"
    if authority["start_authorized"] is not expected_start:
        raise ContractError("start_authorized no coincide con el scope")
    normalized_unit = validate_attempt_unit(unit)
    normalized_authorization_id = validate_sha256(
        authority["authorization_id"], context="authorization_id"
    )
    consumption_path_sha256 = validate_sha256(
        authority["authorization_consumption_path_sha256"],
        context="authorization_consumption_path_sha256",
    )
    authorized_unit = validate_attempt_unit(
        _require_object(authority["authorized_unit"], context="authorized_unit")
    )
    if authorized_unit != normalized_unit:
        raise ContractError("la unidad autorizada no coincide byte a byte")
    expected_attempt_id = attempt_id(normalized_unit)
    if authority["attempt_id"] != expected_attempt_id:
        raise ContractError("attempt_id de autoridad no reconcilia")
    observed_authorization_text = validate_sha256(
        authority["authorization_text_sha256"], context="authorization_text_sha256"
    )
    expected_tooling = validate_sha256(tooling_sha256, context="tooling vivo")
    observed_tooling = validate_sha256(authority["tooling_sha256"], context="tooling autorizado")
    if observed_tooling != expected_tooling:
        raise ContractError("digest del tooling autorizado no reconcilia")
    expected_schedule = validate_sha256(schedule_sha256, context="schedule vivo")
    observed_schedule = validate_sha256(authority["schedule_sha256"], context="schedule autorizado")
    if (
        observed_schedule != expected_schedule
        or authority["schedule_position"] != schedule_position
    ):
        raise ContractError("schedule/posición autorizados no reconcilian")
    expected_authorization_text = authorization_statement(
        normalized_unit,
        authorization_id=normalized_authorization_id,
        authorization_consumption_path_sha256=consumption_path_sha256,
        tooling_sha256=expected_tooling,
        schedule_sha256=expected_schedule,
        schedule_position=schedule_position,
        scope=str(scope),
    )
    if observed_authorization_text != sha256_bytes(expected_authorization_text):
        raise ContractError("authorization_text_sha256 no deriva del acto one-shot exacto")
    observed_documents = _require_object(authority["document_sha256"], context="document_sha256")
    if set(observed_documents) != set(document_hashes):
        raise ContractError("el censo de documentos autorizados no coincide")
    for name, expected_hash in document_hashes.items():
        expected = validate_sha256(expected_hash, context=f"documento vivo {name}")
        observed = validate_sha256(observed_documents[name], context=f"documento autorizado {name}")
        if observed != expected:
            raise ContractError(f"digest documental no reconcilia: {name}")
    return dict(authority)


def validate_schedule(schedule: Mapping[str, Any], unit: Mapping[str, Any]) -> tuple[str, int]:
    """Deriva una permutación reproducible de celdas/ordinales y ubica la unidad actual."""
    phase = schedule.get("phase")
    phase_link_fields = (
        ("screening_schedule_sha256", "promoted_screening_attempt_ids")
        if phase == "confirmation"
        else ()
    )
    _require_exact_keys(
        schedule,
        (
            "schema_version",
            "phase",
            "permutation_algorithm",
            "permutation_seed_sha256",
            "cells",
            "units",
            *phase_link_fields,
        ),
        context="schedule",
    )
    if schedule["schema_version"] != SCHEDULE_SCHEMA_VERSION:
        raise ContractError("schema de schedule inesperado")
    phase = schedule["phase"]
    if phase not in SCHEDULE_PHASE_ATTEMPTS:
        raise ContractError("schedule.phase fuera del catálogo")
    if schedule["permutation_algorithm"] != "sha256-key-sort-v1":
        raise ContractError("schedule.permutation_algorithm inesperado")
    seed = validate_sha256(schedule["permutation_seed_sha256"], context="permutation_seed_sha256")
    raw_cells = schedule["cells"]
    if not isinstance(raw_cells, list) or not raw_cells:
        raise ContractError("schedule.cells debe ser una lista no vacía")
    cells: list[dict[str, Any]] = []
    for index, raw_cell in enumerate(raw_cells):
        cell = _require_object(raw_cell, context=f"schedule.cells[{index}]")
        _require_exact_keys(cell, SCHEDULE_CELL_FIELDS, context=f"schedule.cells[{index}]")
        probe = validate_attempt_unit({**cell, "attempt_ordinal": 1})
        cells.append({name: probe[name] for name in SCHEDULE_CELL_FIELDS})
    cell_hashes = [canonical_json_sha256(cell) for cell in cells]
    if cell_hashes != sorted(cell_hashes) or len(set(cell_hashes)) != len(cell_hashes):
        raise ContractError("schedule.cells debe estar ordenado canónicamente y sin duplicados")
    if phase == "confirmation":
        validate_sha256(schedule["screening_schedule_sha256"], context="screening_schedule_sha256")
        promoted = schedule["promoted_screening_attempt_ids"]
        expected_promoted = sorted(
            attempt_id({**cell, "attempt_ordinal": ordinal})
            for cell in cells
            for ordinal in range(1, SCREENING_ATTEMPTS + 1)
        )
        if not isinstance(promoted, list) or promoted != expected_promoted:
            raise ContractError(
                "confirmation no liga exactamente los tres intentos screening promovidos por celda"
            )
        ordinal_range = range(SCREENING_ATTEMPTS + 1, CONFIRMATION_ATTEMPTS_TOTAL + 1)
    else:
        ordinal_range = range(1, SCHEDULE_PHASE_ATTEMPTS[str(phase)] + 1)
    expected_units = [
        {**cell, "attempt_ordinal": ordinal} for cell in cells for ordinal in ordinal_range
    ]
    expected_units.sort(
        key=lambda candidate: (
            sha256_bytes(f"{seed}\0{attempt_id(candidate)}".encode("ascii")),
            attempt_id(candidate),
        )
    )
    raw_units = schedule["units"]
    if not isinstance(raw_units, list) or not raw_units:
        raise ContractError("schedule.units debe ser una lista no vacía")
    units = [
        validate_attempt_unit(_require_object(raw, context="schedule.units[]")) for raw in raw_units
    ]
    if units != expected_units:
        raise ContractError("schedule.units no deriva exactamente de seed/fase/celdas")
    ids = [attempt_id(candidate) for candidate in units]
    if len(set(ids)) != len(ids):
        raise ContractError("schedule contiene unidades duplicadas")
    target = attempt_id(unit)
    if ids.count(target) != 1:
        raise ContractError("unidad actual no aparece exactamente una vez en schedule")
    return canonical_json_sha256(schedule), ids.index(target)


def validate_boundary_events(
    events: Sequence[Mapping[str, Any]], *, require_complete: bool = True
) -> dict[str, int]:
    """Valida eventos observados; sólo success exige la frontera completa."""
    allowed_names = {
        "boot",
        "limits_applied",
        "ready",
        "start",
        "first_open_or_byte",
        "flush_complete",
        "hash_complete",
        "rename_complete",
        "tree_empty",
    }
    names = [event.get("event") for event in events]
    required_once = (
        "boot",
        "limits_applied",
        "ready",
        "start",
        "first_open_or_byte",
        "flush_complete",
        "hash_complete",
        "rename_complete",
        "tree_empty",
    )
    positions: dict[str, int] = {}
    last_ns = -1
    for index, event in enumerate(events):
        name = event.get("event")
        monotonic_ns = event.get("monotonic_ns")
        if (
            not isinstance(name, str)
            or isinstance(monotonic_ns, bool)
            or not isinstance(monotonic_ns, int)
        ):
            raise ContractError(f"evento de frontera inválido en posición {index}")
        if name not in allowed_names:
            raise ContractError(f"evento de frontera fuera del catálogo: {name!r}")
        context = f"boundary.events[{index}]"
        if name == "boot":
            _require_exact_keys(
                event,
                ("event", "monotonic_ns", "pid", "heavy_work_started"),
                context=context,
            )
            if (
                _require_non_negative_int(event["pid"], context=f"{context}.pid") < 1
                or event["heavy_work_started"] is not False
            ):
                raise ContractError("BOOT no acredita PID/ausencia de trabajo pesado")
        elif name == "limits_applied":
            _require_exact_keys(
                event,
                ("event", "monotonic_ns", "effective_limits"),
                context=context,
            )
            _validate_job_limits(event["effective_limits"], context=f"{context}.effective_limits")
        elif name == "ready":
            _require_exact_keys(
                event,
                ("event", "monotonic_ns", "heavy_work_started"),
                context=context,
            )
            if event["heavy_work_started"] is not False:
                raise ContractError("READY no acredita ausencia de trabajo pesado")
        elif name in {"start", "tree_empty"}:
            _require_exact_keys(event, ("event", "monotonic_ns"), context=context)
        elif name == "first_open_or_byte":
            kind = event.get("kind")
            if kind == "first_open":
                _require_exact_keys(
                    event,
                    (
                        "event",
                        "monotonic_ns",
                        "kind",
                        "provider",
                        "request_id",
                        "protected",
                        "broker_request_sha256",
                        "nonce_commitment_sha256",
                        "candidate_process",
                    ),
                    context=context,
                )
                if event["provider"] != "harness_owned_consumer_open_v1":
                    raise ContractError("first_open no fue solicitado al broker del consumidor")
                validate_sha256(event["request_id"], context=f"{context}.request_id")
                validate_sha256(
                    event["broker_request_sha256"],
                    context=f"{context}.broker_request_sha256",
                )
                validate_sha256(
                    event["nonce_commitment_sha256"],
                    context=f"{context}.nonce_commitment_sha256",
                )
                candidate_process = _require_object(
                    event["candidate_process"], context=f"{context}.candidate_process"
                )
                _require_exact_keys(
                    candidate_process,
                    ("pid", "creation_time_100ns"),
                    context=f"{context}.candidate_process",
                )
                for field in ("pid", "creation_time_100ns"):
                    if (
                        _require_non_negative_int(
                            candidate_process[field],
                            context=f"{context}.candidate_process.{field}",
                        )
                        < 1
                    ):
                        raise ContractError(
                            f"{context}.candidate_process.{field} debe ser positivo"
                        )
                protected = event["protected"]
                if not isinstance(protected, list) or not protected:
                    raise ContractError("first_open.protected debe ser lista no vacía")
                normalized_protected: list[dict[str, Any]] = []
                for protected_index, raw_identity in enumerate(protected):
                    identity = _require_object(
                        raw_identity, context=f"{context}.protected[{protected_index}]"
                    )
                    _require_exact_keys(
                        identity,
                        ("logical_id", "role", "relative_name", "logical_bytes", "sha256"),
                        context=f"{context}.protected[{protected_index}]",
                    )
                    logical_id = validate_sha256(
                        identity["logical_id"], context=f"{context}.protected.logical_id"
                    )
                    role = identity["role"]
                    if role not in {"input", "bundle", "config"}:
                        raise ContractError("first_open.protected.role fuera del catálogo")
                    relative_name = _require_text(
                        identity["relative_name"],
                        context=f"{context}.protected.relative_name",
                    )
                    if (
                        "\\" in relative_name
                        or relative_name.startswith("/")
                        or ":" in relative_name
                        or any(part in {"", ".", ".."} for part in relative_name.split("/"))
                    ):
                        raise ContractError(
                            "first_open.protected.relative_name no es relativo seguro"
                        )
                    logical_bytes = _require_non_negative_int(
                        identity["logical_bytes"], context=f"{context}.protected.logical_bytes"
                    )
                    digest = validate_sha256(
                        identity["sha256"], context=f"{context}.protected.sha256"
                    )
                    if logical_id != canonical_json_sha256(
                        {
                            "role": role,
                            "relative_name": relative_name,
                            "logical_bytes": logical_bytes,
                            "sha256": digest,
                        }
                    ):
                        raise ContractError(
                            "first_open.protected.logical_id no deriva de la identidad"
                        )
                    normalized_protected.append(dict(identity))
                if normalized_protected != sorted(
                    normalized_protected, key=lambda item: str(item["logical_id"])
                ) or len({str(item["logical_id"]) for item in normalized_protected}) != len(
                    normalized_protected
                ):
                    raise ContractError(
                        "first_open.protected no está ordenado o contiene logical_id repetidos"
                    )
            elif kind == "first_byte":
                _require_exact_keys(
                    event,
                    (
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
                    ),
                    context=context,
                )
                if event["provider"] != "harness_owned_candidate_http_ingress_v1":
                    raise ContractError("first_byte no fue observado por el servicio candidato")
                _require_text(event["request_id"], context=f"{context}.request_id")
                _require_non_negative_int(
                    event["request_body_bytes"], context=f"{context}.request_body_bytes"
                )
                validate_sha256(
                    event["request_body_sha256"], context=f"{context}.request_body_sha256"
                )
                validate_sha256(
                    event["service_descriptor_sha256"],
                    context=f"{context}.service_descriptor_sha256",
                )
                validate_sha256(event["endpoint_sha256"], context=f"{context}.endpoint_sha256")
                if event["non_transforming"] is not True:
                    raise ContractError("ingress F-UI debe ser no transformador")
            else:
                raise ContractError("kind de first_open_or_byte fuera del catálogo")
        elif name == "flush_complete":
            _require_exact_keys(
                event,
                ("event", "monotonic_ns", "artifact_count", "logical_bytes"),
                context=context,
            )
            _require_non_negative_int(event["artifact_count"], context=f"{context}.artifact_count")
            _require_non_negative_int(event["logical_bytes"], context=f"{context}.logical_bytes")
        elif name == "hash_complete":
            _require_exact_keys(
                event,
                ("event", "monotonic_ns", "artifact_count", "artifact_sha256"),
                context=context,
            )
            count = _require_non_negative_int(
                event["artifact_count"], context=f"{context}.artifact_count"
            )
            hashes = event["artifact_sha256"]
            if not isinstance(hashes, list) or len(hashes) != count:
                raise ContractError("hash_complete no reconcilia la cardinalidad de hashes")
            for digest_index, digest in enumerate(hashes):
                validate_sha256(digest, context=f"{context}.artifact_sha256[{digest_index}]")
        else:
            _require_exact_keys(
                event,
                ("event", "monotonic_ns", "path", "sha256"),
                context=context,
            )
            _require_text(event["path"], context=f"{context}.path")
            validate_sha256(event["sha256"], context=f"{context}.sha256")
        if monotonic_ns < last_ns:
            raise ContractError("reloj monotónico retrocede en la frontera")
        last_ns = monotonic_ns
        if name in required_once:
            if name in positions:
                raise ContractError(f"evento de frontera duplicado: {name}")
            positions[name] = index
    missing = [name for name in required_once if name not in positions]
    if require_complete and missing:
        raise ContractError(f"eventos de frontera faltantes: {missing!r}")
    if "start" in positions and any(
        prerequisite not in positions for prerequisite in ("boot", "limits_applied", "ready")
    ):
        raise ContractError("START ocurrió sin BOOT/límites/READY observados")
    if (
        "ready" in positions
        and "start" in positions
        and names.index("ready") >= names.index("start")
    ):
        raise ContractError("START no ocurrió después de READY")
    ordered = [positions[name] for name in required_once if name in positions]
    if ordered != sorted(ordered):
        raise ContractError("orden de frontera consumidor/publicación inválido")
    if "first_open_or_byte" in positions and (
        "start" not in positions or positions["first_open_or_byte"] < positions["start"]
    ):
        raise ContractError("frontera consumidora ocurrió antes de START")
    return positions


def _validate_consumer_window_declaration(
    summary: Mapping[str, Any],
    *,
    boundary_events: Sequence[Mapping[str, Any]],
    positions: Mapping[str, int],
    expected_provider: str,
    ready_monotonic_ns: int | None,
    tree_empty_monotonic_ns: int | None,
    required: bool,
) -> None:
    window_raw = summary.get("consumer_window")
    overhead_raw = summary.get("overhead")
    if window_raw is None or overhead_raw is None:
        if required:
            raise ContractError("success carece de consumer_window/overhead")
        if window_raw is not None or overhead_raw is not None:
            raise ContractError("consumer_window/overhead deben aparecer juntos")
        return
    window = _require_object(window_raw, context="resources.summary.consumer_window")
    _require_exact_keys(
        window,
        (
            "provider",
            "start_monotonic_ns",
            "end_monotonic_ns",
            "wall_seconds",
            "sample_ordinals",
            "records",
            "coverage",
            "peak_tree_working_set_bytes",
            "peak_job_memory_commit_bytes_observed_during_window",
            "peak_incremental_allocated_bytes",
            "total_job_cpu_delta_100ns",
        ),
        context="resources.summary.consumer_window",
    )
    if window["provider"] != expected_provider:
        raise ContractError("consumer_window.provider no reconcilia con la frontera")
    if "first_open_or_byte" not in positions or "rename_complete" not in positions:
        raise ContractError("consumer_window existe sin ambas fronteras consumidoras")
    start_ns = int(boundary_events[positions["first_open_or_byte"]]["monotonic_ns"])
    end_ns = int(boundary_events[positions["rename_complete"]]["monotonic_ns"])
    if (
        window["start_monotonic_ns"] != start_ns
        or window["end_monotonic_ns"] != end_ns
        or not isinstance(window["wall_seconds"], int | float)
        or isinstance(window["wall_seconds"], bool)
        or not math.isclose(
            float(window["wall_seconds"]),
            (end_ns - start_ns) / 1_000_000_000,
            rel_tol=0.0,
            abs_tol=1e-12,
        )
    ):
        raise ContractError("consumer_window no deriva de first-open/byte→rename")
    ordinals = window["sample_ordinals"]
    if (
        not isinstance(ordinals, list)
        or not ordinals
        or any(isinstance(item, bool) or not isinstance(item, int) or item < 0 for item in ordinals)
        or ordinals != sorted(set(ordinals))
        or window["records"] != len(ordinals)
    ):
        raise ContractError("consumer_window.sample_ordinals/records no reconcilian")
    for name in (
        "peak_tree_working_set_bytes",
        "peak_job_memory_commit_bytes_observed_during_window",
        "peak_incremental_allocated_bytes",
        "total_job_cpu_delta_100ns",
    ):
        _require_non_negative_int(window[name], context=f"resources.summary.consumer_window.{name}")
    coverage = _require_object(
        window["coverage"], context="resources.summary.consumer_window.coverage"
    )
    _require_exact_keys(
        coverage,
        (
            "start_bracket_ordinal",
            "end_bracket_ordinal",
            "inside_sample_ordinals",
            "start_gap_ns",
            "end_gap_ns",
            "resolution",
        ),
        context="resources.summary.consumer_window.coverage",
    )
    for name in ("start_bracket_ordinal", "end_bracket_ordinal", "start_gap_ns", "end_gap_ns"):
        _require_non_negative_int(
            coverage[name], context=f"resources.summary.consumer_window.coverage.{name}"
        )
    inside = coverage["inside_sample_ordinals"]
    if (
        not isinstance(inside, list)
        or any(isinstance(item, bool) or not isinstance(item, int) or item < 0 for item in inside)
        or inside != sorted(set(inside))
        or not set(inside).issubset(set(ordinals))
        or coverage["resolution"] != ("inside_samples" if inside else "bracketed")
        or coverage["start_bracket_ordinal"] not in ordinals
        or coverage["end_bracket_ordinal"] not in ordinals
    ):
        raise ContractError("consumer_window.coverage no reconcilia sample ordinals/brackets")
    overhead = _require_object(overhead_raw, context="resources.summary.overhead")
    _require_exact_keys(
        overhead,
        (
            "ready_to_consumer_seconds",
            "consumer_to_tree_empty_seconds",
            "envelope_records",
        ),
        context="resources.summary.overhead",
    )
    if ready_monotonic_ns is None or tree_empty_monotonic_ns is None:
        raise ContractError("overhead existe sin READY/tree-empty")
    expected_overhead = (
        (start_ns - ready_monotonic_ns) / 1_000_000_000,
        (tree_empty_monotonic_ns - end_ns) / 1_000_000_000,
    )
    if (
        any(
            isinstance(overhead[name], bool)
            or not isinstance(overhead[name], int | float)
            or not math.isclose(float(overhead[name]), expected, rel_tol=0.0, abs_tol=1e-12)
            for name, expected in zip(
                ("ready_to_consumer_seconds", "consumer_to_tree_empty_seconds"),
                expected_overhead,
                strict=True,
            )
        )
        or _require_non_negative_int(
            overhead["envelope_records"], context="resources.summary.overhead.envelope_records"
        )
        < window["records"]
    ):
        raise ContractError("overhead no deriva de READY/frontera/tree-empty")


def _validate_native_pool_processes(
    value: Any, *, context: str, require_source: bool
) -> list[dict[str, Any]]:
    """Cierra el censo efectivo por PID+creation, incluidas listas de pools vacías."""
    pool_keys = {
        "OMP_NUM_THREADS",
        "MKL_NUM_THREADS",
        "OPENBLAS_NUM_THREADS",
        "NUMEXPR_NUM_THREADS",
        "BLIS_NUM_THREADS",
        "VECLIB_MAXIMUM_THREADS",
    }
    if not isinstance(value, list) or not value:
        raise ContractError(f"{context}: censo por proceso ausente")
    normalized: list[dict[str, Any]] = []
    for index, raw_process in enumerate(value):
        process = _require_object(raw_process, context=f"{context}[{index}]")
        process_fields = (
            "pid",
            "creation_time_100ns",
            "environment",
            "libraries",
            "process_thread_count",
            *(("source",) if require_source else ()),
        )
        _require_exact_keys(
            process,
            process_fields,
            context=f"{context}[{index}]",
        )
        pid = _require_non_negative_int(process["pid"], context=f"{context}[{index}].pid")
        creation = _require_non_negative_int(
            process["creation_time_100ns"],
            context=f"{context}[{index}].creation_time_100ns",
        )
        thread_count = process["process_thread_count"]
        if (
            pid < 1
            or creation < 1
            or isinstance(thread_count, bool)
            or not isinstance(thread_count, int)
            or thread_count < 1
        ):
            raise ContractError(f"{context}[{index}]: identidad/thread count inválido")
        environment = _require_object(
            process["environment"], context=f"{context}[{index}].environment"
        )
        if set(environment) != pool_keys or any(
            not isinstance(item, str) or not item.isdigit() or not 1 <= int(item) <= 4
            for item in environment.values()
        ):
            raise ContractError("variables de pools no acreditan 1…4 threads")
        libraries = process["libraries"]
        if not isinstance(libraries, list):
            raise ContractError("native_pools.libraries debe ser lista")
        normalized_libraries: list[dict[str, Any]] = []
        for raw in libraries:
            library = _require_object(raw, context="native_pools.libraries[]")
            _require_exact_keys(
                library,
                ("library", "version", "threading_layer", "effective_threads"),
                context="native pool library",
            )
            effective = library["effective_threads"]
            if (
                not isinstance(library["library"], str)
                or not library["library"]
                or not isinstance(library["version"], str)
                or not library["version"]
                or not isinstance(library["threading_layer"], str)
                or not library["threading_layer"]
                or isinstance(effective, bool)
                or not isinstance(effective, int)
                or not 1 <= effective <= 4
            ):
                raise ContractError("biblioteca/pool efectivo inválido")
            normalized_libraries.append(dict(library))

        def library_key(item: Mapping[str, Any]) -> tuple[str, str, str]:
            return (
                str(item["library"]),
                str(item["version"]),
                str(item["threading_layer"]),
            )

        if normalized_libraries != sorted(normalized_libraries, key=library_key) or len(
            {library_key(item) for item in normalized_libraries}
        ) != len(normalized_libraries):
            raise ContractError("bibliotecas nativas duplicadas o fuera de orden")
        normalized_process = {
            "pid": pid,
            "creation_time_100ns": creation,
            "environment": dict(environment),
            "libraries": normalized_libraries,
            "process_thread_count": thread_count,
        }
        if require_source:
            source = _require_object(process["source"], context=f"{context}[{index}].source")
            _require_exact_keys(
                source,
                ("path", "logical_bytes", "sha256"),
                context=f"{context}[{index}].source",
            )
            _require_text(source["path"], context=f"{context}[{index}].source.path")
            _require_non_negative_int(
                source["logical_bytes"],
                context=f"{context}[{index}].source.logical_bytes",
            )
            validate_sha256(source["sha256"], context=f"{context}[{index}].source.sha256")
            normalized_process["source"] = dict(source)
        normalized.append(normalized_process)
    identities = [(process["pid"], process["creation_time_100ns"]) for process in normalized]
    if identities != sorted(set(identities)):
        raise ContractError(f"{context}: procesos duplicados o fuera de orden PID/creation")
    return normalized


def validate_native_pool_events(events: Sequence[Mapping[str, Any]]) -> None:
    """Valida el único censo efectivo por proceso derivado dentro del consumidor."""
    if len(events) != 1:
        raise ContractError("sidecar de pools nativos exige exactamente un censo")
    event = _require_object(events[0], context="native_pools[0]")
    _require_exact_keys(
        event,
        ("event", "monotonic_ns", "total_processes", "processes"),
        context="native_pools[0]",
    )
    if event["event"] != "native_pools":
        raise ContractError("evento de pools nativos desconocido")
    _require_non_negative_int(event["monotonic_ns"], context="native_pools.monotonic_ns")
    total = _require_non_negative_int(
        event["total_processes"], context="native_pools.total_processes"
    )
    processes = _validate_native_pool_processes(
        event["processes"], context="native_pools.processes", require_source=False
    )
    if total < 1 or total != len(processes):
        raise ContractError("native_pools.total_processes no reconcilia el censo")


def _reconcile_native_pool_evidence(
    *,
    candidate_process: Mapping[str, Any],
    expected_process_census: Sequence[Mapping[str, Any]],
    aggregate: Mapping[str, Any],
    sidecar_event: Mapping[str, Any],
) -> None:
    """Liga el censo kernel, el agregado con fuentes y el sidecar sin paths."""
    _require_exact_keys(
        aggregate,
        (
            "schema_version",
            "candidate_execution_request_sha256",
            "total_processes",
            "processes",
        ),
        context="candidate native-pools aggregate",
    )
    total_processes = _require_non_negative_int(
        aggregate["total_processes"], context="candidate native-pools aggregate.total_processes"
    )
    kernel_census = _validate_candidate_process_census(
        {
            "source": "windows_job_completion_port_v1",
            "total_processes": len(expected_process_census),
            "processes": list(expected_process_census),
        },
        root_process=candidate_process,
        expected_total_processes=len(expected_process_census),
    )
    if total_processes != kernel_census["total_processes"]:
        raise ContractError("candidate native-pools no reconcilia total_processes kernel")
    observed_processes = _validate_native_pool_processes(
        aggregate["processes"],
        context="candidate native-pools aggregate.processes",
        require_source=True,
    )
    observed_identities = [
        (process["pid"], process["creation_time_100ns"]) for process in observed_processes
    ]
    expected_identities = [
        (process["pid"], process["creation_time_100ns"]) for process in kernel_census["processes"]
    ]
    if observed_identities != expected_identities:
        raise ContractError("candidate native-pools no coincide con el censo kernel PID+creation")
    validate_native_pool_events([sidecar_event])
    expected_sidecar_processes = [
        {
            name: process[name]
            for name in (
                "pid",
                "creation_time_100ns",
                "environment",
                "libraries",
                "process_thread_count",
            )
        }
        for process in observed_processes
    ]
    if (
        sidecar_event.get("total_processes") != total_processes
        or sidecar_event.get("processes") != expected_sidecar_processes
    ):
        raise ContractError("sidecar native_pools no deriva del agregado controller-owned")


def robust_summary(values: Sequence[float | int]) -> dict[str, Any]:
    """Calcula mediana, MAD*, U y estabilidad sin descartar observaciones."""
    if not values:
        raise ContractError("la estadística exige al menos una observación")
    normalized = [float(value) for value in values]
    if any(not math.isfinite(value) or value < 0 for value in normalized):
        raise ContractError("las métricas deben ser finitas y no negativas")
    median = float(statistics.median(normalized))
    mad_star = 1.4826 * float(statistics.median(abs(value - median) for value in normalized))
    upper = max(max(normalized), median + 3.0 * mad_star)
    relative_mad = None if median == 0 else mad_star / median
    stable = bool(median > 0 and relative_mad is not None and relative_mad <= MAX_RELATIVE_MAD)
    return {
        "values": normalized,
        "count": len(normalized),
        "minimum": min(normalized),
        "median": median,
        "maximum": max(normalized),
        "mad_star": mad_star,
        "u": upper,
        "relative_mad": relative_mad,
        "stable": stable,
    }


def evaluate_repetitions(classifications: Sequence[str], *, phase: str) -> dict[str, Any]:
    """Aplica 3/3 screening o 10/10 confirmación sin reemplazos."""
    required = SCREENING_ATTEMPTS if phase == "screening" else CONFIRMATION_ATTEMPTS_TOTAL
    if phase not in {"screening", "confirmation"}:
        raise ContractError(f"fase estadística desconocida: {phase}")
    if len(classifications) != required:
        raise ContractError(f"{phase} exige exactamente {required} intentos")
    unknown = sorted(set(classifications) - set(CLASSIFICATIONS))
    if unknown:
        raise ContractError(f"clasificaciones fuera del catálogo: {unknown!r}")
    return {
        "phase": phase,
        "required_attempts": required,
        "received_attempts": len(classifications),
        "all_success": all(value == "success" for value in classifications),
        "classifications": list(classifications),
    }


def _validate_file_identity(value: Any, *, context: str) -> dict[str, Any]:
    item = _require_object(value, context=context)
    _require_exact_keys(
        item,
        (
            "path",
            "relative_path",
            "bytes",
            "allocated_bytes",
            "allocation_reliable",
            "allocation_source",
            "sha256",
        ),
        context=context,
    )
    _require_text(item["path"], context=f"{context}.path")
    _require_text(item["relative_path"], context=f"{context}.relative_path")
    _require_non_negative_int(item["bytes"], context=f"{context}.bytes")
    _require_non_negative_int(item["allocated_bytes"], context=f"{context}.allocated_bytes")
    _require_bool(item["allocation_reliable"], context=f"{context}.allocation_reliable")
    _require_text(item["allocation_source"], context=f"{context}.allocation_source")
    validate_sha256(item["sha256"], context=f"{context}.sha256")
    return item


def _validate_fixture_file_identity(value: Any, *, context: str) -> dict[str, Any]:
    item = _require_object(value, context=context)
    _require_exact_keys(
        item,
        (
            "relative_path",
            "format",
            "rows",
            "expanded_rows",
            "logical_bytes",
            "allocated_bytes",
            "sha256",
            "path",
            "allocation_reliable",
            "allocation_source",
        ),
        context=context,
    )
    for name in ("relative_path", "format", "path", "allocation_source"):
        _require_text(item[name], context=f"{context}.{name}")
    for name in ("rows", "expanded_rows"):
        if item[name] is not None:
            _require_non_negative_int(item[name], context=f"{context}.{name}")
    for name in ("logical_bytes", "allocated_bytes"):
        _require_non_negative_int(item[name], context=f"{context}.{name}")
    if (
        _require_bool(item["allocation_reliable"], context=f"{context}.allocation_reliable")
        is not True
    ):
        raise ContractError(f"{context}.allocation_reliable no acredita sensor calificable")
    validate_sha256(item["sha256"], context=f"{context}.sha256")
    return item


def _validate_fixture_geometry_observed(
    value: Any,
    *,
    dimensions: Mapping[str, Any],
    inputs: Sequence[Mapping[str, Any]],
    fixture_schema: Mapping[str, Any],
    catalog: Mapping[str, Any],
) -> dict[str, Any]:
    geometry = _require_object(value, context="fixture.geometry_observed")
    _require_exact_keys(
        geometry,
        ("provider", "primary_input", "input_set_sha256", "dimensions", "derivations"),
        context="fixture.geometry_observed",
    )
    if geometry["provider"] != "harness_reopened_inputs_v1":
        raise ContractError("geometry_observed productiva no fue derivada al reabrir inputs")
    primary = _require_object(
        geometry["primary_input"], context="fixture.geometry_observed.primary_input"
    )
    _require_exact_keys(
        primary,
        ("relative_path", "logical_bytes", "sha256"),
        context="fixture.geometry_observed.primary_input",
    )
    _require_text(primary["relative_path"], context="fixture.geometry_observed.primary_input.path")
    _require_non_negative_int(
        primary["logical_bytes"], context="fixture.geometry_observed.primary_input.logical_bytes"
    )
    validate_sha256(primary["sha256"], context="fixture.geometry_observed.primary_input.sha256")
    input_identities = sorted(
        (
            {
                "relative_path": str(item["relative_path"]),
                "logical_bytes": int(item["logical_bytes"]),
                "sha256": str(item["sha256"]),
            }
            for item in inputs
        ),
        key=lambda item: cast(str, item["relative_path"]),
    )
    if input_identities.count(dict(primary)) != 1:
        raise ContractError("geometry_observed.primary_input no liga exactamente un input")
    if geometry["input_set_sha256"] != canonical_json_sha256(input_identities):
        raise ContractError("geometry_observed.input_set_sha256 no deriva del conjunto de inputs")
    observed_dimensions = _require_object(
        geometry["dimensions"], context="fixture.geometry_observed.dimensions"
    )
    if observed_dimensions != dict(dimensions):
        raise ContractError("geometry_observed.dimensions no reconcilia con la geometría")
    derivations = _require_object(
        geometry["derivations"], context="fixture.geometry_observed.derivations"
    )
    if set(derivations) != set(dimensions):
        raise ContractError("geometry_observed.derivations no cubre cada dimensión exactamente")
    primary_sha256 = str(primary["sha256"])
    source_by_dimension: dict[str, list[str]] = {
        name: [primary_sha256]
        for name in dimensions
        if name
        in {
            "rows",
            "operations",
            "observations",
            "transitions",
            "max_cardinality",
            "periods",
            "payload_bytes",
        }
    }
    if "variables" in dimensions:
        source_by_dimension["variables"] = [str(fixture_schema["sha256"])]
    if "scenarios" in dimensions:
        source_by_dimension["scenarios"] = [str(catalog["sha256"])]
    if "expanded_rows" in dimensions:
        factor_names = [
            name for name in ("operations", "periods", "scenarios") if name in dimensions
        ]
        source_by_dimension["expanded_rows"] = sorted(
            {digest for factor_name in factor_names for digest in source_by_dimension[factor_name]}
        )
    for name, declared_value in dimensions.items():
        derivation = _require_object(
            derivations[name], context=f"fixture.geometry_observed.derivations.{name}"
        )
        _require_exact_keys(
            derivation,
            ("algorithm", "value", "source_sha256"),
            context=f"fixture.geometry_observed.derivations.{name}",
        )
        if (
            derivation["algorithm"] != GEOMETRY_DERIVATION_ALGORITHMS[name]
            or derivation["value"] != declared_value
            or derivation["source_sha256"] != source_by_dimension[name]
        ):
            raise ContractError(f"derivación material de geometry.{name} no reconcilia")
    return geometry


def _validate_runtime_provenance(value: Any, *, context: str) -> dict[str, Any]:
    provenance = _require_object(value, context=context)
    _require_exact_keys(
        provenance,
        (
            "probe_schema_version",
            "isolation_flags",
            "no_site",
            "distribution",
            "version",
            "distribution_root",
            "dist_info_path",
            "metadata_sha256",
            "record_sha256",
            "record_entries",
            "imported_package_path",
            "imported_package_sha256",
            "installed_tree_sha256",
            "wheel_sha256",
            "lock_sha256",
            "probe_payload_sha256",
        ),
        context=context,
    )
    if provenance["probe_schema_version"] != "nikodym.readiness.h9r.runtime-provenance.v1":
        raise ContractError(f"{context}.probe_schema_version inesperado")
    if provenance["isolation_flags"] != ["-I", "-B", "-S"]:
        raise ContractError(f"{context}.isolation_flags no acredita runtime aislado")
    if provenance["no_site"] is not True:
        raise ContractError(f"{context}.no_site no acredita bootstrap sin site hooks")
    if provenance["distribution"] != "nikodym":
        raise ContractError(f"{context}.distribution no identifica nikodym")
    for name in (
        "version",
        "distribution_root",
        "dist_info_path",
        "imported_package_path",
    ):
        _require_text(provenance[name], context=f"{context}.{name}")
    _require_non_negative_int(provenance["record_entries"], context=f"{context}.record_entries")
    if provenance["record_entries"] < 1:
        raise ContractError(f"{context}.record_entries debe ser positivo")
    for name in (
        "metadata_sha256",
        "record_sha256",
        "imported_package_sha256",
        "installed_tree_sha256",
        "wheel_sha256",
        "lock_sha256",
        "probe_payload_sha256",
    ):
        validate_sha256(provenance[name], context=f"{context}.{name}")
    return provenance


def _validate_job_limits(value: Any, *, context: str) -> dict[str, Any]:
    item = _require_object(value, context=context)
    _require_exact_keys(
        item,
        (
            "limit_flags",
            "affinity_mask",
            "logical_cpu_count",
            "processor_group",
            "group_affinities",
            "job_memory_commit_limit_bytes",
            "kill_on_job_close",
            "affinity_enforced",
            "job_memory_enforced",
        ),
        context=context,
    )
    for name in (
        "limit_flags",
        "affinity_mask",
        "logical_cpu_count",
        "processor_group",
        "job_memory_commit_limit_bytes",
    ):
        _require_non_negative_int(item[name], context=f"{context}.{name}")
    for name in ("kill_on_job_close", "affinity_enforced", "job_memory_enforced"):
        if _require_bool(item[name], context=f"{context}.{name}") is not True:
            raise ContractError(f"{context}.{name}: el control efectivo debe estar activo")
    logical_cpu_count = item["logical_cpu_count"]
    affinity_mask = item["affinity_mask"]
    if logical_cpu_count not in {1, 2, 3, 4}:
        raise ContractError(f"{context}.logical_cpu_count fuera de 1…4")
    if affinity_mask <= 0:
        raise ContractError(f"{context}.affinity_mask debe ser positiva")
    if affinity_mask.bit_count() != logical_cpu_count:
        raise ContractError(f"{context}: affinity_mask no reconcilia logical_cpu_count")
    if item["job_memory_commit_limit_bytes"] not in set(CAPS.values()):
        raise ContractError(f"{context}.job_memory_commit_limit_bytes fuera del catálogo CAPS")
    raw_groups = item["group_affinities"]
    if not isinstance(raw_groups, list) or len(raw_groups) != 1:
        raise ContractError(f"{context}.group_affinities: se esperaba una afinidad")
    group = _require_object(raw_groups[0], context=f"{context}.group_affinities[0]")
    _require_exact_keys(
        group,
        ("processor_group", "affinity_mask"),
        context=f"{context}.group_affinities[0]",
    )
    _require_non_negative_int(
        group["processor_group"], context=f"{context}.group_affinities[0].processor_group"
    )
    _require_non_negative_int(
        group["affinity_mask"], context=f"{context}.group_affinities[0].affinity_mask"
    )
    if (
        group["processor_group"] != item["processor_group"]
        or group["affinity_mask"] != item["affinity_mask"]
    ):
        raise ContractError(f"{context}: afinidad por grupo no reconcilia")
    return item


def _validate_worker_result(
    value: Any,
    *,
    expected_attempt_id: str,
    returncode_signed: int | None,
    returncode_unsigned: int | None,
    client_returncode_signed: int | None,
    classification: str,
) -> dict[str, Any] | None:
    """Cierra las dos variantes worker y liga su causalidad a la terminación."""
    if value is None:
        if classification == "success":
            raise ContractError("success no conserva worker_result")
        if classification == "consumer_error" and client_returncode_signed in {None, 0}:
            raise ContractError("consumer_error no conserva una causa de consumidor")
        return None

    worker = _require_object(value, context="termination.worker_result")
    common = {"schema_version", "attempt_id", "status", "error"}
    consumer_variant = common | {
        "consumer_returncode_signed",
        "consumer_returncode_unsigned",
    }
    internal_variant = common | {"error_type", "traceback"}
    observed = set(worker)
    if observed == consumer_variant:
        variant = "consumer"
    elif observed == internal_variant:
        variant = "internal"
    else:
        raise ContractError(
            "termination.worker_result: no coincide con ninguna de las dos variantes cerradas"
        )
    if worker["schema_version"] != "nikodym.readiness.h9r.worker-result.v1":
        raise ContractError("termination.worker_result.schema_version inesperado")
    if worker["attempt_id"] != expected_attempt_id:
        raise ContractError("termination.worker_result.attempt_id no reconcilia")

    status = worker["status"]
    if variant == "consumer":
        if status not in {"ok", "error"}:
            raise ContractError("termination.worker_result.status inesperado")
        consumer_signed = worker["consumer_returncode_signed"]
        consumer_unsigned = worker["consumer_returncode_unsigned"]
        if isinstance(consumer_signed, bool) or not isinstance(consumer_signed, int):
            raise ContractError("worker_result.consumer_returncode_signed inválido")
        if (
            isinstance(consumer_unsigned, bool)
            or not isinstance(consumer_unsigned, int)
            or not 0 <= consumer_unsigned <= 0xFFFFFFFF
        ):
            raise ContractError("worker_result.consumer_returncode_unsigned inválido")
        if consumer_unsigned != consumer_signed & 0xFFFFFFFF:
            raise ContractError("returncodes del consumidor en worker_result no reconcilian")
        error = worker["error"]
        if status == "ok":
            if consumer_signed != 0 or error is not None:
                raise ContractError("worker_result ok no deriva de returncode cero sin error")
        elif consumer_signed == 0 or not isinstance(error, str) or not error:
            raise ContractError("worker_result error no deriva de returncode no-cero y mensaje")
        if returncode_signed != consumer_signed or returncode_unsigned != consumer_unsigned:
            raise ContractError("worker_result no reconcilia returncodes de la raíz worker")
    else:
        if status != "error":
            raise ContractError("worker_result interno debe tener status=error")
        for name in ("error_type", "error", "traceback"):
            _require_text(worker[name], context=f"termination.worker_result.{name}")
        if returncode_signed != 1 or returncode_unsigned != 1:
            raise ContractError("worker_result interno no reconcilia exit code 1 del worker")

    if classification == "success" and (
        variant != "consumer" or status != "ok" or client_returncode_signed not in {None, 0}
    ):
        raise ContractError("success no deriva de terminación consumidora limpia")
    if classification == "consumer_error":
        worker_failed = status == "error"
        client_failed = client_returncode_signed not in {None, 0}
        if not (worker_failed or client_failed):
            raise ContractError("consumer_error no deriva de ningún returncode de consumidor")
    return worker


def _validate_termination_classification_flags(
    *,
    classification: str,
    trigger_classification: str | None,
    cleanup_complete: bool,
    timed_out: bool,
    cancelled: bool,
) -> None:
    """Conserva el trigger primario aunque un orphan posterior prevalezca como resultado final."""
    if trigger_classification is not None and (
        not isinstance(trigger_classification, str)
        or trigger_classification not in {"watchdog_deadline", "cancelled"}
    ):
        raise ContractError("trigger_classification fuera del catálogo cerrado")
    if timed_out and cancelled:
        raise ContractError("timed_out y cancelled son mutuamente excluyentes")
    if timed_out is not (trigger_classification == "watchdog_deadline"):
        raise ContractError("timed_out no es bicondicional con el trigger watchdog_deadline")
    if cancelled is not (trigger_classification == "cancelled"):
        raise ContractError("cancelled no es bicondicional con el trigger cancelled")
    if cleanup_complete:
        if trigger_classification is not None and classification != trigger_classification:
            raise ContractError("trigger terminal no reconcilia con la clasificación final")
        if trigger_classification is None and classification in {
            "watchdog_deadline",
            "cancelled",
        }:
            raise ContractError("clasificación timeout/cancelled carece de trigger causal")
    elif classification != "orphan_detected":
        raise ContractError(
            "cleanup incompleto debe preservar orphan_detected como resultado final"
        )
    if classification == "success" and trigger_classification is not None:
        raise ContractError("success no puede acreditar trigger terminal")


def _validate_root_census_map(value: Any, *, context: str) -> dict[str, Any]:
    roots = _require_object(value, context=context)
    expected_roots = ("inputs", "bundle", "scratch", "outputs", "telemetry")
    _require_exact_keys(roots, expected_roots, context=context)
    for name in expected_roots:
        root = _require_object(roots[name], context=f"{context}.{name}")
        _require_exact_keys(
            root,
            (
                "root",
                "logical_bytes",
                "allocated_bytes",
                "files",
                "allocation_reliable",
                "allocation_sources",
            ),
            context=f"{context}.{name}",
        )
        _require_text(root["root"], context=f"{context}.{name}.root")
        for metric in ("logical_bytes", "allocated_bytes", "files"):
            _require_non_negative_int(root[metric], context=f"{context}.{name}.{metric}")
        _require_bool(root["allocation_reliable"], context=f"{context}.{name}.allocation_reliable")
        sources = root["allocation_sources"]
        if not isinstance(sources, list) or not all(
            isinstance(source, str) and source for source in sources
        ):
            raise ContractError(f"{context}.{name}.allocation_sources: lista inválida")
    return roots


def _validate_preflight_source_identity(value: Any, *, context: str) -> dict[str, Any]:
    source = _require_object(value, context=context)
    _require_exact_keys(
        source,
        ("path", "present", "safe_regular_file", "rejection", "bytes", "sha256"),
        context=context,
    )
    _require_text(source["path"], context=f"{context}.path")
    present = _require_bool(source["present"], context=f"{context}.present")
    safe = _require_bool(source["safe_regular_file"], context=f"{context}.safe_regular_file")
    if safe:
        if not present or source["rejection"] is not None:
            raise ContractError(f"{context}: archivo seguro no reconcilia presencia/rechazo")
        _require_non_negative_int(source["bytes"], context=f"{context}.bytes")
        validate_sha256(source["sha256"], context=f"{context}.sha256")
    else:
        if source["bytes"] is not None or source["sha256"] is not None:
            raise ContractError(f"{context}: fuente insegura no puede declarar bytes/hash")
        rejection = source["rejection"]
        expected_rejection = "absent" if not present else rejection
        if expected_rejection not in {
            "absent",
            "symlink_or_reparse_point",
            "not_regular_file",
            "multiple_hardlinks",
        }:
            raise ContractError(f"{context}: causa de rechazo fuera del catalogo")
        if not present and rejection != "absent":
            raise ContractError(f"{context}: fuente ausente no usa rechazo absent")
    return source


def validate_preflight_rejection_evidence(value: Mapping[str, Any]) -> dict[str, Any]:
    """Valida evidencia atomica de rechazo anterior a READY/START/worker."""
    _require_exact_keys(
        value,
        (
            "schema_version",
            "phase",
            "identity",
            "launch_sources",
            "observed",
            "termination",
            "gates",
            "reasons",
        ),
        context="preflight_rejection",
    )
    if (
        value["schema_version"] != PREFLIGHT_REJECTION_SCHEMA_VERSION
        or value["phase"] != "preflight"
    ):
        raise ContractError("preflight rejection usa otro schema/phase")
    identity = _require_object(value["identity"], context="preflight_rejection.identity")
    _require_exact_keys(
        identity,
        ("unit", "attempt_id", "evidence_path", "wall_time_finished_utc"),
        context="preflight_rejection.identity",
    )
    _require_text(identity["evidence_path"], context="preflight_rejection.identity.evidence_path")
    _require_text(
        identity["wall_time_finished_utc"],
        context="preflight_rejection.identity.wall_time_finished_utc",
    )
    if identity["unit"] is None:
        if identity["attempt_id"] is not None:
            raise ContractError("rechazo sin unidad no puede declarar attempt_id")
    else:
        unit = validate_attempt_unit(
            _require_object(identity["unit"], context="preflight_rejection.identity.unit")
        )
        if identity["attempt_id"] != attempt_id(unit):
            raise ContractError("attempt_id del rechazo no reconcilia con su unidad")

    launch = _require_object(value["launch_sources"], context="preflight_rejection.launch_sources")
    launch_names = (
        "unit_path",
        "authority_path",
        "authorization_text_path",
        "trusted_authority_public_key_path",
        "candidate_manifest_path",
        "fixture_manifest_path",
        "config_path",
        "schedule_path",
        "prior_evidence_paths_path",
        "document_paths",
        "workdir",
    )
    _require_exact_keys(launch, launch_names, context="preflight_rejection.launch_sources")
    for name in (*launch_names[:-2], "workdir"):
        _require_text(launch[name], context=f"preflight_rejection.launch_sources.{name}")
    document_paths = _require_object(
        launch["document_paths"], context="preflight_rejection.launch_sources.document_paths"
    )
    if not document_paths:
        raise ContractError("preflight rejection no censa documentos contractuales")
    for name, path in document_paths.items():
        _require_text(name, context="preflight_rejection.document_paths.name")
        _require_text(path, context=f"preflight_rejection.document_paths.{name}")

    observed = _require_object(value["observed"], context="preflight_rejection.observed")
    _require_exact_keys(
        observed, ("source_identities", "workdir_state"), context="preflight_rejection.observed"
    )
    source_identities = _require_object(
        observed["source_identities"], context="preflight_rejection.observed.source_identities"
    )
    source_launch_names = {
        "unit": "unit_path",
        "authority": "authority_path",
        "authorization_text": "authorization_text_path",
        "trusted_authority_public_key": "trusted_authority_public_key_path",
        "candidate_manifest": "candidate_manifest_path",
        "fixture_manifest": "fixture_manifest_path",
        "config": "config_path",
        "schedule": "schedule_path",
        "prior_evidence_paths": "prior_evidence_paths_path",
    }
    expected_source_names = {*source_launch_names, *(f"document:{name}" for name in document_paths)}
    if set(source_identities) != expected_source_names:
        raise ContractError("censo de fuentes del rechazo no es bidireccional")
    for name, launch_name in source_launch_names.items():
        source = _validate_preflight_source_identity(
            source_identities[name], context=f"preflight_rejection.source.{name}"
        )
        if source["path"] != launch[launch_name]:
            raise ContractError(f"preflight_rejection.source.{name}.path no reconcilia")
    for name, document_path in document_paths.items():
        source_name = f"document:{name}"
        source = _validate_preflight_source_identity(
            source_identities[source_name], context=f"preflight_rejection.source.{source_name}"
        )
        if source["path"] != document_path:
            raise ContractError(f"preflight_rejection.source.{source_name}.path no reconcilia")

    workdir = _require_object(
        observed["workdir_state"], context="preflight_rejection.observed.workdir_state"
    )
    _require_exact_keys(
        workdir,
        ("path", "existed_before", "exists_after", "entries_before", "entries_after"),
        context="preflight_rejection.observed.workdir_state",
    )
    if workdir["path"] != launch["workdir"]:
        raise ContractError("workdir observado no reconcilia con launch_sources")
    _require_bool(workdir["existed_before"], context="preflight_rejection.workdir.existed_before")
    exists_after = _require_bool(
        workdir["exists_after"], context="preflight_rejection.workdir.exists_after"
    )
    for name in ("entries_before", "entries_after"):
        entries = workdir[name]
        if (
            not isinstance(entries, list)
            or not all(isinstance(entry, str) and entry for entry in entries)
            or entries != sorted(set(entries))
        ):
            raise ContractError(f"preflight_rejection.workdir.{name}: censo invalido")

    termination = _require_object(value["termination"], context="preflight_rejection.termination")
    _require_exact_keys(
        termination,
        (
            "classification",
            "start_count",
            "ready_count",
            "worker_spawned",
            "cleanup_complete",
            "workdir_removed",
        ),
        context="preflight_rejection.termination",
    )
    if (
        termination["classification"] != "preflight_rejected"
        or termination["start_count"] != 0
        or termination["ready_count"] != 0
        or termination["worker_spawned"] is not False
    ):
        raise ContractError("rechazo preflight no acredita cero READY/START/worker")
    cleanup_complete = _require_bool(
        termination["cleanup_complete"], context="preflight_rejection.termination.cleanup_complete"
    )
    if termination["workdir_removed"] is not (not exists_after):
        raise ContractError("workdir_removed no deriva de exists_after")
    # El emisor de evidencia de rechazo no posee el workdir y no puede borrar una ruta que apareció
    # por carrera después del censo inicial del CLI. La limpieza de un árbol propio ocurre dentro
    # de run_preflight, bajo owner marker, antes de llegar aquí; este artefacto acredita
    # preservación.
    if cleanup_complete is not (workdir["entries_after"] == workdir["entries_before"]):
        raise ContractError("cleanup_complete no deriva del censo del workdir")

    gates = _require_object(value["gates"], context="preflight_rejection.gates")
    _require_exact_keys(
        gates, ("no_start", "no_worker", "evidence_atomic"), context="preflight_rejection.gates"
    )
    if gates != {"no_start": True, "no_worker": True, "evidence_atomic": True}:
        raise ContractError("gates del rechazo preflight no estan verdes")
    reasons = value["reasons"]
    if (
        not isinstance(reasons, list)
        or not reasons
        or not all(isinstance(reason, str) and reason for reason in reasons)
    ):
        raise ContractError("preflight rejection exige al menos una causa")
    return dict(value)


def _validate_declared_output_manifest(
    value: Any,
    *,
    expected_identities: Sequence[str],
    expected_counts: Mapping[str, int],
    expected_golden_sha256: str,
) -> dict[str, Any]:
    from .artifacts import (
        GOLDEN_OBSERVED_ALGORITHM,
        OUTPUT_FORMAT_COUNTERS,
        OUTPUT_MANIFEST_SCHEMA_VERSION,
        derive_golden_observed_sha256,
    )

    manifest = _require_object(value, context="outputs.manifest")
    _require_exact_keys(
        manifest,
        (
            "schema_version",
            "golden_observed_algorithm",
            "golden_observed_sha256",
            "artifacts",
        ),
        context="outputs.manifest",
    )
    if (
        manifest["schema_version"] != OUTPUT_MANIFEST_SCHEMA_VERSION
        or manifest["golden_observed_algorithm"] != GOLDEN_OBSERVED_ALGORITHM
    ):
        raise ContractError("outputs.manifest usa otro schema/algoritmo")
    artifacts = manifest["artifacts"]
    if not isinstance(artifacts, list):
        raise ContractError("outputs.manifest.artifacts debe ser lista")
    if [item.get("identity") if isinstance(item, dict) else None for item in artifacts] != list(
        expected_identities
    ):
        raise ContractError("outputs.manifest no conserva identidad/orden cerrado")
    normalized: list[dict[str, Any]] = []
    for ordinal, raw in enumerate(artifacts):
        artifact = _require_object(raw, context=f"outputs.manifest.artifacts[{ordinal}]")
        artifact_fields = (
            "relative_path",
            "identity",
            "ordinal",
            "format",
            "record_count",
            "count_evidence",
            "logical_bytes",
            "allocated_bytes",
            "allocation_reliable",
            "allocation_source",
            "sha256",
            "chunks",
            "reconciliation_sha256",
        )
        _require_exact_keys(
            artifact, artifact_fields, context=f"outputs.manifest.artifacts[{ordinal}]"
        )
        if artifact["ordinal"] != ordinal:
            raise ContractError("outputs.manifest contiene ordinal duplicado/permutado")
        identity_name = str(artifact["identity"])
        _require_text(artifact["relative_path"], context=f"outputs.artifact[{ordinal}].path")
        output_format = artifact["format"]
        if output_format not in OUTPUT_FORMAT_COUNTERS:
            raise ContractError("outputs.manifest contiene formato fuera del catalogo")
        if output_format == "bin":
            raise ContractError(
                "output bin no es calificable sin counter adapter independiente autorizado"
            )
        record_count = _require_non_negative_int(
            artifact["record_count"], context=f"outputs.artifact[{ordinal}].record_count"
        )
        if record_count != expected_counts.get(identity_name):
            raise ContractError("outputs.manifest contiene conteo distinto del golden firmado")
        count_evidence = _require_object(
            artifact["count_evidence"], context=f"outputs.artifact[{ordinal}].count_evidence"
        )
        _require_exact_keys(
            count_evidence,
            ("mode", "counter_id", "records", "output_sha256", "sidecar"),
            context=f"outputs.artifact[{ordinal}].count_evidence",
        )
        if (
            count_evidence["mode"] != "derived"
            or count_evidence["counter_id"] != OUTPUT_FORMAT_COUNTERS[output_format]
            or count_evidence["records"] != record_count
            or count_evidence["output_sha256"] != artifact["sha256"]
            or count_evidence["sidecar"] is not None
        ):
            raise ContractError("count_evidence no deriva del formato/output")
        validate_sha256(artifact["sha256"], context=f"outputs.artifact[{ordinal}].sha256")
        logical_bytes = _require_non_negative_int(
            artifact["logical_bytes"], context=f"outputs.artifact[{ordinal}].logical_bytes"
        )
        _require_non_negative_int(
            artifact["allocated_bytes"], context=f"outputs.artifact[{ordinal}].allocated_bytes"
        )
        _require_bool(
            artifact["allocation_reliable"],
            context=f"outputs.artifact[{ordinal}].allocation_reliable",
        )
        _require_text(
            artifact["allocation_source"],
            context=f"outputs.artifact[{ordinal}].allocation_source",
        )
        chunks = artifact["chunks"]
        if not isinstance(chunks, list):
            raise ContractError("outputs.manifest chunks no es lista")
        offset = 0
        for chunk_ordinal, raw_chunk in enumerate(chunks):
            chunk = _require_object(raw_chunk, context="outputs.artifact.chunk")
            _require_exact_keys(
                chunk,
                ("ordinal", "offset", "logical_bytes", "sha256"),
                context="outputs.artifact.chunk",
            )
            length = _require_non_negative_int(
                chunk["logical_bytes"], context="outputs.artifact.chunk.logical_bytes"
            )
            if length == 0 or chunk["ordinal"] != chunk_ordinal or chunk["offset"] != offset:
                raise ContractError("outputs.manifest chunks no son contiguos")
            validate_sha256(chunk["sha256"], context="outputs.artifact.chunk.sha256")
            offset += length
        if offset != logical_bytes:
            raise ContractError("outputs.manifest chunks no cubren bytes logicos")
        reconciliation = {
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
        if artifact["reconciliation_sha256"] != canonical_json_sha256(reconciliation):
            raise ContractError("outputs.manifest reconciliation_sha256 no deriva")
        normalized.append(artifact)
    derived_golden = derive_golden_observed_sha256(normalized)
    if (
        manifest["golden_observed_sha256"] != derived_golden
        or derived_golden != expected_golden_sha256
    ):
        raise ContractError("golden observado no deriva/reconcilia con fixture firmado")
    return manifest


def validate_authorization_consumption(
    value: Mapping[str, Any],
    *,
    authority: Mapping[str, Any],
    expected_attempt_id: str,
    verify_receipt: bool = False,
) -> dict[str, Any]:
    """Valida que el acto firmado tenga una única constancia durable ya consumida."""
    _require_exact_keys(
        value,
        (
            "authorization_id",
            "authorization_consumption_path_sha256",
            "state",
            "consumed_at_utc",
            "attempt_id",
            "authority_sha256",
            "receipt",
        ),
        context="authorization_consumption",
    )
    authorization_id = validate_sha256(
        value["authorization_id"], context="authorization_consumption.authorization_id"
    )
    path_sha256 = validate_sha256(
        value["authorization_consumption_path_sha256"],
        context="authorization_consumption.authorization_consumption_path_sha256",
    )
    if authorization_id != authority.get("authorization_id"):
        raise ContractError("consumo no liga authorization_id firmado")
    if path_sha256 != authority.get("authorization_consumption_path_sha256"):
        raise ContractError("consumo no liga la ruta one-shot firmada")
    if value["state"] != "consumed":
        raise ContractError("autorización START no consta consumida")
    consumed_at_utc = _require_text(
        value["consumed_at_utc"], context="authorization_consumption.consumed_at_utc"
    )
    if value["attempt_id"] != expected_attempt_id:
        raise ContractError("consumo no liga attempt_id")
    authority_sha256 = validate_sha256(
        value["authority_sha256"], context="authorization_consumption.authority_sha256"
    )
    if authority_sha256 != canonical_json_sha256(authority):
        raise ContractError("consumo no liga el acto de autoridad canónico")
    receipt = _require_object(value["receipt"], context="authorization_consumption.receipt")
    _require_exact_keys(
        receipt,
        ("path", "bytes", "sha256"),
        context="authorization_consumption.receipt",
    )
    receipt_path = Path(_require_text(receipt["path"], context="receipt.path"))
    if not receipt_path.is_absolute():
        raise ContractError("receipt one-shot debe declarar una ruta absoluta lexical")
    receipt_bytes = _require_non_negative_int(receipt["bytes"], context="receipt.bytes")
    receipt_sha256 = validate_sha256(receipt["sha256"], context="receipt.sha256")
    if authorization_consumption_path_digest(receipt_path) != path_sha256:
        raise ContractError("ruta real del receipt no reconcilia con el digest firmado")
    expected_receipt = {
        "schema_version": AUTHORIZATION_CONSUMPTION_SCHEMA_VERSION,
        "authorization_id": authorization_id,
        "attempt_id": expected_attempt_id,
        "authority_sha256": authority_sha256,
        "state": "consumed",
        "consumed_at_utc": consumed_at_utc,
    }
    expected_bytes = canonical_json_bytes(expected_receipt) + b"\n"
    if receipt_bytes != len(expected_bytes) or receipt_sha256 != sha256_bytes(expected_bytes):
        raise ContractError("identidad del receipt no deriva de su contenido canónico")
    if verify_receipt:
        observed_receipt = _read_descriptor_bound_regular_file(
            path=receipt_path,
            expected_bytes=len(expected_bytes),
            expected_sha256=sha256_bytes(expected_bytes),
            context="receipt one-shot",
            reject_hardlinks=True,
        )
        if observed_receipt != expected_bytes:
            raise ContractError("receipt one-shot cambió o no es JSON canónico exacto")
    return dict(value)


def _validate_unopened_single_link_regular_file(*, path: Path, context: str) -> Path:
    """Valida ruta absoluta/lexical, ancestros, leaf y nlink antes de leer contenido."""
    from .artifacts import is_reparse_or_symlink

    if not path.is_absolute():
        raise ContractError(f"{context}: la ruta debe ser absoluta")
    absolute = Path(os.path.abspath(os.fspath(path)))
    if os.path.normcase(os.fspath(path)) != os.path.normcase(os.fspath(absolute)):
        raise ContractError(f"{context}: la ruta no es lexical canónica")
    if any(is_reparse_or_symlink(item) for item in (absolute, *absolute.parents[:-1])):
        raise ContractError(f"{context}: ruta o ancestro reparse/symlink prohibido")
    try:
        metadata = absolute.lstat()
    except FileNotFoundError as exc:
        raise ContractError(f"{context}: archivo ausente") from exc
    if not stat.S_ISREG(metadata.st_mode):
        raise ContractError(f"{context}: no es archivo regular")
    if int(getattr(metadata, "st_nlink", 1)) != 1:
        raise ContractError(f"{context}: archivo con hardlinks prohibidos")
    return absolute


def _same_open_file(before: os.stat_result, after: os.stat_result) -> bool:
    """Compara identidad y metadatos que no deben variar durante una lectura."""
    return bool(
        os.path.samestat(before, after)
        and before.st_size == after.st_size
        and before.st_mtime_ns == after.st_mtime_ns
    )


def _read_descriptor_bound_regular_file(
    *,
    path: Path,
    context: str,
    expected_bytes: int | None = None,
    expected_sha256: str | None = None,
    reject_hardlinks: bool = False,
) -> bytes:
    """Lee una sola vez y liga path, descriptor, bytes y estado final sin TOCTOU."""
    from .artifacts import is_reparse_or_symlink

    if reject_hardlinks:
        absolute = _validate_unopened_single_link_regular_file(path=path, context=context)
    else:
        absolute = Path(os.path.abspath(os.fspath(path)))
        if (
            not os.path.lexists(absolute)
            or not absolute.is_file()
            or any(is_reparse_or_symlink(item) for item in (absolute, *absolute.parents[:-1]))
        ):
            raise ContractError(f"{context}: archivo ausente, no regular o atraviesa reparse point")
    try:
        before = absolute.lstat()
        with absolute.open("rb") as handle:
            opened = os.fstat(handle.fileno())
            if not stat.S_ISREG(opened.st_mode) or not _same_open_file(before, opened):
                raise ContractError(f"{context}: archivo cambió entre validación y apertura")
            if reject_hardlinks and int(getattr(opened, "st_nlink", 1)) != 1:
                raise ContractError(f"{context}: archivo con hardlinks prohibidos")
            payload = handle.read()
            after_read = os.fstat(handle.fileno())
            if not _same_open_file(opened, after_read):
                raise ContractError(f"{context}: archivo cambió durante la lectura")
        after_path = absolute.lstat()
    except FileNotFoundError as exc:
        raise ContractError(f"{context}: archivo desapareció durante la lectura") from exc
    except OSError as exc:
        raise ContractError(f"{context}: no se pudo leer de forma descriptor-bound") from exc
    if any(is_reparse_or_symlink(item) for item in (absolute, *absolute.parents[:-1])):
        raise ContractError(f"{context}: ruta cambió a reparse/symlink durante la lectura")
    if not _same_open_file(after_read, after_path):
        raise ContractError(f"{context}: path cambió antes de cerrar la validación")
    if reject_hardlinks and int(getattr(after_path, "st_nlink", 1)) != 1:
        raise ContractError(f"{context}: archivo con hardlinks prohibidos")
    if expected_bytes is not None and len(payload) != expected_bytes:
        raise ContractError(f"{context}: identidad viva no reconcilia bytes/hash")
    if expected_sha256 is not None and sha256_bytes(payload) != expected_sha256:
        raise ContractError(f"{context}: identidad viva no reconcilia bytes/hash")
    return payload


def _parse_canonical_json_object_bytes(payload: bytes, *, context: str) -> dict[str, Any]:
    """Parsea el mismo buffer atestado y exige su serialización canónica exacta."""
    try:
        raw: Any = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ContractError(f"{context}: JSON UTF-8 inválido") from exc
    if not isinstance(raw, dict):
        raise ContractError(f"{context}: JSON no es un objeto")
    value = cast(dict[str, Any], raw)
    if payload != canonical_json_bytes(value) + b"\n":
        raise ContractError(f"{context}: JSON no es canónico exacto")
    return value


def _validate_live_regular_file(
    *,
    path: Path,
    expected_bytes: int,
    expected_sha256: str,
    context: str,
    reject_hardlinks: bool = False,
) -> None:
    _read_descriptor_bound_regular_file(
        path=path,
        expected_bytes=expected_bytes,
        expected_sha256=expected_sha256,
        context=context,
        reject_hardlinks=reject_hardlinks,
    )


def _attempt_workdir_from_evidence_path(value: Any, *, context: str) -> Path:
    raw = Path(_require_text(value, context=context))
    if not raw.is_absolute() or raw.name != "attempt.json":
        raise ContractError(f"{context}: debe ser la ruta absoluta workdir/attempt.json")
    return Path(os.path.abspath(os.fspath(raw))).parent


def _validate_exact_sidecar_paths(
    sidecars: Sequence[Any],
    *,
    evidence_path: Any,
    terminal_identities: bool,
    verify_path_safety: bool,
    context: str,
) -> None:
    """Liga el catálogo de sidecars al único directorio telemetry del intento."""
    workdir = _attempt_workdir_from_evidence_path(evidence_path, context=f"{context}.evidence_path")
    telemetry_root = workdir / "telemetry"
    for index, raw in enumerate(sidecars):
        item = _require_object(raw, context=f"{context}.sidecars[{index}]")
        name = _require_text(item.get("name"), context=f"{context}.sidecars[{index}].name")
        if name not in ATTEMPT_SIDECAR_FILENAMES:
            raise ContractError(f"{context}.sidecars[{index}]: nombre fuera del catálogo")
        source = (
            _require_object(item.get("identity"), context=f"{context}.sidecars[{index}].identity")
            if terminal_identities
            else item
        )
        observed = Path(
            _require_text(source.get("path"), context=f"{context}.sidecars[{index}].path")
        )
        expected = telemetry_root / ATTEMPT_SIDECAR_FILENAMES[name]
        if os.path.normcase(os.path.abspath(os.fspath(observed))) != os.path.normcase(
            os.path.abspath(os.fspath(expected))
        ):
            raise ContractError(f"{context}.sidecars[{index}]: path no deriva del workdir")
        if verify_path_safety:
            from .artifacts import is_reparse_or_symlink

            absolute = Path(os.path.abspath(os.fspath(expected)))
            if any(is_reparse_or_symlink(path) for path in (absolute, *absolute.parents[:-1])):
                raise ContractError(
                    f"{context}.sidecars[{index}]: ruta o ancestro reparse prohibido"
                )


_HARNESS_IMPORT_ROOT_KINDS: Final[dict[str, str]] = {
    "_cffi_backend": "file",
    "cffi": "package_tree",
    "cryptography": "package_tree",
    "pyarrow": "package_tree",
    "threadpoolctl": "file",
}


def _validate_harness_runtime(
    value: Any,
    *,
    context: str,
    verify_artifacts: bool,
) -> dict[str, Any]:
    """Cierra y, cuando corresponde, reabre el runtime propio del arnés."""
    runtime = _require_object(value, context=context)
    _require_exact_keys(
        runtime,
        ("python_executable", "python_version", "implementation", "import_roots"),
        context=context,
    )
    executable = _require_object(
        runtime["python_executable"], context=f"{context}.python_executable"
    )
    _require_exact_keys(
        executable,
        ("path", "bytes", "sha256"),
        context=f"{context}.python_executable",
    )
    executable_path = Path(
        _require_text(executable["path"], context=f"{context}.python_executable.path")
    )
    executable_bytes = _require_non_negative_int(
        executable["bytes"], context=f"{context}.python_executable.bytes"
    )
    executable_sha256 = validate_sha256(
        executable["sha256"], context=f"{context}.python_executable.sha256"
    )
    _require_text(runtime["python_version"], context=f"{context}.python_version")
    _require_text(runtime["implementation"], context=f"{context}.implementation")
    roots = runtime["import_roots"]
    if not isinstance(roots, list) or len(roots) != len(_HARNESS_IMPORT_ROOT_KINDS):
        raise ContractError(f"{context}.import_roots no tiene el catálogo exacto")
    normalized_roots: list[dict[str, Any]] = []
    for index, raw_root in enumerate(roots):
        root = _require_object(raw_root, context=f"{context}.import_roots[{index}]")
        _require_exact_keys(
            root,
            ("name", "kind", "path", "files", "logical_bytes", "tree_sha256"),
            context=f"{context}.import_roots[{index}]",
        )
        name = _require_text(root["name"], context=f"{context}.import_roots[{index}].name")
        if name not in _HARNESS_IMPORT_ROOT_KINDS:
            raise ContractError(f"{context}.import_roots contiene dependencia no autorizada")
        if root["kind"] != _HARNESS_IMPORT_ROOT_KINDS[name]:
            raise ContractError(f"{context}.import_roots[{index}].kind no reconcilia")
        root_path = Path(
            _require_text(root["path"], context=f"{context}.import_roots[{index}].path")
        )
        files = _require_non_negative_int(
            root["files"], context=f"{context}.import_roots[{index}].files"
        )
        logical_bytes = _require_non_negative_int(
            root["logical_bytes"],
            context=f"{context}.import_roots[{index}].logical_bytes",
        )
        if files < 1:
            raise ContractError(f"{context}.import_roots[{index}].files debe ser positivo")
        tree_sha256 = validate_sha256(
            root["tree_sha256"], context=f"{context}.import_roots[{index}].tree_sha256"
        )
        if verify_artifacts:
            if root["kind"] == "file":
                from .artifacts import is_reparse_or_symlink

                if (
                    not os.path.lexists(root_path)
                    or not root_path.is_file()
                    or any(
                        is_reparse_or_symlink(item) for item in (root_path, *root_path.parents[:-1])
                    )
                ):
                    raise ContractError(
                        f"{context}.import_roots[{index}] contiene archivo ausente/reparse"
                    )
                live_sha256 = sha256_file(root_path)
                _validate_live_regular_file(
                    path=root_path,
                    expected_bytes=logical_bytes,
                    expected_sha256=live_sha256,
                    context=f"{context}.import_roots[{index}]",
                )
                observed_tree_sha256 = canonical_json_sha256(
                    [
                        {
                            "relative_path": root_path.name,
                            "logical_bytes": logical_bytes,
                            "sha256": live_sha256,
                        }
                    ]
                )
                if files != 1 or observed_tree_sha256 != tree_sha256:
                    raise ContractError(f"{context}.import_roots[{index}] cambió")
            else:
                from .artifacts import is_reparse_or_symlink

                selected_roots = [root_path]
                if name == "pyarrow":
                    selected_roots.append(root_path.parent / "pyarrow.libs")
                import_files: list[dict[str, Any]] = []
                for selected_root in selected_roots:
                    if not selected_root.is_dir() or is_reparse_or_symlink(selected_root):
                        raise ContractError(
                            f"{context}.import_roots[{index}] contiene raíz ausente/reparse"
                        )
                    for candidate in sorted(
                        selected_root.rglob("*"), key=lambda item: item.as_posix()
                    ):
                        if candidate.is_dir():
                            if is_reparse_or_symlink(candidate):
                                raise ContractError(
                                    f"{context}.import_roots[{index}] contiene directorio reparse"
                                )
                            continue
                        if is_reparse_or_symlink(candidate) or not candidate.is_file():
                            raise ContractError(
                                f"{context}.import_roots[{index}] contiene entrada no regular"
                            )
                        import_files.append(
                            {
                                "relative_path": candidate.relative_to(root_path.parent).as_posix(),
                                "logical_bytes": candidate.stat().st_size,
                                "sha256": sha256_file(candidate),
                            }
                        )
                import_files.sort(key=lambda item: str(item["relative_path"]))
                observed = {
                    "files": len(import_files),
                    "logical_bytes": sum(int(item["logical_bytes"]) for item in import_files),
                    "sha256": canonical_json_sha256(import_files),
                }
                if observed != {
                    "files": files,
                    "logical_bytes": logical_bytes,
                    "sha256": tree_sha256,
                }:
                    raise ContractError(f"{context}.import_roots[{index}] cambió")
        normalized_roots.append(dict(root))
    if [root["name"] for root in normalized_roots] != sorted(_HARNESS_IMPORT_ROOT_KINDS):
        raise ContractError(f"{context}.import_roots está duplicado o fuera de orden")
    if verify_artifacts:
        _validate_live_regular_file(
            path=executable_path,
            expected_bytes=executable_bytes,
            expected_sha256=executable_sha256,
            context=f"{context}.python_executable",
        )
    return dict(runtime)


def _validate_exclusive_write_target(path: Path, *, context: str) -> Path:
    """Rechaza destino existente y cualquier ancestro reparse antes de un O_EXCL."""
    from .artifacts import is_reparse_or_symlink

    absolute = Path(os.path.abspath(os.fspath(path)))
    parent = absolute.parent
    if (
        os.path.lexists(absolute)
        or not parent.is_dir()
        or any(is_reparse_or_symlink(item) for item in (parent, *parent.parents[:-1]))
    ):
        raise ContractError(f"{context}: destino existe o atraviesa reparse point")
    return absolute


def _validate_and_capture_post_start_source_identity(
    value: Any, *, context: str, verify_artifact: bool
) -> tuple[dict[str, Any], bytes | None]:
    from .artifacts import is_reparse_or_symlink

    source = _validate_preflight_source_identity(value, context=context)
    if not verify_artifact:
        return source, None
    path = Path(source["path"])
    if source["safe_regular_file"] is True:
        payload = _read_descriptor_bound_regular_file(
            path=path,
            expected_bytes=cast(int, source["bytes"]),
            expected_sha256=cast(str, source["sha256"]),
            context=context,
            reject_hardlinks=True,
        )
        return source, payload
    present = os.path.lexists(path)
    rejection = source["rejection"]
    if rejection == "absent" and present:
        raise ContractError(f"{context}: archivo declarado ausente apareció")
    if rejection == "symlink_or_reparse_point" and (not present or not is_reparse_or_symlink(path)):
        raise ContractError(f"{context}: rechazo reparse no reconcilia con el artefacto vivo")
    if rejection == "not_regular_file" and (
        not present or is_reparse_or_symlink(path) or path.is_file()
    ):
        raise ContractError(f"{context}: rechazo no-regular no reconcilia con el artefacto vivo")
    if rejection == "multiple_hardlinks" and (
        not present
        or is_reparse_or_symlink(path)
        or not path.is_file()
        or int(getattr(path.lstat(), "st_nlink", 1)) <= 1
    ):
        raise ContractError(f"{context}: rechazo hardlink no reconcilia con el artefacto vivo")
    return source, None


def _validate_post_start_source_identity(
    value: Any, *, context: str, verify_artifact: bool
) -> dict[str, Any]:
    source, _payload = _validate_and_capture_post_start_source_identity(
        value, context=context, verify_artifact=verify_artifact
    )
    return source


def _validate_causal_source(
    value: Any,
    *,
    expected_path: Path,
    expected_payload: bytes | None,
    verify_artifact: bool,
    context: str,
) -> dict[str, Any]:
    """Liga un snapshot durable a la fuente viva sin exigir que ésta sobreviva intacta."""
    causal = _require_object(value, context=context)
    _require_exact_keys(causal, ("snapshot", "observed", "matches_snapshot"), context=context)
    observed = _validate_post_start_source_identity(
        causal["observed"], context=f"{context}.observed", verify_artifact=verify_artifact
    )
    if Path(observed["path"]) != expected_path.resolve():
        raise ContractError(f"{context}.observed no liga la ruta causal esperada")
    snapshot_raw = causal["snapshot"]
    if expected_payload is None:
        if snapshot_raw is not None or causal["matches_snapshot"] is not False:
            raise ContractError(f"{context}: fuente aún no publicada exige snapshot null")
        return causal
    snapshot = _require_object(snapshot_raw, context=f"{context}.snapshot")
    _require_exact_keys(snapshot, ("path", "bytes", "sha256"), context=f"{context}.snapshot")
    snapshot_path = Path(_require_text(snapshot["path"], context=f"{context}.snapshot.path"))
    snapshot_bytes = _require_non_negative_int(
        snapshot["bytes"], context=f"{context}.snapshot.bytes"
    )
    snapshot_sha256 = validate_sha256(snapshot["sha256"], context=f"{context}.snapshot.sha256")
    if (
        snapshot_path != expected_path.resolve()
        or snapshot_bytes != len(expected_payload)
        or snapshot_sha256 != sha256_bytes(expected_payload)
    ):
        raise ContractError(f"{context}.snapshot no deriva del payload causal")
    expected_match = bool(
        observed["safe_regular_file"] is True
        and observed["bytes"] == snapshot_bytes
        and observed["sha256"] == snapshot_sha256
    )
    declared_match = _require_bool(
        causal["matches_snapshot"], context=f"{context}.matches_snapshot"
    )
    if declared_match is not expected_match:
        raise ContractError(f"{context}.matches_snapshot no deriva de la observación viva")
    return causal


def _validate_post_start_accounting(
    value: Any, *, context: str, source: str, allow_root_pid: bool
) -> dict[str, Any] | None:
    if value is None:
        return None
    accounting = _require_object(value, context=context)
    fields = [
        "source",
        "total_user_time_100ns",
        "total_kernel_time_100ns",
        "total_user_seconds",
        "total_kernel_seconds",
        "total_page_fault_count",
        "total_processes",
        "active_processes",
        "total_terminated_processes",
        "peak_process_memory_commit_bytes",
        "peak_job_memory_commit_bytes",
        "current_job_memory_commit_bytes",
        "memory_usage_information_supported",
        "io",
    ]
    if allow_root_pid:
        fields.insert(1, "root_pid")
    _require_exact_keys(accounting, fields, context=context)
    if accounting["source"] != source:
        raise ContractError(f"{context}.source inesperado")
    if allow_root_pid and accounting["root_pid"] is not None:
        root_pid = _require_non_negative_int(accounting["root_pid"], context=f"{context}.root_pid")
        if root_pid < 1:
            raise ContractError(f"{context}.root_pid debe ser positivo")
    for name in (
        "total_user_time_100ns",
        "total_kernel_time_100ns",
        "total_page_fault_count",
        "total_processes",
        "active_processes",
        "total_terminated_processes",
        "peak_process_memory_commit_bytes",
        "peak_job_memory_commit_bytes",
    ):
        _require_non_negative_int(accounting[name], context=f"{context}.{name}")
    for name in ("total_user_seconds", "total_kernel_seconds"):
        metric = accounting[name]
        if isinstance(metric, bool) or not isinstance(metric, int | float) or metric < 0:
            raise ContractError(f"{context}.{name}: se esperaba número no negativo")
    _validate_job_memory_usage_information(accounting, context=context)
    io = _require_object(accounting["io"], context=f"{context}.io")
    io_fields = (
        "read_operations",
        "write_operations",
        "other_operations",
        "read_bytes",
        "write_bytes",
        "other_bytes",
    )
    _require_exact_keys(io, io_fields, context=f"{context}.io")
    for name in io_fields:
        _require_non_negative_int(io[name], context=f"{context}.io.{name}")
    return accounting


def _validate_job_memory_usage_information(
    accounting: Mapping[str, Any], *, context: str, require_supported: bool = False
) -> int | None:
    """Liga soporte kernel y valor actual mediante una bicondicional fail-closed."""
    supported = _require_bool(
        accounting.get("memory_usage_information_supported"),
        context=f"{context}.memory_usage_information_supported",
    )
    current = accounting.get("current_job_memory_commit_bytes")
    if supported:
        normalized = _require_non_negative_int(
            current, context=f"{context}.current_job_memory_commit_bytes"
        )
    else:
        if current is not None:
            raise ContractError(
                f"{context}: JobMemoryUsageInformation unsupported exige current null"
            )
        normalized = None
    if require_supported and normalized is None:
        raise ContractError(
            f"{context}: intento calificable exige JobMemoryUsageInformation soportado"
        )
    return normalized


def _validate_post_start_authority(
    value: Any,
    *,
    unit: Mapping[str, Any],
    expected_attempt_id: str,
    trusted_authority_public_key_path: Path,
    allow_harness_test_authority: bool,
) -> dict[str, Any]:
    authority = _require_object(value, context="post_start_failure.authority")
    _require_exact_keys(
        authority,
        (
            "schema_version",
            "scope",
            "start_authorized",
            "authorization_id",
            "authorization_consumption_path_sha256",
            "authorized_unit",
            "attempt_id",
            "authorization_text_sha256",
            "document_sha256",
            "tooling_sha256",
            "schedule_sha256",
            "schedule_position",
            "signer_public_key_sha256",
            "signature_ed25519",
        ),
        context="post_start_failure.authority",
    )
    if authority["schema_version"] != AUTHORIZATION_SCHEMA_VERSION:
        raise ContractError("post-start authority usa otro schema")
    scope = authority["scope"]
    if scope == "harness-test-only":
        if not allow_harness_test_authority:
            raise ContractError("post-start productivo prohíbe autoridad harness-test-only")
    elif scope != "calibration-start":
        raise ContractError("post-start authority usa un scope desconocido")
    if authority["start_authorized"] is not (scope == "calibration-start"):
        raise ContractError("post-start authority no reconcilia start_authorized/scope")
    if authority["attempt_id"] != expected_attempt_id:
        raise ContractError("post-start authority no liga attempt_id")
    authorized_unit = validate_attempt_unit(
        _require_object(authority["authorized_unit"], context="post_start_failure.authorized_unit")
    )
    if authorized_unit != dict(unit):
        raise ContractError("post-start authority no liga la unidad exacta")
    for name in (
        "authorization_id",
        "authorization_consumption_path_sha256",
        "authorization_text_sha256",
        "tooling_sha256",
        "schedule_sha256",
        "signer_public_key_sha256",
    ):
        validate_sha256(authority[name], context=f"post_start_failure.authority.{name}")
    documents = _require_object(
        authority["document_sha256"], context="post_start_failure.authority.document_sha256"
    )
    if not documents:
        raise ContractError("post-start authority no censa documentos")
    for name, digest in documents.items():
        _require_text(name, context="post_start_failure.authority.document_sha256.nombre")
        validate_sha256(digest, context=f"post_start_failure.authority.document_sha256.{name}")
    position = authority["schedule_position"]
    if isinstance(position, bool) or not isinstance(position, int) or position < 0:
        raise ContractError("post-start authority.schedule_position inválida")
    verify_authority_signature(
        authority, trusted_authority_public_key_path=trusted_authority_public_key_path
    )
    return authority


def _validate_authorization_reservation(
    value: Any,
    *,
    authority: Mapping[str, Any],
    expected_attempt_id: str,
    verify_receipt: bool,
) -> dict[str, Any]:
    reservation = _require_object(value, context="pre_start_failure.authorization_reservation")
    _require_exact_keys(
        reservation,
        (
            "authorization_id",
            "authorization_consumption_path_sha256",
            "state",
            "consumed_at_utc",
            "attempt_id",
            "authority_sha256",
            "receipt",
        ),
        context="pre_start_failure.authorization_reservation",
    )
    if (
        reservation["authorization_id"] != authority["authorization_id"]
        or reservation["authorization_consumption_path_sha256"]
        != authority["authorization_consumption_path_sha256"]
        or reservation["attempt_id"] != expected_attempt_id
        or reservation["authority_sha256"] != canonical_json_sha256(authority)
    ):
        raise ContractError("reserva one-shot no liga autoridad/unidad exactas")
    state = reservation["state"]
    if state not in {"absent", "reserved", "consumed"}:
        raise ContractError("reserva pre-START exige state absent/reserved/consumed")
    consumed_at = reservation["consumed_at_utc"]
    if state == "consumed":
        _require_text(consumed_at, context="pre_start_failure.reservation.consumed_at_utc")
    elif consumed_at is not None:
        raise ContractError("reserva absent/reserved no admite consumed_at_utc")
    for name in (
        "authorization_id",
        "authorization_consumption_path_sha256",
        "authority_sha256",
    ):
        validate_sha256(reservation[name], context=f"pre_start_failure.reservation.{name}")
    receipt, captured_receipt = _validate_and_capture_post_start_source_identity(
        reservation["receipt"],
        context="pre_start_failure.authorization_reservation.receipt",
        verify_artifact=verify_receipt,
    )
    receipt_path = Path(receipt["path"])
    if not receipt_path.is_absolute():
        raise ContractError("receipt pre-START debe declarar una ruta absoluta lexical")
    if (
        authorization_consumption_path_digest(receipt_path)
        != reservation["authorization_consumption_path_sha256"]
    ):
        raise ContractError("ruta de reserva one-shot no liga el digest firmado")
    if state == "absent":
        if receipt != {
            "path": receipt["path"],
            "present": False,
            "safe_regular_file": False,
            "rejection": "absent",
            "bytes": None,
            "sha256": None,
        }:
            raise ContractError("reserva absent exige receipt ausente acreditado")
        return reservation

    if receipt["safe_regular_file"] is not True:
        raise ContractError("reserva reserved exige receipt regular seguro")
    receipt_payload = {
        "schema_version": AUTHORIZATION_CONSUMPTION_SCHEMA_VERSION,
        "authorization_id": reservation["authorization_id"],
        "attempt_id": expected_attempt_id,
        "authority_sha256": reservation["authority_sha256"],
        "state": state,
        "consumed_at_utc": consumed_at,
    }
    expected_bytes = canonical_json_bytes(receipt_payload) + b"\n"
    if receipt["bytes"] != len(expected_bytes) or receipt["sha256"] != sha256_bytes(expected_bytes):
        raise ContractError("identidad de reserva one-shot no deriva de su JSON canónico")
    if verify_receipt and captured_receipt != expected_bytes:
        raise ContractError("receipt pre-START vivo no es JSON canónico exacto")
    return reservation


def _validate_pre_start_handshake_source(
    value: Any,
    *,
    name: str,
    expected_attempt_id: str,
    verify_artifact: bool,
) -> dict[str, Any]:
    source, captured_payload = _validate_and_capture_post_start_source_identity(
        value,
        context=f"pre_start_failure.observed.handshake.{name}",
        verify_artifact=verify_artifact,
    )
    if source["present"] is True and source["safe_regular_file"] is not True:
        raise ContractError(f"{name} pre-START existe pero no es archivo regular seguro")
    if not verify_artifact or source["safe_regular_file"] is not True:
        return source
    if captured_payload is None:  # pragma: no cover - protegido por safe_regular_file.
        raise ContractError(f"{name} pre-START carece de captura descriptor-bound")
    payload = _parse_canonical_json_object_bytes(
        captured_payload,
        context=f"pre_start_failure.observed.handshake.{name}",
    )
    if name == "boot":
        _require_exact_keys(
            payload,
            ("protocol_version", "attempt_id", "pid", "heavy_work_started"),
            context="pre_start_failure.handshake.boot.payload",
        )
        if (
            payload["protocol_version"] != PROTOCOL_VERSION
            or payload["attempt_id"] != expected_attempt_id
            or _require_non_negative_int(payload["pid"], context="pre_start_failure.boot.pid") < 1
            or payload["heavy_work_started"] is not False
        ):
            raise ContractError("BOOT pre-START no liga intento/cero workload")
    elif name == "limits_applied":
        _require_exact_keys(
            payload,
            ("protocol_version", "attempt_id", "effective_limits", "resumed_primary_tids"),
            context="pre_start_failure.handshake.limits_applied.payload",
        )
        if (
            payload["protocol_version"] != PROTOCOL_VERSION
            or payload["attempt_id"] != expected_attempt_id
        ):
            raise ContractError("limits_applied pre-START no liga el intento")
        _validate_job_limits(
            payload["effective_limits"], context="pre_start_failure.limits_applied.effective_limits"
        )
        tids = payload["resumed_primary_tids"]
        if (
            not isinstance(tids, list)
            or not tids
            or any(isinstance(tid, bool) or not isinstance(tid, int) or tid < 1 for tid in tids)
            or tids != sorted(set(tids))
        ):
            raise ContractError("limits_applied no conserva TIDs reanudados exactos")
    elif name == "ready":
        _require_exact_keys(
            payload,
            (
                "protocol_version",
                "attempt_id",
                "pid",
                "effective_affinity_mask",
                "processor_groups",
                "native_pool_environment",
                "heavy_work_started",
            ),
            context="pre_start_failure.handshake.ready.payload",
        )
        if (
            payload["protocol_version"] != PROTOCOL_VERSION
            or payload["attempt_id"] != expected_attempt_id
            or _require_non_negative_int(payload["pid"], context="pre_start_failure.ready.pid") < 1
            or payload["heavy_work_started"] is not False
        ):
            raise ContractError("READY pre-START no liga intento/cero workload")
        affinity = _require_non_negative_int(
            payload["effective_affinity_mask"], context="pre_start_failure.ready.affinity"
        )
        if affinity <= 0 or affinity.bit_count() > MAX_LOGICAL_CPUS:
            raise ContractError("READY pre-START declara afinidad no confinada")
        groups = payload["processor_groups"]
        if not isinstance(groups, list) or len(groups) != 1:
            raise ContractError("READY pre-START no declara un único processor group")
        _require_non_negative_int(groups[0], context="pre_start_failure.ready.processor_group")
        pools = _require_object(
            payload["native_pool_environment"], context="pre_start_failure.ready.native_pools"
        )
        if not pools or not all(
            isinstance(key, str) and isinstance(item, str) for key, item in pools.items()
        ):
            raise ContractError("READY pre-START no conserva entorno de pools")
    else:
        raise ContractError(f"fuente handshake fuera del catálogo: {name}")
    return source


def validate_pre_start_failure_evidence(
    value: Mapping[str, Any],
    *,
    trusted_authority_public_key_path: Path,
    verify_artifacts: bool = False,
    allow_harness_test_authority: bool = False,
) -> dict[str, Any]:
    """Valida el terminal tras reserva/worker pero antes de cualquier START."""
    _require_exact_keys(
        value,
        (
            "schema_version",
            "phase",
            "identity",
            "authority",
            "authorization_reservation",
            "cause",
            "cleanup",
            "observed",
            "gates",
            "result",
        ),
        context="pre_start_failure",
    )
    if (
        value["schema_version"] != PRE_START_FAILURE_SCHEMA_VERSION
        or value["phase"] != "pre-start-terminal"
    ):
        raise ContractError("pre-start failure usa otro schema/phase")
    identity = _require_object(value["identity"], context="pre_start_failure.identity")
    _require_exact_keys(
        identity,
        ("attempt_id", "unit", "evidence_path", "wall_time_finished_utc"),
        context="pre_start_failure.identity",
    )
    unit = validate_attempt_unit(
        _require_object(identity["unit"], context="pre_start_failure.identity.unit")
    )
    expected_attempt_id = attempt_id(unit)
    if identity["attempt_id"] != expected_attempt_id:
        raise ContractError("pre-start failure attempt_id no deriva de la unidad")
    evidence_path = Path(
        _require_text(identity["evidence_path"], context="pre_start_failure.identity.evidence_path")
    )
    _require_text(
        identity["wall_time_finished_utc"],
        context="pre_start_failure.identity.wall_time_finished_utc",
    )
    authority = _validate_post_start_authority(
        value["authority"],
        unit=unit,
        expected_attempt_id=expected_attempt_id,
        trusted_authority_public_key_path=trusted_authority_public_key_path,
        allow_harness_test_authority=allow_harness_test_authority,
    )
    reservation = _validate_authorization_reservation(
        value["authorization_reservation"],
        authority=authority,
        expected_attempt_id=expected_attempt_id,
        # El snapshot causal se valida abajo; el terminal debe sobrevivir a corrupción viva.
        verify_receipt=False,
    )
    cause = _require_object(value["cause"], context="pre_start_failure.cause")
    _require_exact_keys(
        cause,
        ("classification", "error_type", "message", "traceback_sha256"),
        context="pre_start_failure.cause",
    )
    classification = cause["classification"]
    if classification not in PRE_START_FAILURE_CLASSIFICATIONS:
        raise ContractError("pre-start cause.classification fuera del catálogo")
    for name in ("error_type", "message"):
        _require_text(cause[name], context=f"pre_start_failure.cause.{name}")
    validate_sha256(cause["traceback_sha256"], context="pre_start_failure.cause.traceback_sha256")

    cleanup = _require_object(value["cleanup"], context="pre_start_failure.cleanup")
    _require_exact_keys(
        cleanup,
        (
            "worker_tree_empty",
            "client_tree_empty",
            "cleanup_complete",
            "job_accounting",
            "client_accounting",
            "errors",
        ),
        context="pre_start_failure.cleanup",
    )
    worker_empty = _require_bool(
        cleanup["worker_tree_empty"], context="pre_start_failure.cleanup.worker_tree_empty"
    )
    client_empty = _require_bool(
        cleanup["client_tree_empty"], context="pre_start_failure.cleanup.client_tree_empty"
    )
    errors = cleanup["errors"]
    if not isinstance(errors, list) or not all(
        isinstance(error, str) and error for error in errors
    ):
        raise ContractError("pre-start cleanup.errors debe ser lista de texto")
    if _require_bool(
        cleanup["cleanup_complete"], context="pre_start_failure.cleanup.cleanup_complete"
    ) is not (worker_empty and client_empty and not errors):
        raise ContractError("pre-start cleanup_complete no deriva de árboles/errores")
    _validate_post_start_accounting(
        cleanup["job_accounting"],
        context="pre_start_failure.cleanup.job_accounting",
        source="windows_job_object",
        allow_root_pid=False,
    )
    _validate_post_start_accounting(
        cleanup["client_accounting"],
        context="pre_start_failure.cleanup.client_accounting",
        source="windows_external_cleanup_job",
        allow_root_pid=True,
    )

    observed = _require_object(value["observed"], context="pre_start_failure.observed")
    _require_exact_keys(
        observed,
        (
            "causal_sources",
            "handshake",
            "sidecars",
            "unexpected_start_quarantine",
        ),
        context="pre_start_failure.observed",
    )
    handshake = _require_object(
        observed["handshake"], context="pre_start_failure.observed.handshake"
    )
    _require_exact_keys(
        handshake,
        ("boot", "limits_applied", "ready", "start"),
        context="pre_start_failure.observed.handshake",
    )
    validated_handshake = {
        name: _validate_pre_start_handshake_source(
            handshake[name],
            name=name,
            expected_attempt_id=expected_attempt_id,
            verify_artifact=verify_artifacts,
        )
        for name in ("boot", "limits_applied", "ready")
    }
    start_source = _validate_post_start_source_identity(
        handshake["start"],
        context="pre_start_failure.observed.handshake.start",
        verify_artifact=verify_artifacts,
    )
    expected_absent_start = {
        "path": start_source["path"],
        "present": False,
        "safe_regular_file": False,
        "rejection": "absent",
        "bytes": None,
        "sha256": None,
    }
    if start_source != expected_absent_start:
        raise ContractError("pre-start terminal exige START causalmente ausente")
    causal_sources = _require_object(
        observed["causal_sources"], context="pre_start_failure.observed.causal_sources"
    )
    _require_exact_keys(
        causal_sources,
        ("authority", "authorization_consumption", "start"),
        context="pre_start_failure.observed.causal_sources",
    )
    authority_causal = _require_object(
        causal_sources["authority"], context="pre_start_failure.causal.authority"
    )
    authority_snapshot = _require_object(
        authority_causal.get("snapshot"), context="pre_start_failure.causal.authority.snapshot"
    )
    _validate_causal_source(
        authority_causal,
        expected_path=Path(
            _require_text(
                authority_snapshot.get("path"),
                context="pre_start_failure.causal.authority.snapshot.path",
            )
        ),
        expected_payload=canonical_json_bytes(authority) + b"\n",
        verify_artifact=verify_artifacts,
        context="pre_start_failure.causal.authority",
    )
    receipt_payload = None
    if reservation["state"] != "absent":
        receipt_payload = (
            canonical_json_bytes(
                {
                    "schema_version": AUTHORIZATION_CONSUMPTION_SCHEMA_VERSION,
                    "authorization_id": reservation["authorization_id"],
                    "attempt_id": expected_attempt_id,
                    "authority_sha256": reservation["authority_sha256"],
                    "state": reservation["state"],
                    "consumed_at_utc": reservation["consumed_at_utc"],
                }
            )
            + b"\n"
        )
    receipt_identity = _require_object(
        reservation["receipt"], context="pre_start_failure.reservation.receipt"
    )
    _validate_causal_source(
        causal_sources["authorization_consumption"],
        expected_path=Path(str(receipt_identity["path"])),
        expected_payload=receipt_payload,
        verify_artifact=verify_artifacts,
        context="pre_start_failure.causal.authorization_consumption",
    )
    start_causal = _validate_causal_source(
        causal_sources["start"],
        expected_path=Path(str(start_source["path"])),
        expected_payload=None,
        verify_artifact=verify_artifacts,
        context="pre_start_failure.causal.start",
    )
    if start_causal["observed"] != expected_absent_start:
        raise ContractError("pre-start causal_sources.start no acredita ausencia exacta")
    presence = [
        validated_handshake[name]["safe_regular_file"]
        for name in ("boot", "limits_applied", "ready")
    ]
    if presence not in (
        [False, False, False],
        [True, False, False],
        [True, True, False],
        [True, True, True],
    ):
        raise ContractError("fuentes BOOT/limits/READY no conservan progresión monótona")

    sidecars = observed["sidecars"]
    expected_names = ATTEMPT_SIDECAR_NAMES
    if not isinstance(sidecars, list) or [
        item.get("name") for item in sidecars if isinstance(item, dict)
    ] != list(expected_names):
        raise ContractError("pre-start failure no preserva quince sidecars en orden")
    for index, raw in enumerate(sidecars):
        sidecar = _require_object(raw, context=f"pre_start_failure.observed.sidecars[{index}]")
        _require_exact_keys(
            sidecar, ("name", "identity"), context=f"pre_start_failure.observed.sidecars[{index}]"
        )
        _validate_post_start_source_identity(
            sidecar["identity"],
            context=f"pre_start_failure.observed.sidecars[{index}].identity",
            verify_artifact=verify_artifacts,
        )
    _validate_exact_sidecar_paths(
        sidecars,
        evidence_path=str(evidence_path),
        terminal_identities=True,
        verify_path_safety=verify_artifacts,
        context="pre_start_failure.observed",
    )
    quarantine_raw = observed["unexpected_start_quarantine"]
    if quarantine_raw is not None:
        quarantine = _require_object(
            quarantine_raw,
            context="pre_start_failure.observed.unexpected_start_quarantine",
        )
        _require_exact_keys(
            quarantine,
            (
                "original_snapshot",
                "quarantined",
                "moved_atomically",
                "worker_created",
                "authorization_gate",
                "role_claims",
            ),
            context="pre_start_failure.observed.unexpected_start_quarantine",
        )
        original = _require_object(
            quarantine["original_snapshot"],
            context="pre_start_failure.unexpected_start.original_snapshot",
        )
        _require_exact_keys(
            original,
            ("path", "bytes", "sha256"),
            context="pre_start_failure.unexpected_start.original_snapshot",
        )
        original_path = Path(
            _require_text(
                original["path"], context="pre_start_failure.unexpected_start.original.path"
            )
        )
        original_bytes = _require_non_negative_int(
            original["bytes"], context="pre_start_failure.unexpected_start.original.bytes"
        )
        original_sha256 = validate_sha256(
            original["sha256"], context="pre_start_failure.unexpected_start.original.sha256"
        )
        if os.path.normcase(original_path.resolve()) != os.path.normcase(
            Path(str(start_source["path"])).resolve()
        ):
            raise ContractError("quarantine START no liga la ruta causal original")
        quarantined = _validate_post_start_source_identity(
            quarantine["quarantined"],
            context="pre_start_failure.unexpected_start.quarantined",
            verify_artifact=verify_artifacts,
        )
        expected_quarantine_path = evidence_path.parent / "scratch" / "invalid-pre-start-token.json"
        if (
            os.path.normcase(Path(str(quarantined["path"])).resolve())
            != os.path.normcase(expected_quarantine_path.resolve())
            or quarantined["present"] is not True
            or quarantined["safe_regular_file"] is not True
            or quarantined["rejection"] is not None
            or quarantined["bytes"] != original_bytes
            or quarantined["sha256"] != original_sha256
        ):
            raise ContractError("quarantine START no conserva bytes/ruta regular exactos")
        if quarantine["moved_atomically"] is not True or not isinstance(
            quarantine["worker_created"], bool
        ):
            raise ContractError("quarantine START no acredita movimiento/estado del worker")

        def require_absent_identity(raw: Any, *, expected_path: Path, context: str) -> None:
            source = _validate_post_start_source_identity(
                raw, context=context, verify_artifact=verify_artifacts
            )
            expected = {
                "path": str(expected_path.resolve()),
                "present": False,
                "safe_regular_file": False,
                "rejection": "absent",
                "bytes": None,
                "sha256": None,
            }
            normalized = {**source, "path": str(Path(str(source["path"])).resolve())}
            if normalized != expected:
                raise ContractError(f"{context} no acredita ausencia exacta")

        control_root = Path(str(start_source["path"])).resolve().parent
        require_absent_identity(
            quarantine["authorization_gate"],
            expected_path=control_root / "internal-authorization-gate.json",
            context="pre_start_failure.unexpected_start.authorization_gate",
        )
        role_claims = _require_object(
            quarantine["role_claims"],
            context="pre_start_failure.unexpected_start.role_claims",
        )
        _require_exact_keys(
            role_claims,
            INTERNAL_AUTHORIZATION_ROLES,
            context="pre_start_failure.unexpected_start.role_claims",
        )
        receipt_path = Path(str(receipt_identity["path"]))
        for role in INTERNAL_AUTHORIZATION_ROLES:
            _reserved_path, claimed_path = internal_authorization_release_paths(
                receipt_path,
                attempt_id_value=expected_attempt_id,
                role=role,
            )
            require_absent_identity(
                role_claims[role],
                expected_path=claimed_path,
                context=f"pre_start_failure.unexpected_start.role_claims.{role}",
            )
        if classification not in {"invariant_failure", "evidence_incomplete"}:
            raise ContractError("quarantine START exige clasificación causal cerrada")
    gates = _require_object(value["gates"], context="pre_start_failure.gates")
    expected_gates = {
        "start_observed": False,
        "workload_started": False,
        "authorization_reserved": reservation["state"] == "reserved",
        "evidence_atomic": True,
    }
    _require_exact_keys(gates, tuple(expected_gates), context="pre_start_failure.gates")
    if gates != expected_gates:
        raise ContractError("pre-start gates no acreditan cero START/workload y estado de reserva")
    result = _require_object(value["result"], context="pre_start_failure.result")
    _require_exact_keys(
        result,
        ("classification", "statistically_eligible"),
        context="pre_start_failure.result",
    )
    if result != {"classification": classification, "statistically_eligible": False}:
        raise ContractError("pre-start result no reconcilia causa/no elegibilidad")
    if verify_artifacts:
        expected_evidence = canonical_json_bytes(value) + b"\n"
        observed_evidence = _read_descriptor_bound_regular_file(
            path=evidence_path,
            expected_bytes=len(expected_evidence),
            expected_sha256=sha256_bytes(expected_evidence),
            context="pre_start_failure.identity.evidence_path",
            reject_hardlinks=True,
        )
        if observed_evidence != expected_evidence:
            raise ContractError("pre-start evidencia final no es JSON canónico exacto")
    return dict(value)


def _validate_internal_start(
    value: Any,
    *,
    authority: Mapping[str, Any],
    expected_attempt_id: str,
    verify_artifact: bool,
    context: str,
) -> dict[str, Any]:
    start = _require_object(value, context=context)
    _require_exact_keys(
        start,
        (
            "protocol_version",
            "authorization_text_sha256",
            "ready_monotonic_ns",
            "start_monotonic_ns",
            "attempt_id",
            "path",
            "bytes",
            "sha256",
        ),
        context=context,
    )
    if (
        start["protocol_version"] != PROTOCOL_VERSION
        or start["authorization_text_sha256"] != authority["authorization_text_sha256"]
        or start["attempt_id"] != expected_attempt_id
    ):
        raise ContractError(f"{context}: START no liga protocolo/autoridad/unidad")
    ready_ns = _require_non_negative_int(
        start["ready_monotonic_ns"], context=f"{context}.ready_monotonic_ns"
    )
    start_ns = _require_non_negative_int(
        start["start_monotonic_ns"], context=f"{context}.start_monotonic_ns"
    )
    if ready_ns > start_ns:
        raise ContractError(f"{context}: START precede READY")
    start_path = Path(_require_text(start["path"], context=f"{context}.path"))
    start_bytes = _require_non_negative_int(start["bytes"], context=f"{context}.bytes")
    start_sha256 = validate_sha256(start["sha256"], context=f"{context}.sha256")
    payload = {
        "protocol_version": start["protocol_version"],
        "authorization_text_sha256": start["authorization_text_sha256"],
        "ready_monotonic_ns": ready_ns,
        "start_monotonic_ns": start_ns,
        "attempt_id": start["attempt_id"],
    }
    expected_bytes = canonical_json_bytes(payload) + b"\n"
    if start_bytes != len(expected_bytes) or start_sha256 != sha256_bytes(expected_bytes):
        raise ContractError(f"{context}: identidad no deriva del token START canónico")
    if verify_artifact:
        observed_start = _read_descriptor_bound_regular_file(
            path=start_path,
            expected_bytes=start_bytes,
            expected_sha256=start_sha256,
            context=context,
            reject_hardlinks=True,
        )
        if observed_start != expected_bytes:
            raise ContractError(f"{context}: token vivo no es JSON canónico exacto")
    return start


def _internal_binding_name(role: str) -> str:
    if role not in INTERNAL_AUTHORIZATION_ROLES:
        raise ContractError(f"rol interno fuera del catálogo: {role!r}")
    return {
        "worker": "worker_request_core_sha256",
        "adapter": "adapter_request_sha256",
        "candidate": "candidate_request_sha256",
        "ui-client": "ui_client_request_sha256",
    }[role]


def validate_internal_authorization_gate(
    value: Mapping[str, Any],
    *,
    expected_role: str,
    expected_request_payload_sha256: str,
    expected_capability_commitment_sha256: str,
    expected_workdir_path: Path,
    trusted_authority_public_key_path: Path,
    verify_artifacts: bool = True,
    allow_harness_test_authority: bool = False,
) -> dict[str, Any]:
    """Reabre toda la autoridad material antes de cargar un executor interno."""
    binding_name = _internal_binding_name(expected_role)
    expected_request_sha = validate_sha256(
        expected_request_payload_sha256, context="internal_gate.expected_request_payload_sha256"
    )
    expected_capability_sha = validate_sha256(
        expected_capability_commitment_sha256,
        context="internal_gate.expected_capability_commitment_sha256",
    )
    _require_exact_keys(
        value,
        (
            "schema_version",
            "attempt_id",
            "unit",
            "authority",
            "bindings",
            "sources",
            "tooling",
            "internal_authorization_precommit",
            "supervisor_instance_nonce",
            "authorization_consumption",
            "start",
        ),
        context="internal_authorization_gate",
    )
    if value["schema_version"] != INTERNAL_AUTHORIZATION_GATE_SCHEMA_VERSION:
        raise ContractError("internal authorization gate usa otro schema")
    unit = validate_attempt_unit(
        _require_object(value["unit"], context="internal_authorization_gate.unit")
    )
    expected_attempt_id = attempt_id(unit)
    if value["attempt_id"] != expected_attempt_id:
        raise ContractError("internal gate attempt_id no deriva de la unidad")
    authority = _validate_post_start_authority(
        value["authority"],
        unit=unit,
        expected_attempt_id=expected_attempt_id,
        trusted_authority_public_key_path=trusted_authority_public_key_path,
        allow_harness_test_authority=allow_harness_test_authority,
    )

    bindings = _require_object(value["bindings"], context="internal_authorization_gate.bindings")
    _require_exact_keys(
        bindings,
        (
            "workdir_path",
            "workdir_sha256",
            "worker_request_core_sha256",
            "adapter_request_sha256",
            "candidate_request_sha256",
            "ui_client_request_sha256",
            "worker_capability_commitment_sha256",
            "adapter_capability_commitment_sha256",
            "candidate_capability_commitment_sha256",
            "ui_client_capability_commitment_sha256",
        ),
        context="internal_authorization_gate.bindings",
    )
    expected_workdir = Path(os.path.abspath(os.fspath(expected_workdir_path)))
    declared_workdir = Path(
        os.path.abspath(
            os.fspath(
                Path(
                    _require_text(
                        bindings["workdir_path"],
                        context="internal_authorization_gate.bindings.workdir_path",
                    )
                )
            )
        )
    )
    if os.path.normcase(declared_workdir) != os.path.normcase(expected_workdir):
        raise ContractError("internal gate workdir_path no reconcilia con el executor")
    expected_workdir_sha = sha256_bytes(
        str(expected_workdir).replace("\\", "/").casefold().encode("utf-8")
    )
    if bindings["workdir_sha256"] != expected_workdir_sha:
        raise ContractError("internal gate workdir_sha256 no deriva de la ruta")
    for name in (
        "worker_request_core_sha256",
        "adapter_request_sha256",
        "candidate_request_sha256",
    ):
        validate_sha256(bindings[name], context=f"internal_authorization_gate.bindings.{name}")
    if bindings["ui_client_request_sha256"] is not None:
        validate_sha256(
            bindings["ui_client_request_sha256"],
            context="internal_authorization_gate.bindings.ui_client_request_sha256",
        )
    for name in (
        "worker_capability_commitment_sha256",
        "adapter_capability_commitment_sha256",
        "candidate_capability_commitment_sha256",
    ):
        validate_sha256(bindings[name], context=f"internal_authorization_gate.bindings.{name}")
    ui_capability = bindings["ui_client_capability_commitment_sha256"]
    if ui_capability is not None:
        validate_sha256(
            ui_capability,
            context="internal_authorization_gate.bindings.ui_client_capability_commitment_sha256",
        )
    if (bindings["ui_client_request_sha256"] is None) is not (ui_capability is None):
        raise ContractError("internal gate request/capability UI no reconcilian")
    if bindings[binding_name] != expected_request_sha:
        raise ContractError("internal gate no liga el payload exacto del executor")
    capability_binding_name = {
        "worker": "worker_capability_commitment_sha256",
        "adapter": "adapter_capability_commitment_sha256",
        "candidate": "candidate_capability_commitment_sha256",
        "ui-client": "ui_client_capability_commitment_sha256",
    }[expected_role]
    if bindings[capability_binding_name] != expected_capability_sha:
        raise ContractError("internal gate no liga la capability exacta del executor")

    sources = _require_object(value["sources"], context="internal_authorization_gate.sources")
    _require_exact_keys(
        sources,
        ("authority", "authorization_text", "trusted_authority_public_key", "schedule"),
        context="internal_authorization_gate.sources",
    )
    normalized_sources: dict[str, dict[str, Any]] = {}
    captured_sources: dict[str, bytes] = {}
    for name in sources:
        source, captured = _validate_and_capture_post_start_source_identity(
            sources[name],
            context=f"internal_authorization_gate.sources.{name}",
            verify_artifact=verify_artifacts,
        )
        normalized_sources[name] = source
        if captured is not None:
            captured_sources[name] = captured
    for name, source in normalized_sources.items():
        if source["safe_regular_file"] is not True:
            raise ContractError(f"internal gate exige fuente regular segura: {name}")
    authority_source = normalized_sources["authority"]
    expected_authority_bytes = canonical_json_bytes(authority) + b"\n"
    if authority_source["bytes"] != len(expected_authority_bytes) or authority_source[
        "sha256"
    ] != sha256_bytes(expected_authority_bytes):
        raise ContractError("internal gate source authority no deriva del objeto inline")
    if verify_artifacts and captured_sources.get("authority") != expected_authority_bytes:
        raise ContractError("internal gate authority viva no es JSON canónico exacto")
    trusted_source = normalized_sources["trusted_authority_public_key"]
    if os.path.normcase(os.path.abspath(str(trusted_source["path"]))) != os.path.normcase(
        os.path.abspath(os.fspath(trusted_authority_public_key_path))
    ):
        raise ContractError("internal gate trust anchor no coincide con el path externo")
    if verify_artifacts:
        trusted_payload = captured_sources.get("trusted_authority_public_key")
        if trusted_payload is None:
            raise ContractError("internal gate trust anchor carece de captura descriptor-bound")
        _, trusted_key_sha256 = _trusted_authority_key_identity_from_bytes(
            trusted_payload,
            context="internal_authorization_gate.sources.trusted_authority_public_key",
        )
        if trusted_key_sha256 != authority["signer_public_key_sha256"]:
            raise ContractError("internal gate trust anchor vivo no liga la autoridad")

    if verify_artifacts:
        schedule_payload = captured_sources.get("schedule")
        if schedule_payload is None:
            raise ContractError("internal gate schedule carece de captura descriptor-bound")
        schedule = _parse_canonical_json_object_bytes(
            schedule_payload, context="internal_authorization_gate.sources.schedule"
        )
        schedule_sha, schedule_position = validate_schedule(schedule, unit)
        if (
            schedule_sha != authority["schedule_sha256"]
            or schedule_position != authority["schedule_position"]
        ):
            raise ContractError("internal gate schedule no liga autoridad/unidad/posición")

    tooling = _require_object(value["tooling"], context="internal_authorization_gate.tooling")
    _require_exact_keys(
        tooling,
        (
            "protocol_version",
            "files",
            "harness_runtime",
            "manifest_sha256",
            "document_sha256",
            "document_paths",
        ),
        context="internal_authorization_gate.tooling",
    )
    if tooling["protocol_version"] != PROTOCOL_VERSION:
        raise ContractError("internal gate tooling usa otro protocolo")
    files = tooling["files"]
    if not isinstance(files, list) or not files:
        raise ContractError("internal gate tooling.files debe ser lista no vacía")
    manifest_files: list[dict[str, Any]] = []
    relative_paths: list[str] = []
    for index, raw in enumerate(files):
        item = _require_object(raw, context=f"internal_authorization_gate.tooling.files[{index}]")
        _require_exact_keys(
            item,
            ("relative_path", "path", "bytes", "sha256"),
            context=f"internal_authorization_gate.tooling.files[{index}]",
        )
        relative = _require_text(
            item["relative_path"],
            context=f"internal_authorization_gate.tooling.files[{index}].relative_path",
        )
        relative_paths.append(relative)
        path = Path(
            _require_text(
                item["path"], context=f"internal_authorization_gate.tooling.files[{index}].path"
            )
        )
        byte_count = _require_non_negative_int(
            item["bytes"], context=f"internal_authorization_gate.tooling.files[{index}].bytes"
        )
        digest = validate_sha256(
            item["sha256"], context=f"internal_authorization_gate.tooling.files[{index}].sha256"
        )
        if verify_artifacts:
            _validate_live_regular_file(
                path=path,
                expected_bytes=byte_count,
                expected_sha256=digest,
                context=f"internal_authorization_gate.tooling.files[{index}]",
                reject_hardlinks=True,
            )
        manifest_files.append({"relative_path": relative, "bytes": byte_count, "sha256": digest})
    if relative_paths != sorted(set(relative_paths)):
        raise ContractError("internal gate tooling.files está duplicado o fuera de orden")
    harness_runtime = _validate_harness_runtime(
        tooling["harness_runtime"],
        context="internal_authorization_gate.tooling.harness_runtime",
        verify_artifacts=verify_artifacts,
    )
    manifest = {
        "protocol_version": PROTOCOL_VERSION,
        "files": manifest_files,
        "harness_runtime": harness_runtime,
    }
    manifest_sha = canonical_json_sha256(manifest)
    if tooling["manifest_sha256"] != manifest_sha or manifest_sha != authority["tooling_sha256"]:
        raise ContractError("internal gate tooling manifest no liga archivos/autoridad")
    document_hashes = _require_object(
        tooling["document_sha256"], context="internal_authorization_gate.tooling.document_sha256"
    )
    document_paths = _require_object(
        tooling["document_paths"], context="internal_authorization_gate.tooling.document_paths"
    )
    if document_hashes != authority["document_sha256"] or set(document_paths) != set(
        document_hashes
    ):
        raise ContractError("internal gate documentos no ligan autoridad/censo")
    for name, digest in document_hashes.items():
        validate_sha256(digest, context=f"internal_authorization_gate.tooling.document.{name}")
        document_path = Path(
            _require_text(
                document_paths[name], context=f"internal_authorization_gate.tooling.path.{name}"
            )
        )
        if verify_artifacts:
            document_payload = _read_descriptor_bound_regular_file(
                path=document_path,
                context=f"internal_authorization_gate.tooling.document.{name}",
                reject_hardlinks=True,
            )
            if sha256_bytes(document_payload) != digest:
                raise ContractError(f"internal gate documento {name} cambió")

    statement_source = normalized_sources["authorization_text"]
    expected_statement = authorization_statement(
        unit,
        authorization_id=str(authority["authorization_id"]),
        authorization_consumption_path_sha256=str(
            authority["authorization_consumption_path_sha256"]
        ),
        tooling_sha256=str(authority["tooling_sha256"]),
        schedule_sha256=str(authority["schedule_sha256"]),
        schedule_position=cast(int, authority["schedule_position"]),
        scope=str(authority["scope"]),
    )
    if (
        statement_source["bytes"] != len(expected_statement)
        or statement_source["sha256"] != sha256_bytes(expected_statement)
        or authority["authorization_text_sha256"] != sha256_bytes(expected_statement)
    ):
        raise ContractError("internal gate statement no deriva de autoridad/unidad")
    if verify_artifacts and captured_sources.get("authorization_text") != expected_statement:
        raise ContractError("internal gate statement vivo no reconcilia")

    consumption = validate_authorization_consumption(
        _require_object(
            value["authorization_consumption"],
            context="internal_authorization_gate.authorization_consumption",
        ),
        authority=authority,
        expected_attempt_id=expected_attempt_id,
        verify_receipt=verify_artifacts,
    )
    start = _validate_internal_start(
        value["start"],
        authority=authority,
        expected_attempt_id=expected_attempt_id,
        verify_artifact=verify_artifacts,
        context="internal_authorization_gate.start",
    )
    nonce = _require_text(
        value["supervisor_instance_nonce"],
        context="internal_authorization_gate.supervisor_instance_nonce",
    )
    if (
        len(nonce) != 64
        or any(character not in "0123456789abcdef" for character in nonce)
        or nonce in {"0" * 64, "f" * 64}
    ):
        raise ContractError("internal gate exige nonce supervisor de 32 bytes hex")
    request_payload_sha256 = {
        "worker": cast(str, bindings["worker_request_core_sha256"]),
        "adapter": cast(str, bindings["adapter_request_sha256"]),
        "candidate": cast(str, bindings["candidate_request_sha256"]),
        "ui-client": cast(str | None, bindings["ui_client_request_sha256"]),
    }
    capability_commitment_sha256 = {
        "worker": cast(str, bindings["worker_capability_commitment_sha256"]),
        "adapter": cast(str, bindings["adapter_capability_commitment_sha256"]),
        "candidate": cast(str, bindings["candidate_capability_commitment_sha256"]),
        "ui-client": cast(str | None, bindings["ui_client_capability_commitment_sha256"]),
    }
    receipt = _require_object(
        consumption["receipt"], context="internal_authorization_gate.consumption.receipt"
    )
    precommit = validate_live_internal_authorization_precommit(
        _require_object(
            value["internal_authorization_precommit"],
            context="internal_authorization_gate.internal_authorization_precommit",
        ),
        authority=authority,
        unit=unit,
        tooling_sha256=cast(str, tooling["manifest_sha256"]),
        schedule_sha256=cast(str, authority["schedule_sha256"]),
        workdir_path=expected_workdir,
        request_payload_sha256=request_payload_sha256,
        capability_commitment_sha256=capability_commitment_sha256,
        authorization_consumption_path=Path(cast(str, receipt["path"])),
    )
    if precommit["supervisor_instance_nonce_sha256"] != sha256_bytes(bytes.fromhex(nonce)):
        raise ContractError("internal gate no abre el nonce comprometido antes de START")
    if start["attempt_id"] != precommit["attempt_id"]:
        raise ContractError("internal gate START/precommit no ligan el mismo intento")
    return dict(value)


def internal_authorization_precommit_path(
    authorization_consumption_path: Path, *, attempt_id_value: str
) -> Path:
    """Deriva la reserva del supervisor anterior al consumo humano y a START."""
    normalized_attempt_id = validate_sha256(
        attempt_id_value, context="internal_precommit.attempt_id"
    )
    receipt = Path(os.path.abspath(os.fspath(authorization_consumption_path)))
    return receipt.with_name(
        f".{receipt.name}.{normalized_attempt_id}.internal-authorization.precommit.json"
    )


def internal_authorization_precommit_value(
    *,
    authority: Mapping[str, Any],
    unit: Mapping[str, Any],
    tooling_sha256: str,
    schedule_sha256: str,
    workdir_path: Path,
    request_payload_sha256: Mapping[str, str | None],
    capability_commitment_sha256: Mapping[str, str | None],
    supervisor_instance_nonce: str,
) -> dict[str, Any]:
    """Liga antes de START todos los requests; el nonce nace sólo en el supervisor."""
    normalized_unit = validate_attempt_unit(unit)
    normalized_attempt_id = attempt_id(normalized_unit)
    if (
        authority.get("attempt_id") != normalized_attempt_id
        or authority.get("authorized_unit") != normalized_unit
    ):
        raise ContractError("internal precommit authority no liga unidad/attempt")
    authorization_id = validate_sha256(
        authority.get("authorization_id"), context="internal_precommit.authorization_id"
    )
    authority_sha256 = canonical_json_sha256(authority)
    normalized_tooling = validate_sha256(
        tooling_sha256, context="internal_precommit.tooling_sha256"
    )
    normalized_schedule = validate_sha256(
        schedule_sha256, context="internal_precommit.schedule_sha256"
    )
    if normalized_tooling != authority.get(
        "tooling_sha256"
    ) or normalized_schedule != authority.get("schedule_sha256"):
        raise ContractError("internal precommit tooling/schedule no ligan autoridad")
    if set(request_payload_sha256) != set(INTERNAL_AUTHORIZATION_ROLES):
        raise ContractError("internal precommit no liga exactamente los cuatro roles")
    if set(capability_commitment_sha256) != set(INTERNAL_AUTHORIZATION_ROLES):
        raise ContractError("internal precommit no liga exactamente cuatro capabilities")
    requests: dict[str, str | None] = {}
    for role in INTERNAL_AUTHORIZATION_ROLES:
        request_digest = request_payload_sha256[role]
        if request_digest is None:
            if role != "ui-client":
                raise ContractError(f"internal precommit exige request para {role}")
            requests[role] = None
        else:
            requests[role] = validate_sha256(
                request_digest, context=f"internal_precommit.request.{role}"
            )
    if (requests["ui-client"] is not None) is not (normalized_unit["flow_id"] == "F-UI"):
        raise ContractError("internal precommit UI request no reconcilia con el flujo")
    capabilities: dict[str, str | None] = {}
    for role in INTERNAL_AUTHORIZATION_ROLES:
        commitment = capability_commitment_sha256[role]
        if commitment is None:
            if role != "ui-client" or requests[role] is not None:
                raise ContractError(f"internal precommit capability ausente para {role}")
            capabilities[role] = None
        else:
            capabilities[role] = validate_sha256(
                commitment, context=f"internal_precommit.capability.{role}"
            )
    if (capabilities["ui-client"] is None) is not (requests["ui-client"] is None):
        raise ContractError("internal precommit request/capability UI no reconcilian")
    if (
        not isinstance(supervisor_instance_nonce, str)
        or len(supervisor_instance_nonce) != 64
        or any(character not in "0123456789abcdef" for character in supervisor_instance_nonce)
        or supervisor_instance_nonce in {"0" * 64, "f" * 64}
    ):
        raise ContractError("internal precommit exige nonce supervisor de 32 bytes hex")
    workdir = Path(os.path.abspath(os.fspath(workdir_path)))
    return {
        "schema_version": INTERNAL_AUTHORIZATION_PRECOMMIT_SCHEMA_VERSION,
        "attempt_id": normalized_attempt_id,
        "unit_sha256": canonical_json_sha256(normalized_unit),
        "authority_sha256": authority_sha256,
        "authorization_id": authorization_id,
        "tooling_sha256": normalized_tooling,
        "schedule_sha256": normalized_schedule,
        "workdir_path": str(workdir),
        "workdir_sha256": sha256_bytes(str(workdir).replace("\\", "/").casefold().encode("utf-8")),
        "request_payload_sha256": requests,
        "capability_commitment_sha256": capabilities,
        "supervisor_instance_nonce_sha256": sha256_bytes(bytes.fromhex(supervisor_instance_nonce)),
        "state": "reserved-pre-start",
    }


def validate_internal_authorization_precommit(
    value: Mapping[str, Any],
    *,
    authority: Mapping[str, Any],
    unit: Mapping[str, Any],
    tooling_sha256: str,
    schedule_sha256: str,
    workdir_path: Path,
    request_payload_sha256: Mapping[str, str | None],
    capability_commitment_sha256: Mapping[str, str | None],
) -> dict[str, Any]:
    """Recalcula el precommit; nunca acepta que el child lo cree o lo complete."""
    _require_exact_keys(
        value,
        (
            "schema_version",
            "attempt_id",
            "unit_sha256",
            "authority_sha256",
            "authorization_id",
            "tooling_sha256",
            "schedule_sha256",
            "workdir_path",
            "workdir_sha256",
            "request_payload_sha256",
            "capability_commitment_sha256",
            "supervisor_instance_nonce_sha256",
            "state",
        ),
        context="internal_authorization_precommit",
    )
    expected = internal_authorization_precommit_value(
        authority=authority,
        unit=unit,
        tooling_sha256=tooling_sha256,
        schedule_sha256=schedule_sha256,
        workdir_path=workdir_path,
        request_payload_sha256=request_payload_sha256,
        capability_commitment_sha256=capability_commitment_sha256,
        # El precommit persiste sólo el compromiso; el nonce vivo no se revela hasta el gate.
        supervisor_instance_nonce="01" * 32,
    )
    expected["supervisor_instance_nonce_sha256"] = validate_sha256(
        value.get("supervisor_instance_nonce_sha256"),
        context="internal_precommit.supervisor_instance_nonce_sha256",
    )
    if dict(value) != expected:
        raise ContractError("internal precommit no deriva de autoridad/unidad/requests")
    return dict(value)


def write_internal_authorization_precommit(
    *,
    authority: Mapping[str, Any],
    unit: Mapping[str, Any],
    tooling_sha256: str,
    schedule_sha256: str,
    workdir_path: Path,
    request_payload_sha256: Mapping[str, str | None],
    capability_commitment_sha256: Mapping[str, str | None],
    supervisor_instance_nonce: str,
    authorization_consumption_path: Path,
) -> dict[str, Any]:
    """Gasta la posibilidad de reservar executors antes del receipt/START mediante O_EXCL."""
    value = internal_authorization_precommit_value(
        authority=authority,
        unit=unit,
        tooling_sha256=tooling_sha256,
        schedule_sha256=schedule_sha256,
        workdir_path=workdir_path,
        request_payload_sha256=request_payload_sha256,
        capability_commitment_sha256=capability_commitment_sha256,
        supervisor_instance_nonce=supervisor_instance_nonce,
    )
    path = internal_authorization_precommit_path(
        authorization_consumption_path, attempt_id_value=str(value["attempt_id"])
    )
    path = _validate_exclusive_write_target(path, context="internal precommit")
    payload = canonical_json_bytes(value) + b"\n"
    try:
        with path.open("xb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    except FileExistsError as exc:
        raise ContractError("internal precommit ya existe; autorización gastada/replay") from exc
    if (
        _read_descriptor_bound_regular_file(
            path=path,
            expected_bytes=len(payload),
            expected_sha256=sha256_bytes(payload),
            context="internal precommit",
            reject_hardlinks=True,
        )
        != payload
    ):
        raise ContractError("internal precommit no reconcilia tras O_EXCL")
    return {
        "path": str(path),
        "bytes": len(payload),
        "sha256": sha256_bytes(payload),
        "value": value,
    }


def reserve_internal_authorization_bundle(
    *,
    authority: Mapping[str, Any],
    unit: Mapping[str, Any],
    tooling_sha256: str,
    schedule_sha256: str,
    workdir_path: Path,
    request_payload_sha256: Mapping[str, str | None],
    capability_commitment_sha256: Mapping[str, str | None],
    supervisor_instance_nonce: str,
    authorization_consumption_path: Path,
) -> dict[str, Any]:
    """Reserva precommit y cada rol aplicable antes de consumir el receipt humano."""
    precommit_publication = write_internal_authorization_precommit(
        authority=authority,
        unit=unit,
        tooling_sha256=tooling_sha256,
        schedule_sha256=schedule_sha256,
        workdir_path=workdir_path,
        request_payload_sha256=request_payload_sha256,
        capability_commitment_sha256=capability_commitment_sha256,
        supervisor_instance_nonce=supervisor_instance_nonce,
        authorization_consumption_path=authorization_consumption_path,
    )
    precommit = cast(dict[str, Any], precommit_publication["value"])
    releases: dict[str, dict[str, Any]] = {}
    for role in INTERNAL_AUTHORIZATION_ROLES:
        request_digest = request_payload_sha256[role]
        capability_digest = capability_commitment_sha256[role]
        if request_digest is None or capability_digest is None:
            continue
        releases[role] = write_internal_authorization_release_reservation(
            precommit=precommit,
            role=role,
            request_payload_sha256=request_digest,
            capability_commitment_sha256=capability_digest,
            authorization_consumption_path=authorization_consumption_path,
        )
    expected_roles = {"worker", "adapter", "candidate"} | (
        {"ui-client"} if unit["flow_id"] == "F-UI" else set()
    )
    if set(releases) != expected_roles:
        raise ContractError("bundle pre-START no reservó exactamente los roles aplicables")
    return {"precommit": precommit_publication, "releases": releases}


def validate_live_internal_authorization_precommit(
    identity: Mapping[str, Any],
    *,
    authority: Mapping[str, Any],
    unit: Mapping[str, Any],
    tooling_sha256: str,
    schedule_sha256: str,
    workdir_path: Path,
    request_payload_sha256: Mapping[str, str | None],
    capability_commitment_sha256: Mapping[str, str | None],
    authorization_consumption_path: Path,
) -> dict[str, Any]:
    """Reabre el precommit O_EXCL exacto; un gate derivado no puede sustituirlo."""
    _require_exact_keys(
        identity, ("path", "bytes", "sha256"), context="internal_precommit.identity"
    )
    expected_path = internal_authorization_precommit_path(
        authorization_consumption_path, attempt_id_value=attempt_id(unit)
    )
    observed_path = Path(
        _require_text(identity["path"], context="internal_precommit.identity.path")
    )
    if os.path.normcase(observed_path.resolve()) != os.path.normcase(expected_path.resolve()):
        raise ContractError("internal precommit path no deriva del receipt/attempt")
    byte_count = _require_non_negative_int(
        identity["bytes"], context="internal_precommit.identity.bytes"
    )
    digest = validate_sha256(identity["sha256"], context="internal_precommit.identity.sha256")
    value = _read_canonical_control_object(
        observed_path,
        context="internal_precommit.identity",
        expected_bytes=byte_count,
        expected_sha256=digest,
    )
    validate_internal_authorization_precommit(
        value,
        authority=authority,
        unit=unit,
        tooling_sha256=tooling_sha256,
        schedule_sha256=schedule_sha256,
        workdir_path=workdir_path,
        request_payload_sha256=request_payload_sha256,
        capability_commitment_sha256=capability_commitment_sha256,
    )
    return value


def internal_authorization_release_paths(
    authorization_consumption_path: Path, *, attempt_id_value: str, role: str
) -> tuple[Path, Path]:
    """Deriva rutas inmutables de reserva/claim desde el receipt humano one-shot."""
    _internal_binding_name(role)
    normalized_attempt_id = validate_sha256(attempt_id_value, context="internal_release.attempt_id")
    receipt = Path(os.path.abspath(os.fspath(authorization_consumption_path)))
    stem = f".{receipt.name}.{normalized_attempt_id}.{role}"
    return (
        receipt.with_name(f"{stem}.internal-release.reserved.json"),
        receipt.with_name(f"{stem}.internal-release.claimed.json"),
    )


def internal_authorization_release_binding(
    precommit: Mapping[str, Any],
    *,
    role: str,
    request_payload_sha256: str,
    capability_commitment_sha256: str,
) -> dict[str, Any]:
    """Deriva antes de START los enlaces del rol desde el precommit ya reservado."""
    _internal_binding_name(role)
    request_sha = validate_sha256(
        request_payload_sha256, context="internal_release.request_payload_sha256"
    )
    normalized_precommit = _require_object(precommit, context="internal_release.precommit")
    requests = _require_object(
        normalized_precommit.get("request_payload_sha256"),
        context="internal_release.precommit.requests",
    )
    if requests.get(role) != request_sha:
        raise ContractError("internal release request no coincide con el precommit")
    capability_sha = validate_sha256(
        capability_commitment_sha256,
        context="internal_release.capability_commitment_sha256",
    )
    capabilities = _require_object(
        normalized_precommit.get("capability_commitment_sha256"),
        context="internal_release.precommit.capabilities",
    )
    if capabilities.get(role) != capability_sha:
        raise ContractError("internal release capability no coincide con el precommit")
    return {
        "precommit_sha256": canonical_json_sha256(normalized_precommit),
        "authority_sha256": validate_sha256(
            normalized_precommit.get("authority_sha256"),
            context="internal_release.authority_sha256",
        ),
        "authorization_id": validate_sha256(
            normalized_precommit.get("authorization_id"),
            context="internal_release.authorization_id",
        ),
        "schedule_sha256": validate_sha256(
            normalized_precommit.get("schedule_sha256"),
            context="internal_release.schedule_sha256",
        ),
        "attempt_id": validate_sha256(
            normalized_precommit.get("attempt_id"), context="internal_release.attempt_id"
        ),
        "unit_sha256": validate_sha256(
            normalized_precommit.get("unit_sha256"), context="internal_release.unit_sha256"
        ),
        "tooling_sha256": validate_sha256(
            normalized_precommit.get("tooling_sha256"),
            context="internal_release.tooling_sha256",
        ),
        "role": role,
        "request_payload_sha256": request_sha,
        "capability_commitment_sha256": capability_sha,
    }


def _internal_release_value(
    precommit: Mapping[str, Any],
    *,
    role: str,
    request_payload_sha256: str,
    capability_commitment_sha256: str,
    state: str,
    gate_sha256: str | None,
    authorization_consumption_sha256: str | None,
    start_sha256: str | None,
    claimed_at_utc: str | None,
) -> dict[str, Any]:
    reserved = state == "reserved-pre-start"
    if state not in {"reserved-pre-start", "consumed"} or (claimed_at_utc is None) is not reserved:
        raise ContractError("estado/claimed_at del internal release no reconcilia")
    optional_claim_hashes = (
        gate_sha256,
        authorization_consumption_sha256,
        start_sha256,
    )
    if reserved:
        if any(item is not None for item in optional_claim_hashes):
            raise ContractError("internal release pre-START no puede anticipar gate/receipt/START")
    else:
        gate_sha256 = validate_sha256(gate_sha256, context="internal_release.gate_sha256")
        authorization_consumption_sha256 = validate_sha256(
            authorization_consumption_sha256,
            context="internal_release.authorization_consumption_sha256",
        )
        start_sha256 = validate_sha256(start_sha256, context="internal_release.start_sha256")
    return {
        "schema_version": INTERNAL_AUTHORIZATION_RELEASE_SCHEMA_VERSION,
        **internal_authorization_release_binding(
            precommit,
            role=role,
            request_payload_sha256=request_payload_sha256,
            capability_commitment_sha256=capability_commitment_sha256,
        ),
        "gate_sha256": gate_sha256,
        "authorization_consumption_sha256": authorization_consumption_sha256,
        "start_sha256": start_sha256,
        "state": state,
        "claimed_at_utc": claimed_at_utc,
    }


def validate_internal_authorization_release(
    value: Mapping[str, Any],
    *,
    precommit: Mapping[str, Any],
    role: str,
    request_payload_sha256: str,
    capability_commitment_sha256: str,
    expected_state: str,
    gate: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Valida reserva pre-START o claim posterior contra su precommit inmutable."""
    _require_exact_keys(
        value,
        (
            "schema_version",
            "precommit_sha256",
            "authority_sha256",
            "authorization_id",
            "schedule_sha256",
            "attempt_id",
            "unit_sha256",
            "tooling_sha256",
            "role",
            "request_payload_sha256",
            "capability_commitment_sha256",
            "gate_sha256",
            "authorization_consumption_sha256",
            "start_sha256",
            "state",
            "claimed_at_utc",
        ),
        context="internal_authorization_release",
    )
    if value["schema_version"] != INTERNAL_AUTHORIZATION_RELEASE_SCHEMA_VERSION:
        raise ContractError("internal release usa otro schema")
    claimed_at = value["claimed_at_utc"]
    if expected_state == "reserved-pre-start":
        if claimed_at is not None:
            raise ContractError("internal release reservado conserva claimed_at")
        gate_sha256 = None
        consumption_sha256 = None
        start_sha256 = None
    elif expected_state == "consumed":
        _require_text(claimed_at, context="internal_release.claimed_at_utc")
        if gate is None:
            raise ContractError("claim consumido exige gate validado")
        gate_sha256 = canonical_json_sha256(gate)
        consumption_sha256 = canonical_json_sha256(
            _require_object(
                gate.get("authorization_consumption"),
                context="internal_release.gate.consumption",
            )
        )
        start_sha256 = validate_sha256(
            _require_object(gate.get("start"), context="internal_release.gate.start").get("sha256"),
            context="internal_release.start_sha256",
        )
    else:
        raise ContractError("expected_state de internal release desconocido")
    expected = _internal_release_value(
        precommit,
        role=role,
        request_payload_sha256=request_payload_sha256,
        capability_commitment_sha256=capability_commitment_sha256,
        state=expected_state,
        gate_sha256=gate_sha256,
        authorization_consumption_sha256=consumption_sha256,
        start_sha256=start_sha256,
        claimed_at_utc=cast(str | None, claimed_at),
    )
    if dict(value) != expected:
        raise ContractError("internal release no deriva byte-exacto del gate/rol/request")
    return dict(value)


def write_internal_authorization_release_reservation(
    *,
    precommit: Mapping[str, Any],
    role: str,
    request_payload_sha256: str,
    capability_commitment_sha256: str,
    authorization_consumption_path: Path,
) -> dict[str, Any]:
    """Reserva con O_EXCL el único claim permitido para un rol interno."""
    reserved_path, claimed_path = internal_authorization_release_paths(
        authorization_consumption_path,
        attempt_id_value=str(precommit.get("attempt_id")),
        role=role,
    )
    if os.path.lexists(claimed_path):
        raise ContractError("internal release ya fue reclamado; replay rechazado")
    value = _internal_release_value(
        precommit,
        role=role,
        request_payload_sha256=request_payload_sha256,
        capability_commitment_sha256=capability_commitment_sha256,
        state="reserved-pre-start",
        gate_sha256=None,
        authorization_consumption_sha256=None,
        start_sha256=None,
        claimed_at_utc=None,
    )
    payload = canonical_json_bytes(value) + b"\n"
    reserved_path = _validate_exclusive_write_target(
        reserved_path, context="internal release reservado"
    )
    try:
        with reserved_path.open("xb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    except FileExistsError as exc:
        raise ContractError("internal release ya reservado; replay rechazado") from exc
    if (
        _read_descriptor_bound_regular_file(
            path=reserved_path,
            expected_bytes=len(payload),
            expected_sha256=sha256_bytes(payload),
            context="internal release reservado",
            reject_hardlinks=True,
        )
        != payload
    ):
        raise ContractError("internal release reservado no reconcilia tras O_EXCL")
    return {"path": str(reserved_path), "value": value}


def claim_internal_authorization_release(
    *,
    gate: Mapping[str, Any],
    role: str,
    request_payload_sha256: str,
    capability_commitment_sha256: str,
    authorization_consumption_path: Path,
) -> dict[str, Any]:
    """Reclama una sola vez mediante claim O_EXCL sin borrar la reserva causal."""
    reserved_path, claimed_path = internal_authorization_release_paths(
        authorization_consumption_path,
        attempt_id_value=str(gate.get("attempt_id")),
        role=role,
    )
    precommit_identity = _require_object(
        gate.get("internal_authorization_precommit"),
        context="internal_release.gate.internal_authorization_precommit",
    )
    precommit_path = Path(
        _require_text(precommit_identity.get("path"), context="internal_release.precommit.path")
    )
    precommit = _read_canonical_control_object(
        precommit_path,
        context="internal release precommit",
        expected_bytes=_require_non_negative_int(
            precommit_identity.get("bytes"), context="internal_release.precommit.bytes"
        ),
        expected_sha256=validate_sha256(
            precommit_identity.get("sha256"), context="internal_release.precommit.sha256"
        ),
    )
    reserved = _read_canonical_control_object(reserved_path, context="internal release reservado")
    validate_internal_authorization_release(
        reserved,
        precommit=precommit,
        role=role,
        request_payload_sha256=request_payload_sha256,
        capability_commitment_sha256=capability_commitment_sha256,
        expected_state="reserved-pre-start",
    )
    claimed_at = datetime.now(UTC).isoformat()
    claimed = _internal_release_value(
        precommit,
        role=role,
        request_payload_sha256=request_payload_sha256,
        capability_commitment_sha256=capability_commitment_sha256,
        state="consumed",
        gate_sha256=canonical_json_sha256(gate),
        authorization_consumption_sha256=canonical_json_sha256(
            _require_object(
                gate.get("authorization_consumption"),
                context="internal_release.gate.consumption",
            )
        ),
        start_sha256=validate_sha256(
            _require_object(gate.get("start"), context="internal_release.gate.start").get("sha256"),
            context="internal_release.start_sha256",
        ),
        claimed_at_utc=claimed_at,
    )
    payload = canonical_json_bytes(claimed) + b"\n"
    claimed_path = _validate_exclusive_write_target(claimed_path, context="internal release claim")
    try:
        with claimed_path.open("xb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    except FileExistsError as exc:
        raise ContractError("internal release ya reclamado; replay rechazado") from exc
    if (
        _read_descriptor_bound_regular_file(
            path=claimed_path,
            expected_bytes=len(payload),
            expected_sha256=sha256_bytes(payload),
            context="internal release claim",
            reject_hardlinks=True,
        )
        != payload
    ):
        raise ContractError("claim internal release no reconcilia tras O_EXCL")
    return {"path": str(claimed_path), "value": claimed}


def validate_post_start_failure_evidence(
    value: Mapping[str, Any],
    *,
    trusted_authority_public_key_path: Path,
    verify_artifacts: bool = False,
    allow_harness_test_authority: bool = False,
) -> dict[str, Any]:
    """Valida el terminal de emergencia posterior a START sin volverlo elegible."""
    _require_exact_keys(
        value,
        (
            "schema_version",
            "phase",
            "identity",
            "authority",
            "execution_context",
            "authorization_consumption",
            "start",
            "cause",
            "cleanup",
            "observed",
            "gates",
            "result",
        ),
        context="post_start_failure",
    )
    if (
        value["schema_version"] != POST_START_FAILURE_SCHEMA_VERSION
        or value["phase"] != "post-start-terminal"
    ):
        raise ContractError("post-start failure usa otro schema/phase")
    identity = _require_object(value["identity"], context="post_start_failure.identity")
    _require_exact_keys(
        identity,
        ("attempt_id", "unit", "evidence_path", "wall_time_finished_utc"),
        context="post_start_failure.identity",
    )
    unit = validate_attempt_unit(
        _require_object(identity["unit"], context="post_start_failure.identity.unit")
    )
    expected_attempt_id = attempt_id(unit)
    if identity["attempt_id"] != expected_attempt_id:
        raise ContractError("post-start failure attempt_id no deriva de la unidad")
    evidence_path = Path(
        _require_text(
            identity["evidence_path"], context="post_start_failure.identity.evidence_path"
        )
    )
    _require_text(
        identity["wall_time_finished_utc"],
        context="post_start_failure.identity.wall_time_finished_utc",
    )
    authority = _validate_post_start_authority(
        value["authority"],
        unit=unit,
        expected_attempt_id=expected_attempt_id,
        trusted_authority_public_key_path=trusted_authority_public_key_path,
        allow_harness_test_authority=allow_harness_test_authority,
    )
    execution_context = _require_object(
        value["execution_context"], context="post_start_failure.execution_context"
    )
    _require_exact_keys(
        execution_context,
        ("environment", "candidate", "tooling", "limits", "schedule"),
        context="post_start_failure.execution_context",
    )
    execution_environment_identity_sha256(execution_context)
    execution_candidate = _require_object(
        execution_context["candidate"],
        context="post_start_failure.execution_context.candidate",
    )
    execution_tooling = _require_object(
        execution_context["tooling"],
        context="post_start_failure.execution_context.tooling",
    )
    _require_exact_keys(
        execution_tooling,
        (
            "protocol_version",
            "manifest_sha256",
            "document_sha256",
            "harness_runtime",
            "harness_runtime_snapshot_sha256",
        ),
        context="post_start_failure.execution_context.tooling",
    )
    execution_limits = _require_object(
        execution_context["limits"],
        context="post_start_failure.execution_context.limits",
    )
    requested_limits = _require_object(
        execution_limits["requested"],
        context="post_start_failure.execution_context.limits.requested",
    )
    execution_schedule = _require_object(
        execution_context["schedule"],
        context="post_start_failure.execution_context.schedule",
    )
    execution_schedule_sha256, execution_schedule_position = validate_schedule(
        execution_schedule, unit
    )
    if (
        execution_candidate["manifest_sha256"] != unit["candidate_manifest_sha256"]
        or execution_tooling["manifest_sha256"] != authority["tooling_sha256"]
        or requested_limits["job_memory_commit_limit_bytes"] != CAPS[unit["cap_id"]]
        or requested_limits["preflight_deadline_seconds"] != PREFLIGHT_DEADLINE_SECONDS
        or requested_limits["handshake_deadline_seconds"] != HANDSHAKE_DEADLINE_SECONDS
        or requested_limits["workload_deadline_seconds"]
        != flow_spec(str(unit["flow_id"]), str(unit["flow_step"])).workload_deadline_seconds
        or execution_schedule_sha256 != authority["schedule_sha256"]
        or execution_schedule_position != authority["schedule_position"]
    ):
        raise ContractError("post-start execution_context no liga unidad/autoridad/deadlines")
    validate_authorization_consumption(
        _require_object(
            value["authorization_consumption"],
            context="post_start_failure.authorization_consumption",
        ),
        authority=authority,
        expected_attempt_id=expected_attempt_id,
        # causal_sources preserva snapshot y observación viva aun si el receipt se corrompió.
        verify_receipt=False,
    )

    start = _require_object(value["start"], context="post_start_failure.start")
    _require_exact_keys(
        start,
        (
            "protocol_version",
            "authorization_text_sha256",
            "ready_monotonic_ns",
            "start_monotonic_ns",
            "attempt_id",
            "path",
            "bytes",
            "sha256",
        ),
        context="post_start_failure.start",
    )
    if (
        start["protocol_version"] != PROTOCOL_VERSION
        or start["authorization_text_sha256"] != authority["authorization_text_sha256"]
        or start["attempt_id"] != expected_attempt_id
    ):
        raise ContractError("post-start token START no liga protocolo/autoridad/unidad")
    _require_non_negative_int(
        start["ready_monotonic_ns"], context="post_start_failure.start.ready_monotonic_ns"
    )
    _require_non_negative_int(
        start["start_monotonic_ns"], context="post_start_failure.start.start_monotonic_ns"
    )
    if start["ready_monotonic_ns"] > start["start_monotonic_ns"]:
        raise ContractError("post-start token START precede READY")
    start_path = Path(_require_text(start["path"], context="post_start_failure.start.path"))
    start_bytes = _require_non_negative_int(
        start["bytes"], context="post_start_failure.start.bytes"
    )
    start_sha256 = validate_sha256(start["sha256"], context="post_start_failure.start.sha256")
    expected_start = {
        "protocol_version": start["protocol_version"],
        "authorization_text_sha256": start["authorization_text_sha256"],
        "ready_monotonic_ns": start["ready_monotonic_ns"],
        "start_monotonic_ns": start["start_monotonic_ns"],
        "attempt_id": start["attempt_id"],
    }
    expected_start_bytes = canonical_json_bytes(expected_start) + b"\n"
    if start_bytes != len(expected_start_bytes) or start_sha256 != sha256_bytes(
        expected_start_bytes
    ):
        raise ContractError("post-start identidad del token START no deriva de su contenido")
    cause = _require_object(value["cause"], context="post_start_failure.cause")
    _require_exact_keys(
        cause,
        ("stage", "error_type", "message", "traceback_sha256"),
        context="post_start_failure.cause",
    )
    if cause["stage"] != "terminal_publication":
        raise ContractError("post-start cause.stage fuera del catálogo")
    for name in ("error_type", "message"):
        _require_text(cause[name], context=f"post_start_failure.cause.{name}")
    validate_sha256(cause["traceback_sha256"], context="post_start_failure.cause.traceback_sha256")

    cleanup = _require_object(value["cleanup"], context="post_start_failure.cleanup")
    _require_exact_keys(
        cleanup,
        (
            "worker_tree_empty",
            "client_tree_empty",
            "cleanup_complete",
            "job_accounting",
            "client_accounting",
            "errors",
        ),
        context="post_start_failure.cleanup",
    )
    worker_empty = _require_bool(
        cleanup["worker_tree_empty"], context="post_start_failure.cleanup.worker_tree_empty"
    )
    client_empty = _require_bool(
        cleanup["client_tree_empty"], context="post_start_failure.cleanup.client_tree_empty"
    )
    errors = cleanup["errors"]
    if not isinstance(errors, list) or not all(
        isinstance(error, str) and error for error in errors
    ):
        raise ContractError("post-start cleanup.errors debe ser una lista cerrada de texto")
    if _require_bool(
        cleanup["cleanup_complete"], context="post_start_failure.cleanup.cleanup_complete"
    ) is not (worker_empty and client_empty and not errors):
        raise ContractError("post-start cleanup_complete no deriva de árboles/errores")
    _validate_post_start_accounting(
        cleanup["job_accounting"],
        context="post_start_failure.cleanup.job_accounting",
        source="windows_job_object",
        allow_root_pid=False,
    )
    _validate_post_start_accounting(
        cleanup["client_accounting"],
        context="post_start_failure.cleanup.client_accounting",
        source="windows_external_cleanup_job",
        allow_root_pid=True,
    )

    observed = _require_object(value["observed"], context="post_start_failure.observed")
    _require_exact_keys(
        observed,
        (
            "causal_sources",
            "sidecars",
            "output_inventory",
            "final_manifest",
            "quarantined_manifest",
            "disk_final",
        ),
        context="post_start_failure.observed",
    )
    causal_sources = _require_object(
        observed["causal_sources"], context="post_start_failure.observed.causal_sources"
    )
    _require_exact_keys(
        causal_sources,
        ("authority", "authorization_consumption", "start"),
        context="post_start_failure.observed.causal_sources",
    )
    authority_causal = _require_object(
        causal_sources["authority"], context="post_start_failure.causal.authority"
    )
    authority_snapshot = _require_object(
        authority_causal.get("snapshot"), context="post_start_failure.causal.authority.snapshot"
    )
    _validate_causal_source(
        authority_causal,
        expected_path=Path(
            _require_text(
                authority_snapshot.get("path"),
                context="post_start_failure.causal.authority.snapshot.path",
            )
        ),
        expected_payload=canonical_json_bytes(authority) + b"\n",
        verify_artifact=verify_artifacts,
        context="post_start_failure.causal.authority",
    )
    consumption = _require_object(
        value["authorization_consumption"], context="post_start_failure.authorization_consumption"
    )
    consumption_receipt = _require_object(
        consumption["receipt"], context="post_start_failure.authorization_consumption.receipt"
    )
    expected_consumption_bytes = (
        canonical_json_bytes(
            {
                "schema_version": AUTHORIZATION_CONSUMPTION_SCHEMA_VERSION,
                "authorization_id": consumption["authorization_id"],
                "attempt_id": consumption["attempt_id"],
                "authority_sha256": consumption["authority_sha256"],
                "state": consumption["state"],
                "consumed_at_utc": consumption["consumed_at_utc"],
            }
        )
        + b"\n"
    )
    _validate_causal_source(
        causal_sources["authorization_consumption"],
        expected_path=Path(str(consumption_receipt["path"])),
        expected_payload=expected_consumption_bytes,
        verify_artifact=verify_artifacts,
        context="post_start_failure.causal.authorization_consumption",
    )
    _validate_causal_source(
        causal_sources["start"],
        expected_path=start_path,
        expected_payload=expected_start_bytes,
        verify_artifact=verify_artifacts,
        context="post_start_failure.causal.start",
    )
    sidecars = observed["sidecars"]
    expected_names = ATTEMPT_SIDECAR_NAMES
    if not isinstance(sidecars, list) or [
        item.get("name") for item in sidecars if isinstance(item, dict)
    ] != list(expected_names):
        raise ContractError("post-start failure no preserva los quince sidecars en orden")
    for index, raw in enumerate(sidecars):
        sidecar = _require_object(raw, context=f"post_start_failure.observed.sidecars[{index}]")
        _require_exact_keys(
            sidecar,
            ("name", "identity"),
            context=f"post_start_failure.observed.sidecars[{index}]",
        )
        _validate_post_start_source_identity(
            sidecar["identity"],
            context=f"post_start_failure.observed.sidecars[{index}].identity",
            verify_artifact=verify_artifacts,
        )
    _validate_exact_sidecar_paths(
        sidecars,
        evidence_path=str(evidence_path),
        terminal_identities=True,
        verify_path_safety=verify_artifacts,
        context="post_start_failure.observed",
    )
    for name in ("final_manifest", "quarantined_manifest"):
        _validate_post_start_source_identity(
            observed[name],
            context=f"post_start_failure.observed.{name}",
            verify_artifact=verify_artifacts,
        )

    inventory_observation = _require_object(
        observed["output_inventory"], context="post_start_failure.observed.output_inventory"
    )
    _require_exact_keys(
        inventory_observation,
        ("available", "value", "error"),
        context="post_start_failure.observed.output_inventory",
    )
    inventory_available = _require_bool(
        inventory_observation["available"],
        context="post_start_failure.observed.output_inventory.available",
    )
    if inventory_available:
        if inventory_observation["error"] is not None or not isinstance(
            inventory_observation["value"], list
        ):
            raise ContractError("post-start inventario disponible no reconcilia value/error")
        inventory_paths: list[str] = []
        for index, raw in enumerate(inventory_observation["value"]):
            item = _require_object(raw, context=f"post_start_failure.output_inventory[{index}]")
            _require_exact_keys(
                item,
                (
                    "relative_path",
                    "logical_bytes",
                    "allocated_bytes",
                    "allocation_reliable",
                    "allocation_source",
                    "sha256",
                ),
                context=f"post_start_failure.output_inventory[{index}]",
            )
            inventory_paths.append(
                _require_text(
                    item["relative_path"],
                    context=f"post_start_failure.output_inventory[{index}].relative_path",
                )
            )
            for metric in ("logical_bytes", "allocated_bytes"):
                _require_non_negative_int(
                    item[metric], context=f"post_start_failure.output_inventory[{index}].{metric}"
                )
            _require_bool(
                item["allocation_reliable"],
                context=f"post_start_failure.output_inventory[{index}].allocation_reliable",
            )
            _require_text(
                item["allocation_source"],
                context=f"post_start_failure.output_inventory[{index}].allocation_source",
            )
            validate_sha256(
                item["sha256"], context=f"post_start_failure.output_inventory[{index}].sha256"
            )
        if inventory_paths != sorted(set(inventory_paths)):
            raise ContractError("post-start output_inventory está duplicado o fuera de orden")
    elif (
        inventory_observation["value"] is not None
        or not isinstance(inventory_observation["error"], str)
        or not inventory_observation["error"]
    ):
        raise ContractError("post-start inventario no disponible no reconcilia value/error")

    disk_observation = _require_object(
        observed["disk_final"], context="post_start_failure.observed.disk_final"
    )
    _require_exact_keys(
        disk_observation,
        ("available", "value", "error"),
        context="post_start_failure.observed.disk_final",
    )
    disk_available = _require_bool(
        disk_observation["available"], context="post_start_failure.observed.disk_final.available"
    )
    if disk_available:
        if disk_observation["error"] is not None:
            raise ContractError("post-start disk_final disponible conserva error")
        _validate_root_census_map(
            disk_observation["value"], context="post_start_failure.observed.disk_final.value"
        )
    elif (
        disk_observation["value"] is not None
        or not isinstance(disk_observation["error"], str)
        or not disk_observation["error"]
    ):
        raise ContractError("post-start disk_final no disponible no reconcilia value/error")

    gates = _require_object(value["gates"], context="post_start_failure.gates")
    _require_exact_keys(
        gates,
        ("start_observed", "authorization_consumed", "evidence_atomic"),
        context="post_start_failure.gates",
    )
    if gates != {
        "start_observed": True,
        "authorization_consumed": True,
        "evidence_atomic": True,
    }:
        raise ContractError("post-start gates no acreditan START/consumo/atomicidad")
    result = _require_object(value["result"], context="post_start_failure.result")
    _require_exact_keys(
        result,
        ("classification", "statistically_eligible"),
        context="post_start_failure.result",
    )
    if result != {"classification": "evidence_incomplete", "statistically_eligible": False}:
        raise ContractError("post-start failure debe ser evidence_incomplete no elegible")
    if verify_artifacts:
        expected_evidence = canonical_json_bytes(value) + b"\n"
        observed_evidence = _read_descriptor_bound_regular_file(
            path=evidence_path,
            expected_bytes=len(expected_evidence),
            expected_sha256=sha256_bytes(expected_evidence),
            context="post_start_failure.identity.evidence_path",
            reject_hardlinks=True,
        )
        if observed_evidence != expected_evidence:
            raise ContractError("post-start evidencia final no es JSON canónico exacto")
    return dict(value)


def _validate_execution_environment(value: Any) -> dict[str, Any]:
    """Cierra y reconcilia el entorno estable que condiciona una medición H9R."""
    environment = _require_object(value, context="environment")
    _require_exact_keys(
        environment,
        (
            "platform",
            "windows_release",
            "windows_version",
            "machine",
            "processor",
            "logical_cpus_host",
            "processor_topology",
            "affinity_before_confinement",
            "system_memory",
            "power_scheme",
            "volume",
            "native_pool_environment",
        ),
        context="environment",
    )
    if environment["platform"] != "win32":
        raise ContractError("environment.platform no acredita Windows")
    for name in ("windows_release", "windows_version", "machine", "processor"):
        _require_text(environment[name], context=f"environment.{name}")
    host_cpus = _require_non_negative_int(
        environment["logical_cpus_host"], context="environment.logical_cpus_host"
    )
    if host_cpus < 1:
        raise ContractError("environment.logical_cpus_host debe ser positivo")

    topology = _require_object(
        environment["processor_topology"], context="environment.processor_topology"
    )
    _require_exact_keys(
        topology,
        (
            "active_group_count",
            "active_processor_count_by_group",
            "total_active_logical_processors",
            "primary_group",
            "primary_group_affinity_mask",
        ),
        context="environment.processor_topology",
    )
    group_count = _require_non_negative_int(
        topology["active_group_count"], context="environment.processor_topology.active_group_count"
    )
    counts = topology["active_processor_count_by_group"]
    if (
        group_count < 1
        or not isinstance(counts, list)
        or len(counts) != group_count
        or any(
            isinstance(count, bool) or not isinstance(count, int) or count < 1 for count in counts
        )
    ):
        raise ContractError("environment.processor_topology no censa todos los grupos activos")
    total_cpus = _require_non_negative_int(
        topology["total_active_logical_processors"],
        context="environment.processor_topology.total_active_logical_processors",
    )
    primary_group = _require_non_negative_int(
        topology["primary_group"], context="environment.processor_topology.primary_group"
    )
    primary_mask = _require_non_negative_int(
        topology["primary_group_affinity_mask"],
        context="environment.processor_topology.primary_group_affinity_mask",
    )
    if (
        total_cpus != sum(counts)
        or total_cpus != host_cpus
        or primary_group >= group_count
        or primary_mask < 1
        or primary_mask >> counts[primary_group]
    ):
        raise ContractError("environment.processor_topology no reconcilia CPU/grupo/afinidad")

    affinity = _require_object(
        environment["affinity_before_confinement"],
        context="environment.affinity_before_confinement",
    )
    _require_exact_keys(
        affinity,
        ("process_mask", "system_mask"),
        context="environment.affinity_before_confinement",
    )
    process_mask = _require_non_negative_int(
        affinity["process_mask"], context="environment.affinity_before_confinement.process_mask"
    )
    system_mask = _require_non_negative_int(
        affinity["system_mask"], context="environment.affinity_before_confinement.system_mask"
    )
    if (
        process_mask < 1
        or system_mask < 1
        or process_mask & ~system_mask
        or system_mask >> counts[primary_group]
        or primary_mask & ~process_mask
    ):
        raise ContractError("environment.affinity_before_confinement no reconcilia con topology")

    system_memory = _require_object(
        environment["system_memory"], context="environment.system_memory"
    )
    _require_exact_keys(
        system_memory,
        (
            "nominal_physical_bytes",
            "physical_total_bytes",
            "physical_visible_bytes",
            "physical_available_bytes",
            "commit_limit_bytes",
            "commit_available_bytes",
            "commit_used_bytes",
            "memory_load_percent",
            "virtual_total_bytes",
            "virtual_available_bytes",
        ),
        context="environment.system_memory",
    )
    for name in system_memory:
        _require_non_negative_int(system_memory[name], context=f"environment.system_memory.{name}")
    if (
        system_memory["nominal_physical_bytes"] < 1
        or system_memory["physical_total_bytes"] < 1
        or system_memory["physical_visible_bytes"] != system_memory["physical_total_bytes"]
        or system_memory["physical_visible_bytes"] > system_memory["nominal_physical_bytes"]
        or system_memory["physical_available_bytes"] > system_memory["physical_visible_bytes"]
        or system_memory["commit_limit_bytes"] < 1
        or system_memory["virtual_total_bytes"] < 1
        or system_memory["virtual_available_bytes"] > system_memory["virtual_total_bytes"]
    ):
        raise ContractError("environment.system_memory no reconcilia totales/visibilidad")
    observed_commit_total = (
        system_memory["commit_used_bytes"] + system_memory["commit_available_bytes"]
    )
    if observed_commit_total != system_memory["commit_limit_bytes"]:
        raise ContractError("commit usado/disponible no reconcilia con el límite")
    if system_memory["memory_load_percent"] > 100:
        raise ContractError("memory_load_percent excede 100")

    power = _require_object(environment["power_scheme"], context="environment.power_scheme")
    _require_exact_keys(
        power, ("available", "returncode", "stdout", "stderr"), context="environment.power_scheme"
    )
    if (
        power["available"] is not True
        or power["returncode"] != 0
        or not isinstance(power["returncode"], int)
    ):
        raise ContractError("environment.power_scheme no acredita esquema activo")
    _require_text(power["stdout"], context="environment.power_scheme.stdout")
    if not isinstance(power["stderr"], str):
        raise ContractError("environment.power_scheme.stderr debe ser texto")

    volume = _require_object(environment["volume"], context="environment.volume")
    _require_exact_keys(
        volume,
        (
            "path",
            "free_bytes",
            "volume_root",
            "volume_name",
            "volume_serial",
            "filesystem",
            "filesystem_flags",
            "maximum_component_length",
            "allocation_unit_bytes",
        ),
        context="environment.volume",
    )
    for name in ("path", "volume_root", "filesystem"):
        _require_text(volume[name], context=f"environment.volume.{name}")
    if not isinstance(volume["volume_name"], str):
        raise ContractError("environment.volume.volume_name debe ser texto")
    for name in (
        "free_bytes",
        "volume_serial",
        "filesystem_flags",
        "maximum_component_length",
        "allocation_unit_bytes",
    ):
        _require_non_negative_int(volume[name], context=f"environment.volume.{name}")
    if volume["allocation_unit_bytes"] < 1:
        raise ContractError("environment.volume.allocation_unit_bytes debe ser positivo")

    native_pools = _require_object(
        environment["native_pool_environment"], context="environment.native_pool_environment"
    )
    pool_names = {
        "OMP_NUM_THREADS",
        "MKL_NUM_THREADS",
        "OPENBLAS_NUM_THREADS",
        "NUMEXPR_NUM_THREADS",
        "BLIS_NUM_THREADS",
        "VECLIB_MAXIMUM_THREADS",
    }
    if set(native_pools) != pool_names or any(
        item is not None and not isinstance(item, str) for item in native_pools.values()
    ):
        raise ContractError("environment.native_pool_environment no tiene censo exacto")
    return environment


def execution_environment_identity_sha256(value: Mapping[str, Any]) -> str:
    """Deriva la identidad estable compartida por intentos y terminales post-START."""
    context = _require_object(value, context="execution_context")
    for name in ("environment", "candidate", "tooling", "limits"):
        if name not in context:
            raise ContractError(f"execution_context carece de {name}")
    environment = _validate_execution_environment(context["environment"])
    system_memory = _require_object(
        environment["system_memory"], context="execution_context.environment.system_memory"
    )
    volume = _require_object(environment["volume"], context="execution_context.environment.volume")
    power = _require_object(
        environment["power_scheme"], context="execution_context.environment.power_scheme"
    )

    candidate = _require_object(context["candidate"], context="execution_context.candidate")
    _require_exact_keys(
        candidate,
        ("manifest_sha256", "manifest_root", "source_sha", "wheel", "sdist", "lock", "runtime"),
        context="execution_context.candidate",
    )
    validate_sha256(
        candidate["manifest_sha256"], context="execution_context.candidate.manifest_sha256"
    )
    _require_text(candidate["manifest_root"], context="execution_context.candidate.manifest_root")
    _validate_git_sha(candidate["source_sha"], context="execution_context.candidate.source_sha")
    for name in ("wheel", "sdist", "lock"):
        _validate_file_identity(candidate[name], context=f"execution_context.candidate.{name}")
    runtime = _require_object(candidate["runtime"], context="execution_context.candidate.runtime")
    _require_exact_keys(
        runtime,
        ("python_executable", "environment", "installed_tree", "provenance"),
        context="execution_context.candidate.runtime",
    )
    for name in ("python_executable", "environment"):
        _validate_file_identity(
            runtime[name], context=f"execution_context.candidate.runtime.{name}"
        )
    installed_tree = _require_object(
        runtime["installed_tree"], context="execution_context.candidate.runtime.installed_tree"
    )
    _require_exact_keys(
        installed_tree,
        ("relative_path", "files", "logical_bytes", "sha256", "path"),
        context="execution_context.candidate.runtime.installed_tree",
    )
    for name in ("relative_path", "path"):
        _require_text(
            installed_tree[name],
            context=f"execution_context.candidate.runtime.installed_tree.{name}",
        )
    for name in ("files", "logical_bytes"):
        _require_non_negative_int(
            installed_tree[name],
            context=f"execution_context.candidate.runtime.installed_tree.{name}",
        )
    validate_sha256(
        installed_tree["sha256"],
        context="execution_context.candidate.runtime.installed_tree.sha256",
    )
    provenance = _validate_runtime_provenance(
        runtime["provenance"], context="execution_context.candidate.runtime.provenance"
    )
    if (
        provenance["installed_tree_sha256"] != installed_tree["sha256"]
        or provenance["wheel_sha256"]
        != _require_object(candidate["wheel"], context="execution_context.candidate.wheel")[
            "sha256"
        ]
        or provenance["lock_sha256"]
        != _require_object(candidate["lock"], context="execution_context.candidate.lock")["sha256"]
    ):
        raise ContractError("execution_context candidate provenance no liga artefactos")

    tooling = _require_object(context["tooling"], context="execution_context.tooling")
    base_tooling_keys = {
        "protocol_version",
        "manifest_sha256",
        "document_sha256",
        "harness_runtime",
    }
    if "runtime_descriptors" in tooling:
        # Un intento normal conserva el tooling completo. El terminal post-START
        # conserva el snapshot causal mínimo validado en su propio contrato.
        if not base_tooling_keys < set(tooling):
            raise ContractError("execution_context.tooling carece de identidad estable")
        runtime_descriptors = _require_object(
            tooling["runtime_descriptors"],
            context="execution_context.tooling.runtime_descriptors",
        )
        snapshot_identity = _require_object(
            runtime_descriptors.get("harness_runtime_snapshot"),
            context="execution_context.tooling.runtime_descriptors.harness_runtime_snapshot",
        )
        snapshot_sha256_value = snapshot_identity.get("sha256")
    else:
        _require_exact_keys(
            tooling,
            (*sorted(base_tooling_keys), "harness_runtime_snapshot_sha256"),
            context="execution_context.tooling",
        )
        snapshot_sha256_value = tooling["harness_runtime_snapshot_sha256"]
    if tooling.get("protocol_version") != PROTOCOL_VERSION:
        raise ContractError("execution_context.tooling usa otro protocolo")
    tooling_sha256 = validate_sha256(
        tooling.get("manifest_sha256"), context="execution_context.tooling.manifest_sha256"
    )
    document_sha256 = _require_object(
        tooling.get("document_sha256"), context="execution_context.tooling.document_sha256"
    )
    if not document_sha256:
        raise ContractError("execution_context.tooling.document_sha256 está vacío")
    for name, digest in document_sha256.items():
        _require_text(name, context="execution_context.tooling.document_sha256.nombre")
        validate_sha256(digest, context=f"execution_context.tooling.document_sha256.{name}")
    harness_runtime = _validate_harness_runtime(
        tooling["harness_runtime"],
        context="execution_context.tooling.harness_runtime",
        verify_artifacts=False,
    )
    snapshot_sha256 = validate_sha256(
        snapshot_sha256_value,
        context="execution_context.tooling.harness_runtime_snapshot_sha256",
    )

    limits = _require_object(context["limits"], context="execution_context.limits")
    _require_exact_keys(limits, ("requested", "effective"), context="execution_context.limits")
    requested = _require_object(limits["requested"], context="execution_context.limits.requested")
    _require_exact_keys(
        requested,
        (
            "logical_cpu_count",
            "affinity_mask",
            "job_memory_commit_limit_bytes",
            "preflight_deadline_seconds",
            "handshake_deadline_seconds",
            "workload_deadline_seconds",
        ),
        context="execution_context.limits.requested",
    )
    for name in ("logical_cpu_count", "affinity_mask", "job_memory_commit_limit_bytes"):
        _require_non_negative_int(
            requested[name], context=f"execution_context.limits.requested.{name}"
        )
    if (
        requested["logical_cpu_count"] not in {1, 2, 3, 4}
        or requested["affinity_mask"] <= 0
        or requested["affinity_mask"].bit_count() != requested["logical_cpu_count"]
        or requested["job_memory_commit_limit_bytes"] not in CAPS.values()
    ):
        raise ContractError("execution_context.limits.requested no reconcilia CPU/cap")
    for name in (
        "preflight_deadline_seconds",
        "handshake_deadline_seconds",
        "workload_deadline_seconds",
    ):
        deadline = requested[name]
        if isinstance(deadline, bool) or not isinstance(deadline, int | float) or deadline <= 0:
            raise ContractError(f"execution_context.limits.requested.{name} inválido")
    effective = _validate_job_limits(
        limits["effective"], context="execution_context.limits.effective"
    )
    if (
        effective["logical_cpu_count"] != requested["logical_cpu_count"]
        or effective["affinity_mask"] != requested["affinity_mask"]
        or effective["job_memory_commit_limit_bytes"] != requested["job_memory_commit_limit_bytes"]
    ):
        raise ContractError("execution_context.limits requested/effective no reconcilian")

    def stable_file(raw: Any) -> dict[str, Any]:
        item = _require_object(raw, context="execution_context.stable_file")
        return {
            "bytes": item["bytes"],
            "allocated_bytes": item["allocated_bytes"],
            "sha256": item["sha256"],
        }

    identity = {
        "host": {
            name: environment[name]
            for name in (
                "platform",
                "windows_release",
                "windows_version",
                "machine",
                "processor",
                "logical_cpus_host",
                "processor_topology",
                "affinity_before_confinement",
            )
        },
        "system_memory": {
            name: system_memory[name]
            for name in (
                "nominal_physical_bytes",
                "physical_total_bytes",
                "physical_visible_bytes",
                "commit_limit_bytes",
                "virtual_total_bytes",
            )
        },
        "power_scheme": {
            "available": power["available"],
            "returncode": power["returncode"],
            "stdout": power["stdout"],
        },
        "volume": {
            name: volume[name]
            for name in (
                "volume_name",
                "volume_serial",
                "filesystem",
                "filesystem_flags",
                "maximum_component_length",
                "allocation_unit_bytes",
            )
        },
        "native_pool_environment": environment["native_pool_environment"],
        "candidate": {
            "source_sha": candidate["source_sha"],
            "wheel_sha256": _require_object(candidate["wheel"], context="candidate.wheel")[
                "sha256"
            ],
            "sdist_sha256": _require_object(candidate["sdist"], context="candidate.sdist")[
                "sha256"
            ],
            "lock_sha256": _require_object(candidate["lock"], context="candidate.lock")["sha256"],
            "python_executable": stable_file(runtime["python_executable"]),
            "environment": stable_file(runtime["environment"]),
            "installed_tree": {
                name: installed_tree[name] for name in ("files", "logical_bytes", "sha256")
            },
            "provenance": {
                name: provenance[name]
                for name in (
                    "probe_schema_version",
                    "isolation_flags",
                    "no_site",
                    "distribution",
                    "version",
                    "metadata_sha256",
                    "record_sha256",
                    "record_entries",
                    "imported_package_sha256",
                    "installed_tree_sha256",
                    "wheel_sha256",
                    "lock_sha256",
                    "probe_payload_sha256",
                )
            },
        },
        "tooling": {
            "protocol_version": tooling["protocol_version"],
            "manifest_sha256": tooling_sha256,
            "document_sha256": document_sha256,
            "harness_runtime": {
                "python_executable": {
                    "bytes": harness_runtime["python_executable"]["bytes"],
                    "sha256": harness_runtime["python_executable"]["sha256"],
                },
                "python_version": harness_runtime["python_version"],
                "implementation": harness_runtime["implementation"],
                "import_roots": [
                    {
                        name: root[name]
                        for name in (
                            "name",
                            "kind",
                            "files",
                            "logical_bytes",
                            "tree_sha256",
                        )
                    }
                    for root in harness_runtime["import_roots"]
                ],
            },
            "harness_runtime_snapshot_sha256": snapshot_sha256,
        },
        "limits": {"requested": requested, "effective": effective},
    }
    return canonical_json_sha256(identity)


def _validate_ui_ingress_response_order(
    request_event: Mapping[str, Any], response_event: Mapping[str, Any]
) -> None:
    """Liga el acuse del cliente al ingress del servicio sin confundir sus relojes."""
    request_ns = _require_non_negative_int(
        request_event.get("monotonic_ns"), context="ui.ingress.monotonic_ns"
    )
    response_ns = _require_non_negative_int(
        response_event.get("monotonic_ns"), context="ui.response.monotonic_ns"
    )
    if (
        request_event.get("event") != "first_open_or_byte"
        or request_event.get("kind") != "first_byte"
        or request_event.get("provider") != "harness_owned_candidate_http_ingress_v1"
        or request_event.get("request_id") != response_event.get("request_id")
        or response_ns < request_ns
    ):
        raise ContractError("respuesta ui_first_byte no sucede causalmente al ingress consumidor")


def _read_canonical_control_object(
    path: Path,
    *,
    context: str,
    expected_bytes: int | None = None,
    expected_sha256: str | None = None,
) -> dict[str, Any]:
    """Parsea un control desde la única captura descriptor-bound que se atesta."""
    payload = _read_descriptor_bound_regular_file(
        path=path,
        expected_bytes=expected_bytes,
        expected_sha256=expected_sha256,
        context=context,
        reject_hardlinks=True,
    )
    return _parse_canonical_json_object_bytes(payload, context=context)


def _validate_candidate_file_identity(
    value: Any, *, expected_path: Path, context: str, verify_artifact: bool = True
) -> dict[str, Any]:
    """Valida una identidad ``path/logical_bytes/sha256`` contra el archivo vivo exacto."""
    identity = _require_object(value, context=context)
    _require_exact_keys(identity, ("path", "logical_bytes", "sha256"), context=context)
    path = Path(_require_text(identity["path"], context=f"{context}.path"))
    logical_bytes = _require_non_negative_int(
        identity["logical_bytes"], context=f"{context}.logical_bytes"
    )
    digest = validate_sha256(identity["sha256"], context=f"{context}.sha256")
    absolute_path = Path(os.path.abspath(os.fspath(path)))
    absolute_expected = Path(os.path.abspath(os.fspath(expected_path)))
    if os.path.normcase(os.fspath(absolute_path)) != os.path.normcase(os.fspath(absolute_expected)):
        raise ContractError(f"{context}: path no deriva del control cerrado")
    if verify_artifact:
        _validate_live_regular_file(
            path=path,
            expected_bytes=logical_bytes,
            expected_sha256=digest,
            context=context,
            reject_hardlinks=True,
        )
    return {"path": str(absolute_path), "logical_bytes": logical_bytes, "sha256": digest}


def _validate_candidate_process_identity(value: Any, *, context: str) -> dict[str, int]:
    process = _require_object(value, context=context)
    _require_exact_keys(process, ("pid", "creation_time_100ns"), context=context)
    pid = _require_non_negative_int(process["pid"], context=f"{context}.pid")
    creation = _require_non_negative_int(
        process["creation_time_100ns"], context=f"{context}.creation_time_100ns"
    )
    if pid < 1 or creation < 1:
        raise ContractError(f"{context}: PID/creation time deben ser positivos")
    return {"pid": pid, "creation_time_100ns": creation}


def _validate_candidate_process_census(
    value: Any,
    *,
    root_process: Mapping[str, Any],
    expected_total_processes: int,
) -> dict[str, Any]:
    """Liga cada PID+creation observado por el completion port al Job hijo."""
    census = _require_object(value, context="candidate-result.candidate_process_census")
    _require_exact_keys(
        census,
        ("source", "total_processes", "processes"),
        context="candidate-result.candidate_process_census",
    )
    processes_raw = census["processes"]
    if (
        census["source"] != "windows_job_completion_port_v1"
        or census["total_processes"] != expected_total_processes
        or expected_total_processes < 1
        or not isinstance(processes_raw, list)
        or len(processes_raw) != expected_total_processes
    ):
        raise ContractError("candidate process census no liga accounting kernel")
    processes = [
        _validate_candidate_process_identity(
            item,
            context=f"candidate-result.candidate_process_census.processes[{index}]",
        )
        for index, item in enumerate(processes_raw)
    ]
    identities = [(item["pid"], item["creation_time_100ns"]) for item in processes]
    if identities != sorted(set(identities)):
        raise ContractError("candidate process census repite o desordena PID+creation")
    root = _validate_candidate_process_identity(
        root_process, context="candidate-result.candidate_process"
    )
    if (root["pid"], root["creation_time_100ns"]) not in set(identities):
        raise ContractError("candidate process census omite el proceso raíz exacto")
    return {**census, "processes": processes}


def _validate_candidate_job_accounting(
    value: Any, *, expected_total_processes: int
) -> dict[str, Any]:
    """Recalcula el censo multiproceso contra el accounting durable del Job hijo."""
    accounting = _require_object(value, context="candidate-result.candidate_job_accounting")
    _require_exact_keys(
        accounting,
        (
            "source",
            "total_user_time_100ns",
            "total_kernel_time_100ns",
            "total_user_seconds",
            "total_kernel_seconds",
            "total_page_fault_count",
            "total_processes",
            "active_processes",
            "total_terminated_processes",
            "peak_process_memory_commit_bytes",
            "peak_job_memory_commit_bytes",
            "current_job_memory_commit_bytes",
            "memory_usage_information_supported",
            "io",
        ),
        context="candidate-result.candidate_job_accounting",
    )
    if accounting["source"] != "windows_job_object":
        raise ContractError("candidate Job accounting usa otra fuente kernel")
    integer_fields = (
        "total_user_time_100ns",
        "total_kernel_time_100ns",
        "total_page_fault_count",
        "total_processes",
        "active_processes",
        "total_terminated_processes",
        "peak_process_memory_commit_bytes",
        "peak_job_memory_commit_bytes",
    )
    for name in integer_fields:
        _require_non_negative_int(
            accounting[name], context=f"candidate-result.candidate_job_accounting.{name}"
        )
    for seconds_name, ticks_name in (
        ("total_user_seconds", "total_user_time_100ns"),
        ("total_kernel_seconds", "total_kernel_time_100ns"),
    ):
        seconds = accounting[seconds_name]
        if (
            isinstance(seconds, bool)
            or not isinstance(seconds, (int, float))
            or not math.isfinite(float(seconds))
            or float(seconds) != int(accounting[ticks_name]) / 10_000_000
        ):
            raise ContractError(
                f"candidate-result.candidate_job_accounting.{seconds_name} no deriva de 100ns"
            )
    if (
        accounting["total_processes"] != expected_total_processes
        or expected_total_processes < 1
        or accounting["active_processes"] != 0
    ):
        raise ContractError("candidate-result total_processes no deriva del Job hijo quiescente")
    _validate_job_memory_usage_information(
        accounting,
        context="candidate-result.candidate_job_accounting",
        require_supported=True,
    )
    io = _require_object(accounting["io"], context="candidate-result.candidate_job_accounting.io")
    _require_exact_keys(
        io,
        (
            "read_operations",
            "write_operations",
            "other_operations",
            "read_bytes",
            "write_bytes",
            "other_bytes",
        ),
        context="candidate-result.candidate_job_accounting.io",
    )
    for name, item in io.items():
        _require_non_negative_int(
            item, context=f"candidate-result.candidate_job_accounting.io.{name}"
        )
    return dict(accounting)


def _validate_candidate_execution_core(
    *,
    candidate_request_raw: Mapping[str, Any],
    candidate_request: Mapping[str, Any],
    harness_runtime_snapshot: Mapping[str, Any],
    candidate_request_payload_sha256: str,
    execution_request: Mapping[str, Any],
    execution_request_identity: Mapping[str, Any],
    candidate_start: Mapping[str, Any],
    candidate_result: Mapping[str, Any],
    native_pools_observation: Mapping[str, Any],
    adapter_result: Mapping[str, Any],
    expected_service_ready: Mapping[str, Any] | None,
    expected_http_exchange: Mapping[str, Any] | None,
    expected_attempt_id: str,
    expected_output_manifest_sha256: str,
    start_monotonic_ns: int,
    first_publisher_monotonic_ns: int,
) -> tuple[str, dict[str, int], int]:
    """Liga la cadena candidate común antes de especializar OPEN o HTTP."""
    from .adapters import (
        ADAPTER_RESULT_SCHEMA_VERSION,
        CANDIDATE_RESULT_SCHEMA_VERSION,
        CANDIDATE_START_SCHEMA_VERSION,
        candidate_execution_request,
    )

    request_sha = validate_sha256(
        candidate_request_payload_sha256, context="candidate_chain.request_sha256"
    )
    if canonical_json_sha256(candidate_request_raw) != request_sha:
        raise ContractError("candidate request payload SHA no deriva del descriptor runtime")
    expected_execution_request = candidate_execution_request(
        candidate_request,
        harness_runtime_snapshot=harness_runtime_snapshot,
    )
    if dict(execution_request) != expected_execution_request:
        raise ContractError("candidate execution request no es la serialización cerrada autorizada")

    identity = _require_object(execution_request_identity, context="candidate execution identity")
    expected_execution_bytes = canonical_json_bytes(expected_execution_request) + b"\n"
    if identity.get("logical_bytes") != len(expected_execution_bytes) or identity.get(
        "sha256"
    ) != sha256_bytes(expected_execution_bytes):
        raise ContractError("candidate execution identity no deriva de sus bytes exactos")

    _require_exact_keys(
        candidate_start,
        (
            "schema_version",
            "attempt_id",
            "candidate_request_sha256",
            "candidate_execution_request",
            "candidate_process",
        ),
        context="candidate-start",
    )
    _require_exact_keys(
        candidate_result,
        (
            "schema_version",
            "attempt_id",
            "candidate_request_sha256",
            "candidate_execution_request",
            "candidate_process",
            "service_ready",
            "native_pools_observation",
            "total_processes",
            "candidate_process_census",
            "candidate_job_accounting",
            "returncode",
            "tree_quiescent",
            "tree_empty_monotonic_ns",
        ),
        context="candidate-result",
    )
    process = _validate_candidate_process_identity(
        candidate_start["candidate_process"], context="candidate-start.candidate_process"
    )
    result_process = _validate_candidate_process_identity(
        candidate_result["candidate_process"], context="candidate-result.candidate_process"
    )
    total_processes = _require_non_negative_int(
        candidate_result["total_processes"],
        context="candidate-result.total_processes",
    )
    _validate_candidate_job_accounting(
        candidate_result["candidate_job_accounting"],
        expected_total_processes=total_processes,
    )
    _validate_candidate_process_census(
        candidate_result["candidate_process_census"],
        root_process=process,
        expected_total_processes=total_processes,
    )
    if (
        candidate_start["schema_version"] != CANDIDATE_START_SCHEMA_VERSION
        or candidate_result["schema_version"] != CANDIDATE_RESULT_SCHEMA_VERSION
        or candidate_start["attempt_id"] != expected_attempt_id
        or candidate_result["attempt_id"] != expected_attempt_id
        or candidate_start["candidate_request_sha256"] != request_sha
        or candidate_result["candidate_request_sha256"] != request_sha
        or candidate_start["candidate_execution_request"] != identity
        or candidate_result["candidate_execution_request"] != identity
        or result_process != process
        or candidate_result["native_pools_observation"] != native_pools_observation
        or total_processes < 1
        or candidate_result["tree_quiescent"] is not True
        or candidate_result["returncode"] != 0
    ):
        raise ContractError("candidate start/result no ligan request, proceso y éxito quiescente")
    tree_empty_ns = _require_non_negative_int(
        candidate_result["tree_empty_monotonic_ns"],
        context="candidate-result.tree_empty_monotonic_ns",
    )
    if tree_empty_ns < 1:
        raise ContractError("candidate-result tree_empty_monotonic_ns debe ser positivo")

    mode = candidate_request.get("mode")
    if mode == "batch":
        if (
            candidate_result["service_ready"] is not None
            or expected_service_ready is not None
            or expected_http_exchange is not None
        ):
            raise ContractError("candidate batch conserva evidencia HTTP")
    elif mode == "http-service":
        if (
            expected_service_ready is None
            or expected_http_exchange is None
            or candidate_result["service_ready"] != expected_service_ready
        ):
            raise ContractError("candidate UI no liga service-ready/HTTP exchange")
    else:
        raise ContractError("candidate result usa mode fuera del catálogo")

    _require_exact_keys(
        adapter_result,
        (
            "schema_version",
            "attempt_id",
            "candidate_execution",
            "http_exchange",
            "output_manifest_sha256",
        ),
        context="adapter-result",
    )
    output_manifest_sha = validate_sha256(
        adapter_result["output_manifest_sha256"],
        context="adapter-result.output_manifest_sha256",
    )
    if (
        adapter_result["schema_version"] != ADAPTER_RESULT_SCHEMA_VERSION
        or adapter_result["attempt_id"] != expected_attempt_id
        or adapter_result["candidate_execution"] != candidate_result
        or adapter_result["http_exchange"] != expected_http_exchange
        or output_manifest_sha != expected_output_manifest_sha256
    ):
        raise ContractError("adapter-result no liga candidate-result/HTTP/manifiesto final")

    deadline_ns = start_monotonic_ns + int(
        float(candidate_request["workload_deadline_seconds"]) * 1_000_000_000
    )
    if not (
        start_monotonic_ns <= tree_empty_ns <= first_publisher_monotonic_ns
        and tree_empty_ns <= deadline_ns
    ):
        raise ContractError("candidate quiescencia/publisher no respetan orden/deadline")
    return request_sha, process, tree_empty_ns


def _validate_candidate_execution_chain(
    *,
    candidate_request_raw: Mapping[str, Any],
    candidate_request: Mapping[str, Any],
    harness_runtime_snapshot: Mapping[str, Any],
    candidate_request_payload_sha256: str,
    execution_request: Mapping[str, Any],
    execution_request_identity: Mapping[str, Any],
    candidate_start: Mapping[str, Any],
    candidate_result: Mapping[str, Any],
    native_pools_observation: Mapping[str, Any],
    adapter_result: Mapping[str, Any],
    consumer_start: Mapping[str, Any],
    audit_events: Sequence[Mapping[str, Any]],
    expected_attempt_id: str,
    expected_output_manifest_sha256: str,
    start_monotonic_ns: int,
    first_publisher_monotonic_ns: int,
) -> dict[str, Any]:
    """Liga child, OPEN brokered, resultado y quiescencia antes del publisher."""
    from .adapters import CONSUMER_OPEN_REQUEST_SCHEMA_VERSION

    _request_sha, process, tree_empty_ns = _validate_candidate_execution_core(
        candidate_request_raw=candidate_request_raw,
        candidate_request=candidate_request,
        harness_runtime_snapshot=harness_runtime_snapshot,
        candidate_request_payload_sha256=candidate_request_payload_sha256,
        execution_request=execution_request,
        execution_request_identity=execution_request_identity,
        candidate_start=candidate_start,
        candidate_result=candidate_result,
        native_pools_observation=native_pools_observation,
        adapter_result=adapter_result,
        expected_service_ready=None,
        expected_http_exchange=None,
        expected_attempt_id=expected_attempt_id,
        expected_output_manifest_sha256=expected_output_manifest_sha256,
        start_monotonic_ns=start_monotonic_ns,
        first_publisher_monotonic_ns=first_publisher_monotonic_ns,
    )

    broker = _require_object(candidate_request.get("broker"), context="candidate.broker")
    input_contract = _require_object(
        candidate_request.get("input_contract"), context="candidate.input_contract"
    )
    protected = input_contract.get("protected")
    if not isinstance(protected, list) or not protected:
        raise ContractError("candidate input_contract carece de protected")
    expected_wire = {
        "schema_version": CONSUMER_OPEN_REQUEST_SCHEMA_VERSION,
        "attempt_id": expected_attempt_id,
        "operation": "OPEN",
        "request_id": broker.get("request_id"),
        "nonce": broker.get("nonce"),
        "protected": protected,
    }
    expected_open = {
        "request_id": broker.get("request_id"),
        "protected": protected,
        "broker_request_sha256": canonical_json_sha256(expected_wire),
        "nonce_commitment_sha256": broker.get("nonce_commitment_sha256"),
        "candidate_process": process,
    }
    for name, expected in expected_open.items():
        if consumer_start.get(name) != expected:
            raise ContractError(f"consumer OPEN no liga candidate request/proceso: {name}")
    open_ns = _require_non_negative_int(
        consumer_start.get("monotonic_ns"), context="candidate consumer OPEN.monotonic_ns"
    )

    if len(audit_events) != 2:
        raise ContractError("adapter broker audit no acredita ready + OPEN exactos")
    broker_ready = _require_object(audit_events[0], context="adapter audit broker_ready")
    broker_open = _require_object(audit_events[1], context="adapter audit consumer_open")
    if (
        broker_ready.get("event") != "broker_ready"
        or broker_ready.get("protected_count") != len(protected)
        or broker_open.get("event") != "consumer_open_brokered"
        or any(broker_open.get(name) != expected for name, expected in expected_open.items())
    ):
        raise ContractError("adapter broker audit no reconcilia con OPEN/candidate")
    broker_ready_ns = _require_non_negative_int(
        broker_ready.get("monotonic_ns"), context="adapter audit ready.monotonic_ns"
    )
    audit_open_ns = _require_non_negative_int(
        broker_open.get("monotonic_ns"), context="adapter audit OPEN.monotonic_ns"
    )
    if not (
        start_monotonic_ns
        <= broker_ready_ns
        <= open_ns
        <= audit_open_ns
        <= tree_empty_ns
        <= first_publisher_monotonic_ns
    ):
        raise ContractError("candidate OPEN/quiescencia/publisher no respetan orden/deadline")
    return dict(candidate_result)


def _validate_candidate_http_execution_chain(
    *,
    candidate_request_raw: Mapping[str, Any],
    candidate_request: Mapping[str, Any],
    harness_runtime_snapshot: Mapping[str, Any],
    candidate_request_payload_sha256: str,
    execution_request: Mapping[str, Any],
    execution_request_identity: Mapping[str, Any],
    candidate_start: Mapping[str, Any],
    candidate_result: Mapping[str, Any],
    native_pools_observation: Mapping[str, Any],
    adapter_result: Mapping[str, Any],
    service_ready_identity: Mapping[str, Any],
    service_ready: Mapping[str, Any],
    http_exchange_identity: Mapping[str, Any],
    http_exchange: Mapping[str, Any],
    consumer_start: Mapping[str, Any],
    ui_response_event: Mapping[str, Any],
    audit_events: Sequence[Mapping[str, Any]],
    expected_ingress: Mapping[str, Any],
    expected_service: Mapping[str, Any],
    output_manifest: Mapping[str, Any],
    expected_attempt_id: str,
    expected_output_manifest_sha256: str,
    start_monotonic_ns: int,
    first_publisher_monotonic_ns: int,
) -> dict[str, Any]:
    """Liga servicio, proxy no-transforming, página real y quiescencia F-UI."""
    from .adapters import (
        CANDIDATE_SERVICE_READY_SCHEMA_VERSION,
        HTTP_EXCHANGE_SCHEMA_VERSION,
        UI_FIRST_BYTE_SCHEMA_VERSION,
    )

    _request_sha, process, tree_empty_ns = _validate_candidate_execution_core(
        candidate_request_raw=candidate_request_raw,
        candidate_request=candidate_request,
        harness_runtime_snapshot=harness_runtime_snapshot,
        candidate_request_payload_sha256=candidate_request_payload_sha256,
        execution_request=execution_request,
        execution_request_identity=execution_request_identity,
        candidate_start=candidate_start,
        candidate_result=candidate_result,
        native_pools_observation=native_pools_observation,
        adapter_result=adapter_result,
        expected_service_ready=service_ready_identity,
        expected_http_exchange=http_exchange_identity,
        expected_attempt_id=expected_attempt_id,
        expected_output_manifest_sha256=expected_output_manifest_sha256,
        start_monotonic_ns=start_monotonic_ns,
        first_publisher_monotonic_ns=first_publisher_monotonic_ns,
    )
    service = _require_object(candidate_request.get("service"), context="candidate.service")
    if candidate_request.get("broker") is not None or any(
        service.get(name) != expected_service.get(name)
        for name in ("host", "port", "ready_timeout_seconds")
    ):
        raise ContractError("candidate UI no liga el servicio firmado")

    _require_exact_keys(
        service_ready,
        (
            "schema_version",
            "attempt_id",
            "candidate_request_sha256",
            "candidate_process",
            "host",
            "port",
            "ready_monotonic_ns",
        ),
        context="candidate service-ready",
    )
    ready_ns = _require_non_negative_int(
        service_ready["ready_monotonic_ns"], context="candidate service-ready.monotonic_ns"
    )
    if (
        service_ready["schema_version"] != CANDIDATE_SERVICE_READY_SCHEMA_VERSION
        or service_ready["attempt_id"] != expected_attempt_id
        or service_ready["candidate_request_sha256"] != candidate_request_payload_sha256
        or service_ready["candidate_process"] != process
        or service_ready["host"] != service["host"]
        or service_ready["port"] != service["port"]
        or ready_ns < 1
    ):
        raise ContractError("candidate service-ready no liga request/proceso/endpoint")

    _require_exact_keys(
        http_exchange,
        (
            "schema_version",
            "attempt_id",
            "candidate_request_sha256",
            "request_id",
            "service_descriptor_sha256",
            "endpoint_sha256",
            "candidate_process",
            "service_ready",
            "request",
            "response",
            "first_verifiable_page",
            "non_transforming",
        ),
        context="candidate HTTP exchange",
    )
    request = _require_object(http_exchange["request"], context="candidate HTTP request")
    _require_exact_keys(
        request,
        (
            "method",
            "path",
            "body_bytes",
            "body_sha256",
            "first_byte_to_service_monotonic_ns",
        ),
        context="candidate HTTP request",
    )
    response = _require_object(http_exchange["response"], context="candidate HTTP response")
    _require_exact_keys(
        response,
        (
            "status",
            "content_type",
            "body_bytes",
            "body_sha256",
            "first_byte_from_service_monotonic_ns",
        ),
        context="candidate HTTP response",
    )
    body = _require_object(expected_ingress.get("body"), context="adapter.ui_ingress.body")
    oracle = _require_object(
        expected_service.get("first_page_oracle"), context="candidate service oracle"
    )
    ingress_ns = _require_non_negative_int(
        request["first_byte_to_service_monotonic_ns"],
        context="candidate HTTP request.first_byte_to_service_monotonic_ns",
    )
    response_ns = _require_non_negative_int(
        response["first_byte_from_service_monotonic_ns"],
        context="candidate HTTP response.first_byte_from_service_monotonic_ns",
    )
    expected_request = {
        "method": "POST",
        "path": expected_ingress["path"],
        "body_bytes": body["logical_bytes"],
        "body_sha256": body["sha256"],
        "first_byte_to_service_monotonic_ns": ingress_ns,
    }
    expected_response = {
        "status": oracle["expected_status"],
        "content_type": oracle["content_type"],
        "body_bytes": oracle["response_body_bytes"],
        "body_sha256": oracle["response_body_sha256"],
        "first_byte_from_service_monotonic_ns": response_ns,
    }
    if (
        http_exchange["schema_version"] != HTTP_EXCHANGE_SCHEMA_VERSION
        or http_exchange["attempt_id"] != expected_attempt_id
        or http_exchange["candidate_request_sha256"] != candidate_request_payload_sha256
        or http_exchange["request_id"] != expected_ingress["request_id"]
        or http_exchange["service_descriptor_sha256"]
        != expected_ingress["service_descriptor_sha256"]
        or http_exchange["endpoint_sha256"] != expected_ingress["endpoint_sha256"]
        or http_exchange["candidate_process"] != process
        or http_exchange["service_ready"] != service_ready_identity
        or request != expected_request
        or response != expected_response
        or http_exchange["first_verifiable_page"] != oracle["first_verifiable_page"]
        or http_exchange["non_transforming"] is not True
    ):
        raise ContractError("candidate HTTP exchange no liga request/respuesta/oráculo exactos")

    expected_boundary = {
        "event": "first_open_or_byte",
        "monotonic_ns": ingress_ns,
        "kind": "first_byte",
        "provider": "harness_owned_candidate_http_ingress_v1",
        "request_id": expected_ingress["request_id"],
        "request_body_bytes": body["logical_bytes"],
        "request_body_sha256": body["sha256"],
        "service_descriptor_sha256": expected_ingress["service_descriptor_sha256"],
        "endpoint_sha256": expected_ingress["endpoint_sha256"],
        "non_transforming": True,
    }
    if dict(consumer_start) != expected_boundary:
        raise ContractError("boundary UI no deriva del primer byte entregado al servicio")

    _require_exact_keys(
        ui_response_event,
        ("schema_version", "attempt_id", "event", "monotonic_ns", "request_id"),
        context="ui response first-byte",
    )
    client_response_ns = _require_non_negative_int(
        ui_response_event["monotonic_ns"], context="ui response first-byte.monotonic_ns"
    )
    if (
        ui_response_event["schema_version"] != UI_FIRST_BYTE_SCHEMA_VERSION
        or ui_response_event["attempt_id"] != expected_attempt_id
        or ui_response_event["event"] != "first_byte"
        or ui_response_event["request_id"] != expected_ingress["request_id"]
        or client_response_ns < response_ns
    ):
        raise ContractError("ui response first-byte no es causal al servicio candidato")

    if len(audit_events) != 1:
        raise ContractError("adapter UI audit no acredita readiness exacto")
    audit_ready = _require_object(audit_events[0], context="adapter UI audit ready")
    audit_ready_ns = _require_non_negative_int(
        audit_ready.get("monotonic_ns"), context="adapter UI audit ready.monotonic_ns"
    )
    if audit_ready.get("event") != "broker_ready" or audit_ready.get("protected_count") != 1:
        raise ContractError("adapter UI audit no liga body protegido único")
    if not (
        start_monotonic_ns
        <= audit_ready_ns
        <= ready_ns
        <= ingress_ns
        <= response_ns
        <= tree_empty_ns
        <= first_publisher_monotonic_ns
    ):
        raise ContractError("candidate HTTP/quiescencia/publisher no respetan orden causal")

    page = _require_object(
        http_exchange["first_verifiable_page"], context="candidate HTTP first page"
    )
    artifacts = output_manifest.get("artifacts")
    if not isinstance(artifacts, list):
        raise ContractError("output manifest carece de artifacts para first page")
    matches = [
        _require_object(item, context="output manifest artifact")
        for item in artifacts
        if isinstance(item, Mapping) and item.get("identity") == page.get("identity")
    ]
    if len(matches) != 1 or {
        "relative_path": matches[0].get("relative_path"),
        "logical_bytes": matches[0].get("logical_bytes"),
        "sha256": matches[0].get("sha256"),
    } != {
        "relative_path": page.get("relative_path"),
        "logical_bytes": page.get("logical_bytes"),
        "sha256": page.get("sha256"),
    }:
        raise ContractError("first-page oracle no liga el output final publicado")
    return dict(candidate_result)


def _validate_preflight_guards(
    value: Any,
    *,
    environment: Mapping[str, Any],
    fixture_inputs: Sequence[Mapping[str, Any]],
    fixture_bundle: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Recalcula headroom y piso de disco; ``passed`` nunca es autodeclarado."""
    guards = _require_object(value, context="limits.guards")
    _require_exact_keys(
        guards,
        (
            "physical_available_bytes",
            "commit_available_bytes",
            "allocated_inputs_bundle_bytes",
            "disk_free_bytes",
            "disk_floor_bytes",
            "passed",
        ),
        context="limits.guards",
    )
    normalized = {
        name: _require_non_negative_int(guards[name], context=f"limits.guards.{name}")
        for name in (
            "physical_available_bytes",
            "commit_available_bytes",
            "allocated_inputs_bundle_bytes",
            "disk_free_bytes",
            "disk_floor_bytes",
        )
    }
    environment_memory = _require_object(
        environment.get("system_memory"), context="environment.system_memory"
    )
    environment_volume = _require_object(environment.get("volume"), context="environment.volume")
    allocated_inputs_bundle = sum(
        _require_non_negative_int(item.get("allocated_bytes"), context="fixture.inputs.allocated")
        for item in fixture_inputs
    )
    if fixture_bundle is not None:
        allocated_inputs_bundle += _require_non_negative_int(
            fixture_bundle.get("allocated_bytes"), context="fixture.bundle.allocated"
        )
    expected_disk_floor = max(PREFLIGHT_MIN_DISK_FREE_BYTES, 3 * allocated_inputs_bundle)
    expected = {
        "physical_available_bytes": environment_memory["physical_available_bytes"],
        "commit_available_bytes": environment_memory["commit_available_bytes"],
        "allocated_inputs_bundle_bytes": allocated_inputs_bundle,
        "disk_free_bytes": environment_volume["free_bytes"],
        "disk_floor_bytes": expected_disk_floor,
    }
    expected_passed = bool(
        expected["physical_available_bytes"] >= PREFLIGHT_MIN_AVAILABLE_PHYSICAL_BYTES
        and expected["commit_available_bytes"] >= PREFLIGHT_MIN_COMMIT_HEADROOM_BYTES
        and expected["disk_free_bytes"] >= expected_disk_floor
    )
    if (
        normalized != expected
        or _require_bool(guards["passed"], context="limits.guards.passed") is not expected_passed
        or not expected_passed
    ):
        raise ContractError("limits.guards no deriva de fixture/entorno/pisos de preflight")
    return dict(guards)


def validate_attempt_evidence(
    value: Mapping[str, Any],
    *,
    verify_artifacts: bool = False,
    trusted_authority_public_key_path: Path | None = None,
    _verify_evidence_self_binding: bool = True,
) -> dict[str, Any]:
    """Valida evidencia cerrada, phase-aware y opcionalmente relee sus artefactos."""
    if verify_artifacts and trusted_authority_public_key_path is None:
        raise ContractError("verify_artifacts exige una clave pública de autoridad externa")
    expected_top = ("schema_version", *ATTEMPT_TOP_LEVEL_OBJECTS)
    _require_exact_keys(value, expected_top, context="evidencia de intento")
    if value["schema_version"] != ATTEMPT_SCHEMA_VERSION:
        raise ContractError("schema_version de intento inesperado")
    objects = {
        name: _require_object(value[name], context=name) for name in ATTEMPT_TOP_LEVEL_OBJECTS
    }
    identity = objects["identity"]
    _require_exact_keys(
        identity,
        (
            "attempt_id",
            "unit",
            "evidence_path",
            "wall_time_finished_utc",
            "preflight_started_monotonic_ns",
            "ready_monotonic_ns",
            "start_monotonic_ns",
            "tree_empty_monotonic_ns",
        ),
        context="identity",
    )
    unit = validate_attempt_unit(_require_object(identity.get("unit"), context="identity.unit"))
    if identity.get("attempt_id") != attempt_id(unit):
        raise ContractError("identity.attempt_id no reconcilia")
    _require_text(identity["evidence_path"], context="identity.evidence_path")
    _require_text(identity["wall_time_finished_utc"], context="identity.wall_time_finished_utc")
    preflight_ns = _require_non_negative_int(
        identity["preflight_started_monotonic_ns"],
        context="identity.preflight_started_monotonic_ns",
    )
    for name in ("ready_monotonic_ns", "start_monotonic_ns", "tree_empty_monotonic_ns"):
        timestamp = identity[name]
        if timestamp is not None:
            _require_non_negative_int(timestamp, context=f"identity.{name}")
    observed_times = [
        timestamp
        for timestamp in (
            preflight_ns,
            identity["ready_monotonic_ns"],
            identity["start_monotonic_ns"],
            identity["tree_empty_monotonic_ns"],
        )
        if timestamp is not None
    ]
    if observed_times != sorted(observed_times):
        raise ContractError("identity: timestamps monotónicos fuera de orden")
    result = objects["result"]
    _require_exact_keys(
        result,
        ("classification", "statistically_eligible", "reasons"),
        context="result",
    )
    classification = result.get("classification")
    if classification not in CLASSIFICATIONS:
        raise ContractError(f"clasificación fuera del catálogo: {classification!r}")
    if result["statistically_eligible"] is not (classification == "success"):
        raise ContractError("elegibilidad estadística no deriva de la clasificación")
    if not isinstance(result["reasons"], list) or not all(
        isinstance(reason, str) for reason in result["reasons"]
    ):
        raise ContractError("result.reasons debe ser lista de texto")
    authority = objects["authority"]
    _require_exact_keys(
        authority,
        (
            "schema_version",
            "scope",
            "start_authorized",
            "authorization_id",
            "authorization_consumption_path_sha256",
            "authorized_unit",
            "attempt_id",
            "authorization_text_sha256",
            "document_sha256",
            "tooling_sha256",
            "schedule_sha256",
            "schedule_position",
            "signer_public_key_sha256",
            "signature_ed25519",
        ),
        context="authority",
    )
    if authority["scope"] != "calibration-start" or authority["start_authorized"] is not True:
        raise ContractError("evidencia de intento no tiene autoridad START exacta")
    if authority["attempt_id"] != identity["attempt_id"]:
        raise ContractError("authority.attempt_id no reconcilia")
    validate_sha256(authority["authorization_id"], context="authority.authorization_id")
    validate_sha256(
        authority["authorization_consumption_path_sha256"],
        context="authority.authorization_consumption_path_sha256",
    )
    if (
        validate_attempt_unit(
            _require_object(authority["authorized_unit"], context="authority.authorized_unit")
        )
        != unit
    ):
        raise ContractError("authority.authorized_unit no reconcilia")
    validate_sha256(authority["schedule_sha256"], context="authority.schedule_sha256")
    if authority["schema_version"] != AUTHORIZATION_SCHEMA_VERSION:
        raise ContractError("authority.schema_version inesperado")
    validate_sha256(
        authority["signer_public_key_sha256"], context="authority.signer_public_key_sha256"
    )
    signature = authority["signature_ed25519"]
    if (
        not isinstance(signature, str)
        or len(signature) != 128
        or any(character not in "0123456789abcdef" for character in signature)
        or signature in {"0" * 128, "f" * 128}
    ):
        raise ContractError("authority.signature_ed25519 inválida")
    if trusted_authority_public_key_path is not None:
        verify_authority_signature(
            authority,
            trusted_authority_public_key_path=trusted_authority_public_key_path,
        )
    elif verify_artifacts:
        raise ContractError("verify_artifacts exige trust anchor Ed25519 externo")
    validate_authorization_consumption(
        objects["authorization_consumption"],
        authority=authority,
        expected_attempt_id=str(identity["attempt_id"]),
        verify_receipt=verify_artifacts,
    )
    for name in ("authorization_text_sha256", "tooling_sha256"):
        validate_sha256(authority[name], context=f"authority.{name}")
    document_hashes = _require_object(
        authority["document_sha256"], context="authority.document_sha256"
    )
    if not document_hashes:
        raise ContractError("authority.document_sha256 no puede estar vacío")
    for name, digest in document_hashes.items():
        _require_text(name, context="authority.document_sha256.nombre")
        validate_sha256(digest, context=f"authority.document_sha256.{name}")
    schedule_position = authority["schedule_position"]
    if (
        isinstance(schedule_position, bool)
        or not isinstance(schedule_position, int)
        or schedule_position < 0
    ):
        raise ContractError("authority.schedule_position inválida")
    candidate = objects["candidate"]
    _require_exact_keys(
        candidate,
        ("manifest_sha256", "manifest_root", "source_sha", "wheel", "sdist", "lock", "runtime"),
        context="candidate",
    )
    if (
        validate_sha256(candidate["manifest_sha256"], context="candidate.manifest_sha256")
        != unit["candidate_manifest_sha256"]
    ):
        raise ContractError("candidate.manifest_sha256 no reconcilia con la unidad")
    _require_text(candidate["manifest_root"], context="candidate.manifest_root")
    _validate_git_sha(candidate["source_sha"], context="candidate.source_sha")
    for name in ("wheel", "sdist", "lock"):
        _validate_file_identity(candidate[name], context=f"candidate.{name}")
    runtime = _require_object(candidate["runtime"], context="candidate.runtime")
    _require_exact_keys(
        runtime,
        ("python_executable", "environment", "installed_tree", "provenance"),
        context="candidate.runtime",
    )
    _validate_file_identity(
        runtime["python_executable"], context="candidate.runtime.python_executable"
    )
    _validate_file_identity(runtime["environment"], context="candidate.runtime.environment")
    installed_tree = _require_object(
        runtime["installed_tree"], context="candidate.runtime.installed_tree"
    )
    _require_exact_keys(
        installed_tree,
        ("relative_path", "files", "logical_bytes", "sha256", "path"),
        context="candidate.runtime.installed_tree",
    )
    _require_text(
        installed_tree["relative_path"], context="candidate.runtime.installed_tree.relative_path"
    )
    _require_text(installed_tree["path"], context="candidate.runtime.installed_tree.path")
    _require_non_negative_int(
        installed_tree["files"], context="candidate.runtime.installed_tree.files"
    )
    _require_non_negative_int(
        installed_tree["logical_bytes"], context="candidate.runtime.installed_tree.logical_bytes"
    )
    validate_sha256(installed_tree["sha256"], context="candidate.runtime.installed_tree.sha256")
    provenance = _validate_runtime_provenance(
        runtime["provenance"], context="candidate.runtime.provenance"
    )
    if (
        provenance["installed_tree_sha256"] != installed_tree["sha256"]
        or provenance["wheel_sha256"] != candidate["wheel"]["sha256"]
        or provenance["lock_sha256"] != candidate["lock"]["sha256"]
    ):
        raise ContractError("candidate.runtime.provenance no liga wheel/lock/árbol")
    tooling = objects["tooling"]
    _require_exact_keys(
        tooling,
        (
            "protocol_version",
            "files",
            "harness_runtime",
            "manifest_sha256",
            "document_sha256",
            "document_paths",
            "launch_sources",
            "runtime_descriptors",
        ),
        context="tooling",
    )
    if tooling["protocol_version"] != PROTOCOL_VERSION:
        raise ContractError("tooling.protocol_version inesperado")
    tooling_sha = validate_sha256(tooling["manifest_sha256"], context="tooling.manifest_sha256")
    if tooling_sha != authority["tooling_sha256"]:
        raise ContractError("tooling.manifest_sha256 no reconcilia con autoridad")
    if tooling["document_sha256"] != document_hashes:
        raise ContractError("tooling.document_sha256 no reconcilia con autoridad")
    tooling_paths = _require_object(tooling["document_paths"], context="tooling.document_paths")
    if set(tooling_paths) != set(document_hashes) or any(
        not isinstance(path, str) or not path for path in tooling_paths.values()
    ):
        raise ContractError("tooling.document_paths no reconcilia el censo documental")
    tooling_files = tooling["files"]
    if not isinstance(tooling_files, list) or not tooling_files:
        raise ContractError("tooling.files debe ser una lista no vacía")
    normalized_tooling_files: list[dict[str, Any]] = []
    for index, raw in enumerate(tooling_files):
        entry = _require_object(raw, context=f"tooling.files[{index}]")
        _require_exact_keys(
            entry, ("relative_path", "bytes", "sha256"), context=f"tooling.files[{index}]"
        )
        relative_path = _require_text(
            entry["relative_path"], context=f"tooling.files[{index}].relative_path"
        )
        byte_count = _require_non_negative_int(
            entry["bytes"], context=f"tooling.files[{index}].bytes"
        )
        digest = validate_sha256(entry["sha256"], context=f"tooling.files[{index}].sha256")
        normalized_tooling_files.append(
            {"relative_path": relative_path, "bytes": byte_count, "sha256": digest}
        )
    relative_paths = [entry["relative_path"] for entry in normalized_tooling_files]
    if relative_paths != sorted(set(relative_paths)):
        raise ContractError("tooling.files está duplicado o fuera de orden")
    harness_runtime = _validate_harness_runtime(
        tooling["harness_runtime"],
        context="tooling.harness_runtime",
        verify_artifacts=False,
    )
    candidate_python = _require_object(
        runtime["python_executable"], context="candidate.runtime.python_executable"
    )
    harness_python = _require_object(
        harness_runtime["python_executable"], context="tooling.harness_runtime.python_executable"
    )
    if os.path.normcase(os.path.abspath(str(candidate_python["path"]))) == os.path.normcase(
        os.path.abspath(str(harness_python["path"]))
    ):
        raise ContractError("runtime del arnés no está separado del runtime candidato")
    candidate_tree_path = os.path.normcase(os.path.abspath(str(installed_tree["path"])))
    for root in cast(list[dict[str, Any]], harness_runtime["import_roots"]):
        root_path = os.path.normcase(os.path.abspath(str(root["path"])))
        try:
            common = os.path.commonpath((candidate_tree_path, root_path))
        except ValueError:
            continue
        if common in {candidate_tree_path, root_path}:
            raise ContractError("dependencia del arnés se solapa con el árbol candidato")
    tooling_manifest = {
        "protocol_version": PROTOCOL_VERSION,
        "files": normalized_tooling_files,
        "harness_runtime": harness_runtime,
    }
    if canonical_json_sha256(tooling_manifest) != tooling_sha:
        raise ContractError("tooling.manifest_sha256 no deriva del censo de archivos")
    launch_sources = _require_object(tooling["launch_sources"], context="tooling.launch_sources")
    _require_exact_keys(
        launch_sources,
        (
            "authority",
            "authorization_text",
            "candidate_manifest",
            "fixture_manifest",
            "config",
            "schedule",
            "trusted_authority_public_key",
        ),
        context="tooling.launch_sources",
    )
    for name, raw_source in launch_sources.items():
        source = _require_object(raw_source, context=f"tooling.launch_sources.{name}")
        _require_exact_keys(
            source,
            ("path", "identity_kind", "sha256"),
            context=f"tooling.launch_sources.{name}",
        )
        _require_text(source["path"], context=f"tooling.launch_sources.{name}.path")
        if name == "authorization_text":
            expected_kind = "raw_file_sha256"
        elif name == "trusted_authority_public_key":
            expected_kind = "ed25519_public_key_sha256"
        else:
            expected_kind = "canonical_json_sha256"
        if source["identity_kind"] != expected_kind:
            raise ContractError(f"tooling.launch_sources.{name}: identity_kind inesperado")
        validate_sha256(source["sha256"], context=f"tooling.launch_sources.{name}.sha256")
    expected_launch_hashes = {
        "authority": canonical_json_sha256(authority),
        "authorization_text": authority["authorization_text_sha256"],
        "candidate_manifest": unit["candidate_manifest_sha256"],
        "fixture_manifest": unit["fixture_manifest_sha256"],
        "config": unit["config_hash"],
        "schedule": authority["schedule_sha256"],
        "trusted_authority_public_key": authority["signer_public_key_sha256"],
    }
    for name, expected_digest in expected_launch_hashes.items():
        if cast(dict[str, Any], launch_sources[name])["sha256"] != expected_digest:
            raise ContractError(f"tooling.launch_sources.{name} no reconcilia con la unidad")
    runtime_descriptors = _require_object(
        tooling["runtime_descriptors"], context="tooling.runtime_descriptors"
    )
    _require_exact_keys(
        runtime_descriptors,
        (
            "adapter_descriptor",
            "adapter_request",
            "candidate_request",
            "harness_runtime_snapshot",
            "ui_client_request",
        ),
        context="tooling.runtime_descriptors",
    )
    for name in (
        "adapter_descriptor",
        "adapter_request",
        "candidate_request",
        "harness_runtime_snapshot",
    ):
        descriptor_identity = _require_object(
            runtime_descriptors[name], context=f"tooling.runtime_descriptors.{name}"
        )
        _require_exact_keys(
            descriptor_identity,
            ("path", "bytes", "sha256"),
            context=f"tooling.runtime_descriptors.{name}",
        )
        _require_text(
            descriptor_identity["path"], context=f"tooling.runtime_descriptors.{name}.path"
        )
        _require_non_negative_int(
            descriptor_identity["bytes"], context=f"tooling.runtime_descriptors.{name}.bytes"
        )
        validate_sha256(
            descriptor_identity["sha256"], context=f"tooling.runtime_descriptors.{name}.sha256"
        )
    ui_descriptor_raw = runtime_descriptors["ui_client_request"]
    if ui_descriptor_raw is not None:
        ui_descriptor = _require_object(
            ui_descriptor_raw, context="tooling.runtime_descriptors.ui_client_request"
        )
        _require_exact_keys(
            ui_descriptor,
            ("path", "bytes", "sha256"),
            context="tooling.runtime_descriptors.ui_client_request",
        )
        _require_text(
            ui_descriptor["path"], context="tooling.runtime_descriptors.ui_client_request.path"
        )
        _require_non_negative_int(
            ui_descriptor["bytes"], context="tooling.runtime_descriptors.ui_client_request.bytes"
        )
        validate_sha256(
            ui_descriptor["sha256"],
            context="tooling.runtime_descriptors.ui_client_request.sha256",
        )
    fixture = objects["fixture"]
    _require_exact_keys(
        fixture,
        (
            "manifest_sha256",
            "manifest_root",
            "flow_id",
            "flow_step",
            "geometry_id",
            "fixture_schema",
            "config",
            "config_hash",
            "root_seed",
            "sub_seed",
            "sub_seed_sha256",
            "generator",
            "dimensions",
            "geometry_observed",
            "inputs_root",
            "inputs",
            "bundle_root",
            "bundle",
            "catalog",
            "expected",
            "contains_customer_data",
            "demo_fixture",
        ),
        context="fixture",
    )
    if fixture.get("manifest_sha256") != unit["fixture_manifest_sha256"]:
        raise ContractError("fixture.manifest_sha256 no reconcilia con la unidad")
    if fixture.get("config_hash") != unit["config_hash"]:
        raise ContractError("fixture.config_hash no reconcilia con la unidad")
    for name in ("flow_id", "flow_step", "geometry_id"):
        if fixture.get(name) != unit[name]:
            raise ContractError(f"fixture.{name} no reconcilia con la unidad")
    spec = flow_spec(str(unit["flow_id"]), str(unit["flow_step"]))
    _require_text(fixture["manifest_root"], context="fixture.manifest_root")
    if fixture["dimensions"] != dict(spec.geometries[str(unit["geometry_id"])]):
        raise ContractError("fixture.dimensions no reconcilia con geometry/flow")
    if fixture["root_seed"] != 20_240_706:
        raise ContractError("fixture.root_seed no coincide con el protocolo")
    expected_sub_seed_sha256 = sha256_bytes(
        f"h9r-cal-v1\0{unit['flow_id']}\0{unit['geometry_id']}".encode()
    )
    if fixture["sub_seed_sha256"] != expected_sub_seed_sha256 or fixture["sub_seed"] != int(
        expected_sub_seed_sha256[:16], 16
    ):
        raise ContractError("fixture.sub_seed no deriva de flow/geometry")
    for name in ("fixture_schema", "config", "catalog"):
        _validate_fixture_file_identity(fixture[name], context=f"fixture.{name}")
    fixture_inputs = fixture["inputs"]
    if not isinstance(fixture_inputs, list) or not fixture_inputs:
        raise ContractError("fixture.inputs debe ser lista no vacia")
    for index, fixture_input in enumerate(fixture_inputs):
        _validate_fixture_file_identity(fixture_input, context=f"fixture.inputs[{index}]")
    if fixture["bundle"] is not None:
        _validate_fixture_file_identity(fixture["bundle"], context="fixture.bundle")
    _require_text(fixture["inputs_root"], context="fixture.inputs_root")
    _require_text(fixture["bundle_root"], context="fixture.bundle_root")
    generator = _require_object(fixture["generator"], context="fixture.generator")
    _require_exact_keys(generator, ("artifact", "source_commit"), context="fixture.generator")
    _validate_fixture_file_identity(generator["artifact"], context="fixture.generator.artifact")
    _validate_git_sha(generator["source_commit"], context="fixture.generator.source_commit")
    if fixture["contains_customer_data"] is not False or fixture["demo_fixture"] is not False:
        raise ContractError("fixture no acredita exclusión de cliente/demo")
    fixture_expected = _require_object(fixture["expected"], context="fixture.expected")
    _require_exact_keys(
        fixture_expected, ("identities", "counts", "golden"), context="fixture.expected"
    )
    if fixture_expected["identities"] != list(spec.expected_output_identities):
        raise ContractError("fixture.expected.identities no reconcilia con el catálogo")
    expected_counts = _require_object(fixture_expected["counts"], context="fixture.expected.counts")
    if set(expected_counts) != set(spec.expected_output_identities):
        raise ContractError("fixture.expected.counts no censa todas las identidades")
    for name, count in expected_counts.items():
        _require_non_negative_int(count, context=f"fixture.expected.counts.{name}")
    fixture_golden = _require_object(fixture_expected["golden"], context="fixture.expected.golden")
    _validate_fixture_file_identity(fixture_golden, context="fixture.expected.golden")
    _validate_fixture_geometry_observed(
        fixture["geometry_observed"],
        dimensions=_require_object(fixture["dimensions"], context="fixture.dimensions"),
        inputs=[_require_object(item, context="fixture.inputs[]") for item in fixture_inputs],
        fixture_schema=_require_object(fixture["fixture_schema"], context="fixture.fixture_schema"),
        catalog=_require_object(fixture["catalog"], context="fixture.catalog"),
    )
    environment = _validate_execution_environment(objects["environment"])
    limits = objects["limits"]
    _require_exact_keys(
        limits,
        (
            "requested",
            "effective",
            "logical_cpu_count_effective",
            "job_memory_commit_limit_bytes_effective",
            "ready_before_start",
            "guards",
        ),
        context="limits",
    )
    requested = _require_object(limits["requested"], context="limits.requested")
    _require_exact_keys(
        requested,
        (
            "logical_cpu_count",
            "affinity_mask",
            "job_memory_commit_limit_bytes",
            "preflight_deadline_seconds",
            "handshake_deadline_seconds",
            "workload_deadline_seconds",
        ),
        context="limits.requested",
    )
    for name in ("logical_cpu_count", "affinity_mask", "job_memory_commit_limit_bytes"):
        _require_non_negative_int(requested[name], context=f"limits.requested.{name}")
    for name in (
        "preflight_deadline_seconds",
        "handshake_deadline_seconds",
        "workload_deadline_seconds",
    ):
        deadline = requested[name]
        if isinstance(deadline, bool) or not isinstance(deadline, int | float) or deadline <= 0:
            raise ContractError(f"limits.requested.{name}: deadline invávida")
    if requested["logical_cpu_count"] not in {1, 2, 3, 4}:
        raise ContractError("limits.requested.logical_cpu_count fuera de 1…4")
    if (
        requested["affinity_mask"] <= 0
        or requested["affinity_mask"].bit_count() != requested["logical_cpu_count"]
    ):
        raise ContractError("limits.requested.affinity_mask no reconcilia CPU lógicas")
    if requested["job_memory_commit_limit_bytes"] != CAPS[unit["cap_id"]]:
        raise ContractError("limits.requested cap no coincide con la unidad")
    if requested["preflight_deadline_seconds"] != PREFLIGHT_DEADLINE_SECONDS:
        raise ContractError("deadline de preflight no coincide con el protocolo")
    if requested["handshake_deadline_seconds"] != HANDSHAKE_DEADLINE_SECONDS:
        raise ContractError("deadline de handshake no coincide con el protocolo")
    spec = flow_spec(str(unit["flow_id"]), str(unit["flow_step"]))
    if requested["workload_deadline_seconds"] != spec.workload_deadline_seconds:
        raise ContractError("deadline del workload no coincide con el catálogo")
    if classification == "success":
        start_ns = identity["start_monotonic_ns"]
        tree_empty_ns = identity["tree_empty_monotonic_ns"]
        if not isinstance(start_ns, int) or not isinstance(tree_empty_ns, int):
            raise ContractError("success carece de START/tree_empty para medir deadline")
        elapsed_ns = tree_empty_ns - start_ns
        deadline_ns = int(float(requested["workload_deadline_seconds"]) * 1_000_000_000)
        if elapsed_ns < 0 or elapsed_ns > deadline_ns:
            raise ContractError("success excede el deadline START→árbol vacío")
    effective_raw = limits["effective"]
    effective = (
        _validate_job_limits(effective_raw, context="limits.effective")
        if effective_raw
        else _require_object(effective_raw, context="limits.effective")
    )
    _validate_preflight_guards(
        limits["guards"],
        environment=environment,
        fixture_inputs=[
            _require_object(item, context="fixture.inputs[]") for item in fixture_inputs
        ],
        fixture_bundle=(
            None
            if fixture["bundle"] is None
            else _require_object(fixture["bundle"], context="fixture.bundle")
        ),
    )
    started = identity["start_monotonic_ns"]
    if started is not None:
        if limits.get("logical_cpu_count_effective") not in {1, 2, 3, 4}:
            raise ContractError("CPU efectiva no está confinada a 1…4")
        cap_id = unit["cap_id"]
        if limits.get("job_memory_commit_limit_bytes_effective") != CAPS[cap_id]:
            raise ContractError("cap job-wide efectivo no coincide con la unidad")
        if limits.get("ready_before_start") is not True:
            raise ContractError("READY no precede START")
        if (
            effective["logical_cpu_count"] != limits["logical_cpu_count_effective"]
            or effective["job_memory_commit_limit_bytes"]
            != limits["job_memory_commit_limit_bytes_effective"]
            or effective["affinity_mask"] != requested["affinity_mask"]
        ):
            raise ContractError("limits efectivos derivados no reconcilian")
    elif classification == "success":
        raise ContractError("success no contiene START observado")
    if not isinstance(limits["ready_before_start"], bool):
        raise ContractError("limits.ready_before_start debe ser booleano")
    outputs = objects["outputs"]
    _require_exact_keys(
        outputs,
        (
            "final_manifest_present",
            "expected_identities",
            "manifest",
            "inventory",
            "quarantined_invalid_manifest",
        ),
        context="outputs",
    )
    final_manifest_present = outputs.get("final_manifest_present")
    if not isinstance(final_manifest_present, bool):
        raise ContractError("outputs.final_manifest_present debe ser booleano")
    if classification == "success" and final_manifest_present is not True:
        raise ContractError("success sin manifiesto final")
    if classification != "success" and final_manifest_present is not False:
        raise ContractError("un no-success conserva manifiesto final publicable")
    expected_identities = outputs["expected_identities"]
    if expected_identities != list(spec.expected_output_identities):
        raise ContractError("outputs.expected_identities no reconcilia con el catálogo")
    if classification == "success" and not isinstance(outputs["manifest"], dict):
        raise ContractError("success no conserva el objeto de manifiesto final")
    if classification != "success" and outputs["manifest"] is not None:
        raise ContractError("un no-success declara contenido de manifiesto publicable")
    if classification == "success":
        _validate_declared_output_manifest(
            outputs["manifest"],
            expected_identities=cast(list[str], expected_identities),
            expected_counts=expected_counts,
            expected_golden_sha256=str(fixture_golden["sha256"]),
        )
    inventory = outputs["inventory"]
    if not isinstance(inventory, list):
        raise ContractError("outputs.inventory debe ser una lista")
    for index, raw_inventory in enumerate(inventory):
        inventory_entry = _require_object(raw_inventory, context=f"outputs.inventory[{index}]")
        _require_exact_keys(
            inventory_entry,
            (
                "relative_path",
                "logical_bytes",
                "allocated_bytes",
                "allocation_reliable",
                "allocation_source",
                "sha256",
            ),
            context=f"outputs.inventory[{index}]",
        )
        _require_text(
            inventory_entry["relative_path"], context=f"outputs.inventory[{index}].relative_path"
        )
        _require_non_negative_int(
            inventory_entry["logical_bytes"], context=f"outputs.inventory[{index}].logical_bytes"
        )
        _require_non_negative_int(
            inventory_entry["allocated_bytes"],
            context=f"outputs.inventory[{index}].allocated_bytes",
        )
        _require_bool(
            inventory_entry["allocation_reliable"],
            context=f"outputs.inventory[{index}].allocation_reliable",
        )
        _require_text(
            inventory_entry["allocation_source"],
            context=f"outputs.inventory[{index}].allocation_source",
        )
        validate_sha256(inventory_entry["sha256"], context=f"outputs.inventory[{index}].sha256")
    inventory_paths = [cast(dict[str, Any], item)["relative_path"] for item in inventory]
    if inventory_paths != sorted(inventory_paths) or len(set(inventory_paths)) != len(
        inventory_paths
    ):
        raise ContractError("outputs.inventory contiene paths duplicados o fuera de orden")
    quarantine = outputs["quarantined_invalid_manifest"]
    if quarantine is not None:
        quarantine_object = _require_object(
            quarantine, context="outputs.quarantined_invalid_manifest"
        )
        _require_exact_keys(
            quarantine_object,
            ("original_path", "quarantine_path", "sha256"),
            context="outputs.quarantined_invalid_manifest",
        )
        _require_text(
            quarantine_object["original_path"],
            context="outputs.quarantined_invalid_manifest.original_path",
        )
        _require_text(
            quarantine_object["quarantine_path"],
            context="outputs.quarantined_invalid_manifest.quarantine_path",
        )
        validate_sha256(
            quarantine_object["sha256"],
            context="outputs.quarantined_invalid_manifest.sha256",
        )
    termination = objects["termination"]
    _require_exact_keys(
        termination,
        (
            "returncode_signed",
            "returncode_unsigned",
            "client_returncode_signed",
            "client_returncode_unsigned",
            "cleanup_complete",
            "tree_empty",
            "client_tree_empty",
            "trigger_classification",
            "timed_out",
            "cancelled",
            "worker_result",
        ),
        context="termination",
    )
    for name in (
        "cleanup_complete",
        "tree_empty",
        "client_tree_empty",
        "timed_out",
        "cancelled",
    ):
        _require_bool(termination[name], context=f"termination.{name}")
    for name in (
        "returncode_signed",
        "returncode_unsigned",
        "client_returncode_signed",
        "client_returncode_unsigned",
    ):
        returncode = termination[name]
        if returncode is not None and (
            isinstance(returncode, bool) or not isinstance(returncode, int)
        ):
            raise ContractError(f"termination.{name}: returncode inválido")
    signed = termination["returncode_signed"]
    unsigned = termination["returncode_unsigned"]
    if signed is None and unsigned is not None:
        raise ContractError("returncode unsigned existe sin signed")
    if isinstance(signed, int) and unsigned != signed & 0xFFFFFFFF:
        raise ContractError("returncodes signed/unsigned no reconcilian")
    client_signed = termination["client_returncode_signed"]
    client_unsigned = termination["client_returncode_unsigned"]
    if client_signed is None and client_unsigned is not None:
        raise ContractError("returncode cliente unsigned existe sin signed")
    if isinstance(client_signed, int) and client_unsigned != client_signed & 0xFFFFFFFF:
        raise ContractError("returncodes cliente signed/unsigned no reconcilian")
    _validate_worker_result(
        termination["worker_result"],
        expected_attempt_id=str(identity["attempt_id"]),
        returncode_signed=cast(int | None, signed),
        returncode_unsigned=cast(int | None, unsigned),
        client_returncode_signed=cast(int | None, client_signed),
        classification=str(classification),
    )
    if termination["cleanup_complete"] is not bool(
        termination["tree_empty"] and termination["client_tree_empty"]
    ):
        raise ContractError("cleanup_complete no deriva de ambos árboles")
    if classification == "orphan_detected":
        if termination["cleanup_complete"] is not False:
            raise ContractError("orphan_detected exige un árbol final no vacío")
    elif termination["cleanup_complete"] is not True:
        raise ContractError("cleanup incompleto debe clasificarse orphan_detected")
    _validate_termination_classification_flags(
        classification=str(classification),
        trigger_classification=cast(str | None, termination["trigger_classification"]),
        cleanup_complete=termination["cleanup_complete"],
        timed_out=cast(bool, termination["timed_out"]),
        cancelled=cast(bool, termination["cancelled"]),
    )
    resources = objects["resources"]
    _require_exact_keys(
        resources,
        (
            "job_accounting",
            "external_client",
            "memory_limit_violation",
            "summary",
            "sidecars",
            "disk_baseline_volume_free_bytes",
            "disk_baseline",
            "disk_final",
            "disk_footprint",
        ),
        context="resources",
    )
    _require_non_negative_int(
        resources["disk_baseline_volume_free_bytes"],
        context="resources.disk_baseline_volume_free_bytes",
    )
    sidecars = resources.get("sidecars")
    if not isinstance(sidecars, list) or len(sidecars) != len(ATTEMPT_SIDECAR_SPECS):
        raise ContractError("resources.sidecars debe enumerar exactamente quince sidecars")
    observed_sidecar_names: list[str] = []
    for index, raw_sidecar in enumerate(sidecars):
        sidecar = _require_object(raw_sidecar, context=f"sidecar[{index}]")
        _require_exact_keys(
            sidecar,
            ("name", "path", "format", "records", "bytes", "sha256"),
            context=f"sidecar[{index}]",
        )
        validate_sha256(sidecar.get("sha256"), context=f"sidecar[{index}].sha256")
        records = sidecar.get("records")
        if isinstance(records, bool) or not isinstance(records, int) or records < 0:
            raise ContractError("conteo de sidecar inválido")
        name = _require_text(sidecar["name"], context=f"sidecar[{index}].name")
        observed_sidecar_names.append(name)
        _require_text(sidecar["path"], context=f"sidecar[{index}].path")
        if sidecar["format"] not in {"jsonl", "binary"}:
            raise ContractError("formato de sidecar fuera del catálogo")
        _require_non_negative_int(sidecar["bytes"], context=f"sidecar[{index}].bytes")
    if observed_sidecar_names != list(ATTEMPT_SIDECAR_NAMES):
        raise ContractError("censo/orden de sidecars no es exacto")
    expected_formats = [format_name for _name, format_name in ATTEMPT_SIDECAR_SPECS]
    if [cast(dict[str, Any], raw)["format"] for raw in sidecars] != expected_formats:
        raise ContractError("formatos de sidecars no reconcilian con el censo cerrado")
    _validate_exact_sidecar_paths(
        sidecars,
        evidence_path=identity["evidence_path"],
        terminal_identities=False,
        verify_path_safety=verify_artifacts,
        context="resources",
    )
    summary = _require_object(resources["summary"], context="resources.summary")
    summary_guard = summary.get("guard_classification")
    if summary_guard is not None and summary_guard != classification:
        raise ContractError("clasificación final no reconcilia con la guarda de recursos")
    if classification == "success" and summary_guard is not None:
        raise ContractError("success conserva una guarda de recursos")
    client = _require_object(resources["external_client"], context="resources.external_client")
    _require_exact_keys(
        client,
        ("declared", "command_sha256", "accounting", "final_census"),
        context="resources.external_client",
    )
    declared_client = _require_bool(
        client["declared"], context="resources.external_client.declared"
    )
    is_ui = unit["flow_id"] == "F-UI"
    if declared_client is not is_ui:
        raise ContractError("declaración de cliente externo no coincide con el flujo")
    if declared_client:
        validate_sha256(
            client["command_sha256"], context="resources.external_client.command_sha256"
        )
        client_accounting = _require_object(
            client["accounting"], context="resources.external_client.accounting"
        )
        client_census = _require_object(
            client["final_census"], context="resources.external_client.final_census"
        )
        _require_exact_keys(
            client_accounting,
            (
                "source",
                "root_pid",
                "total_user_time_100ns",
                "total_kernel_time_100ns",
                "total_user_seconds",
                "total_kernel_seconds",
                "total_page_fault_count",
                "total_processes",
                "active_processes",
                "total_terminated_processes",
                "peak_process_memory_commit_bytes",
                "peak_job_memory_commit_bytes",
                "current_job_memory_commit_bytes",
                "memory_usage_information_supported",
                "io",
            ),
            context="resources.external_client.accounting",
        )
        if client_accounting.get("source") != "windows_external_cleanup_job":
            raise ContractError("accounting del cliente externo tiene otra fuente")
        _require_non_negative_int(
            client_accounting["root_pid"], context="resources.external_client.accounting.root_pid"
        )
        for name in (
            "total_user_time_100ns",
            "total_kernel_time_100ns",
            "total_page_fault_count",
            "total_processes",
            "active_processes",
            "total_terminated_processes",
            "peak_process_memory_commit_bytes",
            "peak_job_memory_commit_bytes",
        ):
            _require_non_negative_int(
                client_accounting[name], context=f"resources.external_client.accounting.{name}"
            )
        _validate_job_memory_usage_information(
            client_accounting,
            context="resources.external_client.accounting",
            require_supported=classification == "success",
        )
        if classification != "orphan_detected" and client_accounting.get("active_processes") != 0:
            raise ContractError("accounting final del cliente conserva procesos activos")
        _require_exact_keys(
            client_census, ("accounting", "tree"), context="resources.external_client.final_census"
        )
        if client_census["accounting"] != client_accounting:
            raise ContractError("censo/accounting del cliente no reconcilian")
        from .telemetry import validate_process_tree_snapshot

        tree = validate_process_tree_snapshot(
            client_census["tree"], context="resources.external_client.final_census.tree"
        )
        if classification != "orphan_detected" and any(tree[name] != [] for name in tree):
            raise ContractError("censo final del cliente externo no está vacío")
        ui_first_byte_records = cast(dict[str, Any], sidecars[5])["records"]
        if classification == "success":
            if client_signed != 0:
                raise ContractError("success UI no acredita cliente=0")
            if ui_first_byte_records != 1:
                raise ContractError("success UI no acredita exactamente un first-byte externo")
        elif ui_first_byte_records not in {0, 1}:
            raise ContractError("terminación UI no-success admite cero o un first-byte causal")
    elif any(client[name] is not None for name in ("command_sha256", "accounting", "final_census")):
        raise ContractError("flujo no-UI conserva metadatos de cliente externo")
    elif client_signed is not None or client_unsigned is not None:
        raise ContractError("flujo no-UI conserva returncode de cliente")
    elif cast(dict[str, Any], sidecars[5])["records"] != 0:
        raise ContractError("flujo no-UI conserva eventos ui_first_byte")
    if cast(dict[str, Any], sidecars[8])["records"] != 0:
        raise ContractError("client_boundary reservado debe permanecer vacío")
    _validate_root_census_map(resources["disk_baseline"], context="resources.disk_baseline")
    _validate_root_census_map(resources["disk_final"], context="resources.disk_final")
    footprint = _require_object(resources["disk_footprint"], context="resources.disk_footprint")
    _require_exact_keys(
        footprint,
        (
            "allocated_inputs_bundle_bytes",
            "peak_incremental_allocated_bytes",
            "footprint_total_bytes",
        ),
        context="resources.disk_footprint",
    )
    for name in footprint:
        _require_non_negative_int(footprint[name], context=f"resources.disk_footprint.{name}")
    if footprint["footprint_total_bytes"] != (
        footprint["allocated_inputs_bundle_bytes"] + footprint["peak_incremental_allocated_bytes"]
    ):
        raise ContractError("resources.disk_footprint total no reconcilia")
    memory_violation = _require_object(
        resources["memory_limit_violation"], context="resources.memory_limit_violation"
    )
    if memory_violation:
        _require_exact_keys(
            memory_violation,
            (
                "source",
                "limit_flags",
                "violation_limit_flags",
                "job_memory_limit_violated",
                "hard_limit_message_observed",
                "violating_pids",
                "completion_messages",
                "job_memory_bytes_at_violation",
                "job_memory_limit_bytes",
            ),
            context="resources.memory_limit_violation",
        )
        _require_bool(
            memory_violation["job_memory_limit_violated"],
            context="resources.memory_limit_violation.job_memory_limit_violated",
        )
        hard_observed = _require_bool(
            memory_violation["hard_limit_message_observed"],
            context="resources.memory_limit_violation.hard_limit_message_observed",
        )
        messages = memory_violation["completion_messages"]
        if not isinstance(messages, list):
            raise ContractError("memory_limit_violation.completion_messages debe ser lista")
        hard_pids: set[int] = set()
        for index, raw_message in enumerate(messages):
            message = _require_object(
                raw_message, context=f"memory_limit_violation.completion_messages[{index}]"
            )
            _require_exact_keys(
                message,
                ("message_id", "completion_key", "message_specific_value"),
                context=f"memory_limit_violation.completion_messages[{index}]",
            )
            for name in message:
                _require_non_negative_int(
                    message[name],
                    context=f"memory_limit_violation.completion_messages[{index}].{name}",
                )
            if message["message_id"] == 10:
                hard_pids.add(int(message["message_specific_value"]))
        violating_pids = memory_violation["violating_pids"]
        if (
            not isinstance(violating_pids, list)
            or violating_pids != sorted(hard_pids)
            or hard_observed is not bool(hard_pids)
            or memory_violation["job_memory_limit_violated"] is not hard_observed
        ):
            raise ContractError("violación hard de memoria no deriva del completion port")
        if (
            classification == "job_memory_limit"
            and memory_violation["job_memory_limit_violated"] is not True
        ):
            raise ContractError("job_memory_limit carece de violación kernel")
        if memory_violation["job_memory_limit_bytes"] != CAPS[unit["cap_id"]]:
            raise ContractError("violación kernel declara otro cap")
    elif classification == "job_memory_limit":
        raise ContractError("job_memory_limit carece de evidencia kernel")
    accounting = _require_object(resources["job_accounting"], context="resources.job_accounting")
    if accounting:
        expected_accounting_fields = (
            "source",
            "total_user_time_100ns",
            "total_kernel_time_100ns",
            "total_user_seconds",
            "total_kernel_seconds",
            "total_page_fault_count",
            "total_processes",
            "active_processes",
            "total_terminated_processes",
            "peak_process_memory_commit_bytes",
            "peak_job_memory_commit_bytes",
            "current_job_memory_commit_bytes",
            "memory_usage_information_supported",
            "io",
        )
        _require_exact_keys(
            accounting, expected_accounting_fields, context="resources.job_accounting"
        )
        if accounting["source"] != "windows_job_object":
            raise ContractError("resources.job_accounting.source inesperado")
        for name in (
            "total_user_time_100ns",
            "total_kernel_time_100ns",
            "total_page_fault_count",
            "total_processes",
            "active_processes",
            "total_terminated_processes",
            "peak_process_memory_commit_bytes",
            "peak_job_memory_commit_bytes",
        ):
            _require_non_negative_int(accounting[name], context=f"resources.job_accounting.{name}")
        _validate_job_memory_usage_information(
            accounting,
            context="resources.job_accounting",
            require_supported=classification == "success",
        )
        if classification != "orphan_detected" and accounting["active_processes"] != 0:
            raise ContractError("evidencia final conserva procesos activos en el Job")
    boundary_events = objects["boundary"].get("events")
    _require_exact_keys(
        objects["boundary"],
        ("provider", "events", "consumer_sidecar_present"),
        context="boundary",
    )
    expected_boundary_provider = (
        "harness_owned_candidate_http_ingress_v1" if is_ui else "harness_owned_consumer_open_v1"
    )
    if objects["boundary"]["provider"] != expected_boundary_provider:
        raise ContractError("boundary.provider no acredita la frontera harness del flujo")
    if not isinstance(boundary_events, list):
        raise ContractError("boundary.events debe ser una lista")
    if not isinstance(objects["boundary"]["consumer_sidecar_present"], bool):
        raise ContractError("boundary.consumer_sidecar_present debe ser booleano")
    positions = validate_boundary_events(
        [_require_object(event, context="boundary.events[]") for event in boundary_events],
        require_complete=classification == "success",
    )
    _validate_consumer_window_declaration(
        summary,
        boundary_events=[
            _require_object(event, context="boundary.events[]") for event in boundary_events
        ],
        positions=positions,
        expected_provider=expected_boundary_provider,
        ready_monotonic_ns=cast(int | None, identity["ready_monotonic_ns"]),
        tree_empty_monotonic_ns=cast(int | None, identity["tree_empty_monotonic_ns"]),
        required=classification == "success",
    )
    if "first_open_or_byte" in positions:
        consumer_start = _require_object(
            boundary_events[positions["first_open_or_byte"]],
            context="boundary.first_open_or_byte",
        )
        if consumer_start["provider"] != expected_boundary_provider:
            raise ContractError("evento inicial consumidor no reconcilia boundary.provider")
        if is_ui:
            if consumer_start["kind"] != "first_byte":
                raise ContractError("F-UI exige primer byte recibido por ingress HTTP")
            geometry_observed = _require_object(
                fixture["geometry_observed"], context="fixture.geometry_observed"
            )
            primary_input = _require_object(
                geometry_observed["primary_input"],
                context="fixture.geometry_observed.primary_input",
            )
            if (
                consumer_start["request_body_bytes"]
                != _require_object(fixture["dimensions"], context="fixture.dimensions")[
                    "payload_bytes"
                ]
                or consumer_start["request_body_bytes"] != primary_input["logical_bytes"]
                or consumer_start["request_body_sha256"] != primary_input["sha256"]
            ):
                raise ContractError("F-UI ingress no recibió el payload protegido byte-exacto")
        else:
            if consumer_start["kind"] != "first_open":
                raise ContractError("flujo no-UI exige broker consumer-open harness-owned")
            expected_open_request_id = canonical_json_sha256(
                {
                    "attempt_id": identity["attempt_id"],
                    "operation": "OPEN",
                    "protected": consumer_start["protected"],
                }
            )
            if consumer_start["request_id"] != expected_open_request_id:
                raise ContractError("consumer-open request_id no liga intento/OPEN/protegidos")
    if is_ui:
        ui_records = cast(dict[str, Any], sidecars[5])["records"]
        if ui_records not in {0, 1} or (classification == "success" and ui_records != 1):
            raise ContractError("ui_first_byte cliente no tiene cardinalidad causal")
    elif cast(dict[str, Any], sidecars[5])["records"] != 0:
        raise ContractError("flujo no-UI conserva evidencia ui_first_byte")
    for event_name, identity_name in (
        ("ready", "ready_monotonic_ns"),
        ("start", "start_monotonic_ns"),
        ("tree_empty", "tree_empty_monotonic_ns"),
    ):
        event_timestamp = (
            boundary_events[positions[event_name]]["monotonic_ns"]
            if event_name in positions
            else None
        )
        if event_timestamp != identity[identity_name]:
            raise ContractError(f"identity.{identity_name} no reconcilia con boundary")
    if classification == "success" and objects["boundary"]["consumer_sidecar_present"] is not True:
        raise ContractError("success no acredita sidecar consumidor")
    gates = objects["gates"]
    _require_exact_keys(
        gates,
        (
            "authority_exact",
            "preflight_passed",
            "limits_effective",
            "sidecars_reconciled",
            "disk_reconciled",
            "output_completeness_bidirectional",
            "atomic_publication",
        ),
        context="gates",
    )
    if not all(isinstance(value, bool) for value in gates.values()):
        raise ContractError("todos los gates deben ser booleanos derivados")
    if gates["authority_exact"] is not True or gates["preflight_passed"] is not True:
        raise ContractError("autoridad/preflight no acreditados")
    if gates["limits_effective"] is not bool(
        effective
        and effective.get("logical_cpu_count") == limits["logical_cpu_count_effective"]
        and effective.get("job_memory_commit_limit_bytes")
        == limits["job_memory_commit_limit_bytes_effective"]
    ):
        raise ContractError("gates.limits_effective no deriva de los límites")
    if gates["atomic_publication"] is not bool(
        (classification == "success" and final_manifest_present)
        or (classification != "success" and not final_manifest_present)
    ):
        raise ContractError("gates.atomic_publication no deriva del estado final")
    if gates["output_completeness_bidirectional"] is not (classification == "success"):
        raise ContractError("gate de completitud no deriva de la clasificación")
    if classification == "success" and not all(gates.values()):
        raise ContractError("success conserva un gate rojo")
    if verify_artifacts:
        from .artifacts import (
            final_inventory,
            validate_census_against_filesystem,
            validate_output_manifest,
            verify_sidecar,
        )
        from .supervisor import (
            tooling_identity,
            validate_candidate_manifest_passive,
            validate_fixture_manifest,
            validate_harness_config,
        )

        launch_source_values = {
            name: cast(dict[str, Any], raw_source) for name, raw_source in launch_sources.items()
        }
        launch_paths: dict[str, Path] = {}
        launch_payloads: dict[str, bytes] = {}
        launch_json_objects: dict[str, dict[str, Any]] = {}
        for name, source in launch_source_values.items():
            source_path = Path(os.path.abspath(str(source["path"])))
            source_payload = _read_descriptor_bound_regular_file(
                path=Path(str(source["path"])),
                context=f"tooling.launch_sources.{name}",
                reject_hardlinks=True,
            )
            launch_paths[name] = source_path
            launch_payloads[name] = source_payload
            if source["identity_kind"] == "raw_file_sha256":
                observed_digest = sha256_bytes(source_payload)
            elif source["identity_kind"] == "ed25519_public_key_sha256":
                _, observed_digest = _trusted_authority_key_identity_from_bytes(
                    source_payload,
                    context=f"tooling.launch_sources.{name}",
                )
            else:
                source_value = _parse_canonical_json_object_bytes(
                    source_payload,
                    context=f"tooling.launch_sources.{name}",
                )
                launch_json_objects[name] = source_value
                observed_digest = canonical_json_sha256(source_value)
            if observed_digest != source["sha256"]:
                raise ContractError(
                    f"tooling.launch_sources.{name}: artefacto cambió tras el intento"
                )

        authority_source = launch_json_objects["authority"]
        if authority_source != authority:
            raise ContractError("authority no reconcilia con su fuente firmada")
        schedule_source = launch_json_objects["schedule"]
        observed_schedule_sha256, observed_schedule_position = validate_schedule(
            schedule_source, unit
        )
        if (
            observed_schedule_sha256 != authority["schedule_sha256"]
            or observed_schedule_position != authority["schedule_position"]
        ):
            raise ContractError("schedule firmado no reconcilia con autoridad/unidad")
        expected_authorization_text = authorization_statement(
            unit,
            authorization_id=str(authority["authorization_id"]),
            authorization_consumption_path_sha256=str(
                authority["authorization_consumption_path_sha256"]
            ),
            tooling_sha256=str(authority["tooling_sha256"]),
            schedule_sha256=observed_schedule_sha256,
            schedule_position=observed_schedule_position,
            scope=str(authority["scope"]),
        )
        if launch_payloads["authorization_text"] != expected_authorization_text:
            raise ContractError("texto de autorización ya no nombra exactamente la unidad")

        candidate_source = launch_json_objects["candidate_manifest"]
        rebuilt_candidate = validate_candidate_manifest_passive(
            candidate_source,
            expected_sha256=str(unit["candidate_manifest_sha256"]),
            manifest_root=launch_paths["candidate_manifest"].resolve().parent,
        )
        if rebuilt_candidate != candidate:
            raise ContractError("candidato declarado no reconcilia con sus artefactos actuales")
        fixture_source = launch_json_objects["fixture_manifest"]
        rebuilt_fixture = validate_fixture_manifest(
            fixture_source,
            expected_sha256=str(unit["fixture_manifest_sha256"]),
            manifest_root=launch_paths["fixture_manifest"].resolve().parent,
            _verify_geometry_material=False,
            _trusted_geometry_observed=_require_object(
                fixture["geometry_observed"], context="fixture.geometry_observed"
            ),
        )
        if rebuilt_fixture != fixture:
            raise ContractError("fixture declarado no reconcilia con sus artefactos actuales")
        config_source = launch_json_objects["config"]
        if canonical_json_sha256(config_source) != unit["config_hash"]:
            raise ContractError("config firmado no reconcilia con la unidad")
        validate_harness_config(
            config_source,
            config_root=launch_paths["config"].resolve().parent,
            candidate_root=Path(str(installed_tree["path"])),
            unit=unit,
            fixture=fixture,
        )

        safe_tooling_paths = {
            name: _validate_unopened_single_link_regular_file(
                path=Path(str(path_value)), context=f"tooling.document_paths.{name}"
            )
            for name, path_value in tooling_paths.items()
        }
        rebuilt_tooling = tooling_identity(safe_tooling_paths)
        for key in (
            "protocol_version",
            "files",
            "harness_runtime",
            "manifest_sha256",
            "document_sha256",
        ):
            if rebuilt_tooling[key] != tooling[key]:
                raise ContractError(f"tooling.{key} no reconcilia con el censo actual")

        for raw_sidecar in sidecars:
            verify_sidecar(cast(dict[str, Any], raw_sidecar))
        from .artifacts import verify_jsonl_sidecar
        from .telemetry import derive_consumer_window_summary, summarize_telemetry_records

        resource_records = verify_jsonl_sidecar(cast(dict[str, Any], sidecars[0]))
        if not resource_records:
            raise ContractError("resources sidecar carece de muestra o terminal causal")
        if not effective:
            raise ContractError("resources crudos carecen de límites efectivos")
        rebuilt_summary = summarize_telemetry_records(
            resource_records,
            baseline_roots=cast(dict[str, dict[str, Any]], resources["disk_baseline"]),
            baseline_volume_free_bytes=int(resources["disk_baseline_volume_free_bytes"]),
            interval_seconds=SAMPLE_INTERVAL_SECONDS,
            expected_affinity_mask=int(effective["affinity_mask"]),
            expected_processor_group=int(effective["processor_group"]),
        )
        if "first_open_or_byte" in positions or "rename_complete" in positions:
            if (
                "first_open_or_byte" not in positions
                or "rename_complete" not in positions
                or identity["ready_monotonic_ns"] is None
                or identity["tree_empty_monotonic_ns"] is None
            ):
                raise ContractError("frontera parcial no permite reconstruir consumer_window")
            consumer_window, overhead = derive_consumer_window_summary(
                resource_records,
                boundary_events=cast(list[Mapping[str, Any]], boundary_events),
                ready_monotonic_ns=int(identity["ready_monotonic_ns"]),
                tree_empty_monotonic_ns=int(identity["tree_empty_monotonic_ns"]),
                baseline_roots=cast(dict[str, dict[str, Any]], resources["disk_baseline"]),
            )
            rebuilt_summary["consumer_window"] = consumer_window
            rebuilt_summary["overhead"] = overhead
        if rebuilt_summary != summary:
            raise ContractError("resources.summary no deriva exactamente del sidecar crudo")
        descriptor_objects: dict[str, dict[str, Any]] = {}
        for name, raw_identity in runtime_descriptors.items():
            if raw_identity is None:
                continue
            descriptor_identity = cast(dict[str, Any], raw_identity)
            descriptor_path = Path(str(descriptor_identity["path"]))
            descriptor_value = _read_canonical_control_object(
                descriptor_path,
                context=f"tooling.runtime_descriptors.{name}",
                expected_bytes=int(descriptor_identity["bytes"]),
                expected_sha256=str(descriptor_identity["sha256"]),
            )
            descriptor_objects[name] = descriptor_value
        from .adapters import (
            validate_adapter_descriptor,
            validate_adapter_request,
            validate_ui_client_request,
        )

        live_bindings = {
            "candidate_manifest_sha256": str(unit["candidate_manifest_sha256"]),
            "fixture_manifest_sha256": str(unit["fixture_manifest_sha256"]),
            "config_hash": str(unit["config_hash"]),
            "tooling_manifest_sha256": str(tooling["manifest_sha256"]),
        }
        normalized_descriptor = validate_adapter_descriptor(
            descriptor_objects["adapter_descriptor"],
            candidate_root=Path(str(installed_tree["path"])),
            expected_flow_id=str(unit["flow_id"]),
            expected_flow_step=str(unit["flow_step"]),
            expected_bindings=live_bindings,
        )
        normalized_request = validate_adapter_request(
            descriptor_objects["adapter_request"],
            require_fresh_candidate_pycache=False,
        )
        if (
            normalized_descriptor["attempt_id"] != identity["attempt_id"]
            or normalized_request["attempt_id"] != identity["attempt_id"]
            or normalized_request["bindings"] != live_bindings
        ):
            raise ContractError("descriptores runtime no ligan la unidad/attempt/tooling")
        if unit["flow_id"] == "F-UI":
            if "ui_client_request" not in descriptor_objects:
                raise ContractError("F-UI carece de ui_client_request cerrado")
            normalized_ui_request = validate_ui_client_request(
                descriptor_objects["ui_client_request"]
            )
            if normalized_ui_request["attempt_id"] != identity["attempt_id"]:
                raise ContractError("ui_client_request no liga attempt_id")
            if "first_open_or_byte" in positions:
                ui_boundary = _require_object(
                    boundary_events[positions["first_open_or_byte"]],
                    context="boundary.ui_ingress",
                )
                endpoint_identity = {
                    name: normalized_ui_request[name]
                    for name in (
                        "method",
                        "loopback_host",
                        "port",
                        "path",
                        "expected_status",
                        "request_id",
                        "body",
                    )
                }
                if ui_boundary["service_descriptor_sha256"] != runtime_descriptors[
                    "adapter_descriptor"
                ]["sha256"] or ui_boundary["endpoint_sha256"] != canonical_json_sha256(
                    endpoint_identity
                ):
                    raise ContractError("ingress F-UI no liga servicio/endpoint firmados")
        elif runtime_descriptors["ui_client_request"] is not None:
            raise ContractError("flujo no-UI conserva ui_client_request")

        candidate_launch = _require_object(
            normalized_request["candidate_launch"], context="adapter.candidate_launch"
        )
        candidate_request = _require_object(
            candidate_launch["candidate_request_value"],
            context="adapter.candidate_launch.candidate_request_value",
        )
        candidate_request_raw = descriptor_objects["candidate_request"]
        candidate_request_payload_sha256 = validate_sha256(
            candidate_launch["candidate_request_payload_sha256"],
            context="adapter.candidate_launch.candidate_request_payload_sha256",
        )
        if candidate_request["attempt_id"] != identity["attempt_id"]:
            raise ContractError("candidate request no liga attempt_id de la evidencia")
        candidate_descriptor_identity = cast(
            dict[str, Any], runtime_descriptors["candidate_request"]
        )
        candidate_launch_identity = _require_object(
            candidate_launch["candidate_request"],
            context="adapter.candidate_launch.candidate_request",
        )
        if (
            candidate_descriptor_identity["path"] != candidate_launch_identity["path"]
            or candidate_descriptor_identity["bytes"] != candidate_launch_identity["logical_bytes"]
            or candidate_descriptor_identity["sha256"] != candidate_launch_identity["sha256"]
        ):
            raise ContractError("candidate request runtime no liga el launch byte-exacto")
        snapshot_descriptor_identity = cast(
            dict[str, Any], runtime_descriptors["harness_runtime_snapshot"]
        )
        snapshot_launch_identity = _require_object(
            candidate_launch["harness_runtime_snapshot"],
            context="adapter.candidate_launch.harness_runtime_snapshot",
        )
        if (
            snapshot_descriptor_identity["path"] != snapshot_launch_identity["path"]
            or snapshot_descriptor_identity["bytes"] != snapshot_launch_identity["logical_bytes"]
            or snapshot_descriptor_identity["sha256"] != snapshot_launch_identity["sha256"]
        ):
            raise ContractError("harness runtime snapshot no liga descriptor/launch")
        launch_material = _require_object(
            candidate_request["launch_material"], context="candidate.launch_material"
        )
        workdir = Path(str(identity["evidence_path"])).resolve().parent
        expected_workdir_sha = sha256_bytes(
            str(workdir).replace("\\", "/").casefold().encode("utf-8")
        )
        candidate_runtime = _require_object(
            candidate_request["runtime"], context="candidate.runtime"
        )
        candidate_python = _require_object(
            candidate_runtime["python_executable"], context="candidate.runtime.python_executable"
        )
        evidence_python = _require_object(
            runtime["python_executable"], context="candidate.runtime.python_executable.evidence"
        )
        if (
            launch_material["unit"] != unit
            or launch_material["adapter_descriptor_sha256"]
            != runtime_descriptors["adapter_descriptor"]["sha256"]
            or launch_material["harness_runtime_snapshot_sha256"]
            != snapshot_descriptor_identity["sha256"]
            or launch_material["tooling_manifest_sha256"] != tooling["manifest_sha256"]
            or launch_material["workdir_sha256"] != expected_workdir_sha
            or candidate_runtime["candidate_root"] != Path(str(installed_tree["path"]))
            or candidate_runtime["candidate_tree_sha256"] != installed_tree["sha256"]
            or candidate_python["path"] != evidence_python["path"]
            or candidate_python["logical_bytes"] != evidence_python["bytes"]
            or candidate_python["sha256"] != evidence_python["sha256"]
            or candidate_runtime["job_memory_commit_limit_bytes"]
            != limits["job_memory_commit_limit_bytes_effective"]
            or candidate_runtime["affinity_mask"] != effective["affinity_mask"]
        ):
            raise ContractError("candidate launch material/runtime no liga unidad/workdir/límites")
        candidate_paths = _require_object(candidate_request["paths"], context="candidate.paths")
        candidate_runtime_root = workdir / "scratch" / "candidate-runtime"
        expected_candidate_paths = {
            "staging": workdir / "scratch" / "consumer-staging",
            "candidate_outputs": workdir
            / "scratch"
            / "consumer-staging"
            / "candidate-outputs.json",
            "adapter_result": workdir / "telemetry" / "control" / "adapter-result.json",
            "brokered_inputs_json": candidate_runtime_root / "brokered-inputs.json",
            "pycache": workdir / "scratch" / "python-cache" / "candidate-child",
            "stdout": workdir / "telemetry" / "candidate.stdout.bin",
            "stderr": workdir / "telemetry" / "candidate.stderr.bin",
            "controller_stdout": workdir / "telemetry" / "candidate-controller.stdout.bin",
            "controller_stderr": workdir / "telemetry" / "candidate-controller.stderr.bin",
            "service_ready": candidate_runtime_root / "service-ready.json",
            "candidate_start": workdir / "telemetry" / "control" / "candidate-start.json",
            "candidate_result": workdir / "telemetry" / "control" / "candidate-result.json",
        }
        if any(
            os.path.normcase(Path(str(candidate_paths[name])).resolve())
            != os.path.normcase(expected_path.resolve())
            for name, expected_path in expected_candidate_paths.items()
        ):
            raise ContractError("candidate paths no derivan del workdir reservado")
        from .artifacts import is_reparse_or_symlink

        candidate_pycache = expected_candidate_paths["pycache"]
        if not candidate_pycache.is_dir() or any(
            is_reparse_or_symlink(path)
            for path in (candidate_pycache, *candidate_pycache.parents[:-1])
        ):
            raise ContractError("candidate pycache post-run escapa o atraviesa reparse point")
        pool_sidecars = [
            cast(dict[str, Any], raw)
            for raw in sidecars
            if isinstance(raw, dict) and raw.get("name") == "native_pools"
        ]
        if len(pool_sidecars) != 1:
            raise ContractError("censo de sidecar native_pools no es exacto")
        native_pool_event: dict[str, Any] | None = None
        if classification == "success":
            native_pool_events = verify_jsonl_sidecar(pool_sidecars[0])
            validate_native_pool_events(native_pool_events)
            native_pool_event = dict(native_pool_events[0])
        disk_final = _require_object(resources["disk_final"], context="resources.disk_final")
        roots = {
            name: Path(str(_require_object(raw, context=f"disk_final.{name}")["root"]))
            for name, raw in disk_final.items()
        }
        validate_census_against_filesystem(disk_final, roots)
        output_root = roots["outputs"]
        manifest: dict[str, Any] | None = None
        if classification == "success":
            fixture = objects["fixture"]
            expected = _require_object(fixture["expected"], context="fixture.expected")
            golden = _require_object(expected["golden"], context="fixture.expected.golden")
            manifest = validate_output_manifest(
                output_root,
                expected_identities=cast(list[str], outputs["expected_identities"]),
                expected_counts=cast(dict[str, int], expected["counts"]),
                expected_golden_sha256=str(golden["sha256"]),
            )
            if manifest != outputs["manifest"]:
                raise ContractError("manifiesto declarado no reconcilia con outputs")
        sidecars_by_name = {
            str(cast(dict[str, Any], raw)["name"]): cast(dict[str, Any], raw) for raw in sidecars
        }
        expected_candidate_log_paths = {
            "candidate_stdout": expected_candidate_paths["stdout"],
            "candidate_stderr": expected_candidate_paths["stderr"],
            "candidate_controller_stdout": expected_candidate_paths["controller_stdout"],
            "candidate_controller_stderr": expected_candidate_paths["controller_stderr"],
        }
        for name, expected_path in expected_candidate_log_paths.items():
            metadata = sidecars_by_name[name]
            if (
                metadata["format"] != "binary"
                or metadata["records"] != 1
                or os.path.normcase(Path(str(metadata["path"])).resolve())
                != os.path.normcase(expected_path.resolve())
            ):
                raise ContractError(f"sidecar {name} no liga el log candidate firmado")
        from .consumer import reconstruct_consumer_sidecars

        reconstructed_consumer = reconstruct_consumer_sidecars(
            boundary_metadata=sidecars_by_name["boundary"],
            filesystem_metadata=sidecars_by_name["filesystem"],
            output_root=output_root,
            manifest=manifest,
            require_complete=classification == "success",
        )
        for consumer_event in reconstructed_consumer["boundary_events"]:
            if sum(event == consumer_event for event in boundary_events) != 1:
                raise ContractError(
                    "boundary combinado no reconcilia exactamente con sidecar consumidor"
                )
        from .adapters import validate_adapter_audit, validate_ui_first_byte

        audit_sidecar = sidecars_by_name["adapter_audit"]
        audit_events: list[dict[str, Any]] = []
        if classification == "success" or audit_sidecar["records"]:
            audit_events = validate_adapter_audit(
                Path(str(audit_sidecar["path"])), require_success=classification == "success"
            )
        ui_sidecar = sidecars_by_name["ui_first_byte"]
        ui_event: dict[str, Any] | None = None
        if ui_sidecar["records"]:
            ui_event = validate_ui_first_byte(
                Path(str(ui_sidecar["path"])), attempt_id=str(identity["attempt_id"])
            )
            consumer_boundary = reconstructed_consumer["boundary_events"]
            request_event = consumer_boundary[0] if consumer_boundary else None
            if not isinstance(request_event, Mapping):
                raise ContractError("F-UI carece de ingress consumidor reconstruido")
            _validate_ui_ingress_response_order(request_event, ui_event)
        if classification == "success":
            execution_request_path = workdir / "telemetry" / "control" / "candidate-execution.json"
            candidate_start_path = expected_candidate_paths["candidate_start"]
            candidate_result_path = expected_candidate_paths["candidate_result"]
            adapter_result_path = expected_candidate_paths["adapter_result"]
            candidate_start = _read_canonical_control_object(
                candidate_start_path, context="candidate-start final"
            )
            candidate_result = _read_canonical_control_object(
                candidate_result_path, context="candidate-result final"
            )
            adapter_result = _read_canonical_control_object(
                adapter_result_path, context="adapter-result final"
            )
            execution_identity = _validate_candidate_file_identity(
                candidate_start.get("candidate_execution_request"),
                expected_path=execution_request_path,
                context="candidate-start.candidate_execution_request",
                verify_artifact=False,
            )
            execution_request = _read_canonical_control_object(
                execution_request_path,
                context="candidate-execution request final",
                expected_bytes=int(execution_identity["logical_bytes"]),
                expected_sha256=str(execution_identity["sha256"]),
            )
            from .adapters import (
                validate_candidate_http_exchange,
                validate_candidate_service_ready,
                validate_native_pools_observation,
            )

            candidate_process = _validate_candidate_process_identity(
                candidate_result.get("candidate_process"),
                context="candidate-result.candidate_process",
            )
            observation_identity = _validate_candidate_file_identity(
                candidate_result.get("native_pools_observation"),
                expected_path=workdir / "telemetry" / "control" / "native-pools-observation.json",
                context="candidate-result.native_pools_observation",
            )
            total_processes = _require_non_negative_int(
                candidate_result.get("total_processes"),
                context="candidate-result.total_processes",
            )
            candidate_process_census = _validate_candidate_process_census(
                candidate_result.get("candidate_process_census"),
                root_process=candidate_process,
                expected_total_processes=total_processes,
            )
            census_processes = cast(list[dict[str, Any]], candidate_process_census["processes"])
            native_pools_observation = validate_native_pools_observation(
                Path(str(observation_identity["path"])),
                candidate_execution_request_sha256=str(execution_identity["sha256"]),
                native_pools_root=candidate_runtime_root / "native-pools",
                expected_process_census=census_processes,
            )
            if native_pool_event is None:
                raise ContractError("success carece del sidecar native_pools")
            _reconcile_native_pool_evidence(
                candidate_process=candidate_process,
                expected_process_census=census_processes,
                aggregate=native_pools_observation,
                sidecar_event=native_pool_event,
            )
            consumer_events = reconstructed_consumer["boundary_events"]
            filesystem_events = reconstructed_consumer["filesystem_events"]
            if not consumer_events or not filesystem_events or manifest is None:
                raise ContractError("success carece de frontera/filesystem/manifiesto causal")
            common_chain: dict[str, Any] = {
                "candidate_request_raw": candidate_request_raw,
                "candidate_request": candidate_request,
                "harness_runtime_snapshot": _require_object(
                    candidate_launch["harness_runtime_snapshot_value"],
                    context="adapter.candidate_launch.harness_runtime_snapshot_value",
                ),
                "candidate_request_payload_sha256": candidate_request_payload_sha256,
                "execution_request": execution_request,
                "execution_request_identity": execution_identity,
                "candidate_start": candidate_start,
                "candidate_result": candidate_result,
                "native_pools_observation": observation_identity,
                "adapter_result": adapter_result,
                "consumer_start": consumer_events[0],
                "audit_events": audit_events,
                "expected_attempt_id": str(identity["attempt_id"]),
                "expected_output_manifest_sha256": sha256_file(output_root / "manifest.json"),
                "start_monotonic_ns": int(identity["start_monotonic_ns"]),
                "first_publisher_monotonic_ns": int(filesystem_events[0]["monotonic_ns"]),
            }
            if not is_ui:
                _validate_candidate_execution_chain(**common_chain)
            else:
                if ui_event is None:
                    raise ContractError("success F-UI carece de response first-byte")
                service_ready_identity = _validate_candidate_file_identity(
                    candidate_result.get("service_ready"),
                    expected_path=expected_candidate_paths["service_ready"],
                    context="candidate-result.service_ready",
                    verify_artifact=False,
                )
                service_ready_value = _read_canonical_control_object(
                    expected_candidate_paths["service_ready"],
                    context="candidate service-ready final",
                    expected_bytes=int(service_ready_identity["logical_bytes"]),
                    expected_sha256=str(service_ready_identity["sha256"]),
                )
                http_exchange_path = (
                    workdir / "telemetry" / "control" / "candidate-http-exchange.json"
                )
                http_exchange_identity = _validate_candidate_file_identity(
                    adapter_result.get("http_exchange"),
                    expected_path=http_exchange_path,
                    context="adapter-result.http_exchange",
                    verify_artifact=False,
                )
                http_exchange_value = _read_canonical_control_object(
                    http_exchange_path,
                    context="candidate HTTP exchange final",
                    expected_bytes=int(http_exchange_identity["logical_bytes"]),
                    expected_sha256=str(http_exchange_identity["sha256"]),
                )
                implementation = _require_object(
                    normalized_descriptor.get("implementation"),
                    context="adapter descriptor implementation",
                )
                expected_service = _require_object(
                    implementation.get("service"), context="adapter descriptor service"
                )
                expected_ingress = _require_object(
                    normalized_request.get("ui_ingress"), context="adapter.ui_ingress"
                )
                validate_candidate_service_ready(
                    expected_candidate_paths["service_ready"],
                    attempt_id=str(identity["attempt_id"]),
                    candidate_request_sha256=candidate_request_payload_sha256,
                    candidate_process=candidate_process,
                    service=expected_service,
                )
                validate_candidate_http_exchange(
                    http_exchange_path,
                    attempt_id=str(identity["attempt_id"]),
                    candidate_request_sha256=candidate_request_payload_sha256,
                    expected_ingress=expected_ingress,
                    expected_service=expected_service,
                    expected_candidate_process=candidate_process,
                    expected_service_ready=service_ready_identity,
                )
                _validate_candidate_http_execution_chain(
                    **common_chain,
                    service_ready_identity=service_ready_identity,
                    service_ready=service_ready_value,
                    http_exchange_identity=http_exchange_identity,
                    http_exchange=http_exchange_value,
                    ui_response_event=ui_event,
                    expected_ingress=expected_ingress,
                    expected_service=expected_service,
                    output_manifest=manifest,
                )
        if final_inventory(output_root) != outputs["inventory"]:
            raise ContractError("inventario de outputs no reconcilia")
        if _verify_evidence_self_binding:
            evidence_path = Path(str(identity["evidence_path"]))
            expected_evidence_bytes = canonical_json_bytes(value) + b"\n"
            observed_evidence = _read_descriptor_bound_regular_file(
                path=evidence_path,
                expected_bytes=len(expected_evidence_bytes),
                expected_sha256=sha256_bytes(expected_evidence_bytes),
                context="identity.evidence_path",
                reject_hardlinks=True,
            )
            if observed_evidence != expected_evidence_bytes:
                raise ContractError(
                    "identity.evidence_path no contiene esta evidencia canónica exacta"
                )
    return dict(value)


def _schema_sha256() -> dict[str, Any]:
    """Devuelve el contrato SHA-256 canónico compartido por los ocho schemas."""
    return {
        "type": "string",
        "pattern": "^[0-9a-f]{64}$",
        "not": {"enum": ["0" * 64, "f" * 64]},
    }


def _schema_git_sha() -> dict[str, Any]:
    """Devuelve el contrato SHA Git 40/64 lowercase, sin placeholders."""
    return {
        "type": "string",
        "pattern": "^(?:[0-9a-f]{40}|[0-9a-f]{64})$",
        "not": {"enum": ["0" * 40, "f" * 40, "0" * 64, "f" * 64]},
    }


def _schema_ed25519_signature() -> dict[str, Any]:
    """Devuelve la firma Ed25519 hex lowercase canónica y no-placeholder."""
    return {
        "type": "string",
        "pattern": "^[0-9a-f]{128}$",
        "not": {"enum": ["0" * 128, "f" * 128]},
    }


def _schema_object(
    properties: Mapping[str, Any],
    *,
    required: Sequence[str] | None = None,
    pattern_properties: Mapping[str, Any] | None = None,
    min_properties: int | None = None,
    max_properties: int | None = None,
) -> dict[str, Any]:
    """Construye objetos Draft 2020-12 cerrados también cuando usan patternProperties."""
    schema: dict[str, Any] = {
        "type": "object",
        "required": list(properties) if required is None else list(required),
        "additionalProperties": False,
        "properties": dict(properties),
    }
    if pattern_properties is not None:
        schema["patternProperties"] = dict(pattern_properties)
    if min_properties is not None:
        schema["minProperties"] = min_properties
    if max_properties is not None:
        schema["maxProperties"] = max_properties
    return schema


def _attempt_schema_defs() -> dict[str, Any]:
    sha = _schema_sha256()
    path = {"type": "string", "minLength": 1}
    non_negative = {"type": "integer", "minimum": 0}
    positive = {"type": "integer", "minimum": 1}
    nullable_non_negative = {"type": ["integer", "null"], "minimum": 0}
    number_non_negative = {"type": "number", "minimum": 0}
    output_identities = sorted(
        {identity for spec in FLOW_SPECS for identity in spec.expected_output_identities}
    )
    dimension_names = sorted(
        {name for spec in FLOW_SPECS for geometry in spec.geometries.values() for name in geometry}
    )
    pool_names = (
        "OMP_NUM_THREADS",
        "MKL_NUM_THREADS",
        "OPENBLAS_NUM_THREADS",
        "NUMEXPR_NUM_THREADS",
        "BLIS_NUM_THREADS",
        "VECLIB_MAXIMUM_THREADS",
    )
    io = _schema_object(
        {
            "read_operations": non_negative,
            "write_operations": non_negative,
            "other_operations": non_negative,
            "read_bytes": non_negative,
            "write_bytes": non_negative,
            "other_bytes": non_negative,
        }
    )
    file_identity = _schema_object(
        {
            "path": path,
            "relative_path": path,
            "bytes": non_negative,
            "allocated_bytes": non_negative,
            "allocation_reliable": {"type": "boolean"},
            "allocation_source": path,
            "sha256": {"$ref": "#/$defs/sha256"},
        }
    )
    fixture_file = _schema_object(
        {
            "relative_path": path,
            "format": path,
            "rows": nullable_non_negative,
            "expanded_rows": nullable_non_negative,
            "logical_bytes": non_negative,
            "allocated_bytes": non_negative,
            "sha256": {"$ref": "#/$defs/sha256"},
            "path": path,
            "allocation_reliable": {"const": True},
            "allocation_source": path,
        }
    )
    unit = _schema_object(
        {
            "candidate_manifest_sha256": {"$ref": "#/$defs/sha256"},
            "flow_id": {"enum": sorted({spec.flow_id for spec in FLOW_SPECS})},
            "flow_step": {"enum": sorted({spec.step for spec in FLOW_SPECS})},
            "fixture_manifest_sha256": {"$ref": "#/$defs/sha256"},
            "config_hash": {"$ref": "#/$defs/sha256"},
            "geometry_id": {"enum": list(GEOMETRY_IDS)},
            "cap_id": {"enum": list(CAPS)},
            "attempt_ordinal": positive,
        }
    )
    unit["oneOf"] = [
        {
            "properties": {
                "flow_id": {"const": spec.flow_id},
                "flow_step": {"const": spec.step},
            },
            "required": ["flow_id", "flow_step"],
        }
        for spec in FLOW_SPECS
    ]
    group_affinity = _schema_object({"processor_group": non_negative, "affinity_mask": positive})
    job_limits = _schema_object(
        {
            "limit_flags": non_negative,
            "affinity_mask": positive,
            "logical_cpu_count": {"type": "integer", "minimum": 1, "maximum": 4},
            "processor_group": non_negative,
            "group_affinities": {
                "type": "array",
                "minItems": 1,
                "maxItems": 1,
                "items": {"$ref": "#/$defs/group_affinity"},
            },
            "job_memory_commit_limit_bytes": {"enum": list(CAPS.values())},
            "kill_on_job_close": {"const": True},
            "affinity_enforced": {"const": True},
            "job_memory_enforced": {"const": True},
        }
    )
    root_census = _schema_object(
        {
            "root": path,
            "logical_bytes": non_negative,
            "allocated_bytes": non_negative,
            "files": non_negative,
            "allocation_reliable": {"type": "boolean"},
            "allocation_sources": {
                "type": "array",
                "uniqueItems": True,
                "items": path,
            },
        }
    )
    root_census_map = _schema_object(
        {
            name: {"$ref": "#/$defs/root_census"}
            for name in ("inputs", "bundle", "scratch", "outputs", "telemetry")
        }
    )
    chunk = _schema_object(
        {
            "ordinal": non_negative,
            "offset": non_negative,
            "logical_bytes": positive,
            "sha256": {"$ref": "#/$defs/sha256"},
        }
    )
    output_artifact = _schema_object(
        {
            "relative_path": path,
            "identity": {"enum": output_identities},
            "ordinal": non_negative,
            "format": {"enum": ["jsonl", "csv", "json", "parquet"]},
            "record_count": non_negative,
            "count_evidence": _schema_object(
                {
                    "mode": {"const": "derived"},
                    "counter_id": {
                        "enum": [
                            "jsonl-records.v1",
                            "csv-data-rows.v1",
                            "json-array-items.v1",
                            "parquet-footer-rows.v1",
                        ]
                    },
                    "records": non_negative,
                    "output_sha256": {"$ref": "#/$defs/sha256"},
                    "sidecar": {"type": "null"},
                }
            ),
            "logical_bytes": non_negative,
            "allocated_bytes": non_negative,
            "allocation_reliable": {"type": "boolean"},
            "allocation_source": path,
            "sha256": {"$ref": "#/$defs/sha256"},
            "chunks": {"type": "array", "items": {"$ref": "#/$defs/chunk"}},
            "reconciliation_sha256": {"$ref": "#/$defs/sha256"},
        }
    )
    output_manifest = _schema_object(
        {
            "schema_version": {"const": "nikodym.readiness.h9r.outputs.v1"},
            "golden_observed_algorithm": {"const": "canonical-output-inventory-sha256.v1"},
            "golden_observed_sha256": {"$ref": "#/$defs/sha256"},
            "artifacts": {
                "type": "array",
                "minItems": 1,
                "uniqueItems": True,
                "items": {"$ref": "#/$defs/output_artifact"},
            },
        }
    )
    inventory_entry = _schema_object(
        {
            "relative_path": path,
            "logical_bytes": non_negative,
            "allocated_bytes": non_negative,
            "allocation_reliable": {"type": "boolean"},
            "allocation_source": path,
            "sha256": {"$ref": "#/$defs/sha256"},
        }
    )
    protected_identity = _schema_object(
        {
            "logical_id": {"$ref": "#/$defs/sha256"},
            "role": {"enum": ["input", "bundle", "config"]},
            "relative_name": {
                "type": "string",
                "pattern": r"^(?!/)(?!.*(?:^|/)\.\.?(?:/|$))(?!.*\\)(?!.*:)[^/]+(?:/[^/]+)*$",
            },
            "logical_bytes": non_negative,
            "sha256": {"$ref": "#/$defs/sha256"},
        }
    )
    candidate_process = _schema_object({"pid": positive, "creation_time_100ns": positive})
    boundary_event = {
        "oneOf": [
            _schema_object(
                {
                    "event": {"const": "boot"},
                    "monotonic_ns": non_negative,
                    "pid": positive,
                    "heavy_work_started": {"const": False},
                }
            ),
            _schema_object(
                {
                    "event": {"const": "limits_applied"},
                    "monotonic_ns": non_negative,
                    "effective_limits": {"$ref": "#/$defs/job_limits"},
                }
            ),
            _schema_object(
                {
                    "event": {"const": "ready"},
                    "monotonic_ns": non_negative,
                    "heavy_work_started": {"const": False},
                }
            ),
            *[
                _schema_object({"event": {"const": event_name}, "monotonic_ns": non_negative})
                for event_name in ("start", "tree_empty")
            ],
            _schema_object(
                {
                    "event": {"const": "first_open_or_byte"},
                    "monotonic_ns": non_negative,
                    "kind": {"const": "first_open"},
                    "provider": {"const": "harness_owned_consumer_open_v1"},
                    "request_id": {"$ref": "#/$defs/sha256"},
                    "protected": {
                        "type": "array",
                        "minItems": 1,
                        "uniqueItems": True,
                        "items": protected_identity,
                    },
                    "broker_request_sha256": {"$ref": "#/$defs/sha256"},
                    "nonce_commitment_sha256": {"$ref": "#/$defs/sha256"},
                    "candidate_process": candidate_process,
                }
            ),
            _schema_object(
                {
                    "event": {"const": "first_open_or_byte"},
                    "monotonic_ns": non_negative,
                    "kind": {"const": "first_byte"},
                    "provider": {"const": "harness_owned_candidate_http_ingress_v1"},
                    "request_id": path,
                    "request_body_bytes": non_negative,
                    "request_body_sha256": {"$ref": "#/$defs/sha256"},
                    "service_descriptor_sha256": {"$ref": "#/$defs/sha256"},
                    "endpoint_sha256": {"$ref": "#/$defs/sha256"},
                    "non_transforming": {"const": True},
                }
            ),
            _schema_object(
                {
                    "event": {"const": "flush_complete"},
                    "monotonic_ns": non_negative,
                    "artifact_count": non_negative,
                    "logical_bytes": non_negative,
                }
            ),
            _schema_object(
                {
                    "event": {"const": "hash_complete"},
                    "monotonic_ns": non_negative,
                    "artifact_count": non_negative,
                    "artifact_sha256": {
                        "type": "array",
                        "items": {"$ref": "#/$defs/sha256"},
                    },
                }
            ),
            _schema_object(
                {
                    "event": {"const": "rename_complete"},
                    "monotonic_ns": non_negative,
                    "path": path,
                    "sha256": {"$ref": "#/$defs/sha256"},
                }
            ),
        ]
    }
    sidecar = _schema_object(
        {
            "name": {"enum": list(ATTEMPT_SIDECAR_NAMES)},
            "path": path,
            "format": {"enum": ["jsonl", "binary"]},
            "records": non_negative,
            "bytes": non_negative,
            "sha256": {"$ref": "#/$defs/sha256"},
        }
    )
    job_accounting = _schema_object(
        {
            "source": {"const": "windows_job_object"},
            "total_user_time_100ns": non_negative,
            "total_kernel_time_100ns": non_negative,
            "total_user_seconds": number_non_negative,
            "total_kernel_seconds": number_non_negative,
            "total_page_fault_count": non_negative,
            "total_processes": non_negative,
            "active_processes": non_negative,
            "total_terminated_processes": non_negative,
            "peak_process_memory_commit_bytes": non_negative,
            "peak_job_memory_commit_bytes": non_negative,
            "current_job_memory_commit_bytes": nullable_non_negative,
            "memory_usage_information_supported": {"type": "boolean"},
            "io": io,
        }
    )
    job_accounting["oneOf"] = [
        {
            "properties": {
                "memory_usage_information_supported": {"const": True},
                "current_job_memory_commit_bytes": non_negative,
            }
        },
        {
            "properties": {
                "memory_usage_information_supported": {"const": False},
                "current_job_memory_commit_bytes": {"type": "null"},
            }
        },
    ]
    external_accounting = _schema_object(
        {
            "source": {"const": "windows_external_cleanup_job"},
            "root_pid": {"type": ["integer", "null"], "minimum": 1},
            "total_user_time_100ns": non_negative,
            "total_kernel_time_100ns": non_negative,
            "total_user_seconds": number_non_negative,
            "total_kernel_seconds": number_non_negative,
            "total_page_fault_count": non_negative,
            "total_processes": non_negative,
            "active_processes": non_negative,
            "total_terminated_processes": non_negative,
            "peak_process_memory_commit_bytes": non_negative,
            "peak_job_memory_commit_bytes": non_negative,
            "current_job_memory_commit_bytes": nullable_non_negative,
            "memory_usage_information_supported": {"type": "boolean"},
            "io": io,
        }
    )
    external_accounting["oneOf"] = job_accounting["oneOf"]
    process_metric = _schema_object(
        {
            "pid": positive,
            "creation_time_100ns": positive,
            "cpu_user_100ns": non_negative,
            "cpu_kernel_100ns": non_negative,
            "page_fault_count": non_negative,
            "working_set_bytes": non_negative,
            "peak_working_set_bytes": non_negative,
            "pagefile_bytes": non_negative,
            "peak_pagefile_bytes": non_negative,
            "private_usage_bytes": non_negative,
            "affinity_mask": positive,
            "system_affinity_mask": positive,
            "logical_cpu_count_effective": positive,
            "processor_groups": {
                "type": "array",
                "minItems": 1,
                "uniqueItems": True,
                "items": non_negative,
            },
            "io": io,
        }
    )
    thread_identity = _schema_object(
        {
            "pid": positive,
            "tid": positive,
            "creation_time_100ns": positive,
            "processor_group": non_negative,
            "affinity_mask": positive,
            "logical_cpu_count_effective": positive,
        }
    )
    process_query_error = _schema_object({"pid": positive, "error": path})
    thread_query_error = _schema_object({"pid": positive, "tid": positive, "error": path})
    external_census = _schema_object(
        {
            "accounting": external_accounting,
            "tree": _schema_object(
                {
                    "pids": {"type": "array", "uniqueItems": True, "items": positive},
                    "processes": {
                        "type": "array",
                        "uniqueItems": True,
                        "items": process_metric,
                    },
                    "threads": {
                        "type": "array",
                        "uniqueItems": True,
                        "items": thread_identity,
                    },
                    "process_query_errors": {
                        "type": "array",
                        "uniqueItems": True,
                        "items": process_query_error,
                    },
                    "thread_query_errors": {
                        "type": "array",
                        "uniqueItems": True,
                        "items": thread_query_error,
                    },
                }
            ),
        }
    )
    high_water = _schema_object(
        {
            "peak_logical_bytes": non_negative,
            "peak_allocated_bytes": non_negative,
            "peak_incremental_allocated_bytes": non_negative,
        }
    )
    full_summary = _schema_object(
        {
            "records": positive,
            "sample_interval_seconds": {"const": SAMPLE_INTERVAL_SECONDS},
            "max_gap_seconds": number_non_negative,
            "peak_job_memory_commit_bytes": non_negative,
            "peak_tree_working_set_bytes": non_negative,
            "peak_supervisor_working_set_bytes": non_negative,
            "peak_client_working_set_bytes": non_negative,
            "peak_client_job_commit_bytes": non_negative,
            "minimum_physical_available_bytes": non_negative,
            "minimum_commit_available_bytes": non_negative,
            "minimum_volume_free_bytes": non_negative,
            "maximum_threads_observed": non_negative,
            "observed_process_identities": {
                "type": "array",
                "uniqueItems": True,
                "items": _schema_object({"pid": positive, "creation_time_100ns": non_negative}),
            },
            "observed_client_process_identities": {
                "type": "array",
                "uniqueItems": True,
                "items": _schema_object({"pid": positive, "creation_time_100ns": non_negative}),
            },
            "root_high_water": _schema_object(
                {},
                required=(),
                pattern_properties={"^(inputs|bundle|scratch|outputs|telemetry)$": high_water},
            ),
            "peak_incremental_allocated_bytes": non_negative,
            "guard_classification": {"type": ["string", "null"], "enum": [*CLASSIFICATIONS, None]},
            "guard_reason": {"type": ["string", "null"]},
        }
    )
    consumer_window_coverage = _schema_object(
        {
            "start_bracket_ordinal": non_negative,
            "end_bracket_ordinal": non_negative,
            "inside_sample_ordinals": {
                "type": "array",
                "uniqueItems": True,
                "items": non_negative,
            },
            "start_gap_ns": non_negative,
            "end_gap_ns": non_negative,
            "resolution": {"enum": ["inside_samples", "bracketed"]},
        }
    )
    full_summary["properties"]["consumer_window"] = _schema_object(
        {
            "provider": {
                "enum": [
                    "harness_owned_consumer_open_v1",
                    "harness_owned_candidate_http_ingress_v1",
                ]
            },
            "start_monotonic_ns": non_negative,
            "end_monotonic_ns": non_negative,
            "wall_seconds": number_non_negative,
            "sample_ordinals": {
                "type": "array",
                "minItems": 1,
                "uniqueItems": True,
                "items": non_negative,
            },
            "records": positive,
            "coverage": consumer_window_coverage,
            "peak_tree_working_set_bytes": non_negative,
            "peak_job_memory_commit_bytes_observed_during_window": non_negative,
            "peak_incremental_allocated_bytes": non_negative,
            "total_job_cpu_delta_100ns": non_negative,
        }
    )
    full_summary["properties"]["overhead"] = _schema_object(
        {
            "ready_to_consumer_seconds": number_non_negative,
            "consumer_to_tree_empty_seconds": number_non_negative,
            "envelope_records": positive,
        }
    )
    short_summary = _schema_object(
        {
            "records": {"const": 0},
            "guard_classification": {"enum": list(CLASSIFICATIONS)},
            "guard_reason": path,
        }
    )
    worker_success_or_consumer_error = _schema_object(
        {
            "schema_version": {"const": "nikodym.readiness.h9r.worker-result.v1"},
            "attempt_id": {"$ref": "#/$defs/sha256"},
            "status": {"enum": ["ok", "error"]},
            "consumer_returncode_signed": {"type": "integer"},
            "consumer_returncode_unsigned": {
                "type": "integer",
                "minimum": 0,
                "maximum": 4_294_967_295,
            },
            "error": {"type": ["string", "null"]},
        }
    )
    worker_internal_error = _schema_object(
        {
            "schema_version": {"const": "nikodym.readiness.h9r.worker-result.v1"},
            "attempt_id": {"$ref": "#/$defs/sha256"},
            "status": {"const": "error"},
            "error_type": path,
            "error": {"type": "string"},
            "traceback": {"type": "string"},
        }
    )
    harness_python = _schema_object(
        {
            "path": path,
            "bytes": non_negative,
            "sha256": {"$ref": "#/$defs/sha256"},
        }
    )
    harness_import_roots = [
        _schema_object(
            {
                "name": {"const": name},
                "kind": {"const": kind},
                "path": path,
                "files": positive,
                "logical_bytes": non_negative,
                "tree_sha256": {"$ref": "#/$defs/sha256"},
            }
        )
        for name, kind in sorted(_HARNESS_IMPORT_ROOT_KINDS.items())
    ]
    harness_runtime = _schema_object(
        {
            "python_executable": harness_python,
            "python_version": path,
            "implementation": path,
            "import_roots": {
                "type": "array",
                "minItems": len(_HARNESS_IMPORT_ROOT_KINDS),
                "maxItems": len(_HARNESS_IMPORT_ROOT_KINDS),
                "uniqueItems": True,
                "prefixItems": harness_import_roots,
                "items": False,
            },
        }
    )
    return {
        "sha256": sha,
        "unit": unit,
        "file_identity": file_identity,
        "fixture_file": fixture_file,
        "group_affinity": group_affinity,
        "job_limits": job_limits,
        "root_census": root_census,
        "root_census_map": root_census_map,
        "chunk": chunk,
        "output_artifact": output_artifact,
        "output_manifest": output_manifest,
        "inventory_entry": inventory_entry,
        "boundary_event": boundary_event,
        "sidecar": sidecar,
        "job_accounting": job_accounting,
        "external_accounting": external_accounting,
        "external_census": external_census,
        "full_summary": full_summary,
        "short_summary": short_summary,
        "worker_success_or_consumer_error": worker_success_or_consumer_error,
        "worker_internal_error": worker_internal_error,
        "harness_runtime": harness_runtime,
        "dimensions": _schema_object(
            {name: {"type": ["integer", "string"], "minimum": 0} for name in dimension_names},
            required=(),
            min_properties=1,
        ),
        "expected_counts": _schema_object(
            {name: non_negative for name in output_identities},
            required=(),
            min_properties=1,
        ),
        "document_sha256": _schema_object(
            {},
            required=(),
            pattern_properties={"^.+$": {"$ref": "#/$defs/sha256"}},
            min_properties=1,
        ),
        "document_paths": _schema_object(
            {}, required=(), pattern_properties={"^.+$": path}, min_properties=1
        ),
        "pool_environment": _schema_object(
            {name: {"type": ["string", "null"]} for name in pool_names}
        ),
    }


def preflight_rejection_json_schema() -> dict[str, Any]:
    """Expone el schema cerrado de un rechazo anterior a cualquier worker/START."""
    path = {"type": "string", "minLength": 1}
    sha = _schema_sha256()
    source_identity = _schema_object(
        {
            "path": path,
            "present": {"type": "boolean"},
            "safe_regular_file": {"type": "boolean"},
            "rejection": {
                "enum": [
                    None,
                    "absent",
                    "symlink_or_reparse_point",
                    "not_regular_file",
                    "multiple_hardlinks",
                ]
            },
            "bytes": {"type": ["integer", "null"], "minimum": 0},
            "sha256": {"anyOf": [sha, {"type": "null"}]},
        }
    )
    source_identity["oneOf"] = [
        {
            "properties": {
                "present": {"const": True},
                "safe_regular_file": {"const": True},
                "rejection": {"const": None},
                "bytes": {"type": "integer", "minimum": 0},
                "sha256": sha,
            }
        },
        {
            "properties": {
                "present": {"const": False},
                "safe_regular_file": {"const": False},
                "rejection": {"const": "absent"},
                "bytes": {"const": None},
                "sha256": {"const": None},
            }
        },
        {
            "properties": {
                "present": {"const": True},
                "safe_regular_file": {"const": False},
                "rejection": {
                    "enum": [
                        "symlink_or_reparse_point",
                        "not_regular_file",
                        "multiple_hardlinks",
                    ]
                },
                "bytes": {"const": None},
                "sha256": {"const": None},
            }
        },
    ]
    base_sources = (
        "unit",
        "authority",
        "authorization_text",
        "trusted_authority_public_key",
        "candidate_manifest",
        "fixture_manifest",
        "config",
        "schedule",
        "prior_evidence_paths",
    )
    document_paths = _schema_object(
        {},
        required=(),
        pattern_properties={"^.+$": path},
        min_properties=1,
    )
    source_identities = _schema_object(
        {name: source_identity for name in base_sources},
        pattern_properties={"^document:.+$": source_identity},
    )
    string_array = {
        "type": "array",
        "uniqueItems": True,
        "items": path,
    }
    schema = _schema_object(
        {
            "schema_version": {"const": PREFLIGHT_REJECTION_SCHEMA_VERSION},
            "phase": {"const": "preflight"},
            "identity": _schema_object(
                {
                    "unit": {"anyOf": [{"$ref": "#/$defs/unit"}, {"type": "null"}]},
                    "attempt_id": {"anyOf": [sha, {"type": "null"}]},
                    "evidence_path": path,
                    "wall_time_finished_utc": path,
                }
            ),
            "launch_sources": _schema_object(
                {
                    "unit_path": path,
                    "authority_path": path,
                    "authorization_text_path": path,
                    "trusted_authority_public_key_path": path,
                    "candidate_manifest_path": path,
                    "fixture_manifest_path": path,
                    "config_path": path,
                    "schedule_path": path,
                    "prior_evidence_paths_path": path,
                    "document_paths": document_paths,
                    "workdir": path,
                }
            ),
            "observed": _schema_object(
                {
                    "source_identities": source_identities,
                    "workdir_state": _schema_object(
                        {
                            "path": path,
                            "existed_before": {"type": "boolean"},
                            "exists_after": {"type": "boolean"},
                            "entries_before": string_array,
                            "entries_after": string_array,
                        }
                    ),
                }
            ),
            "termination": _schema_object(
                {
                    "classification": {"const": "preflight_rejected"},
                    "start_count": {"const": 0},
                    "ready_count": {"const": 0},
                    "worker_spawned": {"const": False},
                    "cleanup_complete": {"type": "boolean"},
                    "workdir_removed": {"type": "boolean"},
                }
            ),
            "gates": _schema_object(
                {
                    "no_start": {"const": True},
                    "no_worker": {"const": True},
                    "evidence_atomic": {"const": True},
                }
            ),
            "reasons": {
                "type": "array",
                "minItems": 1,
                "items": path,
            },
        }
    )
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": PREFLIGHT_REJECTION_SCHEMA_VERSION,
        **schema,
        "$defs": _attempt_schema_defs(),
    }


def pre_start_failure_json_schema(*, allow_harness_test_authority: bool = False) -> dict[str, Any]:
    """Expone el terminal reservado anterior a START; el scope test-only es opt-in."""
    path = {"type": "string", "minLength": 1}
    non_negative = {"type": "integer", "minimum": 0}
    sha = {"$ref": "#/$defs/sha256"}
    source_identity = _schema_object(
        {
            "path": path,
            "present": {"type": "boolean"},
            "safe_regular_file": {"type": "boolean"},
            "rejection": {
                "type": ["string", "null"],
                "enum": [
                    "absent",
                    "symlink_or_reparse_point",
                    "not_regular_file",
                    "multiple_hardlinks",
                    None,
                ],
            },
            "bytes": {"type": ["integer", "null"], "minimum": 0},
            "sha256": {"anyOf": [sha, {"type": "null"}]},
        }
    )
    absent_source_identity = _schema_object(
        {
            "path": path,
            "present": {"const": False},
            "safe_regular_file": {"const": False},
            "rejection": {"const": "absent"},
            "bytes": {"type": "null"},
            "sha256": {"type": "null"},
        }
    )
    snapshot_identity = _schema_object({"path": path, "bytes": non_negative, "sha256": sha})
    causal_source = _schema_object(
        {
            "snapshot": {"anyOf": [snapshot_identity, {"type": "null"}]},
            "observed": source_identity,
            "matches_snapshot": {"type": "boolean"},
        }
    )
    authority = _schema_object(
        {
            "schema_version": {"const": AUTHORIZATION_SCHEMA_VERSION},
            "scope": {
                "enum": (
                    ["calibration-start", "harness-test-only"]
                    if allow_harness_test_authority
                    else ["calibration-start"]
                )
            },
            "start_authorized": {"type": "boolean"},
            "authorization_id": sha,
            "authorization_consumption_path_sha256": sha,
            "authorized_unit": {"$ref": "#/$defs/unit"},
            "attempt_id": sha,
            "authorization_text_sha256": sha,
            "document_sha256": {"$ref": "#/$defs/document_sha256"},
            "tooling_sha256": sha,
            "schedule_sha256": sha,
            "schedule_position": non_negative,
            "signer_public_key_sha256": sha,
            "signature_ed25519": _schema_ed25519_signature(),
        }
    )
    authority["allOf"] = [
        {
            "if": {"properties": {"scope": {"const": "calibration-start"}}},
            "then": {"properties": {"start_authorized": {"const": True}}},
            "else": {"properties": {"start_authorized": {"const": False}}},
        }
    ]
    reservation = _schema_object(
        {
            "authorization_id": sha,
            "authorization_consumption_path_sha256": sha,
            "state": {"enum": ["absent", "reserved", "consumed"]},
            "consumed_at_utc": {"type": ["string", "null"], "format": "date-time"},
            "attempt_id": sha,
            "authority_sha256": sha,
            "receipt": source_identity,
        }
    )
    reservation["allOf"] = [
        {
            "if": {"properties": {"state": {"const": "absent"}}},
            "then": {
                "properties": {
                    "receipt": {
                        "properties": {
                            "present": {"const": False},
                            "safe_regular_file": {"const": False},
                            "rejection": {"const": "absent"},
                            "bytes": {"type": "null"},
                            "sha256": {"type": "null"},
                        }
                    }
                }
            },
            "else": {
                "properties": {
                    "consumed_at_utc": {
                        "type": ["string", "null"],
                        "format": "date-time",
                    },
                    "receipt": {
                        "properties": {
                            "present": {"const": True},
                            "safe_regular_file": {"const": True},
                            "rejection": {"type": "null"},
                            "bytes": non_negative,
                            "sha256": sha,
                        }
                    },
                },
                "allOf": [
                    {
                        "if": {"properties": {"state": {"const": "reserved"}}},
                        "then": {"properties": {"consumed_at_utc": {"type": "null"}}},
                        "else": {"properties": {"consumed_at_utc": {"type": "string"}}},
                    }
                ],
            },
        }
    ]
    sidecar_names = ATTEMPT_SIDECAR_NAMES
    sidecars = {
        "type": "array",
        "minItems": len(ATTEMPT_SIDECAR_SPECS),
        "maxItems": len(ATTEMPT_SIDECAR_SPECS),
        "prefixItems": [
            _schema_object({"name": {"const": name}, "identity": source_identity})
            for name in sidecar_names
        ],
        "items": False,
    }
    unexpected_start_quarantine = _schema_object(
        {
            "original_snapshot": snapshot_identity,
            "quarantined": _schema_object(
                {
                    "path": path,
                    "present": {"const": True},
                    "safe_regular_file": {"const": True},
                    "rejection": {"type": "null"},
                    "bytes": non_negative,
                    "sha256": sha,
                }
            ),
            "moved_atomically": {"const": True},
            "worker_created": {"type": "boolean"},
            "authorization_gate": absent_source_identity,
            "role_claims": _schema_object(
                {role: absent_source_identity for role in INTERNAL_AUTHORIZATION_ROLES}
            ),
        }
    )
    cleanup = _schema_object(
        {
            "worker_tree_empty": {"type": "boolean"},
            "client_tree_empty": {"type": "boolean"},
            "cleanup_complete": {"type": "boolean"},
            "job_accounting": {"anyOf": [{"$ref": "#/$defs/job_accounting"}, {"type": "null"}]},
            "client_accounting": {
                "anyOf": [{"$ref": "#/$defs/external_accounting"}, {"type": "null"}]
            },
            "errors": {"type": "array", "items": path},
        }
    )
    schema = _schema_object(
        {
            "schema_version": {"const": PRE_START_FAILURE_SCHEMA_VERSION},
            "phase": {"const": "pre-start-terminal"},
            "identity": _schema_object(
                {
                    "attempt_id": sha,
                    "unit": {"$ref": "#/$defs/unit"},
                    "evidence_path": path,
                    "wall_time_finished_utc": {"type": "string", "format": "date-time"},
                }
            ),
            "authority": authority,
            "authorization_reservation": reservation,
            "cause": _schema_object(
                {
                    "classification": {"enum": list(PRE_START_FAILURE_CLASSIFICATIONS)},
                    "error_type": path,
                    "message": path,
                    "traceback_sha256": sha,
                }
            ),
            "cleanup": cleanup,
            "observed": _schema_object(
                {
                    "causal_sources": _schema_object(
                        {
                            "authority": causal_source,
                            "authorization_consumption": causal_source,
                            "start": _schema_object(
                                {
                                    "snapshot": {"type": "null"},
                                    "observed": absent_source_identity,
                                    "matches_snapshot": {"const": False},
                                }
                            ),
                        }
                    ),
                    "handshake": _schema_object(
                        {
                            "boot": source_identity,
                            "limits_applied": source_identity,
                            "ready": source_identity,
                            "start": absent_source_identity,
                        }
                    ),
                    "sidecars": sidecars,
                    "unexpected_start_quarantine": {
                        "anyOf": [unexpected_start_quarantine, {"type": "null"}]
                    },
                }
            ),
            "gates": _schema_object(
                {
                    "start_observed": {"const": False},
                    "workload_started": {"const": False},
                    "authorization_reserved": {"type": "boolean"},
                    "evidence_atomic": {"const": True},
                }
            ),
            "result": _schema_object(
                {
                    "classification": {"enum": list(PRE_START_FAILURE_CLASSIFICATIONS)},
                    "statistically_eligible": {"const": False},
                }
            ),
        }
    )
    schema["allOf"] = [
        {
            "if": {
                "properties": {
                    "authorization_reservation": {"properties": {"state": {"const": "reserved"}}}
                }
            },
            "then": {
                "properties": {"gates": {"properties": {"authorization_reserved": {"const": True}}}}
            },
            "else": {
                "properties": {
                    "gates": {"properties": {"authorization_reserved": {"const": False}}}
                }
            },
        },
        {
            "if": {
                "properties": {
                    "observed": {
                        "properties": {"unexpected_start_quarantine": {"not": {"type": "null"}}}
                    }
                }
            },
            "then": {
                "properties": {
                    "cause": {
                        "properties": {
                            "classification": {"enum": ["invariant_failure", "evidence_incomplete"]}
                        }
                    },
                    "result": {
                        "properties": {
                            "classification": {"enum": ["invariant_failure", "evidence_incomplete"]}
                        }
                    },
                }
            },
        },
    ]
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": PRE_START_FAILURE_SCHEMA_VERSION,
        **schema,
        "$defs": _attempt_schema_defs(),
    }


def post_start_failure_json_schema(*, allow_harness_test_authority: bool = False) -> dict[str, Any]:
    """Expone el terminal post-START cerrado; el scope test-only es opt-in."""
    attempt_schema = attempt_json_schema()
    attempt_properties = cast(dict[str, Any], attempt_schema["properties"])
    path = {"type": "string", "minLength": 1}
    non_negative = {"type": "integer", "minimum": 0}
    sha = {"$ref": "#/$defs/sha256"}
    source_identity = _schema_object(
        {
            "path": path,
            "present": {"type": "boolean"},
            "safe_regular_file": {"type": "boolean"},
            "rejection": {
                "type": ["string", "null"],
                "enum": [
                    "absent",
                    "symlink_or_reparse_point",
                    "not_regular_file",
                    "multiple_hardlinks",
                    None,
                ],
            },
            "bytes": {"type": ["integer", "null"], "minimum": 0},
            "sha256": {"anyOf": [sha, {"type": "null"}]},
        }
    )
    snapshot_identity = _schema_object({"path": path, "bytes": non_negative, "sha256": sha})
    causal_source = _schema_object(
        {
            "snapshot": snapshot_identity,
            "observed": source_identity,
            "matches_snapshot": {"type": "boolean"},
        }
    )
    authority = _schema_object(
        {
            "schema_version": {"const": AUTHORIZATION_SCHEMA_VERSION},
            "scope": {
                "enum": (
                    ["calibration-start", "harness-test-only"]
                    if allow_harness_test_authority
                    else ["calibration-start"]
                )
            },
            "start_authorized": {"type": "boolean"},
            "authorization_id": sha,
            "authorization_consumption_path_sha256": sha,
            "authorized_unit": {"$ref": "#/$defs/unit"},
            "attempt_id": sha,
            "authorization_text_sha256": sha,
            "document_sha256": {"$ref": "#/$defs/document_sha256"},
            "tooling_sha256": sha,
            "schedule_sha256": sha,
            "schedule_position": non_negative,
            "signer_public_key_sha256": sha,
            "signature_ed25519": _schema_ed25519_signature(),
        }
    )
    authority["allOf"] = [
        {
            "if": {"properties": {"scope": {"const": "calibration-start"}}},
            "then": {"properties": {"start_authorized": {"const": True}}},
            "else": {"properties": {"start_authorized": {"const": False}}},
        }
    ]
    receipt_identity = _schema_object({"path": path, "bytes": non_negative, "sha256": sha})
    consumption = _schema_object(
        {
            "authorization_id": sha,
            "authorization_consumption_path_sha256": sha,
            "state": {"const": "consumed"},
            "consumed_at_utc": {"type": "string", "format": "date-time"},
            "attempt_id": sha,
            "authority_sha256": sha,
            "receipt": receipt_identity,
        }
    )

    def observation(value_schema: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "oneOf": [
                _schema_object(
                    {
                        "available": {"const": True},
                        "value": value_schema,
                        "error": {"type": "null"},
                    }
                ),
                _schema_object(
                    {
                        "available": {"const": False},
                        "value": {"type": "null"},
                        "error": path,
                    }
                ),
            ]
        }

    sidecar_names = ATTEMPT_SIDECAR_NAMES
    sidecars = {
        "type": "array",
        "minItems": len(ATTEMPT_SIDECAR_SPECS),
        "maxItems": len(ATTEMPT_SIDECAR_SPECS),
        "prefixItems": [
            _schema_object({"name": {"const": name}, "identity": source_identity})
            for name in sidecar_names
        ],
        "items": False,
    }
    cleanup = _schema_object(
        {
            "worker_tree_empty": {"type": "boolean"},
            "client_tree_empty": {"type": "boolean"},
            "cleanup_complete": {"type": "boolean"},
            "job_accounting": {"anyOf": [{"$ref": "#/$defs/job_accounting"}, {"type": "null"}]},
            "client_accounting": {
                "anyOf": [{"$ref": "#/$defs/external_accounting"}, {"type": "null"}]
            },
            "errors": {"type": "array", "items": path},
        }
    )
    schema = _schema_object(
        {
            "schema_version": {"const": POST_START_FAILURE_SCHEMA_VERSION},
            "phase": {"const": "post-start-terminal"},
            "identity": _schema_object(
                {
                    "attempt_id": sha,
                    "unit": {"$ref": "#/$defs/unit"},
                    "evidence_path": path,
                    "wall_time_finished_utc": {"type": "string", "format": "date-time"},
                }
            ),
            "authority": authority,
            "execution_context": _schema_object(
                {
                    "environment": attempt_properties["environment"],
                    "candidate": attempt_properties["candidate"],
                    "tooling": _schema_object(
                        {
                            "protocol_version": {"const": PROTOCOL_VERSION},
                            "manifest_sha256": sha,
                            "document_sha256": {"$ref": "#/$defs/document_sha256"},
                            "harness_runtime": {"$ref": "#/$defs/harness_runtime"},
                            "harness_runtime_snapshot_sha256": sha,
                        }
                    ),
                    "limits": _schema_object(
                        {
                            "requested": cast(dict[str, Any], attempt_properties["limits"])[
                                "properties"
                            ]["requested"],
                            "effective": {"$ref": "#/$defs/job_limits"},
                        }
                    ),
                    "schedule": {
                        "type": "object",
                        "minProperties": 6,
                        "additionalProperties": False,
                        "required": [
                            "schema_version",
                            "phase",
                            "permutation_algorithm",
                            "permutation_seed_sha256",
                            "cells",
                            "units",
                        ],
                        "properties": {
                            "schema_version": {"const": SCHEDULE_SCHEMA_VERSION},
                            "phase": {"enum": list(SCHEDULE_PHASE_ATTEMPTS)},
                            "permutation_algorithm": {"const": "sha256-key-sort-v1"},
                            "permutation_seed_sha256": sha,
                            "cells": {
                                "type": "array",
                                "minItems": 1,
                                "uniqueItems": True,
                                "items": _schema_object(
                                    {
                                        name: cast(dict[str, Any], _attempt_schema_defs()["unit"])[
                                            "properties"
                                        ][name]
                                        for name in SCHEDULE_CELL_FIELDS
                                    }
                                ),
                            },
                            "units": {
                                "type": "array",
                                "minItems": 1,
                                "uniqueItems": True,
                                "items": {"$ref": "#/$defs/unit"},
                            },
                            "screening_schedule_sha256": sha,
                            "promoted_screening_attempt_ids": {
                                "type": "array",
                                "minItems": SCREENING_ATTEMPTS,
                                "uniqueItems": True,
                                "items": sha,
                            },
                        },
                        "allOf": [
                            {
                                "if": {"properties": {"phase": {"const": "confirmation"}}},
                                "then": {
                                    "required": [
                                        "schema_version",
                                        "phase",
                                        "permutation_algorithm",
                                        "permutation_seed_sha256",
                                        "cells",
                                        "units",
                                        "screening_schedule_sha256",
                                        "promoted_screening_attempt_ids",
                                    ]
                                },
                                "else": {
                                    "not": {
                                        "anyOf": [
                                            {"required": ["screening_schedule_sha256"]},
                                            {"required": ["promoted_screening_attempt_ids"]},
                                        ]
                                    }
                                },
                            }
                        ],
                    },
                }
            ),
            "authorization_consumption": consumption,
            "start": _schema_object(
                {
                    "protocol_version": {"const": PROTOCOL_VERSION},
                    "authorization_text_sha256": sha,
                    "ready_monotonic_ns": non_negative,
                    "start_monotonic_ns": non_negative,
                    "attempt_id": sha,
                    "path": path,
                    "bytes": non_negative,
                    "sha256": sha,
                }
            ),
            "cause": _schema_object(
                {
                    "stage": {"const": "terminal_publication"},
                    "error_type": path,
                    "message": path,
                    "traceback_sha256": sha,
                }
            ),
            "cleanup": cleanup,
            "observed": _schema_object(
                {
                    "causal_sources": _schema_object(
                        {
                            "authority": causal_source,
                            "authorization_consumption": causal_source,
                            "start": causal_source,
                        }
                    ),
                    "sidecars": sidecars,
                    "output_inventory": observation(
                        {"type": "array", "items": {"$ref": "#/$defs/inventory_entry"}}
                    ),
                    "final_manifest": source_identity,
                    "quarantined_manifest": source_identity,
                    "disk_final": observation({"$ref": "#/$defs/root_census_map"}),
                }
            ),
            "gates": _schema_object(
                {
                    "start_observed": {"const": True},
                    "authorization_consumed": {"const": True},
                    "evidence_atomic": {"const": True},
                }
            ),
            "result": _schema_object(
                {
                    "classification": {"const": "evidence_incomplete"},
                    "statistically_eligible": {"const": False},
                }
            ),
        }
    )
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": POST_START_FAILURE_SCHEMA_VERSION,
        **schema,
        "$defs": _attempt_schema_defs(),
    }


def internal_authorization_precommit_json_schema() -> dict[str, Any]:
    """Expone la reserva causal previa a receipt/START y cerrada por rol."""
    sha = _schema_sha256()
    role_hashes = _schema_object(
        {
            "worker": sha,
            "adapter": sha,
            "candidate": sha,
            "ui-client": {"anyOf": [sha, {"type": "null"}]},
        }
    )
    schema = _schema_object(
        {
            "schema_version": {"const": INTERNAL_AUTHORIZATION_PRECOMMIT_SCHEMA_VERSION},
            "attempt_id": sha,
            "unit_sha256": sha,
            "authority_sha256": sha,
            "authorization_id": sha,
            "tooling_sha256": sha,
            "schedule_sha256": sha,
            "workdir_path": {"type": "string", "minLength": 1},
            "workdir_sha256": sha,
            "request_payload_sha256": role_hashes,
            "capability_commitment_sha256": role_hashes,
            "supervisor_instance_nonce_sha256": sha,
            "state": {"const": "reserved-pre-start"},
        }
    )
    schema["allOf"] = [
        {
            "if": {
                "properties": {
                    "request_payload_sha256": {"properties": {"ui-client": {"type": "null"}}}
                }
            },
            "then": {
                "properties": {
                    "capability_commitment_sha256": {"properties": {"ui-client": {"type": "null"}}}
                }
            },
            "else": {
                "properties": {"capability_commitment_sha256": {"properties": {"ui-client": sha}}}
            },
        }
    ]
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": INTERNAL_AUTHORIZATION_PRECOMMIT_SCHEMA_VERSION,
        **schema,
    }


def internal_authorization_gate_json_schema(
    *, allow_harness_test_authority: bool = False
) -> dict[str, Any]:
    """Expone el gate material que cada executor reabre antes del consumidor."""
    shared = post_start_failure_json_schema(
        allow_harness_test_authority=allow_harness_test_authority
    )
    shared_properties = cast(dict[str, Any], shared["properties"])
    observed_properties = cast(
        dict[str, Any], cast(dict[str, Any], shared_properties["observed"])["properties"]
    )
    source_identity = observed_properties["final_manifest"]
    path = {"type": "string", "minLength": 1}
    non_negative = {"type": "integer", "minimum": 0}
    sha = {"$ref": "#/$defs/sha256"}
    tooling_file = _schema_object(
        {"relative_path": path, "path": path, "bytes": non_negative, "sha256": sha}
    )
    schema = _schema_object(
        {
            "schema_version": {"const": INTERNAL_AUTHORIZATION_GATE_SCHEMA_VERSION},
            "attempt_id": sha,
            "unit": {"$ref": "#/$defs/unit"},
            "authority": shared_properties["authority"],
            "bindings": _schema_object(
                {
                    "workdir_path": path,
                    "workdir_sha256": sha,
                    "worker_request_core_sha256": sha,
                    "adapter_request_sha256": sha,
                    "candidate_request_sha256": sha,
                    "ui_client_request_sha256": {"anyOf": [sha, {"type": "null"}]},
                    "worker_capability_commitment_sha256": sha,
                    "adapter_capability_commitment_sha256": sha,
                    "candidate_capability_commitment_sha256": sha,
                    "ui_client_capability_commitment_sha256": {"anyOf": [sha, {"type": "null"}]},
                }
            ),
            "sources": _schema_object(
                {
                    "authority": source_identity,
                    "authorization_text": source_identity,
                    "trusted_authority_public_key": source_identity,
                    "schedule": source_identity,
                }
            ),
            "tooling": _schema_object(
                {
                    "protocol_version": {"const": PROTOCOL_VERSION},
                    "files": {
                        "type": "array",
                        "minItems": 1,
                        "uniqueItems": True,
                        "items": tooling_file,
                    },
                    "harness_runtime": {"$ref": "#/$defs/harness_runtime"},
                    "manifest_sha256": sha,
                    "document_sha256": {"$ref": "#/$defs/document_sha256"},
                    "document_paths": {"$ref": "#/$defs/document_paths"},
                }
            ),
            "internal_authorization_precommit": _schema_object(
                {"path": path, "bytes": non_negative, "sha256": sha}
            ),
            "supervisor_instance_nonce": _schema_sha256(),
            "authorization_consumption": shared_properties["authorization_consumption"],
            "start": shared_properties["start"],
        }
    )
    schema["allOf"] = [
        {
            "if": {
                "properties": {
                    "bindings": {"properties": {"ui_client_request_sha256": {"type": "null"}}}
                }
            },
            "then": {
                "properties": {
                    "bindings": {
                        "properties": {"ui_client_capability_commitment_sha256": {"type": "null"}}
                    }
                }
            },
            "else": {
                "properties": {
                    "bindings": {"properties": {"ui_client_capability_commitment_sha256": sha}}
                }
            },
        }
    ]
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": INTERNAL_AUTHORIZATION_GATE_SCHEMA_VERSION,
        **schema,
        "$defs": shared["$defs"],
    }


def internal_authorization_release_json_schema() -> dict[str, Any]:
    """Expone reserva/claim one-shot ligado al gate, rol y request exactos."""
    sha = _schema_sha256()
    schema = _schema_object(
        {
            "schema_version": {"const": INTERNAL_AUTHORIZATION_RELEASE_SCHEMA_VERSION},
            "precommit_sha256": sha,
            "authority_sha256": sha,
            "authorization_id": sha,
            "schedule_sha256": sha,
            "attempt_id": sha,
            "unit_sha256": sha,
            "tooling_sha256": sha,
            "role": {"enum": list(INTERNAL_AUTHORIZATION_ROLES)},
            "request_payload_sha256": sha,
            "capability_commitment_sha256": sha,
            "gate_sha256": {"anyOf": [sha, {"type": "null"}]},
            "authorization_consumption_sha256": {"anyOf": [sha, {"type": "null"}]},
            "start_sha256": {"anyOf": [sha, {"type": "null"}]},
            "state": {"enum": ["reserved-pre-start", "consumed"]},
            "claimed_at_utc": {"type": ["string", "null"], "format": "date-time"},
        }
    )
    schema["allOf"] = [
        {
            "if": {"properties": {"state": {"const": "reserved-pre-start"}}},
            "then": {
                "properties": {
                    "gate_sha256": {"type": "null"},
                    "authorization_consumption_sha256": {"type": "null"},
                    "start_sha256": {"type": "null"},
                    "claimed_at_utc": {"type": "null"},
                }
            },
            "else": {
                "properties": {
                    "gate_sha256": sha,
                    "authorization_consumption_sha256": sha,
                    "start_sha256": sha,
                    "claimed_at_utc": {"type": "string", "format": "date-time"},
                }
            },
        }
    ]
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": INTERNAL_AUTHORIZATION_RELEASE_SCHEMA_VERSION,
        **schema,
    }


def attempt_json_schema() -> dict[str, Any]:
    """Expone el schema completo y recursivamente cerrado del intento H9R."""
    path = {"type": "string", "minLength": 1}
    non_negative = {"type": "integer", "minimum": 0}
    positive_number = {"type": "number", "exclusiveMinimum": 0}
    output_identities = sorted(
        {identity for spec in FLOW_SPECS for identity in spec.expected_output_identities}
    )
    candidate = _schema_object(
        {
            "manifest_sha256": {"$ref": "#/$defs/sha256"},
            "manifest_root": path,
            "source_sha": _schema_git_sha(),
            "wheel": {"$ref": "#/$defs/file_identity"},
            "sdist": {"$ref": "#/$defs/file_identity"},
            "lock": {"$ref": "#/$defs/file_identity"},
            "runtime": _schema_object(
                {
                    "python_executable": {"$ref": "#/$defs/file_identity"},
                    "environment": {"$ref": "#/$defs/file_identity"},
                    "installed_tree": _schema_object(
                        {
                            "relative_path": path,
                            "files": non_negative,
                            "logical_bytes": non_negative,
                            "sha256": {"$ref": "#/$defs/sha256"},
                            "path": path,
                        }
                    ),
                    "provenance": _schema_object(
                        {
                            "probe_schema_version": {
                                "const": "nikodym.readiness.h9r.runtime-provenance.v1"
                            },
                            "isolation_flags": {"const": ["-I", "-B", "-S"]},
                            "no_site": {"const": True},
                            "distribution": {"const": "nikodym"},
                            "version": path,
                            "distribution_root": path,
                            "dist_info_path": path,
                            "metadata_sha256": {"$ref": "#/$defs/sha256"},
                            "record_sha256": {"$ref": "#/$defs/sha256"},
                            "record_entries": {"type": "integer", "minimum": 1},
                            "imported_package_path": path,
                            "imported_package_sha256": {"$ref": "#/$defs/sha256"},
                            "installed_tree_sha256": {"$ref": "#/$defs/sha256"},
                            "wheel_sha256": {"$ref": "#/$defs/sha256"},
                            "lock_sha256": {"$ref": "#/$defs/sha256"},
                            "probe_payload_sha256": {"$ref": "#/$defs/sha256"},
                        }
                    ),
                }
            ),
        }
    )
    tooling_file = _schema_object(
        {
            "relative_path": path,
            "bytes": non_negative,
            "sha256": {"$ref": "#/$defs/sha256"},
        }
    )
    runtime_descriptor_identity = _schema_object(
        {
            "path": path,
            "bytes": non_negative,
            "sha256": {"$ref": "#/$defs/sha256"},
        }
    )

    def launch_source(identity_kind: str) -> dict[str, Any]:
        return _schema_object(
            {
                "path": path,
                "identity_kind": {"const": identity_kind},
                "sha256": {"$ref": "#/$defs/sha256"},
            }
        )

    tooling = _schema_object(
        {
            "protocol_version": {"const": PROTOCOL_VERSION},
            "files": {
                "type": "array",
                "minItems": 1,
                "uniqueItems": True,
                "items": tooling_file,
            },
            "harness_runtime": {"$ref": "#/$defs/harness_runtime"},
            "manifest_sha256": {"$ref": "#/$defs/sha256"},
            "document_sha256": {"$ref": "#/$defs/document_sha256"},
            "document_paths": {"$ref": "#/$defs/document_paths"},
            "launch_sources": _schema_object(
                {
                    "authority": launch_source("canonical_json_sha256"),
                    "authorization_text": launch_source("raw_file_sha256"),
                    "candidate_manifest": launch_source("canonical_json_sha256"),
                    "fixture_manifest": launch_source("canonical_json_sha256"),
                    "config": launch_source("canonical_json_sha256"),
                    "schedule": launch_source("canonical_json_sha256"),
                    "trusted_authority_public_key": launch_source("ed25519_public_key_sha256"),
                }
            ),
            "runtime_descriptors": _schema_object(
                {
                    "adapter_descriptor": runtime_descriptor_identity,
                    "adapter_request": runtime_descriptor_identity,
                    "candidate_request": runtime_descriptor_identity,
                    "harness_runtime_snapshot": runtime_descriptor_identity,
                    "ui_client_request": {"anyOf": [runtime_descriptor_identity, {"type": "null"}]},
                }
            ),
        }
    )
    geometry_derivation = _schema_object(
        {
            "algorithm": {"enum": sorted(set(GEOMETRY_DERIVATION_ALGORITHMS.values()))},
            "value": non_negative,
            "source_sha256": {
                "type": "array",
                "minItems": 1,
                "uniqueItems": True,
                "items": {"$ref": "#/$defs/sha256"},
            },
        }
    )
    geometry_observed = _schema_object(
        {
            "provider": {"const": "harness_reopened_inputs_v1"},
            "primary_input": _schema_object(
                {
                    "relative_path": path,
                    "logical_bytes": non_negative,
                    "sha256": {"$ref": "#/$defs/sha256"},
                }
            ),
            "input_set_sha256": {"$ref": "#/$defs/sha256"},
            "dimensions": {"$ref": "#/$defs/dimensions"},
            "derivations": _schema_object(
                {name: geometry_derivation for name in sorted(GEOMETRY_DERIVATION_ALGORITHMS)},
                required=(),
                min_properties=1,
            ),
        }
    )
    fixture = _schema_object(
        {
            "manifest_sha256": {"$ref": "#/$defs/sha256"},
            "manifest_root": path,
            "flow_id": {"enum": sorted({spec.flow_id for spec in FLOW_SPECS})},
            "flow_step": {"enum": sorted({spec.step for spec in FLOW_SPECS})},
            "geometry_id": {"enum": list(GEOMETRY_IDS)},
            "fixture_schema": {"$ref": "#/$defs/fixture_file"},
            "config": {"$ref": "#/$defs/fixture_file"},
            "config_hash": {"$ref": "#/$defs/sha256"},
            "root_seed": {"const": 20_240_706},
            "sub_seed": non_negative,
            "sub_seed_sha256": {"$ref": "#/$defs/sha256"},
            "generator": _schema_object(
                {
                    "artifact": {"$ref": "#/$defs/fixture_file"},
                    "source_commit": _schema_git_sha(),
                }
            ),
            "dimensions": {"$ref": "#/$defs/dimensions"},
            "geometry_observed": geometry_observed,
            "inputs_root": path,
            "inputs": {
                "type": "array",
                "minItems": 1,
                "uniqueItems": True,
                "items": {"$ref": "#/$defs/fixture_file"},
            },
            "bundle_root": path,
            "bundle": {"anyOf": [{"$ref": "#/$defs/fixture_file"}, {"type": "null"}]},
            "catalog": {"$ref": "#/$defs/fixture_file"},
            "expected": _schema_object(
                {
                    "identities": {
                        "type": "array",
                        "minItems": 1,
                        "uniqueItems": True,
                        "items": {"enum": output_identities},
                    },
                    "counts": {"$ref": "#/$defs/expected_counts"},
                    "golden": {"$ref": "#/$defs/fixture_file"},
                }
            ),
            "contains_customer_data": {"const": False},
            "demo_fixture": {"const": False},
        }
    )
    fixture["oneOf"] = [
        {
            "properties": {
                "flow_id": {"const": spec.flow_id},
                "flow_step": {"const": spec.step},
                "geometry_id": {"const": geometry_id},
                "dimensions": _schema_object(
                    {name: {"const": value} for name, value in dimensions.items()}
                ),
                "geometry_observed": {
                    "properties": {
                        "dimensions": _schema_object(
                            {name: {"const": value} for name, value in dimensions.items()}
                        ),
                        "derivations": _schema_object(
                            {
                                name: _schema_object(
                                    {
                                        "algorithm": {
                                            "const": GEOMETRY_DERIVATION_ALGORITHMS[name]
                                        },
                                        "value": {"const": value},
                                        "source_sha256": {
                                            "type": "array",
                                            "minItems": 1,
                                            "uniqueItems": True,
                                            "items": {"$ref": "#/$defs/sha256"},
                                        },
                                    }
                                )
                                for name, value in dimensions.items()
                            }
                        ),
                    },
                    "required": ["dimensions", "derivations"],
                },
                "expected": {
                    "properties": {
                        "identities": {"const": list(spec.expected_output_identities)},
                        "counts": _schema_object(
                            {name: non_negative for name in spec.expected_output_identities}
                        ),
                    },
                    "required": ["identities", "counts"],
                },
            },
            "required": [
                "flow_id",
                "flow_step",
                "geometry_id",
                "dimensions",
                "geometry_observed",
                "expected",
            ],
        }
        for spec in FLOW_SPECS
        for geometry_id, dimensions in spec.geometries.items()
    ]
    topology = _schema_object(
        {
            "active_group_count": {"type": "integer", "minimum": 1},
            "active_processor_count_by_group": {
                "type": "array",
                "minItems": 1,
                "items": {"type": "integer", "minimum": 1},
            },
            "total_active_logical_processors": {"type": "integer", "minimum": 1},
            "primary_group": non_negative,
            "primary_group_affinity_mask": {"type": "integer", "minimum": 1},
        }
    )
    system_memory = _schema_object(
        {
            "nominal_physical_bytes": non_negative,
            "physical_total_bytes": non_negative,
            "physical_visible_bytes": non_negative,
            "physical_available_bytes": non_negative,
            "commit_limit_bytes": non_negative,
            "commit_available_bytes": non_negative,
            "commit_used_bytes": non_negative,
            "memory_load_percent": {"type": "integer", "minimum": 0, "maximum": 100},
            "virtual_total_bytes": non_negative,
            "virtual_available_bytes": non_negative,
        }
    )
    environment = _schema_object(
        {
            "platform": {"const": "win32"},
            "windows_release": path,
            "windows_version": path,
            "machine": path,
            "processor": path,
            "logical_cpus_host": {"type": "integer", "minimum": 1},
            "processor_topology": topology,
            "affinity_before_confinement": _schema_object(
                {
                    "process_mask": {"type": "integer", "minimum": 1},
                    "system_mask": {"type": "integer", "minimum": 1},
                }
            ),
            "system_memory": system_memory,
            "power_scheme": _schema_object(
                {
                    "available": {"const": True},
                    "returncode": {"const": 0},
                    "stdout": path,
                    "stderr": {"type": "string"},
                }
            ),
            "volume": _schema_object(
                {
                    "path": path,
                    "free_bytes": non_negative,
                    "volume_root": path,
                    "volume_name": {"type": "string"},
                    "volume_serial": non_negative,
                    "filesystem": path,
                    "filesystem_flags": non_negative,
                    "maximum_component_length": non_negative,
                    "allocation_unit_bytes": {"type": "integer", "minimum": 1},
                }
            ),
            "native_pool_environment": {"$ref": "#/$defs/pool_environment"},
        }
    )
    authority = _schema_object(
        {
            "schema_version": {"const": AUTHORIZATION_SCHEMA_VERSION},
            "scope": {"const": "calibration-start"},
            "start_authorized": {"const": True},
            "authorization_id": {"$ref": "#/$defs/sha256"},
            "authorization_consumption_path_sha256": {"$ref": "#/$defs/sha256"},
            "authorized_unit": {"$ref": "#/$defs/unit"},
            "attempt_id": {"$ref": "#/$defs/sha256"},
            "authorization_text_sha256": {"$ref": "#/$defs/sha256"},
            "document_sha256": {"$ref": "#/$defs/document_sha256"},
            "tooling_sha256": {"$ref": "#/$defs/sha256"},
            "schedule_sha256": {"$ref": "#/$defs/sha256"},
            "schedule_position": non_negative,
            "signer_public_key_sha256": (
                {"const": CALIBRATION_AUTHORITY_PUBLIC_KEY_SHA256}
                if CALIBRATION_AUTHORITY_PUBLIC_KEY_SHA256 is not None
                else {"not": {}}
            ),
            "signature_ed25519": _schema_ed25519_signature(),
        }
    )
    receipt_identity = _schema_object(
        {
            "path": path,
            "bytes": non_negative,
            "sha256": {"$ref": "#/$defs/sha256"},
        }
    )
    authorization_consumption = _schema_object(
        {
            "authorization_id": {"$ref": "#/$defs/sha256"},
            "authorization_consumption_path_sha256": {"$ref": "#/$defs/sha256"},
            "state": {"const": "consumed"},
            "consumed_at_utc": {"type": "string", "format": "date-time"},
            "attempt_id": {"$ref": "#/$defs/sha256"},
            "authority_sha256": {"$ref": "#/$defs/sha256"},
            "receipt": receipt_identity,
        }
    )
    requested_limits = _schema_object(
        {
            "logical_cpu_count": {"type": "integer", "minimum": 1, "maximum": 4},
            "affinity_mask": {"type": "integer", "minimum": 1},
            "job_memory_commit_limit_bytes": {"enum": list(CAPS.values())},
            "preflight_deadline_seconds": {"const": PREFLIGHT_DEADLINE_SECONDS},
            "handshake_deadline_seconds": {"const": HANDSHAKE_DEADLINE_SECONDS},
            "workload_deadline_seconds": positive_number,
        }
    )
    guards = _schema_object(
        {
            "physical_available_bytes": non_negative,
            "commit_available_bytes": non_negative,
            "allocated_inputs_bundle_bytes": non_negative,
            "disk_free_bytes": non_negative,
            "disk_floor_bytes": non_negative,
            "passed": {"const": True},
        }
    )
    memory_violation = _schema_object(
        {
            "source": {"const": "windows_job_completion_port_and_limit_violation_information"},
            "limit_flags": non_negative,
            "violation_limit_flags": non_negative,
            "job_memory_limit_violated": {"type": "boolean"},
            "hard_limit_message_observed": {"type": "boolean"},
            "violating_pids": {
                "type": "array",
                "items": non_negative,
                "uniqueItems": True,
            },
            "completion_messages": {
                "type": "array",
                "items": _schema_object(
                    {
                        "message_id": non_negative,
                        "completion_key": non_negative,
                        "message_specific_value": non_negative,
                    }
                ),
            },
            "job_memory_bytes_at_violation": non_negative,
            "job_memory_limit_bytes": {"enum": list(CAPS.values())},
        }
    )
    empty_object = _schema_object({}, required=(), max_properties=0)
    properties = {
        "schema_version": {"const": ATTEMPT_SCHEMA_VERSION},
        "identity": _schema_object(
            {
                "attempt_id": {"$ref": "#/$defs/sha256"},
                "unit": {"$ref": "#/$defs/unit"},
                "evidence_path": path,
                "wall_time_finished_utc": {"type": "string", "format": "date-time"},
                "preflight_started_monotonic_ns": non_negative,
                "ready_monotonic_ns": {"type": ["integer", "null"], "minimum": 0},
                "start_monotonic_ns": {"type": ["integer", "null"], "minimum": 0},
                "tree_empty_monotonic_ns": {"type": ["integer", "null"], "minimum": 0},
            }
        ),
        "authority": authority,
        "authorization_consumption": authorization_consumption,
        "candidate": candidate,
        "tooling": tooling,
        "fixture": fixture,
        "environment": environment,
        "limits": _schema_object(
            {
                "requested": requested_limits,
                "effective": {"anyOf": [{"$ref": "#/$defs/job_limits"}, empty_object]},
                "logical_cpu_count_effective": {
                    "type": ["integer", "null"],
                    "minimum": 1,
                    "maximum": 4,
                },
                "job_memory_commit_limit_bytes_effective": {
                    "type": ["integer", "null"],
                    "enum": [*CAPS.values(), None],
                },
                "ready_before_start": {"type": "boolean"},
                "guards": guards,
            }
        ),
        "boundary": _schema_object(
            {
                "provider": {
                    "enum": [
                        "harness_owned_consumer_open_v1",
                        "harness_owned_candidate_http_ingress_v1",
                    ]
                },
                "events": {
                    "type": "array",
                    "uniqueItems": True,
                    "items": {"$ref": "#/$defs/boundary_event"},
                },
                "consumer_sidecar_present": {"type": "boolean"},
            }
        ),
        "resources": _schema_object(
            {
                "job_accounting": {"anyOf": [{"$ref": "#/$defs/job_accounting"}, empty_object]},
                "external_client": _schema_object(
                    {
                        "declared": {"type": "boolean"},
                        "command_sha256": {"anyOf": [{"$ref": "#/$defs/sha256"}, {"type": "null"}]},
                        "accounting": {
                            "anyOf": [
                                {"$ref": "#/$defs/external_accounting"},
                                {"type": "null"},
                            ]
                        },
                        "final_census": {
                            "anyOf": [
                                {"$ref": "#/$defs/external_census"},
                                {"type": "null"},
                            ]
                        },
                    }
                ),
                "memory_limit_violation": {"anyOf": [memory_violation, empty_object]},
                "summary": {
                    "oneOf": [
                        {"$ref": "#/$defs/full_summary"},
                        {"$ref": "#/$defs/short_summary"},
                        empty_object,
                    ]
                },
                "sidecars": {
                    "type": "array",
                    "minItems": len(ATTEMPT_SIDECAR_SPECS),
                    "maxItems": len(ATTEMPT_SIDECAR_SPECS),
                    "uniqueItems": True,
                    "prefixItems": [
                        _schema_object(
                            {
                                "name": {"const": name},
                                "path": path,
                                "format": {"const": sidecar_format},
                                "records": non_negative,
                                "bytes": non_negative,
                                "sha256": {"$ref": "#/$defs/sha256"},
                            }
                        )
                        for name, sidecar_format in ATTEMPT_SIDECAR_SPECS
                    ],
                    "items": False,
                },
                "disk_baseline_volume_free_bytes": non_negative,
                "disk_baseline": {"$ref": "#/$defs/root_census_map"},
                "disk_final": {"$ref": "#/$defs/root_census_map"},
                "disk_footprint": _schema_object(
                    {
                        "allocated_inputs_bundle_bytes": non_negative,
                        "peak_incremental_allocated_bytes": non_negative,
                        "footprint_total_bytes": non_negative,
                    }
                ),
            }
        ),
        "outputs": _schema_object(
            {
                "final_manifest_present": {"type": "boolean"},
                "expected_identities": {
                    "type": "array",
                    "minItems": 1,
                    "uniqueItems": True,
                    "items": {"enum": output_identities},
                },
                "manifest": {"anyOf": [{"$ref": "#/$defs/output_manifest"}, {"type": "null"}]},
                "inventory": {
                    "type": "array",
                    "uniqueItems": True,
                    "items": {"$ref": "#/$defs/inventory_entry"},
                },
                "quarantined_invalid_manifest": {
                    "anyOf": [
                        _schema_object(
                            {
                                "original_path": path,
                                "quarantine_path": path,
                                "sha256": {"$ref": "#/$defs/sha256"},
                            }
                        ),
                        {"type": "null"},
                    ]
                },
            }
        ),
        "termination": _schema_object(
            {
                "returncode_signed": {"type": ["integer", "null"]},
                "returncode_unsigned": {
                    "type": ["integer", "null"],
                    "minimum": 0,
                    "maximum": 4_294_967_295,
                },
                "client_returncode_signed": {"type": ["integer", "null"]},
                "client_returncode_unsigned": {
                    "type": ["integer", "null"],
                    "minimum": 0,
                    "maximum": 4_294_967_295,
                },
                "cleanup_complete": {"type": "boolean"},
                "tree_empty": {"type": "boolean"},
                "client_tree_empty": {"type": "boolean"},
                "trigger_classification": {"enum": ["watchdog_deadline", "cancelled", None]},
                "timed_out": {"type": "boolean"},
                "cancelled": {"type": "boolean"},
                "worker_result": {
                    "oneOf": [
                        {"$ref": "#/$defs/worker_success_or_consumer_error"},
                        {"$ref": "#/$defs/worker_internal_error"},
                        {"type": "null"},
                    ]
                },
            }
        ),
        "gates": _schema_object(
            {
                "authority_exact": {"type": "boolean"},
                "preflight_passed": {"type": "boolean"},
                "limits_effective": {"type": "boolean"},
                "sidecars_reconciled": {"type": "boolean"},
                "disk_reconciled": {"type": "boolean"},
                "output_completeness_bidirectional": {"type": "boolean"},
                "atomic_publication": {"type": "boolean"},
            }
        ),
        "result": _schema_object(
            {
                "classification": {"type": "string", "enum": list(CLASSIFICATIONS)},
                "statistically_eligible": {"type": "boolean"},
                "reasons": {"type": "array", "items": {"type": "string"}},
            }
        ),
    }
    schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": ATTEMPT_SCHEMA_VERSION,
        **_schema_object(properties),
        "$defs": _attempt_schema_defs(),
    }
    schema["properties"]["termination"]["oneOf"] = [
        {
            "properties": {
                "trigger_classification": {"const": "watchdog_deadline"},
                "timed_out": {"const": True},
                "cancelled": {"const": False},
            },
            "required": ["trigger_classification", "timed_out", "cancelled"],
        },
        {
            "properties": {
                "trigger_classification": {"const": "cancelled"},
                "timed_out": {"const": False},
                "cancelled": {"const": True},
            },
            "required": ["trigger_classification", "timed_out", "cancelled"],
        },
        {
            "properties": {
                "trigger_classification": {"type": "null"},
                "timed_out": {"const": False},
                "cancelled": {"const": False},
            },
            "required": ["trigger_classification", "timed_out", "cancelled"],
        },
    ]
    schema["allOf"] = [
        {
            "if": {
                "properties": {
                    "identity": {
                        "properties": {
                            "unit": {
                                "properties": {
                                    "flow_id": {"const": spec.flow_id},
                                    "flow_step": {"const": spec.step},
                                    "geometry_id": {"const": geometry_id},
                                },
                                "required": ["flow_id", "flow_step", "geometry_id"],
                            }
                        },
                        "required": ["unit"],
                    }
                },
                "required": ["identity"],
            },
            "then": {
                "properties": {
                    "fixture": {
                        "properties": {
                            "flow_id": {"const": spec.flow_id},
                            "flow_step": {"const": spec.step},
                            "geometry_id": {"const": geometry_id},
                            "dimensions": _schema_object(
                                {
                                    name: {"const": value}
                                    for name, value in spec.geometries[geometry_id].items()
                                }
                            ),
                        },
                        "required": ["flow_id", "flow_step", "geometry_id", "dimensions"],
                    },
                    "limits": {
                        "properties": {
                            "requested": {
                                "properties": {
                                    "workload_deadline_seconds": {
                                        "const": spec.workload_deadline_seconds
                                    }
                                },
                                "required": ["workload_deadline_seconds"],
                            }
                        },
                        "required": ["requested"],
                    },
                    "boundary": {
                        "properties": {
                            "provider": {
                                "const": (
                                    "harness_owned_candidate_http_ingress_v1"
                                    if spec.flow_id == "F-UI"
                                    else "harness_owned_consumer_open_v1"
                                )
                            }
                        },
                        "required": ["provider"],
                    },
                    "outputs": {
                        "properties": {
                            "expected_identities": {"const": list(spec.expected_output_identities)}
                        },
                        "required": ["expected_identities"],
                    },
                },
                "required": ["fixture", "limits", "boundary", "outputs"],
            },
        }
        for spec in FLOW_SPECS
        for geometry_id in GEOMETRY_IDS
    ]
    schema["allOf"].append(
        {
            "if": {
                "properties": {
                    "result": {
                        "properties": {"classification": {"const": "orphan_detected"}},
                        "required": ["classification"],
                    }
                },
                "required": ["result"],
            },
            "then": {
                "properties": {
                    "termination": {
                        "properties": {"cleanup_complete": {"const": False}},
                        "not": {
                            "properties": {
                                "tree_empty": {"const": True},
                                "client_tree_empty": {"const": True},
                            },
                            "required": ["tree_empty", "client_tree_empty"],
                        },
                    }
                }
            },
            "else": {
                "properties": {
                    "termination": {
                        "properties": {
                            "cleanup_complete": {"const": True},
                            "tree_empty": {"const": True},
                            "client_tree_empty": {"const": True},
                        }
                    }
                }
            },
        }
    )
    for trigger in ("watchdog_deadline", "cancelled"):
        schema["allOf"].extend(
            [
                {
                    "if": {
                        "properties": {
                            "termination": {
                                "properties": {
                                    "trigger_classification": {"const": trigger},
                                    "cleanup_complete": {"const": True},
                                },
                                "required": ["trigger_classification", "cleanup_complete"],
                            }
                        },
                        "required": ["termination"],
                    },
                    "then": {
                        "properties": {
                            "result": {
                                "properties": {"classification": {"const": trigger}},
                                "required": ["classification"],
                            }
                        },
                        "required": ["result"],
                    },
                },
                {
                    "if": {
                        "properties": {
                            "result": {
                                "properties": {"classification": {"const": trigger}},
                                "required": ["classification"],
                            }
                        },
                        "required": ["result"],
                    },
                    "then": {
                        "properties": {
                            "termination": {
                                "properties": {
                                    "trigger_classification": {"const": trigger},
                                    "cleanup_complete": {"const": True},
                                },
                                "required": ["trigger_classification", "cleanup_complete"],
                            }
                        },
                        "required": ["termination"],
                    },
                },
            ]
        )
    schema["allOf"].append(
        {
            "if": {
                "properties": {
                    "result": {
                        "properties": {"classification": {"const": "success"}},
                        "required": ["classification"],
                    }
                },
                "required": ["result"],
            },
            "then": {
                "properties": {
                    "resources": {
                        "properties": {
                            "job_accounting": {
                                "properties": {
                                    "memory_usage_information_supported": {"const": True},
                                    "current_job_memory_commit_bytes": non_negative,
                                },
                                "required": [
                                    "memory_usage_information_supported",
                                    "current_job_memory_commit_bytes",
                                ],
                            }
                        },
                        "required": ["job_accounting"],
                    }
                },
                "required": ["resources"],
            },
        }
    )
    return schema


def aggregate_json_schema() -> dict[str, Any]:
    """Expone el schema completo y recursivamente cerrado del agregado por celda."""
    sha = _schema_sha256()
    non_negative = {"type": "number", "minimum": 0}
    integer_non_negative = {"type": "integer", "minimum": 0}
    cell_identity = _schema_object(
        {
            "candidate_manifest_sha256": sha,
            "flow_id": {"enum": sorted({spec.flow_id for spec in FLOW_SPECS})},
            "flow_step": {"enum": sorted({spec.step for spec in FLOW_SPECS})},
            "fixture_manifest_sha256": sha,
            "config_hash": sha,
            "geometry_id": {"enum": list(GEOMETRY_IDS)},
            "cap_id": {"enum": list(CAPS)},
        }
    )
    cell_identity["oneOf"] = [
        {
            "properties": {
                "flow_id": {"const": spec.flow_id},
                "flow_step": {"const": spec.step},
            },
            "required": ["flow_id", "flow_step"],
        }
        for spec in FLOW_SPECS
    ]
    metrics = _schema_object(
        {
            "wall_seconds": non_negative,
            "peak_job_memory_commit_bytes": non_negative,
            "peak_incremental_allocated_bytes": non_negative,
        }
    )
    terminal_cause = _schema_object(
        {
            "stage": {"const": "terminal_publication"},
            "error_type": {"type": "string", "minLength": 1},
            "message": {"type": "string", "minLength": 1},
            "traceback_sha256": sha,
        }
    )
    attempt = _schema_object(
        {
            "attempt_id": sha,
            "attempt_ordinal": {"type": "integer", "minimum": 1},
            "schedule_sha256": sha,
            "schedule_phase": {"enum": [*SCHEDULE_PHASE_ATTEMPTS, None]},
            "linked_screening_schedule_sha256": {"anyOf": [sha, {"type": "null"}]},
            "schedule_position": integer_non_negative,
            "evidence_sha256": sha,
            "evidence_path": {"type": "string", "minLength": 1},
            "evidence_schema_version": {
                "enum": [ATTEMPT_SCHEMA_VERSION, POST_START_FAILURE_SCHEMA_VERSION]
            },
            "classification": {"type": "string", "enum": list(CLASSIFICATIONS)},
            "execution_environment_sha256": sha,
            "metrics": {"anyOf": [metrics, {"type": "null"}]},
            "terminal_cause": {"anyOf": [terminal_cause, {"type": "null"}]},
        }
    )
    attempt["oneOf"] = [
        {
            "properties": {
                "evidence_schema_version": {"const": ATTEMPT_SCHEMA_VERSION},
                "schedule_phase": {"enum": list(SCHEDULE_PHASE_ATTEMPTS)},
                "execution_environment_sha256": sha,
                "metrics": metrics,
                "terminal_cause": {"type": "null"},
            }
        },
        {
            "properties": {
                "evidence_schema_version": {"const": POST_START_FAILURE_SCHEMA_VERSION},
                "classification": {"const": "evidence_incomplete"},
                "schedule_phase": {"enum": list(SCHEDULE_PHASE_ATTEMPTS)},
                "execution_environment_sha256": sha,
                "metrics": {"type": "null"},
                "terminal_cause": terminal_cause,
            }
        },
    ]
    robust = _schema_object(
        {
            "values": {
                "type": "array",
                "minItems": 1,
                "items": non_negative,
            },
            "count": {"type": "integer", "minimum": 1},
            "minimum": non_negative,
            "median": non_negative,
            "maximum": non_negative,
            "mad_star": non_negative,
            "u": non_negative,
            "relative_mad": {"type": ["number", "null"], "minimum": 0},
            "stable": {"type": "boolean"},
        }
    )
    statistics = _schema_object(
        {
            "wall_seconds": robust,
            "peak_job_memory_commit_bytes": robust,
            "peak_incremental_allocated_bytes": robust,
        },
        required=(),
    )
    digest_array = {
        "type": "array",
        "minItems": 1,
        "uniqueItems": True,
        "items": sha,
    }
    nullable_sha = {"anyOf": [sha, {"type": "null"}]}
    schedules = _schema_object(
        {
            "screening": nullable_sha,
            "confirmation": nullable_sha,
            "bracket_following": nullable_sha,
        }
    )
    schedules["oneOf"] = [
        {
            "properties": {
                "screening": sha,
                "confirmation": {"type": "null"},
                "bracket_following": {"type": "null"},
            }
        },
        {
            "properties": {
                "screening": sha,
                "confirmation": sha,
                "bracket_following": {"type": "null"},
            }
        },
        {
            "properties": {
                "screening": {"type": "null"},
                "confirmation": {"type": "null"},
                "bracket_following": sha,
            }
        },
        {
            "properties": {
                "screening": {"type": "null"},
                "confirmation": {"type": "null"},
                "bracket_following": {"type": "null"},
            }
        },
    ]
    properties = {
        "schema_version": {"const": AGGREGATE_SCHEMA_VERSION},
        "cell_identity": cell_identity,
        "execution_environment_sha256": sha,
        "schedules": schedules,
        "expected_attempt_ids": digest_array,
        "received_attempt_ids": digest_array,
        "attempts": {
            "type": "array",
            "minItems": 1,
            "uniqueItems": True,
            "items": attempt,
        },
        "completeness": _schema_object(
            {
                "missing": {"type": "array", "uniqueItems": True, "items": sha},
                "extra": {"type": "array", "maxItems": 0},
                "duplicates": {"type": "array", "maxItems": 0},
                "order_matches": {"const": True},
                "complete": {"type": "boolean"},
            }
        ),
        "statistics": statistics,
    }
    schema = _schema_object(properties)
    schema["allOf"] = [
        {
            "if": {
                "properties": {
                    "schedules": {
                        "properties": {
                            "screening": {"type": "null"},
                            "confirmation": {"type": "null"},
                            "bracket_following": {"type": "null"},
                        },
                        "required": ["screening", "confirmation", "bracket_following"],
                    }
                },
                "required": ["schedules"],
            },
            "then": {
                "properties": {
                    "attempts": {
                        "contains": {
                            "properties": {
                                "evidence_schema_version": {
                                    "const": POST_START_FAILURE_SCHEMA_VERSION
                                }
                            },
                            "required": ["evidence_schema_version"],
                        },
                        "minContains": 1,
                    }
                }
            },
        }
    ]
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": AGGREGATE_SCHEMA_VERSION,
        **schema,
    }
