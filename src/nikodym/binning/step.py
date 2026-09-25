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
from collections.abc import Callable
from dataclasses import dataclass
from importlib import metadata
from typing import TYPE_CHECKING, Any, Final, Literal, TypeAlias, cast

from nikodym.binning.config import BinningConfig, VariableBinningConfig
from nikodym.binning.diagnostics import event_rate_by_partition
from nikodym.binning.exceptions import BinningFitError
from nikodym.core.mixins import AuditableMixin
from nikodym.core.registry import register
from nikodym.core.steps import (
    REGLA_TTD_NO_PUNTUADA,
    ArtifactKey,
    campo_de_card,
    card_publicada,
)

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
    "bin_frame",
    "result",
    "binning_card",
    # Aditivo (enmienda FLUJO-GUIADO-SCORECARD §3.6-2, D-FLU-6): la tasa de malos por tramo y
    # muestra con la marca de inversión; clave propia, las tablas estables no cambian.
    "event_rate_by_partition",
    # Aditivos (enmienda PUNTUAR-POBLACION-TTD, D-TTD-2 y D-TTD-5): el WoE de las operaciones
    # fuera del ajuste que la TTD declarada incluye, y las categorías no vistas en Desarrollo
    # contadas por muestra. Claves propias: `woe_frame` y la card no cambian.
    "out_of_model_woe_frame",
    "unseen_categories",
    # Aditivo (enmienda COPY-PRUEBA-REAL-SBA, D-CPY-3): los bordes efectivos de cada tramo regular
    # numérico, a precisión completa, para escribir sus rangos sin el redondeo de la etiqueta.
    "bin_edges",
)
#: La partición de las filas que no entran al ajuste (SDD-02: indeterminadas, excluidas y las que
#: una división por columna no asignó a ninguna muestra).
_OUT_OF_MODEL_PARTITION: Final = "fuera_de_modelo"
#: Las muestras en que se cuentan las categorías no vistas (D-TTD-5), en el orden en que se leen.
#: Desarrollo no está: por construcción, todo lo que trae lo vio el ajuste.
_UNSEEN_SAMPLES: Final[tuple[str, ...]] = ("holdout", "oot", _OUT_OF_MODEL_PARTITION)
_MODEL_PARTITIONS: Final[frozenset[str]] = frozenset({"desarrollo", "holdout", "oot"})
_AUTO_MONOTONIC_TRENDS: Final[frozenset[str]] = frozenset(
    {"auto", "auto_heuristic", "auto_asc_desc"}
)
_NUMERICAL_DTYPES: Final[frozenset[str]] = frozenset({"numerical", "categorical"})
_OPTIMAL_STATUS: Final = "OPTIMAL"


