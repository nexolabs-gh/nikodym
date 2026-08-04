"""Gate de la enmienda DIRECCIÓN-DEL-SCORE (D-DIR-1…9).

🔴 **El defecto que cierra no fallaba: publicaba.** El mismo dato —«un puntaje más alto, ¿es mejor
o peor cliente?»— se declara en tres secciones y cada una se leía por su cuenta. Con la tarjeta
construida en un sentido y el desempeño midiendo en el otro, la corrida llegaba a ``done`` y el
informe publicaba **Gini -0,424** con el validador, ``check_pipeline``, ``check_dataset`` y la
propia corrida los cuatro en verde y **cero avisos**.

⚠️ **Este gate se mide en los DOS sentidos, y el segundo es el caro.** La cara obvia es que la
contradicción se detiene; la simétrica es que **sin tarjeta activa no se detiene nada**, porque
«Validar un modelo existente» trae el puntaje por la puerta de artefactos externos y ahí la
orientación sólo la sabe el usuario. Un gate que midiera sólo la primera se pondría verde con la
feature rota para el trabajo P2.

⚠️ **La corrida de punta a punta NO se mide aquí, y no por comodidad**: ajustar el binning real
dentro de pytest tumba el runner —crash duro del solver de OptBinning al cargar sus binarios
nativos, no un fallo—. Está medida fuera, con su oráculo escrito a mano antes del arreglo, y anclada
en §1.1 de la enmienda: Gini +0,4247 coherente contra **-0,4243** invertido, sobre el preset F1.
"""

from __future__ import annotations

import copy
import dataclasses
from typing import Any

import pytest

from nikodym.core.config import NikodymConfig
from nikodym.core.dataset_check import METODO_CONVENCION_SCORE, ContextoConfig, check_dataset
from nikodym.core.exceptions import ConfigError
from nikodym.performance.config import PerformanceConfig
from nikodym.performance.step import PerformanceStep
from nikodym.scorecard.config import ScorecardConfig
from nikodym.stability.config import StabilityConfig
from nikodym.stability.step import StabilityStep

_INVERSA = "higher_is_higher_risk"
_DIRECTA = "higher_is_lower_risk"

# --------------------------------------------------------------------------------------------
# 1. El contrato del protocolo: quién declara la orientación, y quién sólo la mide
# --------------------------------------------------------------------------------------------


def test_solo_la_seccion_que_construye_el_puntaje_declara_la_orientacion() -> None:
    """`scorecard` fabrica el puntaje y lo declara; `performance` y `stability` sólo lo miden.

    Es el reparto que hace que el dato tenga una sola fuente de verdad. Si una sección que no
    construye el puntaje empezara a declararlo, habría dos declarantes y el desempate de
    `_direccion_del_score` —el primero en orden de campo— decidiría en silencio cuál gana.
    """
    assert callable(getattr(ScorecardConfig(), METODO_CONVENCION_SCORE, None))
    for cfg in (PerformanceConfig(), StabilityConfig()):
        assert not callable(getattr(cfg, METODO_CONVENCION_SCORE, None)), (
            f"{type(cfg).__name__} declara la orientación del puntaje, y no lo construye: "
            "con dos declarantes el desempate lo decide el orden de los campos."
        )


def test_lo_que_declara_scorecard_es_su_propio_campo() -> None:
    """El protocolo no inventa: devuelve el valor que el usuario escribió, sin traducir."""
    for valor in (_DIRECTA, _INVERSA):
        assert ScorecardConfig(score_direction=valor).direccion_del_score_declarada() == valor


def test_el_contexto_transporta_la_orientacion_sin_interpretarla() -> None:
    """El núcleo la lleva como `str` opaco: no conoce el vocabulario del dominio (D-DIR-3)."""
    campos = {campo.name: campo.type for campo in dataclasses.fields(ContextoConfig)}
    assert "direccion_del_score" in campos
    assert "str" in str(campos["direccion_del_score"]), (
        "el contexto anota la orientación con un tipo de dominio: el núcleo pasaría a conocer "
        f"el vocabulario de scorecard ({campos['direccion_del_score']})"
    )


