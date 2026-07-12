"""Paso orquestable de la capa ``binning`` (SDD-06 §4/§6/§7; CT-1).

``BinningStep`` implementa el :class:`~nikodym.core.steps.Step` nativo del dominio
``binning``: lee los artefactos publicados por ``data``, ajusta ``WoEBinner`` sólo sobre
Desarrollo, transforma las particiones modelables y publica tablas WoE/IV, frame WoE y resumen de
model card bajo el dominio ``binning``.

El módulo evita importar ``pandas``, ``sklearn`` y ``optbinning`` en import time.
``nikodym.binning`` lo importa para ejecutar ``@register("standard", domain="binning")`` sin
contaminar el núcleo liviano; las dependencias tabulares y de scoring se cargan dentro de
``execute``.

**Estable (SemVer 1.x).**
"""

from __future__ import annotations

import importlib
from importlib import metadata
from typing import TYPE_CHECKING, Any, Final, Literal, TypeAlias, cast

from nikodym.binning.config import BinningConfig, VariableBinningConfig
from nikodym.binning.exceptions import BinningFitError
from nikodym.core.mixins import AuditableMixin
from nikodym.core.registry import register
from nikodym.core.steps import ArtifactKey

if TYPE_CHECKING:
    import numpy as np
    import pandas as pd

    from nikodym.binning.results import BinningCardSection, BinningResult
    from nikodym.binning.transformer import WoEBinner
    from nikodym.core.study import Study
    from nikodym.data.partition import PartitionResult
    from nikodym.data.special import MaskedFrame
    from nikodym.data.target import LabeledFrame

    DataFrame: TypeAlias = pd.DataFrame
    Series: TypeAlias = pd.Series
else:
    DataFrame: TypeAlias = Any
    Series: TypeAlias = Any

__all__ = ["BINNING_ARTIFACTS", "BinningStep"]

BINNING_ARTIFACTS: Final[tuple[str, ...]] = (
    "process",
    "tables",
    "summary",
    "woe_frame",
    "result",
    "binning_card",
)
_MODEL_PARTITIONS: Final[frozenset[str]] = frozenset({"desarrollo", "holdout", "oot"})
_AUTO_MONOTONIC_TRENDS: Final[frozenset[str]] = frozenset(
    {"auto", "auto_heuristic", "auto_asc_desc"}
)
_NUMERICAL_DTYPES: Final[frozenset[str]] = frozenset({"numerical", "categorical"})
_OPTIMAL_STATUS: Final = "OPTIMAL"


