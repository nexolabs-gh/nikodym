"""Bundle público seguro y aplicación targetless de scorecards (SDD-30 W1).

El formato público es un directorio con ``manifest.json`` canónico y ``bins.parquet``. No
serializa objetos Python ni ejecuta pickle/joblib: carga primero el manifiesto, verifica allowlist,
tamaños y hashes, y recién entonces deja que PyArrow lea las reglas columnares.

**Experimental (SemVer 1.x):** la superficie puede crecer de forma aditiva.
"""

from __future__ import annotations

import hashlib
import json
import math
import numbers
import os
import shutil
import sqlite3
import struct
import tempfile
from collections.abc import Iterator, Mapping
from contextlib import suppress
from dataclasses import dataclass
from datetime import date, datetime
from importlib import metadata
from itertools import pairwise
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final, Self, cast

import numpy as np
import pandas as pd

from nikodym.core.build import (
    build_uv_lock_hash,
    installed_distribution_hash,
    runtime_environment_hash,
)
from nikodym.data.hashing import data_hash
from nikodym.scorecard.exceptions import ScorecardBundleError

if TYPE_CHECKING:
    from nikodym.core.config import NikodymConfig
    from nikodym.core.study import Study

__all__ = [
    "BatchApplicationResult",
    "FittedScorecardBundle",
    "ScorecardApplicationResult",
    "apply",
    "fit_scorecard_bundle",
]

_BUNDLE_SCHEMA: Final = 1
_BUNDLE_FILES: Final = frozenset({"manifest.json", "bins.parquet"})
_MAX_MANIFEST_BYTES: Final = 2 * 1024 * 1024
_MAX_RULES_BYTES: Final = 256 * 1024 * 1024
_MAX_RULES_ROWS: Final = 1_000_000
_MAX_RULES_UNCOMPRESSED_BYTES: Final = 512 * 1024 * 1024
_MAX_TRAIN_ROWS: Final = 1_000_000
_MAX_TRAIN_VARIABLES: Final = 100
_MAX_TRAIN_CARDINALITY: Final = 100_000
_MAX_BATCH_ROWS: Final = 5_000_000
_RULE_COLUMNS: Final = (
    "feature",
    "woe_column",
    "bin_id",
    "kind",
    "lower",
    "upper",
    "values_json",
    "woe",
    "raw_points",
    "points",
    "support",
    "supported",
)
_NUMERIC_OUTPUTS: Final = (
    "eta",
    "pd_raw",
    "score_unrounded",
    "score",
    "pd_calibrated",
)


@dataclass(frozen=True, slots=True)
class ScorecardApplicationResult:
    """Salida completa de apply con una fila estable por entrada y traza por tratamiento."""

    application_frame: pd.DataFrame
    woe_frame: pd.DataFrame
    trace_frame: pd.DataFrame
    summary: Mapping[str, int]
    lineage: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class BatchApplicationResult:
    """Referencia verificable a una aplicación batch particionada."""

    output_dir: Path
    manifest_path: Path
    rows: int
    chunks: int
    bundle_hash: str
    input_hash: str
    output_hash: str


@dataclass(frozen=True, slots=True)
class _PreparedFeatureRules:
    """Vista inmutable de reglas congeladas reutilizable entre chunks."""

    rules: pd.DataFrame
    special_rules: Mapping[tuple[str, Any], pd.Series[Any]]
    declared_specials: frozenset[tuple[str, Any]]
    categorical: Mapping[tuple[str, Any], pd.Series[Any]]
    numeric: pd.DataFrame
    numeric_lowers: np.ndarray[Any, Any]
    numeric_uppers: np.ndarray[Any, Any]
    numeric_woe: np.ndarray[Any, Any]
    numeric_raw_points: np.ndarray[Any, Any]
    numeric_points: np.ndarray[Any, Any]
    numeric_bin_ids: np.ndarray[Any, Any]
    missing_rule: pd.Series[Any] | None