# --------------------------------------------------------------------------------------------
# 2. El aviso PREVIO: cara positiva y cara simétrica
# --------------------------------------------------------------------------------------------


def _requisitos_de_direccion(
    config: NikodymConfig, columnas: tuple[frozenset[str], tuple[str, ...]]
) -> list[str]:
    """Los avisos de orientación que el preflight emite, por su ruta."""
    nombres, indices = columnas
    veredicto = check_dataset(config, nombres, index_columns=indices)
    return [
        m.path
        for m in veredicto.mismatches
        if m.kind == "unmet_requirement" and m.path.endswith("score_direction")
    ]


@pytest.mark.parametrize("seccion", ["performance", "stability"])
def test_el_preflight_avisa_antes_de_correr(
    preset_f1: dict[str, Any], columnas_f1: tuple[frozenset[str], tuple[str, ...]], seccion: str
) -> None:
    """Cara positiva: con la tarjeta activa y la sección al revés, se avisa en la pantalla."""
    crudo = copy.deepcopy(preset_f1)
    crudo[seccion]["score_direction"] = _INVERSA
    config = NikodymConfig.model_validate(crudo)

    assert _requisitos_de_direccion(config, columnas_f1) == [f"{seccion}.score_direction"]


def test_el_preflight_calla_cuando_las_tres_coinciden(
    preset_f1: dict[str, Any], columnas_f1: tuple[frozenset[str], tuple[str, ...]]
) -> None:
    """Un aviso que se dispara de más se aprende a ignorar: el preset de fábrica no lo dispara."""
    config = NikodymConfig.model_validate(copy.deepcopy(preset_f1))
    assert _requisitos_de_direccion(config, columnas_f1) == []


def test_el_preflight_calla_sin_tarjeta_activa(
    preset_f1: dict[str, Any], columnas_f1: tuple[frozenset[str], tuple[str, ...]]
) -> None:
    """🔴 **Cara simétrica.** Sin `scorecard` no hay con qué contradecirse, y el campo manda.

    Es el caso de «Validar un modelo existente» (P2): trae el puntaje ya construido por la puerta
    de artefactos externos y la orientación sólo la sabe quien lo trajo. Avisar aquí sería el falso
    positivo que D-INV-8 documentó, y este gate es lo único que separa «cerramos el defecto» de
    «rompimos el trabajo que no tiene tarjeta».
    """
    crudo = copy.deepcopy(preset_f1)
    for apagada in ("binning", "selection", "model", "scorecard", "calibration"):
        crudo[apagada] = None
    crudo["performance"]["score_direction"] = _INVERSA
    crudo["stability"]["score_direction"] = _INVERSA
    config = NikodymConfig.model_validate(crudo)

    assert _requisitos_de_direccion(config, columnas_f1) == []


def test_el_barrido_del_preflight_no_es_vacuo(
    preset_f1: dict[str, Any], columnas_f1: tuple[frozenset[str], tuple[str, ...]]
) -> None:
    """Un gate que recorre cero da verde y no prueba nada: pasó ya dos veces en este repo."""
    config = NikodymConfig.model_validate(copy.deepcopy(preset_f1))
    assert config.scorecard is not None
    assert config.performance is not None
    assert config.stability is not None
    nombres, _ = columnas_f1
    assert len(nombres) >= 5, f"sólo {len(nombres)} columnas: {sorted(nombres)}"


# --------------------------------------------------------------------------------------------
# 3. La guarda del motor: la contradicción DETIENE, no se descarta en silencio
# --------------------------------------------------------------------------------------------


