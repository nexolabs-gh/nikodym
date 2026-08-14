"""Agregado verificable, protocolo adaptativo y estadística robusta H9R."""

from __future__ import annotations

import math
import os
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, cast

from .artifacts import (
    disk_footprint_summary,
    verify_jsonl_sidecar,
    verify_sidecar,
)
from .contracts import (
    AGGREGATE_SCHEMA_VERSION,
    ATTEMPT_SCHEMA_VERSION,
    CAP_HEADROOM_RATIO,
    CAPS,
    CLASSIFICATIONS,
    CONFIRMATION_ATTEMPTS_TOTAL,
    GIB,
    MIB,
    POST_START_FAILURE_SCHEMA_VERSION,
    SAMPLE_INTERVAL_SECONDS,
    SCREENING_ATTEMPTS,
    ContractError,
    _read_canonical_control_object,
    attempt_id,
    canonical_json_sha256,
    execution_environment_identity_sha256,
    robust_summary,
    validate_attempt_evidence,
    validate_attempt_unit,
    validate_post_start_failure_evidence,
    validate_schedule,
    validate_sha256,
)
from .telemetry import derive_consumer_window_summary, summarize_telemetry_records

CELL_IDENTITY_FIELDS = (
    "candidate_manifest_sha256",
    "flow_id",
    "flow_step",
    "fixture_manifest_sha256",
    "config_hash",
    "geometry_id",
    "cap_id",
)

CAMPAIGN_CONTINUABLE_CLASSIFICATIONS = frozenset({"success", "job_memory_limit"})


def _validate_started_evidence(
    value: Mapping[str, Any],
    *,
    trusted_authority_public_key_path: Path,
    verify_artifacts: bool,
) -> dict[str, Any]:
    """Valida la unión cerrada de evidencias que consumieron START."""
    schema_version = value.get("schema_version")
    if schema_version == ATTEMPT_SCHEMA_VERSION:
        return validate_attempt_evidence(
            value,
            verify_artifacts=verify_artifacts,
            trusted_authority_public_key_path=trusted_authority_public_key_path,
        )
    if schema_version == POST_START_FAILURE_SCHEMA_VERSION:
        return validate_post_start_failure_evidence(
            value,
            verify_artifacts=verify_artifacts,
            trusted_authority_public_key_path=trusted_authority_public_key_path,
        )
    raise ContractError("evidencia de campaña no es attempt ni terminal post-START")


def _reopen_canonical_evidence_path(evidence_path: object) -> dict[str, Any]:
    """Reabre una evidencia sólo tras validar path/ancestros/nlink y JSON canónico."""
    if not isinstance(evidence_path, str) or not evidence_path:
        raise ContractError("evidencia a agregar carece de identity.evidence_path")
    raw_path = Path(evidence_path)
    if not raw_path.is_absolute() or raw_path.name != "attempt.json":
        raise ContractError("identity.evidence_path debe ser absoluto y terminar en attempt.json")
    absolute = Path(os.path.abspath(os.fspath(raw_path)))
    if os.path.normcase(os.fspath(raw_path)) != os.path.normcase(os.fspath(absolute)):
        raise ContractError("identity.evidence_path no es una ruta lexical canónica")
    return _read_canonical_control_object(absolute, context="evidencia fuente del agregado")


def _reopen_bound_attempt_source(value: Mapping[str, Any]) -> dict[str, Any]:
    """Impide que el builder agregue A mientras publique el path de otra evidencia B."""
    identity = value.get("identity")
    if not isinstance(identity, Mapping):
        raise ContractError("evidencia a agregar carece de identity")
    reopened = _reopen_canonical_evidence_path(identity.get("evidence_path"))
    if reopened != dict(value):
        raise ContractError("payload de intento no coincide con identity.evidence_path")
    return reopened


def validate_statistical_progression(
    attempts: Sequence[Mapping[str, Any]], *, phase: str
) -> dict[str, Any]:
    """Valida cardinalidad/ordinales y que confirmación nazca de screening 3/3."""
    if phase not in {"screening", "confirmation"}:
        raise ContractError(f"fase desconocida: {phase}")
    required = SCREENING_ATTEMPTS if phase == "screening" else CONFIRMATION_ATTEMPTS_TOTAL
    if len(attempts) != required:
        raise ContractError(f"{phase} exige exactamente {required} intentos")
    ordinals: list[int] = []
    classifications: list[str] = []
    for index, attempt in enumerate(attempts):
        ordinal = attempt.get("attempt_ordinal")
        classification = attempt.get("classification")
        if isinstance(ordinal, bool) or not isinstance(ordinal, int):
            raise ContractError(f"attempt[{index}].attempt_ordinal no es entero")
        if classification not in CLASSIFICATIONS:
            raise ContractError(f"attempt[{index}].classification fuera del catálogo")
        ordinals.append(ordinal)
        classifications.append(cast(str, classification))
    if ordinals != list(range(1, required + 1)):
        raise ContractError("ordinales de intentos no son exactos/contiguos")
    if (
        phase == "confirmation"
        and classifications[:SCREENING_ATTEMPTS] != ["success"] * SCREENING_ATTEMPTS
    ):
        raise ContractError("confirmación no acredita screening previo 3/3 success")
    return {
        "phase": phase,
        "required_attempts": required,
        "ordinals": ordinals,
        "classifications": classifications,
        "screening_promoted": classifications[:SCREENING_ATTEMPTS]
        == ["success"] * SCREENING_ATTEMPTS,
    }


def _phase_for_attempt_count(count: int) -> str:
    if count == SCREENING_ATTEMPTS:
        return "screening"
    if count == CONFIRMATION_ATTEMPTS_TOTAL:
        return "confirmation"
    raise ContractError(
        f"agregado exige cardinalidad exacta de screening o confirmación: observada={count}"
    )