@dataclass(frozen=True, slots=True)
class _FeatureColumnResolution:
    """Candidatas resueltas y decisiones anti-fuga derivadas del config de ``data``."""

    columns: tuple[str, ...]
    excluded_by_target_rule: tuple[str, ...]
    explicit_target_rule_columns: tuple[str, ...]
    target_rule_paths: dict[str, tuple[str, ...]]


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

        feature_resolution = _resolve_feature_columns(
            frame=frame,
            target_col=target_col,
            status_col=status_col,
            partition_col=partition_col,
            ttd_col=ttd_col,
            config=self.config,
            data_config=getattr(study.config, "data", None),
            pd=pd,
        )
        self._log_target_rule_decisions(feature_resolution)
        feature_columns = feature_resolution.columns
        _validate_feature_columns_not_empty(feature_columns)
        train_mask = _training_mask(frame, target_col, partition_col)
        y_train = cast(Series, frame.loc[train_mask, target_col].copy(deep=True))
        _validate_training_target(y_train)

        eligible_mask = _modelable_mask(frame, partition_col)
        x_train = frame.loc[train_mask, list(feature_columns)].copy(deep=True)
        x_transform = frame.loc[eligible_mask, list(feature_columns)].copy(deep=True)

        self._log_special_policy(special=special, feature_columns=feature_columns)
        overrides, suspendidos = _active_overrides(
            self.config, feature_columns, tuple(str(column) for column in frame.columns)
        )
        self._log_suspended_overrides(suspendidos)
        binner = _build_binner(self.config, feature_columns)
        binner.set_params(variable_overrides=overrides)
        # El sumidero va al binner (D-RAR-1): si reagrupa una categoría rara, el intento
        # tiene que quedar en el trail aunque el reajuste falle y `execute` no termine.
        binner.fit(x_train, y_train, special=special, audit=self._audit)
        woe_only = binner.transform(x_transform)
        bin_frame = binner.transform_bins(x_transform)
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
            excluded_by_target_rule=feature_resolution.excluded_by_target_rule,
        )
        self._log_binning_decisions(
            binner=binner,
            summary=summary,
            feature_columns=feature_columns,
            pd=pd,
        )
        # Diagnóstico aparte (§3.6-2): sobre las etiquetas congeladas de las filas elegibles, con
        # la tendencia resuelta en desarrollo como referencia. No toca tablas ni summary.
        tasas_por_muestra = event_rate_by_partition(
            bin_frame=bin_frame,
            target=frame.loc[eligible_mask, target_col],
            partition=frame.loc[eligible_mask, partition_col],
            tables=tables,
            trends=_resolved_trends_by_variable(summary),
        )
        # D-TTD-1 y D-TTD-5: las operaciones fuera del ajuste se transforman con el binner ya
        # ajustado DESPUÉS de registrar las categorías no vistas de las modelables, porque cada
        # `transform` reemplaza ese conteo; y el conteo vuelve a su valor para que el `process`
        # publicado sea el de siempre.
        conteo_modelables = dict(binner.unknown_categories_)
        fuera_mask = _out_of_model_mask(frame, partition_col, ttd_col)
        out_of_model_woe_frame = self._woe_fuera_del_ajuste(
            binner=binner,
            frame=frame,
            fuera_mask=fuera_mask,
            feature_columns=feature_columns,
            structural_columns=(target_col, status_col, partition_col, ttd_col),
            vacio=woe_frame.iloc[0:0].copy(deep=True),
            pd=pd,
        )
        binner.unknown_categories_ = conteo_modelables
        # Los dos diagnósticos aditivos (D-TTD-5, D-CPY-3) son accesorios: si fallan, se publican
        # vacíos con la causa en el trail y la corrida sigue (revisión adversarial del código,
        # pasada 1).
        categorias_no_vistas = self._diagnostico_aislado(
            "categorias_no_vistas_no_contadas",
            lambda: _categorias_no_vistas_por_muestra(
                binner,
                frame=frame,
                feature_columns=feature_columns,
                muestras={
                    "holdout": _partition_mask(frame, partition_col, "holdout"),
                    "oot": _partition_mask(frame, partition_col, "oot"),
                    _OUT_OF_MODEL_PARTITION: fuera_mask,
                },
                pd=pd,
            ),
            vacio=pd.DataFrame(columns=["variable", "muestra", "filas"]).astype(
                {"variable": "object", "muestra": "object", "filas": "int64"}
            ),
        )
        bordes = self._diagnostico_aislado(
            "bordes_de_tramo_no_publicados",
            lambda: _bordes_efectivos(binner, tables, pd),
            vacio=_bordes_vacios(pd),
        )
        self._publish_artifacts(
            study,
            binner,
            tables,
            summary,
            woe_frame,
            bin_frame,
            result,
            binning_card,
            tasas_por_muestra,
            out_of_model_woe_frame,
            categorias_no_vistas,
            bordes,
        )
        return result

    def _diagnostico_aislado(
        self, regla: str, calcular: Callable[[], DataFrame], *, vacio: DataFrame
    ) -> DataFrame:
        """Un diagnóstico aditivo que no puede detener la corrida: si falla, vacío y al trail."""
        try:
            return calcular()
        except Exception as exc:  # accesorio: nunca detiene la corrida
            self.log_decision(
                regla=regla,
                umbral=self.name,
                valor={"causa": f"{type(exc).__name__}: {exc}"},
                accion="publicar_vacio",
            )
            return vacio

    def _woe_fuera_del_ajuste(
        self,
        *,
        binner: WoEBinner,
        frame: DataFrame,
        fuera_mask: Series,
        feature_columns: tuple[str, ...],
        structural_columns: tuple[str, ...],
        vacio: DataFrame,
        pd: Any,
    ) -> DataFrame:
        """El WoE de las operaciones fuera del ajuste que la TTD incluye (D-TTD-1).

        La misma transformación que reciben Holdout y OOT —con los WoE asignados de D-FAL-1 y los
        reagrupamientos de D-RAR-1—, sin reajustar nada. Sin filas, la clave queda vacía con el
        esquema del ``woe_frame``; si la transformación falla, también, y la falla queda en el
        trail: puntuar fuera del ajuste nunca detiene la corrida (§1.6).
        """
        if not bool(fuera_mask.any()):
            return vacio
        try:
            woe_only = binner.transform(
                frame.loc[fuera_mask, list(feature_columns)].copy(deep=True)
            )
            return _assemble_woe_frame(
                source=frame,
                eligible_mask=fuera_mask,
                woe_only=woe_only,
                structural_columns=structural_columns,
                keep_structural_columns=self.config.keep_structural_columns,
                pd=pd,
            )
        except Exception as exc:  # D-TTD-1 §1.6: fuera del ajuste nunca detiene la corrida
            self.log_decision(
                regla=REGLA_TTD_NO_PUNTUADA,
                umbral=self.name,
                valor={"filas": int(fuera_mask.sum()), "causa": f"{type(exc).__name__}: {exc}"},
                accion="publicar_vacio",
            )
            return vacio

    def _log_suspended_overrides(self, suspendidos: tuple[VariableBinningConfig, ...]) -> None:
        """Declara los tramos fijados de variables excluidas que quedan en suspenso (D-EXC-1)."""
        for override in suspendidos:
            self.log_decision(
                regla="override_en_suspenso",
                umbral="binning.exclude_columns",
                valor={"variable": override.name},
                accion="no_aplicar_override",
            )

    def _log_target_rule_decisions(self, resolution: _FeatureColumnResolution) -> None:
        """Declara exclusiones automáticas y contradicciones de una lista explícita."""
        for column in resolution.excluded_by_target_rule:
            self.log_decision(
                regla="columna_del_target",
                umbral=_audit_rule_path(resolution.target_rule_paths[column]),
                valor=column,
                accion="excluir_de_candidatas",
                step=self.name,
            )
        for column in resolution.explicit_target_rule_columns:
            self.log_decision(
                regla="columna_del_target",
                umbral=_audit_rule_path(resolution.target_rule_paths[column]),
                valor=column,
                accion="conservar_por_lista_explicita",
                step=self.name,
            )

    def _log_special_policy(
        self,
        *,
        special: MaskedFrame,
        feature_columns: tuple[str, ...],
    ) -> None:
        """Registra el tratamiento de special values declarado para variables candidatas."""
        catalog = special.declared_special_catalog or special.special_catalog
        for column in feature_columns:
            codes = catalog.get(column, [])
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
        self._log_unknown_categories(binner.unknown_categories_, binner.cat_unknown)

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
            if iv >= 0.50:
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

    def _log_unknown_categories(
        self, unknown_categories: dict[str, int], cat_unknown: float | str | None = None
    ) -> None:
        """Registra categorías no vistas durante la transformación WoE, con su tratamiento real.

        Con el default (``cat_unknown=None``) OptBinning asigna WoE 0 y el evento es el de siempre.
        Con un valor declarado, el evento decía «neutral» aunque se aplicara ese valor: ahora dice
        el valor (enmienda PUNTUAR-POBLACION-TTD, D-TTD-5, revisión adversarial, pasada 3).
        """
        for variable, count in unknown_categories.items():
            if count <= 0:
                continue
            self.log_decision(
                regla="categoria_no_vista",
                umbral=0 if cat_unknown is None else cat_unknown,
                valor={"variable": variable, "conteo": count},
                accion="asignar_woe_neutral" if cat_unknown is None else "asignar_woe_declarado",
            )

    def metrics(self, study: Study) -> dict[str, float | None]:
        """Publica el resumen métrico del dominio al namespace canónico (D-GOB-4).

        Los dos conteos que describen qué pudo binnearse. El IV por variable NO entra: es un mapa
        por variable, no un escalar del modelo, y aplanarlo publicaría una clave por columna en
        cada model card. Sin ``metric_sections`` (D-GOB-5).
        """
        card = card_publicada(study, "binning", "binning_card")
        return {
            "n_variables_binned": campo_de_card(card, "n_variables_binned"),
            "n_variables_skipped": campo_de_card(card, "n_variables_skipped"),
        }

    def _publish_artifacts(
        self,
        study: Study,
        process: WoEBinner,
        tables: dict[str, DataFrame],
        summary: DataFrame,
        woe_frame: DataFrame,
        bin_frame: DataFrame,
        result: BinningResult,
        binning_card: BinningCardSection,
        event_rate_by_partition_table: DataFrame,
        out_of_model_woe_frame: DataFrame,
        unseen_categories: DataFrame,
        bin_edges: DataFrame,
    ) -> None:
        """Publica los artefactos estables, los tramos congelados y los diagnósticos aditivos."""
        study.artifacts.set("binning", "process", process)
        study.artifacts.set("binning", "tables", tables)
        study.artifacts.set("binning", "summary", summary)
        study.artifacts.set("binning", "woe_frame", woe_frame)
        study.artifacts.set("binning", "bin_frame", bin_frame.copy(deep=True))
        study.artifacts.set("binning", "result", result)
        study.artifacts.set("binning", "binning_card", binning_card)
        study.artifacts.set("binning", "event_rate_by_partition", event_rate_by_partition_table)
        study.artifacts.set("binning", "out_of_model_woe_frame", out_of_model_woe_frame)
        study.artifacts.set("binning", "unseen_categories", unseen_categories)
        study.artifacts.set("binning", "bin_edges", bin_edges)


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
) -> _FeatureColumnResolution:
    """Resuelve candidatas y evidencia anti-fuga preservando el orden declarado."""
    exclusions = _structural_columns(target_col, status_col, partition_col, ttd_col)
    exclusions.update(_data_declared_structural_columns(data_config))
    exclusions.update(_datetime_columns(frame, pd))
    exclusions.update(config.exclude_columns)
    target_rule_paths = _target_rule_paths_by_column(data_config)

    if config.feature_columns == "*":
        excluded_by_target_rule = tuple(
            str(column)
            for column in frame.columns
            if str(column) in target_rule_paths and str(column) not in exclusions
        )
        wildcard_exclusions = exclusions | set(target_rule_paths) | _single_unique_key(data_config)
        columns = tuple(
            str(column) for column in frame.columns if str(column) not in wildcard_exclusions
        )
        explicit_target_rule_columns: tuple[str, ...] = ()
    else:
        missing = [column for column in config.feature_columns if column not in frame.columns]
        if missing:
            joined = ", ".join(f"'{column}'" for column in missing)
            raise BinningFitError(
                f"BinningConfig.feature_columns declara columna(s) inexistente(s): {joined}."
            )
        columns = tuple(column for column in config.feature_columns if column not in exclusions)
        excluded_by_target_rule = ()
        explicit_target_rule_columns = tuple(
            column for column in columns if column in target_rule_paths
        )

    return _FeatureColumnResolution(
        columns=columns,
        excluded_by_target_rule=excluded_by_target_rule,
        explicit_target_rule_columns=explicit_target_rule_columns,
        target_rule_paths=target_rule_paths,
    )


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