def test_los_dos_pasos_consumen_la_ficha_sin_exigirla() -> None:
    """`optional_requires` y no `requires` (D-DIR-2): exigirla rompería el trabajo sin tarjeta."""
    for step in (PerformanceStep, StabilityStep):
        assert ("scorecard", "card") in step.optional_requires
        assert ("scorecard", "card") not in step.requires, (
            f"{step.__name__} EXIGE la ficha de la tarjeta: «Validar un modelo existente» inyecta "
            "el puntaje sin ficha y dejaría de resolver."
        )


@pytest.mark.parametrize("seccion", ["performance", "stability"])
@pytest.mark.parametrize("con_ficha", [True, False])
def test_la_guarda_detiene_solo_cuando_hay_ficha_que_contradecir(
    seccion: str, con_ficha: bool
) -> None:
    """Las dos caras de la guarda del motor, sobre el paso real y con la ficha inyectada.

    Cara positiva (`con_ficha=True`): la tarjeta declara una orientación, la sección la contraria,
    y el paso se detiene con `ConfigError` **antes** de calcular nada.

    🔴 Cara simétrica (`con_ficha=False`): sin ficha —el puntaje llegó por la puerta de artefactos
    externos— el mismo config **no** se detiene. Es «Validar un modelo existente», y sin esta mitad
    el gate se pondría verde con el trabajo P2 roto.

    ⚠️ Se ejercita el paso y no `nikodym.run`: **ajustar el binning real dentro de pytest tumba el
    runner** —el solver de OptBinning revienta al cargar sus binarios nativos, crash duro y no
    fallo—, así que la corrida de punta a punta está medida fuera y anclada en §1.1 de la enmienda.
    """
    step, study = _paso_y_study(seccion, direccion=_INVERSA, con_ficha=con_ficha)

    if not con_ficha:
        step.execute(study, _rng())
        return

    with pytest.raises(ConfigError) as exc:
        step.execute(study, _rng())
    assert "score_direction" in str(exc.value)
    assert _DIRECTA in str(exc.value) and _INVERSA in str(exc.value), (
        f"el error tiene que decir las DOS orientaciones para que se sepa cuál cambiar: {exc.value}"
    )


@pytest.mark.parametrize("seccion", ["performance", "stability"])
def test_la_guarda_no_cobra_peaje_cuando_coinciden(seccion: str) -> None:
    """Control de que la guarda no rompe el caso normal: con las dos iguales, el paso corre."""
    step, study = _paso_y_study(seccion, direccion=_DIRECTA, con_ficha=True)
    step.execute(study, _rng())


def test_la_guarda_se_dispara_aunque_el_valor_sea_inerte() -> None:
    """🔴 Se detiene también con la fuente de ranking por defecto, donde el valor no cambia cifras.

    Medido: la orientación de `performance` sólo entra al cálculo con `evaluation_source='score'`.
    Callar en el otro caso dejaría la contradicción escrita y publicada en la ficha del informe,
    lista para volverse mortal en cuanto alguien cambie la fuente con dos clicks — que es el camino
    por el que se llegó al Gini invertido.
    """
    step, study = _paso_y_study(
        "performance", direccion=_INVERSA, con_ficha=True, evaluation_source="pd_calibrated"
    )
    with pytest.raises(ConfigError):
        step.execute(study, _rng())


# --------------------------------------------------------------------------------------------
# Andamiaje del paso: artefactos mínimos, sin pasar por binning
# --------------------------------------------------------------------------------------------


def _rng() -> Any:
    """Los dos pasos son deterministas y descartan el generador, pero el contrato lo exige."""
    import numpy as np

    return np.random.default_rng(0)


def _frame_score() -> Any:
    """El artefacto ``scorecard.score`` mínimo que los dos evaluadores aceptan."""
    import pandas as pd

    return pd.DataFrame(
        {
            "partition": ["desarrollo"] * 4,
            "target": [1, 0, 1, 0],
            "score": [100.0, 200.0, 300.0, 400.0],
        },
        index=pd.Index(["c0", "c1", "c2", "c3"], name="loan_id"),
    )