@register("standard", domain="binning")
class BinningStep(AuditableMixin):
    """Orquesta binning supervisado WoE/IV y publica artefactos ``domain='binning'``."""

    name: str = "binning"
    requires: tuple[ArtifactKey, ...] = (
        ("data", "frame"),
        ("data", "labels"),
        ("data", "splits"),
        ("data", "special"),
    )
    provides: tuple[ArtifactKey, ...] = tuple(("binning", key) for key in BINNING_ARTIFACTS)

    def __init__(self, config: BinningConfig) -> None:
        """Construye el paso desde la sección ``BinningConfig`` ya validada."""
        self.config = config

    @classmethod
    def from_config(cls, cfg: BinningConfig) -> BinningStep:
        """Construye ``BinningStep`` desde ``NikodymConfig.binning``."""
        return cls(cfg)

    def execute(self, study: Study, rng: np.random.Generator) -> BinningResult:
        """Ejecuta fit en Desarrollo y transform determinista sin consumir ``rng``.

        ``rng`` se recibe por el protocolo homogéneo de ``Step``; binning v1 no introduce muestreo
        ni azar propio. La reproducibilidad depende de la matriz fija de datos/config/OptBinning.
        """
        del rng
        pd = _import_pandas()

        frame = _as_dataframe(study.artifacts.get("data", "frame"), pd).copy(deep=True)
        labels = _as_labeled_frame(study.artifacts.get("data", "labels"))
        splits = _as_partition_result(study.artifacts.get("data", "splits"))
        special = _as_masked_frame(study.artifacts.get("data", "special"))

        target_col = labels.target_col
        status_col = labels.status_col
        partition_col = splits.partition_col
        ttd_col = splits.ttd_col
        _validate_required_columns(frame, (target_col, status_col, partition_col, ttd_col))

        feature_columns = _resolve_feature_columns(
            frame=frame,
            target_col=target_col,
            status_col=status_col,
            partition_col=partition_col,
            ttd_col=ttd_col,
            config=self.config,
            data_config=getattr(study.config, "data", None),
            pd=pd,
        )
        train_mask = _training_mask(frame, target_col, partition_col)
        y_train = cast(Series, frame.loc[train_mask, target_col].copy(deep=True))
        _validate_training_target(y_train)

        eligible_mask = _modelable_mask(frame, partition_col)
        x_train = frame.loc[train_mask, list(feature_columns)].copy(deep=True)
        x_transform = frame.loc[eligible_mask, list(feature_columns)].copy(deep=True)

        self._log_special_policy(special=special, feature_columns=feature_columns)
        binner = _build_binner(self.config, feature_columns)
        binner.fit(x_train, y_train, special=special)
        woe_only = binner.transform(x_transform)
        woe_frame = _assemble_woe_frame(
            source=frame,
            eligible_mask=eligible_mask,
            woe_only=woe_only,
            structural_columns=(target_col, status_col, partition_col, ttd_col),
            keep_structural_columns=self.config.keep_structural_columns,
            pd=pd,
        )
        tables = _copy_tables(binner.tables_)
        summary = _summary_with_fresh_iv_band(binner.summary_, pd)
        variable_summaries = _variable_summaries(summary, pd)

        result, binning_card = _build_results(
            woe_frame=woe_frame,
            tables=tables,
            summary=summary,
            variable_summaries=variable_summaries,
            binner=binner,
            config=self.config,
        )
        self._log_binning_decisions(
            binner=binner,
            summary=summary,
            feature_columns=feature_columns,
            pd=pd,
        )
        self._publish_artifacts(study, binner, tables, summary, woe_frame, result, binning_card)
        return result

    def _log_special_policy(
        self,
        *,
        special: MaskedFrame,
        feature_columns: tuple[str, ...],
    ) -> None:
        """Registra el tratamiento de special values declarado para variables candidatas."""
        for column in feature_columns:
            codes = special.special_catalog.get(column, [])
            if not codes:
                continue
            mask = special.special_mask[column] if column in special.special_mask.columns else None
            count = int(mask.fillna(False).astype("bool").sum()) if mask is not None else 0
            action = (
                "separar_special"
                if self.config.special_handling == "separate"
                else "tratar_como_missing"
            )
            self.log_decision(
                regla="special_values",
                umbral=self.config.special_handling,
                valor={"variable": column, "conteo": count, "codigos": list(codes)},
                accion=action,
            )

    def _log_binning_decisions(
        self,
        *,
        binner: WoEBinner,
        summary: DataFrame,
        feature_columns: tuple[str, ...],
        pd: Any,
    ) -> None:
        """Registra decisiones auditables derivadas de los atributos fiteados del binner."""
        self._log_skipped_variables(binner.skipped_variables_)
        self._log_monotonicity_overrides(feature_columns)
        self._log_monotonicity_auto_resolved(feature_columns, summary)
        self._log_summary_diagnostics(summary, pd)
        self._log_unknown_categories(binner.unknown_categories_)

    def _log_skipped_variables(self, skipped: dict[str, str]) -> None:
        """Registra variables omitidas por casos borde o status del solver."""
        for variable, reason in skipped.items():
            if reason == "constant":
                self.log_decision(
                    regla="variable_constante",
                    umbral="nunique_non_missing>1",
                    valor={"variable": variable, "razon": reason},
                    accion="omitir_variable",
                )
            elif reason == "all_missing":
                self.log_decision(
                    regla="variable_all_missing",
                    umbral="missing_rate<1",
                    valor={"variable": variable, "razon": reason},
                    accion="omitir_variable",
                )
            elif reason == "single_class":
                self.log_decision(
                    regla="variable_single_class",
                    umbral="ambas_clases",
                    valor={"variable": variable, "razon": reason},
                    accion="omitir_variable",
                )
            elif reason.startswith("solver_status:"):
                status = reason.split(":", maxsplit=1)[1]
                self.log_decision(
                    regla="solver_no_optimo",
                    umbral=_OPTIMAL_STATUS,
                    valor={"variable": variable, "status": status},
                    accion="omitir_variable",
                )

    def _log_monotonicity_overrides(self, feature_columns: tuple[str, ...]) -> None:
        """Registra monotonía forzada global o por variable."""
        override_by_name = {override.name: override for override in self.config.variable_overrides}
        for variable in feature_columns:
            override = override_by_name.get(variable)
            trend = _effective_forced_trend(self.config, override)
            if trend is None:
                continue
            self.log_decision(
                regla="monotonia_forzada",
                umbral="auto",
                valor={"variable": variable, "monotonic_trend": trend},
                accion="aplicar_restriccion",
            )

    def _log_monotonicity_auto_resolved(
        self,
        feature_columns: tuple[str, ...],
        summary: DataFrame,
    ) -> None:
        """Registra la tendencia AUTO-RESUELTA por variable cuando el modo es automático.

        En modo ``auto*`` OptBinning no fuerza una dirección explícita, así que el log de decisiones
        quedaba mudo sobre monotonía en la ruta por defecto. Nikodym deriva la dirección real de los
        bins ajustados (``WoEBinner``) y aquí la registra por variable, etiquetada HONESTO como
        ``monotonia_auto_resuelta`` (no fue forzada, por eso no es ``monotonia_forzada``).
        """
        override_by_name = {override.name: override for override in self.config.variable_overrides}
        resolved = _resolved_trends_by_variable(summary)
        for variable in feature_columns:
            mode = _effective_monotonic_mode(self.config, override_by_name.get(variable))
            if mode not in _AUTO_MONOTONIC_TRENDS:
                continue
            trend = resolved.get(variable)
            if trend is None:
                continue
            self.log_decision(
                regla="monotonia_auto_resuelta",
                umbral=mode,
                valor={"variable": variable, "monotonic_trend": trend},
                accion="registrar_tendencia",
            )

    def _log_summary_diagnostics(self, summary: DataFrame, pd: Any) -> None:
        """Registra IV bajo/sospechoso y bins efectivos menores al máximo solicitado."""
        override_by_name = {override.name: override for override in self.config.variable_overrides}
        for row in summary.to_dict(orient="records"):
            if not bool(row.get("selected", False)):
                continue
            variable = str(row["name"])
            iv = float(row["iv"])
            n_bins = int(row["n_bins"])
            max_n_bins = _effective_max_n_bins(self.config, override_by_name.get(variable))
            if max_n_bins is not None and 0 < n_bins < max_n_bins:
                self.log_decision(
                    regla="bins_colapsados",
                    umbral=max_n_bins,
                    valor={"variable": variable, "n_bins": n_bins},
                    accion="conservar_variable",
                )
            if iv > 0.50:
                self.log_decision(
                    regla="iv_sospechoso",
                    umbral=0.50,
                    valor={"variable": variable, "iv": iv},
                    accion="diagnosticar_sin_eliminar",
                )
            elif iv < 0.02:
                self.log_decision(
                    regla="iv_bajo",
                    umbral=0.02,
                    valor={"variable": variable, "iv": iv},
                    accion="diagnosticar_sin_eliminar",
                )
        del pd

    def _log_unknown_categories(self, unknown_categories: dict[str, int]) -> None:
        """Registra categorías no vistas durante la transformación WoE."""
        for variable, count in unknown_categories.items():
            if count <= 0:
                continue
            self.log_decision(
                regla="categoria_no_vista",
                umbral=0,
                valor={"variable": variable, "conteo": count},
                accion="asignar_woe_neutral",
            )

    def _publish_artifacts(
        self,
        study: Study,
        process: WoEBinner,
        tables: dict[str, DataFrame],
        summary: DataFrame,
        woe_frame: DataFrame,
        result: BinningResult,
        binning_card: BinningCardSection,
    ) -> None:
        """Publica los seis artefactos estables del dominio ``binning``."""
        study.artifacts.set("binning", "process", process)
        study.artifacts.set("binning", "tables", tables)
        study.artifacts.set("binning", "summary", summary)
        study.artifacts.set("binning", "woe_frame", woe_frame)
        study.artifacts.set("binning", "result", result)
        study.artifacts.set("binning", "binning_card", binning_card)