def _data_declared_structural_columns(data_config: object) -> set[str]:
    """Extrae las columnas que ``DataConfig`` usa para ARMAR la muestra, no para predecir.

    Son las que el usuario declara como maquinaria del ejercicio —la fecha de observación, el
    corte de datos, la fecha o la cohorte del split— y que por eso no pueden entrar como variables
    candidatas cuando ``feature_columns`` es el comodín.

    ⚠️ ``partition_col`` entra por el mismo motivo, y **es una columna del propio usuario**: con la
    estrategia ``columna`` (D-COL-2) la división llega marcada en su archivo, así que sin esta
    línea la columna que dice a qué muestra pertenece cada fila se ofrecería como predictor. Es el
    mismo criterio con que ya se excluyen ``date_col`` y ``cohort_col``; lo que cambia con esa
    estrategia es sólo que la columna existe siempre.

    *(El nombre anterior —``_data_temporal_columns``— describía sólo dos de sus cuatro fuentes,
    y con ``partition_col`` habría pasado a mentir del todo.)*
    """
    columns: set[str] = set()
    target = _get_config_attr(data_config, "target")
    window = _get_config_attr(target, "window")
    columns.update(_present_strings(_get_config_attr(window, "observation_date_col")))
    columns.update(_present_strings(_get_config_attr(window, "data_cutoff_col")))

    partition = _get_config_attr(data_config, "partition")
    strategy = _get_config_attr(partition, "strategy")
    columns.update(_present_strings(_get_config_attr(strategy, "date_col")))
    columns.update(_present_strings(_get_config_attr(strategy, "cohort_col")))
    columns.update(_present_strings(_get_config_attr(strategy, "partition_col")))
    return columns