class FittedScorecardBundle:
    """Estado fiteado puro de F1, persistible sin ejecución arbitraria."""

    def __init__(self, *, manifest: Mapping[str, Any], rules: pd.DataFrame) -> None:
        normalized = _validate_manifest(dict(manifest), require_files=False)
        normalized_rules = _validate_rules(rules)
        _validate_rule_mapping(normalized, normalized_rules)
        logical_hash = _rules_hash(normalized_rules)
        if normalized["rules_sha256"] != logical_hash:
            raise ScorecardBundleError(
                "El hash lógico de bins no coincide con las reglas recibidas: "
                f"esperado={normalized['rules_sha256']}, observado={logical_hash}."
            )
        expected_bundle_hash = _bundle_hash(normalized)
        if normalized["bundle_hash"] != expected_bundle_hash:
            raise ScorecardBundleError(
                "El hash semántico del bundle no coincide con su manifiesto: "
                f"esperado={normalized['bundle_hash']}, observado={expected_bundle_hash}."
            )
        self._manifest = normalized
        self._rules = normalized_rules
        self._prepared_rules = {
            feature: _prepare_feature_rules(
                normalized_rules.loc[normalized_rules["feature"].eq(feature)].copy(deep=False),
                special_values=tuple(normalized["special_catalog"].get(feature, ())),
            )
            for feature in normalized["model"]["features"]
        }

    @property
    def bundle_hash(self) -> str:
        """Hash semántico estable, independiente de timestamps y bytes físicos de Parquet."""
        return cast(str, self._manifest["bundle_hash"])

    @property
    def manifest(self) -> dict[str, Any]:
        """Copia defensiva del manifiesto público."""
        return cast("dict[str, Any]", json.loads(_canonical_json(self._manifest)))

    @classmethod
    def from_study(cls, study: Study) -> Self:
        """Congela reglas, modelo, scaler, calibración y lineage de un F1 ya ejecutado."""
        if study.run_context.status != "done":
            raise ScorecardBundleError(
                "Sólo se puede construir un bundle desde un Study terminado con status='done'."
            )
        required = (
            ("binning", "process"),
            ("model", "final_features"),
            ("model", "final_woe_columns"),
            ("model", "coefficients"),
            ("scorecard", "scorecard"),
            ("scorecard", "card"),
            ("calibration", "parameters"),
        )
        missing = [
            f"{domain}.{key}" for domain, key in required if not study.artifacts.has(domain, key)
        ]
        if missing:
            raise ScorecardBundleError(
                "El Study no contiene todos los artefactos fiteados de F1: " + ", ".join(missing)
            )

        binner = study.artifacts.get("binning", "process")
        features = tuple(str(value) for value in study.artifacts.get("model", "final_features"))
        woe_columns = tuple(
            str(value) for value in study.artifacts.get("model", "final_woe_columns")
        )
        coefficients = study.artifacts.get("model", "coefficients")
        scorecard = study.artifacts.get("scorecard", "scorecard")
        card = study.artifacts.get("scorecard", "card")
        calibration = study.artifacts.get("calibration", "parameters")
        rules = _rules_from_fitted(
            binner=binner,
            features=features,
            woe_columns=woe_columns,
            scorecard=scorecard,
        )
        intercept, beta = _model_parameters(
            coefficients,
            features=features,
            woe_columns=woe_columns,
        )
        lineage = study.lineage_bundle()
        stable_lineage = {
            "git_sha": lineage.git_sha,
            "git_dirty": lineage.git_dirty,
            "data_hash": lineage.data_hash,
            "config_hash": lineage.config_hash,
            "root_seed": lineage.root_seed,
            "uv_lock_hash": lineage.uv_lock_hash,
            "runtime_environment_hash": getattr(lineage, "runtime_environment_hash", None),
            "installed_distribution_hash": installed_distribution_hash(),
            "library_versions": dict(sorted(lineage.library_versions.items())),
            "determinism_caveats": list(lineage.determinism_caveats),
            "injected_artifacts": list(lineage.injected_artifacts),
        }
        input_schema, row_identity, treatment_policy, special_catalog = _inference_contracts(
            study, features
        )
        model = {
            "features": list(features),
            "woe_columns": list(woe_columns),
            "intercept": intercept,
            "beta": beta,
            "score_column": str(card.score_column),
            "score_direction": str(card.score_direction),
            "rounding_method": str(card.rounding_method),
            "min_score": card.min_score,
            "max_score": card.max_score,
            "calibration": calibration.model_dump(mode="json"),
        }
        manifest: dict[str, Any] = {
            "schema_version": _BUNDLE_SCHEMA,
            "format": "nikodym.scorecard.bundle",
            "input_schema": input_schema,
            "row_identity": row_identity,
            "treatment_policy": treatment_policy,
            "special_catalog": special_catalog,
            "model": model,
            "fit_lineage": stable_lineage,
            "rules_sha256": _rules_hash(rules),
            "files": {},
            "bundle_hash": "",
        }
        manifest["bundle_hash"] = _bundle_hash(manifest)
        return cls(manifest=manifest, rules=rules)

    @classmethod
    def load(cls, path: str | Path) -> Self:
        """Carga un bundle tras verificar forma, allowlist, tamaños y SHA-256 físicos."""
        root = Path(path)
        if not root.is_dir() or root.is_symlink():
            raise ScorecardBundleError(f"El bundle debe ser un directorio regular: '{root}'.")
        entries = {entry.name for entry in root.iterdir()}
        if entries != _BUNDLE_FILES:
            raise ScorecardBundleError(
                "Contenido de bundle inesperado: "
                f"faltan={sorted(_BUNDLE_FILES - entries)}, "
                f"sobran={sorted(entries - _BUNDLE_FILES)}."
            )
        for name in _BUNDLE_FILES:
            entry = root / name
            if entry.is_symlink() or not entry.is_file():
                raise ScorecardBundleError(f"El artefacto '{name}' no es un archivo regular.")
        manifest_path = root / "manifest.json"
        if manifest_path.stat().st_size > _MAX_MANIFEST_BYTES:
            raise ScorecardBundleError("manifest.json excede el límite de 2 MiB.")
        try:
            manifest_bytes = manifest_path.read_bytes()
            raw_manifest = json.loads(manifest_bytes.decode("utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ScorecardBundleError(f"manifest.json inválido: {exc}.") from exc
        manifest = _validate_manifest(raw_manifest, require_files=True)
        if manifest_bytes != (_canonical_json(manifest) + "\n").encode("utf-8"):
            raise ScorecardBundleError("manifest.json no usa bytes JSON canónicos.")
        current_build_hash = build_uv_lock_hash()
        if manifest["fit_lineage"]["uv_lock_hash"] != current_build_hash:
            raise ScorecardBundleError(
                "El bundle fue construido con otra fuente de dependencias: "
                f"fit={manifest['fit_lineage']['uv_lock_hash']}, "
                f"apply={current_build_hash}."
            )
        rules_path = root / "bins.parquet"
        size = rules_path.stat().st_size
        if size > _MAX_RULES_BYTES:
            raise ScorecardBundleError("bins.parquet excede el límite de 256 MiB.")
        expected = manifest["files"].get("bins.parquet")
        observed = _hash_file(rules_path)
        if expected != observed:
            raise ScorecardBundleError(
                "Hash físico inválido para bins.parquet: "
                f"esperado={expected!r}, observado={observed}."
            )
        try:
            import pyarrow.parquet as pq

            parquet = pq.ParquetFile(rules_path)  # type: ignore[no-untyped-call]
            metadata_ = parquet.metadata
            if metadata_ is None or metadata_.num_rows > _MAX_RULES_ROWS:
                raise ScorecardBundleError(
                    "bins.parquet excede el límite de 1.000.000 reglas según metadata."
                )
            if tuple(parquet.schema_arrow.names) != _RULE_COLUMNS:
                raise ScorecardBundleError("bins.parquet declara un schema físico inesperado.")
            uncompressed = sum(
                metadata_.row_group(group).column(column).total_uncompressed_size
                for group in range(metadata_.num_row_groups)
                for column in range(metadata_.row_group(group).num_columns)
            )
            if uncompressed > _MAX_RULES_UNCOMPRESSED_BYTES:
                raise ScorecardBundleError(
                    "bins.parquet excede el límite descomprimido de 512 MiB."
                )
            rules = parquet.read().to_pandas()  # type: ignore[no-untyped-call]
        except ScorecardBundleError:
            raise
        except Exception as exc:
            raise ScorecardBundleError(f"No se pudo leer bins.parquet verificado: {exc}.") from exc
        return cls(manifest=manifest, rules=rules)

    def save(self, path: str | Path) -> Path:
        """Escribe el bundle en un directorio nuevo mediante temporal y rename atómico."""
        destination = Path(path)
        if destination.exists() or destination.is_symlink():
            raise ScorecardBundleError(f"El destino del bundle ya existe: '{destination}'.")
        destination.parent.mkdir(parents=True, exist_ok=True)
        tmp = Path(
            tempfile.mkdtemp(prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent)
        )
        try:
            rules_path = tmp / "bins.parquet"
            self._rules.to_parquet(rules_path, index=False, engine="pyarrow")
            manifest = self.manifest
            manifest["files"] = {"bins.parquet": _hash_file(rules_path)}
            _write_canonical_json_file(tmp / "manifest.json", manifest)
            os.replace(tmp, destination)
        except Exception:
            shutil.rmtree(tmp, ignore_errors=True)
            raise
        return destination

    def apply(self, frame: pd.DataFrame) -> ScorecardApplicationResult:
        """Aplica el estado congelado sin refit; una condición no soportada falla por fila."""
        expected_columns = {
            *self._manifest["model"]["features"],
            *self._manifest["row_identity"]["unique_keys"],
        }
        ignored_extra_columns = [
            str(column) for column in frame.columns if str(column) not in expected_columns
        ]
        raw = _validate_apply_frame(frame, self._manifest, self._rules)
        model = self._manifest["model"]
        features = tuple(model["features"])
        woe_columns = tuple(model["woe_columns"])
        beta = {str(key): float(value) for key, value in model["beta"].items()}
        rows = len(raw.index)
        columns = len(features)
        woe_matrix = np.full((rows, columns), np.nan, dtype="float64")
        raw_points_matrix = np.full((rows, columns), np.nan, dtype="float64")
        points_matrix = np.full((rows, columns), np.nan, dtype="float64")
        bin_matrix = np.full((rows, columns), None, dtype="object")
        state_matrix = np.full((rows, columns), None, dtype="object")
        reason_matrix = np.full((rows, columns), None, dtype="object")
        warning_matrix = np.full((rows, columns), None, dtype="object")
        special_catalog = self._manifest["special_catalog"]
        special_handling = str(self._manifest["treatment_policy"]["special_handling"])

        for position, feature in enumerate(features):
            prepared = self._prepared_rules[feature]
            treatment = _apply_feature(
                raw[feature],
                prepared.rules,
                special_values=tuple(special_catalog.get(feature, ())),
                special_handling=special_handling,
                prepared=prepared,
            )
            woe_matrix[:, position] = treatment["woe"]
            raw_points_matrix[:, position] = treatment["raw_points"]
            points_matrix[:, position] = treatment["points"]
            bin_matrix[:, position] = treatment["bin_id"]
            state_matrix[:, position] = treatment["state"]
            reason_matrix[:, position] = treatment["reason"]
            warning_matrix[:, position] = treatment["warning"]

        first_failure = np.full(rows, None, dtype="object")
        for position, feature in enumerate(features):
            mask = (first_failure == None) & (reason_matrix[:, position] != None)  # noqa: E711
            if mask.any():
                first_failure[mask] = np.char.add(
                    f"{feature}:", reason_matrix[mask, position].astype(str)
                )
        scorable = first_failure == None  # noqa: E711
        eta = np.full(rows, float(model["intercept"]), dtype="float64")
        score_unrounded = np.zeros(rows, dtype="float64")
        score = np.zeros(rows, dtype="float64")
        for position, feature in enumerate(features):
            eta += beta[feature] * woe_matrix[:, position]
            score_unrounded += raw_points_matrix[:, position]
            score += points_matrix[:, position]
        minimum, maximum = model["min_score"], model["max_score"]
        if minimum is not None:
            score = np.maximum(score, float(minimum))
        if maximum is not None:
            score = np.minimum(score, float(maximum))
        pd_raw = _expit_array(eta)
        pd_calibrated = _calibrate_array(eta, model["calibration"])
        for output in (eta, score_unrounded, score, pd_raw, pd_calibrated):
            output[~scorable] = np.nan
        woe_matrix[~scorable, :] = np.nan

        input_positions = np.arange(rows, dtype="int64")
        input_ids = raw.index.to_numpy(copy=True)
        treatment_flags = [
            sorted(
                {
                    str(state)
                    for state in state_matrix[row_position, :].tolist()
                    if state not in {None, "observed"}
                }
            )
            for row_position in range(rows)
        ]
        warning_codes = [
            sorted(
                {
                    str(warning)
                    for warning in warning_matrix[row_position, :].tolist()
                    if warning is not None
                }
            )
            for row_position in range(rows)
        ]
        application = pd.DataFrame(
            {
                "input_position": input_positions,
                "input_id": input_ids,
                "input_row_hash": _row_hashes(raw),
                "scoring_status": np.where(scorable, "scored", "not_scorable"),
                "treatment_flags": treatment_flags,
                "rejection_reason": first_failure,
                "not_scorable_reason": first_failure,
                "eta": pd.array(eta, dtype="Float64"),
                "linear_predictor": pd.array(eta, dtype="Float64"),
                "pd_raw": pd.array(pd_raw, dtype="Float64"),
                "score_unrounded": pd.array(score_unrounded, dtype="Float64"),
                "score": pd.array(score, dtype="Float64"),
                "pd_calibrated": pd.array(pd_calibrated, dtype="Float64"),
                "warning_codes": warning_codes,
                "bundle_hash": self.bundle_hash,
            },
            index=raw.index.copy(),
        )
        woe_frame = pd.DataFrame(
            {
                "input_position": input_positions,
                "input_id": input_ids,
                **{
                    column: pd.array(woe_matrix[:, position], dtype="Float64")
                    for position, column in enumerate(woe_columns)
                },
            },
            index=raw.index.copy(),
        )
        raw_values = (
            raw.loc[:, list(features)]
            .astype("string")
            .fillna("<missing>")
            .to_numpy(dtype="object", copy=False)
            .ravel(order="C")
        )
        trace = pd.DataFrame(
            {
                "input_position": np.repeat(input_positions, columns),
                "input_id": np.repeat(input_ids, columns),
                "feature_position": np.tile(np.arange(columns, dtype="int64"), rows),
                "feature": np.tile(np.asarray(features, dtype="object"), rows),
                "raw_value": raw_values,
                "raw_state": state_matrix.ravel(order="C"),
                "rule": np.where(
                    bin_matrix.ravel(order="C") == None,  # noqa: E711
                    reason_matrix.ravel(order="C"),
                    bin_matrix.ravel(order="C"),
                ),
                "bin_id": bin_matrix.ravel(order="C"),
                "woe": pd.array(woe_matrix.ravel(order="C"), dtype="Float64"),
                "transformed_value": pd.array(woe_matrix.ravel(order="C"), dtype="Float64"),
                "raw_points": pd.array(raw_points_matrix.ravel(order="C"), dtype="Float64"),
                "points": pd.array(points_matrix.ravel(order="C"), dtype="Float64"),
                "reason": reason_matrix.ravel(order="C"),
                "warning_code": warning_matrix.ravel(order="C"),
            }
        )
        application["treatment_trace_hash"] = _trace_hashes(trace, rows=rows)
        counts = application["scoring_status"].value_counts().to_dict()
        summary = {
            "input_rows": len(raw.index),
            "scored_rows": int(counts.get("scored", 0)),
            "not_scorable_rows": int(counts.get("not_scorable", 0)),
        }
        try:
            version = metadata.version("nikodym")
        except metadata.PackageNotFoundError:  # pragma: no cover - editable anómalo
            version = "unknown"
        current_build_hash = build_uv_lock_hash()
        current_runtime_hash = runtime_environment_hash()
        current_distribution_hash = installed_distribution_hash()
        fit_lineage = self._manifest["fit_lineage"]
        lineage = {
            "bundle_hash": self.bundle_hash,
            "data_hash": data_hash(raw),
            "config_hash": fit_lineage["config_hash"],
            "fit_data_hash": fit_lineage["data_hash"],
            "git_sha": fit_lineage["git_sha"],
            "git_dirty": fit_lineage["git_dirty"],
            "root_seed": fit_lineage["root_seed"],
            "bundle_schema_version": _BUNDLE_SCHEMA,
            "nikodym_version": version,
            "uv_lock_hash": current_build_hash,
            "runtime_environment_hash": current_runtime_hash,
            "installed_distribution_hash": current_distribution_hash,
            "fit_uv_lock_hash": fit_lineage["uv_lock_hash"],
            "fit_runtime_environment_hash": fit_lineage["runtime_environment_hash"],
            "runtime_matches_fit": current_runtime_hash == fit_lineage["runtime_environment_hash"],
            "distribution_matches_fit": current_distribution_hash
            == fit_lineage["installed_distribution_hash"],
            "candidate_distribution_hash": current_distribution_hash,
            "library_versions": fit_lineage["library_versions"],
            "determinism_caveats": fit_lineage["determinism_caveats"],
            "injected_artifacts": fit_lineage["injected_artifacts"],
            "features": list(features),
            "treatment_policy": self._manifest["treatment_policy"],
            "ignored_extra_columns": ignored_extra_columns,
        }
        return ScorecardApplicationResult(application, woe_frame, trace, summary, lineage)

    def apply_file(
        self,
        input_path: str | Path,
        output_dir: str | Path,
        *,
        chunk_size: int = 100_000,
        id_column: str | None = None,
    ) -> BatchApplicationResult:
        """Aplica CSV/Parquet por chunks y publica tres vistas particionadas más manifiesto."""
        if chunk_size < 1:
            raise ScorecardBundleError("chunk_size debe ser mayor o igual a 1.")
        source = Path(input_path)
        destination = Path(output_dir)
        if destination.exists() or destination.is_symlink():
            raise ScorecardBundleError(f"El destino batch ya existe: '{destination}'.")
        if not source.is_file() or source.is_symlink():
            raise ScorecardBundleError(f"La entrada batch no es un archivo regular: '{source}'.")
        destination.parent.mkdir(parents=True, exist_ok=True)
        tmp = Path(
            tempfile.mkdtemp(prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent)
        )
        chunks: list[dict[str, Any]] = []
        apply_lineage: dict[str, Any] | None = None
        input_digest = hashlib.sha256(b"nikodym.batch.input.v1\0")
        output_digest = hashlib.sha256(b"nikodym.batch.output.v1\0")
        rows = 0
        identity_db = tmp / ".identities.sqlite3"
        connection = sqlite3.connect(identity_db)
        try:
            connection.execute("CREATE TABLE seen (identity TEXT PRIMARY KEY)")
            connection.execute("CREATE TABLE seen_keys (identity TEXT PRIMARY KEY)")
            for view in ("application", "woe", "trace"):
                (tmp / view).mkdir()
            for chunk_number, chunk in enumerate(
                _read_chunks(
                    source,
                    chunk_size=chunk_size,
                    manifest=self._manifest,
                    id_column=id_column,
                )
            ):
                chunk = chunk.copy(deep=True)
                _validate_batch_rows(rows + len(chunk.index))
                if id_column is not None:
                    if id_column not in chunk.columns:
                        raise ScorecardBundleError(
                            f"La columna de identidad '{id_column}' no existe."
                        )
                    chunk = chunk.set_index(id_column, drop=True)
                elif isinstance(chunk.index, pd.RangeIndex):
                    chunk.index = pd.RangeIndex(rows, rows + len(chunk.index), name="input_id")
                if chunk.index.has_duplicates:
                    raise ScorecardBundleError(
                        "La entrada batch contiene identificadores duplicados."
                    )
                identities = [
                    _canonical_json(_encode_scalar(value)) for value in chunk.index.tolist()
                ]
                try:
                    connection.executemany(
                        "INSERT INTO seen(identity) VALUES (?)",
                        ((identity,) for identity in identities),
                    )
                    connection.commit()
                except sqlite3.IntegrityError as exc:
                    raise ScorecardBundleError(
                        "La entrada batch repite identificadores entre chunks."
                    ) from exc
                result = self.apply(chunk)
                unique_keys = tuple(self._manifest["row_identity"]["unique_keys"])
                if unique_keys:
                    key_identities = [
                        _canonical_json([_encode_scalar(row[key]) for key in unique_keys])
                        for _, row in chunk.loc[:, list(unique_keys)].iterrows()
                    ]
                    try:
                        connection.executemany(
                            "INSERT INTO seen_keys(identity) VALUES (?)",
                            ((identity,) for identity in key_identities),
                        )
                        connection.commit()
                    except sqlite3.IntegrityError as exc:
                        raise ScorecardBundleError(
                            "La entrada batch repite llaves de identidad entre chunks."
                        ) from exc
                chunk_runtime_lineage = dict(result.lineage)
                chunk_hash = cast(str, chunk_runtime_lineage.pop("data_hash"))
                if apply_lineage is None:
                    apply_lineage = chunk_runtime_lineage
                elif chunk_runtime_lineage != apply_lineage:
                    raise ScorecardBundleError("El lineage runtime cambió entre chunks del batch.")
                start = rows
                end = start + len(chunk.index)
                application_frame = result.application_frame.copy(deep=True)
                woe_frame = result.woe_frame.copy(deep=True)
                trace_frame = result.trace_frame.copy(deep=True)
                application_frame["input_position"] += start
                woe_frame["input_position"] += start
                trace_frame["input_position"] += start
                part = f"part-{chunk_number:06d}.parquet"
                files: dict[str, dict[str, Any]] = {}
                for view, frame in (
                    ("application", application_frame),
                    ("woe", woe_frame),
                    ("trace", trace_frame),
                ):
                    path = tmp / view / part
                    frame.to_parquet(path, index=True, engine="pyarrow")
                    files[view] = {
                        "path": f"{view}/{part}",
                        "sha256": _hash_file(path),
                        "bytes": path.stat().st_size,
                        "rows": len(frame.index),
                    }
                _update_frame_digest(
                    input_digest,
                    application_frame,
                    ("input_position", "input_id", "input_row_hash"),
                )
                _update_frame_digest(
                    output_digest,
                    application_frame,
                    tuple(application_frame.columns),
                )
                chunks.append(
                    {
                        "chunk": chunk_number,
                        "start": start,
                        "end": end,
                        "input_rows": len(chunk.index),
                        "input_data_hash": chunk_hash,
                        "files": files,
                    }
                )
                rows = end
            if not chunks:
                raise ScorecardBundleError("La entrada batch está vacía.")
            connection.close()
            identity_db.unlink()
            assert apply_lineage is not None
            apply_lineage = {
                **apply_lineage,
                "data_hash": input_digest.hexdigest(),
            }
            batch_manifest = {
                "schema_version": 1,
                "format": "nikodym.scorecard.batch",
                "bundle_hash": self.bundle_hash,
                "source_sha256": _hash_file(source),
                "input_hash": input_digest.hexdigest(),
                "output_hash": output_digest.hexdigest(),
                "rows": rows,
                "chunks": chunks,
                "apply_lineage": apply_lineage,
            }
            _write_canonical_json_file(tmp / "manifest.json", batch_manifest)
            os.replace(tmp, destination)
        except Exception:
            connection.close()
            shutil.rmtree(tmp, ignore_errors=True)
            raise
        return BatchApplicationResult(
            output_dir=destination,
            manifest_path=destination / "manifest.json",
            rows=rows,
            chunks=len(chunks),
            bundle_hash=self.bundle_hash,
            input_hash=input_digest.hexdigest(),
            output_hash=output_digest.hexdigest(),
        )


def fit_scorecard_bundle(config: NikodymConfig, frame: pd.DataFrame) -> FittedScorecardBundle:
    """Ejecuta F1 por la API canónica y congela su salida en un bundle targetless."""
    from nikodym.api import run
    from nikodym.core.config import NikodymConfig
    from nikodym.core.config.schema import cargar_configs_de_dominio

    cargar_configs_de_dominio()
    typed_config = NikodymConfig.model_validate(config.model_dump(mode="python"))
    if typed_config.data is None or typed_config.binning is None:
        raise ScorecardBundleError(
            "fit_scorecard_bundle requiere las secciones data y binning activas."
        )
    memory_data = typed_config.data.model_copy(
        update={"load": typed_config.data.load.model_copy(update={"source": None})}
    )
    memory_config = typed_config.model_copy(update={"data": memory_data})
    feature_columns = _training_feature_columns(typed_config, frame)
    _validate_training_envelope(frame, feature_columns)
    study = run(memory_config, artifacts={("data", "input_frame"): frame})
    if study.run_context.status != "done":
        error = study.run_context.error
        detail = error.message if error is not None else "sin diagnóstico"
        raise ScorecardBundleError(f"El fit de F1 no terminó correctamente: {detail}.")
    return FittedScorecardBundle.from_study(study)


def _training_feature_columns(config: NikodymConfig, frame: pd.DataFrame) -> tuple[str, ...]:
    """Resuelve también el wildcard antes de crear el solver para aplicar H9."""
    assert config.binning is not None and config.data is not None
    if config.binning.feature_columns != "*":
        return tuple(str(value) for value in config.binning.feature_columns)
    from nikodym.binning.step import _resolve_feature_columns

    resolution = _resolve_feature_columns(
        frame=frame,
        target_col="target",
        status_col="label_status",
        partition_col="partition",
        ttd_col="ttd",
        config=config.binning,
        data_config=config.data,
        pd=pd,
    )
    return tuple(resolution.columns)


def _validate_training_envelope(frame: pd.DataFrame, feature_columns: tuple[str, ...]) -> None:
    """Rechaza N+1 de H9=B antes de ajustar o crear workers del solver."""
    rows = len(frame.index)
    variables = len(feature_columns)
    if rows > _MAX_TRAIN_ROWS:
        raise ScorecardBundleError(
            f"El fit excede el envelope S2: filas={rows:,}, límite={_MAX_TRAIN_ROWS:,}."
        )
    if variables > _MAX_TRAIN_VARIABLES:
        raise ScorecardBundleError(
            "El fit excede el envelope S2: "
            f"variables={variables:,}, límite={_MAX_TRAIN_VARIABLES:,}."
        )
    for feature in feature_columns:
        if feature not in frame.columns:
            continue
        cardinality = int(frame[feature].nunique(dropna=True))
        if cardinality > _MAX_TRAIN_CARDINALITY:
            raise ScorecardBundleError(
                "El fit excede el envelope S2: "
                f"cardinalidad de '{feature}'={cardinality:,}, "
                f"límite={_MAX_TRAIN_CARDINALITY:,}."
            )


def _validate_batch_rows(rows: int) -> None:
    """Aplica el techo contractual de H9=B a toda entrada batch."""
    if rows > _MAX_BATCH_ROWS:
        raise ScorecardBundleError(
            "El batch excede el envelope S2: "
            f"filas>{_MAX_BATCH_ROWS:,} (observadas al menos {rows:,})."
        )


def apply(
    bundle: FittedScorecardBundle | str | Path,
    frame: pd.DataFrame,
) -> ScorecardApplicationResult:
    """Superficie funcional aditiva para aplicar un bundle en memoria o desde disco."""
    fitted = (
        bundle if isinstance(bundle, FittedScorecardBundle) else FittedScorecardBundle.load(bundle)
    )
    return fitted.apply(frame)


def _inference_contracts(
    study: Study, features: tuple[str, ...]
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, list[dict[str, Any]]]]:
    """Congela schema, identidad y políticas que gobiernan cartera nueva."""
    data_config = study.config.data
    binning_config = study.config.binning
    if data_config is None or binning_config is None:
        raise ScorecardBundleError("El Study F1 no conserva config data/binning tipado.")
    schema = data_config.schema_
    specs = {str(spec.name): spec for spec in schema.columns}
    frame = study.artifacts.get("data", "frame")
    columns: list[dict[str, Any]] = []
    for feature in features:
        spec = specs.get(feature)
        if spec is None:
            if feature not in frame.columns:
                raise ScorecardBundleError(
                    f"No se puede congelar el dtype del predictor final '{feature}'."
                )
            columns.append(
                {
                    "name": feature,
                    "dtype": _logical_dtype(frame[feature].dtype),
                    "nullable": bool(frame[feature].isna().any()),
                    "coerce": False,
                }
            )
        else:
            columns.append(
                {
                    "name": feature,
                    "dtype": str(spec.dtype),
                    "nullable": bool(spec.nullable),
                    "coerce": bool(spec.coerce),
                }
            )
    special_catalog: dict[str, list[dict[str, Any]]] = {feature: [] for feature in features}
    for special in data_config.missing.special_values:
        selected = features if special.columns == "*" else tuple(special.columns)
        for feature in selected:
            if feature not in special_catalog:
                continue
            for sentinel in special.sentinels:
                encoded = _encode_scalar(sentinel)
                if encoded not in special_catalog[feature]:
                    special_catalog[feature].append(encoded)
    special_catalog = {feature: values for feature, values in special_catalog.items() if values}
    index_dtype = _logical_dtype(frame.index.dtype)
    input_schema = {
        "columns": columns,
        "extra_columns": (
            "forbid"
            if schema.strict is True
            else "filter"
            if schema.strict == "filter"
            else "allow"
        ),
    }
    unique_keys = tuple(schema.unique_keys or ())
    missing_unique_keys = [key for key in unique_keys if key not in frame.columns]
    if missing_unique_keys:
        raise ScorecardBundleError(
            f"No se pueden congelar llaves de identidad ausentes: {missing_unique_keys!r}."
        )
    row_identity = {
        "index_name": schema.index_col,
        "index_dtype": index_dtype,
        "unique_keys": list(unique_keys),
        "unique_key_dtypes": {
            key: str(specs[key].dtype) if key in specs else _logical_dtype(frame[key].dtype)
            for key in unique_keys
        },
        "null_policy": "forbid",
    }
    treatment_policy = {
        "special_handling": str(binning_config.special_handling),
        "missing": "frozen_bin_or_not_scorable",
        "unseen": "not_scorable",
        "outlier": "frozen_support_or_not_scorable",
        "non_finite": "declared_special_or_not_scorable",
    }
    return input_schema, row_identity, treatment_policy, special_catalog


def _logical_dtype(dtype: Any) -> str:
    if pd.api.types.is_bool_dtype(dtype):
        return "bool"
    if pd.api.types.is_integer_dtype(dtype):
        return "int"
    if pd.api.types.is_float_dtype(dtype):
        return "float"
    if pd.api.types.is_datetime64_any_dtype(dtype):
        return "datetime"
    if isinstance(dtype, pd.CategoricalDtype):
        return "category"
    return "str"


def _rules_from_fitted(
    *,
    binner: Any,
    features: tuple[str, ...],
    woe_columns: tuple[str, ...],
    scorecard: pd.DataFrame,
) -> pd.DataFrame:
    if len(features) != len(woe_columns) or not features:
        raise ScorecardBundleError("El mapping final feature/WoE es vacío o inconsistente.")
    rows: list[dict[str, Any]] = []
    for feature, woe_column in zip(features, woe_columns, strict=True):
        if feature not in binner.tables_:
            raise ScorecardBundleError(f"No existe tabla de binning para '{feature}'.")
        table = binner.tables_[feature]
        table = table.loc[table.index.astype(str) != "Totals"].reset_index(drop=True)
        fitted = binner.process_.get_binned_variable(feature)
        dtype = str(fitted.dtype)
        regular_specs = _regular_specs(fitted, table, dtype=dtype)
        n_regular = len(regular_specs)
        points_rows = scorecard.loc[scorecard["feature"].eq(feature)].sort_values("bin_index")
        if len(points_rows.index) != len(table.index):
            raise ScorecardBundleError(
                f"Tabla de puntos y bins no reconcilian para '{feature}': "
                f"puntos={len(points_rows.index)}, bins={len(table.index)}."
            )
        for bin_index, table_row in table.iterrows():
            label = str(table_row["Bin"])
            if bin_index < n_regular and dtype == "numerical":
                kind = "numeric"
                lower, upper = regular_specs[bin_index]
                values: list[dict[str, Any]] = []
            elif bin_index < n_regular:
                kind = "categorical"
                lower = upper = math.nan
                values = [_encode_scalar(value) for value in regular_specs[bin_index]]
            elif label != "Missing":
                kind = "special"
                lower = upper = math.nan
                values = [_encode_scalar(value) for value in binner.special_codes_.get(feature, [])]
            elif label == "Missing":
                kind = "missing"
                lower = upper = math.nan
                values = []
            else:
                raise ScorecardBundleError(
                    f"Bin auxiliar desconocido para '{feature}': "
                    f"índice={bin_index}, label={label!r}."
                )
            score_row = points_rows.iloc[bin_index]
            support = int(table_row["Count"])
            rows.append(
                {
                    "feature": feature,
                    "woe_column": woe_column,
                    "bin_id": f"{feature}:{bin_index}",
                    "kind": kind,
                    "lower": lower,
                    "upper": upper,
                    "values_json": _canonical_json(values),
                    "woe": float(table_row["WoE"]),
                    "raw_points": float(score_row["raw_points"]),
                    "points": float(score_row["points"]),
                    "support": support,
                    "supported": support > 0,
                }
            )
    return _validate_rules(pd.DataFrame(rows, columns=_RULE_COLUMNS))


def _regular_specs(fitted: Any, table: pd.DataFrame, *, dtype: str) -> list[Any]:
    """Extrae cuts/grupos del objeto real; el fallback sólo sirve a dobles de tests."""
    splits = getattr(fitted, "splits", None)
    if splits is not None:
        raw_splits = list(splits)
        if dtype == "numerical":
            bounds = [-math.inf, *(float(value) for value in raw_splits), math.inf]
            return list(pairwise(bounds))
        return [list(group) for group in raw_splits]
    labels = [
        str(label) for label in table["Bin"].tolist() if str(label) not in {"Special", "Missing"}
    ]
    if dtype == "numerical":
        specs: list[tuple[float, float]] = []
        for label in labels:
            parts = [part.strip() for part in label[1:-1].split(",", maxsplit=1)]
            if len(parts) != 2:
                raise ScorecardBundleError(f"Intervalo numérico no interpretable: {label!r}.")
            lower = -math.inf if parts[0] == "-inf" else float(parts[0])
            upper = math.inf if parts[1] == "inf" else float(parts[1])
            specs.append((lower, upper))
        return specs
    return [[item.strip() for item in label[1:-1].split(",") if item.strip()] for label in labels]


def _model_parameters(
    coefficients: pd.DataFrame,
    *,
    features: tuple[str, ...],
    woe_columns: tuple[str, ...],
) -> tuple[float, dict[str, float]]:
    intercept_mask = coefficients["feature"].eq("intercept") | coefficients["woe_column"].eq(
        "const"
    )
    intercept_rows = coefficients.loc[intercept_mask, "beta"]
    if len(intercept_rows.index) > 1:
        raise ScorecardBundleError("El modelo contiene más de un intercepto.")
    intercept = float(intercept_rows.iloc[0]) if len(intercept_rows.index) else 0.0
    beta: dict[str, float] = {}
    for feature, woe_column in zip(features, woe_columns, strict=True):
        matched = coefficients.loc[
            coefficients["feature"].eq(feature) & coefficients["woe_column"].eq(woe_column), "beta"
        ]
        if len(matched.index) != 1:
            raise ScorecardBundleError(f"Coeficiente ausente o ambiguo para '{feature}'.")
        beta[feature] = float(matched.iloc[0])
    return intercept, beta


def _validate_apply_frame(
    frame: pd.DataFrame,
    manifest: Mapping[str, Any],
    rules: pd.DataFrame,
) -> pd.DataFrame:
    if not isinstance(frame, pd.DataFrame) or frame.empty:
        raise ScorecardBundleError("apply requiere un pandas.DataFrame no vacío.")
    duplicated = frame.columns[frame.columns.duplicated()].tolist()
    if duplicated:
        raise ScorecardBundleError(f"apply recibió columnas duplicadas: {duplicated!r}.")
    if frame.index.has_duplicates:
        raise ScorecardBundleError("apply requiere un identificador de fila único en el índice.")
    if bool(pd.isna(frame.index).any()):
        raise ScorecardBundleError("apply no admite identificadores de fila nulos.")
    features = tuple(manifest["model"]["features"])
    missing = [feature for feature in features if feature not in frame.columns]
    if missing:
        raise ScorecardBundleError(f"apply no contiene predictores requeridos: {missing!r}.")
    identity = manifest["row_identity"]
    expected_index = identity["index_name"]
    if expected_index is not None and frame.index.name != expected_index:
        raise ScorecardBundleError(
            f"apply requiere índice '{expected_index}', observado={frame.index.name!r}."
        )
    expected_index_dtype = str(identity["index_dtype"])
    observed_index_dtype = _logical_dtype(frame.index.dtype)
    if observed_index_dtype != expected_index_dtype:
        raise ScorecardBundleError(
            "Dtype incompatible en el identificador de fila: "
            f"esperado={expected_index_dtype!r}, observado={observed_index_dtype!r}."
        )
    unique_keys = tuple(identity["unique_keys"])
    missing_keys = [column for column in unique_keys if column not in frame.columns]
    if missing_keys:
        raise ScorecardBundleError(
            f"apply no contiene llaves de identidad requeridas: {missing_keys!r}."
        )
    if unique_keys:
        keys = frame.loc[:, list(unique_keys)]
        if keys.isna().any(axis=None):
            raise ScorecardBundleError("apply recibió llaves de identidad nulas.")
        if keys.duplicated().any():
            raise ScorecardBundleError("apply recibió llaves de identidad duplicadas.")
        for key in unique_keys:
            expected_key_dtype = str(identity["unique_key_dtypes"][key])
            observed_key_dtype = _logical_dtype(frame[key].dtype)
            if observed_key_dtype != expected_key_dtype:
                raise ScorecardBundleError(
                    f"Dtype incompatible en llave '{key}': "
                    f"esperado={expected_key_dtype!r}, observado={observed_key_dtype!r}."
                )
    schema = manifest["input_schema"]
    allowed = {*features, *unique_keys}
    extras = [str(column) for column in frame.columns if str(column) not in allowed]
    if extras and schema["extra_columns"] == "forbid":
        raise ScorecardBundleError(f"apply recibió columnas extra prohibidas: {extras!r}.")
    raw_columns = list(dict.fromkeys((*features, *unique_keys)))
    raw = frame.loc[:, raw_columns].copy(deep=True)
    contracts = {str(item["name"]): item for item in schema["columns"]}
    for feature in features:
        raw[feature] = _validate_or_coerce_series(raw[feature], contracts[feature])
    numeric_features = rules.loc[rules["kind"].eq("numeric"), "feature"].unique().tolist()
    for feature in numeric_features:
        special_values = {
            _encoded_key(value)
            for values_json in rules.loc[
                rules["feature"].eq(feature) & rules["kind"].eq("special"), "values_json"
            ]
            for value in json.loads(values_json)
        }
        series = raw[feature]
        if pd.api.types.is_bool_dtype(series.dtype):
            raise ScorecardBundleError(
                f"Dtype incompatible en predictor numérico '{feature}': bool."
            )
        if pd.api.types.is_numeric_dtype(series.dtype):
            continue
        values = pd.unique(series.dropna())
        for value in values.tolist():
            if pd.isna(value) or _encoded_key(_encode_scalar(value)) in special_values:
                continue
            if isinstance(value, bool) or not isinstance(value, numbers.Real):
                raise ScorecardBundleError(
                    f"Dtype incompatible en predictor numérico '{feature}': {type(value).__name__}."
                )
    return raw


def _validate_or_coerce_series(
    series: pd.Series[Any], contract: Mapping[str, Any]
) -> pd.Series[Any]:
    dtype = str(contract["dtype"])
    result = series.copy(deep=True)
    if bool(contract["coerce"]):
        target = {
            "int": "Int64",
            "float": "Float64",
            "str": "string",
            "bool": "boolean",
            "category": "category",
            "datetime": "datetime64[ns]",
        }[dtype]
        try:
            result = result.astype(cast(Any, target))
        except (TypeError, ValueError) as exc:
            raise ScorecardBundleError(
                f"No se pudo coercionar '{series.name}' al dtype congelado {dtype!r}: {exc}."
            ) from exc
    elif not _dtype_matches(result, dtype):
        raise ScorecardBundleError(
            f"Dtype incompatible en predictor '{series.name}': "
            f"esperado={dtype!r}, observado={str(series.dtype)!r}."
        )
    if not bool(contract["nullable"]) and bool(result.isna().any()):
        raise ScorecardBundleError(f"El predictor no nullable '{series.name}' contiene nulos.")
    return result


def _dtype_matches(series: pd.Series[Any], expected: str) -> bool:
    dtype = series.dtype
    if expected == "bool":
        return bool(pd.api.types.is_bool_dtype(dtype))
    if expected == "int":
        return bool(pd.api.types.is_integer_dtype(dtype) and not pd.api.types.is_bool_dtype(dtype))
    if expected == "float":
        return bool(pd.api.types.is_numeric_dtype(dtype) and not pd.api.types.is_bool_dtype(dtype))
    if expected == "datetime":
        return bool(pd.api.types.is_datetime64_any_dtype(dtype))
    if expected == "category":
        return isinstance(dtype, pd.CategoricalDtype) or _all_non_null_instances(series, str)
    return bool(pd.api.types.is_string_dtype(dtype) or _all_non_null_instances(series, str))


def _all_non_null_instances(series: pd.Series[Any], expected: type[Any]) -> bool:
    return all(isinstance(value, expected) for value in series.dropna().tolist())


def _apply_feature(
    series: pd.Series[Any],
    rules: pd.DataFrame,
    *,
    special_values: tuple[Mapping[str, Any], ...],
    special_handling: str,
    prepared: _PreparedFeatureRules | None = None,
) -> dict[str, np.ndarray[Any, Any]]:
    """Resuelve valores únicos preservando estado, regla y puntos antes del rounding."""
    row_count = len(series.index)
    codes, uniques = pd.factorize(series, sort=False, use_na_sentinel=True)
    unique_count = len(uniques)
    unique_woe = np.full(unique_count, np.nan, dtype="float64")
    unique_raw_points = np.full(unique_count, np.nan, dtype="float64")
    unique_points = np.full(unique_count, np.nan, dtype="float64")
    unique_bins = np.full(unique_count, None, dtype="object")
    unique_states = np.full(unique_count, None, dtype="object")
    unique_reasons = np.full(unique_count, None, dtype="object")
    unique_warnings = np.full(unique_count, None, dtype="object")

    prepared = prepared or _prepare_feature_rules(rules, special_values=special_values)
    special_rules = prepared.special_rules
    declared_specials = prepared.declared_specials
    categorical = prepared.categorical
    numeric = prepared.numeric
    numeric_uppers = prepared.numeric_uppers
    missing_rule = prepared.missing_rule

    def assign_rule(mask: np.ndarray[Any, Any], row: pd.Series[Any]) -> None:
        unique_woe[mask] = float(row["woe"])
        unique_raw_points[mask] = float(row["raw_points"])
        unique_points[mask] = float(row["points"])
        unique_bins[mask] = str(row["bin_id"])

    def resolve_special(mask: np.ndarray[Any, Any], encoded: tuple[str, Any]) -> None:
        if not mask.any():
            return
        unique_states[mask] = "special"
        selected = missing_rule if special_handling == "as_missing" else special_rules.get(encoded)
        if selected is not None and bool(selected["supported"]):
            assign_rule(mask, selected)
            if special_handling == "as_missing":
                unique_warnings[mask] = "special_mapeado_a_missing_entrenado"
        else:
            unique_reasons[mask] = "special_sin_soporte_en_fit"
            unique_warnings[mask] = "special_sin_soporte_en_fit"

    if not numeric.empty and pd.api.types.is_numeric_dtype(series.dtype):
        unique_numbers = uniques.to_numpy(dtype="float64", copy=True)
        for encoded in declared_specials:
            if encoded[0] == "number":
                special_mask = unique_numbers == float(encoded[1])
            else:
                # ``+/-inf`` conserva una representación JSON estricta, pero debe ganar al
                # guard de no finitos cuando el contrato lo declaró como special.
                special_mask = np.fromiter(
                    (_encoded_key(_encode_scalar(value)) == encoded for value in uniques.tolist()),
                    dtype="bool",
                    count=unique_count,
                )
            resolve_special(special_mask, encoded)
        unresolved = unique_states == None  # noqa: E711
        non_finite = unresolved & ~np.isfinite(unique_numbers)
        unique_states[non_finite] = "outlier"
        unique_reasons[non_finite] = "valor_no_finito_no_declarado"
        unique_warnings[non_finite] = "valor_no_finito_no_declarado"
        observed = unresolved & np.isfinite(unique_numbers)
        if observed.any():
            observed_positions = np.flatnonzero(observed)
            bin_positions = np.searchsorted(
                numeric_uppers, unique_numbers[observed], side="right"
            ).astype("int64", copy=False)
            in_range = bin_positions < len(numeric.index)
            selected_positions = observed_positions[in_range]
            selected_bins = bin_positions[in_range]
            lower = prepared.numeric_lowers[selected_bins]
            upper = prepared.numeric_uppers[selected_bins]
            contained = (lower <= unique_numbers[selected_positions]) & (
                unique_numbers[selected_positions] < upper
            )
            accepted = selected_positions[contained]
            accepted_bins = selected_bins[contained]
            unique_states[accepted] = "observed"
            unique_woe[accepted] = prepared.numeric_woe[accepted_bins]
            unique_raw_points[accepted] = prepared.numeric_raw_points[accepted_bins]
            unique_points[accepted] = prepared.numeric_points[accepted_bins]
            unique_bins[accepted] = prepared.numeric_bin_ids[accepted_bins]
            rejected = observed & (unique_states == None)  # noqa: E711
            unique_states[rejected] = "outlier"
            unique_reasons[rejected] = "outlier_sin_politica_congelada"
            unique_warnings[rejected] = "outlier_sin_politica_congelada"
    else:
        for unique_position, value in enumerate(uniques.tolist()):
            matched: pd.Series[Any] | None
            encoded = _encoded_key(_encode_scalar(value))
            if encoded in declared_specials:
                mask = np.zeros(unique_count, dtype="bool")
                mask[unique_position] = True
                resolve_special(mask, encoded)
                continue
            if not numeric.empty:
                if isinstance(value, bool) or not isinstance(value, numbers.Real):
                    raise ScorecardBundleError(
                        f"Dtype incompatible en predictor numérico '{series.name}': "
                        f"{type(value).__name__}."
                    )
                number = float(value)
                if not math.isfinite(number):
                    unique_states[unique_position] = "outlier"
                    unique_reasons[unique_position] = "valor_no_finito_no_declarado"
                    unique_warnings[unique_position] = "valor_no_finito_no_declarado"
                    continue
                bin_position = int(np.searchsorted(numeric_uppers, number, side="right"))
                if bin_position >= len(numeric.index):
                    unique_states[unique_position] = "outlier"
                    unique_reasons[unique_position] = "outlier_sin_politica_congelada"
                    unique_warnings[unique_position] = "outlier_sin_politica_congelada"
                    continue
                matched = numeric.iloc[bin_position]
                if not (float(matched["lower"]) <= number < float(matched["upper"])):
                    unique_states[unique_position] = "outlier"
                    unique_reasons[unique_position] = "outlier_sin_politica_congelada"
                    unique_warnings[unique_position] = "outlier_sin_politica_congelada"
                    continue
            else:
                matched = categorical.get(encoded)
                if matched is None:
                    unique_states[unique_position] = "unseen"
                    unique_reasons[unique_position] = "categoria_no_observada_en_fit"
                    unique_warnings[unique_position] = "categoria_no_observada_en_fit"
                    continue
            unique_states[unique_position] = "observed"
            single = np.zeros(unique_count, dtype="bool")
            single[unique_position] = True
            assign_rule(single, matched)

    valid_codes = codes >= 0
    woe = np.full(row_count, np.nan, dtype="float64")
    raw_points = np.full(row_count, np.nan, dtype="float64")
    points = np.full(row_count, np.nan, dtype="float64")
    bins = np.full(row_count, None, dtype="object")
    states = np.full(row_count, None, dtype="object")
    reasons = np.full(row_count, None, dtype="object")
    warnings = np.full(row_count, None, dtype="object")
    if valid_codes.any():
        selected = codes[valid_codes]
        woe[valid_codes] = unique_woe[selected]
        raw_points[valid_codes] = unique_raw_points[selected]
        points[valid_codes] = unique_points[selected]
        bins[valid_codes] = unique_bins[selected]
        states[valid_codes] = unique_states[selected]
        reasons[valid_codes] = unique_reasons[selected]
        warnings[valid_codes] = unique_warnings[selected]

    missing_mask = ~valid_codes
    if missing_mask.any():
        states[missing_mask] = "missing"
        if missing_rule is not None and bool(missing_rule["supported"]):
            woe[missing_mask] = float(missing_rule["woe"])
            raw_points[missing_mask] = float(missing_rule["raw_points"])
            points[missing_mask] = float(missing_rule["points"])
            bins[missing_mask] = str(missing_rule["bin_id"])
        else:
            reasons[missing_mask] = "missing_sin_soporte_en_fit"
            warnings[missing_mask] = "missing_sin_soporte_en_fit"
    return {
        "woe": woe,
        "raw_points": raw_points,
        "points": points,
        "bin_id": bins,
        "state": states,
        "reason": reasons,
        "warning": warnings,
    }


def _prepare_feature_rules(
    rules: pd.DataFrame,
    *,
    special_values: tuple[Mapping[str, Any], ...],
) -> _PreparedFeatureRules:
    """Compila sólo invariantes del bundle; no conserva estado de una aplicación."""
    special_rules: dict[tuple[str, Any], pd.Series[Any]] = {}
    for _, row in rules.loc[rules["kind"].eq("special")].iterrows():
        for value in json.loads(row["values_json"]):
            special_rules[_encoded_key(value)] = row
    categorical: dict[tuple[str, Any], pd.Series[Any]] = {}
    for _, row in rules.loc[rules["kind"].eq("categorical")].iterrows():
        for value in json.loads(row["values_json"]):
            categorical[_encoded_key(value)] = row
    numeric = rules.loc[rules["kind"].eq("numeric")].sort_values("lower")
    missing_rows = rules.loc[rules["kind"].eq("missing")]
    return _PreparedFeatureRules(
        rules=rules,
        special_rules=special_rules,
        declared_specials=frozenset(_encoded_key(value) for value in special_values),
        categorical=categorical,
        numeric=numeric,
        numeric_lowers=numeric["lower"].to_numpy(dtype="float64", copy=True),
        numeric_uppers=numeric["upper"].to_numpy(dtype="float64", copy=True),
        numeric_woe=numeric["woe"].to_numpy(dtype="float64", copy=True),
        numeric_raw_points=numeric["raw_points"].to_numpy(dtype="float64", copy=True),
        numeric_points=numeric["points"].to_numpy(dtype="float64", copy=True),
        numeric_bin_ids=numeric["bin_id"].to_numpy(dtype="object", copy=True),
        missing_rule=None if missing_rows.empty else missing_rows.iloc[0],
    )


def _match_rule(
    value: Any,
    rules: pd.DataFrame,
) -> tuple[pd.Series[Any] | None, str, str | None]:
    encoded = _encoded_key(_encode_scalar(value))
    special = rules.loc[rules["kind"].eq("special")]
    if not special.empty:
        values = {_encoded_key(item) for item in json.loads(special.iloc[0]["values_json"])}
        if encoded in values:
            row = special.iloc[0]
            if bool(row["supported"]):
                return row, "special", None
            return None, "special", "special_sin_soporte_en_fit"
    if pd.isna(value):
        missing = rules.loc[rules["kind"].eq("missing")]
        if not missing.empty and bool(missing.iloc[0]["supported"]):
            return missing.iloc[0], "missing", None
        return None, "missing", "missing_sin_soporte_en_fit"
    numeric = rules.loc[rules["kind"].eq("numeric")]
    if not numeric.empty:
        number = float(value)
        if not math.isfinite(number):
            return None, "non_finite", "valor_no_finito_no_declarado"
        matched = numeric.loc[(numeric["lower"] <= number) & (number < numeric["upper"])]
        if len(matched.index) == 1:
            return matched.iloc[0], "regular", None
        return None, "outlier", "outlier_sin_politica_congelada"
    categorical = rules.loc[rules["kind"].eq("categorical")]
    for _, row in categorical.iterrows():
        values = {_encoded_key(item) for item in json.loads(row["values_json"])}
        if encoded in values:
            return row, "regular", None
    return None, "unseen", "categoria_no_observada_en_fit"


def _calibrate(eta: float, calibration: Mapping[str, Any]) -> float:
    method = calibration["method"]
    if method == "intercept_offset":
        offset = 0.0 if calibration["offset"] is None else float(calibration["offset"])
        return _expit(eta + offset)
    if method == "platt_scaling":
        slope = float(calibration["slope"])
        intercept = float(calibration["intercept"])
        post_offset = (
            0.0 if calibration["post_offset"] is None else float(calibration["post_offset"])
        )
        return _expit(intercept + slope * eta + post_offset)
    if method == "isotonic":
        knots = calibration["isotonic_knots"]
        if not knots:
            raise ScorecardBundleError("La calibración isotonic no conserva knots.")
        x = np.asarray([pair[0] for pair in knots], dtype="float64")
        y = np.asarray([pair[1] for pair in knots], dtype="float64")
        base = float(np.interp(eta, x, y, left=y[0], right=y[-1]))
        base = min(max(base, np.finfo(float).eps), 1.0 - np.finfo(float).eps)
        post_offset = (
            0.0 if calibration["post_offset"] is None else float(calibration["post_offset"])
        )
        return _expit(math.log(base / (1.0 - base)) + post_offset)
    raise ScorecardBundleError(f"Método de calibración no soportado en bundle: {method!r}.")


def _calibrate_array(
    eta: np.ndarray[Any, Any], calibration: Mapping[str, Any]
) -> np.ndarray[Any, Any]:
    method = calibration["method"]
    if method == "intercept_offset":
        offset = 0.0 if calibration["offset"] is None else float(calibration["offset"])
        return _expit_array(eta + offset)
    if method == "platt_scaling":
        slope = float(calibration["slope"])
        intercept = float(calibration["intercept"])
        post_offset = (
            0.0 if calibration["post_offset"] is None else float(calibration["post_offset"])
        )
        return _expit_array(intercept + slope * eta + post_offset)
    if method == "isotonic":
        knots = calibration["isotonic_knots"]
        if not knots:
            raise ScorecardBundleError("La calibración isotonic no conserva knots.")
        x = np.asarray([pair[0] for pair in knots], dtype="float64")
        y = np.asarray([pair[1] for pair in knots], dtype="float64")
        base = np.interp(eta, x, y, left=y[0], right=y[-1])
        base = np.clip(base, np.finfo(float).eps, 1.0 - np.finfo(float).eps)
        post_offset = (
            0.0 if calibration["post_offset"] is None else float(calibration["post_offset"])
        )
        return _expit_array(np.log(base / (1.0 - base)) + post_offset)
    raise ScorecardBundleError(f"Método de calibración no soportado en bundle: {method!r}.")


def _expit(value: float) -> float:
    if value >= 0.0:
        exp_negative = math.exp(-value)
        return 1.0 / (1.0 + exp_negative)
    exp_positive = math.exp(value)
    return exp_positive / (1.0 + exp_positive)


def _expit_array(values: np.ndarray[Any, Any]) -> np.ndarray[Any, Any]:
    result = np.empty_like(values, dtype="float64")
    positive = values >= 0.0
    result[positive] = 1.0 / (1.0 + np.exp(-values[positive]))
    negative = ~positive
    exponential = np.exp(values[negative])
    result[negative] = exponential / (1.0 + exponential)
    return result


def _limit_score(score: float, minimum: float | None, maximum: float | None) -> float:
    if minimum is not None:
        score = max(score, float(minimum))
    if maximum is not None:
        score = min(score, float(maximum))
    return score


def _read_chunks(
    path: Path,
    *,
    chunk_size: int,
    manifest: Mapping[str, Any],
    id_column: str | None,
) -> Iterator[pd.DataFrame]:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        dtype_map: dict[str, Any] = {}
        parse_dates: list[str] = []
        pandas_dtypes = {
            "int": "Int64",
            "float": "Float64",
            "str": "string",
            "bool": "boolean",
            "category": "category",
        }
        for contract in manifest["input_schema"]["columns"]:
            name = str(contract["name"])
            logical = str(contract["dtype"])
            if logical == "datetime":
                parse_dates.append(name)
            else:
                dtype_map[name] = pandas_dtypes[logical]
        for name, logical in manifest["row_identity"]["unique_key_dtypes"].items():
            if logical == "datetime":
                parse_dates.append(name)
            else:
                dtype_map[name] = pandas_dtypes[logical]
        if id_column is not None:
            identity_dtype = str(manifest["row_identity"]["index_dtype"])
            if identity_dtype == "datetime":
                parse_dates.append(id_column)
            else:
                dtype_map[id_column] = pandas_dtypes[identity_dtype]
        yield from pd.read_csv(
            path,
            chunksize=chunk_size,
            dtype=cast(Any, dtype_map),
            parse_dates=parse_dates or None,
        )
        return
    if suffix in {".parquet", ".pq"}:
        try:
            import pyarrow.parquet as pq
        except ModuleNotFoundError as exc:  # pragma: no cover - dependencia base
            raise ScorecardBundleError("Batch Parquet requiere pyarrow.") from exc
        parquet = pq.ParquetFile(path)  # type: ignore[no-untyped-call]
        if parquet.metadata is None:
            raise ScorecardBundleError("La entrada Parquet no contiene metadata verificable.")
        _validate_batch_rows(parquet.metadata.num_rows)
        for batch in parquet.iter_batches(batch_size=chunk_size):  # type: ignore[no-untyped-call]
            yield batch.to_pandas()
        return
    raise ScorecardBundleError("Batch sólo acepta archivos CSV o Parquet.")


def _validate_rules(value: pd.DataFrame) -> pd.DataFrame:
    if not isinstance(value, pd.DataFrame):
        raise ScorecardBundleError("Las reglas del bundle deben ser un pandas.DataFrame.")
    if tuple(value.columns) != _RULE_COLUMNS:
        raise ScorecardBundleError(
            f"Schema de bins inválido: esperado={_RULE_COLUMNS!r}, "
            f"observado={tuple(value.columns)!r}."
        )
    if value.empty or len(value.index) > _MAX_RULES_ROWS:
        raise ScorecardBundleError("El bundle debe contener entre 1 y 1.000.000 reglas.")
    rules = value.copy(deep=True).reset_index(drop=True)
    if rules["bin_id"].duplicated().any():
        raise ScorecardBundleError("Las reglas contienen bin_id duplicados.")
    if not rules["kind"].isin({"numeric", "categorical", "special", "missing"}).all():
        raise ScorecardBundleError("Las reglas contienen un kind desconocido.")
    for column in ("feature", "woe_column", "bin_id", "kind"):
        if not rules[column].map(lambda item: isinstance(item, str) and bool(item)).all():
            raise ScorecardBundleError(f"Las reglas contienen {column} vacío o no textual.")
    for column in ("woe", "raw_points", "points"):
        numeric = pd.to_numeric(rules[column], errors="coerce").to_numpy(dtype="float64")
        if not np.isfinite(numeric).all():
            raise ScorecardBundleError(f"Las reglas contienen {column} no finito.")
        rules[column] = numeric
    raw_support = pd.to_numeric(rules["support"], errors="raise")
    if (
        not np.isfinite(raw_support.to_numpy(dtype="float64")).all()
        or not (raw_support == np.floor(raw_support)).all()
    ):
        raise ScorecardBundleError("Las reglas contienen soporte no entero o no finito.")
    rules["support"] = raw_support.astype("int64")
    if (rules["support"] < 0).any():
        raise ScorecardBundleError("Las reglas contienen soporte negativo.")
    if not rules["supported"].map(lambda item: isinstance(item, bool | np.bool_)).all():
        raise ScorecardBundleError("supported debe contener booleanos explícitos.")
    rules["supported"] = rules["supported"].astype(bool)
    if not (rules["supported"] == rules["support"].gt(0)).all():
        raise ScorecardBundleError("supported no coincide con support > 0.")
    parsed_values: list[list[Any]] = []
    for raw in rules["values_json"].tolist():
        try:
            parsed = json.loads(raw)
        except (TypeError, json.JSONDecodeError) as exc:
            raise ScorecardBundleError("values_json inválido en reglas.") from exc
        if not isinstance(parsed, list) or _canonical_json(parsed) != raw:
            raise ScorecardBundleError("values_json debe ser una lista JSON canónica.")
        for item in parsed:
            _validate_encoded_scalar(item)
        parsed_values.append(parsed)
    rules["lower"] = pd.to_numeric(rules["lower"], errors="coerce").astype("float64")
    rules["upper"] = pd.to_numeric(rules["upper"], errors="coerce").astype("float64")
    for feature, feature_rules in rules.groupby("feature", sort=False):
        if feature_rules["woe_column"].nunique() != 1:
            raise ScorecardBundleError(f"'{feature}' tiene más de una columna WoE.")
        for auxiliary in ("special", "missing"):
            if int(feature_rules["kind"].eq(auxiliary).sum()) > 1:
                raise ScorecardBundleError(f"'{feature}' tiene más de una regla {auxiliary}.")
        regular_kinds = set(
            feature_rules.loc[feature_rules["kind"].isin({"numeric", "categorical"}), "kind"]
        )
        if len(regular_kinds) != 1:
            raise ScorecardBundleError(f"'{feature}' mezcla o no declara reglas regulares.")
        if regular_kinds == {"numeric"}:
            numeric_rules = feature_rules.loc[feature_rules["kind"].eq("numeric")].sort_values(
                "lower"
            )
            bounds = list(zip(numeric_rules["lower"], numeric_rules["upper"], strict=True))
            if not bounds or bounds[0][0] != -math.inf or bounds[-1][1] != math.inf:
                raise ScorecardBundleError(f"Los bins numéricos de '{feature}' no cubren todo R.")
            if any(lower >= upper for lower, upper in bounds) or any(
                left[1] != right[0] for left, right in pairwise(bounds)
            ):
                raise ScorecardBundleError(
                    f"Los bins numéricos de '{feature}' tienen gaps/solapes."
                )
        else:
            seen: set[tuple[str, Any]] = set()
            for index in feature_rules.index[feature_rules["kind"].eq("categorical")]:
                values = parsed_values[int(index)]
                encoded = {_encoded_key(item) for item in values}
                if not encoded or seen.intersection(encoded):
                    raise ScorecardBundleError(
                        f"Los bins categóricos de '{feature}' están vacíos o se solapan."
                    )
                seen.update(encoded)
    return rules


def _validate_rule_mapping(manifest: Mapping[str, Any], rules: pd.DataFrame) -> None:
    features = tuple(str(value) for value in manifest["model"]["features"])
    observed = tuple(dict.fromkeys(str(value) for value in rules["feature"].tolist()))
    if observed != features:
        raise ScorecardBundleError(
            f"Las reglas no reconcilian con las features del modelo: {observed!r} != {features!r}."
        )
    expected_woe = dict(zip(features, manifest["model"]["woe_columns"], strict=True))
    observed_woe = {
        str(feature): str(group["woe_column"].iloc[0])
        for feature, group in rules.groupby("feature", sort=False)
    }
    if observed_woe != expected_woe:
        raise ScorecardBundleError("Las reglas no reconcilian con el mapping feature/WoE.")
    catalog = manifest["special_catalog"]
    handling = manifest["treatment_policy"]["special_handling"]
    for feature in features:
        declared = tuple(catalog.get(feature, ()))
        special_rows = rules.loc[rules["feature"].eq(feature) & rules["kind"].eq("special")]
        frozen = tuple(
            item for raw in special_rows["values_json"].tolist() for item in json.loads(raw)
        )
        if len({_encoded_key(item) for item in frozen}) != len(frozen):
            raise ScorecardBundleError(
                f"Las reglas special de '{feature}' contienen sentinels duplicados."
            )
        if handling == "separate":
            if {_encoded_key(item) for item in frozen} != {_encoded_key(item) for item in declared}:
                raise ScorecardBundleError(
                    f"special_catalog no reconcilia con las reglas congeladas de '{feature}'."
                )
        elif frozen:
            raise ScorecardBundleError(
                f"'{feature}' conserva reglas special incompatibles con as_missing."
            )
        if handling == "as_missing" and declared:
            missing = rules.loc[rules["feature"].eq(feature) & rules["kind"].eq("missing")]
            if missing.empty:
                raise ScorecardBundleError(
                    f"'{feature}' declara special as_missing sin bin missing congelado."
                )


def _validate_inference_contracts(value: Mapping[str, Any], features: list[str]) -> None:
    schema = value.get("input_schema")
    if not isinstance(schema, dict) or set(schema) != {"columns", "extra_columns"}:
        raise ScorecardBundleError("Schema de input_schema inválido.")
    columns = schema["columns"]
    if (
        not isinstance(columns, list)
        or [item.get("name") for item in columns if isinstance(item, dict)] != features
    ):
        raise ScorecardBundleError("input_schema no reconcilia con las features del modelo.")
    allowed_dtypes = {"int", "float", "str", "bool", "category", "datetime"}
    for column in columns:
        if (
            not isinstance(column, dict)
            or set(column) != {"name", "dtype", "nullable", "coerce"}
            or column["dtype"] not in allowed_dtypes
            or not isinstance(column["nullable"], bool)
            or not isinstance(column["coerce"], bool)
        ):
            raise ScorecardBundleError("input_schema.columns contiene una regla inválida.")
    if schema["extra_columns"] not in {"allow", "filter", "forbid"}:
        raise ScorecardBundleError("input_schema.extra_columns es inválido.")
    identity = value.get("row_identity")
    if (
        not isinstance(identity, dict)
        or set(identity)
        != {"index_name", "index_dtype", "unique_keys", "unique_key_dtypes", "null_policy"}
        or identity["index_dtype"] not in allowed_dtypes
        or not isinstance(identity["unique_keys"], list)
        or not all(isinstance(item, str) and item for item in identity["unique_keys"])
        or len(identity["unique_keys"]) != len(set(identity["unique_keys"]))
        or not isinstance(identity["unique_key_dtypes"], dict)
        or set(identity["unique_key_dtypes"]) != set(identity["unique_keys"])
        or not all(dtype in allowed_dtypes for dtype in identity["unique_key_dtypes"].values())
        or identity["null_policy"] != "forbid"
    ):
        raise ScorecardBundleError("Schema de row_identity inválido.")
    treatment = value.get("treatment_policy")
    treatment_keys = {"special_handling", "missing", "unseen", "outlier", "non_finite"}
    if (
        not isinstance(treatment, dict)
        or set(treatment) != treatment_keys
        or treatment["special_handling"] not in {"separate", "as_missing"}
        or treatment["missing"] != "frozen_bin_or_not_scorable"
        or treatment["unseen"] != "not_scorable"
        or treatment["outlier"] != "frozen_support_or_not_scorable"
        or treatment["non_finite"] != "declared_special_or_not_scorable"
    ):
        raise ScorecardBundleError("Schema de treatment_policy inválido.")
    catalog = value.get("special_catalog")
    if not isinstance(catalog, dict) or not set(catalog).issubset(features):
        raise ScorecardBundleError("Schema de special_catalog inválido.")
    for feature, sentinels in catalog.items():
        if not isinstance(sentinels, list):
            raise ScorecardBundleError(f"special_catalog de '{feature}' es inválido.")
        for sentinel in sentinels:
            _validate_encoded_scalar(sentinel)
        if len({_encoded_key(item) for item in sentinels}) != len(sentinels):
            raise ScorecardBundleError(f"special_catalog de '{feature}' es inválido o duplicado.")


def _validate_manifest(value: Any, *, require_files: bool) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ScorecardBundleError("manifest.json debe contener un objeto JSON.")
    required = {
        "schema_version",
        "format",
        "input_schema",
        "row_identity",
        "treatment_policy",
        "special_catalog",
        "model",
        "fit_lineage",
        "rules_sha256",
        "files",
        "bundle_hash",
    }
    if set(value) != required:
        raise ScorecardBundleError(
            f"Claves de manifest inválidas: faltan={sorted(required - set(value))}, "
            f"sobran={sorted(set(value) - required)}."
        )
    if value["schema_version"] != _BUNDLE_SCHEMA or value["format"] != "nikodym.scorecard.bundle":
        raise ScorecardBundleError("Schema o formato de bundle no soportado.")
    for field in ("rules_sha256", "bundle_hash"):
        if not _is_sha256(value[field]):
            raise ScorecardBundleError(f"{field} no es un SHA-256 hexadecimal.")
    files = value["files"]
    if not isinstance(files, dict):
        raise ScorecardBundleError("manifest.files debe ser un objeto.")
    if require_files:
        if set(files) != {"bins.parquet"} or not _is_sha256(files.get("bins.parquet")):
            raise ScorecardBundleError("manifest.files no ancla bins.parquet correctamente.")
    elif files and (set(files) != {"bins.parquet"} or not _is_sha256(files.get("bins.parquet"))):
        raise ScorecardBundleError("manifest.files contiene una entrada inválida.")
    model = value["model"]
    model_keys = {
        "features",
        "woe_columns",
        "intercept",
        "beta",
        "score_column",
        "score_direction",
        "rounding_method",
        "min_score",
        "max_score",
        "calibration",
    }
    if not isinstance(model, dict) or set(model) != model_keys:
        raise ScorecardBundleError("Schema de manifest.model inválido.")
    features = model["features"]
    woe_columns = model["woe_columns"]
    if (
        not isinstance(features, list)
        or not features
        or len(features) != len(set(features))
        or not isinstance(woe_columns, list)
        or len(features) != len(woe_columns)
        or set(model["beta"]) != set(features)
    ):
        raise ScorecardBundleError("Mapping feature/WoE/beta inválido en manifest.model.")
    if (
        not all(isinstance(feature, str) and feature for feature in features)
        or not all(isinstance(column, str) and column for column in woe_columns)
        or len(set(woe_columns)) != len(woe_columns)
        or not _is_finite_number(model["intercept"])
        or not all(_is_finite_number(beta) for beta in model["beta"].values())
    ):
        raise ScorecardBundleError("Parámetros numéricos o nombres inválidos en manifest.model.")
    if model["score_direction"] not in {
        "higher_is_lower_risk",
        "higher_is_higher_risk",
    } or model["rounding_method"] not in {
        "none",
        "nearest_integer",
        "floor_integer",
        "ceil_integer",
    }:
        raise ScorecardBundleError("Dirección o redondeo inválido en manifest.model.")
    _validate_inference_contracts(value, features)
    minimum, maximum = model["min_score"], model["max_score"]
    if minimum is not None and not _is_finite_number(minimum):
        raise ScorecardBundleError("min_score debe ser finito o null.")
    if maximum is not None and not _is_finite_number(maximum):
        raise ScorecardBundleError("max_score debe ser finito o null.")
    if minimum is not None and maximum is not None and float(minimum) > float(maximum):
        raise ScorecardBundleError("min_score no puede exceder max_score.")
    try:
        from nikodym.calibration.results import CalibrationParameters

        model["calibration"] = CalibrationParameters.model_validate(
            model["calibration"]
        ).model_dump(mode="json")
    except Exception as exc:
        raise ScorecardBundleError(f"Calibración inválida en manifest.model: {exc}.") from exc
    lineage = value["fit_lineage"]
    lineage_keys = {
        "git_sha",
        "git_dirty",
        "data_hash",
        "config_hash",
        "root_seed",
        "uv_lock_hash",
        "runtime_environment_hash",
        "installed_distribution_hash",
        "library_versions",
        "determinism_caveats",
        "injected_artifacts",
    }
    if not isinstance(lineage, dict) or set(lineage) != lineage_keys:
        raise ScorecardBundleError("Schema de fit_lineage inválido.")
    for hash_field in (
        "data_hash",
        "config_hash",
        "uv_lock_hash",
        "runtime_environment_hash",
        "installed_distribution_hash",
    ):
        if not _is_sha256(lineage[hash_field]):
            raise ScorecardBundleError(f"fit_lineage.{hash_field} no es SHA-256.")
    _canonical_json(value)
    return cast("dict[str, Any]", json.loads(_canonical_json(value)))


def _is_finite_number(value: Any) -> bool:
    return (
        isinstance(value, numbers.Real)
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    )


def _rules_hash(rules: pd.DataFrame) -> str:
    records = []
    for row in rules.loc[:, list(_RULE_COLUMNS)].to_dict(orient="records"):
        records.append(
            {
                key: (
                    _json_number(value)
                    if key in {"lower", "upper", "woe", "raw_points", "points"}
                    else value
                )
                for key, value in row.items()
            }
        )
    return hashlib.sha256(_canonical_json(records).encode()).hexdigest()


def _bundle_hash(manifest: Mapping[str, Any]) -> str:
    semantic = {
        key: value for key, value in manifest.items() if key not in {"bundle_hash", "files"}
    }
    return hashlib.sha256(_canonical_json(semantic).encode()).hexdigest()


def _row_hashes(frame: pd.DataFrame) -> np.ndarray[Any, Any]:
    """Ancla filas en orden de entrada con dos hashes vectorizados y un SHA-256 final."""
    from pandas.util import hash_pandas_object

    columns = sorted(frame.columns)
    canonical = frame.loc[:, columns]
    forward = hash_pandas_object(
        canonical,
        index=True,
        encoding="utf8",
        hash_key="0123456789123456",
        categorize=True,
    ).to_numpy(dtype="<u8", copy=True)
    reverse = hash_pandas_object(
        canonical.loc[:, list(reversed(columns))],
        index=True,
        encoding="utf8",
        hash_key="6543210987654321",
        categorize=True,
    ).to_numpy(dtype="<u8", copy=True)
    schema = hashlib.sha256(
        _canonical_json(
            {
                "columns": columns,
                "dtypes": [str(canonical[column].dtype) for column in columns],
            }
        ).encode()
    ).digest()
    prefix = b"nikodym.scorecard.input-row.v1\0" + schema
    return np.asarray(
        [
            hashlib.sha256(prefix + struct.pack("<QQ", int(left), int(right))).hexdigest()
            for left, right in zip(forward, reverse, strict=True)
        ],
        dtype="object",
    )


def _trace_hashes(trace: pd.DataFrame, *, rows: int) -> np.ndarray[Any, Any]:
    """Resume cada traza feature-ordenada en 128 bits, sin bucles por observación."""
    from pandas.util import hash_pandas_object

    columns = [
        "feature_position",
        "feature",
        "raw_value",
        "raw_state",
        "rule",
        "bin_id",
        "woe",
        "transformed_value",
        "raw_points",
        "points",
        "reason",
        "warning_code",
    ]
    width = 0 if rows == 0 else len(trace.index) // rows
    if width < 1 or rows * width != len(trace.index):
        raise ScorecardBundleError("La traza no reconcilia filas por feature.")
    forward = hash_pandas_object(
        trace.loc[:, columns],
        index=False,
        encoding="utf8",
        hash_key="0123456789123456",
        categorize=True,
    ).to_numpy(dtype="<u8", copy=False)
    ordered = forward.reshape(rows, width)
    prefix = b"nikodym.scorecard.treatment-trace.v1\0"
    return np.asarray(
        [hashlib.sha256(prefix + row.tobytes()).hexdigest() for row in ordered],
        dtype="object",
    )


def _update_frame_digest(
    digest: Any,
    frame: pd.DataFrame,
    columns: tuple[str, ...],
) -> None:
    """Alimenta un digest continuo con filas lógicas, independiente del corte de chunks."""
    from pandas.util import hash_pandas_object

    canonical = frame.loc[:, list(columns)].copy(deep=False)
    for column in canonical.select_dtypes(include="object").columns:
        if canonical[column].map(lambda value: isinstance(value, list | dict | tuple)).any():
            canonical[column] = canonical[column].map(
                lambda value: (
                    _canonical_json(value) if isinstance(value, list | dict | tuple) else value
                )
            )
    row_hashes = hash_pandas_object(
        canonical,
        index=False,
        encoding="utf8",
        hash_key="0123456789123456",
        categorize=True,
    ).to_numpy(dtype="<u8", copy=True)
    digest.update(row_hashes.tobytes())


def _row_hash(input_id: Any, row: pd.Series[Any]) -> str:
    payload = {
        "index": _encode_scalar(input_id),
        "values": {str(column): _encode_scalar(row[column]) for column in sorted(row.index)},
    }
    return hashlib.sha256(_canonical_json(payload).encode()).hexdigest()


def _encode_scalar(value: Any) -> dict[str, Any]:
    if hasattr(value, "item") and not isinstance(value, (str, bytes)):
        with suppress(TypeError, ValueError):
            value = value.item()
    if value is None or value is pd.NA or (isinstance(value, float) and math.isnan(value)):
        return {"type": "null", "value": None}
    if isinstance(value, bool):
        return {"type": "bool", "value": value}
    if isinstance(value, numbers.Integral):
        return {"type": "int", "value": int(value)}
    if isinstance(value, numbers.Real):
        number = float(value)
        if math.isinf(number):
            return {"type": "float", "value": "+inf" if number > 0 else "-inf"}
        return {"type": "float", "value": _json_number(number)}
    if isinstance(value, str):
        return {"type": "str", "value": value}
    if isinstance(value, bytes):
        return {"type": "bytes_hex", "value": value.hex()}
    if hasattr(value, "isoformat"):
        return {"type": type(value).__name__, "value": value.isoformat()}
    return {"type": type(value).__name__, "value": str(value)}


def _json_number(value: Any) -> float | str:
    number = float(value)
    if math.isnan(number):
        return "nan"
    if math.isinf(number):
        return "+inf" if number > 0 else "-inf"
    return 0.0 if number == 0.0 else number


def _encoded_key(value: Mapping[str, Any]) -> tuple[str, Any]:
    """Compara int/float por valor numérico sin colapsarlos con strings o bool."""
    kind = value.get("type")
    raw = value.get("value")
    if kind in {"int", "float"} and isinstance(raw, int | float):
        return ("number", float(raw))
    return (str(kind), _canonical_json(raw))


def _validate_encoded_scalar(value: Any) -> None:
    """Valida el codec cerrado usado por catálogo y reglas, sin ejecutar tipos arbitrarios."""
    if not isinstance(value, dict) or set(value) != {"type", "value"}:
        raise ScorecardBundleError("Valor escalar codificado con schema inválido.")
    kind = value["type"]
    raw = value["value"]
    valid = (
        (kind == "null" and raw is None)
        or (kind == "bool" and isinstance(raw, bool))
        or (kind == "int" and isinstance(raw, int) and not isinstance(raw, bool))
        or (
            kind == "float"
            and (
                (isinstance(raw, int | float) and not isinstance(raw, bool))
                or (isinstance(raw, str) and raw in {"+inf", "-inf"})
            )
        )
        or (kind == "str" and isinstance(raw, str))
        or (
            kind == "bytes_hex"
            and isinstance(raw, str)
            and len(raw) % 2 == 0
            and all(char in "0123456789abcdef" for char in raw)
        )
        or (kind in {"date", "datetime", "Timestamp"} and isinstance(raw, str) and bool(raw))
    )
    if not valid:
        raise ScorecardBundleError("Valor escalar codificado inválido o no canónico.")
    try:
        decoded = _decode_scalar(value)
    except (TypeError, ValueError) as exc:
        raise ScorecardBundleError("Valor escalar codificado inválido o no canónico.") from exc
    round_trip = _canonical_json(value) == _canonical_json(_encode_scalar(decoded))
    if not round_trip:
        raise ScorecardBundleError("Valor escalar codificado inválido o no canónico.")


def _decode_scalar(value: Mapping[str, Any]) -> Any:
    kind = value["type"]
    raw = value["value"]
    if kind == "null":
        return None
    if kind == "float" and raw in {"+inf", "-inf"}:
        return math.inf if raw == "+inf" else -math.inf
    if kind == "bytes_hex":
        return bytes.fromhex(str(raw))
    if kind == "date":
        return date.fromisoformat(str(raw))
    if kind == "datetime":
        return datetime.fromisoformat(str(raw))
    if kind == "Timestamp":
        timestamp = pd.Timestamp(str(raw))
        if pd.isna(timestamp):
            raise ValueError("Timestamp no puede ser NaT")
        return timestamp
    return raw


def _canonical_json(value: Any) -> str:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise ScorecardBundleError(f"Valor no serializable de forma canónica: {exc}.") from exc


def _write_canonical_json_file(path: Path, value: Any) -> None:
    """Escribe JSON canónico con LF físico, independiente de la plataforma."""
    path.write_bytes((_canonical_json(value) + "\n").encode("utf-8"))


def _is_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()