def _import_pandas() -> Any:
    """Importa ``pandas`` localmente para preservar el import liviano del paquete."""
    return importlib.import_module("pandas")


def _as_dataframe(value: object, pd: Any) -> DataFrame:
    """Valida el artefacto ``data.frame`` antes de leerlo."""
    if isinstance(value, pd.DataFrame):
        return cast(DataFrame, value)
    raise BinningFitError(
        "El artefacto ('data', 'frame') debe ser un pandas.DataFrame; "
        f"tipo observado={type(value).__name__}."
    )


def _as_labeled_frame(value: object) -> LabeledFrame:
    """Valida el artefacto ``data.labels`` con import local de ``data``."""
    from nikodym.data.target import LabeledFrame

    if isinstance(value, LabeledFrame):
        return value
    raise BinningFitError(
        "El artefacto ('data', 'labels') debe ser un LabeledFrame; "
        f"tipo observado={type(value).__name__}."
    )


def _as_partition_result(value: object) -> PartitionResult:
    """Valida el artefacto ``data.splits`` con import local de ``data``."""
    from nikodym.data.partition import PartitionResult

    if isinstance(value, PartitionResult):
        return value
    raise BinningFitError(
        "El artefacto ('data', 'splits') debe ser un PartitionResult; "
        f"tipo observado={type(value).__name__}."
    )


