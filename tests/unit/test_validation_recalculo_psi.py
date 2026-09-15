"""El recálculo del PSI de ``validation`` (D-VAL-16, capa C de VALIDACION-COTEJADA).

Con ``consume_stability=False`` el paso recalcula el PSI con **el mismo ensamblador y el mismo
evaluador** que la etapa de estabilidad (``nikodym.stability.step.compute_stability``), declara en
``requires`` exactamente lo que va a leer —por el patrón D-REQ: la sección ``stability`` lo declara,
el núcleo lo transporta, el paso lo lee del DTO— y la tabla dice ``source="recomputed"``. Hasta la
capa C ningún camino del ``Study`` llegaba al fallback y apagar el toggle abortaba la corrida.

Los tests nacieron rojos sobre ``b8e4be4`` (§6 «Capa C» de la enmienda): (1) la corrida sin paso
``stability`` llega a ``done``; (2) con el paso, los frames son idénticos fila a fila
(``np.array_equal``, no ``approx``: es el mismo motor por la misma llamada), también con columnas
personalizadas y CSI por bins; (2b) ``run_step`` en los tres casos; (3) los ``requires`` los
construye ``Study._resolve_steps`` y nombran lo que se lee de verdad; la receta mínima corre
sobre un ``data.frame`` sin columna temporal y con un scorecard de dirección contraria al default;
la ficha inyectada no es inerte y su dirección es la que se usa; ``check_dataset`` y
``check_pipeline`` acusan antes de ejecutar; (4) los tres ``requires`` ausentes con la clave exacta.
"""

from __future__ import annotations

import subprocess
import sys
import textwrap
from typing import Any

import numpy as np
import pandas as pd
import pytest

import nikodym
from nikodym.core.audit import InMemoryAuditSink
from nikodym.core.config import NikodymConfig, RunConfig
from nikodym.core.dataset_check import check_dataset
from nikodym.core.exceptions import ArtifactNotFoundError, ConfigError
from nikodym.core.steps import METODO_REQUISITOS_RECALCULO, ContextoDeResolucion
from nikodym.core.study import Study
from nikodym.scorecard.results import ScorecardCardSection
from nikodym.stability.config import StabilityConfig, receta_minima_de_recalculo
from nikodym.stability.exceptions import StabilityDataError
from nikodym.validation.config import StabilityValidationConfig, ValidationConfig
from nikodym.validation.results import StabilityRecompute
from nikodym.validation.step import ValidationStep

# ─────────────────────────── fixtures: los artefactos de un scorecard ───────────────────────────

_SCORE = ("scorecard", "score")
_CARD = ("scorecard", "card")
_CALIBRATED = ("calibration", "calibrated_pd_frame")
_DATA = ("data", "frame")
_BINS = ("binning", "bin_frame")
_METRICS = ("stability", "stability_metrics")
_PSI_TABLE = ("stability", "psi_table")


def _index() -> pd.Index:
    return pd.Index(
        [
            *(f"d{i}" for i in range(10)),
            *(f"h{i}" for i in range(10)),
            *(f"o{i}" for i in range(10)),
        ],
        name="loan_id",
    )


def _score_frame(
    *, score_column: str = "score", include_period: bool = False, period_name: str = "period"
) -> pd.DataFrame:
    """``scorecard.score``: score y puntos por característica final; el período sólo si se pide."""
    dev = [float(i) for i in range(1, 11)]
    holdout = [1.0] * 8 + [6.0, 10.0]
    frame = pd.DataFrame(
        {
            score_column: [*dev, *holdout, *dev],
            "f2__points": [
                *([0.0] * 5 + [10.0] * 5),
                *([0.0] * 8 + [10.0] * 2),
                *([0.0] * 5 + [10.0] * 5),
            ],
            "f1__points": [
                *([0.0] * 5 + [10.0] * 5),
                *([0.0] * 6 + [10.0] * 4),
                *([0.0] * 5 + [10.0] * 5),
            ],
        },
        index=_index(),
    )
    if include_period:
        frame[period_name] = ["P0"] * 10 + ["P1"] * 10 + ["P2"] * 10
    return frame


def _calibrated_pd_frame(
    *, partition_column: str = "partition", pd_column: str = "pd_calibrated"
) -> pd.DataFrame:
    return pd.DataFrame(
        {
            partition_column: ["desarrollo"] * 10 + ["holdout"] * 10 + ["oot"] * 10,
            pd_column: [0.10] * 15 + [0.20] * 15,
            "target": [0, 1] * 15,
        },
        index=_index(),
    )


def _data_frame(*, with_period: bool = True, extra_period: str | None = None) -> pd.DataFrame:
    """``data.frame``: sólo aporta la columna temporal; la receta mínima no la necesita."""
    data: dict[str, Any] = {"raw_feature": [float(i) for i in range(30)]}
    if with_period:
        data["period"] = ["P0"] * 10 + ["P1"] * 10 + ["P2"] * 10
    if extra_period is not None:
        data[extra_period] = ["C0"] * 15 + ["C1"] * 15
    return pd.DataFrame(data, index=_index())


