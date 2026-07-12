"""Carga y validación de matrices regulatorias CMF versionadas.

El módulo mantiene los parámetros normativos de B-1/B-3 fuera del motor de cálculo: lee el
bundle activo desde datos empaquetados, verifica su hash y construye DTOs Pydantic congelados.
No importa ``pandas`` ni ejecuta cálculos de provisión; esa responsabilidad queda para B15.4.

**Experimental (fuera de la garantía SemVer 1.x).**
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Mapping
from decimal import Decimal, InvalidOperation
from importlib import resources
from typing import Any, Literal, Protocol, cast

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

from nikodym.provisioning.cmf.exceptions import CmfMatrixError

__all__ = [
    "CMF_MATRIX_IDS",
    "CmfMatrixBundle",
    "CmfMatrixConfigLike",
    "CmfMatrixError",
    "CmfMatrixManifest",
    "CmfMatrixRow",
    "load_cmf_matrices",
    "validate_cmf_matrix_bundle",
]

RowStatus = Literal["verified", "pending"]
ManifestStatus = Literal["verified", "pending", "pending_reconciliation", "deprecated"]
SourceStatus = Literal["verified", "referenced", "pending"]

CMF_MATRIX_IDS: tuple[str, ...] = (
    "commercial_individual_performing_v2014",
    "commercial_individual_default_v2014",
    "commercial_group_leasing_v2018",
    "commercial_group_student_v2018",
    "commercial_group_generic_factoring_v2020",
    "commercial_group_guarantee_substitution_v2018",
    "consumer_standard_v2025",
    "housing_pvg_v2018",
    "guarantee_aval_quality_v2018",
    "contingent_b3_v2016",
)

_DATA_ROOT_PACKAGE = "nikodym.provisioning.cmf"
_PE_TOLERANCE_PERCENT = Decimal("0.0001")
_EXPECTED_DEFAULT_PP: Mapping[str, tuple[str, str]] = {
    "C1": ("2", "hasta_3_percent"),
    "C2": ("10", "gt_3_le_20_percent"),
    "C3": ("25", "gt_20_le_30_percent"),
    "C4": ("40", "gt_30_le_50_percent"),
    "C5": ("65", "gt_50_le_80_percent"),
    "C6": ("90", "gt_80_percent"),
}


class CmfMatrixConfigLike(Protocol):
    """Contrato estructural mínimo para B15.1, compatible con ``CmfMatrixConfig`` futuro."""

    active_version: str
    require_verified_rows: bool
    fail_on_source_mismatch: bool


class CmfOfficialSource(BaseModel):
    """Fuente oficial declarada en el manifest del bundle normativo."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    circular: str
    url: str
    role: str
    status: SourceStatus


class CmfManifestMatrixEntry(BaseModel):
    """Metadatos por matriz dentro del manifest versionado."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    matrix_id: str
    status: ManifestStatus
    source_ref: str
    effective_date: str
    source_normative: str


class CmfPendingItem(BaseModel):
    """Brecha normativa marcada explicitamente como ``FALTA-DATO``."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    source_ref: str
    status: Literal["pending"]
    marker: Literal["FALTA-DATO"]
    description: str


class CmfMatrixManifest(BaseModel):
    """Manifest auditable del bundle de matrices CMF."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    version: str
    effective_date: str
    extraction_date: str
    official_sources: tuple[CmfOfficialSource, ...]
    normativa_refs: tuple[str, ...]
    yaml_sha256: str
    author: str
    verifier: str
    status: ManifestStatus
    matrices: tuple[CmfManifestMatrixEntry, ...]
    pending_items: tuple[CmfPendingItem, ...] = Field(default_factory=tuple)


class CmfMatrixRow(BaseModel):
    """Fila normativa individual de una matriz CMF versionada."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    matrix_id: str
    row_id: str
    dimensions: dict[str, str] = Field(default_factory=dict)
    pi_percent: str | None = None
    pdi_percent: str | None = None
    pe_percent: str | None = None
    pp_percent: str | None = None
    ccf_percent: str | None = None
    mp_percent: str | None = None
    status: RowStatus
    source_ref: str

    @field_validator("dimensions")
    @classmethod
    def _ordena_dimensions(cls, value: dict[str, str]) -> dict[str, str]:
        """Ordena dimensiones para dumps determinísticos."""
        return {key: value[key] for key in sorted(value)}