def _frame_pd_calibrada() -> Any:
    """El artefacto ``calibration.calibrated_pd_frame`` canónico."""
    import pandas as pd

    return pd.DataFrame(
        {
            "partition": ["desarrollo"] * 4,
            "target": [1, 0, 1, 0],
            "pd_calibrated": [0.90, 0.80, 0.70, 0.10],
        },
        index=pd.Index(["c0", "c1", "c2", "c3"], name="loan_id"),
    )


def _ficha_scorecard(direccion: str) -> Any:
    """La ficha que publica el paso `scorecard`, con la orientación con que construyó el puntaje."""
    from nikodym.scorecard.results import ScorecardCardSection

    return ScorecardCardSection(
        pdo=20.0,
        target_score=600.0,
        target_odds=50.0,
        factor=28.85,
        offset=487.12,
        score_direction=direccion,
        rounding_method="nearest_integer",
        n_variables=1,
        score_column="score",
        points_columns=("x__points",),
        min_score=None,
        max_score=None,
        overrides_count=0,
        dependency_versions={},
    )


def _paso_y_study(
    seccion: str,
    *,
    direccion: str,
    con_ficha: bool,
    evaluation_source: str = "score",
) -> tuple[Any, Any]:
    """Monta el paso pedido con sus artefactos upstream, y la ficha sólo si se pide.

    La ficha se inyecta siempre con la orientación **directa**: es la tarjeta la que fija la verdad,
    y `direccion` es lo que la sección declara — que es donde vive la contradicción.
    """
    from nikodym.core.study import Study

    if seccion == "performance":
        cfg = PerformanceConfig(
            partitions=("desarrollo",),
            n_deciles=2,
            min_rows_per_partition=1,
            score_direction=direccion,
            evaluation_source=evaluation_source,
        )
        step: Any = PerformanceStep.from_config(cfg)
        study = Study(NikodymConfig(performance=cfg))
    else:
        cfg_s = StabilityConfig(
            comparisons=("dev_vs_holdout",),
            psi_bins=2,
            csi_bins=2,
            score_direction=direccion,
            temporal_axis="none",
            include_pd_stability=False,
        )
        step = StabilityStep.from_config(cfg_s)
        study = Study(NikodymConfig(stability=cfg_s))

    study.artifacts.set("scorecard", "score", _frame_score())
    study.artifacts.set("calibration", "calibrated_pd_frame", _frame_pd_calibrada())
    if con_ficha:
        study.artifacts.set("scorecard", "card", _ficha_scorecard(_DIRECTA))
    return step, study


# --------------------------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def preset_f1() -> dict[str, Any]:
    """El config del preset F1 tal cual, sin dataset apuntado (basta para el preflight)."""
    presets = pytest.importorskip("nikodym.ui.presets")
    return dict(presets.standard_preset()["config"])


@pytest.fixture(scope="module")
def columnas_f1(tmp_path_factory: pytest.TempPathFactory) -> tuple[frozenset[str], tuple[str, ...]]:
    """Las columnas reales del parquet del catálogo, leídas con el helper del repo.

    ⚠️ Leer el parquet por cuenta propia reintroduce el falso positivo más caro del repo: el esquema
    Arrow lista el índice como una columna más, y el preset saldría incompatible con su propio
    dataset. Por eso se usa `_columnas_del_parquet`, que separa índice de columnas.
    """
    datasets = pytest.importorskip("nikodym.ui.datasets")
    presets = pytest.importorskip("nikodym.ui.presets")
    from nikodym.ui.routes import _columnas_del_parquet

    workdir = tmp_path_factory.mktemp("dir-score")
    ruta = datasets.materialize(presets.standard_preset()["dataset_id"], workdir=workdir)
    columnas, indices = _columnas_del_parquet(ruta)
    return columnas, indices