def _reconcile_schedule_progression(
    attempts: Sequence[Mapping[str, Any]],
) -> dict[str, str | None]:
    """Reconcilia 3 screening o 3+7 acumulativos sin reejecutar ordinales."""
    phase = _phase_for_attempt_count(len(attempts))
    ordinals = [int(attempt["attempt_ordinal"]) for attempt in attempts]
    if ordinals != list(range(1, len(attempts) + 1)):
        raise ContractError("ordinales de intentos no son exactos/contiguos")

    schedules: dict[str, str | None] = {
        "screening": None,
        "confirmation": None,
        "bracket_following": None,
    }
    if phase == "screening":
        schedule_phases = {str(attempt["schedule_phase"]) for attempt in attempts}
        if schedule_phases not in ({"screening"}, {"bracket_following"}):
            raise ContractError("agregado de tres mezcla fases o usa confirmation")
        schedule_phase = next(iter(schedule_phases))
        hashes = {str(attempt["schedule_sha256"]) for attempt in attempts}
        if len(hashes) != 1:
            raise ContractError("los tres intentos no pertenecen a un único schedule")
        if any(attempt["linked_screening_schedule_sha256"] is not None for attempt in attempts):
            raise ContractError("screening/bracket no admite vínculo de confirmación")
        schedules[schedule_phase] = next(iter(hashes))
    else:
        screening = attempts[:SCREENING_ATTEMPTS]
        extension = attempts[SCREENING_ATTEMPTS:]
        if len(extension) != CONFIRMATION_ATTEMPTS_TOTAL - SCREENING_ATTEMPTS:
            raise ContractError("confirmación exige exactamente siete intentos de extensión")
        if any(attempt["schedule_phase"] != "screening" for attempt in screening):
            raise ContractError("ordinales 1..3 no pertenecen al schedule screening")
        if any(attempt["schedule_phase"] != "confirmation" for attempt in extension):
            raise ContractError("ordinales 4..10 no pertenecen al schedule confirmation")
        screening_hashes = {str(attempt["schedule_sha256"]) for attempt in screening}
        confirmation_hashes = {str(attempt["schedule_sha256"]) for attempt in extension}
        if len(screening_hashes) != 1 or len(confirmation_hashes) != 1:
            raise ContractError("cada fase acumulativa exige un único schedule firmado")
        screening_hash = next(iter(screening_hashes))
        confirmation_hash = next(iter(confirmation_hashes))
        if screening_hash == confirmation_hash:
            raise ContractError("screening y extensión deben usar schedules distintos")
        if any(attempt["linked_screening_schedule_sha256"] is not None for attempt in screening):
            raise ContractError("intentos screening no admiten vínculo de confirmación")
        if any(
            attempt["linked_screening_schedule_sha256"] != screening_hash for attempt in extension
        ):
            raise ContractError("extensión no liga exactamente su schedule screening")
        schedules["screening"] = screening_hash
        schedules["confirmation"] = confirmation_hash

    for schedule_phase in ("screening", "confirmation", "bracket_following"):
        positions = [
            int(attempt["schedule_position"])
            for attempt in attempts
            if attempt["schedule_phase"] == schedule_phase
        ]
        if len(set(positions)) != len(positions):
            raise ContractError(f"posiciones duplicadas dentro del schedule {schedule_phase}")
    return schedules


def _validate_terminal_progression(
    attempts: Sequence[Mapping[str, Any]], *, expected_count: int
) -> bool:
    """Acepta sólo un terminal post-START final y un prefijo causal de la fase esperada."""
    terminals = [
        index
        for index, attempt in enumerate(attempts)
        if attempt.get("evidence_schema_version") == POST_START_FAILURE_SCHEMA_VERSION
    ]
    if terminals != [len(attempts) - 1]:
        raise ContractError("terminal post-START debe ser único y cerrar el prefijo recibido")
    ordinals = [attempt.get("attempt_ordinal") for attempt in attempts]
    if ordinals != list(range(1, len(attempts) + 1)):
        raise ContractError("terminal post-START no conserva ordinales contiguos")
    prior = attempts[:-1]
    terminal = attempts[-1]
    if expected_count == CONFIRMATION_ATTEMPTS_TOTAL:
        if len(attempts) < SCREENING_ATTEMPTS + 1:
            raise ContractError("terminal de confirmation exige screening 3/3 ya promovido")
        if any(attempt.get("classification") != "success" for attempt in prior):
            raise ContractError("terminal de confirmation no acredita prefijo success")
        if terminal.get("schedule_phase") != "confirmation":
            raise ContractError("terminal ordinal 4…10 no acredita schedule confirmation")
        screening_hashes = {
            str(attempt["schedule_sha256"])
            for attempt in prior[:SCREENING_ATTEMPTS]
            if attempt.get("schedule_phase") == "screening"
        }
        if len(screening_hashes) != 1 or terminal.get("linked_screening_schedule_sha256") != next(
            iter(screening_hashes)
        ):
            raise ContractError("terminal confirmation no liga screening promovido")
        screening_hash = next(iter(screening_hashes))
        extension = attempts[SCREENING_ATTEMPTS:]
        if any(attempt.get("schedule_phase") != "confirmation" for attempt in extension):
            raise ContractError("prefijo terminal mezcla fases de confirmation")
        if any(
            attempt.get("linked_screening_schedule_sha256") != screening_hash
            for attempt in extension
        ):
            raise ContractError("prefijo terminal confirmation no liga screening promovido")
        if len({str(attempt["schedule_sha256"]) for attempt in extension}) != 1:
            raise ContractError("prefijo terminal mezcla schedules de confirmation")
    elif any(
        attempt.get("classification") not in CAMPAIGN_CONTINUABLE_CLASSIFICATIONS
        for attempt in prior
    ):
        raise ContractError("terminal screening sigue a una terminación que ya detenía campaña")
    elif terminal.get("schedule_phase") not in {"screening", "bracket_following"}:
        raise ContractError("terminal de tres usa una fase de schedule incompatible")
    return True


def _reconcile_terminal_schedules(
    attempts: Sequence[Mapping[str, Any]], *, expected_count: int
) -> dict[str, str | None]:
    """Reconcilia las fases observadas, incluida la fase acreditada por el terminal."""
    schedules: dict[str, str | None] = {
        "screening": None,
        "confirmation": None,
        "bracket_following": None,
    }
    terminal = attempts[-1]
    normal = attempts[:-1]
    for phase in schedules:
        digests = {
            str(attempt["schedule_sha256"])
            for attempt in attempts
            if attempt.get("schedule_phase") == phase
        }
        if len(digests) > 1:
            raise ContractError(f"prefijo terminal mezcla schedules de {phase}")
        if digests:
            schedules[phase] = next(iter(digests))
    if normal and expected_count == SCREENING_ATTEMPTS:
        terminal_phase = str(terminal["schedule_phase"])
        if any(attempt.get("schedule_phase") != terminal_phase for attempt in normal):
            raise ContractError("terminal post-START no pertenece a la fase del prefijo")
    positions_by_schedule: dict[str, list[int]] = {}
    for attempt in attempts:
        positions_by_schedule.setdefault(str(attempt["schedule_sha256"]), []).append(
            int(attempt["schedule_position"])
        )
    if any(len(positions) != len(set(positions)) for positions in positions_by_schedule.values()):
        raise ContractError("prefijo terminal repite posición dentro de un schedule")
    return schedules