class CmfMatrixBundle(BaseModel):
    """Conjunto cargado de matrices CMF, manifest y filas normalizadas."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    manifest: CmfMatrixManifest
    rows: tuple[CmfMatrixRow, ...]

    @property
    def matrix_ids(self) -> tuple[str, ...]:
        """Identificadores presentes en las filas, en orden canónico CMF."""
        present = {row.matrix_id for row in self.rows}
        return tuple(matrix_id for matrix_id in CMF_MATRIX_IDS if matrix_id in present)

    @property
    def rows_by_matrix(self) -> dict[str, tuple[CmfMatrixRow, ...]]:
        """Agrupa filas por ``matrix_id`` preservando el orden del YAML."""
        grouped: dict[str, list[CmfMatrixRow]] = {}
        for row in self.rows:
            grouped.setdefault(row.matrix_id, []).append(row)
        return {matrix_id: tuple(rows) for matrix_id, rows in grouped.items()}

    def get_rows(self, matrix_id: str) -> tuple[CmfMatrixRow, ...]:
        """Devuelve todas las filas de una matriz; ``()`` si no existe."""
        return self.rows_by_matrix.get(matrix_id, ())

    def get_row(self, matrix_id: str, row_id: str) -> CmfMatrixRow:
        """Devuelve una fila normativa exacta o falla con mensaje auditable."""
        for row in self.get_rows(matrix_id):
            if row.row_id == row_id:
                return row
        raise CmfMatrixError(
            f"No existe la fila normativa matrix_id={matrix_id!r}, row_id={row_id!r}."
        )


def load_cmf_matrices(config: CmfMatrixConfigLike) -> CmfMatrixBundle:
    """Carga el bundle CMF activo, verificando hash, manifest y estado de filas."""
    version = config.active_version
    manifest = CmfMatrixManifest.model_validate_json(_read_resource_bytes("manifest.json"))
    yaml_name = f"{version}.yaml"
    sha_name = f"{version}.sha256"
    yaml_bytes = _read_resource_bytes(yaml_name)
    expected_sha = _read_resource_bytes(sha_name).decode("utf-8").strip()
    actual_sha = hashlib.sha256(yaml_bytes).hexdigest()

    _require_source_match(
        actual_sha == expected_sha,
        (
            f"Hash YAML inconsistente para {yaml_name}: esperado {expected_sha}, "
            f"observado {actual_sha}."
        ),
        fail=config.fail_on_source_mismatch,
    )
    _require_source_match(
        manifest.yaml_sha256 == expected_sha,
        "El sha256 del manifest no coincide con el archivo .sha256 del bundle CMF.",
        fail=config.fail_on_source_mismatch,
    )
    _require_source_match(
        manifest.version == version,
        f"Manifest CMF version={manifest.version!r} no coincide con active_version={version!r}.",
        fail=config.fail_on_source_mismatch,
    )

    rows = _parse_yaml_rows(
        yaml_bytes,
        version,
        fail_on_source_mismatch=config.fail_on_source_mismatch,
    )
    bundle = CmfMatrixBundle(manifest=manifest, rows=rows)
    if config.require_verified_rows:
        _require_no_pending_rows(bundle)
    validate_cmf_matrix_bundle(bundle)
    return bundle


def validate_cmf_matrix_bundle(bundle: CmfMatrixBundle) -> None:
    """Valida cobertura, duplicados y coherencia aritmética del bundle CMF."""
    _validate_matrix_coverage(bundle)
    _validate_row_uniqueness(bundle.rows)
    for row in bundle.rows:
        _validate_percent_coherence(row)
        _validate_default_row(row)


def _read_resource_bytes(name: str) -> bytes:
    try:
        return resources.files(_DATA_ROOT_PACKAGE).joinpath("data", name).read_bytes()
    except FileNotFoundError as exc:
        raise CmfMatrixError(f"No existe el recurso de matrices CMF {name!r}.") from exc


def _require_source_match(condition: bool, message: str, *, fail: bool) -> None:
    if fail and not condition:
        raise CmfMatrixError(message)


def _parse_yaml_rows(
    yaml_bytes: bytes,
    version: str,
    *,
    fail_on_source_mismatch: bool,
) -> tuple[CmfMatrixRow, ...]:
    document = cast(Mapping[str, Any], yaml.safe_load(yaml_bytes.decode("utf-8")))
    _require_source_match(
        document["version"] == version,
        f"YAML CMF version={document['version']!r} no coincide con active_version={version!r}.",
        fail=fail_on_source_mismatch,
    )
    rows: list[CmfMatrixRow] = []
    matrices = cast(Iterable[Mapping[str, Any]], document["matrices"])
    for matrix in matrices:
        matrix_id = str(matrix["matrix_id"])
        for raw_row in cast(Iterable[Mapping[str, Any]], matrix["rows"]):
            payload = dict(raw_row)
            payload["matrix_id"] = matrix_id
            rows.append(CmfMatrixRow.model_validate(payload))
    return tuple(rows)


def _require_no_pending_rows(bundle: CmfMatrixBundle) -> None:
    pending = [(row.matrix_id, row.row_id) for row in bundle.rows if row.status == "pending"]
    if pending:
        raise CmfMatrixError(f"El bundle CMF contiene filas pending no permitidas: {pending}.")


def _validate_matrix_coverage(bundle: CmfMatrixBundle) -> None:
    expected = set(CMF_MATRIX_IDS)
    observed = {row.matrix_id for row in bundle.rows}
    if observed != expected:
        missing = sorted(expected - observed)
        unexpected = sorted(observed - expected)
        raise CmfMatrixError(
            f"El bundle CMF no cubre exactamente las 10 matrices: faltan={missing}, "
            f"sobran={unexpected}."
        )

    manifest_ids = {entry.matrix_id for entry in bundle.manifest.matrices}
    if manifest_ids != expected:
        missing = sorted(expected - manifest_ids)
        unexpected = sorted(manifest_ids - expected)
        raise CmfMatrixError(
            f"El manifest CMF no cubre exactamente las 10 matrices: faltan={missing}, "
            f"sobran={unexpected}."
        )

    for entry in bundle.manifest.matrices:
        if not entry.source_ref or not entry.effective_date or entry.status == "deprecated":
            raise CmfMatrixError(
                f"Manifest CMF incompleto o deprecado para matrix_id={entry.matrix_id!r}."
            )


def _validate_row_uniqueness(rows: tuple[CmfMatrixRow, ...]) -> None:
    seen: set[tuple[str, str]] = set()
    for row in rows:
        key = (row.matrix_id, row.row_id)
        if key in seen:
            raise CmfMatrixError(
                f"Fila normativa duplicada en matrix_id={row.matrix_id!r}, row_id={row.row_id!r}."
            )
        seen.add(key)


def _validate_percent_coherence(row: CmfMatrixRow) -> None:
    if row.pi_percent is None or row.pdi_percent is None or row.pe_percent is None:
        return
    pi = _decimal_percent(row.pi_percent, row=row, field_name="pi_percent")
    pdi = _decimal_percent(row.pdi_percent, row=row, field_name="pdi_percent")
    pe = _decimal_percent(row.pe_percent, row=row, field_name="pe_percent")
    expected = (pi * pdi) / Decimal("100")
    if abs(pe - expected) > _PE_TOLERANCE_PERCENT:
        raise CmfMatrixError(
            "PE inconsistente para "
            f"matrix_id={row.matrix_id!r}, row_id={row.row_id!r}: "
            f"PE={row.pe_percent}, PI*PDI/100={expected}."
        )


def _validate_default_row(row: CmfMatrixRow) -> None:
    if row.matrix_id != "commercial_individual_default_v2014":
        return
    expected_pp, expected_range = _EXPECTED_DEFAULT_PP[row.row_id]
    if row.pp_percent is None:
        raise CmfMatrixError(
            f"Fila C sin PP en matrix_id={row.matrix_id!r}, row_id={row.row_id!r}."
        )
    observed_pp = _decimal_percent(row.pp_percent, row=row, field_name="pp_percent")
    if observed_pp != Decimal(expected_pp):
        raise CmfMatrixError(
            f"PP inconsistente para matrix_id={row.matrix_id!r}, row_id={row.row_id!r}: "
            f"esperado={expected_pp}, observado={row.pp_percent}."
        )
    observed_range = row.dimensions.get("expected_loss_range")
    if observed_range != expected_range:
        raise CmfMatrixError(
            f"Rango de perdida inconsistente para matrix_id={row.matrix_id!r}, "
            f"row_id={row.row_id!r}: esperado={expected_range!r}, observado={observed_range!r}."
        )


def _decimal_percent(value: str, *, row: CmfMatrixRow, field_name: str) -> Decimal:
    normalized = value.strip().replace(",", ".")
    try:
        return Decimal(normalized) + Decimal("0")
    except InvalidOperation as exc:
        raise CmfMatrixError(
            f"Porcentaje invalido en matrix_id={row.matrix_id!r}, row_id={row.row_id!r}, "
            f"campo={field_name}: {value!r}."
        ) from exc