def _target_rule_paths_by_column(data_config: object) -> dict[str, tuple[str, ...]]:
    """Indexa las columnas que definen etiqueta en ``bad_rule``/``good_rule``.

    ``indeterminate_rule`` y ``exclusion_rules`` seleccionan la muestra, no determinan la
    etiqueta de las filas que permanecen; excluir sus columnas produciría falsos positivos.
    """
    target = _get_config_attr(data_config, "target")
    paths_by_column: dict[str, list[str]] = {}
    for rule_name in ("bad_rule", "good_rule"):
        rule = _get_config_attr(target, rule_name)
        path = f"data.target.{rule_name}"
        for column in _predicate_columns(rule):
            paths = paths_by_column.setdefault(column, [])
            if path not in paths:
                paths.append(path)
    return {column: tuple(paths) for column, paths in paths_by_column.items()}


def _single_unique_key(data_config: object) -> set[str]:
    """Devuelve la llave que identifica por sí sola; una combinación no se descompone."""
    if isinstance(data_config, dict):
        schema = data_config.get("schema", data_config.get("schema_"))
    else:
        # ``SchemaConfig`` usa ``schema_`` porque ``BaseModel.schema`` ya existe; el alias público
        # y el blob opaco usan ``schema``.
        schema = getattr(data_config, "schema_", None)
    unique_keys = _get_config_attr(schema, "unique_keys")
    if isinstance(unique_keys, list | tuple) and len(unique_keys) == 1:
        return _present_strings(unique_keys[0])
    return set()


