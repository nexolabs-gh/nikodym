"""Paso orquestable de la capa ``validation`` (SDD-22 §4/§7/§9; CT-1).

``ValidationStep`` implementa el :class:`~nikodym.core.steps.Step` nativo del dominio
``validation``: lee los artefactos de las familias activas (calibración/discriminación/estabilidad
/backtesting), arma el frame analítico común (§6) sin mutar aguas arriba, delega en
:class:`~nikodym.validation.evaluator.ValidationEvaluator`, emite las decisiones auditables (§9) y
publica las seis claves estables bajo ``domain='validation'``.

**``requires`` dinámicos (CT-1, patrón SDD-16 §4).** ``from_config`` compone las dependencias según
las familias activas y los toggles de config: ``calibration`` exige ``calibration``+``data.labels``;
``discrimination`` **prefiere** ``performance.discriminant_metrics`` (o cae a ``calibration``
+``data.labels`` con ``consume_performance=False``); ``stability`` exige
``stability.stability_metrics``+``psi_table`` con ``consume_stability=True`` y, con ``False``, lo
que el recálculo va a leer —``scorecard.score``, ``calibration.calibrated_pd_frame`` y, según la
sección ``stability`` declarada, ``data.frame`` y ``binning.bin_frame``— (D-VAL-16); ``backtesting``
(sólo si ``enabled``) exige ``provisioning_ifrs9.detail``+``staging``+``data.frame``. Un
``requires`` ausente levanta :class:`~nikodym.core.exceptions.ArtifactNotFoundError` **antes** de
ejecutar.

**El recálculo del PSI sigue el patrón D-REQ.** El paso no puede leer ``NikodymConfig.stability``
al construirse (D-INV-1, D-REQ-2): la sección ``stability`` declara lo que el recálculo leerá
(``StabilityConfig.requisitos_de_recalculo_declarados``), el núcleo lo transporta en
``ContextoDeResolucion.requisitos_de_recalculo`` sin interpretarlo y
:meth:`from_config_with_context` lo lee con tres estados —clave ausente: la sección no está
declarada y el recálculo usa la **receta mínima** (sin eje temporal ni bins,
``nikodym.stability.config.receta_minima_de_recalculo``);
``None``: la sección está declarada e incoaccionable y el paso levanta ``ConfigError`` al
construirse, para que ``check_pipeline`` lo acuse antes de ejecutar nada; tupla: lo declarado—.
``execute`` re-deriva la lista efectiva desde ``study.config`` y la exige con ``_require_present``
antes de calcular, que es la misma degradación declarada que ``tuning`` tiene en ``run_step``
(D-REQ-4). El recálculo corre ``nikodym.stability.step.compute_stability`` —el mismo ensamblador y
el mismo evaluador que el paso de estabilidad, por la misma llamada— y la tabla lo dice con
``source='recomputed'``.

El módulo evita importar ``pandas``/``numpy``/``scipy``/``sklearn`` en import time.
``nikodym.validation`` lo importa para ejecutar ``@register("standard", domain="validation")`` sin
contaminar el núcleo liviano; el evaluador (y con él pandas/numpy) se importa **perezosamente**
dentro de ``execute``. El motor v1 es determinista: ``execute`` descarta el ``rng``.

**Nota data.labels (nitpick c).** ``('data','labels')`` es un :class:`LabeledFrame` (SDD-02), no un
``DataFrame``: se extrae ``.frame``/``.target_col`` correctamente. El ``detail`` de
``provisioning_ifrs9`` puede traer celdas ``Decimal``/``float``: el evaluador las convierte a float.

**Experimental (fuera de la garantía SemVer 1.x).**
"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING, Any, Final, TypeAlias, cast

from nikodym.core.exceptions import ArtifactNotFoundError, ConfigError, MissingDependencyError
from nikodym.core.mixins import AuditableMixin
from nikodym.core.registry import register
from nikodym.core.steps import ArtifactKey, ContextoDeResolucion, campo_de_card
from nikodym.validation.config import ValidationConfig
from nikodym.validation.exceptions import ValidationDataError

if TYPE_CHECKING:
    import numpy as np
    import pandas as pd

    from nikodym.core.audit import AuditEvent
    from nikodym.core.study import Study
    from nikodym.stability.config import StabilityConfig
    from nikodym.validation.results import (
        StabilityRecompute,
        StabilityRecomputeRecipe,
        StabilitySource,
        ValidationResult,
    )

    DataFrame: TypeAlias = pd.DataFrame
else:
    AuditEvent: TypeAlias = Any
    DataFrame: TypeAlias = Any
    StabilityConfig: TypeAlias = Any
    StabilityRecompute: TypeAlias = Any
    StabilityRecomputeRecipe: TypeAlias = Any
    StabilitySource: TypeAlias = Any
    Study: TypeAlias = Any
    ValidationResult: TypeAlias = Any

__all__ = ["VALIDATION_ARTIFACTS", "ValidationStep"]

VALIDATION_ARTIFACTS: Final[tuple[str, ...]] = (
    "discrimination",
    "calibration",
    "stability",
    "backtesting",
    "result",
    "card",
)
_SCORING_EXTRA_MESSAGE: Final = (
    "ValidationStep requiere pandas/numpy/scipy; instale nikodym[scoring]."
)
_CALIBRATION_DOMAIN: Final = "calibration"
_DATA_DOMAIN: Final = "data"
_PERFORMANCE_DOMAIN: Final = "performance"
_STABILITY_DOMAIN: Final = "stability"
_IFRS9_DOMAIN: Final = "provisioning_ifrs9"
_SCORECARD_DOMAIN: Final = "scorecard"
_ROW_ID_COLUMN: Final = "row_id"
#: La ficha del scorecard en la ruta de recálculo: se **lee** si está —la receta mínima toma de
#: ella la dirección del score y la guarda del ensamblador la contrasta con la sección declarada—
#: y no se exige, porque el trabajo que trae el puntaje ya construido puede venir sin ficha. Va en
#: ``optional_requires`` de **toda** la ruta ``consume_stability=False`` para que la puerta pública
#: no la declare inerte (D-ART-5; pasadas 5 y 6 de Codex sobre la enmienda VALIDACION-COTEJADA).
_RECOMPUTE_OPTIONAL_REQUIRES: Final[tuple[ArtifactKey, ...]] = ((_SCORECARD_DOMAIN, "card"),)


@register("standard", domain="validation")
class ValidationStep(AuditableMixin):
    """Orquesta la validación avanzada y publica ``domain='validation'``."""

    name: str = "validation"
    requires: tuple[ArtifactKey, ...] = ()
    optional_requires: tuple[ArtifactKey, ...] = ()
    provides: tuple[ArtifactKey, ...] = tuple(("validation", key) for key in VALIDATION_ARTIFACTS)

    def __init__(
        self,
        config: ValidationConfig,
        *,
        requisitos_de_recalculo: tuple[ArtifactKey, ...] | None = None,
    ) -> None:
        """Construye el paso desde la sección ``ValidationConfig`` y arma ``requires`` (CT-1).

        ``requisitos_de_recalculo`` es lo que la sección ``stability`` declaró que el recálculo del
        PSI leerá (D-VAL-16); ``None`` significa **«no se sabe»** —resolución suelta, o sección no
        declarada— y entonces se declaran los de la **receta mínima**, que es lo único que el paso
        puede afirmar por sí solo. Sólo cuenta con la familia ``stability`` activa y
        ``consume_stability=False``; en cualquier otro caso se ignora.
        """
        self.config = config
        self.requires = _requires_for(config, requisitos_de_recalculo)
        self.optional_requires = (
            _RECOMPUTE_OPTIONAL_REQUIRES if _recalcula_estabilidad(config) else ()
        )

    @classmethod
    def from_config(cls, cfg: ValidationConfig) -> ValidationStep:
        """Construye ``ValidationStep`` desde ``NikodymConfig.validation`` (firma histórica).

        Sin contexto, la ruta de recálculo declara los ``requires`` de la receta mínima y
        :meth:`execute` exige lo efectivo antes de calcular (D-REQ-4): un ``run_step('validation')``
        con sección declarada que necesite ``data.frame`` o ``binning.bin_frame`` y no los tenga
        falla al entrar a ``execute`` con la clave exacta, no a mitad de cálculo.
        """
        return cls(cfg)

    @classmethod
    def from_config_with_context(
        cls,
        cfg: ValidationConfig,
        *,
        contexto: ContextoDeResolucion,
    ) -> ValidationStep:
        """Fábrica contextual del resolver (D-FX-2): declara el ``requires`` de ESTA invocación.

        Tercer implementador del hook. Con ``consume_stability=False`` lee
        ``contexto.requisitos_de_recalculo['stability']`` y distingue **tres estados** (D-VAL-16):
        clave ausente → la sección no está declarada y el recálculo usará la receta mínima, así
        que se declaran sus dos claves y nada más; ``None`` → la sección está declarada pero no se
        pudo coaccionar, y como ``execute`` va a releerla el paso se detiene aquí, en el
        preflight, con ``ConfigError`` (``check_pipeline`` lo acusa antes de ejecutar ningún
        paso); tupla → lo declarado. Es una precisión sobre D-REQ-4, no una excepción: degradar al
        default es correcto cuando el paso conserva el contrato que declararía solo; aquí va a leer
        esa sección, y un config inválido no puede pasar la comprobación previa.
        """
        if not _recalcula_estabilidad(cfg):
            return cls(cfg)
        declarados = contexto.requisitos_de_recalculo
        if _STABILITY_DOMAIN not in declarados:
            return cls(
                cfg, requisitos_de_recalculo=_receta_minima().requisitos_de_recalculo_declarados()
            )
        requisitos = declarados[_STABILITY_DOMAIN]
        if requisitos is None:
            raise ConfigError(
                "La sección 'stability' está declarada pero no es válida, y el recálculo del PSI "
                "de 'validation' (consume_stability=False) la lee: corrige la sección 'stability' "
                "o quítala del config para recalcular con la receta mínima."
            )
        return cls(cfg, requisitos_de_recalculo=requisitos)

    def emit(self, event: AuditEvent) -> None:
        """Permite pasar el step como ``AuditSink`` si un motor futuro lo requiere."""
        self._audit.emit(event)

    def execute(self, study: Study, rng: np.random.Generator) -> ValidationResult:
        """Ejecuta la validación determinista sin consumir ``rng`` y publica seis artefactos."""
        del rng  # El evaluador v1 es determinista (SDD-22 §9): se descarta el azar.
        pd = _import_pandas()
        from nikodym.validation.evaluator import ValidationEvaluator

        cfg = _validation_config_from_study(study, fallback=self.config)
        # El recálculo del PSI lee la sección `stability` en ejecución —la misma lectura de una
        # sección ajena que `tuning` hace con `ml`—; los `requires` efectivos se re-derivan de
        # ella y se exigen ANTES de calcular nada (D-REQ-4, D-VAL-16). Sin sección, la receta
        # mínima; la dirección del score sale de la ficha del scorecard si está.
        recalculo: tuple[StabilityConfig, StabilityRecomputeRecipe] | None = None
        requisitos_de_recalculo: tuple[ArtifactKey, ...] | None = None
        if _recalcula_estabilidad(cfg):
            recalculo = _stability_config_from_study(
                study, score_direction=_direccion_de_la_ficha(study)
            )
            requisitos_de_recalculo = recalculo[0].requisitos_de_recalculo_declarados()
        requires = _requires_for(cfg, requisitos_de_recalculo)
        _require_present(study, requires)
        families = _active_families(cfg)

        analytic = self._read_analytic_frame(study, cfg, families, pd)
        performance_metrics = self._read_performance_metrics(study, cfg, families, pd)
        stability_metrics, stability_source, stability_recompute = self._read_stability_metrics(
            study, families, pd, recalculo=recalculo
        )
        ifrs9_detail, realised = self._read_backtesting_inputs(study, cfg, families, pd)

        result = ValidationEvaluator.from_config(cfg).validate(
            calibrated_pd=analytic,
            performance_metrics=performance_metrics,
            stability_metrics=stability_metrics,
            stability_source=stability_source,
            stability_recompute=stability_recompute,
            ifrs9_detail=ifrs9_detail,
            realised=realised,
            model_ref=_model_ref(study),
        )
        self._emit_decisions(result)
        self._publish_artifacts(study, result)
        return result

    # --- lectura de artefactos por familia -----------------------------------------------------

    def _read_analytic_frame(
        self, study: Study, cfg: ValidationConfig, families: frozenset[str], pd: Any
    ) -> DataFrame | None:
        """Arma el frame analítico común (§6) si alguna familia lo necesita, sin mutar upstream."""
        if not _needs_analytic_frame(cfg, families):
            return None
        calibrated = _as_dataframe(
            study.artifacts.get(_CALIBRATION_DOMAIN, "calibrated_pd_frame"),
            pd,
            "calibration.calibrated_pd_frame",
        )
        labeled = study.artifacts.get(_DATA_DOMAIN, "labels")
        return _assemble_analytic_frame(calibrated, labeled, cfg, pd)

    def _read_performance_metrics(
        self, study: Study, cfg: ValidationConfig, families: frozenset[str], pd: Any
    ) -> DataFrame | None:
        """Lee ``performance.discriminant_metrics`` cuando la discriminación lo consume."""
        if "discrimination" not in families or not cfg.discrimination.consume_performance:
            return None
        return _as_dataframe(
            study.artifacts.get(_PERFORMANCE_DOMAIN, "discriminant_metrics"),
            pd,
            "performance.discriminant_metrics",
        )

    def _read_stability_metrics(
        self,
        study: Study,
        families: frozenset[str],
        pd: Any,
        *,
        recalculo: tuple[StabilityConfig, StabilityRecomputeRecipe] | None,
    ) -> tuple[DataFrame | None, StabilitySource, StabilityRecompute | None]:
        """Obtiene el ``stability_metrics`` de la familia de estabilidad y de dónde salió.

        Con ``consume_stability=True`` lee el artefacto del paso de estabilidad. Con ``False``
        (``recalculo`` no nulo) corre :func:`nikodym.stability.step.compute_stability` con la
        ``StabilityConfig`` efectiva —la declarada o la receta mínima— sobre los artefactos que
        ``requires`` ya exigió: es el mismo ensamblador y el mismo evaluador que el paso de
        estabilidad, por la misma llamada (D-VAL-16), sin sink de auditoría propio (las bandas las
        audita este paso). El import es perezoso para no acoplar ``import nikodym.validation`` al
        grafo de ``stability``.
        """
        if "stability" not in families:
            return None, "stability_artifact", None
        if recalculo is None:
            return (
                _as_dataframe(
                    study.artifacts.get(_STABILITY_DOMAIN, "stability_metrics"),
                    pd,
                    "stability.stability_metrics",
                ),
                "stability_artifact",
                None,
            )
        from nikodym.stability.step import compute_stability
        from nikodym.validation.results import StabilityRecompute

        stability_cfg, recipe = recalculo
        result = compute_stability(study, stability_cfg)
        receta = StabilityRecompute(
            recipe=recipe,
            temporal_axis=stability_cfg.temporal_axis,
            csi_source=stability_cfg.csi_source,
        )
        return result.stability_metrics.copy(deep=True), "recomputed", receta

    def _read_backtesting_inputs(
        self, study: Study, cfg: ValidationConfig, families: frozenset[str], pd: Any
    ) -> tuple[DataFrame | None, DataFrame | None]:
        """Alinea ``provisioning_ifrs9.detail`` y ``data.frame`` por ``row_id`` (backtesting)."""
        if "backtesting" not in families or not cfg.backtesting.enabled:
            return None, None
        detail = _as_dataframe(
            study.artifacts.get(_IFRS9_DOMAIN, "detail"),
            pd,
            "provisioning_ifrs9.detail",
        )
        data_frame = _as_dataframe(
            study.artifacts.get(_DATA_DOMAIN, "frame"),
            pd,
            "data.frame",
        )
        return _align_backtesting_inputs(detail, data_frame)

    # --- auditoría (§9) ------------------------------------------------------------------------

    def _emit_decisions(self, result: ValidationResult) -> None:
        """Registra el ``log_decision`` §9: fallos, HL sin veredicto, semáforo, PSI, reúso y avisos.

        El evento del semáforo lleva como ``umbral`` los dos cortes con que se decidió el color,
        leídos del record ya resellado (D-VAL-15): ``grade.alpha`` es la significancia del
        contraste y registrarla como umbral —lo que hacía hasta la capa A de VALIDACION-COTEJADA—
        impedía reconstruir el color desde el trail con cortes personalizados.
        """
        for record in result.calibration_records:
            if record.test == "hosmer_lemeshow" and record.decision == "fail":
                self.log_decision(
                    regla="calibration_hosmer_lemeshow",
                    umbral=record.alpha,
                    valor={
                        "partition": record.partition,
                        "statistic": record.statistic,
                        "p_value": record.p_value,
                    },
                    accion="revisar_calibracion",
                )
        self._emit_hl_not_evaluable_decisions(result)
        self._emit_traffic_light_cuts_decision(result)
        for grade in result.grade_records:
            if grade.traffic_light != "green":
                self.log_decision(
                    regla="calibration_semaforo",
                    umbral={"green_alpha": grade.green_alpha, "red_alpha": grade.red_alpha},
                    valor={
                        "grade": grade.grade,
                        "p_value": grade.p_value,
                        "traffic_light": grade.traffic_light,
                    },
                    accion="vigilar_calibracion_por_grado",
                )
        self._emit_not_evaluable_grade_decisions(result)
        for backtest in result.backtest_records:
            if backtest.decision == "fail":
                self.log_decision(
                    regla=f"backtesting_{backtest.parameter}",
                    umbral=backtest.alpha,
                    valor={
                        "segment": backtest.segment,
                        "statistic": backtest.statistic,
                        "p_value": backtest.p_value,
                    },
                    accion="revisar_parametro_ifrs9",
                )
        self._emit_stability_decisions(result)
        if any(record.source == "recomputed" for record in result.discrimination_records):
            self.log_decision(
                regla="discrimination_source",
                umbral="performance_artifact",
                valor="recomputed",
                accion="reusar_performance_evaluator",
            )
        self._emit_stability_source_decision(result)
        for gap in result.card.falta_dato:
            self.log_decision(
                regla="validation_falta_dato",
                umbral=self.config.fail_on_falta_dato,
                valor=gap,
                accion="trazar_brecha_metodologica",
            )

    def _emit_traffic_light_cuts_decision(self, result: ValidationResult) -> None:
        """Registra UNA decisión con los dos cortes del semáforo si corrió el contraste por grado.

        Incondicional al color obtenido (pasada 1 de Codex sobre la capa A): el evento
        ``calibration_semaforo`` sólo sale en ámbar/rojo, así que una corrida toda verde no dejaba
        los cortes en el trail y reconstruir sus decisiones exigía recuperar el config o los
        artefactos. Aquí van los cortes y el recuento de colores; sin contraste
        (``traffic_light_cuts`` nulo) no hay semáforo que registrar.
        """
        section = result.card.metric_sections.get("validation", {})
        cuts = section.get("traffic_light_cuts")
        if not isinstance(cuts, dict):
            return
        counts = section.get("traffic_light", {})
        self.log_decision(
            regla="calibration_semaforo_cortes",
            umbral={"green_alpha": cuts.get("green_alpha"), "red_alpha": cuts.get("red_alpha")},
            valor={
                "green": counts.get("green", 0),
                "amber": counts.get("amber", 0),
                "red": counts.get("red", 0),
                "not_evaluable": len(section.get("not_evaluable_grades", ())),
            },
            accion="publicar_cortes_del_semaforo",
        )

    def _emit_hl_not_evaluable_decisions(self, result: ValidationResult) -> None:
        """Audita cada Hosmer-Lemeshow sin veredicto con su causa (D-VAL-17: una regla, 4 causas).

        Lee la misma lista que publica la card —``not_evaluable_partitions``— para que el trail y el
        resultado no puedan decir cosas distintas.
        El ``umbral`` es lo configurado (mínimo por grupo y grupos pedidos); el ``valor``, la
        partición con sus operaciones, el tamaño de su grupo más chico —nulo si la partición entera
        quedó bajo el mínimo y los grupos nunca se formaron— y la causa. Regla nueva de un dominio
        experimental: su forma sigue la marca de ``validation`` (D-EST-5).
        """
        section = result.card.metric_sections.get("validation", {})
        for item in section.get("not_evaluable_partitions", ()):
            self.log_decision(
                regla="calibration_hl_not_evaluable",
                umbral={"min_rows": item.get("min_rows"), "n_groups": item.get("n_groups")},
                valor={
                    "partition": item.get("partition"),
                    "n": item.get("n"),
                    "min_group_size": item.get("min_group_size"),
                    "reason": item.get("reason"),
                },
                accion="omitir_hosmer_lemeshow_no_evaluable",
            )

    def _emit_not_evaluable_grade_decisions(self, result: ValidationResult) -> None:
        """Audita cada grado bajo mínimo omitido del semáforo/verdicto (SDD-22 §6/§8/§9).

        Los grados con ``n < min_rows_per_group`` no producen semáforo (falta de potencia): el
        evaluador los excluye de ``grade_records`` y los expone en ``metric_sections`` para dejar
        traza. Aquí se emite el ``log_decision`` §9 que documenta la omisión sin veredicto engañoso.
        """
        section = result.card.metric_sections.get("validation", {})
        for grade in section.get("not_evaluable_grades", ()):
            self.log_decision(
                regla="calibration_grade_not_evaluable",
                umbral=grade.get("min_rows"),
                valor={
                    "grade": grade.get("grade"),
                    "n": grade.get("n"),
                    "observed_defaults": grade.get("observed_defaults"),
                },
                accion="omitir_grado_sin_potencia",
            )

    def _emit_stability_decisions(self, result: ValidationResult) -> None:
        """Registra una decisión por fila de estabilidad en banda review/redevelop (§9).

        El ``valor`` lleva ``source`` (D-VAL-16): con el PSI recalculado, el trail dice de dónde
        salió la fila que gatilló la banda. Clave aditiva en una regla de dominio experimental
        (D-EST-5).
        """
        stability = result.stability
        if stability.shape[0] == 0:
            return
        for row in stability.itertuples(index=False):
            if row.band in ("review", "redevelop"):
                self.log_decision(
                    regla="stability_psi",
                    umbral=(row.stable_threshold, row.review_threshold),
                    valor={
                        "feature": row.feature,
                        "value": row.value,
                        "band": row.band,
                        "source": row.source,
                    },
                    accion="vigilar_estabilidad",
                )

    def _emit_stability_source_decision(self, result: ValidationResult) -> None:
        """Registra UNA decisión cuando el PSI se recalculó, con la receta usada (D-VAL-16).

        Hermana de ``discrimination_source``: el ``umbral`` es la fuente que el toggle habría
        consumido, el ``valor`` la procedencia efectiva y la receta —sección declarada o receta
        mínima, con su eje y su fuente de CSI—, leída de la misma card que publica
        ``stability_recompute`` para que el trail y el resultado no puedan decir cosas distintas.
        Con la receta mínima el trail dice, así, que no hubo eje temporal porque la sección
        ``stability`` no está declarada.
        """
        section = result.card.metric_sections.get("validation", {})
        if section.get("stability_source") != "recomputed":
            return
        receta = section.get("stability_recompute") or {}
        self.log_decision(
            regla="stability_source",
            umbral="stability_artifact",
            valor={
                "source": "recomputed",
                "recipe": receta.get("recipe"),
                "temporal_axis": receta.get("temporal_axis"),
                "csi_source": receta.get("csi_source"),
            },
            accion="reusar_stability_evaluator",
        )

    # --- publicación ---------------------------------------------------------------------------

    def _publish_artifacts(self, study: Study, result: ValidationResult) -> None:
        """Publica las seis claves estables del dominio ``validation`` (copias defensivas)."""
        study.artifacts.set("validation", "discrimination", result.discrimination.copy(deep=True))
        study.artifacts.set("validation", "calibration", result.calibration.copy(deep=True))
        study.artifacts.set("validation", "stability", result.stability.copy(deep=True))
        study.artifacts.set("validation", "backtesting", result.backtesting.copy(deep=True))
        study.artifacts.set("validation", "result", result.model_copy(deep=True))
        study.artifacts.set("validation", "card", result.card.model_copy(deep=True))


# ─────────────────────────── helpers de contrato (CT-1) ───────────────────────────


def _active_families(config: ValidationConfig) -> frozenset[str]:
    """Devuelve el conjunto de familias activas declaradas en la config."""
    return frozenset(config.families)


def _needs_analytic_frame(config: ValidationConfig, families: frozenset[str]) -> bool:
    """Indica si alguna familia exige el frame analítico (calibración o fallback discriminación)."""
    if "calibration" in families:
        return True
    return "discrimination" in families and not config.discrimination.consume_performance


def _recalcula_estabilidad(config: ValidationConfig) -> bool:
    """Si esta config recalcula el PSI en vez de consumir el artefacto (D-VAL-16)."""
    return "stability" in _active_families(config) and not config.stability.consume_stability


def _receta_minima(score_direction: str | None = None) -> StabilityConfig:
    """La receta mínima de recálculo, importada perezosamente.

    Ver ``nikodym.stability.config.receta_minima_de_recalculo``.
    """
    from nikodym.stability.config import receta_minima_de_recalculo

    if score_direction not in (None, "higher_is_lower_risk", "higher_is_higher_risk"):
        raise ConfigError(
            "La ficha del scorecard declara una dirección del score desconocida: "
            f"{score_direction!r}."
        )
    return receta_minima_de_recalculo(score_direction)  # type: ignore[arg-type]


def _requires_for(
    config: ValidationConfig,
    requisitos_de_recalculo: tuple[ArtifactKey, ...] | None = None,
) -> tuple[ArtifactKey, ...]:
    """Compone las claves ``requires`` dinámicas según familias y toggles (CT-1, SDD-22 §4).

    ``requisitos_de_recalculo`` es lo que la sección ``stability`` declaró para el recálculo del
    PSI (D-VAL-16); ``None`` = «no se sabe» → los de la receta mínima. Sólo entra con la familia
    ``stability`` activa y ``consume_stability=False``.
    """
    families = _active_families(config)
    requires: list[ArtifactKey] = []
    if "calibration" in families:
        requires.append((_CALIBRATION_DOMAIN, "calibrated_pd_frame"))
        requires.append((_DATA_DOMAIN, "labels"))
    if "discrimination" in families:
        if config.discrimination.consume_performance:
            requires.append((_PERFORMANCE_DOMAIN, "discriminant_metrics"))
        else:
            requires.append((_CALIBRATION_DOMAIN, "calibrated_pd_frame"))
            requires.append((_DATA_DOMAIN, "labels"))
    if "stability" in families:
        if config.stability.consume_stability:
            requires.append((_STABILITY_DOMAIN, "stability_metrics"))
            requires.append((_STABILITY_DOMAIN, "psi_table"))
        elif requisitos_de_recalculo is None:
            requires.extend(_receta_minima().requisitos_de_recalculo_declarados())
        else:
            requires.extend(requisitos_de_recalculo)
    if "backtesting" in families and config.backtesting.enabled:
        requires.append((_IFRS9_DOMAIN, "detail"))
        requires.append((_IFRS9_DOMAIN, "staging"))
        requires.append((_DATA_DOMAIN, "frame"))
    # Dedup preservando el orden de aparición (calibración y fallback comparten calibration+labels).
    return tuple(dict.fromkeys(requires))


def _require_present(study: Study, requires: tuple[ArtifactKey, ...]) -> None:
    """Exige que cada artefacto ``requires`` (CT-1) esté en el ``ArtifactStore``."""
    for domain, key in requires:
        if not study.artifacts.has(domain, key):
            raise ArtifactNotFoundError(
                f"El paso 'validation' requiere el artefacto ('{domain}', '{key}'), "
                "ausente del ArtifactStore."
            )


def _model_ref(study: Study) -> str:
    """Deriva la referencia al modelo validado desde el nombre del config (no vacía)."""
    name = getattr(study.config, "name", None)
    text = str(name).strip() if name is not None else ""
    return text or "validation"


# ─────────────────────────── ensamblado de frames ───────────────────────────


def _assemble_analytic_frame(
    calibrated: DataFrame, labeled: Any, config: ValidationConfig, pd: Any
) -> DataFrame:
    """Alinea la PD calibrada con el target/grado de ``data.labels`` por índice (§6, nitpick c)."""
    calib = config.calibration
    labels_frame, target_col = _read_labeled_frame(labeled, pd)
    _validate_unique_index(calibrated, artifact="calibration.calibrated_pd_frame")
    _validate_unique_index(labels_frame, artifact="data.labels.frame")
    for column in (calib.partition_column, calib.pd_column):
        if column not in calibrated.columns:
            raise ValidationDataError(
                f"calibration.calibrated_pd_frame no contiene la columna requerida '{column}'."
            )
    missing = calibrated.index.difference(labels_frame.index)
    if len(missing):
        raise ValidationDataError(
            "data.labels no cubre todas las operaciones de calibration.calibrated_pd_frame: "
            f"faltan={missing.astype(str).tolist()}."
        )
    aligned_labels = labels_frame.loc[calibrated.index]
    data: dict[str, Any] = {
        calib.partition_column: calibrated[calib.partition_column].to_numpy(),
        calib.pd_column: calibrated[calib.pd_column].to_numpy(),
        calib.target_column: aligned_labels[target_col].to_numpy(),
    }
    frame = pd.DataFrame(data, index=calibrated.index)
    if calib.grade_col in aligned_labels.columns:
        frame[calib.grade_col] = aligned_labels[calib.grade_col].to_numpy()
    return cast(DataFrame, frame)


def _read_labeled_frame(labeled: Any, pd: Any) -> tuple[DataFrame, str]:
    """Extrae ``.frame``/``.target_col`` de un :class:`LabeledFrame` (SDD-02); valida contrato."""
    frame = getattr(labeled, "frame", None)
    target_col = getattr(labeled, "target_col", None)
    if not isinstance(frame, pd.DataFrame) or not isinstance(target_col, str):
        raise ValidationDataError(
            "El artefacto data.labels debe ser un LabeledFrame (SDD-02) con .frame y .target_col; "
            f"tipo observado={type(labeled).__name__}."
        )
    if target_col not in frame.columns:
        raise ValidationDataError(
            f"data.labels.frame no contiene su columna target declarada '{target_col}'."
        )
    return frame, target_col


def _align_backtesting_inputs(
    detail: DataFrame, data_frame: DataFrame
) -> tuple[DataFrame, DataFrame]:
    """Indexa ``detail`` por ``row_id`` y reindexa ``data.frame`` para alinear el backtesting."""
    if _ROW_ID_COLUMN not in detail.columns:
        raise ValidationDataError(
            f"provisioning_ifrs9.detail no contiene la columna '{_ROW_ID_COLUMN}' para alinear el "
            "backtesting con data.frame."
        )
    indexed = detail.set_index(_ROW_ID_COLUMN)
    _validate_unique_index(indexed, artifact="provisioning_ifrs9.detail(row_id)")
    _validate_unique_index(data_frame, artifact="data.frame")
    missing = indexed.index.difference(data_frame.index)
    if len(missing):
        raise ValidationDataError(
            "data.frame no cubre todas las operaciones de provisioning_ifrs9.detail: "
            f"faltan={missing.astype(str).tolist()}."
        )
    realised = data_frame.loc[indexed.index]
    return indexed, realised


def _validate_unique_index(frame: DataFrame, *, artifact: str) -> None:
    """Rechaza índices duplicados antes de alinear artefactos."""
    if frame.index.is_unique:
        return
    duplicated = frame.index[frame.index.duplicated()].astype(str).tolist()
    joined = ", ".join(f"'{item}'" for item in duplicated[:5])
    raise ValidationDataError(f"{artifact} contiene índice duplicado; ejemplos: {joined}.")


# ─────────────────────────── utilidades de import/config ───────────────────────────


def _import_pandas() -> Any:
    """Importa ``pandas`` localmente para preservar el import liviano del paquete."""
    try:
        return importlib.import_module("pandas")
    except ModuleNotFoundError as exc:
        raise MissingDependencyError(_SCORING_EXTRA_MESSAGE) from exc


def _as_dataframe(value: object, pd: Any, artifact: str) -> DataFrame:
    """Valida un artefacto tabular de entrada antes de leerlo."""
    if isinstance(value, pd.DataFrame):
        return cast(DataFrame, value)
    raise ValidationDataError(
        f"El artefacto '{artifact}' debe ser un pandas.DataFrame; "
        f"tipo observado={type(value).__name__}."
    )


def _validation_config_from_study(study: Study, *, fallback: ValidationConfig) -> ValidationConfig:
    """Lee ``NikodymConfig.validation`` y usa el config del paso como respaldo standalone."""
    raw_config = getattr(study.config, "validation", None)
    if raw_config is None:
        return fallback
    if isinstance(raw_config, ValidationConfig):
        return raw_config
    return ValidationConfig.model_validate(raw_config)


def _stability_config_from_study(
    study: Study, *, score_direction: str | None
) -> tuple[StabilityConfig, StabilityRecomputeRecipe]:
    """La ``StabilityConfig`` con que se recalcula el PSI y qué receta es (D-VAL-16).

    Lee ``NikodymConfig.stability`` en ejecución —la misma lectura de una sección ajena que hace
    ``tuning`` con ``ml``—: declarada, se usa tal cual (``"declared"``); ausente, la **receta
    mínima** con la dirección del score de la ficha del scorecard (``"minimal"``). Es el mismo
    helper cuyos ``requisitos_de_recalculo_declarados()`` exige ``execute`` antes de calcular, de
    modo que lo que el DAG comprueba y lo que el recálculo lee salen de un solo objeto.
    """
    from nikodym.stability.config import StabilityConfig

    raw_config = getattr(study.config, _STABILITY_DOMAIN, None)
    if raw_config is None:
        return _receta_minima(score_direction), "minimal"
    if isinstance(raw_config, StabilityConfig):
        return raw_config, "declared"
    return StabilityConfig.model_validate(raw_config), "declared"


def _direccion_de_la_ficha(study: Study) -> str | None:
    """La dirección del score que declara la ficha del scorecard, o ``None`` sin ficha.

    Se lee con :func:`~nikodym.core.steps.campo_de_card`: la ficha llega como DTO cuando la
    publicó el paso y como ``Mapping`` cuando la inyectó la puerta pública (D-ART). Es la única
    lectura de ``scorecard.card`` de esta ruta, por lo que la clave va en ``optional_requires``.
    """
    if not study.artifacts.has(_SCORECARD_DOMAIN, "card"):
        return None
    valor = campo_de_card(study.artifacts.get(_SCORECARD_DOMAIN, "card"), "score_direction")
    return None if valor is None else str(valor)