def _as_masked_frame(value: object) -> MaskedFrame:
    """Valida el artefacto ``data.special`` con import local de ``data``."""
    from nikodym.data.special import MaskedFrame

    if isinstance(value, MaskedFrame):
        return value
    raise BinningFitError(
        "El artefacto ('data', 'special') debe ser un MaskedFrame; "
        f"tipo observado={type(value).__name__}."
    )


def _validate_required_columns(frame: DataFrame, columns: tuple[str, ...]) -> None:
    """Falla con una lista completa si faltan columnas estructurales en ``data.frame``."""
    missing = [column for column in columns if column not in frame.columns]
    if missing:
        joined = ", ".join(f"'{column}'" for column in missing)
        raise BinningFitError(
            f"data.frame no contiene columnas estructurales requeridas: {joined}."
        )


def _resolve_feature_columns(
    *,
    frame: DataFrame,
    target_col: str,
    status_col: str,
    partition_col: str,
    ttd_col: str,
    config: BinningConfig,
    data_config: object,
    pd: Any,
) -> tuple[str, ...]:
    """Resuelve variables candidatas de binning preservando el orden del frame."""
    exclusions = _structural_columns(target_col, status_col, partition_col, ttd_col)
    exclusions.update(_data_temporal_columns(data_config))
    exclusions.update(_datetime_columns(frame, pd))
    exclusions.update(config.exclude_columns)

    if config.feature_columns == "*":
        columns = tuple(str(column) for column in frame.columns if str(column) not in exclusions)
    else:
        missing = [column for column in config.feature_columns if column not in frame.columns]
        if missing:
            joined = ", ".join(f"'{column}'" for column in missing)
            raise BinningFitError(
                f"BinningConfig.feature_columns declara columna(s) inexistente(s): {joined}."
            )
        columns = tuple(column for column in config.feature_columns if column not in exclusions)

    if not columns:
        raise BinningFitError(
            "No hay columnas candidatas para binning tras excluir estructurales, fechas/cohortes "
            "y exclude_columns."
        )
    return columns


def _structural_columns(
    target_col: str,
    status_col: str,
    partition_col: str,
    ttd_col: str,
) -> set[str]:
    """Devuelve el conjunto de columnas estructurales de ``data``."""
    return {
        target_col,
        status_col,
        partition_col,
        ttd_col,
        "target",
        "label_status",
        "partition",
        "ttd",
    }


def _data_temporal_columns(data_config: object) -> set[str]:
    """Extrae columnas de fecha/cohorte declaradas en ``DataConfig`` si están disponibles."""
    columns: set[str] = set()
    target = _get_config_attr(data_config, "target")
    window = _get_config_attr(target, "window")
    columns.update(_present_strings(_get_config_attr(window, "observation_date_col")))
    columns.update(_present_strings(_get_config_attr(window, "data_cutoff_col")))

    partition = _get_config_attr(data_config, "partition")
    strategy = _get_config_attr(partition, "strategy")
    columns.update(_present_strings(_get_config_attr(strategy, "date_col")))
    columns.update(_present_strings(_get_config_attr(strategy, "cohort_col")))
    return columns