def _validate_feature_columns_not_empty(columns: tuple[str, ...]) -> None:
    """Falla con todas las causas que pueden vaciar las candidatas resueltas."""
    if columns:
        return
    raise BinningFitError(
        "No hay columnas candidatas para binning tras excluir estructurales, fechas/cohortes, "
        "exclude_columns, reglas bad/good del target y llaves de unicidad simples."
    )


def _predicate_columns(rule: object) -> tuple[str, ...]:
    """Extrae ``Predicate.col`` de ``all_of``/``any_of`` en modelos o blobs opacos."""
    columns: list[str] = []
    for group_name in ("all_of", "any_of"):
        predicates = _get_config_attr(rule, group_name)
        if not isinstance(predicates, list | tuple):
            continue
        for predicate in predicates:
            column = _get_config_attr(predicate, "col")
            if isinstance(column, str) and column and column not in columns:
                columns.append(column)
    return tuple(columns)


def _audit_rule_path(paths: tuple[str, ...]) -> str | tuple[str, ...]:
    """Conserva el path simple legible y no pierde reglas si una columna aparece en ambas."""
    return paths[0] if len(paths) == 1 else paths


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


def _out_of_model_mask(frame: DataFrame, partition_col: str, ttd_col: str) -> Series:
    """Las filas fuera del ajuste que la TTD declarada incluye (D-TTD-1; D-DATA-5 intacta).

    Con ``ttd_includes_excluded=False`` la columna ``ttd`` vale ``False`` en toda la partición
    ``fuera_de_modelo``, así que la máscara queda vacía: no se puntúa ninguna fila nueva.
    """
    en_particion = frame[partition_col].astype("string").eq(_OUT_OF_MODEL_PARTITION)
    en_ttd = frame[ttd_col].astype("boolean")
    return cast(Series, (en_particion & en_ttd).fillna(False).astype("bool"))


def _bordes_efectivos(binner: WoEBinner, tables: dict[str, DataFrame], pd: Any) -> DataFrame:
    """Los bordes de cada tramo regular numérico, desde los cortes ajustados (D-CPY-3).

    Los mismos cortes que lee ``Scorecard.merge_bins`` (``get_binned_variable(...).splits``), a
    precisión completa: la etiqueta ``Bin`` de OptBinning los redondea a dos decimales. Una variable
    cuyos tramos no calzan con sus cortes, o categórica, no aporta filas y se lee con su etiqueta.
    """
    import math

    from nikodym.core.tramos import BIN_EDGES_COLUMNS

    filas: list[dict[str, Any]] = []
    proceso = getattr(binner, "process_", None)
    for variable, tabla in tables.items():
        try:
            ajustada = proceso.get_binned_variable(variable) if proceso is not None else None
        except Exception:  # una variable no tramificada no tiene cortes que publicar
            continue
        if ajustada is None or str(getattr(ajustada, "dtype", "numerical")) != "numerical":
            continue
        cortes = [float(corte) for corte in getattr(ajustada, "splits", ())]
        etiquetas = tabla["Bin"] if "Bin" in tabla.columns else pd.Series(dtype=object)
        regulares = [
            etiqueta
            for indice, etiqueta in etiquetas.items()
            if str(indice) != "Totals"
            and isinstance(etiqueta, str)
            and etiqueta not in {"", "Special", "Missing"}
        ]
        if len(regulares) != len(cortes) + 1:
            continue
        bordes = [-math.inf, *cortes, math.inf]
        filas.extend(
            {"variable": str(variable), "bin_index": i, "lower": bordes[i], "upper": bordes[i + 1]}
            for i in range(len(cortes) + 1)
        )
    if not filas:
        return _bordes_vacios(pd)
    return cast(
        DataFrame,
        pd.DataFrame(filas, columns=list(BIN_EDGES_COLUMNS)).astype(
            {"variable": "object", "bin_index": "int64", "lower": "float64", "upper": "float64"}
        ),
    )