def validate_campaign_progress(
    *,
    schedule: Mapping[str, Any],
    current_unit: Mapping[str, Any],
    prior_evidence_paths: Sequence[Path],
    trusted_authority_public_key_path: Path,
) -> dict[str, Any]:
    """Bloquea avance si falta una unidad previa o cualquier rojo no es el cap controlado.

    El schedule no autoriza START: sólo fija la permutación. Cada evidencia previa debe traer su
    propia autoridad humana y pertenecer a la posición exacta. La única terminación roja que permite
    presentar la unidad siguiente es ``job_memory_limit``; todos los demás rojos exigen revisar el
    arnés antes de continuar.
    """
    schedule_sha256, position = validate_schedule(schedule, current_unit)
    phase = str(schedule["phase"])
    promoted_ids = (
        cast(list[str], schedule["promoted_screening_attempt_ids"])
        if phase == "confirmation"
        else []
    )
    required_prior = len(promoted_ids) + position
    if len(prior_evidence_paths) != required_prior:
        raise ContractError(
            "avance de campaña incompleto: "
            f"phase={phase}, required_prior={required_prior}, "
            f"prior_evidence={len(prior_evidence_paths)}"
        )
    raw_units = cast(list[dict[str, Any]], schedule["units"])
    prior: list[dict[str, Any]] = []
    for expected_position, evidence_path in enumerate(prior_evidence_paths):
        evidence = _validate_started_evidence(
            _reopen_canonical_evidence_path(os.fspath(evidence_path)),
            verify_artifacts=True,
            trusted_authority_public_key_path=trusted_authority_public_key_path,
        )
        identity = cast(dict[str, Any], evidence["identity"])
        authority = cast(dict[str, Any], evidence["authority"])
        result = cast(dict[str, Any], evidence["result"])
        identity_unit = cast(dict[str, Any], identity["unit"])
        observed_attempt_id = attempt_id(identity_unit)
        if expected_position < len(promoted_ids):
            if observed_attempt_id != promoted_ids[expected_position]:
                raise ContractError(
                    "evidencia screening promovida no coincide con el attempt_id ligado: "
                    f"position={expected_position}"
                )
            if authority["schedule_sha256"] != schedule["screening_schedule_sha256"]:
                raise ContractError("evidencia promovida no pertenece al schedule screening ligado")
        else:
            extension_position = expected_position - len(promoted_ids)
            expected_unit = raw_units[extension_position]
            if identity_unit != expected_unit:
                raise ContractError(
                    f"evidencia previa {expected_position} no pertenece a su unidad del schedule"
                )
            if (
                authority["schedule_sha256"] != schedule_sha256
                or authority["schedule_position"] != extension_position
            ):
                raise ContractError(
                    f"evidencia previa {expected_position} no pertenece a la permutación firmada"
                )
        classification = str(result["classification"])
        continuable = (
            {"success"} if phase == "confirmation" else CAMPAIGN_CONTINUABLE_CLASSIFICATIONS
        )
        if classification not in continuable:
            raise ContractError(
                "campaña detenida por terminación previa: "
                f"position={expected_position}, classification={classification}"
            )
        if expected_position < len(promoted_ids) and classification != "success":
            raise ContractError("confirmación exige screening promovido 3/3 success")
        prior.append(
            {
                "position": expected_position,
                "attempt_id": observed_attempt_id,
                "evidence_path": str(evidence_path.resolve()),
                "evidence_sha256": canonical_json_sha256(evidence),
                "classification": classification,
            }
        )
    return {
        "schedule_sha256": schedule_sha256,
        "schedule_phase": phase,
        "current_position": position,
        "required_prior": required_prior,
        "prior": prior,
        "advance_allowed": True,
    }


def _post_start_failure_summary(
    evidence: Mapping[str, Any],
    cell: Mapping[str, Any],
    *,
    trusted_authority_public_key_path: Path,
) -> dict[str, Any]:
    """Cuenta un START terminal sin fabricar métricas y liga el entorno preflight."""
    validated = validate_post_start_failure_evidence(
        evidence,
        verify_artifacts=True,
        trusted_authority_public_key_path=trusted_authority_public_key_path,
    )
    identity = cast(dict[str, Any], validated["identity"])
    unit = cast(dict[str, Any], identity["unit"])
    observed_cell = {name: unit[name] for name in CELL_IDENTITY_FIELDS}
    if observed_cell != dict(cell):
        raise ContractError("terminal post-START no pertenece exactamente a cell_identity")
    authority = cast(dict[str, Any], validated["authority"])
    cause = cast(dict[str, Any], validated["cause"])
    execution_context = cast(dict[str, Any], validated["execution_context"])
    schedule = cast(dict[str, Any], execution_context["schedule"])
    schedule_sha256, schedule_position = validate_schedule(schedule, unit)
    if (
        schedule_sha256 != authority["schedule_sha256"]
        or schedule_position != authority["schedule_position"]
    ):
        raise ContractError("terminal post-START no liga schedule/authority/unidad")
    schedule_phase = str(schedule["phase"])
    linked_screening_schedule_sha256 = (
        validate_sha256(
            schedule["screening_schedule_sha256"],
            context="terminal.linked_screening_schedule_sha256",
        )
        if schedule_phase == "confirmation"
        else None
    )
    return {
        "attempt_id": attempt_id(unit),
        "attempt_ordinal": unit["attempt_ordinal"],
        "schedule_sha256": schedule_sha256,
        "schedule_phase": schedule_phase,
        "linked_screening_schedule_sha256": linked_screening_schedule_sha256,
        "schedule_position": schedule_position,
        "evidence_sha256": canonical_json_sha256(validated),
        "evidence_path": str(identity["evidence_path"]),
        "evidence_schema_version": POST_START_FAILURE_SCHEMA_VERSION,
        "classification": "evidence_incomplete",
        "execution_environment_sha256": execution_environment_identity_sha256(execution_context),
        "metrics": None,
        "terminal_cause": dict(cause),
    }