def _get_config_attr(obj: object, name: str) -> object:
    """Lee atributos o claves de un sub-config que puede ser Pydantic o dict opaco."""
    if obj is None:
        return None
    if isinstance(obj, dict):
        return obj.get(name)
    return getattr(obj, name, None)


def _present_strings(value: object) -> set[str]:
    """Normaliza un valor opcional a conjunto de strings no vacíos."""
    if isinstance(value, str) and value:
        return {value}
    return set()


def _datetime_columns(frame: DataFrame, pd: Any) -> set[str]:
    """Detecta columnas datetime del frame para excluirlas de ``feature_columns='*'``."""
    return {
        str(column)
        for column in frame.columns
        if pd.api.types.is_datetime64_any_dtype(frame[column].dtype)
    }


def _training_mask(frame: DataFrame, target_col: str, partition_col: str) -> Series:
    """Selecciona Desarrollo con target no nulo para el fit anti-leakage."""
    partition = frame[partition_col].astype("string")
    mask = partition.eq("desarrollo") & frame[target_col].notna()
    return cast(Series, mask.fillna(False).astype("bool"))


def _modelable_mask(frame: DataFrame, partition_col: str) -> Series:
    """Selecciona las particiones elegibles para transformar a WoE."""
    mask = frame[partition_col].astype("string").isin(_MODEL_PARTITIONS)
    return cast(Series, mask.fillna(False).astype("bool"))


def _validate_training_target(y_train: Series) -> None:
    """Valida target 0/1 con ambas clases antes de llamar a OptBinning."""
    if y_train.empty:
        raise BinningFitError("No hay filas de Desarrollo con target no nulo para ajustar binning.")
    invalid = ~y_train.isin((0, 1))
    if bool(invalid.any()):
        observed = sorted(str(value) for value in y_train.loc[invalid].unique())
        raise BinningFitError(
            "El target de Desarrollo para binning debe contener sólo 0/1; "
            f"valores observados inválidos={observed}."
        )
    classes = {int(value) for value in y_train.unique()}
    if classes != {0, 1}:
        raise BinningFitError(
            "Target degenerado para binning: Desarrollo requiere al menos un 0 y un 1; "
            f"clases observadas={sorted(classes)}."
        )


def _build_binner(config: BinningConfig, feature_columns: tuple[str, ...]) -> WoEBinner:
    """Construye ``WoEBinner`` y bloquea las features ya resueltas por el paso."""
    from nikodym.binning.transformer import WoEBinner

    binner = WoEBinner.from_config(config)
    binner.set_params(feature_columns=feature_columns, exclude_columns=())
    return binner


def _assemble_woe_frame(
    *,
    source: DataFrame,
    eligible_mask: Series,
    woe_only: DataFrame,
    structural_columns: tuple[str, ...],
    keep_structural_columns: bool,
    pd: Any,
) -> DataFrame:
    """Arma el ``woe_frame`` final sin reintroducir variables crudas."""
    if not keep_structural_columns:
        return woe_only.copy(deep=True)

    present = [column for column in structural_columns if column in source.columns]
    structural = source.loc[eligible_mask, present].copy(deep=True)
    return cast(DataFrame, pd.concat([structural, woe_only.copy(deep=True)], axis=1))


def _copy_tables(tables: dict[str, DataFrame]) -> dict[str, DataFrame]:
    """Copia defensivamente las tablas por variable antes de publicarlas."""
    return {name: table.copy(deep=True) for name, table in tables.items()}


def _summary_with_fresh_iv_band(summary: DataFrame, pd: Any) -> DataFrame:
    """Cruza ``iv`` con ``iv_band`` para mantener consistencia tras B6.2."""
    from nikodym.binning.results import iv_band

    result = summary.copy(deep=True)
    if result.empty:
        return result
    iv_values = pd.to_numeric(result["iv"], errors="raise")
    result["iv"] = iv_values.map(lambda value: _normalize_zero(float(value)))
    result["iv_band"] = result["iv"].map(lambda value: iv_band(float(value)))
    return result