def _bin_frame() -> pd.DataFrame:
    """``binning.bin_frame``: los bins congelados de las dos features finales (CSI por bins)."""
    return pd.DataFrame(
        {
            "f1__bin": ["b0"] * 5 + ["b1"] * 5 + ["b0"] * 6 + ["b1"] * 4 + ["b0"] * 5 + ["b1"] * 5,
            "f2__bin": ["b0"] * 5 + ["b1"] * 5 + ["b0"] * 8 + ["b1"] * 2 + ["b0"] * 5 + ["b1"] * 5,
            "otra__bin": ["z"] * 30,
        },
        index=_index(),
    )


def _ficha(direccion: str, *, score_column: str = "score") -> ScorecardCardSection:
    """La ficha del paso ``scorecard``, con la orientación con que construyó el puntaje."""
    return ScorecardCardSection(
        pdo=20.0,
        target_score=600.0,
        target_odds=50.0,
        factor=28.85,
        offset=487.12,
        score_direction=direccion,
        rounding_method="nearest_integer",
        n_variables=2,
        score_column=score_column,
        points_columns=("f1__points", "f2__points"),
        min_score=None,
        max_score=None,
        overrides_count=0,
        dependency_versions={},
    )


def _validation_config(**stability_overrides: Any) -> ValidationConfig:
    """Sólo la familia de estabilidad, con el consumo apagado: la ruta de recálculo."""
    params: dict[str, Any] = {"consume_stability": False}
    params.update(stability_overrides)
    return ValidationConfig(families=("stability",), stability=StabilityValidationConfig(**params))


def _stability_config(**overrides: Any) -> StabilityConfig:
    """Sección ``stability`` con bins chicos para los fixtures sintéticos."""
    params: dict[str, Any] = {"psi_bins": 2, "csi_bins": 2, "include_pd_stability": True}
    params.update(overrides)
    return StabilityConfig(**params)


def _study(
    config: NikodymConfig,
    artifacts: dict[tuple[str, str], Any],
    *,
    sink: InMemoryAuditSink | None = None,
) -> Study:
    study = Study(config)
    if sink is not None:
        study.set_audit_sink(sink)
    for (domain, key), value in artifacts.items():
        study.artifacts.set(domain, key, value)
    return study


def _artefactos_base(**kwargs: Any) -> dict[tuple[str, str], Any]:
    return {
        _SCORE: _score_frame(
            **{k: v for k, v in kwargs.items() if k in ("score_column", "include_period")}
        ),
        _CALIBRATED: _calibrated_pd_frame(
            **{k: v for k, v in kwargs.items() if k in ("partition_column", "pd_column")}
        ),
    }


def _identidad(frame: pd.DataFrame) -> np.ndarray:
    return frame[["metric", "comparison", "feature"]].astype(str).to_numpy()


# ═══════════════ (1) la corrida sin paso de estabilidad llega a done ═══════════════


def test_sin_paso_stability_el_toggle_apagado_recalcula_y_la_tabla_lo_dice() -> None:
    """(1): antes abortaba con el ``ValidationDataError`` del fallback («exige el frame»)."""
    sink = InMemoryAuditSink()
    study = _study(
        NikodymConfig(validation=_validation_config(), run=RunConfig(steps=["validation"])),
        {**_artefactos_base(), _DATA: _data_frame(with_period=False)},
        sink=sink,
    )
    study.run()

    assert study.run_context.status == "done"
    result = study.artifacts.get("validation", "result")
    assert len(result.stability) > 0
    assert set(result.stability["source"]) == {"recomputed"}
    assert set(result.stability["metric"]) == {"score_psi", "pd_psi", "csi"}
    # La receta mínima no produce filas temporales: sin sección declarada no hay eje.
    assert not (result.stability["metric"] == "temporal_score").any()
    section = result.card.metric_sections["validation"]
    assert section["stability_source"] == "recomputed"
    assert section["stability_recompute"] == {
        "recipe": "minimal",
        "temporal_axis": "none",
        "csi_source": "score_points",
    }
    # El trail lo dice: una decisión con la fuente y la receta, hermana de `discrimination_source`.
    decisiones = [
        e
        for e in sink.events
        if e.kind == "decision" and e.payload.get("regla") == "stability_source"
    ]
    assert len(decisiones) == 1
    assert decisiones[0].payload["umbral"] == "stability_artifact"
    assert decisiones[0].payload["valor"] == {
        "source": "recomputed",
        "recipe": "minimal",
        "temporal_axis": "none",
        "csi_source": "score_points",
    }
    assert decisiones[0].payload["accion"] == "reusar_stability_evaluator"


def test_con_el_toggle_encendido_nada_cambia_y_el_trail_no_registra_recalculo() -> None:
    """Control: el consumo sigue exigiendo el artefacto y la card dice ``stability_artifact``."""
    from nikodym.stability.step import compute_stability

    base = {**_artefactos_base(), _DATA: _data_frame()}
    calc = compute_stability(_study(NikodymConfig(), base), _stability_config(temporal_axis="none"))
    sink = InMemoryAuditSink()
    study = _study(
        NikodymConfig(
            validation=_validation_config(consume_stability=True),
            run=RunConfig(steps=["validation"]),
        ),
        {_METRICS: calc.stability_metrics, _PSI_TABLE: calc.psi_table},
        sink=sink,
    )
    study.run()
    result = study.artifacts.get("validation", "result")
    assert set(result.stability["source"]) == {"stability_artifact"}
    section = result.card.metric_sections["validation"]
    assert section["stability_source"] == "stability_artifact"
    assert section["stability_recompute"] is None
    assert not any(e.payload.get("regla") == "stability_source" for e in sink.events)