def _summarize_started_evidence(
    evidence: Mapping[str, Any],
    cell: Mapping[str, Any],
    *,
    trusted_authority_public_key_path: Path,
) -> dict[str, Any]:
    schema_version = evidence.get("schema_version")
    if schema_version == ATTEMPT_SCHEMA_VERSION:
        return _attempt_summary(
            evidence,
            cell,
            trusted_authority_public_key_path=trusted_authority_public_key_path,
        )
    if schema_version == POST_START_FAILURE_SCHEMA_VERSION:
        return _post_start_failure_summary(
            evidence,
            cell,
            trusted_authority_public_key_path=trusted_authority_public_key_path,
        )
    # Los summaries directos sólo se usan en tests focales que reemplazan esta función.
    return _attempt_summary(
        evidence,
        cell,
        trusted_authority_public_key_path=trusted_authority_public_key_path,
    )


def _ceil_multiple(value: float, multiple: int) -> int:
    if value < 0 or multiple <= 0:
        raise ContractError("ceil_multiple recibió un valor inválido")
    return int(math.ceil(value / multiple) * multiple)


def _validate_cell_identity(value: Mapping[str, Any]) -> dict[str, Any]:
    if set(value) != set(CELL_IDENTITY_FIELDS):
        raise ContractError("cell_identity no tiene campos exactos")
    normalized_unit = validate_attempt_unit({**value, "attempt_ordinal": 1})
    return {name: normalized_unit[name] for name in CELL_IDENTITY_FIELDS}


def _expected_attempt_ids_for_cell(cell: Mapping[str, Any], *, expected_count: int) -> list[str]:
    """Deriva cada unidad esperada; el caller no puede inventar IDs del tail faltante."""
    _phase_for_attempt_count(expected_count)
    return [
        attempt_id({**cell, "attempt_ordinal": ordinal}) for ordinal in range(1, expected_count + 1)
    ]


def _execution_environment_sha256(validated: Mapping[str, Any]) -> str:
    """Liga intentos a un mismo host/runtime sin incorporar headroom o paths dinámicos."""
    return execution_environment_identity_sha256(validated)


def _attempt_summary(
    evidence: Mapping[str, Any],
    cell: Mapping[str, Any],
    *,
    trusted_authority_public_key_path: Path,
) -> dict[str, Any]:
    validated = validate_attempt_evidence(
        evidence,
        verify_artifacts=True,
        trusted_authority_public_key_path=trusted_authority_public_key_path,
    )
    identity = cast(dict[str, Any], validated["identity"])
    unit = cast(dict[str, Any], identity["unit"])
    observed_cell = {name: unit[name] for name in CELL_IDENTITY_FIELDS}
    if observed_cell != dict(cell):
        raise ContractError("intento no pertenece exactamente a cell_identity")
    resources = cast(dict[str, Any], validated["resources"])
    sidecars = cast(list[dict[str, Any]], resources["sidecars"])
    resources_sidecar: dict[str, Any] | None = None
    for sidecar in sidecars:
        verify_sidecar(sidecar)
        if sidecar.get("name") == "resources":
            if resources_sidecar is not None:
                raise ContractError("evidencia contiene más de un sidecar resources")
            resources_sidecar = sidecar
    if resources_sidecar is None:
        raise ContractError("evidencia carece de sidecar resources")
    resource_records = verify_jsonl_sidecar(resources_sidecar)
    result = cast(dict[str, Any], validated["result"])
    classification = str(result["classification"])
    boundary = cast(dict[str, Any], validated["boundary"])
    raw_events = boundary.get("events")
    if not isinstance(raw_events, list):
        raise ContractError("boundary.events no es lista")

    def event_timestamp(name: str) -> int | None:
        observed = [
            event.get("monotonic_ns")
            for event in raw_events
            if isinstance(event, dict) and event.get("event") == name
        ]
        if len(observed) > 1:
            raise ContractError(f"boundary contiene {name} duplicado")
        if not observed:
            return None
        value = observed[0]
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ContractError(f"boundary.{name}.monotonic_ns inválido")
        return value

    ready_ns = event_timestamp("ready")
    consumer_start_ns = event_timestamp("first_open_or_byte")
    consumer_end_ns = event_timestamp("rename_complete")
    tree_empty_ns = event_timestamp("tree_empty")
    if classification == "success" and (
        isinstance(consumer_start_ns, bool)
        or not isinstance(consumer_start_ns, int)
        or isinstance(consumer_end_ns, bool)
        or not isinstance(consumer_end_ns, int)
        or isinstance(tree_empty_ns, bool)
        or not isinstance(tree_empty_ns, int)
        or consumer_end_ns < consumer_start_ns
    ):
        raise ContractError("success no permite derivar wall first-open/byte→rename")

    if not resource_records:
        raise ContractError("un intento agregable exige muestras crudas de recursos")
    baseline = cast(dict[str, dict[str, Any]], resources["disk_baseline"])
    final_disk = cast(dict[str, dict[str, Any]], resources["disk_final"])
    declared_summary = cast(dict[str, Any], resources["summary"])
    limits = cast(dict[str, Any], validated["limits"])
    effective = limits.get("effective")
    if not isinstance(effective, Mapping) or not effective:
        raise ContractError("muestras crudas carecen de límites efectivos atestiguados")
    affinity_mask = effective.get("affinity_mask")
    processor_group = effective.get("processor_group")
    if (
        isinstance(affinity_mask, bool)
        or not isinstance(affinity_mask, int)
        or affinity_mask <= 0
        or isinstance(processor_group, bool)
        or not isinstance(processor_group, int)
        or processor_group < 0
    ):
        raise ContractError("límites efectivos no permiten reconstruir guardas CPU/grupo")
    baseline_volume_free = resources.get("disk_baseline_volume_free_bytes")
    if (
        isinstance(baseline_volume_free, bool)
        or not isinstance(baseline_volume_free, int)
        or baseline_volume_free < 0
    ):
        raise ContractError("baseline de espacio libre no es entero no negativo")
    # Ningún campo terminal declarado se acepta como entrada: la guarda se deriva de JSONL,
    # baseline de volumen y límites efectivos atestiguados.
    rebuilt_summary = summarize_telemetry_records(
        resource_records,
        baseline_roots=baseline,
        baseline_volume_free_bytes=baseline_volume_free,
        interval_seconds=SAMPLE_INTERVAL_SECONDS,
        expected_affinity_mask=affinity_mask,
        expected_processor_group=processor_group,
    )
    if consumer_start_ns is not None or consumer_end_ns is not None:
        if (
            not isinstance(ready_ns, int)
            or not isinstance(tree_empty_ns, int)
            or not isinstance(consumer_start_ns, int)
            or not isinstance(consumer_end_ns, int)
        ):
            raise ContractError("frontera consumidor parcial no permite reconstruir summary")
        consumer_window, overhead = derive_consumer_window_summary(
            resource_records,
            boundary_events=raw_events,
            ready_monotonic_ns=ready_ns,
            tree_empty_monotonic_ns=tree_empty_ns,
            baseline_roots=baseline,
        )
        rebuilt_summary["consumer_window"] = consumer_window
        rebuilt_summary["overhead"] = overhead
    elif classification == "success":
        raise ContractError("success carece de resources.summary.consumer_window")
    if declared_summary != rebuilt_summary:
        raise ContractError("resources.summary no deriva exactamente del sidecar crudo")
    disk_samples = [
        cast(dict[str, dict[str, Any]], cast(dict[str, Any], record["disk"])["roots"])
        for record in resource_records
        if record.get("record_type") is None
    ]
    # disk_final participa sólo en el footprint: no puede reescribir summary ni guardas.
    rebuilt_footprint = disk_footprint_summary(baseline, [*disk_samples, final_disk])
    if resources["disk_footprint"] != rebuilt_footprint:
        raise ContractError("disk_footprint no deriva exactamente del JSONL y disk_final")
    sampled_peak_job_commit = int(rebuilt_summary.get("peak_job_memory_commit_bytes", 0))
    raw_accounting = resources.get("job_accounting")
    if not isinstance(raw_accounting, Mapping) or not raw_accounting:
        if classification == "success":
            raise ContractError("success carece de job_accounting final autoritativo")
        peak_job_commit = sampled_peak_job_commit
    else:
        final_peak = raw_accounting.get("peak_job_memory_commit_bytes")
        if isinstance(final_peak, bool) or not isinstance(final_peak, int) or final_peak < 0:
            raise ContractError(
                "job_accounting.peak_job_memory_commit_bytes no es entero no negativo"
            )
        if sampled_peak_job_commit > final_peak:
            raise ContractError("peak Job muestreado excede el accounting final autoritativo")
        peak_job_commit = final_peak
    peak_incremental = int(rebuilt_footprint["peak_incremental_allocated_bytes"])

    metrics = {
        "wall_seconds": 0.0
        if "consumer_window" not in rebuilt_summary
        else float(cast(dict[str, Any], rebuilt_summary["consumer_window"])["wall_seconds"]),
        "peak_job_memory_commit_bytes": float(peak_job_commit),
        "peak_incremental_allocated_bytes": float(peak_incremental),
    }
    if any(not math.isfinite(value) or value < 0 for value in metrics.values()):
        raise ContractError("métrica derivada no finita/negativa")
    authority = cast(dict[str, Any], validated["authority"])
    tooling = cast(dict[str, Any], validated["tooling"])
    launch_sources = cast(dict[str, Any], tooling["launch_sources"])
    schedule_source = cast(dict[str, Any], launch_sources["schedule"])
    schedule = _read_canonical_control_object(
        Path(str(schedule_source["path"])), context="attempt.schedule_source"
    )
    schedule_sha256, schedule_position = validate_schedule(schedule, unit)
    if (
        schedule_sha256 != authority["schedule_sha256"]
        or schedule_position != authority["schedule_position"]
    ):
        raise ContractError("schedule reabierto no reconcilia con autoridad/unidad")
    schedule_phase = str(schedule["phase"])
    linked_screening_schedule_sha256 = (
        validate_sha256(
            schedule["screening_schedule_sha256"],
            context="attempt.linked_screening_schedule_sha256",
        )
        if schedule_phase == "confirmation"
        else None
    )
    if schedule_phase == "confirmation":
        promoted = cast(list[str], schedule["promoted_screening_attempt_ids"])
        required_promoted = {
            attempt_id({**cell, "attempt_ordinal": ordinal})
            for ordinal in range(1, SCREENING_ATTEMPTS + 1)
        }
        if not required_promoted.issubset(set(promoted)):
            raise ContractError("schedule confirmation no liga el screening de esta celda")
    return {
        "attempt_id": attempt_id(unit),
        "attempt_ordinal": unit["attempt_ordinal"],
        "schedule_sha256": schedule_sha256,
        "schedule_phase": schedule_phase,
        "linked_screening_schedule_sha256": linked_screening_schedule_sha256,
        "schedule_position": schedule_position,
        "evidence_sha256": canonical_json_sha256(validated),
        "evidence_path": str(identity["evidence_path"]),
        "evidence_schema_version": ATTEMPT_SCHEMA_VERSION,
        "classification": classification,
        "execution_environment_sha256": _execution_environment_sha256(validated),
        "metrics": metrics,
        "terminal_cause": None,
    }