def _bordes_vacios(pd: Any) -> DataFrame:
    """El esquema de ``("binning", "bin_edges")`` sin filas."""
    from nikodym.core.tramos import BIN_EDGES_COLUMNS

    return cast(
        DataFrame,
        pd.DataFrame(columns=list(BIN_EDGES_COLUMNS)).astype(
            {"variable": "object", "bin_index": "int64", "lower": "float64", "upper": "float64"}
        ),
    )


def _partition_mask(frame: DataFrame, partition_col: str, partition: str) -> Series:
    """Las filas de una partición, como máscara booleana sin nulos."""
    return cast(
        Series, frame[partition_col].astype("string").eq(partition).fillna(False).astype("bool")
    )


def _categorias_no_vistas_por_muestra(
    binner: WoEBinner,
    *,
    frame: DataFrame,
    feature_columns: tuple[str, ...],
    muestras: dict[str, Series],
    pd: Any,
) -> DataFrame:
    """Cuenta por variable y muestra las filas con una categoría que no existía en Desarrollo.

    Una fila por par (variable, muestra) con al menos una, en el orden de las variables y de
    :data:`_UNSEEN_SAMPLES`; vacío si no hay ninguna (D-TTD-5). No toca el estado del binner.
    """
    from nikodym.binning.transformer import _contar_categorias_no_vistas

    filas: list[dict[str, Any]] = []
    conteos = {
        muestra: _contar_categorias_no_vistas(
            binner, frame.loc[mascara, list(feature_columns)].copy(deep=True)
        )
        for muestra, mascara in muestras.items()
        if bool(mascara.any())
    }
    for variable in binner.process_columns_:
        for muestra in _UNSEEN_SAMPLES:
            n = int(conteos.get(muestra, {}).get(variable, 0))
            if n > 0:
                filas.append({"variable": str(variable), "muestra": muestra, "filas": n})
    return cast(
        DataFrame,
        pd.DataFrame(filas, columns=["variable", "muestra", "filas"]).astype(
            {"variable": "object", "muestra": "object", "filas": "int64"}
        ),
    )


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


def _active_overrides(
    config: BinningConfig,
    feature_columns: tuple[str, ...],
    frame_columns: tuple[str, ...],
) -> tuple[tuple[VariableBinningConfig, ...], tuple[VariableBinningConfig, ...]]:
    """Separa los overrides que se aplican de los que quedan en suspenso (D-EXC-1).

    Un override de una variable que el config excluye —``exclude()`` después de ``set_bins()`` o
    ``merge_bins()``— queda en suspenso en vez de detener la corrida; sigue en el config, así que
    ``keep()`` lo reactiva. Un override de una variable que **no existe en el archivo** sigue
    siendo un error aunque también figure en ``exclude_columns``: suspenderlo escondería un error
    de config o un cambio de esquema (revisión adversarial del código, pasada 1).
    """
    excluidas = (set(config.exclude_columns) & set(frame_columns)) - set(feature_columns)
    activos = tuple(o for o in config.variable_overrides if o.name not in excluidas)
    suspendidos = tuple(o for o in config.variable_overrides if o.name in excluidas)
    return activos, suspendidos


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
    excluded_by_target_rule: tuple[str, ...],
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
        excluded_by_target_rule=excluded_by_target_rule,
        rare_category_regroupings=dict(getattr(binner, "rare_category_regroupings_", {})),
        assigned_bins=tuple(getattr(binner, "assigned_bins_", ())),
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