def _variable_summaries(summary: DataFrame, pd: Any) -> tuple[Any, ...]:
    """Construye ``BinningVariableSummary`` para variables efectivamente binneadas."""
    from nikodym.binning.results import BinningVariableSummary, iv_band

    records: list[BinningVariableSummary] = []
    for row in summary.to_dict(orient="records"):
        if not bool(row.get("selected", False)):
            continue
        iv = _normalize_zero(float(row["iv"]))
        dtype = _summary_dtype(row.get("dtype"))
        records.append(
            BinningVariableSummary(
                name=str(row["name"]),
                dtype=dtype,
                status=str(row.get("status", "")),
                selected=True,
                n_bins=int(row.get("n_bins", 0)),
                iv=iv,
                iv_band=iv_band(iv),
                monotonic_trend=_optional_string(row.get("monotonic_trend"), pd),
                skipped_reason=_optional_string(row.get("skipped_reason"), pd),
            )
        )
    return tuple(records)


def _summary_dtype(value: object) -> Literal["numerical", "categorical"]:
    """Normaliza dtype de summary al literal del contrato público."""
    text = str(value)
    if text in _NUMERICAL_DTYPES:
        return cast('Literal["numerical", "categorical"]', text)
    raise BinningFitError(f"OptBinning reportó dtype no soportado en summary: {text!r}.")


def _optional_string(value: object, pd: Any) -> str | None:
    """Convierte valores faltantes de pandas a ``None`` en contenedores Pydantic."""
    if value is None:
        return None
    if isinstance(value, float) and pd.isna(value):
        return None
    text = str(value)
    return None if text in {"", "None", "nan", "<NA>"} else text


def _build_results(
    *,
    woe_frame: DataFrame,
    tables: dict[str, DataFrame],
    summary: DataFrame,
    variable_summaries: tuple[Any, ...],
    binner: WoEBinner,
    config: BinningConfig,
) -> tuple[BinningResult, BinningCardSection]:
    """Construye ``BinningResult`` y ``BinningCardSection`` sin recalcular OptBinning."""
    from nikodym.binning.results import BinningCardSection, BinningResult, BinningVariableSummary

    typed_summaries = cast(tuple[BinningVariableSummary, ...], variable_summaries)
    result = BinningResult(
        woe_frame=woe_frame.copy(deep=True),
        tables=_copy_tables(tables),
        summary=summary.copy(deep=True),
        variable_summaries=typed_summaries,
        woe_column_map=dict(binner.woe_column_map_),
        skipped_variables=dict(binner.skipped_variables_),
    )
    card = BinningCardSection.from_result(
        result,
        special_handling=config.special_handling,
        missing_handling=str(config.metric_missing),
        optbinning_version=_optbinning_version(),
    )
    return result, card


def _optbinning_version() -> str:
    """Obtiene la versión instalada de OptBinning sin importar el módulo pesado."""
    try:
        return metadata.version("optbinning")
    except metadata.PackageNotFoundError:
        return "no_instalado"


def _effective_forced_trend(
    config: BinningConfig,
    override: VariableBinningConfig | None,
) -> str | None:
    """Devuelve la tendencia forzada si la config no está en modo automático."""
    if override is not None and override.monotonic_trend is not None:
        return override.monotonic_trend
    trend = config.monotonic_trend
    if trend is None or trend in _AUTO_MONOTONIC_TRENDS:
        return None
    return trend


def _effective_monotonic_mode(
    config: BinningConfig,
    override: VariableBinningConfig | None,
) -> str | None:
    """Devuelve el modo de monotonía efectivo (el override tiene prioridad sobre el global)."""
    if override is not None and override.monotonic_trend is not None:
        return override.monotonic_trend
    return config.monotonic_trend


def _resolved_trends_by_variable(summary: DataFrame) -> dict[str, str]:
    """Mapa ``variable→tendencia resuelta`` para filas seleccionadas con dirección concreta."""
    resolved: dict[str, str] = {}
    for row in summary.to_dict(orient="records"):
        if not bool(row.get("selected", False)):
            continue
        trend = row.get("monotonic_trend")
        if isinstance(trend, str) and trend:
            resolved[str(row["name"])] = trend
    return resolved


def _effective_max_n_bins(
    config: BinningConfig,
    override: VariableBinningConfig | None,
) -> int | None:
    """Resuelve el máximo de bins efectivo para auditar colapsos."""
    if override is not None and override.max_n_bins is not None:
        return override.max_n_bins
    return config.max_n_bins


def _normalize_zero(value: float) -> float:
    """Normaliza ``-0.0`` a ``0.0`` para salidas reproducibles."""
    if value == 0.0:
        return 0.0
    return value