def _assemble_aggregate_from_summaries(
    *,
    cell_identity: Mapping[str, Any],
    expected_attempt_ids: Sequence[str],
    summaries: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Ensambla summaries ya validados; separa tests puros del entrypoint de evidencia."""
    cell = _validate_cell_identity(cell_identity)
    expected_count = len(expected_attempt_ids)
    expected_phase = _phase_for_attempt_count(expected_count)
    derived_expected = _expected_attempt_ids_for_cell(cell, expected_count=expected_count)
    if list(expected_attempt_ids) != derived_expected:
        raise ContractError("expected_attempt_ids no deriva de cell_identity + ordinales exactos")
    if len(set(expected_attempt_ids)) != len(expected_attempt_ids):
        raise ContractError("expected_attempt_ids contiene duplicados")
    for index, expected in enumerate(expected_attempt_ids):
        validate_sha256(expected, context=f"expected_attempt_ids[{index}]")
    normalized = [dict(summary) for summary in summaries]
    summary_fields = {
        "attempt_id",
        "attempt_ordinal",
        "schedule_sha256",
        "schedule_phase",
        "linked_screening_schedule_sha256",
        "schedule_position",
        "evidence_sha256",
        "evidence_path",
        "evidence_schema_version",
        "classification",
        "execution_environment_sha256",
        "metrics",
        "terminal_cause",
    }
    for index, summary in enumerate(normalized):
        if set(summary) != summary_fields:
            raise ContractError(f"summary[{index}] tiene campos faltantes o extra")
    has_terminal = any(
        attempt.get("evidence_schema_version") == POST_START_FAILURE_SCHEMA_VERSION
        for attempt in normalized
    )
    received = [str(attempt["attempt_id"]) for attempt in normalized]
    if len(set(received)) != len(received):
        raise ContractError("received_attempt_ids contiene duplicados")
    missing = list(expected_attempt_ids[len(received) :]) if has_terminal else []
    extra = sorted(set(received) - set(expected_attempt_ids))
    order_matches = received == list(expected_attempt_ids[: len(received)])
    if extra or not order_matches or (not has_terminal and len(received) != expected_count):
        raise ContractError(
            f"completitud de agregado falla: missing={missing!r}, extra={extra!r}, "
            f"order_matches={order_matches}"
        )
    if has_terminal:
        _validate_terminal_progression(normalized, expected_count=expected_count)
        schedules = _reconcile_terminal_schedules(normalized, expected_count=expected_count)
    else:
        validate_statistical_progression(normalized, phase=expected_phase)
        schedules = _reconcile_schedule_progression(normalized)
    environment_hashes = {
        validate_sha256(
            attempt["execution_environment_sha256"],
            context="aggregate.attempt.execution_environment_sha256",
        )
        for attempt in normalized
    }
    if len(environment_hashes) != 1:
        raise ContractError("agregado mezcla hosts/runtime/power/volumen/límites")
    execution_environment_sha256 = next(iter(environment_hashes))
    successes = [attempt for attempt in normalized if attempt["classification"] == "success"]
    statistics: dict[str, Any] = {}
    if successes:
        for metric in (
            "wall_seconds",
            "peak_job_memory_commit_bytes",
            "peak_incremental_allocated_bytes",
        ):
            statistics[metric] = robust_summary(
                [cast(dict[str, float], attempt["metrics"])[metric] for attempt in successes]
            )
    return {
        "schema_version": AGGREGATE_SCHEMA_VERSION,
        "cell_identity": cell,
        "execution_environment_sha256": execution_environment_sha256,
        "schedules": schedules,
        "expected_attempt_ids": list(expected_attempt_ids),
        "received_attempt_ids": received,
        "attempts": normalized,
        "completeness": {
            "missing": missing,
            "extra": [],
            "duplicates": [],
            "order_matches": True,
            "complete": not missing,
        },
        "statistics": statistics,
    }


def build_aggregate(
    *,
    cell_identity: Mapping[str, Any],
    expected_attempt_ids: Sequence[str],
    attempts: Sequence[Mapping[str, Any]],
    trusted_authority_public_key_path: Path,
) -> dict[str, Any]:
    """Agrega sólo evidencias reabiertas, validadas y firmadas ligadas por fase."""
    cell = _validate_cell_identity(cell_identity)
    bound_attempts = [_reopen_bound_attempt_source(attempt) for attempt in attempts]
    summaries = [
        _summarize_started_evidence(
            attempt,
            cell,
            trusted_authority_public_key_path=trusted_authority_public_key_path,
        )
        for attempt in bound_attempts
    ]
    return _assemble_aggregate_from_summaries(
        cell_identity=cell,
        expected_attempt_ids=expected_attempt_ids,
        summaries=summaries,
    )


def validate_aggregate(
    value: Mapping[str, Any], *, trusted_authority_public_key_path: Path
) -> dict[str, Any]:
    """Recalcula cardinalidad, sidecars y estadísticos para impedir evidencia derivada."""
    expected_fields = {
        "schema_version",
        "cell_identity",
        "execution_environment_sha256",
        "schedules",
        "expected_attempt_ids",
        "received_attempt_ids",
        "attempts",
        "completeness",
        "statistics",
    }
    if set(value) != expected_fields:
        raise ContractError("campos de agregado faltantes o extra")
    if value["schema_version"] != AGGREGATE_SCHEMA_VERSION:
        raise ContractError("schema_version de agregado inesperado")
    declared_environment_raw = value["execution_environment_sha256"]
    declared_environment_sha256 = validate_sha256(
        declared_environment_raw, context="aggregate.execution_environment_sha256"
    )
    declared_schedules = value["schedules"]
    if not isinstance(declared_schedules, dict) or set(declared_schedules) != {
        "screening",
        "confirmation",
        "bracket_following",
    }:
        raise ContractError("schedules no tiene campos exactos")
    for phase_name, digest in declared_schedules.items():
        if digest is not None:
            validate_sha256(digest, context=f"aggregate.schedules.{phase_name}")
    expected = value["expected_attempt_ids"]
    received = value["received_attempt_ids"]
    attempts = value["attempts"]
    if (
        not isinstance(expected, list)
        or not isinstance(received, list)
        or not isinstance(attempts, list)
    ):
        raise ContractError("listas de agregado inválidas")
    raw_cell = value["cell_identity"]
    if not isinstance(raw_cell, dict):
        raise ContractError("cell_identity no es objeto")
    cell = _validate_cell_identity(cast(dict[str, Any], raw_cell))
    derived_expected = _expected_attempt_ids_for_cell(cell, expected_count=len(expected))
    if expected != derived_expected:
        raise ContractError("aggregate.expected_attempt_ids no deriva de la celda/ordinales")
    for index, identifier in enumerate(expected):
        validate_sha256(identifier, context=f"aggregate.expected_attempt_ids[{index}]")
    for index, identifier in enumerate(received):
        validate_sha256(identifier, context=f"aggregate.received_attempt_ids[{index}]")
    if len(set(expected)) != len(expected) or len(set(received)) != len(received):
        raise ContractError("expected/received contienen attempt IDs duplicados")
    if len(attempts) != len(received):
        raise ContractError("attempt summaries no reconcilian cardinalidad received")
    # Un agregado publicado contiene summaries; se recalculan desde sus campos cerrados. La
    # construcción inicial, única ruta autorizada, ya reabrió todas las evidencias y sidecars.
    normalized_attempts: list[dict[str, Any]] = []
    required_attempt_fields = {
        "attempt_id",
        "attempt_ordinal",
        "schedule_sha256",
        "schedule_phase",
        "linked_screening_schedule_sha256",
        "schedule_position",
        "evidence_sha256",
        "evidence_path",
        "evidence_schema_version",
        "classification",
        "execution_environment_sha256",
        "metrics",
        "terminal_cause",
    }
    for raw in attempts:
        if not isinstance(raw, dict) or set(raw) != required_attempt_fields:
            raise ContractError("summary de intento no tiene campos exactos")
        for digest_name in (
            "attempt_id",
            "schedule_sha256",
            "evidence_sha256",
        ):
            validate_sha256(raw[digest_name], context=f"aggregate.attempt.{digest_name}")
        evidence_schema = raw["evidence_schema_version"]
        if evidence_schema not in {ATTEMPT_SCHEMA_VERSION, POST_START_FAILURE_SCHEMA_VERSION}:
            raise ContractError("schema de evidencia en summary fuera de la unión cerrada")
        terminal = evidence_schema == POST_START_FAILURE_SCHEMA_VERSION
        if raw["schedule_phase"] not in {
            "screening",
            "confirmation",
            "bracket_following",
            None,
        }:
            raise ContractError("schedule_phase inválida en agregado")
        if raw["schedule_phase"] is None and not terminal:
            raise ContractError("sólo terminal post-START puede omitir schedule_phase")
        linked = raw["linked_screening_schedule_sha256"]
        if linked is not None:
            validate_sha256(linked, context="aggregate.attempt.linked_screening_schedule_sha256")
        for integer_name in ("attempt_ordinal", "schedule_position"):
            integer_value = raw[integer_name]
            minimum = 1 if integer_name == "attempt_ordinal" else 0
            if (
                isinstance(integer_value, bool)
                or not isinstance(integer_value, int)
                or integer_value < minimum
            ):
                raise ContractError(f"aggregate.attempt.{integer_name} inválido")
        if raw["classification"] not in CLASSIFICATIONS:
            raise ContractError("clasificación inválida en agregado")
        metrics = raw["metrics"]
        environment_hash = raw["execution_environment_sha256"]
        terminal_cause = raw["terminal_cause"]
        if terminal:
            if (
                raw["classification"] != "evidence_incomplete"
                or metrics is not None
                or not isinstance(environment_hash, str)
                or not isinstance(terminal_cause, dict)
                or set(terminal_cause) != {"stage", "error_type", "message", "traceback_sha256"}
            ):
                raise ContractError("summary terminal post-START no conserva causa/no-métricas")
            validate_sha256(environment_hash, context="aggregate.terminal.environment")
            validate_sha256(
                terminal_cause["traceback_sha256"], context="aggregate.terminal.traceback_sha256"
            )
            for name in ("stage", "error_type", "message"):
                if not isinstance(terminal_cause[name], str) or not terminal_cause[name]:
                    raise ContractError(f"aggregate.terminal.{name} no es texto")
        else:
            validate_sha256(environment_hash, context="aggregate.attempt.environment")
            if (
                terminal_cause is not None
                or not isinstance(metrics, dict)
                or set(metrics)
                != {
                    "wall_seconds",
                    "peak_job_memory_commit_bytes",
                    "peak_incremental_allocated_bytes",
                }
            ):
                raise ContractError("metrics/causa del intento ordinario no tienen forma exacta")
            if any(
                isinstance(metric, bool)
                or not isinstance(metric, int | float)
                or not math.isfinite(float(metric))
                or float(metric) < 0
                for metric in metrics.values()
            ):
                raise ContractError("métrica de agregado inválida")
        normalized_attempts.append(dict(raw))
    if [row["attempt_id"] for row in normalized_attempts] != received:
        raise ContractError("summaries no coinciden con received_attempt_ids")
    observed_environment_hashes = {
        str(row["execution_environment_sha256"]) for row in normalized_attempts
    }
    if observed_environment_hashes != {declared_environment_sha256}:
        raise ContractError("agregado mezcla identidades estables de entorno")
    has_terminal = any(
        row["evidence_schema_version"] == POST_START_FAILURE_SCHEMA_VERSION
        for row in normalized_attempts
    )
    expected_phase = _phase_for_attempt_count(len(expected))
    if has_terminal:
        if received != expected[: len(received)]:
            raise ContractError("terminal post-START no conserva el prefijo expected/received")
    elif expected != received:
        raise ContractError("expected/received no coinciden exactamente")
    if has_terminal:
        _validate_terminal_progression(normalized_attempts, expected_count=len(expected))
        rebuilt_schedules = _reconcile_terminal_schedules(
            normalized_attempts, expected_count=len(expected)
        )
    else:
        rebuilt_schedules = _reconcile_schedule_progression(normalized_attempts)
    if declared_schedules != rebuilt_schedules:
        raise ContractError("schedules declarados no reconcilian con los intentos")
    for row in normalized_attempts:
        evidence_path = row["evidence_path"]
        if not isinstance(evidence_path, str):
            raise ContractError("evidence_path del agregado no es texto")
        rebuilt = _summarize_started_evidence(
            _reopen_canonical_evidence_path(evidence_path),
            cell,
            trusted_authority_public_key_path=trusted_authority_public_key_path,
        )
        if rebuilt != row:
            raise ContractError("summary no deriva byte-exacto de su evidencia/sidecars")
    if not has_terminal:
        validate_statistical_progression(normalized_attempts, phase=expected_phase)
    successes = [row for row in normalized_attempts if row["classification"] == "success"]
    rebuilt_statistics: dict[str, Any] = {}
    if successes:
        for metric in (
            "wall_seconds",
            "peak_job_memory_commit_bytes",
            "peak_incremental_allocated_bytes",
        ):
            rebuilt_statistics[metric] = robust_summary(
                [float(cast(dict[str, Any], row["metrics"])[metric]) for row in successes]
            )
    expected_missing = list(expected[len(received) :]) if has_terminal else []
    expected_completeness = {
        "missing": expected_missing,
        "extra": [],
        "duplicates": [],
        "order_matches": True,
        "complete": not expected_missing,
    }
    if value["completeness"] != expected_completeness:
        raise ContractError("completitud declarada no coincide con la recalculada")
    if value["statistics"] != rebuilt_statistics:
        raise ContractError("estadística declarada descarta o altera observaciones")
    return dict(value)


def evaluate_cell(
    aggregate: Mapping[str, Any],
    *,
    phase: str,
    cap_id: str,
    trusted_authority_public_key_path: Path,
) -> dict[str, Any]:
    """Evalúa screening/confirmación y headroom del cap como hipótesis."""
    validated = validate_aggregate(
        aggregate, trusted_authority_public_key_path=trusted_authority_public_key_path
    )
    attempts = cast(list[dict[str, Any]], validated["attempts"])
    progression = validate_statistical_progression(attempts, phase=phase)
    required = int(progression["required_attempts"])
    if cap_id not in CAPS or validated["cell_identity"]["cap_id"] != cap_id:
        raise ContractError(f"cap_id desconocido o distinto de la celda: {cap_id}")
    classifications = [str(attempt["classification"]) for attempt in attempts]
    all_success = all(classification == "success" for classification in classifications)
    peak_values = [
        cast(dict[str, float], attempt["metrics"])["peak_job_memory_commit_bytes"]
        for attempt in attempts
        if attempt["classification"] == "success"
    ]
    cap_headroom = bool(
        all_success and peak_values and max(peak_values) <= CAPS[cap_id] * CAP_HEADROOM_RATIO
    )
    stable = bool(
        all_success
        and validated["statistics"]
        and all(
            bool(summary["stable"])
            for summary in cast(dict[str, dict[str, Any]], validated["statistics"]).values()
        )
    )
    return {
        "phase": phase,
        "required_attempts": required,
        "all_success": all_success,
        "cap_headroom_85_percent": cap_headroom,
        "statistics_stable": stable,
        "eligible": bool(all_success and cap_headroom and stable),
        "classifications": classifications,
    }


def evaluate_bracket(
    *,
    previous: Mapping[str, Any],
    candidate: Mapping[str, Any],
    following: Mapping[str, Any],
    trusted_authority_public_key_path: Path,
) -> dict[str, Any]:
    """Exige tres agregados adyacentes: 3/3, 10/10 y rojo controlado 3/3."""
    previous_valid = validate_aggregate(
        previous, trusted_authority_public_key_path=trusted_authority_public_key_path
    )
    candidate_valid = validate_aggregate(
        candidate, trusted_authority_public_key_path=trusted_authority_public_key_path
    )
    following_valid = validate_aggregate(
        following, trusted_authority_public_key_path=trusted_authority_public_key_path
    )
    expected_schedule_shapes = (
        {"screening": True, "confirmation": False, "bracket_following": False},
        {"screening": True, "confirmation": True, "bracket_following": False},
        {"screening": False, "confirmation": False, "bracket_following": True},
    )
    for label, aggregate_value, expected_shape in zip(
        ("G-", "G0", "G+"),
        (previous_valid, candidate_valid, following_valid),
        expected_schedule_shapes,
        strict=True,
    ):
        schedules = cast(dict[str, str | None], aggregate_value["schedules"])
        observed_shape = {name: digest is not None for name, digest in schedules.items()}
        if observed_shape != expected_shape:
            raise ContractError(f"{label} no usa los schedules exactos de su fase de bracket")
    previous_schedules = cast(dict[str, str | None], previous_valid["schedules"])
    candidate_schedules = cast(dict[str, str | None], candidate_valid["schedules"])
    if previous_schedules["screening"] != candidate_schedules["screening"]:
        raise ContractError("G- y G0 no pertenecen al mismo schedule screening")
    environment_hashes = {
        str(aggregate_value["execution_environment_sha256"])
        for aggregate_value in (previous_valid, candidate_valid, following_valid)
    }
    if len(environment_hashes) != 1:
        raise ContractError("bracket mezcla identidades estables de entorno/arnés")
    cells = [
        cast(dict[str, Any], item["cell_identity"])
        for item in (previous_valid, candidate_valid, following_valid)
    ]
    # Fixture y config materializan la geometría; por diseño cambian entre G-/G0/G+. La
    # continuidad de bracket está dada por candidato, frontera consumidora y cap.
    invariant_fields = {
        "candidate_manifest_sha256",
        "flow_id",
        "flow_step",
        "cap_id",
    }
    if any(
        {key: cell[key] for key in invariant_fields}
        != {key: cells[0][key] for key in invariant_fields}
        for cell in cells[1:]
    ):
        raise ContractError("bracket mezcla candidato/flujo/step/cap")
    geometry_order = {"G-": 0, "G0": 1, "G+": 2}
    indices = [geometry_order.get(str(cell["geometry_id"]), -99) for cell in cells]
    if indices[1] - indices[0] != 1 or indices[2] - indices[1] != 1:
        raise ContractError("bracket no usa geometrías adyacentes")
    previous_eval = evaluate_cell(
        previous_valid,
        phase="screening",
        cap_id=str(cells[0]["cap_id"]),
        trusted_authority_public_key_path=trusted_authority_public_key_path,
    )
    candidate_eval = evaluate_cell(
        candidate_valid,
        phase="confirmation",
        cap_id=str(cells[1]["cap_id"]),
        trusted_authority_public_key_path=trusted_authority_public_key_path,
    )
    following_attempts = cast(list[dict[str, Any]], following_valid["attempts"])
    if len(following_attempts) != SCREENING_ATTEMPTS:
        raise ContractError("G siguiente exige exactamente 3 intentos")
    controlled_red = all(
        attempt["classification"] == "job_memory_limit" for attempt in following_attempts
    )
    measured = bool(previous_eval["all_success"] and candidate_eval["eligible"] and controlled_red)
    return {
        "previous_3_of_3_success": previous_eval["all_success"],
        "candidate_10_of_10_success": candidate_eval["all_success"],
        "following_3_of_3_job_memory_limit": controlled_red,
        "bracket_measured": measured,
    }


def derive_hypothesis_candidates(
    *,
    previous: Mapping[str, Any],
    candidate: Mapping[str, Any],
    following: Mapping[str, Any],
    trusted_authority_public_key_path: Path,
) -> dict[str, int]:
    """Deriva hipótesis sólo tras 10/10, headroom y bracket completos."""
    bracket = evaluate_bracket(
        previous=previous,
        candidate=candidate,
        following=following,
        trusted_authority_public_key_path=trusted_authority_public_key_path,
    )
    if bracket["bracket_measured"] is not True:
        raise ContractError("sin bracket 3/3→10/10→3/3 no se derivan hipótesis")
    validated = validate_aggregate(
        candidate, trusted_authority_public_key_path=trusted_authority_public_key_path
    )
    statistics = cast(dict[str, dict[str, Any]], validated["statistics"])
    required = {
        "wall_seconds",
        "peak_job_memory_commit_bytes",
        "peak_incremental_allocated_bytes",
    }
    if set(statistics) != required:
        raise ContractError("faltan estadísticas para derivar hipótesis")
    if not all(bool(statistics[name]["stable"]) for name in required):
        raise ContractError("una celda inestable no deriva hipótesis")
    wall_u = float(statistics["wall_seconds"]["u"])
    memory_u = float(statistics["peak_job_memory_commit_bytes"]["u"])
    disk = statistics["peak_incremental_allocated_bytes"]
    disk_u = float(disk["u"])
    disk_mad = float(disk["mad_star"])
    return {
        "budget_candidate_seconds": _ceil_multiple(1.20 * wall_u, 30),
        "memory_needed_bytes": _ceil_multiple(memory_u / 0.85, 256 * MIB),
        "disk_free_candidate_bytes": _ceil_multiple(
            disk_u + max(0.20 * disk_u, 3.0 * disk_mad) + GIB,
            256 * MIB,
        ),
    }