# ═══════════════ (2) con el paso: el recálculo es el mismo cálculo, fila a fila ═══════════════


@pytest.mark.parametrize(
    ("columnas", "csi_source"),
    [
        ({}, "score_points"),
        (
            {"score_column": "puntaje", "pd_column": "pd_cal", "partition_column": "muestra"},
            "score_points",
        ),
        ({}, "woe_bins"),
        (
            {"score_column": "puntaje", "pd_column": "pd_cal", "partition_column": "muestra"},
            "woe_bins",
        ),
    ],
)
def test_recomputed_es_identico_al_artefacto_del_paso_fila_a_fila(
    columnas: dict[str, str], csi_source: str
) -> None:
    """(2): identidad, cantidad y ``value`` con ``np.array_equal`` — también con columnas
    personalizadas y con el CSI por bins WoE."""
    stability_cfg = _stability_config(csi_source=csi_source, **columnas)
    artifacts = {**_artefactos_base(**columnas), _DATA: _data_frame()}
    if csi_source == "woe_bins":
        artifacts[_BINS] = _bin_frame()
    study = _study(
        NikodymConfig(
            stability=stability_cfg,
            validation=_validation_config(),
            run=RunConfig(steps=["stability", "validation"]),
        ),
        artifacts,
    )
    study.run()

    assert study.run_context.status == "done"
    artefacto = study.artifacts.get(*_METRICS)
    recomputed = study.artifacts.get("validation", "result").stability
    assert len(recomputed) == len(artefacto) > 0
    assert (artefacto["metric"] == "temporal_score").any()  # la sección declarada trae el eje
    if csi_source == "woe_bins":
        assert set(artefacto.loc[artefacto["metric"] == "csi", "feature"]) == {"f1__bin", "f2__bin"}
    assert np.array_equal(_identidad(artefacto), _identidad(recomputed))
    assert np.array_equal(
        artefacto["value"].to_numpy(dtype=float),
        recomputed["value"].to_numpy(dtype=float),
        equal_nan=True,
    )
    assert set(recomputed["source"]) == {"recomputed"}
    section = study.artifacts.get("validation", "card").metric_sections["validation"]
    assert section["stability_recompute"] == {
        "recipe": "declared",
        "temporal_axis": "period",
        "csi_source": csi_source,
    }


# ═══════════ (2b) run_step: la fábrica histórica declara la receta mínima; execute exige ══════════


def test_run_step_sin_seccion_corre_la_receta_minima() -> None:
    study = _study(
        NikodymConfig(validation=_validation_config()),
        {**_artefactos_base(), _DATA: _data_frame(with_period=False)},
    )
    result = study.run_step("validation")
    assert set(result.stability["source"]) == {"recomputed"}
    assert result.card.metric_sections["validation"]["stability_recompute"]["recipe"] == "minimal"


def test_run_step_con_eje_temporal_declarado_y_sin_data_frame_falla_al_entrar_sin_calcular(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """(2b): el error es el de prerequisito con la clave exacta; el evaluador no llega a correr."""
    import nikodym.stability.step as stability_step

    def _no_debe_correr(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("compute_stability corrió con un requires ausente")

    monkeypatch.setattr(stability_step, "compute_stability", _no_debe_correr)
    study = _study(
        NikodymConfig(stability=_stability_config(), validation=_validation_config()),
        _artefactos_base(),
    )
    with pytest.raises(ArtifactNotFoundError, match=r"\('data', 'frame'\)"):
        study.run_step("validation")


def test_run_step_con_woe_bins_declarado_y_sin_bin_frame_falla_al_entrar_sin_calcular(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import nikodym.stability.step as stability_step

    def _no_debe_correr(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("compute_stability corrió con un requires ausente")

    monkeypatch.setattr(stability_step, "compute_stability", _no_debe_correr)
    study = _study(
        NikodymConfig(
            stability=_stability_config(temporal_axis="none", csi_source="woe_bins"),
            validation=_validation_config(),
        ),
        _artefactos_base(),
    )
    with pytest.raises(ArtifactNotFoundError, match=r"\('binning', 'bin_frame'\)"):
        study.run_step("validation")


# ═══════════════ (3) requires construidos por Study._resolve_steps, no a mano ═══════════════


def _requires_resueltos(config: NikodymConfig) -> tuple[tuple[str, str], ...]:
    """Lo que el resolver del núcleo declara para ``validation`` en ESTA invocación."""
    study = Study(config)
    pasos = study._resolve_steps(config.run.steps)
    paso = next(p for p in pasos if p.name == "validation")
    assert isinstance(paso, ValidationStep)
    return paso.requires


def test_requires_con_la_seccion_declarada_nombra_lo_que_el_recalculo_lee() -> None:
    """(3): eje temporal por defecto → ``data.frame``; nunca ``stability.stability_metrics``."""
    requires = _requires_resueltos(
        NikodymConfig(
            stability=_stability_config(),
            validation=_validation_config(),
            run=RunConfig(steps=["validation"]),
        )
    )
    assert requires == (_SCORE, _CALIBRATED, _DATA)
    assert _METRICS not in requires and _PSI_TABLE not in requires


def test_requires_con_eje_none_no_nombra_data_frame_y_con_woe_bins_nombra_bin_frame() -> None:
    sin_eje = _requires_resueltos(
        NikodymConfig(
            stability=_stability_config(temporal_axis="none"),
            validation=_validation_config(),
            run=RunConfig(steps=["validation"]),
        )
    )
    assert sin_eje == (_SCORE, _CALIBRATED)
    con_bins = _requires_resueltos(
        NikodymConfig(
            stability=_stability_config(csi_source="woe_bins"),
            validation=_validation_config(),
            run=RunConfig(steps=["validation"]),
        )
    )
    assert con_bins == (_SCORE, _CALIBRATED, _DATA, _BINS)


def test_requires_sin_seccion_declarada_nombra_solo_la_receta_minima() -> None:
    requires = _requires_resueltos(
        NikodymConfig(validation=_validation_config(), run=RunConfig(steps=["validation"]))
    )
    assert requires == (_SCORE, _CALIBRATED)
    assert requires == receta_minima_de_recalculo().requisitos_de_recalculo_declarados()


def test_los_requires_no_dependen_de_que_stability_corra_sino_de_que_este_declarada() -> None:
    """La sección declarada fuera de ``run.steps`` manda igual: ``execute`` la va a leer."""
    requires = _requires_resueltos(
        NikodymConfig(
            stability=_stability_config(csi_source="woe_bins"),
            validation=_validation_config(),
            run=RunConfig(steps=["validation"]),
        )
    )
    assert _BINS in requires and _DATA in requires


def test_la_receta_minima_corre_sin_columna_temporal_y_con_direccion_contraria_al_default() -> None:
    """(3): los dos casos que antes abortaban tarde; el trail dice que no hubo eje."""
    sink = InMemoryAuditSink()
    study = _study(
        NikodymConfig(validation=_validation_config(), run=RunConfig(steps=["validation"])),
        {
            **_artefactos_base(),
            _DATA: _data_frame(with_period=False),
            _CARD: _ficha("higher_is_higher_risk"),
        },
        sink=sink,
    )
    study.run()
    assert study.run_context.status == "done"
    result = study.artifacts.get("validation", "result")
    assert set(result.stability["source"]) == {"recomputed"}
    decision = next(e.payload for e in sink.events if e.payload.get("regla") == "stability_source")
    assert decision["valor"]["recipe"] == "minimal"
    assert decision["valor"]["temporal_axis"] == "none"


def test_la_direccion_de_la_ficha_es_la_que_usa_la_receta_minima() -> None:
    """Con el default (``higher_is_lower_risk``) la guarda del ensamblador habría detenido la
    corrida ante una ficha contraria: llegar a ``done`` prueba que la receta tomó la de la ficha."""
    from nikodym.validation import step as step_module

    study = _study(
        NikodymConfig(validation=_validation_config()),
        {**_artefactos_base(), _CARD: _ficha("higher_is_higher_risk")},
    )
    cfg, receta = step_module._stability_config_from_study(
        study, score_direction=step_module._direccion_de_la_ficha(study)
    )
    assert receta == "minimal"
    assert cfg.score_direction == "higher_is_higher_risk"
    assert cfg.temporal_axis == "none" and cfg.csi_source == "score_points"
    # Sin ficha, el default; y con una ficha `Mapping` (puerta pública) también se lee.
    assert step_module._direccion_de_la_ficha(_study(NikodymConfig(), {})) is None
    con_dict = _study(NikodymConfig(), {_CARD: {"score_direction": "higher_is_higher_risk"}})
    assert step_module._direccion_de_la_ficha(con_dict) == "higher_is_higher_risk"


@pytest.mark.parametrize("con_seccion", [False, True])
def test_por_la_puerta_publica_la_ficha_inyectada_no_es_inerte_y_su_direccion_se_usa(
    con_seccion: bool,
) -> None:
    """(3): ``nikodym.run(..., artifacts=...)`` con score y ficha y sin paso ``scorecard``, en las
    dos ramas. Control negativo declarado: quitar ``("scorecard","card")`` de ``optional_requires``
    la vuelve inerte y este test se pone rojo."""
    config = NikodymConfig(
        stability=_stability_config(temporal_axis="none", score_direction="higher_is_higher_risk")
        if con_seccion
        else None,
        validation=_validation_config(),
        run=RunConfig(steps=["validation"]),
    )
    artifacts: dict[tuple[str, str], Any] = {
        **_artefactos_base(),
        _CARD: _ficha("higher_is_higher_risk"),
    }
    chequeo = nikodym.check_pipeline(config, artifacts=artifacts)
    assert chequeo.executable, chequeo.message
    assert _CARD not in chequeo.inert_artifacts
    study = nikodym.run(config, artifacts=artifacts)
    assert study.run_context.status == "done", study.run_context.error
    assert _CARD not in study.inert_injected_artifacts
    result = study.artifacts.get("validation", "result")
    assert set(result.stability["source"]) == {"recomputed"}


def test_una_ficha_dict_con_direccion_opuesta_a_la_seccion_declarada_es_config_error() -> None:
    """La guarda lee la ficha con ``campo_de_card``: un ``Mapping`` inyectado no la elude.
    Control negativo declarado: volver a ``getattr`` en ``_require_direccion_coherente`` deja pasar
    la contradicción y este test se pone rojo."""
    config = NikodymConfig(
        stability=_stability_config(temporal_axis="none", score_direction="higher_is_lower_risk"),
        validation=_validation_config(),
        run=RunConfig(steps=["validation"]),
    )
    artifacts: dict[tuple[str, str], Any] = {
        **_artefactos_base(),
        _CARD: {"score_direction": "higher_is_higher_risk"},
    }
    study = nikodym.run(config, artifacts=artifacts)
    assert study.run_context.status == "failed"
    assert study.run_context.error is not None
    assert study.run_context.error.type == "ConfigError"
    assert "contraria" in study.run_context.error.message
    # Y el paso de estabilidad, que comparte la guarda, también la detiene con la ficha `dict`.
    with_step = NikodymConfig(
        stability=_stability_config(temporal_axis="none", score_direction="higher_is_lower_risk"),
        run=RunConfig(steps=["stability"]),
    )
    fallida = nikodym.run(with_step, artifacts=artifacts)
    assert fallida.run_context.status == "failed"
    assert fallida.run_context.error is not None
    assert fallida.run_context.error.type == "ConfigError"


def _config_scorecard_completo(**stability_overrides: Any) -> NikodymConfig:
    """Un config con ``scorecard`` declarado: el preflight conoce así la dirección del score."""
    from nikodym.scorecard.config import ScorecardConfig

    return NikodymConfig(
        scorecard=ScorecardConfig(),
        stability=_stability_config(**stability_overrides),
        validation=_validation_config(),
    )


def test_check_dataset_acusa_la_columna_temporal_ausente_antes_de_ejecutar() -> None:
    """(3), control end-to-end 1/3: con la sección declarada, su propio preflight cubre el eje."""
    chequeo = check_dataset(_config_scorecard_completo(), ["score", "target", "raw_feature"])
    rutas = {m.path for m in chequeo.mismatches if m.kind == "unmet_requirement"}
    assert "stability.temporal_axis" in rutas


def test_check_dataset_acusa_la_columna_temporal_ambigua_antes_de_ejecutar() -> None:
    """Control end-to-end 2/3: dos candidatas y el motor no elige por el usuario."""
    chequeo = check_dataset(_config_scorecard_completo(), ["score", "target", "period", "cohort"])
    rutas = {m.path for m in chequeo.mismatches if m.kind == "unmet_requirement"}
    assert "stability.temporal_column" in rutas


def test_check_dataset_acusa_la_direccion_contraria_antes_de_ejecutar() -> None:
    """Control end-to-end 3/3: la sección describe el puntaje al revés que ``scorecard``."""
    chequeo = check_dataset(
        _config_scorecard_completo(score_direction="higher_is_higher_risk"),
        ["score", "target", "period"],
    )
    rutas = {m.path for m in chequeo.mismatches if m.kind == "unmet_requirement"}
    assert "stability.score_direction" in rutas
    # Control positivo: con la misma dirección, sin aviso.
    limpio = check_dataset(_config_scorecard_completo(), ["score", "target", "period"])
    assert not any(m.path == "stability.score_direction" for m in limpio.mismatches)


def test_check_pipeline_acusa_una_seccion_stability_declarada_e_invalida_sin_ejecutar_nada() -> (
    None
):
    """(3) end-to-end: el estado ``None`` del DTO. La sección llega opaca —un proceso que no
    importó ``nikodym.stability``— e inválida; el resolver la coacciona, falla, la transporta como
    ``None`` y la fábrica contextual se detiene con ``ConfigError`` nombrando ``stability``. Se
    corre en un intérprete fresco porque en éste la sección ya llega tipada y el propio
    ``NikodymConfig`` la rechazaría antes."""
    code = textwrap.dedent(
        """
        import sys
        import pandas as pd
        import nikodym
        from nikodym.core.config import NikodymConfig, RunConfig
        from nikodym.validation.config import StabilityValidationConfig, ValidationConfig
        import nikodym.validation.step as step_module

        assert "nikodym.stability" not in sys.modules
        config = NikodymConfig(
            stability={"psi_stable_threshold": 0.30, "psi_review_threshold": 0.10},
            validation=ValidationConfig(
                families=("stability",),
                stability=StabilityValidationConfig(consume_stability=False),
            ),
            run=RunConfig(steps=["validation"]),
        )
        assert isinstance(config.stability, dict)
        ejecutado = []
        original = step_module.ValidationStep.execute
        step_module.ValidationStep.execute = lambda self, study, rng: ejecutado.append(1)
        idx = pd.Index([f"c{i}" for i in range(6)])
        score = pd.DataFrame({"score": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0]}, index=idx)
        calib = pd.DataFrame(
            {"partition": ["desarrollo"] * 3 + ["holdout"] * 3, "pd_calibrated": [0.1] * 6},
            index=idx,
        )
        chequeo = nikodym.check_pipeline(
            config, artifacts=[("scorecard", "score"), ("calibration", "calibrated_pd_frame")]
        )
        assert not chequeo.executable, chequeo
        assert "stability" in (chequeo.message or ""), chequeo.message
        assert "recálculo" in (chequeo.message or ""), chequeo.message
        study = nikodym.run(
            config,
            artifacts={
                ("scorecard", "score"): score,
                ("calibration", "calibrated_pd_frame"): calib,
            },
        )
        assert study.run_context.status == "failed"
        assert study.run_context.error.type == "ConfigError"
        assert study.run_context.error.step is None  # falló al resolver, antes del primer paso
        assert ejecutado == []
        print("ok")
        """
    )
    completed = subprocess.run(
        [sys.executable, "-c", code], check=False, capture_output=True, text=True, timeout=120
    )
    assert completed.returncode == 0, completed.stderr + completed.stdout
    assert completed.stdout.strip().endswith("ok")


def test_el_dto_transporta_none_para_la_seccion_declarada_e_incoaccionable() -> None:
    """La fábrica contextual distingue los tres estados del DTO (unidad, sin subproceso)."""
    cfg = _validation_config()
    # Ausente → receta mínima.
    ausente = ValidationStep.from_config_with_context(
        cfg, contexto=ContextoDeResolucion(dominios_activos=frozenset({"validation"}))
    )
    assert ausente.requires == (_SCORE, _CALIBRATED)
    # None → ConfigError que nombra la sección y por qué.
    with pytest.raises(ConfigError, match=r"'stability'.*recálculo"):
        ValidationStep.from_config_with_context(
            cfg,
            contexto=ContextoDeResolucion(
                dominios_activos=frozenset({"validation"}),
                requisitos_de_recalculo={"stability": None},
            ),
        )
    # Tupla → lo declarado, tal cual.
    declarado = ValidationStep.from_config_with_context(
        cfg,
        contexto=ContextoDeResolucion(
            dominios_activos=frozenset({"validation"}),
            requisitos_de_recalculo={"stability": (_SCORE, _CALIBRATED, _BINS)},
        ),
    )
    assert declarado.requires == (_SCORE, _CALIBRATED, _BINS)
    # Con el toggle encendido el contexto no cambia nada, ni siquiera el `None`.
    encendido = ValidationStep.from_config_with_context(
        _validation_config(consume_stability=True),
        contexto=ContextoDeResolucion(
            dominios_activos=frozenset({"validation"}),
            requisitos_de_recalculo={"stability": None},
        ),
    )
    assert encendido.requires == (_METRICS, _PSI_TABLE)
    assert encendido.optional_requires == ()


def test_el_nucleo_llena_el_tercer_campo_sobre_las_secciones_declaradas() -> None:
    """``Study._contexto_de_resolucion``: la sección declarada aporta su tupla; ausente, nada; y un
    implementador que sólo mira ``dominios_activos`` no cambia (el DTO es aditivo)."""
    con = Study(
        NikodymConfig(
            stability=_stability_config(csi_source="woe_bins"), validation=_validation_config()
        )
    )._contexto_de_resolucion(frozenset({"validation"}))
    assert dict(con.requisitos_de_recalculo) == {"stability": (_SCORE, _CALIBRATED, _DATA, _BINS)}
    assert con.dominios_activos == frozenset({"validation"})
    sin = Study(NikodymConfig(validation=_validation_config()))._contexto_de_resolucion(
        frozenset({"validation"})
    )
    assert "stability" not in sin.requisitos_de_recalculo
    assert ContextoDeResolucion(dominios_activos=frozenset()).requisitos_de_recalculo == {}
    assert callable(getattr(StabilityConfig, METODO_REQUISITOS_RECALCULO))


def test_el_score_que_ya_trae_la_columna_temporal_corre_con_data_frame_y_no_sin_el() -> None:
    """El límite declarado de CT-1 (§3.2): ``requires`` exige ``data.frame`` con eje temporal
    aunque el ensamblador habría podido leer la columna del score. Positivo y negativo."""
    config = NikodymConfig(
        stability=_stability_config(),
        validation=_validation_config(),
        run=RunConfig(steps=["validation"]),
    )
    con = _study(
        config, {**_artefactos_base(include_period=True), _DATA: _data_frame(with_period=False)}
    )
    con.run()
    assert con.run_context.status == "done"
    tabla = con.artifacts.get("validation", "result").stability
    assert (tabla["metric"] == "temporal_score").any()
    sin = _study(config, _artefactos_base(include_period=True))
    with pytest.raises(ConfigError, match=r"'frame'.*'data'"):
        sin.run()


# ═══════════ (4) los tres requires ausentes, con la clave exacta y antes de ejecutar ═══════════


@pytest.mark.parametrize(
    ("stability_cfg", "artifacts", "clave"),
    [
        (None, {_CALIBRATED: _calibrated_pd_frame()}, ("scorecard", "score")),
        (_stability_config(), _artefactos_base(), ("data", "frame")),
        (
            _stability_config(temporal_axis="none", csi_source="woe_bins"),
            _artefactos_base(),
            ("binning", "bin_frame"),
        ),
    ],
)
def test_check_pipeline_acusa_el_requires_ausente_con_la_clave_exacta(
    stability_cfg: StabilityConfig | None,
    artifacts: dict[tuple[str, str], Any],
    clave: tuple[str, str],
) -> None:
    """(4): antes, el primero moría en el evaluador hablando de un frame que nadie podía dar y los
    otros dos dentro del ensamblador (``StabilityDataError``), tras correr los pasos previos."""
    config = NikodymConfig(
        stability=stability_cfg,
        validation=_validation_config(),
        run=RunConfig(steps=["validation"]),
    )
    chequeo = nikodym.check_pipeline(config, artifacts=list(artifacts))
    assert not chequeo.executable
    assert f"'{clave[1]}'" in (chequeo.message or "") and f"'{clave[0]}'" in (chequeo.message or "")
    study = _study(config, artifacts)
    with pytest.raises(ConfigError, match=f"'{clave[1]}'.*'{clave[0]}'"):
        study.run()
    assert study.run_context.status == "failed"
    assert study.run_context.error is not None
    assert study.run_context.error.type != StabilityDataError.__name__


# ═══════════════ El DTO de la receta y la reconciliación de la card ═══════════════


def test_la_receta_minima_de_la_card_es_cerrada_y_con_su_invariante() -> None:
    StabilityRecompute(recipe="minimal", temporal_axis="none", csi_source="score_points")
    StabilityRecompute(recipe="declared", temporal_axis="period", csi_source="woe_bins")
    with pytest.raises(ValueError, match="receta mínima"):
        StabilityRecompute(recipe="minimal", temporal_axis="period", csi_source="score_points")
    with pytest.raises(ValueError):
        StabilityRecompute(
            recipe="minimal", temporal_axis="none", csi_source="score_points", extra=1
        )  # type: ignore[call-arg]


def test_el_evaluador_rechaza_una_procedencia_que_la_config_no_autorizo() -> None:
    """Sin tercer estado implícito (§3.2-4): consumir con el toggle apagado, o al revés, no vale."""
    from nikodym.validation.evaluator import ValidationEvaluator
    from nikodym.validation.exceptions import ValidationConfigError, ValidationDataError
    from nikodym.validation.stability import evaluate_stability

    metrics = pd.DataFrame(
        {
            "metric": ["score_psi"],
            "comparison": ["dev_vs_holdout"],
            "feature": ["score"],
            "value": [0.01],
        }
    )
    with pytest.raises(ValidationDataError, match="al revés"):
        evaluate_stability(StabilityValidationConfig(), metrics, source="recomputed")
    with pytest.raises(ValidationDataError, match="al revés"):
        evaluate_stability(
            StabilityValidationConfig(consume_stability=False), metrics, source="stability_artifact"
        )
    evaluador = ValidationEvaluator.from_config(_validation_config())
    with pytest.raises(ValidationConfigError, match="si y sólo si"):
        evaluador.validate(stability_metrics=metrics, stability_source="recomputed")
    receta = StabilityRecompute(recipe="minimal", temporal_axis="none", csi_source="score_points")
    with pytest.raises(ValidationConfigError, match="si y sólo si"):
        evaluador.validate(
            stability_metrics=metrics,
            stability_source="stability_artifact",
            stability_recompute=receta,
        )


def test_la_card_y_la_tabla_dicen_la_misma_procedencia() -> None:
    """``ValidationResult`` reconcilia ``source`` ↔ ``stability_source`` ↔ la receta."""
    from nikodym.validation.evaluator import ValidationEvaluator

    metrics = pd.DataFrame(
        {
            "metric": ["score_psi"],
            "comparison": ["dev_vs_holdout"],
            "feature": ["score"],
            "value": [0.01],
        }
    )
    receta = StabilityRecompute(recipe="minimal", temporal_axis="none", csi_source="score_points")
    result = ValidationEvaluator.from_config(_validation_config()).validate(
        stability_metrics=metrics, stability_source="recomputed", stability_recompute=receta
    )
    base = result.model_dump()

    def _rehidrata(**cambios: Any) -> None:
        from nikodym.validation.results import ValidationResult

        payload = dict(base)
        card = dict(payload["card"])
        section = dict(card["metric_sections"]["validation"])
        section.update(cambios)
        card["metric_sections"] = {"validation": section}
        payload["card"] = card
        ValidationResult.model_validate(payload)

    _rehidrata()  # control positivo: la copia coherente vale
    with pytest.raises(ValueError, match="procedencia repetida"):
        _rehidrata(stability_source="stability_artifact", stability_recompute=None)
    with pytest.raises(ValueError, match="stability_recompute"):
        _rehidrata(stability_recompute=None)
    with pytest.raises(ValueError, match="receta inválida"):
        _rehidrata(
            stability_recompute={
                "recipe": "minimal",
                "temporal_axis": "period",
                "csi_source": "score_points",
            }
        )
    with pytest.raises(ValueError, match="stability_source"):
        _rehidrata(stability_source=None)


# ═══════════════ La prosa del informe dice de dónde salió el PSI ═══════════════


def _html_de(result: Any) -> str:
    """La subsección de estabilidad del capítulo «Validación formal» del HTML real."""
    import re
    from datetime import UTC, datetime

    from nikodym.core.lineage import LineageBundle
    from nikodym.report.builder import ReportBuilder
    from nikodym.report.config import ReportConfig
    from nikodym.report.renderer import HtmlReportRenderer
    from nikodym.report.results import ReportInputBundle

    lineage = LineageBundle(
        git_sha="abc123",
        git_dirty=False,
        data_hash="data123456789abcdef",
        config_hash="cfg123456789abcdef",
        root_seed=42,
        uv_lock_hash="uv123",
        library_versions={"nikodym": "1.16.0"},
        determinism_caveats=[],
        created_at=datetime(2026, 9, 15, 12, 0, tzinfo=UTC),
        schema_version="1.0.0",
    )
    cfg = ReportConfig(sections={"missing_policy": "skip"})
    bundle = ReportInputBundle(
        lineage=lineage,
        cards={"validation": result.card.model_dump(mode="python")},
        results={"validation": result},
        tables={"validation.stability": result.stability},
        figures={},
        sections=(),
    )
    bundle = bundle.model_copy(update={"sections": ReportBuilder(cfg).build_sections(bundle)})
    html = HtmlReportRenderer(cfg).render(bundle)
    bloque = re.search(
        r'<section[^>]*id="section-validation-stability"[^>]*>(.*?)</section>', html, re.S
    )
    assert bloque is not None, "el documento no trae la subsección de estabilidad"
    return bloque.group(1)


def _resultado_con_procedencia(source: str, receta: StabilityRecompute | None) -> Any:
    from nikodym.validation.evaluator import ValidationEvaluator

    metrics = pd.DataFrame(
        {
            "metric": ["score_psi"],
            "comparison": ["dev_vs_holdout"],
            "feature": ["score"],
            "value": [0.01],
        }
    )
    cfg = _validation_config(consume_stability=(source == "stability_artifact"))
    return ValidationEvaluator.from_config(cfg).validate(
        stability_metrics=metrics, stability_source=source, stability_recompute=receta
    )


def test_la_prosa_dice_que_el_psi_se_recalculo_con_la_receta_minima() -> None:
    seccion = _html_de(
        _resultado_con_procedencia(
            "recomputed",
            StabilityRecompute(recipe="minimal", temporal_axis="none", csi_source="score_points"),
        )
    )
    assert "Recalculado en esta etapa con el motor de estabilidad" in seccion
    assert "sin eje temporal: la sección de estabilidad no está declarada" in seccion
    assert "Filas evaluadas: 1" in seccion
    assert "recipe" not in seccion and "score_points" not in seccion


def test_la_prosa_dice_que_el_psi_se_recalculo_con_la_seccion_declarada() -> None:
    seccion = _html_de(
        _resultado_con_procedencia(
            "recomputed",
            StabilityRecompute(recipe="declared", temporal_axis="period", csi_source="woe_bins"),
        )
    )
    assert "Recalculado en esta etapa con el motor de estabilidad" in seccion
    assert "con la configuración de la sección de estabilidad" in seccion
    assert "no está declarada" not in seccion


def test_con_el_artefacto_consumido_la_prosa_de_la_familia_sigue_igual() -> None:
    """La demo F1 lleva esta frase byte a byte: con el consumo, nada nuevo."""
    seccion = _html_de(_resultado_con_procedencia("stability_artifact", None))
    assert "Filas evaluadas: 1" in seccion
    assert "Recalculado en esta etapa" not in seccion
    assert "motor de estabilidad" not in seccion


# ═══════════ Límite medido: la sección declarada FUERA de run.steps no se preflightea ═══════════


def test_limite_declarado_la_seccion_fuera_de_run_steps_no_se_preflightea_y_execute_falla_al_entrar(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``check_dataset`` filtra los requisitos por ``run.steps``: con ``stability`` declarada pero
    fuera de la corrida y ``consume_stability=False``, su columna temporal y su dirección no se
    anticipan (medido el 2026-09-15; §3.2 de la enmienda lo afirmaba al revés). Alcanzable sólo por
    código o YAML —``run`` no está en el formulario—. Lo que sí se garantiza: el DAG exige
    ``data.frame`` y el recálculo falla al resolver la columna temporal, con el mensaje del motor
    de estabilidad y **antes** de validar el esquema o calcular un solo PSI. Se pinta aquí para que
    un cambio del preflight lo acuse."""
    import nikodym.stability.evaluator as stability_evaluator

    def _no_debe_llegar(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("el evaluador llegó a validar el esquema sin columna temporal")

    monkeypatch.setattr(stability_evaluator, "_validate_schema", _no_debe_llegar)
    from nikodym.scorecard.config import ScorecardConfig

    config = NikodymConfig(
        scorecard=ScorecardConfig(),
        stability=_stability_config(),  # eje temporal por defecto (`period`)
        validation=_validation_config(),
        run=RunConfig(steps=["validation"]),
    )
    chequeo = check_dataset(config, ["score", "target", "raw_feature"])
    assert not any(m.path.startswith("stability.") for m in chequeo.mismatches)  # el límite
    study = _study(config, {**_artefactos_base(), _DATA: _data_frame(with_period=False)})
    with pytest.raises(StabilityDataError, match="columna de período/cohorte"):
        study.run()
    assert study.run_context.status == "failed"
    assert study.run_context.error is not None and study.run_context.error.step == "validation"
